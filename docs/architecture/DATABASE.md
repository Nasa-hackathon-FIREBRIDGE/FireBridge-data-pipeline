# FIREBRIDGE database dictionary

**Proposed schema v2 — October 24, 2026.** Generated from [schema.sql](schema.sql) and versioned column explanations. The 47 tables below specify each row's meaning, every column/type, required values, defaults, keys and constraints. No database has been created by this design.

Start with [the data-platform overview](DATA_PLATFORM.md), then [pipelines](PIPELINES.md) and [API contracts](API.md). Small operational and join tables are included in the full count; they are not separate services.

`uuid` is an application-generated ID. `timestamptz` is an absolute timestamp handled in UTC. `jsonb` fields must be validated against versioned Pydantic/JSON contracts. Geometry uses WGS84 longitude/latitude (SRID 4326), while metric areas are calculated in the documented equal-area projection. Null is unavailable/not-applicable. Required means NOT NULL or primary-key membership; conditional checks may impose additional requirements.

This is a schema for an empty development database, not an in-place migration from the previous draft. Use Alembic and data migration planning when an actual deployment exists. Large files/global rows remain outside PostgreSQL; serving completeness must be verified.

## 1. `sources`

One exact product / platform / collection / processing stream. A satellite with multiple products has multiple source rows.

| Column | SQL type | Required | Default / generation | Meaning |
|---|---|---|---|---|
| `id` | `text` | Yes | — | Unique row identifier. |
| `name` | `text` | Yes | — | Human-readable name. |
| `provider` | `text` | Yes | — | Organization/service that supplies the data or model. |
| `kind` | `text` | Yes | — | Data family: hotspots, masks, geolocation, land cover, imagery, weather or reports. |
| `platform` | `text` | No | — | Terra, Aqua, S-NPP, NOAA-20, NOAA-21, Landsat mission, or null for non-satellite sources. |
| `instrument` | `text` | No | — | MODIS, VIIRS, Landsat instrument, or null when not applicable. |
| `product` | `text` | Yes | — | Provider product identifier. |
| `collection` | `text` | Yes | — | Exact product collection/version; use an explicit documented not-applicable value if needed. |
| `processing_stream` | `text` | Yes | — | Standard, NRT, reanalysis, forecast, or another explicitly named source stream. |
| `documentation_url` | `text` | Yes | — | Official product or provider documentation link. |
| `citation` | `text` | Yes | — | Attribution/citation text to show in evidence and exports. |
| `license_info` | `text` | Yes | — | Applicable access/reuse terms and attribution requirements. |
| `native_resolution_m` | `double precision` | No | — | Documented nominal/native spatial scale in metres; does not guarantee event-location accuracy. |
| `schema_version` | `text` | Yes | — | Version of the data contract used to interpret this record. |
| `metadata` | `jsonb` | Yes | DEFAULT '{}' | Versioned source-specific metadata, including units and derivation where relevant. |

**Keys and value rules**

- `id`: `PRIMARY KEY`
- `kind`: `CHECK (kind IN ('hotspots', 'fire_mask', 'geolocation', 'land_cover', 'imagery', 'weather', 'news', 'incident_report'))`
- `native_resolution_m`: `CHECK (native_resolution_m > 0)`

## 2. `assets`

One immutable input file or API response revision. Store the bytes in file/object storage and their identity here.

| Column | SQL type | Required | Default / generation | Meaning |
|---|---|---|---|---|
| `id` | `uuid` | Yes | — | Unique row identifier. |
| `source_id` | `text` | Yes | — | FK to the exact product specification in sources. |
| `native_key` | `text` | Yes | — | Provider granule/filename/request identity, excluding secrets. |
| `revision` | `text` | Yes | — | Provider or locally assigned immutable content revision. |
| `source_url` | `text` | Yes | — | Original retrieval address; credentials must never be embedded. |
| `storage_uri` | `text` | Yes | — | Internal file/object address of preserved bytes. |
| `sha256` | `text` | Yes | — | SHA-256 digest of the immutable artifact or content named in this row. |
| `byte_size` | `bigint` | Yes | — | Byte count of preserved content. |
| `time_start` | `timestamptz` | No | — | UTC beginning of source observation coverage. |
| `time_end` | `timestamptz` | No | — | UTC end of source observation coverage. |
| `footprint` | `geometry(multipolygon, 4326)` | No | — | Actual spatial support when known; not an invented precise location. |
| `retrieved_at` | `timestamptz` | Yes | — | UTC timestamp when the source was fetched. |
| `validation_status` | `text` | Yes | — | Pending check, accepted input, or quarantined failure. |
| `metadata` | `jsonb` | Yes | DEFAULT '{}' | Versioned source-specific metadata, including units and derivation where relevant. |

**Keys and value rules**

- `id`: `PRIMARY KEY`
- `source_id`: `REFERENCES sources (id)`
- `sha256`: `CHECK (sha256 ~ '^[0-9a-f]{64}$')`
- `byte_size`: `CHECK (byte_size >= 0)`
- `validation_status`: `CHECK (validation_status IN ('pending', 'accepted', 'quarantined'))`
- `UNIQUE (source_id, native_key, revision, sha256)`
- `UNIQUE (id, source_id)`
- `CHECK (time_end IS NULL OR time_start IS NULL OR time_end >= time_start)`

## 3. `data_releases`

One frozen, publishable combination of inputs, code and scientific configuration.

| Column | SQL type | Required | Default / generation | Meaning |
|---|---|---|---|---|
| `id` | `uuid` | Yes | — | Unique row identifier. |
| `name` | `text` | Yes | — | Human-readable name. |
| `status` | `text` | Yes | — | Explicit lifecycle/result state; permitted values appear in the constraints below. |
| `stream` | `text` | Yes | — | Retrospective, provisional, or experiment; avoids silently mixing standard and NRT. |
| `code_version` | `text` | Yes | — | Reproducible code identifier: commit hash or saved source-bundle digest. |
| `config` | `jsonb` | Yes | — | Versioned machine-readable processing configuration. |
| `config_sha256` | `text` | Yes | — | Digest of canonicalized configuration. |
| `manifest_uri` | `text` | Yes | — | Location of the immutable input/output inventory. |
| `parent_release_id` | `uuid` | No | — | Previous snapshot from which unchanged partitions can be reused. |
| `dataset_kind` | `text` | Yes | — | Satellite, weather or report snapshot; components are pinned separately. |
| `scope_key` | `text` | Yes | — | Registered served geography/data scope, not an arbitrary user polygon. |
| `observation_cutoff` | `timestamptz` | Yes | — | Declared event-time cutoff for this snapshot; not proof of complete local observation coverage. Weather forecasts retain their own later valid times. |
| `validation_report_uri` | `text` | No | — | Publication gate results and inventory completeness evidence. |
| `created_at` | `timestamptz` | Yes | DEFAULT now() | UTC timestamp when this record was created. |
| `published_at` | `timestamptz` | No | — | UTC time of release publication, not a news publication time. |

**Keys and value rules**

- `id`: `PRIMARY KEY`
- `name`: `UNIQUE`
- `status`: `CHECK (status IN ('draft', 'validated', 'published', 'retired'))`
- `stream`: `CHECK (stream IN ('retrospective', 'provisional', 'experiment'))`
- `parent_release_id`: `REFERENCES data_releases (id)`
- `dataset_kind`: `CHECK (dataset_kind IN ('satellite', 'weather', 'reports'))`

## 4. `release_assets`

One input asset included in one release with a declared role.

| Column | SQL type | Required | Default / generation | Meaning |
|---|---|---|---|---|
| `release_id` | `uuid` | Yes | — | FK to the frozen dataset/configuration in data_releases. |
| `asset_id` | `uuid` | Yes | — | FK to the immutable input file/API response in assets. |
| `role` | `text` | Yes | — | Purpose of the linked asset in this context. |

**Keys and value rules**

- `release_id`: `REFERENCES data_releases (id)`
- `asset_id`: `REFERENCES assets (id)`
- `PRIMARY KEY (release_id, asset_id, role)`

## 5. `pipeline_runs`

One execution of a processing stage; supports retries and reproducibility.

| Column | SQL type | Required | Default / generation | Meaning |
|---|---|---|---|---|
| `id` | `uuid` | Yes | — | Unique row identifier. |
| `release_id` | `uuid` | No | — | Optional output release; early acquisition can run before a release exists. |
| `stage` | `text` | Yes | — | Named pipeline operation, such as decode_masks or build_calendar. |
| `idempotency_key` | `text` | Yes | — | Deterministic identity preventing duplicate processing requests. |
| `status` | `text` | Yes | — | Explicit lifecycle/result state; permitted values appear in the constraints below. |
| `code_version` | `text` | Yes | — | Reproducible code identifier: commit hash or saved source-bundle digest. |
| `config` | `jsonb` | Yes | — | Versioned machine-readable processing configuration. |
| `input_manifest_uri` | `text` | Yes | — | Manifest of exact input records/assets and their versions. |
| `output_manifest_uri` | `text` | No | — | Manifest of the outputs written by this processing run. |
| `started_at` | `timestamptz` | No | — | UTC processing start time. |
| `finished_at` | `timestamptz` | No | — | UTC processing finish time. |
| `error_code` | `text` | No | — | Machine-readable failure code; detailed redacted logs live separately. |
| `log_uri` | `text` | No | — | Location of redacted execution logs. |

**Keys and value rules**

- `id`: `PRIMARY KEY`
- `release_id`: `REFERENCES data_releases (id)`
- `idempotency_key`: `UNIQUE`
- `status`: `CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled'))`

## 6. `areas`

One immutable geographic selection or named AOI revision.

| Column | SQL type | Required | Default / generation | Meaning |
|---|---|---|---|---|
| `id` | `uuid` | Yes | — | Unique row identifier. |
| `name` | `text` | Yes | — | Human-readable name. |
| `version` | `text` | Yes | — | Immutable version identifier. |
| `geom` | `geometry(multipolygon, 4326)` | Yes | — | WGS84 geometry used for location/intersection queries; metric areas are calculated separately. |
| `geometry_sha256` | `text` | Yes | — | Digest of normalized geometry used for cache/version identity. |
| `display_timezone` | `text` | Yes | — | IANA civil display zone, e.g. Africa/Casablanca; not the raw data time basis. |
| `provenance` | `text` | Yes | — | Drawn polygon, reviewed boundary source, or other geometry provenance. |
| `created_at` | `timestamptz` | Yes | DEFAULT now() | UTC timestamp when this record was created. |

**Keys and value rules**

- `id`: `PRIMARY KEY`
- `UNIQUE (geometry_sha256, version)`
- `CHECK (st_isvalid(geom) AND NOT st_isempty(geom))`

## 7. `grids`

One fully specified analysis grid and land-mask version.

| Column | SQL type | Required | Default / generation | Meaning |
|---|---|---|---|---|
| `id` | `text` | Yes | — | Unique row identifier. |
| `version` | `text` | Yes | — | Immutable version identifier. |
| `projection_srid` | `integer` | Yes | — | Equal-area projection identifier; initial Morocco proposal is EPSG:6933. |
| `cell_size_m` | `double precision` | Yes | — | Proposed 5000 m initially; other grid sizes require separate versions. |
| `origin_x_m` | `double precision` | Yes | — | Fixed grid origin easting in the projected CRS. |
| `origin_y_m` | `double precision` | Yes | — | Fixed grid origin northing in the projected CRS. |
| `supported_extent` | `geometry(multipolygon, 4326)` | Yes | — | Documented geographic extent within which this grid/product is supported. |
| `land_mask_asset_id` | `uuid` | Yes | — | FK to the reviewed land mask input asset. |
| `construction_spec` | `jsonb` | Yes | — | Axis convention, rasterization, land-mask rules, CRS and nodata specification. |

**Keys and value rules**

- `id`: `PRIMARY KEY`
- `cell_size_m`: `CHECK (cell_size_m > 0)`
- `land_mask_asset_id`: `REFERENCES assets (id)`

## 8. `grid_cells`

One cell of an analysis grid. Area is calculated in its equal-area projection.

| Column | SQL type | Required | Default / generation | Meaning |
|---|---|---|---|---|
| `id` | `bigint` | Yes | GENERATED ALWAYS AS IDENTITY | Unique row identifier. Generated identity value. |
| `grid_id` | `text` | Yes | — | FK to the grid definition in grids. |
| `grid_x` | `integer` | Yes | — | Integer column index under the fixed grid origin. |
| `grid_y` | `integer` | Yes | — | Integer row index under the fixed grid origin. |
| `geom` | `geometry(multipolygon, 4326)` | Yes | — | WGS84 geometry used for location/intersection queries; metric areas are calculated separately. |
| `area_m2` | `double precision` | Yes | — | Total geometric cell area in square metres. |
| `land_area_m2` | `double precision` | Yes | — | Land portion of the cell in square metres. |

**Keys and value rules**

- `id`: `PRIMARY KEY`
- `grid_id`: `REFERENCES grids (id)`
- `area_m2`: `CHECK (area_m2 > 0)`
- `land_area_m2`: `CHECK (land_area_m2 >= 0 AND land_area_m2 <= area_m2)`
- `UNIQUE (grid_id, grid_x, grid_y)`

## 9. `area_cells`

One AOI/cell intersection under a weighting method; contains land-only overlap.

| Column | SQL type | Required | Default / generation | Meaning |
|---|---|---|---|---|
| `area_id` | `uuid` | Yes | — | FK to the immutable AOI revision in areas. |
| `cell_id` | `bigint` | Yes | — | FK to the analysis grid cell in grid_cells. |
| `overlap_land_area_m2` | `double precision` | Yes | — | Square metres of land shared by this AOI and cell; aggregation weight. |
| `weighting_version` | `text` | Yes | — | Version of clipping/land-area computation. |

**Keys and value rules**

- `area_id`: `REFERENCES areas (id)`
- `cell_id`: `REFERENCES grid_cells (id)`
- `overlap_land_area_m2`: `CHECK (overlap_land_area_m2 > 0)`
- `PRIMARY KEY (area_id, cell_id, weighting_version)`

## 10. `detections`

One native hotspot record in a canonical input asset. It is not a unique fire incident.

| Column | SQL type | Required | Default / generation | Meaning |
|---|---|---|---|---|
| `id` | `bigint` | Yes | GENERATED ALWAYS AS IDENTITY | Unique row identifier. Generated identity value. |
| `asset_id` | `uuid` | Yes | — | First canonical input asset for this record; later sightings remain in fetch/input manifests. |
| `source_id` | `text` | Yes | — | Exact normalized platform/product source. A combined MODIS asset can contain both Terra and Aqua sources. |
| `native_record_key` | `text` | Yes | — | Stable row/pixel identity within the preserved asset. |
| `record_sha256` | `text` | Yes | — | Hash of canonical native record content plus source/identity rules; deduplicates repeated unchanged API rows across files. |
| `identity_key` | `text` | No | — | Stable native pixel/granule identity if available; null if a defensible identity is unavailable. |
| `identity_method` | `text` | Yes | — | Exact version of native-key or canonical-row hashing; never rounded-location fuzzy deduplication. |
| `processing_level` | `text` | Yes | — | Standard, NRT, RT, URT or unknown from the actual record; feed name alone is insufficient. |
| `acquired_at` | `timestamptz` | Yes | — | Actual UTC acquisition timestamp. |
| `geom` | `geometry(point, 4326)` | Yes | — | WGS84 geometry used for location/intersection queries; metric areas are calculated separately. |
| `confidence_raw` | `text` | No | — | Unchanged native numeric/category confidence stored as text. |
| `confidence_scheme` | `text` | Yes | — | Product-specific confidence definition; not a universal probability. |
| `type_raw` | `text` | No | — | Native thermal-source classification, null when unavailable. |
| `day_night` | `text` | No | — | Native day/night flag mapped to a documented enum. |
| `frp_mw` | `double precision` | No | — | Fire radiative power in megawatts; zero may be valid and flagged. |
| `brightness_bands` | `jsonb` | Yes | DEFAULT '{}' | Array/object recording exact band, brightness-temperature value and unit; no cross-band equivalence assumed. |
| `scan_km` | `double precision` | No | — | Footprint width only where documented in km; null for incompatible native fields. |
| `track_km` | `double precision` | No | — | Footprint length only where documented in km. |
| `cross_track_sample` | `integer` | No | — | Native sample index where supplied; do not substitute it for kilometres. |
| `native_fields` | `jsonb` | Yes | DEFAULT '{}' | Remaining original fields and record locator, retained for auditing. |

**Keys and value rules**

- `id`: `PRIMARY KEY`
- `record_sha256`: `CHECK (record_sha256 ~ '^[0-9a-f]{64}$')`
- `processing_level`: `CHECK (processing_level IN ('standard', 'nrt', 'rt', 'urt', 'unknown'))`
- `day_night`: `CHECK (day_night IN ('day', 'night', 'unknown'))`
- `frp_mw`: `CHECK (frp_mw >= 0 AND frp_mw < CAST('Infinity' AS double precision))`
- `scan_km`: `CHECK (scan_km > 0)`
- `track_km`: `CHECK (track_km > 0)`
- `FOREIGN KEY (asset_id) REFERENCES assets (id)`
- `FOREIGN KEY (source_id) REFERENCES sources (id)`
- `UNIQUE (asset_id, native_record_key)`
- `UNIQUE (source_id, record_sha256)`

## 11. `observations`

One analysis cell × source product × satellite pass × QA policy in a data release.

| Column | SQL type | Required | Default / generation | Meaning |
|---|---|---|---|---|
| `id` | `uuid` | Yes | — | Unique row identifier. |
| `release_id` | `uuid` | Yes | — | FK to the frozen dataset/configuration in data_releases. |
| `cell_id` | `bigint` | Yes | — | FK to the analysis grid cell in grid_cells. |
| `source_id` | `text` | Yes | — | FK to the exact product specification in sources. |
| `pass_key` | `text` | Yes | — | Deterministic platform overpass identity after granule-overlap handling. |
| `time_start` | `timestamptz` | Yes | — | UTC beginning of source observation coverage. |
| `time_end` | `timestamptz` | Yes | — | UTC end of source observation coverage. |
| `representative_time` | `timestamptz` | Yes | — | Documented representative actual acquisition time inside this cell/pass interval. |
| `local_solar_date` | `date` | Yes | — | Cell-centre approximate local solar date under the release policy. |
| `regime` | `text` | Yes | — | Declared observation regime, such as afternoon_day or morning_day. |
| `land_area_m2` | `double precision` | Yes | — | Cell land support used by this QA computation. |
| `usable_land_m2` | `double precision` | No | — | Usable observed land, square metres. |
| `cloud_land_m2` | `double precision` | No | — | Cloud/obscured land under the product-specific decoder. |
| `invalid_land_m2` | `double precision` | No | — | Observed but invalid/unprocessed land. |
| `unobserved_land_m2` | `double precision` | No | — | Land outside the available observation support. |
| `usable_support_uri` | `text` | No | — | Exact geolocated usable mask/geometry needed to intersect two observations. |
| `detection_links_uri` | `text` | No | — | Versioned mapping from contributing raw record IDs to retained/excluded detections and reasons. |
| `coverage_status` | `text` | Yes | — | Usable, insufficient, missing input or outside swath. |
| `retained_detection_count` | `integer` | No | — | Retained detections on usable support; may be null if not computable. |
| `retained_any` | `boolean` | No | — | Defined cell/pass response; null when ineligible, false only for a valid negative. |
| `eligible` | `boolean` | Yes | — | Whether this opportunity meets the declared QA rules. |
| `exclusion_reasons` | `jsonb` | Yes | DEFAULT '[]' | Structured reason codes for rejected or incomplete opportunities. |
| `qa_policy_version` | `text` | Yes | — | Decoder, confidence, geometry and eligibility policy version. |
| `geometry_summary` | `jsonb` | Yes | DEFAULT '{}' | Source viewing/solar geometry summaries with units and methods. |

**Keys and value rules**

- `id`: `PRIMARY KEY`
- `release_id`: `REFERENCES data_releases (id)`
- `cell_id`: `REFERENCES grid_cells (id)`
- `source_id`: `REFERENCES sources (id)`
- `land_area_m2`: `CHECK (land_area_m2 > 0)`
- `usable_land_m2`: `CHECK (usable_land_m2 >= 0 AND usable_land_m2 <= land_area_m2)`
- `cloud_land_m2`: `CHECK (cloud_land_m2 >= 0 AND cloud_land_m2 <= land_area_m2)`
- `invalid_land_m2`: `CHECK (invalid_land_m2 >= 0 AND invalid_land_m2 <= land_area_m2)`
- `unobserved_land_m2`: `CHECK (unobserved_land_m2 >= 0 AND unobserved_land_m2 <= land_area_m2)`
- `coverage_status`: `CHECK (coverage_status IN ('usable', 'insufficient', 'missing_input', 'outside_swath'))`
- `retained_detection_count`: `CHECK (retained_detection_count >= 0)`
- `UNIQUE (release_id, cell_id, source_id, pass_key, qa_policy_version)`
- `UNIQUE (id, release_id, cell_id)`
- `CHECK (time_end >= time_start AND representative_time BETWEEN time_start AND time_end)`
- `CHECK ((eligible AND coverage_status = 'usable' AND retained_any IS NOT NULL AND retained_detection_count IS NOT NULL AND usable_support_uri IS NOT NULL AND usable_land_m2 IS NOT NULL AND cloud_land_m2 IS NOT NULL AND invalid_land_m2 IS NOT NULL AND unobserved_land_m2 IS NOT NULL) OR (NOT eligible AND retained_any IS NULL))`
- `CHECK (retained_any IS NULL OR retained_any = (retained_detection_count > 0))`

## 12. `observation_assets`

One source-file link used to derive an observation, including non-detection support.

| Column | SQL type | Required | Default / generation | Meaning |
|---|---|---|---|---|
| `observation_id` | `uuid` | Yes | — | FK to the source cell/pass observation. |
| `asset_id` | `uuid` | Yes | — | FK to the immutable input file/API response in assets. |
| `role` | `text` | Yes | — | Purpose of the linked asset in this context. |

**Keys and value rules**

- `observation_id`: `REFERENCES observations (id)`
- `asset_id`: `REFERENCES assets (id)`
- `role`: `CHECK (role IN ('fire_mask', 'geolocation', 'hotspots', 'land_mask'))`
- `PRIMARY KEY (observation_id, asset_id, role)`

## 13. `matched_pairs`

One source/reference observation pair on the same cell and shared usable land, under a pairing series.

| Column | SQL type | Required | Default / generation | Meaning |
|---|---|---|---|---|
| `id` | `uuid` | Yes | — | Unique row identifier. |
| `release_id` | `uuid` | Yes | — | FK to the frozen dataset/configuration in data_releases. |
| `cell_id` | `bigint` | Yes | — | FK to the analysis grid cell in grid_cells. |
| `series_key` | `text` | Yes | — | Identity of source/reference products, regime and matching-policy version. |
| `reference_observation_id` | `uuid` | Yes | — | FK to the reference cell/pass; initially Aqua. |
| `source_observation_id` | `uuid` | Yes | — | FK to the paired source cell/pass; initially S-NPP. |
| `time_delta_seconds` | `integer` | Yes | — | Absolute time separation used for the pairing eligibility rule. |
| `shared_usable_land_m2` | `double precision` | Yes | — | Area of intersection of both usable land masks. |
| `shared_usable_fraction` | `double precision` | Yes | — | Shared usable land divided by declared cell land area, 0–1. |
| `shared_support_uri` | `text` | Yes | — | Geometry/mask of the actual shared support, not merely its area. |
| `eligible` | `boolean` | Yes | — | Whether the pair meets all frozen comparison gates. |
| `reference_target` | `boolean` | No | — | Reference retained-any detection on shared support; null for excluded pairs. |
| `source_any_on_shared_support` | `boolean` | No | — | Common-grid baseline response, calculated on the same shared support. |
| `split_name` | `text` | No | — | Frozen train, development, calibration, temporal test, spatial test or excluded assignment. |
| `block_id` | `text` | No | — | Spatial/temporal leakage-control block identifier. |
| `episode_group_id` | `text` | No | — | Group tying neighboring observations of the same likely episode together. |
| `exclusion_reasons` | `jsonb` | Yes | DEFAULT '[]' | Structured reason codes for rejected or incomplete opportunities. |

**Keys and value rules**

- `id`: `PRIMARY KEY`
- `release_id`: `REFERENCES data_releases (id)`
- `cell_id`: `REFERENCES grid_cells (id)`
- `time_delta_seconds`: `CHECK (time_delta_seconds >= 0)`
- `shared_usable_land_m2`: `CHECK (shared_usable_land_m2 >= 0)`
- `shared_usable_fraction`: `CHECK (shared_usable_fraction BETWEEN 0 AND 1)`
- `split_name`: `CHECK (split_name IN ('train', 'development', 'calibration', 'temporal_test', 'spatial_test', 'excluded'))`
- `FOREIGN KEY (reference_observation_id, release_id, cell_id) REFERENCES observations (id, release_id, cell_id)`
- `FOREIGN KEY (source_observation_id, release_id, cell_id) REFERENCES observations (id, release_id, cell_id)`
- `UNIQUE (release_id, series_key, reference_observation_id)`
- `UNIQUE (release_id, series_key, source_observation_id)`
- `CHECK (reference_observation_id <> source_observation_id)`
- `CHECK ((eligible AND reference_target IS NOT NULL AND source_any_on_shared_support IS NOT NULL AND split_name IS NOT NULL AND block_id IS NOT NULL) OR (NOT eligible AND reference_target IS NULL))`

## 14. `feature_sets`

One frozen feature dataset and split manifest. Actual feature rows live in Parquet.

| Column | SQL type | Required | Default / generation | Meaning |
|---|---|---|---|---|
| `id` | `uuid` | Yes | — | Unique row identifier. |
| `release_id` | `uuid` | Yes | — | FK to the frozen dataset/configuration in data_releases. |
| `version` | `text` | Yes | — | Immutable version identifier. |
| `artifact_uri` | `text` | Yes | — | File/object-storage location of the immutable dataset or model. |
| `sha256` | `text` | Yes | — | SHA-256 digest of the immutable artifact or content named in this row. |
| `feature_contract` | `jsonb` | Yes | — | Predictor names, units, derivations, missing-value policy and serving availability. |
| `split_manifest_uri` | `text` | Yes | — | Immutable membership of temporal/geographic train/dev/calibration/test groups. |
| `split_sha256` | `text` | Yes | — | Digest of the frozen split manifest. |
| `row_count` | `bigint` | Yes | — | Number of feature rows in the artifact. |
| `created_at` | `timestamptz` | Yes | DEFAULT now() | UTC timestamp when this record was created. |

**Keys and value rules**

- `id`: `PRIMARY KEY`
- `release_id`: `REFERENCES data_releases (id)`
- `row_count`: `CHECK (row_count >= 0)`

## 15. `model_versions`

One fitted model version for a declared source-to-reference response and support domain.

| Column | SQL type | Required | Default / generation | Meaning |
|---|---|---|---|---|
| `id` | `uuid` | Yes | — | Unique row identifier. |
| `name` | `text` | Yes | — | Human-readable name. |
| `version` | `text` | Yes | — | Immutable version identifier. |
| `feature_set_id` | `uuid` | Yes | — | FK to training features and frozen split definitions. |
| `source_id` | `text` | Yes | — | FK to the exact product specification in sources. |
| `reference_source_id` | `text` | Yes | — | FK to the exact target reference product. |
| `algorithm` | `text` | Yes | — | Baseline/logistic/boosted-tree algorithm and implementation identity. |
| `artifact_uri` | `text` | Yes | — | File/object-storage location of the immutable dataset or model. |
| `sha256` | `text` | Yes | — | SHA-256 digest of the immutable artifact or content named in this row. |
| `target_definition` | `jsonb` | Yes | — | Precise response, regime, grid, confidence rule and shared-support definition. |
| `support_domain` | `jsonb` | Yes | — | Validated geography, seasons, streams, coverage and feature-domain limits. |
| `calibration_manifest_uri` | `text` | Yes | — | Probability calibration procedure, artifact and disjoint calibration set. |
| `status` | `text` | Yes | — | Explicit lifecycle/result state; permitted values appear in the constraints below. |
| `created_at` | `timestamptz` | Yes | DEFAULT now() | UTC timestamp when this record was created. |

**Keys and value rules**

- `id`: `PRIMARY KEY`
- `feature_set_id`: `REFERENCES feature_sets (id)`
- `source_id`: `REFERENCES sources (id)`
- `reference_source_id`: `REFERENCES sources (id)`
- `status`: `CHECK (status IN ('candidate', 'validated', 'rejected', 'retired'))`
- `UNIQUE (name, version)`

## 16. `evaluations`

One model × release × experiment × evaluation slice.

| Column | SQL type | Required | Default / generation | Meaning |
|---|---|---|---|---|
| `id` | `uuid` | Yes | — | Unique row identifier. |
| `model_id` | `uuid` | Yes | — | FK to the fitted model version. |
| `release_id` | `uuid` | Yes | — | FK to the frozen dataset/configuration in data_releases. |
| `experiment` | `text` | Yes | — | Temporal holdout, geographic holdout, withheld-Aqua replay, sensitivity, etc. |
| `slice_key` | `text` | Yes | — | Evaluation subset, e.g. land cover/region/platform. |
| `split_manifest_uri` | `text` | Yes | — | Immutable membership of temporal/geographic train/dev/calibration/test groups. |
| `sample_count` | `bigint` | Yes | — | Eligible evaluated opportunities. |
| `positive_count` | `bigint` | Yes | — | Positive reference responses among those opportunities. |
| `independent_block_count` | `integer` | Yes | — | Independent blocks/episodes supporting the reported score. |
| `metrics` | `jsonb` | Yes | — | Defined metrics with units, null handling and uncertainty where computed. |
| `baseline_metrics` | `jsonb` | Yes | — | Metrics for an appropriate baseline on exactly the same evaluated support. |
| `uncertainty_method` | `text` | No | — | Block bootstrap, empirical error range, or explicitly not estimated. |
| `report_uri` | `text` | Yes | — | Location of the reproducible evaluation report. |

**Keys and value rules**

- `id`: `PRIMARY KEY`
- `model_id`: `REFERENCES model_versions (id)`
- `release_id`: `REFERENCES data_releases (id)`
- `sample_count`: `CHECK (sample_count >= 0)`
- `positive_count`: `CHECK (positive_count BETWEEN 0 AND sample_count)`
- `independent_block_count`: `CHECK (independent_block_count >= 0)`
- `UNIQUE (model_id, release_id, experiment, slice_key)`

## 17. `predictions`

One model result for one source observation; unsupported results have null probability.

| Column | SQL type | Required | Default / generation | Meaning |
|---|---|---|---|---|
| `id` | `uuid` | Yes | — | Unique row identifier. |
| `release_id` | `uuid` | Yes | — | FK to the frozen dataset/configuration in data_releases. |
| `cell_id` | `bigint` | Yes | — | FK to the analysis grid cell in grid_cells. |
| `observation_id` | `uuid` | Yes | — | FK to the source cell/pass observation. |
| `model_id` | `uuid` | Yes | — | FK to the fitted model version. |
| `response_probability` | `double precision` | No | — | Estimated reference retained-detection response, 0–1; not probability of a real fire. |
| `status` | `text` | Yes | — | Explicit lifecycle/result state; permitted values appear in the constraints below. |
| `support_reasons` | `jsonb` | Yes | DEFAULT '[]' | Domain checks and unsupported reasons. |
| `features_uri` | `text` | Yes | — | Exact feature row used for this prediction. |
| `uncertainty` | `jsonb` | No | — | Documented empirical uncertainty information and method, or null when not estimated. |

**Keys and value rules**

- `id`: `PRIMARY KEY`
- `release_id`: `REFERENCES data_releases (id)`
- `cell_id`: `REFERENCES grid_cells (id)`
- `model_id`: `REFERENCES model_versions (id)`
- `response_probability`: `CHECK (response_probability BETWEEN 0 AND 1)`
- `status`: `CHECK (status IN ('supported', 'unsupported', 'failed'))`
- `FOREIGN KEY (observation_id, release_id, cell_id) REFERENCES observations (id, release_id, cell_id)`
- `UNIQUE (observation_id, model_id)`
- `UNIQUE (id, release_id, cell_id)`
- `CHECK ((status = 'supported' AND response_probability IS NOT NULL) OR (status <> 'supported' AND response_probability IS NULL))`

## 18. `daily_activity`

One cell/day/metric/policy in a release, including unsupported or missing cell-days.

| Column | SQL type | Required | Default / generation | Meaning |
|---|---|---|---|---|
| `release_id` | `uuid` | Yes | — | FK to the frozen dataset/configuration in data_releases. |
| `cell_id` | `bigint` | Yes | — | FK to the analysis grid cell in grid_cells. |
| `reporting_date` | `date` | Yes | — | Cell reporting day under the declared time basis. |
| `time_basis` | `text` | Yes | — | Versioned UTC/solar/civil-day policy; initial comparable product uses local solar day. |
| `metric_key` | `text` | Yes | — | Versioned response definition, e.g. aqua_equivalent_active_cell_v1. |
| `selection_policy` | `text` | Yes | — | Fixed eligible-source/pass priority; does not maximize fire response. |
| `observation_id` | `uuid` | No | — | FK to the source cell/pass observation. |
| `prediction_id` | `uuid` | No | — | FK to the selected prediction for an inferred response; null for direct reference. |
| `response_value` | `double precision` | No | — | Observed 0/1 or supported model probability; null for unavailable states. |
| `status` | `text` | Yes | — | Explicit lifecycle/result state; permitted values appear in the constraints below. |
| `candidate_count` | `integer` | Yes | — | Number of opportunities considered before deterministic selection. |
| `reasons` | `jsonb` | Yes | DEFAULT '[]' | Structured quality/support explanations for the result. |

**Keys and value rules**

- `release_id`: `REFERENCES data_releases (id)`
- `cell_id`: `REFERENCES grid_cells (id)`
- `response_value`: `CHECK (response_value BETWEEN 0 AND 1)`
- `status`: `CHECK (status IN ('reference_observed', 'source_estimated', 'insufficient_coverage', 'unsupported_model', 'missing_data'))`
- `candidate_count`: `CHECK (candidate_count >= 0)`
- `PRIMARY KEY (release_id, cell_id, reporting_date, time_basis, metric_key, selection_policy)`
- `FOREIGN KEY (observation_id, release_id, cell_id) REFERENCES observations (id, release_id, cell_id)`
- `FOREIGN KEY (prediction_id, release_id, cell_id) REFERENCES predictions (id, release_id, cell_id)`
- `CHECK ((status = 'reference_observed' AND observation_id IS NOT NULL AND prediction_id IS NULL AND response_value IS NOT NULL AND response_value IN (0, 1)) OR (status = 'source_estimated' AND observation_id IS NOT NULL AND prediction_id IS NOT NULL AND response_value IS NOT NULL) OR (status IN ('insufficient_coverage', 'unsupported_model', 'missing_data') AND response_value IS NULL AND prediction_id IS NULL))`
- `FOREIGN KEY (metric_key) REFERENCES metric_definitions (id)`

## 19. `analyses`

One immutable user selection and analysis configuration, with job/cache state.

| Column | SQL type | Required | Default / generation | Meaning |
|---|---|---|---|---|
| `id` | `uuid` | Yes | — | Unique row identifier. |
| `area_id` | `uuid` | Yes | — | FK to the immutable AOI revision in areas. |
| `release_id` | `uuid` | Yes | — | FK to the frozen dataset/configuration in data_releases. |
| `start_date` | `date` | Yes | — | Inclusive selected reporting date. |
| `end_date_exclusive` | `date` | Yes | — | Exclusive selected reporting date. |
| `time_basis` | `text` | Yes | — | Reporting-day definition shared by relevant outputs. |
| `metric_key` | `text` | Yes | — | Exact requested response definition. |
| `grid_id` | `text` | No | — | Analysis grid for comparable metrics; null is allowed for a native-detection-only request. |
| `selection_policy` | `text` | Yes | — | Daily pass/source selection policy version. |
| `weighting_version` | `text` | Yes | — | AOI intersection-weight version to use. |
| `baseline_spec` | `jsonb` | No | — | Frozen baseline years/season/support rules, or null if unavailable. |
| `weather_policy` | `jsonb` | Yes | — | Selected source models, variables, dates, weighting and freshness policy. |
| `news_policy` | `jsonb` | Yes | — | Date-aware discovery, review and source-matching policy. |
| `request_spec` | `jsonb` | Yes | — | Canonical request including source IDs, data mode, baseline/filter versions, authorization scope and component choices. |
| `cache_key` | `text` | Yes | — | Hash of all immutable inputs/settings that determine the result. |
| `status` | `text` | Yes | — | Explicit lifecycle/result state; permitted values appear in the constraints below. |
| `error_code` | `text` | No | — | Machine-readable failure code; detailed redacted logs live separately. |
| `created_at` | `timestamptz` | Yes | DEFAULT now() | UTC timestamp when this record was created. |
| `completed_at` | `timestamptz` | No | — | UTC timestamp when processing completed; null while pending. |

**Keys and value rules**

- `id`: `PRIMARY KEY`
- `area_id`: `REFERENCES areas (id)`
- `release_id`: `REFERENCES data_releases (id)`
- `grid_id`: `REFERENCES grids (id)`
- `cache_key`: `UNIQUE`
- `status`: `CHECK (status IN ('queued', 'running', 'ready', 'partial', 'unsupported', 'failed'))`
- `CHECK (end_date_exclusive > start_date)`
- `FOREIGN KEY (metric_key) REFERENCES metric_definitions (id)`

## 20. `calendar_periods`

One reporting period within a saved analysis; stores numerator and denominator explicitly.

| Column | SQL type | Required | Default / generation | Meaning |
|---|---|---|---|---|
| `analysis_id` | `uuid` | Yes | — | FK to the saved user selection in analyses. |
| `period_start` | `date` | Yes | — | Inclusive beginning of the reporting period. |
| `period_end_exclusive` | `date` | Yes | — | Exclusive end date of the period. |
| `resolution` | `text` | Yes | — | Day, week, month or full selection. |
| `response_numerator_m2_days` | `double precision` | Yes | — | Sum of eligible AOI land weights times daily response; not burned area. |
| `eligible_land_m2_days` | `double precision` | Yes | — | Eligible AOI land-area-days; denominator of the comparable response. |
| `possible_land_m2_days` | `double precision` | Yes | — | Total AOI land area times reporting days; coverage denominator. |
| `response_value` | `double precision` | No | GENERATED ALWAYS AS (response_numerator_m2_days / NULLIF(eligible_land_m2_days, 0)) STORED | Generated numerator / eligible denominator; null at zero eligible support. Calculated by PostgreSQL. |
| `coverage_fraction` | `double precision` | No | GENERATED ALWAYS AS (eligible_land_m2_days / possible_land_m2_days) STORED | Generated eligible / possible area-days, 0–1. Calculated by PostgreSQL. |
| `observed_weight_fraction` | `double precision` | No | — | Eligible weight contributed by directly observed reference, versus estimated source. |
| `valid_cell_days` | `bigint` | Yes | — | Eligible cell-days contributing to the period. |
| `baseline_year_count` | `integer` | Yes | DEFAULT 0 | Number of supported comparable historical years; zero when no baseline. |
| `seasonal_percentile` | `double precision` | No | — | Baseline percentile only after the minimum-baseline policy passes. |
| `uncertainty` | `jsonb` | No | — | Documented empirical uncertainty information and method, or null when not estimated. |
| `status` | `text` | Yes | — | Explicit lifecycle/result state; permitted values appear in the constraints below. |
| `reasons` | `jsonb` | Yes | DEFAULT '[]' | Structured quality/support explanations for the result. |

**Keys and value rules**

- `analysis_id`: `REFERENCES analyses (id)`
- `resolution`: `CHECK (resolution IN ('day', 'week', 'month', 'selection'))`
- `response_numerator_m2_days`: `CHECK (response_numerator_m2_days >= 0)`
- `eligible_land_m2_days`: `CHECK (eligible_land_m2_days >= 0)`
- `possible_land_m2_days`: `CHECK (possible_land_m2_days > 0)`
- `observed_weight_fraction`: `CHECK (observed_weight_fraction BETWEEN 0 AND 1)`
- `valid_cell_days`: `CHECK (valid_cell_days >= 0)`
- `baseline_year_count`: `CHECK (baseline_year_count >= 0)`
- `seasonal_percentile`: `CHECK (seasonal_percentile BETWEEN 0 AND 100)`
- `status`: `CHECK (status IN ('supported', 'limited', 'unsupported'))`
- `PRIMARY KEY (analysis_id, period_start, resolution)`
- `CHECK (period_end_exclusive > period_start)`
- `CHECK (response_numerator_m2_days <= eligible_land_m2_days AND eligible_land_m2_days <= possible_land_m2_days)`
- `CHECK (baseline_year_count > 0 OR seasonal_percentile IS NULL)`

## 21. `weather_locations`

One native weather grid cell, station or declared sampling point.

| Column | SQL type | Required | Default / generation | Meaning |
|---|---|---|---|---|
| `id` | `uuid` | Yes | — | Unique row identifier. |
| `source_id` | `text` | Yes | — | FK to the exact product specification in sources. |
| `native_location_key` | `text` | Yes | — | Stable source grid-cell or station identity; preserve returned coordinates. |
| `support_kind` | `text` | Yes | — | Native grid cell, station, or explicitly sampled point. |
| `geom` | `geometry(point, 4326)` | Yes | — | WGS84 geometry used for location/intersection queries; metric areas are calculated separately. |
| `footprint` | `geometry(multipolygon, 4326)` | No | — | Actual spatial support when known; not an invented precise location. |
| `elevation_m` | `double precision` | No | — | Provider/model elevation in metres, with metadata for any adjustment. |
| `native_resolution_m` | `double precision` | No | — | Documented nominal/native spatial scale in metres; does not guarantee event-location accuracy. |
| `metadata` | `jsonb` | Yes | DEFAULT '{}' | Versioned source-specific metadata, including units and derivation where relevant. |

**Keys and value rules**

- `id`: `PRIMARY KEY`
- `source_id`: `REFERENCES sources (id)`
- `support_kind`: `CHECK (support_kind IN ('grid_cell', 'station', 'sample_point'))`
- `UNIQUE (source_id, native_location_key)`
- `UNIQUE (id, source_id)`

## 22. `weather_values`

One weather variable/location/interval from a particular input asset revision.

| Column | SQL type | Required | Default / generation | Meaning |
|---|---|---|---|---|
| `id` | `bigint` | Yes | GENERATED ALWAYS AS IDENTITY | Unique row identifier. Generated identity value. |
| `location_id` | `uuid` | Yes | — | FK to the native weather location or sampling point. |
| `source_id` | `text` | Yes | — | FK to the exact product specification in sources. |
| `asset_id` | `uuid` | Yes | — | FK to the immutable input file/API response in assets. |
| `variable` | `text` | Yes | — | Canonical variable name, including height/depth where relevant. |
| `unit` | `text` | Yes | — | Explicit normalized unit for this variable/statistic. |
| `valid_start` | `timestamptz` | Yes | — | UTC start of the measurement/aggregation interval. |
| `valid_end` | `timestamptz` | Yes | — | UTC end; may equal start for instantaneous values. |
| `issued_at` | `timestamptz` | No | — | Forecast model-run issue time; required for forecasts. |
| `available_at` | `timestamptz` | No | — | When this value was actually available, if known; needed for historical real-time replay. |
| `data_kind` | `text` | Yes | — | Reanalysis, forecast, model_current or station_observation. Model current values are not station measurements. |
| `statistic` | `text` | Yes | — | How the value relates to its interval: instant, sum, mean, etc. |
| `value` | `double precision` | No | — | Numeric value in the declared unit; null represents unavailable/invalid data. |
| `quality_status` | `text` | Yes | — | Valid value, missing input, or rejected value. |
| `derivation` | `jsonb` | Yes | DEFAULT '{}' | Native unit, conversion, de-accumulation, model and original record locator. |

**Keys and value rules**

- `id`: `PRIMARY KEY`
- `data_kind`: `CHECK (data_kind IN ('reanalysis', 'forecast', 'model_current', 'station_observation'))`
- `statistic`: `CHECK (statistic IN ('instant', 'mean', 'maximum', 'minimum', 'interval_sum'))`
- `quality_status`: `CHECK (quality_status IN ('valid', 'missing', 'invalid'))`
- `FOREIGN KEY (location_id, source_id) REFERENCES weather_locations (id, source_id)`
- `FOREIGN KEY (asset_id, source_id) REFERENCES assets (id, source_id)`
- `UNIQUE (asset_id, location_id, variable, valid_start, valid_end)`
- `CHECK (valid_end >= valid_start)`
- `CHECK (data_kind <> 'forecast' OR issued_at IS NOT NULL)`
- `CHECK ((quality_status = 'valid' AND value IS NOT NULL AND value > CAST('-Infinity' AS double precision) AND value < CAST('Infinity' AS double precision)) OR (quality_status <> 'valid' AND value IS NULL))`

## 23. `weather_summaries`

One area/period/variable/source statistic within a saved analysis.

| Column | SQL type | Required | Default / generation | Meaning |
|---|---|---|---|---|
| `id` | `uuid` | Yes | — | Unique row identifier. |
| `analysis_id` | `uuid` | Yes | — | FK to the saved user selection in analyses. |
| `source_id` | `text` | Yes | — | FK to the exact product specification in sources. |
| `variable` | `text` | Yes | — | Canonical variable name, including height/depth where relevant. |
| `unit` | `text` | Yes | — | Explicit normalized unit for this variable/statistic. |
| `period_start` | `timestamptz` | Yes | — | Inclusive beginning of the reporting period. |
| `period_end` | `timestamptz` | Yes | — | Exclusive end of the reporting period. |
| `statistic` | `text` | Yes | — | How the value relates to its interval: instant, sum, mean, etc. |
| `value` | `double precision` | No | — | Numeric value in the declared unit; null represents unavailable/invalid data. |
| `spatial_method` | `text` | Yes | — | Area-weighted native-grid statistic or explicitly labelled sample-point context. |
| `spatial_weights_uri` | `text` | Yes | — | Versioned weights/locations used for the AOI, including coverage geometry. |
| `input_manifest_uri` | `text` | Yes | — | Manifest of exact input records/assets and their versions. |
| `temporal_coverage_fraction` | `double precision` | Yes | — | Fraction of required time support with valid values, 0–1. |
| `spatial_coverage_fraction` | `double precision` | Yes | — | Fraction of required spatial support represented, 0–1. |
| `status` | `text` | Yes | — | Explicit lifecycle/result state; permitted values appear in the constraints below. |
| `reasons` | `jsonb` | Yes | DEFAULT '[]' | Structured quality/support explanations for the result. |

**Keys and value rules**

- `id`: `PRIMARY KEY`
- `analysis_id`: `REFERENCES analyses (id)`
- `source_id`: `REFERENCES sources (id)`
- `temporal_coverage_fraction`: `CHECK (temporal_coverage_fraction BETWEEN 0 AND 1)`
- `spatial_coverage_fraction`: `CHECK (spatial_coverage_fraction BETWEEN 0 AND 1)`
- `status`: `CHECK (status IN ('supported', 'limited', 'missing'))`
- `UNIQUE (analysis_id, source_id, variable, period_start, period_end, statistic)`
- `CHECK (period_end > period_start)`
- `CHECK (status <> 'missing' OR value IS NULL)`

## 24. `news_reports`

One retrieved document revision and extraction version, separate from events it describes.

| Column | SQL type | Required | Default / generation | Meaning |
|---|---|---|---|---|
| `id` | `uuid` | Yes | — | Unique row identifier. |
| `asset_id` | `uuid` | Yes | — | FK to the immutable input file/API response in assets. |
| `canonical_url` | `text` | Yes | — | Normalized publisher link, excluding tracking parameters. |
| `title` | `text` | Yes | — | Document headline; untrusted source text, not an instruction. |
| `publisher` | `text` | Yes | — | Originating publisher/agency. |
| `language` | `text` | Yes | — | Language code, initially en/fr, optionally ar. |
| `published_at` | `timestamptz` | No | — | UTC publication timestamp if known; preserve its precision. |
| `publication_precision` | `text` | Yes | — | Precision of publication time; preserve day-only or unknown timestamps. |
| `retrieved_at` | `timestamptz` | Yes | — | UTC timestamp when the source was fetched. |
| `content_sha256` | `text` | Yes | — | Digest identifying the retrieved document version. |
| `summary` | `text` | No | — | Short permitted synopsis, not a copied full article. |
| `original_reporting_url` | `text` | No | — | Original reporting link when this article is a republication. |
| `syndication_group` | `text` | No | — | Shared reporting lineage used to avoid counting copies as independent evidence. |
| `source_lineage` | `text` | Yes | — | Whether the report is field-based, official, satellite-derived, mixed or unknown. |
| `extraction_version` | `text` | Yes | — | Version of extraction code/prompt. |
| `review_status` | `text` | Yes | — | Whether a human checked the extraction or rejected it. |

**Keys and value rules**

- `id`: `PRIMARY KEY`
- `asset_id`: `REFERENCES assets (id)`
- `source_lineage`: `CHECK (source_lineage IN ('field_report', 'official_incident', 'satellite_derived', 'mixed', 'unknown'))`
- `review_status`: `CHECK (review_status IN ('unreviewed', 'reviewed', 'rejected'))`
- `UNIQUE (canonical_url, content_sha256, extraction_version)`

## 25. `reported_events`

One event claim extracted from a report. Different reports may describe the same event.

| Column | SQL type | Required | Default / generation | Meaning |
|---|---|---|---|---|
| `id` | `uuid` | Yes | — | Unique row identifier. |
| `report_id` | `uuid` | Yes | — | FK to the exact document/extraction revision. |
| `claim_index` | `integer` | Yes | — | Stable event-claim position within that report. |
| `event_start` | `date` | No | — | Earliest supported event date, not the publication date. |
| `event_end_exclusive` | `date` | No | — | Exclusive end of the supported event-date interval. |
| `date_precision` | `text` | Yes | — | Precision of the reported event date: day, interval, month, unknown, etc. |
| `place_text` | `text` | No | — | Original place description in the report. |
| `location` | `geometry(geometry, 4326)` | No | — | Point or region representing the report’s actual geographic precision. |
| `location_precision` | `text` | Yes | — | Exact location, town, province, country, unknown, etc. |
| `location_uncertainty_m` | `double precision` | No | — | Documented geocoding uncertainty where measurable. |
| `geocoding_method` | `text` | No | — | Geocoder/source/version or reviewed manual assignment. |
| `event_cluster_key` | `text` | No | — | Optional reviewed grouping of reports about the same event; not a satellite incident count. |
| `reported_event_type` | `text` | No | — | Type claimed by the report, not inferred from a MODIS type code. |
| `reported_burned_area_ha` | `double precision` | No | — | Area as reported by the source; never calculated from hotspot count. |
| `reported_cause` | `text` | No | — | Attributed cause claimed by the report, preserved as a claim. |
| `claim_summary` | `text` | Yes | — | Plain synopsis of the extracted event claim. |
| `review_status` | `text` | Yes | — | Whether a human checked the extraction or rejected it. |
| `reviewed_by` | `text` | No | — | Reviewer identifier, not an inferred credibility score. |
| `reviewed_at` | `timestamptz` | No | — | UTC timestamp of that review. |

**Keys and value rules**

- `id`: `PRIMARY KEY`
- `report_id`: `REFERENCES news_reports (id)`
- `location_uncertainty_m`: `CHECK (location_uncertainty_m >= 0)`
- `reported_burned_area_ha`: `CHECK (reported_burned_area_ha >= 0)`
- `review_status`: `CHECK (review_status IN ('unreviewed', 'reviewed', 'rejected'))`
- `UNIQUE (report_id, claim_index)`
- `CHECK (event_end_exclusive IS NULL OR event_start IS NULL OR event_end_exclusive > event_start)`

## 26. `analysis_event_links`

One assessed link between an analysis and a reported event under a matching method.

| Column | SQL type | Required | Default / generation | Meaning |
|---|---|---|---|---|
| `analysis_id` | `uuid` | Yes | — | FK to the saved user selection in analyses. |
| `event_id` | `uuid` | Yes | — | FK to the extracted report event. |
| `relation` | `text` | Yes | — | Candidate, consistent, conflicting, unresolved or rejected match. |
| `match_method_version` | `text` | Yes | — | Version of date/location matching rules. |
| `temporal_match` | `jsonb` | Yes | — | Matched intervals, tolerances and temporal uncertainty. |
| `spatial_match` | `jsonb` | Yes | — | Intersection/distance evidence with geometry precision. |
| `independence` | `text` | Yes | — | Whether this source adds independent evidence or reuses satellite data. |
| `evidence_note` | `text` | Yes | — | Reason for the assessed relationship; no automatic universal confirmation. |
| `reviewed_by` | `text` | No | — | Reviewer identifier, not an inferred credibility score. |
| `reviewed_at` | `timestamptz` | No | — | UTC timestamp of that review. |

**Keys and value rules**

- `analysis_id`: `REFERENCES analyses (id)`
- `event_id`: `REFERENCES reported_events (id)`
- `relation`: `CHECK (relation IN ('candidate', 'consistent', 'conflicting', 'unresolved', 'rejected'))`
- `independence`: `CHECK (independence IN ('independent', 'dependent', 'unknown'))`
- `PRIMARY KEY (analysis_id, event_id, match_method_version)`

## 27. `evidence_snapshots`

One immutable, bounded bundle of facts, statuses and source citations for an analysis.

| Column | SQL type | Required | Default / generation | Meaning |
|---|---|---|---|---|
| `id` | `uuid` | Yes | — | Unique row identifier. |
| `analysis_id` | `uuid` | Yes | — | FK to the saved user selection in analyses. |
| `schema_version` | `text` | Yes | — | Version of the data contract used to interpret this record. |
| `evidence_json` | `jsonb` | Yes | — | Bounded facts with IDs, values, units, statuses, source links and exact versions. |
| `sha256` | `text` | Yes | — | SHA-256 digest of the immutable artifact or content named in this row. |
| `created_at` | `timestamptz` | Yes | DEFAULT now() | UTC timestamp when this record was created. |

**Keys and value rules**

- `id`: `PRIMARY KEY`
- `analysis_id`: `REFERENCES analyses (id)`
- `UNIQUE (analysis_id, sha256)`

## 28. `ai_explanations`

One explanation attempt for a snapshot, question, model, prompt version and language.

| Column | SQL type | Required | Default / generation | Meaning |
|---|---|---|---|---|
| `id` | `uuid` | Yes | — | Unique row identifier. |
| `snapshot_id` | `uuid` | Yes | — | FK to the immutable facts supplied to the model. |
| `language` | `text` | Yes | — | Language code, initially en/fr, optionally ar. |
| `question` | `text` | Yes | — | User question for this selection; sanitized for display and treated as user input. |
| `provider` | `text` | Yes | — | Organization/service that supplies the data or model. |
| `model_id` | `text` | Yes | — | Actual language-model identifier used, separate from scientific model_versions. |
| `prompt_version` | `text` | Yes | — | Version of the explanation instructions. |
| `tool_contract_version` | `text` | Yes | — | Version of allowed read-only tools and schemas. |
| `output_json` | `jsonb` | No | — | Structured answer, per-claim evidence IDs, limitations and suggested checks. |
| `status` | `text` | Yes | — | Explicit lifecycle/result state; permitted values appear in the constraints below. |
| `validation_report` | `jsonb` | No | — | Results of fact, citation, scope, unit and limitation checks. |
| `tool_trace_uri` | `text` | No | — | Redacted tool inputs/outputs used for reproducibility, not private model reasoning. |
| `input_tokens` | `integer` | No | — | Recorded provider input usage if available. |
| `output_tokens` | `integer` | No | — | Recorded provider output usage if available. |
| `cache_key` | `text` | Yes | — | Hash of all immutable inputs/settings that determine the result. |
| `created_at` | `timestamptz` | Yes | DEFAULT now() | UTC timestamp when this record was created. |
| `completed_at` | `timestamptz` | No | — | UTC timestamp when processing completed; null while pending. |

**Keys and value rules**

- `id`: `PRIMARY KEY`
- `snapshot_id`: `REFERENCES evidence_snapshots (id)`
- `status`: `CHECK (status IN ('queued', 'running', 'validated', 'rejected', 'failed', 'template_fallback'))`
- `input_tokens`: `CHECK (input_tokens >= 0)`
- `output_tokens`: `CHECK (output_tokens >= 0)`
- `cache_key`: `UNIQUE`

## 29. `metric_definitions`

One versioned measurement contract; raw detections and comparable responses use distinct units.

| Column | SQL type | Required | Default / generation | Meaning |
|---|---|---|---|---|
| `id` | `text` | Yes | — | Stable version-qualified metric identifier referenced by analyses/daily_activity. |
| `version` | `text` | Yes | — | Measurement contract version. |
| `unit` | `text` | Yes | — | detections, dimensionless_reference_response, or another explicit unit. |
| `family` | `text` | Yes | — | Native detections, source response or harmonized response. |
| `description` | `text` | Yes | — | Plain-language meaning shown to users. |
| `definition` | `jsonb` | Yes | — | Formula, eligible support, aggregation/time rules, uncertainty and allowed data streams. |
| `requires_masks` | `boolean` | Yes | — | Whether local QA/geolocation is needed to calculate this metric. |
| `requires_model` | `boolean` | Yes | — | Whether calibrated source inference is part of this metric. |

**Keys and value rules**

- `id`: `PRIMARY KEY`
- `family`: `CHECK (family IN ('native_detections', 'source_response', 'harmonized_response'))`

## 30. `ingestion_feeds`

One external transport adapter; MODIS_NRT is one feed that yields Terra and Aqua records.

| Column | SQL type | Required | Default / generation | Meaning |
|---|---|---|---|---|
| `id` | `text` | Yes | — | Stable feed identifier. |
| `provider` | `text` | Yes | — | Provider organization/service. |
| `adapter` | `text` | Yes | — | Adapter implementation name, e.g. firms_area_csv. |
| `adapter_version` | `text` | Yes | — | Decoder/request-contract version. |
| `endpoint_template` | `text` | Yes | — | Redacted URL template with placeholders; never store actual MAP_KEY in a URL. |
| `credential_ref` | `text` | No | — | Secret manager/environment variable name, never the secret value. |
| `rate_limit_group` | `text` | Yes | — | Shared quota bucket, e.g. the same FIRMS account across all sources. |
| `capability_spec` | `jsonb` | Yes | — | Verified maximum window, pagination, coverage, latency class and source documentation. |
| `state` | `text` | Yes | — | Active, paused, retired or not yet verified. |
| `verified_at` | `timestamptz` | No | — | Last capability verification time, UTC. |

**Keys and value rules**

- `id`: `PRIMARY KEY`
- `state`: `CHECK (state IN ('active', 'paused', 'retired', 'unverified'))`

## 31. `feed_sources`

One exact source emitted by a feed, with the predicate that selects its rows.

| Column | SQL type | Required | Default / generation | Meaning |
|---|---|---|---|---|
| `feed_id` | `text` | Yes | — | FK to ingestion_feeds. |
| `source_id` | `text` | Yes | — | FK to sources; output product can differ from a combined transport asset source. |
| `selector` | `jsonb` | Yes | — | Platform/product discriminators and mappings; MODIS Terra and Aqua are separated here. |

**Keys and value rules**

- `feed_id`: `REFERENCES ingestion_feeds (id)`
- `source_id`: `REFERENCES sources (id)`
- `PRIMARY KEY (feed_id, source_id)`

## 32. `source_availability`

One dated provider availability observation for a feed/source; records retained for audit.

| Column | SQL type | Required | Default / generation | Meaning |
|---|---|---|---|---|
| `feed_id` | `text` | Yes | — | FK component to feed_sources. |
| `source_id` | `text` | Yes | — | FK component to feed_sources. |
| `checked_at` | `timestamptz` | Yes | — | UTC time availability was checked. |
| `available_start` | `timestamptz` | No | — | Earliest reported event/valid time; may be unknown. |
| `available_end_exclusive` | `timestamptz` | No | — | End of reported available interval, exclusive; not a local cloud-coverage claim. |
| `status` | `text` | Yes | — | Available, partial, unavailable, unknown or retired. |
| `evidence_asset_id` | `uuid` | No | — | Optional immutable response proving this availability result. |
| `detail` | `jsonb` | Yes | — | Gaps, endpoint response, documented retirement and product version notes. |

**Keys and value rules**

- `status`: `CHECK (status IN ('available', 'partial', 'unavailable', 'unknown', 'retired'))`
- `evidence_asset_id`: `REFERENCES assets (id)`
- `PRIMARY KEY (feed_id, source_id, checked_at)`
- `FOREIGN KEY (feed_id, source_id) REFERENCES feed_sources (feed_id, source_id)`
- `CHECK (available_end_exclusive IS NULL OR available_start IS NULL OR available_end_exclusive > available_start)`

## 33. `ingestion_subscriptions`

One configured feed × registered scope × acquisition mode; public map clicks do not create it.

| Column | SQL type | Required | Default / generation | Meaning |
|---|---|---|---|---|
| `id` | `uuid` | Yes | — | Unique subscription identifier. |
| `feed_id` | `text` | Yes | — | FK to the transport adapter. |
| `area_id` | `uuid` | Yes | — | FK to the acquisition polygon used for bounding-box tiles and later clipping. |
| `scope_key` | `text` | Yes | — | Stable registered scope/shard name. |
| `mode` | `text` | Yes | — | Backfill, incremental or standard/revision reconciliation. |
| `interval_seconds` | `integer` | Yes | — | Proposed polling frequency; not provider observation frequency. |
| `overlap_seconds` | `integer` | Yes | — | Time deliberately re-requested to catch late data. |
| `history_start` | `timestamptz` | Yes | — | Earliest event/update time this subscription manages. |
| `fixed_end_exclusive` | `timestamptz` | No | — | Optional bounded end for historical imports. |
| `request_config` | `jsonb` | Yes | — | Sources, variables, collection IDs, chunking, backoff and endpoint-specific settings. |
| `config_sha256` | `text` | Yes | — | Hash of canonical subscription configuration. |
| `enabled` | `boolean` | Yes | DEFAULT FALSE | False until credentials, inventory and scope have passed readiness checks. |
| `next_due_at` | `timestamptz` | No | — | Earliest scheduled next poll in UTC. |
| `lease_owner` | `text` | No | — | Worker identity holding a temporary lock. |
| `lease_expires_at` | `timestamptz` | No | — | When another worker may recover an abandoned subscription. |

**Keys and value rules**

- `id`: `PRIMARY KEY`
- `feed_id`: `REFERENCES ingestion_feeds (id)`
- `area_id`: `REFERENCES areas (id)`
- `mode`: `CHECK (mode IN ('backfill', 'incremental', 'reconciliation'))`
- `interval_seconds`: `CHECK (interval_seconds > 0)`
- `overlap_seconds`: `CHECK (overlap_seconds >= 0)`
- `UNIQUE (feed_id, scope_key, mode, config_sha256)`
- `CHECK (fixed_end_exclusive IS NULL OR fixed_end_exclusive > history_start)`

## 34. `fetch_runs`

One bounded external query attempt; complete means retrieval succeeded, not that nature was fully observed.

| Column | SQL type | Required | Default / generation | Meaning |
|---|---|---|---|---|
| `id` | `uuid` | Yes | — | Unique attempt identifier. |
| `subscription_id` | `uuid` | Yes | — | FK to the acquisition subscription. |
| `pipeline_run_id` | `uuid` | No | — | Optional parent processing execution. |
| `request_key` | `text` | Yes | — | Hash of feed, scope, window, request parameters and scheduled poll generation; retry keeps it stable. |
| `attempt` | `integer` | Yes | — | Attempt number within that request key, beginning at one. |
| `query_start` | `timestamptz` | Yes | — | Inclusive lower bound in the declared query basis. |
| `query_end_exclusive` | `timestamptz` | Yes | — | Exclusive upper bound in the declared query basis. |
| `query_basis` | `text` | Yes | — | Observation time, provider revision time, publication time or model initialization time. |
| `sanitized_request` | `jsonb` | Yes | — | Exact request and pagination parameters with credentials redacted. |
| `status` | `text` | Yes | — | Queued, running, complete, partial, failed or validated not-modified. |
| `enumeration_complete` | `boolean` | Yes | DEFAULT FALSE | All required pages/chunks resolved; empty data alone does not establish completeness. |
| `page_count` | `integer` | Yes | DEFAULT 0 | Number of validated pages/payloads. |
| `record_count` | `bigint` | No | — | Parsed returned count; zero is a valid successful empty payload. |
| `started_at` | `timestamptz` | No | — | UTC start time of this attempt. |
| `completed_at` | `timestamptz` | No | — | UTC finish time of this attempt. |
| `max_observation_at` | `timestamptz` | No | — | Latest event time actually present; null for an empty response. |
| `http_status` | `integer` | No | — | Last HTTP response status, if applicable. |
| `retry_after` | `timestamptz` | No | — | Next allowed retry after provider limit/backoff. |
| `error_code` | `text` | No | — | Redacted structured error classification. |

**Keys and value rules**

- `id`: `PRIMARY KEY`
- `subscription_id`: `REFERENCES ingestion_subscriptions (id)`
- `pipeline_run_id`: `REFERENCES pipeline_runs (id)`
- `attempt`: `CHECK (attempt > 0)`
- `query_basis`: `CHECK (query_basis IN ('observation_time', 'provider_updated_time', 'publication_time', 'model_issue_time'))`
- `status`: `CHECK (status IN ('queued', 'running', 'complete', 'partial', 'failed', 'not_modified'))`
- `page_count`: `CHECK (page_count >= 0)`
- `record_count`: `CHECK (record_count >= 0)`
- `UNIQUE (subscription_id, request_key, attempt)`
- `CHECK (query_end_exclusive > query_start)`

## 35. `fetch_assets`

One immutable response/file associated with a fetch attempt and page; includes successful empty responses.

| Column | SQL type | Required | Default / generation | Meaning |
|---|---|---|---|---|
| `fetch_run_id` | `uuid` | Yes | — | FK to fetch_runs. |
| `asset_id` | `uuid` | Yes | — | FK to preserved bytes or a validated previously cached asset. |
| `role` | `text` | Yes | — | Catalog page, payload, empty result, availability or cached payload. |
| `page_key` | `text` | Yes | — | Stable page/chunk/granule locator for replay. |

**Keys and value rules**

- `fetch_run_id`: `REFERENCES fetch_runs (id)`
- `asset_id`: `REFERENCES assets (id)`
- `role`: `CHECK (role IN ('catalog_page', 'payload', 'empty_result', 'availability', 'cached_payload'))`
- `PRIMARY KEY (fetch_run_id, asset_id, role, page_key)`

## 36. `ingestion_checkpoints`

One committed progress marker per subscription/stage; does not infer progress from the last detection.

| Column | SQL type | Required | Default / generation | Meaning |
|---|---|---|---|---|
| `subscription_id` | `uuid` | Yes | — | FK to ingestion_subscriptions. |
| `stage` | `text` | Yes | — | Discovery, fetch, normalization or publication checkpoint. |
| `cursor_basis` | `text` | Yes | — | Exact meaning of committed_until, such as successfully queried UTC end. |
| `committed_until` | `timestamptz` | No | — | Contiguous committed boundary; do not advance over unresolved gaps. |
| `cursor_json` | `jsonb` | Yes | DEFAULT '{}' | Provider cursor state scoped to a fixed request; long-lived revision watermark is explicit. |
| `last_success_run_id` | `uuid` | No | — | Fetch evidence for the committed boundary. |
| `updated_at` | `timestamptz` | Yes | — | UTC checkpoint update time. |
| `generation` | `bigint` | Yes | DEFAULT 0 | Optimistic concurrency version used for compare-and-swap updates. |

**Keys and value rules**

- `subscription_id`: `REFERENCES ingestion_subscriptions (id)`
- `stage`: `CHECK (stage IN ('discovery', 'fetch', 'normalize', 'publish'))`
- `last_success_run_id`: `REFERENCES fetch_runs (id)`
- `generation`: `CHECK (generation >= 0)`
- `PRIMARY KEY (subscription_id, stage)`

## 37. `ingestion_gaps`

One unresolved or resolved interval of ingestion availability; distinct from clouds/no-detection.

| Column | SQL type | Required | Default / generation | Meaning |
|---|---|---|---|---|
| `id` | `uuid` | Yes | — | Unique gap identifier. |
| `subscription_id` | `uuid` | Yes | — | FK to subscription/scope. |
| `gap_start` | `timestamptz` | Yes | — | Inclusive start of the unavailable/query-failed interval. |
| `gap_end_exclusive` | `timestamptz` | Yes | — | Exclusive end of the interval. |
| `kind` | `text` | Yes | — | Transport/catalog/companion/provider/retirement or unknown problem. |
| `status` | `text` | Yes | — | Open, retrying, resolved or explicitly accepted unavailable. |
| `discovered_at` | `timestamptz` | Yes | — | UTC first detection of this gap. |
| `last_attempt_at` | `timestamptz` | No | — | Most recent repair attempt time. |
| `retry_after` | `timestamptz` | No | — | Next eligible bounded repair time. |
| `resolved_by_run_id` | `uuid` | No | — | Fetch run that supplied missing evidence, when resolved. |
| `evidence` | `jsonb` | Yes | — | Failure response IDs, missing granule keys and resolution explanation. |

**Keys and value rules**

- `id`: `PRIMARY KEY`
- `subscription_id`: `REFERENCES ingestion_subscriptions (id)`
- `kind`: `CHECK (kind IN ('fetch_failed', 'catalog_incomplete', 'missing_asset', 'missing_companion', 'provider_outage', 'retired_source', 'unknown'))`
- `status`: `CHECK (status IN ('open', 'retrying', 'resolved', 'accepted_unavailable'))`
- `resolved_by_run_id`: `REFERENCES fetch_runs (id)`
- `CHECK (gap_end_exclusive > gap_start)`

## 38. `quality_issues`

One rule violation produced by a pipeline execution; blocking issues prevent publication.

| Column | SQL type | Required | Default / generation | Meaning |
|---|---|---|---|---|
| `id` | `uuid` | Yes | — | Unique issue identifier. |
| `pipeline_run_id` | `uuid` | Yes | — | FK to the execution that found the issue. |
| `asset_id` | `uuid` | No | — | Optional FK to affected raw input. |
| `rule_id` | `text` | Yes | — | Versioned quality-check identifier. |
| `severity` | `text` | Yes | — | Informational, warning or publication-blocking. |
| `status` | `text` | Yes | — | Open, resolved or reviewed/accepted with explanation. |
| `affected_count` | `bigint` | Yes | — | Count of affected records or objects. |
| `sample_locator` | `jsonb` | Yes | — | Bounded sample of row/granule locators without copying large data. |
| `explanation` | `text` | Yes | — | Human-readable problem. |
| `resolution_note` | `text` | No | — | Recorded fix or accepted limitation. |
| `created_at` | `timestamptz` | Yes | DEFAULT now() | UTC issue creation time. |

**Keys and value rules**

- `id`: `PRIMARY KEY`
- `pipeline_run_id`: `REFERENCES pipeline_runs (id)`
- `asset_id`: `REFERENCES assets (id)`
- `severity`: `CHECK (severity IN ('info', 'warning', 'blocking'))`
- `status`: `CHECK (status IN ('open', 'resolved', 'accepted'))`
- `affected_count`: `CHECK (affected_count >= 0)`

## 39. `data_partitions`

One immutable complete snapshot of one series/partition key; empty snapshots are allowed.

| Column | SQL type | Required | Default / generation | Meaning |
|---|---|---|---|---|
| `id` | `uuid` | Yes | — | Unique partition revision identifier. |
| `pipeline_run_id` | `uuid` | Yes | — | FK to the run producing this partition. |
| `kind` | `text` | Yes | — | Detection, observation, feature, daily product, weather, report or tile output. |
| `series_key` | `text` | Yes | — | Product/stream or method series; publication resolves overlap explicitly. |
| `partition_key` | `text` | Yes | — | Deterministic date/spatial shard key within a series. |
| `support_spec` | `jsonb` | Yes | — | Exact half-open time/spatial bounds, input completeness, stream and selection rules. |
| `storage_uri` | `text` | Yes | — | Immutable Parquet/mask/tile/manifest artifact location. |
| `sha256` | `text` | Yes | — | SHA-256 digest of the artifact. |
| `input_manifest_uri` | `text` | Yes | — | Exact raw input assets/rows and processing policies. |
| `schema_version` | `text` | Yes | — | Version of the partition row schema. |
| `row_count` | `bigint` | Yes | — | Canonical output records, zero for an authoritative empty snapshot. |
| `serving_complete` | `boolean` | Yes | — | True only when all rows required by the bounded serving contract are in database tables; false requires lake-backed queries. |
| `validation_status` | `text` | Yes | — | Pending, validated or quarantined. |
| `created_at` | `timestamptz` | Yes | DEFAULT now() | UTC time the partition revision was produced. |

**Keys and value rules**

- `id`: `PRIMARY KEY`
- `pipeline_run_id`: `REFERENCES pipeline_runs (id)`
- `kind`: `CHECK (kind IN ('detections', 'observations', 'features', 'daily_activity', 'weather', 'reports', 'tiles'))`
- `sha256`: `CHECK (sha256 ~ '^[0-9a-f]{64}$')`
- `row_count`: `CHECK (row_count >= 0)`
- `validation_status`: `CHECK (validation_status IN ('pending', 'validated', 'quarantined'))`
- `UNIQUE (series_key, partition_key, sha256)`
- `UNIQUE (id, series_key, partition_key)`

## 40. `partition_detections`

One canonical detection included in a served detection partition.

| Column | SQL type | Required | Default / generation | Meaning |
|---|---|---|---|---|
| `partition_id` | `uuid` | Yes | — | FK to a complete detection partition revision. |
| `detection_id` | `bigint` | Yes | — | FK to the immutable normalized detection record. |

**Keys and value rules**

- `partition_id`: `REFERENCES data_partitions (id)`
- `detection_id`: `REFERENCES detections (id)`
- `PRIMARY KEY (partition_id, detection_id)`

## 41. `release_partitions`

One selected revision per series/partition key in a release; unchanged partitions can be shared.

| Column | SQL type | Required | Default / generation | Meaning |
|---|---|---|---|---|
| `release_id` | `uuid` | Yes | — | FK to immutable release snapshot. |
| `series_key` | `text` | Yes | — | Series being published; part of unique selection key. |
| `partition_key` | `text` | Yes | — | Time/spatial partition selection key. |
| `partition_id` | `uuid` | Yes | — | FK to the selected matching series/key partition revision. |

**Keys and value rules**

- `release_id`: `REFERENCES data_releases (id)`
- `PRIMARY KEY (release_id, series_key, partition_key)`
- `FOREIGN KEY (partition_id, series_key, partition_key) REFERENCES data_partitions (id, series_key, partition_key)`

## 42. `partition_dependencies`

One derived partition dependency used to find downstream rebuild work.

| Column | SQL type | Required | Default / generation | Meaning |
|---|---|---|---|---|
| `partition_id` | `uuid` | Yes | — | FK to the derived output partition. |
| `input_partition_id` | `uuid` | Yes | — | FK to one upstream partition. |
| `role` | `text` | Yes | — | Input role, such as detections, mask, weather or geolocation. |

**Keys and value rules**

- `partition_id`: `REFERENCES data_partitions (id)`
- `input_partition_id`: `REFERENCES data_partitions (id)`
- `PRIMARY KEY (partition_id, input_partition_id, role)`
- `CHECK (partition_id <> input_partition_id)`

## 43. `release_aliases`

One mutable pointer to a published release for a named scope; readers pin its resolved UUID.

| Column | SQL type | Required | Default / generation | Meaning |
|---|---|---|---|---|
| `alias` | `text` | Yes | — | latest_standard, latest_recent, latest_weather_history, latest_weather_recent or latest_reports. |
| `scope_key` | `text` | Yes | — | Registered product/geographic scope. |
| `release_id` | `uuid` | Yes | — | FK to the published snapshot currently selected. |
| `generation` | `bigint` | Yes | DEFAULT 0 | Compare-and-swap generation preventing concurrent publishers overwriting each other. |
| `updated_at` | `timestamptz` | Yes | — | UTC atomic pointer update time. |

**Keys and value rules**

- `release_id`: `REFERENCES data_releases (id)`
- `generation`: `CHECK (generation >= 0)`
- `PRIMARY KEY (alias, scope_key)`

## 44. `release_changes`

One documented scoped change between two published snapshots.

| Column | SQL type | Required | Default / generation | Meaning |
|---|---|---|---|---|
| `id` | `uuid` | Yes | — | Unique change identifier. |
| `from_release_id` | `uuid` | Yes | — | FK to prior snapshot. |
| `to_release_id` | `uuid` | Yes | — | FK to replacement/new snapshot. |
| `series_key` | `text` | Yes | — | Affected source or method series. |
| `affected_start` | `timestamptz` | Yes | — | Inclusive event/valid-time lower bound. |
| `affected_end_exclusive` | `timestamptz` | Yes | — | Exclusive event/valid-time upper bound. |
| `affected_area` | `geometry(multipolygon, 4326)` | No | — | Affected geography if known; null means scope-wide/unknown. |
| `reason` | `text` | Yes | — | New, late, revised, standard replacement, retraction, method/weather/report change. |
| `diff_manifest_uri` | `text` | Yes | — | Counts, changed partition IDs and canonical added/removed/changed record evidence. |
| `created_at` | `timestamptz` | Yes | DEFAULT now() | UTC change-record time. |

**Keys and value rules**

- `id`: `PRIMARY KEY`
- `from_release_id`: `REFERENCES data_releases (id)`
- `to_release_id`: `REFERENCES data_releases (id)`
- `reason`: `CHECK (reason IN ('new_data', 'late_data', 'provider_revision', 'standard_replacement', 'retraction', 'method_change', 'weather_revision', 'report_revision'))`
- `CHECK (from_release_id <> to_release_id)`
- `CHECK (affected_end_exclusive > affected_start)`

## 45. `analysis_components`

One pinned satellite/weather/reports snapshot or explicit missing component per analysis.

| Column | SQL type | Required | Default / generation | Meaning |
|---|---|---|---|---|
| `analysis_id` | `uuid` | Yes | — | FK to the immutable user request. |
| `component` | `text` | Yes | — | Satellite, historical weather, recent weather or reports. |
| `release_id` | `uuid` | No | — | Exact context release, nullable when that component is unavailable/not requested. |
| `status` | `text` | Yes | — | Ready, partial, missing, unsupported, failed or not requested. |
| `reasons` | `jsonb` | Yes | DEFAULT '[]' | Scope, missingness and context-availability explanations. |

**Keys and value rules**

- `analysis_id`: `REFERENCES analyses (id)`
- `component`: `CHECK (component IN ('satellite', 'weather_historical', 'weather_recent', 'reports'))`
- `release_id`: `REFERENCES data_releases (id)`
- `status`: `CHECK (status IN ('ready', 'partial', 'missing', 'unsupported', 'failed', 'not_requested'))`
- `PRIMARY KEY (analysis_id, component)`
- `CHECK ((status IN ('ready', 'partial') AND release_id IS NOT NULL) OR status NOT IN ('ready', 'partial'))`

## 46. `api_jobs`

One durable asynchronous API job with request identity and export lifecycle.

| Column | SQL type | Required | Default / generation | Meaning |
|---|---|---|---|---|
| `id` | `uuid` | Yes | — | Unique job identifier returned to the client. |
| `kind` | `text` | Yes | — | Analysis, explanation, export, backfill or explicit refresh. |
| `analysis_id` | `uuid` | No | — | Optional FK to selected analysis. |
| `explanation_id` | `uuid` | No | — | Optional FK to AI attempt. |
| `requested_by` | `text` | Yes | — | Authenticated principal/session scope used for authorization and idempotency. |
| `request_hash` | `text` | Yes | — | Canonical request digest; same idempotency key with different hash returns conflict. |
| `idempotency_key` | `text` | Yes | — | Client-supplied or server-generated key unique within requester scope. |
| `request_spec` | `jsonb` | Yes | — | Validated bounded job configuration, with secrets excluded. |
| `status` | `text` | Yes | — | Queued, running, succeeded, partial, failed or cancelled. |
| `attempt` | `integer` | Yes | DEFAULT 0 | Worker attempt count; jobs are retried idempotently. |
| `lease_expires_at` | `timestamptz` | No | — | When an abandoned running job can be reclaimed. |
| `progress` | `jsonb` | Yes | DEFAULT '{}' | Completed/total work units, stage and warnings; no fabricated ETA. |
| `result_manifest_uri` | `text` | No | — | Prepared export/result manifest after completion. |
| `result_sha256` | `text` | No | — | Digest of the export/result artifact. |
| `result_byte_size` | `bigint` | No | — | Artifact byte count. |
| `expires_at` | `timestamptz` | No | — | Export retention/download expiry, distinct from scientific data retention. |
| `error_code` | `text` | No | — | Redacted structured failure. |
| `created_at` | `timestamptz` | Yes | DEFAULT now() | UTC submission time. |
| `completed_at` | `timestamptz` | No | — | UTC terminal-state time. |

**Keys and value rules**

- `id`: `PRIMARY KEY`
- `kind`: `CHECK (kind IN ('analysis', 'explanation', 'export', 'backfill', 'refresh'))`
- `analysis_id`: `REFERENCES analyses (id)`
- `explanation_id`: `REFERENCES ai_explanations (id)`
- `status`: `CHECK (status IN ('queued', 'running', 'succeeded', 'partial', 'failed', 'cancelled'))`
- `attempt`: `CHECK (attempt >= 0)`
- `result_byte_size`: `CHECK (result_byte_size >= 0)`
- `UNIQUE (requested_by, idempotency_key)`

## 47. `outbox_events`

One durable work/publication event committed in the same database transaction as its state change.

| Column | SQL type | Required | Default / generation | Meaning |
|---|---|---|---|---|
| `id` | `uuid` | Yes | — | Unique event identifier. |
| `event_type` | `text` | Yes | — | Versioned event name, e.g. release.published or analysis.requested. |
| `aggregate_id` | `text` | Yes | — | Related job/release/analysis ID; validated by event type. |
| `dedupe_key` | `text` | Yes | — | Stable event identity for at-least-once delivery. |
| `payload` | `jsonb` | Yes | — | Minimal typed job IDs/config references, no credentials. |
| `status` | `text` | Yes | — | Pending, leased for dispatch, or delivered. |
| `attempts` | `integer` | Yes | DEFAULT 0 | Dispatch attempt count. |
| `available_at` | `timestamptz` | Yes | — | Earliest permitted dispatch time. |
| `lease_expires_at` | `timestamptz` | No | — | Recovery time if dispatcher dies. |
| `delivered_at` | `timestamptz` | No | — | Broker-confirmed dispatch time, not job completion. |
| `created_at` | `timestamptz` | Yes | DEFAULT now() | UTC creation time. |

**Keys and value rules**

- `id`: `PRIMARY KEY`
- `dedupe_key`: `UNIQUE`
- `status`: `CHECK (status IN ('pending', 'dispatching', 'delivered'))`
- `attempts`: `CHECK (attempts >= 0)`

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
