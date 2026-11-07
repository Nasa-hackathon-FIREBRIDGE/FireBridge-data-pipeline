select * from {{ ref('daily_weather') }}
where sample_count>24 or valid_sample_count>sample_count
 or (not complete_day and value is not null)
 or (complete_day and (sample_count<>24 or valid_sample_count<>24 or value is null))
