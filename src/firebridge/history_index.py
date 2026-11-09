"""Lossless, immutable spatial Parquet copies for selective archive reads."""
from datetime import date
from concurrent.futures import ThreadPoolExecutor
import fcntl
import json
import math
from pathlib import Path
import shutil
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq
import tempfile
import time

import duckdb

from .catalog import FEEDS
from .history import RAW_SCHEMA
from .history_serving import inventory, GIB
from .lake import atomic_json, sha256
from .util import digest

LAYOUT='geo5-regions-v1'
COLUMNS=','.join('"'+name+'"' for name in RAW_SCHEMA.names)
CELL_SQL="least(35,floor((cast(latitude AS DOUBLE)+90)/5)::INT)*72+least(71,floor((cast(longitude AS DOUBLE)+180)/5)::INT)"


def cells(bbox):
    west,south,east,north=bbox
    if not all(math.isfinite(v) for v in bbox) or not -180<=west<=east<=180 or not -90<=south<=north<=90:
        raise ValueError('Invalid spatial index bounds')
    return [y*72+x for y in range(min(35,math.floor((south+90)/5)),min(35,math.floor((north+90)/5))+1)
      for x in range(min(71,math.floor((west+180)/5)),min(71,math.floor((east+180)/5))+1)]


def locations(settings,record):
    root=settings.data_dir/'history-index'/LAYOUT
    name=record['id']+'-'+record['parquet_sha256']
    return root,root/'windows'/name,root/'windows'/name/'index.json'


def descriptor(settings,record):
    root,target,receipt=locations(settings,record)
    if not receipt.exists():return None
    value=json.loads(receipt.read_text())
    if value.get('layout')!=LAYOUT or value.get('source_sha256')!=record['parquet_sha256'] or value.get('rows')!=record['rows'] or not value.get('lossless_verified'):
        raise ValueError('Spatial index receipt mismatch')
    if sum(shard['rows'] for shard in value['shards'])!=record['rows']:raise ValueError('Spatial index row count mismatch')
    for shard in value['shards']:
        path=settings.data_dir/'history-index'/shard['path']
        if not path.resolve().is_relative_to(target.resolve()) or sha256(path)!=shard['sha256']:
            raise ValueError('Spatial index checksum mismatch')
    return value


def region_ids(bbox):
    cells(bbox)  # validate bounds
    w,s,e,n=bbox
    return {y*12+x for y in range(min(5,math.floor((s+90)/30)),min(5,math.floor((n+90)/30))+1)
      for x in range(min(11,math.floor((w+180)/30)),min(11,math.floor((e+180)/30))+1)}


def selected_shards(value,bbox):
    regions=region_ids(bbox)
    return [shard for shard in value['shards'] if shard['region'] is None or shard['region'] in regions]


def validate_copy(db,source,target,expected_rows):
    # Full equality, not sample/hash equivalence. The generated source row key
    # also detects missing/duplicate rows while retaining duplicate observations.
    pairs=','.join('s."'+c+'"' for c in RAW_SCHEMA.names)
    other=','.join('i."'+c+'"' for c in RAW_SCHEMA.names)
    cell=CELL_SQL.replace('latitude','s.latitude').replace('longitude','s.longitude')
    row=db.execute(f"""SELECT count(*) n,count(DISTINCT i._source_row) unique_rows,
      count(*) FILTER(WHERE s._source_row IS NULL OR i._source_row IS NULL
       OR ({pairs}) IS DISTINCT FROM ({other})
       OR i._geo_lon IS DISTINCT FROM cast(s.longitude AS DOUBLE)
       OR i._geo_lat IS DISTINCT FROM cast(s.latitude AS DOUBLE)
       OR i._geo_cell IS DISTINCT FROM {cell}) bad
      FROM read_parquet($source) s FULL OUTER JOIN read_parquet($target) i USING(_source_row)""",
      {'source':str(source),'target':target if isinstance(target,list) else str(target)}).fetchone()
    if row!=(expected_rows,expected_rows,0):raise ValueError('Spatial index is not an exact lossless copy')


def build_window(settings,record,*,reserve_bytes=16*GIB):
    root,target,receipt=locations(settings,record)
    target.parent.mkdir(parents=True,exist_ok=True)
    existing=descriptor(settings,record)
    if existing:return existing,True
    source=settings.data_dir/'lake/history/parquet'/(record['id']+'.parquet')
    if sha256(source)!=record['parquet_sha256']:raise ValueError('Archive file checksum mismatch')
    if shutil.disk_usage(settings.data_dir).free<reserve_bytes+source.stat().st_size*8+2*GIB:
        raise RuntimeError('Spatial index disk reserve reached')
    with tempfile.TemporaryDirectory(prefix='build-',dir=root) as temporary:
        temporary=Path(temporary);candidate=temporary/'index';candidate.mkdir()
        output=candidate/'parts'
        with duckdb.connect(config={'threads':1,'memory_limit':'768MB','preserve_insertion_order':False,
          'partitioned_write_max_open_files':1,'temp_directory':str(temporary/'spill'),'max_temp_directory_size':'2GB'}) as db:
            selection=f"""SELECT {COLUMNS},cast(longitude AS DOUBLE) _geo_lon,
              cast(latitude AS DOUBLE) _geo_lat,{CELL_SQL} _geo_cell,
              least(5,floor((cast(latitude AS DOUBLE)+90)/30)::INT)*12+
              least(11,floor((cast(longitude AS DOUBLE)+180)/30)::INT) _geo_bucket
              FROM read_parquet($source) ORDER BY _geo_bucket,_geo_cell,_geo_lat,_geo_lon,_source_row"""
            if record['rows']:
                db.execute(f"COPY ({selection}) TO $target (FORMAT PARQUET,COMPRESSION ZSTD,ROW_GROUP_SIZE 2048,PARTITION_BY(_geo_bucket))",
                  {'source':str(source),'target':str(output)})
            else:
                output.mkdir()
                db.execute(f"COPY ({selection}) TO $target (FORMAT PARQUET,COMPRESSION ZSTD,ROW_GROUP_SIZE 2048)",
                  {'source':str(source),'target':str(output/'empty.parquet')})
            paths=sorted(output.rglob('*.parquet'))
            validate_copy(db,source,[str(p) for p in paths],record['rows'])
        shards=[]
        for path in paths:
            parent=path.parent.name
            region=int(parent.split('=',1)[1]) if parent.startswith('_geo_bucket=') else None
            shards.append({'path':str((target/path.relative_to(candidate)).relative_to(settings.data_dir/'history-index')),
              'region':region,'sha256':sha256(path),'rows':pq.read_metadata(path).num_rows,'bytes':path.stat().st_size})
        value={'layout':LAYOUT,'source_sha256':record['parquet_sha256'],'rows':record['rows'],
          'bytes':sum(p['bytes'] for p in shards),'lossless_verified':True,'shards':shards}
        atomic_json(candidate/'index.json',value)
        candidate.replace(target)
        return value,False


def build(settings,*,start=None,end=None,max_windows=None,reserve_bytes=16*GIB,workers=2):
    for value in (start,end):
        if value and date.fromisoformat(value).isoformat()!=value:raise ValueError('Use ISO dates')
    if start and end and start>=end:raise ValueError('Invalid index interval')
    if max_windows is not None and (type(max_windows) is not int or not 1<=max_windows<=10000):raise ValueError('Invalid index batch size')
    if type(workers) is not int or not 1<=workers<=2:raise ValueError('Use one or two index workers')
    root=settings.data_dir/'history-index';root.mkdir(exist_ok=True)
    with (root/'build.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        records=inventory(settings.data_dir/'lake/history')
        audit=json.loads((settings.data_dir/'history-serving/audit.json').read_text())
        if audit['state']!='passed' or audit['inventory_sha256']!=digest(records):raise ValueError('A current successful archive audit is required')
        verified={r['id']:r for r in audit['results']}
        selected=[r for r in records if FEEDS[r['feed']][1]=='standard' and (not start or r['end_exclusive']>start) and (not end or r['start']<end)]
        if max_windows is not None:selected=selected[:max_windows]
        for r in selected:
            if verified[r['id']]['status']!='verified' or verified[r['id']].get('invalid_native_rows'):raise ValueError('Unresolved archive quality blocker')
        layout=root/LAYOUT
        # Only our orphaned temporary directories, while holding the exclusive
        # builder lock. Final immutable windows and all source files are retained.
        if layout.exists():
            for orphan in layout.glob('build-*'):
                if orphan.is_dir() and not orphan.is_symlink():shutil.rmtree(orphan)
        started=time.monotonic();built=reused=retained=0
        pool=ThreadPoolExecutor(max_workers=workers,thread_name_prefix='history-index')
        try:
            for i,(value,cached) in enumerate(pool.map(lambda r:build_window(settings,r,reserve_bytes=reserve_bytes),selected)):
                reused+=int(cached);built+=int(not cached);retained+=value['bytes']
                progress={'state':'indexing','completed':i+1,'planned':len(selected),'built':built,'reused':reused,
                  'retained_bytes':retained,'elapsed_seconds':round(time.monotonic()-started,3),'provider_calls':0}
                atomic_json(root/'progress.json',progress)
                if i%25==0:print(json.dumps(progress),flush=True)
        finally:pool.shutdown(wait=True,cancel_futures=True)
        result={'state':'complete','completed':len(selected),'built':built,'reused':reused,'retained_bytes':retained,
          'elapsed_seconds':round(time.monotonic()-started,3),'provider_calls':0}
        atomic_json(root/'progress.json',result);return result


def selection_sql(indexed,raw,bbox,start,end):
    params={'start':start,'end':end,'west':bbox[0],'south':bbox[1],'east':bbox[2],'north':bbox[3]}
    queries=[]
    if indexed:
        params['indexed']=indexed
        tile_ids=','.join(map(str,cells(bbox)))
        queries.append(f"""SELECT {COLUMNS},filename FROM read_parquet($indexed,filename=true)
          WHERE acq_date>=$start AND acq_date<$end AND _geo_cell IN ({tile_ids})
          AND _geo_lon BETWEEN $west AND $east AND _geo_lat BETWEEN $south AND $north""")
    if raw:
        params['raw']=raw
        queries.append(f"""SELECT {COLUMNS},filename FROM read_parquet($raw,filename=true)
          WHERE acq_date>=$start AND acq_date<$end AND try_cast(longitude AS DOUBLE) BETWEEN $west AND $east
          AND try_cast(latitude AS DOUBLE) BETWEEN $south AND $north""")
    if not queries:
        return 'SELECT '+','.join('CAST(NULL AS '+('BIGINT' if c=='_source_row' else 'VARCHAR')+') AS "'+c+'"' for c in [*RAW_SCHEMA.names,'filename'])+' WHERE FALSE',{}
    return ' UNION ALL '.join(queries),params


def selected_batches(indexed,raw,bbox,start,end,temporary):
    """Bounded streaming: Arrow avoids SQL/file-binding overhead for tiny shards."""
    if indexed:
        pa.set_cpu_count(2);pa.set_io_thread_count(2)
        condition=(ds.field('acq_date')>=start) & (ds.field('acq_date')<end)
        condition=condition & ds.field('_geo_cell').isin(cells(bbox))
        condition=condition & (ds.field('_geo_lon')>=bbox[0]) & (ds.field('_geo_lon')<=bbox[2])
        condition=condition & (ds.field('_geo_lat')>=bbox[1]) & (ds.field('_geo_lat')<=bbox[3])
        scanner=ds.dataset(indexed,format='parquet',partitioning=None).scanner(
          columns=[*RAW_SCHEMA.names,'__filename'],filter=condition,batch_size=2048,
          batch_readahead=1,fragment_readahead=2,use_threads=True)
        for batch in scanner.to_batches():
            if not batch.num_rows:continue
            rows=batch.to_pylist()
            for row in rows:row['filename']=row.pop('__filename')
            yield rows
    if raw:
        with duckdb.connect(config={'threads':2,'memory_limit':'512MB','temp_directory':temporary,'max_temp_directory_size':'512MB'}) as db:
            query,args=selection_sql([],raw,bbox,start,end);cursor=db.execute(query,args)
            columns=[c[0] for c in cursor.description]
            while batch:=cursor.fetchmany(2048):yield [dict(zip(columns,row)) for row in batch]
