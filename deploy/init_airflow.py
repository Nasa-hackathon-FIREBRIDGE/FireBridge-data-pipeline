"""Idempotent setup; never enable subscriptions or unpause Dags."""
import os
import subprocess
import psycopg

def command(*args):
    subprocess.run(args,check=True)

command('airflow','db','migrate')
url=os.environ['AIRFLOW__DATABASE__SQL_ALCHEMY_CONN'].replace('postgresql+psycopg2:','postgresql:')
with psycopg.connect(url) as conn:
    exists=conn.execute('SELECT 1 FROM ab_user WHERE username=%s',(os.environ['AIRFLOW_ADMIN_USER'],)).fetchone()
if not exists:
    command('airflow','users','create','--username',os.environ['AIRFLOW_ADMIN_USER'],
            '--password',os.environ['AIRFLOW_ADMIN_PASSWORD'],'--firstname','FIREBRIDGE',
            '--lastname','Operator','--role','Admin','--email','operator@localhost.invalid')
ingestion_slots=int(os.environ.get('FIREBRIDGE_INGESTION_POOL_SLOTS','2'))
if not 1 <= ingestion_slots <= 4: raise ValueError('Invalid ingestion pool size')
command('airflow','pools','set','firebridge_ingestion',str(ingestion_slots),'Bounded provider calls with a shared database rate budget')
command('airflow','pools','set','firebridge_analytics','1','Serialize memory-intensive dbt builds on this VPS')
command('firebridge','init')
command('firebridge','register-pilot')
print('Initialized. New Dags/subscriptions start disabled; existing scheduling settings are preserved.')
