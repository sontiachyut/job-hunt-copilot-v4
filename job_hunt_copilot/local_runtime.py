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
from .resume_tailoring import (
    RESUME_REVIEW_STATUS_APPROVED,
    RESUME_REVIEW_STATUS_REJECTED,
    ResumeTailoringError,
    record_tailoring_review_override,
)
from .runtime_pack import materialize_runtime_pack, write_text_atomic
from .supervisor import (
    AGENT_MODE_PAUSED,
    AGENT_MODE_RUNNING,
    AGENT_MODE_STOPPED,
    NON_TERMINAL_RUN_STATUSES,
    begin_replanning,
    complete_pipeline_run,
    create_agent_incident,
    get_agent_incident,
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
CHAT_IDLE_TIMEOUT_MINUTES = 15
CHAT_IDLE_TIMEOUT_SECONDS = CHAT_IDLE_TIMEOUT_MINUTES * 60
OBJECT_OVERRIDE_TYPE_JOB_POSTING = "job_posting"
OBJECT_OVERRIDE_TYPE_TAILORING_REVIEW = "tailoring_review"
SUPPORTED_OBJECT_OVERRIDE_TYPES = frozenset(
    {
        OBJECT_OVERRIDE_TYPE_JOB_POSTING,
        OBJECT_OVERRIDE_TYPE_TAILORING_REVIEW,
    }
)
SUPPORTED_TAILORING_REVIEW_OVERRIDE_DECISIONS = frozenset(
    {
        RESUME_REVIEW_STATUS_APPROVED,
        RESUME_REVIEW_STATUS_REJECTED,
    }
)
GUIDANCE_SCOPE_CURRENT_ONLY = "current_only"
GUIDANCE_SCOPE_CURRENT_AND_SIMILAR_FUTURE = "current_and_similar_future"
GUIDANCE_SCOPES = frozenset(
    {
        GUIDANCE_SCOPE_CURRENT_ONLY,
        GUIDANCE_SCOPE_CURRENT_AND_SIMILAR_FUTURE,
    }
)
GUIDANCE_REQUEST_KIND_CONFLICT = "conflict"
GUIDANCE_REQUEST_KIND_UNCERTAINTY = "uncertainty"
GUIDANCE_REQUEST_KINDS = frozenset(
    {
        GUIDANCE_REQUEST_KIND_CONFLICT,
        GUIDANCE_REQUEST_KIND_UNCERTAINTY,
    }
)
GUIDANCE_CONFLICT_INCIDENT_TYPE = "expert_guidance_conflict"
GUIDANCE_CLARIFICATION_INCIDENT_TYPE = "expert_guidance_clarification"
GUIDANCE_CLARIFICATION_PAUSE_REASON = "expert_guidance_clarification"
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


def maybe_resume_after_chat_idle_timeout(
    connection: sqlite3.Connection,
    *,
    current_time: str,
) -> tuple[dict[str, str], dict[str, Any] | None]:
    control_state = read_agent_control_state(connection, timestamp=current_time)
    if not control_state.agent_enabled or control_state.agent_mode != AGENT_MODE_PAUSED:
        return dict(control_state.values), None
    if control_state.pause_reason != CHAT_INTERACTION_PAUSE_REASON:
        return dict(control_state.values), None
    if control_state.active_chat_session_id:
        return dict(control_state.values), None
    if control_state.last_chat_exit_mode != CHAT_SESSION_EXIT_MODE_UNEXPECTED_EXIT:
        return dict(control_state.values), None

    idle_reference_at = control_state.last_chat_ended_at or control_state.paused_at
    if not idle_reference_at:
        return dict(control_state.values), None

    idle_seconds = int((_parse_utc_iso(current_time) - _parse_utc_iso(idle_reference_at)).total_seconds())
    if idle_seconds < CHAT_IDLE_TIMEOUT_SECONDS:
        return dict(control_state.values), None

    resumed = resume_agent(
        connection,
        manual_command="jhc-chat idle-timeout-auto-resume",
        timestamp=current_time,
    )
    return dict(resumed.values), {
        "resume_reason": "unexpected_chat_exit_idle_timeout",
        "resumed_at": current_time,
        "idle_reference_at": idle_reference_at,
        "idle_seconds": idle_seconds,
        "idle_timeout_minutes": CHAT_IDLE_TIMEOUT_MINUTES,
        "last_chat_exit_mode": control_state.last_chat_exit_mode,
        "previous_pause_reason": control_state.pause_reason,
    }


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


def _normalize_guidance_object_type(object_type: str) -> str:
    normalized = object_type.strip()
    if not normalized:
        raise ValueError("object_type is required for expert guidance commands.")
    return {
        "job_posting": "job_postings",
        "job_postings": "job_postings",
        "contact": "contacts",
        "contacts": "contacts",
        "resume_tailoring_run": "resume_tailoring_runs",
        "resume_tailoring_runs": "resume_tailoring_runs",
        "tailoring_review": "resume_tailoring_runs",
    }.get(normalized, normalized)


def _guidance_pause_reason(directive_key: str) -> str:
    sanitized_key = re.sub(r"[^a-z0-9_]+", "_", directive_key.strip().lower()).strip("_")
    suffix = sanitized_key or "general"
    return f"{GUIDANCE_CONFLICT_INCIDENT_TYPE}:{suffix}"


def _parse_override_json_payload(raw_value: str | None) -> dict[str, Any]:
    if not raw_value:
        return {}
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _resolve_guidance_linkage(
    connection: sqlite3.Connection,
    *,
    object_type: str,
    object_id: str,
) -> tuple[str | None, str | None, str | None]:
    if object_type == "job_postings":
        row = connection.execute(
            """
            SELECT lead_id
            FROM job_postings
            WHERE job_posting_id = ?
            """,
            (object_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"job_posting {object_id!r} does not exist.")
        return (str(row["lead_id"]) if row["lead_id"] else None, object_id, None)

    if object_type == "contacts":
        row = connection.execute(
            """
            SELECT contact_id
            FROM contacts
            WHERE contact_id = ?
            """,
            (object_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"contact {object_id!r} does not exist.")
        return (None, None, object_id)

    if object_type == "resume_tailoring_runs":
        row = connection.execute(
            """
            SELECT rtr.job_posting_id, jp.lead_id
            FROM resume_tailoring_runs rtr
            LEFT JOIN job_postings jp
              ON jp.job_posting_id = rtr.job_posting_id
            WHERE rtr.resume_tailoring_run_id = ?
            """,
            (object_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"resume_tailoring_run {object_id!r} does not exist.")
        return (
            str(row["lead_id"]) if row["lead_id"] else None,
            str(row["job_posting_id"]) if row["job_posting_id"] else None,
            None,
        )

    return (None, None, None)


def _list_guidance_override_rows(
    connection: sqlite3.Connection,
    *,
    object_type: str,
    component_stage: str,
) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT override_event_id, object_type, object_id, component_stage, previous_value,
               new_value, override_reason, override_timestamp
        FROM override_events
        WHERE object_type = ?
          AND component_stage = ?
        ORDER BY override_timestamp DESC, override_event_id DESC
        """,
        (object_type, component_stage),
    ).fetchall()


def _find_latest_guidance_override(
    connection: sqlite3.Connection,
    *,
    object_type: str,
    object_id: str,
    component_stage: str,
    directive_key: str,
) -> tuple[sqlite3.Row, dict[str, Any]] | None:
    rows = connection.execute(
        """
        SELECT override_event_id, object_type, object_id, component_stage, previous_value,
               new_value, override_reason, override_timestamp
        FROM override_events
        WHERE object_type = ?
          AND object_id = ?
          AND component_stage = ?
        ORDER BY override_timestamp DESC, override_event_id DESC
        """,
        (object_type, object_id, component_stage),
    ).fetchall()
    for row in rows:
        payload = _parse_override_json_payload(str(row["new_value"] or ""))
        if payload.get("directive_key") == directive_key:
            return row, payload
    return None


def _list_conflicting_guidance_overrides(
    connection: sqlite3.Connection,
    *,
    object_type: str,
    component_stage: str,
    directive_key: str,
    directive_value: str,
) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    for row in _list_guidance_override_rows(
        connection,
        object_type=object_type,
        component_stage=component_stage,
    ):
        payload = _parse_override_json_payload(str(row["new_value"] or ""))
        if payload.get("directive_key") != directive_key:
            continue
        if payload.get("guidance_scope") != GUIDANCE_SCOPE_CURRENT_AND_SIMILAR_FUTURE:
            continue
        if payload.get("directive_value") == directive_value:
            continue
        conflicts.append(
            {
                "override_event_id": str(row["override_event_id"]),
                "object_id": str(row["object_id"]),
                "override_timestamp": str(row["override_timestamp"]),
                "directive_value": str(payload.get("directive_value") or ""),
                "guidance_scope": str(payload.get("guidance_scope") or ""),
                "source_guidance_override_event_id": payload.get(
                    "source_guidance_override_event_id"
                ),
            }
        )
    return conflicts


def _find_existing_guidance_incident(
    connection: sqlite3.Connection,
    *,
    incident_type: str,
    escalation_reason: str,
    lead_id: str | None,
    job_posting_id: str | None,
    contact_id: str | None,
) -> Any | None:
    row = connection.execute(
        """
        SELECT agent_incident_id
        FROM agent_incidents
        WHERE incident_type = ?
          AND status IN ('open', 'in_repair', 'escalated')
          AND COALESCE(lead_id, '') = COALESCE(?, '')
          AND COALESCE(job_posting_id, '') = COALESCE(?, '')
          AND COALESCE(contact_id, '') = COALESCE(?, '')
          AND COALESCE(escalation_reason, '') = ?
        ORDER BY updated_at DESC, created_at DESC, agent_incident_id DESC
        LIMIT 1
        """,
        (
            incident_type,
            lead_id,
            job_posting_id,
            contact_id,
            escalation_reason,
        ),
    ).fetchone()
    if row is None:
        return None
    return get_agent_incident(connection, str(row["agent_incident_id"]))


def _ensure_guidance_incident(
    connection: sqlite3.Connection,
    *,
    incident_type: str,
    severity: str,
    summary: str,
    escalation_reason_payload: dict[str, Any],
    lead_id: str | None,
    job_posting_id: str | None,
    contact_id: str | None,
    created_at: str,
) -> Any:
    escalation_reason = json.dumps(escalation_reason_payload, sort_keys=True)
    existing = _find_existing_guidance_incident(
        connection,
        incident_type=incident_type,
        escalation_reason=escalation_reason,
        lead_id=lead_id,
        job_posting_id=job_posting_id,
        contact_id=contact_id,
    )
    if existing is not None:
        return existing
    return create_agent_incident(
        connection,
        incident_type=incident_type,
        severity=severity,
        summary=summary,
        lead_id=lead_id,
        job_posting_id=job_posting_id,
        contact_id=contact_id,
        escalation_reason=escalation_reason,
        created_at=created_at,
    )


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


def apply_object_override(
    object_type: str,
    object_id: str,
    *,
    new_value: str,
    reason: str | None,
    project_root: Path | str | None = None,
    manual_command: str | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    normalized_object_type = object_type.strip()
    normalized_object_id = object_id.strip()
    normalized_new_value = new_value.strip()
    reason_text = (reason or "").strip()

    if normalized_object_type not in SUPPORTED_OBJECT_OVERRIDE_TYPES:
        supported_types = ", ".join(sorted(SUPPORTED_OBJECT_OVERRIDE_TYPES))
        raise ValueError(
            f"Unsupported object_type={normalized_object_type!r}. Supported values: {supported_types}."
        )
    if not normalized_object_id:
        raise ValueError("object_id is required for the override command.")
    if not normalized_new_value:
        raise ValueError("new_value is required for the override command.")
    if not reason_text:
        raise ValueError("Override reason is required for the override command.")

    if normalized_object_type == OBJECT_OVERRIDE_TYPE_JOB_POSTING:
        if normalized_new_value != JOB_POSTING_STATUS_ABANDONED:
            raise ValueError(
                "Supported job_posting override values: 'abandoned'."
            )
        report = abandon_job_posting(
            normalized_object_id,
            project_root=project_root,
            reason=reason_text,
            manual_command=manual_command or "override",
            timestamp=timestamp,
        )
        report["command"] = "override"
        report["override_target"] = {
            "object_type": normalized_object_type,
            "object_id": normalized_object_id,
            "component_stage": "posting_status",
            "new_value": normalized_new_value,
        }
        return report

    if normalized_new_value not in SUPPORTED_TAILORING_REVIEW_OVERRIDE_DECISIONS:
        supported_decisions = ", ".join(sorted(SUPPORTED_TAILORING_REVIEW_OVERRIDE_DECISIONS))
        raise ValueError(
            "Supported tailoring_review override values: "
            f"{supported_decisions}."
        )

    paths = ProjectPaths.from_root(project_root)
    migration = initialize_database(paths.db_path)
    current_timestamp = timestamp or now_utc_iso()

    with connect_canonical_database(paths) as connection:
        try:
            result = record_tailoring_review_override(
                connection,
                paths,
                job_posting_id=normalized_object_id,
                decision_type=normalized_new_value,
                override_reason=reason_text,
                decision_notes=reason_text,
                timestamp=current_timestamp,
            )
        except ResumeTailoringError as exc:
            raise ValueError(str(exc)) from exc

        control_state = read_agent_control_state(connection, timestamp=current_timestamp)

    return {
        "contract_version": CONTRACT_VERSION,
        "produced_at": now_utc_iso(),
        "project_root": str(paths.project_root),
        "database": {
            "db_path": str(migration.db_path),
            "applied_migrations": migration.applied_migrations,
            "user_version": migration.user_version,
        },
        "command": "override",
        "status": "completed",
        "override_target": {
            "object_type": normalized_object_type,
            "object_id": normalized_object_id,
            "component_stage": "resume_review_status",
            "new_value": normalized_new_value,
        },
        "job_posting": {
            "job_posting_id": result.job_posting_id,
            "posting_status": result.posting_status,
        },
        "resume_tailoring_run": {
            "resume_tailoring_run_id": result.resume_tailoring_run_id,
            "resume_review_status": result.run.resume_review_status,
            "tailoring_status": result.run.tailoring_status,
            "workspace_path": result.run.workspace_path,
        },
        "review_artifact": {
            "artifact_type": result.review_artifact.record.artifact_type,
            "path": result.review_artifact.location.relative_path,
        },
        "override_event_id": (
            None
            if result.override_event is None
            else result.override_event.override_event_id
        ),
        "manual_command": manual_command,
        "control_state": dict(control_state.values),
    }


def persist_expert_guidance(
    object_type: str,
    object_id: str,
    *,
    component_stage: str,
    directive_key: str,
    directive_value: str,
    reason: str,
    guidance_scope: str = GUIDANCE_SCOPE_CURRENT_AND_SIMILAR_FUTURE,
    source_override_event_id: str | None = None,
    project_root: Path | str | None = None,
    manual_command: str | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    normalized_object_type = _normalize_guidance_object_type(object_type)
    normalized_object_id = object_id.strip()
    normalized_component_stage = component_stage.strip()
    normalized_directive_key = directive_key.strip()
    normalized_directive_value = directive_value.strip()
    normalized_reason = reason.strip()
    normalized_source_override_event_id = (
        source_override_event_id.strip() if source_override_event_id else None
    )

    if not normalized_object_id:
        raise ValueError("object_id is required for the guidance command.")
    if not normalized_component_stage:
        raise ValueError("component_stage is required for the guidance command.")
    if not normalized_directive_key:
        raise ValueError("directive_key is required for the guidance command.")
    if not normalized_directive_value:
        raise ValueError("directive_value is required for the guidance command.")
    if not normalized_reason:
        raise ValueError("reason is required for the guidance command.")
    if guidance_scope not in GUIDANCE_SCOPES:
        supported_scopes = ", ".join(sorted(GUIDANCE_SCOPES))
        raise ValueError(
            f"Unsupported guidance scope={guidance_scope!r}. Supported values: {supported_scopes}."
        )

    paths = ProjectPaths.from_root(project_root)
    migration = initialize_database(paths.db_path)
    current_timestamp = timestamp or now_utc_iso()

    with connect_canonical_database(paths) as connection:
        lead_id, job_posting_id, contact_id = _resolve_guidance_linkage(
            connection,
            object_type=normalized_object_type,
            object_id=normalized_object_id,
        )

        if normalized_source_override_event_id is not None:
            source_row = connection.execute(
                """
                SELECT override_event_id
                FROM override_events
                WHERE override_event_id = ?
                """,
                (normalized_source_override_event_id,),
            ).fetchone()
            if source_row is None:
                raise ValueError(
                    "source_override_event_id "
                    f"{normalized_source_override_event_id!r} does not exist."
                )

        latest_guidance = _find_latest_guidance_override(
            connection,
            object_type=normalized_object_type,
            object_id=normalized_object_id,
            component_stage=normalized_component_stage,
            directive_key=normalized_directive_key,
        )
        latest_row = latest_guidance[0] if latest_guidance is not None else None
        latest_payload = latest_guidance[1] if latest_guidance is not None else {}
        latest_source_override_event_id = (
            str(latest_payload.get("source_guidance_override_event_id") or "")
            if latest_payload
            else ""
        )

        requested_source_override_event_id = (
            normalized_source_override_event_id
            or latest_source_override_event_id
            or None
        )
        if (
            latest_row is not None
            and latest_payload.get("directive_value") == normalized_directive_value
            and latest_payload.get("guidance_scope") == guidance_scope
            and (
                normalized_source_override_event_id is None
                or latest_source_override_event_id == normalized_source_override_event_id
            )
        ):
            control_state = read_agent_control_state(connection, timestamp=current_timestamp)
            return {
                "contract_version": CONTRACT_VERSION,
                "produced_at": now_utc_iso(),
                "project_root": str(paths.project_root),
                "database": {
                    "db_path": str(migration.db_path),
                    "applied_migrations": migration.applied_migrations,
                    "user_version": migration.user_version,
                },
                "command": "guidance",
                "status": "already_live",
                "guidance": {
                    "object_type": normalized_object_type,
                    "object_id": normalized_object_id,
                    "component_stage": normalized_component_stage,
                    "directive_key": normalized_directive_key,
                    "directive_value": normalized_directive_value,
                    "guidance_scope": guidance_scope,
                    "applies_to_similar_future_cases": (
                        guidance_scope == GUIDANCE_SCOPE_CURRENT_AND_SIMILAR_FUTURE
                    ),
                    "source_guidance_override_event_id": (
                        latest_payload.get("source_guidance_override_event_id")
                        or str(latest_row["override_event_id"])
                    ),
                    "override_event_id": str(latest_row["override_event_id"]),
                    "override_timestamp": str(latest_row["override_timestamp"]),
                },
                "conflict": None,
                "manual_command": manual_command,
                "control_state": dict(control_state.values),
            }

        conflicts = _list_conflicting_guidance_overrides(
            connection,
            object_type=normalized_object_type,
            component_stage=normalized_component_stage,
            directive_key=normalized_directive_key,
            directive_value=normalized_directive_value,
        )

        requested_source_override_event_id = (
            requested_source_override_event_id or "__self__"
        )
        guidance_payload = {
            "directive_key": normalized_directive_key,
            "directive_value": normalized_directive_value,
            "guidance_scope": guidance_scope,
            "applies_to_similar_future_cases": (
                guidance_scope == GUIDANCE_SCOPE_CURRENT_AND_SIMILAR_FUTURE
            ),
            "source_guidance_override_event_id": requested_source_override_event_id,
            "recorded_at": current_timestamp,
            "recorded_via": manual_command or "guidance",
        }
        previous_payload = latest_payload if latest_payload else {}
        override_event = record_override_event(
            connection,
            object_type=normalized_object_type,
            object_id=normalized_object_id,
            component_stage=normalized_component_stage,
            previous_value=json.dumps(previous_payload, sort_keys=True),
            new_value=json.dumps(guidance_payload, sort_keys=True),
            override_reason=normalized_reason,
            override_by="owner",
            lead_id=lead_id,
            job_posting_id=job_posting_id,
            contact_id=contact_id,
            override_timestamp=current_timestamp,
        )
        if requested_source_override_event_id == "__self__":
            guidance_payload["source_guidance_override_event_id"] = (
                override_event.override_event_id
            )
            with connection:
                connection.execute(
                    """
                    UPDATE override_events
                    SET new_value = ?
                    WHERE override_event_id = ?
                    """,
                    (
                        json.dumps(guidance_payload, sort_keys=True),
                        override_event.override_event_id,
                    ),
                )

        control_state = read_agent_control_state(connection, timestamp=current_timestamp)
        conflict_report = None
        status = "guidance_persisted"
        if conflicts:
            conflict_summary = (
                "Conflicting standing expert guidance requires clarification before "
                "autonomous progression resumes."
            )
            conflict_incident = _ensure_guidance_incident(
                connection,
                incident_type=GUIDANCE_CONFLICT_INCIDENT_TYPE,
                severity="high",
                summary=conflict_summary,
                escalation_reason_payload={
                    "kind": GUIDANCE_REQUEST_KIND_CONFLICT,
                    "object_type": normalized_object_type,
                    "object_id": normalized_object_id,
                    "component_stage": normalized_component_stage,
                    "directive_key": normalized_directive_key,
                    "directive_value": normalized_directive_value,
                    "source_guidance_override_event_id": guidance_payload[
                        "source_guidance_override_event_id"
                    ],
                    "conflicting_override_event_ids": [
                        conflict["override_event_id"] for conflict in conflicts
                    ],
                },
                lead_id=lead_id,
                job_posting_id=job_posting_id,
                contact_id=contact_id,
                created_at=current_timestamp,
            )
            if control_state.agent_enabled or control_state.agent_mode != AGENT_MODE_STOPPED:
                control_state = pause_agent(
                    connection,
                    reason=_guidance_pause_reason(normalized_directive_key),
                    manual_command=manual_command or "guidance",
                    timestamp=current_timestamp,
                )
            conflict_report = {
                "clarification_required": True,
                "incident_id": conflict_incident.agent_incident_id,
                "summary": conflict_summary,
                "conflicting_override_event_ids": [
                    conflict["override_event_id"] for conflict in conflicts
                ],
                "pause_reason": control_state.pause_reason,
            }
            status = "clarification_required"

    return {
        "contract_version": CONTRACT_VERSION,
        "produced_at": now_utc_iso(),
        "project_root": str(paths.project_root),
        "database": {
            "db_path": str(migration.db_path),
            "applied_migrations": migration.applied_migrations,
            "user_version": migration.user_version,
        },
        "command": "guidance",
        "status": status,
        "guidance": {
            "object_type": normalized_object_type,
            "object_id": normalized_object_id,
            "component_stage": normalized_component_stage,
            "directive_key": normalized_directive_key,
            "directive_value": normalized_directive_value,
            "guidance_scope": guidance_scope,
            "applies_to_similar_future_cases": (
                guidance_scope == GUIDANCE_SCOPE_CURRENT_AND_SIMILAR_FUTURE
            ),
            "source_guidance_override_event_id": guidance_payload[
                "source_guidance_override_event_id"
            ],
            "override_event_id": override_event.override_event_id,
            "override_timestamp": current_timestamp,
        },
        "conflict": conflict_report,
        "manual_command": manual_command,
        "control_state": dict(control_state.values),
    }


def request_guidance_clarification(
    object_type: str,
    object_id: str,
    *,
    component_stage: str,
    directive_key: str,
    directive_value: str,
    reason: str,
    request_kind: str = GUIDANCE_REQUEST_KIND_UNCERTAINTY,
    source_override_event_id: str | None = None,
    project_root: Path | str | None = None,
    manual_command: str | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    normalized_object_type = _normalize_guidance_object_type(object_type)
    normalized_object_id = object_id.strip()
    normalized_component_stage = component_stage.strip()
    normalized_directive_key = directive_key.strip()
    normalized_directive_value = directive_value.strip()
    normalized_reason = reason.strip()
    normalized_source_override_event_id = (
        source_override_event_id.strip() if source_override_event_id else None
    )

    if not normalized_object_id:
        raise ValueError("object_id is required for the clarify-guidance command.")
    if not normalized_component_stage:
        raise ValueError("component_stage is required for the clarify-guidance command.")
    if not normalized_directive_key:
        raise ValueError("directive_key is required for the clarify-guidance command.")
    if not normalized_directive_value:
        raise ValueError("directive_value is required for the clarify-guidance command.")
    if not normalized_reason:
        raise ValueError("reason is required for the clarify-guidance command.")
    if request_kind not in GUIDANCE_REQUEST_KINDS:
        supported_kinds = ", ".join(sorted(GUIDANCE_REQUEST_KINDS))
        raise ValueError(
            f"Unsupported request_kind={request_kind!r}. Supported values: {supported_kinds}."
        )

    paths = ProjectPaths.from_root(project_root)
    migration = initialize_database(paths.db_path)
    current_timestamp = timestamp or now_utc_iso()

    with connect_canonical_database(paths) as connection:
        lead_id, job_posting_id, contact_id = _resolve_guidance_linkage(
            connection,
            object_type=normalized_object_type,
            object_id=normalized_object_id,
        )
        if normalized_source_override_event_id is not None:
            source_row = connection.execute(
                """
                SELECT override_event_id
                FROM override_events
                WHERE override_event_id = ?
                """,
                (normalized_source_override_event_id,),
            ).fetchone()
            if source_row is None:
                raise ValueError(
                    "source_override_event_id "
                    f"{normalized_source_override_event_id!r} does not exist."
                )

        incident_type = (
            GUIDANCE_CONFLICT_INCIDENT_TYPE
            if request_kind == GUIDANCE_REQUEST_KIND_CONFLICT
            else GUIDANCE_CLARIFICATION_INCIDENT_TYPE
        )
        summary = (
            "Expert clarification is required before this standing guidance can be "
            "reused safely."
            if request_kind == GUIDANCE_REQUEST_KIND_UNCERTAINTY
            else (
                "A materially conflicting expert-guidance request requires "
                "clarification before autonomous progression resumes."
            )
        )
        incident = _ensure_guidance_incident(
            connection,
            incident_type=incident_type,
            severity="high",
            summary=summary,
            escalation_reason_payload={
                "kind": request_kind,
                "object_type": normalized_object_type,
                "object_id": normalized_object_id,
                "component_stage": normalized_component_stage,
                "directive_key": normalized_directive_key,
                "directive_value": normalized_directive_value,
                "source_guidance_override_event_id": normalized_source_override_event_id,
            },
            lead_id=lead_id,
            job_posting_id=job_posting_id,
            contact_id=contact_id,
            created_at=current_timestamp,
        )
        control_state = read_agent_control_state(connection, timestamp=current_timestamp)
        pause_reason = (
            _guidance_pause_reason(normalized_directive_key)
            if request_kind == GUIDANCE_REQUEST_KIND_CONFLICT
            else GUIDANCE_CLARIFICATION_PAUSE_REASON
        )
        if control_state.agent_enabled or control_state.agent_mode != AGENT_MODE_STOPPED:
            control_state = pause_agent(
                connection,
                reason=pause_reason,
                manual_command=manual_command or "clarify-guidance",
                timestamp=current_timestamp,
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
        "command": "clarify-guidance",
        "status": "clarification_required",
        "clarification_request": {
            "request_kind": request_kind,
            "object_type": normalized_object_type,
            "object_id": normalized_object_id,
            "component_stage": normalized_component_stage,
            "directive_key": normalized_directive_key,
            "directive_value": normalized_directive_value,
            "source_guidance_override_event_id": normalized_source_override_event_id,
            "incident_id": incident.agent_incident_id,
            "summary": incident.summary,
        },
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
        control_state_values, chat_idle_timeout_resume = maybe_resume_after_chat_idle_timeout(
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
        "chat_idle_timeout_resume": chat_idle_timeout_resume,
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
