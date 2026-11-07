select i.*, b.scope_key
from {{ source('serving', 'analytics_inputs') }} i
join {{ source('serving', 'analytics_builds') }} b on b.id=i.build_id
where i.build_id={{ build_id() }}
