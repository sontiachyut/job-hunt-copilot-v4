#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from common import default_project_root, require_project_git_root


def run_git(project_root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=project_root,
        text=True,
        capture_output=True,
        check=check,
    )


def status_has_changes(project_root: Path) -> bool:
    result = run_git(project_root, "status", "--porcelain", check=True)
    return bool(result.stdout.strip())


def current_branch(project_root: Path) -> str:
    result = run_git(project_root, "branch", "--show-current", check=True)
    branch = result.stdout.strip()
    if not branch:
        raise RuntimeError("Unable to determine current git branch for build checkpoint push.")
    return branch


def ensure_origin(project_root: Path) -> str:
    result = run_git(project_root, "remote", "get-url", "origin", check=False)
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError("Build checkpoint push requires git remote 'origin' to exist.")
    return result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=str(default_project_root()))
    parser.add_argument("--cycle-id", required=True)
    parser.add_argument("--epic-id", required=True)
    parser.add_argument("--epic-name", required=True)
    parser.add_argument("--cycle-result", required=True)
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    require_project_git_root(project_root)
    ensure_origin(project_root)

    if not status_has_changes(project_root):
        print(json.dumps({"result": "no_changes"}))
        return 0

    branch = current_branch(project_root)

    run_git(project_root, "add", "-A")

    commit_subject = f"checkpoint(build-agent): {args.cycle_id} {args.epic_id}"
    commit_body = (
        f"Epic: {args.epic_id} - {args.epic_name}\n"
        f"Cycle result: {args.cycle_result}\n"
        f"Cycle id: {args.cycle_id}\n"
    )

    commit = run_git(project_root, "commit", "-m", commit_subject, "-m", commit_body, check=False)
    if commit.returncode != 0:
        status_after_add = run_git(project_root, "status", "--porcelain", check=True)
        if not status_after_add.stdout.strip():
            print(json.dumps({"result": "no_changes_after_add"}))
            return 0
        raise RuntimeError(commit.stderr.strip() or commit.stdout.strip() or "git commit failed")

    sha = run_git(project_root, "rev-parse", "HEAD", check=True).stdout.strip()
    push = run_git(project_root, "push", "origin", branch, check=False)
    if push.returncode != 0:
        raise RuntimeError(push.stderr.strip() or push.stdout.strip() or "git push failed")

    print(
        json.dumps(
            {
                "result": "pushed",
                "branch": branch,
                "commit_sha": sha,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
