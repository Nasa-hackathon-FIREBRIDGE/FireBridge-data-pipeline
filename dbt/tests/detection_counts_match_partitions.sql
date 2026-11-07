select p.partition_id from {{ ref('stg_satellite_partitions') }} p
left join {{ ref('daily_detections') }} d
 on d.source_id=p.source_id and d.date_utc=p.date_utc and d.satellite_release_id=p.release_id
where d.detection_count is distinct from p.row_count
 or not p.serving_complete or p.validation_status<>'validated'
