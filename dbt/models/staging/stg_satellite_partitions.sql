select i.build_id,i.scope_key,p.release_id,p.partition_id,p.partition_key::date as date_utc,
 p.support_spec->>'source_id' as source_id,
 regexp_replace(p.support_spec->>'source_id','-(standard|nrt)$','') as source_family,
 s.platform,s.processing_stream,p.row_count,p.serving_complete,p.validation_status,
 p.support_spec->>'period_state' as period_state
from {{ source('serving','partitions') }} p
join {{ ref('stg_inputs') }} i on i.release_id=p.release_id and i.alias='best_available'
join {{ source('serving','sources') }} s on s.id=p.support_spec->>'source_id'
where p.kind='detections'
