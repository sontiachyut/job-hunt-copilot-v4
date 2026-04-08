from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from job_hunt_copilot.bootstrap import run_bootstrap
from job_hunt_copilot.paths import ProjectPaths
from job_hunt_copilot.supervisor import (
    ACTION_PERFORM_MANDATORY_AGENT_REVIEW,
    REVIEW_PACKET_STATUS_PENDING,
    RUN_STATUS_ESCALATED,
    RUN_STATUS_IN_PROGRESS,
    SUPERVISOR_CYCLE_RESULT_FAILED,
    SUPERVISOR_CYCLE_RESULT_NO_WORK,
    SUPERVISOR_CYCLE_RESULT_SUCCESS,
    advance_pipeline_run,
    ensure_role_targeted_pipeline_run,
    escalate_agent_incident,
    get_pipeline_run,
    list_expert_review_packets_for_run,
    resume_agent,
    run_supervisor_cycle,
)
from tests.support import create_minimal_project, seed_pending_review_tailoring_run


def bootstrap_project(tmp_path: Path) -> Path:
    project_root = tmp_path / "repo"
    project_root.mkdir()
    create_minimal_project(project_root)
    run_bootstrap(project_root=project_root)
    return project_root


def connect_database(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    return connection


def seed_role_targeted_posting(
    connection: sqlite3.Connection,
    *,
    lead_id: str = "ld_downstream",
    job_posting_id: str = "jp_downstream",
    lead_identity_key: str = "acme|platform-engineer",
    posting_identity_key: str = "acme|platform-engineer|remote",
    company_name: str = "Acme",
    role_title: str = "Platform Engineer",
    timestamp: str = "2026-04-08T00:00:00Z",
) -> tuple[str, str]:
    connection.execute(
        """
        INSERT INTO linkedin_leads (
          lead_id, lead_identity_key, lead_status, lead_shape, split_review_status,
          source_type, source_reference, source_mode, company_name, role_title,
          created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            lead_id,
            lead_identity_key,
            "reviewed",
            "posting_plus_contacts",
            "confident",
            "manual_paste",
            "paste/paste.txt",
            "manual_paste",
            company_name,
            role_title,
            timestamp,
            timestamp,
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
            job_posting_id,
            lead_id,
            posting_identity_key,
            company_name,
            role_title,
            "resume_review_pending",
            timestamp,
            timestamp,
        ),
    )
    connection.commit()
    return lead_id, job_posting_id


def seed_general_learning_contact(
    connection: sqlite3.Connection,
    *,
    timestamp: str = "2026-04-08T00:00:00Z",
) -> str:
    connection.execute(
        """
        INSERT INTO contacts (
          contact_id, identity_key, display_name, company_name, origin_component,
          contact_status, full_name, first_name, last_name, current_working_email,
          created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "ct_general_learning",
            "acme|sam-learner",
            "Sam Learner",
            "Acme",
            "manual_capture",
            "identified",
            "Sam Learner",
            "Sam",
            "Learner",
            "sam.learner@acme.example",
            timestamp,
            timestamp,
        ),
    )
    connection.commit()
    return "ct_general_learning"


def test_lead_handoff_advances_the_durable_run_into_agent_review(tmp_path: Path) -> None:
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    lead_id, job_posting_id = seed_role_targeted_posting(connection)
    seed_pending_review_tailoring_run(
        connection,
        paths,
        job_posting_id=job_posting_id,
        company_name="Acme",
        role_title="Platform Engineer",
    )
    resume_agent(
        connection,
        manual_command="jhc-agent-start",
        timestamp="2026-04-08T00:05:00Z",
    )
    pipeline_run, _ = ensure_role_targeted_pipeline_run(
        connection,
        lead_id=lead_id,
        job_posting_id=job_posting_id,
        current_stage="lead_handoff",
        started_at="2026-04-08T00:06:00Z",
    )

    execution = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-04-08T00:07:00Z",
    )
    updated_run = get_pipeline_run(connection, pipeline_run.pipeline_run_id)
    connection.close()

    assert execution.cycle.result == SUPERVISOR_CYCLE_RESULT_SUCCESS
    assert execution.selected_work is not None
    assert execution.selected_work.work_type == "pipeline_run"
    assert execution.selected_work.action_id == "checkpoint_pipeline_run"
    assert execution.selected_work.current_stage == "lead_handoff"
    assert updated_run is not None
    assert updated_run.pipeline_run_id == pipeline_run.pipeline_run_id
    assert updated_run.run_status == RUN_STATUS_IN_PROGRESS
    assert updated_run.current_stage == "agent_review"


def test_agent_review_stage_advances_to_people_search_after_approval(tmp_path: Path) -> None:
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    lead_id, job_posting_id = seed_role_targeted_posting(connection)
    seed_pending_review_tailoring_run(
        connection,
        paths,
        job_posting_id=job_posting_id,
        company_name="Acme",
        role_title="Platform Engineer",
    )
    resume_agent(
        connection,
        manual_command="jhc-agent-start",
        timestamp="2026-04-08T00:08:00Z",
    )
    pipeline_run, _ = ensure_role_targeted_pipeline_run(
        connection,
        lead_id=lead_id,
        job_posting_id=job_posting_id,
        current_stage="agent_review",
        started_at="2026-04-08T00:09:00Z",
    )

    execution = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-04-08T00:10:00Z",
    )
    updated_run = get_pipeline_run(connection, pipeline_run.pipeline_run_id)
    posting_row = connection.execute(
        """
        SELECT posting_status
        FROM job_postings
        WHERE job_posting_id = ?
        """,
        (job_posting_id,),
    ).fetchone()
    tailoring_row = connection.execute(
        """
        SELECT resume_review_status
        FROM resume_tailoring_runs
        WHERE job_posting_id = ?
        ORDER BY COALESCE(completed_at, updated_at, created_at, started_at) DESC,
                 resume_tailoring_run_id DESC
        LIMIT 1
        """,
        (job_posting_id,),
    ).fetchone()
    review_artifact_count = connection.execute(
        """
        SELECT COUNT(*)
        FROM artifact_records
        WHERE job_posting_id = ?
          AND artifact_type = 'tailoring_review_decision'
        """,
        (job_posting_id,),
    ).fetchone()[0]
    connection.close()

    assert execution.cycle.result == SUPERVISOR_CYCLE_RESULT_SUCCESS
    assert execution.selected_work is not None
    assert execution.selected_work.work_id == pipeline_run.pipeline_run_id
    assert execution.selected_work.action_id == ACTION_PERFORM_MANDATORY_AGENT_REVIEW
    assert execution.selected_work.current_stage == "agent_review"
    assert execution.incident is None
    assert execution.review_packet is None
    assert updated_run is not None
    assert updated_run.run_status == RUN_STATUS_IN_PROGRESS
    assert updated_run.current_stage == "people_search"
    assert posting_row is not None
    assert posting_row["posting_status"] == "requires_contacts"
    assert tailoring_row is not None
    assert tailoring_row["resume_review_status"] == "approved"
    assert review_artifact_count == 1


def test_existing_pipeline_run_is_selected_before_bootstrapping_another_eligible_posting(
    tmp_path: Path,
) -> None:
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    lead_id, job_posting_id = seed_role_targeted_posting(connection)
    _, waiting_job_posting_id = seed_role_targeted_posting(
        connection,
        lead_id="ld_waiting",
        job_posting_id="jp_waiting",
        lead_identity_key="beta|data-engineer",
        posting_identity_key="beta|data-engineer|remote",
        company_name="Beta Systems",
        role_title="Data Engineer",
        timestamp="2026-04-08T00:01:00Z",
    )
    resume_agent(
        connection,
        manual_command="jhc-agent-start",
        timestamp="2026-04-08T00:05:00Z",
    )
    pipeline_run, _ = ensure_role_targeted_pipeline_run(
        connection,
        lead_id=lead_id,
        job_posting_id=job_posting_id,
        current_stage="lead_handoff",
        started_at="2026-04-08T00:06:00Z",
    )

    execution = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-04-08T00:07:00Z",
    )
    stored_runs = connection.execute(
        """
        SELECT pipeline_run_id, job_posting_id, current_stage
        FROM pipeline_runs
        ORDER BY started_at
        """
    ).fetchall()
    waiting_run_count = connection.execute(
        """
        SELECT COUNT(*)
        FROM pipeline_runs
        WHERE job_posting_id = ?
        """,
        (waiting_job_posting_id,),
    ).fetchone()[0]
    connection.close()

    assert execution.cycle.result == SUPERVISOR_CYCLE_RESULT_SUCCESS
    assert execution.selected_work is not None
    assert execution.selected_work.work_type == "pipeline_run"
    assert execution.selected_work.work_id == pipeline_run.pipeline_run_id
    assert execution.selected_work.action_id == "checkpoint_pipeline_run"
    assert execution.pipeline_run is not None
    assert execution.pipeline_run.pipeline_run_id == pipeline_run.pipeline_run_id
    assert execution.pipeline_run.job_posting_id == job_posting_id
    assert waiting_run_count == 0
    assert [dict(row) for row in stored_runs] == [
        {
            "pipeline_run_id": pipeline_run.pipeline_run_id,
            "job_posting_id": job_posting_id,
            "current_stage": "agent_review",
        }
    ]


def test_contact_rooted_general_learning_work_is_not_selected_yet(tmp_path: Path) -> None:
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    contact_id = seed_general_learning_contact(connection)
    resume_agent(
        connection,
        manual_command="jhc-agent-start",
        timestamp="2026-04-08T00:05:00Z",
    )

    execution = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-04-08T00:06:00Z",
    )
    pipeline_run_count = connection.execute(
        "SELECT COUNT(*) FROM pipeline_runs"
    ).fetchone()[0]
    contact_row = connection.execute(
        """
        SELECT contact_id, current_working_email
        FROM contacts
        WHERE contact_id = ?
        """,
        (contact_id,),
    ).fetchone()
    connection.close()

    assert execution.cycle.result == SUPERVISOR_CYCLE_RESULT_NO_WORK
    assert execution.selected_work is None
    assert execution.pipeline_run is None
    assert execution.incident is None
    assert execution.review_packet is None
    assert execution.cycle.error_summary == "no bounded supervisor work unit is currently due"
    assert pipeline_run_count == 0
    assert contact_row is not None
    assert contact_row["contact_id"] == contact_id
    assert contact_row["current_working_email"] == "sam.learner@acme.example"


@pytest.mark.parametrize(
    "blocked_stage",
    [
        "people_search",
        "email_discovery",
        "sending",
        "delivery_feedback",
    ],
)
def test_downstream_stage_without_registered_action_escalates_with_review_packet(
    tmp_path: Path,
    blocked_stage: str,
) -> None:
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    lead_id, job_posting_id = seed_role_targeted_posting(connection)
    resume_agent(
        connection,
        manual_command="jhc-agent-start",
        timestamp="2026-04-08T00:10:00Z",
    )
    pipeline_run, _ = ensure_role_targeted_pipeline_run(
        connection,
        lead_id=lead_id,
        job_posting_id=job_posting_id,
        current_stage=blocked_stage,
        started_at="2026-04-08T00:11:00Z",
    )

    execution = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-04-08T00:12:00Z",
    )
    updated_run = get_pipeline_run(connection, pipeline_run.pipeline_run_id)
    stored_packets = list_expert_review_packets_for_run(connection, pipeline_run.pipeline_run_id)
    snapshot = json.loads((project_root / execution.context_snapshot_path).read_text(encoding="utf-8"))
    connection.close()

    assert execution.cycle.result == SUPERVISOR_CYCLE_RESULT_FAILED
    assert execution.selected_work is not None
    assert execution.selected_work.work_id == pipeline_run.pipeline_run_id
    assert execution.selected_work.action_id is None
    assert execution.selected_work.current_stage == blocked_stage
    assert execution.incident is not None
    assert execution.incident.incident_type == "unsupported_supervisor_action"
    assert execution.review_packet is not None
    assert execution.review_packet.packet_status == REVIEW_PACKET_STATUS_PENDING
    assert updated_run is not None
    assert updated_run.run_status == RUN_STATUS_ESCALATED
    assert updated_run.current_stage == blocked_stage
    assert updated_run.review_packet_status == REVIEW_PACKET_STATUS_PENDING
    assert updated_run.last_error_summary == (
        f"No registered bounded supervisor action covers pipeline stage "
        f"'{blocked_stage}' yet."
    )
    assert stored_packets == [execution.review_packet]
    assert snapshot["selected_work"]["current_stage"] == blocked_stage
    assert snapshot["pipeline_run"]["current_stage"] == blocked_stage
    assert snapshot["review_packet"]["packet_path"] == execution.review_packet.packet_path


def test_retry_after_downstream_stage_blocker_reuses_same_run_and_review_packet(
    tmp_path: Path,
) -> None:
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    lead_id, job_posting_id = seed_role_targeted_posting(connection)
    seed_pending_review_tailoring_run(
        connection,
        paths,
        job_posting_id=job_posting_id,
        company_name="Acme",
        role_title="Platform Engineer",
    )
    resume_agent(
        connection,
        manual_command="jhc-agent-start",
        timestamp="2026-04-08T00:20:00Z",
    )
    pipeline_run, _ = ensure_role_targeted_pipeline_run(
        connection,
        lead_id=lead_id,
        job_posting_id=job_posting_id,
        current_stage="agent_review",
        started_at="2026-04-08T00:21:00Z",
    )

    first_execution = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-04-08T00:22:00Z",
    )
    assert first_execution.cycle.result == SUPERVISOR_CYCLE_RESULT_SUCCESS
    assert first_execution.pipeline_run is not None
    assert first_execution.pipeline_run.current_stage == "people_search"

    second_execution = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-04-08T00:23:00Z",
    )
    assert second_execution.incident is not None
    assert second_execution.review_packet is not None

    escalated_incident = escalate_agent_incident(
        connection,
        second_execution.incident.agent_incident_id,
        escalation_reason=(
            "Expert confirmed the downstream supervisor gap and recorded it for later "
            "catalog work."
        ),
        timestamp="2026-04-08T00:24:00Z",
    )
    retried_run = advance_pipeline_run(
        connection,
        pipeline_run.pipeline_run_id,
        current_stage="people_search",
        run_summary="Retry the same downstream boundary without restarting the run.",
        timestamp="2026-04-08T00:25:00Z",
    )
    reused_run, created = ensure_role_targeted_pipeline_run(
        connection,
        lead_id=lead_id,
        job_posting_id=job_posting_id,
        current_stage="lead_handoff",
        started_at="2026-04-08T00:26:00Z",
    )

    third_execution = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-04-08T00:27:00Z",
    )
    stored_packets = list_expert_review_packets_for_run(connection, pipeline_run.pipeline_run_id)
    connection.close()

    assert first_execution.pipeline_run is not None
    assert first_execution.pipeline_run.pipeline_run_id == pipeline_run.pipeline_run_id
    assert escalated_incident.status == "escalated"
    assert retried_run.pipeline_run_id == pipeline_run.pipeline_run_id
    assert retried_run.run_status == RUN_STATUS_IN_PROGRESS
    assert retried_run.current_stage == "people_search"
    assert created is False
    assert reused_run.pipeline_run_id == pipeline_run.pipeline_run_id
    assert reused_run.current_stage == "people_search"
    assert third_execution.cycle.result == SUPERVISOR_CYCLE_RESULT_FAILED
    assert third_execution.selected_work is not None
    assert third_execution.selected_work.work_id == pipeline_run.pipeline_run_id
    assert third_execution.selected_work.current_stage == "people_search"
    assert third_execution.review_packet is not None
    assert third_execution.review_packet.expert_review_packet_id == (
        second_execution.review_packet.expert_review_packet_id
    )
    assert len(stored_packets) == 1
