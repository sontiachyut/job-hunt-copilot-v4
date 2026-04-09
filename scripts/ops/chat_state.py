#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from job_hunt_copilot.chat_runtime import (
    build_chat_change_summary,
    build_chat_review_queue,
    build_chat_startup_dashboard,
    render_chat_change_summary,
    render_chat_review_queue,
    render_chat_startup_dashboard,
)
from job_hunt_copilot.db import initialize_database
from job_hunt_copilot.local_runtime import connect_canonical_database
from job_hunt_copilot.paths import ProjectPaths
from job_hunt_copilot.records import now_utc_iso
from job_hunt_copilot.supervisor import read_agent_control_state


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["dashboard", "review-queue", "change-summary"])
    parser.add_argument("--project-root", default=str(PROJECT_ROOT))
    parser.add_argument("--current-time", default=None)
    parser.add_argument("--max-items-per-group", type=int, default=3)
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    paths = ProjectPaths.from_root(project_root)
    current_time = args.current_time or now_utc_iso()
    initialize_database(paths.db_path)

    with connect_canonical_database(paths) as connection:
        if args.command == "dashboard":
            control_state = read_agent_control_state(connection, timestamp=current_time)
            payload = build_chat_startup_dashboard(
                connection,
                project_root=project_root,
                current_time=current_time,
                agent_mode=control_state.agent_mode,
                pause_reason=control_state.pause_reason,
            )
            rendered = render_chat_startup_dashboard(payload)
        elif args.command == "review-queue":
            payload = build_chat_review_queue(
                connection,
                project_root=project_root,
                max_items_per_group=args.max_items_per_group,
            )
            rendered = render_chat_review_queue(payload)
        else:
            payload = build_chat_change_summary(
                connection,
                project_root=project_root,
                current_time=current_time,
                max_items_per_group=args.max_items_per_group,
            )
            rendered = render_chat_change_summary(payload)

    print(
        json.dumps(
            {
                "command": args.command,
                "project_root": str(project_root),
                "current_time": current_time,
                "max_items_per_group": args.max_items_per_group,
                "payload": payload,
                "rendered_markdown": rendered,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
