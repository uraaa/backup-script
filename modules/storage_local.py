import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


def save_to_local(archive_path: str, local_dir: str, dry_run: bool = False) -> str:
    """
    Copy archive into local_dir. Returns destination path.
    """
    src = Path(archive_path)
    dest_dir = Path(local_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name

    if dry_run:
        logger.info("[DRY-RUN] Would copy %s -> %s", src, dest)
        return str(dest)

    logger.info("Saving archive to local storage: %s", dest)
    shutil.copy2(src, dest)
    return str(dest)
