from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from .acceptance_traceability import SMOKE_COVERAGE_TARGETS
from .acceptance_traceability import write_acceptance_trace_reports
from .blocker_audit import (
    VALIDATION_COMMANDS,
    build_ba10_blocker_audit,
    write_ba10_blocker_audit_reports,
)


AUTOMATED_VALIDATION_KIND = "automated"
VALIDATION_SUITE_REPORT_VERSION = 2
VALIDATION_SUITE_REPORT_JSON_PATH = Path(
    "build-agent/reports/ba-10-validation-suite-latest.json"
)
VALIDATION_SUITE_REPORT_MD_PATH = Path(
    "build-agent/reports/ba-10-validation-suite-latest.md"
)


@dataclass(frozen=True)
class QualityValidationCommand:
    command_id: str
    title: str
    kind: str
    command: str
    description: str

    def as_dict(self) -> dict[str, str]:
        return {
            "command_id": self.command_id,
            "title": self.title,
            "kind": self.kind,
            "command": self.command,
            "description": self.description,
        }


@dataclass(frozen=True)
class SmokeValidationTarget:
    target_id: str
    title: str
    acceptance_scenario: str
    acceptance_checks: tuple[str, ...]
    validation_command_ids: tuple[str, ...]
    test_refs: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "target_id": self.target_id,
            "title": self.title,
            "acceptance_scenario": self.acceptance_scenario,
            "acceptance_checks": list(self.acceptance_checks),
            "validation_command_ids": list(self.validation_command_ids),
            "test_refs": list(self.test_refs),
        }


def list_quality_validation_commands(*, include_manual: bool = True) -> list[QualityValidationCommand]:
    commands: list[QualityValidationCommand] = []
    for command_id, metadata in VALIDATION_COMMANDS.items():
        if not include_manual and metadata["kind"] != AUTOMATED_VALIDATION_KIND:
            continue
        commands.append(
            QualityValidationCommand(
                command_id=command_id,
                title=metadata["title"],
                kind=metadata["kind"],
                command=metadata["command"],
                description=metadata["description"],
            )
        )
    return commands


def list_smoke_validation_targets() -> list[SmokeValidationTarget]:
    return [
        SmokeValidationTarget(
            target_id=target["target_id"],
            title=target["title"],
            acceptance_scenario=target["acceptance_scenario"],
            acceptance_checks=tuple(target["acceptance_checks"]),
            validation_command_ids=tuple(target["validation_command_ids"]),
            test_refs=tuple(target["test_refs"]),
        )
        for target in SMOKE_COVERAGE_TARGETS
    ]


def _dedupe_values(values: Sequence[str]) -> list[str]:
    resolved: list[str] = []
    seen_values: set[str] = set()
    for value in values:
        if value in seen_values:
            continue
        seen_values.add(value)
        resolved.append(value)
    return resolved


def _dedupe_command_ids(command_ids: Sequence[str]) -> list[str]:
    return _dedupe_values(command_ids)


def _resolve_audit_validation_command_ids(
    entries: Sequence[dict[str, Any]],
    *,
    entry_key: str,
    requested_ids: Sequence[str],
    entry_label: str,
) -> list[str]:
    entries_by_id = {
        entry[entry_key]: entry for entry in entries if entry.get(entry_key)
    }
    resolved_command_ids: list[str] = []
    for requested_id in requested_ids:
        entry = entries_by_id.get(requested_id)
        if entry is None:
            raise ValueError(f"Unknown BA-10 {entry_label}: {requested_id}")
        resolved_command_ids.extend(
            command["command_id"] for command in entry["validation_commands"]
        )
    return _dedupe_command_ids(resolved_command_ids)


def resolve_acceptance_gap_validation_command_ids(
    project_root: Path | str,
    gap_ids: Sequence[str],
) -> list[str]:
    audit = build_ba10_blocker_audit(project_root)
    return _resolve_audit_validation_command_ids(
        audit["acceptance_gap_clusters"],
        entry_key="gap_id",
        requested_ids=gap_ids,
        entry_label="acceptance gap",
    )


def resolve_build_board_blocker_validation_command_ids(
    project_root: Path | str,
    blocker_ids: Sequence[str],
) -> list[str]:
    audit = build_ba10_blocker_audit(project_root)
    return _resolve_audit_validation_command_ids(
        audit["build_board_blockers"],
        entry_key="blocker_id",
        requested_ids=blocker_ids,
        entry_label="build-board blocker",
    )


def resolve_current_focus_validation_command_ids(project_root: Path | str) -> list[str]:
    audit = build_ba10_blocker_audit(project_root)
    current_focus = audit["current_focus"]
    validation_commands = current_focus.get("validation_commands") or []
    if not validation_commands:
        slice_id = current_focus.get("slice_id") or "<unknown>"
        raise ValueError(
            f"Current focus slice `{slice_id}` has no recorded BA-10 validation commands."
        )
    return _dedupe_command_ids(
        [command["command_id"] for command in validation_commands]
    )


def resolve_validation_selector_details(
    project_root: Path | str,
    *,
    smoke_target_ids: Sequence[str] | None = None,
    gap_ids: Sequence[str] | None = None,
    blocker_ids: Sequence[str] | None = None,
    include_current_focus: bool = False,
) -> dict[str, Any]:
    details: dict[str, Any] = {
        "smoke_targets": [],
        "acceptance_gaps": [],
        "build_board_blockers": [],
        "current_focus": None,
    }

    requested_smoke_target_ids = _dedupe_values(list(smoke_target_ids or ()))
    if requested_smoke_target_ids:
        available_targets = {
            target.target_id: target.as_dict() for target in list_smoke_validation_targets()
        }
        for target_id in requested_smoke_target_ids:
            target = available_targets.get(target_id)
            if target is None:
                raise ValueError(f"Unknown smoke validation target: {target_id}")
            details["smoke_targets"].append(target)

    requested_gap_ids = _dedupe_values(list(gap_ids or ()))
    requested_blocker_ids = _dedupe_values(list(blocker_ids or ()))
    if not (requested_gap_ids or requested_blocker_ids or include_current_focus):
        return details

    audit = build_ba10_blocker_audit(project_root)
    gaps_by_id = {
        cluster["gap_id"]: cluster for cluster in audit["acceptance_gap_clusters"]
    }
    blockers_by_id = {
        blocker["blocker_id"]: blocker for blocker in audit["build_board_blockers"]
    }

    for gap_id in requested_gap_ids:
        cluster = gaps_by_id.get(gap_id)
        if cluster is None:
            raise ValueError(f"Unknown BA-10 acceptance gap: {gap_id}")
        details["acceptance_gaps"].append(
            {
                "gap_id": cluster["gap_id"],
                "title": cluster["title"],
                "next_slice": cluster["next_slice"],
                "open_scenario_count": cluster["open_scenario_count"],
                "validation_command_ids": [
                    command["command_id"] for command in cluster["validation_commands"]
                ],
                "validation_suite_command": cluster["validation_suite"]["command"],
            }
        )

    for blocker_id in requested_blocker_ids:
        blocker = blockers_by_id.get(blocker_id)
        if blocker is None:
            raise ValueError(f"Unknown BA-10 build-board blocker: {blocker_id}")
        details["build_board_blockers"].append(
            {
                "blocker_id": blocker["blocker_id"],
                "status": blocker["status"],
                "owner_role": blocker["owner_role"],
                "summary": blocker["summary"],
                "validation_command_ids": [
                    command["command_id"] for command in blocker["validation_commands"]
                ],
                "validation_suite_command": blocker["validation_suite"]["command"],
            }
        )

    if include_current_focus:
        current_focus = audit["current_focus"]
        details["current_focus"] = {
            "epic_id": current_focus.get("epic_id"),
            "slice_id": current_focus.get("slice_id"),
            "owner_role": current_focus.get("owner_role"),
            "reason": current_focus.get("reason"),
            "gap_ids": list(current_focus.get("gap_ids") or []),
            "validation_command_ids": [
                command["command_id"]
                for command in current_focus.get("validation_commands", [])
            ],
            "validation_suite_command": (
                current_focus.get("validation_suite", {}) or {}
            ).get("command"),
        }

    return details


def build_smoke_validation_plan(
    smoke_target_ids: Sequence[str] | None = None,
) -> list[QualityValidationCommand]:
    available_targets = {target.target_id: target for target in list_smoke_validation_targets()}
    requested_target_ids = (
        list(smoke_target_ids)
        if smoke_target_ids
        else [target.target_id for target in available_targets.values()]
    )

    command_ids: list[str] = []
    for target_id in requested_target_ids:
        target = available_targets.get(target_id)
        if target is None:
            raise ValueError(f"Unknown smoke validation target: {target_id}")
        command_ids.extend(target.validation_command_ids)

    return build_quality_validation_plan(command_ids)


def build_quality_validation_plan(
    command_ids: Sequence[str] | None = None,
    *,
    include_manual: bool = False,
) -> list[QualityValidationCommand]:
    if not command_ids:
        return list_quality_validation_commands(include_manual=False)

    seen_command_ids: set[str] = set()
    plan: list[QualityValidationCommand] = []
    for command_id in command_ids:
        if command_id in seen_command_ids:
            continue
        seen_command_ids.add(command_id)

        metadata = VALIDATION_COMMANDS.get(command_id)
        if metadata is None:
            raise ValueError(f"Unknown quality validation command: {command_id}")

        if metadata["kind"] != AUTOMATED_VALIDATION_KIND and not include_manual:
            raise ValueError(
                f"Quality validation command `{command_id}` is `{metadata['kind']}` and "
                "requires `include_manual=True`."
            )

        plan.append(
            QualityValidationCommand(
                command_id=command_id,
                title=metadata["title"],
                kind=metadata["kind"],
                command=metadata["command"],
                description=metadata["description"],
            )
        )
    return plan


def refresh_ba10_validation_reports(project_root: Path | str) -> dict[str, Any]:
    root = Path(project_root)
    return {
        "acceptance_trace_reports": write_acceptance_trace_reports(root),
        "blocker_audit_reports": write_ba10_blocker_audit_reports(root),
    }


def _utc_timestamp() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _build_repo_status_snapshot(project_root: Path | str) -> dict[str, Any] | None:
    root = Path(project_root)
    try:
        audit = build_ba10_blocker_audit(root)
    except (FileNotFoundError, NotADirectoryError, OSError, ValueError):
        return None

    summary = dict(audit["summary"])
    open_gap_ids = [
        cluster["gap_id"]
        for cluster in audit["acceptance_gap_clusters"]
        if cluster.get("open_scenario_count")
    ]
    open_blocker_ids = [
        blocker["blocker_id"]
        for blocker in audit["build_board_blockers"]
        if blocker.get("status") == "open"
    ]
    current_focus = audit.get("current_focus") or {}
    return {
        "acceptance_scenario_count": summary.get("acceptance_scenario_count"),
        "acceptance_status_counts": dict(summary.get("acceptance_status_counts") or {}),
        "open_acceptance_scenario_count": summary.get("open_acceptance_scenario_count"),
        "open_acceptance_gap_cluster_count": summary.get(
            "open_acceptance_gap_cluster_count"
        ),
        "open_acceptance_gap_ids": open_gap_ids,
        "open_build_board_blocker_count": summary.get(
            "open_build_board_blocker_count"
        ),
        "open_build_board_blocker_ids": open_blocker_ids,
        "current_focus": {
            "epic_id": current_focus.get("epic_id"),
            "slice_id": current_focus.get("slice_id"),
            "owner_role": current_focus.get("owner_role"),
        },
    }


def build_ba10_validation_suite_report(
    payload: dict[str, Any],
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    commands = [dict(command) for command in payload.get("commands", [])]
    command_kind_counts: dict[str, int] = {}
    passed_command_count = 0
    failed_command_count = 0
    total_duration_seconds = 0.0

    for command in commands:
        kind = str(command.get("kind", "unknown"))
        command_kind_counts[kind] = command_kind_counts.get(kind, 0) + 1

        if command.get("status") == "passed":
            passed_command_count += 1
        elif command.get("status") == "failed":
            failed_command_count += 1

        duration_seconds = command.get("duration_seconds")
        if isinstance(duration_seconds, (int, float)):
            total_duration_seconds += float(duration_seconds)

    report = dict(payload)
    report["validation_suite_report_version"] = VALIDATION_SUITE_REPORT_VERSION
    report["generated_at"] = generated_at or _utc_timestamp()
    report["summary"] = {
        "command_count": len(commands),
        "command_kind_counts": command_kind_counts,
        "passed_command_count": passed_command_count,
        "failed_command_count": failed_command_count,
        "total_duration_seconds": round(total_duration_seconds, 3),
    }
    repo_status = report.get("repo_status")
    if repo_status is None:
        repo_status = _build_repo_status_snapshot(report["project_root"])
    if repo_status is not None:
        report["repo_status"] = repo_status
    return report


def _selector_value_text(values: Sequence[str] | None) -> str:
    if not values:
        return "none"
    return ", ".join(f"`{value}`" for value in values)


def render_ba10_validation_suite_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    refreshed_reports = report.get("refreshed_reports") or {}
    selector_details = report.get("selector_details") or {}
    lines = [
        "# BA-10 Validation Suite Report",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- Project root: `{report['project_root']}`",
        f"- Passed: `{report.get('passed', False)}`",
        f"- Command count: `{summary['command_count']}`",
        f"- Passed commands: `{summary['passed_command_count']}`",
        f"- Failed commands: `{summary['failed_command_count']}`",
        f"- Total duration seconds: `{summary['total_duration_seconds']}`",
        f"- Requested command ids: {_selector_value_text(report.get('requested_command_ids'))}",
        f"- Requested smoke targets: {_selector_value_text(report.get('requested_smoke_targets'))}",
        f"- Requested acceptance gaps: {_selector_value_text(report.get('requested_gap_ids'))}",
        f"- Requested build-board blockers: {_selector_value_text(report.get('requested_blocker_ids'))}",
        f"- Current focus requested: `{report.get('requested_current_focus', False)}`",
        f"- Include manual commands: `{report.get('include_manual', False)}`",
        f"- Refresh reports before run: `{not report.get('skip_report_refresh', False)}`",
    ]

    if report.get("failed_command_ids"):
        lines.append(
            "- Failed command ids: "
            + _selector_value_text(report.get("failed_command_ids"))
        )

    lines.extend(["", "## Command Kind Counts", ""])
    for kind, count in summary["command_kind_counts"].items():
        lines.append(f"- `{kind}`: `{count}`")

    if refreshed_reports:
        lines.extend(["", "## Refreshed Reports", ""])
        acceptance_trace_reports = refreshed_reports.get("acceptance_trace_reports") or {}
        blocker_audit_reports = refreshed_reports.get("blocker_audit_reports") or {}
        if acceptance_trace_reports:
            lines.append(
                "- Acceptance trace JSON: "
                f"`{acceptance_trace_reports.get('json_path', '')}`"
            )
            lines.append(
                "- Acceptance trace markdown: "
                f"`{acceptance_trace_reports.get('markdown_path', '')}`"
            )
        if blocker_audit_reports:
            lines.append(
                "- Blocker audit JSON: "
                f"`{blocker_audit_reports.get('json_path', '')}`"
            )
            lines.append(
                "- Blocker audit markdown: "
                f"`{blocker_audit_reports.get('markdown_path', '')}`"
            )

    repo_status = report.get("repo_status") or {}
    if repo_status:
        status_counts = repo_status.get("acceptance_status_counts") or {}
        lines.extend(["", "## Open BA-10 Status", ""])
        lines.append(
            f"- Acceptance scenarios: `{repo_status.get('acceptance_scenario_count')}`"
        )
        lines.append(
            f"- Open acceptance scenarios: `{repo_status.get('open_acceptance_scenario_count')}`"
        )
        lines.append(
            "- Acceptance status counts: "
            + ", ".join(
                f"`{status}`={count}" for status, count in status_counts.items()
            )
        )
        lines.append(
            "- Open acceptance gap clusters: "
            f"`{repo_status.get('open_acceptance_gap_cluster_count')}`"
        )
        lines.append(
            "- Open acceptance gap ids: "
            + _selector_value_text(repo_status.get("open_acceptance_gap_ids"))
        )
        lines.append(
            "- Open build-board blockers: "
            f"`{repo_status.get('open_build_board_blocker_count')}`"
        )
        lines.append(
            "- Open build-board blocker ids: "
            + _selector_value_text(repo_status.get("open_build_board_blocker_ids"))
        )
        current_focus_snapshot = repo_status.get("current_focus") or {}
        if current_focus_snapshot.get("slice_id"):
            lines.append(
                "- Current build focus: "
                f"`{current_focus_snapshot.get('epic_id')}` / "
                f"`{current_focus_snapshot.get('slice_id')}` / "
                f"`{current_focus_snapshot.get('owner_role')}`"
            )

    smoke_targets = selector_details.get("smoke_targets") or []
    acceptance_gaps = selector_details.get("acceptance_gaps") or []
    build_board_blockers = selector_details.get("build_board_blockers") or []
    current_focus = selector_details.get("current_focus")
    if smoke_targets or acceptance_gaps or build_board_blockers or current_focus:
        lines.extend(["", "## Selector Details", ""])

        if smoke_targets:
            lines.extend(["### Smoke Targets", ""])
            for target in smoke_targets:
                lines.append(f"- `{target['target_id']}`: {target['title']}")
                lines.append(
                    f"  - Acceptance scenario: `{target['acceptance_scenario']}`"
                )
                lines.append(
                    "  - Acceptance checks: "
                    + "; ".join(target.get("acceptance_checks", []))
                )
                lines.append(
                    "  - Validation command ids: "
                    + ", ".join(
                        f"`{command_id}`"
                        for command_id in target.get("validation_command_ids", [])
                    )
                )
                lines.append(
                    "  - Test refs: "
                    + ", ".join(
                        f"`{test_ref}`" for test_ref in target.get("test_refs", [])
                    )
                )
            lines.append("")

        if acceptance_gaps:
            lines.extend(["### Acceptance Gaps", ""])
            for gap in acceptance_gaps:
                lines.append(f"- `{gap['gap_id']}`: {gap['title']}")
                lines.append(f"  - Next slice: `{gap['next_slice']}`")
                lines.append(
                    f"  - Open scenario count: `{gap['open_scenario_count']}`"
                )
                lines.append(
                    "  - Validation command ids: "
                    + ", ".join(
                        f"`{command_id}`"
                        for command_id in gap.get("validation_command_ids", [])
                    )
                )
                lines.append(
                    "  - Validation suite: "
                    f"`{gap.get('validation_suite_command', '')}`"
                )
            lines.append("")

        if build_board_blockers:
            lines.extend(["### Build-Board Blockers", ""])
            for blocker in build_board_blockers:
                lines.append(f"- `{blocker['blocker_id']}`: {blocker['summary']}")
                lines.append(f"  - Status: `{blocker['status']}`")
                lines.append(f"  - Owner role: `{blocker['owner_role']}`")
                lines.append(
                    "  - Validation command ids: "
                    + ", ".join(
                        f"`{command_id}`"
                        for command_id in blocker.get("validation_command_ids", [])
                    )
                )
                lines.append(
                    "  - Validation suite: "
                    f"`{blocker.get('validation_suite_command', '')}`"
                )
            lines.append("")

        if current_focus:
            lines.extend(["### Current Focus", ""])
            lines.append(f"- Epic: `{current_focus.get('epic_id')}`")
            lines.append(f"- Slice: `{current_focus.get('slice_id')}`")
            lines.append(f"- Owner role: `{current_focus.get('owner_role')}`")
            lines.append(f"- Reason: {current_focus.get('reason')}")
            lines.append(
                "- Gap ids: "
                + _selector_value_text(current_focus.get("gap_ids"))
            )
            lines.append(
                "- Validation command ids: "
                + _selector_value_text(current_focus.get("validation_command_ids"))
            )
            lines.append(
                "- Validation suite: "
                f"`{current_focus.get('validation_suite_command', '')}`"
            )

    lines.extend(
        [
            "",
            "## Command Results",
            "",
            "| Command | Kind | Status | Returncode | Duration (s) |",
            "| --- | --- | --- | ---: | ---: |",
        ]
    )
    for command in report.get("commands", []):
        returncode = command.get("returncode")
        duration_seconds = command.get("duration_seconds")
        duration_text = (
            f"{duration_seconds:.3f}"
            if isinstance(duration_seconds, (int, float))
            else ""
        )
        lines.append(
            "| "
            + f"{command['command_id']} | {command.get('kind', '')} | "
            + f"{command.get('status', 'planned')} | "
            + f"{'' if returncode is None else returncode} | {duration_text} |"
        )

    lines.extend(["", "## Command Details", ""])
    for command in report.get("commands", []):
        lines.append(f"### {command['command_id']}: {command['title']}")
        lines.append(f"- Kind: `{command.get('kind', '')}`")
        if command.get("status"):
            lines.append(f"- Status: `{command['status']}`")
        if "returncode" in command:
            lines.append(f"- Returncode: `{command['returncode']}`")
        if "duration_seconds" in command:
            lines.append(f"- Duration seconds: `{command['duration_seconds']}`")
        lines.append(f"- Command: `{command['command']}`")
        lines.append(f"- Description: {command['description']}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write_ba10_validation_suite_reports(
    project_root: Path | str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    root = Path(project_root)
    report = build_ba10_validation_suite_report(payload)
    json_path = root / VALIDATION_SUITE_REPORT_JSON_PATH
    md_path = root / VALIDATION_SUITE_REPORT_MD_PATH
    json_path.parent.mkdir(parents=True, exist_ok=True)
    report["report_paths"] = {
        "json_path": str(json_path),
        "markdown_path": str(md_path),
    }
    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_ba10_validation_suite_markdown(report), encoding="utf-8")
    return report
