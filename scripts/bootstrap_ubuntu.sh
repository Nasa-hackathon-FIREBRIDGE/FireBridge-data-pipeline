#!/bin/sh
# Run deliberately on the target Ubuntu 24.04/26.04 server as root, not on a laptop.
set -eu
if [ "$(id -u)" -ne 0 ]; then echo 'Run with sudo on the target VPS.' >&2; exit 1; fi
. /etc/os-release
if [ "$ID" != ubuntu ]; then echo 'This bootstrap supports Ubuntu only.' >&2; exit 1; fi
apt-get update
apt-get install -y ca-certificates curl python3 rsync
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
arch=$(dpkg --print-architecture)
cat > /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: ${UBUNTU_CODENAME:-$VERSION_CODENAME}
Components: stable
Architectures: $arch
Signed-By: /etc/apt/keyrings/docker.asc
EOF
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
docker compose version
