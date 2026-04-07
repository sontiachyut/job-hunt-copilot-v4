from __future__ import annotations

import sqlite3
from pathlib import Path
from zoneinfo import ZoneInfo

from job_hunt_copilot.bootstrap import run_bootstrap
from job_hunt_copilot.outreach import (
    CONTACT_STATUS_EXHAUSTED,
    JOB_POSTING_STATUS_READY_FOR_OUTREACH,
    JOB_POSTING_STATUS_REQUIRES_CONTACTS,
    POSTING_CONTACT_STATUS_EXHAUSTED,
    POSTING_CONTACT_STATUS_IDENTIFIED,
    POSTING_CONTACT_STATUS_SHORTLISTED,
    RECIPIENT_TYPE_ALUMNI,
    RECIPIENT_TYPE_ENGINEER,
    RECIPIENT_TYPE_HIRING_MANAGER,
    RECIPIENT_TYPE_RECRUITER,
    evaluate_role_targeted_send_set,
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
