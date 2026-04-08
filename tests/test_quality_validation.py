from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from job_hunt_copilot.blocker_audit import VALIDATION_COMMANDS
from job_hunt_copilot.quality_validation import (
    AUTOMATED_VALIDATION_KIND,
    VALIDATION_SUITE_REPORT_JSON_PATH,
    VALIDATION_SUITE_REPORT_MD_PATH,
    build_smoke_validation_plan,
    build_ba10_validation_suite_report,
    build_quality_validation_plan,
    list_smoke_validation_targets,
    render_ba10_validation_suite_markdown,
    resolve_acceptance_gap_validation_command_ids,
    resolve_current_focus_validation_command_ids,
    write_ba10_validation_suite_reports,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_default_quality_validation_plan_uses_only_automated_commands_in_registry_order():
    plan = build_quality_validation_plan()

    expected_command_ids = [
        command_id
        for command_id, metadata in VALIDATION_COMMANDS.items()
        if metadata["kind"] == AUTOMATED_VALIDATION_KIND
    ]

    assert [command.command_id for command in plan] == expected_command_ids
    assert all(command.kind == AUTOMATED_VALIDATION_KIND for command in plan)


def test_quality_validation_plan_rejects_manual_commands_by_default():
    with pytest.raises(ValueError, match="requires `include_manual=True`"):
        build_quality_validation_plan(["qa_host_launchd_validation"])


def test_quality_validation_plan_accepts_manual_commands_when_enabled():
    plan = build_quality_validation_plan(
        ["qa_codex_cli_compatibility", "qa_host_launchd_validation"],
        include_manual=True,
    )

    assert [command.command_id for command in plan] == [
        "qa_codex_cli_compatibility",
        "qa_host_launchd_validation",
    ]


def test_smoke_validation_targets_cover_required_flow_boundaries():
    targets = list_smoke_validation_targets()

    assert [target.target_id for target in targets] == [
        "bootstrap",
        "tailoring",
        "discovery",
        "send",
        "feedback",
        "review_query",
    ]
    for target in targets:
        assert target.acceptance_scenario == "Build smoke test passes"
        assert target.acceptance_checks
        assert target.validation_command_ids
        assert "tests/test_smoke_harness.py" in target.test_refs


def test_smoke_validation_plan_dedupes_shared_smoke_command_and_preserves_registry_order():
    plan = build_smoke_validation_plan(["feedback", "review_query"])

    assert [command.command_id for command in plan] == [
        "qa_smoke_flow",
        "qa_feedback_regressions",
        "qa_review_surface_regressions",
    ]


def test_gap_validation_command_resolution_follows_open_gap_command_mapping():
    command_ids = resolve_acceptance_gap_validation_command_ids(
        REPO_ROOT, ["BA10_SUPERVISOR_DOWNSTREAM_ACTION_CATALOG"]
    )

    assert command_ids == [
        "qa_supervisor_regressions",
        "qa_acceptance_reports",
    ]


def test_current_focus_validation_command_resolution_follows_active_slice():
    command_ids = resolve_current_focus_validation_command_ids(REPO_ROOT)

    assert command_ids == [
        "qa_supervisor_regressions",
        "qa_acceptance_reports",
    ]


def test_quality_validation_suite_script_dry_run_reports_selected_commands():
    result = subprocess.run(
        [
            sys.executable,
            "scripts/quality/run_ba10_validation_suite.py",
            "--project-root",
            str(REPO_ROOT),
            "--dry-run",
            "--command-id",
            "qa_smoke_flow",
            "--command-id",
            "qa_runtime_pack_regressions",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["project_root"] == str(REPO_ROOT)
    assert payload["refreshed_reports"] is False
    assert payload["requested_gap_ids"] == []
    assert payload["requested_blocker_ids"] == []
    assert payload["requested_current_focus"] is False
    assert [command["command_id"] for command in payload["commands"]] == [
        "qa_smoke_flow",
        "qa_runtime_pack_regressions",
    ]
    assert payload["requested_smoke_targets"] == []


def test_quality_validation_suite_script_rejects_manual_commands_without_flag():
    result = subprocess.run(
        [
            sys.executable,
            "scripts/quality/run_ba10_validation_suite.py",
            "--project-root",
            str(REPO_ROOT),
            "--dry-run",
            "--command-id",
            "qa_host_launchd_validation",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "requires `include_manual=True`" in result.stderr


def test_quality_validation_suite_script_dry_run_expands_gap_ids():
    result = subprocess.run(
        [
            sys.executable,
            "scripts/quality/run_ba10_validation_suite.py",
            "--project-root",
            str(REPO_ROOT),
            "--dry-run",
            "--gap-id",
            "BA10_SUPERVISOR_DOWNSTREAM_ACTION_CATALOG",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["requested_gap_ids"] == ["BA10_SUPERVISOR_DOWNSTREAM_ACTION_CATALOG"]
    assert payload["requested_blocker_ids"] == []
    assert payload["requested_current_focus"] is False
    assert [command["command_id"] for command in payload["commands"]] == [
        "qa_supervisor_regressions",
        "qa_acceptance_reports",
    ]


def test_quality_validation_suite_script_rejects_manual_blocker_without_flag():
    result = subprocess.run(
        [
            sys.executable,
            "scripts/quality/run_ba10_validation_suite.py",
            "--project-root",
            str(REPO_ROOT),
            "--dry-run",
            "--blocker-id",
            "BUILD-CLI-001",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "requires `include_manual=True`" in result.stderr


def test_quality_validation_suite_script_dry_run_expands_current_focus():
    result = subprocess.run(
        [
            sys.executable,
            "scripts/quality/run_ba10_validation_suite.py",
            "--project-root",
            str(REPO_ROOT),
            "--dry-run",
            "--current-focus",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["requested_gap_ids"] == []
    assert payload["requested_blocker_ids"] == []
    assert payload["requested_current_focus"] is True
    assert [command["command_id"] for command in payload["commands"]] == [
        "qa_supervisor_regressions",
        "qa_acceptance_reports",
    ]


def test_quality_validation_suite_script_dry_run_expands_smoke_targets():
    result = subprocess.run(
        [
            sys.executable,
            "scripts/quality/run_ba10_validation_suite.py",
            "--project-root",
            str(REPO_ROOT),
            "--dry-run",
            "--smoke-target",
            "bootstrap",
            "--smoke-target",
            "feedback",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["requested_smoke_targets"] == ["bootstrap", "feedback"]
    assert [command["command_id"] for command in payload["commands"]] == [
        "qa_smoke_flow",
        "qa_bootstrap_regressions",
        "qa_feedback_regressions",
    ]


def test_build_ba10_validation_suite_report_summarizes_results():
    report = build_ba10_validation_suite_report(
        {
            "project_root": str(REPO_ROOT),
            "refreshed_reports": False,
            "requested_command_ids": ["qa_smoke_flow"],
            "requested_gap_ids": ["BA10_SUPERVISOR_DOWNSTREAM_ACTION_CATALOG"],
            "requested_blocker_ids": [],
            "requested_current_focus": True,
            "requested_smoke_targets": ["bootstrap"],
            "include_manual": True,
            "skip_report_refresh": False,
            "commands": [
                {
                    "command_id": "qa_smoke_flow",
                    "title": "Smoke harness flow",
                    "kind": "automated",
                    "command": "python3.11 -m pytest tests/test_smoke_harness.py",
                    "description": "Replays the smoke path.",
                    "status": "passed",
                    "returncode": 0,
                    "duration_seconds": 1.25,
                },
                {
                    "command_id": "qa_host_launchd_validation",
                    "title": "Host launchd validation",
                    "kind": "manual_host",
                    "command": "bin/jhc-agent-start && launchctl print gui/$UID/com.jobhuntcopilot.supervisor",
                    "description": "Checks launchd on the host.",
                    "status": "failed",
                    "returncode": 1,
                    "duration_seconds": 0.5,
                },
            ],
            "failed_command_ids": ["qa_host_launchd_validation"],
            "passed": False,
        },
        generated_at="2026-04-08T21:00:00Z",
    )

    assert report["validation_suite_report_version"] == 1
    assert report["generated_at"] == "2026-04-08T21:00:00Z"
    assert report["summary"] == {
        "command_count": 2,
        "command_kind_counts": {
            "automated": 1,
            "manual_host": 1,
        },
        "passed_command_count": 1,
        "failed_command_count": 1,
        "total_duration_seconds": 1.75,
    }

    markdown = render_ba10_validation_suite_markdown(report)
    assert "# BA-10 Validation Suite Report" in markdown
    assert "- Command ids: `qa_smoke_flow`" in markdown
    assert "- Acceptance gaps: `BA10_SUPERVISOR_DOWNSTREAM_ACTION_CATALOG`" in markdown
    assert "- Failed command ids: `qa_host_launchd_validation`" in markdown
    assert "| qa_smoke_flow | automated | passed | 0 | 1.250 |" in markdown
    assert "### qa_host_launchd_validation: Host launchd validation" in markdown


def test_write_ba10_validation_suite_reports_persists_json_and_markdown(tmp_path: Path):
    report = write_ba10_validation_suite_reports(
        tmp_path,
        {
            "project_root": str(tmp_path),
            "refreshed_reports": {
                "acceptance_trace_reports": {
                    "json_path": "/tmp/acceptance.json",
                    "markdown_path": "/tmp/acceptance.md",
                },
                "blocker_audit_reports": {
                    "json_path": "/tmp/blocker.json",
                    "markdown_path": "/tmp/blocker.md",
                },
            },
            "requested_command_ids": [],
            "requested_gap_ids": [],
            "requested_blocker_ids": ["OPS-LAUNCHD-001"],
            "requested_current_focus": False,
            "requested_smoke_targets": ["feedback"],
            "include_manual": False,
            "skip_report_refresh": False,
            "commands": [
                {
                    "command_id": "qa_feedback_regressions",
                    "title": "Delivery feedback regressions",
                    "kind": "automated",
                    "command": "python3.11 -m pytest tests/test_delivery_feedback.py",
                    "description": "Confirms delayed-feedback persistence.",
                    "status": "passed",
                    "returncode": 0,
                    "duration_seconds": 2.0,
                }
            ],
            "failed_command_ids": [],
            "passed": True,
        },
    )

    json_path = tmp_path / VALIDATION_SUITE_REPORT_JSON_PATH
    md_path = tmp_path / VALIDATION_SUITE_REPORT_MD_PATH

    assert report["report_paths"] == {
        "json_path": str(json_path),
        "markdown_path": str(md_path),
    }
    assert json.loads(json_path.read_text(encoding="utf-8")) == report

    markdown = md_path.read_text(encoding="utf-8")
    assert "## Refreshed Reports" in markdown
    assert "- Build-board blockers: `OPS-LAUNCHD-001`" in markdown
    assert "- Smoke targets: `feedback`" in markdown
    assert "### qa_feedback_regressions: Delivery feedback regressions" in markdown
