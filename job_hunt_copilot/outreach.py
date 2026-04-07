from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

JOB_POSTING_STATUS_REQUIRES_CONTACTS = "requires_contacts"
JOB_POSTING_STATUS_READY_FOR_OUTREACH = "ready_for_outreach"

CONTACT_STATUS_EXHAUSTED = "exhausted"
POSTING_CONTACT_STATUS_IDENTIFIED = "identified"
POSTING_CONTACT_STATUS_SHORTLISTED = "shortlisted"
POSTING_CONTACT_STATUS_OUTREACH_IN_PROGRESS = "outreach_in_progress"
POSTING_CONTACT_STATUS_OUTREACH_DONE = "outreach_done"
POSTING_CONTACT_STATUS_EXHAUSTED = "exhausted"

RECIPIENT_TYPE_RECRUITER = "recruiter"
RECIPIENT_TYPE_HIRING_MANAGER = "hiring_manager"
RECIPIENT_TYPE_ENGINEER = "engineer"
RECIPIENT_TYPE_ALUMNI = "alumni"
RECIPIENT_TYPE_OTHER_INTERNAL = "other_internal"
RECIPIENT_TYPE_FOUNDER = "founder"

AUTOMATIC_SEND_SET_LIMIT = 3
AUTOMATIC_COMPANY_DAILY_SEND_CAP = 3
MIN_INTER_SEND_GAP_MINUTES = 6
MAX_INTER_SEND_GAP_MINUTES = 10

SEND_SET_PRIMARY_SLOTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("recruiter", (RECIPIENT_TYPE_RECRUITER,)),
    ("manager_adjacent", (RECIPIENT_TYPE_HIRING_MANAGER, RECIPIENT_TYPE_FOUNDER)),
    ("engineer", (RECIPIENT_TYPE_ENGINEER,)),
)
SEND_SET_FALLBACK_TYPE_ORDER = (
    RECIPIENT_TYPE_HIRING_MANAGER,
    RECIPIENT_TYPE_FOUNDER,
    RECIPIENT_TYPE_RECRUITER,
    RECIPIENT_TYPE_ENGINEER,
    RECIPIENT_TYPE_ALUMNI,
    RECIPIENT_TYPE_OTHER_INTERNAL,
)

_CANDIDATE_STATE_READY = "ready"
_CANDIDATE_STATE_NEEDS_EMAIL = "needs_email"
_CANDIDATE_STATE_REPEAT_REVIEW = "repeat_review"
_CANDIDATE_STATE_UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class SendSetContactPlan:
    slot_name: str
    selection_kind: str
    contact_id: str
    job_posting_contact_id: str
    recipient_type: str
    display_name: str
    has_usable_email: bool
    current_working_email: str | None
    readiness_state: str
    blocking_reason: str | None
    prior_outreach_count: int
    link_level_status: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "slot_name": self.slot_name,
            "selection_kind": self.selection_kind,
            "contact_id": self.contact_id,
            "job_posting_contact_id": self.job_posting_contact_id,
            "recipient_type": self.recipient_type,
            "display_name": self.display_name,
            "has_usable_email": self.has_usable_email,
            "current_working_email": self.current_working_email,
            "readiness_state": self.readiness_state,
            "blocking_reason": self.blocking_reason,
            "prior_outreach_count": self.prior_outreach_count,
            "link_level_status": self.link_level_status,
        }


@dataclass(frozen=True)
class RepeatOutreachReviewContact:
    contact_id: str
    job_posting_contact_id: str
    recipient_type: str
    display_name: str
    prior_outreach_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "contact_id": self.contact_id,
            "job_posting_contact_id": self.job_posting_contact_id,
            "recipient_type": self.recipient_type,
            "display_name": self.display_name,
            "prior_outreach_count": self.prior_outreach_count,
        }


@dataclass(frozen=True)
class RoleTargetedSendSetPlan:
    job_posting_id: str
    lead_id: str
    company_name: str
    role_title: str
    posting_status_after_evaluation: str
    ready_for_outreach: bool
    selected_contacts: tuple[SendSetContactPlan, ...]
    repeat_outreach_review_contacts: tuple[RepeatOutreachReviewContact, ...]
    max_send_set_size: int
    current_send_set_size: int
    company_sent_today: int
    remaining_company_daily_capacity: int
    global_gap_minutes: int
    earliest_allowed_send_at: str
    pacing_allowed_now: bool
    pacing_block_reason: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "posting_status_after_review": self.posting_status_after_evaluation,
            "ready_for_outreach": self.ready_for_outreach,
            "max_send_set_size": self.max_send_set_size,
            "current_send_set_size": self.current_send_set_size,
            "selected_slots": [contact.slot_name for contact in self.selected_contacts],
            "selected_contact_ids": [contact.contact_id for contact in self.selected_contacts],
            "selected_job_posting_contact_ids": [
                contact.job_posting_contact_id for contact in self.selected_contacts
            ],
            "selected_contacts": [contact.as_dict() for contact in self.selected_contacts],
            "blocking_contact_ids": [
                contact.contact_id
                for contact in self.selected_contacts
                if contact.readiness_state != _CANDIDATE_STATE_READY
            ],
            "repeat_outreach_review_contact_ids": [
                contact.contact_id for contact in self.repeat_outreach_review_contacts
            ],
            "repeat_outreach_review_contacts": [
                contact.as_dict() for contact in self.repeat_outreach_review_contacts
            ],
            "company_pacing": {
                "daily_send_cap": AUTOMATIC_COMPANY_DAILY_SEND_CAP,
                "company_sent_today": self.company_sent_today,
                "remaining_company_daily_capacity": self.remaining_company_daily_capacity,
                "global_gap_minutes": self.global_gap_minutes,
                "earliest_allowed_send_at": self.earliest_allowed_send_at,
                "pacing_allowed_now": self.pacing_allowed_now,
                "pacing_block_reason": self.pacing_block_reason,
            },
        }


@dataclass(frozen=True)
class _CandidateRow:
    contact_id: str
    job_posting_contact_id: str
    recipient_type: str
    display_name: str
    current_working_email: str | None
    contact_status: str
    link_level_status: str
    prior_outreach_count: int
    link_created_at: str

    @property
    def has_usable_email(self) -> bool:
        return _is_usable_email(self.current_working_email)

    @property
    def selection_state(self) -> str:
        if self.prior_outreach_count > 0:
            return _CANDIDATE_STATE_REPEAT_REVIEW
        if self.link_level_status in {
            POSTING_CONTACT_STATUS_OUTREACH_IN_PROGRESS,
            POSTING_CONTACT_STATUS_OUTREACH_DONE,
            POSTING_CONTACT_STATUS_EXHAUSTED,
        }:
            return _CANDIDATE_STATE_UNAVAILABLE
        if self.contact_status == CONTACT_STATUS_EXHAUSTED:
            return _CANDIDATE_STATE_UNAVAILABLE
        if self.link_level_status not in {
            POSTING_CONTACT_STATUS_IDENTIFIED,
            POSTING_CONTACT_STATUS_SHORTLISTED,
        }:
            return _CANDIDATE_STATE_UNAVAILABLE
        if self.has_usable_email:
            return _CANDIDATE_STATE_READY
        return _CANDIDATE_STATE_NEEDS_EMAIL


def evaluate_role_targeted_send_set(
    connection: sqlite3.Connection,
    *,
    job_posting_id: str,
    current_time: str,
    local_timezone: tzinfo | str | None = None,
) -> RoleTargetedSendSetPlan:
    posting_row = _load_posting_row(connection, job_posting_id=job_posting_id)
    candidates = _load_candidate_rows(connection, job_posting_id=job_posting_id)
    selected_candidates = _select_send_set_candidates(candidates)
    repeat_review_contacts = tuple(
        RepeatOutreachReviewContact(
            contact_id=candidate.contact_id,
            job_posting_contact_id=candidate.job_posting_contact_id,
            recipient_type=candidate.recipient_type,
            display_name=candidate.display_name,
            prior_outreach_count=candidate.prior_outreach_count,
        )
        for candidate in candidates
        if candidate.selection_state == _CANDIDATE_STATE_REPEAT_REVIEW
    )

    selected_contacts = tuple(
        SendSetContactPlan(
            slot_name=slot_name,
            selection_kind=selection_kind,
            contact_id=candidate.contact_id,
            job_posting_contact_id=candidate.job_posting_contact_id,
            recipient_type=candidate.recipient_type,
            display_name=candidate.display_name,
            has_usable_email=candidate.has_usable_email,
            current_working_email=candidate.current_working_email,
            readiness_state=candidate.selection_state,
            blocking_reason=(
                None
                if candidate.selection_state == _CANDIDATE_STATE_READY
                else "waiting_for_usable_email"
            ),
            prior_outreach_count=candidate.prior_outreach_count,
            link_level_status=candidate.link_level_status,
        )
        for slot_name, selection_kind, candidate in selected_candidates
    )
    ready_for_outreach = bool(selected_contacts) and all(
        contact.readiness_state == _CANDIDATE_STATE_READY for contact in selected_contacts
    )

    current_dt = _parse_iso_datetime(current_time)
    resolved_timezone = _resolve_local_timezone(current_dt, local_timezone)
    company_sent_today = _count_company_sends_today(
        connection,
        company_name=str(posting_row["company_name"]),
        current_dt=current_dt,
        local_timezone=resolved_timezone,
    )
    remaining_company_daily_capacity = max(
        0,
        AUTOMATIC_COMPANY_DAILY_SEND_CAP - company_sent_today,
    )
    global_gap_minutes = _determine_global_gap_minutes(
        job_posting_id=job_posting_id,
        selected_contact_ids=[contact.contact_id for contact in selected_contacts],
        current_dt=current_dt,
        local_timezone=resolved_timezone,
    )
    pacing = _build_pacing_plan(
        connection,
        current_dt=current_dt,
        local_timezone=resolved_timezone,
        company_name=str(posting_row["company_name"]),
        company_sent_today=company_sent_today,
        remaining_company_daily_capacity=remaining_company_daily_capacity,
        global_gap_minutes=global_gap_minutes,
    )

    return RoleTargetedSendSetPlan(
        job_posting_id=str(posting_row["job_posting_id"]),
        lead_id=str(posting_row["lead_id"]),
        company_name=str(posting_row["company_name"]),
        role_title=str(posting_row["role_title"]),
        posting_status_after_evaluation=(
            JOB_POSTING_STATUS_READY_FOR_OUTREACH
            if ready_for_outreach
            else JOB_POSTING_STATUS_REQUIRES_CONTACTS
        ),
        ready_for_outreach=ready_for_outreach,
        selected_contacts=selected_contacts,
        repeat_outreach_review_contacts=repeat_review_contacts,
        max_send_set_size=AUTOMATIC_SEND_SET_LIMIT,
        current_send_set_size=len(selected_contacts),
        company_sent_today=company_sent_today,
        remaining_company_daily_capacity=remaining_company_daily_capacity,
        global_gap_minutes=global_gap_minutes,
        earliest_allowed_send_at=pacing["earliest_allowed_send_at"],
        pacing_allowed_now=pacing["pacing_allowed_now"],
        pacing_block_reason=pacing["pacing_block_reason"],
    )


def _load_posting_row(
    connection: sqlite3.Connection,
    *,
    job_posting_id: str,
) -> sqlite3.Row:
    posting_row = connection.execute(
        """
        SELECT job_posting_id, lead_id, company_name, role_title
        FROM job_postings
        WHERE job_posting_id = ?
        """,
        (job_posting_id,),
    ).fetchone()
    if posting_row is None:
        raise ValueError(f"Job posting `{job_posting_id}` was not found.")
    return posting_row


def _load_candidate_rows(
    connection: sqlite3.Connection,
    *,
    job_posting_id: str,
) -> list[_CandidateRow]:
    rows = connection.execute(
        """
        WITH outreach_history AS (
          SELECT contact_id, COUNT(*) AS prior_outreach_count
          FROM outreach_messages
          GROUP BY contact_id
        )
        SELECT jpc.job_posting_contact_id, jpc.contact_id, jpc.recipient_type, jpc.link_level_status,
               jpc.created_at AS link_created_at, c.display_name, c.current_working_email,
               c.contact_status, COALESCE(oh.prior_outreach_count, 0) AS prior_outreach_count
        FROM job_posting_contacts jpc
        JOIN contacts c
          ON c.contact_id = jpc.contact_id
        LEFT JOIN outreach_history oh
          ON oh.contact_id = jpc.contact_id
        WHERE jpc.job_posting_id = ?
        ORDER BY jpc.created_at ASC, jpc.job_posting_contact_id ASC
        """,
        (job_posting_id,),
    ).fetchall()
    return [
        _CandidateRow(
            contact_id=str(row["contact_id"]),
            job_posting_contact_id=str(row["job_posting_contact_id"]),
            recipient_type=str(row["recipient_type"]).strip(),
            display_name=str(row["display_name"]).strip(),
            current_working_email=_normalize_optional_text(row["current_working_email"]),
            contact_status=str(row["contact_status"]).strip(),
            link_level_status=str(row["link_level_status"]).strip(),
            prior_outreach_count=int(row["prior_outreach_count"] or 0),
            link_created_at=str(row["link_created_at"]).strip(),
        )
        for row in rows
        if str(row["recipient_type"]).strip()
    ]


def _select_send_set_candidates(
    candidates: Sequence[_CandidateRow],
) -> list[tuple[str, str, _CandidateRow]]:
    selected: list[tuple[str, str, _CandidateRow]] = []
    selected_contact_ids: set[str] = set()

    for slot_name, recipient_types in SEND_SET_PRIMARY_SLOTS:
        candidate = _pick_best_candidate(
            candidates,
            allowed_recipient_types=recipient_types,
            selected_contact_ids=selected_contact_ids,
        )
        if candidate is None:
            continue
        selected.append((slot_name, "preferred", candidate))
        selected_contact_ids.add(candidate.contact_id)

    if len(selected) >= AUTOMATIC_SEND_SET_LIMIT:
        return selected[:AUTOMATIC_SEND_SET_LIMIT]

    fallback_candidates = sorted(
        (
            candidate
            for candidate in candidates
            if candidate.contact_id not in selected_contact_ids
            and candidate.selection_state in {_CANDIDATE_STATE_READY, _CANDIDATE_STATE_NEEDS_EMAIL}
        ),
        key=_fallback_sort_key,
    )
    for candidate in fallback_candidates:
        if len(selected) >= AUTOMATIC_SEND_SET_LIMIT:
            break
        selected.append((f"fallback_{len(selected) + 1}", "fallback", candidate))
        selected_contact_ids.add(candidate.contact_id)
    return selected


def _pick_best_candidate(
    candidates: Sequence[_CandidateRow],
    *,
    allowed_recipient_types: Sequence[str],
    selected_contact_ids: set[str],
) -> _CandidateRow | None:
    eligible_candidates = [
        candidate
        for candidate in candidates
        if candidate.contact_id not in selected_contact_ids
        and candidate.recipient_type in allowed_recipient_types
        and candidate.selection_state in {_CANDIDATE_STATE_READY, _CANDIDATE_STATE_NEEDS_EMAIL}
    ]
    if not eligible_candidates:
        return None
    return min(eligible_candidates, key=_preferred_sort_key)


def _preferred_sort_key(candidate: _CandidateRow) -> tuple[int, int, str, str]:
    return (
        _selection_state_rank(candidate.selection_state),
        0 if candidate.link_level_status == POSTING_CONTACT_STATUS_SHORTLISTED else 1,
        candidate.link_created_at,
        candidate.contact_id,
    )


def _fallback_sort_key(candidate: _CandidateRow) -> tuple[int, int, int, str, str]:
    return (
        _selection_state_rank(candidate.selection_state),
        _fallback_type_rank(candidate.recipient_type),
        0 if candidate.link_level_status == POSTING_CONTACT_STATUS_SHORTLISTED else 1,
        candidate.link_created_at,
        candidate.contact_id,
    )


def _selection_state_rank(selection_state: str) -> int:
    if selection_state == _CANDIDATE_STATE_READY:
        return 0
    if selection_state == _CANDIDATE_STATE_NEEDS_EMAIL:
        return 1
    if selection_state == _CANDIDATE_STATE_REPEAT_REVIEW:
        return 2
    return 3


def _fallback_type_rank(recipient_type: str) -> int:
    try:
        return SEND_SET_FALLBACK_TYPE_ORDER.index(recipient_type)
    except ValueError:
        return len(SEND_SET_FALLBACK_TYPE_ORDER)


def _count_company_sends_today(
    connection: sqlite3.Connection,
    *,
    company_name: str,
    current_dt: datetime,
    local_timezone: tzinfo,
) -> int:
    rows = connection.execute(
        """
        SELECT om.sent_at, jp.company_name AS posting_company_name, c.company_name AS contact_company_name
        FROM outreach_messages om
        LEFT JOIN job_postings jp
          ON jp.job_posting_id = om.job_posting_id
        LEFT JOIN contacts c
          ON c.contact_id = om.contact_id
        WHERE om.sent_at IS NOT NULL
          AND TRIM(om.sent_at) <> ''
        """
    ).fetchall()
    current_local_day = current_dt.astimezone(local_timezone).date()
    send_count = 0
    for row in rows:
        row_company_name = _normalize_optional_text(row["posting_company_name"]) or _normalize_optional_text(
            row["contact_company_name"]
        )
        if row_company_name != company_name:
            continue
        sent_at = _normalize_optional_text(row["sent_at"])
        if sent_at is None:
            continue
        sent_at_local = _parse_iso_datetime(sent_at).astimezone(local_timezone)
        if sent_at_local.date() == current_local_day:
            send_count += 1
    return send_count


def _determine_global_gap_minutes(
    *,
    job_posting_id: str,
    selected_contact_ids: Sequence[str],
    current_dt: datetime,
    local_timezone: tzinfo,
) -> int:
    seed = "|".join(
        [
            job_posting_id,
            current_dt.astimezone(local_timezone).date().isoformat(),
            ",".join(sorted(selected_contact_ids)),
        ]
    )
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return MIN_INTER_SEND_GAP_MINUTES + (digest[0] % (MAX_INTER_SEND_GAP_MINUTES - MIN_INTER_SEND_GAP_MINUTES + 1))


def _build_pacing_plan(
    connection: sqlite3.Connection,
    *,
    current_dt: datetime,
    local_timezone: tzinfo,
    company_name: str,
    company_sent_today: int,
    remaining_company_daily_capacity: int,
    global_gap_minutes: int,
) -> dict[str, Any]:
    constraint_times = [current_dt]
    pacing_block_reason: str | None = None

    if remaining_company_daily_capacity <= 0 or company_sent_today >= AUTOMATIC_COMPANY_DAILY_SEND_CAP:
        next_day = current_dt.astimezone(local_timezone).date() + timedelta(days=1)
        company_window_start = datetime.combine(next_day, time.min, tzinfo=local_timezone).astimezone(UTC)
        constraint_times.append(company_window_start)
        pacing_block_reason = "company_daily_cap"

    latest_sent_at = _load_latest_sent_at(connection)
    if latest_sent_at is not None:
        gap_due_at = latest_sent_at + timedelta(minutes=global_gap_minutes)
        constraint_times.append(gap_due_at)
        if gap_due_at > current_dt and pacing_block_reason is None:
            pacing_block_reason = "global_inter_send_gap"

    earliest_allowed_send_at = max(constraint_times)
    return {
        "earliest_allowed_send_at": _isoformat_utc(earliest_allowed_send_at),
        "pacing_allowed_now": earliest_allowed_send_at <= current_dt,
        "pacing_block_reason": pacing_block_reason,
        "company_name": company_name,
    }


def _load_latest_sent_at(connection: sqlite3.Connection) -> datetime | None:
    row = connection.execute(
        """
        SELECT sent_at
        FROM outreach_messages
        WHERE sent_at IS NOT NULL
          AND TRIM(sent_at) <> ''
        ORDER BY sent_at DESC, outreach_message_id DESC
        LIMIT 1
        """
    ).fetchone()
    sent_at = _normalize_optional_text(row["sent_at"]) if row is not None else None
    if sent_at is None:
        return None
    return _parse_iso_datetime(sent_at)


def _resolve_local_timezone(current_dt: datetime, local_timezone: tzinfo | str | None) -> tzinfo:
    if isinstance(local_timezone, str):
        return ZoneInfo(local_timezone)
    if local_timezone is not None:
        return local_timezone
    return current_dt.astimezone().tzinfo or UTC


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


def _is_usable_email(value: str | None) -> bool:
    return bool(value and "@" in value and "." in value.split("@", 1)[-1])
