import logging
import os
import shutil
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)


def _copy_path(src: str, dest_dir: str) -> None:
    src_path = Path(src)
    if not src_path.exists():
        logger.warning("Path does not exist and will be skipped: %s", src)
        return

    dest_dir_path = Path(dest_dir)

    if src_path.is_dir():
        # Copy directory contents into a subfolder named by directory basename
        target = dest_dir_path / src_path.name
        logger.debug("Copying directory %s -> %s", src_path, target)
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(src_path, target, symlinks=True, dirs_exist_ok=False)
    else:
        # Copy single file into dest_dir keeping filename
        target = dest_dir_path / src_path.name
        logger.debug("Copying file %s -> %s", src_path, target)
        dest_dir_path.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_path, target)


def stage_sources(temp_dir: str, code_paths: Iterable[str], assets_paths: Iterable[str],
                  config_paths: Iterable[str], nginx_paths: Iterable[str], dry_run: bool = False) -> None:
    """
    Collect all requested sources into the temporary staging directory.
    Structure inside temp_dir:
      temp_dir/
        code/
        assets/
        mautic_configs/
        nginx/
    """
    base = Path(temp_dir)
    (base / "code").mkdir(parents=True, exist_ok=True)
    (base / "assets").mkdir(parents=True, exist_ok=True)
    (base / "mautic_configs").mkdir(parents=True, exist_ok=True)
    (base / "nginx").mkdir(parents=True, exist_ok=True)

    if dry_run:
        logger.info("[DRY-RUN] Would stage code paths: %s", list(code_paths))
        logger.info("[DRY-RUN] Would stage assets paths: %s", list(assets_paths))
        logger.info("[DRY-RUN] Would stage Mautic configs: %s", list(config_paths))
        logger.info("[DRY-RUN] Would stage Nginx paths: %s", list(nginx_paths))
        return

    for p in code_paths:
        _copy_path(p, str(base / "code"))
    for p in assets_paths:
        _copy_path(p, str(base / "assets"))
    for p in config_paths:
        _copy_path(p, str(base / "mautic_configs"))
    for p in nginx_paths:
        _copy_path(p, str(base / "nginx"))

    logger.info("Staging complete in %s", temp_dir)
