"""Synthetic input for the isolated validation Compose project only."""
import os
from uuid import uuid4
from firebridge.config import Settings
from firebridge.catalog import source_id,area
from firebridge.db import connect
from firebridge.normalize import normalize
from firebridge.publish import detection_partition,publish,run
from firebridge.store import Store,asset

if os.environ.get('FIREBRIDGE_VALIDATION')!='isolated-firebridge-validation':
    raise RuntimeError('Synthetic seeding requires the isolated validation environment')
settings=Settings.load()
scope='validation-smoke'
with connect(settings) as conn:
    if conn.execute("SELECT 1 FROM data_releases WHERE scope_key<>%s LIMIT 1",(scope,)).fetchone():
        raise RuntimeError('Refusing synthetic seed in a database with non-validation releases')
    area(conn,scope,[-6,34,-4,36])
    obj=Store(settings.data_dir).json({'synthetic':True,'scope':scope})
    aid=asset(conn,obj,'raw-modis_sp','synthetic-validation','https://example.invalid/synthetic')
    rid=run(conn,'validation',str(uuid4()),{'synthetic':True},obj.uri)
    pids=[]
    for day,positions in [('2024-01-17',[-5,-4.9]),('2024-01-19',[])]:
        rows=[normalize(dict(satellite='Terra',latitude='35',longitude=str(lon),acq_date=day,
          acq_time='1200',confidence='80',daynight='D'),'standard',['Terra']) for lon in positions]
        pids.append(detection_partition(conn,settings,rid,aid,source_id('Terra','standard'),day,scope,[-6,34,-4,36],rows))
    result=publish(conn,settings,pids,scope)
print({'scope':scope,'synthetic':True,'releases':result})
