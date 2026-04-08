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


def test_select_work_target_prefers_current_focus_slice_owner_role() -> None:
    module = load_run_build_lead_cycle_module()
    board = {
        "current_focus": {
            "epic_id": "BA-10",
            "slice_id": "BA-10-S4",
            "owner_role": "build-lead",
        },
        "epics": [
            {
                "id": "BA-10",
                "name": "Validation and hardening",
                "status": "in_progress",
                "owner_role": "quality-engineer",
                "near_term_slices": [
                    {
                        "id": "BA-10-S3",
                        "name": "Cross-component regression and blocker burn-down",
                        "owner_role": "quality-engineer",
                        "status": "in_progress",
                    },
                    {
                        "id": "BA-10-S4",
                        "name": "Downstream supervisor action-catalog burn-down",
                        "owner_role": "build-lead",
                        "status": "in_progress",
                    },
                ],
            }
        ],
    }

    epic, slice_item = module.select_work_target(board)

    assert epic["id"] == "BA-10"
    assert slice_item["id"] == "BA-10-S4"
    assert slice_item["owner_role"] == "build-lead"


def test_build_prompt_uses_selected_slice_and_slice_owner_role() -> None:
    module = load_run_build_lead_cycle_module()
    epic = {
        "id": "BA-10",
        "name": "Validation and hardening",
        "owner_role": "quality-engineer",
        "objective": "Add validation and blocker burn-down.",
        "done_when": ["acceptance coverage is traceable"],
    }
    slice_item = {
        "id": "BA-10-S4",
        "name": "Downstream supervisor action-catalog burn-down",
        "owner_role": "build-lead",
        "deliverables": ["register one downstream action beyond lead_handoff"],
    }
    snapshot_path = REPO_ROOT / "build-agent" / "state" / "context-snapshots" / "example.json"
    snapshot = {"resume_mode": False}

    prompt = module.build_prompt(
        REPO_ROOT,
        "build-cycle-example",
        epic,
        slice_item,
        snapshot_path,
        snapshot,
    )

    assert "- selected_slice_id: BA-10-S4" in prompt
    assert "- selected_slice_name: Downstream supervisor action-catalog burn-down" in prompt
    assert "- owner_role: build-lead" in prompt
    assert "register one downstream action beyond lead_handoff" in prompt
    assert "Do not switch to a neighboring support or evidence slice just because it is easier." in prompt
