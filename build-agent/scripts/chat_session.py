#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path

from common import (
    append_jsonl,
    build_chat_sessions_path,
    default_project_root,
    ensure_dirs,
    load_control_state,
    now_utc_iso,
    save_control_state,
)


def begin(project_root: Path) -> dict:
    ensure_dirs(project_root)
    state = load_control_state(project_root)
    if state.get("active_chat_session_id"):
        raise RuntimeError(f"Another build chat session is already active: {state['active_chat_session_id']}")
    session_id = f"build-chat-{uuid.uuid4().hex[:10]}"
    state["active_chat_session_id"] = session_id
    state["last_chat_started_at"] = now_utc_iso()
    if state.get("agent_enabled") and state.get("agent_mode") == "running":
        state["mode_before_chat"] = "running"
        state["agent_mode"] = "paused"
        state["pause_reason"] = "expert_interaction"
    save_control_state(project_root, state)
    append_jsonl(
        build_chat_sessions_path(project_root),
        {
            "event": "begin",
            "session_id": session_id,
            "recorded_at": now_utc_iso(),
            "agent_mode_after_begin": state.get("agent_mode"),
        },
    )
    return {"session_id": session_id}


def end(project_root: Path, session_id: str, exit_mode: str) -> dict:
    ensure_dirs(project_root)
    state = load_control_state(project_root)
    active_session_id = state.get("active_chat_session_id")
    if active_session_id and active_session_id != session_id:
        append_jsonl(
            build_chat_sessions_path(project_root),
            {
                "event": "end_ignored",
                "session_id": session_id,
                "active_session_id": active_session_id,
                "exit_mode": exit_mode,
                "recorded_at": now_utc_iso(),
            },
        )
        return {"session_id": session_id, "exit_mode": exit_mode, "status": "ignored_session_mismatch"}
    state["active_chat_session_id"] = None
    state["last_chat_ended_at"] = now_utc_iso()
    state["last_chat_exit_mode"] = exit_mode
    if state.get("agent_enabled") and state.get("agent_mode") == "paused" and state.get("pause_reason") == "expert_interaction":
        state["agent_mode"] = state.get("mode_before_chat") or "running"
        if state["agent_mode"] == "running":
            state["pause_reason"] = None
    state["mode_before_chat"] = None
    save_control_state(project_root, state)
    append_jsonl(
        build_chat_sessions_path(project_root),
        {
            "event": "end",
            "session_id": session_id,
            "exit_mode": exit_mode,
            "recorded_at": now_utc_iso(),
            "agent_mode_after_end": state.get("agent_mode"),
        },
    )
    return {"session_id": session_id, "exit_mode": exit_mode}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["begin", "end"])
    parser.add_argument("--project-root", default=str(default_project_root()))
    parser.add_argument("--session-id")
    parser.add_argument("--exit-mode", choices=["explicit_close", "unexpected_exit"])
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    if args.command == "begin":
        result = begin(project_root)
    else:
        if not args.exit_mode:
            raise SystemExit("--exit-mode is required for end")
        if not args.session_id:
            raise SystemExit("--session-id is required for end")
        result = end(project_root, args.session_id, args.exit_mode)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
