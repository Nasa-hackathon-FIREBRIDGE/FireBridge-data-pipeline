import duckdb
import pytest

from firebridge.config import Settings
from firebridge.history_serving import audit,inventory
from firebridge.history_index import build,descriptor,selection_sql,cells,validate_copy
from test_history_serving import window,HEADER


def fixture(tmp_path,body=None):
    settings=Settings('unused',tmp_path)
    root=window(settings,body or HEADER+'35,-5,2024-01-01,1200,N20,n,D,2,-999\n'*2+
      '35,20,2024-01-02,0000,N20,h,N,2,12\n')
    audit(settings)
    return settings,root,inventory(root)[0]


def test_spatial_copy_is_lossless_reusable_and_preserves_duplicate_native_rows(tmp_path):
    settings,root,record=fixture(tmp_path)
    result=build(settings,reserve_bytes=0)
    assert result['built']==1 and result['provider_calls']==0
    assert build(settings,reserve_bytes=0)['reused']==1
    d=descriptor(settings,record);indexed=[str(tmp_path/'history-index'/shard['path']) for shard in d['shards']];raw=str(root/'parquet'/(record['id']+'.parquet'))
    with duckdb.connect() as db:
        fast,args=selection_sql(indexed,[],[-6,34,-4,36],'2024-01-01','2024-01-03')
        original,oldargs=selection_sql([],[raw],[-6,34,-4,36],'2024-01-01','2024-01-03')
        a=db.execute(fast,args).fetchall();b=db.execute(original,oldargs).fetchall()
        assert sorted(r[:-1] for r in a)==sorted(r[:-1] for r in b) and len(a)==2
        assert all(r[14]=='-999' for r in a)  # original optional FRP text is retained


def test_boundary_coordinates_and_empty_windows_remain_queryable(tmp_path):
    settings,_,record=fixture(tmp_path,HEADER+'90,180,2024-01-01,1200,N20,n,D,2,1\n-90,-180,2024-01-01,1200,N20,n,D,2,2\n')
    build(settings,reserve_bytes=0);d=descriptor(settings,record)
    with duckdb.connect() as db:
        for box in ([179,89,180,90],[-180,-90,-179,-89]):
            query,args=selection_sql([str(tmp_path/'history-index'/shard['path']) for shard in d['shards']],[],box,'2024-01-01','2024-01-03')
            assert len(db.execute(query,args).fetchall())==1
    assert cells([180,90,180,90])==[2591]
    assert len(cells([-180,-90,180,90]))==2592


def test_changed_spatial_copy_is_rejected_and_never_silently_rebuilt(tmp_path):
    settings,_,record=fixture(tmp_path)
    build(settings,reserve_bytes=0);d=descriptor(settings,record)
    (tmp_path/'history-index'/d['shards'][0]['path']).write_bytes(b'corrupt')
    with pytest.raises(ValueError,match='checksum'):build(settings,reserve_bytes=0)


def test_exact_validation_rejects_a_copy_with_changed_measurement(tmp_path):
    settings,root,record=fixture(tmp_path)
    build(settings,reserve_bytes=0);d=descriptor(settings,record)
    original=root/'parquet'/(record['id']+'.parquet');index=[str(tmp_path/'history-index'/shard['path']) for shard in d['shards']];bad=tmp_path/'bad.parquet'
    with duckdb.connect() as db:
        db.execute("COPY (SELECT * REPLACE ('999' AS frp) FROM read_parquet($source)) TO $target (FORMAT PARQUET)",{'source':index,'target':str(bad)})
        with pytest.raises(ValueError,match='lossless'):validate_copy(db,original,bad,record['rows'])


def test_explicit_empty_inventory_has_an_empty_valid_index(tmp_path):
    settings,_,record=fixture(tmp_path,HEADER)
    assert build(settings,reserve_bytes=0)['built']==1
    assert descriptor(settings,record)['rows']==0
