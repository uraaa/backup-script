import fnmatch
import logging
import os
import shutil
from pathlib import Path
from typing import List, Optional

import pathspec

logger = logging.getLogger(__name__)

# Directories that are never part of "project code" and are always skipped
# when staging a directory, regardless of .gitignore content.
ALWAYS_SKIP_DIRS = {".git"}


def _load_gitignore_spec(directory: Path) -> Optional[pathspec.PathSpec]:
    gitignore_file = directory / ".gitignore"
    if not gitignore_file.is_file():
        return None
    try:
        lines = gitignore_file.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        logger.warning("Failed to read .gitignore at %s", gitignore_file, exc_info=True)
        return None
    return pathspec.PathSpec.from_lines("gitwildmatch", lines)


def _is_ignored(rel_path: Path, is_dir: bool, spec: Optional[pathspec.PathSpec],
                exclude_patterns: List[str]) -> bool:
    rel_posix = rel_path.as_posix()
    if spec is not None:
        check_path = rel_posix + "/" if is_dir else rel_posix
        if spec.match_file(check_path):
            return True
    if exclude_patterns:
        name = rel_path.name
        for pattern in exclude_patterns:
            if fnmatch.fnmatch(name, pattern):
                return True
    return False


def _copy_directory(src_root: Path, dest_root: Path, spec: Optional[pathspec.PathSpec],
                     exclude_patterns: List[str]) -> None:
    dest_root.mkdir(parents=True, exist_ok=True)
    for dirpath, dirnames, filenames in os.walk(src_root, followlinks=False):
        cur_dir = Path(dirpath)
        rel_dir = cur_dir.relative_to(src_root)

        kept_dirnames = []
        for d in dirnames:
            if d in ALWAYS_SKIP_DIRS:
                continue
            rel_path = rel_dir / d
            if _is_ignored(rel_path, True, spec, exclude_patterns):
                continue
            kept_dirnames.append(d)
        dirnames[:] = kept_dirnames

        target_dir = dest_root / rel_dir
        target_dir.mkdir(parents=True, exist_ok=True)

        for f in filenames:
            rel_path = rel_dir / f
            if _is_ignored(rel_path, False, spec, exclude_patterns):
                continue
            src_file = cur_dir / f
            dest_file = target_dir / f
            if src_file.is_symlink():
                os.symlink(os.readlink(src_file), dest_file)
            else:
                shutil.copy2(src_file, dest_file)


def _copy_path(src: str, dest_dir: str, exclude: Optional[List[str]] = None,
               use_gitignore: bool = True) -> None:
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

        spec = _load_gitignore_spec(src_path) if use_gitignore else None
        if spec is not None:
            logger.debug("Using .gitignore rules found in %s", src_path)

        _copy_directory(src_path, target, spec, exclude or [])
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
      - exclude: list[str] (optional) — extra filename patterns to exclude,
        on top of .gitignore
      - gitignore: bool (optional, default true) — if the path is a directory
        and contains a .gitignore file, its rules are applied automatically;
        set to false to disable this and rely only on `exclude`

    A plain string entry is equivalent to {path: <string>}.

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
            use_gitignore = True if isinstance(entry, str) else bool(entry.get('gitignore', True))
            logger.info("[DRY-RUN] Would stage path: %s (exclude: %s, gitignore: %s)", p, exclude, use_gitignore)
        return

    for entry in paths:
        if isinstance(entry, str):
            p = entry
            exclude = []
            use_gitignore = True
        else:
            p = entry.get('path', '')
            exclude = entry.get('exclude', [])
            use_gitignore = bool(entry.get('gitignore', True))

        if not p:
            continue
        _copy_path(p, str(files_dir), exclude=exclude or None, use_gitignore=use_gitignore)

    logger.info("Staging complete in %s", temp_dir)
