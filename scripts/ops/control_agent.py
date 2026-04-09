#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from job_hunt_copilot.local_runtime import abandon_job_posting, mutate_agent_control_state


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=["start", "stop", "pause", "resume", "replan", "status", "abandon"],
    )
    parser.add_argument("--project-root", default=str(PROJECT_ROOT))
    parser.add_argument("--reason")
    parser.add_argument("--manual-command")
    parser.add_argument("--job-posting-id")
    args = parser.parse_args()

    try:
        if args.command == "abandon":
            if not args.job_posting_id:
                parser.error("--job-posting-id is required for the abandon command.")
            report = abandon_job_posting(
                args.job_posting_id,
                project_root=Path(args.project_root),
                reason=args.reason,
                manual_command=args.manual_command or "abandon",
            )
        else:
            report = mutate_agent_control_state(
                args.command,
                project_root=Path(args.project_root),
                reason=args.reason,
                manual_command=args.manual_command,
            )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
