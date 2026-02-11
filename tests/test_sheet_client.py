"""Tests for sheet_client.py - summary and filtering logic."""

from unittest.mock import patch

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
