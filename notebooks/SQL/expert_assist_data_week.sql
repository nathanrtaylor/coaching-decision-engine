WITH
DateSelector AS (
    SELECT *
    FROM
        ( VALUES (
             DATE (:start_date), DATE (:end_date),
                 :start_date, :end_date
                 ))
        AS t ("StartDate","EndDate","StartDateStr","EndDateStr")
),

Expert_Assist_Per_Call AS(
    SELECT 
        COALESCE(
            element_at(ex.edp_raw_data_map, 'Identities_ReservationSid'),
            element_at(ex.edp_raw_data_map, 'Identities_SessionId')
            ) as reservation_id,
        COUNT(DISTINCT element_at(ex.edp_raw_data_map, 'ExtraData_messageId')) EaTotalMessages,
        COUNT(DISTINCT 
            CASE WHEN element_at(ex.edp_raw_data_map,'ExtraData_source') = 'ExpertInput'
                THEN element_at(ex.edp_raw_data_map, 'ExtraData_messageId') END
                ) EaExpertWrittenMessages,
        COUNT(DISTINCT 
            CASE WHEN element_at(ex.edp_raw_data_map,'ExtraData_source') != 'ExpertInput'
                THEN element_at(ex.edp_raw_data_map, 'ExtraData_messageId') END
                ) EaSystemGeneratedMessages,
        COUNT(DISTINCT 
            CASE WHEN element_at(ex.edp_raw_data_map,'ExtraData_source') = 'HelpMeNow'
                THEN element_at(ex.edp_raw_data_map, 'ExtraData_messageId') END
                ) EaQuickSolveMessages
    FROM
        care.l1_asurion_home_events_analytics_exwo ex
    WHERE 1=1
        AND element_at(ex.edp_raw_data_map,'Name') ='MessageSent'
        AND ex.edp_updated_date >= (SELECT StartDateStr FROM DateSelector)
        AND DATE(CAST( AT_TIMEZONE(
                from_iso8601_timestamp(element_at(ex.edp_raw_data_map,'Time')),
                'America/Chicago') AS TIMESTAMP)) 
            BETWEEN (SELECT StartDate FROM DateSelector) 
                AND (SELECT EndDate FROM DateSelector)
    GROUP BY
        COALESCE(
            element_at(ex.edp_raw_data_map, 'Identities_ReservationSid'),
            element_at(ex.edp_raw_data_map, 'Identities_SessionId'))
),

Sales AS (
    SELECT
        s.reservation_id,
        1 as "SalesFunnellMatch",
        MAX(COALESCE(s.Opportunity_CH,0)) AS "Opportunity_CH",
        MAX(COALESCE(s.Ai_Offer_CH,0)) AS "Ai_Offer_CH",
        MAX(COALESCE(s.Sale_CH,0)) AS "Sale_CH"
    FROM(
        SELECT
            sf.reservation_id,
            MAX(COALESCE(sf.opportunity_flg,0)) "Opportunity_CH",
            MAX(COALESCE(sf.ai_offer_count,0)) AS "Ai_Offer_CH",
            MAX(COALESCE(sf.enroll_count,0)) AS "Sale_CH"
        FROM 
            hive.care.l3_att_sales_funnel sf
        WHERE 1 =1
            AND sf.interaction_channel = 'voice'
            AND sf.business_unit IN ('soluto','mobility')
            AND sf.product_group = 'Connected Home'
            AND DATE(sf.event_date_cst) BETWEEN (SELECT StartDate FROM DateSelector) 
                AND  (SELECT EndDate from DateSelector)
        GROUP BY
            sf.reservation_id
        
        UNION ALL
        
        SELECT
            sf.reservation_id,
            MAX(COALESCE(sf.opportunity_flg,0)) "Opportunity_CH",
            MAX(COALESCE(sf.ai_offer_count,0)) AS "Ai_Offer_CH",
            MAX(COALESCE(sf.enroll_count,0)) AS "Sale_CH"
        FROM 
            care.l3_verizon_sales_funnel sf
        WHERE 1 =1
            AND sf.interaction_channel = 'voice'
            AND sf.business_unit IN ('soluto','mobility')
            AND sf.product_group = 'Connected Home'
            AND DATE(sf.event_date_cst) BETWEEN (SELECT StartDate FROM DateSelector) 
                AND  (SELECT EndDate from DateSelector)
        GROUP BY
            sf.reservation_id
    ) s
    GROUP BY
        s.reservation_Id
),

Inbound_Call_Stats AS(
    SELECT
        tid.reservation_id AS "reservation_id",
        MIN_BY(tgs.recording_link,tid.segstart) AS "URL",
        MIN_BY(rk.Language, tid.segstart) AS "Language",
        MIN_BY(rk.Business_Unit, tid.segstart) AS "Business_Unit",
        MIN_BY(rk.client, tid.segstart) AS "Client",
        MIN_BY(rk.subclient, tid.segstart) AS "Subclient",
        MIN(tid.segstart) as segstart,
        MIN(tid.event_date_cst) AS "Date",
        MIN_BY(tid.answering_id,tid.segstart) AS "Employee",
        1 AS "InboundCalls",
        0 AS "OutboundCalls",
        MAX(CASE WHEN rk.sales_enabled = 'true' THEN 1 ELSE 0 END) "SalesEnabled",
        SUM(
            (COALESCE(tid.interaction_tm_sec, 0)
            +COALESCE(tid.wrap_tm_sec, 0))
            ) AS "ResolutionTime",
        SUM(s.SalesFunnellMatch) AS "SalesFunnellMatch",
        sum(s.Opportunity_CH) as "Opportunity_CH",
        SUM(s.Ai_Offer_CH) AS "Ai_Offer_CH",

        SIGN(SUM(ea.EaTotalMessages)) AS EaTotalMessages,
        SIGN(SUM(ea.EaExpertWrittenMessages)) AS EaExpertWrittenMessages,
        SIGN(SUM(ea.EaSystemGeneratedMessages)) AS EaSystemGeneratedMessages,
        SIGN(SUM(ea.EaQuickSolveMessages)) AS EaQuickSolveMessages,
        SUM(s.Sale_Ch) AS "Sale_Ch"
    FROM
        hive.care.l3_asurion_twilio_interaction_detail tid
        LEFT OUTER JOIN
        hive.care.l4_asurion_umt_routing_key_analytics_mapper rk
            ON lower(tid.interaction_routing_key) = lower(rk.routingrulekey)
            AND tid.event_date_cst between rk.startdate and rk.enddate
        LEFT OUTER JOIN
        Sales s
            ON tid.reservation_id = s.reservation_id
        LEFT OUTER JOIN
        Expert_Assist_Per_Call ea
            ON tid.reservation_id = ea.reservation_id
        LEFT JOIN 
        hive.care.l3_asurion_interaction_detail_tags tgs
            ON tid.reservation_id = tgs.reservation_id
    WHERE 1=1
        AND tid.direction = 'inbound'
        AND tid.disposition_action in (
            'handled','consult','conference','transfer',
            'flex_int_transfer_WARM',
            'flex_int_transfer_COLD')
        AND (
            rk.business_unit = 'Soluto'
            OR (
                rk.business_unit = 'Mobility'
                AND lower(rk.type) LIKE '%fl%'
                AND lower(rk.subclient) NOT LIKE '%mex%'
                )
            )
        AND rk.client in ('Verizon','AT&T')
        AND tid.event_date_cst BETWEEN (SELECT StartDate FROM DateSelector) 
            AND  (SELECT EndDate from DateSelector)
    GROUP BY
        tid.reservation_id
),

Outbound_Call_Stats AS(
    SELECT
        ocl.inbound_reservation_id AS "reservation_id",
        MIN_BY(tgs.recording_link, ocl.outbound_segment_start) AS "URL",
        
        MIN_BY(rk.Language, ocl.outbound_segment_start) AS "Language",
        MIN_BY(rk.Business_Unit, ocl.outbound_segment_start) AS "Business_Unit",
        MIN_BY(rk.client, ocl.outbound_segment_start) AS "Client",
        MIN_BY(rk.subclient, ocl.outbound_segment_start) AS "Subclient",
        MIN(ocl.outbound_segment_start) as segstart,
        MIN(ocl.event_date_cst) AS "Date",
        MIN_BY(ocl.originating_id, 
                    ocl.outbound_segment_start) AS "Employee",
        -- 0 AS ExWo,
        0 AS "InboundCalls",
        COUNT(*) AS "OutboundCalls",
        MAX(CASE WHEN rk.sales_enabled = 'true' THEN 1 ELSE 0 END) "SalesEnabled",
        SUM(
            ( COALESCE(ocl.interaction_time_outbound, 0) 
            + COALESCE(ocl.wrap_time_outbound, 0))
            + CASE WHEN ocl.disposition_action IN ('abandoned', 'resv_canceled')
                   THEN ocl.abn_time_outbound ELSE 0 END
            ) AS "ResolutionTime",
        SUM(s.SalesFunnellMatch) AS "SalesFunnellMatch",
        sum(s.Opportunity_CH) as "Opportunity_CH",
        SUM(s.Ai_Offer_CH) AS "Ai_Offer_CH",
        SIGN(SUM(ea.EaTotalMessages)) AS eaTotalMessages,
        SIGN(SUM(ea.EaExpertWrittenMessages)) AS EaExpertWrittenMessages,
        SIGN(SUM(ea.EaSystemGeneratedMessages)) AS EaSystemGeneratedMessages,
        SIGN(SUM(ea.EaQuickSolveMessages)) AS EaQuickSolveMessages,
        SUM(s.Sale_Ch) AS "Sale_Ch"
    FROM
        hive.care.l3_asurion_inbound_outbound_call_link_tbl ocl
        LEFT JOIN
        hive.care.l4_asurion_umt_routing_key_analytics_mapper rk
            ON ocl.inbound_interaction_routing_key = rk.routingrulekey
            AND ocl.event_date_cst between rk.startdate and rk.enddate
        LEFT OUTER JOIN
        Sales s
            ON ocl.outbound_reservation_id = s.reservation_id
        LEFT OUTER JOIN
       Expert_Assist_Per_Call ea
            ON ocl.outbound_reservation_id = ea.reservation_id
        LEFT JOIN 
        hive.care.l3_asurion_interaction_detail_tags tgs
            ON ocl.outbound_reservation_id = tgs.reservation_id
    WHERE
        1 = 1
        AND (
            rk.business_unit = 'Soluto'
            OR (
                rk.business_unit = 'Mobility'
                AND lower(rk.type) LIKE '%fl%'
                AND lower(rk.subclient) NOT LIKE '%mex%'
                )
            )
        AND rk.client in ('Verizon','AT&T')
        AND ocl.disposition_action NOT IN ('resv_time_out','resv_rejected')
        AND ocl.event_date_cst BETWEEN (SELECT StartDate FROM DateSelector) 
            AND  (SELECT EndDate from DateSelector)
    GROUP BY
        ocl.inbound_reservation_id
),

Call_Stats AS (
SELECT
    c.reservation_id,
    MIN_BY(c.URL, c.segstart) "URL",
    CAST(SUBSTRING(MIN_BY(c.Language, c.segstart),1,3) AS Char(3)) "Language_",
    CAST(SUBSTRING(MIN_BY(c.business_unit, c.segstart),1,1) AS Char(1)) "BusinessUnit_",
    CAST(SUBSTRING(MIN_BY(c.Client, c.segstart),1,1) AS Char(1)) "Client_",
    MIN_BY(c.SubClient, c.segstart) "Subclient",
    CONCAT(
        MIN_BY(c.Employee, c.segstart),
        '-',
        date_format(MIN(DATE(c.Date)),'%Y-%m-%d')
    ) "EmployeeKey",
    MIN(DATE(c.Date)) "Date",
    CAST(MIN_BY(c.Employee, c.segstart) AS INT) Employee,

    COALESCE(SUM(c.InboundCalls),0) "InboundCalls",
    COALESCE(SUM(c.OutboundCalls),0) "Outbound Calls",

    SUM(COALESCE(c.SalesFunnellMatch, 0)) "Sales Funnel Matches",
    MAX(COALESCE(c.SalesEnabled, 0)) "SalesEnabled",
    SIGN(COALESCE(SUM(c.Opportunity_CH),0)) "Sales Opportunity Connected Home",
    -- SIGN(COALESCE(SUM(c.Ai_Offer_CH), 0)) "Ai Sales Offer Connected Home",
    
    SIGN(COALESCE(SUM(c.EaTotalMessages),0)) "Expert Assist Usage",
    SIGN(COALESCE(SUM(c.EaExpertWrittenMessages),0)) "EA Written Messages",
    SIGN(COALESCE(SUM(c.EaSystemGeneratedMessages),0)) "EA System Generated Messages",
    SIGN(COALESCE(SUM(c.EaQuickSolveMessages),0)) "EA Quick Solve Messages",
    
    SIGN(COALESCE(SUM(c.Sale_Ch),0)) AS "Sale Connected Home"
 
    -- SUM(CASE WHEN c.OutboundCalls = 0  
    --          THEN c.ResolutionTime ELSE 0 END) AS "Handle Time",
    -- SUM(c.ResolutionTime) AS "Resolution Time"
FROM
    (
        SELECT * FROM Inbound_Call_Stats i
        UNION ALL
        SELECT * FROM Outbound_Call_Stats o
    ) c
WHERE 1=1
GROUP BY
    c.reservation_id
HAVING
    SUM(c.ResolutionTime) <= 8 * 60 * 60
    AND SUM(c.InboundCalls) > 0 
)
 
SELECT CAST(d.week_stop_date AS DATE) AS week_, cs.BusinessUnit_, cs.Client_, CAST(cs.Employee as VARCHAR) as expert_id, 
	sum(cs."Expert Assist Usage") as num, 
	sum(cs.InboundCalls) as den, 
    ROUND(
    COALESCE(
    CAST(sum(cs."Expert Assist Usage") AS DOUBLE) /
    NULLIF(CAST(sum(cs.InboundCalls) AS DOUBLE), 0.0),
    0.000
    ),
    3
    ) AS calc
FROM 
    Call_Stats cs
LEFT OUTER JOIN 
	hive.care.l4_asurion_umt_ppx_pay_calendar d ON cs."Date" = CAST(d.event_date AS DATE)
WHERE 
	cs."Client_" IN :client_list
	AND
	cs."BusinessUnit_" IN :business_unit_list
	     
group BY d.week_stop_date, BusinessUnit_, Client_, Employee 