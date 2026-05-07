"""Regression tests for the deterministic Aetna EOB parser.

The parser (`VisionExtractor._parse_aetna_eob`) reads pdfplumber text and
returns a `MultiClaimExtraction`. These tests bypass pdfplumber by injecting
synthetic text that exercises the regex paths — no real PDFs, no PHI.

Synthetic patterns are modeled on observed Aetna pdfplumber output:
- Page header/footer pattern stripped before parsing
- Wrapped role markers (bare `(spouse)` on its own line)
- Service date variants: `on\nM/D/YY` and bare `M/D/YY`
- Multi-claim extraction with prefix matching for truncated provider names
"""

from pathlib import Path

import pytest

from src.processors.llm_extractor import VisionExtractor


class _StubExtractor(VisionExtractor):
    """VisionExtractor with pdfplumber stubbed to return a fixed text blob.

    Relies on `VisionExtractor.__init__` being lazy about LLM client
    construction (``self._client = None``). The Aetna parser path never calls
    ``_init_client``, so these tests run without an Ollama instance. If
    ``__init__`` is ever changed to eagerly initialize the client, these tests
    will silently start requiring a local LLM — update this stub to also block
    ``_init_client``.
    """

    def __init__(self, text: str, **kwargs):
        super().__init__(**kwargs)
        self._stub_text = text

    def _extract_text_with_pdfplumber(self, pdf_path, max_pages=20):  # noqa: ARG002
        return self._stub_text


def _aetna_text(summary_lines: str, detail_blocks: str) -> str:
    """Build a synthetic Aetna pdfplumber-style text blob.

    The parser strips repeated page headers, so we replicate the pattern.
    """
    header = (
        "Statement date: January 15, 2026 Page 1 of 3\n"
        "Member: Test User Member ID: T12345\n"
        "Group name: TEST GROUP Group #: G123 Plan: PPO\n"
    )
    return (
        f"=== PAGE 1 ===\n"
        f"{header}"
        f"Statement date: January 15, 2026\n"
        f"\n"
        f"Your payment summary\n"
        f"Plan's share Your share\n"
        f"Patient Provider Sent to Send date Amount Amount\n"
        f"{summary_lines}"
        f"Total: $75.00\n"
        f"\n"
        f"=== PAGE 2 ===\n"
        f"{header.replace('Page 1 of 3', 'Page 2 of 3')}"
        f"{detail_blocks}"
    )


@pytest.fixture
def stub():
    """Build a stub extractor with default family ['Alice', 'Bob', 'Charlie']."""

    def _make(text: str) -> _StubExtractor:
        return _StubExtractor(text=text)

    return _make


def test_returns_none_when_summary_section_missing(stub):
    """No `Your payment summary` block → parser returns None (signals fallback)."""
    extractor = stub("=== PAGE 1 ===\nNothing matches here.\n")
    assert extractor._parse_aetna_eob(Path("synthetic.pdf")) is None


def test_returns_none_when_pdfplumber_returns_empty(stub):
    """Empty pdfplumber text → None."""
    extractor = stub("")
    assert extractor._parse_aetna_eob(Path("synthetic.pdf")) is None


def test_single_claim_self(stub):
    """Single claim with inline role marker, plain provider, dated detail block."""
    summary = "Alice Test Provider A $50.00 ELECTRONIC 1/10/2026 $50.00 $25.00 (self)\n"
    details = (
        "Claim for Alice (self)\n"
        "Provider: Test Provider A (Internal Medicine)\n"
        "Claim ID: AET00001 Network: In\n"
        "Service type and date\n"
        "A B C D\n"
        "Office visit on\n"
        "1/10/26\n"
        "75.00 25.00 50.00 25.00\n"
    )

    result = stub(_aetna_text(summary, details))._parse_aetna_eob(Path("synthetic.pdf"))

    assert result is not None
    assert result.payer_name == "Aetna"
    assert result.statement_date == "2026-01-15"
    assert len(result.claims) == 1

    claim = result.claims[0]
    assert claim.patient_name == "Alice"
    assert claim.insurance_paid == 50.00
    assert claim.patient_responsibility == 25.00
    assert claim.claim_number == "AET00001"
    assert claim.service_date == "2026-01-10"
    assert claim.billed_amount == 75.00


def test_wrapped_role_marker_merges_into_previous_line(stub):
    """When `(spouse)` wraps to its own line, it must merge into the prior summary line."""
    summary = (
        "Alice Test Provider A $50.00 ELECTRONIC 1/10/2026 $50.00 $25.00 (self)\n"
        "Bob Test Provider B $100.00 CHECK 1/12/2026 $100.00 $50.00\n"
        "(spouse)\n"
    )
    details = (
        "Claim for Alice (self)\n"
        "Provider: Test Provider A (Internal Medicine)\n"
        "Claim ID: AET00001 Network: In\n"
        "Service type and date\n"
        "A B C D\n"
        "Office visit on\n"
        "1/10/26\n"
        "75.00 25.00 50.00 25.00\n"
        "\n"
        "Claim for Bob (spouse)\n"
        "Provider: Test Provider B (Cardiology)\n"
        "Claim ID: AET00002 Network: In\n"
        "Service type and date\n"
        "A B C D\n"
        "Specialist visit on\n"
        "1/12/26\n"
        "150.00 50.00 100.00 50.00\n"
    )

    result = stub(_aetna_text(summary, details))._parse_aetna_eob(Path("synthetic.pdf"))

    assert result is not None
    assert len(result.claims) == 2

    by_patient = {c.patient_name: c for c in result.claims}
    assert by_patient["Alice"].claim_number == "AET00001"
    assert by_patient["Bob"].claim_number == "AET00002"
    assert by_patient["Bob"].patient_responsibility == 50.00
    assert by_patient["Bob"].service_date == "2026-01-12"


def test_two_digit_year_dates_parse_correctly(stub):
    """Service dates like `1/10/26` should resolve to 2026-01-10."""
    summary = "Alice Test Clinic $30.00 ELECTRONIC 3/05/2026 $30.00 $15.00 (self)\n"
    details = (
        "Claim for Alice (self)\n"
        "Provider: Test Clinic (Family Medicine)\n"
        "Claim ID: AET99999 Network: In\n"
        "Service type and date\n"
        "A B C D\n"
        "Lab work on\n"
        "3/5/26\n"
        "45.00 15.00 30.00 15.00\n"
    )
    result = stub(_aetna_text(summary, details))._parse_aetna_eob(Path("synthetic.pdf"))

    assert result is not None
    assert result.claims[0].service_date == "2026-03-05"


def test_falls_back_to_statement_date_when_detail_missing(stub):
    """If detail section doesn't match, claim still gets statement_date as fallback."""
    summary = "Alice Mystery Provider $20.00 ELECTRONIC 1/10/2026 $20.00 $10.00 (self)\n"
    details = "Claim for Alice (self)\nProvider: Different Name (Specialty)\nClaim ID: X\n"

    result = stub(_aetna_text(summary, details))._parse_aetna_eob(Path("synthetic.pdf"))

    assert result is not None
    assert len(result.claims) == 1
    assert result.claims[0].service_date == "2026-01-15"  # falls back to statement_date


def test_prefix_match_bridges_truncated_provider_name(stub):
    """Summary line truncates the provider; detail section has the full name.

    Real Aetna pdfplumber output sometimes truncates provider names at page
    boundaries on the summary side while the detail section has the canonical
    long form. `_find_detail_key` matches by patient + provider-prefix to bridge
    these — without prefix matching the detail (claim ID, service date, billed
    amount) would be silently dropped.
    """
    # Summary line: provider truncated to "iRhythm Technologies" (no ", Inc.")
    summary = "Alice iRhythm Technologies $200.00 ELECTRONIC 2/15/2026 $200.00 $40.00 (self)\n"
    # Detail section: full provider name "iRhythm Technologies, Inc."
    details = (
        "Claim for Alice (self)\n"
        "Provider: iRhythm Technologies, Inc. (Cardiology)\n"
        "Claim ID: AET77777 Network: In\n"
        "Service type and date\n"
        "A B C D\n"
        "Cardiac monitoring on\n"
        "2/15/26\n"
        "300.00 60.00 200.00 40.00\n"
    )
    result = stub(_aetna_text(summary, details))._parse_aetna_eob(Path("synthetic.pdf"))

    assert result is not None
    assert len(result.claims) == 1
    claim = result.claims[0]
    # Detail was found via prefix match → claim ID and service date populated.
    assert claim.claim_number == "AET77777"
    assert claim.service_date == "2026-02-15"
    assert claim.billed_amount == 300.00
    # And the canonical full provider name from the detail wins.
    assert claim.original_provider == "iRhythm Technologies, Inc."
