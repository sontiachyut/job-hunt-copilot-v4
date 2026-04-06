from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .paths import ProjectPaths


PROVIDER_SECRET_FILENAMES = {
    "apollo": "apollo_keys.json",
    "prospeo": "prospeo_keys.json",
    "getprospect": "getprospect_keys.json",
    "hunter": "hunter_keys.json",
}

GMAIL_CLIENT_SECRET_FILENAME = "client_secret_runtime.json"
GMAIL_TOKEN_FILENAME = "token.json"


def discover_runtime_secrets(paths: ProjectPaths) -> Path | None:
    configured = os.environ.get("JHC_RUNTIME_SECRETS_FILE")
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured))
    candidates.extend(paths.runtime_secrets_candidates())
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return None


def existing_vendor_secret_paths(paths: ProjectPaths) -> list[Path]:
    targets = [paths.secrets_dir / name for name in PROVIDER_SECRET_FILENAMES.values()]
    targets.extend(sorted(paths.secrets_dir.glob("client_secret_*.json")))
    token_path = paths.secrets_dir / GMAIL_TOKEN_FILENAME
    if token_path.exists():
        targets.append(token_path)
    return [target.resolve() for target in targets if target.exists()]


def materialize_runtime_secrets(paths: ProjectPaths, overwrite: bool = False) -> dict[str, Any]:
    paths.secrets_dir.mkdir(parents=True, exist_ok=True)
    runtime_secrets_path = discover_runtime_secrets(paths)

    if runtime_secrets_path is None:
        existing_paths = existing_vendor_secret_paths(paths)
        required = [paths.secrets_dir / name for name in PROVIDER_SECRET_FILENAMES.values()]
        client_secret_exists = any(path.name.startswith("client_secret_") for path in existing_paths)
        if all(path.exists() for path in required) and client_secret_exists:
            return {
                "runtime_secrets_path": None,
                "materialized_paths": [],
                "available_paths": [str(path) for path in existing_paths],
            }
        raise FileNotFoundError(
            "Expected secrets/runtime_secrets.json or pre-materialized vendor secret files in secrets/."
        )

    payload = json.loads(runtime_secrets_path.read_text(encoding="utf-8"))
    materialized_paths: list[str] = []

    def maybe_write_json(target: Path, content: Any) -> None:
        if target.exists() and not overwrite:
            return
        target.write_text(json.dumps(content, indent=2, sort_keys=False) + "\n", encoding="utf-8")
        materialized_paths.append(str(target))

    for provider_name, filename in PROVIDER_SECRET_FILENAMES.items():
        provider_payload = payload.get(provider_name)
        if provider_payload:
            maybe_write_json(paths.secrets_dir / filename, provider_payload)

    gmail_payload = payload.get("gmail", {})
    client_secret_payload = gmail_payload.get("client_secret_json")
    if client_secret_payload:
        maybe_write_json(paths.secrets_dir / GMAIL_CLIENT_SECRET_FILENAME, client_secret_payload)

    token_payload = gmail_payload.get("token_json")
    if token_payload:
        maybe_write_json(paths.secrets_dir / GMAIL_TOKEN_FILENAME, token_payload)

    available_paths = existing_vendor_secret_paths(paths)
    return {
        "runtime_secrets_path": str(runtime_secrets_path),
        "materialized_paths": materialized_paths,
        "available_paths": [str(path) for path in available_paths],
    }
