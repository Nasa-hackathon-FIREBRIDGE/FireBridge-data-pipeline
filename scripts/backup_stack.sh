#!/bin/sh
set -eu
umask 077
cd "$(dirname "$0")/.."
# Immutable object mirror is shared by all dump dates: no repeated multi-GB full tarballs.
backup_root="${FIREBRIDGE_BACKUP_DIR:-$PWD/data/platform/backups/server}"
stamp=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$backup_root/dumps" "$backup_root/objects"
exec 9>"$backup_root/.backup.lock"
flock -n 9 || { echo 'Another backup is running.' >&2; exit 1; }
sh scripts/stack.sh exec -T db pg_dump -U firebridge -d firebridge -Fc > "$backup_root/dumps/$stamp-firebridge.dump.partial"
sh scripts/stack.sh exec -T airflow-db pg_dump -U airflow -d airflow -Fc > "$backup_root/dumps/$stamp-airflow.dump.partial"
data_root=data/platform
if [ "${FIREBRIDGE_STACK:-server}" = validation ]; then data_root=data/platform-validation; fi
# Copy AFTER dumps: immutable objects referenced by either snapshot must already exist.
# No --delete: older snapshots may still reference older objects.
if [ -d "$data_root/objects" ]; then rsync -a -- "$data_root/objects/" "$backup_root/objects/"; fi
mv "$backup_root/dumps/$stamp-firebridge.dump.partial" "$backup_root/dumps/$stamp-firebridge.dump"
mv "$backup_root/dumps/$stamp-airflow.dump.partial" "$backup_root/dumps/$stamp-airflow.dump"
(cd "$backup_root/dumps" && sha256sum "$stamp-firebridge.dump" "$stamp-airflow.dump" > "$stamp.sha256")
printf '%s\n' "$stamp" > "$backup_root/LATEST.partial"
mv "$backup_root/LATEST.partial" "$backup_root/LATEST"
printf 'Completed backup: %s (%s)\n' "$backup_root" "$stamp"
printf 'Copy the backup directory off this VPS. Preserve .env separately in encrypted storage.\n'
