import logging
import os
from dataclasses import dataclass
from typing import List, Optional, Tuple
from urllib.parse import quote, urlsplit
from xml.etree import ElementTree as ET

import requests

logger = logging.getLogger(__name__)

_DAV_NS = {"d": "DAV:"}


@dataclass
class MailRuConfig:
    username: str  # full mail.ru/bk.ru/inbox.ru email
    password: str  # app password, created in Cloud Mail.ru -> "Пароли для внешних приложений"
    remote_folder: str = "/backups"  # target folder path inside the cloud
    webdav_url: str = "https://webdav.cloud.mail.ru"


class MailRuClient:
    """
    Client for cloud.mail.ru over its WebDAV interface (webdav.cloud.mail.ru).
    Requires an app password (not the regular account password).
    """

    def __init__(self, cfg: MailRuConfig, session: Optional[requests.Session] = None):
        self.cfg = cfg
        self.session = session or requests.Session()
        self.session.auth = (cfg.username, cfg.password)
        self._folder_ready = False

    def _folder_path(self) -> str:
        return "/" + self.cfg.remote_folder.strip("/")

    def _folder_url(self) -> str:
        path = self._folder_path().strip("/")
        base = self.cfg.webdav_url.rstrip("/")
        return f"{base}/{quote(path)}" if path else base

    def _file_url(self, filename: str) -> str:
        return f"{self._folder_url()}/{quote(filename)}"

    def _ensure_folder(self) -> None:
        if self._folder_ready:
            return
        resp = self.session.request("MKCOL", self._folder_url(), timeout=60)
        # 201 = created, 405 = already exists
        if resp.status_code not in (201, 405):
            logger.error("Failed to create Mail.ru Cloud folder %s: %s %s",
                         self.cfg.remote_folder, resp.status_code, resp.text)
            raise RuntimeError(f"Mail.ru MKCOL failed: {resp.status_code} {resp.text}")
        self._folder_ready = True

    def upload_file(self, local_file_path: str, dry_run: bool = False) -> str:
        filename = os.path.basename(local_file_path)
        if dry_run:
            logger.info("[DRY-RUN] Would upload %s to Mail.ru Cloud folder %s", filename, self.cfg.remote_folder)
            return filename
        self._ensure_folder()
        with open(local_file_path, "rb") as f:
            resp = self.session.put(self._file_url(filename), data=f, timeout=600)
        if resp.status_code not in (200, 201, 204):
            logger.error("Mail.ru Cloud upload failed: %s %s", resp.status_code, resp.text)
            raise RuntimeError(f"Mail.ru Cloud upload failed: {resp.status_code} {resp.text}")
        logger.info("Uploaded to Mail.ru Cloud: %s", filename)
        return filename

    def list_files(self) -> List[Tuple[str, str]]:
        """
        Returns list of (name, href) for files in the configured folder.
        """
        self._ensure_folder()
        headers = {"Depth": "1", "Content-Type": "application/xml; charset=utf-8"}
        body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<d:propfind xmlns:d="DAV:"><d:prop><d:displayname/><d:resourcetype/></d:prop></d:propfind>'
        )
        resp = self.session.request("PROPFIND", self._folder_url(), headers=headers, data=body, timeout=60)
        if resp.status_code != 207:
            logger.error("Failed to list Mail.ru Cloud folder %s: %s %s",
                         self.cfg.remote_folder, resp.status_code, resp.text)
            raise RuntimeError(f"Mail.ru PROPFIND failed: {resp.status_code} {resp.text}")

        root = ET.fromstring(resp.content)
        folder_path = self._folder_path().rstrip("/")
        files: List[Tuple[str, str]] = []
        for response in root.findall("d:response", _DAV_NS):
            href = response.findtext("d:href", default="", namespaces=_DAV_NS)
            href_path = urlsplit(href).path.rstrip("/")
            if not href_path or href_path == folder_path:
                continue  # skip the folder's own entry
            is_collection = response.find(".//d:resourcetype/d:collection", _DAV_NS) is not None
            if is_collection:
                continue
            name = os.path.basename(href_path)
            from urllib.parse import unquote
            files.append((unquote(name), href))
        return files

    def delete_file(self, href: str) -> None:
        url = href if href.startswith("http") else f"{self.cfg.webdav_url.rstrip('/')}{href}"
        resp = self.session.delete(url, timeout=60)
        if resp.status_code not in (200, 204, 404):
            logger.error("Failed to delete Mail.ru Cloud file %s: %s %s", href, resp.status_code, resp.text)
            raise RuntimeError(f"Mail.ru delete failed: {resp.status_code} {resp.text}")
