# External source interfaces and operating assumptions

**Documentation checked October 24, 2026.** Authenticated data endpoints were not called and account-specific inventory/quotas were not verified. Endpoint templates below contain placeholders, not credentials. Scheduling values in the pipeline document are our proposed defaults, not provider promises.

| Source | Historical acquisition | Recent/revision acquisition | Required interpretation |
|---|---|---|---|
| MODIS Terra + Aqua hotspots | Existing MCD14ML monthly files; FIRMS standard archive/API when available | One `MODIS_NRT` transport, split by the row's satellite field | Keep platform, collection and processing level; the API response can include both satellites |
| VIIRS S-NPP | Standard archive / `VIIRS_SNPP_SP` within discovered availability | `VIIRS_SNPP_NRT` while service is available | Preserve historical overlap; handle retirement explicitly |
| VIIRS NOAA-20 | Standard archive / `VIIRS_NOAA20_SP` | `VIIRS_NOAA20_NRT` | Separate product adapter and model support |
| VIIRS NOAA-21 | Standard archive / `VIIRS_NOAA21_SP` is now listed in official API docs | `VIIRS_NOAA21_NRT` | Actual date/collection availability must be queried; earlier local downloads were NRT |
| Landsat FIRMS hotspots | Existing archives where geographically supported | `LANDSAT_NRT`, documented by the area API as US/Canada only | Do not promise coverage for Morocco; imagery is a different acquisition/product path |
| Fire masks and geolocation | CMR discovery plus resolved authenticated download links | Re-discover new/revised granules by exact collection; NRT only if compatible products/decoders are verified | Point-feed availability does not establish mask or geolocation availability |
| Historical weather | Open-Meteo archive with `models=era5`, or CDS gridded files | Periodic revision/late-data fetch | Reanalysis has delay; it is not a live weather station |
| Recent weather | Pinned model/run where available | Single Runs API, or explicitly model-derived current values | Preserve actual issue time; fetch time is not a substitute |
| Dated reports | Reviewed official/local archives and date-aware search | Publisher feeds/permitted search adapters, optional GDELT discovery | Search results are not a complete incident inventory |

**FIRMS interfaces**

```text
GET https://firms.modaps.eosdis.nasa.gov/api/data_availability/csv/{MAP_KEY}/ALL
GET https://firms.modaps.eosdis.nasa.gov/api/area/csv/{MAP_KEY}/{SOURCE}/{west,south,east,north}/{DAY_RANGE}/{DATE}
GET https://firms.modaps.eosdis.nasa.gov/mapserver/mapkey_status/?MAP_KEY={MAP_KEY}
```

The area documentation currently permits 1–5 days per request. With a date, it returns that date through `DATE + DAY_RANGE - 1`; without a date it returns the most recent days. Its listed quota is 5,000 transactions per 10-minute interval and large queries can consume multiple transactions. Use explicit dates for repeatable chunks. Availability is an interval/catalog hint, not local clear-sky coverage. The country endpoints are currently marked unavailable; use bounding boxes and local polygon clipping. [Area contract](https://firms.modaps.eosdis.nasa.gov/api/area/) · [Availability](https://firms.modaps.eosdis.nasa.gov/api/data_availability/) · [API index](https://firms.modaps.eosdis.nasa.gov/api/)

The archive page currently describes approximately a five-month standard-replacement lag. Treat it as planning guidance: replacement runs must inspect actual product availability, including older unresolved intervals. [FIRMS archive](https://firms.modaps.eosdis.nasa.gov/download/)

The missing-data page reports platform/day gaps, and currently returned a table-load failure during this review. It does not establish per-pixel cloud/validity. Store check failures as unknown, not zero gaps. [Missing-data documentation](https://firms.modaps.eosdis.nasa.gov/api/missing_data/)

NASA's Earthdata Forum notice says S-NPP science delivery is scheduled to cease November 1, 2026 at 13:00 UTC, subject to change. Record the notice and recheck actual service status; do not silently remap S-NPP identifiers to NOAA-20/21. NOAA-20/21 are separate continuations requiring their own validation. [NASA notice](https://forum.earthdata.nasa.gov/viewtopic.php?t=8108)

FIRMS MAP_KEY, Earthdata credentials and any CDS credentials are distinct. A FIRMS key does not authorize all NASA science-file downloads. Redact MAP_KEY path segments as well as query parameters in application/proxy logs.

**CMR science inventory**

```text
GET https://cmr.earthdata.nasa.gov/search/collections.json?short_name={PRODUCT}&version={COLLECTION}
GET https://cmr.earthdata.nasa.gov/search/granules.json?collection_concept_id={PINNED_ID}&temporal={START},{END}&bounding_box={BBOX}&page_size={SIZE}
```

Resolve the exact collection/provider once and pin it. Follow `CMR-Search-After` pagination with the same parameters and retain every catalog response; `updated_since` supports revision discovery. Search-after results reflect changing provider state, so use bounded windows, overlapping revision checks and reconciliation, not an assumption of snapshot isolation. Locally enforce half-open acquisition bounds. Follow validated download links from metadata; do not manufacture file URLs. [CMR API documentation](https://cmr.earthdata.nasa.gov/search/site/docs/search/api.html)

The product family initially includes MYD14/MYD03 (Aqua), VNP14IMG/VNP03IMG (S-NPP), then MOD14/MOD03 and VJ114IMG/VJ103IMG. Resolve NOAA-21 science companions from the actual chosen catalog/version. Verify collection compatibility rather than using whichever geolocation landing page is newest. The existing sample inventory is not evidence of complete coverage or successful downloads.

**Weather interfaces**

```text
GET https://archive-api.open-meteo.com/v1/archive?latitude={LAT}&longitude={LON}&start_date={YYYY-MM-DD}&end_date={YYYY-MM-DD}&hourly=temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m,wind_direction_10m&models=era5&timezone=GMT&timeformat=unixtime&wind_speed_unit=ms
```

Historical API end dates are inclusive; convert the internal exclusive end carefully. Preserve returned coordinates, units and model. ERA5/ERA5-Land are documented as updating daily with about five days' delay in this API. Query actual availability rather than filling recent missing reanalysis with invented values. [Historical weather](https://open-meteo.com/en/docs/historical-weather-api)

For recent weather, the Single Runs API supports selecting a model initialization through `run`. Record that issue time, each valid time and retrieval time. Discover the supported model endpoint/identifier and run availability before enabling its adapter. The ordinary forecast API can stitch runs; its `current` output is model-derived, and is therefore stored as `model_current` if used. `generationtime_ms` is computation duration, not a forecast initialization timestamp. [Single Runs API](https://open-meteo.com/en/docs/single-runs-api) · [Forecast/current semantics](https://open-meteo.com/en/docs) · [Model availability](https://open-meteo.com/en/docs/model-updates)

**Reports and news**

Prefer original official incident reports and reviewed local reporting for the demonstration. Store event dates separately from publication dates, including uncertainty. RSS/search polling can have partial coverage, delayed indexing and truncation. GDELT's DOC introduction describes a recent rolling window and is dated 2017; verify current limits rather than assuming it can retrieve the full 2024 archive. Historical backfill needs an appropriate archival route and reviewed original links. [GDELT DOC](https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/) · [GDELT data access](https://www.gdeltproject.org/data.html)
