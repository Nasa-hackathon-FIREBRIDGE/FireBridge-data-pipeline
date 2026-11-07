import hashlib
import json
from pathlib import Path
import zipfile
import duckdb
import pytest
from firebridge.lake import convert_archive, build_catalog, working_directory


def archive(tmp_path, data):
    path=tmp_path/'source.zip'
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:z.writestr('source.csv',data)
    return path


HEADER='latitude,longitude,acq_date,acq_time,satellite,instrument,confidence,daynight,frp\n'


def test_full_archive_preserves_rows_invalid_frp_and_replays(tmp_path):
    path=archive(tmp_path, HEADER+'35,-5,2024-01-01,0015,N20,VIIRS,n,N,-999\n'+
        '-20,130,2025-09-01,1200,SNPP,SNPP,h,D,25\n')
    root=tmp_path/'lake'
    expected={'rows':2,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'stream':'standard'}
    receipt=convert_archive(path,root,expected=expected,min_free_bytes=0)
    assert convert_archive(path,root,expected=expected,min_free_bytes=0)==receipt
    summary=build_catalog(root,[receipt])
    assert summary['source_rows']==2
    with working_directory(root),duckdb.connect(str(root/'catalog.duckdb'),read_only=True) as c:
        assert c.execute('SELECT frp_raw,frp_mw,frp_invalid FROM detections ORDER BY date_utc').fetchall()==[(-999,None,True),(25,25,False)]
        assert c.execute('SELECT acq_time FROM raw_source_rows ORDER BY _source_row').fetchall()==[('0015',),('1200',)]
        assert c.execute("SELECT instrument,instrument_raw FROM detections WHERE satellite='SNPP'").fetchone()==('VIIRS','SNPP')


def test_invalid_archive_never_publishes_parquet(tmp_path):
    path=archive(tmp_path,HEADER+'95,-5,2024-01-01,1200,Terra,MODIS,80,D,10\n')
    root=tmp_path/'lake'
    with pytest.raises(ValueError,match='coordinates'):convert_archive(path,root,min_free_bytes=0)
    assert not list((root/'parquet').glob('*'))


def test_changed_source_and_disk_floor_stop_before_publication(tmp_path):
    path=archive(tmp_path,HEADER+'35,-5,2024-01-01,1200,Terra,MODIS,80,D,10\n')
    root=tmp_path/'lake'
    with pytest.raises(ValueError,match='changed'):convert_archive(path,root,expected={'sha256':'wrong'})
    with pytest.raises(RuntimeError,match='reserve'):convert_archive(path,root,min_free_bytes=10**20)
    assert not list((root/'parquet').glob('*'))
