ALTER TABLE job_postings
  ADD COLUMN application_state TEXT DEFAULT 'not_applied';

ALTER TABLE job_postings
  ADD COLUMN applied_at TEXT;

ALTER TABLE job_postings
  ADD COLUMN application_url TEXT;

ALTER TABLE job_postings
  ADD COLUMN application_notes TEXT;

ALTER TABLE job_postings
  ADD COLUMN application_updated_at TEXT;

ALTER TABLE contacts
  ADD COLUMN responder_state TEXT DEFAULT 'none';

ALTER TABLE contacts
  ADD COLUMN responded_at TEXT;

ALTER TABLE contacts
  ADD COLUMN responder_notes TEXT;

ALTER TABLE contacts
  ADD COLUMN responder_updated_at TEXT;

CREATE INDEX IF NOT EXISTS idx_job_postings_application_state
  ON job_postings(application_state);

CREATE INDEX IF NOT EXISTS idx_contacts_responder_state
  ON contacts(responder_state);

PRAGMA user_version = 4;
