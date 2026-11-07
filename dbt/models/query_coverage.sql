with limits as (
 select min(date_utc) as lo,max(date_utc) as hi from {{ ref('stg_satellite_partitions') }}
), families as (
 select distinct build_id,scope_key,source_family,platform,release_id from {{ ref('stg_satellite_partitions') }}
), calendar as (
 select d::date as date_utc from limits,generate_series(lo,hi,interval '1 day') d
)
select f.build_id,f.scope_key,c.date_utc,f.source_family,f.platform,p.source_id,
 f.release_id as satellite_release_id,
 case when p.partition_id is null then 'missing'
      when p.row_count=0 then 'complete_empty' else 'complete_with_detections' end::text as query_status,
 p.period_state,p.row_count as detection_count,'unknown'::text as observation_coverage
from families f cross join calendar c
left join {{ ref('stg_satellite_partitions') }} p
 on p.source_family=f.source_family and p.date_utc=c.date_utc and p.release_id=f.release_id
