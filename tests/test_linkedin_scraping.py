from __future__ import annotations

import json
import sqlite3

from job_hunt_copilot.bootstrap import run_bootstrap
from job_hunt_copilot.linkedin_scraping import (
    SUBMISSION_PATH_IMMEDIATE_SELECTED_TEXT,
    SUBMISSION_PATH_TRAY_REVIEW,
    ingest_manual_capture_submission,
    ingest_paste_inbox,
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
