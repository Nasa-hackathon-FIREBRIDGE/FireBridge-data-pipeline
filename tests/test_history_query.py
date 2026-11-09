from dataclasses import replace
import json
from uuid import uuid4

import pytest

from firebridge.catalog import area
from firebridge.db import connect
from firebridge.history_serving import audit
from firebridge.history_query import publish_catalog,submit,prepare,status
from firebridge.util import digest
from test_history_serving import window,HEADER


def request(settings,*,bbox=(-6,34,-4,36),start='2024-01-01',end='2024-01-03',geometry=None,indexed=False):
    root=window(settings,HEADER+'35,-5,2024-01-01,1200,N20,n,D,2,-999\n'*2+
      '35,-5,2024-01-02,0000,N20,h,N,2,12\n'+
      '35,20,2024-01-01,1200,N20,n,D,2,9\n')
    audit(settings)
    if indexed:
        from firebridge.history_index import build
        build(settings,reserve_bytes=0)
    catalog=publish_catalog(settings)
    aid=uuid4();analysis=uuid4()
    with connect(settings) as db:
        source=area(db,'test-aoi-'+str(aid),bbox)
        if geometry:
            source=uuid4()
            db.execute("INSERT INTO areas(id,name,version,geom,geometry_sha256,display_timezone,provenance) VALUES (%s,'polygon fixture',%s,ST_Multi(ST_GeomFromText(%s,4326)),%s,'UTC','fixture')",(source,str(source),geometry,digest(geometry)))
        db.execute("""INSERT INTO metric_definitions(id,version,unit,family,description,definition,requires_masks,requires_model)
          VALUES ('native_detections_v1','1','count','native_detections','native','{}',false,false) ON CONFLICT DO NOTHING""")
        spec={'history_catalog_id':catalog['catalog_id'],'data_mode':'standard_only'}
        from psycopg.types.json import Jsonb
        db.execute("""INSERT INTO analyses(id,area_id,release_id,start_date,end_date_exclusive,time_basis,metric_key,
          selection_policy,weighting_version,weather_policy,news_policy,request_spec,cache_key,status)
          VALUES (%s,%s,%s,%s,%s,'utc','native_detections_v1','standard','v1','{}','{}',%s,%s,'queued')""",
          (analysis,source,catalog['catalog_id'],start,end,Jsonb(spec),digest(str(analysis))))
    return str(analysis),root,catalog


@pytest.mark.integration
@pytest.mark.parametrize('indexed',[False,True])
def test_query_prunes_area_deduplicates_preserves_frp_and_is_reusable(database,tmp_path,indexed):
    settings=replace(database,data_dir=tmp_path)
    analysis,root,catalog=request(settings,indexed=indexed)
    first=submit(settings,analysis)
    assert first['status']=='queued'
    result=prepare(settings,first['job_id'],reserve_bytes=0)
    assert result['status']=='succeeded' and result['result']['selected_rows']==2
    assert result['result']['duplicate_rows']==1 and result['result']['provider_calls']==0
    assert result['result']['indexed_windows']==int(indexed)
    assert submit(settings,analysis)==result
    assert prepare(settings,first['job_id'],reserve_bytes=0)==result
    with connect(settings) as db:
        rows=db.execute('SELECT d.frp_mw,d.native_fields FROM serving.detections s JOIN detections d ON d.id=s.id WHERE s.release_id=%s ORDER BY d.acquired_at',(result['result']['release_id'],)).fetchall()
        assert len(rows)==2 and rows[0]['frp_mw'] is None and rows[0]['native_fields']['frp_raw']=='-999'
        assert rows[1]['frp_mw']==12
        parts=db.execute('SELECT support_spec,row_count FROM release_partitions rp JOIN data_partitions p ON rp.partition_id=p.id WHERE release_id=%s',(result['result']['release_id'],)).fetchall()
        assert len(parts)==1 and parts[0]['row_count']==2
        assert parts[0]['support_spec']['inventory_complete'] and parts[0]['support_spec']['end_exclusive'].startswith('2024-01-03')
        assert db.execute('SELECT release_id FROM analyses WHERE id=%s',(analysis,)).fetchone()['release_id']==__import__('uuid').UUID(catalog['catalog_id'])


@pytest.mark.integration
@pytest.mark.parametrize('indexed',[False,True])
def test_zero_result_retains_verified_inventory(database,tmp_path,indexed):
    settings=replace(database,data_dir=tmp_path)
    analysis,_,_=request(settings,bbox=(0,0,1,1),indexed=indexed)
    job=submit(settings,analysis);result=prepare(settings,job['job_id'],reserve_bytes=0)
    assert result['result']['selected_rows']==0
    with connect(settings) as db:
        assert db.execute('SELECT sum(row_count) n FROM data_partitions WHERE id IN (SELECT partition_id FROM release_partitions WHERE release_id=%s)',(result['result']['release_id'],)).fetchone()['n']==0


@pytest.mark.integration
@pytest.mark.parametrize('indexed',[False,True])
def test_exact_polygon_hole_excludes_points_inside_bbox(database,tmp_path,indexed):
    settings=replace(database,data_dir=tmp_path)
    analysis,_,_=request(settings,geometry='POLYGON((-6 34,-4 34,-4 36,-6 36,-6 34),(-5.5 34.5,-5.5 35.5,-4.5 35.5,-4.5 34.5,-5.5 34.5))',indexed=indexed)
    result=prepare(settings,submit(settings,analysis)['job_id'],reserve_bytes=0)
    assert result['result']['selected_rows']==0


@pytest.mark.integration
def test_corruption_and_size_limits_cannot_publish_partial_result(database,tmp_path):
    settings=replace(database,data_dir=tmp_path)
    analysis,_,_=request(settings)
    job=submit(settings,analysis)
    with pytest.raises(RuntimeError,match='history_selection_too_large'):
        prepare(settings,job['job_id'],max_selected=1,reserve_bytes=0)
    assert status(settings,job['job_id'])['error_code']=='history_selection_too_large'
    with connect(settings) as db:
        assert db.execute('SELECT release_id FROM pipeline_runs WHERE id=%s',(job['job_id'],)).fetchone()['release_id'] is None


@pytest.mark.integration
@pytest.mark.parametrize('indexed',[False,True])
def test_changed_input_fails_closed_before_publication(database,tmp_path,indexed):
    settings=replace(database,data_dir=tmp_path)
    analysis,root,_=request(settings,indexed=indexed)
    job=submit(settings,analysis)
    # The directory also contains _empty.parquet for schema discovery. Mutate
    # the actual catalog input, regardless of filesystem directory order.
    target=root/'parquet'/'VIIRS_NOAA20_SP_2024-01-01_2024-01-03.parquet'
    if indexed:
        from firebridge.history_index import descriptor
        from firebridge.history_serving import inventory
        value=descriptor(settings,inventory(root)[0])
        target=tmp_path/'history-index'/value['shards'][0]['path']
    target.write_bytes(b'changed')
    with pytest.raises(ValueError,match='checksum'):prepare(settings,job['job_id'],reserve_bytes=0)
    assert status(settings,job['job_id'])['status']=='failed'
