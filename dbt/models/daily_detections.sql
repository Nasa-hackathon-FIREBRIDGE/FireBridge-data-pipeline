with stats as (
 select release_id,source_id,(acquired_at at time zone 'UTC')::date as date_utc,
 count(*) as detection_count,count(frp_mw) as frp_sample_count,
 avg(frp_mw) as frp_mean_mw,max(frp_mw) as frp_max_mw
 from {{ ref('stg_detections') }} group by 1,2,3
)
select p.build_id,p.scope_key,p.date_utc,p.source_id,p.platform,p.processing_stream,
 p.release_id as satellite_release_id,coalesce(s.detection_count,0)::bigint as detection_count,
 coalesce(s.frp_sample_count,0)::bigint as frp_sample_count,s.frp_mean_mw,s.frp_max_mw
from {{ ref('stg_satellite_partitions') }} p
left join stats s on s.release_id=p.release_id and s.source_id=p.source_id and s.date_utc=p.date_utc
