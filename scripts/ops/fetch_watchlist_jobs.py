#!/usr/bin/env python3

from __future__ import annotations

import csv
import json
import re
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[2]
WATCHLIST_CSV = ROOT / "ops" / "company-watchlists" / "company-watchlist.csv"
RUNS_DIR = ROOT / "ops" / "company-watchlists" / "daily-fetches"

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

SUPPORTED_BOARD_TYPES = {"ashby", "dover", "greenhouse", "lever", "workable"}

GREENHOUSE_RE = re.compile(r"(?:job-boards|boards)\.greenhouse\.io/([A-Za-z0-9_-]+)", re.I)
ASHBY_RE = re.compile(r"(?:jobs\.ashbyhq\.com|api\.ashbyhq\.com/posting-api/job-board)/([A-Za-z0-9._%-]+)", re.I)
LEVER_RE = re.compile(r"jobs\.lever\.co/([A-Za-z0-9._-]+)", re.I)
WORKABLE_RE = re.compile(r"apply\.workable\.com/([A-Za-z0-9._-]+)", re.I)
DOVER_RE = re.compile(r"app\.dover\.com/jobs/([A-Za-z0-9._%-]+)", re.I)
DOVER_API_RE = re.compile(r"app\.dover\.com/feed/v1/boards/([A-Za-z0-9._%-]+)/jobs", re.I)

JOB_FIELDNAMES = [
    "run_id",
    "fetched_at_utc",
    "company_key",
    "company_name",
    "segment_primary",
    "segment_tags",
    "priority_tier",
    "company_website",
    "careers_page",
    "board_type",
    "board_url",
    "source_api_url",
    "source_job_id",
    "title",
    "location",
    "department",
    "team",
    "employment_type",
    "workplace_type",
    "is_remote",
    "posted_at",
    "updated_at",
    "job_url",
    "apply_url",
]

COMPANY_RESULT_FIELDNAMES = [
    "run_id",
    "fetched_at_utc",
    "company_key",
    "company_name",
    "segment_primary",
    "board_type",
    "board_url",
    "source_api_url",
    "fetch_status",
    "job_count",
    "endpoint_http_status",
    "notes",
]

_session_local = threading.local()


def session() -> requests.Session:
    sess = getattr(_session_local, "session", None)
    if sess is None:
        sess = requests.Session()
        sess.headers.update(REQUEST_HEADERS)
        _session_local.session = sess
    return sess


def bool_string(value: bool) -> str:
    return "true" if value else "false"


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def parse_check_daily(value: str) -> bool:
    return value.strip().casefold() in {"1", "true", "yes", "y"}


def normalize_location_parts(parts: list[str]) -> str:
    cleaned = [part.strip() for part in parts if part and part.strip()]
    seen: list[str] = []
    for part in cleaned:
        if part not in seen:
            seen.append(part)
    return ", ".join(seen)


def iso_from_epoch_ms(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return ""
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()


def normalize_department_list(items: list[dict[str, Any]]) -> str:
    return ";".join(item.get("name", "").strip() for item in items if item.get("name"))


def normalize_mixed_department(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        names: list[str] = []
        for item in value:
            if isinstance(item, dict):
                name = item.get("name") or item.get("title") or ""
                if name:
                    names.append(str(name).strip())
            elif item:
                names.append(str(item).strip())
        return ";".join(name for name in names if name)
    return ""


def match_first(pattern: re.Pattern[str], value: str) -> str:
    match = pattern.search(value)
    return match.group(1) if match else ""


def configured_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for row in rows:
        if not parse_check_daily(row.get("check_daily", "")):
            continue
        if row.get("board_type") not in SUPPORTED_BOARD_TYPES:
            continue
        if not row.get("board_url"):
            continue
        result.append(row)
    return result


def company_result(
    row: dict[str, str],
    *,
    run_id: str,
    fetched_at_utc: str,
    source_api_url: str = "",
    fetch_status: str,
    job_count: int = 0,
    endpoint_http_status: str = "",
    notes: str = "",
) -> dict[str, str]:
    return {
        "run_id": run_id,
        "fetched_at_utc": fetched_at_utc,
        "company_key": row["company_key"],
        "company_name": row["company_name"],
        "segment_primary": row["segment_primary"],
        "board_type": row["board_type"],
        "board_url": row["board_url"],
        "source_api_url": source_api_url,
        "fetch_status": fetch_status,
        "job_count": str(job_count),
        "endpoint_http_status": endpoint_http_status,
        "notes": notes,
    }


def job_row(
    row: dict[str, str],
    *,
    run_id: str,
    fetched_at_utc: str,
    source_api_url: str,
    source_job_id: str,
    title: str,
    location: str = "",
    department: str = "",
    team: str = "",
    employment_type: str = "",
    workplace_type: str = "",
    is_remote: str = "",
    posted_at: str = "",
    updated_at: str = "",
    job_url: str = "",
    apply_url: str = "",
) -> dict[str, str]:
    return {
        "run_id": run_id,
        "fetched_at_utc": fetched_at_utc,
        "company_key": row["company_key"],
        "company_name": row["company_name"],
        "segment_primary": row["segment_primary"],
        "segment_tags": row["segment_tags"],
        "priority_tier": row["priority_tier"],
        "company_website": row["company_website"],
        "careers_page": row["careers_page"],
        "board_type": row["board_type"],
        "board_url": row["board_url"],
        "source_api_url": source_api_url,
        "source_job_id": source_job_id,
        "title": title,
        "location": location,
        "department": department,
        "team": team,
        "employment_type": employment_type,
        "workplace_type": workplace_type,
        "is_remote": is_remote,
        "posted_at": posted_at,
        "updated_at": updated_at,
        "job_url": job_url,
        "apply_url": apply_url,
    }


def fetch_greenhouse_jobs(row: dict[str, str], run_id: str, fetched_at_utc: str) -> tuple[dict[str, str], list[dict[str, str]]]:
    token = match_first(GREENHOUSE_RE, row["board_url"])
    if not token:
        return company_result(
            row,
            run_id=run_id,
            fetched_at_utc=fetched_at_utc,
            fetch_status="invalid_board_url",
            notes="unable_to_parse_greenhouse_token",
        ), []

    api_url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
    response = session().get(api_url, timeout=20)
    if response.status_code != 200:
        return company_result(
            row,
            run_id=run_id,
            fetched_at_utc=fetched_at_utc,
            source_api_url=api_url,
            fetch_status="endpoint_error",
            endpoint_http_status=str(response.status_code),
            notes=f"http_{response.status_code}",
        ), []

    payload = response.json()
    jobs = payload.get("jobs", [])
    normalized_jobs = [
        job_row(
            row,
            run_id=run_id,
            fetched_at_utc=fetched_at_utc,
            source_api_url=api_url,
            source_job_id=str(job.get("id", "")),
            title=job.get("title", ""),
            location=(job.get("location") or {}).get("name", ""),
            department=normalize_department_list(job.get("departments", [])),
            team="",
            employment_type="",
            workplace_type="",
            is_remote=bool_string("remote" in ((job.get("location") or {}).get("name", "").casefold())),
            posted_at=job.get("first_published", ""),
            updated_at=job.get("updated_at", ""),
            job_url=job.get("absolute_url", ""),
            apply_url=job.get("absolute_url", ""),
        )
        for job in jobs
    ]
    return company_result(
        row,
        run_id=run_id,
        fetched_at_utc=fetched_at_utc,
        source_api_url=api_url,
        fetch_status="live_jobs" if normalized_jobs else "zero_jobs",
        job_count=len(normalized_jobs),
        endpoint_http_status=str(response.status_code),
    ), normalized_jobs


def fetch_ashby_jobs(row: dict[str, str], run_id: str, fetched_at_utc: str) -> tuple[dict[str, str], list[dict[str, str]]]:
    org = match_first(ASHBY_RE, row["board_api_url"]) or match_first(ASHBY_RE, row["board_url"])
    if not org:
        return company_result(
            row,
            run_id=run_id,
            fetched_at_utc=fetched_at_utc,
            fetch_status="invalid_board_url",
            notes="unable_to_parse_ashby_org",
        ), []

    org = unquote(org)
    api_url = f"https://api.ashbyhq.com/posting-api/job-board/{org}?includeCompensation=true"
    response = session().get(api_url, timeout=20)
    if response.status_code != 200:
        return company_result(
            row,
            run_id=run_id,
            fetched_at_utc=fetched_at_utc,
            source_api_url=api_url,
            fetch_status="endpoint_error",
            endpoint_http_status=str(response.status_code),
            notes=f"http_{response.status_code}",
        ), []

    payload = response.json()
    jobs = payload.get("jobs", [])
    normalized_jobs = [
        job_row(
            row,
            run_id=run_id,
            fetched_at_utc=fetched_at_utc,
            source_api_url=api_url,
            source_job_id=job.get("id", ""),
            title=job.get("title", ""),
            location=job.get("location", ""),
            department=job.get("department", ""),
            team=job.get("team", ""),
            employment_type=job.get("employmentType", ""),
            workplace_type=job.get("workplaceType", ""),
            is_remote=bool_string(bool(job.get("isRemote"))),
            posted_at=job.get("publishedAt", ""),
            updated_at="",
            job_url=job.get("jobUrl", ""),
            apply_url=job.get("applyUrl", ""),
        )
        for job in jobs
        if job.get("isListed", True)
    ]
    return company_result(
        row,
        run_id=run_id,
        fetched_at_utc=fetched_at_utc,
        source_api_url=api_url,
        fetch_status="live_jobs" if normalized_jobs else "zero_jobs",
        job_count=len(normalized_jobs),
        endpoint_http_status=str(response.status_code),
    ), normalized_jobs


def fetch_lever_jobs(row: dict[str, str], run_id: str, fetched_at_utc: str) -> tuple[dict[str, str], list[dict[str, str]]]:
    account = match_first(LEVER_RE, row["board_url"])
    if not account:
        return company_result(
            row,
            run_id=run_id,
            fetched_at_utc=fetched_at_utc,
            fetch_status="invalid_board_url",
            notes="unable_to_parse_lever_account",
        ), []

    api_url = f"https://api.lever.co/v0/postings/{account}?mode=json"
    response = session().get(api_url, timeout=20)
    if response.status_code != 200:
        return company_result(
            row,
            run_id=run_id,
            fetched_at_utc=fetched_at_utc,
            source_api_url=api_url,
            fetch_status="endpoint_error",
            endpoint_http_status=str(response.status_code),
            notes=f"http_{response.status_code}",
        ), []

    payload = response.json()
    normalized_jobs = [
        job_row(
            row,
            run_id=run_id,
            fetched_at_utc=fetched_at_utc,
            source_api_url=api_url,
            source_job_id=job.get("id", ""),
            title=job.get("text", ""),
            location=(job.get("categories") or {}).get("location", ""),
            department="",
            team=(job.get("categories") or {}).get("team", ""),
            employment_type=(job.get("categories") or {}).get("commitment", ""),
            workplace_type=job.get("workplaceType", ""),
            is_remote=bool_string(job.get("workplaceType") == "remote"),
            posted_at=iso_from_epoch_ms(job.get("createdAt")),
            updated_at=iso_from_epoch_ms(job.get("updatedAt")),
            job_url=job.get("hostedUrl", ""),
            apply_url=job.get("applyUrl", ""),
        )
        for job in payload
    ]
    return company_result(
        row,
        run_id=run_id,
        fetched_at_utc=fetched_at_utc,
        source_api_url=api_url,
        fetch_status="live_jobs" if normalized_jobs else "zero_jobs",
        job_count=len(normalized_jobs),
        endpoint_http_status=str(response.status_code),
    ), normalized_jobs


def fetch_workable_jobs(row: dict[str, str], run_id: str, fetched_at_utc: str) -> tuple[dict[str, str], list[dict[str, str]]]:
    account = match_first(WORKABLE_RE, row["board_url"])
    if not account:
        return company_result(
            row,
            run_id=run_id,
            fetched_at_utc=fetched_at_utc,
            fetch_status="invalid_board_url",
            notes="unable_to_parse_workable_account",
        ), []

    api_url = f"https://apply.workable.com/api/v3/accounts/{account}/jobs"
    response = session().post(api_url, json={}, timeout=20)
    if response.status_code != 200:
        return company_result(
            row,
            run_id=run_id,
            fetched_at_utc=fetched_at_utc,
            source_api_url=api_url,
            fetch_status="endpoint_error",
            endpoint_http_status=str(response.status_code),
            notes=f"http_{response.status_code}",
        ), []

    payload = response.json()
    jobs = payload.get("results", [])
    normalized_jobs = []
    for job in jobs:
        location = normalize_location_parts(
            [
                (job.get("location") or {}).get("city", ""),
                (job.get("location") or {}).get("region", "") or "",
                (job.get("location") or {}).get("country", ""),
            ]
        )
        departments = job.get("department", [])
        department_names = ";".join(
            item.get("title", "").strip() if isinstance(item, dict) else str(item).strip()
            for item in departments
            if item
        )
        job_url = f"https://apply.workable.com/{account}/j/{job.get('shortcode', '')}/"
        normalized_jobs.append(
            job_row(
                row,
                run_id=run_id,
                fetched_at_utc=fetched_at_utc,
                source_api_url=api_url,
                source_job_id=str(job.get("id", "")),
                title=job.get("title", ""),
                location=location,
                department=department_names,
                team="",
                employment_type=job.get("type", ""),
                workplace_type=job.get("workplace", ""),
                is_remote=bool_string(bool(job.get("remote"))),
                posted_at=job.get("published", ""),
                updated_at="",
                job_url=job_url,
                apply_url=job_url,
            )
        )

    return company_result(
        row,
        run_id=run_id,
        fetched_at_utc=fetched_at_utc,
        source_api_url=api_url,
        fetch_status="live_jobs" if normalized_jobs else "zero_jobs",
        job_count=len(normalized_jobs),
        endpoint_http_status=str(response.status_code),
    ), normalized_jobs


def fetch_dover_jobs(row: dict[str, str], run_id: str, fetched_at_utc: str) -> tuple[dict[str, str], list[dict[str, str]]]:
    api_url = row.get("board_api_url", "")
    token = match_first(DOVER_API_RE, api_url)
    if not token:
        token = match_first(DOVER_RE, row["board_url"])
        if token:
            api_url = f"https://app.dover.com/feed/v1/boards/{token}/jobs"
    if not token or not api_url:
        return company_result(
            row,
            run_id=run_id,
            fetched_at_utc=fetched_at_utc,
            fetch_status="invalid_board_url",
            notes="unable_to_parse_dover_slug",
        ), []

    response = session().get(api_url, timeout=20)
    if response.status_code != 200:
        return company_result(
            row,
            run_id=run_id,
            fetched_at_utc=fetched_at_utc,
            source_api_url=api_url,
            fetch_status="endpoint_error",
            endpoint_http_status=str(response.status_code),
            notes=f"http_{response.status_code}",
        ), []

    payload = response.json()
    jobs = payload.get("jobs", [])
    normalized_jobs = [
        job_row(
            row,
            run_id=run_id,
            fetched_at_utc=fetched_at_utc,
            source_api_url=api_url,
            source_job_id=str(job.get("id", "")),
            title=job.get("title", ""),
            location=(job.get("location") or {}).get("name", ""),
            department=normalize_mixed_department(job.get("department")),
            team="",
            employment_type="",
            workplace_type="remote" if job.get("remote") else "",
            is_remote=bool_string(bool(job.get("remote"))),
            posted_at=job.get("first_published", ""),
            updated_at=job.get("updated_at", ""),
            job_url=job.get("absolute_url", ""),
            apply_url=job.get("absolute_url", ""),
        )
        for job in jobs
    ]
    return company_result(
        row,
        run_id=run_id,
        fetched_at_utc=fetched_at_utc,
        source_api_url=api_url,
        fetch_status="live_jobs" if normalized_jobs else "zero_jobs",
        job_count=len(normalized_jobs),
        endpoint_http_status=str(response.status_code),
    ), normalized_jobs


def fetch_company_jobs(row: dict[str, str], run_id: str, fetched_at_utc: str) -> tuple[dict[str, str], list[dict[str, str]]]:
    try:
        if row["board_type"] == "greenhouse":
            return fetch_greenhouse_jobs(row, run_id, fetched_at_utc)
        if row["board_type"] == "ashby":
            return fetch_ashby_jobs(row, run_id, fetched_at_utc)
        if row["board_type"] == "lever":
            return fetch_lever_jobs(row, run_id, fetched_at_utc)
        if row["board_type"] == "workable":
            return fetch_workable_jobs(row, run_id, fetched_at_utc)
        if row["board_type"] == "dover":
            return fetch_dover_jobs(row, run_id, fetched_at_utc)
        return company_result(
            row,
            run_id=run_id,
            fetched_at_utc=fetched_at_utc,
            fetch_status="unsupported_board_type",
            notes=row["board_type"],
        ), []
    except requests.RequestException as exc:
        return company_result(
            row,
            run_id=run_id,
            fetched_at_utc=fetched_at_utc,
            fetch_status="request_error",
            notes=type(exc).__name__,
        ), []
    except Exception as exc:  # pragma: no cover - defensive guard for live integrations
        return company_result(
            row,
            run_id=run_id,
            fetched_at_utc=fetched_at_utc,
            fetch_status="parse_error",
            notes=type(exc).__name__,
        ), []


def build_summary(
    *,
    run_id: str,
    fetched_at_utc: str,
    all_rows: list[dict[str, str]],
    configured: list[dict[str, str]],
    company_results: list[dict[str, str]],
    jobs: list[dict[str, str]],
    output_dir: Path,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "fetched_at_utc": fetched_at_utc,
        "watchlist_rows_total": len(all_rows),
        "configured_rows_total": len(configured),
        "job_rows_total": len(jobs),
        "company_fetch_status_counts": dict(Counter(row["fetch_status"] for row in company_results)),
        "jobs_by_board_type": dict(Counter(job["board_type"] for job in jobs)),
        "jobs_by_segment_primary": dict(Counter(job["segment_primary"] for job in jobs)),
        "jobs_csv": str(output_dir / "jobs.csv"),
        "company_results_csv": str(output_dir / "company-results.csv"),
    }


def main() -> None:
    all_rows = read_csv_rows(WATCHLIST_CSV)
    configured = configured_rows(all_rows)

    fetched_at_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = RUNS_DIR / run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    company_results: list[dict[str, str]] = []
    jobs: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=24) as executor:
        future_map = {
            executor.submit(fetch_company_jobs, row, run_id, fetched_at_utc): row
            for row in configured
        }
        for future in as_completed(future_map):
            company_result_row, company_jobs = future.result()
            company_results.append(company_result_row)
            jobs.extend(company_jobs)

    company_results.sort(key=lambda row: row["company_name"].casefold())
    jobs.sort(
        key=lambda row: (
            row["company_name"].casefold(),
            row["title"].casefold(),
            row["source_job_id"],
        )
    )

    write_csv(output_dir / "company-results.csv", COMPANY_RESULT_FIELDNAMES, company_results)
    write_csv(output_dir / "jobs.csv", JOB_FIELDNAMES, jobs)

    summary = build_summary(
        run_id=run_id,
        fetched_at_utc=fetched_at_utc,
        all_rows=all_rows,
        configured=configured,
        company_results=company_results,
        jobs=jobs,
        output_dir=output_dir,
    )
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (RUNS_DIR / "latest-run.txt").write_text(run_id + "\n", encoding="utf-8")
    (RUNS_DIR / "latest-summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    print(f"Configured companies fetched: {len(configured)}")
    print(f"Jobs fetched: {len(jobs)}")
    print(f"Wrote {output_dir / 'company-results.csv'}")
    print(f"Wrote {output_dir / 'jobs.csv'}")
    print(f"Wrote {output_dir / 'summary.json'}")
    print(f"Wrote {RUNS_DIR / 'latest-run.txt'}")
    print(f"Wrote {RUNS_DIR / 'latest-summary.json'}")


if __name__ == "__main__":
    main()
