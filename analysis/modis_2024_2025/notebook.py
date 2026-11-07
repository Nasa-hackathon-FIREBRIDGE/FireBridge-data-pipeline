"""Build and execute the teaching notebook against real global MODIS data."""
from pathlib import Path
import json, os
import nbformat as nbf
from nbclient import NotebookClient

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'notebooks/MODIS_Terra_Aqua_2024_2025.ipynb'
def main():
    cells=[]
    def md(s):cells.append(nbf.v4.new_markdown_cell(s))
    def code(s):cells.append(nbf.v4.new_code_cell(s))
    md('''# MODIS Terra and Aqua: understand the data before modeling
**January 17, 2024–January 17, 2025 inclusive, UTC, worldwide.**

This notebook explores real standard MCD14ML detections downloaded from the MODIS Fire Science Team. Every row is a detected thermal anomaly associated with a pixel and time. It is not automatically an incident, ignition, wildfire, or burned-area measurement.

Run cells in order. The report and presentation explain the results in plain language. This notebook shows how to inspect and reproduce them. The raw files remain unchanged.''')
    code('''from pathlib import Path
import json
import numpy as np
import pandas as pd
from IPython.display import display, Image

ROOT=Path.cwd()
if ROOT.name == 'notebooks': ROOT=ROOT.parent
assert (ROOT/'FIREBRIDGE_Blueprint.md').exists(), 'Run from the project root or notebooks folder'
R=ROOT/'reports/modis_2024_2025'
P=ROOT/'data/processed/modis_2024_2025'
def table(name): return pd.read_csv(R/'tables'/f'{name}.csv')
def figure(name): display(Image(filename=str(R/'figures'/name)))
summary=json.loads((R/'summary.json').read_text())
print(summary['requested_start_inclusive_utc'], 'through', summary['requested_end_inclusive_utc'])
print(f"{summary['requested_calendar_dates']} calendar dates; {summary['analysis_rows']:,} detections")''')
    md('''## 1. Where the data came from
Thirteen monthly gzip files cover January 2024–January 2025. The pipeline takes January 17 onward from the first file and January 17 or earlier from the last. January 2024 has **15** dates in this analysis; January 2025 has **17**.

The source fields are `YYYYMMDD HHMM sat lat lon T21 T31 sample FRP conf type dn`. `T/A` becomes Terra/Aqua, and `HHMM` must keep leading zeros. `sample` is the cross-track pixel index, **0–1353**, rather than a measurement in km. Explicit FIRMS `scan` and `track` are absent from these new raw files.''')
    code('''inventory=table('input_inventory')
display(inventory[['filename','raw_rows','target_rows','excluded_date_rows','raw_start','raw_end']])
assert inventory.target_rows.sum()==summary['analysis_rows']
assert summary['requested_calendar_dates']==len(pd.date_range('2024-01-17','2025-01-17'))==367''')
    md('''## 2. Read actual detections
The processed Parquet keeps source filename and row number, native values and derived fields. The sample below is a real row, not an invented example. Acquisition is UTC. Temperatures are brightness temperatures in Kelvin, not flame temperature; FRP is power in MW.''')
    code('''cols=['source_file','source_row','satellite','acq_date','acq_time','acq_utc','latitude','longitude',
      'brightness','bright_t31','sample','frp','confidence','type','daynight',
      'confidence_class','retained','vegetation_retained','frp_valid','solar_hour','solar_date','month']
d=pd.read_parquet(P/'detections.parquet',columns=cols)
display(d.head(5))
print('Rows:',len(d),'Memory MB:',round(d.memory_usage(deep=True).sum()/1e6,1))
assert len(d)==summary['analysis_rows']
assert d.acq_date.between('2024-01-17','2025-01-17').all()''')
    md('''## 3. Quality and independent source agreement
Inspect missing fields, invalid coordinates/times, non-finite numbers, categories and exact duplicates. A confidence of 0 is a valid low-confidence detection. A FRP of 0 is preserved and flagged; it does not turn the row into a negative observation.

The original FIRMS archive is an independent January 1–17, 2025 check. Compare multiplicities of every shared native field; do not ingest it again and double the records.''')
    code('''display(table('quality_checks'))
audit=json.loads((R/'january_overlap_audit.json').read_text())
display(pd.Series({k:v for k,v in audit.items() if k not in ['comparison_fields']}))
assert audit['matched_rows_all_shared_native_fields']==audit['umd_january_rows']==audit['firms_january_rows']
assert audit['umd_unmatched_rows']==audit['firms_unmatched_rows']==0
print('All shared January records match exactly.')''')
    md('''## 4. Terra and Aqua separately
They carry the same instrument but sample different times. More detected pixels does not prove greater accuracy or more distinct incidents. Split day and night before interpreting comparisons.''')
    code('''display(table('platform_summary'))
display(table('platform_daynight_summary'))
counts=d.groupby('satellite',observed=True).size()
print('Aqua / Terra detection ratio:',round(counts['Aqua']/counts['Terra'],3))
for sat,g in d.groupby('satellite',observed=True):
    print(sat, 'daytime share:', round(100*g.daynight.eq('D').mean(),2),'%')''')
    md('''## 5. Monthly activity and partial-month denominators
Use counts per requested calendar date when comparing partial January bins. Even normalized counts are still conditional on sampling and detection, not coverage-corrected rates. One annual cycle cannot establish a historical climatology or an unusual-season threshold.''')
    code('''monthly=table('monthly')
display(monthly[['month','satellite','rows','days_in_requested_window','partial_month',
      'detections_per_requested_calendar_day','type0_conf30_per_requested_calendar_day']])
assert monthly.rows.sum()==len(d)==table('daily').rows.sum()
figure('01_monthly_rates.png')
figure('06_hemisphere_seasons.png')''')
    md('''## 6. Global geography
The map includes every detection, aggregated into 1° bins. These bins have different physical areas by latitude. A dark bin indicates many exported detections, not a measured level of wildfire risk. Basemap boundaries are coarse cartographic context; no national rates are estimated here.''')
    code('''figure('02_global_map.png')
spatial=table('global_1degree_bins')
assert spatial.rows.sum()==len(d)
display(table('top_global_bins').head(12))''')
    md('''## 7. Confidence and native source types
Baseline project filter: `confidence >= 30`. A candidate vegetation layer also requires `type == 0`. Low <30; nominal 30–79; high ≥80. Type 0 means presumed vegetation fire, type 1 volcano, type 2 other static land source, type 3 offshore.

Native confidence is a detection-quality score, not a calibrated probability of wildfire. Keep every raw category, and measure how much a stricter rule changes the results. Persistent hotspots need review rather than automatic deletion: agricultural burning is in the project's scope.''')
    code('''display(table('type'))
display(table('confidence_sensitivity'))
candidate=d[d.vegetation_retained]
print('Candidate vegetation detections:',len(candidate),f'({100*len(candidate)/len(d):.2f}% of all points)')
figure('03_confidence.png')
figure('10_confidence_sensitivity.png')''')
    md('''## 8. Fire radiative power and temperature
The long FRP tail makes the mean larger than the median. Describe quantiles before choosing an outlier threshold. High FRP can be real and should not be removed just because it is large. Zero values remain flagged.

Power at different passes cannot be summed as energy. MW is not hectares. A larger pixel can include more fire, and brightness/FRP relationships partly reflect the shared retrieval process.''')
    code('''display(table('exact_quantiles').query("field == 'frp'"))
display(table('frp_extremes')[['satellite','acq_date','acq_time','latitude','longitude','frp','confidence','type']].head(10))
figure('04_frp_distribution.png')
figure('11_thermal_frp.png')
corr=table('type0_spearman')
display(corr[(corr.x=='frp')&(corr.y.isin(['brightness','confidence','sample']))])''')
    md('''## 9. Actual acquisition timing
Approximate local mean solar hour = `(UTC hour + longitude/15) % 24`. It is not civil time and has no equation-of-time correction. The derived solar date can differ from UTC date.

Both orbits drifted by 2024, so fixed historical 10:30/13:30 assumptions are unsuitable. These distributions describe detected hotspots, not all possible observations or the satellite's exact equator crossings.''')
    code('''figure('05_solar_time.png')
display(table('monthly_solar_timing'))
print('Rows whose approximate local solar date differs from UTC:',d.solar_date.ne(d.acq_date).sum())''')
    md('''## 10. Pixel geometry: a limited audit
The user's original FIRMS CSV supplies `scan/track` for January 1–17, 2025. These fields are **not** present for the new full-year MCD14ML source. A pixel is nominally about 1 km at nadir and larger away from nadir. `scan*track` is a footprint proxy, not the area actually burning.''')
    code('''display(table('january_footprint_summary'))
figure('09_footprint_january.png')''')
    md('''## 11. Northern Morocco pilot and aggregation choices
The blueprint study rectangle is −6.4..−4.5° longitude, 34.5..35.9° latitude. This is not a province boundary, national statistic or reviewed land mask. Only **57** detections occur here; **49** meet the proposed vegetation/confidence rule. Many dots can belong to the same continuing event, so this is not 49 independent training examples.

The 2/5/10 km table shows how detection counts differ from cells with at least one detection. These are descriptive cell-days across all regimes, **not eligible Aqua–VIIRS labels**.''')
    code('''display(table('regional_summary'))
display(table('regional_grid_sensitivity').query("region=='pilot'"))
pilot=pd.read_parquet(P/'pilot.parquet')
display(pilot[['satellite','acq_date','acq_time','confidence','type','frp','grid_x_5km','grid_y_5km']].head(10))
figure('07_pilot_calendar.png')
figure('08_pilot_map.png')''')
    md('''## 12. What FIREBRIDGE can do now
Build a transparent calendar of **recorded detections**, split by platform and inclusion rule. Preserve the source and raw attributes. Show three distinct future states: detected activity, usable observation with no retained activity, and unsupported observation. Point files currently support only the first state.

The blueprint's main harmonization target is an **Aqua-equivalent detection response**, with Aqua treated as an imperfect reference convention on a proposed 5 km grid. Terra's morning regime requires its own adapter/evaluation. The current global EDA is not a globally validated harmonization model.''')
    code('''daily=table('daily')
display(daily.head())
assert daily.valid_observation_coverage.eq('unknown_from_points').all()
print('No valid negative-observation labels can be derived from these points alone.')''')
    md('''## 13. Next work, in order
1. Review the pilot AOI/land mask; broaden years or region to obtain enough independent episodes. One year cannot establish normal versus unusual activity.
2. Acquire a bounded pilot sample of Aqua **MYD14** / compatible **MYD03**, Terra **MOD14** / compatible **MOD03**, and VIIRS fire masks/geolocation. Explicitly resolve collection compatibility.
3. Decode full fire masks and QA, including clouds, water and unprocessed pixels; calculate usable land per cell/pass. Do not invent negatives from absent dots.
4. Create opportunities by actual time and common usable support. The blueprint initially proposes ≤30-minute Aqua–VIIRS pairing, ≥80% usable shared land and 5 km cells; test alternatives.
5. Freeze separate temporal/geographic evaluation blocks. Keep target-only Aqua values, future observations and post-event labels out of predictors. Train a transparent baseline only after positive and eligible negative labels exist.
6. Withhold Aqua, predict its defined response using VIIRS, then reveal Aqua and report held-out errors and uncertainty. Add a separately evaluated Terra adapter later.

**Not established here:** burned area, ignition counts, cloud-corrected trends, classifier accuracy, causes of seasonal changes, or deployment readiness.

Sources: [MODIS C6/C6.1 guide](https://www.earthdata.nasa.gov/s3fs-public/2023-09/MODIS_C6_C6.1_Fire_User_Guide_1.0.pdf), [NASA 2024 orbital drift](https://ntrs.nasa.gov/api/citations/20250000522/downloads/AGU24_Terra_25years_MODIS_geometry_poster_GLin.pdf), [FIREBRIDGE blueprint](../FIREBRIDGE_Blueprint.md), and the linked report's detailed source notes.''')
    nb=nbf.v4.new_notebook(cells=cells,metadata={'kernelspec':{'name':'firebridge-modis','display_name':'FIREBRIDGE Python 3.12','language':'python'}})
    OUT.parent.mkdir(exist_ok=True)
    nbf.write(nb,OUT)
    kernel_dir=Path('/tmp/firebridge-modis-jupyter/kernels/firebridge-modis')
    kernel_dir.mkdir(parents=True,exist_ok=True)
    (kernel_dir/'kernel.json').write_text(json.dumps({'argv':[str(ROOT/'firebridge_env/bin/python'),'-m','ipykernel_launcher','-f','{connection_file}'],
        'display_name':'FIREBRIDGE Python 3.12','language':'python'}))
    os.environ.update({'JUPYTER_PATH':'/tmp/firebridge-modis-jupyter',
        'JUPYTER_RUNTIME_DIR':'/tmp/firebridge-modis-jupyter/runtime','IPYTHONDIR':'/tmp/firebridge-modis-ipython',
        'MPLCONFIGDIR':'/tmp/firebridge-mpl'})
    client=NotebookClient(nb,timeout=180,kernel_name='firebridge-modis',resources={'metadata':{'path':str(ROOT)}})
    client.execute()
    nbf.write(nb,OUT)
    print(f'Executed {sum(c.cell_type=="code" for c in cells)} code cells: {OUT}',flush=True)

if __name__=='__main__':main()
