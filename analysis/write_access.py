from pathlib import Path
import json
import pandas as pd
ROOT=Path(__file__).resolve().parents[1];T=ROOT/'reports/tables'
rows=json.loads((T/'science_granule_inventory.json').read_text())
plan=json.loads((T/'science_download_manifest.json').read_text())
summary=pd.DataFrame(rows).groupby('product').agg(candidate_granules=('filename','size'),catalog_MB=('size_MB_catalog','sum')).reset_index()
summary.to_csv(T/'science_inventory_summary.csv',index=False)
selected=pd.DataFrame(plan)[['product','filename','size_MB_catalog','status']]
text=f'''# Additional datasets: actual access status

The supplied FIRMS archives were analyzed locally. Additional source discovery used NASA's public CMR catalog for the pilot rectangle (−6.4,34.5,−4.5,35.9), with **14–20 July 2025** as a continuous swath smoke-test window. Land cover uses annual 2024; burned area uses July 2025. No discovery result is counted as a downloaded science observation.

## What was downloaded

- **EFFIS country totals workbook, report 2024**: real annual national burned-area (ha) and reported forest-fire counts, 1980–2024 columns/rows with country-specific missingness. Morocco and Spain extracts and a historical chart are available. Morocco's earlier blank years remain null. The source worksheet's area title contains a typo (`1980 - 204`); actual year cells extend through 2024. No source workbook is edited.
- **NASA MODIS C6/C6.1 and VIIRS Collection 2 user guides**, FIRMS attribute definitions/README, Landsat field definitions, and provider access documentation.
- **CMR collection and granule metadata** for required/supporting products, with actual collection identifiers, acquisition ranges, candidate file links and provider size estimates.

[EFFIS source workbook](https://forest-fire.emergency.copernicus.eu/effis/applications/data-and-services/report_2024.xlsx) · [EFFIS data license](https://forest-fire.emergency.copernicus.eu/about-effis/data-license)

## NASA science-file inventory

{summary.to_markdown(index=False,floatfmt='.1f')}

These are catalog candidates intersecting the bounding box. CMR geometry does not establish clear-sky pixel coverage. Size estimates are provider metadata, not measured downloaded bytes. The complete candidate catalog is approximately **{summary.catalog_MB.sum()/1024:.2f} GiB** if provider MB units are MiB. Geolocation dominates storage. We select a roughly **{selected.size_MB_catalog.sum():.1f} MB** initial sample rather than download the whole week.

## Bounded sample and download status

{selected.to_markdown(index=False,floatfmt='.1f')}

The source/reference quartet is chosen by smallest granule start-time difference within 60 minutes among daytime-UTC candidates in the predeclared week, independent of whether it contains detections. This is for schema/access exploration; it is not a valid matched-opportunity label. The same acquisition key must identify each geolocation companion. Later pixel geolocation must verify actual AOI overlap.

Required fire/geolocation collections currently resolve to MYD14 061 / MYD03 61 and VNP14IMG 002 / VNP03IMG 2. NOAA-20 resolves to VJ114IMG 002 / VJ103IMG 2.1; the latter is a different geolocation revision and must be checked against product guidance before training. Terra full-mask analysis also needs MOD03, which is not present and is not included in this first Aqua/S-NPP sample.

## Access issues verified this run

- Direct LP DAAC land-cover and burned-area file requests returned **HTTP 401 Unauthorized** without credentials.
- No EARTHDATA_TOKEN/LAADS_TOKEN/FIRMS_MAP_KEY/CDS credentials or .netrc were initially configured. A local `.env` token can enable the bounded downloader; the status table above records the latest attempted run.
- ORNL's public MODIS REST service returned **HTTP 500** for the product list and attempted MCD12Q1/MCD64A1 date/band endpoints. No ORNL subset was successfully acquired. This does not mean the products have no data.
- This session's browser automation found no available Chrome or in-app browser, so it could not open Earthdata sign-in automatically.
- ERA5-Land is optional and has not been downloaded: CDS login/API setup and dataset terms are required. Its absence does not block point-data EDA or the first sensor-comparison design.
- Historical EFFIS perimeters/incident-level local reports are not downloaded. National statistics are available; requesting unavailable historical extracts is a separate provider interaction. No request was submitted on your behalf.
- Earlier standard FIRMS detections (especially Aqua/MODIS 2020–2024 and S-NPP 2020–2023) remain missing. Use a regional FIRMS archive request after login. The present token downloader targets science files, not a FIRMS MAP_KEY-protected Area API.

## Enable NASA downloads

1. Sign in at [Earthdata Login](https://urs.earthdata.nasa.gov/).
2. Choose Generate Token, then Show Token, following [NASA's current instructions](https://urs.earthdata.nasa.gov/documentation/for_users/user_token).
3. Store the token locally in the project's ignored `.env` file:

```dotenv
EARTHDATA_TOKEN=your_token_here
```

4. Run `firebridge_env/bin/python analysis/download_science.py`. It never prints the token and writes checksums/statuses to `science_download_manifest.json`.
5. Inspect actual science contents before claiming the masks are usable. Download completion does not imply verified companion alignment, QA decoding or computed coverage.

Do not commit or paste the token into notebooks. [CDS setup](https://cds.climate.copernicus.eu/how-to-api) is separate from Earthdata access.

## Dataset priorities after this EDA

1. Full masks and geolocation for continuous Aqua/S-NPP overlap (including negatives).
2. Earlier standard points and additional complete seasons to support independent splits.
3. Annual land cover and monthly burned area for the complete reviewed AOI.
4. Independent event reports/perimeters, with lineage and uncertainty checked.
5. NOAA-20 adapter, then optional ERA5-Land context.
'''
(ROOT/'reports/DATA_ACCESS.md').write_text(text)
print(summary.to_string(index=False))
