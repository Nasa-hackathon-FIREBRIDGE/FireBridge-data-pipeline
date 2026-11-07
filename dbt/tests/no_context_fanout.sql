select build_id,date_utc from {{ ref('area_daily_context') }}
group by 1,2 having count(*)<>1
