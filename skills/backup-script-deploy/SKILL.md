---
name: backup-script-deploy
description: Deploy, configure, update, or verify uraaa/backup-script on Linux hosts, including database dumps, remote storage, retention, scheduling, alerts, and restore drills. Use for application backup installations; do not use for filesystem-only copy requests.
---

# Backup Script Deploy

Deploy a recoverable backup installation, not merely a scheduled archive job.

## Route

1. Read [references/deployment.md](references/deployment.md) for every task.
2. When the target is Tiledesk, also read
   [references/tiledesk.md](references/tiledesk.md).

## Required outcome

- Inventory the real application, database, storage, existing schedules, and
  baseline health before mutation.
- Pin the installation to an exact Git commit from
  `https://github.com/uraaa/backup-script`.
- Keep each application in its own installation, configuration, log, lock, work,
  and archive paths.
- Keep credentials only in the deployed configuration with mode `0600`. Never
  print them or place them in Git, manifests, evidence, commands shown to the
  user, or documentation.
- Put work and archives on the intended data disk and fail closed when that disk
  is not mounted.
- Prevent concurrent runs with an application-specific non-blocking lock.
- Treat the archive and its `.manifest.json` checksum sidecar as one artifact.
- Verify one real local backup, one remote upload/listing, and one disposable
  restore before calling the installation complete.
- Record the deployed commit, paths, schedule, retention, destination, alert
  channels, restore result, and post-install application health without secrets.

Do not stop services, copy live raw database volumes, restore into production,
delete existing backups, or change unrelated schedules unless the user has
explicitly authorized that operation. A zero exit code or upload response alone
is not proof that the backup can be restored.
