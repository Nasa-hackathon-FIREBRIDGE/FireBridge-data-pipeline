#!/usr/bin/python3
"""Root-owned forced SSH command for verified CI release uploads and activation.

Only the dedicated CI key may invoke this helper. It never accepts shell code,
uploads application secrets, or starts provider downloads. Python stdlib only.
"""
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request

ROOT = Path('/opt/firebridge')
SHARED = ROOT/'shared'
REPO = 'https://github.com/Nasa-hackathon-FIREBRIDGE/FireBridge-data-pipeline'
SHA = r'[0-9a-f]{40}'
HASH = r'[0-9a-f]{64}'
RESERVE = 20*1024**3
SERVICES = ('airflow-api','airflow-scheduler','airflow-dag-processor')
ROOT_FILES = {'README.md','LICENSE','FIREBRIDGE_Blueprint.md','pyproject.toml','requirements-data.lock',
    'Dockerfile','compose.yaml','compose.airflow.yaml','compose.local.yaml','compose.contabo.yaml',
    'compose.release.yaml','start_local.sh','stop_local.sh','history_status.sh','.dockerignore','.env.example','.gitignore'}
ROOT_DIRS = {'src','dags','dbt','deploy','scripts','tests','config','docs','.github'}


def parse_command(value):
    parts=value.split()
    if parts==['status']:return parts
    if len(parts)==3 and parts[0] in ('source','image') and re.fullmatch(SHA,parts[1]) and re.fullmatch(HASH,parts[2]):return parts
    if len(parts)==2 and parts[0] in ('activate','rollback') and re.fullmatch(SHA,parts[1]):return parts
    raise ValueError('Unsupported deployment command')


def validate_members(members):
    total=0;names=set()
    if len(members)>5000:raise ValueError('Too many release members')
    for m in members:
        p=PurePosixPath(m.name)
        if p.is_absolute() or '..' in p.parts or not p.parts or m.name in names:
            raise ValueError('Unsafe or duplicate release path')
        names.add(m.name)
        if not (m.isfile() or m.isdir()):raise ValueError('Links and special files are forbidden')
        if len(p.parts)==1 and m.isfile() and p.name not in ROOT_FILES:raise ValueError('Unexpected root file')
        if len(p.parts)>1 and p.parts[0] not in ROOT_DIRS:raise ValueError('Unexpected directory')
        if any(part=='.env' or (part.startswith('.env.') and part!='.env.example') for part in p.parts):
            raise ValueError('Secrets cannot be shipped in releases')
        if p.as_posix() in ('deploy/server-profile','deploy/release-image'):raise ValueError('Host settings cannot be uploaded')
        total+=m.size
        if total>200*1024**2:raise ValueError('Release expands beyond size limit')
    return members


def atomic_json(path,data):
    temporary=path.with_suffix('.partial')
    temporary.write_text(json.dumps(data,indent=2)+'\n');temporary.chmod(0o600);temporary.replace(path)


def run(args,*,cwd=None,log=None,timeout=900):
    result=subprocess.run(args,cwd=cwd,stdout=log or subprocess.PIPE,stderr=log or subprocess.PIPE,
        text=log is None,timeout=timeout)
    if result.returncode:raise RuntimeError('Command failed; inspect the private deployment log')
    return result.stdout if log is None else None


def stack(release,*args,log=None,timeout=900):
    return run(['sh','scripts/stack.sh',*args],cwd=release,log=log,timeout=timeout)


def receive(kind,revision,expected,stream):
    limit=(3*1024**3 if kind=='image' else 50*1024**2)
    target=ROOT/'inbox'/f'{revision}-{kind}.tar.gz'
    temporary=target.with_suffix('.partial'); digest=hashlib.sha256(); size=0
    try:
        with temporary.open('wb') as out:
            while chunk:=stream.read(1024**2):
                size+=len(chunk)
                if size>limit or shutil.disk_usage(ROOT).free<RESERVE:
                    raise ValueError('Upload size limit or disk reserve reached')
                digest.update(chunk);out.write(chunk)
        if digest.hexdigest()!=expected:raise ValueError('Upload checksum mismatch')
        temporary.replace(target)
        if kind=='source':
            with tarfile.open(target,'r:gz') as archive:validate_members(archive.getmembers())
        else:
            with (SHARED/'deployments'/f'{revision}-image.log').open('a') as log:
                if shutil.disk_usage(ROOT).free<RESERVE+6*1024**3:raise ValueError('Insufficient space to load image')
                run(['docker','image','load','--input',str(target)],log=log,timeout=900)
            info=json.loads(run(['docker','image','inspect',f'firebridge-airflow:{revision}']))[0]
            labels=info.get('Config',{}).get('Labels',{}) or {}
            if labels.get('org.opencontainers.image.revision')!=revision or labels.get('org.opencontainers.image.source')!=REPO:
                raise ValueError('Image provenance labels do not match this release')
            atomic_json(ROOT/'inbox'/f'{revision}-image.json',{'image_id':info['Id'],'revision':revision})
            target.unlink()  # Docker now retains the verified image; no second multi-GB copy.
        return {'uploaded':kind,'revision':revision,'bytes':size,'sha256':expected}
    finally:temporary.unlink(missing_ok=True)


def credentials():
    values={}
    for line in (SHARED/'.env').read_text().splitlines():
        if '=' in line and not line.startswith('#'):
            k,v=line.split('=',1);values[k]=v.strip().strip('"\'')
    return values


def airflow_api():
    values=credentials()
    def request(method,path,data=None,token=None):
        headers={'Content-Type':'application/json'}
        if token:headers['Authorization']='Bearer '+token
        req=urllib.request.Request('http://127.0.0.1:8080'+path,
            data=json.dumps(data).encode() if data is not None else None,headers=headers,method=method)
        with urllib.request.urlopen(req,timeout=30) as response:return json.load(response)
    token=request('POST','/auth/token',{'username':values['AIRFLOW_ADMIN_USER'],'password':values['AIRFLOW_ADMIN_PASSWORD']})['access_token']
    return lambda method,path,data=None:request(method,path,data,token)


def pause_and_drain(release):
    api=airflow_api()
    dags=api('GET','/api/v2/dags?limit=100')['dags']
    enabled=[d['dag_id'] for d in dags if not d['is_paused']]
    try:
        for dag in enabled:api('PATCH','/api/v2/dags/'+dag,{'is_paused':True})
        deadline=time.monotonic()+600
        while True:
            count=stack(release,'exec','-T','airflow-db','psql','-U','airflow','-d','airflow','-At','-c',
                "SELECT count(*) FROM dag_run WHERE state IN ('running','queued')").strip()
            if count=='0':return enabled
            if time.monotonic()>deadline:raise RuntimeError('Active workflows did not drain; retry after they finish')
            time.sleep(10)
    except Exception:
        for dag in enabled:api('PATCH','/api/v2/dags/'+dag,{'is_paused':False})
        raise


def restore_schedules(enabled):
    if enabled:
        api=airflow_api()
        for dag in enabled:api('PATCH','/api/v2/dags/'+dag,{'is_paused':False})


def prepare_release(revision):
    release=ROOT/'releases'/revision
    marker=ROOT/'inbox'/f'{revision}-image.json'
    image=json.loads(marker.read_text())
    actual=json.loads(run(['docker','image','inspect',f'firebridge-airflow:{revision}']))[0]['Id']
    if actual!=image['image_id']:raise ValueError('Release image changed after verification')
    if release.exists():return release
    temporary=ROOT/'releases'/(revision+'.partial')
    if temporary.exists():shutil.rmtree(temporary)
    temporary.mkdir(mode=0o755)
    with tarfile.open(ROOT/'inbox'/f'{revision}-source.tar.gz','r:gz') as archive:
        for member in validate_members(archive.getmembers()):
            member.mode&=0o755
        archive.extractall(temporary,filter='data')
    for name in ('compose.yaml','compose.airflow.yaml','compose.contabo.yaml','compose.release.yaml','scripts/init_server.py'):
        if not (temporary/name).is_file():raise ValueError('Incomplete deployment bundle')
    if (SHARED/'.env').exists():(temporary/'.env').symlink_to(SHARED/'.env')
    (temporary/'data').symlink_to(SHARED/'data',target_is_directory=True)
    (temporary/'deploy').mkdir(exist_ok=True)
    (temporary/'deploy/server-profile').write_text('contabo-plus-6\n')
    (temporary/'deploy/release-image').write_text(f'firebridge-airflow:{revision}\n')
    temporary.rename(release)
    return release


def activate(revision):
    release=prepare_release(revision)
    previous=(ROOT/'current').resolve() if (ROOT/'current').exists() else None
    previous_image=None
    if previous and (SHARED/'deployment.json').exists():
        previous_image=json.loads((SHARED/'deployment.json').read_text()).get('image_id')
    enabled=[];paused=False;stopped=False
    log_path=SHARED/'deployments'/f'{revision}.log'
    with log_path.open('a') as log:
        try:
            if shutil.disk_usage(ROOT).free<RESERVE:raise ValueError('Disk reserve reached')
            if not (SHARED/'.env').exists():
                run(['python3','scripts/init_server.py'],cwd=release,log=log)
                (release/'.env').replace(SHARED/'.env')
                (release/'.env').symlink_to(SHARED/'.env')
            stack(release,'config','--quiet',log=log)
            if previous:
                enabled=pause_and_drain(previous);paused=True
                # Do not issue manual workflow triggers during maintenance.
                stack(previous,'stop',*SERVICES,log=log);stopped=True
                stack(previous,'ps',log=log)
                run(['sh','scripts/backup_stack.sh'],cwd=previous,log=log)
            stack(release,'up','-d','--wait','--no-build','db','airflow-db',log=log)
            stack(release,'run','--rm','--no-deps','airflow-permissions',log=log)
            stack(release,'run','--rm','airflow-init',log=log)
            stack(release,'run','--rm','--no-deps','airflow-init','python','-m','firebridge','orchestrator','airflow',log=log)
            stack(release,'up','-d','--wait','--no-build',*SERVICES,log=log)
            stack(release,'exec','-T','airflow-scheduler','python','/opt/firebridge/deploy/check_dags.py',log=log)
            stack(release,'exec','-T','airflow-scheduler','firebridge','status',log=log)
            restore_schedules(enabled)
            link=ROOT/'current.next';link.unlink(missing_ok=True);link.symlink_to(release,target_is_directory=True);link.replace(ROOT/'current')
            result={'state':'healthy','revision':revision,'previous_revision':previous.name if previous else None,
                'deployed_at':datetime.now(timezone.utc).isoformat(),'new_provider_subscriptions_enabled':False,
                'restored_schedules':enabled,'image':f'firebridge-airflow:{revision}',
                'image_id':json.loads(run(['docker','image','inspect',f'firebridge-airflow:{revision}']))[0]['Id']}
            atomic_json(SHARED/'deployment.json',result)
            return result
        except Exception:
            if previous:
                try:
                    # A rerun may rebuild the same commit with a new image ID.
                    # Recover the actually deployed image, even if its tag moved.
                    if previous==release and previous_image:
                        run(['docker','image','tag',previous_image,f'firebridge-airflow:{revision}'],log=log)
                        atomic_json(ROOT/'inbox'/f'{revision}-image.json',{'image_id':previous_image,'revision':revision})
                    if stopped:stack(previous,'up','-d','--wait','--no-build',*SERVICES,log=log)
                    if paused:restore_schedules(enabled)
                except Exception:
                    raise RuntimeError('Deployment and code recovery failed; inspect private logs. Database backups retained.') from None
            raise RuntimeError('Deployment failed; previous code selected when available. Database schema is not automatically downgraded. Inspect private logs.') from None


def main():
    if os.geteuid()!=0:raise RuntimeError('Use the installed root-owned forced command')
    os.umask(0o077)
    parts=parse_command(os.environ.get('SSH_ORIGINAL_COMMAND',''))
    for path in (ROOT/'inbox',ROOT/'releases',SHARED/'deployments',SHARED/'data'):
        path.mkdir(parents=True,exist_ok=True)
    with (SHARED/'deployment.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if parts[0]=='status':
            result=json.loads((SHARED/'deployment.json').read_text()) if (SHARED/'deployment.json').exists() else {'state':'not_deployed'}
        elif parts[0] in ('source','image'):result=receive(*parts,sys.stdin.buffer)
        else:result=activate(parts[1])
        print(json.dumps(result))


if __name__=='__main__':
    try:main()
    except Exception as error:
        # Never expose exception details that might include host configuration.
        print(json.dumps({'state':'failed','error_type':type(error).__name__,
            'message':str(error) if isinstance(error,(ValueError,RuntimeError)) else 'Inspect private server deployment logs'}))
        raise SystemExit(1)
