from __future__ import annotations

import re
from typing import Any, Mapping

from .step_01_jd_sections import normalize_jd_line


JD_POLICY_LINE_PATTERNS = (
    re.compile(r"\bequal employment opportunity\b", re.IGNORECASE),
    re.compile(r"\bwithout discrimination\b", re.IGNORECASE),
    re.compile(r"\breasonable accommodations?\b", re.IGNORECASE),
    re.compile(r"\binternal applicants?\b", re.IGNORECASE),
    re.compile(r"\bbase pay range\b", re.IGNORECASE),
    re.compile(r"\bequity grade\b", re.IGNORECASE),
    re.compile(r"\bbenefits package\b", re.IGNORECASE),
    re.compile(r"\bremote-first company\b", re.IGNORECASE),
    re.compile(r"\bpay range\b", re.IGNORECASE),
    re.compile(r"\bconfidence gap\b", re.IGNORECASE),
    re.compile(r"\bimposter syndrome\b", re.IGNORECASE),
    re.compile(r"\btalent community\b", re.IGNORECASE),
    re.compile(r"\bred flag\b", re.IGNORECASE),
)


def build_step_02_artifact(
    *,
    posting_row: Mapping[str, Any],
    run: Any,
    step_01_payload: Mapping[str, Any],
) -> dict[str, Any]:
    signals: list[dict[str, Any]] = []
    extracted_counts: dict[str, int] = {}

    for section in step_01_payload.get("sections") or []:
        if not isinstance(section, Mapping):
            continue
        section_id = str(section.get("section_id") or "")
        section_heading = section.get("heading")
        section_type = str(section.get("section_type") or "general")

        for line in section.get("lines") or []:
            if not isinstance(line, Mapping):
                continue
            normalized = normalize_jd_line(str(line.get("text") or ""))
            if not normalized or _should_skip_raw_signal(normalized):
                continue

            signal = {
                "raw_signal_id": f"raw_signal_{len(signals) + 1:02d}",
                "raw_text": normalized,
                "source_section_id": section_id,
                "source_heading": section_heading,
                "source_section_type": section_type,
                "source_line_number": line.get("line_number"),
            }
            signals.append(signal)
            extracted_counts[section_type] = extracted_counts.get(section_type, 0) + 1

    return {
        "job_posting_id": posting_row["job_posting_id"],
        "resume_tailoring_run_id": run.resume_tailoring_run_id,
        "status": "generated",
        "role_title": step_01_payload.get("role_title") or posting_row["role_title"],
        "signals_extracted": len(signals),
        "signals_by_section_type": extracted_counts,
        "signals": signals,
    }


def _should_skip_raw_signal(line: str) -> bool:
    if any(pattern.search(line) for pattern in JD_POLICY_LINE_PATTERNS):
        return True
    lowered = line.lower()
    if any(
        term in lowered
        for term in (
            "equal employment opportunity",
            "reasonable accommodation",
            "internal applicants",
        )
    ):
        return True
    return False
