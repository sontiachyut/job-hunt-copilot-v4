from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .artifacts import ArtifactLinkage, register_artifact_record, write_yaml_contract
from .contracts import CONTRACT_VERSION
from .paths import ProjectPaths, workspace_slug
from .records import lifecycle_timestamps, new_canonical_id, now_utc_iso


LINKEDIN_SCRAPING_COMPONENT = "linkedin_scraping"

LEAD_STATUS_CAPTURED = "captured"
LEAD_STATUS_SPLIT_READY = "split_ready"
LEAD_STATUS_REVIEWED = "reviewed"
LEAD_STATUS_HANDED_OFF = "handed_off"
LEAD_SPLIT_REVIEW_NOT_STARTED = "not_started"
LEAD_SPLIT_REVIEW_CONFIDENT = "confident"
LEAD_SPLIT_REVIEW_NEEDS_REVIEW = "needs_review"
LEAD_SPLIT_REVIEW_AMBIGUOUS = "ambiguous"
LEAD_SHAPE_POSTING_ONLY = "posting_only"
LEAD_SHAPE_POSTING_PLUS_CONTACTS = "posting_plus_contacts"

JOB_POSTING_STATUS_SOURCED = "sourced"
CONTACT_STATUS_IDENTIFIED = "identified"
POSTING_CONTACT_STATUS_IDENTIFIED = "identified"
LEAD_CONTACT_ROLE_POSTER = "poster"

RECIPIENT_TYPE_HIRING_MANAGER = "hiring_manager"
RECIPIENT_TYPE_RECRUITER = "recruiter"
RECIPIENT_TYPE_ENGINEER = "engineer"
RECIPIENT_TYPE_ALUMNI = "alumni"
RECIPIENT_TYPE_FOUNDER = "founder"
RECIPIENT_TYPE_OTHER_INTERNAL = "other_internal"

MANIFEST_REASON_AMBIGUOUS_SPLIT_REVIEW = "ambiguous_split_review"
MANIFEST_REASON_MISSING_JD = "missing_jd"
MANIFEST_REASON_SPLIT_REVIEW_NOT_READY = "split_review_not_ready"
MANIFEST_REASON_POSTING_NOT_MATERIALIZED = "posting_not_materialized"

SOURCE_MODE_MANUAL_CAPTURE = "manual_capture"
SOURCE_MODE_MANUAL_PASTE = "manual_paste"

SOURCE_TYPE_MANUAL_CAPTURE_BUNDLE = "manual_capture_bundle"
SOURCE_TYPE_MANUAL_PASTE = "manual_paste"

SUBMISSION_PATH_IMMEDIATE_SELECTED_TEXT = "immediate_selected_text"
SUBMISSION_PATH_TRAY_REVIEW = "tray_review"
SUBMISSION_PATH_PASTE_INBOX = "paste_inbox"

LEAD_RAW_SOURCE_ARTIFACT_TYPE = "lead_raw_source"
LEAD_SPLIT_METADATA_ARTIFACT_TYPE = "lead_split_metadata"
LEAD_SPLIT_REVIEW_ARTIFACT_TYPE = "lead_split_review"
LEAD_MANIFEST_ARTIFACT_TYPE = "lead_manifest"
LEAD_SPLIT_METHOD_RULE_BASED_FIRST_PASS = "rule_based_first_pass"

TEXT_CAPTURE_MODES = frozenset({"selected_text", "full_page", "manual_paste"})
PAGE_TYPES = frozenset({"post", "job", "profile", "unknown"})

POST_MARKER_RE = re.compile(r"\b(?:#hiring|we(?:'|’)re hiring|we are hiring|hiring at)\b", re.IGNORECASE)
NETWORKING_HINT_RE = re.compile(r"\balumni\b", re.IGNORECASE)
JD_MARKER_RE = re.compile(
    r"^(?:about the job|about the role|job description|responsibilities|what you(?:'|’)ll do|"
    r"what we(?:'|’)re looking for|qualifications)\b",
    re.IGNORECASE,
)
PROFILE_MARKER_RE = re.compile(
    r"^(?:highlightshighlights|introduce myself|message|connect|follow|experience|activity|"
    r"see all details|about [a-z])",
    re.IGNORECASE,
)
POST_CHROME_REASONS = {
    "view job": "job_cta_chrome",
}
JD_CHROME_REASONS = {
    "view job": "job_cta_chrome",
}
PROFILE_CHROME_REASONS = {
    "highlightshighlights": "profile_chrome",
    "introduce myself": "profile_chrome",
    "message": "profile_chrome",
    "connect": "profile_chrome",
    "follow": "profile_chrome",
}


class LinkedInScrapingError(ValueError):
    """Raised when manual LinkedIn scraping input is invalid."""


@dataclass(frozen=True)
class LeadSummary:
    company_name: str
    role_title: str
    location: str | None = None
    work_mode: str | None = None
    compensation_summary: str | None = None
    poster_name: str | None = None
    poster_title: str | None = None

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "LeadSummary":
        company_name = _normalize_required_text(payload.get("company_name"), field_name="company_name")
        role_title = _normalize_required_text(payload.get("role_title"), field_name="role_title")
        return cls(
            company_name=company_name,
            role_title=role_title,
            location=_normalize_optional_text(payload.get("location")),
            work_mode=_normalize_optional_text(payload.get("work_mode")),
            compensation_summary=_normalize_optional_text(payload.get("compensation_summary")),
            poster_name=_normalize_optional_text(payload.get("poster_name")),
            poster_title=_normalize_optional_text(payload.get("poster_title")),
        )

    def as_dict(self) -> dict[str, str | None]:
        return {
            "company_name": self.company_name,
            "role_title": self.role_title,
            "location": self.location,
            "work_mode": self.work_mode,
            "compensation_summary": self.compensation_summary,
            "poster_name": self.poster_name,
            "poster_title": self.poster_title,
        }


@dataclass(frozen=True)
class CaptureItem:
    capture_order: int
    capture_mode: str
    page_type: str
    source_url: str | None = None
    page_title: str | None = None
    selected_text: str | None = None
    full_text: str | None = None
    captured_at: str | None = None

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, Any],
        *,
        default_capture_order: int,
    ) -> "CaptureItem":
        capture_mode = _normalize_required_text(payload.get("capture_mode"), field_name="capture_mode")
        if capture_mode not in TEXT_CAPTURE_MODES:
            raise LinkedInScrapingError(
                f"Unsupported capture_mode `{capture_mode}`. Expected one of: "
                + ", ".join(sorted(TEXT_CAPTURE_MODES))
            )

        page_type = _normalize_optional_text(payload.get("page_type")) or "unknown"
        if page_type not in PAGE_TYPES:
            raise LinkedInScrapingError(
                f"Unsupported page_type `{page_type}`. Expected one of: "
                + ", ".join(sorted(PAGE_TYPES))
            )

        selected_text = _normalize_optional_text(payload.get("selected_text"), preserve_whitespace=True)
        full_text = _normalize_optional_text(payload.get("full_text"), preserve_whitespace=True)
        if selected_text is None and full_text is None:
            raise LinkedInScrapingError(
                "Each capture item must include at least one of `selected_text` or `full_text`."
            )

        raw_capture_order = payload.get("capture_order", default_capture_order)
        try:
            capture_order = int(raw_capture_order)
        except (TypeError, ValueError) as exc:
            raise LinkedInScrapingError("capture_order must be an integer.") from exc

        return cls(
            capture_order=capture_order,
            capture_mode=capture_mode,
            page_type=page_type,
            source_url=_normalize_optional_text(payload.get("source_url")),
            page_title=_normalize_optional_text(payload.get("page_title")),
            selected_text=selected_text,
            full_text=full_text,
            captured_at=_normalize_optional_text(payload.get("captured_at")),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "capture_order": self.capture_order,
            "capture_mode": self.capture_mode,
            "page_type": self.page_type,
            "source_url": self.source_url,
            "page_title": self.page_title,
            "selected_text": self.selected_text,
            "full_text": self.full_text,
            "captured_at": self.captured_at,
        }


@dataclass(frozen=True)
class ManualCaptureSubmission:
    source_mode: str
    source_type: str
    submission_id: str
    source_reference: str
    summary: LeadSummary
    submission_path: str
    captures: tuple[CaptureItem, ...]
    accepted_at: str

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ManualCaptureSubmission":
        source_mode = _normalize_required_text(payload.get("source_mode"), field_name="source_mode")
        if source_mode not in {SOURCE_MODE_MANUAL_CAPTURE, SOURCE_MODE_MANUAL_PASTE}:
            raise LinkedInScrapingError(
                "source_mode must be `manual_capture` or `manual_paste`."
            )

        source_type = _normalize_required_text(payload.get("source_type"), field_name="source_type")
        if source_type not in {SOURCE_TYPE_MANUAL_CAPTURE_BUNDLE, SOURCE_TYPE_MANUAL_PASTE}:
            raise LinkedInScrapingError(
                "source_type must be `manual_capture_bundle` or `manual_paste`."
            )

        raw_captures = payload.get("captures")
        if not isinstance(raw_captures, Sequence) or isinstance(raw_captures, (str, bytes)):
            raise LinkedInScrapingError("captures must be a non-empty array.")
        captures = tuple(
            CaptureItem.from_mapping(item, default_capture_order=index + 1)
            for index, item in enumerate(raw_captures)
        )
        if not captures:
            raise LinkedInScrapingError("captures must contain at least one capture item.")

        submission_path = _normalize_optional_text(payload.get("submission_path"))
        if submission_path is None:
            submission_path = infer_submission_path(captures, source_mode=source_mode)

        return cls(
            source_mode=source_mode,
            source_type=source_type,
            submission_id=_normalize_required_text(payload.get("submission_id"), field_name="submission_id"),
            source_reference=_normalize_required_text(
                payload.get("source_reference"),
                field_name="source_reference",
            ),
            summary=LeadSummary.from_mapping(payload.get("summary") or {}),
            submission_path=submission_path,
            captures=tuple(sorted(captures, key=lambda item: item.capture_order)),
            accepted_at=_normalize_optional_text(payload.get("accepted_at")) or now_utc_iso(),
        )

    def lead_identity_key(self) -> str:
        return "|".join(
            [
                self.source_type,
                workspace_slug(self.summary.company_name),
                workspace_slug(self.summary.role_title),
                self.submission_id,
            ]
        )

    def primary_source_url(self) -> str | None:
        for capture in self.captures:
            if capture.source_url:
                return capture.source_url
        return None

    def last_scraped_at(self) -> str:
        capture_times = [capture.captured_at for capture in self.captures if capture.captured_at]
        return max(capture_times) if capture_times else self.accepted_at

    def capture_bundle_payload(self, *, lead_id: str, lead_identity_key: str) -> dict[str, Any]:
        return {
            "contract_version": CONTRACT_VERSION,
            "produced_at": self.accepted_at,
            "producer_component": LINKEDIN_SCRAPING_COMPONENT,
            "result": "success",
            "lead_id": lead_id,
            "lead_identity_key": lead_identity_key,
            "source_mode": self.source_mode,
            "source_type": self.source_type,
            "source_reference": self.source_reference,
            "submission_id": self.submission_id,
            "submission_path": self.submission_path,
            "accepted_at": self.accepted_at,
            "summary": self.summary.as_dict(),
            "captures": [capture.as_dict() for capture in self.captures],
        }


@dataclass(frozen=True)
class ManualLeadIngestionResult:
    lead_id: str
    lead_identity_key: str
    source_mode: str
    source_type: str
    workspace_dir: Path
    capture_bundle_path: Path
    raw_source_path: Path
    created: bool
    refreshed: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "lead_id": self.lead_id,
            "lead_identity_key": self.lead_identity_key,
            "source_mode": self.source_mode,
            "source_type": self.source_type,
            "created": self.created,
            "refreshed": self.refreshed,
            "workspace_path": str(self.workspace_dir),
            "capture_bundle_path": str(self.capture_bundle_path),
            "raw_source_path": str(self.raw_source_path),
        }


@dataclass(frozen=True)
class ManualLeadDerivationResult:
    lead_id: str
    lead_status: str
    split_review_status: str
    selected_method: str
    workspace_dir: Path
    split_metadata_path: Path
    split_review_path: Path
    lead_manifest_path: Path
    post_path: Path | None
    jd_path: Path | None
    poster_profile_path: Path | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "lead_id": self.lead_id,
            "lead_status": self.lead_status,
            "split_review_status": self.split_review_status,
            "selected_method": self.selected_method,
            "workspace_path": str(self.workspace_dir),
            "split_metadata_path": str(self.split_metadata_path),
            "split_review_path": str(self.split_review_path),
            "lead_manifest_path": str(self.lead_manifest_path),
            "post_path": str(self.post_path) if self.post_path else None,
            "jd_path": str(self.jd_path) if self.jd_path else None,
            "poster_profile_path": str(self.poster_profile_path) if self.poster_profile_path else None,
        }


@dataclass(frozen=True)
class ManualLeadMaterializationResult:
    lead_id: str
    lead_status: str
    lead_shape: str
    split_review_status: str
    materialized: bool
    reason_code: str | None
    job_posting_id: str | None
    job_posting_created: bool
    contact_id: str | None
    contact_created: bool
    linkedin_lead_contact_id: str | None
    job_posting_contact_id: str | None
    lead_manifest_path: Path

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "lead_id": self.lead_id,
            "lead_status": self.lead_status,
            "lead_shape": self.lead_shape,
            "split_review_status": self.split_review_status,
            "materialized": self.materialized,
            "reason_code": self.reason_code,
            "job_posting_id": self.job_posting_id,
            "job_posting_created": self.job_posting_created,
            "contact_id": self.contact_id,
            "contact_created": self.contact_created,
            "linkedin_lead_contact_id": self.linkedin_lead_contact_id,
            "job_posting_contact_id": self.job_posting_contact_id,
            "lead_manifest_path": str(self.lead_manifest_path),
        }


def infer_submission_path(
    captures: Sequence[CaptureItem],
    *,
    source_mode: str,
) -> str:
    if source_mode == SOURCE_MODE_MANUAL_PASTE:
        return SUBMISSION_PATH_PASTE_INBOX
    has_selected_text = any(capture.selected_text for capture in captures)
    if has_selected_text:
        return SUBMISSION_PATH_IMMEDIATE_SELECTED_TEXT
    return SUBMISSION_PATH_TRAY_REVIEW


def build_manual_paste_submission(
    paths: ProjectPaths,
    *,
    company_name: str,
    role_title: str,
    location: str | None = None,
    work_mode: str | None = None,
    compensation_summary: str | None = None,
    poster_name: str | None = None,
    poster_title: str | None = None,
) -> ManualCaptureSubmission:
    if not paths.paste_inbox_path.exists():
        raise FileNotFoundError(f"Paste inbox not found: {paths.paste_inbox_path}")

    raw_bytes = paths.paste_inbox_path.read_bytes()
    try:
        raw_text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LinkedInScrapingError("paste/paste.txt must be valid UTF-8 text.") from exc

    submission_id = "paste-" + hashlib.sha256(
        b"|".join(
            [
                workspace_slug(company_name).encode("utf-8"),
                workspace_slug(role_title).encode("utf-8"),
                raw_bytes,
            ]
        )
    ).hexdigest()[:16]
    return ManualCaptureSubmission.from_mapping(
        {
            "source_mode": SOURCE_MODE_MANUAL_PASTE,
            "source_type": SOURCE_TYPE_MANUAL_PASTE,
            "submission_id": submission_id,
            "source_reference": paths.relative_to_root(paths.paste_inbox_path).as_posix(),
            "submission_path": SUBMISSION_PATH_PASTE_INBOX,
            "summary": {
                "company_name": company_name,
                "role_title": role_title,
                "location": location,
                "work_mode": work_mode,
                "compensation_summary": compensation_summary,
                "poster_name": poster_name,
                "poster_title": poster_title,
            },
            "captures": [
                {
                    "capture_order": 1,
                    "capture_mode": SOURCE_TYPE_MANUAL_PASTE,
                    "page_type": "unknown",
                    "full_text": raw_text,
                    "captured_at": now_utc_iso(),
                }
            ],
        }
    )


def load_manual_capture_submission(bundle_path: Path | str) -> ManualCaptureSubmission:
    bundle = json.loads(Path(bundle_path).read_text(encoding="utf-8"))
    if not isinstance(bundle, Mapping):
        raise LinkedInScrapingError("Manual capture bundle JSON must be an object.")
    return ManualCaptureSubmission.from_mapping(bundle)


def ingest_manual_capture_submission(
    project_root: Path | str | None = None,
    *,
    submission: ManualCaptureSubmission | Mapping[str, Any],
    existing_lead_id: str | None = None,
) -> ManualLeadIngestionResult:
    paths = ProjectPaths.from_root(project_root)
    normalized_submission = (
        submission
        if isinstance(submission, ManualCaptureSubmission)
        else ManualCaptureSubmission.from_mapping(submission)
    )
    lead_identity_key = normalized_submission.lead_identity_key()

    connection = sqlite3.connect(paths.db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")

    try:
        existing_lead = None
        if existing_lead_id is not None:
            existing_lead = _load_manual_lead_row(connection, lead_id=existing_lead_id)
            _validate_refresh_workspace_identity(existing_lead, submission=normalized_submission)
            existing_identity_match = _find_existing_lead(connection, lead_identity_key)
            if existing_identity_match is not None and existing_identity_match["lead_id"] != existing_lead["lead_id"]:
                raise LinkedInScrapingError(
                    "Cannot refresh into a lead whose refreshed identity already belongs to a different lead."
                )
        else:
            existing_lead = _find_existing_lead(connection, lead_identity_key)
        if existing_lead is not None:
            return _refresh_manual_lead_workspace(
                connection,
                paths,
                existing_lead=existing_lead,
                submission=normalized_submission,
                lead_identity_key=lead_identity_key,
            )

        lead_id = new_canonical_id("linkedin_leads")
        workspace_dir = paths.lead_workspace_dir(
            normalized_submission.summary.company_name,
            normalized_submission.summary.role_title,
            lead_id,
        )
        capture_bundle_path = paths.lead_capture_bundle_path(
            normalized_submission.summary.company_name,
            normalized_submission.summary.role_title,
            lead_id,
        )
        raw_source_path = paths.lead_raw_source_path(
            normalized_submission.summary.company_name,
            normalized_submission.summary.role_title,
            lead_id,
        )

        capture_bundle = normalized_submission.capture_bundle_payload(
            lead_id=lead_id,
            lead_identity_key=lead_identity_key,
        )
        raw_source_bytes = _render_raw_source_bytes(normalized_submission)
        capture_bundle_path.parent.mkdir(parents=True, exist_ok=True)
        capture_bundle_path.write_text(json.dumps(capture_bundle, indent=2) + "\n", encoding="utf-8")
        raw_source_path.parent.mkdir(parents=True, exist_ok=True)
        raw_source_path.write_bytes(raw_source_bytes)

        timestamps = lifecycle_timestamps(normalized_submission.accepted_at)
        with connection:
            connection.execute(
                """
                INSERT INTO linkedin_leads (
                  lead_id, lead_identity_key, lead_status, lead_shape, split_review_status,
                  source_type, source_reference, source_mode, source_url, company_name, role_title,
                  location, work_mode, compensation_summary, poster_name, poster_title,
                  last_scraped_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    lead_id,
                    lead_identity_key,
                    LEAD_STATUS_CAPTURED,
                    LEAD_SHAPE_POSTING_ONLY,
                    LEAD_SPLIT_REVIEW_NOT_STARTED,
                    normalized_submission.source_type,
                    normalized_submission.source_reference,
                    normalized_submission.source_mode,
                    normalized_submission.primary_source_url(),
                    normalized_submission.summary.company_name,
                    normalized_submission.summary.role_title,
                    normalized_submission.summary.location,
                    normalized_submission.summary.work_mode,
                    normalized_submission.summary.compensation_summary,
                    normalized_submission.summary.poster_name,
                    normalized_submission.summary.poster_title,
                    normalized_submission.last_scraped_at(),
                    timestamps["created_at"],
                    timestamps["updated_at"],
                ),
            )
            register_artifact_record(
                connection,
                paths,
                artifact_type=LEAD_RAW_SOURCE_ARTIFACT_TYPE,
                artifact_path=raw_source_path,
                producer_component=LINKEDIN_SCRAPING_COMPONENT,
                linkage=ArtifactLinkage(lead_id=lead_id),
                created_at=normalized_submission.accepted_at,
            )
    finally:
        connection.close()

    return ManualLeadIngestionResult(
        lead_id=lead_id,
        lead_identity_key=lead_identity_key,
        source_mode=normalized_submission.source_mode,
        source_type=normalized_submission.source_type,
        workspace_dir=workspace_dir,
        capture_bundle_path=capture_bundle_path,
        raw_source_path=raw_source_path,
        created=True,
        refreshed=False,
    )


def _refresh_manual_lead_workspace(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    existing_lead: Mapping[str, Any],
    submission: ManualCaptureSubmission,
    lead_identity_key: str,
) -> ManualLeadIngestionResult:
    lead_id = existing_lead["lead_id"]
    artifact_paths = _manual_lead_artifact_paths(
        paths,
        company_name=existing_lead["company_name"],
        role_title=existing_lead["role_title"],
        lead_id=lead_id,
    )
    current_bundle = _load_capture_bundle(artifact_paths["capture_bundle_path"])
    if not _manual_lead_refresh_needed(
        submission=submission,
        current_bundle=current_bundle,
        raw_source_path=artifact_paths["raw_source_path"],
    ):
        return ManualLeadIngestionResult(
            lead_id=lead_id,
            lead_identity_key=lead_identity_key,
            source_mode=existing_lead["source_mode"],
            source_type=existing_lead["source_type"],
            workspace_dir=artifact_paths["workspace_dir"],
            capture_bundle_path=artifact_paths["capture_bundle_path"],
            raw_source_path=artifact_paths["raw_source_path"],
            created=False,
            refreshed=False,
        )

    snapshot_timestamp = now_utc_iso()
    history_snapshot_dir = _snapshot_manual_lead_workspace(
        artifact_paths=artifact_paths,
        lead_id=lead_id,
        snapshot_reason="source_refresh",
        snapshot_timestamp=snapshot_timestamp,
    )
    existing_posting = _find_existing_posting_for_lead(connection, lead_id=lead_id)
    existing_job_posting_id = existing_posting["job_posting_id"] if existing_posting is not None else None
    _preserve_existing_posting_history(
        connection,
        paths,
        job_posting_id=existing_job_posting_id,
        live_jd_path=artifact_paths["jd_path"],
        history_snapshot_dir=history_snapshot_dir,
    )
    _clear_live_review_artifacts(artifact_paths)

    refreshed_lead_row = dict(existing_lead)
    refreshed_lead_row.update(
        {
            "lead_id": lead_id,
            "lead_identity_key": lead_identity_key,
            "source_type": submission.source_type,
            "source_reference": submission.source_reference,
            "source_mode": submission.source_mode,
            "source_url": submission.primary_source_url(),
            "company_name": submission.summary.company_name,
            "role_title": submission.summary.role_title,
            "location": submission.summary.location,
            "work_mode": submission.summary.work_mode,
            "compensation_summary": submission.summary.compensation_summary,
            "poster_name": submission.summary.poster_name,
            "poster_title": submission.summary.poster_title,
        }
    )

    artifact_paths["capture_bundle_path"].parent.mkdir(parents=True, exist_ok=True)
    artifact_paths["capture_bundle_path"].write_text(
        json.dumps(
            submission.capture_bundle_payload(
                lead_id=lead_id,
                lead_identity_key=lead_identity_key,
            ),
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    artifact_paths["raw_source_path"].parent.mkdir(parents=True, exist_ok=True)
    artifact_paths["raw_source_path"].write_bytes(_render_raw_source_bytes(submission))

    created_entities = _collect_created_entities(
        connection,
        lead_id=lead_id,
        job_posting_id=existing_job_posting_id,
    )
    lead_shape = (
        LEAD_SHAPE_POSTING_PLUS_CONTACTS
        if created_entities["contact_ids"]
        else refreshed_lead_row["lead_shape"]
    )
    updated_at = now_utc_iso()

    with connection:
        connection.execute(
            """
            UPDATE linkedin_leads
            SET lead_identity_key = ?, lead_status = ?, lead_shape = ?, split_review_status = ?,
                source_type = ?, source_reference = ?, source_mode = ?, source_url = ?,
                company_name = ?, role_title = ?, location = ?, work_mode = ?,
                compensation_summary = ?, poster_name = ?, poster_title = ?,
                last_scraped_at = ?, updated_at = ?
            WHERE lead_id = ?
            """,
            (
                lead_identity_key,
                LEAD_STATUS_CAPTURED,
                lead_shape,
                LEAD_SPLIT_REVIEW_NOT_STARTED,
                submission.source_type,
                submission.source_reference,
                submission.source_mode,
                submission.primary_source_url(),
                submission.summary.company_name,
                submission.summary.role_title,
                submission.summary.location,
                submission.summary.work_mode,
                submission.summary.compensation_summary,
                submission.summary.poster_name,
                submission.summary.poster_title,
                submission.last_scraped_at(),
                updated_at,
                lead_id,
            ),
        )
        _replace_lead_artifact_record(
            connection,
            paths,
            artifact_type=LEAD_RAW_SOURCE_ARTIFACT_TYPE,
            artifact_path=artifact_paths["raw_source_path"],
            lead_id=lead_id,
            created_at=submission.accepted_at,
        )
        _delete_lead_artifact_record(
            connection,
            artifact_type=LEAD_SPLIT_METADATA_ARTIFACT_TYPE,
            lead_id=lead_id,
        )
        _delete_lead_artifact_record(
            connection,
            artifact_type=LEAD_SPLIT_REVIEW_ARTIFACT_TYPE,
            lead_id=lead_id,
        )
        _write_manual_lead_manifest(
            connection,
            paths,
            lead_row=refreshed_lead_row,
            lead_status=LEAD_STATUS_CAPTURED,
            lead_shape=lead_shape,
            split_review_status=LEAD_SPLIT_REVIEW_NOT_STARTED,
            artifact_paths=artifact_paths,
            created_entities=created_entities,
            handoff_targets={
                "posting_materialization": _build_posting_materialization_target(
                    split_review_status=LEAD_SPLIT_REVIEW_NOT_STARTED,
                    jd_path=artifact_paths["jd_path"],
                    job_posting_id=created_entities["job_posting_id"],
                    allow_existing_posting_to_satisfy_target=False,
                ),
                "resume_tailoring": _build_resume_tailoring_target(
                    job_posting_id=created_entities["job_posting_id"],
                    jd_path=artifact_paths["jd_path"],
                ),
            },
        )

    return ManualLeadIngestionResult(
        lead_id=lead_id,
        lead_identity_key=lead_identity_key,
        source_mode=submission.source_mode,
        source_type=submission.source_type,
        workspace_dir=artifact_paths["workspace_dir"],
        capture_bundle_path=artifact_paths["capture_bundle_path"],
        raw_source_path=artifact_paths["raw_source_path"],
        created=False,
        refreshed=True,
    )


def _render_raw_source_bytes(submission: ManualCaptureSubmission) -> bytes:
    if submission.source_type == SOURCE_TYPE_MANUAL_PASTE:
        raw_capture = submission.captures[0]
        if raw_capture.full_text is None:
            raise LinkedInScrapingError("manual_paste capture must include full_text.")
        return raw_capture.full_text.encode("utf-8")
    return render_manual_capture_source(submission).encode("utf-8")


def _manual_lead_refresh_needed(
    *,
    submission: ManualCaptureSubmission,
    current_bundle: Mapping[str, Any] | None,
    raw_source_path: Path,
) -> bool:
    if current_bundle is None or not raw_source_path.exists():
        return True
    return _manual_submission_refresh_signature(submission) != _capture_bundle_refresh_signature(current_bundle)


def _manual_submission_refresh_signature(submission: ManualCaptureSubmission) -> dict[str, Any]:
    return {
        "source_mode": submission.source_mode,
        "source_type": submission.source_type,
        "submission_id": submission.submission_id,
        "source_reference": submission.source_reference,
        "submission_path": submission.submission_path,
        "summary": submission.summary.as_dict(),
        "captures": [
            {
                "capture_order": capture.capture_order,
                "capture_mode": capture.capture_mode,
                "page_type": capture.page_type,
                "source_url": capture.source_url,
                "page_title": capture.page_title,
                "selected_text": capture.selected_text,
                "full_text": capture.full_text,
            }
            for capture in submission.captures
        ],
    }


def _capture_bundle_refresh_signature(capture_bundle: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "source_mode": capture_bundle.get("source_mode"),
        "source_type": capture_bundle.get("source_type"),
        "submission_id": capture_bundle.get("submission_id"),
        "source_reference": capture_bundle.get("source_reference"),
        "submission_path": capture_bundle.get("submission_path"),
        "summary": dict(capture_bundle.get("summary") or {}),
        "captures": [
            {
                "capture_order": capture.get("capture_order"),
                "capture_mode": capture.get("capture_mode"),
                "page_type": capture.get("page_type"),
                "source_url": capture.get("source_url"),
                "page_title": capture.get("page_title"),
                "selected_text": capture.get("selected_text"),
                "full_text": capture.get("full_text"),
            }
            for capture in (capture_bundle.get("captures") or [])
            if isinstance(capture, Mapping)
        ],
    }


def _validate_refresh_workspace_identity(
    existing_lead: Mapping[str, Any],
    *,
    submission: ManualCaptureSubmission,
) -> None:
    if workspace_slug(existing_lead["company_name"] or "") != workspace_slug(submission.summary.company_name):
        raise LinkedInScrapingError(
            "Cannot refresh a lead into a different company workspace slug; create a new lead instead."
        )
    if workspace_slug(existing_lead["role_title"] or "") != workspace_slug(submission.summary.role_title):
        raise LinkedInScrapingError(
            "Cannot refresh a lead into a different role workspace slug; create a new lead instead."
        )


def _snapshot_manual_lead_workspace(
    *,
    artifact_paths: Mapping[str, Path],
    lead_id: str,
    snapshot_reason: str,
    snapshot_timestamp: str,
) -> Path | None:
    snapshot_sources = [
        artifact_paths["capture_bundle_path"],
        artifact_paths["raw_source_path"],
        artifact_paths["post_path"],
        artifact_paths["jd_path"],
        artifact_paths["poster_profile_path"],
        artifact_paths["split_metadata_path"],
        artifact_paths["split_review_path"],
        artifact_paths["lead_manifest_path"],
    ]
    existing_sources = [path for path in snapshot_sources if path.exists()]
    if not existing_sources:
        return None

    workspace_dir = artifact_paths["workspace_dir"]
    history_dir = workspace_dir / "history"
    snapshot_dir = _allocate_history_snapshot_dir(
        history_dir=history_dir,
        snapshot_timestamp=snapshot_timestamp,
        snapshot_reason=snapshot_reason,
    )
    copied_files: list[str] = []
    for source_path in existing_sources:
        relative_path = source_path.relative_to(workspace_dir)
        target_path = snapshot_dir / relative_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(source_path.read_bytes())
        copied_files.append(relative_path.as_posix())

    (snapshot_dir / "snapshot.json").write_text(
        json.dumps(
            {
                "lead_id": lead_id,
                "snapshot_reason": snapshot_reason,
                "snapshotted_at": snapshot_timestamp,
                "copied_files": copied_files,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return snapshot_dir


def _allocate_history_snapshot_dir(
    *,
    history_dir: Path,
    snapshot_timestamp: str,
    snapshot_reason: str,
) -> Path:
    slug = snapshot_timestamp.replace("-", "").replace(":", "").replace(".", "").replace("+00:00", "Z")
    base_dir = history_dir / f"{slug}-{workspace_slug(snapshot_reason)}"
    candidate = base_dir
    suffix = 1
    while candidate.exists():
        suffix += 1
        candidate = history_dir / f"{base_dir.name}-{suffix}"
    candidate.mkdir(parents=True, exist_ok=False)
    return candidate


def _preserve_existing_posting_history(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    job_posting_id: str | None,
    live_jd_path: Path,
    history_snapshot_dir: Path | None,
) -> None:
    if job_posting_id is None or history_snapshot_dir is None or not live_jd_path.exists():
        return
    snapshot_jd_path = history_snapshot_dir / live_jd_path.name
    if not snapshot_jd_path.exists():
        return
    connection.execute(
        """
        UPDATE job_postings
        SET jd_artifact_path = ?, updated_at = ?
        WHERE job_posting_id = ?
        """,
        (
            paths.relative_to_root(snapshot_jd_path).as_posix(),
            now_utc_iso(),
            job_posting_id,
        ),
    )


def _clear_live_review_artifacts(artifact_paths: Mapping[str, Path]) -> None:
    for key in (
        "post_path",
        "jd_path",
        "poster_profile_path",
        "split_metadata_path",
        "split_review_path",
    ):
        path = artifact_paths[key]
        if path.exists():
            path.unlink()


def _delete_lead_artifact_record(
    connection: sqlite3.Connection,
    *,
    artifact_type: str,
    lead_id: str,
) -> None:
    connection.execute(
        "DELETE FROM artifact_records WHERE artifact_type = ? AND lead_id = ?",
        (artifact_type, lead_id),
    )


def ingest_paste_inbox(
    project_root: Path | str | None = None,
    *,
    company_name: str,
    role_title: str,
    location: str | None = None,
    work_mode: str | None = None,
    compensation_summary: str | None = None,
    poster_name: str | None = None,
    poster_title: str | None = None,
    existing_lead_id: str | None = None,
) -> ManualLeadIngestionResult:
    paths = ProjectPaths.from_root(project_root)
    submission = build_manual_paste_submission(
        paths,
        company_name=company_name,
        role_title=role_title,
        location=location,
        work_mode=work_mode,
        compensation_summary=compensation_summary,
        poster_name=poster_name,
        poster_title=poster_title,
    )
    return ingest_manual_capture_submission(
        paths.project_root,
        submission=submission,
        existing_lead_id=existing_lead_id,
    )


def materialize_manual_lead_entities(
    project_root: Path | str | None = None,
    *,
    lead_id: str,
) -> ManualLeadMaterializationResult:
    paths = ProjectPaths.from_root(project_root)
    connection = sqlite3.connect(paths.db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")

    try:
        lead_row = _load_manual_lead_row(connection, lead_id=lead_id)
        artifact_paths = _manual_lead_artifact_paths(
            paths,
            company_name=lead_row["company_name"],
            role_title=lead_row["role_title"],
            lead_id=lead_id,
        )
        if not artifact_paths["lead_manifest_path"].exists():
            raise LinkedInScrapingError(
                f"Lead `{lead_id}` has not completed derivation yet; `{artifact_paths['lead_manifest_path']}` is missing."
            )

        capture_bundle = _load_capture_bundle(artifact_paths["capture_bundle_path"])
        lead_state = dict(lead_row)
        existing_posting = _find_existing_posting_for_lead(connection, lead_id=lead_id)

        materialization_ready, reason_code = _posting_materialization_status(
            split_review_status=lead_state["split_review_status"],
            jd_path=artifact_paths["jd_path"],
        )

        job_posting_created = False
        contact_created = False
        materialized_contact: dict[str, Any] | None = None
        job_posting_id = existing_posting["job_posting_id"] if existing_posting is not None else None

        if materialization_ready:
            job_posting_id, job_posting_created = _upsert_job_posting(
                connection,
                paths,
                lead_row=lead_state,
                jd_path=artifact_paths["jd_path"],
            )
            materialized_contact = _materialize_manual_poster_contact(
                connection,
                lead_row=lead_state,
                capture_bundle=capture_bundle,
                poster_profile_path=artifact_paths["poster_profile_path"],
                job_posting_id=job_posting_id,
            )
            if materialized_contact is not None:
                contact_created = materialized_contact["contact_created"]
                lead_state["poster_name"] = materialized_contact["display_name"]
                lead_state["poster_title"] = materialized_contact["position_title"]
            reason_code = None
        elif job_posting_id is None:
            reason_code = reason_code or MANIFEST_REASON_POSTING_NOT_MATERIALIZED

        created_entities = _collect_created_entities(
            connection,
            lead_id=lead_id,
            job_posting_id=job_posting_id,
        )
        if created_entities["job_posting_id"] is not None:
            job_posting_id = created_entities["job_posting_id"]
            lead_status = LEAD_STATUS_HANDED_OFF
            reason_code = None
        else:
            lead_status = lead_state["lead_status"]

        lead_shape = (
            LEAD_SHAPE_POSTING_PLUS_CONTACTS
            if created_entities["contact_ids"]
            else LEAD_SHAPE_POSTING_ONLY
        )
        handoff_targets = {
            "posting_materialization": _build_posting_materialization_target(
                split_review_status=lead_state["split_review_status"],
                jd_path=artifact_paths["jd_path"],
                job_posting_id=job_posting_id,
            ),
            "resume_tailoring": _build_resume_tailoring_target(
                job_posting_id=job_posting_id,
                jd_path=artifact_paths["jd_path"],
            ),
        }

        updated_at = now_utc_iso()
        with connection:
            connection.execute(
                """
                UPDATE linkedin_leads
                SET lead_status = ?, lead_shape = ?, poster_name = ?, poster_title = ?, updated_at = ?
                WHERE lead_id = ?
                """,
                (
                    lead_status,
                    lead_shape,
                    lead_state["poster_name"],
                    lead_state["poster_title"],
                    updated_at,
                    lead_id,
                ),
            )
            _write_manual_lead_manifest(
                connection,
                paths,
                lead_row=lead_state,
                lead_status=lead_status,
                lead_shape=lead_shape,
                split_review_status=lead_state["split_review_status"],
                artifact_paths=artifact_paths,
                created_entities=created_entities,
                handoff_targets=handoff_targets,
            )
    finally:
        connection.close()

    return ManualLeadMaterializationResult(
        lead_id=lead_id,
        lead_status=lead_status,
        lead_shape=lead_shape,
        split_review_status=lead_state["split_review_status"],
        materialized=job_posting_id is not None,
        reason_code=reason_code,
        job_posting_id=job_posting_id,
        job_posting_created=job_posting_created,
        contact_id=(materialized_contact or {}).get("contact_id"),
        contact_created=contact_created,
        linkedin_lead_contact_id=(materialized_contact or {}).get("linkedin_lead_contact_id"),
        job_posting_contact_id=(materialized_contact or {}).get("job_posting_contact_id"),
        lead_manifest_path=artifact_paths["lead_manifest_path"],
    )


def derive_manual_lead_context(
    project_root: Path | str | None = None,
    *,
    lead_id: str,
) -> ManualLeadDerivationResult:
    paths = ProjectPaths.from_root(project_root)
    connection = sqlite3.connect(paths.db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")

    try:
        lead_row = connection.execute(
            """
            SELECT lead_id, lead_status, lead_shape, split_review_status, source_type, source_reference,
                   source_mode, source_url, company_name, role_title, location, work_mode,
                   compensation_summary, poster_name, poster_title
            FROM linkedin_leads
            WHERE lead_id = ?
            """,
            (lead_id,),
        ).fetchone()
        if lead_row is None:
            raise LinkedInScrapingError(f"Lead `{lead_id}` was not found.")
        if lead_row["source_mode"] not in {SOURCE_MODE_MANUAL_CAPTURE, SOURCE_MODE_MANUAL_PASTE}:
            raise LinkedInScrapingError(
                f"Lead `{lead_id}` is not a manual lead and cannot use the manual split pipeline."
            )

        artifact_paths = _manual_lead_artifact_paths(
            paths,
            company_name=lead_row["company_name"],
            role_title=lead_row["role_title"],
            lead_id=lead_id,
        )
        workspace_dir = artifact_paths["workspace_dir"]
        raw_source_path = artifact_paths["raw_source_path"]
        capture_bundle_path = artifact_paths["capture_bundle_path"]
        post_path = artifact_paths["post_path"]
        jd_path = artifact_paths["jd_path"]
        poster_profile_path = artifact_paths["poster_profile_path"]
        split_metadata_path = artifact_paths["split_metadata_path"]
        split_review_path = artifact_paths["split_review_path"]
        lead_manifest_path = artifact_paths["lead_manifest_path"]

        if not raw_source_path.exists():
            raise LinkedInScrapingError(
                f"Lead `{lead_id}` does not have a canonical raw source artifact at {raw_source_path}."
            )

        raw_source_text = raw_source_path.read_text(encoding="utf-8")
        capture_bundle = _load_capture_bundle(capture_bundle_path)
        sections = _derive_sections(
            raw_source_text=raw_source_text,
            capture_bundle=capture_bundle,
            post_path=post_path,
            jd_path=jd_path,
            poster_profile_path=poster_profile_path,
        )
        review_status, lead_status, confidence, findings, validation_checks, recommended_action = _review_sections(
            sections=sections,
        )

        _write_optional_markdown(post_path, sections["post"]["derived_text"])
        _write_optional_markdown(jd_path, sections["jd"]["derived_text"])
        _write_optional_markdown(poster_profile_path, sections["poster_profile"]["derived_text"])

        linkage = ArtifactLinkage(lead_id=lead_id)
        split_metadata_contract = write_yaml_contract(
            split_metadata_path,
            producer_component=LINKEDIN_SCRAPING_COMPONENT,
            result="success",
            linkage=linkage,
            payload={
                "selected_method": LEAD_SPLIT_METHOD_RULE_BASED_FIRST_PASS,
                "acquisition_mode": lead_row["source_mode"],
                "source_artifact_path": str(raw_source_path.resolve()),
                "capture_bundle_path": str(capture_bundle_path.resolve()) if capture_bundle_path.exists() else None,
                "sections": {
                    name: _section_metadata_payload(section)
                    for name, section in sections.items()
                },
                "ai_second_pass": {
                    "configured": False,
                    "attempted": False,
                    "accepted": False,
                },
            },
        )
        split_review_contract = write_yaml_contract(
            split_review_path,
            producer_component=LINKEDIN_SCRAPING_COMPONENT,
            result="success",
            linkage=linkage,
            payload={
                "selected_method": LEAD_SPLIT_METHOD_RULE_BASED_FIRST_PASS,
                "split_status": review_status,
                "confidence": confidence,
                "coverage": {
                    "available_sections": [
                        name for name, section in sections.items() if section["available"]
                    ],
                    "unavailable_sections": [
                        {
                            "section": name,
                            "reason_code": section["unavailable_reason"],
                        }
                        for name, section in sections.items()
                        if not section["available"]
                    ],
                },
                "validation_checks": validation_checks,
                "findings": findings,
                "recommended_action": recommended_action,
                "acquisition_mode": lead_row["source_mode"],
                "derived_artifact_availability": {
                    name: _section_availability_payload(section)
                    for name, section in sections.items()
                },
                "ai_second_pass": {
                    "configured": False,
                    "attempted": False,
                    "accepted": False,
                },
            },
        )

        lead_manifest_contract = _write_manual_lead_manifest(
            connection,
            paths,
            lead_row=lead_row,
            lead_status=lead_status,
            lead_shape=lead_row["lead_shape"],
            split_review_status=review_status,
            artifact_paths=artifact_paths,
            created_entities={
                "job_posting_id": None,
                "contact_ids": [],
                "job_posting_contact_ids": [],
                "linkedin_lead_contact_ids": [],
            },
            handoff_targets={
                "posting_materialization": _build_posting_materialization_target(
                    split_review_status=review_status,
                    jd_path=jd_path,
                    job_posting_id=None,
                )
            },
        )

        updated_at = now_utc_iso()
        with connection:
            connection.execute(
                """
                UPDATE linkedin_leads
                SET lead_status = ?, split_review_status = ?, updated_at = ?
                WHERE lead_id = ?
                """,
                (
                    lead_status,
                    review_status,
                    updated_at,
                    lead_id,
                ),
            )
            _replace_lead_artifact_record(
                connection,
                paths,
                artifact_type=LEAD_SPLIT_METADATA_ARTIFACT_TYPE,
                artifact_path=split_metadata_path,
                lead_id=lead_id,
                created_at=split_metadata_contract["produced_at"],
            )
            _replace_lead_artifact_record(
                connection,
                paths,
                artifact_type=LEAD_SPLIT_REVIEW_ARTIFACT_TYPE,
                artifact_path=split_review_path,
                lead_id=lead_id,
                created_at=split_review_contract["produced_at"],
            )
    finally:
        connection.close()

    return ManualLeadDerivationResult(
        lead_id=lead_id,
        lead_status=lead_status,
        split_review_status=review_status,
        selected_method=LEAD_SPLIT_METHOD_RULE_BASED_FIRST_PASS,
        workspace_dir=workspace_dir,
        split_metadata_path=split_metadata_path,
        split_review_path=split_review_path,
        lead_manifest_path=lead_manifest_path,
        post_path=post_path if sections["post"]["available"] else None,
        jd_path=jd_path if sections["jd"]["available"] else None,
        poster_profile_path=poster_profile_path if sections["poster_profile"]["available"] else None,
    )


def render_manual_capture_source(submission: ManualCaptureSubmission) -> str:
    sections = [
        "# Manual Capture Source",
        "",
        f"- source_mode: {submission.source_mode}",
        f"- source_type: {submission.source_type}",
        f"- submission_id: {submission.submission_id}",
        f"- submission_path: {submission.submission_path}",
        f"- accepted_at: {submission.accepted_at}",
        f"- company_name: {submission.summary.company_name}",
        f"- role_title: {submission.summary.role_title}",
    ]
    if submission.summary.location:
        sections.append(f"- location: {submission.summary.location}")
    if submission.summary.work_mode:
        sections.append(f"- work_mode: {submission.summary.work_mode}")
    if submission.summary.compensation_summary:
        sections.append(f"- compensation_summary: {submission.summary.compensation_summary}")
    if submission.summary.poster_name:
        sections.append(f"- poster_name: {submission.summary.poster_name}")
    if submission.summary.poster_title:
        sections.append(f"- poster_title: {submission.summary.poster_title}")

    rendered = "\n".join(sections).rstrip() + "\n"
    for capture in submission.captures:
        capture_lines = [
            "",
            f"## Capture {capture.capture_order}",
            f"- capture_mode: {capture.capture_mode}",
            f"- page_type: {capture.page_type}",
        ]
        if capture.source_url:
            capture_lines.append(f"- source_url: {capture.source_url}")
        if capture.page_title:
            capture_lines.append(f"- page_title: {capture.page_title}")
        if capture.captured_at:
            capture_lines.append(f"- captured_at: {capture.captured_at}")
        rendered += "\n".join(capture_lines).rstrip() + "\n"
        if capture.selected_text is not None:
            rendered += "\n### Selected Text\n"
            rendered += capture.selected_text
            if not capture.selected_text.endswith("\n"):
                rendered += "\n"
        if capture.full_text is not None:
            rendered += "\n### Full Text\n"
            rendered += capture.full_text
            if not capture.full_text.endswith("\n"):
                rendered += "\n"
    return rendered


def _load_capture_bundle(capture_bundle_path: Path) -> Mapping[str, Any] | None:
    if not capture_bundle_path.exists():
        return None
    payload = json.loads(capture_bundle_path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, Mapping) else None


def _manual_lead_artifact_paths(
    paths: ProjectPaths,
    *,
    company_name: str,
    role_title: str,
    lead_id: str,
) -> dict[str, Path]:
    return {
        "workspace_dir": paths.lead_workspace_dir(company_name, role_title, lead_id),
        "raw_source_path": paths.lead_raw_source_path(company_name, role_title, lead_id),
        "capture_bundle_path": paths.lead_capture_bundle_path(company_name, role_title, lead_id),
        "post_path": paths.lead_post_path(company_name, role_title, lead_id),
        "jd_path": paths.lead_jd_path(company_name, role_title, lead_id),
        "poster_profile_path": paths.lead_poster_profile_path(company_name, role_title, lead_id),
        "split_metadata_path": paths.lead_split_metadata_path(company_name, role_title, lead_id),
        "split_review_path": paths.lead_split_review_path(company_name, role_title, lead_id),
        "lead_manifest_path": paths.lead_manifest_path(company_name, role_title, lead_id),
    }


def _derive_sections(
    *,
    raw_source_text: str,
    capture_bundle: Mapping[str, Any] | None,
    post_path: Path,
    jd_path: Path,
    poster_profile_path: Path,
) -> dict[str, dict[str, Any]]:
    fragments_by_section = {
        "post": [],
        "jd": [],
        "poster_profile": [],
    }
    if capture_bundle is not None:
        _add_capture_bundle_fragments(
            fragments_by_section=fragments_by_section,
            raw_source_text=raw_source_text,
            capture_bundle=capture_bundle,
        )

    if not any(fragments_by_section.values()):
        _add_freeform_fragments(
            fragments_by_section=fragments_by_section,
            raw_source_text=raw_source_text,
        )
    else:
        missing_sections = [
            name for name, fragments in fragments_by_section.items() if not fragments
        ]
        if missing_sections:
            freeform_fragments = {
                "post": [],
                "jd": [],
                "poster_profile": [],
            }
            _add_freeform_fragments(
                fragments_by_section=freeform_fragments,
                raw_source_text=raw_source_text,
            )
            for section_name in missing_sections:
                fragments_by_section[section_name] = freeform_fragments[section_name]

    return {
        "post": _build_section_payload(
            section_name="post",
            fragments=fragments_by_section["post"],
            artifact_path=post_path,
            clean_fn=_clean_post_text,
        ),
        "jd": _build_section_payload(
            section_name="jd",
            fragments=fragments_by_section["jd"],
            artifact_path=jd_path,
            clean_fn=_clean_jd_text,
        ),
        "poster_profile": _build_section_payload(
            section_name="poster_profile",
            fragments=fragments_by_section["poster_profile"],
            artifact_path=poster_profile_path,
            clean_fn=_clean_profile_text,
        ),
    }


def _add_capture_bundle_fragments(
    *,
    fragments_by_section: dict[str, list[dict[str, Any]]],
    raw_source_text: str,
    capture_bundle: Mapping[str, Any],
) -> None:
    raw_captures = capture_bundle.get("captures")
    if not isinstance(raw_captures, Sequence) or isinstance(raw_captures, (str, bytes)):
        return

    for raw_capture in raw_captures:
        if not isinstance(raw_capture, Mapping):
            continue
        page_type = _normalize_optional_text(raw_capture.get("page_type")) or "unknown"
        section_name = {
            "post": "post",
            "job": "jd",
            "profile": "poster_profile",
        }.get(page_type)
        if section_name is None:
            continue

        fragment_text = _preferred_capture_fragment(raw_capture, section_name=section_name)
        if fragment_text is None:
            continue
        fragments_by_section[section_name].append(
            {
                "text": fragment_text,
                "ranges": _line_ranges_for_fragment(raw_source_text, fragment_text),
                "capture_order": _capture_order(raw_capture),
                "page_type": page_type,
            }
        )


def _add_freeform_fragments(
    *,
    fragments_by_section: dict[str, list[dict[str, Any]]],
    raw_source_text: str,
) -> None:
    raw_lines = raw_source_text.splitlines()
    if not raw_lines:
        return

    jd_start = _find_jd_start(raw_lines)
    profile_start = _find_profile_start(raw_lines, start=(jd_start + 1) if jd_start is not None else 0)

    if jd_start is not None:
        post_lines = raw_lines[:jd_start]
        if _looks_like_post_block(post_lines):
            fragments_by_section["post"].append(
                _fragment_from_lines(post_lines, start_line=1, page_type="unknown")
            )

        jd_end = profile_start if profile_start is not None else len(raw_lines)
        jd_lines = raw_lines[jd_start:jd_end]
        if jd_lines:
            fragments_by_section["jd"].append(
                _fragment_from_lines(jd_lines, start_line=jd_start + 1, page_type="unknown")
            )

        if profile_start is not None:
            profile_lines = raw_lines[profile_start:]
            if profile_lines:
                fragments_by_section["poster_profile"].append(
                    _fragment_from_lines(
                        profile_lines,
                        start_line=profile_start + 1,
                        page_type="unknown",
                    )
                )
        return

    if _looks_like_post_block(raw_lines):
        fragments_by_section["post"].append(
            _fragment_from_lines(raw_lines, start_line=1, page_type="unknown")
        )


def _review_sections(
    *,
    sections: Mapping[str, Mapping[str, Any]],
) -> tuple[str, str, str, list[str], list[dict[str, str]], str]:
    jd_available = bool(sections["jd"]["available"])
    post_available = bool(sections["post"]["available"])
    profile_available = bool(sections["poster_profile"]["available"])

    if not jd_available:
        return (
            LEAD_SPLIT_REVIEW_AMBIGUOUS,
            LEAD_STATUS_SPLIT_READY,
            "low",
            ["No valid job-description section was detected from the canonical raw source."],
            [
                _validation_check(
                    name="jd_present",
                    status="fail",
                    message="A usable JD block was not detected.",
                ),
                _validation_check(
                    name="raw_source_preserved",
                    status="pass",
                    message="The canonical raw source remains unchanged and reviewable.",
                ),
            ],
            "review_split_before_materialization",
        )

    findings = ["A usable job-description section was detected from the canonical raw source."]
    validation_checks = [
        _validation_check(
            name="jd_present",
            status="pass",
            message="A usable JD block was detected.",
        ),
        _validation_check(
            name="raw_source_preserved",
            status="pass",
            message="The canonical raw source remains unchanged and reviewable.",
        ),
    ]
    if post_available:
        findings.append("A hiring-post section was derived for networking or outreach context.")
    else:
        findings.append("No separate hiring-post section was detected.")
    if profile_available:
        findings.append("A poster-profile section was derived from the captured evidence.")
    else:
        findings.append("No poster-profile section was detected.")

    if post_available and profile_available:
        return (
            LEAD_SPLIT_REVIEW_CONFIDENT,
            LEAD_STATUS_REVIEWED,
            "high",
            findings,
            validation_checks,
            "materialize_manual_lead_entities",
        )
    return (
        LEAD_SPLIT_REVIEW_NEEDS_REVIEW,
        LEAD_STATUS_REVIEWED,
        "medium",
        findings,
        validation_checks,
        "materialize_manual_lead_entities",
    )


def _build_section_payload(
    *,
    section_name: str,
    fragments: Sequence[Mapping[str, Any]],
    artifact_path: Path,
    clean_fn,
) -> dict[str, Any]:
    derived_parts: list[str] = []
    source_ranges: list[dict[str, int]] = []
    page_type_hints: list[str] = []
    capture_orders: list[int] = []
    omitted_segments: list[dict[str, str]] = []

    for fragment in fragments:
        fragment_text = fragment.get("text")
        if not isinstance(fragment_text, str) or not fragment_text.strip():
            continue
        cleaned_text, dropped_segments = clean_fn(fragment_text)
        if cleaned_text:
            derived_parts.append(cleaned_text)
        fragment_ranges = fragment.get("ranges") or []
        source_ranges.extend(fragment_ranges)
        page_type = fragment.get("page_type")
        if isinstance(page_type, str):
            page_type_hints.append(page_type)
        capture_order = fragment.get("capture_order")
        if isinstance(capture_order, int):
            capture_orders.append(capture_order)
        omitted_segments.extend(dropped_segments)

    derived_text = _join_unique_parts(derived_parts)
    return {
        "section_name": section_name,
        "artifact_path": artifact_path,
        "available": derived_text is not None,
        "derived_text": derived_text,
        "source_ranges": _dedupe_ranges(source_ranges),
        "page_type_hints": _dedupe_strings(page_type_hints),
        "capture_orders": sorted(set(capture_orders)),
        "omitted_segments": omitted_segments,
        "unavailable_reason": None if derived_text else "not_detected",
    }


def _preferred_capture_fragment(raw_capture: Mapping[str, Any], *, section_name: str) -> str | None:
    selected_text = _normalize_optional_text(raw_capture.get("selected_text"), preserve_whitespace=True)
    full_text = _normalize_optional_text(raw_capture.get("full_text"), preserve_whitespace=True)
    if section_name == "post":
        return full_text or selected_text
    return full_text or selected_text


def _capture_order(raw_capture: Mapping[str, Any]) -> int | None:
    raw_value = raw_capture.get("capture_order")
    try:
        return int(raw_value) if raw_value is not None else None
    except (TypeError, ValueError):
        return None


def _find_jd_start(raw_lines: Sequence[str]) -> int | None:
    for index, line in enumerate(raw_lines):
        if JD_MARKER_RE.search(line.strip()):
            return index
    return None


def _find_profile_start(raw_lines: Sequence[str], *, start: int) -> int | None:
    for index in range(start, len(raw_lines)):
        candidate = raw_lines[index].strip()
        if not candidate:
            continue
        if PROFILE_MARKER_RE.search(candidate):
            return index
    return None


def _looks_like_post_block(lines: Sequence[str]) -> bool:
    if not lines:
        return False
    joined = "\n".join(lines)
    return bool(POST_MARKER_RE.search(joined) or NETWORKING_HINT_RE.search(joined))


def _fragment_from_lines(lines: Sequence[str], *, start_line: int, page_type: str) -> dict[str, Any]:
    text = "\n".join(lines).strip()
    if not text:
        return {
            "text": "",
            "ranges": [],
            "capture_order": None,
            "page_type": page_type,
        }
    return {
        "text": text,
        "ranges": [
            {
                "start_line": start_line,
                "end_line": start_line + len(lines) - 1,
            }
        ],
        "capture_order": None,
        "page_type": page_type,
    }


def _line_ranges_for_fragment(raw_source_text: str, fragment_text: str) -> list[dict[str, int]]:
    raw_lines = raw_source_text.splitlines()
    fragment_lines = fragment_text.splitlines()
    if not raw_lines or not fragment_lines:
        return []

    matches: list[dict[str, int]] = []
    window = len(fragment_lines)
    for index in range(0, len(raw_lines) - window + 1):
        if raw_lines[index : index + window] == fragment_lines:
            matches.append({"start_line": index + 1, "end_line": index + window})
            break
    return matches


def _clean_post_text(text: str) -> tuple[str | None, list[dict[str, str]]]:
    return _clean_section_text(text, chrome_reasons=POST_CHROME_REASONS)


def _clean_jd_text(text: str) -> tuple[str | None, list[dict[str, str]]]:
    return _clean_section_text(text, chrome_reasons=JD_CHROME_REASONS)


def _clean_profile_text(text: str) -> tuple[str | None, list[dict[str, str]]]:
    return _clean_section_text(text, chrome_reasons=PROFILE_CHROME_REASONS)


def _clean_section_text(
    text: str,
    *,
    chrome_reasons: Mapping[str, str],
) -> tuple[str | None, list[dict[str, str]]]:
    lines = text.splitlines()
    cleaned_lines: list[str] = []
    omitted_segments: list[dict[str, str]] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if cleaned_lines and cleaned_lines[-1] != "":
                cleaned_lines.append("")
            continue
        reason = chrome_reasons.get(stripped.lower())
        if reason:
            omitted_segments.append({"snippet": stripped, "reason_code": reason})
            continue
        cleaned_lines.append(stripped)
    normalized = _normalize_clean_lines(cleaned_lines)
    return ("\n".join(normalized) if normalized else None, omitted_segments)


def _normalize_clean_lines(lines: Sequence[str]) -> list[str]:
    normalized = list(lines)
    while normalized and normalized[0] == "":
        normalized.pop(0)
    while normalized and normalized[-1] == "":
        normalized.pop()
    return normalized


def _join_unique_parts(parts: Sequence[str]) -> str | None:
    normalized_parts: list[str] = []
    seen: set[str] = set()
    for part in parts:
        stripped = part.strip()
        if not stripped or stripped in seen:
            continue
        normalized_parts.append(stripped)
        seen.add(stripped)
    if not normalized_parts:
        return None
    return "\n\n".join(normalized_parts) + "\n"


def _dedupe_ranges(ranges: Sequence[Mapping[str, Any]]) -> list[dict[str, int]]:
    seen: set[tuple[int, int]] = set()
    ordered: list[dict[str, int]] = []
    for candidate in ranges:
        try:
            key = (int(candidate["start_line"]), int(candidate["end_line"]))
        except (KeyError, TypeError, ValueError):
            continue
        if key in seen:
            continue
        seen.add(key)
        ordered.append({"start_line": key[0], "end_line": key[1]})
    return ordered


def _dedupe_strings(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _section_metadata_payload(section: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "available": section["available"],
        "artifact_path": str(section["artifact_path"].resolve()) if section["available"] else None,
        "section_ranges": section["source_ranges"],
        "page_type_hints": section["page_type_hints"],
        "capture_orders": section["capture_orders"],
        "omitted_segments": section["omitted_segments"],
        "unavailable_reason": section["unavailable_reason"],
    }


def _section_availability_payload(section: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "available": section["available"],
        "artifact_path": str(section["artifact_path"].resolve()) if section["available"] else None,
        "reason_code": None if section["available"] else section["unavailable_reason"],
    }


def _artifact_availability_from_path(path: Path, *, unavailable_reason: str = "not_detected") -> dict[str, Any]:
    available = path.exists()
    return {
        "available": available,
        "artifact_path": str(path.resolve()) if available else None,
        "reason_code": None if available else unavailable_reason,
    }


def _validation_check(*, name: str, status: str, message: str) -> dict[str, str]:
    return {
        "name": name,
        "status": status,
        "message": message,
    }


def _write_optional_markdown(path: Path, text: str | None) -> None:
    if text is None:
        if path.exists():
            path.unlink()
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _replace_lead_artifact_record(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    artifact_type: str,
    artifact_path: Path,
    lead_id: str,
    created_at: str,
) -> None:
    connection.execute(
        "DELETE FROM artifact_records WHERE artifact_type = ? AND lead_id = ?",
        (artifact_type, lead_id),
    )
    register_artifact_record(
        connection,
        paths,
        artifact_type=artifact_type,
        artifact_path=artifact_path,
        producer_component=LINKEDIN_SCRAPING_COMPONENT,
        linkage=ArtifactLinkage(lead_id=lead_id),
        created_at=created_at,
    )


def _write_manual_lead_manifest(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    lead_row: Mapping[str, Any],
    lead_status: str,
    lead_shape: str,
    split_review_status: str,
    artifact_paths: Mapping[str, Path],
    created_entities: Mapping[str, Any],
    handoff_targets: Mapping[str, Any],
) -> dict[str, Any]:
    lead_manifest_path = artifact_paths["lead_manifest_path"]
    contract = write_yaml_contract(
        lead_manifest_path,
        producer_component=LINKEDIN_SCRAPING_COMPONENT,
        result="success",
        linkage=ArtifactLinkage(lead_id=lead_row["lead_id"]),
        payload=_build_manual_lead_manifest_payload(
            lead_row=lead_row,
            lead_status=lead_status,
            lead_shape=lead_shape,
            split_review_status=split_review_status,
            artifact_paths=artifact_paths,
            created_entities=created_entities,
            handoff_targets=handoff_targets,
        ),
    )
    _replace_lead_artifact_record(
        connection,
        paths,
        artifact_type=LEAD_MANIFEST_ARTIFACT_TYPE,
        artifact_path=lead_manifest_path,
        lead_id=lead_row["lead_id"],
        created_at=contract["produced_at"],
    )
    return contract


def _build_manual_lead_manifest_payload(
    *,
    lead_row: Mapping[str, Any],
    lead_status: str,
    lead_shape: str,
    split_review_status: str,
    artifact_paths: Mapping[str, Path],
    created_entities: Mapping[str, Any],
    handoff_targets: Mapping[str, Any],
) -> dict[str, Any]:
    capture_bundle_path = artifact_paths["capture_bundle_path"]
    raw_source_path = artifact_paths["raw_source_path"]
    post_path = artifact_paths["post_path"]
    jd_path = artifact_paths["jd_path"]
    poster_profile_path = artifact_paths["poster_profile_path"]
    split_metadata_path = artifact_paths["split_metadata_path"]
    split_review_path = artifact_paths["split_review_path"]
    return {
        "lead_status": lead_status,
        "lead_shape": lead_shape,
        "split_review_status": split_review_status,
        "source": {
            "source_type": lead_row["source_type"],
            "source_reference": lead_row["source_reference"],
            "source_mode": lead_row["source_mode"],
            "source_url": lead_row["source_url"],
        },
        "summary": {
            "company_name": lead_row["company_name"],
            "role_title": lead_row["role_title"],
            "location": lead_row["location"],
            "work_mode": lead_row["work_mode"],
            "compensation_summary": lead_row["compensation_summary"],
            "poster_name": lead_row["poster_name"],
            "poster_title": lead_row["poster_title"],
        },
        "artifacts": {
            "capture_bundle_path": str(capture_bundle_path.resolve()) if capture_bundle_path.exists() else None,
            "raw_source_path": str(raw_source_path.resolve()) if raw_source_path.exists() else None,
            "post_path": str(post_path.resolve()) if post_path.exists() else None,
            "jd_path": str(jd_path.resolve()) if jd_path.exists() else None,
            "poster_profile_path": str(poster_profile_path.resolve()) if poster_profile_path.exists() else None,
            "split_metadata_path": str(split_metadata_path.resolve()) if split_metadata_path.exists() else None,
            "split_review_path": str(split_review_path.resolve()) if split_review_path.exists() else None,
        },
        "artifact_availability": {
            "post": _artifact_availability_from_path(post_path),
            "jd": _artifact_availability_from_path(jd_path),
            "poster_profile": _artifact_availability_from_path(poster_profile_path),
        },
        "created_entities": dict(created_entities),
        "handoff_targets": dict(handoff_targets),
    }


def _build_posting_materialization_target(
    *,
    split_review_status: str,
    jd_path: Path,
    job_posting_id: str | None,
    allow_existing_posting_to_satisfy_target: bool = True,
) -> dict[str, Any]:
    ready, reason_code = _posting_materialization_status(
        split_review_status=split_review_status,
        jd_path=jd_path,
    )
    if job_posting_id is not None and allow_existing_posting_to_satisfy_target:
        ready = True
        reason_code = None
    target = {
        "ready": ready,
        "reason_code": reason_code,
        "required_artifacts": [str(jd_path.resolve())] if jd_path.exists() else [],
    }
    if job_posting_id is not None:
        target["created_entities"] = {"job_posting_id": job_posting_id}
    return target


def _build_resume_tailoring_target(
    *,
    job_posting_id: str | None,
    jd_path: Path,
) -> dict[str, Any]:
    ready = job_posting_id is not None and jd_path.exists()
    if ready:
        reason_code = None
    elif job_posting_id is None:
        reason_code = MANIFEST_REASON_POSTING_NOT_MATERIALIZED
    else:
        reason_code = MANIFEST_REASON_MISSING_JD
    target = {
        "ready": ready,
        "reason_code": reason_code,
        "required_artifacts": [str(jd_path.resolve())] if jd_path.exists() else [],
    }
    if job_posting_id is not None:
        target["created_entities"] = {"job_posting_id": job_posting_id}
    return target


def _posting_materialization_status(
    *,
    split_review_status: str,
    jd_path: Path,
) -> tuple[bool, str | None]:
    if split_review_status == LEAD_SPLIT_REVIEW_AMBIGUOUS:
        return False, MANIFEST_REASON_AMBIGUOUS_SPLIT_REVIEW
    if split_review_status == LEAD_SPLIT_REVIEW_NOT_STARTED:
        return False, MANIFEST_REASON_SPLIT_REVIEW_NOT_READY
    if not jd_path.exists():
        return False, MANIFEST_REASON_MISSING_JD
    return True, None


def _collect_created_entities(
    connection: sqlite3.Connection,
    *,
    lead_id: str,
    job_posting_id: str | None,
) -> dict[str, Any]:
    lead_contact_rows = connection.execute(
        """
        SELECT linkedin_lead_contact_id, contact_id
        FROM linkedin_lead_contacts
        WHERE lead_id = ?
        ORDER BY created_at ASC, linkedin_lead_contact_id ASC
        """,
        (lead_id,),
    ).fetchall()
    posting_contact_rows = []
    if job_posting_id is not None:
        posting_contact_rows = connection.execute(
            """
            SELECT job_posting_contact_id, contact_id
            FROM job_posting_contacts
            WHERE job_posting_id = ?
            ORDER BY created_at ASC, job_posting_contact_id ASC
            """,
            (job_posting_id,),
        ).fetchall()

    contact_ids: list[str] = []
    seen_contact_ids: set[str] = set()
    for row in [*lead_contact_rows, *posting_contact_rows]:
        contact_id = row["contact_id"]
        if contact_id in seen_contact_ids:
            continue
        seen_contact_ids.add(contact_id)
        contact_ids.append(contact_id)

    return {
        "job_posting_id": job_posting_id,
        "contact_ids": contact_ids,
        "job_posting_contact_ids": [row["job_posting_contact_id"] for row in posting_contact_rows],
        "linkedin_lead_contact_ids": [row["linkedin_lead_contact_id"] for row in lead_contact_rows],
    }


def _upsert_job_posting(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    lead_row: Mapping[str, Any],
    jd_path: Path,
) -> tuple[str, bool]:
    existing_posting = _find_existing_posting_for_lead(connection, lead_id=lead_row["lead_id"])
    posting_identity_key = _build_posting_identity_key(lead_row, jd_path=jd_path)
    jd_artifact_path = paths.relative_to_root(jd_path).as_posix()
    updated_at = now_utc_iso()
    if existing_posting is not None:
        connection.execute(
            """
            UPDATE job_postings
            SET posting_identity_key = ?, company_name = ?, role_title = ?, location = ?,
                jd_artifact_path = ?, updated_at = ?
            WHERE job_posting_id = ?
            """,
            (
                posting_identity_key,
                lead_row["company_name"],
                lead_row["role_title"],
                lead_row["location"],
                jd_artifact_path,
                updated_at,
                existing_posting["job_posting_id"],
            ),
        )
        return existing_posting["job_posting_id"], False

    timestamps = lifecycle_timestamps(updated_at)
    job_posting_id = new_canonical_id("job_postings")
    connection.execute(
        """
        INSERT INTO job_postings (
          job_posting_id, lead_id, posting_identity_key, company_name, role_title, posting_status,
          location, employment_type, posted_at, jd_artifact_path, archived_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job_posting_id,
            lead_row["lead_id"],
            posting_identity_key,
            lead_row["company_name"],
            lead_row["role_title"],
            JOB_POSTING_STATUS_SOURCED,
            lead_row["location"],
            None,
            None,
            jd_artifact_path,
            None,
            timestamps["created_at"],
            timestamps["updated_at"],
        ),
    )
    return job_posting_id, True


def _build_posting_identity_key(lead_row: Mapping[str, Any], *, jd_path: Path) -> str:
    normalized_jd = " ".join(jd_path.read_text(encoding="utf-8").split())
    jd_fingerprint = hashlib.sha256(normalized_jd.encode("utf-8")).hexdigest()[:16]
    return "|".join(
        [
            "manual_lead",
            workspace_slug(lead_row["company_name"] or "unknown"),
            workspace_slug(lead_row["role_title"] or "unknown"),
            workspace_slug(lead_row["location"] or "unknown"),
            jd_fingerprint,
        ]
    )


def _materialize_manual_poster_contact(
    connection: sqlite3.Connection,
    *,
    lead_row: Mapping[str, Any],
    capture_bundle: Mapping[str, Any] | None,
    poster_profile_path: Path,
    job_posting_id: str,
) -> dict[str, Any] | None:
    poster_candidate = _extract_poster_candidate(
        lead_row=lead_row,
        capture_bundle=capture_bundle,
        poster_profile_path=poster_profile_path,
    )
    if poster_candidate is None:
        return None

    existing_lead_contact = connection.execute(
        """
        SELECT llc.linkedin_lead_contact_id, llc.contact_id
        FROM linkedin_lead_contacts AS llc
        WHERE llc.lead_id = ? AND llc.is_primary_poster = 1
        ORDER BY llc.created_at ASC, llc.linkedin_lead_contact_id ASC
        """,
        (lead_row["lead_id"],),
    ).fetchall()
    if len(existing_lead_contact) > 1:
        raise LinkedInScrapingError(
            f"Lead `{lead_row['lead_id']}` has multiple primary-poster lead links."
        )

    contact_created = False
    if existing_lead_contact:
        contact_id = existing_lead_contact[0]["contact_id"]
        linkedin_lead_contact_id = existing_lead_contact[0]["linkedin_lead_contact_id"]
    else:
        reusable_contact = _find_reusable_contact(connection, poster_candidate)
        if reusable_contact is None:
            contact_id = new_canonical_id("contacts")
            timestamps = lifecycle_timestamps()
            connection.execute(
                """
                INSERT INTO contacts (
                  contact_id, identity_key, display_name, company_name, origin_component, contact_status,
                  full_name, first_name, last_name, linkedin_url, position_title, location,
                  discovery_summary, current_working_email, identity_source, provider_name,
                  provider_person_id, name_quality, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    contact_id,
                    poster_candidate["identity_key"],
                    poster_candidate["display_name"],
                    poster_candidate["company_name"],
                    LINKEDIN_SCRAPING_COMPONENT,
                    CONTACT_STATUS_IDENTIFIED,
                    poster_candidate["full_name"],
                    poster_candidate["first_name"],
                    poster_candidate["last_name"],
                    poster_candidate["linkedin_url"],
                    poster_candidate["position_title"],
                    None,
                    None,
                    None,
                    poster_candidate["identity_source"],
                    None,
                    None,
                    "manual_capture_exact",
                    timestamps["created_at"],
                    timestamps["updated_at"],
                ),
            )
            contact_created = True
        else:
            contact_id = reusable_contact["contact_id"]
        linkedin_lead_contact_id = new_canonical_id("linkedin_lead_contacts")
        timestamps = lifecycle_timestamps()
        connection.execute(
            """
            INSERT INTO linkedin_lead_contacts (
              linkedin_lead_contact_id, lead_id, contact_id, contact_role, recipient_type_inferred,
              is_primary_poster, extraction_confidence, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                linkedin_lead_contact_id,
                lead_row["lead_id"],
                contact_id,
                LEAD_CONTACT_ROLE_POSTER,
                poster_candidate["recipient_type"],
                1,
                "high",
                timestamps["created_at"],
                timestamps["updated_at"],
            ),
        )

    existing_contact = connection.execute(
        """
        SELECT contact_id, company_name, origin_component, contact_status, current_working_email,
               provider_name, provider_person_id, name_quality, created_at
        FROM contacts
        WHERE contact_id = ?
        """,
        (contact_id,),
    ).fetchone()
    updated_at = now_utc_iso()
    connection.execute(
        """
        UPDATE contacts
        SET identity_key = ?, display_name = ?, company_name = ?, origin_component = ?, contact_status = ?,
            full_name = ?, first_name = ?, last_name = ?, linkedin_url = ?, position_title = ?,
            identity_source = ?, name_quality = ?, updated_at = ?
        WHERE contact_id = ?
        """,
        (
            poster_candidate["identity_key"],
            poster_candidate["display_name"],
            poster_candidate["company_name"],
            existing_contact["origin_component"] if existing_contact is not None else LINKEDIN_SCRAPING_COMPONENT,
            existing_contact["contact_status"] if existing_contact is not None else CONTACT_STATUS_IDENTIFIED,
            poster_candidate["full_name"],
            poster_candidate["first_name"],
            poster_candidate["last_name"],
            poster_candidate["linkedin_url"],
            poster_candidate["position_title"],
            poster_candidate["identity_source"],
            "manual_capture_exact",
            updated_at,
            contact_id,
        ),
    )

    existing_posting_contact = connection.execute(
        """
        SELECT job_posting_contact_id
        FROM job_posting_contacts
        WHERE job_posting_id = ? AND contact_id = ?
        ORDER BY created_at ASC, job_posting_contact_id ASC
        """,
        (job_posting_id, contact_id),
    ).fetchall()
    if len(existing_posting_contact) > 1:
        raise LinkedInScrapingError(
            f"Posting `{job_posting_id}` has multiple contact links for contact `{contact_id}`."
        )

    if existing_posting_contact:
        job_posting_contact_id = existing_posting_contact[0]["job_posting_contact_id"]
        connection.execute(
            """
            UPDATE job_posting_contacts
            SET recipient_type = ?, relevance_reason = ?, updated_at = ?
            WHERE job_posting_contact_id = ?
            """,
            (
                poster_candidate["recipient_type"],
                poster_candidate["relevance_reason"],
                updated_at,
                job_posting_contact_id,
            ),
        )
    else:
        job_posting_contact_id = new_canonical_id("job_posting_contacts")
        timestamps = lifecycle_timestamps(updated_at)
        connection.execute(
            """
            INSERT INTO job_posting_contacts (
              job_posting_contact_id, job_posting_id, contact_id, recipient_type, relevance_reason,
              link_level_status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_posting_contact_id,
                job_posting_id,
                contact_id,
                poster_candidate["recipient_type"],
                poster_candidate["relevance_reason"],
                POSTING_CONTACT_STATUS_IDENTIFIED,
                timestamps["created_at"],
                timestamps["updated_at"],
            ),
        )

    if not existing_lead_contact:
        connection.execute(
            """
            UPDATE linkedin_lead_contacts
            SET extraction_confidence = ?, updated_at = ?
            WHERE linkedin_lead_contact_id = ?
            """,
            (
                "high",
                updated_at,
                linkedin_lead_contact_id,
            ),
        )
    else:
        connection.execute(
            """
            UPDATE linkedin_lead_contacts
            SET recipient_type_inferred = ?, extraction_confidence = ?, updated_at = ?
            WHERE linkedin_lead_contact_id = ?
            """,
            (
                poster_candidate["recipient_type"],
                "high",
                updated_at,
                linkedin_lead_contact_id,
            ),
        )

    return {
        "contact_id": contact_id,
        "contact_created": contact_created,
        "linkedin_lead_contact_id": linkedin_lead_contact_id,
        "job_posting_contact_id": job_posting_contact_id,
        "display_name": poster_candidate["display_name"],
        "position_title": poster_candidate["position_title"],
    }


def _extract_poster_candidate(
    *,
    lead_row: Mapping[str, Any],
    capture_bundle: Mapping[str, Any] | None,
    poster_profile_path: Path,
) -> dict[str, Any] | None:
    parsed_profile_name, parsed_profile_title = _parse_poster_profile(poster_profile_path)
    display_name = lead_row["poster_name"] or parsed_profile_name
    position_title = lead_row["poster_title"] or parsed_profile_title
    linkedin_url = _profile_source_url(capture_bundle)
    if display_name is None:
        return None
    if not poster_profile_path.exists() and position_title is None and linkedin_url is None:
        return None

    first_name, last_name = _split_person_name(display_name)
    recipient_type = _infer_recipient_type(position_title)
    return {
        "display_name": display_name,
        "full_name": display_name if " " in display_name.strip() else None,
        "first_name": first_name,
        "last_name": last_name,
        "position_title": position_title,
        "linkedin_url": linkedin_url,
        "company_name": lead_row["company_name"],
        "identity_key": _build_contact_identity_key(
            company_name=lead_row["company_name"],
            display_name=display_name,
            position_title=position_title,
            linkedin_url=linkedin_url,
        ),
        "identity_source": "manual_capture_profile" if poster_profile_path.exists() else "manual_capture_summary",
        "recipient_type": recipient_type,
        "relevance_reason": _recipient_relevance_reason(
            recipient_type=recipient_type,
            position_title=position_title,
        ),
    }


def _find_reusable_contact(
    connection: sqlite3.Connection,
    poster_candidate: Mapping[str, Any],
) -> sqlite3.Row | None:
    linkedin_url = poster_candidate["linkedin_url"]
    if linkedin_url:
        rows = connection.execute(
            """
            SELECT contact_id
            FROM contacts
            WHERE linkedin_url = ? AND company_name = ?
            ORDER BY created_at ASC, contact_id ASC
            """,
            (linkedin_url, poster_candidate["company_name"]),
        ).fetchall()
        if len(rows) == 1:
            return rows[0]
        if len(rows) > 1:
            return None

    rows = connection.execute(
        """
        SELECT contact_id
        FROM contacts
        WHERE identity_key = ? AND company_name = ?
        ORDER BY created_at ASC, contact_id ASC
        """,
        (poster_candidate["identity_key"], poster_candidate["company_name"]),
    ).fetchall()
    if len(rows) == 1:
        return rows[0]
    return None


def _parse_poster_profile(poster_profile_path: Path) -> tuple[str | None, str | None]:
    if not poster_profile_path.exists():
        return None, None
    lines = [line.strip() for line in poster_profile_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        return None, None
    display_name = lines[0]
    position_title = None
    for line in lines[1:]:
        if line.lower() in {"about", "experience", "activity"}:
            break
        if PROFILE_MARKER_RE.search(line):
            continue
        position_title = line
        break
    return display_name, position_title


def _profile_source_url(capture_bundle: Mapping[str, Any] | None) -> str | None:
    if capture_bundle is None:
        return None
    raw_captures = capture_bundle.get("captures")
    if not isinstance(raw_captures, Sequence) or isinstance(raw_captures, (str, bytes)):
        return None
    for raw_capture in raw_captures:
        if not isinstance(raw_capture, Mapping):
            continue
        page_type = _normalize_optional_text(raw_capture.get("page_type")) or "unknown"
        if page_type != "profile":
            continue
        source_url = _normalize_optional_text(raw_capture.get("source_url"))
        if source_url:
            return source_url
    return None


def _build_contact_identity_key(
    *,
    company_name: str,
    display_name: str,
    position_title: str | None,
    linkedin_url: str | None,
) -> str:
    if linkedin_url:
        return "|".join(
            [
                "linkedin_profile",
                workspace_slug(company_name),
                workspace_slug(linkedin_url),
            ]
        )
    return "|".join(
        [
            "manual_poster",
            workspace_slug(company_name),
            workspace_slug(display_name),
            workspace_slug(position_title or "unknown"),
        ]
    )


def _split_person_name(display_name: str) -> tuple[str | None, str | None]:
    parts = [part for part in display_name.strip().split() if part]
    if not parts:
        return None, None
    if len(parts) == 1:
        return parts[0], None
    return parts[0], " ".join(parts[1:])


def _infer_recipient_type(position_title: str | None) -> str:
    normalized = (position_title or "").lower()
    if "founder" in normalized or "co-founder" in normalized or "cofounder" in normalized:
        return RECIPIENT_TYPE_FOUNDER
    if any(token in normalized for token in ("recruit", "talent", "sourcer", "people ops")):
        return RECIPIENT_TYPE_RECRUITER
    if "alumni" in normalized:
        return RECIPIENT_TYPE_ALUMNI
    if any(token in normalized for token in ("manager", "director", "head", "vp", "vice president", "chief")):
        return RECIPIENT_TYPE_HIRING_MANAGER
    if any(token in normalized for token in ("engineer", "developer", "architect", "swe", "software")):
        return RECIPIENT_TYPE_ENGINEER
    return RECIPIENT_TYPE_OTHER_INTERNAL


def _recipient_relevance_reason(*, recipient_type: str, position_title: str | None) -> str:
    if recipient_type == RECIPIENT_TYPE_FOUNDER:
        return "Poster title indicates founder-level internal routing context."
    if recipient_type == RECIPIENT_TYPE_RECRUITER:
        return "Poster title indicates a recruiting contact for this role."
    if recipient_type == RECIPIENT_TYPE_HIRING_MANAGER:
        return "Poster title indicates leadership close to the likely hiring loop."
    if recipient_type == RECIPIENT_TYPE_ENGINEER:
        return "Poster title indicates a role-relevant internal engineer."
    if recipient_type == RECIPIENT_TYPE_ALUMNI:
        return "Poster evidence suggests an alumni-style networking contact."
    if position_title:
        return f"Poster identified directly from manual lead evidence as `{position_title}`."
    return "Poster identified directly from manual lead evidence."


def _load_manual_lead_row(connection: sqlite3.Connection, *, lead_id: str) -> sqlite3.Row:
    lead_row = connection.execute(
        """
        SELECT lead_id, lead_status, lead_shape, split_review_status, source_type, source_reference,
               source_mode, source_url, company_name, role_title, location, work_mode,
               compensation_summary, poster_name, poster_title
        FROM linkedin_leads
        WHERE lead_id = ?
        """,
        (lead_id,),
    ).fetchone()
    if lead_row is None:
        raise LinkedInScrapingError(f"Lead `{lead_id}` was not found.")
    if lead_row["source_mode"] not in {SOURCE_MODE_MANUAL_CAPTURE, SOURCE_MODE_MANUAL_PASTE}:
        raise LinkedInScrapingError(
            f"Lead `{lead_id}` is not a manual lead and cannot use the manual lead-materialization pipeline."
        )
    return lead_row


def _find_existing_posting_for_lead(
    connection: sqlite3.Connection,
    *,
    lead_id: str,
) -> sqlite3.Row | None:
    rows = connection.execute(
        """
        SELECT job_posting_id, posting_status
        FROM job_postings
        WHERE lead_id = ?
        ORDER BY created_at ASC, job_posting_id ASC
        """,
        (lead_id,),
    ).fetchall()
    if not rows:
        return None
    if len(rows) > 1:
        raise LinkedInScrapingError(
            f"Lead `{lead_id}` already has multiple `job_postings` rows."
        )
    return rows[0]


def _find_existing_lead(
    connection: sqlite3.Connection,
    lead_identity_key: str,
) -> sqlite3.Row | None:
    rows = connection.execute(
        """
        SELECT lead_id, company_name, role_title, source_type, source_mode
        FROM linkedin_leads
        WHERE lead_identity_key = ?
        ORDER BY created_at ASC
        """,
        (lead_identity_key,),
    ).fetchall()
    if not rows:
        return None
    if len(rows) > 1:
        raise LinkedInScrapingError(
            f"Multiple leads already exist for lead_identity_key `{lead_identity_key}`."
        )
    return rows[0]


def _normalize_required_text(value: Any, *, field_name: str) -> str:
    normalized = _normalize_optional_text(value)
    if normalized is None:
        raise LinkedInScrapingError(f"{field_name} is required.")
    return normalized


def _normalize_optional_text(value: Any, *, preserve_whitespace: bool = False) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise LinkedInScrapingError("Expected string input for manual capture fields.")
    normalized = value if preserve_whitespace else value.strip()
    return normalized if normalized else None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=None)
    subparsers = parser.add_subparsers(dest="command", required=True)

    paste_parser = subparsers.add_parser("paste")
    paste_parser.add_argument("--company-name", required=True)
    paste_parser.add_argument("--role-title", required=True)
    paste_parser.add_argument("--location")
    paste_parser.add_argument("--work-mode")
    paste_parser.add_argument("--compensation-summary")
    paste_parser.add_argument("--poster-name")
    paste_parser.add_argument("--poster-title")
    paste_parser.add_argument("--lead-id")

    bundle_parser = subparsers.add_parser("capture-bundle")
    bundle_parser.add_argument("--bundle", required=True)
    bundle_parser.add_argument("--lead-id")

    derive_parser = subparsers.add_parser("derive")
    derive_parser.add_argument("--lead-id", required=True)

    materialize_parser = subparsers.add_parser("materialize")
    materialize_parser.add_argument("--lead-id", required=True)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "paste":
            result = ingest_paste_inbox(
                args.project_root,
                company_name=args.company_name,
                role_title=args.role_title,
                location=args.location,
                work_mode=args.work_mode,
                compensation_summary=args.compensation_summary,
                poster_name=args.poster_name,
                poster_title=args.poster_title,
                existing_lead_id=args.lead_id,
            )
        else:
            if args.command == "derive":
                result = derive_manual_lead_context(
                    args.project_root,
                    lead_id=args.lead_id,
                )
            elif args.command == "materialize":
                result = materialize_manual_lead_entities(
                    args.project_root,
                    lead_id=args.lead_id,
                )
            else:
                result = ingest_manual_capture_submission(
                    args.project_root,
                    submission=load_manual_capture_submission(args.bundle),
                    existing_lead_id=args.lead_id,
                )
    except Exception as exc:  # pragma: no cover - CLI formatting
        print(
            json.dumps(
                {
                    "status": "error",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                },
                indent=2,
            )
        )
        return 1

    print(json.dumps(result.as_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
