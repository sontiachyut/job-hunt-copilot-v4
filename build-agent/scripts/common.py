#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml


CONTRACT_VERSION = "1.0"


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def default_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def build_agent_root(project_root: Path) -> Path:
    return project_root / "build-agent"


def state_dir(project_root: Path) -> Path:
    return build_agent_root(project_root) / "state"


def runtime_dir(project_root: Path) -> Path:
    return build_agent_root(project_root) / "runtime"


def logs_dir(project_root: Path) -> Path:
    return build_agent_root(project_root) / "logs"


def cycles_log_dir(project_root: Path) -> Path:
    return logs_dir(project_root) / "cycles"


def context_snapshot_dir(project_root: Path) -> Path:
    return state_dir(project_root) / "context-snapshots"


def ensure_dirs(project_root: Path) -> None:
    for path in [
        runtime_dir(project_root),
        logs_dir(project_root),
        cycles_log_dir(project_root),
        context_snapshot_dir(project_root),
        build_agent_root(project_root) / "launchd",
    ]:
        path.mkdir(parents=True, exist_ok=True)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", delete=False, dir=path.parent, encoding="utf-8") as handle:
        handle.write(content)
        tmp_path = Path(handle.name)
    os.replace(tmp_path, path)


def load_json(path: Path, default: Any | None = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: Any) -> None:
    write_text_atomic(path, json.dumps(data, indent=2, sort_keys=False) + "\n")


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=False) + "\n")


def load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def save_yaml(path: Path, data: Any) -> None:
    write_text_atomic(path, yaml.safe_dump(data, sort_keys=False))


def build_control_path(project_root: Path) -> Path:
    return state_dir(project_root) / "build-control.json"


def build_leases_path(project_root: Path) -> Path:
    return state_dir(project_root) / "build-leases.json"


def build_cycles_path(project_root: Path) -> Path:
    return state_dir(project_root) / "build-cycles.jsonl"


def build_chat_sessions_path(project_root: Path) -> Path:
    return state_dir(project_root) / "build-chat-sessions.jsonl"


def build_runtime_pack_path(project_root: Path) -> Path:
    return runtime_dir(project_root) / "runtime-pack.json"


def build_plist_template_path(project_root: Path) -> Path:
    return build_agent_root(project_root) / "launchd" / "job-hunt-copilot-build-lead.plist.template"


def build_plist_output_path(project_root: Path) -> Path:
    return build_agent_root(project_root) / "launchd" / "job-hunt-copilot-build-lead.plist"


def default_control_state() -> dict[str, Any]:
    return {
        "contract_version": CONTRACT_VERSION,
        "agent_enabled": False,
        "agent_mode": "stopped",
        "pause_reason": None,
        "active_chat_session_id": None,
        "last_manual_command": None,
        "last_cycle_started_at": None,
        "last_cycle_completed_at": None,
        "last_sleep_wake_check_at": None,
        "last_sleep_wake_event_at": None,
        "last_sleep_wake_detection_method": None,
        "last_sleep_wake_recovery_at": None,
        "last_runtime_pack_path": None,
        "last_plist_path": None,
        "last_chat_started_at": None,
        "last_chat_ended_at": None,
        "last_chat_exit_mode": None,
        "mode_before_chat": None,
    }


def default_leases() -> dict[str, Any]:
    return {
        "contract_version": CONTRACT_VERSION,
        "leases": {},
    }


def load_control_state(project_root: Path) -> dict[str, Any]:
    path = build_control_path(project_root)
    data = load_json(path, default=None)
    if data is None:
        data = default_control_state()
        save_json(path, data)
    else:
        merged = default_control_state()
        merged.update(data)
        data = merged
        save_json(path, data)
    return data


def save_control_state(project_root: Path, data: dict[str, Any]) -> None:
    save_json(build_control_path(project_root), data)


def load_leases(project_root: Path) -> dict[str, Any]:
    path = build_leases_path(project_root)
    data = load_json(path, default=None)
    if data is None:
        data = default_leases()
        save_json(path, data)
    else:
        merged = default_leases()
        merged.update(data)
        data = merged
        save_json(path, data)
    return data


def save_leases(project_root: Path, data: dict[str, Any]) -> None:
    save_json(build_leases_path(project_root), data)


def iso_to_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def new_cycle_id() -> str:
    return f"build-cycle-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"


def lease_expiry_iso(hours: int = 4) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def require_project_git_root(project_root: Path) -> None:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=project_root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError("Build agent requires a dedicated git repository rooted at the project directory.")
    git_root = Path(result.stdout.strip()).resolve()
    expected = project_root.resolve()
    if git_root != expected:
        raise RuntimeError(
            f"Build agent requires the project directory to be the git root. "
            f"Current git root is {git_root}, expected {expected}."
        )


def resolve_binary(env_name: str, candidates: list[str]) -> str:
    configured = os.environ.get(env_name)
    if configured and Path(configured).exists():
        return configured
    for candidate in candidates:
        found = shutil.which(candidate)
        if found:
            return found
        if Path(candidate).exists():
            return str(Path(candidate))
    raise RuntimeError(f"Unable to resolve required binary for {env_name}.")


def resolve_python_bin() -> str:
    current_python = Path(sys.executable).resolve()
    if current_python.exists():
        return str(current_python)
    return resolve_binary(
        "JHC_PYTHON_BIN",
        [
            "/opt/homebrew/opt/python@3.11/libexec/bin/python3",
            "/opt/homebrew/bin/python3",
            "/usr/local/bin/python3",
            "python3",
        ],
    )


def resolve_codex_bin() -> str:
    return resolve_binary(
        "JHC_CODEX_BIN",
        [
            "codex",
            "/opt/homebrew/bin/codex",
            "/usr/local/bin/codex",
        ],
    )


def resolve_node_bin() -> str:
    return resolve_binary(
        "JHC_NODE_BIN",
        [
            "node",
            "/opt/homebrew/bin/node",
            "/usr/local/bin/node",
        ],
    )


def resolve_runtime_path() -> str:
    ordered_dirs = [
        str(Path(resolve_python_bin()).resolve().parent),
        str(Path(resolve_codex_bin()).resolve().parent),
        str(Path(resolve_node_bin()).resolve().parent),
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
        "/usr/sbin",
        "/sbin",
    ]
    existing_path = os.environ.get("PATH", "")
    if existing_path:
        ordered_dirs.extend(part for part in existing_path.split(os.pathsep) if part)

    deduped: list[str] = []
    seen: set[str] = set()
    for raw_dir in ordered_dirs:
        resolved_dir = str(Path(raw_dir).expanduser())
        if resolved_dir in seen:
            continue
        seen.add(resolved_dir)
        deduped.append(resolved_dir)
    return os.pathsep.join(deduped)


def runtime_subprocess_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env["PATH"] = resolve_runtime_path()
    if extra:
        env.update(extra)
    return env


def process_is_alive(pid: int | None) -> bool:
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def latest_build_activity_at(control_state: dict[str, Any]) -> datetime | None:
    candidates = [
        control_state.get("last_cycle_started_at"),
        control_state.get("last_cycle_completed_at"),
        control_state.get("last_sleep_wake_recovery_at"),
    ]
    datetimes = [iso_to_datetime(value) for value in candidates if value]
    datetimes = [dt for dt in datetimes if dt is not None]
    if not datetimes:
        return None
    return max(datetimes)


_PMSET_WAKE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} [+-]\d{4})\s+Wake\b")


def latest_pmset_wake_after(since: datetime | None) -> dict[str, Any] | None:
    result = subprocess.run(
        ["pmset", "-g", "log"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None

    for raw_line in reversed(result.stdout.splitlines()):
        line = raw_line.strip()
        match = _PMSET_WAKE_RE.match(line)
        if not match:
            continue
        try:
            wake_at = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S %z")
        except ValueError:
            continue
        if since and wake_at <= since:
            return None
        return {
            "event_at": wake_at.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "source": "pmset_log",
            "raw_line": line,
        }
    return None


def detect_sleep_wake_interruption(
    control_state: dict[str, Any],
    fallback_gap_hours: int = 1,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    anchor = latest_build_activity_at(control_state)
    detection: dict[str, Any] = {
        "interrupted": False,
        "method": None,
        "event_at": None,
        "fallback_gap_hours": fallback_gap_hours,
        "anchor_at": anchor.replace(microsecond=0).isoformat().replace("+00:00", "Z") if anchor else None,
    }

    pmset_detection = latest_pmset_wake_after(anchor)
    if pmset_detection:
        detection["interrupted"] = True
        detection["method"] = pmset_detection["source"]
        detection["event_at"] = pmset_detection["event_at"]
        detection["raw_line"] = pmset_detection["raw_line"]
        return detection

    if anchor and now - anchor > timedelta(hours=fallback_gap_hours):
        detection["interrupted"] = True
        detection["method"] = "gap_fallback"
        detection["event_at"] = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        detection["gap_seconds"] = int((now - anchor).total_seconds())

    return detection
