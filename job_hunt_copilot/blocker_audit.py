from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import yaml

from .acceptance_traceability import (
    REPORT_JSON_PATH as TRACE_REPORT_JSON_PATH,
    REPORT_MD_PATH as TRACE_REPORT_MD_PATH,
    STATUS_GAP,
    STATUS_PARTIAL,
    build_acceptance_trace_matrix,
)


BLOCKER_AUDIT_VERSION = 5
BUILD_BOARD_PATH = Path("build-agent/state/build-board.yaml")
REPORT_JSON_PATH = Path("build-agent/reports/ba-10-blocker-audit.json")
REPORT_MD_PATH = Path("build-agent/reports/ba-10-blocker-audit.md")
OPEN_ACCEPTANCE_STATUSES = (STATUS_PARTIAL, STATUS_GAP)
VALIDATION_SUITE_SCRIPT = "python3.11 scripts/quality/run_ba10_validation_suite.py"
VALIDATION_SUITE_PROJECT_ROOT_PLACEHOLDER = "<repo_root>"

VALIDATION_COMMANDS: dict[str, dict[str, str]] = {
    "qa_acceptance_reports": {
        "title": "Acceptance report guards",
        "kind": "automated",
        "command": "python3.11 -m pytest tests/test_acceptance_traceability.py tests/test_blocker_audit.py",
        "description": "Keeps the committed BA-10 acceptance and blocker reports synchronized with repo code, tests, and state references.",
    },
    "qa_smoke_flow": {
        "title": "Smoke harness flow",
        "kind": "automated",
        "command": "python3.11 -m pytest tests/test_smoke_harness.py",
        "description": "Replays the committed bootstrap -> tailoring -> discovery -> send -> feedback -> review-query smoke path.",
    },
    "qa_bootstrap_regressions": {
        "title": "Bootstrap regressions",
        "kind": "automated",
        "command": "python3.11 -m pytest tests/test_bootstrap.py tests/test_schema.py tests/test_artifacts.py",
        "description": "Confirms bootstrap prerequisites, canonical schema migration, and shared artifact contracts stay valid.",
    },
    "qa_tailoring_regressions": {
        "title": "Tailoring regressions",
        "kind": "automated",
        "command": "python3.11 -m pytest tests/test_resume_tailoring.py",
        "description": "Confirms tailoring bootstrap, deterministic artifact generation, compile verification, and mandatory review gates stay intact.",
    },
    "qa_discovery_regressions": {
        "title": "Discovery regressions",
        "kind": "automated",
        "command": "python3.11 -m pytest tests/test_email_discovery.py",
        "description": "Confirms people search, shortlist materialization, enrichment, discovery artifacts, and provider-budget behavior stay intact.",
    },
    "qa_outreach_regressions": {
        "title": "Outreach regressions",
        "kind": "automated",
        "command": "python3.11 -m pytest tests/test_outreach.py",
        "description": "Confirms send-set readiness, draft persistence, safe send execution, and repeat-outreach guardrails stay intact.",
    },
    "qa_feedback_regressions": {
        "title": "Delivery feedback regressions",
        "kind": "automated",
        "command": "python3.11 -m pytest tests/test_delivery_feedback.py",
        "description": "Confirms immediate or delayed feedback ingestion, normalized event persistence, and delivery outcome artifacts stay intact.",
    },
    "qa_supervisor_regressions": {
        "title": "Supervisor downstream hardening regressions",
        "kind": "automated",
        "command": "python3.11 -m pytest tests/test_supervisor_downstream_actions.py",
        "description": "Confirms `lead_handoff` advances into `agent_review`, bounded mandatory review advances into `people_search`, bounded people search advances into `email_discovery`, bounded email discovery advances into `sending`, later stages still escalate explicitly, and retries preserve the same durable run plus pending review packet.",
    },
    "qa_runtime_control_regressions": {
        "title": "Runtime control regressions",
        "kind": "automated",
        "command": "python3.11 -m pytest tests/test_local_runtime.py",
        "description": "Covers launchd plist wiring, control commands, chat lifecycle state, delayed feedback runners, and explicit negative control cases.",
    },
    "qa_review_surface_regressions": {
        "title": "Review surface regressions",
        "kind": "automated",
        "command": "python3.11 -m pytest tests/test_review_queries.py",
        "description": "Verifies persisted grouped review surfaces and traceability reads that back the chat/review boundary.",
    },
    "qa_runtime_pack_regressions": {
        "title": "Runtime pack regressions",
        "kind": "automated",
        "command": "python3.11 -m pytest tests/test_runtime_pack.py",
        "description": "Confirms generated runtime scaffolding stays honest about current action-catalog and maintenance placeholder status.",
    },
    "qa_build_agent_cycle_regressions": {
        "title": "Build-agent cycle regressions",
        "kind": "automated",
        "command": "python3.11 -m pytest tests/test_build_agent_cycle.py",
        "description": "Guards the unattended build-lead `codex exec` invocation shape so unsupported approval flags do not return.",
    },
    "qa_codex_cli_compatibility": {
        "title": "Codex CLI compatibility check",
        "kind": "manual_local",
        "command": "codex exec --help && codex --help",
        "description": "Reconfirms the current CLI shape so unattended build wrappers do not reintroduce unsupported approval flags.",
    },
    "qa_host_launchd_validation": {
        "title": "Host launchd validation",
        "kind": "manual_host",
        "command": "bin/jhc-agent-start && launchctl print gui/$UID/com.jobhuntcopilot.supervisor",
        "description": "Must run outside the sandbox to validate real host launchd bootstrap behavior and collect diagnostic output.",
    },
}

GAP_VALIDATION_COMMAND_IDS: dict[str, tuple[str, ...]] = {
    "BA10_SUPERVISOR_DOWNSTREAM_ACTION_CATALOG": (
        "qa_supervisor_regressions",
        "qa_acceptance_reports",
    ),
    "BA10_MAINTENANCE_AUTOMATION": (
        "qa_runtime_pack_regressions",
        "qa_acceptance_reports",
    ),
    "BA10_CHAT_REVIEW_AND_CONTROL": (
        "qa_runtime_control_regressions",
        "qa_review_surface_regressions",
        "qa_runtime_pack_regressions",
        "qa_acceptance_reports",
    ),
    "BA10_CHAT_IDLE_TIMEOUT_RESUME": (
        "qa_runtime_control_regressions",
        "qa_runtime_pack_regressions",
        "qa_acceptance_reports",
    ),
    "BA10_POSTING_ABANDON_CONTROL": (
        "qa_runtime_control_regressions",
        "qa_acceptance_reports",
    ),
}

BOARD_BLOCKER_VALIDATION_COMMAND_IDS: dict[str, tuple[str, ...]] = {
    "BA10-TRACE-001": (
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
    ),
    "BUILD-CLI-001": (
        "qa_build_agent_cycle_regressions",
        "qa_codex_cli_compatibility",
    ),
    "OPS-LAUNCHD-001": (
        "qa_runtime_control_regressions",
        "qa_host_launchd_validation",
    ),
}


def _load_build_board(project_root: Path) -> dict[str, Any]:
    payload = yaml.safe_load((project_root / BUILD_BOARD_PATH).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected mapping in {BUILD_BOARD_PATH}")
    return payload


def _resolve_validation_commands(command_ids: tuple[str, ...]) -> list[dict[str, str]]:
    commands: list[dict[str, str]] = []
    for command_id in command_ids:
        metadata = VALIDATION_COMMANDS[command_id]
        commands.append(
            {
                "command_id": command_id,
                "title": metadata["title"],
                "kind": metadata["kind"],
                "command": metadata["command"],
                "description": metadata["description"],
            }
        )
    return commands


def _build_validation_suite_entry(
    *,
    selector_args: tuple[str, ...],
    validation_commands: list[dict[str, str]],
) -> dict[str, Any]:
    requires_include_manual = any(
        command["kind"] != "automated" for command in validation_commands
    )
    args = [
        "--project-root",
        VALIDATION_SUITE_PROJECT_ROOT_PLACEHOLDER,
        *selector_args,
    ]
    if requires_include_manual:
        args.append("--include-manual")
    return {
        "args": list(args),
        "command": " ".join([VALIDATION_SUITE_SCRIPT, *args]),
        "requires_include_manual": requires_include_manual,
    }


def _build_acceptance_gap_clusters(matrix: dict[str, Any]) -> list[dict[str, Any]]:
    scenario_rows_by_gap_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    owner_roles_by_gap_id: dict[str, set[str]] = defaultdict(set)
    epic_ids_by_gap_id: dict[str, set[str]] = defaultdict(set)
    rules_by_gap_id: dict[str, set[str]] = defaultdict(set)
    status_counts_by_gap_id: dict[str, Counter[str]] = defaultdict(Counter)
    slice_ids_by_gap_id: dict[str, list[str]] = defaultdict(list)

    for rule in matrix["rules"]:
        for scenario in rule["scenarios"]:
            if scenario["status"] not in OPEN_ACCEPTANCE_STATUSES:
                continue
            for gap_id in scenario["gap_ids"]:
                scenario_rows_by_gap_id[gap_id].append(
                    {
                        "name": scenario["name"],
                        "status": scenario["status"],
                        "owner_role": scenario["owner_role"],
                        "epic_ids": list(scenario["epic_ids"]),
                    }
                )
                owner_roles_by_gap_id[gap_id].add(scenario["owner_role"])
                epic_ids_by_gap_id[gap_id].update(scenario["epic_ids"])
                rules_by_gap_id[gap_id].add(rule["rule"])
                status_counts_by_gap_id[gap_id][scenario["status"]] += 1
                for slice_id in scenario["slice_ids"]:
                    if slice_id not in slice_ids_by_gap_id[gap_id]:
                        slice_ids_by_gap_id[gap_id].append(slice_id)

    clusters: list[dict[str, Any]] = []
    for gap in matrix["gap_registry"]:
        scenario_rows = scenario_rows_by_gap_id.get(gap["gap_id"], [])
        if not scenario_rows:
            continue
        validation_commands = _resolve_validation_commands(
            GAP_VALIDATION_COMMAND_IDS.get(gap["gap_id"], ("qa_acceptance_reports",))
        )
        status_counts = {
            STATUS_PARTIAL: status_counts_by_gap_id[gap["gap_id"]][STATUS_PARTIAL],
            STATUS_GAP: status_counts_by_gap_id[gap["gap_id"]][STATUS_GAP],
        }
        cluster_record = {
            "gap_id": gap["gap_id"],
            "title": gap["title"],
            "reason": gap["reason"],
            "next_slice": gap["next_slice"],
            "rules": sorted(rules_by_gap_id[gap["gap_id"]]),
            "owner_roles": sorted(owner_roles_by_gap_id[gap["gap_id"]]),
            "epic_ids": sorted(epic_ids_by_gap_id[gap["gap_id"]]),
            "slice_ids": list(
                dict.fromkeys(
                    list(gap.get("slice_ids", [])) + list(slice_ids_by_gap_id[gap["gap_id"]])
                )
            ),
            "open_scenario_count": len(scenario_rows),
            "status_counts": status_counts,
            "evidence_summary": gap["evidence_summary"],
            "evidence_code_refs": list(gap["evidence_code_refs"]),
            "evidence_test_refs": list(gap["evidence_test_refs"]),
            "validation_commands": validation_commands,
            "validation_suite": _build_validation_suite_entry(
                selector_args=("--gap-id", gap["gap_id"]),
                validation_commands=validation_commands,
            ),
            "scenarios": scenario_rows,
        }
        implementation_snapshot = gap.get("implementation_snapshot")
        if implementation_snapshot:
            cluster_record["implementation_snapshot"] = dict(implementation_snapshot)
        clusters.append(cluster_record)
    return clusters


def _build_board_blockers(
    board: dict[str, Any],
    *,
    project_root: Path,
) -> list[dict[str, Any]]:
    self_generated_report_refs = {str(REPORT_JSON_PATH), str(REPORT_MD_PATH)}
    blockers: list[dict[str, Any]] = []
    for blocker in board.get("known_blockers", []):
        if not isinstance(blocker, dict):
            continue
        evidence_refs = list(blocker.get("evidence") or [])
        missing_evidence_refs = [
            path_text
            for path_text in evidence_refs
            if path_text not in self_generated_report_refs and not (project_root / path_text).exists()
        ]
        validation_commands = _resolve_validation_commands(
            BOARD_BLOCKER_VALIDATION_COMMAND_IDS.get(
                blocker["blocker_id"], ("qa_acceptance_reports",)
            )
        )
        blockers.append(
            {
                "blocker_id": blocker["blocker_id"],
                "status": blocker.get("status", "open"),
                "severity": blocker.get("severity", "unknown"),
                "owner_role": blocker.get("owner_role", ""),
                "summary": blocker.get("summary", ""),
                "impact": blocker.get("impact"),
                "next_action": blocker.get("next_action"),
                "evidence_refs": evidence_refs,
                "missing_evidence_refs": missing_evidence_refs,
                "validation_commands": validation_commands,
                "validation_suite": _build_validation_suite_entry(
                    selector_args=("--blocker-id", blocker["blocker_id"]),
                    validation_commands=validation_commands,
                ),
            }
        )
    return blockers


def _build_current_focus(
    board: dict[str, Any],
    *,
    acceptance_gap_clusters: list[dict[str, Any]],
) -> dict[str, Any]:
    focus = {
        "epic_id": board.get("current_focus", {}).get("epic_id"),
        "slice_id": board.get("current_focus", {}).get("slice_id"),
        "owner_role": board.get("current_focus", {}).get("owner_role"),
        "reason": board.get("current_focus", {}).get("reason"),
    }
    slice_id = focus.get("slice_id")
    matching_clusters = [
        cluster
        for cluster in acceptance_gap_clusters
        if cluster["open_scenario_count"] and cluster["next_slice"] == slice_id
    ]
    if not matching_clusters:
        return focus

    seen_command_ids: set[str] = set()
    validation_commands: list[dict[str, str]] = []
    for cluster in matching_clusters:
        for command in cluster["validation_commands"]:
            command_id = command["command_id"]
            if command_id in seen_command_ids:
                continue
            seen_command_ids.add(command_id)
            validation_commands.append(command)

    focus["gap_ids"] = [cluster["gap_id"] for cluster in matching_clusters]
    focus["validation_commands"] = validation_commands
    focus["validation_suite"] = _build_validation_suite_entry(
        selector_args=("--current-focus",),
        validation_commands=validation_commands,
    )
    return focus


def build_ba10_blocker_audit(project_root: Path | str) -> dict[str, Any]:
    root = Path(project_root)
    matrix = build_acceptance_trace_matrix(root)
    board = _load_build_board(root)
    acceptance_gap_clusters = _build_acceptance_gap_clusters(matrix)
    board_blockers = _build_board_blockers(board, project_root=root)
    current_focus = _build_current_focus(
        board,
        acceptance_gap_clusters=acceptance_gap_clusters,
    )
    missing_evidence_refs = sum(
        len(blocker["missing_evidence_refs"]) for blocker in board_blockers
    )

    return {
        "blocker_audit_version": BLOCKER_AUDIT_VERSION,
        "sources": {
            "acceptance_trace_report_json": str(TRACE_REPORT_JSON_PATH),
            "acceptance_trace_report_markdown": str(TRACE_REPORT_MD_PATH),
            "build_board": str(BUILD_BOARD_PATH),
        },
        "current_focus": current_focus,
        "summary": {
            "acceptance_scenario_count": matrix["scenario_count"],
            "acceptance_status_counts": dict(matrix["status_counts"]),
            "open_acceptance_scenario_count": matrix["status_counts"][STATUS_PARTIAL]
            + matrix["status_counts"][STATUS_GAP],
            "open_acceptance_gap_cluster_count": len(acceptance_gap_clusters),
            "open_build_board_blocker_count": sum(
                1 for blocker in board_blockers if blocker["status"] == "open"
            ),
            "build_board_blockers_with_missing_evidence": missing_evidence_refs,
        },
        "implemented_slices": list(matrix["implemented_slices"]),
        "acceptance_gap_clusters": acceptance_gap_clusters,
        "build_board_blockers": board_blockers,
    }


def render_ba10_blocker_audit_markdown(audit: dict[str, Any]) -> str:
    summary = audit["summary"]
    current_focus = audit["current_focus"]
    lines = [
        "# BA-10 Blocker Audit",
        "",
        f"- Acceptance scenarios: `{summary['acceptance_scenario_count']}`",
        f"- Open acceptance scenarios: `{summary['open_acceptance_scenario_count']}`",
        f"- Open acceptance gap clusters: `{summary['open_acceptance_gap_cluster_count']}`",
        f"- Open build-board blockers: `{summary['open_build_board_blocker_count']}`",
        f"- Blockers with missing evidence refs: `{summary['build_board_blockers_with_missing_evidence']}`",
        "",
        "## Current Focus",
        "",
        f"- Epic: `{current_focus['epic_id']}`",
        f"- Slice: `{current_focus['slice_id']}`",
        f"- Owner role: `{current_focus['owner_role']}`",
        f"- Reason: {current_focus['reason']}",
    ]
    if current_focus.get("gap_ids"):
        lines.append(
            "- Matching gap ids: "
            + ", ".join(f"`{gap_id}`" for gap_id in current_focus["gap_ids"])
        )
    if current_focus.get("validation_suite"):
        lines.append(
            f"- Validation suite: `{current_focus['validation_suite']['command']}`"
        )
    lines.extend(
        [
        "",
        "## Acceptance Gap Clusters",
        "",
        ]
    )

    for cluster in audit["acceptance_gap_clusters"]:
        status_counts = cluster["status_counts"]
        lines.append(f"### {cluster['gap_id']}: {cluster['title']}")
        lines.append(f"- Next slice: `{cluster['next_slice']}`")
        lines.append(f"- Owner roles: {', '.join(f'`{role}`' for role in cluster['owner_roles'])}")
        lines.append(f"- Rules: {', '.join(f'`{rule}`' for rule in cluster['rules'])}")
        lines.append(f"- Epics: {', '.join(f'`{epic_id}`' for epic_id in cluster['epic_ids'])}")
        lines.append(
            "- Supporting slices: "
            + ", ".join(f"`{slice_id}`" for slice_id in cluster["slice_ids"])
        )
        lines.append(
            f"- Open scenarios: `{cluster['open_scenario_count']}` "
            f"(`partial`: `{status_counts[STATUS_PARTIAL]}`, `gap`: `{status_counts[STATUS_GAP]}`)"
        )
        lines.append(f"- Reason: {cluster['reason']}")
        lines.append(f"- Evidence summary: {cluster['evidence_summary']}")
        lines.append(
            "- Evidence code refs: "
            + ", ".join(f"`{path}`" for path in cluster["evidence_code_refs"])
        )
        lines.append(
            "- Evidence test refs: "
            + ", ".join(f"`{path}`" for path in cluster["evidence_test_refs"])
        )
        lines.append(f"- Validation suite: `{cluster['validation_suite']['command']}`")
        implementation_snapshot = cluster.get("implementation_snapshot") or {}
        if implementation_snapshot:
            lines.append("- Implementation snapshot:")
            selector_priority = implementation_snapshot.get(
                "current_selector_priority_order", []
            )
            if selector_priority:
                lines.append(
                    "  - Current selector priority order: "
                    + ", ".join(f"`{entry}`" for entry in selector_priority)
                )
            registered_stages = implementation_snapshot.get(
                "registered_role_targeted_checkpoint_stages", []
            )
            if registered_stages:
                lines.append(
                    "  - Registered role-targeted checkpoint stages: "
                    + ", ".join(f"`{stage}`" for stage in registered_stages)
                )
            blocked_stages = implementation_snapshot.get(
                "validated_blocked_role_targeted_stages", []
            )
            if blocked_stages:
                lines.append(
                    "  - Validated blocked role-targeted stages: "
                    + ", ".join(f"`{stage}`" for stage in blocked_stages)
                )
            unsupported_paths = implementation_snapshot.get(
                "unsupported_autonomous_scope_paths", []
            )
            if unsupported_paths:
                lines.append(
                    "  - Unsupported autonomous scope paths: "
                    + ", ".join(f"`{path}`" for path in unsupported_paths)
                )
        lines.append("- Confirmation commands:")
        for command in cluster["validation_commands"]:
            lines.append(
                f"  - `{command['command']}` ({command['kind']}: {command['description']})"
            )
        lines.append("- Open scenarios:")
        for scenario in cluster["scenarios"]:
            lines.append(f"  - `[{scenario['status']}]` {scenario['name']}")
        lines.append("")

    lines.extend(["## Build-Board Blockers", ""])
    for blocker in audit["build_board_blockers"]:
        lines.append(f"### {blocker['blocker_id']}")
        lines.append(f"- Status: `{blocker['status']}`")
        lines.append(f"- Severity: `{blocker['severity']}`")
        lines.append(f"- Owner role: `{blocker['owner_role']}`")
        lines.append(f"- Summary: {blocker['summary']}")
        if blocker["impact"]:
            lines.append(f"- Impact: {blocker['impact']}")
        if blocker["next_action"]:
            lines.append(f"- Next action: {blocker['next_action']}")
        if blocker["evidence_refs"]:
            lines.append(
                "- Evidence refs: " + ", ".join(f"`{path}`" for path in blocker["evidence_refs"])
            )
        else:
            lines.append("- Evidence refs: none recorded")
        if blocker["missing_evidence_refs"]:
            lines.append(
                "- Missing evidence refs: "
                + ", ".join(f"`{path}`" for path in blocker["missing_evidence_refs"])
            )
        lines.append(f"- Validation suite: `{blocker['validation_suite']['command']}`")
        lines.append("- Confirmation commands:")
        for command in blocker["validation_commands"]:
            lines.append(
                f"  - `{command['command']}` ({command['kind']}: {command['description']})"
            )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write_ba10_blocker_audit_reports(project_root: Path | str) -> dict[str, str]:
    root = Path(project_root)
    audit = build_ba10_blocker_audit(root)
    json_path = root / REPORT_JSON_PATH
    md_path = root / REPORT_MD_PATH
    json_path.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_ba10_blocker_audit_markdown(audit), encoding="utf-8")
    return {
        "json_path": str(json_path),
        "markdown_path": str(md_path),
    }
