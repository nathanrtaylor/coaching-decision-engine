SELECT
date_add('day', 4, date_trunc('week', CAST(date AS date))) AS week_ending,
expert_id,
site AS mascot,
icp_client,
tenure_group,
coach,
supervisor_id AS coach_id
from hive.care.expert_performance_metrics
WHERE LOWER(icp_client) IN :icp_client_list 
AND
date between DATE :start_date and DATE :end_date 
--and expert_id IN :expert_ids
GROUP BY 1, 2, 3, 4, 5, 6, 7