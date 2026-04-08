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

    for rule in matrix["rules"]:
        for path_text in rule["code_refs"] + rule["test_refs"]:
            assert (REPO_ROOT / path_text).exists(), path_text
        for scenario in rule["scenarios"]:
            assert scenario["owner_role"]
            assert scenario["epic_ids"]
            assert scenario["code_refs"], scenario["name"]
            assert scenario["test_refs"], scenario["name"]
            for path_text in scenario["code_refs"] + scenario["test_refs"]:
                assert (REPO_ROOT / path_text).exists(), path_text

    for note in matrix["epic_validation_notes"]:
        assert note["owner_role"]
        assert note["focus"]
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
        for path_text in gap["evidence_code_refs"] + gap["evidence_test_refs"]:
            assert (REPO_ROOT / path_text).exists(), path_text
