#!/usr/bin/env python3

from __future__ import annotations

import csv
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCAL_SOURCE = ROOT / "ops" / "local-companies" / "greater-phoenix-software-100.csv"
WATCHLIST_DIR = ROOT / "ops" / "company-watchlists"
MASTER_WATCHLIST = WATCHLIST_DIR / "company-watchlist.csv"
LOCAL_VIEW = WATCHLIST_DIR / "local-watchlist.csv"
YC_VIEW = WATCHLIST_DIR / "yc-watchlist.csv"
README_PATH = WATCHLIST_DIR / "README.md"
YC_CONFIRMED_LIVE_SOURCE = WATCHLIST_DIR / "yc-api-native-board-confirmation.csv"
YC_RECHECK_TRUTH_SOURCE = WATCHLIST_DIR / "yc-us-hiring-recheck-truth.csv"
YC_MANUAL_SOURCE_AUDIT = WATCHLIST_DIR / "yc-manual-job-sources.csv"

FIELDNAMES = [
    "company_key",
    "company_name",
    "segment_primary",
    "segment_tags",
    "source_lists",
    "local_source_rank",
    "yc_source_rank",
    "city",
    "state_or_region",
    "metro_area",
    "company_category",
    "employee_band",
    "hq_status",
    "company_website",
    "careers_page",
    "company_linkedin",
    "source_systems",
    "check_daily",
    "priority_tier",
    "board_type",
    "board_url",
    "board_token",
    "board_api_url",
    "board_confirmation_status",
    "board_last_verified_at",
    "resolved_from_url",
    "listing_source_type",
    "listing_source_url",
    "listing_source_job_count",
    "listing_source_last_verified_at",
    "listing_authority",
    "listing_source_notes",
    "job_source_type",
    "job_source_url",
    "job_source_job_count",
    "job_source_last_verified_at",
    "job_source_notes",
    "jd_capture_status",
    "jd_format",
    "jd_extraction_method",
    "jd_extraction_locator",
    "jd_last_verified_at",
    "jd_notes",
    "notes",
]

MULTI_VALUE_FIELDS = {"segment_tags", "source_lists", "source_systems"}
CLEAR_SENTINEL = "__CLEAR__"


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return slug or "company"


def normalize_multivalue(value: str) -> str:
    seen: list[str] = []
    for part in (piece.strip() for piece in value.split(";")):
        if part and part not in seen:
            seen.append(part)
    return ";".join(seen)


def merge_multivalue(first: str, second: str) -> str:
    return normalize_multivalue(";".join(part for part in [first, second] if part))


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(reader)


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def load_local_source_rows() -> list[dict[str, str]]:
    return read_csv_rows(LOCAL_SOURCE)


def load_confirmed_yc_rows() -> list[dict[str, str]]:
    rows = read_csv_rows(YC_CONFIRMED_LIVE_SOURCE)
    live_rows = [row for row in rows if row.get("confirmation_status") == "live_jobs"]
    return sorted(live_rows, key=lambda row: row["company_name"].casefold())


def load_recheck_truth_rows() -> list[dict[str, str]]:
    rows = read_csv_rows(YC_RECHECK_TRUTH_SOURCE)
    useful_rows = [
        row
        for row in rows
        if row.get("recheck_confirmation_status") in {"live_jobs", "detected_structured_board"}
    ]
    return sorted(useful_rows, key=lambda row: row["company_name"].casefold())


def load_manual_source_audit_rows() -> list[dict[str, str]]:
    return sorted(
        read_csv_rows(YC_MANUAL_SOURCE_AUDIT),
        key=lambda row: row["company_name"].casefold(),
    )


def jd_fields_for_board_type(board_type: str) -> dict[str, str]:
    mapping = {
        "greenhouse": {
            "jd_capture_status": "full_jd_inferred_api",
            "jd_format": "html",
            "jd_extraction_method": "api_field",
            "jd_extraction_locator": "jobs[].content",
        },
        "ashby": {
            "jd_capture_status": "full_jd_inferred_api",
            "jd_format": "html_or_text",
            "jd_extraction_method": "api_field",
            "jd_extraction_locator": "jobs[].descriptionHtml|jobs[].descriptionPlain",
        },
        "lever": {
            "jd_capture_status": "full_jd_inferred_api",
            "jd_format": "html_or_text",
            "jd_extraction_method": "api_field",
            "jd_extraction_locator": "[].description|[].descriptionPlain",
        },
        "dover": {
            "jd_capture_status": "full_jd_inferred_api",
            "jd_format": "html",
            "jd_extraction_method": "api_field",
            "jd_extraction_locator": "jobs[].content",
        },
        "workable": {
            "jd_capture_status": "full_jd_inferred_api",
            "jd_format": "markdown_detail_page",
            "jd_extraction_method": "workable_jobs_api_to_markdown_detail",
            "jd_extraction_locator": "results[].shortcode -> /jobs/view/<shortcode>.md",
        },
    }
    return mapping.get(
        board_type,
        {
            "jd_capture_status": "",
            "jd_format": "",
            "jd_extraction_method": "",
            "jd_extraction_locator": "",
        },
    )


def build_source_row_from_local(local_row: dict[str, str]) -> dict[str, str]:
    segment_tags = "local"
    source_lists = "greater_phoenix"
    source_systems = "phx_fwd_local_software_100"

    if "ycombinator.com/companies" in local_row["careers_page"]:
        segment_tags = merge_multivalue(segment_tags, "yc")
        source_lists = merge_multivalue(source_lists, "yc_seed_from_local_overlap")
        source_systems = merge_multivalue(source_systems, "local_yc_overlap")

    return {
        "company_key": slugify(local_row["company_name"]),
        "company_name": local_row["company_name"],
        "segment_primary": "local",
        "segment_tags": segment_tags,
        "source_lists": source_lists,
        "local_source_rank": local_row["rank"],
        "yc_source_rank": "",
        "city": local_row["city"],
        "state_or_region": "AZ",
        "metro_area": "Greater Phoenix",
        "company_category": local_row["category"],
        "employee_band": local_row["number_of_employees"],
        "hq_status": local_row["remote_hq"],
        "company_website": local_row["company_website"],
        "careers_page": local_row["careers_page"],
        "company_linkedin": local_row["company_linkedin"],
        "source_systems": source_systems,
        "check_daily": "true",
        "priority_tier": "",
        "board_type": "",
        "board_url": "",
        "board_token": "",
        "board_api_url": "",
        "board_confirmation_status": "",
        "board_last_verified_at": "",
        "resolved_from_url": "",
        "listing_source_type": "",
        "listing_source_url": "",
        "listing_source_job_count": "",
        "listing_source_last_verified_at": "",
        "listing_authority": "",
        "listing_source_notes": "",
        "job_source_type": "",
        "job_source_url": "",
        "job_source_job_count": "",
        "job_source_last_verified_at": "",
        "job_source_notes": "",
        "jd_capture_status": "",
        "jd_format": "",
        "jd_extraction_method": "",
        "jd_extraction_locator": "",
        "jd_last_verified_at": "",
        "jd_notes": "",
        "notes": "",
    }


def build_source_row_from_confirmed_yc(
    yc_row: dict[str, str],
    yc_rank: int,
) -> dict[str, str]:
    jd_fields = jd_fields_for_board_type(yc_row["detected_board_type"])
    return {
        "company_key": slugify(yc_row["company_slug"] or yc_row["company_name"]),
        "company_name": yc_row["company_name"],
        "segment_primary": "yc",
        "segment_tags": "yc",
        "source_lists": "yc_us_hiring_confirmed_api_native_live",
        "local_source_rank": "",
        "yc_source_rank": str(yc_rank),
        "city": "",
        "state_or_region": "",
        "metro_area": "",
        "company_category": "",
        "employee_band": "",
        "hq_status": "",
        "company_website": yc_row["website"],
        "careers_page": yc_row["selected_url"] or yc_row["board_url"],
        "company_linkedin": "",
        "source_systems": "yc_public_directory;yc_api_native_board_confirmation",
        "check_daily": "true",
        "priority_tier": "",
        "board_type": yc_row["detected_board_type"],
        "board_url": yc_row["board_url"],
        "board_token": yc_row["board_token"],
        "board_api_url": yc_row["api_url"],
        "board_confirmation_status": yc_row["confirmation_status"],
        "board_last_verified_at": "",
        "resolved_from_url": yc_row["selected_url"],
        "listing_source_type": "api_native",
        "listing_source_url": yc_row["api_url"] or yc_row["board_url"],
        "listing_source_job_count": yc_row["job_count"],
        "listing_source_last_verified_at": "",
        "listing_authority": "api_primary",
        "listing_source_notes": "Public ATS/API feed is the authoritative live listing source.",
        "job_source_type": "api_native",
        "job_source_url": yc_row["api_url"] or yc_row["board_url"],
        "job_source_job_count": yc_row["job_count"],
        "job_source_last_verified_at": "",
        "job_source_notes": "",
        "jd_capture_status": jd_fields["jd_capture_status"],
        "jd_format": jd_fields["jd_format"],
        "jd_extraction_method": jd_fields["jd_extraction_method"],
        "jd_extraction_locator": jd_fields["jd_extraction_locator"],
        "jd_last_verified_at": "",
        "jd_notes": "",
        "notes": "",
    }


def build_source_row_from_recheck_truth(recheck_row: dict[str, str]) -> dict[str, str]:
    job_source_type = ""
    job_source_url = ""
    job_source_job_count = ""
    listing_source_type = ""
    listing_source_url = ""
    listing_source_job_count = ""
    listing_authority = ""
    listing_source_notes = ""
    if recheck_row["recheck_confirmation_status"] == "live_jobs":
        job_source_type = "api_native"
        job_source_url = recheck_row["recheck_api_url"] or recheck_row["recheck_board_url"]
        job_source_job_count = recheck_row["recheck_job_count"]
        listing_source_type = "api_native"
        listing_source_url = job_source_url
        listing_source_job_count = job_source_job_count
        listing_authority = "api_primary"
        listing_source_notes = "Public ATS/API feed is the authoritative live listing source."
    elif recheck_row["recheck_confirmation_status"] == "detected_structured_board":
        job_source_type = "structured_board"
        job_source_url = recheck_row["recheck_board_url"]

    jd_fields = (
        jd_fields_for_board_type(recheck_row["recheck_board_type"])
        if recheck_row["recheck_confirmation_status"] == "live_jobs"
        else {
            "jd_capture_status": "",
            "jd_format": "",
            "jd_extraction_method": "",
            "jd_extraction_locator": "",
        }
    )

    return {
        "company_key": slugify(recheck_row["company_slug"] or recheck_row["company_name"]),
        "company_name": recheck_row["company_name"],
        "segment_primary": "yc",
        "segment_tags": "yc",
        "source_lists": "yc_us_hiring_recheck_truth",
        "local_source_rank": "",
        "yc_source_rank": "",
        "city": "",
        "state_or_region": "",
        "metro_area": "",
        "company_category": "",
        "employee_band": "",
        "hq_status": "",
        "company_website": recheck_row["website"],
        "careers_page": recheck_row["resolved_from_url"] or recheck_row["previous_selected_url"],
        "company_linkedin": "",
        "source_systems": "yc_public_directory;yc_deep_recheck_truth",
        "check_daily": "true",
        "priority_tier": "",
        "board_type": recheck_row["recheck_board_type"],
        "board_url": recheck_row["recheck_board_url"],
        "board_token": recheck_row["recheck_board_token"],
        "board_api_url": recheck_row["recheck_api_url"],
        "board_confirmation_status": recheck_row["recheck_confirmation_status"],
        "board_last_verified_at": recheck_row["checked_at_utc"],
        "resolved_from_url": recheck_row["resolved_from_url"],
        "listing_source_type": listing_source_type,
        "listing_source_url": listing_source_url,
        "listing_source_job_count": listing_source_job_count,
        "listing_source_last_verified_at": recheck_row["checked_at_utc"] if listing_source_type else "",
        "listing_authority": listing_authority,
        "listing_source_notes": listing_source_notes,
        "job_source_type": job_source_type,
        "job_source_url": job_source_url,
        "job_source_job_count": job_source_job_count,
        "job_source_last_verified_at": recheck_row["checked_at_utc"],
        "job_source_notes": "",
        "jd_capture_status": jd_fields["jd_capture_status"],
        "jd_format": jd_fields["jd_format"],
        "jd_extraction_method": jd_fields["jd_extraction_method"],
        "jd_extraction_locator": jd_fields["jd_extraction_locator"],
        "jd_last_verified_at": recheck_row["checked_at_utc"] if jd_fields["jd_capture_status"] else "",
        "jd_notes": "",
        "notes": "",
    }


def build_source_row_from_manual_source_audit(manual_row: dict[str, str]) -> dict[str, str]:
    board_type = manual_row.get("board_type", "")
    board_url = manual_row.get("board_url", "")
    board_token = manual_row.get("board_token", "")
    board_api_url = manual_row.get("board_api_url", "")
    board_confirmation_status = manual_row.get("board_confirmation_status", "")
    if not board_type:
        board_type = CLEAR_SENTINEL
        board_url = CLEAR_SENTINEL
        board_token = CLEAR_SENTINEL
        board_api_url = CLEAR_SENTINEL
        board_confirmation_status = CLEAR_SENTINEL

    listing_source_type = manual_row.get("listing_source_type", "")
    listing_source_url = manual_row.get("listing_source_url", "")
    listing_source_job_count = manual_row.get("listing_source_job_count", "")
    listing_source_last_verified_at = manual_row.get("listing_source_last_verified_at", "")
    listing_authority = manual_row.get("listing_authority", "")
    listing_source_notes = manual_row.get("listing_source_notes", "")

    if not listing_source_type:
        if manual_row["job_source_type"] == "api_native":
            listing_source_type = "api_native"
            listing_source_url = manual_row["job_source_url"]
            listing_source_job_count = manual_row["job_source_job_count"]
            listing_source_last_verified_at = manual_row["job_source_last_verified_at"]
            listing_authority = "api_primary"
            listing_source_notes = "Public ATS/API feed is the authoritative live listing source."
        elif manual_row["job_source_type"] == "company_careers_page":
            listing_source_type = "company_careers_page"
            listing_source_url = manual_row["job_source_url"]
            listing_source_job_count = manual_row["job_source_job_count"]
            listing_source_last_verified_at = manual_row["job_source_last_verified_at"]
            listing_authority = "company_primary"
            listing_source_notes = "First-party careers page is the authoritative live listing source."
        elif manual_row["job_source_type"] == "yc_jobs_page":
            listing_source_type = "yc_jobs_page"
            listing_source_url = manual_row["job_source_url"]
            listing_source_job_count = manual_row["job_source_job_count"]
            listing_source_last_verified_at = manual_row["job_source_last_verified_at"]
            listing_authority = "yc_primary"
            listing_source_notes = "YC appears to be the authoritative public listing surface from current evidence."

    return {
        "company_key": slugify(manual_row["company_slug"] or manual_row["company_name"]),
        "company_name": manual_row["company_name"],
        "segment_primary": "yc",
        "segment_tags": "yc",
        "source_lists": "yc_manual_job_source_audit",
        "local_source_rank": "",
        "yc_source_rank": "",
        "city": "",
        "state_or_region": "",
        "metro_area": "",
        "company_category": "",
        "employee_band": "",
        "hq_status": "",
        "company_website": manual_row["website"],
        "careers_page": manual_row["careers_page"] or manual_row["job_source_url"],
        "company_linkedin": "",
        "source_systems": "yc_public_directory;yc_manual_source_audit",
        "check_daily": "true",
        "priority_tier": "",
        "board_type": board_type,
        "board_url": board_url,
        "board_token": board_token,
        "board_api_url": board_api_url,
        "board_confirmation_status": board_confirmation_status,
        "board_last_verified_at": manual_row["job_source_last_verified_at"],
        "resolved_from_url": manual_row.get("resolved_from_url", manual_row["job_source_url"]),
        "listing_source_type": listing_source_type,
        "listing_source_url": listing_source_url,
        "listing_source_job_count": listing_source_job_count,
        "listing_source_last_verified_at": listing_source_last_verified_at,
        "listing_authority": listing_authority,
        "listing_source_notes": listing_source_notes,
        "job_source_type": manual_row["job_source_type"],
        "job_source_url": manual_row["job_source_url"],
        "job_source_job_count": manual_row["job_source_job_count"],
        "job_source_last_verified_at": manual_row["job_source_last_verified_at"],
        "job_source_notes": manual_row["job_source_notes"],
        "jd_capture_status": manual_row.get("jd_capture_status", ""),
        "jd_format": manual_row.get("jd_format", ""),
        "jd_extraction_method": manual_row.get("jd_extraction_method", ""),
        "jd_extraction_locator": manual_row.get("jd_extraction_locator", ""),
        "jd_last_verified_at": manual_row.get("jd_last_verified_at", ""),
        "jd_notes": manual_row.get("jd_notes", ""),
        "notes": "",
    }


def merge_source_rows(source_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    merged_by_key: dict[str, dict[str, str]] = {}
    for source_row in source_rows:
        company_key = source_row["company_key"]
        existing_row = merged_by_key.get(company_key)
        if existing_row:
            merged_by_key[company_key] = merge_rows(source_row, existing_row, preserve_clear_sentinel=True)
        else:
            merged_by_key[company_key] = source_row
    return list(merged_by_key.values())


def build_source_rows() -> list[dict[str, str]]:
    source_rows = [build_source_row_from_local(row) for row in load_local_source_rows()]
    confirmed_yc_rows = load_confirmed_yc_rows()
    for index, yc_row in enumerate(confirmed_yc_rows, start=1):
        source_rows.append(build_source_row_from_confirmed_yc(yc_row, index))
    for recheck_row in load_recheck_truth_rows():
        source_rows.append(build_source_row_from_recheck_truth(recheck_row))
    for manual_row in load_manual_source_audit_rows():
        source_rows.append(build_source_row_from_manual_source_audit(manual_row))
    return merge_source_rows(source_rows)


def index_rows(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {row["company_key"]: row for row in rows}


def merge_rows(
    source_row: dict[str, str],
    existing_row: dict[str, str],
    preserve_clear_sentinel: bool = False,
) -> dict[str, str]:
    merged: dict[str, str] = {}
    for field in FIELDNAMES:
        source_value = source_row.get(field, "")
        existing_value = existing_row.get(field, "")

        if field in MULTI_VALUE_FIELDS:
            merged[field] = merge_multivalue(source_value, existing_value)
            continue

        if source_value == CLEAR_SENTINEL:
            merged[field] = CLEAR_SENTINEL if preserve_clear_sentinel else ""
            continue

        if source_value:
            merged[field] = source_value
        else:
            merged[field] = existing_value

    if source_row.get("segment_primary") == "local" or existing_row.get("segment_primary") == "local":
        merged["segment_primary"] = "local"
    elif existing_row.get("segment_primary"):
        merged["segment_primary"] = existing_row["segment_primary"]

    return merged


def rank_sort_value(value: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 999999


def segment_sort_value(value: str) -> int:
    order = {
        "local": 0,
        "yc": 1,
    }
    return order.get(value, 99)


def build_master_rows() -> list[dict[str, str]]:
    source_rows = build_source_rows()
    existing_rows = read_csv_rows(MASTER_WATCHLIST)
    existing_by_key = index_rows(existing_rows)

    merged_rows: list[dict[str, str]] = []
    seen_keys: set[str] = set()

    for source_row in source_rows:
        company_key = source_row["company_key"]
        seen_keys.add(company_key)
        existing_row = existing_by_key.get(company_key)
        if existing_row:
            merged_rows.append(merge_rows(source_row, existing_row))
        else:
            merged_rows.append(source_row)

    for existing_row in existing_rows:
        if existing_row["company_key"] not in seen_keys:
            merged_rows.append(existing_row)

    return sorted(
        merged_rows,
        key=lambda row: (
            segment_sort_value(row["segment_primary"]),
            rank_sort_value(row["local_source_rank"] or row["yc_source_rank"]),
            row["company_name"].casefold(),
        ),
    )


def derive_view_rows(master_rows: list[dict[str, str]], tag: str) -> list[dict[str, str]]:
    view_rows: list[dict[str, str]] = []
    for row in master_rows:
        tags = {part.strip() for part in row["segment_tags"].split(";") if part.strip()}
        if tag in tags:
            view_rows.append(row)
    return view_rows


def write_readme(master_count: int, local_count: int, yc_count: int) -> None:
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    lines = [
        "# Company Watchlists",
        "",
        f"Generated at: `{generated_at}`",
        "",
        "`company-watchlist.csv` is the source of truth for the daily job crawler.",
        "",
        "Current files:",
        f"- `company-watchlist.csv`: {master_count} total companies",
        f"- `local-watchlist.csv`: {local_count} derived local-view rows",
        f"- `yc-watchlist.csv`: {yc_count} derived YC-view rows",
        "",
        "Recommended workflow:",
        "1. Edit `company-watchlist.csv` directly.",
        "2. Use `segment_tags` to classify companies, for example `local`, `yc`, or `local;yc`.",
        "3. Fill `board_type` and `board_url` as ATS metadata becomes known.",
        "4. Run `python3 scripts/ops/fetch_watchlist_jobs.py` to fetch jobs from supported authoritative API-native listing sources.",
        "",
        "Important columns:",
        "- `segment_primary`: the main bucket for sorting and prioritization",
        "- `segment_tags`: semicolon-separated category tags",
        "- `source_lists`: where the company entered the watchlist",
        "- `check_daily`: whether the crawler should include the company every day",
        "- `priority_tier`: your manual ranking layer",
        "- `board_type` / `board_url`: ATS routing metadata for deterministic fetches",
        "- `board_token` / `board_api_url`: resolved ATS identifiers when known",
        "- `board_confirmation_status` / `board_last_verified_at`: latest verification state",
        "- `resolved_from_url`: the page where the board was actually discovered",
        "- `listing_source_type` / `listing_source_url`: the source we trust for live open-role freshness",
        "- `listing_authority`: freshness confidence label such as `api_primary`, `company_primary`, `yc_primary`, or `yc_fallback`",
        "- `fetch_watchlist_jobs.py` currently uses `listing_authority` and `listing_source_type` to fetch only authoritative API-native boards; `yc_primary` and `company_primary` rows stay in the registry but require separate fetchers",
        "- `job_source_type` / `job_source_url`: the deterministic extraction source we should crawl for role data and JD",
        "- `job_source_job_count` / `job_source_last_verified_at`: current observed source state",
        "- `jd_capture_status` / `jd_format`: JD readiness label such as `full_jd_verified`, `full_jd_inferred_api`, or `unconfirmed`",
        "- `jd_extraction_method` / `jd_extraction_locator`: how the deterministic JD fetcher should pull content, for example `same_page_html_sections`, `company_jobs_list_to_detail_pages`, or `yc_jobs_list_to_detail_pages`",
        "- `jd_last_verified_at` / `jd_notes`: latest JD-source validation notes",
        "",
        "Seed sources for the current watchlist:",
        "- `ops/local-companies/greater-phoenix-software-100.csv`",
        "- `ops/company-watchlists/yc-api-native-board-confirmation.csv` (`confirmation_status = live_jobs` rows)",
        "- `ops/company-watchlists/yc-us-hiring-recheck-truth.csv` (`live_jobs` and `detected_structured_board` rows)",
        "- `ops/company-watchlists/yc-manual-job-sources.csv` (manual source decisions like `company_careers_page` or `yc_jobs_page`)",
    ]
    README_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    WATCHLIST_DIR.mkdir(parents=True, exist_ok=True)

    master_rows = build_master_rows()
    local_rows = derive_view_rows(master_rows, "local")
    yc_rows = derive_view_rows(master_rows, "yc")

    write_csv(MASTER_WATCHLIST, master_rows)
    write_csv(LOCAL_VIEW, local_rows)
    write_csv(YC_VIEW, yc_rows)
    write_readme(master_count=len(master_rows), local_count=len(local_rows), yc_count=len(yc_rows))

    print(f"Wrote {len(master_rows)} rows to {MASTER_WATCHLIST}")
    print(f"Wrote {len(local_rows)} rows to {LOCAL_VIEW}")
    print(f"Wrote {len(yc_rows)} rows to {YC_VIEW}")
    print(f"Wrote summary to {README_PATH}")


if __name__ == "__main__":
    main()
