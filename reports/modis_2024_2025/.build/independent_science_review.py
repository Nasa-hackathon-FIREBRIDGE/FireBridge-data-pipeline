from pathlib import Path
import sys,json,hashlib,zipfile
sys.path.insert(0,'/home/da-rog/dev_projects/FIREBRIDGE-project/firebridge_env/lib/python3.12/site-packages')
import pandas as pd
import numpy as np
from pyproj import Transformer

R=Path('/home/da-rog/dev_projects/FIREBRIDGE-project')
O=R/'reports/modis_2024_2025'
T=O/'tables'
P=R/'data/processed/modis_2024_2025'
I=pd.read_csv(T/'input_inventory.csv')
S=json.loads((O/'summary.json').read_text())
results={}
def check(name,condition,detail=None):
    assert condition,(name,detail)
    results[name]={'pass':True,'detail':detail}

# Fresh scan of every supplied monthly file, independent of the saved point table.
raw_counts=[]
raw_flags={'invalid_time':0,'invalid_sample':0,'noninteger_sample':0,'bad_date_month':0,'bad_native_satellite':0,'bad_native_daynight':0}
for row in I.itertuples():
    p=R/'data/external/modis_2024_2025'/row.filename
    check('sha256_'+row.filename,hashlib.sha256(p.read_bytes()).hexdigest()==row.sha256)
    n=selected=0
    for a in pd.read_csv(p,sep=r'\s+',dtype={'YYYYMMDD':str,'HHMM':str},chunksize=250000):
        n+=len(a)
        raw_flags['bad_date_month']+=int(a.YYYYMMDD.str[:6].ne(row.filename.split('.')[1]).sum())
        g=a.loc[a.YYYYMMDD.between('20240117','20250117')].copy()
        selected+=len(g)
        h=g.HHMM.str.zfill(4)
        valid=h.str.fullmatch(r'\d{4}')&h.str[:2].astype(int).between(0,23)&h.str[2:].astype(int).between(0,59)
        raw_flags['invalid_time']+=int((~valid).sum())
        raw_flags['invalid_sample']+=int((~g['sample'].between(0,1353)).sum())
        raw_flags['noninteger_sample']+=int(g['sample'].mod(1).ne(0).sum())
        raw_flags['bad_native_satellite']+=int((~g.sat.isin(['A','T'])).sum())
        raw_flags['bad_native_daynight']+=int((~g.dn.isin(['D','N'])).sum())
        raw_counts.append(g.groupby(['YYYYMMDD','sat']).size().rename('raw_rows').reset_index())
    check('raw_rows_'+row.filename,n==row.raw_rows,n)
    check('target_rows_'+row.filename,selected==row.target_rows,selected)
    print('RAW VERIFIED',row.filename,n,selected,flush=True)
check('all_raw_native_flags_clear',not any(raw_flags.values()),raw_flags)
rc=pd.concat(raw_counts).groupby(['YYYYMMDD','sat']).raw_rows.sum().reset_index()
rc['acq_date']=pd.to_datetime(rc.YYYYMMDD,format='%Y%m%d').dt.strftime('%Y-%m-%d')
rc['satellite']=rc.sat.map({'A':'Aqua','T':'Terra'})
daily=pd.read_csv(T/'daily.csv')
joined=rc.merge(daily,on=['acq_date','satellite'],how='outer')
check('raw_daily_inventory_exact',joined.raw_rows.eq(joined.rows).all(),int(rc.raw_rows.sum()))
check('requested_inclusive_dates',daily.acq_date.nunique()==367 and daily.acq_date.min()=='2024-01-17' and daily.acq_date.max()=='2025-01-17')
check('global_platform_date_inventory',len(daily)==734 and daily.rows.gt(0).all())

d=pd.read_parquet(P/'detections.parquet')
check('all_timestamp_bounds',d.acq_utc.ge(pd.Timestamp('2024-01-17',tz='UTC')).all() and d.acq_utc.lt(pd.Timestamp('2025-01-18',tz='UTC')).all())
check('all_numeric_finite',np.isfinite(d[['latitude','longitude','brightness','bright_t31','sample','frp','confidence','type']].to_numpy()).all())
check('sample_native_zero_based_range',d['sample'].between(0,1353).all(),[int(d['sample'].min()),int(d['sample'].max())])
native=['acq_date','acq_time','satellite','latitude','longitude','brightness','bright_t31','sample','frp','confidence','type','daynight']
check('no_exact_native_duplicates',not d.duplicated(native).any())
check('no_location_time_key_duplicates',not d.duplicated(['satellite','acq_utc','latitude','longitude']).any())
check('confidence_and_type_flags',d.retained.eq(d.confidence.ge(30)).all() and d.vegetation_retained.eq(d.confidence.ge(30)&d.type.eq(0)).all())
check('summary_row_count',len(d)==S['analysis_rows']==4876343)
for filename in ['daily','monthly','platform_summary','daynight','confidence','type','hemisphere_monthly','global_1degree_bins','solar_hour_bins']:
    a=pd.read_csv(T/(filename+'.csv'))
    check(filename+'_row_total',int(a.rows.sum())==len(d),int(a.rows.sum()))
    for sat,g in a.groupby('satellite'):
        check(filename+'_'+sat+'_total',int(g.rows.sum())==int(d.satellite.eq(sat).sum()),int(g.rows.sum()))
monthly=pd.read_csv(T/'monthly.csv')
den=pd.Series(pd.date_range('2024-01-17','2025-01-17').strftime('%Y-%m')).value_counts()
check('monthly_calendar_denominators',monthly.days_in_requested_window.eq(monthly.month.map(den)).all())
check('monthly_partial_januaries',set(monthly.loc[monthly.partial_month,'month'])=={'2024-01','2025-01'})
check('monthly_retained_total',int(monthly.type0_conf30_rows.sum())==int(d.vegetation_retained.sum()),int(d.vegetation_retained.sum()))

q=pd.read_csv(T/'exact_quantiles.csv')
quantile_max_diff=0
for (sat,dn,field),a in q.groupby(['satellite','daynight','field']):
    v=d.loc[d.satellite.eq(sat)&d.daynight.eq(dn),field]
    if field=='frp':v=v[v.ge(0)]
    expect=v.quantile(a['quantile'].tolist()).to_numpy()
    quantile_max_diff=max(quantile_max_diff,float(np.max(np.abs(expect-a.value.to_numpy()))))
check('full_population_quantiles',quantile_max_diff<1e-10,quantile_max_diff)

tr=Transformer.from_crs(4326,6933,always_xy=True)
grid=pd.read_csv(T/'regional_grid_sensitivity.csv')
regions=pd.read_csv(T/'regional_summary.csv')
unlabeled_grid_exports=[]
for region,b in S['region_bounds'].items():
    g=d[d.longitude.between(b[0],b[2])&d.latitude.between(b[1],b[3])].copy()
    for sat,a in g.groupby('satellite',observed=True):
        check(region+'_'+sat+'_rectangle_count',len(a)==int(regions.loc[regions.region.eq(region)&regions.satellite.eq(sat),'rows'].iloc[0]),len(a))
    g=g[g.vegetation_retained].copy()
    x,y=tr.transform(g.longitude.to_numpy(),g.latitude.to_numpy())
    for size in [2000,5000,10000]:
        g['gx']=np.floor(x/size).astype(int);g['gy']=np.floor(y/size).astype(int)
        for sat,a in g.groupby('satellite',observed=True):
            e=grid.loc[grid.region.eq(region)&grid.satellite.eq(sat)&grid.cell_km.eq(size/1000)].iloc[0]
            check(region+'_'+sat+'_'+str(size)+'_positive_counts',
                len(a)==e.type0_conf30_detections and len(a[['gx','gy']].drop_duplicates())==e.positive_cells and
                len(a[['gx','gy','acq_date']].drop_duplicates())==e.positive_cell_utc_days and
                len(a[['gx','gy','solar_date']].drop_duplicates())==e.positive_cell_solar_days)
    saved=pd.read_parquet(P/(region+'.parquet'))
    if 'gx' in saved:
        sx,sy=tr.transform(saved.longitude.to_numpy(),saved.latitude.to_numpy())
        is10=np.array_equal(saved.gx,np.floor(sx/10000).astype(int)) and np.array_equal(saved.gy,np.floor(sy/10000).astype(int))
        unlabeled_grid_exports.append({'region':region,'gx_gy_are_10km':is10})
results['unlabeled_region_grid_exports']={'detail':unlabeled_grid_exports}

# Independent sorted-frame multiset audit; read source CSV freshly, not its cache.
zpath=Path(S['january_overlap_audit']['firms_archive'])
fparts=[]
with zipfile.ZipFile(zpath) as z:
    name=[n for n in z.namelist() if n.endswith('.csv')][0]
    with z.open(name) as f:
        for a in pd.read_csv(f,dtype={'acq_time':str,'acq_date':str},chunksize=250000):
            b=a[a.acq_date.between('2025-01-01','2025-01-17')]
            if len(b):fparts.append(b.copy())
f=pd.concat(fparts,ignore_index=True)
f['acq_time']=f.acq_time.str.zfill(4)
common=[c for c in native if c!='sample']
u=d[d.acq_date.ge('2025-01-01')][common].copy()
u['satellite']=u.satellite.astype(str);u['daynight']=u.daynight.astype(str)
u=u.sort_values(common).reset_index(drop=True)
f=f[common].sort_values(common).reset_index(drop=True)
pd.testing.assert_frame_equal(u,f,check_dtype=False)
check('fresh_january_exact_multiset',len(u)==len(f)==202406,len(u))
check('january_difference_export_empty',len(pd.read_csv(T/'january_overlap_differences.csv'))==0)
(O/'.build/independent_science_checks.json').write_text(json.dumps(results,indent=2))
print('ALL INDEPENDENT CHECKS PASSED',len(results),flush=True)
