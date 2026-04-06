from __future__ import annotations

import json
import plistlib
import sqlite3
import subprocess
import sys
from pathlib import Path

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
    chat_wrapper = (REPO_ROOT / "bin" / "jhc-chat").read_text(encoding="utf-8")

    assert "scripts/ops/build_runtime_pack.py" in start_wrapper
    assert "scripts/ops/materialize_supervisor_plist.py" in start_wrapper
    assert "scripts/ops/control_agent.py\" start" in start_wrapper
    assert "scripts/ops/control_agent.py\" stop" in start_wrapper
    assert "trap rollback_start_failure ERR" in start_wrapper
    assert 'launchctl bootstrap "gui/$UID" "$PLIST"' in start_wrapper
    assert 'launchctl kickstart -k "$LABEL"' in start_wrapper
    assert "com.jobhuntcopilot.supervisor" in start_wrapper

    assert "scripts/ops/control_agent.py\" stop" in stop_wrapper
    assert 'launchctl bootout "gui/$UID" "$PLIST"' in stop_wrapper
    assert "com.jobhuntcopilot.supervisor" in stop_wrapper

    assert "scripts/ops/run_supervisor_cycle.py" in cycle_wrapper
    assert '--project-root "$ROOT"' in cycle_wrapper

    assert "scripts/ops/chat_session.py\" begin" in chat_wrapper
    assert "scripts/ops/chat_session.py\" end" in chat_wrapper
    assert 'PROMPT_FILE="$ROOT/ops/agent/chat-bootstrap.md"' in chat_wrapper
    assert "--ephemeral" in chat_wrapper
    assert "--sandbox workspace-write" in chat_wrapper
    assert "--ask-for-approval never" in chat_wrapper
