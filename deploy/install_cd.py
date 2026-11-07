"""Install the restricted CI deployment account on the reviewed VPS; root only."""
import argparse
import os
from pathlib import Path
import pwd
import re
import shutil
import subprocess


def run(*args):
    return subprocess.run(args,check=True,capture_output=True,text=True).stdout


def install(public_key,gateway):
    if os.geteuid()!=0:raise RuntimeError('Run on the VPS as root')
    key=Path(public_key).read_text().strip()
    if '\n' in key or not re.fullmatch(r'ssh-ed25519 [A-Za-z0-9+/=]+(?: [^\r\n]+)?',key):
        raise ValueError('Expected a single Ed25519 public key')
    run('ssh-keygen','-lf',str(public_key))
    account='firebridge-deploy'
    try:pwd.getpwnam(account)
    except KeyError:
        run('useradd','--system','--create-home','--home-dir','/var/lib/firebridge-deploy','--shell','/bin/bash',account)
    entry=pwd.getpwnam(account)
    home=Path(entry.pw_dir)
    keys=home/'.ssh';keys.mkdir(mode=0o700,exist_ok=True)
    keys.chmod(0o700);os.chown(keys,entry.pw_uid,entry.pw_gid)
    authorized=keys/'authorized_keys'
    authorized.write_text('restrict,command="/usr/bin/sudo -n /usr/local/sbin/firebridge-cd-gateway" '+key+'\n')
    authorized.chmod(0o600);os.chown(authorized,entry.pw_uid,entry.pw_gid)
    helper=Path('/usr/local/sbin/firebridge-cd-gateway')
    shutil.copyfile(gateway,helper);helper.chmod(0o755);os.chown(helper,0,0)
    rule=Path('/etc/sudoers.d/firebridge-cd')
    temporary=rule.with_suffix('.partial')
    temporary.write_text('Defaults:firebridge-deploy env_keep += "SSH_ORIGINAL_COMMAND"\n'
        'firebridge-deploy ALL=(root) NOPASSWD: /usr/local/sbin/firebridge-cd-gateway ""\n')
    temporary.chmod(0o440);run('visudo','-cf',str(temporary));temporary.replace(rule)
    ssh=Path('/etc/ssh/sshd_config.d/00-firebridge.conf')
    original=ssh.read_text()
    match=re.search(r'^AllowUsers (.+)$',original,re.M)
    if not match:raise RuntimeError('Review existing SSH AllowUsers before installation')
    allowed=match[1].split()
    if account not in allowed:allowed.append(account)
    updated=original[:match.start()]+'AllowUsers '+' '.join(allowed)+original[match.end():]
    backup=Path('/var/backups/firebridge-ssh-before-cd.conf');backup.write_text(original);backup.chmod(0o600)
    ssh.write_text(updated)
    try:run('/usr/sbin/sshd','-t')
    except Exception:ssh.write_text(original);raise
    run('systemctl','reload','ssh')
    root=Path('/opt/firebridge');root.mkdir(mode=0o755,exist_ok=True)
    for name in ('shared','shared/deployments','shared/data','inbox','releases'):
        p=root/name;p.mkdir(parents=True,exist_ok=True);p.chmod(0o700)
    print('Restricted CI account installed. No interactive shell, forwarding, Docker-group membership, application secrets or downloads were enabled.')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--public-key',type=Path,required=True)
    p.add_argument('--gateway',type=Path,required=True)
    a=p.parse_args();install(a.public_key,a.gateway)
