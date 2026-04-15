from __future__ import annotations

import re
from typing import Any, Mapping

from .step_01_jd_sections import extract_level, extract_with_regex, jd_heading_from_line


TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9.+/#-]*")
LOCATION_TOKEN_RE = re.compile(r"\b(remote|hybrid|on-site|onsite)\b", re.IGNORECASE)
EMPLOYMENT_TYPE_RE = re.compile(r"\b(full[- ]time|part[- ]time|contract|internship)\b", re.IGNORECASE)
COMMON_SIGNAL_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "any",
        "and",
        "as",
        "at",
        "by",
        "from",
        "the",
        "that",
        "this",
        "these",
        "those",
        "to",
        "of",
        "for",
        "with",
        "in",
        "on",
        "or",
        "our",
        "your",
        "you",
        "we",
        "will",
        "be",
        "is",
        "are",
        "using",
        "build",
        "develop",
        "experience",
        "more",
        "please",
        "visit",
    }
)
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
THEME_SIGNAL_WEIGHTS = {
    "role_title": 2.0,
    "core_responsibility": 2.0,
    "must_have": 1.0,
    "nice_to_have": 0.5,
    "informational": 0.0,
}
FRONTEND_AI_TERMS = frozenset(
    {
        "accessibility",
        "agentic",
        "angular",
        "browser",
        "css",
        "customer-facing",
        "dom",
        "embeddings",
        "frontend",
        "html",
        "javascript",
        "llm",
        "llms",
        "node",
        "react",
        "responsive",
        "typescript",
        "ui",
        "ux",
        "vue",
        "web",
    }
)
DISTRIBUTED_INFRA_TERMS = frozenset(
    {
        "availability",
        "aws",
        "azure",
        "cloud",
        "distributed",
        "etl",
        "gcp",
        "high-availability",
        "infrastructure",
        "kafka",
        "kubernetes",
        "latency",
        "monitoring",
        "observability",
        "performance",
        "pipeline",
        "platform",
        "reliability",
        "spark",
        "streaming",
        "throughput",
    }
)


def build_step_03_artifact(
    *,
    posting_row: Mapping[str, Any],
    run: Any,
    step_02_payload: Mapping[str, Any],
    jd_text: str,
) -> dict[str, Any]:
    signals: list[dict[str, Any]] = []
    seen_signals: set[str] = set()
    counts = {
        "must_have": 0,
        "core_responsibility": 0,
        "nice_to_have": 0,
        "informational": 0,
    }

    for raw_signal in step_02_payload.get("signals") or []:
        if not isinstance(raw_signal, Mapping):
            continue
        normalized_line = str(raw_signal.get("raw_text") or "").strip()
        if not normalized_line:
            continue

        priority = classify_signal_priority(
            source_heading=raw_signal.get("source_heading"),
            source_section_type=raw_signal.get("source_section_type"),
            line=normalized_line,
        )
        if priority is None:
            continue

        dedupe_key = f"{priority}|{normalized_line.lower()}"
        if dedupe_key in seen_signals:
            continue
        seen_signals.add(dedupe_key)

        counts[priority] += 1
        signal_id = f"signal_{priority}_{counts[priority]}"
        category = categorize_signal(normalized_line)
        signals.append(
            {
                "signal_id": signal_id,
                "raw_signal_id": raw_signal.get("raw_signal_id"),
                "priority": priority,
                "weight": signal_priority_weight(priority),
                "category": category,
                "signal": normalized_line,
                "text": normalized_line,
                "tokens": sorted(tokenize(normalized_line)),
                "rationale": signal_rationale(priority, raw_signal.get("source_heading"), normalized_line),
                "jd_evidence": normalized_line,
                "source_heading": raw_signal.get("source_heading"),
                "source_section_id": raw_signal.get("source_section_id"),
                "source_section_type": raw_signal.get("source_section_type"),
                "source_line_number": raw_signal.get("source_line_number"),
            }
        )

    role_title = str(posting_row["role_title"])
    role_intent_signals = [
        signal["signal"]
        for signal in signals
        if signal["priority"] in {"core_responsibility", "must_have"}
    ][:2]
    role_intent_summary = (
        "; ".join(role_intent_signals)
        if role_intent_signals
        else f"Role-targeted tailoring for {role_title} using the persisted JD mirror."
    )

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
        "role_intent_summary": role_intent_summary,
        "signal_priority_weights": {
            "must_have": THEME_SIGNAL_WEIGHTS["must_have"],
            "core_responsibility": THEME_SIGNAL_WEIGHTS["core_responsibility"],
            "nice_to_have": THEME_SIGNAL_WEIGHTS["nice_to_have"],
            "informational": THEME_SIGNAL_WEIGHTS["informational"],
        },
        "theme_signal_weights": dict(THEME_SIGNAL_WEIGHTS),
        "signals_by_priority": {
            priority: [signal for signal in signals if signal["priority"] == priority]
            for priority in ("must_have", "core_responsibility", "nice_to_have", "informational")
        },
        "signals": signals,
    }


def classify_signal_priority(
    *,
    source_heading: Any,
    source_section_type: Any,
    line: str,
) -> str | None:
    heading = str(source_heading or "").lower()
    normalized = line.lower()
    if jd_heading_from_line(line):
        return None
    if any(pattern.search(line) for pattern in JD_POLICY_LINE_PATTERNS):
        return None
    if any(
        term in heading
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
        return None
    if any(
        term in normalized
        for term in (
            "relocation is not provided",
            "must reside",
            "must be located",
            "must live in",
            "hybrid work model",
            "days in the office",
        )
    ):
        return "informational"
    if any(term in heading for term in ("benefits", "salary", "compensation")):
        return "informational"
    if any(term in normalized for term in ("salary", "benefits", "compensation", "hybrid", "remote")):
        return "informational"
    section_type = str(source_section_type or "").strip()
    if section_type in {"must_have", "core_responsibility", "nice_to_have", "informational"}:
        return section_type
    if any(term in heading for term in ("nice", "preferred")):
        return "nice_to_have"
    if any(term in heading for term in ("responsibilit", "what you'll do", "what you will do", "about the role")):
        return "core_responsibility"
    if any(term in heading for term in ("requirement", "qualification", "must", "bring")):
        return "must_have"
    if any(
        term in normalized
        for term in (
            "policy of",
            "equal employment opportunity",
            "without discrimination",
            "reasonable accommodations",
            "internal applicants",
        )
    ):
        return None
    if extract_experience_lower_bound(line) is not None:
        return "must_have"
    if any(term in normalized for term in ("required", "must", "minimum", "citizenship", "clearance")):
        return "must_have"
    if any(term in normalized for term in ("preferred", "nice to have", "bonus")):
        return "nice_to_have"
    if any(term in normalized for term in ("build", "design", "develop", "collaborate", "own")):
        return "core_responsibility"
    return None


def categorize_signal(line: str) -> str:
    tokens = tokenize(line)
    if tokens & {"citizenship", "clearance", "security"}:
        return "authorization"
    if tokens & {"salary", "compensation", "benefits", "bonus", "equity", "pay"}:
        return "compensation"
    if tokens & {"relocation", "reside", "onsite", "hybrid", "remote", "location"}:
        return "location_constraint"
    if tokens & {"bachelor", "masters", "master", "degree", "phd"}:
        return "education_requirement"
    if tokens & {"years", "year"}:
        return "experience_requirement"
    if tokens & FRONTEND_AI_TERMS:
        return "frontend_ai"
    if tokens & DISTRIBUTED_INFRA_TERMS:
        return "distributed_infra"
    if tokens & {"communicate", "collaborate", "stakeholders", "team"}:
        return "collaboration"
    if tokens & {"reliability", "monitoring", "uptime", "incident"}:
        return "reliability"
    return "general"


def signal_priority_weight(priority: str) -> float:
    return THEME_SIGNAL_WEIGHTS[priority]


def signal_rationale(priority: str, heading: Any, line: str) -> str:
    heading_value = str(heading or "").strip()
    heading_note = f" under `{heading_value}`" if heading_value else ""
    if priority == "must_have":
        return f"Classified as must-have because the JD presents this requirement{heading_note}."
    if priority == "core_responsibility":
        return f"Classified as core responsibility because the JD frames this work item{heading_note}."
    if priority == "nice_to_have":
        return f"Classified as nice-to-have because the JD marks it as optional{heading_note}."
    return f"Captured as informational context from the JD{heading_note}."


def tokenize(text: str) -> set[str]:
    lowered = text.lower()
    lowered = lowered.replace("node.js", "node js")
    lowered = lowered.replace("next.js", "next js")
    lowered = lowered.replace("c++", "cplusplus")
    lowered = lowered.replace("real-time", "realtime")
    tokens = {
        token
        for token in TOKEN_RE.findall(lowered)
        if token not in COMMON_SIGNAL_STOPWORDS and len(token) > 1
    }
    if "realtime" in lowered:
        tokens.add("real-time")
    if "agentic ai" in lowered:
        tokens.add("agentic")
        tokens.add("ai")
    return tokens


def extract_experience_lower_bound(line: str) -> int | None:
    patterns = (
        re.compile(r"\b(?P<years>\d+)\s*\+\s*years?\b", re.IGNORECASE),
        re.compile(r"\bminimum(?: of)?\s+(?P<years>\d+)\s+years?\b", re.IGNORECASE),
        re.compile(r"\bat least\s+(?P<years>\d+)\s+years?\b", re.IGNORECASE),
        re.compile(r"\b(?P<years>\d+)\s+years?\b", re.IGNORECASE),
    )
    for pattern in patterns:
        match = pattern.search(line)
        if match is not None:
            return int(match.group("years"))
    return None
