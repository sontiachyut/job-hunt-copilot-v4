from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path

from job_hunt_copilot.paths import ProjectPaths


def create_minimal_project(root: Path) -> None:
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


def initialize_git_repository(root: Path) -> None:
    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "add", "."],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "Initial repo scaffold"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )


def seed_pending_review_tailoring_run(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    job_posting_id: str,
    company_name: str,
    role_title: str,
    resume_tailoring_run_id: str = "rtr_pending_review",
    base_used: str = "generalist",
    timestamp: str = "2026-04-08T00:00:00Z",
) -> str:
    workspace_dir = paths.tailoring_workspace_dir(company_name, role_title)
    workspace_dir.mkdir(parents=True, exist_ok=True)
    final_resume_path = workspace_dir / "Achyutaram Sonti.pdf"
    final_resume_path.write_text("% final resume placeholder\n", encoding="utf-8")
    meta_path = paths.tailoring_meta_path(company_name, role_title)
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(
        "\n".join(
            [
                f"resume_tailoring_run_id: {resume_tailoring_run_id}",
                f"base_used: {base_used}",
                "tailoring_status: tailored",
                "resume_review_status: resume_review_pending",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    connection.execute(
        """
        INSERT INTO resume_tailoring_runs (
          resume_tailoring_run_id, job_posting_id, base_used, tailoring_status,
          resume_review_status, workspace_path, meta_yaml_path, final_resume_path,
          verification_outcome, started_at, completed_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            resume_tailoring_run_id,
            job_posting_id,
            base_used,
            "tailored",
            "resume_review_pending",
            paths.relative_to_root(workspace_dir).as_posix(),
            paths.relative_to_root(meta_path).as_posix(),
            paths.relative_to_root(final_resume_path).as_posix(),
            "pass",
            timestamp,
            timestamp,
            timestamp,
            timestamp,
        ),
    )
    connection.commit()
    return resume_tailoring_run_id
