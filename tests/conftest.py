from dataclasses import replace
import os
from uuid import uuid4
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
import pytest
from firebridge.catalog import seed
from firebridge.config import Settings
from firebridge.db import migrate


@pytest.fixture(scope='session')
def database(tmp_path_factory):
    if os.getenv('FIREBRIDGE_TEST_DB')!='1':
        pytest.skip('Set FIREBRIDGE_TEST_DB=1 to create an isolated integration database')
    base=Settings.load()
    name='firebridge_test_'+uuid4().hex[:12]
    admin=make_conninfo(base.database_url,dbname='postgres')
    with psycopg.connect(admin,autocommit=True) as conn:
        conn.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    settings=replace(base,database_url=make_conninfo(base.database_url,dbname=name),
                     data_dir=tmp_path_factory.mktemp('firebridge-data'),firms_key='fixture-key-not-a-secret')
    try:
        migrate(settings);seed(settings)
        yield settings
    finally:
        assert name.startswith('firebridge_test_')
        with psycopg.connect(admin,autocommit=True) as conn:
            conn.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))


@pytest.fixture
def scope():
    return 'test-'+uuid4().hex[:10]
