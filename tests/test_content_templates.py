from __future__ import annotations

import pytest

from job_hunt_copilot.tailoring.content_templates import (
    get_skill_categories,
    get_summary_template,
    load_skill_categories,
    load_summary_templates,
)
from job_hunt_copilot.tailoring.theme_classifier import EXPECTED_THEMES


def test_load_summary_templates_covers_all_expected_themes() -> None:
    templates = load_summary_templates()

    assert list(templates) == list(EXPECTED_THEMES)
    assert templates["frontend_web"].startswith(
        "Software engineer with 3+ years of experience building production web applications"
    )
    assert "agent workflows" in templates["agent_ai_systems"]


def test_get_summary_template_returns_theme_specific_copy() -> None:
    template = get_summary_template("platform_infra")

    assert "observability" in template
    assert "containerized distributed systems" in template


def test_load_skill_categories_returns_expected_frontend_layout() -> None:
    categories = load_skill_categories()

    assert list(categories) == list(EXPECTED_THEMES)
    assert categories["frontend_web"] == [
        {"name": "Languages", "pool_sources": ["languages"]},
        {"name": "Frontend \\& UI", "pool_sources": ["frontend & mobile"]},
        {"name": "Backend \\& Data", "pool_sources": ["backend", "data & storage"]},
        {"name": "Cloud \\& DevOps", "pool_sources": ["cloud & devops"]},
        {"name": "Testing \\& Reliability", "pool_sources": ["testing & reliability"]},
    ]


def test_get_skill_categories_returns_copy_of_theme_template() -> None:
    categories = get_skill_categories("generalist")
    categories[0]["name"] = "Mutated"

    reloaded = get_skill_categories("generalist")

    assert reloaded[0]["name"] == "Languages"
    assert reloaded[1]["name"] == "Application \\& Systems"


def test_getters_reject_unknown_theme() -> None:
    with pytest.raises(ValueError, match="Unknown theme"):
        get_summary_template("security")

    with pytest.raises(ValueError, match="Unknown theme"):
        get_skill_categories("security")
