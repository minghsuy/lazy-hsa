"""
LLM Extractor for HSA Receipt System
Uses vision-enabled LLM (Mistral Small 3) for direct image-to-JSON extraction
"""

import base64
import contextlib
import json
import logging
import re
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Extraction constants
MIN_PAGE_TEXT_LENGTH = 50  # Skip pages with less usable text
MAX_FALLBACK_PAGES = 4  # Max pages to check in image-only fallback
MAX_PDF_PAGES = 5  # Max pages to process from PDFs


class Category(Enum):
    MEDICAL = "medical"
    DENTAL = "dental"
    VISION = "vision"
    PHARMACY = "pharmacy"
    UNKNOWN = "unknown"


class DocumentType(Enum):
    RECEIPT = "receipt"
    EOB = "eob"
    STATEMENT = "statement"
    CLAIM = "claim"
    PRESCRIPTION = "prescription"
    UNKNOWN = "unknown"


@dataclass
class ExtractedReceipt:
    """Structured receipt data extracted from document."""

    provider_name: str
    service_date: str | None  # YYYY-MM-DD
    service_type: str
    patient_name: str
    billed_amount: float
    insurance_paid: float
    patient_responsibility: float
    hsa_eligible: bool
    category: str
    document_type: str
    confidence_score: float
    notes: str
    raw_extraction: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def generate_filename(self, extension: str = "pdf") -> str:
        """Generate standardized filename."""
        date = self.service_date or datetime.now().strftime("%Y-%m-%d")
        provider = re.sub(r"[^\w\s-]", "", self.provider_name)[:30].strip().replace(" ", "_")
        service = re.sub(r"[^\w\s-]", "", self.service_type)[:20].strip().replace(" ", "_")
        amount = f"{self.patient_responsibility:.2f}"
        return f"{date}_{provider}_{service}_${amount}.{extension}"


EXTRACTION_PROMPT_TEMPLATE = """You are a medical receipt/EOB data extractor. Analyze this document image and extract structured information.

The family members are: {family_members}

Extract the following as a JSON object:
{{
  "provider_name": "Name of healthcare provider, pharmacy, or retailer",
  "service_date": "YYYY-MM-DD format or null if unclear",
  "service_type": "Brief description of service or product",
  "patient_name": "MUST be one of: {family_members} - match based on recipient/patient name in document",
  "eligible_subtotal": 0.00,
  "receipt_tax": 0.00,
  "receipt_taxable_amount": 0.00,
  "insurance_paid": 0.00,
  "hsa_eligible": true,
  "category": "medical|dental|vision|pharmacy",
  "document_type": "receipt|eob|statement|claim|prescription",
  "confidence_score": 0.95,
  "notes": "Any uncertainties or important details"
}}

CRITICAL - Recognize the store/provider from the image and apply these rules:

RETAIL STORES (Costco, CVS, Walgreens, Target, Walmart, Amazon):
- STRICT RULE: ONLY include items with VISIBLE "F" or "*" marker!
- The "F" marker appears in a dedicated COLUMN between price and "Dept" - look carefully!
- Items WITHOUT the "F" marker (like ZIPLOC, supplements) must be EXCLUDED
- Example from Costco receipt:
  * "SALONPAS 140    15.99 A  F  Dept" ← HAS "F" marker = INCLUDE
  * "ZIPLOC QUART    12.99 A     Dept" ← NO "F" marker = EXCLUDE
  * "NM COQ 140CT    37.99 A     Dept" ← NO "F" marker = EXCLUDE
- Rows starting with "SC" are discounts/coupons - IGNORE completely
- DO NOT assume eligibility based on product type - ONLY the "F" marker matters
- service_type: List EACH eligible item with quantity and unit price (e.g., "4x Salonpas @$15.99")
- DO NOT CALCULATE - just extract these raw values:
  * eligible_subtotal = sum of ONLY the FSA/HSA marked item prices (pre-tax)
  * receipt_tax = the TAX amount shown on receipt (e.g., "TAX 18.28" → 18.28)
  * receipt_taxable_amount = the taxable subtotal shown (e.g., "Taxable Amount 200.29" → 200.29)
- insurance_paid = 0 for retail purchases
- category = "pharmacy"
- If NO marked items found, set hsa_eligible=false and eligible_subtotal=0

HEALTHCARE EOBs (Sutter, Kaiser, Delta Dental, VSP, Anthem, Blue Cross):
- Look for "Patient Responsibility", "Member Pays", "Your Cost", "Amount Due"
- patient_responsibility = amount YOU owe after insurance
- insurance_paid = what the plan/insurance paid
- category based on provider type (medical/dental/vision)

General Rules:
- patient_name MUST be exactly one of: {family_members}
- Match the patient/recipient in the document to the closest family member name
- If unclear, default to the first family member ({default_patient})
- Respond with ONLY the JSON object, no other text
{provider_skill}"""


# Provider-specific extraction skills (activated based on filename/content hints)
PROVIDER_SKILLS = {
    "costco": """
COSTCO RECEIPT RULES:
- Look for "F" marker in column after price - ONLY these items are FSA-eligible
- Format: "ITEM_NAME    PRICE A  F  Dept" means FSA-eligible
- Format: "ITEM_NAME    PRICE A     Dept" means NOT eligible (no F)
- Rows starting with "SC" are discounts - IGNORE them
- provider_name: "Costco"
- eligible_subtotal: sum ONLY items with F marker
- receipt_tax: the TAX amount shown
- receipt_taxable_amount: the "Taxable Amount" shown
- document_type: "receipt"
- category: "pharmacy"

Example: If you see 4 lines of "SALONPAS 140  15.99 A F Dept" → eligible_subtotal = 63.96
""",
    "cvs": """
CVS-SPECIFIC RULES:
- Look for FSA/HSA ELIGIBLE label on items
- Rx number indicates prescription (hsa_eligible=true)
- Include copay as patient_responsibility
- For OTC items, only include if marked FSA eligible
- category = "pharmacy"
""",
    "walgreens": """
WALGREENS-SPECIFIC RULES:
- Look for "FSA" or "HSA" markers next to eligible items
- Prescription copays are always HSA eligible
- For OTC items, only include if marked FSA/HSA eligible
- category = "pharmacy"
""",
    "amazon": """
AMAZON ORDER RULES:
- patient_name: Extract from "Ship to:" name
- service_date: Use "Order placed" date (not delivery date)
- service_type: Product name from the order
- DO NOT CALCULATE - read these values directly from the receipt:
  * eligible_subtotal: Use "Grand Total" amount (this already includes tax)
  * receipt_tax: 0 (tax is already in Grand Total)
  * receipt_taxable_amount: 0 (not needed - Grand Total is final)
- If "FSA or HSA eligible: $X.XX" line exists, that IS the amount to use
- provider_name: "Amazon"
- category: "pharmacy"
- document_type: "receipt"
""",
    "sutter": """
SUTTER HEALTH-SPECIFIC RULES:
- This is likely a hospital/medical bill or EOB
- Look for "Patient Responsibility" or "Amount Due" for patient_responsibility
- Look for "Insurance Payment" or "Plan Paid" for insurance_paid
- service_date is the "Date of Service"
- category = "medical"
- document_type is likely "statement" or "eob"
""",
    "aetna": """
AETNA EOB-SPECIFIC RULES:
- This is a medical EOB from Aetna HDHP
- Look for "Member Responsibility" or "Your Responsibility" for patient_responsibility
- Look for "Plan Paid" or "Aetna Paid" for insurance_paid
- billed_amount is the "Charged" or "Billed" amount
- May have multiple service lines - sum all patient responsibility amounts
- Use earliest "Date of Service" if multiple dates
- category = "medical"
- document_type = "eob"
""",
    "express_scripts": """
EXPRESS SCRIPTS-SPECIFIC RULES:
- This is a pharmacy receipt/invoice from Express Scripts (PBM)
- Medications delivered by mail are HSA-eligible prescriptions
- Look for "Your Cost" or "You Pay" for patient_responsibility
- service_type should be the medication name(s)
- provider_name = "Express Scripts"
- category = "pharmacy"
- document_type = "prescription"
- hsa_eligible = true (prescriptions are always eligible)
""",
    "delta_dental": """
DELTA DENTAL-SPECIFIC RULES:
- This is a dental EOB
- Look for "Patient Pays" for patient_responsibility
- Look for "Benefit Paid" for insurance_paid
- category = "dental"
- document_type = "eob"
""",
    "vsp": """
VSP VISION-SPECIFIC RULES:
- This is a vision EOB or receipt
- Look for "Your Cost" or "Member Pays" for patient_responsibility
- category = "vision"
""",
    "stanford": """
STANFORD HEALTH CARE-SPECIFIC RULES:
- This is a hospital/medical statement from Stanford Health Care
- IMPORTANT: Look through ALL text for the key fields - they may be on different pages
- Look for "Patient Responsibility" for the amount the patient owes
- Look for "Balance Due" or "Amount Due" as confirmation
- Look for "Patient Deductible" - this often equals Patient Responsibility for HDHP plans
- "Service Date" is the date of medical service (not statement date)
- "Visit Type" describes the service (e.g., Outpatient, Inpatient)
- "Location" is usually "Stanford Hospital" or a clinic name
- Look for service descriptions like "Treatment/Observation Room"
- insurance_paid may be $0 if applied to deductible
- billed_amount is "Total Charges"
- category = "medical"
- document_type = "statement"
""",
}


def detect_provider_skill(filename: str, hints: list[str] | None = None) -> str | None:
    """Detect which provider skill to apply based on filename or hints.

    Args:
        filename: Name of the file being processed
        hints: Optional list of text hints (e.g., from OCR preview)

    Returns:
        Provider skill key if detected, None otherwise
    """
    text_to_check = filename.lower()
    if hints:
        text_to_check += " " + " ".join(h.lower() for h in hints)

    # Check for provider matches
    # NOTE: EOB routing to EOBs/{category}/ folder is planned for v0.3.0
    provider_patterns = {
        "costco": ["costco", "store 423", "store423"],  # Costco store numbers
        "cvs": ["cvs"],
        "walgreens": ["walgreens", "walgreen"],
        "amazon": ["amazon"],
        "express_scripts": [
            "express scripts",
            "express_scripts",
            "express-scripts",
            "expressscripts",
            "esrx",
        ],
        "sutter": ["sutter", "pamf", "palo alto medical"],
        "aetna": ["aetna"],
        "delta_dental": ["delta dental", "deltadental"],
        "vsp": ["vsp", "vision service plan"],
        "stanford": ["stanford", "stanford health", "stanfordhealthcare"],
    }

    for skill_key, patterns in provider_patterns.items():
        for pattern in patterns:
            if pattern in text_to_check:
                return skill_key

    return None


def get_extraction_prompt(
    family_members: list[str] | None = None,
    provider_skill: str | None = None,
) -> str:
    """Generate extraction prompt with family member names and optional provider skill.

    Args:
        family_members: List of family member names
        provider_skill: Optional provider skill key (e.g., "costco", "cvs")

    Returns:
        Complete extraction prompt
    """
    family_members = family_members or ["Ming", "Vanessa", "Maxwell"]

    skill_text = ""
    if provider_skill and provider_skill in PROVIDER_SKILLS:
        skill_text = PROVIDER_SKILLS[provider_skill]
        logger.info(f"Applying provider skill: {provider_skill}")

    return EXTRACTION_PROMPT_TEMPLATE.format(
        family_members=", ".join(family_members),
        default_patient=family_members[0],
        provider_skill=skill_text,
    )


class VisionExtractor:
    """Extract structured data from document images using vision-enabled LLM."""

    def __init__(
        self,
        api_base: str = "http://localhost:11434/v1",
        model: str = "mistral-small3",
        max_tokens: int = 2048,
        temperature: float = 0.1,
        family_members: list[str] | None = None,
    ):
        self.api_base = api_base.rstrip("/")
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.family_members = family_members or ["Ming", "Vanessa", "Maxwell"]
        self._client = None
        self._current_provider_skill = None  # Set per-file extraction

    def _init_client(self):
        if self._client is None:
            try:
                from openai import OpenAI

                self._client = OpenAI(
                    base_url=self.api_base,
                    api_key="ollama",  # Ollama doesn't need real key
                )
                logger.info(f"Vision LLM client initialized: {self.api_base}, model: {self.model}")
            except ImportError as err:
                raise ImportError("openai package not installed. Run: uv add openai") from err
        return self._client

    def _encode_image(self, image_path: Path) -> tuple[str, str]:
        """Encode image to base64 and determine MIME type."""
        suffix = image_path.suffix.lower()
        mime_types = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".webp": "image/webp",
        }
        mime_type = mime_types.get(suffix, "image/jpeg")

        with open(image_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode("utf-8")

        return image_data, mime_type

    def _convert_pdf_to_images(self, pdf_path: Path, max_pages: int = MAX_PDF_PAGES) -> list[Path]:
        """Convert PDF pages to images for vision processing.

        Args:
            pdf_path: Path to PDF file
            max_pages: Maximum pages to convert (default MAX_PDF_PAGES, key info usually early)
        """
        try:
            from pdf2image import convert_from_path
        except ImportError as err:
            raise ImportError("pdf2image not installed. Run: uv add pdf2image") from err

        images = convert_from_path(str(pdf_path), dpi=200, last_page=max_pages)
        image_paths = []

        for i, image in enumerate(images):
            temp_path = Path(tempfile.gettempdir()) / f"hsa_receipt_page_{i}.png"
            image.save(temp_path, "PNG")
            image_paths.append(temp_path)

        return image_paths

    def _decode_cid_text(self, text: str) -> str:
        """Decode CID-encoded text like (cid:84)(cid:104) to actual characters."""

        def decode_cid(match):
            try:
                cid = int(match.group(1))
                # CID values are typically ASCII codes
                if cid == 10:  # Newline - check first
                    return "\n"
                elif 32 <= cid <= 126:  # Printable ASCII (includes space at 32)
                    return chr(cid)
                else:
                    return ""
            except (ValueError, OverflowError):
                return ""

        return re.sub(r"\(cid:(\d+)\)", decode_cid, text)

    def _clean_extracted_text(self, text: str) -> str:
        """Clean extracted PDF text by removing garbage and decoding CID."""
        # First, decode CID-encoded text like (cid:84)(cid:104) -> "Th"
        text = self._decode_cid_text(text)

        # Remove QR code binary patterns (long strings of 0s and 1s)
        text = re.sub(r"\b[01]{10,}\b", "", text)

        # Remove hex patterns like 0X37B08973
        text = re.sub(r"\b0X[0-9A-Fa-f]+\b", "", text)

        # Remove excessive whitespace
        text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
        text = re.sub(r"[ \t]+", " ", text)

        return text.strip()

    def _extract_text_with_pdfplumber(self, pdf_path: Path, max_pages: int = MAX_PDF_PAGES) -> str:
        """Extract text from PDF pages using pdfplumber.

        Args:
            pdf_path: Path to the PDF file
            max_pages: Maximum pages to extract (default MAX_PDF_PAGES, key info is usually early)
        """
        try:
            import pdfplumber
        except ImportError as err:
            raise ImportError("pdfplumber not installed. Run: uv add pdfplumber") from err

        all_text = []
        try:
            with pdfplumber.open(pdf_path) as pdf:
                pages_to_process = min(len(pdf.pages), max_pages)
                for i, page in enumerate(pdf.pages[:pages_to_process]):
                    page_text = page.extract_text() or ""

                    # Clean the extracted text
                    page_text = self._clean_extracted_text(page_text)

                    # Skip pages with very little usable text
                    if len(page_text) > MIN_PAGE_TEXT_LENGTH:
                        all_text.append(f"=== PAGE {i + 1} ===\n{page_text}")

            combined = "\n\n".join(all_text)
            logger.info(
                f"Extracted {len(combined)} chars from {len(all_text)} PDF pages (of {pages_to_process} processed)"
            )
            return combined
        except (OSError, ValueError) as e:
            logger.warning(f"pdfplumber extraction failed ({type(e).__name__}): {e}")
            return ""
        except Exception as e:
            logger.error(f"Unexpected pdfplumber error: {type(e).__name__}: {e}")
            return ""

    def _extract_with_text_and_image(
        self, text_content: str, image_path: Path | None = None
    ) -> ExtractedReceipt:
        """Extract receipt data using text content and optional image."""
        client = self._init_client()
        prompt = self._get_prompt()

        # Build message content
        content = []

        # Add instruction about text content
        text_prompt = (
            prompt
            + f"""

DOCUMENT TEXT (extracted from all pages):
```
{text_content}
```

Analyze the text above to extract the JSON data. The text contains content from ALL pages of the document.
"""
        )
        content.append({"type": "text", "text": text_prompt})

        # Add image if available (for visual verification)
        if image_path and image_path.exists():
            image_data, mime_type = self._encode_image(image_path)
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{image_data}"},
                }
            )

        try:
            response = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": content}],
                max_tokens=self.max_tokens,
                temperature=self.temperature,
            )

            raw_response = response.choices[0].message.content
            parsed = self._parse_response(raw_response)
            return self._build_receipt(parsed)

        except Exception as e:
            logger.error(f"Text+image extraction failed: {e}")
            return self._fallback_extraction("text extraction")

    def _get_prompt(self) -> str:
        """Get the extraction prompt, including any active provider skill."""
        return get_extraction_prompt(
            family_members=self.family_members,
            provider_skill=self._current_provider_skill,
        )

    def extract_from_image(self, image_path: Path) -> ExtractedReceipt:
        """Extract receipt data from a single image."""
        client = self._init_client()
        image_data, mime_type = self._encode_image(image_path)
        prompt = self._get_prompt()

        try:
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:{mime_type};base64,{image_data}"},
                            },
                        ],
                    }
                ],
                max_tokens=self.max_tokens,
                temperature=self.temperature,
            )

            raw_response = response.choices[0].message.content
            parsed = self._parse_response(raw_response)
            return self._build_receipt(parsed)

        except Exception as e:
            logger.error(f"Vision extraction failed: {e}")
            return self._fallback_extraction(str(image_path))

    def extract_from_pdf(self, pdf_path: Path) -> ExtractedReceipt:
        """Extract receipt data from PDF using pdfplumber text + first page image."""
        # First, try to extract text from all pages using pdfplumber
        text_content = self._extract_text_with_pdfplumber(pdf_path)

        # Convert first page to image for visual context
        image_paths = self._convert_pdf_to_images(pdf_path)

        try:
            if text_content:
                # Use text from all pages + first page image
                first_image = image_paths[0] if image_paths else None
                result = self._extract_with_text_and_image(text_content, first_image)

                # If result looks incomplete (zero amount), try image-only on key pages
                if result.patient_responsibility == 0 and len(image_paths) > 1:
                    logger.info(
                        "Zero amount from text extraction, trying image-only on key pages..."
                    )
                    for img_path in image_paths[:MAX_FALLBACK_PAGES]:
                        alt_result = self.extract_from_image(img_path)
                        if alt_result.patient_responsibility > 0:
                            # Replace with image-only result if it found a valid amount
                            if alt_result.confidence_score >= result.confidence_score:
                                result = alt_result
                            break

                return result

            elif image_paths:
                # Fallback: no text extracted, use image-only approach
                logger.warning("No text extracted, falling back to image-only")
                result = self.extract_from_image(image_paths[0])

                # Check other pages if first page gave low confidence
                if len(image_paths) > 1 and result.confidence_score < 0.7:
                    for img_path in image_paths[1:]:
                        alt_result = self.extract_from_image(img_path)
                        if alt_result.confidence_score > result.confidence_score:
                            result = alt_result
                            break

                return result
            else:
                return self._fallback_extraction(str(pdf_path))

        finally:
            # Cleanup temp images
            for img_path in image_paths:
                with contextlib.suppress(OSError):
                    img_path.unlink()

    def extract(self, file_path: str | Path, provider_hint: str | None = None) -> ExtractedReceipt:
        """Extract receipt data from file (image or PDF).

        Args:
            file_path: Path to the receipt file
            provider_hint: Optional hint for provider skill detection (e.g., "costco")
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        # Detect provider skill from filename (or explicit hint)
        hints = [provider_hint] if provider_hint else None
        self._current_provider_skill = detect_provider_skill(file_path.name, hints)
        if self._current_provider_skill:
            logger.info(f"Detected provider skill: {self._current_provider_skill}")

        suffix = file_path.suffix.lower()

        try:
            if suffix == ".pdf":
                return self.extract_from_pdf(file_path)
            elif suffix in {
                ".png",
                ".jpg",
                ".jpeg",
                ".gif",
                ".webp",
                ".tiff",
                ".bmp",
                ".heic",
                ".heif",
            }:
                # Convert non-standard formats to PNG first
                if suffix in {".tiff", ".bmp"}:
                    from PIL import Image

                    img = Image.open(file_path)
                    temp_path = Path(tempfile.gettempdir()) / "hsa_receipt_converted.png"
                    img.save(temp_path, "PNG")
                    try:
                        return self.extract_from_image(temp_path)
                    finally:
                        temp_path.unlink(missing_ok=True)
                elif suffix in {".heic", ".heif"}:
                    # HEIC/HEIF requires pillow-heif plugin
                    try:
                        import pillow_heif

                        pillow_heif.register_heif_opener()
                    except ImportError as err:
                        raise ImportError(
                            "pillow-heif not installed. Run: uv add pillow-heif"
                        ) from err

                    from PIL import Image

                    img = Image.open(file_path)
                    temp_path = Path(tempfile.gettempdir()) / "hsa_receipt_converted.png"
                    img.save(temp_path, "PNG")
                    logger.info("Converted HEIC to PNG for processing")
                    try:
                        return self.extract_from_image(temp_path)
                    finally:
                        temp_path.unlink(missing_ok=True)
                else:
                    return self.extract_from_image(file_path)
            else:
                raise ValueError(f"Unsupported file type: {suffix}")
        finally:
            # Reset provider skill after extraction
            self._current_provider_skill = None

    def _parse_response(self, response: str) -> dict[str, Any]:
        """Parse LLM response to extract JSON."""
        response = response.strip()

        # Strip markdown code blocks
        if response.startswith("```json"):
            response = response[7:]
        if response.startswith("```"):
            response = response[3:]
        if response.endswith("```"):
            response = response[:-3]
        response = response.strip()

        try:
            parsed = json.loads(response)
            # Handle case where LLM returns array instead of object
            if isinstance(parsed, list) and len(parsed) > 0:
                parsed = parsed[0]
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            # Try to find JSON object in response
            match = re.search(r"\{[^{}]*\}", response, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
            logger.warning("Could not parse LLM response as JSON")
            return {}

    def _build_receipt(self, parsed: dict[str, Any]) -> ExtractedReceipt:
        """Build ExtractedReceipt from parsed JSON, calculating tax in Python."""
        # Extract raw values
        eligible_subtotal = float(parsed.get("eligible_subtotal") or 0)
        receipt_tax = float(parsed.get("receipt_tax") or 0)
        receipt_taxable_amount = float(parsed.get("receipt_taxable_amount") or 0)
        insurance_paid = float(parsed.get("insurance_paid") or 0)

        # Calculate tax on eligible items (Python does the math, not LLM)
        tax_on_eligible = 0.0
        tax_rate = 0.0
        if eligible_subtotal > 0 and receipt_taxable_amount > 0 and receipt_tax > 0:
            tax_rate = receipt_tax / receipt_taxable_amount
            tax_on_eligible = round(eligible_subtotal * tax_rate, 2)

        # For retail: patient_responsibility = eligible items + tax
        # For EOBs: use the extracted patient_responsibility directly
        document_type = parsed.get("document_type") or "unknown"
        if document_type in ("receipt", "prescription") and eligible_subtotal > 0:
            patient_responsibility = eligible_subtotal + tax_on_eligible
            billed_amount = eligible_subtotal
        else:
            # EOB or other - use extracted values
            patient_responsibility = float(
                parsed.get("patient_responsibility") or eligible_subtotal
            )
            billed_amount = float(parsed.get("billed_amount") or eligible_subtotal)

        # Build notes with tax calculation if applicable
        notes = parsed.get("notes") or ""
        if tax_on_eligible > 0:
            tax_note = (
                f"Tax rate {tax_rate * 100:.3f}%, tax on eligible items: ${tax_on_eligible:.2f}"
            )
            notes = f"{tax_note}. {notes}" if notes else tax_note

        # Handle service_type as string (LLM sometimes returns a list)
        service_type = parsed.get("service_type") or "Unknown Service"
        if isinstance(service_type, list):
            service_type = ", ".join(str(s) for s in service_type)

        return ExtractedReceipt(
            provider_name=parsed.get("provider_name") or "Unknown",
            service_date=parsed.get("service_date"),
            service_type=service_type,
            patient_name=parsed.get("patient_name") or "Unknown",
            billed_amount=billed_amount,
            insurance_paid=insurance_paid,
            patient_responsibility=patient_responsibility,
            hsa_eligible=bool(parsed.get("hsa_eligible", True)),
            category=parsed.get("category") or "unknown",
            document_type=document_type,
            confidence_score=float(parsed.get("confidence_score") or 0.5),
            notes=notes,
            raw_extraction=parsed,
        )

    def _fallback_extraction(self, source: str) -> ExtractedReceipt:
        """Fallback when vision extraction fails."""
        return ExtractedReceipt(
            provider_name="Unknown (Extraction Failed)",
            service_date=None,
            service_type="Unknown (Needs Manual Review)",
            patient_name="Unknown",
            billed_amount=0,
            insurance_paid=0,
            patient_responsibility=0,
            hsa_eligible=True,
            category="unknown",
            document_type="unknown",
            confidence_score=0.1,
            notes=f"Vision extraction failed - manual review required. Source: {source}",
            raw_extraction={},
        )


class MockVisionExtractor(VisionExtractor):
    """Mock extractor for testing without running LLM."""

    def extract(self, file_path: str | Path) -> ExtractedReceipt:
        return ExtractedReceipt(
            provider_name="Mock Provider",
            service_date="2026-01-15",
            service_type="Test Service",
            patient_name="Test Patient",
            billed_amount=100.00,
            insurance_paid=80.00,
            patient_responsibility=20.00,
            hsa_eligible=True,
            category="medical",
            document_type="receipt",
            confidence_score=0.95,
            notes="Mock extraction for testing",
            raw_extraction={"mock": True},
        )


def get_extractor(
    use_mock: bool = False,
    api_base: str = "http://localhost:11434/v1",
    model: str = "mistral-small3",
    **kwargs,
) -> VisionExtractor:
    """Factory function to get appropriate extractor."""
    if use_mock:
        return MockVisionExtractor()
    return VisionExtractor(api_base=api_base, model=model, **kwargs)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        file_path = sys.argv[1]
        use_mock = "--mock" in sys.argv

        extractor = get_extractor(use_mock=use_mock)
        result = extractor.extract(file_path)

        print("Extracted Data:")
        print(json.dumps(result.to_dict(), indent=2, default=str))
        print(f"\nGenerated filename: {result.generate_filename()}")
    else:
        print("Usage: python llm_extractor.py <image_or_pdf_path> [--mock]")
