#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
if [ "${FIREBRIDGE_STACK:-server}" = validation ]; then
  exec docker compose -p firebridge-validation -f compose.yaml -f compose.airflow.yaml -f deploy/compose.validation.yaml "$@"
fi
if [ -f deploy/server-profile ]; then
  server_profile=$(cat deploy/server-profile)
  case "$server_profile" in
    contabo-plus-6)
      if [ -f deploy/release-image ]; then
        FIREBRIDGE_RELEASE_IMAGE=$(cat deploy/release-image)
        export FIREBRIDGE_RELEASE_IMAGE
        exec docker compose -f compose.yaml -f compose.airflow.yaml -f compose.contabo.yaml -f compose.release.yaml "$@"
      fi
      exec docker compose -f compose.yaml -f compose.airflow.yaml -f compose.contabo.yaml "$@"
      ;;
    *) echo 'Unknown deploy/server-profile. Expected contabo-plus-6.' >&2; exit 1 ;;
  esac
fi
exec docker compose -f compose.yaml -f compose.airflow.yaml "$@"
