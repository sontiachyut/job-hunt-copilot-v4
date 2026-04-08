from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_BUILD_LEAD_CYCLE_PATH = (
    REPO_ROOT / "build-agent" / "scripts" / "run_build_lead_cycle.py"
)


def load_run_build_lead_cycle_module() -> ModuleType:
    script_dir = str(RUN_BUILD_LEAD_CYCLE_PATH.parent)
    sys.path.insert(0, script_dir)
    try:
        spec = importlib.util.spec_from_file_location(
            "test_run_build_lead_cycle",
            RUN_BUILD_LEAD_CYCLE_PATH,
        )
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


def test_build_codex_exec_command_uses_supported_workspace_write_invocation() -> None:
    module = load_run_build_lead_cycle_module()
    project_root = REPO_ROOT
    last_message_path = (
        REPO_ROOT / "build-agent" / "logs" / "cycles" / "example.last-message.md"
    )

    command = module.build_codex_exec_command(
        codex_bin="/opt/homebrew/bin/codex",
        project_root=project_root,
        last_message_path=last_message_path,
    )

    assert command == [
        "/opt/homebrew/bin/codex",
        "exec",
        "--ephemeral",
        "--sandbox",
        "workspace-write",
        "-C",
        str(project_root),
        "-o",
        str(last_message_path),
        "-",
    ]
    assert "--ask-for-approval" not in command
    assert "--approval" not in command
