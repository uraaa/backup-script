import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def dump_mysql(host: str, port: int, db_name: str, user: str, password: str, output_dir: str, dry_run: bool = False) -> str:
    """
    Create a mysqldump of the given database into output_dir/db_dump.sql
    Returns the path to the dump file.
    """
    dump_path = str(Path(output_dir) / "db_dump.sql")

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

    logger.info("Running mysqldump...")
    logger.debug("Command: %s", " ".join(cmd))

    with open(dump_path, "wb") as f:
        try:
            proc = subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE, env=env, check=False)
        except FileNotFoundError:
            logger.exception("mysqldump not found. Ensure it is installed and in PATH.")
            raise
        if proc.returncode != 0:
            stderr = proc.stderr.decode(errors='ignore') if proc.stderr else ''
            logger.error("mysqldump failed with code %s: %s", proc.returncode, stderr)
            raise RuntimeError(f"mysqldump failed: {stderr}")

    logger.info("Database dump created at %s", dump_path)
    return dump_path
