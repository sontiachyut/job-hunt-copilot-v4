from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import MappingProxyType
from typing import Final

from .records import lifecycle_timestamps, new_canonical_id, now_utc_iso


RUN_STATUS_IN_PROGRESS: Final = "in_progress"
RUN_STATUS_PAUSED: Final = "paused"
RUN_STATUS_ESCALATED: Final = "escalated"
RUN_STATUS_FAILED: Final = "failed"
RUN_STATUS_COMPLETED: Final = "completed"

RUN_STATUSES = frozenset(
    {
        RUN_STATUS_IN_PROGRESS,
        RUN_STATUS_PAUSED,
        RUN_STATUS_ESCALATED,
        RUN_STATUS_FAILED,
        RUN_STATUS_COMPLETED,
    }
)
NON_TERMINAL_RUN_STATUSES = frozenset({RUN_STATUS_IN_PROGRESS, RUN_STATUS_PAUSED})
TERMINAL_RUN_STATUSES = frozenset(
    {
        RUN_STATUS_ESCALATED,
        RUN_STATUS_FAILED,
        RUN_STATUS_COMPLETED,
    }
)

REVIEW_PACKET_STATUS_NOT_READY: Final = "not_ready"
REVIEW_PACKET_STATUS_PENDING: Final = "pending_expert_review"
REVIEW_PACKET_STATUS_REVIEWED: Final = "reviewed"
REVIEW_PACKET_STATUS_SUPERSEDED: Final = "superseded"

REVIEW_PACKET_STATUSES = frozenset(
    {
        REVIEW_PACKET_STATUS_NOT_READY,
        REVIEW_PACKET_STATUS_PENDING,
        REVIEW_PACKET_STATUS_REVIEWED,
        REVIEW_PACKET_STATUS_SUPERSEDED,
    }
)

AGENT_MODE_RUNNING: Final = "running"
AGENT_MODE_PAUSED: Final = "paused"
AGENT_MODE_STOPPED: Final = "stopped"
AGENT_MODE_REPLANNING: Final = "replanning"

AGENT_MODES = frozenset(
    {
        AGENT_MODE_RUNNING,
        AGENT_MODE_PAUSED,
        AGENT_MODE_STOPPED,
        AGENT_MODE_REPLANNING,
    }
)

SUPERVISOR_CYCLE_RESULT_IN_PROGRESS: Final = "in_progress"
SUPERVISOR_CYCLE_RESULT_SUCCESS: Final = "success"
SUPERVISOR_CYCLE_RESULT_NO_WORK: Final = "no_work"
SUPERVISOR_CYCLE_RESULT_DEFERRED: Final = "deferred"
SUPERVISOR_CYCLE_RESULT_FAILED: Final = "failed"
SUPERVISOR_CYCLE_RESULT_AUTO_PAUSED: Final = "auto_paused"
SUPERVISOR_CYCLE_RESULT_REPLANNED: Final = "replanned"

SUPERVISOR_CYCLE_FINAL_RESULTS = frozenset(
    {
        SUPERVISOR_CYCLE_RESULT_SUCCESS,
        SUPERVISOR_CYCLE_RESULT_NO_WORK,
        SUPERVISOR_CYCLE_RESULT_DEFERRED,
        SUPERVISOR_CYCLE_RESULT_FAILED,
        SUPERVISOR_CYCLE_RESULT_AUTO_PAUSED,
        SUPERVISOR_CYCLE_RESULT_REPLANNED,
    }
)

SUPERVISOR_LEASE_NAME: Final = "supervisor_cycle"

CONTROL_DEFAULTS = MappingProxyType(
    {
        "agent_enabled": "false",
        "agent_mode": AGENT_MODE_STOPPED,
        "pause_reason": "",
        "paused_at": "",
        "last_manual_command": "",
        "last_replan_at": "",
        "last_replan_reason": "",
        "last_sleep_wake_check_at": "",
        "last_seen_sleep_event_at": "",
        "last_seen_wake_event_at": "",
        "last_sleep_wake_event_ref": "",
        "active_chat_session_id": "",
    }
)

REVIEW_PACKET_TRANSITIONS = MappingProxyType(
    {
        REVIEW_PACKET_STATUS_NOT_READY: frozenset(
            {
                REVIEW_PACKET_STATUS_NOT_READY,
                REVIEW_PACKET_STATUS_PENDING,
            }
        ),
        REVIEW_PACKET_STATUS_PENDING: frozenset(
            {
                REVIEW_PACKET_STATUS_PENDING,
                REVIEW_PACKET_STATUS_REVIEWED,
                REVIEW_PACKET_STATUS_SUPERSEDED,
            }
        ),
        REVIEW_PACKET_STATUS_REVIEWED: frozenset(
            {
                REVIEW_PACKET_STATUS_REVIEWED,
                REVIEW_PACKET_STATUS_SUPERSEDED,
            }
        ),
        REVIEW_PACKET_STATUS_SUPERSEDED: frozenset({REVIEW_PACKET_STATUS_SUPERSEDED}),
    }
)

_UNSET = object()


class SupervisorStateError(ValueError):
    """Raised when canonical supervisor state is invalid or contradictory."""


class InvalidLifecycleTransition(SupervisorStateError):
    """Raised when a caller attempts an unsupported state transition."""


class DuplicateActivePipelineRun(SupervisorStateError):
    """Raised when canonical state already contains multiple open runs for one posting."""


@dataclass(frozen=True)
class PipelineRunRecord:
    pipeline_run_id: str
    run_scope_type: str
    run_status: str
    current_stage: str
    lead_id: str | None
    job_posting_id: str | None
    completed_at: str | None
    last_error_summary: str | None
    review_packet_status: str | None
    run_summary: str | None
    started_at: str
    created_at: str
    updated_at: str

    @property
    def is_terminal(self) -> bool:
        return self.run_status in TERMINAL_RUN_STATUSES


@dataclass(frozen=True)
class SupervisorCycleRecord:
    supervisor_cycle_id: str
    trigger_type: str
    scheduler_name: str | None
    selected_work_type: str | None
    selected_work_id: str | None
    pipeline_run_id: str | None
    context_snapshot_path: str | None
    sleep_wake_detection_method: str | None
    sleep_wake_event_ref: str | None
    started_at: str
    completed_at: str | None
    result: str
    error_summary: str | None
    created_at: str


@dataclass(frozen=True)
class LeaseRecord:
    lease_name: str
    lease_owner_id: str
    acquired_at: str
    expires_at: str
    last_renewed_at: str | None
    lease_note: str | None


@dataclass(frozen=True)
class LeaseAcquireResult:
    status: str
    lease: LeaseRecord

    @property
    def acquired(self) -> bool:
        return self.status in {"acquired", "reclaimed"}

    @property
    def deferred(self) -> bool:
        return self.status == "deferred"


@dataclass(frozen=True)
class ControlStateSnapshot:
    values: dict[str, str]

    @property
    def agent_enabled(self) -> bool:
        return self.values["agent_enabled"] == "true"

    @property
    def agent_mode(self) -> str:
        return self.values["agent_mode"]

    @property
    def pause_reason(self) -> str | None:
        return _optional_text(self.values["pause_reason"])

    @property
    def paused_at(self) -> str | None:
        return _optional_text(self.values["paused_at"])

    @property
    def last_manual_command(self) -> str | None:
        return _optional_text(self.values["last_manual_command"])

    @property
    def last_replan_at(self) -> str | None:
        return _optional_text(self.values["last_replan_at"])

    @property
    def last_replan_reason(self) -> str | None:
        return _optional_text(self.values["last_replan_reason"])

    @property
    def last_sleep_wake_check_at(self) -> str | None:
        return _optional_text(self.values["last_sleep_wake_check_at"])

    @property
    def last_seen_sleep_event_at(self) -> str | None:
        return _optional_text(self.values["last_seen_sleep_event_at"])

    @property
    def last_seen_wake_event_at(self) -> str | None:
        return _optional_text(self.values["last_seen_wake_event_at"])

    @property
    def last_sleep_wake_event_ref(self) -> str | None:
        return _optional_text(self.values["last_sleep_wake_event_ref"])

    @property
    def active_chat_session_id(self) -> str | None:
        return _optional_text(self.values["active_chat_session_id"])

    @property
    def allows_new_pipeline_progression(self) -> bool:
        return self.agent_enabled and self.agent_mode == AGENT_MODE_RUNNING

    @property
    def allows_safe_observational_work(self) -> bool:
        return self.agent_enabled and self.agent_mode in {AGENT_MODE_RUNNING, AGENT_MODE_PAUSED, AGENT_MODE_REPLANNING}


def read_agent_control_state(
    connection: sqlite3.Connection,
    *,
    timestamp: str | None = None,
) -> ControlStateSnapshot:
    _ensure_control_defaults(connection, timestamp=timestamp)
    rows = connection.execute(
        """
        SELECT control_key, control_value
        FROM agent_control_state
        WHERE control_key IN ({})
        ORDER BY control_key
        """.format(",".join("?" for _ in CONTROL_DEFAULTS)),
        tuple(CONTROL_DEFAULTS.keys()),
    ).fetchall()
    values = dict(CONTROL_DEFAULTS)
    for control_key, control_value in rows:
        values[control_key] = control_value
    return ControlStateSnapshot(values=values)


def upsert_control_values(
    connection: sqlite3.Connection,
    updates: dict[str, str | bool | None],
    *,
    timestamp: str | None = None,
) -> ControlStateSnapshot:
    current_timestamp = timestamp or now_utc_iso()
    _ensure_control_defaults(connection, timestamp=current_timestamp)

    rows = [
        (control_key, _normalize_control_value(control_value), current_timestamp)
        for control_key, control_value in updates.items()
    ]
    with connection:
        connection.executemany(
            """
            INSERT INTO agent_control_state (control_key, control_value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(control_key) DO UPDATE SET
              control_value = excluded.control_value,
              updated_at = excluded.updated_at
            """,
            rows,
        )
    return read_agent_control_state(connection, timestamp=current_timestamp)


def resume_agent(
    connection: sqlite3.Connection,
    *,
    manual_command: str | None = None,
    timestamp: str | None = None,
) -> ControlStateSnapshot:
    updates = {
        "agent_enabled": True,
        "agent_mode": AGENT_MODE_RUNNING,
        "pause_reason": None,
        "paused_at": None,
    }
    if manual_command is not None:
        updates["last_manual_command"] = manual_command
    return upsert_control_values(connection, updates, timestamp=timestamp)


def pause_agent(
    connection: sqlite3.Connection,
    *,
    reason: str,
    manual_command: str | None = None,
    timestamp: str | None = None,
) -> ControlStateSnapshot:
    if not reason.strip():
        raise SupervisorStateError("Pause reason is required.")
    current_timestamp = timestamp or now_utc_iso()
    updates = {
        "agent_enabled": True,
        "agent_mode": AGENT_MODE_PAUSED,
        "pause_reason": reason,
        "paused_at": current_timestamp,
    }
    if manual_command is not None:
        updates["last_manual_command"] = manual_command
    return upsert_control_values(connection, updates, timestamp=current_timestamp)


def stop_agent(
    connection: sqlite3.Connection,
    *,
    manual_command: str | None = None,
    timestamp: str | None = None,
) -> ControlStateSnapshot:
    updates = {
        "agent_enabled": False,
        "agent_mode": AGENT_MODE_STOPPED,
        "pause_reason": None,
        "paused_at": None,
    }
    if manual_command is not None:
        updates["last_manual_command"] = manual_command
    return upsert_control_values(connection, updates, timestamp=timestamp)


def begin_replanning(
    connection: sqlite3.Connection,
    *,
    reason: str,
    manual_command: str | None = None,
    timestamp: str | None = None,
) -> ControlStateSnapshot:
    if not reason.strip():
        raise SupervisorStateError("Replanning reason is required.")
    current_timestamp = timestamp or now_utc_iso()
    updates = {
        "agent_enabled": True,
        "agent_mode": AGENT_MODE_REPLANNING,
        "pause_reason": None,
        "paused_at": None,
        "last_replan_at": current_timestamp,
        "last_replan_reason": reason,
    }
    if manual_command is not None:
        updates["last_manual_command"] = manual_command
    return upsert_control_values(connection, updates, timestamp=current_timestamp)


def get_pipeline_run(
    connection: sqlite3.Connection,
    pipeline_run_id: str,
) -> PipelineRunRecord | None:
    row = connection.execute(
        """
        SELECT pipeline_run_id, run_scope_type, run_status, current_stage, lead_id,
               job_posting_id, completed_at, last_error_summary, review_packet_status,
               run_summary, started_at, created_at, updated_at
        FROM pipeline_runs
        WHERE pipeline_run_id = ?
        """,
        (pipeline_run_id,),
    ).fetchone()
    return None if row is None else _pipeline_run_from_row(row)


def get_open_pipeline_run_for_posting(
    connection: sqlite3.Connection,
    job_posting_id: str,
) -> PipelineRunRecord | None:
    rows = connection.execute(
        """
        SELECT pipeline_run_id, run_scope_type, run_status, current_stage, lead_id,
               job_posting_id, completed_at, last_error_summary, review_packet_status,
               run_summary, started_at, created_at, updated_at
        FROM pipeline_runs
        WHERE job_posting_id = ?
          AND run_status IN (?, ?)
        ORDER BY started_at DESC, created_at DESC
        """,
        (
            job_posting_id,
            RUN_STATUS_IN_PROGRESS,
            RUN_STATUS_PAUSED,
        ),
    ).fetchall()
    if not rows:
        return None
    if len(rows) > 1:
        raise DuplicateActivePipelineRun(
            f"Found multiple non-terminal pipeline_runs for job_posting_id={job_posting_id}."
        )
    return _pipeline_run_from_row(rows[0])


def ensure_role_targeted_pipeline_run(
    connection: sqlite3.Connection,
    *,
    lead_id: str,
    job_posting_id: str,
    current_stage: str,
    started_at: str | None = None,
    pipeline_run_id: str | None = None,
    run_summary: str | None = None,
) -> tuple[PipelineRunRecord, bool]:
    existing = get_open_pipeline_run_for_posting(connection, job_posting_id)
    if existing is not None:
        return existing, False

    current_timestamp = started_at or now_utc_iso()
    timestamps = lifecycle_timestamps(current_timestamp)
    pipeline_run_id = pipeline_run_id or new_canonical_id("pipeline_runs")
    with connection:
        connection.execute(
            """
            INSERT INTO pipeline_runs (
              pipeline_run_id, run_scope_type, run_status, current_stage, lead_id,
              job_posting_id, completed_at, last_error_summary, review_packet_status,
              run_summary, started_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pipeline_run_id,
                "role_targeted_posting",
                RUN_STATUS_IN_PROGRESS,
                current_stage,
                lead_id,
                job_posting_id,
                None,
                None,
                REVIEW_PACKET_STATUS_NOT_READY,
                run_summary,
                current_timestamp,
                timestamps["created_at"],
                timestamps["updated_at"],
            ),
        )
    created = get_pipeline_run(connection, pipeline_run_id)
    if created is None:  # pragma: no cover - defensive invariant
        raise SupervisorStateError(f"Failed to load pipeline_run {pipeline_run_id} after creation.")
    return created, True


def advance_pipeline_run(
    connection: sqlite3.Connection,
    pipeline_run_id: str,
    *,
    current_stage: str,
    run_summary: str | None = _UNSET,
    timestamp: str | None = None,
) -> PipelineRunRecord:
    return _update_pipeline_run(
        connection,
        pipeline_run_id,
        new_status=RUN_STATUS_IN_PROGRESS,
        current_stage=current_stage,
        run_summary=run_summary,
        completed_at=None,
        last_error_summary=None,
        timestamp=timestamp,
    )


def pause_pipeline_run(
    connection: sqlite3.Connection,
    pipeline_run_id: str,
    *,
    current_stage: str | None = None,
    error_summary: str | None = _UNSET,
    run_summary: str | None = _UNSET,
    timestamp: str | None = None,
) -> PipelineRunRecord:
    return _update_pipeline_run(
        connection,
        pipeline_run_id,
        new_status=RUN_STATUS_PAUSED,
        current_stage=current_stage,
        last_error_summary=error_summary,
        run_summary=run_summary,
        completed_at=None,
        timestamp=timestamp,
    )


def escalate_pipeline_run(
    connection: sqlite3.Connection,
    pipeline_run_id: str,
    *,
    current_stage: str | None = None,
    error_summary: str | None = _UNSET,
    run_summary: str | None = _UNSET,
    timestamp: str | None = None,
) -> PipelineRunRecord:
    current_timestamp = timestamp or now_utc_iso()
    return _update_pipeline_run(
        connection,
        pipeline_run_id,
        new_status=RUN_STATUS_ESCALATED,
        current_stage=current_stage,
        last_error_summary=error_summary,
        run_summary=run_summary,
        completed_at=current_timestamp,
        timestamp=current_timestamp,
    )


def fail_pipeline_run(
    connection: sqlite3.Connection,
    pipeline_run_id: str,
    *,
    current_stage: str | None = None,
    error_summary: str,
    run_summary: str | None = _UNSET,
    timestamp: str | None = None,
) -> PipelineRunRecord:
    if not error_summary.strip():
        raise SupervisorStateError("Failure summary is required.")
    current_timestamp = timestamp or now_utc_iso()
    return _update_pipeline_run(
        connection,
        pipeline_run_id,
        new_status=RUN_STATUS_FAILED,
        current_stage=current_stage,
        last_error_summary=error_summary,
        run_summary=run_summary,
        completed_at=current_timestamp,
        timestamp=current_timestamp,
    )


def complete_pipeline_run(
    connection: sqlite3.Connection,
    pipeline_run_id: str,
    *,
    current_stage: str = "completed",
    run_summary: str | None = _UNSET,
    timestamp: str | None = None,
) -> PipelineRunRecord:
    current_timestamp = timestamp or now_utc_iso()
    return _update_pipeline_run(
        connection,
        pipeline_run_id,
        new_status=RUN_STATUS_COMPLETED,
        current_stage=current_stage,
        run_summary=run_summary,
        completed_at=current_timestamp,
        timestamp=current_timestamp,
    )


def set_pipeline_run_review_packet_status(
    connection: sqlite3.Connection,
    pipeline_run_id: str,
    review_packet_status: str,
    *,
    timestamp: str | None = None,
) -> PipelineRunRecord:
    if review_packet_status not in REVIEW_PACKET_STATUSES:
        raise SupervisorStateError(
            f"Unsupported review_packet_status={review_packet_status!r}."
        )
    current = _require_pipeline_run(connection, pipeline_run_id)
    current_review_status = current.review_packet_status or REVIEW_PACKET_STATUS_NOT_READY
    allowed = REVIEW_PACKET_TRANSITIONS[current_review_status]
    if review_packet_status not in allowed:
        raise InvalidLifecycleTransition(
            f"Cannot transition review_packet_status from {current_review_status!r} "
            f"to {review_packet_status!r}."
        )
    return _update_pipeline_run(
        connection,
        pipeline_run_id,
        review_packet_status=review_packet_status,
        timestamp=timestamp,
    )


def start_supervisor_cycle(
    connection: sqlite3.Connection,
    *,
    trigger_type: str,
    scheduler_name: str | None = None,
    sleep_wake_detection_method: str | None = None,
    sleep_wake_event_ref: str | None = None,
    started_at: str | None = None,
    supervisor_cycle_id: str | None = None,
) -> SupervisorCycleRecord:
    current_timestamp = started_at or now_utc_iso()
    supervisor_cycle_id = supervisor_cycle_id or new_canonical_id("supervisor_cycles")
    timestamps = lifecycle_timestamps(current_timestamp)
    with connection:
        connection.execute(
            """
            INSERT INTO supervisor_cycles (
              supervisor_cycle_id, trigger_type, scheduler_name, selected_work_type,
              selected_work_id, pipeline_run_id, context_snapshot_path,
              sleep_wake_detection_method, sleep_wake_event_ref, started_at,
              completed_at, result, error_summary, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                supervisor_cycle_id,
                trigger_type,
                scheduler_name,
                None,
                None,
                None,
                None,
                sleep_wake_detection_method,
                sleep_wake_event_ref,
                current_timestamp,
                None,
                SUPERVISOR_CYCLE_RESULT_IN_PROGRESS,
                None,
                timestamps["created_at"],
            ),
        )
    cycle = get_supervisor_cycle(connection, supervisor_cycle_id)
    if cycle is None:  # pragma: no cover - defensive invariant
        raise SupervisorStateError(
            f"Failed to load supervisor_cycle {supervisor_cycle_id} after creation."
        )
    return cycle


def assign_supervisor_cycle_work_unit(
    connection: sqlite3.Connection,
    supervisor_cycle_id: str,
    *,
    selected_work_type: str,
    selected_work_id: str,
    pipeline_run_id: str | None = None,
    context_snapshot_path: str | None = None,
) -> SupervisorCycleRecord:
    cycle = _require_supervisor_cycle(connection, supervisor_cycle_id)
    if cycle.result != SUPERVISOR_CYCLE_RESULT_IN_PROGRESS:
        raise InvalidLifecycleTransition(
            f"Cannot assign work to completed supervisor_cycle {supervisor_cycle_id}."
        )
    with connection:
        connection.execute(
            """
            UPDATE supervisor_cycles
            SET selected_work_type = ?,
                selected_work_id = ?,
                pipeline_run_id = ?,
                context_snapshot_path = ?
            WHERE supervisor_cycle_id = ?
            """,
            (
                selected_work_type,
                selected_work_id,
                pipeline_run_id,
                context_snapshot_path,
                supervisor_cycle_id,
            ),
        )
    return _require_supervisor_cycle(connection, supervisor_cycle_id)


def finish_supervisor_cycle(
    connection: sqlite3.Connection,
    supervisor_cycle_id: str,
    *,
    result: str,
    completed_at: str | None = None,
    error_summary: str | None = None,
) -> SupervisorCycleRecord:
    if result not in SUPERVISOR_CYCLE_FINAL_RESULTS:
        raise SupervisorStateError(f"Unsupported supervisor cycle result={result!r}.")
    cycle = _require_supervisor_cycle(connection, supervisor_cycle_id)
    if cycle.result != SUPERVISOR_CYCLE_RESULT_IN_PROGRESS:
        raise InvalidLifecycleTransition(
            f"Supervisor cycle {supervisor_cycle_id} is already finalized with {cycle.result!r}."
        )
    current_timestamp = completed_at or now_utc_iso()
    with connection:
        connection.execute(
            """
            UPDATE supervisor_cycles
            SET completed_at = ?,
                result = ?,
                error_summary = ?
            WHERE supervisor_cycle_id = ?
            """,
            (
                current_timestamp,
                result,
                error_summary,
                supervisor_cycle_id,
            ),
        )
    return _require_supervisor_cycle(connection, supervisor_cycle_id)


def get_supervisor_cycle(
    connection: sqlite3.Connection,
    supervisor_cycle_id: str,
) -> SupervisorCycleRecord | None:
    row = connection.execute(
        """
        SELECT supervisor_cycle_id, trigger_type, scheduler_name, selected_work_type,
               selected_work_id, pipeline_run_id, context_snapshot_path,
               sleep_wake_detection_method, sleep_wake_event_ref, started_at,
               completed_at, result, error_summary, created_at
        FROM supervisor_cycles
        WHERE supervisor_cycle_id = ?
        """,
        (supervisor_cycle_id,),
    ).fetchone()
    return None if row is None else _supervisor_cycle_from_row(row)


def acquire_runtime_lease(
    connection: sqlite3.Connection,
    *,
    lease_name: str,
    lease_owner_id: str,
    ttl_seconds: int,
    now: str | None = None,
    lease_note: str | None = None,
) -> LeaseAcquireResult:
    if ttl_seconds <= 0:
        raise SupervisorStateError("ttl_seconds must be positive.")

    current_timestamp = now or now_utc_iso()
    expires_at = _timestamp_plus_seconds(current_timestamp, ttl_seconds)

    connection.execute("BEGIN IMMEDIATE")
    try:
        row = connection.execute(
            """
            SELECT lease_name, lease_owner_id, acquired_at, expires_at, last_renewed_at, lease_note
            FROM agent_runtime_leases
            WHERE lease_name = ?
            """,
            (lease_name,),
        ).fetchone()
        if row is None:
            connection.execute(
                """
                INSERT INTO agent_runtime_leases (
                  lease_name, lease_owner_id, acquired_at, expires_at, last_renewed_at, lease_note
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    lease_name,
                    lease_owner_id,
                    current_timestamp,
                    expires_at,
                    current_timestamp,
                    lease_note,
                ),
            )
            connection.commit()
            return LeaseAcquireResult(
                status="acquired",
                lease=LeaseRecord(
                    lease_name=lease_name,
                    lease_owner_id=lease_owner_id,
                    acquired_at=current_timestamp,
                    expires_at=expires_at,
                    last_renewed_at=current_timestamp,
                    lease_note=lease_note,
                ),
            )

        current_lease = _lease_from_row(row)
        if _lease_is_expired(current_lease, current_timestamp):
            connection.execute(
                """
                UPDATE agent_runtime_leases
                SET lease_owner_id = ?,
                    acquired_at = ?,
                    expires_at = ?,
                    last_renewed_at = ?,
                    lease_note = ?
                WHERE lease_name = ?
                """,
                (
                    lease_owner_id,
                    current_timestamp,
                    expires_at,
                    current_timestamp,
                    lease_note,
                    lease_name,
                ),
            )
            connection.commit()
            return LeaseAcquireResult(
                status="reclaimed",
                lease=LeaseRecord(
                    lease_name=lease_name,
                    lease_owner_id=lease_owner_id,
                    acquired_at=current_timestamp,
                    expires_at=expires_at,
                    last_renewed_at=current_timestamp,
                    lease_note=lease_note,
                ),
            )

        connection.commit()
        return LeaseAcquireResult(status="deferred", lease=current_lease)
    except Exception:
        connection.rollback()
        raise


def renew_runtime_lease(
    connection: sqlite3.Connection,
    *,
    lease_name: str,
    lease_owner_id: str,
    ttl_seconds: int,
    now: str | None = None,
    lease_note: str | None = None,
) -> LeaseRecord:
    if ttl_seconds <= 0:
        raise SupervisorStateError("ttl_seconds must be positive.")

    current_timestamp = now or now_utc_iso()
    expires_at = _timestamp_plus_seconds(current_timestamp, ttl_seconds)
    lease = _require_runtime_lease(connection, lease_name)
    if lease.lease_owner_id != lease_owner_id:
        raise InvalidLifecycleTransition(
            f"Lease {lease_name} is owned by {lease.lease_owner_id!r}, not {lease_owner_id!r}."
        )
    if _lease_is_expired(lease, current_timestamp):
        raise InvalidLifecycleTransition(
            f"Lease {lease_name} expired at {lease.expires_at}; reacquire it instead of renewing."
        )

    with connection:
        connection.execute(
            """
            UPDATE agent_runtime_leases
            SET expires_at = ?,
                last_renewed_at = ?,
                lease_note = ?
            WHERE lease_name = ?
            """,
            (
                expires_at,
                current_timestamp,
                lease_note if lease_note is not None else lease.lease_note,
                lease_name,
            ),
        )
    return _require_runtime_lease(connection, lease_name)


def release_runtime_lease(
    connection: sqlite3.Connection,
    *,
    lease_name: str,
    lease_owner_id: str,
) -> bool:
    with connection:
        result = connection.execute(
            """
            DELETE FROM agent_runtime_leases
            WHERE lease_name = ?
              AND lease_owner_id = ?
            """,
            (
                lease_name,
                lease_owner_id,
            ),
        )
    return result.rowcount > 0


def get_runtime_lease(
    connection: sqlite3.Connection,
    lease_name: str,
) -> LeaseRecord | None:
    row = connection.execute(
        """
        SELECT lease_name, lease_owner_id, acquired_at, expires_at, last_renewed_at, lease_note
        FROM agent_runtime_leases
        WHERE lease_name = ?
        """,
        (lease_name,),
    ).fetchone()
    return None if row is None else _lease_from_row(row)


def _ensure_control_defaults(
    connection: sqlite3.Connection,
    *,
    timestamp: str | None = None,
) -> None:
    current_timestamp = timestamp or now_utc_iso()
    existing_keys = {
        row[0]
        for row in connection.execute(
            "SELECT control_key FROM agent_control_state WHERE control_key IN ({})".format(
                ",".join("?" for _ in CONTROL_DEFAULTS)
            ),
            tuple(CONTROL_DEFAULTS.keys()),
        ).fetchall()
    }
    missing_rows = [
        (control_key, control_value, current_timestamp)
        for control_key, control_value in CONTROL_DEFAULTS.items()
        if control_key not in existing_keys
    ]
    if not missing_rows:
        return
    with connection:
        connection.executemany(
            """
            INSERT INTO agent_control_state (control_key, control_value, updated_at)
            VALUES (?, ?, ?)
            """,
            missing_rows,
        )


def _update_pipeline_run(
    connection: sqlite3.Connection,
    pipeline_run_id: str,
    *,
    new_status: str | None = None,
    current_stage: str | None = None,
    review_packet_status: str | None = None,
    completed_at: str | None | object = _UNSET,
    last_error_summary: str | None | object = _UNSET,
    run_summary: str | None | object = _UNSET,
    timestamp: str | None = None,
) -> PipelineRunRecord:
    current = _require_pipeline_run(connection, pipeline_run_id)
    current_timestamp = timestamp or now_utc_iso()
    fields: dict[str, str | None] = {"updated_at": current_timestamp}

    if new_status is not None:
        if new_status not in RUN_STATUSES:
            raise SupervisorStateError(f"Unsupported run_status={new_status!r}.")
        _validate_run_status_transition(current.run_status, new_status)
        fields["run_status"] = new_status

    if current_stage is not None:
        if not current_stage.strip():
            raise SupervisorStateError("current_stage must not be blank.")
        fields["current_stage"] = current_stage

    if review_packet_status is not None:
        if review_packet_status not in REVIEW_PACKET_STATUSES:
            raise SupervisorStateError(
                f"Unsupported review_packet_status={review_packet_status!r}."
            )
        current_review_status = current.review_packet_status or REVIEW_PACKET_STATUS_NOT_READY
        allowed_review_states = REVIEW_PACKET_TRANSITIONS[current_review_status]
        if review_packet_status not in allowed_review_states:
            raise InvalidLifecycleTransition(
                f"Cannot transition review_packet_status from {current_review_status!r} "
                f"to {review_packet_status!r}."
            )
        fields["review_packet_status"] = review_packet_status

    if completed_at is not _UNSET:
        fields["completed_at"] = completed_at
    if last_error_summary is not _UNSET:
        fields["last_error_summary"] = last_error_summary
    if run_summary is not _UNSET:
        fields["run_summary"] = run_summary

    assignments = ", ".join(f"{field_name} = ?" for field_name in fields)
    values = [fields[field_name] for field_name in fields]
    values.append(pipeline_run_id)
    with connection:
        connection.execute(
            f"UPDATE pipeline_runs SET {assignments} WHERE pipeline_run_id = ?",
            values,
        )
    return _require_pipeline_run(connection, pipeline_run_id)


def _validate_run_status_transition(current_status: str, new_status: str) -> None:
    if current_status == new_status:
        return
    if current_status == RUN_STATUS_IN_PROGRESS:
        if new_status in {RUN_STATUS_PAUSED, RUN_STATUS_ESCALATED, RUN_STATUS_FAILED, RUN_STATUS_COMPLETED}:
            return
    if current_status == RUN_STATUS_PAUSED:
        if new_status in {RUN_STATUS_IN_PROGRESS, RUN_STATUS_ESCALATED, RUN_STATUS_FAILED, RUN_STATUS_COMPLETED}:
            return
    if current_status == RUN_STATUS_ESCALATED:
        if new_status == RUN_STATUS_IN_PROGRESS:
            return
    raise InvalidLifecycleTransition(
        f"Cannot transition pipeline_run from {current_status!r} to {new_status!r}."
    )


def _require_pipeline_run(
    connection: sqlite3.Connection,
    pipeline_run_id: str,
) -> PipelineRunRecord:
    run = get_pipeline_run(connection, pipeline_run_id)
    if run is None:
        raise SupervisorStateError(f"pipeline_run {pipeline_run_id!r} does not exist.")
    return run


def _require_supervisor_cycle(
    connection: sqlite3.Connection,
    supervisor_cycle_id: str,
) -> SupervisorCycleRecord:
    cycle = get_supervisor_cycle(connection, supervisor_cycle_id)
    if cycle is None:
        raise SupervisorStateError(
            f"supervisor_cycle {supervisor_cycle_id!r} does not exist."
        )
    return cycle


def _require_runtime_lease(
    connection: sqlite3.Connection,
    lease_name: str,
) -> LeaseRecord:
    lease = get_runtime_lease(connection, lease_name)
    if lease is None:
        raise SupervisorStateError(f"Lease {lease_name!r} does not exist.")
    return lease


def _pipeline_run_from_row(row: sqlite3.Row | tuple[object, ...]) -> PipelineRunRecord:
    return PipelineRunRecord(
        pipeline_run_id=row[0],
        run_scope_type=row[1],
        run_status=row[2],
        current_stage=row[3],
        lead_id=_optional_text(row[4]),
        job_posting_id=_optional_text(row[5]),
        completed_at=_optional_text(row[6]),
        last_error_summary=_optional_text(row[7]),
        review_packet_status=_optional_text(row[8]),
        run_summary=_optional_text(row[9]),
        started_at=row[10],
        created_at=row[11],
        updated_at=row[12],
    )


def _supervisor_cycle_from_row(row: sqlite3.Row | tuple[object, ...]) -> SupervisorCycleRecord:
    return SupervisorCycleRecord(
        supervisor_cycle_id=row[0],
        trigger_type=row[1],
        scheduler_name=_optional_text(row[2]),
        selected_work_type=_optional_text(row[3]),
        selected_work_id=_optional_text(row[4]),
        pipeline_run_id=_optional_text(row[5]),
        context_snapshot_path=_optional_text(row[6]),
        sleep_wake_detection_method=_optional_text(row[7]),
        sleep_wake_event_ref=_optional_text(row[8]),
        started_at=row[9],
        completed_at=_optional_text(row[10]),
        result=row[11],
        error_summary=_optional_text(row[12]),
        created_at=row[13],
    )


def _lease_from_row(row: sqlite3.Row | tuple[object, ...]) -> LeaseRecord:
    return LeaseRecord(
        lease_name=row[0],
        lease_owner_id=row[1],
        acquired_at=row[2],
        expires_at=row[3],
        last_renewed_at=_optional_text(row[4]),
        lease_note=_optional_text(row[5]),
    )


def _normalize_control_value(value: str | bool | None) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    return str(value)


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _timestamp_plus_seconds(timestamp: str, ttl_seconds: int) -> str:
    return _to_utc_iso(_parse_utc_iso(timestamp) + timedelta(seconds=ttl_seconds))


def _lease_is_expired(lease: LeaseRecord, now: str) -> bool:
    return _parse_utc_iso(lease.expires_at) <= _parse_utc_iso(now)


def _parse_utc_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _to_utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
