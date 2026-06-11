#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import json
import re
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote, urljoin, urlparse

import requests

ROOT = Path(__file__).resolve().parents[2]
WATCHLIST_DIR = ROOT / "ops" / "company-watchlists"
TRACKABILITY_CSV = WATCHLIST_DIR / "yc-us-hiring-trackability.csv"
CONFIRMATION_CSV = WATCHLIST_DIR / "yc-api-native-board-confirmation.csv"
BATCH_DIR = WATCHLIST_DIR / "recheck-batches"
TRUTH_CSV = WATCHLIST_DIR / "yc-us-hiring-recheck-truth.csv"
TRUTH_SUMMARY_JSON = WATCHLIST_DIR / "yc-us-hiring-recheck-truth-summary.json"

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

COMMON_CAREERS_PATHS = [
    "/careers",
    "/careers/",
    "/jobs",
    "/jobs/",
    "/about/careers",
    "/about/careers/",
    "/about/careers/join-the-team",
    "/open-positions",
    "/open-positions/",
    "/job-openings",
    "/job-openings/",
    "/join-the-team",
    "/join-our-team",
    "/company/careers",
    "/company/careers/",
]

ANCHOR_RE = re.compile(
    r"<a\b[^>]*href=[\"'](?P<href>[^\"']+)[\"'][^>]*>(?P<text>.*?)</a>",
    re.IGNORECASE | re.DOTALL,
)
TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")

GREENHOUSE_PATTERNS = (
    re.compile(r"https?://(?:job-boards|boards)\.greenhouse\.io/([A-Za-z0-9_-]+)", re.I),
    re.compile(r"https?://boards-api\.greenhouse\.io/v1/boards/([A-Za-z0-9_-]+)/jobs", re.I),
    re.compile(r"embed/job_board/js\?for=([A-Za-z0-9_-]+)", re.I),
)
ASHBY_PATTERNS = (
    re.compile(r"https?://jobs\.ashbyhq\.com/([A-Za-z0-9._%-]+)", re.I),
    re.compile(r"https?://api\.ashbyhq\.com/posting-api/job-board/([A-Za-z0-9._%-]+)", re.I),
)
LEVER_PATTERNS = (
    re.compile(r"https?://jobs\.lever\.co/([A-Za-z0-9._-]+)", re.I),
    re.compile(r"https?://api\.lever\.co/v0/postings/([A-Za-z0-9._-]+)", re.I),
)
LEVER_CONFIG_PATTERNS = (
    re.compile(r'accountName:\s*"([^"]+)"', re.I),
    re.compile(r"companyName:\s*['\"]([^'\"]+)['\"]", re.I),
)
WORKABLE_PATTERNS = (
    re.compile(r"https?://(?:apply\.)?workable\.com/([A-Za-z0-9._-]+)", re.I),
    re.compile(r"https?://apply\.workable\.com/([A-Za-z0-9._-]+)", re.I),
)
DOVER_PATTERNS = (
    re.compile(r"https?://app\.dover\.com/jobs/([A-Za-z0-9._%-]+)", re.I),
    re.compile(r"https?://app\.dover\.com/apply/([A-Za-z0-9._%-]+)/", re.I),
    re.compile(r"https?://app\.dover\.com/feed/v1/boards/([A-Za-z0-9._%-]+)/jobs", re.I),
)

STRUCTURED_PATTERNS: tuple[tuple[str, str], ...] = (
    ("rippling", "ats.rippling.com"),
    ("workday", "myworkdayjobs.com"),
    ("ukg_ultipro", "recruiting.ultipro.com"),
    ("ukg_ultipro", "ultipro.com"),
    ("paycom", "paycomonline.net"),
    ("icims", "icims.com"),
    ("bamboohr", "bamboohr.com"),
    ("recruitee", "recruitee.com"),
    ("jazzhr", "applytojob.com"),
    ("breezy", "breezy.hr"),
    ("teamtailor", "teamtailor.com"),
    ("smartrecruiters", "smartrecruiters.com"),
    ("linkedin_jobs", "linkedin.com/jobs"),
    ("notion", "notion.site"),
    ("dover", "app.dover.com"),
)

RESULT_FIELDNAMES = [
    "checked_at_utc",
    "batch_id",
    "queue_position",
    "company_name",
    "company_slug",
    "website",
    "yc_directory_url",
    "previous_trackability",
    "previous_board_type",
    "previous_selected_url",
    "recheck_trackability",
    "recheck_board_type",
    "recheck_board_token",
    "recheck_board_url",
    "recheck_api_url",
    "recheck_confirmation_status",
    "recheck_job_count",
    "visited_pages",
    "resolved_from_url",
    "evidence",
    "notes",
]

TRACKABILITY_PRIORITY = {
    "custom_page": 0,
    "unknown": 1,
    "api_native": 2,
    "structured_board": 3,
}

ATS_HOST_KEYWORDS = (
    "greenhouse.io",
    "ashbyhq.com",
    "lever.co",
    "workable.com",
    "myworkdayjobs.com",
    "ultipro.com",
    "icims.com",
    "bamboohr.com",
    "recruitee.com",
    "jazzhr.com",
    "applytojob.com",
    "breezy.hr",
    "teamtailor.com",
    "smartrecruiters.com",
    "rippling.com",
    "ripplingcdn.com",
    "ats.rippling.com",
    "paycomonline.net",
    "app.dover.com",
)

_session_local = threading.local()


@dataclass(frozen=True)
class BoardCandidate:
    board_type: str
    trackability: str
    board_url: str
    api_url: str
    token: str
    evidence: str


def session() -> requests.Session:
    sess = getattr(_session_local, "session", None)
    if sess is None:
        sess = requests.Session()
        sess.headers.update(REQUEST_HEADERS)
        _session_local.session = sess
    return sess


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=RESULT_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def merge_truth_rows(existing_rows: list[dict[str, str]], new_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    merged = {row["company_slug"]: row for row in existing_rows}
    for row in new_rows:
        merged[row["company_slug"]] = row
    return sorted(merged.values(), key=lambda row: row["company_name"].casefold())


def write_truth_outputs(new_rows: list[dict[str, str]]) -> None:
    existing_rows = read_csv_rows(TRUTH_CSV) if TRUTH_CSV.exists() else []
    merged_rows = merge_truth_rows(existing_rows, new_rows)
    write_csv(TRUTH_CSV, merged_rows)

    summary = {
        "company_count": len(merged_rows),
        "status_counts": dict(Counter(row["recheck_confirmation_status"] for row in merged_rows)),
        "trackability_counts": dict(Counter(row["recheck_trackability"] for row in merged_rows)),
        "board_type_counts": dict(
            Counter(row["recheck_board_type"] for row in merged_rows if row["recheck_board_type"])
        ),
    }
    TRUTH_SUMMARY_JSON.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


def clean_text(text: str) -> str:
    return SPACE_RE.sub(" ", TAG_RE.sub(" ", text)).strip()


def host(url: str) -> str:
    return urlparse(url).netloc.casefold()


def origin(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def fetch_text(url: str) -> tuple[str, int, str]:
    response = session().get(url, timeout=20, allow_redirects=True)
    response.raise_for_status()
    content_type = response.headers.get("content-type", "").casefold()
    if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
        return response.url, response.status_code, ""
    return response.url, response.status_code, response.text[:700_000]


def extract_matches(patterns: Iterable[re.Pattern[str]], values: Iterable[str]) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value:
            continue
        for pattern in patterns:
            for match in pattern.finditer(value):
                token = match.group(1)
                if token not in seen:
                    seen.add(token)
                    found.append(token)
    return found


def expand_dover_tokens(tokens: Iterable[str]) -> list[str]:
    expanded: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        for candidate in (token, unquote(token), token.casefold(), unquote(token).casefold()):
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            expanded.append(candidate)
    return expanded


def detect_board_candidates(url: str, html: str, company_slug: str) -> list[BoardCandidate]:
    values = [url, html]
    candidates: list[BoardCandidate] = []
    seen: set[tuple[str, str]] = set()

    def add(candidate: BoardCandidate) -> None:
        key = (candidate.board_type, candidate.board_url)
        if key in seen:
            return
        seen.add(key)
        candidates.append(candidate)

    for token in extract_matches(GREENHOUSE_PATTERNS, values):
        add(
            BoardCandidate(
                board_type="greenhouse",
                trackability="api_native",
                board_url=f"https://job-boards.greenhouse.io/{token}",
                api_url=f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true",
                token=token,
                evidence="greenhouse_pattern",
            )
        )

    for token in extract_matches(ASHBY_PATTERNS, values):
        add(
            BoardCandidate(
                board_type="ashby",
                trackability="api_native",
                board_url=f"https://jobs.ashbyhq.com/{token}",
                api_url=f"https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=true",
                token=token,
                evidence="ashby_pattern",
            )
        )

    lever_tokens = extract_matches(LEVER_PATTERNS, values)
    for pattern in LEVER_CONFIG_PATTERNS:
        lever_tokens.extend(match.group(1) for match in pattern.finditer(html))
    if any("lever" in value.casefold() for value in values):
        lever_tokens.append(company_slug)
    lever_seen: set[str] = set()
    for token in lever_tokens:
        if token in lever_seen or not token:
            continue
        lever_seen.add(token)
        add(
            BoardCandidate(
                board_type="lever",
                trackability="api_native",
                board_url=f"https://jobs.lever.co/{token}",
                api_url=f"https://api.lever.co/v0/postings/{token}?mode=json",
                token=token,
                evidence="lever_pattern",
            )
        )

    for token in extract_matches(WORKABLE_PATTERNS, values):
        add(
            BoardCandidate(
                board_type="workable",
                trackability="api_native",
                board_url=f"https://apply.workable.com/{token}/",
                api_url=f"https://apply.workable.com/api/v3/accounts/{token}/jobs",
                token=token,
                evidence="workable_pattern",
            )
        )

    for token in expand_dover_tokens(extract_matches(DOVER_PATTERNS, values)):
        add(
            BoardCandidate(
                board_type="dover",
                trackability="api_native",
                board_url=f"https://app.dover.com/jobs/{token}",
                api_url=f"https://app.dover.com/feed/v1/boards/{token}/jobs",
                token=token,
                evidence="dover_pattern",
            )
        )

    haystack = f"{url}\n{html}".casefold()
    for board_type, marker in STRUCTURED_PATTERNS:
        if marker.casefold() in haystack:
            add(
                BoardCandidate(
                    board_type=board_type,
                    trackability="structured_board",
                    board_url=url,
                    api_url="",
                    token="",
                    evidence=marker,
                )
            )
    return candidates


def confirm_candidate(candidate: BoardCandidate) -> tuple[str, int, str]:
    try:
        if candidate.board_type == "greenhouse":
            response = session().get(candidate.api_url, timeout=20)
            if response.status_code != 200:
                return "endpoint_error", 0, f"http_{response.status_code}"
            jobs = response.json().get("jobs", [])
            return ("live_jobs" if jobs else "board_reachable_zero_jobs", len(jobs), "")

        if candidate.board_type == "ashby":
            response = session().get(candidate.api_url, timeout=20)
            if response.status_code != 200:
                return "endpoint_error", 0, f"http_{response.status_code}"
            jobs = response.json().get("jobs", [])
            live_jobs = [job for job in jobs if job.get("isListed", True)]
            return ("live_jobs" if live_jobs else "board_reachable_zero_jobs", len(live_jobs), "")

        if candidate.board_type == "lever":
            response = session().get(candidate.api_url, timeout=20)
            if response.status_code != 200:
                return "endpoint_error", 0, f"http_{response.status_code}"
            payload = response.json()
            job_count = len(payload) if isinstance(payload, list) else 0
            return ("live_jobs" if job_count else "board_reachable_zero_jobs", job_count, "")

        if candidate.board_type == "workable":
            response = session().post(candidate.api_url, json={}, timeout=20)
            if response.status_code != 200:
                return "endpoint_error", 0, f"http_{response.status_code}"
            payload = response.json()
            results = payload.get("results", [])
            total = payload.get("total")
            job_count = total if isinstance(total, int) else len(results)
            return ("live_jobs" if job_count else "board_reachable_zero_jobs", job_count, "")

        if candidate.board_type == "dover":
            response = session().get(candidate.api_url, timeout=20)
            if response.status_code != 200:
                return "endpoint_error", 0, f"http_{response.status_code}"
            payload = response.json()
            jobs = payload.get("jobs", [])
            return ("live_jobs" if jobs else "board_reachable_zero_jobs", len(jobs), "")
    except Exception as exc:  # pragma: no cover - network variance
        return "endpoint_error", 0, type(exc).__name__

    return "unconfirmed", 0, f"unsupported:{candidate.board_type}"


def score_link(base_host: str, href: str, text: str) -> int:
    href_lower = href.casefold()
    text_lower = text.casefold()

    if href_lower.startswith(("mailto:", "tel:", "javascript:")):
        return -1000
    if any(domain in href_lower for domain in ("facebook.com", "instagram.com", "twitter.com", "x.com", "linkedin.com/company")):
        return -1000

    score = 0
    if any(keyword in text_lower for keyword in ("careers", "jobs", "open positions", "job openings", "join", "hiring", "team")):
        score += 90
    if any(keyword in href_lower for keyword in ("/careers", "/jobs", "open-positions", "job-openings", "join-the-team", "join-our-team", "/apply")):
        score += 80
    if any(keyword in href_lower for keyword in ATS_HOST_KEYWORDS):
        score += 120
    if host(href) == base_host:
        score += 30
    return score


def extract_candidate_links(base_url: str, html: str) -> list[str]:
    base_host = host(base_url)
    ranked: list[tuple[int, str]] = []
    seen: set[str] = set()
    for match in ANCHOR_RE.finditer(html):
        href = match.group("href").strip()
        text = clean_text(match.group("text"))
        full_url = urljoin(base_url, href)
        if not full_url.startswith(("http://", "https://")):
            continue
        if full_url in seen:
            continue
        seen.add(full_url)
        score = score_link(base_host, full_url, text)
        if score > 0:
            ranked.append((score, full_url))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [url for _, url in ranked[:12]]


def build_seed_urls(row: dict[str, str]) -> list[str]:
    seeds: list[str] = []
    for value in (row.get("selected_url", ""), row.get("website", "")):
        if value.startswith(("http://", "https://")) and value not in seeds:
            seeds.append(value)
    website = row.get("website", "")
    if website.startswith(("http://", "https://")):
        base = origin(website)
        for path in COMMON_CAREERS_PATHS:
            candidate = base + path
            if candidate not in seeds:
                seeds.append(candidate)
    return seeds


def select_recheck_rows(batch_size: int, batch_index: int, company_slugs: list[str]) -> list[dict[str, str]]:
    rows = read_csv_rows(TRACKABILITY_CSV)
    confirmed_rows = read_csv_rows(CONFIRMATION_CSV)
    confirmed_live = {row["company_slug"] for row in confirmed_rows if row["confirmation_status"] == "live_jobs"}
    remaining = [row for row in rows if row["company_slug"] not in confirmed_live]

    if company_slugs:
        wanted = set(company_slugs)
        return sorted(
            [row for row in remaining if row["company_slug"] in wanted],
            key=lambda row: row["company_name"].casefold(),
        )

    remaining.sort(
        key=lambda row: (
            TRACKABILITY_PRIORITY.get(row["trackability"], 99),
            row["company_name"].casefold(),
        )
    )
    start = (batch_index - 1) * batch_size
    end = start + batch_size
    return remaining[start:end]


def recheck_company(
    row: dict[str, str],
    batch_id: str,
    queue_position: int,
    checked_at_utc: str,
) -> dict[str, str]:
    seeds = build_seed_urls(row)
    queue: list[tuple[str, int]] = [(url, 0) for url in seeds]
    seen_urls: set[str] = set()
    best_structured: BoardCandidate | None = None
    notes: list[str] = []

    while queue and len(seen_urls) < 12:
        current_url, depth = queue.pop(0)
        if current_url in seen_urls:
            continue
        seen_urls.add(current_url)
        try:
            final_url, _, html = fetch_text(current_url)
        except Exception as exc:  # pragma: no cover - network variance
            notes.append(f"fetch_failed:{type(exc).__name__}:{current_url}")
            continue

        candidates = detect_board_candidates(final_url, html, row["company_slug"])
        for candidate in candidates:
            if candidate.trackability == "api_native":
                status, job_count, note = confirm_candidate(candidate)
                if status == "live_jobs":
                    return {
                        "checked_at_utc": checked_at_utc,
                        "batch_id": batch_id,
                        "queue_position": str(queue_position),
                        "company_name": row["company_name"],
                        "company_slug": row["company_slug"],
                        "website": row["website"],
                        "yc_directory_url": row["yc_directory_url"],
                        "previous_trackability": row["trackability"],
                        "previous_board_type": row["detected_board_type"],
                        "previous_selected_url": row["selected_url"],
                        "recheck_trackability": "api_native",
                        "recheck_board_type": candidate.board_type,
                        "recheck_board_token": candidate.token,
                        "recheck_board_url": candidate.board_url,
                        "recheck_api_url": candidate.api_url,
                        "recheck_confirmation_status": status,
                        "recheck_job_count": str(job_count),
                        "visited_pages": str(len(seen_urls)),
                        "resolved_from_url": final_url,
                        "evidence": candidate.evidence,
                        "notes": note,
                    }
                notes.append(f"{candidate.board_type}:{status}:{note}")
            elif best_structured is None:
                best_structured = candidate

        if depth < 2:
            for link in extract_candidate_links(final_url, html):
                if link not in seen_urls:
                    queue.append((link, depth + 1))

    if best_structured is not None:
        return {
            "checked_at_utc": checked_at_utc,
            "batch_id": batch_id,
            "queue_position": str(queue_position),
            "company_name": row["company_name"],
            "company_slug": row["company_slug"],
            "website": row["website"],
            "yc_directory_url": row["yc_directory_url"],
            "previous_trackability": row["trackability"],
            "previous_board_type": row["detected_board_type"],
            "previous_selected_url": row["selected_url"],
            "recheck_trackability": "structured_board",
            "recheck_board_type": best_structured.board_type,
            "recheck_board_token": best_structured.token,
            "recheck_board_url": best_structured.board_url,
            "recheck_api_url": "",
            "recheck_confirmation_status": "detected_structured_board",
            "recheck_job_count": "0",
            "visited_pages": str(len(seen_urls)),
            "resolved_from_url": best_structured.board_url,
            "evidence": best_structured.evidence,
            "notes": ";".join(notes[:8]),
        }

    return {
        "checked_at_utc": checked_at_utc,
        "batch_id": batch_id,
        "queue_position": str(queue_position),
        "company_name": row["company_name"],
        "company_slug": row["company_slug"],
        "website": row["website"],
        "yc_directory_url": row["yc_directory_url"],
        "previous_trackability": row["trackability"],
        "previous_board_type": row["detected_board_type"],
        "previous_selected_url": row["selected_url"],
        "recheck_trackability": "unknown",
        "recheck_board_type": "",
        "recheck_board_token": "",
        "recheck_board_url": "",
        "recheck_api_url": "",
        "recheck_confirmation_status": "no_structured_board_found",
        "recheck_job_count": "0",
        "visited_pages": str(len(seen_urls)),
        "resolved_from_url": "",
        "evidence": "",
        "notes": ";".join(notes[:8]),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--batch-index", type=int, default=1)
    parser.add_argument("--company-slugs", type=str, default="")
    parser.add_argument("--batch-id", type=str, default="")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    company_slugs = [slug.strip() for slug in args.company_slugs.split(",") if slug.strip()]
    rows = select_recheck_rows(args.batch_size, args.batch_index, company_slugs)
    if not rows:
        print("No companies selected for this batch.")
        return

    batch_id = f"batch-{args.batch_index:03d}"
    if company_slugs:
        batch_id = f"slugs-{'-'.join(company_slugs)}"
    if args.batch_id:
        batch_id = args.batch_id

    checked_at_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    results: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=min(10, len(rows))) as executor:
        future_map = {
            executor.submit(recheck_company, row, batch_id, idx, checked_at_utc): row
            for idx, row in enumerate(rows, start=1)
        }
        for future in as_completed(future_map):
            results.append(future.result())

    results.sort(key=lambda row: int(row["queue_position"]))
    BATCH_DIR.mkdir(parents=True, exist_ok=True)
    output_csv = BATCH_DIR / f"{batch_id}.csv"
    output_json = BATCH_DIR / f"{batch_id}.summary.json"
    write_csv(output_csv, results)
    write_truth_outputs(results)

    summary = {
        "batch_id": batch_id,
        "company_count": len(results),
        "status_counts": dict(Counter(row["recheck_confirmation_status"] for row in results)),
        "trackability_counts": dict(Counter(row["recheck_trackability"] for row in results)),
        "companies": [
            {
                "queue_position": row["queue_position"],
                "company_name": row["company_name"],
                "previous_trackability": row["previous_trackability"],
                "recheck_trackability": row["recheck_trackability"],
                "recheck_board_type": row["recheck_board_type"],
                "recheck_confirmation_status": row["recheck_confirmation_status"],
                "recheck_job_count": row["recheck_job_count"],
            }
            for row in results
        ],
    }
    output_json.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    print(f"Selected {len(results)} companies for {batch_id}.")
    print(f"Wrote {output_csv}")
    print(f"Wrote {output_json}")
    print(f"Wrote {TRUTH_CSV}")
    print(f"Wrote {TRUTH_SUMMARY_JSON}")


if __name__ == "__main__":
    main()
