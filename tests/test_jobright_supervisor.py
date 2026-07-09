from __future__ import annotations

import sqlite3
from dataclasses import replace

from job_hunt_copilot.bootstrap import run_bootstrap
from job_hunt_copilot.jobright_ingestion import (
    JOBRIGHT_BATCH_RESULT_READY,
    JobrightRecommendation,
    JobrightRecommendationBatch,
)
from job_hunt_copilot.paths import ProjectPaths
from job_hunt_copilot.supervisor import (
    SUPERVISOR_CYCLE_RESULT_SUCCESS,
    SupervisorActionDependencies,
    read_agent_control_state,
    resume_agent,
    run_supervisor_cycle,
)
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


class FakeJobrightRecommendationCollector:
    def __init__(self, *batches: JobrightRecommendationBatch) -> None:
        self._pending_batches = list(batches)
        self._prepared_batches: dict[str, JobrightRecommendationBatch] = {}
        self.prepare_calls: list[dict[str, str | None]] = []

    def prepare_batch(
        self,
        *,
        current_time: str,
        last_polled_at: str | None = None,
    ) -> JobrightRecommendationBatch | None:
        self.prepare_calls.append(
            {
                "current_time": current_time,
                "last_polled_at": last_polled_at,
            }
        )
        if self._prepared_batches:
            return next(iter(self._prepared_batches.values()))
        if not self._pending_batches:
            return None
        batch = self._pending_batches.pop(0)
        self._prepared_batches[batch.ingestion_run_id] = batch
        return batch

    def peek_prepared_batch(self, ingestion_run_id: str) -> JobrightRecommendationBatch | None:
        return self._prepared_batches.get(ingestion_run_id)

    def pop_prepared_batch(self, ingestion_run_id: str) -> JobrightRecommendationBatch | None:
        return self._prepared_batches.pop(ingestion_run_id, None)


def _long_jd() -> str:
    return "\n\n".join(
        [
            "About the job",
            "Build backend systems, data workflows, and AI-adjacent product infrastructure in production.",
            "Work with APIs, orchestration, observability, and pragmatic ownership across customer-facing systems.",
            "Operate services in cloud environments with strong attention to reliability, tooling, and measurable delivery.",
            "Partner with product and engineering teammates to translate requirements into shippable implementation plans.",
            "Experience with Python, distributed systems, and production debugging is valuable for this role.",
        ]
    )


def _recommendation() -> JobrightRecommendation:
    return JobrightRecommendation(
        jobright_job_id="jobright-job-002",
        lead_identity_key="jobright:jobright-job-002",
        job_url="https://jobright.ai/jobs/info/jobright-job-002",
        company_name="Signal Stack",
        role_title="Platform Engineer",
        display_score=84.1,
        rank_desc="Good Match",
        location="Remote",
        salary=None,
        apply_url="https://jobs.signalstack.dev/platform-engineer",
        recommendation_scores={"Skill Match": 88},
        skill_matching_scores={"python": 0.9},
        industry_matching_scores={"platform": 0.85},
        jobright_named_contact=None,
        social_connections=[
            {
                "fullName": "Taylor Public",
                "title": "Engineer",
                "linkedinUrl": "https://www.linkedin.com/in/taylor-public/",
                "companyName": "Signal Stack",
                "sourceRank": 1,
            },
            {
                "fullName": "Casey Public",
                "title": "Recruiter",
                "linkedinUrl": "https://www.linkedin.com/in/casey-public/",
                "companyName": "Signal Stack",
                "sourceRank": 2,
            },
        ],
        personal_social_connections=None,
        jd_text=_long_jd(),
        jd_is_usable=True,
        observed_at="2026-06-27T04:01:00Z",
        feed_payload={"jobId": "jobright-job-002", "displayScore": 84.1},
        page_payload={"fetch": {"http_status": 200}, "job_summary": {"title": "Platform Engineer"}},
    )


def test_run_supervisor_cycle_ingests_jobright_batch_into_lead_discovery(tmp_path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    resume_agent(
        connection,
        manual_command="jhc-agent-start",
        timestamp="2026-06-27T04:00:00Z",
    )
    collector = FakeJobrightRecommendationCollector(
        JobrightRecommendationBatch(
            ingestion_run_id="jobright-auto-20260627T040100Z",
            result=JOBRIGHT_BATCH_RESULT_READY,
            collected_at="2026-06-27T04:01:00Z",
            recommendations=(_recommendation(),),
            raw_feed_payload={"jobs": [{"jobId": "jobright-job-002"}]},
        )
    )

    execution = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-06-27T04:01:00Z",
        action_dependencies=SupervisorActionDependencies(
            jobright_recommendation_collector=collector,
            local_timezone="UTC",
        ),
    )

    lead_row = connection.execute(
        """
        SELECT lead_status, source_mode, latest_fit_score
        FROM leads
        ORDER BY created_at ASC, lead_id ASC
        LIMIT 1
        """
    ).fetchone()
    job_posting_count = int(connection.execute("SELECT COUNT(*) FROM job_postings").fetchone()[0] or 0)
    observation_count = int(connection.execute("SELECT COUNT(*) FROM lead_source_observations").fetchone()[0] or 0)
    control_state = read_agent_control_state(connection, timestamp="2026-06-27T04:01:00Z")
    connection.close()

    assert execution.cycle.result == SUPERVISOR_CYCLE_RESULT_SUCCESS
    assert execution.selected_work is not None
    assert execution.selected_work.work_type == "jobright_recommendation_batch"
    assert execution.selected_work.work_id == "jobright-auto-20260627T040100Z"
    assert execution.action_id == "poll_jobright_recommendations"
    assert dict(lead_row) == {
        "lead_status": "discovered",
        "source_mode": "jobright_recommendation",
        "latest_fit_score": 84.1,
    }
    assert job_posting_count == 0
    assert observation_count == 2
    assert control_state.values["jobright_poll_last_run_at"] == "2026-06-27T04:01:00Z"
    assert control_state.values["jobright_poll_last_result"] == "ready"
    assert control_state.values["jobright_last_ingestion_run_id"] == "jobright-auto-20260627T040100Z"
    assert control_state.values["jobright_reauth_required_at"] == ""
    assert paths.jobright_run_summary_path("jobright-auto-20260627T040100Z").exists()


def test_run_supervisor_cycle_promotes_jobright_lead_then_bootstraps_posting(tmp_path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    resume_agent(
        connection,
        manual_command="jhc-agent-start",
        timestamp="2026-06-27T05:00:00Z",
    )
    collector = FakeJobrightRecommendationCollector(
        JobrightRecommendationBatch(
            ingestion_run_id="jobright-auto-20260627T050100Z",
            result=JOBRIGHT_BATCH_RESULT_READY,
            collected_at="2026-06-27T05:01:00Z",
            recommendations=(_recommendation(),),
            raw_feed_payload={"jobs": [{"jobId": "jobright-job-002"}]},
        )
    )

    first_cycle = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-06-27T05:01:00Z",
        action_dependencies=SupervisorActionDependencies(
            jobright_recommendation_collector=collector,
            local_timezone="UTC",
        ),
    )
    second_cycle = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-06-27T05:02:00Z",
        action_dependencies=SupervisorActionDependencies(
            jobright_recommendation_collector=collector,
            local_timezone="UTC",
        ),
    )
    third_cycle = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-06-27T05:03:00Z",
        action_dependencies=SupervisorActionDependencies(
            jobright_recommendation_collector=collector,
            local_timezone="UTC",
        ),
    )

    promoted_lead_row = connection.execute(
        """
        SELECT lead_id, lead_status
        FROM leads
        ORDER BY created_at ASC, lead_id ASC
        LIMIT 1
        """
    ).fetchone()
    posting_row = connection.execute(
        """
        SELECT job_posting_id, posting_status
        FROM job_postings
        WHERE lead_id = ?
        """,
        (promoted_lead_row["lead_id"],),
    ).fetchone()
    pipeline_run_row = connection.execute(
        """
        SELECT run_status, current_stage, job_posting_id
        FROM pipeline_runs
        WHERE job_posting_id = ?
        ORDER BY created_at ASC, pipeline_run_id ASC
        LIMIT 1
        """,
        (posting_row["job_posting_id"],),
    ).fetchone()
    connection.close()

    assert first_cycle.action_id == "poll_jobright_recommendations"
    assert second_cycle.action_id == "promote_jobright_lead"
    assert second_cycle.selected_work is not None
    assert second_cycle.selected_work.work_type == "lead"
    assert third_cycle.action_id == "bootstrap_role_targeted_run"
    assert dict(promoted_lead_row) == {
        "lead_id": promoted_lead_row["lead_id"],
        "lead_status": "promoted",
    }
    assert dict(posting_row) == {
        "job_posting_id": posting_row["job_posting_id"],
        "posting_status": "sourced",
    }
    assert dict(pipeline_run_row) == {
        "run_status": "in_progress",
        "current_stage": "lead_handoff",
        "job_posting_id": posting_row["job_posting_id"],
    }


def test_jobright_seeded_unpromoted_contacts_do_not_enter_general_learning_selection(tmp_path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    resume_agent(
        connection,
        manual_command="jhc-agent-start",
        timestamp="2026-06-27T06:00:00Z",
    )
    base = _recommendation()
    single_public = replace(
        base,
        jobright_job_id="jobright-job-003",
        lead_identity_key="jobright:jobright-job-003",
        job_url="https://jobright.ai/jobs/info/jobright-job-003",
        company_name="Solo Public",
        role_title="Platform Engineer",
        display_score=84.1,
        rank_desc="Good Match",
        social_connections=base.social_connections[:1],
        personal_social_connections=None,
        feed_payload={"jobId": "jobright-job-003", "displayScore": 84.1},
        page_payload={"fetch": {"http_status": 200}, "job_summary": {"title": "Platform Engineer"}},
    )
    collector = FakeJobrightRecommendationCollector(
        JobrightRecommendationBatch(
            ingestion_run_id="jobright-auto-20260627T060100Z",
            result=JOBRIGHT_BATCH_RESULT_READY,
            collected_at="2026-06-27T06:01:00Z",
            recommendations=(single_public,),
            raw_feed_payload={"jobs": [{"jobId": "jobright-job-003"}]},
        )
    )

    first_cycle = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-06-27T06:01:00Z",
        action_dependencies=SupervisorActionDependencies(
            jobright_recommendation_collector=collector,
            local_timezone="UTC",
        ),
    )
    second_cycle = run_supervisor_cycle(
        connection,
        paths,
        trigger_type="launchd_heartbeat",
        scheduler_name="launchd",
        started_at="2026-06-27T06:02:00Z",
        action_dependencies=SupervisorActionDependencies(
            jobright_recommendation_collector=collector,
            local_timezone="UTC",
        ),
    )

    lead_row = connection.execute(
        """
        SELECT lead_status, reason_code
        FROM leads
        WHERE lead_identity_key = 'jobright:jobright-job-003'
        """
    ).fetchone()
    pipeline_run_count = int(connection.execute("SELECT COUNT(*) FROM pipeline_runs").fetchone()[0] or 0)
    connection.close()

    assert first_cycle.action_id == "poll_jobright_recommendations"
    assert second_cycle.cycle.result == "no_work"
    assert second_cycle.selected_work is None
    assert dict(lead_row) == {
        "lead_status": "held",
        "reason_code": "single_public_connection_only",
    }
    assert pipeline_run_count == 0
