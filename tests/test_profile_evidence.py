from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from job_hunt_copilot.bootstrap import run_bootstrap
from job_hunt_copilot.paths import ProjectPaths
from job_hunt_copilot.profile_evidence import (
    ProfileEvidenceBuildError,
    ProfileEvidenceRetrievalError,
    build_profile_evidence_corpus,
    retrieve_managerial_profile_evidence,
)
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


def test_build_profile_evidence_corpus_refreshes_sqlite_and_mirror(tmp_path: Path) -> None:
    project_root, paths = bootstrap_project(tmp_path)
    connection = connect_database(project_root / "job_hunt_copilot.db")

    result = build_profile_evidence_corpus(connection, paths)

    count = connection.execute("SELECT COUNT(*) FROM profile_evidence_chunks").fetchone()[0]
    mirror_payload = json.loads(paths.profile_evidence_mirror_json_path.read_text(encoding="utf-8"))
    connection.close()

    assert result.chunk_count == count == 3
    assert mirror_payload["source_path"] == "assets/outreach/managerial-profile-evidence.yaml"
    assert len(mirror_payload["chunks"]) == 3
    assert mirror_payload["chunks"][0]["evidence_id"] == "exp_hl7_scale"


def test_build_profile_evidence_corpus_rejects_duplicate_ids(tmp_path: Path) -> None:
    project_root, paths = bootstrap_project(tmp_path)
    paths.managerial_profile_evidence_source_path.write_text(
        "\n".join(
            [
                "chunks:",
                "  - evidence_id: dup_signal",
                "    text: First chunk.",
                "    source_type: resume_experience",
                "    evidence_type: achievement",
                "    skill_tags: [python]",
                "    theme_tags: [backend]",
                "    strength: 4",
                "  - evidence_id: dup_signal",
                "    text: Second chunk.",
                "    source_type: resume_project",
                "    evidence_type: project",
                "    skill_tags: [fastapi]",
                "    theme_tags: [ai]",
                "    strength: 3",
                "",
            ]
        ),
        encoding="utf-8",
    )
    connection = connect_database(project_root / "job_hunt_copilot.db")

    with pytest.raises(ProfileEvidenceBuildError, match="Duplicate evidence_id"):
        build_profile_evidence_corpus(connection, paths)

    connection.close()


def test_retrieve_managerial_profile_evidence_demotes_generic_reliability_for_ai_workflow_roles(
    tmp_path: Path,
) -> None:
    project_root, paths = bootstrap_project(tmp_path)
    paths.managerial_profile_evidence_source_path.write_text(
        "\n".join(
            [
                "chunks:",
                "  - evidence_id: ai_workflow_delivery",
                "    text: Built AI workflow automation for multi-step operational tasks with human-in-the-loop review.",
                "    source_type: job_hunt_copilot",
                "    evidence_type: project",
                "    skill_tags: [python, ai-agents, workflow-automation]",
                "    theme_tags: [ai, workflow-automation, production-workflows]",
                "    strength: 4",
                "  - evidence_id: stakeholder_enablement",
                "    text: Led applied AI workshops and enablement sessions for graduate students focused on practical product-building workflows.",
                "    source_type: education",
                "    evidence_type: stakeholder",
                "    skill_tags: [applied-ai, workshops, communication]",
                "    theme_tags: [ai, stakeholder-enablement, coaching]",
                "    strength: 4",
                "  - evidence_id: ai_delivery_system",
                "    text: Built backend workflow systems in Python and Scala that shipped governed analytics outputs for production users.",
                "    source_type: resume_experience",
                "    evidence_type: system",
                "    skill_tags: [python, scala, backend-apis, analytics-delivery]",
                "    theme_tags: [backend, data, workflow-automation, production-systems]",
                "    strength: 5",
                "  - evidence_id: generic_reliability",
                "    text: Maintained uptime with monitoring, alerting, and incident triage in production workflows.",
                "    source_type: resume_experience",
                "    evidence_type: reliability",
                "    skill_tags: [monitoring, alerting, incident-response]",
                "    theme_tags: [reliability, observability, production-systems]",
                "    strength: 5",
                "  - evidence_id: cloud_scale",
                "    text: Processed 50M+ daily records through distributed production systems on Azure and Spark.",
                "    source_type: resume_experience",
                "    evidence_type: achievement",
                "    skill_tags: [azure, spark, python, scala]",
                "    theme_tags: [data, distributed, cloud, production-systems]",
                "    strength: 5",
                "",
            ]
        ),
        encoding="utf-8",
    )
    connection = connect_database(project_root / "job_hunt_copilot.db")
    build_profile_evidence_corpus(connection, paths)

    selection = retrieve_managerial_profile_evidence(
        connection,
        role_title="AI/ML Engineer - Associate Consultant",
        role_theme="client-facing AI workflow delivery and stakeholder enablement",
        bounded_jd_relevance_pack=(
            {
                "jd_signal": "turning generative AI ideas into usable client workflows",
                "supporting_line": "turning generative AI ideas into usable client workflows",
                "theme_tags": ["ai", "workflow-automation", "stakeholder-enablement"],
            },
            {
                "jd_signal": "stakeholder coaching and enablement around new AI capabilities",
                "supporting_line": "stakeholder coaching and enablement around new AI capabilities",
                "theme_tags": ["ai", "stakeholder-enablement"],
            },
        ),
    )
    connection.close()

    prompt_ids = [chunk.evidence_id for chunk in selection.prompt_chunks]
    assert "ai_workflow_delivery" in prompt_ids
    assert "stakeholder_enablement" in prompt_ids
    assert "ai_delivery_system" in prompt_ids
    assert "generic_reliability" not in prompt_ids


def test_retrieve_managerial_profile_evidence_fails_closed_with_only_two_strong_chunks(
    tmp_path: Path,
) -> None:
    project_root, paths = bootstrap_project(tmp_path)
    paths.managerial_profile_evidence_source_path.write_text(
        "\n".join(
            [
                "chunks:",
                "  - evidence_id: strong_ai_workflow",
                "    text: Built AI workflow automation in production systems.",
                "    source_type: job_hunt_copilot",
                "    evidence_type: project",
                "    skill_tags: [python, ai-agents, workflow-automation]",
                "    theme_tags: [ai, workflow-automation, production-workflows]",
                "    strength: 4",
                "  - evidence_id: strong_backend_delivery",
                "    text: Built backend data systems in Python and Scala for production analytics delivery.",
                "    source_type: resume_experience",
                "    evidence_type: system",
                "    skill_tags: [python, scala, backend-apis, analytics-delivery]",
                "    theme_tags: [backend, data, production-systems]",
                "    strength: 5",
                "  - evidence_id: weak_generic_school",
                "    text: Completed graduate coursework in computer science.",
                "    source_type: education",
                "    evidence_type: skill_anchor",
                "    skill_tags: [computer-science]",
                "    theme_tags: [education]",
                "    strength: 1",
                "",
            ]
        ),
        encoding="utf-8",
    )
    connection = connect_database(project_root / "job_hunt_copilot.db")
    build_profile_evidence_corpus(connection, paths)

    with pytest.raises(ProfileEvidenceRetrievalError, match="three grounded evidence chunks"):
        retrieve_managerial_profile_evidence(
            connection,
            role_title="GenAI Workflow Engineer",
            role_theme="production AI workflow delivery",
            bounded_jd_relevance_pack=(
                {
                    "jd_signal": "shipping AI workflows into production",
                    "supporting_line": "shipping AI workflows into production",
                    "theme_tags": ["ai", "workflow-automation"],
                },
            ),
        )

    connection.close()
