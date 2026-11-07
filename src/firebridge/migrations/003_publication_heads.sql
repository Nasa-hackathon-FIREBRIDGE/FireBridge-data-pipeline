SET LOCAL search_path=firebridge,public;
CREATE TABLE partition_heads (
 scope_key text NOT NULL,
 series_key text NOT NULL,
 partition_key text NOT NULL,
 partition_id uuid NOT NULL REFERENCES data_partitions(id),
 accepted_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(scope_key,series_key,partition_key)
);
CREATE VIEW serving.release_events AS SELECT id,aggregate_id AS release_id,payload,created_at
 FROM outbox_events WHERE event_type='release.published';
