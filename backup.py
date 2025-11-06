#!/usr/bin/env python3
import argparse
import logging
import os
import shutil
import sys
import traceback
from datetime import datetime
from pathlib import Path

import yaml

from modules.logging_setup import setup_logging
from modules import paths as paths_mod
from modules import db as db_mod
from modules.archiver import make_archive
from modules.storage_local import save_to_local
from modules.rotation import rotate_local, rotate_sharepoint
from modules.alerts import send_error_email
from modules.storage_sharepoint import SharePointClient, SharePointConfig

import os

if os.getenv("PYCHARM_DEBUG", "0") == "1":
    import pydevd_pycharm
    pydevd_pycharm.settrace(
        '188.134.21.52',  # IP твоего компа, который видит сервер
        port=5678,
        suspend=True
    )

logger = logging.getLogger(__name__)


def load_config(path: str) -> dict:
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f) or {}


def ensure_dir(p: str):
    Path(p).mkdir(parents=True, exist_ok=True)


def run_backup(config_path: str, dry_run: bool, verbose: bool) -> int:
    cfg = load_config(config_path)

    log_dir = cfg.get('logging', {}).get('dir', './logs')
    setup_logging(log_dir, verbose=verbose)

    logger.info("==== Mautic backup started ====")

    # Extract config parts
    mautic = cfg.get('mautic', {})
    nginx = cfg.get('nginx', {})
    db = cfg.get('db', {})
    backup_cfg = cfg.get('backup', {})
    alerts_cfg = cfg.get('alerts', {})
    sp_cfg = cfg.get('sharepoint', {})

    temp_dir_root = backup_cfg.get('temp_dir', '/tmp/mautic-backup')
    local_dir = backup_cfg.get('local_dir', './backups')
    max_archives = int(backup_cfg.get('max_archives', 14))

    code_paths = mautic.get('code_paths', [])
    assets_paths = mautic.get('assets_paths', [])
    config_paths = mautic.get('config_paths', [])
    nginx_paths = nginx.get('paths', [])

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    work_dir = os.path.join(temp_dir_root, f"work_{timestamp}")

    exit_code = 0
    archive_local_path = None
    local_saved_path = None
    sharepoint_uploaded_name = None

    try:
        # Prepare dirs
        ensure_dir(temp_dir_root)
        ensure_dir(local_dir)

        # Stage sources
        logger.info("Staging sources to %s", work_dir)
        ensure_dir(work_dir)
        paths_mod.stage_sources(
            temp_dir=work_dir,
            code_paths=code_paths,
            assets_paths=assets_paths,
            config_paths=config_paths,
            nginx_paths=nginx_paths,
            dry_run=dry_run,
        )

        # DB dump
        dump_dir = os.path.join(work_dir, 'database')
        logger.info("Creating database dump into %s", dump_dir)
        db_mod.dump_mysql(
            host=db.get('host', 'localhost'),
            port=int(db.get('port', 3306)),
            db_name=db.get('name', ''),
            user=db.get('user', ''),
            password=str(db.get('password', '')),
            output_dir=dump_dir,
            dry_run=dry_run,
        )

        # Archive
        archive_output_dir = temp_dir_root  # create an archive next to work dir, then copy to local storage
        archive_local_path = make_archive(work_dir, archive_output_dir, dry_run=dry_run)

        # Save to local storage
        local_saved_path = save_to_local(archive_local_path, local_dir, dry_run=dry_run)

        # Remove the temporary archive from temp_dir_root after copying to local to save space
        try:
            if not dry_run and archive_local_path and os.path.isfile(archive_local_path):
                os.remove(archive_local_path)
                logger.debug("Removed temporary archive %s", archive_local_path)
        except Exception:
            logger.warning("Failed to remove temporary archive %s", archive_local_path, exc_info=True)

        # Rotation for local
        try:
            rotate_local(local_dir, max_archives=max_archives, dry_run=dry_run)
        except Exception:
            logger.exception("Local rotation failed (will continue but mark as error)")
            exit_code = 1

        # SharePoint upload if enabled
        if sp_cfg.get('enabled', False):
            try:
                cfg_obj = SharePointConfig(
                    tenant_id=str(sp_cfg.get('tenant_id', '')),
                    client_id=str(sp_cfg.get('client_id', '')),
                    client_secret=str(sp_cfg.get('client_secret', '')),
                    site_id=str(sp_cfg.get('site_id', '')),
                    drive_id=str(sp_cfg.get('drive_id', '')),
                    folder_path=str(sp_cfg.get('folder_path', '/')),
                )
                sp_client = SharePointClient(cfg_obj)
                sharepoint_uploaded_name = sp_client.upload_file(local_saved_path, dry_run=dry_run)
                # Rotation for SharePoint
                try:
                    rotate_sharepoint(sp_client, max_archives=max_archives, dry_run=dry_run)
                except Exception:
                    logger.exception("SharePoint rotation failed")
                    exit_code = 1
            except Exception:
                logger.exception("SharePoint upload failed")
                exit_code = 1
        else:
            logger.info("SharePoint upload disabled in config")

        logger.info("==== Mautic backup finished ====")
        # Send alert on partial failures as well
        try:
            if exit_code == 1 and alerts_cfg.get('enabled', False):
                subject = f"Mautic backup FAILED (partial): {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                log_file_hint = os.path.join(log_dir, f"backup_{datetime.now().strftime('%Y-%m-%d')}.log")
                body = (
                    "One or more non-fatal errors occurred during Mautic backup.\n\n"
                    f"Config: {config_path}\n"
                    f"Work dir: {work_dir}\n"
                    f"Local archive (if any): {archive_local_path}\n"
                    f"Local saved (if any): {local_saved_path}\n"
                    f"SharePoint uploaded name (if any): {sharepoint_uploaded_name}\n\n"
                    f"See log file: {log_file_hint}\n"
                )
                send_error_email(
                    smtp_host=alerts_cfg.get('smtp_host', ''),
                    smtp_port=int(alerts_cfg.get('smtp_port', 25)),
                    use_tls=bool(alerts_cfg.get('use_tls', True)),
                    username=alerts_cfg.get('username', ''),
                    password=str(alerts_cfg.get('password', '')),
                    from_email=alerts_cfg.get('from_email', ''),
                    to_emails=list(alerts_cfg.get('to_emails', [])),
                    subject=subject,
                    body=body,
                )
        except Exception:
            logger.exception("Failed to send partial-failure alert email")
        return exit_code

    except Exception as e:
        logger.exception("Backup failed with an unhandled error")
        try:
            if alerts_cfg.get('enabled', False):
                subject = f"Mautic backup FAILED: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                log_file_hint = os.path.join(log_dir, f"backup_{datetime.now().strftime('%Y-%m-%d')}.log")
                body = (
                    "An error occurred during Mautic backup.\n\n"
                    f"Config: {config_path}\n"
                    f"Work dir: {work_dir}\n"
                    f"Local archive (if any): {archive_local_path}\n"
                    f"Local saved (if any): {local_saved_path}\n"
                    f"SharePoint uploaded name (if any): {sharepoint_uploaded_name}\n\n"
                    f"See log file: {log_file_hint}\n\n"
                    f"Traceback:\n{traceback.format_exc()}"
                )
                send_error_email(
                    smtp_host=alerts_cfg.get('smtp_host', ''),
                    smtp_port=int(alerts_cfg.get('smtp_port', 25)),
                    use_tls=bool(alerts_cfg.get('use_tls', True)),
                    username=alerts_cfg.get('username', ''),
                    password=str(alerts_cfg.get('password', '')),
                    from_email=alerts_cfg.get('from_email', ''),
                    to_emails=list(alerts_cfg.get('to_emails', [])),
                    subject=subject,
                    body=body,
                )
        except Exception:
            logger.exception("Failed to send alert email")
        return 1
    finally:
        # Cleanup working directory if not dry-run
        try:
            if not dry_run and work_dir and os.path.isdir(work_dir):
                shutil.rmtree(work_dir, ignore_errors=False)
                logger.debug("Cleaned up work dir %s", work_dir)
        except Exception:
            logger.warning("Failed to cleanup work dir %s", work_dir, exc_info=True)


def main():
    parser = argparse.ArgumentParser(description='Mautic backup utility')
    parser.add_argument('--config', required=True, help='Path to config.yaml')
    parser.add_argument('--dry-run', action='store_true', help='Run without creating archive or uploading')
    parser.add_argument('--verbose', action='store_true', help='Enable DEBUG logging')
    args = parser.parse_args()

    code = run_backup(args.config, dry_run=args.dry_run, verbose=args.verbose)
    sys.exit(code)


if __name__ == '__main__':
    main()
