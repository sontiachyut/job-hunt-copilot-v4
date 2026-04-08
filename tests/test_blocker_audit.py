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
    assert current_focus["gap_ids"] == ["BA10_SUPERVISOR_DOWNSTREAM_ACTION_CATALOG"]
    assert [command["command_id"] for command in current_focus["validation_commands"]] == [
        "qa_supervisor_regressions",
        "qa_acceptance_reports",
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

    supervisor_cluster = next(
        cluster
        for cluster in audit["acceptance_gap_clusters"]
        if cluster["gap_id"] == "BA10_SUPERVISOR_DOWNSTREAM_ACTION_CATALOG"
    )
    assert supervisor_cluster["implementation_snapshot"] == {
        "current_selector_priority_order": [
            "active_incident",
            "open_pipeline_run",
            "new_role_targeted_posting",
        ],
        "registered_role_targeted_checkpoint_stages": ["agent_review", "lead_handoff"],
        "registered_role_targeted_action_stages": [
            "agent_review",
            "lead_handoff",
            "people_search",
        ],
        "validated_blocked_role_targeted_stages": [
            "email_discovery",
            "sending",
            "delivery_feedback",
        ],
        "unsupported_autonomous_scope_paths": [
            "contact_rooted_general_learning",
        ],
    }
    assert "BA-10-S4" in supervisor_cluster["slice_ids"]

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
