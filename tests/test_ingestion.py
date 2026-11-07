from dataclasses import replace
from datetime import timedelta
import httpx
import pytest
from firebridge.catalog import source_id
from firebridge.db import connect
from firebridge.http import FetchError,get
from firebridge.ingest import firms
from firebridge.scheduler import subscribe
from firebridge.util import now,utc

HEADER='latitude,longitude,acq_date,acq_time,satellite,confidence,daynight,version\n'
pytestmark=pytest.mark.integration


def prepare(settings,scope):
    sid=subscribe(settings,'MODIS_NRT',scope,[-6,34,-4,36],'2024-01-17',mode='backfill',end='2024-01-18')
    with connect(settings) as conn:
        for platform in ['Terra','Aqua']:
            conn.execute("""INSERT INTO source_availability(feed_id,source_id,checked_at,available_start,available_end_exclusive,status,detail)
              VALUES ('MODIS_NRT',%s,now(),'2024-01-01','2025-01-01','available','{}')""",(source_id(platform,'nrt'),))
    return dict(feed='MODIS_NRT',scope_key=scope,bbox=[-6,34,-4,36],start='2024-01-17',end_exclusive='2024-01-18',subscription_id=sid)


def client(body,status=200):
    return httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(status,content=body)))


def test_firms_replay_and_bad_payload_preserves_release(database,scope):
    request=prepare(database,scope)
    data=(HEADER+'35,-5,2024-01-17,1200,Terra,80,D,6.1NRT\n').encode()
    with client(data) as c:a=firms(database,request,client=c)
    with client(data) as c:b=firms(database,request,client=c)
    assert a['releases']==b['releases']
    with client(b'<html>unauthorized</html>') as c:
        with pytest.raises(FetchError,match='invalid_firms_payload'):firms(database,request,client=c)
    with connect(database) as conn:
        assert conn.execute("SELECT count(*) AS n FROM ingestion_gaps WHERE subscription_id=%s AND status='open'",(request['subscription_id'],)).fetchone()['n']==1
        assert str(conn.execute("SELECT release_id FROM release_aliases WHERE scope_key=%s AND alias='best_available'",(scope,)).fetchone()['release_id'])==a['releases']['best_available']
    with client(HEADER.encode()) as c:empty=firms(database,request,client=c)
    assert empty['rows']==0
    with connect(database) as conn:
        assert conn.execute('SELECT count(*) AS n FROM serving.detections WHERE release_id=%s',(empty['releases']['best_available'],)).fetchone()['n']==0
        assert conn.execute("SELECT count(*) AS n FROM ingestion_gaps WHERE subscription_id=%s AND status='open'",(request['subscription_id'],)).fetchone()['n']==0
        assert conn.execute("SELECT committed_until FROM ingestion_checkpoints WHERE subscription_id=%s AND stage='publish'",(request['subscription_id'],)).fetchone()['committed_until']==utc('2024-01-18')


def test_http_redaction_and_bounds(database):
    with client(b'no',403) as c:
        with pytest.raises(FetchError) as error:get(database,'https://example.test/secret-token',client=c)
        assert str(error.value)=='http_403' and error.value.blocked
    with client(b'123456') as c:
        with pytest.raises(FetchError,match='payload_too_large'):get(replace(database,max_bytes=3),'https://example.test',client=c)
