from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from .theme_classifier import EXPECTED_THEMES


REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "assets" / "resume-tailoring" / "data"
SUMMARY_TEMPLATES_PATH = DATA_DIR / "summary_templates.yaml"
SKILL_CATEGORIES_PATH = DATA_DIR / "skill_categories.yaml"


def load_summary_templates(path: Path | None = None) -> dict[str, str]:
    payload = _load_yaml_mapping(path or SUMMARY_TEMPLATES_PATH)
    summaries = payload.get("summaries")
    if not isinstance(summaries, Mapping):
        raise ValueError("Summary templates YAML must contain a top-level `summaries` mapping.")

    _validate_theme_keys("Summary templates YAML", summaries)

    loaded: dict[str, str] = {}
    for theme_id in EXPECTED_THEMES:
        summary = summaries[theme_id]
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError(f"Summary template `{theme_id}` must be a non-empty string.")
        loaded[theme_id] = summary.strip()
    return loaded


def get_summary_template(
    theme: str,
    templates: Mapping[str, str] | None = None,
) -> str:
    loaded_templates = templates or load_summary_templates()
    return _require_theme_mapping_value(
        "summary template",
        theme,
        loaded_templates,
        expected_type=str,
    )


def load_skill_categories(path: Path | None = None) -> dict[str, list[dict[str, Any]]]:
    payload = _load_yaml_mapping(path or SKILL_CATEGORIES_PATH)
    categories = payload.get("categories")
    if not isinstance(categories, Mapping):
        raise ValueError("Skill categories YAML must contain a top-level `categories` mapping.")

    _validate_theme_keys("Skill categories YAML", categories)

    loaded: dict[str, list[dict[str, Any]]] = {}
    for theme_id in EXPECTED_THEMES:
        category_payload = categories[theme_id]
        if not isinstance(category_payload, Sequence) or isinstance(category_payload, (str, bytes)):
            raise ValueError(f"Skill category template `{theme_id}` must define a sequence.")
        if not category_payload:
            raise ValueError(f"Skill category template `{theme_id}` must define at least one category.")

        theme_categories: list[dict[str, Any]] = []
        seen_names: set[str] = set()
        for raw_category in category_payload:
            if not isinstance(raw_category, Mapping):
                raise ValueError(f"Skill category template `{theme_id}` contains a non-mapping category.")

            name = raw_category.get("name")
            if not isinstance(name, str) or not name.strip():
                raise ValueError(f"Skill category template `{theme_id}` has a category with an invalid `name`.")
            normalized_name = name.strip()
            if normalized_name in seen_names:
                raise ValueError(
                    f"Skill category template `{theme_id}` contains a duplicate category `{normalized_name}`."
                )
            seen_names.add(normalized_name)

            pool_sources = raw_category.get("pool_sources")
            if not isinstance(pool_sources, Sequence) or isinstance(pool_sources, (str, bytes)):
                raise ValueError(
                    f"Skill category `{normalized_name}` for theme `{theme_id}` must define `pool_sources`."
                )
            if not pool_sources or not all(isinstance(item, str) and item.strip() for item in pool_sources):
                raise ValueError(
                    f"Skill category `{normalized_name}` for theme `{theme_id}` has invalid `pool_sources`."
                )

            theme_categories.append(
                {
                    "name": normalized_name,
                    "pool_sources": [str(item).strip() for item in pool_sources],
                }
            )

        loaded[theme_id] = theme_categories

    return loaded


def get_skill_categories(
    theme: str,
    templates: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    loaded_templates = templates or load_skill_categories()
    categories = _require_theme_mapping_value(
        "skill category template",
        theme,
        loaded_templates,
        expected_type=Sequence,
    )
    return [dict(category) for category in categories]


def _validate_theme_keys(source_name: str, payload: Mapping[str, Any]) -> None:
    missing = [theme_id for theme_id in EXPECTED_THEMES if theme_id not in payload]
    if missing:
        raise ValueError(f"{source_name} is missing required themes: {', '.join(missing)}.")

    unexpected = [theme_id for theme_id in payload if theme_id not in EXPECTED_THEMES]
    if unexpected:
        raise ValueError(f"{source_name} contains unexpected themes: {', '.join(sorted(unexpected))}.")


def _require_theme_mapping_value(
    label: str,
    theme: str,
    payload: Mapping[str, Any],
    *,
    expected_type: type[Any],
) -> Any:
    if theme not in EXPECTED_THEMES:
        raise ValueError(f"Unknown theme `{theme}`.")

    value = payload.get(theme)
    if value is None:
        raise ValueError(f"Missing {label} for theme `{theme}`.")
    if expected_type is str:
        if not isinstance(value, str):
            raise ValueError(f"Theme `{theme}` must resolve to a string {label}.")
        return value
    if not isinstance(value, expected_type) or isinstance(value, (str, bytes)):
        raise ValueError(f"Theme `{theme}` must resolve to a sequence {label}.")
    return value


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a mapping at `{path}`.")
    return payload
