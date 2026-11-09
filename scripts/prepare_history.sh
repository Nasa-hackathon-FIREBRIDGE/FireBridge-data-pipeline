#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
exec sh scripts/stack.sh exec -T airflow-scheduler python /opt/firebridge/deploy/history_preparation.py
