"""Build deterministic regional EDA tables, scientific figures, and a readable report."""
from pathlib import Path
import json, math, datetime, hashlib, zipfile, xml.etree.ElementTree as ET
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm
import seaborn as sns
from pyproj import Transformer

ROOT=Path(__file__).resolve().parents[1]
T=ROOT/'reports/tables';F=ROOT/'reports/figures';P=ROOT/'data/processed'
COLORS={'Aqua':'#d45a35','Terra':'#986635','SNPP':'#148478','N20':'#397cc5','N21':'#9956ad'}
PLATFORMS=list(COLORS)
BBOX=(-6.4,34.5,-4.5,35.9)
TRANS=Transformer.from_crs(4326,6933,always_xy=True)
sns.set_theme(style='whitegrid',context='notebook',font_scale=1.05)
plt.rcParams.update({'figure.dpi':120,'savefig.dpi':170,'axes.spines.top':False,'axes.spines.right':False})

def csv(df,name):df.to_csv(T/f'{name}.csv',index=False)
def js(obj,name):(T/f'{name}.json').write_text(json.dumps(obj,indent=2,default=str))
def fig(name):
    plt.tight_layout();plt.savefig(F/f'{name}.png',bbox_inches='tight');plt.close()
def rectangle(df,b):
    w,s,e,n=b;return df.longitude.between(w,e)&df.latitude.between(s,n)
def table(df):return df.to_markdown(index=False,floatfmt='.3g')

def pair_candidates(d,size,tolerance):
    """Greedy nearest positive timestamp pairing, no reuse. NOT observation matching."""
    reference_years=d.loc[d.satellite.eq('Aqua'),'year'].unique()
    v=d[(d.daynight=='D')&d.retained&d.stream.eq('standard')&d.year.isin(reference_years)].copy()
    v['gx']=np.floor(v.x_m/size).astype(int);v['gy']=np.floor(v.y_m/size).astype(int)
    v=v[['satellite','gx','gy','acq_utc']].drop_duplicates()
    out=[]
    for sat in ['SNPP','N20']:
        counts={'grid_km':size/1000,'tolerance_min':tolerance,'source':sat,'pairs':0,'source_positive_times':int((v.satellite==sat).sum()),'aqua_positive_times':int((v.satellite=='Aqua').sum())}
        gaps=[]
        for (gx,gy),g in v.groupby(['gx','gy']):
            a=sorted(g.loc[g.satellite=='Aqua','acq_utc']);b=sorted(g.loc[g.satellite==sat,'acq_utc'])
            if not a or not b:continue
            aa=np.array([t.value for t in a]);bb=np.array([t.value for t in b])
            candidates=[]
            for i,stamp in enumerate(aa):
                left=np.searchsorted(bb,stamp-int(tolerance*60*1e9));right=np.searchsorted(bb,stamp+int(tolerance*60*1e9),side='right')
                for j in range(left,right):candidates.append((abs(stamp-bb[j])/60e9,i,j))
            used_a=set();used_b=set()
            for delta,i,j in sorted(candidates):
                if i in used_a or j in used_b:continue
                used_a.add(i);used_b.add(j);gaps.append(delta)
        counts['pairs']=len(gaps);counts['median_gap_min']=float(np.median(gaps)) if gaps else None
        out.append(counts)
    return out

def parse_effis():
    p=ROOT/'data/external/effis_country_totals_2024.xlsx'
    if not p.exists():return []
    ns={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    results=[]
    with zipfile.ZipFile(p) as z:
        strings=[]
        if 'xl/sharedStrings.xml' in z.namelist():
            for si in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('m:si',ns):strings.append(''.join(si.itertext()))
        for name in z.namelist():
            if not name.startswith('xl/worksheets/sheet') or not name.endswith('.xml'):continue
            rows=[]
            for row in ET.fromstring(z.read(name)).findall('.//m:row',ns):
                values={}
                for c in row.findall('m:c',ns):
                    val=c.find('m:v',ns);v=val.text if val is not None else ''
                    if c.get('t')=='s':v=strings[int(v)]
                    elif c.get('t')=='inlineStr':v=''.join(c.find('m:is',ns).itertext())
                    values[c.get('r')]=v
                rows.append(values)
            results.append({'sheet_xml':name,'rows':rows})
    js(results,'effis_workbook_cells');return results

def main():
    profiles=json.loads((T/'archive_profiles.json').read_text())
    inventory=[];quality=[];numeric=[];cats=[]
    for p in profiles:
        inventory.append({'archive':p['archive'],'stream':p['stream'],'platforms':','.join(p['categories']['satellite']),
                          'first_date':p['date_min'],'last_date':p['date_max'],'rows':p['rows'],
                          'pilot_rows':p['regions'].get('pilot',0),'south_spain_rows':p['regions'].get('southern_spain_rectangle',0),
                          'compressed_MB':p['signature']['bytes']/1e6,'uncompressed_MB':p['uncompressed_bytes']/1e6,
                          'duplicate_hash_excess':p['duplicate_row_hash_excess']})
        for field,n in p['missing'].items():quality.append({'archive':p['archive'],'check':'missing_'+field,'rows':n})
        for field,n in p['invalid'].items():quality.append({'archive':p['archive'],'check':field,'rows':n})
        for field,vals in p['categories'].items():
            for val,n in vals.items():cats.append({'archive':p['archive'],'field':field,'value':val,'rows':n})
        for field,vals in p['numeric'].items():
            numeric.append({'archive':p['archive'],'field':field,**{k:v for k,v in vals.items() if k!='sample_quantiles'},**{'sample_q'+k:v for k,v in vals['sample_quantiles'].items()}})
    inv=pd.DataFrame(inventory);csv(inv,'inventory');csv(pd.DataFrame(quality),'quality_checks');csv(pd.DataFrame(numeric),'global_numeric_profile');csv(pd.DataFrame(cats),'global_categories')
    d=pd.read_parquet(P/'regional_detections_raw.parquet')
    native=[c for c in d.columns if c not in ['archive','member','source_row']]
    exact_excess=int(d.duplicated(native).sum())
    csv(d[d.duplicated(native,keep=False)],'regional_exact_duplicates')
    d=d.drop_duplicates(native).copy()
    d['acq_time']=d.acq_time.str.zfill(4)
    d['acq_utc']=pd.to_datetime(d.acq_date+' '+d.acq_time,format='%Y-%m-%d %H%M',utc=True,errors='coerce')
    valid= d.acq_utc.notna()&d.latitude.between(-90,90)&d.longitude.between(-180,180)
    csv(d[~valid],'regional_quarantine');d=d[valid].copy()
    d['sensor_family']=np.where(d.satellite.isin(['Aqua','Terra']),'MODIS','VIIRS')
    conf=pd.to_numeric(d.confidence,errors='coerce')
    d['confidence_class']=np.where(d.sensor_family.eq('MODIS'),np.select([conf<30,conf<80,conf<=100],['low','nominal','high'],default='unknown'),d.confidence.map({'l':'low','n':'nominal','h':'high'}).fillna('unknown'))
    d['retained']=d.confidence_class.isin(['nominal','high'])
    d['year']=d.acq_utc.dt.year;d['month']=d.acq_utc.dt.month
    d['solar_hour']=(d.acq_utc.dt.hour+d.acq_utc.dt.minute/60+d.longitude/15)%24
    d['x_m'],d['y_m']=TRANS.transform(d.longitude.values,d.latitude.values)
    d['grid_x_5km']=np.floor(d.x_m/5000).astype(int);d['grid_y_5km']=np.floor(d.y_m/5000).astype(int)
    for name,b in {'pilot':BBOX,'southern_spain_rectangle':[-7.5,36,-1,38.5],'morocco_context_rectangle':[-13.5,27,-.9,36.1]}.items():d[name]=rectangle(d,b)
    key=['satellite','stream','acq_utc','latitude','longitude']
    csv(d[d.duplicated(key,keep=False)],'same_detection_key_review')
    d.to_parquet(P/'regional_detections.parquet',index=False)
    pilot=d[d.pilot].copy();pilot.to_parquet(P/'pilot_detections.parquet',index=False)
    csv(pilot,'pilot_detections')
    group=['satellite','stream','year']
    summary=pilot.groupby(group).agg(rows=('satellite','size'),retained=('retained','sum'),days_with_detections=('acq_date','nunique'),median_frp_MW=('frp','median'),max_frp_MW=('frp','max'),median_solar_hour=('solar_hour','median')).reset_index()
    csv(summary,'pilot_platform_year')
    conf_table=pilot.groupby(group+['confidence_class']).size().rename('rows').reset_index();csv(conf_table,'pilot_confidence')
    monthly=pilot.groupby(group+['month']).size().rename('rows').reset_index();csv(monthly,'pilot_monthly')
    daily=pilot.groupby(['satellite','stream','acq_date']).size().rename('rows').reset_index();csv(daily,'pilot_daily')
    types=pilot.groupby(['satellite','stream','type'],dropna=False).size().rename('rows').reset_index();csv(types,'pilot_type')
    quantiles=[]
    for (sat,stream),g in pilot.groupby(['satellite','stream']):
        for col in ['brightness','bright_t31','frp','scan','track','solar_hour']:
            for q,v in g[col].quantile([0,.01,.25,.5,.75,.95,.99,1]).items():quantiles.append({'satellite':sat,'stream':stream,'field':col,'quantile':q,'value':v})
    csv(pd.DataFrame(quantiles),'pilot_exact_quantiles')
    recurrence=pilot.groupby(['satellite','stream','grid_x_5km','grid_y_5km']).agg(rows=('satellite','size'),detection_days=('acq_date','nunique'),lon=('longitude','mean'),lat=('latitude','mean'),first=('acq_date','min'),last=('acq_date','max')).reset_index().sort_values('detection_days',ascending=False)
    csv(recurrence,'pilot_recurrence');csv(pilot.nlargest(40,'frp'),'pilot_frp_extremes')
    pairs=[]
    for size in [2000,5000,10000]:
        for tol in [15,30,60]:pairs+=pair_candidates(pilot,size,tol)
    pair_df=pd.DataFrame(pairs);csv(pair_df,'positive_timestamp_pair_diagnostics')
    grid=[]
    for size in [2000,5000,10000]:
        a=pilot.copy();a['gx']=np.floor(a.x_m/size).astype(int);a['gy']=np.floor(a.y_m/size).astype(int)
        for (sat,stream,yr),g in a.groupby(group):
            grid.append({'grid_km':size/1000,'satellite':sat,'stream':stream,'year':yr,'detection_rows':len(g),'positive_cell_days':len(g[['gx','gy','acq_date']].drop_duplicates()),'positive_cells':len(g[['gx','gy']].drop_duplicates())})
    csv(pd.DataFrame(grid),'grid_sensitivity')
    # Correlations describe detector-selected samples only, never causal drivers.
    cor=[]
    for sat,g in pilot.groupby('satellite'):
        vals=g[['brightness','bright_t31','frp','scan','track']].rank().corr(method='pearson')
        for x in vals:
            for y in vals:cor.append({'satellite':sat,'x':x,'y':y,'spearman_r':vals.loc[x,y]})
    csv(pd.DataFrame(cor),'pilot_correlations')
    # Detection calendar: NaN means no file covering this year; 0 means no exported rows.
    matrix=[];labels=[]
    date_support=[]
    for profile in profiles:
        if '_LS_' in profile['archive']:continue
        dd=pd.read_parquet(P/'archive_profiles'/Path(profile['archive']).stem/'daily.parquet')
        dd['stream']=profile['stream'];date_support.append(dd)
    support=pd.concat(date_support,ignore_index=True)
    support['year']=support.acq_date.str[:4].astype(int);support['month']=support.acq_date.str[5:7].astype(int)
    for (sat,stream,yr),sg in support.groupby(['satellite','stream','year']):
        g=pilot[(pilot.satellite==sat)&(pilot.stream==stream)&(pilot.year==yr)]
        counts=g.groupby('month').size().reindex(range(1,13),fill_value=0).astype(float)
        counts.loc[~counts.index.isin(sg.month.unique())]=np.nan
        matrix.append(counts.values)
        span=f'{sg.acq_date.min()} to {sg.acq_date.max()}'
        expected_days=366 if pd.Timestamp(f'{yr}-12-31').is_leap_year else 365
        partial=' incomplete dates' if sg.acq_date.nunique()<expected_days else ''
        labels.append(f'{sat} {yr} ({stream}){partial}')
    plt.figure(figsize=(13,max(5,len(labels)*.42)))
    sns.heatmap(np.array(matrix),annot=True,fmt='.0f',yticklabels=labels,xticklabels=list('JFMAMJJASOND'),cmap='YlOrRd',cbar_kws={'label':'Exported detection rows'})
    plt.gca().set_facecolor('#e9edef')
    plt.title('Northern Morocco: monthly detection rows\nZero rows do not establish a usable fire-free observation');plt.xlabel('Month (UTC)');fig('01_pilot_calendar')
    # Global binned density, all rows, including overlapping satellites.
    spatial=[]
    for p in profiles:
        s=pd.read_parquet(P/'archive_profiles'/Path(p['archive']).stem/'spatial.parquet');spatial.append(s)
    sp=pd.concat(spatial).groupby(['lat_bin','lon_bin'])['rows'].sum().reset_index();csv(sp,'global_spatial_bins')
    plt.figure(figsize=(13,5));plt.scatter(sp.lon_bin+.5,sp.lat_bin+.5,c=sp.rows,s=5,cmap='magma_r',norm=LogNorm())
    plt.colorbar(label='Detection rows per 1° bin (2023–2025 + 1 Jan 2026)');plt.xlim(-180,180);plt.ylim(-65,85);plt.xlabel('Longitude');plt.ylabel('Latitude');plt.title('Your downloads cover the globe; density is affected by sampling and source overlap');fig('02_global_distribution')
    # Detection positions, no web basemap or implied province boundary.
    f,axes=plt.subplots(2,3,figsize=(13,8),sharex=True,sharey=True)
    for ax,sat in zip(axes.flat,PLATFORMS):
        g=pilot[pilot.satellite==sat];ax.scatter(g.longitude,g.latitude,s=7,alpha=.45,c=COLORS[sat]);ax.set_title(f'{sat}: {len(g):,} rows');ax.set_xlim(BBOX[0],BBOX[2]);ax.set_ylim(BBOX[1],BBOX[3]);ax.set_xlabel('Longitude');ax.set_ylabel('Latitude')
    axes.flat[-1].axis('off');axes.flat[-1].text(.05,.8,'Computational study rectangle\nAll available years and confidences\nNo reviewed land/province clipping\nPoint clusters are not incident counts',transform=axes.flat[-1].transAxes,va='top')
    f.suptitle('Detection positions in the northern Morocco pilot',y=1.01);fig('03_pilot_positions')
    f,axes=plt.subplots(1,2,figsize=(13,4.5))
    for sat,g in pilot.groupby('satellite'):
        for flag,ax in zip(['D','N'],axes):
            x=g.loc[g.daynight==flag,'solar_hour'];ax.hist(x,bins=np.linspace(0,24,97),histtype='step',density=True,label=sat,color=COLORS[sat]);ax.set_title('Day detections' if flag=='D' else 'Night detections');ax.set_xlabel('Approximate local solar hour');ax.set_ylabel('Density among detections');ax.set_xlim(0,24)
    axes[0].legend();fig('04_detection_times')
    plt.figure(figsize=(10,5))
    for sat,g in pilot.groupby('satellite'):
        x=np.sort(g.frp.dropna());plt.step(x,np.arange(1,len(x)+1)/len(x),where='post',label=sat,color=COLORS[sat])
    plt.xscale('symlog',linthresh=.1);plt.xlabel('Per-detection FRP (MW), symlog axis');plt.ylabel('Fraction of detections at or below value');plt.title('FRP distributions among detected pixels');plt.legend();fig('05_frp_ecdf')
    pc=pilot.groupby(['satellite','confidence_class']).size().unstack(fill_value=0).reindex(columns=['low','nominal','high'],fill_value=0)
    pc.div(pc.sum(axis=1),axis=0).plot.bar(stacked=True,figsize=(10,4),color=['#cfb67c','#438c9c','#b34e39']);plt.ylabel('Fraction of detection rows');plt.xlabel('Platform');plt.xticks(rotation=0);plt.title('Native confidence mapped to documented categories');plt.legend(title='Confidence',bbox_to_anchor=(1.02,1));fig('06_confidence')
    f,axes=plt.subplots(1,2,figsize=(12,4.5))
    for sat,g in pilot.groupby('satellite'):
        axes[0].scatter(g.scan,g.track,s=5,alpha=.18,label=sat,color=COLORS[sat]);axes[1].scatter(g.brightness,g.frp,s=5,alpha=.18,color=COLORS[sat])
    axes[0].set(xlabel='Scan footprint dimension (km)',ylabel='Track footprint dimension (km)',title='MODIS/VIIRS footprint geometry');legend=axes[0].legend(markerscale=3)
    for handle in legend.legend_handles: handle.set_alpha(1)
    axes[1].set(xlabel='Sensor-specific brightness (K)',ylabel='FRP (MW)',title='Thermal channels differ by sensor');axes[1].set_yscale('symlog',linthresh=1);fig('07_geometry_thermal')
    p5=pair_df[pair_df.grid_km==5];f,ax=plt.subplots(figsize=(8,4))
    for sat,g in p5.groupby('source'):ax.plot(g.tolerance_min,g.pairs,'o-',label=sat,color=COLORS[sat])
    ax.set(xlabel='Maximum timestamp gap (minutes)',ylabel='Paired positive timestamp groups',title='5 km positive-only matching feasibility\nNot eligible observation pairs or training labels');ax.legend();fig('08_pairing_feasibility')
    f,ax=plt.subplots(figsize=(10,5))
    top=recurrence.head(12).copy();names=[f'{r.satellite} ({r.lon:.2f}, {r.lat:.2f})' for r in top.itertuples()]
    ax.barh(names[::-1],top.detection_days.values[::-1],color='#337c80');ax.set(xlabel='Distinct UTC days with detections',title='Repeatedly detected 5 km cells: review candidates, not automatic exclusions');fig('09_recurrence')
    parse_effis()
    # Per-platform date availability inferred from exported detections only.
    availability=[]
    for p in profiles:
        dd=pd.read_parquet(P/'archive_profiles'/Path(p['archive']).stem/'daily.parquet')
        for sat,g in dd.groupby('satellite'):
            present=set(g.acq_date);all_dates=pd.date_range(p['date_min'],p['date_max']).strftime('%Y-%m-%d')
            absent=[date for date in all_dates if date not in present]
            availability.append({'archive':p['archive'],'satellite':sat,'first_detection':g.acq_date.min(),'last_detection':g.acq_date.max(),'days_with_global_rows':g.acq_date.nunique(),'days_without_global_rows_inside_file_span':len(absent),'dates_without_rows':','.join(absent)})
    csv(pd.DataFrame(availability),'export_date_gaps')
    checks={'input_rows':int(inv.rows.sum()),'archives':len(profiles),'pilot_raw_rows':sum(p['regions'].get('pilot',0) for p in profiles),
            'pilot_deduplicated_valid_rows':len(pilot),'regional_exact_duplicate_excess':exact_excess,
            'regional_raw_rows':sum(len(pd.read_parquet(q)) for q in (P/'archive_profiles').glob('*/regional.parquet')),
            'regional_clean_rows':len(d),'global_hash_duplicate_excess':int(inv.duplicate_hash_excess.sum()),
            'all_zip_crc_verified':all(p['zip_crc_verified'] for p in profiles)}
    assert int(summary.rows.sum())==len(pilot)==int(monthly.rows.sum())==int(conf_table.rows.sum())
    assert len(d)==checks['regional_raw_rows']-exact_excess-int((~valid).sum())
    assert (d.acq_utc.dt.tz is not None) and d.satellite.isin(PLATFORMS).all()
    assert not d.duplicated(native).any()
    js(checks,'validation')
    make_report(inv,summary,pilot,types,pair_df,checks,profiles)
    print(json.dumps(checks,indent=2))

def make_report(inv,summary,pilot,types,pair_df,checks,profiles):
    peak=pilot.groupby('acq_date').size().sort_values(ascending=False).head(10).rename('detection_rows').reset_index()
    csv(peak,'pilot_busiest_dates')
    compressed=inv.compressed_MB.sum()/1000;uncompressed=inv.uncompressed_MB.sum()/1000
    report=f'''# FIREBRIDGE data exploration

Analysis run: {datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}.

## Read this first

The {len(inv)} archives contain **{checks['input_rows']:,} detection rows**, using {compressed:.2f} GB compressed and {uncompressed:.2f} GB uncompressed. Every CSV row was scanned. The northern Morocco rectangle contains **{checks['pilot_deduplicated_valid_rows']:,} valid, exactly deduplicated detections**. Global summaries use all records; global quantiles use a reproducible uniform sample of at most 20,000 rows per archive. Regional quantiles use all regional detections.

**These are hotspot detections, not a table of distinct fires.** Their absence does not prove that a satellite had a clear usable view. Full fire masks plus geolocation are the critical remaining input for the harmonization experiment.

Start with the inventory, then the Morocco figures, then the missing-data checklist. The executed notebook `notebooks/FIREBRIDGE_EDA.ipynb` lets you inspect and change the analysis without rereading the global files.

## 1. What you downloaded

{table(inv[['archive','platforms','stream','first_date','last_date','rows','pilot_rows']])}

- MODIS contains Aqua and Terra; keep their distinct observation times separate.
- The S-NPP archive writes `instrument=SNPP`. The native value is preserved; the derived sensor family is VIIRS.
- NOAA-21 files are NRT; do not treat their rows as interchangeable with standard archive rows.
- Landsat is a separate source with different field definitions and geographic availability. Its pilot row count above determines its relevance here.
- An already extracted Landsat CSV is inventoried but excluded from ingestion; its filename, size and CRC are compared with the ZIP member (`extracted_copies.json`).
- These files do not supply the blueprint's 2020–2022 training/development years. Aqua's substantive supplied year is 2025; trailing boundary-day records, if present, are shown separately. The originally proposed split is therefore unavailable. Any future 2024 holdout must be reserved again before outcome-driven model work; this EDA is not a frozen evaluation.

## 2. Geography and sampling

![Global density](figures/02_global_distribution.png)

The pilot bounds are west −6.4°, south 34.5°, east −4.5°, north 35.9°. They describe a rectangle, not Chefchaouen or Larache administrative boundaries. Land and water have not been polygon-clipped. A broader Morocco context rectangle and a southern-Spain rectangle were extracted for schema and coverage inspection; neither is a national statistic. Southern Spain has not been used for model fitting or performance tuning.

![Pilot map](figures/03_pilot_positions.png)

## 3. What the observations look like in Morocco

{table(summary)}

![Calendar](figures/01_pilot_calendar.png)

Cells report exactly deduplicated regional detection rows, including all native confidence classes. Gray/blank cells have no exported global rows for that platform/month. Years with fewer than the expected number of dates with global export rows are labeled incomplete dates; this includes internal gaps and boundary-only years. Some annual files include the next January 1: dates, not filenames, define year membership. A displayed zero means **no rows in this export**, with observation eligibility unknown. The count differences combine actual burning with sensor sensitivity, footprint, timing, processing, and missing observations. They cannot be interpreted as changes in incident numbers or burned hectares.

Busiest dates in the supplied files (all platforms pooled solely to find examples):

{table(peak)}

These are exploration candidates. Multiple satellites and adjacent pixels can repeatedly detect one episode. Do not use this ranking as an event catalog or select only these dates for training.

## 4. Quality, duplicates and unusual values

All ZIP CSV members passed full-read CRC verification: **{checks['all_zip_crc_verified']}**. The broad regional subset had **{checks['regional_exact_duplicate_excess']:,} exact excess rows**, removed only from derived tables; raw archives are preserved. Global full-row hashing found **{checks['global_hash_duplicate_excess']:,} excess equal hashes**. An independent raw-line comparison confirmed 304 exact duplicates in the 2024 Landsat file (`independent_validation.json`). This is a duplicate screen, not a mathematically collision-free identity proof. Global profile counts remain raw. Cross-file deduplication is exact for regional rows; global cross-file row equality is not exhaustively checked.

See `tables/quality_checks.csv` for missing fields, invalid coordinates, malformed dates/times and nonfinite numeric values. `global_numeric_profile.csv` contains exact extrema/means and explicitly sampled quantiles. `same_detection_key_review.csv` flags distinct records sharing platform, stream, time and location; they are retained for review. A missing column is a schema limitation rather than a zero-valued measurement.

![Confidence](figures/06_confidence.png)

Confidence filtering retains MODIS values ≥30 (nominal/high; high begins at 80) and VIIRS `n`/`h`. Raw rows remain available. These categories indicate detection quality, not comparable calibrated probabilities. No automatic outlier deletion is applied: large FRP may be a real detection, and a VIIRS brightness pile-up can reflect channel saturation. Review the guide before interpreting sentinel values or censoring.

![FRP](figures/05_frp_ecdf.png)

FRP is instantaneous radiative **power in MW**, not energy, burned area, or intensity per unit area. ECDFs compare distributions conditional on detections. They are not sensor calibration curves.

![Geometry](figures/07_geometry_thermal.png)

MODIS brightness uses channels 21/22 and 31; VIIRS fields correspond to I4 and I5 even when these exports use generic column labels `brightness` / `bright_t31`. Landsat scan/track are LOS pixel positions and must not enter these kilometer-footprint charts. Brightness temperatures describe the pixel signal, not the literal flame temperature.

Type flags in the pilot:

{table(types)}

For standard files, type 0 is presumed vegetation fire, 1 volcano, 2 other static land source, 3 offshore. Missing type (especially NRT) is unknown. A vegetation label does not distinguish agricultural burning from wildfire. No type is silently discarded in this EDA.

![Recurrence](figures/09_recurrence.png)

Repeated detection in one 5 km cell is a review flag, not proof of a factory or false detection. `pilot_recurrence.csv` supports inspection; multiple distinct fires and repeated agricultural burns can occur in one cell.

## 5. Timing and matching feasibility

![Timing](figures/04_detection_times.png)

UTC timestamps are formed with zero-padded HHMM. Approximate local solar hour is UTC hour + longitude/15 modulo 24; it is not Casablanca civil time. These histograms represent **detected** pixels only, not complete orbital coverage. Actual timestamp distributions must replace assumptions of fixed afternoon overpass times.

![Pair diagnostic](figures/08_pairing_feasibility.png)

{table(pair_df[pair_df.grid_km==5])}

The diagnostic is restricted to years with supplied Aqua detections (2025 here). It uses daytime nominal/high detections, standard sources, a 5 km EPSG:6933 grid anchored at (0,0), and greedy nearest timestamp matching without reuse within each sensor pair/cell. A timestamp group is not a resolved satellite pass or granule. Only both-positive samples exist here. This cannot estimate recall, false-positive rate, occurrence prevalence, reference-negative labels, or model accuracy. The 2/5/10 km and 15/30/60 minute sensitivity table is in `positive_timestamp_pair_diagnostics.csv`.

## 6. What each dataset adds

| Dataset | What it measures | What FIREBRIDGE needs it for |
|---|---|---|
| FIRMS MODIS/VIIRS points | Locations of detected thermal anomalies | Descriptive calendars and positive detections |
| MYD14 + compatible MYD03 | Aqua fire mask + full-pixel geolocation/geometry | Observable reference positives and negatives |
| VNP14IMG + VNP03IMG | S-NPP fire mask + geolocation | Source coverage and shared usable support |
| VJ114IMG + VJ103IMG | NOAA-20 fire mask + geolocation | Separate successor adapter |
| MOD14 + MOD03 | Terra mask + geolocation | Separate morning-regime analysis; MOD03 is a necessary companion even though omitted from the blueprint table |
| MCD12Q1 | Annual categorical land cover and QC | Forest/cropland/shrubland strata; no ignition cause |
| MCD64A1 | Monthly burned-pixel dates, uncertainty and QA | Timing/spatial corroboration; not independent of MODIS active-fire inputs |
| EFFIS | Country statistics and available burned-area products | External context; check lineage and granularity before evaluation |
| ERA5-Land | Gridded reanalysis weather/soil variables | Optional historical context; not an active-fire mask |
| Local incident reports | Reported events with uncertain time/location | Independent evidence when verified records exist |

Read `DATA_ACCESS.md` for actual download results and remaining authentication requirements. A catalog result is not a downloaded science asset. `download_manifest.json` records successful downloads and failures; the catalog files preserve granule IDs, size estimates and URLs. NASA catalog footprints still require spatial verification against full geolocation.

## 7. Recommended data decisions

1. Keep all raw files and native sensor fields. Use the small regional Parquet tables for daily work.
2. Use 2025 for the first descriptive Aqua–S-NPP feasibility exercise because those are the supplied overlapping files. Acquire standard 2020–2024 regional points before implementing the blueprint split. Avoid downloading more global CSVs just to work on Morocco.
3. Download and inspect a continuous, predeclared week of paired masks/geolocation including periods with no detected hotspots. Discovery here uses 14–20 July 2025; it is a schema/access smoke test, not a representative training sample or an event-selected success case.
4. Resolve collections and companions using acquisition keys, then compute full-pixel valid/cloud/water/invalid fractions. Follow documented QA definitions; do not guess bit masks.
5. Review a land/AOI polygon, establish the analysis grid, and preserve observations excluded by coverage thresholds with reasons.
6. Freeze temporal/spatial splits before fitting or selecting any harmonization model. EDA alone supplies no measured ML improvement.

## 8. Reproduce and audit

From the project root:

```bash
firebridge_env/bin/python analysis/profile_archives.py
firebridge_env/bin/python analysis/build_eda.py
firebridge_env/bin/python analysis/make_notebook.py
```

The full scan is chunked at 200,000 rows, processes one archive at a time, and caches per-file results keyed by source size/mtime. SHA-256 and ZIP CRC are recorded for each archive. A same-size/same-mtime modified file would require clearing its cache. Raw download timestamps are unknown for the supplied archives; filesystem timestamps are not claimed as retrieval times. The notebook uses precomputed data. `requirements-lock.txt` records package versions.

Integrity assertions reconcile regional raw rows, exact duplicates, quarantined rows, and independent grouped totals. All charts are descriptive. The missing observation denominator prevents computation of the blueprint's H(W) and C(W) metrics.

## Sources and definitions

- [NASA FIRMS archive README](https://firms.modaps.eosdis.nasa.gov/download/Readme.txt) — file naming and stream conventions. Its NOAA-20 availability note conflicts with actual supplied standard files; source files and current catalog inventory take precedence for this inventory.
- [NASA MODIS/VIIRS attribute definitions](https://www.earthdata.nasa.gov/data/tools/firms/active-fire-data-attributes-modis-viirs) — measurement units, confidence, type flags and spectral meaning.
- [MODIS C6/C6.1 fire user guide](https://www.earthdata.nasa.gov/s3fs-public/2023-09/MODIS_C6_C6.1_Fire_User_Guide_1.0.pdf) — product and mask interpretation.
- [VIIRS Collection 2 fire user guide](https://www.earthdata.nasa.gov/s3fs-public/2025-06/VIIRS_C2_AF-375m_User_Guide_1.2.pdf) — VIIRS-specific interpretation.
- [NASA Landsat FAQ](https://forum.earthdata.nasa.gov/viewtopic.php?t=5197) — Landsat coverage, scan/track semantics and detection characteristics.
- [NASA CMR](https://cmr.earthdata.nasa.gov/search/site/docs/search/api.html) — collection/granule discovery; query responses saved locally.
- [EFFIS data/services](https://forest-fire.emergency.copernicus.eu/applications/data-and-services) — country totals and data request routes.
- [ORNL subset service](https://modis.ornl.gov/data/modis_webservice.html) — bounded scientific subsets; service failures are retained.
- [ERA5-Land](https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land?tab=overview) — optional context.

Local analysis follows the supplied `FIREBRIDGE_Blueprint.md` as a proposed research design, not a validated algorithm. No app, predictive model or hackathon submission is produced here.
'''
    (ROOT/'reports/FIREBRIDGE_EDA.md').write_text(report)

if __name__=='__main__':main()
