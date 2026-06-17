from __future__ import annotations

import sqlite3
from pathlib import Path

from job_hunt_copilot.bootstrap import run_bootstrap
from job_hunt_copilot.send_lane import (
    SEND_LANE_QUEUE_FOLLOWUP,
    SEND_LANE_QUEUE_ORIGINAL,
    build_send_lane_window_summary,
    decide_shared_send_turn,
    followup_queue_has_sendable_now,
    shared_send_window,
)
from tests.support import create_minimal_project


def _bootstrap_connection(tmp_path: Path) -> sqlite3.Connection:
    project_root = tmp_path / "repo"
    project_root.mkdir()
    create_minimal_project(project_root)
    run_bootstrap(project_root=project_root)
    connection = sqlite3.connect(project_root / "job_hunt_copilot.db")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    return connection


def test_shared_send_window_alternates_every_two_hours_from_phoenix_midnight() -> None:
    midnight_window = shared_send_window("2026-06-15T07:00:00Z")
    boundary_window = shared_send_window("2026-06-15T09:00:00Z")

    assert midnight_window.preferred_queue_kind == SEND_LANE_QUEUE_FOLLOWUP
    assert boundary_window.preferred_queue_kind == SEND_LANE_QUEUE_ORIGINAL


def test_decide_shared_send_turn_uses_fallback_only_when_preferred_queue_is_empty() -> None:
    followup_preferred = decide_shared_send_turn(
        current_time="2026-06-15T19:00:00Z",
        original_sendable_now=True,
        followup_sendable_now=True,
    )
    fallback_to_original = decide_shared_send_turn(
        current_time="2026-06-15T19:00:00Z",
        original_sendable_now=True,
        followup_sendable_now=False,
    )

    assert followup_preferred.selected_queue_kind == SEND_LANE_QUEUE_FOLLOWUP
    assert followup_preferred.fallback_used is False
    assert fallback_to_original.selected_queue_kind == SEND_LANE_QUEUE_ORIGINAL
    assert fallback_to_original.fallback_used is True


def test_followup_queue_has_sendable_now_respects_auto_send_pause(tmp_path: Path) -> None:
    connection = _bootstrap_connection(tmp_path)
    project_root = tmp_path / "repo"
    draft_dir = project_root / "ops" / "followups" / "fp_1"
    draft_dir.mkdir(parents=True, exist_ok=True)
    (draft_dir / "followup_draft.md").write_text(
        "Hi Alex,\n\nQuick follow-up.\n\nIf you would be open to it, I would still value a brief 10-minute conversation.\n\nBest,\nAchyutaram Sonti\n",
        encoding="utf-8",
    )
    (draft_dir / "followup_review_evidence.json").write_text(
        "{\"payload\": {}}",
        encoding="utf-8",
    )
    connection.execute(
        """
        INSERT INTO contacts (
          contact_id, identity_key, display_name, company_name, origin_component,
          contact_status, full_name, first_name, current_working_email,
          created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "ct_1",
            "ct_1|exampleco",
            "Alex Example",
            "ExampleCo",
            "linkedin_scraping",
            "sent",
            "Alex Example",
            "Alex",
            "alex@example.com",
            "2026-06-09T18:39:00Z",
            "2026-06-09T18:39:00Z",
        ),
    )
    connection.execute(
        """
        INSERT INTO outreach_messages (
          outreach_message_id, contact_id, outreach_mode, recipient_email,
          message_status, subject, body_text, thread_id, sent_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "om_original",
            "ct_1",
            "role_targeted",
            "alex@example.com",
            "sent",
            "Learning from your career path",
            "Hi Alex,\n\nOriginal.\n\nBest,\nAchyutaram Sonti",
            "thread_1",
            "2026-06-09T18:39:00Z",
            "2026-06-09T18:39:00Z",
            "2026-06-09T18:39:00Z",
        ),
    )
    connection.execute(
        """
        INSERT INTO outreach_followup_plans (
          outreach_followup_plan_id, original_outreach_message_id, contact_id,
          plan_status, followup_sequence, eligible_after, draft_artifact_path,
          review_evidence_artifact_path, last_evaluated_at, agent_reviewed_at,
          created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "fp_1",
            "om_original",
            "ct_1",
            "agent_reviewed",
            1,
            "2026-06-14T00:00:00Z",
            "ops/followups/fp_1/followup_draft.md",
            "ops/followups/fp_1/followup_review_evidence.json",
            "2026-06-15T18:30:00Z",
            "2026-06-15T18:30:00Z",
            "2026-06-14T00:00:00Z",
            "2026-06-14T00:00:00Z",
        ),
    )
    connection.executemany(
        """
        INSERT INTO agent_control_state (control_key, control_value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(control_key) DO UPDATE SET
          control_value = excluded.control_value,
          updated_at = excluded.updated_at
        """,
        [
            ("followup_auto_send_enabled", "true", "2026-06-15T19:00:00Z"),
            ("followup_auto_send_paused", "false", "2026-06-15T19:00:00Z"),
            ("followup_initial_rollout_sent_count", "0", "2026-06-15T19:00:00Z"),
        ],
    )
    connection.commit()

    assert followup_queue_has_sendable_now(connection, current_time="2026-06-15T19:00:00Z") is True

    connection.execute(
        """
        INSERT INTO agent_control_state (control_key, control_value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(control_key) DO UPDATE SET
          control_value = excluded.control_value,
          updated_at = excluded.updated_at
        """,
        ("followup_auto_send_paused", "true", "2026-06-15T19:05:00Z"),
    )
    connection.commit()

    assert followup_queue_has_sendable_now(connection, current_time="2026-06-15T19:05:00Z") is False


def test_build_send_lane_window_summary_includes_next_window_preview() -> None:
    summary = build_send_lane_window_summary("2026-06-15T19:00:00Z")

    assert summary.active_window_preference == SEND_LANE_QUEUE_FOLLOWUP
    assert summary.next_window_preference == SEND_LANE_QUEUE_ORIGINAL
    assert summary.active_window_local_start.endswith("MST")
    assert summary.next_window_local_start.endswith("MST")
