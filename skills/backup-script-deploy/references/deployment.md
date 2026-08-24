# Deployment Workflow

## 1. Inventory

Inspect without exposing configuration values:

- hostname, architecture, timezone, disk mounts, free space, and inode space;
- application and database containers/services, health, restart counts, image
  identities, bind mounts, and database dump tools;
- application configuration paths and their sizes;
- current cron entries/systemd timers, existing backup installations, and owned
  backup directories;
- destination availability and credential capability by key presence only;
- public and local application health to preserve as the baseline.

Estimate retention capacity from one real or representative dump. Do not count
Docker image layers as recurring application data.

## 2. Installation

Use an application-specific root such as `/opt/<app>-backup`:

```text
/opt/<app>-backup/
├── repo/       exact backup-script checkout
├── venv/       locked Python dependencies
├── config/     mode 0700; YAML files mode 0600
├── logs/       bounded application logs
└── run.sh      locked runner, no credentials
```

Put work and archives on the designated data disk. Fetch the repository, verify
the expected remote URL, and detach at the approved commit. Never deploy an
unpinned branch tip. Install `requirements.txt` into a private virtual
environment instead of the system Python.

The runner must:

- accept only explicit configured modes such as `daily` and `weekly`;
- verify the data mount with `findmnt --target <path>` before creating files;
- acquire `flock -n /run/lock/<app>-backup.lock`;
- invoke the pinned `backup.py` and propagate its exit code;
- contain no provider or database credential values.

## 3. Configuration

Every job has one database section. Supported `db.type` values are `mysql`,
`postgres`, and `mongodb` plus their documented aliases. For a containerized
database, set `docker_container` to the exact existing container name. For
MongoDB, an empty `name` creates a complete logical instance dump; set
`auth_database` when authentication requires it.

Include only application paths needed for recovery. Exclude the installation's
local archive, log, and work directories so archives cannot recursively include
themselves.

Use separate configs and destination folders when schedules have different
retention. Configure enabled remote providers and alert channels in each
mode-`0600` file. Reuse credentials only when the user authorizes the same
security principal for the new target; do not silently copy credentials from
another production system.

## 4. Scheduling

Prefer the scheduler already used on the host. For cron, edit idempotently:

- preserve every unrelated entry;
- identify owned lines by the exact application runner path;
- leave exactly one line per configured schedule;
- use the server timezone explicitly in the handoff.

Run `--dry-run` before installing the schedule. A dry-run validates routing but
does not prove dump, upload, or restore behavior.

## 5. Acceptance

Run one real backup manually. Verify:

1. archive and `.manifest.json` both exist locally;
2. manifest filename, byte size, and SHA-256 match the archive;
3. both artifacts are listed in the intended remote folder;
4. no archive payload appeared on the boot disk;
5. retention counts archives, not manifests;
6. logs contain no configured secret values;
7. application health and container restart counts did not regress.

Restore the database payload into an isolated disposable database using the
same major version as production. Publish no host port. Compare database,
table/collection, and row/document counts appropriate to the application. Use
a unique marker/label and delete only the disposable container, volume, and
bounded restore directory after evidence is captured.

## 6. Update and rollback

Before updating, record the current commit and retain its checkout/config.
Fetch the requested commit, run syntax/import and dry-run checks, then run a real
backup and restore drill. Roll back by detaching to the recorded commit; do not
change the database or remove last-known-good archives merely because an update
failed.

Record each completed production installation in the backup-script `README`
with project/domain, script location, destination paths, schedule, retention,
and enabled alert channels. Never record credentials.
