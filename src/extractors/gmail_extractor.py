"""Gmail Extractor for HSA Receipt System - extracts medical emails and attachments"""
import base64
from pathlib import Path
from datetime import datetime
from typing import List, Optional
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class EmailAttachment:
    filename: str
    mime_type: str
    data: bytes
    message_id: str
    subject: str
    sender: str
    date: datetime


@dataclass
class EmailMessage:
    message_id: str
    thread_id: str
    subject: str
    sender: str
    date: datetime
    body_text: str
    body_html: str
    attachments: List[EmailAttachment]
    labels: List[str]


class GmailExtractor:
    """Extract medical-related emails and attachments from Gmail."""
    
    MEDICAL_QUERIES = [
        'from:(sutter OR sutterhealth) has:attachment',
        'from:(stanford OR stanfordhealthcare) has:attachment',
        'from:("delta dental" OR deltadentalins) subject:(EOB OR statement)',
        'from:(vsp OR "vision service plan") has:attachment',
        'from:(cvs OR cvshealth) subject:(prescription OR receipt)',
        'from:(express-scripts OR expressscripts) subject:(EOB OR claim)',
    ]
    
    SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
    
    def __init__(self, credentials_file: str, token_file: str, user_email: str = "me"):
        self.credentials_file = Path(credentials_file)
        self.token_file = Path(token_file)
        self.user_email = user_email
        self._service = None
        
    def _get_service(self):
        if self._service is not None:
            return self._service
            
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
        
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
        
        self._service = build('gmail', 'v1', credentials=creds)
        return self._service
    
    def search_messages(self, query: str, max_results: int = 100, after_date: Optional[datetime] = None) -> List[str]:
        service = self._get_service()
        if after_date:
            query = f"{query} after:{after_date.strftime('%Y/%m/%d')}"
        
        message_ids = []
        page_token = None
        
        while len(message_ids) < max_results:
            results = service.users().messages().list(
                userId=self.user_email, q=query,
                maxResults=min(100, max_results - len(message_ids)),
                pageToken=page_token
            ).execute()
            
            message_ids.extend([m['id'] for m in results.get('messages', [])])
            page_token = results.get('nextPageToken')
            if not page_token:
                break
        
        return message_ids
    
    def extract_medical_emails(self, after_date: Optional[datetime] = None, output_dir: Optional[Path] = None) -> List[EmailMessage]:
        all_messages = []
        seen_ids = set()
        
        for query in self.MEDICAL_QUERIES:
            message_ids = self.search_messages(query=query, max_results=50, after_date=after_date)
            
            for msg_id in message_ids:
                if msg_id in seen_ids:
                    continue
                seen_ids.add(msg_id)
                
                try:
                    msg = self.get_message(msg_id)
                    all_messages.append(msg)
                    if output_dir and msg.attachments:
                        self._save_attachments(msg.attachments, output_dir)
                except Exception as e:
                    logger.error(f"Error processing message {msg_id}: {e}")
        
        logger.info(f"Extracted {len(all_messages)} unique medical emails")
        return all_messages
    
    def get_message(self, message_id: str) -> EmailMessage:
        service = self._get_service()
        msg = service.users().messages().get(userId=self.user_email, id=message_id, format='full').execute()
        headers = {h['name'].lower(): h['value'] for h in msg['payload'].get('headers', [])}

        from email.utils import parsedate_to_datetime
        try:
            date = parsedate_to_datetime(headers.get('date', ''))
        except Exception:
            date = datetime.now()

        # Extract body and attachments
        body_text, body_html, attachments = self._parse_payload(
            msg['payload'], message_id, headers.get('subject', ''), headers.get('from', ''), date
        )

        return EmailMessage(
            message_id=message_id,
            thread_id=msg.get('threadId', ''),
            subject=headers.get('subject', '(No Subject)'),
            sender=headers.get('from', ''),
            date=date,
            body_text=body_text,
            body_html=body_html,
            attachments=attachments,
            labels=msg.get('labelIds', [])
        )

    def _parse_payload(self, payload: dict, msg_id: str, subject: str, sender: str, date: datetime):
        """Recursively parse email payload to extract body and attachments."""
        body_text = ""
        body_html = ""
        attachments = []

        mime_type = payload.get('mimeType', '')
        parts = payload.get('parts', [])

        if parts:
            # Multipart message
            for part in parts:
                t, h, a = self._parse_payload(part, msg_id, subject, sender, date)
                body_text += t
                body_html += h
                attachments.extend(a)
        else:
            # Single part
            body = payload.get('body', {})
            data = body.get('data')
            attachment_id = body.get('attachmentId')
            filename = payload.get('filename', '')

            if attachment_id and filename:
                # This is an attachment - fetch it
                att_data = self._get_attachment(msg_id, attachment_id)
                if att_data:
                    attachments.append(EmailAttachment(
                        filename=filename,
                        mime_type=mime_type,
                        data=att_data,
                        message_id=msg_id,
                        subject=subject,
                        sender=sender,
                        date=date,
                    ))
            elif data:
                # This is body content
                decoded = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
                if 'text/plain' in mime_type:
                    body_text += decoded
                elif 'text/html' in mime_type:
                    body_html += decoded

        return body_text, body_html, attachments

    def _get_attachment(self, message_id: str, attachment_id: str) -> Optional[bytes]:
        """Fetch attachment data by ID."""
        try:
            service = self._get_service()
            att = service.users().messages().attachments().get(
                userId=self.user_email, messageId=message_id, id=attachment_id
            ).execute()
            return base64.urlsafe_b64decode(att['data'])
        except Exception as e:
            logger.error(f"Failed to get attachment {attachment_id}: {e}")
            return None
    
    def _save_attachments(self, attachments: List[EmailAttachment], output_dir: Path):
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        for att in attachments:
            filepath = output_dir / f"{att.date.strftime('%Y%m%d')}_{att.filename}"
            with open(filepath, 'wb') as f:
                f.write(att.data)


def setup_gmail_oauth(credentials_file: str, token_file: str):
    extractor = GmailExtractor(credentials_file=credentials_file, token_file=token_file)
    service = extractor._get_service()
    profile = service.users().getProfile(userId='me').execute()
    print(f"Successfully authorized: {profile['emailAddress']}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "setup":
        creds = sys.argv[2] if len(sys.argv) > 2 else "config/credentials/gdrive_credentials.json"
        token = sys.argv[3] if len(sys.argv) > 3 else "config/credentials/gmail_token.json"
        setup_gmail_oauth(creds, token)
