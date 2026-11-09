import argparse
from datetime import timedelta
import json
from pathlib import Path
import sys
from uuid import UUID
from .catalog import FEEDS,PILOT_BBOX,seed
from .config import Settings
from .db import connect,migrate
from .util import canonical,now,utc


def bbox(value):
    from .catalog import polygon
    try:result=[float(x) for x in value.split(',')];polygon(result)
    except (ValueError,TypeError):raise argparse.ArgumentTypeError('Expected west,south,east,north')
    return result


def bounds(parser):
    parser.add_argument('--scope',default='morocco-pilot')
    parser.add_argument('--bbox',type=bbox,default=PILOT_BBOX)
    parser.add_argument('--start',required=True,help='Inclusive UTC date')
    parser.add_argument('--end',required=True,help='Exclusive UTC date')


def main():
    parser=argparse.ArgumentParser(description='FIREBRIDGE data engineering CLI; no HTTP server')
    commands=parser.add_subparsers(dest='command',required=True)
    commands.add_parser('init',help='Apply checksum-verified migrations and seed product definitions')
    commands.add_parser('status',help='Print database/release/queue health without credentials')
    commands.add_parser('register-pilot',help='Create disabled pilot subscriptions; makes no provider calls')
    p=commands.add_parser('import-modis',help='Import audited global MODIS Parquet or a regional slice');bounds(p)
    p.add_argument('--path',default='data/processed/modis_2024_2025/detections.parquet')
    p=commands.add_parser('import-archive',help='Stream a FIRMS CSV/ZIP; declare original download coverage');bounds(p)
    p.add_argument('--path',required=True);p.add_argument('--feed',choices=FEEDS,required=True)
    p.add_argument('--coverage-start',required=True);p.add_argument('--coverage-end',required=True)
    p=commands.add_parser('subscribe',help='Register a disabled subscription unless --enable is explicit');bounds(p)
    p.add_argument('--feed',required=True);p.add_argument('--mode',choices=['backfill','incremental','reconciliation'],default='backfill')
    p.add_argument('--enable',action='store_true');p.add_argument('--config',default='{}',help='Non-secret JSON adapter options')
    for name in ['enable','disable','resume']:
        p=commands.add_parser(name);p.add_argument('subscription_id',type=UUID)
    p=commands.add_parser('worker',help='Run durable schedules; disabled subscriptions do not fetch')
    p.add_argument('--once',action='store_true')
    commands.add_parser('availability',help='Explicit live FIRMS availability request')
    p=commands.add_parser('orchestrator',help='Switch the single scheduling authority; stop existing workers first')
    p.add_argument('owner',choices=['local','airflow'])
    p=commands.add_parser('build-analytics',help='Build and test dbt candidates, then atomically publish analytical views')
    p.add_argument('--scope',required=True);p.add_argument('--force',action='store_true')
    commands.add_parser('health',help='Report operational health; exit nonzero when work needs attention')
    p=commands.add_parser('fetch-weather',help='Explicit live weather point-context request');bounds(p)
    p.add_argument('--latitude',type=float,required=True);p.add_argument('--longitude',type=float,required=True)
    p.add_argument('--kind',choices=['reanalysis','model_current'],default='reanalysis')
    p=commands.add_parser('discover-science',help='Explicit live CMR catalog request');bounds(p)
    p.add_argument('--collection',required=True);p.add_argument('--updated-since')
    p=commands.add_parser('import-reports',help='Import dated report metadata and reviewed event claims')
    p.add_argument('--path',required=True);p.add_argument('--scope',default='morocco-pilot')
    p=commands.add_parser('history-audit',help='Offline checksums, row support, quality and coverage audit')
    p.add_argument('--refresh',action='store_true')
    p=commands.add_parser('history-benchmark',help='Load representative real windows into a disposable isolated database')
    p.add_argument('--max-rows-per-window',type=int,default=1_000_000)
    p.add_argument('--keep-database',action='store_true')
    p=commands.add_parser('history-load',help='Resume a bounded batch from existing history files; no provider calls')
    p.add_argument('--scope',default='global');p.add_argument('--bbox',type=bbox,default=[-180,-90,180,90])
    p.add_argument('--max-windows',type=int,default=3);p.add_argument('--max-rows-per-window',type=int,default=2_000_000)
    p.add_argument('--request-id',action='append');p.add_argument('--database-budget-gib',type=int,default=100)
    p=commands.add_parser('publish-history-catalog',help='Publish verified archive metadata for selective historical analyses; no bulk point import')
    p.add_argument('--scope',default='global')
    p=commands.add_parser('index-history',help='Build exact lossless spatial query copies from audited local history; no provider calls')
    p.add_argument('--start');p.add_argument('--end');p.add_argument('--max-windows',type=int)
    p.add_argument('--workers',type=int,choices=[1,2],default=2)
    args=parser.parse_args();settings=Settings.load();result=None
    if args.command=='index-history':
        from .history_index import build
        result=build(settings,start=args.start,end=args.end,max_windows=args.max_windows,workers=args.workers)
    elif args.command=='publish-history-catalog':
        from .history_query import publish_catalog
        result=publish_catalog(settings,args.scope)
    elif args.command=='init':
        migrate(settings);seed(settings);result={'database':'initialized','provider_calls':0}
    elif args.command=='status':
        with connect(settings) as conn:
            result={'releases':conn.execute('SELECT * FROM serving.latest_releases ORDER BY scope_key,alias').fetchall(),
             'canonical_detections':conn.execute('SELECT count(*) AS n FROM detections').fetchone()['n'],
             'subscriptions':conn.execute('SELECT * FROM serving.ingestion_health ORDER BY scope_key,feed_id').fetchall(),
             'tasks':conn.execute('SELECT status,count(*) AS count FROM ingest_tasks GROUP BY status').fetchall(),
             'open_gaps':conn.execute("SELECT count(*) AS n FROM ingestion_gaps WHERE status IN ('open','retrying')").fetchone()['n'],
             'failed_runs':conn.execute("SELECT count(*) AS n FROM pipeline_runs WHERE status='failed'").fetchone()['n']}
    elif args.command=='import-modis':
        from .ingest import import_modis
        result=import_modis(settings,args.path,args.scope,args.bbox,args.start,args.end)
    elif args.command=='import-archive':
        from .archive import import_archive
        if args.feed=='LANDSAT_NRT' and args.scope=='morocco-pilot':raise ValueError('Landsat FIRMS does not serve Morocco; choose a supported US/Canada scope')
        result=import_archive(settings,args.path,args.feed,args.scope,args.bbox,args.start,args.end,coverage_start=args.coverage_start,coverage_end=args.coverage_end)
    elif args.command in ('subscribe','register-pilot'):
        from .scheduler import subscribe
        if args.command=='subscribe':
            result={'subscription_id':subscribe(settings,args.feed,args.scope,args.bbox,args.start,mode=args.mode,
              end=args.end if args.mode=='backfill' else None,enabled=args.enable,config=json.loads(args.config))}
        else:
            ids=[]
            for feed in FEEDS:
                if feed=='LANDSAT_NRT':continue
                for mode in (['incremental','reconciliation'] if feed.endswith('NRT') else ['reconciliation']):
                    ids.append(subscribe(settings,feed,'morocco-pilot',PILOT_BBOX,'2024-01-17',mode=mode))
            for feed in ('WEATHER_ERA5','WEATHER_RECENT'):
                ids.append(subscribe(settings,feed,'morocco-pilot',PILOT_BBOX,'2024-01-17'))
            result={'subscriptions':ids,'enabled':False,'provider_calls':0}
    elif args.command in ('enable','disable','resume'):
        with connect(settings) as conn:
            row=conn.execute("UPDATE ingestion_subscriptions SET enabled=%s,next_due_at=now() WHERE id=%s RETURNING id",(args.command!='disable',args.subscription_id)).fetchone()
            if not row:raise ValueError('Subscription not found')
            if args.command=='resume':
                conn.execute("UPDATE ingest_tasks SET status='queued',attempt=0,available_at=now(),error_code=NULL,completed_at=NULL WHERE subscription_id=%s AND status IN ('blocked','failed')",(args.subscription_id,))
            if args.command=='disable':
                conn.execute("UPDATE ingest_tasks SET status='blocked',error_code='subscription_disabled' WHERE subscription_id=%s AND status='queued'",(args.subscription_id,))
            result={'subscription_id':str(args.subscription_id),'enabled':args.command!='disable'}
    elif args.command=='worker':
        from .scheduler import worker
        result=worker(settings,args.once)
    elif args.command=='availability':
        from .ingest import refresh_availability
        result=refresh_availability(settings)
    elif args.command=='orchestrator':
        from .orchestration import set_owner
        result=set_owner(settings,args.owner)
    elif args.command=='build-analytics':
        from .analytics import build
        result=build(settings,args.scope,force=args.force)
    elif args.command=='health':
        from .orchestration import health
        result=health(settings)
        if not result['healthy']:
            print(json.dumps(result,indent=2,default=str));sys.exit(1)
    elif args.command=='fetch-weather':
        from .weather import fetch_weather
        result=fetch_weather(settings,dict(scope_key=args.scope,latitude=args.latitude,longitude=args.longitude,
           start=args.start,end_exclusive=args.end,data_kind=args.kind))
    elif args.command=='discover-science':
        from .science import discover
        result=discover(settings,dict(scope_key=args.scope,bbox=args.bbox,start=args.start,end_exclusive=args.end,
                       collection_concept_id=args.collection,updated_since=args.updated_since))
    elif args.command=='import-reports':
        from .reports import import_reports
        result=import_reports(settings,args.path,args.scope)
    elif args.command=='history-audit':
        from .history_serving import audit
        result=audit(settings,refresh=args.refresh)
        result={k:v for k,v in result.items() if k!='results'}
        if result['state']!='passed':
            print(json.dumps(result,indent=2,default=str));sys.exit(1)
    elif args.command=='history-benchmark':
        from .history_serving import benchmark
        result=benchmark(settings,max_rows_per_window=args.max_rows_per_window,keep_database=args.keep_database)
    elif args.command=='history-load':
        from .history_serving import load,GIB
        result=load(settings,scope=args.scope,bbox=args.bbox,max_windows=args.max_windows,
          max_rows_per_window=args.max_rows_per_window,request_ids=args.request_id,max_database_bytes=args.database_budget_gib*GIB)
    if result is not None:print(json.dumps(result,indent=2,default=str,allow_nan=False))


if __name__=='__main__':
    main()
