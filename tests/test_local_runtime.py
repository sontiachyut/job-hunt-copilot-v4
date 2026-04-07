from __future__ import annotations

import json
import plistlib
import sqlite3
import subprocess
import sys
from pathlib import Path

import job_hunt_copilot.local_runtime as local_runtime
from job_hunt_copilot.delivery_feedback import DeliveryFeedbackSignal
from job_hunt_copilot.local_runtime import execute_delayed_feedback_sync, execute_supervisor_heartbeat
from tests.support import create_minimal_project


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
    assert "--ephemeral" in chat_wrapper
    assert "--sandbox workspace-write" in chat_wrapper
    assert "--ask-for-approval never" in chat_wrapper
