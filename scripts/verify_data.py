"""Verify real imported counts and the Node.js read-only contract; no provider calls."""
from collections import Counter
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import duckdb
import psycopg
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from firebridge.config import Settings
from firebridge.db import connect

settings=Settings.load()
receipt={'checked_at':datetime.now(timezone.utc).isoformat(),'external_provider_calls':0}
with connect(settings) as conn:
    receipt['database']=conn.execute("SELECT version() AS postgres,PostGIS_Lib_Version() AS postgis").fetchone()
    receipt['migrations']=conn.execute('SELECT name,sha256 FROM public.firebridge_migrations ORDER BY name').fetchall()
    receipt['table_count']=conn.execute("SELECT count(*) AS n FROM information_schema.tables WHERE table_schema='firebridge' AND table_type='BASE TABLE'").fetchone()['n']
    receipt['view_count']=conn.execute("SELECT count(*) AS n FROM information_schema.views WHERE table_schema='serving'").fetchone()['n']
    aliases=conn.execute('SELECT * FROM serving.latest_releases ORDER BY scope_key,alias').fetchall()
    receipt['releases']=[]
    for alias in aliases:
        counts=conn.execute('SELECT source_id,count(*) AS n FROM serving.detections WHERE release_id=%s GROUP BY source_id ORDER BY source_id',(alias['release_id'],)).fetchall()
        partitions=conn.execute('SELECT count(*) AS n,sum(row_count) AS rows FROM serving.partitions WHERE release_id=%s',(alias['release_id'],)).fetchone()
        assert sum(r['n'] for r in counts)==partitions['rows']
        receipt['releases'].append(dict(alias=alias['alias'],scope_key=alias['scope_key'],release_id=str(alias['release_id']),
                                       partitions=partitions['n'],rows=sum(r['n'] for r in counts),by_source=counts))
    global_release=next(r for r in receipt['releases'] if r['scope_key']=='global' and r['alias']=='standard_only')
    assert global_release['rows']==4_876_343
    assert global_release['partitions']==734
    pilot=next(r for r in receipt['releases'] if r['scope_key']=='morocco-pilot' and r['alias']=='best_available')
    pc={r['source_id']:r['n'] for r in pilot['by_source']}
    assert pc['modis-terra-c61-standard']==22 and pc['modis-aqua-c61-standard']==35
    assert pc['viirs-snpp-c2-standard']==311 and pc['viirs-noaa20-c2-standard']==342 and pc['viirs-noaa21-c2-nrt']==324
    assert pilot['partitions']==367*5 and pilot['rows']==1034
    receipt['enabled_subscriptions']=conn.execute('SELECT count(*) AS n FROM ingestion_subscriptions WHERE enabled').fetchone()['n']
    assert receipt['enabled_subscriptions']==0
    receipt['queued_tasks']=conn.execute("SELECT count(*) AS n FROM ingest_tasks WHERE status IN ('queued','running')").fetchone()['n']
    assert receipt['queued_tasks']==0
    contract=conn.execute("""SELECT table_name,column_name,data_type,udt_name,ordinal_position FROM information_schema.columns
     WHERE table_schema='serving' ORDER BY table_name,ordinal_position""").fetchall()
    Path('docs/data/DB_CONTRACT.json').write_text(json.dumps(contract,indent=2))

reader=make_conninfo(settings.database_url,user='firebridge_reader',password=os.environ['FIREBRIDGE_READER_PASSWORD'])
with psycopg.connect(reader,row_factory=dict_row) as conn:
    conn.execute(Path('docs/data/queries.sql').read_text(),prepare=False)
    sample=conn.execute("EXECUTE fb_latest('morocco-pilot','best_available')").fetchone()
    assert str(sample['release_id'])==pilot['release_id']
    with conn.transaction():
        conn.execute("SET LOCAL statement_timeout='15s'")
        rows=conn.execute('SELECT count(*) AS n FROM serving.detections WHERE release_id=%s',(pilot['release_id'],)).fetchone()['n']
        assert rows==1034
    try:
        with conn.transaction():conn.execute('SELECT * FROM firebridge.ingestion_subscriptions LIMIT 1')
    except psycopg.errors.InsufficientPrivilege:pass
    else:raise AssertionError('Reader unexpectedly has access to operational tables')
    receipt['reader_contract']='all six query templates prepared; pilot query verified; operational tables denied'

Path('docs/data/verification.json').write_text(json.dumps(receipt,indent=2,default=str))
print(json.dumps(receipt,indent=2,default=str))
