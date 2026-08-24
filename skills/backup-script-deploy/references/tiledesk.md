# Tiledesk Profile

## Approved zero-downtime scope

Back up:

- a full logical dump from the running `mongo` container so both `tiledesk` and
  `chat21` application databases are covered;
- `/opt/tiledesk` deployment configuration, excluding its backup directories;
- the active Tiledesk Nginx configuration;
- secret-free release/image identity metadata when it already exists.

Do not back up Qdrant, Redis, RabbitMQ, raw live volumes, Docker image layers,
PeerTube, or Kiwi. Do not stop, pause, restart, or recreate Tiledesk containers.

## Oracle production layout

Use the configured SSH profile `oracle-kiwi-peertube`. Re-inventory because
container names and paths may change. The expected baseline is:

| Purpose | Path/value |
|---|---|
| Installation | `/opt/tiledesk-backup` |
| Database container | `mongo` |
| Work root | `/mnt/storage/tiledesk-backups/.work` |
| Daily local | `/mnt/storage/tiledesk-backups/auto/daily` |
| Weekly local | `/mnt/storage/tiledesk-backups/auto/weekly` |
| Daily SharePoint | `/Tiledesk/auto/daily` |
| Weekly SharePoint | `/Tiledesk/auto/weekly` |
| Daily schedule | `03:00 UTC`, retain 7 |
| Weekly schedule | Sunday `04:00 UTC`, retain 4 |

Fail before writing if `/mnt/storage` is not the mounted secondary filesystem.
Do not place work archives under `/tmp` or `/opt`.

## Configuration rules

Use `db.type: mongodb`, `docker_container: mongo`, and an empty database name
for the full logical instance dump. Include MongoDB credentials only if the
running production instance actually enables authentication; obtain them from
the existing approved deployment configuration without printing them.

Use separate daily and weekly configs because local/remote directories and
retention differ. Both must point to the same application-scoped lock.

## Restore proof

Before the backup, capture collection/document counts for the `tiledesk` and
`chat21` databases without reading document bodies. Extract the inner MongoDB
archive from the outer backup into a unique bounded restore directory. Start a
disposable container from the current production Mongo image with no published
ports and a new labeled volume, then stream the payload into:

```text
mongorestore --archive --gzip --drop
```

Compare restored database names and per-collection document counts with the
source snapshot. Remove only resources carrying the unique restore marker.
Finally verify every production Tiledesk container stayed running with unchanged
restart counts and the public endpoint retained its baseline health.
