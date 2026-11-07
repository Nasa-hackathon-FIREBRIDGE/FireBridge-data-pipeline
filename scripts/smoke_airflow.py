"""Exercise the actual Airflow scheduler/API/LocalExecutor in the isolated validation stack."""
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import subprocess
import time
from uuid import uuid4
import httpx
from dotenv import dotenv_values

root=Path(__file__).resolve().parents[1]
if os.environ.get('FIREBRIDGE_STACK')!='validation':
    raise RuntimeError('Use FIREBRIDGE_STACK=validation; this script must never target the live stack')
env=dotenv_values(root/'.env')
stack=['sh','scripts/stack.sh','exec','-T']
def sql(query):
    return subprocess.check_output(stack+['db','psql','-X','-U','firebridge','-d','firebridge','-At','-v','ON_ERROR_STOP=1','-c',query],text=True).strip()
assert sql("SELECT count(*) FROM firebridge.ingestion_subscriptions WHERE enabled")=='0'
assert sql("SELECT count(*) FROM firebridge.data_releases WHERE scope_key<>'validation-smoke'")=='0'
subprocess.run(stack+['airflow-scheduler','firebridge','orchestrator','airflow'],check=True)
client=httpx.Client(base_url='http://127.0.0.1:8081',timeout=30)
auth=client.post('/auth/token',json={'username':env['AIRFLOW_ADMIN_USER'],'password':env['AIRFLOW_ADMIN_PASSWORD']})
auth.raise_for_status()
client.headers['Authorization']='Bearer '+auth.json()['access_token']
def request(method,path,**kw):
    r=client.request(method,path,**kw)
    if r.status_code>=400:raise RuntimeError(f'Airflow API failed: {method} {path}, HTTP {r.status_code}')
    return r.json()
expected={'firebridge_ingestion','firebridge_analytics','firebridge_archive_import','firebridge_health'}
deadline=time.monotonic()+180
while True:
    if request('GET','/api/v2/importErrors')['total_entries']:
        raise RuntimeError('Airflow Dag import errors; inspect airflow dags list-import-errors')
    available={d['dag_id'] for d in request('GET','/api/v2/dags',params={'limit':100})['dags']}
    if expected<=available:break
    if time.monotonic()>deadline:raise RuntimeError('Dags did not register')
    time.sleep(5)
errors=request('GET','/api/v2/importErrors')
if errors['total_entries']:raise RuntimeError('Airflow Dag import errors')
out={}
def trigger(dag,conf=None):
    run_id='manual__validation_'+uuid4().hex
    request('PATCH',f'/api/v2/dags/{dag}',json={'is_paused':False})
    try:
        request('POST',f'/api/v2/dags/{dag}/dagRuns',json={'dag_run_id':run_id,'logical_date':None,'conf':conf or {}})
        deadline=time.monotonic()+300
        while True:
            result=request('GET',f'/api/v2/dags/{dag}/dagRuns/{run_id}')
            if result['state'] in ('success','failed'):break
            tasks=request('GET',f'/api/v2/dags/{dag}/dagRuns/{run_id}/taskInstances')['task_instances']
            if any(t['state'] in ('failed','up_for_retry') for t in tasks):
                request('PATCH',f'/api/v2/dags/{dag}/dagRuns/{run_id}',json={'state':'failed'})
                raise RuntimeError('Airflow smoke task failed; inspect task logs: '+dag)
            if time.monotonic()>deadline:raise RuntimeError('Airflow smoke run timed out: '+dag)
            time.sleep(3)
        out[dag]={'state':result['state'],'run_id':run_id}
        if result['state']!='success':raise RuntimeError('Airflow smoke run failed: '+dag)
        print(json.dumps({dag:out[dag]}),flush=True)
    finally:
        request('PATCH',f'/api/v2/dags/{dag}',json={'is_paused':True})

trigger('firebridge_ingestion')
trigger('firebridge_analytics')
before=sql("SELECT string_agg(DISTINCT query_status,',') FROM serving.query_coverage c JOIN serving.latest_analytics l ON l.build_id=c.build_id WHERE l.scope_key='validation-smoke' AND date_utc='2024-01-18'")
assert before in ('missing','complete_empty')  # A repeated smoke run may already have imported the complete archive.
imports=root/'data/imports-validation'
imports.mkdir(parents=True,exist_ok=True)
(imports/'synthetic-modis.csv').write_text('latitude,longitude,acq_date,acq_time,satellite,confidence,daynight,version,frp\n35,-5,2024-01-17,1200,Terra,80,D,6.1,10\n35,-4.9,2024-01-17,1200,Terra,80,D,6.1,20\n')
trigger('firebridge_archive_import',{'path':'synthetic-modis.csv','format':'firms','feed':'MODIS_SP',
 'scope':'validation-smoke','bbox':[-6,34,-4,36],'start':'2024-01-17','end':'2024-01-20',
 'coverage_start':'2024-01-17','coverage_end':'2024-01-20'})
assert sql("SELECT count(*) FROM serving.query_coverage c JOIN serving.latest_analytics l ON l.build_id=c.build_id WHERE l.scope_key='validation-smoke' AND query_status='missing'")=='0'
trigger('firebridge_health')
assert sql('SELECT count(*) FROM firebridge.fetch_runs')=='0'
receipt={'checked_at':datetime.now(timezone.utc).isoformat(),'synthetic':True,'provider_calls':0,'runs':out,
 'published_detection_count':int(sql("SELECT sum(detection_count) FROM serving.daily_detections d JOIN serving.latest_analytics l ON l.build_id=d.build_id WHERE l.scope_key='validation-smoke'"))}
(root/'docs/data/airflow-smoke-verification.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(receipt,indent=2))
