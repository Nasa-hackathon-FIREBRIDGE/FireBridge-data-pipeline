from psycopg.types.json import Jsonb
from .db import connect
from .util import uid, digest

PLATFORMS = {
    "Terra": ("modis-terra", "MODIS", "61", 1000),
    "Aqua": ("modis-aqua", "MODIS", "61", 1000),
    "SNPP": ("viirs-snpp", "VIIRS", "2", 375),
    "N20": ("viirs-noaa20", "VIIRS", "2", 375),
    "N21": ("viirs-noaa21", "VIIRS", "2", 375),
    "L8": ("landsat8", "OLI", "1", 30),
    "L9": ("landsat9", "OLI-2", "1", 30),
}
FEEDS = {
    "MODIS_SP": (["Terra", "Aqua"], "standard"),
    "MODIS_NRT": (["Terra", "Aqua"], "nrt"),
    "VIIRS_SNPP_SP": (["SNPP"], "standard"),
    "VIIRS_SNPP_NRT": (["SNPP"], "nrt"),
    "VIIRS_NOAA20_SP": (["N20"], "standard"),
    "VIIRS_NOAA20_NRT": (["N20"], "nrt"),
    "VIIRS_NOAA21_SP": (["N21"], "standard"),
    "VIIRS_NOAA21_NRT": (["N21"], "nrt"),
    "LANDSAT_NRT": (["L8", "L9"], "nrt"),
}
PILOT_BBOX = [-6.4, 34.5, -4.5, 35.9]


def source_id(platform, stream, collection=None):
    slug, _, default_collection, _ = PLATFORMS[platform]
    return f"{slug}-c{collection or default_collection}-{stream}"


def polygon(bbox):
    w, s, e, n = map(float, bbox)
    if not (-180 <= w < e <= 180 and -90 <= s < n <= 90):
        raise ValueError("bbox must be west,south,east,north without antimeridian crossing")
    return {"type": "MultiPolygon", "coordinates": [[[[w,s],[e,s],[e,n],[w,n],[w,s]]]]}


def area(conn, scope, bbox):
    geom = polygon(bbox)
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ('scope:'+scope,))
    registered=conn.execute("SELECT a.geometry_sha256 FROM ingestion_scopes s JOIN areas a ON a.id=s.area_id WHERE s.scope_key=%s",(scope,)).fetchone()
    if registered and registered['geometry_sha256']!=digest(geom):
        raise ValueError('Scope key already identifies another geometry; use a new scope key')
    area_id = uid(["area", scope, bbox])
    conn.execute("""INSERT INTO areas(id,name,version,geom,geometry_sha256,display_timezone,provenance)
      VALUES (%s,%s,'1',ST_SetSRID(ST_GeomFromGeoJSON(%s),4326),%s,'UTC','Registered ingestion rectangle')
      ON CONFLICT DO NOTHING""", (area_id, scope, Jsonb(geom), digest(geom)))
    existing = conn.execute("SELECT id FROM areas WHERE geometry_sha256=%s AND version='1'", (digest(geom),)).fetchone()
    conn.execute('INSERT INTO ingestion_scopes(scope_key,area_id) VALUES (%s,%s) ON CONFLICT DO NOTHING',(scope,existing['id']))
    return existing["id"]


def seed(settings):
    with connect(settings) as conn:
        for platform, (slug, instrument, collection, resolution) in PLATFORMS.items():
            for stream in (["nrt"] if platform.startswith("L") else ["standard", "nrt"]):
                sid = source_id(platform, stream)
                conn.execute("""INSERT INTO sources(id,name,provider,kind,platform,instrument,product,collection,
                 processing_stream,documentation_url,citation,license_info,native_resolution_m,schema_version,metadata)
                 VALUES (%s,%s,'NASA FIRMS','hotspots',%s,%s,%s,%s,%s,%s,'NASA FIRMS / originating science team',
                 'NASA open data; retain attribution',%s,'native-v1',%s) ON CONFLICT DO NOTHING""",
                 (sid, f"{platform} active-fire detections ({stream})", platform, instrument, slug, collection, stream,
                  "https://firms.modaps.eosdis.nasa.gov/", resolution,
                  Jsonb({"comparison_family": f"{slug}-c{collection}", "mask_coverage_available": False})))
                if platform.startswith('L'):
                    # c1 in these stable internal IDs is a legacy adapter tag, not a claimed NASA collection.
                    conn.execute("UPDATE sources SET collection='not-provided',metadata=metadata || %s WHERE id=%s",
                                 (Jsonb({'collection_status':'not supplied by FIRMS CSV','id_c1_tag':'internal adapter identity, not NASA collection'}),sid))
        # FIRMS historical MODIS version 6.03 is Collection 6, not Collection 6.1.
        for platform in ('Terra','Aqua'):
            for stream in ('standard','nrt'):
                sid=source_id(platform,stream,'6')
                slug,instrument,_,resolution=PLATFORMS[platform]
                conn.execute("""INSERT INTO sources(id,name,provider,kind,platform,instrument,product,collection,
                  processing_stream,documentation_url,citation,license_info,native_resolution_m,schema_version,metadata)
                  VALUES (%s,%s,'NASA FIRMS','hotspots',%s,%s,%s,'6',%s,
                  'https://nasa-gibs.github.io/gibs-api-docs/python-usage/',
                  'NASA FIRMS / originating science team','NASA open data; retain attribution',%s,'native-v1',%s)
                  ON CONFLICT DO NOTHING""",(sid,f'{platform} Collection 6 ({stream})',platform,instrument,slug,stream,
                  resolution,Jsonb({'comparison_family':slug+'-c6','mask_coverage_available':False})))
        for feed, (platforms, stream) in FEEDS.items():
            raw_id = "raw-" + feed.lower()
            conn.execute("""INSERT INTO sources(id,name,provider,kind,product,collection,processing_stream,
              documentation_url,citation,license_info,schema_version) VALUES (%s,%s,'NASA FIRMS','hotspots',%s,
              'provider-native',%s,'https://firms.modaps.eosdis.nasa.gov/api/area/','NASA FIRMS','NASA open data','1')
              ON CONFLICT DO NOTHING""", (raw_id, feed + " original payload", feed, stream))
            conn.execute("""INSERT INTO ingestion_feeds(id,provider,adapter,adapter_version,endpoint_template,
              credential_ref,rate_limit_group,capability_spec,state) VALUES (%s,'NASA FIRMS','firms','1',
              'https://firms.modaps.eosdis.nasa.gov/api/area/csv/{MAP_KEY}/{SOURCE}/{BBOX}/{DAYS}/{DATE}',
              'env:FIRMS_MAP_KEY','firms',%s,'unverified') ON CONFLICT DO NOTHING""",
              (feed, Jsonb({"max_days":5,"region":"US and Canada only" if feed=="LANDSAT_NRT" else "global",
                            "raw_source_id":raw_id,"stream":stream,"platforms":platforms})))
            for platform in platforms:
                conn.execute("INSERT INTO feed_sources VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                             (feed, source_id(platform, stream), Jsonb({"satellite": platform})))
        for sid, kind, product, stream, url in [
            ("openmeteo-era5", "weather", "ERA5", "reanalysis", "https://open-meteo.com/en/docs/historical-weather-api"),
            ("openmeteo-ifs", "weather", "ECMWF IFS", "model_current", "https://open-meteo.com/en/docs"),
            ("reviewed-reports", "news", "reviewed-import", "reviewed", "https://www.earthdata.nasa.gov/"),
            ("cmr-catalog", "fire_mask", "CMR inventory", "catalog", "https://cmr.earthdata.nasa.gov/search/site/docs/search/api.html"),
        ]:
            conn.execute("""INSERT INTO sources(id,name,provider,kind,product,collection,processing_stream,documentation_url,
             citation,license_info,schema_version) VALUES (%s,%s,%s,%s,%s,'1',%s,%s,%s,%s,'1') ON CONFLICT DO NOTHING""",
             (sid,product, "Open-Meteo / ECMWF" if kind=="weather" else "Original publisher / NASA",kind,product,stream,url,
              "Open-Meteo and ECMWF" if kind=="weather" else "Original source retained",
              "CC BY 4.0; check provider usage plan" if kind=="weather" else "Per original document"))
        for fid, adapter in [("WEATHER_ERA5","weather"),("WEATHER_RECENT","weather"),("CMR","cmr"),("NEWS_RSS","news")]:
            conn.execute("""INSERT INTO ingestion_feeds(id,provider,adapter,adapter_version,endpoint_template,
              rate_limit_group,capability_spec,state) VALUES (%s,%s,%s,'1',%s,%s,'{}','active') ON CONFLICT DO NOTHING""",
              (fid,"NASA" if adapter=="cmr" else "Open-Meteo",adapter,"verified adapter URL",adapter))
        conn.execute("""INSERT INTO metric_definitions VALUES ('native_detections','1','detections','native_detections',
         'Number of published active-fire point records; not incidents or burned area','{}',false,false) ON CONFLICT DO NOTHING""")
        area(conn, "morocco-pilot", PILOT_BBOX)
        area(conn, "global", [-180,-90,180,90])
