select d.build_id from {{ ref('daily_detections') }} d
left join {{ ref('stg_inputs') }} i on i.release_id=d.satellite_release_id and i.alias='best_available'
where i.release_id is null or d.build_id<>{{ build_id() }}
