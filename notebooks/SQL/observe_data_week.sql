WITH 
DateSelector AS (
    SELECT *
    FROM (
        VALUES (
            CAST(:start_date AS date),
            CAST(:end_date   AS date),
            :start_date,
            :end_date
        )
    ) AS t ("StartDate","EndDate","StartDateStr","EndDateStr")
),

org_tenure AS (
    SELECT
        wde.emplid,
        CONCAT(wde.last_name, ', ', wde.pref_first_name, ' (', wde.emplid, ')') AS EmpName,
        CONCAT(wds.last_name, ', ', wds.pref_first_name, ' (', wds.emplid, ')') AS Coach,
        m.manager,
        m."sr. manager"   AS sr_manager,
        m.director,
        m.mascot,
        wde.job_title, 
        wde.last_hire_dt,
        date_diff('day', wde.last_hire_dt, current_date) AS tenure
    FROM hive.care.l2_asurion_hrprd_dbo_asu_person_worker AS wde
    LEFT JOIN hive.care.l2_asurion_hrprd_dbo_asu_person_worker AS wds
        ON wde.supervisor_id = wds.emplid
       AND wds.current_flag = TRUE
    LEFT JOIN hive.care.expert_mascots AS m
        ON wde.emplid = m.eid
    WHERE wde.current_flag = TRUE
),

epm AS (
    SELECT
        expert_id AS emplid,
        icp_client,
        tenure_group,
        date,
        CAST(week_stop_date AS DATE) AS week_
    FROM hive.care.expert_performance_metrics a
    LEFT OUTER JOIN 
        hive.care.l4_asurion_umt_ppx_pay_calendar d ON a."date" = CAST(d.event_date AS DATE)
    WHERE lower(icp_client) IN :icp_client_list
      and date BETWEEN (SELECT StartDate FROM DateSelector) AND (SELECT EndDate FROM DateSelector)
),

observe_data AS (
    SELECT
        expert_id AS emplid,
        date,
        template_questions_name,
        behavior_name,
        score,
        opportunity
    FROM hive.care.l3_asurion_observe_behaviors_scores 
    WHERE template_questions_name IN :observe_scorecards
      AND date BETWEEN (SELECT StartDate FROM DateSelector) 
                    AND (SELECT EndDate FROM DateSelector)
)

SELECT
    m.emplid as expert_id,
    m.week_,
    m.icp_client,
    m.tenure_group,
    t.tenure,
    b.template_questions_name,
    b.behavior_name,
    SUM(b.score)       AS num,
    SUM(b.opportunity) AS den
FROM epm m
LEFT JOIN org_tenure t
    ON m.emplid = t.emplid
LEFT JOIN observe_data b
    ON m.emplid = b.emplid
   AND m.date   = b.date
GROUP BY
    m.emplid,
    m.week_,
    m.icp_client,
    m.tenure_group,
    t.tenure,
    b.template_questions_name,
    b.behavior_name;
