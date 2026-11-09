"""Selective archive preparation: prune files/AOI before canonical normalization.

Only requested records enter the existing native serving contract. SQL run keys
and an advisory lock make work durable and idempotent across process restarts.
No provider/network acquisition and no global-history PostgreSQL import.
"""
from collections import defaultdict
from contextlib import contextmanager
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import time

import duckdb
from psycopg.types.json import Jsonb

from .catalog import FEEDS, source_id
from .db import connect
from .history_serving import inventory, native_row, _space, GIB
from .history_index import descriptor, selection_sql, selected_shards
from .lake import sha256
from .publish import stream_detection_partition, publish
from .store import Store, asset
from .util import canonical, digest, now, uid, utc

ENGINE = 'archive-selection-v1'
STAGE = 'archive-selection'
_verified_files = {}
AREA_SQL = """CASE WHEN ST_XMax(a.geom)-ST_XMin(a.geom)>=359.999
 AND ST_YMax(a.geom)-ST_YMin(a.geom)>=179.999 THEN a.geom
 WHEN ST_XMax(a.geom)-ST_XMin(a.geom)>180 THEN
 (SELECT ST_Collect(CASE WHEN ST_XMax(part.geom)-ST_XMin(part.geom)>180
 THEN ST_WrapX(ST_ShiftLongitude(part.geom),180,-360) ELSE part.geom END)
 FROM ST_Dump(a.geom) part) ELSE a.geom END"""


def method_sha():
    root=Path(__file__).parent
    return digest([ENGINE,*(sha256(root/p) for p in ('normalize.py','history_serving.py','history_query.py','history_index.py'))])


def verify_immutable(path, expected):
    stat=path.stat();identity=(str(path),stat.st_size,stat.st_mtime_ns,expected)
    if identity not in _verified_files:
        if sha256(path)!=expected:raise ValueError('Archive file checksum mismatch')
        if len(_verified_files)>5000:_verified_files.clear()
        _verified_files[identity]=True


@contextmanager
def worker_lock(settings):
    # Release synchronously: closing a TCP connection can finish before the
    # server has processed its disconnect and released session advisory locks.
    with connect(settings) as db:
        db.autocommit=True
        acquired=db.execute("SELECT pg_try_advisory_lock(hashtextextended('history-query-worker',0)) ok").fetchone()['ok']
        try:yield acquired
        finally:
            if acquired:db.execute("SELECT pg_advisory_unlock(hashtextextended('history-query-worker',0))")


def window_sources(record):
    platforms,stream=FEEDS[record['feed']]
    observed=record.get('platforms') or ([] if record['feed'].startswith('MODIS') else platforms)
    if record['feed'].startswith('MODIS'):
        collections=set()
        for version in record.get('versions',[]):
            version=str(version).upper().replace('NRT','')
            if version in ('6','006','6.0','6.02','6.03'):collections.add('6')
            elif version in ('61','061','6.1','61.03','6.1.03'):collections.add('61')
            elif 'RT' not in version:raise ValueError('Unsupported archived MODIS collection')
        return sorted(source_id(p,stream,c) for p in observed for c in collections)
    return sorted(source_id(p,stream) for p in observed)


def publish_catalog(settings, scope='global'):
    """Publish immutable metadata only. No point rows or recent aliases change."""
    root=settings.data_dir/'lake/history';audit=json.loads((settings.data_dir/'history-serving/audit.json').read_text())
    records=inventory(root)
    if audit['state']!='passed' or audit['inventory_sha256']!=digest(records):raise ValueError('A current successful archive audit is required')
    verified={r['id']:r for r in audit['results']}
    windows=[]
    for r in records:
        q=verified[r['id']]
        if q['status']!='verified' or q.get('invalid_native_rows'):raise ValueError('Archive has unresolved native blockers')
        receipt=json.loads((root/'receipts'/(r['id']+'.json')).read_text())
        indexed=descriptor(settings,r)
        windows.append({**r,'sources':window_sources(q),'native_columns':receipt['native_columns'],
          **({'query_index':indexed} if indexed else {})})
    signature=digest([ENGINE,audit['inventory_sha256'],method_sha(),
      [(w['id'],digest(w['query_index'])) for w in windows if 'query_index' in w]])
    rid=uid(['archive-catalog',scope,signature]);store=Store(settings.data_dir)
    manifest={'engine':ENGINE,'signature':signature,'method_sha256':method_sha(),'windows':windows}
    obj=store.json(manifest)
    sources=sorted({s for w in windows for s in w['sources'] if s.endswith('-standard')})
    standard=[w for w in windows if FEEDS[w['feed']][1]=='standard' and w['sources']]
    config={'engine':ENGINE,'signature':signature,'source_ids':sources,'metric_ids':['native_detections_v1'],
      'start':min(w['start'] for w in standard),'end_exclusive':max(w['end_exclusive'] for w in standard),
      'observation_coverage':'unknown','archive_rows':audit['source_rows'],'manifest_sha256':obj.sha256}
    with connect(settings) as db:
        db.execute("""INSERT INTO data_releases(id,name,status,stream,code_version,config,config_sha256,
          manifest_uri,dataset_kind,scope_key,observation_cutoff,published_at,validation_report_uri)
          VALUES (%s,%s,'published','retrospective',%s,%s,%s,%s,'satellite',%s,%s,now(),%s)
          ON CONFLICT(id) DO NOTHING""",(rid,'Historical archive '+signature[:12],ENGINE,Jsonb(config),signature,obj.uri,scope,utc(config['end_exclusive']),obj.uri))
        for source in sources:
            source_obj=store.json({'catalog_id':str(rid),'source_id':source,'manifest_sha256':obj.sha256,
              'windows':[{'id':w['id'],'sha256':w['parquet_sha256'],'start':w['start'],'end_exclusive':w['end_exclusive']} for w in windows if source in w['sources']]})
            aid=asset(db,source_obj,source,'archive-catalog:'+signature,'NASA FIRMS validated archive inventory',{'catalog_signature':signature})
            db.execute("INSERT INTO release_assets VALUES (%s,%s,'archive_inventory') ON CONFLICT DO NOTHING",(rid,aid))
        db.execute("""INSERT INTO release_aliases VALUES ('historical_archive',%s,%s,1,now())
          ON CONFLICT(alias,scope_key) DO UPDATE SET release_id=EXCLUDED.release_id,
          generation=release_aliases.generation+1,updated_at=now()
          WHERE release_aliases.release_id<>EXCLUDED.release_id""",(scope,rid))
    return {'catalog_id':str(rid),'signature':signature,'windows':len(windows),'provider_calls':0}


def catalog(settings, release_id):
    with connect(settings) as db:
        r=db.execute("SELECT * FROM data_releases WHERE id=%s AND status='published' AND config->>'engine'=%s",(release_id,ENGINE)).fetchone()
    if not r:raise ValueError('Unknown immutable archive catalog')
    path=Store(settings.data_dir).resolve(r['manifest_uri'])
    if sha256(path)!=r['config']['manifest_sha256']:raise ValueError('Archive manifest checksum mismatch')
    value=json.loads(path.read_text())
    if value['method_sha256']!=method_sha():raise ValueError('Archive catalog uses a different normalizer; publish the current catalog')
    return value


def submit(settings, analysis_id):
    """Untrusted HTTP callers can identify an existing analysis, never pass SQL/paths."""
    with connect(settings) as db:
        row=db.execute("""SELECT x.id,x.area_id,x.start_date::text,x.end_date_exclusive::text,x.request_spec,
          a.geometry_sha256 FROM analyses x JOIN areas a ON a.id=x.area_id WHERE x.id=%s""",(analysis_id,)).fetchone()
        if not row or not row['request_spec'].get('history_catalog_id'):raise ValueError('Analysis is not an archive request')
        spec={'catalog_id':row['request_spec']['history_catalog_id'],'area_id':str(row['area_id']),
          'geometry_sha256':row['geometry_sha256'],'start':row['start_date'],'end_exclusive':row['end_date_exclusive'],
          'data_mode':row['request_spec'].get('data_mode')}
        if spec['data_mode']!='standard_only':raise ValueError('Unsupported archive processing selection')
        if not 0<(utc(spec['end_exclusive'])-utc(spec['start'])).days<=3660:raise ValueError('Select at most 3660 days per historical analysis')
        key=digest([ENGINE,spec]);rid=uid([STAGE,key])
        db.execute("""INSERT INTO pipeline_runs(id,stage,idempotency_key,status,code_version,config,input_manifest_uri)
          VALUES (%s,%s,%s,'queued',%s,%s,%s) ON CONFLICT(idempotency_key) DO NOTHING""",(rid,STAGE,key,ENGINE,Jsonb(spec),'archive-catalog:'+spec['catalog_id']))
    return status(settings,str(rid))


def status(settings, run_id):
    with connect(settings) as db:
        r=db.execute('SELECT id,status,error_code,output_manifest_uri FROM pipeline_runs WHERE id=%s AND stage=%s',(run_id,STAGE)).fetchone()
    if not r:raise ValueError('Unknown historical preparation')
    result={'job_id':str(r['id']),'status':r['status'],'error_code':r['error_code']}
    if r['status']=='succeeded':
        path=Store(settings.data_dir).resolve(r['output_manifest_uri'])
        if sha256(path)!=path.stem:raise ValueError('Historical result receipt checksum mismatch')
        result['result']=json.loads(path.read_text())
    return result


def intervals(windows,start,end):
    supported=defaultdict(list)
    for w in windows:
        for source in w['sources']:
            if source.endswith('-standard'):supported[source].append((max(start,w['start']),min(end,w['end_exclusive'])))
    merged={}
    for source,ranges in supported.items():
        out=[]
        for left,right in sorted(ranges):
            if left>=right:continue
            if out and left<=out[-1][1]:out[-1][1]=max(out[-1][1],right)
            else:out.append([left,right])
        if out:merged[source]=out
    return merged


def prepare(settings,run_id,*,max_selected=1_000_000,reserve_bytes=16*GIB,database_budget=100*GIB,timeout_seconds=1800):
    """One bounded job; no whole-archive canonicalization or main-scope publication."""
    started=time.monotonic();root=settings.data_dir/'lake/history';store=Store(settings.data_dir)
    with worker_lock(settings) as acquired:
        if not acquired:return None
        with connect(settings) as db:
            job=db.execute('SELECT * FROM pipeline_runs WHERE id=%s AND stage=%s',(run_id,STAGE)).fetchone()
            if not job:raise ValueError('Unknown historical job')
            if job['status']=='succeeded':return status(settings,run_id)
            if job['status'] not in ('queued','running'):return status(settings,run_id)
            db.execute("UPDATE pipeline_runs SET status='running',started_at=now(),error_code=NULL WHERE id=%s",(run_id,))
        try:
            spec=job['config'];manifest=catalog(settings,spec['catalog_id'])
            windows=[w for w in manifest['windows'] if w['start']<spec['end_exclusive'] and w['end_exclusive']>spec['start'] and FEEDS[w['feed']][1]=='standard' and w['sources']]
            support=intervals(windows,spec['start'],spec['end_exclusive'])
            if not support:raise ValueError('No archived standard records support this interval')
            with connect(settings) as db:
                area=db.execute(f"""WITH selected AS (SELECT {AREA_SQL} geom,a.geometry_sha256 FROM areas a WHERE a.id=%s)
                  SELECT geometry_sha256,ST_XMin(geom) w,ST_YMin(geom) s,ST_XMax(geom) e,ST_YMax(geom) n FROM selected""",(spec['area_id'],)).fetchone()
            if not area or area['geometry_sha256']!=spec['geometry_sha256']:raise ValueError('Area revision changed')
            bbox=[area[k] for k in ('w','s','e','n')];_space(settings,reserve_bytes,database_budget)
            indexed=[];raw_paths=[];by_path={};checked_bytes=0;indexed_count=0
            for w in windows:
                if 'query_index' in w:
                    q=w['query_index'];base=settings.data_dir/'history-index'
                    if q['source_sha256']!=w['parquet_sha256'] or q['rows']!=w['rows'] or not q['lossless_verified']:
                        raise ValueError('Pinned index does not match source')
                    inputs=[(base/item['path'],item['sha256']) for item in selected_shards(q,bbox)]
                    indexed_count+=1
                else:
                    base=root;inputs=[(root/'parquet'/(w['id']+'.parquet'),w['parquet_sha256'])]
                for path,expected in inputs:
                    if not path.resolve().is_relative_to(base.resolve()):raise ValueError('Archive path escapes root')
                    verify_immutable(path,expected)
                    (indexed if 'query_index' in w else raw_paths).append(str(path))
                    by_path[str(path)]=w;checked_bytes+=path.stat().st_size
            temp_root=settings.data_dir/'history-query';temp_root.mkdir(exist_ok=True)
            scope='hist-'+job['idempotency_key'][:40]
            with tempfile.TemporaryDirectory(prefix='query-',dir=temp_root) as temporary,sqlite3.connect(Path(temporary)/'selected.sqlite3') as spool,duckdb.connect(config={'threads':2,'memory_limit':'512MB','temp_directory':temporary,'max_temp_directory_size':'512MB'}) as db:
                spool.execute('PRAGMA journal_mode=OFF');spool.execute('PRAGMA cache_size=-16384')
                spool.execute('CREATE TABLE rows(source TEXT,day TEXT,sha TEXT,body TEXT,PRIMARY KEY(source,day,sha)) WITHOUT ROWID')
                query,parameters=selection_sql(indexed,raw_paths,bbox,spec['start'],spec['end_exclusive'])
                cursor=db.execute(query,parameters)
                columns=[c[0] for c in cursor.description];candidates=0;invalid_frp=0
                with connect(settings) as spatial:
                    while batch:=cursor.fetchmany(2048):
                        if time.monotonic()-started>timeout_seconds:raise RuntimeError('history_query_timeout')
                        _space(settings,reserve_bytes,database_budget)
                        raw=[dict(zip(columns,row)) for row in batch]
                        keep=spatial.execute(f"""SELECT p.ordinality FROM areas a CROSS JOIN
                          unnest(%s::float8[],%s::float8[]) WITH ORDINALITY p(lon,lat,ordinality)
                          WHERE a.id=%s AND ST_Covers({AREA_SQL},ST_SetSRID(ST_MakePoint(p.lon,p.lat),4326))""",
                          ([float(r['longitude']) for r in raw],[float(r['latitude']) for r in raw],spec['area_id'])).fetchall()
                        for kept in keep:
                            r=raw[kept['ordinality']-1];w=by_path[r['filename']]
                            native={k:r[k] for k in w['native_columns']};row,invalid=native_row(native,w['feed'])
                            if row is None:continue
                            if row['source_id'] not in support:raise ValueError('Record source missing from frozen catalog')
                            candidates+=1;invalid_frp+=int(invalid)
                            if candidates>max_selected:raise RuntimeError('history_selection_too_large')
                            spool.execute('INSERT OR IGNORE INTO rows VALUES (?,?,?,?)',(row['source_id'],str(row['acquired_at'].date()),row['record_sha256'],canonical(row)))
                        spool.commit()
                count=spool.execute('SELECT count(*) FROM rows').fetchone()[0]
                _space(settings,reserve_bytes,database_budget,expected_growth=count*4096)
                partitions=[]
                with connect(settings) as sql:
                    for source,ranges in sorted(support.items()):
                        obj=store.json({'catalog_id':spec['catalog_id'],'manifest_sha256':digest(manifest),
                          'selection':spec,'source_id':source,'inputs':[{'id':w['id'],'parquet_sha256':w['parquet_sha256']} for w in windows if source in w['sources']]})
                        aid=asset(sql,obj,source,job['idempotency_key'],'NASA FIRMS historical selection input manifest',{'engine':ENGINE,'raw_frp_policy':'invalid becomes flagged NULL'})
                        for left,right in ranges:
                            n=spool.execute('SELECT count(*) FROM rows WHERE source=? AND day>=? AND day<?',(source,left,right)).fetchone()[0]
                            def records(source=source,left=left,right=right):
                                for (body,) in spool.execute('SELECT body FROM rows WHERE source=? AND day>=? AND day<? ORDER BY sha',(source,left,right)):
                                    row=json.loads(body);row['acquired_at']=utc(row['acquired_at']);yield row
                            partitions.append(str(stream_detection_partition(sql,settings,run_id,aid,source,left,scope,bbox,records,n,
                              fetched_at=now(),end_exclusive=right,area_id=spec['area_id'],inventory_complete=True)))
                    releases=publish(sql,settings,partitions,scope)
                    rid=releases['standard_only']
                    sql.execute("UPDATE data_releases SET config=config || %s WHERE id=ANY(%s::uuid[])",
                      (Jsonb({'engine':ENGINE,'selection_key':job['idempotency_key'],'catalog_id':spec['catalog_id'],'area_id':spec['area_id'],
                        'start':spec['start'],'end_exclusive':spec['end_exclusive'],'source_ids':sorted(support)}),list(releases.values())))
                    result={**spec,'release_id':rid,'selection_key':job['idempotency_key'],'source_ids':sorted(support),
                      'selected_rows':count,'duplicate_rows':candidates-count,'invalid_frp_rows':invalid_frp,'input_windows':len(windows),
                      'indexed_windows':indexed_count,'raw_windows':len(raw_paths),'read_files':len(indexed)+len(raw_paths),
                      'verified_input_bytes':checked_bytes,'elapsed_seconds':round(time.monotonic()-started,3),'provider_calls':0}
                    receipt=store.json(result)
                    sql.execute("UPDATE pipeline_runs SET status='succeeded',finished_at=now(),release_id=%s,output_manifest_uri=%s WHERE id=%s",(rid,receipt.uri,run_id))
                with connect(settings) as sql:
                    sql.execute('ANALYZE firebridge.detections,firebridge.partition_detections,firebridge.data_partitions')
            return status(settings,run_id)
        except Exception as exc:
            code=str(exc) if isinstance(exc,RuntimeError) and str(exc) in ('history_selection_too_large','history_query_timeout') else 'history_preparation_failed'
            with connect(settings) as db:db.execute("UPDATE pipeline_runs SET status='failed',finished_at=now(),error_code=%s WHERE id=%s",(code,run_id))
            raise
