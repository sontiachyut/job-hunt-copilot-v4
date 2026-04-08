#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from job_hunt_copilot.quality_validation import (
    build_smoke_validation_plan,
    build_quality_validation_plan,
    list_quality_validation_commands,
    list_smoke_validation_targets,
    refresh_ba10_validation_reports,
    resolve_acceptance_gap_validation_command_ids,
    resolve_build_board_blocker_validation_command_ids,
    resolve_current_focus_validation_command_ids,
    write_ba10_validation_suite_reports,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=str(PROJECT_ROOT))
    parser.add_argument("--command-id", action="append", dest="command_ids", default=[])
    parser.add_argument("--smoke-target", action="append", dest="smoke_target_ids", default=[])
    parser.add_argument("--gap-id", action="append", dest="gap_ids", default=[])
    parser.add_argument("--blocker-id", action="append", dest="blocker_ids", default=[])
    parser.add_argument(
        "--current-focus",
        action="store_true",
        help="Resolve the validation plan for the active BA-10 focus slice from the blocker audit.",
    )
    parser.add_argument(
        "--include-manual",
        action="store_true",
        help="Allow explicitly requested manual_local/manual_host commands in the plan.",
    )
    parser.add_argument(
        "--skip-report-refresh",
        action="store_true",
        help="Skip regenerating the committed BA-10 acceptance trace and blocker audit reports.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List the available BA-10 validation commands and exit.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve the execution plan and emit JSON without running commands.",
    )
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()

    if args.list:
        payload = {
            "project_root": str(project_root),
            "commands": [
                command.as_dict()
                for command in list_quality_validation_commands(
                    include_manual=args.include_manual
                )
            ],
            "smoke_targets": [
                target.as_dict() for target in list_smoke_validation_targets()
            ],
        }
        print(json.dumps(payload, indent=2))
        return 0

    try:
        resolved_command_ids: list[str] = []
        if args.current_focus:
            resolved_command_ids.extend(
                resolve_current_focus_validation_command_ids(project_root)
            )
        if args.gap_ids:
            resolved_command_ids.extend(
                resolve_acceptance_gap_validation_command_ids(project_root, args.gap_ids)
            )
        if args.blocker_ids:
            resolved_command_ids.extend(
                resolve_build_board_blocker_validation_command_ids(
                    project_root, args.blocker_ids
                )
            )
        if args.smoke_target_ids:
            resolved_command_ids.extend(
                command.command_id
                for command in build_smoke_validation_plan(args.smoke_target_ids)
            )
        if args.command_ids:
            resolved_command_ids.extend(args.command_ids)

        plan = build_quality_validation_plan(
            resolved_command_ids or None,
            include_manual=args.include_manual,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.dry_run:
        payload = {
            "project_root": str(project_root),
            "refreshed_reports": False,
            "requested_command_ids": list(args.command_ids),
            "requested_gap_ids": list(args.gap_ids),
            "requested_blocker_ids": list(args.blocker_ids),
            "requested_current_focus": args.current_focus,
            "requested_smoke_targets": list(args.smoke_target_ids),
            "include_manual": args.include_manual,
            "skip_report_refresh": args.skip_report_refresh,
            "commands": [command.as_dict() for command in plan],
        }
        print(json.dumps(payload, indent=2))
        return 0

    refreshed_reports = None
    if not args.skip_report_refresh:
        refreshed_reports = refresh_ba10_validation_reports(project_root)

    results: list[dict[str, object]] = []
    failed_command_ids: list[str] = []
    for command in plan:
        print(f"==> [{command.command_id}] {command.command}", flush=True)
        started_at = time.monotonic()
        completed = subprocess.run(
            command.command,
            cwd=project_root,
            check=False,
            executable="/bin/zsh",
            shell=True,
        )
        duration_seconds = round(time.monotonic() - started_at, 3)
        status = "passed" if completed.returncode == 0 else "failed"
        if completed.returncode != 0:
            failed_command_ids.append(command.command_id)
        results.append(
            {
                **command.as_dict(),
                "status": status,
                "returncode": completed.returncode,
                "duration_seconds": duration_seconds,
            }
        )

    payload = {
        "project_root": str(project_root),
        "refreshed_reports": refreshed_reports,
        "requested_command_ids": list(args.command_ids),
        "requested_gap_ids": list(args.gap_ids),
        "requested_blocker_ids": list(args.blocker_ids),
        "requested_current_focus": args.current_focus,
        "requested_smoke_targets": list(args.smoke_target_ids),
        "include_manual": args.include_manual,
        "skip_report_refresh": args.skip_report_refresh,
        "commands": results,
        "failed_command_ids": failed_command_ids,
        "passed": not failed_command_ids,
    }
    payload = write_ba10_validation_suite_reports(project_root, payload)
    print(json.dumps(payload, indent=2))
    return 0 if not failed_command_ids else 1


if __name__ == "__main__":
    raise SystemExit(main())
