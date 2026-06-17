from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo


SEND_LANE_QUEUE_FOLLOWUP = "followup"
SEND_LANE_QUEUE_ORIGINAL = "original"
SEND_LANE_WAIT_REASON_WINDOW = "waiting_for_window"
SEND_LANE_WAIT_REASON_PACING_GAP = "waiting_for_pacing_gap"
SEND_LANE_TIMEZONE = ZoneInfo("America/Phoenix")
PREPARED_FRONTIER_CAP = 10
DRAFT_FRESHNESS_WINDOW = timedelta(hours=24)

FOLLOWUP_AUTO_SEND_ENABLED_KEY = "followup_auto_send_enabled"
FOLLOWUP_AUTO_SEND_PAUSED_KEY = "followup_auto_send_paused"
FOLLOWUP_INITIAL_ROLLOUT_SENT_COUNT_KEY = "followup_initial_rollout_sent_count"
FOLLOWUP_INITIAL_ROLLOUT_APPROVED_KEY = "followup_initial_rollout_approved"
FOLLOWUP_INITIAL_AUTO_SEND_CAP = 10

FOLLOWUP_SENDABLE_PLAN_STATUSES = (
    "agent_reviewed",
    "waiting_for_pacing",
    "retryable",
)

LEGACY_FOLLOWUP_WAIT_REASONS = (
    "waiting_for_pacing",
    "waiting_for_pacing_gap",
    "waiting_for_window",
    "role_targeted_priority_wait",
)


@dataclass(frozen=True)
class SharedSendWindow:
    preferred_queue_kind: str
    other_queue_kind: str
    local_window_start: str
    local_window_end: str
    utc_window_start: str
    utc_window_end: str


@dataclass(frozen=True)
class SharedSendTurnDecision:
    active_window_preference: str
    selected_queue_kind: str | None
    fallback_used: bool
    original_sendable_now: bool
    followup_sendable_now: bool
    local_window_start: str
    local_window_end: str
    utc_window_start: str
    utc_window_end: str

    def queue_wait_reason(self, queue_kind: str) -> str | None:
        if self.selected_queue_kind is None:
            return None
        if queue_kind == self.selected_queue_kind:
            return None
        return SEND_LANE_WAIT_REASON_WINDOW


@dataclass(frozen=True)
class SendLaneWindowSummary:
    active_window_preference: str
    active_window_local_start: str
    active_window_local_end: str
    active_window_utc_start: str
    active_window_utc_end: str
    next_window_preference: str
    next_window_local_start: str
    next_window_local_end: str
    next_window_utc_start: str
    next_window_utc_end: str


def decide_shared_send_turn(
    *,
    current_time: str,
    original_sendable_now: bool,
    followup_sendable_now: bool,
    original_queue_enabled: bool = True,
    followup_queue_enabled: bool = True,
    timezone: ZoneInfo = SEND_LANE_TIMEZONE,
) -> SharedSendTurnDecision:
    window = shared_send_window(current_time, timezone=timezone)
    original_available = bool(original_sendable_now and original_queue_enabled)
    followup_available = bool(followup_sendable_now and followup_queue_enabled)
    availability = {
        SEND_LANE_QUEUE_ORIGINAL: original_available,
        SEND_LANE_QUEUE_FOLLOWUP: followup_available,
    }
    preferred_available = availability[window.preferred_queue_kind]
    other_available = availability[window.other_queue_kind]
    if preferred_available:
        selected_queue_kind: str | None = window.preferred_queue_kind
        fallback_used = False
    elif other_available:
        selected_queue_kind = window.other_queue_kind
        fallback_used = True
    else:
        selected_queue_kind = None
        fallback_used = False
    return SharedSendTurnDecision(
        active_window_preference=window.preferred_queue_kind,
        selected_queue_kind=selected_queue_kind,
        fallback_used=fallback_used,
        original_sendable_now=original_available,
        followup_sendable_now=followup_available,
        local_window_start=window.local_window_start,
        local_window_end=window.local_window_end,
        utc_window_start=window.utc_window_start,
        utc_window_end=window.utc_window_end,
    )


def shared_send_window(
    current_time: str | datetime,
    *,
    timezone: ZoneInfo = SEND_LANE_TIMEZONE,
) -> SharedSendWindow:
    current_dt = _coerce_datetime(current_time)
    local_dt = current_dt.astimezone(timezone)
    block_start_hour = (local_dt.hour // 2) * 2
    start_local = local_dt.replace(
        hour=block_start_hour,
        minute=0,
        second=0,
        microsecond=0,
    )
    end_local = start_local + timedelta(hours=2)
    block_index = block_start_hour // 2
    preferred_queue_kind = (
        SEND_LANE_QUEUE_FOLLOWUP
        if block_index % 2 == 0
        else SEND_LANE_QUEUE_ORIGINAL
    )
    other_queue_kind = (
        SEND_LANE_QUEUE_ORIGINAL
        if preferred_queue_kind == SEND_LANE_QUEUE_FOLLOWUP
        else SEND_LANE_QUEUE_FOLLOWUP
    )
    return SharedSendWindow(
        preferred_queue_kind=preferred_queue_kind,
        other_queue_kind=other_queue_kind,
        local_window_start=_format_local_window_boundary(start_local),
        local_window_end=_format_local_window_boundary(end_local),
        utc_window_start=_isoformat_utc(start_local.astimezone(UTC)),
        utc_window_end=_isoformat_utc(end_local.astimezone(UTC)),
    )


def next_preferred_window_start(
    current_time: str,
    *,
    queue_kind: str,
    timezone: ZoneInfo = SEND_LANE_TIMEZONE,
) -> str:
    current_dt = _coerce_datetime(current_time).astimezone(timezone)
    candidate_start = current_dt.replace(
        hour=(current_dt.hour // 2) * 2,
        minute=0,
        second=0,
        microsecond=0,
    )
    for _ in range(13):
        candidate_window = shared_send_window(candidate_start, timezone=timezone)
        if candidate_window.preferred_queue_kind == queue_kind and candidate_start > current_dt:
            return candidate_window.utc_window_start
        candidate_start += timedelta(hours=2)
    return _isoformat_utc(current_dt.astimezone(UTC))


def build_send_lane_window_summary(
    current_time: str | datetime,
    *,
    timezone: ZoneInfo = SEND_LANE_TIMEZONE,
) -> SendLaneWindowSummary:
    active_window = shared_send_window(current_time, timezone=timezone)
    next_window = shared_send_window(
        _coerce_datetime(current_time) + timedelta(hours=2),
        timezone=timezone,
    )
    return SendLaneWindowSummary(
        active_window_preference=active_window.preferred_queue_kind,
        active_window_local_start=active_window.local_window_start,
        active_window_local_end=active_window.local_window_end,
        active_window_utc_start=active_window.utc_window_start,
        active_window_utc_end=active_window.utc_window_end,
        next_window_preference=next_window.preferred_queue_kind,
        next_window_local_start=next_window.local_window_start,
        next_window_local_end=next_window.local_window_end,
        next_window_utc_start=next_window.utc_window_start,
        next_window_utc_end=next_window.utc_window_end,
    )


def followup_auto_send_available(connection: sqlite3.Connection) -> bool:
    values = {
        row["control_key"]: row["control_value"]
        for row in connection.execute(
            """
            SELECT control_key, control_value
            FROM agent_control_state
            WHERE control_key IN (?, ?, ?, ?)
            """,
            (
                FOLLOWUP_AUTO_SEND_ENABLED_KEY,
                FOLLOWUP_AUTO_SEND_PAUSED_KEY,
                FOLLOWUP_INITIAL_ROLLOUT_SENT_COUNT_KEY,
                FOLLOWUP_INITIAL_ROLLOUT_APPROVED_KEY,
            ),
        )
    }
    if values.get(FOLLOWUP_AUTO_SEND_ENABLED_KEY) != "true":
        return False
    if values.get(FOLLOWUP_AUTO_SEND_PAUSED_KEY) == "true":
        return False
    rollout_approved = values.get(FOLLOWUP_INITIAL_ROLLOUT_APPROVED_KEY) == "true"
    if rollout_approved:
        return True
    try:
        sent_count = int(values.get(FOLLOWUP_INITIAL_ROLLOUT_SENT_COUNT_KEY, "0"))
    except ValueError:
        sent_count = 0
    return sent_count < FOLLOWUP_INITIAL_AUTO_SEND_CAP


def followup_queue_has_sendable_now(
    connection: sqlite3.Connection,
    *,
    current_time: str,
) -> bool:
    if not followup_auto_send_available(connection):
        return False
    freshness_cutoff = _isoformat_utc(_coerce_datetime(current_time) - DRAFT_FRESHNESS_WINDOW)
    row = connection.execute(
        """
        WITH prepared_frontier AS (
          SELECT fp.outreach_followup_plan_id
          FROM outreach_followup_plans fp
          JOIN outreach_messages om
            ON om.outreach_message_id = fp.original_outreach_message_id
          WHERE fp.plan_status IN (?, ?, ?, ?)
            AND fp.draft_artifact_path IS NOT NULL
            AND TRIM(fp.draft_artifact_path) <> ''
            AND fp.review_evidence_artifact_path IS NOT NULL
            AND TRIM(fp.review_evidence_artifact_path) <> ''
          ORDER BY fp.eligible_after ASC,
                   fp.followup_sequence DESC,
                   om.sent_at ASC,
                   fp.outreach_followup_plan_id ASC
          LIMIT ?
        )
        SELECT 1
        FROM outreach_followup_plans fp
        JOIN prepared_frontier pf
          ON pf.outreach_followup_plan_id = fp.outreach_followup_plan_id
        WHERE fp.plan_status IN (?, ?, ?)
          AND fp.eligible_after <= ?
          AND (fp.next_retry_at IS NULL OR fp.next_retry_at <= ?)
          AND COALESCE(fp.agent_reviewed_at, fp.last_evaluated_at, fp.updated_at) >= ?
          AND (
            fp.plan_status <> 'waiting_for_pacing'
            OR fp.last_skip_reason IS NULL
            OR fp.last_skip_reason IN (?, ?, ?, ?)
          )
        LIMIT 1
        """,
        (
            FOLLOWUP_SENDABLE_PLAN_STATUSES[0],
            FOLLOWUP_SENDABLE_PLAN_STATUSES[1],
            FOLLOWUP_SENDABLE_PLAN_STATUSES[2],
            "dry_run_ready",
            PREPARED_FRONTIER_CAP,
            FOLLOWUP_SENDABLE_PLAN_STATUSES[0],
            FOLLOWUP_SENDABLE_PLAN_STATUSES[1],
            FOLLOWUP_SENDABLE_PLAN_STATUSES[2],
            current_time,
            current_time,
            freshness_cutoff,
            LEGACY_FOLLOWUP_WAIT_REASONS[0],
            LEGACY_FOLLOWUP_WAIT_REASONS[1],
            LEGACY_FOLLOWUP_WAIT_REASONS[2],
            LEGACY_FOLLOWUP_WAIT_REASONS[3],
        ),
    ).fetchone()
    return row is not None


def _coerce_datetime(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def is_within_draft_freshness_window(
    *,
    reference_time: str | datetime | None,
    current_time: str | datetime,
) -> bool:
    if reference_time is None:
        return False
    reference_dt = _coerce_datetime(reference_time)
    current_dt = _coerce_datetime(current_time)
    return current_dt - reference_dt < DRAFT_FRESHNESS_WINDOW


def _isoformat_utc(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _format_local_window_boundary(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %I:%M %p %Z")
