WITH
pushed_behaviors AS (
  SELECT
    recommendation.*,
    CASE WHEN behavior_pass_fail = 'fail' THEN call_link END AS call_link_fail,
    CASE WHEN behavior_pass_fail = 'pass' THEN call_link END AS call_link_pass
  FROM hive.care.l3_asurion_observe_helix_coaching_client_filtered AS recommendation
  WHERE recommendation.coaching_week >= DATE '2025-04-01' 
),
actual_behaviors AS (
  SELECT
    cal.week_start_date                          AS coaching_week,
    cast(cast(hc.coachee_emp_id as int)as varchar)  AS raw_emplid,
    hc.behavior_selected                         AS actual_coached_behavior,
    case
    	when hc.coaching_type = 'Get to Know Me' then 'Get to know me'
    	when hc.coaching_status = 'Excused' then 'Excused' 
    	else 'ADAPT'
    end 										as coaching_event,
    hc.coaching_topic,
    hc.coaching_type,
    hc.uniqueid
  FROM hive.care.l2_asurion_coachdb_coachdb_helixcoaching AS hc
  JOIN hive.care.l4_asurion_umt_ppx_pay_calendar AS cal
    ON hc.coaching_date = cal.event_date
   AND cal.week_start_date >= DATE '2025-06-01'
  WHERE
    hc.coaching_type   IN ('ADAPT', 'Get to Know Me')
    AND hc.coaching_status in ('Submitted', 'Excused')
)
SELECT
  p.emplid,
  CONCAT(wde.last_name, ', ', wde.pref_first_name, ' (', wde.emplid, ')') AS Name,
  CONCAT(wds.last_name, ', ', wds.pref_first_name, ' (', wds.emplid, ')') AS Coach,
  m.manager,
  m."sr. manager",
  m.director,
  m.mascot,
  p.coaching_week        AS pushed_week,
  a.coaching_week        AS actual_week,
  p.behavior_name_short  AS pushed_behavior,
  a.actual_coached_behavior,
  CASE
  	when p.client = 'all' and p.behavior_name_short in ('Ownership','Increased Transfer Rate', 'Transition Statement', 'Sales Confidence', 'Trust Building', 'Find My Iphone', 'VZW Continuing Ed') then 'Verizon'
    when p.client = 'all' and p.behavior_name_short in ('In Warranty SUR', 'ATT Continuing Ed') then 'ATT'
  	else p.client
  end					 as observe_client, 
  case
  	when p.business_unit = 'all' and p.behavior_name_short in ('Ownership','Increased Transfer Rate', 'Transition Statement', 'Sales Confidence', 'Trust Building', 'ATT Continuing Ed', 'VZW Continuing Ed') then 'Soluto'
    when p.business_unit = 'all' and p.behavior_name_short in ('In Warranty SUR') then 'Mobility'
  	when p.business_unit = 'all' and p.behavior_name_short in ('Find My Iphone') then 'Mobility'
  	else p.business_unit 
  end					as observe_business_unit,
  a.coaching_event, 
  a.coaching_topic,
  CASE
    WHEN a.coaching_topic = 'Recommendation' THEN 'Coaching Evolution'
    WHEN a.coaching_topic IS NULL         THEN null
    when a.coaching_event = 'Excused' then a.coaching_event 
    when a.coaching_event = 'Get to know me' then a.coaching_event 
    ELSE 'Legacy ADAPT'
  END                         AS process,
  CASE
    WHEN p.client = 'all'
         AND p.behavior_name_short = a.actual_coached_behavior
      THEN 'priority_override'
    WHEN p.client <> 'all'
         AND p.behavior_name_short = a.actual_coached_behavior
      THEN 'coaching_recommendation'
    WHEN a.coaching_topic <> 'Recommendation'
         AND p.behavior_name_short <> a.actual_coached_behavior
      THEN 'coach_override'
    ELSE 'coaching_recommendation'
  END                         AS behavior_source,
  a.uniqueid
--  p.call_link_pass,
--  p.call_link_fail
FROM pushed_behaviors AS p
LEFT JOIN actual_behaviors AS a
  ON p.emplid       = a.raw_emplid
 AND p.coaching_week = a.coaching_week
LEFT JOIN hive.care.l2_asurion_hrprd_dbo_asu_person_worker AS wde
  ON p.emplid        = wde.emplid
 AND wde.current_flag = TRUE
LEFT JOIN hive.care.l2_asurion_hrprd_dbo_asu_person_worker AS wds
  ON wde.supervisor_id = wds.emplid
 AND wds.current_flag   = TRUE
LEFT JOIN hive.care.expert_mascots AS m
  ON p.emplid = m.eid;