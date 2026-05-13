from __future__ import annotations

import base64
import json
import sqlite3
from dataclasses import dataclass
from email import message_from_bytes

from job_hunt_copilot.bootstrap import run_bootstrap
from job_hunt_copilot.followups import (
    GmailSameThreadFollowUpSender,
    PLAN_STATUS_DRY_RUN_READY,
    PLAN_STATUS_SENT,
    SKIP_REASON_ALREADY_FOLLOWED_UP,
    SKIP_REASON_MISSING_THREAD_CONTEXT,
    SKIP_REASON_REPLIED_IN_THREAD,
    FollowUpCandidate,
    ThreadInspectionResult,
    build_followup_dashboard_summary,
    run_followup_cycle,
    validate_followup_body,
)
from job_hunt_copilot.outreach import SEND_OUTCOME_SENT, SendAttemptOutcome
from job_hunt_copilot.paths import ProjectPaths
from tests.support import create_minimal_project


NOW = "2026-05-12T18:00:00Z"
OLD_SENT_AT = "2026-05-01T16:00:00Z"


@dataclass
class FakeThreadInspector:
    result: ThreadInspectionResult
    calls: int = 0

    def inspect_thread(self, candidate, *, current_time: str) -> ThreadInspectionResult:
        self.calls += 1
        return self.result


@dataclass
class FakeSender:
    sent_bodies: list[str]

    def send_followup(self, candidate, *, body_text: str) -> SendAttemptOutcome:
        self.sent_bodies.append(body_text)
        return SendAttemptOutcome(
            outcome=SEND_OUTCOME_SENT,
            thread_id=candidate.thread_id,
            delivery_tracking_id="gmail_followup_1",
            sent_at=NOW,
        )


class FakeGmailSendService:
    def __init__(self):
        self.sent_body = None

    def users(self):
        return self

    def messages(self):
        return self

    def send(self, *, userId, body):
        assert userId == "me"
        self.sent_body = body
        return self

    def execute(self):
        return {
            "id": "gmail_followup_1",
            "threadId": "thread_1",
            "internalDate": "1778608800000",
        }


def _bootstrap_connection(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    create_minimal_project(project_root)
    run_bootstrap(project_root=project_root)
    connection = sqlite3.connect(project_root / "job_hunt_copilot.db")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    return project_root, connection


def _candidate_for_sender(project_root) -> FollowUpCandidate:
    return FollowUpCandidate(
        outreach_followup_plan_id="fp_1",
        original_outreach_message_id="om_original",
        contact_id="ct_1",
        job_posting_id="jp_1",
        job_posting_contact_id="jpc_1",
        recipient_email="alex@example.com",
        outreach_mode="role_targeted",
        subject="Backend Developer at ExampleCo",
        body_text="Hi Alex,\n\nI'm reaching out about the Backend Developer role at ExampleCo because the work touches Java services and REST APIs.\n\nBest,\nAchyutaram Sonti",
        thread_id="thread_1",
        delivery_tracking_id="gmail_original_1",
        sent_at=OLD_SENT_AT,
        eligible_after=NOW,
        followup_sequence=1,
        contact_display_name="Alex Rivera",
        contact_first_name="Alex",
        contact_status="sent",
        company_name="ExampleCo",
        role_title="Backend Developer",
        jd_artifact_path=None,
        tailored_resume_path=None,
        plan_status="pending",
        retry_count=0,
        next_retry_at=None,
    )


def _seed_sent_role_targeted_message(
    connection: sqlite3.Connection,
    *,
    outreach_message_id: str = "om_original",
    contact_id: str = "ct_1",
    recipient_email: str = "alex@example.com",
    thread_id: str = "thread_1",
    sent_at: str = OLD_SENT_AT,
    company_name: str = "ExampleCo",
    role_title: str = "Backend Developer",
    subject: str = "Backend Developer at ExampleCo",
    body_text: str | None = None,
) -> None:
    now = "2026-05-01T15:00:00Z"
    body = body_text or (
        "Hi Alex,\n\n"
        f"I'm reaching out about the {role_title} role at {company_name} because the work touches Java services, REST APIs, and AWS data pipelines.\n\n"
        "Best,\nAchyutaram Sonti"
    )
    connection.execute(
        """
        INSERT INTO linkedin_leads (
          lead_id, lead_identity_key, lead_status, lead_shape, split_review_status,
          source_type, source_reference, source_mode, company_name, role_title,
          created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "ld_1",
            f"{company_name.lower()}|{role_title.lower()}",
            "reviewed",
            "posting_only",
            "confident",
            "manual_paste",
            "paste/paste.txt",
            "manual_paste",
            company_name,
            role_title,
            now,
            now,
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
            "jp_1",
            "ld_1",
            f"{company_name.lower()}|{role_title.lower()}|remote",
            company_name,
            role_title,
            "outreach_in_progress",
            None,
            now,
            now,
        ),
    )
    connection.execute(
        """
        INSERT INTO contacts (
          contact_id, identity_key, display_name, company_name, origin_component,
          contact_status, full_name, first_name, current_working_email,
          created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            contact_id,
            f"{contact_id}|exampleco",
            "Alex Rivera",
            company_name,
            "linkedin_scraping",
            "sent",
            "Alex Rivera",
            "Alex",
            recipient_email,
            now,
            now,
        ),
    )
    connection.execute(
        """
        INSERT INTO job_posting_contacts (
          job_posting_contact_id, job_posting_id, contact_id, recipient_type,
          relevance_reason, link_level_status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("jpc_1", "jp_1", contact_id, "recruiter", "recruiter", "outreach_done", now, now),
    )
    connection.execute(
        """
        INSERT INTO outreach_messages (
          outreach_message_id, contact_id, outreach_mode, recipient_email,
          message_status, job_posting_id, job_posting_contact_id, subject,
          body_text, body_html, thread_id, delivery_tracking_id, sent_at,
          created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            outreach_message_id,
            contact_id,
            "role_targeted",
            recipient_email,
            "sent",
            "jp_1",
            "jpc_1",
            subject,
            body,
            None,
            thread_id,
            "gmail_original_1",
            sent_at,
            now,
            now,
        ),
    )
    connection.commit()


def test_dry_run_renders_strict_followup_without_sent_state(tmp_path):
    project_root, connection = _bootstrap_connection(tmp_path)
    _seed_sent_role_targeted_message(connection)
    inspector = FakeThreadInspector(ThreadInspectionResult(result="clear", checked_at=NOW))

    result = run_followup_cycle(
        connection,
        project_root=project_root,
        current_time=NOW,
        dry_run=True,
        thread_inspector=inspector,
    )

    plan = connection.execute("SELECT * FROM outreach_followup_plans").fetchone()
    followups = connection.execute(
        "SELECT * FROM outreach_messages WHERE outreach_mode = 'role_targeted_followup'"
    ).fetchall()
    cycle = connection.execute("SELECT * FROM followup_cycle_runs").fetchone()

    assert result.dry_run is True
    assert result.drafts_created == 1
    assert result.messages_sent == 0
    assert plan["plan_status"] == PLAN_STATUS_DRY_RUN_READY
    assert plan["sent_at"] is None
    assert plan["draft_artifact_path"]
    assert followups == []
    assert cycle["candidates_examined"] == 1
    draft_text = (project_root / plan["draft_artifact_path"]).read_text(encoding="utf-8")
    assert "I wanted to briefly follow up on my earlier note about the Backend Developer role at ExampleCo." in draft_text
    assert "Best,\nAchyutaram Sonti" in draft_text
    assert "asonti1@asu.edu" not in draft_text
    assert "50M+" not in draft_text


def test_followup_prefers_original_email_role_company_and_records_review_gates(tmp_path):
    project_root, connection = _bootstrap_connection(tmp_path)
    _seed_sent_role_targeted_message(
        connection,
        company_name="Canonical Corp",
        role_title="Canonical Backend Developer",
        subject="Canonical Backend Developer at Canonical Corp",
        body_text=(
            "Hi Alex,\n\n"
            "I'm reaching out about the Staff Platform Engineer role at Acme Labs because the work touches Java services, REST APIs, and AWS data pipelines.\n\n"
            "Best,\n"
            "Achyutaram Sonti\n"
            "https://www.linkedin.com/in/achyutaram-sonti\n"
            "asonti1@asu.edu"
        ),
    )

    run_followup_cycle(
        connection,
        project_root=project_root,
        current_time=NOW,
        dry_run=True,
        thread_inspector=FakeThreadInspector(ThreadInspectionResult(result="clear", checked_at=NOW)),
    )

    plan = connection.execute("SELECT * FROM outreach_followup_plans").fetchone()
    draft_text = (project_root / plan["draft_artifact_path"]).read_text(encoding="utf-8")
    evidence = json.loads((project_root / plan["review_evidence_artifact_path"]).read_text(encoding="utf-8"))

    assert "Staff Platform Engineer role at Acme Labs" in draft_text
    assert "Canonical Backend Developer role at Canonical Corp" not in draft_text
    assert evidence["role_title_source"] == "original_email_body"
    assert evidence["company_name_source"] == "original_email_body"
    assert evidence["guards"]["approved_template"] is True
    assert evidence["guards"]["direct_thread_reply_check_clear"] is True
    assert evidence["guards"]["no_prior_followup"] is True
    assert evidence["guards"]["original_email_did_not_bounce"] is True
    assert evidence["grounding_sources"]["original_email_body"] is True


def test_followup_recovers_opening_at_company_and_strips_subject_impact_suffix(tmp_path):
    project_root, connection = _bootstrap_connection(tmp_path)
    _seed_sent_role_targeted_message(
        connection,
        company_name="PayPal",
        role_title="Sr Software Engineer",
        subject="Sr Software Engineer at PayPal | Impact: 24",
        body_text=(
            "Hi Trevor,\n\n"
            "I came across the Sr Software Engineer opening at PayPal, and the work touches Java services, REST APIs, and AWS data pipelines.\n\n"
            "Best,\n"
            "Achyutaram Sonti"
        ),
    )

    run_followup_cycle(
        connection,
        project_root=project_root,
        current_time=NOW,
        dry_run=True,
        thread_inspector=FakeThreadInspector(ThreadInspectionResult(result="clear", checked_at=NOW)),
    )

    plan = connection.execute("SELECT * FROM outreach_followup_plans").fetchone()
    draft_text = (project_root / plan["draft_artifact_path"]).read_text(encoding="utf-8")
    evidence = json.loads((project_root / plan["review_evidence_artifact_path"]).read_text(encoding="utf-8"))
    assert "Sr Software Engineer role at PayPal." in draft_text
    assert "Impact: 24" not in draft_text
    assert evidence["company_name"] == "PayPal"
    assert evidence["company_name_source"] == "original_email_body"


def test_background_fit_prefers_role_specific_original_email_phrases(tmp_path):
    project_root, connection = _bootstrap_connection(tmp_path)
    _seed_sent_role_targeted_message(
        connection,
        company_name="Scribd, Inc.",
        role_title="Software Engineer - Backend (Python)",
        subject="Interest in the Software Engineer - Backend (Python) role at Scribd, Inc.",
        body_text=(
            "Hi Liam,\n\n"
            "I'm reaching out about the Software Engineer - Backend (Python) role at Scribd, Inc. because I was interested "
            "in the role's focus on implementing event-driven, distributed systems to extract, enrich, and process metadata "
            "from large-scale document and media datasets. That is close to the kind of systems work I have been doing in production.\n\n"
            "Given your role, I thought you might have useful perspective. In one recent role, I built high-availability Python "
            "and Scala backend data services on AWS (EMR, S3), processing 50M+ daily records.\n\n"
            "Best,\n"
            "Achyutaram Sonti"
        ),
    )

    run_followup_cycle(
        connection,
        project_root=project_root,
        current_time=NOW,
        dry_run=True,
        thread_inspector=FakeThreadInspector(ThreadInspectionResult(result="clear", checked_at=NOW)),
    )

    plan = connection.execute("SELECT * FROM outreach_followup_plans").fetchone()
    draft_text = (project_root / plan["draft_artifact_path"]).read_text(encoding="utf-8")
    evidence = json.loads((project_root / plan["review_evidence_artifact_path"]).read_text(encoding="utf-8"))

    assert (
        "event-driven distributed systems, metadata processing, and large-scale document/media datasets"
        in draft_text
    )
    assert "Java services, Go/Golang services, and Python systems" not in draft_text
    assert evidence["selected_phrase_sources"] == {
        "event-driven distributed systems": "original_email_body",
        "metadata processing": "original_email_body",
        "large-scale document/media datasets": "original_email_body",
    }


def test_unreadable_optional_jd_artifact_does_not_fail_dry_run(tmp_path):
    project_root, connection = _bootstrap_connection(tmp_path)
    _seed_sent_role_targeted_message(connection)
    jd_path = project_root / "linkedin-scraping" / "runtime" / "leads" / "exampleco" / "backend-developer" / "jd.md"
    jd_path.parent.mkdir(parents=True, exist_ok=True)
    jd_path.write_bytes(b"\xd0\x00\xff")
    connection.execute(
        "UPDATE job_postings SET jd_artifact_path = ?, updated_at = ? WHERE job_posting_id = ?",
        (
            "linkedin-scraping/runtime/leads/exampleco/backend-developer/jd.md",
            NOW,
            "jp_1",
        ),
    )
    connection.commit()

    result = run_followup_cycle(
        connection,
        project_root=project_root,
        current_time=NOW,
        dry_run=True,
        thread_inspector=FakeThreadInspector(ThreadInspectionResult(result="clear", checked_at=NOW)),
    )

    plan = connection.execute("SELECT * FROM outreach_followup_plans").fetchone()
    evidence = json.loads((project_root / plan["review_evidence_artifact_path"]).read_text(encoding="utf-8"))
    assert result.result == "success"
    assert result.drafts_created == 1
    assert evidence["grounding_sources"]["jd_artifact"] is False
    assert "missing_jd_artifact" in evidence["grounding_fallbacks"]


def test_reply_in_thread_suppresses_followup(tmp_path):
    project_root, connection = _bootstrap_connection(tmp_path)
    _seed_sent_role_targeted_message(connection)
    inspector = FakeThreadInspector(
        ThreadInspectionResult(result="replied", checked_at=NOW, has_inbound_reply=True)
    )

    result = run_followup_cycle(
        connection,
        project_root=project_root,
        current_time=NOW,
        dry_run=True,
        thread_inspector=inspector,
    )

    plan = connection.execute("SELECT * FROM outreach_followup_plans").fetchone()
    assert result.skipped_replied == 1
    assert plan["plan_status"] == "skipped"
    assert plan["last_skip_reason"] == SKIP_REASON_REPLIED_IN_THREAD


def test_missing_thread_context_in_real_cycle_writes_review_packet(tmp_path):
    project_root, connection = _bootstrap_connection(tmp_path)
    _seed_sent_role_targeted_message(connection, thread_id=None)

    result = run_followup_cycle(
        connection,
        project_root=project_root,
        current_time=NOW,
        dry_run=False,
        thread_inspector=FakeThreadInspector(ThreadInspectionResult(result="clear", checked_at=NOW)),
    )

    plan = connection.execute("SELECT * FROM outreach_followup_plans").fetchone()
    assert plan["plan_status"] == "held_for_review"
    assert plan["last_skip_reason"] == SKIP_REASON_MISSING_THREAD_CONTEXT
    assert result.artifact_paths
    packet_text = (project_root / result.artifact_paths[0]).read_text(encoding="utf-8")
    assert "missing_followup_thread_context" in packet_text
    assert "Original Email" in packet_text


def test_existing_later_followup_suppresses_duplicate(tmp_path):
    project_root, connection = _bootstrap_connection(tmp_path)
    _seed_sent_role_targeted_message(connection)
    connection.execute(
        """
        INSERT INTO outreach_messages (
          outreach_message_id, contact_id, outreach_mode, recipient_email,
          message_status, job_posting_id, job_posting_contact_id, subject,
          body_text, body_html, thread_id, delivery_tracking_id, sent_at,
          created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "om_existing_followup",
            "ct_1",
            "role_targeted_followup",
            "alex@example.com",
            "sent",
            "jp_1",
            "jpc_1",
            "Backend Developer at ExampleCo",
            "already followed up",
            None,
            "thread_1",
            "gmail_followup_old",
            "2026-05-08T16:00:00Z",
            "2026-05-08T16:00:00Z",
            "2026-05-08T16:00:00Z",
        ),
    )
    connection.commit()

    result = run_followup_cycle(
        connection,
        project_root=project_root,
        current_time=NOW,
        dry_run=True,
        thread_inspector=FakeThreadInspector(ThreadInspectionResult(result="clear", checked_at=NOW)),
    )

    plan = connection.execute("SELECT * FROM outreach_followup_plans").fetchone()
    assert result.skipped_already_followed_up == 1
    assert plan["last_skip_reason"] == SKIP_REASON_ALREADY_FOLLOWED_UP


def test_auto_send_uses_persisted_body_and_records_linked_followup(tmp_path):
    project_root, connection = _bootstrap_connection(tmp_path)
    _seed_sent_role_targeted_message(connection, sent_at="2026-05-01T00:00:00Z")
    connection.execute(
        "UPDATE agent_control_state SET control_value = 'true', updated_at = ? WHERE control_key = 'followup_auto_send_enabled'",
        (NOW,),
    )
    connection.commit()
    inspector = FakeThreadInspector(ThreadInspectionResult(result="clear", checked_at=NOW))
    sender = FakeSender(sent_bodies=[])

    result = run_followup_cycle(
        connection,
        project_root=project_root,
        current_time=NOW,
        dry_run=False,
        thread_inspector=inspector,
        sender=sender,
    )

    plan = connection.execute("SELECT * FROM outreach_followup_plans").fetchone()
    sent = connection.execute(
        "SELECT * FROM outreach_messages WHERE outreach_mode = 'role_targeted_followup'"
    ).fetchone()

    assert result.messages_sent == 1
    assert inspector.calls == 2
    assert plan["plan_status"] == PLAN_STATUS_SENT
    assert plan["followup_outreach_message_id"] == sent["outreach_message_id"]
    assert sent["thread_id"] == "thread_1"
    assert sent["recipient_email"] == "alex@example.com"
    assert sent["body_text"] == sender.sent_bodies[0]
    assert sender.sent_bodies[0] == (project_root / plan["draft_artifact_path"]).read_text(encoding="utf-8").rstrip("\n")


def test_gmail_same_thread_sender_preserves_recoverable_cc_and_reply_headers(tmp_path):
    project_root, _ = _bootstrap_connection(tmp_path)
    candidate = _candidate_for_sender(project_root)
    send_result_path = (
        project_root
        / "outreach"
        / "output"
        / "exampleco"
        / "backend-developer"
        / "messages"
        / "om_original"
        / "send_result.json"
    )
    send_result_path.parent.mkdir(parents=True, exist_ok=True)
    send_result_path.write_text(
        json.dumps(
            {
                "result": "success",
                "cc_emails": ["lead@example.com", "team@example.com"],
                "rfc_message_id": "<original-message@example.com>",
            }
        ),
        encoding="utf-8",
    )
    service = FakeGmailSendService()

    outcome = GmailSameThreadFollowUpSender(
        ProjectPaths.from_root(project_root),
        service_factory=lambda: service,
    ).send_followup(candidate, body_text="Hi Alex,\n\nFollow-up body.\n\nBest,\nAchyutaram Sonti")

    assert outcome.outcome == SEND_OUTCOME_SENT
    assert service.sent_body["threadId"] == "thread_1"
    decoded = base64.urlsafe_b64decode(service.sent_body["raw"])
    message = message_from_bytes(decoded)
    assert message["To"] == "alex@example.com"
    assert message["Cc"] == "lead@example.com, team@example.com"
    assert message["In-Reply-To"] == "<original-message@example.com>"
    assert message["References"] == "<original-message@example.com>"


def test_auto_send_respects_global_pacing_queue(tmp_path):
    project_root, connection = _bootstrap_connection(tmp_path)
    _seed_sent_role_targeted_message(connection, sent_at="2026-05-01T00:00:00Z")
    connection.execute(
        "UPDATE agent_control_state SET control_value = 'true', updated_at = ? WHERE control_key = 'followup_auto_send_enabled'",
        (NOW,),
    )
    connection.execute(
        """
        INSERT INTO outreach_messages (
          outreach_message_id, contact_id, outreach_mode, recipient_email,
          message_status, subject, body_text, thread_id, delivery_tracking_id,
          sent_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "om_recent",
            "ct_1",
            "role_targeted",
            "other@example.com",
            "sent",
            "recent",
            "recent",
            "thread_recent",
            "gmail_recent",
            "2026-05-12T17:58:00Z",
            "2026-05-12T17:58:00Z",
            "2026-05-12T17:58:00Z",
        ),
    )
    connection.commit()
    sender = FakeSender(sent_bodies=[])

    result = run_followup_cycle(
        connection,
        project_root=project_root,
        current_time=NOW,
        dry_run=False,
        thread_inspector=FakeThreadInspector(ThreadInspectionResult(result="clear", checked_at=NOW)),
        sender=sender,
    )

    plan = connection.execute(
        "SELECT * FROM outreach_followup_plans WHERE original_outreach_message_id = 'om_original'"
    ).fetchone()
    assert result.messages_sent == 0
    assert result.waiting_for_pacing_count == 1
    assert sender.sent_bodies == []
    assert plan["plan_status"] == "waiting_for_pacing"


def test_followup_dashboard_summary_reports_compact_status(tmp_path):
    project_root, connection = _bootstrap_connection(tmp_path)
    _seed_sent_role_targeted_message(connection)
    run_followup_cycle(
        connection,
        project_root=project_root,
        current_time=NOW,
        dry_run=True,
        thread_inspector=FakeThreadInspector(ThreadInspectionResult(result="clear", checked_at=NOW)),
    )

    summary = build_followup_dashboard_summary(connection, current_time=NOW)

    assert summary["due_now"] == 1
    assert summary["waiting_for_pacing"] == 0
    assert summary["sent_today"] == 0
    assert summary["blocked_or_review"] == 0
    assert summary["last_cycle_at"] == NOW
    assert summary["last_cycle_result"] == "success"


def test_template_validator_rejects_generic_or_metric_heavy_fit_areas():
    valid_body = (
        "Hi Alex,\n\n"
        "I wanted to briefly follow up on my earlier note about the Backend Developer role at ExampleCo.\n\n"
        "I reached out because I believe the role could be a strong mutual fit with my background in Java services and REST APIs. "
        "I know you are busy, so I appreciate you taking the time to read this.\n\n"
        "If you are open to it, I would be grateful for a brief 15-minute conversation to hear your perspective on the role, the team, or what tends to matter in the process.\n\n"
        "If this is not relevant or not the right time, I completely understand and will not keep following up.\n\n"
        "Best,\nAchyutaram Sonti"
    )

    assert validate_followup_body(valid_body, background_fit_areas="Java services and REST APIs")
    assert not validate_followup_body(valid_body, background_fit_areas="software engineering")
    assert not validate_followup_body(valid_body, background_fit_areas="50M+ records and REST APIs")
