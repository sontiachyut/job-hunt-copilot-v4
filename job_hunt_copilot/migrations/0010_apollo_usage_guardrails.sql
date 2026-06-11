PRAGMA foreign_keys = ON;

ALTER TABLE provider_budget_state
  ADD COLUMN breaker_state TEXT NOT NULL DEFAULT 'closed';

ALTER TABLE provider_budget_state
  ADD COLUMN breaker_reason TEXT;

ALTER TABLE provider_budget_state
  ADD COLUMN breaker_message TEXT;

ALTER TABLE provider_budget_state
  ADD COLUMN breaker_until TEXT;

ALTER TABLE provider_budget_state
  ADD COLUMN breaker_set_at TEXT;

ALTER TABLE provider_budget_state
  ADD COLUMN last_usage_checked_at TEXT;

CREATE TABLE IF NOT EXISTS provider_usage_snapshots (
  provider_usage_snapshot_id TEXT PRIMARY KEY,
  provider_name TEXT NOT NULL,
  endpoint_key TEXT NOT NULL,
  day_limit INTEGER,
  day_consumed INTEGER,
  day_left_over INTEGER,
  hour_limit INTEGER,
  hour_consumed INTEGER,
  hour_left_over INTEGER,
  minute_limit INTEGER,
  minute_consumed INTEGER,
  minute_left_over INTEGER,
  observed_at TEXT NOT NULL,
  raw_payload_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_provider_usage_snapshots_provider_endpoint_observed
  ON provider_usage_snapshots(provider_name, endpoint_key, observed_at);

CREATE INDEX IF NOT EXISTS idx_provider_usage_snapshots_observed_at
  ON provider_usage_snapshots(observed_at);

PRAGMA user_version = 10;
