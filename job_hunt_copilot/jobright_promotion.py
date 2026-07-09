from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from functools import cmp_to_key
from pathlib import Path
from typing import Any

import yaml

from .artifacts import ENVELOPE_FIELDS, ArtifactLinkage, register_artifact_record, write_json_contract, write_yaml_contract
from .company_keys import derive_company_key_values
from .jobright_ingestion import (
    JOBRIGHT_LEAD_STATUS_BLOCKED_NO_JD,
    JOBRIGHT_LEAD_STATUS_DISCOVERED,
    JOBRIGHT_LEAD_STATUS_HELD,
    JOBRIGHT_LEAD_STATUS_PROMOTED,
    JOBRIGHT_SOURCE_MODE,
)
from .linkedin_scraping import (
    CONTACT_STATUS_IDENTIFIED,
    JOB_POSTING_STATUS_SOURCED,
    LEAD_SHAPE_POSTING_PLUS_CONTACTS,
    LEAD_SPLIT_REVIEW_NOT_APPLICABLE,
    LEAD_STATUS_HANDED_OFF,
    POSTING_CONTACT_STATUS_IDENTIFIED,
    _infer_recipient_type,
    _recipient_relevance_reason,
)
from .paths import ProjectPaths, workspace_slug
from .records import lifecycle_timestamps, new_canonical_id, now_utc_iso


JOBRIGHT_PROMOTION_COMPONENT = "jobright_promotion"
PROMOTION_DECISION_ARTIFACT_TYPE = "lead_promotion_decision"
JD_PROVENANCE_ARTIFACT_TYPE = "lead_jd_provenance"
PROMOTION_ACTIVE_CAP = 6

ACTIVE_PROMOTED_POSTING_STATUSES = frozenset(
    {
        "sourced",
        "tailoring_in_progress",
        "resume_review_pending",
        "requires_contacts",
        "ready_for_outreach",
        "outreach_in_progress",
    }
)
BACKLOG_PRESSURE_STATUSES = frozenset(
    {
        "sourced",
        "tailoring_in_progress",
        "resume_review_pending",
        "requires_contacts",
        "ready_for_outreach",
    }
)
OVERLY_SENIOR_TOKENS = (
    "staff ",
    "principal",
    "director",
    "head of",
    "vp ",
    "vice president",
    "chief ",
)
OFF_LANE_TITLE_TOKENS = (
    "solutions engineer",
    "solution engineer",
    "customer engineer",
    "sales engineer",
    "implementation specialist",
    "chief of staff",
    "product manager",
    "designer",
    "research scientist",
)
AI_TITLE_TOKENS = (
    "ai engineer",
    "applied ai",
    "machine learning engineer",
    "ml engineer",
    "ml infrastructure",
    "machine learning infrastructure",
    "llm",
    "forward deployed ai",
    "ai-directed",
    "model shaping",
    "genai",
)
BACKEND_TITLE_TOKENS = (
    "backend",
    "platform",
    "infrastructure",
    "distributed",
    "data engineer",
    "devops",
    "site reliability",
    "sre",
    "cloud",
)
BACKEND_JD_TOKENS = (
    "backend",
    "platform",
    "infrastructure",
    "distributed",
    "data pipeline",
    "api",
    "reliability",
    "observability",
    "cloud",
    "kubernetes",
    "aws",
)
KNOWN_INTERMEDIARY_COMPANIES = frozenset(
    {
        workspace_slug("Harnham"),
        workspace_slug("Proven Recruiting"),
        workspace_slug("Arkhya Tech"),
        workspace_slug("Stellar Consulting Solutions"),
        workspace_slug("Connect Tech+Talent"),
        workspace_slug("E-IT"),
        workspace_slug("Conexess Group"),
        workspace_slug("Collabera"),
        workspace_slug("Matlen Silver"),
        workspace_slug("Morgan McKinley"),
    }
)
INTERMEDIARY_COMPANY_TOKENS = (
    "recruiting",
    "staffing",
    "talent",
    "consulting",
    "search",
    "agency",
)
SOURCE_PRIORITY_FOR_APOLLO = {
    "jobright_personal_school": 1,
    "jobright_personal_company": 1,
    "jobright_named_contact": 2,
    "jobright_public": 3,
}


@dataclass(frozen=True)
class JobrightPromotionCandidate:
    lead_id: str
    lead_identity_key: str
    company_name: str
    role_title: str
    location: str | None
    canonical_company_key: str
    company_key_source: str
    active_source_observation_id: str
    source_url: str | None
    source_reference: str
    latest_fit_score: float | None
    latest_fit_label: str | None
    latest_public_connection_count: int
    latest_personal_connection_count: int
    latest_total_connection_count: int
    observed_at: str
    jobright_job_id: str | None
    apply_url: str | None
    jd_artifact_path: str | None
    jd_hash: str | None
    jd_is_usable: bool
    source_payload_path: str | None
    created_at: str
    updated_at: str
    lane: str | None
    connection_quality_rank: int


@dataclass(frozen=True)
class JobrightPromotionFrontier:
    selected_candidate: JobrightPromotionCandidate | None
    active_promoted_count: int
    backlog_pressure: bool
    evaluated_leads: int


@dataclass(frozen=True)
class JobrightLeadPromotionResult:
    lead_id: str
    result: str
    job_posting_id: str | None
    contacts_carried_forward: int
    selected_at: str
    reason_code: str | None = None
    message: str | None = None


def refresh_jobright_promotion_frontier(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    current_time: str,
    active_cap: int = PROMOTION_ACTIVE_CAP,
) -> JobrightPromotionFrontier:
    candidate_rows = connection.execute(
        """
        SELECT l.lead_id, l.lead_identity_key, l.lead_status, l.source_reference, l.source_url,
               l.company_name, l.role_title, l.location, l.reason_code, l.latest_fit_score,
               l.latest_fit_label, l.latest_public_connection_count,
               l.latest_personal_connection_count, l.latest_total_connection_count,
               l.created_at, l.updated_at,
               lso.source_observation_id, lso.observed_at, lso.jobright_job_id,
               lso.apply_url, lso.jd_artifact_path, lso.jd_hash, lso.jd_is_usable,
               lso.source_payload_path
        FROM leads l
        JOIN lead_source_observations lso
          ON lso.source_observation_id = l.active_source_observation_id
        WHERE l.source_mode = ?
          AND l.lead_status NOT IN (?, ?, ?)
          AND NOT EXISTS (
            SELECT 1
            FROM job_postings jp
            WHERE jp.lead_id = l.lead_id
          )
        ORDER BY l.updated_at DESC, l.created_at DESC, l.lead_id DESC
        """,
        (
            JOBRIGHT_SOURCE_MODE,
            JOBRIGHT_LEAD_STATUS_PROMOTED,
            "reauth_required",
            "closed",
        ),
    ).fetchall()
    active_company_rows = connection.execute(
        f"""
        SELECT canonical_company_key, company_name, posting_status
        FROM job_postings
        WHERE posting_status IN ({", ".join("?" for _ in ACTIVE_PROMOTED_POSTING_STATUSES)})
        """,
        tuple(sorted(ACTIVE_PROMOTED_POSTING_STATUSES)),
    ).fetchall()
    active_company_keys = {
        str(row["canonical_company_key"] or derive_company_key_values(row["company_name"])[0])
        for row in active_company_rows
    }
    active_promoted_count = len(active_company_rows)
    stalled_count = int(
        connection.execute(
            f"""
            SELECT COUNT(*)
            FROM job_postings
            WHERE posting_status IN ({", ".join("?" for _ in BACKLOG_PRESSURE_STATUSES)})
            """,
            tuple(sorted(BACKLOG_PRESSURE_STATUSES)),
        ).fetchone()[0]
        or 0
    )
    backlog_pressure = active_promoted_count >= active_cap or stalled_count >= 3

    candidates: list[JobrightPromotionCandidate] = []
    hold_updates: dict[str, tuple[str, str | None]] = {}
    for row in candidate_rows:
        candidate = _build_candidate_from_row(row, paths=paths)
        if candidate.jd_artifact_path is None or not candidate.jd_is_usable:
            hold_updates[candidate.lead_id] = (JOBRIGHT_LEAD_STATUS_BLOCKED_NO_JD, "blocked_no_jd")
            continue
        failure_reason = _promotion_failure_reason(
            candidate,
            backlog_pressure=backlog_pressure,
            active_company_keys=active_company_keys,
            paths=paths,
        )
        if failure_reason is not None:
            hold_updates[candidate.lead_id] = (
                JOBRIGHT_LEAD_STATUS_HELD,
                failure_reason,
            )
            continue
        candidates.append(candidate)

    selected_candidate: JobrightPromotionCandidate | None = None
    selected_by_company: list[JobrightPromotionCandidate] = []
    grouped: dict[str, list[JobrightPromotionCandidate]] = {}
    for candidate in candidates:
        grouped.setdefault(candidate.canonical_company_key, []).append(candidate)
    for company_candidates in grouped.values():
        ranked = sorted(company_candidates, key=cmp_to_key(_compare_candidates))
        selected = ranked[0]
        selected_by_company.append(selected)
        for loser in ranked[1:]:
            hold_updates[loser.lead_id] = (
                JOBRIGHT_LEAD_STATUS_HELD,
                "same_company_lower_fit",
            )
    if active_promoted_count < active_cap and selected_by_company:
        selected_candidate = sorted(
            selected_by_company,
            key=cmp_to_key(_compare_candidates),
        )[0]

    for row in candidate_rows:
        lead_id = str(row["lead_id"])
        if selected_candidate is not None and lead_id == selected_candidate.lead_id:
            new_status = JOBRIGHT_LEAD_STATUS_DISCOVERED
            reason_code = None
        elif lead_id in hold_updates:
            new_status, reason_code = hold_updates[lead_id]
        else:
            new_status = JOBRIGHT_LEAD_STATUS_DISCOVERED
            reason_code = "waiting_active_capacity" if active_promoted_count >= active_cap else None
        _persist_promotion_state(
            connection,
            lead_id=lead_id,
            source_observation_id=str(row["source_observation_id"]),
            lead_status=new_status,
            reason_code=reason_code,
            current_time=current_time,
        )

    return JobrightPromotionFrontier(
        selected_candidate=selected_candidate,
        active_promoted_count=active_promoted_count,
        backlog_pressure=backlog_pressure,
        evaluated_leads=len(candidate_rows),
    )


def promote_jobright_lead(
    project_root: Path | str,
    *,
    lead_id: str,
    current_time: str | None = None,
    connection: sqlite3.Connection | None = None,
) -> JobrightLeadPromotionResult:
    timestamp = current_time or now_utc_iso()
    paths = ProjectPaths.from_root(project_root)
    owns_connection = connection is None
    if connection is None:
        connection = sqlite3.connect(paths.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON;")
    try:
        with connection:
            row = connection.execute(
                """
                SELECT l.lead_id, l.lead_identity_key, l.lead_status, l.source_type,
                       l.source_reference, l.source_mode, l.source_url, l.company_name,
                       l.role_title, l.location, l.canonical_jd_artifact_path,
                       l.active_source_observation_id, l.reason_code, l.latest_fit_score,
                       l.latest_fit_label, l.latest_public_connection_count,
                       l.latest_personal_connection_count, l.latest_total_connection_count,
                       l.created_at, l.updated_at,
                       lso.observed_at, lso.jobright_job_id, lso.apply_url, lso.jd_artifact_path,
                       lso.jd_hash, lso.jd_is_usable, lso.source_payload_path
                FROM leads l
                JOIN lead_source_observations lso
                  ON lso.source_observation_id = l.active_source_observation_id
                WHERE l.lead_id = ?
                LIMIT 1
                """,
                (lead_id,),
            ).fetchone()
            if row is None:
                return JobrightLeadPromotionResult(
                    lead_id=lead_id,
                    result="missing",
                    job_posting_id=None,
                    contacts_carried_forward=0,
                    selected_at=timestamp,
                    reason_code="missing_lead",
                    message=f"Lead `{lead_id}` no longer exists.",
                )

            candidate = _build_candidate_from_row(row, paths=paths)
            if row["lead_status"] not in {JOBRIGHT_LEAD_STATUS_DISCOVERED, JOBRIGHT_LEAD_STATUS_HELD}:
                return JobrightLeadPromotionResult(
                    lead_id=lead_id,
                    result="skipped",
                    job_posting_id=None,
                    contacts_carried_forward=0,
                    selected_at=timestamp,
                    reason_code="lead_not_promotable",
                    message=f"Lead `{lead_id}` is not in a promotable state.",
                )
            if candidate.jd_artifact_path is None or not candidate.jd_is_usable:
                _persist_promotion_state(
                    connection,
                    lead_id=lead_id,
                    source_observation_id=candidate.active_source_observation_id,
                    lead_status=JOBRIGHT_LEAD_STATUS_BLOCKED_NO_JD,
                    reason_code="blocked_no_jd",
                    current_time=timestamp,
                )
                return JobrightLeadPromotionResult(
                    lead_id=lead_id,
                    result="held",
                    job_posting_id=None,
                    contacts_carried_forward=0,
                    selected_at=timestamp,
                    reason_code="blocked_no_jd",
                    message="Lead is missing a usable canonical JD.",
                )

            _ensure_legacy_linkedin_lead_shadow(connection, candidate=candidate, current_time=timestamp)
            job_posting_id = _upsert_promoted_job_posting(connection, paths, candidate=candidate, current_time=timestamp)
            carried_forward = _carry_forward_jobright_contacts(
                connection,
                lead_id=lead_id,
                job_posting_id=job_posting_id,
                current_time=timestamp,
            )
            _persist_promotion_artifacts(
                connection,
                paths,
                candidate=candidate,
                job_posting_id=job_posting_id,
                contacts_carried_forward=carried_forward,
                current_time=timestamp,
            )
            _persist_promotion_state(
                connection,
                lead_id=lead_id,
                source_observation_id=candidate.active_source_observation_id,
                lead_status=JOBRIGHT_LEAD_STATUS_PROMOTED,
                reason_code=None,
                current_time=timestamp,
            )
            _refresh_promoted_lead_manifest(
                paths,
                candidate=candidate,
                job_posting_id=job_posting_id,
                current_time=timestamp,
            )
        return JobrightLeadPromotionResult(
            lead_id=lead_id,
            result="promoted",
            job_posting_id=job_posting_id,
            contacts_carried_forward=carried_forward,
            selected_at=timestamp,
        )
    finally:
        if owns_connection:
            connection.close()


def _build_candidate_from_row(
    row: sqlite3.Row,
    *,
    paths: ProjectPaths,
) -> JobrightPromotionCandidate:
    company_name = str(row["company_name"] or "Unknown Company")
    role_title = str(row["role_title"] or "Unknown Role")
    canonical_company_key, _, company_key_source = derive_company_key_values(company_name)
    public_count = int(row["latest_public_connection_count"] or 0)
    personal_count = int(row["latest_personal_connection_count"] or 0)
    total_count = int(row["latest_total_connection_count"] or 0)
    jd_path = str(row["jd_artifact_path"] or row["canonical_jd_artifact_path"] or "").strip() or None
    lane = _classify_role_lane(role_title, paths.resolve_from_root(jd_path) if jd_path else None)
    return JobrightPromotionCandidate(
        lead_id=str(row["lead_id"]),
        lead_identity_key=str(row["lead_identity_key"]),
        company_name=company_name,
        role_title=role_title,
        location=_normalize_optional_text(row["location"]),
        canonical_company_key=canonical_company_key,
        company_key_source=company_key_source,
        active_source_observation_id=str(
            _row_value(row, "active_source_observation_id") or row["source_observation_id"]
        ),
        source_url=_normalize_optional_text(row["source_url"]),
        source_reference=str(row["source_reference"]),
        latest_fit_score=_parse_optional_float(row["latest_fit_score"]),
        latest_fit_label=_normalize_optional_text(row["latest_fit_label"]),
        latest_public_connection_count=public_count,
        latest_personal_connection_count=personal_count,
        latest_total_connection_count=total_count,
        observed_at=str(row["observed_at"]),
        jobright_job_id=_normalize_optional_text(row["jobright_job_id"]),
        apply_url=_normalize_optional_text(row["apply_url"]),
        jd_artifact_path=jd_path,
        jd_hash=_normalize_optional_text(row["jd_hash"]),
        jd_is_usable=bool(int(row["jd_is_usable"] or 0)),
        source_payload_path=_normalize_optional_text(row["source_payload_path"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        lane=lane,
        connection_quality_rank=2 if personal_count >= 1 else 1 if public_count >= 2 else 0,
    )


def _promotion_failure_reason(
    candidate: JobrightPromotionCandidate,
    *,
    backlog_pressure: bool,
    active_company_keys: set[str],
    paths: ProjectPaths,
) -> str | None:
    role_title = candidate.role_title.lower()
    company_slug = workspace_slug(candidate.company_name)
    if candidate.canonical_company_key in active_company_keys:
        return "same_company_active"
    if _looks_like_intermediary(company_slug, candidate.company_name):
        return "intermediary_excluded"
    if _is_off_lane_role(role_title):
        return "off_lane_role"
    if _is_overly_senior(role_title):
        return "overly_senior_role"
    if candidate.lane is None:
        return "off_lane_role"
    threshold = 70.0 if candidate.lane == "ai" else 80.0
    if candidate.latest_fit_score is None:
        return "missing_fit_score"
    if candidate.latest_fit_score < threshold:
        return "below_lane_threshold"
    if candidate.latest_total_connection_count == 0:
        return "blocked_no_connections"
    if candidate.latest_personal_connection_count == 0 and candidate.latest_public_connection_count == 1:
        return "single_public_connection_only"
    if candidate.connection_quality_rank == 0:
        return "blocked_connection_gate"
    if backlog_pressure and candidate.latest_personal_connection_count == 0:
        return "backlog_pressure_public_only"
    if candidate.jd_artifact_path is None:
        return "blocked_no_jd"
    jd_path = paths.resolve_from_root(candidate.jd_artifact_path)
    if not jd_path.exists():
        return "blocked_no_jd"
    return None


def _classify_role_lane(role_title: str, jd_path: Path | None) -> str | None:
    title = role_title.lower()
    if _is_off_lane_role(title):
        return None
    if any(token in title for token in AI_TITLE_TOKENS):
        return "ai"
    if any(token in title for token in BACKEND_TITLE_TOKENS):
        return "backend"
    if "software engineer" in title or "engineer" in title:
        jd_text = ""
        if jd_path is not None and jd_path.exists():
            try:
                jd_text = jd_path.read_text(encoding="utf-8").lower()
            except OSError:
                jd_text = ""
        if any(token in jd_text for token in BACKEND_JD_TOKENS):
            return "backend"
        if any(token in jd_text for token in ("machine learning", "ai ", " llm", "model ")):
            return "ai"
    return None


def _is_off_lane_role(role_title: str) -> bool:
    return any(token in role_title for token in OFF_LANE_TITLE_TOKENS)


def _is_overly_senior(role_title: str) -> bool:
    normalized = f"{role_title} "
    return any(token in normalized for token in OVERLY_SENIOR_TOKENS)


def _looks_like_intermediary(company_slug: str, company_name: str) -> bool:
    if company_slug in KNOWN_INTERMEDIARY_COMPANIES:
        return True
    normalized = company_name.lower()
    return any(token in normalized for token in INTERMEDIARY_COMPANY_TOKENS)


def _compare_candidates(left: JobrightPromotionCandidate, right: JobrightPromotionCandidate) -> int:
    left_score = left.latest_fit_score if left.latest_fit_score is not None else -1.0
    right_score = right.latest_fit_score if right.latest_fit_score is not None else -1.0
    if abs(left_score - right_score) <= 5.0 and left.connection_quality_rank != right.connection_quality_rank:
        return -1 if left.connection_quality_rank > right.connection_quality_rank else 1
    if left_score != right_score:
        return -1 if left_score > right_score else 1
    if left.connection_quality_rank != right.connection_quality_rank:
        return -1 if left.connection_quality_rank > right.connection_quality_rank else 1
    if left.latest_total_connection_count != right.latest_total_connection_count:
        return -1 if left.latest_total_connection_count > right.latest_total_connection_count else 1
    if left.observed_at != right.observed_at:
        return -1 if left.observed_at > right.observed_at else 1
    if left.company_name != right.company_name:
        return -1 if left.company_name < right.company_name else 1
    if left.role_title != right.role_title:
        return -1 if left.role_title < right.role_title else 1
    if left.lead_id == right.lead_id:
        return 0
    return -1 if left.lead_id < right.lead_id else 1


def _persist_promotion_state(
    connection: sqlite3.Connection,
    *,
    lead_id: str,
    source_observation_id: str,
    lead_status: str,
    reason_code: str | None,
    current_time: str,
) -> None:
    connection.execute(
        """
        UPDATE leads
        SET lead_status = ?,
            reason_code = ?,
            updated_at = ?
        WHERE lead_id = ?
        """,
        (
            lead_status,
            reason_code,
            current_time,
            lead_id,
        ),
    )
    connection.execute(
        """
        UPDATE lead_source_observations
        SET promotion_eligibility_status = ?,
            promotion_hold_reason = ?,
            updated_at = ?
        WHERE source_observation_id = ?
        """,
        (
            lead_status,
            reason_code,
            current_time,
            source_observation_id,
        ),
    )


def _ensure_legacy_linkedin_lead_shadow(
    connection: sqlite3.Connection,
    *,
    candidate: JobrightPromotionCandidate,
    current_time: str,
) -> None:
    existing = connection.execute(
        """
        SELECT lead_id
        FROM linkedin_leads
        WHERE lead_id = ?
        LIMIT 1
        """,
        (candidate.lead_id,),
    ).fetchone()
    if existing is None:
        connection.execute(
            """
            INSERT INTO linkedin_leads (
              lead_id, lead_identity_key, lead_status, lead_shape, split_review_status,
              source_type, source_reference, source_mode, source_url, company_name,
              role_title, location, work_mode, compensation_summary, poster_name,
              poster_title, last_scraped_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                candidate.lead_id,
                candidate.lead_identity_key,
                LEAD_STATUS_HANDED_OFF,
                LEAD_SHAPE_POSTING_PLUS_CONTACTS,
                LEAD_SPLIT_REVIEW_NOT_APPLICABLE,
                "jobright_recommendation",
                candidate.source_reference,
                JOBRIGHT_SOURCE_MODE,
                candidate.source_url,
                candidate.company_name,
                candidate.role_title,
                candidate.location,
                None,
                None,
                None,
                None,
                candidate.observed_at,
                candidate.created_at,
                current_time,
            ),
        )
        return
    connection.execute(
        """
        UPDATE linkedin_leads
        SET lead_identity_key = ?,
            lead_status = ?,
            lead_shape = ?,
            split_review_status = ?,
            source_type = ?,
            source_reference = ?,
            source_mode = ?,
            source_url = ?,
            company_name = ?,
            role_title = ?,
            location = ?,
            last_scraped_at = ?,
            updated_at = ?
        WHERE lead_id = ?
        """,
        (
            candidate.lead_identity_key,
            LEAD_STATUS_HANDED_OFF,
            LEAD_SHAPE_POSTING_PLUS_CONTACTS,
            LEAD_SPLIT_REVIEW_NOT_APPLICABLE,
            "jobright_recommendation",
            candidate.source_reference,
            JOBRIGHT_SOURCE_MODE,
            candidate.source_url,
            candidate.company_name,
            candidate.role_title,
            candidate.location,
            candidate.observed_at,
            current_time,
            candidate.lead_id,
        ),
    )


def _upsert_promoted_job_posting(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    candidate: JobrightPromotionCandidate,
    current_time: str,
) -> str:
    jd_path = paths.resolve_from_root(candidate.jd_artifact_path) if candidate.jd_artifact_path else None
    if jd_path is None or not jd_path.exists():
        raise ValueError(f"Promoted lead `{candidate.lead_id}` is missing its canonical JD.")
    posting_identity_key = _build_posting_identity_key(candidate, jd_path=jd_path)
    existing = connection.execute(
        """
        SELECT job_posting_id
        FROM job_postings
        WHERE lead_id = ?
        LIMIT 1
        """,
        (candidate.lead_id,),
    ).fetchone()
    application_url_column = _has_job_postings_column(connection, "application_url")
    if existing is None:
        job_posting_id = new_canonical_id("job_postings")
        canonical_company_key, provider_company_key, company_key_source = derive_company_key_values(candidate.company_name)
        insert_columns = [
            "job_posting_id",
            "lead_id",
            "posting_identity_key",
            "canonical_company_key",
            "provider_company_key",
            "company_name",
            "role_title",
            "posting_status",
            "company_key_source",
            "location",
            "employment_type",
            "posted_at",
            "jd_artifact_path",
            "archived_at",
            "created_at",
            "updated_at",
            "promoted_from_source_observation_id",
            "promotion_fit_score",
            "promotion_fit_label",
            "promotion_public_connection_count",
            "promotion_personal_connection_count",
            "promotion_total_connection_count",
        ]
        insert_values: list[Any] = [
            job_posting_id,
            candidate.lead_id,
            posting_identity_key,
            canonical_company_key,
            provider_company_key,
            candidate.company_name,
            candidate.role_title,
            JOB_POSTING_STATUS_SOURCED,
            company_key_source,
            candidate.location,
            None,
            None,
            candidate.jd_artifact_path,
            None,
            current_time,
            current_time,
            candidate.active_source_observation_id,
            candidate.latest_fit_score,
            candidate.latest_fit_label,
            candidate.latest_public_connection_count,
            candidate.latest_personal_connection_count,
            candidate.latest_total_connection_count,
        ]
        if application_url_column:
            insert_columns.insert(13, "application_url")
            insert_values.insert(13, candidate.apply_url)
        connection.execute(
            f"""
            INSERT INTO job_postings (
              {", ".join(insert_columns)}
            ) VALUES ({", ".join("?" for _ in insert_columns)})
            """,
            tuple(insert_values),
        )
        return job_posting_id

    job_posting_id = str(existing["job_posting_id"])
    update_sql = """
        UPDATE job_postings
        SET posting_identity_key = ?,
            company_name = ?,
            role_title = ?,
            posting_status = ?,
            location = ?,
            jd_artifact_path = ?,
            canonical_company_key = ?,
            provider_company_key = ?,
            company_key_source = ?,
            promoted_from_source_observation_id = ?,
            promotion_fit_score = ?,
            promotion_fit_label = ?,
            promotion_public_connection_count = ?,
            promotion_personal_connection_count = ?,
            promotion_total_connection_count = ?,
            updated_at = ?
    """
    params: list[Any] = [
        posting_identity_key,
        candidate.company_name,
        candidate.role_title,
        JOB_POSTING_STATUS_SOURCED,
        candidate.location,
        candidate.jd_artifact_path,
        candidate.canonical_company_key,
        None,
        candidate.company_key_source,
        candidate.active_source_observation_id,
        candidate.latest_fit_score,
        candidate.latest_fit_label,
        candidate.latest_public_connection_count,
        candidate.latest_personal_connection_count,
        candidate.latest_total_connection_count,
        current_time,
    ]
    if application_url_column:
        update_sql += ", application_url = ?"
        params.append(candidate.apply_url)
    update_sql += " WHERE job_posting_id = ?"
    params.append(job_posting_id)
    connection.execute(update_sql, tuple(params))
    return job_posting_id


def _carry_forward_jobright_contacts(
    connection: sqlite3.Connection,
    *,
    lead_id: str,
    job_posting_id: str,
    current_time: str,
) -> int:
    rows = connection.execute(
        """
        SELECT lc.lead_contact_id, lc.contact_id, lc.contact_source_type,
               lc.contact_source_priority_tier, lc.contact_source_rank,
               c.position_title
        FROM lead_contacts lc
        JOIN contacts c
          ON c.contact_id = lc.contact_id
        WHERE lc.lead_id = ?
          AND lc.removed_at IS NULL
        ORDER BY lc.contact_source_priority_tier ASC,
                 lc.contact_source_rank ASC,
                 lc.created_at ASC
        """,
        (lead_id,),
    ).fetchall()
    carried = 0
    for row in rows:
        recipient_type = _infer_recipient_type(_normalize_optional_text(row["position_title"]))
        relevance_reason = _recipient_relevance_reason(
            recipient_type=recipient_type,
            position_title=_normalize_optional_text(row["position_title"]),
        )
        existing = connection.execute(
            """
            SELECT job_posting_contact_id
            FROM job_posting_contacts
            WHERE job_posting_id = ?
              AND contact_id = ?
            LIMIT 1
            """,
            (job_posting_id, row["contact_id"]),
        ).fetchone()
        if existing is None:
            job_posting_contact_id = new_canonical_id("job_posting_contacts")
            timestamps = lifecycle_timestamps(current_time)
            connection.execute(
                """
                INSERT INTO job_posting_contacts (
                  job_posting_contact_id, job_posting_id, contact_id, recipient_type,
                  relevance_reason, link_level_status, lead_contact_id,
                  contact_source_type, contact_source_priority_tier,
                  contact_source_rank, is_in_intended_outreach_set,
                  entered_intended_outreach_set_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_posting_contact_id,
                    job_posting_id,
                    row["contact_id"],
                    recipient_type,
                    relevance_reason,
                    POSTING_CONTACT_STATUS_IDENTIFIED,
                    row["lead_contact_id"],
                    row["contact_source_type"],
                    row["contact_source_priority_tier"],
                    row["contact_source_rank"],
                    1,
                    current_time,
                    timestamps["created_at"],
                    timestamps["updated_at"],
                ),
            )
        else:
            connection.execute(
                """
                UPDATE job_posting_contacts
                SET recipient_type = ?,
                    relevance_reason = ?,
                    link_level_status = ?,
                    lead_contact_id = ?,
                    contact_source_type = ?,
                    contact_source_priority_tier = ?,
                    contact_source_rank = ?,
                    is_in_intended_outreach_set = 1,
                    entered_intended_outreach_set_at = COALESCE(entered_intended_outreach_set_at, ?),
                    removed_from_intended_outreach_set_at = NULL,
                    intended_outreach_set_removal_reason = NULL,
                    updated_at = ?
                WHERE job_posting_id = ?
                  AND contact_id = ?
                """,
                (
                    recipient_type,
                    relevance_reason,
                    POSTING_CONTACT_STATUS_IDENTIFIED,
                    row["lead_contact_id"],
                    row["contact_source_type"],
                    row["contact_source_priority_tier"],
                    row["contact_source_rank"],
                    current_time,
                    current_time,
                    job_posting_id,
                    row["contact_id"],
                ),
            )
        connection.execute(
            """
            UPDATE lead_contacts
            SET is_initial_intended_contact = 1,
                updated_at = ?
            WHERE lead_contact_id = ?
            """,
            (
                current_time,
                row["lead_contact_id"],
            ),
        )
        carried += 1
    return carried


def _persist_promotion_artifacts(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    candidate: JobrightPromotionCandidate,
    job_posting_id: str,
    contacts_carried_forward: int,
    current_time: str,
) -> None:
    promotion_path = paths.lead_ingestion_promotion_decision_path(
        candidate.company_name,
        candidate.role_title,
        candidate.lead_id,
    )
    provenance_path = paths.lead_ingestion_jd_provenance_path(
        candidate.company_name,
        candidate.role_title,
        candidate.lead_id,
    )
    promotion_contract = write_json_contract(
        promotion_path,
        producer_component=JOBRIGHT_PROMOTION_COMPONENT,
        result="success",
        linkage=ArtifactLinkage(lead_id=candidate.lead_id, job_posting_id=job_posting_id),
        payload={
            "promotion_result": "promoted",
            "lead_status_after_promotion": JOBRIGHT_LEAD_STATUS_PROMOTED,
            "source_observation_id": candidate.active_source_observation_id,
            "display_score": candidate.latest_fit_score,
            "rank_desc": candidate.latest_fit_label,
            "lane": candidate.lane,
            "connection_summary": {
                "public_count": candidate.latest_public_connection_count,
                "personal_count": candidate.latest_personal_connection_count,
                "total_count": candidate.latest_total_connection_count,
            },
            "contacts_carried_forward": contacts_carried_forward,
        },
        produced_at=current_time,
    )
    provenance_contract = write_json_contract(
        provenance_path,
        producer_component=JOBRIGHT_PROMOTION_COMPONENT,
        result="success",
        linkage=ArtifactLinkage(lead_id=candidate.lead_id, job_posting_id=job_posting_id),
        payload={
            "source_observation_id": candidate.active_source_observation_id,
            "jobright_job_id": candidate.jobright_job_id,
            "source_url": candidate.source_url,
            "apply_url": candidate.apply_url,
            "source_payload_path": candidate.source_payload_path,
            "jd_artifact_path": candidate.jd_artifact_path,
            "jd_hash": candidate.jd_hash,
        },
        produced_at=current_time,
    )
    _replace_artifact_record(
        connection,
        paths,
        artifact_type=PROMOTION_DECISION_ARTIFACT_TYPE,
        artifact_path=promotion_path,
        lead_id=candidate.lead_id,
        job_posting_id=job_posting_id,
        created_at=promotion_contract["produced_at"],
    )
    _replace_artifact_record(
        connection,
        paths,
        artifact_type=JD_PROVENANCE_ARTIFACT_TYPE,
        artifact_path=provenance_path,
        lead_id=candidate.lead_id,
        job_posting_id=job_posting_id,
        created_at=provenance_contract["produced_at"],
    )


def _refresh_promoted_lead_manifest(
    paths: ProjectPaths,
    *,
    candidate: JobrightPromotionCandidate,
    job_posting_id: str,
    current_time: str,
) -> None:
    lead_manifest_path = paths.lead_ingestion_lead_manifest_path(
        candidate.company_name,
        candidate.role_title,
        candidate.lead_id,
    )
    existing_payload: dict[str, Any] = {}
    if lead_manifest_path.exists():
        loaded = yaml.safe_load(lead_manifest_path.read_text(encoding="utf-8")) or {}
        if isinstance(loaded, dict):
            existing_payload = {
                key: value
                for key, value in loaded.items()
                if key not in ENVELOPE_FIELDS
            }
    existing_payload.update(
        {
            "lead_status": JOBRIGHT_LEAD_STATUS_PROMOTED,
            "active_source_observation_id": candidate.active_source_observation_id,
            "lead_status_reason_code": None,
            "created_entities": {
                "job_posting_id": job_posting_id,
            },
            "handoff_targets": {
                "posting_materialization": {
                    "ready": True,
                    "reason_code": None,
                    "created_entities": {"job_posting_id": job_posting_id},
                    "required_artifacts": [paths.resolve_from_root(candidate.jd_artifact_path).as_posix()]
                    if candidate.jd_artifact_path
                    else [],
                },
                "resume_tailoring": {
                    "ready": True,
                    "reason_code": None,
                    "created_entities": {"job_posting_id": job_posting_id},
                    "required_artifacts": [paths.resolve_from_root(candidate.jd_artifact_path).as_posix()]
                    if candidate.jd_artifact_path
                    else [],
                },
            },
        }
    )
    artifacts = dict(existing_payload.get("artifacts") or {})
    artifacts["promotion_decision_path"] = paths.relative_to_root(
        paths.lead_ingestion_promotion_decision_path(
            candidate.company_name,
            candidate.role_title,
            candidate.lead_id,
        )
    ).as_posix()
    artifacts["jd_provenance_path"] = paths.relative_to_root(
        paths.lead_ingestion_jd_provenance_path(
            candidate.company_name,
            candidate.role_title,
            candidate.lead_id,
        )
    ).as_posix()
    existing_payload["artifacts"] = artifacts
    write_yaml_contract(
        lead_manifest_path,
        producer_component=JOBRIGHT_PROMOTION_COMPONENT,
        result="success",
        linkage=ArtifactLinkage(lead_id=candidate.lead_id, job_posting_id=job_posting_id),
        payload=existing_payload,
        produced_at=current_time,
    )


def _replace_artifact_record(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    artifact_type: str,
    artifact_path: Path,
    lead_id: str,
    job_posting_id: str,
    created_at: str,
) -> None:
    connection.execute(
        """
        DELETE FROM artifact_records
        WHERE artifact_type = ?
          AND lead_id = ?
        """,
        (artifact_type, lead_id),
    )
    register_artifact_record(
        connection,
        paths,
        artifact_type=artifact_type,
        artifact_path=artifact_path,
        producer_component=JOBRIGHT_PROMOTION_COMPONENT,
        linkage=ArtifactLinkage(lead_id=lead_id, job_posting_id=job_posting_id),
        created_at=created_at,
    )


def _build_posting_identity_key(
    candidate: JobrightPromotionCandidate,
    *,
    jd_path: Path,
) -> str:
    normalized_jd = " ".join(jd_path.read_text(encoding="utf-8").split())
    if candidate.jd_hash:
        jd_fingerprint = candidate.jd_hash[:16]
    else:
        import hashlib

        jd_fingerprint = hashlib.sha256(normalized_jd.encode("utf-8")).hexdigest()[:16]
    return "|".join(
        [
            "jobright_lead",
            workspace_slug(candidate.company_name),
            workspace_slug(candidate.role_title),
            workspace_slug(candidate.location or "unknown-location"),
            workspace_slug(candidate.jobright_job_id or candidate.lead_identity_key),
            jd_fingerprint,
        ]
    )


def _has_job_postings_column(connection: sqlite3.Connection, column_name: str) -> bool:
    rows = connection.execute("PRAGMA table_info(job_postings)").fetchall()
    return any(str(row[1]) == column_name for row in rows)


def _parse_optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _row_value(row: sqlite3.Row, key: str) -> Any:
    try:
        return row[key]
    except (IndexError, KeyError):
        return None
