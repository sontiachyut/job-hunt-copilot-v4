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
    ]

    latest_validation = report["latest_validation"]
    assert latest_validation["available"] is True
    assert latest_validation["selector_label"] == "current_focus"
    assert latest_validation["selector_summary"] == {
        "requested_command_ids": [],
        "requested_smoke_targets": [],
        "requested_gap_ids": [],
        "requested_blocker_ids": [],
        "requested_current_focus": True,
    }
    assert latest_validation["tracks_current_focus"] is True
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
    ]

    architecture_surface = next(
        surface
        for surface in report["repo_surfaces"]
        if surface["path"] == "docs/ARCHITECTURE.md"
    )
    assert architecture_surface["requires_open_gap_titles"] is True
    assert architecture_surface["required_gap_titles"] == [
        "Maintenance workflow and artifacts are not implemented",
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


def test_repo_readiness_marks_latest_validation_as_custom_when_it_does_not_track_current_focus():
    report = build_repo_readiness_report(
        REPO_ROOT,
        validation_suite_report={
            "generated_at": "2026-04-09T20:15:00Z",
            "passed": True,
            "summary": {
                "command_count": 11,
                "failed_command_count": 0,
            },
            "report_paths": {
                "json_path": str(REPO_ROOT / "build-agent/reports/ba-10-validation-suite-latest.json"),
                "markdown_path": str(REPO_ROOT / "build-agent/reports/ba-10-validation-suite-latest.md"),
            },
            "requested_command_ids": [],
            "requested_smoke_targets": [],
            "requested_gap_ids": [],
            "requested_blocker_ids": ["BA10-TRACE-001"],
            "requested_current_focus": False,
            "selector_details": {
                "smoke_targets": [],
                "acceptance_gaps": [],
                "build_board_blockers": [
                    {
                        "blocker_id": "BA10-TRACE-001",
                    }
                ],
                "current_focus": None,
            },
        },
    )

    assert report["latest_validation"]["selector_summary"] == {
        "requested_command_ids": [],
        "requested_smoke_targets": [],
        "requested_gap_ids": [],
        "requested_blocker_ids": ["BA10-TRACE-001"],
        "requested_current_focus": False,
    }
    assert report["latest_validation"]["selector_label"] == "blockers: BA10-TRACE-001"
    assert report["latest_validation"]["tracks_current_focus"] is False
