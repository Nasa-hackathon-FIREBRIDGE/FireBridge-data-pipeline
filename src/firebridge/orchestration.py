"""Bounded Airflow entry points; PostgreSQL is an audit ledger, Airflow owns retries."""
from datetime import timedelta
from uuid import UUID, uuid4
import shutil
from psycopg.types.json import Jsonb
from .db import connect
from .http import FetchError
from .scheduler import assert_owner, schedule
from .util import now


class TaskBlocked(RuntimeError):
    pass


class TaskDeferred(RuntimeError):
    """Provider timing/budget wait; next scheduled Dag can pick up the queued task."""


def set_owner(settings, owner):
    if owner not in ('local','airflow'):
        raise ValueError('Unknown orchestrator')
    with connect(settings) as conn:
        conn.execute('SELECT owner FROM orchestration_control WHERE singleton FOR UPDATE')
        if conn.execute("SELECT 1 FROM ingest_tasks WHERE status='running' AND lease_expires_at>now() LIMIT 1").fetchone():
            raise RuntimeError('Stop scheduling and wait for active ingestion tasks before switching')
        conn.execute('UPDATE orchestration_control SET owner=%s,changed_at=now() WHERE singleton',(owner,))
        conn.execute("UPDATE ingest_tasks SET orchestrator=%s WHERE status<>'succeeded'",(owner,))
    return {'orchestrator':owner}


def plan(settings, limit=512):
    schedule(settings,owner='airflow')
    with connect(settings) as conn:
        return [str(r['id']) for r in conn.execute("""SELECT id FROM ingest_tasks WHERE orchestrator='airflow'
          AND ((status='queued' AND available_at<=now()) OR (status='running' AND lease_expires_at<now()))
          ORDER BY CASE WHEN kind='availability' THEN 0 ELSE 1 END,available_at,created_at LIMIT %s""",(limit,))]


def execute(settings, task_id):
    """Exactly one attempt. Exceptions reach Airflow; no nested queue retry loop."""
    task_id=UUID(str(task_id))
    with connect(settings) as conn:
        assert_owner(conn,'airflow')
        task=conn.execute('SELECT * FROM ingest_tasks WHERE id=%s FOR UPDATE',(task_id,)).fetchone()
        if not task or task['orchestrator']!='airflow':
            raise TaskBlocked('task_not_owned_by_airflow')
        if task['status']=='succeeded':
            return task['result']
        if task['status']=='blocked':
            raise TaskBlocked(task['error_code'] or 'blocked')
        if task['subscription_id']:
            sub=conn.execute('SELECT enabled,mode,fixed_end_exclusive FROM ingestion_subscriptions WHERE id=%s',(task['subscription_id'],)).fetchone()
            if not sub['enabled']:
                raise TaskBlocked('subscription_disabled')
        if task['status']=='running' and task['lease_expires_at']>now():
            raise TaskDeferred('task_already_running')
        if task['available_at']>now():
            raise TaskDeferred('task_not_due')
        task=conn.execute("""UPDATE ingest_tasks SET status='running',attempt=attempt+1,lease_token=%s,
          lease_expires_at=now()+interval '20 minutes',completed_at=NULL WHERE id=%s RETURNING *""",
          (uuid4(),task_id)).fetchone()
    try:
        from .ingest import firms,refresh_availability,assert_lease
        from .weather import fetch_weather
        from .news import fetch_news
        from .science import discover
        if task['kind']=='availability': result=refresh_availability(settings)
        else:
            adapter={'firms':firms,'weather':fetch_weather,'news':fetch_news,'cmr':discover}[task['kind']]
            result=adapter(settings,task['request'],task)
        with connect(settings) as conn:
            assert_lease(conn,task)
            conn.execute("""UPDATE ingest_tasks SET status='succeeded',completed_at=now(),lease_expires_at=NULL,
              result=%s,error_code=NULL WHERE id=%s AND lease_token=%s""",(Jsonb(result),task_id,task['lease_token']))
        return result
    except Exception as exc:
        code=exc.code if isinstance(exc,FetchError) else type(exc).__name__
        blocked=isinstance(exc,FetchError) and exc.blocked
        deferred=code in ('local_rate_budget','provider_cooldown','outside_provider_available_dates','provider_availability_unknown') or (isinstance(exc,FetchError) and exc.http_status==429)
        status='blocked' if blocked else ('queued' if deferred else 'failed')
        with connect(settings) as conn:
            conn.execute("""UPDATE ingest_tasks SET status=%s,error_code=%s,lease_expires_at=NULL,
              completed_at=CASE WHEN %s='queued' THEN NULL ELSE now() END,
              available_at=%s WHERE id=%s AND lease_token=%s""",
              (status,code,status,now()+timedelta(seconds=getattr(exc,'retry_seconds',0) if deferred else 0),task_id,task['lease_token']))
            if blocked and task['subscription_id']:
                conn.execute('UPDATE ingestion_subscriptions SET enabled=false WHERE id=%s',(task['subscription_id'],))
        if blocked: raise TaskBlocked(code) from None
        if deferred: raise TaskDeferred(code) from None
        # No provider URL/credential-bearing exception can escape into Airflow logs.
        raise RuntimeError(code) from None


def analytics_scopes(settings):
    with connect(settings) as conn:
        return [r['scope_key'] for r in conn.execute("SELECT scope_key FROM release_aliases WHERE alias='best_available' ORDER BY scope_key")]


def health(settings, stale_hours=6):
    with connect(settings) as conn:
        failed=conn.execute("SELECT count(*) AS n FROM ingest_tasks WHERE status IN ('failed','blocked') AND error_code IS DISTINCT FROM 'subscription_disabled'").fetchone()['n']
        stale=conn.execute("""SELECT s.id,s.feed_id,s.scope_key FROM ingestion_subscriptions s WHERE s.enabled AND NOT s.planning_complete
          AND s.next_due_at<now()-(%s * interval '1 hour')""",(stale_hours,)).fetchall()
        builds=conn.execute("SELECT count(*) AS n FROM analytics_builds WHERE status='building' AND started_at<now()-interval '1 hour'").fetchone()['n']
        stalled=conn.execute("""SELECT s.id,s.feed_id,s.scope_key FROM ingestion_subscriptions s
          JOIN ingest_tasks t ON t.subscription_id=s.id WHERE s.enabled AND NOT s.planning_complete
          GROUP BY s.id HAVING min(t.created_at)<now()-greatest(%s*interval '1 hour',s.interval_seconds*3*interval '1 second')
          AND (max(t.completed_at) FILTER(WHERE t.status='succeeded') IS NULL OR
            max(t.completed_at) FILTER(WHERE t.status='succeeded')<now()-greatest(%s*interval '1 hour',s.interval_seconds*3*interval '1 second'))""",
          (stale_hours,stale_hours)).fetchall()
        stale_analytics=conn.execute("""SELECT DISTINCT a.scope_key FROM release_aliases a
          JOIN data_releases r ON r.id=a.release_id
          LEFT JOIN analytics_latest l ON l.scope_key=a.scope_key
          LEFT JOIN analytics_builds b ON b.id=l.build_id
          WHERE a.alias IN ('best_available','weather_historical','weather_recent','reports')
          AND EXISTS(SELECT 1 FROM release_aliases x WHERE x.scope_key=a.scope_key AND x.alias='best_available')
          AND b.input_releases->>a.alias IS DISTINCT FROM a.release_id::text
          AND r.published_at<now()-interval '2 hours'""").fetchall()
        free=shutil.disk_usage(settings.data_dir).free
        return {'failed_or_blocked_tasks':failed,'overdue_subscriptions':stale,'subscriptions_without_recent_success':stalled,
                'stuck_analytics_builds':builds,'stale_analytics':stale_analytics,'disk_free_bytes':free,
                'healthy':not(failed or stale or stalled or builds or stale_analytics or free<5*1024**3)}
