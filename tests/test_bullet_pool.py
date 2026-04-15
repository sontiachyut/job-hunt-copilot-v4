from __future__ import annotations

from job_hunt_copilot.tailoring.bullet_pool import (
    filter_bullets_by_theme,
    get_bullets_for_entry,
    load_experience_pool,
    rank_bullets_by_jd_overlap,
)


def test_load_experience_pool_returns_expected_entries_and_limits() -> None:
    pool = load_experience_pool()

    assert list(pool) == ["swe_role", "associate_swe_role", "intern_role"]
    assert pool["swe_role"]["bullet_limits"] == {"min": 3, "max": 4}
    assert pool["associate_swe_role"]["bullet_limits"] == {"min": 2, "max": 3}
    assert pool["intern_role"]["bullet_limits"] == {"min": 1, "max": 1}


def test_get_bullets_for_entry_returns_validated_variants() -> None:
    pool = load_experience_pool()
    swe_bullets = get_bullets_for_entry(pool, "swe_role")

    assert len(swe_bullets) == 16
    assert all("bullet_id" in bullet for bullet in swe_bullets)
    assert all("text" in bullet for bullet in swe_bullets)
    assert all("themes" in bullet for bullet in swe_bullets)
    assert all(bullet["source"] == "swe_role" for bullet in swe_bullets)
    assert len({bullet["bullet_id"] for bullet in swe_bullets}) == len(swe_bullets)


def test_filter_bullets_by_theme_returns_matching_variants_without_crossing_groups() -> None:
    pool = load_experience_pool()
    swe_bullets = get_bullets_for_entry(pool, "swe_role")

    distributed = filter_bullets_by_theme(swe_bullets, "distributed_infra")
    frontend = filter_bullets_by_theme(swe_bullets, "frontend_web")

    distributed_ids = {bullet["bullet_id"] for bullet in distributed}
    frontend_ids = {bullet["bullet_id"] for bullet in frontend}

    assert distributed_ids == {
        "swe_scale_distributed",
        "swe_delivery_distributed",
        "swe_optimization_distributed",
        "swe_reliability_distributed",
    }
    assert frontend_ids == {
        "swe_scale_frontend",
        "swe_delivery_frontend",
        "swe_optimization_frontend",
        "swe_reliability_frontend",
    }
    assert not distributed_ids & frontend_ids


def test_rank_bullets_by_jd_overlap_prefers_frontend_swe_variants() -> None:
    pool = load_experience_pool()
    swe_bullets = get_bullets_for_entry(pool, "swe_role")

    ranked = rank_bullets_by_jd_overlap(
        swe_bullets,
        {"dashboard", "customer-facing", "web", "analytics"},
    )

    assert ranked[0]["bullet_id"] == "swe_scale_frontend"
    assert ranked[1]["bullet_id"] == "swe_delivery_frontend"


def test_rank_bullets_by_jd_overlap_uses_alias_normalization_for_intern_variants() -> None:
    pool = load_experience_pool()
    intern_bullets = get_bullets_for_entry(pool, "intern_role")

    ranked = rank_bullets_by_jd_overlap(intern_bullets, {"React", "Node", "frontend"})

    assert ranked[0]["bullet_id"] == "intern_frontend"
