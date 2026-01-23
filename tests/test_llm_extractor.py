"""Tests for llm_extractor.py - Vision LLM extraction module."""

import pytest

from src.processors.llm_extractor import (
    ExtractedReceipt,
    VisionExtractor,
    detect_provider_skill,
    get_extraction_prompt,
)


class TestDetectProviderSkill:
    """Tests for detect_provider_skill function."""

    def test_detect_costco_from_filename(self):
        """Detect Costco from filename containing 'costco'."""
        assert detect_provider_skill("costco_receipt.heic") == "costco"
        assert detect_provider_skill("COSTCO_salonpas.pdf") == "costco"

    def test_detect_costco_from_store_number(self):
        """Detect Costco from store number pattern."""
        assert detect_provider_skill("receipt.pdf", hints=["store 423"]) == "costco"

    def test_detect_cvs(self):
        """Detect CVS from filename."""
        assert detect_provider_skill("cvs_prescription.pdf") == "cvs"
        assert detect_provider_skill("CVS_Ming_rx.jpg") == "cvs"

    def test_detect_walgreens(self):
        """Detect Walgreens from filename."""
        assert detect_provider_skill("walgreens_receipt.png") == "walgreens"
        assert detect_provider_skill("walgreen_pharmacy.pdf") == "walgreens"

    def test_detect_amazon(self):
        """Detect Amazon from filename."""
        assert detect_provider_skill("amazon_order.pdf") == "amazon"
        assert detect_provider_skill("Amazon_Miralax.heic") == "amazon"

    def test_detect_sutter(self):
        """Detect Sutter Health from filename."""
        assert detect_provider_skill("sutter_eob.pdf") == "sutter"
        assert detect_provider_skill("pamf_statement.pdf") == "sutter"
        assert (
            detect_provider_skill("palo alto medical.pdf", hints=["palo alto medical"]) == "sutter"
        )

    def test_detect_aetna(self):
        """Detect Aetna from filename."""
        assert detect_provider_skill("aetna_eob.pdf") == "aetna"
        assert detect_provider_skill("Aetna_Medical_EOB.pdf") == "aetna"

    def test_detect_express_scripts(self):
        """Detect Express Scripts from filename."""
        assert detect_provider_skill("express_scripts_invoice.pdf") == "express_scripts"
        assert detect_provider_skill("express-scripts-rx.pdf") == "express_scripts"
        assert detect_provider_skill("esrx_medication.pdf") == "express_scripts"

    def test_detect_delta_dental(self):
        """Detect Delta Dental from filename."""
        assert detect_provider_skill("delta dental_eob.pdf") == "delta_dental"

    def test_detect_vsp(self):
        """Detect VSP from filename."""
        assert detect_provider_skill("vsp_vision.pdf") == "vsp"

    def test_no_match_returns_none(self):
        """Return None when no provider matches."""
        assert detect_provider_skill("random_receipt.pdf") is None
        assert detect_provider_skill("medical_bill.jpg") is None

    def test_case_insensitive(self):
        """Provider detection is case-insensitive."""
        assert detect_provider_skill("COSTCO.PDF") == "costco"
        assert detect_provider_skill("CvS_receipt.jpg") == "cvs"


class TestGetExtractionPrompt:
    """Tests for get_extraction_prompt function."""

    def test_includes_family_members(self):
        """Prompt includes family member names."""
        prompt = get_extraction_prompt(family_members=["Alice", "Bob"])
        assert "Alice" in prompt
        assert "Bob" in prompt

    def test_default_family_members(self):
        """Uses default family members when none provided."""
        prompt = get_extraction_prompt()
        assert "Ming" in prompt
        assert "Vanessa" in prompt
        assert "Maxwell" in prompt

    def test_includes_provider_skill(self):
        """Provider skill text is appended to prompt."""
        prompt = get_extraction_prompt(provider_skill="costco")
        assert "COSTCO RECEIPT RULES" in prompt
        assert '"F"' in prompt or "'F'" in prompt  # FSA marker

    def test_unknown_skill_ignored(self):
        """Unknown provider skill doesn't cause error."""
        prompt = get_extraction_prompt(provider_skill="unknown_provider")
        # Should not raise, just returns base prompt
        assert "provider_name" in prompt


class TestExtractedReceiptGenerateFilename:
    """Tests for ExtractedReceipt.generate_filename method."""

    def test_basic_filename(self):
        """Generate basic filename from receipt data."""
        receipt = ExtractedReceipt(
            provider_name="CVS Pharmacy",
            service_date="2026-01-15",
            service_type="Prescription",
            patient_name="Ming",
            billed_amount=25.00,
            insurance_paid=0,
            patient_responsibility=25.00,
            hsa_eligible=True,
            category="pharmacy",
            document_type="receipt",
            confidence_score=0.95,
            notes="",
            raw_extraction={},
        )
        filename = receipt.generate_filename()
        assert filename == "2026-01-15_CVS_Pharmacy_Prescription_$25.00.pdf"

    def test_custom_extension(self):
        """Generate filename with custom extension."""
        receipt = ExtractedReceipt(
            provider_name="Test",
            service_date="2026-01-01",
            service_type="Test",
            patient_name="Test",
            billed_amount=10.00,
            insurance_paid=0,
            patient_responsibility=10.00,
            hsa_eligible=True,
            category="medical",
            document_type="receipt",
            confidence_score=0.9,
            notes="",
            raw_extraction={},
        )
        assert receipt.generate_filename("png").endswith(".png")

    def test_special_characters_removed(self):
        """Special characters are removed from filename."""
        receipt = ExtractedReceipt(
            provider_name="Dr. Smith's Office!",
            service_date="2026-01-15",
            service_type="Check-up (annual)",
            patient_name="Ming",
            billed_amount=100.00,
            insurance_paid=80.00,
            patient_responsibility=20.00,
            hsa_eligible=True,
            category="medical",
            document_type="receipt",
            confidence_score=0.9,
            notes="",
            raw_extraction={},
        )
        filename = receipt.generate_filename()
        assert "!" not in filename
        assert "(" not in filename
        assert "'" not in filename

    def test_no_service_date_uses_today(self):
        """Use today's date when service_date is None."""
        receipt = ExtractedReceipt(
            provider_name="Test",
            service_date=None,
            service_type="Test",
            patient_name="Test",
            billed_amount=10.00,
            insurance_paid=0,
            patient_responsibility=10.00,
            hsa_eligible=True,
            category="medical",
            document_type="receipt",
            confidence_score=0.9,
            notes="",
            raw_extraction={},
        )
        filename = receipt.generate_filename()
        # Should have a date at the start (YYYY-MM-DD format)
        assert filename[4] == "-"
        assert filename[7] == "-"


class TestVisionExtractorParseResponse:
    """Tests for VisionExtractor._parse_response method."""

    @pytest.fixture
    def extractor(self):
        """Create extractor instance for testing."""
        return VisionExtractor()

    def test_parse_plain_json(self, extractor):
        """Parse plain JSON response."""
        response = '{"provider_name": "CVS", "hsa_eligible": true}'
        result = extractor._parse_response(response)
        assert result["provider_name"] == "CVS"
        assert result["hsa_eligible"] is True

    def test_parse_json_in_markdown(self, extractor):
        """Parse JSON wrapped in markdown code block."""
        response = """```json
{"provider_name": "Costco", "eligible_subtotal": 63.96}
```"""
        result = extractor._parse_response(response)
        assert result["provider_name"] == "Costco"
        assert result["eligible_subtotal"] == 63.96

    def test_parse_json_array_takes_first(self, extractor):
        """When LLM returns array, take first element."""
        response = '[{"provider_name": "First"}, {"provider_name": "Second"}]'
        result = extractor._parse_response(response)
        assert result["provider_name"] == "First"

    def test_parse_invalid_json_returns_empty(self, extractor):
        """Invalid JSON returns empty dict."""
        response = "This is not JSON at all"
        result = extractor._parse_response(response)
        assert result == {}

    def test_parse_json_with_extra_text(self, extractor):
        """Extract JSON from response with surrounding text."""
        response = 'Here is the data: {"provider_name": "Test"} That is all.'
        result = extractor._parse_response(response)
        assert result["provider_name"] == "Test"


class TestVisionExtractorBuildReceipt:
    """Tests for VisionExtractor._build_receipt method - tax calculation logic."""

    @pytest.fixture
    def extractor(self):
        """Create extractor instance for testing."""
        return VisionExtractor()

    def test_build_receipt_retail_with_tax(self, extractor):
        """Retail receipt: calculate tax on eligible items."""
        parsed = {
            "provider_name": "Costco",
            "service_date": "2026-01-04",
            "service_type": "4x Salonpas @$15.99",
            "patient_name": "Ming",
            "eligible_subtotal": 63.96,  # 4 x 15.99
            "receipt_tax": 18.28,
            "receipt_taxable_amount": 200.29,
            "insurance_paid": 0,
            "hsa_eligible": True,
            "category": "pharmacy",
            "document_type": "receipt",
            "confidence_score": 0.90,
            "notes": "",
        }
        receipt = extractor._build_receipt(parsed)

        # Tax rate = 18.28 / 200.29 = 0.09127...
        # Tax on eligible = 63.96 * 0.09127 = 5.84
        # Patient responsibility = 63.96 + 5.84 = 69.80
        assert receipt.patient_responsibility == pytest.approx(69.80, abs=0.01)
        assert receipt.billed_amount == 63.96
        assert "Tax rate" in receipt.notes
        assert "9.127%" in receipt.notes or "9.12" in receipt.notes

    def test_build_receipt_retail_no_eligible_items(self, extractor):
        """Retail receipt with no eligible items: hsa_eligible should be from parsed."""
        parsed = {
            "provider_name": "Target",
            "service_date": "2026-01-04",
            "service_type": "Groceries",
            "patient_name": "Ming",
            "eligible_subtotal": 0,
            "receipt_tax": 5.00,
            "receipt_taxable_amount": 50.00,
            "insurance_paid": 0,
            "hsa_eligible": False,
            "category": "unknown",
            "document_type": "receipt",
            "confidence_score": 0.80,
            "notes": "No eligible items",
        }
        receipt = extractor._build_receipt(parsed)
        assert receipt.patient_responsibility == 0
        assert receipt.hsa_eligible is False

    def test_build_receipt_eob_uses_extracted_values(self, extractor):
        """EOB: use extracted patient_responsibility directly, not calculated."""
        parsed = {
            "provider_name": "Sutter Health",
            "service_date": "2026-01-10",
            "service_type": "Office Visit",
            "patient_name": "Vanessa",
            "eligible_subtotal": 0,
            "receipt_tax": 0,
            "receipt_taxable_amount": 0,
            "patient_responsibility": 45.00,
            "billed_amount": 250.00,
            "insurance_paid": 205.00,
            "hsa_eligible": True,
            "category": "medical",
            "document_type": "eob",
            "confidence_score": 0.95,
            "notes": "",
        }
        receipt = extractor._build_receipt(parsed)
        assert receipt.patient_responsibility == 45.00
        assert receipt.billed_amount == 250.00
        assert receipt.insurance_paid == 205.00

    def test_build_receipt_handles_service_type_list(self, extractor):
        """Handle when LLM returns service_type as a list."""
        parsed = {
            "provider_name": "CVS",
            "service_date": "2026-01-04",
            "service_type": ["Prescription A", "Prescription B"],
            "patient_name": "Ming",
            "eligible_subtotal": 20.00,
            "receipt_tax": 0,
            "receipt_taxable_amount": 0,
            "insurance_paid": 0,
            "hsa_eligible": True,
            "category": "pharmacy",
            "document_type": "prescription",
            "confidence_score": 0.85,
            "notes": "",
        }
        receipt = extractor._build_receipt(parsed)
        assert "Prescription A" in receipt.service_type
        assert "Prescription B" in receipt.service_type

    def test_build_receipt_missing_fields_use_defaults(self, extractor):
        """Missing fields use sensible defaults."""
        parsed = {
            "provider_name": "Unknown Clinic",
            # Most fields missing
        }
        receipt = extractor._build_receipt(parsed)
        assert receipt.provider_name == "Unknown Clinic"
        assert receipt.patient_name == "Unknown"
        assert receipt.patient_responsibility == 0
        assert receipt.confidence_score == 0.5  # Default


class TestMockExtractor:
    """Test the MockVisionExtractor for testing purposes."""

    def test_mock_extractor_returns_fixed_data(self, mock_extractor):
        """Mock extractor returns predictable test data."""
        result = mock_extractor.extract("/fake/path.pdf")
        assert result.provider_name == "Mock Provider"
        assert result.confidence_score == 0.95
        assert result.raw_extraction.get("mock") is True
