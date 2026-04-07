from __future__ import annotations

import json
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from job_hunt_copilot.bootstrap import run_bootstrap
from job_hunt_copilot.delivery_feedback import (
    DELIVERY_FEEDBACK_COMPONENT,
    EVENT_STATE_BOUNCED,
    EVENT_STATE_NOT_BOUNCED,
    OBSERVATION_SCOPE_DELAYED,
    DeliveryFeedbackSignal,
    sync_delivery_feedback,
)
from job_hunt_copilot.email_discovery import (
    EMAIL_DISCOVERY_COMPONENT,
    PROVIDER_NAME_APOLLO,
    PROVIDER_NAME_PROSPEO,
    ApolloResolvedCompany,
    EmailDiscoveryProviderResult,
    run_apollo_people_search,
    run_email_discovery_for_contact,
)
from job_hunt_copilot.outreach import (
    OUTREACH_COMPONENT,
    SendAttemptOutcome,
    execute_role_targeted_send_set,
    generate_role_targeted_send_set_drafts,
)
from job_hunt_copilot.paths import ProjectPaths
from job_hunt_copilot.resume_tailoring import (
    MANDATORY_REVIEWER_AGENT,
    RESUME_REVIEW_STATUS_APPROVED,
    bootstrap_tailoring_run,
    finalize_tailoring_run,
    generate_tailoring_intelligence,
    record_tailoring_review_decision,
)
from job_hunt_copilot.review_queries import query_object_traceability, query_review_surfaces
from tests.support import create_minimal_project


REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_PROFILE_PATH = REPO_ROOT / "assets" / "resume-tailoring" / "profile.md"
REAL_BASE_RESUME_PATH = (
    REPO_ROOT / "assets" / "resume-tailoring" / "base" / "distributed-infra" / "base-resume.tex"
)

SMOKE_COMPANY_NAME = "Acme Data Systems"
SMOKE_ROLE_TITLE = "Software Engineer"
SMOKE_LEAD_ID = "ld_smoke"
SMOKE_JOB_POSTING_ID = "jp_smoke"


@dataclass(frozen=True)
class SmokeFlowState:
    project_root: Path
    paths: ProjectPaths
    connection: sqlite3.Connection
    bootstrap_report: dict[str, object]
    finalize_result: object
    review_result: object
    search_result: object
    discovery_result: object
    draft_batch: object
    send_execution: object
    sent_message_id: str


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


class RecordingOutreachSender:
    def __init__(self) -> None:
        self.attempted_message_ids: list[str] = []

    def send(self, message):  # type: ignore[no-untyped-def]
        self.attempted_message_ids.append(message.outreach_message_id)
        return SendAttemptOutcome(
            outcome="sent",
            thread_id=f"thread-{message.outreach_message_id}",
            delivery_tracking_id=f"delivery-{message.outreach_message_id}",
        )


class FakeMailboxFeedbackObserver:
    def __init__(self, *, signals: list[DeliveryFeedbackSignal]) -> None:
        self.signals = signals
        self.poll_calls: list[dict[str, object]] = []

    def poll(self, messages, *, current_time, observation_scope):  # type: ignore[no-untyped-def]
        self.poll_calls.append(
            {
                "message_ids": [message.outreach_message_id for message in messages],
                "current_time": current_time,
                "observation_scope": observation_scope,
            }
        )
        return list(self.signals)


def _connect_database(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    return connection


def _create_smoke_project(tmp_path: Path) -> tuple[Path, ProjectPaths, dict[str, object]]:
    project_root = tmp_path / "repo"
    project_root.mkdir()
    create_minimal_project(project_root)

    generalist_dir = project_root / "assets" / "resume-tailoring" / "base" / "generalist"
    shutil.rmtree(generalist_dir)
    (project_root / "assets" / "resume-tailoring" / "profile.md").write_text(
        REAL_PROFILE_PATH.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    distributed_dir = project_root / "assets" / "resume-tailoring" / "base" / "distributed-infra"
    distributed_dir.mkdir(parents=True, exist_ok=True)
    (distributed_dir / "base-resume.tex").write_text(
        REAL_BASE_RESUME_PATH.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    report = run_bootstrap(project_root=project_root)
    return project_root, ProjectPaths.from_root(project_root), report


def _seed_smoke_posting(connection: sqlite3.Connection, paths: ProjectPaths) -> None:
    lead_workspace = paths.lead_workspace_dir(SMOKE_COMPANY_NAME, SMOKE_ROLE_TITLE, SMOKE_LEAD_ID)
    jd_path = lead_workspace / "jd.md"
    jd_path.parent.mkdir(parents=True, exist_ok=True)
    jd_path.write_text(
        "\n".join(
            [
                "# JD",
                "Requirements",
                "",
                "- 3+ years of software engineering experience.",
                "- Build distributed data services in Python and Apache Spark on AWS.",
                "- Own monitoring, reliability, and incident response for production pipelines.",
                "",
                "Nice to Have",
                "- Kubernetes exposure.",
            ]
        )
        + "\n",
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
            SMOKE_LEAD_ID,
            "acme-data-systems|software-engineer",
            "handed_off",
            "posting_only",
            "not_applicable",
            "gmail_job_alert",
            "gmail/message/123",
            "gmail_job_alert",
            "https://careers.acmedata.example/jobs/123",
            SMOKE_COMPANY_NAME,
            SMOKE_ROLE_TITLE,
            "2026-04-07T11:00:00Z",
            "2026-04-07T11:00:00Z",
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
            SMOKE_JOB_POSTING_ID,
            SMOKE_LEAD_ID,
            "acme-data-systems|software-engineer",
            SMOKE_COMPANY_NAME,
            SMOKE_ROLE_TITLE,
            "sourced",
            paths.relative_to_root(jd_path).as_posix(),
            "2026-04-07T11:00:00Z",
            "2026-04-07T11:00:00Z",
        ),
    )
    connection.commit()


def _write_sender_profile(paths: ProjectPaths) -> None:
    profile_path = paths.assets_dir / "resume-tailoring" / "profile.md"
    profile_path.write_text(
        "\n".join(
            [
                "# Achyutaram Sonti - Master Profile",
                "",
                "## Personal",
                "- **Name:** Achyutaram Sonti",
                "- **Email:** asonti1@asu.edu",
                "- **Phone:** 602-768-6071",
                "- **LinkedIn:** https://www.linkedin.com/in/asonti/",
                "- **GitHub:** https://github.com/sontiachyut",
                "",
                "## Education",
                "- **Arizona State University, Tempe, USA** - MS in Computer Science, GPA 3.96/4.00 (Aug 2024 - May 2026)",
                "",
                "## Work Experience",
                "- Built distributed Python and Scala data services on AWS, processing 50M+ daily HL7 records.",
                "- Optimized Apache Spark pipelines on AWS EMR, improving throughput and reducing cost.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _build_candidate(
    *,
    provider_person_id: str,
    display_name: str,
    title: str,
    has_email: bool = False,
    email: str | None = None,
    linkedin_url: str | None = None,
) -> dict[str, object]:
    return {
        "provider_person_id": provider_person_id,
        "display_name": display_name,
        "title": title,
        "has_email": has_email,
        "email": email,
        "linkedin_url": linkedin_url,
        "has_direct_phone": False,
        "last_refreshed_at": "2026-04-07T11:30:00Z",
    }


def _assert_json_contract(
    artifact_path: Path,
    *,
    expected_component: str,
    expected_result: str,
    required_ids: tuple[str, ...],
) -> dict[str, object]:
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert payload["contract_version"]
    assert payload["produced_at"]
    assert payload["producer_component"] == expected_component
    assert payload["result"] == expected_result
    for field_name in required_ids:
        assert payload[field_name]
    return payload


def _run_role_targeted_smoke_flow(tmp_path: Path) -> SmokeFlowState:
    project_root, paths, bootstrap_report = _create_smoke_project(tmp_path)

    connection = _connect_database(project_root / "job_hunt_copilot.db")
    _seed_smoke_posting(connection, paths)
    bootstrap_result = bootstrap_tailoring_run(
        connection,
        paths,
        job_posting_id=SMOKE_JOB_POSTING_ID,
        timestamp="2026-04-07T11:05:00Z",
    )
    assert bootstrap_result.run is not None

    generate_tailoring_intelligence(
        connection,
        paths,
        job_posting_id=SMOKE_JOB_POSTING_ID,
        timestamp="2026-04-07T11:10:00Z",
    )
    finalize_result = finalize_tailoring_run(
        connection,
        paths,
        job_posting_id=SMOKE_JOB_POSTING_ID,
        timestamp="2026-04-07T11:20:00Z",
    )
    review_result = record_tailoring_review_decision(
        connection,
        paths,
        job_posting_id=SMOKE_JOB_POSTING_ID,
        decision_type=RESUME_REVIEW_STATUS_APPROVED,
        decision_notes="Smoke harness agent approval for downstream discovery and outreach.",
        reviewer_type=MANDATORY_REVIEWER_AGENT,
        timestamp="2026-04-07T11:25:00Z",
    )
    connection.close()

    apollo_provider = FakeApolloProvider(
        resolved_company=ApolloResolvedCompany(
            organization_id="org_acme",
            organization_name=SMOKE_COMPANY_NAME,
            primary_domain="acmedata.example",
            website_url="https://acmedata.example",
            linkedin_url="https://www.linkedin.com/company/acme-data-systems",
        ),
        candidates=[
            _build_candidate(
                provider_person_id="pp_recruiter",
                display_name="Priya Recruiter",
                title="Technical Recruiter",
                has_email=True,
                email="priya@acmedata.example",
                linkedin_url="https://linkedin.example/priya",
            ),
            _build_candidate(
                provider_person_id="pp_manager",
                display_name="Morgan Manager",
                title="Engineering Manager",
                linkedin_url="https://linkedin.example/morgan",
            ),
        ],
    )
    search_result = run_apollo_people_search(
        project_root=project_root,
        job_posting_id=SMOKE_JOB_POSTING_ID,
        provider=apollo_provider,
        current_time="2026-04-07T11:30:00Z",
    )

    lookup_connection = _connect_database(project_root / "job_hunt_copilot.db")
    manager_contact_id = lookup_connection.execute(
        """
        SELECT contact_id
        FROM contacts
        WHERE display_name = 'Morgan Manager'
        """
    ).fetchone()["contact_id"]
    lookup_connection.close()

    discovery_provider = FakeEmailFinderProvider(
        provider_name=PROVIDER_NAME_PROSPEO,
        responses=[
            EmailDiscoveryProviderResult(
                provider_name=PROVIDER_NAME_PROSPEO,
                outcome="found",
                email="morgan@acmedata.example",
                provider_verification_status="verified",
                provider_score="93",
            )
        ],
    )
    discovery_result = run_email_discovery_for_contact(
        project_root=project_root,
        job_posting_id=SMOKE_JOB_POSTING_ID,
        contact_id=manager_contact_id,
        providers=[discovery_provider],
        current_time="2026-04-07T11:35:00Z",
    )

    _write_sender_profile(paths)
    connection = _connect_database(project_root / "job_hunt_copilot.db")
    draft_batch = generate_role_targeted_send_set_drafts(
        connection,
        project_root=project_root,
        job_posting_id=SMOKE_JOB_POSTING_ID,
        current_time="2026-04-07T11:40:00Z",
        local_timezone=ZoneInfo("UTC"),
    )
    sender = RecordingOutreachSender()
    send_execution = execute_role_targeted_send_set(
        connection,
        project_root=project_root,
        job_posting_id=SMOKE_JOB_POSTING_ID,
        current_time="2026-04-07T11:45:00Z",
        local_timezone=ZoneInfo("UTC"),
        sender=sender,
    )
    sent_message_id = send_execution.sent_messages[0].outreach_message_id

    return SmokeFlowState(
        project_root=project_root,
        paths=paths,
        connection=connection,
        bootstrap_report=bootstrap_report,
        finalize_result=finalize_result,
        review_result=review_result,
        search_result=search_result,
        discovery_result=discovery_result,
        draft_batch=draft_batch,
        send_execution=send_execution,
        sent_message_id=sent_message_id,
    )


def test_smoke_harness_exercises_bootstrap_tailoring_discovery_send_feedback_and_review_queries(
    tmp_path: Path,
):
    state = _run_role_targeted_smoke_flow(tmp_path)
    connection = state.connection

    try:
        assert state.bootstrap_report["status"] == "ok"
        assert (state.project_root / "paste" / "paste.txt").exists()
        assert (state.project_root / "ops" / "agent" / "identity.yaml").exists()
        assert (state.project_root / "ops" / "agent" / "policies.yaml").exists()
        assert (state.project_root / "secrets" / "apollo_keys.json").exists()
        assert (state.project_root / "assets" / "outreach" / "cold-outreach-guide.md").exists()
        assert state.finalize_result.result == "pass"
        assert Path(state.finalize_result.final_resume_path).name == "Achyutaram Sonti.pdf"

        discovery_payload = _assert_json_contract(
            state.discovery_result.artifact_path,
            expected_component=EMAIL_DISCOVERY_COMPONENT,
            expected_result="success",
            required_ids=("job_posting_id", "contact_id"),
        )
        assert discovery_payload["outcome"] == "found"
        assert discovery_payload["email"] == "morgan@acmedata.example"

        send_result_path = Path(state.send_execution.sent_messages[0].send_result_artifact_path)
        send_payload = _assert_json_contract(
            send_result_path,
            expected_component=OUTREACH_COMPONENT,
            expected_result="success",
            required_ids=("outreach_message_id", "contact_id", "job_posting_id"),
        )
        assert send_payload["send_status"] == "sent"
        assert send_payload["thread_id"] == f"thread-{state.sent_message_id}"
        assert send_payload["delivery_tracking_id"] == f"delivery-{state.sent_message_id}"

        delayed_result = sync_delivery_feedback(
            connection,
            project_root=state.project_root,
            current_time="2026-04-07T12:20:00Z",
            scheduler_name="job-hunt-copilot-feedback-sync",
            scheduler_type="launchd",
            observation_scope=OBSERVATION_SCOPE_DELAYED,
            observer=FakeMailboxFeedbackObserver(signals=[]),
        )
        assert delayed_result.messages_examined == 1
        assert delayed_result.not_bounced_events_written == 1
        assert delayed_result.bounce_events_written == 0
        assert delayed_result.reply_events_written == 0

        delivery_payload = _assert_json_contract(
            state.paths.outreach_latest_delivery_outcome_path(SMOKE_COMPANY_NAME, SMOKE_ROLE_TITLE),
            expected_component=DELIVERY_FEEDBACK_COMPONENT,
            expected_result="success",
            required_ids=("outreach_message_id", "contact_id", "job_posting_id"),
        )
        assert delivery_payload["event_state"] == EVENT_STATE_NOT_BOUNCED

        review_surfaces = query_review_surfaces(connection, project_root=state.project_root)
        assert any(
            row["job_posting_id"] == SMOKE_JOB_POSTING_ID for row in review_surfaces["posting_states"]
        )
        assert any(
            row["outreach_message_id"] == state.sent_message_id
            for row in review_surfaces["sent_message_history"]
        )
        assert review_surfaces["delivery_feedback_reuse_candidates"]

        traceability = query_object_traceability(
            connection,
            project_root=state.project_root,
            object_type="job_posting",
            object_id=SMOKE_JOB_POSTING_ID,
        )
        assert traceability["snapshot"]["posting_status"] == "outreach_in_progress"
        assert {artifact["artifact_type"] for artifact in traceability["artifacts"]} >= {
            "send_result",
            "delivery_outcome",
        }
        assert traceability["downstream_records"]["outreach_messages"]
    finally:
        connection.close()


def test_smoke_harness_captures_delayed_bounce_after_send_session(tmp_path: Path):
    state = _run_role_targeted_smoke_flow(tmp_path)
    connection = state.connection

    try:
        observer = FakeMailboxFeedbackObserver(
            signals=[
                DeliveryFeedbackSignal(
                    signal_type=EVENT_STATE_BOUNCED,
                    event_timestamp="2026-04-07T11:52:00Z",
                    delivery_tracking_id=f"delivery-{state.sent_message_id}",
                )
            ]
        )
        delayed_result = sync_delivery_feedback(
            connection,
            project_root=state.project_root,
            current_time="2026-04-07T11:55:00Z",
            scheduler_name="job-hunt-copilot-feedback-sync",
            scheduler_type="launchd",
            observation_scope=OBSERVATION_SCOPE_DELAYED,
            observer=observer,
        )

        assert observer.poll_calls == [
            {
                "message_ids": [state.sent_message_id],
                "current_time": "2026-04-07T11:55:00Z",
                "observation_scope": OBSERVATION_SCOPE_DELAYED,
            }
        ]
        assert delayed_result.messages_examined == 1
        assert delayed_result.bounce_events_written == 1
        assert delayed_result.not_bounced_events_written == 0
        assert delayed_result.reply_events_written == 0

        latest_payload = _assert_json_contract(
            state.paths.outreach_latest_delivery_outcome_path(SMOKE_COMPANY_NAME, SMOKE_ROLE_TITLE),
            expected_component=DELIVERY_FEEDBACK_COMPONENT,
            expected_result="success",
            required_ids=("outreach_message_id", "contact_id", "job_posting_id"),
        )
        assert latest_payload["event_state"] == EVENT_STATE_BOUNCED

        review_surfaces = query_review_surfaces(connection, project_root=state.project_root)
        assert any(
            row["outreach_message_id"] == state.sent_message_id
            for row in review_surfaces["bounced_email_cases"]
        )
    finally:
        connection.close()
