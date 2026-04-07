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

    summary = audit["summary"]
    assert summary["open_acceptance_scenario_count"] == (
        summary["acceptance_status_counts"]["partial"] + summary["acceptance_status_counts"]["gap"]
    )

    for cluster in audit["acceptance_gap_clusters"]:
        assert cluster["open_scenario_count"] == (
            cluster["status_counts"]["partial"] + cluster["status_counts"]["gap"]
        )
        assert cluster["owner_roles"]
        assert cluster["rules"]
        assert cluster["epic_ids"]
        assert cluster["validation_commands"]
        for path_text in cluster["evidence_code_refs"] + cluster["evidence_test_refs"]:
            assert (REPO_ROOT / path_text).exists(), path_text
        for command in cluster["validation_commands"]:
            assert command["command_id"]
            assert command["command"]
            assert command["kind"]
            assert command["description"]

    for blocker in audit["build_board_blockers"]:
        assert blocker["blocker_id"]
        assert blocker["status"]
        assert blocker["severity"]
        assert blocker["owner_role"]
        assert blocker["summary"]
        assert blocker["validation_commands"]
        assert blocker["missing_evidence_refs"] == []
        for path_text in blocker["evidence_refs"]:
            assert (REPO_ROOT / path_text).exists(), path_text
        for command in blocker["validation_commands"]:
            assert command["command_id"]
            assert command["command"]
            assert command["kind"]
            assert command["description"]
