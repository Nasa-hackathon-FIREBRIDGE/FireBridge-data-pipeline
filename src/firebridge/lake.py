"""Lossless local archive layer: stream every source row into compressed Parquet.

This is an exploration layer, separate from validated PostGIS serving releases.
Native CSV text, overlap rows and questionable values are preserved deliberately.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import csv
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
from uuid import uuid4

import duckdb
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pacsv
import pyarrow.parquet as pq

from .archive import csv_stream
from .normalize import ALIASES, BASE

PLATFORMS = ('Terra', 'Aqua', 'SNPP', 'N20', 'N21', 'L8', 'L9')


def sha256(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def atomic_json(path, value):
    temp = path.with_suffix('.json.partial')
    temp.write_text(json.dumps(value, indent=2, default=str) + '\n')
    temp.replace(path)


def check_space(root, min_free_bytes):
    free = shutil.disk_usage(root).free
    if free < min_free_bytes:
        raise RuntimeError(f'Archive load stopped safely: {free // 1024**3} GiB free; requires {min_free_bytes // 1024**3} GiB reserve')


def platforms(values):
    mapping = {**{p: p for p in PLATFORMS}, **ALIASES}
    keys = pa.array(list(mapping))
    index = pc.index_in(pc.cast(values, pa.string()), value_set=keys)
    if pc.any(pc.is_null(index)).as_py():
        raise ValueError('Unknown satellite identifier in local archive')
    result = pc.take(pa.array(list(mapping.values())), index)
    if not set(pc.unique(result).to_pylist()) <= set(PLATFORMS):
        raise ValueError('Unsupported satellite')
    return result


def convert_archive(path, root, *, expected=None, min_free_bytes=8 * 1024**3):
    path, root = Path(path), Path(root)
    root.mkdir(parents=True, exist_ok=True)
    (root / 'parquet').mkdir(exist_ok=True)
    (root / 'receipts').mkdir(exist_ok=True)
    fingerprint = sha256(path)
    if expected and expected.get('sha256') != fingerprint:
        raise ValueError(f'Source changed since inventory: {path.name}')
    identity = path.stem + '-' + fingerprint[:16]
    target = root / 'parquet' / (identity + '.parquet')
    receipt_path = root / 'receipts' / (identity + '.json')
    if target.exists() and receipt_path.exists():
        receipt = json.loads(receipt_path.read_text())
        if receipt['parquet_sha256'] != sha256(target):
            raise ValueError('Existing Parquet checksum mismatch: ' + target.name)
        print(json.dumps({'archive': path.name, 'status': 'already_loaded', 'rows': receipt['rows']}), flush=True)
        return receipt
    temporary = target.with_suffix('.parquet.partial')
    scanned = 0
    native_fields = None
    writer = None
    try:
        with csv_stream(path) as (source, member):
            header = next(csv.reader([source.readline().decode('utf-8-sig')]))
            if not BASE <= set(header) or len(header) != len(set(header)):
                raise ValueError('Unexpected archive CSV schema')
            if any(c.startswith('_') for c in header):
                raise ValueError('Reserved archive provenance column')
            native_fields = header
            source.seek(0)
            reader = pacsv.open_csv(source, read_options=pacsv.ReadOptions(block_size=8*1024*1024),
                convert_options=pacsv.ConvertOptions(column_types={c: pa.string() for c in header},
                    strings_can_be_null=False))
            for batch in reader:
                check_space(root, min_free_bytes)
                table = pa.Table.from_batches([batch])
                for column, maximum in [('latitude', 90), ('longitude', 180)]:
                    values = pc.cast(table[column], pa.float64())
                    if pc.any(pc.or_(pc.invert(pc.is_finite(values)), pc.greater(pc.abs(values), maximum))).as_py():
                        raise ValueError('Invalid coordinates in source')
                pc.cast(table['acq_date'], pa.date32())  # strict cast, not silently converted to null
                table = table.append_column('_platform', platforms(table['satellite']))
                table = table.append_column('_source_row', pa.array(range(scanned+2, scanned+2+table.num_rows), type=pa.int64()))
                if writer is None:
                    writer = pq.ParquetWriter(temporary, table.schema, compression='zstd', compression_level=6)
                writer.write_table(table, row_group_size=100_000)
                scanned += table.num_rows
            # Reading the entire ZIP member also verifies its CRC.
        if writer is None:
            raise ValueError('Empty archive: explicit empty-dataset support is required')
        writer.close()
        writer = None
        if expected and scanned != expected['rows']:
            raise ValueError('Archive row count differs from inventory')
        if pq.ParquetFile(temporary).metadata.num_rows != scanned:
            raise ValueError('Parquet row count mismatch')
        temporary.replace(target)
        receipt = {'archive': path.name, 'archive_id': identity, 'source_path': str(path.resolve()),
            'source_sha256': fingerprint, 'source_bytes': path.stat().st_size, 'rows': scanned,
            'parquet': str(target.relative_to(root)), 'parquet_bytes': target.stat().st_size,
            'parquet_sha256': sha256(target), 'native_columns': native_fields,
            'zip_crc_verified': path.suffix.lower() == '.zip',
            'stream': (expected or {}).get('stream', 'unknown'),
            'within_archive_duplicate_excess': (expected or {}).get('duplicate_row_hash_excess'),
            'loaded_at': datetime.now(timezone.utc).isoformat()}
        atomic_json(receipt_path, receipt)
        print(json.dumps({'archive': path.name, 'status': 'loaded', 'rows': scanned,
            'parquet_mb': round(target.stat().st_size/1024**2, 1)}), flush=True)
        return receipt
    finally:
        if writer is not None:
            writer.close()
        temporary.unlink(missing_ok=True)


def quote(value):
    return "'" + str(value).replace("'", "''") + "'"


@contextmanager
def working_directory(path):
    old = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old)


def build_catalog(root, receipts, modis_path=None):
    """Small portable DuckDB catalog over immutable Parquet, atomically replaced."""
    root = Path(root).resolve()
    catalog = root / ('catalog-' + uuid4().hex + '.duckdb')
    with working_directory(root), duckdb.connect(str(catalog), config={'threads': 2, 'memory_limit': '2GB'}) as conn:
        conn.execute("SET max_temp_directory_size='2GB'")
        conn.execute('CREATE TABLE archive_inventory(archive VARCHAR, archive_id VARCHAR, source_sha256 VARCHAR, source_rows BIGINT, parquet_bytes BIGINT, processing_stream VARCHAR, within_archive_duplicate_excess BIGINT)')
        raw = []
        for r in receipts:
            conn.execute('INSERT INTO archive_inventory VALUES (?,?,?,?,?,?,?)', [r['archive'], r['archive_id'], r['source_sha256'], r['rows'], r['parquet_bytes'], r['stream'], r['within_archive_duplicate_excess']])
            raw.append(f"SELECT *, {quote(r['archive'])} AS _archive, {quote(r['stream'])} AS _stream FROM read_parquet({quote(r['parquet'])})")
        if modis_path:
            # Preserve the complete audited MODIS selection without adding duplicate raw ZIP files.
            source = Path(modis_path).resolve()
            fingerprint = sha256(source)
            destination = root / 'parquet' / ('audited-modis-' + fingerprint[:16] + '.parquet')
            if not destination.exists():
                temp = destination.with_suffix('.partial')
                shutil.copyfile(source, temp)
                if sha256(temp) != fingerprint:
                    raise ValueError('Audited MODIS copy checksum mismatch')
                temp.replace(destination)
            rows = pq.ParquetFile(destination).metadata.num_rows
            conn.execute('INSERT INTO archive_inventory VALUES (?,?,?,?,?,?,?)', ['Audited MODIS study selection', 'audited-modis', fingerprint, rows, destination.stat().st_size, 'standard', 0])
            raw.append(f"SELECT *, satellite::VARCHAR AS _platform, source_row AS _source_row, 'Audited MODIS study selection' AS _archive, 'standard' AS _stream FROM read_parquet({quote(str(destination.relative_to(root)))})")
        conn.execute('CREATE VIEW raw_source_rows AS ' + ' UNION ALL BY NAME '.join(raw))
        fields = {r[0] for r in conn.execute('DESCRIBE raw_source_rows').fetchall()}
        def optional(name, cast='DOUBLE'):
            return f'try_cast("{name}" AS {cast})' if name in fields else f'NULL::{cast}'
        frp = optional('frp')
        conn.execute(f'''CREATE VIEW detections AS SELECT
            _archive AS archive, _source_row AS source_row, _platform AS satellite,
            CASE WHEN _platform IN ('Terra','Aqua') THEN 'MODIS'
                 WHEN _platform IN ('SNPP','N20','N21') THEN 'VIIRS'
                 WHEN _platform='L8' THEN 'OLI' ELSE 'OLI-2' END AS instrument,
            instrument::VARCHAR AS instrument_raw, acq_date::DATE AS date_utc,
            lpad(acq_time::VARCHAR,4,'0') AS time_utc,
            latitude::DOUBLE AS latitude, longitude::DOUBLE AS longitude,
            confidence::VARCHAR AS confidence_raw, daynight::VARCHAR AS daynight,
            _stream AS processing_stream, {frp} AS frp_raw,
            CASE WHEN isfinite({frp}) AND {frp}>=0 THEN {frp} END AS frp_mw,
            CASE WHEN {frp}<0 OR NOT isfinite({frp}) THEN true ELSE false END AS frp_invalid,
            {optional('brightness')} AS brightness_k,
            {optional('bright_t31')} AS second_band_k,
            {optional('scan')} AS scan_native, {optional('track')} AS track_native,
            {optional('sample','BIGINT')} AS cross_track_sample,
            {optional('type','VARCHAR')} AS type_raw
            FROM raw_source_rows''')
        conn.execute('''CREATE TABLE archive_daily_counts AS SELECT archive,satellite,instrument,processing_stream,date_utc,
            count(*) AS source_row_count,count(frp_mw) AS valid_frp_count,
            count(*) FILTER(WHERE frp_invalid) AS invalid_frp_count,
            avg(frp_mw) AS frp_mean_mw,max(frp_mw) AS frp_max_mw
            FROM detections GROUP BY ALL''')
        conn.execute('''CREATE TABLE satellite_inventory AS SELECT satellite,instrument,processing_stream,
            sum(source_row_count)::BIGINT AS source_rows,min(date_utc) AS first_observed_date,
            max(date_utc) AS last_observed_date,count(DISTINCT archive) AS archives,
            sum(invalid_frp_count)::BIGINT AS invalid_frp_rows
            FROM archive_daily_counts GROUP BY ALL ORDER BY satellite''')
        conn.execute('''CREATE TABLE overlapping_source_days AS SELECT satellite,date_utc,count(DISTINCT archive) AS archive_count
            FROM archive_daily_counts GROUP BY ALL HAVING count(DISTINCT archive)>1''')
        totals = conn.execute('SELECT sum(source_rows) FROM archive_inventory').fetchone()[0]
        assert totals == conn.execute('SELECT sum(source_row_count) FROM archive_daily_counts').fetchone()[0]
        inventory = [dict(zip([c[0] for c in conn.description], row)) for row in conn.execute('SELECT * FROM satellite_inventory').fetchall()]
        overlap_days = conn.execute('SELECT count(*) FROM overlapping_source_days').fetchone()[0]
        conn.execute('CHECKPOINT')
    catalog.replace(root / 'catalog.duckdb')
    summary = {'loaded_at': datetime.now(timezone.utc).isoformat(), 'source_rows': totals,
        'archive_files': len(receipts), 'additional_audited_modis': bool(modis_path),
        'satellites': inventory, 'overlapping_source_days': overlap_days,
        'semantics': 'All source rows retained. Counts include duplicates and overlapping downloads; not unique detections or fire incidents.',
        'storage': 'Parquet + DuckDB; separate from the validated PostgreSQL serving releases.'}
    atomic_json(root / 'manifest.json', summary)
    return summary


def load_all(folder, profile_dir, root, modis_path=None, min_free_bytes=8*1024**3):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    with (root / '.load.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        receipts = []
        profiles = sorted(Path(profile_dir).glob('*/profile.json'))
        if not profiles:
            raise ValueError('No verified source inventory found')
        for profile in profiles:
            expected = json.loads(profile.read_text())
            path = Path(folder) / expected['archive']
            if not path.is_file():
                raise ValueError('Missing source archive: ' + path.name)
            atomic_json(root / 'progress.json', {'state': 'loading', 'current': path.name,
                'completed_archives': len(receipts), 'total_archives': len(profiles)})
            receipts.append(convert_archive(path, root, expected=expected, min_free_bytes=min_free_bytes))
        check_space(root, min_free_bytes)
        summary = build_catalog(root, receipts, modis_path)
        atomic_json(root / 'progress.json', {'state': 'complete', 'completed_archives': len(receipts), 'total_archives': len(profiles)})
        return summary
