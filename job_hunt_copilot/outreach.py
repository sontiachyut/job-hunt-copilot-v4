from __future__ import annotations

import base64
import html
import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence
from zoneinfo import ZoneInfo

import yaml

from .artifacts import ArtifactLinkage, publish_json_artifact, register_artifact_record
from .delivery_feedback import MailboxFeedbackObserver, run_immediate_delivery_feedback_poll
from .paths import ProjectPaths
from .records import lifecycle_timestamps, new_canonical_id

OUTREACH_COMPONENT = "email_drafting_sending"
OUTREACH_DRAFT_ARTIFACT_TYPE = "email_draft"
OUTREACH_DRAFT_HTML_ARTIFACT_TYPE = "email_draft_html"
SEND_RESULT_ARTIFACT_TYPE = "send_result"

JOB_POSTING_STATUS_REQUIRES_CONTACTS = "requires_contacts"
JOB_POSTING_STATUS_READY_FOR_OUTREACH = "ready_for_outreach"
JOB_POSTING_STATUS_OUTREACH_IN_PROGRESS = "outreach_in_progress"
JOB_POSTING_STATUS_COMPLETED = "completed"

CONTACT_STATUS_WORKING_EMAIL_FOUND = "working_email_found"
CONTACT_STATUS_OUTREACH_IN_PROGRESS = "outreach_in_progress"
CONTACT_STATUS_SENT = "sent"
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
AUTOMATIC_POSTING_DAILY_SEND_CAP = 3
MIN_INTER_SEND_GAP_MINUTES = 6
MAX_INTER_SEND_GAP_MINUTES = 10
JOB_HUNT_COPILOT_REPO_URL = "https://github.com/sontiachyut/job-hunt-copilot-v4"

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
MESSAGE_STATUS_BLOCKED = "blocked"
MESSAGE_STATUS_FAILED = "failed"
MESSAGE_STATUS_SENT = "sent"

SEND_OUTCOME_SENT = "sent"
SEND_OUTCOME_FAILED = "failed"
SEND_OUTCOME_AMBIGUOUS = "ambiguous"

PROFILE_FIELD_RE = re.compile(r"^- \*\*(?P<label>[^*]+):\*\* (?P<value>.+?)\s*$")
MARKDOWN_HEADING_RE = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<title>.+?)\s*$")
METRIC_RE = re.compile(r"\b(?:\$?\d[\d,.]*\+?%?|\d[\d,.]*\+?(?:\s?(?:TPS|ms|hours?|day|days|hospitals?|users?|microservices?|records(?:/second)?|students?|tests?|bugs?)))\b")
NAME_SPLIT_RE = re.compile(r"\s+")
ROLE_SIGNAL_BOILERPLATE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b\d+\+?\s+years?\b", re.IGNORECASE),
    re.compile(r"\bbachelor", re.IGNORECASE),
    re.compile(r"\bequal opportunity", re.IGNORECASE),
    re.compile(r"\bpay range\b", re.IGNORECASE),
    re.compile(r"\badditional compensation\b", re.IGNORECASE),
    re.compile(r"\bbenefits\b", re.IGNORECASE),
    re.compile(r"\bapply today\b", re.IGNORECASE),
    re.compile(r"\bfind us at\b", re.IGNORECASE),
    re.compile(r"\bfor over \d+ years\b", re.IGNORECASE),
    re.compile(r"\bnationalities\b", re.IGNORECASE),
    re.compile(r"\bdiversity\b", re.IGNORECASE),
    re.compile(r"\bsustainability\b", re.IGNORECASE),
    re.compile(r"\bhybrid work model\b", re.IGNORECASE),
    re.compile(r"\brelocation is not provided\b", re.IGNORECASE),
    re.compile(r"\breside in\b", re.IGNORECASE),
    re.compile(r"\bwho we are\b", re.IGNORECASE),
    re.compile(r"\bthe company\b", re.IGNORECASE),
    re.compile(r"\bour benefits\b", re.IGNORECASE),
    re.compile(r"\bcommitment to diversity\b", re.IGNORECASE),
    re.compile(r"\bjoin our team\b", re.IGNORECASE),
    re.compile(r"\bthis role is ideal for\b", re.IGNORECASE),
    re.compile(r"\beager to learn\b", re.IGNORECASE),
)
ROLE_SIGNAL_NONTECHNICAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^seeking an? .+ to join our team", re.IGNORECASE),
    re.compile(
        r"^contribute to design of new functionality and expand existing functionality$",
        re.IGNORECASE,
    ),
    re.compile(r"^you will help build and drive solutions", re.IGNORECASE),
    re.compile(r"^communicat", re.IGNORECASE),
    re.compile(r"^manage (?:a number of )?projects?", re.IGNORECASE),
    re.compile(r"^learn and become proficient", re.IGNORECASE),
    re.compile(r"^effective communication", re.IGNORECASE),
    re.compile(r"^team player", re.IGNORECASE),
    re.compile(r"^well-rounded", re.IGNORECASE),
    re.compile(r"^strong analytical and problem-solving skills", re.IGNORECASE),
    re.compile(r"^thrives in a fast-paced", re.IGNORECASE),
    re.compile(r"^ability and desire", re.IGNORECASE),
    re.compile(r"^willing to work extended hours", re.IGNORECASE),
    re.compile(r"^passionate about building great software", re.IGNORECASE),
)
ROLE_SIGNAL_TECHNICAL_PRIORITY_PATTERNS: tuple[tuple[re.Pattern[str], int], ...] = (
    (re.compile(r"\b(?:rest apis?|microservices?)\b", re.IGNORECASE), 10),
    (re.compile(r"\b(?:high-throughput|enterprise-scale|payment systems?)\b", re.IGNORECASE), 9),
    (re.compile(r"\b(?:webapi|restful services?|swagger|postman)\b", re.IGNORECASE), 9),
    (re.compile(r"\b(?:web-based client-server|client-server applications?)\b", re.IGNORECASE), 8),
    (re.compile(r"\b(?:distributed|event-driven|backend)\b", re.IGNORECASE), 8),
    (re.compile(r"\b(?:spring boot|jakarta ee)\b", re.IGNORECASE), 7),
    (re.compile(r"\b(?:\.net(?: framework| core)?|asp\.net|c#)\b", re.IGNORECASE), 6),
    (re.compile(r"\b(?:sql server|mongodb|postgresql|mysql|relational databases?)\b", re.IGNORECASE), 6),
    (re.compile(r"\b(?:aws|gcp|azure|cloud|ci/cd|jenkins|circleci|github actions)\b", re.IGNORECASE), 6),
    (re.compile(r"\b(?:docker|kubernetes)\b", re.IGNORECASE), 6),
    (re.compile(r"\b(?:concurrency|stream processing|relational databases?)\b", re.IGNORECASE), 5),
    (re.compile(r"\b(?:java(?:\s*17\+?)?|python|scala|golang|go|c\+\+|c#)\b", re.IGNORECASE), 5),
    (re.compile(r"\b(?:object-oriented design|design patterns?)\b", re.IGNORECASE), 4),
    (re.compile(r"\b(?:security|real-time|scheduling|metadata|documents?|platform|infrastructure)\b", re.IGNORECASE), 4),
)
ROLE_SIGNAL_SOURCE_PRIORITY: dict[str, int] = {
    "role_intent": 1,
    "must_have": 4,
    "core_responsibility": 5,
    "nice_to_have": 2,
    "jd_fallback": 1,
}
ROLE_SIGNAL_LEADING_CASE_EXCEPTIONS: frozenset[str] = frozenset(
    {
        "java",
        "python",
        "scala",
        "golang",
        "go",
        "aws",
        "gcp",
        "azure",
        "spring",
        "jakarta",
        "kubernetes",
        "docker",
    }
)
ROLE_TARGETED_DRAFT_BLOCK_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bwork around identifies\b", re.IGNORECASE),
    re.compile(r"\brole's focus on seeking\b", re.IGNORECASE),
    re.compile(r"\brole's focus on basic understanding of\b", re.IGNORECASE),
    re.compile(r"\brole's focus on (?:contribute|communicat|manage|learn)\b", re.IGNORECASE),
    re.compile(r"\byour role as .+ seems close to\b", re.IGNORECASE),
    re.compile(r"\bteam behind this role\b", re.IGNORECASE),
    re.compile(r"\bwork behind this role\b", re.IGNORECASE),
    re.compile(r"\bstrong fit\b", re.IGNORECASE),
    re.compile(r"\bOne example of that overlap is\b", re.IGNORECASE),
    re.compile(r"\bI came across the\b", re.IGNORECASE),
    re.compile(r"\bThe emphasis on\b", re.IGNORECASE),
    re.compile(r"\bMS in Computer Science at ASU\b", re.IGNORECASE),
    re.compile(r"\bArizona State University\b", re.IGNORECASE),
    re.compile(r"\b(?:which is )?what prompted me to reach out\b", re.IGNORECASE),
)
ROLE_SIGNAL_VERB_PREFIXES = {
    "deliver": "delivering",
    "delivers": "delivering",
    "advise": "advising",
    "advises": "advising",
    "guide": "guiding",
    "guides": "guiding",
    "operate": "operating",
    "operates": "operating",
    "apply": "applying",
    "applies": "applying",
    "drive": "driving",
    "develop": "developing",
    "design": "designing",
    "implement": "implementing",
    "collaborate": "collaborating",
    "ensure": "ensuring",
    "review": "reviewing",
    "evaluate": "evaluating",
    "lead": "leading",
    "build": "building",
    "extract": "extracting",
    "enrich": "enriching",
    "process": "processing",
    "support": "supporting",
    "oversee": "overseeing",
    "manage": "managing",
}


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
    posting_sent_today: int
    remaining_posting_daily_capacity: int
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
            "posting_pacing": {
                "daily_send_cap": AUTOMATIC_POSTING_DAILY_SEND_CAP,
                "posting_sent_today": self.posting_sent_today,
                "remaining_posting_daily_capacity": self.remaining_posting_daily_capacity,
                "global_gap_minutes": self.global_gap_minutes,
                "earliest_allowed_send_at": self.earliest_allowed_send_at,
                "pacing_allowed_now": self.pacing_allowed_now,
                "pacing_block_reason": self.pacing_block_reason,
            },
        }


class OutreachDraftingError(RuntimeError):
    pass


class OutreachSendingError(RuntimeError):
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
class RoleTargetedCompositionPlan:
    opener_paragraph: str
    background_paragraph: str
    copilot_paragraphs: tuple[str, str, str]
    ask_paragraph: str
    snippet_text: str


@dataclass(frozen=True)
class RoleTargetedOpenerInputs:
    company_name: str
    role_title: str
    role_theme: str
    technical_focus: str
    overlap_sentence: str


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


@dataclass(frozen=True)
class OutboundOutreachMessage:
    outreach_message_id: str
    contact_id: str
    job_posting_id: str | None
    job_posting_contact_id: str | None
    outreach_mode: str
    recipient_email: str
    subject: str
    body_text: str
    body_html: str | None
    resume_attachment_path: str | None


@dataclass(frozen=True)
class SendAttemptOutcome:
    outcome: str
    thread_id: str | None = None
    delivery_tracking_id: str | None = None
    sent_at: str | None = None
    reason_code: str | None = None
    message: str | None = None


class OutreachMessageSender(Protocol):
    def send(self, message: OutboundOutreachMessage) -> SendAttemptOutcome:
        raise NotImplementedError


class GmailApiOutreachSender:
    def __init__(
        self,
        paths: ProjectPaths,
        *,
        service_factory: object | None = None,
    ) -> None:
        self._paths = paths
        self._service_factory = service_factory

    def send(self, message: OutboundOutreachMessage) -> SendAttemptOutcome:
        try:
            service = self._build_service()
            mime_message = self._build_mime_message(message)
            raw_payload = base64.urlsafe_b64encode(mime_message.as_bytes()).decode("ascii")
            response = (
                service.users()
                .messages()
                .send(userId="me", body={"raw": raw_payload})
                .execute()
            )
        except FileNotFoundError as exc:
            return SendAttemptOutcome(
                outcome=SEND_OUTCOME_FAILED,
                reason_code="missing_resume_attachment",
                message=str(exc),
            )
        except Exception as exc:
            return SendAttemptOutcome(
                outcome=SEND_OUTCOME_FAILED,
                reason_code="gmail_send_failed",
                message=str(exc),
            )

        delivery_tracking_id = _normalize_optional_text(response.get("id"))
        if delivery_tracking_id is None:
            return SendAttemptOutcome(
                outcome=SEND_OUTCOME_AMBIGUOUS,
                reason_code="gmail_missing_message_id",
                message="Gmail send succeeded without returning a message id.",
            )
        sent_at = _gmail_sent_at_from_response(response)
        return SendAttemptOutcome(
            outcome=SEND_OUTCOME_SENT,
            thread_id=_normalize_optional_text(response.get("threadId")),
            delivery_tracking_id=delivery_tracking_id,
            sent_at=sent_at,
        )

    def _build_service(self) -> Any:
        if self._service_factory is not None:
            return self._service_factory()
        from .gmail_alerts import _build_gmail_service

        return _build_gmail_service(self._paths)

    def _build_mime_message(self, message: OutboundOutreachMessage) -> EmailMessage:
        mime_message = EmailMessage()
        mime_message["To"] = message.recipient_email
        mime_message["Subject"] = message.subject
        mime_message.set_content(message.body_text)
        if message.body_html:
            mime_message.add_alternative(message.body_html, subtype="html")
        if message.resume_attachment_path:
            attachment_path = Path(message.resume_attachment_path)
            attachment_bytes = attachment_path.read_bytes()
            mime_message.add_attachment(
                attachment_bytes,
                maintype="application",
                subtype="pdf",
                filename=attachment_path.name,
            )
        return mime_message


def _gmail_sent_at_from_response(response: Mapping[str, Any]) -> str:
    internal_date = _normalize_optional_text(response.get("internalDate"))
    if internal_date:
        try:
            internal_date_ms = int(internal_date)
        except ValueError:
            internal_date_ms = 0
        if internal_date_ms > 0:
            return (
                datetime.fromtimestamp(internal_date_ms / 1000, tz=UTC)
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z")
            )
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class SentOutreachMessage:
    outreach_message_id: str
    contact_id: str
    job_posting_contact_id: str
    recipient_email: str
    sent_at: str
    thread_id: str | None
    delivery_tracking_id: str | None
    send_result_artifact_path: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "outreach_message_id": self.outreach_message_id,
            "contact_id": self.contact_id,
            "job_posting_contact_id": self.job_posting_contact_id,
            "recipient_email": self.recipient_email,
            "sent_at": self.sent_at,
            "thread_id": self.thread_id,
            "delivery_tracking_id": self.delivery_tracking_id,
            "send_result_artifact_path": self.send_result_artifact_path,
        }


@dataclass(frozen=True)
class SendExecutionIssue:
    outreach_message_id: str
    contact_id: str
    job_posting_contact_id: str
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
class DelayedOutreachMessage:
    outreach_message_id: str
    contact_id: str
    job_posting_contact_id: str
    earliest_allowed_send_at: str
    pacing_block_reason: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "outreach_message_id": self.outreach_message_id,
            "contact_id": self.contact_id,
            "job_posting_contact_id": self.job_posting_contact_id,
            "earliest_allowed_send_at": self.earliest_allowed_send_at,
            "pacing_block_reason": self.pacing_block_reason,
        }


@dataclass(frozen=True)
class RoleTargetedSendExecutionResult:
    job_posting_id: str
    selected_contact_ids: tuple[str, ...]
    sent_messages: tuple[SentOutreachMessage, ...]
    blocked_messages: tuple[SendExecutionIssue, ...]
    failed_messages: tuple[SendExecutionIssue, ...]
    delayed_messages: tuple[DelayedOutreachMessage, ...]
    posting_status_after_execution: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "job_posting_id": self.job_posting_id,
            "selected_contact_ids": list(self.selected_contact_ids),
            "sent_messages": [message.as_dict() for message in self.sent_messages],
            "blocked_messages": [issue.as_dict() for issue in self.blocked_messages],
            "failed_messages": [issue.as_dict() for issue in self.failed_messages],
            "delayed_messages": [message.as_dict() for message in self.delayed_messages],
            "posting_status_after_execution": self.posting_status_after_execution,
        }


@dataclass(frozen=True)
class GeneralLearningSendExecutionResult:
    contact_id: str
    outreach_message_id: str
    drafted_message: DraftedOutreachMessage | None
    message_status_after_execution: str
    send_result_artifact_path: str
    sent_at: str | None
    thread_id: str | None
    delivery_tracking_id: str | None
    reason_code: str | None
    message: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "contact_id": self.contact_id,
            "outreach_message_id": self.outreach_message_id,
            "drafted_message": (
                None if self.drafted_message is None else self.drafted_message.as_dict()
            ),
            "message_status_after_execution": self.message_status_after_execution,
            "send_result_artifact_path": self.send_result_artifact_path,
            "sent_at": self.sent_at,
            "thread_id": self.thread_id,
            "delivery_tracking_id": self.delivery_tracking_id,
            "reason_code": self.reason_code,
            "message": self.message,
        }


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
    posting_sent_today = _count_posting_sends_today(
        connection,
        job_posting_id=str(posting_row["job_posting_id"]),
        current_dt=current_dt,
        local_timezone=resolved_timezone,
    )
    remaining_posting_daily_capacity = max(
        0,
        AUTOMATIC_POSTING_DAILY_SEND_CAP - posting_sent_today,
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
        job_posting_id=str(posting_row["job_posting_id"]),
        posting_sent_today=posting_sent_today,
        remaining_posting_daily_capacity=remaining_posting_daily_capacity,
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
        posting_sent_today=posting_sent_today,
        remaining_posting_daily_capacity=remaining_posting_daily_capacity,
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
          WHERE sent_at IS NOT NULL
             OR message_status = ?
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
        (MESSAGE_STATUS_SENT, job_posting_id),
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


def _count_posting_sends_today(
    connection: sqlite3.Connection,
    *,
    job_posting_id: str,
    current_dt: datetime,
    local_timezone: tzinfo,
) -> int:
    rows = connection.execute(
        """
        SELECT om.sent_at
        FROM outreach_messages om
        WHERE om.sent_at IS NOT NULL
          AND TRIM(om.sent_at) <> ''
          AND om.job_posting_id = ?
        """
        ,
        (job_posting_id,),
    ).fetchall()
    current_local_day = current_dt.astimezone(local_timezone).date()
    send_count = 0
    for row in rows:
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
    job_posting_id: str,
    posting_sent_today: int,
    remaining_posting_daily_capacity: int,
    global_gap_minutes: int,
) -> dict[str, Any]:
    constraint_times = [current_dt]
    pacing_block_reason: str | None = None

    if remaining_posting_daily_capacity <= 0 or posting_sent_today >= AUTOMATIC_POSTING_DAILY_SEND_CAP:
        next_day = current_dt.astimezone(local_timezone).date() + timedelta(days=1)
        posting_window_start = datetime.combine(next_day, time.min, tzinfo=local_timezone).astimezone(UTC)
        constraint_times.append(posting_window_start)
        pacing_block_reason = "posting_daily_cap"

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
        "job_posting_id": job_posting_id,
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
        plan = _compose_role_targeted_composition_plan(context)
        body_lines = [
            f"Hi {_first_name(context.display_name)},",
            "",
            plan.opener_paragraph,
            "",
            plan.background_paragraph,
            "",
            *plan.copilot_paragraphs,
            "",
            plan.ask_paragraph,
        ]
        include_snippet = True
        if include_snippet:
            body_lines.extend(
                [
                    "",
                    "I've included a short snippet below that you can paste into an IM/Email:",
                    "[snippet]",
                    plan.snippet_text,
                    "[/snippet]",
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
                f"{role_hint.lower()}. I have been gravitating toward backend, distributed-systems, and "
                "AI-adjacent engineering work."
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
            work_area=_select_role_work_area(
                tailoring_inputs["step_3_payload"],
                tailoring_inputs["jd_text"],
                step_4_payload=tailoring_inputs["step_4_payload"],
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


def execute_general_learning_outreach(
    connection: sqlite3.Connection,
    *,
    project_root: Path | str,
    contact_id: str,
    current_time: str,
    sender: OutreachMessageSender,
    renderer: OutreachDraftRenderer | None = None,
    feedback_observer: MailboxFeedbackObserver | None = None,
) -> GeneralLearningSendExecutionResult:
    paths = ProjectPaths.from_root(project_root)
    contact_row = _load_general_learning_contact_row(connection, contact_id=contact_id)
    drafted_message: DraftedOutreachMessage | None = None

    active_message = _load_latest_general_learning_message_row(
        connection,
        contact_id=contact_id,
    )
    if active_message is None:
        draft_result = generate_general_learning_draft(
            connection,
            project_root=project_root,
            contact_id=contact_id,
            current_time=current_time,
            renderer=renderer,
        )
        drafted_message = draft_result.drafted_message
        active_message = _load_latest_general_learning_message_row(
            connection,
            contact_id=contact_id,
        )

    if active_message is None:  # pragma: no cover - defensive invariant
        raise OutreachSendingError(
            f"General-learning outreach failed to materialize a message for contact `{contact_id}`."
        )
    if str(active_message["message_status"]) != MESSAGE_STATUS_GENERATED:
        raise OutreachSendingError(
            "General-learning automatic sending requires the latest message to be "
            f"`{MESSAGE_STATUS_GENERATED}`, but `{active_message['outreach_message_id']}` is "
            f"`{active_message['message_status']}`."
        )

    guardrail_block = _evaluate_general_learning_send_guardrails(
        connection,
        paths,
        contact_row=contact_row,
        active_message=active_message,
    )
    if guardrail_block is not None:
        return _persist_blocked_general_learning_send(
            connection,
            paths,
            contact_row=contact_row,
            active_message=active_message,
            current_time=current_time,
            drafted_message=drafted_message,
            reason_code=guardrail_block["reason_code"],
            message=guardrail_block["message"],
        )

    outbound = OutboundOutreachMessage(
        outreach_message_id=str(active_message["outreach_message_id"]),
        contact_id=str(contact_row["contact_id"]),
        job_posting_id=None,
        job_posting_contact_id=None,
        outreach_mode=OUTREACH_MODE_GENERAL_LEARNING,
        recipient_email=str(active_message["recipient_email"]),
        subject=str(active_message["subject"]),
        body_text=str(active_message["body_text"]),
        body_html=_normalize_optional_text(active_message["body_html"]),
        resume_attachment_path=None,
    )
    normalized_outcome = _normalize_send_attempt_outcome(sender.send(outbound))

    if normalized_outcome.outcome == SEND_OUTCOME_SENT:
        result = _persist_successful_general_learning_send(
            connection,
            paths,
            contact_row=contact_row,
            active_message=active_message,
            current_time=current_time,
            drafted_message=drafted_message,
            sent_at=normalized_outcome.sent_at or current_time,
            thread_id=normalized_outcome.thread_id,
            delivery_tracking_id=normalized_outcome.delivery_tracking_id,
        )
        run_immediate_delivery_feedback_poll(
            connection,
            project_root=project_root,
            current_time=current_time,
            outreach_message_ids=[result.outreach_message_id],
            observer=feedback_observer,
        )
        return result

    if normalized_outcome.outcome == SEND_OUTCOME_AMBIGUOUS:
        return _persist_blocked_general_learning_send(
            connection,
            paths,
            contact_row=contact_row,
            active_message=active_message,
            current_time=current_time,
            drafted_message=drafted_message,
            reason_code=normalized_outcome.reason_code or "ambiguous_send_outcome",
            message=normalized_outcome.message
            or "The general-learning send outcome could not be reconciled safely.",
        )

    return _persist_failed_general_learning_send_attempt(
        connection,
        paths,
        contact_row=contact_row,
        active_message=active_message,
        current_time=current_time,
        drafted_message=drafted_message,
        reason_code=normalized_outcome.reason_code or "send_provider_failed",
        message=normalized_outcome.message
        or "The outbound send provider returned a failure.",
    )


@dataclass(frozen=True)
class _ActiveWaveMessage:
    contact_id: str
    job_posting_contact_id: str
    recipient_type: str
    display_name: str
    recipient_email: str | None
    contact_status: str
    link_level_status: str
    link_created_at: str
    outreach_message_id: str
    message_status: str
    subject: str | None
    body_text: str | None
    body_html: str | None
    thread_id: str | None
    delivery_tracking_id: str | None
    sent_at: str | None
    message_created_at: str
    message_updated_at: str


def execute_role_targeted_send_set(
    connection: sqlite3.Connection,
    *,
    project_root: Path | str,
    job_posting_id: str,
    current_time: str,
    sender: OutreachMessageSender,
    local_timezone: tzinfo | str | None = None,
    feedback_observer: MailboxFeedbackObserver | None = None,
) -> RoleTargetedSendExecutionResult:
    paths = ProjectPaths.from_root(project_root)
    posting_row = _load_role_targeted_send_posting_row(connection, job_posting_id=job_posting_id)
    if posting_row["posting_status"] not in {
        JOB_POSTING_STATUS_READY_FOR_OUTREACH,
        JOB_POSTING_STATUS_OUTREACH_IN_PROGRESS,
        JOB_POSTING_STATUS_COMPLETED,
    }:
        raise OutreachSendingError(
            f"Job posting `{job_posting_id}` is `{posting_row['posting_status']}`; sending starts only from `ready_for_outreach`, `outreach_in_progress`, or `completed`."
        )

    active_wave = _load_active_role_targeted_wave(connection, job_posting_id=job_posting_id)
    if not active_wave:
        raise OutreachSendingError(
            f"Job posting `{job_posting_id}` does not have an active drafted outreach wave."
        )
    _validate_active_role_targeted_wave(active_wave, job_posting_id=job_posting_id)

    current_dt = _parse_iso_datetime(current_time)
    resolved_timezone = _resolve_local_timezone(current_dt, local_timezone)
    wave_contact_ids = [message.contact_id for message in active_wave]
    global_gap_minutes = _determine_global_gap_minutes(
        job_posting_id=job_posting_id,
        selected_contact_ids=wave_contact_ids,
        current_dt=current_dt,
        local_timezone=resolved_timezone,
    )

    sent_messages: list[SentOutreachMessage] = []
    blocked_messages: list[SendExecutionIssue] = []
    failed_messages: list[SendExecutionIssue] = []
    delayed_messages: list[DelayedOutreachMessage] = []

    for index, active_message in enumerate(active_wave):
        if active_message.message_status == MESSAGE_STATUS_SENT:
            continue
        if active_message.message_status in {MESSAGE_STATUS_FAILED, MESSAGE_STATUS_BLOCKED}:
            continue
        if active_message.message_status != MESSAGE_STATUS_GENERATED:
            issue = _persist_blocked_send(
                connection,
                paths,
                posting_row=posting_row,
                active_message=active_message,
                current_time=current_time,
                reason_code="unexpected_message_status",
                message=(
                    f"Automatic sending only supports `{MESSAGE_STATUS_GENERATED}` messages, "
                    f"but `{active_message.outreach_message_id}` is `{active_message.message_status}`."
                ),
                exhaust_link=False,
            )
            blocked_messages.append(issue)
            continue

        guardrail_block = _evaluate_send_guardrails(
            connection,
            paths,
            posting_row=posting_row,
            active_message=active_message,
        )
        if guardrail_block is not None:
            issue = _persist_blocked_send(
                connection,
                paths,
                posting_row=posting_row,
                active_message=active_message,
                current_time=current_time,
                reason_code=guardrail_block["reason_code"],
                message=guardrail_block["message"],
                exhaust_link=bool(guardrail_block["exhaust_link"]),
            )
            blocked_messages.append(issue)
            if bool(guardrail_block["stop_wave"]):
                break
            continue

        pacing = _build_role_targeted_send_pacing_plan(
            connection,
            posting_row=posting_row,
            current_dt=current_dt,
            local_timezone=resolved_timezone,
            global_gap_minutes=global_gap_minutes,
        )
        if not pacing["pacing_allowed_now"]:
            delayed_messages.extend(
                _build_delayed_messages(
                    active_wave[index:],
                    earliest_allowed_send_at=str(pacing["earliest_allowed_send_at"]),
                    pacing_block_reason=_normalize_optional_text(pacing["pacing_block_reason"]),
                )
            )
            break

        outbound = OutboundOutreachMessage(
            outreach_message_id=active_message.outreach_message_id,
            contact_id=active_message.contact_id,
            job_posting_id=str(posting_row["job_posting_id"]),
            job_posting_contact_id=active_message.job_posting_contact_id,
            outreach_mode=OUTREACH_MODE_ROLE_TARGETED,
            recipient_email=str(active_message.recipient_email),
            subject=str(active_message.subject),
            body_text=str(active_message.body_text),
            body_html=active_message.body_html,
            resume_attachment_path=_load_resume_attachment_path(
                paths,
                company_name=str(posting_row["company_name"]),
                role_title=str(posting_row["role_title"]),
                outreach_message_id=active_message.outreach_message_id,
            ),
        )
        outcome = sender.send(outbound)
        normalized_outcome = _normalize_send_attempt_outcome(outcome)

        if normalized_outcome.outcome == SEND_OUTCOME_SENT:
            sent_messages.append(
                _persist_successful_send(
                    connection,
                    paths,
                    posting_row=posting_row,
                    active_message=active_message,
                    current_time=current_time,
                    sent_at=normalized_outcome.sent_at or current_time,
                    thread_id=normalized_outcome.thread_id,
                    delivery_tracking_id=normalized_outcome.delivery_tracking_id,
                )
            )
            if index + 1 < len(active_wave):
                post_send_pacing = _build_role_targeted_send_pacing_plan(
                    connection,
                    posting_row=posting_row,
                    current_dt=current_dt,
                    local_timezone=resolved_timezone,
                    global_gap_minutes=global_gap_minutes,
                )
                delayed_messages.extend(
                    _build_delayed_messages(
                        active_wave[index + 1 :],
                        earliest_allowed_send_at=str(post_send_pacing["earliest_allowed_send_at"]),
                        pacing_block_reason=_normalize_optional_text(post_send_pacing["pacing_block_reason"]),
                    )
                )
            break

        if normalized_outcome.outcome == SEND_OUTCOME_AMBIGUOUS:
            blocked_messages.append(
                _persist_blocked_send(
                    connection,
                    paths,
                    posting_row=posting_row,
                    active_message=active_message,
                    current_time=current_time,
                    reason_code=normalized_outcome.reason_code or "ambiguous_send_outcome",
                    message=normalized_outcome.message or "The send outcome could not be reconciled safely.",
                    exhaust_link=True,
                )
            )
            break

        failed_messages.append(
            _persist_failed_send_attempt(
                connection,
                paths,
                posting_row=posting_row,
                active_message=active_message,
                current_time=current_time,
                reason_code=normalized_outcome.reason_code or "send_provider_failed",
                message=normalized_outcome.message or "The outbound send provider returned a failure.",
            )
        )

    posting_status_after_execution = _load_current_posting_status(
        connection,
        job_posting_id=job_posting_id,
    )
    if sent_messages:
        run_immediate_delivery_feedback_poll(
            connection,
            project_root=project_root,
            current_time=current_time,
            outreach_message_ids=[message.outreach_message_id for message in sent_messages],
            observer=feedback_observer,
        )
    return RoleTargetedSendExecutionResult(
        job_posting_id=job_posting_id,
        selected_contact_ids=tuple(message.contact_id for message in active_wave),
        sent_messages=tuple(sent_messages),
        blocked_messages=tuple(blocked_messages),
        failed_messages=tuple(failed_messages),
        delayed_messages=tuple(delayed_messages),
        posting_status_after_execution=posting_status_after_execution,
    )


def _load_role_targeted_send_posting_row(
    connection: sqlite3.Connection,
    *,
    job_posting_id: str,
) -> sqlite3.Row:
    row = connection.execute(
        """
        SELECT job_posting_id, lead_id, company_name, role_title, posting_status
        FROM job_postings
        WHERE job_posting_id = ?
        """,
        (job_posting_id,),
    ).fetchone()
    if row is None:
        raise OutreachSendingError(f"Job posting `{job_posting_id}` was not found.")
    return row


def _load_active_role_targeted_wave(
    connection: sqlite3.Connection,
    *,
    job_posting_id: str,
) -> list[_ActiveWaveMessage]:
    rows = connection.execute(
        """
        SELECT jpc.job_posting_contact_id, jpc.contact_id, jpc.recipient_type, jpc.link_level_status,
               jpc.created_at AS link_created_at, c.display_name, c.current_working_email,
               c.contact_status, om.outreach_message_id, om.message_status, om.subject,
               om.body_text, om.body_html, om.thread_id, om.delivery_tracking_id, om.sent_at,
               om.created_at AS message_created_at, om.updated_at AS message_updated_at
        FROM job_posting_contacts jpc
        JOIN contacts c
          ON c.contact_id = jpc.contact_id
        LEFT JOIN outreach_messages om
          ON om.outreach_message_id = (
            SELECT om2.outreach_message_id
            FROM outreach_messages om2
            WHERE om2.job_posting_id = jpc.job_posting_id
              AND om2.contact_id = jpc.contact_id
            ORDER BY om2.created_at DESC, om2.outreach_message_id DESC
            LIMIT 1
          )
        WHERE jpc.job_posting_id = ?
          AND jpc.link_level_status IN (?, ?, ?)
          AND EXISTS (
            SELECT 1
            FROM outreach_messages om3
            WHERE om3.job_posting_id = jpc.job_posting_id
              AND om3.contact_id = jpc.contact_id
          )
        ORDER BY jpc.created_at ASC, jpc.job_posting_contact_id ASC
        """,
        (
            job_posting_id,
            POSTING_CONTACT_STATUS_OUTREACH_IN_PROGRESS,
            POSTING_CONTACT_STATUS_OUTREACH_DONE,
            POSTING_CONTACT_STATUS_EXHAUSTED,
        ),
    ).fetchall()
    wave = [
        _ActiveWaveMessage(
            contact_id=str(row["contact_id"]),
            job_posting_contact_id=str(row["job_posting_contact_id"]),
            recipient_type=str(row["recipient_type"]),
            display_name=str(row["display_name"]),
            recipient_email=_normalize_optional_text(row["current_working_email"]),
            contact_status=str(row["contact_status"]),
            link_level_status=str(row["link_level_status"]),
            link_created_at=str(row["link_created_at"]),
            outreach_message_id=str(row["outreach_message_id"]) if row["outreach_message_id"] else "",
            message_status=str(row["message_status"]) if row["message_status"] else "",
            subject=_normalize_optional_text(row["subject"]),
            body_text=_normalize_optional_text(row["body_text"]),
            body_html=_normalize_optional_text(row["body_html"]),
            thread_id=_normalize_optional_text(row["thread_id"]),
            delivery_tracking_id=_normalize_optional_text(row["delivery_tracking_id"]),
            sent_at=_normalize_optional_text(row["sent_at"]),
            message_created_at=str(row["message_created_at"]) if row["message_created_at"] else "",
            message_updated_at=str(row["message_updated_at"]) if row["message_updated_at"] else "",
        )
        for row in rows
    ]
    return sorted(wave, key=_active_wave_sort_key)


def _validate_active_role_targeted_wave(
    active_wave: Sequence[_ActiveWaveMessage],
    *,
    job_posting_id: str,
) -> None:
    missing_messages = [
        message.job_posting_contact_id
        for message in active_wave
        if not message.outreach_message_id or not message.message_status
    ]
    if missing_messages:
        missing_label = ", ".join(missing_messages)
        raise OutreachSendingError(
            f"Job posting `{job_posting_id}` has active outreach contacts without persisted message rows: {missing_label}."
        )


def _active_wave_sort_key(message: _ActiveWaveMessage) -> tuple[int, int, str, str]:
    return (
        _selection_state_rank(_recipient_type_send_slot(message.recipient_type)),
        _fallback_type_rank(message.recipient_type),
        message.link_created_at,
        message.contact_id,
    )


def _recipient_type_send_slot(recipient_type: str) -> str:
    if recipient_type == RECIPIENT_TYPE_RECRUITER:
        return _CANDIDATE_STATE_READY
    if recipient_type in {RECIPIENT_TYPE_HIRING_MANAGER, RECIPIENT_TYPE_FOUNDER}:
        return _CANDIDATE_STATE_NEEDS_EMAIL
    if recipient_type == RECIPIENT_TYPE_ENGINEER:
        return _CANDIDATE_STATE_REPEAT_REVIEW
    return _CANDIDATE_STATE_UNAVAILABLE


def _build_role_targeted_send_pacing_plan(
    connection: sqlite3.Connection,
    *,
    posting_row: Mapping[str, Any],
    current_dt: datetime,
    local_timezone: tzinfo,
    global_gap_minutes: int,
) -> dict[str, Any]:
    posting_sent_today = _count_posting_sends_today(
        connection,
        job_posting_id=str(posting_row["job_posting_id"]),
        current_dt=current_dt,
        local_timezone=local_timezone,
    )
    remaining_posting_daily_capacity = max(
        0,
        AUTOMATIC_POSTING_DAILY_SEND_CAP - posting_sent_today,
    )
    return _build_pacing_plan(
        connection,
        current_dt=current_dt,
        local_timezone=local_timezone,
        job_posting_id=str(posting_row["job_posting_id"]),
        posting_sent_today=posting_sent_today,
        remaining_posting_daily_capacity=remaining_posting_daily_capacity,
        global_gap_minutes=global_gap_minutes,
    )


def _build_delayed_messages(
    messages: Sequence[_ActiveWaveMessage],
    *,
    earliest_allowed_send_at: str,
    pacing_block_reason: str | None,
) -> list[DelayedOutreachMessage]:
    delayed: list[DelayedOutreachMessage] = []
    for message in messages:
        if message.message_status != MESSAGE_STATUS_GENERATED:
            continue
        delayed.append(
            DelayedOutreachMessage(
                outreach_message_id=message.outreach_message_id,
                contact_id=message.contact_id,
                job_posting_contact_id=message.job_posting_contact_id,
                earliest_allowed_send_at=earliest_allowed_send_at,
                pacing_block_reason=pacing_block_reason,
            )
        )
    return delayed


def _evaluate_send_guardrails(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    posting_row: Mapping[str, Any],
    active_message: _ActiveWaveMessage,
) -> dict[str, Any] | None:
    if active_message.recipient_email is None:
        return {
            "reason_code": "missing_recipient_email",
            "message": "Automatic sending requires a usable recipient email.",
            "exhaust_link": False,
            "stop_wave": False,
        }
    if active_message.subject is None or active_message.body_text is None:
        return {
            "reason_code": "missing_draft_content",
            "message": "Automatic sending requires persisted draft subject and body content.",
            "exhaust_link": False,
            "stop_wave": False,
        }

    draft_path = paths.outreach_message_draft_path(
        str(posting_row["company_name"]),
        str(posting_row["role_title"]),
        active_message.outreach_message_id,
    )
    send_result_path = paths.outreach_message_send_result_path(
        str(posting_row["company_name"]),
        str(posting_row["role_title"]),
        active_message.outreach_message_id,
    )
    if not draft_path.exists():
        return {
            "reason_code": "missing_draft_artifact",
            "message": f"Draft artifact is missing for `{active_message.outreach_message_id}`.",
            "exhaust_link": False,
            "stop_wave": False,
        }
    if not send_result_path.exists():
        return {
            "reason_code": "missing_send_result_artifact",
            "message": f"send_result.json is missing for `{active_message.outreach_message_id}`.",
            "exhaust_link": False,
            "stop_wave": False,
        }

    try:
        send_result_contract = _read_json_file(send_result_path)
    except Exception:
        return {
            "reason_code": "invalid_send_result_artifact",
            "message": f"send_result.json is unreadable for `{active_message.outreach_message_id}`.",
            "exhaust_link": False,
            "stop_wave": False,
        }
    send_status = _normalize_optional_text(send_result_contract.get("send_status"))
    if send_status in {MESSAGE_STATUS_SENT, MESSAGE_STATUS_BLOCKED}:
        return {
            "reason_code": "ambiguous_send_state",
            "message": "Stored send_result.json already reflects a non-generated send state, so automatic resend is unsafe.",
            "exhaust_link": True,
            "stop_wave": True,
        }
    if active_message.sent_at or active_message.thread_id or active_message.delivery_tracking_id:
        return {
            "reason_code": "ambiguous_send_state",
            "message": "Message delivery metadata already exists without a clean completed send state, so automatic resend is unsafe.",
            "exhaust_link": True,
            "stop_wave": True,
        }

    prior_sent_count = int(
        connection.execute(
            """
            SELECT COUNT(*)
            FROM outreach_messages
            WHERE contact_id = ?
              AND outreach_message_id <> ?
              AND (
                sent_at IS NOT NULL
                OR message_status = ?
              )
            """,
            (
                active_message.contact_id,
                active_message.outreach_message_id,
                MESSAGE_STATUS_SENT,
            ),
        ).fetchone()[0]
        or 0
    )
    if prior_sent_count > 0:
        return {
            "reason_code": "repeat_outreach_review_required",
            "message": "Prior outreach history exists for this contact, so automatic repeat sending is blocked pending review.",
            "exhaust_link": True,
            "stop_wave": False,
        }

    other_active_message_count = int(
        connection.execute(
            """
            SELECT COUNT(*)
            FROM outreach_messages
            WHERE contact_id = ?
              AND outreach_message_id <> ?
              AND message_status IN (?, ?)
            """,
            (
                active_message.contact_id,
                active_message.outreach_message_id,
                MESSAGE_STATUS_GENERATED,
                MESSAGE_STATUS_BLOCKED,
            ),
        ).fetchone()[0]
        or 0
    )
    if other_active_message_count > 0:
        return {
            "reason_code": "ambiguous_send_state",
            "message": "Multiple active outreach messages exist for this contact, so automatic resend is unsafe.",
            "exhaust_link": True,
            "stop_wave": True,
        }
    return None


def _normalize_send_attempt_outcome(outcome: SendAttemptOutcome) -> SendAttemptOutcome:
    if outcome.outcome not in {
        SEND_OUTCOME_SENT,
        SEND_OUTCOME_FAILED,
        SEND_OUTCOME_AMBIGUOUS,
    }:
        raise OutreachSendingError(
            f"Unsupported send outcome `{outcome.outcome}` returned by the message sender."
        )
    return outcome


def _load_resume_attachment_path(
    paths: ProjectPaths,
    *,
    company_name: str,
    role_title: str,
    outreach_message_id: str,
) -> str | None:
    send_result_path = paths.outreach_message_send_result_path(company_name, role_title, outreach_message_id)
    if not send_result_path.exists():
        return None
    payload = _read_json_file(send_result_path)
    return _normalize_optional_text(payload.get("resume_attachment_path"))


def _persist_successful_send(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    posting_row: Mapping[str, Any],
    active_message: _ActiveWaveMessage,
    current_time: str,
    sent_at: str,
    thread_id: str | None,
    delivery_tracking_id: str | None,
) -> SentOutreachMessage:
    normalized_sent_at = _isoformat_utc(_parse_iso_datetime(sent_at))
    with connection:
        connection.execute(
            """
            UPDATE outreach_messages
            SET message_status = ?, thread_id = ?, delivery_tracking_id = ?, sent_at = ?, updated_at = ?
            WHERE outreach_message_id = ?
            """,
            (
                MESSAGE_STATUS_SENT,
                thread_id,
                delivery_tracking_id,
                normalized_sent_at,
                current_time,
                active_message.outreach_message_id,
            ),
        )
    _transition_contact_to_sent(
        connection,
        posting_row=posting_row,
        active_message=active_message,
        current_time=current_time,
    )
    send_result_artifact_path = _publish_role_targeted_send_result(
        connection,
        paths,
        posting_row=posting_row,
        active_message=active_message,
        current_time=current_time,
        result="success",
        send_status=MESSAGE_STATUS_SENT,
        sent_at=normalized_sent_at,
        thread_id=thread_id,
        delivery_tracking_id=delivery_tracking_id,
        reason_code=None,
        message=None,
    )
    _complete_posting_if_wave_finished(
        connection,
        posting_row=posting_row,
        current_time=current_time,
    )
    return SentOutreachMessage(
        outreach_message_id=active_message.outreach_message_id,
        contact_id=active_message.contact_id,
        job_posting_contact_id=active_message.job_posting_contact_id,
        recipient_email=str(active_message.recipient_email),
        sent_at=normalized_sent_at,
        thread_id=thread_id,
        delivery_tracking_id=delivery_tracking_id,
        send_result_artifact_path=send_result_artifact_path,
    )


def _persist_blocked_send(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    posting_row: Mapping[str, Any],
    active_message: _ActiveWaveMessage,
    current_time: str,
    reason_code: str,
    message: str,
    exhaust_link: bool,
) -> SendExecutionIssue:
    with connection:
        connection.execute(
            """
            UPDATE outreach_messages
            SET message_status = ?, updated_at = ?
            WHERE outreach_message_id = ?
            """,
            (
                MESSAGE_STATUS_BLOCKED,
                current_time,
                active_message.outreach_message_id,
            ),
        )
    if exhaust_link:
        _mark_posting_contact_exhausted_for_review(
            connection,
            posting_row=posting_row,
            active_message=active_message,
            current_time=current_time,
            transition_reason=message,
        )
    _publish_role_targeted_send_result(
        connection,
        paths,
        posting_row=posting_row,
        active_message=active_message,
        current_time=current_time,
        result="blocked",
        send_status=MESSAGE_STATUS_BLOCKED,
        sent_at=None,
        thread_id=active_message.thread_id,
        delivery_tracking_id=active_message.delivery_tracking_id,
        reason_code=reason_code,
        message=message,
    )
    _complete_posting_if_wave_finished(
        connection,
        posting_row=posting_row,
        current_time=current_time,
    )
    return SendExecutionIssue(
        outreach_message_id=active_message.outreach_message_id,
        contact_id=active_message.contact_id,
        job_posting_contact_id=active_message.job_posting_contact_id,
        reason_code=reason_code,
        message=message,
    )


def _persist_failed_send_attempt(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    posting_row: Mapping[str, Any],
    active_message: _ActiveWaveMessage,
    current_time: str,
    reason_code: str,
    message: str,
) -> SendExecutionIssue:
    with connection:
        connection.execute(
            """
            UPDATE outreach_messages
            SET message_status = ?, updated_at = ?
            WHERE outreach_message_id = ?
            """,
            (
                MESSAGE_STATUS_FAILED,
                current_time,
                active_message.outreach_message_id,
            ),
        )
    _publish_role_targeted_send_result(
        connection,
        paths,
        posting_row=posting_row,
        active_message=active_message,
        current_time=current_time,
        result="failed",
        send_status=MESSAGE_STATUS_FAILED,
        sent_at=None,
        thread_id=None,
        delivery_tracking_id=None,
        reason_code=reason_code,
        message=message,
    )
    return SendExecutionIssue(
        outreach_message_id=active_message.outreach_message_id,
        contact_id=active_message.contact_id,
        job_posting_contact_id=active_message.job_posting_contact_id,
        reason_code=reason_code,
        message=message,
    )


def _publish_role_targeted_send_result(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    posting_row: Mapping[str, Any],
    active_message: _ActiveWaveMessage,
    current_time: str,
    result: str,
    send_status: str,
    sent_at: str | None,
    thread_id: str | None,
    delivery_tracking_id: str | None,
    reason_code: str | None,
    message: str | None,
) -> str:
    company_name = str(posting_row["company_name"])
    role_title = str(posting_row["role_title"])
    draft_path = paths.outreach_message_draft_path(company_name, role_title, active_message.outreach_message_id)
    html_path = paths.outreach_message_html_path(company_name, role_title, active_message.outreach_message_id)
    send_result_path = paths.outreach_message_send_result_path(
        company_name,
        role_title,
        active_message.outreach_message_id,
    )
    published = publish_json_artifact(
        connection,
        paths,
        artifact_type=SEND_RESULT_ARTIFACT_TYPE,
        artifact_path=send_result_path,
        producer_component=OUTREACH_COMPONENT,
        result=result,
        linkage=ArtifactLinkage(
            lead_id=str(posting_row["lead_id"]),
            job_posting_id=str(posting_row["job_posting_id"]),
            contact_id=active_message.contact_id,
            outreach_message_id=active_message.outreach_message_id,
        ),
        payload={
            "outreach_mode": OUTREACH_MODE_ROLE_TARGETED,
            "recipient_email": active_message.recipient_email,
            "send_status": send_status,
            "sent_at": sent_at,
            "thread_id": thread_id,
            "delivery_tracking_id": delivery_tracking_id,
            "subject": active_message.subject,
            "body_text_artifact_path": str(draft_path.resolve()) if draft_path.exists() else None,
            "body_html_artifact_path": str(html_path.resolve()) if html_path.exists() else None,
            "resume_attachment_path": _load_resume_attachment_path(
                paths,
                company_name=company_name,
                role_title=role_title,
                outreach_message_id=active_message.outreach_message_id,
            ),
        },
        produced_at=current_time,
        reason_code=reason_code,
        message=message,
    )
    _write_text_file(
        paths.outreach_latest_send_result_path(company_name, role_title),
        json.dumps(published.contract, indent=2) + "\n",
    )
    return str(send_result_path.resolve())


def _transition_contact_to_sent(
    connection: sqlite3.Connection,
    *,
    posting_row: Mapping[str, Any],
    active_message: _ActiveWaveMessage,
    current_time: str,
) -> None:
    with connection:
        if active_message.contact_status != CONTACT_STATUS_SENT:
            connection.execute(
                """
                UPDATE contacts
                SET contact_status = ?, updated_at = ?
                WHERE contact_id = ?
                """,
                (
                    CONTACT_STATUS_SENT,
                    current_time,
                    active_message.contact_id,
                ),
            )
            _record_state_transition(
                connection,
                object_type="contact",
                object_id=active_message.contact_id,
                stage="contact_status",
                previous_state=active_message.contact_status,
                new_state=CONTACT_STATUS_SENT,
                transition_timestamp=current_time,
                transition_reason="An outreach message was sent for this contact.",
                lead_id=str(posting_row["lead_id"]),
                job_posting_id=str(posting_row["job_posting_id"]),
                contact_id=active_message.contact_id,
            )
        if active_message.link_level_status != POSTING_CONTACT_STATUS_OUTREACH_DONE:
            connection.execute(
                """
                UPDATE job_posting_contacts
                SET link_level_status = ?, updated_at = ?
                WHERE job_posting_contact_id = ?
                """,
                (
                    POSTING_CONTACT_STATUS_OUTREACH_DONE,
                    current_time,
                    active_message.job_posting_contact_id,
                ),
            )
            _record_state_transition(
                connection,
                object_type="job_posting_contact",
                object_id=active_message.job_posting_contact_id,
                stage="link_level_status",
                previous_state=active_message.link_level_status,
                new_state=POSTING_CONTACT_STATUS_OUTREACH_DONE,
                transition_timestamp=current_time,
                transition_reason="An outreach message was sent for this posting-contact pair.",
                lead_id=str(posting_row["lead_id"]),
                job_posting_id=str(posting_row["job_posting_id"]),
                contact_id=active_message.contact_id,
            )


def _mark_posting_contact_exhausted_for_review(
    connection: sqlite3.Connection,
    *,
    posting_row: Mapping[str, Any],
    active_message: _ActiveWaveMessage,
    current_time: str,
    transition_reason: str,
) -> None:
    if active_message.link_level_status in {
        POSTING_CONTACT_STATUS_OUTREACH_DONE,
        POSTING_CONTACT_STATUS_EXHAUSTED,
    }:
        return
    with connection:
        connection.execute(
            """
            UPDATE job_posting_contacts
            SET link_level_status = ?, updated_at = ?
            WHERE job_posting_contact_id = ?
            """,
            (
                POSTING_CONTACT_STATUS_EXHAUSTED,
                current_time,
                active_message.job_posting_contact_id,
            ),
        )
        _record_state_transition(
            connection,
            object_type="job_posting_contact",
            object_id=active_message.job_posting_contact_id,
            stage="link_level_status",
            previous_state=active_message.link_level_status,
            new_state=POSTING_CONTACT_STATUS_EXHAUSTED,
            transition_timestamp=current_time,
            transition_reason=transition_reason,
            lead_id=str(posting_row["lead_id"]),
            job_posting_id=str(posting_row["job_posting_id"]),
            contact_id=active_message.contact_id,
        )


def _complete_posting_if_wave_finished(
    connection: sqlite3.Connection,
    *,
    posting_row: Mapping[str, Any],
    current_time: str,
) -> None:
    active_wave = _load_active_role_targeted_wave(
        connection,
        job_posting_id=str(posting_row["job_posting_id"]),
    )
    if not active_wave:
        return
    latest_statuses = {message.message_status for message in active_wave}
    if not latest_statuses or not latest_statuses.issubset({MESSAGE_STATUS_SENT, MESSAGE_STATUS_BLOCKED}):
        return

    current_status = _load_current_posting_status(
        connection,
        job_posting_id=str(posting_row["job_posting_id"]),
    )
    if current_status == JOB_POSTING_STATUS_COMPLETED:
        return
    next_send_set_plan = evaluate_role_targeted_send_set(
        connection,
        job_posting_id=str(posting_row["job_posting_id"]),
        current_time=current_time,
    )
    if next_send_set_plan.selected_contacts:
        next_status = next_send_set_plan.posting_status_after_evaluation
        if next_status == JOB_POSTING_STATUS_READY_FOR_OUTREACH:
            transition_reason = (
                "The active drafted outreach wave reached terminal states, and untouched "
                "contacts remain ready for the next automatic send wave."
            )
        else:
            transition_reason = (
                "The active drafted outreach wave reached terminal states, and untouched "
                "contacts remain but still need usable email discovery before the next wave."
            )
    else:
        next_status = JOB_POSTING_STATUS_COMPLETED
        transition_reason = (
            "The active drafted outreach wave reached terminal sent or review-blocked "
            "states and no untouched automatic outreach contacts remain."
        )
    if current_status == next_status:
        return
    with connection:
        connection.execute(
            """
            UPDATE job_postings
            SET posting_status = ?, updated_at = ?
            WHERE job_posting_id = ?
            """,
            (
                next_status,
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
            new_state=next_status,
            transition_timestamp=current_time,
            transition_reason=transition_reason,
            lead_id=str(posting_row["lead_id"]),
            job_posting_id=str(posting_row["job_posting_id"]),
            contact_id=None,
        )


def _load_current_posting_status(
    connection: sqlite3.Connection,
    *,
    job_posting_id: str,
) -> str:
    row = connection.execute(
        """
        SELECT posting_status
        FROM job_postings
        WHERE job_posting_id = ?
        """,
        (job_posting_id,),
    ).fetchone()
    if row is None:
        raise OutreachSendingError(f"Job posting `{job_posting_id}` was not found.")
    return str(row["posting_status"])


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
               c.contact_status,
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


def _load_latest_general_learning_message_row(
    connection: sqlite3.Connection,
    *,
    contact_id: str,
) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT outreach_message_id, contact_id, recipient_email, message_status, subject,
               body_text, body_html, thread_id, delivery_tracking_id, sent_at, created_at,
               updated_at
        FROM outreach_messages
        WHERE contact_id = ?
          AND outreach_mode = ?
        ORDER BY created_at DESC, outreach_message_id DESC
        LIMIT 1
        """,
        (contact_id, OUTREACH_MODE_GENERAL_LEARNING),
    ).fetchone()


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
    step_4_path = paths.tailoring_step_4_evidence_map_path(company_name, role_title)
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
        "step_4_payload": _read_yaml_file(step_4_path) if step_4_path.exists() else {},
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
        return None
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
    candidate_entries = []
    for entry in bullets:
        text = str(entry.get("text") or "").strip()
        if not text:
            continue
        candidate_entries.append(
            (
                text,
                _normalize_optional_text(entry.get("purpose")) or "",
            )
        )
    if not candidate_entries:
        return None
    purpose_rank = {
        "scale-impact": 0,
        "optimization": 1,
        "end-to-end-flow": 2,
        "reliability-operations": 3,
    }
    candidate_entries.sort(
        key=lambda item: (
            purpose_rank.get(item[1], 99),
            0 if METRIC_RE.search(item[0]) else 1,
            len(item[0]),
        )
    )
    return candidate_entries[0][0]


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
    return _select_role_work_area(step_3_payload, jd_text, step_4_payload=None)


def _select_role_work_area(
    step_3_payload: Mapping[str, Any],
    jd_text: str,
    *,
    step_4_payload: Mapping[str, Any] | None,
) -> str | None:
    candidate_signals: list[tuple[str, str]] = []
    role_intent_summary = _normalize_optional_text(step_3_payload.get("role_intent_summary"))
    if role_intent_summary is not None:
        candidate_signals.extend(
            ("role_intent", part.strip())
            for part in role_intent_summary.split(";")
            if part.strip()
        )
    for priority_key in ("must_have", "core_responsibility", "nice_to_have"):
        signals = step_3_payload.get("signals_by_priority", {}).get(priority_key) or []
        for signal in signals:
            text = _normalize_optional_text(signal.get("signal"))
            if text is not None:
                candidate_signals.append((priority_key, text))
    scored_candidates: list[tuple[int, int, str]] = []
    fallback_candidates: list[str] = []
    for index, (source_kind, raw_signal) in enumerate(candidate_signals):
        cleaned = _clean_role_signal(raw_signal)
        if cleaned is not None:
            fallback_candidates.append(cleaned)
            score = _score_role_signal_for_opener(
                cleaned,
                raw_signal=raw_signal,
                source_kind=source_kind,
                step_4_payload=step_4_payload,
            )
            if score > 0:
                scored_candidates.append((score, -index, cleaned))
    if scored_candidates:
        return max(scored_candidates)[2]
    if fallback_candidates:
        return fallback_candidates[0]
    for line in jd_text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            cleaned = _clean_role_signal(stripped)
            if cleaned is not None:
                scored = _score_role_signal_for_opener(
                    cleaned,
                    raw_signal=stripped,
                    source_kind="jd_fallback",
                    step_4_payload=step_4_payload,
                )
                if scored > 0:
                    return cleaned
                return cleaned
    return None


def _clean_role_signal(value: str) -> str | None:
    cleaned = re.sub(r"\s+", " ", value.strip().rstrip("."))
    cleaned = re.sub(
        r"^[A-Za-z][A-Za-z0-9 &/()+.\-]{0,40}:\s+",
        "",
        cleaned,
    )
    cleaned = re.sub(
        r"^\d+\+?(?:\s*[-–]\s*\d+)?\s+years?\s+of\s+"
        r"(?:(?:professional|hands-on)\s+)*experience(?:\s+(?:with|in|building))?\s+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"^As a .*?,\s+you(?:'|’)ll\s+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"^(?:experience with|experience in|experience building|building|build|developing|develop|designing|design|working on|work on)\s+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"^(?:strong proficiency in|solid understanding of|hands-on experience with|proficiency in|understanding of|basic understanding of|basic knowledge of|working knowledge of|knowledge of|familiarity with)\s+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    if not cleaned:
        return None
    normalized = cleaned.lower()
    if any(pattern.search(normalized) for pattern in ROLE_SIGNAL_BOILERPLATE_PATTERNS):
        return None
    if any(pattern.search(normalized) for pattern in ROLE_SIGNAL_NONTECHNICAL_PATTERNS):
        return None
    if len(cleaned) > 220 and cleaned.count(".") + cleaned.count(";") >= 1:
        return None
    first_word, _, remainder = cleaned.partition(" ")
    gerund = ROLE_SIGNAL_VERB_PREFIXES.get(first_word.lower())
    if gerund is not None:
        cleaned = f"{gerund} {remainder}".strip()
    if (
        cleaned
        and not (len(cleaned) > 1 and cleaned[:2].isupper())
        and first_word.lower() not in ROLE_SIGNAL_LEADING_CASE_EXCEPTIONS
    ):
        cleaned = cleaned[:1].lower() + cleaned[1:]
    return cleaned or None


def _score_role_signal_for_opener(
    cleaned_signal: str,
    *,
    raw_signal: str,
    source_kind: str,
    step_4_payload: Mapping[str, Any] | None,
) -> int:
    lowered = cleaned_signal.lower()
    technical_score = max(
        weight
        for pattern, weight in ROLE_SIGNAL_TECHNICAL_PRIORITY_PATTERNS
        if pattern.search(lowered)
    ) if any(pattern.search(lowered) for pattern, _ in ROLE_SIGNAL_TECHNICAL_PRIORITY_PATTERNS) else 0
    if technical_score <= 0:
        return 0
    evidence_score = _score_jd_signal_evidence_overlap(raw_signal, step_4_payload)
    return technical_score * 100 + ROLE_SIGNAL_SOURCE_PRIORITY.get(source_kind, 0) * 10 + evidence_score * 5


def _score_jd_signal_evidence_overlap(
    raw_signal: str,
    step_4_payload: Mapping[str, Any] | None,
) -> int:
    if step_4_payload is None:
        return 0
    matches = step_4_payload.get("matches")
    if not isinstance(matches, list):
        return 0
    confidence_weight = {"high": 4, "medium": 2, "low": 1}
    score = 0
    normalized_raw_signal = raw_signal.strip()
    for match in matches:
        if not isinstance(match, Mapping):
            continue
        if _normalize_optional_text(match.get("jd_signal")) != normalized_raw_signal:
            continue
        confidence = (_normalize_optional_text(match.get("confidence")) or "").lower()
        score += confidence_weight.get(confidence, 1)
        source_excerpt = (_normalize_optional_text(match.get("source_excerpt")) or "").lower()
        if METRIC_RE.search(source_excerpt):
            score += 2
        if any(
            token in source_excerpt
            for token in (
                "microservice",
                "backend api",
                "distributed",
                "throughput",
                "uptime",
                "java",
                "aws",
                "kubernetes",
            )
        ):
            score += 1
    return score


def _build_role_targeted_subject(context: RoleTargetedDraftContext) -> str:
    return f"Interest in the {context.role_title} role at {context.company_name}"


def _compose_role_targeted_composition_plan(
    context: RoleTargetedDraftContext,
) -> RoleTargetedCompositionPlan:
    proof_point = context.proof_point or (
        "the distributed systems work I have done across reliability, performance, and production delivery"
    )
    opener_inputs = _compose_role_targeted_opener_inputs(context)
    plan = RoleTargetedCompositionPlan(
        opener_paragraph=_render_role_targeted_opener(opener_inputs),
        background_paragraph=(
            f"{_build_role_targeted_why_line(context)} "
            f"{_proof_point_sentence(proof_point)}"
        ),
        copilot_paragraphs=tuple(_job_hunt_copilot_pitch_lines()),
        ask_paragraph=(
            "If it would be useful, I would welcome a short 15-minute conversation sometime this or next week "
            "to learn a bit more about the role and get your perspective on whether my background could be relevant. "
            "If you're not the right person, I'd also really appreciate it if you could point me to the right "
            "person or forward my resume internally."
        ),
        snippet_text=_render_forwardable_snippet_text(context),
    )
    _validate_role_targeted_composition_plan(plan)
    return plan


def _compose_role_targeted_opener_inputs(
    context: RoleTargetedDraftContext,
) -> RoleTargetedOpenerInputs:
    role_theme = _compose_role_targeted_role_theme(context)
    technical_focus = _compose_role_targeted_technical_focus(context, role_theme)
    lowered = role_theme.lower()
    if "security" in lowered or "government" in lowered:
        return RoleTargetedOpenerInputs(
            company_name=context.company_name,
            role_title=context.role_title,
            role_theme=role_theme,
            technical_focus=technical_focus,
            overlap_sentence=(
                "That is an area where I want to keep building depth."
            ),
        )
    if "leadership" in lowered or "scheduling" in lowered:
        return RoleTargetedOpenerInputs(
            company_name=context.company_name,
            role_title=context.role_title,
            role_theme=role_theme,
            technical_focus=technical_focus,
            overlap_sentence=(
                "That is close to the kind of systems and leadership work I want to keep leaning into."
            ),
        )
    if "platform" in lowered or "cloud" in lowered:
        return RoleTargetedOpenerInputs(
            company_name=context.company_name,
            role_title=context.role_title,
            role_theme=role_theme,
            technical_focus=technical_focus,
            overlap_sentence=(
                "That is close to the kind of platform and infrastructure work I want to keep growing in."
            ),
        )
    if "python" in lowered:
        return RoleTargetedOpenerInputs(
            company_name=context.company_name,
            role_title=context.role_title,
            role_theme=role_theme,
            technical_focus=technical_focus,
            overlap_sentence=(
                "That is close to the kind of systems work I have been doing in production over the last "
                "few years."
            ),
        )
    return RoleTargetedOpenerInputs(
        company_name=context.company_name,
        role_title=context.role_title,
        role_theme=role_theme,
        technical_focus=technical_focus,
        overlap_sentence=(
            "That is close to the kind of systems work I have been doing in production over the last few "
            "years."
        ),
    )


def _render_role_targeted_opener(inputs: RoleTargetedOpenerInputs) -> str:
    return (
        f"I'm reaching out about the {inputs.role_title} role at {inputs.company_name} because I was "
        f"interested in the role's focus on {inputs.technical_focus}. {inputs.overlap_sentence}"
    )


def _build_role_targeted_why_line(context: RoleTargetedDraftContext) -> str:
    title = _normalize_optional_text(context.position_title)
    if context.recipient_type == RECIPIENT_TYPE_RECRUITER:
        if title is not None:
            return f"Given your role as {title}, I thought you might have useful perspective on the hiring context for this opening."
        return "I thought you might have useful perspective on the hiring context for this opening."
    if context.recipient_type == RECIPIENT_TYPE_HIRING_MANAGER:
        if title is not None:
            return f"Given your role as {title}, I thought you might have useful perspective on the team and the problems this role is meant to solve."
        return "I thought you might have useful perspective on the team and the problems this role is meant to solve."
    if context.recipient_type == RECIPIENT_TYPE_ALUMNI:
        return (
            "I'm reaching out to you specifically because you seemed like the right fellow Sun Devil to ask for a grounded perspective on this work."
        )
    if title is not None:
        return f"Given your role as {title}, I thought you might have useful perspective on the day-to-day work this role touches."
    return "I thought you might have useful perspective on the day-to-day work this role touches."


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


def _snippet_intro_sentence(context: RoleTargetedDraftContext) -> str:
    if context.recipient_type in {RECIPIENT_TYPE_HIRING_MANAGER, RECIPIENT_TYPE_FOUNDER}:
        return (
            f"Hi, passing along a candidate who may be worth a look for the "
            f"{context.role_title} role at {context.company_name}."
        )
    return (
        f"Hi, sharing a candidate who may be relevant for the "
        f"{context.role_title} role at {context.company_name}."
    )


def _snippet_background_sentence(context: RoleTargetedDraftContext) -> str:
    experience = _experience_summary_line(context)
    if context.recipient_type in {RECIPIENT_TYPE_HIRING_MANAGER, RECIPIENT_TYPE_ENGINEER}:
        return f"His background includes {experience}."
    return f"He has {experience}."


def _snippet_proof_sentence(context: RoleTargetedDraftContext) -> str:
    impact = _impact_summary_line(context)
    return f"One relevant example: {impact}."


def _role_work_area_phrase(value: str | None) -> str:
    normalized = _normalize_optional_text(value)
    if normalized is None:
        return "backend and distributed systems work"
    cleaned = normalized.strip(" .,:;")
    lowered = cleaned.lower()
    for prefix in ("and ", "to ", "help ", "able to "):
        if lowered.startswith(prefix):
            cleaned = cleaned[len(prefix):].strip(" .,:;")
            lowered = cleaned.lower()
    for marker in (
        ", based on definitions from more senior roles",
        " based on definitions from more senior roles",
        "; based on definitions from more senior roles",
    ):
        position = lowered.find(marker)
        if position >= 0:
            cleaned = cleaned[:position].strip(" .,:;")
            lowered = cleaned.lower()
    if ";" in cleaned:
        parts = [part.strip(" .,:;") for part in cleaned.split(";") if part.strip(" .,:;")]
        if parts:
            cleaned = parts[-1]
            lowered = cleaned.lower()
    return cleaned or "backend and distributed systems work"


def _compose_role_targeted_role_theme(context: RoleTargetedDraftContext) -> str:
    source = " ".join(
        value
        for value in (
            context.role_title,
            _normalize_optional_text(context.work_area),
            _normalize_optional_text(context.role_intent_summary),
            context.jd_text[:2000],
        )
        if value
    ).lower()
    if any(
        token in source
        for token in (
            "information security",
            "security engineer",
            "enterprise security",
            "application security",
            "cloud security",
            "cybersecurity",
            "cyber security",
            "secure infrastructure",
            "intel federal",
            "government information security",
            "government-focused security",
        )
    ):
        return "enterprise security systems, secure infrastructure, and government-focused security work"
    if any(token in source for token in ("scheduler", "scheduling", "scheduling engines")):
        return "engineering leadership and real-time scheduling systems"
    if any(token in source for token in ("distributed", "grpc", "load balancing")):
        return "backend systems, distributed services, and production delivery"
    if "backend" in source:
        return "backend services and application delivery"
    if any(token in source for token in ("event-driven", "metadata", "documents", "document", "python")):
        return "production Python services, backend systems, and distributed processing"
    if any(token in source for token in ("platform", "cloud", "infrastructure")):
        return "cloud infrastructure, platform systems, and production engineering"
    candidate = _role_work_area_phrase(context.work_area or context.role_intent_summary)
    if len(candidate.split()) <= 8 and " " in candidate:
        return candidate
    return "backend systems, distributed services, and production engineering"


def _compose_role_targeted_technical_focus(
    context: RoleTargetedDraftContext,
    role_theme: str,
) -> str:
    for raw_value in (context.work_area, context.role_intent_summary):
        normalized_focus = _normalize_technical_focus_phrase(raw_value)
        if normalized_focus is not None:
            return normalized_focus
    return role_theme


def _join_focus_phrases(parts: Sequence[str]) -> str:
    cleaned = [part.strip(" ,.;") for part in parts if part.strip(" ,.;")]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    if len(cleaned) == 2:
        return f"{cleaned[0]} and {cleaned[1]}"
    return ", ".join(cleaned[:-1]) + f", and {cleaned[-1]}"


def _looks_like_technology_focus_list(value: str) -> bool:
    lowered = value.lower()
    if any(
        marker in lowered
        for marker in (
            "backend work will include",
            "frontend work will include",
            "technologies such as",
            "as well as html",
            "as well as css",
            "as well as javascript",
            "as well as bootstrap",
        )
    ):
        return True
    tech_term_hits = sum(
        1
        for term in (
            "java",
            "scala",
            "kotlin",
            "restful",
            "spring",
            "angular",
            "html",
            "css",
            "javascript",
            "bootstrap",
            "docker",
            "kubernetes",
            "aws",
            "gcp",
            "azure",
        )
        if term in lowered
    )
    return value.count(",") >= 3 and tech_term_hits >= 3


def _summarize_technical_focus_enumeration(candidate: str) -> str:
    normalized = re.sub(r"\band\b", ",", candidate, flags=re.IGNORECASE)
    raw_parts = [part.strip(" ,.;") for part in normalized.split(",") if part.strip(" ,.;")]
    if len(raw_parts) <= 4:
        return candidate

    selected: list[str] = []
    for part in raw_parts:
        lowered = part.lower()
        if lowered in {"backend work will include", "frontend work will include", "technologies such as"}:
            continue
        if lowered.startswith("containerization technologies"):
            part = "containerization technologies"
        elif lowered == "restful":
            part = "RESTful services"
        if part not in selected:
            selected.append(part)

    if not selected:
        return candidate

    preferred_order = [
        "angular",
        "html",
        "css",
        "javascript",
        "bootstrap",
        "java",
        "scala",
        "restful services",
        "spring",
        "kotlin",
        "aws",
        "gcp",
        "azure",
        "docker",
        "kubernetes",
        "containerization technologies",
    ]
    preferred: list[str] = []
    for term in preferred_order:
        for part in selected:
            if part.lower() == term and part not in preferred:
                preferred.append(part)
    if preferred:
        selected = preferred + [part for part in selected if part not in preferred]

    if "containerization technologies" in selected and len(selected) > 4:
        selected = [part for part in selected if part != "containerization technologies"][:3] + [
            "containerization technologies"
        ]
    else:
        selected = selected[:4]

    summary = _join_focus_phrases(selected)
    return summary or candidate


def _normalize_technical_focus_phrase(value: str | None) -> str | None:
    normalized = _normalize_optional_text(value)
    if normalized is None:
        return None
    candidate = _clean_role_signal(normalized)
    if candidate is None:
        candidate = _role_work_area_phrase(normalized)
    candidate = _role_work_area_phrase(candidate)
    first_word, _, remainder = candidate.partition(" ")
    gerund = ROLE_SIGNAL_VERB_PREFIXES.get(first_word.lower())
    if gerund is not None:
        candidate = f"{gerund} {remainder}".strip()
    candidate = re.sub(
        r"\busing agile methodologies and devops principles\b.*$",
        "",
        candidate,
        flags=re.IGNORECASE,
    )
    candidate = re.sub(
        r"\bto improve and grow\b.*$",
        "",
        candidate,
        flags=re.IGNORECASE,
    )
    candidate = re.sub(
        r"\bwith a constant focus on security\b.*$",
        "",
        candidate,
        flags=re.IGNORECASE,
    )
    candidate = re.sub(
        r"^(?:backend|frontend)\s+work\s+will\s+include(?:\s+project\s+heavily\s+using|\s+technologies\s+such\s+as)?\s+",
        "",
        candidate,
        flags=re.IGNORECASE,
    )
    candidate = re.sub(
        r"\btechnologies such as\b",
        "",
        candidate,
        flags=re.IGNORECASE,
    )
    candidate = re.sub(
        r"\bas well as\b",
        ",",
        candidate,
        flags=re.IGNORECASE,
    )
    candidate = re.sub(
        r"\bto deliver\b.*$",
        "",
        candidate,
        flags=re.IGNORECASE,
    )
    candidate = re.sub(
        r"\bwith an emphasis on\b.*$",
        "",
        candidate,
        flags=re.IGNORECASE,
    )
    candidate = re.sub(
        r"\bRESTful\b(?!\s+services)",
        "RESTful services",
        candidate,
        flags=re.IGNORECASE,
    )
    candidate = re.sub(r"\s+", " ", candidate).strip(" ,.;")
    if _looks_like_technology_focus_list(candidate):
        candidate = _summarize_technical_focus_enumeration(candidate)
    if not candidate:
        return None
    lowered = candidate.lower()
    if any(pattern.search(lowered) for pattern in ROLE_SIGNAL_BOILERPLATE_PATTERNS):
        return None
    if len(candidate.split()) > 18:
        return None
    if re.search(r"\b(?:identifies|develops|plans|implements|supports),\s", lowered):
        return None
    return candidate


def _role_work_area_opening(work_area: str) -> str:
    lowered = work_area.lower()
    base_action_prefixes = (
        "build ",
        "design ",
        "develop ",
        "implement ",
        "improve ",
        "optimize ",
        "scale ",
        "modernize ",
        "create ",
        "lead ",
        "support ",
        "maintain ",
        "drive ",
        "own ",
        "extract ",
        "enrich ",
        "process ",
    )
    gerund_action_prefixes = (
        "building ",
        "designing ",
        "developing ",
        "implementing ",
        "improving ",
        "optimizing ",
        "scaling ",
        "modernizing ",
        "creating ",
        "leading ",
        "supporting ",
        "maintaining ",
        "driving ",
        "owning ",
        "extracting ",
        "enriching ",
        "processing ",
        "delivering ",
    )
    if lowered.startswith(base_action_prefixes):
        return f"the chance to {work_area}"
    if lowered.startswith(gerund_action_prefixes):
        return f"the chance to work on {work_area}"
    return f"the work around {work_area}"


def _ensure_sentence(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return ""
    if stripped.endswith((".", "!", "?")):
        return stripped
    return stripped + "."


def _proof_point_sentence(proof_point: str) -> str:
    stripped = proof_point.strip().rstrip(".")
    if not stripped:
        return "For example, I have worked on backend and distributed systems in production."
    lowered = stripped.lower()
    if lowered.startswith("i "):
        return f"In one recent role, {stripped}."
    verb_prefixes = (
        "built ",
        "designed ",
        "developed ",
        "implemented ",
        "optimized ",
        "led ",
        "created ",
        "improved ",
        "shipped ",
        "migrated ",
        "automated ",
        "scaled ",
        "reduced ",
        "owned ",
        "processed ",
        "ran ",
        "delivered ",
    )
    if lowered.startswith(verb_prefixes):
        return f"In one recent role, I {stripped[0].lower()}{stripped[1:]}."
    return f"For example, {stripped}."


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


def _job_hunt_copilot_pitch_lines() -> list[str]:
    return [
        "Lately, I have been spending time sharpening my Agentic AI skills.",
        (
            f"I built Job Hunt Copilot ({JOB_HUNT_COPILOT_REPO_URL}) for my own job search, "
            "and this email is one of its live outputs."
        ),
        (
            "It is an AI agent I use for my own job search to find leads and send outreach autonomously, "
            "and I personally review every email before it goes out."
        ),
    ]


def _render_forwardable_snippet_text(context: RoleTargetedDraftContext) -> str:
    linkedin = _compact_linkedin(context.sender.linkedin_url)
    return " ".join(
        [
            _snippet_intro_sentence(context),
            _snippet_background_sentence(context),
            _snippet_proof_sentence(context),
            f"Profile: {linkedin}",
        ]
    )


def _validate_role_targeted_composition_plan(plan: RoleTargetedCompositionPlan) -> None:
    combined_text = " ".join(
        [
            plan.opener_paragraph,
            plan.background_paragraph,
            *plan.copilot_paragraphs,
            plan.ask_paragraph,
            plan.snippet_text,
        ]
    )
    for pattern in ROLE_TARGETED_DRAFT_BLOCK_PATTERNS:
        if pattern.search(combined_text):
            raise OutreachDraftingError(
                f"Role-targeted composition failed quality validation for pattern `{pattern.pattern}`."
            )


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


def _evaluate_general_learning_send_guardrails(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    contact_row: Mapping[str, Any],
    active_message: Mapping[str, Any],
) -> dict[str, str] | None:
    contact_id = str(contact_row["contact_id"])
    recipient_email = _normalize_optional_text(active_message["recipient_email"])
    if recipient_email is None:
        return {
            "reason_code": "missing_recipient_email",
            "message": "Automatic general-learning sending requires a usable recipient email.",
        }
    if (
        _normalize_optional_text(active_message["subject"]) is None
        or _normalize_optional_text(active_message["body_text"]) is None
    ):
        return {
            "reason_code": "missing_draft_content",
            "message": "Automatic general-learning sending requires persisted draft subject and body content.",
        }

    company_name = str(contact_row["company_name"] or "unknown-company")
    draft_path = paths.general_learning_outreach_draft_path(
        company_name,
        contact_id,
        str(active_message["outreach_message_id"]),
    )
    send_result_path = paths.general_learning_outreach_send_result_path(
        company_name,
        contact_id,
        str(active_message["outreach_message_id"]),
    )
    if not draft_path.exists():
        return {
            "reason_code": "missing_draft_artifact",
            "message": f"Draft artifact is missing for `{active_message['outreach_message_id']}`.",
        }
    if not send_result_path.exists():
        return {
            "reason_code": "missing_send_result_artifact",
            "message": f"send_result.json is missing for `{active_message['outreach_message_id']}`.",
        }

    try:
        send_result_contract = _read_json_file(send_result_path)
    except Exception:
        return {
            "reason_code": "invalid_send_result_artifact",
            "message": f"send_result.json is unreadable for `{active_message['outreach_message_id']}`.",
        }
    send_status = _normalize_optional_text(send_result_contract.get("send_status"))
    if send_status in {MESSAGE_STATUS_SENT, MESSAGE_STATUS_BLOCKED}:
        return {
            "reason_code": "ambiguous_send_state",
            "message": "Stored general-learning send_result.json already reflects a non-generated send state, so automatic resend is unsafe.",
        }
    if (
        _normalize_optional_text(active_message["sent_at"]) is not None
        or _normalize_optional_text(active_message["thread_id"]) is not None
        or _normalize_optional_text(active_message["delivery_tracking_id"]) is not None
    ):
        return {
            "reason_code": "ambiguous_send_state",
            "message": "Message delivery metadata already exists without a clean completed send state, so automatic resend is unsafe.",
        }

    prior_sent_count = int(
        connection.execute(
            """
            SELECT COUNT(*)
            FROM outreach_messages
            WHERE contact_id = ?
              AND outreach_message_id <> ?
              AND (
                sent_at IS NOT NULL
                OR message_status = ?
              )
            """,
            (
                contact_id,
                str(active_message["outreach_message_id"]),
                MESSAGE_STATUS_SENT,
            ),
        ).fetchone()[0]
        or 0
    )
    if prior_sent_count > 0:
        return {
            "reason_code": "repeat_outreach_review_required",
            "message": "Prior outreach history exists for this contact, so automatic repeat sending is blocked pending review.",
        }

    other_active_message_count = int(
        connection.execute(
            """
            SELECT COUNT(*)
            FROM outreach_messages
            WHERE contact_id = ?
              AND outreach_message_id <> ?
              AND message_status IN (?, ?)
            """,
            (
                contact_id,
                str(active_message["outreach_message_id"]),
                MESSAGE_STATUS_GENERATED,
                MESSAGE_STATUS_BLOCKED,
            ),
        ).fetchone()[0]
        or 0
    )
    if other_active_message_count > 0:
        return {
            "reason_code": "ambiguous_send_state",
            "message": "Multiple active outreach messages exist for this contact, so automatic resend is unsafe.",
        }
    return None


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


def _persist_successful_general_learning_send(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    contact_row: Mapping[str, Any],
    active_message: Mapping[str, Any],
    current_time: str,
    drafted_message: DraftedOutreachMessage | None,
    sent_at: str,
    thread_id: str | None,
    delivery_tracking_id: str | None,
) -> GeneralLearningSendExecutionResult:
    normalized_sent_at = _isoformat_utc(_parse_iso_datetime(sent_at))
    outreach_message_id = str(active_message["outreach_message_id"])
    with connection:
        connection.execute(
            """
            UPDATE outreach_messages
            SET message_status = ?, thread_id = ?, delivery_tracking_id = ?, sent_at = ?, updated_at = ?
            WHERE outreach_message_id = ?
            """,
            (
                MESSAGE_STATUS_SENT,
                thread_id,
                delivery_tracking_id,
                normalized_sent_at,
                current_time,
                outreach_message_id,
            ),
        )

    current_contact_status = str(contact_row["contact_status"]).strip()
    if current_contact_status != CONTACT_STATUS_SENT:
        with connection:
            connection.execute(
                """
                UPDATE contacts
                SET contact_status = ?, updated_at = ?
                WHERE contact_id = ?
                """,
                (
                    CONTACT_STATUS_SENT,
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
                new_state=CONTACT_STATUS_SENT,
                transition_timestamp=current_time,
                transition_reason="A general-learning outreach message was sent for this contact.",
                lead_id=None,
                job_posting_id=None,
                contact_id=str(contact_row["contact_id"]),
            )

    send_result_artifact_path = _publish_general_learning_send_result(
        connection,
        paths,
        contact_row=contact_row,
        active_message=active_message,
        current_time=current_time,
        result="success",
        send_status=MESSAGE_STATUS_SENT,
        sent_at=normalized_sent_at,
        thread_id=thread_id,
        delivery_tracking_id=delivery_tracking_id,
        reason_code=None,
        message=None,
    )
    return GeneralLearningSendExecutionResult(
        contact_id=str(contact_row["contact_id"]),
        outreach_message_id=outreach_message_id,
        drafted_message=drafted_message,
        message_status_after_execution=MESSAGE_STATUS_SENT,
        send_result_artifact_path=send_result_artifact_path,
        sent_at=normalized_sent_at,
        thread_id=thread_id,
        delivery_tracking_id=delivery_tracking_id,
        reason_code=None,
        message=None,
    )


def _persist_blocked_general_learning_send(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    contact_row: Mapping[str, Any],
    active_message: Mapping[str, Any],
    current_time: str,
    drafted_message: DraftedOutreachMessage | None,
    reason_code: str,
    message: str,
) -> GeneralLearningSendExecutionResult:
    outreach_message_id = str(active_message["outreach_message_id"])
    with connection:
        connection.execute(
            """
            UPDATE outreach_messages
            SET message_status = ?, updated_at = ?
            WHERE outreach_message_id = ?
            """,
            (
                MESSAGE_STATUS_BLOCKED,
                current_time,
                outreach_message_id,
            ),
        )

    send_result_artifact_path = _publish_general_learning_send_result(
        connection,
        paths,
        contact_row=contact_row,
        active_message=active_message,
        current_time=current_time,
        result="blocked",
        send_status=MESSAGE_STATUS_BLOCKED,
        sent_at=None,
        thread_id=_normalize_optional_text(active_message["thread_id"]),
        delivery_tracking_id=_normalize_optional_text(active_message["delivery_tracking_id"]),
        reason_code=reason_code,
        message=message,
    )
    return GeneralLearningSendExecutionResult(
        contact_id=str(contact_row["contact_id"]),
        outreach_message_id=outreach_message_id,
        drafted_message=drafted_message,
        message_status_after_execution=MESSAGE_STATUS_BLOCKED,
        send_result_artifact_path=send_result_artifact_path,
        sent_at=None,
        thread_id=None,
        delivery_tracking_id=None,
        reason_code=reason_code,
        message=message,
    )


def _persist_failed_general_learning_send_attempt(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    contact_row: Mapping[str, Any],
    active_message: Mapping[str, Any],
    current_time: str,
    drafted_message: DraftedOutreachMessage | None,
    reason_code: str,
    message: str,
) -> GeneralLearningSendExecutionResult:
    outreach_message_id = str(active_message["outreach_message_id"])
    with connection:
        connection.execute(
            """
            UPDATE outreach_messages
            SET message_status = ?, updated_at = ?
            WHERE outreach_message_id = ?
            """,
            (
                MESSAGE_STATUS_FAILED,
                current_time,
                outreach_message_id,
            ),
        )

    send_result_artifact_path = _publish_general_learning_send_result(
        connection,
        paths,
        contact_row=contact_row,
        active_message=active_message,
        current_time=current_time,
        result="failed",
        send_status=MESSAGE_STATUS_FAILED,
        sent_at=None,
        thread_id=None,
        delivery_tracking_id=None,
        reason_code=reason_code,
        message=message,
    )
    return GeneralLearningSendExecutionResult(
        contact_id=str(contact_row["contact_id"]),
        outreach_message_id=outreach_message_id,
        drafted_message=drafted_message,
        message_status_after_execution=MESSAGE_STATUS_FAILED,
        send_result_artifact_path=send_result_artifact_path,
        sent_at=None,
        thread_id=None,
        delivery_tracking_id=None,
        reason_code=reason_code,
        message=message,
    )


def _publish_general_learning_send_result(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    contact_row: Mapping[str, Any],
    active_message: Mapping[str, Any],
    current_time: str,
    result: str,
    send_status: str,
    sent_at: str | None,
    thread_id: str | None,
    delivery_tracking_id: str | None,
    reason_code: str | None,
    message: str | None,
) -> str:
    company_name = str(contact_row["company_name"] or "unknown-company")
    contact_id = str(contact_row["contact_id"])
    outreach_message_id = str(active_message["outreach_message_id"])
    draft_path = paths.general_learning_outreach_draft_path(
        company_name,
        contact_id,
        outreach_message_id,
    )
    html_path = paths.general_learning_outreach_html_path(
        company_name,
        contact_id,
        outreach_message_id,
    )
    send_result_path = paths.general_learning_outreach_send_result_path(
        company_name,
        contact_id,
        outreach_message_id,
    )
    publish_json_artifact(
        connection,
        paths,
        artifact_type=SEND_RESULT_ARTIFACT_TYPE,
        artifact_path=send_result_path,
        producer_component=OUTREACH_COMPONENT,
        result=result,
        linkage=ArtifactLinkage(
            contact_id=contact_id,
            outreach_message_id=outreach_message_id,
        ),
        payload={
            "outreach_mode": OUTREACH_MODE_GENERAL_LEARNING,
            "recipient_email": _normalize_optional_text(active_message["recipient_email"]),
            "send_status": send_status,
            "sent_at": sent_at,
            "thread_id": thread_id,
            "delivery_tracking_id": delivery_tracking_id,
            "subject": _normalize_optional_text(active_message["subject"]),
            "body_text_artifact_path": str(draft_path.resolve()) if draft_path.exists() else None,
            "body_html_artifact_path": str(html_path.resolve()) if html_path.exists() else None,
        },
        produced_at=current_time,
        reason_code=reason_code,
        message=message,
    )
    return str(send_result_path.resolve())


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
    pitch_lines = _job_hunt_copilot_pitch_lines()
    snippet_intro_line = "I've included a short snippet below that you can paste into an IM/Email:"

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

    body_lines = body_markdown.splitlines()
    index = 0
    while index < len(body_lines):
        raw_line = body_lines[index]
        stripped = raw_line.rstrip()
        if not stripped:
            flush_paragraph()
            flush_blockquote()
            index += 1
            continue
        if stripped == snippet_intro_line:
            flush_paragraph()
            flush_blockquote()
            html_blocks.append(f"<p>{html.escape(snippet_intro_line)}</p>")
            index += 1
            if index < len(body_lines) and body_lines[index].strip() == "[snippet]":
                snippet_lines: list[str] = []
                index += 1
                while index < len(body_lines):
                    snippet_line = body_lines[index].rstrip()
                    if snippet_line.strip() == "[/snippet]":
                        index += 1
                        break
                    snippet_lines.append(snippet_line)
                    index += 1
                html_blocks.append(_render_forwardable_snippet_html("\n".join(snippet_lines).strip()))
            continue
        if stripped == "Best,":
            flush_paragraph()
            flush_blockquote()
            signature_lines = ["Best,"]
            index += 1
            while index < len(body_lines):
                signature_line = body_lines[index].rstrip()
                if not signature_line:
                    break
                signature_lines.append(signature_line)
                index += 1
            html_blocks.append(_render_signature_block_html(signature_lines))
            continue
        if stripped == "[snippet]":
            flush_paragraph()
            flush_blockquote()
            snippet_lines: list[str] = []
            index += 1
            while index < len(body_lines):
                snippet_line = body_lines[index].rstrip()
                if snippet_line.strip() == "[/snippet]":
                    index += 1
                    break
                snippet_lines.append(snippet_line)
                index += 1
            html_blocks.append(_render_forwardable_snippet_html("\n".join(snippet_lines).strip()))
            continue
        if body_lines[index : index + len(pitch_lines)] == pitch_lines:
            flush_paragraph()
            flush_blockquote()
            html_blocks.append(_render_job_hunt_copilot_callout_html())
            index += len(pitch_lines)
            continue
        if stripped.startswith("> "):
            flush_paragraph()
            blockquote_lines.append(stripped[2:])
            index += 1
            continue
        flush_blockquote()
        paragraph_lines.append(stripped)
        index += 1
    flush_paragraph()
    flush_blockquote()
    return "<html><body>" + "".join(html_blocks) + "</body></html>\n"


def _render_job_hunt_copilot_callout_html() -> str:
    line_one, line_two, line_three = _job_hunt_copilot_pitch_lines()
    repo_url = html.escape(JOB_HUNT_COPILOT_REPO_URL, quote=True)
    escaped_repo_text = html.escape(JOB_HUNT_COPILOT_REPO_URL)
    line_two_html = html.escape(line_two).replace(
        escaped_repo_text,
        f'<a href="{repo_url}" style="color:#1d4ed8;text-decoration:none;font-weight:600;">{escaped_repo_text}</a>',
    )
    return (
        '<div style="margin:16px 0;padding:14px 16px;'
        'border-left:3px solid #111827;border-radius:4px;'
        'background:#f8fafc;">'
        f'<p style="margin:0 0 8px 0;color:#334155;line-height:1.55;">{html.escape(line_one)}</p>'
        f'<p style="margin:0 0 8px 0;color:#111827;line-height:1.55;font-weight:600;">{line_two_html}</p>'
        f'<p style="margin:0;color:#475569;line-height:1.55;">{html.escape(line_three)}</p>'
        "</div>"
    )


def _render_forwardable_snippet_html(snippet_text: str) -> str:
    return (
        '<div style="background:#f4f4f4;border-left:4px solid #1a73e8;'
        "padding:12px 16px;margin:12px 0;border-radius:4px;"
        "font-family:Arial,sans-serif;font-size:13px;color:#333;"
        'line-height:1.5;white-space:pre-wrap;">'
        f"{html.escape(snippet_text)}"
        "</div>"
    )


def _render_signature_block_html(signature_lines: Sequence[str]) -> str:
    escaped_lines = [html.escape(line) for line in signature_lines]
    return (
        '<p style="margin:16px 0 0 0;line-height:1.6;">'
        + "<br>".join(escaped_lines)
        + "</p>"
    )


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
