"""Provider quota responses must wait without hiding unrelated HTTP failures."""
from contextlib import contextmanager
from datetime import timedelta

import httpx
import pytest

from firebridge.config import Settings
from firebridge.http import FetchError, get
from firebridge.util import now


@pytest.mark.parametrize('status,body,retry_after,delay', [
    (400, b'Exceeding allowed transaction limit.', '', 600),
    (429, b'Too many requests', '900', 900),
])
def test_firms_quota_sets_shared_cooldown_without_exposing_response(monkeypatch,tmp_path,status,body,retry_after,delay):
    updates=[]
    class Connection:
        def execute(self,query,params):updates.append((query,params))
    @contextmanager
    def connect(_):yield Connection()
    monkeypatch.setattr('firebridge.http.connect',connect)
    monkeypatch.setattr('firebridge.http.firms_slot',lambda _:None)
    clock=now()
    monkeypatch.setattr('firebridge.http.now',lambda:clock)
    settings=Settings('unused',tmp_path,firms_key='private-fixture-key')
    with httpx.Client(transport=httpx.MockTransport(lambda _:httpx.Response(
            status,content=body,headers={'Retry-After':retry_after}))) as client:
        with pytest.raises(FetchError) as caught:
            get(settings,'https://example.test/private-fixture-key',firms=True,client=client)
    error=caught.value
    assert str(error)=='provider_cooldown' and not error.blocked
    assert error.http_status==status and error.retry_seconds==delay
    assert len(updates)==1 and 'GREATEST' in updates[0][0]
    assert updates[0][1]==(clock+timedelta(seconds=delay),)


@pytest.mark.parametrize('firms,body', [
    (True,b'Invalid date or source'),
    (False,b'Exceeding allowed transaction limit.'),
])
def test_other_bad_requests_remain_errors(monkeypatch,tmp_path,firms,body):
    monkeypatch.setattr('firebridge.http.firms_slot',lambda _:None)
    with httpx.Client(transport=httpx.MockTransport(lambda _:httpx.Response(400,content=body))) as client:
        with pytest.raises(FetchError) as caught:
            get(Settings('unused',tmp_path),'https://example.test',firms=firms,client=client)
    assert str(caught.value)=='http_400' and caught.value.http_status==400


@pytest.mark.integration
def test_quota_cooldown_prevents_another_http_request(database):
    from firebridge.db import connect
    with connect(database) as conn:
        conn.execute("DELETE FROM provider_budgets WHERE id='firms'")
    calls=[]
    def respond(_):
        calls.append(1)
        return httpx.Response(400,content=b'Exceeding allowed transaction limit.')
    try:
        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            with pytest.raises(FetchError,match='provider_cooldown'):
                get(database,'https://example.test',firms=True,client=client)
            with pytest.raises(FetchError,match='provider_cooldown'):
                get(database,'https://example.test',firms=True,client=client)
        assert len(calls)==1
        with connect(database) as conn:
            blocked=conn.execute("SELECT blocked_until FROM provider_budgets WHERE id='firms'").fetchone()['blocked_until']
            assert blocked>now()+timedelta(minutes=9)
    finally:
        with connect(database) as conn:
            conn.execute("DELETE FROM provider_budgets WHERE id='firms'")
