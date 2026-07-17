#!/usr/bin/env python3
import argparse
import logging
import os
import shutil
import socket
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
from modules.rotation import rotate_local, rotate_sharepoint, rotate_gdrive, rotate_s3, rotate_mailru, rotate_logs
from modules.alerts import send_error_email, send_telegram_message
from modules.storage_sharepoint import SharePointClient, SharePointConfig
from modules.storage_gdrive import GoogleDriveClient, GoogleDriveConfig
from modules.storage_s3 import S3Client, S3Config
from modules.storage_mailru import MailRuClient, MailRuConfig

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


def send_alerts(alerts_cfg: dict, subject: str, body: str) -> None:
    """
    Fan out a notification to every enabled channel under the `alerts` config
    section (currently `email` and `telegram`). Add a new channel by adding
    another `if` block here reading its own sub-section.
    """
    email_cfg = alerts_cfg.get('email', {})
    if email_cfg.get('enabled', False):
        try:
            send_error_email(
                smtp_host=email_cfg.get('smtp_host', ''),
                smtp_port=int(email_cfg.get('smtp_port', 25)),
                use_tls=bool(email_cfg.get('use_tls', True)),
                username=email_cfg.get('username', ''),
                password=str(email_cfg.get('password', '')),
                from_email=email_cfg.get('from_email', ''),
                to_emails=list(email_cfg.get('to_emails', [])),
                subject=subject,
                body=body,
            )
        except Exception:
            logger.exception("Failed to send alert email")

    telegram_cfg = alerts_cfg.get('telegram', {})
    if telegram_cfg.get('enabled', False):
        try:
            send_telegram_message(
                bot_token=str(telegram_cfg.get('bot_token', '')),
                chat_id=str(telegram_cfg.get('chat_id', '')),
                text=f"{subject}\n\n{body}",
            )
        except Exception:
            logger.exception("Failed to send Telegram alert")


def run_backup(config_path: str, dry_run: bool, verbose: bool) -> int:
    cfg = load_config(config_path)

    log_cfg = cfg.get('logging', {})
    log_dir = log_cfg.get('dir', './logs')
    max_log_files = int(log_cfg.get('max_log_files', 30))
    setup_logging(log_dir, verbose=verbose)

    project_name = str(cfg.get('name') or os.path.splitext(os.path.basename(config_path))[0])
    hostname = socket.gethostname()

    logger.info("==== Backup started (%s @ %s) ====", project_name, hostname)

    # Extract config parts
    paths_cfg = cfg.get('paths', [])
    db = cfg.get('db', {})
    backup_cfg = cfg.get('backup', {})
    alerts_cfg = cfg.get('alerts', {})
    sp_cfg = cfg.get('sharepoint', {})
    gd_cfg = cfg.get('google_drive', {})
    s3_cfg = cfg.get('aws_s3', {})
    mailru_cfg = cfg.get('mailru', {})

    temp_dir_root = backup_cfg.get('temp_dir', '/tmp/backup')
    local_dir = backup_cfg.get('local_dir', './backups')
    max_archives = int(backup_cfg.get('max_archives', 14))

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    work_dir = os.path.join(temp_dir_root, f"work_{timestamp}")

    exit_code = 0
    archive_local_path = None
    local_saved_path = None
    sharepoint_uploaded_name = None
    gdrive_uploaded_name = None
    s3_uploaded_name = None
    mailru_uploaded_name = None

    try:
        # Prepare dirs
        ensure_dir(temp_dir_root)
        ensure_dir(local_dir)

        # Stage sources
        logger.info("Staging sources to %s", work_dir)
        ensure_dir(work_dir)
        paths_mod.stage_sources(
            temp_dir=work_dir,
            paths=paths_cfg,
            dry_run=dry_run,
        )

        # DB dump
        dump_dir = os.path.join(work_dir, 'database')
        db_type = db.get('type', 'mysql')
        logger.info("Creating %s database dump into %s", db_type, dump_dir)
        db_mod.dump_database(
            db_type=db_type,
            host=db.get('host', 'localhost'),
            port=int(db.get('port', 5432 if str(db_type).lower().startswith('post') else 3306)),
            db_name=db.get('name', ''),
            user=db.get('user', ''),
            password=str(db.get('password', '')),
            output_dir=dump_dir,
            dry_run=dry_run,
            docker_container=db.get('docker_container'),
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

        # Rotation for logs
        try:
            rotate_logs(log_dir, max_log_files=max_log_files, dry_run=dry_run)
        except Exception:
            logger.exception("Log rotation failed (will continue)")

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

        # Google Drive upload if enabled
        if gd_cfg.get('enabled', False):
            try:
                gd_cfg_obj = GoogleDriveConfig(
                    credentials_file=str(gd_cfg.get('credentials_file', '')),
                    folder_id=str(gd_cfg.get('folder_id', '')),
                )
                gd_client = GoogleDriveClient(gd_cfg_obj)
                gdrive_uploaded_name = gd_client.upload_file(local_saved_path, dry_run=dry_run)
                # Rotation for Google Drive
                try:
                    rotate_gdrive(gd_client, max_archives=max_archives, dry_run=dry_run)
                except Exception:
                    logger.exception("Google Drive rotation failed")
                    exit_code = 1
            except Exception:
                logger.exception("Google Drive upload failed")
                exit_code = 1
        else:
            logger.info("Google Drive upload disabled in config")

        # AWS S3 upload if enabled
        if s3_cfg.get('enabled', False):
            try:
                s3_cfg_obj = S3Config(
                    access_key_id=str(s3_cfg.get('access_key_id', '')),
                    secret_access_key=str(s3_cfg.get('secret_access_key', '')),
                    bucket=str(s3_cfg.get('bucket', '')),
                    region=str(s3_cfg.get('region', 'us-east-1')),
                    prefix=str(s3_cfg.get('prefix', '')),
                    endpoint_url=s3_cfg.get('endpoint_url') or None,
                )
                s3_client = S3Client(s3_cfg_obj)
                s3_uploaded_name = s3_client.upload_file(local_saved_path, dry_run=dry_run)
                try:
                    rotate_s3(s3_client, max_archives=max_archives, dry_run=dry_run)
                except Exception:
                    logger.exception("S3 rotation failed")
                    exit_code = 1
            except Exception:
                logger.exception("S3 upload failed")
                exit_code = 1
        else:
            logger.info("S3 upload disabled in config")

        # Mail.ru Cloud upload if enabled
        if mailru_cfg.get('enabled', False):
            try:
                mailru_cfg_obj = MailRuConfig(
                    username=str(mailru_cfg.get('username', '')),
                    password=str(mailru_cfg.get('password', '')),
                    remote_folder=str(mailru_cfg.get('remote_folder', '/backups')),
                    webdav_url=str(mailru_cfg.get('webdav_url', 'https://webdav.cloud.mail.ru')),
                )
                mailru_client = MailRuClient(mailru_cfg_obj)
                mailru_uploaded_name = mailru_client.upload_file(local_saved_path, dry_run=dry_run)
                try:
                    rotate_mailru(mailru_client, max_archives=max_archives, dry_run=dry_run)
                except Exception:
                    logger.exception("Mail.ru Cloud rotation failed")
                    exit_code = 1
            except Exception:
                logger.exception("Mail.ru Cloud upload failed")
                exit_code = 1
        else:
            logger.info("Mail.ru Cloud upload disabled in config")

        logger.info("==== Backup finished (%s @ %s) ====", project_name, hostname)
        # Send alert on partial failures as well
        if exit_code == 1:
            subject = f"[{project_name}] Backup FAILED (partial): {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            log_file_hint = os.path.join(log_dir, f"backup_{datetime.now().strftime('%Y-%m-%d')}.log")
            body = (
                "One or more non-fatal errors occurred during backup.\n\n"
                f"Project: {project_name}\n"
                f"Host: {hostname}\n"
                f"Config: {config_path}\n"
                f"Work dir: {work_dir}\n"
                f"Local archive (if any): {archive_local_path}\n"
                f"Local saved (if any): {local_saved_path}\n"
                f"SharePoint uploaded name (if any): {sharepoint_uploaded_name}\n"
                f"Google Drive uploaded name (if any): {gdrive_uploaded_name}\n"
                f"S3 uploaded key (if any): {s3_uploaded_name}\n"
                f"Mail.ru Cloud uploaded name (if any): {mailru_uploaded_name}\n\n"
                f"See log file: {log_file_hint}\n"
            )
            send_alerts(alerts_cfg, subject, body)
        return exit_code

    except Exception as e:
        logger.exception("Backup failed with an unhandled error")
        subject = f"[{project_name}] Backup FAILED: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        log_file_hint = os.path.join(log_dir, f"backup_{datetime.now().strftime('%Y-%m-%d')}.log")
        body = (
            "An error occurred during backup.\n\n"
            f"Project: {project_name}\n"
            f"Host: {hostname}\n"
            f"Config: {config_path}\n"
            f"Work dir: {work_dir}\n"
            f"Local archive (if any): {archive_local_path}\n"
            f"Local saved (if any): {local_saved_path}\n"
            f"SharePoint uploaded name (if any): {sharepoint_uploaded_name}\n"
            f"Google Drive uploaded name (if any): {gdrive_uploaded_name}\n"
            f"S3 uploaded key (if any): {s3_uploaded_name}\n"
            f"Mail.ru Cloud uploaded name (if any): {mailru_uploaded_name}\n\n"
            f"See log file: {log_file_hint}\n\n"
            f"Traceback:\n{traceback.format_exc()}"
        )
        send_alerts(alerts_cfg, subject, body)
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
    parser = argparse.ArgumentParser(description='Web application backup utility')
    parser.add_argument('--config', required=True, help='Path to config.yaml')
    parser.add_argument('--dry-run', action='store_true', help='Run without creating archive or uploading')
    parser.add_argument('--verbose', action='store_true', help='Enable DEBUG logging')
    args = parser.parse_args()

    code = run_backup(args.config, dry_run=args.dry_run, verbose=args.verbose)
    sys.exit(code)


if __name__ == '__main__':
    main()
