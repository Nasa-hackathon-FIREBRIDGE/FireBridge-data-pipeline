"""Configure the GitHub production environment using locally authenticated gh.

Reads deployment keys directly from ignored local files; never prints them.
Does not push code or start a workflow unless --trigger is explicitly requested.
"""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[1]
REPO='Nasa-hackathon-FIREBRIDGE/FireBridge-data-pipeline'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--host',required=True)
    p.add_argument('--enable',action='store_true',help='Enable automatic production deployment after CI')
    p.add_argument('--trigger',action='store_true',help='Start a new pipeline run on main')
    a=p.parse_args()
    if not re.fullmatch(r'[a-zA-Z0-9.:-]+',a.host):raise SystemExit('Invalid VPS host')
    gh=str(ROOT/'.tools/gh') if (ROOT/'.tools/gh').exists() else shutil.which('gh')
    if not gh:raise SystemExit('Install GitHub CLI first')
    def command(*args,body=None,allowed_failure=False):
        r=subprocess.run([gh,*args],input=body,capture_output=True)
        if r.returncode and not allowed_failure:
            raise SystemExit('GitHub operation failed: '+str(args[0])+'. Check CLI login and organization administrator access.')
        return r
    command('auth','status')
    permission=json.loads(command('repo','view',REPO,'--json','viewerPermission').stdout)['viewerPermission']
    if permission!='ADMIN':raise SystemExit('Repository administrator access is required')
    endpoint=f'repos/{REPO}/environments/production'
    found=command('api',endpoint,allowed_failure=True)
    if found.returncode:
        body=json.dumps({'deployment_branch_policy':{'protected_branches':False,'custom_branch_policies':True}}).encode()
        command('api','--method','PUT',endpoint,'--input','-',body=body)
    else:
        settings=json.loads(found.stdout)
        if not (settings.get('deployment_branch_policy') or {}).get('custom_branch_policies'):
            raise SystemExit('Existing production environment needs selected-branch deployment policy. Review Settings > Environments; existing protections were preserved.')
    policies=json.loads(command('api',endpoint+'/deployment-branch-policies').stdout)['branch_policies']
    if not any(x['name']=='main' and x.get('type','branch')=='branch' for x in policies):
        command('api','--method','POST',endpoint+'/deployment-branch-policies','--input','-',
            body=json.dumps({'name':'main','type':'branch'}).encode())
    for name,path in [('DEPLOY_SSH_KEY',ROOT/'.deploy/github_actions'),('DEPLOY_KNOWN_HOSTS',ROOT/'.deploy/known_hosts')]:
        if not path.is_file():raise SystemExit('Missing ignored deployment file: '+str(path))
        command('secret','set',name,'--env','production','--repo',REPO,body=path.read_bytes())
    command('variable','set','DEPLOY_HOST','--env','production','--repo',REPO,'--body',a.host)
    existing=json.loads(command('variable','list','--repo',REPO,'--json','name,value').stdout)
    if a.enable or not any(x['name']=='DEPLOY_ENABLED' for x in existing):
        command('variable','set','DEPLOY_ENABLED','--repo',REPO,'--body','true' if a.enable else 'false')
    if a.trigger:command('workflow','run','data-platform.yml','--ref','main','--repo',REPO)
    print(json.dumps({'production_environment':'configured','deployment_credentials':'encrypted in GitHub',
        'host_variable':'configured','automatic_deployment_enabled_by_this_command':a.enable,'workflow_triggered':a.trigger}))


if __name__=='__main__':main()
