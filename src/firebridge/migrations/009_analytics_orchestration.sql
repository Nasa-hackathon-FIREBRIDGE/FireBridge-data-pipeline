SET LOCAL search_path=firebridge,public;

-- Exactly one scheduling authority for the shared ingestion ledger.
CREATE TABLE orchestration_control (
 singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
 owner text NOT NULL CHECK(owner IN ('local','airflow')),
 changed_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO orchestration_control(singleton,owner) VALUES(true,'local');
ALTER TABLE ingest_tasks ADD COLUMN orchestrator text NOT NULL DEFAULT 'local'
 CHECK(orchestrator IN ('local','airflow'));

CREATE TABLE analytics_builds (
 id uuid PRIMARY KEY,
 scope_key text NOT NULL,
 signature text NOT NULL,
 model_sha256 text NOT NULL,
 status text NOT NULL CHECK(status IN ('building','published','failed')),
 input_releases jsonb NOT NULL,
 started_at timestamptz NOT NULL DEFAULT now(),
 finished_at timestamptz,
 error_code text,
 artifacts_uri text
);
CREATE TABLE analytics_inputs (
 build_id uuid NOT NULL REFERENCES analytics_builds(id),
 alias text NOT NULL,
 release_id uuid NOT NULL REFERENCES data_releases(id),
 PRIMARY KEY(build_id,alias)
);
CREATE TABLE analytics_latest (
 scope_key text PRIMARY KEY,
 build_id uuid NOT NULL REFERENCES analytics_builds(id),
 published_at timestamptz NOT NULL DEFAULT now()
);
CREATE SCHEMA analytics;
CREATE TABLE analytics.daily_detections (
 build_id uuid NOT NULL REFERENCES analytics_builds(id), scope_key text NOT NULL,
 date_utc date NOT NULL, source_id text NOT NULL, platform text NOT NULL,
 processing_stream text NOT NULL, satellite_release_id uuid NOT NULL REFERENCES data_releases(id),
 detection_count bigint NOT NULL CHECK(detection_count>=0),
 frp_sample_count bigint NOT NULL, frp_mean_mw double precision, frp_max_mw double precision,
 PRIMARY KEY(build_id,source_id,date_utc)
);
CREATE TABLE analytics.query_coverage (
 build_id uuid NOT NULL REFERENCES analytics_builds(id), scope_key text NOT NULL,
 date_utc date NOT NULL, source_family text NOT NULL, platform text NOT NULL,
 source_id text, satellite_release_id uuid NOT NULL REFERENCES data_releases(id),
 query_status text NOT NULL CHECK(query_status IN ('missing','complete_empty','complete_with_detections')),
 period_state text, detection_count bigint, observation_coverage text NOT NULL CHECK(observation_coverage='unknown'),
 PRIMARY KEY(build_id,source_family,date_utc)
);
CREATE TABLE analytics.daily_weather (
 build_id uuid NOT NULL REFERENCES analytics_builds(id), scope_key text NOT NULL,
 date_utc date NOT NULL, location_id uuid NOT NULL, source_id text NOT NULL,
 weather_release_id uuid NOT NULL REFERENCES data_releases(id), data_kind text NOT NULL,
 latitude double precision NOT NULL, longitude double precision NOT NULL,
 variable text NOT NULL, unit text NOT NULL, aggregation text NOT NULL,
 sample_count bigint NOT NULL, valid_sample_count bigint NOT NULL,
 value double precision, complete_day boolean NOT NULL,
 PRIMARY KEY(build_id,location_id,variable,date_utc,weather_release_id)
);
CREATE TABLE analytics.daily_reports (
 build_id uuid NOT NULL REFERENCES analytics_builds(id), scope_key text NOT NULL,
 date_utc date NOT NULL, reports_release_id uuid NOT NULL REFERENCES data_releases(id),
 article_count bigint NOT NULL, reviewed_count bigint NOT NULL,
 articles jsonb NOT NULL,
 PRIMARY KEY(build_id,date_utc,reports_release_id)
);
CREATE TABLE analytics.area_daily_context (
 build_id uuid NOT NULL REFERENCES analytics_builds(id), scope_key text NOT NULL,
 date_utc date NOT NULL, detections_by_source jsonb NOT NULL,
 query_coverage jsonb NOT NULL, weather_samples jsonb NOT NULL, reports jsonb NOT NULL,
 PRIMARY KEY(build_id,date_utc)
);
CREATE VIEW serving.analytics_inputs AS SELECT * FROM analytics_inputs;
CREATE VIEW serving.analytics_builds AS SELECT * FROM analytics_builds;
CREATE VIEW serving.latest_analytics AS SELECT l.*,b.input_releases,b.model_sha256,b.finished_at
 FROM analytics_latest l JOIN analytics_builds b ON b.id=l.build_id WHERE b.status='published';
CREATE VIEW serving.daily_detections AS SELECT m.* FROM analytics.daily_detections m
 JOIN analytics_builds b ON b.id=m.build_id WHERE b.status='published';
CREATE VIEW serving.query_coverage AS SELECT m.* FROM analytics.query_coverage m
 JOIN analytics_builds b ON b.id=m.build_id WHERE b.status='published';
CREATE VIEW serving.daily_weather AS SELECT m.* FROM analytics.daily_weather m
 JOIN analytics_builds b ON b.id=m.build_id WHERE b.status='published';
CREATE VIEW serving.daily_reports AS SELECT m.* FROM analytics.daily_reports m
 JOIN analytics_builds b ON b.id=m.build_id WHERE b.status='published';
CREATE VIEW serving.area_daily_context AS SELECT m.* FROM analytics.area_daily_context m
 JOIN analytics_builds b ON b.id=m.build_id WHERE b.status='published';
CREATE VIEW serving.task_health AS SELECT id,subscription_id,kind,orchestrator,status,
 attempt,error_code,created_at,completed_at FROM ingest_tasks;
