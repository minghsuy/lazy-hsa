"""
LLM Extractor for HSA Receipt System
Uses vision-enabled LLM (Mistral Small 3) for direct image-to-JSON extraction
"""

import base64
import json
import re
from datetime import datetime
from dataclasses import dataclass, asdict
from enum import Enum
from pathlib import Path
from typing import Any
import logging

logger = logging.getLogger(__name__)


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


EXTRACTION_PROMPT = """You are a medical receipt/EOB data extractor. Analyze this document image and extract structured information.

Extract the following as a JSON object:
{
  "provider_name": "Name of healthcare provider or pharmacy",
  "service_date": "YYYY-MM-DD format or null if unclear",
  "service_type": "Brief description of service (e.g., 'Office Visit', 'Prescription', 'Dental Cleaning')",
  "patient_name": "Patient name or null if not visible",
  "billed_amount": 0.00,
  "insurance_paid": 0.00,
  "patient_responsibility": 0.00,
  "hsa_eligible": true,
  "category": "medical|dental|vision|pharmacy",
  "document_type": "receipt|eob|statement|claim|prescription",
  "confidence_score": 0.95,
  "notes": "Any uncertainties or important details"
}

Rules:
- For EOBs, patient_responsibility is what the patient owes after insurance
- If amounts are unclear, set confidence_score lower
- hsa_eligible should be true for qualified medical expenses
- Respond with ONLY the JSON object, no other text"""


class VisionExtractor:
    """Extract structured data from document images using vision-enabled LLM."""

    def __init__(
        self,
        api_base: str = "http://localhost:11434/v1",
        model: str = "mistral-small3",
        max_tokens: int = 2048,
        temperature: float = 0.1,
    ):
        self.api_base = api_base.rstrip("/")
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self._client = None

    def _init_client(self):
        if self._client is None:
            try:
                from openai import OpenAI

                self._client = OpenAI(
                    base_url=self.api_base,
                    api_key="ollama",  # Ollama doesn't need real key
                )
                logger.info(f"Vision LLM client initialized: {self.api_base}, model: {self.model}")
            except ImportError:
                raise ImportError("openai package not installed. Run: uv add openai")
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

    def _convert_pdf_to_images(self, pdf_path: Path) -> list[Path]:
        """Convert PDF pages to images for vision processing."""
        try:
            from pdf2image import convert_from_path
        except ImportError:
            raise ImportError("pdf2image not installed. Run: uv add pdf2image")

        images = convert_from_path(str(pdf_path), dpi=200)
        image_paths = []

        for i, image in enumerate(images):
            temp_path = Path(f"/tmp/hsa_receipt_page_{i}.png")
            image.save(temp_path, "PNG")
            image_paths.append(temp_path)

        return image_paths

    def extract_from_image(self, image_path: Path) -> ExtractedReceipt:
        """Extract receipt data from a single image."""
        client = self._init_client()
        image_data, mime_type = self._encode_image(image_path)

        try:
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": EXTRACTION_PROMPT},
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
        """Extract receipt data from PDF (converts to images first)."""
        image_paths = self._convert_pdf_to_images(pdf_path)

        try:
            # For multi-page PDFs, process first page (usually has key info)
            # Could be extended to process all pages and merge
            if image_paths:
                result = self.extract_from_image(image_paths[0])

                # If multi-page and low confidence, try other pages
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
                try:
                    img_path.unlink()
                except OSError:
                    pass

    def extract(self, file_path: str | Path) -> ExtractedReceipt:
        """Extract receipt data from file (image or PDF)."""
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        suffix = file_path.suffix.lower()

        if suffix == ".pdf":
            return self.extract_from_pdf(file_path)
        elif suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".tiff", ".bmp"}:
            # Convert non-standard formats to PNG first
            if suffix in {".tiff", ".bmp"}:
                from PIL import Image

                img = Image.open(file_path)
                temp_path = Path(f"/tmp/hsa_receipt_converted.png")
                img.save(temp_path, "PNG")
                try:
                    return self.extract_from_image(temp_path)
                finally:
                    temp_path.unlink(missing_ok=True)
            else:
                return self.extract_from_image(file_path)
        else:
            raise ValueError(f"Unsupported file type: {suffix}")

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
            return json.loads(response)
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
        """Build ExtractedReceipt from parsed JSON."""
        return ExtractedReceipt(
            provider_name=parsed.get("provider_name", "Unknown"),
            service_date=parsed.get("service_date"),
            service_type=parsed.get("service_type", "Unknown Service"),
            patient_name=parsed.get("patient_name", "Unknown"),
            billed_amount=float(parsed.get("billed_amount", 0)),
            insurance_paid=float(parsed.get("insurance_paid", 0)),
            patient_responsibility=float(parsed.get("patient_responsibility", 0)),
            hsa_eligible=bool(parsed.get("hsa_eligible", True)),
            category=parsed.get("category", "unknown"),
            document_type=parsed.get("document_type", "unknown"),
            confidence_score=float(parsed.get("confidence_score", 0.5)),
            notes=parsed.get("notes", ""),
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
