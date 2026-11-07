## Publication checks beyond individual SQL rows

These cross-row and scientific checks belong in the pipeline and must pass before a release is published. SQL foreign keys alone do not prove them.

- Every input hash matches its stored bytes, every output references accepted assets in the correct release, and source collections/geolocation companions are compatible.
- Canonical source files do not duplicate the same observation through overlapping archives, ZIP/CSV copies, FIRMS/swath duplicates or NRT/standard representations. The file/record unique key makes retries safe; canonical cross-file selection is a separate ingestion responsibility.
- Geometry is valid, within the supported grid extent, and has the documented land mask. AOI weights are positive and do not exceed cell land area. All computed numeric fields are finite.
- Observation land categories are disjoint and sum to cell land area within a declared geometric tolerance. Eligible rows have decoded mask/geolocation provenance, actual usable support and detection links. Unavailable coverage is never synthesized from absence of detections.
- Matched observations belong to the intended two sources/regime, with time difference recomputed from actual times. Shared support is the geometric intersection; its fraction uses the declared denominator. Targets and features are recalculated on that exact support. Unique pairing keys prevent reuse within a defined series.
- Frozen temporal, geographic and episode groups do not leak across train/development/calibration/test. Features contain no reference-only or future information. Probability calibration uses a disjoint split.
- A model's source product, stream, grid, feature schema and support domain match inference inputs. Only validated models can enter a published comparable product. Predictions carry the same release/cell as their observation.
- A daily predicted row points to a prediction of its selected observation, uses the same response value, and is supported. A reference row points to the correct eligible reference product and copies its defined response. No selection is based on maximizing fire response.
- All expected cell-days are represented, including missing states. Analysis grid, area weights, reporting dates, metric and selection policy match the daily rows being aggregated. Periods lie inside the selection. Coverage remains distinct from scientific support.
- Historical anomaly labels pass the frozen minimum-year, sample-size and common-support policy. A positive baseline-year count alone does not establish a sufficient baseline.
- Weather inputs have explicit variable, units, model, valid interval, availability/issue times where applicable and accumulation semantics. Weights do not count duplicated returned grid points. Missing hours reduce coverage rather than become zero rain.
- Report matches use event dates and geographic precision, retain the exact document revision, and distinguish source independence from syndication. Review changes create a new evidence snapshot.
- Published scientific releases and evidence snapshots are immutable in the service layer. Corrections create new releases/snapshots. API/worker database roles prevent ordinary requests from rewriting published results.
- AI output references existing facts in its own snapshot, preserves metric units/time basis, and cannot turn contextual weather or news into automatic sensor ground truth.
- Every selected partition has the matching series/key, validated immutable bytes and complete declared membership. Zero-row partitions require successful authoritative empty retrieval. The partition-dependency graph is acyclic, including transitive paths.
- A release's dataset kind agrees with its partition kinds; alias scope/kind/stream agree with the target release. Published aliases never point to draft, partial-write or quarantined artifacts. Raw descriptive releases can contain explicit gaps without claiming complete observation coverage.
- Each analysis has exactly one satellite component matching analyses.release_id. Weather/report queries use only their pinned release membership and exact revisions. Component states, request hashes and cache keys cannot change after the analysis is finalized.
- Every served detection belongs to exactly one selected canonical source/day/shard in the release. Repeated sightings link through raw input manifests without duplicating canonical membership. Standard and NRT do not overlap for a product/key selected under best-available policy.
- Checkpoints advance by validated contiguous work in their declared query basis, not by latest positive observation. Open gaps remain in the repair ledger. Publication and outbox event insertion commit together; consumers tolerate repeated delivery.
- Quality issues with blocking severity must be resolved before publication; accepting a limitation requires an explicit reason and a product status that exposes its consequence. Missing companions and source retirement never become valid negative observations.

## Indexes and scaling

The SQL includes GiST geometry indexes, source/time lookups, pairing split lookups and a simple multilingual-friendly lexical news index. The news index uses the `simple` text-search configuration; it does not claim language-specific stemming or semantic retrieval. Start with bounded serving tables and measure query plans. PostgreSQL monthly partitioning is a later migration that must account for partition keys in unique constraints and foreign keys.

See [validation.json](validation.json) for static verification. No database was connected to or modified by these checks.
