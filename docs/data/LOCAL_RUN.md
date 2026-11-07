# Run the complete local data workspace

From this project directory, run:

```bash
./start_local.sh
```

**This now starts/resumes the full historical NASA FIRMS download as well.** It runs in Airflow after the existing local archives are loaded; the launcher returns while the download continues. Read [FULL_HISTORY.md](FULL_HISTORY.md) for date coverage, storage limits, and progress. Use `./start_local.sh --skip-download` to start the local services without launching a new download.

If the input folder moves:

```bash
./start_local.sh --archives '/new/path/to/nasa hackathon data'
```

Docker Engine with Docker Compose and Python 3 must already be installed. This launcher uses the local archive inventory and audited MODIS Parquet from the EDA. It does not require a host Python virtual environment. The first run needs internet access to obtain container images and the official DuckDB browser extension/UI assets.

## Open these URLs

| URL | What to inspect |
|---|---|
| <http://localhost:4213> | **Existing files:** expand `nasa` → `main`. **New full-history acquisition:** expand `history` → `main` after launching the download. |
| <http://localhost:8082> | **PostgreSQL serving data:** expand `serving` to inspect validated native releases and dbt summaries. The connection uses `firebridge_reader` and is read-only. |
| <http://localhost:8080> | **Airflow:** task progress, logs, schedules and failures. Use `AIRFLOW_ADMIN_USER` and `AIRFLOW_ADMIN_PASSWORD` from the private `.env`. |

The data browsers connect automatically; no database password needs to be entered. All three listeners are local to this computer. Closing the browser does not stop Docker services.

## What the command does

1. Checks every inventoried input file and generates any missing private configuration without replacing credentials.
2. Builds the image and starts PostgreSQL/PostGIS plus the separate Airflow metadata database.
3. Applies migrations, prepares permissions, and gives Airflow ownership of ingestion.
4. Starts the API, scheduler, workflow parser and PostgreSQL browser.
5. Triggers or resumes `firebridge_local_archive_lake` and waits for it to finish. This manual Airflow workflow reads all ten ZIP archives, without date or geographic filtering, and includes the audited MODIS study selection.
6. Enables the ingestion, analytics and health workflow schedules and triggers an initial run of each.
7. Unless `--skip-download` is supplied, starts or resumes `firebridge_full_history_download`, a manual Airflow workflow that acquires all available project fire-point history. It does not wait for that long download to finish.
8. Starts the SQL browser, verifies all three HTTP URLs, and prints them.

Keep the terminal open during the first archive import. Services are detached; after the command succeeds, the terminal may be closed. The archive task can continue in Airflow if the terminal disconnects; rerun the command to reconnect to an active import or verify/reuse completed files. Reruns verify checksums and reuse converted archives. They do not create a second copy of their source rows. The catalog is rebuilt atomically, and the browser restarts to attach to that version.

Startup preserves existing provider subscription settings. **The recurring provider subscriptions remain disabled.** The new full-history workflow is separate and does download NASA data when launched. To start ongoing live fetching after the backfill, inspect provider availability and enable the intended subscriptions using [OPERATIONS.md](OPERATIONS.md). A laptop must remain powered on with Docker running for execution to continue.

## Why two data browsers?

The existing PostgreSQL representation uses roughly 4.9 GB for 4.89 million canonical records. This laptop had about 28 GB free before the full load. Expanding approximately 148 million archive rows into the same indexed representation, plus provenance files, would exceed that capacity.

The complete history therefore lives in **compressed Parquet files**, queried locally by **DuckDB**. PostgreSQL keeps the existing validated serving scopes and their analytical releases. This is a deliberate storage split: the complete archive is not silently claimed to be in PostgreSQL. The Node.js team still uses the published PostgreSQL contract; full global serving slices can be imported on adequately sized storage later.

The source archive layer preserves questionable values and duplicate/overlap rows for inspection. It is not a validated release, a unique-detection count, a fire-incident catalog, or an expansion to every NASA mission product. These files contain active-fire point records for Terra, Aqua, S-NPP, NOAA-20, NOAA-21 and Landsat 8/9. Landsat files cover their US/Canada footprint. The existing `nasa` catalog starts with NOAA-20 in 2023 and other loaded platforms in 2024. The separate `history` catalog expands backward as requested windows finish downloading. Its planned dates must not be mistaken for completed coverage.

The `nasa` catalog contains all ten ZIPs plus the filtered MODIS study selection. It does not include January 1–16, 2024 from the additional raw MODIS monthly files. The full-history acquisition requests that period directly along with the rest of MODIS history.

## Start exploring the full archive

In the DuckDB browser, create a SQL cell and run:

```sql
SELECT * FROM nasa.main.satellite_inventory ORDER BY satellite;
```

This gives each satellite's source-row count, first/last observed dates, number of archives and invalid FRP count. Dates are observed ranges, not proof that every day or location was observed.

Inspect points from a satellite/date range:

```sql
SELECT * FROM nasa.main.detections
WHERE satellite='N20'
  AND date_utc >= DATE '2024-07-01'
  AND date_utc < DATE '2024-08-01'
LIMIT 100;
```

Inspect regional points without loading the world into the browser:

```sql
SELECT * FROM nasa.main.detections
WHERE longitude BETWEEN -6.4 AND -4.5
  AND latitude BETWEEN 34.5 AND 35.9
  AND date_utc >= DATE '2024-01-17'
  AND date_utc < DATE '2025-01-18'
LIMIT 500;
```

Inspect source counts and overlapping download days:

```sql
SELECT * FROM nasa.main.archive_inventory;
SELECT * FROM nasa.main.overlapping_source_days ORDER BY satellite,date_utc;
SELECT * FROM nasa.main.archive_daily_counts
WHERE satellite='N21' ORDER BY date_utc,archive;
```

`raw_source_rows` preserves all CSV columns as source text, plus archive/satellite/row provenance. The additional audited MODIS selection retains its native typed fields and original source filename/row. `detections` exposes convenient typed fields. Invalid negative/nonfinite FRP remains visible in `frp_raw`, with `frp_invalid=true` and `frp_mw=NULL`. Confidence scales are native and differ by sensor. Landsat `scan_native`/`track_native` are positions, not kilometre footprint widths.

The S-NPP downloads label the native instrument field `SNPP`. The convenience view retains that in `instrument_raw` and identifies the actual instrument as `VIIRS`, using the satellite identity.

**Do not sum overlapping archive days as unique detections.** Yearly files overlap on boundary dates; the audited MODIS selection overlaps the 2025 MODIS archive; one Landsat archive contains exact duplicate rows. These facts are intentionally visible. Use PostgreSQL pinned releases for validated, deduplicated project results.

The DuckDB UI executes queries locally. Its frontend assets are fetched from the official UI server; no MotherDuck/cloud sign-in is required. [Official DuckDB UI documentation](https://duckdb.org/docs/1.5/core_extensions/ui)

## Inspect PostgreSQL results

In the PostgreSQL browser, open the Query tab:

```sql
SELECT * FROM serving.latest_analytics;

SELECT d.scope_key,d.platform,SUM(d.detection_count) AS detections
FROM serving.daily_detections d
JOIN serving.latest_analytics l ON l.build_id=d.build_id
GROUP BY d.scope_key,d.platform
ORDER BY d.scope_key,d.platform;
```

For detailed backend examples, use [ANALYTICS.md](ANALYTICS.md) and [NODE_HANDOFF.md](NODE_HANDOFF.md).

## Stop, restart and troubleshoot

```bash
./stop_local.sh
./start_local.sh

# Service state and recent task-runner logs:
sh scripts/local_stack.sh ps
sh scripts/local_stack.sh logs --tail=80 airflow-scheduler archive-browser

# Compact archive progress and final inventory:
cat data/platform/lake/progress.json
cat data/platform/lake/manifest.json
```

No command above removes database volumes or original downloads. If an archive fails validation, inspect its Airflow task log; previously completed Parquet files remain reusable. Conversion stops before the disk drops below an 8 GiB reserve. Preserve `data/platform/lake/parquet`, its receipts and catalog together when moving the full archive. The existing server backup script backs up PostgreSQL and its immutable object store; it does **not** include this additional lake directory. Back up the lake separately or rebuild it from the original ZIP files and audited MODIS selection.
