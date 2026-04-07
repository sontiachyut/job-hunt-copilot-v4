from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import parse_qs, urlparse

from .artifacts import write_json_contract
from .contracts import CONTRACT_VERSION
from .paths import ProjectPaths, workspace_slug
from .records import now_utc_iso


LINKEDIN_SCRAPING_COMPONENT = "linkedin_scraping"

SOURCE_MODE_GMAIL_JOB_ALERT = "gmail_job_alert"
SOURCE_TYPE_GMAIL_LINKEDIN_ALERT = "gmail_linkedin_job_alert_email"

BODY_REPRESENTATION_TEXT_PLAIN = "text_plain"
BODY_REPRESENTATION_TEXT_HTML_DERIVED = "text_html_derived"

PARSE_OUTCOME_PARSED_CARDS = "parsed_cards"
PARSE_OUTCOME_ZERO_CARDS = "zero_cards"

ZERO_CARD_REVIEW_THRESHOLD = 3

CARD_SEPARATOR_RE = re.compile(r"(?m)^\s*[-_]{3,}\s*$")
JOB_URL_RE = re.compile(r"https?://(?:www\.)?linkedin\.com/jobs/view/[^\s<>()]+", re.IGNORECASE)
JOB_ID_FROM_URL_RE = re.compile(r"/jobs/view/(?:[^/?#]*/)?(?P<job_id>\d+)(?:[/?#]|$)", re.IGNORECASE)
ANCHOR_RE = re.compile(
    r'(?is)<a\b[^>]*href=["\'](?P<href>[^"\']+)["\'][^>]*>(?P<label>.*?)</a>'
)
TAG_RE = re.compile(r"(?is)<[^>]+>")
LOCATION_HINT_RE = re.compile(
    r"\b(remote|hybrid|on[\s-]?site|onsite|united states|usa|canada|europe|uk)\b|,\s*[A-Z]{2}\b",
    re.IGNORECASE,
)
HTML_BLOCK_TAG_RE = re.compile(r"(?i)</?(?:br|p|div|li|tr|td|table|section|article|ul|ol|h[1-6])\b[^>]*>")
MULTILINE_BLANKS_RE = re.compile(r"\n{3,}")
LEADING_BULLET_RE = re.compile(r"^[\s\u2022\-*]+")

GLOBAL_NOISE_LINES = frozenset(
    {
        "linkedin",
        "jobs you may be interested in",
        "see all jobs",
        "view all jobs",
        "job alerts",
        "manage preferences",
        "unsubscribe",
        "was this email helpful?",
        "update your preferences",
    }
)
CARD_NOISE_LINES = frozenset(
    {
        "view job",
        "save",
        "dismiss",
        "apply",
        "easy apply",
        "apply now",
        "manage preferences",
        "unsubscribe",
    }
)


class GmailAlertError(ValueError):
    """Raised when Gmail alert ingestion input is invalid."""


@dataclass(frozen=True)
class GmailAlertMessage:
    gmail_message_id: str
    gmail_thread_id: str | None
    sender: str
    subject: str
    received_at: str
    ingestion_run_id: str
    collected_at: str
    text_plain_body: str | None = None
    text_html_body: str | None = None

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, Any],
        *,
        default_ingestion_run_id: str | None = None,
        default_collected_at: str | None = None,
    ) -> "GmailAlertMessage":
        gmail_message_id = _normalize_required_text(payload.get("gmail_message_id"), field_name="gmail_message_id")
        if "/" in gmail_message_id or "\\" in gmail_message_id:
            raise GmailAlertError("gmail_message_id cannot contain path separators.")

        text_plain_body = _normalize_optional_body_text(payload.get("text_plain_body"))
        text_html_body = _normalize_optional_body_text(payload.get("text_html_body"))
        if text_plain_body is None and text_html_body is None:
            raise GmailAlertError(
                "Gmail alert messages must include at least one of `text_plain_body` or `text_html_body`."
            )

        ingestion_run_id = _normalize_optional_text(payload.get("ingestion_run_id")) or default_ingestion_run_id
        if ingestion_run_id is None:
            raise GmailAlertError("ingestion_run_id is required for Gmail alert ingestion.")

        return cls(
            gmail_message_id=gmail_message_id,
            gmail_thread_id=_normalize_optional_text(payload.get("gmail_thread_id")),
            sender=_normalize_required_text(payload.get("sender"), field_name="sender"),
            subject=_normalize_required_text(payload.get("subject"), field_name="subject"),
            received_at=_normalize_utc_timestamp(payload.get("received_at"), field_name="received_at"),
            ingestion_run_id=_normalize_required_text(ingestion_run_id, field_name="ingestion_run_id"),
            collected_at=_normalize_utc_timestamp(
                payload.get("collected_at") or default_collected_at or now_utc_iso(),
                field_name="collected_at",
            ),
            text_plain_body=text_plain_body,
            text_html_body=text_html_body,
        )

    def available_body_representations(self) -> list[str]:
        available: list[str] = []
        if self.text_plain_body is not None:
            available.append(BODY_REPRESENTATION_TEXT_PLAIN)
        if self.text_html_body is not None:
            available.append(BODY_REPRESENTATION_TEXT_HTML_DERIVED)
        return available

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_mode": SOURCE_MODE_GMAIL_JOB_ALERT,
            "gmail_message_id": self.gmail_message_id,
            "gmail_thread_id": self.gmail_thread_id,
            "sender": self.sender,
            "subject": self.subject,
            "received_at": self.received_at,
            "ingestion_run_id": self.ingestion_run_id,
            "collected_at": self.collected_at,
            "text_plain_body": self.text_plain_body,
            "text_html_body": self.text_html_body,
        }


@dataclass(frozen=True)
class GmailAlertBatch:
    ingestion_run_id: str
    messages: tuple[GmailAlertMessage, ...]

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "GmailAlertBatch":
        ingestion_run_id = _normalize_required_text(payload.get("ingestion_run_id"), field_name="ingestion_run_id")
        raw_messages = payload.get("messages")
        if not isinstance(raw_messages, Sequence) or isinstance(raw_messages, (str, bytes)):
            raise GmailAlertError("messages must be an array of Gmail message payloads.")

        messages = tuple(
            GmailAlertMessage.from_mapping(
                item,
                default_ingestion_run_id=ingestion_run_id,
                default_collected_at=now_utc_iso(),
            )
            for item in raw_messages
            if isinstance(item, Mapping)
        )
        if not messages:
            raise GmailAlertError("messages must contain at least one Gmail message payload.")
        return cls(ingestion_run_id=ingestion_run_id, messages=messages)


@dataclass(frozen=True)
class ParsedGmailAlertCard:
    card_index: int
    role_title: str
    company_name: str
    location: str | None
    badge_lines: tuple[str, ...]
    job_url: str | None
    job_id: str | None
    gmail_message_id: str
    synthetic_identity_key: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "card_index": self.card_index,
            "role_title": self.role_title,
            "company_name": self.company_name,
            "location": self.location,
            "badge_lines": list(self.badge_lines),
            "job_url": self.job_url,
            "job_id": self.job_id,
            "gmail_message_id": self.gmail_message_id,
            "synthetic_identity_key": self.synthetic_identity_key,
        }


@dataclass(frozen=True)
class GmailAlertParseResult:
    body_representation_used: str
    attempted_body_representations: tuple[str, ...]
    parse_outcome: str
    selected_body_text: str
    cards: tuple[ParsedGmailAlertCard, ...]

    @property
    def parseable_job_card_count(self) -> int:
        return len(self.cards)


@dataclass(frozen=True)
class GmailCollectionResult:
    gmail_message_id: str
    gmail_thread_id: str | None
    created: bool
    duplicate: bool
    collection_dir: Path
    email_markdown_path: Path
    email_json_path: Path
    job_cards_path: Path
    parse_outcome: str
    parseable_job_card_count: int
    body_representation_used: str | None
    zero_card_review_required: bool
    zero_card_trigger_reason: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "gmail_message_id": self.gmail_message_id,
            "gmail_thread_id": self.gmail_thread_id,
            "created": self.created,
            "duplicate": self.duplicate,
            "collection_dir": str(self.collection_dir),
            "email_markdown_path": str(self.email_markdown_path),
            "email_json_path": str(self.email_json_path),
            "job_cards_path": str(self.job_cards_path),
            "parse_outcome": self.parse_outcome,
            "parseable_job_card_count": self.parseable_job_card_count,
            "body_representation_used": self.body_representation_used,
            "zero_card_review_required": self.zero_card_review_required,
            "zero_card_trigger_reason": self.zero_card_trigger_reason,
        }


@dataclass(frozen=True)
class GmailAlertBatchIngestionResult:
    ingestion_run_id: str
    messages_seen: int
    collections_created: int
    duplicates_ignored: int
    zero_card_messages: int
    review_required_zero_card_messages: int
    collection_results: tuple[GmailCollectionResult, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "ingestion_run_id": self.ingestion_run_id,
            "messages_seen": self.messages_seen,
            "collections_created": self.collections_created,
            "duplicates_ignored": self.duplicates_ignored,
            "zero_card_messages": self.zero_card_messages,
            "review_required_zero_card_messages": self.review_required_zero_card_messages,
            "collections": [result.as_dict() for result in self.collection_results],
        }


@dataclass(frozen=True)
class _ExistingCollectionMetadata:
    gmail_message_id: str
    gmail_thread_id: str | None
    collection_dir: Path
    email_markdown_path: Path
    email_json_path: Path
    job_cards_path: Path
    parse_outcome: str
    parseable_job_card_count: int
    body_representation_used: str | None
    zero_card_review_required: bool
    zero_card_review_resolved: bool


@dataclass(frozen=True)
class _PendingCollection:
    message: GmailAlertMessage
    parse_result: GmailAlertParseResult
    collection_dir: Path
    email_markdown_path: Path
    email_json_path: Path
    job_cards_path: Path


def load_gmail_alert_batch(batch_path: Path | str) -> GmailAlertBatch:
    payload = json.loads(Path(batch_path).read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise GmailAlertError("Gmail alert batch JSON must be an object.")
    return GmailAlertBatch.from_mapping(payload)


def parse_gmail_alert_message(message: GmailAlertMessage | Mapping[str, Any]) -> GmailAlertParseResult:
    normalized = message if isinstance(message, GmailAlertMessage) else GmailAlertMessage.from_mapping(message)

    attempted_representations: list[str] = []
    plain_text_result: GmailAlertParseResult | None = None
    if normalized.text_plain_body is not None:
        attempted_representations.append(BODY_REPRESENTATION_TEXT_PLAIN)
        plain_cards = _parse_cards_from_body(
            normalized.text_plain_body,
            gmail_message_id=normalized.gmail_message_id,
        )
        plain_text_result = GmailAlertParseResult(
            body_representation_used=BODY_REPRESENTATION_TEXT_PLAIN,
            attempted_body_representations=tuple(attempted_representations),
            parse_outcome=_parse_outcome_for_cards(plain_cards),
            selected_body_text=normalized.text_plain_body,
            cards=plain_cards,
        )
        if plain_cards or normalized.text_html_body is None:
            return plain_text_result

    if normalized.text_html_body is not None:
        attempted_representations.append(BODY_REPRESENTATION_TEXT_HTML_DERIVED)
        derived_text = _html_to_text(normalized.text_html_body)
        html_cards = _parse_cards_from_body(
            derived_text,
            gmail_message_id=normalized.gmail_message_id,
        )
        return GmailAlertParseResult(
            body_representation_used=BODY_REPRESENTATION_TEXT_HTML_DERIVED,
            attempted_body_representations=tuple(attempted_representations),
            parse_outcome=_parse_outcome_for_cards(html_cards),
            selected_body_text=derived_text,
            cards=html_cards,
        )

    if plain_text_result is None:
        raise GmailAlertError("No usable message bodies were available for parsing.")
    return plain_text_result


def ingest_gmail_alert_batch(
    project_root: Path | str | None = None,
    *,
    batch: GmailAlertBatch | Mapping[str, Any],
) -> GmailAlertBatchIngestionResult:
    paths = ProjectPaths.from_root(project_root)
    normalized_batch = batch if isinstance(batch, GmailAlertBatch) else GmailAlertBatch.from_mapping(batch)

    existing_index = _existing_collection_index(paths)
    existing_unresolved_zero_card_count = sum(
        1
        for metadata in existing_index.values()
        if metadata.parse_outcome == PARSE_OUTCOME_ZERO_CARDS and not metadata.zero_card_review_resolved
    )

    ordered_slots: list[tuple[str, Any]] = []
    pending_by_message_id: dict[str, _PendingCollection] = {}

    for message in normalized_batch.messages:
        existing_metadata = existing_index.get(message.gmail_message_id)
        if existing_metadata is not None:
            ordered_slots.append(("existing_duplicate", existing_metadata))
            continue

        pending_metadata = pending_by_message_id.get(message.gmail_message_id)
        if pending_metadata is not None:
            ordered_slots.append(("batch_duplicate", message.gmail_message_id))
            continue

        parse_result = parse_gmail_alert_message(message)
        collection_dir = _collection_dir(paths, message.received_at, message.gmail_message_id)
        pending = _PendingCollection(
            message=message,
            parse_result=parse_result,
            collection_dir=collection_dir,
            email_markdown_path=collection_dir / "email.md",
            email_json_path=collection_dir / "email.json",
            job_cards_path=collection_dir / "job-cards.json",
        )
        pending_by_message_id[message.gmail_message_id] = pending
        ordered_slots.append(("created", message.gmail_message_id))

    zero_card_messages_in_run = [
        pending
        for pending in pending_by_message_id.values()
        if pending.parse_result.parse_outcome == PARSE_OUTCOME_ZERO_CARDS
    ]
    zero_card_run_count = len(zero_card_messages_in_run)
    cumulative_unresolved_zero_card_count = existing_unresolved_zero_card_count + zero_card_run_count

    created_results: dict[str, GmailCollectionResult] = {}
    for gmail_message_id, pending in pending_by_message_id.items():
        zero_card_review = _build_zero_card_review_metadata(
            parse_result=pending.parse_result,
            zero_card_run_count=zero_card_run_count,
            cumulative_unresolved_zero_card_count=cumulative_unresolved_zero_card_count,
        )
        _persist_collection_unit(
            paths,
            pending=pending,
            zero_card_review=zero_card_review,
        )
        created_results[gmail_message_id] = GmailCollectionResult(
            gmail_message_id=pending.message.gmail_message_id,
            gmail_thread_id=pending.message.gmail_thread_id,
            created=True,
            duplicate=False,
            collection_dir=pending.collection_dir,
            email_markdown_path=pending.email_markdown_path,
            email_json_path=pending.email_json_path,
            job_cards_path=pending.job_cards_path,
            parse_outcome=pending.parse_result.parse_outcome,
            parseable_job_card_count=pending.parse_result.parseable_job_card_count,
            body_representation_used=pending.parse_result.body_representation_used,
            zero_card_review_required=bool(zero_card_review["review_required"]),
            zero_card_trigger_reason=zero_card_review["trigger_reason"],
        )

    collection_results: list[GmailCollectionResult] = []
    for slot_type, slot_value in ordered_slots:
        if slot_type == "created":
            collection_results.append(created_results[slot_value])
            continue

        if slot_type == "existing_duplicate":
            metadata = slot_value
        else:
            created_result = created_results[slot_value]
            metadata = _ExistingCollectionMetadata(
                gmail_message_id=created_result.gmail_message_id,
                gmail_thread_id=created_result.gmail_thread_id,
                collection_dir=created_result.collection_dir,
                email_markdown_path=created_result.email_markdown_path,
                email_json_path=created_result.email_json_path,
                job_cards_path=created_result.job_cards_path,
                parse_outcome=created_result.parse_outcome,
                parseable_job_card_count=created_result.parseable_job_card_count,
                body_representation_used=created_result.body_representation_used,
                zero_card_review_required=created_result.zero_card_review_required,
                zero_card_review_resolved=False,
            )

        collection_results.append(
            GmailCollectionResult(
                gmail_message_id=metadata.gmail_message_id,
                gmail_thread_id=metadata.gmail_thread_id,
                created=False,
                duplicate=True,
                collection_dir=metadata.collection_dir,
                email_markdown_path=metadata.email_markdown_path,
                email_json_path=metadata.email_json_path,
                job_cards_path=metadata.job_cards_path,
                parse_outcome=metadata.parse_outcome,
                parseable_job_card_count=metadata.parseable_job_card_count,
                body_representation_used=metadata.body_representation_used,
                zero_card_review_required=metadata.zero_card_review_required,
                zero_card_trigger_reason="already_collected",
            )
        )

    return GmailAlertBatchIngestionResult(
        ingestion_run_id=normalized_batch.ingestion_run_id,
        messages_seen=len(normalized_batch.messages),
        collections_created=sum(1 for result in collection_results if result.created),
        duplicates_ignored=sum(1 for result in collection_results if result.duplicate),
        zero_card_messages=sum(1 for result in collection_results if result.created and result.parse_outcome == PARSE_OUTCOME_ZERO_CARDS),
        review_required_zero_card_messages=sum(
            1
            for result in collection_results
            if result.created and result.parse_outcome == PARSE_OUTCOME_ZERO_CARDS and result.zero_card_review_required
        ),
        collection_results=tuple(collection_results),
    )


def _persist_collection_unit(
    paths: ProjectPaths,
    *,
    pending: _PendingCollection,
    zero_card_review: Mapping[str, Any],
) -> None:
    pending.collection_dir.mkdir(parents=True, exist_ok=True)
    pending.email_markdown_path.write_text(
        _render_email_markdown(pending.message, pending.parse_result),
        encoding="utf-8",
    )
    write_json_contract(
        pending.email_json_path,
        producer_component=LINKEDIN_SCRAPING_COMPONENT,
        result="success",
        payload={
            "source_mode": SOURCE_MODE_GMAIL_JOB_ALERT,
            "source_type": SOURCE_TYPE_GMAIL_LINKEDIN_ALERT,
            "gmail_message_id": pending.message.gmail_message_id,
            "gmail_thread_id": pending.message.gmail_thread_id,
            "sender": pending.message.sender,
            "subject": pending.message.subject,
            "received_at": pending.message.received_at,
            "collected_at": pending.message.collected_at,
            "ingestion_run_id": pending.message.ingestion_run_id,
            "collection_dir": paths.relative_to_root(pending.collection_dir).as_posix(),
            "body_representations_available": pending.message.available_body_representations(),
            "body_representation_used": pending.parse_result.body_representation_used,
            "parse_attempts": [
                {
                    "body_representation": representation,
                    "attempted": True,
                }
                for representation in pending.parse_result.attempted_body_representations
            ],
            "parse_outcome": pending.parse_result.parse_outcome,
            "parseable_job_card_count": pending.parse_result.parseable_job_card_count,
            "selected_body_text": pending.parse_result.selected_body_text,
            "job_cards_path": paths.relative_to_root(pending.job_cards_path).as_posix(),
            "lead_fanout_ready": pending.parse_result.parseable_job_card_count > 0,
            "zero_card_review": dict(zero_card_review),
        },
        produced_at=pending.message.collected_at,
    )
    write_json_contract(
        pending.job_cards_path,
        producer_component=LINKEDIN_SCRAPING_COMPONENT,
        result="success",
        payload={
            "source_mode": SOURCE_MODE_GMAIL_JOB_ALERT,
            "gmail_message_id": pending.message.gmail_message_id,
            "gmail_thread_id": pending.message.gmail_thread_id,
            "ingestion_run_id": pending.message.ingestion_run_id,
            "body_representation_used": pending.parse_result.body_representation_used,
            "parse_outcome": pending.parse_result.parse_outcome,
            "parseable_job_card_count": pending.parse_result.parseable_job_card_count,
            "cards": [card.as_dict() for card in pending.parse_result.cards],
        },
        produced_at=pending.message.collected_at,
    )


def _existing_collection_index(paths: ProjectPaths) -> dict[str, _ExistingCollectionMetadata]:
    index: dict[str, _ExistingCollectionMetadata] = {}
    for email_json_path in sorted(paths.gmail_runtime_dir.glob("*/email.json")):
        collection_dir = email_json_path.parent
        email_markdown_path = collection_dir / "email.md"
        job_cards_path = collection_dir / "job-cards.json"
        if not email_markdown_path.exists() or not job_cards_path.exists():
            continue

        try:
            payload = json.loads(email_json_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, Mapping):
            continue

        gmail_message_id = _normalize_optional_text(payload.get("gmail_message_id"))
        if gmail_message_id is None:
            continue

        zero_card_review = payload.get("zero_card_review")
        zero_card_review_required = False
        zero_card_review_resolved = False
        if isinstance(zero_card_review, Mapping):
            zero_card_review_required = bool(zero_card_review.get("review_required"))
            zero_card_review_resolved = bool(zero_card_review.get("review_resolved"))

        try:
            parseable_job_card_count = int(payload.get("parseable_job_card_count", 0))
        except (TypeError, ValueError):
            parseable_job_card_count = 0

        index[gmail_message_id] = _ExistingCollectionMetadata(
            gmail_message_id=gmail_message_id,
            gmail_thread_id=_normalize_optional_text(payload.get("gmail_thread_id")),
            collection_dir=collection_dir,
            email_markdown_path=email_markdown_path,
            email_json_path=email_json_path,
            job_cards_path=job_cards_path,
            parse_outcome=_normalize_optional_text(payload.get("parse_outcome")) or PARSE_OUTCOME_ZERO_CARDS,
            parseable_job_card_count=parseable_job_card_count,
            body_representation_used=_normalize_optional_text(payload.get("body_representation_used")),
            zero_card_review_required=zero_card_review_required,
            zero_card_review_resolved=zero_card_review_resolved,
        )
    return index


def _build_zero_card_review_metadata(
    *,
    parse_result: GmailAlertParseResult,
    zero_card_run_count: int,
    cumulative_unresolved_zero_card_count: int,
) -> dict[str, Any]:
    if parse_result.parse_outcome != PARSE_OUTCOME_ZERO_CARDS:
        return {
            "threshold": ZERO_CARD_REVIEW_THRESHOLD,
            "review_required": False,
            "trigger_reason": None,
            "zero_card_count_in_run": 0,
            "cumulative_unresolved_zero_card_count": cumulative_unresolved_zero_card_count,
            "review_resolved": False,
        }

    review_required = False
    trigger_reason = None
    if zero_card_run_count > ZERO_CARD_REVIEW_THRESHOLD:
        review_required = True
        trigger_reason = "run_threshold_exceeded"
    elif cumulative_unresolved_zero_card_count > ZERO_CARD_REVIEW_THRESHOLD:
        review_required = True
        trigger_reason = "history_threshold_exceeded"

    return {
        "threshold": ZERO_CARD_REVIEW_THRESHOLD,
        "review_required": review_required,
        "trigger_reason": trigger_reason,
        "zero_card_count_in_run": zero_card_run_count,
        "cumulative_unresolved_zero_card_count": cumulative_unresolved_zero_card_count,
        "review_resolved": False,
    }


def _collection_dir(paths: ProjectPaths, received_at: str, gmail_message_id: str) -> Path:
    timestamp = _normalize_utc_timestamp(received_at, field_name="received_at")
    collection_key = _collection_timestamp_key(timestamp)
    return paths.gmail_runtime_dir / f"{collection_key}-{gmail_message_id}"


def _collection_timestamp_key(timestamp: str) -> str:
    parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(timezone.utc)
    return parsed.strftime("%Y%m%dT%H%M%SZ")


def _render_email_markdown(message: GmailAlertMessage, parse_result: GmailAlertParseResult) -> str:
    lines = [
        "# Gmail Alert Email",
        "",
        f"- source_mode: {SOURCE_MODE_GMAIL_JOB_ALERT}",
        f"- source_type: {SOURCE_TYPE_GMAIL_LINKEDIN_ALERT}",
        f"- gmail_message_id: {message.gmail_message_id}",
        f"- gmail_thread_id: {message.gmail_thread_id or ''}",
        f"- sender: {message.sender}",
        f"- subject: {message.subject}",
        f"- received_at: {message.received_at}",
        f"- collected_at: {message.collected_at}",
        f"- ingestion_run_id: {message.ingestion_run_id}",
        f"- body_representation_used: {parse_result.body_representation_used}",
        f"- parse_outcome: {parse_result.parse_outcome}",
        f"- parseable_job_card_count: {parse_result.parseable_job_card_count}",
        "",
        "## Email Body",
        "",
        parse_result.selected_body_text.rstrip(),
        "",
    ]
    return "\n".join(lines)


def _parse_cards_from_body(body_text: str, *, gmail_message_id: str) -> tuple[ParsedGmailAlertCard, ...]:
    normalized_body = _normalize_body_text(body_text)
    if normalized_body is None:
        return ()

    raw_blocks = _candidate_blocks(normalized_body)
    cards: list[ParsedGmailAlertCard] = []
    seen_keys: set[tuple[str, str]] = set()

    for raw_block in raw_blocks:
        parsed = _parse_card_block(raw_block, gmail_message_id=gmail_message_id)
        if parsed is None:
            continue
        dedupe_key = _card_dedupe_key(parsed)
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)
        cards.append(
            ParsedGmailAlertCard(
                card_index=len(cards) + 1,
                role_title=parsed.role_title,
                company_name=parsed.company_name,
                location=parsed.location,
                badge_lines=parsed.badge_lines,
                job_url=parsed.job_url,
                job_id=parsed.job_id,
                gmail_message_id=parsed.gmail_message_id,
                synthetic_identity_key=parsed.synthetic_identity_key,
            )
        )
    return tuple(cards)


def _candidate_blocks(body_text: str) -> list[str]:
    if CARD_SEPARATOR_RE.search(body_text):
        cleaned_blocks = [segment.strip() for segment in CARD_SEPARATOR_RE.split(body_text) if segment.strip()]
        if cleaned_blocks:
            return cleaned_blocks
    return [body_text]


def _parse_card_block(block_text: str, *, gmail_message_id: str) -> ParsedGmailAlertCard | None:
    if "view job" not in block_text.lower() and JOB_URL_RE.search(block_text) is None:
        return None

    lines = [_clean_card_line(line) for line in block_text.splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return None

    data_lines: list[str] = []
    for line in lines:
        normalized = line.lower()
        if normalized in GLOBAL_NOISE_LINES:
            continue
        if normalized in CARD_NOISE_LINES:
            break
        if JOB_URL_RE.search(line):
            break
        data_lines.append(line)

    data_lines = _trim_leading_noise_lines(data_lines)
    if len(data_lines) < 2:
        return None

    role_title = data_lines[0]
    company_name = data_lines[1]
    remaining = data_lines[2:]
    location = None
    if remaining and _looks_like_location(remaining[0]):
        location = remaining[0]
        remaining = remaining[1:]

    badge_lines = tuple(line for line in remaining if line.lower() not in CARD_NOISE_LINES)
    job_url = _extract_job_url(block_text)
    job_id = _extract_job_id(job_url)
    synthetic_identity_key = _synthetic_identity_key(job_id=job_id, job_url=job_url, card=None)

    return ParsedGmailAlertCard(
        card_index=0,
        role_title=role_title,
        company_name=company_name,
        location=location,
        badge_lines=badge_lines,
        job_url=job_url,
        job_id=job_id,
        gmail_message_id=gmail_message_id,
        synthetic_identity_key=synthetic_identity_key,
    )


def _card_dedupe_key(card: ParsedGmailAlertCard) -> tuple[str, str]:
    if card.job_id:
        return ("job_id", card.job_id)
    if card.job_url:
        return ("job_url", card.job_url)
    return (
        "summary",
        "|".join(
            [
                workspace_slug(card.role_title),
                workspace_slug(card.company_name),
                workspace_slug(card.location or "unknown"),
            ]
        ),
    )


def _parse_outcome_for_cards(cards: Sequence[ParsedGmailAlertCard]) -> str:
    return PARSE_OUTCOME_PARSED_CARDS if cards else PARSE_OUTCOME_ZERO_CARDS


def _html_to_text(html_body: str) -> str:
    rendered = html_body
    rendered = ANCHOR_RE.sub(_replace_anchor_with_preserved_href, rendered)
    rendered = HTML_BLOCK_TAG_RE.sub("\n", rendered)
    rendered = TAG_RE.sub("", rendered)
    rendered = unescape(rendered)
    rendered = rendered.replace("\r\n", "\n").replace("\r", "\n")
    rendered = MULTILINE_BLANKS_RE.sub("\n\n", rendered)
    return rendered.strip() + "\n" if rendered.strip() else ""


def _replace_anchor_with_preserved_href(match: re.Match[str]) -> str:
    href = unescape(match.group("href")).strip()
    label = _clean_card_line(_html_to_text(match.group("label")))
    parts = [part for part in (label, href) if part]
    return "\n".join(parts)


def _extract_job_url(block_text: str) -> str | None:
    match = JOB_URL_RE.search(block_text)
    if match is None:
        return None
    return _normalize_job_url(match.group(0))


def _normalize_job_url(job_url: str) -> str:
    parsed = urlparse(job_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return job_url.strip()

    job_id = _extract_job_id(job_url)
    if job_id is not None:
        return f"https://www.linkedin.com/jobs/view/{job_id}/"

    path = re.sub(r"/+", "/", parsed.path.rstrip("/"))
    return f"https://www.linkedin.com{path}"


def _extract_job_id(job_url: str | None) -> str | None:
    if not job_url:
        return None

    match = JOB_ID_FROM_URL_RE.search(job_url)
    if match is not None:
        return match.group("job_id")

    parsed = urlparse(job_url)
    query_values = parse_qs(parsed.query)
    current_job_ids = query_values.get("currentJobId")
    if current_job_ids:
        current_job_id = current_job_ids[0].strip()
        if current_job_id:
            return current_job_id
    return None


def _synthetic_identity_key(
    *,
    job_id: str | None,
    job_url: str | None,
    card: ParsedGmailAlertCard | None,
) -> str | None:
    if job_id is not None:
        return None
    if job_url is None:
        return None
    return "|".join(["gmail_alert_card_url", workspace_slug(job_url)])


def _looks_like_location(line: str) -> bool:
    if LOCATION_HINT_RE.search(line):
        return True
    return bool("," in line and len(line.split()) <= 8)


def _trim_leading_noise_lines(lines: Sequence[str]) -> list[str]:
    trimmed = list(lines)
    while trimmed and trimmed[0].lower() in GLOBAL_NOISE_LINES:
        trimmed.pop(0)
    return trimmed


def _clean_card_line(line: str) -> str:
    normalized = line.replace("\xa0", " ").strip()
    normalized = LEADING_BULLET_RE.sub("", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _normalize_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise GmailAlertError("Expected string input for Gmail alert fields.")
    normalized = value.strip()
    return normalized if normalized else None


def _normalize_required_text(value: Any, *, field_name: str) -> str:
    normalized = _normalize_optional_text(value)
    if normalized is None:
        raise GmailAlertError(f"{field_name} is required.")
    return normalized


def _normalize_optional_body_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise GmailAlertError("Expected string input for Gmail alert body fields.")
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    return normalized if normalized.strip() else None


def _normalize_body_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    normalized = MULTILINE_BLANKS_RE.sub("\n\n", normalized)
    return normalized.strip() + "\n" if normalized.strip() else None


def _normalize_utc_timestamp(value: Any, *, field_name: str) -> str:
    raw_text = _normalize_required_text(value, field_name=field_name)
    try:
        parsed = datetime.fromisoformat(raw_text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GmailAlertError(f"{field_name} must be a valid ISO-8601 timestamp.") from exc

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
