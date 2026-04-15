from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "assets" / "resume-tailoring" / "data"
ADJACENCY_MAP_PATH = DATA_DIR / "adjacency_map.yaml"
TERM_ALIASES_PATH = DATA_DIR / "term_aliases.yaml"
LOOKUP_KEY_RE = re.compile(r"[^a-z0-9]+")


def load_adjacency_map(path: Path | None = None) -> dict[str, dict[str, Any]]:
    payload = _load_yaml_mapping(path or ADJACENCY_MAP_PATH)
    families = payload.get("families")
    if not isinstance(families, Mapping):
        raise ValueError("Adjacency map YAML must contain a top-level `families` mapping.")

    adjacency_map: dict[str, dict[str, Any]] = {}
    for family_name, family_payload in families.items():
        if not isinstance(family_name, str) or not isinstance(family_payload, Mapping):
            raise ValueError("Adjacency families must map string family names to mappings.")

        members = family_payload.get("members")
        if not isinstance(members, list) or not all(isinstance(member, str) for member in members):
            raise ValueError(f"Adjacency family `{family_name}` must define a string `members` list.")

        adjacency_map[family_name] = {
            "members": list(members),
            "skill_category_default": family_payload.get("skill_category_default"),
            "reason": family_payload.get("reason"),
        }

    return adjacency_map


def load_term_aliases(path: Path | None = None) -> dict[str, list[str]]:
    payload = _load_yaml_mapping(path or TERM_ALIASES_PATH)
    aliases = payload.get("aliases")
    if not isinstance(aliases, Mapping):
        raise ValueError("Term aliases YAML must contain a top-level `aliases` mapping.")

    alias_map: dict[str, list[str]] = {}
    for canonical_term, alias_values in aliases.items():
        if not isinstance(canonical_term, str):
            raise ValueError("Alias keys must be strings.")
        if not isinstance(alias_values, list) or not all(isinstance(value, str) for value in alias_values):
            raise ValueError(f"Alias entry `{canonical_term}` must map to a list of strings.")
        alias_map[canonical_term] = list(alias_values)

    return alias_map


def normalize_term(term: str, aliases: Mapping[str, Iterable[str]] | None = None) -> str:
    if not isinstance(term, str):
        raise TypeError("Term normalization expects a string input.")

    stripped_term = term.strip()
    if not stripped_term:
        return ""

    alias_lookup = _build_alias_lookup(aliases or load_term_aliases())
    return alias_lookup.get(_lookup_key(stripped_term), stripped_term)


def find_adjacent_match(
    requested_term: str,
    profile_terms: Iterable[str],
    adjacency_map: Mapping[str, Mapping[str, Any]] | None = None,
    aliases: Mapping[str, Iterable[str]] | None = None,
) -> dict[str, Any] | None:
    adjacency_data = adjacency_map or load_adjacency_map()
    alias_data = aliases or load_term_aliases()
    normalized_requested = normalize_term(requested_term, alias_data)
    family_name = _find_family_name(normalized_requested, adjacency_data, alias_data)
    if family_name is None:
        return None

    family = adjacency_data[family_name]
    normalized_members = {
        normalize_term(member, alias_data)
        for member in _family_members(family_name, family)
    }

    adjacent_profile_terms: list[tuple[str, str]] = []
    for profile_term in profile_terms:
        normalized_profile_term = normalize_term(profile_term, alias_data)
        if normalized_profile_term == normalized_requested:
            continue
        if normalized_profile_term in normalized_members:
            adjacent_profile_terms.append((normalized_profile_term, profile_term))

    if not adjacent_profile_terms:
        return None

    matched_normalized, matched_via = min(
        adjacent_profile_terms,
        key=lambda item: (_lookup_key(item[0]), _lookup_key(item[1])),
    )
    return {
        "family": family_name,
        "requested_term": requested_term,
        "normalized_requested_term": normalized_requested,
        "matched_via": matched_via,
        "normalized_matched_via": matched_normalized,
        "skill_category_default": family.get("skill_category_default"),
        "reason": family.get("reason"),
    }


def _find_family_name(
    term: str,
    adjacency_map: Mapping[str, Mapping[str, Any]],
    aliases: Mapping[str, Iterable[str]],
) -> str | None:
    for family_name, family in adjacency_map.items():
        normalized_members = {
            normalize_term(member, aliases)
            for member in _family_members(family_name, family)
        }
        if term in normalized_members:
            return family_name
    return None


def _family_members(family_name: str, family: Mapping[str, Any]) -> list[str]:
    members = family.get("members")
    if not isinstance(members, list) or not all(isinstance(member, str) for member in members):
        raise ValueError(f"Adjacency family `{family_name}` must define a string `members` list.")
    return members


def _build_alias_lookup(aliases: Mapping[str, Iterable[str]]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for canonical_term, alias_values in aliases.items():
        canonical = canonical_term.strip()
        if not canonical:
            continue
        lookup[_lookup_key(canonical)] = canonical
        for alias_value in alias_values:
            alias = alias_value.strip()
            if alias:
                lookup[_lookup_key(alias)] = canonical
    return lookup


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a mapping at `{path}`.")
    return payload


def _lookup_key(term: str) -> str:
    return LOOKUP_KEY_RE.sub("", term.strip().casefold())
