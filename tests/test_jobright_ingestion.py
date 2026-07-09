from __future__ import annotations

import json
import sqlite3

from job_hunt_copilot.bootstrap import run_bootstrap
from job_hunt_copilot.jobright_ingestion import (
    JOBRIGHT_BATCH_RESULT_READY,
    JobrightRecommendation,
    JobrightRecommendationBatch,
    _extract_page_payload,
    _extract_recommendation_entries,
    ingest_jobright_recommendation_batch,
)
from job_hunt_copilot.paths import ProjectPaths
from tests.support import create_minimal_project


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


def _long_jd() -> str:
    parts = [
        "About the job",
        "Build distributed backend and AI-adjacent systems that support production workflows.",
        "Design APIs, data pipelines, orchestration, and operational tooling with strong ownership.",
        "Work closely with product and engineering peers to improve reliability, observability, and developer experience.",
        "Ship Python services, infrastructure automation, and debugging workflows across real customer-facing systems.",
        "You should be comfortable reading product requirements, shaping implementation plans, and driving pragmatic execution.",
        "Experience with backend services, databases, cloud platforms, and production incident response is valuable.",
        "Clear written communication, end-to-end ownership, and bias toward shipping are all important for this role.",
    ]
    return "\n\n".join(parts)


def build_recommendation(
    *,
    observed_at: str,
    display_score: float,
    rank_desc: str,
    extra_social_count: int = 0,
    include_named_contact: bool = False,
) -> JobrightRecommendation:
    social_connections = [
        {
            "fullName": "Avery Engineer",
            "title": "Software Engineer",
            "linkedinUrl": "https://www.linkedin.com/in/avery-engineer/",
            "companyName": "Acme AI",
            "sourceRank": 1,
        }
    ]
    for index in range(extra_social_count):
        social_connections.append(
            {
                "fullName": f"Extra Person {index + 1}",
                "title": "Engineer",
                "linkedinUrl": f"https://www.linkedin.com/in/extra-person-{index + 1}/",
                "companyName": "Acme AI",
                "sourceRank": index + 2,
            }
        )
    personal_social_connections = {
        "school": [
            {
                "fullName": "Riley School",
                "title": "Engineer",
                "linkedinUrl": "https://www.linkedin.com/in/riley-school/",
                "companyName": "Acme AI",
                "sourceRank": 1,
            }
        ],
        "company": [
            {
                "fullName": "Jordan Company",
                "title": "Hiring Manager",
                "linkedinUrl": "https://www.linkedin.com/in/jordan-company/",
                "companyName": "Acme AI",
                "sourceRank": 1,
            }
        ],
    }
    jobright_named_contact = None
    if include_named_contact:
        jobright_named_contact = {
            "fullName": "Jamie Named",
            "title": None,
            "linkedinUrl": "https://www.linkedin.com/in/jamie-named/",
            "companyName": "Acme AI",
            "sourceRank": 1,
        }
    return JobrightRecommendation(
        jobright_job_id="jobright-job-001",
        lead_identity_key="jobright:jobright-job-001",
        job_url="https://jobright.ai/jobs/info/jobright-job-001",
        company_name="Acme AI",
        role_title="Backend AI Engineer",
        display_score=display_score,
        rank_desc=rank_desc,
        location="Phoenix, AZ",
        salary="$170K - $190K",
        apply_url="https://jobs.acme.ai/backend-ai-engineer",
        recommendation_scores={"Skill Match": 92},
        skill_matching_scores={"python": 0.95},
        industry_matching_scores={"ai": 0.9},
        jobright_named_contact=jobright_named_contact,
        social_connections=social_connections,
        personal_social_connections=personal_social_connections,
        jd_text=_long_jd(),
        jd_is_usable=True,
        observed_at=observed_at,
        feed_payload={"jobId": "jobright-job-001", "displayScore": display_score},
        page_payload={
            "fetch": {"http_status": 200},
            "job_summary": {"title": "Backend AI Engineer"},
            "jobright_named_contact": jobright_named_contact,
        },
    )


def test_ingest_jobright_recommendation_batch_persists_leads_observations_and_contacts(tmp_path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    batch = JobrightRecommendationBatch(
        ingestion_run_id="jobright-auto-20260627T010000Z",
        result=JOBRIGHT_BATCH_RESULT_READY,
        collected_at="2026-06-27T01:00:00Z",
        recommendations=(build_recommendation(observed_at="2026-06-27T01:00:00Z", display_score=87.2, rank_desc="Strong Match"),),
        raw_feed_payload={"jobs": [{"jobId": "jobright-job-001"}]},
    )

    result = ingest_jobright_recommendation_batch(project_root, batch=batch)

    assert result.result == JOBRIGHT_BATCH_RESULT_READY
    assert result.leads_created == 1
    assert result.leads_updated == 0
    assert result.source_observations_written == 2
    assert result.contacts_linked == 3

    connection = connect_database(project_root / "job_hunt_copilot.db")
    lead_row = connection.execute(
        """
        SELECT lead_status, source_mode, canonical_jd_artifact_path,
               latest_fit_score, latest_total_connection_count
        FROM leads
        """
    ).fetchone()
    observation_rows = connection.execute(
        """
        SELECT observation_kind, public_connection_count, personal_connection_count, jd_is_usable
        FROM lead_source_observations
        ORDER BY observation_kind ASC
        """
    ).fetchall()
    lead_contact_rows = connection.execute(
        """
        SELECT contact_source_type, contact_source_priority_tier
        FROM lead_contacts
        ORDER BY contact_source_priority_tier ASC, contact_source_rank ASC
        """
    ).fetchall()
    contact_count = int(connection.execute("SELECT COUNT(*) FROM contacts").fetchone()[0])
    connection.close()

    assert dict(lead_row) == {
        "lead_status": "discovered",
        "source_mode": "jobright_recommendation",
        "canonical_jd_artifact_path": "lead-ingestion/runtime/leads/acme-ai/backend-ai-engineer/led_"
        + result.lead_ids[0].split("led_", 1)[1]
        + "/jd.md",
        "latest_fit_score": 87.2,
        "latest_total_connection_count": 3,
    }
    assert [dict(row) for row in observation_rows] == [
        {
            "observation_kind": "job_page",
            "public_connection_count": 1,
            "personal_connection_count": 2,
            "jd_is_usable": 1,
        },
        {
            "observation_kind": "recommendation_feed",
            "public_connection_count": 0,
            "personal_connection_count": 0,
            "jd_is_usable": 0,
        },
    ]
    assert [dict(row) for row in lead_contact_rows] == [
        {
            "contact_source_type": "jobright_personal_school",
            "contact_source_priority_tier": 1,
        },
        {
            "contact_source_type": "jobright_personal_company",
            "contact_source_priority_tier": 1,
        },
        {
            "contact_source_type": "jobright_public",
            "contact_source_priority_tier": 3,
        },
    ]
    assert contact_count == 3

    lead_id = result.lead_ids[0]
    workspace_dir = paths.lead_ingestion_lead_workspace_dir("Acme AI", "Backend AI Engineer", lead_id)
    assert (workspace_dir / "jd.md").exists()
    assert (workspace_dir / "lead-manifest.yaml").exists()
    assert (workspace_dir / "source-observations.json").exists()
    assert (workspace_dir / "source-contacts.json").exists()
    assert paths.jobright_run_summary_path(batch.ingestion_run_id).exists()


def test_ingest_jobright_recommendation_batch_refreshes_existing_lead(tmp_path):
    project_root = bootstrap_project(tmp_path)
    first_batch = JobrightRecommendationBatch(
        ingestion_run_id="jobright-auto-20260627T010000Z",
        result=JOBRIGHT_BATCH_RESULT_READY,
        collected_at="2026-06-27T01:00:00Z",
        recommendations=(build_recommendation(observed_at="2026-06-27T01:00:00Z", display_score=81.0, rank_desc="Good Match"),),
        raw_feed_payload={"jobs": [{"jobId": "jobright-job-001"}]},
    )
    second_batch = JobrightRecommendationBatch(
        ingestion_run_id="jobright-auto-20260627T020000Z",
        result=JOBRIGHT_BATCH_RESULT_READY,
        collected_at="2026-06-27T02:00:00Z",
        recommendations=(
            build_recommendation(
                observed_at="2026-06-27T02:00:00Z",
                display_score=90.0,
                rank_desc="Strong Match",
                extra_social_count=1,
            ),
        ),
        raw_feed_payload={"jobs": [{"jobId": "jobright-job-001"}]},
    )

    first_result = ingest_jobright_recommendation_batch(project_root, batch=first_batch)
    second_result = ingest_jobright_recommendation_batch(project_root, batch=second_batch)

    assert first_result.leads_created == 1
    assert second_result.leads_created == 0
    assert second_result.leads_updated == 1
    assert first_result.lead_ids == second_result.lead_ids

    connection = connect_database(project_root / "job_hunt_copilot.db")
    lead_row = connection.execute(
        """
        SELECT latest_fit_score, latest_fit_label, latest_public_connection_count,
               latest_total_connection_count
        FROM leads
        WHERE lead_identity_key = 'jobright:jobright-job-001'
        """
    ).fetchone()
    observation_count = int(
        connection.execute(
            "SELECT COUNT(*) FROM lead_source_observations WHERE lead_id = ?",
            (first_result.lead_ids[0],),
        ).fetchone()[0]
    )
    contact_count = int(
        connection.execute(
            "SELECT COUNT(*) FROM contacts",
        ).fetchone()[0]
    )
    connection.close()

    assert dict(lead_row) == {
        "latest_fit_score": 90.0,
        "latest_fit_label": "Strong Match",
        "latest_public_connection_count": 2,
        "latest_total_connection_count": 4,
    }
    assert observation_count == 4
    assert contact_count == 4

    summary_payload = json.loads(
        ProjectPaths.from_root(project_root)
        .jobright_run_summary_path(second_batch.ingestion_run_id)
        .read_text(encoding="utf-8")
    )
    assert summary_payload["leads_updated"] == 1


def test_ingest_jobright_recommendation_batch_persists_jobright_named_contact_separately(tmp_path):
    project_root = bootstrap_project(tmp_path)
    batch = JobrightRecommendationBatch(
        ingestion_run_id="jobright-auto-20260627T011500Z",
        result=JOBRIGHT_BATCH_RESULT_READY,
        collected_at="2026-06-27T01:15:00Z",
        recommendations=(
            build_recommendation(
                observed_at="2026-06-27T01:15:00Z",
                display_score=87.2,
                rank_desc="Strong Match",
                include_named_contact=True,
            ),
        ),
        raw_feed_payload={"jobs": [{"jobId": "jobright-job-001"}]},
    )

    result = ingest_jobright_recommendation_batch(project_root, batch=batch)

    connection = connect_database(project_root / "job_hunt_copilot.db")
    lead_row = connection.execute(
        """
        SELECT latest_public_connection_count, latest_total_connection_count
        FROM leads
        """
    ).fetchone()
    lead_contact_rows = connection.execute(
        """
        SELECT contact_source_type, contact_source_priority_tier, contact_source_rank
        FROM lead_contacts
        ORDER BY contact_source_priority_tier ASC, contact_source_rank ASC
        """
    ).fetchall()
    connection.close()

    assert result.contacts_linked == 4
    assert dict(lead_row) == {
        "latest_public_connection_count": 2,
        "latest_total_connection_count": 4,
    }
    assert [dict(row) for row in lead_contact_rows] == [
        {
            "contact_source_type": "jobright_personal_school",
            "contact_source_priority_tier": 1,
            "contact_source_rank": 1,
        },
        {
            "contact_source_type": "jobright_personal_company",
            "contact_source_priority_tier": 1,
            "contact_source_rank": 1,
        },
        {
            "contact_source_type": "jobright_named_contact",
            "contact_source_priority_tier": 2,
            "contact_source_rank": 1,
        },
        {
            "contact_source_type": "jobright_public",
            "contact_source_priority_tier": 3,
            "contact_source_rank": 1,
        },
    ]

    lead_id = result.lead_ids[0]
    workspace_dir = ProjectPaths.from_root(project_root).lead_ingestion_lead_workspace_dir(
        "Acme AI",
        "Backend AI Engineer",
        lead_id,
    )
    page_payload = json.loads((workspace_dir / "raw" / "job-page.json").read_text(encoding="utf-8"))
    assert page_payload["jobright_named_contact"]["fullName"] == "Jamie Named"
    assert page_payload["page_payload"]["jobright_named_contact"]["fullName"] == "Jamie Named"


def test_extract_recommendation_entries_supports_live_joblist_jobresult_shape():
    payload = {
        "success": True,
        "errorCode": 10000,
        "errorMsg": None,
        "result": {
            "jobList": [
                {
                    "displayScore": 85.1104,
                    "rankDesc": "Good Match",
                    "recommendationScores": [
                        {
                            "displayName": "Experience Level",
                            "score": 0.72,
                        },
                        {
                            "displayName": "Skill Match",
                            "score": 0.9092,
                        },
                    ],
                    "jobResult": {
                        "jobId": "6a40999d1afc66714d3ca263",
                        "jobTitle": "Full Stack Engineer",
                        "jobLocation": "Vienna, VA",
                        "companyName": "TekStripes, Inc",
                        "applyLink": "https://www.linkedin.com/jobs/view/4434267242",
                        "originalUrl": "https://www.linkedin.com/jobs/view/4434267242",
                    },
                }
            ]
        },
    }

    entries = _extract_recommendation_entries(payload)

    assert entries == [
        {
            "jobright_job_id": "6a40999d1afc66714d3ca263",
            "job_url": "https://jobright.ai/jobs/info/6a40999d1afc66714d3ca263",
            "company_name": "TekStripes, Inc",
            "role_title": "Full Stack Engineer",
            "display_score": 85.1104,
            "rank_desc": "Good Match",
            "location": "Vienna, VA",
            "salary": None,
            "apply_url": "https://www.linkedin.com/jobs/view/4434267242",
            "recommendation_scores": {
                "Experience Level": 0.72,
                "Skill Match": 0.9092,
            },
            "skill_matching_scores": {},
            "industry_matching_scores": {},
            "feed_payload": payload["result"]["jobList"][0],
        }
    ]


def test_extract_page_payload_assembles_structured_jobright_sections_into_usable_jd():
    next_data = {
        "props": {
            "pageProps": {
                "dataSource": {
                    "jobResult": {
                        "jobTitle": "Software Engineer, Platform - Frisco, TX, USA",
                        "companyName": "Speechify",
                        "jobLocation": "United States",
                        "salaryDesc": "$140K/yr - $200K/yr",
                        "jobSummary": (
                            "Speechify is a company dedicated to making reading accessible through "
                            "innovative text-to-speech products. The Software Engineer, Platform "
                            "will be responsible for building and maintaining backend services, "
                            "ensuring they meet business and scalability requirements while "
                            "collaborating with cross-functional teams."
                        ),
                        "coreResponsibilities": [
                            "Design, develop, and maintain robust APIs including public TTS API, internal APIs like Payment, Subscription, Auth and Consumption Tracking, ensuring they meet business and scalability requirements",
                            "Oversee the full backend API landscape, enhancing and optimizing for performance and maintainability",
                            "Collaborate on B2B solutions, focusing on customization and integration needs for enterprise clients",
                            "Work closely with cross-functional teams to align backend architecture with overall product strategy and user experience",
                        ],
                        "qualifications": {
                            "mustHave": [
                                "Proven experience in backend development: TS/Node (required)",
                                "Direct experience with GCP and knowledge of AWS, Azure, or other cloud providers",
                                "Efficiency in ideation and implementation, prioritizing tasks based on urgency and impact",
                            ],
                            "preferredHave": [
                                "Experience with Docker and containerized deployments",
                                "Proficiency in deploying high availability applications on Kubernetes",
                            ],
                        },
                        "benefitsSummaries": [
                            "Bonus",
                            "Stock depending on experience",
                            "Autonomy, fostering focus and creativity",
                        ],
                    }
                }
            }
        }
    }
    html = (
        "<html><head><title>Speechify</title></head><body>"
        f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(next_data)}</script>'
        "</body></html>"
    )

    payload = _extract_page_payload(
        html,
        fallback_entry={
            "jobTitle": "Software Engineer, Platform - Frisco, TX, USA",
            "companyName": "Speechify",
            "location": "United States",
        },
    )

    jd_text = payload["jd_text"]
    assert payload["jd_is_usable"] is True
    assert jd_text is not None
    assert "Responsibilities" in jd_text
    assert "Qualifications" in jd_text
    assert "Benefits" in jd_text
    assert "public TTS API" in jd_text
    assert "Proficiency in deploying high availability applications on Kubernetes" in jd_text


def test_extract_page_payload_captures_jobright_named_contact_block():
    next_data = {
        "props": {
            "pageProps": {
                "dataSource": {
                    "jobResult": {
                        "jobTitle": "AI Engineer",
                        "companyName": "SoftStandard Solutions",
                        "jobLocation": "Remote",
                        "jobRecruiter": "Garima Patankar",
                        "jobRecruiterProfileUrl": "https://in.linkedin.com/in/garima-patankar-905018257?trk=feed",
                    }
                }
            }
        }
    }
    html = (
        "<html><head><title>SoftStandard</title></head><body>"
        f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(next_data)}</script>'
        "</body></html>"
    )

    payload = _extract_page_payload(
        html,
        fallback_entry={
            "jobTitle": "AI Engineer",
            "companyName": "SoftStandard Solutions",
            "location": "Remote",
        },
    )

    assert payload["jobright_named_contact"] == {
        "fullName": "Garima Patankar",
        "title": None,
        "linkedinUrl": "https://in.linkedin.com/in/garima-patankar-905018257",
        "companyName": "SoftStandard Solutions",
        "sourceRank": 1,
    }
