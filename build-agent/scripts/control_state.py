#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import (
    default_project_root,
    ensure_dirs,
    load_control_state,
    now_utc_iso,
    save_control_state,
)


def mutate(project_root: Path, command: str, pause_reason: str | None = None) -> dict:
    ensure_dirs(project_root)
    state = load_control_state(project_root)
    state["last_manual_command"] = command
    updated_at = now_utc_iso()

    if command == "start":
        state["agent_enabled"] = True
        state["agent_mode"] = "running"
        state["pause_reason"] = None
    elif command == "stop":
        state["agent_enabled"] = False
        state["agent_mode"] = "stopped"
        state["pause_reason"] = pause_reason or "manual_stop"
    elif command == "pause":
        state["agent_enabled"] = True
        state["agent_mode"] = "paused"
        state["pause_reason"] = pause_reason or "manual_pause"
    elif command == "resume":
        state["agent_enabled"] = True
        state["agent_mode"] = "running"
        state["pause_reason"] = None
    else:
        raise ValueError(f"Unsupported command: {command}")

    state["updated_at"] = updated_at
    save_control_state(project_root, state)
    return state


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["start", "stop", "pause", "resume", "status"])
    parser.add_argument("--project-root", default=str(default_project_root()))
    parser.add_argument("--pause-reason")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    ensure_dirs(project_root)

    if args.command == "status":
        print(json.dumps(load_control_state(project_root), indent=2))
        return 0

    state = mutate(project_root, args.command, pause_reason=args.pause_reason)
    print(json.dumps(state, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
