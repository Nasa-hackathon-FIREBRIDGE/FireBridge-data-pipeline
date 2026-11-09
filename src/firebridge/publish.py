"""One transaction publishes complete revisions and advances release pointers."""
from datetime import timedelta
from uuid import uuid4
from psycopg.types.json import Jsonb
from .store import Store
from .util import canonical, digest, uid, utc, now
from . import __version__


def run(conn, stage, key, config, input_uri):
    rid = uid([stage,key])
    conn.execute("""INSERT INTO pipeline_runs(id,stage,idempotency_key,status,code_version,config,input_manifest_uri,started_at)
      VALUES (%s,%s,%s,'running',%s,%s,%s,now()) ON CONFLICT(idempotency_key)
      DO UPDATE SET status='running',started_at=now(),error_code=NULL,finished_at=NULL""",
      (rid,stage,key,__version__,Jsonb(config),input_uri))
    return rid


def detection_partition(conn, settings, run_id, asset_id, source, day, scope, bbox, rows, *, fetched_at=None):
    day = utc(day)
    end = day + timedelta(days=1)
    w,s,e,n = bbox
    unique = {}
    for row in rows:
        if row['source_id'] != source or not day <= row['acquired_at'] < end:
            raise ValueError("Row outside partition source/time support")
        if not (w <= row['longitude'] <= e and s <= row['latitude'] <= n):
            raise ValueError("Row outside declared spatial support")
        unique[row['record_sha256']] = row
    ordered = [unique[k] for k in sorted(unique)]
    stream = source.rsplit('-',1)[-1]
    support = {"scope_key":scope,"bbox":bbox,"source_id":source,"start":day.isoformat(),"end_exclusive":end.isoformat(),
               "processing_stream":stream,"query_complete":True,"observation_coverage":"unknown",
               "period_state":"closed" if end <= (fetched_at or now()) else "open"}
    # Acquisition rows are authoritative for this exact day and rectangular scope.
    obj = Store(settings.data_dir).json({"schema":"detections-v1","support":support,
                                       "records":[{k:v for k,v in r.items() if k!='native_record_key'} for r in ordered]})
    return _load_detection_partition(conn,run_id,asset_id,source,day,scope,support,obj,len(ordered),ordered)


def stream_detection_partition(conn,settings,run_id,asset_id,source,day,scope,bbox,rows,count,*,fetched_at,provider_footprint=None,end_exclusive=None,area_id=None,inventory_complete=False):
    """Replay a disk-sorted, unique row factory without materializing a whole day.

    Its canonical object is byte-identical to detection_partition for identical
    observations/support. The caller validates the whole input before this step.
    """
    day=utc(day);end=utc(end_exclusive) if end_exclusive else day+timedelta(days=1)
    if end<=day:raise ValueError('Invalid partition interval')
    support={"scope_key":scope,"bbox":bbox,"source_id":source,"start":day.isoformat(),
      "end_exclusive":end.isoformat(),"processing_stream":source.rsplit('-',1)[-1],
      "query_complete":True,"observation_coverage":"unknown",
      "period_state":"closed" if end<=fetched_at else "open"}
    if provider_footprint:support['provider_footprint']=provider_footprint
    if area_id:
        support.update(area_id=str(area_id),inventory_complete=inventory_complete,source_ids=[source])
    def chunks():
        yield b'{"records":['
        previous=None;seen=0
        for r in rows():
            sha=r['record_sha256']
            if previous is not None and sha<=previous:raise ValueError('Unsorted or duplicate spool')
            if r['source_id']!=source or not day<=r['acquired_at']<end:
                raise ValueError('Spool outside partition support')
            w,s,e,n=bbox
            if not w<=r['longitude']<=e or not s<=r['latitude']<=n:raise ValueError('Spool outside bbox')
            yield ((',' if seen else '')+canonical({k:v for k,v in r.items() if k!='native_record_key'})).encode()
            previous=sha;seen+=1
        if seen!=count:raise ValueError('Spool count changed')
        yield ('],"schema":"detections-v1","support":'+canonical(support)+'}').encode()
    obj=Store(settings.data_dir).put(chunks(),'.json')
    return _load_detection_partition(conn,run_id,asset_id,source,day,scope,support,obj,count,rows())


def _load_detection_partition(conn,run_id,asset_id,source,day,scope,support,obj,count,ordered):
    stream=source.rsplit('-',1)[-1]
    series = f"detections:{source}:{scope}"
    key = day.date().isoformat()
    partition_id = uid([series,key,obj.sha256])
    if conn.execute("SELECT 1 FROM data_partitions WHERE id=%s", (partition_id,)).fetchone():
        return partition_id
    conn.execute("""INSERT INTO data_partitions(id,pipeline_run_id,kind,series_key,partition_key,support_spec,storage_uri,
      sha256,input_manifest_uri,schema_version,row_count,serving_complete,validation_status)
      VALUES (%s,%s,'detections',%s,%s,%s,%s,%s,%s,'native-v1',%s,true,'validated')""",
      (partition_id,run_id,series,key,Jsonb(support),obj.uri,obj.sha256,str(asset_id),count))
    conn.execute("INSERT INTO partition_assets VALUES (%s,%s)", (partition_id,asset_id))
    conn.execute("""CREATE TEMP TABLE IF NOT EXISTS stage_detections (
      source_id text, record_sha256 text, acquired_at timestamptz, lon float8, lat float8,
      confidence_raw text, confidence_scheme text,type_raw text,day_night text,frp_mw float8,
      brightness_bands jsonb,scan_km float8,track_km float8,cross_track_sample integer,native_fields jsonb)
      ON COMMIT DROP""")
    conn.execute("TRUNCATE stage_detections")
    with conn.cursor().copy("COPY stage_detections FROM STDIN") as copy:
        for r in ordered:
            copy.write_row((r['source_id'],r['record_sha256'],r['acquired_at'],r['longitude'],r['latitude'],
              r['confidence_raw'],r['confidence_scheme'],r['type_raw'],r['day_night'],r['frp_mw'],
              Jsonb(r['brightness_bands']),r['scan_km'],r['track_km'],r['cross_track_sample'],Jsonb(r['native_fields'])))
    conn.execute("""INSERT INTO detections(asset_id,source_id,native_record_key,record_sha256,identity_method,processing_level,
      acquired_at,geom,confidence_raw,confidence_scheme,type_raw,day_night,frp_mw,brightness_bands,scan_km,track_km,cross_track_sample,native_fields)
      SELECT %s,source_id,record_sha256,record_sha256,'canonical-native-v1',%s,acquired_at,
      ST_SetSRID(ST_MakePoint(lon,lat),4326),confidence_raw,confidence_scheme,type_raw,day_night,frp_mw,
      brightness_bands,scan_km,track_km,cross_track_sample,native_fields FROM stage_detections
      ON CONFLICT(source_id,record_sha256) DO NOTHING""", (asset_id,stream))
    conn.execute("""INSERT INTO partition_detections SELECT %s,d.id FROM stage_detections s
      JOIN detections d USING(source_id,record_sha256)""", (partition_id,))
    return partition_id


def publish(conn, settings, partition_ids, scope, kind="satellite", reason="new_data", observed_at=None):
    if not partition_ids: raise ValueError("Cannot publish without complete partitions")
    # Serializes across aliases, including the first publication. No lost parallel update.
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (f"publish:{kind}:{scope}",))
    observed_at = observed_at or now()
    partitions = conn.execute("SELECT * FROM data_partitions WHERE id=ANY(%s)", (partition_ids,)).fetchall()
    if len(partitions) != len(set(partition_ids)): raise ValueError("Missing partition")
    for p in partitions:
        if not p['serving_complete'] or p['validation_status'] != 'validated' or p['support_spec']['scope_key']!=scope:
            raise ValueError("Partition publication gate failed")
        table, column = {"detections":("partition_detections","detection_id"),
                         "weather":("partition_weather_values","weather_value_id"),
                         "reports":("partition_reports","report_id")}[p['kind']]
        count = conn.execute(f"SELECT count(*) AS n FROM {table} WHERE partition_id=%s", (p['id'],)).fetchone()['n']
        if count!=p['row_count']: raise ValueError("Serving membership count mismatch")
        conn.execute("""INSERT INTO partition_heads(scope_key,series_key,partition_key,partition_id,accepted_at)
          VALUES (%s,%s,%s,%s,%s) ON CONFLICT(scope_key,series_key,partition_key)
          DO UPDATE SET partition_id=EXCLUDED.partition_id,accepted_at=EXCLUDED.accepted_at
          WHERE partition_heads.accepted_at<=EXCLUDED.accepted_at""",
          (scope,p['series_key'],p['partition_key'],p['id'],observed_at))
    heads = conn.execute("""SELECT p.* FROM partition_heads h JOIN data_partitions p ON p.id=h.partition_id
      WHERE h.scope_key=%s AND p.kind=%s ORDER BY p.series_key,p.partition_key""",
      (scope,{"satellite":"detections","weather":"weather","reports":"reports"}[kind])).fetchall()
    if kind == "satellite":
        standard = [p for p in heads if p['support_spec']['processing_stream']=='standard']
        nrt = [p for p in heads if p['support_spec']['processing_stream']=='nrt']
        best = {}
        for p in nrt + standard:
            identity = (p['support_spec']['source_id'].rsplit('-',1)[0],p['partition_key'])
            best[identity] = p
        selections = {"standard_only":standard,"nrt_only":nrt,"best_available":list(best.values())}
    else:
        selections = {"weather_historical":[p for p in heads if p['support_spec']['data_kind']=='reanalysis'],
                      "weather_recent":[p for p in heads if p['support_spec']['data_kind']!='reanalysis']} if kind=='weather' else {"reports":heads}
    output = {}
    for alias, selected in selections.items():
        if not selected: continue
        selected = sorted(selected,key=lambda p:(p['series_key'],p['partition_key']))
        membership = [(p['series_key'],p['partition_key'],str(p['id'])) for p in selected]
        signature = digest([kind,scope,alias,membership])
        current = conn.execute("SELECT * FROM release_aliases WHERE alias=%s AND scope_key=%s", (alias,scope)).fetchone()
        old_members = []
        if current:
            old_members = conn.execute("SELECT series_key,partition_key,partition_id FROM release_partitions WHERE release_id=%s ORDER BY series_key,partition_key",(current['release_id'],)).fetchall()
            if [(p['series_key'],p['partition_key'],str(p['partition_id'])) for p in old_members]==membership:
                output[alias] = str(current['release_id']); continue
        release_id = uuid4()  # A return to old content is still a new chronological release.
        manifest = Store(settings.data_dir).json({"id":str(release_id),"alias":alias,"scope":scope,"membership":membership,"signature":signature})
        stream = "retrospective" if alias in ('standard_only','weather_historical','reports') or (kind=='satellite' and all(p['support_spec']['processing_stream']=='standard' for p in selected)) else "provisional"
        cutoff = min(now(),max(utc(p['support_spec']['end_exclusive']) for p in selected))
        conn.execute("""INSERT INTO data_releases(id,name,status,stream,code_version,config,config_sha256,manifest_uri,
          parent_release_id,dataset_kind,scope_key,observation_cutoff,published_at,validation_report_uri)
          VALUES (%s,%s,'published',%s,%s,%s,%s,%s,%s,%s,%s,%s,now(),%s)""",
          (release_id,f"{scope}:{alias}:{release_id}",stream,__version__,Jsonb({"alias":alias,"signature":signature,
           "observation_coverage":"unknown" if kind=='satellite' else "not_applicable"}),signature,manifest.uri,
           current['release_id'] if current else None,kind,scope,cutoff,manifest.uri))
        with conn.cursor().copy("COPY release_partitions(release_id,series_key,partition_key,partition_id) FROM STDIN") as copy:
            for p in selected: copy.write_row((release_id,p['series_key'],p['partition_key'],p['id']))
        conn.execute("""INSERT INTO release_assets SELECT DISTINCT %s,pa.asset_id,'partition_input' FROM partition_assets pa
          JOIN release_partitions rp ON rp.partition_id=pa.partition_id WHERE rp.release_id=%s""", (release_id,release_id))
        if current:
            old_map={(p['series_key'],p['partition_key']):p['partition_id'] for p in old_members}
            for p in selected:
                if old_map.get((p['series_key'],p['partition_key']))==p['id']:continue
                change_reason = reason
                if kind=='satellite' and p['support_spec']['processing_stream']=='standard' and alias=='best_available':
                    nrt_series=p['series_key'].replace('-standard:', '-nrt:')
                    if (nrt_series,p['partition_key']) in old_map:change_reason='standard_replacement'
                conn.execute("""INSERT INTO release_changes(id,from_release_id,to_release_id,series_key,affected_start,
                  affected_end_exclusive,reason,diff_manifest_uri) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                  (uuid4(),current['release_id'],release_id,p['series_key'],utc(p['support_spec']['start']),
                   utc(p['support_spec']['end_exclusive']),change_reason,manifest.uri))
        conn.execute("""INSERT INTO release_aliases VALUES (%s,%s,%s,1,now()) ON CONFLICT(alias,scope_key)
          DO UPDATE SET release_id=EXCLUDED.release_id,generation=release_aliases.generation+1,updated_at=now()""",(alias,scope,release_id))
        payload={"release_id":str(release_id),"scope_key":scope,"alias":alias,"dataset_kind":kind}
        conn.execute("""INSERT INTO outbox_events(id,event_type,aggregate_id,dedupe_key,payload,status,available_at)
          VALUES (%s,'release.published',%s,%s,%s,'pending',now())""",(uuid4(),str(release_id),str(release_id),Jsonb(payload)))
        conn.execute("SELECT pg_notify('firebridge_release',%s)",(canonical(payload),))
        output[alias]=str(release_id)
    return output
