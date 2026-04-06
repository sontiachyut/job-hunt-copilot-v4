from __future__ import annotations

import yaml

from job_hunt_copilot.runtime_pack import materialize_runtime_pack
from tests.support import create_minimal_project


def test_runtime_pack_preserves_existing_progress_surfaces(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    create_minimal_project(project_root)

    initial_report = materialize_runtime_pack(project_root=project_root)
    progress_log_path = project_root / "ops" / "agent" / "progress-log.md"
    ops_plan_path = project_root / "ops" / "agent" / "ops-plan.yaml"

    progress_log_path.write_text(
        "# Supervisor Progress Log\n\n## Current Summary\n- updated_at: custom\n",
        encoding="utf-8",
    )
    custom_ops_plan = {
        "contract_version": "1.0",
        "generated_at": "custom",
        "agent_mode": "paused",
        "active_priorities": [],
        "watch_items": [],
        "maintenance_backlog": [],
        "weak_areas": [],
        "replan": {
            "status": "active",
            "last_replan_at": "custom",
            "next_focus": "custom",
            "reason": "custom",
        },
    }
    ops_plan_path.write_text(yaml.safe_dump(custom_ops_plan, sort_keys=False), encoding="utf-8")

    second_report = materialize_runtime_pack(project_root=project_root)

    assert initial_report["created_paths"]
    assert progress_log_path.read_text(encoding="utf-8").startswith("# Supervisor Progress Log\n\n## Current Summary\n- updated_at: custom\n")
    assert yaml.safe_load(ops_plan_path.read_text(encoding="utf-8")) == custom_ops_plan
    assert str(progress_log_path) in second_report["preserved_paths"]
    assert str(ops_plan_path) in second_report["preserved_paths"]
