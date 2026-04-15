from __future__ import annotations

import re
from typing import Any, Mapping


MARKDOWN_HEADING_RE = re.compile(r"^(?P<hashes>#+)\s+(?P<title>.+?)\s*$")
LEVEL_TOKEN_RE = re.compile(r"\b(intern|junior|mid|senior|staff|principal|lead)\b", re.IGNORECASE)
LOCATION_TOKEN_RE = re.compile(r"\b(remote|hybrid|on-site|onsite)\b", re.IGNORECASE)
EMPLOYMENT_TYPE_RE = re.compile(r"\b(full[- ]time|part[- ]time|contract|internship)\b", re.IGNORECASE)
JD_HEADING_ONLY_PATTERNS = (
    re.compile(
        r"^(job description|job description summary|the company|required skills?(?:\s*&\s*experience)?|"
        r"essential responsibilities|key responsibilities|responsibilities|what you(?:['’]ll| will) do|"
        r"what you bring|minimum qualifications|qualifications|requirements|required qualifications?|"
        r"preferred qualifications?|additional responsibilities(?:\s+and\s+preferred qualifications?)?|"
        r"nice to have|our benefits|benefits(?: to support you)?|who we are|commitment to diversity and "
        r"inclusion|belonging at .+|internal application policy)$",
        re.IGNORECASE,
    ),
    re.compile(r"^(lead with purpose\.?\s*partner with impact\.?)$", re.IGNORECASE),
)
SECTION_TYPE_PRIORITY_ORDER = (
    "must_have",
    "core_responsibility",
    "nice_to_have",
    "informational",
    "general",
)


def build_step_01_artifact(
    *,
    posting_row: Mapping[str, Any],
    run: Any,
    jd_text: str,
) -> dict[str, Any]:
    sections: list[dict[str, Any]] = []
    current_section: dict[str, Any] | None = None

    for line_number, raw_line in enumerate(jd_text.splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped:
            continue

        heading = jd_heading_from_line(stripped)
        if heading is not None:
            if current_section is not None:
                _finalize_section(current_section)
                sections.append(current_section)
            current_section = {
                "section_id": f"section_{len(sections) + 1:02d}",
                "heading": heading,
                "section_type": classify_section_type(heading),
                "start_line": line_number,
                "end_line": line_number,
                "lines": [],
            }
            continue

        if current_section is None:
            current_section = {
                "section_id": f"section_{len(sections) + 1:02d}",
                "heading": None,
                "section_type": "general",
                "start_line": line_number,
                "end_line": line_number,
                "lines": [],
            }

        current_section["lines"].append(
            {
                "line_number": line_number,
                "text": stripped,
            }
        )
        current_section["end_line"] = line_number

    if current_section is not None:
        _finalize_section(current_section)
        sections.append(current_section)

    section_counts = {section_type: 0 for section_type in SECTION_TYPE_PRIORITY_ORDER}
    for section in sections:
        section_type = str(section.get("section_type") or "general")
        section_counts[section_type] = section_counts.get(section_type, 0) + 1

    role_title = str(posting_row["role_title"])
    return {
        "job_posting_id": posting_row["job_posting_id"],
        "resume_tailoring_run_id": run.resume_tailoring_run_id,
        "status": "generated",
        "role_title": role_title,
        "role_metadata": {
            "role_title": role_title,
            "level": extract_level(role_title),
            "location": extract_with_regex(jd_text, LOCATION_TOKEN_RE),
            "employment_type": extract_with_regex(jd_text, EMPLOYMENT_TYPE_RE),
        },
        "section_counts": section_counts,
        "sections": sections,
    }


def jd_heading_from_line(line: str) -> str | None:
    stripped = line.strip()
    if not stripped:
        return None

    markdown_match = MARKDOWN_HEADING_RE.match(stripped)
    if markdown_match is not None:
        return markdown_match.group("title").strip()

    cleaned = stripped.rstrip(":").strip()
    if not cleaned:
        return None
    if any(pattern.search(cleaned) for pattern in JD_HEADING_ONLY_PATTERNS):
        return cleaned
    if len(cleaned) > 80 or cleaned.endswith((".", "!", "?")):
        return None

    words = [re.sub(r"[^A-Za-z0-9&()/+-]+", "", word) for word in cleaned.split()]
    words = [word for word in words if word]
    if not words or len(words) > 8:
        return None

    allowed_lowercase = {"and", "or", "of", "to", "for", "with", "the", "a", "an", "in", "on", "at", "by"}
    if all(
        word.isupper()
        or any(char.isdigit() for char in word)
        or word.lower() in allowed_lowercase
        or word[0].isupper()
        for word in words
    ):
        return cleaned
    return None


def normalize_jd_line(line: str) -> str:
    cleaned = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", line).strip()
    if len(cleaned) < 8:
        return ""
    if jd_heading_from_line(cleaned):
        return ""
    return cleaned


def classify_section_type(heading: str | None) -> str:
    normalized_heading = str(heading or "").strip().lower()
    if not normalized_heading:
        return "general"
    if any(term in normalized_heading for term in ("nice", "preferred")):
        return "nice_to_have"
    if any(
        term in normalized_heading
        for term in ("responsibilit", "what you'll do", "what you will do", "about the role")
    ):
        return "core_responsibility"
    if any(term in normalized_heading for term in ("requirement", "qualification", "must", "bring")):
        return "must_have"
    if any(
        term in normalized_heading
        for term in (
            "internal application policy",
            "benefits",
            "the company",
            "who we are",
            "commitment to diversity",
            "belonging at",
            "job description summary",
        )
    ):
        return "informational"
    return "general"


def extract_level(role_title: str) -> str | None:
    match = LEVEL_TOKEN_RE.search(role_title)
    return None if match is None else match.group(1).lower()


def extract_with_regex(text: str, pattern: re.Pattern[str]) -> str | None:
    match = pattern.search(text)
    return None if match is None else match.group(0)


def _finalize_section(section: dict[str, Any]) -> None:
    lines = section.get("lines") or []
    section["line_count"] = len(lines)
    normalized_excerpt_lines = [
        normalize_jd_line(str(line.get("text") or ""))
        for line in lines
    ]
    section["normalized_excerpt"] = [
        line
        for line in normalized_excerpt_lines
        if line
    ][:3]
