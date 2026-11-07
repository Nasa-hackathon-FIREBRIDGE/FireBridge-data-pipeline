"""CMR revision-aware discovery. Inventory is not usable-mask evidence."""
import json
from psycopg.types.json import Jsonb
from .db import connect
from .http import get,FetchError
from .ingest import assert_lease
from .publish import run
from .store import Store,asset
from .util import uid,digest,utc


def discover(settings,request,task=None,client=None):
    collection=request['collection_concept_id']
    if not collection.startswith('C'):raise ValueError('Pin an exact CMR collection concept ID')
    start,end=utc(request['start']),utc(request['end_exclusive'])
    if end<=start:raise ValueError('Invalid CMR interval')
    url='https://cmr.earthdata.nasa.gov/search/granules.json'
    params={'collection_concept_id':collection,'temporal':f'{start.isoformat()},{end.isoformat()}',
            'bounding_box':','.join(map(str,request['bbox'])),'page_size':200,'sort_key[]':['start_date','concept_id']}
    if request.get('updated_since'):params['updated_since']=request['updated_since']
    token=None;seen=set();objects=[];granules=[];complete=False
    for page in range(10):
        headers={'CMR-Search-After':token} if token else {}
        body,response_headers=get(settings,url,params=params,headers=headers,client=client)
        obj=Store(settings.data_dir).put([body],'.json');objects.append(obj)
        try:entries=json.loads(body)['feed']['entry']
        except (ValueError,KeyError,TypeError):raise FetchError('invalid_cmr_payload',blocked=True) from None
        for entry in entries:
            granules.append((entry,obj))
        if not entries:complete=True;break
        next_token=response_headers.get('cmr-search-after')
        if not next_token:
            if len(entries)<200:complete=True;break
            raise FetchError('cmr_missing_pagination',blocked=True)
        if next_token in seen:raise FetchError('cmr_repeated_cursor',blocked=True)
        seen.add(next_token);token=next_token
    manifest=Store(settings.data_dir).json({'request':request,'pages':[o.uri for o in objects],
             'enumeration_complete':complete,'granules_returned':len(granules),'snapshot_isolation':False})
    with connect(settings) as conn:
        assert_lease(conn,task)
        rid=run(conn,'cmr',digest([request,manifest.sha256]),request,manifest.uri)
        aids={o.sha256:asset(conn,o,'cmr-catalog',collection+':'+o.sha256,url,{'request':request}) for o in objects}
        for entry,obj in granules:
            concept=entry['id'];revision=digest(entry)
            conn.execute("""INSERT INTO science_granules VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
              (uid([concept,revision]),collection,concept,revision,aids[obj.sha256],entry.get('time_start'),entry.get('time_end'),entry.get('updated'),Jsonb(entry)))
        conn.execute("UPDATE pipeline_runs SET status=%s,finished_at=now(),output_manifest_uri=%s,error_code=%s WHERE id=%s",
                     ('succeeded' if complete else 'failed',manifest.uri,None if complete else 'cmr_page_cap',rid))
    if not complete:raise FetchError('cmr_page_cap_split_request',blocked=True)
    return {'catalogued':len(granules),'enumeration_complete':True,'masks_ready':False,'manifest':manifest.uri}
