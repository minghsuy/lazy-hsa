"""Tests for sheet_client.py - summary and filtering logic."""

from unittest.mock import MagicMock, patch

import pytest

from src.storage.sheet_client import GSheetsClient, _safe_float


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
