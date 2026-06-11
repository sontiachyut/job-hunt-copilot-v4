from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .paths import ProjectPaths
from .records import new_canonical_id, now_utc_iso

TOKEN_USAGE_RE = re.compile(r"tokens used\s*[\r\n]+\s*([0-9,\s]+)", re.IGNORECASE)
MODEL_RE = re.compile(r"^model:\s*(.+?)\s*$", re.MULTILINE)
PROVIDER_RE = re.compile(r"^provider:\s*(.+?)\s*$", re.MULTILINE)
SESSION_ID_RE = re.compile(r"^session id:\s*(.+?)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class ParsedCodexUsage:
    provider_name: str | None
    model_name: str | None
    session_id: str | None
    total_tokens: int | None
    usage_parse_status: str
    raw_usage_text: str | None


def parse_codex_usage(stderr_text: str) -> ParsedCodexUsage:
    provider_match = PROVIDER_RE.search(stderr_text)
    model_match = MODEL_RE.search(stderr_text)
    session_match = SESSION_ID_RE.search(stderr_text)
    tokens_match = TOKEN_USAGE_RE.search(stderr_text)
    raw_usage_text = tokens_match.group(1).strip() if tokens_match else None
    digits_only = re.sub(r"\D", "", raw_usage_text or "")
    total_tokens = int(digits_only) if digits_only else None
    return ParsedCodexUsage(
        provider_name=provider_match.group(1).strip() if provider_match else None,
        model_name=model_match.group(1).strip() if model_match else None,
        session_id=session_match.group(1).strip() if session_match else None,
        total_tokens=total_tokens,
        usage_parse_status="reported" if total_tokens is not None else "missing",
        raw_usage_text=raw_usage_text,
    )


def record_codex_usage_event(
    paths: ProjectPaths,
    *,
    component_name: str,
    operation_name: str,
    invocation_status: str,
    exit_code: int,
    stderr_text: str,
    run_directory_path: Path,
    prompt_artifact_path: Path | None,
    output_artifact_path: Path | None,
    stdout_artifact_path: Path | None,
    stderr_artifact_path: Path,
    lead_id: str | None = None,
    job_posting_id: str | None = None,
    contact_id: str | None = None,
    outreach_message_id: str | None = None,
    created_at: str | None = None,
) -> str:
    parsed = parse_codex_usage(stderr_text)
    timestamp = created_at or now_utc_iso()
    connection = sqlite3.connect(paths.db_path)
    connection.execute("PRAGMA foreign_keys = ON;")
    try:
        usage_event_id = new_canonical_id("llm_usage_events")
        with connection:
            connection.execute(
                """
                INSERT INTO llm_usage_events (
                  llm_usage_event_id, provider_name, model_name, session_id,
                  component_name, operation_name, invocation_status, exit_code,
                  total_tokens, usage_parse_status, raw_usage_text, run_directory_path,
                  prompt_artifact_path, output_artifact_path, stdout_artifact_path, stderr_artifact_path,
                  lead_id, job_posting_id, contact_id, outreach_message_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    usage_event_id,
                    parsed.provider_name,
                    parsed.model_name,
                    parsed.session_id,
                    component_name,
                    operation_name,
                    invocation_status,
                    exit_code,
                    parsed.total_tokens,
                    parsed.usage_parse_status,
                    parsed.raw_usage_text,
                    paths.relative_to_root(run_directory_path).as_posix(),
                    paths.relative_to_root(prompt_artifact_path).as_posix() if prompt_artifact_path else None,
                    paths.relative_to_root(output_artifact_path).as_posix() if output_artifact_path and output_artifact_path.exists() else None,
                    paths.relative_to_root(stdout_artifact_path).as_posix() if stdout_artifact_path else None,
                    paths.relative_to_root(stderr_artifact_path).as_posix(),
                    lead_id,
                    job_posting_id,
                    contact_id,
                    outreach_message_id,
                    timestamp,
                ),
            )
        return usage_event_id
    finally:
        connection.close()
