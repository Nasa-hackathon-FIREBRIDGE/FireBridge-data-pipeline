"""Stream local FIRMS ZIP/CSV files into complete regional daily snapshots."""
from collections import defaultdict
from contextlib import contextmanager
from datetime import timedelta
import csv
import io
import json
from pathlib import Path
import tempfile
import zipfile
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pacsv
from .catalog import FEEDS,source_id,area
from .db import connect
from .normalize import normalize,BASE
from .publish import run,detection_partition,publish
from .store import Store,asset
from .util import days,utc,digest


@contextmanager
def csv_stream(path):
    if path.suffix.lower()=='.zip':
        with zipfile.ZipFile(path) as z:
            members=[m for m in z.infolist() if m.filename.lower().endswith('.csv') and not m.is_dir()]
            if len(members)!=1:raise ValueError('Expected exactly one CSV in the archive')
            with z.open(members[0]) as f:yield f,members[0].filename
    else:
        with path.open('rb') as f:yield f,path.name


def import_archive(settings,path,feed,scope,bbox,start,end,*,coverage_start,coverage_end):
    """Coverage bounds come from the download request, never min/max detections alone."""
    start,end=utc(start),utc(end); coverage_start,coverage_end=utc(coverage_start),utc(coverage_end)
    window=list(days(start,end))
    if start<coverage_start or end>coverage_end:raise ValueError('Requested dates exceed declared archive coverage')
    platforms,stream=FEEDS[feed]
    path=Path(path).resolve();store=Store(settings.data_dir);obj=store.file(path)
    spec=dict(scope_key=scope,bbox=bbox,start=start.isoformat(),end_exclusive=end.isoformat(),feed=feed,
              declared_coverage_start=coverage_start.isoformat(),declared_coverage_end_exclusive=coverage_end.isoformat(),sha256=obj.sha256)
    with connect(settings) as conn:
        area(conn,scope,bbox);rid=run(conn,'local-archive',digest(spec),spec,obj.uri)
        aid=asset(conn,obj,'raw-'+feed.lower(),path.name,str(path),spec,coverage_start,coverage_end)
    selected=0;scanned=0;pids=[]
    try:
        with tempfile.TemporaryDirectory(prefix='archive-',dir=settings.data_dir/'staging') as temp:
            # Streaming Arrow rejects bad coordinate/date casts; ZIP CRC is verified at EOF.
            with csv_stream(path) as (f,member):
                header=next(csv.reader([f.readline().decode('utf-8-sig')]))
                if not BASE<=set(header):raise ValueError('Unexpected archive CSV schema')
                f.seek(0)
                reader=pacsv.open_csv(f,read_options=pacsv.ReadOptions(block_size=8*1024*1024),
                                     convert_options=pacsv.ConvertOptions(column_types={c:pa.string() for c in header}))
                for batch in reader:
                    scanned+=batch.num_rows
                    lat=pc.cast(batch.column(batch.schema.get_field_index('latitude')),pa.float64())
                    lon=pc.cast(batch.column(batch.schema.get_field_index('longitude')),pa.float64())
                    if pc.any(pc.or_(pc.invert(pc.is_finite(lat)),pc.invert(pc.is_finite(lon)))).as_py():raise ValueError('Non-finite coordinate in archive')
                    if pc.any(pc.or_(pc.greater(pc.abs(lat),90),pc.greater(pc.abs(lon),180))).as_py():raise ValueError('Out-of-bounds coordinate in archive')
                    dates=pc.cast(batch.column(batch.schema.get_field_index('acq_date')),pa.date32())
                    w,s,e,n=bbox
                    keep=pc.and_(pc.and_(pc.greater_equal(lon,w),pc.less_equal(lon,e)),pc.and_(pc.greater_equal(lat,s),pc.less_equal(lat,n)))
                    keep=pc.and_(keep,pc.and_(pc.greater_equal(dates,pa.scalar(start.date())),pc.less(dates,pa.scalar(end.date()))))
                    rows=batch.filter(keep).to_pylist();selected+=len(rows)
                    grouped=defaultdict(list)
                    for row in rows:grouped[row['acq_date']].append(row)
                    for day,raw in grouped.items():
                        with (Path(temp)/(day+'.jsonl')).open('a') as out:
                            for row in raw:out.write(json.dumps(row)+'\n')
            # No serving data is published until the whole compressed member validated.
            for day in window:
                grouped=defaultdict(list);spool=Path(temp)/(str(day.date())+'.jsonl')
                if spool.exists():
                    with spool.open() as f:
                        for line in f:
                            row=normalize(json.loads(line),stream,platforms)
                            if row is not None:grouped[row['source_id']].append(row)
                with connect(settings) as conn:
                    for platform in platforms:
                        sid=source_id(platform,stream)
                        pids.append(detection_partition(conn,settings,rid,aid,sid,day,scope,bbox,grouped[sid]))
            with connect(settings) as conn:
                result=publish(conn,settings,pids,scope)
                conn.execute("UPDATE pipeline_runs SET status='succeeded',finished_at=now(),output_manifest_uri=%s WHERE id=%s",(obj.uri,rid))
        return dict(scanned_rows=scanned,selected_rows=selected,partitions=len(pids),releases=result,scope_key=scope)
    except Exception:
        with connect(settings) as conn:
            conn.execute("UPDATE pipeline_runs SET status='failed',finished_at=now(),error_code='archive_validation_failed' WHERE id=%s",(rid,))
        raise
