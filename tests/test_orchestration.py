from uuid import uuid4
from datetime import timedelta
import pytest
from firebridge.db import connect
from firebridge.http import FetchError
from firebridge.orchestration import execute,set_owner,TaskBlocked,TaskDeferred
from firebridge.scheduler import enqueue,schedule,claim,subscribe
from firebridge.util import now

pytestmark=pytest.mark.integration


@pytest.fixture
def airflow_db(database):
    set_owner(database,'airflow')
    try:yield database
    finally:
        with connect(database) as conn:
            conn.execute("UPDATE ingest_tasks SET status='blocked',error_code='test_finished' WHERE orchestrator='airflow' AND status IN ('queued','running')")
        set_owner(database,'local')


def task(settings,kind='availability',subscription=None):
    with connect(settings) as conn:
        return enqueue(conn,kind,{},str(uuid4()),subscription)


def test_scheduler_has_single_owner(airflow_db):
    with pytest.raises(RuntimeError,match='owned by airflow'):schedule(airflow_db)
    with pytest.raises(RuntimeError,match='owned by airflow'):claim(airflow_db)


def test_failures_reach_airflow_and_success_replays_without_fetch(airflow_db,monkeypatch):
    calls=[]
    def fetch(_):
        calls.append(1)
        if len(calls)==1:raise FetchError('network_error')
        return {'verified':True}
    monkeypatch.setattr('firebridge.ingest.refresh_availability',fetch)
    tid=task(airflow_db)
    with pytest.raises(RuntimeError,match='network_error'):execute(airflow_db,tid)
    with connect(airflow_db) as conn:
        assert conn.execute('SELECT status FROM ingest_tasks WHERE id=%s',(tid,)).fetchone()['status']=='failed'
    assert execute(airflow_db,tid)=={'verified':True}
    assert execute(airflow_db,tid)=={'verified':True}
    assert len(calls)==2


def test_provider_wait_is_deferred_and_cannot_run_early(airflow_db,monkeypatch):
    def wait(_):raise FetchError('provider_cooldown',retry_seconds=600)
    monkeypatch.setattr('firebridge.ingest.refresh_availability',wait)
    tid=task(airflow_db)
    with pytest.raises(TaskDeferred):execute(airflow_db,tid)
    with connect(airflow_db) as conn:
        row=conn.execute('SELECT status,available_at FROM ingest_tasks WHERE id=%s',(tid,)).fetchone()
        assert row['status']=='queued' and row['available_at']>now()+timedelta(minutes=9)
    with pytest.raises(TaskDeferred,match='task_not_due'):execute(airflow_db,tid)


def test_blocking_error_disables_subscription_and_never_exposes_url(airflow_db,scope,monkeypatch):
    sid=subscribe(airflow_db,'MODIS_NRT',scope,[-6,34,-4,36],'2024-01-17',enabled=True)
    def blocked(*_):raise FetchError('invalid_firms_payload',blocked=True)
    monkeypatch.setattr('firebridge.ingest.firms',blocked)
    tid=task(airflow_db,'firms',sid)
    with pytest.raises(TaskBlocked,match='invalid_firms_payload'):execute(airflow_db,tid)
    with connect(airflow_db) as conn:
        assert not conn.execute('SELECT enabled FROM ingestion_subscriptions WHERE id=%s',(sid,)).fetchone()['enabled']


def test_cannot_switch_owner_while_ingestion_active(airflow_db):
    tid=task(airflow_db)
    with connect(airflow_db) as conn:
        conn.execute("UPDATE ingest_tasks SET status='running',lease_expires_at=now()+interval '10 minutes' WHERE id=%s",(tid,))
    with pytest.raises(RuntimeError,match='active ingestion'):set_owner(airflow_db,'local')


def test_disabled_backfill_cannot_retry_in_airflow(airflow_db,scope,monkeypatch):
    sid=subscribe(airflow_db,'MODIS_NRT',scope,[-6,34,-4,36],'2024-01-17',enabled=True,mode='backfill',end='2024-01-18')
    calls=[]
    def failure(*_):calls.append(1);raise FetchError('network_error')
    monkeypatch.setattr('firebridge.ingest.firms',failure)
    tid=task(airflow_db,'firms',sid)
    with pytest.raises(RuntimeError,match='network_error'):execute(airflow_db,tid)
    with connect(airflow_db) as conn:
        conn.execute('UPDATE ingestion_subscriptions SET enabled=false WHERE id=%s',(sid,))
    with pytest.raises(TaskBlocked,match='subscription_disabled'):execute(airflow_db,tid)
    assert len(calls)==1


def test_finished_backfill_stays_authorized_for_queued_windows(airflow_db,scope):
    sid=subscribe(airflow_db,'MODIS_NRT',scope,[-6,34,-4,36],'2024-01-17',enabled=True,mode='backfill',end='2024-01-18')
    schedule(airflow_db,owner='airflow')
    with connect(airflow_db) as conn:
        sub=conn.execute('SELECT enabled,planning_complete FROM ingestion_subscriptions WHERE id=%s',(sid,)).fetchone()
        assert sub=={'enabled':True,'planning_complete':True}
        assert conn.execute("SELECT count(*) AS n FROM ingest_tasks WHERE subscription_id=%s AND kind='firms'",(sid,)).fetchone()['n']==1
        conn.execute('UPDATE ingestion_subscriptions SET enabled=false WHERE id=%s',(sid,))
