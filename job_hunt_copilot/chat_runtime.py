from __future__ import annotations

import sqlite3
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from typing import Any

from .paths import ProjectPaths
from .review_queries import query_review_surfaces


ROLLING_RUNTIME_WINDOW_DAYS = 7
CHAT_REVIEW_GROUP_ORDER = (
    "pending_expert_review_packets",
    "failed_expert_requested_background_tasks",
    "maintenance_change_batches",
    "open_incidents",
)


def _parse_timestamp(timestamp: str) -> datetime:
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(timezone.utc)


def _resolve_local_timezone(
    *,
    current_time: datetime,
    local_timezone: tzinfo | None,
) -> tzinfo:
    if local_timezone is not None:
        return local_timezone
    return datetime.now().astimezone().tzinfo or current_time.tzinfo or timezone.utc


def _format_duration(seconds: float) -> str:
    rounded_seconds = max(int(round(seconds)), 0)
    hours, remainder = divmod(rounded_seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    return f"{minutes}m"


def _format_timestamp_for_display(timestamp: str | None, local_timezone: tzinfo) -> str | None:
    if not timestamp:
        return None
    localized = _parse_timestamp(timestamp).astimezone(local_timezone)
    zone_name = localized.tzname() or localized.strftime("%z")
    return f"{localized:%Y-%m-%d %H:%M} {zone_name}"


def _record_runtime_by_local_day(
    seconds_by_day: dict[date, float],
    *,
    started_at: datetime,
    completed_at: datetime,
    local_timezone: tzinfo,
) -> None:
    if completed_at <= started_at:
        return

    local_start = started_at.astimezone(local_timezone)
    local_end = completed_at.astimezone(local_timezone)
    cursor = local_start
    while cursor.date() < local_end.date():
        next_day = datetime.combine(
            cursor.date() + timedelta(days=1),
            time.min,
            tzinfo=local_timezone,
        )
        seconds_by_day[cursor.date()] = seconds_by_day.get(cursor.date(), 0.0) + (
            next_day - cursor
        ).total_seconds()
        cursor = next_day

    seconds_by_day[cursor.date()] = seconds_by_day.get(cursor.date(), 0.0) + (
        local_end - cursor
    ).total_seconds()


def _bucket_timestamps_by_local_day(
    timestamps: list[str],
    *,
    local_timezone: tzinfo,
) -> dict[date, int]:
    counts: dict[date, int] = {}
    for timestamp in timestamps:
        local_day = _parse_timestamp(timestamp).astimezone(local_timezone).date()
        counts[local_day] = counts.get(local_day, 0) + 1
    return counts


def _query_single_timestamp_column(
    connection: sqlite3.Connection,
    sql: str,
    params: tuple[Any, ...] = (),
) -> list[str]:
    return [
        str(row[0])
        for row in connection.execute(sql, params).fetchall()
        if row[0]
    ]


def build_chat_runtime_metrics(
    connection: sqlite3.Connection,
    *,
    current_time: str,
    local_timezone: tzinfo | None = None,
) -> dict[str, Any]:
    current_dt = _parse_timestamp(current_time)
    resolved_timezone = _resolve_local_timezone(
        current_time=current_dt,
        local_timezone=local_timezone,
    )
    today = current_dt.astimezone(resolved_timezone).date()
    yesterday = today - timedelta(days=1)

    runtime_seconds_by_day: dict[date, float] = {}
    for row in connection.execute(
        """
        SELECT started_at, completed_at
        FROM supervisor_cycles
        WHERE started_at IS NOT NULL
        """
    ).fetchall():
        started_at = _parse_timestamp(str(row["started_at"]))
        completed_at = (
            _parse_timestamp(str(row["completed_at"]))
            if row["completed_at"]
            else current_dt
        )
        _record_runtime_by_local_day(
            runtime_seconds_by_day,
            started_at=started_at,
            completed_at=completed_at,
            local_timezone=resolved_timezone,
        )

    successful_run_counts = _bucket_timestamps_by_local_day(
        _query_single_timestamp_column(
            connection,
            """
            SELECT completed_at
            FROM pipeline_runs
            WHERE run_status = 'completed'
              AND completed_at IS NOT NULL
            """,
        ),
        local_timezone=resolved_timezone,
    )
    successful_send_counts = _bucket_timestamps_by_local_day(
        _query_single_timestamp_column(
            connection,
            """
            SELECT sent_at
            FROM outreach_messages
            WHERE sent_at IS NOT NULL
            """,
        ),
        local_timezone=resolved_timezone,
    )
    bounce_counts = _bucket_timestamps_by_local_day(
        _query_single_timestamp_column(
            connection,
            """
            SELECT event_timestamp
            FROM delivery_feedback_events
            WHERE event_state = 'bounced'
            """,
        ),
        local_timezone=resolved_timezone,
    )
    reply_counts = _bucket_timestamps_by_local_day(
        _query_single_timestamp_column(
            connection,
            """
            SELECT event_timestamp
            FROM delivery_feedback_events
            WHERE event_state = 'replied'
            """,
        ),
        local_timezone=resolved_timezone,
    )

    rolling_days = [today - timedelta(days=offset) for offset in range(ROLLING_RUNTIME_WINDOW_DAYS)]
    rolling_average_runtime_seconds = sum(
        runtime_seconds_by_day.get(day, 0.0) for day in rolling_days
    ) / ROLLING_RUNTIME_WINDOW_DAYS

    def metrics_for_day(day: date) -> dict[str, Any]:
        runtime_seconds = runtime_seconds_by_day.get(day, 0.0)
        return {
            "date": day.isoformat(),
            "runtime_seconds": round(runtime_seconds, 3),
            "runtime_display": _format_duration(runtime_seconds),
            "successful_run_count": successful_run_counts.get(day, 0),
            "successful_send_count": successful_send_counts.get(day, 0),
            "bounce_count": bounce_counts.get(day, 0),
            "reply_count": reply_counts.get(day, 0),
        }

    return {
        "today": metrics_for_day(today),
        "yesterday": metrics_for_day(yesterday),
        "rolling_average_daily_runtime_seconds": round(rolling_average_runtime_seconds, 3),
        "rolling_average_daily_runtime_display": _format_duration(
            rolling_average_runtime_seconds
        ),
        "rolling_window_days": ROLLING_RUNTIME_WINDOW_DAYS,
        "local_timezone": str(resolved_timezone),
    }


def _build_pending_review_packet_items(
    review_surfaces: dict[str, tuple[dict[str, Any], ...]],
    *,
    local_timezone: tzinfo,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for packet in review_surfaces["pending_expert_review_packets"]:
        title_parts = [packet.get("company_name"), packet.get("role_title")]
        title = " / ".join(part for part in title_parts if part) or "Pending expert review packet"
        summary = packet.get("run_summary") or packet.get("packet_status") or "pending expert review"
        created_at = str(packet.get("created_at") or "")
        items.append(
            {
                "headline": title,
                "summary": str(summary),
                "timestamp": created_at,
                "timestamp_display": _format_timestamp_for_display(created_at, local_timezone),
                "artifact_refs": [packet.get("packet_path")] if packet.get("packet_path") else [],
            }
        )
    return items


def _build_failed_background_task_items(
    connection: sqlite3.Connection,
    *,
    local_timezone: tzinfo,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT run_status, current_stage, run_summary, started_at, completed_at, updated_at
        FROM pipeline_runs
        WHERE run_scope_type = 'expert_requested_background_task'
          AND run_status IN ('failed', 'escalated', 'paused')
        ORDER BY COALESCE(updated_at, completed_at, started_at) DESC
        """
    ).fetchall()
    items: list[dict[str, Any]] = []
    for row in rows:
        timestamp = str(
            row["updated_at"] or row["completed_at"] or row["started_at"] or ""
        )
        summary = row["run_summary"] or f"{row['run_status']} during {row['current_stage']}"
        items.append(
            {
                "headline": str(summary),
                "summary": f"status={row['run_status']} stage={row['current_stage']}",
                "timestamp": timestamp,
                "timestamp_display": _format_timestamp_for_display(timestamp, local_timezone),
                "artifact_refs": [],
            }
        )
    return items


def _build_maintenance_batch_items(
    connection: sqlite3.Connection,
    *,
    local_timezone: tzinfo,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT scope_slug, status, approval_outcome, validation_summary, summary_path, json_path,
               COALESCE(failed_at, merged_at, approved_at, validated_at, created_at) AS sort_at
        FROM maintenance_change_batches
        ORDER BY sort_at DESC, maintenance_change_batch_id DESC
        """
    ).fetchall()
    items: list[dict[str, Any]] = []
    for row in rows:
        timestamp = str(row["sort_at"] or "")
        summary = row["validation_summary"] or f"{row['status']} / {row['approval_outcome']}"
        artifact_refs = [path for path in (row["summary_path"], row["json_path"]) if path]
        items.append(
            {
                "headline": str(row["scope_slug"]),
                "summary": str(summary),
                "timestamp": timestamp,
                "timestamp_display": _format_timestamp_for_display(timestamp, local_timezone),
                "artifact_refs": artifact_refs,
            }
        )
    return items


def _build_open_incident_items(
    review_surfaces: dict[str, tuple[dict[str, Any], ...]],
    *,
    local_timezone: tzinfo,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for incident in review_surfaces["open_agent_incidents"]:
        title_parts = [incident.get("company_name"), incident.get("role_title")]
        title = " / ".join(part for part in title_parts if part) or "Open incident"
        if incident.get("full_name"):
            title = f"{title} | {incident['full_name']}"
        timestamp = str(incident.get("updated_at") or incident.get("created_at") or "")
        items.append(
            {
                "headline": title,
                "summary": f"{incident['severity']}: {incident['summary']}",
                "timestamp": timestamp,
                "timestamp_display": _format_timestamp_for_display(timestamp, local_timezone),
                "artifact_refs": [],
            }
        )
    return items


def build_chat_review_queue(
    connection: sqlite3.Connection,
    *,
    project_root: str | Any,
    local_timezone: tzinfo | None = None,
    max_items_per_group: int = 3,
) -> dict[str, Any]:
    current_dt = datetime.now(timezone.utc)
    resolved_timezone = _resolve_local_timezone(
        current_time=current_dt,
        local_timezone=local_timezone,
    )
    review_surfaces = query_review_surfaces(connection, project_root=project_root)
    all_groups = {
        "pending_expert_review_packets": {
            "title": "Pending expert review packets",
            "items": _build_pending_review_packet_items(
                review_surfaces,
                local_timezone=resolved_timezone,
            ),
        },
        "failed_expert_requested_background_tasks": {
            "title": "Failed or unresolved expert-requested background tasks",
            "items": _build_failed_background_task_items(
                connection,
                local_timezone=resolved_timezone,
            ),
        },
        "maintenance_change_batches": {
            "title": "Autonomous maintenance change batches",
            "items": _build_maintenance_batch_items(
                connection,
                local_timezone=resolved_timezone,
            ),
        },
        "open_incidents": {
            "title": "Open incidents",
            "items": _build_open_incident_items(
                review_surfaces,
                local_timezone=resolved_timezone,
            ),
        },
    }

    ordered_groups: list[dict[str, Any]] = []
    for group_id in CHAT_REVIEW_GROUP_ORDER:
        group = all_groups[group_id]
        ordered_groups.append(
            {
                "group_id": group_id,
                "title": group["title"],
                "total_count": len(group["items"]),
                "items": group["items"][:max_items_per_group],
            }
        )

    return {
        "group_order": list(CHAT_REVIEW_GROUP_ORDER),
        "groups": ordered_groups,
    }


def build_chat_startup_dashboard(
    connection: sqlite3.Connection,
    *,
    project_root: str | Any,
    current_time: str,
    agent_mode: str,
    pause_reason: str | None,
    local_timezone: tzinfo | None = None,
) -> dict[str, Any]:
    paths = ProjectPaths.from_root(project_root)
    current_dt = _parse_timestamp(current_time)
    resolved_timezone = _resolve_local_timezone(
        current_time=current_dt,
        local_timezone=local_timezone,
    )
    runtime_metrics = build_chat_runtime_metrics(
        connection,
        current_time=current_time,
        local_timezone=resolved_timezone,
    )
    review_queue = build_chat_review_queue(
        connection,
        project_root=paths.project_root,
        local_timezone=resolved_timezone,
    )
    group_index = {
        group["group_id"]: group
        for group in review_queue["groups"]
    }
    maintenance_batches = group_index["maintenance_change_batches"]
    maintenance_state = (
        f"{maintenance_batches['total_count']} recorded maintenance batches"
        if maintenance_batches["total_count"]
        else "maintenance workflow still backlog; no recorded change batches"
    )

    return {
        "generated_at": current_time,
        "agent_mode": agent_mode,
        "pause_reason": pause_reason,
        "runtime_metrics": runtime_metrics,
        "review_queue": review_queue,
        "summary": {
            "pending_expert_review_count": group_index["pending_expert_review_packets"][
                "total_count"
            ],
            "open_incident_count": group_index["open_incidents"]["total_count"],
            "maintenance_batch_count": maintenance_batches["total_count"],
            "maintenance_state": maintenance_state,
        },
    }


def render_chat_startup_dashboard(dashboard: dict[str, Any]) -> str:
    runtime_metrics = dashboard["runtime_metrics"]
    summary = dashboard["summary"]
    lines = [
        "# Job Hunt Copilot Dashboard",
        "",
        f"- Autonomous mode: {dashboard['agent_mode']}",
        f"- Pending expert review items: {summary['pending_expert_review_count']}",
        f"- Open incidents: {summary['open_incident_count']}",
        f"- Maintenance state: {summary['maintenance_state']}",
        (
            "- Autonomous runtime: "
            f"today {runtime_metrics['today']['runtime_display']} | "
            f"yesterday {runtime_metrics['yesterday']['runtime_display']} | "
            f"rolling avg ({runtime_metrics['rolling_window_days']}d) "
            f"{runtime_metrics['rolling_average_daily_runtime_display']}"
        ),
        (
            "- Successful runs: "
            f"today {runtime_metrics['today']['successful_run_count']} | "
            f"yesterday {runtime_metrics['yesterday']['successful_run_count']}"
        ),
        (
            "- Successful sends: "
            f"today {runtime_metrics['today']['successful_send_count']} | "
            f"yesterday {runtime_metrics['yesterday']['successful_send_count']}"
        ),
        (
            "- Bounces: "
            f"today {runtime_metrics['today']['bounce_count']} | "
            f"yesterday {runtime_metrics['yesterday']['bounce_count']}"
        ),
        (
            "- Replies: "
            f"today {runtime_metrics['today']['reply_count']} | "
            f"yesterday {runtime_metrics['yesterday']['reply_count']}"
        ),
        "",
        "## Review Queue",
    ]
    for group in dashboard["review_queue"]["groups"]:
        lines.append(f"- {group['title']}: {group['total_count']}")
        if not group["items"]:
            lines.append("  - none")
            continue
        for item in group["items"]:
            detail_parts = []
            if item["timestamp_display"]:
                detail_parts.append(item["timestamp_display"])
            detail_parts.append(item["headline"])
            detail_parts.append(item["summary"])
            lines.append(f"  - {' | '.join(detail_parts)}")
    lines.append("")
    return "\n".join(lines)
