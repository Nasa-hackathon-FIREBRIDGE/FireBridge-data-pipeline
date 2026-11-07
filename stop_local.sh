#!/bin/sh
set -eu
cd "$(dirname "$0")"
sh scripts/local_stack.sh stop
printf 'FIREBRIDGE stopped. Databases, downloaded files and published results are preserved.\n'
