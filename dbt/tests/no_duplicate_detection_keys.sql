select source_id,date_utc from {{ ref('daily_detections') }}
group by 1,2 having count(*)<>1
