#!/usr/bin/env python3

from __future__ import annotations

import csv
import json
import re
import threading
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parents[2]
INPUT_CSV = ROOT / "ops" / "company-watchlists" / "yc-us-hiring-trackability.csv"
OUTPUT_CSV = ROOT / "ops" / "company-watchlists" / "yc-api-native-board-confirmation.csv"
OUTPUT_JSON = ROOT / "ops" / "company-watchlists" / "yc-api-native-board-confirmation-summary.json"

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

FIELDNAMES = [
    "company_name",
    "company_slug",
    "website",
    "yc_directory_url",
    "detected_board_type",
    "selected_url",
    "board_token",
    "board_url",
    "api_url",
    "confirmation_status",
    "job_count",
    "endpoint_http_status",
    "notes",
]

GREENHOUSE_PATTERNS = (
    re.compile(r"https?://(?:job-boards|boards)\.greenhouse\.io/([A-Za-z0-9_-]+)", re.I),
    re.compile(r"https?://boards-api\.greenhouse\.io/v1/boards/([A-Za-z0-9_-]+)/jobs", re.I),
    re.compile(r"embed/job_board/js\?for=([A-Za-z0-9_-]+)", re.I),
)
WORKABLE_PATTERNS = (
    re.compile(r"https?://(?:apply\.)?workable\.com/([A-Za-z0-9._-]+)", re.I),
    re.compile(r"https?://apply\.workable\.com/([A-Za-z0-9._-]+)", re.I),
)
ASHBY_PATTERNS = (
    re.compile(r"https?://jobs\.ashbyhq\.com/([A-Za-z0-9._-]+)", re.I),
    re.compile(r"https?://api\.ashbyhq\.com/posting-api/job-board/([A-Za-z0-9._-]+)", re.I),
)
LEVER_PATTERNS = (
    re.compile(r"https?://jobs\.lever\.co/([A-Za-z0-9._-]+)", re.I),
    re.compile(r"https?://api\.lever\.co/v0/postings/([A-Za-z0-9._-]+)", re.I),
)
LEVER_CONFIG_PATTERNS = (
    re.compile(r'accountName:\s*"([^"]+)"', re.I),
    re.compile(r"companyName:\s*['\"]([^'\"]+)['\"]", re.I),
)

_session_local = threading.local()


def session() -> requests.Session:
    sess = getattr(_session_local, "session", None)
    if sess is None:
        sess = requests.Session()
        sess.headers.update(REQUEST_HEADERS)
        _session_local.session = sess
    return sess


def dedupe(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value:
            continue
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def fetch_text(url: str) -> tuple[str, int, str]:
    response = session().get(url, timeout=20, allow_redirects=True)
    status = response.status_code
    final_url = response.url
    content_type = response.headers.get("content-type", "").casefold()
    if "text/html" in content_type or "application/xhtml+xml" in content_type:
        return final_url, status, response.text[:700_000]
    return final_url, status, ""


def extract_matches(patterns: Iterable[re.Pattern[str]], values: Iterable[str]) -> list[str]:
    matches: list[str] = []
    for value in values:
        if not value:
            continue
        for pattern in patterns:
            matches.extend(match.group(1) for match in pattern.finditer(value))
    return dedupe(matches)


def greenhouse_tokens(url: str, html: str) -> list[str]:
    return extract_matches(GREENHOUSE_PATTERNS, [url, html])


def workable_accounts(url: str, html: str) -> list[str]:
    return extract_matches(WORKABLE_PATTERNS, [url, html])


def ashby_orgs(url: str, html: str) -> list[str]:
    return extract_matches(ASHBY_PATTERNS, [url, html])


def lever_accounts(url: str, html: str, company_slug: str) -> list[str]:
    matches = extract_matches(LEVER_PATTERNS, [url, html])
    for pattern in LEVER_CONFIG_PATTERNS:
        matches.extend(match.group(1) for match in pattern.finditer(html))
    # Fallback helps when the page is partially blocked but the company slug matches the Lever handle.
    matches.append(company_slug)
    return dedupe(matches)


def make_result(
    row: dict[str, str],
    *,
    board_token: str = "",
    board_url: str = "",
    api_url: str = "",
    confirmation_status: str,
    job_count: int = 0,
    endpoint_http_status: str = "",
    notes: str = "",
) -> dict[str, str]:
    return {
        "company_name": row["company_name"],
        "company_slug": row["company_slug"],
        "website": row["website"],
        "yc_directory_url": row["yc_directory_url"],
        "detected_board_type": row["detected_board_type"],
        "selected_url": row["selected_url"],
        "board_token": board_token,
        "board_url": board_url,
        "api_url": api_url,
        "confirmation_status": confirmation_status,
        "job_count": str(job_count),
        "endpoint_http_status": endpoint_http_status,
        "notes": notes,
    }


def confirm_greenhouse(row: dict[str, str]) -> dict[str, str]:
    html = ""
    final_url = row["selected_url"]
    surface_status = ""
    try:
        final_url, status, html = fetch_text(row["selected_url"])
        surface_status = str(status)
    except Exception as exc:  # pragma: no cover - network variance
        surface_status = type(exc).__name__

    tokens = greenhouse_tokens(final_url, html)
    if not tokens:
        return make_result(
            row,
            confirmation_status="unresolved_board_token",
            endpoint_http_status=surface_status,
            notes="no_greenhouse_token_found",
        )

    best_empty: dict[str, str] | None = None
    last_failure = "no_greenhouse_endpoint_succeeded"
    last_http_status = ""
    for token in tokens:
        board_url = f"https://job-boards.greenhouse.io/{token}"
        api_url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
        try:
            response = session().get(api_url, timeout=20)
            status_code = response.status_code
            if status_code != 200:
                last_http_status = str(status_code)
                last_failure = f"http_{status_code}"
                continue
            payload = response.json()
            jobs = payload.get("jobs", [])
            job_count = len(jobs)
            if job_count > 0:
                return make_result(
                    row,
                    board_token=token,
                    board_url=board_url,
                    api_url=api_url,
                    confirmation_status="live_jobs",
                    job_count=job_count,
                    endpoint_http_status=str(status_code),
                )
            best_empty = make_result(
                row,
                board_token=token,
                board_url=board_url,
                api_url=api_url,
                confirmation_status="board_reachable_zero_jobs",
                job_count=0,
                endpoint_http_status=str(status_code),
            )
        except Exception as exc:  # pragma: no cover - network variance
            last_failure = type(exc).__name__

    if best_empty is not None:
        return best_empty
    return make_result(
        row,
        confirmation_status="endpoint_error",
        endpoint_http_status=last_http_status or surface_status,
        notes=last_failure,
    )


def confirm_workable(row: dict[str, str]) -> dict[str, str]:
    html = ""
    final_url = row["selected_url"]
    surface_status = ""
    try:
        final_url, status, html = fetch_text(row["selected_url"])
        surface_status = str(status)
    except Exception as exc:  # pragma: no cover - network variance
        surface_status = type(exc).__name__

    accounts = workable_accounts(final_url, html)
    if not accounts:
        return make_result(
            row,
            confirmation_status="unresolved_board_token",
            endpoint_http_status=surface_status,
            notes="no_workable_account_found",
        )

    best_empty: dict[str, str] | None = None
    last_failure = "no_workable_endpoint_succeeded"
    last_http_status = ""
    for account in accounts:
        board_url = f"https://apply.workable.com/{account}/"
        api_url = f"https://apply.workable.com/api/v3/accounts/{account}/jobs"
        try:
            response = session().post(api_url, json={}, timeout=20)
            status_code = response.status_code
            if status_code != 200:
                last_http_status = str(status_code)
                last_failure = f"http_{status_code}"
                continue
            payload = response.json()
            results = payload.get("results", [])
            job_count = payload.get("total")
            if not isinstance(job_count, int):
                job_count = len(results)
            if job_count > 0:
                return make_result(
                    row,
                    board_token=account,
                    board_url=board_url,
                    api_url=api_url,
                    confirmation_status="live_jobs",
                    job_count=job_count,
                    endpoint_http_status=str(status_code),
                )
            best_empty = make_result(
                row,
                board_token=account,
                board_url=board_url,
                api_url=api_url,
                confirmation_status="board_reachable_zero_jobs",
                job_count=0,
                endpoint_http_status=str(status_code),
            )
        except Exception as exc:  # pragma: no cover - network variance
            last_failure = type(exc).__name__

    if best_empty is not None:
        return best_empty
    return make_result(
        row,
        confirmation_status="endpoint_error",
        endpoint_http_status=last_http_status or surface_status,
        notes=last_failure,
    )


def confirm_ashby(row: dict[str, str]) -> dict[str, str]:
    html = ""
    final_url = row["selected_url"]
    surface_status = ""
    try:
        final_url, status, html = fetch_text(row["selected_url"])
        surface_status = str(status)
    except Exception as exc:  # pragma: no cover - network variance
        surface_status = type(exc).__name__

    orgs = ashby_orgs(final_url, html)
    if not orgs:
        return make_result(
            row,
            confirmation_status="unresolved_board_token",
            endpoint_http_status=surface_status,
            notes="no_ashby_org_found",
        )

    best_empty: dict[str, str] | None = None
    last_failure = "no_ashby_endpoint_succeeded"
    last_http_status = ""
    for org in orgs:
        board_url = f"https://jobs.ashbyhq.com/{org}"
        api_url = f"https://api.ashbyhq.com/posting-api/job-board/{org}?includeCompensation=true"
        try:
            response = session().get(api_url, timeout=20)
            status_code = response.status_code
            if status_code != 200:
                last_http_status = str(status_code)
                last_failure = f"http_{status_code}"
                continue
            payload = response.json()
            jobs = payload.get("jobs", [])
            job_count = len(jobs)
            if job_count > 0:
                return make_result(
                    row,
                    board_token=org,
                    board_url=board_url,
                    api_url=api_url,
                    confirmation_status="live_jobs",
                    job_count=job_count,
                    endpoint_http_status=str(status_code),
                )
            best_empty = make_result(
                row,
                board_token=org,
                board_url=board_url,
                api_url=api_url,
                confirmation_status="board_reachable_zero_jobs",
                job_count=0,
                endpoint_http_status=str(status_code),
            )
        except Exception as exc:  # pragma: no cover - network variance
            last_failure = type(exc).__name__

    if best_empty is not None:
        return best_empty
    return make_result(
        row,
        confirmation_status="endpoint_error",
        endpoint_http_status=last_http_status or surface_status,
        notes=last_failure,
    )


def confirm_lever(row: dict[str, str]) -> dict[str, str]:
    html = ""
    final_url = row["selected_url"]
    surface_status = ""
    try:
        final_url, status, html = fetch_text(row["selected_url"])
        surface_status = str(status)
    except Exception as exc:  # pragma: no cover - network variance
        surface_status = type(exc).__name__

    accounts = lever_accounts(final_url, html, row["company_slug"])
    if not accounts:
        return make_result(
            row,
            confirmation_status="unresolved_board_token",
            endpoint_http_status=surface_status,
            notes="no_lever_account_found",
        )

    best_empty: dict[str, str] | None = None
    last_failure = "no_lever_endpoint_succeeded"
    last_http_status = ""
    for account in accounts:
        board_url = f"https://jobs.lever.co/{account}"
        api_url = f"https://api.lever.co/v0/postings/{account}?mode=json"
        try:
            response = session().get(api_url, timeout=20)
            status_code = response.status_code
            if status_code != 200:
                last_http_status = str(status_code)
                last_failure = f"http_{status_code}"
                continue
            payload = response.json()
            job_count = len(payload) if isinstance(payload, list) else 0
            if job_count > 0:
                return make_result(
                    row,
                    board_token=account,
                    board_url=board_url,
                    api_url=api_url,
                    confirmation_status="live_jobs",
                    job_count=job_count,
                    endpoint_http_status=str(status_code),
                )
            best_empty = make_result(
                row,
                board_token=account,
                board_url=board_url,
                api_url=api_url,
                confirmation_status="board_reachable_zero_jobs",
                job_count=0,
                endpoint_http_status=str(status_code),
            )
        except Exception as exc:  # pragma: no cover - network variance
            last_failure = type(exc).__name__

    if best_empty is not None:
        return best_empty
    return make_result(
        row,
        confirmation_status="endpoint_error",
        endpoint_http_status=last_http_status or surface_status,
        notes=last_failure,
    )


def confirm_row(row: dict[str, str]) -> dict[str, str]:
    board_type = row["detected_board_type"]
    if board_type == "greenhouse":
        return confirm_greenhouse(row)
    if board_type == "workable":
        return confirm_workable(row)
    if board_type == "ashby":
        return confirm_ashby(row)
    if board_type == "lever":
        return confirm_lever(row)
    return make_result(
        row,
        confirmation_status="unsupported_board_type",
        notes=f"unsupported:{board_type}",
    )


def load_rows() -> list[dict[str, str]]:
    with INPUT_CSV.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return [row for row in rows if row["trackability"] == "api_native"]


def write_outputs(rows: list[dict[str, str]]) -> None:
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    status_counts = Counter(row["confirmation_status"] for row in rows)
    board_totals = Counter(row["detected_board_type"] for row in rows)
    board_status_counts: dict[str, dict[str, int]] = defaultdict(dict)
    for board_type in sorted(board_totals):
        board_rows = [row for row in rows if row["detected_board_type"] == board_type]
        board_status_counts[board_type] = dict(
            Counter(row["confirmation_status"] for row in board_rows)
        )

    summary = {
        "total_api_native_companies": len(rows),
        "status_counts": dict(status_counts),
        "board_totals": dict(board_totals),
        "board_status_counts": board_status_counts,
        "confirmed_live_jobs_total": status_counts.get("live_jobs", 0),
    }
    OUTPUT_JSON.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    rows = load_rows()
    results: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=24) as executor:
        future_map = {executor.submit(confirm_row, row): row for row in rows}
        for future in as_completed(future_map):
            results.append(future.result())

    results.sort(key=lambda row: row["company_name"].casefold())
    write_outputs(results)

    live_jobs = sum(1 for row in results if row["confirmation_status"] == "live_jobs")
    print(f"Confirmed {live_jobs} live boards out of {len(results)} api_native companies.")
    print(f"Wrote {OUTPUT_CSV}")
    print(f"Wrote {OUTPUT_JSON}")


if __name__ == "__main__":
    main()
