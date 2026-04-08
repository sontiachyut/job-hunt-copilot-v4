from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from job_hunt_copilot.blocker_audit import VALIDATION_COMMANDS
from job_hunt_copilot.quality_validation import (
    AUTOMATED_VALIDATION_KIND,
    build_smoke_validation_plan,
    build_quality_validation_plan,
    list_smoke_validation_targets,
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
