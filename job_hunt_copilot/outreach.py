from __future__ import annotations

import html
import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from pathlib import Path
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

import yaml

from .artifacts import ArtifactLinkage, publish_json_artifact, register_artifact_record
from .paths import ProjectPaths
from .records import lifecycle_timestamps, new_canonical_id

OUTREACH_COMPONENT = "email_drafting_sending"
OUTREACH_DRAFT_ARTIFACT_TYPE = "email_draft"
OUTREACH_DRAFT_HTML_ARTIFACT_TYPE = "email_draft_html"
SEND_RESULT_ARTIFACT_TYPE = "send_result"

JOB_POSTING_STATUS_REQUIRES_CONTACTS = "requires_contacts"
JOB_POSTING_STATUS_READY_FOR_OUTREACH = "ready_for_outreach"
JOB_POSTING_STATUS_OUTREACH_IN_PROGRESS = "outreach_in_progress"

CONTACT_STATUS_WORKING_EMAIL_FOUND = "working_email_found"
CONTACT_STATUS_OUTREACH_IN_PROGRESS = "outreach_in_progress"
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

OUTREACH_MODE_ROLE_TARGETED = "role_targeted"
OUTREACH_MODE_GENERAL_LEARNING = "general_learning"
MESSAGE_STATUS_GENERATED = "generated"
MESSAGE_STATUS_FAILED = "failed"
MESSAGE_STATUS_SENT = "sent"

PROFILE_FIELD_RE = re.compile(r"^- \*\*(?P<label>[^*]+):\*\* (?P<value>.+?)\s*$")
MARKDOWN_HEADING_RE = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<title>.+?)\s*$")
METRIC_RE = re.compile(r"\b(?:\$?\d[\d,.]*\+?%?|\d[\d,.]*\+?(?:\s?(?:TPS|ms|hours?|day|days|hospitals?|users?|microservices?|records(?:/second)?|students?|tests?|bugs?)))\b")
NAME_SPLIT_RE = re.compile(r"\s+")


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


class OutreachDraftingError(RuntimeError):
    pass


@dataclass(frozen=True)
class SenderIdentity:
    name: str
    email: str | None
    phone: str | None
    linkedin_url: str | None
    github_url: str | None
    education_summary: str | None


@dataclass(frozen=True)
class RenderedDraft:
    subject: str
    body_markdown: str
    body_html: str | None
    include_forwardable_snippet: bool


@dataclass(frozen=True)
class RoleTargetedDraftContext:
    job_posting_id: str
    job_posting_contact_id: str
    lead_id: str
    company_name: str
    role_title: str
    recipient_type: str
    contact_id: str
    display_name: str
    recipient_email: str
    position_title: str | None
    discovery_summary: str | None
    recipient_profile: Mapping[str, Any] | None
    jd_text: str
    role_intent_summary: str | None
    proof_point: str | None
    fit_summary: str | None
    work_area: str | None
    sender: SenderIdentity
    tailored_resume_path: str


@dataclass(frozen=True)
class GeneralLearningDraftContext:
    contact_id: str
    company_name: str
    display_name: str
    recipient_email: str
    recipient_type: str
    position_title: str | None
    recipient_profile: Mapping[str, Any] | None
    sender: SenderIdentity


@dataclass(frozen=True)
class DraftFailure:
    outreach_message_id: str
    contact_id: str
    job_posting_contact_id: str | None
    reason_code: str
    message: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "outreach_message_id": self.outreach_message_id,
            "contact_id": self.contact_id,
            "job_posting_contact_id": self.job_posting_contact_id,
            "reason_code": self.reason_code,
            "message": self.message,
        }


@dataclass(frozen=True)
class DraftedOutreachMessage:
    outreach_message_id: str
    contact_id: str
    job_posting_id: str | None
    job_posting_contact_id: str | None
    outreach_mode: str
    recipient_email: str
    message_status: str
    subject: str
    body_text: str
    body_html: str | None
    body_text_artifact_path: str
    send_result_artifact_path: str
    body_html_artifact_path: str | None
    resume_attachment_path: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "outreach_message_id": self.outreach_message_id,
            "contact_id": self.contact_id,
            "job_posting_id": self.job_posting_id,
            "job_posting_contact_id": self.job_posting_contact_id,
            "outreach_mode": self.outreach_mode,
            "recipient_email": self.recipient_email,
            "message_status": self.message_status,
            "subject": self.subject,
            "body_text_artifact_path": self.body_text_artifact_path,
            "send_result_artifact_path": self.send_result_artifact_path,
            "body_html_artifact_path": self.body_html_artifact_path,
            "resume_attachment_path": self.resume_attachment_path,
        }


@dataclass(frozen=True)
class RoleTargetedDraftBatchResult:
    job_posting_id: str
    selected_contact_ids: tuple[str, ...]
    drafted_messages: tuple[DraftedOutreachMessage, ...]
    failed_contacts: tuple[DraftFailure, ...]
    posting_status_after_drafting: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "job_posting_id": self.job_posting_id,
            "selected_contact_ids": list(self.selected_contact_ids),
            "drafted_messages": [message.as_dict() for message in self.drafted_messages],
            "failed_contacts": [failure.as_dict() for failure in self.failed_contacts],
            "posting_status_after_drafting": self.posting_status_after_drafting,
        }


@dataclass(frozen=True)
class GeneralLearningDraftResult:
    drafted_message: DraftedOutreachMessage

    def as_dict(self) -> dict[str, Any]:
        return {"drafted_message": self.drafted_message.as_dict()}


class OutreachDraftRenderer:
    def render_role_targeted(self, context: RoleTargetedDraftContext) -> RenderedDraft:
        raise NotImplementedError

    def render_general_learning(self, context: GeneralLearningDraftContext) -> RenderedDraft:
        raise NotImplementedError


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


class DeterministicOutreachDraftRenderer(OutreachDraftRenderer):
    def render_role_targeted(self, context: RoleTargetedDraftContext) -> RenderedDraft:
        work_area = context.work_area or context.role_intent_summary or "this team's work"
        opening = (
            f"I came across the {context.role_title} opening at {context.company_name}, and "
            f"the work this team seems to be doing around {work_area} immediately stood out to me. "
            f"I've been working on similar backend and distributed-systems problems, so the role felt "
            "like one where there could be real overlap."
        )
        why_this_person = _build_role_targeted_why_line(context)
        proof_point = context.proof_point or (
            "one example of that overlap is the distributed systems work I have done across reliability, "
            "performance, and production delivery."
        )
        education_line = context.sender.education_summary or "I am currently finishing my MS in Computer Science at ASU."
        fit_summary = context.fit_summary or "backend systems, distributed services, and production reliability"
        body_lines = [
            f"Hi {_first_name(context.display_name)},",
            "",
            opening,
            "",
            (
                f"{why_this_person} {education_line} One example of that overlap is {proof_point}. "
                f"The role feels like a strong fit for both my background and the kind of systems work "
                "I want to keep growing in."
            ),
            "",
            (
                "If it makes sense, would you be open to a short 15-minute Zoom sometime this or next week? "
                "If you're not the right person, I'd also really appreciate it if you could point me to the "
                "right person or forward my resume internally."
            ),
        ]
        include_snippet = context.recipient_type != RECIPIENT_TYPE_HIRING_MANAGER
        if include_snippet:
            body_lines.extend(
                [
                    "",
                    "Forwardable snippet:",
                    f"> Candidate: {context.sender.name} | {_snippet_stage(context.sender)} | {_compact_linkedin(context.sender.linkedin_url)}",
                    f"> Experience: {_experience_summary_line(context)}",
                    f"> Impact: {_impact_summary_line(context)}",
                    f"> Fit: {fit_summary}",
                ]
            )
        body_lines.extend(
            [
                "",
                "Best,",
                context.sender.name,
                *_signature_lines(context.sender),
            ]
        )
        body_markdown = "\n".join(line for line in body_lines if line is not None).strip() + "\n"
        return RenderedDraft(
            subject=_build_role_targeted_subject(context),
            body_markdown=body_markdown,
            body_html=_render_markdown_email_html(body_markdown),
            include_forwardable_snippet=include_snippet,
        )

    def render_general_learning(self, context: GeneralLearningDraftContext) -> RenderedDraft:
        work_signal = _recipient_work_signal(context.recipient_profile)
        role_hint = context.position_title or "your work"
        subject = f"Learning from your work at {context.company_name} | {context.sender.name}"
        opening = (
            f"I came across your background at {context.company_name}"
            if not work_signal
            else f"I came across your work on {work_signal} at {context.company_name}"
        )
        body_lines = [
            f"Hi {_first_name(context.display_name)},",
            "",
            (
                f"{opening}, and it stood out to me because I have been trying to learn from people working close to "
                f"{role_hint.lower()}. I am currently finishing my MS in Computer Science at ASU and have been "
                "gravitating toward backend, distributed-systems, and AI-adjacent engineering work."
            ),
            "",
            (
                "I am reaching out in a learning-first mode rather than with a direct role ask. "
                "If you would be open to it, I would really value a short 15-minute conversation to learn "
                "how you think about the work, the team, and what matters most in that area."
            ),
            "",
            "Best,",
            context.sender.name,
            *_signature_lines(context.sender),
        ]
        body_markdown = "\n".join(body_lines).strip() + "\n"
        return RenderedDraft(
            subject=subject,
            body_markdown=body_markdown,
            body_html=_render_markdown_email_html(body_markdown),
            include_forwardable_snippet=False,
        )


def generate_role_targeted_send_set_drafts(
    connection: sqlite3.Connection,
    *,
    project_root: Path | str,
    job_posting_id: str,
    current_time: str,
    local_timezone: tzinfo | str | None = None,
    renderer: OutreachDraftRenderer | None = None,
) -> RoleTargetedDraftBatchResult:
    paths = ProjectPaths.from_root(project_root)
    posting_row = _load_role_targeted_draft_posting_row(connection, job_posting_id=job_posting_id)
    send_set_plan = evaluate_role_targeted_send_set(
        connection,
        job_posting_id=job_posting_id,
        current_time=current_time,
        local_timezone=local_timezone,
    )
    if posting_row["posting_status"] != JOB_POSTING_STATUS_READY_FOR_OUTREACH:
        raise OutreachDraftingError(
            f"Job posting `{job_posting_id}` is `{posting_row['posting_status']}`; drafting starts only from `ready_for_outreach`."
        )
    if not send_set_plan.ready_for_outreach or not send_set_plan.selected_contacts:
        raise OutreachDraftingError(
            f"Job posting `{job_posting_id}` does not have a fully ready current send set."
        )

    sender = _load_sender_identity(paths)
    tailoring_inputs = _load_tailoring_draft_inputs(
        connection,
        paths,
        posting_row=posting_row,
        current_time=current_time,
    )
    draft_renderer = renderer or DeterministicOutreachDraftRenderer()
    drafted_messages: list[DraftedOutreachMessage] = []
    failed_contacts: list[DraftFailure] = []
    posting_promoted = False

    for contact_plan in send_set_plan.selected_contacts:
        contact_row = _load_draft_contact_row(
            connection,
            job_posting_id=job_posting_id,
            contact_id=contact_plan.contact_id,
        )
        recipient_email = _normalize_optional_text(contact_row["current_working_email"])
        if recipient_email is None:
            raise OutreachDraftingError(
                f"Contact `{contact_plan.contact_id}` is missing a usable working email."
            )
        message_id = new_canonical_id("outreach_messages")
        if not posting_promoted:
            _promote_posting_into_outreach_in_progress(
                connection,
                posting_row=posting_row,
                current_time=current_time,
            )
            posting_promoted = True
        _promote_contact_into_outreach_in_progress(
            connection,
            posting_row=posting_row,
            contact_row=contact_row,
            current_time=current_time,
        )
        recipient_profile = _load_recipient_profile(
            connection,
            paths,
            job_posting_id=job_posting_id,
            contact_id=str(contact_row["contact_id"]),
        )
        context = RoleTargetedDraftContext(
            job_posting_id=str(posting_row["job_posting_id"]),
            job_posting_contact_id=str(contact_row["job_posting_contact_id"]),
            lead_id=str(posting_row["lead_id"]),
            company_name=str(posting_row["company_name"]),
            role_title=str(posting_row["role_title"]),
            recipient_type=str(contact_row["recipient_type"]),
            contact_id=str(contact_row["contact_id"]),
            display_name=str(contact_row["display_name"]),
            recipient_email=recipient_email,
            position_title=_normalize_optional_text(contact_row["position_title"]),
            discovery_summary=_normalize_optional_text(contact_row["discovery_summary"]),
            recipient_profile=recipient_profile,
            jd_text=tailoring_inputs["jd_text"],
            role_intent_summary=tailoring_inputs["role_intent_summary"],
            proof_point=_select_proof_point(tailoring_inputs["step_6_payload"]),
            fit_summary=_select_fit_summary(
                tailoring_inputs["step_6_payload"],
                tailoring_inputs["step_3_payload"],
            ),
            work_area=_role_work_area(
                tailoring_inputs["step_3_payload"],
                tailoring_inputs["jd_text"],
            ),
            sender=sender,
            tailored_resume_path=str(tailoring_inputs["resume_path"]),
        )
        try:
            rendered = draft_renderer.render_role_targeted(context)
        except Exception as exc:
            failure = _persist_failed_draft_attempt(
                connection,
                paths,
                posting_row=posting_row,
                contact_row=contact_row,
                outreach_message_id=message_id,
                outreach_mode=OUTREACH_MODE_ROLE_TARGETED,
                recipient_email=recipient_email,
                current_time=current_time,
                reason_code="draft_generation_failed",
                message=str(exc) or "Draft generation failed.",
            )
            failed_contacts.append(failure)
            continue

        drafted = _persist_rendered_draft(
            connection,
            paths,
            posting_row=posting_row,
            contact_row=contact_row,
            outreach_message_id=message_id,
            outreach_mode=OUTREACH_MODE_ROLE_TARGETED,
            recipient_email=recipient_email,
            rendered=rendered,
            current_time=current_time,
            resume_attachment_path=str(tailoring_inputs["resume_path"]),
            use_role_targeted_mirrors=True,
        )
        drafted_messages.append(drafted)

    return RoleTargetedDraftBatchResult(
        job_posting_id=job_posting_id,
        selected_contact_ids=tuple(contact.contact_id for contact in send_set_plan.selected_contacts),
        drafted_messages=tuple(drafted_messages),
        failed_contacts=tuple(failed_contacts),
        posting_status_after_drafting=JOB_POSTING_STATUS_OUTREACH_IN_PROGRESS,
    )


def generate_general_learning_draft(
    connection: sqlite3.Connection,
    *,
    project_root: Path | str,
    contact_id: str,
    current_time: str,
    renderer: OutreachDraftRenderer | None = None,
) -> GeneralLearningDraftResult:
    paths = ProjectPaths.from_root(project_root)
    sender = _load_sender_identity(paths)
    contact_row = _load_general_learning_contact_row(connection, contact_id=contact_id)
    recipient_email = _normalize_optional_text(contact_row["current_working_email"])
    if recipient_email is None:
        raise OutreachDraftingError(f"Contact `{contact_id}` is missing a usable working email.")
    recipient_profile = _load_latest_contact_recipient_profile(
        connection,
        paths,
        contact_id=contact_id,
    )
    context = GeneralLearningDraftContext(
        contact_id=str(contact_row["contact_id"]),
        company_name=str(contact_row["company_name"] or "unknown-company"),
        display_name=str(contact_row["display_name"]),
        recipient_email=recipient_email,
        recipient_type=str(contact_row["recipient_type"] or RECIPIENT_TYPE_OTHER_INTERNAL),
        position_title=_normalize_optional_text(contact_row["position_title"]),
        recipient_profile=recipient_profile,
        sender=sender,
    )
    draft_renderer = renderer or DeterministicOutreachDraftRenderer()
    message_id = new_canonical_id("outreach_messages")
    rendered = draft_renderer.render_general_learning(context)
    drafted_message = _persist_rendered_general_learning_draft(
        connection,
        paths,
        contact_row=contact_row,
        outreach_message_id=message_id,
        recipient_email=recipient_email,
        rendered=rendered,
        current_time=current_time,
    )
    return GeneralLearningDraftResult(drafted_message=drafted_message)


def _load_role_targeted_draft_posting_row(
    connection: sqlite3.Connection,
    *,
    job_posting_id: str,
) -> sqlite3.Row:
    row = connection.execute(
        """
        SELECT jp.job_posting_id, jp.lead_id, jp.company_name, jp.role_title, jp.posting_status,
               jp.jd_artifact_path
        FROM job_postings jp
        WHERE jp.job_posting_id = ?
        """,
        (job_posting_id,),
    ).fetchone()
    if row is None:
        raise OutreachDraftingError(f"Job posting `{job_posting_id}` was not found.")
    return row


def _load_draft_contact_row(
    connection: sqlite3.Connection,
    *,
    job_posting_id: str,
    contact_id: str,
) -> sqlite3.Row:
    row = connection.execute(
        """
        SELECT jpc.job_posting_contact_id, jpc.job_posting_id, jpc.contact_id, jpc.recipient_type,
               jpc.link_level_status, c.display_name, c.current_working_email, c.contact_status,
               c.position_title, c.discovery_summary, c.company_name
        FROM job_posting_contacts jpc
        JOIN contacts c
          ON c.contact_id = jpc.contact_id
        WHERE jpc.job_posting_id = ?
          AND jpc.contact_id = ?
        """,
        (job_posting_id, contact_id),
    ).fetchone()
    if row is None:
        raise OutreachDraftingError(
            f"Linked contact `{contact_id}` for job posting `{job_posting_id}` was not found."
        )
    return row


def _load_general_learning_contact_row(
    connection: sqlite3.Connection,
    *,
    contact_id: str,
) -> sqlite3.Row:
    row = connection.execute(
        """
        SELECT c.contact_id, c.display_name, c.current_working_email, c.company_name,
               c.position_title, c.discovery_summary,
               (
                 SELECT jpc.recipient_type
                 FROM job_posting_contacts jpc
                 WHERE jpc.contact_id = c.contact_id
                 ORDER BY jpc.created_at DESC, jpc.job_posting_contact_id DESC
                 LIMIT 1
               ) AS recipient_type
        FROM contacts c
        WHERE c.contact_id = ?
        """,
        (contact_id,),
    ).fetchone()
    if row is None:
        raise OutreachDraftingError(f"Contact `{contact_id}` was not found.")
    return row


def _load_tailoring_draft_inputs(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    posting_row: Mapping[str, Any],
    current_time: str,
) -> dict[str, Any]:
    latest_run = connection.execute(
        """
        SELECT resume_tailoring_run_id, resume_review_status, final_resume_path, meta_yaml_path
        FROM resume_tailoring_runs
        WHERE job_posting_id = ?
        ORDER BY created_at DESC, resume_tailoring_run_id DESC
        LIMIT 1
        """,
        (posting_row["job_posting_id"],),
    ).fetchone()
    if latest_run is None or str(latest_run["resume_review_status"]).strip() != "approved":
        raise OutreachDraftingError(
            f"Job posting `{posting_row['job_posting_id']}` is not backed by an approved tailoring run."
        )
    resume_path_text = _normalize_optional_text(latest_run["final_resume_path"])
    if resume_path_text is None:
        raise OutreachDraftingError(
            f"Job posting `{posting_row['job_posting_id']}` does not have a tailored resume attachment path."
        )
    resume_path = paths.resolve_from_root(resume_path_text)
    if not resume_path.exists():
        raise OutreachDraftingError(f"Tailored resume path does not exist: {resume_path}")

    company_name = str(posting_row["company_name"])
    role_title = str(posting_row["role_title"])
    step_3_path = paths.tailoring_step_3_jd_signals_path(company_name, role_title)
    step_6_path = paths.tailoring_step_6_candidate_bullets_path(company_name, role_title)
    if not step_3_path.exists() or not step_6_path.exists():
        raise OutreachDraftingError(
            f"Tailoring intelligence artifacts are missing for job posting `{posting_row['job_posting_id']}`."
        )
    jd_text = _load_posting_jd_text(paths, posting_row)
    return {
        "current_time": current_time,
        "resume_path": resume_path,
        "jd_text": jd_text,
        "step_3_payload": _read_yaml_file(step_3_path),
        "step_6_payload": _read_yaml_file(step_6_path),
        "role_intent_summary": _normalize_optional_text(
            _read_yaml_file(step_3_path).get("role_intent_summary")
        ),
    }


def _load_posting_jd_text(paths: ProjectPaths, posting_row: Mapping[str, Any]) -> str:
    jd_artifact_path = _normalize_optional_text(posting_row["jd_artifact_path"])
    if jd_artifact_path is None:
        return ""
    jd_path = paths.resolve_from_root(jd_artifact_path)
    if not jd_path.exists():
        return ""
    return jd_path.read_text(encoding="utf-8")


def _load_sender_identity(paths: ProjectPaths) -> SenderIdentity:
    profile_path = paths.assets_dir / "resume-tailoring" / "profile.md"
    if not profile_path.exists():
        raise OutreachDraftingError("Sender master profile is missing.")
    profile_text = profile_path.read_text(encoding="utf-8")
    fields: dict[str, str] = {}
    education_line: str | None = None
    current_heading = ""
    for raw_line in profile_text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("<!--"):
            continue
        heading_match = MARKDOWN_HEADING_RE.match(stripped)
        if heading_match is not None:
            current_heading = heading_match.group("title").strip().lower()
            continue
        field_match = PROFILE_FIELD_RE.match(stripped)
        if field_match is not None:
            fields[field_match.group("label").strip().lower()] = field_match.group("value").strip()
            continue
        if current_heading == "education" and stripped.startswith("- ") and education_line is None:
            education_line = stripped[2:].strip()
    name = fields.get("name", "Achyutaram Sonti")
    return SenderIdentity(
        name=name,
        email=fields.get("email"),
        phone=fields.get("phone"),
        linkedin_url=fields.get("linkedin"),
        github_url=fields.get("github"),
        education_summary=_normalize_education_line(education_line),
    )


def _normalize_education_line(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"\*\*", "", value).strip()
    if "Arizona State University" in normalized and "MS" in normalized:
        return "I am currently finishing my MS in Computer Science at ASU."
    return normalized


def _load_recipient_profile(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    job_posting_id: str,
    contact_id: str,
) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT file_path
        FROM artifact_records
        WHERE artifact_type = ?
          AND job_posting_id = ?
          AND contact_id = ?
        ORDER BY created_at DESC, artifact_id DESC
        LIMIT 1
        """,
        ("recipient_profile", job_posting_id, contact_id),
    ).fetchone()
    if row is None or not row["file_path"]:
        return None
    path = paths.resolve_from_root(str(row["file_path"]))
    if not path.exists():
        return None
    payload = _read_json_file(path)
    profile = payload.get("profile")
    return profile if isinstance(profile, Mapping) else None


def _load_latest_contact_recipient_profile(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    contact_id: str,
) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT file_path
        FROM artifact_records
        WHERE artifact_type = ?
          AND contact_id = ?
        ORDER BY created_at DESC, artifact_id DESC
        LIMIT 1
        """,
        ("recipient_profile", contact_id),
    ).fetchone()
    if row is None or not row["file_path"]:
        return None
    path = paths.resolve_from_root(str(row["file_path"]))
    if not path.exists():
        return None
    payload = _read_json_file(path)
    profile = payload.get("profile")
    return profile if isinstance(profile, Mapping) else None


def _select_proof_point(step_6_payload: Mapping[str, Any]) -> str | None:
    bullets = list((step_6_payload.get("software_engineer") or {}).get("bullets") or [])
    if not bullets:
        return None
    texts = [str(entry.get("text") or "").strip() for entry in bullets if str(entry.get("text") or "").strip()]
    if not texts:
        return None
    texts.sort(key=lambda text: (0 if METRIC_RE.search(text) else 1, len(text)))
    return texts[0]


def _select_fit_summary(
    step_6_payload: Mapping[str, Any],
    step_3_payload: Mapping[str, Any],
) -> str | None:
    selected_items: list[str] = []
    signal_ids = {
        str(signal.get("signal_id"))
        for signal in step_3_payload.get("signals", [])
        if signal.get("priority") in {"must_have", "core_responsibility"}
    }
    for entry in step_6_payload.get("technical_skills", []) or []:
        matched_signal_ids = {str(signal_id) for signal_id in entry.get("matched_signal_ids") or []}
        if signal_ids and not (signal_ids & matched_signal_ids):
            continue
        for item in entry.get("items") or []:
            normalized = str(item).strip()
            if normalized and normalized not in selected_items:
                selected_items.append(normalized)
            if len(selected_items) == 4:
                return ", ".join(selected_items)
    for entry in step_6_payload.get("technical_skills", []) or []:
        for item in entry.get("items") or []:
            normalized = str(item).strip()
            if normalized and normalized not in selected_items:
                selected_items.append(normalized)
            if len(selected_items) == 4:
                return ", ".join(selected_items)
    return ", ".join(selected_items[:4]) or None


def _role_work_area(step_3_payload: Mapping[str, Any], jd_text: str) -> str | None:
    for priority_key in ("must_have", "core_responsibility", "nice_to_have"):
        signals = step_3_payload.get("signals_by_priority", {}).get(priority_key) or []
        for signal in signals:
            text = _normalize_optional_text(signal.get("signal"))
            if text is None:
                continue
            return _clean_role_signal(text)
    for line in jd_text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return _clean_role_signal(stripped)
    return None


def _clean_role_signal(value: str) -> str:
    cleaned = value.strip().rstrip(".")
    cleaned = re.sub(
        r"^(?:experience with|experience in|experience building|building|build|developing|develop|designing|design|working on|work on)\s+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned[:1].lower() + cleaned[1:] if cleaned else cleaned


def _build_role_targeted_subject(context: RoleTargetedDraftContext) -> str:
    proof_point = context.proof_point or ""
    metric_match = METRIC_RE.search(proof_point)
    if metric_match is not None:
        return f"{context.role_title} at {context.company_name} | Impact: {metric_match.group(0)}"
    return f"{context.role_title} at {context.company_name} | {context.sender.name}"


def _build_role_targeted_why_line(context: RoleTargetedDraftContext) -> str:
    work_signal = _recipient_work_signal(context.recipient_profile)
    title = context.position_title or "your role"
    if context.recipient_type == RECIPIENT_TYPE_RECRUITER:
        if work_signal:
            return f"I'm reaching out to you specifically because your work on {work_signal} looks close to hiring for this area."
        return f"I'm reaching out to you specifically because your role as {title} looks close to hiring for this area."
    if context.recipient_type == RECIPIENT_TYPE_HIRING_MANAGER:
        if work_signal:
            return f"I'm reaching out to you specifically because your work on {work_signal} seems closely tied to this team."
        return f"I'm reaching out to you specifically because your role as {title} seems closely tied to this team."
    if context.recipient_type == RECIPIENT_TYPE_ALUMNI:
        return (
            "I'm reaching out to you specifically because you seemed like the right fellow Sun Devil to ask for a grounded perspective on this work."
        )
    if work_signal:
        return f"I'm reaching out to you specifically because your work on {work_signal} seems close to the problems this role touches."
    return f"I'm reaching out to you specifically because your role as {title} seems close to this work area."


def _recipient_work_signal(recipient_profile: Mapping[str, Any] | None) -> str | None:
    if recipient_profile is None:
        return None
    work_signals = recipient_profile.get("work_signals")
    if isinstance(work_signals, list):
        for signal in work_signals:
            normalized = _normalize_optional_text(signal)
            if normalized is not None:
                return normalized
    about_preview = _normalize_optional_text(
        (recipient_profile.get("about") or {}).get("preview_text")
        if isinstance(recipient_profile.get("about"), Mapping)
        else None
    )
    if about_preview is not None:
        return about_preview
    top_card = recipient_profile.get("top_card")
    if isinstance(top_card, Mapping):
        for key in ("headline", "current_title"):
            normalized = _normalize_optional_text(top_card.get(key))
            if normalized is not None:
                return normalized
    return None


def _impact_summary_line(context: RoleTargetedDraftContext) -> str:
    proof_point = context.proof_point or "credible impact across backend and distributed systems work"
    return proof_point.rstrip(".")


def _experience_summary_line(context: RoleTargetedDraftContext) -> str:
    summary = _normalize_optional_text(context.fit_summary)
    if summary is not None:
        return f"3+ years across {summary}"
    return "3+ years building backend and distributed systems"


def _snippet_stage(sender: SenderIdentity) -> str:
    if sender.education_summary and "ASU" in sender.education_summary:
        return "MS CS at ASU"
    return "Software Engineer"


def _compact_linkedin(value: str | None) -> str:
    if value is None:
        return "LinkedIn available on request"
    return re.sub(r"^https?://", "", value).rstrip("/")


def _signature_lines(sender: SenderIdentity) -> list[str]:
    lines: list[str] = []
    if sender.linkedin_url:
        lines.append(sender.linkedin_url)
    if sender.phone:
        lines.append(sender.phone)
    if sender.email:
        lines.append(sender.email)
    return lines


def _persist_rendered_draft(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    posting_row: Mapping[str, Any],
    contact_row: Mapping[str, Any],
    outreach_message_id: str,
    outreach_mode: str,
    recipient_email: str,
    rendered: RenderedDraft,
    current_time: str,
    resume_attachment_path: str | None,
    use_role_targeted_mirrors: bool,
) -> DraftedOutreachMessage:
    company_name = str(posting_row["company_name"])
    role_title = str(posting_row["role_title"])
    draft_path = paths.outreach_message_draft_path(company_name, role_title, outreach_message_id)
    html_path = paths.outreach_message_html_path(company_name, role_title, outreach_message_id)
    send_result_path = paths.outreach_message_send_result_path(company_name, role_title, outreach_message_id)

    _write_text_file(draft_path, rendered.body_markdown)
    body_html_artifact_path: str | None = None
    if rendered.body_html:
        _write_text_file(html_path, rendered.body_html)
        body_html_artifact_path = str(html_path.resolve())

    timestamps = lifecycle_timestamps(current_time)
    with connection:
        connection.execute(
            """
            INSERT INTO outreach_messages (
              outreach_message_id, contact_id, outreach_mode, recipient_email, message_status,
              job_posting_id, job_posting_contact_id, subject, body_text, body_html,
              thread_id, delivery_tracking_id, sent_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                outreach_message_id,
                contact_row["contact_id"],
                outreach_mode,
                recipient_email,
                MESSAGE_STATUS_GENERATED,
                posting_row["job_posting_id"],
                contact_row["job_posting_contact_id"],
                rendered.subject,
                rendered.body_markdown,
                rendered.body_html,
                None,
                None,
                None,
                timestamps["created_at"],
                timestamps["updated_at"],
            ),
        )

    _register_text_artifact(
        connection,
        paths,
        artifact_type=OUTREACH_DRAFT_ARTIFACT_TYPE,
        artifact_path=draft_path,
        linkage=ArtifactLinkage(
            lead_id=str(posting_row["lead_id"]),
            job_posting_id=str(posting_row["job_posting_id"]),
            contact_id=str(contact_row["contact_id"]),
            outreach_message_id=outreach_message_id,
        ),
        created_at=current_time,
    )
    if rendered.body_html:
        _register_text_artifact(
            connection,
            paths,
            artifact_type=OUTREACH_DRAFT_HTML_ARTIFACT_TYPE,
            artifact_path=html_path,
            linkage=ArtifactLinkage(
                lead_id=str(posting_row["lead_id"]),
                job_posting_id=str(posting_row["job_posting_id"]),
                contact_id=str(contact_row["contact_id"]),
                outreach_message_id=outreach_message_id,
            ),
            created_at=current_time,
        )

    published_send_result = publish_json_artifact(
        connection,
        paths,
        artifact_type=SEND_RESULT_ARTIFACT_TYPE,
        artifact_path=send_result_path,
        producer_component=OUTREACH_COMPONENT,
        result="success",
        linkage=ArtifactLinkage(
            lead_id=str(posting_row["lead_id"]),
            job_posting_id=str(posting_row["job_posting_id"]),
            contact_id=str(contact_row["contact_id"]),
            outreach_message_id=outreach_message_id,
        ),
        payload={
            "outreach_mode": outreach_mode,
            "recipient_email": recipient_email,
            "send_status": MESSAGE_STATUS_GENERATED,
            "sent_at": None,
            "thread_id": None,
            "delivery_tracking_id": None,
            "subject": rendered.subject,
            "body_text_artifact_path": str(draft_path.resolve()),
            "body_html_artifact_path": body_html_artifact_path,
            "resume_attachment_path": resume_attachment_path,
        },
        produced_at=current_time,
    )
    if use_role_targeted_mirrors:
        _write_text_file(paths.outreach_latest_draft_path(company_name, role_title), rendered.body_markdown)
        _write_text_file(
            paths.outreach_latest_send_result_path(company_name, role_title),
            json.dumps(published_send_result.contract, indent=2) + "\n",
        )
    return DraftedOutreachMessage(
        outreach_message_id=outreach_message_id,
        contact_id=str(contact_row["contact_id"]),
        job_posting_id=str(posting_row["job_posting_id"]),
        job_posting_contact_id=str(contact_row["job_posting_contact_id"]),
        outreach_mode=outreach_mode,
        recipient_email=recipient_email,
        message_status=MESSAGE_STATUS_GENERATED,
        subject=rendered.subject,
        body_text=rendered.body_markdown,
        body_html=rendered.body_html,
        body_text_artifact_path=str(draft_path.resolve()),
        send_result_artifact_path=str(send_result_path.resolve()),
        body_html_artifact_path=body_html_artifact_path,
        resume_attachment_path=resume_attachment_path,
    )


def _persist_rendered_general_learning_draft(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    contact_row: Mapping[str, Any],
    outreach_message_id: str,
    recipient_email: str,
    rendered: RenderedDraft,
    current_time: str,
) -> DraftedOutreachMessage:
    company_name = str(contact_row["company_name"] or "unknown-company")
    contact_id = str(contact_row["contact_id"])
    draft_path = paths.general_learning_outreach_draft_path(company_name, contact_id, outreach_message_id)
    html_path = paths.general_learning_outreach_html_path(company_name, contact_id, outreach_message_id)
    send_result_path = paths.general_learning_outreach_send_result_path(company_name, contact_id, outreach_message_id)

    _write_text_file(draft_path, rendered.body_markdown)
    body_html_artifact_path: str | None = None
    if rendered.body_html:
        _write_text_file(html_path, rendered.body_html)
        body_html_artifact_path = str(html_path.resolve())

    timestamps = lifecycle_timestamps(current_time)
    with connection:
        connection.execute(
            """
            INSERT INTO outreach_messages (
              outreach_message_id, contact_id, outreach_mode, recipient_email, message_status,
              job_posting_id, job_posting_contact_id, subject, body_text, body_html,
              thread_id, delivery_tracking_id, sent_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                outreach_message_id,
                contact_id,
                OUTREACH_MODE_GENERAL_LEARNING,
                recipient_email,
                MESSAGE_STATUS_GENERATED,
                None,
                None,
                rendered.subject,
                rendered.body_markdown,
                rendered.body_html,
                None,
                None,
                None,
                timestamps["created_at"],
                timestamps["updated_at"],
            ),
        )

    _register_text_artifact(
        connection,
        paths,
        artifact_type=OUTREACH_DRAFT_ARTIFACT_TYPE,
        artifact_path=draft_path,
        linkage=ArtifactLinkage(
            contact_id=contact_id,
            outreach_message_id=outreach_message_id,
        ),
        created_at=current_time,
    )
    if rendered.body_html:
        _register_text_artifact(
            connection,
            paths,
            artifact_type=OUTREACH_DRAFT_HTML_ARTIFACT_TYPE,
            artifact_path=html_path,
            linkage=ArtifactLinkage(
                contact_id=contact_id,
                outreach_message_id=outreach_message_id,
            ),
            created_at=current_time,
        )
    publish_json_artifact(
        connection,
        paths,
        artifact_type=SEND_RESULT_ARTIFACT_TYPE,
        artifact_path=send_result_path,
        producer_component=OUTREACH_COMPONENT,
        result="success",
        linkage=ArtifactLinkage(
            contact_id=contact_id,
            outreach_message_id=outreach_message_id,
        ),
        payload={
            "outreach_mode": OUTREACH_MODE_GENERAL_LEARNING,
            "recipient_email": recipient_email,
            "send_status": MESSAGE_STATUS_GENERATED,
            "sent_at": None,
            "thread_id": None,
            "delivery_tracking_id": None,
            "subject": rendered.subject,
            "body_text_artifact_path": str(draft_path.resolve()),
            "body_html_artifact_path": body_html_artifact_path,
        },
        produced_at=current_time,
    )
    return DraftedOutreachMessage(
        outreach_message_id=outreach_message_id,
        contact_id=contact_id,
        job_posting_id=None,
        job_posting_contact_id=None,
        outreach_mode=OUTREACH_MODE_GENERAL_LEARNING,
        recipient_email=recipient_email,
        message_status=MESSAGE_STATUS_GENERATED,
        subject=rendered.subject,
        body_text=rendered.body_markdown,
        body_html=rendered.body_html,
        body_text_artifact_path=str(draft_path.resolve()),
        send_result_artifact_path=str(send_result_path.resolve()),
        body_html_artifact_path=body_html_artifact_path,
        resume_attachment_path=None,
    )


def _persist_failed_draft_attempt(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    posting_row: Mapping[str, Any],
    contact_row: Mapping[str, Any],
    outreach_message_id: str,
    outreach_mode: str,
    recipient_email: str,
    current_time: str,
    reason_code: str,
    message: str,
) -> DraftFailure:
    company_name = str(posting_row["company_name"])
    role_title = str(posting_row["role_title"])
    send_result_path = paths.outreach_message_send_result_path(company_name, role_title, outreach_message_id)
    timestamps = lifecycle_timestamps(current_time)
    with connection:
        connection.execute(
            """
            INSERT INTO outreach_messages (
              outreach_message_id, contact_id, outreach_mode, recipient_email, message_status,
              job_posting_id, job_posting_contact_id, subject, body_text, body_html,
              thread_id, delivery_tracking_id, sent_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                outreach_message_id,
                contact_row["contact_id"],
                outreach_mode,
                recipient_email,
                MESSAGE_STATUS_FAILED,
                posting_row["job_posting_id"],
                contact_row["job_posting_contact_id"],
                None,
                None,
                None,
                None,
                None,
                None,
                timestamps["created_at"],
                timestamps["updated_at"],
            ),
        )
    published_send_result = publish_json_artifact(
        connection,
        paths,
        artifact_type=SEND_RESULT_ARTIFACT_TYPE,
        artifact_path=send_result_path,
        producer_component=OUTREACH_COMPONENT,
        result="failed",
        linkage=ArtifactLinkage(
            lead_id=str(posting_row["lead_id"]),
            job_posting_id=str(posting_row["job_posting_id"]),
            contact_id=str(contact_row["contact_id"]),
            outreach_message_id=outreach_message_id,
        ),
        payload={
            "outreach_mode": outreach_mode,
            "recipient_email": recipient_email,
            "send_status": MESSAGE_STATUS_FAILED,
            "sent_at": None,
            "thread_id": None,
            "delivery_tracking_id": None,
            "subject": None,
            "body_text_artifact_path": None,
            "body_html_artifact_path": None,
        },
        produced_at=current_time,
        reason_code=reason_code,
        message=message,
    )
    _write_text_file(
        paths.outreach_latest_send_result_path(company_name, role_title),
        json.dumps(published_send_result.contract, indent=2) + "\n",
    )
    return DraftFailure(
        outreach_message_id=outreach_message_id,
        contact_id=str(contact_row["contact_id"]),
        job_posting_contact_id=str(contact_row["job_posting_contact_id"]),
        reason_code=reason_code,
        message=message,
    )


def _promote_posting_into_outreach_in_progress(
    connection: sqlite3.Connection,
    *,
    posting_row: Mapping[str, Any],
    current_time: str,
) -> None:
    current_status = str(posting_row["posting_status"]).strip()
    if current_status == JOB_POSTING_STATUS_OUTREACH_IN_PROGRESS:
        return
    with connection:
        connection.execute(
            """
            UPDATE job_postings
            SET posting_status = ?, updated_at = ?
            WHERE job_posting_id = ?
            """,
            (
                JOB_POSTING_STATUS_OUTREACH_IN_PROGRESS,
                current_time,
                posting_row["job_posting_id"],
            ),
        )
        _record_state_transition(
            connection,
            object_type="job_posting",
            object_id=str(posting_row["job_posting_id"]),
            stage="posting_status",
            previous_state=current_status,
            new_state=JOB_POSTING_STATUS_OUTREACH_IN_PROGRESS,
            transition_timestamp=current_time,
            transition_reason="The first contact in the ready send set entered drafting.",
            lead_id=str(posting_row["lead_id"]),
            job_posting_id=str(posting_row["job_posting_id"]),
            contact_id=None,
        )


def _promote_contact_into_outreach_in_progress(
    connection: sqlite3.Connection,
    *,
    posting_row: Mapping[str, Any],
    contact_row: Mapping[str, Any],
    current_time: str,
) -> None:
    current_contact_status = str(contact_row["contact_status"]).strip()
    current_link_status = str(contact_row["link_level_status"]).strip()
    with connection:
        if current_contact_status != CONTACT_STATUS_OUTREACH_IN_PROGRESS:
            connection.execute(
                """
                UPDATE contacts
                SET contact_status = ?, updated_at = ?
                WHERE contact_id = ?
                """,
                (
                    CONTACT_STATUS_OUTREACH_IN_PROGRESS,
                    current_time,
                    contact_row["contact_id"],
                ),
            )
            _record_state_transition(
                connection,
                object_type="contact",
                object_id=str(contact_row["contact_id"]),
                stage="contact_status",
                previous_state=current_contact_status,
                new_state=CONTACT_STATUS_OUTREACH_IN_PROGRESS,
                transition_timestamp=current_time,
                transition_reason="Drafting began for this posting-contact pair.",
                lead_id=str(posting_row["lead_id"]),
                job_posting_id=str(posting_row["job_posting_id"]),
                contact_id=str(contact_row["contact_id"]),
            )
        if current_link_status != POSTING_CONTACT_STATUS_OUTREACH_IN_PROGRESS:
            connection.execute(
                """
                UPDATE job_posting_contacts
                SET link_level_status = ?, updated_at = ?
                WHERE job_posting_contact_id = ?
                """,
                (
                    POSTING_CONTACT_STATUS_OUTREACH_IN_PROGRESS,
                    current_time,
                    contact_row["job_posting_contact_id"],
                ),
            )
            _record_state_transition(
                connection,
                object_type="job_posting_contact",
                object_id=str(contact_row["job_posting_contact_id"]),
                stage="link_level_status",
                previous_state=current_link_status,
                new_state=POSTING_CONTACT_STATUS_OUTREACH_IN_PROGRESS,
                transition_timestamp=current_time,
                transition_reason="Drafting began for this posting-contact pair.",
                lead_id=str(posting_row["lead_id"]),
                job_posting_id=str(posting_row["job_posting_id"]),
                contact_id=str(contact_row["contact_id"]),
            )


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
    contact_id: str | None,
) -> None:
    connection.execute(
        """
        INSERT INTO state_transition_events (
          state_transition_event_id, object_type, object_id, stage, previous_state,
          new_state, transition_timestamp, transition_reason, caused_by, lead_id,
          job_posting_id, contact_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            new_canonical_id("state_transition_events"),
            object_type,
            object_id,
            stage,
            previous_state,
            new_state,
            transition_timestamp,
            transition_reason,
            OUTREACH_COMPONENT,
            lead_id,
            job_posting_id,
            contact_id,
        ),
    )


def _register_text_artifact(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    artifact_type: str,
    artifact_path: Path,
    linkage: ArtifactLinkage,
    created_at: str,
) -> None:
    register_artifact_record(
        connection,
        paths,
        artifact_type=artifact_type,
        artifact_path=artifact_path,
        producer_component=OUTREACH_COMPONENT,
        linkage=linkage,
        created_at=created_at,
    )


def _write_text_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _render_markdown_email_html(body_markdown: str) -> str:
    html_blocks: list[str] = []
    paragraph_lines: list[str] = []
    blockquote_lines: list[str] = []

    def flush_paragraph() -> None:
        nonlocal paragraph_lines
        if paragraph_lines:
            html_blocks.append(f"<p>{html.escape(' '.join(paragraph_lines))}</p>")
            paragraph_lines = []

    def flush_blockquote() -> None:
        nonlocal blockquote_lines
        if blockquote_lines:
            html_blocks.append(
                "<blockquote>"
                + "".join(f"<p>{html.escape(line)}</p>" for line in blockquote_lines)
                + "</blockquote>"
            )
            blockquote_lines = []

    for raw_line in body_markdown.splitlines():
        stripped = raw_line.rstrip()
        if not stripped:
            flush_paragraph()
            flush_blockquote()
            continue
        if stripped.startswith("> "):
            flush_paragraph()
            blockquote_lines.append(stripped[2:])
            continue
        flush_blockquote()
        paragraph_lines.append(stripped)
    flush_paragraph()
    flush_blockquote()
    return "<html><body>" + "".join(html_blocks) + "</body></html>\n"


def _read_yaml_file(path: Path) -> Mapping[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, Mapping):
        raise OutreachDraftingError(f"YAML payload must be a mapping: {path}")
    return payload


def _read_json_file(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise OutreachDraftingError(f"JSON payload must be an object: {path}")
    return payload


def _first_name(display_name: str) -> str:
    parts = [part for part in NAME_SPLIT_RE.split(display_name.strip()) if part]
    return parts[0] if parts else display_name
