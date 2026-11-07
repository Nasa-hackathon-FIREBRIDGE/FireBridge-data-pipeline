# Database-backed API contracts

> **Implementation update (October 26, 2026):** the data pipelines and database are now implemented in `src/firebridge`. The backend team will build the HTTP endpoints in **Node.js**. See [the current data guide](../data/README.md), [operations](../data/OPERATIONS.md) and [Node.js database handoff](../data/NODE_HANDOFF.md). The text below preserves the earlier design proposal; statements about FastAPI/Celery or an uninitialized database are superseded by that implementation guide.

**Proposed API v1, October 24, 2026. These routes are not implemented yet.** This file specifies each endpoint's input, database work, response and exceptional states. The companion [endpoint catalog](endpoint_catalog.json) is machine-readable and checked against the SQL table names.

**Common rules**

- Base path: `/api/v1`. All timestamps are ISO 8601 UTC; dates use the analysis's explicit time basis. Intervals are `[start, end_exclusive)`. The UI converts its inclusive end date before submitting.
- Geography is GeoJSON longitude/latitude WGS84. Validate rings, self-intersections, bounds, vertex count and land area; normalize/deduplicate geometry. Split antimeridian shapes deliberately. Initial proposal: 5,000 vertices, 250,000 km² per interactive scientific AOI, 2,000 cell-days for detailed evidence and 5,000 points/page. These are configurable workload limits; larger supported requests use queued work or coarser tiles. Reject out-of-domain scientific grids.
- An analysis pins a satellite release and separate context releases. `latest_*` is resolved once at creation; child routes never re-resolve it independently. `data_mode` is `standard_only`, `best_available` or `nrt_only`. Source filters and confidence/QA policies are frozen in `request_spec`.
- A common response includes `request_id`, `schema_version`, `data` and `warnings`. Analysis responses also include `analysis_id`, release IDs, metric ID/unit, time basis, grid/selection/model versions, status and provenance links. Source freshness and local observation coverage are separate fields.
- Comparable metrics accept only source sets and time bases compatible with their published daily-selection policy. Filtering the displayed native dots does not change that harmonized policy. A different scientific source priority requires a separately computed/versioned policy, not merely filtering a prepared probability series.
- Missing numbers are `null`, not zero. Empty rows, unsupported science, missing components, partial inventories, active current-day windows and transport failures have distinct reason codes. Each response states its scope; no invented incident count or burned area.
- `400`: malformed syntax; `401/403`: access; `404`: unknown/inaccessible resource; `409`: idempotency conflict or requested dependency not ready; `410`: expired export; `422`: invalid geometry/window/metric/filter; `429`: app quota; `503`: no usable service snapshot. A valid request for an unavailable scientific result can return `200` with `status=unsupported` and null values.
- POST requests accept `Idempotency-Key`. Store `(requested_by,key,request_hash)` before queuing. Reuse the existing result for the same request; return `409` for a different body under the same key. Async POST returns `202` with `job_id`, status URL and resource ID when allocated. Cached completed work returns `200`; new saved areas return `201`.
- Use a repeatable-read transaction to resolve initial release aliases/components. Read published immutable rows with parameterized SQL. Public routes cannot trigger unlimited source downloads, model training or arbitrary SQL.
- Cursors are opaque/signed and bind release, filter hash, ordering and authorization scope. Native detection order is `(acquired_at,id)`; a cursor from another analysis is rejected. ETags bind full immutable configuration. Expensive export preparation uses POST; GET serves a prepared result only.
- Initial app freshness polling: the UI can check `/updates` every minute while open. This reads the database and does not contact NASA on each browser poll. Server schedules are defined separately in [PIPELINES.md](PIPELINES.md).

**1. `GET /catalog` — what can be selected**

Input: optional `scope_key`; no geographic search triggers external acquisition.

Reads: `sources`, `metric_definitions`, `ingestion_feeds`, `feed_sources`, `source_availability`, `release_aliases`, `data_releases`, `grids`.

Work: resolve the registered scope; list verified product streams and published releases; join metric definitions and validated geographic support. Distinguish provider availability from what FIREBRIDGE has actually ingested.

Returns: `sources[] {source_id, platform, product, collection, processing_stream, provider_available_interval, ingested_interval, availability_status}`, `metrics[] {id, unit, requires_masks, requires_model, supported_extent}`, `release_aliases[]`, `limits`, `verified_at`. Missing dates remain null; never claim NOAA-21 standard data is locally loaded merely because the endpoint exists.

**2. `GET /sources/{source_id}/availability` — freshness and gaps**

Input: `source_id`, required `scope_key`, optional `[start,end_exclusive)` UTC filter. Reject a source outside that scope.

Reads: `source_availability`, `feed_sources`, `ingestion_subscriptions`, `fetch_runs`, `ingestion_checkpoints`, `ingestion_gaps`, `release_aliases`, `data_releases`.

Work: combine latest provider check with last attempted/successful fetch and committed stage boundaries for the correct scope. Include source-specific gaps and any retirement notice.

Returns: `provider_status`, `last_attempt_at`, `last_success_at`, `queried_through`, `latest_observation_at`, `published_at`, `next_check_at`, `stale`, `stale_reason`, `gaps[] {start,end_exclusive,kind,status}`. If the combined MODIS transport is healthy but only Terra records occur in a response, do not manufacture an Aqua acquisition timestamp. Global status cannot prove local coverage.

**3. `GET /releases/{release_id}` — exact data version**

Input: published release UUID.

Reads: `data_releases`, `release_partitions`, `data_partitions`, `release_assets`, `sources`, `release_changes`.

Returns: `id`, `dataset_kind`, `stream`, `scope_key`, `parent_release_id`, `published_at`, `observation_cutoff`, `code_version`, configuration digest, manifest digest/authorized link, partition counts, source composition, validation status and change summary. Paginate detailed membership rather than returning millions of IDs. Internal storage paths and credentials are never public URLs.

**4. `GET /updates` — tell the UI a newer snapshot exists**

Input: `scope_key`, optional `after_release_id`, and component/alias filters.

Reads: `release_aliases`, `data_releases`, `release_changes`.

Returns: `current[] {alias,release_id,published_at}`, `has_updates`, `changes[] {reason,affected_interval,summary}`, `checked_at`. `has_updates` compares UUIDs/generations, not row counts. The old analysis remains unchanged. This endpoint never downloads provider data.

**5. `POST /areas` — save a valid area**

Body: `{name, geometry: GeoJSON Polygon|MultiPolygon, display_timezone}`. Client cannot supply an unchecked area weight or claimed square kilometres.

Reads: `areas`; writes `areas` after normalization/validation. AOI weights are built lazily in the analysis job using the selected grid/land mask and stored in `area_cells`.

Returns `201` or reused `200`: `{area_id, name, geometry, bbox, geometry_sha256, version, display_timezone, geometric_area_km2}`. The geometric area is not the land denominator used by scientific aggregation. Reject invalid geometry with field-level `422`; do not silently repair a self-intersection into a different intended AOI.

**6. `GET /areas/{area_id}` — saved geographic selection**

Input: area UUID; optional supported `grid_id` to expose existing weight metadata.

Reads: `areas`, `area_cells`, `grids`, `grid_cells`.

Returns: normalized geometry/version/provenance, geometric area, and available grid summaries `{grid_id, weighting_version, intersecting_cells, overlap_land_area_m2}`. If weights have not been computed, return `weights_status=not_prepared`, not zero land area.

**7. `POST /analyses` — freeze the user's selection**

Required body: `area_id`, `start_date`, `end_date_exclusive`, `time_basis`, `metric_key`, `source_ids[]`, `data_mode`. Optional: explicit `satellite_release_id`, `grid_id`, `baseline_spec`, `weather {enabled, historical_model, recent_policy}`, `reports {enabled, review_policy}`, `language` for later UI use. A comparable metric requires an approved grid/selection/QA policy; raw native counts can use `grid_id=null`.

Reads: `areas`, `metric_definitions`, `sources`, `grids`, `release_aliases`, `data_releases`, `release_partitions`, `data_partitions`. Writes: `analyses`, `analysis_components`, `api_jobs`, `outbox_events`; worker later writes weights and prepared results.

Work: validate scope/dates/source/metric combinations; resolve exact satellite and context releases in one transaction; canonicalize selection; calculate the cache key including all release UUIDs and policies; atomically create analysis/job/outbox if not already cached. No masks available means comparable output is unsupported; it does not silently become a native-count metric.

Returns: `{analysis_id, job_id, status, resolved_releases, selected_window, metric, component_statuses, links}` with `202`, or `200` for an existing ready analysis. An interval with no local inventory creates a meaningful missing/unsupported result or an authorized bounded lake job, not an uncontrolled upstream backfill. External backfill is an admin operation.

Example request (design illustration, not an existing area/release):

```json
{
  "area_id": "11111111-1111-4111-8111-111111111111",
  "start_date": "2024-01-17",
  "end_date_exclusive": "2025-01-18",
  "time_basis": "UTC",
  "metric_key": "native_detections_v1",
  "source_ids": ["modis_terra_c61_standard", "modis_aqua_c61_standard"],
  "data_mode": "standard_only",
  "grid_id": null,
  "weather": {"enabled": true, "historical_model": "era5", "recent_policy": "separate"},
  "reports": {"enabled": true, "review_policy": "reviewed_with_candidates_separate"}
}
```

**8. `GET /analyses/{id}` — selected analysis and readiness**

Reads: `analyses`, `analysis_components`, `api_jobs`, pinned `data_releases`, latest aliases only to indicate availability of newer releases.

Returns: `status`, normalized request, pinned release IDs, component states, stage/progress, `newer_release_available`, warnings, links to child routes. It may be `partial` if satellite data is ready but weather/reports are missing. Do not present missing reports as zero incidents. A failed job includes a stable error code and retryability, not raw credentials/provider HTML.

**9. `GET /analyses/{id}/summary` — main dashboard facts**

Reads: `analyses`, `analysis_components`, `calendar_periods`, release-filtered `partition_detections`/`detections`, `weather_summaries`, `analysis_event_links`; or a checked prepared artifact when data is lake-backed.

Returns: `native_detections_by_source[]`, `comparable_response {value,unit,status}`, `coverage {fraction,denominator,status}`, `observed_vs_estimated_share`, `weather_status`, `report_counts_by_review_status`, `limitations`, `fact_ids`. Do not sum all platform counts into a claimed unique incident count. For raw-only analyses, comparable response/coverage are null with reasons. Every headline's exact scope is explicit.

**10. `GET /analyses/{id}/calendar` — timeline or calendar cells**

Input: `resolution=day|week|month`, optional narrowed interval inside the saved selection. Metric/filters cannot be changed here; create a new analysis to change them.

Reads: `calendar_periods` for comparable responses; for native counts, the prepared source-count artifact or release-selected detections grouped by declared day/source. `calendar_periods` is dimensionless and must not hold native counts.

Returns: `periods[] {start,end_exclusive,value,unit,status,open_period,coverage_fraction,eligible_land_m2_days,possible_land_m2_days,observed_weight_fraction,baseline_year_count,seasonal_percentile,reasons}`. Native-count mode returns `counts_by_source`, `inventory_status`, and null local coverage instead of a fabricated denominator. Include empty periods: `0` only for a verified complete point-query snapshot with no rows, `null` for unavailable inventory. A partial inventory may return an explicitly labelled observed lower-bound count.

**11. `GET /analyses/{id}/coverage` — what was observable**

Input: optional reporting period and cell filter, bounded to the analysis.

Reads: `area_cells`, `grid_cells`, `observations`, `daily_activity`, `calendar_periods`, source ingestion gaps via pinned release manifests.

Returns: observed/eligible/missing cell-days, usable/cloud/invalid/unobserved land summaries, coverage fraction/denominator, QA policy, `ingestion_status` and `observation_coverage_status` separately. Counts are computed on the declared selected opportunities; do not sum overlapping pass land areas as unique AOI land. Point-only releases return `observation_coverage_status=unknown`.

**12. `GET /analyses/{id}/detections` — native hotspot details**

Input: optional bbox/time narrowing, `limit` (default 500, maximum 5,000), cursor. Source/quality filters must be a subset of the saved request; bind them into the cursor.

Reads: `analyses` → `release_partitions` → `data_partitions` → `partition_detections` → `detections` → `sources`/`assets`; use exact AOI clipping. For incomplete serving slices, use queued prepared data, never silently the partial SQL subset.

Returns: `{features: GeoJSON Feature[], next_cursor, returned, truncated, count_scope}`. Each feature includes `detection_id`, source/platform, acquired UTC time, native confidence scheme/value, type if present, FRP MW, band-specific brightness, processing level and evidence link. Raw nulls remain null. Deduplicate canonical membership before pagination. `truncated=true` means another page exists, not a complete count.

**13. `GET /analyses/{id}/tiles/{layer}/{z}/{x}/{y}.mvt` — map at scale**

Input: allowlisted `layer=detections|activity|coverage`, valid tile coordinates, optional saved-selection period subset.

Reads: immutable prepared tile partitions/artifacts or bounded release-selected PostGIS query through `ST_AsMVT`; inputs come from detections or grid/daily/coverage tables. Never accept arbitrary table/SQL names.

Returns: `application/vnd.mapbox-vector-tile`, ETag, release headers and a documented style/property schema. Low zoom returns count bins/clusters in a named aggregated layer; high zoom returns bounded points/cells. An empty valid tile is different from an unavailable layer (`409` preparing or explicit unsupported metadata in the analysis). Do not truncate points invisibly; use aggregation. The UI reads status from the analysis/coverage route, not from absence of a tile feature.

**14. `GET /analyses/{id}/cells/{cell_id}` — evidence behind a cell**

Input: reporting date or bounded interval inside the analysis; cell must intersect that AOI.

Reads: `area_cells`, `grid_cells`, `observations`, `observation_assets`, `assets`, `daily_activity`, `predictions`, `model_versions`, optional `matched_pairs` for a published evaluation experiment.

Returns: cell geometry, AOI land weight, candidate passes with times/QA, selected pass and selection reason, raw retained counts, model value/version/support, exclusions and source links. Limit/paginate long pass histories. Raw record mappings are read from `detection_links_uri` through an authorized evidence service. A valid no-detection response is explicitly distinct from no observation.

**15. `GET /analyses/{id}/comparison` — compare compatible measurements**

Input: `view=native_counts|common_response|withheld_reference`, `resolution=week|month`.

Reads: selected detections for native view; `matched_pairs`, frozen evaluation artifacts, `evaluations`, `model_versions`, `daily_activity`, `calendar_periods` for scientific views.

Returns: `unit`, `support_definition`, `series[]`, sample/positive/independent-block counts, baseline and model metrics, `experiment_id`/manifest, limitations. Common-response comparisons use the same eligible support. Withheld-reference view is available only for a precomputed held-out experiment, not retrained on demand. If unsupported, return null series and a reason; do not overlay native counts and probabilities as the same quantity.

**16. `GET /analyses/{id}/weather` — historical and recent conditions**

Input: variables subset, `resolution=hour|day|period`, `context=historical|recent|both`.

Reads: `analysis_components` → selected weather release partition manifests → `weather_values`/`weather_locations`; prepared `weather_summaries` where available.

Returns: `series[] {variable,unit,source_model,data_kind,issued_at,valid_intervals,values,spatial_method,native_resolution,spatial_coverage,temporal_coverage,status}`, plus weights/input evidence IDs. Historical/recent series remain separate. Missing issue time is allowed only for explicitly model-current/other compatible kinds. Hourly area-wide responses use correct native-grid weighting or labelled point sampling; missing rainfall is null. A missing context is `200` with `status=missing`, not an invented weather report.

**17. `GET /analyses/{id}/reports` — supporting dated reports**

Input: `relation`, `review_status`, cursor and limit (default 20, maximum 100).

Reads: pinned reports membership → `news_reports`, `reported_events`, `analysis_event_links`.

Returns: original URL/title/publisher, publication date/precision, event interval, original place/geometry precision, claim summary, review/match status, source independence/syndication group and evidence IDs. Candidate reports are visibly distinct. Never return a province centroid as a precise fire point. Empty output means no matching reports in this collected snapshot, not no incident.

**18. `GET /analyses/{id}/provenance` — reproducibility and evidence**

Input: optional fact/cell/period filter and cursor.

Reads: `analysis_components`, `data_releases`, `release_partitions`, `data_partitions`, `release_assets`, `assets`, model/evaluation references and evidence snapshots.

Returns: method/grid/QA/selection versions, exact product streams, input hashes, retrieval times, public source citations, data/model versions, preparation status and authorized export links. Do not expose private storage paths, signed tokens, secret-bearing FIRMS URLs or unrestricted provider credentials.

**19. `POST /analyses/{id}/explanations` — explain the selection**

Body: `language=en|fr|ar` (enable only evaluated languages), optional bounded `question`. Uses the already selected area/dates; a question asking for another region cannot silently change scope.

Reads: prepared analysis outputs and context; writes `evidence_snapshots`, `ai_explanations`, `api_jobs`, `outbox_events`.

Returns: cached `200` or `202 {explanation_id,job_id,status,links}`. Worker freezes numeric facts, coverage and report versions, runs the read-only explainer, validates citations/values/units and uses a template fallback if necessary. No external provider download or arbitrary SQL is delegated to the language model. A partial evidence bundle remains partial in the explanation.

**20. `GET /explanations/{id}` — explanation and citations**

Reads: `ai_explanations`, `evidence_snapshots`, authorized parent analysis.

Returns: `status`, `language`, structured summary/findings/limitations/suggested checks, per-claim `evidence_ids`, source links, snapshot hash, model/prompt versions and `generated_at`. Only validated output or the explicit deterministic fallback is shown as a final answer. Rejected drafts are not exposed as authoritative results.

**21. `POST /analyses/{id}/exports` — prepare a reproducible download**

Body: `format=csv|geojson|parquet`, `content=summary|calendar|detections|weather|reports|evidence`, bounded options. Reject invalid combinations, e.g. weather table as an unsupported geometry-only format.

Reads: the same pinned analysis/release records used by screen routes. Writes `api_jobs`, `outbox_events`; worker writes artifact bytes/hash/manifest/expiry.

Returns: cached `200` or `202 {job_id,status_url}`. Export includes schema, units, source/release/method attribution and selected bounds. Large exports use workers and the lake; never build a multi-million-row CSV in the API process. The job retains row count and content hash.

**22. `GET /jobs/{id}` — durable job status**

Reads: `api_jobs`, optional linked analysis/explanation. Authorization checks `requested_by`/shared-resource policy.

Returns: `kind`, `status`, stage, completed/total units when known, attempt count, errors/retryability, related resource links and export expiry. Progress may be indeterminate; do not fabricate a percentage/ETA. A job remains durable if Redis restarts.

**23. `GET /jobs/{id}/download` — retrieve a prepared export**

Reads: completed authorized `api_jobs` and artifact metadata.

Returns: streamed bytes or short-lived signed redirect, Content-Type, Content-Disposition, byte length and checksum. `409` if not finished; `410` if expired; `404` for inaccessible resource. This GET does not start a new export. A regeneration POST uses the same scientific snapshot and a new delivery job if the old artifact expired.

Use a new Idempotency-Key for an intentional regeneration after expiry; retrying the old key still identifies the old job.

**24. `GET /admin/ingestion/subscriptions` — operational overview**

Input: admin authentication, optional scope/feed/mode/state filters; paginated.

Reads: `ingestion_subscriptions`, `ingestion_feeds`, `feed_sources`, `ingestion_checkpoints`, recent `fetch_runs`, gap counts.

Returns: configured cadence/overlap, enabled state, next due, stage boundaries, last outcomes, backlog/gaps and adapter version. Credentials are represented only by configured/not-configured status. Viewing this route does not change schedules.

**25. `POST /admin/ingestion/backfills` — request historical work**

Body: registered `feed_id`, `area_id`/scope, explicit UTC `[start,end_exclusive)`, products/collection and adapter options, resource budget. Admin authorization and idempotency required.

Reads: feeds/sources/availability/existing inventory. Writes: a bounded backfill subscription (or reuses matching config), `api_jobs`, `outbox_events`; planner creates fetch runs.

Returns `202`: `job_id`, planned chunks/scope, expected work if known, missing access requirements. Validate product limits and maximum work budget before accepting. Unknown byte volume is reported as unknown; do not promise a download size from no inventory.

**26. `POST /admin/ingestion/subscriptions/{id}/refresh` — retry/refresh configured scope**

Body: optional bounded window and reason; `mode=poll|repair|reconcile`. Cannot change the feed/collection implicitly.

Reads: subscription, checkpoints and gaps. Writes: `api_jobs`, `outbox_events`; the worker acquires its lease and creates fetch runs.

Returns cached `200` or queued `202`. Provider rate limits still apply. The API does not synchronously fetch NASA inside the request. One source's failure does not force a full worldwide reload.

**27. `GET /admin/ingestion/runs/{id}` — inspect a processing attempt**

Input: `fetch_runs.id` (this route is for a fetch attempt, not an arbitrary pipeline UUID).

Reads: `fetch_runs`, `fetch_assets`, `assets`, related `pipeline_runs`, `quality_issues`.

Returns: sanitized request/window/basis, timing/status, pages/record counts, input hashes, errors, related normalized outputs and gate outcomes. Include failed pages and successful emptiness. Never show MAP_KEY path segments, authorization headers or raw sensitive error bodies.

**28. `GET /admin/ingestion/gaps` — repair backlog**

Input: scope/feed/status/date filters, cursor/limit.

Reads: `ingestion_gaps`, `ingestion_subscriptions`, `ingestion_feeds`, referenced resolution fetch runs.

Returns: gap kind/interval, first detection, last repair attempt, next retry, evidence and resolution. Cloudy observations are not ingestion gaps. Retired sources are explicit accepted-unavailable intervals, not an infinite failing retry queue.

**Infrastructure health routes**

`GET /health/live` checks process liveness without a database query. `GET /health/ready` performs a bounded DB connectivity check and verifies a published catalog/release can be served; return `503` if the API cannot serve its minimum contract. External NASA/Open-Meteo outages degrade freshness but do not make a cached API unready. Worker/queue health is a separate operational signal, not a claim about scientific coverage.

**Example unavailable scientific result**

This is a contract example, not a measured new result:

```json
{
  "schema_version": "1",
  "status": "unsupported",
  "metric": {"id": "aqua_equivalent_active_cell_v1", "unit": "dimensionless_reference_response"},
  "value": null,
  "observation_coverage": {"fraction": null, "status": "unknown"},
  "reasons": ["FIRE_MASK_OR_GEOLOCATION_MISSING"],
  "available_views": ["native_detections", "weather_context", "report_evidence"]
}
```

The client shows this state clearly and may offer a separate descriptive analysis. It never replaces the missing value with zero or labels native counts as harmonized.

**Query design and publication checks**

See [query_patterns.sql](query_patterns.sql) for prepared SQL examples of canonical detections, area-weighted aggregation and scoped freshness. These are design examples for the specified tables; runtime query plans and performance remain untested. Application contracts must additionally validate membership/source filters, role authorization, exact time-basis semantics and release readiness.
