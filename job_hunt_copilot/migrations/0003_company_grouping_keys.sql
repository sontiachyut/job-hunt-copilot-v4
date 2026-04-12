ALTER TABLE job_postings ADD COLUMN canonical_company_key TEXT;
ALTER TABLE job_postings ADD COLUMN provider_company_key TEXT;
ALTER TABLE job_postings ADD COLUMN company_key_source TEXT;

CREATE INDEX IF NOT EXISTS idx_job_postings_company_key
  ON job_postings(canonical_company_key);

PRAGMA user_version = 3;
