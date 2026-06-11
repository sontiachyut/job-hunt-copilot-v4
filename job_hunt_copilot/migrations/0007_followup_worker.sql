PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS followup_cycle_runs (
  followup_cycle_run_id TEXT PRIMARY KEY,
  scheduler_name TEXT NOT NULL,
  scheduler_type TEXT NOT NULL,
  started_at TEXT NOT NULL,
  result TEXT NOT NULL,
  completed_at TEXT,
  candidates_examined INTEGER,
  drafts_created INTEGER,
  messages_sent INTEGER,
  waiting_for_pacing_count INTEGER,
  skipped_replied INTEGER,
  skipped_bounced INTEGER,
  skipped_already_followed_up INTEGER,
  retryable_count INTEGER,
  blocked_count INTEGER,
  held_for_review INTEGER,
  last_checkpoint TEXT,
  error_message TEXT
);

CREATE TABLE IF NOT EXISTS outreach_followup_plans (
  outreach_followup_plan_id TEXT PRIMARY KEY,
  original_outreach_message_id TEXT NOT NULL,
  followup_outreach_message_id TEXT,
  contact_id TEXT NOT NULL,
  job_posting_id TEXT,
  plan_status TEXT NOT NULL,
  followup_sequence INTEGER NOT NULL,
  eligible_after TEXT NOT NULL,
  last_evaluated_at TEXT,
  last_reply_check_at TEXT,
  last_reply_check_result TEXT,
  gmail_thread_id_snapshot TEXT,
  last_skip_reason TEXT,
  agent_reviewed_at TEXT,
  sent_at TEXT,
  draft_artifact_path TEXT,
  review_evidence_artifact_path TEXT,
  retry_count INTEGER NOT NULL DEFAULT 0,
  next_retry_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (original_outreach_message_id) REFERENCES outreach_messages(outreach_message_id),
  FOREIGN KEY (followup_outreach_message_id) REFERENCES outreach_messages(outreach_message_id),
  FOREIGN KEY (contact_id) REFERENCES contacts(contact_id),
  FOREIGN KEY (job_posting_id) REFERENCES job_postings(job_posting_id)
);

CREATE INDEX IF NOT EXISTS idx_followup_cycle_runs_started_at
  ON followup_cycle_runs(started_at);
CREATE INDEX IF NOT EXISTS idx_followup_cycle_runs_result
  ON followup_cycle_runs(result);
CREATE INDEX IF NOT EXISTS idx_followup_cycle_runs_scheduler_name
  ON followup_cycle_runs(scheduler_name);

CREATE INDEX IF NOT EXISTS idx_outreach_followup_plans_original_message
  ON outreach_followup_plans(original_outreach_message_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_outreach_followup_plans_original_sequence
  ON outreach_followup_plans(original_outreach_message_id, followup_sequence);
CREATE INDEX IF NOT EXISTS idx_outreach_followup_plans_followup_message
  ON outreach_followup_plans(followup_outreach_message_id);
CREATE INDEX IF NOT EXISTS idx_outreach_followup_plans_contact
  ON outreach_followup_plans(contact_id);
CREATE INDEX IF NOT EXISTS idx_outreach_followup_plans_job_posting
  ON outreach_followup_plans(job_posting_id);
CREATE INDEX IF NOT EXISTS idx_outreach_followup_plans_status
  ON outreach_followup_plans(plan_status);
CREATE INDEX IF NOT EXISTS idx_outreach_followup_plans_eligible_after
  ON outreach_followup_plans(eligible_after);

PRAGMA user_version = 7;
