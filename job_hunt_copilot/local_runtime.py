from __future__ import annotations

import json
import plistlib
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from .contracts import CONTRACT_VERSION
from .db import initialize_database
from .delivery_feedback import (
    DELAYED_FEEDBACK_POLL_INTERVAL_MINUTES,
    OBSERVATION_SCOPE_DELAYED,
    MailboxFeedbackObserver,
    sync_delivery_feedback,
)
from .paths import ProjectPaths
from .records import now_utc_iso
from .runtime_pack import materialize_runtime_pack, write_text_atomic
from .supervisor import (
    AGENT_MODE_PAUSED,
    AGENT_MODE_RUNNING,
    AGENT_MODE_STOPPED,
    begin_replanning,
    pause_agent,
    read_agent_control_state,
    resume_agent,
    run_supervisor_cycle,
    stop_agent,
    upsert_control_values,
)


SUPERVISOR_LAUNCHD_LABEL = "com.jobhuntcopilot.supervisor"
SUPERVISOR_HEARTBEAT_INTERVAL_SECONDS = 180
SUPERVISOR_TRIGGER_TYPE = "launchd_heartbeat"
SUPERVISOR_SCHEDULER_NAME = "launchd"
SUPERVISOR_SLEEP_WAKE_DETECTION_METHOD = "pmset_log"
FEEDBACK_SYNC_LAUNCHD_LABEL = "com.jobhuntcopilot.feedback-sync"
FEEDBACK_SYNC_INTERVAL_SECONDS = DELAYED_FEEDBACK_POLL_INTERVAL_MINUTES * 60
FEEDBACK_SYNC_SCHEDULER_NAME = "job-hunt-copilot-feedback-sync"
FEEDBACK_SYNC_SCHEDULER_TYPE = "launchd"
CHAT_SESSION_EXIT_MODE_EXPLICIT_CLOSE = "explicit_close"
CHAT_SESSION_EXIT_MODE_UNEXPECTED_EXIT = "unexpected_exit"
CHAT_SESSION_EXIT_MODES = frozenset(
    {
        CHAT_SESSION_EXIT_MODE_EXPLICIT_CLOSE,
        CHAT_SESSION_EXIT_MODE_UNEXPECTED_EXIT,
    }
)
CHAT_INTERACTION_PAUSE_REASON = "expert_interaction"


def connect_canonical_database(paths: ProjectPaths) -> sqlite3.Connection:
    connection = sqlite3.connect(paths.db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    return connection


def append_jsonl_record(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=False))
        handle.write("\n")


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


def render_feedback_sync_launchd_plist_payload(paths: ProjectPaths) -> dict[str, Any]:
    return {
        "Label": FEEDBACK_SYNC_LAUNCHD_LABEL,
        "RunAtLoad": True,
        "StartInterval": FEEDBACK_SYNC_INTERVAL_SECONDS,
        "KeepAlive": False,
        "WorkingDirectory": str(paths.project_root),
        "ProgramArguments": [str(paths.feedback_sync_cycle_entrypoint_path)],
        "StandardOutPath": str(paths.feedback_sync_stdout_log_path),
        "StandardErrorPath": str(paths.feedback_sync_stderr_log_path),
    }


def render_feedback_sync_launchd_plist(paths: ProjectPaths) -> str:
    payload = render_feedback_sync_launchd_plist_payload(paths)
    return plistlib.dumps(payload, fmt=plistlib.FMT_XML, sort_keys=False).decode("utf-8")


def materialize_feedback_sync_launchd_plist(
    project_root: Path | str | None = None,
) -> dict[str, Any]:
    paths = ProjectPaths.from_root(project_root)
    paths.ops_logs_dir.mkdir(parents=True, exist_ok=True)
    paths.ops_launchd_dir.mkdir(parents=True, exist_ok=True)

    rendered = render_feedback_sync_launchd_plist(paths)
    created = not paths.feedback_sync_plist_path.exists()
    write_text_atomic(paths.feedback_sync_plist_path, rendered)
    paths.feedback_sync_plist_path.chmod(0o644)

    return {
        "contract_version": CONTRACT_VERSION,
        "generated_at": now_utc_iso(),
        "project_root": str(paths.project_root),
        "plist_path": str(paths.feedback_sync_plist_path),
        "launchd_label": FEEDBACK_SYNC_LAUNCHD_LABEL,
        "poll_interval_seconds": FEEDBACK_SYNC_INTERVAL_SECONDS,
        "program_arguments": [str(paths.feedback_sync_cycle_entrypoint_path)],
        "stdout_log_path": str(paths.feedback_sync_stdout_log_path),
        "stderr_log_path": str(paths.feedback_sync_stderr_log_path),
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


def begin_chat_operator_session(
    *,
    project_root: Path | str | None = None,
    session_id: str | None = None,
    started_at: str | None = None,
) -> dict[str, Any]:
    paths = ProjectPaths.from_root(project_root)
    migration = initialize_database(paths.db_path)
    current_timestamp = started_at or now_utc_iso()
    effective_session_id = session_id or f"jhc-chat-{uuid.uuid4().hex[:10]}"

    with connect_canonical_database(paths) as connection:
        control_state = read_agent_control_state(connection, timestamp=current_timestamp)
        if control_state.active_chat_session_id:
            raise ValueError(
                "Another jhc-chat session is already active: "
                f"{control_state.active_chat_session_id}"
            )

        updates: dict[str, str | bool | None] = {
            "active_chat_session_id": effective_session_id,
            "chat_resume_on_close": False,
            "last_chat_started_at": current_timestamp,
        }
        resume_on_close = False
        if control_state.agent_enabled and control_state.agent_mode == AGENT_MODE_RUNNING:
            resume_on_close = True
            updates.update(
                {
                    "agent_mode": AGENT_MODE_PAUSED,
                    "pause_reason": CHAT_INTERACTION_PAUSE_REASON,
                    "paused_at": current_timestamp,
                    "chat_resume_on_close": True,
                }
            )
        snapshot = upsert_control_values(connection, updates, timestamp=current_timestamp)

    append_jsonl_record(
        paths.chat_sessions_log_path,
        {
            "event": "begin",
            "session_id": effective_session_id,
            "recorded_at": current_timestamp,
            "resume_on_close": resume_on_close,
            "agent_mode_after_begin": snapshot.agent_mode,
            "pause_reason_after_begin": snapshot.pause_reason,
        },
    )
    runtime_pack = materialize_runtime_pack(paths.project_root)
    return {
        "contract_version": CONTRACT_VERSION,
        "produced_at": now_utc_iso(),
        "project_root": str(paths.project_root),
        "database": {
            "db_path": str(migration.db_path),
            "applied_migrations": migration.applied_migrations,
            "user_version": migration.user_version,
        },
        "status": "started",
        "session_id": effective_session_id,
        "resume_on_close": resume_on_close,
        "started_at": current_timestamp,
        "chat_sessions_log_path": str(paths.chat_sessions_log_path),
        "control_state": dict(snapshot.values),
        "runtime_pack": runtime_pack,
    }


def end_chat_operator_session(
    *,
    project_root: Path | str | None = None,
    session_id: str,
    exit_mode: str,
    ended_at: str | None = None,
) -> dict[str, Any]:
    if exit_mode not in CHAT_SESSION_EXIT_MODES:
        raise ValueError(f"Unsupported chat exit mode: {exit_mode}")

    paths = ProjectPaths.from_root(project_root)
    migration = initialize_database(paths.db_path)
    current_timestamp = ended_at or now_utc_iso()

    with connect_canonical_database(paths) as connection:
        control_state = read_agent_control_state(connection, timestamp=current_timestamp)
        active_session_id = control_state.active_chat_session_id
        if active_session_id and active_session_id != session_id:
            append_jsonl_record(
                paths.chat_sessions_log_path,
                {
                    "event": "end_ignored",
                    "session_id": session_id,
                    "active_session_id": active_session_id,
                    "exit_mode": exit_mode,
                    "recorded_at": current_timestamp,
                },
            )
            runtime_pack = materialize_runtime_pack(paths.project_root)
            return {
                "contract_version": CONTRACT_VERSION,
                "produced_at": now_utc_iso(),
                "project_root": str(paths.project_root),
                "database": {
                    "db_path": str(migration.db_path),
                    "applied_migrations": migration.applied_migrations,
                    "user_version": migration.user_version,
                },
                "status": "ignored_session_mismatch",
                "session_id": session_id,
                "active_session_id": active_session_id,
                "exit_mode": exit_mode,
                "chat_sessions_log_path": str(paths.chat_sessions_log_path),
                "control_state": dict(control_state.values),
                "runtime_pack": runtime_pack,
            }

        should_resume = (
            exit_mode == CHAT_SESSION_EXIT_MODE_EXPLICIT_CLOSE
            and control_state.chat_resume_on_close
            and control_state.agent_enabled
            and control_state.agent_mode == AGENT_MODE_PAUSED
            and control_state.pause_reason == CHAT_INTERACTION_PAUSE_REASON
        )
        updates: dict[str, str | bool | None] = {
            "active_chat_session_id": None,
            "chat_resume_on_close": False,
            "last_chat_ended_at": current_timestamp,
            "last_chat_exit_mode": exit_mode,
        }
        snapshot = upsert_control_values(connection, updates, timestamp=current_timestamp)
        if should_resume:
            snapshot = resume_agent(
                connection,
                manual_command="jhc-chat explicit_close",
                timestamp=current_timestamp,
            )

    append_jsonl_record(
        paths.chat_sessions_log_path,
        {
            "event": "end",
            "session_id": session_id,
            "exit_mode": exit_mode,
            "recorded_at": current_timestamp,
            "resumed_agent": should_resume,
            "agent_mode_after_end": snapshot.agent_mode,
            "pause_reason_after_end": snapshot.pause_reason,
        },
    )
    runtime_pack = materialize_runtime_pack(paths.project_root)
    return {
        "contract_version": CONTRACT_VERSION,
        "produced_at": now_utc_iso(),
        "project_root": str(paths.project_root),
        "database": {
            "db_path": str(migration.db_path),
            "applied_migrations": migration.applied_migrations,
            "user_version": migration.user_version,
        },
        "status": "ended",
        "session_id": session_id,
        "exit_mode": exit_mode,
        "resumed_agent": should_resume,
        "ended_at": current_timestamp,
        "chat_sessions_log_path": str(paths.chat_sessions_log_path),
        "control_state": dict(snapshot.values),
        "runtime_pack": runtime_pack,
    }


def execute_delayed_feedback_sync(
    *,
    project_root: Path | str | None = None,
    current_time: str | None = None,
    observer: MailboxFeedbackObserver | None = None,
) -> dict[str, Any]:
    paths = ProjectPaths.from_root(project_root)
    migration = initialize_database(paths.db_path)
    effective_time = current_time or now_utc_iso()

    with connect_canonical_database(paths) as connection:
        control_state = read_agent_control_state(connection, timestamp=effective_time)
        if not control_state.agent_enabled and control_state.agent_mode == AGENT_MODE_STOPPED:
            return {
                "contract_version": CONTRACT_VERSION,
                "produced_at": now_utc_iso(),
                "project_root": str(paths.project_root),
                "database": {
                    "db_path": str(migration.db_path),
                    "applied_migrations": migration.applied_migrations,
                    "user_version": migration.user_version,
                },
                "status": "skipped_agent_stopped",
                "current_time": effective_time,
                "control_state": dict(control_state.values),
            }

        result = sync_delivery_feedback(
            connection,
            project_root=paths.project_root,
            current_time=effective_time,
            scheduler_name=FEEDBACK_SYNC_SCHEDULER_NAME,
            scheduler_type=FEEDBACK_SYNC_SCHEDULER_TYPE,
            observation_scope=OBSERVATION_SCOPE_DELAYED,
            observer=observer,
        )

    return {
        "contract_version": CONTRACT_VERSION,
        "produced_at": now_utc_iso(),
        "project_root": str(paths.project_root),
        "database": {
            "db_path": str(migration.db_path),
            "applied_migrations": migration.applied_migrations,
            "user_version": migration.user_version,
        },
        "status": "completed",
        "current_time": effective_time,
        "control_state": dict(control_state.values),
        "feedback_sync": result.as_dict(),
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
