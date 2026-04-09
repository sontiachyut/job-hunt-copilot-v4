from __future__ import annotations

import json
import plistlib
import re
import sqlite3
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .chat_runtime import build_chat_startup_dashboard, render_chat_startup_dashboard
from .contracts import CONTRACT_VERSION
from .db import initialize_database
from .delivery_feedback import (
    DELAYED_FEEDBACK_POLL_INTERVAL_MINUTES,
    OBSERVATION_SCOPE_DELAYED,
    MailboxFeedbackObserver,
    sync_delivery_feedback,
)
from .paths import ProjectPaths
from .records import new_canonical_id, now_utc_iso
from .runtime_pack import materialize_runtime_pack, write_text_atomic
from .supervisor import (
    AGENT_MODE_PAUSED,
    AGENT_MODE_RUNNING,
    AGENT_MODE_STOPPED,
    NON_TERMINAL_RUN_STATUSES,
    begin_replanning,
    complete_pipeline_run,
    pause_agent,
    read_agent_control_state,
    record_override_event,
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
SUPERVISOR_SLEEP_WAKE_FALLBACK_GAP_HOURS = 1
SUPERVISOR_SLEEP_WAKE_FALLBACK_GAP_SECONDS = SUPERVISOR_SLEEP_WAKE_FALLBACK_GAP_HOURS * 3600
SUPERVISOR_SLEEP_WAKE_FALLBACK_METHOD = "gap_fallback"
FEEDBACK_SYNC_LAUNCHD_LABEL = "com.jobhuntcopilot.feedback-sync"
FEEDBACK_SYNC_INTERVAL_SECONDS = DELAYED_FEEDBACK_POLL_INTERVAL_MINUTES * 60
FEEDBACK_SYNC_SCHEDULER_NAME = "job-hunt-copilot-feedback-sync"
FEEDBACK_SYNC_SCHEDULER_TYPE = "launchd"
LOCAL_RUNTIME_COMPONENT = "local_runtime_control"
JOB_POSTING_STATUS_SOURCED = "sourced"
JOB_POSTING_STATUS_TAILORING_IN_PROGRESS = "tailoring_in_progress"
JOB_POSTING_STATUS_RESUME_REVIEW_PENDING = "resume_review_pending"
JOB_POSTING_STATUS_REQUIRES_CONTACTS = "requires_contacts"
JOB_POSTING_STATUS_READY_FOR_OUTREACH = "ready_for_outreach"
JOB_POSTING_STATUS_OUTREACH_IN_PROGRESS = "outreach_in_progress"
JOB_POSTING_STATUS_ABANDONED = "abandoned"
ABANDONABLE_POSTING_STATUSES = frozenset(
    {
        JOB_POSTING_STATUS_SOURCED,
        JOB_POSTING_STATUS_TAILORING_IN_PROGRESS,
        JOB_POSTING_STATUS_RESUME_REVIEW_PENDING,
        JOB_POSTING_STATUS_REQUIRES_CONTACTS,
        JOB_POSTING_STATUS_READY_FOR_OUTREACH,
        JOB_POSTING_STATUS_OUTREACH_IN_PROGRESS,
    }
)
CHAT_SESSION_EXIT_MODE_EXPLICIT_CLOSE = "explicit_close"
CHAT_SESSION_EXIT_MODE_UNEXPECTED_EXIT = "unexpected_exit"
CHAT_SESSION_EXIT_MODES = frozenset(
    {
        CHAT_SESSION_EXIT_MODE_EXPLICIT_CLOSE,
        CHAT_SESSION_EXIT_MODE_UNEXPECTED_EXIT,
    }
)
CHAT_INTERACTION_PAUSE_REASON = "expert_interaction"
PMSET_EVENT_LINE_PATTERN = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} [+-]\d{4})\s+(?P<body>.+)$"
)


def _run_system_command(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=False, capture_output=True, text=True)


def _parse_utc_iso(timestamp: str) -> datetime:
    normalized = timestamp.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized).astimezone(timezone.utc)


def _format_utc_iso(timestamp: datetime) -> str:
    return timestamp.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _latest_timestamp(*timestamps: str | None) -> str | None:
    populated = [timestamp for timestamp in timestamps if timestamp]
    if not populated:
        return None
    return max(populated, key=_parse_utc_iso)


def _latest_supervisor_cycle_checkpoint_at(connection: sqlite3.Connection) -> str | None:
    row = connection.execute(
        """
        SELECT COALESCE(
          MAX(COALESCE(completed_at, started_at)),
          ''
        )
        FROM supervisor_cycles
        """
    ).fetchone()
    if row is None:
        return None
    return row[0] or None


def _read_pmset_uuid() -> str | None:
    result = _run_system_command(["pmset", "-g", "uuid"])
    if result.returncode != 0:
        return None
    uuid_text = result.stdout.strip()
    return uuid_text or None


def _classify_pmset_event(body: str) -> str | None:
    if "MaintenanceWake" in body:
        return None
    if re.search(r"\bDarkWake\b", body):
        return "DarkWake"
    if re.search(r"\bWake\b", body):
        return "Wake"
    if re.search(r"\bSleep\b", body):
        return "Sleep"
    return None


def _find_recent_pmset_sleep_wake_event(
    *,
    since: str | None,
) -> dict[str, Any] | None:
    result = _run_system_command(["pmset", "-g", "log"])
    if result.returncode != 0:
        return None

    since_dt = _parse_utc_iso(since) if since else None
    pmset_uuid = _read_pmset_uuid()
    for raw_line in reversed(result.stdout.splitlines()):
        match = PMSET_EVENT_LINE_PATTERN.match(raw_line)
        if match is None:
            continue
        event_type = _classify_pmset_event(match.group("body"))
        if event_type is None:
            continue
        event_dt = datetime.strptime(match.group("timestamp"), "%Y-%m-%d %H:%M:%S %z").astimezone(
            timezone.utc
        )
        if since_dt is not None and event_dt <= since_dt:
            break
        event_timestamp = _format_utc_iso(event_dt)
        uuid_fragment = pmset_uuid or "unknown-uuid"
        return {
            "detection_method": SUPERVISOR_SLEEP_WAKE_DETECTION_METHOD,
            "event_type": event_type,
            "event_timestamp": event_timestamp,
            "event_ref": f"pmset:{uuid_fragment}:{event_type.lower()}:{event_timestamp}",
            "pmset_uuid": pmset_uuid,
            "source_line": raw_line.strip(),
        }
    return None


def _build_gap_fallback_recovery_context(
    *,
    current_time: str,
    reference_cycle_at: str,
) -> dict[str, Any] | None:
    gap_seconds = int((_parse_utc_iso(current_time) - _parse_utc_iso(reference_cycle_at)).total_seconds())
    if gap_seconds <= SUPERVISOR_SLEEP_WAKE_FALLBACK_GAP_SECONDS:
        return None
    return {
        "detection_method": SUPERVISOR_SLEEP_WAKE_FALLBACK_METHOD,
        "event_type": "GapRecovery",
        "event_timestamp": current_time,
        "event_ref": f"gap_fallback:{reference_cycle_at}->{current_time}",
        "reference_cycle_at": reference_cycle_at,
        "gap_seconds": gap_seconds,
        "fallback_gap_hours": SUPERVISOR_SLEEP_WAKE_FALLBACK_GAP_HOURS,
    }


def detect_sleep_wake_recovery(
    connection: sqlite3.Connection,
    *,
    current_time: str,
) -> tuple[dict[str, str], dict[str, Any] | None]:
    control_state = read_agent_control_state(connection, timestamp=current_time)
    latest_cycle_at = _latest_supervisor_cycle_checkpoint_at(connection)
    pmset_since = _latest_timestamp(control_state.last_sleep_wake_check_at, latest_cycle_at)

    recovery_context = _find_recent_pmset_sleep_wake_event(since=pmset_since)
    if recovery_context is None and latest_cycle_at is not None:
        recovery_context = _build_gap_fallback_recovery_context(
            current_time=current_time,
            reference_cycle_at=latest_cycle_at,
        )

    updates: dict[str, str | bool | None] = {
        "last_sleep_wake_check_at": current_time,
    }
    if recovery_context is not None:
        if recovery_context["event_type"] == "Sleep":
            updates["last_seen_sleep_event_at"] = recovery_context["event_timestamp"]
        elif recovery_context["event_type"] in {"Wake", "DarkWake"}:
            updates["last_seen_wake_event_at"] = recovery_context["event_timestamp"]
        updates["last_sleep_wake_event_ref"] = recovery_context["event_ref"]

    snapshot = upsert_control_values(connection, updates, timestamp=current_time)
    return dict(snapshot.values), recovery_context


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


def _record_state_transition(
    connection: sqlite3.Connection,
    *,
    object_type: str,
    object_id: str,
    stage: str,
    previous_state: str,
    new_state: str,
    transition_timestamp: str,
    transition_reason: str | None,
    lead_id: str | None,
    job_posting_id: str | None,
) -> str:
    state_transition_event_id = new_canonical_id("state_transition_events")
    connection.execute(
        """
        INSERT INTO state_transition_events (
          state_transition_event_id, object_type, object_id, stage, previous_state,
          new_state, transition_timestamp, transition_reason, caused_by, lead_id,
          job_posting_id, contact_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            LOCAL_RUNTIME_COMPONENT,
            lead_id,
            job_posting_id,
            None,
        ),
    )
    return state_transition_event_id


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


def abandon_job_posting(
    job_posting_id: str,
    *,
    project_root: Path | str | None = None,
    reason: str | None = None,
    manual_command: str | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    normalized_job_posting_id = job_posting_id.strip()
    if not normalized_job_posting_id:
        raise ValueError("job_posting_id is required for the abandon command.")

    paths = ProjectPaths.from_root(project_root)
    migration = initialize_database(paths.db_path)
    current_timestamp = timestamp or now_utc_iso()
    reason_text = (reason or "The posting was explicitly abandoned by the expert.").strip()

    with connect_canonical_database(paths) as connection:
        posting_row = connection.execute(
            """
            SELECT lead_id, posting_status
            FROM job_postings
            WHERE job_posting_id = ?
            """,
            (normalized_job_posting_id,),
        ).fetchone()
        if posting_row is None:
            raise ValueError(f"job_posting {normalized_job_posting_id!r} does not exist.")

        lead_id = str(posting_row["lead_id"]) if posting_row["lead_id"] else None
        previous_status = str(posting_row["posting_status"] or "").strip()
        if (
            previous_status != JOB_POSTING_STATUS_ABANDONED
            and previous_status not in ABANDONABLE_POSTING_STATUSES
        ):
            raise ValueError(
                "Only non-terminal active postings may be abandoned; "
                f"job_posting {normalized_job_posting_id!r} is at "
                f"posting_status={previous_status!r}."
            )

        control_state = read_agent_control_state(connection, timestamp=current_timestamp)
        open_pipeline_rows = connection.execute(
            """
            SELECT pipeline_run_id, run_status, current_stage
            FROM pipeline_runs
            WHERE job_posting_id = ?
              AND run_status IN ({})
            ORDER BY started_at ASC, pipeline_run_id ASC
            """.format(",".join("?" for _ in NON_TERMINAL_RUN_STATUSES)),
            (
                normalized_job_posting_id,
                *sorted(NON_TERMINAL_RUN_STATUSES),
            ),
        ).fetchall()

        override_event = None
        state_transition_event_id = None
        if previous_status != JOB_POSTING_STATUS_ABANDONED:
            with connection:
                connection.execute(
                    """
                    UPDATE job_postings
                    SET posting_status = ?, updated_at = ?
                    WHERE job_posting_id = ?
                    """,
                    (
                        JOB_POSTING_STATUS_ABANDONED,
                        current_timestamp,
                        normalized_job_posting_id,
                    ),
                )
                state_transition_event_id = _record_state_transition(
                    connection,
                    object_type="job_postings",
                    object_id=normalized_job_posting_id,
                    stage="posting_status",
                    previous_state=previous_status,
                    new_state=JOB_POSTING_STATUS_ABANDONED,
                    transition_timestamp=current_timestamp,
                    transition_reason=reason_text,
                    lead_id=lead_id,
                    job_posting_id=normalized_job_posting_id,
                )
                override_event = record_override_event(
                    connection,
                    object_type="job_postings",
                    object_id=normalized_job_posting_id,
                    component_stage="posting_status",
                    previous_value=previous_status,
                    new_value=JOB_POSTING_STATUS_ABANDONED,
                    override_reason=reason_text,
                    override_by="owner",
                    lead_id=lead_id,
                    job_posting_id=normalized_job_posting_id,
                    override_timestamp=current_timestamp,
                )

        retired_pipeline_runs: list[dict[str, str]] = []
        for row in open_pipeline_rows:
            previous_run_status = str(row["run_status"])
            previous_stage = str(row["current_stage"])
            run_summary = (
                f"The linked job_posting {normalized_job_posting_id} was explicitly abandoned "
                "by the expert."
            )
            if previous_status == JOB_POSTING_STATUS_ABANDONED:
                run_summary = (
                    f"The linked job_posting {normalized_job_posting_id} was already "
                    "abandoned; the stray active pipeline_run was retired."
                )
            completed_run = complete_pipeline_run(
                connection,
                str(row["pipeline_run_id"]),
                current_stage=JOB_POSTING_STATUS_ABANDONED,
                run_summary=run_summary,
                timestamp=current_timestamp,
            )
            retired_pipeline_runs.append(
                {
                    "pipeline_run_id": completed_run.pipeline_run_id,
                    "previous_run_status": previous_run_status,
                    "new_run_status": completed_run.run_status,
                    "previous_stage": previous_stage,
                    "new_stage": completed_run.current_stage,
                }
            )

        current_posting = connection.execute(
            """
            SELECT lead_id, posting_status, updated_at
            FROM job_postings
            WHERE job_posting_id = ?
            """,
            (normalized_job_posting_id,),
        ).fetchone()
        status = (
            "abandoned"
            if previous_status != JOB_POSTING_STATUS_ABANDONED
            else "already_abandoned"
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
        "command": "abandon",
        "status": status,
        "job_posting": {
            "job_posting_id": normalized_job_posting_id,
            "lead_id": str(current_posting["lead_id"]) if current_posting["lead_id"] else None,
            "previous_status": previous_status,
            "posting_status": str(current_posting["posting_status"]),
            "updated_at": str(current_posting["updated_at"]),
        },
        "retired_pipeline_runs": retired_pipeline_runs,
        "state_transition_event_id": state_transition_event_id,
        "override_event_id": None if override_event is None else override_event.override_event_id,
        "manual_command": manual_command,
        "control_state": dict(control_state.values),
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
        startup_dashboard = build_chat_startup_dashboard(
            connection,
            project_root=paths.project_root,
            current_time=current_timestamp,
            agent_mode=snapshot.agent_mode,
            pause_reason=snapshot.pause_reason,
        )

    startup_briefing = render_chat_startup_dashboard(startup_dashboard)
    write_text_atomic(paths.ops_agent_chat_startup_path, startup_briefing)

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
        "startup_briefing_path": str(paths.ops_agent_chat_startup_path),
        "startup_briefing": startup_briefing,
        "startup_dashboard": startup_dashboard,
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
    effective_started_at = started_at or now_utc_iso()

    with connect_canonical_database(paths) as connection:
        control_state_values, sleep_wake_recovery_context = detect_sleep_wake_recovery(
            connection,
            current_time=effective_started_at,
        )
        execution = run_supervisor_cycle(
            connection,
            paths,
            trigger_type=SUPERVISOR_TRIGGER_TYPE,
            scheduler_name=SUPERVISOR_SCHEDULER_NAME,
            sleep_wake_detection_method=(
                sleep_wake_recovery_context["detection_method"]
                if sleep_wake_recovery_context is not None
                else SUPERVISOR_SLEEP_WAKE_DETECTION_METHOD
            ),
            sleep_wake_event_ref=(
                sleep_wake_recovery_context["event_ref"]
                if sleep_wake_recovery_context is not None
                else None
            ),
            started_at=effective_started_at,
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
            "sleep_wake_detection_method": execution.cycle.sleep_wake_detection_method,
            "sleep_wake_event_ref": execution.cycle.sleep_wake_event_ref,
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
        "pre_cycle_control_state": control_state_values,
        "sleep_wake_recovery_context": sleep_wake_recovery_context,
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
