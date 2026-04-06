from __future__ import annotations

import json
import sqlite3
import yaml

from job_hunt_copilot.bootstrap import run_bootstrap
from job_hunt_copilot.linkedin_scraping import (
    SUBMISSION_PATH_IMMEDIATE_SELECTED_TEXT,
    SUBMISSION_PATH_TRAY_REVIEW,
    derive_manual_lead_context,
    ingest_manual_capture_submission,
    ingest_paste_inbox,
    materialize_manual_lead_entities,
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


def build_materializable_submission(
    *,
    submission_id,
    poster_name="Alex Kordun",
    poster_title="Director of Engineering, Guidewire",
    profile_source_url="https://www.linkedin.com/in/alex-kordun/",
):
    return {
        "source_mode": "manual_capture",
        "source_type": "manual_capture_bundle",
        "submission_id": submission_id,
        "source_reference": f"http://127.0.0.1:8765/submissions/{submission_id}",
        "summary": {
            "company_name": "Guidewire Software",
            "role_title": "Software Engineer (Full-Stack)",
            "location": "Bedford, MA",
            "work_mode": "Hybrid",
            "poster_name": poster_name,
            "poster_title": poster_title,
        },
        "captures": [
            {
                "capture_order": 1,
                "capture_mode": "selected_text",
                "page_type": "post",
                "source_url": "https://www.linkedin.com/feed/update/example",
                "selected_text": "We're hiring backend and frontend engineers.",
                "full_text": "View job\nWe're hiring backend and frontend engineers.\n1 school alumni works here",
            },
            {
                "capture_order": 2,
                "capture_mode": "full_page",
                "page_type": "job",
                "source_url": "https://www.linkedin.com/jobs/view/example",
                "full_text": (
                    "About the job\n"
                    "Build product surfaces with Python and TypeScript.\n"
                    "Qualifications\n"
                    "3+ years of experience."
                ),
            },
            {
                "capture_order": 3,
                "capture_mode": "full_page",
                "page_type": "profile",
                "source_url": profile_source_url,
                "full_text": (
                    f"{poster_name}\n"
                    f"{poster_title}\n"
                    "HighlightsHighlights\n"
                    "Introduce myself\n"
                    "About\n"
                    "Leads distributed product teams.\n"
                    "Experience\n"
                    "Guidewire"
                ),
            },
        ],
    }


def test_paste_ingestion_copies_raw_source_unchanged_and_registers_lead_artifact(tmp_path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    pasted_source = (
        "Guidewire Software\n"
        "Software Engineer (Full-Stack)\n"
        "We're hiring backend and frontend engineers.\r\n"
        "About the job\r\n"
        "Build product surfaces with Python and TypeScript.\r\n"
    )
    paths.paste_inbox_path.write_bytes(pasted_source.encode("utf-8"))

    result = ingest_paste_inbox(
        project_root,
        company_name="Guidewire Software",
        role_title="Software Engineer (Full-Stack)",
        location="Bedford, MA",
    )

    assert result.created is True
    assert result.raw_source_path.read_bytes() == pasted_source.encode("utf-8")
    assert [path.name for path in result.raw_source_path.parent.iterdir()] == ["source.md"]

    capture_bundle = json.loads(result.capture_bundle_path.read_text(encoding="utf-8"))
    assert capture_bundle["source_mode"] == "manual_paste"
    assert capture_bundle["source_type"] == "manual_paste"
    assert capture_bundle["submission_path"] == "paste_inbox"
    assert capture_bundle["captures"][0]["full_text"] == pasted_source

    connection = connect_database(project_root / "job_hunt_copilot.db")
    lead_row = connection.execute(
        """
        SELECT lead_status, split_review_status, source_type, source_reference, source_mode,
               company_name, role_title, location
        FROM linkedin_leads
        WHERE lead_id = ?
        """,
        (result.lead_id,),
    ).fetchone()
    artifact_row = connection.execute(
        """
        SELECT artifact_type, file_path, lead_id
        FROM artifact_records
        WHERE lead_id = ?
        """,
        (result.lead_id,),
    ).fetchone()
    connection.close()

    assert dict(lead_row) == {
        "lead_status": "captured",
        "split_review_status": "not_started",
        "source_type": "manual_paste",
        "source_reference": "paste/paste.txt",
        "source_mode": "manual_paste",
        "company_name": "Guidewire Software",
        "role_title": "Software Engineer (Full-Stack)",
        "location": "Bedford, MA",
    }
    assert dict(artifact_row) == {
        "artifact_type": "lead_raw_source",
        "file_path": paths.relative_to_root(result.raw_source_path).as_posix(),
        "lead_id": result.lead_id,
    }


def test_paste_ingestion_is_idempotent_for_the_same_input(tmp_path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    paths.paste_inbox_path.write_text(
        "Guidewire Software\nSoftware Engineer (Full-Stack)\nAbout the job\nBuild it.\n",
        encoding="utf-8",
    )

    first_result = ingest_paste_inbox(
        project_root,
        company_name="Guidewire Software",
        role_title="Software Engineer (Full-Stack)",
    )
    second_result = ingest_paste_inbox(
        project_root,
        company_name="Guidewire Software",
        role_title="Software Engineer (Full-Stack)",
    )

    assert first_result.lead_id == second_result.lead_id
    assert first_result.created is True
    assert second_result.created is False

    connection = connect_database(project_root / "job_hunt_copilot.db")
    lead_count = connection.execute("SELECT COUNT(*) FROM linkedin_leads").fetchone()[0]
    artifact_count = connection.execute(
        "SELECT COUNT(*) FROM artifact_records WHERE artifact_type = 'lead_raw_source'"
    ).fetchone()[0]
    connection.close()

    assert lead_count == 1
    assert artifact_count == 1


def test_manual_capture_bundle_persists_bundle_and_selected_text_verbatim(tmp_path):
    project_root = bootstrap_project(tmp_path)

    submission = {
        "source_mode": "manual_capture",
        "source_type": "manual_capture_bundle",
        "submission_id": "manual-submission-001",
        "source_reference": "http://127.0.0.1:8765/submissions/manual-submission-001",
        "summary": {
            "company_name": "Guidewire Software",
            "role_title": "Software Engineer (Full-Stack)",
            "location": "Bedford, MA",
            "poster_name": "Alex Kordun",
        },
        "captures": [
            {
                "capture_mode": "selected_text",
                "page_type": "post",
                "source_url": "https://www.linkedin.com/feed/update/example",
                "page_title": "Guidewire is hiring",
                "selected_text": "We're hiring backend and frontend engineers.",
                "full_text": "View job\nWe're hiring backend and frontend engineers.\n1 school alumni works here",
                "captured_at": "2026-04-06T21:10:00Z",
            },
            {
                "capture_mode": "full_page",
                "page_type": "job",
                "source_url": "https://www.linkedin.com/jobs/view/example",
                "page_title": "Software Engineer (Full-Stack)",
                "full_text": "About the job\nBuild product surfaces with Python and TypeScript.",
                "captured_at": "2026-04-06T21:11:00Z",
            },
        ],
    }

    result = ingest_manual_capture_submission(project_root, submission=submission)

    capture_bundle = json.loads(result.capture_bundle_path.read_text(encoding="utf-8"))
    raw_source = result.raw_source_path.read_text(encoding="utf-8")

    assert capture_bundle["submission_path"] == SUBMISSION_PATH_IMMEDIATE_SELECTED_TEXT
    assert capture_bundle["captures"][0]["selected_text"] == "We're hiring backend and frontend engineers."
    assert "We're hiring backend and frontend engineers." in raw_source
    assert "About the job\nBuild product surfaces with Python and TypeScript." in raw_source
    assert "## Capture 1" in raw_source
    assert "## Capture 2" in raw_source


def test_manual_capture_without_selected_text_defaults_to_tray_review_submission_path(tmp_path):
    project_root = bootstrap_project(tmp_path)

    result = ingest_manual_capture_submission(
        project_root,
        submission={
            "source_mode": "manual_capture",
            "source_type": "manual_capture_bundle",
            "submission_id": "manual-submission-002",
            "source_reference": "http://127.0.0.1:8765/submissions/manual-submission-002",
            "summary": {
                "company_name": "Guidewire Software",
                "role_title": "Software Engineer (Full-Stack)",
            },
            "captures": [
                {
                    "capture_mode": "full_page",
                    "page_type": "job",
                    "full_text": "About the job\nBuild product surfaces with Python and TypeScript.",
                }
            ],
        },
    )

    capture_bundle = json.loads(result.capture_bundle_path.read_text(encoding="utf-8"))

    assert capture_bundle["submission_path"] == SUBMISSION_PATH_TRAY_REVIEW


def test_manual_lead_derivation_publishes_split_review_and_manifest_artifacts(tmp_path):
    project_root = bootstrap_project(tmp_path)

    ingestion = ingest_manual_capture_submission(
        project_root,
        submission={
            "source_mode": "manual_capture",
            "source_type": "manual_capture_bundle",
            "submission_id": "manual-submission-derive-001",
            "source_reference": "http://127.0.0.1:8765/submissions/manual-submission-derive-001",
            "summary": {
                "company_name": "Guidewire Software",
                "role_title": "Software Engineer (Full-Stack)",
                "location": "Bedford, MA",
                "work_mode": "Hybrid",
                "poster_name": "Alex Kordun",
                "poster_title": "Director of Engineering, Guidewire",
            },
            "captures": [
                {
                    "capture_order": 1,
                    "capture_mode": "selected_text",
                    "page_type": "post",
                    "selected_text": "We're hiring backend and frontend engineers.",
                    "full_text": "View job\nWe're hiring backend and frontend engineers.\n1 school alumni works here",
                },
                {
                    "capture_order": 2,
                    "capture_mode": "full_page",
                    "page_type": "job",
                    "full_text": (
                        "About the job\n"
                        "Build product surfaces with Python and TypeScript.\n"
                        "Qualifications\n"
                        "3+ years of experience."
                    ),
                },
                {
                    "capture_order": 3,
                    "capture_mode": "full_page",
                    "page_type": "profile",
                    "full_text": (
                        "Alex Kordun\n"
                        "Director of Engineering, Guidewire\n"
                        "HighlightsHighlights\n"
                        "Introduce myself\n"
                        "About\n"
                        "Leads distributed product teams.\n"
                        "Experience\n"
                        "Guidewire"
                    ),
                },
            ],
        },
    )

    derived = derive_manual_lead_context(project_root, lead_id=ingestion.lead_id)

    post_text = derived.post_path.read_text(encoding="utf-8")
    jd_text = derived.jd_path.read_text(encoding="utf-8")
    profile_text = derived.poster_profile_path.read_text(encoding="utf-8")
    split_metadata = yaml.safe_load(derived.split_metadata_path.read_text(encoding="utf-8"))
    split_review = yaml.safe_load(derived.split_review_path.read_text(encoding="utf-8"))
    manifest = yaml.safe_load(derived.lead_manifest_path.read_text(encoding="utf-8"))

    assert derived.lead_status == "reviewed"
    assert derived.split_review_status == "confident"
    assert "We're hiring backend and frontend engineers." in post_text
    assert "1 school alumni works here" in post_text
    assert "View job" not in post_text
    assert "About the job" in jd_text
    assert "Build product surfaces with Python and TypeScript." in jd_text
    assert "HighlightsHighlights" not in profile_text
    assert "Introduce myself" not in profile_text
    assert "Director of Engineering, Guidewire" in profile_text
    assert "Leads distributed product teams." in profile_text
    assert split_metadata["selected_method"] == "rule_based_first_pass"
    assert split_metadata["sections"]["post"]["section_ranges"]
    assert split_metadata["sections"]["jd"]["section_ranges"]
    assert split_review["split_status"] == "confident"
    assert split_review["recommended_action"] == "materialize_manual_lead_entities"
    assert manifest["lead_status"] == "reviewed"
    assert manifest["handoff_targets"]["posting_materialization"]["ready"] is True
    assert manifest["artifact_availability"]["poster_profile"]["available"] is True

    connection = connect_database(project_root / "job_hunt_copilot.db")
    lead_row = connection.execute(
        "SELECT lead_status, split_review_status FROM linkedin_leads WHERE lead_id = ?",
        (ingestion.lead_id,),
    ).fetchone()
    artifact_types = {
        row["artifact_type"]
        for row in connection.execute(
            """
            SELECT artifact_type
            FROM artifact_records
            WHERE lead_id = ?
            """,
            (ingestion.lead_id,),
        ).fetchall()
    }
    connection.close()

    assert dict(lead_row) == {
        "lead_status": "reviewed",
        "split_review_status": "confident",
    }
    assert {
        "lead_raw_source",
        "lead_split_metadata",
        "lead_split_review",
        "lead_manifest",
    }.issubset(artifact_types)


def test_ambiguous_manual_lead_derivation_publishes_blocked_manifest(tmp_path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    raw_text = (
        "Guidewire Software\n"
        "Software Engineer (Full-Stack)\n"
        "Interesting company.\n"
        "Reach out if this sounds interesting.\n"
    )
    paths.paste_inbox_path.write_text(raw_text, encoding="utf-8")

    ingestion = ingest_paste_inbox(
        project_root,
        company_name="Guidewire Software",
        role_title="Software Engineer (Full-Stack)",
    )
    raw_before = ingestion.raw_source_path.read_bytes()

    derived = derive_manual_lead_context(project_root, lead_id=ingestion.lead_id)

    split_review = yaml.safe_load(derived.split_review_path.read_text(encoding="utf-8"))
    manifest = yaml.safe_load(derived.lead_manifest_path.read_text(encoding="utf-8"))

    assert derived.lead_status == "split_ready"
    assert derived.split_review_status == "ambiguous"
    assert derived.jd_path is None
    assert ingestion.raw_source_path.read_bytes() == raw_before
    assert split_review["split_status"] == "ambiguous"
    assert split_review["recommended_action"] == "review_split_before_materialization"
    assert manifest["handoff_targets"]["posting_materialization"]["ready"] is False
    assert manifest["handoff_targets"]["posting_materialization"]["reason_code"] == "ambiguous_split_review"

    connection = connect_database(project_root / "job_hunt_copilot.db")
    lead_row = connection.execute(
        "SELECT lead_status, split_review_status FROM linkedin_leads WHERE lead_id = ?",
        (ingestion.lead_id,),
    ).fetchone()
    connection.close()

    assert dict(lead_row) == {
        "lead_status": "split_ready",
        "split_review_status": "ambiguous",
    }


def test_manual_lead_derivation_is_idempotent_for_artifact_records(tmp_path):
    project_root = bootstrap_project(tmp_path)

    ingestion = ingest_manual_capture_submission(
        project_root,
        submission={
            "source_mode": "manual_capture",
            "source_type": "manual_capture_bundle",
            "submission_id": "manual-submission-derive-002",
            "source_reference": "http://127.0.0.1:8765/submissions/manual-submission-derive-002",
            "summary": {
                "company_name": "Guidewire Software",
                "role_title": "Software Engineer (Full-Stack)",
            },
            "captures": [
                {
                    "capture_order": 1,
                    "capture_mode": "full_page",
                    "page_type": "job",
                    "full_text": "About the job\nBuild product surfaces with Python and TypeScript.",
                }
            ],
        },
    )

    first = derive_manual_lead_context(project_root, lead_id=ingestion.lead_id)
    second = derive_manual_lead_context(project_root, lead_id=ingestion.lead_id)

    connection = connect_database(project_root / "job_hunt_copilot.db")
    artifact_counts = {
        row["artifact_type"]: row["artifact_count"]
        for row in connection.execute(
            """
            SELECT artifact_type, COUNT(*) AS artifact_count
            FROM artifact_records
            WHERE lead_id = ?
              AND artifact_type IN ('lead_split_metadata', 'lead_split_review', 'lead_manifest')
            GROUP BY artifact_type
            """,
            (ingestion.lead_id,),
        ).fetchall()
    }
    connection.close()

    assert first.lead_manifest_path == second.lead_manifest_path
    assert artifact_counts == {
        "lead_manifest": 1,
        "lead_split_metadata": 1,
        "lead_split_review": 1,
    }


def test_manual_lead_materialization_creates_posting_contact_links_and_tailoring_handoff(tmp_path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)

    ingestion = ingest_manual_capture_submission(
        project_root,
        submission=build_materializable_submission(submission_id="manual-submission-materialize-001"),
    )
    derived = derive_manual_lead_context(project_root, lead_id=ingestion.lead_id)
    materialized = materialize_manual_lead_entities(project_root, lead_id=ingestion.lead_id)
    manifest = yaml.safe_load(materialized.lead_manifest_path.read_text(encoding="utf-8"))

    connection = connect_database(project_root / "job_hunt_copilot.db")
    lead_row = connection.execute(
        """
        SELECT lead_status, lead_shape, poster_name, poster_title
        FROM linkedin_leads
        WHERE lead_id = ?
        """,
        (ingestion.lead_id,),
    ).fetchone()
    posting_row = connection.execute(
        """
        SELECT lead_id, company_name, role_title, posting_status, jd_artifact_path
        FROM job_postings
        WHERE job_posting_id = ?
        """,
        (materialized.job_posting_id,),
    ).fetchone()
    contact_row = connection.execute(
        """
        SELECT display_name, company_name, origin_component, contact_status, position_title, linkedin_url
        FROM contacts
        WHERE contact_id = ?
        """,
        (materialized.contact_id,),
    ).fetchone()
    lead_contact_row = connection.execute(
        """
        SELECT contact_role, recipient_type_inferred, is_primary_poster
        FROM linkedin_lead_contacts
        WHERE linkedin_lead_contact_id = ?
        """,
        (materialized.linkedin_lead_contact_id,),
    ).fetchone()
    posting_contact_row = connection.execute(
        """
        SELECT recipient_type, link_level_status
        FROM job_posting_contacts
        WHERE job_posting_contact_id = ?
        """,
        (materialized.job_posting_contact_id,),
    ).fetchone()
    connection.close()

    assert derived.lead_status == "reviewed"
    assert materialized.materialized is True
    assert materialized.job_posting_created is True
    assert materialized.contact_created is True
    assert materialized.lead_status == "handed_off"
    assert materialized.lead_shape == "posting_plus_contacts"
    assert manifest["lead_status"] == "handed_off"
    assert manifest["lead_shape"] == "posting_plus_contacts"
    assert manifest["created_entities"]["job_posting_id"] == materialized.job_posting_id
    assert manifest["created_entities"]["contact_ids"] == [materialized.contact_id]
    assert manifest["created_entities"]["job_posting_contact_ids"] == [materialized.job_posting_contact_id]
    assert manifest["created_entities"]["linkedin_lead_contact_ids"] == [materialized.linkedin_lead_contact_id]
    assert manifest["handoff_targets"]["posting_materialization"]["ready"] is True
    assert manifest["handoff_targets"]["resume_tailoring"]["ready"] is True
    assert manifest["handoff_targets"]["resume_tailoring"]["created_entities"]["job_posting_id"] == (
        materialized.job_posting_id
    )
    assert dict(lead_row) == {
        "lead_status": "handed_off",
        "lead_shape": "posting_plus_contacts",
        "poster_name": "Alex Kordun",
        "poster_title": "Director of Engineering, Guidewire",
    }
    assert dict(posting_row) == {
        "lead_id": ingestion.lead_id,
        "company_name": "Guidewire Software",
        "role_title": "Software Engineer (Full-Stack)",
        "posting_status": "sourced",
        "jd_artifact_path": paths.relative_to_root(derived.jd_path).as_posix(),
    }
    assert dict(contact_row) == {
        "display_name": "Alex Kordun",
        "company_name": "Guidewire Software",
        "origin_component": "linkedin_scraping",
        "contact_status": "identified",
        "position_title": "Director of Engineering, Guidewire",
        "linkedin_url": "https://www.linkedin.com/in/alex-kordun/",
    }
    assert dict(lead_contact_row) == {
        "contact_role": "poster",
        "recipient_type_inferred": "hiring_manager",
        "is_primary_poster": 1,
    }
    assert dict(posting_contact_row) == {
        "recipient_type": "hiring_manager",
        "link_level_status": "identified",
    }


def test_manual_lead_materialization_skips_ambiguous_leads_and_keeps_manifest_blocked(tmp_path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    paths.paste_inbox_path.write_text(
        "Guidewire Software\nSoftware Engineer (Full-Stack)\nInteresting company.\nReach out if this sounds interesting.\n",
        encoding="utf-8",
    )

    ingestion = ingest_paste_inbox(
        project_root,
        company_name="Guidewire Software",
        role_title="Software Engineer (Full-Stack)",
    )
    derive_manual_lead_context(project_root, lead_id=ingestion.lead_id)
    materialized = materialize_manual_lead_entities(project_root, lead_id=ingestion.lead_id)
    manifest = yaml.safe_load(materialized.lead_manifest_path.read_text(encoding="utf-8"))

    connection = connect_database(project_root / "job_hunt_copilot.db")
    lead_row = connection.execute(
        "SELECT lead_status, lead_shape FROM linkedin_leads WHERE lead_id = ?",
        (ingestion.lead_id,),
    ).fetchone()
    posting_count = connection.execute(
        "SELECT COUNT(*) FROM job_postings WHERE lead_id = ?",
        (ingestion.lead_id,),
    ).fetchone()[0]
    connection.close()

    assert materialized.materialized is False
    assert materialized.reason_code == "ambiguous_split_review"
    assert dict(lead_row) == {
        "lead_status": "split_ready",
        "lead_shape": "posting_only",
    }
    assert posting_count == 0
    assert manifest["handoff_targets"]["posting_materialization"]["ready"] is False
    assert manifest["handoff_targets"]["posting_materialization"]["reason_code"] == "ambiguous_split_review"
    assert manifest["handoff_targets"]["resume_tailoring"]["ready"] is False
    assert manifest["handoff_targets"]["resume_tailoring"]["reason_code"] == "posting_not_materialized"


def test_manual_lead_materialization_is_idempotent_for_postings_and_links(tmp_path):
    project_root = bootstrap_project(tmp_path)

    ingestion = ingest_manual_capture_submission(
        project_root,
        submission=build_materializable_submission(submission_id="manual-submission-materialize-002"),
    )
    derive_manual_lead_context(project_root, lead_id=ingestion.lead_id)

    first = materialize_manual_lead_entities(project_root, lead_id=ingestion.lead_id)
    second = materialize_manual_lead_entities(project_root, lead_id=ingestion.lead_id)

    connection = connect_database(project_root / "job_hunt_copilot.db")
    counts = {
        "job_postings": connection.execute(
            "SELECT COUNT(*) FROM job_postings WHERE lead_id = ?",
            (ingestion.lead_id,),
        ).fetchone()[0],
        "contacts": connection.execute(
            """
            SELECT COUNT(*)
            FROM contacts
            WHERE company_name = 'Guidewire Software'
              AND display_name = 'Alex Kordun'
            """
        ).fetchone()[0],
        "linkedin_lead_contacts": connection.execute(
            "SELECT COUNT(*) FROM linkedin_lead_contacts WHERE lead_id = ?",
            (ingestion.lead_id,),
        ).fetchone()[0],
        "job_posting_contacts": connection.execute(
            "SELECT COUNT(*) FROM job_posting_contacts WHERE job_posting_id = ?",
            (first.job_posting_id,),
        ).fetchone()[0],
        "lead_manifest_artifacts": connection.execute(
            """
            SELECT COUNT(*)
            FROM artifact_records
            WHERE lead_id = ? AND artifact_type = 'lead_manifest'
            """,
            (ingestion.lead_id,),
        ).fetchone()[0],
    }
    connection.close()

    assert first.job_posting_id == second.job_posting_id
    assert first.contact_id == second.contact_id
    assert first.linkedin_lead_contact_id == second.linkedin_lead_contact_id
    assert first.job_posting_contact_id == second.job_posting_contact_id
    assert first.job_posting_created is True
    assert second.job_posting_created is False
    assert first.contact_created is True
    assert second.contact_created is False
    assert counts == {
        "job_postings": 1,
        "contacts": 1,
        "linkedin_lead_contacts": 1,
        "job_posting_contacts": 1,
        "lead_manifest_artifacts": 1,
    }


def test_founder_title_is_preserved_as_a_first_class_recipient_type(tmp_path):
    project_root = bootstrap_project(tmp_path)

    ingestion = ingest_manual_capture_submission(
        project_root,
        submission=build_materializable_submission(
            submission_id="manual-submission-materialize-founder",
            poster_name="Jordan Vale",
            poster_title="Co-Founder & CTO",
            profile_source_url="https://www.linkedin.com/in/jordan-vale/",
        ),
    )
    derive_manual_lead_context(project_root, lead_id=ingestion.lead_id)
    materialized = materialize_manual_lead_entities(project_root, lead_id=ingestion.lead_id)

    connection = connect_database(project_root / "job_hunt_copilot.db")
    lead_contact_row = connection.execute(
        """
        SELECT recipient_type_inferred
        FROM linkedin_lead_contacts
        WHERE linkedin_lead_contact_id = ?
        """,
        (materialized.linkedin_lead_contact_id,),
    ).fetchone()
    posting_contact_row = connection.execute(
        """
        SELECT recipient_type
        FROM job_posting_contacts
        WHERE job_posting_contact_id = ?
        """,
        (materialized.job_posting_contact_id,),
    ).fetchone()
    connection.close()

    assert materialized.materialized is True
    assert lead_contact_row["recipient_type_inferred"] == "founder"
    assert posting_contact_row["recipient_type"] == "founder"
