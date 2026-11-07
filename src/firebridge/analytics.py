"""Build dbt models privately, verify them, then publish all marts in one transaction."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
from uuid import uuid4
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from psycopg.types.json import Jsonb
from .db import connect
from .store import Store
from .util import digest

MODELS=('daily_detections','query_coverage','daily_weather','daily_reports','area_daily_context')


def project_dir():
    return Path(os.environ.get('FIREBRIDGE_DBT_PROJECT',Path(__file__).resolve().parents[2]/'dbt')).resolve()


def model_hash(project):
    paths=sorted(p for p in project.rglob('*') if p.is_file() and p.suffix in ('.sql','.yml') and not set(p.relative_to(project).parts)&{'target','logs','dbt_packages'})
    if not paths: raise ValueError('dbt project not found')
    h=hashlib.sha256()
    for p in paths: h.update(str(p.relative_to(project)).encode()+b'\0'+p.read_bytes())
    dependency_lock=project.parent/'deploy'/'requirements-dbt.lock'
    if dependency_lock.exists():h.update(dependency_lock.read_bytes())
    h.update(Path(__file__).read_bytes())
    return h.hexdigest()


def dbt_environment(settings,schema):
    info=conninfo_to_dict(settings.database_url)
    env=dict(os.environ)
    env.update(DBT_HOST=info.get('host','localhost'),DBT_PORT=info.get('port','5432'),
      DBT_DATABASE=info['dbname'],DBT_USER=info.get('user','firebridge'),DBT_PASSWORD=info.get('password',''),
      DBT_SSLMODE=info.get('sslmode','prefer'),DBT_BUILD_SCHEMA=schema,DBT_SEND_ANONYMOUS_USAGE_STATS='false',
      PGOPTIONS='-c timezone=UTC -c statement_timeout=600000')
    if os.environ.get('FIREBRIDGE_DBT_PASSWORD'):
        env.update(DBT_USER='firebridge_transform',DBT_PASSWORD=os.environ['FIREBRIDGE_DBT_PASSWORD'])
    return env


def build(settings,scope,*,force=False,project=None,dbt_bin=None):
    project=Path(project or project_dir())
    executable=dbt_bin or os.environ.get('FIREBRIDGE_DBT_BIN','dbt')
    if not shutil.which(executable): raise ValueError('dbt executable unavailable; use the Airflow image or configure FIREBRIDGE_DBT_BIN')
    build_id=uuid4();schema='fb_build_'+build_id.hex
    work=settings.data_dir/'analytics'/str(build_id)
    code=model_hash(project)
    # A session lock spans dbt's separate connections; release pinning happens after acquiring it.
    with connect(settings) as lock:
        lock.autocommit=True
        if not lock.execute('SELECT pg_try_advisory_lock(hashtextextended(%s,0)) AS ok',('analytics:'+scope,)).fetchone()['ok']:
            raise RuntimeError('analytics_scope_busy')
        with connect(settings) as conn:
            inputs={r['alias']:str(r['release_id']) for r in conn.execute("""SELECT alias,release_id FROM release_aliases
              WHERE scope_key=%s AND alias IN ('best_available','weather_historical','weather_recent','reports') ORDER BY alias""",(scope,))}
            if 'best_available' not in inputs: raise ValueError('No published satellite release for scope')
            signature=digest([scope,inputs,code])
            current=conn.execute('SELECT b.* FROM analytics_latest l JOIN analytics_builds b ON b.id=l.build_id WHERE l.scope_key=%s',(scope,)).fetchone()
            if current and current['signature']==signature and not force:
                return {'build_id':str(current['id']),'scope_key':scope,'status':'unchanged'}
            conn.execute("INSERT INTO analytics_builds(id,scope_key,signature,model_sha256,status,input_releases) VALUES (%s,%s,%s,%s,'building',%s)",
                         (build_id,scope,signature,code,Jsonb(inputs)))
            for alias,rid in inputs.items():
                conn.execute('INSERT INTO analytics_inputs VALUES (%s,%s,%s)',(build_id,alias,rid))
            env=dbt_environment(settings,schema)
            conn.execute(sql.SQL('CREATE SCHEMA {} AUTHORIZATION {}').format(sql.Identifier(schema),sql.Identifier(env['DBT_USER'])))
        work.mkdir(parents=True,exist_ok=False)
        artifacts_uri=None
        try:
            arguments=[executable,'build','--project-dir',str(project),'--profiles-dir',str(project),
                '--target-path',str(work/'target'),'--log-path',str(work/'logs'),'--vars',json.dumps({'build_id':str(build_id)}),'--no-use-colors']
            with (work/'console.log').open('w') as output:
                result=subprocess.run(arguments,env=env,stdout=output,stderr=subprocess.STDOUT,timeout=1800,check=False)
            report_path=work/'target'/'run_results.json'
            if report_path.exists():
                artifacts_uri=Store(settings.data_dir).file(report_path).uri
            if result.returncode!=0: raise RuntimeError('dbt_build_failed')
            report=json.loads(report_path.read_text())
            if not report.get('results') or any(r['status'] not in ('success','pass') for r in report['results']):
                raise RuntimeError('dbt_results_not_all_passed')
            built={r['unique_id'].split('.')[-1] for r in report['results'] if r['unique_id'].startswith('model.')}
            if not set(MODELS)<=built: raise RuntimeError('dbt_missing_required_models')
            with connect(settings) as conn:
                counts={}
                for model in MODELS:
                    # Match columns by name; accidental model reordering cannot corrupt publication.
                    columns=[r['column_name'] for r in conn.execute("""SELECT column_name FROM information_schema.columns
                      WHERE table_schema='analytics' AND table_name=%s ORDER BY ordinal_position""",(model,))]
                    fields=sql.SQL(',').join(map(sql.Identifier,columns))
                    bad=conn.execute(sql.SQL('SELECT 1 FROM {}.{} WHERE build_id IS DISTINCT FROM %s OR scope_key IS DISTINCT FROM %s LIMIT 1').format(sql.Identifier(schema),sql.Identifier(model)),(build_id,scope)).fetchone()
                    if bad: raise RuntimeError('candidate_scope_mismatch')
                    inserted=conn.execute(sql.SQL('INSERT INTO analytics.{} ({}) SELECT {} FROM {}.{}').format(
                        sql.Identifier(model),fields,fields,sql.Identifier(schema),sql.Identifier(model)))
                    counts[model]=inserted.rowcount
                if not counts['daily_detections'] or not counts['area_daily_context']:
                    raise RuntimeError('empty_analytics_output')
                conn.execute("UPDATE analytics_builds SET status='published',finished_at=now(),artifacts_uri=%s WHERE id=%s",(artifacts_uri,build_id))
                conn.execute("""INSERT INTO analytics_latest(scope_key,build_id) VALUES (%s,%s)
                  ON CONFLICT(scope_key) DO UPDATE SET build_id=EXCLUDED.build_id,published_at=now()""",(scope,build_id))
                conn.execute("SELECT pg_notify('firebridge_analytics',%s)",(json.dumps({'build_id':str(build_id),'scope_key':scope}),))
            return {'build_id':str(build_id),'scope_key':scope,'status':'published','rows':counts,'input_releases':inputs}
        except Exception as exc:
            code=str(exc) if isinstance(exc,RuntimeError) and str(exc).replace('_','').isalnum() else type(exc).__name__
            with connect(settings) as conn:
                conn.execute("UPDATE analytics_builds SET status='failed',finished_at=now(),error_code=%s,artifacts_uri=%s WHERE id=%s",(code,artifacts_uri,build_id))
            raise RuntimeError(f'analytics_failed:{build_id}:{code}') from None
        finally:
            with connect(settings) as conn:
                conn.execute(sql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(sql.Identifier(schema)))
