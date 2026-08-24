import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path


def _sha256_and_size(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def verify_manifest(manifest_path: str, archive_path: str) -> None:
    manifest = Path(manifest_path)
    archive = Path(archive_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    archive_meta = payload.get("archive", {})
    digest, size = _sha256_and_size(archive)

    if payload.get("schema_version") != 1:
        raise ValueError("Unsupported manifest schema version")
    if archive_meta.get("filename") != archive.name:
        raise ValueError("Manifest archive filename does not match")
    if archive_meta.get("size_bytes") != size:
        raise ValueError("Manifest archive size does not match")
    if archive_meta.get("sha256") != digest:
        raise ValueError("Manifest archive SHA-256 does not match")


def create_manifest(archive_path: str, project_name: str, hostname: str) -> str:
    archive = Path(archive_path)
    if not archive.is_file() or archive.stat().st_size == 0:
        raise ValueError(f"Archive is missing or empty: {archive}")

    digest, size = _sha256_and_size(archive)
    manifest = Path(f"{archive}.manifest.json")
    temporary = manifest.with_name(f".{manifest.name}.tmp-{os.getpid()}")
    payload = {
        "schema_version": 1,
        "project": project_name,
        "hostname": hostname,
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "archive": {
            "filename": archive.name,
            "size_bytes": size,
            "sha256": digest,
        },
    }

    try:
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, manifest)
    finally:
        temporary.unlink(missing_ok=True)

    verify_manifest(str(manifest), str(archive))
    return str(manifest)
