#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
# Runs independently of Airflow, so a stopped scheduler cannot hide its own failure.
sh scripts/stack.sh ps --format json | python3 -c '
import json,sys
payload=sys.stdin.read()
try:
    rows=json.loads(payload)
    if isinstance(rows,dict):rows=[rows]
except json.JSONDecodeError:
    rows=[json.loads(line) for line in payload.splitlines() if line.strip()]
required={"db","airflow-db","airflow-api","airflow-scheduler","airflow-dag-processor"}
healthy={r["Service"] for r in rows if r["State"]=="running" and r.get("Health")=="healthy"}
missing=sorted(required-healthy)
print(json.dumps({"unhealthy_services":missing}))
sys.exit(bool(missing))'
sh scripts/stack.sh exec -T airflow-scheduler firebridge health
