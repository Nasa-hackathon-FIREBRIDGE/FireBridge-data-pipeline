#!/bin/sh
set -eu
# Run from the project root. Does not display credentials or remove old backups.
mkdir -p data/platform/backups
backup_path="data/platform/backups/firebridge-$(date -u +%Y%m%dT%H%M%SZ).dump"
docker compose exec -T db pg_dump -U firebridge -d firebridge -Fc > "$backup_path.partial"
mv "$backup_path.partial" "$backup_path"
printf 'Database backup saved: %s\n' "$backup_path"
