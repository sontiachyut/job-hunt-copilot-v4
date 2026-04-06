from __future__ import annotations

import json
import sqlite3

import pytest

from job_hunt_copilot.bootstrap import run_bootstrap


def create_minimal_project(root):
    (root / "prd").mkdir(parents=True, exist_ok=True)
    (root / "prd" / "spec.md").write_text("# spec\n", encoding="utf-8")

    ai_dir = root / "assets" / "resume-tailoring" / "ai"
    ai_dir.mkdir(parents=True, exist_ok=True)
    (root / "assets" / "resume-tailoring" / "profile.md").write_text("# profile\n", encoding="utf-8")
    (ai_dir / "system-prompt.md").write_text("# prompt\n", encoding="utf-8")
    (ai_dir / "cookbook.md").write_text("# cookbook\n", encoding="utf-8")
    (ai_dir / "sop-swe-experience-tailoring.md").write_text("# sop\n", encoding="utf-8")
    base_dir = root / "assets" / "resume-tailoring" / "base" / "generalist"
    base_dir.mkdir(parents=True, exist_ok=True)
    (base_dir / "base-resume.tex").write_text("% resume\n", encoding="utf-8")
    outreach_dir = root / "assets" / "outreach"
    outreach_dir.mkdir(parents=True, exist_ok=True)
    (outreach_dir / "cold-outreach-guide.md").write_text("# guide\n", encoding="utf-8")

    secrets_dir = root / "secrets"
    secrets_dir.mkdir(parents=True, exist_ok=True)
    (secrets_dir / "runtime_secrets.json").write_text(
        json.dumps(
            {
                "apollo": {"api_key": "apollo-key"},
                "prospeo": {"api_key": "prospeo-key"},
                "getprospect": {"api_key": "getprospect-key"},
                "hunter": {"keys": ["hunter-key"]},
                "gmail": {
                    "oauth_scopes": [
                        "https://www.googleapis.com/auth/gmail.send",
                        "https://www.googleapis.com/auth/gmail.readonly",
                    ],
                    "client_secret_json": {
                        "installed": {
                            "client_id": "client-id",
                            "project_id": "project-id",
                        }
                    },
                    "token_json": {
                        "token": "refresh-token",
                        "scopes": ["https://www.googleapis.com/auth/gmail.readonly"],
                    },
                },
            },
            indent=2,
            sort_keys=False,
        )
        + "\n",
        encoding="utf-8",
    )


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

    connection = sqlite3.connect(project_root / "job_hunt_copilot.db")
    migrations = connection.execute(
        "SELECT migration_name FROM schema_migrations ORDER BY migration_name"
    ).fetchall()
    user_version = connection.execute("PRAGMA user_version").fetchone()[0]
    connection.close()

    assert migrations == [("0001_runtime_bootstrap.sql",)]
    assert user_version == 1


def test_bootstrap_is_idempotent(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    create_minimal_project(project_root)

    first_report = run_bootstrap(project_root=project_root)
    second_report = run_bootstrap(project_root=project_root)

    assert first_report["database"]["applied_migrations"] == ["0001_runtime_bootstrap.sql"]
    assert second_report["database"]["applied_migrations"] == []
    assert second_report["directories"]["created_paths"] == []


def test_bootstrap_requires_minimum_assets(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    create_minimal_project(project_root)
    (project_root / "assets" / "outreach" / "cold-outreach-guide.md").unlink()

    with pytest.raises(FileNotFoundError):
        run_bootstrap(project_root=project_root)
