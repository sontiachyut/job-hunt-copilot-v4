from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .supervisor import SUPPORTED_PIPELINE_CHECKPOINT_STAGES


TRACE_MATRIX_VERSION = 4
FEATURE_PATH = Path("prd/test-spec.feature")
BUILD_BOARD_PATH = Path("build-agent/state/build-board.yaml")
REPORT_JSON_PATH = Path("build-agent/reports/ba-10-acceptance-trace-matrix.json")
REPORT_MD_PATH = Path("build-agent/reports/ba-10-acceptance-trace-matrix.md")
IMPLEMENTED_SLICE_STATUSES = {"completed", "in_progress"}

STATUS_IMPLEMENTED = "implemented"
STATUS_PARTIAL = "partial"
STATUS_GAP = "gap"
STATUS_DEFERRED_OPTIONAL = "deferred_optional"
STATUS_EXCLUDED = "excluded_from_required_acceptance"

STATUS_ORDER = (
    STATUS_IMPLEMENTED,
    STATUS_PARTIAL,
    STATUS_GAP,
    STATUS_DEFERRED_OPTIONAL,
    STATUS_EXCLUDED,
)


@dataclass(frozen=True)
class RuleBlueprint:
    owner_role: str
    epic_ids: tuple[str, ...]
    code_refs: tuple[str, ...]
    test_refs: tuple[str, ...]
    default_status: str = STATUS_IMPLEMENTED
    default_gap_ids: tuple[str, ...] = ()
    note: str | None = None


def _gap_metadata(
    *,
    title: str,
    reason: str,
    next_slice: str,
    evidence_summary: str,
    evidence_code_refs: tuple[str, ...],
    evidence_test_refs: tuple[str, ...],
    implementation_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "title": title,
        "reason": reason,
        "next_slice": next_slice,
        "evidence_summary": evidence_summary,
        "evidence_code_refs": evidence_code_refs,
        "evidence_test_refs": evidence_test_refs,
    }
    if implementation_snapshot:
        payload["implementation_snapshot"] = implementation_snapshot
    return payload


def _load_build_board(project_root: Path) -> dict[str, Any]:
    payload = yaml.safe_load((project_root / BUILD_BOARD_PATH).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected mapping in {BUILD_BOARD_PATH}")
    return payload


def _collect_implemented_slice_catalog(
    board: dict[str, Any],
) -> tuple[list[dict[str, str]], dict[str, list[str]]]:
    slice_catalog: list[dict[str, str]] = []
    slice_ids_by_epic: dict[str, list[str]] = defaultdict(list)

    for epic in board.get("epics", []):
        if not isinstance(epic, dict):
            continue
        epic_id = epic.get("id")
        if not epic_id:
            continue
        for slice_record in epic.get("near_term_slices", []):
            if not isinstance(slice_record, dict):
                continue
            slice_id = slice_record.get("id")
            status = slice_record.get("status")
            if not slice_id or status not in IMPLEMENTED_SLICE_STATUSES:
                continue
            slice_catalog.append(
                {
                    "slice_id": slice_id,
                    "epic_id": epic_id,
                    "name": slice_record.get("name", ""),
                    "owner_role": slice_record.get(
                        "owner_role", epic.get("owner_role", "")
                    ),
                    "status": status,
                }
            )
            slice_ids_by_epic[epic_id].append(slice_id)

    return slice_catalog, slice_ids_by_epic


def _resolve_slice_ids(
    epic_ids: tuple[str, ...] | list[str],
    slice_ids_by_epic: dict[str, list[str]],
) -> list[str]:
    resolved_epic_ids = list(epic_ids)
    if len(resolved_epic_ids) > 1 and "BA-10" in resolved_epic_ids:
        resolved_epic_ids = [
            epic_id for epic_id in resolved_epic_ids if epic_id != "BA-10"
        ]

    resolved_slice_ids: list[str] = []
    seen_slice_ids: set[str] = set()

    for epic_id in resolved_epic_ids:
        epic_slice_ids = slice_ids_by_epic.get(epic_id)
        if not epic_slice_ids:
            raise ValueError(f"No implemented slices recorded for epic {epic_id!r}")
        for slice_id in epic_slice_ids:
            if slice_id in seen_slice_ids:
                continue
            seen_slice_ids.add(slice_id)
            resolved_slice_ids.append(slice_id)

    return resolved_slice_ids


def _supervisor_downstream_implementation_snapshot() -> dict[str, Any]:
    return {
        "registered_role_targeted_checkpoint_stages": sorted(
            SUPPORTED_PIPELINE_CHECKPOINT_STAGES
        ),
        "validated_blocked_role_targeted_stages": [
            "agent_review",
            "people_search",
            "email_discovery",
            "sending",
            "delivery_feedback",
        ],
        "unsupported_autonomous_scope_paths": [
            "contact_rooted_general_learning",
        ],
    }


GAP_REGISTRY: dict[str, dict[str, Any]] = {
    "BA10_SMOKE_HARNESS": _gap_metadata(
        title="Integrated smoke harness is still missing",
        reason="The repo has strong component tests, but no committed cross-component smoke run that exercises bootstrap through review-query surfaces in one pass.",
        next_slice="BA-10-S2",
        evidence_summary="The committed smoke harness now exercises bootstrap through review-query reads in one deterministic cross-component flow.",
        evidence_code_refs=(
            "job_hunt_copilot/bootstrap.py",
            "job_hunt_copilot/outreach.py",
            "job_hunt_copilot/delivery_feedback.py",
            "job_hunt_copilot/review_queries.py",
        ),
        evidence_test_refs=(
            "tests/test_smoke_harness.py",
            "tests/test_acceptance_traceability.py",
        ),
    ),
    "BA10_SUPERVISOR_DOWNSTREAM_ACTION_CATALOG": _gap_metadata(
        title="Supervisor orchestration still stops at lead handoff",
        reason="The durable heartbeat, selector ordering, and retry-safe run persistence exist, but the registered action catalog still only advances autonomous work through `lead_handoff`; later stages reselect the same durable run and escalate instead of executing.",
        next_slice="BA-10-S4",
        evidence_summary="Focused downstream-stage regressions prove `lead_handoff` is the only registered checkpoint, later stages escalate with durable run and review-packet retention, retries reuse the same run instead of restarting, and a ready contact-rooted general-learning candidate still yields no selected supervisor work.",
        evidence_code_refs=(
            "job_hunt_copilot/supervisor.py",
            "job_hunt_copilot/local_runtime.py",
            "job_hunt_copilot/runtime_pack.py",
        ),
        evidence_test_refs=(
            "tests/test_supervisor_downstream_actions.py",
            "tests/test_blocker_audit.py",
            "tests/test_acceptance_traceability.py",
        ),
        implementation_snapshot=_supervisor_downstream_implementation_snapshot(),
    ),
    "BA10_MAINTENANCE_AUTOMATION": _gap_metadata(
        title="Maintenance workflow and artifacts are not implemented",
        reason="The schema and runtime pack reserve maintenance surfaces, but there is no autonomous maintenance batch workflow, no maintenance artifacts, and no maintenance review flow yet.",
        next_slice="BA-10-S3",
        evidence_summary="Schema and runtime scaffolding reserve maintenance surfaces, but there is still no maintenance module, runner, or review-artifact workflow.",
        evidence_code_refs=(
            "job_hunt_copilot/migrations/0002_canonical_schema.sql",
            "job_hunt_copilot/paths.py",
            "job_hunt_copilot/runtime_pack.py",
        ),
        evidence_test_refs=(
            "tests/test_schema.py",
            "tests/test_runtime_pack.py",
            "tests/test_acceptance_traceability.py",
        ),
    ),
    "BA10_CHAT_REVIEW_AND_CONTROL": _gap_metadata(
        title="Chat review and control remain wrapper-only",
        reason="The direct `jhc-chat` entrypoint manages chat session lifecycle, but richer review retrieval, control routing, and expert-guidance behaviors are not yet implemented in the chat surface.",
        next_slice="BA-10-S3",
        evidence_summary="Chat lifecycle, review-query reads, and bootstrap scaffolding exist, but chat itself still does not retrieve grouped reviews or route control decisions.",
        evidence_code_refs=(
            "scripts/ops/chat_session.py",
            "job_hunt_copilot/local_runtime.py",
            "job_hunt_copilot/review_queries.py",
            "job_hunt_copilot/runtime_pack.py",
        ),
        evidence_test_refs=(
            "tests/test_local_runtime.py",
            "tests/test_review_queries.py",
            "tests/test_runtime_pack.py",
            "tests/test_acceptance_traceability.py",
        ),
    ),
    "BA10_CHAT_IDLE_TIMEOUT_RESUME": _gap_metadata(
        title="Idle-timeout resume is still backlog",
        reason="Explicit-close and explicit-resume paths exist, but unexpected `jhc-chat` exits still require a later explicit resume because automatic idle-timeout recovery is not implemented.",
        next_slice="BA-10-S3",
        evidence_summary="Unexpected chat exit is recorded and a later explicit resume works, but no automatic idle-timeout resume helper exists.",
        evidence_code_refs=(
            "job_hunt_copilot/local_runtime.py",
            "job_hunt_copilot/runtime_pack.py",
        ),
        evidence_test_refs=(
            "tests/test_local_runtime.py",
            "tests/test_runtime_pack.py",
            "tests/test_acceptance_traceability.py",
        ),
    ),
    "BA10_DELAYED_FEEDBACK_SCHEDULING": _gap_metadata(
        title="Delayed feedback scheduling is not wired to a scheduler",
        reason="Delivery feedback syncing can run and persists scheduler metadata, but there is no committed launchd-driven delayed feedback poller yet.",
        next_slice="BA-10-S3",
        evidence_summary="The dedicated delayed-feedback launchd runner, plist materialization, and smoke-covered sync path are now committed.",
        evidence_code_refs=(
            "job_hunt_copilot/local_runtime.py",
            "scripts/ops/run_feedback_sync.py",
            "scripts/ops/materialize_feedback_sync_plist.py",
            "bin/jhc-feedback-sync-cycle",
        ),
        evidence_test_refs=(
            "tests/test_local_runtime.py",
            "tests/test_smoke_harness.py",
            "tests/test_acceptance_traceability.py",
        ),
    ),
    "BA10_SLEEP_WAKE_RECOVERY": _gap_metadata(
        title="Sleep and wake recovery is not implemented beyond metadata",
        reason="Supervisor cycles record the intended sleep/wake detection method, but the actual pmset-log parsing and conservative fallback logic have not been implemented.",
        next_slice="BA-10-S3",
        evidence_summary="Supervisor heartbeats now parse pmset sleep/wake evidence first and fall back to a conservative cycle-gap recovery heuristic.",
        evidence_code_refs=("job_hunt_copilot/local_runtime.py",),
        evidence_test_refs=(
            "tests/test_local_runtime.py",
            "tests/test_acceptance_traceability.py",
        ),
    ),
    "BA10_POSTING_ABANDON_CONTROL": _gap_metadata(
        title="Posting-abandon control surface is missing",
        reason="There is no explicit user-facing or runtime control path that abandons a posting from arbitrary active orchestration states while preserving canonical history.",
        next_slice="BA-10-S3",
        evidence_summary="Agent-level start/stop/pause/resume/replan controls exist, but there is still no posting-scoped abandon command or runtime mutation path.",
        evidence_code_refs=(
            "scripts/ops/control_agent.py",
            "job_hunt_copilot/local_runtime.py",
            "job_hunt_copilot/supervisor.py",
        ),
        evidence_test_refs=(
            "tests/test_local_runtime.py",
            "tests/test_acceptance_traceability.py",
        ),
    ),
}


RULE_BLUEPRINTS: dict[str, RuleBlueprint] = {
    "Build bootstrap and prerequisites": RuleBlueprint(
        owner_role="foundation-engineer",
        epic_ids=("BA-01", "BA-03", "BA-10"),
        code_refs=(
            "job_hunt_copilot/bootstrap.py",
            "job_hunt_copilot/db.py",
            "job_hunt_copilot/paths.py",
            "job_hunt_copilot/runtime_pack.py",
            "job_hunt_copilot/local_runtime.py",
            "bin/jhc-bootstrap",
            "bin/jhc-agent-start",
            "bin/jhc-agent-stop",
            "bin/jhc-chat",
        ),
        test_refs=(
            "tests/test_bootstrap.py",
            "tests/test_schema.py",
            "tests/test_runtime_pack.py",
            "tests/test_local_runtime.py",
            "tests/test_smoke_harness.py",
        ),
        note="Bootstrap, schema, runtime-pack, and local wrapper surfaces have direct pytest coverage, and the BA-10 smoke harness now exercises bootstrap through a committed downstream flow.",
    ),
    "Machine handoff contracts and canonical state": RuleBlueprint(
        owner_role="build-lead",
        epic_ids=("BA-01", "BA-02", "BA-04", "BA-06", "BA-07", "BA-08", "BA-09"),
        code_refs=(
            "job_hunt_copilot/artifacts.py",
            "job_hunt_copilot/contracts.py",
            "job_hunt_copilot/supervisor.py",
            "job_hunt_copilot/linkedin_scraping.py",
            "job_hunt_copilot/resume_tailoring.py",
            "job_hunt_copilot/email_discovery.py",
            "job_hunt_copilot/outreach.py",
            "job_hunt_copilot/delivery_feedback.py",
            "job_hunt_copilot/review_queries.py",
        ),
        test_refs=(
            "tests/test_artifacts.py",
            "tests/test_supervisor.py",
            "tests/test_linkedin_scraping.py",
            "tests/test_resume_tailoring.py",
            "tests/test_email_discovery.py",
            "tests/test_outreach.py",
            "tests/test_delivery_feedback.py",
            "tests/test_review_queries.py",
        ),
        note="Artifact contracts, DB-first bootstraps, and review-packet companions are validated at each component boundary rather than through one end-to-end smoke yet.",
    ),
    "State transitions and relationship records": RuleBlueprint(
        owner_role="build-lead",
        epic_ids=("BA-01", "BA-04", "BA-06", "BA-07", "BA-08", "BA-09"),
        code_refs=(
            "job_hunt_copilot/db.py",
            "job_hunt_copilot/linkedin_scraping.py",
            "job_hunt_copilot/resume_tailoring.py",
            "job_hunt_copilot/email_discovery.py",
            "job_hunt_copilot/outreach.py",
            "job_hunt_copilot/delivery_feedback.py",
        ),
        test_refs=(
            "tests/test_schema.py",
            "tests/test_linkedin_scraping.py",
            "tests/test_resume_tailoring.py",
            "tests/test_email_discovery.py",
            "tests/test_outreach.py",
            "tests/test_delivery_feedback.py",
        ),
    ),
    "External integrations and bootstrap configuration": RuleBlueprint(
        owner_role="ingestion-engineer",
        epic_ids=("BA-01", "BA-04", "BA-05", "BA-07"),
        code_refs=(
            "job_hunt_copilot/bootstrap.py",
            "job_hunt_copilot/secrets.py",
            "job_hunt_copilot/linkedin_scraping.py",
            "job_hunt_copilot/gmail_alerts.py",
            "job_hunt_copilot/email_discovery.py",
        ),
        test_refs=(
            "tests/test_bootstrap.py",
            "tests/test_linkedin_scraping.py",
            "tests/test_gmail_alerts.py",
            "tests/test_email_discovery.py",
        ),
    ),
    "Failure, retry, and idempotency behavior": RuleBlueprint(
        owner_role="quality-engineer",
        epic_ids=("BA-02", "BA-04", "BA-05", "BA-07", "BA-08", "BA-09"),
        code_refs=(
            "job_hunt_copilot/supervisor.py",
            "job_hunt_copilot/linkedin_scraping.py",
            "job_hunt_copilot/gmail_alerts.py",
            "job_hunt_copilot/email_discovery.py",
            "job_hunt_copilot/outreach.py",
            "job_hunt_copilot/delivery_feedback.py",
        ),
        test_refs=(
            "tests/test_supervisor_downstream_actions.py",
            "tests/test_supervisor.py",
            "tests/test_linkedin_scraping.py",
            "tests/test_gmail_alerts.py",
            "tests/test_email_discovery.py",
            "tests/test_outreach.py",
            "tests/test_delivery_feedback.py",
        ),
    ),
    "Resume Tailoring behavior": RuleBlueprint(
        owner_role="tailoring-engineer",
        epic_ids=("BA-06",),
        code_refs=(
            "job_hunt_copilot/resume_tailoring.py",
            "job_hunt_copilot/paths.py",
        ),
        test_refs=("tests/test_resume_tailoring.py",),
    ),
    "Email Discovery behavior": RuleBlueprint(
        owner_role="outreach-engineer",
        epic_ids=("BA-07", "BA-09"),
        code_refs=(
            "job_hunt_copilot/email_discovery.py",
            "job_hunt_copilot/review_queries.py",
        ),
        test_refs=(
            "tests/test_email_discovery.py",
            "tests/test_review_queries.py",
        ),
    ),
    "Email Drafting and Sending behavior": RuleBlueprint(
        owner_role="outreach-engineer",
        epic_ids=("BA-08",),
        code_refs=("job_hunt_copilot/outreach.py",),
        test_refs=("tests/test_outreach.py",),
    ),
    "Delivery Feedback behavior": RuleBlueprint(
        owner_role="outreach-engineer",
        epic_ids=("BA-03", "BA-09"),
        code_refs=(
            "job_hunt_copilot/delivery_feedback.py",
            "job_hunt_copilot/local_runtime.py",
            "job_hunt_copilot/paths.py",
        ),
        test_refs=(
            "tests/test_delivery_feedback.py",
            "tests/test_outreach.py",
            "tests/test_local_runtime.py",
            "tests/test_smoke_harness.py",
        ),
    ),
    "Supervisor Agent behavior": RuleBlueprint(
        owner_role="build-lead",
        epic_ids=("BA-02", "BA-03"),
        code_refs=(
            "job_hunt_copilot/supervisor.py",
            "job_hunt_copilot/local_runtime.py",
            "job_hunt_copilot/runtime_pack.py",
            "scripts/ops/run_supervisor_cycle.py",
            "scripts/ops/control_agent.py",
            "scripts/ops/chat_session.py",
            "bin/jhc-agent-start",
            "bin/jhc-agent-stop",
            "bin/jhc-agent-cycle",
            "bin/jhc-chat",
        ),
        test_refs=(
            "tests/test_supervisor_downstream_actions.py",
            "tests/test_supervisor.py",
            "tests/test_local_runtime.py",
            "tests/test_runtime_pack.py",
        ),
        default_status=STATUS_PARTIAL,
        default_gap_ids=("BA10_SUPERVISOR_DOWNSTREAM_ACTION_CATALOG",),
        note="The durable supervisor core is real and tested, but its autonomous action catalog is still intentionally narrow and the richer chat or maintenance runtime remains incomplete.",
    ),
    "Review surfaces and chat-based control": RuleBlueprint(
        owner_role="quality-engineer",
        epic_ids=("BA-03", "BA-09"),
        code_refs=(
            "job_hunt_copilot/review_queries.py",
            "job_hunt_copilot/local_runtime.py",
            "bin/jhc-chat",
        ),
        test_refs=(
            "tests/test_review_queries.py",
            "tests/test_local_runtime.py",
        ),
    ),
    "Current-build orchestration remains sequential": RuleBlueprint(
        owner_role="build-lead",
        epic_ids=("BA-06", "BA-07", "BA-08", "BA-09"),
        code_refs=(
            "job_hunt_copilot/resume_tailoring.py",
            "job_hunt_copilot/email_discovery.py",
            "job_hunt_copilot/outreach.py",
            "job_hunt_copilot/delivery_feedback.py",
            "job_hunt_copilot/supervisor.py",
        ),
        test_refs=(
            "tests/test_resume_tailoring.py",
            "tests/test_email_discovery.py",
            "tests/test_outreach.py",
            "tests/test_delivery_feedback.py",
            "tests/test_supervisor_downstream_actions.py",
            "tests/test_supervisor.py",
        ),
        note="Component-level state gates and sequencing exist, but the autonomous heartbeat does not yet walk the full downstream pipeline.",
    ),
    "LinkedIn Scraping acceptance": RuleBlueprint(
        owner_role="ingestion-engineer",
        epic_ids=("BA-04", "BA-05"),
        code_refs=(
            "job_hunt_copilot/linkedin_scraping.py",
            "job_hunt_copilot/gmail_alerts.py",
            "bin/jhc-linkedin-ingest",
            "scripts/linkedin_scraping/ingest_manual_capture.py",
        ),
        test_refs=(
            "tests/test_linkedin_scraping.py",
            "tests/test_gmail_alerts.py",
        ),
    ),
    "End-to-end acceptance": RuleBlueprint(
        owner_role="quality-engineer",
        epic_ids=("BA-06", "BA-07", "BA-08", "BA-09", "BA-10"),
        code_refs=(
            "job_hunt_copilot/resume_tailoring.py",
            "job_hunt_copilot/email_discovery.py",
            "job_hunt_copilot/outreach.py",
            "job_hunt_copilot/delivery_feedback.py",
            "job_hunt_copilot/supervisor.py",
        ),
        test_refs=(
            "tests/test_resume_tailoring.py",
            "tests/test_email_discovery.py",
            "tests/test_outreach.py",
            "tests/test_delivery_feedback.py",
            "tests/test_supervisor_downstream_actions.py",
            "tests/test_supervisor.py",
            "tests/test_smoke_harness.py",
        ),
        default_status=STATUS_PARTIAL,
        default_gap_ids=("BA10_SUPERVISOR_DOWNSTREAM_ACTION_CATALOG",),
        note="The components exist and now have committed smoke coverage across tailoring, discovery, send, delayed feedback, and review-query boundaries, but the autonomous supervisor still does not orchestrate the full downstream pipeline past lead handoff.",
    ),
    "Current-build safety, privacy, and evidence-grounding boundaries": RuleBlueprint(
        owner_role="quality-engineer",
        epic_ids=("BA-06", "BA-08", "BA-09", "BA-10"),
        code_refs=(
            "job_hunt_copilot/resume_tailoring.py",
            "job_hunt_copilot/outreach.py",
            "job_hunt_copilot/delivery_feedback.py",
            "job_hunt_copilot/review_queries.py",
            "job_hunt_copilot/artifacts.py",
            "job_hunt_copilot/secrets.py",
        ),
        test_refs=(
            "tests/test_resume_tailoring.py",
            "tests/test_outreach.py",
            "tests/test_delivery_feedback.py",
            "tests/test_review_queries.py",
            "tests/test_artifacts.py",
        ),
        note="Explicit BA-10 hardening regressions now verify unsupported tailoring asks stay as gaps, automatic outreach still requires approved review and blocks repeat ambiguity, and review-oriented outputs stay summary-level.",
    ),
}

EPIC_VALIDATION_NOTES: list[dict[str, Any]] = [
    {
        "epic_id": "BA-01",
        "owner_role": "foundation-engineer",
        "focus": "bootstrap, schema migration, shared artifact contracts",
        "primary_tests": [
            "tests/test_bootstrap.py",
            "tests/test_schema.py",
            "tests/test_artifacts.py",
        ],
        "ba10_smoke_targets": [
            "bootstrap prerequisites",
            "DB init and migration",
            "required assets and secret materialization",
        ],
    },
    {
        "epic_id": "BA-02",
        "owner_role": "build-lead",
        "focus": "durable supervisor state, bounded cycles, incidents, review packets",
        "primary_tests": ["tests/test_supervisor.py"],
        "ba10_smoke_targets": [
            "single-cycle heartbeat execution",
            "lease safety",
            "review-packet persistence for escalations",
        ],
    },
    {
        "epic_id": "BA-03",
        "owner_role": "build-lead",
        "focus": "runtime pack, launchd helpers, chat session lifecycle",
        "primary_tests": [
            "tests/test_runtime_pack.py",
            "tests/test_local_runtime.py",
        ],
        "ba10_smoke_targets": [
            "runtime-pack materialization",
            "repo-local wrapper wiring",
            "chat begin/end pause semantics",
        ],
    },
    {
        "epic_id": "BA-04",
        "owner_role": "ingestion-engineer",
        "focus": "manual capture, paste fallback, lead derivation and posting materialization",
        "primary_tests": ["tests/test_linkedin_scraping.py"],
        "ba10_smoke_targets": [
            "paste inbox ingestion",
            "capture-bundle persistence",
            "posting/contact handoff creation",
        ],
    },
    {
        "epic_id": "BA-05",
        "owner_role": "ingestion-engineer",
        "focus": "Gmail collection, job-card parsing, JD provenance merge",
        "primary_tests": ["tests/test_gmail_alerts.py"],
        "ba10_smoke_targets": [
            "plain-text-first Gmail parsing",
            "JD recovery merge",
            "lead dedupe and blocked-no-jd handling",
        ],
    },
    {
        "epic_id": "BA-06",
        "owner_role": "tailoring-engineer",
        "focus": "eligibility, tailoring workspace, finalize verification, mandatory review",
        "primary_tests": ["tests/test_resume_tailoring.py"],
        "ba10_smoke_targets": [
            "sample posting tailoring bootstrap",
            "finalize plus compile check",
            "review approval handoff into outreach readiness",
        ],
    },
    {
        "epic_id": "BA-07",
        "owner_role": "outreach-engineer",
        "focus": "people search, enrichment, email discovery, provider budgets",
        "primary_tests": ["tests/test_email_discovery.py"],
        "ba10_smoke_targets": [
            "Apollo shortlist bootstrap",
            "provider cascade outcome",
            "machine-valid discovery artifact",
        ],
    },
    {
        "epic_id": "BA-08",
        "owner_role": "outreach-engineer",
        "focus": "send-set readiness, drafting artifacts, safe send execution",
        "primary_tests": ["tests/test_outreach.py"],
        "ba10_smoke_targets": [
            "role-targeted draft batch",
            "general-learning draft path",
            "machine-valid send artifact",
        ],
    },
    {
        "epic_id": "BA-09",
        "owner_role": "outreach-engineer",
        "focus": "feedback event persistence, review queries, feedback reuse policy",
        "primary_tests": [
            "tests/test_delivery_feedback.py",
            "tests/test_review_queries.py",
            "tests/test_smoke_harness.py",
        ],
        "ba10_smoke_targets": [
            "one delayed feedback sync run",
            "delivery_outcome artifact generation",
            "review-surface queryability",
        ],
    },
    {
        "epic_id": "BA-10",
        "owner_role": "quality-engineer",
        "focus": "acceptance traceability, smoke harness, blocker burn-down",
        "primary_tests": [
            "tests/test_acceptance_traceability.py",
            "tests/test_blocker_audit.py",
            "tests/test_supervisor_downstream_actions.py",
            "tests/test_smoke_harness.py",
        ],
        "ba10_smoke_targets": [
            "feature-to-code coverage honesty",
            "committed smoke fixture coverage",
            "explicit blocker confirmation",
        ],
    },
]

SMOKE_COVERAGE_TARGETS: tuple[dict[str, Any], ...] = (
    {
        "target_id": "bootstrap",
        "title": "Bootstrap and prerequisites",
        "acceptance_scenario": "Build smoke test passes",
        "acceptance_checks": (
            "the system initializes or migrates `job_hunt_copilot.db`",
            "the system loads runtime secrets successfully",
            "the system reads the required files from `assets/`",
        ),
        "code_refs": (
            "job_hunt_copilot/bootstrap.py",
            "job_hunt_copilot/secrets.py",
            "job_hunt_copilot/db.py",
        ),
        "test_refs": (
            "tests/test_smoke_harness.py",
            "tests/test_bootstrap.py",
            "tests/test_schema.py",
        ),
        "validation_command_ids": (
            "qa_smoke_flow",
            "qa_bootstrap_regressions",
        ),
    },
    {
        "target_id": "tailoring",
        "title": "Resume tailoring",
        "acceptance_scenario": "Build smoke test passes",
        "acceptance_checks": (
            "the system can create a Resume Tailoring workspace for a sample posting",
            "the system can compile the base or tailored resume successfully",
        ),
        "code_refs": (
            "job_hunt_copilot/resume_tailoring.py",
            "job_hunt_copilot/paths.py",
        ),
        "test_refs": (
            "tests/test_smoke_harness.py",
            "tests/test_resume_tailoring.py",
        ),
        "validation_command_ids": (
            "qa_smoke_flow",
            "qa_tailoring_regressions",
        ),
    },
    {
        "target_id": "discovery",
        "title": "Discovery path",
        "acceptance_scenario": "Build smoke test passes",
        "acceptance_checks": (
            "the system can run a discovery-path check with normalized output",
            "the system can generate a machine-valid `discovery_result.json`",
        ),
        "code_refs": (
            "job_hunt_copilot/email_discovery.py",
            "job_hunt_copilot/review_queries.py",
        ),
        "test_refs": (
            "tests/test_smoke_harness.py",
            "tests/test_email_discovery.py",
        ),
        "validation_command_ids": (
            "qa_smoke_flow",
            "qa_discovery_regressions",
        ),
    },
    {
        "target_id": "send",
        "title": "Drafting and sending",
        "acceptance_scenario": "Build smoke test passes",
        "acceptance_checks": (
            "the system can generate a machine-valid `send_result.json`",
        ),
        "code_refs": (
            "job_hunt_copilot/outreach.py",
            "job_hunt_copilot/paths.py",
        ),
        "test_refs": (
            "tests/test_smoke_harness.py",
            "tests/test_outreach.py",
        ),
        "validation_command_ids": (
            "qa_smoke_flow",
            "qa_outreach_regressions",
        ),
    },
    {
        "target_id": "feedback",
        "title": "Delayed feedback sync",
        "acceptance_scenario": "Build smoke test passes",
        "acceptance_checks": (
            "the delayed feedback sync logic can run once without crashing",
        ),
        "code_refs": (
            "job_hunt_copilot/delivery_feedback.py",
            "job_hunt_copilot/local_runtime.py",
        ),
        "test_refs": (
            "tests/test_smoke_harness.py",
            "tests/test_delivery_feedback.py",
            "tests/test_local_runtime.py",
        ),
        "validation_command_ids": (
            "qa_smoke_flow",
            "qa_feedback_regressions",
        ),
    },
    {
        "target_id": "review_query",
        "title": "Review-query surfaces",
        "acceptance_scenario": "Build smoke test passes",
        "acceptance_checks": (
            "at least one review surface can be queried from canonical state",
        ),
        "code_refs": (
            "job_hunt_copilot/review_queries.py",
            "job_hunt_copilot/delivery_feedback.py",
        ),
        "test_refs": (
            "tests/test_smoke_harness.py",
            "tests/test_review_queries.py",
        ),
        "validation_command_ids": (
            "qa_smoke_flow",
            "qa_review_surface_regressions",
        ),
    },
)

SCENARIO_OVERRIDES: dict[str, dict[str, Any]] = {}


def _register_override(
    *,
    scenarios: tuple[str, ...],
    status: str,
    gap_ids: tuple[str, ...] = (),
    note: str | None = None,
) -> None:
    for scenario in scenarios:
        if scenario in SCENARIO_OVERRIDES:
            raise ValueError(f"Duplicate scenario override: {scenario}")
        SCENARIO_OVERRIDES[scenario] = {
            "status": status,
            "gap_ids": list(gap_ids),
            "note": note,
        }


_register_override(
    scenarios=("Build smoke test passes",),
    status=STATUS_IMPLEMENTED,
    note="`tests/test_smoke_harness.py` now exercises bootstrap, tailoring, discovery, sending, delayed feedback sync, and review-query reads in one committed cross-component flow.",
)
_register_override(
    scenarios=("Maintenance change artifacts exist for every autonomous maintenance batch",),
    status=STATUS_GAP,
    gap_ids=("BA10_MAINTENANCE_AUTOMATION",),
    note="Maintenance artifacts are specified in the schema and PRD, but no maintenance batch workflow writes them yet.",
)
_register_override(
    scenarios=("Optional AI second pass can replace an ambiguous rule split only when confidence improves",),
    status=STATUS_DEFERRED_OPTIONAL,
    note="The PRD keeps the AI second pass optional for the current build, so the bounded rule-based split path is still the implemented default.",
)
_register_override(
    scenarios=("Delayed feedback scheduling uses launchd in the current deployment",),
    status=STATUS_IMPLEMENTED,
    note="`job_hunt_copilot.local_runtime`, `scripts/ops/run_feedback_sync.py`, `scripts/ops/materialize_feedback_sync_plist.py`, and the new `ops/launchd/job-hunt-copilot-feedback-sync.plist` now give delayed feedback polling a dedicated launchd invocation path that still calls the shared Delivery Feedback sync logic.",
)
_register_override(
    scenarios=(
        "Supervisor heartbeat runs under launchd and rebuilds fresh context from persisted state",
        "Runtime self-awareness comes from the generated identity and policy pack",
        "Heartbeats resume durable pipeline runs rather than creating duplicate work",
        "Supervisor control, incident, run, and review-packet states follow the current canonical semantics",
        "Supervisor leases prevent overlapping cycles and allow stale recovery",
        "Supervisor cycles follow the current bounded single-work-unit algorithm",
        "Supervisor chooses only registered catalog actions and escalates unknown needs",
        "Review-worthy terminal runs always generate expert review packets",
        "Auto-pause triggers on critical incidents or repeated unresolved incident clusters",
        "Paused and stopped modes have different operational boundaries",
        "jhc-agent-start starts once and jhc-agent-stop preserves state",
        "Current supervisor launchd and wrapper wiring uses the repo-local command path",
        "jhc-agent-start and jhc-agent-stop use the current launchctl wiring",
        "jhc-chat is the direct Codex-backed operator entrypoint",
        "jhc-chat uses explicit session begin and end wiring in the current build",
        "Progress log, ops plan, and context snapshot use the current exact file shapes",
        "Opening jhc-chat immediately pauses autonomous work and safe checkpointing is strict",
    ),
    status=STATUS_IMPLEMENTED,
    note="This behavior is implemented and covered by the current supervisor or local-runtime tests.",
)
_register_override(
    scenarios=(
        "Supervisor work selection follows the current default priority order",
    ),
    status=STATUS_PARTIAL,
    gap_ids=("BA10_SUPERVISOR_DOWNSTREAM_ACTION_CATALOG",),
    note="Current supervisor regressions prove open incidents outrank ordinary pipeline advancement and existing runs outrank new posting bootstrap, but due sends, delayed feedback, general-learning work, and maintenance still have no registered selector or action path.",
)
_register_override(
    scenarios=(
        "Role-targeted flow completes from LinkedIn Scraping through delivery feedback",
        "Role-targeted orchestration follows the current dependency order",
    ),
    status=STATUS_PARTIAL,
    gap_ids=("BA10_SUPERVISOR_DOWNSTREAM_ACTION_CATALOG",),
    note="The downstream components and stage-boundary artifacts exist, and `tests/test_supervisor_downstream_actions.py` now proves the current heartbeat still stops at `lead_handoff` and escalates later stages instead of executing the full dependency chain.",
)
_register_override(
    scenarios=("End-to-end retry resumes from the last successful stage boundary",),
    status=STATUS_PARTIAL,
    gap_ids=("BA10_SUPERVISOR_DOWNSTREAM_ACTION_CATALOG",),
    note="`tests/test_supervisor_downstream_actions.py` now proves downstream retries keep the same `pipeline_run_id`, blocked stage, and pending review packet instead of restarting from `lead_handoff`, but the later-stage autonomous actions are still not registered.",
)
_register_override(
    scenarios=("General learning outreach bypasses the role-targeted agent-review requirement",),
    status=STATUS_PARTIAL,
    gap_ids=("BA10_SUPERVISOR_DOWNSTREAM_ACTION_CATALOG",),
    note="General-learning drafting and sending exist in the outreach component, but `tests/test_supervisor_downstream_actions.py` now proves the supervisor still has no contact-rooted general-learning selector or action path.",
)
_register_override(
    scenarios=("Two-step outreach is excluded from required acceptance",),
    status=STATUS_EXCLUDED,
    note="The feature file explicitly marks two-step outreach as outside the required acceptance surface for the current build.",
)
_register_override(
    scenarios=("The user may explicitly abandon a posting from any active orchestration state",),
    status=STATUS_GAP,
    gap_ids=("BA10_POSTING_ABANDON_CONTROL",),
    note="No posting-abandon runtime control surface or tests exist yet.",
)
_register_override(
    scenarios=(
        "jhc-chat startup dashboard is detailed, bounded, and clean-first",
        "Review retrieval is grouped, compact-first, and newest-first within each group",
    ),
    status=STATUS_PARTIAL,
    gap_ids=("BA10_CHAT_REVIEW_AND_CONTROL",),
    note="The runtime pack and review-query layer exist, but the direct chat experience has not yet implemented this richer behavior end to end.",
)
_register_override(
    scenarios=(
        "AI agent surfaces the current review queue in chat",
        "Startup dashboard runtime metrics count only active autonomous execution",
        "jhc-chat uses persisted state for answers and control routing",
        "Default change summaries cover activity since the last completed expert review",
        "Expert guidance becomes live immediately but conflicting or uncertain reuse asks first",
        "Conflicting expert guidance pauses the whole autonomous system",
        "Expert-requested background tasks require explicit handoff summary and exclusive focus",
        "Expert-requested background task outcomes return to review appropriately",
    ),
    status=STATUS_GAP,
    gap_ids=("BA10_CHAT_REVIEW_AND_CONTROL",),
    note="The direct `jhc-chat` wrapper manages session state only; chat-side review retrieval, routing, and guidance behaviors are still missing.",
)
_register_override(
    scenarios=("Expert-interaction resume follows explicit close, explicit resume, or safe idle timeout",),
    status=STATUS_PARTIAL,
    gap_ids=("BA10_CHAT_IDLE_TIMEOUT_RESUME",),
    note="Explicit close and explicit resume paths exist, but automatic idle-timeout recovery after unexpected chat exit is still backlog.",
)
_register_override(
    scenarios=("Current macOS sleep or wake detection uses pmset logs first and conservative fallback second",),
    status=STATUS_IMPLEMENTED,
    note="`job_hunt_copilot.local_runtime.execute_supervisor_heartbeat` now checks `pmset -g log` first, records detected Sleep/Wake/DarkWake evidence into canonical control-state metadata, and falls back to a >1 hour supervisor-cycle gap heuristic when explicit power-event lines are unavailable.",
)
_register_override(
    scenarios=(
        "Daily maintenance is mandatory, bounded, and run-boundary aware",
        "Maintenance changes follow the current git and approval workflow",
        "Proper maintenance validation requires both change-scoped and full-project testing",
        "Failed or unapproved maintenance batches remain reviewable",
    ),
    status=STATUS_GAP,
    gap_ids=("BA10_MAINTENANCE_AUTOMATION",),
    note="Only maintenance placeholders exist today; the maintenance workflow itself is still missing.",
)
_register_override(
    scenarios=("Delayed bounce after the send session still gets captured",),
    status=STATUS_IMPLEMENTED,
    note="`tests/test_smoke_harness.py`, `tests/test_delivery_feedback.py`, and `tests/test_local_runtime.py` now cover delayed bounce capture after send completion through the shared sync logic plus the dedicated launchd-facing feedback-sync runner.",
)
_register_override(
    scenarios=("Secrets and tokens do not leak into canonical state or review surfaces",),
    status=STATUS_IMPLEMENTED,
    note="BA-10 hardening coverage now scans canonical state, review outputs, and machine handoff artifacts to confirm runtime secret values stay out of persisted workflow surfaces.",
)


def parse_feature_file(feature_path: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    current_rule: str | None = None
    current_rule_line: int | None = None
    for line_number, raw_line in enumerate(feature_path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if line.startswith("Rule: "):
            current_rule = line.removeprefix("Rule: ")
            current_rule_line = line_number
            continue
        if line.startswith("Scenario: "):
            if current_rule is None or current_rule_line is None:
                raise ValueError(f"Scenario before rule at {feature_path}:{line_number}")
            entries.append(
                {
                    "rule": current_rule,
                    "rule_line": current_rule_line,
                    "scenario": line.removeprefix("Scenario: "),
                    "scenario_line": line_number,
                }
            )
    return entries


def build_acceptance_trace_matrix(project_root: Path | str) -> dict[str, Any]:
    root = Path(project_root)
    board = _load_build_board(root)
    implemented_slices, slice_ids_by_epic = _collect_implemented_slice_catalog(board)
    feature_entries = parse_feature_file(root / FEATURE_PATH)
    feature_rules = {entry["rule"] for entry in feature_entries}
    unknown_rules = feature_rules - set(RULE_BLUEPRINTS)
    if unknown_rules:
        raise ValueError(f"Missing rule blueprints for: {sorted(unknown_rules)}")

    feature_scenarios = {entry["scenario"] for entry in feature_entries}
    unknown_overrides = set(SCENARIO_OVERRIDES) - feature_scenarios
    if unknown_overrides:
        raise ValueError(f"Unknown scenario overrides: {sorted(unknown_overrides)}")

    scenarios_by_rule: dict[str, list[dict[str, Any]]] = defaultdict(list)
    scenario_status_counts = {status: 0 for status in STATUS_ORDER}

    for entry in feature_entries:
        rule = entry["rule"]
        blueprint = RULE_BLUEPRINTS[rule]
        override = SCENARIO_OVERRIDES.get(entry["scenario"], {})
        status = override.get("status", blueprint.default_status)
        if status not in STATUS_ORDER:
            raise ValueError(f"Unsupported status {status!r} for scenario {entry['scenario']!r}")
        gap_ids = override.get("gap_ids", list(blueprint.default_gap_ids))
        for gap_id in gap_ids:
            if gap_id not in GAP_REGISTRY:
                raise ValueError(f"Unknown gap id {gap_id!r} for scenario {entry['scenario']!r}")
        slice_ids = _resolve_slice_ids(blueprint.epic_ids, slice_ids_by_epic)

        scenario_record = {
            "name": entry["scenario"],
            "scenario_line": entry["scenario_line"],
            "status": status,
            "owner_role": blueprint.owner_role,
            "epic_ids": list(blueprint.epic_ids),
            "slice_ids": slice_ids,
            "code_refs": list(blueprint.code_refs),
            "test_refs": list(blueprint.test_refs),
            "gap_ids": gap_ids,
            "note": override.get("note", blueprint.note),
        }
        scenarios_by_rule[rule].append(scenario_record)
        scenario_status_counts[status] += 1

    rules: list[dict[str, Any]] = []
    for rule in feature_entries:
        rule_name = rule["rule"]
        if any(existing["rule"] == rule_name for existing in rules):
            continue
        blueprint = RULE_BLUEPRINTS[rule_name]
        rule_scenarios = scenarios_by_rule[rule_name]
        status_counts = {status: 0 for status in STATUS_ORDER}
        for scenario in rule_scenarios:
            status_counts[scenario["status"]] += 1
        rules.append(
            {
                "rule": rule_name,
                "rule_line": rule["rule_line"],
                "owner_role": blueprint.owner_role,
                "epic_ids": list(blueprint.epic_ids),
                "slice_ids": _resolve_slice_ids(blueprint.epic_ids, slice_ids_by_epic),
                "code_refs": list(blueprint.code_refs),
                "test_refs": list(blueprint.test_refs),
                "note": blueprint.note,
                "status_counts": status_counts,
                "scenarios": rule_scenarios,
            }
        )

    gap_scenarios: dict[str, list[str]] = defaultdict(list)
    gap_slice_ids_by_gap_id: dict[str, list[str]] = defaultdict(list)
    for rule in rules:
        for scenario in rule["scenarios"]:
            for gap_id in scenario["gap_ids"]:
                gap_scenarios[gap_id].append(scenario["name"])
                for slice_id in scenario["slice_ids"]:
                    if slice_id not in gap_slice_ids_by_gap_id[gap_id]:
                        gap_slice_ids_by_gap_id[gap_id].append(slice_id)

    gap_registry = []
    for gap_id, metadata in GAP_REGISTRY.items():
        gap_slice_ids = list(gap_slice_ids_by_gap_id.get(gap_id, []))
        if metadata["next_slice"] not in gap_slice_ids:
            gap_slice_ids.append(metadata["next_slice"])
        gap_record = {
            "gap_id": gap_id,
            "title": metadata["title"],
            "reason": metadata["reason"],
            "next_slice": metadata["next_slice"],
            "evidence_summary": metadata["evidence_summary"],
            "evidence_code_refs": list(metadata["evidence_code_refs"]),
            "evidence_test_refs": list(metadata["evidence_test_refs"]),
            "slice_ids": gap_slice_ids,
            "scenario_names": gap_scenarios.get(gap_id, []),
        }
        implementation_snapshot = metadata.get("implementation_snapshot")
        if implementation_snapshot:
            gap_record["implementation_snapshot"] = dict(implementation_snapshot)
        gap_registry.append(gap_record)

    return {
        "trace_matrix_version": TRACE_MATRIX_VERSION,
        "feature_path": str(FEATURE_PATH),
        "scenario_count": len(feature_entries),
        "status_counts": scenario_status_counts,
        "implemented_slices": implemented_slices,
        "rules": rules,
        "gap_registry": gap_registry,
        "epic_validation_notes": [
            {
                **note,
                "slice_ids": _resolve_slice_ids([note["epic_id"]], slice_ids_by_epic),
            }
            for note in EPIC_VALIDATION_NOTES
        ],
        "smoke_coverage_targets": [
            {
                "target_id": target["target_id"],
                "title": target["title"],
                "acceptance_scenario": target["acceptance_scenario"],
                "acceptance_checks": list(target["acceptance_checks"]),
                "code_refs": list(target["code_refs"]),
                "test_refs": list(target["test_refs"]),
                "validation_command_ids": list(target["validation_command_ids"]),
            }
            for target in SMOKE_COVERAGE_TARGETS
        ],
    }


def render_acceptance_trace_markdown(matrix: dict[str, Any]) -> str:
    lines = [
        "# BA-10 Acceptance Trace Matrix",
        "",
        f"- Feature file: `{matrix['feature_path']}`",
        f"- Scenario count: `{matrix['scenario_count']}`",
        "- Status counts:",
    ]
    for status in STATUS_ORDER:
        lines.append(f"  - `{status}`: `{matrix['status_counts'][status]}`")

    lines.extend(
        [
            "",
            "## Implemented Slice Catalog",
            "",
            "| Slice | Epic | Owner | Status |",
            "| --- | --- | --- | --- |",
        ]
    )
    for slice_record in matrix["implemented_slices"]:
        lines.append(
            "| "
            + f"{slice_record['slice_id']} | {slice_record['epic_id']} | "
            + f"{slice_record['owner_role']} | {slice_record['status']} |"
        )

    lines.extend(
        [
            "",
            "## Rule Summary",
            "",
            "| Rule | Owner | Implemented | Partial | Gap | Deferred | Excluded |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for rule in matrix["rules"]:
        counts = rule["status_counts"]
        lines.append(
            "| "
            + f"{rule['rule']} | {rule['owner_role']} | {counts[STATUS_IMPLEMENTED]} | "
            + f"{counts[STATUS_PARTIAL]} | {counts[STATUS_GAP]} | "
            + f"{counts[STATUS_DEFERRED_OPTIONAL]} | {counts[STATUS_EXCLUDED]} |"
        )

    lines.extend(["", "## Rule-To-Slice Mapping", ""])
    for rule in matrix["rules"]:
        lines.append(f"### {rule['rule']}")
        lines.append(
            "- Supporting slices: "
            + ", ".join(f"`{slice_id}`" for slice_id in rule["slice_ids"])
        )
        lines.append("")

    lines.extend(["", "## Explicit Gaps", ""])
    for gap in matrix["gap_registry"]:
        if not gap["scenario_names"]:
            continue
        lines.append(f"### {gap['gap_id']}: {gap['title']}")
        lines.append(f"- Next slice: `{gap['next_slice']}`")
        if gap["slice_ids"]:
            lines.append(
                "- Supporting slices: "
                + ", ".join(f"`{slice_id}`" for slice_id in gap["slice_ids"])
            )
        lines.append(f"- Reason: {gap['reason']}")
        lines.append(f"- Evidence summary: {gap['evidence_summary']}")
        lines.append(
            "- Evidence code refs: "
            + ", ".join(f"`{path}`" for path in gap["evidence_code_refs"])
        )
        lines.append(
            "- Evidence test refs: "
            + ", ".join(f"`{path}`" for path in gap["evidence_test_refs"])
        )
        implementation_snapshot = gap.get("implementation_snapshot") or {}
        if implementation_snapshot:
            lines.append("- Implementation snapshot:")
            registered_stages = implementation_snapshot.get(
                "registered_role_targeted_checkpoint_stages", []
            )
            if registered_stages:
                lines.append(
                    "  - Registered role-targeted checkpoint stages: "
                    + ", ".join(f"`{stage}`" for stage in registered_stages)
                )
            blocked_stages = implementation_snapshot.get(
                "validated_blocked_role_targeted_stages", []
            )
            if blocked_stages:
                lines.append(
                    "  - Validated blocked role-targeted stages: "
                    + ", ".join(f"`{stage}`" for stage in blocked_stages)
                )
            unsupported_paths = implementation_snapshot.get(
                "unsupported_autonomous_scope_paths", []
            )
            if unsupported_paths:
                lines.append(
                    "  - Unsupported autonomous scope paths: "
                    + ", ".join(f"`{path}`" for path in unsupported_paths)
                )
        lines.append(f"- Scenarios: `{len(gap['scenario_names'])}`")
        for scenario_name in gap["scenario_names"]:
            lines.append(f"  - {scenario_name}")
        lines.append("")

    lines.extend(["## Epic Validation Ownership", ""])
    for note in matrix["epic_validation_notes"]:
        lines.append(f"### {note['epic_id']} ({note['owner_role']})")
        lines.append(f"- Focus: {note['focus']}")
        lines.append(
            "- Implemented slices: "
            + ", ".join(f"`{slice_id}`" for slice_id in note["slice_ids"])
        )
        lines.append("- Primary tests:")
        for test_ref in note["primary_tests"]:
            lines.append(f"  - `{test_ref}`")
        lines.append("- BA-10 smoke targets:")
        for target in note["ba10_smoke_targets"]:
            lines.append(f"  - {target}")
        lines.append("")

    lines.extend(["## Smoke Coverage Targets", ""])
    for target in matrix["smoke_coverage_targets"]:
        lines.append(f"### {target['target_id']}: {target['title']}")
        lines.append(f"- Acceptance scenario: `{target['acceptance_scenario']}`")
        lines.append("- Acceptance checks:")
        for check in target["acceptance_checks"]:
            lines.append(f"  - {check}")
        lines.append(
            "- Evidence code refs: "
            + ", ".join(f"`{path}`" for path in target["code_refs"])
        )
        lines.append(
            "- Evidence test refs: "
            + ", ".join(f"`{path}`" for path in target["test_refs"])
        )
        lines.append(
            "- Validation command ids: "
            + ", ".join(f"`{command_id}`" for command_id in target["validation_command_ids"])
        )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write_acceptance_trace_reports(project_root: Path | str) -> dict[str, str]:
    root = Path(project_root)
    matrix = build_acceptance_trace_matrix(root)
    json_path = root / REPORT_JSON_PATH
    md_path = root / REPORT_MD_PATH
    json_path.write_text(json.dumps(matrix, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_acceptance_trace_markdown(matrix), encoding="utf-8")
    return {
        "json_path": str(json_path),
        "markdown_path": str(md_path),
    }
