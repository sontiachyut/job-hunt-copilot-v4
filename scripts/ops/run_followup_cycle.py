from __future__ import annotations

import argparse
import json
from pathlib import Path

from job_hunt_copilot.local_runtime import execute_followup_cycle


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one bounded follow-up worker cycle.")
    parser.add_argument("--project-root", default=None)
    parser.add_argument("--current-time", default=None)
    parser.add_argument(
        "--send",
        action="store_true",
        help="Attempt real auto-send when runtime control state enables follow-ups. Default is dry-run.",
    )
    args = parser.parse_args()

    report = execute_followup_cycle(
        project_root=Path(args.project_root) if args.project_root else None,
        current_time=args.current_time,
        dry_run=not args.send,
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
