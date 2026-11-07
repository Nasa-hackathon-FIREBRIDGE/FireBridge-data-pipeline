from uuid import uuid4
import pytest
from firebridge.catalog import source_id
from firebridge.db import connect
from firebridge.normalize import normalize
from firebridge.publish import detection_partition,publish,run
from firebridge.store import Store,asset
from firebridge.util import utc,now
from datetime import timedelta

pytestmark=pytest.mark.integration


def publish_points(settings,scope,stream,positions,day='2024-01-17'):
    with connect(settings) as conn:
        body=Store(settings.data_dir).json([scope,stream,positions,day])
        aid=asset(conn,body,'raw-modis_'+('sp' if stream=='standard' else 'nrt'),body.sha256,'https://example.test/fixture')
        rid=run(conn,'test',str(uuid4()),{},str(body.path))
        rows=[normalize(dict(satellite='Terra',latitude='35',longitude=str(x),acq_date=day,acq_time='1200',confidence='80',daynight='D'),stream,['Terra']) for x in positions]
        pid=detection_partition(conn,settings,rid,aid,source_id('Terra',stream),day,scope,[-6,34,-4,36],rows)
        return publish(conn,settings,[pid],scope),pid


def count(settings,release):
    with connect(settings) as conn:
        return conn.execute('SELECT count(*) AS n FROM serving.detections WHERE release_id=%s',(release,)).fetchone()['n']


def test_replay_dedup_revision_and_empty_standard_replacement(database,scope):
    a,p1=publish_points(database,scope,'nrt',[-5,-5,-4.9])
    assert count(database,a['best_available'])==2
    replay,p2=publish_points(database,scope,'nrt',[-4.9,-5])
    assert p1==p2 and a==replay
    revised,_=publish_points(database,scope,'nrt',[-5])
    assert revised['best_available']!=a['best_available']
    assert count(database,a['best_available'])==2 and count(database,revised['best_available'])==1
    standard,_=publish_points(database,scope,'standard',[])
    assert count(database,standard['best_available'])==0
    assert count(database,standard['nrt_only'])==1
    late,_=publish_points(database,scope,'nrt',[-5,-4.8])
    assert late['best_available']==standard['best_available']  # standard wins, including empty result
    with connect(database) as conn:
        change=conn.execute("SELECT reason FROM release_changes WHERE to_release_id=%s",(standard['best_available'],)).fetchone()
        assert change['reason']=='standard_replacement'


def test_transaction_rollback_never_moves_alias(database,scope):
    first,pid=publish_points(database,scope,'nrt',[-5])
    with pytest.raises(RuntimeError):
        with connect(database) as conn:
            obj=Store(database.data_dir).json([scope,'uncommitted-correction'])
            aid=asset(conn,obj,'raw-modis_nrt',obj.sha256,'https://example.test/rollback')
            rid=run(conn,'test',str(uuid4()),{},str(obj.path))
            revised=detection_partition(conn,database,rid,aid,source_id('Terra','nrt'),'2024-01-17',scope,[-6,34,-4,36],[])
            advanced=publish(conn,database,[revised],scope)
            assert advanced['best_available']!=first['best_available']
            raise RuntimeError('simulated crash before commit')
    with connect(database) as conn:
        current=conn.execute("SELECT release_id FROM release_aliases WHERE scope_key=%s AND alias='best_available'",(scope,)).fetchone()
    assert str(current['release_id'])==first['best_available']


def test_reject_incomplete_serving_membership(database,scope):
    first,pid=publish_points(database,scope,'nrt',[-5])
    with pytest.raises(ValueError,match='count mismatch'):
        with connect(database) as conn:
            conn.execute('UPDATE data_partitions SET row_count=99 WHERE id=%s',(pid,))
            publish(conn,database,[pid],scope)
    assert count(database,first['best_available'])==1


def test_old_fetch_finishing_late_cannot_replace_newer_snapshot(database,scope):
    _,old_pid=publish_points(database,scope,'nrt',[-5])
    newer,_=publish_points(database,scope,'nrt',[-5,-4.8])
    with connect(database) as conn:
        result=publish(conn,database,[old_pid],scope,observed_at=now()-timedelta(hours=1))
    assert result==newer and count(database,result['best_available'])==2
