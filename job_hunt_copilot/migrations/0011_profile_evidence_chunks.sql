CREATE TABLE profile_evidence_chunks (
  evidence_id TEXT PRIMARY KEY,
  text TEXT NOT NULL,
  source_type TEXT NOT NULL,
  evidence_type TEXT NOT NULL,
  skill_tags_json TEXT NOT NULL,
  theme_tags_json TEXT NOT NULL,
  strength INTEGER NOT NULL,
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX idx_profile_evidence_chunks_active
  ON profile_evidence_chunks(is_active);

CREATE INDEX idx_profile_evidence_chunks_source_type
  ON profile_evidence_chunks(source_type);

CREATE INDEX idx_profile_evidence_chunks_evidence_type
  ON profile_evidence_chunks(evidence_type);

CREATE INDEX idx_profile_evidence_chunks_strength
  ON profile_evidence_chunks(strength);

PRAGMA user_version = 11;
