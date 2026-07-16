import gzip
import logging
import os
import subprocess
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


def _run_dump(cmd: List[str], dump_path: str, env: Optional[dict], tool_name: str) -> None:
    logger.debug("Command: %s", " ".join(cmd))
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    except FileNotFoundError:
        logger.exception("%s not found. Ensure it is installed and in PATH.", tool_name)
        raise

    with gzip.open(dump_path, "wb") as gz:
        while True:
            chunk = proc.stdout.read(1024 * 1024)  # 1 MB chunks
            if not chunk:
                break
            gz.write(chunk)

    proc.wait()
    if proc.returncode != 0:
        stderr = proc.stderr.read().decode(errors='ignore') if proc.stderr else ''
        logger.error("%s failed with code %s: %s", tool_name, proc.returncode, stderr)
        raise RuntimeError(f"{tool_name} failed: {stderr}")


def dump_mysql(host: str, port: int, db_name: str, user: str, password: str, output_dir: str, dry_run: bool = False) -> str:
    """
    Create a mysqldump of the given database into output_dir/db_dump.sql.gz
    The dump is compressed on the fly with gzip to save disk space.
    Returns the path to the dump file.
    """
    dump_path = str(Path(output_dir) / "db_dump.sql.gz")

    if dry_run:
        logger.info("[DRY-RUN] Would run mysqldump for DB '%s' on %s:%s -> %s", db_name, host, port, dump_path)
        return dump_path

    Path(output_dir).mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    # Use MYSQL_PWD to avoid showing password in process list
    if password:
        env["MYSQL_PWD"] = password

    cmd = [
        "mysqldump",
        # f"--host={host}",
        # f"--port={port}",
        f"--user={user}",
        "--single-transaction",
        "--quick",
        "--routines",
        db_name,
    ]

    logger.info("Running mysqldump (with on-the-fly gzip compression)...")
    _run_dump(cmd, dump_path, env, "mysqldump")
    logger.info("Database dump created at %s", dump_path)
    return dump_path


def dump_postgres(
    host: str,
    port: int,
    db_name: str,
    user: str,
    password: str,
    output_dir: str,
    dry_run: bool = False,
    docker_container: Optional[str] = None,
) -> str:
    """
    Create a pg_dump of the given database into output_dir/db_dump.sql.gz
    The dump is compressed on the fly with gzip to save disk space.

    If `docker_container` is set, pg_dump is executed inside that container
    via `docker exec` (useful when Postgres only runs inside a docker-compose
    network and isn't reachable/installed on the host). In that case host/port
    are ignored and pg_dump connects over the container's local socket.

    Returns the path to the dump file.
    """
    dump_path = str(Path(output_dir) / "db_dump.sql.gz")

    if dry_run:
        target = f"docker container '{docker_container}'" if docker_container else f"{host}:{port}"
        logger.info("[DRY-RUN] Would run pg_dump for DB '%s' on %s -> %s", db_name, target, dump_path)
        return dump_path

    Path(output_dir).mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    if password:
        env["PGPASSWORD"] = password

    if docker_container:
        cmd = [
            "docker", "exec",
            "-e", f"PGPASSWORD={password}",
            docker_container,
            "pg_dump",
            f"--username={user}",
            "--format=plain",
            db_name,
        ]
        tool_name = "docker exec pg_dump"
    else:
        cmd = [
            "pg_dump",
            f"--host={host}",
            f"--port={port}",
            f"--username={user}",
            "--format=plain",
            "--no-password",
            db_name,
        ]
        tool_name = "pg_dump"

    logger.info("Running pg_dump (with on-the-fly gzip compression)...")
    _run_dump(cmd, dump_path, env, tool_name)
    logger.info("Database dump created at %s", dump_path)
    return dump_path


def dump_database(db_type: str, host: str, port: int, db_name: str, user: str, password: str,
                   output_dir: str, dry_run: bool = False, docker_container: Optional[str] = None) -> str:
    """
    Dispatch to the dump function matching db_type ('mysql' or 'postgres'/'postgresql').
    """
    normalized = (db_type or "mysql").strip().lower()
    if normalized in ("postgres", "postgresql", "pg"):
        return dump_postgres(host, port, db_name, user, password, output_dir, dry_run=dry_run,
                              docker_container=docker_container)
    if normalized in ("mysql", "mariadb"):
        return dump_mysql(host, port, db_name, user, password, output_dir, dry_run=dry_run)
    raise ValueError(f"Unsupported db.type: {db_type!r} (expected 'mysql' or 'postgres')")
