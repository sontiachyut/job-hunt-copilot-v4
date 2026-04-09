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
    resolve_validation_selector_details,
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


def test_validation_selector_details_include_requested_smoke_gap_blocker_and_current_focus_context():
    details = resolve_validation_selector_details(
        REPO_ROOT,
        smoke_target_ids=["bootstrap", "feedback"],
        gap_ids=["BA10_MAINTENANCE_AUTOMATION"],
        blocker_ids=["BA10-TRACE-001"],
        include_current_focus=True,
    )

    assert [target["target_id"] for target in details["smoke_targets"]] == [
        "bootstrap",
        "feedback",
    ]
    assert details["smoke_targets"][0]["validation_command_ids"] == [
        "qa_smoke_flow",
        "qa_bootstrap_regressions",
    ]
    assert details["acceptance_gaps"][0] == {
        "gap_id": "BA10_MAINTENANCE_AUTOMATION",
        "title": "Maintenance workflow and artifacts are not implemented",
        "next_slice": "BA-10-S3",
        "open_scenario_count": 6,
        "status_counts": {
            "partial": 1,
            "gap": 5,
        },
        "validation_command_ids": [
            "qa_runtime_pack_regressions",
            "qa_acceptance_reports",
            "qa_supervisor_regressions",
        ],
        "validation_suite_command": (
            "python3.11 scripts/quality/run_ba10_validation_suite.py "
            "--project-root <repo_root> --gap-id BA10_MAINTENANCE_AUTOMATION"
        ),
        "open_scenarios": [
            {
                "name": "Maintenance change artifacts exist for every autonomous maintenance batch",
                "status": "gap",
                "rule": "Machine handoff contracts and canonical state",
                "scenario_line": 220,
                "note": "Maintenance artifacts are specified in the schema and PRD, but no maintenance batch workflow writes them yet.",
            },
            {
                "name": "Supervisor work selection follows the current default priority order",
                "status": "partial",
                "rule": "Supervisor Agent behavior",
                "scenario_line": 1132,
                "note": "Current supervisor regressions prove open incidents outrank ordinary pipeline advancement, existing runs outrank new posting bootstrap, new postings outrank opportunistic contact-rooted general-learning work, and contact-rooted general-learning work now covers bounded delayed feedback, send-ready dispatch, and email discovery, but bounded maintenance work itself still has no dedicated selector or action path.",
            },
            {
                "name": "Daily maintenance is mandatory, bounded, and run-boundary aware",
                "status": "gap",
                "rule": "Supervisor Agent behavior",
                "scenario_line": 1322,
                "note": "Only maintenance placeholders exist today; the maintenance workflow itself is still missing.",
            },
            {
                "name": "Maintenance changes follow the current git and approval workflow",
                "status": "gap",
                "rule": "Supervisor Agent behavior",
                "scenario_line": 1331,
                "note": "Only maintenance placeholders exist today; the maintenance workflow itself is still missing.",
            },
            {
                "name": "Proper maintenance validation requires both change-scoped and full-project testing",
                "status": "gap",
                "rule": "Supervisor Agent behavior",
                "scenario_line": 1342,
                "note": "Only maintenance placeholders exist today; the maintenance workflow itself is still missing.",
            },
            {
                "name": "Failed or unapproved maintenance batches remain reviewable",
                "status": "gap",
                "rule": "Supervisor Agent behavior",
                "scenario_line": 1349,
                "note": "Only maintenance placeholders exist today; the maintenance workflow itself is still missing.",
            },
        ],
    }
    assert details["build_board_blockers"][0]["blocker_id"] == "BA10-TRACE-001"
    assert details["build_board_blockers"][0]["validation_command_ids"] == [
        "qa_acceptance_reports",
        "qa_smoke_flow",
        "qa_bootstrap_regressions",
        "qa_tailoring_regressions",
        "qa_discovery_regressions",
        "qa_outreach_regressions",
        "qa_feedback_regressions",
        "qa_supervisor_regressions",
        "qa_runtime_control_regressions",
        "qa_review_surface_regressions",
        "qa_runtime_pack_regressions",
    ]
    assert details["current_focus"]["epic_id"] == "BA-10"
    assert details["current_focus"]["slice_id"] == "BA-10-S3"
    assert details["current_focus"]["owner_role"] == "quality-engineer"
    assert details["current_focus"]["gap_ids"] == [
        "BA10_MAINTENANCE_AUTOMATION",
        "BA10_CHAT_REVIEW_AND_CONTROL",
    ]
    assert details["current_focus"]["validation_command_ids"] == [
        "qa_runtime_pack_regressions",
        "qa_acceptance_reports",
        "qa_supervisor_regressions",
        "qa_runtime_control_regressions",
        "qa_review_surface_regressions",
    ]
    assert [gap["gap_id"] for gap in details["current_focus"]["gap_summaries"]] == [
        "BA10_MAINTENANCE_AUTOMATION",
        "BA10_CHAT_REVIEW_AND_CONTROL",
    ]
    assert details["current_focus"]["gap_summaries"][0]["open_scenarios"][0] == {
        "name": "Maintenance change artifacts exist for every autonomous maintenance batch",
        "status": "gap",
        "rule": "Machine handoff contracts and canonical state",
        "scenario_line": 220,
        "note": "Maintenance artifacts are specified in the schema and PRD, but no maintenance batch workflow writes them yet.",
    }
    assert details["current_focus"]["validation_suite_command"] == (
        "python3.11 scripts/quality/run_ba10_validation_suite.py "
        "--project-root <repo_root> --current-focus"
    )
    assert (
        "BA-10-S4 closed the downstream supervisor action-catalog gap"
        in details["current_focus"]["reason"]
    )
    assert (
        "explicit persisted-state review-queue or default change-summary chat reads"
        in details["current_focus"]["reason"]
    )


def test_gap_validation_command_resolution_follows_open_gap_command_mapping():
    command_ids = resolve_acceptance_gap_validation_command_ids(
        REPO_ROOT, ["BA10_MAINTENANCE_AUTOMATION"]
    )

    assert command_ids == [
        "qa_runtime_pack_regressions",
        "qa_acceptance_reports",
        "qa_supervisor_regressions",
    ]


def test_chat_review_gap_validation_command_resolution_follows_open_gap_command_mapping():
    command_ids = resolve_acceptance_gap_validation_command_ids(
        REPO_ROOT, ["BA10_CHAT_REVIEW_AND_CONTROL"]
    )

    assert command_ids == [
        "qa_runtime_control_regressions",
        "qa_review_surface_regressions",
        "qa_runtime_pack_regressions",
        "qa_acceptance_reports",
    ]


def test_current_focus_validation_command_resolution_follows_active_slice():
    command_ids = resolve_current_focus_validation_command_ids(REPO_ROOT)

    assert command_ids == [
        "qa_runtime_pack_regressions",
        "qa_acceptance_reports",
        "qa_supervisor_regressions",
        "qa_runtime_control_regressions",
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
    assert payload["requested_gap_ids"] == []
    assert payload["requested_blocker_ids"] == []
    assert payload["requested_current_focus"] is False
    assert [command["command_id"] for command in payload["commands"]] == [
        "qa_smoke_flow",
        "qa_runtime_pack_regressions",
    ]
    assert payload["requested_smoke_targets"] == []
    assert payload["selector_details"] == {
        "smoke_targets": [],
        "acceptance_gaps": [],
        "build_board_blockers": [],
        "current_focus": None,
    }


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
            "BA10_MAINTENANCE_AUTOMATION",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["requested_gap_ids"] == ["BA10_MAINTENANCE_AUTOMATION"]
    assert payload["requested_blocker_ids"] == []
    assert payload["requested_current_focus"] is False
    assert [command["command_id"] for command in payload["commands"]] == [
        "qa_runtime_pack_regressions",
        "qa_acceptance_reports",
        "qa_supervisor_regressions",
    ]
    assert payload["selector_details"]["acceptance_gaps"] == [
        {
            "gap_id": "BA10_MAINTENANCE_AUTOMATION",
            "title": "Maintenance workflow and artifacts are not implemented",
            "next_slice": "BA-10-S3",
            "open_scenario_count": 6,
            "status_counts": {
                "partial": 1,
                "gap": 5,
            },
            "validation_command_ids": [
                "qa_runtime_pack_regressions",
                "qa_acceptance_reports",
                "qa_supervisor_regressions",
            ],
            "validation_suite_command": (
                "python3.11 scripts/quality/run_ba10_validation_suite.py "
                "--project-root <repo_root> --gap-id BA10_MAINTENANCE_AUTOMATION"
            ),
            "open_scenarios": [
                {
                    "name": "Maintenance change artifacts exist for every autonomous maintenance batch",
                    "status": "gap",
                    "rule": "Machine handoff contracts and canonical state",
                    "scenario_line": 220,
                    "note": "Maintenance artifacts are specified in the schema and PRD, but no maintenance batch workflow writes them yet.",
                },
                {
                    "name": "Supervisor work selection follows the current default priority order",
                    "status": "partial",
                    "rule": "Supervisor Agent behavior",
                    "scenario_line": 1132,
                    "note": "Current supervisor regressions prove open incidents outrank ordinary pipeline advancement, existing runs outrank new posting bootstrap, new postings outrank opportunistic contact-rooted general-learning work, and contact-rooted general-learning work now covers bounded delayed feedback, send-ready dispatch, and email discovery, but bounded maintenance work itself still has no dedicated selector or action path.",
                },
                {
                    "name": "Daily maintenance is mandatory, bounded, and run-boundary aware",
                    "status": "gap",
                    "rule": "Supervisor Agent behavior",
                    "scenario_line": 1322,
                    "note": "Only maintenance placeholders exist today; the maintenance workflow itself is still missing.",
                },
                {
                    "name": "Maintenance changes follow the current git and approval workflow",
                    "status": "gap",
                    "rule": "Supervisor Agent behavior",
                    "scenario_line": 1331,
                    "note": "Only maintenance placeholders exist today; the maintenance workflow itself is still missing.",
                },
                {
                    "name": "Proper maintenance validation requires both change-scoped and full-project testing",
                    "status": "gap",
                    "rule": "Supervisor Agent behavior",
                    "scenario_line": 1342,
                    "note": "Only maintenance placeholders exist today; the maintenance workflow itself is still missing.",
                },
                {
                    "name": "Failed or unapproved maintenance batches remain reviewable",
                    "status": "gap",
                    "rule": "Supervisor Agent behavior",
                    "scenario_line": 1349,
                    "note": "Only maintenance placeholders exist today; the maintenance workflow itself is still missing.",
                },
            ],
        }
    ]


def test_quality_validation_suite_script_dry_run_expands_chat_review_gap_ids():
    result = subprocess.run(
        [
            sys.executable,
            "scripts/quality/run_ba10_validation_suite.py",
            "--project-root",
            str(REPO_ROOT),
            "--dry-run",
            "--gap-id",
            "BA10_CHAT_REVIEW_AND_CONTROL",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["requested_gap_ids"] == ["BA10_CHAT_REVIEW_AND_CONTROL"]
    assert [command["command_id"] for command in payload["commands"]] == [
        "qa_runtime_control_regressions",
        "qa_review_surface_regressions",
        "qa_runtime_pack_regressions",
        "qa_acceptance_reports",
    ]
    assert payload["selector_details"]["acceptance_gaps"] == [
        {
            "gap_id": "BA10_CHAT_REVIEW_AND_CONTROL",
            "title": "Chat review and control are still missing deeper expert-guidance workflows",
            "next_slice": "BA-10-S3",
            "open_scenario_count": 5,
            "status_counts": {
                "partial": 1,
                "gap": 4,
            },
            "validation_command_ids": [
                "qa_runtime_control_regressions",
                "qa_review_surface_regressions",
                "qa_runtime_pack_regressions",
                "qa_acceptance_reports",
            ],
            "validation_suite_command": (
                "python3.11 scripts/quality/run_ba10_validation_suite.py "
                "--project-root <repo_root> --gap-id BA10_CHAT_REVIEW_AND_CONTROL"
            ),
            "open_scenarios": [
                {
                    "name": "jhc-chat uses persisted state for answers and control routing",
                    "status": "partial",
                    "rule": "Supervisor Agent behavior",
                    "scenario_line": 1249,
                    "note": "`scripts/ops/chat_state.py` now rereads persisted dashboard, review-queue, and change-summary state, and `scripts/ops/control_agent.py` remains the canonical global-control route, but generic object-specific override routing and broader chat-native control workflows are still incomplete.",
                },
                {
                    "name": "Expert guidance becomes live immediately but conflicting or uncertain reuse asks first",
                    "status": "gap",
                    "rule": "Supervisor Agent behavior",
                    "scenario_line": 1273,
                    "note": "The direct `jhc-chat` wrapper now has persisted review-queue and default change-summary helper reads, but expert-guidance reuse decisions, conflict-wide pausing, and background-task handoff or return workflows are still missing.",
                },
                {
                    "name": "Conflicting expert guidance pauses the whole autonomous system",
                    "status": "gap",
                    "rule": "Supervisor Agent behavior",
                    "scenario_line": 1281,
                    "note": "The direct `jhc-chat` wrapper now has persisted review-queue and default change-summary helper reads, but expert-guidance reuse decisions, conflict-wide pausing, and background-task handoff or return workflows are still missing.",
                },
                {
                    "name": "Expert-requested background tasks require explicit handoff summary and exclusive focus",
                    "status": "gap",
                    "rule": "Supervisor Agent behavior",
                    "scenario_line": 1307,
                    "note": "The direct `jhc-chat` wrapper now has persisted review-queue and default change-summary helper reads, but expert-guidance reuse decisions, conflict-wide pausing, and background-task handoff or return workflows are still missing.",
                },
                {
                    "name": "Expert-requested background task outcomes return to review appropriately",
                    "status": "gap",
                    "rule": "Supervisor Agent behavior",
                    "scenario_line": 1314,
                    "note": "The direct `jhc-chat` wrapper now has persisted review-queue and default change-summary helper reads, but expert-guidance reuse decisions, conflict-wide pausing, and background-task handoff or return workflows are still missing.",
                },
            ],
        }
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


def test_quality_validation_suite_script_dry_run_expands_build_cli_blocker_with_automated_and_manual_checks():
    result = subprocess.run(
        [
            sys.executable,
            "scripts/quality/run_ba10_validation_suite.py",
            "--project-root",
            str(REPO_ROOT),
            "--dry-run",
            "--blocker-id",
            "BUILD-CLI-001",
            "--include-manual",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["requested_blocker_ids"] == ["BUILD-CLI-001"]
    assert [command["command_id"] for command in payload["commands"]] == [
        "qa_build_agent_cycle_regressions",
        "qa_codex_cli_compatibility",
    ]
    assert payload["selector_details"]["build_board_blockers"] == [
        {
            "blocker_id": "BUILD-CLI-001",
            "status": "open",
            "owner_role": "build-lead",
            "summary": (
                "The unattended build wrapper now has automated regression "
                "coverage for its `codex exec` command shape, but real host-side "
                "cycle execution still needs confirmation after the "
                "`--ask-for-approval` incompatibility."
            ),
            "validation_command_ids": [
                "qa_build_agent_cycle_regressions",
                "qa_codex_cli_compatibility",
            ],
            "validation_suite_command": (
                "python3.11 scripts/quality/run_ba10_validation_suite.py "
                "--project-root <repo_root> --blocker-id BUILD-CLI-001 --include-manual"
            ),
        }
    ]


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
        "qa_runtime_pack_regressions",
        "qa_acceptance_reports",
        "qa_supervisor_regressions",
        "qa_runtime_control_regressions",
        "qa_review_surface_regressions",
    ]
    current_focus = payload["selector_details"]["current_focus"]
    assert current_focus["epic_id"] == "BA-10"
    assert current_focus["slice_id"] == "BA-10-S3"
    assert current_focus["owner_role"] == "quality-engineer"
    assert current_focus["gap_ids"] == [
        "BA10_MAINTENANCE_AUTOMATION",
        "BA10_CHAT_REVIEW_AND_CONTROL",
    ]
    assert current_focus["validation_command_ids"] == [
        "qa_runtime_pack_regressions",
        "qa_acceptance_reports",
        "qa_supervisor_regressions",
        "qa_runtime_control_regressions",
        "qa_review_surface_regressions",
    ]
    assert [gap["gap_id"] for gap in current_focus["gap_summaries"]] == [
        "BA10_MAINTENANCE_AUTOMATION",
        "BA10_CHAT_REVIEW_AND_CONTROL",
    ]
    assert current_focus["validation_suite_command"] == (
        "python3.11 scripts/quality/run_ba10_validation_suite.py "
        "--project-root <repo_root> --current-focus"
    )
    assert (
        "BA-10-S4 closed the downstream supervisor action-catalog gap"
        in current_focus["reason"]
    )
    assert (
        "explicit persisted-state review-queue or default change-summary chat reads"
        in current_focus["reason"]
    )


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
    assert payload["selector_details"]["smoke_targets"] == [
        {
            "target_id": "bootstrap",
            "title": "Bootstrap and prerequisites",
            "acceptance_scenario": "Build smoke test passes",
            "acceptance_checks": [
                "the system initializes or migrates `job_hunt_copilot.db`",
                "the system loads runtime secrets successfully",
                "the system reads the required files from `assets/`",
            ],
            "validation_command_ids": [
                "qa_smoke_flow",
                "qa_bootstrap_regressions",
            ],
            "test_refs": [
                "tests/test_smoke_harness.py",
                "tests/test_bootstrap.py",
                "tests/test_schema.py",
            ],
        },
        {
            "target_id": "feedback",
            "title": "Delayed feedback sync",
            "acceptance_scenario": "Build smoke test passes",
            "acceptance_checks": [
                "the delayed feedback sync logic can run once without crashing",
            ],
            "validation_command_ids": [
                "qa_smoke_flow",
                "qa_feedback_regressions",
            ],
            "test_refs": [
                "tests/test_smoke_harness.py",
                "tests/test_delivery_feedback.py",
                "tests/test_local_runtime.py",
            ],
        },
    ]


def test_build_ba10_validation_suite_report_summarizes_results():
    report = build_ba10_validation_suite_report(
        {
            "project_root": str(REPO_ROOT),
            "refreshed_reports": False,
            "repo_status": {
                "acceptance_scenario_count": 214,
                "acceptance_status_counts": {
                    "implemented": 198,
                    "partial": 2,
                    "gap": 12,
                    "deferred_optional": 1,
                    "excluded_from_required_acceptance": 1,
                },
                "open_acceptance_scenario_count": 14,
                "open_acceptance_gap_cluster_count": 2,
                "open_acceptance_gap_ids": [
                    "BA10_MAINTENANCE_AUTOMATION",
                    "BA10_CHAT_REVIEW_AND_CONTROL",
                ],
                "open_acceptance_gap_summaries": [
                    {
                        "gap_id": "BA10_MAINTENANCE_AUTOMATION",
                        "title": "Maintenance workflow and artifacts are not implemented",
                        "open_scenario_count": 6,
                    },
                    {
                        "gap_id": "BA10_CHAT_REVIEW_AND_CONTROL",
                        "title": "Chat review and control remain wrapper-only",
                        "open_scenario_count": 8,
                    },
                ],
                "open_build_board_blocker_count": 3,
                "open_build_board_blocker_ids": [
                    "BA10-TRACE-001",
                    "BUILD-CLI-001",
                    "OPS-LAUNCHD-001",
                ],
                "current_focus": {
                    "epic_id": "BA-10",
                    "slice_id": "BA-10-S3",
                    "owner_role": "quality-engineer",
                },
            },
            "requested_command_ids": ["qa_smoke_flow"],
            "requested_gap_ids": ["BA10_MAINTENANCE_AUTOMATION"],
            "requested_blocker_ids": [],
            "requested_current_focus": True,
            "requested_smoke_targets": ["bootstrap"],
            "include_manual": True,
            "skip_report_refresh": False,
            "selector_details": {
                "smoke_targets": [
                    {
                        "target_id": "bootstrap",
                        "title": "Bootstrap and prerequisites",
                        "acceptance_scenario": "Build smoke test passes",
                        "acceptance_checks": [
                            "the system initializes or migrates `job_hunt_copilot.db`",
                            "the system loads runtime secrets successfully",
                            "the system reads the required files from `assets/`",
                        ],
                        "validation_command_ids": [
                            "qa_smoke_flow",
                            "qa_bootstrap_regressions",
                        ],
                        "test_refs": [
                            "tests/test_smoke_harness.py",
                            "tests/test_bootstrap.py",
                            "tests/test_schema.py",
                        ],
                    }
                ],
                "acceptance_gaps": [
                    {
                        "gap_id": "BA10_MAINTENANCE_AUTOMATION",
                        "title": "Maintenance workflow and artifacts are not implemented",
                        "next_slice": "BA-10-S3",
                        "open_scenario_count": 6,
                        "status_counts": {
                            "partial": 1,
                            "gap": 5,
                        },
                        "validation_command_ids": [
                            "qa_runtime_pack_regressions",
                            "qa_acceptance_reports",
                            "qa_supervisor_regressions",
                        ],
                        "validation_suite_command": (
                            "python3.11 scripts/quality/run_ba10_validation_suite.py "
                            "--project-root <repo_root> --gap-id BA10_MAINTENANCE_AUTOMATION"
                        ),
                        "open_scenarios": [
                            {
                                "name": "Maintenance change artifacts exist for every autonomous maintenance batch",
                                "status": "gap",
                                "rule": "Machine handoff contracts and canonical state",
                                "scenario_line": 220,
                                "note": "Maintenance artifacts are specified in the schema and PRD, but no maintenance batch workflow writes them yet.",
                            },
                            {
                                "name": "Supervisor work selection follows the current default priority order",
                                "status": "partial",
                                "rule": "Supervisor Agent behavior",
                                "scenario_line": 1132,
                                "note": "Current supervisor regressions prove open incidents outrank ordinary pipeline advancement, existing runs outrank new posting bootstrap, new postings outrank opportunistic contact-rooted general-learning work, and contact-rooted general-learning work now covers bounded delayed feedback, send-ready dispatch, and email discovery, but bounded maintenance work itself still has no dedicated selector or action path.",
                            },
                        ],
                    }
                ],
                "build_board_blockers": [],
                "current_focus": {
                    "epic_id": "BA-10",
                    "slice_id": "BA-10-S3",
                    "owner_role": "quality-engineer",
                    "reason": "BA-10-S4 closed the downstream supervisor action-catalog gap.",
                    "gap_ids": [
                        "BA10_MAINTENANCE_AUTOMATION",
                        "BA10_CHAT_REVIEW_AND_CONTROL",
                    ],
                    "gap_summaries": [
                        {
                            "gap_id": "BA10_MAINTENANCE_AUTOMATION",
                            "title": "Maintenance workflow and artifacts are not implemented",
                            "next_slice": "BA-10-S3",
                            "open_scenario_count": 6,
                            "status_counts": {
                                "partial": 1,
                                "gap": 5,
                            },
                            "validation_command_ids": [
                                "qa_runtime_pack_regressions",
                                "qa_acceptance_reports",
                                "qa_supervisor_regressions",
                            ],
                            "validation_suite_command": (
                                "python3.11 scripts/quality/run_ba10_validation_suite.py "
                                "--project-root <repo_root> --gap-id BA10_MAINTENANCE_AUTOMATION"
                            ),
                            "open_scenarios": [
                                {
                                    "name": "Maintenance change artifacts exist for every autonomous maintenance batch",
                                    "status": "gap",
                                    "rule": "Machine handoff contracts and canonical state",
                                    "scenario_line": 220,
                                    "note": "Maintenance artifacts are specified in the schema and PRD, but no maintenance batch workflow writes them yet.",
                                }
                            ],
                        }
                    ],
                    "validation_command_ids": [
                        "qa_runtime_pack_regressions",
                        "qa_acceptance_reports",
                        "qa_supervisor_regressions",
                        "qa_runtime_control_regressions",
                        "qa_review_surface_regressions",
                    ],
                    "validation_suite_command": (
                        "python3.11 scripts/quality/run_ba10_validation_suite.py "
                        "--project-root <repo_root> --current-focus"
                    ),
                },
            },
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

    assert report["validation_suite_report_version"] == 2
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
    assert report["repo_status"] == {
        "acceptance_scenario_count": 214,
        "acceptance_status_counts": {
            "implemented": 198,
            "partial": 2,
            "gap": 12,
            "deferred_optional": 1,
            "excluded_from_required_acceptance": 1,
        },
        "open_acceptance_scenario_count": 14,
        "open_acceptance_gap_cluster_count": 2,
        "open_acceptance_gap_ids": [
            "BA10_MAINTENANCE_AUTOMATION",
            "BA10_CHAT_REVIEW_AND_CONTROL",
        ],
        "open_acceptance_gap_summaries": [
            {
                "gap_id": "BA10_MAINTENANCE_AUTOMATION",
                "title": "Maintenance workflow and artifacts are not implemented",
                "open_scenario_count": 6,
            },
            {
                "gap_id": "BA10_CHAT_REVIEW_AND_CONTROL",
                "title": "Chat review and control remain wrapper-only",
                "open_scenario_count": 8,
            },
        ],
        "open_build_board_blocker_count": 3,
        "open_build_board_blocker_ids": [
            "BA10-TRACE-001",
            "BUILD-CLI-001",
            "OPS-LAUNCHD-001",
        ],
        "current_focus": {
            "epic_id": "BA-10",
            "slice_id": "BA-10-S3",
            "owner_role": "quality-engineer",
        },
    }

    markdown = render_ba10_validation_suite_markdown(report)
    assert "# BA-10 Validation Suite Report" in markdown
    assert "- Requested command ids: `qa_smoke_flow`" in markdown
    assert (
        "- Requested acceptance gaps: `BA10_MAINTENANCE_AUTOMATION`"
        in markdown
    )
    assert "- Failed command ids: `qa_host_launchd_validation`" in markdown
    assert "## Open BA-10 Status" in markdown
    assert "- Open acceptance gap clusters: `2`" in markdown
    assert "- Open acceptance gap summaries:" in markdown
    assert (
        "  - `BA10_MAINTENANCE_AUTOMATION`: Maintenance workflow and artifacts are not implemented (`6` scenarios)"
        in markdown
    )
    assert "- Open build-board blocker ids: `BA10-TRACE-001`, `BUILD-CLI-001`, `OPS-LAUNCHD-001`" in markdown
    assert "## Selector Details" in markdown
    assert "### Smoke Targets" in markdown
    assert "### Acceptance Gaps" in markdown
    assert "### Current Focus" in markdown
    assert "- `bootstrap`: Bootstrap and prerequisites" in markdown
    assert (
        "- `BA10_MAINTENANCE_AUTOMATION`: Maintenance workflow and artifacts are not implemented"
    ) in markdown
    assert (
        "    - `[gap]` Maintenance change artifacts exist for every autonomous maintenance batch (rule: `Machine handoff contracts and canonical state`, line: `220`)"
        in markdown
    )
    assert "- Gap summaries:" in markdown
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
            "repo_status": {
                "acceptance_scenario_count": 214,
                "acceptance_status_counts": {
                    "implemented": 197,
                    "partial": 3,
                    "gap": 12,
                },
                "open_acceptance_scenario_count": 6,
                "open_acceptance_gap_cluster_count": 1,
                "open_acceptance_gap_ids": [
                    "BA10_MAINTENANCE_AUTOMATION",
                ],
                "open_acceptance_gap_summaries": [
                    {
                        "gap_id": "BA10_MAINTENANCE_AUTOMATION",
                        "title": "Maintenance workflow and artifacts are not implemented",
                        "open_scenario_count": 6,
                    }
                ],
                "open_build_board_blocker_count": 1,
                "open_build_board_blocker_ids": ["OPS-LAUNCHD-001"],
                "current_focus": {
                    "epic_id": "BA-10",
                    "slice_id": "BA-10-S3",
                    "owner_role": "quality-engineer",
                },
            },
            "requested_command_ids": [],
            "requested_gap_ids": [],
            "requested_blocker_ids": ["OPS-LAUNCHD-001"],
            "requested_current_focus": False,
            "requested_smoke_targets": ["feedback"],
            "include_manual": False,
            "skip_report_refresh": False,
            "selector_details": {
                "smoke_targets": [
                    {
                        "target_id": "feedback",
                        "title": "Delayed feedback sync",
                        "acceptance_scenario": "Build smoke test passes",
                        "acceptance_checks": [
                            "the delayed feedback sync logic can run once without crashing",
                        ],
                        "validation_command_ids": [
                            "qa_smoke_flow",
                            "qa_feedback_regressions",
                        ],
                        "test_refs": [
                            "tests/test_smoke_harness.py",
                            "tests/test_delivery_feedback.py",
                            "tests/test_local_runtime.py",
                        ],
                    }
                ],
                "acceptance_gaps": [],
                "build_board_blockers": [
                    {
                        "blocker_id": "OPS-LAUNCHD-001",
                        "status": "open",
                        "owner_role": "build-lead",
                        "summary": "Host launchd validation is still pending outside the sandbox.",
                        "validation_command_ids": [
                            "qa_runtime_control_regressions",
                            "qa_host_launchd_validation",
                        ],
                        "validation_suite_command": (
                            "python3.11 scripts/quality/run_ba10_validation_suite.py "
                            "--project-root <repo_root> --blocker-id OPS-LAUNCHD-001 --include-manual"
                        ),
                    }
                ],
                "current_focus": None,
            },
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
    assert "## Open BA-10 Status" in markdown
    assert "### Build-Board Blockers" in markdown
    assert "- Requested build-board blockers: `OPS-LAUNCHD-001`" in markdown
    assert "- Requested smoke targets: `feedback`" in markdown
    assert "### qa_feedback_regressions: Delivery feedback regressions" in markdown
