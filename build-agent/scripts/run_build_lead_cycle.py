#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

from common import (
    append_jsonl,
    build_agent_root,
    build_cycles_path,
    context_snapshot_dir,
    cycles_log_dir,
    default_project_root,
    ensure_dirs,
    iso_to_datetime,
    lease_expiry_iso,
    detect_sleep_wake_interruption,
    load_control_state,
    load_leases,
    load_yaml,
    now_utc_iso,
    process_is_alive,
    require_project_git_root,
    save_control_state,
    save_json,
    save_leases,
)


LEASE_NAME = "build_lead_cycle"
STATE_TRACKED_FILES = [
    "build-agent/state/build-board.yaml",
    "build-agent/state/build-journal.md",
    "build-agent/state/codex-progress.txt",
    "build-agent/state/IMPLEMENTATION_PLAN.md",
]


def new_cycle_id() -> str:
    return f"build-cycle-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"


def acquire_lease(project_root: Path, cycle_id: str) -> tuple[bool, dict]:
    leases = load_leases(project_root)
    lease = leases["leases"].get(LEASE_NAME)
    now = datetime.now(timezone.utc)
    if lease:
        expires_at = iso_to_datetime(lease.get("expires_at"))
        if expires_at and expires_at > now:
            return False, lease
    leases["leases"][LEASE_NAME] = {
        "lease_name": LEASE_NAME,
        "lease_owner_id": cycle_id,
        "lease_owner_pid": os.getpid(),
        "acquired_at": now_utc_iso(),
        "expires_at": lease_expiry_iso(hours=4),
        "lease_note": "active build-lead cycle",
    }
    save_leases(project_root, leases)
    return True, leases["leases"][LEASE_NAME]


def release_lease(project_root: Path, cycle_id: str) -> None:
    leases = load_leases(project_root)
    lease = leases["leases"].get(LEASE_NAME)
    if lease and lease.get("lease_owner_id") == cycle_id:
        leases["leases"].pop(LEASE_NAME, None)
        save_leases(project_root, leases)


def current_lease(project_root: Path) -> dict | None:
    return load_leases(project_root)["leases"].get(LEASE_NAME)


def reclaim_stale_lease(project_root: Path) -> dict | None:
    leases = load_leases(project_root)
    lease = leases["leases"].pop(LEASE_NAME, None)
    if lease is not None:
        save_leases(project_root, leases)
    return lease


def run_sleep_wake_recovery(project_root: Path, cycle_id: str, started_at: str, detection: dict) -> int:
    control_state = load_control_state(project_root)
    active_lease = current_lease(project_root)
    recovery_actions: list[str] = []
    result = "recovered"

    if active_lease:
        lease_pid = active_lease.get("lease_owner_pid")
        if process_is_alive(lease_pid):
            recovery_actions.append("live_lease_preserved")
            result = "deferred"
        else:
            reclaim_stale_lease(project_root)
            recovery_actions.append("stale_lease_reclaimed")
    else:
        recovery_actions.append("no_active_lease")

    completed_at = now_utc_iso()
    control_state["last_cycle_completed_at"] = completed_at
    control_state["last_sleep_wake_check_at"] = completed_at
    control_state["last_sleep_wake_event_at"] = detection.get("event_at")
    control_state["last_sleep_wake_detection_method"] = detection.get("method")
    control_state["last_sleep_wake_recovery_at"] = completed_at
    save_control_state(project_root, control_state)

    record_cycle(
        project_root,
        {
            "build_cycle_id": cycle_id,
            "started_at": started_at,
            "completed_at": completed_at,
            "result": result,
            "reason": "sleep_wake_recovery",
            "sleep_wake_detection": detection,
            "recovery_actions": recovery_actions,
        },
    )
    return 0


def select_epic(board: dict) -> dict | None:
    epics = board.get("epics", [])
    indexed = {epic["id"]: epic for epic in epics}
    focus_id = board.get("current_focus", {}).get("epic_id")
    if focus_id in indexed and indexed[focus_id].get("status") not in {"completed", "done"}:
        return indexed[focus_id]
    for epic in epics:
        if epic.get("status") in {"pending", "in_progress", "not_started"}:
            return epic
    return None


def git_status_excerpt(project_root: Path, limit: int = 50) -> list[str]:
    result = subprocess.run(
        ["git", "status", "--short"],
        cwd=project_root,
        text=True,
        capture_output=True,
        check=True,
    )
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    return lines[:limit]


def tracked_state_file_mtimes(project_root: Path) -> dict[str, int | None]:
    mtimes: dict[str, int | None] = {}
    for relpath in STATE_TRACKED_FILES:
        path = project_root / relpath
        mtimes[relpath] = path.stat().st_mtime_ns if path.exists() else None
    return mtimes


def changed_state_files(before: dict[str, int | None], after: dict[str, int | None]) -> list[str]:
    changed: list[str] = []
    for relpath in STATE_TRACKED_FILES:
        if before.get(relpath) != after.get(relpath):
            changed.append(relpath)
    return changed


def build_snapshot(project_root: Path, cycle_id: str, board: dict, epic: dict, control_state: dict) -> tuple[Path, dict]:
    status_excerpt = git_status_excerpt(project_root)
    snapshot = {
        "contract_version": "1.0",
        "build_cycle_id": cycle_id,
        "created_at": now_utc_iso(),
        "resume_mode": bool(status_excerpt),
        "git_status_excerpt": status_excerpt,
        "interruption_context": {
            "last_sleep_wake_event_at": control_state.get("last_sleep_wake_event_at"),
            "last_sleep_wake_detection_method": control_state.get("last_sleep_wake_detection_method"),
            "last_sleep_wake_recovery_at": control_state.get("last_sleep_wake_recovery_at"),
        },
        "selected_epic": {
            "epic_id": epic.get("id"),
            "name": epic.get("name"),
            "status": epic.get("status"),
            "owner_role": epic.get("owner_role"),
            "objective": epic.get("objective"),
            "done_when": epic.get("done_when", []),
        },
        "board_summary": {
            "current_phase": board.get("global_status", {}).get("current_phase"),
            "overall_risk": board.get("global_status", {}).get("overall_risk"),
            "current_focus": board.get("current_focus", {}),
            "known_blockers": board.get("known_blockers", []),
        },
        "state_files": [
            *STATE_TRACKED_FILES,
        ],
        "notes": [
            "One bounded slice only",
            "Update build state before exit",
            "Validate before claiming progress",
        ],
    }
    path = context_snapshot_dir(project_root) / f"{cycle_id}.json"
    save_json(path, snapshot)
    return path, snapshot


def build_prompt(project_root: Path, cycle_id: str, epic: dict, snapshot_path: Path, snapshot: dict) -> str:
    build_root = build_agent_root(project_root)
    bootstrap = (build_root / "builder-bootstrap.md").read_text(encoding="utf-8").strip()
    owner_role = epic.get("owner_role", "build-lead")
    role_brief_path = build_root / "team" / f"{owner_role}.md"
    role_brief = role_brief_path.read_text(encoding="utf-8").strip() if role_brief_path.exists() else ""

    done_when = epic.get("done_when", [])
    done_when_lines = "\n".join(f"- {item}" for item in done_when)
    resume_rule = ""
    if snapshot.get("resume_mode"):
        resume_rule = """
Resume-first rule:
- The repository already contains uncommitted changes from a previously interrupted or unfinished slice.
- Before starting a fresh slice, inspect those changes, understand them, reconcile them against the current epic, and validate them.
- If the in-progress work is still valid, continue and finish that work first.
- If the work is invalid or contradictory, record the blocker explicitly instead of piling new changes on top.
"""

    return f"""{bootstrap}

Current unattended build cycle:
- cycle_id: {cycle_id}
- selected_epic_id: {epic.get('id')}
- selected_epic_name: {epic.get('name')}
- owner_role: {owner_role}
- objective: {epic.get('objective')}
- context_snapshot: {snapshot_path.relative_to(project_root)}

Done-when targets for this epic:
{done_when_lines or "- No explicit done_when targets recorded."}

Role brief for this cycle:
{role_brief}

Cycle rules:
- Focus on one bounded implementation slice toward the selected epic.
- Stay primarily within the selected owner role's subsystem and responsibility boundary.
- Read the current repository and current git state before editing.
- Update these files before exiting if anything meaningful changed:
  - build-agent/state/build-board.yaml
  - build-agent/state/build-journal.md
  - build-agent/state/codex-progress.txt
  - build-agent/state/IMPLEMENTATION_PLAN.md
- If blocked, record the blocker explicitly instead of hand-waving.
- Validate the changed area before claiming completion.
- Check the current repository state carefully before resuming after any interruption.
- Resume interrupted in-progress work cleanly before branching into unrelated new work.
- In your final response, summarize:
  - the slice attempted or completed
  - files changed
  - validation run
  - whether the build state files were updated
  - the next best slice

{resume_rule}
"""


def record_cycle(project_root: Path, payload: dict) -> None:
    append_jsonl(build_cycles_path(project_root), payload)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=str(default_project_root()))
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    ensure_dirs(project_root)
    require_project_git_root(project_root)

    subprocess.run(
        [
            "python3",
            str(build_agent_root(project_root) / "scripts" / "materialize_runtime_pack.py"),
            "--project-root",
            str(project_root),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )

    cycle_id = new_cycle_id()
    started_at = now_utc_iso()

    control_state = load_control_state(project_root)
    sleep_wake_detection = detect_sleep_wake_interruption(control_state)
    control_state["last_cycle_started_at"] = started_at
    control_state["last_sleep_wake_check_at"] = started_at
    save_control_state(project_root, control_state)

    if not control_state.get("agent_enabled") or control_state.get("agent_mode") in {"stopped", "paused"}:
        completed_at = now_utc_iso()
        control_state["last_cycle_completed_at"] = completed_at
        save_control_state(project_root, control_state)
        record_cycle(
            project_root,
            {
                "build_cycle_id": cycle_id,
                "started_at": started_at,
                "completed_at": completed_at,
                "result": "deferred",
                "reason": f"agent_mode={control_state.get('agent_mode')}",
            },
        )
        return 0

    if sleep_wake_detection.get("interrupted"):
        return run_sleep_wake_recovery(project_root, cycle_id, started_at, sleep_wake_detection)

    acquired, lease = acquire_lease(project_root, cycle_id)
    if not acquired:
        completed_at = now_utc_iso()
        control_state = load_control_state(project_root)
        control_state["last_cycle_completed_at"] = completed_at
        save_control_state(project_root, control_state)
        record_cycle(
            project_root,
            {
                "build_cycle_id": cycle_id,
                "started_at": started_at,
                "completed_at": completed_at,
                "result": "deferred",
                "reason": "active_lease",
                "lease_owner_id": lease.get("lease_owner_id"),
            },
        )
        return 0

    try:
        board = load_yaml(build_agent_root(project_root) / "state" / "build-board.yaml")
        epic = select_epic(board)
        if epic is None:
            completed_at = now_utc_iso()
            control_state = load_control_state(project_root)
            control_state["last_cycle_completed_at"] = completed_at
            save_control_state(project_root, control_state)
            record_cycle(
                project_root,
                {
                    "build_cycle_id": cycle_id,
                    "started_at": started_at,
                    "completed_at": completed_at,
                    "result": "no_work",
                },
            )
            return 0

        state_mtimes_before = tracked_state_file_mtimes(project_root)
        snapshot_path, snapshot = build_snapshot(project_root, cycle_id, board, epic, load_control_state(project_root))
        prompt = build_prompt(project_root, cycle_id, epic, snapshot_path, snapshot)

        if shutil.which("codex") is None:
            completed_at = now_utc_iso()
            control_state = load_control_state(project_root)
            control_state["last_cycle_completed_at"] = completed_at
            save_control_state(project_root, control_state)
            record_cycle(
                project_root,
                {
                    "build_cycle_id": cycle_id,
                    "started_at": started_at,
                    "completed_at": completed_at,
                    "result": "failed",
                    "reason": "codex_cli_not_found",
                },
            )
            return 1

        cycle_log_path = cycles_log_dir(project_root) / f"{cycle_id}.log"
        last_message_path = cycles_log_dir(project_root) / f"{cycle_id}.last-message.md"
        command = [
            "codex",
            "exec",
            "--dangerously-bypass-approvals-and-sandbox",
            "-C",
            str(project_root),
            "-o",
            str(last_message_path),
            "-",
        ]

        with cycle_log_path.open("w", encoding="utf-8") as log_handle:
            log_handle.write(f"# {cycle_id}\n")
            log_handle.write(f"started_at: {started_at}\n")
            log_handle.write(f"selected_epic: {epic.get('id')} {epic.get('name')}\n\n")
            completed = subprocess.run(command, input=prompt, text=True, stdout=log_handle, stderr=subprocess.STDOUT)

        completed_at = now_utc_iso()
        control_state = load_control_state(project_root)
        control_state["last_cycle_completed_at"] = completed_at
        save_control_state(project_root, control_state)

        result = "success" if completed.returncode == 0 else "failed"
        state_mtimes_after = tracked_state_file_mtimes(project_root)
        updated_state_files = changed_state_files(state_mtimes_before, state_mtimes_after)
        if result == "success" and git_status_excerpt(project_root) and not updated_state_files:
            result = "failed"
        checkpoint_info = None
        if result == "success":
            checkpoint_process = subprocess.run(
                [
                    "python3",
                    str(build_agent_root(project_root) / "scripts" / "git_checkpoint.py"),
                    "--project-root",
                    str(project_root),
                    "--cycle-id",
                    cycle_id,
                    "--epic-id",
                    str(epic.get("id")),
                    "--epic-name",
                    str(epic.get("name")),
                    "--cycle-result",
                    result,
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            if checkpoint_process.stdout.strip():
                try:
                    checkpoint_info = json.loads(checkpoint_process.stdout.strip())
                except json.JSONDecodeError:
                    checkpoint_info = {"result": "unparseable", "raw": checkpoint_process.stdout.strip()}
            if checkpoint_process.returncode != 0:
                result = "failed"
                checkpoint_info = checkpoint_info or {"result": "failed", "error": checkpoint_process.stderr.strip() or checkpoint_process.stdout.strip()}
        else:
            checkpoint_info = {
                "result": "skipped",
                "reason": "cycle_not_successful",
            }
            if not updated_state_files and git_status_excerpt(project_root):
                checkpoint_info["guard"] = "state_files_not_updated"

        record_cycle(
            project_root,
            {
                "build_cycle_id": cycle_id,
                "started_at": started_at,
                "completed_at": completed_at,
                "result": result,
                "selected_epic_id": epic.get("id"),
                "owner_role": epic.get("owner_role"),
                "context_snapshot": str(snapshot_path.relative_to(project_root)),
                "cycle_log": str(cycle_log_path.relative_to(project_root)),
                "last_message_path": str(last_message_path.relative_to(project_root)),
                "return_code": completed.returncode,
                "updated_state_files": updated_state_files,
                "git_checkpoint": checkpoint_info,
            },
        )
        if result != "success":
            return 1
        return 0
    except Exception as exc:
        completed_at = now_utc_iso()
        control_state = load_control_state(project_root)
        control_state["last_cycle_completed_at"] = completed_at
        save_control_state(project_root, control_state)
        record_cycle(
            project_root,
            {
                "build_cycle_id": cycle_id,
                "started_at": started_at,
                "completed_at": completed_at,
                "result": "failed",
                "reason": repr(exc),
            },
        )
        raise
    finally:
        release_lease(project_root, cycle_id)


if __name__ == "__main__":
    raise SystemExit(main())
