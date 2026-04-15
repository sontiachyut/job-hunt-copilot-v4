from __future__ import annotations

from job_hunt_copilot.tailoring.keyword_system import (
    find_adjacent_match,
    load_adjacency_map,
    load_term_aliases,
    normalize_term,
)


def test_load_adjacency_map_contains_expected_frontend_family() -> None:
    adjacency_map = load_adjacency_map()

    assert "frontend_frameworks" in adjacency_map
    assert adjacency_map["frontend_frameworks"]["members"] == ["React", "Angular", "Vue", "Svelte"]
    assert adjacency_map["frontend_frameworks"]["skill_category_default"] == "Frontend & UI"


def test_find_adjacent_match_returns_family_when_profile_has_member() -> None:
    adjacency_map = load_adjacency_map()

    result = find_adjacent_match("Angular", {"React", "Python", "AWS"}, adjacency_map)

    assert result is not None
    assert result["family"] == "frontend_frameworks"
    assert result["matched_via"] == "React"
    assert result["skill_category_default"] == "Frontend & UI"


def test_find_adjacent_match_returns_none_when_no_family_member() -> None:
    adjacency_map = load_adjacency_map()

    result = find_adjacent_match("Angular", {"Python", "AWS"}, adjacency_map)

    assert result is None


def test_find_adjacent_match_uses_alias_normalization() -> None:
    adjacency_map = load_adjacency_map()
    aliases = load_term_aliases()

    result = find_adjacent_match("K8s", {"EKS", "Terraform"}, adjacency_map, aliases)

    assert result is not None
    assert result["family"] == "container_orchestration"
    assert result["normalized_requested_term"] == "K8s"
    assert result["matched_via"] == "EKS"


def test_normalize_term_resolves_aliases() -> None:
    aliases = load_term_aliases()

    assert normalize_term("Kubernetes", aliases) == "K8s"
    assert normalize_term("JS", aliases) == "JS"
    assert normalize_term("React", aliases) == "React.js"
    assert normalize_term("GraphQL", aliases) == "GraphQL"
