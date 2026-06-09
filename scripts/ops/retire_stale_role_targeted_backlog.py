#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from job_hunt_copilot.local_runtime import retire_stale_role_targeted_send_backlog


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=str(PROJECT_ROOT))
    parser.add_argument("--cutoff-created-before", required=True)
    parser.add_argument("--reason")
    parser.add_argument("--manual-command")
    parser.add_argument("--timestamp")
    args = parser.parse_args()

    report = retire_stale_role_targeted_send_backlog(
        cutoff_created_before=args.cutoff_created_before,
        project_root=Path(args.project_root),
        reason=args.reason,
        manual_command=args.manual_command or "retire-stale-role-targeted-backlog",
        timestamp=args.timestamp,
    )
    print(json.dumps(report, indent=2, sort_keys=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
