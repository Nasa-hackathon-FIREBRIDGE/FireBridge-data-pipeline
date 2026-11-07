"""Apply the reviewed Ubuntu VPS baseline, with timed SSH rollback.

Run on the target host as root only after a separate admin key login and sudo
have been tested. Does not rotate passwords, install Docker, or start the app.
"""
import argparse
from datetime import datetime, timezone
import grp
import json
import os
from pathlib import Path
import pwd
import re
import shlex
import shutil
import subprocess


def ssh_policy(admin,keep_root_key=False,allow_deploy=False):
    if not re.fullmatch(r'[a-z][a-z0-9_-]{0,30}',admin) or admin=='root':
        raise ValueError('Use an ordinary administrator account')
    return f'''# FIREBRIDGE: key-only administration; local tunnels remain available.
PubkeyAuthentication yes
AuthenticationMethods publickey
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin {'prohibit-password' if keep_root_key else 'no'}
PermitEmptyPasswords no
AllowUsers {admin}{' root' if keep_root_key else ''}{' firebridge-deploy' if allow_deploy else ''}
MaxAuthTries 3
LoginGraceTime 30
MaxSessions 5
X11Forwarding no
AllowAgentForwarding no
AllowTcpForwarding local
PermitTunnel no
PermitUserEnvironment no
ClientAliveInterval 300
ClientAliveCountMax 2
LogLevel VERBOSE
'''


def command(*args):
    return subprocess.run(args,check=True,text=True,capture_output=True).stdout


def write_config(path,content,backup):
    path=Path(path)
    relative=path.relative_to('/')
    saved=backup/relative
    saved.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():shutil.copy2(path,saved)
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.firebridge-partial')
    temp.write_text(content)
    temp.chmod(0o644)
    temp.replace(path)


def configure_os(backup):
    # Preserve existing rules; allow management before enabling the firewall.
    command('ufw','allow','22/tcp','comment','SSH administration')
    command('ufw','default','deny','incoming')
    command('ufw','default','allow','outgoing')
    command('ufw','logging','low')
    command('ufw','--force','enable')
    write_config('/etc/fail2ban/jail.d/firebridge.local',
        '[sshd]\nenabled = true\nbackend = systemd\nport = 22\n'
        'banaction = ufw\nfindtime = 10m\nmaxretry = 5\nbantime = 1h\n',backup)
    command('fail2ban-client','-t')
    write_config('/etc/apt/apt.conf.d/20auto-upgrades',
        'APT::Periodic::Update-Package-Lists "1";\nAPT::Periodic::Unattended-Upgrade "1";\n',backup)
    write_config('/etc/apt/apt.conf.d/99firebridge-maintenance',
        'Unattended-Upgrade::Automatic-Reboot "false";\n',backup)
    write_config('/etc/systemd/journald.conf.d/firebridge.conf',
        '[Journal]\nStorage=persistent\nSystemMaxUse=256M\nRuntimeMaxUse=64M\n'
        'MaxRetentionSec=14day\nCompress=yes\n',backup)
    command('systemctl','enable','--now','fail2ban','apt-daily.timer','apt-daily-upgrade.timer','unattended-upgrades')
    command('systemctl','restart','fail2ban','systemd-journald')


def apply(admin,os_only=False,keep_root_key=False):
    try:pwd.getpwnam('firebridge-deploy');allow_deploy=True
    except KeyError:allow_deploy=False
    policy=ssh_policy(admin,keep_root_key,allow_deploy)
    if os.geteuid()!=0:raise RuntimeError('Run as root on the target VPS')
    info={line.split('=',1)[0]:line.split('=',1)[1].strip('"')
          for line in Path('/etc/os-release').read_text().splitlines() if '=' in line}
    if info.get('ID')!='ubuntu' or info.get('VERSION_ID')!='24.04':
        raise RuntimeError('This baseline was reviewed for Ubuntu 24.04 only')
    account=pwd.getpwnam(admin)
    if account.pw_uid==0 or admin not in grp.getgrnam('sudo').gr_mem:
        raise RuntimeError('Administrator must be an ordinary sudo-group member')
    keys=Path(account.pw_dir)/'.ssh/authorized_keys'
    command('ssh-keygen','-lf',str(keys))
    if not re.search(r'^Include\s+/etc/ssh/sshd_config\.d/\*\.conf\s*$',
                     Path('/etc/ssh/sshd_config').read_text(),re.M):
        raise RuntimeError('Review nonstandard SSH Include configuration first')
    effective=command('/usr/sbin/sshd','-T')
    ports=re.findall(r'^port (\d+)$',effective,re.M)
    if ports!=['22']:raise RuntimeError('Review nonstandard SSH ports before firewall changes')
    # Refuse to overwrite another active rollback window.
    timer=subprocess.run(['systemctl','is-active','--quiet','firebridge-ssh-rollback.timer']).returncode
    if timer==0:raise RuntimeError('A previous SSH rollback timer is still armed')
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup=Path('/var/backups/firebridge-security')/stamp
    backup.mkdir(parents=True,mode=0o700)
    backup.parent.chmod(0o700)
    if os_only:
        configure_os(backup)
        print(json.dumps({'state':'os_baseline_applied','ssh_policy_changed':False,
            'backup_directory':str(backup)}))
        return
    ssh=Path('/etc/ssh/sshd_config.d/00-firebridge.conf')
    saved=backup/ssh.relative_to('/')
    if ssh.exists():
        saved.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(ssh,saved)
        restore=f'cp -p {shlex.quote(str(saved))} {shlex.quote(str(ssh))}'
    else:
        restore=f'rm -f {shlex.quote(str(ssh))}'
    rollback=backup/'restore-ssh.sh'
    rollback.write_text('#!/bin/sh\nset -eu\n'+restore+
        '\n/usr/sbin/sshd -t\nsystemctl reload ssh\n')
    rollback.chmod(0o700)
    command('systemd-run','--unit=firebridge-ssh-rollback','--on-active=10m','/bin/sh',str(rollback))
    try:
        write_config(ssh,policy,backup)
        command('/usr/sbin/sshd','-t')
        # First-value wins: verify the drop-in actually overrides cloud defaults.
        effective_lines=[line.split(' ',1) for line in command('/usr/sbin/sshd','-T').splitlines() if ' ' in line]
        settings=dict(effective_lines)
        expected={'passwordauthentication':'no','kbdinteractiveauthentication':'no',
            'authenticationmethods':'publickey'}
        if any(settings.get(k)!=v for k,v in expected.items()):
            raise RuntimeError('Effective SSH settings differ from requested policy')
        allowed=[value for key,value in effective_lines if key=='allowusers']
        if set(allowed)!={admin,*(['root'] if keep_root_key else []),*(['firebridge-deploy'] if allow_deploy else [])}:
            raise RuntimeError('Effective SSH allowed users differ from requested policy')
        root_values=('prohibit-password','without-password') if keep_root_key else ('no',)
        if settings.get('permitrootlogin') not in root_values:
            raise RuntimeError('Effective root SSH policy differs from requested policy')
        configure_os(backup)
        command('systemctl','reload','ssh')
        result={'state':'ssh_rollback_armed','admin':admin,'backup_directory':str(backup),
            'rollback_minutes':10,'ssh_port':22,'public_services':'SSH only',
            'root_key_temporarily_retained':keep_root_key,
            'next_step':'Verify a NEW admin SSH connection, then cancel firebridge-ssh-rollback.timer.'}
        (backup/'applied.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result))
    except Exception:
        command('/bin/sh',str(rollback))
        command('systemctl','stop','firebridge-ssh-rollback.timer')
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--admin',required=True)
    parser.add_argument('--apply',action='store_true',help='Actually change this host; default prints SSH policy only')
    parser.add_argument('--os-only',action='store_true',help='Apply firewall, Fail2ban, updates and logging; leave SSH policy untouched')
    parser.add_argument('--keep-root-key',action='store_true',help='Transition only: retain root public-key access while admin sudo is verified')
    args=parser.parse_args()
    if args.apply:apply(args.admin,args.os_only,args.keep_root_key)
    else:print(ssh_policy(args.admin,args.keep_root_key))
