import logging
import os
import tarfile
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


def make_archive(temp_dir: str, output_dir: str, dry_run: bool = False) -> str:
    """
    Create tar.gz archive from temp_dir content.
    Archive name: mautic_backup_YYYYmmdd_HHMMSS.tar.gz
    Returns path to archive.
    """
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    archive_name = f"mautic_backup_{ts}.tar.gz"
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    archive_path = output_path / archive_name

    if dry_run:
        logger.info("[DRY-RUN] Would create archive %s from %s", archive_path, temp_dir)
        return str(archive_path)

    logger.info("Creating archive %s", archive_path)
    with tarfile.open(archive_path, mode='w:gz') as tar:
        tar.add(temp_dir, arcname=".")
    logger.info("Archive created at %s", archive_path)
    return str(archive_path)
