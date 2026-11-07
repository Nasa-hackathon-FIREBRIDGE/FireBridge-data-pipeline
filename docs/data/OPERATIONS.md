# Run and maintain the data pipelines

**For the Airflow + dbt server deployment, start with [DEPLOYMENT.md](DEPLOYMENT.md).** This page documents the ingestion adapters and their subscription rules. The legacy `firebridge worker` commands below apply only when the database's orchestration owner is `local`; they are rejected when Airflow owns ingestion. Analytical models and versioned outputs are explained in [ANALYTICS.md](ANALYTICS.md).

All commands run from the project root. Internal date intervals are **start inclusive, end exclusive, UTC**. January 17, 2024 through January 17, 2025 inclusive is `--start 2024-01-17 --end 2025-01-18`.

## 1. Local setup

```bash
python3 scripts/init_local.py
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-data.lock
.venv/bin/python -m pip install --no-deps -e .
docker compose up -d db
.venv/bin/firebridge init
.venv/bin/firebridge register-pilot
.venv/bin/firebridge status
```

`init_local.py` creates random project-specific database passwords and mode-0600 `.env`; it never overwrites an existing file. The database listens only on `127.0.0.1:55432`. The database is named `firebridge`. `init` verifies the checksum of every applied SQL migration; change the schema by adding a new migration. Rerunning setup does not erase data. Use Python ≥3.12; local tests also ran on Python 3.14.

The reader password is `FIREBRIDGE_READER_PASSWORD` in the private `.env`; use that with user `firebridge_reader` for the backend. The writer connection is `DATABASE_URL`. Keep both outside source control. The Docker worker overrides its database hostname to `db` and object directory to `/data`.

## 2. Historical imports using local files

```bash
# Complete global MODIS selection already prepared and checked by the EDA.
.venv/bin/firebridge import-modis --scope global --bbox=-180,-90,180,90 \
  --start 2024-01-17 --end 2025-01-18

# Complete smaller serving selection, including zero-return days.
.venv/bin/firebridge import-modis --scope morocco-pilot --bbox=-6.4,34.5,-4.5,35.9 \
  --start 2024-01-17 --end 2025-01-18

# Six local VIIRS annual archives, with the overlap date assigned once.
.venv/bin/python scripts/import_downloads.py

# General CSV/ZIP importer: declare the original download request's coverage.
.venv/bin/firebridge import-archive \
  --path '/path/to/fire_archive.zip' --feed VIIRS_NOAA20_SP \
  --scope my-region --bbox=-6,34,-4,36 \
  --start 2024-01-17 --end 2024-02-01 \
  --coverage-start 2024-01-01 --coverage-end 2025-01-02
```

`--coverage-start` and `--coverage-end` must come from the archive request/inventory, not from the first and last observed hotspot. These are operator-supplied assertions and are saved in provenance. A provider outage within an archive remains possible; this importer does not equate archive completeness with satellite observation coverage.

The CSV reader streams the compressed member without extracting its global table. It validates coordinate casts and ZIP CRC, spools selected rows to disk, and only publishes after the full member is read. A ZIP must contain exactly one CSV. A corrupt payload, invalid selected record, or out-of-scope record prevents publication. Exact canonical records deduplicate by source and hash. Changing a native row creates a new record; a complete replacement partition controls which revision is selected.

The MODIS command accepts the audited EDA Parquet with `source_file`, `source_row` and standard-stream provenance. It is not a generic arbitrary-Parquet completeness detector. Original source files remain in `data/external/modis_2024_2025`; the stored Parquet preserves their native values and source row references.

For Landsat use a US/Canada scope. A Morocco empty slice is not supported coverage. Do not use both the ZIP and its extracted copy as independent datasets.

## 3. Future satellite updates — currently disabled

A free **FIRMS MAP_KEY**, available from [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov/api/map_key/), authorizes point-feed API access. Put it in `FIRMS_MAP_KEY` in `.env`. It is different from `EARTHDATA_TOKEN`, which is for protected science-file access. No key is stored in SQL, manifests, reports or error messages.

`register-pilot` creates disabled subscriptions. Inspect their IDs with `status`, then explicitly enable the intended one:

```bash
.venv/bin/firebridge availability                 # explicit external request
.venv/bin/firebridge enable SUBSCRIPTION_UUID
.venv/bin/firebridge worker --once                # schedule, process one task, exit
.venv/bin/firebridge worker                       # foreground continuous worker
```

For a persistent container worker, after initialization:

```bash
docker compose --profile pipeline up -d --build worker
docker compose logs --tail=50 worker
docker compose stop worker
```

Do not run a host and container worker against different copies of the object directory. They must share the same bytes. SQL object URIs are relative to `FIREBRIDGE_DATA_DIR` (for example, `objects/ab/<hash>.json`) and are portable between host and container. Original source URLs/paths describe provenance. The Node.js API should use the serving views; filesystem access requires a separate deliberate object-serving policy.

`disable UUID` blocks queued tasks for that subscription and prevents future scheduling; an already-running request may finish. `resume UUID` explicitly requeues failed/blocked tasks and enables the subscription after the underlying issue is fixed. No schedules were enabled in the local-data implementation run.

### Actual scheduling rules

| Subscription | Due interval | Work planned |
|---|---|---|
| NRT incremental | 1 hour | Last 3 UTC dates, one date per task, including the open current date |
| NRT reconciliation | 1 day | Last 14 UTC dates |
| SP reconciliation | 1 day | Up to 210 dates ending at catalog availability; plus older recorded gaps |
| Historical backfill | 1 hour planning cycle | Up to 31 dates enqueued per cycle until the requested end |
| Weather reanalysis | 1 day | Recent overlap, ending before the nominal 5-day provider delay; explicit missing values retained |
| Weather recent | 1 hour | Recent 3-date model-context window |
| CMR revisions | 6 hours | Updated-in-last-7-days across the subscription's full historical temporal interval |
| Approved RSS | 6 hours | Current feed metadata; partial inventory, no guarantee of 7-day retention |

FIRMS availability is refreshed every six-hour cycle and rechecked before data requests if stale. The area adapter allows 1–5 days, but the scheduler uses one day to bound work. Registered live FIRMS rectangles are limited to 100 square degrees; a global live deployment needs a reviewed shard/central-feed strategy. The default shared local budget is 60 requests per ten minutes, conservative relative to the advertised account transaction limit. Large queries may consume more than one provider transaction; this is not a complete provider transaction accounting system. HTTP 429 applies a shared cooldown and honors Retry-After.

Availability bounds are hints, not proof that a sensor saw every place each day. The returned source/platform and processing stream are checked; RT/URT records are preserved in the raw response and excluded from the NRT serving product. There is no automatic future-platform substitution.

Standard reconciliation waits for an availability catalog before planning dates. Requests older than the available API interval block with `historical_archive_required`; use an archive import instead. A queued/running request is coalesced across scheduling cycles, so a delayed provider does not create a second active copy of the same work. Legacy NOAA identifiers `1`/`2` and current `N20`/`N21` normalize to the same exact platform; unknown MODIS/VIIRS collection versions are rejected. These aliases follow [NASA's FIRMS naming notice](https://firms2.modaps.eosdis.nasa.gov/usfs/tutorials/) and [NASA's current VIIRS attributes](https://modaps.modaps.eosdis.nasa.gov/services/about/products/viirs-land-c2-nrt/vj114imgtdl_nrt.html).

## 4. Weather and reports

Historical weather command (external request, not executed during local-only setup):

```bash
.venv/bin/firebridge fetch-weather --scope morocco-pilot --bbox=-6.4,34.5,-4.5,35.9 \
  --latitude 35.2 --longitude -5.45 --start 2024-07-01 --end 2024-08-01 --kind reanalysis
```

ERA5 is fixed explicitly. Recent model data uses `--kind model_current` with ECMWF IFS 0.25°. Values retain returned coordinates, units, valid intervals, retrieval availability, missingness and model. Unknown issue time stays null; this is not a pinned forecast-run archive. Precipitation samples represent the preceding hour ending at the provider timestamp. Partition days use sample time, so the first rain sample covers the previous day's final hour. Choose interval-based aggregation deliberately in the backend.

Local dated report import:

```bash
.venv/bin/firebridge import-reports --path my-reviewed-reports.json --scope morocco-pilot
```

See [reports.example.json](../../config/reports.example.json) for the shape. That file is a clearly labeled synthetic template; do not import it into a real evidence release. A reviewed document requires `reviewed_by`. A publication date is not assumed to be an event date. Each event has its own interval and location precision. Corrections create a new document version; previous releases remain readable. Articles disappearing from an RSS response are not retracted.

For RSS, register `NEWS_RSS` with non-secret JSON config containing `url` and `publisher`; explicitly allow the hostname in `FIREBRIDGE_NEWS_ALLOWED_HOSTS`. The adapter accepts HTTPS RSS/Atom, rejects XML entities, and limits payloads to 2 MB. It saves original XML and normalized metadata. Items are unreviewed and contain no inferred event locations. An empty feed is a partial discovery result, never “no fires.” Live RSS has not been verified in this run.

## 5. Science catalog

```bash
.venv/bin/firebridge discover-science --collection C_PINNED_CONCEPT_ID \
  --scope morocco-pilot --bbox=-6.4,34.5,-4.5,35.9 --start 2024-07-01 --end 2024-07-02
```

Resolve and pin a real collection ID from CMR first. The adapter retains every catalog page, follows search-after, detects repeated/missing cursors, and caps each job at 10 × 200 granules. A capped job is explicitly incomplete/blocked; split it into smaller windows. CMR is not snapshot-isolated. This code catalogs revisions but does not download/decode masks, pair geolocation companions, or calculate usable observations. The research downloader in `analysis/download_science.py` remains a separate bounded experiment.

## 6. Recovery, checks and backups

- Workers claim jobs using `FOR UPDATE SKIP LOCKED`, with a 20-minute lease and a new token on each claim. Publication checks that token. Expired jobs can be reclaimed; expired final attempts become failed. Duplicate queue delivery does not duplicate canonical records or unchanged releases.
- Network/server errors retry with backoff/jitter. Authentication/schema errors block the task; a blocked subscription is disabled until explicit repair/resume. 429/budget/provider-availability waits do not exhaust normal attempts.
- FIRMS failures create gap rows. A later complete successful window resolves its covered gaps. Daily repair includes older open gaps outside the rolling window. Failed local imports remain in `pipeline_runs`; rerun the same command after fixing the cause.
- A checkpoint means **the furthest completed query window**, not contiguous archive coverage. Its `cursor_json.contiguous` is false; inspect gaps and partition coverage as well. Never infer coverage from the latest hotspot timestamp.
- A release transaction writes membership, alias changes, change records and a durable publication event together. `NOTIFY firebridge_release` is a wakeup hint; `serving.release_events` is the recoverable event ledger. No broker is required.
- Current release history and original objects are retained indefinitely in this MVP. There is no automated deletion/retention job or external alert-delivery service. Monitor disk usage, failed/blocked tasks and stale subscriptions.
- Global quarterly/monthly provider archive audits and automatic CMR page subdivision are not yet implemented. The CLI supports explicit bounded reimports/backfills; schedule an operator-reviewed audit before a broader deployment.

```bash
.venv/bin/firebridge status
sh scripts/backup_database.sh
# Also back up data/platform/objects without modifying their content-addressed names.
```

Restore a dump into a **new** PostGIS database and validate it before switching clients. Never use `docker compose down -v` for routine stopping; it removes the named database volume. `docker compose stop` preserves it.

Tests use fixture HTTP responses and a newly created `firebridge_test_<random>` database; no providers are called:

```bash
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m pytest -q -m 'not integration'
FIREBRIDGE_TEST_DB=1 .venv/bin/python -m pytest -q
```
