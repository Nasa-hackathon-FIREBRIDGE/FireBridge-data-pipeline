SET LOCAL search_path=firebridge,public;
CREATE TABLE science_granules (
 id uuid PRIMARY KEY,
 collection_concept_id text NOT NULL,
 concept_id text NOT NULL,
 revision_key text NOT NULL,
 asset_id uuid NOT NULL REFERENCES assets(id),
 time_start timestamptz,
 time_end timestamptz,
 updated_at timestamptz,
 metadata jsonb NOT NULL,
 UNIQUE(concept_id,revision_key)
);
CREATE VIEW serving.science_inventory AS SELECT id,collection_concept_id,concept_id,revision_key,
 asset_id,time_start,time_end,updated_at,'catalogued_not_decoded'::text AS status FROM science_granules;
