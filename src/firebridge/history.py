"""Resumable global FIRMS point history, separate from validated PostGIS releases.

No provider I/O happens at import or catalog initialization. A frozen availability
snapshot defines non-overlapping requests. Only complete, validated responses
become visible in the history catalog; raw CSV bytes are retained as gzip.
"""
from collections import Counter
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import csv
import fcntl
import gzip
import hashlib
import io
import json
from pathlib import Path
import shutil
import sqlite3
import time

import duckdb
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pacsv
import pyarrow.parquet as pq

from .catalog import FEEDS
from .http import FetchError, get
from .lake import atomic_json, platforms, quote, sha256, working_directory
from .normalize import BASE

GIB = 1024**3
GLOBAL_REQUESTS_PER_10_MIN = 20
FAMILIES = ('MODIS', 'VIIRS_SNPP', 'VIIRS_NOAA20', 'VIIRS_NOAA21', 'LANDSAT')
FIELDS = ('latitude longitude brightness bright_ti4 scan track acq_date acq_time '
          'satellite instrument confidence version bright_t31 bright_ti5 frp daynight type path row').split()
RAW_SCHEMA = pa.schema([(c, pa.string()) for c in FIELDS] +
    [('_platform', pa.string()), ('_archive', pa.string()), ('_stream', pa.string()), ('_source_row', pa.int64())])
REQUEST_SCHEMA = pa.schema([(c, pa.string()) for c in
    ('id', 'feed', 'start', 'end_exclusive', 'status', 'error_code', 'raw_sha256', 'parquet_sha256', 'completed_at')] +
    [(c, pa.int64()) for c in ('rows', 'raw_bytes', 'parquet_bytes', 'attempts')])
DAILY_SCHEMA = pa.schema([('archive', pa.string()), ('satellite', pa.string()),
    ('processing_stream', pa.string()), ('date_utc', pa.date32()), ('source_rows', pa.int64()),
    ('invalid_frp_rows', pa.int64())])


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def plan_requests(availability, through):
    """Prefer standard processing; fill only its later tail from NRT, <=5 days.

    Recent NRT is fetched first because that rolling archive expires. Remaining
    windows alternate satellite families from their earliest available dates.
    """
    bounds = {}
    for row in availability:
        if row['data_id'] not in FEEDS:
            continue
        lo, hi = date.fromisoformat(row['min_date']), date.fromisoformat(row['max_date'])
        if lo > hi or row['data_id'] in bounds:
            raise ValueError('invalid_availability_bounds')
        bounds[row['data_id']] = (lo, min(hi, through))
    requests, gaps = [], []
    for family_index, family in enumerate(FAMILIES):
        standard, nrt = family + '_SP', family + '_NRT'
        if (family != 'LANDSAT' and standard not in bounds) or nrt not in bounds:
            raise ValueError('required_feed_missing_from_availability')
        spans = []
        if standard in bounds:
            lo, hi = bounds[standard]
            spans.append((standard, lo, hi, 1))
        lo, hi = bounds[nrt]
        if standard in bounds:
            standard_end = bounds[standard][1] + timedelta(days=1)
            if lo > standard_end and standard_end <= through:
                gaps.append({'family': family, 'start': str(standard_end),
                    'end_exclusive': str(min(lo, through + timedelta(days=1))),
                    'reason': 'not_in_provider_available_ranges'})
            lo = max(lo, standard_end)
        spans.append((nrt, lo, hi, 1 if family == 'LANDSAT' else 0))
        for feed, lo, hi, phase in spans:
            index = 0
            while lo <= hi:
                end = min(lo + timedelta(days=5), hi + timedelta(days=1))
                requests.append({'id': f'{feed}_{lo}_{end}', 'feed': feed,
                    'start': str(lo), 'end_exclusive': str(end), 'status': 'pending',
                    'priority': phase * 1_000_000 + index * len(FAMILIES) + family_index})
                lo, index = end, index + 1
    return sorted(requests, key=lambda r: (r['priority'], r['id'])), gaps


def ledger(root):
    conn = sqlite3.connect(root / 'ledger.sqlite3')
    conn.row_factory = sqlite3.Row
    conn.execute('''CREATE TABLE IF NOT EXISTS requests(
        id TEXT PRIMARY KEY,feed TEXT NOT NULL,start TEXT NOT NULL,end_exclusive TEXT NOT NULL,
        priority INTEGER NOT NULL,status TEXT NOT NULL,error_code TEXT,rows INTEGER,
        raw_bytes INTEGER,parquet_bytes INTEGER,raw_sha256 TEXT,parquet_sha256 TEXT,
        completed_at TEXT,attempts INTEGER NOT NULL DEFAULT 0)''')
    conn.commit()
    return conn


def write_parquet_atomic(table, path):
    temp = path.with_suffix('.partial')
    pq.write_table(table, temp, compression='zstd', compression_level=6, row_group_size=100_000)
    temp.replace(path)


def export_status(root, conn, state, **extra):
    rows = [dict(r) for r in conn.execute('SELECT * FROM requests ORDER BY priority,id')]
    write_parquet_atomic(pa.Table.from_pylist(rows, schema=REQUEST_SCHEMA), root / 'requests.parquet')
    counts = Counter(r['status'] for r in rows)
    result = {'state': state, 'updated_at': utc_now(), 'planned_windows': len(rows),
        'completed_windows': counts['complete'], 'failed_windows': counts['failed'],
        'pending_windows': len(rows) - counts['complete'],
        'downloaded_source_rows': sum(r['rows'] or 0 for r in rows if r['status'] == 'complete'),
        'retained_bytes': sum((r['raw_bytes'] or 0)+(r['parquet_bytes'] or 0) for r in rows if r['status'] == 'complete'),
        'free_disk_bytes': shutil.disk_usage(root).free, **extra}
    atomic_json(root / 'progress.json', result)
    print(json.dumps(result), flush=True)
    return result


def initialize(root):
    """Create an empty inspectable catalog offline. Safe to run before download."""
    root = Path(root).resolve()
    for name in ('raw', 'parquet', 'daily', 'receipts'):
        (root / name).mkdir(parents=True, exist_ok=True)
    for subdir, schema in [('parquet', RAW_SCHEMA), ('daily', DAILY_SCHEMA)]:
        path = root / subdir / '_empty.parquet'
        if not path.exists():
            write_parquet_atomic(pa.Table.from_pylist([], schema=schema), path)
    with ledger(root) as conn:
        if not (root / 'requests.parquet').exists():
            export_status(root, conn, 'not_started')
    catalog = root / 'catalog.duckdb'
    if catalog.exists():
        return
    # The browser's working directory is the parent lake directory. Relative
    # references keep this catalog portable between host and Docker mounts.
    prefix = root.name
    temporary = root / 'catalog.build.duckdb'
    temporary.unlink(missing_ok=True)
    temporary.with_suffix('.duckdb.wal').unlink(missing_ok=True)
    with working_directory(root.parent), duckdb.connect(str(temporary)) as db:
        db.execute(f"CREATE VIEW request_inventory AS SELECT * FROM read_parquet({quote(prefix+'/requests.parquet')})")
        db.execute(f'''CREATE VIEW raw_source_rows AS SELECT p.*
            FROM read_parquet({quote(prefix+'/parquet/*.parquet')},union_by_name=true) p
            JOIN request_inventory r ON p._archive=r.id WHERE r.status='complete' ''')
        db.execute('''CREATE VIEW detections AS SELECT _archive AS archive,_source_row AS source_row,
            _platform AS satellite,
            CASE WHEN _platform IN ('Terra','Aqua') THEN 'MODIS'
                 WHEN _platform IN ('SNPP','N20','N21') THEN 'VIIRS'
                 WHEN _platform='L8' THEN 'OLI' ELSE 'OLI-2' END AS instrument,
            instrument AS instrument_raw,acq_date::DATE AS date_utc,lpad(acq_time,4,'0') AS time_utc,
            latitude::DOUBLE AS latitude,longitude::DOUBLE AS longitude,
            confidence AS confidence_raw,daynight,version AS version_raw,_stream AS processing_stream,
            try_cast(frp AS DOUBLE) AS frp_raw,
            CASE WHEN isfinite(try_cast(frp AS DOUBLE)) AND try_cast(frp AS DOUBLE)>=0
                 THEN try_cast(frp AS DOUBLE) END AS frp_mw,
            (try_cast(frp AS DOUBLE)<0 OR NOT isfinite(try_cast(frp AS DOUBLE))) AS frp_invalid,
            coalesce(try_cast(brightness AS DOUBLE),try_cast(bright_ti4 AS DOUBLE)) AS brightness_k,
            coalesce(try_cast(bright_t31 AS DOUBLE),try_cast(bright_ti5 AS DOUBLE)) AS second_band_k,
            try_cast(scan AS DOUBLE) AS scan_native,try_cast(track AS DOUBLE) AS track_native,
            type AS type_raw FROM raw_source_rows''')
        db.execute(f'''CREATE VIEW daily_counts AS SELECT p.*
            FROM read_parquet({quote(prefix+'/daily/*.parquet')},union_by_name=true) p
            JOIN request_inventory r ON p.archive=r.id WHERE r.status='complete' ''')
        db.execute('''CREATE VIEW satellite_inventory AS SELECT satellite,processing_stream,
            sum(source_rows)::BIGINT AS source_rows,min(date_utc) AS first_observed_date,
            max(date_utc) AS last_observed_date,sum(invalid_frp_rows)::BIGINT AS invalid_frp_rows
            FROM daily_counts GROUP BY ALL''')
        db.execute('CHECKPOINT')
    temporary.replace(catalog)


def validate_and_store(root, request, body, *, reserve_bytes=8*GIB):
    """All-or-nothing window; source corruption and wrong-feed rows fail closed."""
    header = next(csv.reader(io.StringIO(body.partition(b'\n')[0].decode('utf-8-sig')))) if body else []
    if not BASE <= set(header) or len(set(header)) != len(header) or set(header) - set(FIELDS):
        raise ValueError('invalid_or_changed_csv_schema')
    table = pacsv.read_csv(io.BytesIO(body), convert_options=pacsv.ConvertOptions(
        column_types={c: pa.string() for c in header}, strings_can_be_null=False))
    for column, maximum in [('latitude', 90), ('longitude', 180)]:
        values = pc.cast(table[column], pa.float64())
        if pc.any(pc.or_(pc.invert(pc.is_finite(values)), pc.greater(pc.abs(values), maximum))).as_py():
            raise ValueError('invalid_coordinates')
    dates = pc.cast(table['acq_date'], pa.date32())
    lo, hi = date.fromisoformat(request['start']), date.fromisoformat(request['end_exclusive'])
    if pc.any(pc.or_(pc.less(dates, pa.scalar(lo)), pc.greater_equal(dates, pa.scalar(hi)))).as_py():
        raise ValueError('record_outside_requested_dates')
    hhmm = pc.utf8_lpad(table['acq_time'], width=4, padding='0')
    if pc.any(pc.invert(pc.match_substring_regex(hhmm, r'^([01][0-9]|2[0-3])[0-5][0-9]$'))).as_py():
        raise ValueError('invalid_acquisition_time')
    native_platforms = platforms(table['satellite'])
    allowed, stream = FEEDS[request['feed']]
    if not set(pc.unique(native_platforms).to_pylist()) <= set(allowed):
        raise ValueError('unexpected_satellite_for_feed')
    if stream == 'standard' and 'version' in header:
        if pc.any(pc.match_substring_regex(pc.utf8_upper(table['version']), 'RT')).as_py():
            raise ValueError('realtime_record_in_standard_feed')
    for field in FIELDS:
        if field not in header:
            table = table.append_column(field, pa.nulls(table.num_rows, type=pa.string()))
    table = table.append_column('_platform', native_platforms)
    table = table.append_column('_archive', pa.array([request['id']] * table.num_rows, type=pa.string()))
    table = table.append_column('_stream', pa.array([stream] * table.num_rows, type=pa.string()))
    table = table.append_column('_source_row', pa.array(range(2, table.num_rows+2), type=pa.int64()))
    table = table.select(RAW_SCHEMA.names).cast(RAW_SCHEMA)
    if shutil.disk_usage(root).free < reserve_bytes + len(body)*2 + 64*1024**2:
        raise FetchError('disk_reserve_reached', blocked=True)
    raw = root / 'raw' / (request['id'] + '.csv.gz')
    parquet = root / 'parquet' / (request['id'] + '.parquet')
    daily = root / 'daily' / (request['id'] + '.parquet')
    temporary = raw.with_suffix('.partial')
    with temporary.open('wb') as out:
        with gzip.GzipFile(fileobj=out, mode='wb', mtime=0) as gz:
            gz.write(body)
    temporary.replace(raw)
    write_parquet_atomic(table, parquet)
    with duckdb.connect(config={'threads': 1, 'memory_limit': '512MB'}) as db:
        db.register('source', table)
        counts = db.execute('''SELECT _archive AS archive,_platform AS satellite,_stream AS processing_stream,
            acq_date::DATE AS date_utc,count(*)::BIGINT AS source_rows,
            count(*) FILTER(WHERE try_cast(frp AS DOUBLE)<0 OR NOT isfinite(try_cast(frp AS DOUBLE)))::BIGINT AS invalid_frp_rows
            FROM source GROUP BY ALL''').to_arrow_table().cast(DAILY_SCHEMA)
    write_parquet_atomic(counts, daily)
    receipt = {**request, 'rows': table.num_rows, 'raw_bytes': raw.stat().st_size,
        'parquet_bytes': parquet.stat().st_size, 'raw_sha256': sha256(raw),
        'uncompressed_csv_sha256': hashlib.sha256(body).hexdigest(), 'parquet_sha256': sha256(parquet),
        'daily_sha256': sha256(daily), 'native_columns': header, 'completed_at': utc_now(),
        'provider': 'https://firms.modaps.eosdis.nasa.gov/api/area/',
        'geography': 'US/Canada provider footprint' if request['feed']=='LANDSAT_NRT' else 'world',
        'status': 'complete', 'processing_stream': stream}
    atomic_json(root / 'receipts' / (request['id'] + '.json'), receipt)
    return receipt


def verify_completed(root, conn):
    """A rerun verifies bytes before skipping any completed window."""
    for row in conn.execute("SELECT id,raw_sha256,parquet_sha256 FROM requests WHERE status='complete'"):
        try:
            receipt = json.loads((root/'receipts'/(row['id']+'.json')).read_text())
            for directory, suffix, field in [('raw','.csv.gz','raw_sha256'),
                    ('parquet','.parquet','parquet_sha256'), ('daily','.parquet','daily_sha256')]:
                expected = receipt[field]
                if field in row.keys() and row[field] != expected:
                    raise ValueError('receipt_mismatch')
                if sha256(root/directory/(row['id']+suffix)) != expected:
                    raise ValueError('checksum_mismatch')
        except (OSError, ValueError, KeyError):
            conn.execute("UPDATE requests SET status='failed',error_code='local_checksum_failed' WHERE id=?", (row['id'],))
            conn.commit()
            raise FetchError('local_checksum_failed', blocked=True) from None


def run(settings, *, root=None, max_windows=None, reserve_bytes=8*GIB, client=None, sleep=time.sleep):
    """Explicit execution only. Shared PostgreSQL budget also covers live fetches."""
    # World requests cost multiple NASA transactions. Keep headroom under the
    # provider quota, while respecting any smaller operator-supplied budget.
    settings = replace(settings, firms_budget=min(settings.firms_budget, GLOBAL_REQUESTS_PER_10_MIN))
    root = Path(root or settings.data_dir/'lake'/'history').resolve()
    initialize(root)
    with (root/'.download.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with ledger(root) as conn:
            try:
                if not settings.firms_key:
                    raise FetchError('missing_firms_key', blocked=True)
                verify_completed(root, conn)
                if not conn.execute('SELECT count(*) FROM requests').fetchone()[0]:
                    body, _ = get(settings, 'https://firms.modaps.eosdis.nasa.gov/api/data_availability/csv/'+settings.firms_key+'/ALL', client=client, firms=True)
                    reader = csv.DictReader(io.StringIO(body.decode('utf-8-sig')))
                    if not {'data_id','min_date','max_date'} <= set(reader.fieldnames or []):
                        raise FetchError('invalid_availability_schema', blocked=True)
                    availability = list(reader)
                    through = datetime.now(timezone.utc).date()-timedelta(days=1)
                    requests, gaps = plan_requests(availability, through)
                    atomic_json(root/'plan.json', {'created_at': utc_now(), 'through_date_inclusive': str(through),
                        'availability': availability, 'windows': len(requests), 'provider_gaps': gaps,
                        'policy': 'Standard history plus disjoint NRT tail; latest complete UTC day; full provider geography.'})
                    conn.executemany('INSERT INTO requests(id,feed,start,end_exclusive,priority,status) VALUES (:id,:feed,:start,:end_exclusive,:priority,:status)', requests)
                    conn.commit()
                completed_this_run = 0
                for row in conn.execute("SELECT * FROM requests WHERE status!='complete' ORDER BY priority,id").fetchall():
                    request = {k: row[k] for k in ('id', 'feed', 'start', 'end_exclusive')}
                    failures = 0
                    while True:
                        export_status(root, conn, 'downloading', current_request=request['id'])
                        # Reserve room for the largest allowed response before fetching.
                        if shutil.disk_usage(root).free < reserve_bytes + settings.max_bytes*2 + 64*1024**2:
                            raise FetchError('disk_reserve_reached', blocked=True)
                        conn.execute('UPDATE requests SET attempts=attempts+1,error_code=NULL WHERE id=?', (row['id'],))
                        conn.commit()
                        try:
                            days = (date.fromisoformat(row['end_exclusive'])-date.fromisoformat(row['start'])).days
                            url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{settings.firms_key}/{row['feed']}/world/{days}/{row['start']}"
                            body, _ = get(settings, url, client=client, firms=True)
                            receipt = validate_and_store(root, request, body, reserve_bytes=reserve_bytes)
                            conn.execute('''UPDATE requests SET status='complete',error_code=NULL,rows=:rows,
                                raw_bytes=:raw_bytes,parquet_bytes=:parquet_bytes,raw_sha256=:raw_sha256,
                                parquet_sha256=:parquet_sha256,completed_at=:completed_at WHERE id=:id''', receipt)
                            conn.commit()
                            completed_this_run += 1
                            export_status(root, conn, 'downloading')
                            break
                        except FetchError as exc:
                            code = exc.code
                            waiting = code in ('local_rate_budget', 'provider_cooldown', 'http_429')
                            if not waiting:
                                failures += 1
                            conn.execute("UPDATE requests SET status=?,error_code=? WHERE id=?", ('pending' if waiting else 'failed',code,row['id']))
                            conn.commit()
                            if exc.blocked or failures >= 3:
                                raise
                            export_status(root, conn, 'waiting_for_provider', error_code=code,
                                retry_seconds=exc.retry_seconds)
                            sleep(max(1, exc.retry_seconds))
                        except (ValueError, UnicodeError, pa.ArrowException, csv.Error):
                            conn.execute("UPDATE requests SET status='failed',error_code='invalid_firms_payload' WHERE id=?", (row['id'],))
                            conn.commit()
                            raise FetchError('invalid_firms_payload', blocked=True) from None
                    if max_windows is not None and completed_this_run >= max_windows:
                        return export_status(root, conn, 'batch_complete')
                gaps = json.loads((root/'plan.json').read_text())['provider_gaps']
                return export_status(root, conn, 'complete_with_provider_gaps' if gaps else 'complete')
            except FetchError as exc:
                export_status(root, conn, 'paused_disk' if exc.code=='disk_reserve_reached' else 'failed', error_code=exc.code)
                raise
            except Exception:
                export_status(root, conn, 'failed', error_code='history_internal_error')
                # Exception text may include a URL from a dependency. Never persist it.
                raise FetchError('history_internal_error', blocked=True) from None
