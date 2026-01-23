"""Google Sheets Client for HSA Receipt System - manages tracking spreadsheet"""

import contextlib
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from processors.llm_extractor import ExtractedReceipt

logger = logging.getLogger(__name__)


@dataclass
class ReceiptRecord:
    id: int
    date_added: str
    service_date: str
    provider: str
    service_type: str
    patient: str
    category: str
    billed_amount: float
    insurance_paid: float
    patient_responsibility: float
    hsa_eligible: bool
    document_type: str
    file_path: str
    file_link: str
    reimbursed: bool
    reimbursement_date: str
    reimbursement_amount: float
    confidence: float
    notes: str


class GSheetsClient:
    """Google Sheets client for HSA receipt tracking."""

    SCOPES = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.file",  # Needed to create/find spreadsheets
    ]

    HEADERS = [
        "ID",
        "Date Added",
        "Service Date",
        "Provider",
        "Service Type",
        "Patient",
        "Category",
        "Billed Amount",
        "Insurance Paid",
        "Patient Responsibility",
        "HSA Eligible",
        "Document Type",
        "File Path",
        "File Link",
        "Reimbursed",
        "Reimbursement Date",
        "Reimbursement Amount",
        "Confidence",
        "Notes",
    ]

    def __init__(
        self,
        credentials_file: str,
        spreadsheet_name: str = "HSA_Master_Index",
        worksheet_name: str = "Receipts",
        token_file: str = None,
    ):
        self.credentials_file = credentials_file
        self.spreadsheet_name = spreadsheet_name
        self.worksheet_name = worksheet_name
        # Use same token directory as Drive by default
        self.token_file = token_file or credentials_file.replace(
            "gdrive_credentials.json", "gsheets_token.json"
        )
        self._client = None
        self._spreadsheet = None
        self._worksheet = None

    def _get_client(self):
        if self._client is not None:
            return self._client

        from pathlib import Path

        import gspread
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow

        token_path = Path(self.token_file)
        creds = None

        if token_path.exists():
            creds = Credentials.from_authorized_user_file(str(token_path), self.SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(self.credentials_file, self.SCOPES)
                creds = flow.run_local_server(port=0)

            token_path.parent.mkdir(parents=True, exist_ok=True)
            with open(token_path, "w") as f:
                f.write(creds.to_json())

        self._client = gspread.authorize(creds)
        return self._client

    def _get_worksheet(self):
        if self._worksheet is not None:
            return self._worksheet

        client = self._get_client()

        try:
            self._spreadsheet = client.open(self.spreadsheet_name)
        except Exception:
            self._spreadsheet = client.create(self.spreadsheet_name)
            logger.info(f"Created spreadsheet: {self.spreadsheet_name}")

        try:
            self._worksheet = self._spreadsheet.worksheet(self.worksheet_name)
        except Exception:
            self._worksheet = self._spreadsheet.add_worksheet(
                title=self.worksheet_name, rows=1000, cols=len(self.HEADERS)
            )
            self._worksheet.update("A1", [self.HEADERS])
            logger.info(f"Created worksheet: {self.worksheet_name}")

        return self._worksheet

    def add_record(self, record: ReceiptRecord) -> int:
        worksheet = self._get_worksheet()
        all_values = worksheet.get_all_values()
        next_id = len(all_values)

        row = [
            next_id,
            record.date_added or datetime.now().strftime("%Y-%m-%d"),
            record.service_date or "",
            record.provider,
            record.service_type,
            record.patient,
            record.category,
            record.billed_amount,
            record.insurance_paid,
            record.patient_responsibility,
            "Yes" if record.hsa_eligible else "No",
            record.document_type,
            record.file_path,
            record.file_link,
            "Yes" if record.reimbursed else "No",
            record.reimbursement_date or "",
            record.reimbursement_amount or 0,
            f"{record.confidence:.0%}",
            record.notes,
        ]

        worksheet.append_row(row, value_input_option="USER_ENTERED")
        logger.info(f"Added record ID {next_id}: {record.provider}")
        return next_id

    def get_all_records(self) -> list[dict[str, Any]]:
        worksheet = self._get_worksheet()
        return worksheet.get_all_records()

    def find_duplicates(
        self,
        provider: str,
        service_date: str,
        amount: float,
        tolerance: float = 0.01,
    ) -> list[dict[str, Any]]:
        """Find potential duplicate records by matching provider, date, and amount.

        This helps detect when both a hospital bill and EOB are uploaded for the
        same service. They should be linked rather than counted twice.

        Args:
            provider: Provider name to match (fuzzy - checks if either contains the other)
            service_date: Service date in YYYY-MM-DD format
            amount: Patient responsibility amount
            tolerance: Amount tolerance for matching (default $0.01)

        Returns:
            List of matching records
        """
        records = self.get_all_records()
        matches = []
        provider_lower = provider.lower()

        for record in records:
            # Check date match
            if record.get("Service Date") != service_date:
                continue

            # Check provider match (fuzzy - either contains the other)
            record_provider = (record.get("Provider") or "").lower()
            if not (provider_lower in record_provider or record_provider in provider_lower):
                continue

            # Check amount match (within tolerance)
            try:
                record_amount = float(record.get("Patient Responsibility", 0))
                if abs(record_amount - amount) > tolerance:
                    continue
            except (ValueError, TypeError):
                continue

            matches.append(record)

        return matches

    def get_unreimbursed_total(self) -> float:
        records = self.get_all_records()
        total = 0.0
        for record in records:
            if record.get("HSA Eligible") == "Yes" and record.get("Reimbursed") != "Yes":
                with contextlib.suppress(ValueError, TypeError):
                    total += float(record.get("Patient Responsibility", 0))
        return total

    def get_summary_by_year(self) -> dict[int, dict[str, float]]:
        records = self.get_all_records()
        summary = {}

        for record in records:
            try:
                service_date = record.get("Service Date", "")
                if not service_date:
                    continue
                year = int(service_date[:4])

                if year not in summary:
                    summary[year] = {
                        "total_billed": 0,
                        "total_insurance": 0,
                        "total_responsibility": 0,
                        "total_reimbursed": 0,
                        "count": 0,
                    }

                summary[year]["count"] += 1
                summary[year]["total_billed"] += float(record.get("Billed Amount", 0) or 0)
                summary[year]["total_insurance"] += float(record.get("Insurance Paid", 0) or 0)
                summary[year]["total_responsibility"] += float(
                    record.get("Patient Responsibility", 0) or 0
                )

                if record.get("Reimbursed") == "Yes":
                    summary[year]["total_reimbursed"] += float(
                        record.get("Reimbursement Amount", 0) or 0
                    )
            except (ValueError, TypeError):
                pass

        return summary


def create_record_from_extraction(
    extraction: "ExtractedReceipt", file_path: str, file_link: str
) -> ReceiptRecord:
    return ReceiptRecord(
        id=0,
        date_added=datetime.now().strftime("%Y-%m-%d"),
        service_date=extraction.service_date or "",
        provider=extraction.provider_name,
        service_type=extraction.service_type,
        patient=extraction.patient_name,
        category=extraction.category,
        billed_amount=extraction.billed_amount,
        insurance_paid=extraction.insurance_paid,
        patient_responsibility=extraction.patient_responsibility,
        hsa_eligible=extraction.hsa_eligible,
        document_type=extraction.document_type,
        file_path=file_path,
        file_link=file_link,
        reimbursed=False,
        reimbursement_date="",
        reimbursement_amount=0,
        confidence=extraction.confidence_score,
        notes=extraction.notes,
    )


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "setup":
        creds = sys.argv[2] if len(sys.argv) > 2 else "config/credentials/sheets_credentials.json"
        client = GSheetsClient(credentials_file=creds)
        _ = client._get_worksheet()
        print(f"Spreadsheet URL: {client._spreadsheet.url}")
