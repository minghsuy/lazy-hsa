#!/usr/bin/env python3
"""
HSA Receipt Processing Pipeline
Main orchestration for the receipt organization system

Uses vision-enabled LLM (Mistral Small 3) for direct image-to-JSON extraction.
"""

import logging
import sys
from datetime import datetime
from pathlib import Path

import yaml

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from processors.llm_extractor import ExtractedReceipt, get_extractor
from storage.gdrive_client import GDriveClient
from storage.sheet_client import GSheetsClient, create_record_from_extraction

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class HSAReceiptPipeline:
    """
    Main pipeline for processing HSA receipts.

    Flow:
    1. Get receipt file (from inbox, email, or scanner)
    2. Use vision LLM to extract structured data directly from image/PDF
    3. Validate HSA eligibility and apply business rules
    4. Upload to Google Drive with proper naming
    5. Add record to tracking spreadsheet
    """

    def __init__(self, config_path: str = "config/config.yaml"):
        """Initialize pipeline from config."""
        self.config = self._load_config(config_path)
        self.hsa_start_date = datetime.strptime(
            self.config.get("hsa", {}).get("start_date", "2026-01-01"),
            "%Y-%m-%d",
        )

        # Processing thresholds
        processing = self.config.get("processing", {})
        self.auto_threshold = processing.get("auto_process_threshold", 0.85)
        self.review_threshold = processing.get("review_threshold", 0.70)

        # Family member names (for folder mapping)
        family = self.config.get("family", [])
        self.family_names = [m.get("name", "Unknown") for m in family] if family else ["Ming", "Wife", "Son"]

        # Initialize components (lazy)
        self._llm = None
        self._gdrive = None
        self._sheets = None

    def _normalize_patient_name(self, extracted_name: str) -> str:
        """Map extracted full name to configured family member folder name."""
        if not extracted_name:
            return "Unknown"

        extracted_lower = extracted_name.lower()
        for family_name in self.family_names:
            # Check if family name is contained in extracted name
            if family_name.lower() in extracted_lower:
                return family_name

        # No match found, return as-is
        return extracted_name

    def _load_config(self, config_path: str) -> dict:
        """Load configuration from YAML."""
        config_path = Path(config_path)
        if not config_path.exists():
            logger.warning(f"Config not found: {config_path}, using defaults")
            return {}

        with open(config_path) as f:
            return yaml.safe_load(f) or {}

    @property
    def llm(self):
        """Lazy-load vision LLM extractor."""
        if self._llm is None:
            llm_config = self.config.get("llm", {})
            use_mock = llm_config.get("use_mock", False)

            # Build API base URL
            provider = llm_config.get("provider", "ollama")
            if provider == "ollama":
                default_base = "http://localhost:11434/v1"
            else:  # vllm
                default_base = "http://localhost:8000/v1"

            self._llm = get_extractor(
                use_mock=use_mock,
                api_base=llm_config.get("api_base", default_base),
                model=llm_config.get("model", "mistral-small3"),
                max_tokens=llm_config.get("max_tokens", 2048),
                temperature=llm_config.get("temperature", 0.1),
            )
        return self._llm

    @property
    def gdrive(self):
        """Lazy-load Google Drive client."""
        if self._gdrive is None:
            gdrive_config = self.config.get("google_drive", {})
            self._gdrive = GDriveClient(
                credentials_file=gdrive_config.get(
                    "credentials_file", "config/credentials/gdrive_credentials.json"
                ),
                token_file=gdrive_config.get(
                    "token_file", "config/credentials/gdrive_token.json"
                ),
                root_folder_name=gdrive_config.get("root_folder", "HSA_Receipts"),
            )
        return self._gdrive

    @property
    def sheets(self):
        """Lazy-load Google Sheets client."""
        if self._sheets is None:
            sheets_config = self.config.get("google_sheets", {})
            self._sheets = GSheetsClient(
                credentials_file=self.config.get("google_drive", {}).get(
                    "credentials_file", "config/credentials/gdrive_credentials.json"
                ),
                spreadsheet_name=sheets_config.get("spreadsheet_name", "HSA_Master_Index"),
                worksheet_name=sheets_config.get("worksheet_name", "Receipts"),
            )
        return self._sheets

    def _classify_confidence(self, score: float) -> str:
        """Classify extraction confidence level."""
        if score >= self.auto_threshold:
            return "high"
        elif score >= self.review_threshold:
            return "medium"
        else:
            return "low"

    def process_file(
        self,
        file_path: str,
        patient_hint: str | None = None,
        dry_run: bool = False,
    ) -> dict | None:
        """
        Process a single receipt file.

        Args:
            file_path: Path to receipt file (PDF or image)
            patient_hint: Optional hint for patient name
            dry_run: If True, don't upload or record, just return results

        Returns:
            Dict with processing results, or None if failed
        """
        file_path = Path(file_path)
        if not file_path.exists():
            logger.error(f"File not found: {file_path}")
            return None

        logger.info(f"Processing: {file_path.name}")

        # Step 1: Vision LLM extraction (direct from image/PDF)
        try:
            extraction = self.llm.extract(file_path)
            confidence_level = self._classify_confidence(extraction.confidence_score)
            logger.info(
                f"Extraction [{confidence_level}]: {extraction.provider_name} - "
                f"{extraction.service_type} - ${extraction.patient_responsibility:.2f}"
            )
        except Exception as e:
            logger.error(f"Vision extraction failed: {e}")
            return None

        # Apply patient hint if provided (always override), otherwise normalize extracted name
        if patient_hint:
            folder_patient = patient_hint
        else:
            folder_patient = self._normalize_patient_name(extraction.patient_name)

        # Update extraction with normalized patient name for folder/filename
        if folder_patient != extraction.patient_name:
            extraction = ExtractedReceipt(
                **{**extraction.to_dict(), "patient_name": folder_patient}
            )

        # Step 2: Validate HSA eligibility date
        if extraction.service_date:
            try:
                service_date = datetime.strptime(extraction.service_date, "%Y-%m-%d")
                if service_date < self.hsa_start_date:
                    logger.warning(
                        f"Service date {extraction.service_date} is before HSA start date"
                    )
                    notes = extraction.notes
                    notes += f" [Pre-HSA: before {self.hsa_start_date.strftime('%Y-%m-%d')}]"
                    extraction = ExtractedReceipt(
                        **{**extraction.to_dict(), "hsa_eligible": False, "notes": notes}
                    )
            except ValueError:
                pass

        # Step 3: Generate filename
        file_extension = file_path.suffix.lstrip(".")
        new_filename = extraction.generate_filename(extension=file_extension)
        logger.info(f"Generated filename: {new_filename}")

        # Determine confidence-based action
        confidence_level = self._classify_confidence(extraction.confidence_score)
        needs_review = confidence_level != "high"

        if dry_run:
            return {
                "file": str(file_path),
                "extraction": extraction.to_dict(),
                "new_filename": new_filename,
                "confidence_level": confidence_level,
                "needs_review": needs_review,
                "would_upload_to": f"{extraction.category}/{extraction.patient_name}",
            }

        # Step 4: Upload to Google Drive
        try:
            folder_id = self.gdrive.get_folder_id_for_receipt(
                category=extraction.category,
                patient=extraction.patient_name,
            )

            drive_file = self.gdrive.upload_file(
                local_path=file_path,
                folder_id=folder_id,
                new_name=new_filename,
            )
            logger.info(f"Uploaded to Drive: {drive_file.web_link}")
        except Exception as e:
            logger.error(f"Drive upload failed: {e}")
            return None

        # Step 5: Add to tracking spreadsheet
        record_id = None
        try:
            file_path_str = (
                self.gdrive.get_folder_path(extraction.category, extraction.patient_name)
                + "/"
                + new_filename
            )

            record = create_record_from_extraction(
                extraction=extraction,
                file_path=file_path_str,
                file_link=drive_file.web_link,
            )
            record_id = self.sheets.add_record(record)
            logger.info(f"Added to spreadsheet: ID {record_id}")
        except Exception as e:
            logger.error(f"Spreadsheet update failed: {e}")
            # Don't fail - file is uploaded

        return {
            "file": str(file_path),
            "extraction": extraction.to_dict(),
            "confidence_level": confidence_level,
            "needs_review": needs_review,
            "drive_file": {
                "id": drive_file.id,
                "name": drive_file.name,
                "link": drive_file.web_link,
            },
            "record_id": record_id,
        }

    def process_directory(
        self,
        directory: str,
        patient_hint: str | None = None,
        dry_run: bool = False,
    ) -> list[dict]:
        """
        Process all receipt files in a directory.

        Args:
            directory: Path to directory
            patient_hint: Optional hint for patient name
            dry_run: If True, don't upload or record

        Returns:
            List of processing results
        """
        directory = Path(directory)
        results = []

        # Supported file types
        extensions = {".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".webp", ".gif"}

        for file_path in sorted(directory.iterdir()):
            if file_path.suffix.lower() in extensions:
                result = self.process_file(
                    file_path=str(file_path),
                    patient_hint=patient_hint,
                    dry_run=dry_run,
                )
                if result:
                    results.append(result)

        logger.info(f"Processed {len(results)} files from {directory}")
        return results

    def setup(self, family_members: list[str] | None = None):
        """
        Initial setup: create folder structure and spreadsheet.

        Args:
            family_members: List of family member names
        """
        family = self.config.get("family", [])
        if family_members:
            family_names = family_members
        elif family:
            family_names = [m.get("name", "Unknown") for m in family]
        else:
            family_names = ["Ming", "Wife", "Son"]

        logger.info("Setting up HSA receipt system...")

        # Create folder structure
        folders = self.gdrive.setup_folder_structure(
            year=datetime.now().year,
            family_members=family_names,
        )
        logger.info(f"Created {len(folders)} folders in Google Drive")

        # Initialize spreadsheet
        _ = self.sheets._get_worksheet()
        logger.info(f"Spreadsheet ready: {self.sheets._spreadsheet.url}")

        print("\n Setup complete!")
        print(f" Google Drive: {len(folders)} folders created")
        print(f" Spreadsheet: {self.sheets._spreadsheet.url}")

        return {
            "folders": folders,
            "spreadsheet_url": self.sheets._spreadsheet.url,
        }

    def get_summary(self) -> dict:
        """Get summary of all HSA expenses."""
        summary = self.sheets.get_summary_by_year()
        unreimbursed = self.sheets.get_unreimbursed_total()

        return {
            "by_year": summary,
            "total_unreimbursed": unreimbursed,
        }


# CLI using Click
try:
    import click
    from rich.console import Console
    from rich.table import Table

    console = Console()

    @click.group()
    @click.option("--config", default="config/config.yaml", help="Config file path")
    @click.pass_context
    def cli(ctx, config):
        """HSA Receipt Processing Pipeline"""
        ctx.ensure_object(dict)
        ctx.obj["pipeline"] = HSAReceiptPipeline(config_path=config)

    @cli.command()
    @click.option("--family", multiple=True, help="Family member names")
    @click.pass_context
    def setup(ctx, family):
        """Initial setup: create folder structure and spreadsheet."""
        pipeline = ctx.obj["pipeline"]
        family_list = list(family) if family else None
        pipeline.setup(family_members=family_list)

    @cli.command()
    @click.option("--file", "file_path", help="Single file to process")
    @click.option("--dir", "dir_path", help="Directory to process")
    @click.option("--patient", help="Patient name hint")
    @click.option("--dry-run", is_flag=True, help="Preview without uploading")
    @click.pass_context
    def process(ctx, file_path, dir_path, patient, dry_run):
        """Process receipt files."""
        import json

        pipeline = ctx.obj["pipeline"]

        if file_path:
            result = pipeline.process_file(file_path, patient_hint=patient, dry_run=dry_run)
            if result:
                console.print_json(json.dumps(result, indent=2, default=str))
        elif dir_path:
            results = pipeline.process_directory(dir_path, patient_hint=patient, dry_run=dry_run)
            console.print(f"Processed {len(results)} files")
            for r in results:
                status = "[yellow]REVIEW[/yellow]" if r.get("needs_review") else "[green]OK[/green]"
                console.print(f"  {status} {r['extraction']['provider_name']}: ${r['extraction']['patient_responsibility']:.2f}")
        else:
            console.print("[red]Specify --file or --dir[/red]")

    @cli.command()
    @click.pass_context
    def summary(ctx):
        """Show HSA expense summary."""
        pipeline = ctx.obj["pipeline"]
        data = pipeline.get_summary()

        table = Table(title="HSA Expense Summary")
        table.add_column("Year")
        table.add_column("Receipts", justify="right")
        table.add_column("Billed", justify="right")
        table.add_column("Insurance", justify="right")
        table.add_column("Your Cost", justify="right")
        table.add_column("Reimbursed", justify="right")

        for year, info in sorted(data["by_year"].items()):
            table.add_row(
                str(year),
                str(info["count"]),
                f"${info['total_billed']:,.2f}",
                f"${info['total_insurance']:,.2f}",
                f"${info['total_responsibility']:,.2f}",
                f"${info['total_reimbursed']:,.2f}",
            )

        console.print(table)
        console.print(f"\n Total Unreimbursed: [bold]${data['total_unreimbursed']:,.2f}[/bold]")

    @cli.command("email-scan")
    @click.option("--since", help="Scan emails since date (YYYY-MM-DD)")
    @click.option("--dry-run", is_flag=True, help="Preview without processing")
    @click.option("--output-dir", default="tmp/email_attachments", help="Where to save attachments")
    @click.pass_context
    def email_scan(ctx, since, dry_run, output_dir):
        """Scan Gmail for medical emails and process attachments."""
        from extractors.gmail_extractor import GmailExtractor
        from pathlib import Path
        import tempfile

        pipeline = ctx.obj["pipeline"]
        config = pipeline.config

        # Get credentials path from config
        gdrive_config = config.get("google_drive", {})
        creds_file = gdrive_config.get("credentials_file", "config/credentials/gdrive_credentials.json")
        token_file = "config/credentials/gmail_token.json"

        # Parse since date
        since_date = None
        if since:
            since_date = datetime.strptime(since, "%Y-%m-%d")
        else:
            # Default: HSA start date
            since_date = pipeline.hsa_start_date

        console.print(f"[cyan]Scanning emails since {since_date.strftime('%Y-%m-%d')}...[/cyan]")

        extractor = GmailExtractor(credentials_file=creds_file, token_file=token_file)

        # Create output dir
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Extract medical emails
        messages = extractor.extract_medical_emails(after_date=since_date, output_dir=output_path)

        console.print(f"\n[green]Found {len(messages)} medical emails[/green]")

        # Count and list attachments
        total_attachments = 0
        for msg in messages:
            if msg.attachments:
                total_attachments += len(msg.attachments)
                console.print(f"  {msg.date.strftime('%Y-%m-%d')} | {msg.sender[:40]} | {msg.subject[:50]}")
                for att in msg.attachments:
                    console.print(f"    └─ [blue]{att.filename}[/blue] ({att.mime_type})")

        console.print(f"\n[cyan]Total attachments: {total_attachments}[/cyan]")

        if dry_run:
            console.print("[yellow]Dry run - not processing files[/yellow]")
            return

        # Process each PDF attachment
        if total_attachments > 0:
            console.print("\n[cyan]Processing attachments through pipeline...[/cyan]")
            processed = 0
            for msg in messages:
                for att in msg.attachments:
                    if att.mime_type == "application/pdf" or att.filename.lower().endswith(".pdf"):
                        # Save to temp file
                        filepath = output_path / f"{msg.date.strftime('%Y%m%d')}_{att.filename}"
                        with open(filepath, "wb") as f:
                            f.write(att.data)

                        console.print(f"\nProcessing: {att.filename}")
                        result = pipeline.process_file(str(filepath), dry_run=False)
                        if result:
                            processed += 1
                            status = "[green]OK[/green]" if not result.get("needs_review") else "[yellow]REVIEW[/yellow]"
                            console.print(f"  {status} {result['extraction']['provider_name']}: ${result['extraction']['patient_responsibility']:.2f}")

            console.print(f"\n[green]Processed {processed} attachments[/green]")

except ImportError:
    # Fallback if click/rich not installed
    def cli():
        print("CLI requires click and rich. Run: uv add click rich")
        sys.exit(1)


if __name__ == "__main__":
    cli()
