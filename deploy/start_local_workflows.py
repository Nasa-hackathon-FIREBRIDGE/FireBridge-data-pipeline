"""Start/reuse the full local archive run and activate the recurring local workflows."""
import argparse
import json
import os
from pathlib import Path
import time
from uuid import uuid4
import httpx

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--skip-download',action='store_true',help='Do not start a new full-history download')
args=parser.parse_args()

client=httpx.Client(base_url='http://airflow-api:8080',timeout=30)
def authenticate():
    response=client.post('/auth/token',json={'username':os.environ['AIRFLOW_ADMIN_USER'],
        'password':os.environ['AIRFLOW_ADMIN_PASSWORD']})
    response.raise_for_status()
    client.headers['Authorization']='Bearer '+response.json()['access_token']

authenticate()
def api(method,path,**kwargs):
    response=client.request(method,path,**kwargs)
    if response.status_code==401:
        authenticate()
        response=client.request(method,path,**kwargs)
    if response.status_code>=400:
        raise RuntimeError(f'Airflow request failed: {method} {path} HTTP {response.status_code}')
    return response.json()

expected={'firebridge_ingestion','firebridge_analytics','firebridge_health',
    'firebridge_archive_import','firebridge_local_archive_lake','firebridge_full_history_download'}
deadline=time.monotonic()+180
while True:
    if api('GET','/api/v2/importErrors')['total_entries']:
        raise RuntimeError('Airflow workflow import error; inspect the Airflow UI')
    registered={row['dag_id'] for row in api('GET','/api/v2/dags',params={'limit':100})['dags']}
    if expected<=registered:break
    if time.monotonic()>deadline:raise RuntimeError('Workflows did not register within three minutes')
    time.sleep(3)

dag='firebridge_local_archive_lake'
api('PATCH',f'/api/v2/dags/{dag}',json={'is_paused':False})
runs=api('GET',f'/api/v2/dags/{dag}/dagRuns',params={'limit':100,'order_by':'-run_after'})['dag_runs']
active=next((r for r in runs if r['state'] in ('running','queued')),None)
run_id=active['dag_run_id'] if active else 'manual__local_start_'+uuid4().hex
if not active:
    api('POST',f'/api/v2/dags/{dag}/dagRuns',json={'dag_run_id':run_id,'logical_date':None,'conf':{}})
print('Loading all local archive files through Airflow: '+run_id,flush=True)
progress=Path('/data/lake/progress.json')
last=None
deadline=time.monotonic()+4*3600+300
while True:
    run=api('GET',f'/api/v2/dags/{dag}/dagRuns/{run_id}')
    if run['state'] in ('success','failed'):break
    if progress.exists():
        current=progress.read_text()
        if current!=last:
            print('Archive progress: '+json.dumps(json.loads(current)),flush=True)
            last=current
    if time.monotonic()>deadline:raise RuntimeError('Archive workflow exceeded the startup wait limit; inspect Airflow')
    time.sleep(10)
if run['state']!='success':
    raise RuntimeError('Archive import failed; open its task log in Airflow. Existing published data was preserved.')
receipt={'archive_run':{'dag':dag,'run_id':run_id,'state':run['state']},'recurring_workflows':{}}
for dag in ('firebridge_ingestion','firebridge_analytics','firebridge_health'):
    api('PATCH',f'/api/v2/dags/{dag}',json={'is_paused':False})
    runs=api('GET',f'/api/v2/dags/{dag}/dagRuns',params={'limit':20,'order_by':'-run_after'})['dag_runs']
    active=next((r for r in runs if r['state'] in ('running','queued')),None)
    rid=active['dag_run_id'] if active else 'manual__local_start_'+uuid4().hex
    if not active:api('POST',f'/api/v2/dags/{dag}/dagRuns',json={'dag_run_id':rid,'logical_date':None,'conf':{}})
    receipt['recurring_workflows'][dag]={'enabled':True,'run_id':rid}
print('Archive load complete. Ingestion, analytics and health workflows are enabled.',flush=True)
print('Recurring provider subscriptions keep their existing settings.',flush=True)
if not args.skip_download:
    # Initialize an empty browser catalog offline before dispatching the task.
    # The task owns availability discovery and every actual provider request.
    from firebridge.history import initialize
    initialize(Path('/data/lake/history'))
    dag='firebridge_full_history_download'
    api('PATCH',f'/api/v2/dags/{dag}',json={'is_paused':False})
    runs=api('GET',f'/api/v2/dags/{dag}/dagRuns',params={'limit':100,'order_by':'-run_after'})['dag_runs']
    active=next((r for r in runs if r['state'] in ('running','queued')),None)
    rid=active['dag_run_id'] if active else 'manual__full_history_'+uuid4().hex
    if not active:
        api('POST',f'/api/v2/dags/{dag}/dagRuns',json={'dag_run_id':rid,'logical_date':None,'conf':{}})
    receipt['full_history_download']={'dag':dag,'run_id':rid,'state':'dispatched_or_reused'}
    print('Full NASA FIRMS history download started/resumed in Airflow: '+rid,flush=True)
    print('The launcher does not wait for this long download. Check history.request_inventory in DuckDB or the Airflow task.',flush=True)
else:
    print('Full-history download was not started (--skip-download). Existing running tasks are unaffected.',flush=True)
Path('/data/lake/local-workflows.json').write_text(json.dumps(receipt,indent=2)+'\n')
