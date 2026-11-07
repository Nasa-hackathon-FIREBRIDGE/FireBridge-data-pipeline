"""Verify real analytical outputs and reader/transform isolation; no provider requests."""
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import psycopg
from psycopg.conninfo import make_conninfo
from firebridge.config import Settings
from firebridge.db import connect
from firebridge.store import Store

settings=Settings.load()
receipt={'checked_at':datetime.now(timezone.utc).isoformat(),'external_provider_calls':0,'analytics':[]}
with connect(settings) as conn:
    receipt['orchestrator']=conn.execute('SELECT owner FROM orchestration_control WHERE singleton').fetchone()['owner']
    receipt['enabled_subscriptions']=conn.execute('SELECT count(*) AS n FROM ingestion_subscriptions WHERE enabled').fetchone()['n']
    receipt['migration_count']=conn.execute('SELECT count(*) AS n FROM public.firebridge_migrations').fetchone()['n']
    for item in conn.execute('SELECT * FROM serving.latest_analytics ORDER BY scope_key').fetchall():
        expected=conn.execute('SELECT sum(row_count) AS n FROM serving.partitions WHERE release_id=%s',(item['input_releases']['best_available'],)).fetchone()['n']
        actual=conn.execute('SELECT count(*) AS rows,sum(detection_count) AS detections FROM serving.daily_detections WHERE build_id=%s',(item['build_id'],)).fetchone()
        assert actual['detections']==expected
        uri=conn.execute('SELECT artifacts_uri FROM analytics_builds WHERE id=%s',(item['build_id'],)).fetchone()['artifacts_uri']
        results=json.loads(Store(settings.data_dir).resolve(uri).read_text())['results']
        assert results and all(r['status'] in ('pass','success') for r in results)
        receipt['analytics'].append({'scope':item['scope_key'],'build_id':str(item['build_id']),
          'input_releases':item['input_releases'],'summary_rows':actual['rows'],'native_detections':int(actual['detections']),
          'dbt_nodes_passed':len(results)})
    assert receipt['analytics'],'Build real analytics before verification'
    receipt['serving_views']=conn.execute("SELECT count(*) AS n FROM information_schema.views WHERE table_schema='serving'").fetchone()['n']

for user,password_key in [('firebridge_reader','FIREBRIDGE_READER_PASSWORD'),('firebridge_transform','FIREBRIDGE_DBT_PASSWORD')]:
    url=make_conninfo(settings.database_url,user=user,password=os.environ[password_key])
    with psycopg.connect(url) as conn:
        assert conn.execute('SELECT count(*) FROM serving.latest_analytics').fetchone()[0]==len(receipt['analytics'])
        for statement in ('SELECT * FROM firebridge.ingestion_subscriptions LIMIT 0',
                          'UPDATE analytics.daily_detections SET detection_count=0 WHERE false'):
            try:
                with conn.transaction():conn.execute(statement)
            except psycopg.errors.InsufficientPrivilege:pass
            else:raise AssertionError(user+' unexpectedly has private/write access')
receipt['permission_checks']='Reader and transform roles can read serving results; private source access and permanent analytic writes denied'
Path('docs/data/platform-verification.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(receipt,indent=2))
