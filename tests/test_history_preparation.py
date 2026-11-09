"""Exercise the launcher against Airflow's token and paused-DAG API contract."""
import importlib.util
import json
from pathlib import Path

import httpx
import pytest


@pytest.mark.parametrize('token_status', [200, 201])
def test_preparation_accepts_successful_tokens_and_refreshes_expired_auth(monkeypatch, token_status):
    spec = importlib.util.spec_from_file_location('history_preparation', Path(__file__).parents[1] / 'deploy/history_preparation.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    client_class = httpx.Client
    calls = []
    auth_calls = 0
    expired = False

    def handle(request):
        nonlocal auth_calls, expired
        path = request.url.path
        calls.append((request.method, path, json.loads(request.content) if request.content else None))
        if path == '/auth/token':
            auth_calls += 1
            return httpx.Response(token_status, json={'access_token': f'test-token-{auth_calls}'})
        if not expired:
            expired = True
            return httpx.Response(401, json={'detail': 'expired'})
        assert request.headers['Authorization'] == 'Bearer test-token-2'
        if request.method == 'PATCH':
            return httpx.Response(200, json={})
        if path.endswith('/dagRuns'):
            if request.method == 'GET':
                return httpx.Response(200, json={'dag_runs': []})
            return httpx.Response(201, json={})
        if '/dagRuns/' in path:
            return httpx.Response(200, json={'state': 'success'})
        return httpx.Response(200, json={'is_paused': True})

    monkeypatch.setenv('AIRFLOW_ADMIN_USER', 'fixture')
    monkeypatch.setenv('AIRFLOW_ADMIN_PASSWORD', 'fixture-only')
    monkeypatch.setattr(module.httpx, 'Client', lambda **kw: client_class(transport=httpx.MockTransport(handle), **kw))
    module.main()
    assert auth_calls == 2
    triggered = [path.split('/')[4] for method, path, body in calls if method == 'POST' and path.endswith('/dagRuns')]
    assert triggered == ['firebridge_history_audit', 'firebridge_history_benchmark']
    for dag in triggered:
        updates = [body for method, path, body in calls if method == 'PATCH' and path == '/api/v2/dags/' + dag]
        assert updates == [{'is_paused': False}, {'is_paused': True}]
