WITH oai_qa AS (
SELECT
a.meeting_id,
a.id,
b.interaction_url,
b.m_asurion_call_id AS ucid,
a.partner_agent_id AS expert_id,
a.created_at AS eval_date,
a.template_questions_name,
a.calculatedscore_value,
a.obtainedscore,
a.template_questions_phrase AS question,
a.template_questions_options_displaytext AS Answer,
a.template_questions_score AS Question_Score
FROM hive.care.l3_asurion_observe_autoqa_evaluations a
JOIN hive.care.l3_asurion_observe_interaction b 
 ON a.meeting_id = b.id 
WHERE a.created_at between DATE :start_date and DATE :end_date
AND a.template_questions_name IN :observe_scorecards
AND a.partner_agent_id IN :emplids
),
s AS (
SELECT 
a.dw_survey_response_id,
a.dw_soluto_crm_id,
a.expert_id,
c.cvp_call_id AS ucid,
a.rep_score AS expert_five_star,
a.recommend_verbatim
FROM hive.care.l3_asurion_survey_response a
JOIN hive.care.l3_asurion_whole_home_expert_hierarchy b ON a.expert_id = b.expert_id AND a.survey_response_dt BETWEEN b.eff_start_dt AND b.eff_end_dt 
LEFT JOIN hive.care.l3_verizon_soluto_crm c ON a.dw_soluto_crm_id = c.dw_soluto_crm_id 
WHERE survey_response_dt >= DATE :start_date 
AND client IN :client_list
AND lob_name IN :lob_list
AND a.survey_complete = 1
)
SELECT *
FROM s
    JOIN oai_qa
     ON oai_qa.ucid = s.ucid AND oai_qa.expert_id = s.expert_id
ORDER BY s.ucid, oai_qa.id