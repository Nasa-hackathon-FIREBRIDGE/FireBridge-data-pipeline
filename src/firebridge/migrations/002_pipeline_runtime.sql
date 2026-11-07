SET LOCAL search_path=firebridge,public;
-- Durable execution queue. Separate from the backend team's API job table.
CREATE TABLE ingest_tasks (
    id uuid PRIMARY KEY,
    subscription_id uuid REFERENCES ingestion_subscriptions(id),
    kind text NOT NULL CHECK (kind IN ('firms','weather','availability','cmr')),
    request jsonb NOT NULL,
    dedupe_key text NOT NULL UNIQUE,
    status text NOT NULL CHECK (status IN ('queued','running','succeeded','failed','blocked')),
    attempt integer NOT NULL DEFAULT 0,
    max_attempts integer NOT NULL DEFAULT 5 CHECK (max_attempts>0),
    available_at timestamptz NOT NULL DEFAULT now(),
    lease_token uuid,
    lease_expires_at timestamptz,
    error_code text,
    result jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz
);
CREATE INDEX ingest_tasks_due ON ingest_tasks(available_at) WHERE status IN ('queued','running');
CREATE TABLE provider_budgets (
    id text PRIMARY KEY,
    window_start timestamptz NOT NULL,
    used integer NOT NULL DEFAULT 0,
    blocked_until timestamptz
);
CREATE TABLE partition_weather_values (
    partition_id uuid NOT NULL REFERENCES data_partitions(id),
    weather_value_id bigint NOT NULL REFERENCES weather_values(id),
    PRIMARY KEY(partition_id,weather_value_id)
);
CREATE TABLE partition_reports (
    partition_id uuid NOT NULL REFERENCES data_partitions(id),
    report_id uuid NOT NULL REFERENCES news_reports(id),
    PRIMARY KEY(partition_id,report_id)
);
-- Manifests can include an empty snapshot, so input lineage cannot rely on rows.
CREATE TABLE partition_assets (
    partition_id uuid NOT NULL REFERENCES data_partitions(id),
    asset_id uuid NOT NULL REFERENCES assets(id),
    PRIMARY KEY(partition_id,asset_id)
);
CREATE INDEX detections_time ON detections(acquired_at,id);
CREATE INDEX weather_partition_value ON partition_weather_values(weather_value_id,partition_id);

CREATE SCHEMA serving;
CREATE VIEW serving.sources AS SELECT id,name,provider,kind,platform,instrument,product,
 collection,processing_stream,documentation_url,citation,license_info,native_resolution_m,metadata FROM sources;
CREATE VIEW serving.areas AS SELECT id,name,version,ST_AsGeoJSON(geom)::jsonb AS geometry,
 geometry_sha256,display_timezone,provenance FROM areas;
CREATE VIEW serving.releases AS SELECT id,name,status,stream,dataset_kind,scope_key,
 parent_release_id,observation_cutoff,created_at,published_at,config,code_version
 FROM data_releases WHERE status='published';
CREATE VIEW serving.latest_releases AS SELECT a.*,r.dataset_kind,r.stream,r.observation_cutoff,
 r.published_at FROM release_aliases a JOIN data_releases r ON r.id=a.release_id WHERE r.status='published';
CREATE VIEW serving.partitions AS SELECT rp.release_id,p.id AS partition_id,p.kind,p.series_key,
 p.partition_key,p.support_spec,p.row_count,p.serving_complete,p.validation_status,p.sha256
 FROM release_partitions rp JOIN data_partitions p ON p.id=rp.partition_id
 JOIN data_releases r ON r.id=rp.release_id WHERE r.status='published';
CREATE VIEW serving.detections AS SELECT rp.release_id,r.scope_key,d.id,d.source_id,d.acquired_at,
 d.geom,ST_X(d.geom) AS longitude,ST_Y(d.geom) AS latitude,d.confidence_raw,d.confidence_scheme,
 d.type_raw,d.day_night,d.frp_mw,d.processing_level,d.brightness_bands,d.scan_km,d.track_km,
 d.cross_track_sample,d.asset_id,d.record_sha256,p.support_spec
 FROM release_partitions rp JOIN data_releases r ON r.id=rp.release_id
 JOIN data_partitions p ON p.id=rp.partition_id
 JOIN partition_detections pd ON pd.partition_id=p.id JOIN detections d ON d.id=pd.detection_id
 WHERE r.status='published' AND p.serving_complete AND p.validation_status='validated';
CREATE VIEW serving.weather AS SELECT rp.release_id,w.id,w.source_id,w.variable,w.unit,w.valid_start,
 w.valid_end,w.issued_at,w.available_at,w.data_kind,w.statistic,w.value,w.quality_status,
 w.asset_id,w.derivation,l.support_kind,l.geom,ST_X(l.geom) AS longitude,ST_Y(l.geom) AS latitude,
 l.metadata AS location_metadata,p.support_spec
 FROM release_partitions rp JOIN data_releases r ON r.id=rp.release_id
 JOIN partition_weather_values pw ON pw.partition_id=rp.partition_id
 JOIN data_partitions p ON p.id=rp.partition_id JOIN weather_values w ON w.id=pw.weather_value_id
 JOIN weather_locations l ON l.id=w.location_id WHERE r.status='published';
CREATE VIEW serving.reports AS SELECT rp.release_id,n.id,n.canonical_url,n.title,n.publisher,n.language,
 n.published_at,n.publication_precision,n.summary,n.source_lineage,n.review_status,
 n.original_reporting_url,n.syndication_group,n.content_sha256,n.asset_id
 FROM release_partitions rp JOIN data_releases r ON r.id=rp.release_id
 JOIN partition_reports pr ON pr.partition_id=rp.partition_id JOIN news_reports n ON n.id=pr.report_id
 WHERE r.status='published';
CREATE VIEW serving.reported_events AS SELECT e.* FROM reported_events e
 WHERE EXISTS (SELECT 1 FROM serving.reports n WHERE n.id=e.report_id);
CREATE VIEW serving.source_availability AS SELECT * FROM source_availability;
CREATE VIEW serving.ingestion_health AS SELECT s.id,s.feed_id,s.scope_key,s.mode,s.enabled,s.next_due_at,
 c.committed_until AS queried_through,c.updated_at AS last_success_at,
 (SELECT count(*) FROM ingestion_gaps g WHERE g.subscription_id=s.id AND g.status IN ('open','retrying')) AS open_gaps,
 (SELECT max(f.started_at) FROM fetch_runs f WHERE f.subscription_id=s.id) AS last_attempt_at
 FROM ingestion_subscriptions s LEFT JOIN ingestion_checkpoints c ON c.subscription_id=s.id AND c.stage='publish';
CREATE VIEW serving.release_changes AS SELECT id,from_release_id,to_release_id,series_key,
 affected_start,affected_end_exclusive,reason,created_at FROM release_changes;
CREATE VIEW serving.asset_provenance AS SELECT id,source_id,native_key,revision,source_url,sha256,
 byte_size,time_start,time_end,retrieved_at,validation_status,metadata FROM assets;
