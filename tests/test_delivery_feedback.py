from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from job_hunt_copilot.bootstrap import run_bootstrap
from job_hunt_copilot.delivery_feedback import (
    DELIVERY_OUTCOME_ARTIFACT_TYPE,
    EVENT_STATE_BOUNCED,
    EVENT_STATE_NOT_BOUNCED,
    EVENT_STATE_REPLIED,
    OBSERVATION_SCOPE_DELAYED,
    DeliveryFeedbackSignal,
    GmailMailboxFeedbackObserver,
    ObservedOutreachMessage,
    sync_delivery_feedback,
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
    lead_id: str = "ld_feedback",
    job_posting_id: str = "jp_feedback",
    company_name: str = "Acme Robotics",
    role_title: str = "Staff Software Engineer / AI",
    created_at: str = "2026-04-07T10:00:00Z",
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
            "gmail/message/feedback",
            "gmail_job_alert",
            "https://careers.acme.example/jobs/feedback",
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
            "completed",
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
    display_name: str,
    recipient_email: str,
    recipient_type: str = "recruiter",
    job_posting_id: str = "jp_feedback",
    company_name: str = "Acme Robotics",
    created_at: str = "2026-04-07T10:01:00Z",
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
            "sent",
            display_name,
            recipient_email,
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
            "Feedback test linkage.",
            "outreach_done",
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
    sent_at: str,
    thread_id: str | None = None,
    delivery_tracking_id: str | None = None,
    job_posting_id: str = "jp_feedback",
    job_posting_contact_id: str | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO outreach_messages (
          outreach_message_id, contact_id, outreach_mode, recipient_email, message_status,
          job_posting_id, job_posting_contact_id, subject, body_text, thread_id,
          delivery_tracking_id, sent_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            outreach_message_id,
            contact_id,
            "role_targeted",
            recipient_email,
            "sent",
            job_posting_id,
            job_posting_contact_id,
            "Hello",
            "Body",
            thread_id,
            delivery_tracking_id,
            sent_at,
            sent_at,
            sent_at,
        ),
    )
    connection.commit()


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


def test_gmail_mailbox_feedback_observer_detects_real_bounce_formats(tmp_path: Path):
    project_root, paths = bootstrap_project(tmp_path)

    def gmail_api_body(text: str) -> str:
        import base64

        return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")

    bounce_payload = {
        "id": "gmail-bounce-001",
        "threadId": "thread-bounce-001",
        "internalDate": "1775923668000",
        "payload": {
            "headers": [
                {"name": "From", "value": "Mail Delivery Subsystem <mailer-daemon@googlemail.com>"},
                {"name": "To", "value": "asonti1@asu.edu"},
                {"name": "Subject", "value": "Delivery Status Notification (Failure)"},
                {"name": "Date", "value": "Sat, 11 Apr 2026 11:47:48 -0700 (PDT)"},
            ],
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {
                        "data": gmail_api_body(
                            "** Address not found **\n\n"
                            "Your message wasn't delivered to brittany.grey@addisongroup.com because the address couldn't be found.\n\n"
                            "Final-Recipient: rfc822; brittany.grey@addisongroup.com\n"
                            "Action: failed\n"
                            "Status: 5.4.1\n"
                        )
                    },
                }
            ],
        },
    }

    class FakeRequest:
        def __init__(self, payload):  # type: ignore[no-untyped-def]
            self._payload = payload

        def execute(self):  # type: ignore[no-untyped-def]
            return self._payload

    class FakeMessagesResource:
        def list(self, **kwargs):  # type: ignore[no-untyped-def]
            return FakeRequest({"messages": [{"id": "gmail-bounce-001"}]})

        def get(self, **kwargs):  # type: ignore[no-untyped-def]
            return FakeRequest(bounce_payload)

    class FakeUsersResource:
        def messages(self):  # type: ignore[no-untyped-def]
            return FakeMessagesResource()

    class FakeGmailService:
        def users(self):  # type: ignore[no-untyped-def]
            return FakeUsersResource()

    observer = GmailMailboxFeedbackObserver(
        paths,
        service_factory=FakeGmailService,
    )

    signals = observer.poll(
        (
            ObservedOutreachMessage(
                outreach_message_id="msg_feedback",
                contact_id="ct_feedback",
                job_posting_id="jp_feedback",
                lead_id="ld_feedback",
                outreach_mode="role_targeted",
                recipient_email="brittany.grey@addisongroup.com",
                thread_id="outbound-thread-001",
                delivery_tracking_id="outbound-msg-001",
                sent_at="2026-04-11T18:47:44Z",
                company_name="Addison Group",
                role_title="Software Engineer",
                bounce_observation_ends_at="2026-04-11T19:17:44Z",
                has_bounced=False,
                has_not_bounced=False,
                has_replied=False,
            ),
        ),
        current_time="2026-04-11T18:59:39Z",
        observation_scope=OBSERVATION_SCOPE_DELAYED,
    )

    assert len(signals) == 1
    signal = signals[0]
    assert signal.signal_type == EVENT_STATE_BOUNCED
    assert signal.recipient_email == "brittany.grey@addisongroup.com"
    assert signal.provider_message_id == "gmail-bounce-001"


def test_sync_delivery_feedback_persists_bounce_and_reply_events(tmp_path: Path):
    project_root, paths = bootstrap_project(tmp_path)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_posting(connection)
    seed_linked_contact(
        connection,
        contact_id="ct_bounced",
        job_posting_contact_id="jpc_bounced",
        display_name="Priya Recruiter",
        recipient_email="priya@acme.example",
    )
    seed_linked_contact(
        connection,
        contact_id="ct_replied",
        job_posting_contact_id="jpc_replied",
        display_name="Morgan Manager",
        recipient_email="morgan@acme.example",
        recipient_type="hiring_manager",
        created_at="2026-04-07T10:02:00Z",
    )
    seed_sent_message(
        connection,
        outreach_message_id="msg_bounced",
        contact_id="ct_bounced",
        recipient_email="priya@acme.example",
        thread_id="thread-msg_bounced",
        delivery_tracking_id="delivery-msg_bounced",
        sent_at="2026-04-07T10:03:00Z",
        job_posting_contact_id="jpc_bounced",
    )
    seed_sent_message(
        connection,
        outreach_message_id="msg_replied",
        contact_id="ct_replied",
        recipient_email="morgan@acme.example",
        thread_id="thread-msg_replied",
        delivery_tracking_id="delivery-msg_replied",
        sent_at="2026-04-07T10:04:00Z",
        job_posting_contact_id="jpc_replied",
    )

    observer = FakeMailboxFeedbackObserver(
        signals=[
            DeliveryFeedbackSignal(
                signal_type=EVENT_STATE_BOUNCED,
                event_timestamp="2026-04-07T10:05:00Z",
                delivery_tracking_id="delivery-msg_bounced",
            ),
            DeliveryFeedbackSignal(
                signal_type=EVENT_STATE_REPLIED,
                event_timestamp="2026-04-07T10:06:00Z",
                thread_id="thread-msg_replied",
                reply_summary="Happy to connect.",
                raw_reply_excerpt="Happy to connect next week.",
            ),
        ]
    )

    result = sync_delivery_feedback(
        connection,
        project_root=project_root,
        current_time="2026-04-07T10:10:00Z",
        scheduler_name="job-hunt-copilot-feedback-sync",
        scheduler_type="launchd",
        observation_scope=OBSERVATION_SCOPE_DELAYED,
        observer=observer,
    )

    assert observer.poll_calls == [
        {
            "message_ids": ["msg_replied", "msg_bounced"],
            "current_time": "2026-04-07T10:10:00Z",
            "observation_scope": OBSERVATION_SCOPE_DELAYED,
        }
    ]
    assert result.messages_examined == 2
    assert result.bounce_events_written == 1
    assert result.reply_events_written == 1
    assert result.not_bounced_events_written == 0
    assert {event.event_state for event in result.persisted_events} == {
        EVENT_STATE_BOUNCED,
        EVENT_STATE_REPLIED,
    }

    event_rows = connection.execute(
        """
        SELECT outreach_message_id, event_state, event_timestamp, reply_summary, raw_reply_excerpt
        FROM delivery_feedback_events
        ORDER BY event_timestamp ASC, outreach_message_id ASC
        """
    ).fetchall()
    assert [dict(row) for row in event_rows] == [
        {
            "outreach_message_id": "msg_bounced",
            "event_state": EVENT_STATE_BOUNCED,
            "event_timestamp": "2026-04-07T10:05:00Z",
            "reply_summary": None,
            "raw_reply_excerpt": None,
        },
        {
            "outreach_message_id": "msg_replied",
            "event_state": EVENT_STATE_REPLIED,
            "event_timestamp": "2026-04-07T10:06:00Z",
            "reply_summary": "Happy to connect.",
            "raw_reply_excerpt": "Happy to connect next week.",
        },
    ]

    sync_row = connection.execute(
        """
        SELECT scheduler_name, scheduler_type, result, messages_examined,
               bounce_events_written, reply_events_written
        FROM feedback_sync_runs
        WHERE feedback_sync_run_id = ?
        """,
        (result.feedback_sync_run_id,),
    ).fetchone()
    assert dict(sync_row) == {
        "scheduler_name": "job-hunt-copilot-feedback-sync",
        "scheduler_type": "launchd",
        "result": "success",
        "messages_examined": 2,
        "bounce_events_written": 1,
        "reply_events_written": 1,
    }

    artifact_count = connection.execute(
        "SELECT COUNT(*) FROM artifact_records WHERE artifact_type = ?",
        (DELIVERY_OUTCOME_ARTIFACT_TYPE,),
    ).fetchone()[0]
    assert artifact_count == 2
    for event in result.persisted_events:
        assert Path(event.artifact_path).exists()

    latest_payload = json.loads(
        paths.outreach_latest_delivery_outcome_path(
            "Acme Robotics",
            "Staff Software Engineer / AI",
        ).read_text(encoding="utf-8")
    )
    assert latest_payload["outreach_message_id"] == "msg_replied"
    assert latest_payload["event_state"] == EVENT_STATE_REPLIED
    assert latest_payload["matched_by"] == "thread_id"

    connection.close()


def test_sync_delivery_feedback_records_not_bounced_when_window_closes(tmp_path: Path):
    project_root, paths = bootstrap_project(tmp_path)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_posting(connection)
    seed_linked_contact(
        connection,
        contact_id="ct_not_bounced",
        job_posting_contact_id="jpc_not_bounced",
        display_name="Jamie Engineer",
        recipient_email="jamie@acme.example",
        recipient_type="engineer",
    )
    seed_sent_message(
        connection,
        outreach_message_id="msg_not_bounced",
        contact_id="ct_not_bounced",
        recipient_email="jamie@acme.example",
        thread_id="thread-msg_not_bounced",
        delivery_tracking_id="delivery-msg_not_bounced",
        sent_at="2026-04-07T10:00:00Z",
        job_posting_contact_id="jpc_not_bounced",
    )

    result = sync_delivery_feedback(
        connection,
        project_root=project_root,
        current_time="2026-04-07T10:40:00Z",
        scheduler_name="job-hunt-copilot-feedback-sync",
        scheduler_type="launchd",
        observer=FakeMailboxFeedbackObserver(signals=[]),
    )

    assert result.messages_examined == 1
    assert result.bounce_events_written == 0
    assert result.reply_events_written == 0
    assert result.not_bounced_events_written == 1
    assert [event.event_state for event in result.persisted_events] == [EVENT_STATE_NOT_BOUNCED]
    assert result.persisted_events[0].event_timestamp == "2026-04-07T10:30:00Z"

    stored_event = connection.execute(
        """
        SELECT event_state, event_timestamp
        FROM delivery_feedback_events
        WHERE outreach_message_id = ?
        """,
        ("msg_not_bounced",),
    ).fetchone()
    assert dict(stored_event) == {
        "event_state": EVENT_STATE_NOT_BOUNCED,
        "event_timestamp": "2026-04-07T10:30:00Z",
    }

    latest_payload = json.loads(
        paths.outreach_latest_delivery_outcome_path(
            "Acme Robotics",
            "Staff Software Engineer / AI",
        ).read_text(encoding="utf-8")
    )
    assert latest_payload["event_state"] == EVENT_STATE_NOT_BOUNCED
    assert latest_payload["event_timestamp"] == "2026-04-07T10:30:00Z"
    assert latest_payload["matched_by"] == "observation_window_close"

    connection.close()


def test_sync_delivery_feedback_dedupes_retried_reply_signal_by_logical_event(tmp_path: Path):
    project_root, paths = bootstrap_project(tmp_path)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    seed_posting(connection)
    seed_linked_contact(
        connection,
        contact_id="ct_replied",
        job_posting_contact_id="jpc_replied",
        display_name="Morgan Manager",
        recipient_email="morgan@acme.example",
        recipient_type="hiring_manager",
    )
    seed_sent_message(
        connection,
        outreach_message_id="msg_replied",
        contact_id="ct_replied",
        recipient_email="morgan@acme.example",
        thread_id="thread-msg_replied",
        delivery_tracking_id="delivery-msg_replied",
        sent_at="2026-04-07T10:04:00Z",
        job_posting_contact_id="jpc_replied",
    )

    first_result = sync_delivery_feedback(
        connection,
        project_root=project_root,
        current_time="2026-04-07T10:10:00Z",
        scheduler_name="job-hunt-copilot-feedback-sync",
        scheduler_type="launchd",
        observer=FakeMailboxFeedbackObserver(
            signals=[
                DeliveryFeedbackSignal(
                    signal_type=EVENT_STATE_REPLIED,
                    event_timestamp="2026-04-07T10:06:00Z",
                    thread_id="thread-msg_replied",
                    reply_summary="Interested in chatting.",
                    raw_reply_excerpt="Interested in chatting.",
                )
            ]
        ),
    )
    second_result = sync_delivery_feedback(
        connection,
        project_root=project_root,
        current_time="2026-04-07T10:11:00Z",
        scheduler_name="job-hunt-copilot-feedback-sync",
        scheduler_type="launchd",
        observer=FakeMailboxFeedbackObserver(
            signals=[
                DeliveryFeedbackSignal(
                    signal_type=EVENT_STATE_REPLIED,
                    event_timestamp="2026-04-07T10:06:00Z",
                    thread_id="thread-msg_replied",
                    reply_summary="Interested in chatting next week.",
                    raw_reply_excerpt="Interested in chatting next week if you have time.",
                )
            ]
        ),
    )

    assert first_result.reply_events_written == 1
    assert second_result.reply_events_written == 0
    assert second_result.persisted_events == ()

    event_rows = connection.execute(
        """
        SELECT event_state, event_timestamp, reply_summary, raw_reply_excerpt
        FROM delivery_feedback_events
        WHERE outreach_message_id = ?
        """,
        ("msg_replied",),
    ).fetchall()
    assert len(event_rows) == 1
    assert dict(event_rows[0]) == {
        "event_state": EVENT_STATE_REPLIED,
        "event_timestamp": "2026-04-07T10:06:00Z",
        "reply_summary": "Interested in chatting next week.",
        "raw_reply_excerpt": "Interested in chatting next week if you have time.",
    }

    latest_payload = json.loads(
        paths.outreach_latest_delivery_outcome_path(
            "Acme Robotics",
            "Staff Software Engineer / AI",
        ).read_text(encoding="utf-8")
    )
    assert latest_payload["reply_summary"] == "Interested in chatting next week."
    assert latest_payload["raw_reply_excerpt"] == "Interested in chatting next week if you have time."

    connection.close()
