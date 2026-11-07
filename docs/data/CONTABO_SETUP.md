# Contabo server: security first, then FIREBRIDGE

This replaces the earlier Hetzner sizing assumption for this deployment. Contabo currently lists **Cloud VPS Plus 6: 6 vCPUs, 12 GB RAM, 300 GB NVMe**. Verify the purchased instance with its control-panel inventory and the OS audit before applying resource settings. [Official product specifications](https://docs.contabo.com/docs/servers-hosting/vps/).

The server is fresh, with nothing hosted. **Verified on November 6, 2026:** Ubuntu updates, UFW, Fail2ban, automatic security updates, bounded journald/Docker logs, Docker Engine and Compose are installed. AppArmor and time synchronization are active. SSH password and keyboard-interactive authentication are disabled, and fresh public-key logins work for `dataadmin` and temporary root recovery. No project containers or NASA downloads were started on this VPS.

**Remaining access step:** the user must verify `dataadmin` sudo and privately replace the root password previously shared in chat. Root public-key login remains temporarily enabled until that succeeds. Root password SSH is already disabled. The provider firewall, Contabo account 2FA, console/recovery confirmation, off-site backup destination and external alert delivery have not been configured or verified by this session. See [contabo-verification.json](contabo-verification.json).

The outstanding private terminal command is:

```bash
ssh -t dataadmin@13.140.218.234 'sudo -v && sudo passwd root'
```

Enter the existing `dataadmin` sudo password, then choose a new root password. Do not send either password in chat. After this succeeds, the final SSH policy removes root from allowed users and sets `PermitRootLogin no`. The operational script `scripts/secure_vps.py` defaults to printing policy; only `--apply` changes the target host. Its `--keep-root-key` option is for this transition, and its `--os-only` mode leaves SSH policy unchanged. SSH policy changes arm a ten-minute automatic rollback that must be cancelled only after a separate login succeeds.

## 1. Establish access and recovery

On the laptop, install its existing public key:

```bash
ssh-copy-id -i ~/.ssh/id_ed25519.pub root@13.140.218.234
ssh -o PasswordAuthentication=no root@13.140.218.234
```

Enter the VPS password only at the terminal prompt. Never paste a password, private key, `.env`, or resolved Compose configuration into chat or shared logs. The initial root password was shared in chat and needs replacement once key access is verified.

Before restricting SSH, sign into the Contabo panel, enable account two-factor authentication, save recovery codes privately, and confirm that the instance's console/rescue access is available. Create a pre-change snapshot if the panel offers one. A snapshot helps rollback; separate backups are still required for recovery from loss of the server or account.

The existing administrator is `dataadmin`. Use a distinct account/key per team member when adding the team. Access through shared root credentials should end after individual access is established. Keep the original session open while testing a second connection.

## 2. Read-only baseline

The audit script exports hardware, OS version, listening services, selected effective SSH settings, UFW state, service health and Docker status. It does not read passwords, private keys or application environment files, and changes no settings.

From the laptop, once key authentication works:

```bash
ssh root@13.140.218.234 'python3 -' < scripts/audit_vps.py > /tmp/firebridge-vps-before.json
```

Review the detected Ubuntu version, CPU/RAM/disk, SSH port, existing administrator accounts, update/reboot state, time synchronization, and every public listener. Confirm that the IP belongs to the intended purchased instance before provisioning.

## 3. Secure the OS

These changes are performed on the VPS after the audit, not by running a laptop setup script:

1. Install pending Ubuntu security updates. Inspect any reboot requirement; schedule and verify a reboot before deploying the project.
2. Create an ordinary administrator, install the verified public key with correct ownership (`.ssh` mode 0700; `authorized_keys` mode 0600), and grant deliberate sudo access. Test a separate key-only login and privilege escalation before changing root/password SSH settings.
3. Configure OpenSSH for public-key authentication, disable root SSH login and password/keyboard-interactive authentication, and limit authentication attempts. Retain local TCP forwarding for private administrative tunnels. Keep modern Ubuntu crypto defaults rather than copying a static cipher list.
4. Validate the syntax with `sshd -t`, inspect effective settings with `sshd -T` for the intended account, then reload SSH. Keep the original connection open. Use a rollback timer or console recovery while independently testing a new login.
5. Replace the exposed initial root password using a private terminal/password-manager workflow. SSH root login remains disabled; document the chosen console/rescue recovery method.
6. Configure unattended Ubuntu security updates, retain controlled reboots, and verify timers. Security updates may restart affected services; plan maintenance and backups accordingly.
7. Enable Fail2ban for SSH using systemd logs, sensible retry limits and temporary bans. Check that the service is actually monitoring the SSH journal. It complements key authentication and firewall rules.
8. Verify time synchronization and AppArmor. Bound persistent system logs so a noisy service cannot consume the disk. Monitor disk usage, RAM, failed services, and pending reboots.

An SSH port change is optional and is not needed to establish this baseline. Do not disable IPv6 as a shortcut; apply access policy to both address families. Do not apply blanket sysctl/network rules that break Docker forwarding.

[Ubuntu OpenSSH guidance](https://ubuntu.com/server/docs/how-to/security/openssh-server/), [Ubuntu automatic updates](https://ubuntu.com/server/docs/how-to/software/automatic-updates/).

## 4. Firewall policy

Use the Contabo network firewall and UFW on the OS. Add the SSH allow rule **before activating either firewall**. If the administrator has a stable address, restrict SSH to that IP/CIDR. If it changes, establish a deliberate VPN or recovery procedure before imposing a source restriction.

| Port | Initial access policy | Later use |
|---|---|---|
| SSH TCP 22, or verified existing SSH port | Administrator's trusted source where feasible | Server administration |
| TCP 80/443 | Closed until a public web service is deployed | HTTP redirect/certificate handling and HTTPS |
| TCP 5432/55432 | No public access | PostgreSQL via Docker network or SSH tunnel |
| TCP 8080 | No public access | Airflow through SSH tunnel |
| TCP 4213/8082 | No public access | Optional data browsers through SSH tunnel |
| Docker API 2375/2376 | No public listener | Docker socket remains local |

Contabo's firewall denies inbound traffic by default once assigned, and applies immediately. Configure allowed management traffic first. Outbound connections are needed for package updates, DNS/time synchronization and authorized data APIs. [Contabo firewall documentation](https://docs.contabo.com/docs/network-services/firewall/).

Docker published ports can bypass ordinary UFW input rules. Preserve localhost-only binds in Compose and verify externally reachable ports; do not assume a UFW status listing protects a container published on `0.0.0.0`. Keep the provider firewall as another boundary. [Docker firewall behavior](https://docs.docker.com/engine/network/packet-filtering-firewalls/).

## 5. Install the container runtime after security checks

Install Docker Engine and Compose from the official Docker Ubuntu repository, using the existing `scripts/bootstrap_ubuntu.sh` only after the detected OS version and existing packages have been reviewed. It installs prerequisites; it does not implement the OS security steps above.

Only administrators receive Docker access: membership in the Docker group grants control of the host. Preserve the packaged firewall integration and Unix socket permissions; do not expose the Docker API. Use bounded container logs and a documented update/rebuild procedure. Configure any daemon-wide defaults before deploying containers, preserving existing daemon configuration.

The prepared profile totals **9.5 GiB of long-running container memory ceilings**, leaving approximately 2.5 GiB on a nominal 12 GiB server for the OS and other needs. Actual installed memory may be lower; verify it. No application backend or AI model is included in this allowance.

| Service | Memory ceiling | CPU ceiling |
|---|---:|---:|
| FIREBRIDGE PostGIS | 3 GiB | 2 |
| Airflow metadata PostgreSQL | 0.75 GiB | 0.5 |
| Airflow API | 1.5 GiB | 1 |
| Airflow scheduler and executed tasks | 3.5 GiB | 2 |
| Airflow workflow parser | 0.75 GiB | 0.5 |

Airflow parallelism is reduced to two, the ingestion pool to one, and dbt to one thread. Heavy history acquisition and dbt should be run at different times on this VPS. Review actual peaks before increasing concurrency or adding the Node.js services. These limits are an initial configuration, not a load-test result.

## 6. Deploy the project only after the baseline passes

Transfer a source bundle to `/opt/firebridge`, owned by the administrative account. Select the smaller profile **on the server**:

```bash
cd /opt/firebridge
printf '%s\n' contabo-plus-6 > deploy/server-profile
python3 scripts/init_server.py
sh scripts/stack.sh config --quiet
```

`deploy/server-profile` is host-specific and ignored by version control. `scripts/stack.sh` automatically includes `compose.contabo.yaml` when this marker is present. Validation-stack commands keep their separate profile. The laptop's `start_local.sh` is not the server deployment entry point.

Create fresh VPS application secrets; do not copy the laptop's `.env` over the new configuration. Transfer the database, immutable objects and any acquired history deliberately. Use [DEPLOYMENT.md](DEPLOYMENT.md) for database restoration and `scripts/deploy_server.sh` for server startup. New workflows and subscriptions start paused/disabled. Do not start NASA downloads as part of OS hardening.

For private Airflow access, run on the laptop using the tested administrative account:

```bash
ssh -N -L 18080:127.0.0.1:8080 ADMIN_USER@13.140.218.234
```

Then open <http://localhost:18080>. Substitute the actual administrator username. Public TLS proxy and DNS configuration follow only when the application's domain and routing are known. Keep administrative UIs private.

## 7. Backups, updates and acceptance checks

Before enabling unattended project execution:

- Verify a fresh administrative key login, sudo access, the effective SSH policy, provider/OS firewall rules and external port reachability. Recheck after reboot.
- Back up both PostgreSQL databases and referenced immutable objects. Back up the Parquet history directory separately; `backup_stack.sh` does not include it. Preserve `.env` and Airflow's Fernet key in encrypted storage.
- Store a copy outside this VPS, with retention and restore credentials. A backup on the same disk does not cover VPS loss. Choose the external backup destination before claiming off-site backup is configured.
- Rehearse database/object restoration in an isolated environment. An installed timer is not evidence of a working backup or successful recovery.
- Install the supplied backup and health timers only after testing their commands and configuring actual notification delivery. The existing health script is a project check; OS resource/SSH alerts need their own delivery configuration.
- Rebuild pinned application images deliberately, test upgrades, monitor disk/RAM and log growth, and document provider-console recovery. Avoid uncontrolled automatic updates of the entire application stack.

The first project check should use restored local data, with provider collection still disabled. After that succeeds, explicitly start the chosen history or incremental collection workflow and verify one complete request before expanding it.
