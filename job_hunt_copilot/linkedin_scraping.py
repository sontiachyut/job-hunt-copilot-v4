from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .artifacts import ArtifactLinkage, register_artifact_record
from .contracts import CONTRACT_VERSION
from .paths import ProjectPaths, workspace_slug
from .records import lifecycle_timestamps, new_canonical_id, now_utc_iso


LINKEDIN_SCRAPING_COMPONENT = "linkedin_scraping"

LEAD_STATUS_CAPTURED = "captured"
LEAD_SPLIT_REVIEW_NOT_STARTED = "not_started"
LEAD_SHAPE_POSTING_ONLY = "posting_only"

SOURCE_MODE_MANUAL_CAPTURE = "manual_capture"
SOURCE_MODE_MANUAL_PASTE = "manual_paste"

SOURCE_TYPE_MANUAL_CAPTURE_BUNDLE = "manual_capture_bundle"
SOURCE_TYPE_MANUAL_PASTE = "manual_paste"

SUBMISSION_PATH_IMMEDIATE_SELECTED_TEXT = "immediate_selected_text"
SUBMISSION_PATH_TRAY_REVIEW = "tray_review"
SUBMISSION_PATH_PASTE_INBOX = "paste_inbox"

LEAD_RAW_SOURCE_ARTIFACT_TYPE = "lead_raw_source"

TEXT_CAPTURE_MODES = frozenset({"selected_text", "full_page", "manual_paste"})
PAGE_TYPES = frozenset({"post", "job", "profile", "unknown"})


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
