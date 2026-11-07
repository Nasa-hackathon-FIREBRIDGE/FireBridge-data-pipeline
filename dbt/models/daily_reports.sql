select i.build_id,i.scope_key,(r.published_at at time zone 'UTC')::date as date_utc,
 r.release_id as reports_release_id,count(*) as article_count,
 count(*) filter(where r.review_status='reviewed') as reviewed_count,
 jsonb_agg(jsonb_build_object('report_id',r.id,'url',r.canonical_url,'title',r.title,
   'published_at',r.published_at,'review_status',r.review_status,'date_basis','publication_date') order by r.id) as articles
from {{ source('serving','reports') }} r
join {{ ref('stg_inputs') }} i on i.release_id=r.release_id and i.alias='reports'
where r.published_at is not null and r.review_status<>'rejected'
group by 1,2,3,4
