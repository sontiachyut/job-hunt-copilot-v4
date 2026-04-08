from __future__ import annotations

from dataclasses import dataclass
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


def _dedupe_command_ids(command_ids: Sequence[str]) -> list[str]:
    resolved: list[str] = []
    seen_command_ids: set[str] = set()
    for command_id in command_ids:
        if command_id in seen_command_ids:
            continue
        seen_command_ids.add(command_id)
        resolved.append(command_id)
    return resolved


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
