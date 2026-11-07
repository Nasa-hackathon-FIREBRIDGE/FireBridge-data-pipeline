CREATE TABLE firebridge.ingestion_scopes (
 scope_key text PRIMARY KEY,
 area_id uuid NOT NULL REFERENCES firebridge.areas(id),
 created_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO firebridge.ingestion_scopes(scope_key,area_id)
 SELECT name,id FROM firebridge.areas WHERE name IN ('global','morocco-pilot') ON CONFLICT DO NOTHING;
CREATE VIEW serving.scopes AS SELECT s.scope_key,s.area_id,a.geometry_sha256,
 ST_AsGeoJSON(a.geom)::jsonb AS geometry FROM firebridge.ingestion_scopes s JOIN firebridge.areas a ON a.id=s.area_id;
