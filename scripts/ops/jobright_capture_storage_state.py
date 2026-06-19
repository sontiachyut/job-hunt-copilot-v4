#!/usr/bin/env python3
"""Capture a reusable Playwright storage state for an authenticated Jobright session."""

from __future__ import annotations

import argparse
import json
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Launch a headed browser, let a human log into Jobright once, "
            "then save Playwright storage_state JSON for later scripted fetches."
        )
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Path to write the Playwright storage_state JSON.",
    )
    parser.add_argument(
        "--start-url",
        default="https://jobright.ai/",
        help="Initial URL to open before manual login. Default: %(default)s",
    )
    parser.add_argument(
        "--job-url",
        help=(
            "Optional Jobright job URL to open after the start page. Use this "
            "if you want to confirm personalized connections are visible "
            "before saving the session."
        ),
    )
    parser.add_argument(
        "--browser",
        choices=("chromium", "firefox", "webkit"),
        default="chromium",
        help="Playwright browser engine to launch. Default: %(default)s",
    )
    return parser.parse_args()


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


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

    output_path = Path(args.output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path = output_path.with_suffix(output_path.suffix + ".meta.json")

    print(
        textwrap.dedent(
            f"""
            Jobright storage-state capture
            Output: {output_path}

            What to do:
            1. Log into Jobright in the opened browser window.
            2. If you passed --job-url, confirm the target job page shows the
               personalized connection blocks you care about.
            3. Return to this terminal and press Enter once the session is ready.

            This flow avoids local keychain scraping. It uses Playwright's
            normal storage_state export after a manual login.
            """
        ).strip()
    )

    with sync_playwright() as playwright:
        browser_type = getattr(playwright, args.browser)
        browser = browser_type.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(args.start_url, wait_until="domcontentloaded")

        if args.job_url:
            page.goto(args.job_url, wait_until="domcontentloaded")

        input("Press Enter after Jobright login is complete and the session is ready... ")

        context.storage_state(path=str(output_path))
        meta_path.write_text(
            json.dumps(
                {
                    "saved_at": now_utc(),
                    "browser": args.browser,
                    "start_url": args.start_url,
                    "job_url": args.job_url,
                    "storage_state_path": str(output_path),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        browser.close()

    print(f"Saved storage state to {output_path}")
    print(f"Saved capture metadata to {meta_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
