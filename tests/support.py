from __future__ import annotations

import json
from pathlib import Path


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
