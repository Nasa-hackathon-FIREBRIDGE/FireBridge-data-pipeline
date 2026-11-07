-- Precipitation belongs to its interval START date, not the following sample timestamp.
-- Only a full 24 valid UTC hours yields a daily value; partial days remain explicit.
with samples as (
 select i.build_id,i.scope_key,(w.valid_start at time zone 'UTC')::date as date_utc,
 w.location_id,w.source_id,w.release_id as weather_release_id,w.data_kind,w.latitude,w.longitude,
 w.variable,w.unit,w.value,w.quality_status,w.valid_start,w.valid_end
 from {{ source('serving','weather') }} w
 join {{ ref('stg_inputs') }} i on i.release_id=w.release_id and i.alias in ('weather_historical','weather_recent')
 -- A daily mean direction requires circular statistics; do not take an arithmetic mean.
 where w.variable<>'wind_direction_10m'
)
select build_id,scope_key,date_utc,location_id,source_id,weather_release_id,data_kind,latitude,longitude,
 variable,unit,case when variable='precipitation' then 'sum' else 'mean' end::text as aggregation,
 count(*) as sample_count,count(value) filter(where quality_status='valid') as valid_sample_count,
 case when count(*)=24 and count(value) filter(where quality_status='valid')=24 then
   case when variable='precipitation' then sum(value) else avg(value) end
 else null end::double precision as value,
 (count(*)=24 and count(value) filter(where quality_status='valid')=24) as complete_day
from samples group by 1,2,3,4,5,6,7,8,9,10,11
