select * from {{ ref('query_coverage') }}
where (query_status='missing' and detection_count is not null)
 or (query_status='complete_empty' and detection_count is distinct from 0)
 or (query_status='complete_with_detections' and coalesce(detection_count,0)<=0)
 or observation_coverage<>'unknown'
