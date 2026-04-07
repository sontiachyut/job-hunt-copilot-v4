from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import yaml

from job_hunt_copilot.bootstrap import run_bootstrap
from job_hunt_copilot.paths import ProjectPaths
from job_hunt_copilot.resume_tailoring import (
    BOOTSTRAP_REASON_MISSING_JD,
    ELIGIBILITY_STATUS_ELIGIBLE,
    ELIGIBILITY_STATUS_HARD_INELIGIBLE,
    ELIGIBILITY_STATUS_SOFT_FLAG,
    ELIGIBILITY_STATUS_UNKNOWN,
    FINALIZE_REASON_SCOPE_VIOLATION,
    JOB_POSTING_STATUS_HARD_INELIGIBLE,
    JOB_POSTING_STATUS_READY_FOR_OUTREACH,
    JOB_POSTING_STATUS_REQUIRES_CONTACTS,
    JOB_POSTING_STATUS_RESUME_REVIEW_PENDING,
    JOB_POSTING_STATUS_TAILORING_IN_PROGRESS,
    MANDATORY_REVIEWER_AGENT,
    MANDATORY_REVIEWER_OWNER,
    RESUME_REVIEW_STATUS_NOT_READY,
    RESUME_REVIEW_STATUS_APPROVED,
    RESUME_REVIEW_STATUS_PENDING,
    RESUME_REVIEW_STATUS_REJECTED,
    TAILORING_ELIGIBILITY_ARTIFACT_TYPE,
    TAILORING_META_ARTIFACT_TYPE,
    TAILORING_REVIEW_ARTIFACT_TYPE,
    TAILORING_STATUS_NEEDS_REVISION,
    TAILORING_STATUS_IN_PROGRESS,
    TAILORING_STATUS_TAILORED,
    bootstrap_tailoring_run,
    finalize_tailoring_run,
    generate_tailoring_intelligence,
    record_tailoring_review_decision,
    record_tailoring_review_override,
)
from tests.support import create_minimal_project

REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_PROFILE_PATH = REPO_ROOT / "assets" / "resume-tailoring" / "profile.md"
REAL_BASE_RESUME_PATH = (
    REPO_ROOT / "assets" / "resume-tailoring" / "base" / "distributed-infra" / "base-resume.tex"
)


def bootstrap_project(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    create_minimal_project(project_root)
    run_bootstrap(project_root=project_root)
    return project_root


def bootstrap_project_with_real_tailoring_assets(tmp_path):
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

    run_bootstrap(project_root=project_root)
    return project_root


def connect_database(db_path):
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    return connection


def seed_posting(
    connection,
    paths: ProjectPaths,
    *,
    job_posting_id: str = "jp_test",
    lead_id: str = "ld_test",
    company_name: str = "Guidewire Software, Inc.",
    role_title: str = "Staff Software Engineer / AI",
    posting_status: str = "sourced",
    jd_body: str | None,
    post_body: str | None = None,
    poster_profile_body: str | None = None,
    timestamp: str = "2026-04-06T20:00:00Z",
):
    lead_workspace = paths.lead_workspace_dir(company_name, role_title, lead_id)
    jd_path = lead_workspace / "jd.md"
    jd_artifact_path = None
    if jd_body is not None:
        jd_path.parent.mkdir(parents=True, exist_ok=True)
        jd_path.write_text(jd_body, encoding="utf-8")
        jd_artifact_path = paths.relative_to_root(jd_path).as_posix()
    if post_body is not None:
        (lead_workspace / "post.md").write_text(post_body, encoding="utf-8")
    if poster_profile_body is not None:
        (lead_workspace / "poster-profile.md").write_text(poster_profile_body, encoding="utf-8")

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
            "guidewire|staff-software-engineer-ai",
            "handed_off",
            "posting_only",
            "not_applicable",
            "gmail_job_alert",
            "gmail/message/123",
            "gmail_job_alert",
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
            "guidewire|staff-software-engineer-ai|remote",
            company_name,
            role_title,
            posting_status,
            jd_artifact_path,
            timestamp,
            timestamp,
        ),
    )
    connection.commit()
    return jd_path


def seed_linked_contact(
    connection,
    *,
    job_posting_id: str = "jp_test",
    contact_id: str = "ct_test",
    recipient_type: str = "recruiter",
    current_working_email: str | None = None,
    company_name: str = "Acme Data Systems",
    timestamp: str = "2026-04-06T20:30:00Z",
):
    connection.execute(
        """
        INSERT INTO contacts (
          contact_id, identity_key, display_name, company_name, origin_component,
          contact_status, full_name, current_working_email, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            contact_id,
            f"contact|{contact_id}",
            "Jordan Recruiter",
            company_name,
            "linkedin_scraping",
            "identified",
            "Jordan Recruiter",
            current_working_email,
            timestamp,
            timestamp,
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
            f"jpc_{contact_id}",
            job_posting_id,
            contact_id,
            recipient_type,
            "seeded review-ready contact",
            "identified",
            timestamp,
            timestamp,
        ),
    )
    connection.commit()


def prepare_real_tailoring_run(tmp_path, *, jd_body: str):
    project_root = bootstrap_project_with_real_tailoring_assets(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_posting(
        connection,
        paths,
        jd_body=jd_body,
        company_name="Acme Data Systems",
        role_title="Software Engineer",
        timestamp="2026-04-06T20:00:00Z",
    )
    bootstrap_result = bootstrap_tailoring_run(
        connection,
        paths,
        job_posting_id="jp_test",
        timestamp="2026-04-06T20:05:00Z",
    )
    assert bootstrap_result.run is not None
    return project_root, paths, connection, bootstrap_result


def test_bootstrap_tailoring_run_creates_workspace_metadata_and_scaffolds(tmp_path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_posting(
        connection,
        paths,
        jd_body=(
            "# JD\n"
            "Requirements\n"
            "- 3+ years of software engineering experience.\n"
            "- Build AI-powered web applications with React and Python.\n"
        ),
        post_body="# Post\nHiring for an AI-focused platform team.\n",
        poster_profile_body="# Poster\nPlatform engineering manager.\n",
    )

    result = bootstrap_tailoring_run(
        connection,
        paths,
        job_posting_id="jp_test",
        timestamp="2026-04-06T20:10:00Z",
    )

    assert result.eligibility.eligibility_status == ELIGIBILITY_STATUS_ELIGIBLE
    assert result.blocked_reason_code is None
    assert result.run is not None
    assert result.run.base_used == "generalist"
    assert result.run.tailoring_status == TAILORING_STATUS_IN_PROGRESS
    assert result.run.resume_review_status == RESUME_REVIEW_STATUS_NOT_READY
    assert result.run.workspace_path == paths.relative_to_root(
        paths.tailoring_workspace_dir("Guidewire Software, Inc.", "Staff Software Engineer / AI")
    ).as_posix()
    assert result.run.meta_yaml_path == paths.relative_to_root(
        paths.tailoring_meta_path("Guidewire Software, Inc.", "Staff Software Engineer / AI")
    ).as_posix()

    eligibility_payload = yaml.safe_load(
        paths.tailoring_eligibility_path(
            "Guidewire Software, Inc.",
            "Staff Software Engineer / AI",
        ).read_text(encoding="utf-8")
    )
    assert eligibility_payload["job_posting_id"] == "jp_test"
    assert eligibility_payload["eligibility_status"] == ELIGIBILITY_STATUS_ELIGIBLE
    assert eligibility_payload["bootstrap_ready"] is True
    assert eligibility_payload["active_resume_tailoring_run_id"] == result.run.resume_tailoring_run_id

    workspace_dir = paths.tailoring_workspace_dir(
        "Guidewire Software, Inc.",
        "Staff Software Engineer / AI",
    )
    resume_tex_path = paths.tailoring_resume_tex_path(
        "Guidewire Software, Inc.",
        "Staff Software Engineer / AI",
    )
    scope_baseline_path = paths.tailoring_scope_baseline_path(
        "Guidewire Software, Inc.",
        "Staff Software Engineer / AI",
    )
    workspace_jd_path = paths.tailoring_workspace_jd_path(
        "Guidewire Software, Inc.",
        "Staff Software Engineer / AI",
    )
    workspace_post_path = paths.tailoring_workspace_post_path(
        "Guidewire Software, Inc.",
        "Staff Software Engineer / AI",
    )
    workspace_poster_profile_path = paths.tailoring_workspace_poster_profile_path(
        "Guidewire Software, Inc.",
        "Staff Software Engineer / AI",
    )
    input_profile_path = paths.tailoring_input_profile_path
    input_job_posting_path = paths.tailoring_input_job_posting_path(
        "Guidewire Software, Inc.",
        "Staff Software Engineer / AI",
    )
    intelligence_manifest_path = paths.tailoring_intelligence_manifest_path(
        "Guidewire Software, Inc.",
        "Staff Software Engineer / AI",
    )
    step_3_path = paths.tailoring_step_3_jd_signals_path(
        "Guidewire Software, Inc.",
        "Staff Software Engineer / AI",
    )
    step_4_path = paths.tailoring_step_4_evidence_map_path(
        "Guidewire Software, Inc.",
        "Staff Software Engineer / AI",
    )
    step_5_path = paths.tailoring_step_5_context_path(
        "Guidewire Software, Inc.",
        "Staff Software Engineer / AI",
    )
    step_6_path = paths.tailoring_step_6_candidate_bullets_path(
        "Guidewire Software, Inc.",
        "Staff Software Engineer / AI",
    )
    step_7_path = paths.tailoring_step_7_verification_path(
        "Guidewire Software, Inc.",
        "Staff Software Engineer / AI",
    )
    prompts_dir = paths.tailoring_prompts_dir(
        "Guidewire Software, Inc.",
        "Staff Software Engineer / AI",
    )
    meta_payload = yaml.safe_load(
        paths.tailoring_meta_path(
            "Guidewire Software, Inc.",
            "Staff Software Engineer / AI",
        ).read_text(encoding="utf-8")
    )

    assert workspace_dir.is_dir()
    assert resume_tex_path.read_text(encoding="utf-8") == "% resume\n"
    assert scope_baseline_path.read_text(encoding="utf-8") == "% resume\n"
    assert workspace_jd_path.read_text(encoding="utf-8").startswith("# JD")
    assert workspace_post_path.read_text(encoding="utf-8") == "# Post\nHiring for an AI-focused platform team.\n"
    assert workspace_poster_profile_path.read_text(encoding="utf-8") == (
        "# Poster\nPlatform engineering manager.\n"
    )
    assert input_profile_path.read_text(encoding="utf-8") == "# profile\n"
    assert input_job_posting_path.read_text(encoding="utf-8").startswith("# JD")

    assert meta_payload["contract_version"] == "1.0"
    assert meta_payload["producer_component"] == "resume_tailoring"
    assert meta_payload["result"] == "success"
    assert meta_payload["job_posting_id"] == "jp_test"
    assert meta_payload["resume_tailoring_run_id"] == result.run.resume_tailoring_run_id
    assert meta_payload["base_used"] == "generalist"
    assert meta_payload["context_file"] == str(workspace_jd_path.resolve())
    assert meta_payload["scope_baseline_file"] == str(scope_baseline_path.resolve())
    assert meta_payload["section_locks"] == [
        "education",
        "projects",
        "awards-and-leadership",
    ]
    assert meta_payload["experience_role_allowlist"] == ["software-engineer"]
    assert meta_payload["resume_artifacts"]["tex_path"] == str(resume_tex_path.resolve())
    assert meta_payload["send_linkage"] == {
        "outreach_mode": "role_targeted",
        "resume_required": True,
    }

    manifest_payload = yaml.safe_load(intelligence_manifest_path.read_text(encoding="utf-8"))
    step_3_payload = yaml.safe_load(step_3_path.read_text(encoding="utf-8"))
    step_4_payload = yaml.safe_load(step_4_path.read_text(encoding="utf-8"))
    step_6_payload = yaml.safe_load(step_6_path.read_text(encoding="utf-8"))
    step_7_payload = yaml.safe_load(step_7_path.read_text(encoding="utf-8"))

    assert manifest_payload["steps"]["step_3_jd_signals"]["status"] == "not_started"
    assert manifest_payload["steps"]["step_7_verification"]["status"] == "pending"
    assert step_3_payload["status"] == "not_started"
    assert step_4_payload["status"] == "not_started"
    assert step_6_payload["status"] == "not_started"
    assert step_7_payload["verification_outcome"] == "pending"
    assert "Not generated yet." in step_5_path.read_text(encoding="utf-8")
    assert prompts_dir.is_dir()

    artifact_record = connection.execute(
        """
        SELECT artifact_type, file_path, lead_id, job_posting_id
        FROM artifact_records
        WHERE artifact_type = ?
        """,
        (TAILORING_ELIGIBILITY_ARTIFACT_TYPE,),
    ).fetchone()
    assert dict(artifact_record) == {
        "artifact_type": TAILORING_ELIGIBILITY_ARTIFACT_TYPE,
        "file_path": paths.relative_to_root(
            paths.tailoring_eligibility_path(
                "Guidewire Software, Inc.",
                "Staff Software Engineer / AI",
            )
        ).as_posix(),
        "lead_id": "ld_test",
        "job_posting_id": "jp_test",
    }
    meta_record = connection.execute(
        """
        SELECT artifact_type, file_path, lead_id, job_posting_id
        FROM artifact_records
        WHERE artifact_type = ?
        """,
        (TAILORING_META_ARTIFACT_TYPE,),
    ).fetchone()
    assert dict(meta_record) == {
        "artifact_type": TAILORING_META_ARTIFACT_TYPE,
        "file_path": paths.relative_to_root(
            paths.tailoring_meta_path(
                "Guidewire Software, Inc.",
                "Staff Software Engineer / AI",
            )
        ).as_posix(),
        "lead_id": "ld_test",
        "job_posting_id": "jp_test",
    }

    transitions = connection.execute(
        """
        SELECT object_type, stage, previous_state, new_state
        FROM state_transition_events
        WHERE object_id = ?
        ORDER BY stage ASC
        """,
        (result.run.resume_tailoring_run_id,),
    ).fetchall()
    assert [dict(row) for row in transitions] == [
        {
            "object_type": "resume_tailoring_runs",
            "stage": "resume_review_status",
            "previous_state": "not_created",
            "new_state": RESUME_REVIEW_STATUS_NOT_READY,
        },
        {
            "object_type": "resume_tailoring_runs",
            "stage": "tailoring_status",
            "previous_state": "not_created",
            "new_state": TAILORING_STATUS_IN_PROGRESS,
        },
    ]


def test_hard_ineligible_posting_updates_posting_and_skips_run_creation(tmp_path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_posting(
        connection,
        paths,
        jd_body=(
            "# JD\n"
            "Qualifications\n"
            "- 7+ years of professional software engineering experience required.\n"
            "- U.S. citizenship required.\n"
        ),
    )

    result = bootstrap_tailoring_run(
        connection,
        paths,
        job_posting_id="jp_test",
        timestamp="2026-04-06T20:10:00Z",
    )

    assert result.eligibility.eligibility_status == ELIGIBILITY_STATUS_HARD_INELIGIBLE
    assert result.run is None
    assert result.blocked_reason_code is None
    stored_posting = connection.execute(
        "SELECT posting_status FROM job_postings WHERE job_posting_id = ?",
        ("jp_test",),
    ).fetchone()
    assert stored_posting["posting_status"] == JOB_POSTING_STATUS_HARD_INELIGIBLE
    assert connection.execute("SELECT COUNT(*) FROM resume_tailoring_runs").fetchone()[0] == 0

    artifact_payload = yaml.safe_load(
        paths.tailoring_eligibility_path(
            "Guidewire Software, Inc.",
            "Staff Software Engineer / AI",
        ).read_text(encoding="utf-8")
    )
    assert artifact_payload["eligibility_status"] == ELIGIBILITY_STATUS_HARD_INELIGIBLE
    assert artifact_payload["hard_disqualifiers_triggered"] == [
        "experience_gt_5_years",
        "citizenship_required",
    ]
    assert artifact_payload["bootstrap_ready"] is False

    transition = connection.execute(
        """
        SELECT previous_state, new_state, stage
        FROM state_transition_events
        WHERE object_type = 'job_postings' AND object_id = ?
        """,
        ("jp_test",),
    ).fetchone()
    assert dict(transition) == {
        "previous_state": "sourced",
        "new_state": JOB_POSTING_STATUS_HARD_INELIGIBLE,
        "stage": "posting_status",
    }


def test_unknown_eligibility_allows_bootstrap_when_hard_signals_are_missing(tmp_path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_posting(
        connection,
        paths,
        jd_body=(
            "# JD\n"
            "What you'll do\n"
            "- Build AI experiences for support workflows.\n"
            "- Partner with product and data teams.\n"
        ),
    )

    result = bootstrap_tailoring_run(
        connection,
        paths,
        job_posting_id="jp_test",
        timestamp="2026-04-06T20:10:00Z",
    )

    assert result.eligibility.eligibility_status == ELIGIBILITY_STATUS_UNKNOWN
    assert result.run is not None
    assert result.blocked_reason_code is None
    artifact_payload = yaml.safe_load(
        result.eligibility_artifact.location.absolute_path.read_text(encoding="utf-8")
    )
    assert artifact_payload["missing_data_fields"] == [
        "experience_requirement",
        "citizenship_or_clearance_requirement",
    ]


def test_soft_flag_preserves_eligibility_and_recommended_note(tmp_path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_posting(
        connection,
        paths,
        jd_body=(
            "# JD\n"
            "Minimum qualifications\n"
            "- 4+ years of software engineering experience.\n"
            "- Must be authorized to work in the United States without visa sponsorship.\n"
        ),
    )

    result = bootstrap_tailoring_run(
        connection,
        paths,
        job_posting_id="jp_test",
        timestamp="2026-04-06T20:10:00Z",
    )

    assert result.eligibility.eligibility_status == ELIGIBILITY_STATUS_SOFT_FLAG
    assert result.run is not None
    assert result.eligibility.recommended_note is not None
    artifact_payload = yaml.safe_load(
        result.eligibility_artifact.location.absolute_path.read_text(encoding="utf-8")
    )
    assert artifact_payload["soft_flags"] == ["no_sponsorship"]


def test_missing_jd_blocks_honestly_without_creating_a_run(tmp_path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_posting(connection, paths, jd_body=None)

    result = bootstrap_tailoring_run(
        connection,
        paths,
        job_posting_id="jp_test",
        timestamp="2026-04-06T20:10:00Z",
    )

    assert result.eligibility.eligibility_status == ELIGIBILITY_STATUS_UNKNOWN
    assert result.run is None
    assert result.blocked_reason_code == BOOTSTRAP_REASON_MISSING_JD
    assert result.eligibility_artifact.contract["result"] == "blocked"
    assert result.eligibility_artifact.contract["reason_code"] == BOOTSTRAP_REASON_MISSING_JD
    assert connection.execute("SELECT COUNT(*) FROM resume_tailoring_runs").fetchone()[0] == 0


def test_bootstrap_backfills_workspace_for_existing_run_without_meta(tmp_path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_posting(
        connection,
        paths,
        jd_body=(
            "# JD\n"
            "Qualifications\n"
            "- 4 years of software engineering experience.\n"
        ),
    )
    connection.execute(
        """
        INSERT INTO resume_tailoring_runs (
          resume_tailoring_run_id, job_posting_id, base_used, tailoring_status,
          resume_review_status, workspace_path, meta_yaml_path, final_resume_path,
          verification_outcome, started_at, completed_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "rtr_existing",
            "jp_test",
            "generalist",
            "in_progress",
            "not_ready",
            paths.relative_to_root(
                paths.tailoring_workspace_dir(
                    "Guidewire Software, Inc.",
                    "Staff Software Engineer / AI",
                )
            ).as_posix(),
            None,
            None,
            None,
            "2026-04-06T20:00:00Z",
            None,
            "2026-04-06T20:00:00Z",
            "2026-04-06T20:00:00Z",
        ),
    )
    connection.commit()

    result = bootstrap_tailoring_run(
        connection,
        paths,
        job_posting_id="jp_test",
        timestamp="2026-04-06T20:10:00Z",
    )

    assert result.run is not None
    assert result.reused_existing_run is True
    assert result.run.resume_tailoring_run_id == "rtr_existing"
    assert result.run.meta_yaml_path == paths.relative_to_root(
        paths.tailoring_meta_path(
            "Guidewire Software, Inc.",
            "Staff Software Engineer / AI",
        )
    ).as_posix()
    assert paths.tailoring_resume_tex_path(
        "Guidewire Software, Inc.",
        "Staff Software Engineer / AI",
    ).exists()
    assert paths.tailoring_intelligence_manifest_path(
        "Guidewire Software, Inc.",
        "Staff Software Engineer / AI",
    ).exists()


def test_bootstrap_reuses_existing_run_instead_of_creating_duplicates(tmp_path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_posting(
        connection,
        paths,
        jd_body=(
            "# JD\n"
            "Qualifications\n"
            "- 5 years of software engineering experience.\n"
        ),
    )

    first = bootstrap_tailoring_run(
        connection,
        paths,
        job_posting_id="jp_test",
        timestamp="2026-04-06T20:10:00Z",
    )
    assert first.run is not None
    resume_tex_path = paths.tailoring_resume_tex_path(
        "Guidewire Software, Inc.",
        "Staff Software Engineer / AI",
    )
    step_3_path = paths.tailoring_step_3_jd_signals_path(
        "Guidewire Software, Inc.",
        "Staff Software Engineer / AI",
    )
    resume_tex_path.write_text("% manually edited resume\n", encoding="utf-8")
    step_3_path.write_text("status: generated\nsignals:\n  - jd: python\n", encoding="utf-8")
    second = bootstrap_tailoring_run(
        connection,
        paths,
        job_posting_id="jp_test",
        timestamp="2026-04-06T20:15:00Z",
    )

    assert second.run is not None
    assert second.reused_existing_run is True
    assert first.run.resume_tailoring_run_id == second.run.resume_tailoring_run_id
    assert connection.execute("SELECT COUNT(*) FROM resume_tailoring_runs").fetchone()[0] == 1
    assert resume_tex_path.read_text(encoding="utf-8") == "% manually edited resume\n"
    assert step_3_path.read_text(encoding="utf-8") == "status: generated\nsignals:\n  - jd: python\n"


def test_generate_tailoring_intelligence_populates_step_artifacts_and_keeps_run_active(tmp_path):
    _, paths, connection, bootstrap_result = prepare_real_tailoring_run(
        tmp_path,
        jd_body=(
            "# JD\n"
            "Requirements\n"
            "- 3+ years of software engineering experience.\n"
            "- Build distributed data services in Python and Apache Spark on AWS.\n"
            "- Own monitoring, reliability, and incident response for production pipelines.\n"
            "Preferred Qualifications\n"
            "- Kubernetes exposure.\n"
        ),
    )

    result = generate_tailoring_intelligence(
        connection,
        paths,
        job_posting_id="jp_test",
        timestamp="2026-04-06T20:10:00Z",
    )

    assert result.track_name == "distributed_infra"
    assert result.verification_outcome == "pass"
    assert result.resume_tailoring_run_id == bootstrap_result.run.resume_tailoring_run_id

    step_3_payload = yaml.safe_load(
        paths.tailoring_step_3_jd_signals_path("Acme Data Systems", "Software Engineer").read_text(
            encoding="utf-8"
        )
    )
    step_4_payload = yaml.safe_load(
        paths.tailoring_step_4_evidence_map_path("Acme Data Systems", "Software Engineer").read_text(
            encoding="utf-8"
        )
    )
    step_6_payload = yaml.safe_load(
        paths.tailoring_step_6_candidate_bullets_path("Acme Data Systems", "Software Engineer").read_text(
            encoding="utf-8"
        )
    )
    step_7_payload = yaml.safe_load(
        paths.tailoring_step_7_verification_path("Acme Data Systems", "Software Engineer").read_text(
            encoding="utf-8"
        )
    )

    assert step_3_payload["status"] == "generated"
    assert len(step_3_payload["signals"]) >= 3
    assert step_4_payload["status"] == "generated"
    assert step_4_payload["matches"]
    assert step_6_payload["status"] == "generated"
    assert len(step_6_payload["software_engineer"]["bullets"]) == 4
    assert step_7_payload["verification_outcome"] == "pass"
    assert "pending" not in {check["status"] for check in step_7_payload["checks"]}

    run_row = connection.execute(
        """
        SELECT tailoring_status, resume_review_status
        FROM resume_tailoring_runs
        WHERE resume_tailoring_run_id = ?
        """,
        (bootstrap_result.run.resume_tailoring_run_id,),
    ).fetchone()
    assert dict(run_row) == {
        "tailoring_status": TAILORING_STATUS_IN_PROGRESS,
        "resume_review_status": RESUME_REVIEW_STATUS_NOT_READY,
    }
    posting_row = connection.execute(
        "SELECT posting_status FROM job_postings WHERE job_posting_id = ?",
        ("jp_test",),
    ).fetchone()
    assert posting_row["posting_status"] == JOB_POSTING_STATUS_TAILORING_IN_PROGRESS


def test_finalize_tailoring_run_applies_payload_compiles_pdf_and_updates_status(tmp_path):
    _, paths, connection, bootstrap_result = prepare_real_tailoring_run(
        tmp_path,
        jd_body=(
            "# JD\n"
            "Requirements\n"
            "- 3+ years of software engineering experience.\n"
            "- Build distributed data services in Python and Apache Spark on AWS.\n"
            "- Own monitoring, reliability, and incident response for production pipelines.\n"
            "Nice to Have\n"
            "- Kubernetes exposure.\n"
        ),
    )
    generate_tailoring_intelligence(
        connection,
        paths,
        job_posting_id="jp_test",
        timestamp="2026-04-06T20:10:00Z",
    )

    result = finalize_tailoring_run(
        connection,
        paths,
        job_posting_id="jp_test",
        timestamp="2026-04-06T20:20:00Z",
    )

    assert result.result == "pass"
    assert result.reason_code is None
    assert result.run.tailoring_status == TAILORING_STATUS_TAILORED
    assert result.run.resume_review_status == RESUME_REVIEW_STATUS_PENDING
    assert result.verification_outcome == "pass"
    assert result.run.resume_tailoring_run_id == bootstrap_result.run.resume_tailoring_run_id

    final_pdf_path = paths.resolve_from_root(result.final_resume_path)
    assert final_pdf_path.exists()
    assert final_pdf_path.name == "Achyutaram Sonti.pdf"
    meta_payload = yaml.safe_load(
        paths.tailoring_meta_path("Acme Data Systems", "Software Engineer").read_text(
            encoding="utf-8"
        )
    )
    step_7_payload = yaml.safe_load(
        paths.tailoring_step_7_verification_path("Acme Data Systems", "Software Engineer").read_text(
            encoding="utf-8"
        )
    )
    assert meta_payload["tailoring_status"] == TAILORING_STATUS_TAILORED
    assert meta_payload["resume_review_status"] == RESUME_REVIEW_STATUS_PENDING
    assert meta_payload["resume_artifacts"]["pdf_path"] == str(final_pdf_path.resolve())
    assert step_7_payload["verification_outcome"] == "pass"
    assert step_7_payload["page_count"] == 1

    stored_posting = connection.execute(
        "SELECT posting_status FROM job_postings WHERE job_posting_id = ?",
        ("jp_test",),
    ).fetchone()
    assert stored_posting["posting_status"] == JOB_POSTING_STATUS_RESUME_REVIEW_PENDING

    transitions = connection.execute(
        """
        SELECT stage, previous_state, new_state
        FROM state_transition_events
        WHERE object_id = ?
        ORDER BY transition_timestamp ASC, state_transition_event_id ASC
        """,
        (result.run.resume_tailoring_run_id,),
    ).fetchall()
    assert {
        (row["stage"], row["previous_state"], row["new_state"])
        for row in transitions
    } >= {
        (
            "tailoring_status",
            TAILORING_STATUS_IN_PROGRESS,
            TAILORING_STATUS_TAILORED,
        ),
        (
            "resume_review_status",
            RESUME_REVIEW_STATUS_NOT_READY,
            RESUME_REVIEW_STATUS_PENDING,
        ),
    }


def test_mandatory_agent_review_approval_moves_posting_to_requires_contacts(tmp_path):
    _, paths, connection, bootstrap_result = prepare_real_tailoring_run(
        tmp_path,
        jd_body=(
            "# JD\n"
            "Requirements\n"
            "- 3+ years of software engineering experience.\n"
            "- Build distributed data services in Python and Apache Spark on AWS.\n"
            "- Own monitoring and reliability for production pipelines.\n"
        ),
    )
    generate_tailoring_intelligence(
        connection,
        paths,
        job_posting_id="jp_test",
        timestamp="2026-04-06T20:10:00Z",
    )
    finalize_tailoring_run(
        connection,
        paths,
        job_posting_id="jp_test",
        timestamp="2026-04-06T20:20:00Z",
    )

    review_result = record_tailoring_review_decision(
        connection,
        paths,
        job_posting_id="jp_test",
        decision_type=RESUME_REVIEW_STATUS_APPROVED,
        decision_notes="Agent approved the tailored resume for downstream discovery.",
        reviewer_type=MANDATORY_REVIEWER_AGENT,
        timestamp="2026-04-06T20:25:00Z",
    )

    assert review_result.run.resume_tailoring_run_id == bootstrap_result.run.resume_tailoring_run_id
    assert review_result.run.resume_review_status == RESUME_REVIEW_STATUS_APPROVED
    assert review_result.posting_status == JOB_POSTING_STATUS_REQUIRES_CONTACTS
    review_payload = yaml.safe_load(
        review_result.review_artifact.location.absolute_path.read_text(encoding="utf-8")
    )
    assert review_payload["reviewer_type"] == MANDATORY_REVIEWER_AGENT
    assert review_payload["decision_type"] == RESUME_REVIEW_STATUS_APPROVED
    assert review_payload["outreach_handoff"]["ready_for_outreach"] is False
    assert review_payload["new_posting_status"] == JOB_POSTING_STATUS_REQUIRES_CONTACTS

    stored_posting = connection.execute(
        "SELECT posting_status FROM job_postings WHERE job_posting_id = ?",
        ("jp_test",),
    ).fetchone()
    assert stored_posting["posting_status"] == JOB_POSTING_STATUS_REQUIRES_CONTACTS

    meta_payload = yaml.safe_load(
        paths.tailoring_meta_path("Acme Data Systems", "Software Engineer").read_text(
            encoding="utf-8"
        )
    )
    assert meta_payload["resume_review_status"] == RESUME_REVIEW_STATUS_APPROVED
    assert meta_payload["review_gate"]["latest_decision_type"] == RESUME_REVIEW_STATUS_APPROVED

    artifact_rows = connection.execute(
        """
        SELECT artifact_type
        FROM artifact_records
        WHERE job_posting_id = ?
          AND artifact_type = ?
        """,
        ("jp_test", TAILORING_REVIEW_ARTIFACT_TYPE),
    ).fetchall()
    assert len(artifact_rows) == 1

    transitions = connection.execute(
        """
        SELECT object_type, stage, previous_state, new_state
        FROM state_transition_events
        WHERE job_posting_id = ?
        ORDER BY transition_timestamp ASC, state_transition_event_id ASC
        """,
        ("jp_test",),
    ).fetchall()
    assert {
        (row["object_type"], row["stage"], row["previous_state"], row["new_state"])
        for row in transitions
    } >= {
        (
            "resume_tailoring_runs",
            "resume_review_status",
            RESUME_REVIEW_STATUS_PENDING,
            RESUME_REVIEW_STATUS_APPROVED,
        ),
        (
            "job_postings",
            "posting_status",
            JOB_POSTING_STATUS_RESUME_REVIEW_PENDING,
            JOB_POSTING_STATUS_REQUIRES_CONTACTS,
        ),
    }


def test_mandatory_agent_review_can_move_directly_to_ready_for_outreach(tmp_path):
    _, paths, connection, _ = prepare_real_tailoring_run(
        tmp_path,
        jd_body=(
            "# JD\n"
            "Requirements\n"
            "- 3+ years of software engineering experience.\n"
            "- Build distributed data services in Python and Apache Spark on AWS.\n"
            "- Own monitoring and reliability for production pipelines.\n"
        ),
    )
    generate_tailoring_intelligence(
        connection,
        paths,
        job_posting_id="jp_test",
        timestamp="2026-04-06T20:10:00Z",
    )
    finalize_tailoring_run(
        connection,
        paths,
        job_posting_id="jp_test",
        timestamp="2026-04-06T20:20:00Z",
    )
    seed_linked_contact(
        connection,
        job_posting_id="jp_test",
        contact_id="ct_ready",
        recipient_type="recruiter",
        current_working_email="jordan@example.com",
        timestamp="2026-04-06T20:22:00Z",
    )

    review_result = record_tailoring_review_decision(
        connection,
        paths,
        job_posting_id="jp_test",
        decision_type=RESUME_REVIEW_STATUS_APPROVED,
        reviewer_type=MANDATORY_REVIEWER_AGENT,
        timestamp="2026-04-06T20:25:00Z",
    )

    assert review_result.posting_status == JOB_POSTING_STATUS_READY_FOR_OUTREACH
    review_payload = yaml.safe_load(
        review_result.review_artifact.location.absolute_path.read_text(encoding="utf-8")
    )
    assert review_payload["outreach_handoff"] == {
        "posting_status_after_review": JOB_POSTING_STATUS_READY_FOR_OUTREACH,
        "ready_for_outreach": True,
        "selected_tier": "primary",
        "selected_recipient_types": ["hiring_manager", "recruiter", "founder"],
        "linked_contacts_in_selected_tier": 1,
        "linked_contacts_with_usable_email": 1,
    }


def test_review_override_records_prior_decision_context_and_applies_new_status(tmp_path):
    _, paths, connection, bootstrap_result = prepare_real_tailoring_run(
        tmp_path,
        jd_body=(
            "# JD\n"
            "Requirements\n"
            "- 3+ years of software engineering experience.\n"
            "- Build distributed data services in Python and Apache Spark on AWS.\n"
            "- Own monitoring and reliability for production pipelines.\n"
        ),
    )
    generate_tailoring_intelligence(
        connection,
        paths,
        job_posting_id="jp_test",
        timestamp="2026-04-06T20:10:00Z",
    )
    finalize_tailoring_run(
        connection,
        paths,
        job_posting_id="jp_test",
        timestamp="2026-04-06T20:20:00Z",
    )
    rejected = record_tailoring_review_decision(
        connection,
        paths,
        job_posting_id="jp_test",
        decision_type=RESUME_REVIEW_STATUS_REJECTED,
        decision_notes="Agent rejected the output because the summary framing needs revision.",
        reviewer_type=MANDATORY_REVIEWER_AGENT,
        timestamp="2026-04-06T20:25:00Z",
    )

    override_result = record_tailoring_review_override(
        connection,
        paths,
        job_posting_id="jp_test",
        decision_type=RESUME_REVIEW_STATUS_APPROVED,
        override_reason="Owner approved the tailored output for contact discovery.",
        override_by=MANDATORY_REVIEWER_OWNER,
        timestamp="2026-04-06T20:30:00Z",
    )

    assert override_result.run.resume_tailoring_run_id == bootstrap_result.run.resume_tailoring_run_id
    assert override_result.run.resume_review_status == RESUME_REVIEW_STATUS_APPROVED
    assert override_result.posting_status == JOB_POSTING_STATUS_REQUIRES_CONTACTS
    assert override_result.override_event is not None
    assert override_result.override_event.override_reason == (
        "Owner approved the tailored output for contact discovery."
    )
    previous_value = yaml.safe_load(override_result.review_artifact.location.absolute_path.read_text(encoding="utf-8"))
    assert previous_value["previous_decision_context"] == {
        "decision_type": RESUME_REVIEW_STATUS_REJECTED,
        "reviewer_type": MANDATORY_REVIEWER_AGENT,
        "reviewed_at": "2026-04-06T20:25:00Z",
        "artifact_path": rejected.review_artifact.location.relative_path,
        "override_event_id": None,
    }

    stored_override = connection.execute(
        """
        SELECT previous_value, new_value, override_reason, override_timestamp
        FROM override_events
        WHERE override_event_id = ?
        """,
        (override_result.override_event.override_event_id,),
    ).fetchone()
    assert stored_override["override_reason"] == "Owner approved the tailored output for contact discovery."
    assert stored_override["override_timestamp"] == "2026-04-06T20:30:00Z"
    previous_payload = yaml.safe_load(stored_override["previous_value"])
    new_payload = yaml.safe_load(stored_override["new_value"])
    assert previous_payload["decision_context"]["decision_type"] == RESUME_REVIEW_STATUS_REJECTED
    assert new_payload["resume_review_status"] == RESUME_REVIEW_STATUS_APPROVED
    assert new_payload["posting_status"] == JOB_POSTING_STATUS_REQUIRES_CONTACTS


def test_retailoring_after_review_rejection_creates_new_run_and_snapshots_history(tmp_path):
    _, paths, connection, bootstrap_result = prepare_real_tailoring_run(
        tmp_path,
        jd_body=(
            "# JD\n"
            "Requirements\n"
            "- 3+ years of software engineering experience.\n"
            "- Build distributed data services in Python and Apache Spark on AWS.\n"
            "- Own monitoring and reliability for production pipelines.\n"
        ),
    )
    generate_tailoring_intelligence(
        connection,
        paths,
        job_posting_id="jp_test",
        timestamp="2026-04-06T20:10:00Z",
    )
    finalize_tailoring_run(
        connection,
        paths,
        job_posting_id="jp_test",
        timestamp="2026-04-06T20:20:00Z",
    )
    record_tailoring_review_decision(
        connection,
        paths,
        job_posting_id="jp_test",
        decision_type=RESUME_REVIEW_STATUS_REJECTED,
        reviewer_type=MANDATORY_REVIEWER_AGENT,
        timestamp="2026-04-06T20:25:00Z",
    )

    second_bootstrap = bootstrap_tailoring_run(
        connection,
        paths,
        job_posting_id="jp_test",
        timestamp="2026-04-06T20:35:00Z",
    )

    assert second_bootstrap.run is not None
    assert second_bootstrap.run.resume_tailoring_run_id != bootstrap_result.run.resume_tailoring_run_id
    assert second_bootstrap.reused_existing_run is False
    run_rows = connection.execute(
        """
        SELECT resume_tailoring_run_id, workspace_path, meta_yaml_path, final_resume_path
        FROM resume_tailoring_runs
        WHERE job_posting_id = ?
        ORDER BY created_at ASC, resume_tailoring_run_id ASC
        """,
        ("jp_test",),
    ).fetchall()
    assert len(run_rows) == 2
    original_row = dict(run_rows[0])
    assert original_row["resume_tailoring_run_id"] == bootstrap_result.run.resume_tailoring_run_id
    assert original_row["workspace_path"].startswith("resume-tailoring/output/history/")
    assert original_row["meta_yaml_path"].startswith("resume-tailoring/output/history/")
    assert original_row["final_resume_path"].startswith("resume-tailoring/output/history/")
    assert paths.resolve_from_root(original_row["meta_yaml_path"]).exists()
    assert paths.resolve_from_root(original_row["final_resume_path"]).exists()


def test_finalize_rejects_out_of_scope_resume_changes_before_compile(tmp_path):
    _, paths, connection, bootstrap_result = prepare_real_tailoring_run(
        tmp_path,
        jd_body=(
            "# JD\n"
            "Requirements\n"
            "- 3+ years of software engineering experience.\n"
            "- Build distributed data services in Python and Apache Spark on AWS.\n"
            "- Own monitoring, reliability, and incident response for production pipelines.\n"
        ),
    )
    generate_tailoring_intelligence(
        connection,
        paths,
        job_posting_id="jp_test",
        timestamp="2026-04-06T20:10:00Z",
    )

    resume_tex_path = paths.tailoring_resume_tex_path("Acme Data Systems", "Software Engineer")
    tampered_resume = resume_tex_path.read_text(encoding="utf-8").replace(
        "Arizona State University",
        "Tampered State University",
        1,
    )
    resume_tex_path.write_text(tampered_resume, encoding="utf-8")

    result = finalize_tailoring_run(
        connection,
        paths,
        job_posting_id="jp_test",
        timestamp="2026-04-06T20:20:00Z",
    )

    assert result.result == "needs_revision"
    assert result.reason_code == FINALIZE_REASON_SCOPE_VIOLATION
    assert result.run.resume_tailoring_run_id == bootstrap_result.run.resume_tailoring_run_id
    assert result.run.tailoring_status == TAILORING_STATUS_NEEDS_REVISION
    assert result.run.resume_review_status == RESUME_REVIEW_STATUS_NOT_READY
    assert result.final_resume_path is None

    step_7_payload = yaml.safe_load(
        paths.tailoring_step_7_verification_path("Acme Data Systems", "Software Engineer").read_text(
            encoding="utf-8"
        )
    )
    assert step_7_payload["reason_code"] == FINALIZE_REASON_SCOPE_VIOLATION
    assert any("Out-of-scope change" in blocker for blocker in step_7_payload["blockers"])
