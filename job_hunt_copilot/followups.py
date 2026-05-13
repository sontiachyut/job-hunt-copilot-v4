from __future__ import annotations

import base64
import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence
from zoneinfo import ZoneInfo

from .artifacts import ArtifactLinkage, write_json_contract
from .contracts import CONTRACT_VERSION
from .outreach import (
    MAX_AUTOMATIC_TRANSIENT_SEND_RETRIES,
    MAX_INTER_SEND_GAP_MINUTES,
    MESSAGE_STATUS_SENT,
    MIN_INTER_SEND_GAP_MINUTES,
    SEND_OUTCOME_AMBIGUOUS,
    SEND_OUTCOME_FAILED,
    SEND_OUTCOME_SENT,
    SendAttemptOutcome,
    TRANSIENT_SEND_RETRY_COOLDOWN_MINUTES,
)
from .paths import ProjectPaths
from .records import new_canonical_id, now_utc_iso


FOLLOWUP_COMPONENT = "followup_worker"
FOLLOWUP_SEQUENCE_FIRST = 1
FOLLOWUP_ELIGIBILITY_DAYS = 4
FOLLOWUP_DRY_RUN_BATCH_SIZE = 25
FOLLOWUP_SCHEDULER_NAME = "job-hunt-copilot-followups"
FOLLOWUP_SCHEDULER_TYPE = "launchd"
FOLLOWUP_INTERVAL_SECONDS = 60
FOLLOWUP_INITIAL_AUTO_SEND_CAP = 10

OUTREACH_MODE_ROLE_TARGETED = "role_targeted"
OUTREACH_MODE_ROLE_TARGETED_FOLLOWUP = "role_targeted_followup"
LEGACY_FOLLOWUP_MODES = frozenset({"follow_up", OUTREACH_MODE_ROLE_TARGETED_FOLLOWUP})

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

SKIP_REASON_ALREADY_FOLLOWED_UP = "already_followed_up"
SKIP_REASON_BOUNCED = "bounced"
SKIP_REASON_REPLIED_IN_THREAD = "replied_in_thread"
SKIP_REASON_MISSING_THREAD_CONTEXT = "missing_followup_thread_context"
SKIP_REASON_MISSING_ORIGINAL_BODY = "missing_original_body"
SKIP_REASON_WAITING_FOR_PACING = "waiting_for_pacing"
SKIP_REASON_TRANSIENT_RETRY = "transient_send_retry_cooldown"
SKIP_REASON_AMBIGUOUS_SEND = "ambiguous_send_state"
SKIP_REASON_GROUNDING_INSUFFICIENT = "grounding_evidence_insufficient"
SKIP_REASON_CONTACT_HARD_STOP = "contact_hard_stop"

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
PROHIBITED_TEMPLATE_LEAK_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bpersisted jd mirror\b", re.IGNORECASE),
    re.compile(r"\brole-targeted tailoring\b", re.IGNORECASE),
    re.compile(r"\btailoring workspace\b", re.IGNORECASE),
    re.compile(r"\bjd mirror\b", re.IGNORECASE),
)
GENERIC_BACKGROUND_PHRASES = frozenset(
    {
        "software engineering",
        "backend systems",
        "cloud infrastructure",
        "production engineering",
        "backend systems, cloud infrastructure, and production engineering",
        "cloud infrastructure, backend systems, and production engineering",
    }
)
BOUNCE_SENDER_PATTERN = re.compile(r"\b(?:mailer-daemon|postmaster)\b", re.IGNORECASE)
EMAIL_RE = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.IGNORECASE)


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
class RenderedFollowUpDraft:
    body_text: str
    first_name_or_salutation: str
    background_fit_areas: str
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
                reason_code="missing_sender_identity",
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

        has_later_outbound = any(message["is_sender"] for message in post_original_messages)
        has_inbound_reply = any(not message["is_sender"] for message in post_original_messages)
        has_bounce = any(
            BOUNCE_SENDER_PATTERN.search(str(message.get("from", "")))
            or "delivery" in str(message.get("subject", "")).lower()
            and "fail" in str(message.get("subject", "")).lower()
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
                evidence={"messages": post_original_messages},
            )
        return ThreadInspectionResult(
            result="clear",
            checked_at=current_time,
            evidence={"messages": post_original_messages},
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


def run_followup_cycle(
    connection: sqlite3.Connection,
    *,
    project_root: Path | str,
    current_time: str | None = None,
    dry_run: bool = True,
    thread_inspector: FollowUpThreadInspector | None = None,
    sender: FollowUpSender | None = None,
    scheduler_name: str = FOLLOWUP_SCHEDULER_NAME,
    scheduler_type: str = FOLLOWUP_SCHEDULER_TYPE,
    batch_size: int | None = None,
) -> FollowUpCycleResult:
    paths = ProjectPaths.from_root(project_root)
    effective_time = current_time or now_utc_iso()
    started_at = effective_time
    cycle_run_id = new_canonical_id("followup_cycle_runs")
    resolved_batch_size = batch_size or FOLLOWUP_DRY_RUN_BATCH_SIZE
    resolved_inspector = thread_inspector or GmailThreadInspector(paths)
    resolved_sender = sender or GmailSameThreadFollowUpSender(paths)
    auto_send_enabled = (not dry_run) and _followup_auto_send_enabled(connection)
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
            current_time=effective_time,
            local_timezone=ZoneInfo("America/Phoenix"),
            limit=resolved_batch_size,
        )
        candidates = _load_candidate_plans(connection, current_time=effective_time, limit=resolved_batch_size)
        for candidate in candidates:
            counts["candidates_examined"] += 1
            last_checkpoint = candidate.outreach_followup_plan_id
            if not _is_due(candidate, effective_time):
                continue
            decision = _evaluate_candidate_stop_conditions(connection, candidate, effective_time)
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
                )
                continue

            rendered = render_followup_draft(
                paths,
                candidate,
                current_time=effective_time,
                dry_run=dry_run,
                thread_check=pre_draft_check,
                prior_followup_found=False,
                bounce_found=False,
            )
            if rendered is None:
                _mark_plan_status(
                    connection,
                    candidate.outreach_followup_plan_id,
                    PLAN_STATUS_HELD_FOR_REVIEW,
                    effective_time,
                    reason_code=SKIP_REASON_GROUNDING_INSUFFICIENT,
                    reply_check=pre_draft_check,
                )
                counts["held_for_review"] += 1
                if not dry_run:
                    artifact_paths.append(_write_followup_review_packet(paths, candidate, effective_time, SKIP_REASON_GROUNDING_INSUFFICIENT, "Could not render grounded follow-up fit areas.", None, pre_draft_check))
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
                    reason_code="followup_auto_send_disabled",
                    draft_artifact_path=rendered.draft_artifact_path,
                    review_evidence_artifact_path=rendered.review_evidence_artifact_path,
                    reply_check=pre_draft_check,
                )
                counts["held_for_review"] += 1
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
                _increment_initial_rollout_count(connection, effective_time)
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
                artifact_paths.append(_write_followup_review_packet(paths, candidate, effective_time, SKIP_REASON_AMBIGUOUS_SEND, send_outcome.message or "Gmail send state is ambiguous.", rendered, pre_send_check))
                continue
            _handle_failed_send(connection, paths, candidate, rendered, send_outcome, pre_send_check, effective_time, counts, artifact_paths)
    except Exception as exc:
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
    paths: ProjectPaths,
    candidate: FollowUpCandidate,
    *,
    current_time: str,
    dry_run: bool,
    thread_check: ThreadInspectionResult | None = None,
    prior_followup_found: bool = False,
    bounce_found: bool = False,
) -> RenderedFollowUpDraft | None:
    if not _normalize_optional_text(candidate.body_text):
        return None
    original_metadata = _load_original_send_metadata(paths, candidate)
    role_choice = _resolve_role_company(candidate, original_metadata)
    role_title = role_choice["role_title"]
    company_name = role_choice["company_name"]
    if not role_title or not company_name:
        return None
    salutation = _resolve_salutation(candidate)
    fit_choice = _derive_background_fit_areas(paths, candidate)
    if fit_choice is None:
        return None
    background_fit_areas = fit_choice["background_fit_areas"]
    body_text = (
        f"{salutation}\n\n"
        f"I wanted to briefly follow up on my earlier note about the {role_title} role at {company_name}.\n\n"
        f"I reached out because I believe the role could be a strong mutual fit with my background in {background_fit_areas}. "
        "I know you are busy, so I appreciate you taking the time to read this.\n\n"
        "If you are open to it, I would be grateful for a brief 15-minute conversation to hear your perspective on the role, "
        "the team, or what tends to matter in the process.\n\n"
        "If this is not relevant or not the right time, I completely understand and will not keep following up.\n\n"
        "Best,\n"
        "Achyutaram Sonti"
    )
    if not validate_followup_body(body_text, background_fit_areas=background_fit_areas):
        return None
    artifact_dir = _followup_artifact_dir(paths, candidate)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    draft_path = artifact_dir / "followup_draft.md"
    review_path = artifact_dir / "followup_review_evidence.json"
    draft_path.write_text(body_text + "\n", encoding="utf-8")
    evidence = {
        "dry_run": dry_run,
        "original_outreach_message_id": candidate.original_outreach_message_id,
        "outreach_followup_plan_id": candidate.outreach_followup_plan_id,
        "followup_sequence": candidate.followup_sequence,
        "template": "warmer_mutual_fit_first_followup",
        "role_title": role_title,
        "role_title_source": role_choice["role_title_source"],
        "company_name": company_name,
        "company_name_source": role_choice["company_name_source"],
        "salutation": salutation,
        "background_fit_areas": background_fit_areas,
        "grounding_sources": fit_choice["grounding_sources"],
        "grounding_fallbacks": fit_choice["grounding_fallbacks"],
        "original_send_metadata": {
            "source_path": original_metadata.source_path,
            "cc_emails": list(original_metadata.cc_emails),
            "message_id_header": original_metadata.message_id_header,
        },
        "rendered_at": current_time,
        "guards": {
            "approved_template": True,
            "short_signature": True,
            "no_attachments": True,
            "plain_text": True,
            "no_quoted_original": True,
            "no_metric_heavy_proof_points": True,
            "no_retired_template": True,
            "no_internal_artifact_text": True,
            "original_email_did_not_bounce": not bounce_found,
            "no_prior_followup": not prior_followup_found,
            "direct_thread_reply_check_clear": thread_check.safe_to_send if thread_check else None,
        },
        "thread_check": thread_check.as_dict() if thread_check else None,
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
        background_fit_areas=background_fit_areas,
        draft_artifact_path=str(paths.relative_to_root(draft_path)),
        review_evidence_artifact_path=str(paths.relative_to_root(review_path)),
        evidence=evidence,
    )


def validate_followup_body(body_text: str, *, background_fit_areas: str) -> bool:
    if not body_text.strip().endswith("Best,\nAchyutaram Sonti"):
        return False
    if "https://www.linkedin.com" in body_text or "602-" in body_text or "asonti1@asu.edu" in body_text:
        return False
    if any(pattern.search(body_text) for pattern in PROHIBITED_TEMPLATE_LEAK_PATTERNS):
        return False
    if any(char.isdigit() for char in background_fit_areas):
        return False
    normalized_background = _normalize_phrase(background_fit_areas)
    if normalized_background in GENERIC_BACKGROUND_PHRASES:
        return False
    if len([part.strip() for part in re.split(r",|\band\b", background_fit_areas) if part.strip()]) < 2:
        return False
    return True


def build_followup_dashboard_summary(connection: sqlite3.Connection, *, current_time: str | None = None) -> dict[str, Any]:
    effective_time = current_time or now_utc_iso()
    due_now = connection.execute(
        """
        SELECT COUNT(*) FROM outreach_followup_plans
        WHERE eligible_after <= ?
          AND plan_status IN ('pending', 'dry_run_ready', 'agent_reviewed', 'retryable')
        """,
        (effective_time,),
    ).fetchone()[0]
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
    current_time: str,
    local_timezone: ZoneInfo,
    limit: int,
) -> None:
    rows = connection.execute(
        """
        SELECT om.outreach_message_id, om.contact_id, om.job_posting_id, om.sent_at
        FROM outreach_messages om
        LEFT JOIN outreach_followup_plans fp
          ON fp.original_outreach_message_id = om.outreach_message_id
         AND fp.followup_sequence = ?
        WHERE om.outreach_mode = ?
          AND om.message_status = ?
          AND om.sent_at IS NOT NULL
          AND TRIM(om.sent_at) <> ''
          AND fp.outreach_followup_plan_id IS NULL
        ORDER BY om.sent_at ASC, om.outreach_message_id ASC
        LIMIT ?
        """,
        (FOLLOWUP_SEQUENCE_FIRST, OUTREACH_MODE_ROLE_TARGETED, MESSAGE_STATUS_SENT, limit),
    ).fetchall()
    with connection:
        for row in rows:
            sent_at = str(row["sent_at"])
            eligible_after = _eligible_after(sent_at, local_timezone)
            connection.execute(
                """
                INSERT OR IGNORE INTO outreach_followup_plans (
                  outreach_followup_plan_id, original_outreach_message_id, contact_id,
                  job_posting_id, plan_status, followup_sequence, eligible_after,
                  gmail_thread_id_snapshot, created_at, updated_at
                )
                SELECT ?, om.outreach_message_id, om.contact_id, om.job_posting_id,
                       ?, ?, ?, om.thread_id, ?, ?
                FROM outreach_messages om
                WHERE om.outreach_message_id = ?
                """,
                (
                    new_canonical_id("outreach_followup_plans"),
                    PLAN_STATUS_PENDING,
                    FOLLOWUP_SEQUENCE_FIRST,
                    eligible_after,
                    current_time,
                    current_time,
                    row["outreach_message_id"],
                ),
            )


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
          jp.jd_artifact_path,
          (
            SELECT rtr.final_resume_path
            FROM resume_tailoring_runs rtr
            WHERE rtr.job_posting_id = fp.job_posting_id
              AND rtr.resume_review_status = 'approved'
              AND rtr.final_resume_path IS NOT NULL
              AND TRIM(rtr.final_resume_path) <> ''
            ORDER BY COALESCE(rtr.completed_at, rtr.started_at, rtr.updated_at, rtr.created_at) DESC,
                     rtr.resume_tailoring_run_id DESC
            LIMIT 1
          ) AS tailored_resume_path
        FROM outreach_followup_plans fp
        JOIN outreach_messages om
          ON om.outreach_message_id = fp.original_outreach_message_id
        JOIN contacts c
          ON c.contact_id = fp.contact_id
        LEFT JOIN job_postings jp
          ON jp.job_posting_id = fp.job_posting_id
        WHERE fp.plan_status IN (?, ?, ?, ?, ?)
          AND (fp.next_retry_at IS NULL OR fp.next_retry_at <= ?)
        ORDER BY om.sent_at ASC, fp.outreach_followup_plan_id ASC
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
        tailored_resume_path=_normalize_optional_text(row["tailored_resume_path"]),
        plan_status=str(row["plan_status"]),
        retry_count=int(row["retry_count"] or 0),
        next_retry_at=_normalize_optional_text(row["next_retry_at"]),
    )


def _evaluate_candidate_stop_conditions(
    connection: sqlite3.Connection,
    candidate: FollowUpCandidate,
    current_time: str,
) -> dict[str, str] | None:
    del current_time
    if not _normalize_optional_text(candidate.body_text):
        return {"status": PLAN_STATUS_HELD_FOR_REVIEW, "reason_code": SKIP_REASON_MISSING_ORIGINAL_BODY}
    if _normalize_phrase(candidate.contact_status or "") in CONTACT_HARD_STOP_STATUSES:
        return {"status": PLAN_STATUS_SKIPPED, "reason_code": SKIP_REASON_CONTACT_HARD_STOP}
    if not candidate.thread_id:
        return {"status": PLAN_STATUS_HELD_FOR_REVIEW, "reason_code": SKIP_REASON_MISSING_THREAD_CONTEXT}
    if _has_delivery_event(connection, candidate, "bounced"):
        return {"status": PLAN_STATUS_SKIPPED, "reason_code": SKIP_REASON_BOUNCED}
    if _has_delivery_event(connection, candidate, "replied"):
        return {"status": PLAN_STATUS_SKIPPED, "reason_code": SKIP_REASON_REPLIED_IN_THREAD}
    if _has_existing_followup_evidence(connection, candidate):
        return {"status": PLAN_STATUS_SKIPPED, "reason_code": SKIP_REASON_ALREADY_FOLLOWED_UP}
    return None


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
    row = connection.execute(
        """
        SELECT 1
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
        LIMIT 1
        """,
        (
            candidate.original_outreach_message_id,
            MESSAGE_STATUS_SENT,
            candidate.thread_id,
            candidate.contact_id,
            candidate.job_posting_id,
            candidate.sent_at,
        ),
    ).fetchone()
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
        status = PLAN_STATUS_RETRYABLE
        reason = SKIP_REASON_TRANSIENT_RETRY
        counts["retryable_count"] += 1
        _schedule_retry(connection, candidate, current_time, inspection=inspection)
        return
    else:
        status = PLAN_STATUS_HELD_FOR_REVIEW
        reason = inspection.reason_code or SKIP_REASON_MISSING_THREAD_CONTEXT
        counts["held_for_review"] += 1
        if not dry_run:
            _write_followup_review_packet(paths, candidate, current_time, reason, inspection.message or "Thread check did not produce a safe-to-send result.", None, inspection)
    _mark_plan_status(
        connection,
        candidate.outreach_followup_plan_id,
        status,
        current_time,
        reason_code=reason,
        reply_check=inspection,
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
    artifact_paths.append(_write_followup_review_packet(paths, candidate, current_time, outcome.reason_code or "followup_send_failed", outcome.message or "Follow-up send failed.", rendered, inspection))


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
                last_skip_reason = NULL, draft_artifact_path = ?,
                review_evidence_artifact_path = ?, updated_at = ?
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
        "Inspect Gmail or repair metadata, then reset the follow-up plan only if the safety facts still allow sending.",
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
                "## Grounding Evidence",
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
        SKIP_REASON_GROUNDING_INSUFFICIENT: "Could not derive role-specific grounded background fit areas.",
        SKIP_REASON_AMBIGUOUS_SEND: "Gmail send state is ambiguous.",
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


def _derive_background_fit_areas(paths: ProjectPaths, candidate: FollowUpCandidate) -> dict[str, Any] | None:
    original_body = _strip_signature(candidate.body_text)
    jd_text = _read_optional_project_file(paths, candidate.jd_artifact_path)
    tailored_resume_text = _read_optional_project_file(paths, candidate.tailored_resume_path)
    profile_text = "" if tailored_resume_text else _read_profile_skills(paths)
    evidence_parts = [
        ("original_email_body", original_body, True),
        ("jd_artifact", jd_text, bool(jd_text)),
        ("tailored_resume", tailored_resume_text, bool(tailored_resume_text)),
        ("profile_fallback", profile_text, bool(profile_text)),
    ]
    evidence_text = "\n".join(part for _, part, include in evidence_parts if include and part).lower()
    phrase_specs: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("Java services", ("java", "spring", "jakarta")),
        ("Go/Golang services", ("golang", " go ", "kubernetes resource")),
        ("Python systems", ("python", "fastapi")),
        ("Scala data services", ("scala",)),
        ("AWS data pipelines", ("aws", "emr", "s3", "lambda", "sqs")),
        ("Spark pipelines", ("spark", "etl", "databricks")),
        ("REST APIs", ("rest", "api", "apis", "microservice")),
        ("distributed systems", ("distributed", "high-availability", "event-driven", "grpc")),
        ("Kubernetes infrastructure", ("kubernetes", "docker", "container")),
        ("Terraform automation", ("terraform", "infrastructure provisioning")),
        ("AI/ML systems", ("machine learning", " ai ", " llm", "generative ai", "ml ")),
        ("production reliability", ("uptime", "monitoring", "reliability", "sla", "production")),
        ("full-stack development", ("react", "typescript", "frontend", "full stack")),
        ("security and identity", ("security", "identity", "iam", "oauth")),
    )
    selected: list[str] = []
    for phrase, keywords in phrase_specs:
        if any(keyword in evidence_text for keyword in keywords):
            selected.append(phrase)
        if len(selected) == 3:
            break
    if len(selected) < 2:
        return None
    if len(selected) == 2:
        phrase = " and ".join(selected)
    else:
        phrase = f"{selected[0]}, {selected[1]}, and {selected[2]}"
    if _normalize_phrase(phrase) in GENERIC_BACKGROUND_PHRASES:
        return None
    grounding_sources = {
        "original_email_body": True,
        "jd_artifact": bool(jd_text),
        "tailored_resume": bool(tailored_resume_text),
        "profile_fallback": bool(profile_text),
    }
    grounding_fallbacks: list[str] = []
    if not jd_text:
        grounding_fallbacks.append("missing_jd_artifact")
    if not tailored_resume_text and profile_text:
        grounding_fallbacks.append("profile_used_for_missing_tailored_resume")
    if not tailored_resume_text and not profile_text:
        grounding_fallbacks.append("original_email_only")
    return {
        "background_fit_areas": phrase,
        "grounding_sources": grounding_sources,
        "grounding_fallbacks": grounding_fallbacks,
    }


def _resolve_role_company(candidate: FollowUpCandidate, metadata: OriginalSendMetadata) -> dict[str, str | None]:
    body_pair = _extract_role_company_from_original_body(candidate.body_text)
    subject_pair = _extract_role_company_from_subject(candidate.subject)
    role_title = body_pair.get("role_title") or subject_pair.get("role_title") or metadata.role_title or _clean_template_field(candidate.role_title)
    company_name = body_pair.get("company_name") or subject_pair.get("company_name") or metadata.company_name or _clean_template_field(candidate.company_name)
    return {
        "role_title": role_title,
        "role_title_source": (
            "original_email_body"
            if body_pair.get("role_title")
            else "original_subject"
            if subject_pair.get("role_title")
            else "original_send_metadata"
            if metadata.role_title
            else "canonical_database"
            if candidate.role_title
            else None
        ),
        "company_name": company_name,
        "company_name_source": (
            "original_email_body"
            if body_pair.get("company_name")
            else "original_subject"
            if subject_pair.get("company_name")
            else "original_send_metadata"
            if metadata.company_name
            else "canonical_database"
            if candidate.company_name
            else None
        ),
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
    if "@" in normalized or normalized.lower() in {"unknown", "none", "n/a", "hiring", "team"}:
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


def _load_original_send_metadata(paths: ProjectPaths, candidate: FollowUpCandidate) -> OriginalSendMetadata:
    payload = _load_original_send_result_payload(paths, candidate)
    if payload is None:
        return OriginalSendMetadata(
            source_path=None,
            cc_emails=(),
            message_id_header=None,
            role_title=None,
            company_name=None,
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
    source_path = _normalize_optional_text(payload.get("_source_path"))
    return OriginalSendMetadata(
        source_path=source_path,
        cc_emails=cc_values,
        message_id_header=message_id_header,
        role_title=_clean_template_field(payload.get("role_title")),
        company_name=_clean_template_field(payload.get("company_name")),
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


def _read_profile_skills(paths: ProjectPaths) -> str:
    profile_path = paths.assets_dir / "resume-tailoring" / "profile.md"
    if not profile_path.exists():
        return ""
    return profile_path.read_text(encoding="utf-8")


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


def _increment_initial_rollout_count(connection: sqlite3.Connection, current_time: str) -> None:
    row = connection.execute(
        """
        SELECT control_value
        FROM agent_control_state
        WHERE control_key = ?
        """,
        (FOLLOWUP_INITIAL_ROLLOUT_SENT_COUNT_KEY,),
    ).fetchone()
    try:
        count = int(row["control_value"]) if row is not None else 0
    except ValueError:
        count = 0
    count += 1
    updates = [(FOLLOWUP_INITIAL_ROLLOUT_SENT_COUNT_KEY, str(count), current_time)]
    if count >= FOLLOWUP_INITIAL_AUTO_SEND_CAP:
        updates.append((FOLLOWUP_AUTO_SEND_PAUSED_KEY, "true", current_time))
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


def _count_followups_sent_today(connection: sqlite3.Connection, current_time: str) -> int:
    current_local_date = _parse_iso_datetime(current_time).astimezone(ZoneInfo("America/Phoenix")).date()
    rows = connection.execute(
        """
        SELECT sent_at FROM outreach_messages
        WHERE outreach_mode = ?
          AND message_status = ?
          AND sent_at IS NOT NULL
        """,
        (OUTREACH_MODE_ROLE_TARGETED_FOLLOWUP, MESSAGE_STATUS_SENT),
    ).fetchall()
    return sum(
        1
        for row in rows
        if _parse_iso_datetime(str(row["sent_at"])).astimezone(ZoneInfo("America/Phoenix")).date() == current_local_date
    )


def _increment_count_for_reason(counts: dict[str, int], reason_code: str) -> None:
    if reason_code == SKIP_REASON_REPLIED_IN_THREAD:
        counts["skipped_replied"] += 1
    elif reason_code == SKIP_REASON_BOUNCED:
        counts["skipped_bounced"] += 1
    elif reason_code == SKIP_REASON_ALREADY_FOLLOWED_UP:
        counts["skipped_already_followed_up"] += 1
    elif reason_code == SKIP_REASON_WAITING_FOR_PACING:
        counts["waiting_for_pacing_count"] += 1
    elif reason_code == SKIP_REASON_TRANSIENT_RETRY:
        counts["retryable_count"] += 1
    else:
        counts["blocked_count"] += 1


def _is_due(candidate: FollowUpCandidate, current_time: str) -> bool:
    return _parse_iso_datetime(candidate.eligible_after) <= _parse_iso_datetime(current_time)


def _eligible_after(sent_at: str, local_timezone: ZoneInfo) -> str:
    sent_dt = _parse_iso_datetime(sent_at)
    local_dt = sent_dt.astimezone(local_timezone) + timedelta(days=FOLLOWUP_ELIGIBILITY_DAYS)
    return _isoformat_utc(local_dt.astimezone(UTC))


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


def _clean_template_field(value: str | None) -> str | None:
    normalized = _normalize_optional_text(value)
    if normalized is None:
        return None
    return re.sub(r"\s+", " ", normalized)


def _extract_role_company_from_original_body(body_text: str) -> dict[str, str | None]:
    patterns = (
        r"about the (?P<role>.+?) role at (?P<company>[A-Z0-9][^\n.,;:!?|]*?)(?:\s+because\b|[.\n,;:!?|]|$)",
        r"the (?P<role>.+?) opening at (?P<company>[A-Z0-9][^\n.,;:!?|]*?)(?:\s+and\b|\s+because\b|[.\n,;:!?|]|$)",
    )
    match = None
    for pattern in patterns:
        match = re.search(pattern, body_text, re.IGNORECASE)
        if match:
            break
    if not match:
        return {"role_title": None, "company_name": None}
    return {
        "role_title": _clean_template_field(match.group("role")),
        "company_name": _clean_company_name(match.group("company")),
    }


def _extract_role_company_from_subject(subject: str | None) -> dict[str, str | None]:
    normalized = _normalize_optional_text(subject)
    if normalized is None:
        return {"role_title": None, "company_name": None}
    cleaned = re.sub(r"^(?:re|fwd?):\s*", "", normalized, flags=re.IGNORECASE).strip()
    match = re.match(r"(?P<role>.+?)\s+at\s+(?P<company>.+)$", cleaned, re.IGNORECASE)
    if not match:
        return {"role_title": None, "company_name": None}
    return {
        "role_title": _clean_template_field(match.group("role")),
        "company_name": _clean_company_name(match.group("company")),
    }


def _strip_signature(body_text: str) -> str:
    lines = body_text.splitlines()
    for index, line in enumerate(lines):
        if line.strip().lower() in {"best,", "best", "thanks,", "thank you,"}:
            return "\n".join(lines[:index]).strip()
    return body_text


def _clean_company_name(value: str | None) -> str | None:
    normalized = _clean_template_field(value)
    if normalized is None:
        return None
    normalized = re.sub(r"\s*\|\s*Impact:\s*\d+\s*$", "", normalized, flags=re.IGNORECASE)
    return _clean_template_field(normalized)


def _extract_first_email(value: str) -> str | None:
    match = EMAIL_RE.search(value)
    return match.group(0) if match else None


def _load_sender_email(paths: ProjectPaths) -> str | None:
    profile_path = paths.assets_dir / "resume-tailoring" / "profile.md"
    if not profile_path.exists():
        return None
    match = re.search(r"^- \*\*Email:\*\*\s*(?P<email>\S+@\S+)\s*$", profile_path.read_text(encoding="utf-8"), re.MULTILINE)
    return _normalize_email(match.group("email")) if match else None


def _gmail_headers(raw_message: Mapping[str, Any]) -> dict[str, str]:
    payload = raw_message.get("payload") if isinstance(raw_message, Mapping) else None
    headers = payload.get("headers", []) if isinstance(payload, Mapping) else []
    result: dict[str, str] = {}
    for header in headers:
        if not isinstance(header, Mapping):
            continue
        name = _normalize_optional_text(header.get("name"))
        value = _normalize_optional_text(header.get("value"))
        if name and value:
            result[name.lower()] = value
    return result


def _gmail_message_datetime(raw_message: Mapping[str, Any]) -> datetime | None:
    internal_date = _normalize_optional_text(raw_message.get("internalDate"))
    if internal_date:
        try:
            return datetime.fromtimestamp(int(internal_date) / 1000, tz=UTC)
        except ValueError:
            return None
    return None


def _gmail_sent_at_from_response(response: Mapping[str, Any]) -> str:
    internal_date = _normalize_optional_text(response.get("internalDate"))
    if internal_date:
        try:
            return _isoformat_utc(datetime.fromtimestamp(int(internal_date) / 1000, tz=UTC))
        except ValueError:
            pass
    return now_utc_iso()
