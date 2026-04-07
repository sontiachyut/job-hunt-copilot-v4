from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml

from job_hunt_copilot.bootstrap import run_bootstrap
from job_hunt_copilot.outreach import (
    CONTACT_STATUS_EXHAUSTED,
    CONTACT_STATUS_OUTREACH_IN_PROGRESS,
    JOB_POSTING_STATUS_READY_FOR_OUTREACH,
    JOB_POSTING_STATUS_REQUIRES_CONTACTS,
    JOB_POSTING_STATUS_OUTREACH_IN_PROGRESS,
    MESSAGE_STATUS_FAILED,
    MESSAGE_STATUS_GENERATED,
    OutreachDraftingError,
    POSTING_CONTACT_STATUS_EXHAUSTED,
    POSTING_CONTACT_STATUS_IDENTIFIED,
    POSTING_CONTACT_STATUS_OUTREACH_IN_PROGRESS,
    POSTING_CONTACT_STATUS_SHORTLISTED,
    RECIPIENT_TYPE_ALUMNI,
    RECIPIENT_TYPE_ENGINEER,
    RECIPIENT_TYPE_HIRING_MANAGER,
    RECIPIENT_TYPE_RECRUITER,
    evaluate_role_targeted_send_set,
    generate_general_learning_draft,
    generate_role_targeted_send_set_drafts,
)
from job_hunt_copilot.paths import ProjectPaths
from tests.support import create_minimal_project


def bootstrap_project(tmp_path: Path) -> tuple[Path, ProjectPaths]:
    project_root = tmp_path / "repo"
    project_root.mkdir()
    create_minimal_project(project_root)
    run_bootstrap(project_root=project_root)
    return project_root, ProjectPaths.from_root(project_root)


def connect_database(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    return connection


def seed_posting(
    connection: sqlite3.Connection,
    *,
    lead_id: str = "ld_outreach",
    job_posting_id: str = "jp_outreach",
    company_name: str = "Acme Robotics",
    role_title: str = "Staff Software Engineer / AI",
    created_at: str = "2026-04-06T20:00:00Z",
) -> None:
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
            "acme-robotics|staff-software-engineer-ai",
            "handed_off",
            "posting_only",
            "not_applicable",
            "gmail_job_alert",
            "gmail/message/123",
            "gmail_job_alert",
            "https://careers.acme.example/jobs/123",
            company_name,
            role_title,
            created_at,
            created_at,
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
            "acme-robotics|staff-software-engineer-ai",
            company_name,
            role_title,
            JOB_POSTING_STATUS_REQUIRES_CONTACTS,
            created_at,
            created_at,
        ),
    )
    connection.commit()


def seed_linked_contact(
    connection: sqlite3.Connection,
    *,
    contact_id: str,
    job_posting_contact_id: str,
    job_posting_id: str = "jp_outreach",
    company_name: str = "Acme Robotics",
    display_name: str,
    recipient_type: str,
    current_working_email: str | None = None,
    contact_status: str = "identified",
    link_level_status: str = POSTING_CONTACT_STATUS_SHORTLISTED,
    created_at: str,
) -> None:
    connection.execute(
        """
        INSERT INTO contacts (
          contact_id, identity_key, display_name, company_name, origin_component, contact_status,
          full_name, current_working_email, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            contact_id,
            f"{display_name.lower().replace(' ', '-')}|{company_name.lower().replace(' ', '-')}",
            display_name,
            company_name,
            "email_discovery",
            contact_status,
            display_name,
            current_working_email,
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
            "Selected for autonomous outreach.",
            link_level_status,
            created_at,
            created_at,
        ),
    )
    connection.commit()


def seed_sent_message(
    connection: sqlite3.Connection,
    *,
    outreach_message_id: str,
    contact_id: str,
    recipient_email: str,
    job_posting_id: str = "jp_outreach",
    job_posting_contact_id: str | None = None,
    sent_at: str,
) -> None:
    connection.execute(
        """
        INSERT INTO outreach_messages (
          outreach_message_id, contact_id, outreach_mode, recipient_email, message_status,
          job_posting_id, job_posting_contact_id, subject, body_text, sent_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            outreach_message_id,
            contact_id,
            "role_targeted",
            recipient_email,
            "sent",
            job_posting_id,
            job_posting_contact_id,
            "hello",
            "body",
            sent_at,
            sent_at,
            sent_at,
        ),
    )
    connection.commit()


def write_sender_profile(paths: ProjectPaths) -> None:
    profile_path = paths.assets_dir / "resume-tailoring" / "profile.md"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(
        "\n".join(
            [
                "# Achyutaram Sonti — Master Profile",
                "",
                "## Personal",
                "- **Name:** Achyutaram Sonti",
                "- **Email:** asonti1@asu.edu",
                "- **Phone:** 602-768-6071",
                "- **LinkedIn:** https://www.linkedin.com/in/asonti/",
                "- **GitHub:** https://github.com/sontiachyut",
                "",
                "## Education",
                "- **Arizona State University, Tempe, USA** — MS in Computer Science, GPA 3.96/4.00 (Aug 2024 – May 2026)",
                "",
                "## Work Experience",
                "- Built and maintained distributed data services in Python and Scala on AWS, processing 50M+ daily HL7 records (~580 TPS).",
                "- Optimized 25+ Apache Spark jobs on AWS EMR, improving throughput by 50% and reducing AWS costs by $15K monthly.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def seed_approved_tailoring_run(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    company_name: str = "Acme Robotics",
    role_title: str = "Staff Software Engineer / AI",
    job_posting_id: str = "jp_outreach",
    current_time: str = "2026-04-06T20:20:00Z",
) -> None:
    workspace_dir = paths.tailoring_workspace_dir(company_name, role_title)
    workspace_dir.mkdir(parents=True, exist_ok=True)
    jd_path = paths.tailoring_workspace_jd_path(company_name, role_title)
    jd_path.write_text(
        "\n".join(
            [
                "# Staff Software Engineer / AI",
                "",
                "## Must Have",
                "- Build reliable backend and distributed systems for AI platform workloads.",
                "- Optimize latency, throughput, and cloud cost across production services.",
                "",
                "## Responsibilities",
                "- Improve reliability for production data and model-serving systems.",
                "- Work with Python, Spark, AWS, and Kubernetes.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    step_3_path = paths.tailoring_step_3_jd_signals_path(company_name, role_title)
    step_3_path.parent.mkdir(parents=True, exist_ok=True)
    step_3_path.write_text(
        yaml.safe_dump(
            {
                "job_posting_id": job_posting_id,
                "resume_tailoring_run_id": "rtr_outreach",
                "status": "generated",
                "role_intent_summary": "reliable backend and distributed systems for AI platform workloads",
                "signals_by_priority": {
                    "must_have": [
                        {
                            "signal_id": "signal_must_1",
                            "priority": "must_have",
                            "signal": "reliable backend and distributed systems for AI platform workloads",
                            "tokens": ["reliable", "backend", "distributed", "systems", "ai", "platform"],
                        }
                    ],
                    "core_responsibility": [
                        {
                            "signal_id": "signal_core_1",
                            "priority": "core_responsibility",
                            "signal": "optimize latency throughput and cloud cost across production services",
                            "tokens": ["optimize", "latency", "throughput", "cloud", "cost", "production", "services"],
                        }
                    ],
                    "nice_to_have": [],
                    "informational": [],
                },
                "signals": [
                    {
                        "signal_id": "signal_must_1",
                        "priority": "must_have",
                        "signal": "reliable backend and distributed systems for AI platform workloads",
                        "tokens": ["reliable", "backend", "distributed", "systems", "ai", "platform"],
                    },
                    {
                        "signal_id": "signal_core_1",
                        "priority": "core_responsibility",
                        "signal": "optimize latency throughput and cloud cost across production services",
                        "tokens": ["optimize", "latency", "throughput", "cloud", "cost", "production", "services"],
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    step_6_path = paths.tailoring_step_6_candidate_bullets_path(company_name, role_title)
    step_6_path.write_text(
        yaml.safe_dump(
            {
                "job_posting_id": job_posting_id,
                "resume_tailoring_run_id": "rtr_outreach",
                "status": "generated",
                "summary": "MS CS candidate with 3+ years building backend and distributed systems on AWS.",
                "technical_skills": [
                    {
                        "category": "Languages",
                        "items": ["Python", "Spark", "AWS", "Kubernetes"],
                        "matched_signal_ids": ["signal_must_1", "signal_core_1"],
                    }
                ],
                "software_engineer": {
                    "bullets": [
                        {
                            "text": "Optimized 25+ Apache Spark jobs on AWS EMR, improving throughput by 50% and reducing AWS costs by $15K monthly.",
                            "purpose": "optimization",
                            "support_pointers": ["match_1"],
                            "covered_signal_ids": ["signal_core_1"],
                            "char_count": 120,
                        },
                        {
                            "text": "Built distributed Python and Scala data services processing 50M+ daily HL7 records at roughly 580 TPS for real-time analytics.",
                            "purpose": "scale-impact",
                            "support_pointers": ["match_2"],
                            "covered_signal_ids": ["signal_must_1"],
                            "char_count": 125,
                        },
                    ]
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    resume_path = paths.tailoring_pdf_path(company_name, role_title)
    resume_path.write_text("%PDF-1.4\n% mocked pdf\n", encoding="utf-8")
    meta_path = paths.tailoring_meta_path(company_name, role_title)
    meta_path.write_text(
        yaml.safe_dump(
            {
                "resume_tailoring_run_id": "rtr_outreach",
                "resume_review_status": "approved",
                "resume_artifacts": {
                    "pdf_path": str(resume_path.resolve()),
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
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
            "rtr_outreach",
            job_posting_id,
            "distributed-infra",
            "tailored",
            "approved",
            paths.relative_to_root(workspace_dir).as_posix(),
            paths.relative_to_root(meta_path).as_posix(),
            paths.relative_to_root(resume_path).as_posix(),
            "pass",
            current_time,
            current_time,
            current_time,
            current_time,
        ),
    )
    connection.execute(
        """
        UPDATE job_postings
        SET posting_status = ?, jd_artifact_path = ?, updated_at = ?
        WHERE job_posting_id = ?
        """,
        (
            JOB_POSTING_STATUS_READY_FOR_OUTREACH,
            paths.relative_to_root(jd_path).as_posix(),
            current_time,
            job_posting_id,
        ),
    )
    connection.commit()


def seed_recipient_profile(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    company_name: str = "Acme Robotics",
    role_title: str = "Staff Software Engineer / AI",
    job_posting_id: str = "jp_outreach",
    contact_id: str,
    display_name: str,
    current_title: str,
    work_signal: str,
) -> Path:
    artifact_path = paths.discovery_recipient_profile_path(company_name, role_title, contact_id)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(
        json.dumps(
            {
                "contract_version": "1.0",
                "produced_at": "2026-04-06T20:00:00Z",
                "producer_component": "email_discovery",
                "result": "success",
                "job_posting_id": job_posting_id,
                "contact_id": contact_id,
                "profile_source": "linkedin_public_profile",
                "source_method": "public_profile_html",
                "profile": {
                    "identity": {"display_name": display_name, "full_name": display_name},
                    "top_card": {
                        "current_company": company_name,
                        "current_title": current_title,
                        "headline": current_title,
                    },
                    "about": {"preview_text": f"Focused on {work_signal}.", "is_truncated": False},
                    "work_signals": [work_signal],
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    connection.execute(
        """
        INSERT INTO artifact_records (
          artifact_id, artifact_type, file_path, producer_component,
          lead_id, job_posting_id, contact_id, outreach_message_id, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            f"art_profile_{contact_id}",
            "recipient_profile",
            paths.relative_to_root(artifact_path).as_posix(),
            "email_discovery",
            None,
            job_posting_id,
            contact_id,
            None,
            "2026-04-06T20:00:00Z",
        ),
    )
    connection.commit()
    return artifact_path


class FailingRoleTargetedRenderer:
    def __init__(self, *, fail_contact_ids: set[str]) -> None:
        self.fail_contact_ids = fail_contact_ids

    def render_role_targeted(self, context):  # type: ignore[no-untyped-def]
        if context.contact_id in self.fail_contact_ids:
            raise RuntimeError("synthetic render failure")
        from job_hunt_copilot.outreach import DeterministicOutreachDraftRenderer

        return DeterministicOutreachDraftRenderer().render_role_targeted(context)

    def render_general_learning(self, context):  # type: ignore[no-untyped-def]
        from job_hunt_copilot.outreach import DeterministicOutreachDraftRenderer

        return DeterministicOutreachDraftRenderer().render_general_learning(context)


def test_send_set_prefers_ready_contacts_for_each_primary_class(tmp_path: Path):
    project_root, _ = bootstrap_project(tmp_path)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_posting(connection)
    seed_linked_contact(
        connection,
        contact_id="ct_r1",
        job_posting_contact_id="jpc_r1",
        display_name="Riley Recruiter",
        recipient_type=RECIPIENT_TYPE_RECRUITER,
        current_working_email=None,
        created_at="2026-04-06T20:01:00Z",
    )
    seed_linked_contact(
        connection,
        contact_id="ct_r2",
        job_posting_contact_id="jpc_r2",
        display_name="Priya Recruiter",
        recipient_type=RECIPIENT_TYPE_RECRUITER,
        current_working_email="priya@acme.example",
        created_at="2026-04-06T20:02:00Z",
    )
    seed_linked_contact(
        connection,
        contact_id="ct_m1",
        job_posting_contact_id="jpc_m1",
        display_name="Morgan Manager",
        recipient_type=RECIPIENT_TYPE_HIRING_MANAGER,
        current_working_email=None,
        created_at="2026-04-06T20:03:00Z",
    )
    seed_linked_contact(
        connection,
        contact_id="ct_m2",
        job_posting_contact_id="jpc_m2",
        display_name="Avery Director",
        recipient_type=RECIPIENT_TYPE_HIRING_MANAGER,
        current_working_email="avery@acme.example",
        created_at="2026-04-06T20:04:00Z",
    )
    seed_linked_contact(
        connection,
        contact_id="ct_e1",
        job_posting_contact_id="jpc_e1",
        display_name="Jamie Engineer",
        recipient_type=RECIPIENT_TYPE_ENGINEER,
        current_working_email="jamie@acme.example",
        created_at="2026-04-06T20:05:00Z",
    )
    seed_linked_contact(
        connection,
        contact_id="ct_a1",
        job_posting_contact_id="jpc_a1",
        display_name="Alex Alumni",
        recipient_type=RECIPIENT_TYPE_ALUMNI,
        current_working_email="alex@acme.example",
        created_at="2026-04-06T20:06:00Z",
    )

    plan = evaluate_role_targeted_send_set(
        connection,
        job_posting_id="jp_outreach",
        current_time="2026-04-06T20:10:00Z",
        local_timezone=ZoneInfo("UTC"),
    )

    assert plan.posting_status_after_evaluation == JOB_POSTING_STATUS_READY_FOR_OUTREACH
    assert plan.ready_for_outreach is True
    assert [contact.contact_id for contact in plan.selected_contacts] == ["ct_r2", "ct_m2", "ct_e1"]
    assert [contact.slot_name for contact in plan.selected_contacts] == [
        "recruiter",
        "manager_adjacent",
        "engineer",
    ]
    assert all(contact.readiness_state == "ready" for contact in plan.selected_contacts)

    connection.close()


def test_send_set_waits_for_selected_contact_without_usable_email(tmp_path: Path):
    project_root, _ = bootstrap_project(tmp_path)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_posting(connection)
    seed_linked_contact(
        connection,
        contact_id="ct_r1",
        job_posting_contact_id="jpc_r1",
        display_name="Priya Recruiter",
        recipient_type=RECIPIENT_TYPE_RECRUITER,
        current_working_email="priya@acme.example",
        created_at="2026-04-06T20:01:00Z",
    )
    seed_linked_contact(
        connection,
        contact_id="ct_m1",
        job_posting_contact_id="jpc_m1",
        display_name="Morgan Manager",
        recipient_type=RECIPIENT_TYPE_HIRING_MANAGER,
        current_working_email=None,
        created_at="2026-04-06T20:02:00Z",
    )
    seed_linked_contact(
        connection,
        contact_id="ct_e1",
        job_posting_contact_id="jpc_e1",
        display_name="Jamie Engineer",
        recipient_type=RECIPIENT_TYPE_ENGINEER,
        current_working_email="jamie@acme.example",
        created_at="2026-04-06T20:03:00Z",
    )

    plan = evaluate_role_targeted_send_set(
        connection,
        job_posting_id="jp_outreach",
        current_time="2026-04-06T20:10:00Z",
        local_timezone=ZoneInfo("UTC"),
    )

    assert plan.posting_status_after_evaluation == JOB_POSTING_STATUS_REQUIRES_CONTACTS
    assert plan.ready_for_outreach is False
    assert [contact.contact_id for contact in plan.selected_contacts] == ["ct_r1", "ct_m1", "ct_e1"]
    assert [contact.contact_id for contact in plan.selected_contacts if contact.blocking_reason] == ["ct_m1"]

    connection.close()


def test_send_set_excludes_repeat_outreach_and_uses_next_best_contact(tmp_path: Path):
    project_root, _ = bootstrap_project(tmp_path)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_posting(connection)
    seed_linked_contact(
        connection,
        contact_id="ct_r1",
        job_posting_contact_id="jpc_r1",
        display_name="Priya Recruiter",
        recipient_type=RECIPIENT_TYPE_RECRUITER,
        current_working_email="priya@acme.example",
        created_at="2026-04-06T20:01:00Z",
    )
    seed_linked_contact(
        connection,
        contact_id="ct_r2",
        job_posting_contact_id="jpc_r2",
        display_name="Taylor Recruiter",
        recipient_type=RECIPIENT_TYPE_RECRUITER,
        current_working_email="taylor@acme.example",
        created_at="2026-04-06T20:02:00Z",
    )
    seed_linked_contact(
        connection,
        contact_id="ct_m1",
        job_posting_contact_id="jpc_m1",
        display_name="Morgan Manager",
        recipient_type=RECIPIENT_TYPE_HIRING_MANAGER,
        current_working_email="morgan@acme.example",
        created_at="2026-04-06T20:03:00Z",
    )
    seed_linked_contact(
        connection,
        contact_id="ct_e1",
        job_posting_contact_id="jpc_e1",
        display_name="Jamie Engineer",
        recipient_type=RECIPIENT_TYPE_ENGINEER,
        current_working_email="jamie@acme.example",
        created_at="2026-04-06T20:04:00Z",
    )
    seed_sent_message(
        connection,
        outreach_message_id="msg_prior",
        contact_id="ct_r1",
        recipient_email="priya@acme.example",
        job_posting_contact_id="jpc_r1",
        sent_at="2026-04-05T18:00:00Z",
    )

    plan = evaluate_role_targeted_send_set(
        connection,
        job_posting_id="jp_outreach",
        current_time="2026-04-06T20:10:00Z",
        local_timezone=ZoneInfo("UTC"),
    )

    assert plan.ready_for_outreach is True
    assert [contact.contact_id for contact in plan.selected_contacts] == ["ct_r2", "ct_m1", "ct_e1"]
    assert [contact.contact_id for contact in plan.repeat_outreach_review_contacts] == ["ct_r1"]

    connection.close()


def test_send_set_pacing_reports_global_gap_and_company_daily_cap(tmp_path: Path):
    project_root, _ = bootstrap_project(tmp_path)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_posting(connection)
    seed_linked_contact(
        connection,
        contact_id="ct_r1",
        job_posting_contact_id="jpc_r1",
        display_name="Priya Recruiter",
        recipient_type=RECIPIENT_TYPE_RECRUITER,
        current_working_email="priya@acme.example",
        created_at="2026-04-06T20:01:00Z",
    )
    seed_linked_contact(
        connection,
        contact_id="ct_m1",
        job_posting_contact_id="jpc_m1",
        display_name="Morgan Manager",
        recipient_type=RECIPIENT_TYPE_HIRING_MANAGER,
        current_working_email="morgan@acme.example",
        created_at="2026-04-06T20:02:00Z",
    )
    seed_linked_contact(
        connection,
        contact_id="ct_e1",
        job_posting_contact_id="jpc_e1",
        display_name="Jamie Engineer",
        recipient_type=RECIPIENT_TYPE_ENGINEER,
        current_working_email="jamie@acme.example",
        created_at="2026-04-06T20:03:00Z",
    )

    seed_sent_message(
        connection,
        outreach_message_id="msg_gap",
        contact_id="ct_r1",
        recipient_email="priya@acme.example",
        job_posting_contact_id="jpc_r1",
        sent_at="2026-04-06T20:05:00Z",
    )

    gap_plan = evaluate_role_targeted_send_set(
        connection,
        job_posting_id="jp_outreach",
        current_time="2026-04-06T20:08:00Z",
        local_timezone=ZoneInfo("UTC"),
    )

    assert gap_plan.company_sent_today == 1
    assert gap_plan.remaining_company_daily_capacity == 2
    assert gap_plan.global_gap_minutes in {6, 7, 8, 9, 10}
    assert gap_plan.pacing_allowed_now is False
    assert gap_plan.pacing_block_reason == "global_inter_send_gap"

    seed_linked_contact(
        connection,
        contact_id="ct_cap_1",
        job_posting_contact_id="jpc_cap_1",
        display_name="Cap One",
        recipient_type=RECIPIENT_TYPE_RECRUITER,
        current_working_email="cap1@acme.example",
        created_at="2026-04-06T20:09:00Z",
    )
    seed_linked_contact(
        connection,
        contact_id="ct_cap_2",
        job_posting_contact_id="jpc_cap_2",
        display_name="Cap Two",
        recipient_type=RECIPIENT_TYPE_HIRING_MANAGER,
        current_working_email="cap2@acme.example",
        created_at="2026-04-06T20:10:00Z",
    )
    seed_sent_message(
        connection,
        outreach_message_id="msg_cap_1",
        contact_id="ct_cap_1",
        recipient_email="cap1@acme.example",
        job_posting_contact_id="jpc_cap_1",
        sent_at="2026-04-06T12:00:00Z",
    )
    seed_sent_message(
        connection,
        outreach_message_id="msg_cap_2",
        contact_id="ct_cap_2",
        recipient_email="cap2@acme.example",
        job_posting_contact_id="jpc_cap_2",
        sent_at="2026-04-06T13:00:00Z",
    )

    cap_plan = evaluate_role_targeted_send_set(
        connection,
        job_posting_id="jp_outreach",
        current_time="2026-04-06T20:20:00Z",
        local_timezone=ZoneInfo("UTC"),
    )

    assert cap_plan.company_sent_today == 3
    assert cap_plan.remaining_company_daily_capacity == 0
    assert cap_plan.pacing_allowed_now is False
    assert cap_plan.pacing_block_reason == "company_daily_cap"
    assert cap_plan.earliest_allowed_send_at == "2026-04-07T00:00:00Z"

    connection.close()


def test_send_set_ignores_exhausted_contacts_when_filling_slots(tmp_path: Path):
    project_root, _ = bootstrap_project(tmp_path)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_posting(connection)
    seed_linked_contact(
        connection,
        contact_id="ct_r1",
        job_posting_contact_id="jpc_r1",
        display_name="Priya Recruiter",
        recipient_type=RECIPIENT_TYPE_RECRUITER,
        current_working_email="priya@acme.example",
        created_at="2026-04-06T20:01:00Z",
    )
    seed_linked_contact(
        connection,
        contact_id="ct_m1",
        job_posting_contact_id="jpc_m1",
        display_name="Morgan Manager",
        recipient_type=RECIPIENT_TYPE_HIRING_MANAGER,
        current_working_email=None,
        contact_status=CONTACT_STATUS_EXHAUSTED,
        link_level_status=POSTING_CONTACT_STATUS_EXHAUSTED,
        created_at="2026-04-06T20:02:00Z",
    )
    seed_linked_contact(
        connection,
        contact_id="ct_e1",
        job_posting_contact_id="jpc_e1",
        display_name="Jamie Engineer",
        recipient_type=RECIPIENT_TYPE_ENGINEER,
        current_working_email="jamie@acme.example",
        created_at="2026-04-06T20:03:00Z",
    )

    plan = evaluate_role_targeted_send_set(
        connection,
        job_posting_id="jp_outreach",
        current_time="2026-04-06T20:10:00Z",
        local_timezone=ZoneInfo("UTC"),
    )

    assert plan.ready_for_outreach is True
    assert [contact.contact_id for contact in plan.selected_contacts] == ["ct_r1", "ct_e1"]

    connection.close()


def test_role_targeted_draft_batch_persists_messages_artifacts_and_transitions(tmp_path: Path):
    project_root, paths = bootstrap_project(tmp_path)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    write_sender_profile(paths)
    seed_posting(connection)
    seed_linked_contact(
        connection,
        contact_id="ct_r1",
        job_posting_contact_id="jpc_r1",
        display_name="Priya Recruiter",
        recipient_type=RECIPIENT_TYPE_RECRUITER,
        current_working_email="priya@acme.example",
        created_at="2026-04-06T20:01:00Z",
    )
    seed_linked_contact(
        connection,
        contact_id="ct_m1",
        job_posting_contact_id="jpc_m1",
        display_name="Morgan Manager",
        recipient_type=RECIPIENT_TYPE_HIRING_MANAGER,
        current_working_email="morgan@acme.example",
        created_at="2026-04-06T20:02:00Z",
    )
    seed_linked_contact(
        connection,
        contact_id="ct_e1",
        job_posting_contact_id="jpc_e1",
        display_name="Jamie Engineer",
        recipient_type=RECIPIENT_TYPE_ENGINEER,
        current_working_email="jamie@acme.example",
        created_at="2026-04-06T20:03:00Z",
    )
    seed_recipient_profile(
        connection,
        paths,
        contact_id="ct_r1",
        display_name="Priya Recruiter",
        current_title="Corporate Recruiter",
        work_signal="recruiting function close to the target role",
    )
    seed_approved_tailoring_run(connection, paths)

    result = generate_role_targeted_send_set_drafts(
        connection,
        project_root=project_root,
        job_posting_id="jp_outreach",
        current_time="2026-04-06T20:30:00Z",
        local_timezone=ZoneInfo("UTC"),
    )

    assert result.posting_status_after_drafting == JOB_POSTING_STATUS_OUTREACH_IN_PROGRESS
    assert result.selected_contact_ids == ("ct_r1", "ct_m1", "ct_e1")
    assert len(result.drafted_messages) == 3
    assert result.failed_contacts == ()

    recruiter_message = next(
        message for message in result.drafted_messages if message.contact_id == "ct_r1"
    )
    manager_message = next(
        message for message in result.drafted_messages if message.contact_id == "ct_m1"
    )
    recruiter_body = Path(recruiter_message.body_text_artifact_path).read_text(encoding="utf-8")
    manager_body = Path(manager_message.body_text_artifact_path).read_text(encoding="utf-8")
    assert "I'm reaching out to you specifically because" in recruiter_body
    assert "recruiting function close to the target role" in recruiter_body
    assert "Forwardable snippet:" in recruiter_body
    assert "your role as" in manager_body
    assert "15-minute Zoom" in manager_body

    send_result_payload = json.loads(
        Path(recruiter_message.send_result_artifact_path).read_text(encoding="utf-8")
    )
    assert send_result_payload["outreach_message_id"] == recruiter_message.outreach_message_id
    assert send_result_payload["result"] == "success"
    assert send_result_payload["send_status"] == MESSAGE_STATUS_GENERATED
    assert send_result_payload["body_text_artifact_path"] == recruiter_message.body_text_artifact_path
    assert send_result_payload["resume_attachment_path"].endswith("Achyutaram Sonti.pdf")

    latest_draft_path = paths.outreach_latest_draft_path("Acme Robotics", "Staff Software Engineer / AI")
    latest_send_result_path = paths.outreach_latest_send_result_path(
        "Acme Robotics",
        "Staff Software Engineer / AI",
    )
    assert latest_draft_path.exists()
    assert latest_send_result_path.exists()

    posting_status = connection.execute(
        "SELECT posting_status FROM job_postings WHERE job_posting_id = ?",
        ("jp_outreach",),
    ).fetchone()[0]
    assert posting_status == JOB_POSTING_STATUS_OUTREACH_IN_PROGRESS
    contact_rows = connection.execute(
        """
        SELECT c.contact_id, c.contact_status, jpc.link_level_status
        FROM contacts c
        JOIN job_posting_contacts jpc
          ON jpc.contact_id = c.contact_id
        WHERE jpc.job_posting_id = ?
        ORDER BY c.contact_id
        """,
        ("jp_outreach",),
    ).fetchall()
    assert [dict(row) for row in contact_rows] == [
        {
            "contact_id": "ct_e1",
            "contact_status": CONTACT_STATUS_OUTREACH_IN_PROGRESS,
            "link_level_status": POSTING_CONTACT_STATUS_OUTREACH_IN_PROGRESS,
        },
        {
            "contact_id": "ct_m1",
            "contact_status": CONTACT_STATUS_OUTREACH_IN_PROGRESS,
            "link_level_status": POSTING_CONTACT_STATUS_OUTREACH_IN_PROGRESS,
        },
        {
            "contact_id": "ct_r1",
            "contact_status": CONTACT_STATUS_OUTREACH_IN_PROGRESS,
            "link_level_status": POSTING_CONTACT_STATUS_OUTREACH_IN_PROGRESS,
        },
    ]

    message_rows = connection.execute(
        """
        SELECT outreach_message_id, message_status, subject, body_text, body_html
        FROM outreach_messages
        ORDER BY outreach_message_id
        """
    ).fetchall()
    assert len(message_rows) == 3
    assert all(row["message_status"] == MESSAGE_STATUS_GENERATED for row in message_rows)
    assert all(row["subject"] for row in message_rows)
    assert all(row["body_text"] for row in message_rows)
    assert all(row["body_html"] for row in message_rows)

    artifact_count = connection.execute(
        """
        SELECT COUNT(*)
        FROM artifact_records
        WHERE artifact_type IN ('email_draft', 'send_result')
        """
    ).fetchone()[0]
    assert artifact_count >= 6

    connection.close()


def test_role_targeted_drafting_requires_persisted_ready_for_outreach_state(tmp_path: Path):
    project_root, paths = bootstrap_project(tmp_path)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    write_sender_profile(paths)
    seed_posting(connection)
    seed_linked_contact(
        connection,
        contact_id="ct_r1",
        job_posting_contact_id="jpc_r1",
        display_name="Priya Recruiter",
        recipient_type=RECIPIENT_TYPE_RECRUITER,
        current_working_email="priya@acme.example",
        created_at="2026-04-06T20:01:00Z",
    )
    seed_linked_contact(
        connection,
        contact_id="ct_m1",
        job_posting_contact_id="jpc_m1",
        display_name="Morgan Manager",
        recipient_type=RECIPIENT_TYPE_HIRING_MANAGER,
        current_working_email="morgan@acme.example",
        created_at="2026-04-06T20:02:00Z",
    )
    seed_linked_contact(
        connection,
        contact_id="ct_e1",
        job_posting_contact_id="jpc_e1",
        display_name="Jamie Engineer",
        recipient_type=RECIPIENT_TYPE_ENGINEER,
        current_working_email="jamie@acme.example",
        created_at="2026-04-06T20:03:00Z",
    )
    seed_approved_tailoring_run(connection, paths)
    connection.execute(
        "UPDATE job_postings SET posting_status = ? WHERE job_posting_id = ?",
        (JOB_POSTING_STATUS_REQUIRES_CONTACTS, "jp_outreach"),
    )
    connection.commit()

    with pytest.raises(OutreachDraftingError, match="drafting starts only from `ready_for_outreach`"):
        generate_role_targeted_send_set_drafts(
            connection,
            project_root=project_root,
            job_posting_id="jp_outreach",
            current_time="2026-04-06T20:30:00Z",
            local_timezone=ZoneInfo("UTC"),
        )

    connection.close()


def test_role_targeted_draft_batch_surfaces_failed_contact_without_losing_successes(tmp_path: Path):
    project_root, paths = bootstrap_project(tmp_path)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    write_sender_profile(paths)
    seed_posting(connection)
    seed_linked_contact(
        connection,
        contact_id="ct_r1",
        job_posting_contact_id="jpc_r1",
        display_name="Priya Recruiter",
        recipient_type=RECIPIENT_TYPE_RECRUITER,
        current_working_email="priya@acme.example",
        created_at="2026-04-06T20:01:00Z",
    )
    seed_linked_contact(
        connection,
        contact_id="ct_m1",
        job_posting_contact_id="jpc_m1",
        display_name="Morgan Manager",
        recipient_type=RECIPIENT_TYPE_HIRING_MANAGER,
        current_working_email="morgan@acme.example",
        created_at="2026-04-06T20:02:00Z",
    )
    seed_linked_contact(
        connection,
        contact_id="ct_e1",
        job_posting_contact_id="jpc_e1",
        display_name="Jamie Engineer",
        recipient_type=RECIPIENT_TYPE_ENGINEER,
        current_working_email="jamie@acme.example",
        created_at="2026-04-06T20:03:00Z",
    )
    seed_approved_tailoring_run(connection, paths)

    result = generate_role_targeted_send_set_drafts(
        connection,
        project_root=project_root,
        job_posting_id="jp_outreach",
        current_time="2026-04-06T20:30:00Z",
        local_timezone=ZoneInfo("UTC"),
        renderer=FailingRoleTargetedRenderer(fail_contact_ids={"ct_e1"}),
    )

    assert [message.contact_id for message in result.drafted_messages] == ["ct_r1", "ct_m1"]
    assert [failure.contact_id for failure in result.failed_contacts] == ["ct_e1"]
    assert result.failed_contacts[0].reason_code == "draft_generation_failed"

    failed_row = connection.execute(
        """
        SELECT message_status, subject, body_text
        FROM outreach_messages
        WHERE contact_id = ?
        """,
        ("ct_e1",),
    ).fetchone()
    assert dict(failed_row) == {
        "message_status": MESSAGE_STATUS_FAILED,
        "subject": None,
        "body_text": None,
    }

    successful_count = connection.execute(
        """
        SELECT COUNT(*)
        FROM outreach_messages
        WHERE message_status = ?
        """,
        (MESSAGE_STATUS_GENERATED,),
    ).fetchone()[0]
    assert successful_count == 2

    failed_send_result_rows = connection.execute(
        """
        SELECT file_path
        FROM artifact_records
        WHERE artifact_type = 'send_result'
          AND contact_id = 'ct_e1'
        """
    ).fetchall()
    assert len(failed_send_result_rows) == 1
    failed_payload = json.loads(
        paths.resolve_from_root(failed_send_result_rows[0]["file_path"]).read_text(encoding="utf-8")
    )
    assert failed_payload["result"] == "failed"
    assert failed_payload["reason_code"] == "draft_generation_failed"

    connection.close()


def test_general_learning_draft_persists_without_posting_or_resume(tmp_path: Path):
    project_root, paths = bootstrap_project(tmp_path)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    write_sender_profile(paths)
    connection.execute(
        """
        INSERT INTO contacts (
          contact_id, identity_key, display_name, company_name, origin_component, contact_status,
          full_name, current_working_email, position_title, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "ct_general",
            "isaiah-love|acme-robotics",
            "Isaiah Love",
            "Acme Robotics",
            "email_discovery",
            "working_email_found",
            "Isaiah Love",
            "isaiah@acme.example",
            "Corporate Recruiter",
            "2026-04-06T20:00:00Z",
            "2026-04-06T20:00:00Z",
        ),
    )
    connection.commit()

    result = generate_general_learning_draft(
        connection,
        project_root=project_root,
        contact_id="ct_general",
        current_time="2026-04-06T20:30:00Z",
    )

    drafted = result.drafted_message
    assert drafted.job_posting_id is None
    assert drafted.outreach_mode == "general_learning"
    assert drafted.resume_attachment_path is None
    body_text = Path(drafted.body_text_artifact_path).read_text(encoding="utf-8")
    assert "learning-first mode" in body_text
    assert "direct role ask" in body_text

    row = connection.execute(
        """
        SELECT outreach_mode, message_status, job_posting_id
        FROM outreach_messages
        WHERE outreach_message_id = ?
        """,
        (drafted.outreach_message_id,),
    ).fetchone()
    assert dict(row) == {
        "outreach_mode": "general_learning",
        "message_status": MESSAGE_STATUS_GENERATED,
        "job_posting_id": None,
    }

    send_result_payload = json.loads(
        Path(drafted.send_result_artifact_path).read_text(encoding="utf-8")
    )
    assert send_result_payload.get("job_posting_id") is None
    assert send_result_payload["outreach_mode"] == "general_learning"
    assert send_result_payload["send_status"] == MESSAGE_STATUS_GENERATED

    connection.close()
