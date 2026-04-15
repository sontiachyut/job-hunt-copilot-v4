from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from .keyword_system import load_term_aliases, normalize_term
from .theme_classifier import EXPECTED_THEMES


REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "assets" / "resume-tailoring" / "data"
EXPERIENCE_POOL_PATH = DATA_DIR / "bullet_pool_experience.yaml"
PROJECT_POOL_PATH = DATA_DIR / "bullet_pool_projects.yaml"
NORMALIZE_RE = re.compile(r"[^a-z0-9]+")
ALLOWED_IMPACT_TYPES = {
    "scale",
    "optimization",
    "reliability",
    "delivery",
    "product",
    "ai_integration",
}
EXPECTED_THEME_SET = set(EXPECTED_THEMES)


def load_experience_pool(path: Path | None = None) -> dict[str, dict[str, Any]]:
    payload = _load_yaml_mapping(path or EXPERIENCE_POOL_PATH)
    entries = payload.get("entries")
    if not isinstance(entries, Mapping):
        raise ValueError("Experience bullet pool YAML must contain a top-level `entries` mapping.")
    return _validate_entries(entries)


def load_project_pool(path: Path | None = None) -> dict[str, Any]:
    project_pool_path = path or PROJECT_POOL_PATH
    if not project_pool_path.exists():
        return {}

    payload = _load_yaml_mapping(project_pool_path)
    projects = payload.get("projects")
    if not isinstance(projects, Mapping):
        raise ValueError("Project bullet pool YAML must contain a top-level `projects` mapping.")
    return dict(projects)


def get_bullets_for_entry(pool: Mapping[str, Any], entry_id: str) -> list[dict[str, Any]]:
    entry = pool.get(entry_id, {})
    if not isinstance(entry, Mapping):
        raise ValueError(f"Bullet-pool entry `{entry_id}` must be a mapping.")

    bullets = entry.get("bullets", [])
    if not isinstance(bullets, Sequence) or isinstance(bullets, (str, bytes)):
        raise ValueError(f"Bullet-pool entry `{entry_id}` must define a `bullets` sequence.")

    loaded_bullets: list[dict[str, Any]] = []
    for bullet in bullets:
        if not isinstance(bullet, Mapping):
            raise ValueError(f"Bullet-pool entry `{entry_id}` contains a non-mapping bullet.")
        loaded_bullets.append(dict(bullet))
    return loaded_bullets


def filter_bullets_by_theme(
    bullets: Sequence[Mapping[str, Any]],
    theme: str,
) -> list[dict[str, Any]]:
    if theme not in EXPECTED_THEME_SET:
        raise ValueError(f"Unknown theme `{theme}`.")

    matching: list[dict[str, Any]] = []
    for bullet in bullets:
        bullet_themes = bullet.get("themes", [])
        if not isinstance(bullet_themes, Sequence) or isinstance(bullet_themes, (str, bytes)):
            raise ValueError("Each bullet must define a `themes` sequence.")
        if theme in bullet_themes:
            matching.append(dict(bullet))
    return matching


def rank_bullets_by_jd_overlap(
    bullets: Sequence[Mapping[str, Any]],
    jd_tokens: set[str],
) -> list[dict[str, Any]]:
    aliases = load_term_aliases()
    normalized_terms = {
        _normalize_overlap_term(token, aliases)
        for token in jd_tokens
        if isinstance(token, str) and token.strip()
    }
    normalized_terms.discard("")
    normalized_words = {
        word
        for term in normalized_terms
        for word in term.split()
        if word
    }

    ranked: list[tuple[int, str, str, dict[str, Any]]] = []
    for bullet in bullets:
        tags = bullet.get("tech_tags", [])
        if not isinstance(tags, Sequence) or isinstance(tags, (str, bytes)):
            raise ValueError("Each bullet must define a `tech_tags` sequence.")

        overlap = 0
        for tag in tags:
            if not isinstance(tag, str):
                raise ValueError("Each bullet tech tag must be a string.")
            normalized_tag = _normalize_overlap_term(tag, aliases)
            if not normalized_tag:
                continue
            if normalized_tag in normalized_terms:
                overlap += 1
                continue
            tag_words = normalized_tag.split()
            if tag_words and all(word in normalized_words for word in tag_words):
                overlap += 1

        ranked.append(
            (
                overlap,
                str(bullet.get("impact_type", "")),
                str(bullet.get("bullet_id", "")),
                dict(bullet),
            )
        )

    ranked.sort(key=lambda item: (-item[0], item[1], item[2]))
    return [bullet for _, _, _, bullet in ranked]


def _validate_entries(entries: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    validated: dict[str, dict[str, Any]] = {}
    seen_bullet_ids: set[str] = set()

    for entry_id, raw_entry in entries.items():
        if not isinstance(entry_id, str):
            raise ValueError("Experience bullet pool entry IDs must be strings.")
        if not isinstance(raw_entry, Mapping):
            raise ValueError(f"Experience entry `{entry_id}` must be a mapping.")

        bullet_limits = _validate_bullet_limits(entry_id, raw_entry.get("bullet_limits"))
        bullets = raw_entry.get("bullets")
        if not isinstance(bullets, Sequence) or isinstance(bullets, (str, bytes)):
            raise ValueError(f"Experience entry `{entry_id}` must define a `bullets` sequence.")

        validated_bullets: list[dict[str, Any]] = []
        for raw_bullet in bullets:
            validated_bullet = _validate_bullet(entry_id, raw_bullet)
            bullet_id = validated_bullet["bullet_id"]
            if bullet_id in seen_bullet_ids:
                raise ValueError(f"Duplicate bullet ID `{bullet_id}` found in experience pool.")
            seen_bullet_ids.add(bullet_id)
            validated_bullets.append(validated_bullet)

        validated_entry = dict(raw_entry)
        for field_name in ("company", "title", "dates"):
            value = validated_entry.get(field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Experience entry `{entry_id}` must define a non-empty `{field_name}`.")

        tech_stack = validated_entry.get("tech_stack")
        if not isinstance(tech_stack, Sequence) or isinstance(tech_stack, (str, bytes)):
            raise ValueError(f"Experience entry `{entry_id}` must define a `tech_stack` sequence.")
        if not all(isinstance(item, str) and item.strip() for item in tech_stack):
            raise ValueError(f"Experience entry `{entry_id}` has a non-string `tech_stack` item.")

        validated_entry["bullet_limits"] = bullet_limits
        validated_entry["tech_stack"] = [str(item) for item in tech_stack]
        validated_entry["bullets"] = validated_bullets
        validated[entry_id] = validated_entry

    return validated


def _validate_bullet_limits(entry_id: str, raw_limits: Any) -> dict[str, int]:
    if not isinstance(raw_limits, Mapping):
        raise ValueError(f"Experience entry `{entry_id}` must define `bullet_limits`.")

    minimum = raw_limits.get("min")
    maximum = raw_limits.get("max")
    if not isinstance(minimum, int) or not isinstance(maximum, int):
        raise ValueError(f"Experience entry `{entry_id}` bullet limits must be integers.")
    if minimum < 0 or maximum < 0 or minimum > maximum:
        raise ValueError(f"Experience entry `{entry_id}` bullet limits are invalid.")
    return {"min": minimum, "max": maximum}


def _validate_bullet(entry_id: str, raw_bullet: Any) -> dict[str, Any]:
    if not isinstance(raw_bullet, Mapping):
        raise ValueError(f"Experience entry `{entry_id}` contains a non-mapping bullet.")

    bullet = dict(raw_bullet)
    bullet_id = _require_non_empty_string(entry_id, bullet, "bullet_id")
    source = _require_non_empty_string(entry_id, bullet, "source")
    if source != entry_id:
        raise ValueError(f"Bullet `{bullet_id}` must declare source `{entry_id}`.")

    impact_type = _require_non_empty_string(entry_id, bullet, "impact_type")
    if impact_type not in ALLOWED_IMPACT_TYPES:
        raise ValueError(f"Bullet `{bullet_id}` has unsupported impact type `{impact_type}`.")

    base_purpose = bullet.get("base_purpose")
    if base_purpose is not None and (not isinstance(base_purpose, str) or not base_purpose.strip()):
        raise ValueError(f"Bullet `{bullet_id}` has an invalid `base_purpose`.")

    themes = _require_string_list(entry_id, bullet, "themes", bullet_id)
    unknown_themes = [theme for theme in themes if theme not in EXPECTED_THEME_SET]
    if unknown_themes:
        unknown = ", ".join(sorted(unknown_themes))
        raise ValueError(f"Bullet `{bullet_id}` declares unknown themes: {unknown}.")

    tech_tags = _require_string_list(entry_id, bullet, "tech_tags", bullet_id)
    metrics = _require_string_list(entry_id, bullet, "metrics", bullet_id)
    text = _require_non_empty_string(entry_id, bullet, "text")

    bullet["bullet_id"] = bullet_id
    bullet["source"] = source
    bullet["impact_type"] = impact_type
    bullet["themes"] = themes
    bullet["tech_tags"] = tech_tags
    bullet["metrics"] = metrics
    bullet["text"] = text
    return bullet


def _require_non_empty_string(entry_id: str, payload: Mapping[str, Any], field_name: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Experience entry `{entry_id}` field `{field_name}` must be a non-empty string.")
    return value.strip()


def _require_string_list(
    entry_id: str,
    payload: Mapping[str, Any],
    field_name: str,
    bullet_id: str,
) -> list[str]:
    value = payload.get(field_name)
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"Bullet `{bullet_id}` in `{entry_id}` must define `{field_name}` as a sequence.")
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise ValueError(f"Bullet `{bullet_id}` in `{entry_id}` has a non-string `{field_name}` item.")
    return [str(item).strip() for item in value]


def _normalize_overlap_term(term: str, aliases: Mapping[str, Sequence[str]]) -> str:
    canonical_term = normalize_term(term, aliases)
    normalized = NORMALIZE_RE.sub(" ", canonical_term.casefold()).strip()
    return " ".join(normalized.split())


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a mapping at `{path}`.")
    return payload
