# Historical imports, continuing refresh and correction pipelines

> **Implementation update (October 26, 2026):** the data pipelines and database are now implemented in `src/firebridge`. The backend team will build the HTTP endpoints in **Node.js**. See [the current data guide](../data/README.md), [operations](../data/OPERATIONS.md) and [Node.js database handoff](../data/NODE_HANDOFF.md). The text below preserves the earlier design proposal; statements about FastAPI/Celery or an uninitialized database are superseded by that implementation guide.

**Proposed procedures — October 24, 2026.** These are implementation schedules; no automation is enabled by this design. Provider details and verified limitations are in [SOURCES.md](SOURCES.md).

**1. Shared processing stages**

Every historical and recent job uses the same adapters and validation rules. Only the planner's time windows, priority and publication mode differ.

| Stage | Reads | Writes | Completion condition |
|---|---|---|---|
| Plan | Feeds, subscriptions, availability, checkpoints, open gaps | `pipeline_runs`, `fetch_runs` | Bounded windows, spatial shards, request limits and explicit source versions |
| Fetch | Resolved source requests and credentials | Original bytes, `assets`, `fetch_assets`, run outcomes | Response/file type and size verified; required pages present |
| Normalize | Accepted assets + source adapter | Canonical Parquet, `detections`/`weather_values`/`news_reports`, `quality_issues` | Valid schema, units, identity and coordinates; quarantined rows accounted for |
| Snapshot | Complete canonical records for each affected key | `data_partitions`, input manifests, `partition_detections` | Full replacement snapshot, including a proven successful empty snapshot |
| Scientific processing | Masks/geolocation and canonical source data | `observations`, pairs, predictions, daily records, derived partitions | Documented support, model gates and denominator checks pass |
| Validate | Candidate release and dependencies | Validation receipt, issues | Blocking checks passed; intentional gaps remain labelled |
| Publish | Validated candidate and previous alias generation | Release membership, changes, alias, outbox event | Atomic commit; concurrent-publisher conflict causes rebase/retry |
| Serve | Pinned release + user AOI/dates | Analysis components, charts, exports, evidence | All components use their recorded release membership |

Store full-mask support artifacts outside PostgreSQL, with their CRS, category decoding, nodata and checksums. Do not average numeric category codes when reprojecting QA masks. Cloud and missing classifications use the selected product documentation.

**2. Historical satellite backfill**

1. Register existing files without downloading them again. Compute content hashes, validate ZIP/CSV/GZIP/HDF formats and record native product/collection/stream/date coverage. An extracted CSV that duplicates its ZIP member is a second representation of the same input, not extra data.
2. Define the requested geographic/time inventory. Start with the current January 17, 2024–January 17, 2025 MODIS window and the reviewed pilot. Other sensors have independently inventoried date bounds; do not assume identical archive filename ranges imply identical coverage.
3. Reuse `analysis/acquire_modis_monthly.py` logic for existing monthly MODIS records, then generalize configuration. For missing months/products use documented archive access or bounded standard API windows. Global bulk history uses archive files where practical; the small-area API is not the default downloader for years of worldwide data.
4. Stream files in bounded chunks. Parse native timestamps, confidence schemes, bands, FRP units, product type and footprint fields. Preserve unrecognized codes for review instead of silently mapping them to vegetation or nominal confidence.
5. Split transport records into exact platform/product sources. Canonicalize types and native precision for hashing; two satellites observing the same location are distinct records. Do not cluster nearby points into a “fire count.”
6. Write canonical immutable partitions, normally source/stream/year/month/spatial shard for archive storage. For serving/replacement use deterministic source/day/shard keys. A worker can split monthly input into daily publication partitions while retaining the original monthly file.
7. Compare row counts, duplicates and boundary-date totals against the existing EDA. For the current MODIS target, the known 4,876,343 rows and the independent January overlap audit are regression evidence, not expectations for other products/periods.
8. Build a descriptive release first. Record point-data availability separately from observation coverage. Then discover complete fire masks and compatible geolocation for the chosen calibration window, including periods without positive detections.
9. Persist gaps and progress after each validated unit. Restart from completed units; do not rerun the entire archive or append duplicates after a crash.

For shared bounding-box edges and the antimeridian, assign each record to one deterministic half-open shard. Fetches may overlap; canonical partition ownership must not. Split antimeridian requests into documented boxes and validate polygons before ingestion. A global acquisition scope does not make the proposed Morocco analysis grid globally or polar validated.

**3. Science masks, observation coverage and harmonization**

Use a versioned product-pair catalog: fire product, compatible geolocation product, collection IDs, native pixel convention and decoder version. Inventory all granules intersecting the AOI/time range, resolve companion matches by documented identity/time, and quarantine ambiguous/missing companions. Catalog timestamps are not proof that usable observations exist.

Decode and geolocate the full masks. Union overlap inside a satellite pass, calculate disjoint usable/cloud/invalid/unobserved land, and retain support geometry. Build one observation row per cell/source/pass. A valid negative is an eligible observation with no retained reference detection, not an absent FIRMS coordinate. Gaps in input assets remain unknown until repaired or explicitly accepted unavailable.

For paired training: intersect source/reference usable geometry, match actual times independently of fire outcome, calculate both labels and source features on shared support, and freeze blocked time/geographic/episode splits. Publish model evaluation and eligibility domains before allowing source inference. The first common-grid/logistic model is sufficient if more complexity is unsupported.

For continuing updates, run inference with a fixed validated model, never retrain automatically on each poll. Drift or failed support checks create an issue/unsupported slice. Retraining is a separate versioned experiment with unchanged holdout discipline. A new standard collection or an NRT stream is not automatically compatible with the previous model.

Select at most one supported observation per cell/reporting day under the fixed source/pass policy. Build explicit missing/unsupported cell-days. Aggregate using reviewed AOI land weights and preserve numerator/denominator. Require a sufficient seasonally comparable historical baseline before anomaly language. Recent maps may update before compatible masks arrive; their harmonized layer remains unavailable until its dependencies pass.

**4. Incremental near-real-time hotspot ingestion**

Initial policy: poll configured NRT feeds hourly, with a three-UTC-day overlap. One MODIS fetch serves both Terra and Aqua. NOAA-20, NOAA-21 and available S-NPP feeds have separate requests. Landsat polling is enabled only for a supported geographic scope. The FIRMS documented request maximum is currently five days. These settings must be tuned to measured volume and quota use. [Area API](https://firms.modaps.eosdis.nasa.gov/api/area/)

```text
claim one subscription lease
read source availability and last committed query boundary
choose a fixed UTC end and an overlap window
if the gap is older than provider retention, queue archival repair explicitly
split into provider-legal date chunks and deterministic spatial boxes
fetch each chunk; persist bytes/pages before normalization
validate content, schema, request scope and successful emptiness
normalize records; exact-row dedup across overlapping fetches
rebuild complete affected day/shard snapshots
validate and publish changed partitions in a new release
commit stage checkpoints only for completed contiguous work
record gaps/retries for unresolved windows; release the lease
```

Current-day responses are incomplete with respect to a full day; show `open_period=true`. Do not mark today finalized merely because a request succeeded. The overlap catches late publication; a separate reconciliation scan handles revisions outside it. Split a long outage into bounded catch-up windows; do not jump the checkpoint to the newest returned detection and leave the outage unrepaired.

For a complete query containing only a CSV header, record a successful empty asset, zero records and a complete fetch result. It can establish zero detections returned by that query. It does not establish a clear no-fire observation. HTML login/error pages returned with HTTP 200, unexpected columns, partial downloads and timed-out pagination are failures, not empty scientific data.

**5. Standard replacement, late arrivals and reprocessing**

Use a reconciliation subscription distinct from the fast overlap poll. Initially scan actual standard availability daily and inspect the last 210 days plus every older unresolved gap/replacement task. The 210-day starting horizon is chosen to exceed the archive's presently documented approximate five-month replacement lag; it is not a completeness guarantee. If provider availability is older or delayed, extend it and retain unfinished tasks. [Archive guidance](https://firms.modaps.eosdis.nasa.gov/download/)

| Change | Required action |
|---|---|
| Late NRT detection | Rebuild affected complete day/shard partition; publish a new provisional release |
| Provider changes FRP/confidence/location | New native content hash and partition revision; preserve old release |
| Verified complete standard day replaces NRT | Select standard-only membership for that product/day/shard; do not union the two streams |
| Revised standard file/granule | Fetch revision, compare hash, rebuild dependents and publish a new retrospective release |
| NRT/RT disappearance | Check processing-level expiry and authoritative scope before treating it as removal |
| Missing geolocation arrives | Rebuild observations, pairs/predictions and affected calendar partitions |
| Source is retired | Mark retirement, stop futile repeated polls after verification, retain history and explicit gaps |

A publishable partition is a complete snapshot of its declared scope. Check response completion, provider dates, coverage contract and canonical ownership before replacement. When completeness cannot be established, retain the prior published snapshot as stale, expose the gap, and schedule repair. Do not promote a subset merely because its newest date looks plausible.

Record added/removed/changed counts and evidence in `release_changes.diff_manifest_uri`. Follow `partition_dependencies` transitively to rebuild affected products. Unchanged partitions are reused. Existing analysis IDs remain pinned; new analyses resolve the new aliases. An explicit “compare versions” view can explain the correction without implying the physical fire changed after the fact.

CMR revision polling uses provider-update time, while granule coverage uses observation time. Keep both cursors; a newly revised 2024 granule may have a 2026 catalog update. Periodically re-list historical partitions and compare checksums/catalog revisions because the ordinary recent-observation overlap will not catch all old changes. Search-after pagination is not snapshot-isolated; use stable bounded requests, overlap and reconciliation. [CMR API](https://cmr.earthdata.nasa.gov/search/site/docs/search/api.html)

**6. Historical and current weather**

For the historical selection, acquire a fixed reanalysis model and keep native locations/footprints. Request UTC/Unix timestamps and normalize units. Preserve returned location/elevation and native model metadata. Handle cumulative precipitation according to the source's interval definitions. Derive AOI summaries using native-grid land-area weights, or explicitly label point-sampled context if real footprints are unavailable. Do not present the centre point as the weather for a large AOI.

For current/recent dates, query a verified model run, recording initialization, valid interval and available/retrieved time. Where a provider current endpoint supplies model-derived values without a defensible issue timestamp, classify it as `model_current` with `issued_at=null`. Do not invent an issue time from retrieval time. Prefer a fixed-run endpoint when scientific replay matters. [Open-Meteo Single Runs](https://open-meteo.com/en/docs/single-runs-api) · [Current weather semantics](https://open-meteo.com/en/docs)

Poll model availability hourly, download only a newly available run, and retain prior runs. The exact cadence follows the chosen model's schedule. Refresh reanalysis daily and recheck a rolling 30-day period for late/revised values; audit older months periodically. ERA5's documented API delay is about five days, so the immediate recent layer must be separately labelled. [Historical API](https://open-meteo.com/en/docs/historical-weather-api)

When reanalysis becomes available, a new historical weather release can replace provisional context for newly created analyses. It does not overwrite earlier forecast records. Historical comparisons use the same selected model/aggregation policy; a chart mixing sources displays the switch and disables unsupported anomaly comparisons. For a real-time replay, require `available_at <= replay_time`; later reanalysis cannot be substituted as if known then.

Weather summaries keep separate spatial and temporal coverage fractions, zero versus missing rainfall, wind-vector aggregation, source units and interval boundaries. Recent weather describes conditions, not evidence of a confirmed ignition or an all-weather fire prediction.

**7. Historical reports and news updates**

Backfill a small reviewed collection for selected incidents/periods using original official documents and local reports. News search does not exhaustively cover all fires. Preserve canonical URL, content revision, publication precision and extracted event interval/location uncertainty. The same article may mention multiple events; each gets a separate `reported_events` row. Syndicated copies share lineage.

For ongoing collection, poll approved feeds/search adapters every six hours initially, re-query the previous seven publication days, and revisit candidate articles after 24 hours and seven days for corrections. Each adapter must obey its actual limits and retention window. Detect search result caps: subdivide date/region queries where possible; otherwise label the inventory partial. Do not treat an article absent from a search page as retracted.

Extracting a place/date creates a candidate association. Human review or a carefully evaluated deterministic policy is required before calling it consistent independent evidence. A risk bulletin is not an incident report; a current article discussing a past fire belongs to the past event dates. Satellite-derived reporting is dependent evidence. News changes update reports releases and evidence snapshots, never automatically the satellite training label.

**8. Proposed scheduling and priorities**

| Job | Initial schedule | Window / trigger | Priority |
|---|---|---|---|
| Source availability | Every 6 hours; also before a new backfill | Catalog plus documented retirement/outage state | High |
| NRT hotspots | Every 60 minutes | Last 3 UTC days, chunked within current limits | High |
| Hotspot repair | Nightly | Last 14 days plus known gaps; chunk/scope budgeted | Medium |
| Standard replacement | Daily | Availability-driven; initial 210 days plus all older pending work | Medium |
| New/revised masks | Every 6 hours for enabled products | Provider-update watermark with overlap, plus missing companions | Medium |
| Historical archive audit | Monthly | Rotate through archived months and revision inventory | Low |
| Weather model availability | Hourly | Newly published supported model run | Medium |
| Reanalysis refresh | Daily | Recently available dates plus 30-day revision overlap | Medium |
| News/report discovery | Every 6 hours | Last 7 publication days within adapter coverage | Low |
| Article revision checks | After 24 hours and 7 days | Stored candidates/relevant reports | Low |
| Derived products | On validated changed partitions | Transitive dependency set | High for supported scopes |
| AI explanation | On user request, then cache | Immutable evidence hash + question/language/model/prompt | User-requested |

The team must measure bytes, duration, source transaction costs and database load before enabling all scopes. Apply a single shared FIRMS limiter across subscriptions, not a separate full quota per worker. Global NRT collection, if needed, uses a centrally managed bounded/world feed or shard plan; do not let each user's AOI create another global fetch. Start with registered pilot scopes and the existing global historical analytics.

**9. Retries, failure recovery and publication gates**

| Situation | Behavior |
|---|---|
| Network timeout / 5xx | Exponential backoff with jitter, e.g. 30 s, 2 min, 10 min, 30 min, capped attempts; record gap after exhaustion |
| 429 | Honor Retry-After; pause all work sharing the provider quota as appropriate |
| 401/403 | Mark credential/access failure; suspend repeated attempts until configuration changes |
| Unsupported product/schema | Quarantine; keep prior release; require an adapter update and fixture validation |
| Checksum/partial file | Keep failed artifact isolated; do not register as accepted input |
| Worker dies | Lease expires; retry idempotent work; finalized content-hash objects can be reused |
| Database commit succeeds, broker fails | Outbox dispatcher retries; no lost task |
| Broker delivers twice | Unique job/request/output keys prevent duplicate effects |
| One sensor fails | Other source partitions may publish with explicit gap status; no fabricated zeros |
| Science dependencies absent | Publish descriptive detections if valid; comparable layer reports unsupported |
| Latest publication fails | Preserve old alias and expose staleness; never point users at half-written results |

Before publication, assert canonical selected rows are unique within their source/key; accepted asset hashes match; requested membership is complete or explicitly partial; all values/units are valid; current-period status is preserved; critical QA issues are resolved; and relational serving counts match partition manifests. Scientific releases additionally require usable masks, compatible grids, fixed selection policies and correct numerator/denominator calculations. Weather/report availability is independently reported.

**10. What to verify before enabling the scheduler**

| Scenario | Expected evidence |
|---|---|
| Import/poll the same payload twice | Stable canonical counts and unchanged partition hash |
| Successful header-only CSV | Successful fetch/checkpoint; zero returned dots; coverage remains unknown |
| HTTP-200 login page or truncated CSV | Failed/quarantined input; checkpoint not advanced |
| Late detection with an old acquisition time | Found by overlap/repair; one new partition revision |
| Changed or removed record in a complete snapshot | New release reflects correction; old analysis/export unchanged |
| NRT replaced by standard with fewer points | No double counting; difference manifest; no claim that every removed point was false |
| Worker crash at each stage | Idempotent restart without duplicate publication or skipped gaps |
| Two concurrent publishers | One wins generation check; the other rebases safely |
| CMR revision in an old year | Update-time discovery triggers historical dependency rebuild |
| Missing masks and unsupported model | No false negative, no invented harmonized result |
| New forecast run | Prior issued forecast remains accessible; new analysis pins new context |
| Corrected or syndicated news | New exact document snapshot; no duplicate independent confirmations |
| User requests current versus historical data | Distinct stream/freshness labels, same declared time basis |

These are future implementation acceptance checks. The current turn validates the schema and design contracts only; no live fetch/scheduler behavior has been tested.
