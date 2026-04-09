#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from job_hunt_copilot.local_runtime import (
    CHAT_SESSION_EXIT_MODE_EXPLICIT_CLOSE,
    CHAT_SESSION_EXIT_MODE_UNEXPECTED_EXIT,
    begin_chat_operator_session,
    end_chat_operator_session,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["begin", "end"])
    parser.add_argument("--project-root", default=str(PROJECT_ROOT))
    parser.add_argument("--session-id")
    parser.add_argument(
        "--exit-mode",
        choices=[
            CHAT_SESSION_EXIT_MODE_EXPLICIT_CLOSE,
            CHAT_SESSION_EXIT_MODE_UNEXPECTED_EXIT,
        ],
    )
    args = parser.parse_args()

    project_root = Path(args.project_root)
    try:
        if args.command == "begin":
            report = begin_chat_operator_session(project_root=project_root)
        else:
            if not args.session_id:
                raise SystemExit("--session-id is required for end")
            if not args.exit_mode:
                raise SystemExit("--exit-mode is required for end")
            report = end_chat_operator_session(
                project_root=project_root,
                session_id=args.session_id,
                exit_mode=args.exit_mode,
            )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
