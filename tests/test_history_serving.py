from dataclasses import replace
import gzip
import json
from pathlib import Path
import sqlite3

import pytest

from firebridge.config import Settings
from firebridge.db import connect
from firebridge.history import initialize,ledger,validate_and_store
from firebridge.history_serving import audit,benchmark,inventory,load,load_window,native_row
from firebridge.normalize import normalize
from firebridge.publish import detection_partition,stream_detection_partition,run
from firebridge.store import Store,asset
from firebridge.util import now,utc

HEADER='latitude,longitude,acq_date,acq_time,satellite,confidence,daynight,version,frp\n'


def window(settings,body=None,feed='VIIRS_NOAA20_SP',start='2024-01-01',end='2024-01-03'):
    root=settings.data_dir/'lake/history';initialize(root)
    req={'id':f'{feed}_{start}_{end}','feed':feed,'start':start,'end_exclusive':end}
    body=body or (HEADER+'35,-5,2024-01-01,1200,N20,n,D,2,12\n'*2)
    receipt=validate_and_store(root,req,body.encode(),reserve_bytes=0)
    with ledger(root) as db:
        db.execute('''INSERT INTO requests(id,feed,start,end_exclusive,priority,status,rows,
          raw_bytes,parquet_bytes,raw_sha256,parquet_sha256,completed_at)
          VALUES (:id,:feed,:start,:end_exclusive,0,'complete',:rows,:raw_bytes,:parquet_bytes,
          :raw_sha256,:parquet_sha256,:completed_at)''',receipt)
    return root


def test_audit_is_offline_checks_all_artifacts_and_detects_later_corruption(tmp_path):
    settings=Settings('unused',tmp_path)
    root=window(settings,HEADER+'35,-5,2024-01-01,1200,N20,n,D,2,-999\n')
    first=audit(settings)
    assert first['state']=='passed' and first['source_rows']==1 and first['provider_calls']==0
    assert first['coverage'][0]['invalid_frp_rows']==1
    assert audit(settings)['results']==first['results']
    raw=next((root/'raw').glob('*.gz'));raw.write_bytes(b'corrupt')
    failed=audit(settings)
    assert failed['state']=='failed' and failed['failed_windows']==1
    assert 'Checksum mismatch' in failed['results'][0]['error']


def test_invalid_frp_stays_null_and_traceable_without_changing_valid_hashes():
    raw=dict(satellite='N20',latitude='35',longitude='-5',acq_date='2024-01-01',acq_time='1200',confidence='n',daynight='D',version='2',frp='12')
    assert native_row(raw,'VIIRS_NOAA20_SP')==(normalize(raw,'standard',['N20']),False)
    corrected,invalid=native_row(raw|{'frp':'-999'},'VIIRS_NOAA20_SP')
    assert invalid and corrected['frp_mw'] is None
    assert corrected['native_fields']['frp_raw']=='-999' and corrected['native_fields']['frp_quality']=='invalid'
    assert corrected['record_sha256']!=normalize(raw|{'frp':None},'standard',['N20'])['record_sha256']


def test_audit_reports_required_native_field_blockers(tmp_path):
    settings=Settings('unused',tmp_path)
    window(settings,HEADER+'35,-5,2024-01-01,1200,N20,wrong,D,2,12\n')
    report=audit(settings)
    assert report['state']=='passed'  # Integrity succeeds; native loading must reject this window.
    assert report['coverage'][0]['blocking_native_rows']==1


@pytest.mark.parametrize('version,collection',[('6.03','c6'),('6.0NRT','c6'),('61.03','c61'),('6.1NRT','c61')])
def test_modis_collection_identity(version,collection):
    row=dict(satellite='Terra',latitude='35',longitude='-5',acq_date='2024-01-01',acq_time='1200',confidence='80',daynight='D',version=version)
    assert normalize(row,'nrt' if version.endswith('NRT') else 'standard',['Terra'],allow_historical_collections=True)['source_id']==f'modis-terra-{collection}-'+('nrt' if version.endswith('NRT') else 'standard')


@pytest.mark.integration
def test_resume_after_publication_failure_deduplicates_and_preserves_empty_days(database,scope,monkeypatch,tmp_path):
    database=replace(database,data_dir=tmp_path)
    root=window(database)
    real_publish=__import__('firebridge.history_serving',fromlist=['publish']).publish
    monkeypatch.setattr('firebridge.history_serving.publish',lambda *a,**kw: (_ for _ in ()).throw(RuntimeError('crash before publication')))
    args=dict(root=root,scope=scope,bbox=[-6,34,-4,36],max_windows=1,reserve_bytes=0)
    with pytest.raises(RuntimeError,match='crash'):load(database,**args)
    with connect(database) as db:
        assert not db.execute('SELECT 1 FROM release_aliases WHERE scope_key=%s',(scope,)).fetchone()
        assert db.execute("SELECT count(*) n FROM data_partitions WHERE support_spec->>'scope_key'=%s",(scope,)).fetchone()['n']==2
    monkeypatch.setattr('firebridge.history_serving.publish',real_publish)
    result=load(database,**args)
    assert result['new_windows']==1 and result['results'][0]['unique_rows']==1
    assert result['results'][0]['duplicate_rows']==1
    replay=load(database,**args,request_ids=[inventory(root)[0]['id']])
    assert replay['new_windows']==0 and replay['results'][0]['reused']
    assert replay['results'][0]['releases']==result['results'][0]['releases']
    resumed=load(database,**args)
    assert resumed['new_windows']==0 and resumed['skipped_completed_windows']==1 and not resumed['results']
    with connect(database) as db:
        rows=db.execute("SELECT partition_key,row_count FROM data_partitions WHERE support_spec->>'scope_key'=%s ORDER BY partition_key",(scope,)).fetchall()
    assert [(r['partition_key'],r['row_count']) for r in rows]==[('2024-01-01',1),('2024-01-02',0)]


@pytest.mark.integration
def test_invalid_native_row_cannot_publish_a_partial_window(database,scope,tmp_path):
    database=replace(database,data_dir=tmp_path)
    root=window(database,HEADER+'35,-5,2024-01-01,1200,N20,n,D,2,12\n35,-5,2024-01-02,1200,N20,wrong,D,2,13\n')
    with pytest.raises(ValueError,match='confidence'):
        load(database,root=root,scope=scope,max_windows=1,reserve_bytes=0)
    with connect(database) as db:
        assert not db.execute("SELECT 1 FROM data_partitions WHERE support_spec->>'scope_key'=%s",(scope,)).fetchone()
        assert not db.execute('SELECT 1 FROM release_aliases WHERE scope_key=%s',(scope,)).fetchone()


@pytest.mark.integration
def test_stream_partition_matches_existing_contract(database,scope):
    native=dict(satellite='Terra',latitude='35',longitude='-5',acq_date='2024-01-01',acq_time='1200',confidence='80',daynight='D',version='6.03')
    row=normalize(native,'standard',['Terra'],allow_historical_collections=True);bbox=[-6,34,-4,36]
    with connect(database) as db:
        obj=Store(database.data_dir).json({'test':'stream'})
        aid=asset(db,obj,'raw-modis_sp',scope,'https://example.invalid/fixture')
        rid=run(db,'stream-test',scope,{},obj.uri)
        first=detection_partition(db,database,rid,aid,row['source_id'],'2024-01-01',scope,bbox,[row],fetched_at=now())
        second=stream_detection_partition(db,database,rid,aid,row['source_id'],'2024-01-01',scope,bbox,lambda:iter([row]),1,fetched_at=now())
        assert first==second


@pytest.mark.integration
def test_benchmark_never_changes_main_database_and_cleans_own_database(database,tmp_path):
    database=replace(database,data_dir=tmp_path)
    # Its inventory has one feed; production selects a window for every inventoried feed.
    root=window(database)
    audit(database)
    with connect(database) as db:before=db.execute('SELECT count(*) n FROM detections').fetchone()['n']
    result=benchmark(database,root=root,build_analytics=False,reserve_bytes=0)
    assert result['state']=='passed' and result['unique_detections']==1
    assert not result['retained_database'] and result['database_growth_bytes']>0
    with connect(database) as db:
        assert db.execute('SELECT count(*) n FROM detections').fetchone()['n']==before
        assert not db.execute('SELECT 1 FROM pg_database WHERE datname=%s',(result['database'],)).fetchone()


@pytest.mark.integration
def test_invalid_frp_is_flagged_in_postgres_and_quality_ledger(database,scope,tmp_path):
    database=replace(database,data_dir=tmp_path)
    root=window(database,HEADER+'35,-5,2024-01-01,1200,N20,n,D,2,-999\n')
    result=load(database,root=root,scope=scope,max_windows=1,reserve_bytes=0)
    with connect(database) as db:
        row=db.execute('SELECT d.frp_mw,d.native_fields FROM serving.detections s JOIN detections d ON d.id=s.id WHERE s.release_id=%s',(result['results'][0]['releases']['standard_only'],)).fetchone()
        assert row['frp_mw'] is None and row['native_fields']['frp_raw']=='-999'
        assert db.execute("SELECT 1 FROM quality_issues WHERE rule_id='invalid-frp'").fetchone()


@pytest.mark.integration
def test_landsat_has_separate_scope_and_provider_footprint(database,scope,tmp_path):
    database=replace(database,data_dir=tmp_path)
    root=window(database,HEADER+'35,-105,2024-01-01,1200,L8,H,D,,\n',feed='LANDSAT_NRT')
    result=load(database,root=root,scope=scope,max_windows=1,reserve_bytes=0)
    assert result['scopes']==[scope+'-landsat-us-canada']
    with connect(database) as db:
        row=db.execute('SELECT support_spec FROM data_partitions WHERE id=%s',(result['results'][0]['partition_ids'][0],)).fetchone()
        assert 'US/Canada' in row['support_spec']['provider_footprint']
        assert not db.execute('SELECT 1 FROM release_aliases WHERE scope_key=%s',(scope,)).fetchone()
