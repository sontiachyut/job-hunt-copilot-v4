from __future__ import annotations

import argparse
import json
from pathlib import Path

from job_hunt_copilot.local_runtime import materialize_followup_worker_launchd_plist


def main() -> None:
    parser = argparse.ArgumentParser(description="Materialize the follow-up worker launchd plist.")
    parser.add_argument("--project-root", default=None)
    args = parser.parse_args()

    report = materialize_followup_worker_launchd_plist(project_root=Path(args.project_root) if args.project_root else None)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
