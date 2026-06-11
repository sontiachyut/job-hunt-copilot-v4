PRAGMA foreign_keys = ON;

ALTER TABLE contacts ADD COLUMN apollo_person_id TEXT;
ALTER TABLE contacts ADD COLUMN apollo_organization_id TEXT;
ALTER TABLE contacts ADD COLUMN apollo_current_title TEXT;
ALTER TABLE contacts ADD COLUMN apollo_current_company TEXT;
ALTER TABLE contacts ADD COLUMN apollo_headline TEXT;
ALTER TABLE contacts ADD COLUMN apollo_location TEXT;
ALTER TABLE contacts ADD COLUMN apollo_linkedin_url TEXT;
ALTER TABLE contacts ADD COLUMN apollo_work_email TEXT;
ALTER TABLE contacts ADD COLUMN apollo_last_refreshed_at TEXT;

CREATE TABLE IF NOT EXISTS contact_provider_profiles (
  contact_provider_profile_id TEXT PRIMARY KEY,
  contact_id TEXT NOT NULL,
  provider_name TEXT NOT NULL,
  provider_person_id TEXT,
  provider_organization_id TEXT,
  profile_stage TEXT NOT NULL,
  raw_payload_json TEXT NOT NULL,
  provider_observed_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (contact_id) REFERENCES contacts(contact_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS contact_employment_history (
  contact_employment_history_id TEXT PRIMARY KEY,
  contact_id TEXT NOT NULL,
  provider_name TEXT NOT NULL,
  provider_person_id TEXT,
  company_label TEXT,
  role_title TEXT,
  start_date TEXT,
  end_date TEXT,
  is_current INTEGER,
  source_sort_index INTEGER NOT NULL,
  raw_payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (contact_id) REFERENCES contacts(contact_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS job_posting_provider_contexts (
  job_posting_provider_context_id TEXT PRIMARY KEY,
  job_posting_id TEXT NOT NULL,
  provider_name TEXT NOT NULL,
  context_stage TEXT NOT NULL,
  provider_organization_id TEXT,
  raw_payload_json TEXT NOT NULL,
  provider_observed_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (job_posting_id) REFERENCES job_postings(job_posting_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_contacts_apollo_person_id
  ON contacts(apollo_person_id);
CREATE INDEX IF NOT EXISTS idx_contacts_apollo_org_id
  ON contacts(apollo_organization_id);

CREATE INDEX IF NOT EXISTS idx_contact_provider_profiles_contact_provider_created
  ON contact_provider_profiles(contact_id, provider_name, created_at);
CREATE INDEX IF NOT EXISTS idx_contact_provider_profiles_provider_person
  ON contact_provider_profiles(provider_name, provider_person_id);

CREATE INDEX IF NOT EXISTS idx_contact_employment_history_contact_provider_sort
  ON contact_employment_history(contact_id, provider_name, source_sort_index);

CREATE INDEX IF NOT EXISTS idx_job_posting_provider_contexts_posting_provider_stage_created
  ON job_posting_provider_contexts(job_posting_id, provider_name, context_stage, created_at);

PRAGMA user_version = 8;
