#!/usr/bin/env python3
"""Attach to a real Chrome window over CDP and save Jobright session artifacts."""

from __future__ import annotations

import argparse
import asyncio
import json
import urllib.parse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
import websockets


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


LOCAL_STORAGE_JS = r"""
() => {
  try {
    return Object.entries(localStorage).map(([name, value]) => ({ name, value }));
  } catch (error) {
    return [];
  }
}
"""


def http_get_json(url: str) -> Any:
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return response.json()


def http_put_json(url: str) -> Any:
    response = requests.put(url, timeout=30)
    response.raise_for_status()
    return response.json()


def list_tabs(cdp_url: str) -> list[dict[str, Any]]:
    return http_get_json(f"{cdp_url.rstrip('/')}/json/list")


def get_or_create_tab(cdp_url: str, job_url: str) -> dict[str, Any]:
    for tab in list_tabs(cdp_url):
        if tab.get("type") == "page" and tab.get("url", "").startswith(job_url):
            return tab

    quoted = urllib.parse.quote(job_url, safe="")
    return http_put_json(f"{cdp_url.rstrip('/')}/json/new?{quoted}")


async def cdp_call(
    ws: websockets.ClientConnection,
    method: str,
    params: dict[str, Any] | None = None,
    request_id_ref: list[int] | None = None,
) -> dict[str, Any]:
    if request_id_ref is None:
        request_id_ref = [0]
    request_id_ref[0] += 1
    request_id = request_id_ref[0]
    payload: dict[str, Any] = {"id": request_id, "method": method}
    if params:
        payload["params"] = params
    await ws.send(json.dumps(payload))
    while True:
        raw = await ws.recv()
        message = json.loads(raw)
        if message.get("id") == request_id:
            return message


def get_result_value(response: dict[str, Any]) -> Any:
    return response.get("result", {}).get("result", {}).get("value")


async def capture_via_raw_cdp(
    ws_url: str,
    job_url: str,
    timeout_seconds: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    async with websockets.connect(ws_url, max_size=10_000_000) as ws:
        request_id_ref = [0]

        await cdp_call(ws, "Page.enable", request_id_ref=request_id_ref)
        await cdp_call(ws, "Runtime.enable", request_id_ref=request_id_ref)
        await cdp_call(ws, "Network.enable", request_id_ref=request_id_ref)

        state = ""
        for _ in range(timeout_seconds):
            response = await cdp_call(
                ws,
                "Runtime.evaluate",
                {"expression": "document.readyState", "returnByValue": True},
                request_id_ref=request_id_ref,
            )
            state = get_result_value(response) or ""
            if state == "complete":
                break
            await asyncio.sleep(1)

        extracted_response = await cdp_call(
            ws,
            "Runtime.evaluate",
            {"expression": EXTRACT_JS, "returnByValue": True},
            request_id_ref=request_id_ref,
        )
        extracted = get_result_value(extracted_response) or {}
        extracted["capturedAt"] = now_utc()
        extracted["jobUrl"] = job_url

        cookies_response = await cdp_call(
            ws,
            "Network.getCookies",
            {"urls": [job_url]},
            request_id_ref=request_id_ref,
        )
        cookies = cookies_response.get("result", {}).get("cookies", [])

        origin_response = await cdp_call(
            ws,
            "Runtime.evaluate",
            {"expression": "location.origin", "returnByValue": True},
            request_id_ref=request_id_ref,
        )
        origin = get_result_value(origin_response)

        local_storage_response = await cdp_call(
            ws,
            "Runtime.evaluate",
            {"expression": LOCAL_STORAGE_JS, "returnByValue": True},
            request_id_ref=request_id_ref,
        )
        local_storage = get_result_value(local_storage_response) or []

        storage_state = {
            "cookies": cookies,
            "origins": [{"origin": origin, "localStorage": local_storage}] if origin else [],
        }

        return extracted, storage_state


def capture_with_playwright(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(args.cdp_url)
        if not browser.contexts:
            raise RuntimeError(
                f"No browser contexts found at {args.cdp_url}. "
                "Launch Chrome with --remote-debugging-port first."
            )

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
        storage_state = context.storage_state()
        browser.close()
        return extracted, storage_state


def main() -> int:
    args = parse_args()

    storage_output = ensure_parent(args.storage_output)
    connections_output = ensure_parent(args.connections_output)

    extracted: dict[str, Any]
    state: dict[str, Any]
    playwright_error: Exception | None = None

    try:
        extracted, state = capture_with_playwright(args)
    except ImportError as error:
        playwright_error = error
    except Exception as error:
        playwright_error = error

    if playwright_error is not None:
        tab = get_or_create_tab(args.cdp_url, args.job_url)
        ws_url = tab.get("webSocketDebuggerUrl")
        if not ws_url:
            sys.stderr.write(f"Could not resolve a page websocket from {args.cdp_url}.\n")
            if isinstance(playwright_error, ImportError):
                sys.stderr.write(
                    "Playwright is not installed.\n"
                    "Install with:\n"
                    "  python3 -m pip install playwright\n"
                    "  python3 -m playwright install chromium\n"
                )
            else:
                sys.stderr.write(f"Playwright CDP attach failed: {playwright_error}\n")
            return 2

        extracted, state = asyncio.run(capture_via_raw_cdp(ws_url, args.job_url, args.timeout_seconds))

    storage_output.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    connections_output.write_text(json.dumps(extracted, indent=2) + "\n", encoding="utf-8")

    print(f"Wrote storage state to {storage_output}")
    print(f"Wrote connections snapshot to {connections_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
