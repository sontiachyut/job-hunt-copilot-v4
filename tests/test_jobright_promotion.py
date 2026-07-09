from __future__ import annotations

import sqlite3
from dataclasses import replace

from job_hunt_copilot.bootstrap import run_bootstrap
from job_hunt_copilot.jobright_ingestion import (
    JOBRIGHT_BATCH_RESULT_READY,
    JobrightRecommendationBatch,
    ingest_jobright_recommendation_batch,
)
from job_hunt_copilot.jobright_promotion import (
    promote_jobright_lead,
    refresh_jobright_promotion_frontier,
)
from job_hunt_copilot.paths import ProjectPaths
from tests.support import create_minimal_project
from tests.test_jobright_ingestion import build_recommendation


def bootstrap_project(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    create_minimal_project(project_root)
    run_bootstrap(project_root=project_root)
    return project_root


def connect_database(db_path):
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    return connection


def _recommendation(
    *,
    company_name: str,
    role_title: str,
    jobright_job_id: str,
    display_score: float,
    rank_desc: str,
    extra_social_count: int = 0,
    include_personal_connections: bool = True,
    include_named_contact: bool = False,
):
    recommendation = build_recommendation(
        observed_at="2026-06-27T05:00:00Z",
        display_score=display_score,
        rank_desc=rank_desc,
        extra_social_count=extra_social_count,
        include_named_contact=include_named_contact,
    )
    recommendation = replace(
        recommendation,
        jobright_job_id=jobright_job_id,
        lead_identity_key=f"jobright:{jobright_job_id}",
        job_url=f"https://jobright.ai/jobs/info/{jobright_job_id}",
        company_name=company_name,
        role_title=role_title,
        apply_url=f"https://jobs.example.com/{jobright_job_id}",
        feed_payload={"jobId": jobright_job_id, "displayScore": display_score},
        page_payload={"fetch": {"http_status": 200}, "job_summary": {"title": role_title}},
    )
    if not include_personal_connections:
        recommendation = replace(recommendation, personal_social_connections=None)
    return recommendation


def test_promote_jobright_lead_materializes_posting_and_seeded_contacts(tmp_path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    batch = JobrightRecommendationBatch(
        ingestion_run_id="jobright-auto-20260627T050000Z",
        result=JOBRIGHT_BATCH_RESULT_READY,
        collected_at="2026-06-27T05:00:00Z",
        recommendations=(
            _recommendation(
                company_name="Acme AI",
                role_title="Applied AI Engineer",
                jobright_job_id="jobright-promote-001",
                display_score=87.2,
                rank_desc="Strong Match",
            ),
        ),
        raw_feed_payload={"jobs": [{"jobId": "jobright-promote-001"}]},
    )
    ingestion_result = ingest_jobright_recommendation_batch(project_root, batch=batch)
    lead_id = ingestion_result.lead_ids[0]

    connection = connect_database(project_root / "job_hunt_copilot.db")
    frontier = refresh_jobright_promotion_frontier(
        connection,
        paths,
        current_time="2026-06-27T05:05:00Z",
    )
    connection.close()

    assert frontier.selected_candidate is not None
    assert frontier.selected_candidate.lead_id == lead_id

    promotion_result = promote_jobright_lead(
        project_root,
        lead_id=lead_id,
        current_time="2026-06-27T05:06:00Z",
    )

    assert promotion_result.result == "promoted"
    assert promotion_result.contacts_carried_forward == 3
    assert promotion_result.job_posting_id is not None

    connection = connect_database(project_root / "job_hunt_copilot.db")
    lead_row = connection.execute(
        """
        SELECT lead_status, reason_code
        FROM leads
        WHERE lead_id = ?
        """,
        (lead_id,),
    ).fetchone()
    posting_row = connection.execute(
        """
        SELECT posting_status, promoted_from_source_observation_id, promotion_fit_score,
               promotion_personal_connection_count, promotion_total_connection_count
        FROM job_postings
        WHERE lead_id = ?
        """,
        (lead_id,),
    ).fetchone()
    posting_contact_rows = connection.execute(
        """
        SELECT contact_source_type, is_in_intended_outreach_set, lead_contact_id
        FROM job_posting_contacts
        WHERE job_posting_id = ?
        ORDER BY contact_source_priority_tier ASC, contact_source_rank ASC
        """,
        (promotion_result.job_posting_id,),
    ).fetchall()
    shadow_row = connection.execute(
        """
        SELECT source_mode, source_url
        FROM linkedin_leads
        WHERE lead_id = ?
        """,
        (lead_id,),
    ).fetchone()
    connection.close()

    assert dict(lead_row) == {
        "lead_status": "promoted",
        "reason_code": None,
    }
    assert dict(posting_row) == {
        "posting_status": "sourced",
        "promoted_from_source_observation_id": frontier.selected_candidate.active_source_observation_id,
        "promotion_fit_score": 87.2,
        "promotion_personal_connection_count": 2,
        "promotion_total_connection_count": 3,
    }
    assert {row["contact_source_type"] for row in posting_contact_rows} == {
        "jobright_personal_school",
        "jobright_personal_company",
        "jobright_public",
    }
    assert all(row["is_in_intended_outreach_set"] == 1 for row in posting_contact_rows)
    assert all(row["lead_contact_id"] for row in posting_contact_rows)
    assert dict(shadow_row) == {
        "source_mode": "jobright_recommendation",
        "source_url": "https://jobright.ai/jobs/info/jobright-promote-001",
    }
    assert paths.lead_ingestion_promotion_decision_path("Acme AI", "Applied AI Engineer", lead_id).exists()
    assert paths.lead_ingestion_jd_provenance_path("Acme AI", "Applied AI Engineer", lead_id).exists()


def test_refresh_jobright_promotion_frontier_holds_single_public_connection_lead(tmp_path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    batch = JobrightRecommendationBatch(
        ingestion_run_id="jobright-auto-20260627T051000Z",
        result=JOBRIGHT_BATCH_RESULT_READY,
        collected_at="2026-06-27T05:10:00Z",
        recommendations=(
            _recommendation(
                company_name="Solo Public",
                role_title="Applied AI Engineer",
                jobright_job_id="jobright-hold-001",
                display_score=84.0,
                rank_desc="Good Match",
                include_personal_connections=False,
            ),
        ),
        raw_feed_payload={"jobs": [{"jobId": "jobright-hold-001"}]},
    )
    ingestion_result = ingest_jobright_recommendation_batch(project_root, batch=batch)
    lead_id = ingestion_result.lead_ids[0]

    connection = connect_database(project_root / "job_hunt_copilot.db")
    frontier = refresh_jobright_promotion_frontier(
        connection,
        paths,
        current_time="2026-06-27T05:11:00Z",
    )
    lead_row = connection.execute(
        """
        SELECT lead_status, reason_code
        FROM leads
        WHERE lead_id = ?
        """,
        (lead_id,),
    ).fetchone()
    posting_count = int(connection.execute("SELECT COUNT(*) FROM job_postings").fetchone()[0] or 0)
    connection.close()

    assert frontier.selected_candidate is None
    assert dict(lead_row) == {
        "lead_status": "held",
        "reason_code": "single_public_connection_only",
    }
    assert posting_count == 0


def test_refresh_jobright_promotion_frontier_counts_named_contact_toward_non_personal_fallback(tmp_path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    batch = JobrightRecommendationBatch(
        ingestion_run_id="jobright-auto-20260627T051500Z",
        result=JOBRIGHT_BATCH_RESULT_READY,
        collected_at="2026-06-27T05:15:00Z",
        recommendations=(
            _recommendation(
                company_name="Named Contact Co",
                role_title="Applied AI Engineer",
                jobright_job_id="jobright-named-001",
                display_score=84.0,
                rank_desc="Good Match",
                include_personal_connections=False,
                include_named_contact=True,
            ),
        ),
        raw_feed_payload={"jobs": [{"jobId": "jobright-named-001"}]},
    )
    ingestion_result = ingest_jobright_recommendation_batch(project_root, batch=batch)
    lead_id = ingestion_result.lead_ids[0]

    connection = connect_database(project_root / "job_hunt_copilot.db")
    frontier = refresh_jobright_promotion_frontier(
        connection,
        paths,
        current_time="2026-06-27T05:16:00Z",
    )
    lead_row = connection.execute(
        """
        SELECT lead_status, reason_code, latest_public_connection_count, latest_total_connection_count
        FROM leads
        WHERE lead_id = ?
        """,
        (lead_id,),
    ).fetchone()
    connection.close()

    assert frontier.selected_candidate is not None
    assert frontier.selected_candidate.lead_id == lead_id
    assert dict(lead_row) == {
        "lead_status": "discovered",
        "reason_code": None,
        "latest_public_connection_count": 2,
        "latest_total_connection_count": 2,
    }


def test_refresh_jobright_promotion_frontier_prefers_personalized_connections_when_score_gap_is_small(tmp_path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    personalized = _recommendation(
        company_name="Connection First",
        role_title="Applied AI Engineer",
        jobright_job_id="jobright-rank-001",
        display_score=78.0,
        rank_desc="Good Match",
    )
    public_only = _recommendation(
        company_name="Score First",
        role_title="Applied AI Engineer",
        jobright_job_id="jobright-rank-002",
        display_score=82.0,
        rank_desc="Good Match",
        extra_social_count=1,
        include_personal_connections=False,
    )
    batch = JobrightRecommendationBatch(
        ingestion_run_id="jobright-auto-20260627T052000Z",
        result=JOBRIGHT_BATCH_RESULT_READY,
        collected_at="2026-06-27T05:20:00Z",
        recommendations=(personalized, public_only),
        raw_feed_payload={"jobs": [{"jobId": "jobright-rank-001"}, {"jobId": "jobright-rank-002"}]},
    )
    ingest_jobright_recommendation_batch(project_root, batch=batch)

    connection = connect_database(project_root / "job_hunt_copilot.db")
    frontier = refresh_jobright_promotion_frontier(
        connection,
        paths,
        current_time="2026-06-27T05:21:00Z",
    )
    connection.close()

    assert frontier.selected_candidate is not None
    assert frontier.selected_candidate.company_name == "Connection First"
    assert frontier.selected_candidate.latest_fit_score == 78.0
