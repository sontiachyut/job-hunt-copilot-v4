from __future__ import annotations

import json
import shlex
import sqlite3
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .contracts import CONTRACT_VERSION
from .paths import ProjectPaths, workspace_slug
from .records import new_canonical_id, now_utc_iso


MAINTENANCE_COMPONENT = "maintenance_automation"

MAINTENANCE_STATUS_IN_PROGRESS = "in_progress"
MAINTENANCE_STATUS_VALIDATED = "validated"
MAINTENANCE_STATUS_MERGED = "merged"
MAINTENANCE_STATUS_FAILED = "failed"
MAINTENANCE_STATUS_RETAINED_FOR_REVIEW = "retained_for_review"

MAINTENANCE_APPROVAL_PENDING = "pending"
MAINTENANCE_APPROVAL_APPROVED = "approved"
MAINTENANCE_APPROVAL_NOT_APPROVED = "not_approved"
MAINTENANCE_APPROVAL_FAILED_VALIDATION = "failed_validation"

VALIDATION_SCOPE_CHANGE_SCOPED = "change_scoped"
VALIDATION_SCOPE_FULL_SYSTEM = "full_system"


class MaintenanceStateError(ValueError):
    """Raised when maintenance state or workflow inputs are invalid."""


class MaintenanceChangeApplier(Protocol):
    def __call__(self, worktree_path: Path) -> None: ...


CommandRunner = Callable[[tuple[str, ...], Path], subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class MaintenanceValidationCommand:
    label: str
    args: tuple[str, ...]

    @property
    def command(self) -> str:
        return shlex.join(self.args)


@dataclass(frozen=True)
class MaintenanceValidationResult:
    scope: str
    label: str
    command: str
    passed: bool
    summary: str
    returncode: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "label": self.label,
            "command": self.command,
            "passed": self.passed,
            "summary": self.summary,
            "returncode": self.returncode,
        }


@dataclass(frozen=True)
class MaintenancePlan:
    scope_slug: str
    short_reason: str
    notes: str | None = None
    change_scoped_validation: tuple[MaintenanceValidationCommand, ...] = ()
    full_system_validation: tuple[MaintenanceValidationCommand, ...] = ()
    related_incident_ids: tuple[str, ...] = ()
    related_review_packet_ids: tuple[str, ...] = ()
    apply_changes: MaintenanceChangeApplier | None = None


@dataclass(frozen=True)
class MaintenanceDependencies:
    plan: MaintenancePlan
    command_runner: CommandRunner | None = None


@dataclass(frozen=True)
class MaintenanceBatchRecord:
    maintenance_change_batch_id: str
    branch_name: str
    scope_slug: str
    status: str
    approval_outcome: str
    summary_path: str
    json_path: str
    head_commit_sha: str | None
    merged_commit_sha: str | None
    merge_commit_message: str | None
    validated_at: str | None
    approved_at: str | None
    merged_at: str | None
    failed_at: str | None
    validation_summary: str | None
    expert_review_packet_id: str | None
    created_at: str


@dataclass(frozen=True)
class MaintenanceBatchExecution:
    batch: MaintenanceBatchRecord
    json_path: str
    markdown_path: str


def _resolve_local_timezone(local_timezone: str | timezone | None) -> timezone | ZoneInfo:
    if local_timezone is None:
        resolved = datetime.now().astimezone().tzinfo
        return resolved if resolved is not None else timezone.utc
    if isinstance(local_timezone, timezone):
        return local_timezone
    try:
        return ZoneInfo(str(local_timezone))
    except ZoneInfoNotFoundError as exc:
        raise MaintenanceStateError(
            f"Unknown local timezone for maintenance: {local_timezone!r}."
        ) from exc


def maintenance_local_day(
    current_time: str,
    *,
    local_timezone: str | timezone | None = None,
) -> str:
    resolved_timezone = _resolve_local_timezone(local_timezone)
    return _parse_utc_iso(current_time).astimezone(resolved_timezone).strftime("%Y%m%d")


def is_daily_maintenance_due(
    connection: sqlite3.Connection,
    *,
    current_time: str,
    local_timezone: str | timezone | None = None,
) -> bool:
    local_day = maintenance_local_day(
        current_time,
        local_timezone=local_timezone,
    )
    rows = connection.execute(
        """
        SELECT created_at
        FROM maintenance_change_batches
        ORDER BY created_at DESC, maintenance_change_batch_id DESC
        """
    ).fetchall()
    return not any(
        maintenance_local_day(str(row["created_at"]), local_timezone=local_timezone) == local_day
        for row in rows
    )


def build_default_maintenance_plan(project_root: Path | str) -> MaintenancePlan:
    root = Path(project_root)
    if not (root / "tests").exists() or not (root / "job_hunt_copilot").exists():
        raise MaintenanceStateError(
            "Default maintenance plan requires the source tree and test suite."
        )
    return MaintenancePlan(
        scope_slug="daily-healthcheck",
        short_reason=(
            "Run the bounded daily maintenance healthcheck, preserve the isolated "
            "git checkpoint, and wait for explicit approval before merge."
        ),
        notes=(
            "This default maintenance batch is review-first by design: it creates an "
            "isolated branch checkpoint, runs bounded validation, and records the "
            "approval state without auto-merging."
        ),
        full_system_validation=(
            MaintenanceValidationCommand(
                label="supervisor-and-readiness-regressions",
                args=(
                    "python3.11",
                    "-m",
                    "pytest",
                    "tests/test_runtime_pack.py",
                    "tests/test_supervisor_downstream_actions.py",
                    "tests/test_quality_validation.py",
                    "tests/test_blocker_audit.py",
                    "tests/test_repo_readiness.py",
                ),
            ),
        ),
    )


def run_daily_maintenance_cycle(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    current_time: str,
    local_timezone: str | timezone | None = None,
    dependencies: MaintenanceDependencies,
) -> MaintenanceBatchExecution:
    if not is_daily_maintenance_due(
        connection,
        current_time=current_time,
        local_timezone=local_timezone,
    ):
        raise MaintenanceStateError("A maintenance batch already exists for this local day.")

    plan = dependencies.plan
    scope_slug = workspace_slug(plan.scope_slug)
    local_day = maintenance_local_day(current_time, local_timezone=local_timezone)
    batch_id = new_canonical_id("maintenance_change_batches")
    branch_name = f"maintenance/{local_day}-{batch_id}-{scope_slug}"
    batch_dir = paths.maintenance_batch_dir(batch_id)
    batch_dir.mkdir(parents=True, exist_ok=True)
    json_path = paths.maintenance_change_json_path(batch_id)
    markdown_path = paths.maintenance_change_markdown_path(batch_id)
    worktree_path = Path(
        tempfile.mkdtemp(prefix=f"jhc-maintenance-{batch_id}-", dir="/tmp")
    ).resolve()

    current_branch = _git_stdout(
        paths.project_root,
        ("rev-parse", "--abbrev-ref", "HEAD"),
    ).strip()
    if not current_branch or current_branch == "HEAD":
        raise MaintenanceStateError(
            "Maintenance requires a named base branch instead of a detached HEAD."
        )

    _run_git(
        paths.project_root,
        ("worktree", "add", "-b", branch_name, str(worktree_path), current_branch),
    )
    if plan.apply_changes is not None:
        plan.apply_changes(worktree_path)

    changed_files = _git_changed_files(worktree_path)
    _run_git(worktree_path, ("add", "-A"))
    _run_git(
        worktree_path,
        (
            "-c",
            "user.name=Job Hunt Copilot",
            "-c",
            "user.email=job-hunt-copilot@example.local",
            "commit",
            "--allow-empty",
            "-m",
            f"maintenance({batch_id}): {scope_slug}",
        ),
    )
    head_commit_sha = _git_stdout(worktree_path, ("rev-parse", "HEAD")).strip()

    change_scoped_results = _run_validation_commands(
        plan.change_scoped_validation,
        worktree_path,
        scope=VALIDATION_SCOPE_CHANGE_SCOPED,
        runner=dependencies.command_runner or _run_command,
    )
    full_system_results = _run_validation_commands(
        plan.full_system_validation,
        worktree_path,
        scope=VALIDATION_SCOPE_FULL_SYSTEM,
        runner=dependencies.command_runner or _run_command,
    )
    all_results = [*change_scoped_results, *full_system_results]
    validations_passed = all(result.passed for result in all_results)

    status = (
        MAINTENANCE_STATUS_VALIDATED
        if validations_passed
        else MAINTENANCE_STATUS_RETAINED_FOR_REVIEW
    )
    approval_outcome = (
        MAINTENANCE_APPROVAL_PENDING
        if validations_passed
        else MAINTENANCE_APPROVAL_FAILED_VALIDATION
    )
    validation_summary = _build_validation_summary(
        change_scoped_results,
        full_system_results,
    )

    payload = {
        "contract_version": CONTRACT_VERSION,
        "maintenance_change_batch_id": batch_id,
        "local_day": local_day,
        "scope_slug": scope_slug,
        "branch_name": branch_name,
        "status": status,
        "approval_outcome": approval_outcome,
        "short_reason": plan.short_reason,
        "head_commit_sha": head_commit_sha,
        "merged_commit_sha": None,
        "merge_commit_message": None,
        "created_at": current_time,
        "validated_at": current_time,
        "approved_at": None,
        "merged_at": None,
        "failed_at": current_time if not validations_passed else None,
        "files_changed": changed_files,
        "change_scoped_validation": [result.as_dict() for result in change_scoped_results],
        "full_system_validation": [result.as_dict() for result in full_system_results],
        "related_incident_ids": list(plan.related_incident_ids),
        "related_review_packet_ids": list(plan.related_review_packet_ids),
        "notes": plan.notes,
        "base_branch_name": current_branch,
        "isolated_worktree_path": str(worktree_path),
        "summary_path": paths.relative_to_root(markdown_path).as_posix(),
        "json_path": paths.relative_to_root(json_path).as_posix(),
        "validation_summary": validation_summary,
    }
    _write_batch_artifacts(
        json_path=json_path,
        markdown_path=markdown_path,
        payload=payload,
    )

    with connection:
        connection.execute(
            """
            INSERT INTO maintenance_change_batches (
              maintenance_change_batch_id, branch_name, scope_slug, status,
              approval_outcome, summary_path, json_path, head_commit_sha,
              merged_commit_sha, merge_commit_message, validated_at, approved_at,
              merged_at, failed_at, validation_summary, expert_review_packet_id,
              created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                batch_id,
                branch_name,
                scope_slug,
                status,
                approval_outcome,
                payload["summary_path"],
                payload["json_path"],
                head_commit_sha,
                None,
                None,
                current_time,
                None,
                None,
                payload["failed_at"],
                validation_summary,
                None,
                current_time,
            ),
        )

    batch = get_maintenance_batch(connection, batch_id)
    if batch is None:  # pragma: no cover - defensive invariant
        raise MaintenanceStateError(
            f"Failed to reload maintenance batch {batch_id} after creation."
        )
    return MaintenanceBatchExecution(
        batch=batch,
        json_path=payload["json_path"],
        markdown_path=payload["summary_path"],
    )


def review_maintenance_change_batch(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    maintenance_change_batch_id: str,
    *,
    decision: str,
    current_time: str,
    reason: str | None = None,
) -> MaintenanceBatchExecution:
    if decision not in {"approve", "reject"}:
        raise MaintenanceStateError(f"Unsupported maintenance review decision: {decision!r}.")

    batch = get_maintenance_batch(connection, maintenance_change_batch_id)
    if batch is None:
        raise MaintenanceStateError(
            f"Unknown maintenance batch: {maintenance_change_batch_id!r}."
        )

    json_path = paths.resolve_from_root(batch.json_path)
    markdown_path = paths.resolve_from_root(batch.summary_path)
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise MaintenanceStateError(
            f"Expected maintenance payload object in {json_path}."
        )

    if decision == "reject":
        if batch.approval_outcome == MAINTENANCE_APPROVAL_NOT_APPROVED:
            return MaintenanceBatchExecution(
                batch=batch,
                json_path=batch.json_path,
                markdown_path=batch.summary_path,
            )
        payload["status"] = MAINTENANCE_STATUS_RETAINED_FOR_REVIEW
        payload["approval_outcome"] = MAINTENANCE_APPROVAL_NOT_APPROVED
        payload["review_decision_at"] = current_time
        if reason:
            payload["review_decision_reason"] = reason.strip()
        with connection:
            connection.execute(
                """
                UPDATE maintenance_change_batches
                SET status = ?, approval_outcome = ?, validation_summary = ?
                WHERE maintenance_change_batch_id = ?
                """,
                (
                    MAINTENANCE_STATUS_RETAINED_FOR_REVIEW,
                    MAINTENANCE_APPROVAL_NOT_APPROVED,
                    batch.validation_summary,
                    maintenance_change_batch_id,
                ),
            )
        _write_batch_artifacts(
            json_path=json_path,
            markdown_path=markdown_path,
            payload=payload,
        )
    else:
        if batch.status == MAINTENANCE_STATUS_MERGED and batch.approval_outcome == MAINTENANCE_APPROVAL_APPROVED:
            return MaintenanceBatchExecution(
                batch=batch,
                json_path=batch.json_path,
                markdown_path=batch.summary_path,
            )
        if batch.approval_outcome == MAINTENANCE_APPROVAL_FAILED_VALIDATION:
            raise MaintenanceStateError(
                "Maintenance batches that failed validation cannot be approved for merge."
            )
        if batch.status != MAINTENANCE_STATUS_VALIDATED or batch.approval_outcome != MAINTENANCE_APPROVAL_PENDING:
            raise MaintenanceStateError(
                "Only validated maintenance batches awaiting approval can be merged."
            )
        if not _batch_validations_passed(payload):
            raise MaintenanceStateError(
                "Maintenance batch approval requires both validation layers to have passed."
            )
        base_branch_name = str(payload.get("base_branch_name") or "")
        if not base_branch_name:
            raise MaintenanceStateError("Maintenance batch payload is missing base_branch_name.")
        current_branch = _git_stdout(
            paths.project_root,
            ("rev-parse", "--abbrev-ref", "HEAD"),
        ).strip()
        if current_branch != base_branch_name:
            raise MaintenanceStateError(
                "Approve maintenance from the original base branch only: "
                f"expected {base_branch_name!r}, found {current_branch!r}."
            )
        merge_commit_message = _merge_commit_message(
            maintenance_change_batch_id=maintenance_change_batch_id,
            scope_slug=batch.scope_slug,
            branch_name=batch.branch_name,
            short_reason=str(payload.get("short_reason") or ""),
            validation_summary=str(payload.get("validation_summary") or ""),
        )
        _run_git(
            paths.project_root,
            (
                "-c",
                "user.name=Job Hunt Copilot",
                "-c",
                "user.email=job-hunt-copilot@example.local",
                "merge",
                "--no-ff",
                batch.branch_name,
                "-m",
                merge_commit_message.splitlines()[0],
                "-m",
                "\n".join(merge_commit_message.splitlines()[1:]),
            ),
        )
        merged_commit_sha = _git_stdout(paths.project_root, ("rev-parse", "HEAD")).strip()
        payload["status"] = MAINTENANCE_STATUS_MERGED
        payload["approval_outcome"] = MAINTENANCE_APPROVAL_APPROVED
        payload["approved_at"] = current_time
        payload["merged_at"] = current_time
        payload["merged_commit_sha"] = merged_commit_sha
        payload["merge_commit_message"] = merge_commit_message
        if reason:
            payload["review_decision_reason"] = reason.strip()
        with connection:
            connection.execute(
                """
                UPDATE maintenance_change_batches
                SET status = ?, approval_outcome = ?, approved_at = ?, merged_at = ?,
                    merged_commit_sha = ?, merge_commit_message = ?, validation_summary = ?
                WHERE maintenance_change_batch_id = ?
                """,
                (
                    MAINTENANCE_STATUS_MERGED,
                    MAINTENANCE_APPROVAL_APPROVED,
                    current_time,
                    current_time,
                    merged_commit_sha,
                    merge_commit_message,
                    batch.validation_summary,
                    maintenance_change_batch_id,
                ),
            )
        _write_batch_artifacts(
            json_path=json_path,
            markdown_path=markdown_path,
            payload=payload,
        )

    updated_batch = get_maintenance_batch(connection, maintenance_change_batch_id)
    if updated_batch is None:  # pragma: no cover - defensive invariant
        raise MaintenanceStateError(
            f"Failed to reload maintenance batch {maintenance_change_batch_id}."
        )
    return MaintenanceBatchExecution(
        batch=updated_batch,
        json_path=updated_batch.json_path,
        markdown_path=updated_batch.summary_path,
    )


def get_maintenance_batch(
    connection: sqlite3.Connection,
    maintenance_change_batch_id: str,
) -> MaintenanceBatchRecord | None:
    row = connection.execute(
        """
        SELECT maintenance_change_batch_id, branch_name, scope_slug, status,
               approval_outcome, summary_path, json_path, head_commit_sha,
               merged_commit_sha, merge_commit_message, validated_at, approved_at,
               merged_at, failed_at, validation_summary, expert_review_packet_id,
               created_at
        FROM maintenance_change_batches
        WHERE maintenance_change_batch_id = ?
        """,
        (maintenance_change_batch_id,),
    ).fetchone()
    if row is None:
        return None
    return MaintenanceBatchRecord(
        maintenance_change_batch_id=str(row["maintenance_change_batch_id"]),
        branch_name=str(row["branch_name"]),
        scope_slug=str(row["scope_slug"]),
        status=str(row["status"]),
        approval_outcome=str(row["approval_outcome"]),
        summary_path=str(row["summary_path"]),
        json_path=str(row["json_path"]),
        head_commit_sha=_optional_text(row["head_commit_sha"]),
        merged_commit_sha=_optional_text(row["merged_commit_sha"]),
        merge_commit_message=_optional_text(row["merge_commit_message"]),
        validated_at=_optional_text(row["validated_at"]),
        approved_at=_optional_text(row["approved_at"]),
        merged_at=_optional_text(row["merged_at"]),
        failed_at=_optional_text(row["failed_at"]),
        validation_summary=_optional_text(row["validation_summary"]),
        expert_review_packet_id=_optional_text(row["expert_review_packet_id"]),
        created_at=str(row["created_at"]),
    )


def _write_batch_artifacts(
    *,
    json_path: Path,
    markdown_path: Path,
    payload: dict[str, Any],
) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(payload, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(
        _render_batch_markdown(payload),
        encoding="utf-8",
    )


def _render_batch_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Maintenance Change Batch",
        "",
        f"- Maintenance change batch: `{payload['maintenance_change_batch_id']}`",
        f"- Local day: `{payload['local_day']}`",
        f"- Scope: `{payload['scope_slug']}`",
        f"- Branch: `{payload['branch_name']}`",
        f"- Status: `{payload['status']}`",
        f"- Approval outcome: `{payload['approval_outcome']}`",
        f"- Short reason: {payload['short_reason']}",
        f"- Created at: `{payload['created_at']}`",
        f"- Validated at: `{payload.get('validated_at') or 'n/a'}`",
        f"- Approved at: `{payload.get('approved_at') or 'n/a'}`",
        f"- Merged at: `{payload.get('merged_at') or 'n/a'}`",
        f"- Failed at: `{payload.get('failed_at') or 'n/a'}`",
        f"- Head commit: `{payload.get('head_commit_sha') or 'n/a'}`",
        f"- Merged commit: `{payload.get('merged_commit_sha') or 'n/a'}`",
    ]
    merge_commit_message = payload.get("merge_commit_message")
    if merge_commit_message:
        lines.extend(["", "## Merge Commit", "", str(merge_commit_message)])
    lines.extend(["", "## Validation Summary", "", str(payload.get("validation_summary") or "n/a")])
    lines.extend(["", "## Files Changed", ""])
    files_changed = payload.get("files_changed") or []
    if files_changed:
        lines.extend(f"- {path}" for path in files_changed)
    else:
        lines.append("- No tracked file content changed; the maintenance checkpoint was recorded with an empty commit.")

    lines.extend(["", "## Change-Scoped Validation", ""])
    change_scoped = payload.get("change_scoped_validation") or []
    if change_scoped:
        for result in change_scoped:
            state = "pass" if result.get("passed") else "fail"
            lines.append(
                f"- `{result['label']}`: {state} | `{result['command']}` | {result['summary']}"
            )
    else:
        lines.append("- No change-scoped validation commands were required for this batch.")

    lines.extend(["", "## Full-System Validation", ""])
    full_system = payload.get("full_system_validation") or []
    if full_system:
        for result in full_system:
            state = "pass" if result.get("passed") else "fail"
            lines.append(
                f"- `{result['label']}`: {state} | `{result['command']}` | {result['summary']}"
            )
    else:
        lines.append("- No full-system validation commands were recorded for this batch.")

    related_incident_ids = payload.get("related_incident_ids") or []
    related_review_packet_ids = payload.get("related_review_packet_ids") or []
    if related_incident_ids or related_review_packet_ids:
        lines.extend(["", "## Related References", ""])
        if related_incident_ids:
            lines.append(
                "- Related incidents: " + ", ".join(f"`{incident_id}`" for incident_id in related_incident_ids)
            )
        if related_review_packet_ids:
            lines.append(
                "- Related review packets: "
                + ", ".join(f"`{packet_id}`" for packet_id in related_review_packet_ids)
            )

    notes = payload.get("notes")
    if notes:
        lines.extend(["", "## Notes", "", str(notes)])
    review_reason = payload.get("review_decision_reason")
    if review_reason:
        lines.extend(["", "## Review Decision Note", "", str(review_reason)])
    lines.append("")
    return "\n".join(lines)


def _build_validation_summary(
    change_scoped_results: list[MaintenanceValidationResult],
    full_system_results: list[MaintenanceValidationResult],
) -> str:
    scoped_summary = _summarize_validation_scope(change_scoped_results)
    full_summary = _summarize_validation_scope(full_system_results)
    return f"change_scoped={scoped_summary}; full_system={full_summary}"


def _summarize_validation_scope(results: list[MaintenanceValidationResult]) -> str:
    if not results:
        return "not_required"
    passed_count = sum(1 for result in results if result.passed)
    if passed_count == len(results):
        return f"passed ({passed_count}/{len(results)})"
    failed_labels = ", ".join(result.label for result in results if not result.passed)
    return f"failed ({passed_count}/{len(results)} passed; failed: {failed_labels})"


def _run_validation_commands(
    commands: tuple[MaintenanceValidationCommand, ...],
    cwd: Path,
    *,
    scope: str,
    runner: CommandRunner,
) -> list[MaintenanceValidationResult]:
    results: list[MaintenanceValidationResult] = []
    for command in commands:
        completed = runner(command.args, cwd)
        summary = _summarize_command_output(completed)
        results.append(
            MaintenanceValidationResult(
                scope=scope,
                label=command.label,
                command=command.command,
                passed=completed.returncode == 0,
                summary=summary,
                returncode=completed.returncode,
            )
        )
    return results


def _run_command(
    args: tuple[str, ...],
    cwd: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )


def _summarize_command_output(completed: subprocess.CompletedProcess[str]) -> str:
    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()
    for candidate in (stdout, stderr):
        if candidate:
            first_line = candidate.splitlines()[0].strip()
            if first_line:
                return first_line[:280]
    return "command completed without output" if completed.returncode == 0 else "command failed without output"


def _git_stdout(
    cwd: Path,
    args: tuple[str, ...],
) -> str:
    completed = _run_git(cwd, args)
    return completed.stdout


def _run_git(
    cwd: Path,
    args: tuple[str, ...],
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        summary = _summarize_command_output(completed)
        raise MaintenanceStateError(f"git {' '.join(args)} failed: {summary}")
    return completed


def _git_changed_files(cwd: Path) -> list[str]:
    completed = _run_git(cwd, ("status", "--porcelain"))
    changed_paths: list[str] = []
    for raw_line in completed.stdout.splitlines():
        if not raw_line.strip():
            continue
        changed_paths.append(raw_line[3:].strip())
    return changed_paths


def _git_status_porcelain(cwd: Path) -> list[str]:
    completed = _run_git(cwd, ("status", "--porcelain"))
    return [line for line in completed.stdout.splitlines() if line.strip()]


def _merge_commit_message(
    *,
    maintenance_change_batch_id: str,
    scope_slug: str,
    branch_name: str,
    short_reason: str,
    validation_summary: str,
) -> str:
    return "\n".join(
        [
            f"merge(maintenance): {maintenance_change_batch_id} {scope_slug}",
            f"Branch: {branch_name}",
            f"Reason: {short_reason}",
            f"Validation: {validation_summary}",
            "Approval: approved",
        ]
    )


def _batch_validations_passed(payload: dict[str, Any]) -> bool:
    for section in ("change_scoped_validation", "full_system_validation"):
        for result in payload.get(section) or []:
            if not result.get("passed"):
                return False
    return True


def _parse_utc_iso(timestamp: str) -> datetime:
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(timezone.utc)


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
