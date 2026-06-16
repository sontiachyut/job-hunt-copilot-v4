from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence
from zoneinfo import ZoneInfo

from .artifacts import ArtifactLinkage, write_json_contract
from .contracts import CONTRACT_VERSION
from .llm_usage import record_codex_usage_event
from .outreach import (
    AUTONOMOUS_CODEX_DRAFT_TIMEOUT_SECONDS,
    CODEX_TIMEOUT_EXIT_CODE,
    JOB_HUNT_COPILOT_REPO_URL,
    MANAGERIAL_PATH_CTA_QUESTION,
    MAX_AUTOMATIC_TRANSIENT_SEND_RETRIES,
    MAX_INTER_SEND_GAP_MINUTES,
    MESSAGE_STATUS_BLOCKED,
    MESSAGE_STATUS_FAILED,
    MESSAGE_STATUS_SENT,
    MIN_INTER_SEND_GAP_MINUTES,
    SEND_OUTCOME_AMBIGUOUS,
    SEND_OUTCOME_FAILED,
    SEND_OUTCOME_SENT,
    SendAttemptOutcome,
    TECHNICAL_PATH_SUBJECT,
    TRANSIENT_SEND_RETRY_COOLDOWN_MINUTES,
    _normalize_subprocess_stream_text,
    is_role_targeted_sending_actionable_now,
)
from .paths import ProjectPaths
from .records import new_canonical_id, now_utc_iso


FOLLOWUP_COMPONENT = "followup_worker"
FOLLOWUP_SCHEDULER_NAME = "job-hunt-copilot-followups"
FOLLOWUP_SCHEDULER_TYPE = "launchd"
FOLLOWUP_INTERVAL_SECONDS = 60
FOLLOWUP_DRY_RUN_BATCH_SIZE = 25
FOLLOWUP_INITIAL_AUTO_SEND_CAP = 10

OUTREACH_MODE_ROLE_TARGETED = "role_targeted"
OUTREACH_MODE_ROLE_TARGETED_FOLLOWUP = "role_targeted_followup"
LEGACY_FOLLOWUP_MODES = frozenset({"follow_up", OUTREACH_MODE_ROLE_TARGETED_FOLLOWUP})

FOLLOWUP_MAX_SEQUENCE = 3
FOLLOWUP_DAY_GAPS = {
    1: 4,
    2: 5,
    3: 7,
}
FOLLOWUP_BUSINESS_TIMEZONE = ZoneInfo("America/Phoenix")
FOLLOWUP_WINDOW_START = time(hour=5, minute=0)
FOLLOWUP_WINDOW_END = time(hour=17, minute=0)
FOLLOWUP_DRAFT_RETRY_LIMIT = 3

POSTURE_TECHNICAL = "technical"
POSTURE_MANAGERIAL = "managerial"

PLAN_STATUS_PENDING = "pending"
PLAN_STATUS_DRY_RUN_READY = "dry_run_ready"
PLAN_STATUS_AGENT_REVIEWED = "agent_reviewed"
PLAN_STATUS_WAITING_FOR_PACING = "waiting_for_pacing"
PLAN_STATUS_RETRYABLE = "retryable"
PLAN_STATUS_SENT = "sent"
PLAN_STATUS_SKIPPED = "skipped"
PLAN_STATUS_BLOCKED = "blocked"
PLAN_STATUS_HELD_FOR_REVIEW = "held_for_review"
PLAN_STATUS_AMBIGUOUS = "ambiguous"

TERMINAL_PLAN_STATUSES = frozenset(
    {
        PLAN_STATUS_SENT,
        PLAN_STATUS_SKIPPED,
        PLAN_STATUS_BLOCKED,
        PLAN_STATUS_HELD_FOR_REVIEW,
        PLAN_STATUS_AMBIGUOUS,
    }
)

SKIP_REASON_ALREADY_FOLLOWED_UP = "already_followed_up"
SKIP_REASON_BOUNCED = "bounced"
SKIP_REASON_REPLIED_IN_THREAD = "replied_in_thread"
SKIP_REASON_CONTACT_REPLY_SUPPRESSION = "contact_reply_suppression"
SKIP_REASON_MISSING_THREAD_CONTEXT = "missing_followup_thread_context"
SKIP_REASON_MISSING_ORIGINAL_BODY = "missing_original_body"
SKIP_REASON_WAITING_FOR_PACING = "waiting_for_pacing"
SKIP_REASON_ROLE_TARGETED_PRIORITY = "role_targeted_priority_wait"
SKIP_REASON_TRANSIENT_RETRY = "transient_send_retry_cooldown"
SKIP_REASON_AMBIGUOUS_SEND = "ambiguous_send_state"
SKIP_REASON_GROUNDING_INSUFFICIENT = "grounding_evidence_insufficient"
SKIP_REASON_CONTACT_HARD_STOP = "contact_hard_stop"
SKIP_REASON_AUTO_SEND_DISABLED = "followup_auto_send_disabled"
SKIP_REASON_MISSING_SENDER_IDENTITY = "missing_sender_identity"
SKIP_REASON_NON_CODEX_ORIGIN = "cutover_retired_deterministic_origin_thread"
SKIP_REASON_UNKNOWN_ORIGIN = "unknown_origin_during_codex_cutover"
SKIP_REASON_MANUAL_ORIGIN = "manual_origin_not_eligible"
SKIP_REASON_NEWER_THREAD_PREFERRED = "newer_codex_thread_preferred"
SKIP_REASON_MULTI_RECIPIENT = "multi_recipient_original_thread"
SKIP_REASON_CANNOT_CLASSIFY_POSTURE = "cannot_classify_followup_posture"
SKIP_REASON_DRAFT_RETRY = "followup_draft_retry"
SKIP_REASON_DRAFT_RETRY_EXHAUSTED = "followup_draft_retry_exhausted"
SKIP_REASON_THREAD_NOT_DUE = "followup_not_due"
SKIP_REASON_THREAD_OUTSIDE_WINDOW = "outside_followup_send_window"
SKIP_REASON_POSTING_ARCHIVED_PRE_CUTOVER = "posting_archived_pre_cutover"

FOLLOWUP_AUTO_SEND_ENABLED_KEY = "followup_auto_send_enabled"
FOLLOWUP_AUTO_SEND_PAUSED_KEY = "followup_auto_send_paused"
FOLLOWUP_INITIAL_ROLLOUT_SENT_COUNT_KEY = "followup_initial_rollout_sent_count"
FOLLOWUP_INITIAL_ROLLOUT_APPROVED_KEY = "followup_initial_rollout_approved"

CONTACT_HARD_STOP_STATUSES = frozenset(
    {
        "do_not_contact",
        "blacklisted",
        "blocked",
        "owner_blocked",
        "unsubscribed",
    }
)

EMAIL_RE = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.IGNORECASE)
BOUNCE_SENDER_PATTERN = re.compile(r"\b(?:mailer-daemon|postmaster)\b", re.IGNORECASE)
ROLE_SPLIT_MANAGERIAL_SUBJECT_RE = re.compile(r"^Interest in the .+ role at .+$")
FIXED_FINAL_TOUCH_SENTENCE = (
    "If now isn't the right time, I completely understand and this will be my last follow-up."
)
PROHIBITED_LEAK_PATTERNS = (
    re.compile(r"\bjob hunt copilot\b", re.IGNORECASE),
    re.compile(re.escape(JOB_HUNT_COPILOT_REPO_URL), re.IGNORECASE),
    re.compile(r"\bresume\b", re.IGNORECASE),
    re.compile(r"\battachment\b", re.IGNORECASE),
    re.compile(r"\battachments\b", re.IGNORECASE),
)
MARKDOWN_BLOCK_PATTERNS = (
    re.compile(r"^\s*[-*]\s+", re.MULTILINE),
    re.compile(r"^\s*#+\s+", re.MULTILINE),
    re.compile(r"```"),
)


@dataclass(frozen=True)
class FollowUpCandidate:
    outreach_followup_plan_id: str
    original_outreach_message_id: str
    contact_id: str
    job_posting_id: str | None
    job_posting_contact_id: str | None
    recipient_email: str
    outreach_mode: str
    subject: str | None
    body_text: str
    thread_id: str | None
    delivery_tracking_id: str | None
    sent_at: str
    eligible_after: str
    followup_sequence: int
    contact_display_name: str | None
    contact_first_name: str | None
    contact_status: str | None
    company_name: str | None
    role_title: str | None
    jd_artifact_path: str | None
    tailored_resume_path: str | None
    plan_status: str
    retry_count: int
    next_retry_at: str | None


@dataclass(frozen=True)
class OriginalSendMetadata:
    source_path: str | None
    cc_emails: tuple[str, ...]
    message_id_header: str | None
    role_title: str | None
    company_name: str | None
    autonomous_origin: bool | None
    draft_origin_kind: str | None
    draft_posture_family: str | None


@dataclass(frozen=True)
class OriginalOutreachOrigin:
    status: str
    posture_family: str | None
    proof_source: str
    reason_code: str | None = None
    reason_message: str | None = None
    autonomous_origin: bool | None = None


@dataclass(frozen=True)
class ThreadInspectionResult:
    result: str
    checked_at: str
    has_inbound_reply: bool = False
    has_bounce: bool = False
    has_later_outbound: bool = False
    temporary_failure: bool = False
    reason_code: str | None = None
    message: str | None = None
    evidence: Mapping[str, Any] | None = None

    @property
    def safe_to_send(self) -> bool:
        return (
            self.result == "clear"
            and not self.has_inbound_reply
            and not self.has_bounce
            and not self.has_later_outbound
            and not self.temporary_failure
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "result": self.result,
            "checked_at": self.checked_at,
            "has_inbound_reply": self.has_inbound_reply,
            "has_bounce": self.has_bounce,
            "has_later_outbound": self.has_later_outbound,
            "temporary_failure": self.temporary_failure,
            "reason_code": self.reason_code,
            "message": self.message,
            "evidence": dict(self.evidence or {}),
        }


@dataclass(frozen=True)
class StructuredFollowUpDraft:
    paragraphs: tuple[str, ...]
    role_company_mode: str
    grounding_mode: str
    why_sent_summary: str | None = None


@dataclass(frozen=True)
class FollowUpDraftContext:
    candidate: FollowUpCandidate
    sequence: int
    posture_family: str
    role_title: str | None
    company_name: str | None
    salutation: str
    original_subject: str | None
    original_body_text: str
    prior_followups: tuple[str, ...]
    sender_evidence_summary: str
    role_company_summary: str
    thread_context_summary: str
    original_metadata: OriginalSendMetadata
    origin: OriginalOutreachOrigin


@dataclass(frozen=True)
class RenderedFollowUpDraft:
    body_text: str
    first_name_or_salutation: str
    draft_artifact_path: str
    review_evidence_artifact_path: str
    evidence: Mapping[str, Any]


@dataclass(frozen=True)
class FollowUpCycleResult:
    followup_cycle_run_id: str
    scheduler_name: str
    scheduler_type: str
    dry_run: bool
    auto_send_enabled: bool
    candidates_examined: int
    drafts_created: int
    messages_sent: int
    waiting_for_pacing_count: int
    skipped_replied: int
    skipped_bounced: int
    skipped_already_followed_up: int
    retryable_count: int
    blocked_count: int
    held_for_review: int
    started_at: str
    completed_at: str
    result: str
    artifact_paths: tuple[str, ...]
    last_checkpoint: str | None = None
    error_message: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "followup_cycle_run_id": self.followup_cycle_run_id,
            "scheduler_name": self.scheduler_name,
            "scheduler_type": self.scheduler_type,
            "dry_run": self.dry_run,
            "auto_send_enabled": self.auto_send_enabled,
            "candidates_examined": self.candidates_examined,
            "drafts_created": self.drafts_created,
            "messages_sent": self.messages_sent,
            "waiting_for_pacing_count": self.waiting_for_pacing_count,
            "skipped_replied": self.skipped_replied,
            "skipped_bounced": self.skipped_bounced,
            "skipped_already_followed_up": self.skipped_already_followed_up,
            "retryable_count": self.retryable_count,
            "blocked_count": self.blocked_count,
            "held_for_review": self.held_for_review,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "result": self.result,
            "artifact_paths": list(self.artifact_paths),
            "last_checkpoint": self.last_checkpoint,
            "error_message": self.error_message,
        }


class FollowUpThreadInspector(Protocol):
    def inspect_thread(
        self,
        candidate: FollowUpCandidate,
        *,
        current_time: str,
    ) -> ThreadInspectionResult:
        raise NotImplementedError


class FollowUpSender(Protocol):
    def send_followup(
        self,
        candidate: FollowUpCandidate,
        *,
        body_text: str,
    ) -> SendAttemptOutcome:
        raise NotImplementedError


class FollowUpDraftRenderer(Protocol):
    def render_followup(
        self,
        context: FollowUpDraftContext,
        *,
        current_time: str,
    ) -> StructuredFollowUpDraft:
        raise NotImplementedError


class GmailThreadInspector:
    def __init__(
        self,
        paths: ProjectPaths,
        *,
        service_factory: object | None = None,
        sender_email: str | None = None,
    ) -> None:
        self._paths = paths
        self._service_factory = service_factory
        self._sender_email = _normalize_email(sender_email) or _load_sender_email(paths)

    def inspect_thread(
        self,
        candidate: FollowUpCandidate,
        *,
        current_time: str,
    ) -> ThreadInspectionResult:
        if not candidate.thread_id:
            return ThreadInspectionResult(
                result="unknown",
                checked_at=current_time,
                reason_code=SKIP_REASON_MISSING_THREAD_CONTEXT,
                message="Original outreach message has no Gmail thread id.",
            )
        if not self._sender_email:
            return ThreadInspectionResult(
                result="unknown",
                checked_at=current_time,
                reason_code=SKIP_REASON_MISSING_SENDER_IDENTITY,
                message="Configured sender email could not be determined for thread classification.",
            )
        try:
            service = self._build_service()
            thread = (
                service.users()
                .threads()
                .get(
                    userId="me",
                    id=candidate.thread_id,
                    format="metadata",
                    metadataHeaders=["From", "To", "Cc", "Date", "Subject", "Message-ID"],
                )
                .execute()
            )
        except Exception as exc:
            return ThreadInspectionResult(
                result="unknown",
                checked_at=current_time,
                temporary_failure=True,
                reason_code="gmail_thread_check_failed",
                message=str(exc),
            )

        original_dt = _parse_iso_datetime(candidate.sent_at)
        post_original_messages: list[dict[str, Any]] = []
        for raw_message in thread.get("messages", []) or []:
            if not isinstance(raw_message, dict):
                continue
            message_dt = _gmail_message_datetime(raw_message)
            if message_dt is None or message_dt <= original_dt:
                continue
            headers = _gmail_headers(raw_message)
            from_header = headers.get("from", "")
            subject = headers.get("subject", "")
            from_email = _normalize_email(_extract_first_email(from_header) or from_header)
            is_sender = from_email == self._sender_email
            post_original_messages.append(
                {
                    "gmail_message_id": raw_message.get("id"),
                    "from": from_header,
                    "from_email": from_email,
                    "subject": subject,
                    "is_sender": is_sender,
                    "message_at": _isoformat_utc(message_dt),
                }
            )

        sender_messages = [message for message in post_original_messages if message["is_sender"]]
        expected_prior_outbound_count = max(candidate.followup_sequence - 1, 0)
        has_later_outbound = len(sender_messages) > expected_prior_outbound_count
        has_inbound_reply = any(not message["is_sender"] for message in post_original_messages)
        has_bounce = any(
            BOUNCE_SENDER_PATTERN.search(str(message.get("from", "")))
            or ("delivery" in str(message.get("subject", "")).lower() and "fail" in str(message.get("subject", "")).lower())
            for message in post_original_messages
        )
        if has_bounce:
            return ThreadInspectionResult(
                result="bounced",
                checked_at=current_time,
                has_bounce=True,
                evidence={"messages": post_original_messages},
            )
        if has_inbound_reply:
            return ThreadInspectionResult(
                result="replied",
                checked_at=current_time,
                has_inbound_reply=True,
                evidence={"messages": post_original_messages},
            )
        if has_later_outbound:
            return ThreadInspectionResult(
                result="already_followed_up",
                checked_at=current_time,
                has_later_outbound=True,
                evidence={
                    "messages": post_original_messages,
                    "sender_message_count": len(sender_messages),
                    "expected_prior_outbound_count": expected_prior_outbound_count,
                },
            )
        return ThreadInspectionResult(
            result="clear",
            checked_at=current_time,
            evidence={
                "messages": post_original_messages,
                "sender_message_count": len(sender_messages),
                "expected_prior_outbound_count": expected_prior_outbound_count,
            },
        )

    def _build_service(self) -> Any:
        if self._service_factory is not None:
            return self._service_factory()
        from .gmail_alerts import _build_gmail_service

        return _build_gmail_service(self._paths)


class GmailSameThreadFollowUpSender:
    def __init__(
        self,
        paths: ProjectPaths,
        *,
        service_factory: object | None = None,
    ) -> None:
        self._paths = paths
        self._service_factory = service_factory

    def send_followup(
        self,
        candidate: FollowUpCandidate,
        *,
        body_text: str,
    ) -> SendAttemptOutcome:
        if not candidate.thread_id:
            return SendAttemptOutcome(
                outcome=SEND_OUTCOME_FAILED,
                reason_code=SKIP_REASON_MISSING_THREAD_CONTEXT,
                message="Cannot send follow-up without original Gmail thread id.",
            )
        try:
            service = self._build_service()
            original_metadata = _load_original_send_metadata(self._paths, candidate)
            mime_message = EmailMessage()
            mime_message["To"] = candidate.recipient_email
            if original_metadata.cc_emails:
                mime_message["Cc"] = ", ".join(original_metadata.cc_emails)
            if candidate.subject:
                mime_message["Subject"] = candidate.subject
            if original_metadata.message_id_header:
                mime_message["In-Reply-To"] = original_metadata.message_id_header
                mime_message["References"] = original_metadata.message_id_header
            mime_message.set_content(body_text)
            raw_payload = base64.urlsafe_b64encode(mime_message.as_bytes()).decode("ascii")
            response = (
                service.users()
                .messages()
                .send(
                    userId="me",
                    body={"raw": raw_payload, "threadId": candidate.thread_id},
                )
                .execute()
            )
        except Exception as exc:
            return SendAttemptOutcome(
                outcome=SEND_OUTCOME_FAILED,
                reason_code="gmail_followup_send_failed",
                message=str(exc),
            )
        delivery_tracking_id = _normalize_optional_text(response.get("id"))
        if delivery_tracking_id is None:
            return SendAttemptOutcome(
                outcome=SEND_OUTCOME_AMBIGUOUS,
                reason_code="gmail_missing_message_id",
                message="Gmail follow-up send returned no message id.",
            )
        return SendAttemptOutcome(
            outcome=SEND_OUTCOME_SENT,
            thread_id=_normalize_optional_text(response.get("threadId")) or candidate.thread_id,
            delivery_tracking_id=delivery_tracking_id,
            sent_at=_gmail_sent_at_from_response(response),
        )

    def _build_service(self) -> Any:
        if self._service_factory is not None:
            return self._service_factory()
        from .gmail_alerts import _build_gmail_service

        return _build_gmail_service(self._paths)


class CodexFollowUpDraftRenderer:
    def __init__(
        self,
        *,
        project_root: Path | str,
        codex_bin: str | None = None,
        model: str | None = None,
    ) -> None:
        self._paths = ProjectPaths.from_root(project_root)
        self._codex_bin = codex_bin or _resolve_codex_bin()
        self._model = model

    def render_followup(
        self,
        context: FollowUpDraftContext,
        *,
        current_time: str,
    ) -> StructuredFollowUpDraft:
        payload = _run_followup_codex_payload(
            self._paths,
            codex_bin=self._codex_bin,
            model=self._model,
            context=context,
            current_time=current_time,
        )
        paragraphs = tuple(_normalize_paragraph_text(paragraph) for paragraph in payload.get("paragraphs", []))
        if len(paragraphs) < 2 or len(paragraphs) > 3 or any(not paragraph for paragraph in paragraphs):
            raise FollowUpDraftingError("Follow-up payload must contain 2 or 3 non-empty paragraphs.")
        role_company_mode = str(payload.get("role_company_mode") or "").strip()
        grounding_mode = str(payload.get("grounding_mode") or "").strip()
        if role_company_mode not in {"explicit", "thread_implied"}:
            raise FollowUpDraftingError("Follow-up payload returned invalid role_company_mode.")
        if grounding_mode not in {
            "original_email_only",
            "original_email_plus_prior_followups",
            "original_outreach_context_fallback",
        }:
            raise FollowUpDraftingError("Follow-up payload returned invalid grounding_mode.")
        why_sent_summary = _normalize_optional_text(payload.get("why_sent_summary"))
        return StructuredFollowUpDraft(
            paragraphs=paragraphs,
            role_company_mode=role_company_mode,
            grounding_mode=grounding_mode,
            why_sent_summary=why_sent_summary,
        )


class FollowUpDraftingError(RuntimeError):
    pass


def run_followup_cycle(
    connection: sqlite3.Connection,
    *,
    project_root: Path | str,
    current_time: str | None = None,
    dry_run: bool = True,
    thread_inspector: FollowUpThreadInspector | None = None,
    sender: FollowUpSender | None = None,
    renderer: FollowUpDraftRenderer | None = None,
    scheduler_name: str = FOLLOWUP_SCHEDULER_NAME,
    scheduler_type: str = FOLLOWUP_SCHEDULER_TYPE,
    batch_size: int | None = None,
    role_targeted_priority_checker: Callable[[sqlite3.Connection, str], bool] | None = None,
) -> FollowUpCycleResult:
    paths = ProjectPaths.from_root(project_root)
    effective_time = current_time or now_utc_iso()
    started_at = effective_time
    cycle_run_id = new_canonical_id("followup_cycle_runs")
    resolved_batch_size = batch_size or FOLLOWUP_DRY_RUN_BATCH_SIZE
    resolved_inspector = thread_inspector or GmailThreadInspector(paths)
    resolved_sender = sender or GmailSameThreadFollowUpSender(paths)
    resolved_renderer = renderer or CodexFollowUpDraftRenderer(project_root=paths.project_root)
    resolved_role_targeted_priority_checker = role_targeted_priority_checker or (
        lambda conn, timestamp: _role_targeted_priority_exists_now(
            conn,
            project_root=paths.project_root,
            current_time=timestamp,
        )
    )
    followup_auto_send_available = _followup_auto_send_enabled(connection)
    auto_send_enabled = (not dry_run) and followup_auto_send_available
    counts = {
        "candidates_examined": 0,
        "drafts_created": 0,
        "messages_sent": 0,
        "waiting_for_pacing_count": 0,
        "skipped_replied": 0,
        "skipped_bounced": 0,
        "skipped_already_followed_up": 0,
        "retryable_count": 0,
        "blocked_count": 0,
        "held_for_review": 0,
    }
    artifact_paths: list[str] = []
    last_checkpoint: str | None = None
    result = "success"
    error_message: str | None = None

    try:
        _materialize_candidate_plans(
            connection,
            paths=paths,
            current_time=effective_time,
            limit=resolved_batch_size,
        )
        if followup_auto_send_available:
            _release_auto_send_disabled_holds(connection, current_time=effective_time)
            _release_missing_sender_identity_holds(connection, current_time=effective_time)
        candidates = _load_candidate_plans(connection, current_time=effective_time, limit=resolved_batch_size)
        for candidate in candidates:
            counts["candidates_examined"] += 1
            last_checkpoint = candidate.outreach_followup_plan_id

            if not _is_due_now(candidate, effective_time):
                continue

            decision = _evaluate_candidate_stop_conditions(
                connection,
                paths,
                candidate,
                current_time=effective_time,
            )
            if decision is not None:
                _apply_stop_decision(
                    connection,
                    paths,
                    candidate,
                    decision,
                    effective_time,
                    dry_run=dry_run,
                    artifact_paths=artifact_paths,
                )
                _increment_count_for_reason(counts, decision["reason_code"])
                continue

            pre_draft_check = resolved_inspector.inspect_thread(candidate, current_time=effective_time)
            if not pre_draft_check.safe_to_send:
                _handle_thread_block(
                    connection,
                    paths,
                    candidate,
                    pre_draft_check,
                    effective_time,
                    dry_run=dry_run,
                    counts=counts,
                    artifact_paths=artifact_paths,
                )
                continue

            try:
                rendered = render_followup_draft(
                    connection,
                    paths,
                    candidate,
                    current_time=effective_time,
                    renderer=resolved_renderer,
                    thread_check=pre_draft_check,
                    dry_run=dry_run,
                )
            except FollowUpDraftingError as exc:
                if _is_codex_outage_error(str(exc)):
                    artifact_path = _pause_followup_auto_send_for_codex_outage(
                        connection,
                        paths=paths,
                        candidate=candidate,
                        current_time=effective_time,
                        message=str(exc),
                    )
                    artifact_paths.append(artifact_path)
                    counts["blocked_count"] += 1
                    result = "codex_unavailable"
                    error_message = str(exc)
                    break
                _handle_draft_failure(
                    connection,
                    paths,
                    candidate,
                    effective_time,
                    message=str(exc),
                    counts=counts,
                    artifact_paths=artifact_paths,
                )
                continue

            counts["drafts_created"] += 1
            artifact_paths.extend([rendered.draft_artifact_path, rendered.review_evidence_artifact_path])

            if dry_run:
                _mark_plan_status(
                    connection,
                    candidate.outreach_followup_plan_id,
                    PLAN_STATUS_DRY_RUN_READY,
                    effective_time,
                    draft_artifact_path=rendered.draft_artifact_path,
                    review_evidence_artifact_path=rendered.review_evidence_artifact_path,
                    reply_check=pre_draft_check,
                )
                continue

            if not auto_send_enabled:
                _mark_plan_status(
                    connection,
                    candidate.outreach_followup_plan_id,
                    PLAN_STATUS_HELD_FOR_REVIEW,
                    effective_time,
                    reason_code=SKIP_REASON_AUTO_SEND_DISABLED,
                    draft_artifact_path=rendered.draft_artifact_path,
                    review_evidence_artifact_path=rendered.review_evidence_artifact_path,
                    reply_check=pre_draft_check,
                )
                counts["held_for_review"] += 1
                continue

            if resolved_role_targeted_priority_checker(connection, effective_time):
                _mark_plan_status(
                    connection,
                    candidate.outreach_followup_plan_id,
                    PLAN_STATUS_WAITING_FOR_PACING,
                    effective_time,
                    reason_code=SKIP_REASON_ROLE_TARGETED_PRIORITY,
                    draft_artifact_path=rendered.draft_artifact_path,
                    review_evidence_artifact_path=rendered.review_evidence_artifact_path,
                    reply_check=pre_draft_check,
                )
                counts["waiting_for_pacing_count"] += 1
                continue

            pacing = _evaluate_global_pacing(connection, candidate, current_time=effective_time)
            if not pacing["allowed"]:
                _mark_plan_status(
                    connection,
                    candidate.outreach_followup_plan_id,
                    PLAN_STATUS_WAITING_FOR_PACING,
                    effective_time,
                    reason_code=SKIP_REASON_WAITING_FOR_PACING,
                    draft_artifact_path=rendered.draft_artifact_path,
                    review_evidence_artifact_path=rendered.review_evidence_artifact_path,
                    reply_check=pre_draft_check,
                )
                counts["waiting_for_pacing_count"] += 1
                continue

            pre_send_check = resolved_inspector.inspect_thread(candidate, current_time=effective_time)
            if not pre_send_check.safe_to_send:
                _handle_thread_block(
                    connection,
                    paths,
                    candidate,
                    pre_send_check,
                    effective_time,
                    dry_run=dry_run,
                    counts=counts,
                    artifact_paths=artifact_paths,
                )
                continue

            _mark_plan_status(
                connection,
                candidate.outreach_followup_plan_id,
                PLAN_STATUS_AGENT_REVIEWED,
                effective_time,
                draft_artifact_path=rendered.draft_artifact_path,
                review_evidence_artifact_path=rendered.review_evidence_artifact_path,
                reply_check=pre_send_check,
                agent_reviewed_at=effective_time,
            )
            send_outcome = resolved_sender.send_followup(candidate, body_text=rendered.body_text)
            if send_outcome.outcome == SEND_OUTCOME_SENT:
                _persist_successful_followup_send(
                    connection,
                    candidate,
                    rendered,
                    send_outcome,
                    current_time=effective_time,
                )
                counts["messages_sent"] += 1
                rollout_cap_reached = _increment_initial_rollout_count(connection, effective_time)
                if rollout_cap_reached:
                    artifact_paths.append(
                        _write_rollout_pause_packet(
                            connection,
                            paths,
                            current_time=effective_time,
                        )
                    )
                break
            if send_outcome.outcome == SEND_OUTCOME_AMBIGUOUS:
                _mark_plan_status(
                    connection,
                    candidate.outreach_followup_plan_id,
                    PLAN_STATUS_AMBIGUOUS,
                    effective_time,
                    reason_code=SKIP_REASON_AMBIGUOUS_SEND,
                    draft_artifact_path=rendered.draft_artifact_path,
                    review_evidence_artifact_path=rendered.review_evidence_artifact_path,
                    reply_check=pre_send_check,
                )
                counts["blocked_count"] += 1
                artifact_paths.append(
                    _write_followup_review_packet(
                        paths,
                        candidate,
                        effective_time,
                        SKIP_REASON_AMBIGUOUS_SEND,
                        send_outcome.message or "Gmail send state is ambiguous.",
                        rendered,
                        pre_send_check,
                    )
                )
                continue
            _handle_failed_send(
                connection,
                paths,
                candidate,
                rendered,
                send_outcome,
                pre_send_check,
                effective_time,
                counts,
                artifact_paths,
            )
    except Exception as exc:  # pragma: no cover - outer defensive boundary
        result = "error"
        error_message = str(exc)
        counts["blocked_count"] += 1

    completed_at = now_utc_iso()
    _record_cycle_run(
        connection,
        followup_cycle_run_id=cycle_run_id,
        scheduler_name=scheduler_name,
        scheduler_type=scheduler_type,
        started_at=started_at,
        completed_at=completed_at,
        result=result,
        last_checkpoint=last_checkpoint,
        error_message=error_message,
        counts=counts,
    )
    return FollowUpCycleResult(
        followup_cycle_run_id=cycle_run_id,
        scheduler_name=scheduler_name,
        scheduler_type=scheduler_type,
        dry_run=dry_run,
        auto_send_enabled=auto_send_enabled,
        artifact_paths=tuple(artifact_paths),
        started_at=started_at,
        completed_at=completed_at,
        result=result,
        last_checkpoint=last_checkpoint,
        error_message=error_message,
        **counts,
    )


def render_followup_draft(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    candidate: FollowUpCandidate,
    *,
    current_time: str,
    renderer: FollowUpDraftRenderer,
    thread_check: ThreadInspectionResult,
    dry_run: bool,
) -> RenderedFollowUpDraft:
    if not _normalize_optional_text(candidate.body_text):
        raise FollowUpDraftingError("Original sent email body is missing.")
    original_metadata = _load_original_send_metadata(paths, candidate)
    origin = _classify_original_outreach_origin(connection, paths, candidate, original_metadata)
    if origin.status != "codex":
        raise FollowUpDraftingError(origin.reason_message or "Original outreach thread is not eligible for Codex follow-up.")
    role_choice = _resolve_role_company(candidate, original_metadata)
    role_title = role_choice["role_title"]
    company_name = role_choice["company_name"]
    salutation = _resolve_salutation(candidate)
    prior_followups = _load_prior_sent_followups(connection, candidate.original_outreach_message_id)
    sender_evidence_summary = _build_sender_evidence_summary(candidate.body_text)
    role_company_summary = _build_role_company_summary(role_title, company_name, sequence=candidate.followup_sequence)
    thread_context_summary = _build_thread_context_summary(candidate, prior_followups)

    context = FollowUpDraftContext(
        candidate=candidate,
        sequence=candidate.followup_sequence,
        posture_family=origin.posture_family or _infer_posture_from_body(candidate.subject, candidate.body_text),
        role_title=role_title,
        company_name=company_name,
        salutation=salutation,
        original_subject=candidate.subject,
        original_body_text=candidate.body_text,
        prior_followups=prior_followups,
        sender_evidence_summary=sender_evidence_summary,
        role_company_summary=role_company_summary,
        thread_context_summary=thread_context_summary,
        original_metadata=original_metadata,
        origin=origin,
    )
    if context.posture_family not in {POSTURE_TECHNICAL, POSTURE_MANAGERIAL}:
        raise FollowUpDraftingError("Could not classify the original thread into a supported follow-up posture.")

    structured = renderer.render_followup(context, current_time=current_time)
    body_text = _assemble_followup_body(
        salutation=salutation,
        paragraphs=structured.paragraphs,
        followup_sequence=candidate.followup_sequence,
    )
    if not validate_followup_body(body_text, followup_sequence=candidate.followup_sequence):
        raise FollowUpDraftingError("Rendered follow-up failed deterministic body validation.")

    artifact_dir = _followup_artifact_dir(paths, candidate)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    draft_path = artifact_dir / "followup_draft.md"
    review_path = artifact_dir / "followup_review_evidence.json"
    draft_path.write_text(body_text + "\n", encoding="utf-8")
    why_sent = {
        "sequence_step": candidate.followup_sequence,
        "posture_family": context.posture_family,
        "grounding_mode": structured.grounding_mode,
        "role_company_mode": structured.role_company_mode,
        "prior_followup_count": len(prior_followups),
        "origin_proof_source": origin.proof_source,
        "why_sent_summary": structured.why_sent_summary,
    }
    evidence = {
        "dry_run": dry_run,
        "original_outreach_message_id": candidate.original_outreach_message_id,
        "outreach_followup_plan_id": candidate.outreach_followup_plan_id,
        "followup_sequence": candidate.followup_sequence,
        "posture_family": context.posture_family,
        "role_title": role_title,
        "company_name": company_name,
        "salutation": salutation,
        "role_company_summary": role_company_summary,
        "sender_evidence_summary": sender_evidence_summary,
        "thread_context_summary": thread_context_summary,
        "origin": {
            "status": origin.status,
            "proof_source": origin.proof_source,
            "autonomous_origin": origin.autonomous_origin,
        },
        "why_sent_this_followup": why_sent,
        "thread_check": thread_check.as_dict(),
    }
    write_json_contract(
        review_path,
        producer_component=FOLLOWUP_COMPONENT,
        result="success",
        linkage=ArtifactLinkage(
            job_posting_id=candidate.job_posting_id,
            contact_id=candidate.contact_id,
            outreach_message_id=candidate.original_outreach_message_id,
        ),
        payload=evidence,
        produced_at=current_time,
    )
    return RenderedFollowUpDraft(
        body_text=body_text,
        first_name_or_salutation=salutation,
        draft_artifact_path=str(paths.relative_to_root(draft_path)),
        review_evidence_artifact_path=str(paths.relative_to_root(review_path)),
        evidence=evidence,
    )


def validate_followup_body(body_text: str, *, followup_sequence: int | None = None) -> bool:
    normalized = body_text.strip()
    if not normalized:
        return False
    if not normalized.endswith("Best,\nAchyutaram Sonti"):
        return False
    if "https://www.linkedin.com" in normalized or "602-" in normalized or "asonti1@asu.edu" in normalized:
        return False
    if any(pattern.search(normalized) for pattern in PROHIBITED_LEAK_PATTERNS):
        return False
    if any(pattern.search(normalized) for pattern in MARKDOWN_BLOCK_PATTERNS):
        return False
    if "[snippet]" in normalized or "[/snippet]" in normalized:
        return False
    if followup_sequence == FOLLOWUP_MAX_SEQUENCE and FIXED_FINAL_TOUCH_SENTENCE not in normalized:
        return False
    if followup_sequence and followup_sequence < FOLLOWUP_MAX_SEQUENCE and FIXED_FINAL_TOUCH_SENTENCE in normalized:
        return False
    paragraphs = _extract_followup_body_paragraphs(normalized)
    if len(paragraphs) < 2 or len(paragraphs) > 3:
        return False
    return True


def build_followup_dashboard_summary(connection: sqlite3.Connection, *, current_time: str | None = None) -> dict[str, Any]:
    effective_time = current_time or now_utc_iso()
    due_now = 0
    for row in connection.execute(
        """
        SELECT outreach_followup_plan_id, original_outreach_message_id, contact_id, job_posting_id,
               plan_status, followup_sequence, eligible_after, retry_count, next_retry_at,
               COALESCE((SELECT om.recipient_email FROM outreach_messages om WHERE om.outreach_message_id = fp.original_outreach_message_id), '') AS recipient_email,
               COALESCE((SELECT om.outreach_mode FROM outreach_messages om WHERE om.outreach_message_id = fp.original_outreach_message_id), '') AS outreach_mode,
               COALESCE((SELECT om.subject FROM outreach_messages om WHERE om.outreach_message_id = fp.original_outreach_message_id), '') AS subject,
               COALESCE((SELECT om.body_text FROM outreach_messages om WHERE om.outreach_message_id = fp.original_outreach_message_id), '') AS body_text,
               (SELECT om.thread_id FROM outreach_messages om WHERE om.outreach_message_id = fp.original_outreach_message_id) AS thread_id,
               (SELECT om.delivery_tracking_id FROM outreach_messages om WHERE om.outreach_message_id = fp.original_outreach_message_id) AS delivery_tracking_id,
               (SELECT om.sent_at FROM outreach_messages om WHERE om.outreach_message_id = fp.original_outreach_message_id) AS sent_at,
               (SELECT c.display_name FROM contacts c WHERE c.contact_id = fp.contact_id) AS contact_display_name,
               (SELECT c.first_name FROM contacts c WHERE c.contact_id = fp.contact_id) AS contact_first_name,
               (SELECT c.contact_status FROM contacts c WHERE c.contact_id = fp.contact_id) AS contact_status
        FROM outreach_followup_plans fp
        WHERE fp.plan_status IN ('pending', 'dry_run_ready', 'agent_reviewed', 'retryable')
        """
    ).fetchall():
        candidate = FollowUpCandidate(
            outreach_followup_plan_id=str(row["outreach_followup_plan_id"]),
            original_outreach_message_id=str(row["original_outreach_message_id"]),
            contact_id=str(row["contact_id"]),
            job_posting_id=_normalize_optional_text(row["job_posting_id"]),
            job_posting_contact_id=None,
            recipient_email=str(row["recipient_email"]),
            outreach_mode=str(row["outreach_mode"]),
            subject=_normalize_optional_text(row["subject"]),
            body_text=str(row["body_text"] or ""),
            thread_id=_normalize_optional_text(row["thread_id"]),
            delivery_tracking_id=_normalize_optional_text(row["delivery_tracking_id"]),
            sent_at=str(row["sent_at"]),
            eligible_after=str(row["eligible_after"]),
            followup_sequence=int(row["followup_sequence"]),
            contact_display_name=_normalize_optional_text(row["contact_display_name"]),
            contact_first_name=_normalize_optional_text(row["contact_first_name"]),
            contact_status=_normalize_optional_text(row["contact_status"]),
            company_name=None,
            role_title=None,
            jd_artifact_path=None,
            tailored_resume_path=None,
            plan_status=str(row["plan_status"]),
            retry_count=int(row["retry_count"] or 0),
            next_retry_at=_normalize_optional_text(row["next_retry_at"]),
        )
        if _is_due_now(candidate, effective_time):
            due_now += 1
    waiting_for_pacing = connection.execute(
        "SELECT COUNT(*) FROM outreach_followup_plans WHERE plan_status = ?",
        (PLAN_STATUS_WAITING_FOR_PACING,),
    ).fetchone()[0]
    sent_today = _count_followups_sent_today(connection, effective_time)
    blocked_or_review = connection.execute(
        """
        SELECT COUNT(*) FROM outreach_followup_plans
        WHERE plan_status IN ('blocked', 'held_for_review', 'ambiguous')
        """,
    ).fetchone()[0]
    last_cycle = connection.execute(
        """
        SELECT started_at, result
        FROM followup_cycle_runs
        ORDER BY started_at DESC, followup_cycle_run_id DESC
        LIMIT 1
        """
    ).fetchone()
    return {
        "due_now": int(due_now),
        "waiting_for_pacing": int(waiting_for_pacing),
        "sent_today": int(sent_today),
        "blocked_or_review": int(blocked_or_review),
        "last_cycle_at": last_cycle["started_at"] if last_cycle is not None else None,
        "last_cycle_result": last_cycle["result"] if last_cycle is not None else None,
    }


def _materialize_candidate_plans(
    connection: sqlite3.Connection,
    *,
    paths: ProjectPaths,
    current_time: str,
    limit: int,
) -> None:
    del limit
    rows = connection.execute(
        """
        SELECT om.outreach_message_id, om.contact_id, om.job_posting_id, om.sent_at,
               om.recipient_email, om.subject, om.body_text, om.thread_id,
               c.display_name, c.first_name, c.contact_status,
               jp.company_name, jp.role_title, jp.jd_artifact_path
        FROM outreach_messages om
        JOIN contacts c
          ON c.contact_id = om.contact_id
        LEFT JOIN job_postings jp
          ON jp.job_posting_id = om.job_posting_id
        WHERE om.outreach_mode = ?
          AND om.message_status = ?
          AND om.sent_at IS NOT NULL
          AND TRIM(om.sent_at) <> ''
        ORDER BY om.sent_at DESC, om.outreach_message_id DESC
        """,
        (
            OUTREACH_MODE_ROLE_TARGETED,
            MESSAGE_STATUS_SENT,
        ),
    ).fetchall()

    newest_eligible_per_contact: dict[str, str] = {}
    origin_cache: dict[str, OriginalOutreachOrigin] = {}
    metadata_cache: dict[str, OriginalSendMetadata] = {}

    for row in rows:
        candidate = _materialization_candidate_from_row(row)
        metadata = _load_original_send_metadata(paths, candidate)
        origin = _classify_original_outreach_origin(connection, paths, candidate, metadata)
        origin_cache[candidate.original_outreach_message_id] = origin
        metadata_cache[candidate.original_outreach_message_id] = metadata
        if origin.status == "codex":
            newest_eligible_per_contact.setdefault(candidate.contact_id, candidate.original_outreach_message_id)

    for row in rows:
        candidate = _materialization_candidate_from_row(row)
        origin = origin_cache[candidate.original_outreach_message_id]
        metadata = metadata_cache[candidate.original_outreach_message_id]
        existing_rows = _load_plan_rows_for_original(connection, candidate.original_outreach_message_id)
        if origin.status != "codex":
            _ensure_terminal_skipped_plan(
                connection,
                candidate,
                existing_rows=existing_rows,
                current_time=current_time,
                reason_code=origin.reason_code or SKIP_REASON_UNKNOWN_ORIGIN,
            )
            continue
        if newest_eligible_per_contact.get(candidate.contact_id) != candidate.original_outreach_message_id:
            _ensure_terminal_skipped_plan(
                connection,
                candidate,
                existing_rows=existing_rows,
                current_time=current_time,
                reason_code=SKIP_REASON_NEWER_THREAD_PREFERRED,
            )
            continue
        if metadata.cc_emails:
            _ensure_terminal_skipped_plan(
                connection,
                candidate,
                existing_rows=existing_rows,
                current_time=current_time,
                reason_code=SKIP_REASON_MULTI_RECIPIENT,
            )
            continue
        if _reopen_pre_cutover_archive_skips(
            connection,
            existing_rows=existing_rows,
            current_time=current_time,
        ):
            existing_rows = _load_plan_rows_for_original(connection, candidate.original_outreach_message_id)
        next_step = _determine_next_sequence(existing_rows)
        if next_step is None:
            continue
        if any(int(plan["followup_sequence"]) == next_step for plan in existing_rows):
            continue
        base_sent_at = _base_sent_at_for_next_sequence(candidate, existing_rows)
        eligible_after = _eligible_after(base_sent_at, next_step, FOLLOWUP_BUSINESS_TIMEZONE)
        with connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO outreach_followup_plans (
                  outreach_followup_plan_id, original_outreach_message_id, contact_id,
                  job_posting_id, plan_status, followup_sequence, eligible_after,
                  gmail_thread_id_snapshot, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_canonical_id("outreach_followup_plans"),
                    candidate.original_outreach_message_id,
                    candidate.contact_id,
                    candidate.job_posting_id,
                    PLAN_STATUS_PENDING,
                    next_step,
                    eligible_after,
                    candidate.thread_id,
                    current_time,
                    current_time,
                ),
            )


def _materialization_candidate_from_row(row: sqlite3.Row) -> FollowUpCandidate:
    return FollowUpCandidate(
        outreach_followup_plan_id="",
        original_outreach_message_id=str(row["outreach_message_id"]),
        contact_id=str(row["contact_id"]),
        job_posting_id=_normalize_optional_text(row["job_posting_id"]),
        job_posting_contact_id=None,
        recipient_email=str(row["recipient_email"]),
        outreach_mode=OUTREACH_MODE_ROLE_TARGETED,
        subject=_normalize_optional_text(row["subject"]),
        body_text=str(row["body_text"] or ""),
        thread_id=_normalize_optional_text(row["thread_id"]),
        delivery_tracking_id=None,
        sent_at=str(row["sent_at"]),
        eligible_after=str(row["sent_at"]),
        followup_sequence=1,
        contact_display_name=_normalize_optional_text(row["display_name"]),
        contact_first_name=_normalize_optional_text(row["first_name"]),
        contact_status=_normalize_optional_text(row["contact_status"]),
        company_name=_normalize_optional_text(row["company_name"]),
        role_title=_normalize_optional_text(row["role_title"]),
        jd_artifact_path=_normalize_optional_text(row["jd_artifact_path"]),
        tailored_resume_path=None,
        plan_status=PLAN_STATUS_PENDING,
        retry_count=0,
        next_retry_at=None,
    )


def _determine_next_sequence(existing_rows: Sequence[sqlite3.Row]) -> int | None:
    if not existing_rows:
        return FOLLOWUP_SEQUENCE_START
    max_sent_sequence = 0
    for row in existing_rows:
        sequence = int(row["followup_sequence"])
        status = str(row["plan_status"])
        if status == PLAN_STATUS_SENT:
            max_sent_sequence = max(max_sent_sequence, sequence)
            continue
        return None
    next_sequence = max_sent_sequence + 1
    if next_sequence > FOLLOWUP_MAX_SEQUENCE:
        return None
    return next_sequence


FOLLOWUP_SEQUENCE_START = 1


def _base_sent_at_for_next_sequence(candidate: FollowUpCandidate, existing_rows: Sequence[sqlite3.Row]) -> str:
    if not existing_rows:
        return candidate.sent_at
    sent_rows = [row for row in existing_rows if str(row["plan_status"]) == PLAN_STATUS_SENT and row["sent_at"]]
    if not sent_rows:
        return candidate.sent_at
    latest = max(sent_rows, key=lambda row: (str(row["sent_at"]), int(row["followup_sequence"])))
    return str(latest["sent_at"])


def _ensure_terminal_skipped_plan(
    connection: sqlite3.Connection,
    candidate: FollowUpCandidate,
    *,
    existing_rows: Sequence[sqlite3.Row],
    current_time: str,
    reason_code: str,
) -> None:
    if existing_rows:
        active_rows = [row for row in existing_rows if str(row["plan_status"]) not in TERMINAL_PLAN_STATUSES]
        if not active_rows:
            return
        with connection:
            connection.executemany(
                """
                UPDATE outreach_followup_plans
                SET plan_status = ?, last_skip_reason = ?, last_evaluated_at = ?, updated_at = ?
                WHERE outreach_followup_plan_id = ?
                """,
                [
                    (
                        PLAN_STATUS_SKIPPED,
                        reason_code,
                        current_time,
                        current_time,
                        str(row["outreach_followup_plan_id"]),
                    )
                    for row in active_rows
                ],
            )
        return
    eligible_after = _eligible_after(candidate.sent_at, FOLLOWUP_SEQUENCE_START, FOLLOWUP_BUSINESS_TIMEZONE)
    with connection:
        connection.execute(
            """
            INSERT OR IGNORE INTO outreach_followup_plans (
              outreach_followup_plan_id, original_outreach_message_id, contact_id,
              job_posting_id, plan_status, followup_sequence, eligible_after,
              gmail_thread_id_snapshot, last_skip_reason, last_evaluated_at,
              created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_canonical_id("outreach_followup_plans"),
                candidate.original_outreach_message_id,
                candidate.contact_id,
                candidate.job_posting_id,
                PLAN_STATUS_SKIPPED,
                FOLLOWUP_SEQUENCE_START,
                eligible_after,
                candidate.thread_id,
                reason_code,
                current_time,
                current_time,
                current_time,
            ),
        )


def _reopen_pre_cutover_archive_skips(
    connection: sqlite3.Connection,
    *,
    existing_rows: Sequence[sqlite3.Row],
    current_time: str,
) -> int:
    reopenable_rows = [
        row
        for row in existing_rows
        if str(row["plan_status"]) == PLAN_STATUS_SKIPPED
        and str(row["last_skip_reason"] or "") == SKIP_REASON_POSTING_ARCHIVED_PRE_CUTOVER
    ]
    if not reopenable_rows:
        return 0
    reopen_sequence = min(int(row["followup_sequence"]) for row in reopenable_rows)
    with connection:
        cursor = connection.executemany(
            """
            UPDATE outreach_followup_plans
            SET plan_status = ?,
                last_skip_reason = NULL,
                retry_count = 0,
                next_retry_at = NULL,
                draft_artifact_path = NULL,
                review_evidence_artifact_path = NULL,
                last_evaluated_at = ?,
                updated_at = ?
            WHERE outreach_followup_plan_id = ?
            """,
            [
                (
                    PLAN_STATUS_PENDING,
                    current_time,
                    current_time,
                    str(row["outreach_followup_plan_id"]),
                )
                for row in reopenable_rows
                if int(row["followup_sequence"]) == reopen_sequence
            ],
        )
    return int(cursor.rowcount or 0)


def _load_plan_rows_for_original(
    connection: sqlite3.Connection,
    original_outreach_message_id: str,
) -> tuple[sqlite3.Row, ...]:
    rows = connection.execute(
        """
        SELECT outreach_followup_plan_id, plan_status, followup_sequence, sent_at, last_skip_reason
        FROM outreach_followup_plans
        WHERE original_outreach_message_id = ?
        ORDER BY followup_sequence ASC, outreach_followup_plan_id ASC
        """,
        (original_outreach_message_id,),
    ).fetchall()
    return tuple(rows)


def _load_candidate_plans(
    connection: sqlite3.Connection,
    *,
    current_time: str,
    limit: int,
) -> tuple[FollowUpCandidate, ...]:
    rows = connection.execute(
        """
        SELECT
          fp.outreach_followup_plan_id,
          fp.original_outreach_message_id,
          fp.contact_id,
          fp.job_posting_id,
          fp.plan_status,
          fp.followup_sequence,
          fp.eligible_after,
          fp.retry_count,
          fp.next_retry_at,
          om.job_posting_contact_id,
          om.recipient_email,
          om.outreach_mode,
          om.subject,
          om.body_text,
          om.thread_id,
          om.delivery_tracking_id,
          om.sent_at,
          c.display_name AS contact_display_name,
          c.first_name AS contact_first_name,
          c.contact_status,
          jp.company_name,
          jp.role_title,
          jp.jd_artifact_path
        FROM outreach_followup_plans fp
        JOIN outreach_messages om
          ON om.outreach_message_id = fp.original_outreach_message_id
        JOIN contacts c
          ON c.contact_id = fp.contact_id
        LEFT JOIN job_postings jp
          ON jp.job_posting_id = fp.job_posting_id
        WHERE fp.plan_status IN (?, ?, ?, ?, ?)
          AND (fp.next_retry_at IS NULL OR fp.next_retry_at <= ?)
        ORDER BY om.sent_at ASC, fp.followup_sequence ASC, fp.outreach_followup_plan_id ASC
        LIMIT ?
        """,
        (
            PLAN_STATUS_PENDING,
            PLAN_STATUS_DRY_RUN_READY,
            PLAN_STATUS_AGENT_REVIEWED,
            PLAN_STATUS_WAITING_FOR_PACING,
            PLAN_STATUS_RETRYABLE,
            current_time,
            limit,
        ),
    ).fetchall()
    return tuple(_candidate_from_row(row) for row in rows)


def _candidate_from_row(row: sqlite3.Row) -> FollowUpCandidate:
    return FollowUpCandidate(
        outreach_followup_plan_id=str(row["outreach_followup_plan_id"]),
        original_outreach_message_id=str(row["original_outreach_message_id"]),
        contact_id=str(row["contact_id"]),
        job_posting_id=_normalize_optional_text(row["job_posting_id"]),
        job_posting_contact_id=_normalize_optional_text(row["job_posting_contact_id"]),
        recipient_email=str(row["recipient_email"]),
        outreach_mode=str(row["outreach_mode"]),
        subject=_normalize_optional_text(row["subject"]),
        body_text=str(row["body_text"] or ""),
        thread_id=_normalize_optional_text(row["thread_id"]),
        delivery_tracking_id=_normalize_optional_text(row["delivery_tracking_id"]),
        sent_at=str(row["sent_at"]),
        eligible_after=str(row["eligible_after"]),
        followup_sequence=int(row["followup_sequence"]),
        contact_display_name=_normalize_optional_text(row["contact_display_name"]),
        contact_first_name=_normalize_optional_text(row["contact_first_name"]),
        contact_status=_normalize_optional_text(row["contact_status"]),
        company_name=_normalize_optional_text(row["company_name"]),
        role_title=_normalize_optional_text(row["role_title"]),
        jd_artifact_path=_normalize_optional_text(row["jd_artifact_path"]),
        tailored_resume_path=None,
        plan_status=str(row["plan_status"]),
        retry_count=int(row["retry_count"] or 0),
        next_retry_at=_normalize_optional_text(row["next_retry_at"]),
    )


def _evaluate_candidate_stop_conditions(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    candidate: FollowUpCandidate,
    *,
    current_time: str,
) -> dict[str, str] | None:
    del current_time
    if not _normalize_optional_text(candidate.body_text):
        return {"status": PLAN_STATUS_HELD_FOR_REVIEW, "reason_code": SKIP_REASON_MISSING_ORIGINAL_BODY}
    if _normalize_phrase(candidate.contact_status or "") in CONTACT_HARD_STOP_STATUSES:
        return {"status": PLAN_STATUS_SKIPPED, "reason_code": SKIP_REASON_CONTACT_HARD_STOP}
    if not candidate.thread_id:
        return {"status": PLAN_STATUS_HELD_FOR_REVIEW, "reason_code": SKIP_REASON_MISSING_THREAD_CONTEXT}
    metadata = _load_original_send_metadata(paths, candidate)
    if metadata.cc_emails:
        return {"status": PLAN_STATUS_SKIPPED, "reason_code": SKIP_REASON_MULTI_RECIPIENT}
    origin = _classify_original_outreach_origin(connection, paths, candidate, metadata)
    if origin.status != "codex":
        return {"status": PLAN_STATUS_SKIPPED, "reason_code": origin.reason_code or SKIP_REASON_UNKNOWN_ORIGIN}
    if _has_contact_reply_suppression(connection, candidate.contact_id):
        return {"status": PLAN_STATUS_SKIPPED, "reason_code": SKIP_REASON_CONTACT_REPLY_SUPPRESSION}
    if _has_delivery_event(connection, candidate, "bounced"):
        return {"status": PLAN_STATUS_SKIPPED, "reason_code": SKIP_REASON_BOUNCED}
    if _has_delivery_event(connection, candidate, "replied"):
        return {"status": PLAN_STATUS_SKIPPED, "reason_code": SKIP_REASON_REPLIED_IN_THREAD}
    if _has_existing_followup_evidence(connection, candidate):
        return {"status": PLAN_STATUS_SKIPPED, "reason_code": SKIP_REASON_ALREADY_FOLLOWED_UP}
    return None


def _has_contact_reply_suppression(connection: sqlite3.Connection, contact_id: str) -> bool:
    row = connection.execute(
        """
        SELECT 1
        FROM delivery_feedback_events dfe
        JOIN outreach_messages om
          ON om.outreach_message_id = dfe.outreach_message_id
        WHERE om.contact_id = ?
          AND dfe.event_state = 'replied'
        LIMIT 1
        """,
        (contact_id,),
    ).fetchone()
    return row is not None


def _has_delivery_event(connection: sqlite3.Connection, candidate: FollowUpCandidate, event_state: str) -> bool:
    row = connection.execute(
        """
        SELECT 1
        FROM delivery_feedback_events
        WHERE outreach_message_id = ?
          AND event_state = ?
        LIMIT 1
        """,
        (candidate.original_outreach_message_id, event_state),
    ).fetchone()
    return row is not None


def _has_existing_followup_evidence(connection: sqlite3.Connection, candidate: FollowUpCandidate) -> bool:
    allowed_prior_rows = connection.execute(
        """
        SELECT followup_outreach_message_id
        FROM outreach_followup_plans
        WHERE original_outreach_message_id = ?
          AND plan_status = ?
          AND followup_sequence < ?
          AND followup_outreach_message_id IS NOT NULL
        """,
        (
            candidate.original_outreach_message_id,
            PLAN_STATUS_SENT,
            candidate.followup_sequence,
        ),
    ).fetchall()
    allowed_prior_ids = {
        str(row["followup_outreach_message_id"])
        for row in allowed_prior_rows
        if row["followup_outreach_message_id"]
    }
    sent_rows = connection.execute(
        """
        SELECT om.outreach_message_id
        FROM outreach_messages om
        WHERE om.outreach_message_id <> ?
          AND om.message_status = ?
          AND om.outreach_mode IN ('follow_up', 'role_targeted_followup')
          AND (
            (om.thread_id IS NOT NULL AND om.thread_id = ?)
            OR (
              om.contact_id = ?
              AND COALESCE(om.job_posting_id, '') = COALESCE(?, '')
              AND om.sent_at > ?
            )
          )
        """,
        (
            candidate.original_outreach_message_id,
            MESSAGE_STATUS_SENT,
            candidate.thread_id,
            candidate.contact_id,
            candidate.job_posting_id,
            candidate.sent_at,
        ),
    ).fetchall()
    row = next(
        (
            candidate_row
            for candidate_row in sent_rows
            if str(candidate_row["outreach_message_id"]) not in allowed_prior_ids
        ),
        None,
    )
    return row is not None


def _apply_stop_decision(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    candidate: FollowUpCandidate,
    decision: Mapping[str, str],
    current_time: str,
    *,
    dry_run: bool,
    artifact_paths: list[str],
) -> None:
    _mark_plan_status(
        connection,
        candidate.outreach_followup_plan_id,
        decision["status"],
        current_time,
        reason_code=decision["reason_code"],
    )
    if not dry_run and decision["status"] in {PLAN_STATUS_BLOCKED, PLAN_STATUS_HELD_FOR_REVIEW, PLAN_STATUS_AMBIGUOUS}:
        artifact_paths.append(
            _write_followup_review_packet(
                paths,
                candidate,
                current_time,
                decision["reason_code"],
                _review_message_for_reason(decision["reason_code"]),
                None,
                None,
            )
        )


def _handle_thread_block(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    candidate: FollowUpCandidate,
    inspection: ThreadInspectionResult,
    current_time: str,
    *,
    dry_run: bool,
    counts: dict[str, int],
    artifact_paths: list[str],
) -> None:
    if inspection.has_bounce or inspection.result == "bounced":
        status = PLAN_STATUS_SKIPPED
        reason = SKIP_REASON_BOUNCED
        counts["skipped_bounced"] += 1
    elif inspection.has_inbound_reply or inspection.result == "replied":
        status = PLAN_STATUS_SKIPPED
        reason = SKIP_REASON_REPLIED_IN_THREAD
        counts["skipped_replied"] += 1
    elif inspection.has_later_outbound or inspection.result == "already_followed_up":
        status = PLAN_STATUS_SKIPPED
        reason = SKIP_REASON_ALREADY_FOLLOWED_UP
        counts["skipped_already_followed_up"] += 1
    elif inspection.temporary_failure:
        _schedule_retry(connection, candidate, current_time, inspection=inspection)
        counts["retryable_count"] += 1
        return
    else:
        status = PLAN_STATUS_HELD_FOR_REVIEW
        reason = inspection.reason_code or SKIP_REASON_MISSING_THREAD_CONTEXT
        counts["held_for_review"] += 1
        if not dry_run:
            artifact_paths.append(
                _write_followup_review_packet(
                    paths,
                    candidate,
                    current_time,
                    reason,
                    inspection.message or "Thread check did not produce a safe-to-send result.",
                    None,
                    inspection,
                )
            )
    _mark_plan_status(
        connection,
        candidate.outreach_followup_plan_id,
        status,
        current_time,
        reason_code=reason,
        reply_check=inspection,
    )


def _handle_draft_failure(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    candidate: FollowUpCandidate,
    current_time: str,
    *,
    message: str,
    counts: dict[str, int],
    artifact_paths: list[str],
) -> None:
    retry_count = candidate.retry_count + 1
    if retry_count < FOLLOWUP_DRAFT_RETRY_LIMIT:
        with connection:
            connection.execute(
                """
                UPDATE outreach_followup_plans
                SET plan_status = ?, last_skip_reason = ?, retry_count = ?, next_retry_at = ?,
                    last_evaluated_at = ?, updated_at = ?
                WHERE outreach_followup_plan_id = ?
                """,
                (
                    PLAN_STATUS_RETRYABLE,
                    SKIP_REASON_DRAFT_RETRY,
                    retry_count,
                    current_time,
                    current_time,
                    current_time,
                    candidate.outreach_followup_plan_id,
                ),
            )
        counts["retryable_count"] += 1
        return
    _mark_plan_status(
        connection,
        candidate.outreach_followup_plan_id,
        PLAN_STATUS_HELD_FOR_REVIEW,
        current_time,
        reason_code=SKIP_REASON_DRAFT_RETRY_EXHAUSTED,
    )
    counts["held_for_review"] += 1
    artifact_paths.append(
        _write_followup_review_packet(
            paths,
            candidate,
            current_time,
            SKIP_REASON_DRAFT_RETRY_EXHAUSTED,
            message,
            None,
            None,
        )
    )


def _handle_failed_send(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    candidate: FollowUpCandidate,
    rendered: RenderedFollowUpDraft,
    outcome: SendAttemptOutcome,
    inspection: ThreadInspectionResult,
    current_time: str,
    counts: dict[str, int],
    artifact_paths: list[str],
) -> None:
    retry_count = candidate.retry_count + 1
    if retry_count <= MAX_AUTOMATIC_TRANSIENT_SEND_RETRIES:
        next_retry_at = _isoformat_utc(_parse_iso_datetime(current_time) + timedelta(minutes=TRANSIENT_SEND_RETRY_COOLDOWN_MINUTES))
        with connection:
            connection.execute(
                """
                UPDATE outreach_followup_plans
                SET plan_status = ?, last_skip_reason = ?, retry_count = ?,
                    next_retry_at = ?, last_evaluated_at = ?, updated_at = ?
                WHERE outreach_followup_plan_id = ?
                """,
                (
                    PLAN_STATUS_RETRYABLE,
                    SKIP_REASON_TRANSIENT_RETRY,
                    retry_count,
                    next_retry_at,
                    current_time,
                    current_time,
                    candidate.outreach_followup_plan_id,
                ),
            )
        counts["retryable_count"] += 1
        return
    _mark_plan_status(
        connection,
        candidate.outreach_followup_plan_id,
        PLAN_STATUS_BLOCKED,
        current_time,
        reason_code=outcome.reason_code or "followup_send_failed",
        draft_artifact_path=rendered.draft_artifact_path,
        review_evidence_artifact_path=rendered.review_evidence_artifact_path,
        reply_check=inspection,
    )
    counts["blocked_count"] += 1
    artifact_paths.append(
        _write_followup_review_packet(
            paths,
            candidate,
            current_time,
            outcome.reason_code or "followup_send_failed",
            outcome.message or "Follow-up send failed.",
            rendered,
            inspection,
        )
    )


def _schedule_retry(
    connection: sqlite3.Connection,
    candidate: FollowUpCandidate,
    current_time: str,
    *,
    inspection: ThreadInspectionResult,
) -> None:
    retry_count = candidate.retry_count + 1
    status = PLAN_STATUS_RETRYABLE if retry_count <= MAX_AUTOMATIC_TRANSIENT_SEND_RETRIES else PLAN_STATUS_BLOCKED
    next_retry_at = None
    if status == PLAN_STATUS_RETRYABLE:
        next_retry_at = _isoformat_utc(_parse_iso_datetime(current_time) + timedelta(minutes=TRANSIENT_SEND_RETRY_COOLDOWN_MINUTES))
    with connection:
        connection.execute(
            """
            UPDATE outreach_followup_plans
            SET plan_status = ?, last_skip_reason = ?, retry_count = ?, next_retry_at = ?,
                last_evaluated_at = ?, last_reply_check_at = ?, last_reply_check_result = ?, updated_at = ?
            WHERE outreach_followup_plan_id = ?
            """,
            (
                status,
                SKIP_REASON_TRANSIENT_RETRY,
                retry_count,
                next_retry_at,
                current_time,
                inspection.checked_at,
                json.dumps(inspection.as_dict(), sort_keys=True),
                current_time,
                candidate.outreach_followup_plan_id,
            ),
        )


def _persist_successful_followup_send(
    connection: sqlite3.Connection,
    candidate: FollowUpCandidate,
    rendered: RenderedFollowUpDraft,
    outcome: SendAttemptOutcome,
    *,
    current_time: str,
) -> None:
    followup_message_id = new_canonical_id("outreach_messages")
    sent_at = _isoformat_utc(_parse_iso_datetime(outcome.sent_at or current_time))
    with connection:
        connection.execute(
            """
            INSERT INTO outreach_messages (
              outreach_message_id, contact_id, outreach_mode, recipient_email,
              message_status, job_posting_id, job_posting_contact_id, subject,
              body_text, body_html, thread_id, delivery_tracking_id, sent_at,
              created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                followup_message_id,
                candidate.contact_id,
                OUTREACH_MODE_ROLE_TARGETED_FOLLOWUP,
                candidate.recipient_email,
                MESSAGE_STATUS_SENT,
                candidate.job_posting_id,
                candidate.job_posting_contact_id,
                candidate.subject,
                rendered.body_text,
                None,
                outcome.thread_id or candidate.thread_id,
                outcome.delivery_tracking_id,
                sent_at,
                current_time,
                current_time,
            ),
        )
        connection.execute(
            """
            UPDATE outreach_followup_plans
            SET plan_status = ?, followup_outreach_message_id = ?, sent_at = ?,
                last_skip_reason = NULL, retry_count = 0, next_retry_at = NULL,
                draft_artifact_path = ?, review_evidence_artifact_path = ?, updated_at = ?
            WHERE outreach_followup_plan_id = ?
            """,
            (
                PLAN_STATUS_SENT,
                followup_message_id,
                sent_at,
                rendered.draft_artifact_path,
                rendered.review_evidence_artifact_path,
                current_time,
                candidate.outreach_followup_plan_id,
            ),
        )


def _mark_plan_status(
    connection: sqlite3.Connection,
    outreach_followup_plan_id: str,
    plan_status: str,
    current_time: str,
    *,
    reason_code: str | None = None,
    draft_artifact_path: str | None = None,
    review_evidence_artifact_path: str | None = None,
    reply_check: ThreadInspectionResult | None = None,
    agent_reviewed_at: str | None = None,
) -> None:
    with connection:
        connection.execute(
            """
            UPDATE outreach_followup_plans
            SET plan_status = ?,
                last_skip_reason = COALESCE(?, last_skip_reason),
                draft_artifact_path = COALESCE(?, draft_artifact_path),
                review_evidence_artifact_path = COALESCE(?, review_evidence_artifact_path),
                last_evaluated_at = ?,
                last_reply_check_at = COALESCE(?, last_reply_check_at),
                last_reply_check_result = COALESCE(?, last_reply_check_result),
                agent_reviewed_at = COALESCE(?, agent_reviewed_at),
                updated_at = ?
            WHERE outreach_followup_plan_id = ?
            """,
            (
                plan_status,
                reason_code,
                draft_artifact_path,
                review_evidence_artifact_path,
                current_time,
                reply_check.checked_at if reply_check else None,
                json.dumps(reply_check.as_dict(), sort_keys=True) if reply_check else None,
                agent_reviewed_at,
                current_time,
                outreach_followup_plan_id,
            ),
        )


def _record_cycle_run(
    connection: sqlite3.Connection,
    *,
    followup_cycle_run_id: str,
    scheduler_name: str,
    scheduler_type: str,
    started_at: str,
    completed_at: str,
    result: str,
    last_checkpoint: str | None,
    error_message: str | None,
    counts: Mapping[str, int],
) -> None:
    with connection:
        connection.execute(
            """
            INSERT INTO followup_cycle_runs (
              followup_cycle_run_id, scheduler_name, scheduler_type, started_at, result,
              completed_at, candidates_examined, drafts_created, messages_sent,
              waiting_for_pacing_count, skipped_replied, skipped_bounced,
              skipped_already_followed_up, retryable_count, blocked_count,
              held_for_review, last_checkpoint, error_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                followup_cycle_run_id,
                scheduler_name,
                scheduler_type,
                started_at,
                result,
                completed_at,
                counts["candidates_examined"],
                counts["drafts_created"],
                counts["messages_sent"],
                counts["waiting_for_pacing_count"],
                counts["skipped_replied"],
                counts["skipped_bounced"],
                counts["skipped_already_followed_up"],
                counts["retryable_count"],
                counts["blocked_count"],
                counts["held_for_review"],
                last_checkpoint,
                error_message,
            ),
        )


def _write_followup_review_packet(
    paths: ProjectPaths,
    candidate: FollowUpCandidate,
    current_time: str,
    reason_code: str,
    message: str,
    rendered: RenderedFollowUpDraft | None,
    inspection: ThreadInspectionResult | None,
) -> str:
    packet_dir = paths.ops_review_packets_dir / "followups"
    packet_dir.mkdir(parents=True, exist_ok=True)
    packet_path = packet_dir / f"{candidate.outreach_followup_plan_id}.md"
    lines = [
        f"# Follow-Up Review: {candidate.outreach_followup_plan_id}",
        "",
        f"- reason_code: {reason_code}",
        f"- message: {message}",
        f"- original_outreach_message_id: {candidate.original_outreach_message_id}",
        f"- contact_id: {candidate.contact_id}",
        f"- job_posting_id: {candidate.job_posting_id or ''}",
        f"- recipient_email: {candidate.recipient_email}",
        f"- thread_id: {candidate.thread_id or ''}",
        f"- delivery_tracking_id: {candidate.delivery_tracking_id or ''}",
        f"- created_at: {current_time}",
        "",
        "## Recommended Action",
        "Inspect the thread and metadata, then reset the plan only if the safety facts still allow another automatic follow-up.",
        "",
        "## Original Email",
        candidate.body_text,
        "",
    ]
    if rendered is not None:
        lines.extend(
            [
                "## Rendered Follow-Up Draft",
                rendered.body_text,
                "",
                "## Follow-Up Evidence",
                "```json",
                json.dumps(rendered.evidence, indent=2),
                "```",
                "",
            ]
        )
    if inspection is not None:
        lines.extend(["## Thread Check Evidence", "```json", json.dumps(inspection.as_dict(), indent=2), "```", ""])
    packet_path.write_text("\n".join(lines), encoding="utf-8")
    return str(paths.relative_to_root(packet_path))


def _review_message_for_reason(reason_code: str) -> str:
    messages = {
        SKIP_REASON_MISSING_THREAD_CONTEXT: "Original same-thread Gmail metadata is missing or unusable.",
        SKIP_REASON_MISSING_ORIGINAL_BODY: "Original sent email body is missing from canonical state.",
        SKIP_REASON_GROUNDING_INSUFFICIENT: "Could not render a bounded grounded follow-up.",
        SKIP_REASON_AMBIGUOUS_SEND: "Gmail send state is ambiguous.",
        SKIP_REASON_DRAFT_RETRY_EXHAUSTED: "Codex drafting failed repeatedly and the thread now needs owner review.",
    }
    return messages.get(reason_code, "Follow-up candidate requires owner review before it can proceed.")


def _evaluate_global_pacing(
    connection: sqlite3.Connection,
    candidate: FollowUpCandidate,
    *,
    current_time: str,
) -> dict[str, Any]:
    current_dt = _parse_iso_datetime(current_time)
    latest_sent_at = _load_latest_sent_at(connection)
    if latest_sent_at is None:
        return {"allowed": True, "earliest_allowed_send_at": current_time}
    gap_minutes = _determine_followup_gap_minutes(candidate, current_dt)
    earliest = latest_sent_at + timedelta(minutes=gap_minutes)
    return {
        "allowed": earliest <= current_dt,
        "earliest_allowed_send_at": _isoformat_utc(earliest),
        "gap_minutes": gap_minutes,
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
    if row is None or not row["sent_at"]:
        return None
    return _parse_iso_datetime(str(row["sent_at"]))


def _determine_followup_gap_minutes(candidate: FollowUpCandidate, current_dt: datetime) -> int:
    seed = "|".join(
        [
            candidate.original_outreach_message_id,
            current_dt.date().isoformat(),
            candidate.contact_id,
        ]
    )
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return MIN_INTER_SEND_GAP_MINUTES + (digest[0] % (MAX_INTER_SEND_GAP_MINUTES - MIN_INTER_SEND_GAP_MINUTES + 1))


def _followup_auto_send_enabled(connection: sqlite3.Connection) -> bool:
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


def _increment_initial_rollout_count(connection: sqlite3.Connection, current_time: str) -> bool:
    rows = {
        row["control_key"]: row["control_value"]
        for row in connection.execute(
            """
            SELECT control_key, control_value
            FROM agent_control_state
            WHERE control_key IN (?, ?)
            """,
            (
                FOLLOWUP_INITIAL_ROLLOUT_SENT_COUNT_KEY,
                FOLLOWUP_INITIAL_ROLLOUT_APPROVED_KEY,
            ),
        )
    }
    try:
        count = int(rows.get(FOLLOWUP_INITIAL_ROLLOUT_SENT_COUNT_KEY, "0"))
    except ValueError:
        count = 0
    rollout_approved = rows.get(FOLLOWUP_INITIAL_ROLLOUT_APPROVED_KEY) == "true"
    count += 1
    cap_reached = False
    updates = [(FOLLOWUP_INITIAL_ROLLOUT_SENT_COUNT_KEY, str(count), current_time)]
    if not rollout_approved and count >= FOLLOWUP_INITIAL_AUTO_SEND_CAP:
        updates.append((FOLLOWUP_AUTO_SEND_PAUSED_KEY, "true", current_time))
        cap_reached = True
    with connection:
        connection.executemany(
            """
            INSERT INTO agent_control_state (control_key, control_value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(control_key) DO UPDATE SET
              control_value = excluded.control_value,
              updated_at = excluded.updated_at
            """,
            updates,
        )
    return cap_reached


def _release_auto_send_disabled_holds(connection: sqlite3.Connection, *, current_time: str) -> int:
    with connection:
        cursor = connection.execute(
            """
            UPDATE outreach_followup_plans
            SET plan_status = ?, last_skip_reason = NULL, updated_at = ?
            WHERE plan_status = ?
              AND last_skip_reason = ?
            """,
            (
                PLAN_STATUS_PENDING,
                current_time,
                PLAN_STATUS_HELD_FOR_REVIEW,
                SKIP_REASON_AUTO_SEND_DISABLED,
            ),
        )
    return int(cursor.rowcount or 0)


def _release_missing_sender_identity_holds(connection: sqlite3.Connection, *, current_time: str) -> int:
    with connection:
        cursor = connection.execute(
            """
            UPDATE outreach_followup_plans
            SET plan_status = ?, last_skip_reason = NULL, updated_at = ?
            WHERE plan_status = ?
              AND last_skip_reason = ?
            """,
            (
                PLAN_STATUS_PENDING,
                current_time,
                PLAN_STATUS_HELD_FOR_REVIEW,
                SKIP_REASON_MISSING_SENDER_IDENTITY,
            ),
        )
    return int(cursor.rowcount or 0)


def _count_followups_sent_today(connection: sqlite3.Connection, current_time: str) -> int:
    current_local_date = _parse_iso_datetime(current_time).astimezone(FOLLOWUP_BUSINESS_TIMEZONE).date()
    count = 0
    rows = connection.execute(
        """
        SELECT sent_at
        FROM outreach_messages
        WHERE outreach_mode = ?
          AND message_status = ?
          AND sent_at IS NOT NULL
          AND TRIM(sent_at) <> ''
        """,
        (OUTREACH_MODE_ROLE_TARGETED_FOLLOWUP, MESSAGE_STATUS_SENT),
    ).fetchall()
    for row in rows:
        sent_local_date = _parse_iso_datetime(str(row["sent_at"])).astimezone(FOLLOWUP_BUSINESS_TIMEZONE).date()
        if sent_local_date == current_local_date:
            count += 1
    return count


def _write_rollout_pause_packet(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    current_time: str,
) -> str:
    packet_dir = paths.ops_dir / "followups" / "rollouts"
    packet_dir.mkdir(parents=True, exist_ok=True)
    packet_path = packet_dir / f"initial-rollout-{current_time.replace(':', '').replace('-', '')}.md"
    rows = connection.execute(
        """
        SELECT fp.outreach_followup_plan_id, fp.original_outreach_message_id, fp.followup_sequence,
               fp.sent_at, om.recipient_email, om.subject
        FROM outreach_followup_plans fp
        JOIN outreach_messages om
          ON om.outreach_message_id = fp.followup_outreach_message_id
        WHERE fp.plan_status = ?
        ORDER BY fp.sent_at DESC, fp.outreach_followup_plan_id DESC
        LIMIT ?
        """,
        (PLAN_STATUS_SENT, FOLLOWUP_INITIAL_AUTO_SEND_CAP),
    ).fetchall()
    lines = [
        "# Follow-Up Initial Rollout Pause",
        "",
        f"- paused_at: `{current_time}`",
        f"- rollout_cap: `{FOLLOWUP_INITIAL_AUTO_SEND_CAP}`",
        "",
        "## Sent Follow-Ups",
        "",
    ]
    for row in rows:
        lines.append(
            f"- `{row['outreach_followup_plan_id']}` seq {row['followup_sequence']} | {row['recipient_email']} | `{row['sent_at']}` | {row['subject'] or ''}"
        )
    packet_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(paths.relative_to_root(packet_path))


def _role_targeted_priority_exists_now(
    connection: sqlite3.Connection,
    *,
    project_root: Path | str,
    current_time: str,
) -> bool:
    posting_rows = connection.execute(
        """
        SELECT job_posting_id
        FROM job_postings
        WHERE posting_status IN ('ready_for_outreach', 'outreach_in_progress')
        ORDER BY created_at ASC, job_posting_id ASC
        """
    ).fetchall()
    for row in posting_rows:
        if is_role_targeted_sending_actionable_now(
            connection,
            project_root=project_root,
            job_posting_id=str(row["job_posting_id"]),
            current_time=current_time,
            local_timezone=FOLLOWUP_BUSINESS_TIMEZONE,
        ):
            return True
    return False


def _pause_followup_auto_send_for_codex_outage(
    connection: sqlite3.Connection,
    *,
    paths: ProjectPaths,
    candidate: FollowUpCandidate,
    current_time: str,
    message: str,
) -> str:
    from .supervisor import create_agent_incident

    summary = (
        "Follow-up worker could not execute the required Codex drafting path and paused follow-up auto-send. "
        f"Original outreach message: {candidate.original_outreach_message_id}. Error: {message}"
    )
    incident = create_agent_incident(
        connection,
        incident_type="codex_followup_outage",
        severity="high",
        summary=summary,
        contact_id=candidate.contact_id,
        job_posting_id=candidate.job_posting_id,
        outreach_message_id=candidate.original_outreach_message_id,
        created_at=current_time,
    )
    with connection:
        connection.execute(
            """
            INSERT INTO agent_control_state (control_key, control_value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(control_key) DO UPDATE SET
              control_value = excluded.control_value,
              updated_at = excluded.updated_at
            """,
            (FOLLOWUP_AUTO_SEND_PAUSED_KEY, "true", current_time),
        )
    packet_dir = paths.ops_review_packets_dir / "followups"
    packet_dir.mkdir(parents=True, exist_ok=True)
    packet_path = packet_dir / f"{candidate.outreach_followup_plan_id}-codex-outage.md"
    packet_path.write_text(
        "\n".join(
            [
                f"# Follow-Up Codex Outage: {candidate.outreach_followup_plan_id}",
                "",
                f"- incident_id: {incident.agent_incident_id}",
                f"- contact_id: {candidate.contact_id}",
                f"- original_outreach_message_id: {candidate.original_outreach_message_id}",
                f"- created_at: {current_time}",
                "",
                "## Error",
                message,
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return str(paths.relative_to_root(packet_path))


def _classify_original_outreach_origin(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    candidate: FollowUpCandidate,
    metadata: OriginalSendMetadata | None = None,
) -> OriginalOutreachOrigin:
    resolved_metadata = metadata or _load_original_send_metadata(paths, candidate)
    if resolved_metadata.autonomous_origin is False:
        return OriginalOutreachOrigin(
            status="manual",
            posture_family=resolved_metadata.draft_posture_family,
            proof_source="send_result_metadata",
            reason_code=SKIP_REASON_MANUAL_ORIGIN,
            reason_message="Original outreach was marked as manual-only and is not eligible for automatic follow-up.",
            autonomous_origin=False,
        )
    if resolved_metadata.draft_origin_kind == "codex_role_split":
        return OriginalOutreachOrigin(
            status="codex",
            posture_family=resolved_metadata.draft_posture_family or _infer_posture_from_body(candidate.subject, candidate.body_text),
            proof_source="send_result_metadata",
            autonomous_origin=resolved_metadata.autonomous_origin,
        )
    if resolved_metadata.draft_origin_kind in {"deterministic", "shared_template"}:
        return OriginalOutreachOrigin(
            status="deterministic",
            posture_family=resolved_metadata.draft_posture_family,
            proof_source="send_result_metadata",
            reason_code=SKIP_REASON_NON_CODEX_ORIGIN,
            reason_message="Original outreach was generated by the retired deterministic/shared-template path.",
            autonomous_origin=resolved_metadata.autonomous_origin,
        )

    llm_event = connection.execute(
        """
        SELECT operation_name, created_at
        FROM llm_usage_events
        WHERE component_name = 'outreach'
          AND invocation_status = 'succeeded'
          AND job_posting_id = ?
          AND contact_id = ?
          AND operation_name IN ('technical-role-split', 'managerial-role-split')
        ORDER BY created_at DESC, llm_usage_event_id DESC
        LIMIT 1
        """,
        (candidate.job_posting_id, candidate.contact_id),
    ).fetchone()
    if llm_event is not None:
        operation_name = str(llm_event["operation_name"])
        posture_family = POSTURE_TECHNICAL if operation_name == "technical-role-split" else POSTURE_MANAGERIAL
        return OriginalOutreachOrigin(
            status="codex",
            posture_family=posture_family,
            proof_source="llm_usage_event",
            autonomous_origin=True,
        )

    posture_family = _infer_posture_from_body(candidate.subject, candidate.body_text)
    if posture_family is not None:
        return OriginalOutreachOrigin(
            status="codex",
            posture_family=posture_family,
            proof_source="body_style_fallback",
            autonomous_origin=None,
        )

    if _looks_like_legacy_deterministic_email(candidate.body_text):
        return OriginalOutreachOrigin(
            status="deterministic",
            posture_family=None,
            proof_source="body_style_fallback",
            reason_code=SKIP_REASON_NON_CODEX_ORIGIN,
            reason_message="Original outreach matches the retired deterministic/shared-template family.",
            autonomous_origin=None,
        )
    return OriginalOutreachOrigin(
        status="unknown",
        posture_family=None,
        proof_source="unable_to_classify",
        reason_code=SKIP_REASON_UNKNOWN_ORIGIN,
        reason_message="Original outreach origin could not be proven valid for the Codex-only automatic follow-up worker.",
        autonomous_origin=None,
    )


def _infer_posture_from_body(subject: str | None, body_text: str) -> str | None:
    normalized_subject = _normalize_optional_text(subject) or ""
    normalized_body = body_text.strip()
    if normalized_subject == TECHNICAL_PATH_SUBJECT and "admired your path" in normalized_body.lower():
        return POSTURE_TECHNICAL
    if ROLE_SPLIT_MANAGERIAL_SUBJECT_RE.match(normalized_subject) and "I hope you're doing well." in normalized_body:
        return POSTURE_MANAGERIAL
    return None


def _looks_like_legacy_deterministic_email(body_text: str) -> bool:
    normalized = body_text.lower()
    legacy_markers = (
        "i'm reaching out about the",
        "given your role as",
        "lately, i have been spending time sharpening my agentic ai skills.",
        "i built job hunt copilot",
    )
    return sum(marker in normalized for marker in legacy_markers) >= 2


def _load_prior_sent_followups(
    connection: sqlite3.Connection,
    original_outreach_message_id: str,
) -> tuple[str, ...]:
    rows = connection.execute(
        """
        SELECT om.body_text
        FROM outreach_followup_plans fp
        JOIN outreach_messages om
          ON om.outreach_message_id = fp.followup_outreach_message_id
        WHERE fp.original_outreach_message_id = ?
          AND fp.plan_status = ?
        ORDER BY fp.followup_sequence ASC
        """,
        (original_outreach_message_id, PLAN_STATUS_SENT),
    ).fetchall()
    return tuple(str(row["body_text"] or "") for row in rows if str(row["body_text"] or "").strip())


def _build_sender_evidence_summary(original_body_text: str) -> str:
    paragraphs = [
        paragraph.strip()
        for paragraph in re.split(r"\n\s*\n", _strip_signature(original_body_text))
        if paragraph.strip()
    ]
    for paragraph in paragraphs:
        if any(marker in paragraph.lower() for marker in ("built ", "designed ", "processed ", "50m+", "580", "uptime", "aws", "azure", "spark")):
            return paragraph
    return paragraphs[0] if paragraphs else ""


def _build_role_company_summary(role_title: str | None, company_name: str | None, *, sequence: int) -> str:
    if sequence == 1 and role_title and company_name:
        return f"Follow-up 1 must explicitly refer to the {role_title} role at {company_name}."
    if role_title and company_name:
        return (
            f"This thread remains anchored to the {role_title} role at {company_name}. "
            "Later follow-ups may rely on thread context instead of repeating both strings verbatim."
        )
    return "Later follow-ups may rely on thread context when role/company detail is unavailable."


def _build_thread_context_summary(candidate: FollowUpCandidate, prior_followups: Sequence[str]) -> str:
    if not prior_followups:
        return "No prior sent follow-ups exist on this thread."
    return (
        f"{len(prior_followups)} prior sent follow-up(s) exist. Avoid repetition and keep this message lighter than the original thread."
    )


def _assemble_followup_body(
    *,
    salutation: str,
    paragraphs: Sequence[str],
    followup_sequence: int,
) -> str:
    final_paragraphs = list(paragraphs)
    if followup_sequence == FOLLOWUP_MAX_SEQUENCE:
        final_paragraphs.append(FIXED_FINAL_TOUCH_SENTENCE)
    lines = [salutation, ""]
    for index, paragraph in enumerate(final_paragraphs):
        lines.append(paragraph.strip())
        lines.append("")
    lines.extend(["Best,", "Achyutaram Sonti"])
    return "\n".join(lines).strip()


def _extract_followup_body_paragraphs(body_text: str) -> list[str]:
    blocks = [block.strip() for block in re.split(r"\n\s*\n", body_text.strip()) if block.strip()]
    if len(blocks) < 3:
        return []
    content_blocks = blocks[1:-1]
    return content_blocks


def _normalize_paragraph_text(value: str) -> str:
    normalized = re.sub(r"\s+", " ", str(value).strip())
    return normalized


def _is_due_now(candidate: FollowUpCandidate, current_time: str) -> bool:
    current_dt = _parse_iso_datetime(current_time)
    if _parse_iso_datetime(candidate.eligible_after) > current_dt:
        return False
    local_dt = current_dt.astimezone(FOLLOWUP_BUSINESS_TIMEZONE)
    if local_dt.weekday() >= 5:
        return False
    local_t = local_dt.timetz().replace(tzinfo=None)
    return FOLLOWUP_WINDOW_START <= local_t <= FOLLOWUP_WINDOW_END


def _eligible_after(sent_at: str, sequence: int, local_timezone: ZoneInfo) -> str:
    sent_dt = _parse_iso_datetime(sent_at).astimezone(local_timezone)
    business_days = FOLLOWUP_DAY_GAPS[sequence]
    target_dt = sent_dt
    days_added = 0
    while days_added < business_days:
        target_dt += timedelta(days=1)
        if target_dt.weekday() >= 5:
            continue
        days_added += 1
    return _isoformat_utc(target_dt.astimezone(UTC))


def _load_original_send_metadata(paths: ProjectPaths, candidate: FollowUpCandidate) -> OriginalSendMetadata:
    payload = _load_original_send_result_payload(paths, candidate)
    if payload is None:
        return OriginalSendMetadata(
            source_path=None,
            cc_emails=(),
            message_id_header=None,
            role_title=None,
            company_name=None,
            autonomous_origin=None,
            draft_origin_kind=None,
            draft_posture_family=None,
        )
    cc_values = _coerce_email_sequence(
        payload.get("cc")
        or payload.get("cc_emails")
        or payload.get("recipient_cc")
        or payload.get("recipient_cc_emails")
    )
    message_id_header = _normalize_optional_text(
        payload.get("rfc_message_id")
        or payload.get("message_id_header")
        or payload.get("message_id")
        or payload.get("Message-ID")
    )
    autonomous_origin = payload.get("autonomous_origin")
    if isinstance(autonomous_origin, str):
        autonomous_origin = autonomous_origin.strip().lower() == "true"
    elif not isinstance(autonomous_origin, bool):
        autonomous_origin = None
    source_path = _normalize_optional_text(payload.get("_source_path"))
    return OriginalSendMetadata(
        source_path=source_path,
        cc_emails=cc_values,
        message_id_header=message_id_header,
        role_title=_clean_template_field(payload.get("role_title")),
        company_name=_clean_template_field(payload.get("company_name")),
        autonomous_origin=autonomous_origin,
        draft_origin_kind=_normalize_optional_text(payload.get("draft_origin_kind") or payload.get("origin_renderer")),
        draft_posture_family=_normalize_optional_text(payload.get("draft_posture_family")),
    )


def _load_original_send_result_payload(paths: ProjectPaths, candidate: FollowUpCandidate) -> dict[str, Any] | None:
    candidates: list[Path] = []
    if candidate.company_name and candidate.role_title:
        candidates.append(
            paths.outreach_message_send_result_path(
                candidate.company_name,
                candidate.role_title,
                candidate.original_outreach_message_id,
            )
        )
    for path in paths.project_root.glob(f"outreach/output/*/*/messages/{candidate.original_outreach_message_id}/send_result.json"):
        candidates.append(path)
    seen: set[Path] = set()
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        if not path.exists() or not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            payload["_source_path"] = str(paths.relative_to_root(path))
            return payload
    return None


def _coerce_email_sequence(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        raw_values = re.split(r"[,;]", value)
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        raw_values = [str(item) for item in value]
    else:
        raw_values = [str(value)]
    emails: list[str] = []
    for raw_value in raw_values:
        for email in EMAIL_RE.findall(raw_value):
            normalized = _normalize_email(email)
            if normalized and normalized not in emails:
                emails.append(normalized)
    return tuple(emails)


def _resolve_role_company(candidate: FollowUpCandidate, metadata: OriginalSendMetadata) -> dict[str, str | None]:
    body_pair = _extract_role_company_from_original_body(candidate.body_text)
    subject_pair = _extract_role_company_from_subject(candidate.subject)
    role_title = body_pair.get("role_title") or subject_pair.get("role_title") or metadata.role_title or _clean_template_field(candidate.role_title)
    company_name = body_pair.get("company_name") or subject_pair.get("company_name") or metadata.company_name or _clean_template_field(candidate.company_name)
    return {
        "role_title": role_title,
        "company_name": company_name,
    }


def _resolve_salutation(candidate: FollowUpCandidate) -> str:
    first_line = candidate.body_text.strip().splitlines()[0].strip() if candidate.body_text.strip() else ""
    if re.match(r"^(Hi|Hello)\s*,\s*$", first_line):
        return first_line.rstrip()
    salutation_match = re.match(r"^(Hi|Hello)\s+([^,\n]+),\s*$", first_line)
    if salutation_match:
        return f"{salutation_match.group(1)} {salutation_match.group(2).strip()},"
    first_name = _clean_name(candidate.contact_first_name) or _first_name_from_display(candidate.contact_display_name)
    if first_name:
        return f"Hi {first_name},"
    return "Hi,"


def _first_name_from_display(display_name: str | None) -> str | None:
    if not display_name:
        return None
    first_token = re.split(r"\s+", display_name.strip())[0]
    return _clean_name(first_token)


def _clean_name(value: str | None) -> str | None:
    normalized = _normalize_optional_text(value)
    if normalized is None:
        return None
    if "@" in normalized or normalized.lower() in {"unknown", "none", "n/a"}:
        return None
    if not re.match(r"^[A-Za-z][A-Za-z'\-]*$", normalized):
        return None
    return normalized


def _followup_artifact_dir(paths: ProjectPaths, candidate: FollowUpCandidate) -> Path:
    if candidate.company_name and candidate.role_title:
        return paths.outreach_message_followup_dir(
            candidate.company_name,
            candidate.role_title,
            candidate.original_outreach_message_id,
            candidate.followup_sequence,
        )
    return paths.fallback_followup_dir(candidate.original_outreach_message_id, candidate.followup_sequence)


def _load_sender_email(paths: ProjectPaths) -> str | None:
    runtime_secrets_path = paths.secrets_dir / "runtime_secrets.json"
    if not runtime_secrets_path.exists():
        return None
    try:
        payload = json.loads(runtime_secrets_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    gmail_payload = payload.get("gmail")
    if not isinstance(gmail_payload, Mapping):
        return None
    for key in ("sender_email", "profile_email"):
        normalized = _normalize_email(gmail_payload.get(key) if isinstance(gmail_payload, Mapping) else None)
        if normalized:
            return normalized
    try:
        from .gmail_alerts import _build_gmail_service

        payload = _build_gmail_service(paths).users().getProfile(userId="me").execute()
    except Exception:
        return None
    if isinstance(payload, Mapping):
        normalized = _normalize_email(payload.get("emailAddress"))
        if normalized:
            return normalized
    return None


def _read_optional_project_file(paths: ProjectPaths, path_text: str | None) -> str:
    if not path_text:
        return ""
    path = paths.resolve_from_root(path_text)
    if not path.exists() or not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _extract_role_company_from_original_body(body_text: str) -> dict[str, str | None]:
    match = re.search(
        r"\babout the (?P<role>.+?) role at (?P<company>.+?)(?: because|\.\s|,|\n)",
        body_text,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return {"role_title": None, "company_name": None}
    return {
        "role_title": _clean_template_field(match.group("role")),
        "company_name": _clean_template_field(match.group("company")),
    }


def _extract_role_company_from_subject(subject: str | None) -> dict[str, str | None]:
    normalized = _normalize_optional_text(subject)
    if not normalized:
        return {"role_title": None, "company_name": None}
    match = ROLE_SPLIT_MANAGERIAL_SUBJECT_RE.match(normalized)
    if not match:
        return {"role_title": None, "company_name": None}
    cleaned = normalized.removeprefix("Interest in the ").strip()
    role_title, _, company_name = cleaned.partition(" role at ")
    return {
        "role_title": _clean_template_field(role_title),
        "company_name": _clean_template_field(company_name),
    }


def _clean_template_field(value: str | None) -> str | None:
    normalized = _normalize_optional_text(value)
    if normalized is None:
        return None
    return re.sub(r"\s+", " ", normalized)


def _strip_signature(body_text: str) -> str:
    return re.split(r"\n\s*Best,\s*\n", body_text, maxsplit=1)[0].strip()


def _parse_iso_datetime(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _isoformat_utc(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _normalize_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _normalize_email(value: str | None) -> str | None:
    normalized = _normalize_optional_text(value)
    return normalized.lower() if normalized else None


def _normalize_phrase(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _increment_count_for_reason(counts: dict[str, int], reason_code: str) -> None:
    if reason_code in {SKIP_REASON_REPLIED_IN_THREAD, SKIP_REASON_CONTACT_REPLY_SUPPRESSION}:
        counts["skipped_replied"] += 1
    elif reason_code == SKIP_REASON_BOUNCED:
        counts["skipped_bounced"] += 1
    elif reason_code == SKIP_REASON_ALREADY_FOLLOWED_UP:
        counts["skipped_already_followed_up"] += 1
    elif reason_code in {SKIP_REASON_WAITING_FOR_PACING, SKIP_REASON_ROLE_TARGETED_PRIORITY}:
        counts["waiting_for_pacing_count"] += 1
    elif reason_code in {SKIP_REASON_TRANSIENT_RETRY, SKIP_REASON_DRAFT_RETRY}:
        counts["retryable_count"] += 1
    elif reason_code in {SKIP_REASON_DRAFT_RETRY_EXHAUSTED, SKIP_REASON_GROUNDING_INSUFFICIENT, SKIP_REASON_AUTO_SEND_DISABLED}:
        counts["held_for_review"] += 1
    else:
        counts["blocked_count"] += 1


def _build_followup_prompt(context: FollowUpDraftContext) -> str:
    prior_followups_text = "\n\n".join(
        f"Prior follow-up {index + 1}:\n{message}"
        for index, message in enumerate(context.prior_followups)
    ) or "No prior follow-ups have been sent."
    shared_rules = [
        "Return JSON only with keys: paragraphs, role_company_mode, grounding_mode, why_sent_summary.",
        "paragraphs must contain 2 or 3 short paragraphs only.",
        "Do not include greeting, signoff, subject, quoted thread text, bullets, markdown, Job Hunt Copilot details, resume mention, or attachment mention.",
        "Keep the follow-up lighter than the original email.",
        f"Follow-up {context.sequence} must keep the primary CTA as: {MANAGERIAL_PATH_CTA_QUESTION}",
        "Stay anchored to the original sent email and prior sent follow-ups only. Do not introduce new candidate evidence.",
    ]
    if context.sequence == 1:
        shared_rules.extend(
            [
                "This is follow-up 1: keep it mostly as a light reminder.",
                "It must explicitly mention the role and company.",
            ]
        )
    elif context.sequence == 2:
        shared_rules.extend(
            [
                "This is follow-up 2: allow one compact mutual-fit reminder from the original evidence.",
                "Role/company can be thread-implied if that reads more naturally.",
            ]
        )
    else:
        shared_rules.extend(
            [
                "This is follow-up 3: keep it respectful, final, and light.",
                "Do not add your own final-stop sentence; deterministic runtime will insert that exact final sentence separately.",
                "Role/company can be thread-implied if the thread already makes them clear.",
            ]
        )
    if context.posture_family == POSTURE_TECHNICAL:
        family_rules = [
            "Keep the tone career-guidance oriented.",
            "Do not switch into direct application or referral language.",
            "A very light callback to the recipient's career path is acceptable, but do not restate the original hook heavily.",
        ]
    else:
        family_rules = [
            "Keep the thread role-interest oriented with the specific role as the anchor.",
            "Later follow-ups may soften into perspective on the role, team, or work, but do not turn this into generic networking.",
        ]
    return "\n".join(
        [
            "Draft the variable follow-up body paragraphs for a same-thread cold outreach follow-up.",
            "",
            "Rules:",
            *[f"- {rule}" for rule in shared_rules],
            *[f"- {rule}" for rule in family_rules],
            "",
            "Bounded context:",
            f"- sequence_step: {context.sequence}",
            f"- posture_family: {context.posture_family}",
            f"- salutation_style: {context.salutation}",
            f"- role_company_summary: {context.role_company_summary}",
            f"- sender_evidence_summary: {context.sender_evidence_summary}",
            f"- thread_context_summary: {context.thread_context_summary}",
            "",
            "Original sent email:",
            context.original_body_text,
            "",
            "Earlier sent follow-ups in this thread:",
            prior_followups_text,
            "",
            "Grounding mode values:",
            "- original_email_only",
            "- original_email_plus_prior_followups",
            "- original_outreach_context_fallback",
        ]
    )


def _run_followup_codex_payload(
    paths: ProjectPaths,
    *,
    codex_bin: str,
    model: str | None,
    context: FollowUpDraftContext,
    current_time: str,
) -> dict[str, Any]:
    prompt = _build_followup_prompt(context)
    run_dir = (
        paths.ops_dir
        / "followups"
        / "codex"
        / f"{current_time.replace(':', '').replace('-', '')}-{_workspace_slug(context.candidate.contact_id)}-{_workspace_slug(context.candidate.original_outreach_message_id)}-seq{context.sequence}"
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = run_dir / "prompt.md"
    schema_path = run_dir / "schema.json"
    output_path = run_dir / "output.json"
    stdout_path = run_dir / "codex.stdout.txt"
    stderr_path = run_dir / "codex.stderr.txt"
    prompt_path.write_text(prompt, encoding="utf-8")
    schema = {
        "type": "object",
        "properties": {
            "paragraphs": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 2,
                "maxItems": 3,
            },
            "role_company_mode": {
                "type": "string",
                "enum": ["explicit", "thread_implied"],
            },
            "grounding_mode": {
                "type": "string",
                "enum": [
                    "original_email_only",
                    "original_email_plus_prior_followups",
                    "original_outreach_context_fallback",
                ],
            },
            "why_sent_summary": {
                "type": "string",
            },
        },
        "required": ["paragraphs", "role_company_mode", "grounding_mode", "why_sent_summary"],
        "additionalProperties": False,
    }
    schema_path.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
    command = _build_codex_exec_command(
        codex_bin=codex_bin,
        project_root=paths.project_root,
        schema_path=schema_path,
        output_path=output_path,
        model=model,
    )
    try:
        completed = subprocess.run(
            command,
            input=prompt,
            text=True,
            capture_output=True,
            check=False,
            env=_build_codex_exec_env(codex_bin),
            timeout=AUTONOMOUS_CODEX_DRAFT_TIMEOUT_SECONDS,
        )
        stdout_text = completed.stdout
        stderr_text = completed.stderr
        exit_code = completed.returncode
    except subprocess.TimeoutExpired as exc:
        stdout_text = _normalize_subprocess_stream_text(exc.stdout)
        stderr_text = _normalize_subprocess_stream_text(exc.stderr)
        stdout_path.write_text(stdout_text, encoding="utf-8")
        stderr_path.write_text(stderr_text, encoding="utf-8")
        record_codex_usage_event(
            paths,
            component_name=FOLLOWUP_COMPONENT,
            operation_name=f"followup-sequence-{context.sequence}-{context.posture_family}",
            invocation_status="failed",
            exit_code=CODEX_TIMEOUT_EXIT_CODE,
            stderr_text=stderr_text,
            run_directory_path=run_dir,
            prompt_artifact_path=prompt_path,
            output_artifact_path=output_path,
            stdout_artifact_path=stdout_path,
            stderr_artifact_path=stderr_path,
            job_posting_id=context.candidate.job_posting_id,
            contact_id=context.candidate.contact_id,
            outreach_message_id=context.candidate.original_outreach_message_id,
            created_at=current_time,
        )
        raise FollowUpDraftingError(
            "`codex exec` timed out after "
            f"{AUTONOMOUS_CODEX_DRAFT_TIMEOUT_SECONDS} seconds. See {stderr_path}."
        ) from exc
    stdout_path.write_text(stdout_text, encoding="utf-8")
    stderr_path.write_text(stderr_text, encoding="utf-8")
    record_codex_usage_event(
        paths,
        component_name=FOLLOWUP_COMPONENT,
        operation_name=f"followup-sequence-{context.sequence}-{context.posture_family}",
        invocation_status="succeeded" if exit_code == 0 else "failed",
        exit_code=exit_code,
        stderr_text=stderr_text,
        run_directory_path=run_dir,
        prompt_artifact_path=prompt_path,
        output_artifact_path=output_path,
        stdout_artifact_path=stdout_path,
        stderr_artifact_path=stderr_path,
        job_posting_id=context.candidate.job_posting_id,
        contact_id=context.candidate.contact_id,
        outreach_message_id=context.candidate.original_outreach_message_id,
        created_at=current_time,
    )
    if exit_code != 0:
        raise FollowUpDraftingError(
            f"`codex exec` failed with exit code {exit_code}. See {stderr_path}."
        )
    if not output_path.exists():
        raise FollowUpDraftingError(
            f"`codex exec` did not materialize a follow-up payload. Expected {output_path}."
        )
    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FollowUpDraftingError(f"Follow-up payload is not valid JSON. See {output_path}.") from exc
    if not isinstance(payload, dict):
        raise FollowUpDraftingError(f"Follow-up payload must be a JSON object. See {output_path}.")
    return payload


def _resolve_codex_bin() -> str:
    for env_name in ("JHC_OUTREACH_CODEX_BIN", "JHC_CODEX_BIN", "CODEX_BIN"):
        candidate = os.environ.get(env_name)
        if candidate and _is_executable_binary(candidate):
            return candidate
    resolved = shutil.which("codex")
    if resolved and _is_executable_binary(resolved):
        return resolved
    for candidate in (
        "/opt/homebrew/bin/codex",
        "/usr/local/bin/codex",
        str(Path.home() / ".local" / "bin" / "codex"),
        str(Path.home() / ".codex" / "bin" / "codex"),
    ):
        if _is_executable_binary(candidate):
            return candidate
    raise FollowUpDraftingError(
        "`codex` binary is required for autonomous follow-up drafting. Install it or set JHC_OUTREACH_CODEX_BIN."
    )


def _is_executable_binary(path: str | os.PathLike[str]) -> bool:
    candidate = Path(path).expanduser()
    return candidate.is_file() and os.access(candidate, os.X_OK)


def _build_codex_exec_env(codex_bin: str) -> dict[str, str]:
    env = dict(os.environ)
    existing_path = env.get("PATH", "")
    candidate_entries = [
        str(Path(codex_bin).expanduser().parent),
        "/opt/homebrew/bin",
        "/usr/local/bin",
        str(Path.home() / ".local" / "bin"),
        str(Path.home() / ".codex" / "bin"),
    ]
    if existing_path:
        candidate_entries.extend(existing_path.split(os.pathsep))
    deduped: list[str] = []
    seen: set[str] = set()
    for entry in candidate_entries:
        normalized = entry.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    env["PATH"] = os.pathsep.join(deduped)
    return env


def _build_codex_exec_command(
    *,
    codex_bin: str,
    project_root: Path,
    schema_path: Path,
    output_path: Path,
    model: str | None = None,
) -> list[str]:
    command = [codex_bin, "exec"]
    if model:
        command.extend(["--model", model])
    command.extend(
        [
            "--ephemeral",
            "--sandbox",
            "workspace-write",
            "-C",
            str(project_root),
            "--output-schema",
            str(schema_path),
            "-o",
            str(output_path),
            "-",
        ]
    )
    return command


def _is_codex_outage_error(message: str) -> bool:
    normalized = message.lower()
    return (
        "`codex` binary is required" in normalized
        or "`codex exec` failed" in normalized
        or "`codex exec` timed out" in normalized
    )


def _workspace_slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-")
    return normalized or "unknown"


def _gmail_headers(raw_message: Mapping[str, Any]) -> dict[str, str]:
    payload = raw_message.get("payload")
    if not isinstance(payload, Mapping):
        return {}
    headers = payload.get("headers")
    if not isinstance(headers, Sequence):
        return {}
    result: dict[str, str] = {}
    for header in headers:
        if not isinstance(header, Mapping):
            continue
        name = str(header.get("name", "")).strip().lower()
        value = str(header.get("value", "")).strip()
        if name:
            result[name] = value
    return result


def _gmail_message_datetime(raw_message: Mapping[str, Any]) -> datetime | None:
    internal_date = raw_message.get("internalDate")
    if internal_date is None:
        return None
    try:
        milliseconds = int(str(internal_date))
    except ValueError:
        return None
    return datetime.fromtimestamp(milliseconds / 1000, tz=UTC)


def _extract_first_email(value: str) -> str | None:
    match = EMAIL_RE.search(value)
    return match.group(0) if match else None


def _gmail_sent_at_from_response(response: Mapping[str, Any]) -> str | None:
    internal_date = response.get("internalDate")
    if internal_date is None:
        return None
    try:
        milliseconds = int(str(internal_date))
    except ValueError:
        return None
    return _isoformat_utc(datetime.fromtimestamp(milliseconds / 1000, tz=UTC))
