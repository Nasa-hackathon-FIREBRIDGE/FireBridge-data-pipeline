# Serve historical analyses without loading the world archive into PostgreSQL

The archive remains the complete immutable gzip/Parquet inventory. A historical
request is prepared asynchronously: Arrow prunes indexed files and row groups by
dates and coordinates (DuckDB handles the raw fallback), then PostGIS applies the exact saved polygon
(including holes and the same antimeridian rules as the webapp). Only selected
records go through the existing canonical native normalizer and publisher.

The result is a bounded PostGIS cache for that area, interval, processing policy
and immutable archive catalog. Existing map tiles, source counts, calendars,
exports and factual AI evidence read the same frozen release. They do not need a
second implementation of result semantics. Full global history is never imported
as a side effect of a user request.

## Request lifecycle

1. Node checks whether a published PostgreSQL release covers the whole requested
   interval for the saved area or a verified world rectangle. A later cutoff alone
   is insufficient. If native serving does not cover it, the request pins the
   immutable historical catalog and queues the existing analysis job.
2. The Node worker submits the analysis UUID to the private history service. It
   renews its SQL lease while polling. The service accepts no file paths, SQL,
   geometry or caller-selected release IDs.
3. The service creates/reuses a deterministic `pipeline_runs` record. One worker
   processes jobs with a PostgreSQL advisory lock. Running jobs can resume after
   container restart; repeated submissions reuse their durable checkpoint.
4. Input Parquet hashes are checked against the audited snapshot. Unchanged
   immutable files reuse process-local checksum verification. Reads retain the
   original native column list, avoiding MODIS/VIIRS band-name ambiguity.
5. After exact polygon clipping, records are normalized and deduplicated into a
   disk-backed spool. Invalid optional FRP becomes a flagged NULL with its raw
   value preserved. A selected malformed required field rejects the whole result.
6. Complete source/interval partitions, memberships, release publication and the
   success receipt commit in one transaction. A failed job cannot publish a
   partial result. The ordinary `global` recent aliases remain unchanged.
7. Node checks the returned release against the catalog, area, dates and durable
   successful run. It binds the result only while still owning the analysis lease,
   updates the satellite component, then completes the analysis. Missing weather
   or reports still produce the existing explicit partial status.

The analysis cache key pins the original archive catalog. The prepared satellite
release is bound while the analysis is still running, before any results become
ready. Completed analyses are not repinned by later archive publications.

## Configure and deploy

Build the spatial serving index once after auditing acquired history. In Airflow,
trigger `firebridge_history_index` with `{}` to cover all available standard
history. It resumes already verified windows and publishes the catalog after the
batch succeeds. Optional `start`/`end` bounds and `max_windows` allow bounded
batches. These are local data operations with no provider requests.

The equivalent server commands are:

```bash
cd /opt/firebridge/current
sh scripts/stack.sh exec -T airflow-scheduler firebridge index-history
sh scripts/stack.sh exec -T airflow-scheduler firebridge publish-history-catalog --scope global
```

Each five-day window is copied into immutable regional Parquet shards. Native
strings, duplicate records and row identifiers remain unchanged. Typed coordinates
and spatial ordering let the bounded Arrow reader prune row groups. Publication requires full exact
row comparison against the audited input, including the typed index coordinates.
The catalog pins each shard hash and its original source hash. Requests verify
only shards overlapping the saved geometry's bounding box, then apply the same
exact PostGIS polygon and normalization rules. Missing indexes use the verified
raw path. Old saved analyses retain their pinned releases.

Index construction uses up to two workers, each with one CPU thread, 768 MiB of
DuckDB memory and at most 2 GiB of temporary spill, plus a 16 GiB free-disk reserve.
Use `index-history --workers 1` on a smaller host. It consumes additional disk
for derived copies; progress records actual retained bytes in
`/data/history-index/progress.json`. Build it after new archive batches as well.
The history service mounts the published index read-only. Indexing never runs in
the public request path.

The existing data-platform image contains `history-api`. It has no public port,
uses Docker's private data network as `http://firebridge-history:8090`, and mounts
the source history directory read-only. It receives no NASA provider credentials.
Its container is read-only outside persistent data and a small temporary mount.
The default CPU/memory ceilings are 2 CPUs and 1536 MiB. Indexed reads use two
Arrow CPU/I/O threads, 2048-row batches and bounded fragment read-ahead. The raw
fallback uses two DuckDB threads and a 512 MiB memory budget. Heavy preparations
run one at a time.

After the data-platform deployment and a successful archive audit, publish the
catalog metadata once:

```bash
cd /opt/firebridge/current
sh scripts/stack.sh exec -T airflow-scheduler firebridge publish-history-catalog --scope global
```

This adds the `historical_archive` catalog alias. It does not load point records,
move `standard_only`/`best_available`, or fetch provider data. After acquiring new
data or changing normalization code, rerun the audit and publish the new catalog.
Existing analyses keep their previous pinned inputs.

Generate a random private token of at least 32 characters. Configure it as
`FIREBRIDGE_HISTORY_TOKEN` in the data-platform server `.env`. In the webapp's
private `runtime.env`, set:

```dotenv
HISTORY_SERVICE_URL=http://firebridge-history:8090
HISTORY_SERVICE_TOKEN=<the same private token>
```

Recreate the history service and app API/worker after setting these fields.
Enable app historical routing only after both tested releases and the catalog are
ready. The token belongs only in private server configuration, never Git or chat.
The shared application DB credentials and source-data ownership remain separate.

No new permanent database migration is needed. The implementation reuses
`pipeline_runs`, immutable native partitions, releases, assets and the existing
analysis queue. Main schemas and curated view contracts remain compatible.

## Current explicit limits

- UTC native `standard_only` analyses, matching the existing webapp contract.
  NRT-only Landsat and recent VIIRS/MODIS tails are not silently relabeled standard.
- At most 3660 days per historical request, one million selected input rows before
  deduplication, a 100 GiB total database budget and a 16 GiB free-disk reserve.
- The bounded PostGIS cache is retained; this version stops new preparation at its
  budget instead of deleting data referenced by saved analyses. Cache reclamation
  requires an explicit policy for saved snapshots and immutable objects.
- First-time requests incur archive reads and preparation. Identical requests
  reuse the analysis and prepared result. Page, tile and export limits still apply.
- Verified empty inventory can produce zero counts. Missing catalog intervals,
  unavailable platforms and unresolved empty MODIS collection identities remain
  incomplete; they do not prove that the satellite observed no fire.

## Inspect work

Use the existing webapp analysis job and private PostgreSQL/pgAdmin access. Data
preparation runs have `pipeline_runs.stage='archive-selection'`. They expose a
safe error code, input catalog, immutable output receipt and timing. The receipt
records selected/duplicate/invalid-FRP counts and verified input bytes/windows.
The analysis job reports `preparing_history` while the satellite component is
being prepared. The public API never receives source filesystem paths or secrets.

For an example full year, use `2020-01-01` through the exclusive end `2021-01-01`.
The audited 2020 archive has Terra, Aqua, S-NPP and NOAA-20. NOAA-21 and the
downloaded Landsat feeds have no 2020 records. Do not imply their presence.
