from __future__ import annotations

import base64
import json
import sqlite3

import yaml

from job_hunt_copilot.bootstrap import run_bootstrap
from job_hunt_copilot.gmail_alerts import (
    BODY_REPRESENTATION_TEXT_HTML_DERIVED,
    BODY_REPRESENTATION_TEXT_PLAIN,
    GmailLinkedInAlertMailboxCollector,
    ingest_gmail_alert_batch,
)
from job_hunt_copilot.linkedin_scraping import (
    ingest_gmail_alert_batch_to_leads,
    materialize_gmail_lead_entities,
    repair_stale_blocked_gmail_leads,
)
from job_hunt_copilot.paths import ProjectPaths
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
    **extra_fields,
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
    payload.update(extra_fields)
    return payload


def _gmail_api_body(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")


def _downgrade_gmail_lead_to_stale_parser_state(project_root, lead_result) -> None:
    alert_card = json.loads(lead_result.alert_card_path.read_text(encoding="utf-8"))
    collection_job_cards_path = project_root / alert_card["collection_job_cards_path"]
    job_cards_payload = json.loads(collection_job_cards_path.read_text(encoding="utf-8"))
    card_index = int(alert_card["card_index"]) - 1
    job_cards_payload["cards"][card_index]["job_url"] = None
    job_cards_payload["cards"][card_index]["job_id"] = None
    job_cards_payload["cards"][card_index]["synthetic_identity_key"] = None
    collection_job_cards_path.write_text(
        json.dumps(job_cards_payload, indent=2) + "\n",
        encoding="utf-8",
    )

    alert_card["job_url"] = None
    alert_card["job_id"] = None
    alert_card["synthetic_identity_key"] = None
    lead_result.alert_card_path.write_text(
        json.dumps(alert_card, indent=2) + "\n",
        encoding="utf-8",
    )

    manifest = yaml.safe_load(lead_result.lead_manifest_path.read_text(encoding="utf-8"))
    manifest["source"]["source_url"] = None
    manifest["source"]["gmail"]["job_url"] = None
    manifest["source"]["gmail"]["job_id"] = None
    manifest["source"]["gmail"]["synthetic_identity_key"] = None
    lead_result.lead_manifest_path.write_text(
        yaml.safe_dump(manifest, sort_keys=False),
        encoding="utf-8",
    )

    connection = connect_database(project_root / "job_hunt_copilot.db")
    connection.execute(
        "UPDATE linkedin_leads SET source_url = NULL WHERE lead_id = ?",
        (lead_result.lead_id,),
    )
    connection.commit()
    connection.close()


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


def test_gmail_parser_handles_alert_creation_intro_and_comm_job_urls(tmp_path):
    project_root = bootstrap_project(tmp_path)

    result = ingest_gmail_alert_batch(
        project_root,
        batch=build_batch(
            build_message(
                gmail_message_id="gmail-message-comm-001",
                received_at="2026-04-06T23:30:00Z",
                text_plain_body=(
                    "Your job alert has been created: Software Engineer Hiring in Greater Phoenix Area.\n"
                    "You’ll receive notifications when new jobs are posted that match your search preferences.\n"
                    "Software Application Development Engineer\n"
                    "Intel\n"
                    "Phoenix, Arizona, United States\n"
                    "825 company alumni\n"
                    "View job: https://www.linkedin.com/comm/jobs/view/4386830282?trk=email_digest\n"
                ),
            )
        ),
    )

    collection = result.collection_results[0]
    cards_payload = json.loads(collection.job_cards_path.read_text(encoding="utf-8"))
    assert collection.parseable_job_card_count == 1
    assert cards_payload["cards"] == [
        {
            "card_index": 1,
            "role_title": "Software Application Development Engineer",
            "company_name": "Intel",
            "location": "Phoenix, Arizona, United States",
            "badge_lines": ["825 company alumni"],
            "job_url": "https://www.linkedin.com/jobs/view/4386830282/",
            "job_id": "4386830282",
            "gmail_message_id": "gmail-message-comm-001",
            "synthetic_identity_key": None,
        }
    ]


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


def test_gmail_batch_fanout_creates_incomplete_lead_workspace_with_jd_provenance(tmp_path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)

    batch = build_batch(
        build_message(
            gmail_message_id="gmail-lead-001",
            received_at="2026-04-06T23:10:00Z",
            text_plain_body=(
                "-----\n"
                "Senior Software Engineer\n"
                "Guidewire Software\n"
                "Boston, MA (Hybrid)\n"
                "Actively recruiting\n"
                "View job\n"
                "https://www.linkedin.com/jobs/view/1234567890/?trackingId=abc\n"
            ),
            jd_recovery=[
                {
                    "job_id": "1234567890",
                    "source_type": "linkedin_guest_job_payload",
                    "source_url": "https://www.linkedin.com/jobs/view/1234567890/",
                    "company_name": "Guidewire Software",
                    "role_title": "Senior Software Engineer",
                    "jd_text": (
                        "About the job\n"
                        "Build distributed insurance product surfaces with Python and TypeScript.\n"
                        "Qualifications\n"
                        "5+ years of backend platform experience.\n"
                    ),
                    "company_resolution": {
                        "status": "best_effort_no_exact_role",
                        "reason_code": "no_exact_company_role_match",
                        "company_website_url": "https://www.guidewire.com",
                        "careers_url": "https://www.guidewire.com/careers",
                    },
                }
            ],
        ),
        ingestion_run_id="gmail-lead-run-001",
    )

    result = ingest_gmail_alert_batch_to_leads(project_root, batch=batch)

    assert result.collections_created == 1
    assert result.leads_created == 1
    assert result.lead_duplicates_ignored == 0
    assert result.blocked_no_jd_leads == 0

    lead = result.lead_results[0]
    manifest = yaml.safe_load(lead.lead_manifest_path.read_text(encoding="utf-8"))
    jd_fetch = json.loads(lead.jd_fetch_path.read_text(encoding="utf-8"))
    alert_card = json.loads(lead.alert_card_path.read_text(encoding="utf-8"))

    assert lead.lead_status == "incomplete"
    assert lead.alert_email_path.name == "alert-email.md"
    assert lead.jd_path.read_text(encoding="utf-8").startswith("About the job")
    assert paths.lead_raw_source_path("Guidewire Software", "Senior Software Engineer", lead.lead_id).exists() is False
    assert manifest["lead_status"] == "incomplete"
    assert manifest["split_review_status"] == "not_applicable"
    assert manifest["artifacts"]["raw_source_path"] is None
    assert manifest["artifacts"]["alert_email_path"] == str(lead.alert_email_path.resolve())
    assert manifest["artifact_availability"]["post"]["reason_code"] == "not_available_in_gmail_mode"
    assert manifest["artifact_availability"]["poster_profile"]["reason_code"] == "not_available_in_gmail_mode"
    assert manifest["handoff_targets"]["posting_materialization"]["ready"] is True
    assert manifest["handoff_targets"]["resume_tailoring"]["ready"] is False
    assert manifest["handoff_targets"]["resume_tailoring"]["reason_code"] == "posting_not_materialized"
    assert jd_fetch["jd_recovery_status"] == "recovered"
    assert jd_fetch["selected_source"]["source_type"] == "linkedin_guest_job_payload"
    assert jd_fetch["company_resolution"] == {
        "status": "best_effort_no_exact_role",
        "reason_code": "no_exact_company_role_match",
        "company_website_url": "https://www.guidewire.com",
        "careers_url": "https://www.guidewire.com/careers",
    }
    assert alert_card["job_id"] == "1234567890"
    assert alert_card["collection_job_cards_path"].endswith("/job-cards.json")

    connection = connect_database(project_root / "job_hunt_copilot.db")
    lead_row = connection.execute(
        """
        SELECT lead_status, split_review_status, source_type, source_mode, source_url
        FROM linkedin_leads
        WHERE lead_id = ?
        """,
        (lead.lead_id,),
    ).fetchone()
    artifact_types = {
        row["artifact_type"]
        for row in connection.execute(
            """
            SELECT artifact_type
            FROM artifact_records
            WHERE lead_id = ?
            """,
            (lead.lead_id,),
        ).fetchall()
    }
    connection.close()

    assert dict(lead_row) == {
        "lead_status": "incomplete",
        "split_review_status": "not_applicable",
        "source_type": "gmail_linkedin_job_alert_email",
        "source_mode": "gmail_job_alert",
        "source_url": "https://www.linkedin.com/jobs/view/1234567890/",
    }
    assert {
        "lead_alert_email",
        "lead_alert_card",
        "lead_jd_fetch",
        "lead_manifest",
    }.issubset(artifact_types)


def test_materialize_gmail_lead_entities_creates_job_posting_and_updates_manifest(tmp_path):
    project_root = bootstrap_project(tmp_path)

    batch = build_batch(
        build_message(
            gmail_message_id="gmail-materialize-001",
            received_at="2026-04-06T23:10:00Z",
            text_plain_body=(
                "-----\n"
                "Senior Software Engineer\n"
                "Guidewire Software\n"
                "Boston, MA (Hybrid)\n"
                "Actively recruiting\n"
                "View job\n"
                "https://www.linkedin.com/jobs/view/1234567890/?trackingId=abc\n"
            ),
            jd_recovery=[
                {
                    "job_id": "1234567890",
                    "source_type": "linkedin_guest_job_payload",
                    "source_url": "https://www.linkedin.com/jobs/view/1234567890/",
                    "company_name": "Guidewire Software",
                    "role_title": "Senior Software Engineer",
                    "jd_text": "About the job\nBuild backend systems.\n",
                }
            ],
        ),
        ingestion_run_id="gmail-materialize-run-001",
    )

    ingestion = ingest_gmail_alert_batch_to_leads(project_root, batch=batch)
    lead = ingestion.lead_results[0]

    materialized = materialize_gmail_lead_entities(project_root, lead_id=lead.lead_id)

    assert materialized.materialized is True
    assert materialized.job_posting_created is True
    assert materialized.reason_code is None

    manifest = yaml.safe_load(materialized.lead_manifest_path.read_text(encoding="utf-8"))
    assert manifest["lead_status"] == "handed_off"
    assert manifest["created_entities"]["job_posting_id"] == materialized.job_posting_id
    assert manifest["handoff_targets"]["posting_materialization"]["created_entities"] == {
        "job_posting_id": materialized.job_posting_id
    }
    assert manifest["handoff_targets"]["resume_tailoring"]["ready"] is True

    connection = connect_database(project_root / "job_hunt_copilot.db")
    posting_row = connection.execute(
        """
        SELECT lead_id, posting_status, jd_artifact_path
        FROM job_postings
        WHERE job_posting_id = ?
        """,
        (materialized.job_posting_id,),
    ).fetchone()
    lead_row = connection.execute(
        """
        SELECT lead_status
        FROM linkedin_leads
        WHERE lead_id = ?
        """,
        (lead.lead_id,),
    ).fetchone()
    connection.close()

    assert posting_row is not None
    assert posting_row["lead_id"] == lead.lead_id
    assert posting_row["posting_status"] == "sourced"
    assert posting_row["jd_artifact_path"].endswith("/jd.md")
    assert lead_row["lead_status"] == "handed_off"


def test_repair_stale_blocked_gmail_leads_reparses_collection_and_materializes(tmp_path, monkeypatch):
    project_root = bootstrap_project(tmp_path)

    batch = build_batch(
        build_message(
            gmail_message_id="gmail-stale-001",
            received_at="2026-04-06T23:20:00Z",
            subject="Achyutaram: your job alert for Software Engineer Hiring in Greater Phoenix Area has been created",
            text_plain_body=(
                "Your job alert has been created: Software Engineer Hiring in Greater Phoenix Area.\n"
                "You’ll receive notifications when new jobs are posted that match your search preferences.\n"
                "-----\n"
                "Full Stack Engineer\n"
                "LHH\n"
                "Phoenix, Arizona, United States\n"
                "Apply with resume & profile\n"
                "View job\n"
                "https://www.linkedin.com/comm/jobs/view/4389508705?trackingId=abc\n"
            ),
        ),
        ingestion_run_id="gmail-stale-run-001",
    )

    monkeypatch.setattr(
        "job_hunt_copilot.linkedin_scraping._fetch_live_gmail_jd_recovery_candidate",
        lambda card: None,
    )
    ingestion = ingest_gmail_alert_batch_to_leads(project_root, batch=batch)
    lead = ingestion.lead_results[0]
    _downgrade_gmail_lead_to_stale_parser_state(project_root, lead)

    monkeypatch.setattr(
        "job_hunt_copilot.linkedin_scraping._fetch_live_gmail_jd_recovery_candidate",
        lambda card: {
            "job_id": card.get("job_id"),
            "job_url": card.get("job_url"),
            "source_type": "linkedin_guest_job_page",
            "source_url": card.get("job_url"),
            "company_name": "LHH",
            "role_title": "Full Stack Engineer",
            "jd_text": "About the job\nBuild .NET services.\n",
        },
    )
    repair = repair_stale_blocked_gmail_leads(project_root, lead_id=lead.lead_id, limit=1)

    assert repair.leads_considered == 1
    assert repair.leads_repaired == 1
    assert repair.materialized_postings == 1
    repaired = repair.repaired_results[0]
    assert repaired.refreshed_job_url == "https://www.linkedin.com/jobs/view/4389508705/"
    assert repaired.final_lead_status == "handed_off"
    assert repaired.materialized is True

    connection = connect_database(project_root / "job_hunt_copilot.db")
    lead_row = connection.execute(
        """
        SELECT lead_status, source_url
        FROM linkedin_leads
        WHERE lead_id = ?
        """,
        (lead.lead_id,),
    ).fetchone()
    posting_count = connection.execute("SELECT COUNT(*) FROM job_postings").fetchone()[0]
    connection.close()

    assert dict(lead_row) == {
        "lead_status": "handed_off",
        "source_url": "https://www.linkedin.com/jobs/view/4389508705/",
    }
    assert posting_count == 1


def test_gmail_mailbox_collector_prepares_batch_from_live_api_shape(tmp_path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)

    class FakeMessagesResource:
        def list(self, **kwargs):  # type: ignore[no-untyped-def]
            class _Request:
                def execute(self_inner):  # type: ignore[no-untyped-def]
                    assert kwargs["q"] == "from:jobalerts-noreply@linkedin.com newer_than:30d"
                    return {"messages": [{"id": "gmail-api-001", "threadId": "thread-001"}]}

            return _Request()

        def get(self, **kwargs):  # type: ignore[no-untyped-def]
            class _Request:
                def execute(self_inner):  # type: ignore[no-untyped-def]
                    assert kwargs["id"] == "gmail-api-001"
                    return {
                        "id": "gmail-api-001",
                        "threadId": "thread-001",
                        "internalDate": "1775518200000",
                        "payload": {
                            "mimeType": "multipart/alternative",
                            "headers": [
                                {"name": "From", "value": "LinkedIn <jobalerts-noreply@linkedin.com>"},
                                {"name": "Subject", "value": "LinkedIn job alerts"},
                            ],
                            "parts": [
                                {
                                    "mimeType": "text/plain",
                                    "body": {
                                        "data": _gmail_api_body(
                                            "-----\n"
                                            "Senior Software Engineer\n"
                                            "Guidewire Software\n"
                                            "Boston, MA (Hybrid)\n"
                                            "View job\n"
                                            "https://www.linkedin.com/jobs/view/1234567890/\n"
                                        )
                                    },
                                }
                            ],
                        },
                    }

            return _Request()

    class FakeUsersResource:
        def __init__(self) -> None:
            self._messages = FakeMessagesResource()

        def messages(self) -> FakeMessagesResource:
            return self._messages

    class FakeGmailService:
        def __init__(self) -> None:
            self._users = FakeUsersResource()

        def users(self) -> FakeUsersResource:
            return self._users

    collector = GmailLinkedInAlertMailboxCollector(
        paths,
        service_factory=FakeGmailService,
        max_new_messages=1,
    )

    batch = collector.prepare_batch(current_time="2026-04-09T00:20:00Z")

    assert batch is not None
    assert batch.ingestion_run_id == "gmail-auto-20260409T002000Z"
    assert len(batch.messages) == 1
    message = batch.messages[0]
    assert message.gmail_message_id == "gmail-api-001"
    assert message.gmail_thread_id == "thread-001"
    assert message.subject == "LinkedIn job alerts"
    assert message.received_at == "2026-04-06T23:30:00Z"
    assert "Senior Software Engineer" in (message.text_plain_body or "")


def test_gmail_batch_fanout_dedupes_existing_leads_by_job_id(tmp_path):
    project_root = bootstrap_project(tmp_path)

    batch = build_batch(
        build_message(
            gmail_message_id="gmail-dedupe-001",
            received_at="2026-04-06T23:20:00Z",
            text_plain_body=(
                "-----\n"
                "Senior Backend Engineer\n"
                "Northwind\n"
                "Remote\n"
                "View job\n"
                "https://www.linkedin.com/jobs/view/1111111111/?trk=email_digest\n"
            ),
            jd_recovery=[
                {
                    "job_id": "1111111111",
                    "source_type": "linkedin_guest_job_payload",
                    "source_url": "https://www.linkedin.com/jobs/view/1111111111/",
                    "jd_text": "About the job\nBuild APIs.\n",
                }
            ],
        ),
        build_message(
            gmail_message_id="gmail-dedupe-002",
            received_at="2026-04-06T23:21:00Z",
            text_plain_body=(
                "-----\n"
                "Senior Backend Engineer\n"
                "Northwind\n"
                "Remote\n"
                "View job\n"
                "https://www.linkedin.com/jobs/view/1111111111/?trackingId=second\n"
            ),
            jd_recovery=[
                {
                    "job_id": "1111111111",
                    "source_type": "linkedin_guest_job_payload",
                    "source_url": "https://www.linkedin.com/jobs/view/1111111111/",
                    "jd_text": "About the job\nBuild APIs.\n",
                }
            ],
        ),
        ingestion_run_id="gmail-dedupe-run-001",
    )

    result = ingest_gmail_alert_batch_to_leads(project_root, batch=batch)

    assert result.collections_created == 2
    assert result.leads_created == 1
    assert result.lead_duplicates_ignored == 1
    assert result.lead_results[0].created is True
    assert result.lead_results[1].duplicate is True
    assert result.lead_results[1].duplicate_lead_id == result.lead_results[0].lead_id

    connection = connect_database(project_root / "job_hunt_copilot.db")
    lead_count = connection.execute("SELECT COUNT(*) FROM linkedin_leads").fetchone()[0]
    connection.close()

    assert lead_count == 1


def test_gmail_batch_fanout_blocks_no_jd_when_no_identifier_or_jd_recovery_exists(tmp_path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)

    batch = build_batch(
        build_message(
            gmail_message_id="gmail-blocked-001",
            received_at="2026-04-06T23:30:00Z",
            text_plain_body=(
                "-----\n"
                "Platform Engineer\n"
                "Widget Labs\n"
                "Remote\n"
                "Actively recruiting\n"
                "View job\n"
            ),
        ),
        ingestion_run_id="gmail-blocked-run-001",
    )

    result = ingest_gmail_alert_batch_to_leads(project_root, batch=batch)

    assert result.leads_created == 1
    assert result.blocked_no_jd_leads == 1

    lead = result.lead_results[0]
    manifest = yaml.safe_load(lead.lead_manifest_path.read_text(encoding="utf-8"))
    jd_fetch = json.loads(lead.jd_fetch_path.read_text(encoding="utf-8"))
    alert_card = json.loads(lead.alert_card_path.read_text(encoding="utf-8"))

    assert lead.lead_status == "blocked_no_jd"
    assert lead.reason_code == "missing_jd"
    assert lead.jd_path is None
    assert paths.lead_jd_path("Widget Labs", "Platform Engineer", lead.lead_id).exists() is False
    assert alert_card["job_id"] is None
    assert alert_card["job_url"] is None
    assert alert_card["synthetic_identity_key"].startswith("gmail_alert_card_summary|")
    assert manifest["lead_status"] == "blocked_no_jd"
    assert manifest["source"]["gmail"]["synthetic_identity_key"].startswith("gmail_alert_card_summary|")
    assert manifest["handoff_targets"]["posting_materialization"]["ready"] is False
    assert manifest["handoff_targets"]["posting_materialization"]["reason_code"] == "missing_jd"
    assert jd_fetch["result"] == "blocked"
    assert jd_fetch["reason_code"] == "missing_jd"

    connection = connect_database(project_root / "job_hunt_copilot.db")
    lead_row = connection.execute(
        """
        SELECT lead_status, split_review_status, source_reference
        FROM linkedin_leads
        WHERE lead_id = ?
        """,
        (lead.lead_id,),
    ).fetchone()
    connection.close()

    assert dict(lead_row) == {
        "lead_status": "blocked_no_jd",
        "split_review_status": "not_applicable",
        "source_reference": "linkedin-scraping/runtime/gmail/20260406T233000Z-gmail-blocked-001/job-cards.json#card_index=1",
    }


def test_gmail_batch_fanout_merges_multiple_jd_sources_and_prefers_linkedin_conflicts(tmp_path):
    project_root = bootstrap_project(tmp_path)

    batch = build_batch(
        build_message(
            gmail_message_id="gmail-merge-001",
            received_at="2026-04-06T23:40:00Z",
            text_plain_body=(
                "-----\n"
                "Staff Platform Engineer\n"
                "Acme Corp\n"
                "Remote\n"
                "View job\n"
                "https://www.linkedin.com/jobs/view/3333333333/?trk=email_digest\n"
            ),
            jd_recovery=[
                {
                    "job_id": "3333333333",
                    "source_type": "linkedin_guest_job_payload",
                    "source_url": "https://www.linkedin.com/jobs/view/3333333333/",
                    "company_name": "Acme Corp",
                    "role_title": "Staff Platform Engineer",
                    "jd_text": (
                        "About the job\n"
                        "Build internal AI platforms for regulated products.\n\n"
                        "Qualifications\n"
                        "5+ years of distributed systems experience.\n"
                    ),
                },
                {
                    "job_id": "3333333333",
                    "source_type": "company_careers_page",
                    "source_url": "https://careers.acme.example/jobs/3333333333",
                    "company_name": "Acme Corp",
                    "role_title": "Staff Platform Engineer",
                    "jd_text": (
                        "About the job\n"
                        "Build internal AI platforms for regulated products.\n\n"
                        "Qualifications\n"
                        "Experience with healthcare claims operations.\n\n"
                        "Benefits\n"
                        "Remote-first team with an annual learning stipend.\n"
                    ),
                },
            ],
        ),
        ingestion_run_id="gmail-merge-run-001",
    )

    result = ingest_gmail_alert_batch_to_leads(project_root, batch=batch)

    lead = result.lead_results[0]
    jd_text = lead.jd_path.read_text(encoding="utf-8")
    jd_fetch = json.loads(lead.jd_fetch_path.read_text(encoding="utf-8"))
    manifest = yaml.safe_load(lead.lead_manifest_path.read_text(encoding="utf-8"))

    assert lead.lead_status == "incomplete"
    assert "5+ years of distributed systems experience." in jd_text
    assert "Experience with healthcare claims operations." not in jd_text
    assert "Benefits\nRemote-first team with an annual learning stipend." in jd_text
    assert jd_fetch["merge_status"] == "merged"
    assert jd_fetch["conflict_resolution_policy"] == (
        "prefer_linkedin_derived_content_when_available_else_highest_priority_source"
    )
    assert any(
        source["source_type"] == "company_careers_page"
        and source["merged_section_count"] == 1
        and source["conflict_section_count"] == 1
        and source["included_in_canonical_jd"] is True
        for source in jd_fetch["contributing_sources"]
    )
    assert manifest["artifact_availability"]["jd"]["provenance"]["merge_status"] == "merged"
    assert manifest["handoff_targets"]["posting_materialization"]["ready"] is True


def test_gmail_batch_fanout_blocks_posting_materialization_for_material_identity_mismatch(tmp_path):
    project_root = bootstrap_project(tmp_path)

    batch = build_batch(
        build_message(
            gmail_message_id="gmail-mismatch-001",
            received_at="2026-04-06T23:45:00Z",
            text_plain_body=(
                "-----\n"
                "Senior Software Engineer\n"
                "Google\n"
                "Remote\n"
                "View job\n"
                "https://www.linkedin.com/jobs/view/4444444444/\n"
            ),
            jd_recovery=[
                {
                    "job_id": "4444444444",
                    "source_type": "linkedin_guest_job_payload",
                    "source_url": "https://www.linkedin.com/jobs/view/4444444444/",
                    "company_name": "Meta",
                    "role_title": "Machine Learning Engineer",
                    "jd_text": (
                        "About the job\n"
                        "Build ML ranking systems.\n"
                    ),
                }
            ],
        ),
        ingestion_run_id="gmail-mismatch-run-001",
    )

    result = ingest_gmail_alert_batch_to_leads(project_root, batch=batch)

    lead = result.lead_results[0]
    manifest = yaml.safe_load(lead.lead_manifest_path.read_text(encoding="utf-8"))
    jd_fetch = json.loads(lead.jd_fetch_path.read_text(encoding="utf-8"))

    assert result.review_required_leads == 1
    assert lead.lead_status == "incomplete"
    assert lead.reason_code == "identity_mismatch_review_required"
    assert lead.jd_path.exists()
    assert manifest["result"] == "blocked"
    assert manifest["reason_code"] == "identity_mismatch_review_required"
    assert manifest["handoff_targets"]["posting_materialization"]["ready"] is False
    assert manifest["handoff_targets"]["posting_materialization"]["reason_code"] == (
        "identity_mismatch_review_required"
    )
    assert manifest["handoff_targets"]["resume_tailoring"]["ready"] is False
    assert manifest["handoff_targets"]["resume_tailoring"]["reason_code"] == (
        "identity_mismatch_review_required"
    )
    assert jd_fetch["result"] == "success"
    assert jd_fetch["identity_reconciliation"]["status"] == "review_required"
    assert jd_fetch["identity_reconciliation"]["company_match"] == "mismatch"
    assert jd_fetch["identity_reconciliation"]["role_match"] == "mismatch"


def test_gmail_batch_fanout_tolerates_normalization_only_identity_differences(tmp_path):
    project_root = bootstrap_project(tmp_path)

    batch = build_batch(
        build_message(
            gmail_message_id="gmail-normalization-001",
            received_at="2026-04-06T23:46:00Z",
            text_plain_body=(
                "-----\n"
                "SWE II\n"
                "Google\n"
                "Remote\n"
                "View job\n"
                "https://www.linkedin.com/jobs/view/5555555555/\n"
            ),
            jd_recovery=[
                {
                    "job_id": "5555555555",
                    "source_type": "linkedin_guest_job_payload",
                    "source_url": "https://www.linkedin.com/jobs/view/5555555555/",
                    "company_name": "Google LLC",
                    "role_title": "Software Engineer II",
                    "jd_text": (
                        "About the job\n"
                        "Ship core product features.\n"
                    ),
                }
            ],
        ),
        ingestion_run_id="gmail-normalization-run-001",
    )

    result = ingest_gmail_alert_batch_to_leads(project_root, batch=batch)

    lead = result.lead_results[0]
    manifest = yaml.safe_load(lead.lead_manifest_path.read_text(encoding="utf-8"))
    jd_fetch = json.loads(lead.jd_fetch_path.read_text(encoding="utf-8"))

    assert result.review_required_leads == 0
    assert lead.reason_code is None
    assert manifest["handoff_targets"]["posting_materialization"]["ready"] is True
    assert "reason_code" not in manifest
    assert jd_fetch["identity_reconciliation"]["status"] == "normalization_tolerated"
    assert jd_fetch["identity_reconciliation"]["company_match"] == "normalized_match"
    assert jd_fetch["identity_reconciliation"]["role_match"] == "normalized_match"


def test_gmail_batch_fanout_dedupes_missing_job_id_cards_by_normalized_url_fallback(tmp_path):
    project_root = bootstrap_project(tmp_path)

    batch = build_batch(
        build_message(
            gmail_message_id="gmail-url-dedupe-001",
            received_at="2026-04-06T23:50:00Z",
            text_plain_body=(
                "-----\n"
                "Backend Engineer\n"
                "Northwind\n"
                "Remote\n"
                "View job\n"
                "https://www.linkedin.com/jobs/view/backend-engineer-at-northwind/?trk=email_digest\n"
            ),
            jd_recovery=[
                {
                    "job_url": "https://www.linkedin.com/jobs/view/backend-engineer-at-northwind/",
                    "source_type": "linkedin_guest_job_payload",
                    "source_url": "https://www.linkedin.com/jobs/view/backend-engineer-at-northwind/",
                    "company_name": "Northwind",
                    "role_title": "Backend Engineer",
                    "jd_text": "About the job\nBuild APIs.\n",
                }
            ],
        ),
        build_message(
            gmail_message_id="gmail-url-dedupe-002",
            received_at="2026-04-06T23:51:00Z",
            text_plain_body=(
                "-----\n"
                "Backend Engineer\n"
                "Northwind\n"
                "Remote\n"
                "View job\n"
                "https://www.linkedin.com/jobs/view/backend-engineer-at-northwind/?trackingId=second\n"
            ),
            jd_recovery=[
                {
                    "job_url": "https://www.linkedin.com/jobs/view/backend-engineer-at-northwind/",
                    "source_type": "linkedin_guest_job_payload",
                    "source_url": "https://www.linkedin.com/jobs/view/backend-engineer-at-northwind/",
                    "company_name": "Northwind",
                    "role_title": "Backend Engineer",
                    "jd_text": "About the job\nBuild APIs.\n",
                }
            ],
        ),
        ingestion_run_id="gmail-url-dedupe-run-001",
    )

    result = ingest_gmail_alert_batch_to_leads(project_root, batch=batch)

    created_lead = result.lead_results[0]
    duplicate_lead = result.lead_results[1]
    alert_card = json.loads(created_lead.alert_card_path.read_text(encoding="utf-8"))

    assert result.leads_created == 1
    assert result.lead_duplicates_ignored == 1
    assert alert_card["job_id"] is None
    assert alert_card["synthetic_identity_key"] == (
        "gmail_alert_job_url|https://www.linkedin.com/jobs/view/backend-engineer-at-northwind/"
    )
    assert duplicate_lead.duplicate is True
    assert duplicate_lead.duplicate_lead_id == created_lead.lead_id
