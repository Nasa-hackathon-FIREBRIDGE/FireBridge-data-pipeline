#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
exec docker compose -f compose.yaml -f compose.airflow.yaml -f compose.local.yaml "$@"
