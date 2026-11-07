-- Aggregate each grain separately before combining. No detection/weather/article fan-out.
with dates as (
 select build_id,scope_key,date_utc from {{ ref('query_coverage') }}
 union select build_id,scope_key,date_utc from {{ ref('daily_weather') }}
 union select build_id,scope_key,date_utc from {{ ref('daily_reports') }}
), detections as (
 select build_id,date_utc,jsonb_agg(to_jsonb(d)-'build_id'-'scope_key'-'date_utc' order by source_id) as values
 from {{ ref('daily_detections') }} d group by 1,2
), coverage as (
 select build_id,date_utc,jsonb_agg(to_jsonb(c)-'build_id'-'scope_key'-'date_utc' order by source_family) as values
 from {{ ref('query_coverage') }} c group by 1,2
), weather as (
 select build_id,date_utc,jsonb_agg(to_jsonb(w)-'build_id'-'scope_key'-'date_utc' order by source_id,location_id,variable) as values
 from {{ ref('daily_weather') }} w group by 1,2
), reports as (
 select build_id,date_utc,jsonb_agg(to_jsonb(r)-'build_id'-'scope_key'-'date_utc') as values
 from {{ ref('daily_reports') }} r group by 1,2
)
select t.build_id,t.scope_key,t.date_utc,
 coalesce(d.values,'[]'::jsonb) as detections_by_source,
 coalesce(c.values,'[]'::jsonb) as query_coverage,
 coalesce(w.values,'[]'::jsonb) as weather_samples,
 coalesce(r.values,'[]'::jsonb) as reports
from dates t
left join detections d using(build_id,date_utc)
left join coverage c using(build_id,date_utc)
left join weather w using(build_id,date_utc)
left join reports r using(build_id,date_utc)
