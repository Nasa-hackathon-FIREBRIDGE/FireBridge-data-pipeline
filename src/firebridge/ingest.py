from collections import defaultdict
import csv
from datetime import timedelta
import io
from pathlib import Path
from uuid import uuid4
import duckdb
from psycopg.types.json import Jsonb
from .catalog import FEEDS, source_id, area
from .db import connect
from .http import get, FetchError
from .normalize import normalize, parse_csv
from .publish import run, detection_partition, publish
from .store import Store, asset
from .util import utc, days, digest, now, uid


def assert_lease(conn, task):
    if task is None: return
    row=conn.execute("SELECT status,lease_token,lease_expires_at FROM ingest_tasks WHERE id=%s FOR UPDATE",(task['id'],)).fetchone()
    if not row or row['status']!='running' or row['lease_token']!=task['lease_token'] or row['lease_expires_at']<=now():
        raise FetchError('lease_lost')


def refresh_availability(settings, client=None):
    if not settings.firms_key: raise FetchError('missing_firms_key',blocked=True)
    # Credentials never enter asset URLs, request ledgers or error strings.
    url=f"https://firms.modaps.eosdis.nasa.gov/api/data_availability/csv/{settings.firms_key}/ALL"
    body,_=get(settings,url,client=client,firms=True)
    reader=csv.DictReader(io.StringIO(body.decode('utf-8-sig')))
    if not {'data_id','min_date','max_date'}.issubset(reader.fieldnames or []):
        raise FetchError('invalid_availability_schema',blocked=True)
    parsed=[]
    for row in reader:
        if row['data_id'] not in FEEDS: continue
        lo,hi=utc(row['min_date']),utc(row['max_date'])+timedelta(days=1)
        if hi<=lo: raise FetchError('invalid_availability_interval',blocked=True)
        parsed.append((row['data_id'],lo,hi))
    if not parsed: raise FetchError('empty_availability_catalog')
    obj=Store(settings.data_dir).put([body],'.csv')
    with connect(settings) as conn:
        aid=asset(conn,obj,'raw-modis_sp','FIRMS:data_availability','https://firms.modaps.eosdis.nasa.gov/api/data_availability/')
        checked=now()
        found={f for f,_,_ in parsed}
        for feed,(platforms,stream) in FEEDS.items():
            limits=next(((lo,hi) for f,lo,hi in parsed if f==feed), (None,None))
            for platform in platforms:
                conn.execute("""INSERT INTO source_availability VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                 (feed,source_id(platform,stream),checked,*limits,'available' if feed in found else 'unknown',aid,
                  Jsonb({'scope':'provider catalog range; not per-AOI clear-sky coverage'})))
            conn.execute("UPDATE ingestion_feeds SET verified_at=%s,state=%s WHERE id=%s",
                         (checked,'active' if feed in found else 'unverified',feed))
    return {'feeds_verified':len(parsed),'checked_at':checked.isoformat()}


def availability_gate(settings, feed, start, end, client=None):
    with connect(settings) as conn:
        row=conn.execute("SELECT * FROM source_availability WHERE feed_id=%s ORDER BY checked_at DESC LIMIT 1",(feed,)).fetchone()
    if not row or row['checked_at']<now()-timedelta(hours=6):
        refresh_availability(settings,client)
        with connect(settings) as conn:
            row=conn.execute("SELECT * FROM source_availability WHERE feed_id=%s ORDER BY checked_at DESC LIMIT 1",(feed,)).fetchone()
    if not row or row['status']!='available': raise FetchError('provider_availability_unknown',retry_seconds=21600)
    if start<row['available_start']:
        raise FetchError('historical_archive_required',blocked=True)
    if end>row['available_end_exclusive']:
        raise FetchError('outside_provider_available_dates',retry_seconds=86400)


def firms(settings, request, task=None, client=None):
    feed=request['feed']; platforms,stream=FEEDS[feed]
    start,end=utc(request['start']),utc(request['end_exclusive'])
    window=list(days(start,end))
    if len(window)>5: raise ValueError('FIRMS requests support at most five days')
    if not settings.firms_key: raise FetchError('missing_firms_key',blocked=True)
    bbox=request['bbox']; scope=request['scope_key']
    # Central registered scopes only; global collection should use local archives or a reviewed shard plan.
    if (bbox[2]-bbox[0])*(bbox[3]-bbox[1])>100:
        raise FetchError('scheduled_bbox_too_large',blocked=True)
    availability_gate(settings,feed,start,end,client)
    subscription=task['subscription_id'] if task else request['subscription_id']
    fetch_id=uuid4(); key=digest(request)
    with connect(settings) as conn:
        assert_lease(conn,task)
        attempt=conn.execute("SELECT coalesce(max(attempt),0)+1 AS n FROM fetch_runs WHERE subscription_id=%s AND request_key=%s",(subscription,key)).fetchone()['n']
        rid=run(conn,'firms',str(fetch_id),request,'provider:FIRMS')
        conn.execute("""INSERT INTO fetch_runs(id,subscription_id,pipeline_run_id,request_key,attempt,query_start,
          query_end_exclusive,query_basis,sanitized_request,status,started_at)
          VALUES (%s,%s,%s,%s,%s,%s,%s,'observation_time',%s,'running',now())""",
          (fetch_id,subscription,rid,key,attempt,start,end,Jsonb(request)))
    raw_obj=None
    try:
        bounds=','.join(map(str,bbox))
        url=f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{settings.firms_key}/{feed}/{bounds}/{len(window)}/{start.date()}"
        fetched=now()
        body,_=get(settings,url,client=client,firms=True)
        raw_obj=Store(settings.data_dir).put([body],'.csv')
        try: rows,excluded=parse_csv(body,stream,platforms)
        except (ValueError,UnicodeError,csv.Error): raise FetchError('invalid_firms_payload',blocked=True) from None
        grouped=defaultdict(list)
        for r in rows:
            if not start<=r['acquired_at']<end: raise FetchError('record_outside_request',blocked=True)
            grouped[(r['source_id'],r['acquired_at'].date())].append(r)
        with connect(settings) as conn:
            assert_lease(conn,task)
            aid=asset(conn,raw_obj,'raw-'+feed.lower(),key,'https://firms.modaps.eosdis.nasa.gov/api/area/',
                      {"request":request,"excluded_rt_urt":excluded},start,end)
            conn.execute("INSERT INTO fetch_assets VALUES (%s,%s,%s,'1')",(fetch_id,aid,'payload' if rows else 'empty_result'))
            pids=[]
            for day in window:
                for platform in platforms:
                    sid=source_id(platform,stream)
                    pids.append(detection_partition(conn,settings,rid,aid,sid,day,scope,bbox,grouped[(sid,day.date())],fetched_at=fetched))
            releases=publish(conn,settings,pids,scope,reason='provider_revision',observed_at=fetched)
            conn.execute("UPDATE fetch_runs SET status='complete',enumeration_complete=true,page_count=1,record_count=%s,completed_at=now(),max_observation_at=%s,http_status=200 WHERE id=%s",
                         (len(rows),max((r['acquired_at'] for r in rows),default=None),fetch_id))
            conn.execute("UPDATE pipeline_runs SET status='succeeded',finished_at=now(),output_manifest_uri=%s WHERE id=%s",(raw_obj.uri,rid))
            for stage in ('fetch','normalize','publish'):
                # This is the end of a completed window, NOT a claim that every earlier date succeeded.
                conn.execute("""INSERT INTO ingestion_checkpoints VALUES (%s,%s,'completed_window',%s,%s,%s,now(),1)
                  ON CONFLICT(subscription_id,stage) DO UPDATE SET committed_until=GREATEST(ingestion_checkpoints.committed_until,EXCLUDED.committed_until),
                  cursor_json=EXCLUDED.cursor_json,last_success_run_id=EXCLUDED.last_success_run_id,updated_at=now(),generation=ingestion_checkpoints.generation+1""",
                  (subscription,stage,end,Jsonb({'window_start':start.isoformat(),'window_end':end.isoformat(),'contiguous':False}),fetch_id))
            conn.execute("UPDATE ingestion_gaps SET status='resolved',resolved_by_run_id=%s WHERE subscription_id=%s AND gap_start>=%s AND gap_end_exclusive<=%s AND status IN ('open','retrying')",(fetch_id,subscription,start,end))
        return {'rows':len(rows),'excluded_rt_urt':excluded,'releases':releases,'fetch_id':str(fetch_id)}
    except Exception as exc:
        code=exc.code if isinstance(exc,FetchError) else 'normalization_or_publication_failed'
        with connect(settings) as conn:
            conn.execute("UPDATE fetch_runs SET status='failed',completed_at=now(),error_code=%s WHERE id=%s",(code,fetch_id))
            conn.execute("UPDATE pipeline_runs SET status='failed',finished_at=now(),error_code=%s WHERE id=%s",(code,rid))
            if raw_obj:
                aid=asset(conn,raw_obj,'raw-'+feed.lower(),key,'https://firms.modaps.eosdis.nasa.gov/api/area/',{'request':request},start,end)
                conn.execute("UPDATE assets SET validation_status='quarantined' WHERE id=%s AND NOT EXISTS(SELECT 1 FROM partition_assets WHERE asset_id=%s)",(aid,aid))
                conn.execute("INSERT INTO quality_issues(id,pipeline_run_id,asset_id,rule_id,severity,status,affected_count,sample_locator,explanation) VALUES (%s,%s,%s,%s,'blocking','open',1,'{}','Snapshot rejected; previous release retained')",(uuid4(),rid,aid,code))
            gap=uid([subscription,start,end])
            conn.execute("""INSERT INTO ingestion_gaps(id,subscription_id,gap_start,gap_end_exclusive,kind,status,discovered_at,last_attempt_at,evidence)
              VALUES (%s,%s,%s,%s,'fetch_failed','open',now(),now(),%s) ON CONFLICT(id) DO UPDATE SET status='open',last_attempt_at=now(),evidence=EXCLUDED.evidence""",
              (gap,subscription,start,end,Jsonb({'error_code':code})))
        raise


def import_modis(settings, path, scope, bbox, start, end):
    """Import the complete, already-audited MCD14ML Parquet selection one UTC day at a time."""
    start,end=utc(start),utc(end)
    window=list(days(start,end))
    path=Path(path).resolve(); store=Store(settings.data_dir)
    obj=store.file(path)
    db=duckdb.connect()
    db.execute("SET threads=2")
    schema={r[0] for r in db.execute('DESCRIBE SELECT * FROM read_parquet(?)',[str(path)]).fetchall()}
    required={'latitude','longitude','acq_date','acq_time','satellite','confidence','daynight','source_file','source_row','stream'}
    if not required<=schema: raise ValueError('Expected audited MCD14ML EDA Parquet with provenance columns')
    stats=db.execute("SELECT min(acq_date),max(acq_date),count(DISTINCT acq_date),count(*) FILTER(WHERE stream!='standard') FROM read_parquet(?)",[str(path)]).fetchone()
    if str(stats[0])>str(start.date()) or str(stats[1])<str((end-timedelta(days=1)).date()) or stats[3]:
        raise ValueError('Requested dates/stream not covered by this audited input')
    config={'scope_key':scope,'bbox':bbox,'start':start.isoformat(),'end_exclusive':end.isoformat(),'input_sha256':obj.sha256}
    with connect(settings) as conn:
        area(conn,scope,bbox)
        rid=run(conn,'local-modis',digest(config),config,obj.uri)
        aid=asset(conn,obj,'raw-modis_sp',path.name,str(path),{'format':'audited MCD14ML Parquet','originals':'data/external/modis_2024_2025'},start,end)
    pids=[]; count=0
    try:
        for day in window:
            w,s,e,n=bbox
            table=db.execute("""SELECT * FROM read_parquet(?) WHERE acq_date=? AND longitude BETWEEN ? AND ? AND latitude BETWEEN ? AND ?""",
                              [str(path),str(day.date()),w,e,s,n]).fetch_arrow_table()
            grouped=defaultdict(list)
            for row in table.to_pylist():
                item=normalize(row,'standard',['Terra','Aqua'])
                grouped[item['source_id']].append(item)
            with connect(settings) as conn:
                for platform in ['Terra','Aqua']:
                    sid=source_id(platform,'standard')
                    pids.append(detection_partition(conn,settings,rid,aid,sid,day,scope,bbox,grouped[sid]))
            count+=table.num_rows
            if day.day==1: print(f"Validated through {day.date()}: {count:,} input records",flush=True)
        with connect(settings) as conn:
            releases=publish(conn,settings,pids,scope)
            conn.execute("UPDATE pipeline_runs SET status='succeeded',finished_at=now(),output_manifest_uri=%s WHERE id=%s",(obj.uri,rid))
        return {'input_rows':count,'partitions':len(pids),'releases':releases,'scope_key':scope}
    except Exception:
        with connect(settings) as conn:
            conn.execute("UPDATE pipeline_runs SET status='failed',finished_at=now(),error_code='local_import_failed' WHERE id=%s",(rid,))
        raise
    finally:
        db.close()
