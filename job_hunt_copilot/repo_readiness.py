from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .blocker_audit import BUILD_BOARD_PATH, build_ba10_blocker_audit


REPO_READINESS_REPORT_VERSION = 1
REPORT_JSON_PATH = Path("build-agent/reports/repo-readiness-summary.json")
REPORT_MD_PATH = Path("build-agent/reports/repo-readiness-summary.md")
VALIDATION_SUITE_REPORT_JSON_PATH = Path(
    "build-agent/reports/ba-10-validation-suite-latest.json"
)
VALIDATION_SUITE_REPORT_MD_PATH = Path(
    "build-agent/reports/ba-10-validation-suite-latest.md"
)


@dataclass(frozen=True)
class RepoSurfaceExpectation:
    path: Path
    label: str
    audience: str
    note: str
    required_snippets: tuple[str, ...]
    requires_open_gap_titles: bool = False


REPO_SURFACE_EXPECTATIONS: tuple[RepoSurfaceExpectation, ...] = (
    RepoSurfaceExpectation(
        path=Path("README.md"),
        label="Repo overview",
        audience="recruiters, hiring managers, and first-pass reviewers",
        note=(
            "The repo overview should acknowledge the remaining open BA-10 gap themes "
            "and point readers at the committed readiness evidence."
        ),
        required_snippets=(
            "repo-readiness-summary.md",
        ),
        requires_open_gap_titles=True,
    ),
    RepoSurfaceExpectation(
        path=Path("docs/ARCHITECTURE.md"),
        label="Technical walkthrough",
        audience="engineering managers and technical reviewers",
        note=(
            "The architecture guide should stay honest about the remaining open BA-10 "
            "gap themes and link to the current readiness snapshot."
        ),
        required_snippets=(
            "repo-readiness-summary.md",
        ),
        requires_open_gap_titles=True,
    ),
    RepoSurfaceExpectation(
        path=Path("build-agent/reports/README.md"),
        label="Report index",
        audience="reviewers following the build evidence trail",
        note=(
            "The report index should route reviewers to the readiness summary and the "
            "three canonical BA-10 evidence reports."
        ),
        required_snippets=(
            "repo-readiness-summary.md",
            "ba-10-acceptance-trace-matrix.md",
            "ba-10-blocker-audit.md",
            "ba-10-validation-suite-latest.md",
        ),
    ),
)

RECOMMENDED_REVIEW_PATH: tuple[str, ...] = (
    "README.md",
    "docs/ARCHITECTURE.md",
    "build-agent/reports/repo-readiness-summary.md",
    "build-agent/reports/ba-10-validation-suite-latest.md",
    "build-agent/reports/ba-10-blocker-audit.md",
    "build-agent/reports/ba-10-acceptance-trace-matrix.md",
)

def _load_build_board(project_root: Path) -> dict[str, Any]:
    payload = yaml.safe_load((project_root / BUILD_BOARD_PATH).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected mapping in {BUILD_BOARD_PATH}")
    return payload


def _load_validation_suite_report(project_root: Path) -> dict[str, Any] | None:
    report_path = project_root / VALIDATION_SUITE_REPORT_JSON_PATH
    if not report_path.exists():
        return None
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(
            f"Expected mapping in {VALIDATION_SUITE_REPORT_JSON_PATH}"
        )
    return payload


def _build_validation_selector_summary(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "requested_command_ids": list(payload.get("requested_command_ids") or []),
        "requested_smoke_targets": list(payload.get("requested_smoke_targets") or []),
        "requested_gap_ids": list(payload.get("requested_gap_ids") or []),
        "requested_blocker_ids": list(payload.get("requested_blocker_ids") or []),
        "requested_current_focus": bool(payload.get("requested_current_focus")),
    }


def _build_validation_selector_label(selector_summary: dict[str, Any]) -> str:
    selector_parts: list[str] = []
    if selector_summary["requested_current_focus"]:
        selector_parts.append("current_focus")
    if selector_summary["requested_blocker_ids"]:
        selector_parts.append(
            "blockers: " + ", ".join(selector_summary["requested_blocker_ids"])
        )
    if selector_summary["requested_gap_ids"]:
        selector_parts.append("gaps: " + ", ".join(selector_summary["requested_gap_ids"]))
    if selector_summary["requested_smoke_targets"]:
        selector_parts.append(
            "smoke: " + ", ".join(selector_summary["requested_smoke_targets"])
        )
    if selector_summary["requested_command_ids"]:
        selector_parts.append(
            "commands: " + ", ".join(selector_summary["requested_command_ids"])
        )
    return "; ".join(selector_parts) if selector_parts else "default_automated_plan"


def _build_surface_status(
    project_root: Path,
    expectation: RepoSurfaceExpectation,
    *,
    open_gap_clusters: list[dict[str, Any]],
) -> dict[str, Any]:
    text = (project_root / expectation.path).read_text(encoding="utf-8")
    missing_snippets = [
        snippet for snippet in expectation.required_snippets if snippet not in text
    ]
    required_gap_titles = (
        [cluster["title"] for cluster in open_gap_clusters if cluster.get("title")]
        if expectation.requires_open_gap_titles
        else []
    )
    missing_gap_titles = [
        title for title in required_gap_titles if title not in text
    ]
    return {
        "path": str(expectation.path),
        "label": expectation.label,
        "audience": expectation.audience,
        "note": expectation.note,
        "required_snippets": list(expectation.required_snippets),
        "missing_snippets": missing_snippets,
        "requires_open_gap_titles": expectation.requires_open_gap_titles,
        "required_gap_titles": required_gap_titles,
        "missing_gap_titles": missing_gap_titles,
        "status": (
            "current"
            if not missing_snippets and not missing_gap_titles
            else "stale"
        ),
    }


def _build_latest_validation_snapshot(
    project_root: Path,
    *,
    validation_suite_report: dict[str, Any] | None,
    current_focus: dict[str, Any],
) -> dict[str, Any]:
    payload = validation_suite_report or _load_validation_suite_report(project_root)
    if payload is None:
        return {
            "available": False,
            "generated_at": None,
            "passed": None,
            "command_count": 0,
            "failed_command_count": 0,
            "report_paths": {
                "json_path": str(project_root / VALIDATION_SUITE_REPORT_JSON_PATH),
                "markdown_path": str(project_root / VALIDATION_SUITE_REPORT_MD_PATH),
            },
            "selector_summary": {
                "requested_command_ids": [],
                "requested_smoke_targets": [],
                "requested_gap_ids": [],
                "requested_blocker_ids": [],
                "requested_current_focus": False,
            },
            "selector_label": "unavailable",
            "tracks_current_focus": False,
        }

    summary = payload.get("summary") or {}
    report_paths = payload.get("report_paths") or {
        "json_path": str(project_root / VALIDATION_SUITE_REPORT_JSON_PATH),
        "markdown_path": str(project_root / VALIDATION_SUITE_REPORT_MD_PATH),
    }
    selector_summary = _build_validation_selector_summary(payload)
    selector_details = payload.get("selector_details") or {}
    selector_current_focus = selector_details.get("current_focus") or {}
    tracks_current_focus = bool(
        current_focus.get("slice_id")
        and selector_summary["requested_current_focus"]
        and selector_current_focus.get("epic_id") == current_focus.get("epic_id")
        and selector_current_focus.get("slice_id") == current_focus.get("slice_id")
        and selector_current_focus.get("owner_role") == current_focus.get("owner_role")
    )
    return {
        "available": True,
        "generated_at": payload.get("generated_at"),
        "passed": payload.get("passed"),
        "command_count": summary.get("command_count"),
        "failed_command_count": summary.get("failed_command_count"),
        "report_paths": report_paths,
        "selector_summary": selector_summary,
        "selector_label": _build_validation_selector_label(selector_summary),
        "tracks_current_focus": tracks_current_focus,
    }


def build_repo_readiness_report(
    project_root: Path | str,
    *,
    validation_suite_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = Path(project_root)
    board = _load_build_board(root)
    audit = build_ba10_blocker_audit(root)
    current_focus = audit["current_focus"]
    latest_validation = _build_latest_validation_snapshot(
        root,
        validation_suite_report=validation_suite_report,
        current_focus=current_focus,
    )

    epics = [
        epic for epic in board.get("epics", []) if isinstance(epic, dict) and epic.get("id")
    ]
    completed_epic_ids = [epic["id"] for epic in epics if epic.get("status") == "completed"]
    in_progress_epic_ids = [
        epic["id"] for epic in epics if epic.get("status") == "in_progress"
    ]

    open_gap_clusters = [
        {
            "gap_id": cluster["gap_id"],
            "title": cluster["title"],
            "open_scenario_count": cluster["open_scenario_count"],
            "status_counts": dict(cluster.get("status_counts") or {}),
            "next_slice": cluster["next_slice"],
            "reason": cluster["reason"],
        }
        for cluster in audit["acceptance_gap_clusters"]
        if cluster.get("open_scenario_count")
    ]
    repo_surfaces = [
        _build_surface_status(
            root,
            expectation,
            open_gap_clusters=open_gap_clusters,
        )
        for expectation in REPO_SURFACE_EXPECTATIONS
    ]
    surface_status = "current" if all(
        surface["status"] == "current" for surface in repo_surfaces
    ) else "stale"
    open_blockers = [
        {
            "blocker_id": blocker["blocker_id"],
            "severity": blocker["severity"],
            "owner_role": blocker["owner_role"],
            "summary": blocker["summary"],
            "next_action": blocker.get("next_action"),
        }
        for blocker in audit["build_board_blockers"]
        if blocker.get("status") == "open"
    ]

    summary = audit["summary"]
    return {
        "repo_readiness_report_version": REPO_READINESS_REPORT_VERSION,
        "generated_at": latest_validation["generated_at"],
        "project_root": str(root),
        "sources": {
            "build_board": str(BUILD_BOARD_PATH),
            "blocker_audit": "build-agent/reports/ba-10-blocker-audit.json",
            "validation_suite_latest": str(VALIDATION_SUITE_REPORT_JSON_PATH),
        },
        "surface_status": surface_status,
        "current_focus": {
            "epic_id": current_focus.get("epic_id"),
            "slice_id": current_focus.get("slice_id"),
            "owner_role": current_focus.get("owner_role"),
            "reason": current_focus.get("reason"),
        },
        "implementation_status": {
            "current_phase": board.get("global_status", {}).get("current_phase"),
            "completed_epic_ids": completed_epic_ids,
            "in_progress_epic_ids": in_progress_epic_ids,
        },
        "latest_validation": latest_validation,
        "acceptance_status": {
            "scenario_count": summary["acceptance_scenario_count"],
            "status_counts": dict(summary["acceptance_status_counts"]),
            "open_scenario_count": summary["open_acceptance_scenario_count"],
            "open_gap_ids": [cluster["gap_id"] for cluster in open_gap_clusters],
        },
        "open_gap_clusters": open_gap_clusters,
        "open_blockers": open_blockers,
        "recommended_review_path": list(RECOMMENDED_REVIEW_PATH),
        "repo_surfaces": repo_surfaces,
    }


def render_repo_readiness_markdown(report: dict[str, Any]) -> str:
    current_focus = report["current_focus"]
    implementation_status = report["implementation_status"]
    latest_validation = report["latest_validation"]
    acceptance_status = report["acceptance_status"]

    lines = [
        "# Repo Readiness Summary",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- Project root: `{report['project_root']}`",
        f"- Repo surface status: `{report['surface_status']}`",
        "- Current build focus: "
        f"`{current_focus['epic_id']}` / "
        f"`{current_focus['slice_id']}` / "
        f"`{current_focus['owner_role']}`",
        f"- Current implementation phase: `{implementation_status['current_phase']}`",
        "- Completed epics in code: "
        + ", ".join(
            f"`{epic_id}`" for epic_id in implementation_status["completed_epic_ids"]
        ),
        "- In-progress epics: "
        + ", ".join(
            f"`{epic_id}`" for epic_id in implementation_status["in_progress_epic_ids"]
        ),
        "",
        "## Latest Validation",
        "",
    ]

    if latest_validation["available"]:
        lines.extend(
            [
                f"- Generated at: `{latest_validation['generated_at']}`",
                f"- Passed: `{latest_validation['passed']}`",
                f"- Command count: `{latest_validation['command_count']}`",
                f"- Failed command count: `{latest_validation['failed_command_count']}`",
                f"- Validation selector: `{latest_validation['selector_label']}`",
                f"- Tracks active focus: `{latest_validation['tracks_current_focus']}`",
                "- Validation suite report: "
                f"`{latest_validation['report_paths']['markdown_path']}`",
            ]
        )
    else:
        lines.append("- Latest validation suite report: unavailable")

    lines.extend(
        [
            "",
            "## Acceptance Snapshot",
            "",
            f"- Acceptance scenarios: `{acceptance_status['scenario_count']}`",
            f"- Open acceptance scenarios: `{acceptance_status['open_scenario_count']}`",
            "- Acceptance status counts: "
            + ", ".join(
                f"`{status}`={count}"
                for status, count in acceptance_status["status_counts"].items()
            ),
            "- Open gap ids: "
            + ", ".join(f"`{gap_id}`" for gap_id in acceptance_status["open_gap_ids"]),
            "",
            "## Remaining Gaps",
            "",
        ]
    )

    for cluster in report["open_gap_clusters"]:
        lines.append(
            "- "
            f"`{cluster['gap_id']}`: {cluster['title']} "
            f"(`{cluster['open_scenario_count']}` scenarios; next slice `{cluster['next_slice']}`)"
        )

    lines.extend(["", "## Open Blockers", ""])
    for blocker in report["open_blockers"]:
        lines.append(
            "- "
            f"`{blocker['blocker_id']}` (`{blocker['severity']}`, `{blocker['owner_role']}`): "
            f"{blocker['summary']}"
        )
        if blocker.get("next_action"):
            lines.append(f"  Next action: {blocker['next_action']}")

    lines.extend(["", "## Review Path", ""])
    for index, path_text in enumerate(report["recommended_review_path"], start=1):
        lines.append(f"{index}. `{path_text}`")

    lines.extend(["", "## Repo Surfaces", ""])
    for surface in report["repo_surfaces"]:
        lines.append(
            "- "
            f"`{surface['path']}`: `{surface['status']}` for {surface['audience']}. "
            f"{surface['note']}"
        )
        if surface["missing_snippets"]:
            lines.append(
                "  Missing snippets: "
                + ", ".join(f"`{snippet}`" for snippet in surface["missing_snippets"])
            )
        if surface["missing_gap_titles"]:
            lines.append(
                "  Missing open gap titles: "
                + ", ".join(
                    f"`{title}`" for title in surface["missing_gap_titles"]
                )
            )

    return "\n".join(lines).rstrip() + "\n"


def write_repo_readiness_reports(
    project_root: Path | str,
    *,
    validation_suite_report: dict[str, Any] | None = None,
) -> dict[str, str]:
    root = Path(project_root)
    report = build_repo_readiness_report(
        root,
        validation_suite_report=validation_suite_report,
    )
    json_path = root / REPORT_JSON_PATH
    md_path = root / REPORT_MD_PATH
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_repo_readiness_markdown(report), encoding="utf-8")
    return {
        "json_path": str(json_path),
        "markdown_path": str(md_path),
    }
