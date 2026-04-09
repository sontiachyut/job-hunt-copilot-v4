from __future__ import annotations

import os
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from .contracts import CONTRACT_VERSION
from .paths import ProjectPaths
from .records import now_utc_iso
from .supervisor import (
    AGENT_MODE_PAUSED,
    AGENT_MODE_REPLANNING,
    AGENT_MODE_RUNNING,
    AGENT_MODE_STOPPED,
    AUTO_PAUSE_CRITICAL_INCIDENT_TYPES,
    REVIEW_PACKET_STATUS_PENDING,
    UNRESOLVED_INCIDENT_STATUSES,
    registered_supervisor_action_catalog,
    read_agent_control_state,
)

RUNTIME_AGENT_NAME = "job-hunt-copilot-supervisor"
RUNTIME_AGENT_ROLE = "operations / supervisor agent"


def write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", delete=False, dir=path.parent, encoding="utf-8") as handle:
        handle.write(content)
        tmp_path = Path(handle.name)
    os.replace(tmp_path, path)


def write_yaml_atomic(path: Path, payload: dict[str, Any]) -> None:
    write_text_atomic(path, yaml.safe_dump(payload, sort_keys=False))


def materialize_runtime_pack(project_root: Path | str | None = None) -> dict[str, Any]:
    paths = ProjectPaths.from_root(project_root)
    generated_at = now_utc_iso()
    runtime_snapshot = load_runtime_snapshot(paths)

    created_paths: list[str] = []
    updated_paths: list[str] = []
    preserved_paths: list[str] = []

    generated_yaml_payloads = {
        paths.ops_agent_identity_path: build_identity_payload(paths, generated_at),
        paths.ops_agent_policies_path: build_policies_payload(generated_at),
        paths.ops_agent_action_catalog_path: build_action_catalog_payload(generated_at),
        paths.ops_agent_service_goals_path: build_service_goals_payload(generated_at),
        paths.ops_agent_escalation_policy_path: build_escalation_policy_payload(paths, generated_at),
    }
    for path, payload in generated_yaml_payloads.items():
        if path.exists():
            updated_paths.append(str(path))
        else:
            created_paths.append(str(path))
        write_yaml_atomic(path, payload)

    generated_markdown_payloads = {
        paths.ops_agent_chat_bootstrap_path: render_chat_bootstrap(paths, runtime_snapshot, generated_at),
        paths.ops_agent_supervisor_bootstrap_path: render_supervisor_bootstrap(
            paths,
            runtime_snapshot,
            generated_at,
        ),
    }
    for path, content in generated_markdown_payloads.items():
        if path.exists():
            updated_paths.append(str(path))
        else:
            created_paths.append(str(path))
        write_text_atomic(path, content)

    initial_state_surfaces = {
        paths.ops_agent_progress_log_path: render_initial_progress_log(paths, runtime_snapshot, generated_at),
        paths.ops_agent_ops_plan_path: build_initial_ops_plan(runtime_snapshot, generated_at),
    }
    for path, payload in initial_state_surfaces.items():
        if path.exists():
            preserved_paths.append(str(path))
            continue
        if isinstance(payload, str):
            write_text_atomic(path, payload)
        else:
            write_yaml_atomic(path, payload)
        created_paths.append(str(path))

    return {
        "contract_version": CONTRACT_VERSION,
        "generated_at": generated_at,
        "project_root": str(paths.project_root),
        "created_paths": created_paths,
        "updated_paths": updated_paths,
        "preserved_paths": preserved_paths,
        "agent_mode": runtime_snapshot["agent_mode"],
        "latest_cycle_result": runtime_snapshot["latest_cycle_result"],
    }


def load_runtime_snapshot(paths: ProjectPaths) -> dict[str, Any]:
    snapshot = {
        "agent_enabled": False,
        "agent_mode": AGENT_MODE_STOPPED,
        "pause_reason": None,
        "latest_cycle_id": None,
        "latest_cycle_result": "not_started",
        "latest_cycle_completed_at": None,
        "open_incident_count": 0,
        "pending_review_count": 0,
        "active_pipeline_run_count": 0,
        "top_focus": "Autonomous execution is stopped until the operator enables the local supervisor.",
        "next_likely_action": "Use `jhc-agent-start` to enable the first heartbeat or inspect canonical control state directly.",
    }

    if not paths.db_path.exists():
        return snapshot

    connection = sqlite3.connect(paths.db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    try:
        control_state = read_agent_control_state(connection)
        latest_cycle = connection.execute(
            """
            SELECT supervisor_cycle_id, result, completed_at
            FROM supervisor_cycles
            ORDER BY started_at DESC, supervisor_cycle_id DESC
            LIMIT 1
            """
        ).fetchone()
        open_incident_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM agent_incidents
            WHERE status IN ({})
            """.format(",".join("?" for _ in UNRESOLVED_INCIDENT_STATUSES)),
            tuple(UNRESOLVED_INCIDENT_STATUSES),
        ).fetchone()[0]
        pending_review_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM expert_review_packets
            WHERE packet_status = ?
            """,
            (REVIEW_PACKET_STATUS_PENDING,),
        ).fetchone()[0]
        active_pipeline_run_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM pipeline_runs
            WHERE run_status IN ('in_progress', 'paused')
            """
        ).fetchone()[0]
    finally:
        connection.close()

    latest_cycle_result = "not_started"
    latest_cycle_id = None
    latest_cycle_completed_at = None
    if latest_cycle is not None:
        latest_cycle_id = latest_cycle["supervisor_cycle_id"]
        latest_cycle_result = latest_cycle["result"]
        latest_cycle_completed_at = latest_cycle["completed_at"]

    snapshot.update(
        {
            "agent_enabled": control_state.agent_enabled,
            "agent_mode": control_state.agent_mode,
            "pause_reason": control_state.pause_reason,
            "latest_cycle_id": latest_cycle_id,
            "latest_cycle_result": latest_cycle_result,
            "latest_cycle_completed_at": latest_cycle_completed_at,
            "open_incident_count": open_incident_count,
            "pending_review_count": pending_review_count,
            "active_pipeline_run_count": active_pipeline_run_count,
        }
    )
    snapshot["top_focus"] = compute_top_focus(snapshot)
    snapshot["next_likely_action"] = compute_next_likely_action(snapshot)
    return snapshot


def compute_top_focus(snapshot: dict[str, Any]) -> str:
    if snapshot["agent_mode"] == AGENT_MODE_STOPPED:
        return "Autonomous execution is stopped until the operator enables the local supervisor."
    if snapshot["agent_mode"] == AGENT_MODE_PAUSED:
        reason = snapshot["pause_reason"] or "an unresolved safety or control-state condition"
        return f"Resolve the active pause reason before ordinary pipeline progression resumes: {reason}."
    if snapshot["agent_mode"] == AGENT_MODE_REPLANNING:
        return "Finish the bounded replanning pass before new pipeline or send work begins."
    if snapshot["open_incident_count"]:
        return "Unresolved incidents outrank ordinary pipeline progression in the current control model."
    if snapshot["pending_review_count"]:
        return "Pending expert review packets need inspection before related follow-up guidance is applied."
    if snapshot["active_pipeline_run_count"]:
        return "Resume one durable pipeline run at a time and checkpoint bounded progress."
    if snapshot["agent_mode"] == AGENT_MODE_RUNNING:
        return "Continue bounded supervisor cycles against due work while honoring control-state semantics."
    return "Keep the runtime pack, canonical state, and review surfaces aligned."


def compute_next_likely_action(snapshot: dict[str, Any]) -> str:
    if snapshot["agent_mode"] == AGENT_MODE_STOPPED:
        return "Use `jhc-agent-start` or an explicit resume command to enable the local supervisor."
    if snapshot["agent_mode"] == AGENT_MODE_PAUSED:
        return "Inspect the blocking incidents or pause reason, then persist a clear resume or stop decision."
    if snapshot["open_incident_count"]:
        return "Escalate or repair the highest-priority unresolved incident before normal advancement."
    if snapshot["pending_review_count"]:
        return "Surface the pending review packet queue to the expert-facing operator."
    if snapshot["active_pipeline_run_count"]:
        return "Resume the next supported non-terminal pipeline run from canonical state."
    return "Wait for the next due control-state change, incident, or eligible pipeline work unit."


def build_identity_payload(paths: ProjectPaths, generated_at: str) -> dict[str, Any]:
    return {
        "contract_version": CONTRACT_VERSION,
        "generated_at": generated_at,
        "agent_name": RUNTIME_AGENT_NAME,
        "role": RUNTIME_AGENT_ROLE,
        "project_name": "job-hunt-copilot-v4",
        "mission_summary": (
            "Run the local Job Hunt Copilot product workflow through canonical state, "
            "bounded supervisor cycles, expert-review packets, and explicit pause or escalation behavior."
        ),
        "deployment_shape": "local single-user macOS launchd heartbeat",
        "owned_components": [
            "agent control state and runtime leases",
            "durable pipeline runs and supervisor-cycle audit",
            "agent incidents, expert review packets, and override lineage",
            "runtime pack, progress surfaces, and context snapshots under ops/",
        ],
        "allowed_actions_summary": [
            "Read canonical SQLite state and the generated runtime pack under ops/agent/.",
            "Choose only registered bounded actions from action-catalog.yaml for autonomous progression.",
            "Persist incidents, review packets, override lineage, and context snapshots when relevant.",
            "Honor canonical paused, stopped, running, and replanning control-state semantics.",
        ],
        "forbidden_actions_summary": [
            "Do not improvise uncataloged autonomous actions; escalate instead.",
            "Do not create duplicate non-terminal pipeline runs for one job posting.",
            "Do not treat filesystem artifacts as canonical lifecycle truth over job_hunt_copilot.db.",
            "Do not expose runtime secrets in incidents, review packets, or progress surfaces.",
        ],
        "canonical_state_locations": {
            "project_root": str(paths.project_root),
            "database": str(paths.db_path),
            "ops_agent_dir": str(paths.ops_agent_dir),
            "progress_log": str(paths.ops_agent_progress_log_path),
            "ops_plan": str(paths.ops_agent_ops_plan_path),
            "review_packets_dir": str(paths.ops_review_packets_dir),
            "incidents_dir": str(paths.ops_incidents_dir),
            "context_snapshots_dir": str(paths.ops_agent_context_snapshots_dir),
        },
    }


def build_policies_payload(generated_at: str) -> dict[str, Any]:
    return {
        "contract_version": CONTRACT_VERSION,
        "generated_at": generated_at,
        "mandatory_review_gates": [
            {
                "gate_id": "resume_tailoring_agent_review",
                "scope": "job_posting",
                "policy": "Outreach-side work begins only after the active tailoring run is approved.",
                "implementation_status": "planned_downstream",
            },
            {
                "gate_id": "post_run_expert_review_packet",
                "scope": "pipeline_run",
                "policy": "Review-worthy terminal run outcomes generate a pending expert review packet.",
                "implementation_status": "implemented",
            },
        ],
        "safety_boundaries": [
            "Read canonical control state before selecting work in each supervisor cycle.",
            "Select at most one primary work unit or one tightly related cluster per cycle.",
            "Validate prerequisites before execution and expected outputs after execution.",
            "When the needed next move is not covered by the registered catalog, escalate instead of improvising.",
        ],
        "send_policies_and_pacing": {
            "implementation_status": "planned_downstream",
            "rules": [
                "Due sends outrank new Gmail ingestion and maintenance when sending support exists.",
                "Duplicate-send risk and send-safety incidents are auto-pause critical.",
                "Required pacing must be honored before new automatic sends begin.",
            ],
        },
        "retry_repair_limits": [
            "Only bounded, explicitly cataloged repair work may proceed automatically.",
            "Unsupported or exhausted cases escalate instead of looping indefinitely.",
        ],
        "pause_resume_stop_semantics": {
            "running": "agent_enabled=true and agent_mode=running; normal autonomous progression may continue.",
            "paused": "agent_enabled=true and agent_mode=paused; new pipeline progression and automatic sends stay blocked while safe observational work may continue.",
            "stopped": "agent_enabled=false and agent_mode=stopped; background autonomous execution is disabled until restarted.",
            "replanning": "agent_enabled=true and agent_mode=replanning; no new pipeline runs, automatic sends, or maintenance merges begin during the bounded replanning pass.",
        },
        "override_semantics": [
            "Expert review decisions and override events persist explicit lineage in canonical state.",
            "Future control or object-state changes should record why the override happened rather than silently mutating history.",
            "The direct expert-facing `jhc-chat` entrypoint now exists; deeper review and control behaviors still build on the same canonical persistence.",
        ],
    }


def build_action_catalog_payload(generated_at: str) -> dict[str, Any]:
    actions = []
    for entry in registered_supervisor_action_catalog().values():
        actions.append(
            {
                "action_id": entry.action_id,
                "scope": entry.work_type,
                "description": entry.description,
                "prerequisites": list(entry.prerequisites),
                "expected_outputs": list(entry.expected_outputs),
                "validation_references": list(entry.validation_references),
            }
        )

    return {
        "contract_version": CONTRACT_VERSION,
        "generated_at": generated_at,
        "catalog_scope": {
            "implementation_status": "narrow_current_build",
            "note": (
                "This generated catalog mirrors the actions currently registered in "
                "job_hunt_copilot.supervisor. Unsupported next moves escalate instead of "
                "pretending broader automation already exists."
            ),
        },
        "actions": actions,
    }


def build_service_goals_payload(generated_at: str) -> dict[str, Any]:
    return {
        "contract_version": CONTRACT_VERSION,
        "generated_at": generated_at,
        "deployment": {
            "scheduler": "launchd",
            "heartbeat_interval_seconds": 180,
            "run_at_load": True,
            "keep_alive": False,
            "sleep_wake_primary_detection": "pmset_log",
            "sleep_wake_fallback_gap_hours": 1,
        },
        "freshness_expectations": [
            "Due work is picked up within the active heartbeat cadence.",
            "No actionable queue item remains untouched without an explicit persisted reason.",
            "Blocked or failed work always receives a persisted reason or incident.",
        ],
        "due_work_priorities": [
            "control-state changes such as pause or stop",
            "open incidents and health-critical failures",
            "due sends and due feedback polling",
            "mandatory agent review gates",
            "active posting runs waiting to advance",
            "new Gmail-ingestion work",
            "bounded maintenance work",
        ],
        "continuous_service_goal_thresholds": {
            "auto_pause_repeated_incident_count": 3,
            "auto_pause_repeated_incident_window_minutes": 45,
            "automatic_replanning_cooldown_hours": 6,
        },
        "current_build_note": (
            "The local launchd plists plus `jhc-agent-start`, `jhc-agent-stop`, "
            "`jhc-agent-cycle`, and `jhc-feedback-sync-cycle` now exist in the repo, "
            "and `jhc-chat` now applies canonical session begin/end wiring with "
            "pause-on-chat control-state handling."
        ),
    }


def build_escalation_policy_payload(paths: ProjectPaths, generated_at: str) -> dict[str, Any]:
    return {
        "contract_version": CONTRACT_VERSION,
        "generated_at": generated_at,
        "incident_severities": ["low", "medium", "high", "critical"],
        "escalation_triggers": [
            {
                "trigger_id": "uncataloged_next_move",
                "when": "The selected work unit needs a next move that is not registered in action-catalog.yaml.",
                "effect": "Persist or escalate an incident instead of improvising broad behavior.",
            },
            {
                "trigger_id": "review_worthy_terminal_run",
                "when": "A pipeline run reaches a review-worthy terminal outcome.",
                "effect": "Generate review_packet.json and review_packet.md, then set pending expert review state.",
            },
        ],
        "auto_pause_triggers": [
            {
                "trigger_id": "critical_operational_incident",
                "incident_types": sorted(AUTO_PAUSE_CRITICAL_INCIDENT_TYPES),
                "effect": "Pause autonomous progression immediately while keeping review surfaces available.",
            },
            {
                "trigger_id": "repeated_unresolved_incident_cluster",
                "threshold": "3 unresolved incidents of the same type and operational area within 45 minutes",
                "effect": "Pause autonomous progression and require explicit review or repair.",
            },
        ],
        "expert_surface_routing": {
            "canonical_database": str(paths.db_path),
            "review_packet_dir": str(paths.ops_review_packets_dir),
            "progress_log": str(paths.ops_agent_progress_log_path),
            "ops_plan": str(paths.ops_agent_ops_plan_path),
            "incident_artifact_dir": str(paths.ops_incidents_dir),
        },
        "current_build_note": (
            "Filesystem incident companions are still downstream work; canonical incident rows, "
            "review packets, and progress surfaces remain the active escalation surfaces now."
        ),
    }


def render_chat_bootstrap(
    paths: ProjectPaths,
    runtime_snapshot: dict[str, Any],
    generated_at: str,
) -> str:
    return "\n".join(
        [
            "# Job Hunt Copilot Chat Bootstrap",
            "",
            "You are the expert-facing operator for Job Hunt Copilot v4.",
            "",
            "Runtime surfaces:",
            f"- Project root: {paths.project_root}",
            f"- Canonical DB: {paths.db_path}",
            f"- Identity: {paths.ops_agent_identity_path}",
            f"- Policies: {paths.ops_agent_policies_path}",
            f"- Action catalog: {paths.ops_agent_action_catalog_path}",
            f"- Service goals: {paths.ops_agent_service_goals_path}",
            f"- Escalation policy: {paths.ops_agent_escalation_policy_path}",
            f"- Progress log: {paths.ops_agent_progress_log_path}",
            f"- Ops plan: {paths.ops_agent_ops_plan_path}",
            f"- Chat startup dashboard: {paths.ops_agent_chat_startup_path}",
            "",
            "Startup steps:",
            "1. read the generated identity, policies, action catalog, service goals, and escalation policy under ops/agent/",
            "2. read the current progress log, ops plan, and chat-startup dashboard before answering substantive runtime questions",
            "3. use the persisted chat-startup dashboard as the clean first-response summary and compact review-queue snapshot",
            "4. inspect canonical control state, open incidents, pending expert review packets, and the relevant DB-backed status snapshot",
            "5. inspect only the artifacts needed for the expert's current question or requested action",
            "",
            "Rules:",
            "- prioritize inspection, explanation, and control-intent persistence",
            "- treat job_hunt_copilot.db as canonical truth over filesystem artifacts",
            "- opening chat counts as expert presence; background autonomous work should remain paused by policy while the expert is actively interacting",
            "- persist pause, resume, stop, replanning, and override intents into canonical state instead of relying on chat memory",
            "- expose pending review packets and open incidents clearly before diving into lower-level detail",
            "- do not expose secrets or tokens in summaries, incidents, or review surfaces",
            "",
            "Current snapshot:",
            f"- generated_at: {generated_at}",
            f"- agent_mode: {runtime_snapshot['agent_mode']}",
            f"- latest_cycle_result: {runtime_snapshot['latest_cycle_result']}",
            f"- open_incident_count: {runtime_snapshot['open_incident_count']}",
            f"- pending_review_count: {runtime_snapshot['pending_review_count']}",
            f"- top_focus: {runtime_snapshot['top_focus']}",
            "",
        ]
    )


def render_supervisor_bootstrap(
    paths: ProjectPaths,
    runtime_snapshot: dict[str, Any],
    generated_at: str,
) -> str:
    return "\n".join(
        [
            "# Job Hunt Copilot Supervisor Bootstrap",
            "",
            "You are the heartbeat-driven supervisor agent for Job Hunt Copilot v4.",
            "",
            "Runtime surfaces:",
            f"- Project root: {paths.project_root}",
            f"- Canonical DB: {paths.db_path}",
            f"- Identity: {paths.ops_agent_identity_path}",
            f"- Policies: {paths.ops_agent_policies_path}",
            f"- Action catalog: {paths.ops_agent_action_catalog_path}",
            f"- Service goals: {paths.ops_agent_service_goals_path}",
            f"- Escalation policy: {paths.ops_agent_escalation_policy_path}",
            f"- Progress log: {paths.ops_agent_progress_log_path}",
            f"- Ops plan: {paths.ops_agent_ops_plan_path}",
            f"- Context snapshots: {paths.ops_agent_context_snapshots_dir}",
            "",
            "Startup steps:",
            "1. read the generated identity, policies, action catalog, service goals, and escalation policy under ops/agent/",
            "2. read the current progress log and ops plan before choosing work",
            "3. inspect canonical control state, unresolved incidents, pending review packets, and non-terminal pipeline runs from job_hunt_copilot.db",
            "4. inspect only the artifacts needed for the selected work unit",
            "",
            "Rules:",
            "- choose at most one primary work unit or one tightly related cluster by default",
            "- use only registered actions from action-catalog.yaml for autonomous progression",
            "- validate prerequisites before execution and expected outputs after execution",
            "- treat job_hunt_copilot.db as canonical truth over filesystem artifacts",
            "- when the needed next move is not cataloged, escalate instead of improvising broad behavior",
            "- honor paused, stopped, and replanning mode boundaries before ordinary progression",
            "- generate review packets for review-worthy terminal pipeline-run outcomes",
            "- do not expose secrets or tokens in persisted summaries or escalations",
            "",
            "Current snapshot:",
            f"- generated_at: {generated_at}",
            f"- agent_mode: {runtime_snapshot['agent_mode']}",
            f"- latest_cycle_result: {runtime_snapshot['latest_cycle_result']}",
            f"- open_incident_count: {runtime_snapshot['open_incident_count']}",
            f"- pending_review_count: {runtime_snapshot['pending_review_count']}",
            f"- active_pipeline_run_count: {runtime_snapshot['active_pipeline_run_count']}",
            f"- top_focus: {runtime_snapshot['top_focus']}",
            "",
        ]
    )


def render_initial_progress_log(
    paths: ProjectPaths,
    runtime_snapshot: dict[str, Any],
    generated_at: str,
) -> str:
    local_day = datetime.now().astimezone().date().isoformat()
    blockers = [
        "The current registered action catalog is intentionally narrow; unsupported downstream stages escalate instead of improvising behavior.",
        "Richer `jhc-chat` review retrieval, control routing, and expert-guidance workflows are still narrower than the acceptance target.",
    ]
    return "\n".join(
        [
            "# Supervisor Progress Log",
            "",
            "## Current Summary",
            f"- updated_at: {generated_at}",
            f"- agent_mode: {runtime_snapshot['agent_mode']}",
            f"- latest_cycle_result: {runtime_snapshot['latest_cycle_result']}",
            f"- top_focus: {runtime_snapshot['top_focus']}",
            "",
            "## Current Blockers",
            *(f"- {blocker}" for blocker in blockers),
            "",
            "## Next Likely Action",
            f"- {runtime_snapshot['next_likely_action']}",
            "",
            "## Latest Replan / Maintenance Note",
            "- No replanning or maintenance note has been recorded yet.",
            "",
            "## Recent Entries",
            (
                "- "
                f"{generated_at} | runtime_pack_materialized | Generated ops/agent runtime identity, policy, "
                "catalog, and bootstrap surfaces from the current repository state. | "
                f"refs: {paths.ops_agent_identity_path}, {paths.ops_agent_action_catalog_path}"
            ),
            "",
            "## Daily Rollups",
            (
                f"- {local_day} | runtime-pack scaffold created; latest_cycle_result="
                f"{runtime_snapshot['latest_cycle_result']}; open_incidents={runtime_snapshot['open_incident_count']}; "
                f"pending_review_packets={runtime_snapshot['pending_review_count']}"
            ),
            "",
        ]
    )


def build_initial_ops_plan(runtime_snapshot: dict[str, Any], generated_at: str) -> dict[str, Any]:
    return {
        "contract_version": CONTRACT_VERSION,
        "generated_at": generated_at,
        "agent_mode": runtime_snapshot["agent_mode"],
        "active_priorities": [
            {
                "rank": 1,
                "title": "Honor persisted control-state mode first",
                "reason": "Pause, stop, and replanning semantics outrank ordinary pipeline progression.",
                "scope_type": "agent_control_state",
                "scope_id": "global",
                "intended_next_action": "refresh_control_state_before_selecting_work",
            },
            {
                "rank": 2,
                "title": "Triage unresolved incidents before ordinary advancement",
                "reason": "Health-critical failures and unresolved incidents outrank normal pipeline work.",
                "scope_type": "agent_incident_queue",
                "scope_id": "global",
                "intended_next_action": "escalate_or_repair_highest_priority_incident",
            },
            {
                "rank": 3,
                "title": "Resume only one durable pipeline run at a time",
                "reason": "The current supervisor model is bounded to one primary work unit per cycle.",
                "scope_type": "pipeline_run",
                "scope_id": "global",
                "intended_next_action": "reuse_existing_non_terminal_run_before_creating_new_history",
            },
            {
                "rank": 4,
                "title": "Generate expert review packets for review-worthy terminal outcomes",
                "reason": "Terminal run outcomes need a pending expert review surface without forcing a global stop.",
                "scope_type": "expert_review_packets",
                "scope_id": "global",
                "intended_next_action": "ensure_pending_review_packet_for_each_review_worthy_terminal_run",
            },
            {
                "rank": 5,
                "title": "Escalate unsupported downstream work instead of improvising",
                "reason": "Current code intentionally registers only a narrow action catalog until later pipeline slices land.",
                "scope_type": "action_catalog",
                "scope_id": "global",
                "intended_next_action": "emit_or_escalate_incident_when_selected_work_needs_uncataloged_behavior",
            },
        ],
        "watch_items": [
            {
                "title": "Repeated unresolved incident clusters",
                "reason": "Three unresolved incidents in the same operational area within 45 minutes trigger auto-pause.",
                "trigger_condition": "incident_cluster_count >= 3 within rolling_45_minutes",
            },
            {
                "title": "Critical safety incidents",
                "reason": "Send safety, duplicate-send risk, credential handling, and canonical-state integrity are auto-pause critical.",
                "trigger_condition": "critical_incident in auto_pause_critical_types remains unresolved",
            },
        ],
        "maintenance_backlog": [],
        "weak_areas": [
            {
                "area": "action_catalog_coverage",
                "note": "Later pipeline stages beyond lead_handoff are not yet registered; unsupported needs escalate.",
            },
            {
                "area": "chat_review_control_depth",
                "note": "The runtime now auto-resumes after unexpected chat exit idles safely, but richer in-chat review retrieval, change summaries, and control routing are still backlog.",
            },
        ],
        "replan": {
            "status": "idle",
            "last_replan_at": None,
            "next_focus": runtime_snapshot["top_focus"],
            "reason": "No replanning cycle has been recorded yet.",
        },
    }
