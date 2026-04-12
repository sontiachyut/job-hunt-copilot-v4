from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

from job_hunt_copilot.bootstrap import run_bootstrap
from job_hunt_copilot.delivery_feedback import EVENT_STATE_NOT_BOUNCED, sync_delivery_feedback
from job_hunt_copilot.outreach import (
    execute_role_targeted_send_set,
    generate_role_targeted_send_set_drafts,
)
from job_hunt_copilot.paths import ProjectPaths
from job_hunt_copilot.supervisor import (
    ACTION_BOOTSTRAP_ROLE_TARGETED_RUN,
    ACTION_RUN_GENERAL_LEARNING_EMAIL_DISCOVERY,
    ACTION_RUN_GENERAL_LEARNING_OUTREACH,
    ACTION_PERFORM_MANDATORY_AGENT_REVIEW,
    ACTION_RUN_ROLE_TARGETED_EMAIL_DISCOVERY,
    ACTION_RUN_ROLE_TARGETED_DELIVERY_FEEDBACK,
    ACTION_RUN_ROLE_TARGETED_PEOPLE_SEARCH,
    ACTION_RUN_ROLE_TARGETED_RESUME_TAILORING,
    ACTION_RUN_ROLE_TARGETED_SENDING,
    REVIEW_PACKET_STATUS_PENDING,
    RUN_STATUS_COMPLETED,
    RUN_STATUS_ESCALATED,
    RUN_STATUS_IN_PROGRESS,
    RUN_STATUS_PAUSED,
    SupervisorActionDependencies,
    SUPERVISOR_CYCLE_RESULT_FAILED,
    SUPERVISOR_CYCLE_RESULT_NO_WORK,
    SUPERVISOR_CYCLE_RESULT_SUCCESS,
    ensure_role_targeted_pipeline_run,
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
    current_working_email: str | None = "sam.learner@acme.example",
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
            current_working_email,
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


def send_single_role_targeted_message(
    connection: sqlite3.Connection,
    *,
    project_root: Path,
    job_posting_id: str,
    drafted_at: str,
    sent_at: str,
) -> str:
    draft_batch = generate_role_targeted_send_set_drafts(
        connection,
        project_root=project_root,
        job_posting_id=job_posting_id,
        current_time=drafted_at,
        local_timezone="UTC",
    )
    send_execution = execute_role_targeted_send_set(
        connection,
        project_root=project_root,
        job_posting_id=job_posting_id,
        current_time=sent_at,
        local_timezone="UTC",
        sender=OutreachRecordingSender(),
    )
    assert len(send_execution.sent_messages) == 1
    assert draft_batch.drafted_messages[0].outreach_message_id == (
        send_execution.sent_messages[0].outreach_message_id
    )
    return send_execution.sent_messages[0].outreach_message_id


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


def test_lead_handoff_advances_sourced_posting_into_resume_tailoring(tmp_path: Path) -> None:
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    lead_id, job_posting_id = seed_role_targeted_posting(
        connection,
        posting_status="sourced",
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
    assert updated_run.current_stage == "resume_tailoring"


def test_resume_tailoring_stage_advances_sourced_posting_into_agent_review(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    lead_id, job_posting_id = seed_role_targeted_posting(
        connection,
        posting_status="sourced",
    )
    jd_path = paths.lead_workspace_dir("Acme", "Platform Engineer", lead_id) / "jd.md"
    jd_path.parent.mkdir(parents=True, exist_ok=True)
    jd_path.write_text("About the job\nBuild platform systems.\n", encoding="utf-8")
    connection.execute(
        """
        UPDATE job_postings
        SET jd_artifact_path = ?
        WHERE job_posting_id = ?
        """,
        (paths.relative_to_root(jd_path).as_posix(), job_posting_id),
    )
    connection.commit()
    resume_agent(
        connection,
        manual_command="jhc-agent-start",
        timestamp="2026-04-08T00:08:00Z",
    )
    pipeline_run, _ = ensure_role_targeted_pipeline_run(
        connection,
        lead_id=lead_id,
        job_posting_id=job_posting_id,
        current_stage="resume_tailoring",
        started_at="2026-04-08T00:09:00Z",
    )

    def fake_generate_tailoring_intelligence(
        db_connection,
        _paths,
        *,
        job_posting_id: str,
        timestamp: str | None = None,
    ):
        current_time = timestamp or "2026-04-08T00:10:00Z"
        db_connection.execute(
            """
            INSERT INTO resume_tailoring_runs (
              resume_tailoring_run_id, job_posting_id, base_used, tailoring_status,
              resume_review_status, workspace_path, verification_outcome,
              started_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "rtr_supervisor_tailoring",
                job_posting_id,
                "generalist",
                "in_progress",
                "not_ready",
                "resume-tailoring/output/tailored/acme/platform-engineer",
                "pass",
                current_time,
                current_time,
                current_time,
            ),
        )
        db_connection.execute(
            """
            UPDATE job_postings
            SET posting_status = ?, updated_at = ?
            WHERE job_posting_id = ?
            """,
            ("tailoring_in_progress", current_time, job_posting_id),
        )
        db_connection.commit()
        return SimpleNamespace(
            job_posting_id=job_posting_id,
            resume_tailoring_run_id="rtr_supervisor_tailoring",
            track_name="generalist",
            verification_outcome="pass",
            blocked_reason_code=None,
            step_artifact_paths={},
        )

    def fake_finalize_tailoring_run(
        db_connection,
        _paths,
        *,
        job_posting_id: str,
        timestamp: str | None = None,
    ):
        current_time = timestamp or "2026-04-08T00:10:30Z"
        db_connection.execute(
            """
            UPDATE resume_tailoring_runs
            SET tailoring_status = ?, resume_review_status = ?, verification_outcome = ?,
                completed_at = ?, updated_at = ?
            WHERE resume_tailoring_run_id = ?
            """,
            (
                "tailored",
                "resume_review_pending",
                "pass",
                current_time,
                current_time,
                "rtr_supervisor_tailoring",
            ),
        )
        db_connection.execute(
            """
            UPDATE job_postings
            SET posting_status = ?, updated_at = ?
            WHERE job_posting_id = ?
            """,
            ("resume_review_pending", current_time, job_posting_id),
        )
        db_connection.commit()
        return SimpleNamespace(
            job_posting_id=job_posting_id,
            resume_tailoring_run_id="rtr_supervisor_tailoring",
            result="pass",
            reason_code=None,
            run=SimpleNamespace(
                resume_tailoring_run_id="rtr_supervisor_tailoring",
                job_posting_id=job_posting_id,
                base_used="generalist",
                tailoring_status="tailored",
                resume_review_status="resume_review_pending",
                workspace_path="resume-tailoring/output/tailored/acme/platform-engineer",
                meta_yaml_path=None,
                final_resume_path="resume-tailoring/output/tailored/acme/platform-engineer/Achyutaram Sonti.pdf",
                verification_outcome="pass",
                started_at="2026-04-08T00:10:00Z",
                completed_at=current_time,
                created_at="2026-04-08T00:10:00Z",
                updated_at=current_time,
            ),
            final_resume_path="resume-tailoring/output/tailored/acme/platform-engineer/Achyutaram Sonti.pdf",
            verification_outcome="pass",
        )

    monkeypatch.setattr(
        "job_hunt_copilot.resume_tailoring.generate_tailoring_intelligence",
        fake_generate_tailoring_intelligence,
    )
    monkeypatch.setattr(
        "job_hunt_copilot.resume_tailoring.finalize_tailoring_run",
        fake_finalize_tailoring_run,
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
    latest_run = connection.execute(
        """
        SELECT tailoring_status, resume_review_status
        FROM resume_tailoring_runs
        WHERE job_posting_id = ?
        ORDER BY created_at DESC, resume_tailoring_run_id DESC
        LIMIT 1
        """,
        (job_posting_id,),
    ).fetchone()
    connection.close()

    assert execution.cycle.result == SUPERVISOR_CYCLE_RESULT_SUCCESS
    assert execution.selected_work is not None
    assert execution.selected_work.work_type == "pipeline_run"
    assert execution.selected_work.action_id == ACTION_RUN_ROLE_TARGETED_RESUME_TAILORING
    assert execution.selected_work.current_stage == "resume_tailoring"
    assert execution.pipeline_run is not None
    assert execution.pipeline_run.pipeline_run_id == pipeline_run.pipeline_run_id
    assert updated_run is not None
    assert updated_run.run_status == RUN_STATUS_IN_PROGRESS
    assert updated_run.current_stage == "agent_review"
    assert posting_row is not None
    assert posting_row["posting_status"] == "resume_review_pending"
    assert latest_run is not None
    assert dict(latest_run) == {
        "tailoring_status": "tailored",
        "resume_review_status": "resume_review_pending",
    }


def test_resume_tailoring_stage_pauses_once_before_retry_escalation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    lead_id, job_posting_id = seed_role_targeted_posting(
        connection,
        posting_status="sourced",
    )
    jd_path = paths.lead_workspace_dir("Acme", "Platform Engineer", lead_id) / "jd.md"
    jd_path.parent.mkdir(parents=True, exist_ok=True)
    jd_path.write_text("About the job\nBuild platform systems.\n", encoding="utf-8")
    connection.execute(
        """
        UPDATE job_postings
        SET jd_artifact_path = ?
        WHERE job_posting_id = ?
        """,
        (paths.relative_to_root(jd_path).as_posix(), job_posting_id),
    )
    connection.commit()
    resume_agent(
        connection,
        manual_command="jhc-agent-start",
        timestamp="2026-04-08T00:08:00Z",
    )
    pipeline_run, _ = ensure_role_targeted_pipeline_run(
        connection,
        lead_id=lead_id,
        job_posting_id=job_posting_id,
        current_stage="resume_tailoring",
        started_at="2026-04-08T00:09:00Z",
    )

    def fake_generate_tailoring_intelligence(
        db_connection,
        _paths,
        *,
        job_posting_id: str,
        timestamp: str | None = None,
    ):
        current_time = timestamp or "2026-04-08T00:10:00Z"
        existing_row = db_connection.execute(
            """
            SELECT resume_tailoring_run_id
            FROM resume_tailoring_runs
            WHERE job_posting_id = ?
            ORDER BY created_at DESC, resume_tailoring_run_id DESC
            LIMIT 1
            """,
            (job_posting_id,),
        ).fetchone()
        if existing_row is None:
            db_connection.execute(
                """
                INSERT INTO resume_tailoring_runs (
                  resume_tailoring_run_id, job_posting_id, base_used, tailoring_status,
                  resume_review_status, workspace_path, verification_outcome,
                  started_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "rtr_supervisor_tailoring",
                    job_posting_id,
                    "generalist",
                    "in_progress",
                    "not_ready",
                    "resume-tailoring/output/tailored/acme/platform-engineer",
                    "pass",
                    current_time,
                    current_time,
                    current_time,
                ),
            )
        else:
            db_connection.execute(
                """
                UPDATE resume_tailoring_runs
                SET tailoring_status = ?, resume_review_status = ?, verification_outcome = ?,
                    completed_at = NULL, updated_at = ?
                WHERE resume_tailoring_run_id = ?
                """,
                (
                    "in_progress",
                    "not_ready",
                    "pass",
                    current_time,
                    existing_row["resume_tailoring_run_id"],
                ),
            )
        db_connection.execute(
            """
            UPDATE job_postings
            SET posting_status = ?, updated_at = ?
            WHERE job_posting_id = ?
            """,
            ("tailoring_in_progress", current_time, job_posting_id),
        )
        db_connection.commit()
        return SimpleNamespace(
            job_posting_id=job_posting_id,
            resume_tailoring_run_id="rtr_supervisor_tailoring",
            track_name="generalist",
            verification_outcome="pass",
            blocked_reason_code=None,
            step_artifact_paths={},
        )

    def fake_finalize_tailoring_run(
        db_connection,
        _paths,
        *,
        job_posting_id: str,
        timestamp: str | None = None,
    ):
        current_time = timestamp or "2026-04-08T00:10:30Z"
        db_connection.execute(
            """
            UPDATE resume_tailoring_runs
            SET tailoring_status = ?, resume_review_status = ?, verification_outcome = ?,
                completed_at = NULL, updated_at = ?
            WHERE resume_tailoring_run_id = ?
            """,
            (
                "needs_revision",
                "not_ready",
                "needs_revision",
                current_time,
                "rtr_supervisor_tailoring",
            ),
        )
        db_connection.execute(
            """
            UPDATE job_postings
            SET posting_status = ?, updated_at = ?
            WHERE job_posting_id = ?
            """,
            ("tailoring_in_progress", current_time, job_posting_id),
        )
        db_connection.commit()
        return SimpleNamespace(
            job_posting_id=job_posting_id,
            resume_tailoring_run_id="rtr_supervisor_tailoring",
            result="needs_revision",
            reason_code="verification_blocked",
            run=SimpleNamespace(
                resume_tailoring_run_id="rtr_supervisor_tailoring",
                job_posting_id=job_posting_id,
                base_used="generalist",
                tailoring_status="needs_revision",
                resume_review_status="not_ready",
                workspace_path="resume-tailoring/output/tailored/acme/platform-engineer",
                meta_yaml_path=None,
                final_resume_path=None,
                verification_outcome="needs_revision",
                started_at="2026-04-08T00:10:00Z",
                completed_at=None,
                created_at="2026-04-08T00:10:00Z",
                updated_at=current_time,
            ),
            final_resume_path=None,
            verification_outcome="needs_revision",
        )

    monkeypatch.setattr(
        "job_hunt_copilot.resume_tailoring.generate_tailoring_intelligence",
        fake_generate_tailoring_intelligence,
    )
    monkeypatch.setattr(
        "job_hunt_copilot.resume_tailoring.finalize_tailoring_run",
        fake_finalize_tailoring_run,
    )

    first_execution = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-04-08T00:10:00Z",
    )
    first_updated_run = get_pipeline_run(connection, pipeline_run.pipeline_run_id)
    first_packets = list_expert_review_packets_for_run(
        connection,
        pipeline_run.pipeline_run_id,
    )

    second_execution = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-04-08T00:20:00Z",
    )
    second_updated_run = get_pipeline_run(connection, pipeline_run.pipeline_run_id)
    latest_run = connection.execute(
        """
        SELECT tailoring_status, resume_review_status
        FROM resume_tailoring_runs
        WHERE job_posting_id = ?
        ORDER BY created_at DESC, resume_tailoring_run_id DESC
        LIMIT 1
        """,
        (job_posting_id,),
    ).fetchone()
    stored_packets = list_expert_review_packets_for_run(connection, pipeline_run.pipeline_run_id)
    connection.close()

    assert first_execution.cycle.result == SUPERVISOR_CYCLE_RESULT_SUCCESS
    assert first_execution.selected_work is not None
    assert (
        first_execution.selected_work.action_id
        == ACTION_RUN_ROLE_TARGETED_RESUME_TAILORING
    )
    assert first_execution.review_packet is None
    assert first_updated_run is not None
    assert first_updated_run.run_status == RUN_STATUS_PAUSED
    assert first_updated_run.current_stage == "resume_tailoring"
    assert first_updated_run.review_packet_status == "not_ready"
    assert first_packets == []

    assert second_execution.cycle.result == SUPERVISOR_CYCLE_RESULT_SUCCESS
    assert second_execution.selected_work is not None
    assert (
        second_execution.selected_work.action_id
        == ACTION_RUN_ROLE_TARGETED_RESUME_TAILORING
    )
    assert second_execution.review_packet is not None
    assert second_execution.review_packet.packet_status == REVIEW_PACKET_STATUS_PENDING
    assert second_updated_run is not None
    assert second_updated_run.run_status == RUN_STATUS_ESCALATED
    assert second_updated_run.current_stage == "resume_tailoring"
    assert second_updated_run.review_packet_status == REVIEW_PACKET_STATUS_PENDING
    assert latest_run is not None
    assert dict(latest_run) == {
        "tailoring_status": "needs_revision",
        "resume_review_status": "not_ready",
    }
    assert len(stored_packets) == 1


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


def test_people_search_stage_escalates_cleanly_when_no_contacts_are_found(tmp_path: Path) -> None:
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

    execution = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-04-08T00:12:00Z",
        action_dependencies=SupervisorActionDependencies(
            apollo_people_search_provider=FakeApolloSearchProvider(candidates=[]),
            apollo_contact_enrichment_provider=FakeApolloEnrichmentProvider({}),
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
    connection.close()

    assert execution.cycle.result == SUPERVISOR_CYCLE_RESULT_SUCCESS
    assert updated_run is not None
    assert updated_run.run_status == RUN_STATUS_ESCALATED
    assert updated_run.current_stage == "people_search"
    assert "did not identify any shortlisted internal contacts" in (updated_run.last_error_summary or "")
    assert posting_status == "requires_contacts"


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


def test_email_discovery_stage_escalates_when_bounded_send_set_is_exhausted(
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
        contact_id="ct_exhausted",
        job_posting_contact_id="jpc_exhausted",
        job_posting_id=job_posting_id,
        display_name="Priya Recruiter",
        recipient_type="recruiter",
        position_title="Technical Recruiter",
        provider_person_id="pp_exhausted",
    )
    resume_agent(
        connection,
        manual_command="jhc-agent-start",
        timestamp="2026-04-08T00:17:30Z",
    )
    pipeline_run, _ = ensure_role_targeted_pipeline_run(
        connection,
        lead_id=lead_id,
        job_posting_id=job_posting_id,
        current_stage="email_discovery",
        started_at="2026-04-08T00:18:00Z",
    )

    execution = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-04-08T00:19:00Z",
        action_dependencies=SupervisorActionDependencies(
            email_finder_providers=(
                FakeEmailFinderProvider(
                    provider_name="prospeo",
                    requires_domain=True,
                    responses=[],
                ),
                FakeEmailFinderProvider(
                    provider_name="getprospect",
                    requires_domain=True,
                    responses=[],
                ),
                FakeEmailFinderProvider(
                    provider_name="hunter",
                    responses=[{"outcome": "rate_limited"}],
                ),
            ),
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
    contact_row = connection.execute(
        """
        SELECT contact_status, discovery_summary
        FROM contacts
        WHERE contact_id = 'ct_exhausted'
        """
    ).fetchone()
    link_row = connection.execute(
        """
        SELECT link_level_status
        FROM job_posting_contacts
        WHERE job_posting_contact_id = 'jpc_exhausted'
        """
    ).fetchone()
    connection.close()

    assert execution.cycle.result == SUPERVISOR_CYCLE_RESULT_SUCCESS
    assert execution.selected_work is not None
    assert execution.selected_work.action_id == ACTION_RUN_ROLE_TARGETED_EMAIL_DISCOVERY
    assert updated_run is not None
    assert updated_run.run_status == RUN_STATUS_ESCALATED
    assert updated_run.current_stage == "email_discovery"
    assert "exhausted the current send set" in (updated_run.last_error_summary or "")
    assert posting_status == "requires_contacts"
    assert dict(contact_row) == {
        "contact_status": "exhausted",
        "discovery_summary": "all_providers_exhausted",
    }
    assert link_row["link_level_status"] == "exhausted"


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
            "current_stage": "resume_tailoring",
        }
    ]


def test_contact_rooted_general_learning_contact_is_selected_and_sent_without_pipeline_run(
    tmp_path: Path,
) -> None:
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    write_sender_profile(paths)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    contact_id = seed_general_learning_contact(connection)
    sender = OutreachRecordingSender()
    observer = OutreachImmediateBounceObserver(event_timestamp="2026-04-08T00:06:30Z")
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
        action_dependencies=SupervisorActionDependencies(
            outreach_sender=sender,
            feedback_observer=observer,
        ),
    )
    pipeline_run_count = connection.execute(
        "SELECT COUNT(*) FROM pipeline_runs"
    ).fetchone()[0]
    contact_row = connection.execute(
        """
        SELECT contact_id, current_working_email, contact_status
        FROM contacts
        WHERE contact_id = ?
        """,
        (contact_id,),
    ).fetchone()
    message_row = connection.execute(
        """
        SELECT outreach_message_id, outreach_mode, message_status, job_posting_id, sent_at
        FROM outreach_messages
        WHERE contact_id = ?
        ORDER BY created_at DESC, outreach_message_id DESC
        LIMIT 1
        """,
        (contact_id,),
    ).fetchone()
    feedback_sync_row = connection.execute(
        """
        SELECT scheduler_name, scheduler_type, observation_scope, result
        FROM feedback_sync_runs
        ORDER BY started_at DESC, feedback_sync_run_id DESC
        LIMIT 1
        """
    ).fetchone()
    connection.close()

    assert execution.cycle.result == SUPERVISOR_CYCLE_RESULT_SUCCESS
    assert execution.selected_work is not None
    assert execution.selected_work.work_type == "contact"
    assert execution.selected_work.work_id == contact_id
    assert execution.selected_work.action_id == ACTION_RUN_GENERAL_LEARNING_OUTREACH
    assert execution.pipeline_run is None
    assert execution.incident is None
    assert execution.review_packet is None
    assert execution.cycle.error_summary is None
    assert pipeline_run_count == 0
    assert sender.attempted_message_ids == [message_row["outreach_message_id"]]
    assert contact_row is not None
    assert contact_row["contact_id"] == contact_id
    assert contact_row["current_working_email"] == "sam.learner@acme.example"
    assert contact_row["contact_status"] == "sent"
    assert dict(message_row) == {
        "outreach_message_id": message_row["outreach_message_id"],
        "outreach_mode": "general_learning",
        "message_status": "sent",
        "job_posting_id": None,
        "sent_at": "2026-04-08T00:06:00Z",
    }
    assert dict(feedback_sync_row) == {
        "scheduler_name": "interactive_post_send",
        "scheduler_type": "interactive",
        "observation_scope": "immediate_post_send",
        "result": "success",
    }
    assert observer.poll_calls[0]["message_ids"] == [message_row["outreach_message_id"]]
    assert observer.poll_calls[0]["observation_scope"] == "immediate_post_send"


def test_contact_rooted_general_learning_email_discovery_advances_to_send_ready_follow_up(
    tmp_path: Path,
) -> None:
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    write_sender_profile(paths)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    contact_id = seed_general_learning_contact(
        connection,
        current_working_email=None,
    )
    finder = FakeEmailFinderProvider(
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
    sender = OutreachRecordingSender()
    observer = OutreachImmediateBounceObserver(event_timestamp="2026-04-08T00:08:30Z")
    resume_agent(
        connection,
        manual_command="jhc-agent-start",
        timestamp="2026-04-08T00:05:00Z",
    )

    first_execution = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-04-08T00:06:00Z",
        action_dependencies=SupervisorActionDependencies(
            email_finder_providers=(finder,),
        ),
    )
    discovery_contact_row = connection.execute(
        """
        SELECT current_working_email, contact_status
        FROM contacts
        WHERE contact_id = ?
        """,
        (contact_id,),
    ).fetchone()
    discovery_artifact_path = connection.execute(
        """
        SELECT file_path
        FROM artifact_records
        WHERE artifact_type = 'discovery_result'
          AND contact_id = ?
          AND job_posting_id IS NULL
        ORDER BY created_at DESC, artifact_id DESC
        LIMIT 1
        """,
        (contact_id,),
    ).fetchone()[0]

    second_execution = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-04-08T00:08:00Z",
        action_dependencies=SupervisorActionDependencies(
            outreach_sender=sender,
            feedback_observer=observer,
        ),
    )
    pipeline_run_count = connection.execute(
        "SELECT COUNT(*) FROM pipeline_runs"
    ).fetchone()[0]
    sent_contact_row = connection.execute(
        """
        SELECT current_working_email, contact_status
        FROM contacts
        WHERE contact_id = ?
        """,
        (contact_id,),
    ).fetchone()
    message_row = connection.execute(
        """
        SELECT outreach_message_id, message_status, job_posting_id, sent_at
        FROM outreach_messages
        WHERE contact_id = ?
          AND outreach_mode = 'general_learning'
        ORDER BY created_at DESC, outreach_message_id DESC
        LIMIT 1
        """,
        (contact_id,),
    ).fetchone()
    connection.close()

    assert first_execution.cycle.result == SUPERVISOR_CYCLE_RESULT_SUCCESS
    assert first_execution.selected_work is not None
    assert first_execution.selected_work.work_type == "contact"
    assert first_execution.selected_work.work_id == contact_id
    assert (
        first_execution.selected_work.action_id
        == ACTION_RUN_GENERAL_LEARNING_EMAIL_DISCOVERY
    )
    assert first_execution.pipeline_run is None
    assert first_execution.incident is None
    assert first_execution.review_packet is None
    assert len(finder.calls) == 1
    assert dict(discovery_contact_row) == {
        "current_working_email": "sam.learner@acme.example",
        "contact_status": "working_email_found",
    }
    assert (project_root / discovery_artifact_path).exists()

    assert second_execution.cycle.result == SUPERVISOR_CYCLE_RESULT_SUCCESS
    assert second_execution.selected_work is not None
    assert second_execution.selected_work.work_type == "contact"
    assert second_execution.selected_work.work_id == contact_id
    assert second_execution.selected_work.action_id == ACTION_RUN_GENERAL_LEARNING_OUTREACH
    assert second_execution.pipeline_run is None
    assert second_execution.incident is None
    assert second_execution.review_packet is None
    assert pipeline_run_count == 0
    assert sender.attempted_message_ids == [message_row["outreach_message_id"]]
    assert dict(sent_contact_row) == {
        "current_working_email": "sam.learner@acme.example",
        "contact_status": "sent",
    }
    assert dict(message_row) == {
        "outreach_message_id": message_row["outreach_message_id"],
        "message_status": "sent",
        "job_posting_id": None,
        "sent_at": "2026-04-08T00:08:00Z",
    }
    assert observer.poll_calls[0]["message_ids"] == [message_row["outreach_message_id"]]
    assert observer.poll_calls[0]["observation_scope"] == "immediate_post_send"


def test_contact_rooted_general_learning_delayed_feedback_is_left_to_feedback_worker_after_send(
    tmp_path: Path,
) -> None:
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    write_sender_profile(paths)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    contact_id = seed_general_learning_contact(connection)
    sender = OutreachRecordingSender()
    resume_agent(
        connection,
        manual_command="jhc-agent-start",
        timestamp="2026-04-08T00:05:00Z",
    )

    first_execution = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-04-08T00:06:00Z",
        action_dependencies=SupervisorActionDependencies(
            outreach_sender=sender,
        ),
    )
    message_row = connection.execute(
        """
        SELECT outreach_message_id, message_status, sent_at
        FROM outreach_messages
        WHERE contact_id = ?
          AND outreach_mode = 'general_learning'
        ORDER BY created_at DESC, outreach_message_id DESC
        LIMIT 1
        """,
        (contact_id,),
    ).fetchone()

    second_execution = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-04-08T00:10:00Z",
    )
    pipeline_run_count = connection.execute(
        "SELECT COUNT(*) FROM pipeline_runs"
    ).fetchone()[0]
    feedback_event_count = connection.execute(
        """
        SELECT COUNT(*)
        FROM delivery_feedback_events
        WHERE outreach_message_id = ?
        """,
        (message_row["outreach_message_id"],),
    ).fetchone()[0]
    supervisor_feedback_sync_count = connection.execute(
        """
        SELECT COUNT(*)
        FROM feedback_sync_runs
        WHERE scheduler_name = 'supervisor_delivery_feedback'
        """
    ).fetchone()[0]
    connection.close()

    assert first_execution.cycle.result == SUPERVISOR_CYCLE_RESULT_SUCCESS
    assert first_execution.selected_work is not None
    assert first_execution.selected_work.action_id == ACTION_RUN_GENERAL_LEARNING_OUTREACH
    assert second_execution.cycle.result == SUPERVISOR_CYCLE_RESULT_NO_WORK
    assert second_execution.selected_work is None
    assert second_execution.pipeline_run is None
    assert second_execution.incident is None
    assert second_execution.review_packet is None
    assert pipeline_run_count == 0
    assert feedback_event_count == 0
    assert dict(message_row) == {
        "outreach_message_id": message_row["outreach_message_id"],
        "message_status": "sent",
        "sent_at": "2026-04-08T00:06:00Z",
    }
    assert supervisor_feedback_sync_count == 0


def test_contact_rooted_general_learning_delayed_feedback_records_not_bounced_and_clears_follow_up(
    tmp_path: Path,
) -> None:
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    write_sender_profile(paths)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    contact_id = seed_general_learning_contact(connection)
    sender = OutreachRecordingSender()
    resume_agent(
        connection,
        manual_command="jhc-agent-start",
        timestamp="2026-04-08T00:05:00Z",
    )

    first_execution = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-04-08T00:06:00Z",
        action_dependencies=SupervisorActionDependencies(
            outreach_sender=sender,
        ),
    )
    message_row = connection.execute(
        """
        SELECT outreach_message_id
        FROM outreach_messages
        WHERE contact_id = ?
          AND outreach_mode = 'general_learning'
        ORDER BY created_at DESC, outreach_message_id DESC
        LIMIT 1
        """,
        (contact_id,),
    ).fetchone()

    sync_delivery_feedback(
        connection,
        project_root=project_root,
        current_time="2026-04-08T00:40:00Z",
        scheduler_name="job-hunt-copilot-feedback-sync",
        scheduler_type="launchd",
    )
    latest_feedback = connection.execute(
        """
        SELECT event_state, event_timestamp
        FROM delivery_feedback_events
        WHERE outreach_message_id = ?
        ORDER BY event_timestamp DESC, delivery_feedback_event_id DESC
        LIMIT 1
        """,
        (message_row["outreach_message_id"],),
    ).fetchone()

    second_execution = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-04-08T00:41:00Z",
    )
    connection.close()

    assert first_execution.cycle.result == SUPERVISOR_CYCLE_RESULT_SUCCESS
    assert first_execution.selected_work is not None
    assert first_execution.selected_work.action_id == ACTION_RUN_GENERAL_LEARNING_OUTREACH
    assert second_execution.pipeline_run is None
    assert second_execution.cycle.result == SUPERVISOR_CYCLE_RESULT_NO_WORK
    assert second_execution.selected_work is None
    assert second_execution.review_packet is None
    assert dict(latest_feedback) == {
        "event_state": EVENT_STATE_NOT_BOUNCED,
        "event_timestamp": "2026-04-08T00:36:00Z",
    }


def test_new_role_targeted_posting_is_selected_before_general_learning_contact(
    tmp_path: Path,
) -> None:
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    write_sender_profile(paths)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    contact_id = seed_general_learning_contact(connection)
    lead_id, job_posting_id = seed_role_targeted_posting(connection)
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
        action_dependencies=SupervisorActionDependencies(
            outreach_sender=OutreachRecordingSender()
        ),
    )
    pipeline_run_rows = connection.execute(
        """
        SELECT job_posting_id, current_stage
        FROM pipeline_runs
        ORDER BY started_at DESC, pipeline_run_id DESC
        """
    ).fetchall()
    message_count = connection.execute(
        """
        SELECT COUNT(*)
        FROM outreach_messages
        WHERE contact_id = ?
        """,
        (contact_id,),
    ).fetchone()[0]
    connection.close()

    assert execution.cycle.result == SUPERVISOR_CYCLE_RESULT_SUCCESS
    assert execution.selected_work is not None
    assert execution.selected_work.work_type == "job_posting"
    assert execution.selected_work.job_posting_id == job_posting_id
    assert execution.pipeline_run is not None
    assert execution.pipeline_run.lead_id == lead_id
    assert execution.pipeline_run.job_posting_id == job_posting_id
    assert [dict(row) for row in pipeline_run_rows] == [
        {
            "job_posting_id": job_posting_id,
            "current_stage": "lead_handoff",
        }
    ]
    assert message_count == 0


def test_delivery_feedback_stage_stays_active_while_high_level_outcome_is_still_pending(
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
        timestamp="2026-04-08T00:00:00Z",
    )
    seed_outreach_ready_tailoring_run(
        connection,
        paths,
        company_name="Acme Robotics",
        role_title="Staff Software Engineer / AI",
        job_posting_id=job_posting_id,
        current_time="2026-04-08T00:01:00Z",
    )
    seed_shortlisted_contact(
        connection,
        contact_id="ct_feedback_pending",
        job_posting_contact_id="jpc_feedback_pending",
        job_posting_id=job_posting_id,
        company_name="Acme Robotics",
        display_name="Priya Recruiter",
        recipient_type="recruiter",
        current_working_email="priya@acme.example",
        position_title="Technical Recruiter",
        created_at="2026-04-08T00:02:00Z",
    )
    sent_message_id = send_single_role_targeted_message(
        connection,
        project_root=project_root,
        job_posting_id=job_posting_id,
        drafted_at="2026-04-08T00:03:00Z",
        sent_at="2026-04-08T00:04:00Z",
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
        current_stage="delivery_feedback",
        started_at="2026-04-08T00:06:00Z",
    )

    first_execution = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-04-08T00:10:00Z",
    )
    updated_run = get_pipeline_run(connection, pipeline_run.pipeline_run_id)
    feedback_event_count = connection.execute(
        """
        SELECT COUNT(*)
        FROM delivery_feedback_events
        WHERE outreach_message_id = ?
        """,
        (sent_message_id,),
    ).fetchone()[0]
    supervisor_feedback_sync_count = connection.execute(
        """
        SELECT COUNT(*)
        FROM feedback_sync_runs
        WHERE scheduler_name = 'supervisor_delivery_feedback'
        """
    ).fetchone()[0]
    stored_packets = list_expert_review_packets_for_run(connection, pipeline_run.pipeline_run_id)
    connection.close()

    assert first_execution.cycle.result == SUPERVISOR_CYCLE_RESULT_NO_WORK
    assert first_execution.selected_work is None
    assert first_execution.incident is None
    assert first_execution.review_packet is None
    assert updated_run is not None
    assert updated_run.pipeline_run_id == pipeline_run.pipeline_run_id
    assert updated_run.run_status == RUN_STATUS_IN_PROGRESS
    assert updated_run.current_stage == "delivery_feedback"
    assert feedback_event_count == 0
    assert supervisor_feedback_sync_count == 0
    assert stored_packets == []


def test_retry_after_delivery_feedback_stage_reuses_same_run_and_completes_later(
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
        timestamp="2026-04-08T00:00:00Z",
    )
    seed_outreach_ready_tailoring_run(
        connection,
        paths,
        company_name="Acme Robotics",
        role_title="Staff Software Engineer / AI",
        job_posting_id=job_posting_id,
        current_time="2026-04-08T00:01:00Z",
    )
    seed_shortlisted_contact(
        connection,
        contact_id="ct_feedback_complete",
        job_posting_contact_id="jpc_feedback_complete",
        job_posting_id=job_posting_id,
        company_name="Acme Robotics",
        display_name="Priya Recruiter",
        recipient_type="recruiter",
        current_working_email="priya@acme.example",
        position_title="Technical Recruiter",
        created_at="2026-04-08T00:02:00Z",
    )
    sent_message_id = send_single_role_targeted_message(
        connection,
        project_root=project_root,
        job_posting_id=job_posting_id,
        drafted_at="2026-04-08T00:03:00Z",
        sent_at="2026-04-08T00:04:00Z",
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
        current_stage="delivery_feedback",
        started_at="2026-04-08T00:06:00Z",
    )

    first_execution = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-04-08T00:10:00Z",
    )
    assert first_execution.cycle.result == SUPERVISOR_CYCLE_RESULT_NO_WORK
    assert first_execution.review_packet is None
    assert first_execution.pipeline_run is None

    reused_run, created = ensure_role_targeted_pipeline_run(
        connection,
        lead_id=lead_id,
        job_posting_id=job_posting_id,
        current_stage="lead_handoff",
        started_at="2026-04-08T00:11:00Z",
    )

    sync_delivery_feedback(
        connection,
        project_root=project_root,
        current_time="2026-04-08T00:35:00Z",
        scheduler_name="job-hunt-copilot-feedback-sync",
        scheduler_type="launchd",
    )

    second_execution = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-04-08T00:36:00Z",
    )
    updated_run = get_pipeline_run(connection, pipeline_run.pipeline_run_id)
    latest_feedback = connection.execute(
        """
        SELECT event_state, event_timestamp
        FROM delivery_feedback_events
        WHERE outreach_message_id = ?
        ORDER BY event_timestamp DESC, delivery_feedback_event_id DESC
        LIMIT 1
        """,
        (sent_message_id,),
    ).fetchone()
    feedback_sync_rows = connection.execute(
        """
        SELECT scheduler_name, scheduler_type, observation_scope, result, messages_examined
        FROM feedback_sync_runs
        ORDER BY started_at
        """
    ).fetchall()
    stored_packets = list_expert_review_packets_for_run(connection, pipeline_run.pipeline_run_id)
    connection.close()

    assert created is False
    assert reused_run.pipeline_run_id == pipeline_run.pipeline_run_id
    assert reused_run.current_stage == "delivery_feedback"
    assert second_execution.cycle.result == SUPERVISOR_CYCLE_RESULT_SUCCESS
    assert second_execution.selected_work is not None
    assert (
        second_execution.selected_work.action_id
        == ACTION_RUN_ROLE_TARGETED_DELIVERY_FEEDBACK
    )
    assert second_execution.incident is None
    assert second_execution.review_packet is not None
    assert second_execution.review_packet.packet_status == REVIEW_PACKET_STATUS_PENDING
    assert updated_run is not None
    assert updated_run.pipeline_run_id == pipeline_run.pipeline_run_id
    assert updated_run.run_status == RUN_STATUS_COMPLETED
    assert updated_run.current_stage == "completed"
    assert updated_run.review_packet_status == REVIEW_PACKET_STATUS_PENDING
    assert dict(latest_feedback) == {
        "event_state": "not_bounced",
        "event_timestamp": "2026-04-08T00:34:00Z",
    }
    worker_feedback_sync_rows = [
        dict(row)
        for row in feedback_sync_rows
        if row["scheduler_name"] == "job-hunt-copilot-feedback-sync"
    ]
    assert worker_feedback_sync_rows == [
        {
            "scheduler_name": "job-hunt-copilot-feedback-sync",
            "scheduler_type": "launchd",
            "observation_scope": "delayed_feedback_sync",
            "result": "success",
            "messages_examined": 1,
        },
    ]
    assert len(stored_packets) == 1


def test_pending_delivery_feedback_run_does_not_block_new_posting_bootstrap(
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
        timestamp="2026-04-08T00:00:00Z",
    )
    seed_outreach_ready_tailoring_run(
        connection,
        paths,
        company_name="Acme Robotics",
        role_title="Staff Software Engineer / AI",
        job_posting_id=job_posting_id,
        current_time="2026-04-08T00:01:00Z",
    )
    seed_shortlisted_contact(
        connection,
        contact_id="ct_feedback_queue",
        job_posting_contact_id="jpc_feedback_queue",
        job_posting_id=job_posting_id,
        company_name="Acme Robotics",
        display_name="Priya Recruiter",
        recipient_type="recruiter",
        current_working_email="priya@acme.example",
        position_title="Technical Recruiter",
        created_at="2026-04-08T00:02:00Z",
    )
    send_single_role_targeted_message(
        connection,
        project_root=project_root,
        job_posting_id=job_posting_id,
        drafted_at="2026-04-08T00:03:00Z",
        sent_at="2026-04-08T00:04:00Z",
    )
    resume_agent(
        connection,
        manual_command="jhc-agent-start",
        timestamp="2026-04-08T00:05:00Z",
    )
    ensure_role_targeted_pipeline_run(
        connection,
        lead_id=lead_id,
        job_posting_id=job_posting_id,
        current_stage="delivery_feedback",
        started_at="2026-04-08T00:06:00Z",
    )
    _, next_job_posting_id = seed_role_targeted_posting(
        connection,
        lead_id="ld_downstream_next",
        job_posting_id="jp_downstream_next",
        lead_identity_key="next-wave-systems|backend-engineer",
        posting_identity_key="next-wave-systems|backend-engineer|remote",
        company_name="Next Wave Systems",
        role_title="Backend Engineer",
        posting_status="sourced",
        timestamp="2026-04-08T00:07:00Z",
    )

    execution = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-04-08T00:10:00Z",
    )
    connection.close()

    assert execution.cycle.result == SUPERVISOR_CYCLE_RESULT_SUCCESS
    assert execution.selected_work is not None
    assert execution.selected_work.action_id == ACTION_BOOTSTRAP_ROLE_TARGETED_RUN
    assert execution.selected_work.job_posting_id == next_job_posting_id
