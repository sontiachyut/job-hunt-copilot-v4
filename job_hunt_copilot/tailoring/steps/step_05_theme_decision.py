from __future__ import annotations

from typing import Any, Mapping

from ..theme_classifier import load_theme_terms


def build_step_05_artifact(
    *,
    posting_row: Mapping[str, Any],
    run: Any,
    step_04_payload: Mapping[str, Any],
) -> dict[str, Any]:
    theme_scores = {
        str(theme_id): float(score)
        for theme_id, score in dict(step_04_payload.get("theme_scores") or {}).items()
    }
    ranked_themes = _ranked_themes(theme_scores)
    decision_basis = step_04_payload.get("decision_basis") or {}

    selected_theme = str(
        decision_basis.get("leading_theme") or (ranked_themes[0] if ranked_themes else "generalist")
    )
    runner_up_theme = str(
        decision_basis.get("runner_up_theme")
        or (ranked_themes[1] if len(ranked_themes) > 1 else selected_theme)
    )
    confidence = float(
        decision_basis.get("confidence")
        if decision_basis.get("confidence") is not None
        else theme_scores.get(selected_theme, 0.0)
    )
    runner_up_score = theme_scores.get(runner_up_theme, 0.0)
    margin = float(
        decision_basis.get("margin")
        if decision_basis.get("margin") is not None
        else confidence - runner_up_score
    )

    theme_terms = load_theme_terms()
    template = str(
        decision_basis.get("template_hint")
        or theme_terms.get(selected_theme, {}).get("template", "runtime")
    )
    selected_template = template if template in {"A", "B"} else None
    layout_mode = "fixed_template" if selected_template is not None else "runtime_deferred"
    hero_section, supporting_section = _layout_sections(selected_template)

    return {
        "job_posting_id": posting_row["job_posting_id"],
        "resume_tailoring_run_id": run.resume_tailoring_run_id,
        "status": "generated",
        "role_title": step_04_payload.get("role_title") or posting_row["role_title"],
        "theme": selected_theme,
        "selected_theme": selected_theme,
        "runner_up": runner_up_theme,
        "runner_up_theme": runner_up_theme,
        "margin": margin,
        "confidence": confidence,
        "template": template,
        "selected_template": selected_template,
        "layout_mode": layout_mode,
        "hero_section": hero_section,
        "supporting_section": supporting_section,
        "reasoning": _build_reasoning(
            selected_theme=selected_theme,
            confidence=confidence,
            runner_up_theme=runner_up_theme,
            runner_up_score=runner_up_score,
            margin=margin,
            template=template,
        ),
        "score_ranking": list(step_04_payload.get("score_ranking") or []),
        "template_decision": {
            "template": template,
            "selected_template": selected_template,
            "decision_mode": layout_mode,
            "decision_status": "resolved" if selected_template is not None else "deferred",
            "hero_section": hero_section,
            "supporting_section": supporting_section,
            "deferred_until_step": 9 if selected_template is None else None,
            "template_candidates": ["A", "B"] if selected_template is None else [selected_template],
        },
    }


def _ranked_themes(theme_scores: Mapping[str, float]) -> list[str]:
    ordering = list(theme_scores)
    return sorted(
        ordering,
        key=lambda theme_id: (-theme_scores.get(theme_id, 0.0), ordering.index(theme_id)),
    )


def _layout_sections(template: str | None) -> tuple[str | None, str | None]:
    if template == "A":
        return "projects", "experience"
    if template == "B":
        return "experience", "projects"
    return None, None


def _build_reasoning(
    *,
    selected_theme: str,
    confidence: float,
    runner_up_theme: str,
    runner_up_score: float,
    margin: float,
    template: str,
) -> list[str]:
    reasoning = [
        f"Selected theme `{selected_theme}` with score {confidence:.1f}.",
        f"Runner-up `{runner_up_theme}` scored {runner_up_score:.1f}, for a margin of {margin:.1f}.",
    ]
    if template in {"A", "B"}:
        reasoning.append(f"Theme `{selected_theme}` maps directly to Template {template}.")
    else:
        reasoning.append(
            f"Theme `{selected_theme}` uses runtime template routing, so the A/B decision is deferred until Step 9."
        )
    return reasoning
