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


def test_repo_agent_wrappers_use_expected_repo_local_wiring():
    start_wrapper = (REPO_ROOT / "bin" / "jhc-agent-start").read_text(encoding="utf-8")
    stop_wrapper = (REPO_ROOT / "bin" / "jhc-agent-stop").read_text(encoding="utf-8")
    cycle_wrapper = (REPO_ROOT / "bin" / "jhc-agent-cycle").read_text(encoding="utf-8")

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
