-- Read-only Node.js handoff queries. All statements execute as firebridge_reader.
-- Resolve the release once; the application persists that ID.
PREPARE fb_latest(text,text) AS
 SELECT release_id,generation,published_at FROM serving.latest_releases WHERE scope_key=$1 AND alias=$2;

PREPARE fb_points(uuid,timestamptz,timestamptz,text[],float8,float8,float8,float8,timestamptz,bigint,int) AS
 SELECT id::text,source_id,acquired_at,longitude,latitude,confidence_raw,confidence_scheme,frp_mw,processing_level
 FROM serving.detections WHERE release_id=$1 AND acquired_at >= $2 AND acquired_at < $3
 AND source_id=ANY($4) AND ST_Covers(ST_MakeEnvelope($5,$6,$7,$8,4326),geom)
 AND ($9 IS NULL OR (acquired_at,id)>($9,$10)) ORDER BY acquired_at,id LIMIT $11;

-- Whole registered scope. Each selected source/day partition is complete.
-- Dates absent from partitions stay missing; the API supplies the requested date scaffold if needed.
PREPARE fb_daily(uuid,date,date) AS
 WITH partition_days AS (
   SELECT partition_key::date AS day,support_spec->>'source_id' AS source_id,
     support_spec->>'processing_stream' AS processing_stream,
     support_spec->>'period_state' AS period_state,row_count
   FROM serving.partitions WHERE release_id=$1 AND kind='detections'
     AND serving_complete AND partition_key::date >=$2 AND partition_key::date <$3
 ) SELECT day,source_id,row_count AS detection_count,processing_stream,period_state,
   'unknown'::text AS observation_coverage FROM partition_days ORDER BY day,source_id;

PREPARE fb_weather(uuid,timestamptz,timestamptz) AS
 SELECT id::text,location_id,source_id,variable,unit,valid_start,valid_end,value,quality_status,
   statistic,data_kind,issued_at,longitude,latitude,support_kind
 FROM serving.weather WHERE release_id=$1 AND valid_end >= $2 AND valid_start < $3
 ORDER BY valid_start,variable,id;

PREPARE fb_reports(uuid) AS
 SELECT r.id,r.title,r.canonical_url,r.published_at,r.review_status,r.source_lineage,
   e.event_start,e.event_end_exclusive,e.location_precision,e.claim_summary
 FROM serving.reports r LEFT JOIN serving.reported_events e ON e.report_id=r.id WHERE r.release_id=$1;

PREPARE fb_events(timestamptz,uuid,int) AS
 SELECT * FROM serving.release_events WHERE (created_at,id)>($1,$2) ORDER BY created_at,id LIMIT $3;
