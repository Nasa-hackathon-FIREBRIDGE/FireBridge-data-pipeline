#!/bin/sh
# One command: local data services plus an explicitly launched full-history download.
set -eu
cd "$(dirname "$0")"
download_option=''
for argument in "$@"; do
    if [ "$argument" = '--skip-download' ]; then download_option='--skip-download'; fi
done
command -v docker >/dev/null || { echo 'Install Docker Engine and its Compose plugin first.' >&2; exit 1; }
docker info >/dev/null 2>&1 || { echo 'Start Docker and ensure your account has Docker access.' >&2; exit 1; }
python3 scripts/init_local_run.py "$@"
sh scripts/local_stack.sh config --quiet
sh scripts/local_stack.sh build airflow-scheduler
sh scripts/local_stack.sh stop worker
sh scripts/local_stack.sh up -d --wait db airflow-db
sh scripts/local_stack.sh run --rm --no-deps airflow-permissions
sh scripts/local_stack.sh run --rm airflow-init
sh scripts/local_stack.sh run --rm --no-deps airflow-init python -c '
from firebridge.config import Settings
from firebridge.db import connect
from firebridge.orchestration import set_owner
s=Settings.load()
with connect(s) as c: owner=c.execute("SELECT owner FROM orchestration_control WHERE singleton").fetchone()["owner"]
if owner != "airflow": set_owner(s,"airflow")
print("Ingestion owner: airflow")'
sh scripts/local_stack.sh up -d --wait airflow-api airflow-scheduler airflow-dag-processor postgres-browser
sh scripts/local_stack.sh exec -T airflow-scheduler python /opt/firebridge/deploy/check_dags.py
if [ -n "$download_option" ]; then
    sh scripts/local_stack.sh exec -T airflow-scheduler python /opt/firebridge/deploy/start_local_workflows.py --skip-download
else
    sh scripts/local_stack.sh exec -T airflow-scheduler python /opt/firebridge/deploy/start_local_workflows.py
fi
# Refresh a previous browser process so it attaches to the newly published catalog.
sh scripts/local_stack.sh up -d --force-recreate archive-browser
python3 scripts/check_local_urls.py
printf '\nFIREBRIDGE is running locally.\n'
printf 'All archive rows (DuckDB): http://localhost:4213\n'
printf 'Published PostgreSQL data: http://localhost:8082\n'
printf 'Airflow workflows: http://localhost:8080\n'
printf 'Airflow login: AIRFLOW_ADMIN_USER / AIRFLOW_ADMIN_PASSWORD in your private .env\n'
printf 'Guide: docs/data/LOCAL_RUN.md\n'
if [ -z "$download_option" ]; then
    printf 'Full-history download continues in Airflow: firebridge_full_history_download\n'
    printf 'Progress: ./history_status.sh\n'
fi
