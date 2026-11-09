"""Offline archive audit, bounded resumable publication, isolated real-data benchmark.

No provider imports or requests. The acquisition ledger is opened read-only.
Database pipeline_runs and immutable partitions are the authoritative load ledger;
the JSON reports are operator-facing checkpoints, not process-health probes.
"""
from collections import Counter, defaultdict
from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
import fcntl
import json
import math
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import time
from uuid import uuid4

import duckdb
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.types.json import Jsonb
import pyarrow.parquet as pq

from .catalog import FEEDS, PLATFORMS, area, polygon, seed, source_id
from .db import connect, migrate
from .history import RAW_SCHEMA
from .lake import atomic_json, sha256
from .normalize import normalize
from .publish import publish, run, stream_detection_partition
from .store import Store, asset
from .util import canonical, days, digest, now, uid, utc

VERSION = 'history-serving-v1'
GIB = 1024**3
ID = re.compile(r'^[A-Z0-9_]+_\d{4}-\d{2}-\d{2}_\d{4}-\d{2}-\d{2}$')


@contextmanager
def locked(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as handle:
        try: fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: raise RuntimeError('Another archive preparation process is active') from None
        yield


def inventory(root):
    root=Path(root).resolve()
    with sqlite3.connect(f'file:{root}/ledger.sqlite3?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        rows=[dict(r) for r in db.execute('SELECT * FROM requests ORDER BY start,feed,id')]
    if not rows: raise ValueError('History inventory is empty')
    for r in rows:
        if not ID.fullmatch(r['id']) or r['feed'] not in FEEDS: raise ValueError('Invalid inventory identifier/feed')
        if r['id']!=f"{r['feed']}_{r['start']}_{r['end_exclusive']}": raise ValueError('Inventory bounds/id mismatch')
        if not 1<=len(list(days(r['start'],r['end_exclusive'])))<=5: raise ValueError('Invalid window bounds')
    return rows


def verify_window(root,r):
    if r['status']!='complete': raise ValueError('Acquisition window is not complete')
    receipt=json.loads((root/'receipts'/(r['id']+'.json')).read_text())
    for name in ('id','feed','start','end_exclusive','rows','raw_sha256','parquet_sha256'):
        if receipt.get(name)!=r[name]: raise ValueError('Receipt/inventory mismatch: '+name)
    if receipt.get('status')!='complete' or receipt.get('processing_stream')!=FEEDS[r['feed']][1]:
        raise ValueError('Invalid receipt state/stream')
    if r['feed']=='LANDSAT_NRT' and receipt.get('geography')!='US/Canada provider footprint':
        raise ValueError('Landsat geography not established')
    for directory,suffix,field in [('raw','.csv.gz','raw_sha256'),('parquet','.parquet','parquet_sha256'),('daily','.parquet','daily_sha256')]:
        path=root/directory/(r['id']+suffix)
        if not path.resolve().is_relative_to(root): raise ValueError('Archive path escapes root')
        if sha256(path)!=receipt.get(field): raise ValueError('Checksum mismatch: '+directory)
    parquet=pq.ParquetFile(root/'parquet'/(r['id']+'.parquet'))
    if parquet.metadata.num_rows!=r['rows'] or not parquet.schema_arrow.equals(RAW_SCHEMA):
        raise ValueError('Parquet schema/count mismatch')
    return receipt


def quality(root,r,db):
    """Vectorized inspection of every row; strict normalization runs during load."""
    platforms,stream=FEEDS[r['feed']]
    values=db.execute('''WITH x AS (SELECT *,try_cast(latitude AS DOUBLE) lat,
      try_cast(longitude AS DOUBLE) lon,try_cast(acq_date AS DATE) observation_day,
      try_cast(frp AS DOUBLE) f FROM read_parquet(?)) SELECT count(*) source_rows,
      count(*) FILTER(WHERE lat IS NULL OR lon IS NULL OR NOT isfinite(lat) OR NOT isfinite(lon)
        OR abs(lat)>90 OR abs(lon)>180 OR observation_day IS NULL OR observation_day<cast(? AS DATE) OR observation_day>=cast(? AS DATE)
        OR NOT regexp_full_match(lpad(acq_time,4,'0'),'([01][0-9]|2[0-3])[0-5][0-9]')
        OR acq_time IS NULL OR _archive IS DISTINCT FROM ? OR _stream IS DISTINCT FROM ?
        OR _platform IS NULL OR NOT list_contains(?,_platform)) invalid_support_rows,
      count(*) FILTER(WHERE frp IS NOT NULL AND trim(frp)<>'' AND
        (f IS NULL OR NOT isfinite(f) OR f<0)) invalid_frp_rows,
      min(observation_day)::VARCHAR first_observation_date,max(observation_day)::VARCHAR last_observation_date,
      list(DISTINCT version) versions,list(DISTINCT _platform) platforms,
      count(*) FILTER(WHERE daynight IS NULL OR upper(daynight) NOT IN ('D','N')
        OR (_platform IN ('Terra','Aqua') AND (try_cast(confidence AS DOUBLE) IS NULL
          OR NOT isfinite(try_cast(confidence AS DOUBLE)) OR try_cast(confidence AS DOUBLE) NOT BETWEEN 0 AND 100))
        OR (_platform IN ('SNPP','N20','N21') AND (confidence IS NULL OR lower(confidence) NOT IN ('l','n','h')))
        OR (_platform IN ('L8','L9') AND (confidence IS NULL OR upper(confidence) NOT IN ('L','M','H')))
        OR (_platform IN ('Terra','Aqua','SNPP','N20','N21') AND
          ((scan IS NOT NULL AND trim(scan)<>'' AND (try_cast(scan AS DOUBLE) IS NULL OR NOT isfinite(try_cast(scan AS DOUBLE)) OR try_cast(scan AS DOUBLE)<=0))
          OR (track IS NOT NULL AND trim(track)<>'' AND (try_cast(track AS DOUBLE) IS NULL OR NOT isfinite(try_cast(track AS DOUBLE)) OR try_cast(track AS DOUBLE)<=0))))) invalid_native_rows
      FROM x''',[str(root/'parquet'/(r['id']+'.parquet')),r['start'],r['end_exclusive'],r['id'],stream,platforms]).fetchone()
    keys=('rows','invalid_support_rows','invalid_frp_rows','first_observation_date','last_observation_date','versions','platforms','invalid_native_rows')
    result=dict(zip(keys,values))
    result['versions']=result['versions'] or []
    result['platforms']=result['platforms'] or []
    return result


def audit(settings,*,root=None,refresh=False):
    root=Path(root or settings.data_dir/'lake/history').resolve()
    out=settings.data_dir/'history-serving';out.mkdir(parents=True,exist_ok=True)
    records=inventory(root);signature=digest(records);started=time.monotonic()
    with locked(out/'audit.lock'),sqlite3.connect(out/'audit.sqlite3') as cache,duckdb.connect(config={'threads':1,'memory_limit':'512MB'}) as db:
        cache.execute('CREATE TABLE IF NOT EXISTS windows(id TEXT PRIMARY KEY,fingerprint TEXT,result TEXT)')
        results=[]
        for index,r in enumerate(records,1):
            try:
                files=[root/d/(r['id']+suffix) for d,suffix in [('raw','.csv.gz'),('parquet','.parquet'),('daily','.parquet'),('receipts','.json')]]
                fingerprint=digest([VERSION,r,[(str(p),p.stat().st_size,p.stat().st_mtime_ns) for p in files]])
                previous=cache.execute('SELECT result FROM windows WHERE id=? AND fingerprint=?',(r['id'],fingerprint)).fetchone()
                if previous and not refresh:
                    result=json.loads(previous[0])
                    if 'invalid_native_rows' not in result:
                        result.update(quality(root,r,db))
                        cache.execute('UPDATE windows SET result=? WHERE id=?',(canonical(result),r['id']));cache.commit()
                else:
                    verify_window(root,r)
                    result={'id':r['id'],'feed':r['feed'],'start':r['start'],'end_exclusive':r['end_exclusive'],
                      'status':'verified','raw_sha256':r['raw_sha256'],'parquet_sha256':r['parquet_sha256'],**quality(root,r,db)}
                    if result['invalid_support_rows']: raise ValueError('Invalid row support')
                    cache.execute('INSERT OR REPLACE INTO windows VALUES (?,?,?)',(r['id'],fingerprint,canonical(result)));cache.commit()
            except (ValueError,OSError,KeyError,duckdb.Error) as exc:
                result={'id':r['id'],'feed':r['feed'],'start':r['start'],'end_exclusive':r['end_exclusive'],'status':'failed','error':str(exc)[:200]}
            results.append(result)
            if index%25==0 or index==len(records):
                atomic_json(out/'audit-progress.json',{'state':'auditing','checked_windows':index,'total_windows':len(records),'updated_at':now(),'failed_windows':sum(x['status']=='failed' for x in results)})
                print(canonical({'audit_windows':index,'total':len(records)}),flush=True)
        coverage=[]
        for feed in sorted({r['feed'] for r in records}):
            spans=sorted((r for r in records if r['feed']==feed),key=lambda r:r['start'])
            gaps=[];overlaps=[];last=None
            for r in spans:
                if last and r['start']>last:gaps.append([last,r['start']])
                if last and r['start']<last:overlaps.append([r['start'],last])
                last=max(last or r['end_exclusive'],r['end_exclusive'])
            subset=[r for r in results if r['feed']==feed and r['status']=='verified']
            coverage.append({'feed':feed,'request_start':spans[0]['start'],'request_end_exclusive':last,
              'windows':len(spans),'verified_windows':len(subset),'source_rows':sum(r['rows'] for r in subset),
              'invalid_frp_rows':sum(r['invalid_frp_rows'] for r in subset),'empty_windows':sum(r['rows']==0 for r in subset),
              'blocking_native_rows':sum(r['invalid_native_rows'] for r in subset),
              'platforms':sorted({p for r in subset for p in (r['platforms'] or [])}),
              'versions':sorted({v for r in subset for v in (r['versions'] or []) if v is not None}),
              'gaps':gaps,'overlaps':overlaps,'geography':'US/Canada provider footprint' if feed=='LANDSAT_NRT' else 'world'})
        plan=json.loads((root/'plan.json').read_text()) if (root/'plan.json').exists() else {}
        report={'version':VERSION,'state':'passed' if all(r['status']=='verified' for r in results) and not any(c['overlaps'] for c in coverage) else 'failed',
          'checked_at':now(),'inventory_sha256':signature,'windows':len(records),'failed_windows':sum(r['status']=='failed' for r in results),
          'source_rows':sum(r.get('rows',0) for r in results),'coverage':coverage,'elapsed_seconds':round(time.monotonic()-started,2),
          'quality_policy':'Invalid FRP remains raw and becomes flagged NULL in native serving; all other invalid native rows block their window.',
          'observation_coverage':'unknown','provider_calls':0,'results':results}
        report['provider_gaps']=plan.get('provider_gaps',[])
        report['through_date_inclusive']=plan.get('through_date_inclusive')
        daily_paths=[str(root/'daily'/(r['id']+'.parquet')) for r in results if r['status']=='verified']
        report['platform_inventory']=[]
        if daily_paths:
            platform_rows=db.execute('''SELECT satellite,processing_stream,min(date_utc)::VARCHAR first_observed_date,
              max(date_utc)::VARCHAR last_observed_date,sum(source_rows)::BIGINT source_rows,
              sum(invalid_frp_rows)::BIGINT invalid_frp_rows FROM read_parquet(?) GROUP BY satellite,processing_stream
              ORDER BY satellite,processing_stream''',[daily_paths]).fetchall()
            report['platform_inventory']=[dict(zip(('satellite','processing_stream','first_observed_date','last_observed_date','source_rows','invalid_frp_rows'),row)) for row in platform_rows]
        report['oversized_windows_for_default_load']=[r['id'] for r in results if r.get('rows',0)>2_000_000]
        report['empty_modis_windows_requiring_collection_review']=[r['id'] for r in results if r['feed'].startswith('MODIS') and r.get('rows')==0]
        atomic_json(out/'audit.json',report)
        atomic_json(out/'audit-progress.json',{k:report[k] for k in ('state','checked_at','windows','failed_windows','source_rows','elapsed_seconds')})
        return report


def native_row(raw,feed):
    """Invalid optional FRP is retained explicitly, never converted to a number."""
    value=raw.get('frp');invalid=False
    if value is not None and str(value).strip():
        try: invalid=not math.isfinite(float(value)) or float(value)<0
        except ValueError: invalid=True
    row=normalize({**raw,'frp':None} if invalid else raw,FEEDS[feed][1],FEEDS[feed][0],allow_historical_collections=True)
    if row and invalid:
        row['native_fields']={**row['native_fields'],'frp_raw':str(value),'frp_quality':'invalid','normalization_policy':VERSION}
        row['record_sha256']=digest({'contract':'native-v1',**{k:v for k,v in row.items() if k not in ('record_sha256','native_record_key')}})
        row['native_record_key']=row['record_sha256']
    return row,invalid


def _spool(root,r,receipt,path,bbox,reserve_bytes):
    db=sqlite3.connect(path)
    db.execute('PRAGMA cache_size=-16384');db.execute('PRAGMA journal_mode=OFF')
    db.execute('CREATE TABLE rows(source TEXT,day TEXT,sha TEXT,body TEXT,PRIMARY KEY(source,day,sha)) WITHOUT ROWID')
    counts=Counter({key:0 for key in ('scanned_rows','invalid_frp_rows','excluded_realtime_rows','selected_rows')});seen_sources=set();w,s,e,n=bbox
    for batch in pq.ParquetFile(root/'parquet'/(r['id']+'.parquet')).iter_batches(batch_size=2048):
        if shutil.disk_usage(path.parent).free<reserve_bytes:
            db.close();raise RuntimeError('Disk reserve reached while normalizing')
        for raw in batch.to_pylist():
            native={k:raw[k] for k in receipt['native_columns']}
            try:row,invalid=native_row(native,r['feed'])
            except ValueError as exc:raise ValueError(f"Native validation at row {raw['_source_row']}: {exc}") from None
            counts['scanned_rows']+=1;counts['invalid_frp_rows']+=int(invalid)
            if row is None:counts['excluded_realtime_rows']+=1;continue
            if not utc(r['start'])<=row['acquired_at']<utc(r['end_exclusive']):raise ValueError('Row outside archive dates')
            seen_sources.add(row['source_id'])
            if not(w<=row['longitude']<=e and s<=row['latitude']<=n):continue
            counts['selected_rows']+=1
            db.execute('INSERT OR IGNORE INTO rows VALUES (?,?,?,?)',(row['source_id'],str(row['acquired_at'].date()),row['record_sha256'],canonical(row)))
        db.commit()
    if counts['scanned_rows']!=receipt['rows']:raise ValueError('Scanned row count mismatch')
    counts['unique_rows']=db.execute('SELECT count(*) FROM rows').fetchone()[0]
    counts['duplicate_rows']=counts['selected_rows']-counts['unique_rows']
    return db,dict(counts),seen_sources


def _space(settings,reserve_bytes,max_database_bytes,expected_growth=0):
    if shutil.disk_usage(settings.data_dir).free<reserve_bytes+expected_growth:raise RuntimeError('Disk reserve reached')
    with connect(settings) as db:
        size=db.execute('SELECT pg_database_size(current_database()) AS n').fetchone()['n']
    if size+expected_growth>=max_database_bytes:raise RuntimeError('Database size budget reached')
    return size


def window_spec(r,scope,bbox):
    footprint=None
    if r['feed']=='LANDSAT_NRT':
        if bbox!=[-180,-90,180,90]:raise ValueError('Landsat history import requires its complete provider footprint; regional clipping is not implemented')
        scope=scope if scope.endswith('-landsat-us-canada') else scope+'-landsat-us-canada'
        footprint='US/Canada provider footprint; not global observation coverage'
    spec={'contract':VERSION,'request_id':r['id'],'raw_sha256':r['raw_sha256'],'parquet_sha256':r['parquet_sha256'],
      'scope_key':scope,'bbox':bbox,'start':r['start'],'end_exclusive':r['end_exclusive']}
    return spec,scope,footprint


def load_window(settings,root,r,scope,bbox,*,reserve_bytes=16*GIB,max_database_bytes=100*GIB):
    """One verified window; commits reusable day partitions, atomically publishes last."""
    receipt=verify_window(root,r)  # Explicit replays rehash; batch resumes skip completed keys.
    spec,scope,footprint=window_spec(r,scope,bbox)
    key=digest(spec);store=Store(settings.data_dir)
    with connect(settings) as db:
        previous=db.execute("SELECT status,output_manifest_uri FROM pipeline_runs WHERE id=%s",(uid(['history-load',key]),)).fetchone()
        if previous and previous['status']=='succeeded':
            manifest_path=store.resolve(previous['output_manifest_uri'])
            if sha256(manifest_path)!=manifest_path.stem:raise ValueError('Completed load receipt checksum changed')
            result=json.loads(manifest_path.read_text())
            for pid in result['partition_ids']:
                member=db.execute('SELECT p.row_count,(SELECT count(*) FROM partition_detections WHERE partition_id=p.id) n FROM data_partitions p WHERE p.id=%s',(pid,)).fetchone()
                if not member or member['row_count']!=member['n']:raise ValueError('Completed load membership changed')
            return {**result,'reused':True}
        area(db,scope,bbox)
        obj=store.file(root/'raw'/(r['id']+'.csv.gz'))
        aid=asset(db,obj,'raw-'+r['feed'].lower(),r['id'],'NASA FIRMS history:'+r['id'],receipt,utc(r['start']),utc(r['end_exclusive']))
        rid=run(db,'history-load',key,spec,obj.uri)
    started=time.monotonic();partition_ids=[]
    try:
        _space(settings,reserve_bytes,max_database_bytes)
        stage=settings.data_dir/'staging';stage.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='history-spool-',dir=stage) as temp:
            spool,counts,sources=_spool(root,r,receipt,Path(temp)/'rows.sqlite3',bbox,reserve_bytes)
            try:
                allowed,stream=FEEDS[r['feed']]
                if r['feed'].startswith('MODIS'):
                    collections={sid.split('-c')[1].split('-')[0] for sid in sources}
                    if not collections:raise ValueError('Empty MODIS window has no verified collection identity')
                    sources={source_id(p,stream,c) for p in allowed for c in collections}
                else:sources={source_id(p,stream) for p in allowed}
                for day in days(r['start'],r['end_exclusive']):
                    for source in sorted(sources):
                        count=spool.execute('SELECT count(*) FROM rows WHERE source=? AND day=?',(source,str(day.date()))).fetchone()[0]
                        # Conservative preflight allowance, not a claim of exact storage cost.
                        _space(settings,reserve_bytes,max_database_bytes,expected_growth=count*4096)
                        def rows():
                            for (body,) in spool.execute('SELECT body FROM rows WHERE source=? AND day=? ORDER BY sha',(source,str(day.date()))):
                                row=json.loads(body);row['acquired_at']=utc(row['acquired_at']);yield row
                        with connect(settings) as db:
                            db.execute("SET LOCAL lock_timeout='10s'");db.execute("SET LOCAL statement_timeout='15min'")
                            partition_ids.append(str(stream_detection_partition(db,settings,rid,aid,source,day,scope,bbox,rows,count,fetched_at=utc(receipt['completed_at']),provider_footprint=footprint)))
            finally:spool.close()
        with connect(settings) as db:
            releases=publish(db,settings,partition_ids,scope,reason='history_import',observed_at=utc(receipt['completed_at']))
            result={**spec,**counts,'partition_ids':partition_ids,'releases':releases,'elapsed_seconds':round(time.monotonic()-started,3),'reused':False}
            manifest=store.json(result)
            db.execute("UPDATE pipeline_runs SET status='succeeded',finished_at=now(),output_manifest_uri=%s WHERE id=%s",(manifest.uri,rid))
            db.execute("UPDATE quality_issues SET status='resolved',resolution_note='Window successfully retried and published' WHERE pipeline_run_id=%s AND rule_id='history-load-failed' AND status='open'",(rid,))
            if counts.get('invalid_frp_rows'):
                db.execute("""INSERT INTO quality_issues(id,pipeline_run_id,asset_id,rule_id,severity,status,affected_count,sample_locator,explanation)
                  VALUES (%s,%s,%s,'invalid-frp','warning','accepted',%s,%s,%s) ON CONFLICT DO NOTHING""",
                  (uid([str(rid),'invalid-frp']),rid,aid,counts['invalid_frp_rows'],Jsonb({'archive':r['id']}),'Raw FRP retained; invalid optional measurement represented as NULL with explicit native_fields quality flag.'))
        return result
    except Exception as exc:
        with connect(settings) as db:
            db.execute("UPDATE pipeline_runs SET status='failed',finished_at=now(),error_code='history_load_failed' WHERE id=%s",(rid,))
            db.execute("""INSERT INTO quality_issues(id,pipeline_run_id,asset_id,rule_id,severity,status,affected_count,sample_locator,explanation)
              VALUES (%s,%s,%s,'history-load-failed','blocking','open',1,%s,%s) ON CONFLICT DO NOTHING""",
              (uid([str(rid),'failure']),rid,aid,Jsonb({'archive':r['id']}),type(exc).__name__+': window rejected; previous release retained'))
        raise


def load(settings,*,root=None,scope='global',bbox=None,request_ids=None,max_windows=3,max_rows_per_window=2_000_000,reserve_bytes=16*GIB,max_database_bytes=100*GIB):
    root=Path(root or settings.data_dir/'lake/history').resolve();bbox=bbox or [-180,-90,180,90];polygon(bbox)
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}',scope):raise ValueError('Invalid scope key')
    if not 1<=max_windows<=50 or not 1<=max_rows_per_window<=10_000_000:raise ValueError('Invalid batch limit')
    all_records=inventory(root);byid={r['id']:r for r in all_records}
    if request_ids and (len(request_ids)>max_windows or len(set(request_ids))!=len(request_ids)):raise ValueError('Explicit request list exceeds batch/contains duplicates')
    records=[byid[k] for k in request_ids] if request_ids else all_records
    out=settings.data_dir/'history-serving';out.mkdir(parents=True,exist_ok=True)
    with locked(out/('load-'+scope+'.lock')),connect(settings) as lock:
        if not lock.execute('SELECT pg_try_advisory_lock(hashtextextended(%s,0)) ok',('history-load:'+scope,)).fetchone()['ok']:
            raise RuntimeError('Another history loader owns this scope')
        completed={r['idempotency_key'] for r in lock.execute("SELECT idempotency_key FROM pipeline_runs WHERE stage='history-load' AND status='succeeded'")}
        lock.commit();results=[];skipped=0;before=_space(settings,reserve_bytes,max_database_bytes)
        for r in records:
            if not request_ids and digest(window_spec(r,scope,bbox)[0]) in completed:
                skipped+=1;continue
            atomic_json(out/('load-'+scope+'.json'),{'state':'loading','updated_at':now(),'current_request':r['id'],'results':results})
            try:
                if r['status']!='complete':raise ValueError('Incomplete acquisition window')
                if r['rows']>max_rows_per_window:raise ValueError('Window exceeds row budget; choose an explicit smaller benchmark or raise measured limit')
                result=load_window(settings,root,r,scope,bbox,reserve_bytes=reserve_bytes,max_database_bytes=max_database_bytes)
            except Exception as exc:
                atomic_json(out/('load-'+scope+'.json'),{'state':'failed','updated_at':now(),'current_request':r['id'],'error_type':type(exc).__name__,'results':results})
                raise
            results.append(result)
            atomic_json(out/('load-'+scope+'.json'),{'state':'loading','updated_at':now(),'results':results})
            if len([r for r in results if not r['reused']])>=max_windows:break
        with connect(settings) as db:
            db.execute('ANALYZE firebridge.detections,firebridge.partition_detections,firebridge.data_partitions,firebridge.release_partitions')
        result={'state':'complete_batch','updated_at':now(),'scope':scope,'scopes':sorted({r['scope_key'] for r in results}),'windows_visited':len(results),'skipped_completed_windows':skipped,
          'new_windows':sum(not r['reused'] for r in results),'database_bytes_before':before,
          'database_bytes_after':_space(settings,reserve_bytes,max_database_bytes),'results':results,'provider_calls':0}
        atomic_json(out/('load-'+scope+'.json'),result)
        return result


def benchmark(settings,*,root=None,max_rows_per_window=1_000_000,keep_database=False,build_analytics=True,reserve_bytes=16*GIB):
    """Representative real windows, isolated DB and files; never changes main aliases."""
    root=Path(root or settings.data_dir/'lake/history').resolve()
    report=json.loads((settings.data_dir/'history-serving/audit.json').read_text())
    records=inventory(root)
    if report['state']!='passed' or report['inventory_sha256']!=digest(records):raise ValueError('Run a successful current audit first')
    chosen=[]
    for feed in sorted({r['feed'] for r in records}):
        candidates=[r for r in report['results'] if r['feed']==feed and 0<r['rows']<=max_rows_per_window and not r['invalid_support_rows'] and not r.get('invalid_native_rows',0)]
        # Include both MODIS platforms rather than the pre-Aqua early mission.
        if feed.startswith('MODIS'):candidates=[r for r in candidates if {'Terra','Aqua'}<=set(r['platforms'])]
        if not candidates:raise ValueError('No bounded representative window for '+feed)
        candidates.sort(key=lambda r:(r['rows'],r['id']));chosen.append(candidates[len(candidates)//2]['id'])
    name='firebridge_history_benchmark_'+uuid4().hex[:12]
    target=replace(settings,database_url=make_conninfo(settings.database_url,dbname=name),data_dir=settings.data_dir/'history-serving/benchmarks'/name)
    target.data_dir.mkdir(parents=True,exist_ok=False)
    admin=make_conninfo(settings.database_url,dbname='postgres');started=time.monotonic()
    with psycopg.connect(admin,autocommit=True) as db:db.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    result={'state':'failed','database':name,'retained_database':keep_database,'provider_calls':0}
    try:
        migrate(target);seed(target)
        imported=load(target,root=root,scope='history-benchmark',request_ids=chosen,max_windows=len(chosen),max_rows_per_window=max_rows_per_window,max_database_bytes=12*GIB,reserve_bytes=reserve_bytes)
        analytics=None
        if build_analytics:
            from .analytics import build
            analytics_started=time.monotonic()
            analytics={'scopes':[build(target,s) for s in imported['scopes']],
              'elapsed_seconds':round(time.monotonic()-analytics_started,3)}
        with connect(target) as db:
            tables=db.execute("SELECT relname,pg_relation_size(relid) table_bytes,pg_indexes_size(relid) index_bytes,pg_total_relation_size(relid) total_bytes FROM pg_catalog.pg_statio_user_tables WHERE schemaname='firebridge' ORDER BY pg_total_relation_size(relid) DESC LIMIT 12").fetchall()
            counts=db.execute('SELECT source_id,count(*) n FROM detections GROUP BY source_id ORDER BY source_id').fetchall()
            final_size=db.execute('SELECT pg_database_size(current_database()) n').fetchone()['n']
            release=db.execute("SELECT release_id FROM release_aliases WHERE alias='best_available' ORDER BY scope_key LIMIT 1").fetchone()['release_id']
            example=db.execute('SELECT longitude lon,latitude lat,acquired_at FROM serving.detections WHERE release_id=%s LIMIT 1',(release,)).fetchone()
            bounds=[max(-180,example['lon']-1),max(-90,example['lat']-1),min(180,example['lon']+1),min(90,example['lat']+1)]
            day=utc(example['acquired_at'].date())
            query="""SELECT count(*) FROM detections d WHERE geom && ST_MakeEnvelope(%s,%s,%s,%s,4326)
              AND ST_Covers(ST_MakeEnvelope(%s,%s,%s,%s,4326),geom) AND acquired_at >= %s AND acquired_at<%s
              AND EXISTS(SELECT 1 FROM partition_detections pd JOIN release_partitions rp ON rp.partition_id=pd.partition_id
                WHERE pd.detection_id=d.id AND rp.release_id=%s)"""
            params=(*bounds,*bounds,day,day+timedelta(days=1),release)
            observed=db.execute(query,params).fetchone()['count']
            explain=db.execute('EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) '+query,params).fetchone()['QUERY PLAN']
        raw=sum(r['scanned_rows'] for r in imported['results']);unique=sum(r['n'] for r in counts)
        growth=final_size-imported['database_bytes_before']
        sidecar_bytes=sum(p.stat().st_size for p in target.data_dir.rglob('*') if p.is_file())
        result={'state':'passed','checked_at':now(),'database':name,'retained_database':keep_database,'provider_calls':0,
          'window_ids':chosen,'source_rows':raw,'unique_detections':unique,'source_counts':counts,'tables':tables,
          'database_growth_bytes':growth,'elapsed_seconds':round(time.monotonic()-started,2),'analytics':analytics,
          'measured_bytes_per_detection':round(growth/unique,2) if unique else None,'spatial_query_explain':explain,
          'measured_bytes_per_source_row':round(growth/raw,2) if raw else None,
          'sidecar_bytes':sidecar_bytes,
          'full_archive_database_plus_sidecars_extrapolation_bytes':round(report['source_rows']*(growth+sidecar_bytes)/raw) if raw else None,
          'spatial_query':{'bbox':bounds,'start':day,'end_exclusive':day+timedelta(days=1),'observed_count':observed,'release_id':str(release)},
          'full_archive_storage_extrapolation_bytes':round(report['source_rows']*growth/raw) if raw else None,
          'extrapolation_limitations':'Sample extrapolation, not a capacity guarantee: source mix, duplicates, WAL, backups, bloat, future updates and full dbt rebuilds add overhead.',
          'load':imported}
        return result
    finally:
        if not keep_database:
            assert name.startswith('firebridge_history_benchmark_')
            with psycopg.connect(admin,autocommit=True) as db:db.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
            if result['state']=='passed':shutil.rmtree(target.data_dir)
        atomic_json(settings.data_dir/'history-serving/benchmark.json',result)
