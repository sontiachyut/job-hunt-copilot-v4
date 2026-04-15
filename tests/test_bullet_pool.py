from __future__ import annotations

from job_hunt_copilot.tailoring.bullet_pool import (
    filter_atoms_by_theme,
    filter_bullets_by_theme,
    get_bullets_for_entry,
    get_project_atoms,
    load_experience_pool,
    load_project_pool,
    rank_bullets_by_jd_overlap,
    rank_project_atoms_by_jd_overlap,
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


def test_load_project_pool_returns_expected_projects() -> None:
    pool = load_project_pool()

    assert set(pool) == {
        "job_hunt_copilot",
        "linkedin_assistant",
        "tiaa_platform",
        "edge_face_recognition",
        "national_parks_viz",
        "health_monitoring",
        "content_rec_engine",
        "cloud_meraki",
    }


def test_get_project_atoms_returns_validated_atoms() -> None:
    pool = load_project_pool()
    atoms = get_project_atoms(pool, "job_hunt_copilot")

    assert len(atoms) == 5
    assert all("atom_id" in atom for atom in atoms)
    assert all("what" in atom for atom in atoms)
    assert all("themes" in atom for atom in atoms)
    assert all("tech" in atom for atom in atoms)
    assert len({atom["atom_id"] for atom in atoms}) == len(atoms)


def test_filter_atoms_by_theme_returns_agentic_job_hunt_copilot_atoms() -> None:
    pool = load_project_pool()
    atoms = get_project_atoms(pool, "job_hunt_copilot")

    agentic_atoms = filter_atoms_by_theme(atoms, "agent_ai_systems")

    assert {atom["atom_id"] for atom in agentic_atoms} == {
        "jhc_supervisor_runtime",
        "jhc_contract_audit",
        "jhc_operator_controls",
        "jhc_validation_surface",
    }


def test_rank_project_atoms_by_jd_overlap_uses_alias_normalization() -> None:
    pool = load_project_pool()
    atoms = get_project_atoms(pool, "content_rec_engine")

    ranked = rank_project_atoms_by_jd_overlap(atoms, {"React", "Node", "Express"})

    assert ranked[0]["atom_id"] == "cre_fullstack_platform"
