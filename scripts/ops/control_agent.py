#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from job_hunt_copilot.local_runtime import mutate_agent_control_state


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["start", "stop", "pause", "resume", "replan", "status"])
    parser.add_argument("--project-root", default=str(PROJECT_ROOT))
    parser.add_argument("--reason")
    parser.add_argument("--manual-command")
    args = parser.parse_args()

    report = mutate_agent_control_state(
        args.command,
        project_root=Path(args.project_root),
        reason=args.reason,
        manual_command=args.manual_command,
    )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
