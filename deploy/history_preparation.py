"""Run the offline audit then the isolated benchmark through authenticated Airflow.

Runs inside the existing scheduler container; credentials never leave its env.
No history-load or provider-download DAG is triggered by this helper.
"""
import os
import time
from uuid import uuid4
import httpx


def main():
    with httpx.Client(base_url='http://airflow-api:8080',timeout=30) as client:
        def authenticate():
            auth=client.post('/auth/token',json={'username':os.environ['AIRFLOW_ADMIN_USER'],'password':os.environ['AIRFLOW_ADMIN_PASSWORD']})
            if auth.status_code!=200:raise RuntimeError('Airflow authentication failed; inspect private configuration')
            client.headers['Authorization']='Bearer '+auth.json()['access_token']
        authenticate()
        def request(method,path,**kwargs):
            response=client.request(method,path,**kwargs)
            if response.status_code==401:
                authenticate();response=client.request(method,path,**kwargs)
            if response.status_code>=400:raise RuntimeError(f'Airflow request failed: {method} {path}, HTTP {response.status_code}')
            return response.json()
        for dag in ('firebridge_history_audit','firebridge_history_benchmark'):
            info=request('GET','/api/v2/dags/'+dag)
            if info['is_paused']:request('PATCH','/api/v2/dags/'+dag,json={'is_paused':False})
            try:
                runs=request('GET',f'/api/v2/dags/{dag}/dagRuns',params={'limit':100,'order_by':'-run_after'})['dag_runs']
                active=[r for r in runs if r['state'] in ('queued','running')]
                if active:run_id=active[0]['dag_run_id']
                else:
                    run_id='manual__history_prepare_'+uuid4().hex
                    request('POST',f'/api/v2/dags/{dag}/dagRuns',json={'dag_run_id':run_id,'logical_date':None,'conf':{}})
                print(f'{dag}: {run_id}',flush=True)
                deadline=time.monotonic()+13*3600;previous=None
                while time.monotonic()<deadline:
                    result=request('GET',f'/api/v2/dags/{dag}/dagRuns/{run_id}')
                    state=result['state']
                    if state!=previous:print(f'{dag}: {state}',flush=True);previous=state
                    if state=='success':break
                    if state=='failed':raise RuntimeError(dag+' failed; inspect its Airflow task logs')
                    time.sleep(15)
                else:raise RuntimeError('Preparation wait timed out; inspect Airflow before retrying')
            finally:
                if info['is_paused']:request('PATCH','/api/v2/dags/'+dag,json={'is_paused':True})
        print('Preparation complete. Reports: /data/history-serving/{audit,benchmark}.json. Main history publication remains a separate bounded operation.',flush=True)


if __name__=='__main__':main()
