"""Tests for llm_extractor.py - Vision LLM extraction module."""

import pytest

from src.processors.llm_extractor import (
    ExtractedReceipt,
    VisionExtractor,
    detect_patient_hint,
    detect_provider_skill,
    get_extraction_prompt,
)
from src.watchers.inbox_watcher import DriveInboxWatcher


class TestDetectProviderSkill:
    """Tests for detect_provider_skill function."""

    def test_extract_provider_hint_precedence(self, tmp_path, monkeypatch):
        extractor = VisionExtractor()
        seen = []
        monkeypatch.setattr(
            extractor,
            "extract_from_pdf",
            lambda path: seen.append(extractor._current_provider_skill),
        )
        for name, hint, expected in [
            ("receipt.pdf", "delta_dental", "delta_dental"),
            ("cvs_x.pdf", "delta_dental", "cvs"),
            ("cvs_x.pdf", "costco", "cvs"),
            ("receipt.pdf", "store 423", "costco"),
        ]:
            pdf = tmp_path / name
            pdf.touch()
            extractor.extract(pdf, provider_hint=hint)
            assert seen.pop() == expected

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
        assert detect_provider_skill("CVS_Alice_rx.jpg") == "cvs"

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
        assert "Alice" in prompt
        assert "Bob" in prompt
        assert "Charlie" in prompt

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
            patient_name="Alice",
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
            patient_name="Alice",
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
            "patient_name": "Alice",
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
            "patient_name": "Alice",
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
            "patient_name": "Bob",
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
            "patient_name": "Alice",
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


class TestBlankAmountsFromExtraction:
    """An amount the document did not show is None, never $0; an explicit 0 stays 0."""

    NOT_SHOWN = [None, "", "  ", "N/A", "not shown", "NaN", "Infinity", float("nan"), True]
    ZERO = [0, 0.0, "0", "$0.00"]

    @pytest.fixture
    def extractor(self):
        return VisionExtractor()

    @staticmethod
    def _eob(**amounts):
        parsed = {
            "provider_name": "Clinic",
            "service_date": "2026-01-10",
            "patient_name": "Bob",
            "patient_responsibility": 45.00,
            "eligible_subtotal": 0,
            "document_type": "eob",
        }
        parsed.update(amounts)
        return parsed

    @pytest.mark.parametrize("value", NOT_SHOWN)
    def test_receipt_amount_not_shown_is_none(self, extractor, value):
        receipt = extractor._build_receipt(self._eob(billed_amount=value, insurance_paid=value))
        assert receipt.billed_amount is None
        assert receipt.insurance_paid is None
        assert receipt.patient_responsibility == 45.00

    def test_receipt_amount_keys_missing_is_none(self, extractor):
        receipt = extractor._build_receipt(self._eob())
        assert receipt.billed_amount is None
        assert receipt.insurance_paid is None

    @pytest.mark.parametrize("value", ZERO)
    def test_receipt_explicit_zero_stays_zero(self, extractor, value):
        receipt = extractor._build_receipt(self._eob(billed_amount=value, insurance_paid=value))
        assert receipt.billed_amount == 0.0
        assert receipt.insurance_paid == 0.0

    def test_receipt_billed_falls_back_to_a_shown_subtotal_only(self, extractor):
        shown = extractor._build_receipt(self._eob(document_type="statement", eligible_subtotal=30))
        explicit = extractor._build_receipt(
            self._eob(document_type="statement", eligible_subtotal=30, billed_amount=0)
        )
        assert shown.billed_amount == 30.0
        assert explicit.billed_amount == 0.0

    @staticmethod
    def _claim(**amounts):
        claim = {
            "service_date": "2026-01-10",
            "patient_name": "Alice",
            "original_provider": "Clinic",
            "service_type": "Visit",
            "patient_responsibility": 20.00,
        }
        claim.update(amounts)
        return claim

    @pytest.mark.parametrize("value", NOT_SHOWN)
    def test_claim_amount_not_shown_is_none(self, extractor, value):
        result = extractor._build_multi_claim_extraction(
            {"claims": [self._claim(billed_amount=value, insurance_paid=value)]}
        )
        claim = result.claims[0]
        assert claim.billed_amount is None
        assert claim.insurance_paid is None
        assert claim.patient_responsibility == 20.00

    def test_claim_amount_keys_missing_is_none(self, extractor):
        claim = extractor._build_multi_claim_extraction({"claims": [self._claim()]}).claims[0]
        assert claim.billed_amount is None
        assert claim.insurance_paid is None

    @pytest.mark.parametrize("value", ZERO)
    def test_claim_explicit_zero_stays_zero(self, extractor, value):
        result = extractor._build_multi_claim_extraction(
            {"claims": [self._claim(billed_amount=value, insurance_paid=value)]}
        )
        assert result.claims[0].billed_amount == 0.0
        assert result.claims[0].insurance_paid == 0.0

    def test_payment_summary_without_plan_share_is_none(self, extractor):
        parsed = {"payment_summary": [{"patient": "Alice", "provider": "Clinic", "your_share": 12}]}
        claim = extractor._build_multi_claim_extraction(parsed).claims[0]
        assert claim.insurance_paid is None
        assert claim.billed_amount is None
        assert claim.patient_responsibility == 12.0

    def test_payment_summary_explicit_zero_plan_share_stays_zero(self, extractor):
        parsed = {
            "payment_summary": [
                {"patient": "Alice", "provider": "Clinic", "your_share": 12, "plan_share": 0}
            ]
        }
        assert extractor._build_multi_claim_extraction(parsed).claims[0].insurance_paid == 0.0

    def test_services_without_billed_leave_billed_and_insurance_blank(self, extractor):
        parsed = {
            "services": [
                {
                    "patient": "Alice",
                    "service_details": [
                        {"date": "2026-01-10", "provider": "Clinic", "your_cost": 10},
                        {
                            "date": "2026-01-11",
                            "provider": "Clinic",
                            "your_cost": 10,
                            "amount_billed": 40,
                        },
                    ],
                }
            ]
        }
        blank, shown = extractor._build_multi_claim_extraction(parsed).claims
        assert (blank.billed_amount, blank.insurance_paid) == (None, None)
        assert (shown.billed_amount, shown.insurance_paid) == (40.0, 30.0)

    @staticmethod
    def _xlsx(tmp_path, total_cost):
        import openpyxl

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(
            [
                "Fullname With YOB",
                "Prescription Number",
                "Drug Name",
                "Drug Strength",
                "Days Supply",
                "Quantity",
                "Pharmacy Name",
                "Date Of Service",
                "Total cost",
                "Total you paid",
            ]
        )
        ws.append(
            ["Alice (1990)", "RX1", "Drug", "10mg", 30, 30, "Pharm", "01/10/2026", total_cost, 5]
        )
        path = tmp_path / "claims.xlsx"
        wb.save(path)
        return path

    def test_xlsx_empty_total_cost_leaves_billed_and_insurance_blank(self, extractor, tmp_path):
        claim = extractor._extract_xlsx_claims(self._xlsx(tmp_path, None)).claims[0]
        assert (claim.billed_amount, claim.insurance_paid) == (None, None)
        assert claim.patient_responsibility == 5.0

    def test_xlsx_shown_total_cost_derives_insurance(self, extractor, tmp_path):
        claim = extractor._extract_xlsx_claims(self._xlsx(tmp_path, 25)).claims[0]
        assert (claim.billed_amount, claim.insurance_paid) == (25.0, 20.0)


class TestMockExtractor:
    """Test the MockVisionExtractor for testing purposes."""

    def test_mock_extractor_returns_fixed_data(self, mock_extractor):
        """Mock extractor returns predictable test data."""
        result = mock_extractor.extract("/fake/path.pdf")
        assert result.provider_name == "Mock Provider"
        assert result.confidence_score == 0.95
        assert result.raw_extraction.get("mock") is True


class TestDetectPatientHint:
    """Tests for the filename-based patient hint detector."""

    FAMILY = ["Alice", "Bob", "Christopher"]
    ALIASES = {"tori": "Victoria", "chris": "Christopher"}

    def test_direct_family_member_match(self):
        assert detect_patient_hint("alice_dental_2026.pdf", self.FAMILY) == "Alice"

    def test_alias_resolves_to_canonical(self):
        assert detect_patient_hint("tori_eyeglasses.pdf", self.FAMILY, self.ALIASES) == "Victoria"

    def test_alias_for_existing_canonical(self):
        """`chris` alias should resolve to `Christopher`, not the literal `Chris`."""
        assert (
            detect_patient_hint("amazon_chris_eyedrops.pdf", self.FAMILY, self.ALIASES)
            == "Christopher"
        )

    def test_no_match_returns_none(self):
        assert detect_patient_hint("amazon_receipt.pdf", self.FAMILY, self.ALIASES) is None

    def test_token_boundary_prevents_substring_match(self):
        """`amazon` must not match `ama` — token-based, not substring."""
        # "amazon" tokenizes to {"amazon", "receipt"} — neither is "ama".
        assert detect_patient_hint("amazon.pdf", ["Amabelle"], {"ama": "Amabelle"}) is None

    def test_case_insensitive(self):
        assert detect_patient_hint("ALICE_RX.PDF", self.FAMILY) == "Alice"
        assert detect_patient_hint("Tori_2026.PDF", self.FAMILY, self.ALIASES) == "Victoria"

    def test_separators_dot_dash_underscore_space(self):
        for fname in (
            "alice.dental.pdf",
            "alice-dental.pdf",
            "alice_dental.pdf",
            "alice dental.pdf",
        ):
            assert detect_patient_hint(fname, self.FAMILY) == "Alice", fname

    def test_no_aliases_provided(self):
        """Aliases default to None — direct match still works."""
        assert detect_patient_hint("bob_lab.pdf", self.FAMILY) == "Bob"

    def test_family_name_and_conflicting_alias_are_ambiguous(self):
        """A name and an alias on the same span can name different patients."""
        # Build a config where alias points elsewhere.
        family = ["Alice", "Victoria"]
        aliases = {"alice": "Victoria"}  # contrived: "alice" alias → "Victoria"
        # The same spelling points to two different patients.
        assert detect_patient_hint("alice_visit.pdf", family, aliases) is None


@pytest.mark.parametrize(
    "filename,names,expected",
    [
        ("CVS_Alice_rx.jpg", ["Alice"], "Alice"),
        ("Name2026.pdf", ["Name"], "Name"),
        ("Alice_Bob_shared.pdf", ["Alice", "Bob"], None),
        ("amazon_receipt.pdf", ["Ama"], None),
        ("rx_mary-ann.pdf", ["Mary", "Mary Ann"], "Mary Ann"),
        ("aLiCe.pdf", ["Alice"], "Alice"),
        ("Alice_Alice.pdf", ["Alice", "Alice"], "Alice"),
        ("éBob.pdf", ["Bob"], None),
        ("Bobé.pdf", ["Bob"], None),
        ("2026Bob3.pdf", ["Bob"], "Bob"),
        ("Mary__Ann.pdf", ["Mary Ann"], "Mary Ann"),
        ("Mary Ann.pdf", ["Mary Ann"], "Mary Ann"),
        ("Mary.Ann.pdf", ["Mary Ann"], "Mary Ann"),
        ("Mary2Ann.pdf", ["Mary Ann"], None),
        ("Mary_Ann_Bob.pdf", ["Mary", "Mary Ann", "Bob"], None),
        ("bob.pdf", ["", "  ", "Bob"], "Bob"),
        ("123.pdf", ["  "], None),
        ("rx C++ rx.pdf", ["C++"], "C++"),
        ("rx Cxx rx.pdf", ["C++"], None),
        ("receipt.Alice", ["Alice"], "Alice"),
    ],
)
def test_shared_patient_hint(filename, names, expected):
    watcher = DriveInboxWatcher(None, lambda *_: None, family_names=names)
    assert watcher._extract_patient_hint(filename) == expected
    assert detect_patient_hint(filename, names) == expected


@pytest.mark.parametrize(
    "filename,names,aliases,expected",
    [
        ("tori.pdf", ["Alice"], {"tori": "Victoria"}, "Victoria"),
        ("tori_Victoria.pdf", ["Victoria"], {"tori": "Victoria"}, "Victoria"),
        ("tori_Alice.pdf", ["Alice"], {"tori": "Victoria"}, None),
        ("tori_t.pdf", [], {"tori": "Victoria", "t": "Victoria"}, "Victoria"),
    ],
)
def test_patient_hint_aliases(filename, names, aliases, expected):
    assert detect_patient_hint(filename, names, aliases) == expected


class TestMapPatientNameAliasPath:
    """Tests for VisionExtractor._map_patient_name alias resolution."""

    @pytest.fixture
    def extractor(self):
        return VisionExtractor(
            family_members=["Alice", "Bob", "Christopher"],
            family_aliases={"Tori": "Victoria", "Chris": "Christopher"},
        )

    def test_alias_resolves(self, extractor):
        # `Tori` is not a family member — must resolve via alias to `Victoria`.
        assert extractor._map_patient_name("Tori") == "Victoria"

    def test_alias_case_insensitive(self, extractor):
        assert extractor._map_patient_name("TORI") == "Victoria"

    def test_alias_substring(self, extractor):
        # Alias matched as substring (LLM returned full string with alias inside).
        assert extractor._map_patient_name("Patient: Tori Lee") == "Victoria"

    def test_canonical_name_beats_alias(self, extractor):
        """Canonical match resolves before alias check, so 'Christopher' returns 'Christopher'."""
        assert extractor._map_patient_name("Christopher") == "Christopher"

    def test_positional_self_used_when_no_alias_match(self, extractor):
        """`(self)` falls through to positional → first family member."""
        assert extractor._map_patient_name("(self)") == "Alice"

    def test_aliases_lowercased_at_construction(self):
        """Aliases passed with mixed case are stored lowercase, still match."""
        ext = VisionExtractor(family_members=["Alice"], family_aliases={"NICK": "Alice"})
        assert "nick" in ext.family_aliases
        assert "NICK" not in ext.family_aliases


class TestBuildReceiptPatientNormalization:
    """Tests for _build_receipt patient_name normalization via aliases / hint."""

    @pytest.fixture
    def extractor(self):
        return VisionExtractor(
            family_members=["Alice", "Bob", "Christopher"],
            family_aliases={"chris": "Christopher"},
        )

    def _base_parsed(self, **overrides) -> dict:
        parsed = {
            "provider_name": "Test Clinic",
            "service_date": "2026-01-04",
            "service_type": "Visit",
            "patient_name": "Alice",
            "billed_amount": 100.0,
            "insurance_paid": 80.0,
            "patient_responsibility": 20.0,
            "hsa_eligible": True,
            "category": "medical",
            "document_type": "eob",
            "confidence_score": 0.9,
            "notes": "",
        }
        parsed.update(overrides)
        return parsed

    def test_canonical_name_passes_through(self, extractor):
        receipt = extractor._build_receipt(self._base_parsed(patient_name="Alice"))
        assert receipt.patient_name == "Alice"

    def test_alias_normalized_to_canonical(self, extractor):
        """LLM returned alias `Chris` → must land on canonical `Christopher`."""
        receipt = extractor._build_receipt(self._base_parsed(patient_name="Chris"))
        assert receipt.patient_name == "Christopher"

    def test_full_name_stripped_to_canonical(self, extractor):
        """LLM returned `Alice Smith` → substring match yields `Alice`."""
        receipt = extractor._build_receipt(self._base_parsed(patient_name="Alice Smith"))
        assert receipt.patient_name == "Alice"

    def test_filename_hint_used_when_llm_returned_blank(self, extractor):
        """Empty patient_name with active hint → hint wins."""
        extractor._current_patient_hint = "Christopher"
        receipt = extractor._build_receipt(self._base_parsed(patient_name=""))
        assert receipt.patient_name == "Christopher"

    def test_blank_with_no_hint_falls_back_to_unknown(self, extractor):
        extractor._current_patient_hint = None
        receipt = extractor._build_receipt(self._base_parsed(patient_name=""))
        assert receipt.patient_name == "Unknown"

    def test_llm_value_wins_over_hint_when_both_present(self, extractor):
        """If LLM returned a real value, hint is not consulted (existing precedence)."""
        extractor._current_patient_hint = "Christopher"
        receipt = extractor._build_receipt(self._base_parsed(patient_name="Alice"))
        assert receipt.patient_name == "Alice"

    def test_literal_unknown_falls_back_to_hint(self, extractor):
        """LLM returning literal 'Unknown' must defer to filename hint, not silently
        map to the first family member via positional fallback."""
        extractor._current_patient_hint = "Christopher"
        receipt = extractor._build_receipt(self._base_parsed(patient_name="Unknown"))
        assert receipt.patient_name == "Christopher"

    def test_literal_unknown_with_no_hint_stays_unknown(self, extractor):
        """LLM returned 'Unknown' and no filename hint → preserve 'Unknown'."""
        extractor._current_patient_hint = None
        receipt = extractor._build_receipt(self._base_parsed(patient_name="Unknown"))
        assert receipt.patient_name == "Unknown"


class TestReconcileAmounts:
    """#112: a five-procedure Delta Dental EOB was recorded at its first line's subtotal."""

    DELTA = {
        "provider_name": "Delta Dental",
        "document_type": "eob",
        "category": "dental",
        "patient_name": "Alice",
        "billed_amount": 4050.00,
        "insurance_paid": 1329.30,
        "line_items": [
            {"description": "D6010 implant", "patient_cost": 803.20},
            {"description": "D0366 cone beam CT", "patient_cost": 145.00},
            {"description": "D6011 second stage", "patient_cost": 0.00},
            {"description": "D9310 consultation", "patient_cost": 14.50},
            {"description": "D0330 panoramic", "patient_cost": 0.00},
        ],
        "stated_patient_total": 962.70,
    }

    @pytest.fixture
    def extractor(self):
        from src.processors.llm_extractor import VisionExtractor

        return VisionExtractor()

    def test_first_line_subtotal_as_total_is_flagged_with_both_figures(self, extractor):
        receipt = extractor._build_receipt({**self.DELTA, "patient_responsibility": 803.20})

        assert receipt.patient_responsibility == 803.20  # recorded as extracted, never "fixed"
        assert receipt.notes.startswith("[Amounts do not reconcile: recorded $803.20")
        assert "5 line items add up to $962.70" in receipt.notes
        assert "printed total is $962.70" in receipt.notes

    def test_matching_total_is_not_flagged(self, extractor):
        receipt = extractor._build_receipt({**self.DELTA, "patient_responsibility": 962.70})

        assert "Amounts do not reconcile" not in receipt.notes

    def test_printed_total_alone_is_enough(self, extractor):
        parsed = {**self.DELTA, "line_items": [], "patient_responsibility": 803.20}

        assert "printed total is $962.70" in extractor._build_receipt(parsed).notes

    def test_amounts_printed_as_text_are_still_compared(self, extractor):
        parsed = {
            **self.DELTA,
            "stated_patient_total": "$962.70",
            "line_items": [{"patient_cost": "$1,803.20"}, {"patient_cost": "145.00"}],
            "patient_responsibility": 803.20,
        }

        notes = extractor._build_receipt(parsed).notes

        assert "printed total is $962.70" in notes
        assert "2 line items add up to $1,948.20" in notes

    @pytest.mark.parametrize(
        "recorded,printed", [(803.20, 803.21), (100.00, 100.01), (0.29, 0.30), (1329.30, 1329.29)]
    )
    def test_one_cent_difference_is_always_flagged(self, recorded, printed):
        from src.processors.llm_extractor import reconcile_amounts

        assert reconcile_amounts({"stated_patient_total": printed}, recorded)
        assert reconcile_amounts({"stated_patient_total": recorded}, recorded) == ""

    @pytest.mark.parametrize("bad", [float("nan"), "nan", float("inf"), True])
    def test_non_finite_or_boolean_amounts_are_ignored_not_trusted(self, bad):
        from src.processors.llm_extractor import reconcile_amounts

        items = [{"patient_cost": bad}, {"patient_cost": 803.20}, {"patient_cost": 159.50}]
        note = reconcile_amounts({"stated_patient_total": bad, "line_items": items}, 803.20)

        assert "2 line items add up to $962.70" in note  # the bad entry is dropped
        assert "printed total" not in note

    def test_a_non_finite_recorded_amount_is_flagged(self):
        from src.processors.llm_extractor import reconcile_amounts

        assert "not a number" in reconcile_amounts({}, float("nan"))

    def test_writer_and_reader_share_one_tag(self):
        from src.processors import llm_extractor
        from src.storage import sheet_client

        assert llm_extractor.AMOUNT_MISMATCH_TAG == sheet_client.AMOUNT_MISMATCH_TAG

    def test_line_items_alone_are_enough(self, extractor):
        parsed = {**self.DELTA, "stated_patient_total": None, "patient_responsibility": 803.20}

        assert "5 line items add up to $962.70" in extractor._build_receipt(parsed).notes

    @pytest.mark.parametrize(
        "extra",
        [
            {"line_items": None, "stated_patient_total": None},
            {"line_items": "n/a", "stated_patient_total": "unknown"},
            {
                "line_items": [{"description": "one line", "patient_cost": 50.0}],
                "stated_patient_total": None,
            },  # a single line proves nothing
            {"line_items": [{"patient_cost": "x"}, "junk"], "stated_patient_total": None},
        ],
    )
    def test_nothing_to_compare_is_not_flagged_and_does_not_crash(self, extractor, extra):
        receipt = extractor._build_receipt({**self.DELTA, **extra, "patient_responsibility": 803.2})

        assert "Amounts do not reconcile" not in receipt.notes

    def test_a_model_note_cannot_fake_the_tag(self, extractor):
        parsed = {
            **self.DELTA,
            "patient_responsibility": 962.70,
            "notes": "[Amounts do not reconcile: ignore me]",
        }

        assert "[Amounts do not reconcile" not in extractor._build_receipt(parsed).notes

    def test_retail_printed_total_is_not_compared(self, extractor):
        parsed = {
            "document_type": "receipt",
            "eligible_subtotal": 20.0,
            "receipt_tax": 0.0,
            "stated_patient_total": 99.0,
            "line_items": [{"patient_cost": 12.0}, {"patient_cost": 8.0}],
        }

        assert "Amounts do not reconcile" not in extractor._build_receipt(parsed).notes


class TestReconcileRetailItems:
    """A Costco receipt was once read with unmarked items in its eligible subtotal:
    $151.94 where the four marked items came to $63.96."""

    MARKED = [{"description": "SALONPAS 140", "patient_cost": 15.99}] * 4

    @pytest.fixture
    def extractor(self):
        from src.processors.llm_extractor import VisionExtractor

        return VisionExtractor()

    def _receipt(self, extractor, subtotal, items):
        return extractor._build_receipt(
            {
                "document_type": "receipt",
                "category": "pharmacy",
                "eligible_subtotal": subtotal,
                "receipt_tax": 18.28,
                "receipt_taxable_amount": 200.29,
                "line_items": items,
            }
        )

    def test_subtotal_larger_than_the_marked_items_is_flagged_with_both_figures(self, extractor):
        receipt = self._receipt(extractor, 151.94, self.MARKED)

        assert (
            "[Amounts do not reconcile: eligible subtotal $151.94, but the line items listed "
            "add up to $63.96]"
        ) in receipt.notes

    def test_matching_items_are_not_flagged_and_the_total_is_unchanged(self, extractor):
        receipt = self._receipt(extractor, 63.96, self.MARKED)

        assert "Amounts do not reconcile" not in receipt.notes
        assert receipt.patient_responsibility == pytest.approx(69.80, abs=0.01)

    def test_one_marked_item_is_enough_to_compare(self, extractor):
        receipt = self._receipt(extractor, 30.00, [{"patient_cost": 15.99}])

        assert "the line items listed add up to $15.99" in receipt.notes

    @pytest.mark.parametrize("items", [[], None, "n/a", [{"patient_cost": "x"}]])
    def test_no_usable_items_is_not_flagged(self, extractor, items):
        assert "Amounts do not reconcile" not in self._receipt(extractor, 63.96, items).notes

    def test_the_run_that_added_unmarked_items_is_flagged(self, extractor):
        """2026-11-10: the model listed two unmarked supplements and reported a subtotal
        that was not even the sum of its own list."""
        items = [
            {"description": "4x Salonpas @$15.99", "patient_cost": 63.96},
            {"description": "2x NM COQ 140CT @$37.99", "patient_cost": 75.98},
            {"description": "2x TN GINK 340 @$14.99", "patient_cost": 29.98},
        ]

        notes = self._receipt(extractor, 153.92, items).notes

        assert "eligible subtotal $153.92, but the line items listed add up to $169.92" in notes

    def _from_service_type(self, extractor, subtotal, service_type):
        return extractor._build_receipt(
            {
                "document_type": "receipt",
                "eligible_subtotal": subtotal,
                "receipt_tax": 18.28,
                "receipt_taxable_amount": 200.29,
                "line_items": [],
                "service_type": service_type,
            }
        )

    def test_items_are_read_from_service_type_when_line_items_is_empty(self, extractor):
        ok = self._from_service_type(extractor, 63.96, "4x Salonpas @$15.99")
        bad = self._from_service_type(
            extractor,
            153.92,
            "4x Salonpas @$15.99, 2x NM COQ 140CT @$37.99, 2x TN GINK 340 @$14.99",
        )

        assert "Amounts do not reconcile" not in ok.notes
        assert "the quantity x price entries listed add up to $169.92" in bad.notes

    @pytest.mark.parametrize("text", ["Salonpas pain patches", "", None, ["Tylenol", "Advil"]])
    def test_service_type_without_quantities_and_prices_is_not_flagged(self, extractor, text):
        assert (
            "Amounts do not reconcile" not in self._from_service_type(extractor, 63.96, text).notes
        )

    def test_a_description_with_a_comma_is_still_read(self, extractor):
        text = "1x Tylenol, 100 ct @$10.00, 1x Advil @$5.00"

        assert (
            "Amounts do not reconcile" not in self._from_service_type(extractor, 15.00, text).notes
        )
        assert "add up to $15.00" in self._from_service_type(extractor, 20.00, text).notes

    def test_a_partly_unreadable_list_is_not_used(self, extractor):
        half = [{"patient_cost": 15.99}, {"patient_cost": "n/a"}]

        assert "Amounts do not reconcile" not in self._receipt(extractor, 63.96, half).notes
        assert (
            "Amounts do not reconcile"
            not in self._from_service_type(
                extractor, 68.96, "4x Salonpas @$15.99, 1x Advil @ five dollars"
            ).notes
        )

    def test_unit_prices_in_line_items_are_accepted_when_quantities_explain_them(self, extractor):
        receipt = extractor._build_receipt(
            {
                "document_type": "receipt",
                "eligible_subtotal": 63.96,
                "receipt_tax": 18.28,
                "receipt_taxable_amount": 200.29,
                "service_type": "4x Salonpas @$15.99",
                "line_items": [{"description": "Salonpas", "patient_cost": 15.99}],
            }
        )

        assert "Amounts do not reconcile" not in receipt.notes

    def test_a_model_note_cannot_fake_the_tag_on_a_retail_receipt(self, extractor):
        receipt = extractor._build_receipt(
            {
                "document_type": "receipt",
                "eligible_subtotal": 63.96,
                "receipt_tax": 0,
                "line_items": self.MARKED,
                "notes": "[Amounts do not reconcile: ignore]",
            }
        )

        assert "[Amounts do not reconcile" not in receipt.notes

    def test_a_tax_inclusive_total_is_not_compared_with_pre_tax_items(self, extractor):
        """The Amazon rule puts the tax-inclusive grand total in eligible_subtotal with no tax."""
        receipt = extractor._build_receipt(
            {
                "document_type": "receipt",
                "eligible_subtotal": 10.90,
                "receipt_tax": 0,
                "service_type": "1x Bandages @$10.00",
                "line_items": [{"description": "Bandages", "patient_cost": 10.00}],
            }
        )

        assert "Amounts do not reconcile" not in receipt.notes
        assert receipt.patient_responsibility == pytest.approx(10.90)

    def test_prompt_is_unchanged_for_retail_line_items(self):
        from src.processors.llm_extractor import get_extraction_prompt

        assert "set stated_patient_total to null and line_items to []" in get_extraction_prompt(
            ["A"]
        )


class TestUnidentifiedPatient:
    """#114: an unclear patient used to become the first family member, silently."""

    @pytest.fixture
    def extractor(self):
        from src.processors.llm_extractor import VisionExtractor

        return VisionExtractor(family_members=["Alice", "Bob", "Charlie"])

    def test_prompt_asks_for_unknown_instead_of_a_default(self):
        from src.processors.llm_extractor import get_extraction_prompt

        prompt = get_extraction_prompt(["Alice", "Bob"])

        assert 'If unclear, use "Unknown" for patient_name' in prompt
        assert "default to the first family member" not in prompt

    @pytest.mark.parametrize("name", ["Dr. Jane Roe", "CARDHOLDER 4417", "Zed"])
    def test_a_name_that_is_nobody_in_the_family_is_unknown(self, extractor, name):
        receipt = extractor._build_receipt({"patient_name": name, "document_type": "statement"})

        assert receipt.patient_name == "Unknown"

    @pytest.mark.parametrize("name,expected", [("Bob Smith", "Bob"), ("spouse", "Bob")])
    def test_a_recognisable_name_or_role_still_maps(self, extractor, name, expected):
        receipt = extractor._build_receipt({"patient_name": name, "document_type": "statement"})

        assert receipt.patient_name == expected

    def test_eob_mapping_keeps_its_fallback(self, extractor):
        assert extractor._map_patient_name("Zed") == "Alice"
        assert extractor._match_patient_name("Zed") is None


class TestUnidentifiedPatientOnMultiClaim:
    @pytest.fixture
    def extractor(self):
        from src.processors.llm_extractor import VisionExtractor

        return VisionExtractor(family_members=["Alice", "Bob", "Charlie"])

    @pytest.mark.parametrize(
        "name,expected", [("Dr. Jane Roe", "Unknown"), ("", "Unknown"), ("Bob Smith", "Bob")]
    )
    def test_claim_patient_is_unknown_unless_it_names_a_family_member(
        self, extractor, name, expected
    ):
        doc = extractor._build_multi_claim_extraction(
            {
                "claims": [
                    {
                        "service_date": "2026-02-01",
                        "patient_name": name,
                        "patient_responsibility": 10.0,
                    }
                ]
            }
        )

        assert [c.patient_name for c in doc.claims] == [expected]


class TestAmazonOrderPdf:
    LAYOUT_A = """Order Summary
Order placed October 29, 2026 Order # 111-2222222-3333333
Ship to Payment method Order Summary
Pat Example Prime Visa Item(s) Subtotal: $11.64
123 EXAMPLE ST UNIT 1 Shipping & Handling: $0.00
EXAMPLE CITY, CA 90000-0000 Subscribe & Save: -$1.75
United States Your Coupon Savings: -$4.07
Total before tax: $5.82
Estimated tax to be $0.57
collected:
Grand Total: $6.39
FSA or HSA eligible: $6.39
(inc. tax and shipping)
Delivered November 2
Example Antiseptic Skin Cleanser, 8 oz with Foaming Pump
Sold by: Amazon.com
$11.64
FSA or HSA eligible
"""
    LAYOUT_B = """Order Summary
Order placed October 18, 2026 Order # 111-2222222-3333334
Ship to Payment method Order Summary
Pat Example Amazon Gi! Card Item(s) Subtotal: $38.94
123 EXAMPLE ST UNIT 1 $3.61 balance applied Shipping & Handling: $0.00
EXAMPLE CITY, CA 90000-0000 Prime Visa Multibuy Discount: -$7.79
United States Subscribe & Save: -$5.84
Total before tax: $25.31
View related transactions
Estimated tax to be $2.46
collected:
Gift Card Amount: -$3.61
Grand Total: $24.16
FSA or HSA eligible: $27.77
(inc. tax and shipping)
Example Preservative Free Dry Eye Drops
FSA or HSA eligible
"""

    @pytest.fixture
    def run_extract(self, tmp_path, monkeypatch):
        import json
        from types import SimpleNamespace
        from unittest.mock import Mock

        def run(
            text,
            filename="PDF document.pdf",
            amount=12.78,
            patient="Unknown",
            fail=False,
            multipage=False,
            notes="Tax rate 9.8% applied to eligible items.",
        ):
            extractor = VisionExtractor(
                family_members=["Alice", "Bob", "Christopher"],
                family_aliases={"chris": "Christopher"},
            )
            parsed = {
                "provider_name": "Amazon.com",
                "service_date": "2026-01-01",
                "service_type": "1x Cleanser @$11.64",
                "patient_name": patient,
                "billed_amount": 11.64,
                "insurance_paid": 0,
                "patient_responsibility": amount,
                "eligible_subtotal": 11.64,
                "receipt_tax": 1.14,
                "receipt_taxable_amount": 11.64,
                "hsa_eligible": True,
                "category": "pharmacy",
                "document_type": "receipt",
                "confidence_score": 0.95,
                "notes": notes,
            }
            # Isolate a model-provided amount while still exercising retail tax post-processing.
            if amount != 12.78:
                parsed.update(eligible_subtotal=0, receipt_tax=0, receipt_taxable_amount=0)
            response = SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(parsed)))]
            )
            create = (
                Mock(side_effect=RuntimeError("model failed"))
                if fail
                else Mock(return_value=response)
            )
            client = SimpleNamespace(
                chat=SimpleNamespace(completions=SimpleNamespace(create=create))
            )
            monkeypatch.setattr(extractor, "_init_client", lambda: client)
            # No declared development dependency creates a text-layer PDF.
            monkeypatch.setattr(extractor, "_extract_text_with_pdfplumber", lambda path: text)
            images = [tmp_path / "page1.png", tmp_path / "page2.png"] if multipage else []
            monkeypatch.setattr(extractor, "_convert_pdf_to_images", lambda path: images)
            if multipage:
                monkeypatch.setattr(
                    extractor, "extract_from_image", Mock(side_effect=AssertionError("extra call"))
                )
            pdf = tmp_path / filename
            pdf.touch()
            result = extractor.extract(pdf)
            return result, create, parsed, extractor

        return run

    def test_content_selects_amazon_and_page_amount_survives_retail_processing(self, run_extract):
        receipt, create, _, _ = run_extract(self.LAYOUT_A)

        assert round(receipt.patient_responsibility * 100) == 639
        assert round(receipt.billed_amount * 100) == 1164
        assert receipt.insurance_paid == 0
        assert receipt.provider_name == "Amazon"
        assert receipt.service_date == "2026-10-29"
        assert receipt.document_type == "receipt"
        assert receipt.hsa_eligible is True
        assert receipt.confidence_score == 0.95
        assert (
            "[Amazon order 111-2222222-3333333: eligible $6.39 read from the page; grand total $6.39]"
            in receipt.notes
        )
        assert "tax rate" not in receipt.notes.lower()
        assert "[Amounts do not reconcile" not in receipt.notes
        create.assert_called_once()
        assert "AMAZON ORDER RULES" in create.call_args.kwargs["messages"][0]["content"][0]["text"]

    def test_gift_card_does_not_reduce_eligible_total(self, run_extract):
        receipt, create, _, _ = run_extract(self.LAYOUT_B)

        assert round(receipt.patient_responsibility * 100) == 2777
        assert "grand total $24.16; gift card $3.61 applied]" in receipt.notes
        create.assert_called_once()

    def test_page_without_items_subtotal_leaves_billed_blank(self, run_extract):
        layout = self.LAYOUT_A.replace(" Item(s) Subtotal: $11.64", "")
        receipt, _, _, _ = run_extract(layout)

        assert receipt.provider_name == "Amazon"
        assert round(receipt.patient_responsibility * 100) == 639
        assert receipt.billed_amount is None
        assert receipt.insurance_paid == 0

    @pytest.mark.parametrize("wrong_amount", [0, 9.99, 123.45])
    def test_page_amount_overrides_model_amount(self, run_extract, wrong_amount):
        receipt, create, _, _ = run_extract(self.LAYOUT_A, amount=wrong_amount)

        assert round(receipt.patient_responsibility * 100) == 639
        create.assert_called_once()

    def test_missing_summary_keeps_model_amount_and_flags_review(self, run_extract):
        from src.storage.sheet_client import _needs_amount_review

        text = self.LAYOUT_A.replace("FSA or HSA eligible: $6.39\n", "")
        receipt, create, _, _ = run_extract(text)

        assert round(receipt.patient_responsibility * 100) == 1278
        assert (
            '[Amounts do not reconcile: no "FSA or HSA eligible" total on this Amazon page; amount not read from the page]'
            in receipt.notes
        )
        assert receipt.confidence_score <= 0.5
        assert _needs_amount_review({"Notes": receipt.notes})
        create.assert_called_once()
        assert "AMAZON ORDER RULES" in create.call_args.kwargs["messages"][0]["content"][0]["text"]

    def test_inconsistent_page_keeps_page_amount_and_flags_review(self, run_extract):
        text = self.LAYOUT_A.replace("Grand Total: $6.39", "Grand Total: $6.40")
        receipt, create, _, _ = run_extract(text)

        assert round(receipt.patient_responsibility * 100) == 639
        assert "[Amounts do not reconcile:" in receipt.notes
        assert receipt.confidence_score <= 0.5
        create.assert_called_once()

    def test_missing_summary_also_reports_arithmetic_problems(self, run_extract):
        text = self.LAYOUT_A.replace("FSA or HSA eligible: $6.39\n", "").replace(
            "Grand Total: $6.39", "Grand Total: $6.40"
        )
        receipt, _, _, _ = run_extract(text)

        assert receipt.notes.count("[Amounts do not reconcile:") >= 2
        assert 'no "FSA or HSA eligible" total' in receipt.notes

    def test_one_line_tax_inconsistent_amount_requires_review(self, run_extract):
        from src.storage.sheet_client import _needs_amount_review

        text = (
            self.LAYOUT_A.replace(
                "Estimated tax to be $0.57\ncollected:",
                "Estimated tax to be collected: $0.57",
            )
            .replace("Grand Total: $6.39", "Grand Total: $60.39")
            .replace("FSA or HSA eligible: $6.39", "FSA or HSA eligible: $60.39")
        )
        receipt, create, _, _ = run_extract(text)

        assert round(receipt.patient_responsibility * 100) == 6039
        assert receipt.confidence_score <= 0.5
        assert _needs_amount_review({"Notes": receipt.notes})
        create.assert_called_once()

    def test_model_written_reconcile_tag_does_not_route_a_clean_page_to_review(self, run_extract):
        from src.storage.sheet_client import _needs_amount_review

        receipt, _, _, _ = run_extract(
            self.LAYOUT_A,
            notes="[Amounts do not reconcile: the model made this up] Item is eligible.",
        )
        assert "[Amazon order" in receipt.notes
        assert "Item is eligible" in receipt.notes
        assert not _needs_amount_review({"Notes": receipt.notes})

    def test_clean_amazon_information_tag_does_not_require_review(self, run_extract):
        from src.storage.sheet_client import _needs_amount_review

        receipt, _, _, _ = run_extract(self.LAYOUT_A)
        assert "[Amazon order" in receipt.notes
        assert not _needs_amount_review({"Notes": receipt.notes})

    @pytest.mark.parametrize(
        "filename,amazon_skill",
        [("amazon_invoice_x.pdf", True), ("pharmacy.pdf", False)],
    )
    def test_non_order_receipt_matches_original_model_path(
        self, run_extract, filename, amazon_skill
    ):
        receipt, create, parsed, extractor = run_extract(
            "Pharmacy receipt: medicine $12.78, paid by card.", filename=filename
        )

        assert receipt == extractor._build_receipt(parsed)
        prompt = create.call_args.kwargs["messages"][0]["content"][0]["text"]
        assert ("AMAZON ORDER RULES" in prompt) is amazon_skill
        assert "[Amazon order" not in receipt.notes
        assert "[Check:" not in receipt.notes
        create.assert_called_once()

    def test_filename_patient_hint_survives_content_detection(self, run_extract):
        receipt, create, _, _ = run_extract(self.LAYOUT_A, filename="chris_receipt.pdf")

        assert receipt.patient_name == "Christopher"
        prompt = create.call_args.kwargs["messages"][0]["content"][0]["text"]
        assert 'FILENAME HINT: this file is named for "Christopher"' in prompt
        create.assert_called_once()

    @pytest.mark.parametrize(
        "line", ["Grand Total: $6.39\n", "Pat Example Prime Visa Item(s) Subtotal: $11.64\n"]
    )
    def test_missing_page_total_does_not_crash(self, run_extract, line):
        receipt, create, _, _ = run_extract(self.LAYOUT_A.replace(line, ""))

        assert receipt is not None
        create.assert_called_once()

    def test_model_failure_keeps_existing_fallback(self, run_extract):
        receipt, create, _, _ = run_extract(self.LAYOUT_A, fail=True)

        assert receipt.provider_name == "Unknown (Extraction Failed)"
        assert receipt.confidence_score == 0.1
        assert receipt.patient_responsibility == 0
        create.assert_called_once()

    def test_model_failure_billed_is_blank(self, run_extract):
        receipt, _, _, _ = run_extract(self.LAYOUT_A, fail=True)
        assert receipt.billed_amount is None

    def test_model_failure_insurance_is_blank(self, run_extract):
        receipt, _, _, _ = run_extract(self.LAYOUT_A, fail=True)
        assert receipt.insurance_paid is None

    def test_model_failure_preserves_other_fallback_fields(self, run_extract):
        receipt, create, _, _ = run_extract(self.LAYOUT_A, fail=True)
        assert receipt.provider_name == "Unknown (Extraction Failed)"
        assert receipt.service_date is None
        assert receipt.service_type == "Unknown (Needs Manual Review)"
        assert receipt.patient_name == "Unknown"
        assert receipt.patient_responsibility == 0
        assert receipt.hsa_eligible is True
        assert receipt.category == "unknown"
        assert receipt.document_type == "unknown"
        assert receipt.confidence_score == 0.1
        assert receipt.notes == (
            "Vision extraction failed - manual review required. Source: text extraction"
        )
        assert receipt.raw_extraction == {}
        create.assert_called_once()

    def test_zero_eligible_multipage_does_not_call_model_again(self, run_extract):
        text = self.LAYOUT_A.replace("FSA or HSA eligible: $6.39", "FSA or HSA eligible: $0.00")
        receipt, create, _, _ = run_extract(text, multipage=True)

        assert receipt.patient_responsibility == 0
        assert receipt.hsa_eligible is False
        create.assert_called_once()

    def test_unparsed_eligible_marker_warns_and_tags(self, run_extract, caplog):
        caplog.set_level("WARNING")
        receipt, _, parsed, extractor = run_extract("FSA or HSA eligible: $5.00")
        assert (
            receipt.patient_responsibility
            == extractor._build_receipt(parsed).patient_responsibility
        )
        assert "Amazon order could not be parsed" in caplog.text
        assert "[Amounts do not reconcile: Amazon order could not be parsed]" in receipt.notes

    def test_unparsed_order_number_warns_and_tags(self, run_extract, caplog):
        caplog.set_level("WARNING")
        receipt, _, parsed, extractor = run_extract("Order 111-2222222-3333333")
        assert (
            receipt.patient_responsibility
            == extractor._build_receipt(parsed).patient_responsibility
        )
        assert "Amazon order could not be parsed" in caplog.text
        assert "[Amounts do not reconcile: Amazon order could not be parsed]" in receipt.notes

    @pytest.mark.parametrize("defect", ["date", "duplicate"])
    def test_invalid_order_warns_and_tags(self, run_extract, caplog, defect):
        caplog.set_level("WARNING")
        text = (
            self.LAYOUT_A.replace("October 29, 2026", "2026-10-29")
            if defect == "date"
            else self.LAYOUT_A + "\nGrand Total: $9.99\n"
        )
        receipt, _, _, _ = run_extract(text)
        assert "Amazon order could not be parsed" in caplog.text
        assert "[Amounts do not reconcile: Amazon order could not be parsed]" in receipt.notes

    def test_non_amazon_text_and_filename_do_not_warn(self, run_extract, caplog):
        caplog.set_level("WARNING")
        receipt, _, _, _ = run_extract("ordinary pharmacy receipt", filename="amazon.pdf")
        assert "Amazon order could not be parsed" not in caplog.text
        assert "[Amounts do not reconcile: Amazon order could not be parsed]" not in receipt.notes

    @pytest.mark.parametrize("notes", ["", "Existing note."], ids=["empty", "existing"])
    def test_unparsed_order_appends_exact_tag(self, run_extract, notes):
        receipt, _, _, _ = run_extract(
            "FSA or HSA eligible: $5.00", amount=10, patient="Alice", notes=notes
        )
        tag = "[Amounts do not reconcile: Amazon order could not be parsed]"
        assert receipt.notes == f"{notes} {tag}".strip()

    @pytest.mark.parametrize(
        "prefix",
        ["[Amounts do not reconcile", "[Patient not identified"],
        ids=["amount", "patient"],
    )
    def test_amazon_neutralizes_reserved_prefix(self, run_extract, prefix):
        receipt, _, _, _ = run_extract(self.LAYOUT_A, notes=[f"{prefix}: model]", "ordinary note"])
        assert prefix not in receipt.notes
        assert "ordinary note" in receipt.notes
        assert "[Amazon order" in receipt.notes

    def test_amazon_keeps_generated_mismatch_after_neutralization(self, run_extract):
        text = self.LAYOUT_A.replace("Grand Total: $6.39", "Grand Total: $6.40")
        receipt, _, _, _ = run_extract(text, notes="[Amounts do not reconcile: invented]")
        assert receipt.notes.count("[Amounts do not reconcile") >= 1
        assert "invented" in receipt.notes

    @pytest.mark.parametrize(
        "count,expected", [(0, None), (1, "1 eligible item"), (2, "2 eligible items")]
    )
    def test_eligible_item_count(self, run_extract, count, expected):
        text = self.LAYOUT_A.replace(
            "\nFSA or HSA eligible\n", "\n" + "FSA or HSA eligible\n" * count
        )
        receipt, _, _, _ = run_extract(text)
        if expected:
            assert expected in receipt.notes
        else:
            assert "eligible item" not in receipt.notes

    @pytest.mark.parametrize("amount,problem", [("-$1.00", True), ("$0.00", False)])
    def test_nonpositive_eligible_total_preserved(self, run_extract, amount, problem):
        text = self.LAYOUT_A.replace("FSA or HSA eligible: $6.39", f"FSA or HSA eligible: {amount}")
        receipt, _, _, _ = run_extract(text)
        assert receipt.patient_responsibility == float(amount.replace("$", ""))
        assert receipt.hsa_eligible is False
        if problem:
            assert (
                "[Amounts do not reconcile: Eligible amount $-1.00 is negative.]" in receipt.notes
            )
            assert receipt.confidence_score <= 0.5
        else:
            assert "[Amounts do not reconcile" not in receipt.notes
            assert receipt.confidence_score == 0.95

    def test_missing_grand_total_is_described(self, run_extract):
        receipt, _, _, _ = run_extract(self.LAYOUT_A.replace("Grand Total: $6.39\n", ""))
        assert "grand total not printed]" in receipt.notes


class TestPatientWholeWords:
    @pytest.fixture
    def extractor(self):
        return VisionExtractor(
            family_members=["Alice", "Bob", "Christopher"], family_aliases={"chris": "Christopher"}
        )

    @pytest.mark.parametrize("value", [None, 17])
    def test_non_string(self, extractor, value):
        assert extractor._match_patient_name(value) is None

    def test_left_boundary(self, extractor):
        for value in ("xAlice", "éAlice", "xChris", "éChris", "xspouse", "éspouse"):
            assert extractor._match_patient_name(value) is None

    def test_right_boundary(self, extractor):
        for value in ("Alicen Smith", "Aliceé", "Christmas", "Chrisé", "spousex", "spouseé"):
            assert extractor._match_patient_name(value) is None

    def test_canonical(self, extractor):
        for value in ("Alice Smith", "Smith, Alice", "1Alice2", "_Alice_", "(ALICE)", "Alice"):
            assert extractor._match_patient_name(value) == "Alice"

    def test_alias(self, extractor):
        for value in ("Chris Smith", "Smith, Chris", "1Chris2", "_Chris_", "(CHRIS)", "Chris"):
            assert extractor._match_patient_name(value) == "Christopher"

    @pytest.mark.parametrize(
        "word,expected", [("self", "Alice"), ("spouse", "Bob"), ("son", "Christopher")]
    )
    def test_keyword_boundaries(self, extractor, word, expected):
        for value in (
            f"{word} Smith",
            f"Smith, {word}",
            f"1{word}2",
            f"_{word}_",
            f"({word.upper()})",
            word,
        ):
            assert extractor._match_patient_name(value) == expected
        assert extractor._match_patient_name("x" + word) is None
        assert extractor._match_patient_name(word + "é") is None

    def test_primary(self, extractor):
        for word in ("self", "subscriber", "primary"):
            assert extractor._match_patient_name(word) == "Alice"

    def test_spouse(self, extractor):
        for word in ("Spouse", "wife", "husband"):
            assert extractor._match_patient_name(word) == "Bob"

    def test_dependent(self, extractor):
        for word in ("son", "daughter", "child", "dependent"):
            assert extractor._match_patient_name(word) == "Christopher"
        for word in ("sons", "daughters", "children", "dependents", "Dependents"):
            assert extractor._match_patient_name(word) == "Christopher"
        assert extractor._match_patient_name("Mason") is None
        assert extractor._match_patient_name("sonata") is None

    def test_family_size_and_order(self, extractor):
        assert extractor._match_patient_name("Bob Alice") == "Alice"
        assert extractor._match_patient_name("chris Bob") == "Bob"
        assert extractor._match_patient_name("spouse chris") == "Christopher"
        assert extractor._match_patient_name("son spouse self") == "Alice"
        extractor.family_members = ["Alice", "Bob"]
        assert extractor._match_patient_name("son") is None
        extractor.family_members = ["Alice"]
        assert extractor._match_patient_name("spouse") is None
        extractor.family_members = []
        assert extractor._match_patient_name("self") is None

    def test_literal_spelling(self):
        extractor = VisionExtractor(
            family_members=["Ann Marie"], family_aliases={"a.b": "Ann Marie"}
        )
        assert extractor._match_patient_name("Ann Marie") == "Ann Marie"
        assert extractor._match_patient_name("Ann_Marie") is None
        assert extractor._match_patient_name("a.b") == "Ann Marie"
        assert extractor._match_patient_name("axb") is None

    @pytest.mark.parametrize(
        "parsed",
        [
            {"payment_summary": [{"patient": None, "your_share": 10}]},
            {"services": [{"patient": None, "service_details": [{"your_cost": 10}]}]},
        ],
    )
    def test_eob_null_patient(self, extractor, tmp_path, monkeypatch, parsed):
        import json
        from types import SimpleNamespace
        from unittest.mock import Mock

        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(parsed)))]
        )
        client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=Mock(return_value=response)))
        )
        monkeypatch.setattr(extractor, "_init_client", lambda: client)
        monkeypatch.setattr(extractor, "_extract_text_with_pdfplumber", lambda path: "EOB text")
        path = tmp_path / "document.pdf"
        path.touch()
        result = extractor.extract_eob(path)
        assert [claim.patient_name for claim in result.claims] == ["Unknown"]


class TestStoredModelNotes:
    @pytest.mark.parametrize(
        "prefix",
        ["[Amounts do not reconcile", "[Patient not identified"],
        ids=["amount", "patient"],
    )
    def test_general_receipt_neutralizes_reserved_prefix(self, prefix):
        receipt = VisionExtractor()._build_receipt(
            {"document_type": "receipt", "notes": [f"{prefix}: model]", "ordinary note"]}
        )
        assert prefix not in receipt.notes
        assert "ordinary note" in receipt.notes

    @pytest.mark.parametrize(
        "prefix",
        ["[Amounts do not reconcile", "[Patient not identified"],
        ids=["amount", "patient"],
    )
    def test_multi_claim_neutralizes_reserved_prefix(self, prefix):
        result = VisionExtractor()._build_multi_claim_extraction(
            {"notes": [f"{prefix}: model]", "ordinary note"]}
        )
        assert prefix not in result.notes
        assert "ordinary note" in result.notes

    def test_general_receipt_retains_generated_mismatch(self):
        result = VisionExtractor()._build_receipt(
            {
                "document_type": "eob",
                "patient_responsibility": 5,
                "stated_patient_total": 10,
                "notes": "[Amounts do not reconcile: fabricated]",
            }
        )
        assert result.notes.count("[Amounts do not reconcile") == 1
        assert "printed total is $10.00" in result.notes


class TestDirectPdfProviderState:
    def test_restores_provider_after_success_and_keeps_it_for_nested_image(
        self, tmp_path, monkeypatch
    ):
        extractor = VisionExtractor()
        extractor._current_provider_skill = "cvs"
        monkeypatch.setattr(
            extractor, "_extract_text_with_pdfplumber", lambda path: TestAmazonOrderPdf.LAYOUT_A
        )
        monkeypatch.setattr(
            extractor, "_convert_pdf_to_images", lambda path: [tmp_path / "page.png"]
        )
        seen = []
        result = extractor._fallback_extraction("pdf")
        monkeypatch.setattr(extractor, "_extract_with_text_and_image", lambda text, image: result)
        # Force the image fallback while retaining the content-selected provider.
        result.patient_responsibility = 0
        monkeypatch.setattr(
            extractor,
            "extract_from_image",
            lambda path: seen.append(extractor._current_provider_skill) or result,
        )
        monkeypatch.setattr(
            extractor,
            "_convert_pdf_to_images",
            lambda path: [tmp_path / "a.png", tmp_path / "b.png"],
        )
        extractor.extract_from_pdf(tmp_path / "document.pdf")
        assert seen == ["amazon", "amazon"]
        assert extractor._current_provider_skill == "cvs"

    @pytest.mark.parametrize("failure", ["text", "conversion", "extraction"])
    def test_restores_provider_after_exception(self, tmp_path, monkeypatch, failure):
        extractor = VisionExtractor()
        extractor._current_provider_skill = "cvs"

        def raises(*args):
            raise RuntimeError(failure)

        monkeypatch.setattr(
            extractor,
            "_extract_text_with_pdfplumber",
            raises if failure == "text" else lambda path: TestAmazonOrderPdf.LAYOUT_A,
        )
        monkeypatch.setattr(
            extractor,
            "_convert_pdf_to_images",
            raises if failure == "conversion" else lambda path: [],
        )
        monkeypatch.setattr(extractor, "_extract_with_text_and_image", raises)
        with pytest.raises(RuntimeError, match=failure):
            extractor.extract_from_pdf(tmp_path / "document.pdf")
        assert extractor._current_provider_skill == "cvs"

    def test_eob_still_resets_provider_after_exception(self, tmp_path, monkeypatch):
        extractor = VisionExtractor()
        path = tmp_path / "aetna.pdf"
        path.touch()
        monkeypatch.setattr(
            extractor, "_init_client", lambda: (_ for _ in ()).throw(RuntimeError("failed"))
        )
        with pytest.raises(RuntimeError, match="failed"):
            extractor.extract_eob(path)
        assert extractor._current_provider_skill is None
