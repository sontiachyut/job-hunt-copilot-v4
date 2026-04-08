from __future__ import annotations

import json
from pathlib import Path

from job_hunt_copilot.acceptance_traceability import (
    REPORT_JSON_PATH,
    REPORT_MD_PATH,
    build_acceptance_trace_matrix,
    render_acceptance_trace_markdown,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_acceptance_trace_matrix_reports_are_current_and_reference_real_repo_paths():
    matrix = build_acceptance_trace_matrix(REPO_ROOT)
    generated_markdown = render_acceptance_trace_markdown(matrix)

    committed_json = json.loads((REPO_ROOT / REPORT_JSON_PATH).read_text(encoding="utf-8"))
    committed_markdown = (REPO_ROOT / REPORT_MD_PATH).read_text(encoding="utf-8")

    assert committed_json == matrix
    assert committed_markdown == generated_markdown
    implemented_slice_catalog = {
        slice_record["slice_id"]: slice_record for slice_record in matrix["implemented_slices"]
    }
    assert implemented_slice_catalog
    assert all(
        slice_record["status"] in {"completed", "in_progress"}
        for slice_record in implemented_slice_catalog.values()
    )

    for rule in matrix["rules"]:
        assert rule["slice_ids"]
        assert all(slice_id in implemented_slice_catalog for slice_id in rule["slice_ids"])
        for path_text in rule["code_refs"] + rule["test_refs"]:
            assert (REPO_ROOT / path_text).exists(), path_text
        for scenario in rule["scenarios"]:
            assert scenario["owner_role"]
            assert scenario["epic_ids"]
            assert scenario["slice_ids"]
            assert scenario["code_refs"], scenario["name"]
            assert scenario["test_refs"], scenario["name"]
            assert all(
                slice_id in implemented_slice_catalog for slice_id in scenario["slice_ids"]
            ), scenario["name"]
            for path_text in scenario["code_refs"] + scenario["test_refs"]:
                assert (REPO_ROOT / path_text).exists(), path_text

    for note in matrix["epic_validation_notes"]:
        assert note["owner_role"]
        assert note["focus"]
        assert note["slice_ids"]
        assert all(slice_id in implemented_slice_catalog for slice_id in note["slice_ids"])
        assert note["ba10_smoke_targets"]
        for test_ref in note["primary_tests"]:
            assert (REPO_ROOT / test_ref).exists(), test_ref

    smoke_targets = {target["target_id"]: target for target in matrix["smoke_coverage_targets"]}
    assert set(smoke_targets) == {
        "bootstrap",
        "tailoring",
        "discovery",
        "send",
        "feedback",
        "review_query",
    }
    for target in smoke_targets.values():
        assert target["acceptance_scenario"] == "Build smoke test passes"
        assert target["acceptance_checks"]
        assert target["validation_command_ids"]
        assert "tests/test_smoke_harness.py" in target["test_refs"]
        for path_text in target["code_refs"] + target["test_refs"]:
            assert (REPO_ROOT / path_text).exists(), path_text

    for gap in matrix["gap_registry"]:
        assert gap["title"]
        assert gap["reason"]
        assert gap["next_slice"]
        assert gap["evidence_summary"]
        assert gap["evidence_code_refs"]
        assert gap["evidence_test_refs"]
        if gap["scenario_names"]:
            assert gap["slice_ids"]
            assert all(slice_id in implemented_slice_catalog for slice_id in gap["slice_ids"])
        for path_text in gap["evidence_code_refs"] + gap["evidence_test_refs"]:
            assert (REPO_ROOT / path_text).exists(), path_text

    supervisor_gap = next(
        gap
        for gap in matrix["gap_registry"]
        if gap["gap_id"] == "BA10_SUPERVISOR_DOWNSTREAM_ACTION_CATALOG"
    )
    assert supervisor_gap["implementation_snapshot"] == {
        "current_selector_priority_order": [
            "active_incident",
            "open_pipeline_run",
            "new_role_targeted_posting",
        ],
        "registered_role_targeted_checkpoint_stages": ["agent_review", "lead_handoff"],
        "registered_role_targeted_action_stages": [
            "agent_review",
            "email_discovery",
            "lead_handoff",
            "people_search",
            "sending",
        ],
        "validated_blocked_role_targeted_stages": [
            "delivery_feedback",
        ],
        "unsupported_autonomous_scope_paths": [
            "contact_rooted_general_learning",
        ],
    }
    assert "BA-10-S4" in supervisor_gap["slice_ids"]

    bootstrap_rule = next(
        rule for rule in matrix["rules"] if rule["rule"] == "Build bootstrap and prerequisites"
    )
    assert "BA-01-S1" in bootstrap_rule["slice_ids"]
