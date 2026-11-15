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


def visit_amount(v: dict) -> float:
    """Get the best available amount for a visit (EOB preferred, then statement)."""
    eob = v.get("EOB Amount")
    return _safe_float(eob if eob != "" else v.get("Statement Amount"))


def _providers_match(provider1: str, provider2: str) -> bool:
    """Check if two provider names match (fuzzy - either contains the other).

    Shared with sqlite_client.py so the two storage backends can't silently
    diverge on what counts as a duplicate/match.
    """
    p1 = (provider1 or "").lower()
    p2 = (provider2 or "").lower()
    return p1 in p2 or p2 in p1


def _parse_linked_ids(value: str | int | None) -> list[int]:
    """Parse a pipe-separated string of record IDs into a list of ints.

    Shared with sqlite_client.py - see `_providers_match` above.
    """
    if not value:
        return []
    parsed = []
    for part in str(value).split("|"):
        part = part.strip()
        if not part:
            continue
        try:
            parsed.append(int(part))
        except (ValueError, TypeError):
            continue
    return parsed


REVIEW_STATUS = "Review Status"
REVIEW_PENDING = "Pending"
REVIEW_CONFIRMED = "Confirmed"


def _is_review_confirmed(record: dict) -> bool:
    """Blank (or no such key) means the row predates the Review Status column -
    the owner's hand-entered rows included - so it counts as confirmed. Any other
    value that isn't "Confirmed" (a typo in a hand edit included) stays out of
    totals and is listed as awaiting review until someone fixes it - including
    falsy non-blank cells such as a hand-typed 0, which gspread reads as int 0."""
    value = record.get(REVIEW_STATUS)
    status = "" if value is None else str(value).strip().casefold()
    return status in ("", REVIEW_CONFIRMED.casefold())


def _is_live(record: dict) -> bool:
    return record.get("Disposition", "") == ""


def _is_countable_record(record: dict) -> bool:
    """Shared with sqlite_client.py - see `_providers_match` above.

    "No" -> skip (subordinate/duplicate); unreviewed -> skip; otherwise count.
    """
    return (
        _is_live(record) and record.get("Is Authoritative") != "No" and _is_review_confirmed(record)
    )


def _counts_toward_unreimbursed(record: dict) -> bool:
    return (
        record.get("HSA Eligible") == "Yes"
        and record.get("Reimbursed") != "Yes"
        and _is_countable_record(record)
    )


UNDATED = "undated"
UNASSIGNED = "unassigned"


def service_year(record: dict) -> int | None:
    """Return a plausible four-digit service year, if present."""
    date = record.get("Service Date")
    if not isinstance(date, str) or len(date) < 4:
        return None
    year = date[:4]
    if not year.isascii() or not year.isdigit() or (len(date) > 4 and date[4].isdigit()):
        return None
    value = int(year)
    return value if 1900 <= value <= 2100 else None


def unreimbursed_by_year(records: list[dict]) -> dict[int | str, float]:
    """Sum unreimbursed amounts by service year, including undated records."""
    totals: dict[int | str, float] = {}
    for record in records:
        if _counts_toward_unreimbursed(record):
            key = service_year(record) or UNDATED
            totals[key] = totals.get(key, 0.0) + _safe_float(record.get("Patient Responsibility"))
    return dict(sorted(totals.items(), key=lambda item: (item[0] == UNDATED, item[0])))


def _patient_key(record: dict) -> str:
    return (record.get("Patient") or "").strip() or UNASSIGNED


def unreimbursed_by_patient(records: list[dict]) -> dict[str, float]:
    """Sum unreimbursed amounts by trimmed patient text."""
    totals: dict[str, float] = {}
    for record in records:
        if _counts_toward_unreimbursed(record):
            key = _patient_key(record)
            totals[key] = totals.get(key, 0.0) + _safe_float(record.get("Patient Responsibility"))
    return dict(sorted(totals.items()))


def unreimbursed_by_role(records: list[dict], roles: dict[str, str]) -> dict[str, float]:
    """Sum unreimbursed amounts by configured display role."""
    totals: dict[str, float] = {}
    for record in records:
        if _counts_toward_unreimbursed(record):
            key = roles.get(_patient_key(record), UNASSIGNED)
            totals[key] = totals.get(key, 0.0) + _safe_float(record.get("Patient Responsibility"))
    return dict(sorted(totals.items(), key=lambda item: (item[0] == UNASSIGNED, item[0])))


def review_counts(records: list[dict]) -> dict[str, int]:
    """Count live records by review, authority, eligibility, and reimbursement.

    Counts overlap and do not sum to total. not_eligible includes every record
    whose HSA Eligible is not Yes, including blank values.
    """
    records = [record for record in records if _is_live(record)]
    return {
        "total": len(records),
        "awaiting_review": sum(not _is_review_confirmed(record) for record in records),
        "confirmed": sum(_is_review_confirmed(record) for record in records),
        "countable": sum(_is_countable_record(record) for record in records),
        "not_eligible": sum(record.get("HSA Eligible") != "Yes" for record in records),
        "reimbursed": sum(record.get("Reimbursed") == "Yes" for record in records),
    }


def disposition_counts(records: list[dict]) -> dict[str, int]:
    """Count rejected and excluded records separately."""
    return {
        "rejected": sum(record.get("Disposition") == "Rejected" for record in records),
        "excluded": sum(record.get("Disposition") == "Excluded" for record in records),
    }


def _confirm_delta(record: dict) -> float:
    """What confirming this record adds to the unreimbursed total (a pending "No"
    record adds nothing - it stays subordinate once confirmed)."""
    if _counts_toward_unreimbursed({**record, REVIEW_STATUS: REVIEW_CONFIRMED}):
        return _safe_float(record.get("Patient Responsibility"))
    return 0.0


def _held_by_pending(records: list[dict]) -> list[dict]:
    """ "No" records whose every linked partner is awaiting review.

    Linking happens at ingestion, so a pending EOB matched to a confirmed
    statement takes the statement out of the totals before anyone has reviewed
    the EOB. `_pending_review_summary` keeps only the ones that would otherwise
    count - the records the reader would otherwise see vanish.
    """
    by_id = {str(r.get("ID")): r for r in records if _is_live(r)}
    held = []
    for r in records:
        if not _is_live(r) or r.get("Is Authoritative") != "No":
            continue
        partners = [by_id.get(str(i)) for i in _parse_linked_ids(r.get("Linked Record ID"))]
        if partners and all(p is not None and not _is_review_confirmed(p) for p in partners):
            held.append(r)
    return held


# A receipt is normally filed within a year of the service. A pre-HSA row older than
# that when it was added is more likely a misread year than a genuinely old receipt.
SUSPECT_PRE_HSA_AGE_DAYS = 366


def _suspect_pre_hsa_reason(record: dict) -> str:
    """Why a pre-HSA row's date looks misread, or "" when it is plausible or unknowable.

    The pre-HSA rule is deterministic, but its input is a model-read service date: a
    year read as 2023 instead of 2026 excludes the receipt from every total."""
    if "[Pre-HSA" not in str(record.get("Notes") or ""):
        return ""
    try:
        service = datetime.strptime(str(record.get("Service Date") or "")[:10], "%Y-%m-%d")
        added = datetime.strptime(str(record.get("Date Added") or "")[:10], "%Y-%m-%d")
    except ValueError:
        return ""
    age = (added - service).days
    if age <= SUSPECT_PRE_HSA_AGE_DAYS:
        return ""
    years = age / 365.25
    span = f"{years:.0f} years" if years >= 1.5 else "over a year"
    return f"service date {service:%Y-%m-%d} is {span} before it was added: check the year"


def _needs_eligibility_review(record: dict) -> bool:
    """A "No" nobody has reviewed. HSA Eligible = No silently keeps the amount out
    of every total, and most of these come from the model, not a rule - so until a
    person confirms the row (Review Status = Confirmed, not blank legacy) it is
    listed. A pre-HSA row is listed only when its date looks misread
    (_suspect_pre_hsa_reason); rows that would not count anyway (reimbursed,
    subordinate) are not listed."""
    status = str(record.get(REVIEW_STATUS) or "").strip().casefold()
    pre_hsa = "[Pre-HSA" in str(record.get("Notes") or "")
    return (
        _is_live(record)
        and str(record.get("HSA Eligible") or "").strip() == "No"
        and str(record.get("Reimbursed") or "").strip() != "Yes"
        and record.get("Is Authoritative") != "No"
        and (not pre_hsa or bool(_suspect_pre_hsa_reason(record)))
        and status != REVIEW_CONFIRMED.casefold()
    )


def _eligibility_review_summary(records: list[dict]) -> dict[str, Any]:
    """Records marked not HSA-eligible that nobody has reviewed, and what they hold
    out of Total Unreimbursed if the "No" is wrong."""
    flagged = [r for r in records if _needs_eligibility_review(r)]
    return {
        "count": len(flagged),
        "amount": sum(_safe_float(r.get("Patient Responsibility")) for r in flagged),
        "records": flagged,
    }


AMOUNT_MISMATCH_TAG = "[Amounts do not reconcile"
PATIENT_GUESS_TAG = "[Patient not identified"


def _needs_amount_review(record: dict) -> bool:
    """The extractor's own figures disagreed (its total vs its line items or the
    document's printed total) and no person has confirmed the row since."""
    status = str(record.get(REVIEW_STATUS) or "").strip().casefold()
    return (
        _is_live(record)
        and AMOUNT_MISMATCH_TAG in str(record.get("Notes") or "")
        and status != REVIEW_CONFIRMED.casefold()
    )


def _needs_patient_review(record: dict) -> bool:
    """The document did not show the patient, so the record was filed under the default
    family member, and no person has confirmed it since."""
    status = str(record.get(REVIEW_STATUS) or "").strip().casefold()
    return (
        _is_live(record)
        and PATIENT_GUESS_TAG in str(record.get("Notes") or "")
        and status != REVIEW_CONFIRMED.casefold()
    )


def _patient_review_summary(records: list[dict]) -> dict[str, Any]:
    flagged = [r for r in records if _needs_patient_review(r)]
    return {"count": len(flagged), "records": flagged}


def _amount_review_summary(records: list[dict]) -> dict[str, Any]:
    flagged = [r for r in records if _needs_amount_review(r)]
    return {"count": len(flagged), "records": flagged}


def _pending_review_summary(records: list[dict]) -> dict[str, Any]:
    """Records awaiting review, the exact amount confirming all of them would add
    to the unreimbursed total, and the confirmed records they hold out of it."""
    pending = [r for r in records if _is_live(r) and not _is_review_confirmed(r)]
    # Only records that would otherwise be in the unreimbursed total "left" it.
    held = [
        r
        for r in _held_by_pending(records)
        if _counts_toward_unreimbursed({**r, "Is Authoritative": ""})
    ]
    return {
        "count": len(pending),
        "unreimbursed_amount": sum(_confirm_delta(r) for r in pending),
        "records": pending,
        "held_out_records": held,
        "held_out_amount": sum(_safe_float(r.get("Patient Responsibility")) for r in held),
    }


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
    # Defaults to Pending so a writer that forgets the field is excluded from
    # totals rather than counted. "" is reserved for rows that predate the column.
    review_status: str = REVIEW_PENDING


class DuplicateRecordIdError(ValueError):
    """An ID sits on more than one row, so acting on "the" record would pick one at random."""


def _duplicate_ids(ids: list) -> dict[int, int]:
    counts: dict[int, int] = {}
    for value in ids:
        parsed = GSheetsClient._parse_record_id(value)
        if parsed is not None:
            counts[parsed] = counts.get(parsed, 0) + 1
    return {i: n for i, n in counts.items() if n > 1}


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
        REVIEW_STATUS,  # Pending = not counted until a person confirms it
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
        # Blank is how the reader recognizes rows that predate the column, so a
        # new row must never be written blank - it would count unreviewed.
        if record.review_status not in (REVIEW_PENDING, REVIEW_CONFIRMED):
            raise ValueError(
                f"review_status must be {REVIEW_PENDING!r} or {REVIEW_CONFIRMED!r}, "
                f"got {record.review_status!r}"
            )
        worksheet = self._get_worksheet()

        # Ensure schema has new columns
        self._migrate_schema_if_needed(worksheet)

        all_values = worksheet.get_all_values()
        self._require_review_status_column(all_values[0] if all_values else [])
        # Highest ID + 1, never the row count: once a row is deleted the count
        # lands on an ID still in use, and every by-ID write then hits two rows.
        ids = [self._parse_record_id(r[0]) for r in all_values[1:] if r]
        next_id = max((i for i in ids if i is not None), default=0) + 1

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
            "; ".join(record.notes) if isinstance(record.notes, list) else record.notes,
            # New fields for EOB linking
            record.original_provider or "",
            record.linked_record_id if record.linked_record_id is not None else "",
            "Yes" if record.is_authoritative else ("No" if record.linked_record_id else ""),
            record.review_status,
        ]

        worksheet.append_row(row, value_input_option="USER_ENTERED")
        logger.info(f"Added record ID {next_id}: {record.provider}")
        return next_id

    def _require_review_status_column(self, header_row: list) -> None:
        """add_record writes positionally, and get_all_records() drops any value
        that sits under no header - so a "Pending" written before the column
        exists (or into a shifted column) reads back blank, which counts."""
        index = self.HEADERS.index(REVIEW_STATUS)
        if len(header_row) <= index or header_row[index] != REVIEW_STATUS:
            column = chr(ord("A") + index)
            raise RuntimeError(
                f"The master sheet has no '{REVIEW_STATUS}' header in column {column}; "
                "refusing to write records whose review state would be unreadable. "
                "Run `lazy-hsa migrate-sheet` to preview the fix, then "
                "`lazy-hsa migrate-sheet --apply`."
            )

    def check_review_status_column(self) -> None:
        """Raise RuntimeError unless the sheet can store Review Status (pre-flight)."""
        self._require_review_status_column(self._get_worksheet().row_values(1))

    def migrate_review_status_column(self, apply: bool = False) -> str:
        """Add the Review Status header to an existing master sheet.

        Dry run unless `apply`. Header-only: existing rows keep blank cells (a
        blank Review Status reads as Confirmed), so no existing total changes.
        add_record writes rows positionally, so this refuses unless the current
        header row is a leading slice of HEADERS; any earlier known columns still
        missing (a sheet that predates the EOB-linking columns) are added with it.
        """
        worksheet = self._get_worksheet()
        header_row = worksheet.row_values(1)
        index = self.HEADERS.index(REVIEW_STATUS)
        column = chr(ord("A") + index)

        if REVIEW_STATUS in header_row:
            found = chr(ord("A") + header_row.index(REVIEW_STATUS))
            if found != column:
                raise RuntimeError(
                    f"'{REVIEW_STATUS}' is in column {found}, but rows are written "
                    f"positionally into column {column}. Move it by hand; nothing written."
                )
            return f"'{REVIEW_STATUS}' is already in column {column}; nothing to do."

        target = self.HEADERS[: index + 1]
        if header_row != target[: len(header_row)]:
            raise RuntimeError(
                f"Refusing to migrate: the header row must be a leading slice of {target}, "
                f"found {header_row}. Rows are written positionally, so a renamed, "
                "reordered or extra column would put values under the wrong header."
            )

        missing = target[len(header_row) :]
        first = chr(ord("A") + len(header_row))
        cells = f"{first}1" if first == column else f"{first}1:{column}1"
        names = ", ".join(f"'{name}'" for name in missing)
        data_rows = worksheet.get_all_values()[1:]
        # Values already sitting in an unheaded column are invisible to
        # get_all_records() today; adding the header would turn them into
        # live review statuses (or link/authority values) for legacy rows.
        stray = [
            f"{chr(ord('A') + col)}{row_number}={str(row[col]).strip()!r}"
            for row_number, row in enumerate(data_rows, start=2)
            for col in range(len(header_row), min(len(row), index + 1))
            if str(row[col]).strip()
        ]
        if stray:
            raise RuntimeError(
                f"Refusing to migrate: {len(stray)} cell(s) under the new header(s) already "
                f"hold values ({', '.join(stray[:10])}{', ...' if len(stray) > 10 else ''}). "
                "Clear or move them by hand first; nothing written."
            )
        legacy_rows = len(data_rows)
        plan = (
            f"add {names} at {cells}; the {legacy_rows} existing rows keep a blank "
            "Review Status, which counts as Confirmed"
        )
        if not apply:
            return f"Dry run - would {plan}. Re-run with --apply to write it."

        if worksheet.col_count < index + 1:
            worksheet.resize(cols=index + 1)
        for offset, name in enumerate(missing):
            worksheet.update_acell(f"{chr(ord(first) + offset)}1", name)
        written = worksheet.row_values(1)
        if written != target:
            raise RuntimeError(
                f"Wrote the header but read back {written}, expected {target}; "
                "check the sheet by hand before ingesting."
            )
        return f"Applied: {plan}."

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
        return _providers_match(provider1, provider2)

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
        target = self._parse_record_id(record_id)
        matches = [
            i
            for i, row in enumerate(all_values[1:], start=2)  # Skip header; rows are 1-based
            if row and target is not None and self._parse_record_id(row[0]) == target
        ]
        if len(matches) > 1:
            raise DuplicateRecordIdError(
                f"Record ID {record_id} is on {len(matches)} rows ({matches}); "
                "give each a unique ID in the sheet first"
            )
        if not matches:
            logger.warning(f"Record ID {record_id} not found")
            return False
        target_row = matches[0]

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

        # Checked before any write: the two update_record calls below would
        # otherwise leave a half-made link if the second one refused.
        duplicated = _duplicate_ids([r.get("ID") for r in records])
        for record_id in (eob_id, statement_id):
            if record_id in duplicated:
                raise DuplicateRecordIdError(
                    f"Record ID {record_id} is on {duplicated[record_id]} rows; "
                    "give each a unique ID in the sheet first"
                )

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
        """Check if record should count in totals (see module-level function)."""
        return _is_countable_record(record)

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

    def duplicate_ids(self) -> dict[int, int]:
        """IDs that sit on more than one row, with their row counts."""
        return _duplicate_ids([r.get("ID") for r in self.get_all_records()])

    def get_unreimbursed_total(self) -> float:
        """Calculate total unreimbursed amount, excluding non-authoritative records.

        Records with Is Authoritative = "No" are always excluded, even if
        they haven't been linked yet. This prevents double-counting when
        both a statement and EOB exist for the same service. Records awaiting
        review are excluded too - see `get_pending_review`.
        """
        records = self.get_all_records()
        return sum(
            _safe_float(r.get("Patient Responsibility"))
            for r in records
            if _counts_toward_unreimbursed(r)
        )

    def get_pending_review(self) -> dict[str, Any]:
        """Records awaiting review: count, records, and the amount confirming
        them would add to `get_unreimbursed_total()`."""
        return _pending_review_summary(self.get_all_records())

    def get_confirm_effects(self) -> dict[int, float]:
        """The Sheet stores its flags, so each record's confirm delta is already right."""
        return {
            r["ID"]: _confirm_delta(r)
            for r in self.get_all_records()
            if not _is_review_confirmed(r)
        }

    def get_eligibility_review(self) -> dict[str, Any]:
        """Unreviewed records marked not HSA-eligible (see _needs_eligibility_review)."""
        return _eligibility_review_summary(self.get_all_records())

    def get_amount_review(self) -> dict[str, Any]:
        """Unconfirmed records whose extracted amounts did not reconcile."""
        return _amount_review_summary(self.get_all_records())

    def get_patient_review(self) -> dict[str, Any]:
        """Unconfirmed records filed under the default member because no patient was shown."""
        return _patient_review_summary(self.get_all_records())

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
        return _parse_linked_ids(linked_ids_str)

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
        pending_review_count: int = 0,
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
        rows.append(["Awaiting Review (not counted above)", str(pending_review_count)])

        ws.clear()
        ws.update("A1", rows, value_input_option="USER_ENTERED")

        return self._spreadsheet.url

    # ── Reimbursement View ──────────────────────────────────────────────

    REIMBURSEMENT_HEADERS = [
        "Service Date",
        "Patient",
        "Provider",
        "Category",
        "EOB Amount",
        "Statement Amount",
        "Overbilled?",
        "EOB?",
        "Statement?",
        "Paid?",
        "Ready to Claim?",
        "Claimed?",
        "Gap",
        "EOB Record ID",
        "Statement Record ID",
        "Match Tier",
    ]

    def reconcile_for_reimbursement(
        self, year: int, amount_tolerance: float = 5.0, date_tolerance_days: int = 7
    ) -> list[dict]:
        """Build a per-visit reconciliation by matching EOBs to statements.

        Matching tiers (provider name is NOT used — too unreliable):
          Tier 1: exact (patient, service_date, amount)
          Tier 2: (patient, service_date) with amount ±tolerance
          Tier 3: (patient, amount) with date ±date_tolerance_days

        Returns list of visit dicts ready for the Reimbursement tab.
        """
        records = self.get_all_records()

        eobs: list[dict] = []
        statements: list[dict] = []

        for r in records:
            if not self._matches_year(r, year):
                continue
            if not self._is_countable_record(r):
                continue
            doc_type = r.get("Document Type", "")
            if doc_type == "eob":
                eobs.append(r)
            elif doc_type in ("statement", "receipt", "prescription", "claim"):
                statements.append(r)

        def _parse_date(s: str):
            try:
                return datetime.strptime(s, "%Y-%m-%d")
            except (ValueError, TypeError):
                return None

        # Track which records have been matched
        matched_eob_ids: set[int] = set()
        matched_stmt_ids: set[int] = set()
        visits: list[dict] = []

        def _rid(r):
            return self._parse_record_id(r.get("ID", 0))

        # Tier 1: exact (patient, date, amount)
        stmt_by_key: dict[tuple, list[dict]] = {}
        for s in statements:
            key = (
                s.get("Patient", ""),
                s.get("Service Date", ""),
                round(_safe_float(s.get("Patient Responsibility")), 2),
            )
            stmt_by_key.setdefault(key, []).append(s)

        for e in eobs:
            eid = _rid(e)
            if eid is None or eid in matched_eob_ids:
                continue
            key = (
                e.get("Patient", ""),
                e.get("Service Date", ""),
                round(_safe_float(e.get("Patient Responsibility")), 2),
            )
            candidates = stmt_by_key.get(key, [])
            for s in candidates:
                sid = _rid(s)
                if sid is None or sid in matched_stmt_ids:
                    continue
                visits.append(self._build_visit(e, s, "Tier 1"))
                matched_eob_ids.add(eid)
                matched_stmt_ids.add(sid)
                break

        # Tier 2: (patient, date) with amount ±tolerance
        for e in eobs:
            eid = _rid(e)
            if eid is None or eid in matched_eob_ids:
                continue
            e_amt = _safe_float(e.get("Patient Responsibility"))
            for s in statements:
                sid = _rid(s)
                if sid is None or sid in matched_stmt_ids:
                    continue
                if e.get("Patient", "") != s.get("Patient", ""):
                    continue
                if e.get("Service Date", "") != s.get("Service Date", ""):
                    continue
                s_amt = _safe_float(s.get("Patient Responsibility"))
                if abs(e_amt - s_amt) <= amount_tolerance:
                    visits.append(self._build_visit(e, s, "Tier 2"))
                    matched_eob_ids.add(eid)
                    matched_stmt_ids.add(sid)
                    break

        # Tier 3: (patient, amount) with date ±date_tolerance_days
        # Only match within same category to avoid false positives
        for e in eobs:
            eid = _rid(e)
            if eid is None or eid in matched_eob_ids:
                continue
            e_amt = _safe_float(e.get("Patient Responsibility"))
            e_date = _parse_date(e.get("Service Date", ""))
            e_cat = e.get("Category", "").lower()
            if not e_date:
                continue
            for s in statements:
                sid = _rid(s)
                if sid is None or sid in matched_stmt_ids:
                    continue
                if e.get("Patient", "") != s.get("Patient", ""):
                    continue
                # Require same category for Tier 3 (looser match needs tighter filter)
                s_cat = s.get("Category", "").lower()
                if (e_cat or s_cat) and e_cat != s_cat:
                    continue
                s_amt = _safe_float(s.get("Patient Responsibility"))
                if abs(e_amt - s_amt) > amount_tolerance:
                    continue
                s_date = _parse_date(s.get("Service Date", ""))
                if not s_date:
                    continue
                if abs((e_date - s_date).days) <= date_tolerance_days:
                    visits.append(self._build_visit(e, s, "Tier 3"))
                    matched_eob_ids.add(eid)
                    matched_stmt_ids.add(sid)
                    break

        # Unmatched EOBs (have EOB but no statement)
        for e in eobs:
            eid = _rid(e)
            if eid is None or eid in matched_eob_ids:
                continue
            provider = e.get("Original Provider") or e.get("Provider", "")
            amt = _safe_float(e.get("Patient Responsibility"))
            visits.append(
                {
                    "Service Date": e.get("Service Date", ""),
                    "Patient": e.get("Patient", ""),
                    "Provider": provider,
                    "Category": e.get("Category", ""),
                    "EOB Amount": amt,
                    "Statement Amount": "",
                    "Overbilled?": "",
                    "EOB?": "Yes",
                    "Statement?": "No",
                    "Paid?": "",
                    "Ready to Claim?": "Yes" if amt > 0 else "N/A",
                    "Claimed?": "",
                    "Gap": "",
                    "EOB Record ID": _rid(e),
                    "Statement Record ID": "",
                    "Match Tier": "",
                }
            )

        # Unmatched statements (have statement but no EOB)
        for s in statements:
            sid = _rid(s)
            if sid is None or sid in matched_stmt_ids:
                continue
            amt = _safe_float(s.get("Patient Responsibility"))
            category = s.get("Category", "")
            # Dental/vision/pharmacy may not have EOBs from medical insurer
            needs_eob = category not in ("dental", "vision", "pharmacy")
            visits.append(
                {
                    "Service Date": s.get("Service Date", ""),
                    "Patient": s.get("Patient", ""),
                    "Provider": s.get("Provider", ""),
                    "Category": category,
                    "EOB Amount": "",
                    "Statement Amount": amt,
                    "Overbilled?": "",
                    "EOB?": "No",
                    "Statement?": "Yes",
                    "Paid?": "Yes" if s.get("Document Type") == "receipt" else "",
                    "Ready to Claim?": "Yes" if not needs_eob else "No",
                    "Claimed?": "",
                    "Gap": "Missing EOB" if needs_eob else "",
                    "EOB Record ID": "",
                    "Statement Record ID": sid,
                    "Match Tier": "",
                }
            )

        # Sort by date
        visits.sort(key=lambda v: v.get("Service Date", ""))
        return visits

    def _build_visit(self, eob: dict, stmt: dict, tier: str) -> dict:
        """Build a visit dict from a matched EOB + statement pair."""
        provider = eob.get("Original Provider") or eob.get("Provider", "")
        eob_amt = _safe_float(eob.get("Patient Responsibility"))
        stmt_amt = _safe_float(stmt.get("Patient Responsibility"))
        is_paid = stmt.get("Document Type") == "receipt"
        overbilled = stmt_amt > eob_amt + 0.01  # statement charges more than EOB says

        return {
            "Service Date": eob.get("Service Date", ""),
            "Patient": eob.get("Patient", ""),
            "Provider": provider,
            "Category": eob.get("Category", "") or stmt.get("Category", ""),
            "EOB Amount": eob_amt,
            "Statement Amount": stmt_amt,
            "Overbilled?": f"YES +${stmt_amt - eob_amt:.2f}" if overbilled else "",
            "EOB?": "Yes",
            "Statement?": "Yes",
            "Paid?": "Yes" if is_paid else "",
            "Ready to Claim?": "Yes",
            "Claimed?": "",
            "Gap": "OVERBILLED — call provider" if overbilled else "",
            "EOB Record ID": self._parse_record_id(eob.get("ID", 0)),
            "Statement Record ID": self._parse_record_id(stmt.get("ID", 0)),
            "Match Tier": tier,
        }

    def push_reimbursement_view(self, visits: list[dict]) -> str:
        """Write the reconciled visits to a 'Reimbursement' tab in the spreadsheet.

        Creates or replaces the tab contents. Returns the spreadsheet URL.
        """
        # Get or create the spreadsheet (reuse from main worksheet)
        _ = self._get_worksheet()  # ensures self._spreadsheet is set
        spreadsheet = self._spreadsheet

        # Get or create Reimbursement worksheet
        tab_name = "Reimbursement"
        try:
            ws = spreadsheet.worksheet(tab_name)
            ws.clear()
        except Exception:
            ws = spreadsheet.add_worksheet(
                title=tab_name,
                rows=max(1000, len(visits) + 20),
                cols=len(self.REIMBURSEMENT_HEADERS),
            )

        # Write headers
        ws.update("A1", [self.REIMBURSEMENT_HEADERS])

        if not visits:
            return spreadsheet.url

        # Write data rows
        rows = []
        for v in visits:
            rows.append(
                [
                    v.get("Service Date", ""),
                    v.get("Patient", ""),
                    v.get("Provider", ""),
                    v.get("Category", ""),
                    v.get("EOB Amount", ""),
                    v.get("Statement Amount", ""),
                    v.get("Overbilled?", ""),
                    v.get("EOB?", ""),
                    v.get("Statement?", ""),
                    v.get("Paid?", ""),
                    v.get("Ready to Claim?", ""),
                    v.get("Claimed?", ""),
                    v.get("Gap", ""),
                    v.get("EOB Record ID", ""),
                    v.get("Statement Record ID", ""),
                    v.get("Match Tier", ""),
                ]
            )

        last_col = chr(ord("A") + len(self.REIMBURSEMENT_HEADERS) - 1)
        ws.update(f"A2:{last_col}{len(rows) + 1}", rows)

        # Summary rows
        total_claimable = sum(visit_amount(v) for v in visits if v.get("Ready to Claim?") == "Yes")
        total_pending = sum(visit_amount(v) for v in visits if v.get("Ready to Claim?") == "No")
        total_all = sum(visit_amount(v) for v in visits if v.get("Ready to Claim?") != "N/A")
        overbilled_visits = [v for v in visits if v.get("Overbilled?")]
        total_overbilled = sum(
            _safe_float(v.get("Statement Amount")) - _safe_float(v.get("EOB Amount"))
            for v in overbilled_visits
        )

        summary_row = len(rows) + 3  # skip a blank row
        ws.update(
            f"A{summary_row}",
            [
                ["SUMMARY", "", "", "", f"${total_all:,.2f}"],
                ["Ready to Claim", "", "", "", f"${total_claimable:,.2f}"],
                ["Pending (gaps)", "", "", "", f"${total_pending:,.2f}"],
                [
                    f"OVERBILLED ({len(overbilled_visits)})"
                    if overbilled_visits
                    else "No overbilling detected",
                    "",
                    "",
                    "",
                    f"${total_overbilled:,.2f}" if overbilled_visits else "",
                ],
            ],
        )

        # Bold headers and overbilling
        ws.format("A1:P1", {"textFormat": {"bold": True}})
        ws.format(f"A{summary_row}:A{summary_row + 3}", {"textFormat": {"bold": True}})
        if overbilled_visits:
            ws.format(
                f"A{summary_row + 3}:E{summary_row + 3}",
                {
                    "textFormat": {"bold": True},
                    "backgroundColor": {"red": 1, "green": 0.8, "blue": 0.8},
                },
            )

        logger.info(
            f"Pushed {len(rows)} visits to Reimbursement tab "
            f"(${total_claimable:,.2f} claimable, ${total_pending:,.2f} pending)"
        )
        return spreadsheet.url

    def delete_record(self, record_id: int) -> bool:
        """Delete a record row by ID.

        Args:
            record_id: The ID of the record to delete

        Returns:
            True if deletion succeeded
        """
        worksheet = self._get_worksheet()
        records = worksheet.get_all_records()

        count = _duplicate_ids([r.get("ID") for r in records]).get(record_id)
        if count:
            raise DuplicateRecordIdError(
                f"Record ID {record_id} is on {count} rows; give each a unique ID in the sheet first"
            )
        for i, record in enumerate(records):
            if self._parse_record_id(record.get("ID", 0)) == record_id:
                # Row index is i + 2 (1-indexed, skip header)
                worksheet.delete_rows(i + 2)
                logger.info(f"Deleted record ID {record_id} (row {i + 2})")
                return True

        logger.warning(f"Record ID {record_id} not found for deletion")
        return False


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
        review_status=REVIEW_PENDING,
    )


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "setup":
        creds = sys.argv[2] if len(sys.argv) > 2 else "config/credentials/sheets_credentials.json"
        client = GSheetsClient(credentials_file=creds)
        _ = client._get_worksheet()
        print(f"Spreadsheet URL: {client._spreadsheet.url}")
