from __future__ import annotations

import base64
import json
import sqlite3
from email import policy
from email.parser import BytesParser
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml

from job_hunt_copilot.bootstrap import run_bootstrap
from job_hunt_copilot.delivery_feedback import DeliveryFeedbackSignal, OBSERVATION_SCOPE_IMMEDIATE
from job_hunt_copilot.outreach import (
    CONTACT_STATUS_EXHAUSTED,
    CONTACT_STATUS_OUTREACH_IN_PROGRESS,
    CONTACT_STATUS_SENT,
    JOB_POSTING_STATUS_COMPLETED,
    JOB_POSTING_STATUS_READY_FOR_OUTREACH,
    JOB_POSTING_STATUS_REQUIRES_CONTACTS,
    JOB_POSTING_STATUS_OUTREACH_IN_PROGRESS,
    MESSAGE_STATUS_BLOCKED,
    MESSAGE_STATUS_FAILED,
    MESSAGE_STATUS_GENERATED,
    MESSAGE_STATUS_SENT,
    GmailApiOutreachSender,
    OutboundOutreachMessage,
    OutreachDraftingError,
    SendAttemptOutcome,
    POSTING_CONTACT_STATUS_EXHAUSTED,
    POSTING_CONTACT_STATUS_IDENTIFIED,
    POSTING_CONTACT_STATUS_OUTREACH_DONE,
    POSTING_CONTACT_STATUS_OUTREACH_IN_PROGRESS,
    POSTING_CONTACT_STATUS_SHORTLISTED,
    RECIPIENT_TYPE_ALUMNI,
    RECIPIENT_TYPE_ENGINEER,
    RECIPIENT_TYPE_HIRING_MANAGER,
    RECIPIENT_TYPE_RECRUITER,
    _normalize_education_line,
    execute_general_learning_outreach,
    execute_role_targeted_send_set,
    evaluate_role_targeted_send_set,
    generate_general_learning_draft,
    generate_role_targeted_send_set_drafts,
    is_role_targeted_sending_actionable_now,
    refresh_role_targeted_generated_drafts,
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


def test_normalize_education_line_drops_asu_ms_summary() -> None:
    value = "- **Arizona State University, Tempe, USA** — MS in Computer Science, GPA 3.96/4.00 (Aug 2024 – May 2026)"

    assert _normalize_education_line(value) is None


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
            f"{lead_id}|acme-robotics|staff-software-engineer-ai",
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


class RecordingOutreachSender:
    def __init__(
        self,
        *,
        failing_message_ids: set[str] | None = None,
        ambiguous_message_ids: set[str] | None = None,
    ) -> None:
        self.failing_message_ids = failing_message_ids or set()
        self.ambiguous_message_ids = ambiguous_message_ids or set()
        self.attempted_message_ids: list[str] = []

    def send(self, message):  # type: ignore[no-untyped-def]
        self.attempted_message_ids.append(message.outreach_message_id)
        if message.outreach_message_id in self.ambiguous_message_ids:
            return SendAttemptOutcome(
                outcome="ambiguous",
                reason_code="ambiguous_send_outcome",
                message="Provider completion could not be reconciled.",
            )
        if message.outreach_message_id in self.failing_message_ids:
            return SendAttemptOutcome(
                outcome="failed",
                reason_code="smtp_rejected",
                message="Synthetic provider rejection.",
            )
        return SendAttemptOutcome(
            outcome="sent",
            thread_id=f"thread-{message.outreach_message_id}",
            delivery_tracking_id=f"delivery-{message.outreach_message_id}",
        )


class SequencedOutreachSender:
    def __init__(self, outcomes_by_message_id):  # type: ignore[no-untyped-def]
        self.outcomes_by_message_id = {
            key: list(value) for key, value in outcomes_by_message_id.items()
        }
        self.attempted_message_ids: list[str] = []

    def send(self, message):  # type: ignore[no-untyped-def]
        self.attempted_message_ids.append(message.outreach_message_id)
        sequence = self.outcomes_by_message_id.get(message.outreach_message_id)
        if not sequence:
            raise AssertionError(f"Unexpected send for {message.outreach_message_id}")
        return sequence.pop(0)


class ImmediateBounceObserver:
    def __init__(self, *, event_timestamp: str) -> None:
        self.event_timestamp = event_timestamp
        self.poll_calls: list[dict[str, object]] = []

    def poll(self, messages, *, current_time, observation_scope):  # type: ignore[no-untyped-def]
        self.poll_calls.append(
            {
                "message_ids": [message.outreach_message_id for message in messages],
                "current_time": current_time,
                "observation_scope": observation_scope,
            }
        )
        if not messages:
            return []
        message = messages[0]
        return [
            DeliveryFeedbackSignal(
                signal_type="bounced",
                event_timestamp=self.event_timestamp,
                delivery_tracking_id=message.delivery_tracking_id,
            )
        ]


class TimeoutFeedbackObserver:
    def __init__(self) -> None:
        self.poll_calls: list[dict[str, object]] = []

    def poll(self, messages, *, current_time, observation_scope):  # type: ignore[no-untyped-def]
        self.poll_calls.append(
            {
                "message_ids": [message.outreach_message_id for message in messages],
                "current_time": current_time,
                "observation_scope": observation_scope,
            }
        )
        raise TimeoutError("Synthetic mailbox timeout")


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


def test_gmail_api_outreach_sender_builds_message_and_attachment(tmp_path: Path):
    project_root, _ = bootstrap_project(tmp_path)
    attachment_path = project_root / "resume.pdf"
    attachment_path.write_bytes(b"%PDF-1.4 test resume\n")

    class FakeSendRequest:
        def __init__(self, response, capture):  # type: ignore[no-untyped-def]
            self._response = response
            self._capture = capture

        def execute(self):  # type: ignore[no-untyped-def]
            return self._response

    class FakeMessagesResource:
        def __init__(self, response, capture):  # type: ignore[no-untyped-def]
            self._response = response
            self._capture = capture

        def send(self, *, userId, body):  # type: ignore[no-untyped-def]
            self._capture["userId"] = userId
            self._capture["body"] = body
            return FakeSendRequest(self._response, self._capture)

    class FakeUsersResource:
        def __init__(self, response, capture):  # type: ignore[no-untyped-def]
            self._response = response
            self._capture = capture

        def messages(self):  # type: ignore[no-untyped-def]
            return FakeMessagesResource(self._response, self._capture)

    class FakeGmailService:
        def __init__(self, response, capture):  # type: ignore[no-untyped-def]
            self._response = response
            self._capture = capture

        def users(self):  # type: ignore[no-untyped-def]
            return FakeUsersResource(self._response, self._capture)

    capture: dict[str, object] = {}
    sender = GmailApiOutreachSender(
        ProjectPaths.from_root(project_root),
        service_factory=lambda: FakeGmailService(
            {
                "id": "gmail-message-123",
                "threadId": "gmail-thread-456",
                "internalDate": "1770000000000",
            },
            capture,
        ),
    )

    result = sender.send(
        message=OutboundOutreachMessage(
            outreach_message_id="om_123",
            contact_id="ct_123",
            job_posting_id="jp_123",
            job_posting_contact_id="jpc_123",
            outreach_mode="role_targeted",
            recipient_email="target@example.com",
            subject="Tailored intro",
            body_text="Plain text body",
            body_html="<p>HTML body</p>",
            resume_attachment_path=str(attachment_path),
        )
    )
    assert result.outcome == "sent"
    assert result.thread_id == "gmail-thread-456"
    assert result.delivery_tracking_id == "gmail-message-123"
    assert capture["userId"] == "me"

    raw_payload = str(capture["body"]["raw"])
    parsed = BytesParser(policy=policy.default).parsebytes(
        base64.urlsafe_b64decode(raw_payload.encode("ascii"))
    )
    assert parsed["To"] == "target@example.com"
    assert parsed["Subject"] == "Tailored intro"
    body_parts = list(parsed.walk())
    assert any(part.get_content_type() == "text/plain" for part in body_parts)
    assert any(part.get_content_type() == "text/html" for part in body_parts)
    attachment_parts = [part for part in body_parts if part.get_content_disposition() == "attachment"]
    assert len(attachment_parts) == 1
    assert attachment_parts[0].get_filename() == "resume.pdf"


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


def test_send_set_silently_skips_same_company_prior_send_when_alternate_exists(tmp_path: Path):
    project_root, _ = bootstrap_project(tmp_path)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_posting(connection, lead_id="ld_primary", job_posting_id="jp_primary")
    seed_posting(
        connection,
        lead_id="ld_other",
        job_posting_id="jp_other",
        role_title="Backend Platform Engineer",
    )
    seed_linked_contact(
        connection,
        contact_id="ct_r1",
        job_posting_contact_id="jpc_r1",
        job_posting_id="jp_primary",
        display_name="Priya Recruiter",
        recipient_type=RECIPIENT_TYPE_RECRUITER,
        current_working_email="priya@acme.example",
        created_at="2026-04-06T20:01:00Z",
    )
    connection.execute(
        """
        INSERT INTO job_posting_contacts (
          job_posting_contact_id, job_posting_id, contact_id, recipient_type, relevance_reason,
          link_level_status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "jpc_other_r1",
            "jp_other",
            "ct_r1",
            RECIPIENT_TYPE_RECRUITER,
            "Previously used on another posting.",
            POSTING_CONTACT_STATUS_OUTREACH_DONE,
            "2026-04-05T18:00:00Z",
            "2026-04-05T18:00:00Z",
        ),
    )
    seed_linked_contact(
        connection,
        contact_id="ct_r2",
        job_posting_contact_id="jpc_r2",
        job_posting_id="jp_primary",
        display_name="Taylor Recruiter",
        recipient_type=RECIPIENT_TYPE_RECRUITER,
        current_working_email="taylor@acme.example",
        created_at="2026-04-06T20:02:00Z",
    )
    seed_linked_contact(
        connection,
        contact_id="ct_m1",
        job_posting_contact_id="jpc_m1",
        job_posting_id="jp_primary",
        display_name="Morgan Manager",
        recipient_type=RECIPIENT_TYPE_HIRING_MANAGER,
        current_working_email="morgan@acme.example",
        created_at="2026-04-06T20:03:00Z",
    )
    seed_linked_contact(
        connection,
        contact_id="ct_e1",
        job_posting_contact_id="jpc_e1",
        job_posting_id="jp_primary",
        display_name="Jamie Engineer",
        recipient_type=RECIPIENT_TYPE_ENGINEER,
        current_working_email="jamie@acme.example",
        created_at="2026-04-06T20:04:00Z",
    )
    seed_sent_message(
        connection,
        outreach_message_id="msg_prior_same_company",
        contact_id="ct_r1",
        recipient_email="priya@acme.example",
        job_posting_id="jp_other",
        job_posting_contact_id="jpc_other_r1",
        sent_at="2026-04-05T18:05:00Z",
    )

    plan = evaluate_role_targeted_send_set(
        connection,
        job_posting_id="jp_primary",
        current_time="2026-04-06T20:10:00Z",
        local_timezone=ZoneInfo("UTC"),
    )

    assert plan.ready_for_outreach is True
    assert [contact.contact_id for contact in plan.selected_contacts] == ["ct_r2", "ct_m1", "ct_e1"]
    assert plan.repeat_outreach_review_contacts == ()

    connection.close()


def test_send_set_surfaces_same_company_prior_send_when_no_alternate_exists(tmp_path: Path):
    project_root, _ = bootstrap_project(tmp_path)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_posting(connection, lead_id="ld_primary", job_posting_id="jp_primary")
    seed_posting(
        connection,
        lead_id="ld_other",
        job_posting_id="jp_other",
        role_title="Backend Platform Engineer",
    )
    seed_linked_contact(
        connection,
        contact_id="ct_r1",
        job_posting_contact_id="jpc_r1",
        job_posting_id="jp_primary",
        display_name="Priya Recruiter",
        recipient_type=RECIPIENT_TYPE_RECRUITER,
        current_working_email="priya@acme.example",
        created_at="2026-04-06T20:01:00Z",
    )
    connection.execute(
        """
        INSERT INTO job_posting_contacts (
          job_posting_contact_id, job_posting_id, contact_id, recipient_type, relevance_reason,
          link_level_status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "jpc_other_r1",
            "jp_other",
            "ct_r1",
            RECIPIENT_TYPE_RECRUITER,
            "Previously used on another posting.",
            POSTING_CONTACT_STATUS_OUTREACH_DONE,
            "2026-04-05T18:00:00Z",
            "2026-04-05T18:00:00Z",
        ),
    )
    seed_sent_message(
        connection,
        outreach_message_id="msg_prior_same_company",
        contact_id="ct_r1",
        recipient_email="priya@acme.example",
        job_posting_id="jp_other",
        job_posting_contact_id="jpc_other_r1",
        sent_at="2026-04-05T18:05:00Z",
    )

    plan = evaluate_role_targeted_send_set(
        connection,
        job_posting_id="jp_primary",
        current_time="2026-04-06T20:10:00Z",
        local_timezone=ZoneInfo("UTC"),
    )

    assert plan.ready_for_outreach is False
    assert plan.selected_contacts == ()
    assert [contact.contact_id for contact in plan.repeat_outreach_review_contacts] == ["ct_r1"]

    connection.close()


def test_send_set_pacing_reports_global_gap_and_posting_daily_cap(tmp_path: Path):
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

    assert gap_plan.posting_sent_today == 1
    assert gap_plan.remaining_posting_daily_capacity == 3
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
    seed_linked_contact(
        connection,
        contact_id="ct_cap_3",
        job_posting_contact_id="jpc_cap_3",
        display_name="Cap Three",
        recipient_type=RECIPIENT_TYPE_ENGINEER,
        current_working_email="cap3@acme.example",
        created_at="2026-04-06T20:11:00Z",
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
    seed_sent_message(
        connection,
        outreach_message_id="msg_cap_3",
        contact_id="ct_cap_3",
        recipient_email="cap3@acme.example",
        job_posting_contact_id="jpc_cap_3",
        sent_at="2026-04-06T14:00:00Z",
    )

    cap_plan = evaluate_role_targeted_send_set(
        connection,
        job_posting_id="jp_outreach",
        current_time="2026-04-06T20:20:00Z",
        local_timezone=ZoneInfo("UTC"),
    )

    assert cap_plan.posting_sent_today == 4
    assert cap_plan.remaining_posting_daily_capacity == 0
    assert cap_plan.pacing_allowed_now is False
    assert cap_plan.pacing_block_reason == "posting_daily_cap"
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
    recruiter_html = Path(recruiter_message.body_html_artifact_path).read_text(encoding="utf-8")
    assert "I thought you might have useful perspective on the hiring context for this opening." in recruiter_body
    assert "MS in Computer Science at ASU" not in recruiter_body
    assert "Arizona State University" not in recruiter_body
    assert "Lately, I have been spending time sharpening my Agentic AI skills." in recruiter_body
    assert "I built Job Hunt Copilot (https://github.com/sontiachyut/job-hunt-copilot-v4) for my own job search to help me identify relevant roles and the right people to reach out to." in recruiter_body
    assert "The AI agent runs autonomously with human-in-the-loop (HITL) review, and I personally review every email before it goes out. This email is a live example of that workflow." in recruiter_body
    assert "strong fit" not in recruiter_body
    assert "15-minute Zoom" not in recruiter_body
    assert "whether my background could be relevant." in recruiter_body
    assert "seems close to" not in recruiter_body
    assert "I came across the" not in recruiter_body
    assert "The emphasis on" not in recruiter_body
    assert "That is what prompted me to reach out." not in recruiter_body
    assert "which is what prompted me to reach out." not in recruiter_body
    assert "I've included a short snippet below that you can paste into an IM/Email:" in recruiter_body
    assert "[snippet]" in recruiter_body
    assert "[/snippet]" in recruiter_body
    assert (
        "Hi, sharing a candidate who may be relevant for the Staff Software Engineer / AI role at Acme Robotics."
        in recruiter_body
    )
    assert (
        "His background overlaps well with the role's focus on reliable backend and distributed systems for AI platform workloads, "
        "and he's intentionally growing in that direction, "
        "including building distributed Python and Scala data services processing 50M+ daily HL7 records at roughly 580 TPS for real-time analytics."
        in recruiter_body
    )
    assert "Profile: www.linkedin.com/in/asonti" in recruiter_body
    assert "Lately, I have been spending time sharpening my Agentic AI skills." in recruiter_html
    assert "I built Job Hunt Copilot" in recruiter_html
    assert 'href="https://github.com/sontiachyut/job-hunt-copilot-v4"' in recruiter_html
    assert (
        '<p style="margin:0;color:#111827;line-height:1.55;font-weight:600;">'
        "The AI agent runs autonomously with human-in-the-loop (HITL) review, and I personally review every email before it goes out. "
        "This email is a live example of that workflow.</p>"
    ) in recruiter_html
    assert "background:#f4f4f4" in recruiter_html
    assert "border-left:4px solid #1a73e8" in recruiter_html
    assert "Best,<br>Achyutaram Sonti<br>https://www.linkedin.com/in/asonti/<br>602-768-6071<br>asonti1@asu.edu" in recruiter_html
    assert "I thought you might be a good person to reach out to for some perspective on this opening." in manager_body
    assert "MS in Computer Science at ASU" not in manager_body
    assert "Arizona State University" not in manager_body
    assert "15-minute Zoom" not in manager_body
    assert "Lately, I have been spending time sharpening my Agentic AI skills." in manager_body
    assert "I built Job Hunt Copilot (https://github.com/sontiachyut/job-hunt-copilot-v4) for my own job search to help me identify relevant roles and the right people to reach out to." in manager_body
    assert "The AI agent runs autonomously with human-in-the-loop (HITL) review, and I personally review every email before it goes out. This email is a live example of that workflow." in manager_body
    assert "strong fit" not in manager_body
    assert "seems close to" not in manager_body
    assert "I came across the" not in manager_body
    assert "The emphasis on" not in manager_body
    assert "That is what prompted me to reach out." not in manager_body
    assert "which is what prompted me to reach out." not in manager_body
    assert "I've included a short snippet below that you can paste into an IM/Email:" in manager_body
    assert "[snippet]" in manager_body
    assert "[/snippet]" in manager_body
    assert (
        "Hi, passing along a candidate who may be worth a look for the Staff Software Engineer / AI role at Acme Robotics."
        in manager_body
    )
    assert (
        "His background overlaps well with the role's focus on reliable backend and distributed systems for AI platform workloads, "
        "and he's intentionally growing in that direction, "
        "including building distributed Python and Scala data services processing 50M+ daily HL7 records at roughly 580 TPS for real-time analytics."
        in manager_body
    )

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


def test_role_targeted_drafting_requires_an_approved_tailoring_run(tmp_path: Path):
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
    seed_approved_tailoring_run(connection, paths)
    connection.execute(
        """
        UPDATE resume_tailoring_runs
        SET resume_review_status = ?, updated_at = ?
        WHERE resume_tailoring_run_id = ?
        """,
        ("resume_review_pending", "2026-04-06T20:25:00Z", "rtr_outreach"),
    )
    connection.commit()

    with pytest.raises(OutreachDraftingError, match="not backed by an approved tailoring run"):
        generate_role_targeted_send_set_drafts(
            connection,
            project_root=project_root,
            job_posting_id="jp_outreach",
            current_time="2026-04-06T20:30:00Z",
            local_timezone=ZoneInfo("UTC"),
        )

    connection.close()


def test_role_targeted_drafting_stays_grounded_in_stored_inputs_not_raw_source_claims(
    tmp_path: Path,
):
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
    lead_workspace = paths.lead_workspace_dir(
        "Acme Robotics",
        "Staff Software Engineer / AI",
        "ld_outreach",
    )
    raw_source_path = lead_workspace / "raw" / "source.md"
    raw_source_path.parent.mkdir(parents=True, exist_ok=True)
    raw_source_path.write_text(
        "# Raw source\nFormer teammate of the CEO with 12 years of Rust experience.\n",
        encoding="utf-8",
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

    body_text = Path(result.drafted_messages[0].body_text_artifact_path).read_text(encoding="utf-8")
    assert "I thought you might have useful perspective on the hiring context for this opening." in body_text
    assert "50M+ daily HL7 records" in body_text
    assert "Former teammate of the CEO" not in body_text
    assert "12 years of Rust experience" not in body_text

    connection.close()


def test_role_targeted_drafting_filters_jd_boilerplate_from_opening_and_subject(
    tmp_path: Path,
):
    project_root, paths = bootstrap_project(tmp_path)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    write_sender_profile(paths)
    seed_posting(
        connection,
        company_name="ASM",
        role_title='Manager I. Software Engineering- "Scheduler"',
    )
    seed_linked_contact(
        connection,
        contact_id="ct_mgr",
        job_posting_contact_id="jpc_mgr",
        display_name="Bryan Chau",
        recipient_type=RECIPIENT_TYPE_HIRING_MANAGER,
        current_working_email="bryan@asm.example",
        created_at="2026-04-06T20:01:00Z",
    )
    seed_approved_tailoring_run(
        connection,
        paths,
        company_name="ASM",
        role_title='Manager I. Software Engineering- "Scheduler"',
    )
    paths.tailoring_step_3_jd_signals_path(
        "ASM",
        'Manager I. Software Engineering- "Scheduler"',
    ).write_text(
        yaml.safe_dump(
            {
                "job_posting_id": "jp_outreach",
                "resume_tailoring_run_id": "rtr_outreach",
                "status": "generated",
                "role_intent_summary": (
                    "For over 55 years ASM has been ahead of what's next.; "
                    "As a Manager, Software Engineering for our Scheduling Team, you'll lead a group "
                    "of talented engineers building advanced scheduling engines that power real-time "
                    "control systems across global chipmaking fabs."
                ),
                "signals_by_priority": {
                    "must_have": [
                        {
                            "signal_id": "signal_must_1",
                            "priority": "must_have",
                            "signal": "3+ years relevant experience and a Bachelor’s degree OR any equivalent combination of education and experience.",
                        }
                    ],
                    "core_responsibility": [
                        {
                            "signal_id": "signal_core_1",
                            "priority": "core_responsibility",
                            "signal": "For over 55 years ASM has been ahead of what's next, at the forefront of innovation.",
                        },
                        {
                            "signal_id": "signal_core_2",
                            "priority": "core_responsibility",
                            "signal": "Drive the design, development, testing, and deployment of scheduling engines for multiple platforms.",
                        },
                    ],
                    "nice_to_have": [],
                    "informational": [],
                },
                "signals": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = generate_role_targeted_send_set_drafts(
        connection,
        project_root=project_root,
        job_posting_id="jp_outreach",
        current_time="2026-04-06T20:30:00Z",
        local_timezone=ZoneInfo("UTC"),
    )

    message = result.drafted_messages[0]
    body_text = Path(message.body_text_artifact_path).read_text(encoding="utf-8")
    assert 'I\'m reaching out about the Manager I. Software Engineering- "Scheduler" role at ASM because I was ' in body_text
    assert "scheduling engines" in body_text
    assert (
        "That lines up well with the kind of systems and leadership work I've done and want to keep leaning into."
        in body_text
    )
    assert "3+ years relevant experience" not in body_text
    assert "For over 55 years ASM" not in body_text
    assert message.subject == 'Interest in the Manager I. Software Engineering- "Scheduler" role at ASM'
    assert "Impact:" not in message.subject

    connection.close()


def test_role_targeted_composition_rewrites_security_jd_into_natural_theme(tmp_path: Path):
    project_root, paths = bootstrap_project(tmp_path)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    write_sender_profile(paths)
    seed_posting(
        connection,
        company_name="Intel",
        role_title="Government Information Security Engineer",
    )
    seed_linked_contact(
        connection,
        contact_id="ct_intel",
        job_posting_contact_id="jpc_intel",
        display_name="Jason Allsburg",
        recipient_type=RECIPIENT_TYPE_HIRING_MANAGER,
        current_working_email="jason@intel.example",
        created_at="2026-04-06T20:01:00Z",
    )
    connection.execute(
        "UPDATE contacts SET position_title = ? WHERE contact_id = ?",
        ("Director of Engineering", "ct_intel"),
    )
    connection.commit()
    seed_approved_tailoring_run(
        connection,
        paths,
        company_name="Intel",
        role_title="Government Information Security Engineer",
    )
    paths.tailoring_step_3_jd_signals_path(
        "Intel",
        "Government Information Security Engineer",
    ).write_text(
        yaml.safe_dump(
            {
                "job_posting_id": "jp_outreach",
                "resume_tailoring_run_id": "rtr_outreach",
                "status": "generated",
                "role_intent_summary": (
                    "Identifies, develops, plans, implements, and supports enterprise security systems "
                    "using Agile methodologies and DevOps principles to improve and grow secure solutions "
                    "for Intel Federal with a constant focus on security."
                ),
                "signals_by_priority": {
                    "must_have": [],
                    "core_responsibility": [],
                    "nice_to_have": [],
                    "informational": [],
                },
                "signals": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = generate_role_targeted_send_set_drafts(
        connection,
        project_root=project_root,
        job_posting_id="jp_outreach",
        current_time="2026-04-06T20:30:00Z",
        local_timezone=ZoneInfo("UTC"),
    )

    body_text = Path(result.drafted_messages[0].body_text_artifact_path).read_text(encoding="utf-8")
    assert (
        "I'm reaching out about the Government Information Security Engineer role at Intel because I was "
        "interested in the role's focus on secure infrastructure, enterprise security systems, and "
        "government-focused security work. "
        "I see a real overlap with the systems work I've done, and it's an area I want to keep building depth in."
        in body_text
    )
    assert "identifies, develops, plans, implements" not in body_text.lower()
    assert "Given your role as Director of Engineering, I thought you might be a good person to reach out to for some perspective on this opening." in body_text

    connection.close()


def test_role_targeted_composition_uses_specific_work_area_in_opener_when_available(
    tmp_path: Path,
):
    project_root, paths = bootstrap_project(tmp_path)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    write_sender_profile(paths)
    seed_posting(
        connection,
        company_name="Scribd, Inc.",
        role_title="Software Engineer - Backend (Python)",
    )
    seed_linked_contact(
        connection,
        contact_id="ct_scribd",
        job_posting_contact_id="jpc_scribd",
        display_name="Ashod Nakashian",
        recipient_type=RECIPIENT_TYPE_ENGINEER,
        current_working_email="ashod@scribd.example",
        created_at="2026-04-06T20:01:00Z",
    )
    connection.execute(
        "UPDATE contacts SET position_title = ? WHERE contact_id = ?",
        ("Software Engineer", "ct_scribd"),
    )
    connection.commit()
    seed_approved_tailoring_run(
        connection,
        paths,
        company_name="Scribd, Inc.",
        role_title="Software Engineer - Backend (Python)",
    )
    paths.tailoring_step_3_jd_signals_path(
        "Scribd, Inc.",
        "Software Engineer - Backend (Python)",
    ).write_text(
        yaml.safe_dump(
            {
                "job_posting_id": "jp_outreach",
                "resume_tailoring_run_id": "rtr_outreach",
                "status": "generated",
                "role_intent_summary": (
                    "Implement event-driven, distributed systems to extract, enrich, and "
                    "process metadata from large-scale document and media datasets."
                ),
                "signals_by_priority": {
                    "must_have": [],
                    "core_responsibility": [],
                    "nice_to_have": [],
                    "informational": [],
                },
                "signals": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = generate_role_targeted_send_set_drafts(
        connection,
        project_root=project_root,
        job_posting_id="jp_outreach",
        current_time="2026-04-06T20:30:00Z",
        local_timezone=ZoneInfo("UTC"),
    )

    body_text = Path(result.drafted_messages[0].body_text_artifact_path).read_text(encoding="utf-8")
    assert (
        "I'm reaching out about the Software Engineer - Backend (Python) role at Scribd, Inc. because I was "
        "interested in the role's focus on implementing event-driven, distributed systems to extract, enrich, "
        "and process metadata from large-scale document and media datasets."
        in body_text
    )
    assert (
        "That lines up well with the kind of backend and distributed systems work I've done and want to keep growing in."
        in body_text
    )

    connection.close()


def test_role_targeted_composition_prefers_full_cycle_ai_ml_delivery_over_uat_style_hooks(
    tmp_path: Path,
):
    project_root, paths = bootstrap_project(tmp_path)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    write_sender_profile(paths)
    seed_posting(
        connection,
        company_name="Honeywell",
        role_title="Advanced AI Engineer (Generative AI)",
    )
    seed_linked_contact(
        connection,
        contact_id="ct_honeywell",
        job_posting_contact_id="jpc_honeywell",
        display_name="Salvador Dominguez",
        recipient_type=RECIPIENT_TYPE_ENGINEER,
        current_working_email="salvador@honeywell.example",
        created_at="2026-04-06T20:01:00Z",
    )
    connection.execute(
        "UPDATE contacts SET position_title = ? WHERE contact_id = ?",
        ("Advanced AI Engineer", "ct_honeywell"),
    )
    connection.commit()
    seed_approved_tailoring_run(
        connection,
        paths,
        company_name="Honeywell",
        role_title="Advanced AI Engineer (Generative AI)",
    )
    paths.tailoring_step_3_jd_signals_path(
        "Honeywell",
        "Advanced AI Engineer (Generative AI)",
    ).write_text(
        yaml.safe_dump(
            {
                "job_posting_id": "jp_outreach",
                "resume_tailoring_run_id": "rtr_outreach",
                "status": "generated",
                "role_intent_summary": (
                    "Join a company that is transforming from a traditional industrial company to a contemporary digital industrial business, harnessing the power of cloud, big data, analytics, Internet of Things, AI/ML (Machine Learning), Automation and design thinking."
                ),
                "signals_by_priority": {
                    "must_have": [],
                    "core_responsibility": [
                        {
                            "signal": (
                                "You will be part of the IT Information Management & Analytics team and in this role, you will at the forefront of implementing state-of-the-art Generative AI, Machine Learning and AI Cognitive Services enhanced business use cases. This Advanced AI Engineer role will work with the business stakeholders, IT business partners, functional consultants, and infrastructure/technology teams to deliver innovative AI technology solutions that accelerate digital transformation and drive operational efficiency as well as business growth. You will focus primarily on the full cycle delivery of AI/ML use cases from requirements/design to release, driving the evolution of AI/ML infrastructure/process, and enabling Intelligent Apps & Automation, next generation of AI Copilots/Assistants, etc."
                            )
                        },
                        {
                            "signal": "Collaborate with data scientists and data engineers to build production-level models and pipelines, including any required preprocessing of input datasets and postprocessing after model inference."
                        },
                        {
                            "signal": "Help develop standard operation practices and support the Operations Teams through UAT and after go-live."
                        },
                    ],
                    "nice_to_have": [],
                    "informational": [],
                },
                "signals": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    paths.tailoring_step_4_evidence_map_path(
        "Honeywell",
        "Advanced AI Engineer (Generative AI)",
    ).write_text(
        yaml.safe_dump(
            {
                "matches": [
                    {
                        "jd_signal": (
                            "You will be part of the IT Information Management & Analytics team and in this role, you will at the forefront of implementing state-of-the-art Generative AI, Machine Learning and AI Cognitive Services enhanced business use cases. This Advanced AI Engineer role will work with the business stakeholders, IT business partners, functional consultants, and infrastructure/technology teams to deliver innovative AI technology solutions that accelerate digital transformation and drive operational efficiency as well as business growth. You will focus primarily on the full cycle delivery of AI/ML use cases from requirements/design to release, driving the evolution of AI/ML infrastructure/process, and enabling Intelligent Apps & Automation, next generation of AI Copilots/Assistants, etc."
                        ),
                        "confidence": "high",
                        "source_excerpt": "Built and maintained distributed, high-availability data services in Python and Scala on AWS, processing 50M+ daily HL7 records (~580 TPS).",
                    },
                    {
                        "jd_signal": "Collaborate with data scientists and data engineers to build production-level models and pipelines, including any required preprocessing of input datasets and postprocessing after model inference.",
                        "confidence": "high",
                        "source_excerpt": "Developed ETL pipelines using Python and Apache Spark, reducing processing time by 40% on 2TB+ daily data.",
                    },
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = generate_role_targeted_send_set_drafts(
        connection,
        project_root=project_root,
        job_posting_id="jp_outreach",
        current_time="2026-04-06T20:30:00Z",
        local_timezone=ZoneInfo("UTC"),
    )

    body_text = Path(result.drafted_messages[0].body_text_artifact_path).read_text(encoding="utf-8")
    assert (
        "I'm reaching out about the Advanced AI Engineer (Generative AI) role at Honeywell because I was "
        "interested in the role's focus on full-cycle AI/ML delivery and AI/ML infrastructure evolution."
        in body_text
    )
    assert (
        "I see a real overlap with the systems work I've done, and it's an area I want to keep building depth in."
        in body_text
    )
    assert (
        "His background overlaps well with the role's focus on full-cycle AI/ML delivery and AI/ML infrastructure evolution"
        in body_text
    )
    assert "His background is in full-cycle AI/ML delivery" not in body_text
    assert "UAT and after go-live" not in body_text
    assert "standard operation practices" not in body_text

    connection.close()


def test_role_targeted_composition_prefers_technical_jd_signals_over_generic_responsibilities(
    tmp_path: Path,
):
    project_root, paths = bootstrap_project(tmp_path)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    write_sender_profile(paths)
    seed_posting(
        connection,
        company_name="KUBRA",
        role_title="Software Engineer -Java",
    )
    seed_linked_contact(
        connection,
        contact_id="ct_kubra",
        job_posting_contact_id="jpc_kubra",
        display_name="Suganthi Cidambaram",
        recipient_type=RECIPIENT_TYPE_ENGINEER,
        current_working_email="suganthi@kubra.example",
        created_at="2026-04-06T20:01:00Z",
    )
    connection.execute(
        "UPDATE contacts SET position_title = ? WHERE contact_id = ?",
        ("Senior Software Engineer, Product Engineering", "ct_kubra"),
    )
    connection.commit()
    seed_approved_tailoring_run(
        connection,
        paths,
        company_name="KUBRA",
        role_title="Software Engineer -Java",
    )
    paths.tailoring_step_3_jd_signals_path(
        "KUBRA",
        "Software Engineer -Java",
    ).write_text(
        yaml.safe_dump(
            {
                "job_posting_id": "jp_outreach",
                "resume_tailoring_run_id": "rtr_outreach",
                "status": "generated",
                "role_intent_summary": (
                    "KUBRA is looking for a Software Developer, Java to join our Payments Engineering "
                    "team. In this role, you will help design, build, and enhance enterprise-scale "
                    "software solutions that support exceptional customer experiences and high-performance "
                    "payment systems.; You will work closely with engineers, team leads, and designers "
                    "to turn business and client requirements into scalable product features."
                ),
                "signals_by_priority": {
                    "must_have": [
                        {
                            "signal": "3-5 years of professional software development experience in Java-based environments"
                        },
                        {
                            "signal": "2+ years of hands-on experience building REST APIs or microservices"
                        },
                    ],
                    "core_responsibility": [
                        {
                            "signal": "Contribute to design of new functionality and expand existing functionality"
                        },
                        {
                            "signal": "Communicate with Software Engineers, Team Lead, and designers"
                        },
                    ],
                    "nice_to_have": [
                        {
                            "signal": "Experience with frameworks such as Spring Boot or Jakarta EE"
                        },
                        {
                            "signal": "Solid understanding of Java concurrency, relational databases, and stream processing"
                        },
                    ],
                    "informational": [],
                },
                "signals": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    paths.tailoring_step_4_evidence_map_path(
        "KUBRA",
        "Software Engineer -Java",
    ).write_text(
        yaml.safe_dump(
            {
                "matches": [
                    {
                        "jd_signal": "2+ years of hands-on experience building REST APIs or microservices",
                        "confidence": "medium",
                        "source_excerpt": "Cloud Meraki tracked 200+ microservices and exposed backend APIs in Golang and Java",
                    },
                    {
                        "jd_signal": "2+ years of hands-on experience building REST APIs or microservices",
                        "confidence": "medium",
                        "source_excerpt": "The optimizer engine and backend APIs in Golang and Java",
                    },
                    {
                        "jd_signal": "Strong proficiency in Java 17+, object-oriented design, and design patterns",
                        "confidence": "high",
                        "source_excerpt": "Cloud Meraki tracked resource usage patterns across the 200+ microservice fleet on Kubernetes",
                    },
                    {
                        "jd_signal": "Strong proficiency in Java 17+, object-oriented design, and design patterns",
                        "confidence": "high",
                        "source_excerpt": "Observed usage patterns across services",
                    },
                    {
                        "jd_signal": "Solid understanding of Java concurrency, relational databases, and stream processing",
                        "confidence": "low",
                        "source_excerpt": "some weak database overlap",
                    },
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = generate_role_targeted_send_set_drafts(
        connection,
        project_root=project_root,
        job_posting_id="jp_outreach",
        current_time="2026-04-06T20:30:00Z",
        local_timezone=ZoneInfo("UTC"),
    )

    body_text = Path(result.drafted_messages[0].body_text_artifact_path).read_text(encoding="utf-8")
    assert "role's focus on REST APIs or microservices" in body_text
    assert "role's focus on contribute to design of new functionality" not in body_text
    assert "Communicate with Software Engineers" not in body_text

    connection.close()


def test_role_targeted_composition_rejects_mixed_ai_security_hook_when_backend_theme_is_better_supported(
    tmp_path: Path,
):
    project_root, paths = bootstrap_project(tmp_path)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    write_sender_profile(paths)
    seed_posting(
        connection,
        company_name="American Express",
        role_title="Software Engineer II",
    )
    seed_linked_contact(
        connection,
        contact_id="ct_amex",
        job_posting_contact_id="jpc_amex",
        display_name="Shawn Spence",
        recipient_type=RECIPIENT_TYPE_ENGINEER,
        current_working_email="shawn@amex.example",
        created_at="2026-04-06T20:01:00Z",
    )
    connection.execute(
        "UPDATE contacts SET position_title = ? WHERE contact_id = ?",
        ("Software Engineer II", "ct_amex"),
    )
    connection.commit()
    seed_approved_tailoring_run(
        connection,
        paths,
        company_name="American Express",
        role_title="Software Engineer II",
    )
    paths.tailoring_step_3_jd_signals_path(
        "American Express",
        "Software Engineer II",
    ).write_text(
        yaml.safe_dump(
            {
                "job_posting_id": "jp_outreach",
                "resume_tailoring_run_id": "rtr_outreach",
                "status": "generated",
                "role_intent_summary": (
                    "Build large-scale, cloud-native applications while leveraging modern "
                    "developer productivity tools, including Generative AI-assisted development "
                    "tools, in a secure transaction platform."
                ),
                "signals_by_priority": {
                    "must_have": [],
                    "core_responsibility": [
                        {
                            "signal": (
                                "Leverage modern developer productivity tools, including "
                                "Generative AI-assisted development tools, to accelerate coding, "
                                "debugging, documentation, and testing while maintaining high "
                                "standards of code quality and security."
                            )
                        },
                        {
                            "signal": (
                                "Build and enhance scalable microservices and APIs that support "
                                "fraud risk assessment and secure customer transaction processing."
                            )
                        },
                        {
                            "signal": (
                                "Develop and optimize high-throughput data pipelines to improve "
                                "system efficiency, reliability, and scalability."
                            )
                        },
                    ],
                    "nice_to_have": [],
                    "informational": [],
                },
                "signals": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    paths.tailoring_step_4_evidence_map_path(
        "American Express",
        "Software Engineer II",
    ).write_text(
        yaml.safe_dump(
            {
                "matches": [
                    {
                        "jd_signal": (
                            "Build and enhance scalable microservices and APIs that support fraud "
                            "risk assessment and secure customer transaction processing."
                        ),
                        "confidence": "high",
                        "source_excerpt": (
                            "Built and maintained distributed, high-availability data services in "
                            "Python and Scala on AWS, processing 50M+ daily HL7 records (~580 TPS)."
                        ),
                    },
                    {
                        "jd_signal": (
                            "Develop and optimize high-throughput data pipelines to improve system "
                            "efficiency, reliability, and scalability."
                        ),
                        "confidence": "high",
                        "source_excerpt": (
                            "Developed ETL pipelines using Python and Apache Spark, reducing "
                            "processing time by 40% on 2TB+ daily data."
                        ),
                    },
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = generate_role_targeted_send_set_drafts(
        connection,
        project_root=project_root,
        job_posting_id="jp_outreach",
        current_time="2026-04-06T20:30:00Z",
        local_timezone=ZoneInfo("UTC"),
    )

    body_text = Path(result.drafted_messages[0].body_text_artifact_path).read_text(encoding="utf-8")
    assert "role's focus on backend APIs and services" in body_text
    assert "machine learning and deep learning and secure infrastructure" not in body_text
    assert "That lines up with the kind of systems work I've been doing." not in body_text
    assert (
        "That lines up well with the kind of backend and distributed systems work I've done and want to keep growing in."
        in body_text
    )
    assert "His background is in machine learning and deep learning and secure infrastructure" not in body_text
    assert "His background is in backend APIs and services" in body_text

    connection.close()


def test_role_targeted_composition_filters_generic_join_our_team_role_intro(
    tmp_path: Path,
):
    project_root, paths = bootstrap_project(tmp_path)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    write_sender_profile(paths)
    seed_posting(
        connection,
        company_name="Valore Partners",
        role_title="Software Engineer",
    )
    seed_linked_contact(
        connection,
        contact_id="ct_valore",
        job_posting_contact_id="jpc_valore",
        display_name="Paul Example",
        recipient_type=RECIPIENT_TYPE_ENGINEER,
        current_working_email="paul@valore.example",
        created_at="2026-04-06T20:01:00Z",
    )
    connection.execute(
        "UPDATE contacts SET position_title = ? WHERE contact_id = ?",
        ("Sr. Software Engineer", "ct_valore"),
    )
    connection.commit()
    seed_approved_tailoring_run(
        connection,
        paths,
        company_name="Valore Partners",
        role_title="Software Engineer",
    )
    paths.tailoring_step_3_jd_signals_path(
        "Valore Partners",
        "Software Engineer",
    ).write_text(
        yaml.safe_dump(
            {
                "job_posting_id": "jp_outreach",
                "resume_tailoring_run_id": "rtr_outreach",
                "status": "generated",
                "role_intent_summary": (
                    "Seeking a Software Engineer to join our team; you will help build and drive solutions "
                    "in a team member capacity, solving complex business problems, using some of the newest "
                    "technologies available."
                ),
                "signals_by_priority": {
                    "must_have": [],
                    "core_responsibility": [
                        {
                            "signal": "Design, develop, and test secure, high-performing, web-based client-server applications with an emphasis on user experience and quality"
                        },
                        {
                            "signal": "API Development & Testing: RESTful services, Swagger, Postman"
                        },
                    ],
                    "nice_to_have": [],
                    "informational": [],
                },
                "signals": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    paths.tailoring_step_4_evidence_map_path(
        "Valore Partners",
        "Software Engineer",
    ).write_text(
        yaml.safe_dump(
            {
                "matches": [
                    {
                        "jd_signal": "API Development & Testing: RESTful services, Swagger, Postman",
                        "confidence": "high",
                        "source_excerpt": "The optimizer engine and backend APIs in Golang and Java",
                    },
                    {
                        "jd_signal": "API Development & Testing: RESTful services, Swagger, Postman",
                        "confidence": "high",
                        "source_excerpt": "Built backend APIs in Golang and Java for production services",
                    },
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = generate_role_targeted_send_set_drafts(
        connection,
        project_root=project_root,
        job_posting_id="jp_outreach",
        current_time="2026-04-06T20:30:00Z",
        local_timezone=ZoneInfo("UTC"),
    )

    body_text = Path(result.drafted_messages[0].body_text_artifact_path).read_text(encoding="utf-8")
    assert "role's focus on RESTful services, Swagger, Postman" in body_text
    assert "role's focus on seeking a Software Engineer to join our team" not in body_text

    connection.close()


def test_role_targeted_composition_prefers_jd_faithful_backend_focus_over_fit_summary_drift(
    tmp_path: Path,
):
    project_root, paths = bootstrap_project(tmp_path)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    write_sender_profile(paths)
    seed_posting(
        connection,
        company_name="Garmin",
        role_title="Software Engineer - Full Stack (Java/Angular)",
    )
    seed_linked_contact(
        connection,
        contact_id="ct_garmin",
        job_posting_contact_id="jpc_garmin",
        company_name="Garmin",
        display_name="Robert Sorensen",
        recipient_type=RECIPIENT_TYPE_HIRING_MANAGER,
        current_working_email="robert.sorensen@example.com",
        created_at="2026-04-06T20:01:00Z",
    )
    connection.execute(
        "UPDATE contacts SET position_title = ? WHERE contact_id = ?",
        ("Software Engineering Manager", "ct_garmin"),
    )
    connection.commit()
    seed_approved_tailoring_run(
        connection,
        paths,
        company_name="Garmin",
        role_title="Software Engineer - Full Stack (Java/Angular)",
    )
    paths.tailoring_workspace_jd_path(
        "Garmin",
        "Software Engineer - Full Stack (Java/Angular)",
    ).write_text(
        "\n".join(
            [
                "# Software Engineer - Full Stack (Java/Angular)",
                "",
                "## Desired Qualifications",
                "- Frontend work will include project heavily using Angular, as well as HTML, CSS, JavaScript and Bootstrap.",
                "- Backend work will include technologies such as Java, Scala, Kotlin, RESTful, Oracle, Postgres, Spring and containerization technologies such as Docker, Podman, CRI-O, Kubernetes and PCF.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    paths.tailoring_step_3_jd_signals_path(
        "Garmin",
        "Software Engineer - Full Stack (Java/Angular)",
    ).write_text(
        yaml.safe_dump(
            {
                "job_posting_id": "jp_outreach",
                "resume_tailoring_run_id": "rtr_outreach",
                "status": "generated",
                "role_intent_summary": (
                    "We are seeking a full-time Software Engineer - Full Stack (Java/Angular) in our Chandler, AZ location."
                ),
                "signals_by_priority": {
                    "must_have": [
                        {
                            "signal_id": "signal_must_backend",
                            "priority": "must_have",
                            "signal": (
                                "Backend work will include technologies such as Java, Scala, Kotlin, RESTful, Oracle, Postgres, "
                                "Spring and containerization technologies such as Docker, Podman, CRI-O, Kubernetes and PCF"
                            ),
                        }
                    ],
                    "core_responsibility": [],
                    "nice_to_have": [],
                    "informational": [],
                },
                "signals": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    paths.tailoring_step_4_evidence_map_path(
        "Garmin",
        "Software Engineer - Full Stack (Java/Angular)",
    ).write_text(
        yaml.safe_dump(
            {
                "matches": [
                    {
                        "jd_signal": (
                            "Backend work will include technologies such as Java, Scala, Kotlin, RESTful, Oracle, Postgres, "
                            "Spring and containerization technologies such as Docker, Podman, CRI-O, Kubernetes and PCF"
                        ),
                        "confidence": "high",
                        "source_excerpt": "The optimizer engine and backend APIs in Golang and Java",
                    },
                    {
                        "jd_signal": (
                            "Backend work will include technologies such as Java, Scala, Kotlin, RESTful, Oracle, Postgres, "
                            "Spring and containerization technologies such as Docker, Podman, CRI-O, Kubernetes and PCF"
                        ),
                        "confidence": "high",
                        "source_excerpt": "Built backend APIs in Golang and Java for production services",
                    },
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    paths.tailoring_step_6_candidate_bullets_path(
        "Garmin",
        "Software Engineer - Full Stack (Java/Angular)",
    ).write_text(
        yaml.safe_dump(
            {
                "job_posting_id": "jp_outreach",
                "resume_tailoring_run_id": "rtr_outreach",
                "status": "generated",
                "summary": "MS CS candidate with 3+ years building backend data services and distributed systems.",
                "technical_skills": [
                    {
                        "category": "Infrastructure & Systems",
                        "items": ["Distributed Systems", "System Design", "gRPC", "Load Balancing"],
                        "matched_signal_ids": ["signal_must_backend"],
                    }
                ],
                "software_engineer": {
                    "bullets": [
                        {
                            "text": "Built high-availability Python and Scala backend data services on AWS (EMR, S3), processing 50M+ daily HL7 records (~580 TPS) for real-time analytics across 1,500+ hospitals with 24/7 uptime",
                            "purpose": "scale-impact",
                            "support_pointers": ["match_1"],
                            "covered_signal_ids": ["signal_must_backend"],
                            "char_count": 190,
                        }
                    ]
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = generate_role_targeted_send_set_drafts(
        connection,
        project_root=project_root,
        job_posting_id="jp_outreach",
        current_time="2026-04-06T20:30:00Z",
        local_timezone=ZoneInfo("UTC"),
    )

    body_text = Path(result.drafted_messages[0].body_text_artifact_path).read_text(encoding="utf-8")
    assert "role's focus on Java, Scala, RESTful services, and Spring" in body_text
    assert "distributed services" not in body_text
    assert "production delivery" not in body_text

    connection.close()


def test_role_targeted_composition_strips_weak_requirement_prefixes_from_opener_hooks(
    tmp_path: Path,
):
    project_root, paths = bootstrap_project(tmp_path)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    write_sender_profile(paths)
    seed_posting(
        connection,
        company_name="Universal Background Screening",
        role_title="Jr Software Engineer (Remote Available)",
    )
    seed_linked_contact(
        connection,
        contact_id="ct_universal",
        job_posting_contact_id="jpc_universal",
        display_name="Francisco Example",
        recipient_type=RECIPIENT_TYPE_ENGINEER,
        current_working_email="francisco@universal.example",
        created_at="2026-04-06T20:01:00Z",
    )
    connection.execute(
        "UPDATE contacts SET position_title = ? WHERE contact_id = ?",
        ("Senior Software Engineer", "ct_universal"),
    )
    connection.commit()
    seed_approved_tailoring_run(
        connection,
        paths,
        company_name="Universal Background Screening",
        role_title="Jr Software Engineer (Remote Available)",
    )
    paths.tailoring_step_3_jd_signals_path(
        "Universal Background Screening",
        "Jr Software Engineer (Remote Available)",
    ).write_text(
        yaml.safe_dump(
            {
                "job_posting_id": "jp_outreach",
                "resume_tailoring_run_id": "rtr_outreach",
                "status": "generated",
                "role_intent_summary": (
                    "The Junior Software Engineer supports the development and maintenance of software applications."
                ),
                "signals_by_priority": {
                    "must_have": [
                        {
                            "signal": "Basic understanding of cloud platforms (AWS or Azure)"
                        },
                    ],
                    "core_responsibility": [
                        {
                            "signal": "Support cloud-based applications and services on AWS or Azure platforms"
                        },
                    ],
                    "nice_to_have": [],
                    "informational": [],
                },
                "signals": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    paths.tailoring_step_4_evidence_map_path(
        "Universal Background Screening",
        "Jr Software Engineer (Remote Available)",
    ).write_text(
        yaml.safe_dump(
            {
                "matches": [
                    {
                        "jd_signal": "Support cloud-based applications and services on AWS or Azure platforms",
                        "confidence": "high",
                        "source_excerpt": "Built distributed, high-availability data services in Python and Scala on AWS (EMR, S3)",
                    },
                    {
                        "jd_signal": "Support cloud-based applications and services on AWS or Azure platforms",
                        "confidence": "high",
                        "source_excerpt": "Optimized Apache Spark jobs on AWS EMR and improved throughput by 50%",
                    },
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = generate_role_targeted_send_set_drafts(
        connection,
        project_root=project_root,
        job_posting_id="jp_outreach",
        current_time="2026-04-06T20:30:00Z",
        local_timezone=ZoneInfo("UTC"),
    )

    body_text = Path(result.drafted_messages[0].body_text_artifact_path).read_text(encoding="utf-8")
    assert "role's focus on supporting cloud-based applications and services on AWS or Azure platforms" in body_text
    assert "role's focus on basic understanding of cloud platforms" not in body_text

    connection.close()


def test_role_targeted_composition_does_not_overclassify_generic_backend_roles_as_security(
    tmp_path: Path,
):
    project_root, paths = bootstrap_project(tmp_path)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    write_sender_profile(paths)
    seed_posting(
        connection,
        company_name="PayPal",
        role_title="Sr Software Engineer",
    )
    seed_linked_contact(
        connection,
        contact_id="ct_paypal",
        job_posting_contact_id="jpc_paypal",
        display_name="Courtney Ngai",
        recipient_type=RECIPIENT_TYPE_ENGINEER,
        current_working_email="courtney@paypal.example",
        created_at="2026-04-06T20:01:00Z",
    )
    connection.execute(
        "UPDATE contacts SET position_title = ? WHERE contact_id = ?",
        ("Senior Software Engineer", "ct_paypal"),
    )
    connection.commit()
    seed_approved_tailoring_run(
        connection,
        paths,
        company_name="PayPal",
        role_title="Sr Software Engineer",
    )
    paths.tailoring_step_3_jd_signals_path(
        "PayPal",
        "Sr Software Engineer",
    ).write_text(
        yaml.safe_dump(
            {
                "job_posting_id": "jp_outreach",
                "resume_tailoring_run_id": "rtr_outreach",
                "status": "generated",
                "role_intent_summary": (
                    "Build secure, highly available backend services and distributed systems "
                    "that support product delivery across the software lifecycle."
                ),
                "signals_by_priority": {
                    "must_have": [],
                    "core_responsibility": [],
                    "nice_to_have": [],
                    "informational": [],
                },
                "signals": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = generate_role_targeted_send_set_drafts(
        connection,
        project_root=project_root,
        job_posting_id="jp_outreach",
        current_time="2026-04-06T20:30:00Z",
        local_timezone=ZoneInfo("UTC"),
    )

    body_text = Path(result.drafted_messages[0].body_text_artifact_path).read_text(encoding="utf-8")
    assert (
        "I'm reaching out about the Sr Software Engineer role at PayPal because I was interested in the role's "
        "focus on backend APIs and services and distributed systems."
        in body_text
    )
    assert "government-focused security work" not in body_text

    connection.close()


def test_role_targeted_composition_filters_benefits_from_focus_selection(tmp_path: Path):
    project_root, paths = bootstrap_project(tmp_path)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    write_sender_profile(paths)
    seed_posting(
        connection,
        company_name="TEKsystems",
        role_title="Backend Developer",
    )
    seed_linked_contact(
        connection,
        contact_id="ct_teksystems",
        job_posting_contact_id="jpc_teksystems",
        display_name="Taylor Recruiter",
        recipient_type=RECIPIENT_TYPE_RECRUITER,
        current_working_email="taylor@teksystems.example",
        created_at="2026-04-06T20:01:00Z",
    )
    seed_approved_tailoring_run(
        connection,
        paths,
        company_name="TEKsystems",
        role_title="Backend Developer",
    )
    paths.tailoring_step_3_jd_signals_path(
        "TEKsystems",
        "Backend Developer",
    ).write_text(
        yaml.safe_dump(
            {
                "job_posting_id": "jp_outreach",
                "resume_tailoring_run_id": "rtr_outreach",
                "status": "generated",
                "role_intent_summary": (
                    "Medical, dental & vision; "
                    "Build Terraform-based infrastructure provisioning, API gateway build-out, "
                    "and workload identity automation for backend platform workloads."
                ),
                "signals_by_priority": {
                    "must_have": [
                        {"signal": "Medical, dental & vision"},
                    ],
                    "core_responsibility": [
                        {
                            "signal": (
                                "Build Terraform-based infrastructure provisioning, API gateway "
                                "build-out, and workload identity automation for backend platform workloads."
                            )
                        }
                    ],
                    "nice_to_have": [],
                    "informational": [],
                },
                "signals": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    paths.tailoring_step_4_evidence_map_path(
        "TEKsystems",
        "Backend Developer",
    ).write_text(
        yaml.safe_dump(
            {
                "matches": [
                    {
                        "jd_signal": (
                            "Build Terraform-based infrastructure provisioning, API gateway "
                            "build-out, and workload identity automation for backend platform workloads."
                        ),
                        "confidence": "high",
                        "source_excerpt": "Built infrastructure automation and backend platform services on AWS.",
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = generate_role_targeted_send_set_drafts(
        connection,
        project_root=project_root,
        job_posting_id="jp_outreach",
        current_time="2026-04-06T20:30:00Z",
        local_timezone=ZoneInfo("UTC"),
    )

    body_text = Path(result.drafted_messages[0].body_text_artifact_path).read_text(encoding="utf-8")
    assert "Medical, dental & vision" not in body_text
    assert "Terraform-based infrastructure provisioning" in body_text
    assert "API gateway build-out" in body_text
    assert "workload identity automation" in body_text

    connection.close()


def test_role_targeted_composition_filters_marketing_slogans_from_focus_selection(tmp_path: Path):
    project_root, paths = bootstrap_project(tmp_path)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    write_sender_profile(paths)
    seed_posting(
        connection,
        company_name="CNH",
        role_title="AI Development Engineer",
    )
    seed_linked_contact(
        connection,
        contact_id="ct_cnh",
        job_posting_contact_id="jpc_cnh",
        display_name="Morgan Engineer",
        recipient_type=RECIPIENT_TYPE_ENGINEER,
        current_working_email="morgan@cnh.example",
        created_at="2026-04-06T20:01:00Z",
    )
    seed_approved_tailoring_run(
        connection,
        paths,
        company_name="CNH",
        role_title="AI Development Engineer",
    )
    paths.tailoring_step_3_jd_signals_path(
        "CNH",
        "AI Development Engineer",
    ).write_text(
        yaml.safe_dump(
            {
                "job_posting_id": "jp_outreach",
                "resume_tailoring_run_id": "rtr_outreach",
                "status": "generated",
                "role_intent_summary": (
                    "Grow a Career. Build a Future!; "
                    "Develop machine learning and deep learning models for perception software on edge devices."
                ),
                "signals_by_priority": {
                    "must_have": [],
                    "core_responsibility": [
                        {"signal": "Grow a Career. Build a Future!"},
                        {
                            "signal": (
                                "Develop machine learning and deep learning models for perception "
                                "software on edge devices."
                            )
                        },
                    ],
                    "nice_to_have": [],
                    "informational": [],
                },
                "signals": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = generate_role_targeted_send_set_drafts(
        connection,
        project_root=project_root,
        job_posting_id="jp_outreach",
        current_time="2026-04-06T20:30:00Z",
        local_timezone=ZoneInfo("UTC"),
    )

    body_text = Path(result.drafted_messages[0].body_text_artifact_path).read_text(encoding="utf-8")
    assert "Grow a Career. Build a Future!" not in body_text
    assert "machine learning and deep learning" in body_text
    assert "perception software" in body_text
    assert "edge devices" in body_text

    connection.close()


def test_role_targeted_composition_summarizes_long_cloud_backend_signal(tmp_path: Path):
    project_root, paths = bootstrap_project(tmp_path)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    write_sender_profile(paths)
    seed_posting(
        connection,
        company_name="PayPal",
        role_title="System & Cloud Engineer",
    )
    seed_linked_contact(
        connection,
        contact_id="ct_paypal_cloud",
        job_posting_contact_id="jpc_paypal_cloud",
        display_name="Priya Engineer",
        recipient_type=RECIPIENT_TYPE_ENGINEER,
        current_working_email="priya@paypal.example",
        created_at="2026-04-06T20:01:00Z",
    )
    seed_approved_tailoring_run(
        connection,
        paths,
        company_name="PayPal",
        role_title="System & Cloud Engineer",
    )
    paths.tailoring_step_3_jd_signals_path(
        "PayPal",
        "System & Cloud Engineer",
    ).write_text(
        yaml.safe_dump(
            {
                "job_posting_id": "jp_outreach",
                "resume_tailoring_run_id": "rtr_outreach",
                "status": "generated",
                "role_intent_summary": "Build backend services and application delivery across cloud teams.",
                "signals_by_priority": {
                    "must_have": [
                        {
                            "signal": (
                                "At least one programming language like GoLang, Java, Ruby, Python to "
                                "design/build/test public cloud platform backend and automation tools."
                            )
                        }
                    ],
                    "core_responsibility": [
                        {
                            "signal": (
                                "Work with container orchestration tools to support cloud-native "
                                "production systems."
                            )
                        }
                    ],
                    "nice_to_have": [],
                    "informational": [],
                },
                "signals": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    paths.tailoring_step_4_evidence_map_path(
        "PayPal",
        "System & Cloud Engineer",
    ).write_text(
        yaml.safe_dump(
            {
                "matches": [
                    {
                        "jd_signal": (
                            "At least one programming language like GoLang, Java, Ruby, Python to "
                            "design/build/test public cloud platform backend and automation tools."
                        ),
                        "confidence": "high",
                        "source_excerpt": "Built backend automation services and cloud-native platform tooling on AWS.",
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = generate_role_targeted_send_set_drafts(
        connection,
        project_root=project_root,
        job_posting_id="jp_outreach",
        current_time="2026-04-06T20:30:00Z",
        local_timezone=ZoneInfo("UTC"),
    )

    body_text = Path(result.drafted_messages[0].body_text_artifact_path).read_text(encoding="utf-8")
    assert "at least one programming language like" not in body_text.lower()
    assert "public cloud" in body_text.lower()
    assert "automation" in body_text.lower()
    assert "application delivery" not in body_text.lower()
    assert "cloud-based production systems" not in body_text.lower()

    connection.close()


def test_role_targeted_composition_prefers_cloud_signal_over_generic_models_phrase(tmp_path: Path):
    project_root, paths = bootstrap_project(tmp_path)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    write_sender_profile(paths)
    seed_posting(
        connection,
        company_name="Wells Fargo",
        role_title="Senior Software Engineer",
    )
    seed_linked_contact(
        connection,
        contact_id="ct_wells",
        job_posting_contact_id="jpc_wells",
        display_name="Jordan Manager",
        recipient_type=RECIPIENT_TYPE_HIRING_MANAGER,
        current_working_email="jordan@wells.example",
        created_at="2026-04-06T20:01:00Z",
    )
    seed_approved_tailoring_run(
        connection,
        paths,
        company_name="Wells Fargo",
        role_title="Senior Software Engineer",
    )
    paths.tailoring_step_3_jd_signals_path(
        "Wells Fargo",
        "Senior Software Engineer",
    ).write_text(
        yaml.safe_dump(
            {
                "job_posting_id": "jp_outreach",
                "resume_tailoring_run_id": "rtr_outreach",
                "status": "generated",
                "role_intent_summary": "Build models, simulations, and analytics to support platform enhancements.",
                "signals_by_priority": {
                    "must_have": [
                        {
                            "signal": "2+ years building cloud-ready solutions on AWS, GCP, or PCF"
                        }
                    ],
                    "core_responsibility": [
                        {
                            "signal": "Build models, simulations, and analytics to support platform enhancements."
                        }
                    ],
                    "nice_to_have": [
                        {"signal": "Build Spark-based data pipelines for large-scale engineering workflows."}
                    ],
                    "informational": [],
                },
                "signals": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    paths.tailoring_step_4_evidence_map_path(
        "Wells Fargo",
        "Senior Software Engineer",
    ).write_text(
        yaml.safe_dump(
            {
                "matches": [
                    {
                        "jd_signal": "2+ years building cloud-ready solutions on AWS, GCP, or PCF",
                        "confidence": "high",
                        "source_excerpt": "Built cloud-ready data services on AWS and production distributed systems at scale.",
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = generate_role_targeted_send_set_drafts(
        connection,
        project_root=project_root,
        job_posting_id="jp_outreach",
        current_time="2026-04-06T20:30:00Z",
        local_timezone=ZoneInfo("UTC"),
    )

    body_text = Path(result.drafted_messages[0].body_text_artifact_path).read_text(encoding="utf-8")
    assert "spark-based data pipelines for large-scale engineering workflows" in body_text.lower()
    assert "models, simulations, and analytics to support platform enhancements" not in body_text

    connection.close()


def test_role_targeted_composition_prefers_cloud_application_work_over_additional_tools_prefix(
    tmp_path: Path,
):
    project_root, paths = bootstrap_project(tmp_path)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    write_sender_profile(paths)
    seed_posting(
        connection,
        company_name="Intel",
        role_title="Cloud Application Development Engineer",
    )
    seed_linked_contact(
        connection,
        contact_id="ct_cloud_apps",
        job_posting_contact_id="jpc_cloud_apps",
        display_name="Ari Manager",
        recipient_type=RECIPIENT_TYPE_HIRING_MANAGER,
        current_working_email="ari@intel.example",
        created_at="2026-04-06T20:01:00Z",
    )
    seed_approved_tailoring_run(
        connection,
        paths,
        company_name="Intel",
        role_title="Cloud Application Development Engineer",
    )
    paths.tailoring_step_3_jd_signals_path(
        "Intel",
        "Cloud Application Development Engineer",
    ).write_text(
        yaml.safe_dump(
            {
                "job_posting_id": "jp_outreach",
                "resume_tailoring_run_id": "rtr_outreach",
                "status": "generated",
                "role_intent_summary": (
                    "Develop cloud and hybrid-cloud applications using frameworks from internal "
                    "and external cloud providers like Amazon Web Services, Google Cloud, and Azure."
                ),
                "signals_by_priority": {
                    "must_have": [
                        {
                            "signal": (
                                "Experience with additional tools such as Databricks, Snowflake, SQL"
                            )
                        }
                    ],
                    "core_responsibility": [
                        {
                            "signal": (
                                "Develop cloud and hybrid-cloud applications using frameworks from internal "
                                "and external cloud providers like Amazon Web Services, Google Cloud, and Azure."
                            )
                        }
                    ],
                    "nice_to_have": [],
                    "informational": [],
                },
                "signals": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = generate_role_targeted_send_set_drafts(
        connection,
        project_root=project_root,
        job_posting_id="jp_outreach",
        current_time="2026-04-06T20:30:00Z",
        local_timezone=ZoneInfo("UTC"),
    )

    body_text = Path(result.drafted_messages[0].body_text_artifact_path).read_text(encoding="utf-8")
    assert "additional tools such as" not in body_text.lower()
    assert "databricks, snowflake, sql" not in body_text.lower()
    assert "public cloud infrastructure" in body_text

    connection.close()


def test_role_targeted_composition_does_not_scramble_cloud_solution_sentence_with_comma_verbs(
    tmp_path: Path,
):
    project_root, paths = bootstrap_project(tmp_path)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    write_sender_profile(paths)
    seed_posting(
        connection,
        company_name="PayPal",
        role_title="Software Engineer",
    )
    seed_linked_contact(
        connection,
        contact_id="ct_paypal_cloud_sentence",
        job_posting_contact_id="jpc_paypal_cloud_sentence",
        display_name="Kumar Manager",
        recipient_type=RECIPIENT_TYPE_HIRING_MANAGER,
        current_working_email="kumar@paypal.example",
        created_at="2026-04-06T20:01:00Z",
    )
    seed_approved_tailoring_run(
        connection,
        paths,
        company_name="PayPal",
        role_title="Software Engineer",
    )
    paths.tailoring_step_3_jd_signals_path(
        "PayPal",
        "Software Engineer",
    ).write_text(
        yaml.safe_dump(
            {
                "job_posting_id": "jp_outreach",
                "resume_tailoring_run_id": "rtr_outreach",
                "status": "generated",
                "role_intent_summary": "Design, develop and deploy scalable software solutions.",
                "signals_by_priority": {
                    "must_have": [
                        {
                            "signal": (
                                "Experience in designing, deploying, and managing scalable cloud "
                                "solutions using AWS, GCP, or Azure platforms (1 year)."
                            )
                        }
                    ],
                    "core_responsibility": [],
                    "nice_to_have": [],
                    "informational": [],
                },
                "signals": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = generate_role_targeted_send_set_drafts(
        connection,
        project_root=project_root,
        job_posting_id="jp_outreach",
        current_time="2026-04-06T20:30:00Z",
        local_timezone=ZoneInfo("UTC"),
    )

    body_text = Path(result.drafted_messages[0].body_text_artifact_path).read_text(encoding="utf-8")
    assert "GCP, Experience in designing" not in body_text
    assert "public cloud infrastructure" in body_text

    connection.close()


def test_role_targeted_composition_prefers_robotics_work_scope_over_full_stack_requirement_prefix(
    tmp_path: Path,
):
    project_root, paths = bootstrap_project(tmp_path)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    write_sender_profile(paths)
    seed_posting(
        connection,
        company_name="Intel",
        role_title="Robotics Software Developer",
    )
    seed_linked_contact(
        connection,
        contact_id="ct_robotics",
        job_posting_contact_id="jpc_robotics",
        display_name="Taylor Manager",
        recipient_type=RECIPIENT_TYPE_HIRING_MANAGER,
        current_working_email="taylor@intel.example",
        created_at="2026-04-06T20:01:00Z",
    )
    seed_approved_tailoring_run(
        connection,
        paths,
        company_name="Intel",
        role_title="Robotics Software Developer",
    )
    paths.tailoring_step_3_jd_signals_path(
        "Intel",
        "Robotics Software Developer",
    ).write_text(
        yaml.safe_dump(
            {
                "job_posting_id": "jp_outreach",
                "resume_tailoring_run_id": "rtr_outreach",
                "status": "generated",
                "role_intent_summary": (
                    "Develop and integrate software solutions for robotic systems within existing "
                    "manufacturing systems to automate processes and tasks within an industrial environment."
                ),
                "signals_by_priority": {
                    "must_have": [
                        {
                            "signal": (
                                "1+ years of experience as a full-stack software developer, developing in "
                                "programming languages such as C/C++/C#, Python, Java, SQL, NoSQL"
                            )
                        }
                    ],
                    "core_responsibility": [
                        {
                            "signal": (
                                "Develop and integrate software solutions for robotic systems within existing "
                                "manufacturing systems to automate processes and tasks within an industrial environment."
                            )
                        },
                        {
                            "signal": (
                                "Writing, testing, and debugging code for robotic applications, including "
                                "motion control, sensor integration, and communication protocols."
                            )
                        },
                    ],
                    "nice_to_have": [],
                    "informational": [],
                },
                "signals": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = generate_role_targeted_send_set_drafts(
        connection,
        project_root=project_root,
        job_posting_id="jp_outreach",
        current_time="2026-04-06T20:30:00Z",
        local_timezone=ZoneInfo("UTC"),
    )

    body_text = Path(result.drafted_messages[0].body_text_artifact_path).read_text(encoding="utf-8")
    assert "full-stack software developer" not in body_text.lower()
    assert "programming languages such as" not in body_text.lower()
    assert "robotic systems" in body_text.lower() or "robotic systems integration" in body_text.lower()
    assert (
        "I see a real overlap with the systems work I've done, and it's the kind of robotics and edge systems work "
        "I want to keep growing in."
        in body_text
    )
    assert "His background is in robotic systems integration" not in body_text

    connection.close()


def test_refresh_role_targeted_generated_drafts_rewrites_pending_unsent_messages(tmp_path: Path):
    project_root, paths = bootstrap_project(tmp_path)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    write_sender_profile(paths)
    seed_posting(
        connection,
        company_name="Acme Platform",
        role_title="Backend Developer",
    )
    seed_linked_contact(
        connection,
        contact_id="ct_refresh",
        job_posting_contact_id="jpc_refresh",
        display_name="Sam Recruiter",
        recipient_type=RECIPIENT_TYPE_RECRUITER,
        current_working_email="sam@acme.example",
        created_at="2026-04-06T20:01:00Z",
    )
    seed_approved_tailoring_run(
        connection,
        paths,
        company_name="Acme Platform",
        role_title="Backend Developer",
    )
    step_3_path = paths.tailoring_step_3_jd_signals_path("Acme Platform", "Backend Developer")
    step_3_path.write_text(
        yaml.safe_dump(
            {
                "job_posting_id": "jp_outreach",
                "resume_tailoring_run_id": "rtr_outreach",
                "status": "generated",
                "role_intent_summary": "Build backend services and application delivery across product teams.",
                "signals_by_priority": {
                    "must_have": [],
                    "core_responsibility": [
                        {"signal": "Build backend services and application delivery across product teams."}
                    ],
                    "nice_to_have": [],
                    "informational": [],
                },
                "signals": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    draft_batch = generate_role_targeted_send_set_drafts(
        connection,
        project_root=project_root,
        job_posting_id="jp_outreach",
        current_time="2026-04-06T20:30:00Z",
        local_timezone=ZoneInfo("UTC"),
    )
    original_message = draft_batch.drafted_messages[0]
    original_body = Path(original_message.body_text_artifact_path).read_text(encoding="utf-8")
    assert "backend APIs and services" in original_body

    step_3_path.write_text(
        yaml.safe_dump(
            {
                "job_posting_id": "jp_outreach",
                "resume_tailoring_run_id": "rtr_outreach",
                "status": "generated",
                "role_intent_summary": (
                    "Build Terraform-based infrastructure provisioning, API gateway build-out, "
                    "and workload identity automation for backend platform workloads."
                ),
                "signals_by_priority": {
                    "must_have": [],
                    "core_responsibility": [
                        {
                            "signal": (
                                "Build Terraform-based infrastructure provisioning, API gateway "
                                "build-out, and workload identity automation for backend platform workloads."
                            )
                        }
                    ],
                    "nice_to_have": [],
                    "informational": [],
                },
                "signals": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    refreshed_ids = refresh_role_targeted_generated_drafts(
        connection,
        project_root=project_root,
        job_posting_id="jp_outreach",
        current_time="2026-04-06T20:40:00Z",
    )

    updated_row = connection.execute(
        """
        SELECT outreach_message_id, message_status, body_text
        FROM outreach_messages
        WHERE outreach_message_id = ?
        """,
        (original_message.outreach_message_id,),
    ).fetchone()
    updated_body = Path(original_message.body_text_artifact_path).read_text(encoding="utf-8")

    assert refreshed_ids == (original_message.outreach_message_id,)
    assert updated_row["outreach_message_id"] == original_message.outreach_message_id
    assert updated_row["message_status"] == MESSAGE_STATUS_GENERATED
    assert "application delivery" not in updated_row["body_text"].lower()
    assert "Terraform-based infrastructure provisioning" in updated_body
    assert "API gateway build-out" in updated_body
    assert "workload identity automation" in updated_body

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
    assert "MS in Computer Science at ASU" not in body_text
    assert "Arizona State University" not in body_text

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


def test_general_learning_send_execution_drafts_sends_and_polls_feedback(tmp_path: Path):
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
            "ct_general_send",
            "sam-learner|acme-robotics",
            "Sam Learner",
            "Acme Robotics",
            "manual_capture",
            "identified",
            "Sam Learner",
            "sam.learner@acme.example",
            "Engineering Manager",
            "2026-04-06T20:00:00Z",
            "2026-04-06T20:00:00Z",
        ),
    )
    connection.commit()

    sender = RecordingOutreachSender()
    observer = ImmediateBounceObserver(event_timestamp="2026-04-06T20:31:00Z")

    result = execute_general_learning_outreach(
        connection,
        project_root=project_root,
        contact_id="ct_general_send",
        current_time="2026-04-06T20:30:00Z",
        sender=sender,
        feedback_observer=observer,
    )

    assert sender.attempted_message_ids == [result.outreach_message_id]
    assert result.drafted_message is not None
    assert result.message_status_after_execution == MESSAGE_STATUS_SENT
    assert result.sent_at == "2026-04-06T20:30:00Z"
    assert result.thread_id == f"thread-{result.outreach_message_id}"
    assert result.delivery_tracking_id == f"delivery-{result.outreach_message_id}"
    assert observer.poll_calls == [
        {
            "message_ids": [result.outreach_message_id],
            "current_time": "2026-04-06T20:30:00Z",
            "observation_scope": OBSERVATION_SCOPE_IMMEDIATE,
        }
    ]

    message_row = connection.execute(
        """
        SELECT outreach_mode, message_status, job_posting_id, sent_at
        FROM outreach_messages
        WHERE outreach_message_id = ?
        """,
        (result.outreach_message_id,),
    ).fetchone()
    assert dict(message_row) == {
        "outreach_mode": "general_learning",
        "message_status": "sent",
        "job_posting_id": None,
        "sent_at": "2026-04-06T20:30:00Z",
    }

    contact_status = connection.execute(
        "SELECT contact_status FROM contacts WHERE contact_id = 'ct_general_send'"
    ).fetchone()[0]
    assert contact_status == CONTACT_STATUS_SENT

    send_result_payload = json.loads(
        Path(result.send_result_artifact_path).read_text(encoding="utf-8")
    )
    assert send_result_payload.get("job_posting_id") is None
    assert send_result_payload["outreach_mode"] == "general_learning"
    assert send_result_payload["send_status"] == MESSAGE_STATUS_SENT
    assert send_result_payload["thread_id"] == f"thread-{result.outreach_message_id}"
    assert send_result_payload["delivery_tracking_id"] == (
        f"delivery-{result.outreach_message_id}"
    )

    feedback_sync_row = connection.execute(
        """
        SELECT scheduler_name, scheduler_type, observation_scope, result
        FROM feedback_sync_runs
        ORDER BY started_at DESC, feedback_sync_run_id DESC
        LIMIT 1
        """
    ).fetchone()
    assert dict(feedback_sync_row) == {
        "scheduler_name": "interactive_post_send",
        "scheduler_type": "interactive",
        "observation_scope": OBSERVATION_SCOPE_IMMEDIATE,
        "result": "success",
    }

    feedback_event_row = connection.execute(
        """
        SELECT event_state, job_posting_id
        FROM delivery_feedback_events
        WHERE outreach_message_id = ?
        ORDER BY event_timestamp DESC, delivery_feedback_event_id DESC
        LIMIT 1
        """,
        (result.outreach_message_id,),
    ).fetchone()
    assert dict(feedback_event_row) == {
        "event_state": "bounced",
        "job_posting_id": None,
    }

    connection.close()


def test_send_execution_persists_sent_metadata_and_delays_remaining_wave(tmp_path: Path):
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
    draft_batch = generate_role_targeted_send_set_drafts(
        connection,
        project_root=project_root,
        job_posting_id="jp_outreach",
        current_time="2026-04-06T20:30:00Z",
        local_timezone=ZoneInfo("UTC"),
    )
    sender = RecordingOutreachSender()

    result = execute_role_targeted_send_set(
        connection,
        project_root=project_root,
        job_posting_id="jp_outreach",
        current_time="2026-04-06T20:40:00Z",
        local_timezone=ZoneInfo("UTC"),
        sender=sender,
    )

    recruiter_message = next(
        message for message in draft_batch.drafted_messages if message.contact_id == "ct_r1"
    )
    assert sender.attempted_message_ids == [recruiter_message.outreach_message_id]
    assert [message.contact_id for message in result.sent_messages] == ["ct_r1"]
    assert [message.contact_id for message in result.delayed_messages] == ["ct_m1", "ct_e1"]
    assert all(
        delayed.pacing_block_reason == "global_inter_send_gap" for delayed in result.delayed_messages
    )
    assert all(
        delayed.earliest_allowed_send_at > "2026-04-06T20:40:00Z" for delayed in result.delayed_messages
    )
    assert result.posting_status_after_execution == JOB_POSTING_STATUS_OUTREACH_IN_PROGRESS

    sent_row = connection.execute(
        """
        SELECT message_status, sent_at, thread_id, delivery_tracking_id
        FROM outreach_messages
        WHERE outreach_message_id = ?
        """,
        (recruiter_message.outreach_message_id,),
    ).fetchone()
    assert dict(sent_row) == {
        "message_status": MESSAGE_STATUS_SENT,
        "sent_at": "2026-04-06T20:40:00Z",
        "thread_id": f"thread-{recruiter_message.outreach_message_id}",
        "delivery_tracking_id": f"delivery-{recruiter_message.outreach_message_id}",
    }

    send_result_payload = json.loads(
        Path(result.sent_messages[0].send_result_artifact_path).read_text(encoding="utf-8")
    )
    assert send_result_payload["send_status"] == MESSAGE_STATUS_SENT
    assert send_result_payload["sent_at"] == "2026-04-06T20:40:00Z"
    assert send_result_payload["thread_id"] == f"thread-{recruiter_message.outreach_message_id}"
    assert send_result_payload["delivery_tracking_id"] == f"delivery-{recruiter_message.outreach_message_id}"

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
            "contact_status": CONTACT_STATUS_SENT,
            "link_level_status": POSTING_CONTACT_STATUS_OUTREACH_DONE,
        },
    ]

    connection.close()


def test_send_execution_runs_immediate_feedback_poll_when_observer_is_provided(tmp_path: Path):
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
    seed_approved_tailoring_run(connection, paths)
    draft_batch = generate_role_targeted_send_set_drafts(
        connection,
        project_root=project_root,
        job_posting_id="jp_outreach",
        current_time="2026-04-06T20:30:00Z",
        local_timezone=ZoneInfo("UTC"),
    )
    observer = ImmediateBounceObserver(event_timestamp="2026-04-06T20:40:30Z")

    result = execute_role_targeted_send_set(
        connection,
        project_root=project_root,
        job_posting_id="jp_outreach",
        current_time="2026-04-06T20:40:00Z",
        local_timezone=ZoneInfo("UTC"),
        sender=RecordingOutreachSender(),
        feedback_observer=observer,
    )

    message_id = draft_batch.drafted_messages[0].outreach_message_id
    assert [message.outreach_message_id for message in result.sent_messages] == [message_id]
    assert observer.poll_calls == [
        {
            "message_ids": [message_id],
            "current_time": "2026-04-06T20:40:00Z",
            "observation_scope": OBSERVATION_SCOPE_IMMEDIATE,
        }
    ]

    feedback_row = connection.execute(
        """
        SELECT event_state, event_timestamp
        FROM delivery_feedback_events
        WHERE outreach_message_id = ?
        """,
        (message_id,),
    ).fetchone()
    assert dict(feedback_row) == {
        "event_state": "bounced",
        "event_timestamp": "2026-04-06T20:40:30Z",
    }

    sync_row = connection.execute(
        """
        SELECT scheduler_name, scheduler_type, observation_scope, result
        FROM feedback_sync_runs
        """
    ).fetchone()
    assert dict(sync_row) == {
        "scheduler_name": "interactive_post_send",
        "scheduler_type": "interactive",
        "observation_scope": OBSERVATION_SCOPE_IMMEDIATE,
        "result": "success",
    }

    latest_feedback_payload = json.loads(
        paths.outreach_latest_delivery_outcome_path(
            "Acme Robotics",
            "Staff Software Engineer / AI",
        ).read_text(encoding="utf-8")
    )
    assert latest_feedback_payload["outreach_message_id"] == message_id
    assert latest_feedback_payload["event_state"] == "bounced"
    assert latest_feedback_payload["matched_by"] == "delivery_tracking_id"

    connection.close()


def test_send_execution_keeps_successful_send_when_immediate_feedback_poll_fails(tmp_path: Path):
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
    seed_approved_tailoring_run(connection, paths)
    draft_batch = generate_role_targeted_send_set_drafts(
        connection,
        project_root=project_root,
        job_posting_id="jp_outreach",
        current_time="2026-04-06T20:30:00Z",
        local_timezone=ZoneInfo("UTC"),
    )
    observer = TimeoutFeedbackObserver()

    result = execute_role_targeted_send_set(
        connection,
        project_root=project_root,
        job_posting_id="jp_outreach",
        current_time="2026-04-06T20:40:00Z",
        local_timezone=ZoneInfo("UTC"),
        sender=RecordingOutreachSender(),
        feedback_observer=observer,
    )

    message_id = draft_batch.drafted_messages[0].outreach_message_id
    message_row = connection.execute(
        """
        SELECT message_status, sent_at
        FROM outreach_messages
        WHERE outreach_message_id = ?
        """,
        (message_id,),
    ).fetchone()
    feedback_sync_row = connection.execute(
        """
        SELECT scheduler_name, scheduler_type, observation_scope, result, error_message
        FROM feedback_sync_runs
        ORDER BY started_at DESC, feedback_sync_run_id DESC
        LIMIT 1
        """
    ).fetchone()
    feedback_event_count = connection.execute(
        """
        SELECT COUNT(*)
        FROM delivery_feedback_events
        WHERE outreach_message_id = ?
        """,
        (message_id,),
    ).fetchone()[0]

    assert [message.outreach_message_id for message in result.sent_messages] == [message_id]
    assert result.blocked_messages == ()
    assert result.failed_messages == ()
    assert dict(message_row) == {
        "message_status": MESSAGE_STATUS_SENT,
        "sent_at": "2026-04-06T20:40:00Z",
    }
    assert dict(feedback_sync_row) == {
        "scheduler_name": "interactive_post_send",
        "scheduler_type": "interactive",
        "observation_scope": OBSERVATION_SCOPE_IMMEDIATE,
        "result": "failed",
        "error_message": "Synthetic mailbox timeout",
    }
    assert feedback_event_count == 0
    assert observer.poll_calls == [
        {
            "message_ids": [message_id],
            "current_time": "2026-04-06T20:40:00Z",
            "observation_scope": OBSERVATION_SCOPE_IMMEDIATE,
        }
    ]

    connection.close()


def test_send_execution_completes_posting_when_last_message_is_sent(tmp_path: Path):
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
    seed_approved_tailoring_run(connection, paths)
    generate_role_targeted_send_set_drafts(
        connection,
        project_root=project_root,
        job_posting_id="jp_outreach",
        current_time="2026-04-06T20:30:00Z",
        local_timezone=ZoneInfo("UTC"),
    )

    result = execute_role_targeted_send_set(
        connection,
        project_root=project_root,
        job_posting_id="jp_outreach",
        current_time="2026-04-06T20:50:00Z",
        local_timezone=ZoneInfo("UTC"),
        sender=RecordingOutreachSender(),
    )

    assert [message.contact_id for message in result.sent_messages] == ["ct_r1"]
    assert result.blocked_messages == ()
    assert result.failed_messages == ()
    assert result.delayed_messages == ()
    assert result.posting_status_after_execution == JOB_POSTING_STATUS_COMPLETED

    posting_status = connection.execute(
        "SELECT posting_status FROM job_postings WHERE job_posting_id = ?",
        ("jp_outreach",),
    ).fetchone()[0]
    assert posting_status == JOB_POSTING_STATUS_COMPLETED

    connection.close()


def test_send_execution_keeps_posting_ready_for_later_waves_when_untouched_contacts_remain(
    tmp_path: Path,
):
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
    seed_linked_contact(
        connection,
        contact_id="ct_a1",
        job_posting_contact_id="jpc_a1",
        display_name="Alex Alumni",
        recipient_type=RECIPIENT_TYPE_ALUMNI,
        current_working_email="alex@acme.example",
        created_at="2026-04-06T20:04:00Z",
    )
    seed_approved_tailoring_run(connection, paths)
    draft_batch = generate_role_targeted_send_set_drafts(
        connection,
        project_root=project_root,
        job_posting_id="jp_outreach",
        current_time="2026-04-06T20:30:00Z",
        local_timezone=ZoneInfo("UTC"),
    )
    drafted_ids_by_contact = {
        message.contact_id: message.outreach_message_id for message in draft_batch.drafted_messages
    }
    connection.execute(
        """
        UPDATE outreach_messages
        SET message_status = ?, sent_at = ?, thread_id = ?, delivery_tracking_id = ?, updated_at = ?
        WHERE outreach_message_id IN (?, ?)
        """,
        (
            MESSAGE_STATUS_SENT,
            "2026-04-06T20:35:00Z",
            "thread-preseeded",
            "delivery-preseeded",
            "2026-04-06T20:35:00Z",
            drafted_ids_by_contact["ct_m1"],
            drafted_ids_by_contact["ct_e1"],
        ),
    )
    connection.execute(
        """
        UPDATE contacts
        SET contact_status = ?, updated_at = ?
        WHERE contact_id IN (?, ?)
        """,
        (
            CONTACT_STATUS_SENT,
            "2026-04-06T20:35:00Z",
            "ct_m1",
            "ct_e1",
        ),
    )
    connection.execute(
        """
        UPDATE job_posting_contacts
        SET link_level_status = ?, updated_at = ?
        WHERE job_posting_contact_id IN (?, ?)
        """,
        (
            POSTING_CONTACT_STATUS_OUTREACH_DONE,
            "2026-04-06T20:35:00Z",
            "jpc_m1",
            "jpc_e1",
        ),
    )
    connection.commit()

    result = execute_role_targeted_send_set(
        connection,
        project_root=project_root,
        job_posting_id="jp_outreach",
        current_time="2026-04-06T20:50:00Z",
        local_timezone=ZoneInfo("UTC"),
        sender=RecordingOutreachSender(),
    )

    posting_status = connection.execute(
        "SELECT posting_status FROM job_postings WHERE job_posting_id = ?",
        ("jp_outreach",),
    ).fetchone()[0]
    next_wave_plan = evaluate_role_targeted_send_set(
        connection,
        job_posting_id="jp_outreach",
        current_time="2026-04-06T20:50:00Z",
        local_timezone=ZoneInfo("UTC"),
    )

    assert [message.contact_id for message in result.sent_messages] == ["ct_r1"]
    assert [message.contact_id for message in result.delayed_messages] == ["ct_a1"]
    assert result.delayed_messages[0].pacing_block_reason == "global_inter_send_gap"
    assert result.posting_status_after_execution == JOB_POSTING_STATUS_OUTREACH_IN_PROGRESS
    assert posting_status == JOB_POSTING_STATUS_OUTREACH_IN_PROGRESS
    assert next_wave_plan.selected_contacts == ()
    assert next_wave_plan.ready_for_outreach is False

    connection.close()


def test_send_execution_returns_posting_to_requires_contacts_when_later_wave_needs_email(
    tmp_path: Path,
):
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
    seed_linked_contact(
        connection,
        contact_id="ct_a1",
        job_posting_contact_id="jpc_a1",
        display_name="Alex Alumni",
        recipient_type=RECIPIENT_TYPE_ALUMNI,
        current_working_email=None,
        created_at="2026-04-06T20:04:00Z",
    )
    seed_approved_tailoring_run(connection, paths)
    draft_batch = generate_role_targeted_send_set_drafts(
        connection,
        project_root=project_root,
        job_posting_id="jp_outreach",
        current_time="2026-04-06T20:30:00Z",
        local_timezone=ZoneInfo("UTC"),
    )
    drafted_ids_by_contact = {
        message.contact_id: message.outreach_message_id for message in draft_batch.drafted_messages
    }
    connection.execute(
        """
        UPDATE outreach_messages
        SET message_status = ?, sent_at = ?, thread_id = ?, delivery_tracking_id = ?, updated_at = ?
        WHERE outreach_message_id IN (?, ?)
        """,
        (
            MESSAGE_STATUS_SENT,
            "2026-04-06T20:35:00Z",
            "thread-preseeded",
            "delivery-preseeded",
            "2026-04-06T20:35:00Z",
            drafted_ids_by_contact["ct_m1"],
            drafted_ids_by_contact["ct_e1"],
        ),
    )
    connection.execute(
        """
        UPDATE contacts
        SET contact_status = ?, updated_at = ?
        WHERE contact_id IN (?, ?)
        """,
        (
            CONTACT_STATUS_SENT,
            "2026-04-06T20:35:00Z",
            "ct_m1",
            "ct_e1",
        ),
    )
    connection.execute(
        """
        UPDATE job_posting_contacts
        SET link_level_status = ?, updated_at = ?
        WHERE job_posting_contact_id IN (?, ?)
        """,
        (
            POSTING_CONTACT_STATUS_OUTREACH_DONE,
            "2026-04-06T20:35:00Z",
            "jpc_m1",
            "jpc_e1",
        ),
    )
    connection.commit()

    result = execute_role_targeted_send_set(
        connection,
        project_root=project_root,
        job_posting_id="jp_outreach",
        current_time="2026-04-06T20:50:00Z",
        local_timezone=ZoneInfo("UTC"),
        sender=RecordingOutreachSender(),
    )

    posting_status = connection.execute(
        "SELECT posting_status FROM job_postings WHERE job_posting_id = ?",
        ("jp_outreach",),
    ).fetchone()[0]
    next_wave_plan = evaluate_role_targeted_send_set(
        connection,
        job_posting_id="jp_outreach",
        current_time="2026-04-06T20:50:00Z",
        local_timezone=ZoneInfo("UTC"),
    )

    assert [message.contact_id for message in result.sent_messages] == ["ct_r1"]
    assert result.posting_status_after_execution == JOB_POSTING_STATUS_REQUIRES_CONTACTS
    assert posting_status == JOB_POSTING_STATUS_REQUIRES_CONTACTS
    assert [contact.contact_id for contact in next_wave_plan.selected_contacts] == ["ct_a1"]
    assert next_wave_plan.ready_for_outreach is False

    connection.close()


def test_send_execution_blocks_repeat_outreach_without_resend(tmp_path: Path):
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
    seed_approved_tailoring_run(connection, paths)
    draft_batch = generate_role_targeted_send_set_drafts(
        connection,
        project_root=project_root,
        job_posting_id="jp_outreach",
        current_time="2026-04-06T20:30:00Z",
        local_timezone=ZoneInfo("UTC"),
    )
    current_message = draft_batch.drafted_messages[0]
    seed_sent_message(
        connection,
        outreach_message_id="msg_previous",
        contact_id="ct_r1",
        recipient_email="priya@acme.example",
        job_posting_contact_id="jpc_r1",
        sent_at="2026-04-05T18:00:00Z",
    )
    sender = RecordingOutreachSender()

    result = execute_role_targeted_send_set(
        connection,
        project_root=project_root,
        job_posting_id="jp_outreach",
        current_time="2026-04-06T20:40:00Z",
        local_timezone=ZoneInfo("UTC"),
        sender=sender,
    )

    assert sender.attempted_message_ids == []
    assert result.sent_messages == ()
    assert result.failed_messages == ()
    assert [issue.outreach_message_id for issue in result.blocked_messages] == [
        current_message.outreach_message_id
    ]
    assert result.blocked_messages[0].reason_code == "repeat_outreach_review_required"
    assert result.posting_status_after_execution == JOB_POSTING_STATUS_COMPLETED

    blocked_row = connection.execute(
        """
        SELECT message_status
        FROM outreach_messages
        WHERE outreach_message_id = ?
        """,
        (current_message.outreach_message_id,),
    ).fetchone()
    assert blocked_row["message_status"] == MESSAGE_STATUS_BLOCKED

    link_row = connection.execute(
        """
        SELECT link_level_status
        FROM job_posting_contacts
        WHERE job_posting_contact_id = ?
        """,
        ("jpc_r1",),
    ).fetchone()
    assert link_row["link_level_status"] == POSTING_CONTACT_STATUS_EXHAUSTED

    send_result_payload = json.loads(
        Path(current_message.send_result_artifact_path).read_text(encoding="utf-8")
    )
    assert send_result_payload["result"] == "blocked"
    assert send_result_payload["send_status"] == MESSAGE_STATUS_BLOCKED
    assert send_result_payload["reason_code"] == "repeat_outreach_review_required"

    connection.close()


def test_send_execution_blocks_transient_gmail_failure_and_retries_same_message_after_cooldown(
    tmp_path: Path,
):
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
    seed_approved_tailoring_run(connection, paths)
    draft_batch = generate_role_targeted_send_set_drafts(
        connection,
        project_root=project_root,
        job_posting_id="jp_outreach",
        current_time="2026-04-06T20:30:00Z",
        local_timezone=ZoneInfo("UTC"),
    )
    message_id = draft_batch.drafted_messages[0].outreach_message_id
    sender = SequencedOutreachSender(
        {
            message_id: [
                SendAttemptOutcome(
                    outcome="failed",
                    reason_code="gmail_send_failed",
                    message=(
                        "HTTPSConnectionPool(host='oauth2.googleapis.com', port=443): "
                        "Max retries exceeded with url: /token "
                        "(Caused by NameResolutionError(\"Failed to resolve "
                        "'oauth2.googleapis.com'\"))"
                    ),
                ),
                SendAttemptOutcome(
                    outcome="sent",
                    thread_id="thread-retried",
                    delivery_tracking_id="delivery-retried",
                ),
            ]
        }
    )

    first_result = execute_role_targeted_send_set(
        connection,
        project_root=project_root,
        job_posting_id="jp_outreach",
        current_time="2026-04-06T20:40:00Z",
        local_timezone=ZoneInfo("UTC"),
        sender=sender,
    )

    blocked_row = connection.execute(
        """
        SELECT message_status, sent_at, thread_id, delivery_tracking_id
        FROM outreach_messages
        WHERE outreach_message_id = ?
        """,
        (message_id,),
    ).fetchone()
    blocked_payload = json.loads(
        paths.outreach_message_send_result_path(
            "Acme Robotics",
            "Staff Software Engineer / AI",
            message_id,
        ).read_text(encoding="utf-8")
    )

    assert first_result.sent_messages == ()
    assert first_result.failed_messages == ()
    assert [issue.outreach_message_id for issue in first_result.blocked_messages] == [message_id]
    assert [message.outreach_message_id for message in first_result.delayed_messages] == [message_id]
    assert first_result.delayed_messages[0].pacing_block_reason == "transient_send_retry_cooldown"
    assert first_result.posting_status_after_execution == JOB_POSTING_STATUS_OUTREACH_IN_PROGRESS
    assert dict(blocked_row) == {
        "message_status": MESSAGE_STATUS_BLOCKED,
        "sent_at": None,
        "thread_id": None,
        "delivery_tracking_id": None,
    }
    assert blocked_payload["result"] == "blocked"
    assert blocked_payload["send_status"] == MESSAGE_STATUS_BLOCKED
    assert blocked_payload["reason_code"] == "gmail_send_failed"
    assert is_role_targeted_sending_actionable_now(
        connection,
        project_root=project_root,
        job_posting_id="jp_outreach",
        current_time="2026-04-06T20:50:00Z",
        local_timezone=ZoneInfo("UTC"),
    ) is False
    assert is_role_targeted_sending_actionable_now(
        connection,
        project_root=project_root,
        job_posting_id="jp_outreach",
        current_time="2026-04-06T20:56:00Z",
        local_timezone=ZoneInfo("UTC"),
    ) is True

    second_result = execute_role_targeted_send_set(
        connection,
        project_root=project_root,
        job_posting_id="jp_outreach",
        current_time="2026-04-06T20:56:00Z",
        local_timezone=ZoneInfo("UTC"),
        sender=sender,
    )

    sent_row = connection.execute(
        """
        SELECT message_status, sent_at, thread_id, delivery_tracking_id
        FROM outreach_messages
        WHERE outreach_message_id = ?
        """,
        (message_id,),
    ).fetchone()
    assert [message.outreach_message_id for message in second_result.sent_messages] == [message_id]
    assert second_result.blocked_messages == ()
    assert second_result.failed_messages == ()
    assert second_result.posting_status_after_execution == JOB_POSTING_STATUS_COMPLETED
    assert dict(sent_row) == {
        "message_status": MESSAGE_STATUS_SENT,
        "sent_at": "2026-04-06T20:56:00Z",
        "thread_id": "thread-retried",
        "delivery_tracking_id": "delivery-retried",
    }

    connection.close()


def test_transient_send_retry_exhaustion_leaves_message_blocked_and_not_actionable(
    tmp_path: Path,
):
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
    seed_approved_tailoring_run(connection, paths)
    draft_batch = generate_role_targeted_send_set_drafts(
        connection,
        project_root=project_root,
        job_posting_id="jp_outreach",
        current_time="2026-04-06T20:30:00Z",
        local_timezone=ZoneInfo("UTC"),
    )
    message_id = draft_batch.drafted_messages[0].outreach_message_id
    transient_failure = SendAttemptOutcome(
        outcome="failed",
        reason_code="gmail_send_failed",
        message=(
            "HTTPSConnectionPool(host='oauth2.googleapis.com', port=443): "
            "Max retries exceeded with url: /token "
            "(Caused by NameResolutionError(\"Failed to resolve "
            "'oauth2.googleapis.com'\"))"
        ),
    )
    sender = SequencedOutreachSender(
        {message_id: [transient_failure, transient_failure, transient_failure, transient_failure]}
    )

    for current_time in (
        "2026-04-06T20:40:00Z",
        "2026-04-06T20:56:00Z",
        "2026-04-06T21:12:00Z",
        "2026-04-06T21:28:00Z",
    ):
        result = execute_role_targeted_send_set(
            connection,
            project_root=project_root,
            job_posting_id="jp_outreach",
            current_time=current_time,
            local_timezone=ZoneInfo("UTC"),
            sender=sender,
        )
        assert result.sent_messages == ()
        assert result.failed_messages == ()
        assert [issue.outreach_message_id for issue in result.blocked_messages] == [message_id]

    blocked_row = connection.execute(
        """
        SELECT message_status
        FROM outreach_messages
        WHERE outreach_message_id = ?
        """,
        (message_id,),
    ).fetchone()
    assert blocked_row["message_status"] == MESSAGE_STATUS_BLOCKED
    assert is_role_targeted_sending_actionable_now(
        connection,
        project_root=project_root,
        job_posting_id="jp_outreach",
        current_time="2026-04-06T21:44:00Z",
        local_timezone=ZoneInfo("UTC"),
    ) is False

    connection.close()


def test_cleared_ambiguous_blocked_send_retries_successfully(
    tmp_path: Path,
):
    project_root, paths = bootstrap_project(tmp_path)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    write_sender_profile(paths)
    seed_posting(connection)
    seed_linked_contact(
        connection,
        contact_id="ct_primary",
        job_posting_contact_id="jpc_primary",
        display_name="Priya Recruiter",
        recipient_type=RECIPIENT_TYPE_RECRUITER,
        current_working_email="priya@acme.example",
        created_at="2026-04-06T20:01:00Z",
    )
    seed_approved_tailoring_run(connection, paths)
    draft_batch = generate_role_targeted_send_set_drafts(
        connection,
        project_root=project_root,
        job_posting_id="jp_outreach",
        current_time="2026-04-06T20:30:00Z",
        local_timezone=ZoneInfo("UTC"),
    )
    message_id = draft_batch.drafted_messages[0].outreach_message_id
    sender = SequencedOutreachSender(
        {
            message_id: [
                SendAttemptOutcome(
                    outcome="sent",
                    thread_id="thread-recovered",
                    delivery_tracking_id="delivery-recovered",
                )
            ]
        }
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
            "ld_duplicate",
            "ld_duplicate|acme-robotics|older-role",
            "handed_off",
            "posting_only",
            "not_applicable",
            "gmail_job_alert",
            "gmail/message/456",
            "gmail_job_alert",
            "https://careers.acme.example/jobs/456",
            "Acme Robotics",
            "Earlier Role",
            "2026-04-06T20:00:30Z",
            "2026-04-06T20:00:30Z",
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
            "jp_duplicate",
            "ld_duplicate",
            "acme-robotics|earlier-role",
            "Acme Robotics",
            "Earlier Role",
            JOB_POSTING_STATUS_OUTREACH_IN_PROGRESS,
            "2026-04-06T20:00:30Z",
            "2026-04-06T20:00:30Z",
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
            "jpc_duplicate",
            "jp_duplicate",
            "ct_primary",
            RECIPIENT_TYPE_RECRUITER,
            "Earlier outreach wave still active.",
            POSTING_CONTACT_STATUS_OUTREACH_IN_PROGRESS,
            "2026-04-06T20:31:00Z",
            "2026-04-06T20:31:00Z",
        ),
    )
    connection.execute(
        """
        INSERT INTO outreach_messages (
          outreach_message_id, contact_id, outreach_mode, recipient_email, message_status,
          job_posting_id, job_posting_contact_id, subject, body_text, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "msg_duplicate",
            "ct_primary",
            "role_targeted",
            "priya@acme.example",
            MESSAGE_STATUS_GENERATED,
            "jp_duplicate",
            "jpc_duplicate",
            "Earlier outreach",
            "Earlier outreach body",
            "2026-04-06T20:31:00Z",
            "2026-04-06T20:31:00Z",
        ),
    )
    connection.commit()

    first_result = execute_role_targeted_send_set(
        connection,
        project_root=project_root,
        job_posting_id="jp_outreach",
        current_time="2026-04-06T20:40:00Z",
        local_timezone=ZoneInfo("UTC"),
        sender=sender,
    )

    blocked_payload = json.loads(
        paths.outreach_message_send_result_path(
            "Acme Robotics",
            "Staff Software Engineer / AI",
            message_id,
        ).read_text(encoding="utf-8")
    )
    blocked_row = connection.execute(
        """
        SELECT message_status
        FROM outreach_messages
        WHERE outreach_message_id = ?
        """,
        (message_id,),
    ).fetchone()
    assert [issue.outreach_message_id for issue in first_result.blocked_messages] == [message_id]
    assert blocked_row["message_status"] == MESSAGE_STATUS_BLOCKED
    assert blocked_payload["reason_code"] == "ambiguous_send_state"

    connection.execute(
        """
        UPDATE outreach_messages
        SET message_status = ?, updated_at = ?
        WHERE outreach_message_id = ?
        """,
        (
            MESSAGE_STATUS_FAILED,
            "2026-04-06T20:50:00Z",
            "msg_duplicate",
        ),
    )
    connection.commit()

    second_result = execute_role_targeted_send_set(
        connection,
        project_root=project_root,
        job_posting_id="jp_outreach",
        current_time="2026-04-06T20:55:00Z",
        local_timezone=ZoneInfo("UTC"),
        sender=sender,
    )

    sent_row = connection.execute(
        """
        SELECT message_status, sent_at, thread_id, delivery_tracking_id
        FROM outreach_messages
        WHERE outreach_message_id = ?
        """,
        (message_id,),
    ).fetchone()
    assert [message.outreach_message_id for message in second_result.sent_messages] == [message_id]
    assert second_result.blocked_messages == ()
    assert second_result.failed_messages == ()
    assert dict(sent_row) == {
        "message_status": MESSAGE_STATUS_SENT,
        "sent_at": "2026-04-06T20:55:00Z",
        "thread_id": "thread-recovered",
        "delivery_tracking_id": "delivery-recovered",
    }

    connection.close()
