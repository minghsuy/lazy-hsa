"""Google Sheets Client for HSA Receipt System - manages tracking spreadsheet"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from processors.llm_extractor import ExtractedReceipt

logger = logging.getLogger(__name__)


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Safely convert a value to float, returning default on failure."""
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


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
    # New fields for EOB linking (Phase 4)
    original_provider: str = ""  # For EOBs: who actually provided the service
    linked_record_id: str | None = None  # Pipe-separated IDs for linked records (e.g., "17|18")
    is_authoritative: bool = False  # "Yes" for authoritative EOBs, "No" for linked subordinate records, "" for standalone


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
        # New columns for EOB linking (columns T, U, V)
        "Original Provider",  # For EOBs: who rendered the service
        "Linked Record ID",  # Bidirectional link between EOB and statement
        "Is Authoritative",  # Yes = use this record's amount for reimbursement
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

        # Ensure schema has new columns
        self._migrate_schema_if_needed(worksheet)

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
            # New fields for EOB linking
            record.original_provider or "",
            record.linked_record_id if record.linked_record_id is not None else "",
            "Yes" if record.is_authoritative else ("No" if record.linked_record_id else ""),
        ]

        worksheet.append_row(row, value_input_option="USER_ENTERED")
        logger.info(f"Added record ID {next_id}: {record.provider}")
        return next_id

    def _migrate_schema_if_needed(self, worksheet) -> None:
        """Add new columns if they don't exist (backward compatibility)."""
        header_row = worksheet.row_values(1)
        new_columns = ["Original Provider", "Linked Record ID", "Is Authoritative"]

        # Check which columns are missing
        missing = [col for col in new_columns if col not in header_row]

        if missing:
            # First, expand the sheet if needed
            current_cols = worksheet.col_count
            needed_cols = len(header_row) + len(missing)
            if current_cols < needed_cols:
                worksheet.resize(cols=needed_cols)
                logger.info(f"Expanded sheet from {current_cols} to {needed_cols} columns")

            # Add missing columns to header row
            start_col = len(header_row) + 1
            for i, col_name in enumerate(missing):
                col_letter = chr(ord("A") + start_col - 1 + i)
                worksheet.update_acell(f"{col_letter}1", col_name)
                logger.info(f"Added new column: {col_name}")

    def _providers_match(self, provider1: str, provider2: str) -> bool:
        """Check if two provider names match (fuzzy - either contains the other)."""
        p1 = provider1.lower()
        p2 = provider2.lower()
        return p1 in p2 or p2 in p1

    def update_record(self, record_id: int, updates: dict[str, Any]) -> bool:
        """Update specific fields of a record by ID.

        Args:
            record_id: The ID of the record to update
            updates: Dict of column name -> new value

        Returns:
            True if update succeeded, False otherwise
        """
        worksheet = self._get_worksheet()
        header_row = worksheet.row_values(1)

        # Find the row for this record ID
        all_values = worksheet.get_all_values()
        target_row = None
        for i, row in enumerate(all_values[1:], start=2):  # Skip header, row numbers start at 1
            if row and str(row[0]) == str(record_id):
                target_row = i
                break

        if target_row is None:
            logger.warning(f"Record ID {record_id} not found")
            return False

        # Update each field
        for col_name, value in updates.items():
            if col_name in header_row:
                col_index = header_row.index(col_name) + 1
                col_letter = chr(ord("A") + col_index - 1)
                cell = f"{col_letter}{target_row}"
                worksheet.update_acell(cell, value)
                logger.debug(f"Updated {cell} ({col_name}) = {value}")

        logger.info(f"Updated record ID {record_id}")
        return True

    def get_all_records(self) -> list[dict[str, Any]]:
        worksheet = self._get_worksheet()
        return worksheet.get_all_records()

    def find_matching_statements(
        self,
        service_date: str,
        patient: str,
        provider_pattern: str,
    ) -> list[dict[str, Any]]:
        """Find statement records that match an EOB claim.

        Used when processing EOBs to link them to existing statement records.
        Matches on: service date + patient + provider name (fuzzy).

        Args:
            service_date: Service date in YYYY-MM-DD format
            patient: Patient name (exact match)
            provider_pattern: Provider name pattern (fuzzy - checks if contained)

        Returns:
            List of matching statement records, sorted by ID descending (newest first)
        """
        records = self.get_all_records()
        matches = []

        for record in records:
            # Skip if already an EOB or already linked
            if record.get("Document Type") == "eob":
                continue
            if record.get("Linked Record ID"):
                continue

            # Check date, patient, and provider match
            if record.get("Service Date") != service_date:
                continue
            if record.get("Patient") != patient:
                continue
            if not self._providers_match(provider_pattern, record.get("Provider") or ""):
                continue

            matches.append(record)

        # Sort by ID descending (newest first)
        matches.sort(key=lambda r: int(r.get("ID", 0)), reverse=True)
        return matches

    @staticmethod
    def _append_link_id(existing: str | int | None, new_id: int) -> str:
        """Append a linked ID to an existing pipe-separated list, avoiding duplicates."""
        if not existing:
            return str(new_id)
        existing_ids = {s.strip() for s in str(existing).split("|")}
        if str(new_id) in existing_ids:
            return str(existing)
        return f"{existing}|{new_id}"

    def link_records(self, eob_id: int, statement_id: int) -> bool:
        """Link an EOB record to a statement record bidirectionally.

        When linked:
        - EOB is marked as authoritative (use its amount for reimbursement)
        - Statement gets linked_record_id pointing to EOB
        - Notes updated with variance if amounts differ
        - Supports multiple links (pipe-separated IDs)

        Args:
            eob_id: ID of the EOB record
            statement_id: ID of the statement record

        Returns:
            True if linking succeeded
        """
        records = self.get_all_records()

        # Find both records in a single pass
        records_by_id = {int(r.get("ID", 0)): r for r in records}
        eob_record = records_by_id.get(eob_id)
        statement_record = records_by_id.get(statement_id)

        if not eob_record or not statement_record:
            logger.warning(f"Could not find both records: EOB {eob_id}, Statement {statement_id}")
            return False

        # Calculate variance for notes
        eob_amount = _safe_float(eob_record.get("Patient Responsibility"))
        stmt_amount = _safe_float(statement_record.get("Patient Responsibility"))
        variance = eob_amount - stmt_amount
        variance_note = f"[Variance: ${variance:+.2f} vs statement]" if abs(variance) > 0.01 else ""

        # Update EOB: mark authoritative, append link to statement
        eob_notes = eob_record.get("Notes") or ""
        if variance_note:
            eob_notes = f"{variance_note} {eob_notes}".strip()

        self.update_record(
            eob_id,
            {
                "Linked Record ID": self._append_link_id(
                    eob_record.get("Linked Record ID"), statement_id
                ),
                "Is Authoritative": "Yes",
                "Notes": eob_notes,
            },
        )

        # Update statement: append link to EOB, not authoritative
        stmt_notes = statement_record.get("Notes") or ""
        link_note = f"[Linked to EOB #{eob_id}]"
        if link_note not in stmt_notes:
            stmt_notes = f"{link_note} {stmt_notes}".strip()

        self.update_record(
            statement_id,
            {
                "Linked Record ID": self._append_link_id(
                    statement_record.get("Linked Record ID"), eob_id
                ),
                "Is Authoritative": "No",
                "Notes": stmt_notes,
            },
        )

        logger.info(f"Linked EOB #{eob_id} <-> Statement #{statement_id}")
        return True

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

        for record in records:
            # Check date and provider match
            if record.get("Service Date") != service_date:
                continue
            if not self._providers_match(provider, record.get("Provider") or ""):
                continue

            # Check amount match (within tolerance)
            record_amount = _safe_float(record.get("Patient Responsibility"))
            if abs(record_amount - amount) > tolerance:
                continue

            matches.append(record)

        return matches

    @staticmethod
    def _is_countable_record(record: dict) -> bool:
        """Check if record should count in totals.

        "No" -> skip (subordinate/duplicate)
        "Yes" or "" -> count
        """
        return record.get("Is Authoritative") != "No"

    def get_unreimbursed_total(self) -> float:
        """Calculate total unreimbursed amount, excluding non-authoritative records.

        Records with Is Authoritative = "No" are always excluded, even if
        they haven't been linked yet. This prevents double-counting when
        both a statement and EOB exist for the same service.
        """
        records = self.get_all_records()
        return sum(
            _safe_float(r.get("Patient Responsibility"))
            for r in records
            if r.get("HSA Eligible") == "Yes"
            and r.get("Reimbursed") != "Yes"
            and self._is_countable_record(r)
        )

    def get_summary_by_year(self) -> dict[int, dict[str, float]]:
        """Get summary by year, excluding non-authoritative records.

        Records with Is Authoritative = "No" are always excluded, even if
        they haven't been linked yet. This prevents double-counting when
        both a statement and EOB exist for the same service.
        """
        records = self.get_all_records()
        summary = {}

        for record in records:
            service_date = record.get("Service Date", "")
            if not service_date:
                continue

            if not self._is_countable_record(record):
                continue

            try:
                year = int(service_date[:4])
            except (ValueError, TypeError):
                continue

            if year not in summary:
                summary[year] = {
                    "total_billed": 0,
                    "total_insurance": 0,
                    "total_responsibility": 0,
                    "total_reimbursed": 0,
                    "count": 0,
                }

            summary[year]["count"] += 1
            summary[year]["total_billed"] += _safe_float(record.get("Billed Amount"))
            summary[year]["total_insurance"] += _safe_float(record.get("Insurance Paid"))
            summary[year]["total_responsibility"] += _safe_float(
                record.get("Patient Responsibility")
            )

            if record.get("Reimbursed") == "Yes":
                summary[year]["total_reimbursed"] += _safe_float(record.get("Reimbursement Amount"))

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
