"""Small, explicitly synthetic history inventory for the isolated CI stack only."""
import os
from firebridge.config import Settings
from firebridge.db import connect
from firebridge.catalog import FEEDS
from firebridge.history import initialize,ledger,validate_and_store

if os.environ.get('FIREBRIDGE_VALIDATION')!='isolated-firebridge-validation':
    raise RuntimeError('History fixtures require the isolated validation environment')
settings=Settings.load()
with connect(settings) as db:
    if db.execute("SELECT 1 FROM data_releases WHERE scope_key<>'validation-smoke' LIMIT 1").fetchone():
        raise RuntimeError('Refusing history fixtures alongside non-validation releases')
root=settings.data_dir/'lake/history';initialize(root)
for feed,(platforms,stream) in FEEDS.items():
    req={'id':f'{feed}_2024-01-17_2024-01-20','feed':feed,'start':'2024-01-17','end_exclusive':'2024-01-20'}
    body='latitude,longitude,acq_date,acq_time,satellite,confidence,daynight,version,frp\n'
    for platform in platforms:
        confidence='80' if platform in ('Terra','Aqua') else ('H' if platform.startswith('L') else 'n')
        version='61.03' if platform in ('Terra','Aqua') else ('' if platform.startswith('L') else '2')
        if stream=='nrt' and version:version+='NRT'
        body+=f'35,-5,2024-01-17,1200,{platform},{confidence},D,{version},12\n'
    receipt=validate_and_store(root,req,body.encode(),reserve_bytes=0)
    with ledger(root) as db:
        db.execute('''INSERT OR REPLACE INTO requests(id,feed,start,end_exclusive,priority,status,rows,
          raw_bytes,parquet_bytes,raw_sha256,parquet_sha256,completed_at)
          VALUES (:id,:feed,:start,:end_exclusive,0,'complete',:rows,:raw_bytes,:parquet_bytes,
          :raw_sha256,:parquet_sha256,:completed_at)''',receipt)
print({'synthetic':True,'history_windows':len(FEEDS),'provider_calls':0})
