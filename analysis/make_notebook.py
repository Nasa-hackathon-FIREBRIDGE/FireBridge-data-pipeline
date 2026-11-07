"""Author and execute the educational EDA notebook against cached, real data."""
from pathlib import Path
import nbformat as nbf
from nbclient import NotebookClient
ROOT=Path(__file__).resolve().parents[1]
nb=nbf.v4.new_notebook();cells=[]
def md(s):cells.append(nbf.v4.new_markdown_cell(s))
def code(s):cells.append(nbf.v4.new_code_cell(s))
md('''# FIREBRIDGE: understand your data before harmonizing it

This notebook explores the actual downloaded observations. It uses the full archive profiles and small regional Parquet tables produced by `analysis/profile_archives.py`. Original ZIPs are unchanged.

**Questions:** What does a row represent? Which sensors, years and locations do we have? Which fields are comparable? What quality issues exist? Can the supplied data support the blueprint's experiment?

Read `reports/FIREBRIDGE_EDA.md` for the narrative and `reports/DATA_ACCESS.md` for acquisition status. No model is fitted. Detection absence is never labeled as an observed negative.''')
code('''from pathlib import Path
import json
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from IPython.display import display, Image, Markdown
ROOT = Path.cwd()
if ROOT.name == 'notebooks': ROOT = ROOT.parent
TABLES = ROOT / 'reports/tables'
DATA = ROOT / 'data/processed'
pd.set_option('display.max_columns', 30)
pd.set_option('display.max_colwidth', 70)
profiles = json.loads((TABLES/'archive_profiles.json').read_text())
pilot = pd.read_parquet(DATA/'pilot_detections.parquet')
regional = pd.read_parquet(DATA/'regional_detections.parquet')
print(f'{len(profiles)} archives; {sum(p["rows"] for p in profiles):,} global rows scanned')
print(f'{len(pilot):,} valid deduplicated pilot detections; {len(regional):,} regional detections')
''')
md('''## 1. Inventory and source identity

One row is a **detected thermal-anomaly pixel at acquisition time**. It is not necessarily one fire. Different resolution, time, confidence, and processing create different counts.

`M-C61` = MODIS Collection 6.1 (Aqua + Terra). `SV-C2` = VIIRS S-NPP. `J1V-C2` = NOAA-20. `J2V-C2` = NOAA-21. `LS` = Landsat. Filename suffixes are request IDs, not years. Use the actual date columns.''')
code("display(pd.read_csv(TABLES/'inventory.csv'))\ndisplay(pd.read_json(TABLES/'extracted_copies.json'))")
md('''## 2. Schema, units, missing values and outliers

Read the field dictionary before merging columns. MODIS confidence is numeric; VIIRS confidence is categorical. Landsat scan/track do not mean kilometers. NRT lacks fields found in the standard files. Missing FRP is not zero FRP.''')
code("display(pilot.head(8))\ndisplay(pilot.dtypes.to_frame('derived_dtype'))\nquality = pd.read_csv(TABLES/'quality_checks.csv')\ndisplay(quality[quality.rows > 0])\ndisplay(pd.read_csv(TABLES/'global_numeric_profile.csv'))")
code("display(pd.read_csv(TABLES/'pilot_exact_quantiles.csv'))\ndisplay(pd.read_csv(TABLES/'same_detection_key_review.csv').head(12))\ndisplay(pd.read_json(TABLES/'validation.json', typ='series'))")
md('''Global quantiles are based on a uniform random-priority sample of up to 20,000 rows per archive (seed 20260926). Extrema, means, categorical counts and missing counts scan all rows. Pilot quantiles use the entire regional table. Global hash duplicate counts are a screen; regional exact duplicates are confirmed using all native fields.''')
md('''## 3. Where are the detections?

Northern Morocco pilot: longitude −6.4 to −4.5, latitude 34.5 to 35.9. This is a computational rectangle. Water and neighboring administrative areas are not polygon-clipped. The context and Spain rectangles are not national boundaries.''')
code("display(Image(filename=str(ROOT/'reports/figures/02_global_distribution.png')))\ndisplay(Image(filename=str(ROOT/'reports/figures/03_pilot_positions.png')))")
code("display(regional.groupby(['satellite','stream','year'])[['pilot','southern_spain_rectangle','morocco_context_rectangle']].sum())")
md('''## 4. Calendar, year overlap and missing observation support

Adjacent annual downloads can overlap on January 1. The regional table is exactly deduplicated before grouping by the actual UTC year. Zero exported rows does not distinguish no fire from clouds, absent passes, or download gaps. Gray calendar cells indicate months without exported global rows for that platform. Incomplete dates marks years with fewer than 365/366 distinct dates in the global export, including boundary-only years and internal gaps.''')
code("display(pd.read_csv(TABLES/'pilot_platform_year.csv'))\ndisplay(Image(filename=str(ROOT/'reports/figures/01_pilot_calendar.png')))\ndisplay(pd.read_csv(TABLES/'export_date_gaps.csv'))")
code('''# Change the platform/year to inspect a detection-only calendar.
PLATFORM = 'SNPP'
YEAR = 2025
selected = pilot[(pilot.satellite == PLATFORM) & (pilot.year == YEAR)]
counts = selected.groupby('acq_date').size()
print('Days with detections:', len(counts))
print('Observation eligibility for days without rows: UNKNOWN')
display(counts.sort_values(ascending=False).head(12).to_frame('detection_rows'))
''')
md('''## 5. Native confidence and thermal signal

Exploratory retained classes: MODIS confidence ≥30; VIIRS nominal/high (`n`,`h`). These are sensor-specific quality categories, not common probabilities. Compare results with and without this selection. FRP is power in MW. VIIRS thermal saturation and MODIS/VIIRS band differences affect interpretation.''')
code("display(Image(filename=str(ROOT/'reports/figures/06_confidence.png')))\ndisplay(Image(filename=str(ROOT/'reports/figures/05_frp_ecdf.png')))\ndisplay(Image(filename=str(ROOT/'reports/figures/07_geometry_thermal.png')))")
code("display(pilot.groupby(['satellite','stream','year']).agg(all_rows=('retained','size'),retained_rows=('retained','sum')))\ndisplay(pd.read_csv(TABLES/'pilot_type.csv'))\ndisplay(pd.read_csv(TABLES/'pilot_frp_extremes.csv').head(12))")
md('''## 6. Geometry, local time and correlation

Approximate solar time = UTC + longitude/15. Use Africa/Casablanca only for civil-time presentation. Footprint dimensions vary with viewing geometry. These distributions are conditioned on a detection; they cannot describe all usable passes.''')
code("display(Image(filename=str(ROOT/'reports/figures/04_detection_times.png')))\ncorr = pd.read_csv(TABLES/'pilot_correlations.csv')\ndisplay(corr[corr.satellite=='SNPP'].pivot(index='x',columns='y',values='spearman_r'))")
md('''Spearman correlations are within-platform descriptive associations. They are computed as Pearson correlation of average ranks. Detector thresholds and saturation influence these relationships; do not infer causal drivers or harmonization coefficients from them.''')
md('''## 7. Recurrent locations and grid sensitivity

Repeated detections in a 5 km cell warrant review but do not prove a static source. Different episodes can occur in the same cell. A positive cell-day is a deduplicated spatial/time bin; it is not an incident or an observed-fire probability.''')
code("display(Image(filename=str(ROOT/'reports/figures/09_recurrence.png')))\ndisplay(pd.read_csv(TABLES/'grid_sensitivity.csv'))")
md('''## 8. Positive-only matching diagnostic

The diagnostic pairs both-positive acquisition timestamp groups in the same equal-area grid cell, separately for each source/reference series. It uses actual time gaps with no reuse and restricts candidates to the supplied Aqua year (2025). This is **not** the blueprint's matched-opportunity table: fire masks, full geolocation, usable-area intersection and valid negatives are absent.''')
code("display(pd.read_csv(TABLES/'positive_timestamp_pair_diagnostics.csv'))\ndisplay(Image(filename=str(ROOT/'reports/figures/08_pairing_feasibility.png')))")
md('''## 9. Added dataset: EFFIS national context

The downloaded workbook contains reported country-level annual burned area and forest-fire counts. Blanks stay missing. These measurements differ from FIRMS hotspot rows and cover entire countries, whereas the pilot covers a small rectangle. They provide historical context, not pixel-level validation labels. Source: [EFFIS data and services](https://forest-fire.emergency.copernicus.eu/applications/data-and-services).''')
code("effis = pd.read_csv(TABLES/'effis_morocco_spain.csv')\ndisplay(effis[effis.year >= 2020])\ndisplay(Image(filename=str(ROOT/'reports/figures/10_effis_context.png')))")
md('''## 10. Additional science files and access status

A one-week granule catalog is saved for July 14–20, 2025. A bounded smoke-test plan selects one near-time daytime Aqua/S-NPP quartet and two context tiles. Discovery and download are distinct statuses. No credentials appear in the notebook.''')
code("manifest = json.loads((TABLES/'science_download_manifest.json').read_text())\ndisplay(pd.DataFrame(manifest)[['product','filename','size_MB_catalog','status']])\ndisplay(pd.DataFrame(json.loads((TABLES/'download_manifest.json').read_text()))[['name','kind','status','bytes']])")
code("science_profile = TABLES/'science_profiles.json'\nif science_profile.exists():\n    display(pd.DataFrame(json.loads(science_profile.read_text())))\nelse:\n    print('Science-file decoding awaits authenticated downloads; local point EDA is complete.')")
md('''## 11. What to do next

1. Acquire paired fire masks and compatible geolocation across contiguous periods including non-detection days.
2. Verify QA codes, shapes, fill values, scale factors, spatial footprints and companion acquisition keys.
3. Compute shared usable land support on a reviewed grid/AOI before creating negatives.
4. Acquire the missing historical years and freeze time/geography splits before model selection.
5. Compare simple aggregation and logistic calibration before more complex models.

The current EDA supports source-specific descriptive analysis. The comparable activity metric and coverage denominator remain unavailable until observation eligibility is established.''')
nb['cells']=cells
nb.metadata={'kernelspec':{'display_name':'Python (firebridge_env)','language':'python','name':'python3'},'language_info':{'name':'python','version':'3.12'}}
path=ROOT/'notebooks/FIREBRIDGE_EDA.ipynb'
nbf.write(nb,path)
NotebookClient(nb,timeout=180,kernel_name='python3',resources={'metadata':{'path':str(ROOT)}}).execute()
nbf.write(nb,path)
assert not any(o.get('output_type')=='error' for c in nb.cells if c.cell_type=='code' for o in c.get('outputs',[]))
print('Executed notebook:',path,'cells:',len(nb.cells))
