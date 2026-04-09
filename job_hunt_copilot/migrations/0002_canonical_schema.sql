PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS linkedin_leads (
  lead_id TEXT PRIMARY KEY,
  lead_identity_key TEXT NOT NULL,
  lead_status TEXT NOT NULL,
  lead_shape TEXT NOT NULL,
  split_review_status TEXT NOT NULL,
  source_type TEXT NOT NULL,
  source_reference TEXT NOT NULL,
  source_mode TEXT NOT NULL,
  source_url TEXT,
  company_name TEXT,
  role_title TEXT,
  location TEXT,
  work_mode TEXT,
  compensation_summary TEXT,
  poster_name TEXT,
  poster_title TEXT,
  last_scraped_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_postings (
  job_posting_id TEXT PRIMARY KEY,
  lead_id TEXT NOT NULL,
  posting_identity_key TEXT NOT NULL,
  company_name TEXT NOT NULL,
  role_title TEXT NOT NULL,
  posting_status TEXT NOT NULL,
  location TEXT,
  employment_type TEXT,
  posted_at TEXT,
  jd_artifact_path TEXT,
  archived_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (lead_id) REFERENCES linkedin_leads(lead_id)
);

CREATE TABLE IF NOT EXISTS contacts (
  contact_id TEXT PRIMARY KEY,
  identity_key TEXT NOT NULL,
  display_name TEXT NOT NULL,
  company_name TEXT NOT NULL,
  origin_component TEXT NOT NULL,
  contact_status TEXT NOT NULL,
  full_name TEXT,
  first_name TEXT,
  last_name TEXT,
  linkedin_url TEXT,
  position_title TEXT,
  location TEXT,
  discovery_summary TEXT,
  current_working_email TEXT,
  identity_source TEXT,
  provider_name TEXT,
  provider_person_id TEXT,
  name_quality TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS linkedin_lead_contacts (
  linkedin_lead_contact_id TEXT PRIMARY KEY,
  lead_id TEXT NOT NULL,
  contact_id TEXT NOT NULL,
  contact_role TEXT NOT NULL,
  recipient_type_inferred TEXT NOT NULL,
  is_primary_poster INTEGER NOT NULL,
  extraction_confidence TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (lead_id) REFERENCES linkedin_leads(lead_id),
  FOREIGN KEY (contact_id) REFERENCES contacts(contact_id),
  UNIQUE (lead_id, contact_id)
);

CREATE TABLE IF NOT EXISTS job_posting_contacts (
  job_posting_contact_id TEXT PRIMARY KEY,
  job_posting_id TEXT NOT NULL,
  contact_id TEXT NOT NULL,
  recipient_type TEXT NOT NULL,
  relevance_reason TEXT NOT NULL,
  link_level_status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (job_posting_id) REFERENCES job_postings(job_posting_id),
  FOREIGN KEY (contact_id) REFERENCES contacts(contact_id),
  UNIQUE (job_posting_id, contact_id)
);

CREATE TABLE IF NOT EXISTS resume_tailoring_runs (
  resume_tailoring_run_id TEXT PRIMARY KEY,
  job_posting_id TEXT NOT NULL,
  base_used TEXT NOT NULL,
  tailoring_status TEXT NOT NULL,
  resume_review_status TEXT NOT NULL,
  workspace_path TEXT NOT NULL,
  meta_yaml_path TEXT,
  final_resume_path TEXT,
  verification_outcome TEXT,
  started_at TEXT,
  completed_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (job_posting_id) REFERENCES job_postings(job_posting_id)
);

CREATE TABLE IF NOT EXISTS state_transition_events (
  state_transition_event_id TEXT PRIMARY KEY,
  object_type TEXT NOT NULL,
  object_id TEXT NOT NULL,
  stage TEXT NOT NULL,
  previous_state TEXT NOT NULL,
  new_state TEXT NOT NULL,
  transition_timestamp TEXT NOT NULL,
  transition_reason TEXT,
  caused_by TEXT,
  lead_id TEXT,
  job_posting_id TEXT,
  contact_id TEXT,
  FOREIGN KEY (lead_id) REFERENCES linkedin_leads(lead_id),
  FOREIGN KEY (job_posting_id) REFERENCES job_postings(job_posting_id),
  FOREIGN KEY (contact_id) REFERENCES contacts(contact_id)
);

CREATE TABLE IF NOT EXISTS override_events (
  override_event_id TEXT PRIMARY KEY,
  object_type TEXT NOT NULL,
  object_id TEXT NOT NULL,
  component_stage TEXT NOT NULL,
  previous_value TEXT NOT NULL,
  new_value TEXT NOT NULL,
  override_reason TEXT NOT NULL,
  override_timestamp TEXT NOT NULL,
  override_by TEXT,
  lead_id TEXT,
  job_posting_id TEXT,
  contact_id TEXT,
  FOREIGN KEY (lead_id) REFERENCES linkedin_leads(lead_id),
  FOREIGN KEY (job_posting_id) REFERENCES job_postings(job_posting_id),
  FOREIGN KEY (contact_id) REFERENCES contacts(contact_id)
);

CREATE TABLE IF NOT EXISTS feedback_sync_runs (
  feedback_sync_run_id TEXT PRIMARY KEY,
  scheduler_name TEXT NOT NULL,
  scheduler_type TEXT NOT NULL,
  started_at TEXT NOT NULL,
  result TEXT NOT NULL,
  completed_at TEXT,
  observation_scope TEXT,
  messages_examined INTEGER,
  bounce_events_written INTEGER,
  reply_events_written INTEGER,
  last_checkpoint TEXT,
  error_message TEXT
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
  pipeline_run_id TEXT PRIMARY KEY,
  run_scope_type TEXT NOT NULL,
  run_status TEXT NOT NULL,
  current_stage TEXT NOT NULL,
  lead_id TEXT,
  job_posting_id TEXT,
  completed_at TEXT,
  last_error_summary TEXT,
  review_packet_status TEXT,
  run_summary TEXT,
  started_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (lead_id) REFERENCES linkedin_leads(lead_id),
  FOREIGN KEY (job_posting_id) REFERENCES job_postings(job_posting_id)
);

CREATE TABLE IF NOT EXISTS supervisor_cycles (
  supervisor_cycle_id TEXT PRIMARY KEY,
  trigger_type TEXT NOT NULL,
  scheduler_name TEXT,
  selected_work_type TEXT,
  selected_work_id TEXT,
  pipeline_run_id TEXT,
  context_snapshot_path TEXT,
  sleep_wake_detection_method TEXT,
  sleep_wake_event_ref TEXT,
  started_at TEXT NOT NULL,
  completed_at TEXT,
  result TEXT NOT NULL,
  error_summary TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (pipeline_run_id) REFERENCES pipeline_runs(pipeline_run_id)
);

CREATE TABLE IF NOT EXISTS agent_control_state (
  control_key TEXT PRIMARY KEY,
  control_value TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_runtime_leases (
  lease_name TEXT PRIMARY KEY,
  lease_owner_id TEXT NOT NULL,
  acquired_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  last_renewed_at TEXT,
  lease_note TEXT
);

CREATE TABLE IF NOT EXISTS windows (
  window_id TEXT PRIMARY KEY,
  window_start TEXT NOT NULL,
  window_end TEXT NOT NULL,
  status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS provider_budget_state (
  provider_name TEXT PRIMARY KEY,
  remaining_credits INTEGER,
  credit_limit INTEGER,
  reset_at TEXT,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS discovery_attempts (
  discovery_attempt_id TEXT PRIMARY KEY,
  contact_id TEXT NOT NULL,
  job_posting_id TEXT,
  window_id TEXT,
  outcome TEXT NOT NULL,
  provider_name TEXT,
  email TEXT,
  email_local_part TEXT,
  detected_pattern TEXT,
  provider_verification_status TEXT,
  provider_score TEXT,
  bounced INTEGER,
  display_name TEXT,
  first_name TEXT,
  last_name TEXT,
  full_name TEXT,
  linkedin_url TEXT,
  position_title TEXT,
  location TEXT,
  provider_person_id TEXT,
  name_quality TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (contact_id) REFERENCES contacts(contact_id),
  FOREIGN KEY (job_posting_id) REFERENCES job_postings(job_posting_id),
  FOREIGN KEY (window_id) REFERENCES windows(window_id)
);

CREATE TABLE IF NOT EXISTS outreach_messages (
  outreach_message_id TEXT PRIMARY KEY,
  contact_id TEXT NOT NULL,
  outreach_mode TEXT NOT NULL,
  recipient_email TEXT NOT NULL,
  message_status TEXT NOT NULL,
  job_posting_id TEXT,
  job_posting_contact_id TEXT,
  subject TEXT,
  body_text TEXT,
  body_html TEXT,
  thread_id TEXT,
  delivery_tracking_id TEXT,
  sent_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (contact_id) REFERENCES contacts(contact_id),
  FOREIGN KEY (job_posting_id) REFERENCES job_postings(job_posting_id),
  FOREIGN KEY (job_posting_contact_id) REFERENCES job_posting_contacts(job_posting_contact_id)
);

CREATE TABLE IF NOT EXISTS delivery_feedback_events (
  delivery_feedback_event_id TEXT PRIMARY KEY,
  outreach_message_id TEXT NOT NULL,
  event_state TEXT NOT NULL,
  event_timestamp TEXT NOT NULL,
  contact_id TEXT,
  job_posting_id TEXT,
  reply_summary TEXT,
  raw_reply_excerpt TEXT,
  created_at TEXT,
  FOREIGN KEY (outreach_message_id) REFERENCES outreach_messages(outreach_message_id),
  FOREIGN KEY (contact_id) REFERENCES contacts(contact_id),
  FOREIGN KEY (job_posting_id) REFERENCES job_postings(job_posting_id)
);

CREATE TABLE IF NOT EXISTS artifact_records (
  artifact_id TEXT PRIMARY KEY,
  artifact_type TEXT NOT NULL,
  file_path TEXT NOT NULL,
  producer_component TEXT NOT NULL,
  lead_id TEXT,
  job_posting_id TEXT,
  contact_id TEXT,
  outreach_message_id TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (lead_id) REFERENCES linkedin_leads(lead_id),
  FOREIGN KEY (job_posting_id) REFERENCES job_postings(job_posting_id),
  FOREIGN KEY (contact_id) REFERENCES contacts(contact_id),
  FOREIGN KEY (outreach_message_id) REFERENCES outreach_messages(outreach_message_id),
  CHECK (
    lead_id IS NOT NULL
    OR job_posting_id IS NOT NULL
    OR contact_id IS NOT NULL
    OR outreach_message_id IS NOT NULL
  )
);

CREATE TABLE IF NOT EXISTS agent_incidents (
  agent_incident_id TEXT PRIMARY KEY,
  incident_type TEXT NOT NULL,
  severity TEXT NOT NULL,
  status TEXT NOT NULL,
  summary TEXT NOT NULL,
  pipeline_run_id TEXT,
  lead_id TEXT,
  job_posting_id TEXT,
  contact_id TEXT,
  outreach_message_id TEXT,
  resolved_at TEXT,
  escalation_reason TEXT,
  repair_attempt_summary TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (pipeline_run_id) REFERENCES pipeline_runs(pipeline_run_id),
  FOREIGN KEY (lead_id) REFERENCES linkedin_leads(lead_id),
  FOREIGN KEY (job_posting_id) REFERENCES job_postings(job_posting_id),
  FOREIGN KEY (contact_id) REFERENCES contacts(contact_id),
  FOREIGN KEY (outreach_message_id) REFERENCES outreach_messages(outreach_message_id)
);

CREATE TABLE IF NOT EXISTS expert_review_packets (
  expert_review_packet_id TEXT PRIMARY KEY,
  pipeline_run_id TEXT NOT NULL,
  packet_status TEXT NOT NULL,
  packet_path TEXT NOT NULL,
  job_posting_id TEXT,
  reviewed_at TEXT,
  summary_excerpt TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (pipeline_run_id) REFERENCES pipeline_runs(pipeline_run_id),
  FOREIGN KEY (job_posting_id) REFERENCES job_postings(job_posting_id)
);

CREATE TABLE IF NOT EXISTS expert_review_decisions (
  expert_review_decision_id TEXT PRIMARY KEY,
  expert_review_packet_id TEXT NOT NULL,
  decision_type TEXT NOT NULL,
  decision_notes TEXT,
  override_event_id TEXT,
  decided_at TEXT NOT NULL,
  applied_at TEXT,
  FOREIGN KEY (expert_review_packet_id) REFERENCES expert_review_packets(expert_review_packet_id),
  FOREIGN KEY (override_event_id) REFERENCES override_events(override_event_id)
);

CREATE TABLE IF NOT EXISTS maintenance_change_batches (
  maintenance_change_batch_id TEXT PRIMARY KEY,
  branch_name TEXT NOT NULL,
  scope_slug TEXT NOT NULL,
  status TEXT NOT NULL,
  approval_outcome TEXT NOT NULL,
  summary_path TEXT NOT NULL,
  json_path TEXT NOT NULL,
  head_commit_sha TEXT,
  merged_commit_sha TEXT,
  merge_commit_message TEXT,
  validated_at TEXT,
  approved_at TEXT,
  merged_at TEXT,
  failed_at TEXT,
  validation_summary TEXT,
  expert_review_packet_id TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (expert_review_packet_id) REFERENCES expert_review_packets(expert_review_packet_id)
);

CREATE TABLE IF NOT EXISTS provider_budget_events (
  provider_budget_event_id TEXT PRIMARY KEY,
  provider_name TEXT NOT NULL,
  event_type TEXT NOT NULL,
  credit_delta INTEGER NOT NULL,
  remaining_credits_after INTEGER,
  related_discovery_attempt_id TEXT,
  related_contact_id TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (related_contact_id) REFERENCES contacts(contact_id)
);

CREATE INDEX IF NOT EXISTS idx_linkedin_leads_identity_key
  ON linkedin_leads(lead_identity_key);
CREATE INDEX IF NOT EXISTS idx_linkedin_leads_status
  ON linkedin_leads(lead_status);
CREATE INDEX IF NOT EXISTS idx_linkedin_leads_split_review_status
  ON linkedin_leads(split_review_status);

CREATE INDEX IF NOT EXISTS idx_job_postings_lead_id
  ON job_postings(lead_id);
CREATE INDEX IF NOT EXISTS idx_job_postings_identity_key
  ON job_postings(posting_identity_key);
CREATE INDEX IF NOT EXISTS idx_job_postings_status
  ON job_postings(posting_status);

CREATE INDEX IF NOT EXISTS idx_contacts_identity_key
  ON contacts(identity_key);
CREATE INDEX IF NOT EXISTS idx_contacts_linkedin_url
  ON contacts(linkedin_url);
CREATE INDEX IF NOT EXISTS idx_contacts_provider_person
  ON contacts(provider_name, provider_person_id);
CREATE INDEX IF NOT EXISTS idx_contacts_status
  ON contacts(contact_status);
CREATE INDEX IF NOT EXISTS idx_contacts_working_email
  ON contacts(current_working_email);
CREATE INDEX IF NOT EXISTS idx_contacts_origin_component
  ON contacts(origin_component);

CREATE UNIQUE INDEX IF NOT EXISTS idx_linkedin_lead_contacts_pair
  ON linkedin_lead_contacts(lead_id, contact_id);
CREATE INDEX IF NOT EXISTS idx_linkedin_lead_contacts_role
  ON linkedin_lead_contacts(contact_role);
CREATE INDEX IF NOT EXISTS idx_linkedin_lead_contacts_recipient_type
  ON linkedin_lead_contacts(recipient_type_inferred);

CREATE UNIQUE INDEX IF NOT EXISTS idx_job_posting_contacts_pair
  ON job_posting_contacts(job_posting_id, contact_id);
CREATE INDEX IF NOT EXISTS idx_job_posting_contacts_status
  ON job_posting_contacts(link_level_status);
CREATE INDEX IF NOT EXISTS idx_job_posting_contacts_recipient_type
  ON job_posting_contacts(recipient_type);

CREATE INDEX IF NOT EXISTS idx_resume_tailoring_runs_job_posting
  ON resume_tailoring_runs(job_posting_id);
CREATE INDEX IF NOT EXISTS idx_resume_tailoring_runs_review_status
  ON resume_tailoring_runs(resume_review_status);

CREATE INDEX IF NOT EXISTS idx_artifact_records_type
  ON artifact_records(artifact_type);
CREATE INDEX IF NOT EXISTS idx_artifact_records_lead
  ON artifact_records(lead_id);
CREATE INDEX IF NOT EXISTS idx_artifact_records_job_posting
  ON artifact_records(job_posting_id);
CREATE INDEX IF NOT EXISTS idx_artifact_records_contact
  ON artifact_records(contact_id);
CREATE INDEX IF NOT EXISTS idx_artifact_records_message
  ON artifact_records(outreach_message_id);

CREATE INDEX IF NOT EXISTS idx_state_transition_events_object
  ON state_transition_events(object_type, object_id);
CREATE INDEX IF NOT EXISTS idx_state_transition_events_timestamp
  ON state_transition_events(transition_timestamp);

CREATE INDEX IF NOT EXISTS idx_override_events_object
  ON override_events(object_type, object_id);
CREATE INDEX IF NOT EXISTS idx_override_events_timestamp
  ON override_events(override_timestamp);

CREATE INDEX IF NOT EXISTS idx_feedback_sync_runs_started_at
  ON feedback_sync_runs(started_at);
CREATE INDEX IF NOT EXISTS idx_feedback_sync_runs_result
  ON feedback_sync_runs(result);
CREATE INDEX IF NOT EXISTS idx_feedback_sync_runs_scheduler_name
  ON feedback_sync_runs(scheduler_name);

CREATE INDEX IF NOT EXISTS idx_pipeline_runs_status
  ON pipeline_runs(run_status);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_job_posting
  ON pipeline_runs(job_posting_id);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_stage
  ON pipeline_runs(current_stage);

CREATE INDEX IF NOT EXISTS idx_supervisor_cycles_started_at
  ON supervisor_cycles(started_at);
CREATE INDEX IF NOT EXISTS idx_supervisor_cycles_result
  ON supervisor_cycles(result);
CREATE INDEX IF NOT EXISTS idx_supervisor_cycles_pipeline_run
  ON supervisor_cycles(pipeline_run_id);

CREATE INDEX IF NOT EXISTS idx_agent_runtime_leases_expires_at
  ON agent_runtime_leases(expires_at);

CREATE INDEX IF NOT EXISTS idx_agent_incidents_status
  ON agent_incidents(status);
CREATE INDEX IF NOT EXISTS idx_agent_incidents_severity
  ON agent_incidents(severity);
CREATE INDEX IF NOT EXISTS idx_agent_incidents_pipeline_run
  ON agent_incidents(pipeline_run_id);

CREATE INDEX IF NOT EXISTS idx_expert_review_packets_status
  ON expert_review_packets(packet_status);
CREATE INDEX IF NOT EXISTS idx_expert_review_packets_pipeline_run
  ON expert_review_packets(pipeline_run_id);

CREATE INDEX IF NOT EXISTS idx_expert_review_decisions_packet
  ON expert_review_decisions(expert_review_packet_id);
CREATE INDEX IF NOT EXISTS idx_expert_review_decisions_decided_at
  ON expert_review_decisions(decided_at);

CREATE INDEX IF NOT EXISTS idx_discovery_attempts_contact
  ON discovery_attempts(contact_id);
CREATE INDEX IF NOT EXISTS idx_discovery_attempts_job_posting
  ON discovery_attempts(job_posting_id);
CREATE INDEX IF NOT EXISTS idx_discovery_attempts_outcome
  ON discovery_attempts(outcome);
CREATE INDEX IF NOT EXISTS idx_discovery_attempts_created_at
  ON discovery_attempts(created_at);

CREATE INDEX IF NOT EXISTS idx_provider_budget_events_provider
  ON provider_budget_events(provider_name);
CREATE INDEX IF NOT EXISTS idx_provider_budget_events_created_at
  ON provider_budget_events(created_at);

CREATE INDEX IF NOT EXISTS idx_outreach_messages_contact
  ON outreach_messages(contact_id);
CREATE INDEX IF NOT EXISTS idx_outreach_messages_job_posting
  ON outreach_messages(job_posting_id);
CREATE INDEX IF NOT EXISTS idx_outreach_messages_status
  ON outreach_messages(message_status);
CREATE INDEX IF NOT EXISTS idx_outreach_messages_sent_at
  ON outreach_messages(sent_at);

CREATE INDEX IF NOT EXISTS idx_delivery_feedback_events_message
  ON delivery_feedback_events(outreach_message_id);
CREATE INDEX IF NOT EXISTS idx_delivery_feedback_events_state
  ON delivery_feedback_events(event_state);
CREATE INDEX IF NOT EXISTS idx_delivery_feedback_events_timestamp
  ON delivery_feedback_events(event_timestamp);

DROP VIEW IF EXISTS unresolved_contacts_review;
CREATE VIEW unresolved_contacts_review AS
WITH latest_attempt AS (
  SELECT da.*
  FROM discovery_attempts da
  JOIN (
    SELECT contact_id, MAX(created_at) AS max_created_at
    FROM discovery_attempts
    GROUP BY contact_id
  ) latest
    ON da.contact_id = latest.contact_id
   AND da.created_at = latest.max_created_at
)
SELECT
  c.contact_id,
  c.full_name,
  c.company_name,
  c.contact_status,
  c.current_working_email,
  CASE
    WHEN c.contact_status = 'exhausted' THEN 'contact_exhausted'
    WHEN la.discovery_attempt_id IS NULL THEN 'no_discovery_attempt'
    ELSE 'latest_outcome_' || la.outcome
  END AS unresolved_reason,
  la.discovery_attempt_id,
  la.outcome AS latest_discovery_outcome,
  la.provider_name,
  la.provider_verification_status,
  la.email AS latest_attempt_email,
  la.created_at AS latest_attempt_at
FROM contacts c
LEFT JOIN latest_attempt la
  ON la.contact_id = c.contact_id
WHERE
  c.contact_status = 'exhausted'
  OR (
    c.current_working_email IS NULL
    AND (la.outcome IS NULL OR la.outcome <> 'found')
  );

DROP VIEW IF EXISTS bounced_email_review;
CREATE VIEW bounced_email_review AS
SELECT
  dfe.delivery_feedback_event_id,
  dfe.outreach_message_id,
  om.contact_id,
  om.job_posting_id,
  c.full_name,
  om.recipient_email,
  dfe.event_state,
  dfe.event_timestamp,
  dfe.reply_summary
FROM delivery_feedback_events dfe
JOIN outreach_messages om
  ON om.outreach_message_id = dfe.outreach_message_id
LEFT JOIN contacts c
  ON c.contact_id = om.contact_id
WHERE dfe.event_state = 'bounced';

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

DROP VIEW IF EXISTS open_agent_incidents_review;
CREATE VIEW open_agent_incidents_review AS
SELECT
  ai.agent_incident_id,
  ai.incident_type,
  ai.severity,
  ai.status,
  ai.summary,
  ai.pipeline_run_id,
  ai.lead_id,
  ai.job_posting_id,
  ai.contact_id,
  ai.outreach_message_id,
  ai.created_at,
  ai.updated_at,
  pr.run_status,
  pr.current_stage,
  jp.company_name,
  jp.role_title,
  c.full_name,
  om.recipient_email
FROM agent_incidents ai
LEFT JOIN pipeline_runs pr
  ON pr.pipeline_run_id = ai.pipeline_run_id
LEFT JOIN job_postings jp
  ON jp.job_posting_id = ai.job_posting_id
LEFT JOIN contacts c
  ON c.contact_id = ai.contact_id
LEFT JOIN outreach_messages om
  ON om.outreach_message_id = ai.outreach_message_id
WHERE ai.status IN ('open', 'in_repair', 'escalated');

PRAGMA user_version = 2;
