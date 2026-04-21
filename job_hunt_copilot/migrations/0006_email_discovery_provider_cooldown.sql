PRAGMA foreign_keys = ON;

ALTER TABLE provider_budget_state
  ADD COLUMN cooldown_until TEXT;

ALTER TABLE provider_budget_state
  ADD COLUMN cooldown_reason TEXT;

ALTER TABLE provider_budget_state
  ADD COLUMN cooldown_message TEXT;

ALTER TABLE provider_budget_state
  ADD COLUMN cooldown_set_at TEXT;

PRAGMA user_version = 6;
