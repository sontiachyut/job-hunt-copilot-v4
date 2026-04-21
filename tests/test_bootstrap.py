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
        ("0003_company_grouping_keys.sql",),
        ("0004_application_and_responder_tracking.sql",),
        ("0005_refresh_expert_review_queue_view.sql",),
        ("0006_email_discovery_provider_cooldown.sql",),
    ]
    assert user_version == 6


def test_bootstrap_is_idempotent(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    create_minimal_project(project_root)

    first_report = run_bootstrap(project_root=project_root)
    second_report = run_bootstrap(project_root=project_root)

    assert first_report["database"]["applied_migrations"] == [
        "0001_runtime_bootstrap.sql",
        "0002_canonical_schema.sql",
        "0003_company_grouping_keys.sql",
        "0004_application_and_responder_tracking.sql",
        "0005_refresh_expert_review_queue_view.sql",
        "0006_email_discovery_provider_cooldown.sql",
    ]
    assert second_report["database"]["applied_migrations"] == []
    assert second_report["directories"]["created_paths"] == []
    assert str(project_root / "ops" / "agent" / "progress-log.md") in second_report["runtime_pack"]["preserved_paths"]
    assert str(project_root / "ops" / "agent" / "ops-plan.yaml") in second_report["runtime_pack"]["preserved_paths"]


def test_bootstrap_refreshes_stale_expert_review_queue_view(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    create_minimal_project(project_root)

    run_bootstrap(project_root=project_root)

    connection = sqlite3.connect(project_root / "job_hunt_copilot.db")
    connection.executescript(
        """
        DROP VIEW IF EXISTS expert_review_queue;
        CREATE VIEW expert_review_queue AS
        SELECT
          erp.expert_review_packet_id,
          erp.pipeline_run_id,
          COALESCE(erp.job_posting_id, pr.job_posting_id) AS job_posting_id,
          erp.packet_status,
          erp.packet_path,
          pr.run_status,
          pr.current_stage,
          pr.run_summary,
          jp.company_name,
          jp.role_title,
          GROUP_CONCAT(ai.agent_incident_id) AS incident_ids,
          GROUP_CONCAT(ai.summary, ' | ') AS incident_summaries,
          erp.created_at
        FROM expert_review_packets erp
        JOIN pipeline_runs pr
          ON pr.pipeline_run_id = erp.pipeline_run_id
        LEFT JOIN job_postings jp
          ON jp.job_posting_id = COALESCE(erp.job_posting_id, pr.job_posting_id)
        LEFT JOIN agent_incidents ai
          ON ai.pipeline_run_id = pr.pipeline_run_id
         AND ai.status IN ('open', 'in_repair', 'escalated')
        WHERE erp.packet_status = 'pending_expert_review'
        GROUP BY
          erp.expert_review_packet_id,
          erp.pipeline_run_id,
          COALESCE(erp.job_posting_id, pr.job_posting_id),
          erp.packet_status,
          erp.packet_path,
          pr.run_status,
          pr.current_stage,
          pr.run_summary,
          jp.company_name,
          jp.role_title,
          erp.created_at;
        """
    )
    connection.execute(
        "DELETE FROM schema_migrations WHERE migration_name = ?",
        ("0005_refresh_expert_review_queue_view.sql",),
    )
    connection.execute("PRAGMA user_version = 4")
    connection.commit()
    connection.close()

    report = run_bootstrap(project_root=project_root)
    assert report["database"]["applied_migrations"] == [
        "0005_refresh_expert_review_queue_view.sql",
    ]

    connection = sqlite3.connect(project_root / "job_hunt_copilot.db")
    view_sql = connection.execute(
        """
        SELECT sql
        FROM sqlite_master
        WHERE type = 'view' AND name = 'expert_review_queue'
        """
    ).fetchone()[0]
    user_version = connection.execute("PRAGMA user_version").fetchone()[0]
    connection.close()

    assert "erp.summary_excerpt" in view_sql
    assert user_version == 5


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
    assert service_goals["deployment"]["heartbeat_interval_seconds"] == 5
    assert ops_plan["agent_mode"] == "stopped"
    assert str(project_root) in chat_bootstrap
    assert str(paths.ops_agent_identity_path) in chat_bootstrap
