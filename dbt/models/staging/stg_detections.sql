select i.build_id,d.*
from {{ source('serving','detections') }} d
join {{ ref('stg_inputs') }} i on i.release_id=d.release_id and i.alias='best_available'
