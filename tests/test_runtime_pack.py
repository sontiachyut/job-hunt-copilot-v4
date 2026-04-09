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


def test_runtime_pack_chat_bootstrap_scaffolds_review_and_control_surfaces(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    create_minimal_project(project_root)

    report = materialize_runtime_pack(project_root=project_root)
    chat_bootstrap = (project_root / "ops" / "agent" / "chat-bootstrap.md").read_text(
        encoding="utf-8"
    )

    assert report["agent_mode"] == "stopped"
    assert "# Job Hunt Copilot Chat Bootstrap" in chat_bootstrap
    assert "You are the expert-facing operator for Job Hunt Copilot v4." in chat_bootstrap
    assert f"- Canonical DB: {project_root / 'job_hunt_copilot.db'}" in chat_bootstrap
    assert f"- Progress log: {project_root / 'ops' / 'agent' / 'progress-log.md'}" in chat_bootstrap
    assert f"- Ops plan: {project_root / 'ops' / 'agent' / 'ops-plan.yaml'}" in chat_bootstrap
    assert f"- Chat startup dashboard: {project_root / 'ops' / 'agent' / 'chat-startup.md'}" in chat_bootstrap
    assert (
        "3. use the persisted chat-startup dashboard as the clean first-response "
        "summary and compact review-queue snapshot"
    ) in chat_bootstrap
    assert (
        "4. inspect canonical control state, open incidents, pending expert review packets, "
        "and the relevant DB-backed status snapshot"
    ) in chat_bootstrap
    assert "- persist pause, resume, stop, replanning, and override intents into canonical state instead of relying on chat memory" in chat_bootstrap
    assert "- agent_mode: stopped" in chat_bootstrap
    assert "- open_incident_count: 0" in chat_bootstrap
    assert "- pending_review_count: 0" in chat_bootstrap


def test_runtime_pack_reflects_idle_timeout_resume_closure_and_remaining_chat_backlog(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    create_minimal_project(project_root)

    materialize_runtime_pack(project_root=project_root)
    ops_plan = yaml.safe_load((project_root / "ops" / "agent" / "ops-plan.yaml").read_text(encoding="utf-8"))

    assert ops_plan["maintenance_backlog"] == []
    assert ops_plan["weak_areas"] == [
        {
            "area": "action_catalog_coverage",
            "note": "Later pipeline stages beyond lead_handoff are not yet registered; unsupported needs escalate.",
        },
        {
            "area": "chat_review_control_depth",
            "note": "The runtime now auto-resumes after unexpected chat exit idles safely, but richer in-chat review retrieval, change summaries, and control routing are still backlog.",
        },
    ]
    assert all(
        priority["scope_type"] != "maintenance_change_batch"
        for priority in ops_plan["active_priorities"]
    )
