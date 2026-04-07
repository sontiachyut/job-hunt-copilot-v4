from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from .artifacts import (
    ArtifactLinkage,
    PublishedArtifact,
    artifact_location,
    publish_yaml_artifact,
    register_artifact_record,
    write_yaml_contract,
)
from .paths import ProjectPaths
from .records import lifecycle_timestamps, new_canonical_id, now_utc_iso


RESUME_TAILORING_COMPONENT = "resume_tailoring"
TAILORING_ELIGIBILITY_ARTIFACT_TYPE = "tailoring_eligibility"
TAILORING_META_ARTIFACT_TYPE = "tailoring_meta"

ELIGIBILITY_STATUS_ELIGIBLE = "eligible"
ELIGIBILITY_STATUS_SOFT_FLAG = "soft-flag"
ELIGIBILITY_STATUS_HARD_INELIGIBLE = "hard-ineligible"
ELIGIBILITY_STATUS_UNKNOWN = "unknown"

TAILORING_STATUS_IN_PROGRESS = "in_progress"
TAILORING_STATUS_NEEDS_REVISION = "needs_revision"
TAILORING_STATUS_TAILORED = "tailored"
TAILORING_STATUS_FAILED = "failed"
TAILORING_STATUSES = frozenset(
    {
        TAILORING_STATUS_IN_PROGRESS,
        TAILORING_STATUS_NEEDS_REVISION,
        TAILORING_STATUS_TAILORED,
        TAILORING_STATUS_FAILED,
    }
)

RESUME_REVIEW_STATUS_NOT_READY = "not_ready"
RESUME_REVIEW_STATUS_PENDING = "resume_review_pending"
RESUME_REVIEW_STATUS_APPROVED = "approved"
RESUME_REVIEW_STATUS_REJECTED = "rejected"
RESUME_REVIEW_STATUSES = frozenset(
    {
        RESUME_REVIEW_STATUS_NOT_READY,
        RESUME_REVIEW_STATUS_PENDING,
        RESUME_REVIEW_STATUS_APPROVED,
        RESUME_REVIEW_STATUS_REJECTED,
    }
)

JOB_POSTING_STATUS_HARD_INELIGIBLE = "hard_ineligible"

BOOTSTRAP_REASON_MISSING_JD = "missing_jd"
BOOTSTRAP_REASON_MISSING_BASE_RESUME = "missing_base_resume"

DEFAULT_SECTION_LOCKS = (
    "education",
    "projects",
    "awards-and-leadership",
)
DEFAULT_EXPERIENCE_ROLE_ALLOWLIST = ("software-engineer",)
INTELLIGENCE_STATUS_NOT_STARTED = "not_started"
INTELLIGENCE_STATUS_PENDING = "pending"
STEP_7_CHECK_IDS = (
    "proof-grounding",
    "jd-coverage",
    "metric-sanity",
    "line-budget",
    "compile-page-readiness",
)

HARD_DISQUALIFIER_EXPERIENCE = "experience_gt_5_years"
HARD_DISQUALIFIER_CITIZENSHIP = "citizenship_required"
HARD_DISQUALIFIER_SECURITY_CLEARANCE = "security_clearance_required"
SOFT_FLAG_NO_SPONSORSHIP = "no_sponsorship"
MISSING_FIELD_EXPERIENCE = "experience_requirement"
MISSING_FIELD_AUTHORIZATION = "citizenship_or_clearance_requirement"

EXPERIENCE_COMPARATOR_RE = re.compile(
    r"\b(?P<operator>more than|over|at least|minimum of|minimum)\s+(?P<years>\d+)\s+"
    r"(?:years?|yrs?)\b",
    re.IGNORECASE,
)
EXPERIENCE_PLUS_RE = re.compile(r"\b(?P<years>\d+)\s*\+\s*(?:years?|yrs?)\b", re.IGNORECASE)
EXPERIENCE_RANGE_RE = re.compile(
    r"\b(?P<years>\d+)\s*(?:-|to)\s*\d+\s*(?:years?|yrs?)\b",
    re.IGNORECASE,
)
EXPERIENCE_PLAIN_RE = re.compile(r"\b(?P<years>\d+)\s*(?:years?|yrs?)\b", re.IGNORECASE)
EXPERIENCE_CONTEXT_RE = re.compile(
    r"\b(experience|experienced|professional|engineering)\b",
    re.IGNORECASE,
)
AMBIGUOUS_EXPERIENCE_RE = re.compile(
    r"\b(years?|yrs?|experience|experienced)\b",
    re.IGNORECASE,
)

HARD_REQUIREMENT_PATTERNS = (
    (
        HARD_DISQUALIFIER_CITIZENSHIP,
        re.compile(
            r"\b(?:u\.?s\.?|us)\s+citizens?(?:hip)?\b.*\b(required|must|only)\b",
            re.IGNORECASE,
        ),
    ),
    (
        HARD_DISQUALIFIER_CITIZENSHIP,
        re.compile(
            r"\bcitizens?(?:hip)?\b.*\b(required|must|only)\b",
            re.IGNORECASE,
        ),
    ),
    (
        HARD_DISQUALIFIER_SECURITY_CLEARANCE,
        re.compile(
            r"\b(?:security|secret|top secret|ts/?sci)\b.*\bclearance\b",
            re.IGNORECASE,
        ),
    ),
    (
        HARD_DISQUALIFIER_SECURITY_CLEARANCE,
        re.compile(
            r"\bclearance\b.*\b(required|requires|must|active|eligible|obtain)\b",
            re.IGNORECASE,
        ),
    ),
)

SOFT_FLAG_PATTERNS = (
    re.compile(
        r"\b(?:no|without)\s+(?:employment\s+)?(?:visa\s+)?sponsorship\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:will not|won't|cannot|can't|do not|does not)\s+"
        r"(?:provide|offer|support)\s+(?:employment\s+)?(?:visa\s+)?sponsorship\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bauthorized to work\b.*\bwithout\b.*\bsponsorship\b",
        re.IGNORECASE,
    ),
)


class ResumeTailoringError(RuntimeError):
    """Raised when resume-tailoring bootstrap cannot load required canonical state."""


@dataclass(frozen=True)
class EligibilityDecision:
    eligibility_status: str
    hard_disqualifiers_triggered: tuple[str, ...]
    soft_flags: tuple[str, ...]
    missing_data_fields: tuple[str, ...]
    decision_reason: str
    evidence_snippets: tuple[str, ...]
    recommended_note: str | None = None

    def as_payload(self) -> dict[str, Any]:
        return {
            "eligibility_status": self.eligibility_status,
            "hard_disqualifiers_triggered": list(self.hard_disqualifiers_triggered),
            "soft_flags": list(self.soft_flags),
            "missing_data_fields": list(self.missing_data_fields),
            "decision_reason": self.decision_reason,
            "evidence_snippets": list(self.evidence_snippets),
            "recommended_note": self.recommended_note,
        }


@dataclass(frozen=True)
class ResumeTailoringRunRecord:
    resume_tailoring_run_id: str
    job_posting_id: str
    base_used: str
    tailoring_status: str
    resume_review_status: str
    workspace_path: str
    meta_yaml_path: str | None
    final_resume_path: str | None
    verification_outcome: str | None
    started_at: str | None
    completed_at: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class TailoringBootstrapResult:
    job_posting_id: str
    lead_id: str
    company_name: str
    role_title: str
    posting_status: str
    eligibility: EligibilityDecision
    eligibility_artifact: PublishedArtifact
    run: ResumeTailoringRunRecord | None
    blocked_reason_code: str | None
    reused_existing_run: bool


def bootstrap_tailoring_run(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    job_posting_id: str,
    timestamp: str | None = None,
) -> TailoringBootstrapResult:
    current_time = timestamp or now_utc_iso()
    posting_row = _load_posting_row(connection, job_posting_id=job_posting_id)
    workspace_path = paths.tailoring_workspace_dir(
        posting_row["company_name"],
        posting_row["role_title"],
    )
    workspace_ref = paths.relative_to_root(workspace_path).as_posix()

    jd_path = _resolve_optional_project_path(paths, posting_row["jd_artifact_path"])
    if jd_path is None or not jd_path.exists():
        decision = EligibilityDecision(
            eligibility_status=ELIGIBILITY_STATUS_UNKNOWN,
            hard_disqualifiers_triggered=(),
            soft_flags=(),
            missing_data_fields=(MISSING_FIELD_EXPERIENCE, MISSING_FIELD_AUTHORIZATION),
            decision_reason=(
                "Resume Tailoring could not evaluate hard eligibility because the posting is "
                "missing a usable persisted `jd.md` artifact."
            ),
            evidence_snippets=(),
            recommended_note=None,
        )
        eligibility_artifact = _write_eligibility_artifact(
            connection,
            paths,
            posting_row=posting_row,
            decision=decision,
            result="blocked",
            current_time=current_time,
            workspace_ref=workspace_ref,
            base_used=None,
            active_run_id=None,
            bootstrap_ready=False,
            reason_code=BOOTSTRAP_REASON_MISSING_JD,
            message="Resume Tailoring requires a persisted `jd.md` artifact before bootstrap can begin.",
        )
        return TailoringBootstrapResult(
            job_posting_id=posting_row["job_posting_id"],
            lead_id=posting_row["lead_id"],
            company_name=posting_row["company_name"],
            role_title=posting_row["role_title"],
            posting_status=posting_row["posting_status"],
            eligibility=decision,
            eligibility_artifact=eligibility_artifact,
            run=None,
            blocked_reason_code=BOOTSTRAP_REASON_MISSING_JD,
            reused_existing_run=False,
        )

    jd_text = jd_path.read_text(encoding="utf-8")
    decision = evaluate_hard_eligibility(jd_text)
    run = None
    blocked_reason_code: str | None = None
    reused_existing_run = False
    base_used: str | None = None
    bootstrap_ready = False
    posting_status = str(posting_row["posting_status"])

    if decision.eligibility_status == ELIGIBILITY_STATUS_HARD_INELIGIBLE:
        posting_status = _set_job_posting_status(
            connection,
            job_posting_id=posting_row["job_posting_id"],
            lead_id=posting_row["lead_id"],
            previous_status=posting_status,
            new_status=JOB_POSTING_STATUS_HARD_INELIGIBLE,
            current_time=current_time,
            transition_reason="Resume Tailoring hard-eligibility gate short-circuited the posting.",
        )
    else:
        existing_run = get_latest_resume_tailoring_run_for_posting(
            connection,
            posting_row["job_posting_id"],
        )
        if existing_run is not None:
            run = existing_run
            reused_existing_run = True
            base_used = existing_run.base_used
        else:
            selected_base = _select_base_resume_track(
                paths,
                role_title=posting_row["role_title"],
                jd_text=jd_text,
            )
            if selected_base is None:
                blocked_reason_code = BOOTSTRAP_REASON_MISSING_BASE_RESUME
            else:
                base_used, base_resume_source = selected_base
                run = _create_resume_tailoring_run(
                    connection,
                    posting_row=posting_row,
                    base_used=base_used,
                    workspace_ref=workspace_ref,
                    current_time=current_time,
                )
                run = _bootstrap_tailoring_workspace(
                    connection,
                    paths,
                    posting_row=posting_row,
                    run=run,
                    jd_path=jd_path,
                    base_resume_source=base_resume_source,
                    current_time=current_time,
                    overwrite=True,
                )

        if run is not None and blocked_reason_code is None:
            _sync_tailoring_input_mirrors(
                paths,
                posting_row=posting_row,
                jd_path=jd_path,
            )
            if not _workspace_bootstrap_is_complete(paths, posting_row=posting_row, run=run):
                base_resume_source = _resolve_base_resume_source(paths, base_used=run.base_used)
                resume_tex_path = paths.tailoring_resume_tex_path(
                    posting_row["company_name"],
                    posting_row["role_title"],
                )
                if base_resume_source is None and not resume_tex_path.exists():
                    blocked_reason_code = BOOTSTRAP_REASON_MISSING_BASE_RESUME
                else:
                    run = _bootstrap_tailoring_workspace(
                        connection,
                        paths,
                        posting_row=posting_row,
                        run=run,
                        jd_path=jd_path,
                        base_resume_source=base_resume_source,
                        current_time=current_time,
                        overwrite=False,
                    )
            bootstrap_ready = _workspace_bootstrap_is_complete(
                paths,
                posting_row=posting_row,
                run=run,
            )

    eligibility_artifact = _write_eligibility_artifact(
        connection,
        paths,
        posting_row=posting_row,
        decision=decision,
        result="blocked" if blocked_reason_code is not None else "success",
        current_time=current_time,
        workspace_ref=workspace_ref,
        base_used=base_used,
        active_run_id=run.resume_tailoring_run_id if run is not None else None,
        bootstrap_ready=bootstrap_ready,
        reason_code=blocked_reason_code,
        message=(
            "Resume Tailoring bootstrap requires at least one base resume track under "
            "`assets/resume-tailoring/base/`."
            if blocked_reason_code == BOOTSTRAP_REASON_MISSING_BASE_RESUME
            else None
        ),
    )
    return TailoringBootstrapResult(
        job_posting_id=posting_row["job_posting_id"],
        lead_id=posting_row["lead_id"],
        company_name=posting_row["company_name"],
        role_title=posting_row["role_title"],
        posting_status=posting_status,
        eligibility=decision,
        eligibility_artifact=eligibility_artifact,
        run=run,
        blocked_reason_code=blocked_reason_code,
        reused_existing_run=reused_existing_run,
    )


def evaluate_hard_eligibility(jd_text: str) -> EligibilityDecision:
    hard_disqualifiers: list[str] = []
    soft_flags: list[str] = []
    evidence_snippets: list[str] = []
    explicit_signal_found = False
    ambiguous_signal_found = False
    experience_signal_found = False
    authorization_signal_found = False

    for raw_line in jd_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        normalized = line.lower()

        experience_lower_bound = _extract_experience_lower_bound(normalized)
        if experience_lower_bound is not None:
            explicit_signal_found = True
            experience_signal_found = True
            if experience_lower_bound > 5:
                _append_unique(hard_disqualifiers, HARD_DISQUALIFIER_EXPERIENCE)
                _append_unique(evidence_snippets, line)
        elif AMBIGUOUS_EXPERIENCE_RE.search(normalized):
            ambiguous_signal_found = True
            _append_unique(evidence_snippets, line)

        for hard_code, pattern in HARD_REQUIREMENT_PATTERNS:
            if not pattern.search(line):
                continue
            explicit_signal_found = True
            authorization_signal_found = True
            _append_unique(hard_disqualifiers, hard_code)
            _append_unique(evidence_snippets, line)

        for pattern in SOFT_FLAG_PATTERNS:
            if not pattern.search(line):
                continue
            explicit_signal_found = True
            authorization_signal_found = True
            _append_unique(soft_flags, SOFT_FLAG_NO_SPONSORSHIP)
            _append_unique(evidence_snippets, line)
            break

    missing_data_fields: list[str] = []
    if not experience_signal_found:
        _append_unique(missing_data_fields, MISSING_FIELD_EXPERIENCE)
    if not authorization_signal_found:
        _append_unique(missing_data_fields, MISSING_FIELD_AUTHORIZATION)

    if hard_disqualifiers:
        return EligibilityDecision(
            eligibility_status=ELIGIBILITY_STATUS_HARD_INELIGIBLE,
            hard_disqualifiers_triggered=tuple(hard_disqualifiers),
            soft_flags=tuple(soft_flags),
            missing_data_fields=tuple(missing_data_fields),
            decision_reason=(
                "JD triggered the current hard-stop policy for Resume Tailoring."
            ),
            evidence_snippets=tuple(evidence_snippets),
            recommended_note=None,
        )

    if soft_flags:
        return EligibilityDecision(
            eligibility_status=ELIGIBILITY_STATUS_SOFT_FLAG,
            hard_disqualifiers_triggered=(),
            soft_flags=tuple(soft_flags),
            missing_data_fields=tuple(missing_data_fields),
            decision_reason=(
                "JD includes a no-sponsorship constraint, so the posting remains eligible with "
                "a soft flag for downstream context."
            ),
            evidence_snippets=tuple(evidence_snippets),
            recommended_note=(
                "Mention current OPT work authorization and the no-sponsorship constraint in "
                "later operator-facing context."
            ),
        )

    if explicit_signal_found:
        return EligibilityDecision(
            eligibility_status=ELIGIBILITY_STATUS_ELIGIBLE,
            hard_disqualifiers_triggered=(),
            soft_flags=(),
            missing_data_fields=tuple(missing_data_fields),
            decision_reason=(
                "The JD includes explicit eligibility-related signals and none of them trigger "
                "the current hard-stop policy."
            ),
            evidence_snippets=tuple(evidence_snippets),
            recommended_note=None,
        )

    if ambiguous_signal_found:
        reason = (
            "The JD mentions eligibility-related requirements without an explicit hard-stop "
            "threshold, so the posting remains `unknown` and may continue."
        )
    else:
        reason = (
            "The JD does not provide explicit hard-eligibility language, so the posting remains "
            "`unknown` and may continue."
        )
    return EligibilityDecision(
        eligibility_status=ELIGIBILITY_STATUS_UNKNOWN,
        hard_disqualifiers_triggered=(),
        soft_flags=(),
        missing_data_fields=tuple(missing_data_fields),
        decision_reason=reason,
        evidence_snippets=tuple(evidence_snippets),
        recommended_note=None,
    )


def get_resume_tailoring_run(
    connection: sqlite3.Connection,
    resume_tailoring_run_id: str,
) -> ResumeTailoringRunRecord | None:
    row = connection.execute(
        """
        SELECT resume_tailoring_run_id, job_posting_id, base_used, tailoring_status,
               resume_review_status, workspace_path, meta_yaml_path, final_resume_path,
               verification_outcome, started_at, completed_at, created_at, updated_at
        FROM resume_tailoring_runs
        WHERE resume_tailoring_run_id = ?
        """,
        (resume_tailoring_run_id,),
    ).fetchone()
    return None if row is None else _resume_tailoring_run_from_row(row)


def get_latest_resume_tailoring_run_for_posting(
    connection: sqlite3.Connection,
    job_posting_id: str,
) -> ResumeTailoringRunRecord | None:
    row = connection.execute(
        """
        SELECT resume_tailoring_run_id, job_posting_id, base_used, tailoring_status,
               resume_review_status, workspace_path, meta_yaml_path, final_resume_path,
               verification_outcome, started_at, completed_at, created_at, updated_at
        FROM resume_tailoring_runs
        WHERE job_posting_id = ?
        ORDER BY created_at DESC, resume_tailoring_run_id DESC
        LIMIT 1
        """,
        (job_posting_id,),
    ).fetchone()
    return None if row is None else _resume_tailoring_run_from_row(row)


def _load_posting_row(
    connection: sqlite3.Connection,
    *,
    job_posting_id: str,
) -> sqlite3.Row:
    row = connection.execute(
        """
        SELECT job_posting_id, lead_id, company_name, role_title, posting_status, jd_artifact_path
        FROM job_postings
        WHERE job_posting_id = ?
        """,
        (job_posting_id,),
    ).fetchone()
    if row is None:
        raise ResumeTailoringError(f"Job posting `{job_posting_id}` was not found.")
    return row


def _resolve_optional_project_path(paths: ProjectPaths, artifact_path: str | None) -> Path | None:
    if artifact_path is None:
        return None
    stripped = str(artifact_path).strip()
    if not stripped:
        return None
    return paths.resolve_from_root(stripped)


def _select_base_resume_track(
    paths: ProjectPaths,
    *,
    role_title: str,
    jd_text: str,
) -> tuple[str, Path] | None:
    candidates = paths.base_resume_sources()
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0].parent.name, candidates[0]

    ranking_text = f"{role_title}\n{jd_text}".lower()
    best_source = candidates[0]
    best_score = _base_track_score(best_source, ranking_text)
    for candidate in candidates[1:]:
        candidate_score = _base_track_score(candidate, ranking_text)
        if candidate_score > best_score:
            best_source = candidate
            best_score = candidate_score
    return best_source.parent.name, best_source


def _base_track_score(base_resume_path: Path, ranking_text: str) -> int:
    track_tokens = [token for token in re.split(r"[^a-z0-9]+", base_resume_path.parent.name.lower()) if token]
    return sum(1 for token in track_tokens if token in ranking_text)


def _resolve_base_resume_source(paths: ProjectPaths, *, base_used: str) -> Path | None:
    for candidate in paths.base_resume_sources():
        if candidate.parent.name == base_used:
            return candidate
    return None


def _write_eligibility_artifact(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    posting_row: Mapping[str, Any],
    decision: EligibilityDecision,
    result: str,
    current_time: str,
    workspace_ref: str,
    base_used: str | None,
    active_run_id: str | None,
    bootstrap_ready: bool,
    reason_code: str | None = None,
    message: str | None = None,
) -> PublishedArtifact:
    eligibility_path = paths.tailoring_eligibility_path(
        posting_row["company_name"],
        posting_row["role_title"],
    )
    jd_artifact_path = posting_row["jd_artifact_path"]
    jd_ref = (
        paths.relative_to_root(jd_artifact_path).as_posix()
        if jd_artifact_path
        else None
    )
    contract = write_yaml_contract(
        eligibility_path,
        producer_component=RESUME_TAILORING_COMPONENT,
        result=result,
        linkage=ArtifactLinkage(
            lead_id=posting_row["lead_id"],
            job_posting_id=posting_row["job_posting_id"],
        ),
        payload={
            **decision.as_payload(),
            "jd_artifact_ref": jd_ref,
            "workspace_path": workspace_ref,
            "base_used": base_used,
            "active_resume_tailoring_run_id": active_run_id,
            "bootstrap_ready": bootstrap_ready,
            "bootstrap_blockers": [reason_code] if reason_code else [],
        },
        produced_at=current_time,
        reason_code=reason_code,
        message=message,
    )
    with connection:
        connection.execute(
            """
            DELETE FROM artifact_records
            WHERE artifact_type = ? AND job_posting_id = ?
            """,
            (
                TAILORING_ELIGIBILITY_ARTIFACT_TYPE,
                posting_row["job_posting_id"],
            ),
        )
        record = register_artifact_record(
            connection,
            paths,
            artifact_type=TAILORING_ELIGIBILITY_ARTIFACT_TYPE,
            artifact_path=eligibility_path,
            producer_component=RESUME_TAILORING_COMPONENT,
            linkage=ArtifactLinkage(
                lead_id=posting_row["lead_id"],
                job_posting_id=posting_row["job_posting_id"],
            ),
            created_at=contract["produced_at"],
        )
    return PublishedArtifact(
        location=artifact_location(paths, eligibility_path),
        contract=contract,
        record=record,
    )


def _create_resume_tailoring_run(
    connection: sqlite3.Connection,
    *,
    posting_row: Mapping[str, Any],
    base_used: str,
    workspace_ref: str,
    current_time: str,
) -> ResumeTailoringRunRecord:
    timestamps = lifecycle_timestamps(current_time)
    run_id = new_canonical_id("resume_tailoring_runs")
    with connection:
        connection.execute(
            """
            INSERT INTO resume_tailoring_runs (
              resume_tailoring_run_id, job_posting_id, base_used, tailoring_status,
              resume_review_status, workspace_path, meta_yaml_path, final_resume_path,
              verification_outcome, started_at, completed_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                posting_row["job_posting_id"],
                base_used,
                TAILORING_STATUS_IN_PROGRESS,
                RESUME_REVIEW_STATUS_NOT_READY,
                workspace_ref,
                None,
                None,
                None,
                current_time,
                None,
                timestamps["created_at"],
                timestamps["updated_at"],
            ),
        )
        _record_state_transition(
            connection,
            object_type="resume_tailoring_runs",
            object_id=run_id,
            stage="tailoring_status",
            previous_state="not_created",
            new_state=TAILORING_STATUS_IN_PROGRESS,
            transition_timestamp=current_time,
            transition_reason="Resume Tailoring bootstrap created the first run row for the posting.",
            lead_id=posting_row["lead_id"],
            job_posting_id=posting_row["job_posting_id"],
        )
        _record_state_transition(
            connection,
            object_type="resume_tailoring_runs",
            object_id=run_id,
            stage="resume_review_status",
            previous_state="not_created",
            new_state=RESUME_REVIEW_STATUS_NOT_READY,
            transition_timestamp=current_time,
            transition_reason="Resume Tailoring bootstrap initialized the review gate as not ready.",
            lead_id=posting_row["lead_id"],
            job_posting_id=posting_row["job_posting_id"],
        )
    created = get_resume_tailoring_run(connection, run_id)
    if created is None:
        raise ResumeTailoringError(
            f"Failed to load resume_tailoring_run `{run_id}` after creation."
        )
    return created


def _workspace_bootstrap_is_complete(
    paths: ProjectPaths,
    *,
    posting_row: Mapping[str, Any],
    run: ResumeTailoringRunRecord,
) -> bool:
    meta_path = _resolve_optional_project_path(paths, run.meta_yaml_path)
    required_paths = (
        meta_path,
        paths.tailoring_workspace_jd_path(posting_row["company_name"], posting_row["role_title"]),
        paths.tailoring_resume_tex_path(posting_row["company_name"], posting_row["role_title"]),
        paths.tailoring_scope_baseline_path(posting_row["company_name"], posting_row["role_title"]),
        paths.tailoring_intelligence_manifest_path(posting_row["company_name"], posting_row["role_title"]),
        paths.tailoring_step_3_jd_signals_path(posting_row["company_name"], posting_row["role_title"]),
        paths.tailoring_step_4_evidence_map_path(posting_row["company_name"], posting_row["role_title"]),
        paths.tailoring_step_5_context_path(posting_row["company_name"], posting_row["role_title"]),
        paths.tailoring_step_6_candidate_bullets_path(posting_row["company_name"], posting_row["role_title"]),
        paths.tailoring_step_7_verification_path(posting_row["company_name"], posting_row["role_title"]),
    )
    return all(path is not None and path.exists() for path in required_paths)


def _sync_tailoring_input_mirrors(
    paths: ProjectPaths,
    *,
    posting_row: Mapping[str, Any],
    jd_path: Path,
) -> None:
    _copy_text_file(
        paths.assets_dir / "resume-tailoring" / "profile.md",
        paths.tailoring_input_profile_path,
        overwrite=True,
    )
    _copy_text_file(
        jd_path,
        paths.tailoring_input_job_posting_path(
            posting_row["company_name"],
            posting_row["role_title"],
        ),
        overwrite=True,
    )


def _bootstrap_tailoring_workspace(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    posting_row: Mapping[str, Any],
    run: ResumeTailoringRunRecord,
    jd_path: Path,
    base_resume_source: Path | None,
    current_time: str,
    overwrite: bool,
) -> ResumeTailoringRunRecord:
    workspace_dir = paths.tailoring_workspace_dir(
        posting_row["company_name"],
        posting_row["role_title"],
    )
    resume_tex_path = paths.tailoring_resume_tex_path(
        posting_row["company_name"],
        posting_row["role_title"],
    )
    scope_baseline_path = paths.tailoring_scope_baseline_path(
        posting_row["company_name"],
        posting_row["role_title"],
    )
    workspace_dir.mkdir(parents=True, exist_ok=True)

    if overwrite or not resume_tex_path.exists():
        if base_resume_source is None:
            raise ResumeTailoringError(
                f"Base resume track `{run.base_used}` is unavailable for workspace bootstrap."
            )
        _copy_text_file(base_resume_source, resume_tex_path, overwrite=True)
    if overwrite or not scope_baseline_path.exists():
        scope_baseline_path.write_text(resume_tex_path.read_text(encoding="utf-8"), encoding="utf-8")

    _copy_text_file(
        jd_path,
        paths.tailoring_workspace_jd_path(posting_row["company_name"], posting_row["role_title"]),
        overwrite=overwrite,
    )
    _sync_optional_workspace_context(
        paths,
        posting_row=posting_row,
        overwrite=overwrite,
    )
    _write_intelligence_scaffolds(
        paths,
        posting_row=posting_row,
        run=run,
        current_time=current_time,
        overwrite=overwrite,
    )
    _publish_tailoring_meta_artifact(
        connection,
        paths,
        posting_row=posting_row,
        run=run,
        current_time=current_time,
    )
    refreshed_run = get_resume_tailoring_run(connection, run.resume_tailoring_run_id)
    if refreshed_run is None:
        raise ResumeTailoringError(
            f"Failed to reload resume_tailoring_run `{run.resume_tailoring_run_id}` after workspace bootstrap."
        )
    return refreshed_run


def _sync_optional_workspace_context(
    paths: ProjectPaths,
    *,
    posting_row: Mapping[str, Any],
    overwrite: bool,
) -> None:
    optional_sources = (
        (
            paths.lead_post_path(
                posting_row["company_name"],
                posting_row["role_title"],
                posting_row["lead_id"],
            ),
            paths.tailoring_workspace_post_path(
                posting_row["company_name"],
                posting_row["role_title"],
            ),
        ),
        (
            paths.lead_poster_profile_path(
                posting_row["company_name"],
                posting_row["role_title"],
                posting_row["lead_id"],
            ),
            paths.tailoring_workspace_poster_profile_path(
                posting_row["company_name"],
                posting_row["role_title"],
            ),
        ),
    )
    for source_path, target_path in optional_sources:
        if source_path.exists():
            _copy_text_file(source_path, target_path, overwrite=overwrite)
        elif overwrite and target_path.exists():
            target_path.unlink()


def _write_intelligence_scaffolds(
    paths: ProjectPaths,
    *,
    posting_row: Mapping[str, Any],
    run: ResumeTailoringRunRecord,
    current_time: str,
    overwrite: bool,
) -> None:
    company_name = posting_row["company_name"]
    role_title = posting_row["role_title"]
    intelligence_dir = paths.tailoring_intelligence_dir(company_name, role_title)
    prompts_dir = paths.tailoring_prompts_dir(company_name, role_title)
    intelligence_dir.mkdir(parents=True, exist_ok=True)
    prompts_dir.mkdir(parents=True, exist_ok=True)

    workspace_path = paths.tailoring_workspace_dir(company_name, role_title).resolve()
    workspace_jd_path = paths.tailoring_workspace_jd_path(company_name, role_title).resolve()
    profile_path = paths.tailoring_input_profile_path.resolve()
    job_context_path = paths.tailoring_input_job_posting_path(company_name, role_title).resolve()
    resume_tex_path = paths.tailoring_resume_tex_path(company_name, role_title).resolve()

    _write_yaml_file(
        paths.tailoring_intelligence_manifest_path(company_name, role_title),
        {
            "job_posting_id": posting_row["job_posting_id"],
            "resume_tailoring_run_id": run.resume_tailoring_run_id,
            "bootstrap_timestamp": current_time,
            "workspace_path": str(workspace_path),
            "prompts_dir": str(prompts_dir.resolve()),
            "steps": {
                "step_3_jd_signals": {
                    "status": INTELLIGENCE_STATUS_NOT_STARTED,
                    "artifact_path": str(paths.tailoring_step_3_jd_signals_path(company_name, role_title).resolve()),
                },
                "step_4_evidence_map": {
                    "status": INTELLIGENCE_STATUS_NOT_STARTED,
                    "artifact_path": str(paths.tailoring_step_4_evidence_map_path(company_name, role_title).resolve()),
                },
                "step_5_elaborated_swe_context": {
                    "status": INTELLIGENCE_STATUS_NOT_STARTED,
                    "artifact_path": str(paths.tailoring_step_5_context_path(company_name, role_title).resolve()),
                },
                "step_6_candidate_resume_edits": {
                    "status": INTELLIGENCE_STATUS_NOT_STARTED,
                    "artifact_path": str(
                        paths.tailoring_step_6_candidate_bullets_path(company_name, role_title).resolve()
                    ),
                },
                "step_7_verification": {
                    "status": INTELLIGENCE_STATUS_PENDING,
                    "artifact_path": str(paths.tailoring_step_7_verification_path(company_name, role_title).resolve()),
                },
            },
        },
        overwrite=overwrite,
    )
    _write_yaml_file(
        paths.tailoring_step_3_jd_signals_path(company_name, role_title),
        {
            "job_posting_id": posting_row["job_posting_id"],
            "resume_tailoring_run_id": run.resume_tailoring_run_id,
            "status": INTELLIGENCE_STATUS_NOT_STARTED,
            "context_file": str(workspace_jd_path),
            "signal_priority_weights": {
                "must_have": 1.00,
                "core_responsibility": 0.75,
                "nice_to_have": 0.40,
                "informational": 0.15,
            },
            "signals": [],
        },
        overwrite=overwrite,
    )
    _write_yaml_file(
        paths.tailoring_step_4_evidence_map_path(company_name, role_title),
        {
            "job_posting_id": posting_row["job_posting_id"],
            "resume_tailoring_run_id": run.resume_tailoring_run_id,
            "status": INTELLIGENCE_STATUS_NOT_STARTED,
            "profile_file": str(profile_path),
            "job_context_file": str(job_context_path),
            "resume_file": str(resume_tex_path),
            "matches": [],
            "gaps": [],
        },
        overwrite=overwrite,
    )
    _write_text_file(
        paths.tailoring_step_5_context_path(company_name, role_title),
        (
            "# Step 5 Elaborated SWE Context\n\n"
            f"- job_posting_id: {posting_row['job_posting_id']}\n"
            f"- resume_tailoring_run_id: {run.resume_tailoring_run_id}\n"
            f"- status: {INTELLIGENCE_STATUS_NOT_STARTED}\n\n"
            "## Selected Pipeline Scope\n\n"
            "Not generated yet.\n\n"
            "## Controlled Elaboration\n\n"
            "Not generated yet.\n\n"
            "## Claim Ledger\n\n"
            "Not generated yet.\n\n"
            "## Interview-Safe Narrative\n\n"
            "Not generated yet.\n"
        ),
        overwrite=overwrite,
    )
    _write_yaml_file(
        paths.tailoring_step_6_candidate_bullets_path(company_name, role_title),
        {
            "job_posting_id": posting_row["job_posting_id"],
            "resume_tailoring_run_id": run.resume_tailoring_run_id,
            "status": INTELLIGENCE_STATUS_NOT_STARTED,
            "summary": None,
            "technical_skills": [],
            "software_engineer": {
                "tech_stack_line": None,
                "bullets": [],
            },
            "support_pointers": [],
            "blockers": [],
        },
        overwrite=overwrite,
    )
    _write_yaml_file(
        paths.tailoring_step_7_verification_path(company_name, role_title),
        {
            "job_posting_id": posting_row["job_posting_id"],
            "resume_tailoring_run_id": run.resume_tailoring_run_id,
            "status": INTELLIGENCE_STATUS_PENDING,
            "verification_outcome": "pending",
            "checks": [
                {
                    "check_id": check_id,
                    "status": INTELLIGENCE_STATUS_PENDING,
                    "notes": [],
                }
                for check_id in STEP_7_CHECK_IDS
            ],
            "blockers": [],
            "revision_guidance": [],
        },
        overwrite=overwrite,
    )


def _publish_tailoring_meta_artifact(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    posting_row: Mapping[str, Any],
    run: ResumeTailoringRunRecord,
    current_time: str,
) -> PublishedArtifact:
    company_name = posting_row["company_name"]
    role_title = posting_row["role_title"]
    meta_path = paths.tailoring_meta_path(company_name, role_title)
    workspace_jd_path = paths.tailoring_workspace_jd_path(company_name, role_title).resolve()
    workspace_post_path = paths.tailoring_workspace_post_path(company_name, role_title).resolve()
    workspace_poster_profile_path = paths.tailoring_workspace_poster_profile_path(
        company_name,
        role_title,
    ).resolve()
    payload = {
        "resume_tailoring_run_id": run.resume_tailoring_run_id,
        "base_used": run.base_used,
        "context_file": str(workspace_jd_path),
        "context_files": {
            "jd": str(workspace_jd_path),
            "post": str(workspace_post_path) if workspace_post_path.exists() else None,
            "poster_profile": (
                str(workspace_poster_profile_path) if workspace_poster_profile_path.exists() else None
            ),
            "working_job_context": str(
                paths.tailoring_input_job_posting_path(company_name, role_title).resolve()
            ),
            "profile": str(paths.tailoring_input_profile_path.resolve()),
        },
        "scope_baseline_file": str(paths.tailoring_scope_baseline_path(company_name, role_title).resolve()),
        "section_locks": list(DEFAULT_SECTION_LOCKS),
        "experience_role_allowlist": list(DEFAULT_EXPERIENCE_ROLE_ALLOWLIST),
        "tailoring_status": run.tailoring_status,
        "resume_review_status": run.resume_review_status,
        "workspace_path": str(paths.tailoring_workspace_dir(company_name, role_title).resolve()),
        "resume_artifacts": {
            "tex_path": str(paths.tailoring_resume_tex_path(company_name, role_title).resolve()),
        },
        "send_linkage": {
            "outreach_mode": "role_targeted",
            "resume_required": True,
        },
    }
    with connection:
        connection.execute(
            """
            DELETE FROM artifact_records
            WHERE artifact_type = ? AND job_posting_id = ?
            """,
            (
                TAILORING_META_ARTIFACT_TYPE,
                posting_row["job_posting_id"],
            ),
        )
    artifact = publish_yaml_artifact(
        connection,
        paths,
        artifact_type=TAILORING_META_ARTIFACT_TYPE,
        artifact_path=meta_path,
        producer_component=RESUME_TAILORING_COMPONENT,
        result="success",
        linkage=ArtifactLinkage(
            lead_id=posting_row["lead_id"],
            job_posting_id=posting_row["job_posting_id"],
        ),
        payload=payload,
        produced_at=current_time,
    )
    meta_ref = paths.relative_to_root(meta_path).as_posix()
    with connection:
        connection.execute(
            """
            UPDATE resume_tailoring_runs
            SET meta_yaml_path = ?, updated_at = ?
            WHERE resume_tailoring_run_id = ?
            """,
            (
                meta_ref,
                current_time,
                run.resume_tailoring_run_id,
            ),
        )
    return artifact


def _copy_text_file(source_path: Path, target_path: Path, *, overwrite: bool) -> None:
    if not overwrite and target_path.exists():
        return
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(source_path.read_text(encoding="utf-8"), encoding="utf-8")


def _write_yaml_file(path: Path, payload: Mapping[str, Any], *, overwrite: bool) -> None:
    if not overwrite and path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(dict(payload), sort_keys=False), encoding="utf-8")


def _write_text_file(path: Path, content: str, *, overwrite: bool) -> None:
    if not overwrite and path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _set_job_posting_status(
    connection: sqlite3.Connection,
    *,
    job_posting_id: str,
    lead_id: str,
    previous_status: str,
    new_status: str,
    current_time: str,
    transition_reason: str,
) -> str:
    if previous_status == new_status:
        return new_status
    with connection:
        connection.execute(
            """
            UPDATE job_postings
            SET posting_status = ?, updated_at = ?
            WHERE job_posting_id = ?
            """,
            (
                new_status,
                current_time,
                job_posting_id,
            ),
        )
        _record_state_transition(
            connection,
            object_type="job_postings",
            object_id=job_posting_id,
            stage="posting_status",
            previous_state=previous_status,
            new_state=new_status,
            transition_timestamp=current_time,
            transition_reason=transition_reason,
            lead_id=lead_id,
            job_posting_id=job_posting_id,
        )
    return new_status


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
            RESUME_TAILORING_COMPONENT,
            lead_id,
            job_posting_id,
            None,
        ),
    )


def _extract_experience_lower_bound(line: str) -> int | None:
    if "year" not in line and "yr" not in line:
        return None
    if not EXPERIENCE_CONTEXT_RE.search(line):
        return None

    comparator_match = EXPERIENCE_COMPARATOR_RE.search(line)
    if comparator_match is not None:
        years = int(comparator_match.group("years"))
        operator = comparator_match.group("operator").lower()
        if operator in {"more than", "over"}:
            return years + 1
        return years

    plus_match = EXPERIENCE_PLUS_RE.search(line)
    if plus_match is not None:
        return int(plus_match.group("years"))

    range_match = EXPERIENCE_RANGE_RE.search(line)
    if range_match is not None:
        return int(range_match.group("years"))

    plain_match = EXPERIENCE_PLAIN_RE.search(line)
    if plain_match is not None:
        return int(plain_match.group("years"))
    return None


def _append_unique(values: list[str], candidate: str) -> None:
    if candidate not in values:
        values.append(candidate)


def _resume_tailoring_run_from_row(row: sqlite3.Row) -> ResumeTailoringRunRecord:
    tailoring_status = str(row[3])
    resume_review_status = str(row[4])
    if tailoring_status not in TAILORING_STATUSES:
        raise ResumeTailoringError(f"Unsupported tailoring_status={tailoring_status!r}.")
    if resume_review_status not in RESUME_REVIEW_STATUSES:
        raise ResumeTailoringError(
            f"Unsupported resume_review_status={resume_review_status!r}."
        )
    return ResumeTailoringRunRecord(
        resume_tailoring_run_id=row[0],
        job_posting_id=row[1],
        base_used=row[2],
        tailoring_status=tailoring_status,
        resume_review_status=resume_review_status,
        workspace_path=row[5],
        meta_yaml_path=row[6],
        final_resume_path=row[7],
        verification_outcome=row[8],
        started_at=row[9],
        completed_at=row[10],
        created_at=row[11],
        updated_at=row[12],
    )
