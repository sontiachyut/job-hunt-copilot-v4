from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol, Sequence

from .artifacts import ArtifactLinkage, publish_json_artifact
from .paths import ProjectPaths
from .records import new_canonical_id

DELIVERY_FEEDBACK_COMPONENT = "delivery_feedback"
DELIVERY_OUTCOME_ARTIFACT_TYPE = "delivery_outcome"

EVENT_STATE_BOUNCED = "bounced"
EVENT_STATE_NOT_BOUNCED = "not_bounced"
EVENT_STATE_REPLIED = "replied"
EVENT_STATES = frozenset(
    {
        EVENT_STATE_BOUNCED,
        EVENT_STATE_NOT_BOUNCED,
        EVENT_STATE_REPLIED,
    }
)

OBSERVATION_SCOPE_IMMEDIATE = "immediate_post_send"
OBSERVATION_SCOPE_DELAYED = "delayed_feedback_sync"

BOUNCE_OBSERVATION_WINDOW_MINUTES = 30
DELAYED_FEEDBACK_POLL_INTERVAL_MINUTES = 5


@dataclass(frozen=True)
class ObservedOutreachMessage:
    outreach_message_id: str
    contact_id: str
    job_posting_id: str | None
    lead_id: str | None
    outreach_mode: str
    recipient_email: str
    thread_id: str | None
    delivery_tracking_id: str | None
    sent_at: str
    company_name: str
    role_title: str | None
    bounce_observation_ends_at: str
    has_bounced: bool
    has_not_bounced: bool
    has_replied: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "outreach_message_id": self.outreach_message_id,
            "contact_id": self.contact_id,
            "job_posting_id": self.job_posting_id,
            "lead_id": self.lead_id,
            "outreach_mode": self.outreach_mode,
            "recipient_email": self.recipient_email,
            "thread_id": self.thread_id,
            "delivery_tracking_id": self.delivery_tracking_id,
            "sent_at": self.sent_at,
            "company_name": self.company_name,
            "role_title": self.role_title,
            "bounce_observation_ends_at": self.bounce_observation_ends_at,
            "has_bounced": self.has_bounced,
            "has_not_bounced": self.has_not_bounced,
            "has_replied": self.has_replied,
        }


@dataclass(frozen=True)
class DeliveryFeedbackSignal:
    signal_type: str
    event_timestamp: str
    outreach_message_id: str | None = None
    recipient_email: str | None = None
    thread_id: str | None = None
    delivery_tracking_id: str | None = None
    provider_message_id: str | None = None
    reply_summary: str | None = None
    raw_reply_excerpt: str | None = None

    def normalized_signal_type(self) -> str:
        normalized = _normalize_optional_text(self.signal_type)
        if normalized not in {EVENT_STATE_BOUNCED, EVENT_STATE_REPLIED}:
            raise ValueError(f"Unsupported delivery-feedback signal type: {self.signal_type!r}")
        return normalized


@dataclass(frozen=True)
class PersistedDeliveryFeedbackEvent:
    delivery_feedback_event_id: str
    outreach_message_id: str
    contact_id: str
    job_posting_id: str | None
    event_state: str
    event_timestamp: str
    artifact_path: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "delivery_feedback_event_id": self.delivery_feedback_event_id,
            "outreach_message_id": self.outreach_message_id,
            "contact_id": self.contact_id,
            "job_posting_id": self.job_posting_id,
            "event_state": self.event_state,
            "event_timestamp": self.event_timestamp,
            "artifact_path": self.artifact_path,
        }


@dataclass(frozen=True)
class DeliveryFeedbackSyncResult:
    feedback_sync_run_id: str
    scheduler_name: str
    scheduler_type: str
    observation_scope: str
    messages_examined: int
    bounce_events_written: int
    reply_events_written: int
    not_bounced_events_written: int
    persisted_events: tuple[PersistedDeliveryFeedbackEvent, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "feedback_sync_run_id": self.feedback_sync_run_id,
            "scheduler_name": self.scheduler_name,
            "scheduler_type": self.scheduler_type,
            "observation_scope": self.observation_scope,
            "messages_examined": self.messages_examined,
            "bounce_events_written": self.bounce_events_written,
            "reply_events_written": self.reply_events_written,
            "not_bounced_events_written": self.not_bounced_events_written,
            "persisted_events": [event.as_dict() for event in self.persisted_events],
        }


class MailboxFeedbackObserver(Protocol):
    def poll(
        self,
        messages: Sequence[ObservedOutreachMessage],
        *,
        current_time: str,
        observation_scope: str,
    ) -> Sequence[DeliveryFeedbackSignal]:
        raise NotImplementedError


@dataclass(frozen=True)
class _MatchedSignal:
    candidate: ObservedOutreachMessage
    signal: DeliveryFeedbackSignal
    matched_by: str


def sync_delivery_feedback(
    connection: sqlite3.Connection,
    *,
    project_root: Path | str,
    current_time: str,
    scheduler_name: str,
    scheduler_type: str,
    observation_scope: str = OBSERVATION_SCOPE_DELAYED,
    observer: MailboxFeedbackObserver | None = None,
    target_outreach_message_ids: Sequence[str] | None = None,
) -> DeliveryFeedbackSyncResult:
    if observation_scope not in {OBSERVATION_SCOPE_IMMEDIATE, OBSERVATION_SCOPE_DELAYED}:
        raise ValueError(f"Unsupported feedback observation scope: {observation_scope!r}")

    paths = ProjectPaths.from_root(project_root)
    normalized_current_time = _isoformat_utc(_parse_iso_datetime(current_time))
    current_dt = _parse_iso_datetime(normalized_current_time)
    feedback_sync_run_id = new_canonical_id("feedback_sync_runs")

    _insert_feedback_sync_run(
        connection,
        feedback_sync_run_id=feedback_sync_run_id,
        scheduler_name=scheduler_name,
        scheduler_type=scheduler_type,
        started_at=normalized_current_time,
        observation_scope=observation_scope,
    )

    messages_examined = 0
    bounce_events_written = 0
    reply_events_written = 0
    not_bounced_events_written = 0
    matched_signal_count = 0
    unmatched_signal_count = 0

    try:
        candidates = _load_observed_outreach_messages(
            connection,
            current_dt=current_dt,
            target_outreach_message_ids=target_outreach_message_ids,
        )
        messages_examined = len(candidates)

        raw_signals: tuple[DeliveryFeedbackSignal, ...]
        if observer is None:
            raw_signals = ()
        else:
            raw_signals = tuple(
                observer.poll(
                    tuple(candidates),
                    current_time=normalized_current_time,
                    observation_scope=observation_scope,
                )
            )

        matched_signals, unmatched_signal_count = _match_feedback_signals(raw_signals, candidates)
        matched_signal_count = len(matched_signals)

        feedback_states = {
            candidate.outreach_message_id: _candidate_feedback_states(candidate)
            for candidate in candidates
        }
        persisted_events: list[PersistedDeliveryFeedbackEvent] = []

        for matched in matched_signals:
            persisted_event = _persist_mailbox_feedback_signal(
                connection,
                paths,
                candidate=matched.candidate,
                signal=matched.signal,
                matched_by=matched.matched_by,
                produced_at=normalized_current_time,
            )
            if persisted_event is None:
                continue
            persisted_events.append(persisted_event)
            feedback_states[matched.candidate.outreach_message_id].add(persisted_event.event_state)
            if persisted_event.event_state == EVENT_STATE_BOUNCED:
                bounce_events_written += 1
            elif persisted_event.event_state == EVENT_STATE_REPLIED:
                reply_events_written += 1

        for candidate in candidates:
            persisted_event = _persist_not_bounced_outcome_if_due(
                connection,
                paths,
                candidate=candidate,
                feedback_states=feedback_states[candidate.outreach_message_id],
                current_dt=current_dt,
                produced_at=normalized_current_time,
            )
            if persisted_event is None:
                continue
            persisted_events.append(persisted_event)
            feedback_states[candidate.outreach_message_id].add(EVENT_STATE_NOT_BOUNCED)
            not_bounced_events_written += 1

        checkpoint = json.dumps(
            {
                "matched_signal_count": matched_signal_count,
                "unmatched_signal_count": unmatched_signal_count,
                "not_bounced_events_written": not_bounced_events_written,
                "poll_interval_minutes": (
                    0
                    if observation_scope == OBSERVATION_SCOPE_IMMEDIATE
                    else DELAYED_FEEDBACK_POLL_INTERVAL_MINUTES
                ),
            },
            sort_keys=True,
        )
        _complete_feedback_sync_run(
            connection,
            feedback_sync_run_id=feedback_sync_run_id,
            completed_at=normalized_current_time,
            messages_examined=messages_examined,
            bounce_events_written=bounce_events_written,
            reply_events_written=reply_events_written,
            last_checkpoint=checkpoint,
        )
        return DeliveryFeedbackSyncResult(
            feedback_sync_run_id=feedback_sync_run_id,
            scheduler_name=scheduler_name,
            scheduler_type=scheduler_type,
            observation_scope=observation_scope,
            messages_examined=messages_examined,
            bounce_events_written=bounce_events_written,
            reply_events_written=reply_events_written,
            not_bounced_events_written=not_bounced_events_written,
            persisted_events=tuple(persisted_events),
        )
    except Exception as exc:
        _fail_feedback_sync_run(
            connection,
            feedback_sync_run_id=feedback_sync_run_id,
            completed_at=normalized_current_time,
            messages_examined=messages_examined,
            bounce_events_written=bounce_events_written,
            reply_events_written=reply_events_written,
            error_message=str(exc),
        )
        raise


def run_immediate_delivery_feedback_poll(
    connection: sqlite3.Connection,
    *,
    project_root: Path | str,
    current_time: str,
    outreach_message_ids: Sequence[str],
    observer: MailboxFeedbackObserver | None = None,
) -> DeliveryFeedbackSyncResult:
    return sync_delivery_feedback(
        connection,
        project_root=project_root,
        current_time=current_time,
        scheduler_name="interactive_post_send",
        scheduler_type="interactive",
        observation_scope=OBSERVATION_SCOPE_IMMEDIATE,
        observer=observer,
        target_outreach_message_ids=outreach_message_ids,
    )


def _insert_feedback_sync_run(
    connection: sqlite3.Connection,
    *,
    feedback_sync_run_id: str,
    scheduler_name: str,
    scheduler_type: str,
    started_at: str,
    observation_scope: str,
) -> None:
    with connection:
        connection.execute(
            """
            INSERT INTO feedback_sync_runs (
              feedback_sync_run_id, scheduler_name, scheduler_type, started_at, result,
              observation_scope
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                feedback_sync_run_id,
                scheduler_name,
                scheduler_type,
                started_at,
                "running",
                observation_scope,
            ),
        )


def _complete_feedback_sync_run(
    connection: sqlite3.Connection,
    *,
    feedback_sync_run_id: str,
    completed_at: str,
    messages_examined: int,
    bounce_events_written: int,
    reply_events_written: int,
    last_checkpoint: str | None,
) -> None:
    with connection:
        connection.execute(
            """
            UPDATE feedback_sync_runs
            SET result = ?, completed_at = ?, messages_examined = ?, bounce_events_written = ?,
                reply_events_written = ?, last_checkpoint = ?, error_message = NULL
            WHERE feedback_sync_run_id = ?
            """,
            (
                "success",
                completed_at,
                messages_examined,
                bounce_events_written,
                reply_events_written,
                last_checkpoint,
                feedback_sync_run_id,
            ),
        )


def _fail_feedback_sync_run(
    connection: sqlite3.Connection,
    *,
    feedback_sync_run_id: str,
    completed_at: str,
    messages_examined: int,
    bounce_events_written: int,
    reply_events_written: int,
    error_message: str,
) -> None:
    with connection:
        connection.execute(
            """
            UPDATE feedback_sync_runs
            SET result = ?, completed_at = ?, messages_examined = ?, bounce_events_written = ?,
                reply_events_written = ?, error_message = ?
            WHERE feedback_sync_run_id = ?
            """,
            (
                "failed",
                completed_at,
                messages_examined,
                bounce_events_written,
                reply_events_written,
                error_message,
                feedback_sync_run_id,
            ),
        )


def _load_observed_outreach_messages(
    connection: sqlite3.Connection,
    *,
    current_dt: datetime,
    target_outreach_message_ids: Sequence[str] | None,
) -> list[ObservedOutreachMessage]:
    normalized_target_ids = tuple(
        dict.fromkeys(
            value
            for value in (
                _normalize_optional_text(candidate)
                for candidate in (target_outreach_message_ids or ())
            )
            if value is not None
        )
    )
    if target_outreach_message_ids is not None and not normalized_target_ids:
        return []

    conditions = [
        "om.message_status = ?",
        "om.sent_at IS NOT NULL",
        "TRIM(om.sent_at) <> ''",
    ]
    parameters: list[object] = ["sent"]
    if normalized_target_ids:
        placeholders = ", ".join("?" for _ in normalized_target_ids)
        conditions.append(f"om.outreach_message_id IN ({placeholders})")
        parameters.extend(normalized_target_ids)

    rows = connection.execute(
        f"""
        SELECT om.outreach_message_id, om.contact_id, om.job_posting_id, om.outreach_mode,
               om.recipient_email, om.thread_id, om.delivery_tracking_id, om.sent_at,
               c.company_name AS contact_company_name, jp.company_name AS posting_company_name,
               jp.role_title, jp.lead_id
        FROM outreach_messages om
        JOIN contacts c
          ON c.contact_id = om.contact_id
        LEFT JOIN job_postings jp
          ON jp.job_posting_id = om.job_posting_id
        WHERE {" AND ".join(conditions)}
        ORDER BY om.sent_at DESC, om.outreach_message_id DESC
        """,
        parameters,
    ).fetchall()

    if not rows:
        return []

    message_ids = [str(row["outreach_message_id"]) for row in rows]
    feedback_states = _load_feedback_states(connection, message_ids)

    candidates: list[ObservedOutreachMessage] = []
    for row in rows:
        outreach_message_id = str(row["outreach_message_id"])
        states = feedback_states.get(outreach_message_id, frozenset())
        sent_at = _isoformat_utc(_parse_iso_datetime(str(row["sent_at"])))
        observation_window_ends_at = _isoformat_utc(
            _parse_iso_datetime(sent_at)
            + timedelta(minutes=BOUNCE_OBSERVATION_WINDOW_MINUTES)
        )
        candidate = ObservedOutreachMessage(
            outreach_message_id=outreach_message_id,
            contact_id=str(row["contact_id"]),
            job_posting_id=_normalize_optional_text(row["job_posting_id"]),
            lead_id=_normalize_optional_text(row["lead_id"]),
            outreach_mode=str(row["outreach_mode"]),
            recipient_email=str(row["recipient_email"]),
            thread_id=_normalize_optional_text(row["thread_id"]),
            delivery_tracking_id=_normalize_optional_text(row["delivery_tracking_id"]),
            sent_at=sent_at,
            company_name=str(
                row["posting_company_name"]
                or row["contact_company_name"]
                or "unknown-company"
            ),
            role_title=_normalize_optional_text(row["role_title"]),
            bounce_observation_ends_at=observation_window_ends_at,
            has_bounced=EVENT_STATE_BOUNCED in states,
            has_not_bounced=EVENT_STATE_NOT_BOUNCED in states,
            has_replied=EVENT_STATE_REPLIED in states,
        )
        if _should_observe_candidate(candidate, current_dt=current_dt):
            candidates.append(candidate)
    return candidates


def _load_feedback_states(
    connection: sqlite3.Connection,
    outreach_message_ids: Sequence[str],
) -> dict[str, frozenset[str]]:
    normalized_ids = tuple(dict.fromkeys(outreach_message_ids))
    if not normalized_ids:
        return {}
    placeholders = ", ".join("?" for _ in normalized_ids)
    rows = connection.execute(
        f"""
        SELECT outreach_message_id, event_state
        FROM delivery_feedback_events
        WHERE outreach_message_id IN ({placeholders})
        """,
        normalized_ids,
    ).fetchall()
    states: dict[str, set[str]] = {outreach_message_id: set() for outreach_message_id in normalized_ids}
    for row in rows:
        states[str(row["outreach_message_id"])].add(str(row["event_state"]))
    return {
        outreach_message_id: frozenset(message_states)
        for outreach_message_id, message_states in states.items()
    }


def _should_observe_candidate(
    candidate: ObservedOutreachMessage,
    *,
    current_dt: datetime,
) -> bool:
    if candidate.has_bounced:
        return False
    if current_dt <= _parse_iso_datetime(candidate.bounce_observation_ends_at):
        return True
    return not candidate.has_replied


def _candidate_feedback_states(candidate: ObservedOutreachMessage) -> set[str]:
    states: set[str] = set()
    if candidate.has_bounced:
        states.add(EVENT_STATE_BOUNCED)
    if candidate.has_not_bounced:
        states.add(EVENT_STATE_NOT_BOUNCED)
    if candidate.has_replied:
        states.add(EVENT_STATE_REPLIED)
    return states


def _match_feedback_signals(
    signals: Sequence[DeliveryFeedbackSignal],
    candidates: Sequence[ObservedOutreachMessage],
) -> tuple[list[_MatchedSignal], int]:
    by_message_id = {candidate.outreach_message_id: candidate for candidate in candidates}
    by_delivery_tracking = _build_candidate_index(
        candidates,
        lambda candidate: candidate.delivery_tracking_id,
    )
    by_thread_id = _build_candidate_index(
        candidates,
        lambda candidate: candidate.thread_id,
    )
    by_recipient_email = _build_candidate_index(
        candidates,
        lambda candidate: candidate.recipient_email,
        normalizer=_normalize_email,
    )

    matched: list[_MatchedSignal] = []
    unmatched_count = 0
    for signal in signals:
        signal.normalized_signal_type()
        candidate: ObservedOutreachMessage | None = None
        matched_by: str | None = None

        outreach_message_id = _normalize_optional_text(signal.outreach_message_id)
        if outreach_message_id is not None:
            candidate = by_message_id.get(outreach_message_id)
            matched_by = "outreach_message_id" if candidate is not None else None

        if candidate is None:
            candidate = _resolve_unique_candidate(
                by_delivery_tracking,
                signal.delivery_tracking_id,
            )
            if candidate is not None:
                matched_by = "delivery_tracking_id"

        if candidate is None:
            candidate = _resolve_unique_candidate(by_thread_id, signal.thread_id)
            if candidate is not None:
                matched_by = "thread_id"

        if candidate is None:
            candidate = _resolve_unique_candidate(
                by_recipient_email,
                signal.recipient_email,
                normalizer=_normalize_email,
            )
            if candidate is not None:
                matched_by = "recipient_email"

        if candidate is None or matched_by is None:
            unmatched_count += 1
            continue
        matched.append(
            _MatchedSignal(
                candidate=candidate,
                signal=signal,
                matched_by=matched_by,
            )
        )
    return matched, unmatched_count


def _build_candidate_index(
    candidates: Sequence[ObservedOutreachMessage],
    key_getter,
    *,
    normalizer=None,
) -> dict[str, list[ObservedOutreachMessage]]:
    index: dict[str, list[ObservedOutreachMessage]] = {}
    for candidate in candidates:
        raw_value = key_getter(candidate)
        normalized = (
            normalizer(raw_value)
            if normalizer is not None
            else _normalize_optional_text(raw_value)
        )
        if normalized is None:
            continue
        index.setdefault(normalized, []).append(candidate)
    return index


def _resolve_unique_candidate(
    index: dict[str, list[ObservedOutreachMessage]],
    raw_value: str | None,
    *,
    normalizer=None,
) -> ObservedOutreachMessage | None:
    normalized = (
        normalizer(raw_value)
        if normalizer is not None
        else _normalize_optional_text(raw_value)
    )
    if normalized is None:
        return None
    matches = index.get(normalized, [])
    if len(matches) != 1:
        return None
    return matches[0]


def _persist_mailbox_feedback_signal(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    candidate: ObservedOutreachMessage,
    signal: DeliveryFeedbackSignal,
    matched_by: str,
    produced_at: str,
) -> PersistedDeliveryFeedbackEvent | None:
    signal_type = signal.normalized_signal_type()
    event_timestamp = _isoformat_utc(_parse_iso_datetime(signal.event_timestamp))
    reply_summary = _normalize_optional_text(signal.reply_summary)
    raw_reply_excerpt = _normalize_optional_text(signal.raw_reply_excerpt)
    if _feedback_event_exists(
        connection,
        outreach_message_id=candidate.outreach_message_id,
        event_state=signal_type,
        event_timestamp=event_timestamp,
        reply_summary=reply_summary,
        raw_reply_excerpt=raw_reply_excerpt,
    ):
        return None
    return _persist_delivery_feedback_event(
        connection,
        paths,
        candidate=candidate,
        event_state=signal_type,
        event_timestamp=event_timestamp,
        reply_summary=reply_summary,
        raw_reply_excerpt=raw_reply_excerpt,
        matched_by=matched_by,
        provider_message_id=_normalize_optional_text(signal.provider_message_id),
        produced_at=produced_at,
    )


def _persist_not_bounced_outcome_if_due(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    candidate: ObservedOutreachMessage,
    feedback_states: set[str],
    current_dt: datetime,
    produced_at: str,
) -> PersistedDeliveryFeedbackEvent | None:
    if EVENT_STATE_BOUNCED in feedback_states or EVENT_STATE_NOT_BOUNCED in feedback_states:
        return None
    window_end_dt = _parse_iso_datetime(candidate.bounce_observation_ends_at)
    if current_dt < window_end_dt:
        return None
    event_timestamp = _isoformat_utc(window_end_dt)
    if _feedback_event_exists(
        connection,
        outreach_message_id=candidate.outreach_message_id,
        event_state=EVENT_STATE_NOT_BOUNCED,
        event_timestamp=event_timestamp,
        reply_summary=None,
        raw_reply_excerpt=None,
    ):
        return None
    return _persist_delivery_feedback_event(
        connection,
        paths,
        candidate=candidate,
        event_state=EVENT_STATE_NOT_BOUNCED,
        event_timestamp=event_timestamp,
        reply_summary=None,
        raw_reply_excerpt=None,
        matched_by="observation_window_close",
        provider_message_id=None,
        produced_at=produced_at,
    )


def _feedback_event_exists(
    connection: sqlite3.Connection,
    *,
    outreach_message_id: str,
    event_state: str,
    event_timestamp: str,
    reply_summary: str | None,
    raw_reply_excerpt: str | None,
) -> bool:
    row = connection.execute(
        """
        SELECT 1
        FROM delivery_feedback_events
        WHERE outreach_message_id = ?
          AND event_state = ?
          AND event_timestamp = ?
          AND COALESCE(reply_summary, '') = COALESCE(?, '')
          AND COALESCE(raw_reply_excerpt, '') = COALESCE(?, '')
        LIMIT 1
        """,
        (
            outreach_message_id,
            event_state,
            event_timestamp,
            reply_summary,
            raw_reply_excerpt,
        ),
    ).fetchone()
    return row is not None


def _persist_delivery_feedback_event(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    candidate: ObservedOutreachMessage,
    event_state: str,
    event_timestamp: str,
    reply_summary: str | None,
    raw_reply_excerpt: str | None,
    matched_by: str,
    provider_message_id: str | None,
    produced_at: str,
) -> PersistedDeliveryFeedbackEvent:
    delivery_feedback_event_id = new_canonical_id("delivery_feedback_events")
    with connection:
        connection.execute(
            """
            INSERT INTO delivery_feedback_events (
              delivery_feedback_event_id, outreach_message_id, event_state, event_timestamp,
              contact_id, job_posting_id, reply_summary, raw_reply_excerpt, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                delivery_feedback_event_id,
                candidate.outreach_message_id,
                event_state,
                event_timestamp,
                candidate.contact_id,
                candidate.job_posting_id,
                reply_summary,
                raw_reply_excerpt,
                produced_at,
            ),
        )

    artifact_path = _delivery_outcome_artifact_path(
        paths,
        candidate=candidate,
        delivery_feedback_event_id=delivery_feedback_event_id,
    )
    latest_artifact_path = _latest_delivery_outcome_path(paths, candidate=candidate)
    published = publish_json_artifact(
        connection,
        paths,
        artifact_type=DELIVERY_OUTCOME_ARTIFACT_TYPE,
        artifact_path=artifact_path,
        producer_component=DELIVERY_FEEDBACK_COMPONENT,
        result="success",
        linkage=ArtifactLinkage(
            lead_id=candidate.lead_id,
            job_posting_id=candidate.job_posting_id,
            contact_id=candidate.contact_id,
            outreach_message_id=candidate.outreach_message_id,
        ),
        payload={
            "delivery_feedback_event_id": delivery_feedback_event_id,
            "outreach_mode": candidate.outreach_mode,
            "recipient_email": candidate.recipient_email,
            "event_state": event_state,
            "event_type": event_state,
            "event_timestamp": event_timestamp,
            "sent_at": candidate.sent_at,
            "bounce_observation_window_ends_at": candidate.bounce_observation_ends_at,
            "reply_summary": reply_summary,
            "raw_reply_excerpt": raw_reply_excerpt,
            "matched_by": matched_by,
            "secondary_identifiers": {
                "thread_id": candidate.thread_id,
                "delivery_tracking_id": candidate.delivery_tracking_id,
                "provider_message_id": provider_message_id,
            },
        },
        produced_at=produced_at,
    )
    _write_text_file(latest_artifact_path, json.dumps(published.contract, indent=2) + "\n")
    return PersistedDeliveryFeedbackEvent(
        delivery_feedback_event_id=delivery_feedback_event_id,
        outreach_message_id=candidate.outreach_message_id,
        contact_id=candidate.contact_id,
        job_posting_id=candidate.job_posting_id,
        event_state=event_state,
        event_timestamp=event_timestamp,
        artifact_path=str(artifact_path.resolve()),
    )


def _delivery_outcome_artifact_path(
    paths: ProjectPaths,
    *,
    candidate: ObservedOutreachMessage,
    delivery_feedback_event_id: str,
) -> Path:
    if candidate.outreach_mode == "general_learning":
        return paths.general_learning_outreach_delivery_outcome_path(
            candidate.company_name,
            candidate.contact_id,
            candidate.outreach_message_id,
            delivery_feedback_event_id,
        )
    return paths.outreach_message_delivery_outcome_path(
        candidate.company_name,
        candidate.role_title or "unknown-role",
        candidate.outreach_message_id,
        delivery_feedback_event_id,
    )


def _latest_delivery_outcome_path(
    paths: ProjectPaths,
    *,
    candidate: ObservedOutreachMessage,
) -> Path:
    if candidate.outreach_mode == "general_learning":
        return paths.general_learning_outreach_latest_delivery_outcome_path(
            candidate.company_name,
            candidate.contact_id,
        )
    return paths.outreach_latest_delivery_outcome_path(
        candidate.company_name,
        candidate.role_title or "unknown-role",
    )


def _parse_iso_datetime(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _isoformat_utc(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _normalize_optional_text(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _normalize_email(value: object) -> str | None:
    normalized = _normalize_optional_text(value)
    if normalized is None:
        return None
    return normalized.lower()


def _write_text_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
