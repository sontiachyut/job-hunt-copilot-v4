#!/usr/bin/env python3
"""Extract Jobright connection data from a public or authenticated session."""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from datetime import datetime, timezone
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any

import requests


NEXT_DATA_RE = re.compile(
    r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)
TITLE_RE = re.compile(r"<title>(.*?)</title>", re.DOTALL | re.IGNORECASE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch a Jobright job page and extract connection-related data. "
            "If a Playwright storage_state is supplied, the script first tries "
            "a lightweight requests-based HTML fetch and can optionally fall "
            "back to Playwright for authenticated page rendering."
        )
    )
    parser.add_argument("--job-url", required=True, help="Jobright job detail URL.")
    parser.add_argument(
        "--storage-state",
        help="Optional Playwright storage_state JSON captured from a logged-in Jobright session.",
    )
    parser.add_argument(
        "--output",
        help="Optional output JSON path. If omitted, the result is printed to stdout.",
    )
    parser.add_argument(
        "--playwright-fallback",
        action="store_true",
        help=(
            "If personalized data is missing from the requests fetch, open the "
            "page in Playwright with the supplied storage_state and extract again."
        ),
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=30,
        help="HTTP/browser timeout in seconds. Default: %(default)s",
    )
    return parser.parse_args()


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_storage_state(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    return json.loads(Path(path).expanduser().read_text(encoding="utf-8"))


def build_cookie_jar(storage_state: dict[str, Any] | None) -> CookieJar:
    jar = requests.cookies.RequestsCookieJar()
    if not storage_state:
        return jar

    for cookie in storage_state.get("cookies", []):
        if "name" not in cookie or "value" not in cookie:
            continue
        jar.set(
            name=cookie["name"],
            value=cookie["value"],
            domain=cookie.get("domain"),
            path=cookie.get("path", "/"),
        )
    return jar


def extract_title(html_text: str) -> str | None:
    match = TITLE_RE.search(html_text)
    if not match:
        return None
    return html.unescape(match.group(1).strip())


def extract_next_data(html_text: str) -> dict[str, Any] | None:
    match = NEXT_DATA_RE.search(html_text)
    if not match:
        return None
    return json.loads(html.unescape(match.group(1)))


def iter_dicts(obj: Any):
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from iter_dicts(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from iter_dicts(item)


def find_first_key(obj: Any, key: str) -> Any | None:
    for candidate in iter_dicts(obj):
        if key in candidate:
            return candidate[key]
    return None


def find_job_result(obj: Any) -> dict[str, Any] | None:
    for candidate in iter_dicts(obj):
        if not isinstance(candidate, dict):
            continue
        if "socialConnections" in candidate or "personalSocialConnections" in candidate:
            return candidate
    return None


def first_non_empty(*values: Any) -> Any | None:
    for value in values:
        if value not in (None, "", [], {}, False):
            return value
    return None


def normalize_connection_item(item: Any) -> Any:
    if not isinstance(item, dict):
        return item

    preferred_keys = (
        "name",
        "fullName",
        "title",
        "positionTitle",
        "headline",
        "linkedinUrl",
        "workEmail",
        "email",
        "schoolName",
        "companyName",
    )
    normalized: dict[str, Any] = {}

    for key in preferred_keys:
        value = item.get(key)
        if value not in (None, ""):
            normalized[key] = value

    for nested_key in ("school", "company"):
        nested = item.get(nested_key)
        if isinstance(nested, dict):
            nested_scalars = {
                key: value
                for key, value in nested.items()
                if isinstance(value, (str, int, float, bool)) and value not in ("", None)
            }
            if nested_scalars:
                normalized[nested_key] = nested_scalars

    if normalized:
        return normalized
    return item


def normalize_connection_block(value: Any) -> Any:
    if isinstance(value, list):
        return [normalize_connection_item(item) for item in value]
    if isinstance(value, dict):
        return {key: normalize_connection_block(item) for key, item in value.items()}
    return value


def summarize_job_result(job_result: dict[str, Any] | None, next_data: dict[str, Any] | None) -> dict[str, Any]:
    if not job_result and not next_data:
        return {}

    company = first_non_empty(
        job_result.get("companyName") if job_result else None,
        job_result.get("company") if job_result else None,
        job_result.get("companyTitle") if job_result else None,
        find_first_key(next_data, "companyName"),
    )
    if isinstance(company, dict):
        company = first_non_empty(company.get("name"), company.get("companyName"))

    location = first_non_empty(
        job_result.get("location") if job_result else None,
        job_result.get("locationName") if job_result else None,
        job_result.get("jobLocation") if job_result else None,
        find_first_key(next_data, "companyLocation"),
    )
    if isinstance(location, dict):
        location = first_non_empty(
            location.get("name"),
            location.get("displayName"),
            location.get("locationName"),
        )

    return {
        "title": first_non_empty(
            job_result.get("title") if job_result else None,
            job_result.get("jobTitle") if job_result else None,
            find_first_key(next_data, "jobTitle"),
        ),
        "company": company,
        "location": location,
        "salary": first_non_empty(
            job_result.get("salary") if job_result else None,
            job_result.get("salaryText") if job_result else None,
            job_result.get("compensationText") if job_result else None,
            job_result.get("salaryDesc") if job_result else None,
            find_first_key(next_data, "salaryDesc"),
        ),
        "original_job_post_url": first_non_empty(
            job_result.get("originalJobPostUrl") if job_result else None,
            job_result.get("sourceUrl") if job_result else None,
            job_result.get("applyUrl") if job_result else None,
            find_first_key(next_data, "jobtargetEasyapply"),
        ),
    }


def extract_from_next_data(next_data: dict[str, Any] | None) -> dict[str, Any]:
    if not next_data:
        return {
            "job_summary": {},
            "social_connections": None,
            "personal_social_connections": None,
            "find_more_links": {},
        }

    job_result = find_job_result(next_data)
    social_connections = find_first_key(next_data, "socialConnections")
    personal_social_connections = find_first_key(next_data, "personalSocialConnections")

    links = {}
    for candidate in iter_dicts(next_data):
        if not isinstance(candidate, dict):
            continue
        value = candidate.get("linkedinUrl")
        if isinstance(value, str) and "linkedin.com/search/results/people" in value:
            links.setdefault("linkedin_search_links", [])
            if value not in links["linkedin_search_links"]:
                links["linkedin_search_links"].append(value)

    return {
        "job_summary": summarize_job_result(job_result, next_data),
        "social_connections": normalize_connection_block(social_connections),
        "personal_social_connections": normalize_connection_block(personal_social_connections),
        "find_more_links": links,
    }


def fetch_html(job_url: str, storage_state: dict[str, Any] | None, timeout_seconds: int) -> dict[str, Any]:
    session = requests.Session()
    session.cookies = build_cookie_jar(storage_state)
    response = session.get(
        job_url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/137.0.0.0 Safari/537.36"
            )
        },
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    return {
        "mode": "requests",
        "http_status": response.status_code,
        "html": response.text,
    }


def extract_with_playwright(job_url: str, storage_state_path: str, timeout_seconds: int) -> dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright is required for --playwright-fallback. "
            "Install with `python3 -m pip install playwright` and "
            "`python3 -m playwright install chromium`."
        ) from exc

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(storage_state=storage_state_path)
        page = context.new_page()
        page.goto(job_url, wait_until="domcontentloaded", timeout=timeout_seconds * 1000)
        html_text = page.content()
        browser.close()

    return {
        "mode": "playwright",
        "http_status": 200,
        "html": html_text,
    }


def build_result(
    job_url: str,
    fetch_result: dict[str, Any],
    storage_state_path: str | None,
) -> dict[str, Any]:
    html_text = fetch_result["html"]
    next_data = extract_next_data(html_text)
    extraction = extract_from_next_data(next_data)
    return {
        "captured_at": now_utc(),
        "job_url": job_url,
        "storage_state_path": storage_state_path,
        "fetch": {
            "mode": fetch_result["mode"],
            "http_status": fetch_result["http_status"],
            "page_title": extract_title(html_text),
            "next_data_found": next_data is not None,
        },
        **extraction,
    }


def write_output(result: dict[str, Any], output_path: str | None) -> None:
    payload = json.dumps(result, indent=2, ensure_ascii=True) + "\n"
    if output_path:
        path = Path(output_path).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")
        print(f"Wrote {path}")
        return
    sys.stdout.write(payload)


def main() -> int:
    args = parse_args()
    storage_state = load_storage_state(args.storage_state)

    fetch_result = fetch_html(args.job_url, storage_state, args.timeout_seconds)
    result = build_result(args.job_url, fetch_result, args.storage_state)

    if (
        args.playwright_fallback
        and args.storage_state
        and not result.get("personal_social_connections")
    ):
        fetch_result = extract_with_playwright(
            args.job_url,
            args.storage_state,
            args.timeout_seconds,
        )
        result = build_result(args.job_url, fetch_result, args.storage_state)

    write_output(result, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
