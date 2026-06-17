from __future__ import annotations

import base64
import json
import sqlite3
import subprocess
from dataclasses import dataclass
from email import message_from_bytes
from pathlib import Path

import job_hunt_copilot.followups as followups_module
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
    SKIP_REASON_MISSING_SENDER_IDENTITY,
    SKIP_REASON_NON_CODEX_ORIGIN,
    SKIP_REASON_POSTING_ARCHIVED_PRE_CUTOVER,
    SKIP_REASON_WAITING_FOR_WINDOW,
    StructuredFollowUpDraft,
    TECHNICAL_PATH_SUBJECT,
    FollowUpCandidate,
    FollowUpDraftingError,
    GmailSameThreadFollowUpSender,
    ThreadInspectionResult,
    build_followup_dashboard_summary,
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


class FakeGmailProfileService:
    def users(self):
        return self

    def getProfile(self, *, userId):
        assert userId == "me"
        return self

    def execute(self):
        return {"emailAddress": "achyut@example.com"}


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
    lead_id: str = "ld_1",
    job_posting_id: str = "jp_1",
    job_posting_contact_id: str = "jpc_1",
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
            lead_id,
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
            job_posting_id,
            lead_id,
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
        (
            job_posting_contact_id,
            job_posting_id,
            contact_id,
            "engineer",
            "engineer",
            "outreach_done",
            now,
            now,
        ),
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
            job_posting_id,
            job_posting_contact_id,
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


def _write_cached_followup_artifacts(
    project_root: Path,
    *,
    plan_id: str,
    body_text: str,
) -> tuple[str, str]:
    artifact_dir = project_root / "ops" / "followups" / plan_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    draft_path = artifact_dir / "followup_draft.md"
    review_path = artifact_dir / "followup_review_evidence.json"
    draft_path.write_text(body_text + "\n", encoding="utf-8")
    review_path.write_text(json.dumps({"payload": {"cached": True}}), encoding="utf-8")
    return (
        str(Path("ops") / "followups" / plan_id / "followup_draft.md"),
        str(Path("ops") / "followups" / plan_id / "followup_review_evidence.json"),
    )


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


def test_historical_codex_origin_outside_old_recent_slice_materializes_followup(tmp_path):
    project_root, connection = _bootstrap_connection(tmp_path)
    _seed_sent_role_targeted_message(
        connection,
        project_root,
        outreach_message_id="om_oldest",
        lead_id="ld_oldest",
        job_posting_id="jp_oldest",
        job_posting_contact_id="jpc_oldest",
        contact_id="ct_oldest",
        recipient_email="oldest@example.com",
        thread_id="thread_oldest",
        sent_at="2026-06-05T20:30:32Z",
        company_name="Console",
        role_title="Applied AI Engineer",
        subject="Interest in the Applied AI Engineer role at Console",
        body_text=(
            "Hi Kavita,\n\n"
            "I hope you're doing well. I was interested in the Applied AI Engineer role at Console because it lines up with the kind of applied AI and systems work I want to keep growing in.\n\n"
            "Would you be open to a brief 10-minute conversation to hear your perspective on the role or team?\n\n"
            "Best,\n"
            "Achyutaram Sonti"
        ),
        send_result_payload={
            "draft_origin_kind": "codex_role_split",
            "draft_posture_family": "managerial",
            "autonomous_origin": True,
        },
    )
    for index in range(210):
        _seed_sent_role_targeted_message(
            connection,
            project_root,
            outreach_message_id=f"om_recent_{index}",
            lead_id=f"ld_recent_{index}",
            job_posting_id=f"jp_recent_{index}",
            job_posting_contact_id=f"jpc_recent_{index}",
            contact_id=f"ct_recent_{index}",
            recipient_email=f"recent{index}@example.com",
            thread_id=f"thread_recent_{index}",
            sent_at=f"2026-06-15T20:{index % 60:02d}:00Z",
            company_name=f"RecentCo {index}",
            role_title=f"Engineer {index}",
            send_result_payload={
                "draft_origin_kind": "codex_role_split",
                "draft_posture_family": "technical",
                "autonomous_origin": True,
            },
        )

    result = run_followup_cycle(
        connection,
        project_root=project_root,
        current_time=NOW,
        dry_run=True,
        thread_inspector=FakeThreadInspector(ThreadInspectionResult(result="clear", checked_at=NOW)),
        renderer=FakeRenderer(
            (
                "I wanted to briefly follow up on my earlier note.",
                "If you would be open to it, I would still value a brief 10-minute conversation.",
            )
        ),
        batch_size=25,
    )

    oldest_plan = connection.execute(
        """
        SELECT plan_status, followup_sequence
        FROM outreach_followup_plans
        WHERE original_outreach_message_id = ?
        """,
        ("om_oldest",),
    ).fetchone()
    assert result.drafts_created >= 1
    assert oldest_plan is not None
    assert oldest_plan["followup_sequence"] == 1
    assert oldest_plan["plan_status"] in {PLAN_STATUS_DRY_RUN_READY, PLAN_STATUS_PENDING}


def test_pre_cutover_archive_skipped_codex_plan_reopens(tmp_path):
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
    connection.execute(
        """
        INSERT INTO outreach_followup_plans (
          outreach_followup_plan_id, original_outreach_message_id, contact_id, job_posting_id,
          plan_status, followup_sequence, eligible_after, last_skip_reason, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "fp_skipped",
            "om_original",
            "ct_1",
            "jp_1",
            PLAN_STATUS_SKIPPED,
            1,
            "2026-06-13T12:00:00Z",
            SKIP_REASON_POSTING_ARCHIVED_PRE_CUTOVER,
            NOW,
            NOW,
        ),
    )
    connection.commit()

    result = run_followup_cycle(
        connection,
        project_root=project_root,
        current_time=NOW,
        dry_run=True,
        thread_inspector=FakeThreadInspector(ThreadInspectionResult(result="clear", checked_at=NOW)),
        renderer=FakeRenderer(
            (
                "I wanted to briefly follow up on my earlier note.",
                "If you would be open to it, I would still value a brief 10-minute conversation.",
            )
        ),
    )

    plan = connection.execute(
        "SELECT plan_status, last_skip_reason FROM outreach_followup_plans WHERE outreach_followup_plan_id = ?",
        ("fp_skipped",),
    ).fetchone()
    assert result.drafts_created == 1
    assert plan["plan_status"] == PLAN_STATUS_DRY_RUN_READY
    assert plan["last_skip_reason"] is None


def test_load_sender_email_falls_back_to_gmail_profile(tmp_path, monkeypatch):
    project_root, connection = _bootstrap_connection(tmp_path)
    connection.close()
    paths = ProjectPaths.from_root(project_root)
    runtime_secrets_path = paths.secrets_dir / "runtime_secrets.json"
    payload = json.loads(runtime_secrets_path.read_text(encoding="utf-8"))
    gmail_payload = dict(payload["gmail"])
    gmail_payload.pop("sender_email", None)
    gmail_payload.pop("profile_email", None)
    payload["gmail"] = gmail_payload
    runtime_secrets_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    monkeypatch.setattr(
        "job_hunt_copilot.gmail_alerts._build_gmail_service",
        lambda _paths: FakeGmailProfileService(),
    )

    assert followups_module._load_sender_email(paths) == "achyut@example.com"


def test_codex_followup_schema_requires_why_sent_summary(tmp_path, monkeypatch):
    project_root, connection = _bootstrap_connection(tmp_path)
    connection.close()
    paths = ProjectPaths.from_root(project_root)
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
        draft_artifact_path=None,
        review_evidence_artifact_path=None,
        last_evaluated_at=None,
        agent_reviewed_at=None,
        updated_at=None,
    )
    context = followups_module.FollowUpDraftContext(
        candidate=candidate,
        sequence=1,
        posture_family="technical",
        role_title="Backend Developer",
        company_name="ExampleCo",
        salutation="Hi Alex,",
        original_subject=TECHNICAL_PATH_SUBJECT,
        original_body_text=CODEx_TECHNICAL_BODY,
        prior_followups=(),
        sender_evidence_summary="Built distributed systems in Python and Scala.",
        role_company_summary="Follow-up 1 must explicitly refer to the Backend Developer role at ExampleCo.",
        thread_context_summary="No prior sent follow-ups exist on this thread.",
        original_metadata=followups_module.OriginalSendMetadata(
            source_path=None,
            cc_emails=(),
            message_id_header=None,
            role_title="Backend Developer",
            company_name="ExampleCo",
            autonomous_origin=True,
            draft_origin_kind="codex_role_split",
            draft_posture_family="technical",
        ),
        origin=followups_module.OriginalOutreachOrigin(
            status="codex",
            posture_family="technical",
            proof_source="send_result_metadata",
            autonomous_origin=True,
        ),
    )
    captured_schema: dict[str, object] = {}

    def fake_run(command, **kwargs):
        schema_path = Path(command[command.index("--output-schema") + 1])
        output_path = Path(command[command.index("-o") + 1])
        captured_schema.update(json.loads(schema_path.read_text(encoding="utf-8")))
        output_path.write_text(
            json.dumps(
                {
                    "paragraphs": [
                        "I wanted to briefly follow up on my earlier note.",
                        "Would you be open to a brief 10-minute conversation?",
                    ],
                    "role_company_mode": "explicit",
                    "grounding_mode": "original_email_only",
                    "why_sent_summary": "sequence 1 technical follow-up",
                }
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(followups_module.subprocess, "run", fake_run)
    monkeypatch.setattr(followups_module, "_build_codex_exec_env", lambda codex_bin: {})
    monkeypatch.setattr(followups_module, "record_codex_usage_event", lambda *args, **kwargs: "llu_test")

    payload = followups_module._run_followup_codex_payload(
        paths,
        codex_bin="/bin/echo",
        model=None,
        context=context,
        current_time=NOW,
    )

    assert payload["why_sent_summary"] == "sequence 1 technical follow-up"
    assert "why_sent_summary" in captured_schema["required"]


def test_missing_sender_identity_hold_reopens_once_runtime_is_fixed(tmp_path):
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
    connection.execute(
        """
        INSERT INTO outreach_followup_plans (
          outreach_followup_plan_id, original_outreach_message_id, contact_id, job_posting_id,
          plan_status, followup_sequence, eligible_after, last_skip_reason, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "fp_missing_sender",
            "om_original",
            "ct_1",
            "jp_1",
            PLAN_STATUS_HELD_FOR_REVIEW,
            1,
            "2026-06-13T12:00:00Z",
            SKIP_REASON_MISSING_SENDER_IDENTITY,
            NOW,
            NOW,
        ),
    )
    connection.commit()

    result = run_followup_cycle(
        connection,
        project_root=project_root,
        current_time=NOW,
        dry_run=True,
        thread_inspector=FakeThreadInspector(ThreadInspectionResult(result="clear", checked_at=NOW)),
        renderer=FakeRenderer(
            (
                "I wanted to briefly follow up on my earlier note.",
                "If you would be open to it, I would still value a brief 10-minute conversation.",
            )
        ),
    )

    plan = connection.execute(
        "SELECT plan_status, last_skip_reason FROM outreach_followup_plans WHERE outreach_followup_plan_id = ?",
        ("fp_missing_sender",),
    ).fetchone()
    assert result.drafts_created == 1
    assert plan["plan_status"] == PLAN_STATUS_DRY_RUN_READY
    assert plan["last_skip_reason"] is None


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


def test_due_thread_outside_old_business_window_still_renders_when_due(tmp_path):
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
        current_time="2026-06-16T10:00:00Z",
        dry_run=True,
        thread_inspector=FakeThreadInspector(ThreadInspectionResult(result="clear", checked_at="2026-06-16T10:00:00Z")),
        renderer=FakeRenderer(("ignored", "ignored")),
    )

    plan = connection.execute("SELECT * FROM outreach_followup_plans").fetchone()
    assert result.drafts_created == 1
    assert plan["plan_status"] == PLAN_STATUS_DRY_RUN_READY


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


def test_codex_timeout_pauses_followup_auto_send(tmp_path):
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
    _enable_followup_auto_send(connection)
    inspector = FakeThreadInspector(ThreadInspectionResult(result="clear", checked_at=NOW))
    renderer = FailingRenderer("`codex exec` timed out after 600 seconds. See ops/followups/example/codex.stderr.txt.")

    result = run_followup_cycle(
        connection,
        project_root=project_root,
        current_time=NOW,
        dry_run=False,
        thread_inspector=inspector,
        renderer=renderer,
    )

    paused_value = connection.execute(
        "SELECT control_value FROM agent_control_state WHERE control_key = ?",
        (FOLLOWUP_AUTO_SEND_PAUSED_KEY,),
    ).fetchone()[0]
    plan = connection.execute("SELECT * FROM outreach_followup_plans").fetchone()

    assert result.result == "codex_unavailable"
    assert result.blocked_count == 1
    assert paused_value == "true"
    assert plan["plan_status"] == PLAN_STATUS_PENDING


def test_original_preferred_window_holds_followup_when_original_sendable_exists(tmp_path):
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
        current_time="2026-06-15T21:00:00Z",
        dry_run=False,
        thread_inspector=FakeThreadInspector(ThreadInspectionResult(result="clear", checked_at="2026-06-15T21:00:00Z")),
        renderer=renderer,
        sender=FakeSender([]),
        role_targeted_priority_checker=lambda conn, now: True,
    )

    plan = connection.execute("SELECT * FROM outreach_followup_plans").fetchone()
    assert result.messages_sent == 0
    assert plan["plan_status"] == PLAN_STATUS_WAITING_FOR_PACING
    assert plan["last_skip_reason"] == SKIP_REASON_WAITING_FOR_WINDOW


def test_followup_uses_fallback_in_original_window_when_no_original_is_sendable(tmp_path):
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
    _enable_followup_auto_send(connection)
    result = run_followup_cycle(
        connection,
        project_root=project_root,
        current_time="2026-06-15T21:00:00Z",
        dry_run=False,
        thread_inspector=FakeThreadInspector(ThreadInspectionResult(result="clear", checked_at="2026-06-15T21:00:00Z")),
        renderer=FakeRenderer(
            (
                "Just wanted to briefly follow up on my earlier note.",
                "If you would be open to it, I would still value a brief 10-minute conversation.",
            )
        ),
        sender=FakeSender([]),
        role_targeted_priority_checker=lambda conn, now: False,
    )

    plan = connection.execute("SELECT * FROM outreach_followup_plans").fetchone()
    assert result.messages_sent == 1
    assert plan["plan_status"] == PLAN_STATUS_SENT


def test_followup_candidate_order_prefers_oldest_due_then_higher_sequence(tmp_path):
    project_root, connection = _bootstrap_connection(tmp_path)
    _seed_sent_role_targeted_message(
        connection,
        project_root,
        outreach_message_id="om_seq1",
        lead_id="ld_seq1",
        job_posting_id="jp_seq1",
        job_posting_contact_id="jpc_seq1",
        contact_id="ct_seq1",
        recipient_email="seq1@example.com",
        thread_id="thread_seq1",
        send_result_payload={
            "draft_origin_kind": "codex_role_split",
            "draft_posture_family": "technical",
            "autonomous_origin": True,
        },
    )
    _seed_sent_role_targeted_message(
        connection,
        project_root,
        outreach_message_id="om_seq2",
        lead_id="ld_seq2",
        job_posting_id="jp_seq2",
        job_posting_contact_id="jpc_seq2",
        contact_id="ct_seq2",
        recipient_email="seq2@example.com",
        thread_id="thread_seq2",
        send_result_payload={
            "draft_origin_kind": "codex_role_split",
            "draft_posture_family": "technical",
            "autonomous_origin": True,
        },
    )
    _seed_sent_role_targeted_message(
        connection,
        project_root,
        outreach_message_id="om_seq3",
        lead_id="ld_seq3",
        job_posting_id="jp_seq3",
        job_posting_contact_id="jpc_seq3",
        contact_id="ct_seq3",
        recipient_email="seq3@example.com",
        thread_id="thread_seq3",
        send_result_payload={
            "draft_origin_kind": "codex_role_split",
            "draft_posture_family": "technical",
            "autonomous_origin": True,
        },
    )
    connection.executemany(
        """
        INSERT INTO outreach_followup_plans (
          outreach_followup_plan_id, original_outreach_message_id, contact_id, job_posting_id,
          plan_status, followup_sequence, eligible_after, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ("fp_seq1", "om_seq1", "ct_seq1", "jp_seq1", "pending", 1, "2026-06-14T00:00:00Z", NOW, NOW),
            ("fp_seq2", "om_seq2", "ct_seq2", "jp_seq2", "pending", 2, "2026-06-14T00:00:00Z", NOW, NOW),
            ("fp_seq3", "om_seq3", "ct_seq3", "jp_seq3", "pending", 3, "2026-06-14T00:00:00Z", NOW, NOW),
        ],
    )
    connection.commit()

    candidates = followups_module._load_candidate_plans(connection, current_time=NOW, limit=10)

    assert [candidate.followup_sequence for candidate in candidates[:3]] == [3, 2, 1]


def test_followup_cycle_reuses_fresh_cached_draft_without_redrafting(tmp_path):
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
    followups_module._materialize_candidate_plans(
        connection,
        paths=ProjectPaths.from_root(project_root),
        current_time=NOW,
        limit=25,
    )
    plan_id = connection.execute(
        "SELECT outreach_followup_plan_id FROM outreach_followup_plans ORDER BY created_at DESC LIMIT 1"
    ).fetchone()[0]
    draft_path, review_path = _write_cached_followup_artifacts(
        project_root,
        plan_id=str(plan_id),
        body_text=(
            "Hi Alex,\n\n"
            "Just wanted to briefly follow up on my earlier note.\n\n"
            "If you would be open to it, I would still value a brief 10-minute conversation.\n\n"
            "Best,\n"
            "Achyutaram Sonti"
        ),
    )
    connection.execute(
        """
        UPDATE outreach_followup_plans
        SET plan_status = ?, draft_artifact_path = ?, review_evidence_artifact_path = ?,
            last_evaluated_at = ?, agent_reviewed_at = ?, updated_at = ?
        WHERE outreach_followup_plan_id = ?
        """,
        (
            "agent_reviewed",
            draft_path,
            review_path,
                NOW,
                NOW,
                NOW,
                str(plan_id),
            ),
        )
    connection.commit()
    _enable_followup_auto_send(connection)
    renderer = FakeRenderer(
        (
            "This should not be used.",
            "This should not be used either.",
        )
    )
    sender = FakeSender([])

    result = run_followup_cycle(
        connection,
        project_root=project_root,
        current_time=NOW,
        dry_run=False,
        thread_inspector=FakeThreadInspector(ThreadInspectionResult(result="clear", checked_at=NOW)),
        renderer=renderer,
        sender=sender,
        role_targeted_priority_checker=lambda conn, now: False,
    )

    assert result.messages_sent == 1
    assert renderer.calls == 0
    assert sender.sent_bodies[0].startswith("Hi Alex,\n\nJust wanted to briefly follow up")


def test_followup_cycle_does_not_prepare_new_due_plan_when_prepared_frontier_is_full(tmp_path):
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
    for index in range(2, 12):
        _seed_sent_role_targeted_message(
            connection,
            project_root,
            outreach_message_id=f"om_frontier_{index}",
            lead_id=f"ld_frontier_{index}",
            job_posting_id=f"jp_frontier_{index}",
            job_posting_contact_id=f"jpc_frontier_{index}",
            contact_id=f"ct_frontier_{index}",
            recipient_email=f"frontier{index}@example.com",
            thread_id=f"thread_frontier_{index}",
            send_result_payload={
                "draft_origin_kind": "codex_role_split",
                "draft_posture_family": "technical",
                "autonomous_origin": True,
            },
        )
    _seed_sent_role_targeted_message(
        connection,
        project_root,
        outreach_message_id="om_due_pending",
        lead_id="ld_due_pending",
        job_posting_id="jp_due_pending",
        job_posting_contact_id="jpc_due_pending",
        contact_id="ct_due_pending",
        recipient_email="duepending@example.com",
        thread_id="thread_due_pending",
        send_result_payload={
            "draft_origin_kind": "codex_role_split",
            "draft_posture_family": "technical",
            "autonomous_origin": True,
        },
    )
    connection.execute("DELETE FROM outreach_followup_plans")
    for index in range(1, 11):
        draft_path, review_path = _write_cached_followup_artifacts(
            project_root,
            plan_id=f"fp_prepared_{index}",
            body_text=(
                f"Hi Alex,\n\nPrepared {index}.\n\nIf you would be open to it, I would still value a brief 10-minute conversation.\n\nBest,\nAchyutaram Sonti"
            ),
        )
        original_message_id = "om_original" if index == 1 else f"om_frontier_{index}"
        contact_id = "ct_1" if index == 1 else f"ct_frontier_{index}"
        job_posting_id = "jp_1" if index == 1 else f"jp_frontier_{index}"
        connection.execute(
            """
            INSERT INTO outreach_followup_plans (
              outreach_followup_plan_id, original_outreach_message_id, contact_id, job_posting_id,
              plan_status, followup_sequence, eligible_after, draft_artifact_path,
              review_evidence_artifact_path, last_evaluated_at, agent_reviewed_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"fp_prepared_{index}",
                original_message_id,
                contact_id,
                job_posting_id,
                "agent_reviewed",
                1,
                "2026-06-20T00:00:00Z",
                draft_path,
                review_path,
                NOW,
                NOW,
                NOW,
                NOW,
            ),
        )
    connection.execute(
        """
        INSERT INTO outreach_followup_plans (
          outreach_followup_plan_id, original_outreach_message_id, contact_id, job_posting_id,
          plan_status, followup_sequence, eligible_after, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "fp_due_pending",
            "om_due_pending",
            "ct_due_pending",
            "jp_due_pending",
            "pending",
            1,
            "2026-06-14T00:00:00Z",
            NOW,
            NOW,
        ),
    )
    connection.commit()
    _enable_followup_auto_send(connection)
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
        thread_inspector=FakeThreadInspector(ThreadInspectionResult(result="clear", checked_at=NOW)),
        renderer=renderer,
        role_targeted_priority_checker=lambda conn, now: False,
    )

    pending_plan = connection.execute(
        "SELECT plan_status, draft_artifact_path FROM outreach_followup_plans WHERE outreach_followup_plan_id = ?",
        ("fp_due_pending",),
    ).fetchone()
    assert result.drafts_created == 0
    assert renderer.calls == 0
    assert dict(pending_plan) == {
        "plan_status": "pending",
        "draft_artifact_path": None,
    }


def test_followup_dashboard_summary_includes_next_window_preview(tmp_path):
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
    summary = build_followup_dashboard_summary(connection, current_time=NOW)

    assert summary["active_window_preference"] == "followup"
    assert summary["next_window_preference"] == "original"
    assert summary["next_window_local_start"].endswith("MST")


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
        draft_artifact_path=None,
        review_evidence_artifact_path=None,
        last_evaluated_at=None,
        agent_reviewed_at=None,
        updated_at=None,
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
        draft_artifact_path=None,
        review_evidence_artifact_path=None,
        last_evaluated_at=None,
        agent_reviewed_at=None,
        updated_at=None,
    )

    result = inspector.inspect_thread(candidate, current_time=NOW)

    assert result.safe_to_send is True
