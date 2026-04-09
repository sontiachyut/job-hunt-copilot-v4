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
    abandon_job_posting,
    apply_object_override,
    mutate_agent_control_state,
    persist_expert_guidance,
    request_guidance_clarification,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=[
            "start",
            "stop",
            "pause",
            "resume",
            "replan",
            "status",
            "abandon",
            "override",
            "guidance",
            "clarify-guidance",
        ],
    )
    parser.add_argument("--project-root", default=str(PROJECT_ROOT))
    parser.add_argument("--reason")
    parser.add_argument("--manual-command")
    parser.add_argument("--job-posting-id")
    parser.add_argument("--object-type")
    parser.add_argument("--object-id")
    parser.add_argument("--new-value")
    parser.add_argument("--component-stage")
    parser.add_argument("--directive-key")
    parser.add_argument("--directive-value")
    parser.add_argument(
        "--scope",
        default="current_and_similar_future",
        choices=["current_only", "current_and_similar_future"],
    )
    parser.add_argument(
        "--request-kind",
        default="uncertainty",
        choices=["conflict", "uncertainty"],
    )
    parser.add_argument("--source-override-event-id")
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
        elif args.command == "override":
            if not args.object_type:
                parser.error("--object-type is required for the override command.")
            if not args.object_id:
                parser.error("--object-id is required for the override command.")
            if not args.new_value:
                parser.error("--new-value is required for the override command.")
            if not args.reason:
                parser.error("--reason is required for the override command.")
            report = apply_object_override(
                args.object_type,
                args.object_id,
                project_root=Path(args.project_root),
                new_value=args.new_value,
                reason=args.reason,
                manual_command=args.manual_command or "override",
            )
        elif args.command == "guidance":
            if not args.object_type:
                parser.error("--object-type is required for the guidance command.")
            if not args.object_id:
                parser.error("--object-id is required for the guidance command.")
            if not args.component_stage:
                parser.error("--component-stage is required for the guidance command.")
            if not args.directive_key:
                parser.error("--directive-key is required for the guidance command.")
            if not args.directive_value:
                parser.error("--directive-value is required for the guidance command.")
            if not args.reason:
                parser.error("--reason is required for the guidance command.")
            report = persist_expert_guidance(
                args.object_type,
                args.object_id,
                project_root=Path(args.project_root),
                component_stage=args.component_stage,
                directive_key=args.directive_key,
                directive_value=args.directive_value,
                reason=args.reason,
                guidance_scope=args.scope,
                source_override_event_id=args.source_override_event_id,
                manual_command=args.manual_command or "guidance",
            )
        elif args.command == "clarify-guidance":
            if not args.object_type:
                parser.error("--object-type is required for the clarify-guidance command.")
            if not args.object_id:
                parser.error("--object-id is required for the clarify-guidance command.")
            if not args.component_stage:
                parser.error("--component-stage is required for the clarify-guidance command.")
            if not args.directive_key:
                parser.error("--directive-key is required for the clarify-guidance command.")
            if not args.directive_value:
                parser.error("--directive-value is required for the clarify-guidance command.")
            if not args.reason:
                parser.error("--reason is required for the clarify-guidance command.")
            report = request_guidance_clarification(
                args.object_type,
                args.object_id,
                project_root=Path(args.project_root),
                component_stage=args.component_stage,
                directive_key=args.directive_key,
                directive_value=args.directive_value,
                reason=args.reason,
                request_kind=args.request_kind,
                source_override_event_id=args.source_override_event_id,
                manual_command=args.manual_command or "clarify-guidance",
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
