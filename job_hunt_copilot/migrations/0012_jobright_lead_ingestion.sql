CREATE TABLE leads (
  lead_id TEXT PRIMARY KEY,
  lead_identity_key TEXT NOT NULL,
  lead_status TEXT NOT NULL,
  source_type TEXT NOT NULL,
  source_reference TEXT NOT NULL,
  source_mode TEXT NOT NULL,
  source_url TEXT,
  company_name TEXT,
  role_title TEXT,
  location TEXT,
  canonical_jd_artifact_path TEXT,
  active_source_observation_id TEXT,
  reason_code TEXT,
  latest_fit_score REAL,
  latest_fit_label TEXT,
  latest_public_connection_count INTEGER NOT NULL DEFAULT 0,
  latest_personal_connection_count INTEGER NOT NULL DEFAULT 0,
  latest_total_connection_count INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE lead_source_observations (
  source_observation_id TEXT PRIMARY KEY,
  lead_id TEXT NOT NULL,
  ingestion_run_id TEXT NOT NULL,
  source_type TEXT NOT NULL,
  source_reference TEXT NOT NULL,
  source_mode TEXT NOT NULL,
  source_url TEXT,
  observation_kind TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  jobright_job_id TEXT,
  apply_url TEXT,
  display_score REAL,
  rank_desc TEXT,
  recommendation_scores_json TEXT,
  skill_matching_scores_json TEXT,
  industry_matching_scores_json TEXT,
  public_connection_count INTEGER NOT NULL DEFAULT 0,
  personal_connection_count INTEGER NOT NULL DEFAULT 0,
  total_connection_count INTEGER NOT NULL DEFAULT 0,
  job_summary_json TEXT,
  social_connections_json TEXT,
  personal_social_connections_json TEXT,
  jd_artifact_path TEXT,
  jd_hash TEXT,
  jd_is_usable INTEGER NOT NULL DEFAULT 0,
  promotion_eligibility_status TEXT,
  promotion_hold_reason TEXT,
  source_payload_path TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (lead_id) REFERENCES leads(lead_id) ON DELETE CASCADE
);

CREATE TABLE lead_contacts (
  lead_contact_id TEXT PRIMARY KEY,
  lead_id TEXT NOT NULL,
  contact_id TEXT NOT NULL,
  source_observation_id TEXT NOT NULL,
  contact_source_type TEXT NOT NULL,
  contact_source_priority_tier INTEGER NOT NULL,
  contact_source_rank INTEGER NOT NULL,
  is_initial_intended_contact INTEGER NOT NULL DEFAULT 0,
  removed_at TEXT,
  removal_reason TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (lead_id) REFERENCES leads(lead_id) ON DELETE CASCADE,
  FOREIGN KEY (contact_id) REFERENCES contacts(contact_id) ON DELETE CASCADE,
  FOREIGN KEY (source_observation_id) REFERENCES lead_source_observations(source_observation_id) ON DELETE CASCADE,
  UNIQUE (lead_id, contact_id)
);

CREATE INDEX idx_leads_identity_key
  ON leads(lead_identity_key);

CREATE INDEX idx_leads_status
  ON leads(lead_status);

CREATE INDEX idx_leads_active_source_observation_id
  ON leads(active_source_observation_id);

CREATE INDEX idx_lead_source_observations_lead_id
  ON lead_source_observations(lead_id);

CREATE INDEX idx_lead_source_observations_run_kind
  ON lead_source_observations(ingestion_run_id, observation_kind);

CREATE INDEX idx_lead_source_observations_jobright_job_id
  ON lead_source_observations(jobright_job_id);

CREATE INDEX idx_lead_source_observations_observed_at
  ON lead_source_observations(observed_at);

CREATE INDEX idx_lead_source_observations_promotion_status
  ON lead_source_observations(promotion_eligibility_status);

CREATE UNIQUE INDEX idx_lead_contacts_pair
  ON lead_contacts(lead_id, contact_id);

CREATE INDEX idx_lead_contacts_source_type
  ON lead_contacts(contact_source_type);

CREATE INDEX idx_lead_contacts_priority
  ON lead_contacts(contact_source_priority_tier, contact_source_rank);

CREATE INDEX idx_lead_contacts_initial_intended
  ON lead_contacts(is_initial_intended_contact);

ALTER TABLE job_postings
  ADD COLUMN promoted_from_source_observation_id TEXT;

ALTER TABLE job_postings
  ADD COLUMN promotion_fit_score REAL;

ALTER TABLE job_postings
  ADD COLUMN promotion_fit_label TEXT;

ALTER TABLE job_postings
  ADD COLUMN promotion_public_connection_count INTEGER;

ALTER TABLE job_postings
  ADD COLUMN promotion_personal_connection_count INTEGER;

ALTER TABLE job_postings
  ADD COLUMN promotion_total_connection_count INTEGER;

CREATE INDEX idx_job_postings_promoted_source_observation_id
  ON job_postings(promoted_from_source_observation_id);

ALTER TABLE job_posting_contacts
  ADD COLUMN lead_contact_id TEXT;

ALTER TABLE job_posting_contacts
  ADD COLUMN contact_source_type TEXT;

ALTER TABLE job_posting_contacts
  ADD COLUMN contact_source_priority_tier INTEGER;

ALTER TABLE job_posting_contacts
  ADD COLUMN contact_source_rank INTEGER;

ALTER TABLE job_posting_contacts
  ADD COLUMN is_in_intended_outreach_set INTEGER NOT NULL DEFAULT 0;

ALTER TABLE job_posting_contacts
  ADD COLUMN entered_intended_outreach_set_at TEXT;

ALTER TABLE job_posting_contacts
  ADD COLUMN removed_from_intended_outreach_set_at TEXT;

ALTER TABLE job_posting_contacts
  ADD COLUMN intended_outreach_set_removal_reason TEXT;

CREATE INDEX idx_job_posting_contacts_lead_contact_id
  ON job_posting_contacts(lead_contact_id);

CREATE INDEX idx_job_posting_contacts_source_type
  ON job_posting_contacts(contact_source_type);

CREATE INDEX idx_job_posting_contacts_intended_set
  ON job_posting_contacts(is_in_intended_outreach_set);

PRAGMA user_version = 12;
