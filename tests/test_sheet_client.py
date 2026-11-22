"""Tests for sheet_client.py - summary and filtering logic."""

from unittest.mock import MagicMock, patch

import pytest

from src.storage.sheet_client import (
    DuplicateRecordIdError,
    GSheetsClient,
    ReceiptRecord,
    _needs_eligibility_review,
    _safe_float,
    _suspect_pre_hsa_reason,
)

LEGACY_HEADERS = GSheetsClient.HEADERS[: GSheetsClient.HEADERS.index("Review Status")]


class TestSafeFloat:
    def test_normal_float(self):
        assert _safe_float(3.14) == 3.14

    def test_string_number(self):
        assert _safe_float("42.5") == 42.5

    def test_none_returns_zero(self):
        assert _safe_float(None) == 0.0

    def test_empty_string_returns_zero(self):
        assert _safe_float("") == 0.0

    def test_invalid_string_returns_zero(self):
        assert _safe_float("not a number") == 0.0


class TestIsCountableRecord:
    def test_authoritative_yes(self):
        assert GSheetsClient._is_countable_record({"Is Authoritative": "Yes"}) is True

    def test_authoritative_no(self):
        assert GSheetsClient._is_countable_record({"Is Authoritative": "No"}) is False

    def test_authoritative_no_without_link(self):
        """The bug: auth=No but no linked ID should still be excluded."""
        record = {"Is Authoritative": "No", "Linked Record ID": ""}
        assert GSheetsClient._is_countable_record(record) is False

    def test_authoritative_empty(self):
        """Standalone records (empty auth) are always counted."""
        assert GSheetsClient._is_countable_record({"Is Authoritative": ""}) is True

    def test_authoritative_missing(self):
        assert GSheetsClient._is_countable_record({}) is True


def _make_client():
    """Create a GSheetsClient without calling __init__ (no credentials needed)."""
    return GSheetsClient.__new__(GSheetsClient)


class TestGetUnreimbursedTotal:
    @pytest.fixture
    def client(self):
        return _make_client()

    def _sample_records(self):
        return [
            # Standalone receipt - counted
            {
                "Patient Responsibility": "100.00",
                "HSA Eligible": "Yes",
                "Reimbursed": "No",
                "Linked Record ID": "",
                "Is Authoritative": "",
            },
            # Authoritative EOB (linked) - counted
            {
                "Patient Responsibility": "200.00",
                "HSA Eligible": "Yes",
                "Reimbursed": "No",
                "Linked Record ID": "3",
                "Is Authoritative": "Yes",
            },
            # Non-authoritative linked - skipped
            {
                "Patient Responsibility": "200.00",
                "HSA Eligible": "Yes",
                "Reimbursed": "No",
                "Linked Record ID": "2",
                "Is Authoritative": "No",
            },
            # Non-authoritative but NOT linked (the bug) - skipped
            {
                "Patient Responsibility": "410.00",
                "HSA Eligible": "Yes",
                "Reimbursed": "No",
                "Linked Record ID": "",
                "Is Authoritative": "No",
            },
            # Already reimbursed - skipped
            {
                "Patient Responsibility": "50.00",
                "HSA Eligible": "Yes",
                "Reimbursed": "Yes",
                "Linked Record ID": "",
                "Is Authoritative": "",
            },
            # Not HSA eligible - skipped
            {
                "Patient Responsibility": "75.00",
                "HSA Eligible": "No",
                "Reimbursed": "No",
                "Linked Record ID": "",
                "Is Authoritative": "",
            },
        ]

    def test_excludes_non_authoritative_without_link(self, client):
        with patch.object(client, "get_all_records", return_value=self._sample_records()):
            total = client.get_unreimbursed_total()
        # Only $100 (standalone) + $200 (auth EOB) = $300
        assert total == pytest.approx(300.00)

    def test_standalone_record_counted(self, client):
        records = [
            {
                "Patient Responsibility": "150.00",
                "HSA Eligible": "Yes",
                "Reimbursed": "No",
                "Linked Record ID": "",
                "Is Authoritative": "",
            },
        ]
        with patch.object(client, "get_all_records", return_value=records):
            assert client.get_unreimbursed_total() == pytest.approx(150.00)


class TestGetSummaryByYear:
    @pytest.fixture
    def client(self):
        return _make_client()

    def test_excludes_non_authoritative_without_link(self, client):
        records = [
            {
                "Service Date": "2026-03-15",
                "Patient Responsibility": "100.00",
                "Billed Amount": "300.00",
                "Insurance Paid": "200.00",
                "Reimbursed": "No",
                "Reimbursement Amount": "0",
                "Linked Record ID": "",
                "Is Authoritative": "",
            },
            # Non-auth unlinked (should be skipped)
            {
                "Service Date": "2026-04-01",
                "Patient Responsibility": "410.00",
                "Billed Amount": "410.00",
                "Insurance Paid": "0",
                "Reimbursed": "No",
                "Reimbursement Amount": "0",
                "Linked Record ID": "",
                "Is Authoritative": "No",
            },
        ]
        with patch.object(client, "get_all_records", return_value=records):
            summary = client.get_summary_by_year()
        assert summary[2026]["total_responsibility"] == pytest.approx(100.00)
        assert summary[2026]["count"] == 1

    def test_counts_authoritative_linked(self, client):
        records = [
            {
                "Service Date": "2026-01-10",
                "Patient Responsibility": "85.07",
                "Billed Amount": "200.00",
                "Insurance Paid": "114.93",
                "Reimbursed": "No",
                "Reimbursement Amount": "0",
                "Linked Record ID": "3",
                "Is Authoritative": "Yes",
            },
            {
                "Service Date": "2026-01-10",
                "Patient Responsibility": "85.07",
                "Billed Amount": "200.00",
                "Insurance Paid": "114.93",
                "Reimbursed": "No",
                "Reimbursement Amount": "0",
                "Linked Record ID": "2",
                "Is Authoritative": "No",
            },
        ]
        with patch.object(client, "get_all_records", return_value=records):
            summary = client.get_summary_by_year()
        # Only the authoritative record counted
        assert summary[2026]["total_responsibility"] == pytest.approx(85.07)
        assert summary[2026]["count"] == 1


class TestGetOopProgress:
    @pytest.fixture
    def client(self):
        return _make_client()

    def test_sums_countable_hsa_eligible(self, client):
        records = [
            {
                "Service Date": "2026-03-15",
                "Patient Responsibility": "100.00",
                "HSA Eligible": "Yes",
                "Is Authoritative": "",
            },
            {
                "Service Date": "2026-06-01",
                "Patient Responsibility": "250.50",
                "HSA Eligible": "Yes",
                "Is Authoritative": "Yes",
            },
        ]
        with patch.object(client, "get_all_records", return_value=records):
            result = client.get_oop_progress(2026)
        assert result["total_oop"] == pytest.approx(350.50)

    def test_skips_non_authoritative(self, client):
        records = [
            {
                "Service Date": "2026-03-15",
                "Patient Responsibility": "100.00",
                "HSA Eligible": "Yes",
                "Is Authoritative": "No",
            },
        ]
        with patch.object(client, "get_all_records", return_value=records):
            result = client.get_oop_progress(2026)
        assert result["total_oop"] == pytest.approx(0.0)

    def test_skips_wrong_year(self, client):
        records = [
            {
                "Service Date": "2025-12-15",
                "Patient Responsibility": "500.00",
                "HSA Eligible": "Yes",
                "Is Authoritative": "",
            },
        ]
        with patch.object(client, "get_all_records", return_value=records):
            result = client.get_oop_progress(2026)
        assert result["total_oop"] == pytest.approx(0.0)

    def test_skips_non_eligible(self, client):
        records = [
            {
                "Service Date": "2026-03-15",
                "Patient Responsibility": "75.00",
                "HSA Eligible": "No",
                "Is Authoritative": "",
            },
        ]
        with patch.object(client, "get_all_records", return_value=records):
            result = client.get_oop_progress(2026)
        assert result["total_oop"] == pytest.approx(0.0)

    def test_empty_records(self, client):
        with patch.object(client, "get_all_records", return_value=[]):
            result = client.get_oop_progress(2026)
        assert result["total_oop"] == pytest.approx(0.0)


class TestGetUnmatchedRecords:
    @pytest.fixture
    def client(self):
        return _make_client()

    def test_finds_standalone_statements(self, client):
        records = [
            {
                "ID": "1",
                "Service Date": "2026-02-01",
                "Document Type": "statement",
                "Linked Record ID": "",
                "Is Authoritative": "",
                "Provider": "Sutter",
            },
        ]
        with patch.object(client, "get_all_records", return_value=records):
            result = client.get_unmatched_records(2026)
        assert len(result["unmatched_statements"]) == 1
        assert result["unmatched_statements"][0]["ID"] == "1"

    def test_finds_unlinked_eobs(self, client):
        records = [
            {
                "ID": "5",
                "Service Date": "2026-03-01",
                "Document Type": "eob",
                "Linked Record ID": "",
                "Is Authoritative": "Yes",
                "Provider": "Aetna",
            },
        ]
        with patch.object(client, "get_all_records", return_value=records):
            result = client.get_unmatched_records(2026)
        assert len(result["unmatched_eobs"]) == 1
        assert result["unmatched_eobs"][0]["ID"] == "5"

    def test_skips_linked_records(self, client):
        records = [
            {
                "ID": "2",
                "Service Date": "2026-01-10",
                "Document Type": "statement",
                "Linked Record ID": "3",
                "Is Authoritative": "No",
                "Provider": "Sutter",
            },
            {
                "ID": "3",
                "Service Date": "2026-01-10",
                "Document Type": "eob",
                "Linked Record ID": "2",
                "Is Authoritative": "Yes",
                "Provider": "Aetna",
            },
        ]
        with patch.object(client, "get_all_records", return_value=records):
            result = client.get_unmatched_records(2026)
        assert len(result["unmatched_statements"]) == 0
        assert len(result["unmatched_eobs"]) == 0

    def test_filters_by_year(self, client):
        records = [
            {
                "ID": "1",
                "Service Date": "2025-11-01",
                "Document Type": "statement",
                "Linked Record ID": "",
                "Is Authoritative": "",
                "Provider": "Stanford",
            },
        ]
        with patch.object(client, "get_all_records", return_value=records):
            result = client.get_unmatched_records(2026)
        assert len(result["unmatched_statements"]) == 0
        assert len(result["unmatched_eobs"]) == 0


class TestGetLinkedVariances:
    @pytest.fixture
    def client(self):
        return _make_client()

    def test_detects_variance(self, client):
        records = [
            {
                "ID": "3",
                "Service Date": "2026-01-15",
                "Patient Responsibility": "175.00",
                "Is Authoritative": "Yes",
                "Linked Record ID": "4",
                "Provider": "Aetna",
                "Patient": "Alice",
            },
            {
                "ID": "4",
                "Service Date": "2026-01-15",
                "Patient Responsibility": "185.00",
                "Is Authoritative": "No",
                "Linked Record ID": "3",
                "Provider": "Sutter",
                "Patient": "Alice",
            },
        ]
        with patch.object(client, "get_all_records", return_value=records):
            result = client.get_linked_variances(2026)
        assert len(result) == 1
        assert result[0]["eob_id"] == 3
        assert result[0]["statement_id"] == 4
        assert result[0]["variance"] == pytest.approx(-10.00)

    def test_no_variance_when_amounts_match(self, client):
        records = [
            {
                "ID": "5",
                "Service Date": "2026-02-01",
                "Patient Responsibility": "200.00",
                "Is Authoritative": "Yes",
                "Linked Record ID": "6",
                "Provider": "Aetna",
                "Patient": "Bob",
            },
            {
                "ID": "6",
                "Service Date": "2026-02-01",
                "Patient Responsibility": "200.00",
                "Is Authoritative": "No",
                "Linked Record ID": "5",
                "Provider": "Stanford",
                "Patient": "Bob",
            },
        ]
        with patch.object(client, "get_all_records", return_value=records):
            result = client.get_linked_variances(2026)
        assert len(result) == 0

    def test_handles_pipe_separated_ids(self, client):
        records = [
            {
                "ID": "10",
                "Service Date": "2026-03-01",
                "Patient Responsibility": "300.00",
                "Is Authoritative": "Yes",
                "Linked Record ID": "11|12",
                "Provider": "Aetna",
                "Patient": "Alice",
            },
            {
                "ID": "11",
                "Service Date": "2026-03-01",
                "Patient Responsibility": "290.00",
                "Is Authoritative": "No",
                "Linked Record ID": "10",
                "Provider": "Sutter",
                "Patient": "Alice",
            },
            {
                "ID": "12",
                "Service Date": "2026-03-01",
                "Patient Responsibility": "300.00",
                "Is Authoritative": "No",
                "Linked Record ID": "10",
                "Provider": "Sutter",
                "Patient": "Alice",
            },
        ]
        with patch.object(client, "get_all_records", return_value=records):
            result = client.get_linked_variances(2026)
        # Only one variance (ID 10 vs 11, diff=$10), ID 10 vs 12 matches
        assert len(result) == 1
        assert result[0]["variance"] == pytest.approx(10.00)


class TestGetOopBreakdownByPatient:
    @pytest.fixture
    def client(self):
        return _make_client()

    def test_groups_by_patient(self, client):
        records = [
            {
                "Service Date": "2026-01-15",
                "Patient Responsibility": "100.00",
                "Patient": "Alice",
                "HSA Eligible": "Yes",
                "Is Authoritative": "",
            },
            {
                "Service Date": "2026-02-20",
                "Patient Responsibility": "250.00",
                "Patient": "Bob",
                "HSA Eligible": "Yes",
                "Is Authoritative": "",
            },
            {
                "Service Date": "2026-03-10",
                "Patient Responsibility": "50.00",
                "Patient": "Alice",
                "HSA Eligible": "Yes",
                "Is Authoritative": "Yes",
            },
        ]
        with patch.object(client, "get_all_records", return_value=records):
            result = client.get_oop_breakdown_by_patient(2026)
        assert len(result) == 2
        assert result[0]["patient"] == "Bob"
        assert result[0]["total_oop"] == pytest.approx(250.00)
        assert result[1]["patient"] == "Alice"
        assert result[1]["total_oop"] == pytest.approx(150.00)

    def test_sorts_descending(self, client):
        records = [
            {
                "Service Date": "2026-01-01",
                "Patient Responsibility": "10.00",
                "Patient": "Charlie",
                "HSA Eligible": "Yes",
                "Is Authoritative": "",
            },
            {
                "Service Date": "2026-01-01",
                "Patient Responsibility": "500.00",
                "Patient": "Alice",
                "HSA Eligible": "Yes",
                "Is Authoritative": "",
            },
        ]
        with patch.object(client, "get_all_records", return_value=records):
            result = client.get_oop_breakdown_by_patient(2026)
        assert result[0]["patient"] == "Alice"
        assert result[1]["patient"] == "Charlie"

    def test_skips_non_authoritative(self, client):
        records = [
            {
                "Service Date": "2026-05-01",
                "Patient Responsibility": "200.00",
                "Patient": "Alice",
                "HSA Eligible": "Yes",
                "Is Authoritative": "No",
            },
        ]
        with patch.object(client, "get_all_records", return_value=records):
            result = client.get_oop_breakdown_by_patient(2026)
        assert len(result) == 0

    def test_skips_non_eligible(self, client):
        records = [
            {
                "Service Date": "2026-05-01",
                "Patient Responsibility": "75.00",
                "Patient": "Bob",
                "HSA Eligible": "No",
                "Is Authoritative": "",
            },
        ]
        with patch.object(client, "get_all_records", return_value=records):
            result = client.get_oop_breakdown_by_patient(2026)
        assert len(result) == 0

    def test_skips_wrong_year(self, client):
        records = [
            {
                "Service Date": "2025-12-15",
                "Patient Responsibility": "300.00",
                "Patient": "Alice",
                "HSA Eligible": "Yes",
                "Is Authoritative": "",
            },
        ]
        with patch.object(client, "get_all_records", return_value=records):
            result = client.get_oop_breakdown_by_patient(2026)
        assert len(result) == 0

    def test_empty_records(self, client):
        with patch.object(client, "get_all_records", return_value=[]):
            result = client.get_oop_breakdown_by_patient(2026)
        assert result == []


class TestSuggestRecordLinks:
    @pytest.fixture
    def client(self):
        return _make_client()

    def _unmatched_eobs(self):
        return [
            {
                "ID": "10",
                "Service Date": "2026-01-06",
                "Provider": "Aetna",
                "Original Provider": "Sutter",
                "Patient": "Alice",
                "Patient Responsibility": "185.00",
                "Document Type": "eob",
                "Linked Record ID": "",
                "Is Authoritative": "Yes",
            },
        ]

    def _unmatched_stmts(self):
        return [
            {
                "ID": "4",
                "Service Date": "2026-01-06",
                "Provider": "Sutter Health",
                "Patient": "Alice",
                "Patient Responsibility": "185.00",
                "Document Type": "statement",
                "Linked Record ID": "",
                "Is Authoritative": "",
            },
        ]

    def test_exact_date_high_confidence(self, client):
        with patch.object(
            client,
            "get_unmatched_records",
            return_value={
                "unmatched_eobs": self._unmatched_eobs(),
                "unmatched_statements": self._unmatched_stmts(),
            },
        ):
            result = client.suggest_record_links(2026)
        assert len(result["eob_suggestions"]) == 1
        match = result["eob_suggestions"][0]["matches"][0]
        assert match["confidence"] == "high"
        assert match["stars"] == 3
        assert match["date_diff_days"] == 0

    def test_date_within_3d_medium_confidence(self, client):
        stmts = self._unmatched_stmts()
        stmts[0]["Service Date"] = "2026-01-08"  # 2 days off
        with patch.object(
            client,
            "get_unmatched_records",
            return_value={
                "unmatched_eobs": self._unmatched_eobs(),
                "unmatched_statements": stmts,
            },
        ):
            result = client.suggest_record_links(2026)
        assert len(result["eob_suggestions"]) == 1
        match = result["eob_suggestions"][0]["matches"][0]
        assert match["confidence"] == "medium"
        assert match["stars"] == 2

    def test_beyond_tolerance_no_match(self, client):
        stmts = self._unmatched_stmts()
        stmts[0]["Service Date"] = "2026-01-20"  # 14 days off
        with patch.object(
            client,
            "get_unmatched_records",
            return_value={
                "unmatched_eobs": self._unmatched_eobs(),
                "unmatched_statements": stmts,
            },
        ):
            result = client.suggest_record_links(2026)
        assert len(result["eob_suggestions"]) == 0

    def test_different_patient_no_match(self, client):
        stmts = self._unmatched_stmts()
        stmts[0]["Patient"] = "Bob"
        with patch.object(
            client,
            "get_unmatched_records",
            return_value={
                "unmatched_eobs": self._unmatched_eobs(),
                "unmatched_statements": stmts,
            },
        ):
            result = client.suggest_record_links(2026)
        assert len(result["eob_suggestions"]) == 0

    def test_provider_mismatch_no_match(self, client):
        stmts = self._unmatched_stmts()
        stmts[0]["Provider"] = "Stanford"
        with patch.object(
            client,
            "get_unmatched_records",
            return_value={
                "unmatched_eobs": self._unmatched_eobs(),
                "unmatched_statements": stmts,
            },
        ):
            result = client.suggest_record_links(2026)
        assert len(result["eob_suggestions"]) == 0

    def test_empty_records_empty_result(self, client):
        with patch.object(
            client,
            "get_unmatched_records",
            return_value={"unmatched_eobs": [], "unmatched_statements": []},
        ):
            result = client.suggest_record_links(2026)
        assert result["eob_suggestions"] == []
        assert result["statement_suggestions"] == []


class TestPushReconciliationSummary:
    @pytest.fixture
    def client(self):
        c = _make_client()
        # Mock the spreadsheet and worksheet infrastructure
        mock_ws = MagicMock()
        mock_spreadsheet = MagicMock()
        mock_spreadsheet.url = "https://docs.google.com/spreadsheets/d/abc123"
        mock_spreadsheet.worksheet.return_value = mock_ws
        c._spreadsheet = mock_spreadsheet
        c._worksheet = MagicMock()  # So _get_worksheet() short-circuits
        return c

    def test_writes_to_existing_worksheet(self, client):
        ws = client._spreadsheet.worksheet.return_value
        url = client.push_reconciliation_summary(
            year=2026,
            oop_progress=3500.00,
            oop_max=6000,
            patient_breakdown=[
                {"patient": "Alice", "total_oop": 2000.00},
                {"patient": "Bob", "total_oop": 1500.00},
            ],
            unmatched_counts={"statements": 2, "eobs": 1},
            variance_count=3,
        )
        ws.clear.assert_called_once()
        ws.update.assert_called_once()
        rows = ws.update.call_args[0][1]
        assert rows[0] == ["HSA Reconciliation \u2014 2026"]
        assert url == "https://docs.google.com/spreadsheets/d/abc123"

    def test_creates_worksheet_on_missing(self, client):
        client._spreadsheet.worksheet.side_effect = Exception("not found")
        new_ws = MagicMock()
        client._spreadsheet.add_worksheet.return_value = new_ws

        client.push_reconciliation_summary(
            year=2026,
            oop_progress=0,
            oop_max=6000,
            patient_breakdown=[],
            unmatched_counts={"statements": 0, "eobs": 0},
            variance_count=0,
        )
        client._spreadsheet.add_worksheet.assert_called_once_with(
            title="Reconciliation", rows=100, cols=6
        )
        new_ws.clear.assert_called_once()
        new_ws.update.assert_called_once()

    def test_content_structure(self, client):
        ws = client._spreadsheet.worksheet.return_value
        client.push_reconciliation_summary(
            year=2026,
            oop_progress=1200.50,
            oop_max=6000,
            patient_breakdown=[{"patient": "Alice", "total_oop": 1200.50}],
            unmatched_counts={"statements": 1, "eobs": 0},
            variance_count=2,
        )
        rows = ws.update.call_args[0][1]
        # Check OOP summary values
        assert ["Total OOP", "$1,200.50"] in rows
        assert ["OOP Max", "$6,000.00"] in rows
        assert ["Progress", "20%"] in rows
        # Check patient row
        assert ["Alice", "$1,200.50", "20.0%"] in rows
        # Check reconciliation status
        assert ["Unmatched Statements", "1"] in rows
        assert ["Unmatched EOBs", "0"] in rows
        assert ["Amount Variances", "2"] in rows

    def test_reports_records_awaiting_review(self, client):
        ws = client._spreadsheet.worksheet.return_value
        client.push_reconciliation_summary(
            year=2026,
            oop_progress=0,
            oop_max=6000,
            patient_breakdown=[],
            unmatched_counts={"statements": 0, "eobs": 0},
            variance_count=0,
            pending_review_count=3,
        )
        rows = ws.update.call_args[0][1]
        assert ["Awaiting Review (not counted above)", "3"] in rows


def _receipt(**overrides) -> ReceiptRecord:
    """A ReceiptRecord with review_status left to the dataclass default."""
    defaults = {
        "id": 0,
        "date_added": "2026-02-01",
        "service_date": "2026-02-01",
        "provider": "CVS Pharmacy",
        "service_type": "Prescription",
        "patient": "Alice",
        "category": "pharmacy",
        "billed_amount": 40.0,
        "insurance_paid": 0.0,
        "patient_responsibility": 40.0,
        "hsa_eligible": True,
        "document_type": "receipt",
        "file_path": "HSA_Receipts/2026/Pharmacy/Alice/receipt.pdf",
        "file_link": "",
        "reimbursed": False,
        "reimbursement_date": "",
        "reimbursement_amount": 0,
        "confidence": 0.9,
        "notes": "",
    }
    defaults.update(overrides)
    return ReceiptRecord(**defaults)


def _legacy_row(**values) -> list:
    """A row as it sits in a sheet written before the Review Status column existed."""
    base = {
        "Service Date": "2026-01-05",
        "Provider": "Sutter Health",
        "Patient": "Alice",
        "Category": "medical",
        "Patient Responsibility": 100.0,
        "HSA Eligible": "Yes",
        "Document Type": "statement",
        "Reimbursed": "No",
        "Is Authoritative": "",
    }
    base.update(values)
    return [base.get(h, "") for h in LEGACY_HEADERS]


class TestReviewStatusCountable:
    def test_pending_excluded(self):
        assert GSheetsClient._is_countable_record({"Review Status": "Pending"}) is False

    def test_pending_authoritative_eob_excluded(self):
        record = {"Is Authoritative": "Yes", "Review Status": "Pending"}
        assert GSheetsClient._is_countable_record(record) is False

    def test_confirmed_counted(self):
        assert GSheetsClient._is_countable_record({"Review Status": "Confirmed"}) is True

    def test_confirmed_subordinate_still_excluded(self):
        record = {"Is Authoritative": "No", "Review Status": "Confirmed"}
        assert GSheetsClient._is_countable_record(record) is False

    def test_legacy_blank_counted(self):
        assert GSheetsClient._is_countable_record({"Review Status": ""}) is True

    def test_hand_edit_case_and_whitespace_counted(self):
        assert GSheetsClient._is_countable_record({"Review Status": " confirmed "}) is True

    def test_unknown_value_fails_closed(self):
        assert GSheetsClient._is_countable_record({"Review Status": "Confirmd"}) is False

    @pytest.mark.parametrize("value", [0, False])
    def test_falsy_non_blank_value_fails_closed(self, value):
        """gspread reads a hand-typed 0 as int 0; it is not a blank legacy cell."""
        assert GSheetsClient._is_countable_record({"Review Status": value}) is False


class TestReviewStatusWriter:
    def test_record_defaults_to_pending(self):
        assert _receipt().review_status == "Pending"

    def test_add_record_writes_pending_under_its_header_and_excludes_it(self, sheets_client):
        client = sheets_client()
        client.add_record(_receipt(patient_responsibility=40.0))

        row = client._worksheet.rows[0]
        assert row[GSheetsClient.HEADERS.index("Review Status")] == "Pending"
        assert client.get_all_records()[0]["Review Status"] == "Pending"
        assert client.get_unreimbursed_total() == pytest.approx(0.0)
        assert client.get_summary_by_year() == {}
        pending = client.get_pending_review()
        assert pending["count"] == 1
        assert pending["unreimbursed_amount"] == pytest.approx(40.0)

    @pytest.mark.parametrize("amount,cell", [(None, ""), (0, 0), (12.5, 12.5)])
    def test_add_record_writes_absent_reimbursement_as_blank_cell(
        self, sheets_client, amount, cell
    ):
        client = sheets_client()
        client.add_record(_receipt(reimbursement_amount=amount))
        client.add_record(_receipt(provider="Unrelated", reimbursement_amount=7))
        column = GSheetsClient.HEADERS.index("Reimbursement Amount")
        assert [row[column] for row in client._worksheet.rows] == [cell, 7]

    @pytest.mark.parametrize("amount,cell", [(None, ""), (0, 0), (12.5, 12.5)])
    def test_add_record_writes_absent_billed_and_insurance_as_blank_cells(
        self, sheets_client, amount, cell
    ):
        client = sheets_client()
        client.add_record(_receipt(billed_amount=amount, insurance_paid=amount))
        billed = GSheetsClient.HEADERS.index("Billed Amount")
        insurance = GSheetsClient.HEADERS.index("Insurance Paid")
        row = client._worksheet.rows[0]
        assert (row[billed], row[insurance]) == (cell, cell)

    def test_confirming_counts_it(self, sheets_client):
        client = sheets_client()
        record_id = client.add_record(_receipt(patient_responsibility=40.0))

        assert client.update_record(record_id, {"Review Status": "Confirmed"}) is True

        assert client.get_unreimbursed_total() == pytest.approx(40.0)
        assert client.get_summary_by_year()[2026]["total_responsibility"] == pytest.approx(40.0)
        assert client.get_pending_review()["count"] == 0

    def test_add_record_refuses_sheet_without_review_status_column(self, sheets_client):
        """Before the migration, a "Pending" appended positionally lands under no
        header and reads back blank - i.e. counted. The writer must refuse, and
        must not add the column itself."""
        client = sheets_client(LEGACY_HEADERS, [_legacy_row(ID=1)])

        with pytest.raises(RuntimeError, match="migrate-sheet"):
            client.add_record(_receipt())

        assert len(client._worksheet.rows) == 1
        assert client._worksheet.header == LEGACY_HEADERS

    def test_add_record_refuses_shifted_review_status_column(self, sheets_client):
        client = sheets_client(LEGACY_HEADERS + ["Claimed?", "Review Status"])

        with pytest.raises(RuntimeError, match="migrate-sheet"):
            client.add_record(_receipt())

        assert client._worksheet.rows == []

    @pytest.mark.parametrize("status", ["", "Maybe"])
    def test_add_record_rejects_anything_but_pending_or_confirmed(self, sheets_client, status):
        client = sheets_client()

        with pytest.raises(ValueError, match="review_status"):
            client.add_record(_receipt(review_status=status))

        assert client._worksheet.rows == []

    def test_check_review_status_column(self, sheets_client):
        sheets_client().check_review_status_column()
        with pytest.raises(RuntimeError, match="migrate-sheet"):
            sheets_client(LEGACY_HEADERS).check_review_status_column()


class TestMigrateReviewStatusColumn:
    def _legacy_client(self, sheets_client):
        return sheets_client(
            LEGACY_HEADERS,
            [
                _legacy_row(ID=1, **{"Patient Responsibility": 100.0}),
                _legacy_row(ID=2, **{"Patient Responsibility": 50.0, "Is Authoritative": "No"}),
            ],
        )

    def test_dry_run_writes_nothing(self, sheets_client):
        client = self._legacy_client(sheets_client)

        message = client.migrate_review_status_column()

        assert message.startswith("Dry run")
        assert "W1" in message
        assert "2 existing rows" in message
        assert client._worksheet.header == LEGACY_HEADERS
        assert client._worksheet.acell_writes == []
        assert client._worksheet.col_count == len(LEGACY_HEADERS)

    def test_apply_adds_header_and_legacy_rows_still_count(self, sheets_client):
        client = self._legacy_client(sheets_client)
        assert client.get_unreimbursed_total() == pytest.approx(100.0)

        message = client.migrate_review_status_column(apply=True)

        assert message.startswith("Applied")
        assert client._worksheet.header == GSheetsClient.HEADERS
        assert client._worksheet.col_count == len(GSheetsClient.HEADERS)
        assert [r["Review Status"] for r in client.get_all_records()] == ["", ""]
        assert client.get_unreimbursed_total() == pytest.approx(100.0)
        assert client.get_pending_review()["count"] == 0

        client.add_record(_receipt(patient_responsibility=40.0))
        assert client.get_unreimbursed_total() == pytest.approx(100.0)
        assert client.get_pending_review()["unreimbursed_amount"] == pytest.approx(40.0)

    def test_refuses_unexpected_header(self, sheets_client):
        header = ["Patient Resp" if h == "Patient Responsibility" else h for h in LEGACY_HEADERS]
        client = sheets_client(header)

        with pytest.raises(RuntimeError, match="Refusing to migrate"):
            client.migrate_review_status_column(apply=True)

        assert client._worksheet.acell_writes == []

    def test_refuses_extra_trailing_column(self, sheets_client):
        client = sheets_client(LEGACY_HEADERS + ["Claimed?"])

        with pytest.raises(RuntimeError, match="Refusing to migrate"):
            client.migrate_review_status_column(apply=True)

        assert client._worksheet.acell_writes == []

    @pytest.mark.parametrize("apply", [False, True])
    def test_refuses_when_the_new_column_already_holds_values(self, sheets_client, apply):
        """A stray value in unheaded column W is invisible today; adding the header
        would make it a live review status and drop that legacy row from totals."""
        client = sheets_client(LEGACY_HEADERS, [_legacy_row(ID=1), _legacy_row(ID=2) + ["Pending"]])
        assert client.get_unreimbursed_total() == pytest.approx(200.0)

        with pytest.raises(RuntimeError, match=r"W3='Pending'"):
            client.migrate_review_status_column(apply=apply)

        assert client._worksheet.header == LEGACY_HEADERS
        assert client._worksheet.acell_writes == []

    @pytest.mark.parametrize("column,value", [("T", "0"), ("U", "5"), ("V", "No"), ("W", "x")])
    def test_refuses_stray_values_under_every_header_it_would_add(
        self, sheets_client, column, value
    ):
        """On a sheet that predates the linking columns, a stray "No" in V would
        silently subordinate a legacy row; any of T-W must block the migration."""
        pre_linking = GSheetsClient.HEADERS[: GSheetsClient.HEADERS.index("Original Provider")]
        row = [""] * (ord(column) - ord("A") + 1)
        row[0] = 1
        row[-1] = value
        client = sheets_client(pre_linking, [row])

        with pytest.raises(RuntimeError, match=rf"{column}2='{value}'"):
            client.migrate_review_status_column(apply=True)

        assert client._worksheet.header == pre_linking
        assert client._worksheet.acell_writes == []

    def test_misplaced_column_is_refused_with_its_own_message(self, sheets_client):
        client = sheets_client(LEGACY_HEADERS[:-1] + ["Review Status", "Is Authoritative"])

        with pytest.raises(RuntimeError, match="is in column V.*Move it by hand"):
            client.migrate_review_status_column(apply=True)

        assert client._worksheet.acell_writes == []

    def test_sheet_without_linking_columns_gets_them_too(self, sheets_client):
        pre_linking = GSheetsClient.HEADERS[: GSheetsClient.HEADERS.index("Original Provider")]
        client = sheets_client(pre_linking)

        assert "at T1:W1" in client.migrate_review_status_column()
        assert client._worksheet.acell_writes == []

        client.migrate_review_status_column(apply=True)

        assert client._worksheet.header == GSheetsClient.HEADERS

    def test_apply_fails_loudly_when_the_write_does_not_land(self, sheets_client, monkeypatch):
        client = sheets_client(LEGACY_HEADERS)
        monkeypatch.setattr(client._worksheet, "update_acell", lambda label, value: None)

        with pytest.raises(RuntimeError, match="read back"):
            client.migrate_review_status_column(apply=True)

    def test_already_migrated_is_a_no_op(self, sheets_client):
        client = sheets_client()

        assert "nothing to do" in client.migrate_review_status_column(apply=True)
        assert client._worksheet.acell_writes == []


class TestPendingReview:
    @pytest.fixture
    def client(self):
        return _make_client()

    @staticmethod
    def _row(amount, status, **extra):
        row = {
            "ID": extra.pop("ID", 1),
            "Service Date": "2026-03-01",
            "Patient": "Alice",
            "Document Type": "receipt",
            "Patient Responsibility": amount,
            "HSA Eligible": "Yes",
            "Reimbursed": "No",
            "Is Authoritative": "",
            "Review Status": status,
        }
        row.update(extra)
        return row

    def _records(self):
        return [
            self._row(100.0, "Confirmed", ID=1),
            self._row(30.0, "", ID=2),  # legacy
            self._row(40.0, "Pending", ID=3),
            self._row(40.0, "Pending", ID=4, **{"Is Authoritative": "No"}),  # duplicate
            self._row(75.0, "Pending", ID=5, **{"HSA Eligible": "No"}),
            self._row(20.0, "Pending", ID=6, Reimbursed="Yes"),
            self._row(80.0, "Pending", ID=7, **{"Is Authoritative": "Yes"}),  # EOB
        ]

    def test_pending_amount_is_exactly_what_confirming_all_adds(self, client):
        records = self._records()
        with patch.object(client, "get_all_records", return_value=records):
            before = client.get_unreimbursed_total()
            pending = client.get_pending_review()

        confirmed_all = [{**r, "Review Status": "Confirmed"} for r in records]
        with patch.object(client, "get_all_records", return_value=confirmed_all):
            after = client.get_unreimbursed_total()

        assert before == pytest.approx(130.0)
        assert pending["count"] == 5
        assert pending["unreimbursed_amount"] == pytest.approx(120.0)
        assert after == pytest.approx(before + pending["unreimbursed_amount"])

    def test_unknown_status_is_listed_as_awaiting_review(self, client):
        records = [self._row(55.0, "Confirmd")]
        with patch.object(client, "get_all_records", return_value=records):
            assert client.get_unreimbursed_total() == pytest.approx(0.0)
            pending = client.get_pending_review()
        assert [r["Review Status"] for r in pending["records"]] == ["Confirmd"]
        assert pending["unreimbursed_amount"] == pytest.approx(55.0)

    def test_confirmed_record_subordinated_only_by_pending_partners_is_held_out(self, client):
        records = [
            # Confirmed statement linked only to a pending EOB: held out.
            self._row(
                100.0, "Confirmed", ID=1, **{"Is Authoritative": "No", "Linked Record ID": "2"}
            ),
            self._row(
                80.0, "Pending", ID=2, **{"Is Authoritative": "Yes", "Linked Record ID": "1"}
            ),
            # Confirmed statement whose EOB is confirmed: subordinate for real.
            self._row(
                50.0, "Confirmed", ID=3, **{"Is Authoritative": "No", "Linked Record ID": "4"}
            ),
            self._row(
                45.0, "Confirmed", ID=4, **{"Is Authoritative": "Yes", "Linked Record ID": "3"}
            ),
            # Held out, but already reimbursed: was never in the unreimbursed total.
            self._row(
                25.0,
                "Confirmed",
                ID=6,
                Reimbursed="Yes",
                **{"Is Authoritative": "No", "Linked Record ID": "7"},
            ),
            self._row(
                25.0, "Pending", ID=7, **{"Is Authoritative": "Yes", "Linked Record ID": "6"}
            ),
            # Orphaned "No" (partner deleted): not attributable to review.
            self._row(
                30.0, "Confirmed", ID=5, **{"Is Authoritative": "No", "Linked Record ID": "99"}
            ),
        ]
        with patch.object(client, "get_all_records", return_value=records):
            pending = client.get_pending_review()

        assert [r["ID"] for r in pending["held_out_records"]] == [1]
        assert pending["held_out_amount"] == pytest.approx(100.0)

    def _held_ids(self, client, records):
        with patch.object(client, "get_all_records", return_value=records):
            return [r["ID"] for r in client.get_pending_review()["held_out_records"]]

    def test_not_held_when_any_partner_is_a_confirmed_authority(self, client):
        records = [
            self._row(
                100.0, "Confirmed", ID=1, **{"Is Authoritative": "No", "Linked Record ID": "2|3"}
            ),
            self._row(
                80.0, "Pending", ID=2, **{"Is Authoritative": "Yes", "Linked Record ID": "1"}
            ),
            self._row(
                90.0, "Confirmed", ID=3, **{"Is Authoritative": "Yes", "Linked Record ID": "1"}
            ),
        ]
        assert self._held_ids(client, records) == []

    def test_counted_authority_linked_by_a_pending_record_is_not_held(self, client):
        records = [
            self._row(
                80.0, "Confirmed", ID=1, **{"Is Authoritative": "Yes", "Linked Record ID": "2"}
            ),
            self._row(
                100.0, "Pending", ID=2, **{"Is Authoritative": "No", "Linked Record ID": "1"}
            ),
        ]
        assert self._held_ids(client, records) == []

    def test_pending_subordinate_is_not_also_listed_as_held(self, client):
        records = [
            self._row(
                100.0, "Pending", ID=1, **{"Is Authoritative": "No", "Linked Record ID": "2"}
            ),
            self._row(
                80.0, "Pending", ID=2, **{"Is Authoritative": "Yes", "Linked Record ID": "1"}
            ),
        ]
        assert self._held_ids(client, records) == []

    def test_pending_excluded_from_every_total(self, client):
        records = [
            self._row(100.0, "Confirmed", ID=1, Patient="Alice"),
            self._row(40.0, "Pending", ID=2, Patient="Bob", **{"Document Type": "eob"}),
        ]
        with patch.object(client, "get_all_records", return_value=records):
            assert client.get_unreimbursed_total() == pytest.approx(100.0)
            summary = client.get_summary_by_year()
            assert summary[2026]["count"] == 1
            assert summary[2026]["total_responsibility"] == pytest.approx(100.0)
            assert client.get_oop_progress(2026)["total_oop"] == pytest.approx(100.0)
            assert [b["patient"] for b in client.get_oop_breakdown_by_patient(2026)] == ["Alice"]
            visits = client.reconcile_for_reimbursement(2026)
            assert [v["Statement Record ID"] for v in visits] == [1]
            assert all(v["EOB Record ID"] == "" for v in visits)


def _row(record_id, **values) -> list:
    """A current-schema row with the given ID."""
    base = {
        "ID": record_id,
        "Service Date": "2026-01-05",
        "Provider": "Sutter Health",
        "Patient": "Alice",
        "Patient Responsibility": 10.0,
        "HSA Eligible": "Yes",
        "Document Type": "statement",
        "Reimbursed": "No",
        "Review Status": "Pending",
    }
    base.update(values)
    return [base.get(h, "") for h in GSheetsClient.HEADERS]


class TestUniqueRecordIds:
    def test_next_id_skips_past_a_deleted_row(self, sheets_client):
        # Rows 3 and 4 were deleted: the row count (4) would reuse an existing ID.
        client = sheets_client(rows=[_row(1), _row(2), _row(5)])

        assert client.add_record(_receipt()) == 6
        assert client._worksheet.rows[-1][0] == 6

    def test_next_id_after_a_collision_already_in_the_sheet(self, sheets_client):
        client = sheets_client(rows=[_row(1), _row(103), _row(103)])

        assert client.add_record(_receipt()) == 104

    def test_next_id_ignores_blank_and_text_ids(self, sheets_client):
        client = sheets_client(rows=[_row(""), _row("n/a"), _row(7)])

        assert client.add_record(_receipt()) == 8

    def test_first_record_in_an_empty_sheet_is_1(self, sheets_client):
        assert sheets_client().add_record(_receipt()) == 1

    def test_update_refuses_a_duplicated_id_and_writes_nothing(self, sheets_client):
        client = sheets_client(rows=[_row(103, Provider="CVS"), _row(103, Provider="Eye Doc")])

        with pytest.raises(DuplicateRecordIdError, match="103 is on 2 rows"):
            client.update_record(103, {"Review Status": "Confirmed"})

        assert client._worksheet.acell_writes == []

    def test_update_of_a_unique_id_still_writes_that_row(self, sheets_client):
        client = sheets_client(rows=[_row(103), _row(103), _row(104, Provider="Eye Doc")])

        assert client.update_record(104, {"Review Status": "Confirmed"}) is True
        records = client.get_all_records()
        assert [r["Review Status"] for r in records] == ["Pending", "Pending", "Confirmed"]

    def test_link_refuses_a_duplicated_id_before_any_write(self, sheets_client):
        client = sheets_client(
            rows=[_row(1, **{"Document Type": "eob"}), _row(2), _row(2, Provider="Other")]
        )

        with pytest.raises(DuplicateRecordIdError):
            client.link_records(1, 2)

        assert client._worksheet.acell_writes == []

    def test_delete_refuses_a_duplicated_id(self, sheets_client):
        client = sheets_client(rows=[_row(103), _row(103)])

        with pytest.raises(DuplicateRecordIdError):
            client.delete_record(103)

        assert len(client._worksheet.rows) == 2

    def test_delete_of_a_unique_id_still_works(self, sheets_client):
        client = sheets_client(rows=[_row(1), _row(2)])

        assert client.delete_record(2) is True
        assert [r[0] for r in client._worksheet.rows] == [1]

    def test_duplicate_ids_lists_each_collision_with_its_row_count(self, sheets_client):
        client = sheets_client(rows=[_row(1), _row(103), _row(103), _row(7), _row(7), _row(7)])

        assert client.duplicate_ids() == {103: 2, 7: 3}

    def test_duplicated_id_is_a_value_error_so_confirm_reports_it(self):
        assert issubclass(DuplicateRecordIdError, ValueError)


class TestEligibilityReview:
    BASE = {
        "HSA Eligible": "No",
        "Reimbursed": "No",
        "Is Authoritative": "",
        "Notes": "No FSA/HSA markers",
        "Review Status": "",
    }

    @pytest.mark.parametrize(
        "change,flagged",
        [
            ({}, True),  # legacy blank status: never reviewed
            ({"Review Status": "Pending"}, True),
            ({"Review Status": "Confirmed"}, False),  # a person accepted the No
            ({"Review Status": " confirmed "}, False),
            ({"HSA Eligible": "Yes"}, False),
            ({"Reimbursed": "Yes"}, False),
            ({"Is Authoritative": "No"}, False),  # subordinate: never counts anyway
            ({"Notes": "x [Pre-HSA: before 2026-01-01]"}, False),  # the date rule
        ],
    )
    def test_which_rows_are_flagged(self, change, flagged):
        assert _needs_eligibility_review({**self.BASE, **change}) is flagged

    def test_summary_totals_what_the_flagged_rows_hold_out(self, sheets_client):
        rows = [
            _row(1, **{"HSA Eligible": "No", "Patient Responsibility": 566.0, "Review Status": ""}),
            _row(2, **{"HSA Eligible": "No", "Patient Responsibility": 10.0, "Review Status": ""}),
            _row(
                3,
                **{
                    "HSA Eligible": "No",
                    "Patient Responsibility": 99.0,
                    "Review Status": "Confirmed",
                },
            ),
            _row(4, **{"HSA Eligible": "Yes", "Patient Responsibility": 50.0}),
        ]
        review = sheets_client(rows=rows).get_eligibility_review()

        assert review["count"] == 2
        assert review["amount"] == pytest.approx(576.0)
        assert [r["ID"] for r in review["records"]] == [1, 2]


class TestSuspectPreHsaDate:
    """#119: a year misread as 2023 marks a 2026 receipt pre-HSA and drops it from totals."""

    @staticmethod
    def _pre_hsa(service, added, **extra):
        return {
            "HSA Eligible": "No",
            "Reimbursed": "No",
            "Is Authoritative": "",
            "Notes": "paid statement [Pre-HSA: before 2026-01-01]",
            "Review Status": "Pending",
            "Service Date": service,
            "Date Added": added,
            **extra,
        }

    def test_a_date_years_before_filing_is_listed_with_its_reason(self):
        record = self._pre_hsa("2023-02-27", "2026-03-05")

        assert _needs_eligibility_review(record) is True
        assert _suspect_pre_hsa_reason(record) == (
            "service date 2023-02-27 is 3 years before it was added: check the year"
        )

    def test_a_recent_pre_hsa_receipt_is_still_not_listed(self):
        record = self._pre_hsa("2025-12-20", "2026-01-15")

        assert _suspect_pre_hsa_reason(record) == ""
        assert _needs_eligibility_review(record) is False

    @pytest.mark.parametrize("added,listed", [("2026-02-27", False), ("2026-03-01", True)])
    def test_the_boundary_is_one_year(self, added, listed):
        record = self._pre_hsa("2025-02-26", added)

        assert _needs_eligibility_review(record) is listed

    @pytest.mark.parametrize(
        "service,added", [("", "2026-03-05"), ("2023-02-27", ""), ("n/a", "x")]
    )
    def test_an_unreadable_date_is_not_flagged_and_does_not_crash(self, service, added):
        assert _suspect_pre_hsa_reason(self._pre_hsa(service, added)) == ""

    def test_confirming_clears_it(self):
        record = self._pre_hsa("2023-02-27", "2026-03-05", **{"Review Status": "Confirmed"})

        assert _needs_eligibility_review(record) is False

    def test_a_row_that_is_not_pre_hsa_has_no_date_reason(self):
        record = self._pre_hsa("2023-02-27", "2026-03-05", Notes="No FSA markers")

        assert _suspect_pre_hsa_reason(record) == ""
        assert _needs_eligibility_review(record) is True  # still listed, as a model "No"
