from __future__ import annotations

import json
import sqlite3

import pytest
import yaml

from job_hunt_copilot.artifacts import (
    ArtifactLinkage,
    artifact_location,
    build_contract_envelope,
    publish_json_artifact,
    publish_yaml_artifact,
)
from job_hunt_copilot.bootstrap import run_bootstrap
from job_hunt_copilot.paths import ProjectPaths, workspace_slug
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


def seed_artifact_lineage(connection, timestamp: str = "2026-04-05T22:00:00Z") -> ArtifactLinkage:
    connection.execute(
        """
        INSERT INTO linkedin_leads (
          lead_id, lead_identity_key, lead_status, lead_shape, split_review_status,
          source_type, source_reference, source_mode, company_name, role_title,
          created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "ld_test",
            "guidewire|staff-software-engineer",
            "reviewed",
            "posting_plus_contacts",
            "confident",
            "gmail_job_alert",
            "gmail/message/123",
            "gmail_job_alert",
            "Guidewire Software, Inc.",
            "Staff Software Engineer / AI",
            timestamp,
            timestamp,
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
            "jp_test",
            "ld_test",
            "guidewire|staff-software-engineer-ai|remote",
            "Guidewire Software, Inc.",
            "Staff Software Engineer / AI",
            "requires_contacts",
            timestamp,
            timestamp,
        ),
    )
    connection.execute(
        """
        INSERT INTO contacts (
          contact_id, identity_key, display_name, company_name, origin_component,
          contact_status, full_name, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "ct_test",
            "alex-kordun|guidewire",
            "Alex Kordun",
            "Guidewire Software, Inc.",
            "discovery",
            "selected",
            "Alex Kordun",
            timestamp,
            timestamp,
        ),
    )
    connection.execute(
        """
        INSERT INTO outreach_messages (
          outreach_message_id, contact_id, outreach_mode, recipient_email, message_status,
          job_posting_id, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "msg_test",
            "ct_test",
            "role_targeted",
            "alex@example.com",
            "drafted",
            "jp_test",
            timestamp,
            timestamp,
        ),
    )
    connection.commit()
    return ArtifactLinkage(
        lead_id="ld_test",
        job_posting_id="jp_test",
        contact_id="ct_test",
        outreach_message_id="msg_test",
    )


def test_project_path_helpers_follow_canonical_component_layout(tmp_path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)

    assert workspace_slug("Guidewire Software, Inc.") == "guidewire-software-inc"
    assert workspace_slug("Staff Software Engineer / AI") == "staff-software-engineer-ai"
    assert paths.lead_workspace_dir(
        "Guidewire Software, Inc.",
        "Staff Software Engineer / AI",
        "ld_test",
    ) == (
        project_root
        / "linkedin-scraping"
        / "runtime"
        / "leads"
        / "guidewire-software-inc"
        / "staff-software-engineer-ai"
        / "ld_test"
    )
    assert paths.application_workspace_dir(
        "Guidewire Software, Inc.",
        "Staff Software Engineer / AI",
    ) == (
        project_root
        / "applications"
        / "guidewire-software-inc"
        / "staff-software-engineer-ai"
    )
    assert paths.tailoring_workspace_dir(
        "Guidewire Software, Inc.",
        "Staff Software Engineer / AI",
    ) == (
        project_root
        / "resume-tailoring"
        / "output"
        / "tailored"
        / "guidewire-software-inc"
        / "staff-software-engineer-ai"
    )
    assert paths.discovery_workspace_dir(
        "Guidewire Software, Inc.",
        "Staff Software Engineer / AI",
    ) == (
        project_root
        / "discovery"
        / "output"
        / "guidewire-software-inc"
        / "staff-software-engineer-ai"
    )
    assert paths.outreach_workspace_dir(
        "Guidewire Software, Inc.",
        "Staff Software Engineer / AI",
    ) == (
        project_root
        / "outreach"
        / "output"
        / "guidewire-software-inc"
        / "staff-software-engineer-ai"
    )


def test_publish_contract_artifacts_writes_shared_envelope_and_registry_rows(tmp_path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    connection = connect_database(project_root / "job_hunt_copilot.db")
    linkage = seed_artifact_lineage(connection)

    lead_manifest = publish_yaml_artifact(
        connection,
        paths,
        artifact_type="lead_manifest",
        artifact_path=paths.lead_workspace_dir(
            "Guidewire Software, Inc.",
            "Staff Software Engineer / AI",
            "ld_test",
        )
        / "lead-manifest.yaml",
        producer_component="linkedin_scraping",
        result="ok",
        linkage=ArtifactLinkage(lead_id=linkage.lead_id, job_posting_id=linkage.job_posting_id),
        payload={
            "lead_status": "ready_for_tailoring",
            "jd_artifact_ref": paths.relative_to_root(
                paths.lead_workspace_dir(
                    "Guidewire Software, Inc.",
                    "Staff Software Engineer / AI",
                    "ld_test",
                )
                / "jd.md"
            ).as_posix(),
        },
        produced_at="2026-04-05T22:05:00Z",
    )
    discovery_result = publish_json_artifact(
        connection,
        paths,
        artifact_type="discovery_result",
        artifact_path=paths.discovery_workspace_dir(
            "Guidewire Software, Inc.",
            "Staff Software Engineer / AI",
        )
        / "discovery_result.json",
        producer_component="discovery",
        result="ok",
        linkage=ArtifactLinkage(
            job_posting_id=linkage.job_posting_id,
            contact_id=linkage.contact_id,
        ),
        payload={
            "discovery_outcome": "email_found",
            "email": "alex@example.com",
            "recipient_profile_artifact_ref": "discovery/output/guidewire-software-inc/staff-software-engineer-ai/recipient-profiles/ct_test/recipient_profile.json",
        },
        produced_at="2026-04-05T22:06:00Z",
    )

    manifest_payload = yaml.safe_load(lead_manifest.location.absolute_path.read_text(encoding="utf-8"))
    discovery_payload = json.loads(discovery_result.location.absolute_path.read_text(encoding="utf-8"))
    records = connection.execute(
        """
        SELECT artifact_type, file_path, producer_component, lead_id, job_posting_id, contact_id, outreach_message_id, created_at
        FROM artifact_records
        ORDER BY created_at, artifact_type
        """
    ).fetchall()
    connection.close()

    assert manifest_payload == {
        "contract_version": "1.0",
        "produced_at": "2026-04-05T22:05:00Z",
        "producer_component": "linkedin_scraping",
        "result": "ok",
        "lead_id": "ld_test",
        "job_posting_id": "jp_test",
        "lead_status": "ready_for_tailoring",
        "jd_artifact_ref": "linkedin-scraping/runtime/leads/guidewire-software-inc/staff-software-engineer-ai/ld_test/jd.md",
    }
    assert discovery_payload == {
        "contract_version": "1.0",
        "produced_at": "2026-04-05T22:06:00Z",
        "producer_component": "discovery",
        "result": "ok",
        "job_posting_id": "jp_test",
        "contact_id": "ct_test",
        "discovery_outcome": "email_found",
        "email": "alex@example.com",
        "recipient_profile_artifact_ref": "discovery/output/guidewire-software-inc/staff-software-engineer-ai/recipient-profiles/ct_test/recipient_profile.json",
    }
    assert [dict(row) for row in records] == [
        {
            "artifact_type": "lead_manifest",
            "file_path": "linkedin-scraping/runtime/leads/guidewire-software-inc/staff-software-engineer-ai/ld_test/lead-manifest.yaml",
            "producer_component": "linkedin_scraping",
            "lead_id": "ld_test",
            "job_posting_id": "jp_test",
            "contact_id": None,
            "outreach_message_id": None,
            "created_at": "2026-04-05T22:05:00Z",
        },
        {
            "artifact_type": "discovery_result",
            "file_path": "discovery/output/guidewire-software-inc/staff-software-engineer-ai/discovery_result.json",
            "producer_component": "discovery",
            "lead_id": None,
            "job_posting_id": "jp_test",
            "contact_id": "ct_test",
            "outreach_message_id": None,
            "created_at": "2026-04-05T22:06:00Z",
        },
    ]


def test_artifact_contract_helpers_enforce_failure_reason_fields(tmp_path):
    project_root = bootstrap_project(tmp_path)
    paths = ProjectPaths.from_root(project_root)
    blocked_path = paths.outreach_workspace_dir("Guidewire", "Platform Engineer") / "send_result.json"

    with pytest.raises(ValueError):
        build_contract_envelope(
            producer_component="outreach",
            result="blocked",
            linkage=ArtifactLinkage(job_posting_id="jp_test", contact_id="ct_test"),
            payload={"send_status": "blocked"},
        )

    contract = build_contract_envelope(
        producer_component="outreach",
        result="blocked",
        linkage=ArtifactLinkage(
            job_posting_id="jp_test",
            contact_id="ct_test",
            outreach_message_id="msg_test",
        ),
        payload={"send_status": "blocked"},
        reason_code="missing_email",
        message="No deliverable email address was available.",
        produced_at="2026-04-05T22:07:00Z",
    )

    assert contract == {
        "contract_version": "1.0",
        "produced_at": "2026-04-05T22:07:00Z",
        "producer_component": "outreach",
        "result": "blocked",
        "job_posting_id": "jp_test",
        "contact_id": "ct_test",
        "outreach_message_id": "msg_test",
        "send_status": "blocked",
        "reason_code": "missing_email",
        "message": "No deliverable email address was available.",
    }

    location = artifact_location(paths, blocked_path)
    assert location.relative_path == "outreach/output/guidewire/platform-engineer/send_result.json"
