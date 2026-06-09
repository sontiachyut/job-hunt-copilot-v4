#!/usr/bin/env python3

from __future__ import annotations

import csv
import json
import re
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import quote, urljoin, urlparse

import requests

ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT / "ops" / "company-watchlists"
OUTPUT_CSV = OUTPUT_DIR / "yc-us-hiring-trackability.csv"
OUTPUT_JSON = OUTPUT_DIR / "yc-us-hiring-trackability-summary.json"

ALGOLIA_APP = "45BWZJ1SGC"
ALGOLIA_KEY = (
    "NzllNTY5MzJiZGM2OTY2ZTQwMDEzOTNhYWZiZGRjODlhYzVkNjBmOGRjNzJiMWM4ZTU0ZDlh"
    "YTZjOTJiMjlhMWFuYWx5dGljc1RhZ3M9eWNkYyZyZXN0cmljdEluZGljZXM9WUNDb21wYW55X3"
    "Byb2R1Y3Rpb24lMkNZQ0NvbXBhbnlfQnlfTGF1bmNoX0RhdGVfcHJvZHVjdGlvbiZ0YWdGaWx0"
    "ZXJzPSU1QiUyMnljZGNfcHVibGljJTIyJTVE"
)
ALGOLIA_URL = f"https://{ALGOLIA_APP}-dsn.algolia.net/1/indexes/YCCompany_production/query"
ALGOLIA_HEADERS = {
    "X-Algolia-API-Key": ALGOLIA_KEY,
    "X-Algolia-Application-Id": ALGOLIA_APP,
    "Content-Type": "application/json",
}

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
    "/company/careers",
    "/company/careers/",
    "/about/careers",
    "/about/careers/",
    "/join-us",
    "/join-us/",
    "/job-openings",
    "/job-openings/",
    "/open-positions",
    "/open-positions/",
]

ANCHOR_RE = re.compile(
    r"<a\b[^>]*href=[\"'](?P<href>[^\"']+)[\"'][^>]*>(?P<text>.*?)</a>",
    re.IGNORECASE | re.DOTALL,
)
TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class BoardPattern:
    board_type: str
    trackability: str
    evidence_patterns: tuple[str, ...]


BOARD_PATTERNS: tuple[BoardPattern, ...] = (
    BoardPattern("greenhouse", "api_native", ("greenhouse.io", "boards-api.greenhouse.io")),
    BoardPattern("lever", "api_native", ("jobs.lever.co", "lever.co")),
    BoardPattern("ashby", "api_native", ("jobs.ashbyhq.com", "ashbyhq.com")),
    BoardPattern("workable", "api_native", ("apply.workable.com", "workable.com")),
    BoardPattern("smartrecruiters", "api_native", ("smartrecruiters.com", "api.smartrecruiters.com")),
    BoardPattern("rippling", "structured_board", ("ats.rippling.com", "ripplingcdn.com")),
    BoardPattern("jobvite", "structured_board", ("jobs.jobvite.com", "jobvite.com")),
    BoardPattern("icims", "structured_board", ("icims.com", "icims")),
    BoardPattern("workday", "structured_board", ("myworkdayjobs.com", "workday")),
    BoardPattern("ukg_ultipro", "structured_board", ("ultipro.com", "ukg", "recruiting.ultipro.com")),
    BoardPattern("paycom", "structured_board", ("paycomonline.net",)),
    BoardPattern("bamboohr", "structured_board", ("bamboohr.com",)),
    BoardPattern("recruitee", "structured_board", ("recruitee.com",)),
    BoardPattern("comeet", "structured_board", ("comeet.co",)),
    BoardPattern("breezy", "structured_board", ("breezy.hr",)),
    BoardPattern("teamtailor", "structured_board", ("teamtailor.com",)),
    BoardPattern("jazzhr", "structured_board", ("applytojob.com", "resumator", "jazzhr.com")),
    BoardPattern("vivahr", "structured_board", ("avahr.com", "vivahr.com", "jobs.vivahr.com")),
    BoardPattern("notion", "custom_page", ("notion.site",)),
    BoardPattern("linkedin_jobs", "custom_page", ("linkedin.com/jobs",)),
)

CSV_FIELDNAMES = [
    "company_name",
    "company_slug",
    "website",
    "yc_directory_url",
    "all_locations",
    "regions",
    "is_hiring",
    "detected_board_type",
    "trackability",
    "selected_url",
    "evidence",
]


_session_local = threading.local()


def session() -> requests.Session:
    sess = getattr(_session_local, "session", None)
    if sess is None:
        sess = requests.Session()
        sess.headers.update(REQUEST_HEADERS)
        _session_local.session = sess
    return sess


def clean_text(text: str) -> str:
    return SPACE_RE.sub(" ", TAG_RE.sub(" ", text)).strip()


def hostname(url: str) -> str:
    return urlparse(url).netloc.casefold()


def detect_board(url: str, html: str) -> tuple[str, str, str]:
    haystack = f"{url}\n{html}".casefold()
    for pattern in BOARD_PATTERNS:
        for evidence_pattern in pattern.evidence_patterns:
            if evidence_pattern.casefold() in haystack:
                return pattern.board_type, pattern.trackability, evidence_pattern
    return "", "", ""


def get_url(url: str) -> tuple[str, str]:
    response = session().get(url, timeout=15, allow_redirects=True)
    response.raise_for_status()
    content_type = response.headers.get("content-type", "").casefold()
    if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
        return response.url, ""
    return response.url, response.text[:500_000]


def score_link(base_host: str, href: str, text: str) -> int:
    href_lower = href.casefold()
    text_lower = text.casefold()

    if href_lower.startswith(("mailto:", "tel:", "javascript:")):
        return -1000
    if any(domain in href_lower for domain in ["facebook.com", "instagram.com", "twitter.com", "x.com"]):
        return -1000

    score = 0
    if any(keyword in text_lower for keyword in ["careers", "jobs", "open positions", "job openings", "join us", "we're hiring", "hiring"]):
        score += 80
    if any(keyword in href_lower for keyword in ["/careers", "/jobs", "job-openings", "open-positions", "join-us", "hiring"]):
        score += 60
    if any(pattern.board_type in href_lower or any(e in href_lower for e in pattern.evidence_patterns) for pattern in BOARD_PATTERNS):
        score += 70
    if hostname(href) == base_host:
        score += 20
    return score


def extract_candidate_links(base_url: str, html: str) -> list[str]:
    base_host = hostname(base_url)
    scored: list[tuple[int, str]] = []
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
            scored.append((score, full_url))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [url for _, url in scored[:8]]


def build_path_candidates(base_url: str) -> list[str]:
    parsed = urlparse(base_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    return [origin + path for path in COMMON_CAREERS_PATHS]


def fetch_all_yc_us_hiring_companies() -> list[dict]:
    facet_params = (
        "query=&hitsPerPage=0&filters="
        'regions%3A%22United%20States%20of%20America%22%20AND%20isHiring%3Atrue'
        "&facets=%5B%22industry%22%5D&maxValuesPerFacet=100"
    )
    facet_response = requests.post(
        ALGOLIA_URL,
        headers=ALGOLIA_HEADERS,
        json={"params": facet_params},
        timeout=30,
    )
    facet_response.raise_for_status()
    facet_payload = facet_response.json()
    industries = sorted(facet_payload.get("facets", {}).get("industry", {}).keys())

    companies_by_id: dict[str, dict] = {}
    hits_per_page = 500

    for industry in industries:
        page = 0
        encoded_industry = quote(industry, safe="")
        while True:
            params = (
                "query=&hitsPerPage="
                f"{hits_per_page}&page={page}&filters="
                'regions%3A%22United%20States%20of%20America%22%20AND%20isHiring%3Atrue'
                f'%20AND%20industry%3A%22{encoded_industry}%22'
            )
            response = requests.post(
                ALGOLIA_URL,
                headers=ALGOLIA_HEADERS,
                json={"params": params},
                timeout=30,
            )
            response.raise_for_status()
            payload = response.json()
            for hit in payload["hits"]:
                companies_by_id[hit["objectID"]] = hit
            if page + 1 >= payload["nbPages"]:
                break
            page += 1

    return list(companies_by_id.values())


def classify_company(company: dict) -> dict[str, str]:
    website = (company.get("website") or "").strip()
    result = {
        "company_name": company["name"],
        "company_slug": company["slug"],
        "website": website,
        "yc_directory_url": f"https://www.ycombinator.com/companies/{company['slug']}",
        "all_locations": company.get("all_locations", ""),
        "regions": ";".join(company.get("regions", [])),
        "is_hiring": str(company.get("isHiring", False)).lower(),
        "detected_board_type": "",
        "trackability": "unknown",
        "selected_url": "",
        "evidence": "",
    }

    if not website.startswith(("http://", "https://")):
        result["trackability"] = "unknown"
        result["evidence"] = "missing_or_invalid_website"
        return result

    try:
        home_url, home_html = get_url(website)
    except Exception as exc:  # pragma: no cover - network variance
        result["trackability"] = "unknown"
        result["selected_url"] = website
        result["evidence"] = f"homepage_fetch_failed:{type(exc).__name__}"
        return result

    board_type, trackability, evidence = detect_board(home_url, home_html)
    if board_type:
        result["detected_board_type"] = board_type
        result["trackability"] = trackability
        result["selected_url"] = home_url
        result["evidence"] = evidence
        return result

    candidates = extract_candidate_links(home_url, home_html)
    if not candidates:
        candidates = build_path_candidates(home_url)

    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            candidate_url, candidate_html = get_url(candidate)
        except Exception:
            continue

        board_type, trackability, evidence = detect_board(candidate_url, candidate_html)
        if board_type:
            result["detected_board_type"] = board_type
            result["trackability"] = trackability
            result["selected_url"] = candidate_url
            result["evidence"] = evidence
            return result

        if any(keyword in candidate_url.casefold() for keyword in ["/careers", "/jobs", "job-openings", "open-positions", "join-us"]):
            result["selected_url"] = candidate_url
            result["trackability"] = "custom_page"
            result["evidence"] = "custom_careers_page"

    if not result["selected_url"]:
        result["selected_url"] = home_url
        result["evidence"] = "no_careers_surface_detected"

    return result


def write_outputs(rows: list[dict[str, str]]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    trackability_counts = Counter(row["trackability"] for row in rows)
    board_counts = Counter(row["detected_board_type"] for row in rows if row["detected_board_type"])
    summary = {
        "total_companies": len(rows),
        "trackability_counts": dict(trackability_counts),
        "board_counts": dict(board_counts.most_common()),
    }
    OUTPUT_JSON.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    companies = fetch_all_yc_us_hiring_companies()

    results: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=24) as executor:
        future_map = {executor.submit(classify_company, company): company for company in companies}
        for future in as_completed(future_map):
            results.append(future.result())

    results.sort(key=lambda row: row["company_name"].casefold())
    write_outputs(results)

    structured_total = sum(
        1 for row in results if row["trackability"] in {"api_native", "structured_board"}
    )
    print(f"Fetched {len(companies)} YC US hiring companies.")
    print(f"Structured-trackable companies: {structured_total}")
    print(f"Wrote {OUTPUT_CSV}")
    print(f"Wrote {OUTPUT_JSON}")


if __name__ == "__main__":
    main()
