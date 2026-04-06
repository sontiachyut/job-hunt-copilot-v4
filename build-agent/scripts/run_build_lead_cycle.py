#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
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
    load_control_state,
    load_leases,
    load_yaml,
    now_utc_iso,
    require_project_git_root,
    save_control_state,
    save_json,
    save_leases,
)


LEASE_NAME = "build_lead_cycle"


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


def build_snapshot(project_root: Path, cycle_id: str, board: dict, epic: dict) -> Path:
    snapshot = {
        "contract_version": "1.0",
        "build_cycle_id": cycle_id,
        "created_at": now_utc_iso(),
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
            "build-agent/state/build-board.yaml",
            "build-agent/state/build-journal.md",
            "build-agent/state/codex-progress.txt",
            "build-agent/state/IMPLEMENTATION_PLAN.md",
        ],
        "notes": [
            "One bounded slice only",
            "Update build state before exit",
            "Validate before claiming progress",
        ],
    }
    path = context_snapshot_dir(project_root) / f"{cycle_id}.json"
    save_json(path, snapshot)
    return path


def build_prompt(project_root: Path, cycle_id: str, epic: dict, snapshot_path: Path) -> str:
    build_root = build_agent_root(project_root)
    bootstrap = (build_root / "builder-bootstrap.md").read_text(encoding="utf-8").strip()
    owner_role = epic.get("owner_role", "build-lead")
    role_brief_path = build_root / "team" / f"{owner_role}.md"
    role_brief = role_brief_path.read_text(encoding="utf-8").strip() if role_brief_path.exists() else ""

    done_when = epic.get("done_when", [])
    done_when_lines = "\n".join(f"- {item}" for item in done_when)

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
- In your final response, summarize:
  - the slice attempted or completed
  - files changed
  - validation run
  - whether the build state files were updated
  - the next best slice
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
    control_state["last_cycle_started_at"] = started_at
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

        snapshot_path = build_snapshot(project_root, cycle_id, board, epic)
        prompt = build_prompt(project_root, cycle_id, epic, snapshot_path)

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
        checkpoint_info = None
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
                "git_checkpoint": checkpoint_info,
            },
        )
        return completed.returncode if checkpoint_process.returncode == 0 else checkpoint_process.returncode
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
