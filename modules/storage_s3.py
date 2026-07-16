import logging
import os
from dataclasses import dataclass
from typing import List, Optional, Tuple

import boto3
from botocore.config import Config as BotoConfig

logger = logging.getLogger(__name__)


@dataclass
class S3Config:
    access_key_id: str
    secret_access_key: str
    bucket: str
    region: str = "us-east-1"
    prefix: str = ""  # key prefix, e.g. "backups"
    endpoint_url: Optional[str] = None  # for S3-compatible providers (e.g. VK Cloud, MinIO)


class S3Client:
    """
    Thin wrapper around boto3 S3 client. Works with AWS S3 and any
    S3-compatible endpoint when `endpoint_url` is set.
    """

    def __init__(self, cfg: S3Config):
        self.cfg = cfg
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = boto3.client(
                "s3",
                aws_access_key_id=self.cfg.access_key_id,
                aws_secret_access_key=self.cfg.secret_access_key,
                region_name=self.cfg.region,
                endpoint_url=self.cfg.endpoint_url or None,
                config=BotoConfig(retries={"max_attempts": 3, "mode": "standard"}),
            )
        return self._client

    def _prefix(self) -> str:
        p = (self.cfg.prefix or "").strip("/")
        return f"{p}/" if p else ""

    def _key(self, filename: str) -> str:
        return f"{self._prefix()}{filename}"

    def upload_file(self, local_file_path: str, dry_run: bool = False) -> str:
        filename = os.path.basename(local_file_path)
        key = self._key(filename)
        if dry_run:
            logger.info("[DRY-RUN] Would upload %s to s3://%s/%s", filename, self.cfg.bucket, key)
            return key
        self.client.upload_file(local_file_path, self.cfg.bucket, key)
        logger.info("Uploaded to S3: s3://%s/%s", self.cfg.bucket, key)
        return key

    def list_files(self) -> List[Tuple[str, str]]:
        """
        Returns list of (name, key) for objects under the configured prefix.
        """
        prefix = self._prefix()
        results: List[Tuple[str, str]] = []
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.cfg.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                name = key[len(prefix):] if prefix and key.startswith(prefix) else key
                if not name:
                    continue
                results.append((name, key))
        return results

    def delete_file(self, key: str) -> None:
        self.client.delete_object(Bucket=self.cfg.bucket, Key=key)
