from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "assets" / "resume-tailoring" / "data"
THEME_TERMS_PATH = DATA_DIR / "theme_terms.yaml"
NORMALIZE_RE = re.compile(r"[^a-z0-9]+")
EXPECTED_THEMES = (
    "applied_ai",
    "agent_ai_systems",
    "forward_deployed_ai",
    "frontend_web",
    "backend_service",
    "distributed_infra",
    "platform_infra",
    "fullstack",
    "generalist",
)
SOURCE_WEIGHTS: dict[str, float] = {
    "role_title": 2.0,
    "core_responsibility": 2.0,
    "must_have": 1.0,
    "nice_to_have": 0.5,
    "informational": 0.0,
}
CONFIDENCE_THRESHOLD = 2.0
FULLSTACK_CLOSE_RATIO = 0.75


def load_theme_terms(path: Path | None = None) -> dict[str, dict[str, Any]]:
    payload = _load_yaml_mapping(path or THEME_TERMS_PATH)
    themes = payload.get("themes")
    if not isinstance(themes, Mapping):
        raise ValueError("Theme terms YAML must contain a top-level `themes` mapping.")

    missing_themes = [theme for theme in EXPECTED_THEMES if theme not in themes]
    if missing_themes:
        missing = ", ".join(missing_themes)
        raise ValueError(f"Theme terms YAML is missing required themes: {missing}.")

    unexpected_themes = [theme for theme in themes if theme not in EXPECTED_THEMES]
    if unexpected_themes:
        extras = ", ".join(sorted(unexpected_themes))
        raise ValueError(f"Theme terms YAML contains unexpected themes: {extras}.")

    loaded: dict[str, dict[str, Any]] = {}
    for theme_id in EXPECTED_THEMES:
        theme_payload = themes[theme_id]
        if not isinstance(theme_payload, Mapping):
            raise ValueError(f"Theme `{theme_id}` must map to a mapping payload.")

        terms = theme_payload.get("terms")
        if not isinstance(terms, list) or not all(isinstance(term, str) for term in terms):
            raise ValueError(f"Theme `{theme_id}` must define a string `terms` list.")

        template = theme_payload.get("template")
        if template not in {"A", "B", "runtime"}:
            raise ValueError(
                f"Theme `{theme_id}` must declare template `A`, `B`, or `runtime`."
            )

        loaded[theme_id] = {
            "template": template,
            "terms": _dedupe_preserving_order(terms),
        }

    return loaded


def classify_theme(
    step_3_payload: Mapping[str, Any],
    theme_terms: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    if not isinstance(step_3_payload, Mapping):
        raise TypeError("Theme classification expects a mapping payload.")

    loaded_theme_terms = theme_terms or load_theme_terms()
    weighted_sources = _collect_weighted_sources(step_3_payload)

    scores: dict[str, float] = {}
    matched_terms: dict[str, list[str]] = {}
    for theme_id in EXPECTED_THEMES:
        theme_payload = loaded_theme_terms[theme_id]
        score, matches = _score_theme(theme_payload.get("terms", []), weighted_sources)
        scores[theme_id] = score
        matched_terms[theme_id] = matches

    selected_theme, confidence = _select_theme(scores)
    runner_up_theme = _runner_up_theme(selected_theme, scores)
    margin = confidence - scores.get(runner_up_theme, 0.0)
    template = str(loaded_theme_terms[selected_theme].get("template", "runtime"))

    return {
        "theme": selected_theme,
        "template": template,
        "scores": scores,
        "matched_terms": matched_terms,
        "runner_up": runner_up_theme,
        "margin": margin,
        "confidence": confidence,
    }


def _collect_weighted_sources(step_3_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    role_title = _coerce_text(
        step_3_payload.get("role_title") or step_3_payload.get("role_intent_summary")
    )
    if role_title:
        sources.append(_build_source("role_title", role_title, SOURCE_WEIGHTS["role_title"]))

    signals = step_3_payload.get("signals") or []
    if not isinstance(signals, Sequence):
        raise ValueError("Theme classification payload `signals` must be a sequence.")

    for index, signal in enumerate(signals):
        if not isinstance(signal, Mapping):
            raise ValueError("Each theme-classification signal must be a mapping.")

        priority = str(signal.get("priority") or "").strip()
        weight = SOURCE_WEIGHTS.get(priority, 0.0)
        if weight <= 0.0:
            continue

        text = _coerce_text(signal.get("signal") or signal.get("text"))
        if not text:
            tokens = signal.get("tokens")
            if isinstance(tokens, Sequence) and not isinstance(tokens, (str, bytes)):
                text = " ".join(str(token) for token in tokens if str(token).strip())
        if not text:
            continue

        source_name = str(signal.get("signal_id") or f"signal_{index}")
        sources.append(_build_source(source_name, text, weight))

    return sources


def _score_theme(
    theme_terms: Sequence[str],
    weighted_sources: Sequence[Mapping[str, Any]],
) -> tuple[float, list[str]]:
    score = 0.0
    matches: list[str] = []
    for term in _dedupe_preserving_order(theme_terms):
        normalized_term = _normalize_phrase(term)
        if not normalized_term:
            continue

        term_score = 0.0
        for source in weighted_sources:
            if _source_contains_term(source, normalized_term):
                term_score += float(source["weight"])

        if term_score > 0.0:
            score += term_score
            matches.append(term)

    return score, matches


def _source_contains_term(source: Mapping[str, Any], normalized_term: str) -> bool:
    if " " in normalized_term:
        padded_text = f" {source['normalized_text']} "
        padded_term = f" {normalized_term} "
        return padded_term in padded_text
    return normalized_term in source["tokens"]


def _select_theme(scores: Mapping[str, float]) -> tuple[str, float]:
    ranked = sorted(
        EXPECTED_THEMES,
        key=lambda theme_id: (-scores.get(theme_id, 0.0), EXPECTED_THEMES.index(theme_id)),
    )
    best_theme = ranked[0]
    best_score = scores.get(best_theme, 0.0)

    frontend_score = scores.get("frontend_web", 0.0)
    backend_score = scores.get("backend_service", 0.0)
    if _is_fullstack_mix(frontend_score, backend_score):
        best_theme = "fullstack"
        best_score = max(best_score, frontend_score + backend_score)

    if best_theme != "generalist" and best_score < CONFIDENCE_THRESHOLD:
        return "generalist", scores.get("generalist", 0.0)
    return best_theme, best_score


def _runner_up_theme(selected_theme: str, scores: Mapping[str, float]) -> str:
    candidates = [theme for theme in EXPECTED_THEMES if theme != selected_theme]
    ranked = sorted(
        candidates,
        key=lambda theme_id: (-scores.get(theme_id, 0.0), EXPECTED_THEMES.index(theme_id)),
    )
    return ranked[0] if ranked else "generalist"


def _is_fullstack_mix(frontend_score: float, backend_score: float) -> bool:
    if frontend_score < CONFIDENCE_THRESHOLD or backend_score < CONFIDENCE_THRESHOLD:
        return False
    dominant_score = max(frontend_score, backend_score)
    if dominant_score <= 0.0:
        return False
    return min(frontend_score, backend_score) / dominant_score >= FULLSTACK_CLOSE_RATIO


def _build_source(name: str, text: str, weight: float) -> dict[str, Any]:
    normalized_text = _normalize_phrase(text)
    tokens = set(normalized_text.split()) if normalized_text else set()
    return {
        "name": name,
        "raw_text": text,
        "normalized_text": normalized_text,
        "tokens": tokens,
        "weight": weight,
    }


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _dedupe_preserving_order(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            deduped.append(value)
    return deduped


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a mapping at `{path}`.")
    return payload


def _normalize_phrase(text: str) -> str:
    return " ".join(NORMALIZE_RE.split(text.casefold())).strip()
