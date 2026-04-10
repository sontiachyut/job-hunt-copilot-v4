from __future__ import annotations

import json
import plistlib
import sqlite3
import subprocess
import sys
from datetime import timedelta, timezone
from pathlib import Path

from job_hunt_copilot.chat_runtime import (
    build_chat_review_queue,
    build_chat_startup_dashboard,
)
import job_hunt_copilot.maintenance as maintenance_runtime
import job_hunt_copilot.local_runtime as local_runtime
from job_hunt_copilot.delivery_feedback import DeliveryFeedbackSignal
from job_hunt_copilot.maintenance import (
    MaintenanceDependencies,
    MaintenancePlan,
    MaintenanceValidationCommand,
    run_daily_maintenance_cycle,
)
from job_hunt_copilot.paths import ProjectPaths
from job_hunt_copilot.local_runtime import (
    begin_chat_operator_session,
    end_chat_operator_session,
    execute_delayed_feedback_sync,
    execute_supervisor_heartbeat,
    mutate_agent_control_state,
)
from job_hunt_copilot.resume_tailoring import (
    RESUME_REVIEW_STATUS_APPROVED,
    RESUME_REVIEW_STATUS_REJECTED,
    record_tailoring_review_decision,
)
from job_hunt_copilot.supervisor import SupervisorActionDependencies
from tests.support import (
    create_minimal_project,
    initialize_git_repository,
    seed_pending_review_tailoring_run,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def run_script(script_relative_path: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / script_relative_path), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def connect_database(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    return connection


def make_command_result(
    *,
    stdout: str = "",
    stderr: str = "",
    returncode: int = 0,
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["mocked-command"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def test_maintenance_run_command_uses_current_python_when_requested_binary_missing(
    monkeypatch,
    tmp_path,
):
    captured: dict[str, object] = {}

    def fake_run(args, **kwargs):  # type: ignore[no-untyped-def]
        captured["args"] = list(args)
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(
            args=list(args),
            returncode=0,
            stdout="ok\n",
            stderr="",
        )

    monkeypatch.setattr(
        maintenance_runtime.shutil,
        "which",
        lambda executable: None if executable == "python3.11" else f"/usr/bin/{executable}",
    )
    monkeypatch.setattr(maintenance_runtime.subprocess, "run", fake_run)

    result = maintenance_runtime._run_command(
        ("python3.11", "-m", "pytest", "tests/test_runtime_pack.py"),
        tmp_path,
    )

    assert result.returncode == 0
    assert captured["args"] == [
        sys.executable,
        "-m",
        "pytest",
        "tests/test_runtime_pack.py",
    ]


def build_test_maintenance_dependencies(
    *,
    should_fail_full_system: bool = False,
) -> SupervisorActionDependencies:
    def apply_changes(worktree_path: Path) -> None:
        (worktree_path / "maintenance-check.txt").write_text(
            "maintenance checkpoint\n",
            encoding="utf-8",
        )

    def run_validation(
        args: tuple[str, ...],
        cwd: Path,
    ) -> subprocess.CompletedProcess[str]:
        del cwd
        label = args[-1]
        if should_fail_full_system and label == "full-system-check":
            return make_command_result(
                stdout="full-system validation failed\n",
                returncode=1,
            )
        return make_command_result(stdout=f"{label} passed\n")

    return SupervisorActionDependencies(
        local_timezone="UTC",
        maintenance_dependencies=MaintenanceDependencies(
            plan=MaintenancePlan(
                scope_slug="daily-healthcheck",
                short_reason="Record the bounded maintenance checkpoint for runtime-control coverage.",
                notes="Local runtime maintenance regression test batch.",
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


class FakeMailboxFeedbackObserver:
    def __init__(self, *, signals: list[DeliveryFeedbackSignal]) -> None:
        self.signals = signals
        self.poll_calls: list[dict[str, object]] = []

    def poll(self, messages, *, current_time, observation_scope):  # type: ignore[no-untyped-def]
        self.poll_calls.append(
            {
                "message_ids": [message.outreach_message_id for message in messages],
                "current_time": current_time,
                "observation_scope": observation_scope,
            }
        )
        return list(self.signals)


def seed_feedback_candidate(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        INSERT INTO linkedin_leads (
          lead_id, lead_identity_key, lead_status, lead_shape, split_review_status,
          source_type, source_reference, source_mode, source_url, company_name, role_title,
          created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "ld_feedback",
            "acme-robotics|staff-software-engineer-ai",
            "handed_off",
            "posting_only",
            "not_applicable",
            "gmail_job_alert",
            "gmail/message/feedback",
            "gmail_job_alert",
            "https://careers.acme.example/jobs/feedback",
            "Acme Robotics",
            "Staff Software Engineer / AI",
            "2026-04-07T10:00:00Z",
            "2026-04-07T10:00:00Z",
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
            "jp_feedback",
            "ld_feedback",
            "acme-robotics|staff-software-engineer-ai",
            "Acme Robotics",
            "Staff Software Engineer / AI",
            "completed",
            "2026-04-07T10:00:00Z",
            "2026-04-07T10:00:00Z",
        ),
    )
    connection.execute(
        """
        INSERT INTO contacts (
          contact_id, identity_key, display_name, company_name, origin_component, contact_status,
          full_name, current_working_email, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "ct_feedback",
            "priya-recruiter|acme-robotics",
            "Priya Recruiter",
            "Acme Robotics",
            "email_discovery",
            "sent",
            "Priya Recruiter",
            "priya@acme.example",
            "2026-04-07T10:01:00Z",
            "2026-04-07T10:01:00Z",
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
            "jpc_feedback",
            "jp_feedback",
            "ct_feedback",
            "recruiter",
            "Local runtime delayed feedback test linkage.",
            "outreach_done",
            "2026-04-07T10:01:00Z",
            "2026-04-07T10:01:00Z",
        ),
    )
    connection.execute(
        """
        INSERT INTO outreach_messages (
          outreach_message_id, contact_id, outreach_mode, recipient_email, message_status,
          job_posting_id, job_posting_contact_id, subject, body_text, thread_id,
          delivery_tracking_id, sent_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "msg_feedback",
            "ct_feedback",
            "role_targeted",
            "priya@acme.example",
            "sent",
            "jp_feedback",
            "jpc_feedback",
            "Hello",
            "Body",
            "thread-msg_feedback",
            "delivery-msg_feedback",
            "2026-04-07T10:03:00Z",
            "2026-04-07T10:03:00Z",
            "2026-04-07T10:03:00Z",
        ),
    )
    connection.commit()


def seed_posting_for_abandon(
    connection: sqlite3.Connection,
    *,
    posting_status: str,
    run_status: str | None = None,
    current_stage: str = "sending",
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
            "ld_abandon",
            "acme-robotics|staff-software-engineer-platform",
            "handed_off",
            "posting_only",
            "not_applicable",
            "manual_capture",
            "paste/lead-abandon",
            "manual_capture",
            "https://careers.acme.example/jobs/abandon",
            "Acme Robotics",
            "Staff Software Engineer / Platform",
            "2026-04-08T12:00:00Z",
            "2026-04-08T12:00:00Z",
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
            "jp_abandon",
            "ld_abandon",
            "acme-robotics|staff-software-engineer-platform",
            "Acme Robotics",
            "Staff Software Engineer / Platform",
            posting_status,
            "2026-04-08T12:00:00Z",
            "2026-04-08T12:00:00Z",
        ),
    )
    if run_status is not None:
        connection.execute(
            """
            INSERT INTO pipeline_runs (
              pipeline_run_id, run_scope_type, run_status, current_stage, lead_id,
              job_posting_id, completed_at, last_error_summary, review_packet_status,
              run_summary, started_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "pr_abandon",
                "role_targeted_posting",
                run_status,
                current_stage,
                "ld_abandon",
                "jp_abandon",
                None,
                None,
                "not_ready",
                "Active pipeline run before abandon.",
                "2026-04-08T12:05:00Z",
                "2026-04-08T12:05:00Z",
                "2026-04-08T12:05:00Z",
            ),
        )
    connection.commit()


def seed_posting_for_tailoring_override(
    connection: sqlite3.Connection,
    *,
    posting_status: str = "resume_review_pending",
    timestamp: str = "2026-04-08T09:00:00Z",
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
            "ld_tailoring_override",
            "acme-robotics|staff-platform-engineer",
            "handed_off",
            "posting_only",
            "not_applicable",
            "manual_capture",
            "paste/lead-tailoring-override",
            "manual_capture",
            "https://careers.acme.example/jobs/tailoring-override",
            "Acme Robotics",
            "Staff Platform Engineer",
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
            "jp_tailoring_override",
            "ld_tailoring_override",
            "acme-robotics|staff-platform-engineer",
            "Acme Robotics",
            "Staff Platform Engineer",
            posting_status,
            timestamp,
            timestamp,
        ),
    )
    connection.commit()


def seed_posting_for_guidance(
    connection: sqlite3.Connection,
    *,
    lead_id: str,
    job_posting_id: str,
    company_name: str,
    role_title: str,
    posting_status: str = "requires_contacts",
    timestamp: str = "2026-04-08T09:00:00Z",
) -> None:
    identity_key = f"{company_name.lower().replace(' ', '-')}|{role_title.lower().replace(' ', '-')}"
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
            identity_key,
            "handed_off",
            "posting_only",
            "not_applicable",
            "manual_capture",
            f"paste/{lead_id}",
            "manual_capture",
            f"https://careers.example/jobs/{job_posting_id}",
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
            identity_key,
            company_name,
            role_title,
            posting_status,
            timestamp,
            timestamp,
        ),
    )
    connection.commit()


def seed_chat_dashboard_state(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        INSERT INTO linkedin_leads (
          lead_id, lead_identity_key, lead_status, lead_shape, split_review_status,
          source_type, source_reference, source_mode, source_url, company_name, role_title,
          created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "ld_chat",
            "acme-robotics|staff-software-engineer-ai",
            "handed_off",
            "posting_only",
            "not_applicable",
            "manual_capture",
            "paste/lead-chat",
            "manual_capture",
            "https://careers.acme.example/jobs/ai",
            "Acme Robotics",
            "Staff Software Engineer / AI",
            "2026-04-07T15:00:00Z",
            "2026-04-08T14:35:00Z",
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
            "jp_chat",
            "ld_chat",
            "acme-robotics|staff-software-engineer-ai",
            "Acme Robotics",
            "Staff Software Engineer / AI",
            "outreach_in_progress",
            "2026-04-07T15:05:00Z",
            "2026-04-08T14:35:00Z",
        ),
    )
    connection.execute(
        """
        INSERT INTO pipeline_runs (
          pipeline_run_id, run_scope_type, run_status, current_stage, lead_id,
          job_posting_id, review_packet_status, run_summary, started_at, completed_at,
          created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "pr_chat_review",
            "job_posting",
            "escalated",
            "sending",
            "ld_chat",
            "jp_chat",
            "pending_expert_review",
            "Duplicate-send risk needs expert review.",
            "2026-04-08T14:10:00Z",
            "2026-04-08T14:35:00Z",
            "2026-04-08T14:10:00Z",
            "2026-04-08T14:35:00Z",
        ),
    )
    connection.execute(
        """
        INSERT INTO expert_review_packets (
          expert_review_packet_id, pipeline_run_id, packet_status, packet_path,
          job_posting_id, summary_excerpt, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "erp_chat",
            "pr_chat_review",
            "pending_expert_review",
            "ops/review-packets/pr_chat_review/review_packet.md",
            "jp_chat",
            "Duplicate-send risk requires review before another send.",
            "2026-04-08T14:36:00Z",
        ),
    )
    connection.execute(
        """
        INSERT INTO agent_incidents (
          agent_incident_id, incident_type, severity, status, summary,
          pipeline_run_id, job_posting_id, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "ai_chat",
            "duplicate_send_risk",
            "high",
            "open",
            "Potential resend detected for the current outreach wave.",
            "pr_chat_review",
            "jp_chat",
            "2026-04-08T14:34:00Z",
            "2026-04-08T14:37:00Z",
        ),
    )
    connection.execute(
        """
        INSERT INTO maintenance_change_batches (
          maintenance_change_batch_id, branch_name, scope_slug, status, approval_outcome,
          summary_path, json_path, validation_summary, failed_at, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "mcb_chat",
            "maintenance/20260408-mcb-chat-runtime-summary",
            "chat-runtime-summary",
            "failed_validation",
            "needs_review",
            "ops/maintenance/mcb_chat/summary.md",
            "ops/maintenance/mcb_chat/summary.json",
            "Full-project validation failed after the scoped patch passed.",
            "2026-04-08T13:50:00Z",
            "2026-04-08T13:10:00Z",
        ),
    )
    connection.execute(
        """
        INSERT INTO pipeline_runs (
          pipeline_run_id, run_scope_type, run_status, current_stage, lead_id,
          job_posting_id, review_packet_status, run_summary, started_at, completed_at,
          created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "pr_success_today",
            "job_posting",
            "completed",
            "delivery_feedback",
            "ld_chat",
            "jp_chat",
            "not_ready",
            "Completed role-targeted send wave.",
            "2026-04-08T13:00:00Z",
            "2026-04-08T13:20:00Z",
            "2026-04-08T13:00:00Z",
            "2026-04-08T13:20:00Z",
        ),
    )
    connection.execute(
        """
        INSERT INTO pipeline_runs (
          pipeline_run_id, run_scope_type, run_status, current_stage, lead_id,
          job_posting_id, review_packet_status, run_summary, started_at, completed_at,
          created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "pr_success_yesterday",
            "job_posting",
            "completed",
            "delivery_feedback",
            "ld_chat",
            "jp_chat",
            "not_ready",
            "Completed earlier role-targeted send wave.",
            "2026-04-07T15:00:00Z",
            "2026-04-07T15:30:00Z",
            "2026-04-07T15:00:00Z",
            "2026-04-07T15:30:00Z",
        ),
    )
    connection.execute(
        """
        INSERT INTO supervisor_cycles (
          supervisor_cycle_id, trigger_type, scheduler_name, pipeline_run_id,
          started_at, completed_at, result, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "sc_chat_today_1",
            "launchd_heartbeat",
            "launchd",
            "pr_success_today",
            "2026-04-08T13:00:00Z",
            "2026-04-08T13:20:00Z",
            "completed",
            "2026-04-08T13:00:00Z",
        ),
    )
    connection.execute(
        """
        INSERT INTO supervisor_cycles (
          supervisor_cycle_id, trigger_type, scheduler_name, pipeline_run_id,
          started_at, completed_at, result, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "sc_chat_today_2",
            "launchd_heartbeat",
            "launchd",
            "pr_chat_review",
            "2026-04-08T14:20:00Z",
            "2026-04-08T14:35:00Z",
            "escalated",
            "2026-04-08T14:20:00Z",
        ),
    )
    connection.execute(
        """
        INSERT INTO supervisor_cycles (
          supervisor_cycle_id, trigger_type, scheduler_name, pipeline_run_id,
          started_at, completed_at, result, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "sc_chat_yesterday",
            "launchd_heartbeat",
            "launchd",
            "pr_success_yesterday",
            "2026-04-07T15:00:00Z",
            "2026-04-07T15:30:00Z",
            "completed",
            "2026-04-07T15:00:00Z",
        ),
    )
    connection.execute(
        """
        INSERT INTO contacts (
          contact_id, identity_key, display_name, company_name, origin_component, contact_status,
          full_name, current_working_email, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "ct_chat",
            "priya-recruiter|acme-robotics",
            "Priya Recruiter",
            "Acme Robotics",
            "email_discovery",
            "sent",
            "Priya Recruiter",
            "priya@acme.example",
            "2026-04-07T15:10:00Z",
            "2026-04-08T14:35:00Z",
        ),
    )
    connection.execute(
        """
        INSERT INTO outreach_messages (
          outreach_message_id, contact_id, outreach_mode, recipient_email, message_status,
          job_posting_id, subject, body_text, thread_id, delivery_tracking_id, sent_at,
          created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "msg_today",
            "ct_chat",
            "role_targeted",
            "priya@acme.example",
            "sent",
            "jp_chat",
            "Hello again",
            "Follow-up body",
            "thread-today",
            "delivery-today",
            "2026-04-08T14:00:00Z",
            "2026-04-08T14:00:00Z",
            "2026-04-08T14:00:00Z",
        ),
    )
    connection.execute(
        """
        INSERT INTO outreach_messages (
          outreach_message_id, contact_id, outreach_mode, recipient_email, message_status,
          job_posting_id, subject, body_text, thread_id, delivery_tracking_id, sent_at,
          created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "msg_yesterday",
            "ct_chat",
            "role_targeted",
            "priya@acme.example",
            "sent",
            "jp_chat",
            "Yesterday hello",
            "Earlier body",
            "thread-yesterday",
            "delivery-yesterday",
            "2026-04-07T15:05:00Z",
            "2026-04-07T15:05:00Z",
            "2026-04-07T15:05:00Z",
        ),
    )
    connection.execute(
        """
        INSERT INTO delivery_feedback_events (
          delivery_feedback_event_id, outreach_message_id, event_state, event_timestamp,
          reply_summary, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            "dfe_bounce_today",
            "msg_today",
            "bounced",
            "2026-04-08T14:10:00Z",
            "",
            "2026-04-08T14:10:00Z",
        ),
    )
    connection.execute(
        """
        INSERT INTO delivery_feedback_events (
          delivery_feedback_event_id, outreach_message_id, event_state, event_timestamp,
          reply_summary, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            "dfe_reply_yesterday",
            "msg_yesterday",
            "replied",
            "2026-04-07T15:20:00Z",
            "Let's reconnect next quarter.",
            "2026-04-07T15:20:00Z",
        ),
    )
    connection.commit()


def seed_chat_review_queue_state(connection: sqlite3.Connection) -> None:
    seed_chat_dashboard_state(connection)
    connection.execute(
        """
        INSERT INTO linkedin_leads (
          lead_id, lead_identity_key, lead_status, lead_shape, split_review_status,
          source_type, source_reference, source_mode, source_url, company_name, role_title,
          created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "ld_chat_newer",
            "beta-labs|ml-platform-engineer",
            "handed_off",
            "posting_only",
            "not_applicable",
            "gmail_job_alert",
            "gmail/message/chat-newer",
            "gmail_job_alert",
            "https://careers.beta.example/jobs/ml-platform",
            "Beta Labs",
            "ML Platform Engineer",
            "2026-04-08T15:00:00Z",
            "2026-04-08T15:00:00Z",
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
            "jp_chat_newer",
            "ld_chat_newer",
            "beta-labs|ml-platform-engineer",
            "Beta Labs",
            "ML Platform Engineer",
            "delivery_feedback",
            "2026-04-08T15:00:00Z",
            "2026-04-08T15:00:00Z",
        ),
    )
    connection.execute(
        """
        INSERT INTO pipeline_runs (
          pipeline_run_id, run_scope_type, run_status, current_stage, lead_id,
          job_posting_id, review_packet_status, run_summary, started_at, completed_at,
          created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "pr_chat_review_newer",
            "job_posting",
            "escalated",
            "email_discovery",
            "ld_chat_newer",
            "jp_chat_newer",
            "pending_expert_review",
            "Newer discovery stall needs expert review.",
            "2026-04-08T15:00:00Z",
            "2026-04-08T15:10:00Z",
            "2026-04-08T15:00:00Z",
            "2026-04-08T15:10:00Z",
        ),
    )
    connection.execute(
        """
        INSERT INTO expert_review_packets (
          expert_review_packet_id, pipeline_run_id, packet_status, packet_path,
          job_posting_id, summary_excerpt, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "erp_chat_newer",
            "pr_chat_review_newer",
            "pending_expert_review",
            "ops/review-packets/pr_chat_review_newer/review_packet.md",
            "jp_chat_newer",
            "Discovery stalled after contact enrichment.",
            "2026-04-08T15:11:00Z",
        ),
    )
    connection.execute(
        """
        INSERT INTO pipeline_runs (
          pipeline_run_id, run_scope_type, run_status, current_stage, lead_id,
          job_posting_id, review_packet_status, run_summary, started_at, completed_at,
          created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "pr_background_older",
            "expert_requested_background_task",
            "failed",
            "investigation",
            None,
            None,
            "not_ready",
            "Investigate mailbox bounce pattern.",
            "2026-04-08T14:00:00Z",
            "2026-04-08T14:20:00Z",
            "2026-04-08T14:00:00Z",
            "2026-04-08T14:20:00Z",
        ),
    )
    connection.execute(
        """
        INSERT INTO pipeline_runs (
          pipeline_run_id, run_scope_type, run_status, current_stage, lead_id,
          job_posting_id, review_packet_status, run_summary, started_at, completed_at,
          created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "pr_background_newer",
            "expert_requested_background_task",
            "paused",
            "repair",
            None,
            None,
            "not_ready",
            "Reconcile launchctl bootstrap failure evidence.",
            "2026-04-08T15:05:00Z",
            None,
            "2026-04-08T15:05:00Z",
            "2026-04-08T15:21:00Z",
        ),
    )
    connection.execute(
        """
        INSERT INTO maintenance_change_batches (
          maintenance_change_batch_id, branch_name, scope_slug, status, approval_outcome,
          summary_path, json_path, validation_summary, failed_at, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "mcb_chat_newer",
            "maintenance/20260408-mcb-feedback-retry-hardening",
            "feedback-retry-hardening",
            "failed_validation",
            "needs_review",
            "ops/maintenance/mcb_chat_newer/summary.md",
            "ops/maintenance/mcb_chat_newer/summary.json",
            "Scoped retry checks passed but the full regression replay failed.",
            "2026-04-08T15:16:00Z",
            "2026-04-08T15:04:00Z",
        ),
    )
    connection.execute(
        """
        INSERT INTO agent_incidents (
          agent_incident_id, incident_type, severity, status, summary,
          pipeline_run_id, job_posting_id, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "ai_chat_newer",
            "email_discovery_stalled",
            "medium",
            "open",
            "Contact enrichment stalled without a verified working email.",
            "pr_chat_review_newer",
            "jp_chat_newer",
            "2026-04-08T15:12:00Z",
            "2026-04-08T15:18:00Z",
        ),
    )
    connection.commit()


def seed_chat_change_summary_state(connection: sqlite3.Connection) -> None:
    seed_chat_dashboard_state(connection)
    connection.execute(
        """
        INSERT INTO pipeline_runs (
          pipeline_run_id, run_scope_type, run_status, current_stage, lead_id,
          job_posting_id, review_packet_status, run_summary, started_at, completed_at,
          created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "pr_chat_reviewed",
            "job_posting",
            "completed",
            "agent_review",
            "ld_chat",
            "jp_chat",
            "reviewed",
            "An earlier review decision was completed.",
            "2026-04-08T13:40:00Z",
            "2026-04-08T13:59:00Z",
            "2026-04-08T13:40:00Z",
            "2026-04-08T13:59:00Z",
        ),
    )
    connection.execute(
        """
        INSERT INTO expert_review_packets (
          expert_review_packet_id, pipeline_run_id, packet_status, packet_path,
          job_posting_id, reviewed_at, summary_excerpt, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "erp_chat_reviewed",
            "pr_chat_reviewed",
            "reviewed",
            "ops/review-packets/pr_chat_reviewed/review_packet.md",
            "jp_chat",
            "2026-04-08T14:00:00Z",
            "Earlier review was resolved.",
            "2026-04-08T13:58:00Z",
        ),
    )
    connection.execute(
        """
        INSERT INTO expert_review_decisions (
          expert_review_decision_id, expert_review_packet_id, decision_type,
          decision_notes, override_event_id, decided_at, applied_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "erd_chat_reviewed",
            "erp_chat_reviewed",
            "approve_existing_plan",
            "Owner confirmed the earlier review packet.",
            None,
            "2026-04-08T14:00:00Z",
            "2026-04-08T14:00:00Z",
        ),
    )
    connection.execute(
        """
        INSERT INTO maintenance_change_batches (
          maintenance_change_batch_id, branch_name, scope_slug, status, approval_outcome,
          summary_path, json_path, validation_summary, failed_at, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "mcb_chat_post_review",
            "maintenance/20260408-mcb-chat-post-review-followup",
            "chat-post-review-followup",
            "failed_validation",
            "needs_review",
            "ops/maintenance/mcb_chat_post_review/summary.md",
            "ops/maintenance/mcb_chat_post_review/summary.json",
            "Full-project validation still failed after the post-review patch.",
            "2026-04-08T14:50:00Z",
            "2026-04-08T14:20:00Z",
        ),
    )
    connection.execute(
        """
        INSERT INTO override_events (
          override_event_id, object_type, object_id, component_stage, previous_value,
          new_value, override_reason, override_timestamp, override_by, lead_id,
          job_posting_id, contact_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "ovr_chat_post_review",
            "job_postings",
            "jp_chat",
            "posting_status",
            '{"posting_status":"requires_contacts"}',
            '{"posting_status":"ready_for_outreach"}',
            "Owner cleared the posting for outreach after reviewing the packet.",
            "2026-04-08T14:40:00Z",
            "owner",
            "ld_chat",
            "jp_chat",
            None,
        ),
    )
    connection.commit()


def test_materialize_supervisor_plist_script_renders_required_launchd_shape(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    create_minimal_project(project_root)

    result = run_script(
        "scripts/ops/materialize_supervisor_plist.py",
        "--project-root",
        str(project_root),
    )
    report = json.loads(result.stdout)

    plist_path = project_root / "ops" / "launchd" / "job-hunt-copilot-supervisor.plist"
    payload = plistlib.loads(plist_path.read_bytes())

    assert report["plist_path"] == str(plist_path)
    assert payload["Label"] == "com.jobhuntcopilot.supervisor"
    assert payload["RunAtLoad"] is True
    assert payload["StartInterval"] == 180
    assert payload["KeepAlive"] is False
    assert payload["WorkingDirectory"] == str(project_root)
    assert payload["ProgramArguments"] == [str(project_root / "bin" / "jhc-agent-cycle")]
    assert payload["StandardOutPath"] == str(project_root / "ops" / "logs" / "supervisor.stdout.log")
    assert payload["StandardErrorPath"] == str(project_root / "ops" / "logs" / "supervisor.stderr.log")
    assert plist_path.stat().st_mode & 0o777 == 0o644


def test_materialize_feedback_sync_plist_script_renders_required_launchd_shape(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    create_minimal_project(project_root)

    result = run_script(
        "scripts/ops/materialize_feedback_sync_plist.py",
        "--project-root",
        str(project_root),
    )
    report = json.loads(result.stdout)

    plist_path = project_root / "ops" / "launchd" / "job-hunt-copilot-feedback-sync.plist"
    payload = plistlib.loads(plist_path.read_bytes())

    assert report["plist_path"] == str(plist_path)
    assert payload["Label"] == "com.jobhuntcopilot.feedback-sync"
    assert payload["RunAtLoad"] is True
    assert payload["StartInterval"] == 300
    assert payload["KeepAlive"] is False
    assert payload["WorkingDirectory"] == str(project_root)
    assert payload["ProgramArguments"] == [str(project_root / "bin" / "jhc-feedback-sync-cycle")]
    assert payload["StandardOutPath"] == str(project_root / "ops" / "logs" / "feedback-sync.stdout.log")
    assert payload["StandardErrorPath"] == str(project_root / "ops" / "logs" / "feedback-sync.stderr.log")
    assert plist_path.stat().st_mode & 0o777 == 0o644


def test_control_agent_script_persists_running_and_stopped_modes(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    create_minimal_project(project_root)

    run_script(
        "scripts/ops/control_agent.py",
        "start",
        "--project-root",
        str(project_root),
        "--manual-command",
        "jhc-agent-start",
    )
    run_script(
        "scripts/ops/control_agent.py",
        "stop",
        "--project-root",
        str(project_root),
        "--manual-command",
        "jhc-agent-stop",
    )

    connection = connect_database(project_root / "job_hunt_copilot.db")
    control_rows = connection.execute(
        """
        SELECT control_key, control_value
        FROM agent_control_state
        WHERE control_key IN ('agent_enabled', 'agent_mode', 'pause_reason', 'paused_at', 'last_manual_command')
        ORDER BY control_key
        """
    ).fetchall()
    connection.close()

    assert dict(control_rows) == {
        "agent_enabled": "false",
        "agent_mode": "stopped",
        "last_manual_command": "jhc-agent-stop",
        "pause_reason": "",
        "paused_at": "",
    }


def test_control_agent_script_abandons_active_posting_and_retires_open_pipeline_run(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    create_minimal_project(project_root)
    run_script(
        "scripts/ops/control_agent.py",
        "status",
        "--project-root",
        str(project_root),
    )
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_posting_for_abandon(
        connection,
        posting_status="outreach_in_progress",
        run_status="in_progress",
        current_stage="sending",
    )
    connection.close()

    report = json.loads(
        run_script(
            "scripts/ops/control_agent.py",
            "abandon",
            "--project-root",
            str(project_root),
            "--job-posting-id",
            "jp_abandon",
            "--reason",
            "No longer pursuing this role.",
        ).stdout
    )

    assert report["status"] == "abandoned"
    assert report["job_posting"]["job_posting_id"] == "jp_abandon"
    assert report["job_posting"]["lead_id"] == "ld_abandon"
    assert report["job_posting"]["previous_status"] == "outreach_in_progress"
    assert report["job_posting"]["posting_status"] == "abandoned"
    assert report["job_posting"]["updated_at"].endswith("Z")
    assert report["retired_pipeline_runs"] == [
        {
            "pipeline_run_id": "pr_abandon",
            "previous_run_status": "in_progress",
            "new_run_status": "completed",
            "previous_stage": "sending",
            "new_stage": "abandoned",
        }
    ]
    assert report["state_transition_event_id"]
    assert report["override_event_id"]

    connection = connect_database(project_root / "job_hunt_copilot.db")
    posting_row = connection.execute(
        """
        SELECT posting_status, updated_at
        FROM job_postings
        WHERE job_posting_id = ?
        """,
        ("jp_abandon",),
    ).fetchone()
    pipeline_row = connection.execute(
        """
        SELECT run_status, current_stage, completed_at, run_summary
        FROM pipeline_runs
        WHERE pipeline_run_id = ?
        """,
        ("pr_abandon",),
    ).fetchone()
    state_transition_row = connection.execute(
        """
        SELECT object_type, object_id, stage, previous_state, new_state, transition_reason, caused_by
        FROM state_transition_events
        WHERE object_id = ?
        ORDER BY transition_timestamp DESC, state_transition_event_id DESC
        LIMIT 1
        """,
        ("jp_abandon",),
    ).fetchone()
    override_row = connection.execute(
        """
        SELECT object_type, object_id, component_stage, previous_value, new_value, override_reason, override_by
        FROM override_events
        WHERE object_id = ?
        ORDER BY override_timestamp DESC, override_event_id DESC
        LIMIT 1
        """,
        ("jp_abandon",),
    ).fetchone()
    connection.close()

    assert dict(posting_row) == {
        "posting_status": "abandoned",
        "updated_at": report["job_posting"]["updated_at"],
    }
    assert dict(pipeline_row) == {
        "run_status": "completed",
        "current_stage": "abandoned",
        "completed_at": report["job_posting"]["updated_at"],
        "run_summary": "The linked job_posting jp_abandon was explicitly abandoned by the expert.",
    }
    assert dict(state_transition_row) == {
        "object_type": "job_postings",
        "object_id": "jp_abandon",
        "stage": "posting_status",
        "previous_state": "outreach_in_progress",
        "new_state": "abandoned",
        "transition_reason": "No longer pursuing this role.",
        "caused_by": "local_runtime_control",
    }
    assert dict(override_row) == {
        "object_type": "job_postings",
        "object_id": "jp_abandon",
        "component_stage": "posting_status",
        "previous_value": "outreach_in_progress",
        "new_value": "abandoned",
        "override_reason": "No longer pursuing this role.",
        "override_by": "owner",
    }

    run_script(
        "scripts/ops/control_agent.py",
        "start",
        "--project-root",
        str(project_root),
        "--manual-command",
        "jhc-agent-start",
    )
    cycle_report = json.loads(
        run_script(
            "scripts/ops/run_supervisor_cycle.py",
            "--project-root",
            str(project_root),
        ).stdout
    )
    assert cycle_report["cycle"]["result"] == "no_work"


def test_control_agent_script_override_routes_posting_abandon_through_generic_interface(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    create_minimal_project(project_root)
    run_script(
        "scripts/ops/control_agent.py",
        "status",
        "--project-root",
        str(project_root),
    )
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_posting_for_abandon(
        connection,
        posting_status="requires_contacts",
        run_status="paused",
        current_stage="people_search",
    )
    connection.close()

    report = json.loads(
        run_script(
            "scripts/ops/control_agent.py",
            "override",
            "--project-root",
            str(project_root),
            "--object-type",
            "job_posting",
            "--object-id",
            "jp_abandon",
            "--new-value",
            "abandoned",
            "--reason",
            "Owner withdrew this posting from the active pipeline.",
        ).stdout
    )

    assert report["command"] == "override"
    assert report["status"] == "abandoned"
    assert report["override_target"] == {
        "object_type": "job_posting",
        "object_id": "jp_abandon",
        "component_stage": "posting_status",
        "new_value": "abandoned",
    }
    assert report["job_posting"]["posting_status"] == "abandoned"
    assert report["retired_pipeline_runs"] == [
        {
            "pipeline_run_id": "pr_abandon",
            "previous_run_status": "paused",
            "new_run_status": "completed",
            "previous_stage": "people_search",
            "new_stage": "abandoned",
        }
    ]


def test_control_agent_script_abandon_is_idempotent_for_existing_abandoned_posting(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    create_minimal_project(project_root)
    run_script(
        "scripts/ops/control_agent.py",
        "status",
        "--project-root",
        str(project_root),
    )
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_posting_for_abandon(connection, posting_status="abandoned")
    connection.close()

    report = json.loads(
        run_script(
            "scripts/ops/control_agent.py",
            "abandon",
            "--project-root",
            str(project_root),
            "--job-posting-id",
            "jp_abandon",
        ).stdout
    )

    assert report["status"] == "already_abandoned"
    assert report["job_posting"]["previous_status"] == "abandoned"
    assert report["job_posting"]["posting_status"] == "abandoned"
    assert report["retired_pipeline_runs"] == []
    assert report["state_transition_event_id"] is None
    assert report["override_event_id"] is None

    connection = connect_database(project_root / "job_hunt_copilot.db")
    transition_count = connection.execute(
        "SELECT COUNT(*) FROM state_transition_events WHERE object_id = ?",
        ("jp_abandon",),
    ).fetchone()[0]
    override_count = connection.execute(
        "SELECT COUNT(*) FROM override_events WHERE object_id = ?",
        ("jp_abandon",),
    ).fetchone()[0]
    connection.close()

    assert transition_count == 0
    assert override_count == 0


def test_control_agent_script_override_routes_tailoring_review_override(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    create_minimal_project(project_root)
    run_script(
        "scripts/ops/control_agent.py",
        "status",
        "--project-root",
        str(project_root),
    )
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_posting_for_tailoring_override(connection)
    seed_pending_review_tailoring_run(
        connection,
        paths,
        job_posting_id="jp_tailoring_override",
        company_name="Acme Robotics",
        role_title="Staff Platform Engineer",
        resume_tailoring_run_id="rtr_tailoring_override",
        timestamp="2026-04-08T09:05:00Z",
    )
    record_tailoring_review_decision(
        connection,
        paths,
        job_posting_id="jp_tailoring_override",
        decision_type=RESUME_REVIEW_STATUS_REJECTED,
        decision_notes="Agent requested another revision before outreach.",
        timestamp="2026-04-08T09:10:00Z",
    )
    connection.close()

    report = json.loads(
        run_script(
            "scripts/ops/control_agent.py",
            "override",
            "--project-root",
            str(project_root),
            "--object-type",
            "tailoring_review",
            "--object-id",
            "jp_tailoring_override",
            "--new-value",
            "approved",
            "--reason",
            "Owner approved the tailored output for contact discovery.",
        ).stdout
    )

    assert report["command"] == "override"
    assert report["status"] == "completed"
    assert report["override_target"] == {
        "object_type": "tailoring_review",
        "object_id": "jp_tailoring_override",
        "component_stage": "resume_review_status",
        "new_value": "approved",
    }
    assert report["job_posting"] == {
        "job_posting_id": "jp_tailoring_override",
        "posting_status": "requires_contacts",
    }
    assert report["resume_tailoring_run"]["resume_tailoring_run_id"] == "rtr_tailoring_override"
    assert report["resume_tailoring_run"]["resume_review_status"] == "approved"
    assert report["override_event_id"]
    assert report["review_artifact"]["artifact_type"] == "tailoring_review_decision"

    connection = connect_database(project_root / "job_hunt_copilot.db")
    posting_row = connection.execute(
        """
        SELECT posting_status
        FROM job_postings
        WHERE job_posting_id = ?
        """,
        ("jp_tailoring_override",),
    ).fetchone()
    run_row = connection.execute(
        """
        SELECT resume_review_status
        FROM resume_tailoring_runs
        WHERE resume_tailoring_run_id = ?
        """,
        ("rtr_tailoring_override",),
    ).fetchone()
    override_row = connection.execute(
        """
        SELECT object_type, object_id, component_stage, override_reason
        FROM override_events
        WHERE override_event_id = ?
        """,
        (report["override_event_id"],),
    ).fetchone()
    connection.close()

    assert dict(posting_row) == {"posting_status": "requires_contacts"}
    assert dict(run_row) == {"resume_review_status": "approved"}
    assert dict(override_row) == {
        "object_type": "resume_tailoring_runs",
        "object_id": "rtr_tailoring_override",
        "component_stage": "resume_review_status",
        "override_reason": "Owner approved the tailored output for contact discovery.",
    }


def test_control_agent_script_override_rejects_redundant_tailoring_decision_without_side_effects(
    tmp_path,
):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    create_minimal_project(project_root)
    run_script(
        "scripts/ops/control_agent.py",
        "status",
        "--project-root",
        str(project_root),
    )
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_posting_for_tailoring_override(connection)
    seed_pending_review_tailoring_run(
        connection,
        paths,
        job_posting_id="jp_tailoring_override",
        company_name="Acme Robotics",
        role_title="Staff Platform Engineer",
        resume_tailoring_run_id="rtr_tailoring_override",
        timestamp="2026-04-08T09:05:00Z",
    )
    record_tailoring_review_decision(
        connection,
        paths,
        job_posting_id="jp_tailoring_override",
        decision_type=RESUME_REVIEW_STATUS_APPROVED,
        decision_notes="Agent approved the output for outreach bootstrap.",
        timestamp="2026-04-08T09:10:00Z",
    )
    override_count_before = connection.execute(
        "SELECT COUNT(*) FROM override_events"
    ).fetchone()[0]
    connection.close()

    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts/ops/control_agent.py"),
            "override",
            "--project-root",
            str(project_root),
            "--object-type",
            "tailoring_review",
            "--object-id",
            "jp_tailoring_override",
            "--new-value",
            "approved",
            "--reason",
            "Owner still approves the existing reviewed outcome.",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.strip() == "Tailoring review override must change the existing review decision."

    connection = connect_database(project_root / "job_hunt_copilot.db")
    override_count_after = connection.execute("SELECT COUNT(*) FROM override_events").fetchone()[0]
    run_row = connection.execute(
        """
        SELECT resume_review_status
        FROM resume_tailoring_runs
        WHERE resume_tailoring_run_id = ?
        """,
        ("rtr_tailoring_override",),
    ).fetchone()
    connection.close()

    assert override_count_after == override_count_before
    assert dict(run_row) == {"resume_review_status": "approved"}


def test_control_agent_script_abandon_rejects_terminal_posting_status_without_side_effects(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    create_minimal_project(project_root)
    run_script(
        "scripts/ops/control_agent.py",
        "status",
        "--project-root",
        str(project_root),
    )
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_posting_for_abandon(connection, posting_status="completed")
    connection.close()

    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts/ops/control_agent.py"),
            "abandon",
            "--project-root",
            str(project_root),
            "--job-posting-id",
            "jp_abandon",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.strip() == (
        "Only non-terminal active postings may be abandoned; "
        "job_posting 'jp_abandon' is at posting_status='completed'."
    )

    connection = connect_database(project_root / "job_hunt_copilot.db")
    posting_row = connection.execute(
        """
        SELECT posting_status
        FROM job_postings
        WHERE job_posting_id = ?
        """,
        ("jp_abandon",),
    ).fetchone()
    transition_count = connection.execute(
        "SELECT COUNT(*) FROM state_transition_events WHERE object_id = ?",
        ("jp_abandon",),
    ).fetchone()[0]
    override_count = connection.execute(
        "SELECT COUNT(*) FROM override_events WHERE object_id = ?",
        ("jp_abandon",),
    ).fetchone()[0]
    connection.close()

    assert dict(posting_row) == {"posting_status": "completed"}
    assert transition_count == 0
    assert override_count == 0


def test_control_agent_script_guidance_defaults_to_live_future_scope_and_persists_lineage(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    create_minimal_project(project_root)
    run_script(
        "scripts/ops/control_agent.py",
        "status",
        "--project-root",
        str(project_root),
    )
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_posting_for_guidance(
        connection,
        lead_id="ld_guidance_primary",
        job_posting_id="jp_guidance_primary",
        company_name="Acme Robotics",
        role_title="Staff Platform Engineer",
    )
    seed_posting_for_guidance(
        connection,
        lead_id="ld_guidance_reuse",
        job_posting_id="jp_guidance_reuse",
        company_name="Beta Labs",
        role_title="ML Platform Engineer",
        timestamp="2026-04-08T09:30:00Z",
    )
    connection.close()

    primary_report = json.loads(
        run_script(
            "scripts/ops/control_agent.py",
            "guidance",
            "--project-root",
            str(project_root),
            "--object-type",
            "job_posting",
            "--object-id",
            "jp_guidance_primary",
            "--component-stage",
            "sending_policy",
            "--directive-key",
            "duplicate_send_handling",
            "--directive-value",
            "escalate_before_repeat_send",
            "--reason",
            "Treat repeat-send ambiguity as expert-review-only.",
        ).stdout
    )
    duplicate_report = json.loads(
        run_script(
            "scripts/ops/control_agent.py",
            "guidance",
            "--project-root",
            str(project_root),
            "--object-type",
            "job_posting",
            "--object-id",
            "jp_guidance_primary",
            "--component-stage",
            "sending_policy",
            "--directive-key",
            "duplicate_send_handling",
            "--directive-value",
            "escalate_before_repeat_send",
            "--reason",
            "Treat repeat-send ambiguity as expert-review-only.",
        ).stdout
    )
    reuse_report = json.loads(
        run_script(
            "scripts/ops/control_agent.py",
            "guidance",
            "--project-root",
            str(project_root),
            "--object-type",
            "job_posting",
            "--object-id",
            "jp_guidance_reuse",
            "--component-stage",
            "sending_policy",
            "--directive-key",
            "duplicate_send_handling",
            "--directive-value",
            "escalate_before_repeat_send",
            "--reason",
            "Reuse the existing repeat-send safety policy for similar postings.",
            "--source-override-event-id",
            primary_report["guidance"]["override_event_id"],
        ).stdout
    )

    assert primary_report["status"] == "guidance_persisted"
    assert primary_report["guidance"]["object_type"] == "job_postings"
    assert primary_report["guidance"]["guidance_scope"] == "current_and_similar_future"
    assert primary_report["guidance"]["applies_to_similar_future_cases"] is True
    assert (
        primary_report["guidance"]["source_guidance_override_event_id"]
        == primary_report["guidance"]["override_event_id"]
    )
    assert primary_report["conflict"] is None

    assert duplicate_report["status"] == "already_live"
    assert (
        duplicate_report["guidance"]["override_event_id"]
        == primary_report["guidance"]["override_event_id"]
    )

    assert reuse_report["status"] == "guidance_persisted"
    assert reuse_report["guidance"]["object_id"] == "jp_guidance_reuse"
    assert (
        reuse_report["guidance"]["source_guidance_override_event_id"]
        == primary_report["guidance"]["override_event_id"]
    )

    connection = connect_database(project_root / "job_hunt_copilot.db")
    rows = connection.execute(
        """
        SELECT object_id, new_value
        FROM override_events
        WHERE component_stage = 'sending_policy'
        ORDER BY override_timestamp ASC, override_event_id ASC
        """
    ).fetchall()
    connection.close()

    assert len(rows) == 2
    primary_payload = json.loads(rows[0]["new_value"])
    reuse_payload = json.loads(rows[1]["new_value"])
    assert primary_payload["directive_key"] == "duplicate_send_handling"
    assert primary_payload["directive_value"] == "escalate_before_repeat_send"
    assert primary_payload["guidance_scope"] == "current_and_similar_future"
    assert primary_payload["source_guidance_override_event_id"] == primary_report["guidance"]["override_event_id"]
    assert reuse_payload["source_guidance_override_event_id"] == primary_report["guidance"]["override_event_id"]


def test_control_agent_script_guidance_conflict_pauses_agent_and_creates_reviewable_incident(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    create_minimal_project(project_root)
    run_script(
        "scripts/ops/control_agent.py",
        "start",
        "--project-root",
        str(project_root),
        "--manual-command",
        "jhc-agent-start",
    )
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_posting_for_guidance(
        connection,
        lead_id="ld_guidance_conflict_a",
        job_posting_id="jp_guidance_conflict_a",
        company_name="Acme Robotics",
        role_title="Staff Platform Engineer",
    )
    seed_posting_for_guidance(
        connection,
        lead_id="ld_guidance_conflict_b",
        job_posting_id="jp_guidance_conflict_b",
        company_name="Acme Robotics",
        role_title="Senior Reliability Engineer",
        timestamp="2026-04-08T09:35:00Z",
    )
    connection.close()

    run_script(
        "scripts/ops/control_agent.py",
        "guidance",
        "--project-root",
        str(project_root),
        "--object-type",
        "job_posting",
        "--object-id",
        "jp_guidance_conflict_a",
        "--component-stage",
        "sending_policy",
        "--directive-key",
        "duplicate_send_handling",
        "--directive-value",
        "escalate_before_repeat_send",
        "--reason",
        "Keep repeat-send ambiguity review-only.",
    )
    report = json.loads(
        run_script(
            "scripts/ops/control_agent.py",
            "guidance",
            "--project-root",
            str(project_root),
            "--object-type",
            "job_posting",
            "--object-id",
            "jp_guidance_conflict_b",
            "--component-stage",
            "sending_policy",
            "--directive-key",
            "duplicate_send_handling",
            "--directive-value",
            "allow_single_retry_after_owner_confirmation",
            "--reason",
            "Use a narrower resend policy for similar future cases.",
        ).stdout
    )

    assert report["status"] == "clarification_required"
    assert report["guidance"]["override_event_id"]
    assert report["conflict"] is not None
    assert report["conflict"]["clarification_required"] is True
    assert report["conflict"]["incident_id"]
    assert report["conflict"]["conflicting_override_event_ids"]
    assert report["control_state"]["agent_mode"] == "paused"
    assert report["control_state"]["pause_reason"] == "expert_guidance_conflict:duplicate_send_handling"

    connection = connect_database(project_root / "job_hunt_copilot.db")
    incident_row = connection.execute(
        """
        SELECT incident_type, severity, status, summary, job_posting_id
        FROM agent_incidents
        WHERE agent_incident_id = ?
        """,
        (report["conflict"]["incident_id"],),
    ).fetchone()
    guidance_row = connection.execute(
        """
        SELECT new_value
        FROM override_events
        WHERE override_event_id = ?
        """,
        (report["guidance"]["override_event_id"],),
    ).fetchone()
    review_queue = build_chat_review_queue(
        connection,
        project_root=project_root,
        max_items_per_group=5,
    )
    connection.close()

    assert dict(incident_row) == {
        "incident_type": "expert_guidance_conflict",
        "severity": "high",
        "status": "open",
        "summary": "Conflicting standing expert guidance requires clarification before autonomous progression resumes.",
        "job_posting_id": "jp_guidance_conflict_b",
    }
    assert json.loads(guidance_row["new_value"])["directive_value"] == (
        "allow_single_retry_after_owner_confirmation"
    )
    incident_group = next(
        group for group in review_queue["groups"] if group["group_id"] == "open_incidents"
    )
    assert incident_group["total_count"] == 1
    assert incident_group["items"][0]["headline"] == (
        "Acme Robotics / Senior Reliability Engineer"
    )
    assert incident_group["items"][0]["summary"] == (
        "high: Conflicting standing expert guidance requires clarification before autonomous progression resumes."
    )


def test_control_agent_script_clarify_guidance_is_idempotent_and_preserves_reviewable_pause(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    create_minimal_project(project_root)
    run_script(
        "scripts/ops/control_agent.py",
        "start",
        "--project-root",
        str(project_root),
        "--manual-command",
        "jhc-agent-start",
    )
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_posting_for_guidance(
        connection,
        lead_id="ld_guidance_uncertain",
        job_posting_id="jp_guidance_uncertain",
        company_name="Gamma Systems",
        role_title="Principal Data Engineer",
    )
    connection.close()

    first_report = json.loads(
        run_script(
            "scripts/ops/control_agent.py",
            "clarify-guidance",
            "--project-root",
            str(project_root),
            "--object-type",
            "job_posting",
            "--object-id",
            "jp_guidance_uncertain",
            "--component-stage",
            "people_search_policy",
            "--directive-key",
            "contact_reuse",
            "--directive-value",
            "reuse_only_if_same_hiring_manager_chain",
            "--reason",
            "The agent is not confident this future posting is similar enough to reuse the standing contact policy.",
        ).stdout
    )
    second_report = json.loads(
        run_script(
            "scripts/ops/control_agent.py",
            "clarify-guidance",
            "--project-root",
            str(project_root),
            "--object-type",
            "job_posting",
            "--object-id",
            "jp_guidance_uncertain",
            "--component-stage",
            "people_search_policy",
            "--directive-key",
            "contact_reuse",
            "--directive-value",
            "reuse_only_if_same_hiring_manager_chain",
            "--reason",
            "The agent is not confident this future posting is similar enough to reuse the standing contact policy.",
        ).stdout
    )

    assert first_report["status"] == "clarification_required"
    assert first_report["clarification_request"]["request_kind"] == "uncertainty"
    assert first_report["control_state"]["agent_mode"] == "paused"
    assert first_report["control_state"]["pause_reason"] == "expert_guidance_clarification"
    assert (
        second_report["clarification_request"]["incident_id"]
        == first_report["clarification_request"]["incident_id"]
    )

    connection = connect_database(project_root / "job_hunt_copilot.db")
    incident_count = connection.execute(
        """
        SELECT COUNT(*)
        FROM agent_incidents
        WHERE incident_type = 'expert_guidance_clarification'
        """
    ).fetchone()[0]
    review_queue = build_chat_review_queue(
        connection,
        project_root=project_root,
        max_items_per_group=5,
    )
    connection.close()

    assert incident_count == 1
    incident_group = next(
        group for group in review_queue["groups"] if group["group_id"] == "open_incidents"
    )
    assert incident_group["total_count"] == 1
    assert incident_group["items"][0]["headline"] == (
        "Gamma Systems / Principal Data Engineer"
    )
    assert incident_group["items"][0]["summary"] == (
        "high: Expert clarification is required before this standing guidance can be reused safely."
    )


def test_run_supervisor_cycle_script_records_no_work_launchd_cycle(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    create_minimal_project(project_root)

    run_script(
        "scripts/ops/control_agent.py",
        "start",
        "--project-root",
        str(project_root),
        "--manual-command",
        "jhc-agent-start",
    )
    result = run_script(
        "scripts/ops/run_supervisor_cycle.py",
        "--project-root",
        str(project_root),
    )
    report = json.loads(result.stdout)

    assert report["cycle"]["trigger_type"] == "launchd_heartbeat"
    assert report["cycle"]["scheduler_name"] == "launchd"
    assert report["cycle"]["result"] == "no_work"
    assert report["runtime_pack"]["agent_mode"] == "running"
    assert (project_root / "ops" / "agent" / "identity.yaml").exists()

    connection = connect_database(project_root / "job_hunt_copilot.db")
    cycle_row = connection.execute(
        """
        SELECT trigger_type, scheduler_name, result
        FROM supervisor_cycles
        ORDER BY started_at DESC, supervisor_cycle_id DESC
        LIMIT 1
        """
    ).fetchone()
    connection.close()

    assert dict(cycle_row) == {
        "trigger_type": "launchd_heartbeat",
        "scheduler_name": "launchd",
        "result": "no_work",
    }


def test_execute_supervisor_heartbeat_reports_maintenance_batch_when_dependencies_are_injected(
    tmp_path,
    monkeypatch,
):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    create_minimal_project(project_root)
    initialize_git_repository(project_root)

    def fake_run_system_command(args: list[str]) -> subprocess.CompletedProcess[str]:
        if args == ["pmset", "-g", "uuid"]:
            return make_command_result(stdout="TEST-UUID\n")
        if args == ["pmset", "-g", "log"]:
            return make_command_result(stdout="")
        raise AssertionError(f"Unexpected system command: {args!r}")

    monkeypatch.setattr(local_runtime, "_run_system_command", fake_run_system_command)

    run_script(
        "scripts/ops/control_agent.py",
        "start",
        "--project-root",
        str(project_root),
        "--manual-command",
        "jhc-agent-start",
    )
    report = execute_supervisor_heartbeat(
        project_root=project_root,
        started_at="2026-04-09T02:00:00Z",
        action_dependencies=build_test_maintenance_dependencies(),
    )

    assert report["cycle"]["result"] == "success"
    assert report["selected_work"]["work_type"] == "maintenance_cycle"
    assert report["selected_work"]["action_id"] == "run_daily_maintenance"
    assert report["maintenance_change_batch_id"] is not None


def test_review_maintenance_command_approves_and_merges_validated_batch(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    create_minimal_project(project_root)
    initialize_git_repository(project_root)
    paths = ProjectPaths.from_root(project_root)

    run_script(
        "scripts/ops/control_agent.py",
        "status",
        "--project-root",
        str(project_root),
    )

    connection = connect_database(project_root / "job_hunt_copilot.db")
    batch_execution = run_daily_maintenance_cycle(
        connection,
        paths,
        current_time="2026-04-09T02:10:00Z",
        local_timezone="UTC",
        dependencies=build_test_maintenance_dependencies().maintenance_dependencies,
    )
    connection.close()

    report = json.loads(
        run_script(
            "scripts/ops/control_agent.py",
            "review-maintenance",
            "--project-root",
            str(project_root),
            "--maintenance-change-batch-id",
            batch_execution.batch.maintenance_change_batch_id,
            "--decision",
            "approve",
            "--reason",
            "Owner approved the bounded maintenance batch.",
        ).stdout
    )

    assert report["command"] == "review-maintenance"
    assert report["decision"] == "approve"
    assert report["maintenance_batch"]["status"] == "merged"
    assert report["maintenance_batch"]["approval_outcome"] == "approved"
    assert report["maintenance_batch"]["merged_commit_sha"] is not None
    assert report["maintenance_batch"]["merge_commit_message"].startswith(
        f"merge(maintenance): {batch_execution.batch.maintenance_change_batch_id} "
    )


def test_review_maintenance_command_rejects_without_merging(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    create_minimal_project(project_root)
    initialize_git_repository(project_root)
    paths = ProjectPaths.from_root(project_root)

    run_script(
        "scripts/ops/control_agent.py",
        "status",
        "--project-root",
        str(project_root),
    )

    connection = connect_database(project_root / "job_hunt_copilot.db")
    batch_execution = run_daily_maintenance_cycle(
        connection,
        paths,
        current_time="2026-04-09T02:20:00Z",
        local_timezone="UTC",
        dependencies=build_test_maintenance_dependencies().maintenance_dependencies,
    )
    connection.close()

    report = json.loads(
        run_script(
            "scripts/ops/control_agent.py",
            "review-maintenance",
            "--project-root",
            str(project_root),
            "--maintenance-change-batch-id",
            batch_execution.batch.maintenance_change_batch_id,
            "--decision",
            "reject",
            "--reason",
            "Owner wants to inspect the retained branch first.",
        ).stdout
    )

    assert report["command"] == "review-maintenance"
    assert report["decision"] == "reject"
    assert report["maintenance_batch"]["status"] == "retained_for_review"
    assert report["maintenance_batch"]["approval_outcome"] == "not_approved"
    assert report["maintenance_batch"]["merged_commit_sha"] is None


def test_execute_supervisor_heartbeat_prefers_pmset_events_for_recovery_detection(
    tmp_path,
    monkeypatch,
):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    create_minimal_project(project_root)

    run_script(
        "scripts/ops/control_agent.py",
        "start",
        "--project-root",
        str(project_root),
        "--manual-command",
        "jhc-agent-start",
    )

    def install_pmset_responses(*, log_text: str) -> None:
        def fake_run_system_command(args: list[str]) -> subprocess.CompletedProcess[str]:
            if args == ["pmset", "-g", "uuid"]:
                return make_command_result(stdout="6A16BAEF-7D6D-4E47-AEEE-19209976BB89\n")
            if args == ["pmset", "-g", "log"]:
                return make_command_result(stdout=log_text)
            raise AssertionError(f"Unexpected system command: {args!r}")

        monkeypatch.setattr(local_runtime, "_run_system_command", fake_run_system_command)

    install_pmset_responses(log_text="")
    execute_supervisor_heartbeat(
        project_root=project_root,
        started_at="2026-04-07T09:00:00Z",
    )

    install_pmset_responses(
        log_text=(
            "2026-04-07 01:55:00 -0700 Assertions PID 123(Test) Created Noop\n"
            "2026-04-07 02:10:00 -0700 Wake from Normal Sleep [CDNVA] : due to EC.LidOpen\n"
        )
    )
    report = execute_supervisor_heartbeat(
        project_root=project_root,
        started_at="2026-04-07T09:15:00Z",
    )

    connection = connect_database(project_root / "job_hunt_copilot.db")
    cycle_row = connection.execute(
        """
        SELECT sleep_wake_detection_method, sleep_wake_event_ref
        FROM supervisor_cycles
        ORDER BY started_at DESC, supervisor_cycle_id DESC
        LIMIT 1
        """
    ).fetchone()
    control_rows = connection.execute(
        """
        SELECT control_key, control_value
        FROM agent_control_state
        WHERE control_key IN (
          'last_sleep_wake_check_at',
          'last_seen_sleep_event_at',
          'last_seen_wake_event_at',
          'last_sleep_wake_event_ref'
        )
        ORDER BY control_key
        """
    ).fetchall()
    connection.close()

    assert report["cycle"]["sleep_wake_detection_method"] == "pmset_log"
    assert report["sleep_wake_recovery_context"] == {
        "detection_method": "pmset_log",
        "event_type": "Wake",
        "event_timestamp": "2026-04-07T09:10:00Z",
        "event_ref": "pmset:6A16BAEF-7D6D-4E47-AEEE-19209976BB89:wake:2026-04-07T09:10:00Z",
        "pmset_uuid": "6A16BAEF-7D6D-4E47-AEEE-19209976BB89",
        "source_line": "2026-04-07 02:10:00 -0700 Wake from Normal Sleep [CDNVA] : due to EC.LidOpen",
    }
    assert dict(cycle_row) == {
        "sleep_wake_detection_method": "pmset_log",
        "sleep_wake_event_ref": "pmset:6A16BAEF-7D6D-4E47-AEEE-19209976BB89:wake:2026-04-07T09:10:00Z",
    }
    assert dict(control_rows) == {
        "last_seen_sleep_event_at": "",
        "last_seen_wake_event_at": "2026-04-07T09:10:00Z",
        "last_sleep_wake_check_at": "2026-04-07T09:15:00Z",
        "last_sleep_wake_event_ref": "pmset:6A16BAEF-7D6D-4E47-AEEE-19209976BB89:wake:2026-04-07T09:10:00Z",
    }


def test_execute_supervisor_heartbeat_uses_gap_fallback_when_pmset_has_no_new_events(
    tmp_path,
    monkeypatch,
):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    create_minimal_project(project_root)

    run_script(
        "scripts/ops/control_agent.py",
        "start",
        "--project-root",
        str(project_root),
        "--manual-command",
        "jhc-agent-start",
    )

    def fake_run_system_command(args: list[str]) -> subprocess.CompletedProcess[str]:
        if args == ["pmset", "-g", "uuid"]:
            return make_command_result(stdout="6A16BAEF-7D6D-4E47-AEEE-19209976BB89\n")
        if args == ["pmset", "-g", "log"]:
            return make_command_result(stdout="")
        raise AssertionError(f"Unexpected system command: {args!r}")

    monkeypatch.setattr(local_runtime, "_run_system_command", fake_run_system_command)

    execute_supervisor_heartbeat(
        project_root=project_root,
        started_at="2026-04-07T09:00:00Z",
    )
    report = execute_supervisor_heartbeat(
        project_root=project_root,
        started_at="2026-04-07T10:45:00Z",
    )

    connection = connect_database(project_root / "job_hunt_copilot.db")
    cycle_row = connection.execute(
        """
        SELECT sleep_wake_detection_method, sleep_wake_event_ref
        FROM supervisor_cycles
        ORDER BY started_at DESC, supervisor_cycle_id DESC
        LIMIT 1
        """
    ).fetchone()
    control_rows = connection.execute(
        """
        SELECT control_key, control_value
        FROM agent_control_state
        WHERE control_key IN (
          'last_sleep_wake_check_at',
          'last_seen_sleep_event_at',
          'last_seen_wake_event_at',
          'last_sleep_wake_event_ref'
        )
        ORDER BY control_key
        """
    ).fetchall()
    connection.close()

    assert report["cycle"]["sleep_wake_detection_method"] == "gap_fallback"
    assert report["sleep_wake_recovery_context"] == {
        "detection_method": "gap_fallback",
        "event_type": "GapRecovery",
        "event_timestamp": "2026-04-07T10:45:00Z",
        "event_ref": "gap_fallback:2026-04-07T09:00:00Z->2026-04-07T10:45:00Z",
        "reference_cycle_at": "2026-04-07T09:00:00Z",
        "gap_seconds": 6300,
        "fallback_gap_hours": 1,
    }
    assert dict(cycle_row) == {
        "sleep_wake_detection_method": "gap_fallback",
        "sleep_wake_event_ref": "gap_fallback:2026-04-07T09:00:00Z->2026-04-07T10:45:00Z",
    }
    assert dict(control_rows) == {
        "last_seen_sleep_event_at": "",
        "last_seen_wake_event_at": "",
        "last_sleep_wake_check_at": "2026-04-07T10:45:00Z",
        "last_sleep_wake_event_ref": "gap_fallback:2026-04-07T09:00:00Z->2026-04-07T10:45:00Z",
    }


def test_run_feedback_sync_script_records_launchd_feedback_sync_run(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    create_minimal_project(project_root)

    run_script(
        "scripts/ops/control_agent.py",
        "start",
        "--project-root",
        str(project_root),
        "--manual-command",
        "jhc-agent-start",
    )
    result = run_script(
        "scripts/ops/run_feedback_sync.py",
        "--project-root",
        str(project_root),
        "--current-time",
        "2026-04-07T10:10:00Z",
    )
    report = json.loads(result.stdout)

    assert report["status"] == "completed"
    assert report["feedback_sync"]["scheduler_name"] == "job-hunt-copilot-feedback-sync"
    assert report["feedback_sync"]["scheduler_type"] == "launchd"
    assert report["feedback_sync"]["observation_scope"] == "delayed_feedback_sync"
    assert report["feedback_sync"]["messages_examined"] == 0

    connection = connect_database(project_root / "job_hunt_copilot.db")
    sync_row = connection.execute(
        """
        SELECT scheduler_name, scheduler_type, observation_scope, result, messages_examined
        FROM feedback_sync_runs
        ORDER BY started_at DESC, feedback_sync_run_id DESC
        LIMIT 1
        """
    ).fetchone()
    connection.close()

    assert dict(sync_row) == {
        "scheduler_name": "job-hunt-copilot-feedback-sync",
        "scheduler_type": "launchd",
        "observation_scope": "delayed_feedback_sync",
        "result": "success",
        "messages_examined": 0,
    }


def test_execute_delayed_feedback_sync_persists_bounce_after_send_session_end(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    create_minimal_project(project_root)

    run_script(
        "scripts/ops/control_agent.py",
        "start",
        "--project-root",
        str(project_root),
        "--manual-command",
        "jhc-agent-start",
    )
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_feedback_candidate(connection)
    observer = FakeMailboxFeedbackObserver(
        signals=[
            DeliveryFeedbackSignal(
                signal_type="bounced",
                event_timestamp="2026-04-07T10:08:00Z",
                delivery_tracking_id="delivery-msg_feedback",
            )
        ]
    )

    report = execute_delayed_feedback_sync(
        project_root=project_root,
        current_time="2026-04-07T10:10:00Z",
        observer=observer,
    )

    assert observer.poll_calls == [
        {
            "message_ids": ["msg_feedback"],
            "current_time": "2026-04-07T10:10:00Z",
            "observation_scope": "delayed_feedback_sync",
        }
    ]
    assert report["status"] == "completed"
    assert report["feedback_sync"]["bounce_events_written"] == 1

    event_row = connection.execute(
        """
        SELECT outreach_message_id, event_state, event_timestamp
        FROM delivery_feedback_events
        WHERE outreach_message_id = ?
        """,
        ("msg_feedback",),
    ).fetchone()
    sync_row = connection.execute(
        """
        SELECT scheduler_name, scheduler_type, observation_scope, result, bounce_events_written
        FROM feedback_sync_runs
        ORDER BY started_at DESC, feedback_sync_run_id DESC
        LIMIT 1
        """
    ).fetchone()
    connection.close()

    assert dict(event_row) == {
        "outreach_message_id": "msg_feedback",
        "event_state": "bounced",
        "event_timestamp": "2026-04-07T10:08:00Z",
    }
    assert dict(sync_row) == {
        "scheduler_name": "job-hunt-copilot-feedback-sync",
        "scheduler_type": "launchd",
        "observation_scope": "delayed_feedback_sync",
        "result": "success",
        "bounce_events_written": 1,
    }


def test_chat_session_script_pauses_running_agent_and_explicit_close_resumes_it(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    create_minimal_project(project_root)

    run_script(
        "scripts/ops/control_agent.py",
        "start",
        "--project-root",
        str(project_root),
        "--manual-command",
        "jhc-agent-start",
    )
    begin_report = json.loads(
        run_script(
            "scripts/ops/chat_session.py",
            "begin",
            "--project-root",
            str(project_root),
        ).stdout
    )
    end_report = json.loads(
        run_script(
            "scripts/ops/chat_session.py",
            "end",
            "--project-root",
            str(project_root),
            "--session-id",
            begin_report["session_id"],
            "--exit-mode",
            "explicit_close",
        ).stdout
    )

    connection = connect_database(project_root / "job_hunt_copilot.db")
    control_rows = connection.execute(
        """
        SELECT control_key, control_value
        FROM agent_control_state
        WHERE control_key IN (
            'active_chat_session_id',
            'agent_enabled',
            'agent_mode',
            'chat_resume_on_close',
            'last_chat_ended_at',
            'last_chat_exit_mode',
            'last_chat_started_at',
            'pause_reason',
            'paused_at'
        )
        ORDER BY control_key
        """
    ).fetchall()
    connection.close()
    log_lines = (project_root / "ops" / "logs" / "chat-sessions.jsonl").read_text(encoding="utf-8").splitlines()

    assert begin_report["status"] == "started"
    assert begin_report["resume_on_close"] is True
    assert begin_report["control_state"]["agent_mode"] == "paused"
    assert begin_report["control_state"]["pause_reason"] == "expert_interaction"
    assert end_report["status"] == "ended"
    assert end_report["resumed_agent"] is True
    assert end_report["control_state"]["agent_mode"] == "running"

    assert dict(control_rows) == {
        "active_chat_session_id": "",
        "agent_enabled": "true",
        "agent_mode": "running",
        "chat_resume_on_close": "false",
        "last_chat_ended_at": end_report["ended_at"],
        "last_chat_exit_mode": "explicit_close",
        "last_chat_started_at": begin_report["started_at"],
        "pause_reason": "",
        "paused_at": "",
    }
    assert len(log_lines) == 2
    assert json.loads(log_lines[0])["event"] == "begin"
    assert json.loads(log_lines[1])["event"] == "end"


def test_chat_session_script_rejects_second_active_session_without_mutating_active_session(
    tmp_path,
):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    create_minimal_project(project_root)

    run_script(
        "scripts/ops/control_agent.py",
        "start",
        "--project-root",
        str(project_root),
        "--manual-command",
        "jhc-agent-start",
    )
    first_begin = json.loads(
        run_script(
            "scripts/ops/chat_session.py",
            "begin",
            "--project-root",
            str(project_root),
        ).stdout
    )

    second_begin = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts/ops/chat_session.py"),
            "begin",
            "--project-root",
            str(project_root),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    connection = connect_database(project_root / "job_hunt_copilot.db")
    control_rows = connection.execute(
        """
        SELECT control_key, control_value
        FROM agent_control_state
        WHERE control_key IN (
            'active_chat_session_id',
            'agent_enabled',
            'agent_mode',
            'chat_resume_on_close',
            'pause_reason'
        )
        ORDER BY control_key
        """
    ).fetchall()
    connection.close()
    log_lines = (project_root / "ops" / "logs" / "chat-sessions.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()

    assert second_begin.returncode == 2
    assert second_begin.stdout == ""
    assert second_begin.stderr.strip() == (
        "Another jhc-chat session is already active: "
        f"{first_begin['session_id']}"
    )
    assert dict(control_rows) == {
        "active_chat_session_id": first_begin["session_id"],
        "agent_enabled": "true",
        "agent_mode": "paused",
        "chat_resume_on_close": "true",
        "pause_reason": "expert_interaction",
    }
    assert len(log_lines) == 1
    assert json.loads(log_lines[0])["event"] == "begin"


def test_chat_session_unexpected_exit_keeps_expert_interaction_pause_active(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    create_minimal_project(project_root)

    run_script(
        "scripts/ops/control_agent.py",
        "start",
        "--project-root",
        str(project_root),
        "--manual-command",
        "jhc-agent-start",
    )
    begin_report = json.loads(
        run_script(
            "scripts/ops/chat_session.py",
            "begin",
            "--project-root",
            str(project_root),
        ).stdout
    )
    end_report = json.loads(
        run_script(
            "scripts/ops/chat_session.py",
            "end",
            "--project-root",
            str(project_root),
            "--session-id",
            begin_report["session_id"],
            "--exit-mode",
            "unexpected_exit",
        ).stdout
    )

    connection = connect_database(project_root / "job_hunt_copilot.db")
    control_rows = connection.execute(
        """
        SELECT control_key, control_value
        FROM agent_control_state
        WHERE control_key IN (
            'active_chat_session_id',
            'agent_enabled',
            'agent_mode',
            'chat_resume_on_close',
            'last_chat_exit_mode',
            'pause_reason'
        )
        ORDER BY control_key
        """
    ).fetchall()
    connection.close()

    assert end_report["status"] == "ended"
    assert end_report["resumed_agent"] is False
    assert end_report["control_state"]["agent_mode"] == "paused"
    assert end_report["control_state"]["pause_reason"] == "expert_interaction"
    assert dict(control_rows) == {
        "active_chat_session_id": "",
        "agent_enabled": "true",
        "agent_mode": "paused",
        "chat_resume_on_close": "false",
        "last_chat_exit_mode": "unexpected_exit",
        "pause_reason": "expert_interaction",
    }


def test_chat_session_script_ignores_mismatched_end_session_and_preserves_active_session(
    tmp_path,
):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    create_minimal_project(project_root)

    run_script(
        "scripts/ops/control_agent.py",
        "start",
        "--project-root",
        str(project_root),
        "--manual-command",
        "jhc-agent-start",
    )
    begin_report = json.loads(
        run_script(
            "scripts/ops/chat_session.py",
            "begin",
            "--project-root",
            str(project_root),
        ).stdout
    )

    end_report = json.loads(
        run_script(
            "scripts/ops/chat_session.py",
            "end",
            "--project-root",
            str(project_root),
            "--session-id",
            "jhc-chat-mismatched",
            "--exit-mode",
            "explicit_close",
        ).stdout
    )

    connection = connect_database(project_root / "job_hunt_copilot.db")
    control_rows = connection.execute(
        """
        SELECT control_key, control_value
        FROM agent_control_state
        WHERE control_key IN (
            'active_chat_session_id',
            'agent_enabled',
            'agent_mode',
            'chat_resume_on_close',
            'last_chat_ended_at',
            'last_chat_exit_mode',
            'pause_reason'
        )
        ORDER BY control_key
        """
    ).fetchall()
    connection.close()
    log_lines = (project_root / "ops" / "logs" / "chat-sessions.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()

    assert end_report["status"] == "ignored_session_mismatch"
    assert end_report["session_id"] == "jhc-chat-mismatched"
    assert end_report["active_session_id"] == begin_report["session_id"]
    assert end_report["control_state"]["active_chat_session_id"] == begin_report["session_id"]
    assert end_report["control_state"]["agent_mode"] == "paused"
    assert end_report["control_state"]["pause_reason"] == "expert_interaction"
    assert end_report["runtime_pack"]["agent_mode"] == "paused"
    assert dict(control_rows) == {
        "active_chat_session_id": begin_report["session_id"],
        "agent_enabled": "true",
        "agent_mode": "paused",
        "chat_resume_on_close": "true",
        "last_chat_ended_at": "",
        "last_chat_exit_mode": "",
        "pause_reason": "expert_interaction",
    }
    assert len(log_lines) == 2
    assert json.loads(log_lines[0])["event"] == "begin"
    assert json.loads(log_lines[1])["event"] == "end_ignored"


def test_chat_session_explicit_resume_clears_unexpected_exit_pause(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    create_minimal_project(project_root)

    run_script(
        "scripts/ops/control_agent.py",
        "start",
        "--project-root",
        str(project_root),
        "--manual-command",
        "jhc-agent-start",
    )
    begin_report = json.loads(
        run_script(
            "scripts/ops/chat_session.py",
            "begin",
            "--project-root",
            str(project_root),
        ).stdout
    )
    run_script(
        "scripts/ops/chat_session.py",
        "end",
        "--project-root",
        str(project_root),
        "--session-id",
        begin_report["session_id"],
        "--exit-mode",
        "unexpected_exit",
    )
    resume_report = json.loads(
        run_script(
            "scripts/ops/control_agent.py",
            "resume",
            "--project-root",
            str(project_root),
            "--manual-command",
            "resume",
        ).stdout
    )

    connection = connect_database(project_root / "job_hunt_copilot.db")
    control_rows = connection.execute(
        """
        SELECT control_key, control_value
        FROM agent_control_state
        WHERE control_key IN (
            'active_chat_session_id',
            'agent_enabled',
            'agent_mode',
            'chat_resume_on_close',
            'last_chat_exit_mode',
            'last_manual_command',
            'pause_reason',
            'paused_at'
        )
        ORDER BY control_key
        """
    ).fetchall()
    connection.close()

    assert resume_report["command"] == "resume"
    assert resume_report["control_state"]["agent_mode"] == "running"
    assert resume_report["control_state"]["pause_reason"] == ""
    assert dict(control_rows) == {
        "active_chat_session_id": "",
        "agent_enabled": "true",
        "agent_mode": "running",
        "chat_resume_on_close": "false",
        "last_chat_exit_mode": "unexpected_exit",
        "last_manual_command": "resume",
        "pause_reason": "",
        "paused_at": "",
    }


def test_supervisor_heartbeat_auto_resumes_after_unexpected_chat_exit_idle_timeout(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    create_minimal_project(project_root)

    mutate_agent_control_state(
        "start",
        project_root=project_root,
        manual_command="jhc-agent-start",
        timestamp="2026-04-08T00:00:00Z",
    )
    begin_report = begin_chat_operator_session(
        project_root=project_root,
        started_at="2026-04-08T00:01:00Z",
    )
    end_chat_operator_session(
        project_root=project_root,
        session_id=begin_report["session_id"],
        exit_mode="unexpected_exit",
        ended_at="2026-04-08T00:02:00Z",
    )

    heartbeat_report = execute_supervisor_heartbeat(
        project_root=project_root,
        started_at="2026-04-08T00:18:00Z",
    )

    connection = connect_database(project_root / "job_hunt_copilot.db")
    control_rows = connection.execute(
        """
        SELECT control_key, control_value
        FROM agent_control_state
        WHERE control_key IN (
            'active_chat_session_id',
            'agent_enabled',
            'agent_mode',
            'chat_resume_on_close',
            'last_chat_ended_at',
            'last_chat_exit_mode',
            'last_manual_command',
            'pause_reason',
            'paused_at'
        )
        ORDER BY control_key
        """
    ).fetchall()
    connection.close()

    assert heartbeat_report["chat_idle_timeout_resume"] == {
        "resume_reason": "unexpected_chat_exit_idle_timeout",
        "resumed_at": "2026-04-08T00:18:00Z",
        "idle_reference_at": "2026-04-08T00:02:00Z",
        "idle_seconds": 960,
        "idle_timeout_minutes": 15,
        "last_chat_exit_mode": "unexpected_exit",
        "previous_pause_reason": "expert_interaction",
    }
    assert heartbeat_report["pre_cycle_control_state"]["agent_mode"] == "running"
    assert heartbeat_report["pre_cycle_control_state"]["pause_reason"] == ""
    assert heartbeat_report["cycle"]["result"] == "no_work"
    assert heartbeat_report["control_state"]["agent_mode"] == "running"
    assert heartbeat_report["control_state"]["pause_reason"] == ""
    assert dict(control_rows) == {
        "active_chat_session_id": "",
        "agent_enabled": "true",
        "agent_mode": "running",
        "chat_resume_on_close": "false",
        "last_chat_ended_at": "2026-04-08T00:02:00Z",
        "last_chat_exit_mode": "unexpected_exit",
        "last_manual_command": "jhc-chat idle-timeout-auto-resume",
        "pause_reason": "",
        "paused_at": "",
    }


def test_chat_session_explicit_close_preserves_preexisting_non_chat_pause(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    create_minimal_project(project_root)

    run_script(
        "scripts/ops/control_agent.py",
        "pause",
        "--project-root",
        str(project_root),
        "--reason",
        "manual_triage",
        "--manual-command",
        "pause",
    )
    begin_report = json.loads(
        run_script(
            "scripts/ops/chat_session.py",
            "begin",
            "--project-root",
            str(project_root),
        ).stdout
    )
    end_report = json.loads(
        run_script(
            "scripts/ops/chat_session.py",
            "end",
            "--project-root",
            str(project_root),
            "--session-id",
            begin_report["session_id"],
            "--exit-mode",
            "explicit_close",
        ).stdout
    )

    assert begin_report["resume_on_close"] is False
    assert begin_report["control_state"]["agent_mode"] == "paused"
    assert begin_report["control_state"]["pause_reason"] == "manual_triage"
    assert end_report["resumed_agent"] is False
    assert end_report["control_state"]["agent_mode"] == "paused"
    assert end_report["control_state"]["pause_reason"] == "manual_triage"


def test_control_agent_background_task_handoff_records_explicit_summary_and_exclusive_focus(
    tmp_path,
):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    create_minimal_project(project_root)

    run_script(
        "scripts/ops/control_agent.py",
        "start",
        "--project-root",
        str(project_root),
        "--manual-command",
        "jhc-agent-start",
    )
    begin_report = json.loads(
        run_script(
            "scripts/ops/chat_session.py",
            "begin",
            "--project-root",
            str(project_root),
        ).stdout
    )

    handoff_report = json.loads(
        run_script(
            "scripts/ops/control_agent.py",
            "handoff-background-task",
            "--project-root",
            str(project_root),
            "--task-title",
            "Investigate launchctl bootstrap drift",
            "--scope-summary",
            "Inspect the current launchctl bootstrap failure path and capture the exact local blocker.",
            "--expected-outputs",
            "A bounded failure summary plus the exact commands, files, and runtime surfaces inspected.",
            "--risks-assumptions",
            "The sandbox may still block host launchctl diagnostics, so host-only confirmation might remain open.",
            "--will-change",
            "Only bounded runtime-control evidence artifacts and any strictly necessary review notes.",
            "--will-not-change",
            "No destructive git history and no tailoring, discovery, or outreach lifecycle state.",
            "--completion-condition",
            "The runtime blocker is either explained with persisted evidence or explicitly returned for expert review.",
        ).stdout
    )
    end_report = json.loads(
        run_script(
            "scripts/ops/chat_session.py",
            "end",
            "--project-root",
            str(project_root),
            "--session-id",
            begin_report["session_id"],
            "--exit-mode",
            "explicit_close",
        ).stdout
    )

    pipeline_run_id = handoff_report["pipeline_run"]["pipeline_run_id"]
    handoff_json_path = Path(handoff_report["artifacts"]["handoff_json_path"])
    handoff_markdown_path = Path(handoff_report["artifacts"]["handoff_markdown_path"])

    connection = connect_database(project_root / "job_hunt_copilot.db")
    control_rows = connection.execute(
        """
        SELECT control_key, control_value
        FROM agent_control_state
        WHERE control_key IN (
            'active_background_task_run_id',
            'active_chat_session_id',
            'agent_mode',
            'background_task_resume_on_finish',
            'chat_resume_on_close',
            'pause_reason'
        )
        ORDER BY control_key
        """
    ).fetchall()
    pipeline_row = connection.execute(
        """
        SELECT run_scope_type, run_status, current_stage, review_packet_status, run_summary
        FROM pipeline_runs
        WHERE pipeline_run_id = ?
        """,
        (pipeline_run_id,),
    ).fetchone()
    connection.close()

    assert handoff_report["status"] == "handoff_recorded"
    assert handoff_report["handoff_summary"]["task_title"] == "Investigate launchctl bootstrap drift"
    assert handoff_report["handoff_summary"]["exclusive_focus"] is True
    assert handoff_report["control_state"]["active_background_task_run_id"] == pipeline_run_id
    assert handoff_report["control_state"]["background_task_resume_on_finish"] == "true"
    assert end_report["resumed_agent"] is False
    assert end_report["control_state"]["agent_mode"] == "paused"
    assert end_report["control_state"]["pause_reason"] == (
        f"expert_requested_background_task:{pipeline_run_id}"
    )
    assert dict(control_rows) == {
        "active_background_task_run_id": pipeline_run_id,
        "active_chat_session_id": "",
        "agent_mode": "paused",
        "background_task_resume_on_finish": "true",
        "chat_resume_on_close": "false",
        "pause_reason": f"expert_requested_background_task:{pipeline_run_id}",
    }
    assert dict(pipeline_row) == {
        "run_scope_type": "expert_requested_background_task",
        "run_status": "in_progress",
        "current_stage": "background_execution",
        "review_packet_status": "not_ready",
        "run_summary": "Investigate launchctl bootstrap drift",
    }
    assert handoff_json_path.exists()
    assert handoff_markdown_path.exists()
    assert "## Scope" in handoff_markdown_path.read_text(encoding="utf-8")
    assert "## Completion Condition" in handoff_markdown_path.read_text(encoding="utf-8")


def test_control_agent_background_task_success_returns_result_to_pending_review_queue(
    tmp_path,
):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    create_minimal_project(project_root)

    run_script(
        "scripts/ops/control_agent.py",
        "start",
        "--project-root",
        str(project_root),
        "--manual-command",
        "jhc-agent-start",
    )
    begin_report = json.loads(
        run_script(
            "scripts/ops/chat_session.py",
            "begin",
            "--project-root",
            str(project_root),
        ).stdout
    )
    handoff_report = json.loads(
        run_script(
            "scripts/ops/control_agent.py",
            "handoff-background-task",
            "--project-root",
            str(project_root),
            "--task-title",
            "Investigate launchctl bootstrap drift",
            "--scope-summary",
            "Inspect the current launchctl bootstrap failure path and capture the exact local blocker.",
            "--expected-outputs",
            "A bounded failure summary plus the exact commands, files, and runtime surfaces inspected.",
            "--risks-assumptions",
            "The sandbox may still block host launchctl diagnostics, so host-only confirmation might remain open.",
            "--will-change",
            "Only bounded runtime-control evidence artifacts and any strictly necessary review notes.",
            "--will-not-change",
            "No destructive git history and no tailoring, discovery, or outreach lifecycle state.",
            "--completion-condition",
            "The runtime blocker is either explained with persisted evidence or explicitly returned for expert review.",
        ).stdout
    )
    run_script(
        "scripts/ops/chat_session.py",
        "end",
        "--project-root",
        str(project_root),
        "--session-id",
        begin_report["session_id"],
        "--exit-mode",
        "explicit_close",
    )

    pipeline_run_id = handoff_report["pipeline_run"]["pipeline_run_id"]
    return_report = json.loads(
        run_script(
            "scripts/ops/control_agent.py",
            "return-background-task",
            "--project-root",
            str(project_root),
            "--pipeline-run-id",
            pipeline_run_id,
            "--outcome",
            "completed",
            "--summary",
            "Captured the sandbox-only launchctl bootstrap blocker and the remaining host validation follow-up.",
            "--outputs-summary",
            "Recorded the exact failure mode, touched runtime-control evidence only, and prepared a review packet.",
            "--evidence-notes",
            "Host launchctl validation still requires a non-sandbox session.",
        ).stdout
    )

    connection = connect_database(project_root / "job_hunt_copilot.db")
    pipeline_row = connection.execute(
        """
        SELECT run_status, current_stage, review_packet_status, run_summary, last_error_summary
        FROM pipeline_runs
        WHERE pipeline_run_id = ?
        """,
        (pipeline_run_id,),
    ).fetchone()
    packet_row = connection.execute(
        """
        SELECT packet_status, packet_path, summary_excerpt
        FROM expert_review_packets
        WHERE pipeline_run_id = ?
        """,
        (pipeline_run_id,),
    ).fetchone()
    review_queue = build_chat_review_queue(connection, project_root=project_root)
    control_rows = connection.execute(
        """
        SELECT control_key, control_value
        FROM agent_control_state
        WHERE control_key IN (
            'active_background_task_run_id',
            'agent_mode',
            'background_task_resume_on_finish',
            'pause_reason'
        )
        ORDER BY control_key
        """
    ).fetchall()
    connection.close()

    pending_group = next(
        group
        for group in review_queue["groups"]
        if group["group_id"] == "pending_expert_review_packets"
    )

    assert return_report["status"] == "review_returned"
    assert return_report["background_task_outcome"] == "completed"
    assert return_report["expert_review_packet_id"]
    assert return_report["control_state"]["agent_mode"] == "running"
    assert dict(pipeline_row) == {
        "run_status": "completed",
        "current_stage": "review_pending",
        "review_packet_status": "pending_expert_review",
        "run_summary": "Investigate launchctl bootstrap drift",
        "last_error_summary": None,
    }
    assert dict(packet_row) == {
        "packet_status": "pending_expert_review",
        "packet_path": f"ops/review-packets/{pipeline_run_id}/review_packet.json",
        "summary_excerpt": "Captured the sandbox-only launchctl bootstrap blocker and the remaining host validation follow-up.",
    }
    assert pending_group["items"][0]["headline"] == "Investigate launchctl bootstrap drift"
    assert (
        pending_group["items"][0]["summary"]
        == "Captured the sandbox-only launchctl bootstrap blocker and the remaining host validation follow-up."
    )
    assert dict(control_rows) == {
        "active_background_task_run_id": "",
        "agent_mode": "running",
        "background_task_resume_on_finish": "false",
        "pause_reason": "",
    }
    assert Path(return_report["artifacts"]["review_packet_json_path"]).exists()
    assert Path(return_report["artifacts"]["review_packet_markdown_path"]).exists()


def test_control_agent_background_task_stalled_return_restores_chat_pause_and_review_item(
    tmp_path,
):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    create_minimal_project(project_root)

    run_script(
        "scripts/ops/control_agent.py",
        "start",
        "--project-root",
        str(project_root),
        "--manual-command",
        "jhc-agent-start",
    )
    begin_report = json.loads(
        run_script(
            "scripts/ops/chat_session.py",
            "begin",
            "--project-root",
            str(project_root),
        ).stdout
    )
    handoff_report = json.loads(
        run_script(
            "scripts/ops/control_agent.py",
            "handoff-background-task",
            "--project-root",
            str(project_root),
            "--task-title",
            "Investigate launchctl bootstrap drift",
            "--scope-summary",
            "Inspect the current launchctl bootstrap failure path and capture the exact local blocker.",
            "--expected-outputs",
            "A bounded failure summary plus the exact commands, files, and runtime surfaces inspected.",
            "--risks-assumptions",
            "The sandbox may still block host launchctl diagnostics, so host-only confirmation might remain open.",
            "--will-change",
            "Only bounded runtime-control evidence artifacts and any strictly necessary review notes.",
            "--will-not-change",
            "No destructive git history and no tailoring, discovery, or outreach lifecycle state.",
            "--completion-condition",
            "The runtime blocker is either explained with persisted evidence or explicitly returned for expert review.",
        ).stdout
    )

    pipeline_run_id = handoff_report["pipeline_run"]["pipeline_run_id"]
    return_report = json.loads(
        run_script(
            "scripts/ops/control_agent.py",
            "return-background-task",
            "--project-root",
            str(project_root),
            "--pipeline-run-id",
            pipeline_run_id,
            "--outcome",
            "stalled",
            "--summary",
            "Sandbox launchctl access is still blocked, so the host-only check needs expert review.",
            "--evidence-notes",
            "Captured the failing bootstrap command and the current sandbox restriction.",
        ).stdout
    )
    end_report = json.loads(
        run_script(
            "scripts/ops/chat_session.py",
            "end",
            "--project-root",
            str(project_root),
            "--session-id",
            begin_report["session_id"],
            "--exit-mode",
            "explicit_close",
        ).stdout
    )

    connection = connect_database(project_root / "job_hunt_copilot.db")
    pipeline_row = connection.execute(
        """
        SELECT run_status, current_stage, review_packet_status, run_summary, last_error_summary
        FROM pipeline_runs
        WHERE pipeline_run_id = ?
        """,
        (pipeline_run_id,),
    ).fetchone()
    review_queue = build_chat_review_queue(connection, project_root=project_root)
    connection.close()

    failed_group = next(
        group
        for group in review_queue["groups"]
        if group["group_id"] == "failed_expert_requested_background_tasks"
    )

    assert return_report["status"] == "review_returned"
    assert return_report["background_task_outcome"] == "stalled"
    assert return_report["expert_review_packet_id"] is None
    assert return_report["control_state"]["agent_mode"] == "paused"
    assert return_report["control_state"]["pause_reason"] == "expert_interaction"
    assert return_report["control_state"]["chat_resume_on_close"] == "true"
    assert end_report["resumed_agent"] is True
    assert end_report["control_state"]["agent_mode"] == "running"
    assert dict(pipeline_row) == {
        "run_status": "paused",
        "current_stage": "review_pending",
        "review_packet_status": "not_ready",
        "run_summary": "Investigate launchctl bootstrap drift",
        "last_error_summary": "Sandbox launchctl access is still blocked, so the host-only check needs expert review.",
    }
    assert failed_group["items"][0]["headline"] == "Investigate launchctl bootstrap drift"
    assert (
        failed_group["items"][0]["summary"]
        == "Sandbox launchctl access is still blocked, so the host-only check needs expert review."
    )
    assert failed_group["items"][0]["artifact_refs"] == [
        f"ops/background-tasks/{pipeline_run_id}/background_task_result.md",
        f"ops/background-tasks/{pipeline_run_id}/background_task_result.json",
        f"ops/background-tasks/{pipeline_run_id}/background_task_handoff.md",
        f"ops/background-tasks/{pipeline_run_id}/background_task_handoff.json",
    ]


def test_chat_startup_dashboard_uses_persisted_state_for_clean_metrics_and_grouped_review_items(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    create_minimal_project(project_root)

    run_script(
        "scripts/ops/control_agent.py",
        "start",
        "--project-root",
        str(project_root),
        "--manual-command",
        "jhc-agent-start",
    )

    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_chat_dashboard_state(connection)
    dashboard = build_chat_startup_dashboard(
        connection,
        project_root=project_root,
        current_time="2026-04-08T10:00:00Z",
        agent_mode="paused",
        pause_reason="expert_interaction",
        local_timezone=timezone(timedelta(hours=-7)),
    )
    connection.close()

    assert dashboard["summary"] == {
        "pending_expert_review_count": 1,
        "open_incident_count": 1,
        "maintenance_batch_count": 1,
        "maintenance_state": "1 recorded maintenance batches",
    }
    assert dashboard["runtime_metrics"]["today"] == {
        "date": "2026-04-08",
        "runtime_seconds": 2100.0,
        "runtime_display": "35m",
        "successful_run_count": 1,
        "successful_send_count": 1,
        "bounce_count": 1,
        "reply_count": 0,
    }
    assert dashboard["runtime_metrics"]["yesterday"] == {
        "date": "2026-04-07",
        "runtime_seconds": 1800.0,
        "runtime_display": "30m",
        "successful_run_count": 1,
        "successful_send_count": 1,
        "bounce_count": 0,
        "reply_count": 1,
    }
    assert dashboard["runtime_metrics"]["rolling_average_daily_runtime_seconds"] == 557.143
    assert dashboard["runtime_metrics"]["rolling_average_daily_runtime_display"] == "9m"

    review_groups = dashboard["review_queue"]["groups"]
    assert [group["group_id"] for group in review_groups] == [
        "pending_expert_review_packets",
        "failed_expert_requested_background_tasks",
        "maintenance_change_batches",
        "open_incidents",
    ]
    assert review_groups[0]["items"][0]["headline"] == "Acme Robotics / Staff Software Engineer / AI"
    assert (
        review_groups[0]["items"][0]["summary"]
        == "Duplicate-send risk needs expert review."
    )
    assert review_groups[1]["items"] == []
    assert review_groups[2]["items"][0]["headline"] == "chat-runtime-summary"
    assert "Full-project validation failed" in review_groups[2]["items"][0]["summary"]
    assert review_groups[3]["items"][0]["summary"] == (
        "high: Potential resend detected for the current outreach wave."
    )


def test_chat_session_begin_persists_startup_briefing_for_wrapper_startup(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    create_minimal_project(project_root)

    run_script(
        "scripts/ops/control_agent.py",
        "start",
        "--project-root",
        str(project_root),
        "--manual-command",
        "jhc-agent-start",
    )
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_chat_dashboard_state(connection)
    connection.close()

    begin_report = json.loads(
        run_script(
            "scripts/ops/chat_session.py",
            "begin",
            "--project-root",
            str(project_root),
        ).stdout
    )

    startup_path = project_root / "ops" / "agent" / "chat-startup.md"

    assert begin_report["startup_briefing_path"] == str(startup_path)
    assert begin_report["startup_dashboard"]["summary"]["pending_expert_review_count"] == 1
    assert startup_path.read_text(encoding="utf-8") == begin_report["startup_briefing"]
    assert begin_report["startup_briefing"].startswith("# Job Hunt Copilot Dashboard\n")
    assert "- Pending expert review items: 1" in begin_report["startup_briefing"]
    assert "- Open incidents: 1" in begin_report["startup_briefing"]
    assert "## Review Queue" in begin_report["startup_briefing"]
    assert "Pending expert review packets: 1" in begin_report["startup_briefing"]
    assert "Autonomous maintenance change batches: 1" in begin_report["startup_briefing"]
    assert "Open incidents: 1" in begin_report["startup_briefing"]


def test_chat_state_script_returns_persisted_dashboard_from_canonical_state(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    create_minimal_project(project_root)
    run_script(
        "scripts/ops/control_agent.py",
        "start",
        "--project-root",
        str(project_root),
        "--manual-command",
        "jhc-agent-start",
    )

    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_chat_dashboard_state(connection)
    connection.close()

    report = json.loads(
        run_script(
            "scripts/ops/chat_state.py",
            "dashboard",
            "--project-root",
            str(project_root),
            "--current-time",
            "2026-04-08T10:00:00Z",
        ).stdout
    )

    payload = report["payload"]
    assert report["command"] == "dashboard"
    assert report["current_time"] == "2026-04-08T10:00:00Z"
    assert payload["generated_at"] == "2026-04-08T10:00:00Z"
    assert payload["summary"] == {
        "pending_expert_review_count": 1,
        "open_incident_count": 1,
        "maintenance_batch_count": 1,
        "maintenance_state": "1 recorded maintenance batches",
    }
    assert payload["runtime_metrics"]["today"]["runtime_display"] == "35m"
    assert payload["runtime_metrics"]["yesterday"]["runtime_display"] == "30m"
    assert [group["group_id"] for group in payload["review_queue"]["groups"]] == [
        "pending_expert_review_packets",
        "failed_expert_requested_background_tasks",
        "maintenance_change_batches",
        "open_incidents",
    ]
    assert payload["review_queue"]["groups"][0]["items"][0]["headline"] == (
        "Acme Robotics / Staff Software Engineer / AI"
    )
    assert report["rendered_markdown"].startswith("# Job Hunt Copilot Dashboard\n")
    assert "- Pending expert review items: 1" in report["rendered_markdown"]
    assert "- Maintenance state: 1 recorded maintenance batches" in report["rendered_markdown"]
    assert "## Review Queue" in report["rendered_markdown"]


def test_chat_review_queue_is_compact_first_and_newest_first_within_each_group(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    create_minimal_project(project_root)
    run_script(
        "scripts/ops/control_agent.py",
        "status",
        "--project-root",
        str(project_root),
    )

    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_chat_review_queue_state(connection)
    review_queue = build_chat_review_queue(
        connection,
        project_root=project_root,
        local_timezone=timezone(timedelta(hours=-7)),
        max_items_per_group=1,
    )
    connection.close()

    groups = {group["group_id"]: group for group in review_queue["groups"]}

    assert review_queue["group_order"] == [
        "pending_expert_review_packets",
        "failed_expert_requested_background_tasks",
        "maintenance_change_batches",
        "open_incidents",
    ]
    assert groups["pending_expert_review_packets"]["total_count"] == 2
    assert len(groups["pending_expert_review_packets"]["items"]) == 1
    assert groups["pending_expert_review_packets"]["items"][0]["headline"] == (
        "Beta Labs / ML Platform Engineer"
    )

    assert groups["failed_expert_requested_background_tasks"]["total_count"] == 2
    assert len(groups["failed_expert_requested_background_tasks"]["items"]) == 1
    assert groups["failed_expert_requested_background_tasks"]["items"][0]["headline"] == (
        "Reconcile launchctl bootstrap failure evidence."
    )

    assert groups["maintenance_change_batches"]["total_count"] == 2
    assert len(groups["maintenance_change_batches"]["items"]) == 1
    assert groups["maintenance_change_batches"]["items"][0]["headline"] == (
        "feedback-retry-hardening"
    )

    assert groups["open_incidents"]["total_count"] == 2
    assert len(groups["open_incidents"]["items"]) == 1
    assert groups["open_incidents"]["items"][0]["headline"] == (
        "Beta Labs / ML Platform Engineer"
    )
    assert groups["open_incidents"]["items"][0]["summary"] == (
        "medium: Contact enrichment stalled without a verified working email."
    )


def test_chat_state_script_returns_grouped_review_queue_from_persisted_state(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    create_minimal_project(project_root)
    run_script(
        "scripts/ops/control_agent.py",
        "status",
        "--project-root",
        str(project_root),
    )

    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_chat_review_queue_state(connection)
    connection.close()

    report = json.loads(
        run_script(
            "scripts/ops/chat_state.py",
            "review-queue",
            "--project-root",
            str(project_root),
            "--max-items-per-group",
            "1",
        ).stdout
    )

    payload = report["payload"]
    assert report["command"] == "review-queue"
    assert payload["group_order"] == [
        "pending_expert_review_packets",
        "failed_expert_requested_background_tasks",
        "maintenance_change_batches",
        "open_incidents",
    ]
    assert payload["groups"][0]["items"][0]["headline"] == "Beta Labs / ML Platform Engineer"
    assert payload["groups"][1]["items"][0]["headline"] == (
        "Reconcile launchctl bootstrap failure evidence."
    )
    assert payload["groups"][2]["items"][0]["headline"] == "feedback-retry-hardening"
    assert payload["groups"][3]["items"][0]["headline"] == "Beta Labs / ML Platform Engineer"
    assert "## Review Queue" in report["rendered_markdown"]
    assert "Pending expert review packets: 2" in report["rendered_markdown"]
    assert "Autonomous maintenance change batches: 2" in report["rendered_markdown"]


def test_chat_state_scripts_are_idempotent_and_read_only(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    create_minimal_project(project_root)
    run_script(
        "scripts/ops/control_agent.py",
        "status",
        "--project-root",
        str(project_root),
    )

    tracked_tables = (
        "agent_control_state",
        "delivery_feedback_events",
        "expert_review_decisions",
        "expert_review_packets",
        "maintenance_change_batches",
        "agent_incidents",
        "override_events",
        "outreach_messages",
        "pipeline_runs",
        "supervisor_cycles",
        "windows",
        "state_transition_events",
    )
    control_state_query = """
        SELECT control_key, control_value
        FROM agent_control_state
        ORDER BY control_key
    """

    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_chat_change_summary_state(connection)
    before_counts = {
        table_name: connection.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
        for table_name in tracked_tables
    }
    before_control_state = dict(connection.execute(control_state_query).fetchall())
    connection.close()

    review_queue_args = (
        "scripts/ops/chat_state.py",
        "review-queue",
        "--project-root",
        str(project_root),
        "--current-time",
        "2026-04-08T15:30:00Z",
        "--max-items-per-group",
        "2",
    )
    first_review_queue = json.loads(run_script(*review_queue_args).stdout)
    second_review_queue = json.loads(run_script(*review_queue_args).stdout)
    assert first_review_queue == second_review_queue

    dashboard_args = (
        "scripts/ops/chat_state.py",
        "dashboard",
        "--project-root",
        str(project_root),
        "--current-time",
        "2026-04-08T15:30:00Z",
    )
    first_dashboard = json.loads(run_script(*dashboard_args).stdout)
    second_dashboard = json.loads(run_script(*dashboard_args).stdout)
    assert first_dashboard == second_dashboard

    change_summary_args = (
        "scripts/ops/chat_state.py",
        "change-summary",
        "--project-root",
        str(project_root),
        "--current-time",
        "2026-04-08T15:30:00Z",
        "--max-items-per-group",
        "2",
    )
    first_change_summary = json.loads(run_script(*change_summary_args).stdout)
    second_change_summary = json.loads(run_script(*change_summary_args).stdout)
    assert first_change_summary == second_change_summary

    connection = connect_database(project_root / "job_hunt_copilot.db")
    after_counts = {
        table_name: connection.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
        for table_name in tracked_tables
    }
    after_control_state = dict(connection.execute(control_state_query).fetchall())
    connection.close()

    assert after_counts == before_counts
    assert after_control_state == before_control_state


def test_chat_state_script_change_summary_defaults_to_last_completed_expert_review(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    create_minimal_project(project_root)
    run_script(
        "scripts/ops/control_agent.py",
        "status",
        "--project-root",
        str(project_root),
    )

    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_chat_change_summary_state(connection)
    connection.close()

    report = json.loads(
        run_script(
            "scripts/ops/chat_state.py",
            "change-summary",
            "--project-root",
            str(project_root),
            "--current-time",
            "2026-04-08T15:30:00Z",
            "--max-items-per-group",
            "2",
        ).stdout
    )

    payload = report["payload"]
    assert report["command"] == "change-summary"
    assert payload["window_kind"] == "since_last_completed_expert_review"
    assert payload["window_start_at"] == "2026-04-08T14:00:00Z"
    assert payload["activity_counts"]["pending_expert_review_packets"] == 1
    assert payload["activity_counts"]["maintenance_change_batches"] == 1
    assert payload["activity_counts"]["override_events"] == 1
    maintenance_group = next(
        group
        for group in payload["review_queue"]["groups"]
        if group["group_id"] == "maintenance_change_batches"
    )
    assert maintenance_group["items"][0]["headline"] == "chat-post-review-followup"
    assert "Window: since the last completed expert review" in report["rendered_markdown"]
    assert "chat-post-review-followup" in report["rendered_markdown"]
    assert "Reviewable deltas:" in report["rendered_markdown"]


def test_repo_agent_wrappers_use_expected_repo_local_wiring():
    start_wrapper = (REPO_ROOT / "bin" / "jhc-agent-start").read_text(encoding="utf-8")
    stop_wrapper = (REPO_ROOT / "bin" / "jhc-agent-stop").read_text(encoding="utf-8")
    cycle_wrapper = (REPO_ROOT / "bin" / "jhc-agent-cycle").read_text(encoding="utf-8")
    feedback_cycle_wrapper = (REPO_ROOT / "bin" / "jhc-feedback-sync-cycle").read_text(encoding="utf-8")
    chat_wrapper = (REPO_ROOT / "bin" / "jhc-chat").read_text(encoding="utf-8")

    assert "scripts/ops/build_runtime_pack.py" in start_wrapper
    assert "scripts/ops/materialize_supervisor_plist.py" in start_wrapper
    assert "scripts/ops/materialize_feedback_sync_plist.py" in start_wrapper
    assert "scripts/ops/control_agent.py\" start" in start_wrapper
    assert 'launchctl bootstrap "gui/$UID" "$FEEDBACK_PLIST"' in start_wrapper
    assert 'launchctl kickstart -k "$FEEDBACK_LABEL"' in start_wrapper
    assert "scripts/ops/control_agent.py\" stop" in start_wrapper
    assert "trap rollback_start_failure ERR" in start_wrapper
    assert 'launchctl bootstrap "gui/$UID" "$PLIST"' in start_wrapper
    assert 'launchctl kickstart -k "$LABEL"' in start_wrapper
    assert "com.jobhuntcopilot.supervisor" in start_wrapper
    assert "com.jobhuntcopilot.feedback-sync" in start_wrapper

    assert 'launchctl bootout "gui/$UID" "$FEEDBACK_PLIST"' in stop_wrapper
    assert "scripts/ops/control_agent.py\" stop" in stop_wrapper
    assert 'launchctl bootout "gui/$UID" "$PLIST"' in stop_wrapper
    assert "com.jobhuntcopilot.supervisor" in stop_wrapper
    assert "com.jobhuntcopilot.feedback-sync" in stop_wrapper

    assert "scripts/ops/run_supervisor_cycle.py" in cycle_wrapper
    assert '--project-root "$ROOT"' in cycle_wrapper

    assert "scripts/ops/run_feedback_sync.py" in feedback_cycle_wrapper
    assert '--project-root "$ROOT"' in feedback_cycle_wrapper

    assert "scripts/ops/chat_session.py\" begin" in chat_wrapper
    assert "scripts/ops/chat_session.py\" end" in chat_wrapper
    assert 'PROMPT_FILE="$ROOT/ops/agent/chat-bootstrap.md"' in chat_wrapper
    assert 'STARTUP_BRIEFING="$(printf ' in chat_wrapper
    assert 'Current persisted startup briefing:' in chat_wrapper
    assert "--ephemeral" in chat_wrapper
    assert "--sandbox workspace-write" in chat_wrapper
    assert "--ask-for-approval never" in chat_wrapper
