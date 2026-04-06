from __future__ import annotations

import plistlib
import sqlite3
from pathlib import Path
from typing import Any

from .contracts import CONTRACT_VERSION
from .db import initialize_database
from .paths import ProjectPaths
from .records import now_utc_iso
from .runtime_pack import materialize_runtime_pack, write_text_atomic
from .supervisor import (
    begin_replanning,
    pause_agent,
    read_agent_control_state,
    resume_agent,
    run_supervisor_cycle,
    stop_agent,
)


SUPERVISOR_LAUNCHD_LABEL = "com.jobhuntcopilot.supervisor"
SUPERVISOR_HEARTBEAT_INTERVAL_SECONDS = 180
SUPERVISOR_TRIGGER_TYPE = "launchd_heartbeat"
SUPERVISOR_SCHEDULER_NAME = "launchd"
SUPERVISOR_SLEEP_WAKE_DETECTION_METHOD = "pmset_log"


def connect_canonical_database(paths: ProjectPaths) -> sqlite3.Connection:
    connection = sqlite3.connect(paths.db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    return connection


def render_supervisor_launchd_plist_payload(paths: ProjectPaths) -> dict[str, Any]:
    return {
        "Label": SUPERVISOR_LAUNCHD_LABEL,
        "RunAtLoad": True,
        "StartInterval": SUPERVISOR_HEARTBEAT_INTERVAL_SECONDS,
        "KeepAlive": False,
        "WorkingDirectory": str(paths.project_root),
        "ProgramArguments": [str(paths.agent_cycle_entrypoint_path)],
        "StandardOutPath": str(paths.supervisor_stdout_log_path),
        "StandardErrorPath": str(paths.supervisor_stderr_log_path),
    }


def render_supervisor_launchd_plist(paths: ProjectPaths) -> str:
    payload = render_supervisor_launchd_plist_payload(paths)
    return plistlib.dumps(payload, fmt=plistlib.FMT_XML, sort_keys=False).decode("utf-8")


def materialize_supervisor_launchd_plist(
    project_root: Path | str | None = None,
) -> dict[str, Any]:
    paths = ProjectPaths.from_root(project_root)
    paths.ops_logs_dir.mkdir(parents=True, exist_ok=True)
    paths.ops_launchd_dir.mkdir(parents=True, exist_ok=True)

    rendered = render_supervisor_launchd_plist(paths)
    created = not paths.supervisor_plist_path.exists()
    write_text_atomic(paths.supervisor_plist_path, rendered)
    paths.supervisor_plist_path.chmod(0o644)

    return {
        "contract_version": CONTRACT_VERSION,
        "generated_at": now_utc_iso(),
        "project_root": str(paths.project_root),
        "plist_path": str(paths.supervisor_plist_path),
        "launchd_label": SUPERVISOR_LAUNCHD_LABEL,
        "heartbeat_interval_seconds": SUPERVISOR_HEARTBEAT_INTERVAL_SECONDS,
        "program_arguments": [str(paths.agent_cycle_entrypoint_path)],
        "stdout_log_path": str(paths.supervisor_stdout_log_path),
        "stderr_log_path": str(paths.supervisor_stderr_log_path),
        "created": created,
    }


def mutate_agent_control_state(
    command: str,
    *,
    project_root: Path | str | None = None,
    reason: str | None = None,
    manual_command: str | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    paths = ProjectPaths.from_root(project_root)
    migration = initialize_database(paths.db_path)

    with connect_canonical_database(paths) as connection:
        if command == "status":
            snapshot = read_agent_control_state(connection, timestamp=timestamp)
        elif command == "start":
            snapshot = resume_agent(
                connection,
                manual_command=manual_command or "jhc-agent-start",
                timestamp=timestamp,
            )
        elif command == "resume":
            snapshot = resume_agent(
                connection,
                manual_command=manual_command or "resume",
                timestamp=timestamp,
            )
        elif command == "pause":
            if not reason:
                raise ValueError("Pause reason is required for the pause command.")
            snapshot = pause_agent(
                connection,
                reason=reason,
                manual_command=manual_command or "pause",
                timestamp=timestamp,
            )
        elif command == "stop":
            snapshot = stop_agent(
                connection,
                manual_command=manual_command or "jhc-agent-stop",
                timestamp=timestamp,
            )
        elif command == "replan":
            if not reason:
                raise ValueError("Replan reason is required for the replan command.")
            snapshot = begin_replanning(
                connection,
                reason=reason,
                manual_command=manual_command or "replan",
                timestamp=timestamp,
            )
        else:
            raise ValueError(f"Unsupported control command: {command}")

    return {
        "contract_version": CONTRACT_VERSION,
        "produced_at": now_utc_iso(),
        "project_root": str(paths.project_root),
        "database": {
            "db_path": str(migration.db_path),
            "applied_migrations": migration.applied_migrations,
            "user_version": migration.user_version,
        },
        "command": command,
        "control_state": dict(snapshot.values),
    }


def execute_supervisor_heartbeat(
    *,
    project_root: Path | str | None = None,
    started_at: str | None = None,
) -> dict[str, Any]:
    paths = ProjectPaths.from_root(project_root)
    migration = initialize_database(paths.db_path)

    with connect_canonical_database(paths) as connection:
        execution = run_supervisor_cycle(
            connection,
            paths,
            trigger_type=SUPERVISOR_TRIGGER_TYPE,
            scheduler_name=SUPERVISOR_SCHEDULER_NAME,
            sleep_wake_detection_method=SUPERVISOR_SLEEP_WAKE_DETECTION_METHOD,
            started_at=started_at,
        )

    runtime_pack = materialize_runtime_pack(paths.project_root)

    selected_work = None
    if execution.selected_work is not None:
        selected_work = {
            "work_type": execution.selected_work.work_type,
            "work_id": execution.selected_work.work_id,
            "action_id": execution.selected_work.action_id,
            "summary": execution.selected_work.summary,
            "lead_id": execution.selected_work.lead_id,
            "job_posting_id": execution.selected_work.job_posting_id,
            "pipeline_run_id": execution.selected_work.pipeline_run_id,
            "incident_id": execution.selected_work.incident_id,
            "current_stage": execution.selected_work.current_stage,
        }

    return {
        "contract_version": CONTRACT_VERSION,
        "produced_at": now_utc_iso(),
        "project_root": str(paths.project_root),
        "database": {
            "db_path": str(migration.db_path),
            "applied_migrations": migration.applied_migrations,
            "user_version": migration.user_version,
        },
        "cycle": {
            "supervisor_cycle_id": execution.cycle.supervisor_cycle_id,
            "trigger_type": execution.cycle.trigger_type,
            "scheduler_name": execution.cycle.scheduler_name,
            "started_at": execution.cycle.started_at,
            "completed_at": execution.cycle.completed_at,
            "result": execution.cycle.result,
            "error_summary": execution.cycle.error_summary,
            "selected_work_type": execution.cycle.selected_work_type,
            "selected_work_id": execution.cycle.selected_work_id,
            "pipeline_run_id": execution.cycle.pipeline_run_id,
            "context_snapshot_path": execution.cycle.context_snapshot_path,
        },
        "lease_status": execution.lease_status,
        "control_state": dict(execution.control_state.values),
        "selected_work": selected_work,
        "pipeline_run_id": (
            execution.pipeline_run.pipeline_run_id
            if execution.pipeline_run is not None
            else None
        ),
        "agent_incident_id": (
            execution.incident.agent_incident_id
            if execution.incident is not None
            else None
        ),
        "expert_review_packet_id": (
            execution.review_packet.expert_review_packet_id
            if execution.review_packet is not None
            else None
        ),
        "runtime_pack": runtime_pack,
    }
