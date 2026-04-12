from __future__ import annotations

import base64
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import parse_qs, urlparse

from .artifacts import write_json_contract
from .contracts import CONTRACT_VERSION
from .paths import ProjectPaths, workspace_slug
from .records import now_utc_iso
from .secrets import GMAIL_CLIENT_SECRET_FILENAME, GMAIL_TOKEN_FILENAME


LINKEDIN_SCRAPING_COMPONENT = "linkedin_scraping"

SOURCE_MODE_GMAIL_JOB_ALERT = "gmail_job_alert"
SOURCE_TYPE_GMAIL_LINKEDIN_ALERT = "gmail_linkedin_job_alert_email"

BODY_REPRESENTATION_TEXT_PLAIN = "text_plain"
BODY_REPRESENTATION_TEXT_HTML_DERIVED = "text_html_derived"

PARSE_OUTCOME_PARSED_CARDS = "parsed_cards"
PARSE_OUTCOME_ZERO_CARDS = "zero_cards"

ZERO_CARD_REVIEW_THRESHOLD = 3
DEFAULT_GMAIL_POLL_SENDERS = ("jobalerts-noreply@linkedin.com",)
DEFAULT_GMAIL_POLL_WINDOW_DAYS = 30
DEFAULT_GMAIL_POLL_MAX_NEW_MESSAGES = 10
DEFAULT_GMAIL_POLL_PAGE_SIZE = 25
DEFAULT_GMAIL_POLL_MAX_SCAN_PAGES = 4

CARD_SEPARATOR_RE = re.compile(r"(?m)^\s*[-_]{3,}\s*$")
JOB_URL_RE = re.compile(
    r"https?://(?:www\.)?linkedin\.com/(?:comm/)?jobs/view/[^\s<>()]+",
    re.IGNORECASE,
)
JOB_ID_FROM_URL_RE = re.compile(
    r"/(?:comm/)?jobs/view/(?:[^/?#]*/)?(?P<job_id>\d+)(?:[/?#]|$)",
    re.IGNORECASE,
)
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
DIGEST_MATCH_COUNT_RE = re.compile(r"^\d+\+?\s+new jobs match your preferences\.?$", re.IGNORECASE)

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


class GmailMailboxPollingError(RuntimeError):
    """Raised when the live Gmail mailbox collector cannot prepare a bounded batch."""


class GmailMailboxHistoryCheckpointError(GmailMailboxPollingError):
    """Raised when the persisted Gmail mailbox history checkpoint can no longer be used."""


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
    mailbox_history_id_before: str | None = None
    mailbox_history_id_after: str | None = None
    poll_strategy: str = "recent_search"

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
        return cls(
            ingestion_run_id=ingestion_run_id,
            messages=messages,
            mailbox_history_id_before=_normalize_optional_text(payload.get("mailbox_history_id_before")),
            mailbox_history_id_after=_normalize_optional_text(payload.get("mailbox_history_id_after")),
            poll_strategy=_normalize_optional_text(payload.get("poll_strategy")) or "recent_search",
        )


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


@dataclass(frozen=True)
class GmailCollectionRefreshResult:
    gmail_message_id: str
    gmail_thread_id: str | None
    received_at: str
    collected_at: str
    ingestion_run_id: str
    collection_dir: Path
    email_markdown_path: Path
    email_json_path: Path
    job_cards_path: Path
    body_representation_used: str
    parse_outcome: str
    parseable_job_card_count: int
    selected_body_text: str
    cards: tuple[ParsedGmailAlertCard, ...]

    def as_collection_result(self) -> GmailCollectionResult:
        return GmailCollectionResult(
            gmail_message_id=self.gmail_message_id,
            gmail_thread_id=self.gmail_thread_id,
            created=False,
            duplicate=False,
            collection_dir=self.collection_dir,
            email_markdown_path=self.email_markdown_path,
            email_json_path=self.email_json_path,
            job_cards_path=self.job_cards_path,
            parse_outcome=self.parse_outcome,
            parseable_job_card_count=self.parseable_job_card_count,
            body_representation_used=self.body_representation_used,
            zero_card_review_required=False,
            zero_card_trigger_reason=None,
        )

    def as_message(self) -> GmailAlertMessage:
        payload = json.loads(self.email_json_path.read_text(encoding="utf-8"))
        text_html_body = None
        if isinstance(payload, Mapping):
            text_html_body = _normalize_optional_body_text(payload.get("text_html_body"))
        return GmailAlertMessage(
            gmail_message_id=self.gmail_message_id,
            gmail_thread_id=self.gmail_thread_id,
            sender="LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>",
            subject="LinkedIn job alerts",
            received_at=self.received_at,
            ingestion_run_id=self.ingestion_run_id,
            collected_at=self.collected_at,
            text_plain_body=self.selected_body_text,
            text_html_body=text_html_body,
        )

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


class GmailLinkedInAlertMailboxCollector:
    def __init__(
        self,
        paths: ProjectPaths,
        *,
        service_factory: Callable[[], Any] | None = None,
        senders: Sequence[str] = DEFAULT_GMAIL_POLL_SENDERS,
        window_days: int = DEFAULT_GMAIL_POLL_WINDOW_DAYS,
        max_new_messages: int = DEFAULT_GMAIL_POLL_MAX_NEW_MESSAGES,
        page_size: int = DEFAULT_GMAIL_POLL_PAGE_SIZE,
        max_scan_pages: int = DEFAULT_GMAIL_POLL_MAX_SCAN_PAGES,
    ) -> None:
        self._paths = paths
        self._service_factory = service_factory or (lambda: _build_gmail_service(paths))
        self._senders = tuple(
            sender.strip().lower()
            for sender in senders
            if isinstance(sender, str) and sender.strip()
        )
        self._window_days = max(1, int(window_days))
        self._max_new_messages = max(1, int(max_new_messages))
        self._page_size = max(1, int(page_size))
        self._max_scan_pages = max(1, int(max_scan_pages))
        self._prepared_batches: dict[str, GmailAlertBatch] = {}

    def prepare_batch(
        self,
        *,
        current_time: str,
        mailbox_history_checkpoint: str | None = None,
    ) -> GmailAlertBatch | None:
        ingestion_run_id = _gmail_auto_ingestion_run_id(current_time)
        prepared_batch = self._prepared_batches.get(ingestion_run_id)
        if prepared_batch is not None:
            return prepared_batch

        existing_index = _existing_collection_index(self._paths)
        service = self._service_factory()
        checkpoint_before = _normalize_optional_text(mailbox_history_checkpoint)
        checkpoint_after = _gmail_current_mailbox_history_id(service)
        poll_strategy = "recent_search_bootstrap"
        if checkpoint_before:
            try:
                message_refs = _list_incremental_uncollected_gmail_message_refs(
                    service,
                    start_history_id=checkpoint_before,
                    senders=self._senders,
                    existing_message_ids=set(existing_index.keys()),
                    max_new_messages=self._max_new_messages,
                    page_size=self._page_size,
                    max_scan_pages=self._max_scan_pages,
                )
                poll_strategy = "history_checkpoint"
            except GmailMailboxHistoryCheckpointError:
                message_refs = _list_uncollected_gmail_message_refs(
                    service,
                    senders=self._senders,
                    existing_message_ids=set(existing_index.keys()),
                    window_days=self._window_days,
                    max_new_messages=self._max_new_messages,
                    page_size=self._page_size,
                    max_scan_pages=self._max_scan_pages,
                )
                poll_strategy = "history_checkpoint_reset_recent_search"
        else:
            message_refs = _list_uncollected_gmail_message_refs(
                service,
                senders=self._senders,
                existing_message_ids=set(existing_index.keys()),
                window_days=self._window_days,
                max_new_messages=self._max_new_messages,
                page_size=self._page_size,
                max_scan_pages=self._max_scan_pages,
            )
        if not message_refs:
            if checkpoint_before is None and checkpoint_after is not None:
                batch = GmailAlertBatch(
                    ingestion_run_id=ingestion_run_id,
                    messages=(),
                    mailbox_history_id_before=None,
                    mailbox_history_id_after=checkpoint_after,
                    poll_strategy="history_checkpoint_seed",
                )
                self._prepared_batches[ingestion_run_id] = batch
                return batch
            return None

        messages = [
            _fetch_gmail_alert_message(
                service,
                gmail_message_id=ref["id"],
                ingestion_run_id=ingestion_run_id,
                collected_at=current_time,
            )
            for ref in message_refs
        ]
        messages.sort(key=lambda message: (message.received_at, message.gmail_message_id))
        batch = GmailAlertBatch(
            ingestion_run_id=ingestion_run_id,
            messages=tuple(messages),
            mailbox_history_id_before=checkpoint_before,
            mailbox_history_id_after=checkpoint_after,
            poll_strategy=poll_strategy,
        )
        self._prepared_batches[ingestion_run_id] = batch
        return batch

    def peek_prepared_batch(self, ingestion_run_id: str) -> GmailAlertBatch | None:
        return self._prepared_batches.get(ingestion_run_id)

    def pop_prepared_batch(self, ingestion_run_id: str) -> GmailAlertBatch | None:
        return self._prepared_batches.pop(ingestion_run_id, None)


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


def gmail_mailbox_polling_configured(paths: ProjectPaths) -> bool:
    return (
        (paths.secrets_dir / GMAIL_CLIENT_SECRET_FILENAME).exists()
        and (paths.secrets_dir / GMAIL_TOKEN_FILENAME).exists()
    )


def _gmail_auto_ingestion_run_id(current_time: str) -> str:
    return "gmail-auto-" + _collection_timestamp_key(current_time)


def _build_gmail_service(paths: ProjectPaths) -> Any:
    try:
        from googleapiclient.discovery import build
    except ModuleNotFoundError as exc:  # pragma: no cover - bootstrap guards this in runtime
        raise GmailMailboxPollingError(
            "google-api-python-client is required for autonomous Gmail polling."
        ) from exc

    credentials = _load_gmail_credentials(paths)
    return build("gmail", "v1", credentials=credentials, cache_discovery=False)


def _load_gmail_credentials(paths: ProjectPaths) -> Any:
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
    except ModuleNotFoundError as exc:  # pragma: no cover - bootstrap guards this in runtime
        raise GmailMailboxPollingError(
            "google-auth is required for autonomous Gmail polling."
        ) from exc

    client_secret_path = paths.secrets_dir / GMAIL_CLIENT_SECRET_FILENAME
    token_path = paths.secrets_dir / GMAIL_TOKEN_FILENAME
    if not client_secret_path.exists():
        raise GmailMailboxPollingError(
            f"Gmail client secret file is missing: {client_secret_path}"
        )
    if not token_path.exists():
        raise GmailMailboxPollingError(
            f"Gmail token file is missing: {token_path}"
        )

    client_secret_payload = json.loads(client_secret_path.read_text(encoding="utf-8"))
    token_payload = json.loads(token_path.read_text(encoding="utf-8"))
    if not isinstance(client_secret_payload, Mapping):
        raise GmailMailboxPollingError("Gmail client secret JSON must be an object.")
    if not isinstance(token_payload, Mapping):
        raise GmailMailboxPollingError("Gmail token JSON must be an object.")

    client_config = client_secret_payload.get("installed") or client_secret_payload.get("web")
    if not isinstance(client_config, Mapping):
        raise GmailMailboxPollingError(
            "Gmail client secret JSON must contain an `installed` or `web` OAuth client block."
        )

    authorized_user_info = dict(token_payload)
    for key in ("client_id", "client_secret", "token_uri"):
        if key not in authorized_user_info and client_config.get(key):
            authorized_user_info[key] = client_config[key]
    scopes = token_payload.get("scopes")
    if not isinstance(scopes, Sequence) or isinstance(scopes, (str, bytes)):
        scopes = ("https://www.googleapis.com/auth/gmail.readonly",)

    credentials = Credentials.from_authorized_user_info(
        authorized_user_info,
        scopes=list(scopes),
    )
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
    if not credentials.valid:
        raise GmailMailboxPollingError(
            "Gmail credentials are invalid or expired and could not be refreshed."
        )
    return credentials


def _gmail_current_mailbox_history_id(service: Any) -> str | None:
    try:
        payload = service.users().getProfile(userId="me").execute()
    except Exception as exc:  # pragma: no cover - depends on live Gmail API surfaces
        raise GmailMailboxPollingError("Gmail API failed to load mailbox profile historyId.") from exc
    if not isinstance(payload, Mapping):
        raise GmailMailboxPollingError("Gmail mailbox profile payload is malformed.")
    return _normalize_optional_text(payload.get("historyId"))


def _list_uncollected_gmail_message_refs(
    service: Any,
    *,
    senders: Sequence[str],
    existing_message_ids: set[str],
    window_days: int,
    max_new_messages: int,
    page_size: int,
    max_scan_pages: int,
) -> list[dict[str, str]]:
    selected: list[dict[str, str]] = []
    seen_message_ids = set(existing_message_ids)

    for sender in senders:
        next_page_token: str | None = None
        scanned_pages = 0
        query = f"from:{sender} newer_than:{window_days}d"
        while scanned_pages < max_scan_pages and len(selected) < max_new_messages:
            response = (
                service.users()
                .messages()
                .list(
                    userId="me",
                    q=query,
                    maxResults=page_size,
                    pageToken=next_page_token,
                    includeSpamTrash=False,
                )
                .execute()
            )
            for raw_message in response.get("messages", []) or []:
                if not isinstance(raw_message, Mapping):
                    continue
                gmail_message_id = _normalize_optional_text(raw_message.get("id"))
                if gmail_message_id is None or gmail_message_id in seen_message_ids:
                    continue
                seen_message_ids.add(gmail_message_id)
                selected.append(
                    {
                        "id": gmail_message_id,
                        "threadId": _normalize_optional_text(raw_message.get("threadId")) or "",
                    }
                )
                if len(selected) >= max_new_messages:
                    break
            next_page_token = _normalize_optional_text(response.get("nextPageToken"))
            scanned_pages += 1
            if next_page_token is None:
                break
    return selected


def _list_incremental_uncollected_gmail_message_refs(
    service: Any,
    *,
    start_history_id: str,
    senders: Sequence[str],
    existing_message_ids: set[str],
    max_new_messages: int,
    page_size: int,
    max_scan_pages: int,
) -> list[dict[str, str]]:
    selected: list[dict[str, str]] = []
    seen_message_ids = set(existing_message_ids)
    next_page_token: str | None = None
    scanned_pages = 0

    while scanned_pages < max_scan_pages and len(selected) < max_new_messages:
        try:
            response = (
                service.users()
                .history()
                .list(
                    userId="me",
                    startHistoryId=start_history_id,
                    historyTypes=["messageAdded"],
                    maxResults=page_size,
                    pageToken=next_page_token,
                )
                .execute()
            )
        except Exception as exc:  # pragma: no cover - depends on live Gmail API surfaces
            if _is_stale_gmail_history_checkpoint_error(exc):
                raise GmailMailboxHistoryCheckpointError(
                    f"Gmail mailbox history checkpoint {start_history_id!r} is stale."
                ) from exc
            raise GmailMailboxPollingError(
                f"Gmail history polling failed for checkpoint {start_history_id!r}."
            ) from exc

        if not isinstance(response, Mapping):
            raise GmailMailboxPollingError("Gmail history response payload is malformed.")

        for raw_history in response.get("history", []) or []:
            for raw_message in _history_added_messages(raw_history):
                gmail_message_id = _normalize_optional_text(raw_message.get("id"))
                if gmail_message_id is None or gmail_message_id in seen_message_ids:
                    continue
                if not _gmail_message_sender_matches(service, gmail_message_id=gmail_message_id, senders=senders):
                    continue
                seen_message_ids.add(gmail_message_id)
                selected.append(
                    {
                        "id": gmail_message_id,
                        "threadId": _normalize_optional_text(raw_message.get("threadId")) or "",
                    }
                )
                if len(selected) >= max_new_messages:
                    break
            if len(selected) >= max_new_messages:
                break

        next_page_token = _normalize_optional_text(response.get("nextPageToken"))
        scanned_pages += 1
        if next_page_token is None:
            break
    return selected


def _history_added_messages(history_row: Any) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(history_row, Mapping):
        return ()
    messages_added = history_row.get("messagesAdded")
    if isinstance(messages_added, Sequence) and not isinstance(messages_added, (str, bytes)):
        extracted: list[Mapping[str, Any]] = []
        for item in messages_added:
            if not isinstance(item, Mapping):
                continue
            message = item.get("message")
            if isinstance(message, Mapping):
                extracted.append(message)
        if extracted:
            return tuple(extracted)

    raw_messages = history_row.get("messages")
    if not isinstance(raw_messages, Sequence) or isinstance(raw_messages, (str, bytes)):
        return ()
    return tuple(item for item in raw_messages if isinstance(item, Mapping))


def _gmail_message_sender_matches(
    service: Any,
    *,
    gmail_message_id: str,
    senders: Sequence[str],
) -> bool:
    if not senders:
        return True
    payload = (
        service.users()
        .messages()
        .get(
            userId="me",
            id=gmail_message_id,
            format="metadata",
            metadataHeaders=["From"],
        )
        .execute()
    )
    headers = _gmail_headers(payload.get("payload")) if isinstance(payload, Mapping) else {}
    sender_value = (headers.get("from") or "").strip().lower()
    return any(expected_sender in sender_value for expected_sender in senders)


def _is_stale_gmail_history_checkpoint_error(exc: Exception) -> bool:
    status = getattr(getattr(exc, "resp", None), "status", None)
    if status == 404:
        return True
    message = str(exc).lower()
    return "starthistoryid" in message and (
        "too old" in message or "invalid" in message or "not found" in message
    )


def _fetch_gmail_alert_message(
    service: Any,
    *,
    gmail_message_id: str,
    ingestion_run_id: str,
    collected_at: str,
) -> GmailAlertMessage:
    payload = (
        service.users()
        .messages()
        .get(userId="me", id=gmail_message_id, format="full")
        .execute()
    )
    if not isinstance(payload, Mapping):
        raise GmailMailboxPollingError(
            f"Gmail API returned a malformed payload for message {gmail_message_id!r}."
        )

    headers = _gmail_headers(payload.get("payload"))
    text_plain_body, text_html_body = _extract_gmail_message_bodies(payload.get("payload"))
    subject = headers.get("subject") or "LinkedIn job alerts"
    sender = headers.get("from") or "jobalerts-noreply@linkedin.com"
    received_at = _gmail_received_at(payload, headers=headers, fallback=collected_at)
    return GmailAlertMessage.from_mapping(
        {
            "gmail_message_id": gmail_message_id,
            "gmail_thread_id": _normalize_optional_text(payload.get("threadId")),
            "sender": sender,
            "subject": subject,
            "received_at": received_at,
            "ingestion_run_id": ingestion_run_id,
            "collected_at": collected_at,
            "text_plain_body": text_plain_body,
            "text_html_body": text_html_body,
        }
    )


def _gmail_headers(payload: Any) -> dict[str, str]:
    if not isinstance(payload, Mapping):
        return {}
    raw_headers = payload.get("headers")
    if not isinstance(raw_headers, Sequence) or isinstance(raw_headers, (str, bytes)):
        return {}

    headers: dict[str, str] = {}
    for raw_header in raw_headers:
        if not isinstance(raw_header, Mapping):
            continue
        name = _normalize_optional_text(raw_header.get("name"))
        value = _normalize_optional_text(raw_header.get("value"))
        if name is None or value is None:
            continue
        headers[name.lower()] = value
    return headers


def _gmail_received_at(
    payload: Mapping[str, Any],
    *,
    headers: Mapping[str, str],
    fallback: str,
) -> str:
    internal_date = _normalize_optional_text(payload.get("internalDate"))
    if internal_date is not None:
        try:
            epoch_millis = int(internal_date)
        except ValueError:
            epoch_millis = -1
        if epoch_millis >= 0:
            return (
                datetime.fromtimestamp(epoch_millis / 1000, tz=timezone.utc)
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z")
            )

    date_header = headers.get("date")
    if date_header:
        try:
            parsed = parsedate_to_datetime(date_header)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return (
                parsed.astimezone(timezone.utc)
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z")
            )
        except (TypeError, ValueError):
            pass
    return _normalize_utc_timestamp(fallback, field_name="collected_at")


def _extract_gmail_message_bodies(payload: Any) -> tuple[str | None, str | None]:
    plain_parts: list[str] = []
    html_parts: list[str] = []

    def visit(part: Any) -> None:
        if not isinstance(part, Mapping):
            return
        mime_type = _normalize_optional_text(part.get("mimeType")) or ""
        body = part.get("body")
        if isinstance(body, Mapping):
            data = _normalize_optional_text(body.get("data"))
            if data:
                decoded = _decode_gmail_body_data(data)
                if mime_type == "text/plain":
                    plain_parts.append(decoded)
                elif mime_type == "text/html":
                    html_parts.append(decoded)
        raw_parts = part.get("parts")
        if isinstance(raw_parts, Sequence) and not isinstance(raw_parts, (str, bytes)):
            for child in raw_parts:
                visit(child)

    visit(payload)
    plain_text = "\n\n".join(part.strip() for part in plain_parts if part.strip()) or None
    html_text = "\n\n".join(part.strip() for part in html_parts if part.strip()) or None
    return plain_text, html_text


def _decode_gmail_body_data(data: str) -> str:
    padding = "=" * (-len(data) % 4)
    decoded = base64.urlsafe_b64decode(data + padding)
    return decoded.decode("utf-8", errors="replace")


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


def refresh_persisted_gmail_collection(
    project_root: Path | str | None = None,
    *,
    collection_dir: Path | str,
) -> GmailCollectionRefreshResult:
    paths = ProjectPaths.from_root(project_root)
    resolved_collection_dir = _resolve_gmail_collection_dir_reference(paths, collection_dir)
    email_markdown_path = resolved_collection_dir / "email.md"
    email_json_path = resolved_collection_dir / "email.json"
    job_cards_path = resolved_collection_dir / "job-cards.json"
    if not email_json_path.exists():
        raise GmailAlertError(
            f"Persisted Gmail collection is missing email.json at {email_json_path}."
        )
    if not email_markdown_path.exists():
        raise GmailAlertError(
            f"Persisted Gmail collection is missing email.md at {email_markdown_path}."
        )

    payload = json.loads(email_json_path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise GmailAlertError(
            f"Persisted Gmail collection payload at {email_json_path} must be a mapping."
        )

    gmail_message_id = _normalize_required_text(
        payload.get("gmail_message_id"),
        field_name="gmail_message_id",
    )
    selected_body_text = _normalize_optional_body_text(payload.get("selected_body_text"))
    if selected_body_text is None:
        raise GmailAlertError(
            f"Persisted Gmail collection at {email_json_path} does not include selected_body_text."
        )

    body_representation_used = (
        _normalize_optional_text(payload.get("body_representation_used"))
        or BODY_REPRESENTATION_TEXT_PLAIN
    )
    cards = _parse_cards_from_body(selected_body_text, gmail_message_id=gmail_message_id)
    parse_outcome = _parse_outcome_for_cards(cards)
    parseable_job_card_count = len(cards)
    produced_at = now_utc_iso()

    updated_email_payload = {
        key: value
        for key, value in payload.items()
        if key not in {"contract_version", "produced_at", "producer_component", "result"}
    }
    updated_email_payload.update(
        {
            "collection_dir": paths.relative_to_root(resolved_collection_dir).as_posix(),
            "body_representation_used": body_representation_used,
            "parse_outcome": parse_outcome,
            "parseable_job_card_count": parseable_job_card_count,
            "selected_body_text": selected_body_text,
            "job_cards_path": paths.relative_to_root(job_cards_path).as_posix(),
            "lead_fanout_ready": parseable_job_card_count > 0,
        }
    )
    write_json_contract(
        email_json_path,
        producer_component=LINKEDIN_SCRAPING_COMPONENT,
        result="success",
        payload=updated_email_payload,
        produced_at=produced_at,
    )
    write_json_contract(
        job_cards_path,
        producer_component=LINKEDIN_SCRAPING_COMPONENT,
        result="success",
        payload={
            "source_mode": SOURCE_MODE_GMAIL_JOB_ALERT,
            "gmail_message_id": gmail_message_id,
            "gmail_thread_id": _normalize_optional_text(payload.get("gmail_thread_id")),
            "ingestion_run_id": _normalize_required_text(
                payload.get("ingestion_run_id"),
                field_name="ingestion_run_id",
            ),
            "body_representation_used": body_representation_used,
            "parse_outcome": parse_outcome,
            "parseable_job_card_count": parseable_job_card_count,
            "cards": [card.as_dict() for card in cards],
        },
        produced_at=produced_at,
    )

    return GmailCollectionRefreshResult(
        gmail_message_id=gmail_message_id,
        gmail_thread_id=_normalize_optional_text(payload.get("gmail_thread_id")),
        received_at=_normalize_utc_timestamp(payload.get("received_at"), field_name="received_at"),
        collected_at=_normalize_utc_timestamp(
            payload.get("collected_at"),
            field_name="collected_at",
        ),
        ingestion_run_id=_normalize_required_text(
            payload.get("ingestion_run_id"),
            field_name="ingestion_run_id",
        ),
        collection_dir=resolved_collection_dir,
        email_markdown_path=email_markdown_path,
        email_json_path=email_json_path,
        job_cards_path=job_cards_path,
        body_representation_used=body_representation_used,
        parse_outcome=parse_outcome,
        parseable_job_card_count=parseable_job_card_count,
        selected_body_text=selected_body_text,
        cards=cards,
    )


def _resolve_gmail_collection_dir_reference(paths: ProjectPaths, collection_dir: Path | str) -> Path:
    normalized_ref = str(collection_dir).split("#", 1)[0]
    resolved = paths.resolve_from_root(normalized_ref)
    if resolved.name in {"job-cards.json", "email.json"}:
        return resolved.parent
    if resolved.is_file():
        return resolved.parent
    return resolved


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


def persist_gmail_checkpoint_seed(
    paths: ProjectPaths,
    *,
    prepared_batch: GmailAlertBatch,
    collected_at: str,
) -> Path:
    seed_path = paths.gmail_runtime_dir / "_checkpoint-seeds" / f"{prepared_batch.ingestion_run_id}.json"
    write_json_contract(
        seed_path,
        producer_component=LINKEDIN_SCRAPING_COMPONENT,
        result="success",
        payload={
            "source_mode": SOURCE_MODE_GMAIL_JOB_ALERT,
            "ingestion_run_id": prepared_batch.ingestion_run_id,
            "mailbox_history_id_before": prepared_batch.mailbox_history_id_before,
            "mailbox_history_id_after": prepared_batch.mailbox_history_id_after,
            "poll_strategy": prepared_batch.poll_strategy,
            "seeded_without_messages": True,
        },
        produced_at=collected_at,
    )
    return seed_path


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
    if _looks_like_digest_summary_line(role_title) or _looks_like_digest_summary_line(company_name):
        return None
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
    return f"https://www.linkedin.com{path}/"


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
    return "|".join(["gmail_alert_job_url", job_url])


def _looks_like_location(line: str) -> bool:
    if LOCATION_HINT_RE.search(line):
        return True
    return bool("," in line and len(line.split()) <= 8)


def _trim_leading_noise_lines(lines: Sequence[str]) -> list[str]:
    trimmed = list(lines)
    while trimmed and (
        trimmed[0].lower() in GLOBAL_NOISE_LINES
        or _looks_like_alert_intro_line(trimmed[0])
        or _looks_like_digest_summary_line(trimmed[0])
    ):
        trimmed.pop(0)
    return trimmed


def _looks_like_alert_intro_line(line: str) -> bool:
    normalized = line.lower()
    return (
        "job alert has been created" in normalized
        or "receive notifications when new jobs are posted" in normalized
    )


def _looks_like_digest_summary_line(line: str) -> bool:
    normalized = line.strip()
    lowered = normalized.lower()
    return (
        lowered.startswith("your job alert for ")
        or DIGEST_MATCH_COUNT_RE.match(normalized) is not None
        or lowered == "results from the new ai-powered job search"
    )


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
