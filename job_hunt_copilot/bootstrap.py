from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
from pathlib import Path
from typing import Any

from .contracts import CONTRACT_VERSION
from .db import initialize_database
from .paths import ProjectPaths
from .records import now_utc_iso
from .runtime_pack import materialize_runtime_pack
from .secrets import materialize_runtime_secrets

REQUIRED_PYTHON = (3, 11)
REQUIRED_MODULES = {
    "google-auth-oauthlib": "google_auth_oauthlib",
    "google-api-python-client": "googleapiclient",
    "requests": "requests",
    "dnspython": "dns",
    "PyYAML": "yaml",
    "pytest": "pytest",
}


def ensure_required_inputs(paths: ProjectPaths) -> dict[str, Any]:
    missing: list[str] = []
    required_paths = [paths.spec_path, *paths.required_asset_paths()]
    for required_path in required_paths:
        if not required_path.exists():
            missing.append(str(required_path))

    base_resume_sources = [str(path) for path in paths.base_resume_sources()]
    if not base_resume_sources:
        missing.append("assets/resume-tailoring/base/**/base-resume.tex")

    if missing:
        raise FileNotFoundError("Missing required build inputs: " + ", ".join(missing))

    return {
        "spec_path": str(paths.spec_path),
        "base_resume_sources": base_resume_sources,
        "required_asset_paths": [str(path) for path in paths.required_asset_paths()],
    }


def ensure_runtime_support(paths: ProjectPaths) -> dict[str, list[str]]:
    created_paths: list[str] = []
    existing_paths: list[str] = []

    for directory in paths.runtime_support_directories():
        if directory.exists():
            existing_paths.append(str(directory))
        else:
            directory.mkdir(parents=True, exist_ok=True)
            created_paths.append(str(directory))

    if paths.paste_inbox_path.exists():
        existing_paths.append(str(paths.paste_inbox_path))
    else:
        paths.paste_inbox_path.write_text("", encoding="utf-8")
        created_paths.append(str(paths.paste_inbox_path))

    return {
        "created_paths": created_paths,
        "existing_paths": existing_paths,
    }


def check_runtime_prerequisites() -> dict[str, Any]:
    actual_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    python_ok = (
        sys.version_info.major == REQUIRED_PYTHON[0]
        and sys.version_info.minor == REQUIRED_PYTHON[1]
    )

    modules = []
    missing_modules = []
    for package_name, module_name in REQUIRED_MODULES.items():
        present = importlib.util.find_spec(module_name) is not None
        modules.append(
            {
                "package": package_name,
                "module": module_name,
                "ok": present,
            }
        )
        if not present:
            missing_modules.append(package_name)

    latex_binary = shutil.which("pdflatex") or shutil.which("latexmk")
    latex_ok = latex_binary is not None

    result = {
        "python": {
            "expected": "3.11.x",
            "actual": actual_version,
            "ok": python_ok,
        },
        "packages": modules,
        "latex": {
            "expected_binary": "pdflatex or latexmk",
            "resolved_binary": latex_binary,
            "ok": latex_ok,
        },
    }

    if not python_ok:
        raise RuntimeError(
            f"Expected Python 3.11.x for bootstrap checks, found {actual_version}."
        )
    if missing_modules:
        raise RuntimeError(
            "Missing required Python packages: " + ", ".join(sorted(missing_modules))
        )
    if not latex_ok:
        raise RuntimeError("Expected a LaTeX toolchain with pdflatex or latexmk on PATH.")

    return result


def run_bootstrap(
    project_root: Path | str | None = None,
    *,
    overwrite_secrets: bool = False,
    check_prerequisites: bool = False,
) -> dict[str, Any]:
    paths = ProjectPaths.from_root(project_root)

    report = {
        "contract_version": CONTRACT_VERSION,
        "produced_at": now_utc_iso(),
        "project_root": str(paths.project_root),
        "status": "ok",
        "inputs": ensure_required_inputs(paths),
        "directories": ensure_runtime_support(paths),
        "secrets": materialize_runtime_secrets(paths, overwrite=overwrite_secrets),
    }

    migration_result = initialize_database(paths.db_path)
    report["database"] = {
        "db_path": str(migration_result.db_path),
        "applied_migrations": migration_result.applied_migrations,
        "user_version": migration_result.user_version,
    }
    report["runtime_pack"] = materialize_runtime_pack(paths.project_root)

    if check_prerequisites:
        report["prerequisites"] = check_runtime_prerequisites()

    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", choices=["bootstrap", "prereqs"], default="bootstrap")
    parser.add_argument("--project-root", default=None)
    parser.add_argument("--force-secrets", action="store_true")
    parser.add_argument("--check-prerequisites", action="store_true")
    args = parser.parse_args()

    try:
        if args.command == "prereqs":
            report = {
                "contract_version": CONTRACT_VERSION,
                "produced_at": now_utc_iso(),
                "status": "ok",
                "prerequisites": check_runtime_prerequisites(),
            }
        else:
            report = run_bootstrap(
                project_root=Path(args.project_root) if args.project_root else None,
                overwrite_secrets=args.force_secrets,
                check_prerequisites=args.check_prerequisites,
            )
    except Exception as exc:  # pragma: no cover - CLI failure formatting
        failure = {
            "contract_version": CONTRACT_VERSION,
            "produced_at": now_utc_iso(),
            "status": "error",
            "error_type": type(exc).__name__,
            "message": str(exc),
        }
        print(json.dumps(failure, indent=2))
        return 1

    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
