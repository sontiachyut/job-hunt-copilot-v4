PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS llm_usage_events (
  llm_usage_event_id TEXT PRIMARY KEY,
  provider_name TEXT,
  model_name TEXT,
  session_id TEXT,
  component_name TEXT NOT NULL,
  operation_name TEXT NOT NULL,
  invocation_status TEXT NOT NULL,
  exit_code INTEGER NOT NULL,
  total_tokens INTEGER,
  usage_parse_status TEXT NOT NULL,
  raw_usage_text TEXT,
  run_directory_path TEXT NOT NULL,
  prompt_artifact_path TEXT,
  output_artifact_path TEXT,
  stdout_artifact_path TEXT,
  stderr_artifact_path TEXT NOT NULL,
  lead_id TEXT,
  job_posting_id TEXT,
  contact_id TEXT,
  outreach_message_id TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (lead_id) REFERENCES linkedin_leads(lead_id) ON DELETE SET NULL,
  FOREIGN KEY (job_posting_id) REFERENCES job_postings(job_posting_id) ON DELETE SET NULL,
  FOREIGN KEY (contact_id) REFERENCES contacts(contact_id) ON DELETE SET NULL,
  FOREIGN KEY (outreach_message_id) REFERENCES outreach_messages(outreach_message_id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_llm_usage_events_created_at
  ON llm_usage_events(created_at);
CREATE INDEX IF NOT EXISTS idx_llm_usage_events_component_operation
  ON llm_usage_events(component_name, operation_name, created_at);
CREATE INDEX IF NOT EXISTS idx_llm_usage_events_job_posting
  ON llm_usage_events(job_posting_id, created_at);
CREATE INDEX IF NOT EXISTS idx_llm_usage_events_contact
  ON llm_usage_events(contact_id, created_at);

PRAGMA user_version = 9;
