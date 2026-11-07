import csv
import io
import zipfile
import pytest
from firebridge.archive import import_archive
from firebridge.db import connect


@pytest.mark.integration
def test_zip_stream_filter_duplicate_and_full_day_membership(database,scope,tmp_path):
    path=tmp_path/'fixture.zip'
    body='latitude,longitude,acq_date,acq_time,satellite,confidence,daynight,version\n'
    body+='35,-5,2024-01-17,1200,N20,n,D,2\n'*2
    body+='50,20,2024-01-17,1300,N20,h,D,2\n'
    with zipfile.ZipFile(path,'w') as z:z.writestr('fire_archive.csv',body)
    result=import_archive(database,path,'VIIRS_NOAA20_SP',scope,[-6,34,-4,36],'2024-01-17','2024-01-19',coverage_start='2024-01-17',coverage_end='2024-01-19')
    assert result['scanned_rows']==3 and result['selected_rows']==2 and result['partitions']==2
    with connect(database) as conn:
        assert conn.execute('SELECT count(*) AS n FROM serving.detections WHERE release_id=%s',(result['releases']['standard_only'],)).fetchone()['n']==1
