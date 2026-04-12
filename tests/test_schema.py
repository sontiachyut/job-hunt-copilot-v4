from __future__ import annotations

import sqlite3

import pytest

from job_hunt_copilot.bootstrap import run_bootstrap
from job_hunt_copilot.records import lifecycle_timestamps, new_canonical_id
from tests.support import create_minimal_project


EXPECTED_TABLES = {
    "agent_control_state",
    "agent_incidents",
    "agent_runtime_leases",
    "artifact_records",
    "contacts",
    "delivery_feedback_events",
    "discovery_attempts",
    "expert_review_decisions",
    "expert_review_packets",
    "feedback_sync_runs",
    "job_posting_contacts",
    "job_postings",
    "linkedin_lead_contacts",
    "linkedin_leads",
    "maintenance_change_batches",
    "outreach_messages",
    "override_events",
    "pipeline_runs",
    "provider_budget_events",
    "provider_budget_state",
    "resume_tailoring_runs",
    "schema_migrations",
    "state_transition_events",
    "supervisor_cycles",
    "windows",
}

EXPECTED_VIEWS = {
    "bounced_email_review",
    "expert_review_queue",
    "open_agent_incidents_review",
    "unresolved_contacts_review",
}

EXPECTED_INDEXES = {
    "idx_agent_incidents_pipeline_run",
    "idx_agent_incidents_severity",
    "idx_agent_incidents_status",
    "idx_agent_runtime_leases_expires_at",
    "idx_artifact_records_contact",
    "idx_artifact_records_job_posting",
    "idx_artifact_records_lead",
    "idx_artifact_records_message",
    "idx_artifact_records_type",
    "idx_contacts_identity_key",
    "idx_contacts_linkedin_url",
    "idx_contacts_origin_component",
    "idx_contacts_provider_person",
    "idx_contacts_status",
    "idx_contacts_working_email",
    "idx_delivery_feedback_events_message",
    "idx_delivery_feedback_events_state",
    "idx_delivery_feedback_events_timestamp",
    "idx_discovery_attempts_contact",
    "idx_discovery_attempts_created_at",
    "idx_discovery_attempts_job_posting",
    "idx_discovery_attempts_outcome",
    "idx_expert_review_decisions_decided_at",
    "idx_expert_review_decisions_packet",
    "idx_expert_review_packets_pipeline_run",
    "idx_expert_review_packets_status",
    "idx_feedback_sync_runs_result",
    "idx_feedback_sync_runs_scheduler_name",
    "idx_feedback_sync_runs_started_at",
    "idx_job_posting_contacts_pair",
    "idx_job_posting_contacts_recipient_type",
    "idx_job_posting_contacts_status",
    "idx_job_postings_company_key",
    "idx_job_postings_identity_key",
    "idx_job_postings_lead_id",
    "idx_job_postings_status",
    "idx_linkedin_lead_contacts_pair",
    "idx_linkedin_lead_contacts_recipient_type",
    "idx_linkedin_lead_contacts_role",
    "idx_linkedin_leads_identity_key",
    "idx_linkedin_leads_split_review_status",
    "idx_linkedin_leads_status",
    "idx_outreach_messages_contact",
    "idx_outreach_messages_job_posting",
    "idx_outreach_messages_sent_at",
    "idx_outreach_messages_status",
    "idx_override_events_object",
    "idx_override_events_timestamp",
    "idx_pipeline_runs_job_posting",
    "idx_pipeline_runs_stage",
    "idx_pipeline_runs_status",
    "idx_provider_budget_events_created_at",
    "idx_provider_budget_events_provider",
    "idx_resume_tailoring_runs_job_posting",
    "idx_resume_tailoring_runs_review_status",
    "idx_state_transition_events_object",
    "idx_state_transition_events_timestamp",
    "idx_supervisor_cycles_pipeline_run",
    "idx_supervisor_cycles_result",
    "idx_supervisor_cycles_started_at",
}


def bootstrap_project(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    create_minimal_project(project_root)
    run_bootstrap(project_root=project_root)
    return project_root


def connect_database(db_path):
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    return connection


def test_bootstrap_materializes_canonical_schema_objects(tmp_path):
    project_root = bootstrap_project(tmp_path)
    connection = connect_database(project_root / "job_hunt_copilot.db")

    tables = {
        row["name"]
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    views = {
        row["name"]
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'view'")
    }
    indexes = {
        row["name"]
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'index'")
    }
    user_version = connection.execute("PRAGMA user_version").fetchone()[0]

    connection.close()

    assert EXPECTED_TABLES <= tables
    assert EXPECTED_VIEWS <= views
    assert EXPECTED_INDEXES <= indexes
    assert user_version == 3


def test_review_views_are_queryable_from_canonical_state(tmp_path):
    project_root = bootstrap_project(tmp_path)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    now = "2026-04-05T21:00:00Z"

    connection.execute(
        """
        INSERT INTO linkedin_leads (
          lead_id, lead_identity_key, lead_status, lead_shape, split_review_status,
          source_type, source_reference, source_mode, company_name, role_title,
          created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "ld_test",
            "guidewire|software-engineer",
            "reviewed",
            "posting_plus_contacts",
            "confident",
            "manual_paste",
            "paste/paste.txt",
            "manual_paste",
            "Guidewire",
            "Software Engineer",
            now,
            now,
        ),
    )
    connection.execute(
        """
        INSERT INTO job_postings (
          job_posting_id, lead_id, posting_identity_key, company_name, role_title,
          posting_status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "jp_test",
            "ld_test",
            "guidewire|software-engineer|bedford",
            "Guidewire",
            "Software Engineer",
            "requires_contacts",
            now,
            now,
        ),
    )
    connection.execute(
        """
        INSERT INTO contacts (
          contact_id, identity_key, display_name, company_name, origin_component,
          contact_status, full_name, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "ct_test",
            "alex-kordun|guidewire",
            "Alex Kordun",
            "Guidewire",
            "linkedin_scraping",
            "identified",
            "Alex Kordun",
            now,
            now,
        ),
    )
    connection.execute(
        """
        INSERT INTO job_posting_contacts (
          job_posting_contact_id, job_posting_id, contact_id, recipient_type,
          relevance_reason, link_level_status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "jpc_test",
            "jp_test",
            "ct_test",
            "hiring_manager",
            "poster profile",
            "identified",
            now,
            now,
        ),
    )
    connection.execute(
        """
        INSERT INTO discovery_attempts (
          discovery_attempt_id, contact_id, job_posting_id, outcome, provider_name,
          provider_verification_status, email, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "da_test",
            "ct_test",
            "jp_test",
            "not_found",
            "apollo",
            "not_found",
            None,
            now,
        ),
    )
    connection.execute(
        """
        INSERT INTO outreach_messages (
          outreach_message_id, contact_id, outreach_mode, recipient_email, message_status,
          job_posting_id, job_posting_contact_id, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "msg_test",
            "ct_test",
            "role_targeted",
            "alex@example.com",
            "sent",
            "jp_test",
            "jpc_test",
            now,
            now,
        ),
    )
    connection.execute(
        """
        INSERT INTO delivery_feedback_events (
          delivery_feedback_event_id, outreach_message_id, event_state, event_timestamp,
          contact_id, job_posting_id, reply_summary, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "dfe_test",
            "msg_test",
            "bounced",
            now,
            "ct_test",
            "jp_test",
            "mailbox bounce",
            now,
        ),
    )
    connection.execute(
        """
        INSERT INTO pipeline_runs (
          pipeline_run_id, run_scope_type, run_status, current_stage, lead_id,
          job_posting_id, review_packet_status, run_summary, started_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "pr_test",
            "role_targeted_posting",
            "escalated",
            "agent_review",
            "ld_test",
            "jp_test",
            "pending_expert_review",
            "Tailoring approved; outreach blocked for review",
            now,
            now,
            now,
        ),
    )
    connection.execute(
        """
        INSERT INTO expert_review_packets (
          expert_review_packet_id, pipeline_run_id, packet_status, packet_path,
          job_posting_id, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            "erp_test",
            "pr_test",
            "pending_expert_review",
            "/abs/path/ops/review-packets/erp_test/review_packet.json",
            "jp_test",
            now,
        ),
    )
    connection.execute(
        """
        INSERT INTO agent_incidents (
          agent_incident_id, incident_type, severity, status, summary, pipeline_run_id,
          lead_id, job_posting_id, contact_id, outreach_message_id, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "inc_test",
            "manual_review_required",
            "high",
            "open",
            "Need expert confirmation before sending",
            "pr_test",
            "ld_test",
            "jp_test",
            "ct_test",
            "msg_test",
            now,
            now,
        ),
    )
    connection.commit()

    unresolved = connection.execute(
        """
        SELECT contact_id, unresolved_reason, latest_discovery_outcome, provider_verification_status
        FROM unresolved_contacts_review
        WHERE contact_id = 'ct_test'
        """
    ).fetchone()
    bounced = connection.execute(
        """
        SELECT outreach_message_id, recipient_email, event_state
        FROM bounced_email_review
        WHERE outreach_message_id = 'msg_test'
        """
    ).fetchone()
    expert_queue = connection.execute(
        """
        SELECT pipeline_run_id, packet_path, incident_ids, incident_summaries
        FROM expert_review_queue
        WHERE pipeline_run_id = 'pr_test'
        """
    ).fetchone()
    open_incident = connection.execute(
        """
        SELECT agent_incident_id, run_status, company_name, recipient_email
        FROM open_agent_incidents_review
        WHERE agent_incident_id = 'inc_test'
        """
    ).fetchone()

    connection.close()

    assert dict(unresolved) == {
        "contact_id": "ct_test",
        "unresolved_reason": "latest_outcome_not_found",
        "latest_discovery_outcome": "not_found",
        "provider_verification_status": "not_found",
    }
    assert dict(bounced) == {
        "outreach_message_id": "msg_test",
        "recipient_email": "alex@example.com",
        "event_state": "bounced",
    }
    assert dict(expert_queue) == {
        "pipeline_run_id": "pr_test",
        "packet_path": "/abs/path/ops/review-packets/erp_test/review_packet.json",
        "incident_ids": "inc_test",
        "incident_summaries": "Need expert confirmation before sending",
    }
    assert dict(open_incident) == {
        "agent_incident_id": "inc_test",
        "run_status": "escalated",
        "company_name": "Guidewire",
        "recipient_email": "alex@example.com",
    }


def test_canonical_record_helpers_expose_prefix_and_timestamp_conventions():
    lead_id = new_canonical_id("linkedin_leads")
    posting_id = new_canonical_id("job_postings")
    timestamps = lifecycle_timestamps("2026-04-05T21:00:00Z")

    assert lead_id.startswith("ld_")
    assert posting_id.startswith("jp_")
    assert lead_id != new_canonical_id("linkedin_leads")
    assert timestamps == {
        "created_at": "2026-04-05T21:00:00Z",
        "updated_at": "2026-04-05T21:00:00Z",
    }

    with pytest.raises(ValueError):
        new_canonical_id("agent_control_state")
