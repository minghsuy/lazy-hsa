"""Tests for inbox_watcher.py - Google Drive inbox monitoring."""

import pytest

from src.watchers.inbox_watcher import DriveInboxWatcher


class MockGDriveClient:
    """Mock GDrive client for testing."""

    root_folder_name = "HSA_Receipts"

    def get_or_create_folder(self, name, parent_id=None):
        return f"mock_folder_id_{name}"


class TestDriveInboxWatcherIsReceiptFile:
    """Tests for DriveInboxWatcher._is_receipt_file method."""

    @pytest.fixture
    def watcher(self):
        """Create watcher with mock client."""
        return DriveInboxWatcher(
            gdrive_client=MockGDriveClient(),
            process_callback=lambda path, hint: {"processed": True},
        )

    def test_pdf_is_receipt(self, watcher):
        """PDF files are receipts."""
        assert watcher._is_receipt_file("receipt.pdf") is True
        assert watcher._is_receipt_file("STATEMENT.PDF") is True

    def test_image_formats_are_receipts(self, watcher):
        """Common image formats are receipts."""
        assert watcher._is_receipt_file("scan.png") is True
        assert watcher._is_receipt_file("photo.jpg") is True
        assert watcher._is_receipt_file("image.jpeg") is True
        assert watcher._is_receipt_file("document.tiff") is True
        assert watcher._is_receipt_file("receipt.bmp") is True
        assert watcher._is_receipt_file("file.webp") is True
        assert watcher._is_receipt_file("photo.gif") is True

    def test_heic_heif_are_receipts(self, watcher):
        """iPhone photo formats (HEIC/HEIF) are receipts."""
        assert watcher._is_receipt_file("IMG_1234.heic") is True
        assert watcher._is_receipt_file("photo.HEIC") is True
        assert watcher._is_receipt_file("image.heif") is True
        assert watcher._is_receipt_file("scan.HEIF") is True

    def test_xlsx_is_receipt(self, watcher):
        """xlsx files are receipts (Express Scripts claims summaries)."""
        assert watcher._is_receipt_file("Claims Summary.xlsx") is True
        assert watcher._is_receipt_file("express_scripts.XLSX") is True

    def test_non_receipt_files_rejected(self, watcher):
        """Non-receipt file types are rejected."""
        assert watcher._is_receipt_file("document.docx") is False
        assert watcher._is_receipt_file("notes.txt") is False
        assert watcher._is_receipt_file("archive.zip") is False
        assert watcher._is_receipt_file("video.mp4") is False

    def test_case_insensitive_extensions(self, watcher):
        """Extension check is case-insensitive."""
        assert watcher._is_receipt_file("receipt.PDF") is True
        assert watcher._is_receipt_file("photo.JPG") is True
        assert watcher._is_receipt_file("scan.Png") is True


class TestDriveInboxWatcherExtractPatientHint:
    """Tests for DriveInboxWatcher._extract_patient_hint method."""

    @pytest.fixture
    def watcher(self):
        """Create watcher with default family names."""
        return DriveInboxWatcher(
            gdrive_client=MockGDriveClient(),
            process_callback=lambda path, hint: {"processed": True},
            family_names=["Alice", "Bob", "Charlie"],
        )

    def test_extract_alice_from_filename(self, watcher):
        """Extract 'Alice' from filename."""
        assert watcher._extract_patient_hint("CVS_Alice_prescription.pdf") == "Alice"
        assert watcher._extract_patient_hint("alice_receipt.jpg") == "Alice"
        assert watcher._extract_patient_hint("ALICE_eob.pdf") == "Alice"

    def test_extract_bob_from_filename(self, watcher):
        """Extract 'Bob' from filename."""
        assert watcher._extract_patient_hint("Amazon_Miralax_Bob.pdf") == "Bob"
        assert watcher._extract_patient_hint("bob_surgery_bill.pdf") == "Bob"

    def test_extract_charlie_from_filename(self, watcher):
        """Extract 'Charlie' from filename."""
        assert watcher._extract_patient_hint("Kaiser_Charlie_checkup.pdf") == "Charlie"
        assert watcher._extract_patient_hint("charlie_dental.jpg") == "Charlie"

    def test_no_match_returns_none(self, watcher):
        """Return None when no family name in filename."""
        assert watcher._extract_patient_hint("receipt.pdf") is None
        assert watcher._extract_patient_hint("costco_salonpas.heic") is None
        assert watcher._extract_patient_hint("medical_bill.jpg") is None

    def test_case_insensitive_matching(self, watcher):
        """Name matching is case-insensitive."""
        assert watcher._extract_patient_hint("ALICE_receipt.pdf") == "Alice"
        assert watcher._extract_patient_hint("BOB_eob.pdf") == "Bob"
        assert watcher._extract_patient_hint("cHaRlIe.jpg") == "Charlie"

    def test_name_inside_longer_word_is_not_a_hint(self, watcher):
        """A family name embedded in an unrelated word is not a whole-word hit."""
        assert watcher._extract_patient_hint("Bobcat_rental_invoice.pdf") is None
        assert watcher._extract_patient_hint("Alicedale_pharmacy.pdf") is None
        assert watcher._extract_patient_hint("scrabobble.jpg") is None
        assert watcher._extract_patient_hint("MyCharlieBrown.pdf") is None
        assert watcher._extract_patient_hint("Bob\u00e9.pdf") is None
        assert watcher._extract_patient_hint("\u00e9Bob.pdf") is None

    def test_name_ending_a_longer_word_is_not_a_hint(self, watcher):
        """A letter directly before the name disqualifies it too."""
        assert watcher._extract_patient_hint("Mybob_rx.pdf") is None
        assert watcher._extract_patient_hint("xAlice.pdf") is None
        assert watcher._extract_patient_hint("rx_Zbob.pdf") is None

    def test_blank_and_metacharacter_names(self):
        """Blank config names never match; punctuation in a name is literal."""

        def make(names):
            return DriveInboxWatcher(
                gdrive_client=MockGDriveClient(),
                process_callback=lambda path, hint: {"processed": True},
                family_names=names,
            )

        assert make(["", "  "])._extract_patient_hint("x_bob_2026.pdf") is None
        assert make(["", "Bob"])._extract_patient_hint("x_bob_2026.pdf") == "Bob"
        assert make(["  ", "Bob"])._extract_patient_hint("a__bob.pdf") == "Bob"
        assert make(["C++"])._extract_patient_hint("rx C++ rx.pdf") == "C++"
        assert make(["C++"])._extract_patient_hint("rx_cc_rx.pdf") is None

    def test_separators_delimit_whole_words(self, watcher):
        """Underscore, hyphen, dot, digits and spaces all count as separators."""
        assert watcher._extract_patient_hint("cvs-bob-2026.pdf") == "Bob"
        assert watcher._extract_patient_hint("cvs bob rx.pdf") == "Bob"
        assert watcher._extract_patient_hint("rx.Alice.pdf") == "Alice"
        assert watcher._extract_patient_hint("2026Charlie3.jpg") == "Charlie"
        assert watcher._extract_patient_hint("Alice.pdf") == "Alice"

    def test_same_name_twice_is_still_a_hint(self, watcher):
        """Repeating one name is not ambiguity."""
        assert watcher._extract_patient_hint("bob_refund_BOB.pdf") == "Bob"

    def test_two_different_names_give_no_hint(self, watcher, caplog):
        """Two whole-word names: no silent pick; the LLM detector decides."""
        with caplog.at_level("INFO"):
            assert watcher._extract_patient_hint("Alice_Bob_shared.pdf") is None
        assert "Ambiguous patient hint in Alice_Bob_shared.pdf" in caplog.text

    def test_whole_word_name_beside_embedded_name_is_a_hint(self, watcher):
        """An embedded non-word hit does not make a whole-word hit ambiguous."""
        assert watcher._extract_patient_hint("Alicedale_Bob_invoice.pdf") == "Bob"

    def test_longest_match_wins(self):
        """A name contained in a longer configured name defers to the longer one."""
        watcher = DriveInboxWatcher(
            gdrive_client=MockGDriveClient(),
            process_callback=lambda path, hint: {"processed": True},
            family_names=["Mary", "Mary Ann", "Zed"],
        )
        assert watcher._extract_patient_hint("rx mary ann.pdf") == "Mary Ann"
        assert watcher._extract_patient_hint("rx_mary-ann.pdf") == "Mary Ann"
        assert watcher._extract_patient_hint("rx mary__ann.pdf") == "Mary Ann"
        assert watcher._extract_patient_hint("rx mary - ann.pdf") == "Mary Ann"
        assert watcher._extract_patient_hint("rx mary.ann.pdf") == "Mary Ann"
        assert watcher._extract_patient_hint("rx mary.pdf") == "Mary"
        assert watcher._extract_patient_hint("rx mary ann zed.pdf") is None

    def test_custom_family_names(self):
        """Works with custom family name list."""
        watcher = DriveInboxWatcher(
            gdrive_client=MockGDriveClient(),
            process_callback=lambda path, hint: {"processed": True},
            family_names=["John", "Jane", "Junior"],
        )
        assert watcher._extract_patient_hint("john_receipt.pdf") == "John"
        assert watcher._extract_patient_hint("jane_bill.pdf") == "Jane"
        assert watcher._extract_patient_hint("Alice_receipt.pdf") is None  # Not in list


class TestDriveInboxWatcherDryRun:
    """Tests for dry-run mode."""

    def test_dry_run_flag_stored(self):
        """dry_run flag is stored on watcher."""
        watcher = DriveInboxWatcher(
            gdrive_client=MockGDriveClient(),
            process_callback=lambda path, hint: {"processed": True},
            dry_run=True,
        )
        assert watcher.dry_run is True

    def test_dry_run_default_false(self):
        """dry_run defaults to False."""
        watcher = DriveInboxWatcher(
            gdrive_client=MockGDriveClient(),
            process_callback=lambda path, hint: {"processed": True},
        )
        assert watcher.dry_run is False
