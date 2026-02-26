import logging
import os
from dataclasses import dataclass
from typing import List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)


@dataclass
class GoogleDriveConfig:
    credentials_file: str  # path to service account JSON key file
    folder_id: str  # Google Drive folder ID


class GoogleDriveClient:
    """
    Google Drive client using a service account (JSON key file).
    Uploads, lists and deletes files in a specific folder via Google Drive API v3.
    """

    def __init__(self, cfg: GoogleDriveConfig, session: Optional[requests.Session] = None):
        self.cfg = cfg
        self.session = session or requests.Session()
        self.base_url = "https://www.googleapis.com"
        self.token: Optional[str] = None

    def _ensure_token(self):
        if self.token:
            return
        import json
        import time

        with open(self.cfg.credentials_file, 'r', encoding='utf-8') as f:
            creds = json.load(f)

        # Build JWT for Google OAuth2
        import hashlib
        import base64
        import struct

        private_key_pem = creds['private_key']
        client_email = creds['client_email']
        token_uri = creds.get('token_uri', 'https://oauth2.googleapis.com/token')

        now = int(time.time())
        header = {"alg": "RS256", "typ": "JWT"}
        payload = {
            "iss": client_email,
            "scope": "https://www.googleapis.com/auth/drive.file",
            "aud": token_uri,
            "iat": now,
            "exp": now + 3600,
        }

        def _b64url(data: bytes) -> str:
            return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')

        header_b64 = _b64url(json.dumps(header, separators=(',', ':')).encode())
        payload_b64 = _b64url(json.dumps(payload, separators=(',', ':')).encode())
        sign_input = f"{header_b64}.{payload_b64}".encode()

        # Sign with RSA SHA-256 using cryptography library
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding

        private_key = serialization.load_pem_private_key(private_key_pem.encode(), password=None)
        signature = private_key.sign(sign_input, padding.PKCS1v15(), hashes.SHA256())

        jwt_token = f"{header_b64}.{payload_b64}.{_b64url(signature)}"

        resp = self.session.post(token_uri, data={
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": jwt_token,
        }, timeout=60)
        if resp.status_code != 200:
            logger.error("Failed to obtain Google access token: %s %s", resp.status_code, resp.text)
            raise RuntimeError(f"Google token error: {resp.status_code} {resp.text}")
        self.token = resp.json().get("access_token")
        if not self.token:
            raise RuntimeError("No access_token in Google token response")

    def _headers(self):
        self._ensure_token()
        return {"Authorization": f"Bearer {self.token}"}

    def upload_file(self, local_file_path: str, dry_run: bool = False) -> str:
        filename = os.path.basename(local_file_path)
        if dry_run:
            logger.info("[DRY-RUN] Would upload %s to Google Drive folder %s", filename, self.cfg.folder_id)
            return filename
        self._ensure_token()

        file_size = os.path.getsize(local_file_path)

        # Initiate resumable upload
        import json
        metadata = {
            "name": filename,
            "parents": [self.cfg.folder_id],
        }
        init_headers = {
            **self._headers(),
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Length": str(file_size),
        }
        init_url = f"{self.base_url}/upload/drive/v3/files?uploadType=resumable"
        resp = self.session.post(init_url, headers=init_headers, data=json.dumps(metadata), timeout=60)
        if resp.status_code != 200:
            logger.error("Failed to initiate Google Drive upload: %s %s", resp.status_code, resp.text)
            raise RuntimeError(f"Google Drive upload init failed: {resp.status_code} {resp.text}")
        upload_url = resp.headers.get("Location")
        if not upload_url:
            raise RuntimeError("No Location header in resumable upload response")

        # Upload in chunks
        chunk_size = 5 * 1024 * 1024  # 5 MB
        with open(local_file_path, 'rb') as f:
            start = 0
            while start < file_size:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                end = start + len(chunk) - 1
                headers = {
                    "Content-Length": str(len(chunk)),
                    "Content-Range": f"bytes {start}-{end}/{file_size}",
                }
                r = self.session.put(upload_url, headers=headers, data=chunk, timeout=600)
                if r.status_code not in (200, 201, 308):
                    logger.error("Google Drive chunk upload failed: %s %s", r.status_code, r.text)
                    raise RuntimeError(f"Google Drive chunk upload failed: {r.status_code} {r.text}")
                start = end + 1

        logger.info("Uploaded to Google Drive: %s", filename)
        return filename

    def list_files(self) -> List[Tuple[str, str]]:
        """
        Returns list of (name, id) in the configured folder.
        """
        query = f"'{self.cfg.folder_id}' in parents and trashed = false"
        url = (
            f"{self.base_url}/drive/v3/files"
            f"?q={requests.utils.quote(query)}"
            f"&fields=files(id,name)&pageSize=1000"
        )
        resp = self.session.get(url, headers=self._headers(), timeout=60)
        if resp.status_code >= 400:
            logger.error("Failed to list Google Drive files: %s %s", resp.status_code, resp.text)
            raise RuntimeError(f"Google Drive list files failed: {resp.status_code} {resp.text}")
        files = resp.json().get('files', [])
        return [(f['name'], f['id']) for f in files if 'name' in f and 'id' in f]

    def delete_file(self, file_id: str) -> None:
        url = f"{self.base_url}/drive/v3/files/{file_id}"
        resp = self.session.delete(url, headers=self._headers(), timeout=60)
        if resp.status_code not in (200, 204):
            logger.error("Failed to delete Google Drive file id=%s: %s %s", file_id, resp.status_code, resp.text)
            raise RuntimeError(f"Google Drive delete failed: {resp.status_code} {resp.text}")
