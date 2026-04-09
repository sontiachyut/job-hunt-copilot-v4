from __future__ import annotations

import json
from pathlib import Path

from job_hunt_copilot.blocker_audit import VALIDATION_COMMANDS
from job_hunt_copilot.repo_readiness import (
    REPORT_JSON_PATH,
    REPORT_MD_PATH,
    build_repo_readiness_report,
    render_repo_readiness_markdown,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_repo_readiness_reports_are_current_and_repo_surfaces_are_honest():
    report = build_repo_readiness_report(REPO_ROOT)
    generated_markdown = render_repo_readiness_markdown(report)

    committed_json = json.loads((REPO_ROOT / REPORT_JSON_PATH).read_text(encoding="utf-8"))
    committed_markdown = (REPO_ROOT / REPORT_MD_PATH).read_text(encoding="utf-8")

    assert committed_json == report
    assert committed_markdown == generated_markdown
    assert report["surface_status"] == "current"
    assert report["current_focus"]["slice_id"] == "BA-10-S3"
    assert report["acceptance_status"]["open_gap_ids"] == [
        "BA10_MAINTENANCE_AUTOMATION",
        "BA10_CHAT_REVIEW_AND_CONTROL",
    ]

    latest_validation = report["latest_validation"]
    assert latest_validation["available"] is True
    assert latest_validation["report_paths"]["markdown_path"].endswith(
        "build-agent/reports/ba-10-validation-suite-latest.md"
    )

    for path_text in report["recommended_review_path"]:
        assert (REPO_ROOT / path_text).exists(), path_text

    for surface in report["repo_surfaces"]:
        assert (REPO_ROOT / surface["path"]).exists(), surface["path"]
        assert surface["status"] == "current"
        assert surface["missing_snippets"] == []
        assert surface["missing_gap_titles"] == []

    readme_surface = next(
        surface for surface in report["repo_surfaces"] if surface["path"] == "README.md"
    )
    assert readme_surface["requires_open_gap_titles"] is True
    assert readme_surface["required_gap_titles"] == [
        "Maintenance workflow and artifacts are not implemented",
        "Chat review and control are still missing deeper expert-guidance workflows",
    ]

    architecture_surface = next(
        surface
        for surface in report["repo_surfaces"]
        if surface["path"] == "docs/ARCHITECTURE.md"
    )
    assert architecture_surface["requires_open_gap_titles"] is True
    assert architecture_surface["required_gap_titles"] == [
        "Maintenance workflow and artifacts are not implemented",
        "Chat review and control are still missing deeper expert-guidance workflows",
    ]

    reports_index_surface = next(
        surface
        for surface in report["repo_surfaces"]
        if surface["path"] == "build-agent/reports/README.md"
    )
    assert reports_index_surface["requires_open_gap_titles"] is False
    assert reports_index_surface["required_gap_titles"] == []

    assert (
        "tests/test_repo_readiness.py"
        in VALIDATION_COMMANDS["qa_acceptance_reports"]["command"]
    )
