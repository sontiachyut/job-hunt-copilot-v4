from __future__ import annotations

import sqlite3
from pathlib import Path

from job_hunt_copilot.artifacts import ArtifactLinkage, publish_json_artifact, register_artifact_record
from job_hunt_copilot.bootstrap import run_bootstrap
from job_hunt_copilot.delivery_feedback import (
    DELIVERY_FEEDBACK_COMPONENT,
    DELIVERY_OUTCOME_ARTIFACT_TYPE,
)
from job_hunt_copilot.outreach import OUTREACH_COMPONENT
from job_hunt_copilot.paths import ProjectPaths
from job_hunt_copilot.review_queries import (
    query_object_traceability,
    query_outstanding_outreach_review_items,
    query_override_history,
    query_review_surfaces,
    query_sent_message_history,
)
from tests.support import create_minimal_project


def bootstrap_project(tmp_path: Path) -> tuple[Path, ProjectPaths]:
    project_root = tmp_path / "repo"
    project_root.mkdir()
    create_minimal_project(project_root)
    run_bootstrap(project_root=project_root)
    return project_root, ProjectPaths.from_root(project_root)


def connect_database(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    return connection


def insert_lead(
    connection: sqlite3.Connection,
    *,
    lead_id: str,
    company_name: str,
    role_title: str,
    created_at: str,
) -> None:
    connection.execute(
        """
        INSERT INTO linkedin_leads (
          lead_id, lead_identity_key, lead_status, lead_shape, split_review_status,
          source_type, source_reference, source_mode, source_url, company_name, role_title,
          created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            lead_id,
            f"{company_name.lower().replace(' ', '-')}|{role_title.lower().replace(' ', '-')}",
            "handed_off",
            "posting_only",
            "not_applicable",
            "gmail_job_alert",
            f"gmail/{lead_id}",
            "gmail_job_alert",
            f"https://example.com/jobs/{lead_id}",
            company_name,
            role_title,
            created_at,
            created_at,
        ),
    )


def insert_posting(
    connection: sqlite3.Connection,
    *,
    job_posting_id: str,
    lead_id: str,
    company_name: str,
    role_title: str,
    posting_status: str,
    created_at: str,
) -> None:
    connection.execute(
        """
        INSERT INTO job_postings (
          job_posting_id, lead_id, posting_identity_key, company_name, role_title,
          posting_status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job_posting_id,
            lead_id,
            f"{company_name.lower().replace(' ', '-')}|{role_title.lower().replace(' ', '-')}",
            company_name,
            role_title,
            posting_status,
            created_at,
            created_at,
        ),
    )


def insert_tailoring_run(
    connection: sqlite3.Connection,
    *,
    resume_tailoring_run_id: str,
    job_posting_id: str,
    tailoring_status: str,
    resume_review_status: str,
    created_at: str,
) -> None:
    connection.execute(
        """
        INSERT INTO resume_tailoring_runs (
          resume_tailoring_run_id, job_posting_id, base_used, tailoring_status,
          resume_review_status, workspace_path, started_at, completed_at,
          created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            resume_tailoring_run_id,
            job_posting_id,
            "generalist",
            tailoring_status,
            resume_review_status,
            f"resume-tailoring/output/tailored/{job_posting_id}",
            created_at,
            created_at,
            created_at,
            created_at,
        ),
    )


def insert_contact(
    connection: sqlite3.Connection,
    *,
    contact_id: str,
    company_name: str,
    display_name: str,
    contact_status: str,
    current_working_email: str | None,
    created_at: str,
) -> None:
    connection.execute(
        """
        INSERT INTO contacts (
          contact_id, identity_key, display_name, company_name, origin_component, contact_status,
          full_name, current_working_email, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            contact_id,
            f"{display_name.lower().replace(' ', '-')}|{company_name.lower().replace(' ', '-')}",
            display_name,
            company_name,
            "email_discovery",
            contact_status,
            display_name,
            current_working_email,
            created_at,
            created_at,
        ),
    )


def insert_posting_contact(
    connection: sqlite3.Connection,
    *,
    job_posting_contact_id: str,
    job_posting_id: str,
    contact_id: str,
    recipient_type: str,
    link_level_status: str,
    created_at: str,
) -> None:
    connection.execute(
        """
        INSERT INTO job_posting_contacts (
          job_posting_contact_id, job_posting_id, contact_id, recipient_type,
          relevance_reason, link_level_status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job_posting_contact_id,
            job_posting_id,
            contact_id,
            recipient_type,
            "Review query test linkage.",
            link_level_status,
            created_at,
            created_at,
        ),
    )


def insert_message(
    connection: sqlite3.Connection,
    *,
    outreach_message_id: str,
    contact_id: str,
    recipient_email: str,
    message_status: str,
    created_at: str,
    subject: str = "Checking in",
    body_text: str = "Hello from Job Hunt Copilot.",
    job_posting_id: str | None = None,
    job_posting_contact_id: str | None = None,
    sent_at: str | None = None,
    thread_id: str | None = None,
    delivery_tracking_id: str | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO outreach_messages (
          outreach_message_id, contact_id, outreach_mode, recipient_email, message_status,
          job_posting_id, job_posting_contact_id, subject, body_text, thread_id,
          delivery_tracking_id, sent_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            outreach_message_id,
            contact_id,
            "role_targeted",
            recipient_email,
            message_status,
            job_posting_id,
            job_posting_contact_id,
            subject,
            body_text,
            thread_id,
            delivery_tracking_id,
            sent_at,
            created_at,
            created_at,
        ),
    )


def insert_delivery_feedback_event(
    connection: sqlite3.Connection,
    *,
    delivery_feedback_event_id: str,
    outreach_message_id: str,
    contact_id: str,
    job_posting_id: str,
    event_state: str,
    event_timestamp: str,
    reply_summary: str | None = None,
    raw_reply_excerpt: str | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO delivery_feedback_events (
          delivery_feedback_event_id, outreach_message_id, event_state, event_timestamp,
          contact_id, job_posting_id, reply_summary, raw_reply_excerpt, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            delivery_feedback_event_id,
            outreach_message_id,
            event_state,
            event_timestamp,
            contact_id,
            job_posting_id,
            reply_summary,
            raw_reply_excerpt,
            event_timestamp,
        ),
    )


def insert_pipeline_run(
    connection: sqlite3.Connection,
    *,
    pipeline_run_id: str,
    lead_id: str,
    job_posting_id: str,
    run_status: str,
    current_stage: str,
    review_packet_status: str,
    started_at: str,
    run_summary: str,
) -> None:
    connection.execute(
        """
        INSERT INTO pipeline_runs (
          pipeline_run_id, run_scope_type, run_status, current_stage, lead_id,
          job_posting_id, review_packet_status, run_summary, started_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            pipeline_run_id,
            "role_targeted_posting",
            run_status,
            current_stage,
            lead_id,
            job_posting_id,
            review_packet_status,
            run_summary,
            started_at,
            started_at,
            started_at,
        ),
    )


def insert_expert_review_packet(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    expert_review_packet_id: str,
    pipeline_run_id: str,
    job_posting_id: str,
    lead_id: str,
    created_at: str,
) -> None:
    json_path = paths.review_packet_json_path(pipeline_run_id)
    markdown_path = paths.review_packet_markdown_path(pipeline_run_id)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        '{"summary":"Review packet for testing.","recommended_actions":["inspect"]}\n',
        encoding="utf-8",
    )
    markdown_path.write_text("# Review packet\n", encoding="utf-8")
    linkage = ArtifactLinkage(lead_id=lead_id, job_posting_id=job_posting_id)
    register_artifact_record(
        connection,
        paths,
        artifact_type="expert_review_packet_json",
        artifact_path=json_path,
        producer_component="supervisor_agent",
        linkage=linkage,
        created_at=created_at,
    )
    register_artifact_record(
        connection,
        paths,
        artifact_type="expert_review_packet_markdown",
        artifact_path=markdown_path,
        producer_component="supervisor_agent",
        linkage=linkage,
        created_at=created_at,
    )
    connection.execute(
        """
        INSERT INTO expert_review_packets (
          expert_review_packet_id, pipeline_run_id, packet_status, packet_path,
          job_posting_id, summary_excerpt, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            expert_review_packet_id,
            pipeline_run_id,
            "pending_expert_review",
            paths.relative_to_root(json_path).as_posix(),
            job_posting_id,
            "Review packet for testing.",
            created_at,
        ),
    )


def insert_incident(
    connection: sqlite3.Connection,
    *,
    agent_incident_id: str,
    pipeline_run_id: str,
    lead_id: str,
    job_posting_id: str,
    contact_id: str | None,
    outreach_message_id: str | None,
    created_at: str,
    summary: str,
) -> None:
    connection.execute(
        """
        INSERT INTO agent_incidents (
          agent_incident_id, incident_type, severity, status, summary, pipeline_run_id,
          lead_id, job_posting_id, contact_id, outreach_message_id, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            agent_incident_id,
            "manual_review_required",
            "high",
            "open",
            summary,
            pipeline_run_id,
            lead_id,
            job_posting_id,
            contact_id,
            outreach_message_id,
            created_at,
            created_at,
        ),
    )


def insert_override_event(
    connection: sqlite3.Connection,
    *,
    override_event_id: str,
    object_type: str,
    object_id: str,
    component_stage: str,
    previous_value: str,
    new_value: str,
    override_reason: str,
    override_timestamp: str,
    job_posting_id: str | None = None,
    contact_id: str | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO override_events (
          override_event_id, object_type, object_id, component_stage, previous_value,
          new_value, override_reason, override_timestamp, override_by,
          job_posting_id, contact_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            override_event_id,
            object_type,
            object_id,
            component_stage,
            previous_value,
            new_value,
            override_reason,
            override_timestamp,
            "owner",
            job_posting_id,
            contact_id,
        ),
    )


def insert_state_transition(
    connection: sqlite3.Connection,
    *,
    state_transition_event_id: str,
    object_type: str,
    object_id: str,
    stage: str,
    previous_state: str,
    new_state: str,
    transition_timestamp: str,
    transition_reason: str,
    job_posting_id: str | None = None,
    contact_id: str | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO state_transition_events (
          state_transition_event_id, object_type, object_id, stage, previous_state,
          new_state, transition_timestamp, transition_reason, caused_by,
          job_posting_id, contact_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            state_transition_event_id,
            object_type,
            object_id,
            stage,
            previous_state,
            new_state,
            transition_timestamp,
            transition_reason,
            "review_queries_test",
            job_posting_id,
            contact_id,
        ),
    )


def publish_send_result_artifact(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    company_name: str,
    role_title: str,
    lead_id: str,
    job_posting_id: str,
    contact_id: str,
    outreach_message_id: str,
    result: str,
    send_status: str,
    produced_at: str,
    reason_code: str | None = None,
    message: str | None = None,
) -> None:
    publish_json_artifact(
        connection,
        paths,
        artifact_type="send_result",
        artifact_path=paths.outreach_message_send_result_path(
            company_name,
            role_title,
            outreach_message_id,
        ),
        producer_component=OUTREACH_COMPONENT,
        result=result,
        linkage=ArtifactLinkage(
            lead_id=lead_id,
            job_posting_id=job_posting_id,
            contact_id=contact_id,
            outreach_message_id=outreach_message_id,
        ),
        payload={
            "send_status": send_status,
            "produced_for": "review_queries_test",
        },
        produced_at=produced_at,
        reason_code=reason_code,
        message=message,
    )


def publish_delivery_outcome_artifact(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    company_name: str,
    role_title: str,
    lead_id: str,
    job_posting_id: str,
    contact_id: str,
    outreach_message_id: str,
    delivery_feedback_event_id: str,
    event_state: str,
    event_timestamp: str,
) -> None:
    publish_json_artifact(
        connection,
        paths,
        artifact_type=DELIVERY_OUTCOME_ARTIFACT_TYPE,
        artifact_path=paths.outreach_message_delivery_outcome_path(
            company_name,
            role_title,
            outreach_message_id,
            delivery_feedback_event_id,
        ),
        producer_component=DELIVERY_FEEDBACK_COMPONENT,
        result="success",
        linkage=ArtifactLinkage(
            lead_id=lead_id,
            job_posting_id=job_posting_id,
            contact_id=contact_id,
            outreach_message_id=outreach_message_id,
        ),
        payload={
            "delivery_feedback_event_id": delivery_feedback_event_id,
            "event_state": event_state,
            "event_timestamp": event_timestamp,
        },
        produced_at=event_timestamp,
    )


def test_query_review_surfaces_exposes_operational_review_state(tmp_path: Path):
    project_root, paths = bootstrap_project(tmp_path)
    connection = connect_database(project_root / "job_hunt_copilot.db")

    insert_lead(
        connection,
        lead_id="ld_pending",
        company_name="Acme Robotics",
        role_title="AI Platform Engineer",
        created_at="2026-04-07T09:00:00Z",
    )
    insert_posting(
        connection,
        job_posting_id="jp_pending",
        lead_id="ld_pending",
        company_name="Acme Robotics",
        role_title="AI Platform Engineer",
        posting_status="resume_review_pending",
        created_at="2026-04-07T09:00:00Z",
    )
    insert_tailoring_run(
        connection,
        resume_tailoring_run_id="rtr_pending",
        job_posting_id="jp_pending",
        tailoring_status="tailored",
        resume_review_status="resume_review_pending",
        created_at="2026-04-07T09:05:00Z",
    )

    insert_lead(
        connection,
        lead_id="ld_contacts",
        company_name="Beacon Labs",
        role_title="Platform Engineer",
        created_at="2026-04-07T09:10:00Z",
    )
    insert_posting(
        connection,
        job_posting_id="jp_contacts",
        lead_id="ld_contacts",
        company_name="Beacon Labs",
        role_title="Platform Engineer",
        posting_status="requires_contacts",
        created_at="2026-04-07T09:10:00Z",
    )
    insert_contact(
        connection,
        contact_id="ct_working",
        company_name="Beacon Labs",
        display_name="Priya Recruiter",
        contact_status="working_email_found",
        current_working_email="priya@beacon.example",
        created_at="2026-04-07T09:11:00Z",
    )
    insert_posting_contact(
        connection,
        job_posting_contact_id="jpc_working",
        job_posting_id="jp_contacts",
        contact_id="ct_working",
        recipient_type="recruiter",
        link_level_status="shortlisted",
        created_at="2026-04-07T09:11:00Z",
    )
    insert_contact(
        connection,
        contact_id="ct_unresolved",
        company_name="Beacon Labs",
        display_name="Morgan Manager",
        contact_status="identified",
        current_working_email=None,
        created_at="2026-04-07T09:12:00Z",
    )
    insert_posting_contact(
        connection,
        job_posting_contact_id="jpc_unresolved",
        job_posting_id="jp_contacts",
        contact_id="ct_unresolved",
        recipient_type="hiring_manager",
        link_level_status="identified",
        created_at="2026-04-07T09:12:00Z",
    )
    connection.execute(
        """
        INSERT INTO discovery_attempts (
          discovery_attempt_id, contact_id, job_posting_id, outcome, provider_name,
          provider_verification_status, email, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "da_unresolved",
            "ct_unresolved",
            "jp_contacts",
            "not_found",
            "hunter",
            "not_found",
            None,
            "2026-04-07T09:20:00Z",
        ),
    )

    insert_lead(
        connection,
        lead_id="ld_sent",
        company_name="Crest AI",
        role_title="Staff ML Infra Engineer",
        created_at="2026-04-07T09:30:00Z",
    )
    insert_posting(
        connection,
        job_posting_id="jp_sent",
        lead_id="ld_sent",
        company_name="Crest AI",
        role_title="Staff ML Infra Engineer",
        posting_status="completed",
        created_at="2026-04-07T09:30:00Z",
    )
    insert_contact(
        connection,
        contact_id="ct_replied",
        company_name="Crest AI",
        display_name="Alex Engineer",
        contact_status="sent",
        current_working_email="alex@crest.example",
        created_at="2026-04-07T09:31:00Z",
    )
    insert_posting_contact(
        connection,
        job_posting_contact_id="jpc_replied",
        job_posting_id="jp_sent",
        contact_id="ct_replied",
        recipient_type="engineer",
        link_level_status="outreach_done",
        created_at="2026-04-07T09:31:00Z",
    )
    insert_message(
        connection,
        outreach_message_id="msg_replied",
        contact_id="ct_replied",
        recipient_email="alex@crest.example",
        message_status="sent",
        job_posting_id="jp_sent",
        job_posting_contact_id="jpc_replied",
        subject="Loved the ML infra role",
        body_text="I would appreciate any routing advice.",
        sent_at="2026-04-07T09:40:00Z",
        thread_id="thread-msg_replied",
        delivery_tracking_id="delivery-msg_replied",
        created_at="2026-04-07T09:35:00Z",
    )
    publish_send_result_artifact(
        connection,
        paths,
        company_name="Crest AI",
        role_title="Staff ML Infra Engineer",
        lead_id="ld_sent",
        job_posting_id="jp_sent",
        contact_id="ct_replied",
        outreach_message_id="msg_replied",
        result="success",
        send_status="sent",
        produced_at="2026-04-07T09:40:00Z",
    )
    insert_delivery_feedback_event(
        connection,
        delivery_feedback_event_id="dfe_replied",
        outreach_message_id="msg_replied",
        contact_id="ct_replied",
        job_posting_id="jp_sent",
        event_state="replied",
        event_timestamp="2026-04-07T09:47:00Z",
        reply_summary="Happy to connect next week.",
    )
    publish_delivery_outcome_artifact(
        connection,
        paths,
        company_name="Crest AI",
        role_title="Staff ML Infra Engineer",
        lead_id="ld_sent",
        job_posting_id="jp_sent",
        contact_id="ct_replied",
        outreach_message_id="msg_replied",
        delivery_feedback_event_id="dfe_replied",
        event_state="replied",
        event_timestamp="2026-04-07T09:47:00Z",
    )

    insert_contact(
        connection,
        contact_id="ct_bounced",
        company_name="Crest AI",
        display_name="Dana Recruiter",
        contact_status="sent",
        current_working_email="dana@crest.example",
        created_at="2026-04-07T09:32:00Z",
    )
    insert_posting_contact(
        connection,
        job_posting_contact_id="jpc_bounced",
        job_posting_id="jp_sent",
        contact_id="ct_bounced",
        recipient_type="recruiter",
        link_level_status="outreach_done",
        created_at="2026-04-07T09:32:00Z",
    )
    insert_message(
        connection,
        outreach_message_id="msg_bounced",
        contact_id="ct_bounced",
        recipient_email="dana@crest.example",
        message_status="sent",
        job_posting_id="jp_sent",
        job_posting_contact_id="jpc_bounced",
        subject="Interested in the ML infra role",
        body_text="Sharing quick context here.",
        sent_at="2026-04-07T09:45:00Z",
        thread_id="thread-msg_bounced",
        delivery_tracking_id="delivery-msg_bounced",
        created_at="2026-04-07T09:36:00Z",
    )
    publish_send_result_artifact(
        connection,
        paths,
        company_name="Crest AI",
        role_title="Staff ML Infra Engineer",
        lead_id="ld_sent",
        job_posting_id="jp_sent",
        contact_id="ct_bounced",
        outreach_message_id="msg_bounced",
        result="success",
        send_status="sent",
        produced_at="2026-04-07T09:45:00Z",
    )
    insert_delivery_feedback_event(
        connection,
        delivery_feedback_event_id="dfe_bounced",
        outreach_message_id="msg_bounced",
        contact_id="ct_bounced",
        job_posting_id="jp_sent",
        event_state="bounced",
        event_timestamp="2026-04-07T09:48:00Z",
        reply_summary="Mailbox rejected recipient.",
    )
    publish_delivery_outcome_artifact(
        connection,
        paths,
        company_name="Crest AI",
        role_title="Staff ML Infra Engineer",
        lead_id="ld_sent",
        job_posting_id="jp_sent",
        contact_id="ct_bounced",
        outreach_message_id="msg_bounced",
        delivery_feedback_event_id="dfe_bounced",
        event_state="bounced",
        event_timestamp="2026-04-07T09:48:00Z",
    )

    insert_pipeline_run(
        connection,
        pipeline_run_id="pr_review",
        lead_id="ld_sent",
        job_posting_id="jp_sent",
        run_status="escalated",
        current_stage="delivery_feedback",
        review_packet_status="pending_expert_review",
        started_at="2026-04-07T09:50:00Z",
        run_summary="Delivery feedback found a bounced message requiring review.",
    )
    insert_expert_review_packet(
        connection,
        paths,
        expert_review_packet_id="erp_review",
        pipeline_run_id="pr_review",
        job_posting_id="jp_sent",
        lead_id="ld_sent",
        created_at="2026-04-07T09:51:00Z",
    )
    insert_incident(
        connection,
        agent_incident_id="inc_review",
        pipeline_run_id="pr_review",
        lead_id="ld_sent",
        job_posting_id="jp_sent",
        contact_id="ct_bounced",
        outreach_message_id="msg_bounced",
        created_at="2026-04-07T09:52:00Z",
        summary="Owner review required after a bounced delivery signal.",
    )
    connection.commit()

    review_surfaces = query_review_surfaces(connection, project_root=project_root)
    sent_history = query_sent_message_history(connection)

    pending_posting = next(
        item for item in review_surfaces["posting_states"] if item["job_posting_id"] == "jp_pending"
    )
    assert pending_posting["posting_status"] == "resume_review_pending"
    assert pending_posting["latest_resume_review_status"] == "resume_review_pending"

    working_contact = next(
        item for item in review_surfaces["contact_states"] if item["contact_id"] == "ct_working"
    )
    assert working_contact["contact_status"] == "working_email_found"

    replied_contact = next(
        item for item in review_surfaces["contact_states"] if item["contact_id"] == "ct_replied"
    )
    assert replied_contact["contact_status"] == "sent"
    assert replied_contact["latest_delivery_outcome"] == "replied"

    unresolved_contact = next(
        item
        for item in review_surfaces["unresolved_discovery_cases"]
        if item["contact_id"] == "ct_unresolved"
    )
    assert unresolved_contact["unresolved_reason"] == "latest_outcome_not_found"

    bounced_case = next(
        item
        for item in review_surfaces["bounced_email_cases"]
        if item["outreach_message_id"] == "msg_bounced"
    )
    assert bounced_case["event_state"] == "bounced"

    review_packet = next(
        item
        for item in review_surfaces["pending_expert_review_packets"]
        if item["expert_review_packet_id"] == "erp_review"
    )
    assert review_packet["pipeline_run_id"] == "pr_review"

    incident = next(
        item for item in review_surfaces["open_agent_incidents"] if item["agent_incident_id"] == "inc_review"
    )
    assert incident["outreach_message_id"] == "msg_bounced"

    replied_message = next(item for item in sent_history if item["outreach_message_id"] == "msg_replied")
    assert replied_message["display_name"] == "Alex Engineer"
    assert replied_message["job_posting_id"] == "jp_sent"
    assert replied_message["subject"] == "Loved the ML infra role"
    assert replied_message["body_text"] == "I would appreciate any routing advice."
    assert replied_message["sent_at"] == "2026-04-07T09:40:00Z"
    assert replied_message["latest_delivery_outcome"] == "replied"
    assert replied_message["latest_delivery_outcome_artifact_path"].endswith("delivery_outcome.json")

    connection.close()


def test_query_outstanding_outreach_review_items_includes_blocked_failed_and_repeat_cases(tmp_path: Path):
    project_root, paths = bootstrap_project(tmp_path)
    connection = connect_database(project_root / "job_hunt_copilot.db")

    insert_lead(
        connection,
        lead_id="ld_review",
        company_name="Northstar Systems",
        role_title="Backend Engineer",
        created_at="2026-04-07T11:00:00Z",
    )
    insert_posting(
        connection,
        job_posting_id="jp_review",
        lead_id="ld_review",
        company_name="Northstar Systems",
        role_title="Backend Engineer",
        posting_status="outreach_in_progress",
        created_at="2026-04-07T11:00:00Z",
    )

    insert_contact(
        connection,
        contact_id="ct_blocked",
        company_name="Northstar Systems",
        display_name="Blocked Recruiter",
        contact_status="outreach_in_progress",
        current_working_email="blocked@northstar.example",
        created_at="2026-04-07T11:01:00Z",
    )
    insert_posting_contact(
        connection,
        job_posting_contact_id="jpc_blocked",
        job_posting_id="jp_review",
        contact_id="ct_blocked",
        recipient_type="recruiter",
        link_level_status="exhausted",
        created_at="2026-04-07T11:01:00Z",
    )
    insert_message(
        connection,
        outreach_message_id="msg_blocked",
        contact_id="ct_blocked",
        recipient_email="blocked@northstar.example",
        message_status="blocked",
        job_posting_id="jp_review",
        job_posting_contact_id="jpc_blocked",
        subject="Blocked send",
        body_text="Blocked message body",
        created_at="2026-04-07T11:05:00Z",
    )
    publish_send_result_artifact(
        connection,
        paths,
        company_name="Northstar Systems",
        role_title="Backend Engineer",
        lead_id="ld_review",
        job_posting_id="jp_review",
        contact_id="ct_blocked",
        outreach_message_id="msg_blocked",
        result="blocked",
        send_status="blocked",
        produced_at="2026-04-07T11:06:00Z",
        reason_code="repeat_outreach_review_required",
        message="Prior outreach history exists for this contact, so automatic repeat sending is blocked pending review.",
    )

    insert_contact(
        connection,
        contact_id="ct_failed",
        company_name="Northstar Systems",
        display_name="Failed Manager",
        contact_status="outreach_in_progress",
        current_working_email="failed@northstar.example",
        created_at="2026-04-07T11:02:00Z",
    )
    insert_posting_contact(
        connection,
        job_posting_contact_id="jpc_failed",
        job_posting_id="jp_review",
        contact_id="ct_failed",
        recipient_type="hiring_manager",
        link_level_status="outreach_in_progress",
        created_at="2026-04-07T11:02:00Z",
    )
    insert_message(
        connection,
        outreach_message_id="msg_failed",
        contact_id="ct_failed",
        recipient_email="failed@northstar.example",
        message_status="failed",
        job_posting_id="jp_review",
        job_posting_contact_id="jpc_failed",
        subject="Failed send",
        body_text="Failed message body",
        created_at="2026-04-07T11:07:00Z",
    )
    publish_send_result_artifact(
        connection,
        paths,
        company_name="Northstar Systems",
        role_title="Backend Engineer",
        lead_id="ld_review",
        job_posting_id="jp_review",
        contact_id="ct_failed",
        outreach_message_id="msg_failed",
        result="failed",
        send_status="failed",
        produced_at="2026-04-07T11:08:00Z",
        reason_code="smtp_rejected",
        message="The provider rejected the message after draft publication.",
    )

    insert_lead(
        connection,
        lead_id="ld_old",
        company_name="OtherCo",
        role_title="Earlier Role",
        created_at="2026-04-06T08:00:00Z",
    )
    insert_posting(
        connection,
        job_posting_id="jp_old",
        lead_id="ld_old",
        company_name="OtherCo",
        role_title="Earlier Role",
        posting_status="completed",
        created_at="2026-04-06T08:00:00Z",
    )
    insert_contact(
        connection,
        contact_id="ct_repeat",
        company_name="Northstar Systems",
        display_name="Repeat Engineer",
        contact_status="working_email_found",
        current_working_email="repeat@northstar.example",
        created_at="2026-04-07T11:03:00Z",
    )
    insert_posting_contact(
        connection,
        job_posting_contact_id="jpc_repeat",
        job_posting_id="jp_review",
        contact_id="ct_repeat",
        recipient_type="engineer",
        link_level_status="shortlisted",
        created_at="2026-04-07T11:03:00Z",
    )
    insert_message(
        connection,
        outreach_message_id="msg_old",
        contact_id="ct_repeat",
        recipient_email="repeat@northstar.example",
        message_status="sent",
        job_posting_id="jp_old",
        subject="Earlier outreach",
        body_text="Earlier message body",
        sent_at="2026-04-06T09:00:00Z",
        created_at="2026-04-06T08:30:00Z",
    )

    connection.commit()

    review_items = query_outstanding_outreach_review_items(connection, project_root=project_root)

    blocked_item = next(item for item in review_items if item["outreach_message_id"] == "msg_blocked")
    assert blocked_item["item_type"] == "blocked_message"
    assert blocked_item["reason_code"] == "repeat_outreach_review_required"

    failed_item = next(item for item in review_items if item["outreach_message_id"] == "msg_failed")
    assert failed_item["item_type"] == "failed_message"
    assert failed_item["reason_code"] == "smtp_rejected"
    assert failed_item["message"] == "The provider rejected the message after draft publication."

    repeat_item = next(item for item in review_items if item["contact_id"] == "ct_repeat")
    assert repeat_item["item_type"] == "repeat_outreach_contact"
    assert repeat_item["reason_code"] == "repeat_outreach_review_required"
    assert repeat_item["prior_outreach_count"] == 1

    connection.close()


def test_override_history_and_traceability_queries_surface_artifacts_transitions_and_review_links(
    tmp_path: Path,
):
    project_root, paths = bootstrap_project(tmp_path)
    connection = connect_database(project_root / "job_hunt_copilot.db")

    insert_lead(
        connection,
        lead_id="ld_trace",
        company_name="Vector Works",
        role_title="Principal Platform Engineer",
        created_at="2026-04-07T12:00:00Z",
    )
    insert_posting(
        connection,
        job_posting_id="jp_trace",
        lead_id="ld_trace",
        company_name="Vector Works",
        role_title="Principal Platform Engineer",
        posting_status="outreach_in_progress",
        created_at="2026-04-07T12:00:00Z",
    )
    insert_contact(
        connection,
        contact_id="ct_trace",
        company_name="Vector Works",
        display_name="Taylor Architect",
        contact_status="sent",
        current_working_email="taylor@vector.example",
        created_at="2026-04-07T12:01:00Z",
    )
    insert_posting_contact(
        connection,
        job_posting_contact_id="jpc_trace",
        job_posting_id="jp_trace",
        contact_id="ct_trace",
        recipient_type="hiring_manager",
        link_level_status="outreach_done",
        created_at="2026-04-07T12:01:00Z",
    )
    insert_message(
        connection,
        outreach_message_id="msg_trace",
        contact_id="ct_trace",
        recipient_email="taylor@vector.example",
        message_status="sent",
        job_posting_id="jp_trace",
        job_posting_contact_id="jpc_trace",
        subject="Vector Works platform role",
        body_text="Sharing a short note and attached resume.",
        sent_at="2026-04-07T12:10:00Z",
        thread_id="thread-msg_trace",
        delivery_tracking_id="delivery-msg_trace",
        created_at="2026-04-07T12:05:00Z",
    )
    publish_send_result_artifact(
        connection,
        paths,
        company_name="Vector Works",
        role_title="Principal Platform Engineer",
        lead_id="ld_trace",
        job_posting_id="jp_trace",
        contact_id="ct_trace",
        outreach_message_id="msg_trace",
        result="success",
        send_status="sent",
        produced_at="2026-04-07T12:10:00Z",
    )
    insert_delivery_feedback_event(
        connection,
        delivery_feedback_event_id="dfe_trace",
        outreach_message_id="msg_trace",
        contact_id="ct_trace",
        job_posting_id="jp_trace",
        event_state="not_bounced",
        event_timestamp="2026-04-07T12:40:00Z",
    )
    publish_delivery_outcome_artifact(
        connection,
        paths,
        company_name="Vector Works",
        role_title="Principal Platform Engineer",
        lead_id="ld_trace",
        job_posting_id="jp_trace",
        contact_id="ct_trace",
        outreach_message_id="msg_trace",
        delivery_feedback_event_id="dfe_trace",
        event_state="not_bounced",
        event_timestamp="2026-04-07T12:40:00Z",
    )
    insert_state_transition(
        connection,
        state_transition_event_id="ste_trace",
        object_type="job_posting",
        object_id="jp_trace",
        stage="posting_status",
        previous_state="ready_for_outreach",
        new_state="outreach_in_progress",
        transition_timestamp="2026-04-07T12:05:00Z",
        transition_reason="Drafting began for the active outreach wave.",
        job_posting_id="jp_trace",
    )
    insert_override_event(
        connection,
        override_event_id="ovr_trace",
        object_type="job_posting",
        object_id="jp_trace",
        component_stage="posting_status",
        previous_value="requires_contacts",
        new_value="ready_for_outreach",
        override_reason="Owner confirmed the linked contact set was already sufficient.",
        override_timestamp="2026-04-07T12:02:00Z",
        job_posting_id="jp_trace",
    )
    insert_pipeline_run(
        connection,
        pipeline_run_id="pr_trace",
        lead_id="ld_trace",
        job_posting_id="jp_trace",
        run_status="escalated",
        current_stage="delivery_feedback",
        review_packet_status="pending_expert_review",
        started_at="2026-04-07T12:41:00Z",
        run_summary="Message traceability review packet.",
    )
    insert_expert_review_packet(
        connection,
        paths,
        expert_review_packet_id="erp_trace",
        pipeline_run_id="pr_trace",
        job_posting_id="jp_trace",
        lead_id="ld_trace",
        created_at="2026-04-07T12:42:00Z",
    )
    insert_incident(
        connection,
        agent_incident_id="inc_trace",
        pipeline_run_id="pr_trace",
        lead_id="ld_trace",
        job_posting_id="jp_trace",
        contact_id="ct_trace",
        outreach_message_id="msg_trace",
        created_at="2026-04-07T12:43:00Z",
        summary="Trace message linked into expert review packet.",
    )
    connection.commit()

    override_history = query_override_history(
        connection,
        object_type="job_posting",
        object_id="jp_trace",
    )
    assert len(override_history) == 1
    assert override_history[0]["previous_value"] == "requires_contacts"
    assert override_history[0]["new_value"] == "ready_for_outreach"
    assert override_history[0]["override_reason"] == (
        "Owner confirmed the linked contact set was already sufficient."
    )

    traceability = query_object_traceability(
        connection,
        project_root=project_root,
        object_type="job_posting",
        object_id="jp_trace",
    )
    assert traceability["snapshot"]["posting_status"] == "outreach_in_progress"
    assert {artifact["artifact_type"] for artifact in traceability["artifacts"]} >= {
        "send_result",
        "delivery_outcome",
        "expert_review_packet_json",
    }
    assert traceability["state_transitions"][0]["new_state"] == "outreach_in_progress"

    downstream_messages = traceability["downstream_records"]["outreach_messages"]
    assert len(downstream_messages) == 1
    assert downstream_messages[0]["outreach_message_id"] == "msg_trace"
    assert downstream_messages[0]["latest_delivery_outcome"] == "not_bounced"
    assert downstream_messages[0]["linked_incident_ids"] == "inc_trace"
    assert downstream_messages[0]["linked_review_packet_ids"] == "erp_trace"

    review_packets = traceability["downstream_records"]["expert_review_packets"]
    assert len(review_packets) == 1
    assert review_packets[0]["expert_review_packet_id"] == "erp_trace"

    connection.close()
