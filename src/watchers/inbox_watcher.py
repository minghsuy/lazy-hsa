"""Google Drive _Inbox Watcher - monitors for new files and processes them."""

import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class DriveInboxWatcher:
    """
    Watch Google Drive _Inbox folder for new files and process them.

    Usage:
        watcher = DriveInboxWatcher(gdrive_client, process_callback)
        watcher.poll()  # One-time check
        watcher.watch(interval=60)  # Continuous polling
    """

    def __init__(
        self,
        gdrive_client,
        process_callback: Callable[[str], dict],
        inbox_folder_name: str = "_Inbox",
        family_names: Optional[list[str]] = None,
    ):
        """
        Args:
            gdrive_client: GDriveClient instance
            process_callback: Function(local_path, patient_hint) -> result dict
            inbox_folder_name: Name of inbox folder to watch
            family_names: List of family member names for filename-based patient detection
        """
        self.gdrive = gdrive_client
        self.process_callback = process_callback
        self.inbox_folder_name = inbox_folder_name
        self.family_names = family_names or ["Ming", "Vanessa", "Maxwell"]
        self._inbox_folder_id = None
        self._processed_files = set()  # Track processed file IDs

    def _get_inbox_folder_id(self) -> str:
        """Get or cache the _Inbox folder ID."""
        if self._inbox_folder_id is None:
            # Find the inbox folder under root
            root_id = self.gdrive.get_or_create_folder(self.gdrive.root_folder_name)
            self._inbox_folder_id = self.gdrive.get_or_create_folder(
                self.inbox_folder_name, root_id
            )
        return self._inbox_folder_id

    def list_inbox_files(self) -> list[dict]:
        """List all files in the _Inbox folder."""
        service = self.gdrive._get_service()
        inbox_id = self._get_inbox_folder_id()

        # Query for files in inbox (not folders)
        query = f"'{inbox_id}' in parents and mimeType != 'application/vnd.google-apps.folder' and trashed = false"

        results = service.files().list(
            q=query,
            fields="files(id, name, mimeType, createdTime, modifiedTime)",
            orderBy="createdTime desc",
            pageSize=100,
        ).execute()

        return results.get("files", [])

    def download_file(self, file_id: str, filename: str, download_dir: Path) -> Path:
        """Download a file from Drive to local path."""
        import io
        from googleapiclient.http import MediaIoBaseDownload

        service = self.gdrive._get_service()
        download_dir.mkdir(parents=True, exist_ok=True)
        local_path = download_dir / filename

        request = service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)

        done = False
        while not done:
            status, done = downloader.next_chunk()
            if status:
                logger.debug(f"Download progress: {int(status.progress() * 100)}%")

        with open(local_path, "wb") as f:
            f.write(fh.getvalue())

        logger.info(f"Downloaded: {filename}")
        return local_path

    def move_file_to_folder(self, file_id: str, dest_folder_id: str):
        """Move a file to a different folder (remove from inbox)."""
        service = self.gdrive._get_service()

        # Get current parents
        file = service.files().get(fileId=file_id, fields="parents").execute()
        previous_parents = ",".join(file.get("parents", []))

        # Move to new folder
        service.files().update(
            fileId=file_id,
            addParents=dest_folder_id,
            removeParents=previous_parents,
            fields="id, parents",
        ).execute()

    def delete_file(self, file_id: str):
        """Delete a file from Drive (move to trash)."""
        service = self.gdrive._get_service()
        service.files().update(fileId=file_id, body={"trashed": True}).execute()

    def poll(self, download_dir: Path = None) -> list[dict]:
        """
        Check inbox for new files and process them.

        Returns:
            List of processing results
        """
        download_dir = download_dir or Path("tmp/inbox_downloads")
        results = []

        files = self.list_inbox_files()
        logger.info(f"Found {len(files)} files in _Inbox")

        for file_info in files:
            file_id = file_info["id"]
            filename = file_info["name"]

            # Skip if already processed this session
            if file_id in self._processed_files:
                continue

            # Skip non-receipt files
            if not self._is_receipt_file(filename):
                logger.debug(f"Skipping non-receipt file: {filename}")
                continue

            # Extract patient hint from filename
            patient_hint = self._extract_patient_hint(filename)
            if patient_hint:
                logger.info(f"Processing: {filename} (patient hint: {patient_hint})")
            else:
                logger.info(f"Processing: {filename}")

            try:
                # Download file
                local_path = self.download_file(file_id, filename, download_dir)

                # Process through callback with patient hint
                result = self.process_callback(str(local_path), patient_hint)

                if result:
                    results.append({
                        "file": filename,
                        "file_id": file_id,
                        "result": result,
                    })

                    # Mark as processed
                    self._processed_files.add(file_id)

                    # Delete local temp file
                    local_path.unlink(missing_ok=True)

                    # Delete from inbox (file has been uploaded to proper folder)
                    self.delete_file(file_id)
                    logger.info(f"Processed and removed from inbox: {filename}")

            except Exception as e:
                logger.error(f"Error processing {filename}: {e}")
                results.append({
                    "file": filename,
                    "file_id": file_id,
                    "error": str(e),
                })

        return results

    def _is_receipt_file(self, filename: str) -> bool:
        """Check if file is a receipt type we can process."""
        extensions = {".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".webp", ".gif"}
        return Path(filename).suffix.lower() in extensions

    def _extract_patient_hint(self, filename: str) -> Optional[str]:
        """Extract patient name hint from filename if family name is present.

        Examples:
            "Amazon Miralax Vanessa Surgery.pdf" -> "Vanessa"
            "CVS_Ming_prescription.jpg" -> "Ming"
            "receipt.pdf" -> None
        """
        filename_lower = filename.lower()
        for name in self.family_names:
            if name.lower() in filename_lower:
                return name
        return None

    def watch(self, interval: int = 60, max_iterations: int = None):
        """
        Continuously poll inbox for new files.

        Args:
            interval: Seconds between polls
            max_iterations: Stop after N iterations (None = forever)
        """
        iteration = 0
        logger.info(f"Starting inbox watcher (polling every {interval}s)")

        try:
            while max_iterations is None or iteration < max_iterations:
                results = self.poll()

                if results:
                    logger.info(f"Processed {len(results)} files")
                    for r in results:
                        if "error" in r:
                            logger.error(f"  {r['file']}: {r['error']}")
                        else:
                            logger.info(f"  {r['file']}: OK")

                iteration += 1
                if max_iterations is None or iteration < max_iterations:
                    time.sleep(interval)

        except KeyboardInterrupt:
            logger.info("Watcher stopped by user")


def create_watcher_from_pipeline(pipeline) -> DriveInboxWatcher:
    """Create a watcher using the pipeline's process_file method."""
    return DriveInboxWatcher(
        gdrive_client=pipeline.gdrive,
        process_callback=lambda path: pipeline.process_file(path, dry_run=False),
    )
