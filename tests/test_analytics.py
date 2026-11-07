import json
import os
from pathlib import Path
import shutil
import pytest
from psycopg import sql
from firebridge.analytics import build,project_dir
from firebridge.db import connect
from test_publication import publish_points
from firebridge.weather import fetch_weather
from firebridge.util import utc

pytestmark=[pytest.mark.integration,pytest.mark.dbt]


@pytest.fixture(autouse=True)
def require_dbt():
    if not shutil.which(os.environ.get('FIREBRIDGE_DBT_BIN','dbt')):
        pytest.skip('Set FIREBRIDGE_DBT_BIN to run real dbt integration checks')


def latest(settings,scope):
    with connect(settings) as conn:
        return conn.execute('SELECT * FROM serving.latest_analytics WHERE scope_key=%s',(scope,)).fetchone()


def test_real_dbt_empty_missing_revision_and_replay(database,scope):
    first,_=publish_points(database,scope,'nrt',[-5,-4.9])
    publish_points(database,scope,'nrt',[],day='2024-01-19')
    a=build(database,scope)
    with connect(database) as conn:
        rows=conn.execute('SELECT query_status,detection_count FROM serving.query_coverage WHERE build_id=%s ORDER BY date_utc',(a['build_id'],)).fetchall()
        assert rows==[{'query_status':'complete_with_detections','detection_count':2},
                      {'query_status':'missing','detection_count':None},{'query_status':'complete_empty','detection_count':0}]
    assert build(database,scope)['status']=='unchanged'
    publish_points(database,scope,'standard',[])
    b=build(database,scope)
    assert b['build_id']!=a['build_id']
    with connect(database) as conn:
        assert conn.execute('SELECT sum(detection_count) AS n FROM serving.daily_detections WHERE build_id=%s',(a['build_id'],)).fetchone()['n']==2
        assert conn.execute('SELECT sum(detection_count) AS n FROM serving.daily_detections WHERE build_id=%s',(b['build_id'],)).fetchone()['n']==0


def test_real_dbt_failed_test_keeps_previous_release(database,scope,tmp_path):
    publish_points(database,scope,'standard',[-5])
    good=build(database,scope)
    broken=tmp_path/'broken-dbt'
    shutil.copytree(project_dir(),broken,ignore=shutil.ignore_patterns('target','logs'))
    (broken/'tests'/'injected_failure.sql').write_text('select 1 as deliberately_failing_row')
    with pytest.raises(RuntimeError,match='dbt_build_failed'):build(database,scope,project=broken)
    assert str(latest(database,scope)['build_id'])==good['build_id']
    with connect(database) as conn:
        failed=conn.execute("SELECT id FROM analytics_builds WHERE scope_key=%s AND status='failed'",(scope,)).fetchone()['id']
        assert conn.execute('SELECT count(*) AS n FROM analytics.daily_detections WHERE build_id=%s',(failed,)).fetchone()['n']==0


def test_publication_failure_rolls_back_all_marts(database,scope):
    publish_points(database,scope,'standard',[-5])
    good=build(database,scope)
    with connect(database) as conn:
        conn.execute(sql.SQL("""CREATE FUNCTION public.reject_test_context() RETURNS trigger LANGUAGE plpgsql AS $$
          BEGIN IF NEW.scope_key={} THEN RAISE EXCEPTION 'injected publication failure'; END IF; RETURN NEW; END $$""").format(sql.Literal(scope)))
        conn.execute('CREATE TRIGGER reject_test_context BEFORE INSERT ON analytics.area_daily_context FOR EACH ROW EXECUTE FUNCTION public.reject_test_context()')
    try:
        with pytest.raises(RuntimeError,match='analytics_failed'):build(database,scope,force=True)
        assert str(latest(database,scope)['build_id'])==good['build_id']
        with connect(database) as conn:
            assert conn.execute("SELECT count(*) AS n FROM analytics.daily_detections d JOIN analytics_builds b ON b.id=d.build_id WHERE b.status='failed' AND b.scope_key=%s",(scope,)).fetchone()['n']==0
    finally:
        with connect(database) as conn:
            conn.execute('DROP TRIGGER reject_test_context ON analytics.area_daily_context')
            conn.execute('DROP FUNCTION public.reject_test_context()')


def test_weather_interval_aggregation_and_no_join_fanout(database,scope,monkeypatch):
    publish_points(database,scope,'standard',[-5,-4.9])
    times=[int(utc('2024-01-17').timestamp())+i*3600 for i in range(72)]
    variables={'temperature_2m':('°C',25),'relative_humidity_2m':('%',40),
      'precipitation':('mm',1),'wind_speed_10m':('m/s',3),'wind_direction_10m':('°',350)}
    payload={'latitude':35,'longitude':-5,'hourly_units':{k:v[0] for k,v in variables.items()},
             'hourly':dict(time=times,**{k:[v[1]]*72 for k,v in variables.items()})}
    payload['hourly']['relative_humidity_2m'][0]=None
    monkeypatch.setattr('firebridge.weather.get',lambda *a,**kw:(json.dumps(payload).encode(),{}))
    fetch_weather(database,{'scope_key':scope,'latitude':35,'longitude':-5,'start':'2024-01-17','end_exclusive':'2024-01-20'})
    result=build(database,scope)
    with connect(database) as conn:
        rain=conn.execute("SELECT date_utc,value,complete_day FROM serving.daily_weather WHERE build_id=%s AND variable='precipitation' ORDER BY date_utc",(result['build_id'],)).fetchall()
        assert [r['value'] for r in rain]==[None,24,24,None]
        humidity=conn.execute("SELECT value,valid_sample_count FROM serving.daily_weather WHERE build_id=%s AND variable='relative_humidity_2m' AND date_utc='2024-01-17'",(result['build_id'],)).fetchone()
        assert humidity=={'value':None,'valid_sample_count':23}
        context=conn.execute("SELECT detections_by_source,weather_samples FROM serving.area_daily_context WHERE build_id=%s AND date_utc='2024-01-17'",(result['build_id'],)).fetchone()
        assert context['detections_by_source'][0]['detection_count']==2 and len(context['weather_samples'])==4
