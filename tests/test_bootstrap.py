from __future__ import annotations

import sqlite3

import pytest

from job_hunt_copilot.bootstrap import run_bootstrap
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


def test_bootstrap_requires_minimum_assets(tmp_path):
    project_root = tmp_path / "repo"
    project_root.mkdir()
    create_minimal_project(project_root)
    (project_root / "assets" / "outreach" / "cold-outreach-guide.md").unlink()

    with pytest.raises(FileNotFoundError):
        run_bootstrap(project_root=project_root)
