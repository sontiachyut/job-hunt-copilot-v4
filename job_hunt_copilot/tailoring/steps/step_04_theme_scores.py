from __future__ import annotations

from typing import Any, Mapping

from ..theme_classifier import classify_theme


def build_step_04_artifact(
    *,
    posting_row: Mapping[str, Any],
    run: Any,
    step_03_payload: Mapping[str, Any],
) -> dict[str, Any]:
    classification = classify_theme(step_03_payload)
    theme_scores = {
        str(theme_id): float(score)
        for theme_id, score in dict(classification.get("scores") or {}).items()
    }
    matched_terms = {
        str(theme_id): list(terms)
        for theme_id, terms in dict(classification.get("matched_terms") or {}).items()
    }
    ranked_themes = _ranked_themes(theme_scores)

    return {
        "job_posting_id": posting_row["job_posting_id"],
        "resume_tailoring_run_id": run.resume_tailoring_run_id,
        "status": "generated",
        "role_title": step_03_payload.get("role_title") or posting_row["role_title"],
        "classified_signal_count": len(step_03_payload.get("signals") or []),
        "signal_priority_weights": dict(step_03_payload.get("signal_priority_weights") or {}),
        "theme_signal_weights": dict(step_03_payload.get("theme_signal_weights") or {}),
        "theme_scores": theme_scores,
        "matched_terms": matched_terms,
        "score_ranking": [
            {
                "rank": index + 1,
                "theme": theme_id,
                "score": theme_scores[theme_id],
                "matched_terms": matched_terms.get(theme_id, []),
                "matched_term_count": len(matched_terms.get(theme_id, [])),
            }
            for index, theme_id in enumerate(ranked_themes)
        ],
        "decision_basis": {
            "leading_theme": classification.get("theme"),
            "template_hint": classification.get("template"),
            "runner_up_theme": classification.get("runner_up"),
            "margin": float(classification.get("margin") or 0.0),
            "confidence": float(classification.get("confidence") or 0.0),
        },
    }


def _ranked_themes(theme_scores: Mapping[str, float]) -> list[str]:
    ordering = list(theme_scores)
    return sorted(
        ordering,
        key=lambda theme_id: (-theme_scores.get(theme_id, 0.0), ordering.index(theme_id)),
    )
