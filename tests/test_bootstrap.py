from __future__ import annotations

import sqlite3

import pytest
import yaml

from job_hunt_copilot.bootstrap import run_bootstrap
from job_hunt_copilot.paths import ProjectPaths
from job_hunt_copilot.supervisor import registered_supervisor_action_catalog
from tests.support import create_minimal_project


def test_bootstrap_materializes_support_dirs_secrets_and_db(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    create_minimal_project(project_root)

    report = run_bootstrap(project_root=project_root)

    assert report["status"] == "ok"
    assert (project_root / "paste" / "paste.txt").exists()
    assert (project_root / "linkedin-scraping" / "runtime" / "gmail").exists()
    assert (project_root / "resume-tailoring" / "output" / "tailored").exists()
    assert (project_root / "secrets" / "apollo_keys.json").exists()
    assert (project_root / "secrets" / "client_secret_runtime.json").exists()
    assert (project_root / "job_hunt_copilot.db").exists()
    assert (project_root / "ops" / "agent" / "identity.yaml").exists()
    assert (project_root / "ops" / "agent" / "policies.yaml").exists()
    assert (project_root / "ops" / "agent" / "action-catalog.yaml").exists()
    assert (project_root / "ops" / "agent" / "service-goals.yaml").exists()
    assert (project_root / "ops" / "agent" / "escalation-policy.yaml").exists()
    assert (project_root / "ops" / "agent" / "chat-bootstrap.md").exists()
    assert (project_root / "ops" / "agent" / "supervisor-bootstrap.md").exists()
    assert (project_root / "ops" / "agent" / "progress-log.md").exists()
    assert (project_root / "ops" / "agent" / "ops-plan.yaml").exists()
    assert (project_root / "ops" / "logs").exists()
    assert str(project_root / "ops" / "agent" / "identity.yaml") in report["runtime_pack"]["created_paths"]

    connection = sqlite3.connect(project_root / "job_hunt_copilot.db")
    migrations = connection.execute(
        "SELECT migration_name FROM schema_migrations ORDER BY migration_name"
    ).fetchall()
    user_version = connection.execute("PRAGMA user_version").fetchone()[0]
    connection.close()

    assert migrations == [
        ("0001_runtime_bootstrap.sql",),
        ("0002_canonical_schema.sql",),
    ]
    assert user_version == 2


def test_bootstrap_is_idempotent(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    create_minimal_project(project_root)

    first_report = run_bootstrap(project_root=project_root)
    second_report = run_bootstrap(project_root=project_root)

    assert first_report["database"]["applied_migrations"] == [
        "0001_runtime_bootstrap.sql",
        "0002_canonical_schema.sql",
    ]
    assert second_report["database"]["applied_migrations"] == []
    assert second_report["directories"]["created_paths"] == []
    assert str(project_root / "ops" / "agent" / "progress-log.md") in second_report["runtime_pack"]["preserved_paths"]
    assert str(project_root / "ops" / "agent" / "ops-plan.yaml") in second_report["runtime_pack"]["preserved_paths"]


def test_bootstrap_requires_minimum_assets(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    create_minimal_project(project_root)
    (project_root / "assets" / "outreach" / "cold-outreach-guide.md").unlink()

    with pytest.raises(FileNotFoundError):
        run_bootstrap(project_root=project_root)


def test_bootstrap_runtime_pack_uses_absolute_paths_and_expected_runtime_shapes(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    create_minimal_project(project_root)

    run_bootstrap(project_root=project_root)
    paths = ProjectPaths.from_root(project_root)

    identity = yaml.safe_load(paths.ops_agent_identity_path.read_text(encoding="utf-8"))
    action_catalog = yaml.safe_load(paths.ops_agent_action_catalog_path.read_text(encoding="utf-8"))
    service_goals = yaml.safe_load(paths.ops_agent_service_goals_path.read_text(encoding="utf-8"))
    ops_plan = yaml.safe_load(paths.ops_agent_ops_plan_path.read_text(encoding="utf-8"))
    chat_bootstrap = paths.ops_agent_chat_bootstrap_path.read_text(encoding="utf-8")

    assert identity["canonical_state_locations"]["project_root"] == str(project_root)
    assert identity["canonical_state_locations"]["database"] == str(project_root / "job_hunt_copilot.db")
    assert [entry["action_id"] for entry in action_catalog["actions"]] == [
        entry.action_id for entry in registered_supervisor_action_catalog().values()
    ]
    assert service_goals["deployment"]["scheduler"] == "launchd"
    assert service_goals["deployment"]["heartbeat_interval_seconds"] == 180
    assert ops_plan["agent_mode"] == "stopped"
    assert str(project_root) in chat_bootstrap
    assert str(paths.ops_agent_identity_path) in chat_bootstrap
