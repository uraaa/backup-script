import logging
import os
import shutil
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


def _copy_path(src: str, dest_dir: str, exclude: Optional[List[str]] = None) -> None:
    src_path = Path(src)
    if not src_path.exists():
        logger.warning("Path does not exist and will be skipped: %s", src)
        return

    dest_dir_path = Path(dest_dir)

    if src_path.is_dir():
        target = dest_dir_path / src_path.name
        logger.debug("Copying directory %s -> %s", src_path, target)
        if target.exists():
            shutil.rmtree(target)

        ignore_func = None
        if exclude:
            ignore_func = shutil.ignore_patterns(*exclude)

        shutil.copytree(src_path, target, symlinks=True, dirs_exist_ok=False, ignore=ignore_func)
    else:
        target = dest_dir_path / src_path.name
        logger.debug("Copying file %s -> %s", src_path, target)
        dest_dir_path.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_path, target)


def stage_sources(temp_dir: str, paths: List[dict], dry_run: bool = False) -> None:
    """
    Collect all requested sources into the temporary staging directory.

    Each entry in `paths` is a dict:
      - path: str — source file or directory
      - exclude: list[str] (optional) — patterns to exclude (for directories)

    Structure inside temp_dir:
      temp_dir/
        files/
          <basename1>/
          <basename2>
          ...
    """
    base = Path(temp_dir)
    files_dir = base / "files"
    files_dir.mkdir(parents=True, exist_ok=True)

    if dry_run:
        for entry in paths:
            p = entry if isinstance(entry, str) else entry.get('path', '')
            exclude = [] if isinstance(entry, str) else entry.get('exclude', [])
            logger.info("[DRY-RUN] Would stage path: %s (exclude: %s)", p, exclude)
        return

    for entry in paths:
        if isinstance(entry, str):
            p = entry
            exclude = []
        else:
            p = entry.get('path', '')
            exclude = entry.get('exclude', [])

        if not p:
            continue
        _copy_path(p, str(files_dir), exclude=exclude or None)

    logger.info("Staging complete in %s", temp_dir)
