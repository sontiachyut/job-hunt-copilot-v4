#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import urllib.request
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

SOURCE_PAGE_URL = "https://www.phxfwd.org/the-list"
AIRTABLE_APP_ID = "appTfDM9hk8wUnZtQ"
AIRTABLE_EMBED_URL = (
    "https://airtable.com/embed/appTfDM9hk8wUnZtQ/shrems71Dzkb0jabm?viewControls=on"
)

CITY_PRIORITY = [
    "Tempe",
    "Chandler",
    "Mesa",
    "Gilbert",
    "Scottsdale",
    "Phoenix",
    "Glendale",
    "Peoria",
    "Queen Creek",
    "Fountain Hills",
    "Carefree",
    "Surprise",
    "Litchfield Park",
    "Anthem",
]

REQUEST_HEADERS = {
    "x-user-locale": "en",
    "x-airtable-application-id": AIRTABLE_APP_ID,
    "X-Requested-With": "XMLHttpRequest",
    "x-airtable-inter-service-client": "webClient",
    "x-time-zone": "America/Phoenix",
}

BLANK_VALUES = {"", "-", "—", "N/A", "n/a", "None", "null"}


def normalize_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "; ".join(normalize_text(item) for item in value if normalize_text(item))
    if isinstance(value, (int, float)):
        return str(value)
    text = html.unescape(str(value)).strip()
    return "" if text in BLANK_VALUES else text


def fetch_json(url: str) -> dict:
    request = urllib.request.Request(url, headers=REQUEST_HEADERS)
    with urllib.request.urlopen(request) as response:
        return json.load(response)


def is_usable_url(url: str) -> bool:
    return url.startswith("http://") or url.startswith("https://")


def is_usable_careers_page(url: str) -> bool:
    if not is_usable_url(url):
        return False
    lowered = url.casefold()
    if "linkedin.com/in/" in lowered:
        return False
    return True


def fetch_shared_view_url() -> str:
    with urllib.request.urlopen(AIRTABLE_EMBED_URL) as response:
        page_html = response.read().decode("utf-8")

    match = re.search(r'urlWithParams: "([^"]+readSharedViewData[^\\"]+)"', page_html)
    if not match:
        raise RuntimeError("Could not locate Airtable shared-view URL inside PHX FWD page.")
    return "https://airtable.com" + match.group(1).encode("utf-8").decode(
        "unicode_escape"
    )


def build_choice_maps(columns: Iterable[dict]) -> dict[str, dict[str, str]]:
    choice_maps: dict[str, dict[str, str]] = {}
    for column in columns:
        options = column.get("typeOptions") or {}
        choices = options.get("choices") or {}
        if choices:
            choice_maps[column["id"]] = {
                choice_id: choice["name"] for choice_id, choice in choices.items()
            }
    return choice_maps


def decode_row(row: dict, column_ids: dict[str, str], choice_maps: dict[str, dict[str, str]]) -> dict[str, str]:
    values = row.get("cellValuesByColumnId", {})
    decoded: dict[str, str] = {}
    for column_name, column_id in column_ids.items():
        value = values.get(column_id)
        if column_id in choice_maps and value is not None:
            value = choice_maps[column_id].get(value, value)
        decoded[column_name] = normalize_text(value)
    return decoded


def collect_rows() -> list[dict[str, str]]:
    shared_view_url = fetch_shared_view_url()
    payload = fetch_json(shared_view_url)
    table = payload["data"]["table"]
    columns = table["columns"]
    choice_maps = build_choice_maps(columns)
    column_ids = {column["name"]: column["id"] for column in columns}
    rows = [decode_row(row, column_ids, choice_maps) for row in table["rows"]]
    return rows


def select_local_companies(rows: Iterable[dict[str, str]], limit: int) -> list[dict[str, str]]:
    city_rank = {city: index for index, city in enumerate(CITY_PRIORITY)}
    deduped: dict[tuple[str, str], dict[str, str]] = {}

    for row in rows:
        city = row.get("City", "")
        company_name = row.get("Company Name", "")
        careers_page = row.get("Careers Page", "")
        if city not in city_rank or not company_name or not is_usable_careers_page(careers_page):
            continue

        key = (company_name.casefold(), city.casefold())
        current = deduped.get(key)
        if current is None or row.get("Last Modified", "") > current.get("Last Modified", ""):
            deduped[key] = row

    selected = sorted(
        deduped.values(),
        key=lambda row: (
            city_rank[row["City"]],
            row.get("Company Name", "").casefold(),
        ),
    )
    return selected[:limit]


def write_csv(path: Path, companies: list[dict[str, str]]) -> None:
    fieldnames = [
        "rank",
        "company_name",
        "city",
        "category",
        "number_of_employees",
        "description",
        "company_website",
        "careers_page",
        "company_linkedin",
        "office_address",
        "remote_hq",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for index, company in enumerate(companies, start=1):
            writer.writerow(
                {
                    "rank": index,
                    "company_name": company.get("Company Name", ""),
                    "city": company.get("City", ""),
                    "category": company.get("Category", ""),
                    "number_of_employees": company.get("Number of Employees", ""),
                    "description": company.get("Description", ""),
                    "company_website": company.get("Company Website", ""),
                    "careers_page": company.get("Careers Page", ""),
                    "company_linkedin": company.get("Company Linkedin", ""),
                    "office_address": company.get("Office Address", ""),
                    "remote_hq": company.get("Remote HQ", ""),
                }
            )


def escape_md(text: str) -> str:
    return text.replace("|", "\\|")


def write_markdown(path: Path, companies: list[dict[str, str]]) -> None:
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    lines = [
        "# Greater Phoenix Local Company List",
        "",
        f"Generated at: `{generated_at}`",
        "",
        "Selection criteria:",
        "- Source directory: PHX FWD `The List of Phoenix Software Companies`",
        "- Filtered to Greater Phoenix cities and companies with a public careers page",
        "- Ordered to favor Tempe and the East Valley before Scottsdale and Phoenix",
        "",
        f"Source links: {SOURCE_PAGE_URL} and {AIRTABLE_EMBED_URL}",
        "",
        "| # | Company | City | Category | Employees | Website | Careers |",
        "|---|---|---|---|---|---|---|",
    ]
    for index, company in enumerate(companies, start=1):
        website = company.get("Company Website", "")
        careers = company.get("Careers Page", "")
        website_cell = f"[site]({website})" if website else ""
        careers_cell = f"[careers]({careers})" if careers else ""
        lines.append(
            "| "
            + " | ".join(
                [
                    str(index),
                    escape_md(company.get("Company Name", "")),
                    escape_md(company.get("City", "")),
                    escape_md(company.get("Category", "")),
                    escape_md(company.get("Number of Employees", "")),
                    website_cell,
                    careers_cell,
                ]
            )
            + " |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export a prioritized list of local Greater Phoenix software companies."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum number of companies to export.",
    )
    parser.add_argument(
        "--output-dir",
        default="ops/local-companies",
        help="Directory for generated output files.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rows = collect_rows()
    companies = select_local_companies(rows, limit=args.limit)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    csv_path = output_dir / "greater-phoenix-software-100.csv"
    md_path = output_dir / "greater-phoenix-software-100.md"
    write_csv(csv_path, companies)
    write_markdown(md_path, companies)

    print(f"Wrote {len(companies)} companies to {csv_path}")
    print(f"Wrote {len(companies)} companies to {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
