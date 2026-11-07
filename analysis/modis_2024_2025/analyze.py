"""Exact global MODIS EDA, 2024-01-17 through 2025-01-17 inclusive (UTC).

Read official MCD14ML standard monthly files. Preserve raw files, provenance and
native classes. FIRMS user CSV is an independent January overlap audit, not a
second input. Counts are detections; point-only zeros are never clear-sky labels.
"""
from pathlib import Path
import json, hashlib, zipfile, calendar
import numpy as np
import pandas as pd
from pyproj import Transformer

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / 'data/external/modis_2024_2025'
OUT = ROOT / 'reports/modis_2024_2025'
TABLES = OUT / 'tables'
PROC = ROOT / 'data/processed/modis_2024_2025'
START, END = '2024-01-17', '2025-01-17'
DATES = pd.date_range(START, END, freq='D')
NATIVE = ['acq_date','acq_time','satellite','latitude','longitude','brightness',
          'bright_t31','sample','frp','confidence','type','daynight']
NUMERIC = ['latitude','longitude','brightness','bright_t31','sample','frp','confidence','type']
REGIONS = {'pilot':[-6.4,34.5,-4.5,35.9],
           'morocco_context_rectangle':[-13.5,27,-0.9,36.1],
           'southern_spain_rectangle':[-7.5,36,-1,38.5]}

def table(df, name):
    df.to_csv(TABLES / f'{name}.csv', index=False)
    return df

def dump(path, obj):
    path.write_text(json.dumps(obj, indent=2, default=lambda x:
        x.item() if isinstance(x,np.generic) else str(x)), encoding='utf-8')

def sha256(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''): h.update(b)
    return h.hexdigest()

def load():
    parts=[]; inventory=[]
    expected=[f'MCD14ML.{d:%Y%m}.061.03.txt.gz' for d in pd.date_range('2024-01-01','2025-01-01',freq='MS')]
    missing=[f for f in expected if not (RAW/f).exists()]
    if missing: raise FileNotFoundError(f'Monthly files missing: {missing}')
    for name in expected:
        path=RAW/name
        a=pd.read_csv(path,sep=r'\s+',dtype={'YYYYMMDD':str,'HHMM':str})
        assert list(a)==['YYYYMMDD','HHMM','sat','lat','lon','T21','T31','sample','FRP','conf','type','dn']
        a['source_row']=np.arange(2,len(a)+2)
        dates=pd.to_datetime(a.YYYYMMDD,format='%Y%m%d',errors='raise')
        assert (dates.dt.strftime('%Y%m')==name.split('.')[1]).all()
        inside=dates.between(START,END)
        inventory.append({'filename':name,'bytes':path.stat().st_size,'sha256':sha256(path),
            'raw_rows':len(a),'target_rows':int(inside.sum()),'excluded_date_rows':int((~inside).sum()),
            'raw_start':dates.min().strftime('%Y-%m-%d'),'raw_end':dates.max().strftime('%Y-%m-%d')})
        a=a.loc[inside].copy()
        a=a.rename(columns={'sat':'satellite','lat':'latitude','lon':'longitude',
            'T21':'brightness','T31':'bright_t31','FRP':'frp','conf':'confidence','dn':'daynight'})
        a['acq_date']=pd.to_datetime(a.pop('YYYYMMDD'),format='%Y%m%d').dt.strftime('%Y-%m-%d')
        a['acq_time']=a.pop('HHMM').str.zfill(4)
        a['source_file']=name
        a['satellite']=a.satellite.map({'A':'Aqua','T':'Terra'})
        parts.append(a)
        print('READ',name,len(a),flush=True)
    table(pd.DataFrame(inventory),'input_inventory')
    return pd.concat(parts,ignore_index=True)

def summarize_group(g):
    valid=g.frp.where(g.frp.ge(0))
    solar=g.solar_hour
    return {'rows':len(g),'retained_conf30_rows':int(g.retained.sum()),
        'type0_conf30_rows':int(g.vegetation_retained.sum()),
        'high_conf80_rows':int(g.confidence.ge(80).sum()),
        'days_with_exported_detections':g.acq_date.nunique(),
        'day_rows':int(g.daynight.eq('D').sum()),'night_rows':int(g.daynight.eq('N').sum()),
        'median_frp_MW':valid.median(),'mean_frp_MW':valid.mean(),'p95_frp_MW':valid.quantile(.95),
        'p99_frp_MW':valid.quantile(.99),'max_frp_MW':valid.max(),
        'negative_frp_rows':int(g.frp.lt(0).sum()),'zero_frp_rows':int(g.frp.eq(0).sum()),
        'median_brightness_K':g.brightness.median(),'median_bright_t31_K':g.bright_t31.median(),
        'day_median_solar_hour':solar[g.daynight.eq('D')].median(),
        'night_median_solar_hour':solar[g.daynight.eq('N')].median()}

def grouped_summary(d, groups):
    results=[]
    for key,g in d.groupby(groups,observed=True):
        key=(key,) if not isinstance(key,tuple) else key
        results.append(dict(zip(groups,key))|summarize_group(g))
    return pd.DataFrame(results)

def january_audit(d):
    archive=Path('/home/da-rog/Downloads/nasa hackathon data/DL_FIRE_M-C61_42014.zip')
    common=[c for c in NATIVE if c!='sample']
    pieces=[]; scanned=0
    with zipfile.ZipFile(archive) as z:
        members=[m for m in z.namelist() if m.endswith('.csv')]
        assert len(members)==1
        with z.open(members[0]) as f:
            for chunk in pd.read_csv(f,dtype={'acq_time':str,'acq_date':str},chunksize=300_000):
                scanned+=len(chunk)
                a=chunk[chunk.acq_date.between('2025-01-01',END)].copy()
                if len(a):pieces.append(a)
    f=pd.concat(pieces,ignore_index=True)
    f.acq_time=f.acq_time.str.zfill(4)
    u=d[d.acq_date.ge('2025-01-01')][common].copy()
    # Multiset equality across every shared native field; no row order reliance.
    ua=u.groupby(common,dropna=False,observed=True).size().rename('umd_rows').reset_index()
    fa=f.groupby(common,dropna=False,observed=True).size().rename('firms_rows').reset_index()
    merged=ua.merge(fa,on=common,how='outer').fillna({'umd_rows':0,'firms_rows':0})
    matched=np.minimum(merged.umd_rows,merged.firms_rows).sum()
    mismatches=merged[merged.umd_rows.ne(merged.firms_rows)].copy()
    table(mismatches,'january_overlap_differences')
    table(f[['satellite','scan','track']].groupby('satellite').agg(
        rows=('scan','size'),scan_min_km=('scan','min'),scan_median_km=('scan','median'),
        scan_p95_km=('scan',lambda x:x.quantile(.95)),scan_max_km=('scan','max'),
        track_min_km=('track','min'),track_median_km=('track','median'),
        track_p95_km=('track',lambda x:x.quantile(.95)),track_max_km=('track','max')).reset_index(),'january_footprint_summary')
    f.to_parquet(PROC/'firms_january_overlap.parquet',index=False)
    audit={'firms_archive':str(archive),'firms_sha256':sha256(archive),
        'archive_rows_scanned':scanned,'umd_january_rows':len(u),'firms_january_rows':len(f),
        'matched_rows_all_shared_native_fields':int(matched),
        'umd_unmatched_rows':int(len(u)-matched),'firms_unmatched_rows':int(len(f)-matched),
        'comparison_fields':common,'zip_crc_verified':True,
        'footprint_scope':'FIRMS January 1-17 2025 overlap only; MCD14ML has sample, not scan/track'}
    dump(OUT/'january_overlap_audit.json',audit)
    return audit

def main():
    for p in [OUT,TABLES,PROC]:p.mkdir(parents=True,exist_ok=True)
    raw=load()
    raw_rows=len(raw)
    raw['acq_utc']=pd.to_datetime(raw.acq_date+' '+raw.acq_time,format='%Y-%m-%d %H%M',utc=True,errors='coerce')
    checks={f'missing_{c}':int(raw[c].isna().sum()) for c in NATIVE}
    for c in NUMERIC:checks[f'nonfinite_{c}']=int((~np.isfinite(raw[c])).sum())
    checks.update({'invalid_coordinates':int((~raw.latitude.between(-90,90)|~raw.longitude.between(-180,180)).sum()),
        'invalid_datetime':int(raw.acq_utc.isna().sum()),
        'invalid_satellite':int((~raw.satellite.isin(['Terra','Aqua'])).sum()),
        'invalid_confidence':int((~raw.confidence.between(0,100)).sum()),
        'invalid_type':int((~raw.type.isin([0,1,2,3])).sum()),
        'invalid_daynight':int((~raw.daynight.isin(['D','N'])).sum()),
        'invalid_sample':int((~raw['sample'].between(0,1353)).sum()),
        'negative_frp':int(raw.frp.lt(0).sum()),'zero_frp':int(raw.frp.eq(0).sum()),
        'nonpositive_temperature':int((raw.brightness.le(0)|raw.bright_t31.le(0)).sum())})
    dup=raw.duplicated(NATIVE)
    checks['exact_duplicate_excess']=int(dup.sum())
    table(raw.loc[raw.duplicated(NATIVE,keep=False)],'exact_duplicates')
    invalid=(raw.acq_utc.isna()|~raw.latitude.between(-90,90)|~raw.longitude.between(-180,180)|
        ~raw.satellite.isin(['Terra','Aqua'])|~raw.daynight.isin(['D','N'])|
        ~raw.confidence.between(0,100)|~raw.type.isin([0,1,2,3]))
    checks['quarantined_rows']=int(invalid.sum())
    table(raw.loc[invalid],'quarantine')
    d=raw.loc[~dup&~invalid].copy()
    d['instrument']='MODIS';d['collection']='061';d['stream']='standard'
    d['confidence_class']=np.select([d.confidence.lt(30),d.confidence.lt(80)],['low','nominal'],default='high')
    d['retained']=d.confidence.ge(30)
    d['vegetation_retained']=d.retained&d.type.eq(0)
    d['frp_valid']=d.frp.ge(0)&np.isfinite(d.frp)
    d['solar_hour']=(d.acq_utc.dt.hour+d.acq_utc.dt.minute/60+d.longitude/15)%24
    d['solar_date']=(d.acq_utc+pd.to_timedelta(d.longitude/15,unit='h')).dt.strftime('%Y-%m-%d')
    d['month']=d.acq_date.str[:7]
    d['hemisphere']=np.where(d.latitude.ge(0),'Northern','Southern')
    key=['satellite','acq_utc','latitude','longitude']
    keydup=d.duplicated(key,keep=False)
    checks['rows_with_repeated_location_time_key']=int(keydup.sum())
    table(d.loc[keydup],'location_time_key_review')
    table(pd.DataFrame([{'check':k,'rows':v} for k,v in checks.items()]),'quality_checks')
    for c in ['satellite','daynight','confidence_class','stream','instrument','collection','hemisphere']:
        d[c]=d[c].astype('category')
    d.to_parquet(PROC/'detections.parquet',index=False)
    table(grouped_summary(d,['satellite']),'platform_summary')
    table(grouped_summary(d,['satellite','daynight']),'platform_daynight_summary')
    table(grouped_summary(d[d.type.eq(0)],['satellite','daynight']),'type0_daynight_summary')
    # Explicit monthly denominator handles two partial January periods.
    monthly=grouped_summary(d,['month','satellite'])
    month_days=pd.Series(DATES.strftime('%Y-%m')).value_counts()
    monthly['days_in_requested_window']=monthly.month.map(month_days)
    monthly['calendar_days_in_month']=monthly.month.map(lambda m:calendar.monthrange(int(m[:4]),int(m[5:]))[1])
    monthly['partial_month']=monthly.days_in_requested_window.ne(monthly.calendar_days_in_month)
    monthly['detections_per_requested_calendar_day']=monthly.rows/monthly.days_in_requested_window
    monthly['type0_conf30_per_requested_calendar_day']=monthly.type0_conf30_rows/monthly.days_in_requested_window
    table(monthly,'monthly')
    daily=d.groupby(['acq_date','satellite'],observed=True).agg(rows=('satellite','size'),
        retained=('retained','sum'),type0_conf30=('vegetation_retained','sum')).reset_index()
    index=pd.MultiIndex.from_product([DATES.strftime('%Y-%m-%d'),['Aqua','Terra']],names=['acq_date','satellite'])
    daily=daily.set_index(['acq_date','satellite']).reindex(index,fill_value=0).reset_index()
    daily['point_export_present']=True
    daily['valid_observation_coverage']='unknown_from_points'
    table(daily,'daily')
    for name,groups in [('confidence',['satellite','confidence_class']),('type',['satellite','type']),
        ('daynight',['satellite','daynight']),('hemisphere_monthly',['month','satellite','hemisphere'])]:
        table(d.groupby(groups,observed=True).size().rename('rows').reset_index(),name)
    quantiles=[]
    for (sat,dn),g in d.groupby(['satellite','daynight'],observed=True):
        for field in ['brightness','bright_t31','frp','confidence','sample','solar_hour']:
            x=g[field]
            if field=='frp':x=x[x.ge(0)]
            for q,v in x.quantile([0,.01,.25,.5,.75,.95,.99,1]).items():
                quantiles.append({'satellite':sat,'daynight':dn,'field':field,'quantile':q,'value':v})
    table(pd.DataFrame(quantiles),'exact_quantiles')
    high=[]
    for sat,g in d.groupby('satellite',observed=True):
        for threshold in [0,30,50,80,90]:
            a=g[g.confidence.ge(threshold)]
            high.append({'satellite':sat,'confidence_threshold':threshold,'rows':len(a),
                'type0_rows':int(a.type.eq(0).sum()),'kept_fraction':len(a)/len(g)})
    table(pd.DataFrame(high),'confidence_sensitivity')
    bins=d.assign(lon_bin=np.floor(d.longitude).astype(int),lat_bin=np.floor(d.latitude).astype(int))
    spatial=bins.groupby(['lon_bin','lat_bin','satellite'],observed=True).agg(
        rows=('satellite','size'),type0_conf30_rows=('vegetation_retained','sum'),
        detection_dates=('acq_date','nunique')).reset_index()
    table(spatial,'global_1degree_bins')
    table(spatial.sort_values('rows',ascending=False).head(40),'top_global_bins')
    table(d.nlargest(40,'frp'),'frp_extremes')
    corr=[]
    for (sat,dn),g in d[d.type.eq(0)&d.frp_valid].groupby(['satellite','daynight'],observed=True):
        fields=['frp','brightness','bright_t31','confidence','sample']
        c=g[fields].corr(method='spearman')
        for x in fields:
            for y in fields:corr.append({'satellite':sat,'daynight':dn,'x':x,'y':y,'spearman_r':c.loc[x,y],'rows':len(g)})
    table(pd.DataFrame(corr),'type0_spearman')
    timing=d.assign(solar_hour_bin=np.floor(d.solar_hour).astype(int)).groupby(
        ['satellite','daynight','solar_hour_bin'],observed=True).size().rename('rows').reset_index()
    table(timing,'solar_hour_bins')
    table(d.groupby(['month','satellite','daynight'],observed=True).solar_hour.agg(
        median='median',p25=lambda x:x.quantile(.25),p75=lambda x:x.quantile(.75),rows='size').reset_index(),'monthly_solar_timing')
    regions=[]; grid=[]
    transform=Transformer.from_crs(4326,6933,always_xy=True)
    for region,b in REGIONS.items():
        g=d[d.longitude.between(b[0],b[2])&d.latitude.between(b[1],b[3])].copy()
        g['x_m'],g['y_m']=transform.transform(g.longitude.to_numpy(),g.latitude.to_numpy())
        for size in [2000,5000,10000]:
            g['gx']=np.floor(g.x_m/size).astype(int);g['gy']=np.floor(g.y_m/size).astype(int)
            for sat,a in g[g.vegetation_retained].groupby('satellite',observed=True):
                grid.append({'region':region,'satellite':sat,'cell_km':size/1000,
                    'type0_conf30_detections':len(a),'positive_cells':len(a[['gx','gy']].drop_duplicates()),
                    'positive_cell_utc_days':len(a[['gx','gy','acq_date']].drop_duplicates()),
                    'positive_cell_solar_days':len(a[['gx','gy','solar_date']].drop_duplicates())})
            if size==5000:
                g['grid_x_5km']=g['gx'];g['grid_y_5km']=g['gy']
                recurrence=g[g.vegetation_retained].groupby(['satellite','gx','gy'],observed=True).agg(
                    rows=('satellite','size'),detection_dates=('acq_date','nunique'),lat=('latitude','mean'),
                    lon=('longitude','mean'),first=('acq_date','min'),last=('acq_date','max')).reset_index()
                table(recurrence.sort_values('detection_dates',ascending=False),f'{region}_5km_recurrence')
        g=g.drop(columns=['gx','gy'])
        g.to_parquet(PROC/f'{region}.parquet',index=False)
        if region=='pilot': table(g,'pilot_detections')
        s=grouped_summary(g,['satellite']);s.insert(0,'region',region);regions.append(s)
        m=grouped_summary(g,['month','satellite'])
        table(m,f'{region}_monthly')
    table(pd.concat(regions,ignore_index=True),'regional_summary')
    table(pd.DataFrame(grid),'regional_grid_sensitivity')
    # Sample is for visual scatter only; all reported summaries/quantiles are exact.
    sample=d.sample(min(40000,len(d)),random_state=20241017)
    sample.to_parquet(PROC/'scatter_sample.parquet',index=False)
    audit=january_audit(d)
    ps=pd.read_csv(TABLES/'platform_summary.csv')
    summary={'requested_start_inclusive_utc':START,'requested_end_inclusive_utc':END,
        'requested_calendar_dates':len(DATES),'geography':'global',
        'source':'UMD MODIS Fire Science Team MCD14ML Collection 061 version 03 standard monthly files',
        'monthly_files':13,'target_raw_rows':raw_rows,'analysis_rows':len(d),
        'exact_duplicate_excess':checks['exact_duplicate_excess'],'quality':checks,
        'platforms':ps.to_dict('records'),'regions':pd.concat(regions).to_dict('records'),
        'global_dates_with_any_exported_detection':d.acq_date.nunique(),
        'global_date_gaps':list(DATES.strftime('%Y-%m-%d')[~DATES.strftime('%Y-%m-%d').isin(d.acq_date.unique())]),
        'platform_dates_without_exported_detections':{sat:daily.loc[daily.satellite.eq(sat)&daily.rows.eq(0),'acq_date'].tolist() for sat in ['Terra','Aqua']},
        'january_overlap_audit':audit,'region_bounds':REGIONS,
        'solar_time_method':'UTC hours + longitude/15 modulo 24; approximate mean local solar time, no equation-of-time correction',
        'confidence_rule':'low<30; nominal30..79; high>=80; baseline retains>=30',
        'valid_negative_observations':'unavailable from point locations; requires fire masks/QA/geolocation',
        'source_schema_limitation':'MCD14ML has cross-track sample index, no explicit scan/track; January FIRMS overlap supplies footprint fields only for January1-17 2025',
        'quarantined_rows':checks['quarantined_rows'],'quantiles':'exact full selected population; not sampled',
        'scatter_sample_rows':len(sample),'scatter_sample_seed':20241017}
    dump(OUT/'summary.json',summary)
    # Scientific reconciliation and window assertions.
    assert len(d)==int(ps.rows.sum())==int(monthly.rows.sum())==int(daily.rows.sum())==int(spatial.rows.sum())
    assert d.acq_date.between(START,END).all() and len(DATES)==367
    assert d.acq_utc.min()>=pd.Timestamp(START,tz='UTC')
    assert d.acq_utc.max()<pd.Timestamp('2025-01-18',tz='UTC')
    assert len(d)==raw_rows-int(dup.sum())-int((invalid&~dup).sum())
    validation={'date_window_and_inclusive_day_count':'pass','platform_month_daily_spatial_totals':'pass',
        'native_exact_duplicate_rule':'pass','negative_frp_not_used_in_frp_quantiles':'pass',
        'export_zeros_not_valid_negative_labels':'pass','january_independent_native_field_match_fraction':audit['matched_rows_all_shared_native_fields']/max(audit['umd_january_rows'],1)}
    dump(OUT/'validation.json',validation)
    print(json.dumps({'analysis_rows':len(d),'platforms':summary['platforms'],'audit':audit},indent=2),flush=True)

if __name__=='__main__':main()
