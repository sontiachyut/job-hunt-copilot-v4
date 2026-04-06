from __future__ import annotations

import sqlite3

import pytest

from job_hunt_copilot.bootstrap import run_bootstrap
from job_hunt_copilot.supervisor import (
    AGENT_MODE_PAUSED,
    AGENT_MODE_REPLANNING,
    AGENT_MODE_RUNNING,
    AGENT_MODE_STOPPED,
    REVIEW_PACKET_STATUS_NOT_READY,
    REVIEW_PACKET_STATUS_PENDING,
    REVIEW_PACKET_STATUS_REVIEWED,
    RUN_STATUS_COMPLETED,
    RUN_STATUS_ESCALATED,
    RUN_STATUS_IN_PROGRESS,
    RUN_STATUS_PAUSED,
    SUPERVISOR_CYCLE_RESULT_DEFERRED,
    SUPERVISOR_CYCLE_RESULT_SUCCESS,
    SUPERVISOR_LEASE_NAME,
    DuplicateActivePipelineRun,
    InvalidLifecycleTransition,
    acquire_runtime_lease,
    advance_pipeline_run,
    assign_supervisor_cycle_work_unit,
    begin_replanning,
    complete_pipeline_run,
    escalate_pipeline_run,
    ensure_role_targeted_pipeline_run,
    finish_supervisor_cycle,
    get_open_pipeline_run_for_posting,
    get_runtime_lease,
    pause_agent,
    pause_pipeline_run,
    read_agent_control_state,
    release_runtime_lease,
    resume_agent,
    set_pipeline_run_review_packet_status,
    start_supervisor_cycle,
    stop_agent,
)
from tests.support import create_minimal_project


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


def seed_role_targeted_posting(
    connection: sqlite3.Connection,
    *,
    timestamp: str = "2026-04-05T23:00:00Z",
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
            "ld_test",
            "guidewire|staff-software-engineer",
            "reviewed",
            "posting_plus_contacts",
            "confident",
            "manual_paste",
            "paste/paste.txt",
            "manual_paste",
            "Guidewire",
            "Staff Software Engineer",
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
            "jp_test",
            "ld_test",
            "guidewire|staff-software-engineer|remote",
            "Guidewire",
            "Staff Software Engineer",
            "resume_review_pending",
            timestamp,
            timestamp,
        ),
    )
    connection.commit()
    return "ld_test", "jp_test"


def test_control_state_helpers_persist_running_pause_stop_and_replanning_modes(tmp_path):
    project_root = bootstrap_project(tmp_path)
    connection = connect_database(project_root / "job_hunt_copilot.db")

    initial = read_agent_control_state(connection, timestamp="2026-04-05T23:10:00Z")
    running = resume_agent(
        connection,
        manual_command="jhc-agent-start",
        timestamp="2026-04-05T23:11:00Z",
    )
    paused = pause_agent(
        connection,
        reason="critical_incident_send_safety",
        manual_command="pause",
        timestamp="2026-04-05T23:12:00Z",
    )
    replanning = begin_replanning(
        connection,
        reason="daily_replan_due",
        manual_command="replan",
        timestamp="2026-04-05T23:13:00Z",
    )
    stopped = stop_agent(
        connection,
        manual_command="jhc-agent-stop",
        timestamp="2026-04-05T23:14:00Z",
    )
    persisted_rows = connection.execute(
        """
        SELECT control_key, control_value
        FROM agent_control_state
        WHERE control_key IN ('agent_enabled', 'agent_mode', 'pause_reason', 'paused_at', 'last_manual_command', 'last_replan_at', 'last_replan_reason')
        ORDER BY control_key
        """
    ).fetchall()
    connection.close()

    assert initial.agent_enabled is False
    assert initial.agent_mode == AGENT_MODE_STOPPED

    assert running.agent_enabled is True
    assert running.agent_mode == AGENT_MODE_RUNNING
    assert running.last_manual_command == "jhc-agent-start"
    assert running.pause_reason is None

    assert paused.agent_enabled is True
    assert paused.agent_mode == AGENT_MODE_PAUSED
    assert paused.pause_reason == "critical_incident_send_safety"
    assert paused.paused_at == "2026-04-05T23:12:00Z"

    assert replanning.agent_enabled is True
    assert replanning.agent_mode == AGENT_MODE_REPLANNING
    assert replanning.last_replan_at == "2026-04-05T23:13:00Z"
    assert replanning.last_replan_reason == "daily_replan_due"
    assert replanning.pause_reason is None

    assert stopped.agent_enabled is False
    assert stopped.agent_mode == AGENT_MODE_STOPPED
    assert stopped.last_manual_command == "jhc-agent-stop"
    assert stopped.pause_reason is None

    assert dict(persisted_rows) == {
        "agent_enabled": "false",
        "agent_mode": "stopped",
        "last_manual_command": "jhc-agent-stop",
        "last_replan_at": "2026-04-05T23:13:00Z",
        "last_replan_reason": "daily_replan_due",
        "pause_reason": "",
        "paused_at": "",
    }


def test_pipeline_run_helpers_reuse_non_terminal_runs_and_create_new_history_after_terminal_outcomes(
    tmp_path,
):
    project_root = bootstrap_project(tmp_path)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    lead_id, job_posting_id = seed_role_targeted_posting(connection)

    first_run, created_first = ensure_role_targeted_pipeline_run(
        connection,
        lead_id=lead_id,
        job_posting_id=job_posting_id,
        current_stage="lead_handoff",
        started_at="2026-04-05T23:20:00Z",
        run_summary="Lead accepted for autonomous role-targeted execution",
    )
    resumed_run, created_second = ensure_role_targeted_pipeline_run(
        connection,
        lead_id=lead_id,
        job_posting_id=job_posting_id,
        current_stage="ignored_because_existing_run_is_resumed",
        started_at="2026-04-05T23:21:00Z",
    )
    paused_run = pause_pipeline_run(
        connection,
        first_run.pipeline_run_id,
        current_stage="agent_review",
        error_summary="waiting_for_auto_pause_clearance",
        timestamp="2026-04-05T23:22:00Z",
    )
    resumed_after_pause = advance_pipeline_run(
        connection,
        first_run.pipeline_run_id,
        current_stage="people_search",
        run_summary="Auto-pause cleared; resuming pipeline",
        timestamp="2026-04-05T23:23:00Z",
    )
    completed_run = complete_pipeline_run(
        connection,
        first_run.pipeline_run_id,
        run_summary="Reached current end-to-end boundary",
        timestamp="2026-04-05T23:24:00Z",
    )
    pending_review_run = set_pipeline_run_review_packet_status(
        connection,
        first_run.pipeline_run_id,
        REVIEW_PACKET_STATUS_PENDING,
        timestamp="2026-04-05T23:24:30Z",
    )
    reviewed_run = set_pipeline_run_review_packet_status(
        connection,
        first_run.pipeline_run_id,
        REVIEW_PACKET_STATUS_REVIEWED,
        timestamp="2026-04-05T23:25:00Z",
    )
    second_run, created_third = ensure_role_targeted_pipeline_run(
        connection,
        lead_id=lead_id,
        job_posting_id=job_posting_id,
        current_stage="lead_handoff",
        started_at="2026-04-05T23:26:00Z",
    )

    with pytest.raises(InvalidLifecycleTransition):
        advance_pipeline_run(
            connection,
            first_run.pipeline_run_id,
            current_stage="sending",
            timestamp="2026-04-05T23:26:30Z",
        )

    open_run = get_open_pipeline_run_for_posting(connection, job_posting_id)
    stored_runs = connection.execute(
        """
        SELECT pipeline_run_id, run_status, review_packet_status, completed_at
        FROM pipeline_runs
        WHERE job_posting_id = ?
        ORDER BY started_at
        """,
        (job_posting_id,),
    ).fetchall()
    connection.close()

    assert created_first is True
    assert created_second is False
    assert created_third is True

    assert first_run.run_status == RUN_STATUS_IN_PROGRESS
    assert first_run.review_packet_status == REVIEW_PACKET_STATUS_NOT_READY
    assert resumed_run.pipeline_run_id == first_run.pipeline_run_id

    assert paused_run.run_status == RUN_STATUS_PAUSED
    assert paused_run.current_stage == "agent_review"
    assert paused_run.last_error_summary == "waiting_for_auto_pause_clearance"

    assert resumed_after_pause.run_status == RUN_STATUS_IN_PROGRESS
    assert resumed_after_pause.current_stage == "people_search"
    assert resumed_after_pause.completed_at is None

    assert completed_run.run_status == RUN_STATUS_COMPLETED
    assert completed_run.completed_at == "2026-04-05T23:24:00Z"
    assert pending_review_run.review_packet_status == REVIEW_PACKET_STATUS_PENDING
    assert reviewed_run.review_packet_status == REVIEW_PACKET_STATUS_REVIEWED

    assert second_run.pipeline_run_id != first_run.pipeline_run_id
    assert second_run.run_status == RUN_STATUS_IN_PROGRESS
    assert open_run is not None
    assert open_run.pipeline_run_id == second_run.pipeline_run_id

    assert [dict(row) for row in stored_runs] == [
        {
            "pipeline_run_id": first_run.pipeline_run_id,
            "run_status": "completed",
            "review_packet_status": "reviewed",
            "completed_at": "2026-04-05T23:24:00Z",
        },
        {
            "pipeline_run_id": second_run.pipeline_run_id,
            "run_status": "in_progress",
            "review_packet_status": "not_ready",
            "completed_at": None,
        },
    ]


def test_open_pipeline_run_lookup_rejects_duplicate_non_terminal_rows(tmp_path):
    project_root = bootstrap_project(tmp_path)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    lead_id, job_posting_id = seed_role_targeted_posting(connection)

    ensure_role_targeted_pipeline_run(
        connection,
        lead_id=lead_id,
        job_posting_id=job_posting_id,
        current_stage="lead_handoff",
        pipeline_run_id="pr_first",
        started_at="2026-04-05T23:30:00Z",
    )
    connection.execute(
        """
        INSERT INTO pipeline_runs (
          pipeline_run_id, run_scope_type, run_status, current_stage, lead_id,
          job_posting_id, review_packet_status, started_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "pr_second",
            "role_targeted_posting",
            "paused",
            "agent_review",
            lead_id,
            job_posting_id,
            "not_ready",
            "2026-04-05T23:31:00Z",
            "2026-04-05T23:31:00Z",
            "2026-04-05T23:31:00Z",
        ),
    )
    connection.commit()

    with pytest.raises(DuplicateActivePipelineRun):
        get_open_pipeline_run_for_posting(connection, job_posting_id)

    connection.close()


def test_supervisor_cycles_and_runtime_leases_support_deferral_and_stale_recovery(tmp_path):
    project_root = bootstrap_project(tmp_path)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    lead_id, job_posting_id = seed_role_targeted_posting(connection)
    pipeline_run, _ = ensure_role_targeted_pipeline_run(
        connection,
        lead_id=lead_id,
        job_posting_id=job_posting_id,
        current_stage="lead_handoff",
        started_at="2026-04-05T23:40:00Z",
    )

    first_acquire = acquire_runtime_lease(
        connection,
        lease_name=SUPERVISOR_LEASE_NAME,
        lease_owner_id="cycle-a",
        ttl_seconds=300,
        now="2026-04-05T23:40:00Z",
        lease_note="heartbeat cycle A",
    )
    overlapping_attempt = acquire_runtime_lease(
        connection,
        lease_name=SUPERVISOR_LEASE_NAME,
        lease_owner_id="cycle-b",
        ttl_seconds=300,
        now="2026-04-05T23:42:00Z",
        lease_note="heartbeat cycle B",
    )
    reclaimed = acquire_runtime_lease(
        connection,
        lease_name=SUPERVISOR_LEASE_NAME,
        lease_owner_id="cycle-b",
        ttl_seconds=300,
        now="2026-04-05T23:46:00Z",
        lease_note="recovered stale lease",
    )

    deferred_cycle = start_supervisor_cycle(
        connection,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-04-05T23:42:00Z",
    )
    finished_deferred_cycle = finish_supervisor_cycle(
        connection,
        deferred_cycle.supervisor_cycle_id,
        result=SUPERVISOR_CYCLE_RESULT_DEFERRED,
        completed_at="2026-04-05T23:42:05Z",
        error_summary="lease still held by earlier heartbeat",
    )
    active_cycle = start_supervisor_cycle(
        connection,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-04-05T23:46:00Z",
    )
    selected_cycle = assign_supervisor_cycle_work_unit(
        connection,
        active_cycle.supervisor_cycle_id,
        selected_work_type="pipeline_run",
        selected_work_id=pipeline_run.pipeline_run_id,
        pipeline_run_id=pipeline_run.pipeline_run_id,
        context_snapshot_path="ops/agent/context-snapshots/sc_test/context_snapshot.json",
    )
    finished_active_cycle = finish_supervisor_cycle(
        connection,
        active_cycle.supervisor_cycle_id,
        result=SUPERVISOR_CYCLE_RESULT_SUCCESS,
        completed_at="2026-04-05T23:47:30Z",
    )
    released = release_runtime_lease(
        connection,
        lease_name=SUPERVISOR_LEASE_NAME,
        lease_owner_id="cycle-b",
    )
    final_lease = get_runtime_lease(connection, SUPERVISOR_LEASE_NAME)
    stored_cycles = connection.execute(
        """
        SELECT supervisor_cycle_id, selected_work_type, selected_work_id, pipeline_run_id, result, error_summary
        FROM supervisor_cycles
        ORDER BY started_at
        """
    ).fetchall()
    connection.close()

    assert first_acquire.status == "acquired"
    assert first_acquire.lease.lease_owner_id == "cycle-a"

    assert overlapping_attempt.deferred is True
    assert overlapping_attempt.lease.lease_owner_id == "cycle-a"
    assert overlapping_attempt.lease.expires_at == "2026-04-05T23:45:00Z"

    assert reclaimed.status == "reclaimed"
    assert reclaimed.lease.lease_owner_id == "cycle-b"
    assert reclaimed.lease.expires_at == "2026-04-05T23:51:00Z"

    assert deferred_cycle.result == "in_progress"
    assert finished_deferred_cycle.result == SUPERVISOR_CYCLE_RESULT_DEFERRED
    assert finished_deferred_cycle.error_summary == "lease still held by earlier heartbeat"

    assert selected_cycle.selected_work_type == "pipeline_run"
    assert selected_cycle.selected_work_id == pipeline_run.pipeline_run_id
    assert selected_cycle.context_snapshot_path == "ops/agent/context-snapshots/sc_test/context_snapshot.json"
    assert finished_active_cycle.result == SUPERVISOR_CYCLE_RESULT_SUCCESS

    assert released is True
    assert final_lease is None

    assert [dict(row) for row in stored_cycles] == [
        {
            "supervisor_cycle_id": deferred_cycle.supervisor_cycle_id,
            "selected_work_type": None,
            "selected_work_id": None,
            "pipeline_run_id": None,
            "result": "deferred",
            "error_summary": "lease still held by earlier heartbeat",
        },
        {
            "supervisor_cycle_id": active_cycle.supervisor_cycle_id,
            "selected_work_type": "pipeline_run",
            "selected_work_id": pipeline_run.pipeline_run_id,
            "pipeline_run_id": pipeline_run.pipeline_run_id,
            "result": "success",
            "error_summary": None,
        },
    ]


def test_escalated_pipeline_runs_can_resume_when_the_clearing_condition_is_persisted(tmp_path):
    project_root = bootstrap_project(tmp_path)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    lead_id, job_posting_id = seed_role_targeted_posting(connection)
    pipeline_run, _ = ensure_role_targeted_pipeline_run(
        connection,
        lead_id=lead_id,
        job_posting_id=job_posting_id,
        current_stage="agent_review",
        started_at="2026-04-05T23:48:00Z",
    )
    escalated = escalate_pipeline_run(
        connection,
        pipeline_run.pipeline_run_id,
        current_stage="agent_review",
        error_summary="expert clarification required",
        timestamp="2026-04-05T23:49:00Z",
    )
    resumed = advance_pipeline_run(
        connection,
        pipeline_run.pipeline_run_id,
        current_stage="people_search",
        run_summary="Expert cleared the escalation; resume the same durable run",
        timestamp="2026-04-05T23:50:00Z",
    )
    connection.close()

    assert escalated.run_status == RUN_STATUS_ESCALATED
    assert resumed.run_status == RUN_STATUS_IN_PROGRESS
    assert resumed.current_stage == "people_search"
    assert resumed.completed_at is None


def test_completed_runs_cannot_transition_back_to_pending_review_packet_generation(tmp_path):
    project_root = bootstrap_project(tmp_path)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    lead_id, job_posting_id = seed_role_targeted_posting(connection)
    pipeline_run, _ = ensure_role_targeted_pipeline_run(
        connection,
        lead_id=lead_id,
        job_posting_id=job_posting_id,
        current_stage="lead_handoff",
        started_at="2026-04-05T23:50:00Z",
    )
    completed = complete_pipeline_run(
        connection,
        pipeline_run.pipeline_run_id,
        timestamp="2026-04-05T23:51:00Z",
    )

    with pytest.raises(InvalidLifecycleTransition):
        pause_pipeline_run(
            connection,
            pipeline_run.pipeline_run_id,
            current_stage="agent_review",
            timestamp="2026-04-05T23:51:30Z",
        )

    connection.close()

    assert completed.run_status == RUN_STATUS_COMPLETED
