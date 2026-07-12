from __future__ import annotations

import json
import re
import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable
from xml.sax.saxutils import escape


REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = REPO_ROOT / "assets" / "readme"
DB_PATH = REPO_ROOT / "job_hunt_copilot.db"
TRACE_MATRIX_PATH = REPO_ROOT / "build-agent" / "reports" / "ba-10-acceptance-trace-matrix.md"


@dataclass(frozen=True)
class MetricCard:
    label: str
    value: str
    note: str
    accent: str


def _tracked_code_stats() -> dict[str, int]:
    repo_files = subprocess.check_output(
        ["git", "ls-files"],
        text=True,
        cwd=REPO_ROOT,
    ).splitlines()
    code_exts = {".py", ".sql"}
    stats = {
        "tracked_code_total": 0,
        "source_lines": 0,
        "test_lines": 0,
        "python_lines": 0,
        "sql_lines": 0,
    }
    for rel_path in repo_files:
        path = REPO_ROOT / rel_path
        if not path.is_file() or path.suffix.lower() not in code_exts:
            continue
        try:
            line_count = sum(1 for _ in path.open("r", encoding="utf-8", errors="ignore"))
        except OSError:
            continue
        stats["tracked_code_total"] += line_count
        if rel_path.startswith("tests/"):
            stats["test_lines"] += line_count
        else:
            stats["source_lines"] += line_count
        if path.suffix.lower() == ".py":
            stats["python_lines"] += line_count
        else:
            stats["sql_lines"] += line_count
    return stats


def _acceptance_stats() -> dict[str, int] | None:
    if not TRACE_MATRIX_PATH.exists():
        return None
    text = TRACE_MATRIX_PATH.read_text(encoding="utf-8")
    scenario_match = re.search(r"Scenario count:\s*`(?P<count>\d+)`", text)
    implemented_match = re.search(r"`implemented`:\s*`(?P<count>\d+)`", text)
    partial_match = re.search(r"`partial`:\s*`(?P<count>\d+)`", text)
    if scenario_match is None:
        return None
    return {
        "scenario_count": int(scenario_match.group("count")),
        "implemented_count": int(implemented_match.group("count")) if implemented_match else 0,
        "partial_count": int(partial_match.group("count")) if partial_match else 0,
    }


def _runtime_stats() -> dict[str, int] | None:
    if not DB_PATH.exists():
        return None
    connection = sqlite3.connect(DB_PATH)
    try:
        return {
            "companies_tracked": _scalar(
                connection,
                """
                SELECT COUNT(DISTINCT LOWER(TRIM(company_name)))
                FROM job_postings
                WHERE company_name IS NOT NULL AND TRIM(company_name) <> ''
                """,
            ),
            "job_postings": _scalar(connection, "SELECT COUNT(*) FROM job_postings"),
            "contacts": _scalar(connection, "SELECT COUNT(*) FROM contacts"),
            "pipeline_runs": _scalar(connection, "SELECT COUNT(*) FROM pipeline_runs"),
            "companies_reached": _scalar(
                connection,
                """
                SELECT COUNT(DISTINCT LOWER(TRIM(jp.company_name)))
                FROM job_postings jp
                JOIN outreach_messages om
                  ON om.job_posting_id = jp.job_posting_id
                 AND om.message_status = 'sent'
                WHERE jp.company_name IS NOT NULL AND TRIM(jp.company_name) <> ''
                """,
            ),
        }
    finally:
        connection.close()


def _scalar(connection: sqlite3.Connection, query: str) -> int:
    row = connection.execute(query).fetchone()
    return int(row[0]) if row is not None and row[0] is not None else 0


def _format_int(value: int) -> str:
    return f"{value:,}"


def _metric_cards(snapshot: dict[str, object]) -> list[MetricCard]:
    code_stats = snapshot["code"]  # type: ignore[index]
    acceptance_stats = snapshot["acceptance"] or {}  # type: ignore[index]
    runtime_stats = snapshot["runtime"] or {}  # type: ignore[index]
    return [
        MetricCard(
            label="Tracked code",
            value=_format_int(int(code_stats["tracked_code_total"])),
            note="Python and SQL tracked in git",
            accent="#2563EB",
        ),
        MetricCard(
            label="Acceptance scenarios",
            value=_format_int(int(acceptance_stats.get("scenario_count", 0))),
            note="Spec-backed behavior checks",
            accent="#0F766E",
        ),
        MetricCard(
            label="Companies tracked",
            value=_format_int(int(runtime_stats.get("companies_tracked", 0))),
            note="Historical runtime coverage",
            accent="#7C3AED",
        ),
        MetricCard(
            label="Job postings",
            value=_format_int(int(runtime_stats.get("job_postings", 0))),
            note="Posting records in canonical state",
            accent="#EA580C",
        ),
        MetricCard(
            label="Contacts stored",
            value=_format_int(int(runtime_stats.get("contacts", 0))),
            note="Contact graph accumulated by the system",
            accent="#DC2626",
        ),
        MetricCard(
            label="Companies reached",
            value=_format_int(int(runtime_stats.get("companies_reached", 0))),
            note="Distinct companies with sent outreach",
            accent="#0891B2",
        ),
    ]


def _render_svg(snapshot: dict[str, object], cards: Iterable[MetricCard]) -> str:
    generated_at = escape(str(snapshot["generated_at"]))
    card_list = list(cards)
    width = 1400
    height = 760
    card_width = 400
    card_height = 180
    left_margin = 80
    top_margin = 180
    gap_x = 40
    gap_y = 36
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
        '<title id="title">Job Hunt Copilot v4 project snapshot</title>',
        '<desc id="desc">Six-card metrics summary covering code size, acceptance depth, and runtime history.</desc>',
        '<rect width="1400" height="760" rx="28" fill="#F8FAFC"/>',
        '<rect x="32" y="32" width="1336" height="696" rx="24" fill="white" stroke="#E2E8F0" stroke-width="2"/>',
        '<text x="80" y="104" font-family="Arial, Helvetica, sans-serif" font-size="42" font-weight="700" fill="#0F172A">Project Snapshot</text>',
        '<text x="80" y="142" font-family="Arial, Helvetica, sans-serif" font-size="22" fill="#475569">Generated from tracked repo files, the acceptance matrix, and local runtime history.</text>',
    ]
    for index, card in enumerate(card_list):
        row = index // 3
        col = index % 3
        x = left_margin + col * (card_width + gap_x)
        y = top_margin + row * (card_height + gap_y)
        parts.extend(
            [
                f'<rect x="{x}" y="{y}" width="{card_width}" height="{card_height}" rx="24" fill="#FFFFFF" stroke="#E2E8F0" stroke-width="2"/>',
                f'<rect x="{x}" y="{y}" width="{card_width}" height="10" rx="24" fill="{card.accent}"/>',
                f'<text x="{x + 28}" y="{y + 54}" font-family="Arial, Helvetica, sans-serif" font-size="18" font-weight="700" fill="#334155">{escape(card.label)}</text>',
                f'<text x="{x + 28}" y="{y + 112}" font-family="Arial, Helvetica, sans-serif" font-size="46" font-weight="700" fill="#0F172A">{escape(card.value)}</text>',
                f'<text x="{x + 28}" y="{y + 148}" font-family="Arial, Helvetica, sans-serif" font-size="18" fill="#64748B">{escape(card.note)}</text>',
            ]
        )
    parts.extend(
        [
            f'<text x="80" y="700" font-family="Arial, Helvetica, sans-serif" font-size="18" fill="#64748B">Snapshot generated: {generated_at}</text>',
            '</svg>',
        ]
    )
    return "\n".join(parts)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    snapshot = {
        "generated_at": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z"),
        "code": _tracked_code_stats(),
        "acceptance": _acceptance_stats(),
        "runtime": _runtime_stats(),
    }
    cards = _metric_cards(snapshot)
    (OUTPUT_DIR / "runtime-snapshot.json").write_text(
        json.dumps(snapshot, indent=2) + "\n",
        encoding="utf-8",
    )
    (OUTPUT_DIR / "runtime-snapshot.svg").write_text(
        _render_svg(snapshot, cards),
        encoding="utf-8",
    )
    print(f"Wrote {OUTPUT_DIR / 'runtime-snapshot.json'}")
    print(f"Wrote {OUTPUT_DIR / 'runtime-snapshot.svg'}")


if __name__ == "__main__":
    main()
