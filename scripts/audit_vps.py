"""Read-only VPS inventory. Run on the target host with sudo; no secrets exported.

Does not install packages, change users/firewalls, restart services, or start the
project. Only selected effective SSH/Docker settings are included in output.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess


def command(*args):
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=20)
        return {'exit_code':proc.returncode,'output':proc.stdout.strip()}
    except FileNotFoundError:
        return {'available':False}
    except subprocess.TimeoutExpired:
        return {'error':'timeout'}


def inventory():
    os_info = {}
    for line in Path('/etc/os-release').read_text().splitlines():
        if '=' in line:
            k,v=line.split('=',1)
            os_info[k]=v.strip('"')
    disk=shutil.disk_usage('/')
    ssh=command('/usr/sbin/sshd','-T')
    selected={'port','permitrootlogin','passwordauthentication','kbdinteractiveauthentication',
        'pubkeyauthentication','permitemptypasswords','maxauthtries','x11forwarding',
        'allowtcpforwarding','allowagentforwarding','allowusers','allowgroups','authenticationmethods'}
    ssh['output']='\n'.join(line for line in ssh.get('output','').splitlines()
        if line.split(' ',1)[0] in selected)
    report={'recorded_at_utc':datetime.now(timezone.utc).isoformat(),
        'effective_uid':os.geteuid(),'os':os_info,'cpu_count':os.cpu_count(),
        'memory':command('free','-h'),'disk_root_bytes':disk._asdict(),
        'filesystems':command('lsblk','-o','NAME,SIZE,TYPE,FSTYPE,MOUNTPOINTS'),
        'listening_ports':command('ss','-lntup'),'effective_ssh_global':ssh,
        'ufw':command('ufw','status','verbose'),
        'failed_services':command('systemctl','--failed','--no-pager','--plain'),
        'time_sync':command('timedatectl','show','-p','NTPSynchronized','-p','Timezone'),
        'reboot_required':Path('/var/run/reboot-required').exists(),
        'admin_accounts':command('getent','group','sudo'),
        'docker_version':command('docker','version','--format','{{.Server.Version}}'),
        'containers':command('docker','ps','--format','{{.Names}}\t{{.Ports}}\t{{.Status}}'),
        'services':{name:command('systemctl','is-active',name) for name in
            ('ssh','ufw','fail2ban','unattended-upgrades','apparmor','docker','apt-daily-upgrade.timer')}}
    daemon=Path('/etc/docker/daemon.json')
    if daemon.exists():
        try:
            data=json.loads(daemon.read_text())
            report['docker_selected_settings']={k:data[k] for k in
                ('log-driver','log-opts','live-restore','iptables','ip6tables','userns-remap') if k in data}
        except (ValueError,OSError):
            report['docker_selected_settings']={'error':'unreadable_or_invalid_config'}
    return report


if __name__=='__main__':
    print(json.dumps(inventory(),indent=2))
