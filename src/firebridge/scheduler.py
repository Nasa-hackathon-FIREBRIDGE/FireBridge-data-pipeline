"""Durable database queue: SKIP LOCKED claims, leases, retries and bounded schedules."""
from datetime import timedelta
import random
import signal
import time
from uuid import uuid4
from psycopg.types.json import Jsonb
from .catalog import FEEDS, area
from .db import connect
from .http import FetchError
from .util import now, utc, days, digest, uid, canonical


def assert_owner(conn, owner):
    current=conn.execute('SELECT owner FROM orchestration_control WHERE singleton FOR SHARE').fetchone()['owner']
    if current!=owner:
        raise RuntimeError(f'Ingestion is owned by {current}; {owner} scheduler is disabled')


def enqueue(conn, kind, request, key, subscription=None, available_at=None):
    # One active task per semantic request, even across schedule cycles or dispatchers.
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",('enqueue:'+digest([kind,str(subscription),request]),))
    active=conn.execute("""SELECT id FROM ingest_tasks WHERE kind=%s AND subscription_id IS NOT DISTINCT FROM %s
      AND request=%s AND status IN ('queued','running') LIMIT 1""",(kind,subscription,Jsonb(request))).fetchone()
    if active:return active['id']
    task_id=uid(['task',key])
    conn.execute("""INSERT INTO ingest_tasks(id,subscription_id,kind,request,dedupe_key,status,available_at)
      VALUES (%s,%s,%s,%s,%s,'queued',%s) ON CONFLICT(dedupe_key) DO NOTHING""",
      (task_id,subscription,kind,Jsonb(request),key,available_at or now()))
    conn.execute("UPDATE ingest_tasks SET orchestrator=(SELECT owner FROM orchestration_control WHERE singleton) WHERE id=%s AND status='queued'",(task_id,))
    return task_id


def subscribe(settings, feed, scope, bbox, history_start, *, enabled=False, mode='incremental', end=None, config=None):
    if feed not in FEEDS and feed not in ('WEATHER_ERA5','WEATHER_RECENT','CMR','NEWS_RSS'): raise ValueError('Unknown feed')
    config=dict(config or {},bbox=bbox)
    if feed in FEEDS and (bbox[2]-bbox[0])*(bbox[3]-bbox[1])>100: raise ValueError('Register smaller scopes; global live queries require a reviewed shard plan')
    if feed=='LANDSAT_NRT' and not config.get('landsat_us_canada_acknowledged'):
        raise ValueError('LANDSAT_NRT serves US/Canada only; explicitly acknowledge supported geography')
    history_start=utc(history_start)
    if end is not None and utc(end)<=history_start:raise ValueError('Invalid subscription interval')
    interval=3600; overlap=3*86400
    if mode=='reconciliation': interval=86400;overlap=(210 if feed.endswith('_SP') else 14)*86400
    if feed=='WEATHER_ERA5': interval=86400;overlap=30*86400
    if feed=='CMR': interval=21600;overlap=7*86400
    if feed=='NEWS_RSS': interval=21600;overlap=7*86400
    signature=digest([config,history_start.isoformat(),utc(end).isoformat() if end else None]); sid=uid([feed,scope,mode,signature])
    with connect(settings) as conn:
        aid=area(conn,scope,bbox)
        # A scope label is a geometry identity, never silently reuse it for another bbox.
        if conn.execute('SELECT 1 FROM ingestion_subscriptions WHERE scope_key=%s AND area_id<>%s',(scope,aid)).fetchone():
            raise ValueError('Scope already registered with a different geometry')
        existing=conn.execute("""SELECT id FROM ingestion_subscriptions WHERE feed_id=%s AND scope_key=%s AND mode=%s
          AND history_start=%s AND fixed_end_exclusive IS NOT DISTINCT FROM %s AND request_config=%s""",
          (feed,scope,mode,history_start,utc(end) if end else None,Jsonb(config))).fetchone()
        if existing:
            if enabled:conn.execute('UPDATE ingestion_subscriptions SET enabled=true,next_due_at=now() WHERE id=%s',(existing['id'],))
            return str(existing['id'])
        conn.execute("""INSERT INTO ingestion_subscriptions(id,feed_id,area_id,scope_key,mode,interval_seconds,overlap_seconds,
          history_start,fixed_end_exclusive,request_config,config_sha256,enabled,next_due_at)
          VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now()) ON CONFLICT(id) DO NOTHING""",
          (sid,feed,aid,scope,mode,interval,overlap,history_start,utc(end) if end else None,Jsonb(config),signature,enabled))
    return str(sid)


def schedule(settings, owner='local'):
    total=0
    with connect(settings) as conn:
        assert_owner(conn,owner)
        subs=conn.execute("SELECT * FROM ingestion_subscriptions WHERE enabled AND NOT planning_complete AND next_due_at<=now() ORDER BY next_due_at FOR UPDATE SKIP LOCKED LIMIT 20").fetchall()
        for sub in subs:
            feed=sub['feed_id']; config=sub['request_config']; clock=now(); today=utc(clock.date())
            end=sub['fixed_end_exclusive'] or today+timedelta(days=1)
            if sub['mode']=='backfill':
                # Backfills progress even across failed days: gaps and failed tasks remain explicit.
                pending=conn.execute("SELECT max((request->>'end_exclusive')::timestamptz) AS hi FROM ingest_tasks WHERE subscription_id=%s",(sub['id'],)).fetchone()['hi']
                start=pending or sub['history_start']
                end=min(end,start+timedelta(days=31))
                cycle='backfill'
            else:
                start=max(sub['history_start'],today-timedelta(seconds=sub['overlap_seconds']-86400))
                cycle=str(int(clock.timestamp())//sub['interval_seconds'])
            if feed=='WEATHER_ERA5':
                end=min(end,today-timedelta(days=5))
            if feed.endswith('_SP'):
                available=conn.execute("SELECT available_end_exclusive FROM source_availability WHERE feed_id=%s AND status='available' ORDER BY checked_at DESC LIMIT 1",(feed,)).fetchone()
                if available:
                    end=min(end,available['available_end_exclusive'])
                    if sub['mode']!='backfill':start=max(sub['history_start'],end-timedelta(days=210))
                else:
                    enqueue(conn,'availability',{},'availability:'+str(int(clock.timestamp())//21600))
                    conn.execute("UPDATE ingestion_subscriptions SET next_due_at=now()+interval '10 minutes' WHERE id=%s",(sub['id'],))
                    continue
            if feed in FEEDS:
                enqueue(conn,'availability',{},'availability:'+str(int(clock.timestamp())//21600))
            if start<end:
                if feed in FEEDS:
                    for day in days(start,end):
                        request=dict(feed=feed,scope_key=sub['scope_key'],bbox=config['bbox'],start=day.isoformat(),end_exclusive=(day+timedelta(days=1)).isoformat())
                        enqueue(conn,'firms',request,digest([str(sub['id']),cycle,request]),sub['id']);total+=1
                elif feed.startswith('WEATHER'):
                    w,s,e,n=config['bbox']
                    # At most 31-day chunks; weather is explicitly a point sample.
                    cursor=start
                    while cursor<end:
                        hi=min(cursor+timedelta(days=31),end)
                        request=dict(scope_key=sub['scope_key'],latitude=config.get('latitude',(s+n)/2),longitude=config.get('longitude',(w+e)/2),
                         data_kind='reanalysis' if feed=='WEATHER_ERA5' else 'model_current',start=cursor.isoformat(),end_exclusive=hi.isoformat())
                        enqueue(conn,'weather',request,digest([str(sub['id']),cycle,request]),sub['id']);total+=1;cursor=hi
                elif feed=='NEWS_RSS':
                    request=dict(config,scope_key=sub['scope_key'],start=start.isoformat(),end_exclusive=end.isoformat())
                    enqueue(conn,'news',request,digest([str(sub['id']),cycle,request]),sub['id']);total+=1
                else:
                    if 'collection_concept_id' not in config:raise ValueError('CMR subscription requires a pinned collection_concept_id')
                    request=dict(config,scope_key=sub['scope_key'],start=start.isoformat(),end_exclusive=end.isoformat())
                    if sub['mode']!='backfill':
                        request['start']=sub['history_start'].isoformat()
                        request['updated_since']=(clock-timedelta(days=7)).isoformat()
                    enqueue(conn,'cmr',request,digest([str(sub['id']),cycle,request]),sub['id']);total+=1
            conn.execute("UPDATE ingestion_subscriptions SET next_due_at=%s,planning_complete=%s WHERE id=%s",
                         (clock+timedelta(seconds=sub['interval_seconds']),sub['mode']=='backfill' and end>=(sub['fixed_end_exclusive'] or today+timedelta(days=1)),sub['id']))
        # Retry older known gaps, including dates outside the rolling windows.
        gaps=conn.execute("""SELECT g.*,s.feed_id,s.scope_key,s.request_config FROM ingestion_gaps g
         JOIN ingestion_subscriptions s ON s.id=g.subscription_id WHERE s.enabled AND g.status='open'
         AND (g.retry_after IS NULL OR g.retry_after<=now()) ORDER BY g.discovered_at FOR UPDATE OF g SKIP LOCKED LIMIT 20""").fetchall()
        for gap in gaps:
            if gap['feed_id'] not in FEEDS:continue
            request=dict(feed=gap['feed_id'],scope_key=gap['scope_key'],bbox=gap['request_config']['bbox'],start=gap['gap_start'].isoformat(),end_exclusive=gap['gap_end_exclusive'].isoformat())
            enqueue(conn,'firms',request,digest(['gap',str(gap['id']),str(now().date())]),gap['subscription_id'])
            conn.execute("UPDATE ingestion_gaps SET retry_after=now()+interval '1 day' WHERE id=%s",(gap['id'],))
    return total


def claim(settings):
    with connect(settings) as conn:
        assert_owner(conn,'local')
        # Exhausted/crashed final attempts become terminal, never stuck running forever.
        conn.execute("UPDATE ingest_tasks SET status='failed',error_code='lease_expired',completed_at=now() WHERE status='running' AND lease_expires_at<now() AND attempt>=max_attempts")
        row=conn.execute("""SELECT * FROM ingest_tasks WHERE attempt<max_attempts AND
          orchestrator='local' AND ((status='queued' AND available_at<=now()) OR (status='running' AND lease_expires_at<now()))
          ORDER BY CASE WHEN kind='availability' THEN 0 ELSE 1 END,available_at,created_at FOR UPDATE SKIP LOCKED LIMIT 1""").fetchone()
        if not row:return None
        return conn.execute("""UPDATE ingest_tasks SET status='running',attempt=attempt+1,lease_token=%s,
          lease_expires_at=now()+interval '20 minutes' WHERE id=%s RETURNING *""",(uuid4(),row['id'])).fetchone()


def process_one(settings):
    from .ingest import firms,refresh_availability
    from .weather import fetch_weather
    from .science import discover
    from .news import fetch_news
    task=claim(settings)
    if not task:return None
    try:
        if task['kind']=='firms': result=firms(settings,task['request'],task)
        elif task['kind']=='weather':result=fetch_weather(settings,task['request'],task)
        elif task['kind']=='availability':result=refresh_availability(settings)
        elif task['kind']=='news':result=fetch_news(settings,task['request'],task)
        else: result=discover(settings,task['request'],task)
        with connect(settings) as conn:
            conn.execute("UPDATE ingest_tasks SET status='succeeded',completed_at=now(),lease_expires_at=NULL,result=%s,error_code=NULL WHERE id=%s AND lease_token=%s",(Jsonb(result),task['id'],task['lease_token']))
        return {'task_id':str(task['id']),'status':'succeeded','result':result}
    except Exception as exc:
        code=exc.code if isinstance(exc,FetchError) else type(exc).__name__
        blocked=isinstance(exc,FetchError) and exc.blocked
        delay=max(getattr(exc,'retry_seconds',0),min(1800,30*2**(task['attempt']-1))+random.randint(0,15))
        status='blocked' if blocked else ('failed' if task['attempt']>=task['max_attempts'] else 'queued')
        # Budget/availability waits are not failed data attempts; don't exhaust retries by waiting.
        wait_only=code in ('local_rate_budget','provider_cooldown','outside_provider_available_dates','provider_availability_unknown')
        if wait_only:status='queued'
        with connect(settings) as conn:
            conn.execute("""UPDATE ingest_tasks SET status=%s,error_code=%s,available_at=%s,lease_expires_at=NULL,
              attempt=attempt-%s,completed_at=CASE WHEN %s IN ('failed','blocked') THEN now() ELSE NULL END
              WHERE id=%s AND lease_token=%s""",(status,code,now()+timedelta(seconds=delay),int(wait_only),status,task['id'],task['lease_token']))
            if blocked and task['subscription_id']:
                conn.execute("UPDATE ingestion_subscriptions SET enabled=false WHERE id=%s",(task['subscription_id'],))
        return {'task_id':str(task['id']),'status':status,'error_code':code}


def worker(settings, once=False):
    stopping=False
    def stop(*_):
        nonlocal stopping
        stopping=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    while not stopping:
        try:
            schedule(settings)
            result=process_one(settings)
            if result:print(canonical(result),flush=True)
            if once:return result
            if not result:time.sleep(settings.poll_seconds)
        except Exception as exc:
            print(canonical({'worker_error':type(exc).__name__}),flush=True)
            if once:raise
            time.sleep(settings.poll_seconds)
