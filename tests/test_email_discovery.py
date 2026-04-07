from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from job_hunt_copilot.bootstrap import run_bootstrap
from job_hunt_copilot.email_discovery import (
    ApolloResolvedCompany,
    EmailDiscoveryError,
    POSTING_CONTACT_STATUS_IDENTIFIED,
    POSTING_CONTACT_STATUS_SHORTLISTED,
    PROVIDER_NAME_APOLLO,
    RECIPIENT_TYPE_ENGINEER,
    RECIPIENT_TYPE_HIRING_MANAGER,
    RECIPIENT_TYPE_RECRUITER,
    run_apollo_people_search,
)
from job_hunt_copilot.paths import ProjectPaths
from tests.support import create_minimal_project


def bootstrap_project(tmp_path: Path) -> Path:
    project_root = tmp_path / "repo"
    project_root.mkdir()
    create_minimal_project(project_root)
    run_bootstrap(project_root=project_root)
    return project_root


def connect_database(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    return connection


def seed_search_ready_posting(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    job_posting_id: str = "jp_search",
    lead_id: str = "ld_search",
    company_name: str = "Acme Robotics",
    role_title: str = "Staff Software Engineer / AI",
    posting_status: str = "requires_contacts",
    resume_review_status: str = "approved",
    source_url: str = "https://careers.acmerobotics.com/jobs/123",
    timestamp: str = "2026-04-06T21:00:00Z",
) -> None:
    lead_workspace = paths.lead_workspace_dir(company_name, role_title, lead_id)
    jd_path = lead_workspace / "jd.md"
    jd_path.parent.mkdir(parents=True, exist_ok=True)
    jd_path.write_text(
        "We are hiring a staff software engineer focused on backend systems and AI platform work.",
        encoding="utf-8",
    )

    connection.execute(
        """
        INSERT INTO linkedin_leads (
          lead_id, lead_identity_key, lead_status, lead_shape, split_review_status,
          source_type, source_reference, source_mode, source_url, company_name, role_title,
          created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            lead_id,
            f"{company_name.lower()}|{role_title.lower()}",
            "handed_off",
            "posting_only",
            "not_applicable",
            "gmail_job_alert",
            "gmail/message/123",
            "gmail_job_alert",
            source_url,
            company_name,
            role_title,
            timestamp,
            timestamp,
        ),
    )
    connection.execute(
        """
        INSERT INTO job_postings (
          job_posting_id, lead_id, posting_identity_key, company_name, role_title,
          posting_status, jd_artifact_path, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job_posting_id,
            lead_id,
            f"{company_name.lower()}|{role_title.lower()}",
            company_name,
            role_title,
            posting_status,
            paths.relative_to_root(jd_path).as_posix(),
            timestamp,
            timestamp,
        ),
    )
    connection.execute(
        """
        INSERT INTO resume_tailoring_runs (
          resume_tailoring_run_id, job_posting_id, base_used, tailoring_status,
          resume_review_status, workspace_path, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "rtr_search",
            job_posting_id,
            "distributed-infra",
            "tailored",
            resume_review_status,
            "resume-tailoring/output/tailored/acme-robotics/staff-software-engineer-ai",
            timestamp,
            timestamp,
        ),
    )
    connection.commit()


def build_candidate(
    *,
    provider_person_id: str,
    display_name: str,
    title: str,
    has_email: bool = False,
    email: str | None = None,
    linkedin_url: str | None = None,
    last_refreshed_at: str = "2026-04-06T21:20:00Z",
) -> dict[str, object]:
    return {
        "provider_person_id": provider_person_id,
        "display_name": display_name,
        "title": title,
        "has_email": has_email,
        "email": email,
        "linkedin_url": linkedin_url,
        "has_direct_phone": False,
        "last_refreshed_at": last_refreshed_at,
    }


class FakeApolloProvider:
    def __init__(
        self,
        *,
        resolved_company: ApolloResolvedCompany | None,
        candidates: list[dict[str, object]],
    ) -> None:
        self.resolved_company = resolved_company
        self.candidates = candidates
        self.resolve_calls: list[dict[str, object | None]] = []
        self.search_calls: list[dict[str, object | None]] = []

    def resolve_company(
        self,
        *,
        company_name: str,
        company_domain: str | None,
        company_website: str | None,
    ) -> ApolloResolvedCompany | None:
        self.resolve_calls.append(
            {
                "company_name": company_name,
                "company_domain": company_domain,
                "company_website": company_website,
            }
        )
        return self.resolved_company

    def search_people(
        self,
        *,
        company_name: str,
        resolved_company: ApolloResolvedCompany | None,
        search_filters: dict[str, object],
    ) -> list[dict[str, object]]:
        self.search_calls.append(
            {
                "company_name": company_name,
                "resolved_company": resolved_company,
                "search_filters": search_filters,
            }
        )
        return list(self.candidates)


def test_apollo_people_search_persists_broad_result_and_shortlists_only_selected_candidates(tmp_path: Path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_search_ready_posting(connection, paths)

    provider = FakeApolloProvider(
        resolved_company=ApolloResolvedCompany(
            organization_id="org_acme",
            organization_name="Acme Robotics",
            primary_domain="acmerobotics.com",
            website_url="https://acmerobotics.com",
            linkedin_url="https://www.linkedin.com/company/acme-robotics",
        ),
        candidates=[
            build_candidate(provider_person_id="pp_r1", display_name="Isaiah Lo***e", title="Corporate Recruiter", has_email=True),
            build_candidate(provider_person_id="pp_r2", display_name="Priya Recruiter", title="Technical Recruiter"),
            build_candidate(provider_person_id="pp_r3", display_name="Taylor Recruiter", title="Talent Acquisition Partner"),
            build_candidate(provider_person_id="pp_m1", display_name="Morgan De***s", title="Director of Engineering"),
            build_candidate(provider_person_id="pp_m2", display_name="Avery Manager", title="Engineering Manager"),
            build_candidate(provider_person_id="pp_m3", display_name="Drew Leader", title="Head of Engineering"),
            build_candidate(provider_person_id="pp_e1", display_name="Jamie Engineer", title="Staff Software Engineer", linkedin_url="https://linkedin.example/jamie"),
            build_candidate(provider_person_id="pp_e2", display_name="Casey Engineer", title="Senior Software Engineer"),
            build_candidate(provider_person_id="pp_o1", display_name="Pat Ops", title="Program Manager"),
        ],
    )

    result = run_apollo_people_search(
        project_root=project_root,
        job_posting_id="jp_search",
        provider=provider,
    )

    assert provider.resolve_calls == [
        {
            "company_name": "Acme Robotics",
            "company_domain": "careers.acmerobotics.com",
            "company_website": "https://careers.acmerobotics.com/jobs/123",
        }
    ]
    assert provider.search_calls[0]["resolved_company"] == provider.resolved_company

    payload = json.loads(result.artifact_path.read_text(encoding="utf-8"))
    assert payload["provider_name"] == PROVIDER_NAME_APOLLO
    assert payload["resolved_company"]["organization_id"] == "org_acme"
    assert payload["search_anchor"] == "organization_id"
    assert payload["candidate_count"] == 9
    assert len(payload["shortlisted_contact_ids"]) == 6

    shortlist_candidates = [candidate for candidate in payload["candidates"] if candidate.get("contact_id")]
    shortlist_provider_ids = {candidate["provider_person_id"] for candidate in shortlist_candidates}
    assert shortlist_provider_ids == {"pp_r1", "pp_r2", "pp_m1", "pp_m2", "pp_e1", "pp_e2"}

    sparse_candidate = next(candidate for candidate in payload["candidates"] if candidate["provider_person_id"] == "pp_r1")
    assert sparse_candidate["display_name"] == "Isaiah Lo***e"
    assert sparse_candidate["full_name"] is None
    assert sparse_candidate["name_quality"] == "provider_obfuscated"

    assert connection.execute("SELECT COUNT(*) FROM contacts").fetchone()[0] == 6
    assert connection.execute("SELECT COUNT(*) FROM job_posting_contacts").fetchone()[0] == 6
    assert connection.execute(
        "SELECT COUNT(*) FROM contacts WHERE provider_person_id = 'pp_o1'"
    ).fetchone()[0] == 0

    recipient_counts = {
        row["recipient_type"]: row["count"]
        for row in connection.execute(
            """
            SELECT recipient_type, COUNT(*) AS count
            FROM job_posting_contacts
            GROUP BY recipient_type
            """
        ).fetchall()
    }
    assert recipient_counts == {
        RECIPIENT_TYPE_ENGINEER: 2,
        RECIPIENT_TYPE_HIRING_MANAGER: 2,
        RECIPIENT_TYPE_RECRUITER: 2,
    }
    assert all(
        row["link_level_status"] == POSTING_CONTACT_STATUS_SHORTLISTED
        for row in connection.execute("SELECT link_level_status FROM job_posting_contacts").fetchall()
    )

    connection.close()


@pytest.mark.parametrize(
    ("posting_status", "resume_review_status", "message_fragment"),
    [
        ("resume_review_pending", "approved", "requires_contacts"),
        ("requires_contacts", "pending", "approved tailoring review"),
    ],
)
def test_apollo_people_search_requires_approved_requires_contacts_bootstrap(
    tmp_path: Path,
    posting_status: str,
    resume_review_status: str,
    message_fragment: str,
):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_search_ready_posting(
        connection,
        paths,
        posting_status=posting_status,
        resume_review_status=resume_review_status,
    )
    provider = FakeApolloProvider(resolved_company=None, candidates=[])

    with pytest.raises(EmailDiscoveryError, match=message_fragment):
        run_apollo_people_search(
            project_root=project_root,
            job_posting_id="jp_search",
            provider=provider,
        )

    connection.close()


def test_apollo_people_search_reuses_existing_contact_and_promotes_identified_link(tmp_path: Path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_search_ready_posting(connection, paths)

    connection.execute(
        """
        INSERT INTO contacts (
          contact_id, identity_key, display_name, company_name, origin_component, contact_status,
          full_name, linkedin_url, position_title, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "ct_existing",
            "manual_poster|acme",
            "Jordan Manager",
            "Acme Robotics",
            "linkedin_scraping",
            "identified",
            "Jordan Manager",
            "https://linkedin.example/jordan",
            "Hiring Manager",
            "2026-04-06T21:00:00Z",
            "2026-04-06T21:00:00Z",
        ),
    )
    connection.execute(
        """
        INSERT INTO job_posting_contacts (
          job_posting_contact_id, job_posting_id, contact_id, recipient_type,
          relevance_reason, link_level_status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "jpc_existing",
            "jp_search",
            "ct_existing",
            RECIPIENT_TYPE_HIRING_MANAGER,
            "Seeded contact from lead evidence.",
            POSTING_CONTACT_STATUS_IDENTIFIED,
            "2026-04-06T21:00:00Z",
            "2026-04-06T21:00:00Z",
        ),
    )
    connection.commit()

    provider = FakeApolloProvider(
        resolved_company=ApolloResolvedCompany(
            organization_id="org_acme",
            organization_name="Acme Robotics",
        ),
        candidates=[
            build_candidate(
                provider_person_id="pp_jordan",
                display_name="Jordan Manager",
                title="Director of Engineering",
                linkedin_url="https://linkedin.example/jordan",
                has_email=True,
                email="jordan@acmerobotics.com",
            )
        ],
    )

    result = run_apollo_people_search(
        project_root=project_root,
        job_posting_id="jp_search",
        provider=provider,
    )

    assert result.shortlisted_contact_ids == ("ct_existing",)
    stored_contact = connection.execute(
        """
        SELECT identity_key, provider_name, provider_person_id, current_working_email
        FROM contacts
        WHERE contact_id = 'ct_existing'
        """
    ).fetchone()
    assert stored_contact["identity_key"] == "apollo_person|pp_jordan"
    assert stored_contact["provider_name"] == PROVIDER_NAME_APOLLO
    assert stored_contact["provider_person_id"] == "pp_jordan"
    assert stored_contact["current_working_email"] == "jordan@acmerobotics.com"

    stored_link = connection.execute(
        """
        SELECT recipient_type, link_level_status
        FROM job_posting_contacts
        WHERE job_posting_contact_id = 'jpc_existing'
        """
    ).fetchone()
    assert stored_link["recipient_type"] == RECIPIENT_TYPE_HIRING_MANAGER
    assert stored_link["link_level_status"] == POSTING_CONTACT_STATUS_SHORTLISTED

    transition = connection.execute(
        """
        SELECT previous_state, new_state, caused_by
        FROM state_transition_events
        WHERE object_type = 'job_posting_contacts'
          AND object_id = 'jpc_existing'
        """
    ).fetchone()
    assert transition["previous_state"] == POSTING_CONTACT_STATUS_IDENTIFIED
    assert transition["new_state"] == POSTING_CONTACT_STATUS_SHORTLISTED
    assert transition["caused_by"] == "email_discovery"

    connection.close()


def test_apollo_people_search_falls_back_to_company_name_anchor_when_resolution_fails(tmp_path: Path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_search_ready_posting(connection, paths)

    provider = FakeApolloProvider(
        resolved_company=None,
        candidates=[
            build_candidate(
                provider_person_id="pp_only",
                display_name="Taylor Recruiter",
                title="Recruiter",
            )
        ],
    )

    result = run_apollo_people_search(
        project_root=project_root,
        job_posting_id="jp_search",
        provider=provider,
    )

    payload = json.loads(result.artifact_path.read_text(encoding="utf-8"))
    assert payload["resolved_company"] is None
    assert payload["search_anchor"] == "company_name_fallback"
    assert payload["candidate_count"] == 1
    assert len(result.shortlisted_contact_ids) == 1

    connection.close()
