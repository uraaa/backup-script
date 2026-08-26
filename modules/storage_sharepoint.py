import logging
import os
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

CHUNK_SIZE = 5 * 1024 * 1024
MAX_CHUNK_RETRIES = 5
RETRYABLE_UPLOAD_STATUS_CODES = {408, 416, 429, 500, 502, 503, 504}


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

    @staticmethod
    def _next_expected_start(payload: dict, fallback: int) -> int:
        ranges = payload.get("nextExpectedRanges") or []
        if not ranges:
            return fallback
        start = str(ranges[0]).split("-", 1)[0]
        return int(start) if start.isdigit() else fallback

    def _query_upload_start(self, upload_url: str, fallback: int) -> int:
        try:
            response = self.session.get(upload_url, timeout=60)
        except requests.RequestException as exc:
            logger.warning(
                "SharePoint upload status check failed at byte %s (%s)",
                fallback,
                type(exc).__name__,
            )
            return fallback
        if response.status_code == 200:
            return self._next_expected_start(response.json(), fallback)
        if response.status_code == 404:
            raise RuntimeError("SharePoint upload session expired")
        if response.status_code in RETRYABLE_UPLOAD_STATUS_CODES:
            return fallback
        raise RuntimeError(f"SharePoint upload status check failed: HTTP {response.status_code}")

    @staticmethod
    def _retry_delay(attempt: int, response=None) -> float:
        if response is not None:
            retry_after = response.headers.get("Retry-After") if hasattr(response, "headers") else None
            if retry_after and str(retry_after).isdigit():
                return min(float(retry_after), 30.0)
        return min(float(2 ** (attempt - 1)), 30.0)

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

        size = os.path.getsize(local_file_path)
        with open(local_file_path, 'rb') as f:
            start = 0
            failures = 0
            while start < size:
                f.seek(start)
                chunk = f.read(CHUNK_SIZE)
                end = start + len(chunk) - 1
                headers = {
                    "Content-Length": str(len(chunk)),
                    "Content-Range": f"bytes {start}-{end}/{size}",
                }
                response = None
                try:
                    response = self.session.put(upload_url, headers=headers, data=chunk, timeout=600)
                except requests.RequestException as exc:
                    failures += 1
                    if failures > MAX_CHUNK_RETRIES:
                        raise RuntimeError(
                            f"SharePoint chunk upload failed after {MAX_CHUNK_RETRIES} retries at byte {start}"
                        ) from None
                    start = self._query_upload_start(upload_url, start)
                    delay = self._retry_delay(failures)
                    logger.warning(
                        "SharePoint chunk upload interrupted at byte %s (%s); retrying in %.1fs (%s/%s)",
                        start,
                        type(exc).__name__,
                        delay,
                        failures,
                        MAX_CHUNK_RETRIES,
                    )
                    time.sleep(delay)
                    continue

                if response.status_code in (200, 201):
                    start = size
                    break
                if response.status_code == 202:
                    next_start = self._next_expected_start(response.json(), end + 1)
                    if next_start > start:
                        failures = 0
                    else:
                        failures += 1
                        if failures > MAX_CHUNK_RETRIES:
                            raise RuntimeError(
                                f"SharePoint chunk upload failed after {MAX_CHUNK_RETRIES} retries at byte {start}"
                            ) from None
                    start = next_start
                    continue
                if response.status_code in RETRYABLE_UPLOAD_STATUS_CODES:
                    failures += 1
                    if failures > MAX_CHUNK_RETRIES:
                        raise RuntimeError(
                            f"SharePoint chunk upload failed after {MAX_CHUNK_RETRIES} retries at byte {start}"
                        ) from None
                    start = self._query_upload_start(upload_url, start)
                    delay = self._retry_delay(failures, response)
                    logger.warning(
                        "SharePoint chunk upload returned HTTP %s at byte %s; retrying in %.1fs (%s/%s)",
                        response.status_code,
                        start,
                        delay,
                        failures,
                        MAX_CHUNK_RETRIES,
                    )
                    time.sleep(delay)
                    continue
                raise RuntimeError(f"SharePoint chunk upload failed: HTTP {response.status_code}")
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
