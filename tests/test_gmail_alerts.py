from __future__ import annotations

import json

from job_hunt_copilot.bootstrap import run_bootstrap
from job_hunt_copilot.gmail_alerts import (
    BODY_REPRESENTATION_TEXT_HTML_DERIVED,
    BODY_REPRESENTATION_TEXT_PLAIN,
    ingest_gmail_alert_batch,
)
from job_hunt_copilot.paths import ProjectPaths
from tests.support import create_minimal_project


def bootstrap_project(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    create_minimal_project(project_root)
    run_bootstrap(project_root=project_root)
    return project_root


def build_batch(*messages, ingestion_run_id="gmail-run-001"):
    return {
        "ingestion_run_id": ingestion_run_id,
        "messages": list(messages),
    }


def build_message(
    *,
    gmail_message_id,
    gmail_thread_id="gmail-thread-001",
    subject="LinkedIn job alerts",
    received_at="2026-04-06T23:57:13Z",
    text_plain_body=None,
    text_html_body=None,
):
    payload = {
        "gmail_message_id": gmail_message_id,
        "gmail_thread_id": gmail_thread_id,
        "sender": "jobalerts-noreply@linkedin.com",
        "subject": subject,
        "received_at": received_at,
    }
    if text_plain_body is not None:
        payload["text_plain_body"] = text_plain_body
    if text_html_body is not None:
        payload["text_html_body"] = text_html_body
    return payload


def test_gmail_collection_persists_plain_text_first_multi_card_artifacts(tmp_path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)

    plain_text_body = (
        "Jobs you may be interested in\n\n"
        "-----\n"
        "Senior Software Engineer\n"
        "Guidewire Software\n"
        "Boston, MA (Hybrid)\n"
        "5 school alumni work here\n"
        "Promoted\n"
        "View job\n"
        "https://www.linkedin.com/jobs/view/1234567890/?trackingId=abc\n\n"
        "-----\n"
        "Staff Platform Engineer\n"
        "Acme Corp\n"
        "Remote\n"
        "Actively recruiting\n"
        "View job\n"
        "https://www.linkedin.com/jobs/view/9876543210/?trk=email_digest\n\n"
        "Manage preferences\n"
    )
    html_body = (
        "<html><body><div>Fallback card</div>"
        "<a href='https://www.linkedin.com/jobs/view/1111111111/'>View job</a></body></html>"
    )

    result = ingest_gmail_alert_batch(
        project_root,
        batch=build_batch(
            build_message(
                gmail_message_id="gmail-message-123",
                text_plain_body=plain_text_body,
                text_html_body=html_body,
            )
        ),
    )

    assert result.messages_seen == 1
    assert result.collections_created == 1
    assert result.duplicates_ignored == 0
    assert result.zero_card_messages == 0

    collection = result.collection_results[0]
    email_payload = json.loads(collection.email_json_path.read_text(encoding="utf-8"))
    cards_payload = json.loads(collection.job_cards_path.read_text(encoding="utf-8"))

    assert collection.created is True
    assert collection.duplicate is False
    assert collection.body_representation_used == BODY_REPRESENTATION_TEXT_PLAIN
    assert collection.collection_dir == paths.gmail_runtime_dir / "20260406T235713Z-gmail-message-123"
    assert collection.email_markdown_path.exists()
    assert collection.email_markdown_path.read_text(encoding="utf-8").startswith("# Gmail Alert Email")

    assert email_payload["gmail_message_id"] == "gmail-message-123"
    assert email_payload["body_representation_used"] == BODY_REPRESENTATION_TEXT_PLAIN
    assert email_payload["parse_outcome"] == "parsed_cards"
    assert email_payload["parseable_job_card_count"] == 2
    assert email_payload["lead_fanout_ready"] is True

    cards = cards_payload["cards"]
    assert len(cards) == 2
    assert cards[0] == {
        "card_index": 1,
        "role_title": "Senior Software Engineer",
        "company_name": "Guidewire Software",
        "location": "Boston, MA (Hybrid)",
        "badge_lines": ["5 school alumni work here", "Promoted"],
        "job_url": "https://www.linkedin.com/jobs/view/1234567890/",
        "job_id": "1234567890",
        "gmail_message_id": "gmail-message-123",
        "synthetic_identity_key": None,
    }
    assert cards[1]["card_index"] == 2
    assert cards[1]["role_title"] == "Staff Platform Engineer"
    assert cards[1]["company_name"] == "Acme Corp"
    assert cards[1]["location"] == "Remote"
    assert cards[1]["job_url"] == "https://www.linkedin.com/jobs/view/9876543210/"
    assert cards[1]["job_id"] == "9876543210"


def test_gmail_collection_is_idempotent_by_message_id_and_does_not_collapse_same_thread_messages(tmp_path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)

    batch = build_batch(
        build_message(
            gmail_message_id="gmail-message-001",
            gmail_thread_id="gmail-thread-shared",
            received_at="2026-04-06T23:00:00Z",
            text_plain_body=(
                "-----\n"
                "Senior Backend Engineer\n"
                "Northwind\n"
                "Remote\n"
                "View job\n"
                "https://www.linkedin.com/jobs/view/1111111111/\n"
            ),
        ),
        build_message(
            gmail_message_id="gmail-message-002",
            gmail_thread_id="gmail-thread-shared",
            received_at="2026-04-06T23:05:00Z",
            text_plain_body=(
                "-----\n"
                "Frontend Engineer\n"
                "Northwind\n"
                "Phoenix, AZ\n"
                "View job\n"
                "https://www.linkedin.com/jobs/view/2222222222/\n"
            ),
        ),
        ingestion_run_id="gmail-run-thread-test",
    )

    first_result = ingest_gmail_alert_batch(project_root, batch=batch)
    duplicate_result = ingest_gmail_alert_batch(
        project_root,
        batch=build_batch(
            build_message(
                gmail_message_id="gmail-message-001",
                gmail_thread_id="gmail-thread-shared",
                received_at="2026-04-07T00:00:00Z",
                text_plain_body=(
                    "-----\n"
                    "Senior Backend Engineer\n"
                    "Northwind\n"
                    "Remote\n"
                    "View job\n"
                    "https://www.linkedin.com/jobs/view/1111111111/\n"
                ),
            ),
            ingestion_run_id="gmail-run-duplicate-test",
        ),
    )

    assert first_result.collections_created == 2
    assert first_result.duplicates_ignored == 0
    assert duplicate_result.collections_created == 0
    assert duplicate_result.duplicates_ignored == 1

    runtime_dirs = sorted(path.name for path in paths.gmail_runtime_dir.iterdir() if path.is_dir())
    assert runtime_dirs == [
        "20260406T230000Z-gmail-message-001",
        "20260406T230500Z-gmail-message-002",
    ]
    assert duplicate_result.collection_results[0].duplicate is True
    assert duplicate_result.collection_results[0].parseable_job_card_count == 1


def test_gmail_parser_falls_back_to_html_only_when_plain_text_is_unusable(tmp_path):
    project_root = bootstrap_project(tmp_path)

    result = ingest_gmail_alert_batch(
        project_root,
        batch=build_batch(
            build_message(
                gmail_message_id="gmail-message-html",
                text_plain_body="LinkedIn updates\nManage preferences\n",
                text_html_body=(
                    "<html><body>"
                    "<div>Principal Platform Engineer</div>"
                    "<div>Widget Labs</div>"
                    "<div>Remote</div>"
                    "<div>Actively recruiting</div>"
                    "<a href='https://www.linkedin.com/jobs/view/5555555555/?trk=foo'>View job</a>"
                    "</body></html>"
                ),
            )
        ),
    )

    collection = result.collection_results[0]
    email_payload = json.loads(collection.email_json_path.read_text(encoding="utf-8"))
    cards_payload = json.loads(collection.job_cards_path.read_text(encoding="utf-8"))

    assert collection.body_representation_used == BODY_REPRESENTATION_TEXT_HTML_DERIVED
    assert email_payload["body_representation_used"] == BODY_REPRESENTATION_TEXT_HTML_DERIVED
    assert email_payload["parseable_job_card_count"] == 1
    assert cards_payload["cards"][0]["role_title"] == "Principal Platform Engineer"
    assert cards_payload["cards"][0]["company_name"] == "Widget Labs"
    assert cards_payload["cards"][0]["job_url"] == "https://www.linkedin.com/jobs/view/5555555555/"


def test_zero_card_gmail_collection_retains_artifacts_and_flags_run_threshold_review(tmp_path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)

    batch = build_batch(
        build_message(
            gmail_message_id="gmail-zero-001",
            received_at="2026-04-06T21:00:00Z",
            text_plain_body="LinkedIn updates\nManage preferences\n",
        ),
        build_message(
            gmail_message_id="gmail-zero-002",
            received_at="2026-04-06T21:01:00Z",
            text_plain_body="LinkedIn updates\nManage preferences\n",
        ),
        build_message(
            gmail_message_id="gmail-zero-003",
            received_at="2026-04-06T21:02:00Z",
            text_plain_body="LinkedIn updates\nManage preferences\n",
        ),
        build_message(
            gmail_message_id="gmail-zero-004",
            received_at="2026-04-06T21:03:00Z",
            text_plain_body="LinkedIn updates\nManage preferences\n",
        ),
        ingestion_run_id="gmail-run-zero-threshold",
    )

    result = ingest_gmail_alert_batch(project_root, batch=batch)

    assert result.collections_created == 4
    assert result.zero_card_messages == 4
    assert result.review_required_zero_card_messages == 4
    assert not any(paths.project_root.joinpath("linkedin-scraping", "runtime", "leads").iterdir())

    for collection in result.collection_results:
        email_payload = json.loads(collection.email_json_path.read_text(encoding="utf-8"))
        cards_payload = json.loads(collection.job_cards_path.read_text(encoding="utf-8"))
        assert cards_payload["cards"] == []
        assert email_payload["parse_outcome"] == "zero_cards"
        assert email_payload["zero_card_review"] == {
            "threshold": 3,
            "review_required": True,
            "trigger_reason": "run_threshold_exceeded",
            "zero_card_count_in_run": 4,
            "cumulative_unresolved_zero_card_count": 4,
            "review_resolved": False,
        }


def test_zero_card_gmail_collection_uses_history_threshold_across_runs(tmp_path):
    project_root = bootstrap_project(tmp_path)

    first_batch = build_batch(
        build_message(
            gmail_message_id="gmail-history-001",
            received_at="2026-04-06T20:00:00Z",
            text_plain_body="LinkedIn updates\nManage preferences\n",
        ),
        build_message(
            gmail_message_id="gmail-history-002",
            received_at="2026-04-06T20:01:00Z",
            text_plain_body="LinkedIn updates\nManage preferences\n",
        ),
        build_message(
            gmail_message_id="gmail-history-003",
            received_at="2026-04-06T20:02:00Z",
            text_plain_body="LinkedIn updates\nManage preferences\n",
        ),
        ingestion_run_id="gmail-history-run-1",
    )
    second_batch = build_batch(
        build_message(
            gmail_message_id="gmail-history-004",
            received_at="2026-04-06T22:00:00Z",
            text_plain_body="LinkedIn updates\nManage preferences\n",
        ),
        ingestion_run_id="gmail-history-run-2",
    )

    first_result = ingest_gmail_alert_batch(project_root, batch=first_batch)
    second_result = ingest_gmail_alert_batch(project_root, batch=second_batch)

    assert first_result.review_required_zero_card_messages == 0
    assert second_result.review_required_zero_card_messages == 1

    email_payload = json.loads(second_result.collection_results[0].email_json_path.read_text(encoding="utf-8"))
    assert email_payload["zero_card_review"] == {
        "threshold": 3,
        "review_required": True,
        "trigger_reason": "history_threshold_exceeded",
        "zero_card_count_in_run": 1,
        "cumulative_unresolved_zero_card_count": 4,
        "review_resolved": False,
    }
