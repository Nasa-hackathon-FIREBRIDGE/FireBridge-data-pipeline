"""Import dated report metadata/claims; no automatic truth or fire-label inference."""
from datetime import timedelta
import json
from pathlib import Path
from urllib.parse import urlparse
from psycopg.types.json import Jsonb
from .db import connect
from .publish import run,publish
from .store import Store,asset
from .util import uid,digest,utc,now


def import_reports(settings,path,scope,*,origin=None,task=None):
    path=Path(path);records=json.loads(path.read_text())
    if not isinstance(records,list) or not 1<=len(records)<=1000:raise ValueError('Provide 1–1000 report records')
    obj=Store(settings.data_dir).file(path)
    with connect(settings) as conn:
        if task is not None:
            from .ingest import assert_lease
            assert_lease(conn,task)
        rid=run(conn,'reports',digest([scope,obj.sha256]),{'scope_key':scope},obj.uri)
        aid=asset(conn,obj,'reviewed-reports',path.name,origin or str(path),{'scope_key':scope,'collection_method':'rss_metadata' if origin else 'local_import'})
        pids=[]
        for report in records:
            url=report['canonical_url']
            if urlparse(url).scheme!='https' or not urlparse(url).hostname:raise ValueError('Original HTTPS report URL required')
            if not report.get('title') or not report.get('publisher'):raise ValueError('Report title and publisher required')
            status=report.get('review_status','unreviewed')
            if status=='reviewed' and not report.get('reviewed_by'):raise ValueError('Reviewed reports require a named reviewer')
            content=digest(report);nid=uid([url,content]);published=utc(report['published_at']) if report.get('published_at') else None
            conn.execute("""INSERT INTO news_reports(id,asset_id,canonical_url,title,publisher,language,published_at,
              publication_precision,retrieved_at,content_sha256,summary,original_reporting_url,syndication_group,source_lineage,
              extraction_version,review_status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,now(),%s,%s,%s,%s,%s,'manual-v1',%s) ON CONFLICT DO NOTHING""",
              (nid,aid,url,report['title'],report['publisher'],report.get('language','und'),published,
               report.get('publication_precision','unknown'),content,report.get('summary'),report.get('original_reporting_url'),
               report.get('syndication_group'),report.get('source_lineage','unknown'),status))
            for index,event in enumerate(report.get('events',[])):
                es=event.get('event_start');ee=event.get('event_end_exclusive')
                if (es is None)!=(ee is None) or (es and utc(ee)<=utc(es)):raise ValueError('Event interval must have both valid bounds or neither')
                location=event.get('location')
                conn.execute("""INSERT INTO reported_events(id,report_id,claim_index,event_start,event_end_exclusive,date_precision,
                  place_text,location,location_precision,location_uncertainty_m,reported_event_type,claim_summary,
                  review_status,reviewed_by,reviewed_at) VALUES (%s,%s,%s,%s,%s,%s,%s,
                  CASE WHEN %s::jsonb IS NULL THEN NULL ELSE ST_SetSRID(ST_GeomFromGeoJSON(%s),4326) END,%s,%s,%s,%s,%s,%s,%s)
                  ON CONFLICT DO NOTHING""",
                  (uid([nid,index]),nid,index,es,ee,event.get('date_precision','unknown'),event.get('place_text'),
                   Jsonb(location) if location else None,Jsonb(location) if location else None,event.get('location_precision','unknown'),
                   event.get('location_uncertainty_m'),event.get('reported_event_type'),event['claim_summary'],status,
                   report.get('reviewed_by'),now() if status=='reviewed' else None))
            base=utc((published or now()).date())
            support={'scope_key':scope,'start':base.isoformat(),'end_exclusive':(base+timedelta(days=1)).isoformat(),
                     'canonical_url':url,'association_status':'not_evaluated','date_basis':'publication_or_import_day'}
            part=Store(settings.data_dir).json({'support':support,'report_id':str(nid),'content_sha256':content})
            series=f'reports:{scope}';key=digest(url);pid=uid([series,key,part.sha256]);pids.append(pid)
            conn.execute("""INSERT INTO data_partitions(id,pipeline_run_id,kind,series_key,partition_key,support_spec,storage_uri,
              sha256,input_manifest_uri,schema_version,row_count,serving_complete,validation_status)
              VALUES (%s,%s,'reports',%s,%s,%s,%s,%s,%s,'reports-v1',1,true,'validated') ON CONFLICT DO NOTHING""",
              (pid,rid,series,key,Jsonb(support),part.uri,part.sha256,obj.uri))
            conn.execute('INSERT INTO partition_reports VALUES (%s,%s) ON CONFLICT DO NOTHING',(pid,nid))
            conn.execute('INSERT INTO partition_assets VALUES (%s,%s) ON CONFLICT DO NOTHING',(pid,aid))
        releases=publish(conn,settings,pids,scope,'reports','report_revision')
        conn.execute("UPDATE pipeline_runs SET status='succeeded',finished_at=now(),output_manifest_uri=%s WHERE id=%s",(obj.uri,rid))
    return {'reports':len(records),'releases':releases,'automatic_satellite_confirmation':False}
