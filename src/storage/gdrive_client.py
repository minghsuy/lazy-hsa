"""Google Drive Client for HSA Receipt System"""
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict
from dataclasses import dataclass
import logging
import mimetypes

logger = logging.getLogger(__name__)


@dataclass
class DriveFile:
    id: str
    name: str
    mime_type: str
    parent_id: str
    web_link: str
    created_time: datetime
    modified_time: datetime


class GDriveClient:
    """Google Drive client for HSA receipt file management."""
    
    SCOPES = ['https://www.googleapis.com/auth/drive.file', 'https://www.googleapis.com/auth/drive.metadata.readonly']
    
    # Default folder structure - family names are passed at runtime from config
    CATEGORIES = ["Medical", "Dental", "Vision", "Pharmacy"]
    EOB_CATEGORIES = ["Medical", "Dental", "Vision"]
    
    SPECIAL_FOLDERS = ["_Inbox", "_Processing", "_Rejected"]
    
    def __init__(self, credentials_file: str, token_file: str, root_folder_name: str = "HSA_Receipts"):
        self.credentials_file = Path(credentials_file)
        self.token_file = Path(token_file)
        self.root_folder_name = root_folder_name
        self._service = None
        self._folder_cache = {}
        
    def _get_service(self):
        if self._service is not None:
            return self._service

        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
        from google_auth_httplib2 import AuthorizedHttp
        import httplib2

        creds = None
        if self.token_file.exists():
            creds = Credentials.from_authorized_user_file(str(self.token_file), self.SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(str(self.credentials_file), self.SCOPES)
                creds = flow.run_local_server(port=0)

            self.token_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.token_file, 'w') as f:
                f.write(creds.to_json())

        # Build service with extended timeout (120 seconds for uploads)
        http = httplib2.Http(timeout=120)
        authorized_http = AuthorizedHttp(creds, http=http)
        self._service = build('drive', 'v3', http=authorized_http)
        return self._service
    
    def get_or_create_folder(self, folder_name: str, parent_id: Optional[str] = None) -> str:
        cache_key = f"{parent_id or 'root'}:{folder_name}"
        if cache_key in self._folder_cache:
            return self._folder_cache[cache_key]
        
        service = self._get_service()
        query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        if parent_id:
            query += f" and '{parent_id}' in parents"
        
        results = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
        files = results.get('files', [])
        
        if files:
            folder_id = files[0]['id']
        else:
            metadata = {'name': folder_name, 'mimeType': 'application/vnd.google-apps.folder'}
            if parent_id:
                metadata['parents'] = [parent_id]
            folder = service.files().create(body=metadata, fields='id').execute()
            folder_id = folder['id']
            logger.info(f"Created folder: {folder_name}")
        
        self._folder_cache[cache_key] = folder_id
        return folder_id
    
    def setup_folder_structure(self, year: Optional[int] = None, family_members: Optional[List[str]] = None) -> Dict[str, str]:
        year = year or datetime.now().year
        family_members = family_members or ["Ming", "Vanessa", "Maxwell"]
        folder_ids = {}

        root_id = self.get_or_create_folder(self.root_folder_name)
        folder_ids[self.root_folder_name] = root_id

        year_id = self.get_or_create_folder(str(year), root_id)
        folder_ids[f"{self.root_folder_name}/{year}"] = year_id

        # Create category folders with family member subfolders
        for category in self.CATEGORIES:
            cat_id = self.get_or_create_folder(category, year_id)
            cat_path = f"{self.root_folder_name}/{year}/{category}"
            folder_ids[cat_path] = cat_id

            for member in family_members:
                sub_id = self.get_or_create_folder(member, cat_id)
                folder_ids[f"{cat_path}/{member}"] = sub_id

        # EOBs folder with category subfolders
        eob_id = self.get_or_create_folder("EOBs", year_id)
        folder_ids[f"{self.root_folder_name}/{year}/EOBs"] = eob_id
        for eob_cat in self.EOB_CATEGORIES:
            sub_id = self.get_or_create_folder(eob_cat, eob_id)
            folder_ids[f"{self.root_folder_name}/{year}/EOBs/{eob_cat}"] = sub_id

        # Special folders at root level
        for special in self.SPECIAL_FOLDERS:
            sp_id = self.get_or_create_folder(special, root_id)
            folder_ids[f"{self.root_folder_name}/{special}"] = sp_id

        logger.info(f"Folder structure setup complete: {len(folder_ids)} folders")
        return folder_ids
    
    def upload_file(self, local_path: Path, folder_id: str, new_name: Optional[str] = None) -> DriveFile:
        service = self._get_service()
        local_path = Path(local_path)
        filename = new_name or local_path.name
        mime_type, _ = mimetypes.guess_type(str(local_path))
        mime_type = mime_type or 'application/octet-stream'

        metadata = {'name': filename, 'parents': [folder_id]}

        from googleapiclient.http import MediaFileUpload

        # Simple upload (works for files < 5MB, use resumable for larger)
        file_size = local_path.stat().st_size
        if file_size > 5 * 1024 * 1024:  # > 5MB
            media = MediaFileUpload(
                str(local_path),
                mimetype=mime_type,
                resumable=True,
                chunksize=5 * 1024 * 1024,  # 5MB chunks
            )
            request = service.files().create(
                body=metadata,
                media_body=media,
                fields='id, name, mimeType, parents, webViewLink, createdTime, modifiedTime',
            )
            response = None
            while response is None:
                status, response = request.next_chunk()
                if status:
                    logger.debug(f"Upload progress: {int(status.progress() * 100)}%")
            file = response
        else:
            # Simple upload for smaller files
            media = MediaFileUpload(str(local_path), mimetype=mime_type, resumable=False)
            file = service.files().create(
                body=metadata,
                media_body=media,
                fields='id, name, mimeType, parents, webViewLink, createdTime, modifiedTime',
            ).execute()

        logger.info(f"Uploaded file: {filename}")

        return DriveFile(
            id=file['id'], name=file['name'], mime_type=file['mimeType'],
            parent_id=file['parents'][0] if file.get('parents') else '',
            web_link=file.get('webViewLink', ''),
            created_time=datetime.fromisoformat(file['createdTime'].replace('Z', '+00:00')),
            modified_time=datetime.fromisoformat(file['modifiedTime'].replace('Z', '+00:00'))
        )
    
    def get_folder_path(self, category: str, patient: str, year: int = None) -> str:
        year = year or datetime.now().year
        return f"{self.root_folder_name}/{year}/{category.title()}/{patient}"
    
    def get_folder_id_for_receipt(self, category: str, patient: str, year: int = None) -> str:
        year = year or datetime.now().year
        root_id = self.get_or_create_folder(self.root_folder_name)
        year_id = self.get_or_create_folder(str(year), root_id)
        cat_id = self.get_or_create_folder(category.title(), year_id)
        return self.get_or_create_folder(patient, cat_id)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "setup":
        creds = sys.argv[2] if len(sys.argv) > 2 else "config/credentials/gdrive_credentials.json"
        token = sys.argv[3] if len(sys.argv) > 3 else "config/credentials/gdrive_token.json"
        client = GDriveClient(credentials_file=creds, token_file=token)
        folders = client.setup_folder_structure(year=2026, family_members=["Ming", "Wife", "Son"])
        print(f"Created {len(folders)} folders")
