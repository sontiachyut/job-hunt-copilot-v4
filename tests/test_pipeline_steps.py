from __future__ import annotations

from types import SimpleNamespace

from job_hunt_copilot.tailoring.steps import (
    build_step_01_artifact,
    build_step_02_artifact,
    build_step_03_artifact,
    build_step_04_artifact,
    build_step_05_artifact,
)


RUN = SimpleNamespace(resume_tailoring_run_id="rtr_test")
POSTING_ROW = {
    "job_posting_id": "jp_test",
    "role_title": "Frontend Software Engineer",
}


def test_step_01_identifies_jd_sections_and_boundaries() -> None:
    payload = build_step_01_artifact(
        posting_row=POSTING_ROW,
        run=RUN,
        jd_text=(
            "Responsibilities\n"
            "- Build Angular and TypeScript interfaces for customer-facing workflows.\n"
            "- Collaborate with designers and backend engineers.\n"
            "Minimum Qualifications\n"
            "- 3+ years of software engineering experience.\n"
            "Preferred Qualifications\n"
            "- React experience.\n"
            "Benefits\n"
            "- Comprehensive health coverage.\n"
        ),
    )

    assert payload["status"] == "generated"
    assert [section["heading"] for section in payload["sections"]] == [
        "Responsibilities",
        "Minimum Qualifications",
        "Preferred Qualifications",
        "Benefits",
    ]
    assert [section["section_type"] for section in payload["sections"]] == [
        "core_responsibility",
        "must_have",
        "nice_to_have",
        "informational",
    ]
    assert payload["sections"][0]["start_line"] == 1
    assert payload["sections"][0]["end_line"] == 3
    assert payload["sections"][1]["lines"][0]["line_number"] == 5


def test_step_02_extracts_meaningful_lines_and_skips_policy_noise() -> None:
    step_01_payload = build_step_01_artifact(
        posting_row=POSTING_ROW,
        run=RUN,
        jd_text=(
            "Responsibilities\n"
            "- Build responsive Angular dashboards.\n"
            "Internal Application Policy\n"
            "- Internal applicants must be in good standing.\n"
            "Preferred Qualifications\n"
            "- Familiarity with accessibility testing.\n"
        ),
    )

    payload = build_step_02_artifact(
        posting_row=POSTING_ROW,
        run=RUN,
        step_01_payload=step_01_payload,
    )

    extracted_text = [signal["raw_text"] for signal in payload["signals"]]
    assert payload["status"] == "generated"
    assert extracted_text == [
        "Build responsive Angular dashboards.",
        "Familiarity with accessibility testing.",
    ]
    assert payload["signals"][0]["source_section_type"] == "core_responsibility"
    assert payload["signals"][1]["source_section_type"] == "nice_to_have"


def test_step_03_classifies_signals_and_uses_spec_weighting() -> None:
    step_01_payload = build_step_01_artifact(
        posting_row=POSTING_ROW,
        run=RUN,
        jd_text=(
            "Responsibilities\n"
            "- Build Angular and JavaScript interfaces for customer-facing workflows.\n"
            "- Own UI quality and accessibility improvements.\n"
            "Minimum Qualifications\n"
            "- 3+ years of software engineering experience.\n"
            "- Full-time role on a hybrid schedule.\n"
            "Preferred Qualifications\n"
            "- React experience.\n"
            "Internal Application Policy\n"
            "- Equal employment opportunity without discrimination.\n"
        ),
    )
    step_02_payload = build_step_02_artifact(
        posting_row=POSTING_ROW,
        run=RUN,
        step_01_payload=step_01_payload,
    )

    payload = build_step_03_artifact(
        posting_row=POSTING_ROW,
        run=RUN,
        step_02_payload=step_02_payload,
        jd_text=(
            "Responsibilities\n"
            "- Build Angular and JavaScript interfaces for customer-facing workflows.\n"
            "- Own UI quality and accessibility improvements.\n"
            "Minimum Qualifications\n"
            "- 3+ years of software engineering experience.\n"
            "- Full-time role on a hybrid schedule.\n"
            "Preferred Qualifications\n"
            "- React experience.\n"
        ),
    )

    assert payload["status"] == "generated"
    assert payload["signal_priority_weights"] == {
        "must_have": 1.0,
        "core_responsibility": 2.0,
        "nice_to_have": 0.5,
        "informational": 0.0,
    }
    assert payload["theme_signal_weights"]["role_title"] == 2.0

    priorities = {
        signal["signal"]: signal["priority"]
        for signal in payload["signals"]
    }
    assert priorities["Build Angular and JavaScript interfaces for customer-facing workflows."] == (
        "core_responsibility"
    )
    assert priorities["3+ years of software engineering experience."] == "must_have"
    assert priorities["Full-time role on a hybrid schedule."] == "informational"
    assert priorities["React experience."] == "nice_to_have"

    angular_signal = next(
        signal for signal in payload["signals"] if "Angular" in signal["signal"]
    )
    assert angular_signal["weight"] == 2.0
    assert "angular" in angular_signal["tokens"]
    assert payload["role_metadata"]["employment_type"] == "Full-time"
    assert payload["role_metadata"]["location"] == "hybrid"


def test_step_04_scores_all_themes_and_favors_frontend_web_for_garmin_like_jd() -> None:
    step_01_payload = build_step_01_artifact(
        posting_row=POSTING_ROW,
        run=RUN,
        jd_text=(
            "Responsibilities\n"
            "- Build Angular and JavaScript web interfaces for customer-facing aviation workflows.\n"
            "- Own accessibility and responsive browser experiences.\n"
            "Minimum Qualifications\n"
            "- 3+ years of software engineering experience.\n"
            "- Experience with TypeScript and UI component development.\n"
        ),
    )
    step_02_payload = build_step_02_artifact(
        posting_row=POSTING_ROW,
        run=RUN,
        step_01_payload=step_01_payload,
    )
    step_03_payload = build_step_03_artifact(
        posting_row=POSTING_ROW,
        run=RUN,
        step_02_payload=step_02_payload,
        jd_text=(
            "Responsibilities\n"
            "- Build Angular and JavaScript web interfaces for customer-facing aviation workflows.\n"
            "- Own accessibility and responsive browser experiences.\n"
            "Minimum Qualifications\n"
            "- 3+ years of software engineering experience.\n"
            "- Experience with TypeScript and UI component development.\n"
        ),
    )

    payload = build_step_04_artifact(
        posting_row=POSTING_ROW,
        run=RUN,
        step_03_payload=step_03_payload,
    )

    assert payload["status"] == "generated"
    assert len(payload["theme_scores"]) == 9
    assert payload["theme_scores"]["frontend_web"] > payload["theme_scores"]["distributed_infra"]
    assert payload["decision_basis"]["leading_theme"] == "frontend_web"
    assert payload["score_ranking"][0]["theme"] == "frontend_web"


def test_step_05_records_theme_decision_and_runtime_template_deferral() -> None:
    step_04_payload = build_step_04_artifact(
        posting_row=POSTING_ROW,
        run=RUN,
        step_03_payload={
            "role_title": "Software Engineer 1 - Aviation Web Development",
            "signal_priority_weights": {
                "must_have": 1.0,
                "core_responsibility": 2.0,
                "nice_to_have": 0.5,
                "informational": 0.0,
            },
            "theme_signal_weights": {
                "role_title": 2.0,
                "must_have": 1.0,
                "core_responsibility": 2.0,
                "nice_to_have": 0.5,
                "informational": 0.0,
            },
            "signals": [
                {
                    "signal_id": "signal_core_1",
                    "priority": "core_responsibility",
                    "signal": (
                        "Build Angular and TypeScript customer-facing web experiences with strong accessibility."
                    ),
                    "tokens": [
                        "build",
                        "angular",
                        "typescript",
                        "customer-facing",
                        "web",
                        "accessibility",
                    ],
                }
            ],
        },
    )

    payload = build_step_05_artifact(
        posting_row=POSTING_ROW,
        run=RUN,
        step_04_payload=step_04_payload,
    )

    assert payload["status"] == "generated"
    assert payload["theme"] == "frontend_web"
    assert payload["template"] == "runtime"
    assert payload["selected_template"] is None
    assert payload["layout_mode"] == "runtime_deferred"
    assert payload["runner_up"] in {row["theme"] for row in payload["score_ranking"]}
    assert payload["margin"] > 0.0
    assert payload["template_decision"]["deferred_until_step"] == 9
    assert payload["reasoning"]
