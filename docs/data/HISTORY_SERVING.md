# Prepare the downloaded history for the webapp

The completed download is an immutable raw/Parquet archive. It is not a
PostgreSQL serving release. The webapp reads published database records, not the
download progress counter. All dates below are UTC, start inclusive/end exclusive.

## Run the audit and benchmark

On the VPS, after deploying the release containing these workflows:

```bash
cd /opt/firebridge/current
sh scripts/prepare_history.sh
```

This authenticates to private Airflow using the scheduler's existing environment,
starts/reuses the manual audit, waits for success, then runs the isolated benchmark.
It restores the workflows' prior paused state. It does not start the acquisition
DAG, enable provider subscriptions or import the entire history into the main DB.

Alternatively, trigger these in order in Airflow:

1. `firebridge_history_audit`
2. `firebridge_history_benchmark`

The benchmark samples one nonempty, bounded, median-sized window per available
feed. MODIS samples must contain both Terra and Aqua. It loads real records into
a new `firebridge_history_benchmark_<random>` database, runs the real publication
code and dbt checks, measures table/index/file sizes and a populated spatial/time
query, then removes its temporary database/files after success. Failed benchmark
logs remain under the generated benchmark directory for diagnosis. It changes
no main database detections or release aliases.

## Reports and their meaning

Server reports live under `/opt/firebridge/shared/data/platform/history-serving/`
(the containers see `/data/history-serving/`):

| File | Meaning |
|---|---|
| `audit-progress.json` | Last saved audit checkpoint; use Airflow for task health. |
| `audit.json` | Per-feed request dates, known provider gaps, observed platforms/versions, row counts, empty windows, invalid FRP and native-quality counts, and per-window integrity results. |
| `audit.sqlite3` | Resumable audit cache, keyed by inventory and file sizes/mtime. A refresh rehashes everything. |
| `benchmark.json` | Actual sampled IDs, imported/deduplicated counts, table/index and canonical-object sizes, dbt results, query plan/timing and explicitly approximate archive-wide storage estimates. |
| `load-<scope>.json` | Last completed import batch or active checkpoint. |

An audit `passed` state verifies file integrity and row support. Its quality counts
can still identify invalid optional measurements or windows requiring native-field
review. Strict normalization is the final gate during loading; a malformed required
field rejects the window. Request completeness does not establish satellite
observation coverage or prove an absence of fire.

Direct offline audit command:

```bash
sh scripts/stack.sh exec -T airflow-scheduler firebridge history-audit
# Force all checksum/quality checks again instead of using unchanged cached files:
sh scripts/stack.sh exec -T airflow-scheduler firebridge history-audit --refresh
```

## Native semantics

MODIS `6.03`/`6.02`/`6.0` are Collection 6; `6.1`/`61.03` remain Collection 6.1.
They use distinct source IDs and are not silently merged. NASA's
[GIBS version mapping](https://nasa-gibs.github.io/gibs-api-docs/python-usage/)
documents these identities. Legacy individual-file adapters retain their stricter
Collection 6.1 contract; use this history loader for mixed historical collections.

A negative or nonfinite FRP is retained in the original file and in the canonical
record's `native_fields.frp_raw`, with `frp_quality=invalid`; its analytical
`frp_mw` is NULL. It is not replaced by zero. The quality issue is recorded in SQL.
Other invalid required native values block the window, rather than silently
dropping observations. RT/URT exclusions remain explicit in load counts.

Landsat uses a separate `<scope>-landsat-us-canada` release scope with explicit
provider-footprint metadata. Its footprint is not described as global coverage;
this loader currently imports that complete provider footprint, not arbitrary
regional Landsat slices. `scan`/`track` remain native image positions for Landsat,
not MODIS-style pixel footprint sizes.

## Publish bounded batches after capacity review

The full archive can require much more disk than its compressed files. Review the
benchmark's database **plus sidecar-object** estimate, and leave room for WAL,
backups, indexes, maintenance and future updates. Current dbt builds recompute a
changed scope in full. A sampled extrapolation does not prove that the entire
archive will fit or meet production query limits.

After that review, `firebridge_history_load` accepts, for example:

```json
{
  "scope": "global",
  "max_windows": 3,
  "max_rows_per_window": 2000000,
  "database_budget_gib": 100
}
```

It has no schedule and starts paused. Each run processes at most three new windows
with this configuration. `request_ids` can select explicit known window IDs; its
length cannot exceed `max_windows`. The hard per-run maximum is 50 windows, and
the row limit is bounded at 10 million per window. No provider request is made.
The default free-disk reserve is 16 GiB, with conservative per-partition preflight
headroom and a database size budget. These guards are not disk reservations;
other services can also consume space.

The actual loading stages are:

1. Reverify raw gzip, Parquet and daily-summary hashes against acquisition receipts.
2. Stream bounded Parquet batches through native validation; deduplicate into a
   disk-backed SQLite spool keyed by source/date/canonical record hash.
3. Build each complete source/day snapshot as a streaming immutable object, then
   bulk COPY normalized rows and link exact partition memberships in PostgreSQL.
4. Publish the full verified window's partitions and release aliases in one
   transaction; mark its deterministic SQL `pipeline_runs` checkpoint succeeded.
5. Refresh planner statistics. The Airflow workflow runs dbt for affected scopes.

Daily partitions committed before a crash are reusable but are not published by
that incomplete window. A retry reuses them. A normal next batch skips successful
SQL checkpoint keys without rereading all previous files; an explicitly selected
replay rehashes its inputs and checks committed membership counts. Failed windows
retain a blocking quality record and preserve the previously published release.

Source releases commit per complete window. dbt publication is a separate atomic
gate: a dbt failure leaves the earlier analytical version readable. Retrying the
DAG reuses the native import and retries analytics. Existing saved webapp analyses
remain pinned to their original releases; request a new analysis for new releases.

## What comes after preparation

For automatic user-selected historical areas/dates, use the selective serving
path described in [HISTORICAL_ANALYSES.md](HISTORICAL_ANALYSES.md). It filters the
archive first and publishes only the requested area into a bounded PostGIS cache.

Choose a serving retention/capacity plan from the measured report. A practical
option is the complete Parquet archive for historical research and a measured
recent subset in PostgreSQL. Full native-history serving may need more storage,
database partitioning and incremental analytical builds. These are separate from
finishing the download. Enable recent collection only after choosing the global
collection strategy and source/date reconciliation policy.
