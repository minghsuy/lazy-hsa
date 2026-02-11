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

    @staticmethod
    def _matches_year(record: dict, year: int) -> bool:
        """Check if a record's service date falls in the given year."""
        service_date = record.get("Service Date", "")
        if not service_date:
            return False
        try:
            return int(service_date[:4]) == year
        except (ValueError, TypeError):
            return False

    @staticmethod
    def _parse_record_id(value) -> int | None:
        """Parse a record ID to int, returning None on failure."""
        try:
            return int(value)
        except (ValueError, TypeError):
            return None

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

    def get_oop_progress(self, year: int) -> dict[str, float]:
        """Get out-of-pocket spending progress for a given year.

        Sums Patient Responsibility for countable, HSA-eligible records.
        """
        records = self.get_all_records()
        total_oop = sum(
            _safe_float(r.get("Patient Responsibility"))
            for r in records
            if self._is_countable_record(r)
            and r.get("HSA Eligible") == "Yes"
            and self._matches_year(r, year)
        )
        return {"total_oop": total_oop}

    def get_oop_breakdown_by_patient(self, year: int) -> list[dict]:
        """Get per-patient OOP spending breakdown for a given year.

        Groups Patient Responsibility by patient for countable, HSA-eligible records.
        Returns list sorted by total_oop descending.
        """
        records = self.get_all_records()
        by_patient: dict[str, float] = {}

        for r in records:
            if (
                self._is_countable_record(r)
                and r.get("HSA Eligible") == "Yes"
                and self._matches_year(r, year)
            ):
                patient = r.get("Patient", "Unknown")
                by_patient[patient] = by_patient.get(patient, 0.0) + _safe_float(
                    r.get("Patient Responsibility")
                )

        return sorted(
            [{"patient": p, "total_oop": t} for p, t in by_patient.items()],
            key=lambda x: x["total_oop"],
            reverse=True,
        )

    def suggest_record_links(
        self, year: int, date_tolerance_days: int = 7
    ) -> dict[str, list[dict]]:
        """Suggest links between unmatched EOBs and statements.

        Matches on same patient + fuzzy provider + date within tolerance.
        Uses Original Provider on EOBs for provider matching.

        Confidence tiers:
          - exact date = high (3 stars)
          - ≤3 days = medium (2 stars)
          - ≤7 days (or tolerance) = low (1 star)
        """
        from datetime import datetime  # noqa: F811

        unmatched = self.get_unmatched_records(year)
        eob_suggestions: list[dict] = []
        stmt_suggestions: list[dict] = []

        def _parse_date(date_str: str) -> datetime | None:
            try:
                return datetime.strptime(date_str, "%Y-%m-%d")
            except (ValueError, TypeError):
                return None

        def _find_matches(source: dict, candidates: list[dict], use_original_provider: bool):
            source_patient = source.get("Patient", "")
            source_provider = (
                source.get("Original Provider") or source.get("Provider", "")
                if use_original_provider
                else source.get("Provider", "")
            )
            source_date = _parse_date(source.get("Service Date", ""))
            if not source_date or not source_patient:
                return []

            matches = []
            for candidate in candidates:
                if candidate.get("Patient", "") != source_patient:
                    continue
                cand_provider = candidate.get("Provider", "")
                if not self._providers_match(source_provider, cand_provider):
                    continue
                cand_date = _parse_date(candidate.get("Service Date", ""))
                if not cand_date:
                    continue
                diff_days = abs((source_date - cand_date).days)
                if diff_days > date_tolerance_days:
                    continue

                if diff_days == 0:
                    confidence, stars = "high", 3
                elif diff_days <= 3:
                    confidence, stars = "medium", 2
                else:
                    confidence, stars = "low", 1

                matches.append(
                    {
                        "record_id": candidate.get("ID", ""),
                        "provider": cand_provider,
                        "service_date": candidate.get("Service Date", ""),
                        "amount": _safe_float(candidate.get("Patient Responsibility")),
                        "date_diff_days": diff_days,
                        "confidence": confidence,
                        "stars": stars,
                    }
                )

            matches.sort(key=lambda m: (m["date_diff_days"], -m["amount"]))
            return matches

        # EOBs looking for matching statements
        for eob in unmatched["unmatched_eobs"]:
            matches = _find_matches(
                eob, unmatched["unmatched_statements"], use_original_provider=True
            )
            if matches:
                eob_suggestions.append({"record": eob, "matches": matches})

        # Statements looking for matching EOBs
        for stmt in unmatched["unmatched_statements"]:
            matches = _find_matches(stmt, unmatched["unmatched_eobs"], use_original_provider=False)
            if matches:
                stmt_suggestions.append({"record": stmt, "matches": matches})

        return {
            "eob_suggestions": eob_suggestions,
            "statement_suggestions": stmt_suggestions,
        }

    def get_unmatched_records(self, year: int) -> dict[str, list[dict]]:
        """Find records without matching counterparts for a given year.

        Unmatched statements: non-EOB, no Linked Record ID, not non-authoritative.
        Unmatched EOBs: EOB type, no Linked Record ID.
        """
        records = self.get_all_records()
        unmatched_statements = []
        unmatched_eobs = []

        for record in records:
            if not self._matches_year(record, year):
                continue
            if record.get("Linked Record ID"):
                continue

            if record.get("Document Type") == "eob":
                unmatched_eobs.append(record)
            elif record.get("Is Authoritative") != "No":
                unmatched_statements.append(record)

        return {
            "unmatched_statements": unmatched_statements,
            "unmatched_eobs": unmatched_eobs,
        }

    @staticmethod
    def _parse_linked_ids(linked_ids_str: str | int | None) -> list[int]:
        """Parse a pipe-separated string of record IDs into a list of ints."""
        if not linked_ids_str:
            return []
        parsed = []
        for part in str(linked_ids_str).split("|"):
            part = part.strip()
            if not part:
                continue
            try:
                parsed.append(int(part))
            except (ValueError, TypeError):
                continue
        return parsed

    def get_linked_variances(self, year: int) -> list[dict]:
        """Find amount variances between linked EOB and statement pairs.

        Looks for authoritative records with linked IDs, compares Patient
        Responsibility amounts, reports differences > $0.01.
        """
        records = self.get_all_records()
        records_by_id: dict[int, dict] = {}
        for r in records:
            record_id = self._parse_record_id(r.get("ID", 0))
            if record_id is not None:
                records_by_id[record_id] = r

        variances = []
        seen_pairs: set[tuple[int, int]] = set()

        for record in records:
            if record.get("Is Authoritative") != "Yes":
                continue
            if not self._matches_year(record, year):
                continue

            linked_ids = self._parse_linked_ids(record.get("Linked Record ID"))
            if not linked_ids:
                continue

            eob_id = self._parse_record_id(record.get("ID", 0))
            if eob_id is None:
                continue
            eob_amount = _safe_float(record.get("Patient Responsibility"))

            for linked_id in linked_ids:
                pair = (min(eob_id, linked_id), max(eob_id, linked_id))
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)

                linked_record = records_by_id.get(linked_id)
                if not linked_record:
                    continue

                stmt_amount = _safe_float(linked_record.get("Patient Responsibility"))
                variance = eob_amount - stmt_amount

                if abs(variance) > 0.01:
                    variances.append(
                        {
                            "eob_id": eob_id,
                            "statement_id": linked_id,
                            "eob_amount": eob_amount,
                            "statement_amount": stmt_amount,
                            "variance": variance,
                            "provider": record.get("Provider", ""),
                            "patient": record.get("Patient", ""),
                            "service_date": record.get("Service Date", ""),
                        }
                    )

        return variances

    def push_reconciliation_summary(
        self,
        year: int,
        oop_progress: float,
        oop_max: float,
        patient_breakdown: list[dict],
        unmatched_counts: dict[str, int],
        variance_count: int,
    ) -> str:
        """Push reconciliation summary to a Reconciliation worksheet.

        Gets or creates a 'Reconciliation' worksheet in the existing spreadsheet.
        Clears and rewrites all content each time.

        Returns the spreadsheet URL.
        """
        from datetime import datetime  # noqa: F811

        # Ensure spreadsheet is initialized via _get_worksheet()
        self._get_worksheet()

        try:
            ws = self._spreadsheet.worksheet("Reconciliation")
        except Exception:
            ws = self._spreadsheet.add_worksheet(title="Reconciliation", rows=100, cols=6)

        pct = (oop_progress / oop_max * 100) if oop_max > 0 else 0

        rows = [
            [f"HSA Reconciliation — {year}"],
            [f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}"],
            [],
            ["Out-of-Pocket Summary"],
            ["Total OOP", f"${oop_progress:,.2f}"],
            ["OOP Max", f"${oop_max:,.2f}"],
            ["Progress", f"{pct:.0f}%"],
            ["Remaining", f"${max(0, oop_max - oop_progress):,.2f}"],
            [],
            ["Per-Patient Breakdown"],
            ["Patient", "Total OOP", "% of Max"],
        ]

        for entry in patient_breakdown:
            p_pct = (entry["total_oop"] / oop_max * 100) if oop_max > 0 else 0
            rows.append([entry["patient"], f"${entry['total_oop']:,.2f}", f"{p_pct:.1f}%"])

        rows.append([])
        rows.append(["Reconciliation Status"])
        rows.append(["Unmatched Statements", str(unmatched_counts.get("statements", 0))])
        rows.append(["Unmatched EOBs", str(unmatched_counts.get("eobs", 0))])
        rows.append(["Amount Variances", str(variance_count)])

        ws.clear()
        ws.update("A1", rows, value_input_option="USER_ENTERED")

        return self._spreadsheet.url


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
