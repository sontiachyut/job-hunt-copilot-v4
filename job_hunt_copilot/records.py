from __future__ import annotations

from datetime import datetime, timezone
from types import MappingProxyType
from uuid import uuid4


CANONICAL_ID_PREFIXES = MappingProxyType(
    {
        "linkedin_leads": "ld",
        "job_postings": "jp",
        "contacts": "ct",
        "linkedin_lead_contacts": "llc",
        "job_posting_contacts": "jpc",
        "resume_tailoring_runs": "rtr",
        "artifact_records": "art",
        "state_transition_events": "ste",
        "override_events": "ovr",
        "feedback_sync_runs": "fsr",
        "pipeline_runs": "pr",
        "supervisor_cycles": "sc",
        "agent_incidents": "inc",
        "expert_review_packets": "erp",
        "expert_review_decisions": "erd",
        "maintenance_change_batches": "mcb",
        "windows": "win",
        "provider_budget_events": "pbe",
        "discovery_attempts": "da",
        "outreach_messages": "msg",
        "delivery_feedback_events": "dfe",
    }
)


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_canonical_id(record_type: str) -> str:
    prefix = CANONICAL_ID_PREFIXES.get(record_type)
    if prefix is None:
        raise ValueError(f"Unsupported canonical record type: {record_type}")
    return f"{prefix}_{uuid4().hex}"


def lifecycle_timestamps(timestamp: str | None = None) -> dict[str, str]:
    current = timestamp or now_utc_iso()
    return {
        "created_at": current,
        "updated_at": current,
    }
