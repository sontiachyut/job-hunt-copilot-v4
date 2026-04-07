from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from job_hunt_copilot.bootstrap import run_bootstrap
from job_hunt_copilot.email_discovery import (
    ApolloResolvedCompany,
    CONTACT_STATUS_WORKING_EMAIL_FOUND,
    EmailDiscoveryError,
    POSTING_CONTACT_STATUS_IDENTIFIED,
    POSTING_CONTACT_STATUS_SHORTLISTED,
    PROVIDER_NAME_APOLLO,
    RECIPIENT_TYPE_ENGINEER,
    RECIPIENT_TYPE_HIRING_MANAGER,
    RECIPIENT_TYPE_RECRUITER,
    run_apollo_contact_enrichment,
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


class FakeApolloEnrichmentProvider:
    def __init__(self, responses: dict[str, dict[str, object] | None]) -> None:
        self.responses = responses
        self.calls: list[dict[str, str | None]] = []

    def enrich_person(
        self,
        *,
        provider_person_id: str | None,
        linkedin_url: str | None,
        person_name: str | None,
        company_domain: str | None,
        company_name: str | None,
    ) -> dict[str, object] | None:
        self.calls.append(
            {
                "provider_person_id": provider_person_id,
                "linkedin_url": linkedin_url,
                "person_name": person_name,
                "company_domain": company_domain,
                "company_name": company_name,
            }
        )
        lookup_key = provider_person_id or linkedin_url or person_name or "unknown"
        return self.responses.get(lookup_key)


class FakeRecipientProfileExtractor:
    def __init__(self, responses: dict[str, dict[str, object] | None]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def extract_profile(
        self,
        *,
        linkedin_url: str,
        contact: dict[str, object],
        posting: dict[str, object],
    ) -> dict[str, object] | None:
        self.calls.append(linkedin_url)
        return self.responses.get(linkedin_url)


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


def test_apollo_contact_enrichment_only_runs_for_shortlisted_contacts_and_persists_recipient_profiles(tmp_path: Path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_search_ready_posting(connection, paths)

    search_provider = FakeApolloProvider(
        resolved_company=ApolloResolvedCompany(
            organization_id="org_acme",
            organization_name="Acme Robotics",
            primary_domain="acmerobotics.com",
        ),
        candidates=[
            build_candidate(provider_person_id="pp_r1", display_name="Isaiah Lo***e", title="Corporate Recruiter"),
            build_candidate(
                provider_person_id="pp_r2",
                display_name="Priya Recruiter",
                title="Technical Recruiter",
                has_email=True,
                email="priya@acmerobotics.com",
                linkedin_url="https://linkedin.example/priya",
            ),
            build_candidate(provider_person_id="pp_m1", display_name="Morgan Manager", title="Engineering Manager"),
            build_candidate(
                provider_person_id="pp_m2",
                display_name="Avery Director",
                title="Director of Engineering",
                has_email=True,
                email="avery@acmerobotics.com",
                linkedin_url="https://linkedin.example/avery",
            ),
            build_candidate(
                provider_person_id="pp_e1",
                display_name="Jamie Engineer",
                title="Staff Software Engineer",
                has_email=True,
                email="jamie@acmerobotics.com",
                linkedin_url="https://linkedin.example/jamie",
            ),
            build_candidate(
                provider_person_id="pp_e2",
                display_name="Casey Engineer",
                title="Senior Software Engineer",
                has_email=True,
                email="casey@acmerobotics.com",
                linkedin_url="https://linkedin.example/casey",
            ),
            build_candidate(provider_person_id="pp_o1", display_name="Pat Ops", title="Program Manager"),
        ],
    )
    run_apollo_people_search(
        project_root=project_root,
        job_posting_id="jp_search",
        provider=search_provider,
    )

    enrichment_provider = FakeApolloEnrichmentProvider(
        {
            "pp_r1": {
                "person": {
                    "id": "pp_r1",
                    "first_name": "Isaiah",
                    "last_name": "Love",
                    "name": "Isaiah Love",
                    "linkedin_url": "https://linkedin.example/isaiah",
                    "title": "Corporate Recruiter",
                    "email": "isaiah@acmerobotics.com",
                    "email_status": "verified",
                    "organization_id": "org_acme",
                    "organization_name": "Acme Robotics",
                    "city": "Phoenix",
                    "state": "Arizona",
                    "country": "United States",
                    "headline": "Corporate Recruiter at Acme Robotics",
                }
            },
            "pp_m1": None,
        }
    )
    profile_extractor = FakeRecipientProfileExtractor(
        {
            "https://linkedin.example/isaiah": {
                "profile_source": "linkedin_public_profile",
                "source_method": "public_profile_html",
                "profile": {
                    "identity": {
                        "display_name": "Isaiah Love",
                        "full_name": "Isaiah Love",
                        "first_name": "Isaiah",
                        "last_name": "Love",
                    },
                    "top_card": {
                        "current_company": "Acme Robotics",
                        "current_title": "Corporate Recruiter",
                        "headline": "Corporate Recruiter at Acme Robotics",
                        "location": "Phoenix, Arizona, United States",
                        "connections": "500+",
                        "followers": "120",
                    },
                    "about": {"preview_text": "Helps hire strong backend and AI talent.", "is_truncated": False},
                    "experience_hints": {
                        "current_company_hint": "Acme Robotics",
                        "education_hint": None,
                        "experience_education_preview": "Acme Robotics recruiting leader",
                    },
                    "recent_public_activity": [],
                    "public_signals": {
                        "licenses_and_certifications": [],
                        "honors_and_awards": [],
                        "recommendation_entities": [],
                    },
                    "work_signals": ["recruiting function close to the target role"],
                    "evidence_snippets": ["Current company hint: Acme Robotics"],
                    "source_coverage": {
                        "about": True,
                        "activity": False,
                        "experience_hint": True,
                        "public_signals": False,
                    },
                },
            },
            "https://linkedin.example/priya": {
                "profile_source": "linkedin_public_profile",
                "source_method": "public_profile_html",
                "profile": {
                    "identity": {
                        "display_name": "Priya Recruiter",
                        "full_name": "Priya Recruiter",
                        "first_name": "Priya",
                        "last_name": "Recruiter",
                    },
                    "top_card": {
                        "current_company": "Acme Robotics",
                        "current_title": "Technical Recruiter",
                        "headline": None,
                        "location": None,
                        "connections": None,
                        "followers": None,
                    },
                    "about": {"preview_text": None, "is_truncated": False},
                    "experience_hints": {
                        "current_company_hint": "Acme Robotics",
                        "education_hint": None,
                        "experience_education_preview": None,
                    },
                    "recent_public_activity": [],
                    "public_signals": {
                        "licenses_and_certifications": [],
                        "honors_and_awards": [],
                        "recommendation_entities": [],
                    },
                    "work_signals": ["recruiting function close to the target role"],
                    "evidence_snippets": ["Current company hint: Acme Robotics"],
                    "source_coverage": {
                        "about": False,
                        "activity": False,
                        "experience_hint": True,
                        "public_signals": False,
                    },
                },
            },
        }
    )

    result = run_apollo_contact_enrichment(
        project_root=project_root,
        job_posting_id="jp_search",
        provider=enrichment_provider,
        recipient_profile_extractor=profile_extractor,
    )

    assert set(call["provider_person_id"] for call in enrichment_provider.calls) == {"pp_r1", "pp_m1"}
    assert all(call["provider_person_id"] != "pp_o1" for call in enrichment_provider.calls)

    isaiah_row = connection.execute(
        """
        SELECT full_name, linkedin_url, current_working_email, contact_status
        FROM contacts
        WHERE provider_person_id = 'pp_r1'
        """
    ).fetchone()
    assert dict(isaiah_row) == {
        "full_name": "Isaiah Love",
        "linkedin_url": "https://linkedin.example/isaiah",
        "current_working_email": "isaiah@acmerobotics.com",
        "contact_status": CONTACT_STATUS_WORKING_EMAIL_FOUND,
    }

    priya_row = connection.execute(
        """
        SELECT current_working_email, contact_status
        FROM contacts
        WHERE provider_person_id = 'pp_r2'
        """
    ).fetchone()
    assert dict(priya_row) == {
        "current_working_email": "priya@acmerobotics.com",
        "contact_status": CONTACT_STATUS_WORKING_EMAIL_FOUND,
    }

    morgan_link = connection.execute(
        """
        SELECT link_level_status
        FROM job_posting_contacts jpc
        JOIN contacts c
          ON c.contact_id = jpc.contact_id
        WHERE c.provider_person_id = 'pp_m1'
        """
    ).fetchone()
    assert morgan_link["link_level_status"] == POSTING_CONTACT_STATUS_SHORTLISTED

    isaiah_profile_path = paths.discovery_recipient_profile_path(
        "Acme Robotics",
        "Staff Software Engineer / AI",
        connection.execute(
            "SELECT contact_id FROM contacts WHERE provider_person_id = 'pp_r1'"
        ).fetchone()[0],
    )
    priya_profile_path = paths.discovery_recipient_profile_path(
        "Acme Robotics",
        "Staff Software Engineer / AI",
        connection.execute(
            "SELECT contact_id FROM contacts WHERE provider_person_id = 'pp_r2'"
        ).fetchone()[0],
    )
    assert isaiah_profile_path.exists()
    assert priya_profile_path.exists()
    isaiah_profile_payload = json.loads(isaiah_profile_path.read_text(encoding="utf-8"))
    assert isaiah_profile_payload["contact_id"]
    assert isaiah_profile_payload["job_posting_id"] == "jp_search"
    assert isaiah_profile_payload["linkedin_url"] == "https://linkedin.example/isaiah"

    posting_status = connection.execute(
        "SELECT posting_status FROM job_postings WHERE job_posting_id = 'jp_search'"
    ).fetchone()[0]
    assert posting_status == "ready_for_outreach"
    assert result.posting_status == "ready_for_outreach"
    assert set(result.recipient_profile_contact_ids) >= {
        connection.execute("SELECT contact_id FROM contacts WHERE provider_person_id = 'pp_r1'").fetchone()[0],
        connection.execute("SELECT contact_id FROM contacts WHERE provider_person_id = 'pp_r2'").fetchone()[0],
    }

    connection.close()


def test_apollo_contact_enrichment_removes_terminal_dead_end_shortlist_contacts(tmp_path: Path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_search_ready_posting(connection, paths)

    search_provider = FakeApolloProvider(
        resolved_company=ApolloResolvedCompany(
            organization_id="org_acme",
            organization_name="Acme Robotics",
            primary_domain="acmerobotics.com",
        ),
        candidates=[
            build_candidate(provider_person_id="pp_dead", display_name="Isa***h Lo***e", title="Corporate Recruiter")
        ],
    )
    search_result = run_apollo_people_search(
        project_root=project_root,
        job_posting_id="jp_search",
        provider=search_provider,
    )

    enrichment_provider = FakeApolloEnrichmentProvider({"pp_dead": None})
    result = run_apollo_contact_enrichment(
        project_root=project_root,
        job_posting_id="jp_search",
        provider=enrichment_provider,
        recipient_profile_extractor=FakeRecipientProfileExtractor({}),
    )

    assert len(search_result.shortlisted_contact_ids) == 1
    assert len(result.removed_job_posting_contact_ids) == 1
    assert len(result.removed_contact_ids) == 1
    assert connection.execute("SELECT COUNT(*) FROM job_posting_contacts").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM contacts").fetchone()[0] == 0
    assert connection.execute(
        "SELECT posting_status FROM job_postings WHERE job_posting_id = 'jp_search'"
    ).fetchone()[0] == "requires_contacts"

    people_search_payload = json.loads(search_result.artifact_path.read_text(encoding="utf-8"))
    assert people_search_payload["candidate_count"] == 1
    assert people_search_payload["candidates"][0]["provider_person_id"] == "pp_dead"

    connection.close()
