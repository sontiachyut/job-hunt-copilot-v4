from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from job_hunt_copilot.bootstrap import run_bootstrap
from job_hunt_copilot.email_discovery import (
    ApolloResolvedCompany,
    CONTACT_STATUS_EXHAUSTED,
    CONTACT_STATUS_WORKING_EMAIL_FOUND,
    DISCOVERY_OUTCOME_DOMAIN_UNRESOLVED,
    DISCOVERY_OUTCOME_NOT_FOUND,
    EmailDiscoveryError,
    EmailDiscoveryProviderResult,
    FEEDBACK_REUSE_PROVIDER_NAME,
    POSTING_CONTACT_STATUS_EXHAUSTED,
    POSTING_CONTACT_STATUS_IDENTIFIED,
    POSTING_CONTACT_STATUS_SHORTLISTED,
    PROVIDER_NAME_APOLLO,
    RECIPIENT_TYPE_ENGINEER,
    RECIPIENT_TYPE_HIRING_MANAGER,
    RECIPIENT_TYPE_RECRUITER,
    _normalize_getprospect_discovery_result,
    _normalize_hunter_discovery_result,
    _normalize_prospeo_discovery_result,
    load_provider_budget_summary,
    run_apollo_contact_enrichment,
    run_apollo_people_search,
    run_email_discovery_for_contact,
    run_general_learning_email_discovery,
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


class FakeEmailFinderProvider:
    def __init__(
        self,
        *,
        provider_name: str,
        responses: list[EmailDiscoveryProviderResult | dict[str, object]],
        requires_domain: bool = False,
    ) -> None:
        self.provider_name = provider_name
        self.responses = list(responses)
        self.requires_domain = requires_domain
        self.calls: list[dict[str, object | None]] = []

    def discover_email(
        self,
        *,
        contact: dict[str, object],
        posting: dict[str, object],
        company_domain: str | None,
        company_name: str | None,
    ) -> EmailDiscoveryProviderResult | dict[str, object]:
        self.calls.append(
            {
                "contact_id": contact.get("contact_id"),
                "job_posting_id": posting.get("job_posting_id"),
                "company_domain": company_domain,
                "company_name": company_name,
            }
        )
        if not self.responses:
            raise AssertionError(f"Fake provider {self.provider_name} ran out of responses.")
        return self.responses.pop(0)


def seed_linked_contact(
    connection: sqlite3.Connection,
    *,
    contact_id: str = "ct_target",
    job_posting_contact_id: str = "jpc_target",
    job_posting_id: str = "jp_search",
    company_name: str = "Acme Robotics",
    display_name: str = "Maya Rivera",
    full_name: str | None = "Maya Rivera",
    first_name: str | None = "Maya",
    last_name: str | None = "Rivera",
    linkedin_url: str | None = "https://linkedin.example/maya",
    position_title: str = "Engineering Manager",
    recipient_type: str = RECIPIENT_TYPE_HIRING_MANAGER,
    current_working_email: str | None = None,
    contact_status: str = "identified",
    link_level_status: str = POSTING_CONTACT_STATUS_SHORTLISTED,
    provider_name: str | None = PROVIDER_NAME_APOLLO,
    provider_person_id: str | None = "pp_target",
    identity_key: str = "apollo_person|pp_target",
    created_at: str = "2026-04-06T21:30:00Z",
) -> None:
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
            identity_key,
            display_name,
            company_name,
            "email_discovery",
            contact_status,
            full_name,
            first_name,
            last_name,
            linkedin_url,
            position_title,
            "Phoenix, AZ",
            "selected_for_discovery",
            current_working_email,
            "apollo_people_search_shortlist",
            provider_name,
            provider_person_id,
            "provider_full" if full_name else "provider_sparse",
            created_at,
            created_at,
        ),
    )
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
            recipient_type,
            "Selected contact for person-scoped discovery.",
            link_level_status,
            created_at,
            created_at,
        ),
    )
    connection.commit()


def seed_general_learning_contact(
    connection: sqlite3.Connection,
    *,
    contact_id: str = "ct_general_learning",
    company_name: str = "Acme Robotics",
    display_name: str = "Sam Learner",
    full_name: str | None = "Sam Learner",
    first_name: str | None = "Sam",
    last_name: str | None = "Learner",
    linkedin_url: str | None = "https://linkedin.example/sam",
    position_title: str = "Engineering Manager",
    current_working_email: str | None = None,
    contact_status: str = "identified",
    provider_name: str | None = None,
    provider_person_id: str | None = None,
    identity_key: str = "manual|sam-learner",
    created_at: str = "2026-04-06T21:30:00Z",
) -> None:
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
            identity_key,
            display_name,
            company_name,
            "manual_capture",
            contact_status,
            full_name,
            first_name,
            last_name,
            linkedin_url,
            position_title,
            "Phoenix, AZ",
            "general_learning_candidate",
            current_working_email,
            "manual_capture",
            provider_name,
            provider_person_id,
            "provider_full" if full_name else "provider_sparse",
            created_at,
            created_at,
        ),
    )
    connection.commit()


def test_general_learning_email_discovery_persists_contact_rooted_result_without_job_posting(
    tmp_path: Path,
):
    project_root = bootstrap_project(tmp_path)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_general_learning_contact(connection)

    hunter = FakeEmailFinderProvider(
        provider_name="hunter",
        responses=[
            {
                "outcome": "found",
                "email": "sam.learner@acme.example",
                "provider_verification_status": "valid",
                "provider_score": "0.91",
            }
        ],
    )

    result = run_general_learning_email_discovery(
        project_root=project_root,
        contact_id="ct_general_learning",
        providers=(hunter,),
        current_time="2026-04-06T21:40:00Z",
    )

    assert result.outcome == "found"
    assert result.provider_name == "hunter"
    assert result.email == "sam.learner@acme.example"
    assert result.contact_status == CONTACT_STATUS_WORKING_EMAIL_FOUND
    assert result.reused_existing_email is False
    assert hunter.calls == [
        {
            "contact_id": "ct_general_learning",
            "job_posting_id": None,
            "company_domain": None,
            "company_name": "Acme Robotics",
        }
    ]

    contact_row = connection.execute(
        """
        SELECT current_working_email, contact_status
        FROM contacts
        WHERE contact_id = 'ct_general_learning'
        """
    ).fetchone()
    assert dict(contact_row) == {
        "current_working_email": "sam.learner@acme.example",
        "contact_status": CONTACT_STATUS_WORKING_EMAIL_FOUND,
    }

    artifact_row = connection.execute(
        """
        SELECT job_posting_id, file_path
        FROM artifact_records
        WHERE artifact_type = 'discovery_result'
          AND contact_id = 'ct_general_learning'
        ORDER BY created_at DESC, artifact_id DESC
        LIMIT 1
        """
    ).fetchone()
    assert artifact_row["job_posting_id"] is None
    artifact_payload = json.loads(result.artifact_path.read_text(encoding="utf-8"))
    assert artifact_payload["contact_id"] == "ct_general_learning"
    assert artifact_payload.get("job_posting_id") is None
    assert artifact_payload["outcome"] == "found"
    assert artifact_payload["email"] == "sam.learner@acme.example"
    assert artifact_payload["attempted_provider_names"] == ["hunter"]

    connection.close()


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


def test_email_discovery_stops_on_first_usable_result_and_persists_budget_state(tmp_path: Path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_search_ready_posting(connection, paths)
    seed_linked_contact(connection)

    prospeo = FakeEmailFinderProvider(
        provider_name="prospeo",
        requires_domain=True,
        responses=[
            {
                "outcome": "not_found",
                "remaining_credits": 49,
                "credit_limit": 100,
                "reset_at": "2026-05-01T00:00:00Z",
            }
        ],
    )
    getprospect = FakeEmailFinderProvider(
        provider_name="getprospect",
        requires_domain=True,
        responses=[
            {
                "outcome": "found",
                "email": "maya@acmerobotics.com",
                "provider_verification_status": "valid",
                "provider_score": "0.92",
                "detected_pattern": "first",
                "remaining_credits": 74,
                "credit_limit": 120,
                "reset_at": "2026-05-01T00:00:00Z",
            }
        ],
    )
    hunter = FakeEmailFinderProvider(
        provider_name="hunter",
        responses=[
            {
                "outcome": "found",
                "email": "should-not-run@acmerobotics.com",
            }
        ],
    )

    result = run_email_discovery_for_contact(
        project_root=project_root,
        job_posting_id="jp_search",
        contact_id="ct_target",
        providers=(prospeo, getprospect, hunter),
        current_time="2026-04-06T21:45:00Z",
    )

    assert len(prospeo.calls) == 1
    assert len(getprospect.calls) == 1
    assert hunter.calls == []
    assert result.outcome == "found"
    assert result.provider_name == "getprospect"
    assert result.email == "maya@acmerobotics.com"
    assert result.posting_status == "ready_for_outreach"

    attempt_row = connection.execute(
        """
        SELECT outcome, provider_name, email, provider_verification_status, provider_score
        FROM discovery_attempts
        WHERE contact_id = 'ct_target'
        ORDER BY created_at DESC, discovery_attempt_id DESC
        LIMIT 1
        """
    ).fetchone()
    assert dict(attempt_row) == {
        "outcome": "found",
        "provider_name": "getprospect",
        "email": "maya@acmerobotics.com",
        "provider_verification_status": "valid",
        "provider_score": "0.92",
    }

    budget_summary = load_provider_budget_summary(project_root=project_root)
    assert budget_summary["combined_known_remaining_credits"] == 123
    assert budget_summary["providers"] == [
        {
            "provider_name": "getprospect",
            "remaining_credits": 74,
            "credit_limit": 120,
            "reset_at": "2026-05-01T00:00:00Z",
            "updated_at": "2026-04-06T21:45:00Z",
        },
        {
            "provider_name": "prospeo",
            "remaining_credits": 49,
            "credit_limit": 100,
            "reset_at": "2026-05-01T00:00:00Z",
            "updated_at": "2026-04-06T21:45:00Z",
        },
    ]

    budget_events = [
        dict(row)
        for row in connection.execute(
            """
            SELECT provider_name, event_type, remaining_credits_after
            FROM provider_budget_events
            ORDER BY provider_name ASC
            """
        ).fetchall()
    ]
    assert budget_events == [
        {
            "provider_name": "getprospect",
            "event_type": "found",
            "remaining_credits_after": 74,
        },
        {
            "provider_name": "prospeo",
            "event_type": "not_found",
            "remaining_credits_after": 49,
        },
    ]

    contact_row = connection.execute(
        """
        SELECT current_working_email, contact_status, discovery_summary
        FROM contacts
        WHERE contact_id = 'ct_target'
        """
    ).fetchone()
    assert dict(contact_row) == {
        "current_working_email": "maya@acmerobotics.com",
        "contact_status": CONTACT_STATUS_WORKING_EMAIL_FOUND,
        "discovery_summary": CONTACT_STATUS_WORKING_EMAIL_FOUND,
    }

    artifact_payload = json.loads(result.artifact_path.read_text(encoding="utf-8"))
    assert artifact_payload["result"] == "success"
    assert artifact_payload["outcome"] == "found"
    assert artifact_payload["provider_name"] == "getprospect"
    assert artifact_payload["attempted_provider_names"] == ["prospeo", "getprospect"]
    assert artifact_payload["provider_steps"][0]["outcome"] == "not_found"
    assert artifact_payload["provider_steps"][1]["outcome"] == "found"

    connection.close()


def test_email_discovery_reuses_known_working_email_without_provider_calls(tmp_path: Path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_search_ready_posting(connection, paths)
    seed_linked_contact(
        connection,
        current_working_email="maya@acmerobotics.com",
        contact_status=CONTACT_STATUS_WORKING_EMAIL_FOUND,
    )
    connection.execute(
        """
        INSERT INTO discovery_attempts (
          discovery_attempt_id, contact_id, job_posting_id, outcome, provider_name, email,
          email_local_part, detected_pattern, provider_verification_status, provider_score,
          bounced, display_name, first_name, last_name, full_name, linkedin_url, position_title,
          location, provider_person_id, name_quality, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "da_existing",
            "ct_target",
            "jp_search",
            "found",
            "hunter",
            "maya@acmerobotics.com",
            "maya",
            "first.last",
            "verified",
            "0.97",
            0,
            "Maya Rivera",
            "Maya",
            "Rivera",
            "Maya Rivera",
            "https://linkedin.example/maya",
            "Engineering Manager",
            "Phoenix, AZ",
            "pp_target",
            "provider_full",
            "2026-04-06T21:35:00Z",
        ),
    )
    connection.commit()

    prospeo = FakeEmailFinderProvider(provider_name="prospeo", responses=[])
    getprospect = FakeEmailFinderProvider(provider_name="getprospect", responses=[])
    hunter = FakeEmailFinderProvider(provider_name="hunter", responses=[])

    result = run_email_discovery_for_contact(
        project_root=project_root,
        job_posting_id="jp_search",
        contact_id="ct_target",
        providers=(prospeo, getprospect, hunter),
        current_time="2026-04-06T21:46:00Z",
    )

    assert result.reused_existing_email is True
    assert result.outcome == "found"
    assert result.provider_name == "hunter"
    assert prospeo.calls == []
    assert getprospect.calls == []
    assert hunter.calls == []
    assert connection.execute(
        "SELECT COUNT(*) FROM provider_budget_events"
    ).fetchone()[0] == 0

    latest_attempt = connection.execute(
        """
        SELECT outcome, provider_name, email
        FROM discovery_attempts
        WHERE contact_id = 'ct_target'
        ORDER BY created_at DESC, discovery_attempt_id DESC
        LIMIT 1
        """
    ).fetchone()
    assert dict(latest_attempt) == {
        "outcome": "found",
        "provider_name": "hunter",
        "email": "maya@acmerobotics.com",
    }

    connection.close()


def test_email_discovery_records_domain_unresolved_but_continues_hunter(tmp_path: Path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_search_ready_posting(
        connection,
        paths,
        source_url="https://www.linkedin.com/jobs/view/123",
    )
    seed_linked_contact(connection, linkedin_url=None, provider_person_id=None, identity_key="manual|maya")

    prospeo = FakeEmailFinderProvider(
        provider_name="prospeo",
        requires_domain=True,
        responses=[],
    )
    getprospect = FakeEmailFinderProvider(
        provider_name="getprospect",
        requires_domain=True,
        responses=[],
    )
    hunter = FakeEmailFinderProvider(
        provider_name="hunter",
        responses=[
            {
                "outcome": "not_found",
                "remaining_credits": 12,
                "credit_limit": 50,
            }
        ],
    )

    result = run_email_discovery_for_contact(
        project_root=project_root,
        job_posting_id="jp_search",
        contact_id="ct_target",
        providers=(prospeo, getprospect, hunter),
        current_time="2026-04-06T21:47:00Z",
    )

    assert result.outcome == DISCOVERY_OUTCOME_DOMAIN_UNRESOLVED
    assert prospeo.calls == []
    assert getprospect.calls == []
    assert len(hunter.calls) == 1

    attempt_row = connection.execute(
        """
        SELECT outcome, provider_name
        FROM discovery_attempts
        WHERE contact_id = 'ct_target'
        ORDER BY created_at DESC, discovery_attempt_id DESC
        LIMIT 1
        """
    ).fetchone()
    assert dict(attempt_row) == {
        "outcome": DISCOVERY_OUTCOME_DOMAIN_UNRESOLVED,
        "provider_name": None,
    }

    contact_row = connection.execute(
        """
        SELECT contact_status, discovery_summary
        FROM contacts
        WHERE contact_id = 'ct_target'
        """
    ).fetchone()
    assert dict(contact_row) == {
        "contact_status": POSTING_CONTACT_STATUS_IDENTIFIED,
        "discovery_summary": DISCOVERY_OUTCOME_DOMAIN_UNRESOLVED,
    }

    unresolved_row = connection.execute(
        """
        SELECT unresolved_reason
        FROM unresolved_contacts_review
        WHERE contact_id = 'ct_target'
        """
    ).fetchone()
    assert unresolved_row["unresolved_reason"] == "latest_outcome_domain_unresolved"

    connection.close()


def test_email_discovery_marks_contact_exhausted_after_full_no_match_cascade(tmp_path: Path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_search_ready_posting(connection, paths)
    seed_linked_contact(connection)

    providers = (
        FakeEmailFinderProvider(provider_name="prospeo", requires_domain=True, responses=[{"outcome": "not_found"}]),
        FakeEmailFinderProvider(provider_name="getprospect", requires_domain=True, responses=[{"outcome": "not_found"}]),
        FakeEmailFinderProvider(provider_name="hunter", responses=[{"outcome": "not_found"}]),
    )

    result = run_email_discovery_for_contact(
        project_root=project_root,
        job_posting_id="jp_search",
        contact_id="ct_target",
        providers=providers,
        current_time="2026-04-06T21:48:00Z",
    )

    assert result.outcome == DISCOVERY_OUTCOME_NOT_FOUND
    contact_row = connection.execute(
        """
        SELECT contact_status, discovery_summary
        FROM contacts
        WHERE contact_id = 'ct_target'
        """
    ).fetchone()
    assert dict(contact_row) == {
        "contact_status": CONTACT_STATUS_EXHAUSTED,
        "discovery_summary": "all_providers_exhausted",
    }

    link_row = connection.execute(
        """
        SELECT link_level_status
        FROM job_posting_contacts
        WHERE job_posting_contact_id = 'jpc_target'
        """
    ).fetchone()
    assert link_row["link_level_status"] == POSTING_CONTACT_STATUS_EXHAUSTED

    unresolved_row = connection.execute(
        """
        SELECT unresolved_reason
        FROM unresolved_contacts_review
        WHERE contact_id = 'ct_target'
        """
    ).fetchone()
    assert unresolved_row["unresolved_reason"] == "contact_exhausted"

    posting_status = connection.execute(
        "SELECT posting_status FROM job_postings WHERE job_posting_id = 'jp_search'"
    ).fetchone()[0]
    assert posting_status == "requires_contacts"

    artifact_payload = json.loads(result.artifact_path.read_text(encoding="utf-8"))
    assert artifact_payload["result"] == "blocked"
    assert artifact_payload["reason_code"] == DISCOVERY_OUTCOME_NOT_FOUND

    connection.close()


def test_email_discovery_retry_skips_bounced_provider_and_rejects_same_email(tmp_path: Path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_search_ready_posting(connection, paths)
    seed_linked_contact(
        connection,
        current_working_email="maya@acmerobotics.com",
        contact_status=CONTACT_STATUS_WORKING_EMAIL_FOUND,
    )
    connection.execute(
        """
        INSERT INTO discovery_attempts (
          discovery_attempt_id, contact_id, job_posting_id, outcome, provider_name, email,
          email_local_part, detected_pattern, provider_verification_status, provider_score,
          bounced, display_name, first_name, last_name, full_name, linkedin_url, position_title,
          location, provider_person_id, name_quality, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "da_bounced",
            "ct_target",
            "jp_search",
            "found",
            "prospeo",
            "maya@acmerobotics.com",
            "maya",
            "first",
            "verified",
            "0.99",
            0,
            "Maya Rivera",
            "Maya",
            "Rivera",
            "Maya Rivera",
            "https://linkedin.example/maya",
            "Engineering Manager",
            "Phoenix, AZ",
            "pp_target",
            "provider_full",
            "2026-04-06T21:35:00Z",
        ),
    )
    connection.execute(
        """
        INSERT INTO outreach_messages (
          outreach_message_id, contact_id, outreach_mode, recipient_email, message_status,
          job_posting_id, job_posting_contact_id, subject, body_text, body_html, thread_id,
          delivery_tracking_id, sent_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "msg_bounced",
            "ct_target",
            "email",
            "maya@acmerobotics.com",
            "sent",
            "jp_search",
            "jpc_target",
            "hello",
            "body",
            None,
            "thread-1",
            "delivery-1",
            "2026-04-06T21:36:00Z",
            "2026-04-06T21:36:00Z",
            "2026-04-06T21:36:00Z",
        ),
    )
    connection.execute(
        """
        INSERT INTO delivery_feedback_events (
          delivery_feedback_event_id, outreach_message_id, event_state, event_timestamp,
          contact_id, job_posting_id, reply_summary, raw_reply_excerpt, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "dfe_bounced",
            "msg_bounced",
            "bounced",
            "2026-04-06T21:40:00Z",
            "ct_target",
            "jp_search",
            None,
            None,
            "2026-04-06T21:40:00Z",
        ),
    )
    connection.commit()

    prospeo = FakeEmailFinderProvider(provider_name="prospeo", responses=[])
    getprospect = FakeEmailFinderProvider(
        provider_name="getprospect",
        requires_domain=True,
        responses=[{"outcome": "found", "email": "maya@acmerobotics.com"}],
    )
    hunter = FakeEmailFinderProvider(
        provider_name="hunter",
        responses=[{"outcome": "found", "email": "maya.rivera@acmerobotics.com"}],
    )

    result = run_email_discovery_for_contact(
        project_root=project_root,
        job_posting_id="jp_search",
        contact_id="ct_target",
        providers=(prospeo, getprospect, hunter),
        current_time="2026-04-06T21:49:00Z",
    )

    assert prospeo.calls == []
    assert len(getprospect.calls) == 1
    assert len(hunter.calls) == 1
    assert result.outcome == "found"
    assert result.provider_name == "hunter"
    assert result.email == "maya.rivera@acmerobotics.com"

    contact_row = connection.execute(
        """
        SELECT current_working_email, contact_status
        FROM contacts
        WHERE contact_id = 'ct_target'
        """
    ).fetchone()
    assert dict(contact_row) == {
        "current_working_email": "maya.rivera@acmerobotics.com",
        "contact_status": CONTACT_STATUS_WORKING_EMAIL_FOUND,
    }
    assert connection.execute(
        """
        SELECT COUNT(*)
        FROM state_transition_events
        WHERE object_type = 'contacts'
          AND object_id = 'ct_target'
        """
    ).fetchone()[0] == 0

    budget_events = [
        dict(row)
        for row in connection.execute(
            """
            SELECT provider_name, event_type
            FROM provider_budget_events
            ORDER BY provider_name ASC
            """
        ).fetchall()
    ]
    assert budget_events == [
        {"provider_name": "getprospect", "event_type": "bounced_match"},
        {"provider_name": "hunter", "event_type": "found"},
        {"provider_name": "prospeo", "event_type": "skipped_bounced_provider"},
    ]

    artifact_payload = json.loads(result.artifact_path.read_text(encoding="utf-8"))
    assert artifact_payload["feedback_reuse_summary"]["blocked_bounced_emails"] == [
        "maya@acmerobotics.com"
    ]
    assert [step["outcome"] for step in artifact_payload["provider_steps"]] == [
        "skipped_bounced_provider",
        "bounced_match",
        "found",
    ]

    connection.close()


def test_email_discovery_reuses_not_bounced_feedback_without_provider_calls(tmp_path: Path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_search_ready_posting(connection, paths)
    seed_linked_contact(
        connection,
        current_working_email="maya@acmerobotics.com",
        contact_status=CONTACT_STATUS_WORKING_EMAIL_FOUND,
    )
    connection.execute(
        """
        INSERT INTO outreach_messages (
          outreach_message_id, contact_id, outreach_mode, recipient_email, message_status,
          job_posting_id, job_posting_contact_id, subject, body_text, thread_id,
          delivery_tracking_id, sent_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "msg_not_bounced",
            "ct_target",
            "role_targeted",
            "maya@acmerobotics.com",
            "sent",
            "jp_search",
            "jpc_target",
            "hello",
            "body",
            "thread-not-bounced",
            "delivery-not-bounced",
            "2026-04-06T21:36:00Z",
            "2026-04-06T21:36:00Z",
            "2026-04-06T21:36:00Z",
        ),
    )
    connection.execute(
        """
        INSERT INTO delivery_feedback_events (
          delivery_feedback_event_id, outreach_message_id, event_state, event_timestamp,
          contact_id, job_posting_id, reply_summary, raw_reply_excerpt, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "dfe_not_bounced",
            "msg_not_bounced",
            "not_bounced",
            "2026-04-06T22:06:00Z",
            "ct_target",
            "jp_search",
            None,
            None,
            "2026-04-06T22:06:00Z",
        ),
    )
    connection.commit()

    prospeo = FakeEmailFinderProvider(provider_name="prospeo", responses=[])
    getprospect = FakeEmailFinderProvider(provider_name="getprospect", responses=[])
    hunter = FakeEmailFinderProvider(provider_name="hunter", responses=[])

    result = run_email_discovery_for_contact(
        project_root=project_root,
        job_posting_id="jp_search",
        contact_id="ct_target",
        providers=(prospeo, getprospect, hunter),
        current_time="2026-04-06T22:10:00Z",
    )

    assert result.reused_existing_email is True
    assert result.outcome == "found"
    assert result.provider_name == FEEDBACK_REUSE_PROVIDER_NAME
    assert result.email == "maya@acmerobotics.com"
    assert prospeo.calls == []
    assert getprospect.calls == []
    assert hunter.calls == []

    latest_attempt = connection.execute(
        """
        SELECT outcome, provider_name, email, provider_verification_status
        FROM discovery_attempts
        WHERE contact_id = 'ct_target'
        ORDER BY created_at DESC, discovery_attempt_id DESC
        LIMIT 1
        """
    ).fetchone()
    assert dict(latest_attempt) == {
        "outcome": "found",
        "provider_name": FEEDBACK_REUSE_PROVIDER_NAME,
        "email": "maya@acmerobotics.com",
        "provider_verification_status": "mailbox_not_bounced",
    }

    artifact_payload = json.loads(result.artifact_path.read_text(encoding="utf-8"))
    assert artifact_payload["observed_not_bounced"] is True
    assert artifact_payload["reply_retained_for_review_only"] is False
    assert artifact_payload["feedback_reuse_summary"]["reusable_not_bounced_emails"] == [
        "maya@acmerobotics.com"
    ]

    connection.close()


def test_provider_no_match_payloads_normalize_to_not_found():
    assert _normalize_prospeo_discovery_result(
        {"error_code": "NO_MATCH"},
        company_domain="acmerobotics.com",
    ).outcome == DISCOVERY_OUTCOME_NOT_FOUND
    assert _normalize_getprospect_discovery_result(
        {"success": False, "data": {"status": "not_found"}},
        company_domain="acmerobotics.com",
    ).outcome == DISCOVERY_OUTCOME_NOT_FOUND
    assert _normalize_hunter_discovery_result(
        {"data": {"email": None}},
        company_domain="acmerobotics.com",
    ).outcome == DISCOVERY_OUTCOME_NOT_FOUND
