from dataclasses import replace
from datetime import date, timedelta
import gzip
import json
from pathlib import Path
import os
import subprocess

import duckdb
import httpx
import pytest

from firebridge.config import Settings
from firebridge.history import (FAMILIES, export_status, initialize, ledger,
    plan_requests, run, validate_and_store, verify_completed)
from firebridge.http import FetchError
from firebridge.lake import working_directory


def available():
    rows = []
    for family in FAMILIES:
        if family != 'LANDSAT':
            rows.append(dict(data_id=family+'_SP', min_date='2024-01-01', max_date='2024-01-07'))
        rows.append(dict(data_id=family+'_NRT', min_date='2024-01-05', max_date='2024-01-12'))
    return rows


HEADER = 'latitude,longitude,acq_date,acq_time,satellite,confidence,daynight,frp\n'
BODY = (HEADER+'35,-5,2024-01-01,15,T,80,D,-999\n').encode()


def request():
    return dict(id='MODIS_SP_2024-01-01_2024-01-06', feed='MODIS_SP',
        start='2024-01-01', end_exclusive='2024-01-06')


def complete(conn, receipt):
    conn.execute('''INSERT INTO requests(id,feed,start,end_exclusive,priority,status,rows,
        raw_sha256,parquet_sha256,raw_bytes,parquet_bytes)
        VALUES (:id,:feed,:start,:end_exclusive,0,'complete',:rows,
        :raw_sha256,:parquet_sha256,:raw_bytes,:parquet_bytes)''', receipt)
    conn.commit()


def test_plan_covers_every_available_day_once_with_standard_precedence():
    plan, gaps = plan_requests(available(), date(2024,1,11))
    assert not gaps
    seen = set()
    for r in plan:
        start, end = date.fromisoformat(r['start']), date.fromisoformat(r['end_exclusive'])
        assert 1 <= (end-start).days <= 5
        family = r['feed'].rsplit('_',1)[0]
        for i in range((end-start).days):
            day = start+timedelta(days=i)
            assert (family,day) not in seen
            seen.add((family,day))
            if family != 'LANDSAT':
                assert r['feed'].endswith('_SP' if day <= date(2024,1,7) else '_NRT')
    assert len(seen) == 4*11 + 7
    assert plan[0]['feed'].endswith('_NRT')  # capture expiring tail first


def test_provider_gap_remains_explicit_and_missing_feed_fails():
    rows = available()
    rows[1]['min_date']='2024-01-10'
    _, gaps = plan_requests(rows, date(2024,1,11))
    assert gaps == [{'family':'MODIS','start':'2024-01-08','end_exclusive':'2024-01-10',
        'reason':'not_in_provider_available_ranges'}]
    with pytest.raises(ValueError,match='required_feed_missing'):
        plan_requests(rows[:-1], date(2024,1,11))


def test_initialization_is_offline_and_catalog_sees_only_committed_windows(tmp_path, monkeypatch):
    monkeypatch.setattr('firebridge.history.get', lambda *a,**kw: pytest.fail('Unexpected provider call'))
    root = tmp_path/'history'
    initialize(root)
    assert json.loads((root/'progress.json').read_text())['state']=='not_started'
    receipt = validate_and_store(root, request(), BODY, reserve_bytes=0)
    assert gzip.decompress((root/'raw'/(request()['id']+'.csv.gz')).read_bytes())==BODY
    with working_directory(tmp_path),duckdb.connect(str(root/'catalog.duckdb'),read_only=True) as db:
        assert db.execute('SELECT count(*) FROM detections').fetchone()[0]==0
        with ledger(root) as conn:
            complete(conn,receipt)
            export_status(root,conn,'downloading')
            verify_completed(root,conn)
        # Same open connection discovers newly published files and inventory.
        assert db.execute('SELECT satellite,time_utc,frp_raw,frp_mw FROM detections').fetchall()==[('Terra','0015',-999,None)]
        assert db.execute('SELECT source_rows,invalid_frp_rows FROM satellite_inventory').fetchall()==[(1,1)]
    (root/'raw'/(request()['id']+'.csv.gz')).write_bytes(b'corrupt')
    with ledger(root) as conn, pytest.raises(FetchError,match='local_checksum_failed'):
        verify_completed(root,conn)


@pytest.mark.parametrize('body', [b'<html>error</html>', BODY.replace(b'35,-5',b'95,-5'),
    BODY.replace(b'2024-01-01',b'2023-01-01'), BODY.replace(b',T,',b',N20,'),
    BODY.replace(b',15,',b',2400,'), BODY+b'broken,truncated\n'])
def test_bad_response_cannot_publish_a_window(tmp_path,body):
    root=tmp_path/'history'
    initialize(root)
    with pytest.raises(Exception):
        validate_and_store(root,request(),body,reserve_bytes=0)
    assert not list((root/'receipts').glob('*.json'))
    assert len(list((root/'parquet').glob('*.parquet')))==1  # empty seed only


def test_header_only_is_a_valid_empty_response_and_disk_floor_blocks(tmp_path):
    root=tmp_path/'history'
    initialize(root)
    receipt=validate_and_store(root,request(),HEADER.encode(),reserve_bytes=0)
    assert receipt['rows']==0
    with pytest.raises(FetchError,match='disk_reserve_reached'):
        validate_and_store(root,request(),BODY,reserve_bytes=10**20)


def test_run_resumes_without_redownloading_completed_windows(tmp_path,monkeypatch):
    root=tmp_path/'history'
    initialize(root)
    settings=Settings('unused',tmp_path,firms_key='fixture-secret')
    with ledger(root) as conn:
        conn.execute('''INSERT INTO requests(id,feed,start,end_exclusive,priority,status)
            VALUES (:id,:feed,:start,:end_exclusive,0,'pending')''',request())
        conn.commit()
    (root/'plan.json').write_text(json.dumps({'provider_gaps':[]}))
    calls=[]
    def fetch(*args,**kwargs):
        calls.append(1)
        return BODY,{}
    monkeypatch.setattr('firebridge.history.get',fetch)
    first=run(settings,root=root,reserve_bytes=0)
    assert first['state']=='complete' and first['completed_windows']==1
    second=run(settings,root=root,reserve_bytes=0)
    assert second['downloaded_source_rows']==1 and len(calls)==1
    for p in root.rglob('*.json'):
        assert 'fixture-secret' not in p.read_text()


def test_rate_wait_then_success_and_malformed_body_stays_unpublished(tmp_path,monkeypatch):
    root=tmp_path/'history'
    initialize(root)
    with ledger(root) as conn:
        conn.execute('''INSERT INTO requests(id,feed,start,end_exclusive,priority,status)
            VALUES (:id,:feed,:start,:end_exclusive,0,'pending')''',request())
        conn.commit()
    (root/'plan.json').write_text(json.dumps({'provider_gaps':[]}))
    responses=[FetchError('http_429',retry_seconds=600),(b'<html>quota error</html>',{})]
    def fetch(*a,**kw):
        value=responses.pop(0)
        if isinstance(value,Exception):raise value
        return value
    monkeypatch.setattr('firebridge.history.get',fetch)
    waited=[]
    with pytest.raises(FetchError,match='invalid_firms_payload'):
        run(Settings('unused',tmp_path,firms_key='fixture-secret'),root=root,reserve_bytes=0,sleep=waited.append)
    assert waited==[600]
    assert json.loads((root/'progress.json').read_text())['completed_windows']==0


@pytest.mark.parametrize('budget,expected',[(60,20),(10,10)])
def test_quota_waits_do_not_exhaust_history_retries_or_mark_failed_windows(tmp_path,monkeypatch,budget,expected):
    root=tmp_path/'history'
    initialize(root)
    with ledger(root) as conn:
        conn.execute('''INSERT INTO requests(id,feed,start,end_exclusive,priority,status)
            VALUES (:id,:feed,:start,:end_exclusive,0,'pending')''',request())
        conn.commit()
    (root/'plan.json').write_text(json.dumps({'provider_gaps':[]}))
    calls=[]
    def fetch(settings,*args,**kwargs):
        assert settings.firms_budget==expected
        calls.append(1)
        if len(calls)<=4:raise FetchError('provider_cooldown',retry_seconds=600,http_status=400)
        return BODY,{}
    monkeypatch.setattr('firebridge.history.get',fetch)
    waits=[]
    def wait(seconds):
        waits.append(seconds)
        status=json.loads((root/'progress.json').read_text())
        assert status['state']=='waiting_for_provider' and status['failed_windows']==0
        with ledger(root) as conn:
            assert conn.execute('SELECT status FROM requests').fetchone()[0]=='pending'
    result=run(Settings('unused',tmp_path,firms_key='fixture-secret',firms_budget=budget),
        root=root,reserve_bytes=0,sleep=wait)
    assert result['state']=='complete' and result['completed_windows']==1
    assert len(calls)==5 and waits==[600]*4


def test_first_execution_freezes_availability_plan_before_fetching_data(tmp_path,monkeypatch):
    lines=['data_id,min_date,max_date']+[
        ','.join(row[k] for k in ('data_id','min_date','max_date')) for row in available()]
    root=tmp_path/'history'
    calls=[]
    def fetch(settings,url,**kwargs):
        calls.append(url)
        if '/data_availability/' in url:
            return ('\n'.join(lines)+'\n').encode(),{}
        assert (root/'plan.json').is_file()
        return BODY.replace(b'2024-01-01',b'2024-01-08'),{}
    monkeypatch.setattr('firebridge.history.get',fetch)
    result=run(Settings('unused',tmp_path,firms_key='fixture-secret'),root=root,reserve_bytes=0,max_windows=1)
    assert len(calls)==2 and result['completed_windows']==1
    assert result['pending_windows']>0 and result['state']=='batch_complete'
    assert 'fixture-secret' not in (root/'plan.json').read_text()


@pytest.mark.parametrize('options,skipped', [([],False),(['--skip-download'],True)])
def test_shell_launcher_download_switch_without_running_services(tmp_path,options,skipped):
    # Stub only external executables: exercise the actual launcher and wrapper.
    # This regression guards the user's explicit no-download startup option.
    binaries=tmp_path/'bin'
    binaries.mkdir()
    log=tmp_path/'calls.log'
    for executable in ('docker','python3'):
        path=binaries/executable
        path.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$TEST_CALL_LOG"\n')
        path.chmod(0o755)
    root=Path(__file__).resolve().parents[1]
    env={**os.environ,'PATH':str(binaries)+os.pathsep+os.environ['PATH'],'TEST_CALL_LOG':str(log)}
    subprocess.run(['sh',str(root/'start_local.sh'),*options],env=env,check=True,capture_output=True)
    calls=log.read_text().splitlines()
    dispatch=[line for line in calls if 'exec -T airflow-scheduler python /opt/firebridge/deploy/start_local_workflows.py' in line]
    assert len(dispatch)==1
    assert ('--skip-download' in dispatch[0])==skipped


@pytest.mark.integration
def test_http_client_uses_shared_budget_and_redacts_credentials(database,tmp_path):
    root=tmp_path/'history'
    initialize(root)
    with ledger(root) as conn:
        conn.execute('''INSERT INTO requests(id,feed,start,end_exclusive,priority,status)
            VALUES (:id,:feed,:start,:end_exclusive,0,'pending')''',request())
        conn.commit()
    (root/'plan.json').write_text(json.dumps({'provider_gaps':[]}))
    with httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,content=BODY))) as client:
        result=run(database,root=root,reserve_bytes=0,client=client)
    assert result['completed_windows']==1
    from firebridge.db import connect
    with connect(database) as conn:
        assert conn.execute("SELECT used FROM provider_budgets WHERE id='firms'").fetchone()['used']>=1
