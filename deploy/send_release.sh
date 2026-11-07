#!/bin/bash
# Runs in the protected GitHub deployment job. Secrets arrive only via its env.
set -euo pipefail
: "${DEPLOY_HOST:?}" "${DEPLOY_USER:?}" "${DEPLOY_SSH_KEY:?}" "${DEPLOY_KNOWN_HOSTS:?}" "${RELEASE_REVISION:?}" "${RELEASE_IMAGE:?}" "${SOURCE_BUNDLE:?}"
[[ "$RELEASE_REVISION" =~ ^[0-9a-f]{40}$ ]] || { echo 'Invalid release revision'; exit 1; }
[[ "$DEPLOY_HOST" =~ ^[a-zA-Z0-9.:-]+$ ]] || { echo 'Invalid deployment host'; exit 1; }
[[ "$DEPLOY_USER" == firebridge-deploy ]] || { echo 'Use the restricted deployment account'; exit 1; }
[[ "$RELEASE_IMAGE" =~ ^ghcr.io/nasa-hackathon-firebridge/firebridge-data-pipeline@sha256:[0-9a-f]{64}$ ]] || { echo 'Invalid release image'; exit 1; }
private_dir=$(mktemp -d)
trap 'rm -rf "$private_dir"' EXIT
chmod 700 "$private_dir"
printf '%s\n' "$DEPLOY_SSH_KEY" > "$private_dir/key"
printf '%s\n' "$DEPLOY_KNOWN_HOSTS" > "$private_dir/known_hosts"
chmod 600 "$private_dir/key" "$private_dir/known_hosts"
ssh_options=(-i "$private_dir/key" -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$private_dir/known_hosts" -o ServerAliveInterval=30 -o ServerAliveCountMax=4 -o ConnectTimeout=20)
target="$DEPLOY_USER@$DEPLOY_HOST"
ssh "${ssh_options[@]}" "$target" status
docker pull "$RELEASE_IMAGE"
docker tag "$RELEASE_IMAGE" "firebridge-airflow:$RELEASE_REVISION"
docker save "firebridge-airflow:$RELEASE_REVISION" | gzip -1 > "$private_dir/image.tar.gz"
image_hash=$(sha256sum "$private_dir/image.tar.gz" | cut -d ' ' -f1)
source_hash=$(sha256sum "$SOURCE_BUNDLE" | cut -d ' ' -f1)
ssh "${ssh_options[@]}" "$target" "source $RELEASE_REVISION $source_hash" < "$SOURCE_BUNDLE"
ssh "${ssh_options[@]}" "$target" "image $RELEASE_REVISION $image_hash" < "$private_dir/image.tar.gz"
ssh "${ssh_options[@]}" "$target" "activate $RELEASE_REVISION"
ssh "${ssh_options[@]}" "$target" status
