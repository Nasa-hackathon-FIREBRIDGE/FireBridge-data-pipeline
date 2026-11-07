"""Private, single-server workflows. All Dags start paused; no parse-time I/O."""
from datetime import datetime,timedelta,timezone
from airflow.sdk import dag,task

DEFAULT={'retries':3,'retry_delay':timedelta(minutes=10),'retry_exponential_backoff':True}
START=datetime(2026,1,1,tzinfo=timezone.utc)


@dag(dag_id='firebridge_ingestion',schedule='*/15 * * * *',start_date=START,
     catchup=False,max_active_runs=1,is_paused_upon_creation=True,default_args=DEFAULT,
     tags=['firebridge','ingestion'],doc_md='Bounded subscribed windows. Provider waits remain queued; blocked/failed windows are visible in task_health. Explicit subscription backfills handle history; catchup is disabled.')
def ingestion():
    @task
    def plan_windows():
        from firebridge.config import Settings
        from firebridge.orchestration import plan
        return plan(Settings.load())

    @task(pool='firebridge_ingestion',execution_timeout=timedelta(minutes=15))
    def ingest_window(ledger_id):
        from airflow.exceptions import AirflowFailException,AirflowSkipException
        from firebridge.config import Settings
        from firebridge.orchestration import execute,TaskBlocked,TaskDeferred
        try: return execute(Settings.load(),ledger_id)
        except TaskBlocked as exc: raise AirflowFailException(str(exc)) from None
        except TaskDeferred as exc: raise AirflowSkipException(f'Deferred in ledger: {exc}') from None

    ingest_window.expand(ledger_id=plan_windows())


@dag(dag_id='firebridge_analytics',schedule='7,37 * * * *',start_date=START,
     catchup=False,max_active_runs=1,is_paused_upon_creation=True,default_args=DEFAULT,
     tags=['firebridge','dbt'],doc_md='Reads immutable published releases. Unchanged scopes skip rebuilding. Each scope publishes only after all required dbt models and data tests pass.')
def analytics():
    @task
    def scopes():
        from firebridge.config import Settings
        from firebridge.orchestration import analytics_scopes
        return analytics_scopes(Settings.load())

    @task(pool='firebridge_analytics',execution_timeout=timedelta(minutes=40),retries=1)
    def build_scope(scope):
        from firebridge.analytics import build
        from firebridge.config import Settings
        return build(Settings.load(),scope)

    build_scope.expand(scope=scopes())


@dag(dag_id='firebridge_health',schedule='*/30 * * * *',start_date=START,
     catchup=False,max_active_runs=1,is_paused_upon_creation=True,
     tags=['firebridge','health'],doc_md='Fails visibly when recorded tasks are failed/blocked, subscriptions are overdue, or analytics builds are stuck. Delivery of external notifications requires an operator-configured notifier.')
def health():
    @task(retries=0)
    def check():
        import json
        from airflow.exceptions import AirflowFailException
        from firebridge.config import Settings
        from firebridge.orchestration import health
        report=health(Settings.load())
        if not report['healthy']: raise AirflowFailException(json.dumps(report,default=str))
        return report
    check()


ingestion()
analytics()
health()


@dag(dag_id='firebridge_archive_import',schedule=None,start_date=START,catchup=False,
     max_active_runs=1,is_paused_upon_creation=True,tags=['firebridge','history'],
     doc_md='Manual archive import. Supply conf: path relative to /imports, format (firms or audited_modis), feed, scope, bbox, start, end, coverage_start, coverage_end. Dates are UTC end-exclusive. Bounds must come from the archive request, never inferred from hotspot timestamps.')
def archive_import():
    @task(pool='firebridge_ingestion',execution_timeout=timedelta(hours=4),retries=0)
    def import_file():
        import os
        from pathlib import Path
        from airflow.sdk import get_current_context
        from firebridge.config import Settings
        from firebridge.archive import import_archive
        from firebridge.ingest import import_modis
        from firebridge.catalog import polygon
        conf=get_current_context()['dag_run'].conf
        root=Path(os.environ.get('FIREBRIDGE_IMPORT_DIR','/imports')).resolve()
        path=(root/conf['path']).resolve()
        if not path.is_relative_to(root) or path.suffix.lower() not in ('.csv','.zip','.parquet'):
            raise ValueError('Archive path must be a CSV, ZIP or audited Parquet inside /imports')
        polygon(conf['bbox'])
        if conf.get('format','firms')=='audited_modis':
            result=import_modis(Settings.load(),path,conf['scope'],conf['bbox'],conf['start'],conf['end'])
        else:
            result=import_archive(Settings.load(),path,conf['feed'],conf['scope'],conf['bbox'],conf['start'],conf['end'],
              coverage_start=conf['coverage_start'],coverage_end=conf['coverage_end'])
        return {'scope':conf['scope'],'result':result}

    @task(pool='firebridge_analytics',execution_timeout=timedelta(minutes=40),retries=1)
    def publish_analytics(imported):
        from firebridge.analytics import build
        from firebridge.config import Settings
        return build(Settings.load(),imported['scope'])

    publish_analytics(import_file())


archive_import()


@dag(dag_id='firebridge_local_archive_lake',schedule=None,start_date=START,catchup=False,
     max_active_runs=1,is_paused_upon_creation=True,tags=['firebridge','history','local'],
     doc_md='Load every inventoried downloaded archive into compressed Parquet, preserving all rows and dates. Requires compose.local.yaml mounts. This exploration catalog is separate from validated PostGIS releases; source overlaps and questionable values remain visible.')
def local_archive_lake():
    @task(pool='firebridge_ingestion',execution_timeout=timedelta(hours=4),retries=0)
    def load_archives():
        import os
        from pathlib import Path
        from firebridge.config import Settings
        from firebridge.lake import load_all
        required=('FIREBRIDGE_ARCHIVE_DIR','FIREBRIDGE_ARCHIVE_PROFILES','FIREBRIDGE_AUDITED_MODIS')
        if not all(os.environ.get(k) for k in required):
            raise ValueError('Use the local Compose override to provide read-only archive mounts')
        return load_all(Path(os.environ[required[0]]),Path(os.environ[required[1]]),
            Settings.load().data_dir/'lake',Path(os.environ[required[2]]))
    load_archives()


local_archive_lake()


@dag(dag_id='firebridge_full_history_download',schedule=None,start_date=START,catchup=False,
     max_active_runs=1,is_paused_upon_creation=True,tags=['firebridge','history','download'],
     doc_md='Explicit full-history acquisition for the six project satellite groups. Queries live availability once, then downloads disjoint <=5-day world windows, preferring standard processing over NRT. Landsat uses the provider US/Canada footprint. Checkpoints, raw gzip, Parquet and progress live under /data/lake/history. An 8 GiB disk reserve stops acquisition safely. Re-trigger to resume; this does not enable recurring provider subscriptions or populate PostGIS.')
def full_history_download():
    @task(pool='firebridge_ingestion',execution_timeout=timedelta(days=7),retries=2,
          retry_delay=timedelta(minutes=10))
    def download_history():
        from airflow.exceptions import AirflowFailException
        from firebridge.config import Settings
        from firebridge.history import run
        from firebridge.http import FetchError
        try:
            return run(Settings.load())
        except FetchError as exc:
            if exc.blocked:
                raise AirflowFailException(exc.code+'; see /data/lake/history/progress.json') from None
            raise RuntimeError(exc.code) from None
    download_history()


full_history_download()
