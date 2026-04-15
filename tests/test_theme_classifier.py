from __future__ import annotations

from job_hunt_copilot.tailoring.theme_classifier import classify_theme, load_theme_terms


def _make_signals(
    core_texts: list[str],
    must_have_texts: list[str] | None = None,
    nice_texts: list[str] | None = None,
    informational_texts: list[str] | None = None,
    role_title: str = "",
) -> dict[str, object]:
    signals: list[dict[str, object]] = []
    for index, text in enumerate(core_texts):
        signals.append(
            {
                "signal_id": f"signal_core_{index}",
                "priority": "core_responsibility",
                "signal": text,
                "tokens": text.lower().split(),
            }
        )
    for index, text in enumerate(must_have_texts or []):
        signals.append(
            {
                "signal_id": f"signal_must_{index}",
                "priority": "must_have",
                "signal": text,
                "tokens": text.lower().split(),
            }
        )
    for index, text in enumerate(nice_texts or []):
        signals.append(
            {
                "signal_id": f"signal_nice_{index}",
                "priority": "nice_to_have",
                "signal": text,
                "tokens": text.lower().split(),
            }
        )
    for index, text in enumerate(informational_texts or []):
        signals.append(
            {
                "signal_id": f"signal_info_{index}",
                "priority": "informational",
                "signal": text,
                "tokens": text.lower().split(),
            }
        )
    return {
        "signals": signals,
        "role_intent_summary": role_title,
    }


def test_load_theme_terms_contains_expected_nine_themes() -> None:
    theme_terms = load_theme_terms()

    assert list(theme_terms) == [
        "applied_ai",
        "agent_ai_systems",
        "forward_deployed_ai",
        "frontend_web",
        "backend_service",
        "distributed_infra",
        "platform_infra",
        "fullstack",
        "generalist",
    ]
    assert theme_terms["frontend_web"]["template"] == "runtime"
    assert "react" in theme_terms["frontend_web"]["terms"]


def test_garmin_aviation_classifies_as_frontend_web() -> None:
    signals = _make_signals(
        core_texts=[
            "Software Engineer 1 Aviation Web Development",
            "web development for customer facing Garmin aviation products",
            "software design and development using Angular JavaScript",
            "Troubleshoots basic issue reports and implements software solutions",
        ],
        must_have_texts=[
            "develop basic software in C C++ C# Java assembly language",
        ],
        role_title="Software Engineer 1 - Aviation Web Development",
    )

    result = classify_theme(signals)

    assert result["theme"] == "frontend_web"
    assert result["template"] == "runtime"
    assert result["scores"]["frontend_web"] > result["scores"]["backend_service"]


def test_agentic_ai_jd_classifies_as_agent_ai_systems() -> None:
    signals = _make_signals(
        core_texts=[
            "Build multi-agent autonomous workflows",
            "Design agentic AI systems with tool use and planning",
            "Implement function calling and orchestration pipelines",
        ],
        role_title="Agent AI Systems Engineer",
    )

    result = classify_theme(signals)

    assert result["theme"] == "agent_ai_systems"
    assert result["template"] == "A"


def test_distributed_infra_jd_classifies_correctly() -> None:
    signals = _make_signals(
        core_texts=[
            "Build distributed systems and data pipelines",
            "Optimize Apache Spark ETL throughput",
            "Maintain high-availability streaming infrastructure",
        ],
        role_title="Data Engineer",
    )

    result = classify_theme(signals)

    assert result["theme"] == "distributed_infra"
    assert result["template"] == "B"


def test_mixed_frontend_backend_classifies_as_fullstack() -> None:
    signals = _make_signals(
        core_texts=[
            "Build React frontend components",
            "Design REST API backend services",
            "Work across the full stack from database to UI",
        ],
        role_title="Full Stack Engineer",
    )

    result = classify_theme(signals)

    assert result["theme"] == "fullstack"
    assert result["template"] == "runtime"


def test_balanced_frontend_backend_mix_uses_fullstack_rule_without_keyword() -> None:
    signals = _make_signals(
        core_texts=[
            "Build React frontend UI components",
            "Design backend REST API services",
        ],
        role_title="Software Engineer",
    )

    result = classify_theme(signals)

    assert result["theme"] == "fullstack"
    assert result["confidence"] > result["scores"]["frontend_web"]
    assert result["confidence"] > result["scores"]["backend_service"]


def test_no_clear_theme_falls_back_to_generalist() -> None:
    signals = _make_signals(
        core_texts=[
            "Work on various software projects",
            "Collaborate with team members",
        ],
        role_title="Software Engineer",
    )

    result = classify_theme(signals)

    assert result["theme"] == "generalist"
    assert result["template"] == "runtime"


def test_informational_signals_are_ignored_for_theme_selection() -> None:
    signals = _make_signals(
        core_texts=[
            "Build backend API services and authentication middleware",
        ],
        informational_texts=[
            "Frontend team happens to use React and Angular for another product",
        ],
        role_title="Backend Engineer",
    )

    result = classify_theme(signals)

    assert result["theme"] == "backend_service"
    assert result["scores"]["frontend_web"] < result["scores"]["backend_service"]


def test_result_includes_all_scores_and_runner_up_metadata() -> None:
    signals = _make_signals(
        core_texts=["Build React web applications"],
        role_title="Frontend Engineer",
    )

    result = classify_theme(signals)

    assert set(result["scores"]) == {
        "applied_ai",
        "agent_ai_systems",
        "forward_deployed_ai",
        "frontend_web",
        "backend_service",
        "distributed_infra",
        "platform_infra",
        "fullstack",
        "generalist",
    }
    assert result["runner_up"] in result["scores"]
    assert isinstance(result["margin"], float)
    assert isinstance(result["confidence"], float)
    assert "react" in result["matched_terms"]["frontend_web"]
