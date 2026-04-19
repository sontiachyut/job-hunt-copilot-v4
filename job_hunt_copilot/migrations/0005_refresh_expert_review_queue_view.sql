DROP VIEW IF EXISTS expert_review_queue;
CREATE VIEW expert_review_queue AS
SELECT
  erp.expert_review_packet_id,
  erp.pipeline_run_id,
  COALESCE(erp.job_posting_id, pr.job_posting_id) AS job_posting_id,
  erp.packet_status,
  erp.packet_path,
  pr.run_status,
  pr.current_stage,
  pr.run_summary,
  erp.summary_excerpt,
  jp.company_name,
  jp.role_title,
  GROUP_CONCAT(ai.agent_incident_id) AS incident_ids,
  GROUP_CONCAT(ai.summary, ' | ') AS incident_summaries,
  erp.created_at
FROM expert_review_packets erp
JOIN pipeline_runs pr
  ON pr.pipeline_run_id = erp.pipeline_run_id
LEFT JOIN job_postings jp
  ON jp.job_posting_id = COALESCE(erp.job_posting_id, pr.job_posting_id)
LEFT JOIN agent_incidents ai
  ON ai.pipeline_run_id = pr.pipeline_run_id
 AND ai.status IN ('open', 'in_repair', 'escalated')
WHERE erp.packet_status = 'pending_expert_review'
GROUP BY
  erp.expert_review_packet_id,
  erp.pipeline_run_id,
  COALESCE(erp.job_posting_id, pr.job_posting_id),
  erp.packet_status,
  erp.packet_path,
  pr.run_status,
  pr.current_stage,
  pr.run_summary,
  erp.summary_excerpt,
  jp.company_name,
  jp.role_title,
  erp.created_at;

PRAGMA user_version = 5;
