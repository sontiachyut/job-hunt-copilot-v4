from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from job_hunt_copilot.bootstrap import run_bootstrap
from job_hunt_copilot.outreach import generate_role_targeted_send_set_drafts
from job_hunt_copilot.paths import ProjectPaths
from job_hunt_copilot.supervisor import (
    ACTION_PERFORM_MANDATORY_AGENT_REVIEW,
    ACTION_RUN_ROLE_TARGETED_EMAIL_DISCOVERY,
    ACTION_RUN_ROLE_TARGETED_PEOPLE_SEARCH,
    ACTION_RUN_ROLE_TARGETED_SENDING,
    REVIEW_PACKET_STATUS_PENDING,
    RUN_STATUS_COMPLETED,
    RUN_STATUS_ESCALATED,
    RUN_STATUS_IN_PROGRESS,
    SupervisorActionDependencies,
    SUPERVISOR_CYCLE_RESULT_FAILED,
    SUPERVISOR_CYCLE_RESULT_NO_WORK,
    SUPERVISOR_CYCLE_RESULT_SUCCESS,
    advance_pipeline_run,
    ensure_role_targeted_pipeline_run,
    escalate_agent_incident,
    get_pipeline_run,
    list_expert_review_packets_for_run,
    resume_agent,
    run_supervisor_cycle,
)
from tests.support import create_minimal_project, seed_pending_review_tailoring_run
from tests.test_outreach import (
    ImmediateBounceObserver as OutreachImmediateBounceObserver,
    RecordingOutreachSender as OutreachRecordingSender,
    seed_approved_tailoring_run as seed_outreach_ready_tailoring_run,
    write_sender_profile,
)


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


def seed_role_targeted_posting(
    connection: sqlite3.Connection,
    *,
    lead_id: str = "ld_downstream",
    job_posting_id: str = "jp_downstream",
    lead_identity_key: str = "acme|platform-engineer",
    posting_identity_key: str = "acme|platform-engineer|remote",
    company_name: str = "Acme",
    role_title: str = "Platform Engineer",
    posting_status: str = "resume_review_pending",
    timestamp: str = "2026-04-08T00:00:00Z",
) -> tuple[str, str]:
    connection.execute(
        """
        INSERT INTO linkedin_leads (
          lead_id, lead_identity_key, lead_status, lead_shape, split_review_status,
          source_type, source_reference, source_mode, company_name, role_title,
          created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            lead_id,
            lead_identity_key,
            "reviewed",
            "posting_plus_contacts",
            "confident",
            "manual_paste",
            "paste/paste.txt",
            "manual_paste",
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
          posting_status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job_posting_id,
            lead_id,
            posting_identity_key,
            company_name,
            role_title,
            posting_status,
            timestamp,
            timestamp,
        ),
    )
    connection.commit()
    return lead_id, job_posting_id


def seed_approved_tailoring_run(
    connection: sqlite3.Connection,
    *,
    job_posting_id: str,
    timestamp: str = "2026-04-08T00:00:00Z",
) -> None:
    connection.execute(
        """
        INSERT INTO resume_tailoring_runs (
          resume_tailoring_run_id, job_posting_id, base_used, tailoring_status,
          resume_review_status, workspace_path, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            f"rtr_{job_posting_id}",
            job_posting_id,
            "generalist",
            "tailored",
            "approved",
            "resume-tailoring/output/tailored/acme/platform-engineer",
            timestamp,
            timestamp,
        ),
    )
    connection.commit()


def seed_general_learning_contact(
    connection: sqlite3.Connection,
    *,
    timestamp: str = "2026-04-08T00:00:00Z",
) -> str:
    connection.execute(
        """
        INSERT INTO contacts (
          contact_id, identity_key, display_name, company_name, origin_component,
          contact_status, full_name, first_name, last_name, current_working_email,
          created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "ct_general_learning",
            "acme|sam-learner",
            "Sam Learner",
            "Acme",
            "manual_capture",
            "identified",
            "Sam Learner",
            "Sam",
            "Learner",
            "sam.learner@acme.example",
            timestamp,
            timestamp,
        ),
    )
    connection.commit()
    return "ct_general_learning"


def seed_shortlisted_contact(
    connection: sqlite3.Connection,
    *,
    contact_id: str,
    job_posting_contact_id: str,
    job_posting_id: str = "jp_downstream",
    company_name: str = "Acme",
    display_name: str,
    recipient_type: str,
    current_working_email: str | None = None,
    contact_status: str = "identified",
    link_level_status: str = "shortlisted",
    position_title: str | None = None,
    provider_person_id: str | None = None,
    created_at: str = "2026-04-08T00:00:00Z",
) -> None:
    connection.execute(
        """
        INSERT INTO contacts (
          contact_id, identity_key, display_name, company_name, origin_component, contact_status,
          full_name, current_working_email, position_title, provider_person_id, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            contact_id,
            f"{company_name.lower()}|{display_name.lower().replace(' ', '-')}",
            display_name,
            company_name,
            "email_discovery",
            contact_status,
            display_name,
            current_working_email,
            position_title,
            provider_person_id,
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
            "Selected for bounded supervisor discovery coverage.",
            link_level_status,
            created_at,
            created_at,
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
    last_refreshed_at: str = "2026-04-08T00:00:00Z",
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


class FakeApolloSearchProvider:
    def __init__(self, *, candidates: list[dict[str, object]]) -> None:
        self.candidates = candidates
        self.resolve_calls: list[dict[str, object | None]] = []
        self.search_calls: list[dict[str, object | None]] = []

    def resolve_company(
        self,
        *,
        company_name: str,
        company_domain: str | None,
        company_website: str | None,
    ) -> None:
        self.resolve_calls.append(
            {
                "company_name": company_name,
                "company_domain": company_domain,
                "company_website": company_website,
            }
        )
        return None

    def search_people(
        self,
        *,
        company_name: str,
        resolved_company: object | None,
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


class FakeEmailFinderProvider:
    def __init__(
        self,
        *,
        provider_name: str,
        responses: list[dict[str, object]],
        requires_domain: bool = False,
    ) -> None:
        self.provider_name = provider_name
        self.responses = list(responses)
        self.requires_domain = requires_domain
        self.calls: list[dict[str, str | None]] = []

    def discover_email(
        self,
        *,
        contact: dict[str, object],
        posting: dict[str, object],
        company_domain: str | None,
        company_name: str | None,
    ) -> dict[str, object]:
        self.calls.append(
            {
                "contact_id": str(contact.get("contact_id") or ""),
                "job_posting_id": str(posting.get("job_posting_id") or ""),
                "company_domain": company_domain,
                "company_name": company_name,
            }
        )
        if self.responses:
            return dict(self.responses.pop(0))
        return {"outcome": "not_found"}


def test_lead_handoff_advances_the_durable_run_into_agent_review(tmp_path: Path) -> None:
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    lead_id, job_posting_id = seed_role_targeted_posting(connection)
    seed_pending_review_tailoring_run(
        connection,
        paths,
        job_posting_id=job_posting_id,
        company_name="Acme",
        role_title="Platform Engineer",
    )
    resume_agent(
        connection,
        manual_command="jhc-agent-start",
        timestamp="2026-04-08T00:05:00Z",
    )
    pipeline_run, _ = ensure_role_targeted_pipeline_run(
        connection,
        lead_id=lead_id,
        job_posting_id=job_posting_id,
        current_stage="lead_handoff",
        started_at="2026-04-08T00:06:00Z",
    )

    execution = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-04-08T00:07:00Z",
    )
    updated_run = get_pipeline_run(connection, pipeline_run.pipeline_run_id)
    connection.close()

    assert execution.cycle.result == SUPERVISOR_CYCLE_RESULT_SUCCESS
    assert execution.selected_work is not None
    assert execution.selected_work.work_type == "pipeline_run"
    assert execution.selected_work.action_id == "checkpoint_pipeline_run"
    assert execution.selected_work.current_stage == "lead_handoff"
    assert updated_run is not None
    assert updated_run.pipeline_run_id == pipeline_run.pipeline_run_id
    assert updated_run.run_status == RUN_STATUS_IN_PROGRESS
    assert updated_run.current_stage == "agent_review"


def test_agent_review_stage_advances_to_people_search_after_approval(tmp_path: Path) -> None:
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    lead_id, job_posting_id = seed_role_targeted_posting(connection)
    seed_pending_review_tailoring_run(
        connection,
        paths,
        job_posting_id=job_posting_id,
        company_name="Acme",
        role_title="Platform Engineer",
    )
    resume_agent(
        connection,
        manual_command="jhc-agent-start",
        timestamp="2026-04-08T00:08:00Z",
    )
    pipeline_run, _ = ensure_role_targeted_pipeline_run(
        connection,
        lead_id=lead_id,
        job_posting_id=job_posting_id,
        current_stage="agent_review",
        started_at="2026-04-08T00:09:00Z",
    )

    execution = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-04-08T00:10:00Z",
    )
    updated_run = get_pipeline_run(connection, pipeline_run.pipeline_run_id)
    posting_row = connection.execute(
        """
        SELECT posting_status
        FROM job_postings
        WHERE job_posting_id = ?
        """,
        (job_posting_id,),
    ).fetchone()
    tailoring_row = connection.execute(
        """
        SELECT resume_review_status
        FROM resume_tailoring_runs
        WHERE job_posting_id = ?
        ORDER BY COALESCE(completed_at, updated_at, created_at, started_at) DESC,
                 resume_tailoring_run_id DESC
        LIMIT 1
        """,
        (job_posting_id,),
    ).fetchone()
    review_artifact_count = connection.execute(
        """
        SELECT COUNT(*)
        FROM artifact_records
        WHERE job_posting_id = ?
          AND artifact_type = 'tailoring_review_decision'
        """,
        (job_posting_id,),
    ).fetchone()[0]
    connection.close()

    assert execution.cycle.result == SUPERVISOR_CYCLE_RESULT_SUCCESS
    assert execution.selected_work is not None
    assert execution.selected_work.work_id == pipeline_run.pipeline_run_id
    assert execution.selected_work.action_id == ACTION_PERFORM_MANDATORY_AGENT_REVIEW
    assert execution.selected_work.current_stage == "agent_review"
    assert execution.incident is None
    assert execution.review_packet is None
    assert updated_run is not None
    assert updated_run.run_status == RUN_STATUS_IN_PROGRESS
    assert updated_run.current_stage == "people_search"
    assert posting_row is not None
    assert posting_row["posting_status"] == "requires_contacts"
    assert tailoring_row is not None
    assert tailoring_row["resume_review_status"] == "approved"
    assert review_artifact_count == 1


def test_people_search_stage_executes_and_advances_to_email_discovery(tmp_path: Path) -> None:
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    lead_id, job_posting_id = seed_role_targeted_posting(
        connection,
        posting_status="requires_contacts",
    )
    seed_approved_tailoring_run(connection, job_posting_id=job_posting_id)
    resume_agent(
        connection,
        manual_command="jhc-agent-start",
        timestamp="2026-04-08T00:10:00Z",
    )
    pipeline_run, _ = ensure_role_targeted_pipeline_run(
        connection,
        lead_id=lead_id,
        job_posting_id=job_posting_id,
        current_stage="people_search",
        started_at="2026-04-08T00:11:00Z",
    )
    search_provider = FakeApolloSearchProvider(
        candidates=[
            build_candidate(
                provider_person_id="pp_r1",
                display_name="Priya Recruiter",
                title="Technical Recruiter",
            ),
            build_candidate(
                provider_person_id="pp_m1",
                display_name="Morgan Manager",
                title="Engineering Manager",
            ),
            build_candidate(
                provider_person_id="pp_e1",
                display_name="Jamie Engineer",
                title="Staff Software Engineer",
            ),
        ]
    )
    enrichment_provider = FakeApolloEnrichmentProvider(
        {"pp_r1": None, "pp_m1": None, "pp_e1": None}
    )

    execution = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-04-08T00:12:00Z",
        action_dependencies=SupervisorActionDependencies(
            apollo_people_search_provider=search_provider,
            apollo_contact_enrichment_provider=enrichment_provider,
        ),
    )
    updated_run = get_pipeline_run(connection, pipeline_run.pipeline_run_id)
    posting_status = connection.execute(
        """
        SELECT posting_status
        FROM job_postings
        WHERE job_posting_id = ?
        """,
        (job_posting_id,),
    ).fetchone()[0]
    shortlist_rows = connection.execute(
        """
        SELECT contact_id, recipient_type, link_level_status
        FROM job_posting_contacts
        WHERE job_posting_id = ?
        ORDER BY recipient_type, contact_id
        """,
        (job_posting_id,),
    ).fetchall()
    people_search_artifact_path = connection.execute(
        """
        SELECT file_path
        FROM artifact_records
        WHERE job_posting_id = ?
          AND artifact_type = 'people_search_result'
        """,
        (job_posting_id,),
    ).fetchone()[0]
    connection.close()

    assert execution.cycle.result == SUPERVISOR_CYCLE_RESULT_SUCCESS
    assert execution.selected_work is not None
    assert execution.selected_work.work_id == pipeline_run.pipeline_run_id
    assert execution.selected_work.action_id == ACTION_RUN_ROLE_TARGETED_PEOPLE_SEARCH
    assert execution.incident is None
    assert execution.review_packet is None
    assert updated_run is not None
    assert updated_run.run_status == RUN_STATUS_IN_PROGRESS
    assert updated_run.current_stage == "email_discovery"
    assert posting_status == "requires_contacts"
    assert len(shortlist_rows) == 3
    assert {row["recipient_type"] for row in shortlist_rows} == {
        "recruiter",
        "hiring_manager",
        "engineer",
    }
    assert all(row["link_level_status"] == "shortlisted" for row in shortlist_rows)
    assert (project_root / people_search_artifact_path).exists()


def test_email_discovery_stage_runs_and_stays_active_until_send_set_is_ready(
    tmp_path: Path,
) -> None:
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    lead_id, job_posting_id = seed_role_targeted_posting(
        connection,
        posting_status="requires_contacts",
    )
    seed_approved_tailoring_run(connection, job_posting_id=job_posting_id)
    seed_shortlisted_contact(
        connection,
        contact_id="ct_discovery",
        job_posting_contact_id="jpc_discovery",
        job_posting_id=job_posting_id,
        display_name="Priya Recruiter",
        recipient_type="recruiter",
        position_title="Technical Recruiter",
        provider_person_id="pp_discovery",
    )
    resume_agent(
        connection,
        manual_command="jhc-agent-start",
        timestamp="2026-04-08T00:12:00Z",
    )
    pipeline_run, _ = ensure_role_targeted_pipeline_run(
        connection,
        lead_id=lead_id,
        job_posting_id=job_posting_id,
        current_stage="email_discovery",
        started_at="2026-04-08T00:13:00Z",
    )
    finder = FakeEmailFinderProvider(
        provider_name="prospeo",
        requires_domain=False,
        responses=[
            {
                "outcome": "not_found",
                "remaining_credits": 41,
                "credit_limit": 100,
                "reset_at": "2026-05-01T00:00:00Z",
            }
        ],
    )

    execution = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-04-08T00:14:00Z",
        action_dependencies=SupervisorActionDependencies(
            email_finder_providers=(finder,),
        ),
    )
    updated_run = get_pipeline_run(connection, pipeline_run.pipeline_run_id)
    posting_status = connection.execute(
        """
        SELECT posting_status
        FROM job_postings
        WHERE job_posting_id = ?
        """,
        (job_posting_id,),
    ).fetchone()[0]
    discovery_artifact_path = connection.execute(
        """
        SELECT file_path
        FROM artifact_records
        WHERE job_posting_id = ?
          AND artifact_type = 'discovery_result'
        """,
        (job_posting_id,),
    ).fetchone()[0]
    connection.close()

    assert execution.cycle.result == SUPERVISOR_CYCLE_RESULT_SUCCESS
    assert execution.selected_work is not None
    assert execution.selected_work.work_id == pipeline_run.pipeline_run_id
    assert execution.selected_work.action_id == ACTION_RUN_ROLE_TARGETED_EMAIL_DISCOVERY
    assert execution.selected_work.current_stage == "email_discovery"
    assert execution.incident is None
    assert execution.review_packet is None
    assert len(finder.calls) == 1
    assert updated_run is not None
    assert updated_run.run_status == RUN_STATUS_IN_PROGRESS
    assert updated_run.current_stage == "email_discovery"
    assert posting_status == "requires_contacts"
    assert (project_root / discovery_artifact_path).exists()


def test_email_discovery_stage_advances_to_sending_when_send_set_becomes_ready(
    tmp_path: Path,
) -> None:
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    lead_id, job_posting_id = seed_role_targeted_posting(
        connection,
        posting_status="requires_contacts",
    )
    seed_approved_tailoring_run(connection, job_posting_id=job_posting_id)
    seed_shortlisted_contact(
        connection,
        contact_id="ct_ready",
        job_posting_contact_id="jpc_ready",
        job_posting_id=job_posting_id,
        display_name="Priya Recruiter",
        recipient_type="recruiter",
        position_title="Technical Recruiter",
        provider_person_id="pp_ready",
    )
    resume_agent(
        connection,
        manual_command="jhc-agent-start",
        timestamp="2026-04-08T00:15:00Z",
    )
    pipeline_run, _ = ensure_role_targeted_pipeline_run(
        connection,
        lead_id=lead_id,
        job_posting_id=job_posting_id,
        current_stage="email_discovery",
        started_at="2026-04-08T00:16:00Z",
    )
    finder = FakeEmailFinderProvider(
        provider_name="getprospect",
        requires_domain=False,
        responses=[
            {
                "outcome": "found",
                "email": "priya@acme.example",
                "provider_verification_status": "valid",
                "provider_score": "0.94",
                "detected_pattern": "first",
            }
        ],
    )

    execution = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-04-08T00:17:00Z",
        action_dependencies=SupervisorActionDependencies(
            email_finder_providers=(finder,),
        ),
    )
    updated_run = get_pipeline_run(connection, pipeline_run.pipeline_run_id)
    posting_status = connection.execute(
        """
        SELECT posting_status
        FROM job_postings
        WHERE job_posting_id = ?
        """,
        (job_posting_id,),
    ).fetchone()[0]
    discovery_artifact_path = connection.execute(
        """
        SELECT file_path
        FROM artifact_records
        WHERE job_posting_id = ?
          AND artifact_type = 'discovery_result'
        """,
        (job_posting_id,),
    ).fetchone()[0]
    contact_row = connection.execute(
        """
        SELECT current_working_email, contact_status
        FROM contacts
        WHERE contact_id = 'ct_ready'
        """
    ).fetchone()
    connection.close()

    assert execution.cycle.result == SUPERVISOR_CYCLE_RESULT_SUCCESS
    assert execution.selected_work is not None
    assert execution.selected_work.work_id == pipeline_run.pipeline_run_id
    assert execution.selected_work.action_id == ACTION_RUN_ROLE_TARGETED_EMAIL_DISCOVERY
    assert execution.incident is None
    assert execution.review_packet is None
    assert len(finder.calls) == 1
    assert updated_run is not None
    assert updated_run.run_status == RUN_STATUS_IN_PROGRESS
    assert updated_run.current_stage == "sending"
    assert posting_status == "ready_for_outreach"
    assert (project_root / discovery_artifact_path).exists()
    assert dict(contact_row) == {
        "current_working_email": "priya@acme.example",
        "contact_status": "working_email_found",
    }


def test_sending_stage_drafts_ready_send_set_and_stays_active_while_more_sends_are_delayed(
    tmp_path: Path,
) -> None:
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    write_sender_profile(paths)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    lead_id, job_posting_id = seed_role_targeted_posting(
        connection,
        company_name="Acme Robotics",
        role_title="Staff Software Engineer / AI",
        posting_status="ready_for_outreach",
        timestamp="2026-04-08T00:18:00Z",
    )
    seed_outreach_ready_tailoring_run(
        connection,
        paths,
        company_name="Acme Robotics",
        role_title="Staff Software Engineer / AI",
        job_posting_id=job_posting_id,
        current_time="2026-04-08T00:19:00Z",
    )
    seed_shortlisted_contact(
        connection,
        contact_id="ct_send_r1",
        job_posting_contact_id="jpc_send_r1",
        job_posting_id=job_posting_id,
        company_name="Acme Robotics",
        display_name="Priya Recruiter",
        recipient_type="recruiter",
        current_working_email="priya@acme.example",
        position_title="Technical Recruiter",
        created_at="2026-04-08T00:20:00Z",
    )
    seed_shortlisted_contact(
        connection,
        contact_id="ct_send_m1",
        job_posting_contact_id="jpc_send_m1",
        job_posting_id=job_posting_id,
        company_name="Acme Robotics",
        display_name="Morgan Manager",
        recipient_type="hiring_manager",
        current_working_email="morgan@acme.example",
        position_title="Engineering Manager",
        created_at="2026-04-08T00:21:00Z",
    )
    seed_shortlisted_contact(
        connection,
        contact_id="ct_send_e1",
        job_posting_contact_id="jpc_send_e1",
        job_posting_id=job_posting_id,
        company_name="Acme Robotics",
        display_name="Jamie Engineer",
        recipient_type="engineer",
        current_working_email="jamie@acme.example",
        position_title="Staff Software Engineer",
        created_at="2026-04-08T00:22:00Z",
    )
    resume_agent(
        connection,
        manual_command="jhc-agent-start",
        timestamp="2026-04-08T00:23:00Z",
    )
    pipeline_run, _ = ensure_role_targeted_pipeline_run(
        connection,
        lead_id=lead_id,
        job_posting_id=job_posting_id,
        current_stage="sending",
        started_at="2026-04-08T00:24:00Z",
    )
    sender = OutreachRecordingSender()

    execution = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-04-08T00:25:00Z",
        action_dependencies=SupervisorActionDependencies(
            outreach_sender=sender,
            local_timezone="UTC",
        ),
    )
    updated_run = get_pipeline_run(connection, pipeline_run.pipeline_run_id)
    posting_status = connection.execute(
        """
        SELECT posting_status
        FROM job_postings
        WHERE job_posting_id = ?
        """,
        (job_posting_id,),
    ).fetchone()[0]
    message_rows = connection.execute(
        """
        SELECT contact_id, message_status
        FROM outreach_messages
        WHERE job_posting_id = ?
        ORDER BY contact_id
        """,
        (job_posting_id,),
    ).fetchall()
    connection.close()

    assert execution.cycle.result == SUPERVISOR_CYCLE_RESULT_SUCCESS
    assert execution.selected_work is not None
    assert execution.selected_work.work_id == pipeline_run.pipeline_run_id
    assert execution.selected_work.action_id == ACTION_RUN_ROLE_TARGETED_SENDING
    assert execution.incident is None
    assert execution.review_packet is None
    assert sender.attempted_message_ids
    assert len(sender.attempted_message_ids) == 1
    assert updated_run is not None
    assert updated_run.run_status == RUN_STATUS_IN_PROGRESS
    assert updated_run.current_stage == "sending"
    assert posting_status == "outreach_in_progress"
    assert [dict(row) for row in message_rows] == [
        {"contact_id": "ct_send_e1", "message_status": "generated"},
        {"contact_id": "ct_send_m1", "message_status": "generated"},
        {"contact_id": "ct_send_r1", "message_status": "sent"},
    ]


def test_sending_stage_advances_to_delivery_feedback_after_terminal_sent_wave(
    tmp_path: Path,
) -> None:
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    write_sender_profile(paths)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    lead_id, job_posting_id = seed_role_targeted_posting(
        connection,
        company_name="Acme Robotics",
        role_title="Staff Software Engineer / AI",
        posting_status="ready_for_outreach",
        timestamp="2026-04-08T00:26:00Z",
    )
    seed_outreach_ready_tailoring_run(
        connection,
        paths,
        company_name="Acme Robotics",
        role_title="Staff Software Engineer / AI",
        job_posting_id=job_posting_id,
        current_time="2026-04-08T00:27:00Z",
    )
    seed_shortlisted_contact(
        connection,
        contact_id="ct_send_final",
        job_posting_contact_id="jpc_send_final",
        job_posting_id=job_posting_id,
        company_name="Acme Robotics",
        display_name="Priya Recruiter",
        recipient_type="recruiter",
        current_working_email="priya@acme.example",
        position_title="Technical Recruiter",
        created_at="2026-04-08T00:28:00Z",
    )
    resume_agent(
        connection,
        manual_command="jhc-agent-start",
        timestamp="2026-04-08T00:29:00Z",
    )
    pipeline_run, _ = ensure_role_targeted_pipeline_run(
        connection,
        lead_id=lead_id,
        job_posting_id=job_posting_id,
        current_stage="sending",
        started_at="2026-04-08T00:30:00Z",
    )
    sender = OutreachRecordingSender()
    observer = OutreachImmediateBounceObserver(event_timestamp="2026-04-08T00:31:30Z")

    execution = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-04-08T00:31:00Z",
        action_dependencies=SupervisorActionDependencies(
            outreach_sender=sender,
            feedback_observer=observer,
            local_timezone="UTC",
        ),
    )
    updated_run = get_pipeline_run(connection, pipeline_run.pipeline_run_id)
    posting_status = connection.execute(
        """
        SELECT posting_status
        FROM job_postings
        WHERE job_posting_id = ?
        """,
        (job_posting_id,),
    ).fetchone()[0]
    feedback_row = connection.execute(
        """
        SELECT event_state, event_timestamp
        FROM delivery_feedback_events
        ORDER BY event_timestamp DESC, delivery_feedback_event_id DESC
        LIMIT 1
        """
    ).fetchone()
    connection.close()

    assert execution.cycle.result == SUPERVISOR_CYCLE_RESULT_SUCCESS
    assert execution.selected_work is not None
    assert execution.selected_work.action_id == ACTION_RUN_ROLE_TARGETED_SENDING
    assert execution.incident is None
    assert execution.review_packet is None
    assert sender.attempted_message_ids
    assert updated_run is not None
    assert updated_run.run_status == RUN_STATUS_IN_PROGRESS
    assert updated_run.current_stage == "delivery_feedback"
    assert posting_status == "completed"
    assert dict(feedback_row) == {
        "event_state": "bounced",
        "event_timestamp": "2026-04-08T00:31:30Z",
    }


def test_sending_stage_completes_review_worthy_run_when_terminal_wave_has_no_sent_messages(
    tmp_path: Path,
) -> None:
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    write_sender_profile(paths)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    lead_id, job_posting_id = seed_role_targeted_posting(
        connection,
        company_name="Acme Robotics",
        role_title="Staff Software Engineer / AI",
        posting_status="ready_for_outreach",
        timestamp="2026-04-08T00:32:00Z",
    )
    seed_outreach_ready_tailoring_run(
        connection,
        paths,
        company_name="Acme Robotics",
        role_title="Staff Software Engineer / AI",
        job_posting_id=job_posting_id,
        current_time="2026-04-08T00:33:00Z",
    )
    seed_shortlisted_contact(
        connection,
        contact_id="ct_send_blocked",
        job_posting_contact_id="jpc_send_blocked",
        job_posting_id=job_posting_id,
        company_name="Acme Robotics",
        display_name="Priya Recruiter",
        recipient_type="recruiter",
        current_working_email="priya@acme.example",
        position_title="Technical Recruiter",
        created_at="2026-04-08T00:34:00Z",
    )
    draft_batch = generate_role_targeted_send_set_drafts(
        connection,
        project_root=project_root,
        job_posting_id=job_posting_id,
        current_time="2026-04-08T00:35:00Z",
        local_timezone="UTC",
    )
    resume_agent(
        connection,
        manual_command="jhc-agent-start",
        timestamp="2026-04-08T00:36:00Z",
    )
    pipeline_run, _ = ensure_role_targeted_pipeline_run(
        connection,
        lead_id=lead_id,
        job_posting_id=job_posting_id,
        current_stage="sending",
        started_at="2026-04-08T00:37:00Z",
    )
    sender = OutreachRecordingSender(
        ambiguous_message_ids={draft_batch.drafted_messages[0].outreach_message_id}
    )

    execution = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-04-08T00:38:00Z",
        action_dependencies=SupervisorActionDependencies(
            outreach_sender=sender,
            local_timezone="UTC",
        ),
    )
    updated_run = get_pipeline_run(connection, pipeline_run.pipeline_run_id)
    posting_status = connection.execute(
        """
        SELECT posting_status
        FROM job_postings
        WHERE job_posting_id = ?
        """,
        (job_posting_id,),
    ).fetchone()[0]
    current_message = connection.execute(
        """
        SELECT message_status
        FROM outreach_messages
        WHERE outreach_message_id = ?
        """,
        (draft_batch.drafted_messages[0].outreach_message_id,),
    ).fetchone()
    connection.close()

    assert execution.cycle.result == SUPERVISOR_CYCLE_RESULT_SUCCESS
    assert execution.selected_work is not None
    assert execution.selected_work.action_id == ACTION_RUN_ROLE_TARGETED_SENDING
    assert execution.incident is None
    assert execution.review_packet is not None
    assert execution.review_packet.packet_status == REVIEW_PACKET_STATUS_PENDING
    assert updated_run is not None
    assert updated_run.run_status == RUN_STATUS_COMPLETED
    assert updated_run.current_stage == "completed"
    assert updated_run.review_packet_status == REVIEW_PACKET_STATUS_PENDING
    assert posting_status == "completed"
    assert dict(current_message) == {"message_status": "blocked"}


def test_existing_pipeline_run_is_selected_before_bootstrapping_another_eligible_posting(
    tmp_path: Path,
) -> None:
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    lead_id, job_posting_id = seed_role_targeted_posting(connection)
    _, waiting_job_posting_id = seed_role_targeted_posting(
        connection,
        lead_id="ld_waiting",
        job_posting_id="jp_waiting",
        lead_identity_key="beta|data-engineer",
        posting_identity_key="beta|data-engineer|remote",
        company_name="Beta Systems",
        role_title="Data Engineer",
        timestamp="2026-04-08T00:01:00Z",
    )
    resume_agent(
        connection,
        manual_command="jhc-agent-start",
        timestamp="2026-04-08T00:05:00Z",
    )
    pipeline_run, _ = ensure_role_targeted_pipeline_run(
        connection,
        lead_id=lead_id,
        job_posting_id=job_posting_id,
        current_stage="lead_handoff",
        started_at="2026-04-08T00:06:00Z",
    )

    execution = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-04-08T00:07:00Z",
    )
    stored_runs = connection.execute(
        """
        SELECT pipeline_run_id, job_posting_id, current_stage
        FROM pipeline_runs
        ORDER BY started_at
        """
    ).fetchall()
    waiting_run_count = connection.execute(
        """
        SELECT COUNT(*)
        FROM pipeline_runs
        WHERE job_posting_id = ?
        """,
        (waiting_job_posting_id,),
    ).fetchone()[0]
    connection.close()

    assert execution.cycle.result == SUPERVISOR_CYCLE_RESULT_SUCCESS
    assert execution.selected_work is not None
    assert execution.selected_work.work_type == "pipeline_run"
    assert execution.selected_work.work_id == pipeline_run.pipeline_run_id
    assert execution.selected_work.action_id == "checkpoint_pipeline_run"
    assert execution.pipeline_run is not None
    assert execution.pipeline_run.pipeline_run_id == pipeline_run.pipeline_run_id
    assert execution.pipeline_run.job_posting_id == job_posting_id
    assert waiting_run_count == 0
    assert [dict(row) for row in stored_runs] == [
        {
            "pipeline_run_id": pipeline_run.pipeline_run_id,
            "job_posting_id": job_posting_id,
            "current_stage": "agent_review",
        }
    ]


def test_contact_rooted_general_learning_work_is_not_selected_yet(tmp_path: Path) -> None:
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    contact_id = seed_general_learning_contact(connection)
    resume_agent(
        connection,
        manual_command="jhc-agent-start",
        timestamp="2026-04-08T00:05:00Z",
    )

    execution = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-04-08T00:06:00Z",
    )
    pipeline_run_count = connection.execute(
        "SELECT COUNT(*) FROM pipeline_runs"
    ).fetchone()[0]
    contact_row = connection.execute(
        """
        SELECT contact_id, current_working_email
        FROM contacts
        WHERE contact_id = ?
        """,
        (contact_id,),
    ).fetchone()
    connection.close()

    assert execution.cycle.result == SUPERVISOR_CYCLE_RESULT_NO_WORK
    assert execution.selected_work is None
    assert execution.pipeline_run is None
    assert execution.incident is None
    assert execution.review_packet is None
    assert execution.cycle.error_summary == "no bounded supervisor work unit is currently due"
    assert pipeline_run_count == 0
    assert contact_row is not None
    assert contact_row["contact_id"] == contact_id
    assert contact_row["current_working_email"] == "sam.learner@acme.example"


@pytest.mark.parametrize(
    "blocked_stage",
    [
        "delivery_feedback",
    ],
)
def test_downstream_stage_without_registered_action_escalates_with_review_packet(
    tmp_path: Path,
    blocked_stage: str,
) -> None:
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    lead_id, job_posting_id = seed_role_targeted_posting(connection)
    resume_agent(
        connection,
        manual_command="jhc-agent-start",
        timestamp="2026-04-08T00:10:00Z",
    )
    pipeline_run, _ = ensure_role_targeted_pipeline_run(
        connection,
        lead_id=lead_id,
        job_posting_id=job_posting_id,
        current_stage=blocked_stage,
        started_at="2026-04-08T00:11:00Z",
    )

    execution = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-04-08T00:12:00Z",
    )
    updated_run = get_pipeline_run(connection, pipeline_run.pipeline_run_id)
    stored_packets = list_expert_review_packets_for_run(connection, pipeline_run.pipeline_run_id)
    snapshot = json.loads((project_root / execution.context_snapshot_path).read_text(encoding="utf-8"))
    connection.close()

    assert execution.cycle.result == SUPERVISOR_CYCLE_RESULT_FAILED
    assert execution.selected_work is not None
    assert execution.selected_work.work_id == pipeline_run.pipeline_run_id
    assert execution.selected_work.action_id is None
    assert execution.selected_work.current_stage == blocked_stage
    assert execution.incident is not None
    assert execution.incident.incident_type == "unsupported_supervisor_action"
    assert execution.review_packet is not None
    assert execution.review_packet.packet_status == REVIEW_PACKET_STATUS_PENDING
    assert updated_run is not None
    assert updated_run.run_status == RUN_STATUS_ESCALATED
    assert updated_run.current_stage == blocked_stage
    assert updated_run.review_packet_status == REVIEW_PACKET_STATUS_PENDING
    assert updated_run.last_error_summary == (
        f"No registered bounded supervisor action covers pipeline stage "
        f"'{blocked_stage}' yet."
    )
    assert stored_packets == [execution.review_packet]
    assert snapshot["selected_work"]["current_stage"] == blocked_stage
    assert snapshot["pipeline_run"]["current_stage"] == blocked_stage
    assert snapshot["review_packet"]["packet_path"] == execution.review_packet.packet_path


def test_retry_after_downstream_stage_blocker_reuses_same_run_and_review_packet(
    tmp_path: Path,
) -> None:
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    write_sender_profile(paths)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    lead_id, job_posting_id = seed_role_targeted_posting(
        connection,
        company_name="Acme Robotics",
        role_title="Staff Software Engineer / AI",
        posting_status="requires_contacts",
    )
    seed_outreach_ready_tailoring_run(
        connection,
        paths,
        company_name="Acme Robotics",
        role_title="Staff Software Engineer / AI",
        job_posting_id=job_posting_id,
        current_time="2026-04-08T00:20:00Z",
    )
    connection.execute(
        """
        UPDATE job_postings
        SET posting_status = ?, updated_at = ?
        WHERE job_posting_id = ?
        """,
        (
            "requires_contacts",
            "2026-04-08T00:20:30Z",
            job_posting_id,
        ),
    )
    connection.commit()
    resume_agent(
        connection,
        manual_command="jhc-agent-start",
        timestamp="2026-04-08T00:20:00Z",
    )
    pipeline_run, _ = ensure_role_targeted_pipeline_run(
        connection,
        lead_id=lead_id,
        job_posting_id=job_posting_id,
        current_stage="people_search",
        started_at="2026-04-08T00:21:00Z",
    )
    search_provider = FakeApolloSearchProvider(
        candidates=[
            build_candidate(
                provider_person_id="pp_r1",
                display_name="Priya Recruiter",
                title="Technical Recruiter",
            )
        ]
    )
    enrichment_provider = FakeApolloEnrichmentProvider(
        {"pp_r1": None}
    )
    discovery_provider = FakeEmailFinderProvider(
        provider_name="getprospect",
        requires_domain=False,
        responses=[
            {
                "outcome": "found",
                "email": "priya@acme.example",
                "provider_verification_status": "valid",
                "provider_score": "0.91",
                "detected_pattern": "first",
            }
        ],
    )
    sender = OutreachRecordingSender()

    first_execution = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-04-08T00:22:00Z",
        action_dependencies=SupervisorActionDependencies(
            apollo_people_search_provider=search_provider,
            apollo_contact_enrichment_provider=enrichment_provider,
        ),
    )
    assert first_execution.cycle.result == SUPERVISOR_CYCLE_RESULT_SUCCESS
    assert first_execution.pipeline_run is not None
    assert first_execution.pipeline_run.current_stage == "email_discovery"

    second_execution = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-04-08T00:23:00Z",
        action_dependencies=SupervisorActionDependencies(
            email_finder_providers=(discovery_provider,),
        ),
    )
    assert second_execution.cycle.result == SUPERVISOR_CYCLE_RESULT_SUCCESS
    assert second_execution.pipeline_run is not None
    assert second_execution.pipeline_run.current_stage == "sending"

    third_execution = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-04-08T00:24:00Z",
        action_dependencies=SupervisorActionDependencies(
            outreach_sender=sender,
            local_timezone="UTC",
        ),
    )
    assert third_execution.cycle.result == SUPERVISOR_CYCLE_RESULT_SUCCESS
    assert third_execution.pipeline_run is not None
    assert third_execution.pipeline_run.current_stage == "delivery_feedback"

    fourth_execution = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-04-08T00:24:30Z",
    )
    assert fourth_execution.incident is not None
    assert fourth_execution.review_packet is not None

    escalated_incident = escalate_agent_incident(
        connection,
        fourth_execution.incident.agent_incident_id,
        escalation_reason=(
            "Expert confirmed the remaining downstream supervisor gap after sending "
            "handoff and recorded it for later catalog work."
        ),
        timestamp="2026-04-08T00:25:00Z",
    )
    retried_run = advance_pipeline_run(
        connection,
        pipeline_run.pipeline_run_id,
        current_stage="delivery_feedback",
        run_summary="Retry the same downstream boundary without restarting the run.",
        timestamp="2026-04-08T00:26:00Z",
    )
    reused_run, created = ensure_role_targeted_pipeline_run(
        connection,
        lead_id=lead_id,
        job_posting_id=job_posting_id,
        current_stage="lead_handoff",
        started_at="2026-04-08T00:27:00Z",
    )

    fifth_execution = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-04-08T00:28:00Z",
    )
    stored_packets = list_expert_review_packets_for_run(connection, pipeline_run.pipeline_run_id)
    connection.close()

    assert first_execution.pipeline_run is not None
    assert first_execution.pipeline_run.pipeline_run_id == pipeline_run.pipeline_run_id
    assert second_execution.pipeline_run is not None
    assert second_execution.pipeline_run.pipeline_run_id == pipeline_run.pipeline_run_id
    assert third_execution.pipeline_run is not None
    assert third_execution.pipeline_run.pipeline_run_id == pipeline_run.pipeline_run_id
    assert escalated_incident.status == "escalated"
    assert retried_run.pipeline_run_id == pipeline_run.pipeline_run_id
    assert retried_run.run_status == RUN_STATUS_IN_PROGRESS
    assert retried_run.current_stage == "delivery_feedback"
    assert created is False
    assert reused_run.pipeline_run_id == pipeline_run.pipeline_run_id
    assert reused_run.current_stage == "delivery_feedback"
    assert fifth_execution.cycle.result == SUPERVISOR_CYCLE_RESULT_FAILED
    assert fifth_execution.selected_work is not None
    assert fifth_execution.selected_work.work_id == pipeline_run.pipeline_run_id
    assert fifth_execution.selected_work.current_stage == "delivery_feedback"
    assert fifth_execution.review_packet is not None
    assert fifth_execution.review_packet.expert_review_packet_id == (
        fourth_execution.review_packet.expert_review_packet_id
    )
    assert len(stored_packets) == 1
