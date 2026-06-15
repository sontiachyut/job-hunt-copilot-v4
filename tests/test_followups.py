from __future__ import annotations

import base64
import json
import sqlite3
from dataclasses import dataclass
from email import message_from_bytes

from job_hunt_copilot.bootstrap import run_bootstrap
from job_hunt_copilot.followups import (
    FOLLOWUP_AUTO_SEND_ENABLED_KEY,
    FOLLOWUP_AUTO_SEND_PAUSED_KEY,
    FOLLOWUP_INITIAL_ROLLOUT_SENT_COUNT_KEY,
    FIXED_FINAL_TOUCH_SENTENCE,
    GmailThreadInspector,
    OUTREACH_MODE_ROLE_TARGETED_FOLLOWUP,
    PLAN_STATUS_DRY_RUN_READY,
    PLAN_STATUS_HELD_FOR_REVIEW,
    PLAN_STATUS_PENDING,
    PLAN_STATUS_RETRYABLE,
    PLAN_STATUS_SENT,
    PLAN_STATUS_SKIPPED,
    PLAN_STATUS_WAITING_FOR_PACING,
    SKIP_REASON_DRAFT_RETRY_EXHAUSTED,
    SKIP_REASON_NON_CODEX_ORIGIN,
    SKIP_REASON_ROLE_TARGETED_PRIORITY,
    StructuredFollowUpDraft,
    TECHNICAL_PATH_SUBJECT,
    FollowUpCandidate,
    FollowUpDraftingError,
    GmailSameThreadFollowUpSender,
    ThreadInspectionResult,
    run_followup_cycle,
)
from job_hunt_copilot.outreach import SEND_OUTCOME_SENT, SendAttemptOutcome
from job_hunt_copilot.paths import ProjectPaths
from tests.support import create_minimal_project


NOW = "2026-06-15T19:00:00Z"
ORIGINAL_SENT_AT = "2026-06-09T18:39:00Z"


CODEx_TECHNICAL_BODY = (
    "Hi Alex,\n\n"
    "I came across your LinkedIn profile and admired your path from InsightRX to ExampleCo and now into your current role as Staff Software Engineer at ExampleCo. "
    "That path stood out to me, and I'd love to grow in a similar direction and ship software at that level over time.\n\n"
    "I am reaching out in a learning-first mode rather than with a direct role ask. If you would be open to it, I would really value a short 10-minute conversation to learn how you think about the work, the team, and what matters most in that area.\n\n"
    "Best,\n"
    "Achyutaram Sonti"
)

LEGACY_BODY = (
    "Hi Alex,\n\n"
    "I'm reaching out about the Backend Developer role at ExampleCo because the work touches backend APIs and services.\n\n"
    "Given your role as Staff Software Engineer, I thought you might have useful perspective on the role.\n\n"
    "Lately, I have been spending time sharpening my Agentic AI skills.\n\n"
    "I built Job Hunt Copilot for my own job search.\n\n"
    "Best,\n"
    "Achyutaram Sonti"
)


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


@dataclass
class FakeRenderer:
    paragraphs: tuple[str, ...]
    calls: int = 0

    def render_followup(self, context, *, current_time: str) -> StructuredFollowUpDraft:
        self.calls += 1
        return StructuredFollowUpDraft(
            paragraphs=self.paragraphs,
            role_company_mode="explicit" if context.sequence == 1 else "thread_implied",
            grounding_mode="original_email_only",
            why_sent_summary=f"sequence {context.sequence}",
        )


class FailingRenderer:
    def __init__(self, message: str = "draft failed") -> None:
        self.message = message

    def render_followup(self, context, *, current_time: str) -> StructuredFollowUpDraft:
        raise FollowUpDraftingError(self.message)


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
            "internalDate": "1781550000000",
        }


class FakeGmailThreadService:
    def __init__(self, payload: dict[str, object]):
        self.payload = payload

    def users(self):
        return self

    def threads(self):
        return self

    def get(self, **kwargs):
        assert kwargs["userId"] == "me"
        return self

    def execute(self):
        return self.payload


def _bootstrap_connection(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    create_minimal_project(project_root)
    run_bootstrap(project_root=project_root)
    connection = sqlite3.connect(project_root / "job_hunt_copilot.db")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    return project_root, connection


def _seed_sent_role_targeted_message(
    connection: sqlite3.Connection,
    project_root,
    *,
    outreach_message_id: str = "om_original",
    contact_id: str = "ct_1",
    recipient_email: str = "alex@example.com",
    thread_id: str = "thread_1",
    sent_at: str = ORIGINAL_SENT_AT,
    company_name: str = "ExampleCo",
    role_title: str = "Backend Developer",
    subject: str = TECHNICAL_PATH_SUBJECT,
    body_text: str = CODEx_TECHNICAL_BODY,
    send_result_payload: dict[str, object] | None = None,
) -> None:
    now = "2026-06-09T18:00:00Z"
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
        ("jpc_1", "jp_1", contact_id, "engineer", "engineer", "outreach_done", now, now),
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
            body_text,
            None,
            thread_id,
            "gmail_original_1",
            sent_at,
            now,
            now,
        ),
    )
    connection.commit()
    if send_result_payload is not None:
        paths = ProjectPaths.from_root(project_root)
        send_result_path = paths.outreach_message_send_result_path(company_name, role_title, outreach_message_id)
        send_result_path.parent.mkdir(parents=True, exist_ok=True)
        send_result_path.write_text(json.dumps(send_result_payload, indent=2) + "\n", encoding="utf-8")


def _seed_sent_followup_plan(
    connection: sqlite3.Connection,
    *,
    original_outreach_message_id: str,
    sequence: int,
    sent_at: str,
    followup_message_id: str,
) -> None:
    connection.execute(
        """
        INSERT INTO outreach_messages (
          outreach_message_id, contact_id, outreach_mode, recipient_email, message_status,
          job_posting_id, job_posting_contact_id, subject, body_text, body_html,
          thread_id, delivery_tracking_id, sent_at, created_at, updated_at
        )
        SELECT ?, contact_id, ?, recipient_email, ?, job_posting_id, job_posting_contact_id,
               subject, ?, NULL, thread_id, ?, ?, ?, ?
        FROM outreach_messages
        WHERE outreach_message_id = ?
        """,
        (
            followup_message_id,
            OUTREACH_MODE_ROLE_TARGETED_FOLLOWUP,
            "sent",
            f"follow-up {sequence}",
            f"gmail_followup_{sequence}",
            sent_at,
            sent_at,
            sent_at,
            original_outreach_message_id,
        ),
    )
    connection.execute(
        """
        INSERT INTO outreach_followup_plans (
          outreach_followup_plan_id, original_outreach_message_id, followup_outreach_message_id,
          contact_id, job_posting_id, plan_status, followup_sequence, eligible_after,
          sent_at, created_at, updated_at
        )
        SELECT ?, ?, ?, contact_id, job_posting_id, ?, ?, ?, ?, ?, ?
        FROM outreach_messages
        WHERE outreach_message_id = ?
        """,
        (
            f"fup_seq_{sequence}",
            original_outreach_message_id,
            followup_message_id,
            PLAN_STATUS_SENT,
            sequence,
            sent_at,
            sent_at,
            sent_at,
            sent_at,
            original_outreach_message_id,
        ),
    )
    connection.commit()


def _enable_followup_auto_send(connection: sqlite3.Connection, *, sent_count: int = 0) -> None:
    connection.executemany(
        """
        INSERT INTO agent_control_state (control_key, control_value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(control_key) DO UPDATE SET
          control_value = excluded.control_value,
          updated_at = excluded.updated_at
        """,
        [
            (FOLLOWUP_AUTO_SEND_ENABLED_KEY, "true", NOW),
            (FOLLOWUP_AUTO_SEND_PAUSED_KEY, "false", NOW),
            (FOLLOWUP_INITIAL_ROLLOUT_SENT_COUNT_KEY, str(sent_count), NOW),
        ],
    )
    connection.commit()


def test_dry_run_materializes_codex_origin_step_one(tmp_path):
    project_root, connection = _bootstrap_connection(tmp_path)
    _seed_sent_role_targeted_message(
        connection,
        project_root,
        send_result_payload={
            "draft_origin_kind": "codex_role_split",
            "draft_posture_family": "technical",
            "autonomous_origin": True,
            "message_id_header": "<msg@example.com>",
        },
    )
    inspector = FakeThreadInspector(ThreadInspectionResult(result="clear", checked_at=NOW))
    renderer = FakeRenderer(
        (
            "I wanted to briefly follow up on my earlier note.",
            "If you would be open to it, I would still value a brief 10-minute conversation to hear your perspective.",
        )
    )

    result = run_followup_cycle(
        connection,
        project_root=project_root,
        current_time=NOW,
        dry_run=True,
        thread_inspector=inspector,
        renderer=renderer,
    )

    plan = connection.execute("SELECT * FROM outreach_followup_plans").fetchone()
    assert result.drafts_created == 1
    assert plan["plan_status"] == PLAN_STATUS_DRY_RUN_READY
    assert plan["followup_sequence"] == 1


def test_materializes_only_next_followup_step(tmp_path):
    project_root, connection = _bootstrap_connection(tmp_path)
    _seed_sent_role_targeted_message(
        connection,
        project_root,
        send_result_payload={
            "draft_origin_kind": "codex_role_split",
            "draft_posture_family": "technical",
            "autonomous_origin": True,
        },
    )
    _seed_sent_followup_plan(
        connection,
        original_outreach_message_id="om_original",
        sequence=1,
        sent_at="2026-06-15T18:50:00Z",
        followup_message_id="msg_followup_1",
    )
    inspector = FakeThreadInspector(ThreadInspectionResult(result="clear", checked_at="2026-06-20T19:00:00Z"))
    renderer = FakeRenderer(
        (
            "Following up once more on my earlier note.",
            "I would still value a brief 10-minute conversation if you are open to it.",
        )
    )

    result = run_followup_cycle(
        connection,
        project_root=project_root,
        current_time="2026-06-22T19:00:00Z",
        dry_run=True,
        thread_inspector=inspector,
        renderer=renderer,
    )

    rows = connection.execute(
        """
        SELECT followup_sequence, plan_status
        FROM outreach_followup_plans
        ORDER BY followup_sequence ASC
        """
    ).fetchall()
    assert result.drafts_created == 1
    assert [tuple(row) for row in rows] == [
        (1, PLAN_STATUS_SENT),
        (2, PLAN_STATUS_DRY_RUN_READY),
    ]


def test_body_style_fallback_accepts_codex_technical_family(tmp_path):
    project_root, connection = _bootstrap_connection(tmp_path)
    _seed_sent_role_targeted_message(
        connection,
        project_root,
        send_result_payload=None,
    )
    inspector = FakeThreadInspector(ThreadInspectionResult(result="clear", checked_at=NOW))
    renderer = FakeRenderer(
        (
            "Just wanted to briefly follow up on my earlier note.",
            "If you would be open to it, I would still value a brief 10-minute conversation.",
        )
    )

    result = run_followup_cycle(
        connection,
        project_root=project_root,
        current_time=NOW,
        dry_run=True,
        thread_inspector=inspector,
        renderer=renderer,
    )

    plan = connection.execute("SELECT * FROM outreach_followup_plans").fetchone()
    assert result.drafts_created == 1
    assert plan["plan_status"] == PLAN_STATUS_DRY_RUN_READY


def test_deterministic_origin_thread_is_skipped(tmp_path):
    project_root, connection = _bootstrap_connection(tmp_path)
    _seed_sent_role_targeted_message(
        connection,
        project_root,
        subject="Software Engineer role",
        body_text=LEGACY_BODY,
        send_result_payload={
            "draft_origin_kind": "deterministic",
            "autonomous_origin": True,
        },
    )

    result = run_followup_cycle(
        connection,
        project_root=project_root,
        current_time=NOW,
        dry_run=True,
        thread_inspector=FakeThreadInspector(ThreadInspectionResult(result="clear", checked_at=NOW)),
        renderer=FakeRenderer(("ignored", "ignored")),
    )

    plan = connection.execute("SELECT * FROM outreach_followup_plans").fetchone()
    assert result.drafts_created == 0
    assert plan["plan_status"] == PLAN_STATUS_SKIPPED
    assert plan["last_skip_reason"] == SKIP_REASON_NON_CODEX_ORIGIN


def test_due_thread_outside_business_window_does_not_render(tmp_path):
    project_root, connection = _bootstrap_connection(tmp_path)
    _seed_sent_role_targeted_message(
        connection,
        project_root,
        send_result_payload={
            "draft_origin_kind": "codex_role_split",
            "draft_posture_family": "technical",
            "autonomous_origin": True,
        },
    )

    result = run_followup_cycle(
        connection,
        project_root=project_root,
        current_time="2026-06-15T10:00:00Z",
        dry_run=True,
        thread_inspector=FakeThreadInspector(ThreadInspectionResult(result="clear", checked_at="2026-06-15T10:00:00Z")),
        renderer=FakeRenderer(("ignored", "ignored")),
    )

    plan = connection.execute("SELECT * FROM outreach_followup_plans").fetchone()
    assert result.drafts_created == 0
    assert plan["plan_status"] == PLAN_STATUS_PENDING


def test_draft_failures_retry_then_hold(tmp_path):
    project_root, connection = _bootstrap_connection(tmp_path)
    _seed_sent_role_targeted_message(
        connection,
        project_root,
        send_result_payload={
            "draft_origin_kind": "codex_role_split",
            "draft_posture_family": "technical",
            "autonomous_origin": True,
        },
    )
    inspector = FakeThreadInspector(ThreadInspectionResult(result="clear", checked_at=NOW))
    renderer = FailingRenderer()

    for _ in range(3):
        run_followup_cycle(
            connection,
            project_root=project_root,
            current_time=NOW,
            dry_run=True,
            thread_inspector=inspector,
            renderer=renderer,
        )

    plan = connection.execute("SELECT * FROM outreach_followup_plans").fetchone()
    assert plan["plan_status"] == PLAN_STATUS_HELD_FOR_REVIEW
    assert plan["last_skip_reason"] == SKIP_REASON_DRAFT_RETRY_EXHAUSTED


def test_priority_lane_holds_followup_when_new_role_targeted_send_exists(tmp_path):
    project_root, connection = _bootstrap_connection(tmp_path)
    _seed_sent_role_targeted_message(
        connection,
        project_root,
        send_result_payload={
            "draft_origin_kind": "codex_role_split",
            "draft_posture_family": "technical",
            "autonomous_origin": True,
        },
    )
    _enable_followup_auto_send(connection)
    inspector = FakeThreadInspector(ThreadInspectionResult(result="clear", checked_at=NOW))
    renderer = FakeRenderer(
        (
            "Just wanted to briefly follow up on my earlier note.",
            "If you would be open to it, I would still value a brief 10-minute conversation.",
        )
    )

    result = run_followup_cycle(
        connection,
        project_root=project_root,
        current_time=NOW,
        dry_run=False,
        thread_inspector=inspector,
        renderer=renderer,
        sender=FakeSender([]),
        role_targeted_priority_checker=lambda conn, now: True,
    )

    plan = connection.execute("SELECT * FROM outreach_followup_plans").fetchone()
    assert result.messages_sent == 0
    assert plan["plan_status"] == PLAN_STATUS_WAITING_FOR_PACING
    assert plan["last_skip_reason"] == SKIP_REASON_ROLE_TARGETED_PRIORITY


def test_rollout_cap_pauses_after_tenth_successful_send(tmp_path):
    project_root, connection = _bootstrap_connection(tmp_path)
    _seed_sent_role_targeted_message(
        connection,
        project_root,
        send_result_payload={
            "draft_origin_kind": "codex_role_split",
            "draft_posture_family": "technical",
            "autonomous_origin": True,
            "message_id_header": "<msg@example.com>",
        },
    )
    _enable_followup_auto_send(connection, sent_count=9)
    inspector = FakeThreadInspector(ThreadInspectionResult(result="clear", checked_at=NOW))
    renderer = FakeRenderer(
        (
            "Just wanted to briefly follow up on my earlier note.",
            "If you would be open to it, I would still value a brief 10-minute conversation.",
        )
    )
    sender = FakeSender([])

    result = run_followup_cycle(
        connection,
        project_root=project_root,
        current_time=NOW,
        dry_run=False,
        thread_inspector=inspector,
        renderer=renderer,
        sender=sender,
        role_targeted_priority_checker=lambda conn, now: False,
    )

    plan = connection.execute("SELECT * FROM outreach_followup_plans").fetchone()
    followups = connection.execute(
        "SELECT * FROM outreach_messages WHERE outreach_mode = ?",
        (OUTREACH_MODE_ROLE_TARGETED_FOLLOWUP,),
    ).fetchall()
    control_rows = {
        row["control_key"]: row["control_value"]
        for row in connection.execute(
            """
            SELECT control_key, control_value
            FROM agent_control_state
            WHERE control_key IN (?, ?)
            """,
            (FOLLOWUP_AUTO_SEND_PAUSED_KEY, FOLLOWUP_INITIAL_ROLLOUT_SENT_COUNT_KEY),
        ).fetchall()
    }
    assert result.messages_sent == 1
    assert plan["plan_status"] == PLAN_STATUS_SENT
    assert len(followups) == 1
    assert control_rows[FOLLOWUP_AUTO_SEND_PAUSED_KEY] == "true"
    assert control_rows[FOLLOWUP_INITIAL_ROLLOUT_SENT_COUNT_KEY] == "10"


def test_sequence_three_appends_fixed_final_touch_sentence(tmp_path):
    project_root, connection = _bootstrap_connection(tmp_path)
    _seed_sent_role_targeted_message(
        connection,
        project_root,
        send_result_payload={
            "draft_origin_kind": "codex_role_split",
            "draft_posture_family": "technical",
            "autonomous_origin": True,
        },
    )
    _seed_sent_followup_plan(
        connection,
        original_outreach_message_id="om_original",
        sequence=1,
        sent_at="2026-06-15T18:50:00Z",
        followup_message_id="msg_followup_1",
    )
    _seed_sent_followup_plan(
        connection,
        original_outreach_message_id="om_original",
        sequence=2,
        sent_at="2026-06-22T18:50:00Z",
        followup_message_id="msg_followup_2",
    )
    inspector = FakeThreadInspector(ThreadInspectionResult(result="clear", checked_at="2026-07-01T19:00:00Z"))
    renderer = FakeRenderer(
        (
            "Just wanted to briefly follow up one last time on my earlier note.",
            "If you would be open to it, I would still value a brief 10-minute conversation.",
        )
    )

    run_followup_cycle(
        connection,
        project_root=project_root,
        current_time="2026-07-01T19:00:00Z",
        dry_run=True,
        thread_inspector=inspector,
        renderer=renderer,
    )

    plan = connection.execute(
        "SELECT draft_artifact_path FROM outreach_followup_plans WHERE followup_sequence = 3"
    ).fetchone()
    draft_path = project_root / str(plan["draft_artifact_path"])
    draft_text = draft_path.read_text(encoding="utf-8")
    assert FIXED_FINAL_TOUCH_SENTENCE in draft_text


def test_gmail_same_thread_sender_preserves_subject_and_cc(tmp_path):
    project_root, connection = _bootstrap_connection(tmp_path)
    _seed_sent_role_targeted_message(
        connection,
        project_root,
        send_result_payload={
            "draft_origin_kind": "codex_role_split",
            "draft_posture_family": "technical",
            "autonomous_origin": True,
            "cc_emails": ["manager@example.com"],
            "message_id_header": "<original@example.com>",
        },
    )
    sender_service = FakeGmailSendService()
    sender = GmailSameThreadFollowUpSender(
        ProjectPaths.from_root(project_root),
        service_factory=lambda: sender_service,
    )
    candidate = FollowUpCandidate(
        outreach_followup_plan_id="fp_1",
        original_outreach_message_id="om_original",
        contact_id="ct_1",
        job_posting_id="jp_1",
        job_posting_contact_id="jpc_1",
        recipient_email="alex@example.com",
        outreach_mode="role_targeted",
        subject=TECHNICAL_PATH_SUBJECT,
        body_text=CODEx_TECHNICAL_BODY,
        thread_id="thread_1",
        delivery_tracking_id="gmail_original_1",
        sent_at=ORIGINAL_SENT_AT,
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

    outcome = sender.send_followup(
        candidate,
        body_text="Hi Alex,\n\nQuick follow-up.\n\nBest,\nAchyutaram Sonti",
    )

    raw_payload = base64.urlsafe_b64decode(sender_service.sent_body["raw"] + "==")
    mime_message = message_from_bytes(raw_payload)
    assert outcome.outcome == SEND_OUTCOME_SENT
    assert mime_message["Subject"] == TECHNICAL_PATH_SUBJECT
    assert mime_message["Cc"] == "manager@example.com"
    assert mime_message["In-Reply-To"] == "<original@example.com>"


def test_gmail_thread_inspector_allows_expected_prior_sender_messages_for_later_sequences(tmp_path):
    project_root, connection = _bootstrap_connection(tmp_path)
    _seed_sent_role_targeted_message(
        connection,
        project_root,
        send_result_payload={
            "draft_origin_kind": "codex_role_split",
            "draft_posture_family": "technical",
            "autonomous_origin": True,
        },
    )
    inspector = GmailThreadInspector(
        ProjectPaths.from_root(project_root),
        service_factory=lambda: FakeGmailThreadService(
            {
                "messages": [
                    {
                        "id": "m1",
                        "internalDate": "1781352000000",
                        "payload": {
                            "headers": [
                                {"name": "From", "value": "achyut@example.com"},
                                {"name": "Subject", "value": TECHNICAL_PATH_SUBJECT},
                            ]
                        },
                    }
                ]
            }
        ),
        sender_email="achyut@example.com",
    )
    candidate = FollowUpCandidate(
        outreach_followup_plan_id="fp_2",
        original_outreach_message_id="om_original",
        contact_id="ct_1",
        job_posting_id="jp_1",
        job_posting_contact_id="jpc_1",
        recipient_email="alex@example.com",
        outreach_mode="role_targeted",
        subject=TECHNICAL_PATH_SUBJECT,
        body_text=CODEx_TECHNICAL_BODY,
        thread_id="thread_1",
        delivery_tracking_id="gmail_original_1",
        sent_at=ORIGINAL_SENT_AT,
        eligible_after=NOW,
        followup_sequence=2,
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

    result = inspector.inspect_thread(candidate, current_time=NOW)

    assert result.safe_to_send is True
