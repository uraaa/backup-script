import logging
import os
from dataclasses import dataclass
from typing import List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)


@dataclass
class SharePointConfig:
    tenant_id: str
    client_id: str
    client_secret: str
    site_id: str
    drive_id: str
    folder_path: str  # e.g., "/backups"


class SharePointClient:
    def __init__(self, cfg: SharePointConfig, session: Optional[requests.Session] = None):
        self.cfg = cfg
        self.session = session or requests.Session()
        self.base_url = "https://graph.microsoft.com/v1.0"
        self.token: Optional[str] = None

    def _ensure_token(self):
        if self.token:
            return
        token_url = f"https://login.microsoftonline.com/{self.cfg.tenant_id}/oauth2/v2.0/token"
        data = {
            "client_id": self.cfg.client_id,
            "client_secret": self.cfg.client_secret,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials",
        }
        resp = self.session.post(token_url, data=data, timeout=60)
        if resp.status_code != 200:
            logger.error("Failed to obtain Graph token: %s %s", resp.status_code, resp.text)
            raise RuntimeError(f"Graph token error: {resp.status_code} {resp.text}")
        self.token = resp.json().get("access_token")
        if not self.token:
            raise RuntimeError("No access_token in Graph token response")

    def _headers(self):
        self._ensure_token()
        return {"Authorization": f"Bearer {self.token}"}

    def _resolve_folder_item(self) -> dict:
        # Access driveItem that represents the folder path
        # API: /sites/{site-id}/drives/{drive-id}/root:{item-path}
        path = self.cfg.folder_path.rstrip('/')
        url = f"{self.base_url}/sites/{self.cfg.site_id}/drives/{self.cfg.drive_id}/root:{path}"
        resp = self.session.get(url, headers=self._headers(), timeout=60)
        if resp.status_code >= 400:
            logger.error("Failed to resolve SharePoint folder %s: %s %s", path, resp.status_code, resp.text)
            raise RuntimeError(f"Resolve folder failed: {resp.status_code} {resp.text}")
        return resp.json()

    def upload_file(self, local_file_path: str, dry_run: bool = False) -> str:
        filename = os.path.basename(local_file_path)
        if dry_run:
            logger.info("[DRY-RUN] Would upload %s to SharePoint folder %s", filename, self.cfg.folder_path)
            return filename
        self._ensure_token()
        # Simple upload for files < 4MB. Our archives are larger, use upload session.
        # Create upload session
        url = (
            f"{self.base_url}/sites/{self.cfg.site_id}/drives/{self.cfg.drive_id}"
            f"/root:{self.cfg.folder_path.rstrip('/')}/{filename}:/createUploadSession"
        )
        resp = self.session.post(url, headers=self._headers(), json={}, timeout=60)
        if resp.status_code >= 400:
            logger.error("Failed to create upload session: %s %s", resp.status_code, resp.text)
            raise RuntimeError(f"Upload session failed: {resp.status_code} {resp.text}")
        upload_url = resp.json().get("uploadUrl")
        if not upload_url:
            raise RuntimeError("No uploadUrl in session response")

        chunk_size = 5 * 1024 * 1024  # 5MB
        size = os.path.getsize(local_file_path)
        with open(local_file_path, 'rb') as f:
            start = 0
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                end = start + len(chunk) - 1
                headers = {
                    "Content-Length": str(len(chunk)),
                    "Content-Range": f"bytes {start}-{end}/{size}",
                }
                r = self.session.put(upload_url, headers=headers, data=chunk, timeout=600)
                if r.status_code not in (200, 201, 202):
                    logger.error("Chunk upload failed: %s %s", r.status_code, r.text)
                    raise RuntimeError(f"Chunk upload failed: {r.status_code} {r.text}")
                start = end + 1
        logger.info("Uploaded to SharePoint: %s", filename)
        return filename

    def list_files(self) -> List[Tuple[str, str]]:
        """
        Returns list of (name, id) in the folder.
        """
        url = (
            f"{self.base_url}/sites/{self.cfg.site_id}/drives/{self.cfg.drive_id}"
            f"/root:{self.cfg.folder_path.rstrip('/')}:/children?$select=name,id,createdDateTime,lastModifiedDateTime&$top=200"
        )
        resp = self.session.get(url, headers=self._headers(), timeout=60)
        if resp.status_code >= 400:
            logger.error("Failed to list files: %s %s", resp.status_code, resp.text)
            raise RuntimeError(f"List files failed: {resp.status_code} {resp.text}")
        items = resp.json().get('value', [])
        return [(it['name'], it['id']) for it in items if 'name' in it and 'id' in it]

    def delete_file(self, item_id: str) -> None:
        url = f"{self.base_url}/sites/{self.cfg.site_id}/drives/{self.cfg.drive_id}/items/{item_id}"
        resp = self.session.delete(url, headers=self._headers(), timeout=60)
        if resp.status_code not in (200, 204):
            logger.error("Failed to delete file id=%s: %s %s", item_id, resp.status_code, resp.text)
            raise RuntimeError(f"Delete failed: {resp.status_code} {resp.text}")
