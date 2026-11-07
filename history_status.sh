#!/bin/sh
# Read-only local status. Does not start Docker, workflows or provider calls.
set -eu
cd "$(dirname "$0")"
exec python3 scripts/history_status.py
