-- Design examples only. PREPARE these in an empty test deployment after schema.sql.
-- No database queries have been executed in this architecture task.
SET search_path = firebridge, public;

-- 1. Canonical native detections for a UTC analysis, stable cursor pagination.
-- $1 analysis UUID; $2/$3 narrowed UTC bounds; $4/$5 cursor (both NULL on first page);
-- $6 bounded page size. App verifies authorization, source filters, serving completeness.
PREPARE fb_detection_page(uuid,timestamptz,timestamptz,timestamptz,bigint,integer) AS
WITH selection AS (
    SELECT a.*, ar.geom FROM analyses a JOIN areas ar ON ar.id=a.area_id
    WHERE a.id=$1 AND a.time_basis='UTC' AND a.status IN ('ready','partial')
), members AS (
    SELECT DISTINCT pd.detection_id
    FROM selection a
    JOIN release_partitions rp ON rp.release_id=a.release_id
    JOIN data_partitions p ON p.id=rp.partition_id AND p.kind='detections'
    JOIN partition_detections pd ON pd.partition_id=p.id
    WHERE p.validation_status='validated'
)
SELECT d.id,d.source_id,d.acquired_at,ST_AsGeoJSON(d.geom)::jsonb AS geometry,
       d.confidence_raw,d.confidence_scheme,d.frp_mw,d.processing_level
FROM selection a CROSS JOIN members m JOIN detections d ON d.id=m.detection_id
WHERE d.acquired_at>=GREATEST($2,a.start_date::timestamp AT TIME ZONE 'UTC')
  AND d.acquired_at<LEAST($3,a.end_date_exclusive::timestamp AT TIME ZONE 'UTC')
  AND ST_Covers(a.geom,d.geom)
  AND d.source_id IN (SELECT jsonb_array_elements_text(a.request_spec->'source_ids'))
  AND (($4 IS NULL AND $5 IS NULL) OR (d.acquired_at,d.id)>($4,$5))
ORDER BY d.acquired_at,d.id
LIMIT $6;

-- 2. Area-weighted response for a single analysis period.
-- Requires a dense, verified daily product (including missing states), land weights
-- from the analysis grid/policy and a comparable metric. $2/$3 are half-open dates.
-- Return NULL, not 0, when no eligible area-days exist; possible support is independent.
PREPARE fb_comparable_period(uuid,date,date) AS
WITH selection AS (
    SELECT * FROM analyses WHERE id=$1
), weights AS (
    SELECT ac.cell_id,ac.overlap_land_area_m2 AS weight
    FROM selection a
    JOIN area_cells ac ON ac.area_id=a.area_id AND ac.weighting_version=a.weighting_version
    JOIN grid_cells g ON g.id=ac.cell_id AND g.grid_id=a.grid_id
), bounds AS (
    SELECT GREATEST($2,start_date) AS first_day,
           LEAST($3,end_date_exclusive) AS end_day FROM selection
), total_support AS (
    SELECT SUM(weight) * (b.end_day-b.first_day) AS possible_m2_days
    FROM weights CROSS JOIN bounds b GROUP BY b.end_day,b.first_day
), eligible AS (
    SELECT w.weight,d.response_value,d.status
    FROM selection a
    JOIN daily_activity d ON d.release_id=a.release_id
        AND d.metric_key=a.metric_key AND d.time_basis=a.time_basis
        AND d.selection_policy=a.selection_policy
    JOIN weights w ON w.cell_id=d.cell_id CROSS JOIN bounds b
    WHERE d.reporting_date>=b.first_day AND d.reporting_date<b.end_day
      AND d.status IN ('reference_observed','source_estimated')
), sums AS (
    SELECT COALESCE(SUM(weight*response_value),0) AS numerator,
           COALESCE(SUM(weight),0) AS denominator,
           COALESCE(SUM(weight) FILTER (WHERE status='reference_observed'),0) AS observed_weight,
           COUNT(*) AS valid_cell_days FROM eligible
)
SELECT numerator,denominator,possible_m2_days,
       numerator/NULLIF(denominator,0) AS response,
       denominator/NULLIF(possible_m2_days,0) AS coverage_fraction,
       observed_weight/NULLIF(denominator,0) AS observed_fraction,valid_cell_days
FROM sums CROSS JOIN total_support;

-- 3. Transport health for a subscription. Empty successful queries still advance success.
-- Never use max_observation_at to infer local clear coverage or a per-platform clock
-- when the feed includes multiple satellites.
PREPARE fb_subscription_health(uuid) AS
SELECT s.id,s.feed_id,s.scope_key,s.enabled,s.next_due_at,
       MAX(f.started_at) AS last_attempt_at,
       MAX(f.completed_at) FILTER (WHERE f.status IN ('complete','not_modified') AND f.enumeration_complete) AS last_success_at,
       c.committed_until AS queried_through,
       (SELECT COUNT(*) FROM ingestion_gaps g WHERE g.subscription_id=s.id AND g.status IN ('open','retrying')) AS open_gaps
FROM ingestion_subscriptions s
LEFT JOIN fetch_runs f ON f.subscription_id=s.id
LEFT JOIN ingestion_checkpoints c ON c.subscription_id=s.id AND c.stage='fetch'
WHERE s.id=$1
GROUP BY s.id,s.feed_id,s.scope_key,s.enabled,s.next_due_at,c.committed_until;

-- 4. Atomic alias compare-and-swap is part of a larger publication transaction.
-- A zero-row result means concurrent change: abort/rebase, never overwrite blindly.
-- Insert the release publication outbox event in the SAME transaction as this UPDATE.
PREPARE fb_advance_alias(text,text,bigint,uuid) AS
UPDATE release_aliases a
SET release_id=$4,generation=a.generation+1,updated_at=now()
FROM data_releases r
WHERE a.alias=$1 AND a.scope_key=$2 AND a.generation=$3
  AND r.id=$4 AND r.status='published' AND r.scope_key=a.scope_key
RETURNING a.alias,a.scope_key,a.release_id,a.generation;
