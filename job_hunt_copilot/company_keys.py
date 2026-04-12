from __future__ import annotations

import sqlite3
from typing import Any, Mapping

from .paths import workspace_slug


PROVISIONAL_COMPANY_KEY_SOURCE = "normalized_company_name"


def build_provisional_company_key(company_name: str | None) -> str:
    return f"name:{workspace_slug((company_name or '').strip() or 'unknown-company')}"


def build_provider_company_key(provider_name: str, provider_company_id: str) -> str:
    normalized_provider = workspace_slug(provider_name.strip() or "provider")
    normalized_id = provider_company_id.strip()
    if not normalized_id:
        raise ValueError("provider_company_id must be non-empty.")
    return f"{normalized_provider}:{normalized_id}"


def derive_company_key_values(
    company_name: str | None,
    *,
    provider_name: str | None = None,
    provider_company_id: str | None = None,
) -> tuple[str, str | None, str]:
    provisional_key = build_provisional_company_key(company_name)
    if provider_name and provider_company_id:
        provider_key = build_provider_company_key(provider_name, provider_company_id)
        return provider_key, provider_key, workspace_slug(provider_name)
    return provisional_key, None, PROVISIONAL_COMPANY_KEY_SOURCE


def posting_company_key_from_row(posting_row: Mapping[str, Any]) -> str:
    canonical_key = _normalize_optional_text(_mapping_lookup(posting_row, "canonical_company_key"))
    if canonical_key:
        return canonical_key
    return build_provisional_company_key(_normalize_optional_text(_mapping_lookup(posting_row, "company_name")))


def ensure_missing_posting_company_keys(
    connection: sqlite3.Connection,
    *,
    current_time: str,
) -> int:
    rows = connection.execute(
        """
        SELECT job_posting_id, company_name
        FROM job_postings
        WHERE canonical_company_key IS NULL
           OR TRIM(canonical_company_key) = ''
        """
    ).fetchall()
    updated = 0
    for row in rows:
        company_name = _normalize_optional_text(row["company_name"])
        canonical_key, _, source = derive_company_key_values(company_name)
        connection.execute(
            """
            UPDATE job_postings
            SET canonical_company_key = ?,
                company_key_source = COALESCE(NULLIF(TRIM(company_key_source), ''), ?),
                updated_at = COALESCE(updated_at, ?)
            WHERE job_posting_id = ?
            """,
            (
                canonical_key,
                source,
                current_time,
                str(row["job_posting_id"]),
            ),
        )
        updated += 1
    return updated


def promote_company_group_to_provider_key(
    connection: sqlite3.Connection,
    *,
    company_name: str | None,
    provider_name: str,
    provider_company_id: str,
    current_time: str,
) -> int:
    provisional_key = build_provisional_company_key(company_name)
    provider_key = build_provider_company_key(provider_name, provider_company_id)
    provider_source = workspace_slug(provider_name)
    normalized_company_slug = workspace_slug((company_name or "").strip() or "unknown-company")

    rows = connection.execute(
        """
        SELECT job_posting_id, company_name, canonical_company_key
        FROM job_postings
        """
    ).fetchall()

    updated = 0
    for row in rows:
        existing_key = _normalize_optional_text(row["canonical_company_key"])
        row_company_slug = workspace_slug(_normalize_optional_text(row["company_name"]) or "unknown-company")
        if existing_key == provider_key:
            continue
        if existing_key == provisional_key or row_company_slug == normalized_company_slug or existing_key is None:
            connection.execute(
                """
                UPDATE job_postings
                SET canonical_company_key = ?,
                    provider_company_key = ?,
                    company_key_source = ?,
                    updated_at = ?
                WHERE job_posting_id = ?
                """,
                (
                    provider_key,
                    provider_key,
                    provider_source,
                    current_time,
                    str(row["job_posting_id"]),
                ),
            )
            updated += 1
    return updated


def _normalize_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _mapping_lookup(mapping: Mapping[str, Any], key: str) -> Any:
    if hasattr(mapping, "keys"):
        try:
            return mapping[key]
        except Exception:
            return None
    getter = getattr(mapping, "get", None)
    if callable(getter):
        return getter(key)
    return None
