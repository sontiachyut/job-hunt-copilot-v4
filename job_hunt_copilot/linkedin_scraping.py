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
LEAD_SPLIT_REVIEW_NOT_STARTED = "not_started"
LEAD_SPLIT_REVIEW_CONFIDENT = "confident"
LEAD_SPLIT_REVIEW_NEEDS_REVIEW = "needs_review"
LEAD_SPLIT_REVIEW_AMBIGUOUS = "ambiguous"
LEAD_SHAPE_POSTING_ONLY = "posting_only"

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

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "lead_id": self.lead_id,
            "lead_identity_key": self.lead_identity_key,
            "source_mode": self.source_mode,
            "source_type": self.source_type,
            "created": self.created,
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
        existing_lead = _find_existing_lead(connection, lead_identity_key)
        if existing_lead is not None:
            workspace_dir = paths.lead_workspace_dir(
                existing_lead["company_name"],
                existing_lead["role_title"],
                existing_lead["lead_id"],
            )
            return ManualLeadIngestionResult(
                lead_id=existing_lead["lead_id"],
                lead_identity_key=lead_identity_key,
                source_mode=existing_lead["source_mode"],
                source_type=existing_lead["source_type"],
                workspace_dir=workspace_dir,
                capture_bundle_path=paths.lead_capture_bundle_path(
                    existing_lead["company_name"],
                    existing_lead["role_title"],
                    existing_lead["lead_id"],
                ),
                raw_source_path=paths.lead_raw_source_path(
                    existing_lead["company_name"],
                    existing_lead["role_title"],
                    existing_lead["lead_id"],
                ),
                created=False,
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
        capture_bundle_path.parent.mkdir(parents=True, exist_ok=True)
        capture_bundle_path.write_text(json.dumps(capture_bundle, indent=2) + "\n", encoding="utf-8")

        if normalized_submission.source_type == SOURCE_TYPE_MANUAL_PASTE:
            raw_capture = normalized_submission.captures[0]
            if raw_capture.full_text is None:
                raise LinkedInScrapingError("manual_paste capture must include full_text.")
            raw_source_path.parent.mkdir(parents=True, exist_ok=True)
            raw_source_path.write_bytes(raw_capture.full_text.encode("utf-8"))
        else:
            raw_source_path.parent.mkdir(parents=True, exist_ok=True)
            raw_source_path.write_text(render_manual_capture_source(normalized_submission), encoding="utf-8")

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
    return ingest_manual_capture_submission(paths.project_root, submission=submission)


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

        workspace_dir = paths.lead_workspace_dir(
            lead_row["company_name"],
            lead_row["role_title"],
            lead_id,
        )
        raw_source_path = paths.lead_raw_source_path(
            lead_row["company_name"],
            lead_row["role_title"],
            lead_id,
        )
        capture_bundle_path = paths.lead_capture_bundle_path(
            lead_row["company_name"],
            lead_row["role_title"],
            lead_id,
        )
        post_path = paths.lead_post_path(lead_row["company_name"], lead_row["role_title"], lead_id)
        jd_path = paths.lead_jd_path(lead_row["company_name"], lead_row["role_title"], lead_id)
        poster_profile_path = paths.lead_poster_profile_path(
            lead_row["company_name"],
            lead_row["role_title"],
            lead_id,
        )
        split_metadata_path = paths.lead_split_metadata_path(
            lead_row["company_name"],
            lead_row["role_title"],
            lead_id,
        )
        split_review_path = paths.lead_split_review_path(
            lead_row["company_name"],
            lead_row["role_title"],
            lead_id,
        )
        lead_manifest_path = paths.lead_manifest_path(
            lead_row["company_name"],
            lead_row["role_title"],
            lead_id,
        )

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

        posting_handoff_ready = review_status != LEAD_SPLIT_REVIEW_AMBIGUOUS and sections["jd"]["available"]
        posting_handoff_reason = None
        if review_status == LEAD_SPLIT_REVIEW_AMBIGUOUS:
            posting_handoff_reason = "ambiguous_split_review"
        elif not sections["jd"]["available"]:
            posting_handoff_reason = "missing_jd"

        lead_manifest_contract = write_yaml_contract(
            lead_manifest_path,
            producer_component=LINKEDIN_SCRAPING_COMPONENT,
            result="success",
            linkage=linkage,
            payload={
                "lead_status": lead_status,
                "lead_shape": lead_row["lead_shape"],
                "split_review_status": review_status,
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
                    "raw_source_path": str(raw_source_path.resolve()),
                    "post_path": str(post_path.resolve()) if sections["post"]["available"] else None,
                    "jd_path": str(jd_path.resolve()) if sections["jd"]["available"] else None,
                    "poster_profile_path": (
                        str(poster_profile_path.resolve()) if sections["poster_profile"]["available"] else None
                    ),
                    "split_metadata_path": str(split_metadata_path.resolve()),
                    "split_review_path": str(split_review_path.resolve()),
                },
                "artifact_availability": {
                    name: _section_availability_payload(section)
                    for name, section in sections.items()
                },
                "created_entities": {
                    "job_posting_id": None,
                    "contact_ids": [],
                    "job_posting_contact_ids": [],
                    "linkedin_lead_contact_ids": [],
                },
                "handoff_targets": {
                    "posting_materialization": {
                        "ready": posting_handoff_ready,
                        "reason_code": posting_handoff_reason,
                        "required_artifacts": [
                            str(jd_path.resolve())
                        ]
                        if sections["jd"]["available"]
                        else [],
                    }
                },
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
            _replace_lead_artifact_record(
                connection,
                paths,
                artifact_type=LEAD_MANIFEST_ARTIFACT_TYPE,
                artifact_path=lead_manifest_path,
                lead_id=lead_id,
                created_at=lead_manifest_contract["produced_at"],
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

    bundle_parser = subparsers.add_parser("capture-bundle")
    bundle_parser.add_argument("--bundle", required=True)

    derive_parser = subparsers.add_parser("derive")
    derive_parser.add_argument("--lead-id", required=True)

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
            )
        else:
            if args.command == "derive":
                result = derive_manual_lead_context(
                    args.project_root,
                    lead_id=args.lead_id,
                )
            else:
                result = ingest_manual_capture_submission(
                    args.project_root,
                    submission=load_manual_capture_submission(args.bundle),
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
