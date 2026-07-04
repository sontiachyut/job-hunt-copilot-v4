from __future__ import annotations

import json
import sqlite3
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError

import pytest

from job_hunt_copilot.bootstrap import run_bootstrap
from job_hunt_copilot.email_discovery import (
    APOLLO_API_USER_AGENT,
    APOLLO_USAGE_ENDPOINT_COMPANY_SEARCH,
    ApolloResolvedCompany,
    CONTACT_STATUS_IDENTIFIED,
    CONTACT_STATUS_EXHAUSTED,
    CONTACT_STATUS_WORKING_EMAIL_FOUND,
    ConfiguredApolloClient,
    DEFAULT_SHORTLIST_LIMIT,
    DISCOVERY_SUMMARY_APOLLO_NO_USABLE_EMAIL,
    DISCOVERY_OUTCOME_DOMAIN_UNRESOLVED,
    DISCOVERY_OUTCOME_NOT_FOUND,
    DISCOVERY_OUTCOME_PROVIDER_ERROR,
    DISCOVERY_OUTCOME_PROVIDER_PAUSED,
    DISCOVERY_OUTCOME_QUOTA_EXHAUSTED,
    DISCOVERY_OUTCOME_RATE_LIMITED,
    EmailDiscoveryError,
    EmailDiscoveryProviderResult,
    FEEDBACK_REUSE_PROVIDER_NAME,
    PeopleSearchCandidate,
    POSTING_CONTACT_STATUS_EXHAUSTED,
    POSTING_CONTACT_STATUS_IDENTIFIED,
    POSTING_CONTACT_STATUS_OUTREACH_DONE,
    POSTING_CONTACT_STATUS_SHORTLISTED,
    PROVIDER_NAME_APOLLO,
    RECIPIENT_TYPE_ENGINEER,
    RECIPIENT_TYPE_HIRING_MANAGER,
    RECIPIENT_TYPE_OTHER_INTERNAL,
    RECIPIENT_TYPE_RECRUITER,
    _normalize_getprospect_discovery_result,
    _normalize_hunter_discovery_result,
    _normalize_prospeo_discovery_result,
    load_provider_budget_summary,
    refresh_same_company_contact_frontier,
    replay_historical_people_search_shortlist,
    is_role_targeted_email_discovery_actionable_now,
    is_role_targeted_people_search_actionable_now,
    run_apollo_contact_enrichment,
    run_apollo_people_search,
    run_email_discovery_for_contact,
    run_general_learning_email_discovery,
    select_initial_enrichment_shortlist,
    _build_apollo_search_filters,
    _manager_expansion_target_for_pool_size,
    _normalize_apollo_usage_snapshots,
    _shortlist_existing_intended_contacts,
)
from job_hunt_copilot.outreach import evaluate_role_targeted_send_set
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
    resume_tailoring_run_id: str | None = None,
    lead_id: str = "ld_search",
    company_name: str = "Acme Robotics",
    role_title: str = "Staff Software Engineer / AI",
    posting_status: str = "requires_contacts",
    resume_review_status: str = "approved",
    source_url: str = "https://careers.acmerobotics.com/jobs/123",
    timestamp: str = "2026-04-06T21:00:00Z",
) -> None:
    if resume_tailoring_run_id is None:
        resume_tailoring_run_id = f"rtr_{job_posting_id}"
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
            resume_tailoring_run_id,
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
    employment_history: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "provider_person_id": provider_person_id,
        "display_name": display_name,
        "title": title,
        "has_email": has_email,
        "email": email,
        "linkedin_url": linkedin_url,
        "has_direct_phone": False,
        "last_refreshed_at": last_refreshed_at,
    }
    if employment_history is not None:
        payload["employment_history"] = employment_history
    return payload


def test_select_initial_enrichment_shortlist_keeps_only_manager_class_technical_leadership():
    shortlist = select_initial_enrichment_shortlist(
        [
            PeopleSearchCandidate.from_mapping(
                build_candidate(
                    provider_person_id="pp_r1",
                    display_name="Priya Recruiter",
                    title="Corporate Recruiter",
                )
            ),
            PeopleSearchCandidate.from_mapping(
                build_candidate(
                    provider_person_id="pp_m1",
                    display_name="Morgan Manager",
                    title="Engineering Manager",
                )
            ),
            PeopleSearchCandidate.from_mapping(
                build_candidate(
                    provider_person_id="pp_e1",
                    display_name="Jamie Engineer",
                    title="Staff Software Engineer",
                )
            ),
            PeopleSearchCandidate.from_mapping(
                build_candidate(
                    provider_person_id="pp_e2",
                    display_name="Casey Engineer",
                    title="Software Engineer",
                )
            ),
            PeopleSearchCandidate.from_mapping(
                build_candidate(
                    provider_person_id="pp_m2",
                    display_name="Avery Director",
                    title="Director of Engineering",
                )
            ),
            PeopleSearchCandidate.from_mapping(
                build_candidate(
                    provider_person_id="pp_e3",
                    display_name="Robin Senior Engineer",
                    title="Senior Software Engineer",
                )
            ),
        ]
    )

    assert [candidate.provider_person_id for candidate in shortlist] == [
        "pp_m1",
        "pp_m2",
    ]


def test_select_initial_enrichment_shortlist_raises_founder_above_director_for_small_startup_style_pool():
    shortlist = select_initial_enrichment_shortlist(
        [
            PeopleSearchCandidate.from_mapping(
                build_candidate(
                    provider_person_id="pp_m1",
                    display_name="Morgan Manager",
                    title="Engineering Manager",
                )
            ),
            PeopleSearchCandidate.from_mapping(
                build_candidate(
                    provider_person_id="pp_f1",
                    display_name="Taylor Founder",
                    title="Founder & CTO",
                )
            ),
            PeopleSearchCandidate.from_mapping(
                build_candidate(
                    provider_person_id="pp_m2",
                    display_name="Avery Director",
                    title="Director of Engineering",
                )
            ),
            PeopleSearchCandidate.from_mapping(
                build_candidate(
                    provider_person_id="pp_c1",
                    display_name="Pat CTO",
                    title="Chief Technology Officer",
                )
            ),
        ],
        limit=4,
    )

    assert [candidate.provider_person_id for candidate in shortlist] == [
        "pp_m1",
        "pp_f1",
        "pp_m2",
        "pp_c1",
    ]


def test_select_initial_enrichment_shortlist_prefers_plain_founder_above_technical_cxo_for_small_startup_style_pool():
    shortlist = select_initial_enrichment_shortlist(
        [
            PeopleSearchCandidate.from_mapping(
                build_candidate(
                    provider_person_id="pp_m1",
                    display_name="Morgan Manager",
                    title="Engineering Manager",
                )
            ),
            PeopleSearchCandidate.from_mapping(
                build_candidate(
                    provider_person_id="pp_f1",
                    display_name="Taylor Founder",
                    title="Founder",
                )
            ),
            PeopleSearchCandidate.from_mapping(
                build_candidate(
                    provider_person_id="pp_c1",
                    display_name="Pat CTO",
                    title="Chief Technology Officer",
                )
            ),
            PeopleSearchCandidate.from_mapping(
                build_candidate(
                    provider_person_id="pp_d1",
                    display_name="Avery Director",
                    title="Director of Engineering",
                )
            ),
        ],
        limit=4,
    )

    assert [candidate.provider_person_id for candidate in shortlist] == [
        "pp_m1",
        "pp_f1",
        "pp_d1",
        "pp_c1",
    ]


def test_select_initial_enrichment_shortlist_keeps_plain_ceo_below_founder_and_technical_cxo():
    shortlist = select_initial_enrichment_shortlist(
        [
            PeopleSearchCandidate.from_mapping(
                build_candidate(
                    provider_person_id="pp_m1",
                    display_name="Morgan Manager",
                    title="Engineering Manager",
                )
            ),
            PeopleSearchCandidate.from_mapping(
                build_candidate(
                    provider_person_id="pp_f1",
                    display_name="Taylor Founder",
                    title="Founder",
                )
            ),
            PeopleSearchCandidate.from_mapping(
                build_candidate(
                    provider_person_id="pp_c1",
                    display_name="Pat CTO",
                    title="Chief Technology Officer",
                )
            ),
            PeopleSearchCandidate.from_mapping(
                build_candidate(
                    provider_person_id="pp_e1",
                    display_name="Casey CEO",
                    title="Chief Executive Officer",
                )
            ),
        ],
        limit=4,
    )

    assert [candidate.provider_person_id for candidate in shortlist] == [
        "pp_m1",
        "pp_f1",
        "pp_c1",
        "pp_e1",
    ]


def test_select_initial_enrichment_shortlist_prefers_usable_email_within_same_priority_bucket():
    shortlist = select_initial_enrichment_shortlist(
        [
            PeopleSearchCandidate.from_mapping(
                build_candidate(
                    provider_person_id="pp_m1",
                    display_name="Morgan Manager",
                    title="Engineering Manager",
                    has_email=False,
                    email=None,
                )
            ),
            PeopleSearchCandidate.from_mapping(
                build_candidate(
                    provider_person_id="pp_m2",
                    display_name="Avery Manager",
                    title="Engineering Manager",
                    has_email=True,
                    email="avery@acme.example",
                )
            ),
        ],
        limit=2,
    )

    assert [candidate.provider_person_id for candidate in shortlist] == [
        "pp_m2",
        "pp_m1",
    ]


def test_build_apollo_search_filters_targets_manager_class_engineering_leadership(tmp_path: Path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_search_ready_posting(
        connection,
        paths,
        company_name="JPMorganChase",
        role_title="AI/ML Engineer [Multiple Positions Available]",
        source_url="https://careers.jpmorganchase.com/jobs/123",
    )
    posting_row = connection.execute(
        "SELECT * FROM job_postings WHERE job_posting_id = 'jp_search'"
    ).fetchone()
    assert posting_row is not None

    search_filters = _build_apollo_search_filters(
        posting_row,
        jd_text="Machine learning and artificial intelligence platform work.",
        shortlist_limit=DEFAULT_SHORTLIST_LIMIT,
    )
    connection.close()

    assert "AI/ML Engineer [Multiple Positions Available]" not in search_filters["titles"]
    assert any("AI" in title and "Manager" in title for title in search_filters["titles"])
    assert "AI Engineering Manager" in search_filters["titles"]
    assert "Head of AI Engineering" in search_filters["titles"]
    assert "Chief Technology Officer" in search_filters["titles"]
    assert search_filters["functions"] == ["engineering"]
    assert search_filters["locations"] == []


@pytest.mark.parametrize(
    ("eligible_pool_size", "expected_target"),
    [
        (0, 0),
        (1, 1),
        (5, 5),
        (6, 7),
        (10, 7),
        (11, 10),
        (20, 10),
    ],
)
def test_manager_expansion_target_scales_with_eligible_pool_size(
    eligible_pool_size: int,
    expected_target: int,
):
    assert _manager_expansion_target_for_pool_size(eligible_pool_size) == expected_target


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


class LocationFallbackApolloProvider(FakeApolloProvider):
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
        if list(search_filters.get("locations") or []):
            return []
        return list(self.candidates)


class QuotaExhaustedApolloProvider(FakeApolloProvider):
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
        raise EmailDiscoveryError(
            "Apollo request failed with HTTP 422.",
            reason_code=DISCOVERY_OUTCOME_QUOTA_EXHAUSTED,
        )


class UsageStatsApolloProvider(FakeApolloProvider):
    def __init__(
        self,
        *,
        resolved_company: ApolloResolvedCompany | None,
        candidates: list[dict[str, object]],
        usage_stats_payload: dict[str, object],
    ) -> None:
        super().__init__(resolved_company=resolved_company, candidates=candidates)
        self.usage_stats_payload = usage_stats_payload
        self.fetch_usage_stats_calls = 0

    def fetch_usage_stats(self) -> dict[str, object]:
        self.fetch_usage_stats_calls += 1
        return dict(self.usage_stats_payload)


class ProviderErrorApolloProvider(FakeApolloProvider):
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
        raise EmailDiscoveryError(
            "Apollo request failed with HTTP 503.",
            reason_code=DISCOVERY_OUTCOME_PROVIDER_ERROR,
        )


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
    contact_source_type: str | None = None,
    contact_source_priority_tier: int | None = None,
    contact_source_rank: int | None = None,
    is_in_intended_outreach_set: int = 0,
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
          link_level_status, contact_source_type, contact_source_priority_tier,
          contact_source_rank, is_in_intended_outreach_set, entered_intended_outreach_set_at,
          created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job_posting_contact_id,
            job_posting_id,
            contact_id,
            recipient_type,
            "Selected contact for person-scoped discovery.",
            link_level_status,
            contact_source_type,
            contact_source_priority_tier,
            contact_source_rank,
            is_in_intended_outreach_set,
            created_at if is_in_intended_outreach_set else None,
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
            raw_payload={
                "organization_id": "org_acme",
                "organization_name": "Acme Robotics",
                "primary_domain": "acmerobotics.com",
                "website_url": "https://acmerobotics.com",
                "linkedin_url": "https://www.linkedin.com/company/acme-robotics",
            },
        ),
        candidates=[
            build_candidate(
                provider_person_id="pp_r1",
                display_name="Isaiah Lo***e",
                title="Corporate Recruiter",
                has_email=True,
                employment_history=[
                    {
                        "company_name": "Acme Robotics",
                        "title": "Corporate Recruiter",
                        "start_date": "2024-01-01",
                        "current": True,
                    }
                ],
            ),
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
    assert payload["apollo_top_up_needed"] == 5
    assert payload["eligible_manager_candidate_count"] == 3
    assert payload["manager_shortlist_target"] == 3
    assert payload["apollo_manager_needed"] == 3
    assert payload["apollo_top_up_added_count"] == 3
    assert len(payload["shortlisted_contact_ids"]) == 3

    shortlist_candidates = [candidate for candidate in payload["candidates"] if candidate.get("contact_id")]
    shortlist_provider_ids = {candidate["provider_person_id"] for candidate in shortlist_candidates}
    assert len(shortlist_provider_ids) == 3
    assert shortlist_provider_ids == {"pp_m1", "pp_m2", "pp_m3"}
    assert {"pp_r1", "pp_r2", "pp_r3", "pp_e1", "pp_e2", "pp_o1"} & shortlist_provider_ids == set()

    sparse_candidate = next(candidate for candidate in payload["candidates"] if candidate["provider_person_id"] == "pp_r1")
    assert sparse_candidate["display_name"] == "Isaiah Lo***e"
    assert sparse_candidate["full_name"] is None
    assert sparse_candidate["name_quality"] == "provider_obfuscated"

    assert connection.execute("SELECT COUNT(*) FROM contacts").fetchone()[0] == 3
    assert connection.execute("SELECT COUNT(*) FROM job_posting_contacts").fetchone()[0] == 3
    assert connection.execute("SELECT COUNT(*) FROM contact_provider_profiles").fetchone()[0] == 3
    assert connection.execute("SELECT COUNT(*) FROM contact_employment_history").fetchone()[0] == 0
    provider_context_row = connection.execute(
        """
        SELECT provider_name, context_stage, provider_organization_id
        FROM job_posting_provider_contexts
        WHERE job_posting_id = 'jp_search'
        """
    ).fetchone()
    assert dict(provider_context_row) == {
        "provider_name": PROVIDER_NAME_APOLLO,
        "context_stage": "apollo_company_resolution",
        "provider_organization_id": "org_acme",
    }
    provider_profile_row = connection.execute(
        """
        SELECT provider_name, profile_stage, provider_person_id
        FROM contact_provider_profiles
        WHERE provider_person_id = 'pp_r1'
        ORDER BY created_at DESC
        LIMIT 1
        """
    ).fetchone()
    assert provider_profile_row is None
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
    assert recipient_counts[RECIPIENT_TYPE_HIRING_MANAGER] >= 3
    assert RECIPIENT_TYPE_RECRUITER not in recipient_counts
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


def test_apollo_people_search_still_runs_manager_harvest_when_seeded_contacts_already_meet_total_minimum(tmp_path: Path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_search_ready_posting(connection, paths)
    for index, (recipient_type, position_title) in enumerate(
        (
            (RECIPIENT_TYPE_HIRING_MANAGER, "Engineering Manager"),
            (RECIPIENT_TYPE_ENGINEER, "Software Engineer"),
            (RECIPIENT_TYPE_RECRUITER, "Technical Recruiter"),
            (RECIPIENT_TYPE_ENGINEER, "Software Engineer"),
            (RECIPIENT_TYPE_HIRING_MANAGER, "Director of Engineering"),
        ),
        start=1,
    ):
        seed_linked_contact(
            connection,
            contact_id=f"ct_seed_{index}",
            job_posting_contact_id=f"jpc_seed_{index}",
            display_name=f"Seeded Contact {index}",
            recipient_type=recipient_type,
            position_title=position_title,
            provider_name=None,
            provider_person_id=None,
            identity_key=f"jobright|seeded|{index}",
            contact_source_type="jobright_public",
            contact_source_priority_tier=2,
            contact_source_rank=index,
            link_level_status=POSTING_CONTACT_STATUS_IDENTIFIED,
            is_in_intended_outreach_set=1,
            created_at=f"2026-04-06T21:3{index}:00Z",
        )

    provider = FakeApolloProvider(
        resolved_company=ApolloResolvedCompany(
            organization_id="org_should_not_run",
            organization_name="Acme Robotics",
        ),
        candidates=[
            build_candidate(
                provider_person_id="pp_unused",
                display_name="Should Not Run",
                title="Engineering Manager",
            )
        ],
    )
    result = run_apollo_people_search(
        project_root=project_root,
        job_posting_id="jp_search",
        provider=provider,
    )

    assert len(provider.resolve_calls) == 1
    assert len(provider.search_calls) == 4
    assert len(result.shortlisted_contact_ids) == 6
    assert {f"ct_seed_{index}" for index in range(1, 6)}.issubset(set(result.shortlisted_contact_ids))

    payload = json.loads(result.artifact_path.read_text(encoding="utf-8"))
    assert payload["apollo_top_up_needed"] == 0
    assert payload["active_apollo_manager_contact_count_before_top_up"] == 0
    assert payload["eligible_manager_candidate_count"] == 1
    assert payload["manager_shortlist_target"] == 1
    assert payload["apollo_manager_needed"] == 1
    assert payload["apollo_top_up_added_count"] == 1
    assert payload["candidate_count"] == 1
    assert len(payload["seeded_shortlist_contact_ids"]) == 5

    shortlisted_rows = connection.execute(
        """
        SELECT contact_id, link_level_status
        FROM job_posting_contacts
        WHERE job_posting_id = 'jp_search'
        ORDER BY contact_id ASC
        """
    ).fetchall()
    assert all(row["link_level_status"] == POSTING_CONTACT_STATUS_SHORTLISTED for row in shortlisted_rows)
    connection.close()


def test_apollo_people_search_reuses_caller_connection_when_transaction_is_already_open(tmp_path: Path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_search_ready_posting(connection, paths)
    connection.execute(
        """
        UPDATE job_postings
        SET updated_at = ?
        WHERE job_posting_id = 'jp_search'
        """,
        ("2026-04-06T21:33:00Z",),
    )

    provider = FakeApolloProvider(
        resolved_company=ApolloResolvedCompany(
            organization_id="org_acme",
            organization_name="Acme Robotics",
            primary_domain="acmerobotics.com",
        ),
        candidates=[
            build_candidate(
                provider_person_id="pp_txn",
                    display_name="Jordan Manager",
                    title="Engineering Manager",
                )
            ],
        )

    result = run_apollo_people_search(
        project_root=project_root,
        job_posting_id="jp_search",
        provider=provider,
        connection=connection,
        current_time="2026-04-06T21:34:00Z",
    )

    assert len(result.shortlisted_contact_ids) == 1
    assert provider.resolve_calls
    assert provider.search_calls
    assert connection.execute(
        """
        SELECT link_level_status
        FROM job_posting_contacts
        WHERE job_posting_id = 'jp_search'
        """
    ).fetchone()[0] == POSTING_CONTACT_STATUS_SHORTLISTED

    connection.close()


def test_apollo_people_search_adds_manager_contacts_even_when_only_some_seeded_contacts_exist(tmp_path: Path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_search_ready_posting(connection, paths)
    for index, (recipient_type, position_title) in enumerate(
        (
            (RECIPIENT_TYPE_HIRING_MANAGER, "Engineering Manager"),
            (RECIPIENT_TYPE_ENGINEER, "Software Engineer"),
            (RECIPIENT_TYPE_RECRUITER, "Technical Recruiter"),
        ),
        start=1,
    ):
        seed_linked_contact(
            connection,
            contact_id=f"ct_seed_gap_{index}",
            job_posting_contact_id=f"jpc_seed_gap_{index}",
            display_name=f"Gap Seeded Contact {index}",
            recipient_type=recipient_type,
            position_title=position_title,
            provider_name=None,
            provider_person_id=None,
            identity_key=f"jobright|gap|{index}",
            contact_source_type="jobright_public",
            contact_source_priority_tier=2,
            contact_source_rank=index,
            link_level_status=POSTING_CONTACT_STATUS_IDENTIFIED,
            is_in_intended_outreach_set=1,
            created_at=f"2026-04-06T21:4{index}:00Z",
        )

    provider = FakeApolloProvider(
        resolved_company=ApolloResolvedCompany(
            organization_id="org_acme",
            organization_name="Acme Robotics",
            primary_domain="acmerobotics.com",
        ),
        candidates=[
            build_candidate(
                provider_person_id="pp_topup_1",
                display_name="Apollo Manager",
                title="Engineering Manager",
            ),
            build_candidate(
                provider_person_id="pp_topup_2",
                display_name="Apollo Director",
                title="Director of Engineering",
            ),
            build_candidate(
                provider_person_id="pp_topup_3",
                display_name="Apollo VP",
                title="VP Engineering",
            ),
        ],
    )
    result = run_apollo_people_search(
        project_root=project_root,
        job_posting_id="jp_search",
        provider=provider,
    )

    assert len(provider.resolve_calls) == 1
    assert len(provider.search_calls) == 4
    assert len(result.shortlisted_contact_ids) == 6

    payload = json.loads(result.artifact_path.read_text(encoding="utf-8"))
    assert payload["apollo_top_up_needed"] == 2
    assert payload["active_apollo_manager_contact_count_before_top_up"] == 0
    assert payload["eligible_manager_candidate_count"] == 3
    assert payload["manager_shortlist_target"] == 3
    assert payload["apollo_manager_needed"] == 3
    assert payload["apollo_top_up_added_count"] == 3
    assert payload["candidate_count"] == 3

    source_rows = connection.execute(
        """
        SELECT contact_source_type, COUNT(*) AS row_count
        FROM job_posting_contacts
        WHERE job_posting_id = 'jp_search'
        GROUP BY contact_source_type
        ORDER BY contact_source_type ASC
        """
    ).fetchall()
    assert [dict(row) for row in source_rows] == [
        {"contact_source_type": "apollo_topup", "row_count": 3},
        {"contact_source_type": "jobright_public", "row_count": 3},
    ]
    connection.close()


def test_people_search_remains_actionable_for_pending_seeded_contacts_even_when_apollo_is_paused(
    tmp_path: Path,
):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_search_ready_posting(connection, paths)
    seed_linked_contact(
        connection,
        contact_id="ct_seed_actionable",
        job_posting_contact_id="jpc_seed_actionable",
        recipient_type=RECIPIENT_TYPE_RECRUITER,
        provider_name=None,
        provider_person_id=None,
        identity_key="jobright|seed|actionable",
        contact_source_type="jobright_public",
        contact_source_priority_tier=2,
        contact_source_rank=1,
        link_level_status=POSTING_CONTACT_STATUS_IDENTIFIED,
        is_in_intended_outreach_set=1,
    )
    connection.execute(
        """
        INSERT INTO provider_budget_state (
          provider_name, cooldown_until, updated_at
        ) VALUES (?, ?, ?)
        """,
        (
            PROVIDER_NAME_APOLLO,
            "2026-04-07T00:00:00Z",
            "2026-04-06T22:00:00Z",
        ),
    )
    connection.commit()

    assert is_role_targeted_people_search_actionable_now(
        connection,
        current_time="2026-04-06T22:10:00Z",
        job_posting_id="jp_search",
    ) is True
    connection.close()


def test_email_discovery_remains_actionable_when_ready_subset_exists_but_pending_contacts_are_cooling_down(
    tmp_path: Path,
):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_search_ready_posting(connection, paths)
    seed_linked_contact(
        connection,
        contact_id="ct_ready_now",
        job_posting_contact_id="jpc_ready_now",
        display_name="Avery Manager",
        position_title="Engineering Manager",
        recipient_type=RECIPIENT_TYPE_HIRING_MANAGER,
        current_working_email="avery@acme.example",
        contact_status=CONTACT_STATUS_WORKING_EMAIL_FOUND,
        is_in_intended_outreach_set=1,
    )
    seed_linked_contact(
        connection,
        contact_id="ct_pending_cooldown",
        job_posting_contact_id="jpc_pending_cooldown",
        display_name="Blair Engineer",
        position_title="Software Engineer",
        recipient_type=RECIPIENT_TYPE_ENGINEER,
        provider_person_id=None,
        identity_key="jobright|cooldown|pending",
        current_working_email=None,
        contact_source_type="jobright_public",
        contact_source_priority_tier=2,
        contact_source_rank=2,
        is_in_intended_outreach_set=1,
    )
    connection.execute(
        """
        INSERT INTO provider_budget_state (
          provider_name, cooldown_until, updated_at
        ) VALUES (?, ?, ?)
        """,
        (
            "getprospect",
            "2026-04-07T00:00:00Z",
            "2026-04-06T22:00:00Z",
        ),
    )
    connection.commit()

    assert is_role_targeted_email_discovery_actionable_now(
        connection,
        project_root=project_root,
        job_posting_id="jp_search",
        current_time="2026-04-06T22:10:00Z",
        providers=(
            FakeEmailFinderProvider(
                provider_name="getprospect",
                responses=[{"outcome": DISCOVERY_OUTCOME_NOT_FOUND}],
                requires_domain=False,
            ),
        ),
    ) is True
    connection.close()


def test_apollo_people_search_reuses_same_company_apollo_key_before_company_resolution(tmp_path: Path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_search_ready_posting(connection, paths, job_posting_id="jp_primary", lead_id="ld_primary")
    seed_search_ready_posting(
        connection,
        paths,
        job_posting_id="jp_existing",
        lead_id="ld_existing",
        role_title="Data Platform Engineer",
    )
    connection.execute(
        """
        UPDATE job_postings
        SET canonical_company_key = ?, provider_company_key = ?, company_key_source = ?, updated_at = ?
        WHERE job_posting_id = ?
        """,
        (
            "apollo:org_acme",
            "apollo:org_acme",
            "apollo",
            "2026-04-06T22:00:00Z",
            "jp_existing",
        ),
    )
    connection.commit()

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
        job_posting_id="jp_primary",
        provider=provider,
    )

    assert provider.resolve_calls == []
    reused_company = provider.search_calls[0]["resolved_company"]
    assert isinstance(reused_company, ApolloResolvedCompany)
    assert reused_company.organization_id == "org_acme"
    payload = json.loads(result.artifact_path.read_text(encoding="utf-8"))
    assert payload["search_anchor"] == "organization_id"
    assert payload["resolved_company"]["organization_id"] == "org_acme"

    promoted_row = connection.execute(
        """
        SELECT canonical_company_key, provider_company_key, company_key_source
        FROM job_postings
        WHERE job_posting_id = 'jp_primary'
        """
    ).fetchone()
    assert dict(promoted_row) == {
        "canonical_company_key": "apollo:org_acme",
        "provider_company_key": "apollo:org_acme",
        "company_key_source": "apollo",
    }

    connection.close()


def test_replay_historical_people_search_shortlist_materializes_missing_candidates(tmp_path: Path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_search_ready_posting(connection, paths)

    provider = FakeApolloProvider(
        resolved_company=ApolloResolvedCompany(
            organization_id="org_acme",
            organization_name="Acme Robotics",
            primary_domain="acmerobotics.com",
        ),
        candidates=[
            build_candidate(provider_person_id="pp_m1", display_name="Morgan Manager", title="Engineering Manager"),
            build_candidate(provider_person_id="pp_m2", display_name="Avery Director", title="Director of Engineering"),
            build_candidate(provider_person_id="pp_m3", display_name="Robin Head", title="Head of Engineering"),
            build_candidate(provider_person_id="pp_m4", display_name="Casey VP", title="VP Engineering", has_email=True, email="casey@acmerobotics.com"),
            build_candidate(provider_person_id="pp_m5", display_name="Pat CTO", title="Chief Technology Officer"),
        ],
    )

    initial = run_apollo_people_search(
        project_root=project_root,
        job_posting_id="jp_search",
        provider=provider,
        shortlist_limit=2,
    )
    assert len(initial.shortlisted_contact_ids) == 2

    connection.execute(
        "UPDATE job_postings SET posting_status = ?, updated_at = ? WHERE job_posting_id = ?",
        ("completed", "2026-04-07T01:00:00Z", "jp_search"),
    )
    connection.commit()

    replay = replay_historical_people_search_shortlist(
        project_root=project_root,
        job_posting_id="jp_search",
        shortlist_limit=5,
        current_time="2026-04-07T02:00:00Z",
    )

    assert replay.candidate_count == 5
    assert replay.shortlist_limit == 5
    assert len(replay.materialized_contact_ids) == 3
    assert len(replay.shortlisted_contact_ids) == 5

    artifact_payload = json.loads(replay.artifact_path.read_text(encoding="utf-8"))
    assert artifact_payload["shortlist_limit"] == 5
    assert len(artifact_payload["shortlisted_contact_ids"]) == 5
    assert len([candidate for candidate in artifact_payload["candidates"] if candidate.get("contact_id")]) == 5

    connection.close()


def test_refresh_same_company_contact_frontier_exhausts_reused_contact_and_backfills_from_saved_artifact(
    tmp_path: Path,
):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_search_ready_posting(connection, paths, job_posting_id="jp_primary", lead_id="ld_primary")
    seed_search_ready_posting(
        connection,
        paths,
        job_posting_id="jp_other",
        lead_id="ld_other",
        role_title="Backend Platform Engineer",
    )

    provider = FakeApolloProvider(
        resolved_company=ApolloResolvedCompany(
            organization_id="org_acme",
            organization_name="Acme Robotics",
            primary_domain="acmerobotics.com",
        ),
        candidates=[
            build_candidate(provider_person_id="pp_m1", display_name="Morgan Manager", title="Engineering Manager"),
            build_candidate(provider_person_id="pp_f1", display_name="Taylor Founder", title="Founder & CTO"),
            build_candidate(provider_person_id="pp_d1", display_name="Avery Director", title="Director of Engineering"),
            build_candidate(provider_person_id="pp_c1", display_name="Pat CTO", title="Chief Technology Officer"),
        ],
    )

    initial = run_apollo_people_search(
        project_root=project_root,
        job_posting_id="jp_primary",
        provider=provider,
        shortlist_limit=3,
        current_time="2026-04-06T21:00:00Z",
    )
    assert len(initial.shortlisted_contact_ids) == 3

    reused_contact_id = connection.execute(
        """
        SELECT contact_id
        FROM contacts
        WHERE provider_person_id = 'pp_m1'
        """
    ).fetchone()["contact_id"]
    connection.execute(
        """
        INSERT INTO job_posting_contacts (
          job_posting_contact_id, job_posting_id, contact_id, recipient_type, relevance_reason,
          link_level_status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "jpc_other_r1",
            "jp_other",
            reused_contact_id,
            RECIPIENT_TYPE_HIRING_MANAGER,
            "Previously used on another posting.",
            POSTING_CONTACT_STATUS_OUTREACH_DONE,
            "2026-04-05T18:00:00Z",
            "2026-04-05T18:00:00Z",
        ),
    )
    connection.execute(
        """
        INSERT INTO outreach_messages (
          outreach_message_id, contact_id, outreach_mode, recipient_email, message_status,
          job_posting_id, job_posting_contact_id, subject, body_text, sent_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "msg_other_r1",
            reused_contact_id,
            "role_targeted",
            "morgan@acmerobotics.com",
            "sent",
            "jp_other",
            "jpc_other_r1",
            "Hello",
            "Hello",
            "2026-04-05T18:05:00Z",
            "2026-04-05T18:05:00Z",
            "2026-04-05T18:05:00Z",
        ),
    )
    connection.commit()
    connection.close()

    refresh_result = refresh_same_company_contact_frontier(
        project_root=project_root,
        job_posting_id="jp_primary",
        shortlist_limit=3,
        current_time="2026-04-06T22:00:00Z",
    )

    assert refresh_result["excluded_count"] == 1
    assert refresh_result["replayed"] is True
    assert len(refresh_result["replay_materialized_contact_ids"]) == 1

    connection = connect_database(project_root / "job_hunt_copilot.db")
    primary_links = connection.execute(
        """
        SELECT c.provider_person_id, jpc.link_level_status
        FROM job_posting_contacts jpc
        JOIN contacts c
          ON c.contact_id = jpc.contact_id
        WHERE jpc.job_posting_id = 'jp_primary'
        ORDER BY jpc.created_at ASC, jpc.job_posting_contact_id ASC
        """
    ).fetchall()
    statuses_by_provider = {str(row["provider_person_id"]): str(row["link_level_status"]) for row in primary_links}
    assert statuses_by_provider["pp_m1"] == POSTING_CONTACT_STATUS_EXHAUSTED
    assert statuses_by_provider["pp_f1"] == POSTING_CONTACT_STATUS_SHORTLISTED
    assert "pp_d1" in statuses_by_provider or "pp_c1" in statuses_by_provider
    active_count = connection.execute(
        """
        SELECT COUNT(*)
        FROM job_posting_contacts
        WHERE job_posting_id = 'jp_primary'
          AND link_level_status IN ('identified', 'shortlisted')
        """
    ).fetchone()[0]
    assert active_count == 3

    connection.close()
    connection = connect_database(project_root / "job_hunt_copilot.db")
    assert connection.execute("SELECT COUNT(*) FROM job_posting_contacts").fetchone()[0] == 5
    assert connection.execute("SELECT COUNT(*) FROM contacts").fetchone()[0] == 4

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
                display_name="Taylor Director",
                title="Director of Engineering",
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


def test_apollo_contact_enrichment_skips_contacts_that_already_have_usable_emails_and_persists_ready_recipient_profiles(
    tmp_path: Path,
):
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
            "https://linkedin.example/avery": {
                "profile_source": "linkedin_public_profile",
                "source_method": "public_profile_html",
                "profile": {
                    "identity": {
                        "display_name": "Avery Director",
                        "full_name": "Avery Director",
                        "first_name": "Avery",
                        "last_name": "Director",
                    },
                    "top_card": {
                        "current_company": "Acme Robotics",
                        "current_title": "Director of Engineering",
                        "headline": "Director of Engineering at Acme Robotics",
                        "location": "Phoenix, Arizona, United States",
                        "connections": "500+",
                        "followers": "220",
                    },
                    "about": {"preview_text": "Leads platform and cloud engineering hiring.", "is_truncated": False},
                    "experience_hints": {
                        "current_company_hint": "Acme Robotics",
                        "education_hint": None,
                        "experience_education_preview": "Director of Engineering at Acme Robotics",
                    },
                    "recent_public_activity": [],
                    "public_signals": {
                        "licenses_and_certifications": [],
                        "honors_and_awards": [],
                        "recommendation_entities": [],
                    },
                    "work_signals": ["Engineering leadership close to the target role"],
                    "evidence_snippets": ["Current company hint: Acme Robotics"],
                    "source_coverage": {
                        "about": True,
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

    called_provider_ids = {str(call["provider_person_id"]) for call in enrichment_provider.calls}
    assert "pp_r2" not in called_provider_ids
    assert "pp_m2" not in called_provider_ids
    assert "pp_e1" not in called_provider_ids
    assert "pp_e2" not in called_provider_ids

    avery_row = connection.execute(
        """
        SELECT current_working_email, contact_status
        FROM contacts
        WHERE provider_person_id = 'pp_m2'
        """
    ).fetchone()
    assert dict(avery_row) == {
        "current_working_email": "avery@acmerobotics.com",
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

    avery_profile_path = paths.discovery_recipient_profile_path(
        "Acme Robotics",
        "Staff Software Engineer / AI",
        connection.execute(
            "SELECT contact_id FROM contacts WHERE provider_person_id = 'pp_m2'"
        ).fetchone()[0],
    )
    assert avery_profile_path.exists()
    avery_profile_payload = json.loads(avery_profile_path.read_text(encoding="utf-8"))
    assert avery_profile_payload["contact_id"]
    assert avery_profile_payload["job_posting_id"] == "jp_search"
    assert avery_profile_payload["linkedin_url"] == "https://linkedin.example/avery"

    posting_status = connection.execute(
        "SELECT posting_status FROM job_postings WHERE job_posting_id = 'jp_search'"
    ).fetchone()[0]
    assert posting_status == "ready_for_outreach"
    assert result.posting_status == "ready_for_outreach"
    assert connection.execute(
        "SELECT contact_id FROM contacts WHERE provider_person_id = 'pp_m2'"
    ).fetchone()[0] in set(result.recipient_profile_contact_ids)

    connection.close()


def test_apollo_contact_enrichment_settles_full_shortlisted_set_when_posting_is_not_ready(tmp_path: Path):
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
            build_candidate(provider_person_id="pp_r1", display_name="Taylor Recruiter", title="Recruiter"),
            build_candidate(provider_person_id="pp_r2", display_name="Priya Recruiter", title="Technical Recruiter"),
            build_candidate(provider_person_id="pp_m1", display_name="Morgan Manager", title="Engineering Manager"),
            build_candidate(provider_person_id="pp_e1", display_name="Jamie Engineer", title="Staff Software Engineer"),
            build_candidate(provider_person_id="pp_o1", display_name="Pat Ops", title="Program Manager"),
        ],
    )
    run_apollo_people_search(
        project_root=project_root,
        job_posting_id="jp_search",
        provider=search_provider,
    )

    shortlisted_provider_ids = {
        str(row["provider_person_id"])
        for row in connection.execute(
            """
            SELECT c.provider_person_id
            FROM job_posting_contacts jpc
            JOIN contacts c
              ON c.contact_id = jpc.contact_id
            WHERE jpc.job_posting_id = ?
              AND jpc.link_level_status = 'shortlisted'
            """,
            ("jp_search",),
        ).fetchall()
    }
    assert shortlisted_provider_ids

    enrichment_provider = FakeApolloEnrichmentProvider(
        {
            provider_person_id: {
                "person": {
                    "id": provider_person_id,
                    "first_name": provider_person_id.split("_", 1)[-1].title(),
                    "last_name": "User",
                    "name": f"{provider_person_id.split('_', 1)[-1].title()} User",
                    "linkedin_url": f"https://linkedin.example/{provider_person_id}",
                    "title": "Updated Title",
                    "email": f"{provider_person_id}@acmerobotics.com",
                    "email_status": "verified",
                    "organization_id": "org_acme",
                    "organization_name": "Acme Robotics",
                    "employment_history": [
                        {
                            "company_name": "Acme Robotics",
                            "title": "Updated Title",
                            "start_date": "2025-01-01",
                            "current": True,
                        }
                    ],
                }
            }
            for provider_person_id in ("pp_r1", "pp_r2", "pp_m1", "pp_e1", "pp_o1")
        }
    )

    run_apollo_contact_enrichment(
        project_root=project_root,
        job_posting_id="jp_search",
        provider=enrichment_provider,
        recipient_profile_extractor=FakeRecipientProfileExtractor({}),
        current_time="2026-04-06T22:30:00Z",
    )

    called_provider_ids = {str(call["provider_person_id"]) for call in enrichment_provider.calls}
    assert called_provider_ids == shortlisted_provider_ids
    enriched_profile_count = connection.execute(
        """
        SELECT COUNT(*)
        FROM contact_provider_profiles
        WHERE profile_stage = 'apollo_enrichment'
        """
    ).fetchone()[0]
    assert enriched_profile_count == len(shortlisted_provider_ids)
    enriched_history_count = connection.execute(
        """
        SELECT COUNT(*)
        FROM contact_employment_history
        WHERE provider_name = 'apollo'
        """
    ).fetchone()[0]
    assert enriched_history_count == len(shortlisted_provider_ids)

    connection.close()


def test_apollo_contact_enrichment_keeps_shortlisted_contacts_when_apollo_returns_no_email(
    tmp_path: Path,
):
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
            build_candidate(provider_person_id="pp_m1", display_name="Morgan Manager", title="Engineering Manager"),
            build_candidate(provider_person_id="pp_m2", display_name="Avery Director", title="Director of Engineering"),
        ],
    )
    run_apollo_people_search(
        project_root=project_root,
        job_posting_id="jp_search",
        provider=search_provider,
    )

    enrichment_provider = FakeApolloEnrichmentProvider(
        {
            "pp_m1": {
                "person": {
                    "id": "pp_m1",
                    "first_name": "Morgan",
                    "last_name": "Manager",
                    "name": "Morgan Manager",
                    "linkedin_url": "https://linkedin.example/pp_m1",
                    "title": "Engineering Manager",
                    "email": None,
                    "email_status": "unavailable",
                    "organization_id": "org_acme",
                    "organization_name": "Acme Robotics",
                }
            },
            "pp_m2": {
                "person": {
                    "id": "pp_m2",
                    "first_name": "Avery",
                    "last_name": "Director",
                    "name": "Avery Director",
                    "linkedin_url": "https://linkedin.example/pp_m2",
                    "title": "Director of Engineering",
                    "email": None,
                    "email_status": "unavailable",
                    "organization_id": "org_acme",
                    "organization_name": "Acme Robotics",
                }
            },
        }
    )

    result = run_apollo_contact_enrichment(
        project_root=project_root,
        job_posting_id="jp_search",
        provider=enrichment_provider,
        recipient_profile_extractor=FakeRecipientProfileExtractor({}),
        current_time="2026-04-06T22:30:00Z",
    )

    enriched_rows = connection.execute(
        """
        SELECT c.provider_person_id, c.contact_status, c.discovery_summary, jpc.link_level_status
        FROM contacts c
        JOIN job_posting_contacts jpc
          ON jpc.contact_id = c.contact_id
        WHERE jpc.job_posting_id = 'jp_search'
        ORDER BY c.provider_person_id ASC
        """
    ).fetchall()
    assert [dict(row) for row in enriched_rows] == [
        {
            "provider_person_id": "pp_m1",
            "contact_status": CONTACT_STATUS_IDENTIFIED,
            "discovery_summary": "Apollo enrichment matched this contact as `Engineering Manager`.",
            "link_level_status": POSTING_CONTACT_STATUS_SHORTLISTED,
        },
        {
            "provider_person_id": "pp_m2",
            "contact_status": CONTACT_STATUS_IDENTIFIED,
            "discovery_summary": "Apollo enrichment matched this contact as `Director of Engineering`.",
            "link_level_status": POSTING_CONTACT_STATUS_SHORTLISTED,
        },
    ]
    assert result.posting_status == "requires_contacts"

    connection.close()


def test_apollo_contact_enrichment_refreshes_stale_other_internal_to_engineer_for_send_set(
    tmp_path: Path,
):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_search_ready_posting(connection, paths)

    timestamp = "2026-04-06T21:25:00Z"
    connection.execute(
        """
        INSERT INTO contacts (
          contact_id, identity_key, display_name, company_name, origin_component, contact_status,
          provider_name, provider_person_id, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "ct_mgr",
            "apollo_person|pp_m1",
            "Morgan Manager",
            "Acme Robotics",
            "lead_ingestion",
            CONTACT_STATUS_IDENTIFIED,
            PROVIDER_NAME_APOLLO,
            "pp_m1",
            timestamp,
            timestamp,
        ),
    )
    connection.execute(
        """
        INSERT INTO contacts (
          contact_id, identity_key, display_name, company_name, origin_component, contact_status,
          provider_name, provider_person_id, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "ct_eng",
            "apollo_person|pp_e1",
            "Jamie Internal",
            "Acme Robotics",
            "lead_ingestion",
            CONTACT_STATUS_IDENTIFIED,
            PROVIDER_NAME_APOLLO,
            "pp_e1",
            timestamp,
            timestamp,
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
            "jpc_mgr",
            "jp_search",
            "ct_mgr",
            RECIPIENT_TYPE_HIRING_MANAGER,
            "Seeded as manager.",
            POSTING_CONTACT_STATUS_SHORTLISTED,
            timestamp,
            timestamp,
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
            "jpc_eng",
            "jp_search",
            "ct_eng",
            RECIPIENT_TYPE_OTHER_INTERNAL,
            "Seeded as generic internal from source-time carry-forward.",
            POSTING_CONTACT_STATUS_SHORTLISTED,
            timestamp,
            timestamp,
        ),
    )
    connection.commit()

    enrichment_provider = FakeApolloEnrichmentProvider(
        {
            "pp_m1": {
                "person": {
                    "id": "pp_m1",
                    "first_name": "Morgan",
                    "last_name": "Manager",
                    "name": "Morgan Manager",
                    "linkedin_url": "https://linkedin.example/pp_m1",
                    "title": "Engineering Manager",
                    "email": None,
                    "email_status": "unavailable",
                    "organization_id": "org_acme",
                    "organization_name": "Acme Robotics",
                }
            },
            "pp_e1": {
                "person": {
                    "id": "pp_e1",
                    "first_name": "Jamie",
                    "last_name": "Engineer",
                    "name": "Jamie Engineer",
                    "linkedin_url": "https://linkedin.example/pp_e1",
                    "title": "Staff Software Engineer",
                    "email": "jamie@acmerobotics.com",
                    "email_status": "verified",
                    "organization_id": "org_acme",
                    "organization_name": "Acme Robotics",
                }
            },
        }
    )

    result = run_apollo_contact_enrichment(
        project_root=project_root,
        job_posting_id="jp_search",
        provider=enrichment_provider,
        recipient_profile_extractor=FakeRecipientProfileExtractor({}),
        current_time="2026-04-06T22:30:00Z",
    )

    engineer_link = connection.execute(
        """
        SELECT recipient_type, relevance_reason
        FROM job_posting_contacts
        WHERE job_posting_contact_id = 'jpc_eng'
        """
    ).fetchone()
    assert dict(engineer_link) == {
        "recipient_type": RECIPIENT_TYPE_ENGINEER,
        "relevance_reason": "Apollo title indicates a role-relevant internal engineer.",
    }

    send_set = evaluate_role_targeted_send_set(
        connection,
        job_posting_id="jp_search",
        current_time="2026-04-06T22:30:00Z",
    )
    assert send_set.ready_for_outreach is True
    assert send_set.posting_status_after_evaluation == "ready_for_outreach"
    assert any(contact.contact_id == "ct_eng" and contact.has_usable_email for contact in send_set.selected_contacts)

    posting_status = connection.execute(
        "SELECT posting_status FROM job_postings WHERE job_posting_id = 'jp_search'"
    ).fetchone()[0]
    assert posting_status == "ready_for_outreach"
    assert result.posting_status == "ready_for_outreach"

    connection.close()


def test_evaluate_send_set_self_heals_stale_other_internal_from_apollo_title(tmp_path: Path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_search_ready_posting(connection, paths)

    timestamp = "2026-04-06T21:25:00Z"
    connection.execute(
        """
        INSERT INTO contacts (
          contact_id, identity_key, display_name, company_name, origin_component, contact_status,
          position_title, apollo_current_title, current_working_email, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "ct_stale",
            "contact|stale",
            "Jamie Internal",
            "Acme Robotics",
            "lead_ingestion",
            CONTACT_STATUS_WORKING_EMAIL_FOUND,
            "Staff Software Engineer",
            "Staff Software Engineer",
            "jamie@acmerobotics.com",
            timestamp,
            timestamp,
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
            "jpc_stale",
            "jp_search",
            "ct_stale",
            RECIPIENT_TYPE_OTHER_INTERNAL,
            "Seeded as generic internal from source-time carry-forward.",
            POSTING_CONTACT_STATUS_SHORTLISTED,
            timestamp,
            timestamp,
        ),
    )
    connection.commit()

    send_set = evaluate_role_targeted_send_set(
        connection,
        job_posting_id="jp_search",
        current_time="2026-04-06T22:30:00Z",
    )

    refreshed_link = connection.execute(
        """
        SELECT recipient_type, relevance_reason
        FROM job_posting_contacts
        WHERE job_posting_contact_id = 'jpc_stale'
        """
    ).fetchone()
    assert dict(refreshed_link) == {
        "recipient_type": RECIPIENT_TYPE_ENGINEER,
        "relevance_reason": "Apollo enrichment title indicates a role-relevant internal engineer.",
    }
    assert send_set.ready_for_outreach is True
    assert any(contact.contact_id == "ct_stale" for contact in send_set.selected_contacts)

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
            build_candidate(provider_person_id="pp_dead", display_name="Isa***h Lo***e", title="Engineering Manager")
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


def test_apollo_people_search_uses_location_free_manager_query(tmp_path: Path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_search_ready_posting(connection, paths)
    connection.execute(
        """
        UPDATE job_postings
        SET location = 'Phoenix, AZ'
        WHERE job_posting_id = 'jp_search'
        """
    )
    connection.commit()

    provider = LocationFallbackApolloProvider(
        resolved_company=ApolloResolvedCompany(
            organization_id="org_acme",
            organization_name="Acme Robotics",
            primary_domain="acmerobotics.com",
        ),
        candidates=[
            build_candidate(
                provider_person_id="pp_relaxed",
                display_name="Priya Director",
                title="Director of Engineering",
            )
        ],
    )

    result = run_apollo_people_search(
        project_root=project_root,
        job_posting_id="jp_search",
        provider=provider,
    )

    assert len(provider.search_calls) == 4
    assert all(call["search_filters"]["locations"] == [] for call in provider.search_calls)
    payload = json.loads(result.artifact_path.read_text(encoding="utf-8"))
    assert payload["candidate_count"] == 1
    assert len(payload["attempted_filters"]) == 4
    assert payload["applied_filters"]["locations"] == []
    assert len(result.shortlisted_contact_ids) == 1

    connection.close()


def test_apollo_people_search_omits_broad_remote_location_filters(tmp_path: Path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_search_ready_posting(connection, paths)
    connection.execute(
        """
        UPDATE job_postings
        SET location = 'Remote, United States'
        WHERE job_posting_id = 'jp_search'
        """
    )
    connection.commit()

    provider = LocationFallbackApolloProvider(
        resolved_company=ApolloResolvedCompany(
            organization_id="org_acme",
            organization_name="Acme Robotics",
            primary_domain="acmerobotics.com",
        ),
        candidates=[
            build_candidate(
                provider_person_id="pp_remote",
                display_name="Priya Recruiter",
                title="Technical Recruiter",
            )
        ],
    )

    result = run_apollo_people_search(
        project_root=project_root,
        job_posting_id="jp_search",
        provider=provider,
    )

    assert len(provider.search_calls) == 4
    assert all(call["search_filters"]["locations"] == [] for call in provider.search_calls)
    payload = json.loads(result.artifact_path.read_text(encoding="utf-8"))
    assert len(payload["attempted_filters"]) == 4
    assert payload["applied_filters"]["locations"] == []

    connection.close()


def test_apollo_people_search_persists_provider_cooldown_on_quota_exhaustion(tmp_path: Path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_search_ready_posting(connection, paths)

    with pytest.raises(EmailDiscoveryError, match="HTTP 422"):
        run_apollo_people_search(
            project_root=project_root,
            job_posting_id="jp_search",
            provider=QuotaExhaustedApolloProvider(resolved_company=None, candidates=[]),
            current_time="2026-04-06T21:45:00Z",
        )

    budget_row = connection.execute(
        """
        SELECT provider_name, cooldown_until, cooldown_reason
        FROM provider_budget_state
        WHERE provider_name = 'apollo'
        """
    ).fetchone()
    event_rows = [
        dict(row)
        for row in connection.execute(
            """
            SELECT provider_name, event_type, remaining_credits_after
            FROM provider_budget_events
            WHERE provider_name = 'apollo'
            ORDER BY created_at ASC, provider_budget_event_id ASC
            """
        ).fetchall()
    ]
    assert dict(budget_row) == {
        "provider_name": "apollo",
        "cooldown_until": "2026-04-07T21:45:00Z",
        "cooldown_reason": DISCOVERY_OUTCOME_QUOTA_EXHAUSTED,
    }
    assert event_rows == [
        {
            "provider_name": "apollo",
            "event_type": DISCOVERY_OUTCOME_QUOTA_EXHAUSTED,
            "remaining_credits_after": None,
        }
    ]

    connection.close()


def test_normalize_apollo_usage_snapshots_parses_usage_stats_endpoint_payload():
    payload = {
        "data": [
            {
                "api_route": ["api/v1/mixed_companies", "search"],
                "day": {"limit": 2000, "consumed": 1259, "left_over": 741},
                "hour": {"limit": 200, "consumed": 27, "left_over": 173},
                "minute": {"limit": 20, "consumed": 2, "left_over": 18},
            },
            {
                "api_route": ["api/v1/mixed_people", "api_search"],
                "day": {"consumed": 1317},
            },
        ]
    }

    snapshots = _normalize_apollo_usage_snapshots(
        payload,
        observed_at="2026-06-10T20:00:00Z",
    )

    assert [snapshot.endpoint_key for snapshot in snapshots] == [
        APOLLO_USAGE_ENDPOINT_COMPANY_SEARCH,
        "api/v1/mixed_people/api_search",
    ]
    assert snapshots[0].day_limit == 2000
    assert snapshots[0].day_consumed == 1259
    assert snapshots[0].hour_consumed == 27
    assert snapshots[0].minute_left_over == 18
    assert snapshots[1].day_consumed == 1317


def test_apollo_usage_guardrail_trips_before_company_resolution_when_daily_cap_is_exceeded(tmp_path: Path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_search_ready_posting(connection, paths)
    provider = UsageStatsApolloProvider(
        resolved_company=None,
        candidates=[],
        usage_stats_payload={
            "data": [
                {
                    "api_route": ["api/v1/mixed_companies", "search"],
                    "day": {"limit": 2000, "consumed": 125, "left_over": 1875},
                    "hour": {"limit": 200, "consumed": 4, "left_over": 196},
                }
            ]
        },
    )

    with pytest.raises(EmailDiscoveryError) as exc_info:
        run_apollo_people_search(
            project_root=project_root,
            job_posting_id="jp_search",
            provider=provider,
            current_time="2026-06-10T20:05:00Z",
        )

    assert exc_info.value.reason_code == DISCOVERY_OUTCOME_PROVIDER_PAUSED
    assert provider.fetch_usage_stats_calls == 1
    assert provider.resolve_calls == []
    assert provider.search_calls == []

    usage_rows = [
        dict(row)
        for row in connection.execute(
            """
            SELECT endpoint_key, day_consumed, observed_at
            FROM provider_usage_snapshots
            ORDER BY observed_at ASC, provider_usage_snapshot_id ASC
            """
        ).fetchall()
    ]
    budget_row = connection.execute(
        """
        SELECT breaker_state, breaker_reason, last_usage_checked_at
        FROM provider_budget_state
        WHERE provider_name = 'apollo'
        """
    ).fetchone()
    control_rows = {
        row["control_key"]: row["control_value"]
        for row in connection.execute(
            """
            SELECT control_key, control_value
            FROM agent_control_state
            WHERE control_key IN (
              'apollo_discovery_paused',
              'apollo_discovery_pause_reason',
              'apollo_discovery_pause_until'
            )
            """
        ).fetchall()
    }
    incident_row = connection.execute(
        """
        SELECT incident_type, summary
        FROM agent_incidents
        ORDER BY created_at DESC, agent_incident_id DESC
        LIMIT 1
        """
    ).fetchone()

    assert usage_rows == [
        {
            "endpoint_key": APOLLO_USAGE_ENDPOINT_COMPANY_SEARCH,
            "day_consumed": 125,
            "observed_at": "2026-06-10T20:05:00Z",
        }
    ]
    assert dict(budget_row) == {
        "breaker_state": "open",
        "breaker_reason": "daily_usage_hard_cap",
        "last_usage_checked_at": "2026-06-10T20:05:00Z",
    }
    assert control_rows["apollo_discovery_paused"] == "true"
    assert "daily cap 100" in control_rows["apollo_discovery_pause_reason"]
    assert incident_row["incident_type"] == "provider_spend_guardrail"

    connection.close()


def test_apollo_provider_error_guardrail_trips_after_three_consecutive_failures(tmp_path: Path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_search_ready_posting(connection, paths)
    provider = ProviderErrorApolloProvider(resolved_company=None, candidates=[])

    for timestamp in (
        "2026-06-10T20:10:00Z",
        "2026-06-10T20:20:00Z",
        "2026-06-10T20:29:00Z",
    ):
        with pytest.raises(EmailDiscoveryError) as exc_info:
            run_apollo_people_search(
                project_root=project_root,
                job_posting_id="jp_search",
                provider=provider,
                current_time=timestamp,
            )
        assert exc_info.value.reason_code == DISCOVERY_OUTCOME_PROVIDER_ERROR

    budget_row = connection.execute(
        """
        SELECT breaker_state, breaker_reason
        FROM provider_budget_state
        WHERE provider_name = 'apollo'
        """
    ).fetchone()
    control_rows = {
        row["control_key"]: row["control_value"]
        for row in connection.execute(
            """
            SELECT control_key, control_value
            FROM agent_control_state
            WHERE control_key IN ('apollo_discovery_paused', 'apollo_discovery_pause_reason')
            """
        ).fetchall()
    }
    provider_error_events = connection.execute(
        """
        SELECT COUNT(*)
        FROM provider_budget_events
        WHERE provider_name = 'apollo'
          AND event_type = ?
        """,
        (DISCOVERY_OUTCOME_PROVIDER_ERROR,),
    ).fetchone()[0]

    assert len(provider.resolve_calls) == 3
    assert dict(budget_row) == {
        "breaker_state": "open",
        "breaker_reason": "consecutive_provider_errors",
    }
    assert control_rows["apollo_discovery_paused"] == "true"
    assert "3 consecutive provider_error outcomes" in control_rows["apollo_discovery_pause_reason"]
    assert provider_error_events == 3

    connection.close()


def test_apollo_pre_call_guard_blocks_outbound_calls_while_breaker_is_active(tmp_path: Path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_search_ready_posting(connection, paths)
    connection.execute(
        """
        INSERT INTO provider_budget_state (
          provider_name, breaker_state, breaker_reason, breaker_message,
          breaker_until, breaker_set_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "apollo",
            "open",
            "manual_test_pause",
            "Apollo abnormal-usage guardrail is active.",
            "2026-06-10T23:00:00Z",
            "2026-06-10T20:00:00Z",
            "2026-06-10T20:00:00Z",
        ),
    )
    connection.commit()
    provider = FakeApolloProvider(resolved_company=None, candidates=[])

    with pytest.raises(EmailDiscoveryError) as exc_info:
        run_apollo_people_search(
            project_root=project_root,
            job_posting_id="jp_search",
            provider=provider,
            current_time="2026-06-10T20:15:00Z",
        )

    assert exc_info.value.reason_code == DISCOVERY_OUTCOME_PROVIDER_PAUSED
    assert provider.resolve_calls == []
    assert provider.search_calls == []

    connection.close()


def test_configured_apollo_client_sends_custom_user_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_headers: list[dict[str, str]] = []

    def fake_request_json(request, *, timeout_seconds, provider_label, http_error_map):
        captured_headers.append(dict(request.header_items()))
        return {}

    monkeypatch.setattr("job_hunt_copilot.email_discovery._request_json", fake_request_json)
    client = ConfiguredApolloClient(api_key="apollo-key")

    client._post_json("https://api.apollo.io/api/v1/mixed_companies/search", {"page": 1})
    client._post_query("https://api.apollo.io/api/v1/people/match", {"id": "person_123"})

    assert len(captured_headers) == 2
    assert captured_headers[0]["User-agent"] == APOLLO_API_USER_AGENT
    assert captured_headers[1]["User-agent"] == APOLLO_API_USER_AGENT


def test_configured_apollo_client_maps_insufficient_credit_422_to_quota_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(request, timeout):
        raise HTTPError(
            url=request.full_url,
            code=422,
            msg="Unprocessable Entity",
            hdrs=None,
            fp=BytesIO(b'{"message":"insufficient credits"}'),
        )

    monkeypatch.setattr("job_hunt_copilot.email_discovery.urlopen", fake_urlopen)
    client = ConfiguredApolloClient(api_key="apollo-key")

    with pytest.raises(EmailDiscoveryError) as exc_info:
        client._post_json("https://api.apollo.io/api/v1/mixed_companies/search", {"page": 1})

    assert exc_info.value.reason_code == DISCOVERY_OUTCOME_QUOTA_EXHAUSTED


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


def test_email_discovery_promotes_posting_when_ready_subset_exists_but_other_contacts_still_pending(
    tmp_path: Path,
):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_search_ready_posting(connection, paths)
    seed_linked_contact(
        connection,
        contact_id="ct_ready",
        job_posting_contact_id="jpc_ready",
        display_name="Priya Engineer",
        full_name="Priya Engineer",
        first_name="Priya",
        last_name="Engineer",
        linkedin_url="https://linkedin.example/priya",
        position_title="Software Engineer",
        recipient_type=RECIPIENT_TYPE_ENGINEER,
        provider_person_id="pp_ready",
        identity_key="apollo_person|pp_ready",
        created_at="2026-04-06T21:30:00Z",
    )
    seed_linked_contact(
        connection,
        contact_id="ct_pending",
        job_posting_contact_id="jpc_pending",
        display_name="Morgan Manager",
        full_name="Morgan Manager",
        first_name="Morgan",
        last_name="Manager",
        linkedin_url="https://linkedin.example/morgan",
        position_title="Engineering Manager",
        recipient_type=RECIPIENT_TYPE_HIRING_MANAGER,
        provider_person_id="pp_pending",
        identity_key="apollo_person|pp_pending",
        created_at="2026-04-06T21:31:00Z",
    )

    finder = FakeEmailFinderProvider(
        provider_name="getprospect",
        responses=[
            {
                "outcome": "found",
                "email": "priya@acmerobotics.com",
                "provider_verification_status": "valid",
                "provider_score": "0.94",
                "detected_pattern": "first",
            }
        ],
    )

    result = run_email_discovery_for_contact(
        project_root=project_root,
        job_posting_id="jp_search",
        contact_id="ct_ready",
        providers=(finder,),
        current_time="2026-04-06T21:46:00Z",
    )

    posting_status = connection.execute(
        "SELECT posting_status FROM job_postings WHERE job_posting_id = 'jp_search'"
    ).fetchone()[0]
    pending_row = connection.execute(
        """
        SELECT current_working_email, contact_status
        FROM contacts
        WHERE contact_id = 'ct_pending'
        """
    ).fetchone()

    assert len(finder.calls) == 1
    assert result.outcome == "found"
    assert result.posting_status == "ready_for_outreach"
    assert posting_status == "ready_for_outreach"
    assert dict(pending_row) == {
        "current_working_email": None,
        "contact_status": CONTACT_STATUS_IDENTIFIED,
    }

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
        responses=[{"outcome": DISCOVERY_OUTCOME_DOMAIN_UNRESOLVED}],
    )
    getprospect = FakeEmailFinderProvider(
        provider_name="getprospect",
        requires_domain=True,
        responses=[{"outcome": DISCOVERY_OUTCOME_DOMAIN_UNRESOLVED}],
    )
    hunter = FakeEmailFinderProvider(
        provider_name="hunter",
        responses=[
            {
                "outcome": "network_error",
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
    assert len(prospeo.calls) == 1
    assert len(getprospect.calls) == 1
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


def test_email_discovery_does_not_exhaust_contact_when_transient_provider_failure_remains(tmp_path: Path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_search_ready_posting(
        connection,
        paths,
        source_url="https://www.linkedin.com/jobs/view/123",
    )
    seed_linked_contact(connection, linkedin_url=None, provider_person_id=None, identity_key="manual|maya")

    providers = (
        FakeEmailFinderProvider(
            provider_name="prospeo",
            requires_domain=True,
            responses=[{"outcome": DISCOVERY_OUTCOME_DOMAIN_UNRESOLVED}],
        ),
        FakeEmailFinderProvider(
            provider_name="getprospect",
            requires_domain=True,
            responses=[{"outcome": DISCOVERY_OUTCOME_DOMAIN_UNRESOLVED}],
        ),
        FakeEmailFinderProvider(
            provider_name="hunter",
            responses=[
                {
                    "outcome": "rate_limited",
                    "remaining_credits": 0,
                    "credit_limit": 50,
                }
            ],
        ),
    )

    result = run_email_discovery_for_contact(
        project_root=project_root,
        job_posting_id="jp_search",
        contact_id="ct_target",
        providers=providers,
        current_time="2026-04-06T21:47:30Z",
    )

    assert result.outcome == DISCOVERY_OUTCOME_DOMAIN_UNRESOLVED
    contact_row = connection.execute(
        """
        SELECT contact_status, discovery_summary
        FROM contacts
        WHERE contact_id = 'ct_target'
        """
    ).fetchone()
    assert dict(contact_row) == {
        "contact_status": CONTACT_STATUS_IDENTIFIED,
        "discovery_summary": DISCOVERY_OUTCOME_DOMAIN_UNRESOLVED,
    }

    link_row = connection.execute(
        """
        SELECT link_level_status
        FROM job_posting_contacts
        WHERE job_posting_contact_id = 'jpc_target'
        """
    ).fetchone()
    assert link_row["link_level_status"] == POSTING_CONTACT_STATUS_SHORTLISTED

    hunter_budget_row = connection.execute(
        """
        SELECT provider_name, remaining_credits, credit_limit, cooldown_until, cooldown_reason
        FROM provider_budget_state
        WHERE provider_name = 'hunter'
        """
    ).fetchone()
    assert dict(hunter_budget_row) == {
        "provider_name": "hunter",
        "remaining_credits": 0,
        "credit_limit": 50,
        "cooldown_until": "2026-04-06T22:02:30Z",
        "cooldown_reason": DISCOVERY_OUTCOME_RATE_LIMITED,
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


def test_email_discovery_persists_provider_cooldown_for_transient_provider_unavailability(tmp_path: Path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_search_ready_posting(
        connection,
        paths,
        source_url="https://www.linkedin.com/jobs/view/123",
    )
    seed_linked_contact(connection)

    providers = (
        FakeEmailFinderProvider(
            provider_name="prospeo",
            responses=[
                {
                    "outcome": DISCOVERY_OUTCOME_RATE_LIMITED,
                    "remaining_credits": 12,
                    "credit_limit": 100,
                }
            ],
            requires_domain=False,
        ),
        FakeEmailFinderProvider(
            provider_name="getprospect",
            responses=[
                {
                    "outcome": DISCOVERY_OUTCOME_PROVIDER_ERROR,
                    "message": "GetProspect request failed with HTTP 403.",
                }
            ],
            requires_domain=False,
        ),
        FakeEmailFinderProvider(
            provider_name="hunter",
            responses=[
                {
                    "outcome": DISCOVERY_OUTCOME_QUOTA_EXHAUSTED,
                    "remaining_credits": 0,
                    "credit_limit": 50,
                    "reset_at": "2026-04-07T00:00:00Z",
                }
            ],
            requires_domain=False,
        ),
    )

    result = run_email_discovery_for_contact(
        project_root=project_root,
        job_posting_id="jp_search",
        contact_id="ct_target",
        providers=providers,
        current_time="2026-04-06T21:48:00Z",
    )

    contact_row = connection.execute(
        """
        SELECT contact_status, discovery_summary
        FROM contacts
        WHERE contact_id = 'ct_target'
        """
    ).fetchone()
    link_row = connection.execute(
        """
        SELECT link_level_status
        FROM job_posting_contacts
        WHERE job_posting_contact_id = 'jpc_target'
        """
    ).fetchone()
    budget_rows = [
        dict(row)
        for row in connection.execute(
            """
            SELECT provider_name, cooldown_until, cooldown_reason
            FROM provider_budget_state
            ORDER BY provider_name ASC
            """
        ).fetchall()
    ]

    assert result.outcome == DISCOVERY_OUTCOME_QUOTA_EXHAUSTED
    assert dict(contact_row) == {
        "contact_status": CONTACT_STATUS_IDENTIFIED,
        "discovery_summary": DISCOVERY_OUTCOME_QUOTA_EXHAUSTED,
    }
    assert link_row["link_level_status"] == POSTING_CONTACT_STATUS_SHORTLISTED
    assert budget_rows == [
        {
            "provider_name": "getprospect",
            "cooldown_until": "2026-04-06T22:03:00Z",
            "cooldown_reason": DISCOVERY_OUTCOME_PROVIDER_ERROR,
        },
        {
            "provider_name": "hunter",
            "cooldown_until": "2026-04-07T00:00:00Z",
            "cooldown_reason": DISCOVERY_OUTCOME_QUOTA_EXHAUSTED,
        },
        {
            "provider_name": "prospeo",
            "cooldown_until": "2026-04-06T22:03:00Z",
            "cooldown_reason": DISCOVERY_OUTCOME_RATE_LIMITED,
        },
    ]

    connection.close()


def test_email_discovery_uses_resolved_company_domain_from_people_search_payload(tmp_path: Path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_search_ready_posting(
        connection,
        paths,
        source_url="https://www.linkedin.com/jobs/view/123",
    )
    seed_linked_contact(
        connection,
        linkedin_url=None,
        full_name="Maya Rivera",
        first_name="Maya",
        last_name="Rivera",
    )
    people_search_path = (
        paths.discovery_workspace_dir("Acme Robotics", "Staff Software Engineer / AI")
        / "people_search_result.json"
    )
    people_search_path.parent.mkdir(parents=True, exist_ok=True)
    people_search_path.write_text(
        json.dumps(
            {
                "resolved_company": {
                    "organization_id": "org_acme",
                    "organization_name": "Acme Robotics",
                    "primary_domain": "acmerobotics.com",
                }
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    prospeo = FakeEmailFinderProvider(
        provider_name="prospeo",
        requires_domain=True,
        responses=[{"outcome": DISCOVERY_OUTCOME_NOT_FOUND}],
    )
    getprospect = FakeEmailFinderProvider(
        provider_name="getprospect",
        requires_domain=True,
        responses=[
            {
                "outcome": "found",
                "email": "maya@acmerobotics.com",
                "provider_verification_status": "verified",
            }
        ],
    )
    hunter = FakeEmailFinderProvider(provider_name="hunter", responses=[])

    result = run_email_discovery_for_contact(
        project_root=project_root,
        job_posting_id="jp_search",
        contact_id="ct_target",
        providers=(prospeo, getprospect, hunter),
        current_time="2026-04-06T21:47:45Z",
    )

    assert result.outcome == "found"
    assert result.email == "maya@acmerobotics.com"
    assert prospeo.calls == [
        {
            "contact_id": "ct_target",
            "job_posting_id": "jp_search",
            "company_domain": "acmerobotics.com",
            "company_name": "Acme Robotics",
        }
    ]
    assert getprospect.calls == [
        {
            "contact_id": "ct_target",
            "job_posting_id": "jp_search",
            "company_domain": "acmerobotics.com",
            "company_name": "Acme Robotics",
        }
    ]
    assert hunter.calls == []

    connection.close()


def test_email_discovery_runs_prospeo_with_linkedin_url_without_company_domain(tmp_path: Path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_search_ready_posting(
        connection,
        paths,
        source_url="https://www.linkedin.com/jobs/view/123",
    )
    seed_linked_contact(connection)

    prospeo = FakeEmailFinderProvider(
        provider_name="prospeo",
        requires_domain=True,
        responses=[
            {
                "outcome": "found",
                "email": "maya@acmerobotics.com",
                "provider_verification_status": "verified",
            }
        ],
    )
    getprospect = FakeEmailFinderProvider(provider_name="getprospect", requires_domain=True, responses=[])
    hunter = FakeEmailFinderProvider(provider_name="hunter", responses=[])

    result = run_email_discovery_for_contact(
        project_root=project_root,
        job_posting_id="jp_search",
        contact_id="ct_target",
        providers=(prospeo, getprospect, hunter),
        current_time="2026-04-06T21:47:50Z",
    )

    assert result.outcome == "found"
    assert result.email == "maya@acmerobotics.com"
    assert prospeo.calls == [
        {
            "contact_id": "ct_target",
            "job_posting_id": "jp_search",
            "company_domain": None,
            "company_name": "Acme Robotics",
        }
    ]
    assert getprospect.calls == []
    assert hunter.calls == []

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


def test_shortlist_existing_intended_contacts_prefers_apollo_before_jobright(tmp_path: Path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_search_ready_posting(connection, paths)
    seed_linked_contact(
        connection,
        contact_id="ct_jobright_priority",
        job_posting_contact_id="jpc_jobright_priority",
        display_name="Jobright Contact",
        recipient_type=RECIPIENT_TYPE_HIRING_MANAGER,
        provider_name=None,
        provider_person_id=None,
        identity_key="jobright|priority",
        contact_source_type="jobright_public",
        contact_source_priority_tier=2,
        contact_source_rank=1,
        link_level_status=POSTING_CONTACT_STATUS_IDENTIFIED,
        is_in_intended_outreach_set=1,
        created_at="2026-04-06T21:01:00Z",
    )
    seed_linked_contact(
        connection,
        contact_id="ct_apollo_priority",
        job_posting_contact_id="jpc_apollo_priority",
        display_name="Apollo Contact",
        recipient_type=RECIPIENT_TYPE_HIRING_MANAGER,
        provider_name=None,
        provider_person_id=None,
        identity_key="apollo|priority",
        contact_source_type="apollo_topup",
        contact_source_priority_tier=3,
        contact_source_rank=1,
        link_level_status=POSTING_CONTACT_STATUS_IDENTIFIED,
        is_in_intended_outreach_set=1,
        created_at="2026-04-06T21:02:00Z",
    )

    shortlisted = _shortlist_existing_intended_contacts(
        connection,
        job_posting_id="jp_search",
        current_time="2026-04-06T21:05:00Z",
    )

    assert [row["contact_id"] for row in shortlisted[:2]] == [
        "ct_apollo_priority",
        "ct_jobright_priority",
    ]
    connection.close()
