"""Manual offline history preparation. All workflows start paused; no provider calls."""
from datetime import datetime,timedelta,timezone
from airflow.sdk import dag,task

START=datetime(2026,1,1,tzinfo=timezone.utc)


def reserve_bytes(settings):
    import os
    from firebridge.db import connect
    if os.environ.get('FIREBRIDGE_VALIDATION')=='isolated-firebridge-validation':
        with connect(settings) as db:
            if db.execute("SELECT 1 FROM data_releases WHERE scope_key<>'validation-smoke' LIMIT 1").fetchone():
                raise ValueError('Validation reserve override requires only synthetic validation scopes')
        return 0
    return 16*1024**3


@dag(dag_id='firebridge_history_audit',schedule=None,start_date=START,catchup=False,
     max_active_runs=1,is_paused_upon_creation=True,tags=['firebridge','history','quality'],
     doc_md='Checks every acquired window offline: gzip/Parquet/daily checksums, row support, quality, source/date coverage. Reports /data/history-serving/audit.json. Does not import into PostGIS or fetch new data.')
def history_audit():
    @task(pool='firebridge_ingestion',execution_timeout=timedelta(hours=12),retries=0)
    def audit_archive():
        from airflow.exceptions import AirflowFailException
        from firebridge.config import Settings
        from firebridge.history_serving import audit
        report=audit(Settings.load())
        if report['state']!='passed':raise AirflowFailException('History audit failed; inspect /data/history-serving/audit.json')
        return {k:v for k,v in report.items() if k!='results'}
    audit_archive()


@dag(dag_id='firebridge_history_benchmark',schedule=None,start_date=START,catchup=False,
     max_active_runs=1,is_paused_upon_creation=True,tags=['firebridge','history','benchmark'],
     doc_md='Requires a successful current history audit. Loads a representative real window per available feed into an isolated temporary PostgreSQL database, measures storage, indexes and query performance, saves /data/history-serving/benchmark.json, then removes only its own database/files. Main releases stay unchanged.')
def history_benchmark():
    @task(pool='firebridge_ingestion',execution_timeout=timedelta(hours=4),retries=0)
    def measure_import():
        from firebridge.config import Settings
        from firebridge.history_serving import benchmark
        settings=Settings.load()
        return benchmark(settings,reserve_bytes=reserve_bytes(settings))
    measure_import()


@dag(dag_id='firebridge_history_load',schedule=None,start_date=START,catchup=False,
     max_active_runs=1,is_paused_upon_creation=True,tags=['firebridge','history','publication'],
     doc_md='Explicit bounded import from existing checksum-verified history. Conf: scope (default global), bbox (default world), max_windows (default 3, maximum 50), request_ids (optional), max_rows_per_window (default 2000000), database_budget_gib (default 100). Publishes complete daily partitions and immutable releases; retries reuse committed partitions. Does not start downloads. Capacity review required before scaling. Runs dbt after a successful batch.')
def history_load():
    @task(pool='firebridge_ingestion',execution_timeout=timedelta(hours=4),retries=0)
    def load_batch():
        from airflow.sdk import get_current_context
        from firebridge.config import Settings
        from firebridge.history_serving import load,GIB
        conf=dict(get_current_context()['dag_run'].conf or {})
        allowed={'scope','bbox','max_windows','request_ids','max_rows_per_window','database_budget_gib'}
        if set(conf)-allowed:raise ValueError('Unknown history-load configuration')
        budget=conf.pop('database_budget_gib',100)
        if not isinstance(budget,int) or not 1<=budget<=150:raise ValueError('Database budget must be 1–150 GiB')
        settings=Settings.load()
        result=load(settings,max_database_bytes=budget*GIB,reserve_bytes=reserve_bytes(settings),**conf)
        return {'scopes':result['scopes'],'new_windows':result['new_windows'],'report':'/data/history-serving/load-'+result['scope']+'.json'}
    @task(pool='firebridge_analytics',execution_timeout=timedelta(minutes=40),retries=1)
    def publish_analytics(imported):
        from firebridge.config import Settings
        from firebridge.analytics import build
        return [build(Settings.load(),scope) for scope in imported['scopes']]
    publish_analytics(load_batch())


history_audit()
history_benchmark()
history_load()
