from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from job_hunt_copilot.bootstrap import run_bootstrap
from job_hunt_copilot.gmail_alerts import GmailAlertBatch
from job_hunt_copilot.maintenance import (
    MaintenanceDependencies,
    MaintenancePlan,
    MaintenanceValidationCommand,
)
from job_hunt_copilot.paths import ProjectPaths
from job_hunt_copilot.supervisor import (
    ACTION_RUN_DAILY_MAINTENANCE,
    AGENT_MODE_PAUSED,
    AGENT_MODE_REPLANNING,
    AGENT_MODE_RUNNING,
    AGENT_MODE_STOPPED,
    INCIDENT_SEVERITY_CRITICAL,
    INCIDENT_SEVERITY_MEDIUM,
    INCIDENT_STATUS_ESCALATED,
    REVIEW_PACKET_STATUS_NOT_READY,
    REVIEW_PACKET_STATUS_PENDING,
    REVIEW_PACKET_STATUS_REVIEWED,
    REVIEW_PACKET_STATUS_SUPERSEDED,
    RUN_STATUS_COMPLETED,
    RUN_STATUS_ESCALATED,
    RUN_STATUS_IN_PROGRESS,
    RUN_STATUS_PAUSED,
    SUPERVISOR_CYCLE_RESULT_AUTO_PAUSED,
    SUPERVISOR_CYCLE_RESULT_DEFERRED,
    SUPERVISOR_CYCLE_RESULT_FAILED,
    SUPERVISOR_CYCLE_RESULT_NO_WORK,
    SUPERVISOR_CYCLE_RESULT_SUCCESS,
    SUPERVISOR_LEASE_NAME,
    DuplicateActivePipelineRun,
    InvalidLifecycleTransition,
    acquire_runtime_lease,
    advance_pipeline_run,
    assign_supervisor_cycle_work_unit,
    begin_replanning,
    complete_pipeline_run,
    create_agent_incident,
    escalate_agent_incident,
    escalate_pipeline_run,
    ensure_role_targeted_pipeline_run,
    fail_pipeline_run,
    finalize_review_worthy_pipeline_run,
    finish_supervisor_cycle,
    generate_expert_review_packet,
    get_agent_incident,
    get_expert_review_decision,
    get_expert_review_packet,
    get_override_event,
    get_open_pipeline_run_for_posting,
    get_pipeline_run,
    get_runtime_lease,
    list_expert_review_decisions_for_packet,
    list_expert_review_packets_for_run,
    list_override_events_for_object,
    pause_agent,
    pause_pipeline_run,
    read_agent_control_state,
    record_expert_review_decision,
    record_expert_override_decision,
    release_runtime_lease,
    resume_agent,
    run_supervisor_cycle,
    select_next_supervisor_work_unit,
    set_pipeline_run_review_packet_status,
    start_supervisor_cycle,
    stop_agent,
    SupervisorActionDependencies,
    _select_open_pipeline_run_work_unit,
)
from tests.support import create_minimal_project, initialize_git_repository


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


def build_test_maintenance_dependencies(
    *,
    should_fail_full_system: bool = False,
) -> SupervisorActionDependencies:
    def apply_changes(worktree_path: Path) -> None:
        changed_path = worktree_path / "maintenance-check.txt"
        changed_path.write_text("maintenance checkpoint\n", encoding="utf-8")

    def run_validation(
        args: tuple[str, ...],
        cwd: Path,
    ) -> subprocess.CompletedProcess[str]:
        del cwd
        label = args[-1]
        if should_fail_full_system and label == "full-system-check":
            return subprocess.CompletedProcess(
                args=list(args),
                returncode=1,
                stdout="full-system validation failed\n",
                stderr="",
            )
        return subprocess.CompletedProcess(
            args=list(args),
            returncode=0,
            stdout=f"{label} passed\n",
            stderr="",
        )

    return SupervisorActionDependencies(
        local_timezone="UTC",
        maintenance_dependencies=MaintenanceDependencies(
            plan=MaintenancePlan(
                scope_slug="daily-healthcheck",
                short_reason="Record the bounded maintenance checkpoint for validation coverage.",
                notes="Supervisor regression test maintenance batch.",
                apply_changes=apply_changes,
                change_scoped_validation=(
                    MaintenanceValidationCommand(
                        label="change-scoped-check",
                        args=("mock-validation", "change-scoped-check"),
                    ),
                ),
                full_system_validation=(
                    MaintenanceValidationCommand(
                        label="full-system-check",
                        args=("mock-validation", "full-system-check"),
                    ),
                ),
            ),
            command_runner=run_validation,
        ),
    )


class FakeGmailAlertCollector:
    def __init__(self, *batches: GmailAlertBatch) -> None:
        self._pending_batches = list(batches)
        self._prepared_batches: dict[str, GmailAlertBatch] = {}
        self.prepare_calls: list[dict[str, str | None]] = []

    def prepare_batch(
        self,
        *,
        current_time: str,
        mailbox_history_checkpoint: str | None = None,
    ) -> GmailAlertBatch | None:
        self.prepare_calls.append(
            {
                "current_time": current_time,
                "mailbox_history_checkpoint": mailbox_history_checkpoint,
            }
        )
        if self._prepared_batches:
            return next(iter(self._prepared_batches.values()))
        if not self._pending_batches:
            return None
        batch = self._pending_batches.pop(0)
        self._prepared_batches[batch.ingestion_run_id] = batch
        return batch

    def peek_prepared_batch(self, ingestion_run_id: str) -> GmailAlertBatch | None:
        return self._prepared_batches.get(ingestion_run_id)

    def pop_prepared_batch(self, ingestion_run_id: str) -> GmailAlertBatch | None:
        return self._prepared_batches.pop(ingestion_run_id, None)


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


def seed_named_role_targeted_posting(
    connection: sqlite3.Connection,
    *,
    lead_id: str,
    job_posting_id: str,
    company_name: str,
    role_title: str,
    posting_status: str,
    timestamp: str,
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
            f"{company_name.lower()}|{role_title.lower()}",
            "reviewed",
            "posting_plus_contacts",
            "confident",
            "manual_paste",
            f"paste/{lead_id}.txt",
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
            f"{company_name.lower()}|{role_title.lower()}|{job_posting_id}",
            company_name,
            role_title,
            posting_status,
            timestamp,
            timestamp,
        ),
    )
    connection.commit()
    return lead_id, job_posting_id


def seed_tailoring_run(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    job_posting_id: str,
    tailoring_status: str,
    resume_review_status: str,
    verification_outcome: str,
    final_resume_path: str | None,
    timestamp: str,
) -> None:
    connection.execute(
        """
        INSERT INTO resume_tailoring_runs (
          resume_tailoring_run_id, job_posting_id, base_used, tailoring_status,
          resume_review_status, workspace_path, final_resume_path, verification_outcome,
          started_at, completed_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            job_posting_id,
            "generalist",
            tailoring_status,
            resume_review_status,
            f"resume-tailoring/output/{run_id}",
            final_resume_path,
            verification_outcome,
            timestamp,
            timestamp,
            timestamp,
            timestamp,
        ),
    )


def seed_send_ready_contact_with_generated_message(
    connection: sqlite3.Connection,
    *,
    contact_id: str,
    job_posting_contact_id: str,
    job_posting_id: str,
    company_name: str,
    display_name: str,
    recipient_email: str,
    created_at: str,
) -> None:
    connection.execute(
        """
        INSERT INTO contacts (
          contact_id, identity_key, display_name, company_name, origin_component, contact_status,
          full_name, current_working_email, position_title, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            contact_id,
            f"{company_name.lower()}|{display_name.lower().replace(' ', '-')}",
            display_name,
            company_name,
            "email_discovery",
            "working_email_found",
            display_name,
            recipient_email,
            "Engineering Manager",
            created_at,
            created_at,
        ),
    )
    connection.execute(
        """
        INSERT INTO job_posting_contacts (
          job_posting_contact_id, job_posting_id, contact_id, recipient_type, relevance_reason,
          link_level_status, is_in_intended_outreach_set, entered_intended_outreach_set_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job_posting_contact_id,
            job_posting_id,
            contact_id,
            "hiring_manager",
            "Selected for bounded supervisor sending coverage.",
            "outreach_in_progress",
            1,
            created_at,
            created_at,
            created_at,
        ),
    )
    connection.execute(
        """
        INSERT INTO outreach_messages (
          outreach_message_id, contact_id, outreach_mode, recipient_email, message_status,
          job_posting_id, job_posting_contact_id, subject, body_text, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            f"msg_{contact_id}",
            contact_id,
            "role_targeted",
            recipient_email,
            "generated",
            job_posting_id,
            job_posting_contact_id,
            f"Interest in the role at {company_name}",
            "Draft body",
            created_at,
            created_at,
        ),
    )
    connection.commit()


def seed_send_ready_contact_without_message(
    connection: sqlite3.Connection,
    *,
    contact_id: str,
    job_posting_contact_id: str,
    job_posting_id: str,
    company_name: str,
    display_name: str,
    recipient_email: str,
    created_at: str,
) -> None:
    connection.execute(
        """
        INSERT INTO contacts (
          contact_id, identity_key, display_name, company_name, origin_component, contact_status,
          full_name, current_working_email, position_title, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            contact_id,
            f"{company_name.lower()}|{display_name.lower().replace(' ', '-')}",
            display_name,
            company_name,
            "email_discovery",
            "working_email_found",
            display_name,
            recipient_email,
            "Recruiter",
            created_at,
            created_at,
        ),
    )
    connection.execute(
        """
        INSERT INTO job_posting_contacts (
          job_posting_contact_id, job_posting_id, contact_id, recipient_type, relevance_reason,
          link_level_status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job_posting_contact_id,
            job_posting_id,
            contact_id,
            "recruiter",
            "Selected for bounded supervisor sending coverage.",
            "shortlisted",
            created_at,
            created_at,
        ),
    )
    connection.commit()


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


def test_finalize_review_worthy_run_generates_packet_artifacts_and_registry_rows(tmp_path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    lead_id, job_posting_id = seed_role_targeted_posting(connection)
    pipeline_run, _ = ensure_role_targeted_pipeline_run(
        connection,
        lead_id=lead_id,
        job_posting_id=job_posting_id,
        current_stage="agent_review",
        started_at="2026-04-05T23:55:00Z",
    )
    create_agent_incident(
        connection,
        incident_type="manual_review_required",
        severity=INCIDENT_SEVERITY_MEDIUM,
        summary="Need expert confirmation before allowing outreach to proceed.",
        pipeline_run_id=pipeline_run.pipeline_run_id,
        lead_id=lead_id,
        job_posting_id=job_posting_id,
        repair_attempt_summary="Supervisor captured the ambiguity and stopped at the review boundary.",
        created_at="2026-04-05T23:56:00Z",
    )

    finalized_run, packet = finalize_review_worthy_pipeline_run(
        connection,
        paths,
        pipeline_run.pipeline_run_id,
        final_status=RUN_STATUS_COMPLETED,
        current_stage="completed",
        run_summary="Reached the current end-to-end role-targeted boundary.",
        timestamp="2026-04-05T23:57:00Z",
    )
    stored_packet = get_expert_review_packet(connection, packet.expert_review_packet_id)
    packet_history = list_expert_review_packets_for_run(connection, pipeline_run.pipeline_run_id)
    packet_json = json.loads(
        (project_root / packet.packet_path).read_text(encoding="utf-8")
    )
    packet_markdown = (project_root / packet.markdown_path).read_text(encoding="utf-8")
    artifact_rows = connection.execute(
        """
        SELECT artifact_type, file_path
        FROM artifact_records
        WHERE job_posting_id = ?
          AND file_path LIKE 'ops/review-packets/%'
        ORDER BY artifact_type
        """,
        (job_posting_id,),
    ).fetchall()
    connection.close()

    assert finalized_run.run_status == RUN_STATUS_COMPLETED
    assert finalized_run.review_packet_status == REVIEW_PACKET_STATUS_PENDING
    assert stored_packet is not None
    assert stored_packet.packet_status == REVIEW_PACKET_STATUS_PENDING
    assert packet_history == [stored_packet]
    assert packet_json["pipeline_run_id"] == pipeline_run.pipeline_run_id
    assert packet_json["job_posting_id"] == job_posting_id
    assert packet_json["run_outcome"] == "completed"
    assert packet_json["recommended_expert_actions"]
    assert packet_json["incidents"][0]["incident_type"] == "manual_review_required"
    assert packet_markdown.startswith("# Expert Review Packet")
    assert "Recommended Expert Actions" in packet_markdown
    assert [dict(row) for row in artifact_rows] == [
        {
            "artifact_type": "expert_review_packet_json",
            "file_path": packet.packet_path,
        },
        {
            "artifact_type": "expert_review_packet_markdown",
            "file_path": packet.markdown_path,
        },
    ]


def test_record_expert_override_decision_persists_lineage_and_marks_packet_reviewed(tmp_path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    lead_id, job_posting_id = seed_role_targeted_posting(connection)
    pipeline_run, _ = ensure_role_targeted_pipeline_run(
        connection,
        lead_id=lead_id,
        job_posting_id=job_posting_id,
        current_stage="agent_review",
        started_at="2026-04-06T00:40:00Z",
    )
    _, packet = finalize_review_worthy_pipeline_run(
        connection,
        paths,
        pipeline_run.pipeline_run_id,
        final_status=RUN_STATUS_ESCALATED,
        current_stage="agent_review",
        error_summary="expert clarification required before outreach proceeds",
        run_summary="Escalated after agent review requested an explicit owner decision.",
        timestamp="2026-04-06T00:41:00Z",
    )
    connection.execute(
        """
        UPDATE job_postings
        SET posting_status = ?, updated_at = ?
        WHERE job_posting_id = ?
        """,
        (
            "requires_contacts",
            "2026-04-06T00:42:00Z",
            job_posting_id,
        ),
    )
    connection.commit()

    decision, override_event = record_expert_override_decision(
        connection,
        packet.expert_review_packet_id,
        decision_type="override_posting_status",
        object_type="job_posting",
        object_id=job_posting_id,
        component_stage="resume_review",
        previous_value={
            "decision_context": {
                "source_packet_id": packet.expert_review_packet_id,
                "run_status": "escalated",
            },
            "posting_status": "resume_review_pending",
        },
        new_value={
            "decision_context": {
                "applied_from": "expert_override",
            },
            "posting_status": "requires_contacts",
        },
        override_reason="Owner approved moving this posting into contact discovery.",
        override_by="owner",
        lead_id=lead_id,
        job_posting_id=job_posting_id,
        decided_at="2026-04-06T00:42:30Z",
    )
    stored_packet = get_expert_review_packet(connection, packet.expert_review_packet_id)
    stored_run = get_pipeline_run(connection, pipeline_run.pipeline_run_id)
    stored_decision = get_expert_review_decision(connection, decision.expert_review_decision_id)
    stored_override = get_override_event(connection, override_event.override_event_id)
    packet_decisions = list_expert_review_decisions_for_packet(
        connection,
        packet.expert_review_packet_id,
    )
    override_history = list_override_events_for_object(
        connection,
        object_type="job_posting",
        object_id=job_posting_id,
    )
    connection.close()

    assert stored_packet is not None
    assert stored_packet.packet_status == REVIEW_PACKET_STATUS_REVIEWED
    assert stored_packet.reviewed_at == "2026-04-06T00:42:30Z"
    assert stored_run is not None
    assert stored_run.review_packet_status == REVIEW_PACKET_STATUS_REVIEWED
    assert stored_decision is not None
    assert stored_decision.override_event_id == override_event.override_event_id
    assert packet_decisions == [stored_decision]
    assert stored_override is not None
    assert stored_override.override_reason == "Owner approved moving this posting into contact discovery."
    assert stored_override.override_by == "owner"
    assert json.loads(stored_override.previous_value)["decision_context"]["source_packet_id"] == (
        packet.expert_review_packet_id
    )
    assert json.loads(stored_override.new_value)["posting_status"] == "requires_contacts"
    assert override_history == [stored_override]


def test_generate_expert_review_packet_reuses_existing_superseded_packet_history(tmp_path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    lead_id, job_posting_id = seed_role_targeted_posting(connection)
    pipeline_run, _ = ensure_role_targeted_pipeline_run(
        connection,
        lead_id=lead_id,
        job_posting_id=job_posting_id,
        current_stage="agent_review",
        started_at="2026-04-06T00:44:00Z",
    )
    finalized_run, packet = finalize_review_worthy_pipeline_run(
        connection,
        paths,
        pipeline_run.pipeline_run_id,
        final_status=RUN_STATUS_ESCALATED,
        current_stage="agent_review",
        error_summary="expert clarification required before outreach proceeds",
        run_summary="Escalated after agent review requested an explicit owner decision.",
        timestamp="2026-04-06T00:45:00Z",
    )
    record_expert_review_decision(
        connection,
        packet.expert_review_packet_id,
        decision_type="owner_acknowledged",
        decided_at="2026-04-06T00:46:00Z",
    )
    connection.execute(
        """
        UPDATE expert_review_packets
        SET packet_status = ?, reviewed_at = ?
        WHERE expert_review_packet_id = ?
        """,
        (
            REVIEW_PACKET_STATUS_SUPERSEDED,
            "2026-04-06T00:47:00Z",
            packet.expert_review_packet_id,
        ),
    )
    connection.commit()
    superseded_run = set_pipeline_run_review_packet_status(
        connection,
        finalized_run.pipeline_run_id,
        REVIEW_PACKET_STATUS_SUPERSEDED,
        timestamp="2026-04-06T00:47:00Z",
    )

    reused_packet = generate_expert_review_packet(
        connection,
        paths,
        finalized_run.pipeline_run_id,
        created_at="2026-04-06T00:48:00Z",
    )
    packet_history = list_expert_review_packets_for_run(connection, finalized_run.pipeline_run_id)
    connection.close()

    assert superseded_run.review_packet_status == REVIEW_PACKET_STATUS_SUPERSEDED
    assert reused_packet.expert_review_packet_id == packet.expert_review_packet_id
    assert reused_packet.packet_status == REVIEW_PACKET_STATUS_SUPERSEDED
    assert len(packet_history) == 1


def test_run_supervisor_cycle_bootstraps_new_posting_run_and_persists_snapshot(tmp_path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    _, job_posting_id = seed_role_targeted_posting(connection)
    resume_agent(
        connection,
        manual_command="jhc-agent-start",
        timestamp="2026-04-06T00:00:00Z",
    )

    execution = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-04-06T00:01:00Z",
    )
    stored_runs = connection.execute(
        """
        SELECT pipeline_run_id, run_status, current_stage, run_summary
        FROM pipeline_runs
        WHERE job_posting_id = ?
        ORDER BY started_at
        """,
        (job_posting_id,),
    ).fetchall()
    final_lease = get_runtime_lease(connection, SUPERVISOR_LEASE_NAME)
    snapshot = json.loads((project_root / execution.context_snapshot_path).read_text(encoding="utf-8"))
    connection.close()

    assert execution.cycle.result == SUPERVISOR_CYCLE_RESULT_SUCCESS
    assert execution.selected_work is not None
    assert execution.selected_work.work_type == "job_posting"
    assert execution.selected_work.work_id == job_posting_id
    assert execution.pipeline_run is not None
    assert execution.pipeline_run.job_posting_id == job_posting_id
    assert execution.pipeline_run.current_stage == "lead_handoff"
    assert execution.pipeline_run.run_status == RUN_STATUS_IN_PROGRESS
    assert len(stored_runs) == 1
    assert stored_runs[0]["run_summary"] == (
        "Supervisor bootstrapped a durable role-targeted run from posting state."
    )
    assert snapshot["selected_work"]["work_type"] == "job_posting"
    assert snapshot["pipeline_run"]["pipeline_run_id"] == execution.pipeline_run.pipeline_run_id
    assert snapshot["control_state"]["agent_mode"] == "running"
    assert final_lease is None


def test_select_next_supervisor_work_unit_prefers_generated_send_frontier_over_draft_generation(
    tmp_path,
):
    project_root = bootstrap_project(tmp_path)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    resume_agent(
        connection,
        manual_command="jhc-agent-start",
        timestamp="2026-04-06T00:00:00Z",
    )

    seed_named_role_targeted_posting(
        connection,
        lead_id="ld_generated",
        job_posting_id="jp_generated",
        company_name="Generated Co",
        role_title="Backend Engineer",
        posting_status="ready_for_outreach",
        timestamp="2026-04-06T00:01:00Z",
    )
    generated_run, _ = ensure_role_targeted_pipeline_run(
        connection,
        lead_id="ld_generated",
        job_posting_id="jp_generated",
        current_stage="sending",
        started_at="2026-04-06T00:02:00Z",
    )
    seed_send_ready_contact_with_generated_message(
        connection,
        contact_id="ct_generated",
        job_posting_contact_id="jpc_generated",
        job_posting_id="jp_generated",
        company_name="Generated Co",
        display_name="Jordan Manager",
        recipient_email="jordan@generated.example",
        created_at="2026-04-06T00:03:00Z",
    )

    seed_named_role_targeted_posting(
        connection,
        lead_id="ld_draft_only",
        job_posting_id="jp_draft_only",
        company_name="Draft Only Co",
        role_title="Data Engineer",
        posting_status="ready_for_outreach",
        timestamp="2026-04-06T00:04:00Z",
    )
    ensure_role_targeted_pipeline_run(
        connection,
        lead_id="ld_draft_only",
        job_posting_id="jp_draft_only",
        current_stage="sending",
        started_at="2026-04-06T00:05:00Z",
    )
    seed_send_ready_contact_without_message(
        connection,
        contact_id="ct_draft_only",
        job_posting_contact_id="jpc_draft_only",
        job_posting_id="jp_draft_only",
        company_name="Draft Only Co",
        display_name="Riley Recruiter",
        recipient_email="riley@draftonly.example",
        created_at="2026-04-06T00:06:00Z",
    )

    selected_work = select_next_supervisor_work_unit(
        connection,
        project_root=project_root,
        current_time="2026-04-06T00:07:00Z",
        action_dependencies=SupervisorActionDependencies(
            local_timezone="UTC",
        ),
    )
    connection.close()

    assert selected_work is not None
    assert selected_work.work_type == "pipeline_run"
    assert selected_work.action_id == "run_role_targeted_sending"
    assert selected_work.pipeline_run_id == generated_run.pipeline_run_id
    assert selected_work.job_posting_id == "jp_generated"
    assert "already-generated send frontier" in selected_work.summary


def test_select_next_supervisor_work_unit_prefers_draftable_send_ready_run_over_stale_reconciliation_and_discovery(
    tmp_path,
    monkeypatch,
):
    import job_hunt_copilot.supervisor as supervisor_module

    project_root = bootstrap_project(tmp_path)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    resume_agent(
        connection,
        manual_command="jhc-agent-start",
        timestamp="2026-04-06T00:00:00Z",
    )

    seed_named_role_targeted_posting(
        connection,
        lead_id="ld_draftable",
        job_posting_id="jp_draftable",
        company_name="Draftable Co",
        role_title="Platform Engineer",
        posting_status="ready_for_outreach",
        timestamp="2026-04-06T00:01:00Z",
    )
    draftable_run, _ = ensure_role_targeted_pipeline_run(
        connection,
        lead_id="ld_draftable",
        job_posting_id="jp_draftable",
        current_stage="sending",
        started_at="2026-04-06T00:02:00Z",
    )
    connection.execute(
        """
        INSERT INTO contacts (
          contact_id, identity_key, display_name, company_name, origin_component, contact_status,
          full_name, current_working_email, position_title, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "ct_draftable",
            "draftable co|jordan-manager",
            "Jordan Manager",
            "Draftable Co",
            "email_discovery",
            "working_email_found",
            "Jordan Manager",
            "jordan@draftable.example",
            "Engineering Manager",
            "2026-04-06T00:03:00Z",
            "2026-04-06T00:03:00Z",
        ),
    )
    connection.execute(
        """
        INSERT INTO job_posting_contacts (
          job_posting_contact_id, job_posting_id, contact_id, recipient_type, relevance_reason,
          link_level_status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "jpc_draftable",
            "jp_draftable",
            "ct_draftable",
            "hiring_manager",
            "Selected for draftable send-set priority coverage.",
            "shortlisted",
            "2026-04-06T00:03:00Z",
            "2026-04-06T00:03:00Z",
        ),
    )

    seed_named_role_targeted_posting(
        connection,
        lead_id="ld_stale",
        job_posting_id="jp_stale",
        company_name="Stale Co",
        role_title="Machine Learning Engineer",
        posting_status="outreach_in_progress",
        timestamp="2026-04-06T00:04:00Z",
    )
    ensure_role_targeted_pipeline_run(
        connection,
        lead_id="ld_stale",
        job_posting_id="jp_stale",
        current_stage="sending",
        started_at="2026-04-06T00:05:00Z",
    )
    monkeypatch.setattr(
        supervisor_module,
        "_classify_stale_role_targeted_sending_reconciliation",
        lambda *_args, job_posting_id, **_kwargs: (
            "completed" if job_posting_id == "jp_stale" else None
        ),
    )

    seed_named_role_targeted_posting(
        connection,
        lead_id="ld_discovery",
        job_posting_id="jp_discovery",
        company_name="Discovery Co",
        role_title="Backend Engineer",
        posting_status="requires_contacts",
        timestamp="2026-04-05T23:59:00Z",
    )
    ensure_role_targeted_pipeline_run(
        connection,
        lead_id="ld_discovery",
        job_posting_id="jp_discovery",
        current_stage="email_discovery",
        started_at="2026-04-05T23:59:30Z",
    )

    selected_work = select_next_supervisor_work_unit(
        connection,
        project_root=project_root,
        current_time="2026-04-06T00:08:00Z",
        action_dependencies=SupervisorActionDependencies(local_timezone="UTC"),
    )
    connection.close()

    assert selected_work is not None
    assert selected_work.work_type == "pipeline_run"
    assert selected_work.action_id == "run_role_targeted_sending"
    assert selected_work.pipeline_run_id == draftable_run.pipeline_run_id
    assert selected_work.job_posting_id == "jp_draftable"
    assert "drafted and sent" in selected_work.summary


def test_select_next_supervisor_work_unit_picks_stale_original_frontier_for_refresh(
    tmp_path,
):
    project_root = bootstrap_project(tmp_path)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    resume_agent(
        connection,
        manual_command="jhc-agent-start",
        timestamp="2026-04-06T00:00:00Z",
    )

    seed_named_role_targeted_posting(
        connection,
        lead_id="ld_stale_frontier",
        job_posting_id="jp_stale_frontier",
        company_name="Stale Frontier Co",
        role_title="AI Platform Engineer",
        posting_status="outreach_in_progress",
        timestamp="2026-04-05T00:00:00Z",
    )
    stale_run, _ = ensure_role_targeted_pipeline_run(
        connection,
        lead_id="ld_stale_frontier",
        job_posting_id="jp_stale_frontier",
        current_stage="sending",
        started_at="2026-04-05T00:01:00Z",
    )
    connection.execute(
        """
        INSERT INTO contacts (
          contact_id, identity_key, display_name, company_name, origin_component, contact_status,
          full_name, current_working_email, position_title, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "ct_stale_frontier",
            "stale frontier co|morgan-manager",
            "Morgan Manager",
            "Stale Frontier Co",
            "email_discovery",
            "outreach_in_progress",
            "Morgan Manager",
            "morgan@stalefrontier.example",
            "Engineering Manager",
            "2026-04-05T00:02:00Z",
            "2026-04-05T00:02:00Z",
        ),
    )
    connection.execute(
        """
        INSERT INTO job_posting_contacts (
          job_posting_contact_id, job_posting_id, contact_id, recipient_type, relevance_reason,
          link_level_status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "jpc_stale_frontier",
            "jp_stale_frontier",
            "ct_stale_frontier",
            "hiring_manager",
            "Selected for stale original frontier refresh coverage.",
            "outreach_in_progress",
            "2026-04-05T00:02:00Z",
            "2026-04-05T00:02:00Z",
        ),
    )
    connection.execute(
        """
        INSERT INTO outreach_messages (
          outreach_message_id, contact_id, outreach_mode, recipient_email, message_status,
          job_posting_id, job_posting_contact_id, subject, body_text, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "om_stale_frontier",
            "ct_stale_frontier",
            "role_targeted",
            "morgan@stalefrontier.example",
            "generated",
            "jp_stale_frontier",
            "jpc_stale_frontier",
            "Old subject",
            "Old body",
            "2026-04-05T00:03:00Z",
            "2026-04-05T00:03:00Z",
        ),
    )

    seed_named_role_targeted_posting(
        connection,
        lead_id="ld_discovery",
        job_posting_id="jp_discovery",
        company_name="Discovery Co",
        role_title="Backend Engineer",
        posting_status="requires_contacts",
        timestamp="2026-04-06T00:04:00Z",
    )
    ensure_role_targeted_pipeline_run(
        connection,
        lead_id="ld_discovery",
        job_posting_id="jp_discovery",
        current_stage="email_discovery",
        started_at="2026-04-06T00:05:00Z",
    )

    selected_work = select_next_supervisor_work_unit(
        connection,
        project_root=project_root,
        current_time="2026-04-06T06:10:00Z",
        action_dependencies=SupervisorActionDependencies(local_timezone="UTC"),
    )
    connection.close()

    assert selected_work is not None
    assert selected_work.work_type == "pipeline_run"
    assert selected_work.action_id == "run_role_targeted_sending"
    assert selected_work.pipeline_run_id == stale_run.pipeline_run_id
    assert selected_work.job_posting_id == "jp_stale_frontier"


def test_select_next_supervisor_work_unit_prefers_orphaned_existing_send_frontier_over_feedback_cleanup_and_discovery(
    tmp_path,
    monkeypatch,
):
    import job_hunt_copilot.supervisor as supervisor_module

    project_root = bootstrap_project(tmp_path)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    resume_agent(
        connection,
        manual_command="jhc-agent-start",
        timestamp="2026-04-06T00:00:00Z",
    )

    _, feedback_only_job_posting_id = seed_named_role_targeted_posting(
        connection,
        lead_id="ld_feedback_only",
        job_posting_id="jp_feedback_only",
        company_name="Completed Co",
        role_title="Platform Engineer",
        posting_status="completed",
        timestamp="2026-04-06T00:01:00Z",
    )
    _, orphaned_job_posting_id = seed_named_role_targeted_posting(
        connection,
        lead_id="ld_orphaned",
        job_posting_id="jp_orphaned",
        company_name="Recovered Co",
        role_title="Machine Learning Engineer",
        posting_status="outreach_in_progress",
        timestamp="2026-04-06T00:02:00Z",
    )
    monkeypatch.setattr(
        supervisor_module,
        "_classify_orphaned_send_stage_recovery",
        lambda *_args, job_posting_id, **_kwargs: (
            ("delivery_feedback", "feedback_only")
            if job_posting_id == feedback_only_job_posting_id
            else ("sending", "existing_frontier")
            if job_posting_id == orphaned_job_posting_id
            else None
        ),
    )

    _, discovery_job_posting_id = seed_named_role_targeted_posting(
        connection,
        lead_id="ld_discovery",
        job_posting_id="jp_discovery",
        company_name="Discovery Co",
        role_title="Backend Engineer",
        posting_status="requires_contacts",
        timestamp="2026-04-06T00:06:00Z",
    )
    discovery_run, _ = ensure_role_targeted_pipeline_run(
        connection,
        lead_id="ld_discovery",
        job_posting_id=discovery_job_posting_id,
        current_stage="email_discovery",
        started_at="2026-04-06T00:07:00Z",
    )

    selected_work = select_next_supervisor_work_unit(
        connection,
        project_root=project_root,
        current_time="2026-04-06T00:08:00Z",
        action_dependencies=SupervisorActionDependencies(local_timezone="UTC"),
    )
    connection.close()

    assert selected_work is not None
    assert selected_work.work_type == "job_posting"
    assert selected_work.action_id == "bootstrap_role_targeted_run"
    assert selected_work.work_id == orphaned_job_posting_id
    assert selected_work.job_posting_id == orphaned_job_posting_id
    assert selected_work.current_stage == "sending"
    assert selected_work.pipeline_run_id is None
    assert "before feedback-only cleanup or older discovery backlog" in selected_work.summary
    assert selected_work.work_id != feedback_only_job_posting_id
    assert selected_work.work_id != discovery_job_posting_id
    assert selected_work.work_id != discovery_run.pipeline_run_id


@pytest.mark.parametrize(
    ("discovery_stage", "patch_target"),
    (
        ("email_discovery", "is_role_targeted_email_discovery_actionable_now"),
        ("people_search", "is_role_targeted_people_search_actionable_now"),
    ),
)
def test_select_next_supervisor_work_unit_prefers_fresh_posting_bootstrap_over_ordinary_discovery_backlog(
    tmp_path,
    monkeypatch,
    discovery_stage,
    patch_target,
):
    import job_hunt_copilot.email_discovery as email_discovery_module

    project_root = bootstrap_project(tmp_path)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    resume_agent(
        connection,
        manual_command="jhc-agent-start",
        timestamp="2026-04-06T00:00:00Z",
    )

    seed_named_role_targeted_posting(
        connection,
        lead_id="ld_backlog",
        job_posting_id="jp_backlog",
        company_name="Backlog Co",
        role_title="Backend Engineer",
        posting_status="requires_contacts",
        timestamp="2026-04-05T23:58:00Z",
    )
    backlog_run, _ = ensure_role_targeted_pipeline_run(
        connection,
        lead_id="ld_backlog",
        job_posting_id="jp_backlog",
        current_stage=discovery_stage,
        started_at="2026-04-05T23:59:00Z",
    )
    monkeypatch.setattr(
        email_discovery_module,
        patch_target,
        lambda *args, **kwargs: True,
    )

    seed_named_role_targeted_posting(
        connection,
        lead_id="ld_fresh",
        job_posting_id="jp_fresh",
        company_name="Fresh Co",
        role_title="AI Engineer",
        posting_status="sourced",
        timestamp="2026-04-06T00:01:00Z",
    )

    selected_work = select_next_supervisor_work_unit(
        connection,
        project_root=project_root,
        current_time="2026-04-06T00:02:00Z",
        action_dependencies=SupervisorActionDependencies(local_timezone="UTC"),
    )
    connection.close()

    assert selected_work is not None
    assert selected_work.work_type == "job_posting"
    assert selected_work.action_id == "bootstrap_role_targeted_run"
    assert selected_work.work_id == "jp_fresh"
    assert selected_work.job_posting_id == "jp_fresh"
    assert selected_work.pipeline_run_id is None
    assert selected_work.work_id != backlog_run.pipeline_run_id
    assert "first durable role-targeted pipeline run" in selected_work.summary


def test_classify_orphaned_feedback_only_recovery_stops_after_completed_closure(
    tmp_path,
    monkeypatch,
):
    import job_hunt_copilot.outreach as outreach_module
    import job_hunt_copilot.supervisor as supervisor_module

    project_root = bootstrap_project(tmp_path)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    lead_id, job_posting_id = seed_named_role_targeted_posting(
        connection,
        lead_id="ld_feedback_only",
        job_posting_id="jp_feedback_only",
        company_name="Completed Co",
        role_title="Platform Engineer",
        posting_status="completed",
        timestamp="2026-04-06T00:01:00Z",
    )
    monkeypatch.setattr(
        outreach_module,
        "is_role_targeted_sending_actionable_now",
        lambda *args, **kwargs: False,
    )
    monkeypatch.setattr(
        outreach_module,
        "_load_role_targeted_send_posting_row",
        lambda *args, **kwargs: {"job_posting_id": job_posting_id},
    )
    monkeypatch.setattr(
        outreach_module,
        "_load_active_role_targeted_wave",
        lambda *args, **kwargs: (),
    )
    monkeypatch.setattr(
        outreach_module,
        "_find_next_send_frontier_message",
        lambda *args, **kwargs: (None, None),
    )
    monkeypatch.setattr(
        supervisor_module,
        "_list_posting_sent_outreach_message_ids",
        lambda *args, **kwargs: ["msg_sent"],
    )
    monkeypatch.setattr(
        supervisor_module,
        "_list_posting_sent_outreach_message_ids_without_terminal_feedback",
        lambda *args, **kwargs: [],
    )

    initial_recovery = supervisor_module._classify_orphaned_send_stage_recovery(
        connection,
        project_root=project_root,
        job_posting_id=job_posting_id,
        current_time="2026-04-06T00:02:00Z",
        local_timezone="UTC",
    )

    recovered_run, _ = ensure_role_targeted_pipeline_run(
        connection,
        lead_id=lead_id,
        job_posting_id=job_posting_id,
        current_stage="delivery_feedback",
        started_at="2026-04-06T00:03:00Z",
    )
    complete_pipeline_run(
        connection,
        recovered_run.pipeline_run_id,
        timestamp="2026-04-06T00:04:00Z",
    )

    post_closure_recovery = supervisor_module._classify_orphaned_send_stage_recovery(
        connection,
        project_root=project_root,
        job_posting_id=job_posting_id,
        current_time="2026-04-06T00:05:00Z",
        local_timezone="UTC",
    )
    connection.close()

    assert initial_recovery == ("delivery_feedback", "feedback_only")
    assert post_closure_recovery is None


def test_classify_orphaned_completed_posting_with_actionable_unsent_frontier_recovers_at_sending(
    tmp_path,
    monkeypatch,
):
    import job_hunt_copilot.outreach as outreach_module
    import job_hunt_copilot.supervisor as supervisor_module

    project_root = bootstrap_project(tmp_path)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    _, job_posting_id = seed_named_role_targeted_posting(
        connection,
        lead_id="ld_completed_unsent",
        job_posting_id="jp_completed_unsent",
        company_name="Completed Co",
        role_title="AI Engineer",
        posting_status="completed",
        timestamp="2026-04-06T00:01:00Z",
    )
    monkeypatch.setattr(
        outreach_module,
        "is_role_targeted_sending_actionable_now",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        outreach_module,
        "_load_role_targeted_send_posting_row",
        lambda *args, **kwargs: {"job_posting_id": job_posting_id},
    )
    monkeypatch.setattr(
        outreach_module,
        "_load_active_role_targeted_wave",
        lambda *args, **kwargs: (),
    )
    monkeypatch.setattr(
        outreach_module,
        "_find_next_send_frontier_message",
        lambda *args, **kwargs: (
            SimpleNamespace(message_status="generated"),
            None,
        ),
    )
    monkeypatch.setattr(
        supervisor_module,
        "_list_posting_sent_outreach_message_ids",
        lambda *args, **kwargs: [],
    )

    recovery = supervisor_module._classify_orphaned_send_stage_recovery(
        connection,
        project_root=project_root,
        job_posting_id=job_posting_id,
        current_time="2026-04-06T00:02:00Z",
        local_timezone="UTC",
    )
    connection.close()

    assert recovery == ("sending", "generated_frontier")


def test_run_supervisor_cycle_retires_generated_draft_for_completed_posting_before_selection(tmp_path):
    project_root = bootstrap_project(tmp_path)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    resume_agent(
        connection,
        manual_command="jhc-agent-start",
        timestamp="2026-04-06T00:00:00Z",
    )

    _, job_posting_id = seed_named_role_targeted_posting(
        connection,
        lead_id="ld_completed_stale",
        job_posting_id="jp_completed_stale",
        company_name="Completed Co",
        role_title="AI Engineer",
        posting_status="completed",
        timestamp="2026-04-06T00:01:00Z",
    )
    seed_send_ready_contact_with_generated_message(
        connection,
        contact_id="ct_completed_stale",
        job_posting_contact_id="jpc_completed_stale",
        job_posting_id=job_posting_id,
        company_name="Completed Co",
        display_name="Harald Morjan",
        recipient_email="harald@example.com",
        created_at="2026-04-06T00:01:30Z",
    )

    execution = run_supervisor_cycle(
        connection,
        ProjectPaths.from_root(project_root),
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-04-06T00:02:00Z",
    )

    retired_row = connection.execute(
        """
        SELECT message_status
        FROM outreach_messages
        WHERE outreach_message_id = 'msg_ct_completed_stale'
        """
    ).fetchone()
    connection.close()

    assert execution.cycle.result == SUPERVISOR_CYCLE_RESULT_NO_WORK
    assert execution.selected_work is None
    assert dict(retired_row) == {"message_status": "failed"}


def test_generated_frontier_only_prepass_returns_none_instead_of_falling_back_to_discovery(
    tmp_path,
):
    project_root = bootstrap_project(tmp_path)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    resume_agent(
        connection,
        manual_command="jhc-agent-start",
        timestamp="2026-04-06T00:00:00Z",
    )

    seed_named_role_targeted_posting(
        connection,
        lead_id="ld_draft_only",
        job_posting_id="jp_draft_only",
        company_name="Draft Only Co",
        role_title="Data Engineer",
        posting_status="ready_for_outreach",
        timestamp="2026-04-06T00:01:00Z",
    )
    ensure_role_targeted_pipeline_run(
        connection,
        lead_id="ld_draft_only",
        job_posting_id="jp_draft_only",
        current_stage="sending",
        started_at="2026-04-06T00:02:00Z",
    )
    seed_send_ready_contact_without_message(
        connection,
        contact_id="ct_draft_only",
        job_posting_contact_id="jpc_draft_only",
        job_posting_id="jp_draft_only",
        company_name="Draft Only Co",
        display_name="Riley Recruiter",
        recipient_email="riley@draftonly.example",
        created_at="2026-04-06T00:03:00Z",
    )

    seed_named_role_targeted_posting(
        connection,
        lead_id="ld_discovery",
        job_posting_id="jp_discovery",
        company_name="Discovery Co",
        role_title="Backend Engineer",
        posting_status="requires_contacts",
        timestamp="2026-04-06T00:04:00Z",
    )
    ensure_role_targeted_pipeline_run(
        connection,
        lead_id="ld_discovery",
        job_posting_id="jp_discovery",
        current_stage="email_discovery",
        started_at="2026-04-06T00:05:00Z",
    )

    selected_work = _select_open_pipeline_run_work_unit(
        connection,
        project_root=project_root,
        current_time="2026-04-06T00:06:00Z",
        local_timezone="UTC",
        generated_frontier_only=True,
    )
    connection.close()

    assert selected_work is None

def test_run_supervisor_cycle_ignores_empty_gmail_batch_without_checkpoint(
    tmp_path,
):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    resume_agent(
        connection,
        manual_command="jhc-agent-start",
        timestamp="2026-04-06T00:00:00Z",
    )
    gmail_collector = FakeGmailAlertCollector(
        GmailAlertBatch(
            ingestion_run_id="gmail-auto-20260406T000100Z",
            messages=(),
            mailbox_history_id_before=None,
            mailbox_history_id_after=None,
            poll_strategy="recent_search_bootstrap",
        )
    )

    execution = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-04-06T00:01:00Z",
        action_dependencies=SupervisorActionDependencies(
            gmail_alert_collector=gmail_collector,
            local_timezone="UTC",
        ),
    )
    incident_count = int(connection.execute("SELECT COUNT(*) FROM agent_incidents").fetchone()[0] or 0)
    connection.close()

    assert execution.cycle.result == "no_work"
    assert execution.selected_work is None
    assert incident_count == 0
    assert not (paths.gmail_runtime_dir / "_checkpoint-seeds" / "gmail-auto-20260406T000100Z.json").exists()


def test_run_supervisor_cycle_recovers_orphaned_send_stage_run_into_sending(tmp_path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    orphaned_lead_id, orphaned_job_posting_id = seed_named_role_targeted_posting(
        connection,
        lead_id="ld_orphaned",
        job_posting_id="jp_orphaned",
        company_name="Recovered Co",
        role_title="Machine Learning Engineer",
        posting_status="outreach_in_progress",
        timestamp="2026-04-06T00:00:00Z",
    )
    seed_tailoring_run(
        connection,
        run_id="rtr_orphaned_approved",
        job_posting_id=orphaned_job_posting_id,
        tailoring_status="tailored",
        resume_review_status="approved",
        verification_outcome="pass",
        final_resume_path="resume-tailoring/output/rtr_orphaned_approved/final.pdf",
        timestamp="2026-04-06T00:01:00Z",
    )
    original_run, _ = ensure_role_targeted_pipeline_run(
        connection,
        lead_id=orphaned_lead_id,
        job_posting_id=orphaned_job_posting_id,
        current_stage="sending",
        started_at="2026-04-06T00:02:00Z",
    )
    fail_pipeline_run(
        connection,
        original_run.pipeline_run_id,
        current_stage="sending",
        error_summary="retired while June backlog was reprioritized",
        timestamp="2026-04-06T00:03:00Z",
    )
    seed_send_ready_contact_with_generated_message(
        connection,
        contact_id="ct_orphaned",
        job_posting_contact_id="jpc_orphaned",
        job_posting_id=orphaned_job_posting_id,
        company_name="Recovered Co",
        display_name="Taylor Hiring Manager",
        recipient_email="taylor@recovered.example",
        created_at="2026-04-06T00:04:00Z",
    )
    resume_agent(
        connection,
        manual_command="jhc-agent-start",
        timestamp="2026-04-06T00:05:00Z",
    )

    execution = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-04-06T00:06:00Z",
        action_dependencies=SupervisorActionDependencies(local_timezone="UTC"),
    )
    pipeline_runs = connection.execute(
        """
        SELECT pipeline_run_id, run_status, current_stage, run_summary
        FROM pipeline_runs
        WHERE job_posting_id = ?
        ORDER BY started_at ASC, pipeline_run_id ASC
        """,
        (orphaned_job_posting_id,),
    ).fetchall()
    connection.close()

    assert execution.cycle.result == SUPERVISOR_CYCLE_RESULT_SUCCESS
    assert execution.selected_work is not None
    assert execution.selected_work.action_id == "bootstrap_role_targeted_run"
    assert execution.selected_work.work_id == orphaned_job_posting_id
    assert execution.selected_work.current_stage == "sending"
    assert execution.pipeline_run is not None
    assert execution.pipeline_run.pipeline_run_id != original_run.pipeline_run_id
    assert execution.pipeline_run.current_stage == "sending"
    assert execution.pipeline_run.run_status == RUN_STATUS_IN_PROGRESS
    assert execution.pipeline_run.run_summary == (
        "Supervisor recovered orphaned send-stage work by recreating a durable "
        "role-targeted run at sending."
    )
    assert [dict(row) for row in pipeline_runs] == [
        {
            "pipeline_run_id": original_run.pipeline_run_id,
            "run_status": "failed",
            "current_stage": "sending",
            "run_summary": None,
        },
        {
            "pipeline_run_id": execution.pipeline_run.pipeline_run_id,
            "run_status": "in_progress",
            "current_stage": "sending",
            "run_summary": (
                "Supervisor recovered orphaned send-stage work by recreating a durable "
                "role-targeted run at sending."
            ),
        },
    ]


def test_run_supervisor_cycle_retires_generated_draft_for_completed_posting_before_selection(tmp_path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    _lead_id, job_posting_id = seed_named_role_targeted_posting(
        connection,
        lead_id="ld_completed_stale",
        job_posting_id="jp_completed_stale",
        company_name="Dormant Co",
        role_title="Platform Engineer",
        posting_status="completed",
        timestamp="2026-04-06T00:00:00Z",
    )
    seed_send_ready_contact_with_generated_message(
        connection,
        contact_id="ct_completed_stale",
        job_posting_contact_id="jpc_completed_stale",
        job_posting_id=job_posting_id,
        company_name="Dormant Co",
        display_name="Riley Dormant",
        recipient_email="riley@dormant.example",
        created_at="2026-04-06T00:01:00Z",
    )
    resume_agent(
        connection,
        manual_command="jhc-agent-start",
        timestamp="2026-04-06T00:02:00Z",
    )

    execution = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-04-06T00:03:00Z",
        action_dependencies=SupervisorActionDependencies(local_timezone="UTC"),
    )
    message_row = connection.execute(
        """
        SELECT message_status
        FROM outreach_messages
        WHERE outreach_message_id = 'msg_ct_completed_stale'
        """
    ).fetchone()
    connection.close()

    assert execution.cycle.result == SUPERVISOR_CYCLE_RESULT_NO_WORK
    assert execution.selected_work is None
    assert message_row["message_status"] == "failed"


def test_run_supervisor_cycle_reconciles_stale_sending_run_back_to_email_discovery(
    tmp_path,
):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    lead_id, job_posting_id = seed_named_role_targeted_posting(
        connection,
        lead_id="ld_stale_send",
        job_posting_id="jp_stale_send",
        company_name="Recovered Co",
        role_title="Machine Learning Engineer",
        posting_status="outreach_in_progress",
        timestamp="2026-04-06T00:00:00Z",
    )
    seed_tailoring_run(
        connection,
        run_id="rtr_stale_send_approved",
        job_posting_id=job_posting_id,
        tailoring_status="tailored",
        resume_review_status="approved",
        verification_outcome="pass",
        final_resume_path="resume-tailoring/output/rtr_stale_send_approved/final.pdf",
        timestamp="2026-04-06T00:01:00Z",
    )
    stale_run, _ = ensure_role_targeted_pipeline_run(
        connection,
        lead_id=lead_id,
        job_posting_id=job_posting_id,
        current_stage="sending",
        started_at="2026-04-06T00:02:00Z",
    )
    seed_send_ready_contact_with_generated_message(
        connection,
        contact_id="ct_stale_sent",
        job_posting_contact_id="jpc_stale_sent",
        job_posting_id=job_posting_id,
        company_name="Recovered Co",
        display_name="Taylor Hiring Manager",
        recipient_email="taylor@recovered.example",
        created_at="2026-04-06T00:03:00Z",
    )
    connection.execute(
        """
        UPDATE outreach_messages
        SET message_status = ?, sent_at = ?, updated_at = ?
        WHERE outreach_message_id = ?
        """,
        (
            "sent",
            "2026-04-06T00:04:00Z",
            "2026-04-06T00:04:00Z",
            "msg_ct_stale_sent",
        ),
    )
    connection.execute(
        """
        UPDATE job_posting_contacts
        SET link_level_status = ?, updated_at = ?
        WHERE job_posting_contact_id = ?
        """,
        (
            "outreach_done",
            "2026-04-06T00:04:00Z",
            "jpc_stale_sent",
        ),
    )
    connection.execute(
        """
        INSERT INTO contacts (
          contact_id, identity_key, display_name, company_name, origin_component, contact_status,
          full_name, current_working_email, position_title, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "ct_stale_needs_email",
            "recovered co|avery-platform-engineer",
            "Avery Platform Engineer",
            "Recovered Co",
            "email_discovery",
            "identified",
            "Avery Platform Engineer",
            None,
            "Senior Software Engineer",
            "2026-04-06T00:05:00Z",
            "2026-04-06T00:05:00Z",
        ),
    )
    connection.execute(
        """
        INSERT INTO job_posting_contacts (
          job_posting_contact_id, job_posting_id, contact_id, recipient_type, relevance_reason,
          link_level_status, is_in_intended_outreach_set, entered_intended_outreach_set_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "jpc_stale_needs_email",
            job_posting_id,
            "ct_stale_needs_email",
            "engineer",
            "Later-wave contact still needs a usable email.",
            "shortlisted",
            1,
            "2026-04-06T00:05:00Z",
            "2026-04-06T00:05:00Z",
            "2026-04-06T00:05:00Z",
        ),
    )
    _, discovery_job_posting_id = seed_named_role_targeted_posting(
        connection,
        lead_id="ld_discovery",
        job_posting_id="jp_discovery",
        company_name="Discovery Co",
        role_title="Backend Engineer",
        posting_status="requires_contacts",
        timestamp="2026-04-06T00:06:00Z",
    )
    ensure_role_targeted_pipeline_run(
        connection,
        lead_id="ld_discovery",
        job_posting_id=discovery_job_posting_id,
        current_stage="email_discovery",
        started_at="2026-04-06T00:07:00Z",
    )
    resume_agent(
        connection,
        manual_command="jhc-agent-start",
        timestamp="2026-04-06T00:08:00Z",
    )

    execution = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-04-06T00:09:00Z",
        action_dependencies=SupervisorActionDependencies(local_timezone="UTC"),
    )
    posting_status = connection.execute(
        "SELECT posting_status FROM job_postings WHERE job_posting_id = ?",
        (job_posting_id,),
    ).fetchone()[0]
    generated_count = int(
        connection.execute(
            """
            SELECT COUNT(*)
            FROM outreach_messages
            WHERE job_posting_id = ?
              AND message_status = 'generated'
            """,
            (job_posting_id,),
        ).fetchone()[0]
        or 0
    )
    connection.close()

    assert execution.cycle.result == SUPERVISOR_CYCLE_RESULT_SUCCESS
    assert execution.selected_work is not None
    assert execution.selected_work.action_id == "run_role_targeted_sending"
    assert execution.selected_work.pipeline_run_id == stale_run.pipeline_run_id
    assert execution.pipeline_run is not None
    assert execution.pipeline_run.pipeline_run_id == stale_run.pipeline_run_id
    assert execution.pipeline_run.current_stage == "email_discovery"
    assert execution.pipeline_run.run_status == RUN_STATUS_IN_PROGRESS
    assert posting_status == "requires_contacts"
    assert generated_count == 0


def test_run_supervisor_cycle_completes_stale_sending_run_without_new_frontier(
    tmp_path,
):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    lead_id, job_posting_id = seed_named_role_targeted_posting(
        connection,
        lead_id="ld_repeat_review",
        job_posting_id="jp_repeat_review",
        company_name="Review Co",
        role_title="Backend Engineer",
        posting_status="ready_for_outreach",
        timestamp="2026-04-06T00:00:00Z",
    )
    seed_tailoring_run(
        connection,
        run_id="rtr_repeat_review_approved",
        job_posting_id=job_posting_id,
        tailoring_status="tailored",
        resume_review_status="approved",
        verification_outcome="pass",
        final_resume_path="resume-tailoring/output/rtr_repeat_review_approved/final.pdf",
        timestamp="2026-04-06T00:01:00Z",
    )
    stale_run, _ = ensure_role_targeted_pipeline_run(
        connection,
        lead_id=lead_id,
        job_posting_id=job_posting_id,
        current_stage="sending",
        started_at="2026-04-06T00:02:00Z",
    )
    connection.execute(
        """
        INSERT INTO contacts (
          contact_id, identity_key, display_name, company_name, origin_component, contact_status,
          full_name, current_working_email, position_title, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "ct_repeat_review",
            "review co|morgan-manager",
            "Morgan Manager",
            "Review Co",
            "email_discovery",
            "working_email_found",
            "Morgan Manager",
            "morgan@review.example",
            "Engineering Manager",
            "2026-04-06T00:03:00Z",
            "2026-04-06T00:03:00Z",
        ),
    )
    connection.execute(
        """
        INSERT INTO job_posting_contacts (
          job_posting_contact_id, job_posting_id, contact_id, recipient_type, relevance_reason,
          link_level_status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "jpc_repeat_review",
            job_posting_id,
            "ct_repeat_review",
            "hiring_manager",
            "Selected for automatic outreach review.",
            "shortlisted",
            "2026-04-06T00:03:00Z",
            "2026-04-06T00:03:00Z",
        ),
    )
    seed_named_role_targeted_posting(
        connection,
        lead_id="ld_prior_outreach",
        job_posting_id="jp_prior_outreach",
        company_name="Earlier Co",
        role_title="Platform Engineer",
        posting_status="completed",
        timestamp="2026-04-06T00:04:00Z",
    )
    connection.execute(
        """
        INSERT INTO outreach_messages (
          outreach_message_id, contact_id, outreach_mode, recipient_email, message_status,
          job_posting_id, job_posting_contact_id, subject, body_text, sent_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "msg_prior_repeat_review",
            "ct_repeat_review",
            "role_targeted",
            "morgan@review.example",
            "sent",
            "jp_prior_outreach",
            None,
            "Earlier outreach",
            "Body",
            "2026-04-06T00:05:00Z",
            "2026-04-06T00:05:00Z",
            "2026-04-06T00:05:00Z",
        ),
    )
    resume_agent(
        connection,
        manual_command="jhc-agent-start",
        timestamp="2026-04-06T00:06:00Z",
    )

    execution = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-04-06T00:07:00Z",
        action_dependencies=SupervisorActionDependencies(local_timezone="UTC"),
    )
    posting_status = connection.execute(
        "SELECT posting_status FROM job_postings WHERE job_posting_id = ?",
        (job_posting_id,),
    ).fetchone()[0]
    current_posting_message_count = int(
        connection.execute(
            "SELECT COUNT(*) FROM outreach_messages WHERE job_posting_id = ?",
            (job_posting_id,),
        ).fetchone()[0]
        or 0
    )
    connection.close()

    assert execution.cycle.result == SUPERVISOR_CYCLE_RESULT_SUCCESS
    assert execution.selected_work is not None
    assert execution.selected_work.action_id == "run_role_targeted_sending"
    assert execution.selected_work.pipeline_run_id == stale_run.pipeline_run_id
    assert execution.pipeline_run is not None
    assert execution.pipeline_run.pipeline_run_id == stale_run.pipeline_run_id
    assert execution.pipeline_run.current_stage == "completed"
    assert execution.pipeline_run.run_status == RUN_STATUS_COMPLETED
    assert posting_status == "completed"
    assert current_posting_message_count == 0


def test_run_supervisor_cycle_reuses_existing_pipeline_run_without_duplicate_history(tmp_path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    lead_id, job_posting_id = seed_role_targeted_posting(connection)
    resume_agent(
        connection,
        manual_command="jhc-agent-start",
        timestamp="2026-04-06T00:05:00Z",
    )
    pipeline_run, _ = ensure_role_targeted_pipeline_run(
        connection,
        lead_id=lead_id,
        job_posting_id=job_posting_id,
        current_stage="lead_handoff",
        started_at="2026-04-06T00:06:00Z",
    )

    execution = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-04-06T00:07:00Z",
    )
    stored_runs = connection.execute(
        """
        SELECT pipeline_run_id, run_status, current_stage, run_summary
        FROM pipeline_runs
        WHERE job_posting_id = ?
        ORDER BY started_at
        """,
        (job_posting_id,),
    ).fetchall()
    connection.close()

    assert execution.cycle.result == SUPERVISOR_CYCLE_RESULT_SUCCESS
    assert execution.selected_work is not None
    assert execution.selected_work.work_type == "pipeline_run"
    assert execution.pipeline_run is not None
    assert execution.pipeline_run.pipeline_run_id == pipeline_run.pipeline_run_id
    assert execution.pipeline_run.run_status == RUN_STATUS_IN_PROGRESS
    assert execution.pipeline_run.current_stage == "resume_tailoring"
    assert len(stored_runs) == 1
    assert stored_runs[0]["pipeline_run_id"] == pipeline_run.pipeline_run_id
    assert stored_runs[0]["current_stage"] == "resume_tailoring"
    assert stored_runs[0]["run_summary"] == (
        "Supervisor advanced the durable pipeline run from lead_handoff into the "
        "bounded resume_tailoring boundary."
    )


def test_run_supervisor_cycle_prioritizes_open_incidents_before_pipeline_advancement(tmp_path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    lead_id, job_posting_id = seed_role_targeted_posting(connection)
    resume_agent(
        connection,
        manual_command="jhc-agent-start",
        timestamp="2026-04-06T00:10:00Z",
    )
    pipeline_run, _ = ensure_role_targeted_pipeline_run(
        connection,
        lead_id=lead_id,
        job_posting_id=job_posting_id,
        current_stage="lead_handoff",
        started_at="2026-04-06T00:11:00Z",
    )
    incident = create_agent_incident(
        connection,
        incident_type="provider_outage",
        severity=INCIDENT_SEVERITY_MEDIUM,
        summary="Apollo enrichment responses are timing out repeatedly.",
        pipeline_run_id=pipeline_run.pipeline_run_id,
        lead_id=lead_id,
        job_posting_id=job_posting_id,
        created_at="2026-04-06T00:12:00Z",
    )

    execution = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-04-06T00:13:00Z",
    )
    escalated_incident = get_agent_incident(connection, incident.agent_incident_id)
    unchanged_run = get_pipeline_run(connection, pipeline_run.pipeline_run_id)
    connection.close()

    assert execution.cycle.result == SUPERVISOR_CYCLE_RESULT_SUCCESS
    assert execution.selected_work is not None
    assert execution.selected_work.work_type == "agent_incident"
    assert execution.incident is not None
    assert execution.incident.agent_incident_id == incident.agent_incident_id
    assert escalated_incident is not None
    assert escalated_incident.status == INCIDENT_STATUS_ESCALATED
    assert unchanged_run is not None
    assert unchanged_run.pipeline_run_id == pipeline_run.pipeline_run_id
    assert unchanged_run.run_summary is None


def test_run_supervisor_cycle_auto_pauses_on_critical_unresolved_incident(tmp_path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    lead_id, job_posting_id = seed_role_targeted_posting(connection)
    resume_agent(
        connection,
        manual_command="jhc-agent-start",
        timestamp="2026-04-06T00:20:00Z",
    )
    ensure_role_targeted_pipeline_run(
        connection,
        lead_id=lead_id,
        job_posting_id=job_posting_id,
        current_stage="lead_handoff",
        started_at="2026-04-06T00:21:00Z",
    )
    critical_incident = create_agent_incident(
        connection,
        incident_type="canonical_state_integrity",
        severity=INCIDENT_SEVERITY_CRITICAL,
        summary="Canonical DB state mismatch detected for an in-flight outreach boundary.",
        lead_id=lead_id,
        job_posting_id=job_posting_id,
        created_at="2026-04-06T00:22:00Z",
    )

    execution = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-04-06T00:23:00Z",
    )
    control_state = read_agent_control_state(connection, timestamp="2026-04-06T00:23:00Z")
    persisted_incident = get_agent_incident(connection, critical_incident.agent_incident_id)
    connection.close()

    assert execution.cycle.result == SUPERVISOR_CYCLE_RESULT_AUTO_PAUSED
    assert execution.selected_work is not None
    assert execution.selected_work.work_type == "agent_incident"
    assert persisted_incident is not None
    assert persisted_incident.status == "open"
    assert control_state.agent_mode == AGENT_MODE_PAUSED
    assert control_state.pause_reason is not None
    assert "canonical_state_integrity" in control_state.pause_reason


@pytest.mark.parametrize(
    "blocked_stage",
    [
        "unsupported_future_stage",
    ],
)
def test_run_supervisor_cycle_emits_incident_when_selected_stage_has_no_registered_action(
    tmp_path,
    blocked_stage,
):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    lead_id, job_posting_id = seed_role_targeted_posting(connection)
    resume_agent(
        connection,
        manual_command="jhc-agent-start",
        timestamp="2026-04-06T00:30:00Z",
    )
    pipeline_run, _ = ensure_role_targeted_pipeline_run(
        connection,
        lead_id=lead_id,
        job_posting_id=job_posting_id,
        current_stage=blocked_stage,
        started_at="2026-04-06T00:31:00Z",
    )

    execution = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-04-06T00:32:00Z",
    )
    updated_run = get_pipeline_run(connection, pipeline_run.pipeline_run_id)
    stored_incidents = connection.execute(
        """
        SELECT incident_type, severity, summary
        FROM agent_incidents
        WHERE pipeline_run_id = ?
        ORDER BY created_at
        """,
        (pipeline_run.pipeline_run_id,),
    ).fetchall()
    stored_packets = list_expert_review_packets_for_run(connection, pipeline_run.pipeline_run_id)
    snapshot = json.loads((project_root / execution.context_snapshot_path).read_text(encoding="utf-8"))
    connection.close()

    assert execution.cycle.result == SUPERVISOR_CYCLE_RESULT_FAILED
    assert execution.selected_work is not None
    assert execution.selected_work.work_type == "pipeline_run"
    assert execution.selected_work.action_id is None
    assert execution.selected_work.current_stage == blocked_stage
    assert execution.incident is not None
    assert execution.incident.incident_type == "unsupported_supervisor_action"
    assert execution.review_packet is not None
    assert execution.review_packet.packet_status == REVIEW_PACKET_STATUS_PENDING
    assert updated_run is not None
    assert updated_run.pipeline_run_id == pipeline_run.pipeline_run_id
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
    assert [dict(row) for row in stored_incidents] == [
        {
            "incident_type": "unsupported_supervisor_action",
            "severity": "high",
            "summary": (
                "No registered bounded supervisor action covers pipeline stage "
                f"'{blocked_stage}' yet."
            ),
        }
    ]


def test_retry_after_downstream_stage_blocker_reuses_same_run_and_pending_review_packet(
    tmp_path,
):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    lead_id, job_posting_id = seed_role_targeted_posting(connection)
    resume_agent(
        connection,
        manual_command="jhc-agent-start",
        timestamp="2026-04-06T00:40:00Z",
    )
    pipeline_run, _ = ensure_role_targeted_pipeline_run(
        connection,
        lead_id=lead_id,
        job_posting_id=job_posting_id,
        current_stage="unsupported_future_stage",
        started_at="2026-04-06T00:41:00Z",
    )

    first_execution = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-04-06T00:42:00Z",
    )
    assert first_execution.incident is not None
    assert first_execution.review_packet is not None

    escalated_incident = escalate_agent_incident(
        connection,
        first_execution.incident.agent_incident_id,
        escalation_reason=(
            "Expert confirmed the downstream supervisor gap and recorded it for later "
            "catalog work."
        ),
        timestamp="2026-04-06T00:43:00Z",
    )
    retried_run = advance_pipeline_run(
        connection,
        pipeline_run.pipeline_run_id,
        current_stage="unsupported_future_stage",
        run_summary="Retry the same downstream boundary without restarting the run.",
        timestamp="2026-04-06T00:44:00Z",
    )
    reused_run, created = ensure_role_targeted_pipeline_run(
        connection,
        lead_id=lead_id,
        job_posting_id=job_posting_id,
        current_stage="lead_handoff",
        started_at="2026-04-06T00:45:00Z",
    )
    second_execution = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-04-06T00:46:00Z",
    )
    stored_runs = connection.execute(
        """
        SELECT pipeline_run_id, run_status, current_stage
        FROM pipeline_runs
        WHERE job_posting_id = ?
        ORDER BY started_at
        """,
        (job_posting_id,),
    ).fetchall()
    stored_packets = list_expert_review_packets_for_run(connection, pipeline_run.pipeline_run_id)
    connection.close()

    assert first_execution.cycle.result == SUPERVISOR_CYCLE_RESULT_FAILED
    assert first_execution.pipeline_run is not None
    assert first_execution.pipeline_run.pipeline_run_id == pipeline_run.pipeline_run_id
    assert first_execution.pipeline_run.current_stage == "unsupported_future_stage"
    assert escalated_incident.status == INCIDENT_STATUS_ESCALATED
    assert retried_run.pipeline_run_id == pipeline_run.pipeline_run_id
    assert retried_run.run_status == RUN_STATUS_IN_PROGRESS
    assert retried_run.current_stage == "unsupported_future_stage"
    assert created is False
    assert reused_run.pipeline_run_id == pipeline_run.pipeline_run_id
    assert reused_run.current_stage == "unsupported_future_stage"
    assert second_execution.cycle.result == SUPERVISOR_CYCLE_RESULT_FAILED
    assert second_execution.selected_work is not None
    assert second_execution.selected_work.work_id == pipeline_run.pipeline_run_id
    assert second_execution.selected_work.current_stage == "unsupported_future_stage"
    assert second_execution.review_packet is not None
    assert second_execution.review_packet.expert_review_packet_id == (
        first_execution.review_packet.expert_review_packet_id
    )
    assert [dict(row) for row in stored_runs] == [
        {
            "pipeline_run_id": pipeline_run.pipeline_run_id,
            "run_status": "escalated",
            "current_stage": "unsupported_future_stage",
        }
    ]
    assert len(stored_packets) == 1


def test_run_supervisor_cycle_executes_daily_maintenance_and_persists_artifacts(tmp_path):
    project_root = bootstrap_project(tmp_path)
    initialize_git_repository(project_root)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    resume_agent(
        connection,
        manual_command="jhc-agent-start",
        timestamp="2026-04-09T00:58:00Z",
    )

    execution = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-04-09T01:00:00Z",
        action_dependencies=build_test_maintenance_dependencies(),
    )
    batch_row = connection.execute(
        """
        SELECT maintenance_change_batch_id, branch_name, status, approval_outcome, json_path, summary_path
        FROM maintenance_change_batches
        """
    ).fetchone()
    snapshot = json.loads(
        (project_root / execution.context_snapshot_path).read_text(encoding="utf-8")
    )
    connection.close()

    assert execution.cycle.result == SUPERVISOR_CYCLE_RESULT_SUCCESS
    assert execution.selected_work is not None
    assert execution.selected_work.work_type == "maintenance_cycle"
    assert execution.selected_work.action_id == ACTION_RUN_DAILY_MAINTENANCE
    assert execution.maintenance_batch_id is not None
    assert batch_row is not None
    assert batch_row["maintenance_change_batch_id"] == execution.maintenance_batch_id
    assert batch_row["branch_name"].startswith(
        f"maintenance/20260409-{execution.maintenance_batch_id}-"
    )
    assert batch_row["status"] == "validated"
    assert batch_row["approval_outcome"] == "pending"

    artifact_json_path = project_root / str(batch_row["json_path"])
    artifact_markdown_path = project_root / str(batch_row["summary_path"])
    artifact_payload = json.loads(artifact_json_path.read_text(encoding="utf-8"))

    assert artifact_json_path.exists()
    assert artifact_markdown_path.exists()
    assert artifact_payload["maintenance_change_batch_id"] == execution.maintenance_batch_id
    assert artifact_payload["local_day"] == "20260409"
    assert artifact_payload["change_scoped_validation"][0]["passed"] is True
    assert artifact_payload["full_system_validation"][0]["passed"] is True
    assert "maintenance-check.txt" in artifact_payload["files_changed"]
    assert snapshot["maintenance_batch"]["maintenance_change_batch_id"] == (
        execution.maintenance_batch_id
    )


def test_run_supervisor_cycle_does_not_interrupt_active_pipeline_run_for_due_maintenance(
    tmp_path,
):
    project_root = bootstrap_project(tmp_path)
    initialize_git_repository(project_root)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    lead_id, job_posting_id = seed_role_targeted_posting(connection)
    resume_agent(
        connection,
        manual_command="jhc-agent-start",
        timestamp="2026-04-09T01:10:00Z",
    )
    active_run, _ = ensure_role_targeted_pipeline_run(
        connection,
        lead_id=lead_id,
        job_posting_id=job_posting_id,
        current_stage="lead_handoff",
        started_at="2026-04-09T01:11:00Z",
    )

    execution = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-04-09T01:12:00Z",
        action_dependencies=build_test_maintenance_dependencies(),
    )
    maintenance_count = int(
        connection.execute(
            "SELECT COUNT(*) FROM maintenance_change_batches"
        ).fetchone()[0]
        or 0
    )
    connection.close()

    assert execution.cycle.result == SUPERVISOR_CYCLE_RESULT_SUCCESS
    assert execution.selected_work is not None
    assert execution.selected_work.work_type == "pipeline_run"
    assert execution.pipeline_run is not None
    assert execution.pipeline_run.pipeline_run_id == active_run.pipeline_run_id
    assert execution.pipeline_run.current_stage == "resume_tailoring"
    assert maintenance_count == 0


def test_run_supervisor_cycle_selects_new_posting_before_due_maintenance(tmp_path):
    project_root = bootstrap_project(tmp_path)
    initialize_git_repository(project_root)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    _, job_posting_id = seed_role_targeted_posting(connection)
    resume_agent(
        connection,
        manual_command="jhc-agent-start",
        timestamp="2026-04-09T01:15:00Z",
    )

    execution = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-04-09T01:16:00Z",
        action_dependencies=build_test_maintenance_dependencies(),
    )
    maintenance_count = int(
        connection.execute(
            "SELECT COUNT(*) FROM maintenance_change_batches"
        ).fetchone()[0]
        or 0
    )
    connection.close()

    assert execution.cycle.result == SUPERVISOR_CYCLE_RESULT_SUCCESS
    assert execution.selected_work is not None
    assert execution.selected_work.work_type == "job_posting"
    assert execution.selected_work.job_posting_id == job_posting_id
    assert execution.pipeline_run is not None
    assert execution.pipeline_run.job_posting_id == job_posting_id
    assert maintenance_count == 0


def test_run_supervisor_cycle_retains_failed_maintenance_batch_for_review(tmp_path):
    project_root = bootstrap_project(tmp_path)
    initialize_git_repository(project_root)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    resume_agent(
        connection,
        manual_command="jhc-agent-start",
        timestamp="2026-04-09T01:20:00Z",
    )

    execution = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-04-09T01:21:00Z",
        action_dependencies=build_test_maintenance_dependencies(
            should_fail_full_system=True
        ),
    )
    batch_row = connection.execute(
        """
        SELECT status, approval_outcome, failed_at, json_path
        FROM maintenance_change_batches
        WHERE maintenance_change_batch_id = ?
        """,
        (execution.maintenance_batch_id,),
    ).fetchone()
    connection.close()

    assert execution.cycle.result == SUPERVISOR_CYCLE_RESULT_SUCCESS
    assert execution.maintenance_batch_id is not None
    assert batch_row is not None
    assert batch_row["status"] == "retained_for_review"
    assert batch_row["approval_outcome"] == "failed_validation"
    assert batch_row["failed_at"] == "2026-04-09T01:21:00Z"

    artifact_payload = json.loads(
        (project_root / str(batch_row["json_path"])).read_text(encoding="utf-8")
    )
    assert artifact_payload["full_system_validation"][0]["passed"] is False
    assert artifact_payload["change_scoped_validation"][0]["passed"] is True
    assert artifact_payload["status"] == "retained_for_review"
    assert artifact_payload["approval_outcome"] == "failed_validation"


def test_run_supervisor_cycle_runs_maintenance_only_once_per_local_day(tmp_path):
    project_root = bootstrap_project(tmp_path)
    initialize_git_repository(project_root)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    resume_agent(
        connection,
        manual_command="jhc-agent-start",
        timestamp="2026-04-09T01:30:00Z",
    )
    action_dependencies = build_test_maintenance_dependencies()

    first_execution = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-04-09T01:31:00Z",
        action_dependencies=action_dependencies,
    )
    second_execution = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-04-09T12:00:00Z",
        action_dependencies=action_dependencies,
    )
    maintenance_count = int(
        connection.execute(
            "SELECT COUNT(*) FROM maintenance_change_batches"
        ).fetchone()[0]
        or 0
    )
    connection.close()

    assert first_execution.maintenance_batch_id is not None
    assert second_execution.cycle.result == "no_work"
    assert second_execution.selected_work is None
    assert maintenance_count == 1
