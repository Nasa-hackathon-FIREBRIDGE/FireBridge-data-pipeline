-- Initial FIREBRIDGE schema, promoted from the approved v2 design.
-- Use an empty development database; create UUIDs in the application.
-- Serving tables contain bounded, published datasets. Global raw data stays in Parquet.
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE SCHEMA firebridge;
SET LOCAL search_path = firebridge, public;

-- Catalog: exact product, collection and processing stream, not just a satellite name.
CREATE TABLE sources (
    id text PRIMARY KEY,
    name text NOT NULL,
    provider text NOT NULL,
    kind text NOT NULL CHECK (kind IN ('hotspots','fire_mask','geolocation','land_cover','imagery','weather','news','incident_report')),
    platform text,
    instrument text,
    product text NOT NULL,
    collection text NOT NULL,
    processing_stream text NOT NULL,
    documentation_url text NOT NULL,
    citation text NOT NULL,
    license_info text NOT NULL,
    native_resolution_m double precision CHECK (native_resolution_m > 0),
    schema_version text NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'
);

-- One immutable file/API response. Metadata records CRS, bands, units and request parameters.
CREATE TABLE assets (
    id uuid PRIMARY KEY,
    source_id text NOT NULL REFERENCES sources(id),
    native_key text NOT NULL,
    revision text NOT NULL,
    source_url text NOT NULL,
    storage_uri text NOT NULL,
    sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    byte_size bigint NOT NULL CHECK (byte_size >= 0),
    time_start timestamptz,
    time_end timestamptz,
    footprint geometry(MultiPolygon,4326),
    retrieved_at timestamptz NOT NULL,
    validation_status text NOT NULL CHECK (validation_status IN ('pending','accepted','quarantined')),
    metadata jsonb NOT NULL DEFAULT '{}',
    UNIQUE(source_id,native_key,revision,sha256),
    UNIQUE(id,source_id),
    CHECK (time_end IS NULL OR time_start IS NULL OR time_end >= time_start)
);

CREATE TABLE data_releases (
    id uuid PRIMARY KEY,
    name text NOT NULL UNIQUE,
    status text NOT NULL CHECK (status IN ('draft','validated','published','retired')),
    stream text NOT NULL CHECK (stream IN ('retrospective','provisional','experiment')),
    code_version text NOT NULL,
    config jsonb NOT NULL,
    config_sha256 text NOT NULL,
    manifest_uri text NOT NULL,
    parent_release_id uuid REFERENCES data_releases(id),
    dataset_kind text NOT NULL CHECK (dataset_kind IN ('satellite','weather','reports')),
    scope_key text NOT NULL,
    observation_cutoff timestamptz NOT NULL,
    validation_report_uri text,
    created_at timestamptz NOT NULL DEFAULT now(),
    published_at timestamptz
);

CREATE TABLE release_assets (
    release_id uuid NOT NULL REFERENCES data_releases(id),
    asset_id uuid NOT NULL REFERENCES assets(id),
    role text NOT NULL,
    PRIMARY KEY(release_id,asset_id,role)
);

CREATE TABLE pipeline_runs (
    id uuid PRIMARY KEY,
    release_id uuid REFERENCES data_releases(id),
    stage text NOT NULL,
    idempotency_key text NOT NULL UNIQUE,
    status text NOT NULL CHECK (status IN ('queued','running','succeeded','failed','cancelled')),
    code_version text NOT NULL,
    config jsonb NOT NULL,
    input_manifest_uri text NOT NULL,
    output_manifest_uri text,
    started_at timestamptz,
    finished_at timestamptz,
    error_code text,
    log_uri text
);

-- Geographies are immutable revisions. area_cells weights use AOI-intersected LAND area.
CREATE TABLE areas (
    id uuid PRIMARY KEY,
    name text NOT NULL,
    version text NOT NULL,
    geom geometry(MultiPolygon,4326) NOT NULL,
    geometry_sha256 text NOT NULL,
    display_timezone text NOT NULL,
    provenance text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(geometry_sha256,version),
    CHECK (ST_IsValid(geom) AND NOT ST_IsEmpty(geom))
);

CREATE TABLE grids (
    id text PRIMARY KEY,
    version text NOT NULL,
    projection_srid integer NOT NULL,
    cell_size_m double precision NOT NULL CHECK (cell_size_m > 0),
    origin_x_m double precision NOT NULL,
    origin_y_m double precision NOT NULL,
    supported_extent geometry(MultiPolygon,4326) NOT NULL,
    land_mask_asset_id uuid NOT NULL REFERENCES assets(id),
    construction_spec jsonb NOT NULL
);

CREATE TABLE grid_cells (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    grid_id text NOT NULL REFERENCES grids(id),
    grid_x integer NOT NULL,
    grid_y integer NOT NULL,
    geom geometry(MultiPolygon,4326) NOT NULL,
    area_m2 double precision NOT NULL CHECK (area_m2 > 0),
    land_area_m2 double precision NOT NULL CHECK (land_area_m2 >= 0 AND land_area_m2 <= area_m2),
    UNIQUE(grid_id,grid_x,grid_y)
);

CREATE TABLE area_cells (
    area_id uuid NOT NULL REFERENCES areas(id),
    cell_id bigint NOT NULL REFERENCES grid_cells(id),
    overlap_land_area_m2 double precision NOT NULL CHECK (overlap_land_area_m2 > 0),
    weighting_version text NOT NULL,
    PRIMARY KEY(area_id,cell_id,weighting_version)
);

-- Native points are not incidents. Identity is source/record/revision, never rounded lat/lon alone.
CREATE TABLE detections (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    asset_id uuid NOT NULL,
    source_id text NOT NULL,
    native_record_key text NOT NULL,
    record_sha256 text NOT NULL CHECK (record_sha256 ~ '^[0-9a-f]{64}$'),
    identity_key text,
    identity_method text NOT NULL,
    processing_level text NOT NULL CHECK (processing_level IN ('standard','nrt','rt','urt','unknown')),
    acquired_at timestamptz NOT NULL,
    geom geometry(Point,4326) NOT NULL,
    confidence_raw text,
    confidence_scheme text NOT NULL,
    type_raw text,
    day_night text CHECK (day_night IN ('day','night','unknown')),
    frp_mw double precision CHECK (frp_mw >= 0 AND frp_mw < 'Infinity'::double precision),
    brightness_bands jsonb NOT NULL DEFAULT '{}',
    scan_km double precision CHECK (scan_km > 0),
    track_km double precision CHECK (track_km > 0),
    cross_track_sample integer,
    native_fields jsonb NOT NULL DEFAULT '{}',
    FOREIGN KEY(asset_id) REFERENCES assets(id),
    FOREIGN KEY(source_id) REFERENCES sources(id),
    UNIQUE(asset_id,native_record_key),
    UNIQUE(source_id,record_sha256)
);

-- One cell/source/pass with full-mask QA. No row is inferred merely from an absent hotspot.
CREATE TABLE observations (
    id uuid PRIMARY KEY,
    release_id uuid NOT NULL REFERENCES data_releases(id),
    cell_id bigint NOT NULL REFERENCES grid_cells(id),
    source_id text NOT NULL REFERENCES sources(id),
    pass_key text NOT NULL,
    time_start timestamptz NOT NULL,
    time_end timestamptz NOT NULL,
    representative_time timestamptz NOT NULL,
    local_solar_date date NOT NULL,
    regime text NOT NULL,
    land_area_m2 double precision NOT NULL CHECK (land_area_m2 > 0),
    usable_land_m2 double precision CHECK (usable_land_m2 >= 0 AND usable_land_m2 <= land_area_m2),
    cloud_land_m2 double precision CHECK (cloud_land_m2 >= 0 AND cloud_land_m2 <= land_area_m2),
    invalid_land_m2 double precision CHECK (invalid_land_m2 >= 0 AND invalid_land_m2 <= land_area_m2),
    unobserved_land_m2 double precision CHECK (unobserved_land_m2 >= 0 AND unobserved_land_m2 <= land_area_m2),
    usable_support_uri text,
    detection_links_uri text,
    coverage_status text NOT NULL CHECK (coverage_status IN ('usable','insufficient','missing_input','outside_swath')),
    retained_detection_count integer CHECK (retained_detection_count >= 0),
    retained_any boolean,
    eligible boolean NOT NULL,
    exclusion_reasons jsonb NOT NULL DEFAULT '[]',
    qa_policy_version text NOT NULL,
    geometry_summary jsonb NOT NULL DEFAULT '{}',
    UNIQUE(release_id,cell_id,source_id,pass_key,qa_policy_version),
    UNIQUE(id,release_id,cell_id),
    CHECK (time_end >= time_start AND representative_time BETWEEN time_start AND time_end),
    CHECK ((eligible AND coverage_status = 'usable' AND retained_any IS NOT NULL AND retained_detection_count IS NOT NULL AND usable_support_uri IS NOT NULL AND usable_land_m2 IS NOT NULL AND cloud_land_m2 IS NOT NULL AND invalid_land_m2 IS NOT NULL AND unobserved_land_m2 IS NOT NULL)
        OR (NOT eligible AND retained_any IS NULL)),
    CHECK (retained_any IS NULL OR retained_any = (retained_detection_count > 0))
);

CREATE TABLE observation_assets (
    observation_id uuid NOT NULL REFERENCES observations(id),
    asset_id uuid NOT NULL REFERENCES assets(id),
    role text NOT NULL CHECK (role IN ('fire_mask','geolocation','hotspots','land_mask')),
    PRIMARY KEY(observation_id,asset_id,role)
);

CREATE TABLE matched_pairs (
    id uuid PRIMARY KEY,
    release_id uuid NOT NULL REFERENCES data_releases(id),
    cell_id bigint NOT NULL REFERENCES grid_cells(id),
    series_key text NOT NULL,
    reference_observation_id uuid NOT NULL,
    source_observation_id uuid NOT NULL,
    time_delta_seconds integer NOT NULL CHECK (time_delta_seconds >= 0),
    shared_usable_land_m2 double precision NOT NULL CHECK (shared_usable_land_m2 >= 0),
    shared_usable_fraction double precision NOT NULL CHECK (shared_usable_fraction BETWEEN 0 AND 1),
    shared_support_uri text NOT NULL,
    eligible boolean NOT NULL,
    reference_target boolean,
    source_any_on_shared_support boolean,
    split_name text CHECK (split_name IN ('train','development','calibration','temporal_test','spatial_test','excluded')),
    block_id text,
    episode_group_id text,
    exclusion_reasons jsonb NOT NULL DEFAULT '[]',
    FOREIGN KEY(reference_observation_id,release_id,cell_id) REFERENCES observations(id,release_id,cell_id),
    FOREIGN KEY(source_observation_id,release_id,cell_id) REFERENCES observations(id,release_id,cell_id),
    UNIQUE(release_id,series_key,reference_observation_id),
    UNIQUE(release_id,series_key,source_observation_id),
    CHECK (reference_observation_id <> source_observation_id),
    CHECK ((eligible AND reference_target IS NOT NULL AND source_any_on_shared_support IS NOT NULL AND split_name IS NOT NULL AND block_id IS NOT NULL)
        OR (NOT eligible AND reference_target IS NULL))
);

-- Per-row features live in Parquet, keyed by pair/observation ID. This is their registry.
CREATE TABLE feature_sets (
    id uuid PRIMARY KEY,
    release_id uuid NOT NULL REFERENCES data_releases(id),
    version text NOT NULL,
    artifact_uri text NOT NULL,
    sha256 text NOT NULL,
    feature_contract jsonb NOT NULL,
    split_manifest_uri text NOT NULL,
    split_sha256 text NOT NULL,
    row_count bigint NOT NULL CHECK (row_count >= 0),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE model_versions (
    id uuid PRIMARY KEY,
    name text NOT NULL,
    version text NOT NULL,
    feature_set_id uuid NOT NULL REFERENCES feature_sets(id),
    source_id text NOT NULL REFERENCES sources(id),
    reference_source_id text NOT NULL REFERENCES sources(id),
    algorithm text NOT NULL,
    artifact_uri text NOT NULL,
    sha256 text NOT NULL,
    target_definition jsonb NOT NULL,
    support_domain jsonb NOT NULL,
    calibration_manifest_uri text NOT NULL,
    status text NOT NULL CHECK (status IN ('candidate','validated','rejected','retired')),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(name,version)
);

CREATE TABLE evaluations (
    id uuid PRIMARY KEY,
    model_id uuid NOT NULL REFERENCES model_versions(id),
    release_id uuid NOT NULL REFERENCES data_releases(id),
    experiment text NOT NULL,
    slice_key text NOT NULL,
    split_manifest_uri text NOT NULL,
    sample_count bigint NOT NULL CHECK (sample_count >= 0),
    positive_count bigint NOT NULL CHECK (positive_count BETWEEN 0 AND sample_count),
    independent_block_count integer NOT NULL CHECK (independent_block_count >= 0),
    metrics jsonb NOT NULL,
    baseline_metrics jsonb NOT NULL,
    uncertainty_method text,
    report_uri text NOT NULL,
    UNIQUE(model_id,release_id,experiment,slice_key)
);

CREATE TABLE predictions (
    id uuid PRIMARY KEY,
    release_id uuid NOT NULL REFERENCES data_releases(id),
    cell_id bigint NOT NULL REFERENCES grid_cells(id),
    observation_id uuid NOT NULL,
    model_id uuid NOT NULL REFERENCES model_versions(id),
    response_probability double precision CHECK (response_probability BETWEEN 0 AND 1),
    status text NOT NULL CHECK (status IN ('supported','unsupported','failed')),
    support_reasons jsonb NOT NULL DEFAULT '[]',
    features_uri text NOT NULL,
    uncertainty jsonb,
    FOREIGN KEY(observation_id,release_id,cell_id) REFERENCES observations(id,release_id,cell_id),
    UNIQUE(observation_id,model_id),
    UNIQUE(id,release_id,cell_id),
    CHECK ((status = 'supported' AND response_probability IS NOT NULL) OR (status <> 'supported' AND response_probability IS NULL))
);

-- Includes missing/unsupported cell-days. Selection never maximizes detections.
CREATE TABLE daily_activity (
    release_id uuid NOT NULL REFERENCES data_releases(id),
    cell_id bigint NOT NULL REFERENCES grid_cells(id),
    reporting_date date NOT NULL,
    time_basis text NOT NULL,
    metric_key text NOT NULL,
    selection_policy text NOT NULL,
    observation_id uuid,
    prediction_id uuid,
    response_value double precision CHECK (response_value BETWEEN 0 AND 1),
    status text NOT NULL CHECK (status IN ('reference_observed','source_estimated','insufficient_coverage','unsupported_model','missing_data')),
    candidate_count integer NOT NULL CHECK (candidate_count >= 0),
    reasons jsonb NOT NULL DEFAULT '[]',
    PRIMARY KEY(release_id,cell_id,reporting_date,time_basis,metric_key,selection_policy),
    FOREIGN KEY(observation_id,release_id,cell_id) REFERENCES observations(id,release_id,cell_id),
    FOREIGN KEY(prediction_id,release_id,cell_id) REFERENCES predictions(id,release_id,cell_id),
    CHECK ((status = 'reference_observed' AND observation_id IS NOT NULL AND prediction_id IS NULL AND response_value IS NOT NULL AND response_value IN (0,1))
        OR (status = 'source_estimated' AND observation_id IS NOT NULL AND prediction_id IS NOT NULL AND response_value IS NOT NULL)
        OR (status IN ('insufficient_coverage','unsupported_model','missing_data') AND response_value IS NULL AND prediction_id IS NULL))
);

-- A frozen user selection. New settings => a new row/cache key, not mutation of results.
CREATE TABLE analyses (
    id uuid PRIMARY KEY,
    area_id uuid NOT NULL REFERENCES areas(id),
    release_id uuid NOT NULL REFERENCES data_releases(id),
    start_date date NOT NULL,
    end_date_exclusive date NOT NULL,
    time_basis text NOT NULL,
    metric_key text NOT NULL,
    grid_id text REFERENCES grids(id),
    selection_policy text NOT NULL,
    weighting_version text NOT NULL,
    baseline_spec jsonb,
    weather_policy jsonb NOT NULL,
    news_policy jsonb NOT NULL,
    request_spec jsonb NOT NULL,
    cache_key text NOT NULL UNIQUE,
    status text NOT NULL CHECK (status IN ('queued','running','ready','partial','unsupported','failed')),
    error_code text,
    created_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    CHECK (end_date_exclusive > start_date)
);

CREATE TABLE calendar_periods (
    analysis_id uuid NOT NULL REFERENCES analyses(id),
    period_start date NOT NULL,
    period_end_exclusive date NOT NULL,
    resolution text NOT NULL CHECK (resolution IN ('day','week','month','selection')),
    response_numerator_m2_days double precision NOT NULL CHECK (response_numerator_m2_days >= 0),
    eligible_land_m2_days double precision NOT NULL CHECK (eligible_land_m2_days >= 0),
    possible_land_m2_days double precision NOT NULL CHECK (possible_land_m2_days > 0),
    response_value double precision GENERATED ALWAYS AS (response_numerator_m2_days / NULLIF(eligible_land_m2_days,0)) STORED,
    coverage_fraction double precision GENERATED ALWAYS AS (eligible_land_m2_days / possible_land_m2_days) STORED,
    observed_weight_fraction double precision CHECK (observed_weight_fraction BETWEEN 0 AND 1),
    valid_cell_days bigint NOT NULL CHECK (valid_cell_days >= 0),
    baseline_year_count integer NOT NULL DEFAULT 0 CHECK (baseline_year_count >= 0),
    seasonal_percentile double precision CHECK (seasonal_percentile BETWEEN 0 AND 100),
    uncertainty jsonb,
    status text NOT NULL CHECK (status IN ('supported','limited','unsupported')),
    reasons jsonb NOT NULL DEFAULT '[]',
    PRIMARY KEY(analysis_id,period_start,resolution),
    CHECK (period_end_exclusive > period_start),
    CHECK (response_numerator_m2_days <= eligible_land_m2_days AND eligible_land_m2_days <= possible_land_m2_days),
    CHECK (baseline_year_count > 0 OR seasonal_percentile IS NULL)
);

-- Weather keeps native spatial support, variable provenance and forecast issue time.
CREATE TABLE weather_locations (
    id uuid PRIMARY KEY,
    source_id text NOT NULL REFERENCES sources(id),
    native_location_key text NOT NULL,
    support_kind text NOT NULL CHECK (support_kind IN ('grid_cell','station','sample_point')),
    geom geometry(Point,4326) NOT NULL,
    footprint geometry(MultiPolygon,4326),
    elevation_m double precision,
    native_resolution_m double precision,
    metadata jsonb NOT NULL DEFAULT '{}',
    UNIQUE(source_id,native_location_key),
    UNIQUE(id,source_id)
);

-- Tall design: one variable at one location over one interval in one asset revision.
CREATE TABLE weather_values (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    location_id uuid NOT NULL,
    source_id text NOT NULL,
    asset_id uuid NOT NULL,
    variable text NOT NULL,
    unit text NOT NULL,
    valid_start timestamptz NOT NULL,
    valid_end timestamptz NOT NULL,
    issued_at timestamptz,
    available_at timestamptz,
    data_kind text NOT NULL CHECK (data_kind IN ('reanalysis','forecast','model_current','station_observation')),
    statistic text NOT NULL CHECK (statistic IN ('instant','mean','maximum','minimum','interval_sum')),
    value double precision,
    quality_status text NOT NULL CHECK (quality_status IN ('valid','missing','invalid')),
    derivation jsonb NOT NULL DEFAULT '{}',
    FOREIGN KEY(location_id,source_id) REFERENCES weather_locations(id,source_id),
    FOREIGN KEY(asset_id,source_id) REFERENCES assets(id,source_id),
    UNIQUE(asset_id,location_id,variable,valid_start,valid_end),
    CHECK (valid_end >= valid_start),
    CHECK (data_kind <> 'forecast' OR issued_at IS NOT NULL),
    CHECK ((quality_status = 'valid' AND value IS NOT NULL AND value > '-Infinity'::double precision AND value < 'Infinity'::double precision) OR (quality_status <> 'valid' AND value IS NULL))
);

CREATE TABLE weather_summaries (
    id uuid PRIMARY KEY,
    analysis_id uuid NOT NULL REFERENCES analyses(id),
    source_id text NOT NULL REFERENCES sources(id),
    variable text NOT NULL,
    unit text NOT NULL,
    period_start timestamptz NOT NULL,
    period_end timestamptz NOT NULL,
    statistic text NOT NULL,
    value double precision,
    spatial_method text NOT NULL,
    spatial_weights_uri text NOT NULL,
    input_manifest_uri text NOT NULL,
    temporal_coverage_fraction double precision NOT NULL CHECK (temporal_coverage_fraction BETWEEN 0 AND 1),
    spatial_coverage_fraction double precision NOT NULL CHECK (spatial_coverage_fraction BETWEEN 0 AND 1),
    status text NOT NULL CHECK (status IN ('supported','limited','missing')),
    reasons jsonb NOT NULL DEFAULT '[]',
    UNIQUE(analysis_id,source_id,variable,period_start,period_end,statistic),
    CHECK (period_end > period_start),
    CHECK (status <> 'missing' OR value IS NULL)
);

-- A report is a document; an extracted event is an uncertain claim within that document.
CREATE TABLE news_reports (
    id uuid PRIMARY KEY,
    asset_id uuid NOT NULL REFERENCES assets(id),
    canonical_url text NOT NULL,
    title text NOT NULL,
    publisher text NOT NULL,
    language text NOT NULL,
    published_at timestamptz,
    publication_precision text NOT NULL,
    retrieved_at timestamptz NOT NULL,
    content_sha256 text NOT NULL,
    summary text,
    original_reporting_url text,
    syndication_group text,
    source_lineage text NOT NULL CHECK (source_lineage IN ('field_report','official_incident','satellite_derived','mixed','unknown')),
    extraction_version text NOT NULL,
    review_status text NOT NULL CHECK (review_status IN ('unreviewed','reviewed','rejected')),
    UNIQUE(canonical_url,content_sha256,extraction_version)
);

CREATE TABLE reported_events (
    id uuid PRIMARY KEY,
    report_id uuid NOT NULL REFERENCES news_reports(id),
    claim_index integer NOT NULL,
    event_start date,
    event_end_exclusive date,
    date_precision text NOT NULL,
    place_text text,
    location geometry(Geometry,4326),
    location_precision text NOT NULL,
    location_uncertainty_m double precision CHECK (location_uncertainty_m >= 0),
    geocoding_method text,
    event_cluster_key text,
    reported_event_type text,
    reported_burned_area_ha double precision CHECK (reported_burned_area_ha >= 0),
    reported_cause text,
    claim_summary text NOT NULL,
    review_status text NOT NULL CHECK (review_status IN ('unreviewed','reviewed','rejected')),
    reviewed_by text,
    reviewed_at timestamptz,
    UNIQUE(report_id,claim_index),
    CHECK (event_end_exclusive IS NULL OR event_start IS NULL OR event_end_exclusive > event_start)
);

CREATE TABLE analysis_event_links (
    analysis_id uuid NOT NULL REFERENCES analyses(id),
    event_id uuid NOT NULL REFERENCES reported_events(id),
    relation text NOT NULL CHECK (relation IN ('candidate','consistent','conflicting','unresolved','rejected')),
    match_method_version text NOT NULL,
    temporal_match jsonb NOT NULL,
    spatial_match jsonb NOT NULL,
    independence text NOT NULL CHECK (independence IN ('independent','dependent','unknown')),
    evidence_note text NOT NULL,
    reviewed_by text,
    reviewed_at timestamptz,
    PRIMARY KEY(analysis_id,event_id,match_method_version)
);

-- Immutable, bounded facts sent to the explainer; includes IDs, values, units and citations.
CREATE TABLE evidence_snapshots (
    id uuid PRIMARY KEY,
    analysis_id uuid NOT NULL REFERENCES analyses(id),
    schema_version text NOT NULL,
    evidence_json jsonb NOT NULL,
    sha256 text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(analysis_id,sha256)
);

CREATE TABLE ai_explanations (
    id uuid PRIMARY KEY,
    snapshot_id uuid NOT NULL REFERENCES evidence_snapshots(id),
    language text NOT NULL,
    question text NOT NULL,
    provider text NOT NULL,
    model_id text NOT NULL,
    prompt_version text NOT NULL,
    tool_contract_version text NOT NULL,
    output_json jsonb,
    status text NOT NULL CHECK (status IN ('queued','running','validated','rejected','failed','template_fallback')),
    validation_report jsonb,
    tool_trace_uri text,
    input_tokens integer CHECK (input_tokens >= 0),
    output_tokens integer CHECK (output_tokens >= 0),
    cache_key text NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz
);

-- Stable metric registry: raw counts, source response and harmonized response differ.
CREATE TABLE metric_definitions (
    id text PRIMARY KEY,
    version text NOT NULL,
    unit text NOT NULL,
    family text NOT NULL CHECK (family IN ('native_detections','source_response','harmonized_response')),
    description text NOT NULL,
    definition jsonb NOT NULL,
    requires_masks boolean NOT NULL,
    requires_model boolean NOT NULL
);
ALTER TABLE daily_activity ADD FOREIGN KEY (metric_key) REFERENCES metric_definitions(id);
ALTER TABLE analyses ADD FOREIGN KEY (metric_key) REFERENCES metric_definitions(id);

-- One provider transport can emit several products (MODIS_NRT contains Terra and Aqua).
CREATE TABLE ingestion_feeds (
    id text PRIMARY KEY,
    provider text NOT NULL,
    adapter text NOT NULL,
    adapter_version text NOT NULL,
    endpoint_template text NOT NULL,
    credential_ref text,
    rate_limit_group text NOT NULL,
    capability_spec jsonb NOT NULL,
    state text NOT NULL CHECK (state IN ('active','paused','retired','unverified')),
    verified_at timestamptz
);
CREATE TABLE feed_sources (
    feed_id text NOT NULL REFERENCES ingestion_feeds(id),
    source_id text NOT NULL REFERENCES sources(id),
    selector jsonb NOT NULL,
    PRIMARY KEY(feed_id,source_id)
);
CREATE TABLE source_availability (
    feed_id text NOT NULL,
    source_id text NOT NULL,
    checked_at timestamptz NOT NULL,
    available_start timestamptz,
    available_end_exclusive timestamptz,
    status text NOT NULL CHECK (status IN ('available','partial','unavailable','unknown','retired')),
    evidence_asset_id uuid REFERENCES assets(id),
    detail jsonb NOT NULL,
    PRIMARY KEY(feed_id,source_id,checked_at),
    FOREIGN KEY(feed_id,source_id) REFERENCES feed_sources(feed_id,source_id),
    CHECK (available_end_exclusive IS NULL OR available_start IS NULL OR available_end_exclusive > available_start)
);

CREATE TABLE ingestion_subscriptions (
    id uuid PRIMARY KEY,
    feed_id text NOT NULL REFERENCES ingestion_feeds(id),
    area_id uuid NOT NULL REFERENCES areas(id),
    scope_key text NOT NULL,
    mode text NOT NULL CHECK (mode IN ('backfill','incremental','reconciliation')),
    interval_seconds integer NOT NULL CHECK (interval_seconds > 0),
    overlap_seconds integer NOT NULL CHECK (overlap_seconds >= 0),
    history_start timestamptz NOT NULL,
    fixed_end_exclusive timestamptz,
    request_config jsonb NOT NULL,
    config_sha256 text NOT NULL,
    enabled boolean NOT NULL DEFAULT false,
    next_due_at timestamptz,
    lease_owner text,
    lease_expires_at timestamptz,
    UNIQUE(feed_id,scope_key,mode,config_sha256),
    CHECK (fixed_end_exclusive IS NULL OR fixed_end_exclusive > history_start)
);

-- One logical bounded request attempt; pagination/response assets are recorded separately.
CREATE TABLE fetch_runs (
    id uuid PRIMARY KEY,
    subscription_id uuid NOT NULL REFERENCES ingestion_subscriptions(id),
    pipeline_run_id uuid REFERENCES pipeline_runs(id),
    request_key text NOT NULL,
    attempt integer NOT NULL CHECK (attempt > 0),
    query_start timestamptz NOT NULL,
    query_end_exclusive timestamptz NOT NULL,
    query_basis text NOT NULL CHECK (query_basis IN ('observation_time','provider_updated_time','publication_time','model_issue_time')),
    sanitized_request jsonb NOT NULL,
    status text NOT NULL CHECK (status IN ('queued','running','complete','partial','failed','not_modified')),
    enumeration_complete boolean NOT NULL DEFAULT false,
    page_count integer NOT NULL DEFAULT 0 CHECK (page_count >= 0),
    record_count bigint CHECK (record_count >= 0),
    started_at timestamptz,
    completed_at timestamptz,
    max_observation_at timestamptz,
    http_status integer,
    retry_after timestamptz,
    error_code text,
    UNIQUE(subscription_id,request_key,attempt),
    CHECK (query_end_exclusive > query_start)
);
CREATE TABLE fetch_assets (
    fetch_run_id uuid NOT NULL REFERENCES fetch_runs(id),
    asset_id uuid NOT NULL REFERENCES assets(id),
    role text NOT NULL CHECK (role IN ('catalog_page','payload','empty_result','availability','cached_payload')),
    page_key text NOT NULL,
    PRIMARY KEY(fetch_run_id,asset_id,role,page_key)
);

CREATE TABLE ingestion_checkpoints (
    subscription_id uuid NOT NULL REFERENCES ingestion_subscriptions(id),
    stage text NOT NULL CHECK (stage IN ('discovery','fetch','normalize','publish')),
    cursor_basis text NOT NULL,
    committed_until timestamptz,
    cursor_json jsonb NOT NULL DEFAULT '{}',
    last_success_run_id uuid REFERENCES fetch_runs(id),
    updated_at timestamptz NOT NULL,
    generation bigint NOT NULL DEFAULT 0 CHECK (generation >= 0),
    PRIMARY KEY(subscription_id,stage)
);
CREATE TABLE ingestion_gaps (
    id uuid PRIMARY KEY,
    subscription_id uuid NOT NULL REFERENCES ingestion_subscriptions(id),
    gap_start timestamptz NOT NULL,
    gap_end_exclusive timestamptz NOT NULL,
    kind text NOT NULL CHECK (kind IN ('fetch_failed','catalog_incomplete','missing_asset','missing_companion','provider_outage','retired_source','unknown')),
    status text NOT NULL CHECK (status IN ('open','retrying','resolved','accepted_unavailable')),
    discovered_at timestamptz NOT NULL,
    last_attempt_at timestamptz,
    retry_after timestamptz,
    resolved_by_run_id uuid REFERENCES fetch_runs(id),
    evidence jsonb NOT NULL,
    CHECK (gap_end_exclusive > gap_start)
);
CREATE TABLE quality_issues (
    id uuid PRIMARY KEY,
    pipeline_run_id uuid NOT NULL REFERENCES pipeline_runs(id),
    asset_id uuid REFERENCES assets(id),
    rule_id text NOT NULL,
    severity text NOT NULL CHECK (severity IN ('info','warning','blocking')),
    status text NOT NULL CHECK (status IN ('open','resolved','accepted')),
    affected_count bigint NOT NULL CHECK (affected_count >= 0),
    sample_locator jsonb NOT NULL,
    explanation text NOT NULL,
    resolution_note text,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- A partition is an immutable COMPLETE snapshot for a declared key/support, not a delta.
CREATE TABLE data_partitions (
    id uuid PRIMARY KEY,
    pipeline_run_id uuid NOT NULL REFERENCES pipeline_runs(id),
    kind text NOT NULL CHECK (kind IN ('detections','observations','features','daily_activity','weather','reports','tiles')),
    series_key text NOT NULL,
    partition_key text NOT NULL,
    support_spec jsonb NOT NULL,
    storage_uri text NOT NULL,
    sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    input_manifest_uri text NOT NULL,
    schema_version text NOT NULL,
    row_count bigint NOT NULL CHECK (row_count >= 0),
    serving_complete boolean NOT NULL,
    validation_status text NOT NULL CHECK (validation_status IN ('pending','validated','quarantined')),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(series_key,partition_key,sha256),
    UNIQUE(id,series_key,partition_key)
);
CREATE TABLE partition_detections (
    partition_id uuid NOT NULL REFERENCES data_partitions(id),
    detection_id bigint NOT NULL REFERENCES detections(id),
    PRIMARY KEY(partition_id,detection_id)
);
CREATE TABLE release_partitions (
    release_id uuid NOT NULL REFERENCES data_releases(id),
    series_key text NOT NULL,
    partition_key text NOT NULL,
    partition_id uuid NOT NULL,
    PRIMARY KEY(release_id,series_key,partition_key),
    FOREIGN KEY(partition_id,series_key,partition_key) REFERENCES data_partitions(id,series_key,partition_key)
);
CREATE TABLE partition_dependencies (
    partition_id uuid NOT NULL REFERENCES data_partitions(id),
    input_partition_id uuid NOT NULL REFERENCES data_partitions(id),
    role text NOT NULL,
    PRIMARY KEY(partition_id,input_partition_id,role),
    CHECK (partition_id <> input_partition_id)
);
CREATE TABLE release_aliases (
    alias text NOT NULL,
    scope_key text NOT NULL,
    release_id uuid NOT NULL REFERENCES data_releases(id),
    generation bigint NOT NULL DEFAULT 0 CHECK (generation >= 0),
    updated_at timestamptz NOT NULL,
    PRIMARY KEY(alias,scope_key)
);
CREATE TABLE release_changes (
    id uuid PRIMARY KEY,
    from_release_id uuid NOT NULL REFERENCES data_releases(id),
    to_release_id uuid NOT NULL REFERENCES data_releases(id),
    series_key text NOT NULL,
    affected_start timestamptz NOT NULL,
    affected_end_exclusive timestamptz NOT NULL,
    affected_area geometry(MultiPolygon,4326),
    reason text NOT NULL CHECK (reason IN ('new_data','late_data','provider_revision','standard_replacement','retraction','method_change','weather_revision','report_revision')),
    diff_manifest_uri text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (from_release_id <> to_release_id),
    CHECK (affected_end_exclusive > affected_start)
);

-- Each analysis pins separate satellite/weather/report releases, including missing components.
CREATE TABLE analysis_components (
    analysis_id uuid NOT NULL REFERENCES analyses(id),
    component text NOT NULL CHECK (component IN ('satellite','weather_historical','weather_recent','reports')),
    release_id uuid REFERENCES data_releases(id),
    status text NOT NULL CHECK (status IN ('ready','partial','missing','unsupported','failed','not_requested')),
    reasons jsonb NOT NULL DEFAULT '[]',
    PRIMARY KEY(analysis_id,component),
    CHECK ((status IN ('ready','partial') AND release_id IS NOT NULL) OR status NOT IN ('ready','partial'))
);
CREATE TABLE api_jobs (
    id uuid PRIMARY KEY,
    kind text NOT NULL CHECK (kind IN ('analysis','explanation','export','backfill','refresh')),
    analysis_id uuid REFERENCES analyses(id),
    explanation_id uuid REFERENCES ai_explanations(id),
    requested_by text NOT NULL,
    request_hash text NOT NULL,
    idempotency_key text NOT NULL,
    request_spec jsonb NOT NULL,
    status text NOT NULL CHECK (status IN ('queued','running','succeeded','partial','failed','cancelled')),
    attempt integer NOT NULL DEFAULT 0 CHECK (attempt >= 0),
    lease_expires_at timestamptz,
    progress jsonb NOT NULL DEFAULT '{}',
    result_manifest_uri text,
    result_sha256 text,
    result_byte_size bigint CHECK (result_byte_size >= 0),
    expires_at timestamptz,
    error_code text,
    created_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    UNIQUE(requested_by,idempotency_key)
);
CREATE TABLE outbox_events (
    id uuid PRIMARY KEY,
    event_type text NOT NULL,
    aggregate_id text NOT NULL,
    dedupe_key text NOT NULL UNIQUE,
    payload jsonb NOT NULL,
    status text NOT NULL CHECK (status IN ('pending','dispatching','delivered')),
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    available_at timestamptz NOT NULL,
    lease_expires_at timestamptz,
    delivered_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX assets_footprint_gist ON assets USING gist(footprint);
CREATE INDEX areas_geom_gist ON areas USING gist(geom);
CREATE INDEX grid_cells_geom_gist ON grid_cells USING gist(geom);
CREATE INDEX detections_geom_gist ON detections USING gist(geom);
CREATE INDEX detections_source_time ON detections(source_id,acquired_at);
CREATE INDEX observations_cell_time ON observations(release_id,cell_id,representative_time);
CREATE INDEX pairs_split ON matched_pairs(release_id,series_key,split_name);
CREATE INDEX daily_activity_period ON daily_activity(release_id,reporting_date,metric_key);
CREATE INDEX weather_location_geom_gist ON weather_locations USING gist(geom);
CREATE INDEX weather_values_lookup ON weather_values(location_id,variable,valid_start);
CREATE INDEX reported_events_geom_gist ON reported_events USING gist(location);
CREATE INDEX reported_events_dates ON reported_events(event_start,event_end_exclusive);
CREATE INDEX news_reports_published ON news_reports(published_at);
CREATE INDEX news_reports_search ON news_reports USING gin(to_tsvector('simple',title || ' ' || coalesce(summary,'')));
CREATE INDEX subscriptions_due ON ingestion_subscriptions(next_due_at) WHERE enabled;
CREATE INDEX fetch_runs_recent ON fetch_runs(subscription_id,started_at DESC);
CREATE INDEX gaps_pending ON ingestion_gaps(status,retry_after);
CREATE INDEX issues_run ON quality_issues(pipeline_run_id,severity,status);
CREATE INDEX partitions_key ON data_partitions(series_key,partition_key,created_at DESC);
CREATE INDEX partition_detections_reverse ON partition_detections(detection_id,partition_id);
CREATE INDEX source_availability_recent ON source_availability(feed_id,source_id,checked_at DESC);
CREATE INDEX release_changes_to ON release_changes(to_release_id);
CREATE INDEX jobs_status ON api_jobs(status,created_at);
CREATE INDEX outbox_due ON outbox_events(available_at) WHERE status <> 'delivered';
