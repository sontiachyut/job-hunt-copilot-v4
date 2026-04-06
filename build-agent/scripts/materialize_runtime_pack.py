#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import (
    build_agent_root,
    build_control_path,
    build_leases_path,
    build_plist_output_path,
    build_plist_template_path,
    build_runtime_pack_path,
    default_control_state,
    default_leases,
    default_project_root,
    ensure_dirs,
    load_json,
    load_yaml,
    now_utc_iso,
    require_project_git_root,
    resolve_codex_bin,
    resolve_python_bin,
    save_json,
    write_text_atomic,
)


def render_plist(project_root: Path) -> str:
    template = build_plist_template_path(project_root).read_text(encoding="utf-8")
    replacements = {
        "__PROJECT_ROOT__": str(project_root),
        "__PYTHON_BIN__": resolve_python_bin(),
        "__RUN_BUILD_LEAD_CYCLE__": str(build_agent_root(project_root) / "scripts" / "run_build_lead_cycle.py"),
        "__STDOUT_LOG__": str(build_agent_root(project_root) / "logs" / "build-lead.stdout.log"),
        "__STDERR_LOG__": str(build_agent_root(project_root) / "logs" / "build-lead.stderr.log"),
    }
    rendered = template
    for needle, value in replacements.items():
        rendered = rendered.replace(needle, value)
    return rendered


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=str(default_project_root()))
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    ensure_dirs(project_root)
    require_project_git_root(project_root)

    build_root = build_agent_root(project_root)
    runtime_pack = {
        "contract_version": "1.0",
        "generated_at": now_utc_iso(),
        "project_root": str(project_root),
        "build_agent_root": str(build_root),
        "python_bin": resolve_python_bin(),
        "codex_bin": resolve_codex_bin(),
        "identity": load_yaml(build_root / "identity.yaml"),
        "policies": load_yaml(build_root / "policies.yaml"),
        "coordination": load_yaml(build_root / "coordination.yaml"),
        "task_catalog": load_yaml(build_root / "task-catalog.yaml"),
        "state_paths": {
            "build_board": str(build_root / "state" / "build-board.yaml"),
            "build_journal": str(build_root / "state" / "build-journal.md"),
            "implementation_plan": str(build_root / "state" / "IMPLEMENTATION_PLAN.md"),
            "codex_progress": str(build_root / "state" / "codex-progress.txt"),
            "control_state": str(build_control_path(project_root)),
            "leases": str(build_leases_path(project_root)),
        },
        "bootstrap_files": {
            "builder": str(build_root / "builder-bootstrap.md"),
            "chat": str(build_root / "chat-bootstrap.md"),
        },
    }
    save_json(build_runtime_pack_path(project_root), runtime_pack)

    control_path = build_control_path(project_root)
    if not control_path.exists():
        save_json(control_path, default_control_state())

    leases_path = build_leases_path(project_root)
    if not leases_path.exists():
        save_json(leases_path, default_leases())

    rendered_plist = render_plist(project_root)
    write_text_atomic(build_plist_output_path(project_root), rendered_plist)

    control_state = load_json(control_path, default_control_state())
    control_state["last_runtime_pack_path"] = str(build_runtime_pack_path(project_root))
    control_state["last_plist_path"] = str(build_plist_output_path(project_root))
    control_state["updated_at"] = now_utc_iso()
    save_json(control_path, control_state)

    print(
        json.dumps(
            {
                "runtime_pack": str(build_runtime_pack_path(project_root)),
                "plist": str(build_plist_output_path(project_root)),
                "generated_at": runtime_pack["generated_at"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
