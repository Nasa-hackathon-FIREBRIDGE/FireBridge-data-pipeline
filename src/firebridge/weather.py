from datetime import timedelta
import json
import math
from psycopg.types.json import Jsonb
from .db import connect
from .http import get, FetchError
from .ingest import assert_lease
from .publish import run, publish
from .store import Store, asset
from .util import utc, now, digest, uid, days

VARIABLES = {
 'temperature_2m': ('°C','instant',-100,70),
 'relative_humidity_2m': ('%','instant',0,100),
 'precipitation': ('mm','interval_sum',0,2000),
 'wind_speed_10m': ('m/s','instant',0,200),
 'wind_direction_10m': ('°','instant',0,360),
}


def parse(payload, start, end):
    hourly=payload.get('hourly',{}); units=payload.get('hourly_units',{})
    times=hourly.get('time',[])
    expected=int((end-start).total_seconds()/3600)
    if len(times)!=expected or len(set(times))!=expected: raise ValueError('Incomplete hourly weather response')
    if times!=[int((start+timedelta(hours=i)).timestamp()) for i in range(expected)]:
        raise ValueError('Weather timestamps do not match requested UTC hours')
    records=[]
    for variable,(unit,stat,lo,hi) in VARIABLES.items():
        if units.get(variable)!=unit or len(hourly.get(variable,[]))!=expected: raise ValueError('Weather units/length changed')
        for stamp,value in zip(times,hourly[variable]):
            quality='missing' if value is None else 'valid'
            if value is not None and (not isinstance(value,(int,float)) or not math.isfinite(value) or not lo<=value<=hi):
                raise ValueError('Invalid weather value')
            t=utc(__import__('datetime').datetime.fromtimestamp(stamp,__import__('datetime').timezone.utc))
            # Open-Meteo precipitation is the sum over the preceding hour, ending at t.
            records.append(dict(variable=variable,unit=unit,valid_start=t-timedelta(hours=1) if stat=='interval_sum' else t,
                                valid_end=t,statistic=stat,value=value,quality_status=quality,sample_time=t))
    return records


def fetch_weather(settings, request, task=None, client=None):
    start,end=utc(request['start']),utc(request['end_exclusive'])
    window=list(days(start,end))
    if len(window)>31: raise ValueError('Weather requests are limited to 31 days')
    kind=request.get('data_kind','reanalysis')
    if kind not in ('reanalysis','model_current'): raise ValueError('Unsupported weather data kind')
    lat,lon=float(request['latitude']),float(request['longitude'])
    if not -90<=lat<=90 or not -180<=lon<=180:raise ValueError('Invalid weather location')
    scope=request['scope_key']
    source='openmeteo-era5' if kind=='reanalysis' else 'openmeteo-ifs'
    model='era5' if kind=='reanalysis' else 'ecmwf_ifs025'
    url='https://archive-api.open-meteo.com/v1/archive' if kind=='reanalysis' else 'https://api.open-meteo.com/v1/forecast'
    params=dict(latitude=lat,longitude=lon,start_date=str(start.date()),end_date=str((end-timedelta(days=1)).date()),
                hourly=','.join(VARIABLES),models=model,timezone='GMT',timeformat='unixtime',wind_speed_unit='ms')
    request_started=now()
    body,_=get(settings,url,params=params,client=client)
    obj=Store(settings.data_dir).put([body],'.json')
    try:
        payload=json.loads(body); records=parse(payload,start,end)
        returned_lat=float(payload['latitude']); returned_lon=float(payload['longitude'])
        if not -90<=returned_lat<=90 or not -180<=returned_lon<=180:raise ValueError('Invalid returned coordinate')
    except (ValueError,KeyError,TypeError): raise FetchError('invalid_weather_payload',blocked=True) from None
    retrieved=now()
    loc_key=digest([model,returned_lat,returned_lon,payload.get('elevation')])
    location=uid([source,loc_key])
    with connect(settings) as conn:
        assert_lease(conn,task)
        rid=run(conn,'weather',digest([request,obj.sha256]),request,obj.uri)
        aid=asset(conn,obj,source,digest(params),url,{'request':params,'data_kind':kind},start,end)
        conn.execute("""INSERT INTO weather_locations(id,source_id,native_location_key,support_kind,geom,elevation_m,metadata)
          VALUES (%s,%s,%s,'sample_point',ST_SetSRID(ST_MakePoint(%s,%s),4326),%s,%s) ON CONFLICT DO NOTHING""",
          (location,source,loc_key,returned_lon,returned_lat,payload.get('elevation'),Jsonb({'model':model,
           'requested_latitude':lat,'requested_longitude':lon,'spatial_method':'point-sampled context; not AOI average'})))
        for r in records:
            conn.execute("""INSERT INTO weather_values(location_id,source_id,asset_id,variable,unit,valid_start,valid_end,
              issued_at,available_at,data_kind,statistic,value,quality_status,derivation)
              VALUES (%s,%s,%s,%s,%s,%s,%s,NULL,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
              (location,source,aid,r['variable'],r['unit'],r['valid_start'],r['valid_end'],retrieved,kind,
               r['statistic'],r['value'],r['quality_status'],Jsonb({'model':model,'sample_time':r['sample_time'].isoformat(),
                'available_at_semantics':'first retrieved by FIREBRIDGE','issued_at_status':'not provided; never inferred',
                'interval_convention':'preceding hour ending at sample_time' if r['statistic']=='interval_sum' else 'instant at sample_time'})))
        pids=[]
        for day in window:
            day_end=day+timedelta(days=1)
            selected=[r for r in records if day<=r['sample_time']<day_end]
            support={'scope_key':scope,'source_id':source,'data_kind':kind,'start':day.isoformat(),
             'end_exclusive':day_end.isoformat(),'time_partition_basis':'sample_time','latitude':returned_lat,'longitude':returned_lon,
             'location_key':loc_key,'spatial_method':'sample_point','issued_at':None}
            part=Store(settings.data_dir).json({'support':support,'asset':str(aid),'records':selected})
            # Keep a stable requested point even if a provider revises its returned grid location.
            point_key=digest([lat,lon])
            series=f"weather:{source}:{scope}:{point_key}"
            pid=uid([series,str(day.date()),part.sha256]); pids.append(pid)
            conn.execute("""INSERT INTO data_partitions(id,pipeline_run_id,kind,series_key,partition_key,support_spec,storage_uri,
             sha256,input_manifest_uri,schema_version,row_count,serving_complete,validation_status)
             VALUES (%s,%s,'weather',%s,%s,%s,%s,%s,%s,'weather-v1',%s,true,'validated') ON CONFLICT DO NOTHING""",
             (pid,rid,series,str(day.date()),Jsonb(support),part.uri,part.sha256,str(aid),len(selected)))
            conn.execute("INSERT INTO partition_assets VALUES (%s,%s) ON CONFLICT DO NOTHING",(pid,aid))
            conn.execute("""INSERT INTO partition_weather_values SELECT %s,id FROM weather_values
              WHERE asset_id=%s AND location_id=%s AND (derivation->>'sample_time')::timestamptz >=%s
              AND (derivation->>'sample_time')::timestamptz <%s ON CONFLICT DO NOTHING""",(pid,aid,location,day,day_end))
        releases=publish(conn,settings,pids,scope,'weather','weather_revision',observed_at=request_started)
        conn.execute("UPDATE pipeline_runs SET status='succeeded',finished_at=now(),output_manifest_uri=%s WHERE id=%s",(obj.uri,rid))
    return {'rows':len(records),'missing':sum(r['value'] is None for r in records),'releases':releases,'data_kind':kind,'spatial_method':'sample_point'}
