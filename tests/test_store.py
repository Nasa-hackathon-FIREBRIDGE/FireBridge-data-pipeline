import pytest
from firebridge.store import Store


def test_objects_portable_immutable_and_path_bounded(tmp_path):
    store=Store(tmp_path/'data')
    a=store.put([b'original bytes'],'.csv');b=store.put([b'original bytes'],'.csv')
    assert a==b and a.uri.startswith('objects/')
    assert store.resolve(a.uri).read_bytes()==b'original bytes'
    assert store.resolve('/old/machine/data/'+a.uri)==a.path
    with pytest.raises(ValueError):store.resolve('../../.env')
