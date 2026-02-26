import logging
import os
import re
from pathlib import Path
from typing import List, Tuple

logger = logging.getLogger(__name__)

ARCHIVE_RE = re.compile(r"^backup_\d{8}_\d{6}\.tar\.gz$")
LOG_RE = re.compile(r"^backup_\d{4}-\d{2}-\d{2}\.log$")


def _select_archives_local(directory: str) -> List[Tuple[str, float]]:
    p = Path(directory)
    if not p.exists():
        return []
    items: List[Tuple[str, float]] = []
    for entry in p.iterdir():
        if entry.is_file() and ARCHIVE_RE.match(entry.name):
            try:
                mtime = entry.stat().st_mtime
            except OSError:
                mtime = 0
            items.append((entry.name, mtime))
    # Sort newest first by mtime, fallback name
    items.sort(key=lambda x: (x[1], x[0]), reverse=True)
    return items


def rotate_local(directory: str, max_archives: int, dry_run: bool = False) -> None:
    archives = _select_archives_local(directory)
    if len(archives) <= max_archives:
        logger.info("Local rotation: nothing to delete (have %d, max %d)", len(archives), max_archives)
        return
    to_delete = archives[max_archives:]
    for name, _ in to_delete:
        path = Path(directory) / name
        if dry_run:
            logger.info("[DRY-RUN] Would delete local archive: %s", path)
        else:
            try:
                path.unlink()
                logger.info("Deleted local archive: %s", path)
            except Exception:
                logger.exception("Failed to delete local archive: %s", path)
                raise


def rotate_sharepoint(sp_client, max_archives: int, dry_run: bool = False) -> None:
    """
    Rotate files in SharePoint folder using client with list_files() -> List[(name,id)] and delete_file(id)
    Sorted by filename descending (timestamp embedded), keep newest max_archives.
    """
    files = sp_client.list_files()
    # Filter by pattern and sort by name desc (timestamp order)
    filtered = [(name, fid) for name, fid in files if ARCHIVE_RE.match(name)]
    filtered.sort(key=lambda x: x[0], reverse=True)
    if len(filtered) <= max_archives:
        logger.info("SharePoint rotation: nothing to delete (have %d, max %d)", len(filtered), max_archives)
        return
    for name, fid in filtered[max_archives:]:
        if dry_run:
            logger.info("[DRY-RUN] Would delete SharePoint archive: %s (id=%s)", name, fid)
        else:
            sp_client.delete_file(fid)
            logger.info("Deleted SharePoint archive: %s", name)


def rotate_gdrive(gd_client, max_archives: int, dry_run: bool = False) -> None:
    """
    Rotate files in Google Drive folder using client with list_files() -> List[(name,id)] and delete_file(id).
    Sorted by filename descending (timestamp embedded), keep newest max_archives.
    """
    files = gd_client.list_files()
    filtered = [(name, fid) for name, fid in files if ARCHIVE_RE.match(name)]
    filtered.sort(key=lambda x: x[0], reverse=True)
    if len(filtered) <= max_archives:
        logger.info("Google Drive rotation: nothing to delete (have %d, max %d)", len(filtered), max_archives)
        return
    for name, fid in filtered[max_archives:]:
        if dry_run:
            logger.info("[DRY-RUN] Would delete Google Drive archive: %s (id=%s)", name, fid)
        else:
            gd_client.delete_file(fid)
            logger.info("Deleted Google Drive archive: %s", name)


def rotate_logs(log_dir: str, max_log_files: int, dry_run: bool = False) -> None:
    """
    Rotate log files in log_dir, keeping only the newest max_log_files.
    Log files match pattern: backup_YYYY-MM-DD.log
    """
    p = Path(log_dir)
    if not p.exists():
        return
    logs: List[Tuple[str, float]] = []
    for entry in p.iterdir():
        if entry.is_file() and LOG_RE.match(entry.name):
            try:
                mtime = entry.stat().st_mtime
            except OSError:
                mtime = 0
            logs.append((entry.name, mtime))
    logs.sort(key=lambda x: (x[1], x[0]), reverse=True)
    if len(logs) <= max_log_files:
        logger.info("Log rotation: nothing to delete (have %d, max %d)", len(logs), max_log_files)
        return
    to_delete = logs[max_log_files:]
    for name, _ in to_delete:
        path = p / name
        if dry_run:
            logger.info("[DRY-RUN] Would delete old log file: %s", path)
        else:
            try:
                path.unlink()
                logger.info("Deleted old log file: %s", path)
            except Exception:
                logger.exception("Failed to delete old log file: %s", path)
