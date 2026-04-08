from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from .acceptance_traceability import SMOKE_COVERAGE_TARGETS
from .acceptance_traceability import write_acceptance_trace_reports
from .blocker_audit import VALIDATION_COMMANDS, write_ba10_blocker_audit_reports


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
