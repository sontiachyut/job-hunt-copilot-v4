from __future__ import annotations

import json
from pathlib import Path

from job_hunt_copilot.blocker_audit import (
    REPORT_JSON_PATH,
    REPORT_MD_PATH,
    build_ba10_blocker_audit,
    render_ba10_blocker_audit_markdown,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_ba10_blocker_audit_reports_are_current_and_reference_real_repo_paths():
    audit = build_ba10_blocker_audit(REPO_ROOT)
    generated_markdown = render_ba10_blocker_audit_markdown(audit)

    committed_json = json.loads((REPO_ROOT / REPORT_JSON_PATH).read_text(encoding="utf-8"))
    committed_markdown = (REPO_ROOT / REPORT_MD_PATH).read_text(encoding="utf-8")

    assert committed_json == audit
    assert committed_markdown == generated_markdown
    implemented_slice_ids = {
        slice_record["slice_id"] for slice_record in audit["implemented_slices"]
    }
    assert implemented_slice_ids

    summary = audit["summary"]
    assert summary["open_acceptance_scenario_count"] == (
        summary["acceptance_status_counts"]["partial"] + summary["acceptance_status_counts"]["gap"]
    )

    current_focus = audit["current_focus"]
    assert current_focus["gap_ids"] == [
        "BA10_MAINTENANCE_AUTOMATION",
        "BA10_CHAT_REVIEW_AND_CONTROL",
    ]
    assert [command["command_id"] for command in current_focus["validation_commands"]] == [
        "qa_runtime_pack_regressions",
        "qa_acceptance_reports",
        "qa_supervisor_regressions",
        "qa_runtime_control_regressions",
        "qa_review_surface_regressions",
    ]
    assert current_focus["validation_suite"] == {
        "args": ["--project-root", "<repo_root>", "--current-focus"],
        "command": (
            "python3.11 scripts/quality/run_ba10_validation_suite.py "
            "--project-root <repo_root> --current-focus"
        ),
        "requires_include_manual": False,
    }

    for cluster in audit["acceptance_gap_clusters"]:
        assert cluster["open_scenario_count"] == (
            cluster["status_counts"]["partial"] + cluster["status_counts"]["gap"]
        )
        assert cluster["owner_roles"]
        assert cluster["rules"]
        assert cluster["epic_ids"]
        assert cluster["slice_ids"]
        assert all(slice_id in implemented_slice_ids for slice_id in cluster["slice_ids"])
        assert cluster["validation_commands"]
        assert cluster["validation_suite"]["args"][:2] == ["--project-root", "<repo_root>"]
        assert cluster["validation_suite"]["args"][2:4] == ["--gap-id", cluster["gap_id"]]
        assert cluster["validation_suite"]["requires_include_manual"] is False
        for path_text in cluster["evidence_code_refs"] + cluster["evidence_test_refs"]:
            assert (REPO_ROOT / path_text).exists(), path_text
        for command in cluster["validation_commands"]:
            assert command["command_id"]
            assert command["command"]
            assert command["kind"]
            assert command["description"]

    maintenance_cluster = next(
        cluster
        for cluster in audit["acceptance_gap_clusters"]
        if cluster["gap_id"] == "BA10_MAINTENANCE_AUTOMATION"
    )
    assert maintenance_cluster["next_slice"] == "BA-10-S3"
    assert maintenance_cluster["status_counts"] == {"partial": 1, "gap": 5}
    assert "BA-10-S3" in maintenance_cluster["slice_ids"]
    assert [command["command_id"] for command in maintenance_cluster["validation_commands"]] == [
        "qa_runtime_pack_regressions",
        "qa_acceptance_reports",
        "qa_supervisor_regressions",
    ]
    maintenance_scenario = maintenance_cluster["scenarios"][0]
    assert maintenance_scenario["rule"] == "Machine handoff contracts and canonical state"
    assert (
        maintenance_scenario["name"]
        == "Maintenance change artifacts exist for every autonomous maintenance batch"
    )
    assert maintenance_scenario["scenario_line"] == 220
    assert maintenance_scenario["status"] == "gap"
    assert maintenance_scenario["owner_role"] == "build-lead"
    assert "BA-01" in maintenance_scenario["epic_ids"]
    assert "BA-09" in maintenance_scenario["epic_ids"]
    assert "BA-01-S1" in maintenance_scenario["slice_ids"]
    assert "BA-09-S3" in maintenance_scenario["slice_ids"]
    assert "job_hunt_copilot/supervisor.py" in maintenance_scenario["code_refs"]
    assert "job_hunt_copilot/review_queries.py" in maintenance_scenario["code_refs"]
    assert "tests/test_supervisor.py" in maintenance_scenario["test_refs"]
    assert "tests/test_review_queries.py" in maintenance_scenario["test_refs"]
    assert (
        maintenance_scenario["note"]
        == "Maintenance artifacts are specified in the schema and PRD, but no maintenance batch workflow writes them yet."
    )

    chat_cluster = next(
        cluster
        for cluster in audit["acceptance_gap_clusters"]
        if cluster["gap_id"] == "BA10_CHAT_REVIEW_AND_CONTROL"
    )
    assert chat_cluster["next_slice"] == "BA-10-S3"
    assert chat_cluster["status_counts"] == {"partial": 1, "gap": 4}
    assert "BA-10-S3" in chat_cluster["slice_ids"]
    assert [command["command_id"] for command in chat_cluster["validation_commands"]] == [
        "qa_runtime_control_regressions",
        "qa_review_surface_regressions",
        "qa_runtime_pack_regressions",
        "qa_acceptance_reports",
    ]
    assert "job_hunt_copilot/chat_runtime.py" in chat_cluster["evidence_code_refs"]
    assert "scripts/ops/chat_state.py" in chat_cluster["evidence_code_refs"]
    assert "tests/test_local_runtime.py" in chat_cluster["evidence_test_refs"]
    assert "tests/test_review_queries.py" in chat_cluster["evidence_test_refs"]

    chat_partial_scenario = next(
        scenario
        for scenario in chat_cluster["scenarios"]
        if scenario["status"] == "partial"
    )
    assert chat_partial_scenario["rule"] == "Supervisor Agent behavior"
    assert chat_partial_scenario["name"] == "jhc-chat uses persisted state for answers and control routing"
    assert chat_partial_scenario["scenario_line"] == 1249
    assert chat_partial_scenario["owner_role"] == "build-lead"
    assert "BA-02" in chat_partial_scenario["epic_ids"]
    assert "BA-03" in chat_partial_scenario["epic_ids"]
    assert "BA-02-S1" in chat_partial_scenario["slice_ids"]
    assert "BA-03-S3" in chat_partial_scenario["slice_ids"]
    assert "job_hunt_copilot/chat_runtime.py" in chat_partial_scenario["code_refs"]
    assert "scripts/ops/chat_session.py" in chat_partial_scenario["code_refs"]
    assert "tests/test_local_runtime.py" in chat_partial_scenario["test_refs"]
    assert "tests/test_runtime_pack.py" in chat_partial_scenario["test_refs"]
    assert (
        chat_partial_scenario["note"]
        == "`scripts/ops/chat_state.py` now rereads persisted dashboard, review-queue, and change-summary state, and `scripts/ops/control_agent.py` remains the canonical global-control route, but generic object-specific override routing and broader chat-native control workflows are still incomplete."
    )

    chat_background_gap = next(
        scenario
        for scenario in chat_cluster["scenarios"]
        if scenario["name"]
        == "Expert-requested background task outcomes return to review appropriately"
    )
    assert chat_background_gap["status"] == "gap"
    assert chat_background_gap["scenario_line"] == 1314
    assert (
        chat_background_gap["note"]
        == "The direct `jhc-chat` wrapper now has persisted review-queue and default change-summary helper reads, but expert-guidance reuse decisions, conflict-wide pausing, and background-task handoff or return workflows are still missing."
    )

    build_cli_blocker = next(
        blocker
        for blocker in audit["build_board_blockers"]
        if blocker["blocker_id"] == "BUILD-CLI-001"
    )
    assert [command["command_id"] for command in build_cli_blocker["validation_commands"]] == [
        "qa_build_agent_cycle_regressions",
        "qa_codex_cli_compatibility",
    ]
    assert build_cli_blocker["validation_suite"] == {
        "args": [
            "--project-root",
            "<repo_root>",
            "--blocker-id",
            "BUILD-CLI-001",
            "--include-manual",
        ],
        "command": (
            "python3.11 scripts/quality/run_ba10_validation_suite.py "
            "--project-root <repo_root> --blocker-id BUILD-CLI-001 --include-manual"
        ),
        "requires_include_manual": True,
    }

    for blocker in audit["build_board_blockers"]:
        assert blocker["blocker_id"]
        assert blocker["status"]
        assert blocker["severity"]
        assert blocker["owner_role"]
        assert blocker["summary"]
        assert blocker["validation_commands"]
        assert blocker["missing_evidence_refs"] == []
        assert blocker["validation_suite"]["args"][:2] == ["--project-root", "<repo_root>"]
        assert blocker["validation_suite"]["args"][2:4] == [
            "--blocker-id",
            blocker["blocker_id"],
        ]
        if blocker["blocker_id"] == "BA10-TRACE-001":
            assert blocker["validation_suite"]["requires_include_manual"] is False
            assert "--include-manual" not in blocker["validation_suite"]["args"]
        else:
            assert blocker["validation_suite"]["requires_include_manual"] is True
            assert blocker["validation_suite"]["args"][-1] == "--include-manual"
        for path_text in blocker["evidence_refs"]:
            assert (REPO_ROOT / path_text).exists(), path_text
        for command in blocker["validation_commands"]:
            assert command["command_id"]
            assert command["command"]
            assert command["kind"]
            assert command["description"]


def test_current_focus_slice_is_reflected_in_open_gap_clusters():
    audit = build_ba10_blocker_audit(REPO_ROOT)

    open_gap_next_slices = {
        cluster["next_slice"] for cluster in audit["acceptance_gap_clusters"] if cluster["open_scenario_count"]
    }

    assert audit["current_focus"]["slice_id"] in open_gap_next_slices
