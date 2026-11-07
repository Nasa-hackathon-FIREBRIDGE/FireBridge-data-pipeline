from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
import json
import httpx
import pytest
from firebridge.db import connect
from firebridge.scheduler import enqueue,claim,schedule,subscribe
from firebridge.util import utc,now
from firebridge.weather import VARIABLES,fetch_weather,parse


def payload():
    start=utc('2024-01-17')
    p={'latitude':35.0,'longitude':-5.0,'elevation':100,'hourly_units':{},'hourly':{'time':[int((start+timedelta(hours=i)).timestamp()) for i in range(24)]}}
    for var,(unit,_,lo,hi) in VARIABLES.items():
        p['hourly_units'][var]=unit;p['hourly'][var]=[(lo+hi)/2]*24
    p['hourly']['precipitation']=[0]*24;p['hourly']['temperature_2m'][0]=None
    return p


def test_weather_intervals_and_missingness():
    p=payload();rows=parse(p,utc('2024-01-17'),utc('2024-01-18'))
    precip=next(r for r in rows if r['variable']=='precipitation')
    assert precip['valid_start']==utc('2024-01-16T23:00:00') and precip['value']==0
    assert rows[0]['value'] is None and rows[0]['quality_status']=='missing'
    p['hourly']['time'].pop()
    with pytest.raises(ValueError):parse(p,utc('2024-01-17'),utc('2024-01-18'))


@pytest.mark.integration
def test_weather_release_replay(database,scope):
    req=dict(scope_key=scope,latitude=35,longitude=-5,start='2024-01-17',end_exclusive='2024-01-18')
    with httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,json=payload()))) as c:
        a=fetch_weather(database,req,client=c);b=fetch_weather(database,req,client=c)
    assert a['rows']==120 and a['missing']==1 and a['releases']==b['releases']
    with connect(database) as conn:
        values=conn.execute('SELECT count(*) AS n FROM serving.weather WHERE release_id=%s',(a['releases']['weather_historical'],)).fetchone()['n']
        assert values==120


@pytest.mark.integration
def test_queue_claims_and_crash_recovery(database,scope):
    with connect(database) as conn:
        ids=[enqueue(conn,'availability',{'fixture':scope,'i':i},scope+str(i)) for i in range(2)]
        assert enqueue(conn,'availability',{'fixture':scope,'i':0},scope+'0')==ids[0]
        assert enqueue(conn,'availability',{'fixture':scope,'i':0},scope+'next-cycle')==ids[0]
    with ThreadPoolExecutor(max_workers=2) as pool:tasks=list(pool.map(lambda _:claim(database),range(2)))
    assert len({t['id'] for t in tasks})==2
    with connect(database) as conn:
        conn.execute("UPDATE ingest_tasks SET lease_expires_at=now()-interval '1 second' WHERE id=%s",(tasks[0]['id'],))
    retry=claim(database)
    assert retry['id']==tasks[0]['id'] and retry['lease_token']!=tasks[0]['lease_token'] and retry['attempt']==2
    with connect(database) as conn:conn.execute("UPDATE ingest_tasks SET status='succeeded' WHERE id=ANY(%s)",(ids,))


@pytest.mark.integration
def test_disabled_subscriptions_do_not_schedule(database,scope):
    sid=subscribe(database,'MODIS_NRT',scope,[-6,34,-4,36],'2024-01-17',mode='backfill',end='2024-01-19')
    schedule(database)
    with connect(database) as conn:
        assert conn.execute('SELECT count(*) AS n FROM ingest_tasks WHERE subscription_id=%s',(sid,)).fetchone()['n']==0
