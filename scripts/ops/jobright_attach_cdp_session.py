#!/usr/bin/env python3
"""Attach to a real Chrome window over CDP and save Jobright session artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Connect to a manually logged-in Chrome instance over the Chrome "
            "DevTools Protocol, then save Jobright storage state and "
            "personalized connection data."
        )
    )
    parser.add_argument(
        "--cdp-url",
        default="http://127.0.0.1:9222",
        help="CDP endpoint for the running Chrome instance. Default: %(default)s",
    )
    parser.add_argument(
        "--job-url",
        required=True,
        help="Jobright job URL to inspect inside the connected browser.",
    )
    parser.add_argument(
        "--storage-output",
        required=True,
        help="Path to write the captured storage_state JSON.",
    )
    parser.add_argument(
        "--connections-output",
        required=True,
        help="Path to write the extracted connection JSON.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=30,
        help="Navigation/evaluation timeout in seconds. Default: %(default)s",
    )
    return parser.parse_args()


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_parent(path_str: str) -> Path:
    path = Path(path_str).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


EXTRACT_JS = r"""
() => {
  const next = document.getElementById('__NEXT_DATA__');
  const nextData = next ? JSON.parse(next.textContent) : null;

  const firstNonEmpty = (...values) => {
    for (const value of values) {
      if (
        value !== undefined &&
        value !== null &&
        value !== '' &&
        value !== false &&
        !(Array.isArray(value) && value.length === 0)
      ) {
        return value;
      }
    }
    return null;
  };

  const walk = (obj, fn, seen = new WeakSet()) => {
    if (!obj || typeof obj !== 'object' || seen.has(obj)) return;
    seen.add(obj);
    fn(obj);
    if (Array.isArray(obj)) {
      for (const item of obj) walk(item, fn, seen);
      return;
    }
    for (const value of Object.values(obj)) walk(value, fn, seen);
  };

  const findFirstKey = (root, key) => {
    let found = null;
    walk(root, candidate => {
      if (found !== null) return;
      if (candidate && typeof candidate === 'object' && !Array.isArray(candidate) && key in candidate) {
        found = candidate[key];
      }
    });
    return found;
  };

  let jobResult = null;
  walk(nextData, candidate => {
    if (jobResult) return;
    if (
      candidate &&
      typeof candidate === 'object' &&
      !Array.isArray(candidate) &&
      ('socialConnections' in candidate || 'personalSocialConnections' in candidate)
    ) {
      jobResult = candidate;
    }
  });

  return {
    extractedAt: new Date().toISOString(),
    pageTitle: document.title,
    url: location.href,
    jobSummary: {
      title: firstNonEmpty(jobResult?.title, jobResult?.jobTitle, findFirstKey(nextData, 'jobTitle')),
      company: firstNonEmpty(
        jobResult?.companyName,
        jobResult?.company,
        jobResult?.companyTitle,
        findFirstKey(nextData, 'companyName')
      ),
      location: firstNonEmpty(
        jobResult?.location,
        jobResult?.locationName,
        jobResult?.jobLocation,
        findFirstKey(nextData, 'companyLocation')
      ),
      salary: firstNonEmpty(
        jobResult?.salary,
        jobResult?.salaryText,
        jobResult?.compensationText,
        jobResult?.salaryDesc,
        findFirstKey(nextData, 'salaryDesc')
      )
    },
    socialConnections: findFirstKey(nextData, 'socialConnections'),
    personalSocialConnections: findFirstKey(nextData, 'personalSocialConnections')
  };
}
"""


def build_storage_state_fallback(context: Any, pages: list[Any]) -> dict[str, Any]:
    cookies = context.cookies()
    origins: list[dict[str, Any]] = []
    seen: set[str] = set()

    for page in pages:
        try:
            origin = page.evaluate("location.origin")
        except Exception:
            continue
        if not origin or origin in seen:
            continue
        seen.add(origin)
        try:
            local_storage = page.evaluate(
                "() => Object.entries(localStorage).map(([name, value]) => ({ name, value }))"
            )
        except Exception:
            local_storage = []
        origins.append({"origin": origin, "localStorage": local_storage})

    return {"cookies": cookies, "origins": origins}


def main() -> int:
    args = parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.stderr.write(
            "Playwright is not installed.\n"
            "Install with:\n"
            "  python3 -m pip install playwright\n"
            "  python3 -m playwright install chromium\n"
        )
        return 2

    storage_output = ensure_parent(args.storage_output)
    connections_output = ensure_parent(args.connections_output)

    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(args.cdp_url)
        if not browser.contexts:
            sys.stderr.write(
                f"No browser contexts found at {args.cdp_url}. "
                "Launch Chrome with --remote-debugging-port first.\n"
            )
            return 3

        context = browser.contexts[0]
        page = None
        for candidate in context.pages:
            if candidate.url.startswith(args.job_url):
                page = candidate
                break

        if page is None:
            page = context.new_page()
            page.goto(args.job_url, wait_until="domcontentloaded", timeout=args.timeout_seconds * 1000)
        else:
            page.bring_to_front()
            if not page.url.startswith(args.job_url):
                page.goto(args.job_url, wait_until="domcontentloaded", timeout=args.timeout_seconds * 1000)

        page.wait_for_timeout(1500)
        page.wait_for_function(
            "() => !!document.getElementById('__NEXT_DATA__')",
            timeout=args.timeout_seconds * 1000,
        )

        extracted = page.evaluate(EXTRACT_JS)
        extracted["capturedAt"] = now_utc()
        extracted["jobUrl"] = args.job_url

        try:
            state = context.storage_state()
        except Exception:
            state = build_storage_state_fallback(context, context.pages)

        storage_output.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        connections_output.write_text(json.dumps(extracted, indent=2) + "\n", encoding="utf-8")
        browser.close()

    print(f"Wrote storage state to {storage_output}")
    print(f"Wrote connections snapshot to {connections_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
