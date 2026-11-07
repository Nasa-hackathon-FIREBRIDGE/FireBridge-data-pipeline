#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
python3 scripts/init_server.py
sh scripts/stack.sh config --quiet
if [ "${FIREBRIDGE_SKIP_BUILD:-0}" != 1 ]; then
  sh scripts/stack.sh build airflow-scheduler
fi
# Stops only the legacy ingestion service. Database and stored files are preserved.
sh scripts/stack.sh stop worker
sh scripts/stack.sh up -d db airflow-db
sh scripts/stack.sh run --rm --no-deps airflow-permissions
sh scripts/stack.sh run --rm airflow-init
sh scripts/stack.sh run --rm --no-deps airflow-init python -m firebridge orchestrator airflow
sh scripts/stack.sh up -d airflow-api airflow-scheduler airflow-dag-processor
sh scripts/stack.sh ps
printf '\nStack started. New Dags are paused. Review the deployment guide before enabling provider downloads.\n'
