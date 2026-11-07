# Database handoff to the Node.js backend team

**You own the HTTP API.** This repo provides data ingestion and PostgreSQL/PostGIS. There is no FastAPI dependency, route implementation or Python web server. The earlier [API contract proposal](../architecture/API.md) remains useful product input; adapt it to your Node.js framework. User authentication, authorization, endpoint validation, request limits, analysis caching, map tiles, exports and the AI explainer are backend responsibilities.

## Connection and permissions

Local development: host `127.0.0.1`, port `55432`, database `firebridge`, user `firebridge_reader`, password from the private `FIREBRIDGE_READER_PASSWORD`. For another container on the same Compose network, use host `db`, port `5432`. Do not use the ingestion owner's credentials in the API.

`firebridge_reader` can select only the curated `serving` views. It cannot insert or update ingestion tables or read their request configuration. The role has no access to filesystem object bytes through SQL. If the backend later writes analyses/users/jobs, create a separate narrowly scoped application role and migrations; do not grant it the data owner's privileges.

The views are the integration contract:

| View | Key / useful fields | Meaning |
|---|---|---|
| `serving.sources` | `id`, `platform`, `instrument`, `collection`, `processing_stream` | Exact source definitions; catalog presence does not mean locally loaded |
| `serving.scopes` | `scope_key`, `area_id`, `geometry` | Immutable ingestion rectangles |
| `serving.latest_releases` | `(alias,scope_key)`, `release_id`, `generation` | Mutable pointers; resolve once per saved analysis |
| `serving.releases` | `id`, `dataset_kind`, `stream`, `published_at` | Immutable published release metadata |
| `serving.partitions` | `release_id`, `partition_id`, `support_spec`, `row_count` | Complete source/day membership, including zero rows and open periods |
| `serving.detections` | `release_id`, `id`, `acquired_at`, `source_id`, `geom` | Selected native points only; all coordinates are EPSG:4326 |
| `serving.weather` | `release_id`, `id`, `location_id`, variable/time/unit/value fields | Selected weather values, explicit sample-point support |
| `serving.reports` | `release_id`, `id`, `canonical_url`, publication and review fields | Selected document revisions |
| `serving.reported_events` | `report_id`, event interval, location/precision | Claims; join through the selected reports release |
| `serving.asset_provenance` | `id`, source, SHA-256, original URL, metadata | Input lineage; no provider key |
| `serving.ingestion_health` | subscription, last success/attempt, open gaps | Transport health, not clear-sky observation coverage |
| `serving.source_availability` | feed/source/check time, available bounds | Catalog history; choose the most recent check |
| `serving.release_changes` | previous/new release, interval, reason | Late data, corrections and standard replacements |
| `serving.release_events` | `id`, `created_at`, payload | Durable publication notifications |
| `serving.science_inventory` | collection, granule, revision, status | Catalogued science assets; not decoded masks |

Native detection IDs are PostgreSQL `bigint`; the Node `pg` driver normally returns them as strings. Keep IDs as strings. Counts may also arrive as strings; convert only after checking range. Do not override all `int8` decoding to JavaScript `Number` globally.

Treat source IDs as opaque keys. In particular, the Landsat IDs' historical internal `c1` adapter tag is not a NASA collection assertion: the catalog's `collection` is `not-provided`, reflecting the supplied FIRMS files. Use catalog columns, not string parsing, for product labels.

## Resolve one immutable snapshot

For the new dbt summaries, resolve `serving.latest_analytics` once and use its **`build_id`** in `serving.daily_detections`, `serving.query_coverage`, `serving.daily_weather`, `serving.daily_reports` and `serving.area_daily_context`. The `input_releases` field pins the exact source releases used. These summaries cover the registered scope; arbitrary smaller polygons still require spatial queries against the pinned native release. See [ANALYTICS.md](ANALYTICS.md) for grains, columns, missingness and example SQL. The following native-release queries remain valid.

```sql
SELECT release_id, generation, published_at, observation_cutoff
FROM serving.latest_releases
WHERE scope_key = $1 AND alias = $2;
-- Example values: 'morocco-pilot', 'best_available'
```

Save `release_id` in the analysis configuration, along with AOI, UTC interval, sources and filters. Resolve weather/report aliases separately and save those IDs too. Missing component aliases are **missing**, not zero-valued components. Use a repeatable-read transaction when initially resolving several aliases so a concurrent publish cannot change one halfway through that resolution.

## A bounded map page

```sql
SELECT id::text, source_id, acquired_at, longitude, latitude,
       confidence_raw, confidence_scheme, type_raw, day_night,
       frp_mw, processing_level, brightness_bands
FROM serving.detections
WHERE release_id = $1
  AND acquired_at >= $2::timestamptz AND acquired_at < $3::timestamptz
  AND source_id = ANY($4::text[])
  AND ST_Covers(ST_MakeEnvelope($5,$6,$7,$8,4326),geom)
  AND ($9::timestamptz IS NULL OR (acquired_at,id) > ($9::timestamptz,$10::bigint))
ORDER BY acquired_at,id
LIMIT $11;
```

Parameters 5–8 are west/south/east/north. Validate the AOI is covered by the release's registered scope and reject/split antimeridian geometry deliberately. Clamp the page size (suggested maximum 5,000). The API should sign cursors and bind them to the release, bounds and source/filter hash. Parameterize all values; never concatenate SQL from the agent or browser.

The global MODIS release covers the full world and the imported historical interval. The pilot release includes the loaded VIIRS sources too. Do not silently append pilot VIIRS records to a global MODIS analysis and label VIIRS coverage global.

## Counts and zero-versus-missing days

```sql
SELECT source_id, (acquired_at AT TIME ZONE 'UTC')::date AS day,
       count(*) AS detection_count
FROM serving.detections
WHERE release_id=$1 AND acquired_at >= $2 AND acquired_at < $3
  AND ST_Covers(ST_MakeEnvelope($4,$5,$6,$7,4326),geom)
GROUP BY source_id,day ORDER BY day,source_id;
```

This returns only days with detections. To render a dense calendar, start from `serving.partitions` for the selected source/day range and LEFT JOIN these counts. A complete selected partition may return zero; a missing partition is null/unknown. The sample [queries.sql](queries.sql) includes a dense whole-scope calendar. Check `support_spec.period_state`: today's partial time interval remains open even when the request itself completed successfully. `query_complete=true` is not observational coverage.

Label the measure “satellite detections.” Do not label native counts incident counts, hectares, frequency-adjusted activity or comparable probabilities. Confidence schemes differ between MODIS, VIIRS and Landsat. `frp_mw` is power at an observation; summing it over all overpasses is not burned energy or fire area.

## Weather and dated evidence

Filter `serving.weather` by its pinned release and `location_id`; retain units, valid intervals, `data_kind`, null values and support metadata. The current adapter supplies point samples, so do not label them whole-area averages. Precipitation is an interval sum; temperature/humidity/wind are instant values. Wind directions require circular/vector handling for aggregation.

Join events through the selected reports release:

```sql
SELECT r.id,r.title,r.canonical_url,r.published_at,r.review_status,r.source_lineage,
       e.event_start,e.event_end_exclusive,e.location_precision,e.claim_summary
FROM serving.reports r
LEFT JOIN serving.reported_events e ON e.report_id=r.id
WHERE r.release_id=$1;
```

A candidate association still needs geographic/event-date matching and review. RSS publication dates do not identify ignition dates, and syndicated or satellite-derived articles are not independent confirmations. The AI agent should explain a bounded evidence snapshot prepared by backend code, cite source IDs/URLs, and state missing inputs. Do not let the agent issue unrestricted SQL or turn missing data into factual conclusions.

## Discover new releases

Poll `serving.latest_releases` for changed generation/release ID. For a notification worker, `LISTEN firebridge_release` provides a wakeup hint. Recover missed notifications from `serving.release_events` using a durable cursor `(created_at,id)`. Event delivery is at-least-once from the consumer's perspective; deduplicate by event ID. These events announce available data and do not update an already saved analysis automatically.

## What is not ready to consume

Scientific observation coverage, usable negative labels, harmonized response, trained models and burned-area estimates are not populated. Weather/news live access remains unverified in the local-only run. Reserved `firebridge.analyses`, `calendar_periods`, `api_jobs` and AI tables are schema provisions, not completed application features. The backend should expose unsupported/missing states until the relevant data product exists.
