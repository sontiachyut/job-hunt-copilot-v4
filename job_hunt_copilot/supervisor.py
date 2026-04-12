from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import MappingProxyType
from typing import Final

from .artifacts import ArtifactLinkage, register_artifact_record
from .maintenance import (
    MaintenanceDependencies,
    get_maintenance_batch,
    is_daily_maintenance_due,
    maintenance_local_day,
    run_daily_maintenance_cycle,
)
from .paths import ProjectPaths
from .records import lifecycle_timestamps, new_canonical_id, now_utc_iso


RUN_STATUS_IN_PROGRESS: Final = "in_progress"
RUN_STATUS_PAUSED: Final = "paused"
RUN_STATUS_ESCALATED: Final = "escalated"
RUN_STATUS_FAILED: Final = "failed"
RUN_STATUS_COMPLETED: Final = "completed"

RUN_STATUSES = frozenset(
    {
        RUN_STATUS_IN_PROGRESS,
        RUN_STATUS_PAUSED,
        RUN_STATUS_ESCALATED,
        RUN_STATUS_FAILED,
        RUN_STATUS_COMPLETED,
    }
)
NON_TERMINAL_RUN_STATUSES = frozenset({RUN_STATUS_IN_PROGRESS, RUN_STATUS_PAUSED})
TERMINAL_RUN_STATUSES = frozenset(
    {
        RUN_STATUS_ESCALATED,
        RUN_STATUS_FAILED,
        RUN_STATUS_COMPLETED,
    }
)

REVIEW_PACKET_STATUS_NOT_READY: Final = "not_ready"
REVIEW_PACKET_STATUS_PENDING: Final = "pending_expert_review"
REVIEW_PACKET_STATUS_REVIEWED: Final = "reviewed"
REVIEW_PACKET_STATUS_SUPERSEDED: Final = "superseded"

REVIEW_PACKET_STATUSES = frozenset(
    {
        REVIEW_PACKET_STATUS_NOT_READY,
        REVIEW_PACKET_STATUS_PENDING,
        REVIEW_PACKET_STATUS_REVIEWED,
        REVIEW_PACKET_STATUS_SUPERSEDED,
    }
)

AGENT_MODE_RUNNING: Final = "running"
AGENT_MODE_PAUSED: Final = "paused"
AGENT_MODE_STOPPED: Final = "stopped"
AGENT_MODE_REPLANNING: Final = "replanning"

AGENT_MODES = frozenset(
    {
        AGENT_MODE_RUNNING,
        AGENT_MODE_PAUSED,
        AGENT_MODE_STOPPED,
        AGENT_MODE_REPLANNING,
    }
)

SUPERVISOR_CYCLE_RESULT_IN_PROGRESS: Final = "in_progress"
SUPERVISOR_CYCLE_RESULT_SUCCESS: Final = "success"
SUPERVISOR_CYCLE_RESULT_NO_WORK: Final = "no_work"
SUPERVISOR_CYCLE_RESULT_DEFERRED: Final = "deferred"
SUPERVISOR_CYCLE_RESULT_FAILED: Final = "failed"
SUPERVISOR_CYCLE_RESULT_AUTO_PAUSED: Final = "auto_paused"
SUPERVISOR_CYCLE_RESULT_REPLANNED: Final = "replanned"

SUPERVISOR_CYCLE_FINAL_RESULTS = frozenset(
    {
        SUPERVISOR_CYCLE_RESULT_SUCCESS,
        SUPERVISOR_CYCLE_RESULT_NO_WORK,
        SUPERVISOR_CYCLE_RESULT_DEFERRED,
        SUPERVISOR_CYCLE_RESULT_FAILED,
        SUPERVISOR_CYCLE_RESULT_AUTO_PAUSED,
        SUPERVISOR_CYCLE_RESULT_REPLANNED,
    }
)

SUPERVISOR_LEASE_NAME: Final = "supervisor_cycle"

INCIDENT_SEVERITY_LOW: Final = "low"
INCIDENT_SEVERITY_MEDIUM: Final = "medium"
INCIDENT_SEVERITY_HIGH: Final = "high"
INCIDENT_SEVERITY_CRITICAL: Final = "critical"

INCIDENT_SEVERITIES = frozenset(
    {
        INCIDENT_SEVERITY_LOW,
        INCIDENT_SEVERITY_MEDIUM,
        INCIDENT_SEVERITY_HIGH,
        INCIDENT_SEVERITY_CRITICAL,
    }
)

INCIDENT_STATUS_OPEN: Final = "open"
INCIDENT_STATUS_IN_REPAIR: Final = "in_repair"
INCIDENT_STATUS_RESOLVED: Final = "resolved"
INCIDENT_STATUS_ESCALATED: Final = "escalated"
INCIDENT_STATUS_SUPPRESSED: Final = "suppressed"

INCIDENT_STATUSES = frozenset(
    {
        INCIDENT_STATUS_OPEN,
        INCIDENT_STATUS_IN_REPAIR,
        INCIDENT_STATUS_RESOLVED,
        INCIDENT_STATUS_ESCALATED,
        INCIDENT_STATUS_SUPPRESSED,
    }
)
ACTIVE_INCIDENT_SELECTION_STATUSES = frozenset(
    {
        INCIDENT_STATUS_OPEN,
        INCIDENT_STATUS_IN_REPAIR,
    }
)
UNRESOLVED_INCIDENT_STATUSES = frozenset(
    {
        INCIDENT_STATUS_OPEN,
        INCIDENT_STATUS_IN_REPAIR,
        INCIDENT_STATUS_ESCALATED,
    }
)
AUTO_PAUSE_CRITICAL_INCIDENT_TYPES = frozenset(
    {
        "send_safety",
        "duplicate_send_risk",
        "credential_handling",
        "canonical_state_integrity",
    }
)

WORK_TYPE_AGENT_INCIDENT: Final = "agent_incident"
WORK_TYPE_INCIDENT_CLUSTER: Final = "incident_cluster"
WORK_TYPE_CONTACT: Final = "contact"
WORK_TYPE_GMAIL_ALERT_BATCH: Final = "gmail_alert_batch"
WORK_TYPE_GMAIL_LEAD_REPAIR: Final = "gmail_lead_repair"
WORK_TYPE_JOB_POSTING: Final = "job_posting"
WORK_TYPE_MAINTENANCE_CYCLE: Final = "maintenance_cycle"
WORK_TYPE_PIPELINE_RUN: Final = "pipeline_run"

ACTION_POLL_GMAIL_LINKEDIN_ALERTS: Final = "poll_gmail_linkedin_alerts"
ACTION_REPAIR_STALE_GMAIL_LEAD: Final = "repair_stale_gmail_lead"
ACTION_BOOTSTRAP_ROLE_TARGETED_RUN: Final = "bootstrap_role_targeted_run"
ACTION_CHECKPOINT_PIPELINE_RUN: Final = "checkpoint_pipeline_run"
ACTION_RUN_ROLE_TARGETED_RESUME_TAILORING: Final = (
    "run_role_targeted_resume_tailoring"
)
ACTION_PERFORM_MANDATORY_AGENT_REVIEW: Final = "perform_mandatory_agent_review"
ACTION_RUN_ROLE_TARGETED_PEOPLE_SEARCH: Final = "run_role_targeted_people_search"
ACTION_RUN_ROLE_TARGETED_EMAIL_DISCOVERY: Final = "run_role_targeted_email_discovery"
ACTION_RUN_ROLE_TARGETED_SENDING: Final = "run_role_targeted_sending"
ACTION_RUN_ROLE_TARGETED_DELIVERY_FEEDBACK: Final = (
    "run_role_targeted_delivery_feedback"
)
ACTION_RUN_GENERAL_LEARNING_EMAIL_DISCOVERY: Final = (
    "run_general_learning_email_discovery"
)
ACTION_RUN_GENERAL_LEARNING_OUTREACH: Final = "run_general_learning_outreach"
ACTION_RUN_GENERAL_LEARNING_DELIVERY_FEEDBACK: Final = (
    "run_general_learning_delivery_feedback"
)
ACTION_RUN_DAILY_MAINTENANCE: Final = "run_daily_maintenance"
ACTION_ESCALATE_OPEN_INCIDENT: Final = "escalate_open_incident"

TERMINAL_DELIVERY_FEEDBACK_EVENT_STATES = frozenset(
    {"bounced", "not_bounced", "replied"}
)

ELIGIBLE_POSTING_STATUSES_FOR_NEW_RUN = frozenset({"resume_review_pending", "sourced"})
SUPPORTED_PIPELINE_CHECKPOINT_STAGES = frozenset(
    {"agent_review", "lead_handoff", "resume_tailoring"}
)
ROLE_TARGETED_PIPELINE_STAGE_ACTIONS = MappingProxyType(
    {
        "lead_handoff": ACTION_CHECKPOINT_PIPELINE_RUN,
        "resume_tailoring": ACTION_RUN_ROLE_TARGETED_RESUME_TAILORING,
        "agent_review": ACTION_PERFORM_MANDATORY_AGENT_REVIEW,
        "people_search": ACTION_RUN_ROLE_TARGETED_PEOPLE_SEARCH,
        "email_discovery": ACTION_RUN_ROLE_TARGETED_EMAIL_DISCOVERY,
        "sending": ACTION_RUN_ROLE_TARGETED_SENDING,
        "delivery_feedback": ACTION_RUN_ROLE_TARGETED_DELIVERY_FEEDBACK,
    }
)

CONTROL_DEFAULTS = MappingProxyType(
    {
        "agent_enabled": "false",
        "agent_mode": AGENT_MODE_STOPPED,
        "pause_reason": "",
        "paused_at": "",
        "last_manual_command": "",
        "last_replan_at": "",
        "last_replan_reason": "",
        "last_sleep_wake_check_at": "",
        "last_seen_sleep_event_at": "",
        "last_seen_wake_event_at": "",
        "last_sleep_wake_event_ref": "",
        "active_chat_session_id": "",
        "chat_resume_on_close": "false",
        "last_chat_started_at": "",
        "last_chat_ended_at": "",
        "last_chat_exit_mode": "",
        "active_background_task_run_id": "",
        "background_task_resume_on_finish": "false",
        "gmail_poll_last_history_id": "",
        "gmail_poll_last_checkpoint_at": "",
        "gmail_poll_last_strategy": "",
    }
)

REVIEW_PACKET_TRANSITIONS = MappingProxyType(
    {
        REVIEW_PACKET_STATUS_NOT_READY: frozenset(
            {
                REVIEW_PACKET_STATUS_NOT_READY,
                REVIEW_PACKET_STATUS_PENDING,
            }
        ),
        REVIEW_PACKET_STATUS_PENDING: frozenset(
            {
                REVIEW_PACKET_STATUS_PENDING,
                REVIEW_PACKET_STATUS_REVIEWED,
                REVIEW_PACKET_STATUS_SUPERSEDED,
            }
        ),
        REVIEW_PACKET_STATUS_REVIEWED: frozenset(
            {
                REVIEW_PACKET_STATUS_REVIEWED,
                REVIEW_PACKET_STATUS_SUPERSEDED,
            }
        ),
        REVIEW_PACKET_STATUS_SUPERSEDED: frozenset({REVIEW_PACKET_STATUS_SUPERSEDED}),
    }
)

EXPERT_REVIEW_PACKET_STATUSES = frozenset(
    {
        REVIEW_PACKET_STATUS_PENDING,
        REVIEW_PACKET_STATUS_REVIEWED,
        REVIEW_PACKET_STATUS_SUPERSEDED,
    }
)

EXPERT_REVIEW_PACKET_TRANSITIONS = MappingProxyType(
    {
        REVIEW_PACKET_STATUS_PENDING: frozenset(
            {
                REVIEW_PACKET_STATUS_PENDING,
                REVIEW_PACKET_STATUS_REVIEWED,
                REVIEW_PACKET_STATUS_SUPERSEDED,
            }
        ),
        REVIEW_PACKET_STATUS_REVIEWED: frozenset(
            {
                REVIEW_PACKET_STATUS_REVIEWED,
                REVIEW_PACKET_STATUS_SUPERSEDED,
            }
        ),
        REVIEW_PACKET_STATUS_SUPERSEDED: frozenset({REVIEW_PACKET_STATUS_SUPERSEDED}),
    }
)

REVIEW_WORTHY_RUN_STATUSES = frozenset(
    {
        RUN_STATUS_ESCALATED,
        RUN_STATUS_FAILED,
        RUN_STATUS_COMPLETED,
    }
)

SUPERVISOR_COMPONENT: Final = "supervisor_agent"

_UNSET = object()


class SupervisorStateError(ValueError):
    """Raised when canonical supervisor state is invalid or contradictory."""


class InvalidLifecycleTransition(SupervisorStateError):
    """Raised when a caller attempts an unsupported state transition."""


class DuplicateActivePipelineRun(SupervisorStateError):
    """Raised when canonical state already contains multiple open runs for one posting."""


@dataclass(frozen=True)
class PipelineRunRecord:
    pipeline_run_id: str
    run_scope_type: str
    run_status: str
    current_stage: str
    lead_id: str | None
    job_posting_id: str | None
    completed_at: str | None
    last_error_summary: str | None
    review_packet_status: str | None
    run_summary: str | None
    started_at: str
    created_at: str
    updated_at: str

    @property
    def is_terminal(self) -> bool:
        return self.run_status in TERMINAL_RUN_STATUSES


@dataclass(frozen=True)
class SupervisorCycleRecord:
    supervisor_cycle_id: str
    trigger_type: str
    scheduler_name: str | None
    selected_work_type: str | None
    selected_work_id: str | None
    pipeline_run_id: str | None
    context_snapshot_path: str | None
    sleep_wake_detection_method: str | None
    sleep_wake_event_ref: str | None
    started_at: str
    completed_at: str | None
    result: str
    error_summary: str | None
    created_at: str


@dataclass(frozen=True)
class LeaseRecord:
    lease_name: str
    lease_owner_id: str
    acquired_at: str
    expires_at: str
    last_renewed_at: str | None
    lease_note: str | None


@dataclass(frozen=True)
class LeaseAcquireResult:
    status: str
    lease: LeaseRecord

    @property
    def acquired(self) -> bool:
        return self.status in {"acquired", "reclaimed"}

    @property
    def deferred(self) -> bool:
        return self.status == "deferred"


@dataclass(frozen=True)
class ControlStateSnapshot:
    values: dict[str, str]

    @property
    def agent_enabled(self) -> bool:
        return self.values["agent_enabled"] == "true"

    @property
    def agent_mode(self) -> str:
        return self.values["agent_mode"]

    @property
    def pause_reason(self) -> str | None:
        return _optional_text(self.values["pause_reason"])

    @property
    def paused_at(self) -> str | None:
        return _optional_text(self.values["paused_at"])

    @property
    def last_manual_command(self) -> str | None:
        return _optional_text(self.values["last_manual_command"])

    @property
    def last_replan_at(self) -> str | None:
        return _optional_text(self.values["last_replan_at"])

    @property
    def last_replan_reason(self) -> str | None:
        return _optional_text(self.values["last_replan_reason"])

    @property
    def last_sleep_wake_check_at(self) -> str | None:
        return _optional_text(self.values["last_sleep_wake_check_at"])

    @property
    def last_seen_sleep_event_at(self) -> str | None:
        return _optional_text(self.values["last_seen_sleep_event_at"])

    @property
    def last_seen_wake_event_at(self) -> str | None:
        return _optional_text(self.values["last_seen_wake_event_at"])

    @property
    def last_sleep_wake_event_ref(self) -> str | None:
        return _optional_text(self.values["last_sleep_wake_event_ref"])

    @property
    def active_chat_session_id(self) -> str | None:
        return _optional_text(self.values["active_chat_session_id"])

    @property
    def chat_resume_on_close(self) -> bool:
        return self.values["chat_resume_on_close"] == "true"

    @property
    def last_chat_started_at(self) -> str | None:
        return _optional_text(self.values["last_chat_started_at"])

    @property
    def last_chat_ended_at(self) -> str | None:
        return _optional_text(self.values["last_chat_ended_at"])

    @property
    def last_chat_exit_mode(self) -> str | None:
        return _optional_text(self.values["last_chat_exit_mode"])

    @property
    def active_background_task_run_id(self) -> str | None:
        return _optional_text(self.values["active_background_task_run_id"])

    @property
    def background_task_resume_on_finish(self) -> bool:
        return self.values["background_task_resume_on_finish"] == "true"

    @property
    def gmail_poll_last_history_id(self) -> str | None:
        return _optional_text(self.values["gmail_poll_last_history_id"])

    @property
    def gmail_poll_last_checkpoint_at(self) -> str | None:
        return _optional_text(self.values["gmail_poll_last_checkpoint_at"])

    @property
    def gmail_poll_last_strategy(self) -> str | None:
        return _optional_text(self.values["gmail_poll_last_strategy"])

    @property
    def allows_new_pipeline_progression(self) -> bool:
        return self.agent_enabled and self.agent_mode == AGENT_MODE_RUNNING

    @property
    def allows_safe_observational_work(self) -> bool:
        return self.agent_enabled and self.agent_mode in {AGENT_MODE_RUNNING, AGENT_MODE_PAUSED, AGENT_MODE_REPLANNING}


@dataclass(frozen=True)
class AgentIncidentRecord:
    agent_incident_id: str
    incident_type: str
    severity: str
    status: str
    summary: str
    pipeline_run_id: str | None
    lead_id: str | None
    job_posting_id: str | None
    contact_id: str | None
    outreach_message_id: str | None
    resolved_at: str | None
    escalation_reason: str | None
    repair_attempt_summary: str | None
    created_at: str
    updated_at: str
    current_stage: str | None = None

    @property
    def unresolved(self) -> bool:
        return self.status in UNRESOLVED_INCIDENT_STATUSES


@dataclass(frozen=True)
class ExpertReviewPacketRecord:
    expert_review_packet_id: str
    pipeline_run_id: str
    packet_status: str
    packet_path: str
    job_posting_id: str | None
    reviewed_at: str | None
    summary_excerpt: str | None
    created_at: str

    @property
    def markdown_path(self) -> str:
        packet_prefix, _, _ = self.packet_path.rpartition("/")
        if not packet_prefix:
            return "review_packet.md"
        return f"{packet_prefix}/review_packet.md"


@dataclass(frozen=True)
class ExpertReviewDecisionRecord:
    expert_review_decision_id: str
    expert_review_packet_id: str
    decision_type: str
    decision_notes: str | None
    override_event_id: str | None
    decided_at: str
    applied_at: str | None


@dataclass(frozen=True)
class OverrideEventRecord:
    override_event_id: str
    object_type: str
    object_id: str
    component_stage: str
    previous_value: str
    new_value: str
    override_reason: str
    override_timestamp: str
    override_by: str | None
    lead_id: str | None
    job_posting_id: str | None
    contact_id: str | None


@dataclass(frozen=True)
class SupervisorWorkUnit:
    work_type: str
    work_id: str
    action_id: str | None
    summary: str
    lead_id: str | None = None
    job_posting_id: str | None = None
    pipeline_run_id: str | None = None
    incident_id: str | None = None
    current_stage: str | None = None


@dataclass(frozen=True)
class SupervisorActionCatalogEntry:
    action_id: str
    work_type: str
    description: str
    prerequisites: tuple[str, ...]
    expected_outputs: tuple[str, ...]
    validation_references: tuple[str, ...]


@dataclass(frozen=True)
class SupervisorCycleExecution:
    cycle: SupervisorCycleRecord
    control_state: ControlStateSnapshot
    lease_status: str
    selected_work: SupervisorWorkUnit | None = None
    action_id: str | None = None
    pipeline_run: PipelineRunRecord | None = None
    incident: AgentIncidentRecord | None = None
    review_packet: ExpertReviewPacketRecord | None = None
    maintenance_batch_id: str | None = None
    context_snapshot_path: str | None = None


@dataclass(frozen=True)
class SupervisorActionDependencies:
    gmail_alert_collector: object | None = None
    apollo_people_search_provider: object | None = None
    apollo_contact_enrichment_provider: object | None = None
    recipient_profile_extractor: object | None = None
    email_finder_providers: tuple[object, ...] | None = None
    outreach_sender: object | None = None
    feedback_observer: object | None = None
    local_timezone: object | str | None = None
    maintenance_dependencies: MaintenanceDependencies | None = None


@dataclass(frozen=True)
class AutoPauseDecision:
    reason: str
    selected_work_type: str
    selected_work_id: str
    incident: AgentIncidentRecord | None = None


SUPERVISOR_ACTION_CATALOG = MappingProxyType(
    {
        ACTION_POLL_GMAIL_LINKEDIN_ALERTS: SupervisorActionCatalogEntry(
            action_id=ACTION_POLL_GMAIL_LINKEDIN_ALERTS,
            work_type=WORK_TYPE_GMAIL_ALERT_BATCH,
            description="Poll Gmail for a bounded batch of new LinkedIn job-alert emails, ingest them into canonical lead state, and materialize any ready job postings.",
            prerequisites=(
                "a Gmail alert collector is configured for the current runtime",
                "at least one uncollected LinkedIn job-alert email is currently visible in Gmail",
                "the batch remains bounded so one supervisor cycle only ingests a small number of messages",
            ),
            expected_outputs=(
                "one bounded Gmail alert batch is persisted under linkedin-scraping/runtime/gmail",
                "new Gmail-derived linkedin_leads rows are created or safely deduplicated by gmail_message_id and lead identity",
                "ready Gmail-derived leads materialize into canonical job_postings for downstream pipeline bootstrap on later cycles",
            ),
            validation_references=(
                "prd/spec.md FR-SYS-38 and current-build Gmail intake requirements",
                "prd/test-spec.feature bounded supervisor work-unit and Gmail-ingestion scenarios",
            ),
        ),
        ACTION_REPAIR_STALE_GMAIL_LEAD: SupervisorActionCatalogEntry(
            action_id=ACTION_REPAIR_STALE_GMAIL_LEAD,
            work_type=WORK_TYPE_GMAIL_LEAD_REPAIR,
            description="Repair one stale Gmail-derived lead whose original collection artifacts were persisted before the LinkedIn alert parser could recover canonical job URLs.",
            prerequisites=(
                "linkedin_lead exists in canonical state",
                "linkedin_lead.source_mode is `gmail_job_alert` and lead_status is `blocked_no_jd`",
                "the stale lead is repairable from persisted Gmail collection artifacts without fetching a new mailbox batch",
            ),
            expected_outputs=(
                "the persisted Gmail collection artifacts are refreshed with the current parser",
                "the selected Gmail lead refreshes its alert card and JD recovery artifacts from the repaired collection",
                "the repaired lead either materializes into a canonical job_posting or remains honestly blocked for a non-parser reason",
            ),
            validation_references=(
                "prd/spec.md Gmail intake durability and canonical artifact requirements",
                "prd/test-spec.feature bounded supervisor work-unit and canonical lead repair scenarios",
            ),
        ),
        ACTION_BOOTSTRAP_ROLE_TARGETED_RUN: SupervisorActionCatalogEntry(
            action_id=ACTION_BOOTSTRAP_ROLE_TARGETED_RUN,
            work_type=WORK_TYPE_JOB_POSTING,
            description="Create a durable role-targeted pipeline run from eligible posting state.",
            prerequisites=(
                "job_posting exists in canonical state",
                "job_posting.posting_status is eligible for a new role-targeted run",
                "no non-terminal pipeline_run already exists for the same job_posting_id",
            ),
            expected_outputs=(
                "one pipeline_run exists for the selected job_posting_id",
                "the pipeline_run is in_progress at the lead_handoff stage",
                "the cycle row links the selected job_posting_id to the created pipeline_run_id",
            ),
            validation_references=(
                "prd/spec.md §12.5A items 4, 36, 41, and 42",
                "prd/test-spec.feature Supervisor cycles bounded single-work-unit algorithm",
            ),
        ),
        ACTION_CHECKPOINT_PIPELINE_RUN: SupervisorActionCatalogEntry(
            action_id=ACTION_CHECKPOINT_PIPELINE_RUN,
            work_type=WORK_TYPE_PIPELINE_RUN,
            description="Advance a durable role-targeted pipeline run from lead handoff toward the next resume-tailoring boundary.",
            prerequisites=(
                "pipeline_run exists and is non-terminal",
                "pipeline_run.current_stage is `lead_handoff`",
                "linked posting state remains available for the selected run",
            ),
            expected_outputs=(
                "the existing pipeline_run is reused instead of creating a duplicate run",
                "the pipeline_run remains canonical in_progress state after the checkpoint",
                "the durable run advances into `resume_tailoring` unless the posting already has a tailored pending-review handoff, in which case it advances into `agent_review`",
                "the cycle summary points at exactly one selected pipeline_run",
            ),
            validation_references=(
                "prd/spec.md §12.5A items 3, 4, 41, and 42",
                "prd/test-spec.feature durable pipeline-run resume scenario",
            ),
        ),
        ACTION_RUN_ROLE_TARGETED_RESUME_TAILORING: SupervisorActionCatalogEntry(
            action_id=ACTION_RUN_ROLE_TARGETED_RESUME_TAILORING,
            work_type=WORK_TYPE_PIPELINE_RUN,
            description="Run the bounded role-targeted resume-tailoring boundary and advance the durable run into mandatory agent review when tailoring reaches the pending-review gate.",
            prerequisites=(
                "pipeline_run exists and is non-terminal",
                "pipeline_run.current_stage is `resume_tailoring`",
                "job_posting exists in canonical state",
                "the linked posting still has a persisted JD artifact and a base resume track can be resolved for autonomous tailoring",
            ),
            expected_outputs=(
                "the existing pipeline_run is reused instead of creating a duplicate run",
                "resume_tailoring state refreshes for the selected posting inside one bounded supervisor cycle",
                "the durable run advances to `agent_review` when tailoring reaches `resume_review_pending`, or exits terminally with honest escalation/hard-ineligible state when autonomous tailoring cannot continue",
            ),
            validation_references=(
                "prd/spec.md FR-SYS-17G, FR-SYS-17H, FR-SYS-38, and FR-OPS-03",
                "prd/test-spec.feature dependency-order and bounded supervisor work-unit scenarios",
            ),
        ),
        ACTION_PERFORM_MANDATORY_AGENT_REVIEW: SupervisorActionCatalogEntry(
            action_id=ACTION_PERFORM_MANDATORY_AGENT_REVIEW,
            work_type=WORK_TYPE_PIPELINE_RUN,
            description="Apply the bounded autonomous mandatory tailoring review and advance the durable run into the next outreach boundary.",
            prerequisites=(
                "pipeline_run exists and is non-terminal",
                "pipeline_run.current_stage is `agent_review`",
                "job_posting.posting_status is `resume_review_pending`",
                "the latest resume_tailoring_run is `tailored` and `resume_review_pending`",
            ),
            expected_outputs=(
                "the active resume_tailoring_run is recorded as agent-approved",
                "job_posting advances to `requires_contacts` or `ready_for_outreach`",
                "the same durable pipeline_run advances to `people_search` or `sending` without duplicate run history",
            ),
            validation_references=(
                "prd/spec.md FR-SYS-17I, FR-SYS-17J, FR-SYS-38, and FR-OPS-03",
                "prd/test-spec.feature mandatory agent review and dependency-order scenarios",
            ),
        ),
        ACTION_RUN_ROLE_TARGETED_PEOPLE_SEARCH: SupervisorActionCatalogEntry(
            action_id=ACTION_RUN_ROLE_TARGETED_PEOPLE_SEARCH,
            work_type=WORK_TYPE_PIPELINE_RUN,
            description="Run the bounded role-targeted people-search boundary and advance the durable run into email discovery or sending.",
            prerequisites=(
                "pipeline_run exists and is non-terminal",
                "pipeline_run.current_stage is `people_search`",
                "job_posting.posting_status is `requires_contacts` unless canonical discovery state already reached `ready_for_outreach`",
                "the selected posting remains linked to an approved tailoring decision",
            ),
            expected_outputs=(
                "the existing pipeline_run is reused instead of creating a duplicate run",
                "people_search_result.json and shortlist state are refreshed when search is still due",
                "the durable run advances to `email_discovery` or `sending` based on canonical readiness",
            ),
            validation_references=(
                "prd/spec.md §1.2 current-build required path items 6 through 9",
                "prd/test-spec.feature role-targeted orchestration and dependency-order scenarios",
            ),
        ),
        ACTION_RUN_ROLE_TARGETED_EMAIL_DISCOVERY: SupervisorActionCatalogEntry(
            action_id=ACTION_RUN_ROLE_TARGETED_EMAIL_DISCOVERY,
            work_type=WORK_TYPE_PIPELINE_RUN,
            description="Run one bounded role-targeted email-discovery step and advance the durable run into sending when the active send set becomes ready.",
            prerequisites=(
                "pipeline_run exists and is non-terminal",
                "pipeline_run.current_stage is `email_discovery`",
                "job_posting.posting_status is `requires_contacts` unless canonical readiness already reached `ready_for_outreach`",
                "the selected posting still has an approved tailoring decision and at least one current send-set contact to inspect",
            ),
            expected_outputs=(
                "the existing pipeline_run is reused instead of creating a duplicate run",
                "one current send-set contact runs through bounded email discovery or working-email reuse",
                "discovery_result.json and canonical discovery state refresh when discovery work is still due",
                "the durable run advances to `sending` only when the active send set is truly ready",
            ),
            validation_references=(
                "prd/spec.md FR-SYS-38, FR-SYS-38H, FR-SYS-41, FR-SYS-41B, and FR-OPS-03",
                "prd/test-spec.feature dependency-order, discovery-readiness, and send-set gate scenarios",
            ),
        ),
        ACTION_RUN_ROLE_TARGETED_SENDING: SupervisorActionCatalogEntry(
            action_id=ACTION_RUN_ROLE_TARGETED_SENDING,
            work_type=WORK_TYPE_PIPELINE_RUN,
            description="Run one bounded role-targeted sending step, generating drafts when needed, and advance the durable run to delivery feedback once the active wave is complete.",
            prerequisites=(
                "pipeline_run exists and is non-terminal",
                "pipeline_run.current_stage is `sending`",
                "job_posting.posting_status is `ready_for_outreach`, `outreach_in_progress`, or `completed`",
                "the selected posting remains linked to an approved tailoring decision",
                "a bounded outreach sender is configured before any automatic send is attempted",
            ),
            expected_outputs=(
                "the existing pipeline_run is reused instead of creating a duplicate run",
                "the current ready send set is drafted before any automatic send attempt when draft artifacts are still missing",
                "one safe automatic send may execute while pacing and repeat-outreach guardrails remain active",
                "the durable run stays at `sending` while later-wave contacts remain due later, advances to `delivery_feedback` after a sent terminal wave, or completes with review artifacts after a no-send blocked terminal wave",
            ),
            validation_references=(
                "prd/spec.md §1.2 current-build required path items 10 through 13",
                "prd/test-spec.feature drafting-before-sending, pacing, dependency-order, and post-send feedback scenarios",
            ),
        ),
        ACTION_RUN_ROLE_TARGETED_DELIVERY_FEEDBACK: SupervisorActionCatalogEntry(
            action_id=ACTION_RUN_ROLE_TARGETED_DELIVERY_FEEDBACK,
            work_type=WORK_TYPE_PIPELINE_RUN,
            description="Inspect persisted delayed feedback for the selected role-targeted posting and complete the durable run once each sent message has a high-level feedback outcome.",
            prerequisites=(
                "pipeline_run exists and is non-terminal",
                "pipeline_run.current_stage is `delivery_feedback`",
                "job_posting.posting_status is `completed` after the terminal send wave",
                "the selected posting remains linked to an approved tailoring decision",
                "at least one sent outreach_message exists for the selected posting",
            ),
            expected_outputs=(
                "the existing pipeline_run is reused instead of creating a duplicate run",
                "the supervisor reads canonical delivery_feedback_events that the separate feedback-sync worker persists",
                "the durable run stays at `delivery_feedback` while high-level feedback outcomes remain pending and completes with review artifacts once every sent message has reached a high-level feedback state",
            ),
            validation_references=(
                "prd/spec.md FR-SYS-38, FR-SYS-38D5 through FR-SYS-38D9, FR-EF-01J through FR-EF-01P, and FR-OPS-17C",
                "prd/test-spec.feature delivery-feedback timing, delayed-bounce, dependency-order, and end-to-end acceptance scenarios",
            ),
        ),
        ACTION_RUN_GENERAL_LEARNING_EMAIL_DISCOVERY: SupervisorActionCatalogEntry(
            action_id=ACTION_RUN_GENERAL_LEARNING_EMAIL_DISCOVERY,
            work_type=WORK_TYPE_CONTACT,
            description="Run one bounded contact-rooted general-learning email-discovery step so a non-posting contact can become send-ready without entering the role-targeted review path.",
            prerequisites=(
                "contact exists in canonical state",
                "contact does not yet have a usable working email and is not tied to a current job_posting contact link",
                "the selected contact has no prior sent outreach history that would require repeat-outreach review",
                "the selected contact has no active general-learning message state yet",
            ),
            expected_outputs=(
                "the supervisor runs one bounded contact-rooted email-discovery attempt or working-email reuse step",
                "discovery_result.json and canonical contact discovery state refresh without adding posting linkage",
                "the selected contact either becomes `working_email_found`, stays eligible for later bounded discovery, or becomes `exhausted` when the current provider set is spent",
            ),
            validation_references=(
                "prd/spec.md FR-SYS-38A, FR-SYS-41, FR-SYS-41B, and FR-OPS-17K",
                "prd/test-spec.feature general-learning orchestration and discovery-before-send scenarios",
            ),
        ),
        ACTION_RUN_GENERAL_LEARNING_OUTREACH: SupervisorActionCatalogEntry(
            action_id=ACTION_RUN_GENERAL_LEARNING_OUTREACH,
            work_type=WORK_TYPE_CONTACT,
            description="Run one bounded contact-rooted general-learning outreach step for a send-ready contact without requiring posting-specific tailoring or agent review.",
            prerequisites=(
                "contact exists in canonical state",
                "contact has a usable working email and is not tied to a current job_posting contact link",
                "the selected contact has no prior sent outreach history that would require repeat-outreach review",
                "a bounded outreach sender is configured before any automatic send is attempted",
            ),
            expected_outputs=(
                "the supervisor reuses an existing generated general-learning draft or creates one when missing",
                "the selected contact receives at most one bounded general-learning send attempt in the cycle",
                "outreach_messages and send_result.json persist the resulting sent, blocked, or failed outcome without adding posting linkage",
            ),
            validation_references=(
                "prd/spec.md FR-SYS-38A, FR-EM-12E1, and FR-OPS-17K",
                "prd/test-spec.feature general-learning drafting and orchestration scenarios",
            ),
        ),
        ACTION_RUN_GENERAL_LEARNING_DELIVERY_FEEDBACK: SupervisorActionCatalogEntry(
            action_id=ACTION_RUN_GENERAL_LEARNING_DELIVERY_FEEDBACK,
            work_type=WORK_TYPE_CONTACT,
            description="Reserved legacy supervisor action for contact-rooted delayed feedback; active mailbox polling is handled by the separate feedback-sync worker.",
            prerequisites=(
                "contact exists in canonical state",
                "the selected contact is not tied to a current job_posting contact link",
                "at least one sent contact-rooted general-learning outreach_message still lacks a terminal feedback outcome",
            ),
            expected_outputs=(
                "the feedback-sync worker persists mailbox-observed delivery feedback without introducing pipeline-run or posting linkage",
            ),
            validation_references=(
                "prd/spec.md FR-SYS-38A, FR-SYS-38D2, FR-EF-01J through FR-EF-01P, and FR-OPS-17K",
                "prd/test-spec.feature general-learning orchestration, delayed feedback timing, and delayed-bounce scenarios",
            ),
        ),
        ACTION_RUN_DAILY_MAINTENANCE: SupervisorActionCatalogEntry(
            action_id=ACTION_RUN_DAILY_MAINTENANCE,
            work_type=WORK_TYPE_MAINTENANCE_CYCLE,
            description="Create one bounded isolated daily maintenance batch, record its validation evidence, and leave merge approval explicit.",
            prerequisites=(
                "no maintenance_change_batch has been created for the current local day",
                "no non-terminal role-targeted pipeline_run is active",
                "the maintenance workflow is enabled for the current runtime",
            ),
            expected_outputs=(
                "one maintenance_change_batches row exists for the current local day",
                "maintenance_change.json and maintenance_change.md exist for that batch",
                "validation outcomes and approval state remain reviewable without auto-merging",
            ),
            validation_references=(
                "prd/spec.md FR-OPS-17P through FR-OPS-17W6",
                "prd/test-spec.feature maintenance automation scenarios",
            ),
        ),
        ACTION_ESCALATE_OPEN_INCIDENT: SupervisorActionCatalogEntry(
            action_id=ACTION_ESCALATE_OPEN_INCIDENT,
            work_type=WORK_TYPE_AGENT_INCIDENT,
            description="Escalate one unresolved operational incident when no bounded repair action exists yet.",
            prerequisites=(
                "agent_incident exists in an active unresolved state",
                "the incident is still canonically visible for supervisor review",
            ),
            expected_outputs=(
                "the incident becomes escalated with an explicit escalation reason",
                "ordinary pipeline progression stays deferred behind the selected incident work unit",
            ),
            validation_references=(
                "prd/spec.md §12.5A items 12, 13, 14, and 41",
                "prd/test-spec.feature supervisor work-priority and auto-pause scenarios",
            ),
        ),
    }
)


def read_agent_control_state(
    connection: sqlite3.Connection,
    *,
    timestamp: str | None = None,
) -> ControlStateSnapshot:
    _ensure_control_defaults(connection, timestamp=timestamp)
    rows = connection.execute(
        """
        SELECT control_key, control_value
        FROM agent_control_state
        WHERE control_key IN ({})
        ORDER BY control_key
        """.format(",".join("?" for _ in CONTROL_DEFAULTS)),
        tuple(CONTROL_DEFAULTS.keys()),
    ).fetchall()
    values = dict(CONTROL_DEFAULTS)
    for control_key, control_value in rows:
        values[control_key] = control_value
    return ControlStateSnapshot(values=values)


def upsert_control_values(
    connection: sqlite3.Connection,
    updates: dict[str, str | bool | None],
    *,
    timestamp: str | None = None,
) -> ControlStateSnapshot:
    current_timestamp = timestamp or now_utc_iso()
    _ensure_control_defaults(connection, timestamp=current_timestamp)

    rows = [
        (control_key, _normalize_control_value(control_value), current_timestamp)
        for control_key, control_value in updates.items()
    ]
    with connection:
        connection.executemany(
            """
            INSERT INTO agent_control_state (control_key, control_value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(control_key) DO UPDATE SET
              control_value = excluded.control_value,
              updated_at = excluded.updated_at
            """,
            rows,
        )
    return read_agent_control_state(connection, timestamp=current_timestamp)


def resume_agent(
    connection: sqlite3.Connection,
    *,
    manual_command: str | None = None,
    timestamp: str | None = None,
) -> ControlStateSnapshot:
    updates = {
        "agent_enabled": True,
        "agent_mode": AGENT_MODE_RUNNING,
        "pause_reason": None,
        "paused_at": None,
    }
    if manual_command is not None:
        updates["last_manual_command"] = manual_command
    return upsert_control_values(connection, updates, timestamp=timestamp)


def pause_agent(
    connection: sqlite3.Connection,
    *,
    reason: str,
    manual_command: str | None = None,
    timestamp: str | None = None,
) -> ControlStateSnapshot:
    if not reason.strip():
        raise SupervisorStateError("Pause reason is required.")
    current_timestamp = timestamp or now_utc_iso()
    updates = {
        "agent_enabled": True,
        "agent_mode": AGENT_MODE_PAUSED,
        "pause_reason": reason,
        "paused_at": current_timestamp,
    }
    if manual_command is not None:
        updates["last_manual_command"] = manual_command
    return upsert_control_values(connection, updates, timestamp=current_timestamp)


def stop_agent(
    connection: sqlite3.Connection,
    *,
    manual_command: str | None = None,
    timestamp: str | None = None,
) -> ControlStateSnapshot:
    updates = {
        "agent_enabled": False,
        "agent_mode": AGENT_MODE_STOPPED,
        "pause_reason": None,
        "paused_at": None,
    }
    if manual_command is not None:
        updates["last_manual_command"] = manual_command
    return upsert_control_values(connection, updates, timestamp=timestamp)


def begin_replanning(
    connection: sqlite3.Connection,
    *,
    reason: str,
    manual_command: str | None = None,
    timestamp: str | None = None,
) -> ControlStateSnapshot:
    if not reason.strip():
        raise SupervisorStateError("Replanning reason is required.")
    current_timestamp = timestamp or now_utc_iso()
    updates = {
        "agent_enabled": True,
        "agent_mode": AGENT_MODE_REPLANNING,
        "pause_reason": None,
        "paused_at": None,
        "last_replan_at": current_timestamp,
        "last_replan_reason": reason,
    }
    if manual_command is not None:
        updates["last_manual_command"] = manual_command
    return upsert_control_values(connection, updates, timestamp=current_timestamp)


def get_pipeline_run(
    connection: sqlite3.Connection,
    pipeline_run_id: str,
) -> PipelineRunRecord | None:
    row = connection.execute(
        """
        SELECT pipeline_run_id, run_scope_type, run_status, current_stage, lead_id,
               job_posting_id, completed_at, last_error_summary, review_packet_status,
               run_summary, started_at, created_at, updated_at
        FROM pipeline_runs
        WHERE pipeline_run_id = ?
        """,
        (pipeline_run_id,),
    ).fetchone()
    return None if row is None else _pipeline_run_from_row(row)


def get_open_pipeline_run_for_posting(
    connection: sqlite3.Connection,
    job_posting_id: str,
) -> PipelineRunRecord | None:
    rows = connection.execute(
        """
        SELECT pipeline_run_id, run_scope_type, run_status, current_stage, lead_id,
               job_posting_id, completed_at, last_error_summary, review_packet_status,
               run_summary, started_at, created_at, updated_at
        FROM pipeline_runs
        WHERE job_posting_id = ?
          AND run_status IN (?, ?)
        ORDER BY started_at DESC, created_at DESC
        """,
        (
            job_posting_id,
            RUN_STATUS_IN_PROGRESS,
            RUN_STATUS_PAUSED,
        ),
    ).fetchall()
    if not rows:
        return None
    if len(rows) > 1:
        raise DuplicateActivePipelineRun(
            f"Found multiple non-terminal pipeline_runs for job_posting_id={job_posting_id}."
        )
    return _pipeline_run_from_row(rows[0])


def ensure_role_targeted_pipeline_run(
    connection: sqlite3.Connection,
    *,
    lead_id: str,
    job_posting_id: str,
    current_stage: str,
    started_at: str | None = None,
    pipeline_run_id: str | None = None,
    run_summary: str | None = None,
) -> tuple[PipelineRunRecord, bool]:
    existing = get_open_pipeline_run_for_posting(connection, job_posting_id)
    if existing is not None:
        return existing, False

    current_timestamp = started_at or now_utc_iso()
    timestamps = lifecycle_timestamps(current_timestamp)
    pipeline_run_id = pipeline_run_id or new_canonical_id("pipeline_runs")
    with connection:
        connection.execute(
            """
            INSERT INTO pipeline_runs (
              pipeline_run_id, run_scope_type, run_status, current_stage, lead_id,
              job_posting_id, completed_at, last_error_summary, review_packet_status,
              run_summary, started_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pipeline_run_id,
                "role_targeted_posting",
                RUN_STATUS_IN_PROGRESS,
                current_stage,
                lead_id,
                job_posting_id,
                None,
                None,
                REVIEW_PACKET_STATUS_NOT_READY,
                run_summary,
                current_timestamp,
                timestamps["created_at"],
                timestamps["updated_at"],
            ),
        )
    created = get_pipeline_run(connection, pipeline_run_id)
    if created is None:  # pragma: no cover - defensive invariant
        raise SupervisorStateError(f"Failed to load pipeline_run {pipeline_run_id} after creation.")
    return created, True


def advance_pipeline_run(
    connection: sqlite3.Connection,
    pipeline_run_id: str,
    *,
    current_stage: str,
    run_summary: str | None = _UNSET,
    timestamp: str | None = None,
) -> PipelineRunRecord:
    return _update_pipeline_run(
        connection,
        pipeline_run_id,
        new_status=RUN_STATUS_IN_PROGRESS,
        current_stage=current_stage,
        run_summary=run_summary,
        completed_at=None,
        last_error_summary=None,
        timestamp=timestamp,
    )


def pause_pipeline_run(
    connection: sqlite3.Connection,
    pipeline_run_id: str,
    *,
    current_stage: str | None = None,
    error_summary: str | None = _UNSET,
    run_summary: str | None = _UNSET,
    timestamp: str | None = None,
) -> PipelineRunRecord:
    return _update_pipeline_run(
        connection,
        pipeline_run_id,
        new_status=RUN_STATUS_PAUSED,
        current_stage=current_stage,
        last_error_summary=error_summary,
        run_summary=run_summary,
        completed_at=None,
        timestamp=timestamp,
    )


def escalate_pipeline_run(
    connection: sqlite3.Connection,
    pipeline_run_id: str,
    *,
    current_stage: str | None = None,
    error_summary: str | None = _UNSET,
    run_summary: str | None = _UNSET,
    timestamp: str | None = None,
) -> PipelineRunRecord:
    current_timestamp = timestamp or now_utc_iso()
    return _update_pipeline_run(
        connection,
        pipeline_run_id,
        new_status=RUN_STATUS_ESCALATED,
        current_stage=current_stage,
        last_error_summary=error_summary,
        run_summary=run_summary,
        completed_at=current_timestamp,
        timestamp=current_timestamp,
    )


def fail_pipeline_run(
    connection: sqlite3.Connection,
    pipeline_run_id: str,
    *,
    current_stage: str | None = None,
    error_summary: str,
    run_summary: str | None = _UNSET,
    timestamp: str | None = None,
) -> PipelineRunRecord:
    if not error_summary.strip():
        raise SupervisorStateError("Failure summary is required.")
    current_timestamp = timestamp or now_utc_iso()
    return _update_pipeline_run(
        connection,
        pipeline_run_id,
        new_status=RUN_STATUS_FAILED,
        current_stage=current_stage,
        last_error_summary=error_summary,
        run_summary=run_summary,
        completed_at=current_timestamp,
        timestamp=current_timestamp,
    )


def complete_pipeline_run(
    connection: sqlite3.Connection,
    pipeline_run_id: str,
    *,
    current_stage: str = "completed",
    run_summary: str | None = _UNSET,
    timestamp: str | None = None,
) -> PipelineRunRecord:
    current_timestamp = timestamp or now_utc_iso()
    return _update_pipeline_run(
        connection,
        pipeline_run_id,
        new_status=RUN_STATUS_COMPLETED,
        current_stage=current_stage,
        run_summary=run_summary,
        completed_at=current_timestamp,
        timestamp=current_timestamp,
    )


def set_pipeline_run_review_packet_status(
    connection: sqlite3.Connection,
    pipeline_run_id: str,
    review_packet_status: str,
    *,
    timestamp: str | None = None,
) -> PipelineRunRecord:
    if review_packet_status not in REVIEW_PACKET_STATUSES:
        raise SupervisorStateError(
            f"Unsupported review_packet_status={review_packet_status!r}."
        )
    current = _require_pipeline_run(connection, pipeline_run_id)
    current_review_status = current.review_packet_status or REVIEW_PACKET_STATUS_NOT_READY
    allowed = REVIEW_PACKET_TRANSITIONS[current_review_status]
    if review_packet_status not in allowed:
        raise InvalidLifecycleTransition(
            f"Cannot transition review_packet_status from {current_review_status!r} "
            f"to {review_packet_status!r}."
        )
    return _update_pipeline_run(
        connection,
        pipeline_run_id,
        review_packet_status=review_packet_status,
        timestamp=timestamp,
    )


def start_supervisor_cycle(
    connection: sqlite3.Connection,
    *,
    trigger_type: str,
    scheduler_name: str | None = None,
    sleep_wake_detection_method: str | None = None,
    sleep_wake_event_ref: str | None = None,
    started_at: str | None = None,
    supervisor_cycle_id: str | None = None,
) -> SupervisorCycleRecord:
    current_timestamp = started_at or now_utc_iso()
    supervisor_cycle_id = supervisor_cycle_id or new_canonical_id("supervisor_cycles")
    timestamps = lifecycle_timestamps(current_timestamp)
    with connection:
        connection.execute(
            """
            INSERT INTO supervisor_cycles (
              supervisor_cycle_id, trigger_type, scheduler_name, selected_work_type,
              selected_work_id, pipeline_run_id, context_snapshot_path,
              sleep_wake_detection_method, sleep_wake_event_ref, started_at,
              completed_at, result, error_summary, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                supervisor_cycle_id,
                trigger_type,
                scheduler_name,
                None,
                None,
                None,
                None,
                sleep_wake_detection_method,
                sleep_wake_event_ref,
                current_timestamp,
                None,
                SUPERVISOR_CYCLE_RESULT_IN_PROGRESS,
                None,
                timestamps["created_at"],
            ),
        )
    cycle = get_supervisor_cycle(connection, supervisor_cycle_id)
    if cycle is None:  # pragma: no cover - defensive invariant
        raise SupervisorStateError(
            f"Failed to load supervisor_cycle {supervisor_cycle_id} after creation."
        )
    return cycle


def assign_supervisor_cycle_work_unit(
    connection: sqlite3.Connection,
    supervisor_cycle_id: str,
    *,
    selected_work_type: str,
    selected_work_id: str,
    pipeline_run_id: str | None = None,
    context_snapshot_path: str | None = None,
) -> SupervisorCycleRecord:
    cycle = _require_supervisor_cycle(connection, supervisor_cycle_id)
    if cycle.result != SUPERVISOR_CYCLE_RESULT_IN_PROGRESS:
        raise InvalidLifecycleTransition(
            f"Cannot assign work to completed supervisor_cycle {supervisor_cycle_id}."
        )
    with connection:
        connection.execute(
            """
            UPDATE supervisor_cycles
            SET selected_work_type = ?,
                selected_work_id = ?,
                pipeline_run_id = ?,
                context_snapshot_path = ?
            WHERE supervisor_cycle_id = ?
            """,
            (
                selected_work_type,
                selected_work_id,
                pipeline_run_id,
                context_snapshot_path,
                supervisor_cycle_id,
            ),
        )
    return _require_supervisor_cycle(connection, supervisor_cycle_id)


def finish_supervisor_cycle(
    connection: sqlite3.Connection,
    supervisor_cycle_id: str,
    *,
    result: str,
    completed_at: str | None = None,
    error_summary: str | None = None,
) -> SupervisorCycleRecord:
    if result not in SUPERVISOR_CYCLE_FINAL_RESULTS:
        raise SupervisorStateError(f"Unsupported supervisor cycle result={result!r}.")
    cycle = _require_supervisor_cycle(connection, supervisor_cycle_id)
    if cycle.result != SUPERVISOR_CYCLE_RESULT_IN_PROGRESS:
        raise InvalidLifecycleTransition(
            f"Supervisor cycle {supervisor_cycle_id} is already finalized with {cycle.result!r}."
        )
    current_timestamp = completed_at or now_utc_iso()
    with connection:
        connection.execute(
            """
            UPDATE supervisor_cycles
            SET completed_at = ?,
                result = ?,
                error_summary = ?
            WHERE supervisor_cycle_id = ?
            """,
            (
                current_timestamp,
                result,
                error_summary,
                supervisor_cycle_id,
            ),
        )
    return _require_supervisor_cycle(connection, supervisor_cycle_id)


def get_supervisor_cycle(
    connection: sqlite3.Connection,
    supervisor_cycle_id: str,
) -> SupervisorCycleRecord | None:
    row = connection.execute(
        """
        SELECT supervisor_cycle_id, trigger_type, scheduler_name, selected_work_type,
               selected_work_id, pipeline_run_id, context_snapshot_path,
               sleep_wake_detection_method, sleep_wake_event_ref, started_at,
               completed_at, result, error_summary, created_at
        FROM supervisor_cycles
        WHERE supervisor_cycle_id = ?
        """,
        (supervisor_cycle_id,),
    ).fetchone()
    return None if row is None else _supervisor_cycle_from_row(row)


def acquire_runtime_lease(
    connection: sqlite3.Connection,
    *,
    lease_name: str,
    lease_owner_id: str,
    ttl_seconds: int,
    now: str | None = None,
    lease_note: str | None = None,
) -> LeaseAcquireResult:
    if ttl_seconds <= 0:
        raise SupervisorStateError("ttl_seconds must be positive.")

    current_timestamp = now or now_utc_iso()
    expires_at = _timestamp_plus_seconds(current_timestamp, ttl_seconds)

    connection.execute("BEGIN IMMEDIATE")
    try:
        row = connection.execute(
            """
            SELECT lease_name, lease_owner_id, acquired_at, expires_at, last_renewed_at, lease_note
            FROM agent_runtime_leases
            WHERE lease_name = ?
            """,
            (lease_name,),
        ).fetchone()
        if row is None:
            connection.execute(
                """
                INSERT INTO agent_runtime_leases (
                  lease_name, lease_owner_id, acquired_at, expires_at, last_renewed_at, lease_note
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    lease_name,
                    lease_owner_id,
                    current_timestamp,
                    expires_at,
                    current_timestamp,
                    lease_note,
                ),
            )
            connection.commit()
            return LeaseAcquireResult(
                status="acquired",
                lease=LeaseRecord(
                    lease_name=lease_name,
                    lease_owner_id=lease_owner_id,
                    acquired_at=current_timestamp,
                    expires_at=expires_at,
                    last_renewed_at=current_timestamp,
                    lease_note=lease_note,
                ),
            )

        current_lease = _lease_from_row(row)
        if _lease_is_expired(current_lease, current_timestamp):
            connection.execute(
                """
                UPDATE agent_runtime_leases
                SET lease_owner_id = ?,
                    acquired_at = ?,
                    expires_at = ?,
                    last_renewed_at = ?,
                    lease_note = ?
                WHERE lease_name = ?
                """,
                (
                    lease_owner_id,
                    current_timestamp,
                    expires_at,
                    current_timestamp,
                    lease_note,
                    lease_name,
                ),
            )
            connection.commit()
            return LeaseAcquireResult(
                status="reclaimed",
                lease=LeaseRecord(
                    lease_name=lease_name,
                    lease_owner_id=lease_owner_id,
                    acquired_at=current_timestamp,
                    expires_at=expires_at,
                    last_renewed_at=current_timestamp,
                    lease_note=lease_note,
                ),
            )

        connection.commit()
        return LeaseAcquireResult(status="deferred", lease=current_lease)
    except Exception:
        connection.rollback()
        raise


def renew_runtime_lease(
    connection: sqlite3.Connection,
    *,
    lease_name: str,
    lease_owner_id: str,
    ttl_seconds: int,
    now: str | None = None,
    lease_note: str | None = None,
) -> LeaseRecord:
    if ttl_seconds <= 0:
        raise SupervisorStateError("ttl_seconds must be positive.")

    current_timestamp = now or now_utc_iso()
    expires_at = _timestamp_plus_seconds(current_timestamp, ttl_seconds)
    lease = _require_runtime_lease(connection, lease_name)
    if lease.lease_owner_id != lease_owner_id:
        raise InvalidLifecycleTransition(
            f"Lease {lease_name} is owned by {lease.lease_owner_id!r}, not {lease_owner_id!r}."
        )
    if _lease_is_expired(lease, current_timestamp):
        raise InvalidLifecycleTransition(
            f"Lease {lease_name} expired at {lease.expires_at}; reacquire it instead of renewing."
        )

    with connection:
        connection.execute(
            """
            UPDATE agent_runtime_leases
            SET expires_at = ?,
                last_renewed_at = ?,
                lease_note = ?
            WHERE lease_name = ?
            """,
            (
                expires_at,
                current_timestamp,
                lease_note if lease_note is not None else lease.lease_note,
                lease_name,
            ),
        )
    return _require_runtime_lease(connection, lease_name)


def release_runtime_lease(
    connection: sqlite3.Connection,
    *,
    lease_name: str,
    lease_owner_id: str,
) -> bool:
    with connection:
        result = connection.execute(
            """
            DELETE FROM agent_runtime_leases
            WHERE lease_name = ?
              AND lease_owner_id = ?
            """,
            (
                lease_name,
                lease_owner_id,
            ),
        )
    return result.rowcount > 0


def get_runtime_lease(
    connection: sqlite3.Connection,
    lease_name: str,
) -> LeaseRecord | None:
    row = connection.execute(
        """
        SELECT lease_name, lease_owner_id, acquired_at, expires_at, last_renewed_at, lease_note
        FROM agent_runtime_leases
        WHERE lease_name = ?
        """,
        (lease_name,),
    ).fetchone()
    return None if row is None else _lease_from_row(row)


def registered_supervisor_action_catalog() -> MappingProxyType[str, SupervisorActionCatalogEntry]:
    return SUPERVISOR_ACTION_CATALOG


def get_agent_incident(
    connection: sqlite3.Connection,
    agent_incident_id: str,
) -> AgentIncidentRecord | None:
    row = connection.execute(
        """
        SELECT agent_incident_id, incident_type, severity, status, summary,
               pipeline_run_id, lead_id, job_posting_id, contact_id,
               outreach_message_id, resolved_at, escalation_reason,
               repair_attempt_summary, created_at, updated_at
        FROM agent_incidents
        WHERE agent_incident_id = ?
        """,
        (agent_incident_id,),
    ).fetchone()
    return None if row is None else _agent_incident_from_row(row)


def create_agent_incident(
    connection: sqlite3.Connection,
    *,
    incident_type: str,
    severity: str,
    summary: str,
    status: str = INCIDENT_STATUS_OPEN,
    pipeline_run_id: str | None = None,
    lead_id: str | None = None,
    job_posting_id: str | None = None,
    contact_id: str | None = None,
    outreach_message_id: str | None = None,
    escalation_reason: str | None = None,
    repair_attempt_summary: str | None = None,
    created_at: str | None = None,
    agent_incident_id: str | None = None,
) -> AgentIncidentRecord:
    if not incident_type.strip():
        raise SupervisorStateError("incident_type is required.")
    if severity not in INCIDENT_SEVERITIES:
        raise SupervisorStateError(f"Unsupported incident severity={severity!r}.")
    if status not in INCIDENT_STATUSES:
        raise SupervisorStateError(f"Unsupported incident status={status!r}.")
    if not summary.strip():
        raise SupervisorStateError("Incident summary is required.")

    current_timestamp = created_at or now_utc_iso()
    timestamps = lifecycle_timestamps(current_timestamp)
    agent_incident_id = agent_incident_id or new_canonical_id("agent_incidents")
    with connection:
        connection.execute(
            """
            INSERT INTO agent_incidents (
              agent_incident_id, incident_type, severity, status, summary,
              pipeline_run_id, lead_id, job_posting_id, contact_id,
              outreach_message_id, resolved_at, escalation_reason,
              repair_attempt_summary, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                agent_incident_id,
                incident_type,
                severity,
                status,
                summary,
                pipeline_run_id,
                lead_id,
                job_posting_id,
                contact_id,
                outreach_message_id,
                current_timestamp if status == INCIDENT_STATUS_RESOLVED else None,
                escalation_reason,
                repair_attempt_summary,
                timestamps["created_at"],
                timestamps["updated_at"],
            ),
        )
    incident = get_agent_incident(connection, agent_incident_id)
    if incident is None:  # pragma: no cover - defensive invariant
        raise SupervisorStateError(
            f"Failed to load agent_incident {agent_incident_id} after creation."
        )
    return incident


def list_unresolved_agent_incidents(
    connection: sqlite3.Connection,
) -> list[AgentIncidentRecord]:
    rows = connection.execute(
        """
        SELECT ai.agent_incident_id, ai.incident_type, ai.severity, ai.status, ai.summary,
               ai.pipeline_run_id, ai.lead_id, ai.job_posting_id, ai.contact_id,
               ai.outreach_message_id, ai.resolved_at, ai.escalation_reason,
               ai.repair_attempt_summary, ai.created_at, ai.updated_at, pr.current_stage
        FROM agent_incidents ai
        LEFT JOIN pipeline_runs pr
          ON pr.pipeline_run_id = ai.pipeline_run_id
        WHERE ai.status IN (?, ?, ?)
        ORDER BY
          CASE ai.severity
            WHEN 'critical' THEN 0
            WHEN 'high' THEN 1
            WHEN 'medium' THEN 2
            ELSE 3
          END,
          ai.created_at ASC
        """,
        (
            INCIDENT_STATUS_OPEN,
            INCIDENT_STATUS_IN_REPAIR,
            INCIDENT_STATUS_ESCALATED,
        ),
    ).fetchall()
    return [_agent_incident_from_row(row) for row in rows]


def escalate_agent_incident(
    connection: sqlite3.Connection,
    agent_incident_id: str,
    *,
    escalation_reason: str,
    timestamp: str | None = None,
    repair_attempt_summary: str | None = None,
) -> AgentIncidentRecord:
    if not escalation_reason.strip():
        raise SupervisorStateError("Escalation reason is required.")
    incident = _require_agent_incident(connection, agent_incident_id)
    if incident.status in {INCIDENT_STATUS_RESOLVED, INCIDENT_STATUS_SUPPRESSED}:
        raise InvalidLifecycleTransition(
            f"Cannot escalate agent_incident {agent_incident_id} from {incident.status!r}."
        )

    current_timestamp = timestamp or now_utc_iso()
    updated_repair_summary = repair_attempt_summary
    if updated_repair_summary is None and incident.repair_attempt_summary:
        updated_repair_summary = incident.repair_attempt_summary

    with connection:
        connection.execute(
            """
            UPDATE agent_incidents
            SET status = ?,
                escalation_reason = ?,
                repair_attempt_summary = ?,
                updated_at = ?
            WHERE agent_incident_id = ?
            """,
            (
                INCIDENT_STATUS_ESCALATED,
                escalation_reason,
                updated_repair_summary,
                current_timestamp,
                agent_incident_id,
            ),
        )
    return _require_agent_incident(connection, agent_incident_id)


def get_expert_review_packet(
    connection: sqlite3.Connection,
    expert_review_packet_id: str,
) -> ExpertReviewPacketRecord | None:
    row = connection.execute(
        """
        SELECT expert_review_packet_id, pipeline_run_id, packet_status, packet_path,
               job_posting_id, reviewed_at, summary_excerpt, created_at
        FROM expert_review_packets
        WHERE expert_review_packet_id = ?
        """,
        (expert_review_packet_id,),
    ).fetchone()
    return None if row is None else _expert_review_packet_from_row(row)


def list_expert_review_packets_for_run(
    connection: sqlite3.Connection,
    pipeline_run_id: str,
) -> list[ExpertReviewPacketRecord]:
    rows = connection.execute(
        """
        SELECT expert_review_packet_id, pipeline_run_id, packet_status, packet_path,
               job_posting_id, reviewed_at, summary_excerpt, created_at
        FROM expert_review_packets
        WHERE pipeline_run_id = ?
        ORDER BY created_at DESC, expert_review_packet_id DESC
        """,
        (pipeline_run_id,),
    ).fetchall()
    return [_expert_review_packet_from_row(row) for row in rows]


def get_expert_review_decision(
    connection: sqlite3.Connection,
    expert_review_decision_id: str,
) -> ExpertReviewDecisionRecord | None:
    row = connection.execute(
        """
        SELECT expert_review_decision_id, expert_review_packet_id, decision_type,
               decision_notes, override_event_id, decided_at, applied_at
        FROM expert_review_decisions
        WHERE expert_review_decision_id = ?
        """,
        (expert_review_decision_id,),
    ).fetchone()
    return None if row is None else _expert_review_decision_from_row(row)


def list_expert_review_decisions_for_packet(
    connection: sqlite3.Connection,
    expert_review_packet_id: str,
) -> list[ExpertReviewDecisionRecord]:
    rows = connection.execute(
        """
        SELECT expert_review_decision_id, expert_review_packet_id, decision_type,
               decision_notes, override_event_id, decided_at, applied_at
        FROM expert_review_decisions
        WHERE expert_review_packet_id = ?
        ORDER BY decided_at ASC, expert_review_decision_id ASC
        """,
        (expert_review_packet_id,),
    ).fetchall()
    return [_expert_review_decision_from_row(row) for row in rows]


def get_override_event(
    connection: sqlite3.Connection,
    override_event_id: str,
) -> OverrideEventRecord | None:
    row = connection.execute(
        """
        SELECT override_event_id, object_type, object_id, component_stage,
               previous_value, new_value, override_reason, override_timestamp,
               override_by, lead_id, job_posting_id, contact_id
        FROM override_events
        WHERE override_event_id = ?
        """,
        (override_event_id,),
    ).fetchone()
    return None if row is None else _override_event_from_row(row)


def list_override_events_for_object(
    connection: sqlite3.Connection,
    *,
    object_type: str,
    object_id: str,
) -> list[OverrideEventRecord]:
    rows = connection.execute(
        """
        SELECT override_event_id, object_type, object_id, component_stage,
               previous_value, new_value, override_reason, override_timestamp,
               override_by, lead_id, job_posting_id, contact_id
        FROM override_events
        WHERE object_type = ?
          AND object_id = ?
        ORDER BY override_timestamp DESC, override_event_id DESC
        """,
        (
            object_type,
            object_id,
        ),
    ).fetchall()
    return [_override_event_from_row(row) for row in rows]


def record_override_event(
    connection: sqlite3.Connection,
    *,
    object_type: str,
    object_id: str,
    component_stage: str,
    previous_value: object,
    new_value: object,
    override_reason: str,
    override_by: str | None = None,
    lead_id: str | None = None,
    job_posting_id: str | None = None,
    contact_id: str | None = None,
    override_timestamp: str | None = None,
    override_event_id: str | None = None,
) -> OverrideEventRecord:
    if not object_type.strip():
        raise SupervisorStateError("object_type is required for override recording.")
    if not object_id.strip():
        raise SupervisorStateError("object_id is required for override recording.")
    if not component_stage.strip():
        raise SupervisorStateError("component_stage is required for override recording.")
    if not override_reason.strip():
        raise SupervisorStateError("override_reason is required for override recording.")

    current_timestamp = override_timestamp or now_utc_iso()
    override_event_id = override_event_id or new_canonical_id("override_events")
    with connection:
        connection.execute(
            """
            INSERT INTO override_events (
              override_event_id, object_type, object_id, component_stage,
              previous_value, new_value, override_reason, override_timestamp,
              override_by, lead_id, job_posting_id, contact_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                override_event_id,
                object_type,
                object_id,
                component_stage,
                _serialize_audit_value(previous_value),
                _serialize_audit_value(new_value),
                override_reason,
                current_timestamp,
                override_by,
                lead_id,
                job_posting_id,
                contact_id,
            ),
        )
    event = get_override_event(connection, override_event_id)
    if event is None:  # pragma: no cover - defensive invariant
        raise SupervisorStateError(
            f"Failed to load override_event {override_event_id} after creation."
        )
    return event


def generate_expert_review_packet(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    pipeline_run_id: str,
    *,
    created_at: str | None = None,
    recommended_expert_actions: list[str] | tuple[str, ...] | None = None,
    expert_review_packet_id: str | None = None,
) -> ExpertReviewPacketRecord:
    pipeline_run = _require_pipeline_run(connection, pipeline_run_id)
    if pipeline_run.run_status not in REVIEW_WORTHY_RUN_STATUSES:
        raise InvalidLifecycleTransition(
            f"pipeline_run {pipeline_run_id!r} is not at a review-worthy terminal outcome."
        )

    existing_packets = list_expert_review_packets_for_run(connection, pipeline_run_id)
    existing_pending = next(
        (
            packet
            for packet in existing_packets
            if packet.packet_status == REVIEW_PACKET_STATUS_PENDING
        ),
        None,
    )
    if existing_pending is not None:
        return existing_pending
    if existing_packets:
        return existing_packets[0]

    current_timestamp = created_at or now_utc_iso()
    packet_payload = _build_review_packet_payload(
        connection,
        pipeline_run,
        generated_at=current_timestamp,
        recommended_expert_actions=recommended_expert_actions,
    )
    json_path = paths.review_packet_json_path(pipeline_run.pipeline_run_id)
    markdown_path = paths.review_packet_markdown_path(pipeline_run.pipeline_run_id)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(packet_payload, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(
        _render_review_packet_markdown(packet_payload),
        encoding="utf-8",
    )

    if pipeline_run.lead_id or pipeline_run.job_posting_id:
        linkage = ArtifactLinkage(
            lead_id=pipeline_run.lead_id,
            job_posting_id=pipeline_run.job_posting_id,
        )
        register_artifact_record(
            connection,
            paths,
            artifact_type="expert_review_packet_json",
            artifact_path=json_path,
            producer_component=SUPERVISOR_COMPONENT,
            linkage=linkage,
            created_at=current_timestamp,
        )
        register_artifact_record(
            connection,
            paths,
            artifact_type="expert_review_packet_markdown",
            artifact_path=markdown_path,
            producer_component=SUPERVISOR_COMPONENT,
            linkage=linkage,
            created_at=current_timestamp,
        )

    expert_review_packet_id = expert_review_packet_id or new_canonical_id("expert_review_packets")
    packet_path = paths.relative_to_root(json_path).as_posix()
    summary_excerpt = _review_packet_summary_excerpt(packet_payload)
    with connection:
        connection.execute(
            """
            INSERT INTO expert_review_packets (
              expert_review_packet_id, pipeline_run_id, packet_status, packet_path,
              job_posting_id, reviewed_at, summary_excerpt, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                expert_review_packet_id,
                pipeline_run.pipeline_run_id,
                REVIEW_PACKET_STATUS_PENDING,
                packet_path,
                pipeline_run.job_posting_id,
                None,
                summary_excerpt,
                current_timestamp,
            ),
        )
    set_pipeline_run_review_packet_status(
        connection,
        pipeline_run.pipeline_run_id,
        REVIEW_PACKET_STATUS_PENDING,
        timestamp=current_timestamp,
    )
    packet = get_expert_review_packet(connection, expert_review_packet_id)
    if packet is None:  # pragma: no cover - defensive invariant
        raise SupervisorStateError(
            f"Failed to load expert_review_packet {expert_review_packet_id} after creation."
        )
    return packet


def finalize_review_worthy_pipeline_run(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    pipeline_run_id: str,
    *,
    final_status: str,
    current_stage: str | None = None,
    error_summary: str | None = None,
    run_summary: str | None = _UNSET,
    timestamp: str | None = None,
    recommended_expert_actions: list[str] | tuple[str, ...] | None = None,
) -> tuple[PipelineRunRecord, ExpertReviewPacketRecord]:
    current_timestamp = timestamp or now_utc_iso()
    if final_status == RUN_STATUS_COMPLETED:
        finalized_run = complete_pipeline_run(
            connection,
            pipeline_run_id,
            current_stage=current_stage or "completed",
            run_summary=run_summary,
            timestamp=current_timestamp,
        )
    elif final_status == RUN_STATUS_FAILED:
        finalized_run = fail_pipeline_run(
            connection,
            pipeline_run_id,
            current_stage=current_stage,
            error_summary=_require_text(error_summary, "error_summary"),
            run_summary=run_summary,
            timestamp=current_timestamp,
        )
    elif final_status == RUN_STATUS_ESCALATED:
        finalized_run = escalate_pipeline_run(
            connection,
            pipeline_run_id,
            current_stage=current_stage,
            error_summary=error_summary,
            run_summary=run_summary,
            timestamp=current_timestamp,
        )
    else:
        raise SupervisorStateError(
            f"Unsupported final_status={final_status!r} for review-worthy finalization."
        )

    packet = generate_expert_review_packet(
        connection,
        paths,
        finalized_run.pipeline_run_id,
        created_at=current_timestamp,
        recommended_expert_actions=recommended_expert_actions,
    )
    return _require_pipeline_run(connection, finalized_run.pipeline_run_id), packet


def record_expert_review_decision(
    connection: sqlite3.Connection,
    expert_review_packet_id: str,
    *,
    decision_type: str,
    decision_notes: str | None = None,
    override_event_id: str | None = None,
    decided_at: str | None = None,
    applied_at: str | None = None,
    expert_review_decision_id: str | None = None,
) -> ExpertReviewDecisionRecord:
    if not decision_type.strip():
        raise SupervisorStateError("decision_type is required for expert review decisions.")

    packet = _require_expert_review_packet(connection, expert_review_packet_id)
    if packet.packet_status != REVIEW_PACKET_STATUS_PENDING:
        raise InvalidLifecycleTransition(
            f"expert_review_packet {expert_review_packet_id!r} is not pending expert review."
        )
    if override_event_id is not None and get_override_event(connection, override_event_id) is None:
        raise SupervisorStateError(
            f"override_event {override_event_id!r} does not exist for decision linkage."
        )

    current_timestamp = decided_at or now_utc_iso()
    expert_review_decision_id = expert_review_decision_id or new_canonical_id(
        "expert_review_decisions"
    )
    with connection:
        connection.execute(
            """
            INSERT INTO expert_review_decisions (
              expert_review_decision_id, expert_review_packet_id, decision_type,
              decision_notes, override_event_id, decided_at, applied_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                expert_review_decision_id,
                expert_review_packet_id,
                decision_type,
                decision_notes,
                override_event_id,
                current_timestamp,
                applied_at,
            ),
        )
    _update_expert_review_packet_status(
        connection,
        expert_review_packet_id,
        packet_status=REVIEW_PACKET_STATUS_REVIEWED,
        reviewed_at=current_timestamp,
    )
    set_pipeline_run_review_packet_status(
        connection,
        packet.pipeline_run_id,
        REVIEW_PACKET_STATUS_REVIEWED,
        timestamp=current_timestamp,
    )
    decision = get_expert_review_decision(connection, expert_review_decision_id)
    if decision is None:  # pragma: no cover - defensive invariant
        raise SupervisorStateError(
            f"Failed to load expert_review_decision {expert_review_decision_id} after creation."
        )
    return decision


def record_expert_override_decision(
    connection: sqlite3.Connection,
    expert_review_packet_id: str,
    *,
    decision_type: str,
    object_type: str,
    object_id: str,
    component_stage: str,
    previous_value: object,
    new_value: object,
    override_reason: str,
    override_by: str | None = None,
    lead_id: str | None = None,
    job_posting_id: str | None = None,
    contact_id: str | None = None,
    decision_notes: str | None = None,
    decided_at: str | None = None,
    applied_at: str | None = None,
) -> tuple[ExpertReviewDecisionRecord, OverrideEventRecord]:
    current_timestamp = decided_at or now_utc_iso()
    override_event = record_override_event(
        connection,
        object_type=object_type,
        object_id=object_id,
        component_stage=component_stage,
        previous_value=previous_value,
        new_value=new_value,
        override_reason=override_reason,
        override_by=override_by,
        lead_id=lead_id,
        job_posting_id=job_posting_id,
        contact_id=contact_id,
        override_timestamp=current_timestamp,
    )
    decision = record_expert_review_decision(
        connection,
        expert_review_packet_id,
        decision_type=decision_type,
        decision_notes=decision_notes or override_reason,
        override_event_id=override_event.override_event_id,
        decided_at=current_timestamp,
        applied_at=applied_at or current_timestamp,
    )
    return decision, override_event


def run_supervisor_cycle(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    trigger_type: str,
    scheduler_name: str | None = None,
    sleep_wake_detection_method: str | None = None,
    sleep_wake_event_ref: str | None = None,
    started_at: str | None = None,
    lease_ttl_seconds: int = 300,
    action_dependencies: SupervisorActionDependencies | None = None,
) -> SupervisorCycleExecution:
    cycle_started_at = started_at or now_utc_iso()
    resolved_action_dependencies = action_dependencies or SupervisorActionDependencies()
    cycle = start_supervisor_cycle(
        connection,
        trigger_type=trigger_type,
        scheduler_name=scheduler_name,
        sleep_wake_detection_method=sleep_wake_detection_method,
        sleep_wake_event_ref=sleep_wake_event_ref,
        started_at=cycle_started_at,
    )
    lease_result = acquire_runtime_lease(
        connection,
        lease_name=SUPERVISOR_LEASE_NAME,
        lease_owner_id=cycle.supervisor_cycle_id,
        ttl_seconds=lease_ttl_seconds,
        now=cycle_started_at,
        lease_note=f"{trigger_type}:{scheduler_name or 'manual'}",
    )
    if lease_result.deferred:
        cycle = finish_supervisor_cycle(
            connection,
            cycle.supervisor_cycle_id,
            result=SUPERVISOR_CYCLE_RESULT_DEFERRED,
            completed_at=cycle_started_at,
            error_summary=(
                "supervisor lease is still held by "
                f"{lease_result.lease.lease_owner_id}"
            ),
        )
        return SupervisorCycleExecution(
            cycle=cycle,
            control_state=read_agent_control_state(connection, timestamp=cycle_started_at),
            lease_status=lease_result.status,
        )

    control_state = read_agent_control_state(connection, timestamp=cycle_started_at)
    selected_work: SupervisorWorkUnit | None = None
    action_id: str | None = None
    pipeline_run: PipelineRunRecord | None = None
    incident: AgentIncidentRecord | None = None
    review_packet: ExpertReviewPacketRecord | None = None
    maintenance_batch_id: str | None = None
    context_snapshot_path: str | None = None
    cycle_result = SUPERVISOR_CYCLE_RESULT_NO_WORK
    error_summary: str | None = None

    try:
        if not control_state.agent_enabled or control_state.agent_mode == AGENT_MODE_STOPPED:
            error_summary = "autonomous operation is disabled"
        elif control_state.agent_mode == AGENT_MODE_REPLANNING:
            cycle_result = SUPERVISOR_CYCLE_RESULT_REPLANNED
            error_summary = control_state.last_replan_reason or "supervisor is in replanning mode"
        elif control_state.agent_mode == AGENT_MODE_PAUSED:
            error_summary = control_state.pause_reason or "supervisor is paused"
        else:
            auto_pause = _detect_auto_pause_condition(connection, now=cycle_started_at)
            if auto_pause is not None:
                control_state = pause_agent(
                    connection,
                    reason=auto_pause.reason,
                    timestamp=cycle_started_at,
                )
                selected_work = SupervisorWorkUnit(
                    work_type=auto_pause.selected_work_type,
                    work_id=auto_pause.selected_work_id,
                    action_id=None,
                    summary=auto_pause.reason,
                    incident_id=(
                        auto_pause.incident.agent_incident_id
                        if auto_pause.incident is not None
                        else None
                    ),
                )
                incident = auto_pause.incident
                error_summary = auto_pause.reason
                cycle_result = SUPERVISOR_CYCLE_RESULT_AUTO_PAUSED
            else:
                selected_work = select_next_supervisor_work_unit(
                    connection,
                    current_time=cycle_started_at,
                    action_dependencies=resolved_action_dependencies,
                )
                if selected_work is None:
                    error_summary = "no bounded supervisor work unit is currently due"
                else:
                    action_id = selected_work.action_id
                    if action_id is None:
                        error_summary = _unsupported_work_summary(selected_work)
                        incident, pipeline_run = _record_progression_failure(
                            connection,
                            selected_work,
                            summary=error_summary,
                            incident_type="unsupported_supervisor_action",
                            severity=INCIDENT_SEVERITY_HIGH,
                            timestamp=cycle_started_at,
                        )
                        review_packet = _ensure_review_packet_for_terminal_run(
                            connection,
                            paths,
                            pipeline_run,
                            created_at=cycle_started_at,
                        )
                        cycle_result = SUPERVISOR_CYCLE_RESULT_FAILED
                    else:
                        catalog_entry = SUPERVISOR_ACTION_CATALOG[action_id]
                        validation_error = _validate_selected_work(
                            connection,
                            selected_work,
                            catalog_entry=catalog_entry,
                            current_time=cycle_started_at,
                            action_dependencies=resolved_action_dependencies,
                        )
                        if validation_error is not None:
                            error_summary = validation_error
                            incident, pipeline_run = _record_progression_failure(
                                connection,
                                selected_work,
                                summary=validation_error,
                                incident_type="supervisor_prerequisite_failed",
                                severity=INCIDENT_SEVERITY_HIGH,
                                timestamp=cycle_started_at,
                            )
                            review_packet = _ensure_review_packet_for_terminal_run(
                                connection,
                                paths,
                                pipeline_run,
                                created_at=cycle_started_at,
                            )
                            cycle_result = SUPERVISOR_CYCLE_RESULT_FAILED
                        else:
                            (
                                pipeline_run,
                                incident,
                                maintenance_batch_id,
                            ) = _execute_selected_work_unit(
                                connection,
                                paths,
                                selected_work,
                                catalog_entry=catalog_entry,
                                timestamp=cycle_started_at,
                                action_dependencies=resolved_action_dependencies,
                            )
                            execution_error = _validate_selected_work_result(
                                connection,
                                paths,
                                selected_work,
                                catalog_entry=catalog_entry,
                                pipeline_run=pipeline_run,
                                incident=incident,
                                maintenance_batch_id=maintenance_batch_id,
                            )
                            if execution_error is not None:
                                error_summary = execution_error
                                incident, pipeline_run = _record_progression_failure(
                                    connection,
                                    selected_work,
                                    summary=execution_error,
                                    incident_type="supervisor_action_execution_failed",
                                    severity=INCIDENT_SEVERITY_HIGH,
                                    timestamp=cycle_started_at,
                                )
                                review_packet = _ensure_review_packet_for_terminal_run(
                                    connection,
                                    paths,
                                    pipeline_run,
                                    created_at=cycle_started_at,
                                )
                                cycle_result = SUPERVISOR_CYCLE_RESULT_FAILED
                            else:
                                review_packet = _ensure_review_packet_for_terminal_run(
                                    connection,
                                    paths,
                                    pipeline_run,
                                    created_at=cycle_started_at,
                                )
                                cycle_result = SUPERVISOR_CYCLE_RESULT_SUCCESS

        if selected_work is not None:
            context_snapshot_path = _write_context_snapshot(
                paths,
                cycle.supervisor_cycle_id,
                {
                    "captured_at": cycle_started_at,
                    "trigger_type": trigger_type,
                    "scheduler_name": scheduler_name,
                    "control_state": dict(control_state.values),
                    "selected_work": {
                        "work_type": selected_work.work_type,
                        "work_id": selected_work.work_id,
                        "action_id": selected_work.action_id,
                        "summary": selected_work.summary,
                        "lead_id": selected_work.lead_id,
                        "job_posting_id": selected_work.job_posting_id,
                        "pipeline_run_id": selected_work.pipeline_run_id,
                        "current_stage": selected_work.current_stage,
                    },
                    "action_catalog_entry": (
                        _catalog_entry_snapshot(SUPERVISOR_ACTION_CATALOG[action_id])
                        if action_id is not None
                        else None
                    ),
                    "cycle_result": cycle_result,
                    "error_summary": error_summary,
                    "pipeline_run": (
                        {
                            "pipeline_run_id": pipeline_run.pipeline_run_id,
                            "run_status": pipeline_run.run_status,
                            "current_stage": pipeline_run.current_stage,
                            "job_posting_id": pipeline_run.job_posting_id,
                            "lead_id": pipeline_run.lead_id,
                            "review_packet_status": pipeline_run.review_packet_status,
                            "run_summary": pipeline_run.run_summary,
                        }
                        if pipeline_run is not None
                        else None
                    ),
                    "incident": (
                        {
                            "agent_incident_id": incident.agent_incident_id,
                            "incident_type": incident.incident_type,
                            "severity": incident.severity,
                            "status": incident.status,
                            "summary": incident.summary,
                            "pipeline_run_id": incident.pipeline_run_id,
                            "job_posting_id": incident.job_posting_id,
                            "escalation_reason": incident.escalation_reason,
                        }
                        if incident is not None
                        else None
                    ),
                    "review_packet": (
                        {
                            "expert_review_packet_id": review_packet.expert_review_packet_id,
                            "packet_status": review_packet.packet_status,
                            "packet_path": review_packet.packet_path,
                            "markdown_path": review_packet.markdown_path,
                            "created_at": review_packet.created_at,
                        }
                        if review_packet is not None
                        else None
                    ),
                    "maintenance_batch": (
                        _maintenance_batch_snapshot(connection, maintenance_batch_id)
                        if maintenance_batch_id is not None
                        else None
                    ),
                },
            )
            cycle = assign_supervisor_cycle_work_unit(
                connection,
                cycle.supervisor_cycle_id,
                selected_work_type=selected_work.work_type,
                selected_work_id=selected_work.work_id,
                pipeline_run_id=(
                    pipeline_run.pipeline_run_id
                    if pipeline_run is not None
                    else selected_work.pipeline_run_id
                ),
                context_snapshot_path=context_snapshot_path,
            )

        cycle = finish_supervisor_cycle(
            connection,
            cycle.supervisor_cycle_id,
            result=cycle_result,
            completed_at=cycle_started_at,
            error_summary=error_summary,
        )
        return SupervisorCycleExecution(
            cycle=cycle,
            control_state=control_state,
            lease_status=lease_result.status,
            selected_work=selected_work,
            action_id=action_id,
            pipeline_run=pipeline_run,
            incident=incident,
            review_packet=review_packet,
            maintenance_batch_id=maintenance_batch_id,
            context_snapshot_path=context_snapshot_path,
        )
    finally:
        release_runtime_lease(
            connection,
            lease_name=SUPERVISOR_LEASE_NAME,
            lease_owner_id=cycle.supervisor_cycle_id,
        )


def select_next_supervisor_work_unit(
    connection: sqlite3.Connection,
    *,
    current_time: str,
    action_dependencies: SupervisorActionDependencies,
) -> SupervisorWorkUnit | None:
    control_state = read_agent_control_state(connection, timestamp=current_time)
    incident_work = _select_active_incident_work_unit(connection)
    if incident_work is not None:
        return incident_work

    gmail_alert_work = _select_gmail_alert_collection_work_unit(
        current_time=current_time,
        gmail_alert_collector=action_dependencies.gmail_alert_collector,
        gmail_history_checkpoint=control_state.gmail_poll_last_history_id,
    )
    if gmail_alert_work is not None:
        return gmail_alert_work

    stale_gmail_repair_work = _select_stale_gmail_lead_repair_work_unit(connection)
    if stale_gmail_repair_work is not None:
        return stale_gmail_repair_work

    pipeline_run_work = _select_open_pipeline_run_work_unit(connection)
    if pipeline_run_work is not None:
        return pipeline_run_work

    posting_work = _select_new_posting_work_unit(connection)
    if posting_work is not None:
        return posting_work

    general_learning_priority_work = _select_general_learning_priority_work_unit(
        connection
    )
    if general_learning_priority_work is not None:
        return general_learning_priority_work

    general_learning_discovery_work = _select_general_learning_discovery_work_unit(
        connection
    )
    if general_learning_discovery_work is not None:
        return general_learning_discovery_work

    return _select_maintenance_work_unit(
        connection,
        current_time=current_time,
        local_timezone=action_dependencies.local_timezone,
        maintenance_dependencies=action_dependencies.maintenance_dependencies,
    )


def _detect_auto_pause_condition(
    connection: sqlite3.Connection,
    *,
    now: str,
) -> AutoPauseDecision | None:
    unresolved_incidents = list_unresolved_agent_incidents(connection)
    for incident in unresolved_incidents:
        if (
            incident.severity == INCIDENT_SEVERITY_CRITICAL
            and incident.incident_type in AUTO_PAUSE_CRITICAL_INCIDENT_TYPES
        ):
            return AutoPauseDecision(
                reason=(
                    "auto_pause: critical "
                    f"{incident.incident_type} incident requires expert review"
                ),
                selected_work_type=WORK_TYPE_AGENT_INCIDENT,
                selected_work_id=incident.agent_incident_id,
                incident=incident,
            )

    cutoff = _timestamp_plus_seconds(now, -(45 * 60))
    cluster_counts: dict[str, int] = {}
    for incident in unresolved_incidents:
        if _parse_utc_iso(incident.created_at) < _parse_utc_iso(cutoff):
            continue
        cluster_key = _incident_cluster_key(incident)
        cluster_counts[cluster_key] = cluster_counts.get(cluster_key, 0) + 1
        if cluster_counts[cluster_key] >= 3:
            return AutoPauseDecision(
                reason=(
                    "auto_pause: repeated unresolved incident cluster "
                    f"{cluster_key} reached 3 occurrences within 45 minutes"
                ),
                selected_work_type=WORK_TYPE_INCIDENT_CLUSTER,
                selected_work_id=cluster_key,
            )
    return None


def _select_gmail_alert_collection_work_unit(
    *,
    current_time: str,
    gmail_alert_collector: object | None,
    gmail_history_checkpoint: str | None,
) -> SupervisorWorkUnit | None:
    if gmail_alert_collector is None:
        return None
    prepare_batch = getattr(gmail_alert_collector, "prepare_batch", None)
    if not callable(prepare_batch):
        return None
    try:
        prepared_batch = prepare_batch(
            current_time=current_time,
            mailbox_history_checkpoint=gmail_history_checkpoint,
        )
    except Exception:
        return None
    if prepared_batch is None:
        return None
    message_count = len(prepared_batch.messages)
    if message_count == 0 and prepared_batch.mailbox_history_id_after:
        return SupervisorWorkUnit(
            work_type=WORK_TYPE_GMAIL_ALERT_BATCH,
            work_id=prepared_batch.ingestion_run_id,
            action_id=ACTION_POLL_GMAIL_LINKEDIN_ALERTS,
            summary="Seed the Gmail mailbox history checkpoint for future incremental lead polling.",
        )
    return SupervisorWorkUnit(
        work_type=WORK_TYPE_GMAIL_ALERT_BATCH,
        work_id=prepared_batch.ingestion_run_id,
        action_id=ACTION_POLL_GMAIL_LINKEDIN_ALERTS,
        summary=(
            "Collect a bounded Gmail alert batch of "
            f"{message_count} LinkedIn job-alert message"
            f"{'' if message_count == 1 else 's'} into canonical lead intake."
        ),
    )


def _select_stale_gmail_lead_repair_work_unit(
    connection: sqlite3.Connection,
) -> SupervisorWorkUnit | None:
    row = connection.execute(
        """
        SELECT lead_id, company_name, role_title
        FROM linkedin_leads
        WHERE source_mode = 'gmail_job_alert'
          AND lead_status = 'blocked_no_jd'
          AND (source_url IS NULL OR TRIM(source_url) = '')
        ORDER BY created_at ASC, lead_id ASC
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        return None
    return SupervisorWorkUnit(
        work_type=WORK_TYPE_GMAIL_LEAD_REPAIR,
        work_id=row["lead_id"],
        action_id=ACTION_REPAIR_STALE_GMAIL_LEAD,
        lead_id=row["lead_id"],
        summary=(
            "Repair stale Gmail lead artifacts for "
            f"{row['company_name'] or 'unknown company'} / {row['role_title'] or 'unknown role'} "
            "so JD recovery can retry with the current parser."
        ),
    )


def _select_active_incident_work_unit(
    connection: sqlite3.Connection,
) -> SupervisorWorkUnit | None:
    rows = connection.execute(
        """
        SELECT ai.agent_incident_id, ai.incident_type, ai.severity, ai.status, ai.summary,
               ai.pipeline_run_id, ai.lead_id, ai.job_posting_id, ai.contact_id,
               ai.outreach_message_id, ai.resolved_at, ai.escalation_reason,
               ai.repair_attempt_summary, ai.created_at, ai.updated_at, pr.current_stage
        FROM agent_incidents ai
        LEFT JOIN pipeline_runs pr
          ON pr.pipeline_run_id = ai.pipeline_run_id
        WHERE ai.status IN (?, ?)
        ORDER BY
          CASE ai.severity
            WHEN 'critical' THEN 0
            WHEN 'high' THEN 1
            WHEN 'medium' THEN 2
            ELSE 3
          END,
          ai.created_at ASC
        LIMIT 1
        """,
        (
            INCIDENT_STATUS_OPEN,
            INCIDENT_STATUS_IN_REPAIR,
        ),
    ).fetchall()
    if not rows:
        return None
    incident = _agent_incident_from_row(rows[0])
    return SupervisorWorkUnit(
        work_type=WORK_TYPE_AGENT_INCIDENT,
        work_id=incident.agent_incident_id,
        action_id=ACTION_ESCALATE_OPEN_INCIDENT,
        summary=f"Escalate unresolved {incident.severity} incident for expert visibility.",
        lead_id=incident.lead_id,
        job_posting_id=incident.job_posting_id,
        pipeline_run_id=incident.pipeline_run_id,
        incident_id=incident.agent_incident_id,
        current_stage=incident.current_stage,
    )


def _select_open_pipeline_run_work_unit(
    connection: sqlite3.Connection,
) -> SupervisorWorkUnit | None:
    rows = connection.execute(
        """
        SELECT pipeline_run_id, run_scope_type, run_status, current_stage, lead_id,
               job_posting_id, completed_at, last_error_summary, review_packet_status,
               run_summary, started_at, created_at, updated_at
        FROM pipeline_runs
        WHERE run_status IN (?, ?)
        ORDER BY updated_at ASC, started_at ASC
        """,
        (
            RUN_STATUS_IN_PROGRESS,
            RUN_STATUS_PAUSED,
        ),
    ).fetchall()
    for row in rows:
        pipeline_run = _pipeline_run_from_row(row)
        if pipeline_run.current_stage == "delivery_feedback":
            job_posting_id = _optional_text(pipeline_run.job_posting_id)
            if job_posting_id:
                sent_message_ids = _list_posting_sent_outreach_message_ids(
                    connection,
                    job_posting_id=job_posting_id,
                )
                if sent_message_ids:
                    pending_feedback_message_ids = (
                        _list_posting_sent_outreach_message_ids_without_terminal_feedback(
                            connection,
                            job_posting_id=job_posting_id,
                        )
                    )
                    if pending_feedback_message_ids:
                        continue

        action_id = ROLE_TARGETED_PIPELINE_STAGE_ACTIONS.get(pipeline_run.current_stage)
        return SupervisorWorkUnit(
            work_type=WORK_TYPE_PIPELINE_RUN,
            work_id=pipeline_run.pipeline_run_id,
            action_id=action_id,
            summary=(
                "Resume the existing durable pipeline run without creating duplicate work."
            ),
            lead_id=pipeline_run.lead_id,
            job_posting_id=pipeline_run.job_posting_id,
            pipeline_run_id=pipeline_run.pipeline_run_id,
            current_stage=pipeline_run.current_stage,
        )
    return None


def _select_new_posting_work_unit(
    connection: sqlite3.Connection,
) -> SupervisorWorkUnit | None:
    placeholders = ", ".join("?" for _ in ELIGIBLE_POSTING_STATUSES_FOR_NEW_RUN)
    rows = connection.execute(
        f"""
        SELECT jp.job_posting_id, jp.lead_id, jp.posting_status, jp.company_name, jp.role_title
        FROM job_postings jp
        WHERE jp.posting_status IN ({placeholders})
          AND NOT EXISTS (
            SELECT 1
            FROM pipeline_runs pr
            WHERE pr.job_posting_id = jp.job_posting_id
              AND pr.run_status IN (?, ?)
          )
        ORDER BY jp.created_at ASC
        LIMIT 1
        """,
        (
            *sorted(ELIGIBLE_POSTING_STATUSES_FOR_NEW_RUN),
            RUN_STATUS_IN_PROGRESS,
            RUN_STATUS_PAUSED,
        ),
    ).fetchall()
    if not rows:
        return None
    row = rows[0]
    return SupervisorWorkUnit(
        work_type=WORK_TYPE_JOB_POSTING,
        work_id=row[0],
        action_id=ACTION_BOOTSTRAP_ROLE_TARGETED_RUN,
        summary=(
            "Create the first durable role-targeted pipeline run for an eligible posting."
        ),
        lead_id=_optional_text(row[1]),
        job_posting_id=row[0],
    )


def _select_general_learning_priority_work_unit(
    connection: sqlite3.Connection,
) -> SupervisorWorkUnit | None:
    send_ready_row = connection.execute(
        """
        SELECT c.contact_id, c.display_name, c.company_name,
               (
                 SELECT om.message_status
                 FROM outreach_messages om
                 WHERE om.contact_id = c.contact_id
                   AND om.outreach_mode = 'general_learning'
                 ORDER BY om.created_at DESC, om.outreach_message_id DESC
                 LIMIT 1
               ) AS latest_general_learning_message_status
        FROM contacts c
        WHERE c.current_working_email IS NOT NULL
          AND TRIM(c.current_working_email) <> ''
          AND c.contact_status NOT IN ('outreach_in_progress', 'sent', 'exhausted')
          AND NOT EXISTS (
            SELECT 1
            FROM job_posting_contacts jpc
            WHERE jpc.contact_id = c.contact_id
          )
          AND NOT EXISTS (
            SELECT 1
            FROM outreach_messages sent_om
            WHERE sent_om.contact_id = c.contact_id
              AND (
                sent_om.sent_at IS NOT NULL
                OR sent_om.message_status = 'sent'
              )
          )
          AND COALESCE((
                SELECT om.message_status
                FROM outreach_messages om
                WHERE om.contact_id = c.contact_id
                  AND om.outreach_mode = 'general_learning'
                ORDER BY om.created_at DESC, om.outreach_message_id DESC
                LIMIT 1
              ), '') NOT IN ('blocked', 'failed', 'sent')
        ORDER BY
          CASE
            WHEN COALESCE((
              SELECT om.message_status
              FROM outreach_messages om
              WHERE om.contact_id = c.contact_id
                AND om.outreach_mode = 'general_learning'
              ORDER BY om.created_at DESC, om.outreach_message_id DESC
              LIMIT 1
            ), '') = 'generated' THEN 0
            ELSE 1
          END,
          c.created_at ASC,
          c.contact_id ASC
        LIMIT 1
        """
    ).fetchone()
    if send_ready_row is not None:
        display_name = _optional_text(send_ready_row[1]) or send_ready_row[0]
        company_name = _optional_text(send_ready_row[2]) or "unknown-company"
        latest_status = _optional_text(send_ready_row[3])
        summary = (
            "Resume a previously drafted contact-rooted general-learning send."
            if latest_status == "generated"
            else (
                "Create and send one bounded contact-rooted general-learning outreach "
                f"message for {display_name} at {company_name}."
            )
        )
        return SupervisorWorkUnit(
            work_type=WORK_TYPE_CONTACT,
            work_id=send_ready_row[0],
            action_id=ACTION_RUN_GENERAL_LEARNING_OUTREACH,
            summary=summary,
        )

    return None


def _select_maintenance_work_unit(
    connection: sqlite3.Connection,
    *,
    current_time: str,
    local_timezone: object | str | None,
    maintenance_dependencies: MaintenanceDependencies | None,
) -> SupervisorWorkUnit | None:
    if maintenance_dependencies is None:
        return None
    if not is_daily_maintenance_due(
        connection,
        current_time=current_time,
        local_timezone=local_timezone,
    ):
        return None
    local_day = maintenance_local_day(
        current_time,
        local_timezone=local_timezone,
    )
    return SupervisorWorkUnit(
        work_type=WORK_TYPE_MAINTENANCE_CYCLE,
        work_id=local_day,
        action_id=ACTION_RUN_DAILY_MAINTENANCE,
        summary=(
            "Run the bounded daily maintenance cycle before starting new autonomous work "
            f"for local day {local_day}."
        ),
    )


def _select_general_learning_discovery_work_unit(
    connection: sqlite3.Connection,
) -> SupervisorWorkUnit | None:
    discovery_row = connection.execute(
        """
        SELECT c.contact_id, c.display_name, c.company_name
        FROM contacts c
        WHERE (
                c.current_working_email IS NULL
                OR TRIM(c.current_working_email) = ''
              )
          AND c.contact_status NOT IN ('outreach_in_progress', 'sent', 'exhausted')
          AND NOT EXISTS (
            SELECT 1
            FROM job_posting_contacts jpc
            WHERE jpc.contact_id = c.contact_id
          )
          AND NOT EXISTS (
            SELECT 1
            FROM outreach_messages sent_om
            WHERE sent_om.contact_id = c.contact_id
              AND (
                sent_om.sent_at IS NOT NULL
                OR sent_om.message_status = 'sent'
              )
          )
          AND COALESCE((
                SELECT om.message_status
                FROM outreach_messages om
                WHERE om.contact_id = c.contact_id
                  AND om.outreach_mode = 'general_learning'
                ORDER BY om.created_at DESC, om.outreach_message_id DESC
                LIMIT 1
              ), '') = ''
        ORDER BY c.created_at ASC, c.contact_id ASC
        LIMIT 1
        """
    ).fetchone()
    if discovery_row is None:
        return None
    display_name = _optional_text(discovery_row[1]) or discovery_row[0]
    company_name = _optional_text(discovery_row[2]) or "unknown-company"
    return SupervisorWorkUnit(
        work_type=WORK_TYPE_CONTACT,
        work_id=discovery_row[0],
        action_id=ACTION_RUN_GENERAL_LEARNING_EMAIL_DISCOVERY,
        summary=(
            "Run one bounded contact-rooted general-learning email-discovery step "
            f"for {display_name} at {company_name}."
        ),
    )


def _validate_selected_work(
    connection: sqlite3.Connection,
    selected_work: SupervisorWorkUnit,
    *,
    catalog_entry: SupervisorActionCatalogEntry,
    current_time: str,
    action_dependencies: SupervisorActionDependencies,
) -> str | None:
    if catalog_entry.work_type != selected_work.work_type:
        return (
            f"Selected work type {selected_work.work_type!r} does not match "
            f"catalog action {catalog_entry.action_id!r}."
        )

    if catalog_entry.action_id == ACTION_POLL_GMAIL_LINKEDIN_ALERTS:
        if selected_work.work_type != WORK_TYPE_GMAIL_ALERT_BATCH:
            return (
                "Gmail alert polling selected a mismatched work type "
                f"{selected_work.work_type!r}."
            )
        collector = action_dependencies.gmail_alert_collector
        if collector is None:
            return "Autonomous Gmail polling is not enabled for the current runtime."
        peek_prepared_batch = getattr(collector, "peek_prepared_batch", None)
        if not callable(peek_prepared_batch):
            return "Configured Gmail alert collector does not expose peek_prepared_batch()."
        prepared_batch = peek_prepared_batch(selected_work.work_id)
        if prepared_batch is None:
            return (
                "Selected Gmail alert batch is no longer prepared for ingestion_run_id "
                f"{selected_work.work_id!r}."
            )
        if not prepared_batch.messages and not prepared_batch.mailbox_history_id_after:
            return (
                "Prepared Gmail alert batch is empty for ingestion_run_id "
                f"{selected_work.work_id!r}."
            )
        return None

    if catalog_entry.action_id == ACTION_REPAIR_STALE_GMAIL_LEAD:
        if selected_work.work_type != WORK_TYPE_GMAIL_LEAD_REPAIR:
            return (
                "Stale Gmail lead repair selected a mismatched work type "
                f"{selected_work.work_type!r}."
            )
        lead_row = connection.execute(
            """
            SELECT lead_status, source_mode, source_url
            FROM linkedin_leads
            WHERE lead_id = ?
            """,
            (selected_work.work_id,),
        ).fetchone()
        if lead_row is None:
            return f"linkedin_lead {selected_work.work_id!r} no longer exists."
        if lead_row["source_mode"] != "gmail_job_alert":
            return (
                f"linkedin_lead {selected_work.work_id!r} is not a Gmail lead; "
                f"found source_mode={lead_row['source_mode']!r}."
            )
        if lead_row["lead_status"] != "blocked_no_jd":
            return (
                f"linkedin_lead {selected_work.work_id!r} is no longer blocked_no_jd; "
                f"found {lead_row['lead_status']!r}."
            )
        if _optional_text(lead_row["source_url"]):
            return (
                f"linkedin_lead {selected_work.work_id!r} already has a source_url and "
                "does not match the stale Gmail parser backlog."
            )
        return None

    if catalog_entry.action_id == ACTION_BOOTSTRAP_ROLE_TARGETED_RUN:
        posting_row = connection.execute(
            """
            SELECT lead_id, posting_status
            FROM job_postings
            WHERE job_posting_id = ?
            """,
            (selected_work.work_id,),
        ).fetchone()
        if posting_row is None:
            return f"job_posting {selected_work.work_id!r} no longer exists."
        if posting_row[1] not in ELIGIBLE_POSTING_STATUSES_FOR_NEW_RUN:
            return (
                f"job_posting {selected_work.work_id!r} is not eligible for run bootstrap "
                f"from posting_status={posting_row[1]!r}."
            )
        existing_run = get_open_pipeline_run_for_posting(connection, selected_work.work_id)
        if existing_run is not None:
            return (
                f"job_posting {selected_work.work_id!r} already has non-terminal "
                f"pipeline_run {existing_run.pipeline_run_id!r}."
            )
        if not _optional_text(posting_row[0]):
            return f"job_posting {selected_work.work_id!r} is missing lead linkage."
        return None

    if catalog_entry.action_id == ACTION_CHECKPOINT_PIPELINE_RUN:
        pipeline_run = get_pipeline_run(connection, selected_work.work_id)
        if pipeline_run is None:
            return f"pipeline_run {selected_work.work_id!r} no longer exists."
        if pipeline_run.run_status not in {RUN_STATUS_IN_PROGRESS, RUN_STATUS_PAUSED}:
            return (
                f"pipeline_run {selected_work.work_id!r} is not non-terminal; "
                f"found {pipeline_run.run_status!r}."
            )
        if pipeline_run.current_stage != "lead_handoff":
            return (
                f"pipeline_run {selected_work.work_id!r} is at unsupported checkpoint stage "
                f"{pipeline_run.current_stage!r}."
            )
        if not pipeline_run.job_posting_id:
            return f"pipeline_run {selected_work.work_id!r} is missing job_posting_id."
        return None

    if catalog_entry.action_id == ACTION_RUN_ROLE_TARGETED_RESUME_TAILORING:
        pipeline_run = get_pipeline_run(connection, selected_work.work_id)
        if pipeline_run is None:
            return f"pipeline_run {selected_work.work_id!r} no longer exists."
        if pipeline_run.run_status not in {RUN_STATUS_IN_PROGRESS, RUN_STATUS_PAUSED}:
            return (
                f"pipeline_run {selected_work.work_id!r} is not non-terminal; "
                f"found {pipeline_run.run_status!r}."
            )
        if pipeline_run.current_stage != "resume_tailoring":
            return (
                f"pipeline_run {selected_work.work_id!r} is at unsupported resume-tailoring "
                f"stage {pipeline_run.current_stage!r}."
            )
        if not pipeline_run.job_posting_id:
            return f"pipeline_run {selected_work.work_id!r} is missing job_posting_id."
        posting_row = connection.execute(
            """
            SELECT posting_status, jd_artifact_path
            FROM job_postings
            WHERE job_posting_id = ?
            """,
            (pipeline_run.job_posting_id,),
        ).fetchone()
        if posting_row is None:
            return f"job_posting {pipeline_run.job_posting_id!r} no longer exists."
        if not _optional_text(posting_row["jd_artifact_path"]):
            return (
                f"job_posting {pipeline_run.job_posting_id!r} is missing jd_artifact_path "
                "for autonomous resume tailoring."
            )
        return None

    if catalog_entry.action_id == ACTION_PERFORM_MANDATORY_AGENT_REVIEW:
        pipeline_run = get_pipeline_run(connection, selected_work.work_id)
        if pipeline_run is None:
            return f"pipeline_run {selected_work.work_id!r} no longer exists."
        if pipeline_run.run_status not in {RUN_STATUS_IN_PROGRESS, RUN_STATUS_PAUSED}:
            return (
                f"pipeline_run {selected_work.work_id!r} is not non-terminal; "
                f"found {pipeline_run.run_status!r}."
            )
        if pipeline_run.current_stage != "agent_review":
            return (
                f"pipeline_run {selected_work.work_id!r} is at unsupported review stage "
                f"{pipeline_run.current_stage!r}."
            )
        job_posting_id = _optional_text(pipeline_run.job_posting_id)
        if job_posting_id is None:
            return f"pipeline_run {selected_work.work_id!r} is missing job_posting_id."
        posting_row = connection.execute(
            """
            SELECT posting_status
            FROM job_postings
            WHERE job_posting_id = ?
            """,
            (job_posting_id,),
        ).fetchone()
        if posting_row is None:
            return f"job_posting {job_posting_id!r} no longer exists."
        if posting_row[0] != "resume_review_pending":
            return (
                f"job_posting {job_posting_id!r} is not at the mandatory review boundary; "
                f"found posting_status={posting_row[0]!r}."
            )
        latest_run = connection.execute(
            """
            SELECT tailoring_status, resume_review_status
            FROM resume_tailoring_runs
            WHERE job_posting_id = ?
            ORDER BY COALESCE(completed_at, updated_at, created_at, started_at) DESC,
                     resume_tailoring_run_id DESC
            LIMIT 1
            """,
            (job_posting_id,),
        ).fetchone()
        if latest_run is None:
            return (
                f"job_posting {job_posting_id!r} has no resume_tailoring_run to review."
            )
        if latest_run[0] != "tailored" or latest_run[1] != "resume_review_pending":
            return (
                f"job_posting {job_posting_id!r} is missing a tailored pending-review run; "
                f"found tailoring_status={latest_run[0]!r}, "
                f"resume_review_status={latest_run[1]!r}."
            )
        return None

    if catalog_entry.action_id == ACTION_RUN_ROLE_TARGETED_PEOPLE_SEARCH:
        pipeline_run = get_pipeline_run(connection, selected_work.work_id)
        if pipeline_run is None:
            return f"pipeline_run {selected_work.work_id!r} no longer exists."
        if pipeline_run.run_status not in {RUN_STATUS_IN_PROGRESS, RUN_STATUS_PAUSED}:
            return (
                f"pipeline_run {selected_work.work_id!r} is not non-terminal; "
                f"found {pipeline_run.run_status!r}."
            )
        if pipeline_run.current_stage != "people_search":
            return (
                f"pipeline_run {selected_work.work_id!r} is at unsupported people-search "
                f"stage {pipeline_run.current_stage!r}."
            )
        job_posting_id = _optional_text(pipeline_run.job_posting_id)
        if job_posting_id is None:
            return f"pipeline_run {selected_work.work_id!r} is missing job_posting_id."
        posting_row = connection.execute(
            """
            SELECT posting_status
            FROM job_postings
            WHERE job_posting_id = ?
            """,
            (job_posting_id,),
        ).fetchone()
        if posting_row is None:
            return f"job_posting {job_posting_id!r} no longer exists."
        if posting_row[0] == "ready_for_outreach":
            return None
        if posting_row[0] != "requires_contacts":
            return (
                f"job_posting {job_posting_id!r} is not at the people-search boundary; "
                f"found posting_status={posting_row[0]!r}."
            )
        latest_run = connection.execute(
            """
            SELECT resume_review_status
            FROM resume_tailoring_runs
            WHERE job_posting_id = ?
            ORDER BY COALESCE(completed_at, updated_at, created_at, started_at) DESC,
                     resume_tailoring_run_id DESC
            LIMIT 1
            """,
            (job_posting_id,),
        ).fetchone()
        if latest_run is None or latest_run[0] != "approved":
            return (
                f"job_posting {job_posting_id!r} is not backed by an approved tailoring "
                "review for people search."
            )
        return None

    if catalog_entry.action_id == ACTION_RUN_ROLE_TARGETED_EMAIL_DISCOVERY:
        from .outreach import evaluate_role_targeted_send_set

        pipeline_run = get_pipeline_run(connection, selected_work.work_id)
        if pipeline_run is None:
            return f"pipeline_run {selected_work.work_id!r} no longer exists."
        if pipeline_run.run_status not in {RUN_STATUS_IN_PROGRESS, RUN_STATUS_PAUSED}:
            return (
                f"pipeline_run {selected_work.work_id!r} is not non-terminal; "
                f"found {pipeline_run.run_status!r}."
            )
        if pipeline_run.current_stage != "email_discovery":
            return (
                f"pipeline_run {selected_work.work_id!r} is at unsupported email-discovery "
                f"stage {pipeline_run.current_stage!r}."
            )
        job_posting_id = _optional_text(pipeline_run.job_posting_id)
        if job_posting_id is None:
            return f"pipeline_run {selected_work.work_id!r} is missing job_posting_id."
        posting_row = connection.execute(
            """
            SELECT posting_status
            FROM job_postings
            WHERE job_posting_id = ?
            """,
            (job_posting_id,),
        ).fetchone()
        if posting_row is None:
            return f"job_posting {job_posting_id!r} no longer exists."
        if posting_row[0] not in {"requires_contacts", "ready_for_outreach"}:
            return (
                f"job_posting {job_posting_id!r} is not at the email-discovery boundary; "
                f"found posting_status={posting_row[0]!r}."
            )
        latest_run = connection.execute(
            """
            SELECT resume_review_status
            FROM resume_tailoring_runs
            WHERE job_posting_id = ?
            ORDER BY COALESCE(completed_at, updated_at, created_at, started_at) DESC,
                     resume_tailoring_run_id DESC
            LIMIT 1
            """,
            (job_posting_id,),
        ).fetchone()
        if latest_run is None or latest_run[0] != "approved":
            return (
                f"job_posting {job_posting_id!r} is not backed by an approved tailoring "
                "review for email discovery."
            )
        send_set_plan = evaluate_role_targeted_send_set(
            connection,
            job_posting_id=job_posting_id,
            current_time=now_utc_iso(),
        )
        if not send_set_plan.selected_contacts:
            return (
                f"job_posting {job_posting_id!r} has no current send-set contacts available "
                "for bounded email discovery."
            )
        return None

    if catalog_entry.action_id == ACTION_RUN_ROLE_TARGETED_SENDING:
        pipeline_run = get_pipeline_run(connection, selected_work.work_id)
        if pipeline_run is None:
            return f"pipeline_run {selected_work.work_id!r} no longer exists."
        if pipeline_run.run_status not in {RUN_STATUS_IN_PROGRESS, RUN_STATUS_PAUSED}:
            return (
                f"pipeline_run {selected_work.work_id!r} is not non-terminal; "
                f"found {pipeline_run.run_status!r}."
            )
        if pipeline_run.current_stage != "sending":
            return (
                f"pipeline_run {selected_work.work_id!r} is at unsupported sending "
                f"stage {pipeline_run.current_stage!r}."
            )
        job_posting_id = _optional_text(pipeline_run.job_posting_id)
        if job_posting_id is None:
            return f"pipeline_run {selected_work.work_id!r} is missing job_posting_id."
        posting_row = connection.execute(
            """
            SELECT posting_status
            FROM job_postings
            WHERE job_posting_id = ?
            """,
            (job_posting_id,),
        ).fetchone()
        if posting_row is None:
            return f"job_posting {job_posting_id!r} no longer exists."
        posting_status = _require_text(
            _optional_text(posting_row[0]),
            "posting_status",
        )
        if posting_status not in {
            "ready_for_outreach",
            "outreach_in_progress",
            "completed",
        }:
            return (
                f"job_posting {job_posting_id!r} is not at the sending boundary; "
                f"found posting_status={posting_status!r}."
            )
        latest_run = connection.execute(
            """
            SELECT resume_review_status
            FROM resume_tailoring_runs
            WHERE job_posting_id = ?
            ORDER BY COALESCE(completed_at, updated_at, created_at, started_at) DESC,
                     resume_tailoring_run_id DESC
            LIMIT 1
            """,
            (job_posting_id,),
        ).fetchone()
        if latest_run is None or latest_run[0] != "approved":
            return (
                f"job_posting {job_posting_id!r} is not backed by an approved tailoring "
                "review for sending."
            )
        if (
            posting_status != "completed"
            and action_dependencies.outreach_sender is None
        ):
            return (
                "Supervisor sending requires an injected outreach sender before any "
                f"automatic send is attempted for job_posting {job_posting_id!r}."
            )
        return None

    if catalog_entry.action_id == ACTION_RUN_ROLE_TARGETED_DELIVERY_FEEDBACK:
        pipeline_run = get_pipeline_run(connection, selected_work.work_id)
        if pipeline_run is None:
            return f"pipeline_run {selected_work.work_id!r} no longer exists."
        if pipeline_run.run_status not in {RUN_STATUS_IN_PROGRESS, RUN_STATUS_PAUSED}:
            return (
                f"pipeline_run {selected_work.work_id!r} is not non-terminal; "
                f"found {pipeline_run.run_status!r}."
            )
        if pipeline_run.current_stage != "delivery_feedback":
            return (
                f"pipeline_run {selected_work.work_id!r} is at unsupported delivery-feedback "
                f"stage {pipeline_run.current_stage!r}."
            )
        job_posting_id = _optional_text(pipeline_run.job_posting_id)
        if job_posting_id is None:
            return f"pipeline_run {selected_work.work_id!r} is missing job_posting_id."
        posting_status = _load_posting_status(
            connection,
            job_posting_id=job_posting_id,
        )
        if posting_status != "completed":
            return (
                f"job_posting {job_posting_id!r} is not at the delivery-feedback boundary; "
                f"found posting_status={posting_status!r}."
            )
        latest_run = connection.execute(
            """
            SELECT resume_review_status
            FROM resume_tailoring_runs
            WHERE job_posting_id = ?
            ORDER BY COALESCE(completed_at, updated_at, created_at, started_at) DESC,
                     resume_tailoring_run_id DESC
            LIMIT 1
            """,
            (job_posting_id,),
        ).fetchone()
        if latest_run is None or latest_run[0] != "approved":
            return (
                f"job_posting {job_posting_id!r} is not backed by an approved tailoring "
                "review for delivery feedback."
            )
        sent_message_ids = _list_posting_sent_outreach_message_ids(
            connection,
            job_posting_id=job_posting_id,
        )
        if not sent_message_ids:
            return (
                f"job_posting {job_posting_id!r} reached delivery_feedback without any "
                "sent outreach messages."
            )
        return None

    if catalog_entry.action_id == ACTION_RUN_GENERAL_LEARNING_EMAIL_DISCOVERY:
        row = connection.execute(
            """
            SELECT c.contact_id, c.current_working_email, c.contact_status,
                   (
                     SELECT COUNT(*)
                     FROM job_posting_contacts jpc
                     WHERE jpc.contact_id = c.contact_id
                   ) AS posting_link_count,
                   (
                     SELECT COUNT(*)
                     FROM outreach_messages om
                     WHERE om.contact_id = c.contact_id
                       AND (
                         om.sent_at IS NOT NULL
                         OR om.message_status = 'sent'
                       )
                   ) AS sent_message_count,
                   (
                     SELECT om.message_status
                     FROM outreach_messages om
                     WHERE om.contact_id = c.contact_id
                       AND om.outreach_mode = 'general_learning'
                     ORDER BY om.created_at DESC, om.outreach_message_id DESC
                     LIMIT 1
                   ) AS latest_general_learning_message_status
            FROM contacts c
            WHERE c.contact_id = ?
            """,
            (selected_work.work_id,),
        ).fetchone()
        if row is None:
            return f"contact {selected_work.work_id!r} no longer exists."
        if _optional_text(row[1]):
            return (
                f"contact {selected_work.work_id!r} already has a usable working email "
                "and should advance to bounded general-learning outreach instead."
            )
        if int(row[3] or 0) > 0:
            return (
                f"contact {selected_work.work_id!r} is still tied to posting-linked "
                "outreach state and is not eligible for the contact-rooted "
                "general-learning discovery boundary."
            )
        if int(row[4] or 0) > 0:
            return (
                f"contact {selected_work.work_id!r} already has prior sent outreach "
                "history and requires repeat-outreach review."
            )
        latest_status = _optional_text(row[5])
        if latest_status is not None:
            return (
                f"contact {selected_work.work_id!r} already has general-learning "
                f"message state {latest_status!r}."
            )
        if _optional_text(row[2]) in {"outreach_in_progress", "sent", "exhausted"}:
            return (
                f"contact {selected_work.work_id!r} is already at contact_status="
                f"{row[2]!r} and is not eligible for bounded general-learning discovery."
            )
        return None

    if catalog_entry.action_id == ACTION_RUN_GENERAL_LEARNING_OUTREACH:
        if action_dependencies.outreach_sender is None:
            return (
                "Supervisor general-learning outreach requires an injected outreach "
                "sender before any automatic send is attempted."
            )
        row = connection.execute(
            """
            SELECT c.contact_id, c.current_working_email, c.contact_status,
                   (
                     SELECT COUNT(*)
                     FROM job_posting_contacts jpc
                     WHERE jpc.contact_id = c.contact_id
                   ) AS posting_link_count,
                   (
                     SELECT COUNT(*)
                     FROM outreach_messages om
                     WHERE om.contact_id = c.contact_id
                       AND (
                         om.sent_at IS NOT NULL
                         OR om.message_status = 'sent'
                       )
                   ) AS sent_message_count,
                   (
                     SELECT om.message_status
                     FROM outreach_messages om
                     WHERE om.contact_id = c.contact_id
                       AND om.outreach_mode = 'general_learning'
                     ORDER BY om.created_at DESC, om.outreach_message_id DESC
                     LIMIT 1
                   ) AS latest_general_learning_message_status
            FROM contacts c
            WHERE c.contact_id = ?
            """,
            (selected_work.work_id,),
        ).fetchone()
        if row is None:
            return f"contact {selected_work.work_id!r} no longer exists."
        if not _optional_text(row[1]):
            return (
                f"contact {selected_work.work_id!r} is missing a usable working email "
                "for bounded general-learning outreach."
            )
        if int(row[3] or 0) > 0:
            return (
                f"contact {selected_work.work_id!r} is still tied to posting-linked "
                "outreach state and is not eligible for the contact-rooted "
                "general-learning boundary."
            )
        if int(row[4] or 0) > 0:
            return (
                f"contact {selected_work.work_id!r} already has prior sent outreach "
                "history and requires repeat-outreach review."
            )
        latest_status = _optional_text(row[5])
        if latest_status in {"blocked", "failed", "sent"}:
            return (
                f"contact {selected_work.work_id!r} is already at a terminal or "
                f"review-blocked general-learning message status {latest_status!r}."
            )
        if _optional_text(row[2]) in {"outreach_in_progress", "sent", "exhausted"} and latest_status != "generated":
            return (
                f"contact {selected_work.work_id!r} is already at contact_status="
                f"{row[2]!r} and has no resumable generated general-learning draft."
            )
        return None

    if catalog_entry.action_id == ACTION_RUN_GENERAL_LEARNING_DELIVERY_FEEDBACK:
        row = connection.execute(
            """
            SELECT c.contact_id,
                   (
                     SELECT COUNT(*)
                     FROM job_posting_contacts jpc
                     WHERE jpc.contact_id = c.contact_id
                   ) AS posting_link_count
            FROM contacts c
            WHERE c.contact_id = ?
            """,
            (selected_work.work_id,),
        ).fetchone()
        if row is None:
            return f"contact {selected_work.work_id!r} no longer exists."
        if int(row[1] or 0) > 0:
            return (
                f"contact {selected_work.work_id!r} is still tied to posting-linked "
                "outreach state and is not eligible for the contact-rooted "
                "general-learning delayed-feedback boundary."
            )
        pending_feedback_message_ids = (
            _list_contact_rooted_general_learning_sent_outreach_message_ids_without_terminal_feedback(
                connection,
                contact_id=selected_work.work_id,
            )
        )
        if not pending_feedback_message_ids:
            return (
                f"contact {selected_work.work_id!r} has no sent general-learning "
                "messages that still require delayed feedback follow-through."
            )
        return None

    if catalog_entry.action_id == ACTION_RUN_DAILY_MAINTENANCE:
        if selected_work.work_type != WORK_TYPE_MAINTENANCE_CYCLE:
            return (
                "Daily maintenance selected a mismatched work type "
                f"{selected_work.work_type!r}."
            )
        if action_dependencies.maintenance_dependencies is None:
            return "Daily maintenance is not enabled for the current runtime."
        if not is_daily_maintenance_due(
            connection,
            current_time=current_time,
            local_timezone=action_dependencies.local_timezone,
        ):
            return (
                "A maintenance batch already exists for the current local day, so no "
                "additional daily maintenance batch is due."
            )
        return None

    if catalog_entry.action_id == ACTION_ESCALATE_OPEN_INCIDENT:
        incident = get_agent_incident(connection, selected_work.work_id)
        if incident is None:
            return f"agent_incident {selected_work.work_id!r} no longer exists."
        if incident.status not in ACTIVE_INCIDENT_SELECTION_STATUSES:
            return (
                f"agent_incident {selected_work.work_id!r} is not in an active "
                f"selection status; found {incident.status!r}."
            )
        return None

    return f"Catalog action {catalog_entry.action_id!r} is not executable yet."


def _execute_selected_work_unit(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    selected_work: SupervisorWorkUnit,
    *,
    catalog_entry: SupervisorActionCatalogEntry,
    timestamp: str,
    action_dependencies: SupervisorActionDependencies,
) -> tuple[PipelineRunRecord | None, AgentIncidentRecord | None, str | None]:
    if catalog_entry.action_id == ACTION_POLL_GMAIL_LINKEDIN_ALERTS:
        from .linkedin_scraping import (
            ingest_gmail_alert_batch_to_leads,
            materialize_gmail_lead_entities,
        )

        collector = _require_dependency(
            action_dependencies.gmail_alert_collector,
            "Supervisor Gmail polling requires an injected Gmail alert collector.",
        )
        pop_prepared_batch = getattr(collector, "pop_prepared_batch", None)
        if not callable(pop_prepared_batch):
            raise SupervisorStateError(
                "Configured Gmail alert collector does not expose pop_prepared_batch()."
            )
        prepared_batch = pop_prepared_batch(selected_work.work_id)
        if prepared_batch is None:
            prepare_batch = getattr(collector, "prepare_batch", None)
            if callable(prepare_batch):
                prepared_batch = prepare_batch(
                    current_time=timestamp,
                    mailbox_history_checkpoint=read_agent_control_state(
                        connection,
                        timestamp=timestamp,
                    ).gmail_poll_last_history_id,
                )
        if prepared_batch is None or prepared_batch.ingestion_run_id != selected_work.work_id:
            raise SupervisorStateError(
                "Supervisor lost the prepared Gmail alert batch before execution for "
                f"ingestion_run_id {selected_work.work_id!r}."
            )

        if not prepared_batch.messages:
            if not prepared_batch.mailbox_history_id_after:
                raise SupervisorStateError(
                    "Supervisor cannot seed a Gmail mailbox checkpoint from an empty batch "
                    f"without mailbox_history_id_after for ingestion_run_id {selected_work.work_id!r}."
                )
            upsert_control_values(
                connection,
                {
                    "gmail_poll_last_history_id": prepared_batch.mailbox_history_id_after,
                    "gmail_poll_last_checkpoint_at": timestamp,
                    "gmail_poll_last_strategy": prepared_batch.poll_strategy,
                },
                timestamp=timestamp,
            )
            return None, None, None

        ingestion_result = ingest_gmail_alert_batch_to_leads(
            paths.project_root,
            batch=prepared_batch,
        )
        lead_ids = sorted(
            {
                lead_result.lead_id
                for lead_result in ingestion_result.lead_results
                if lead_result.lead_id
            }
        )
        for lead_id in lead_ids:
            materialize_gmail_lead_entities(paths.project_root, lead_id=lead_id)
        if prepared_batch.mailbox_history_id_after:
            upsert_control_values(
                connection,
                {
                    "gmail_poll_last_history_id": prepared_batch.mailbox_history_id_after,
                    "gmail_poll_last_checkpoint_at": timestamp,
                    "gmail_poll_last_strategy": prepared_batch.poll_strategy,
                },
                timestamp=timestamp,
            )
        return None, None, None

    if catalog_entry.action_id == ACTION_REPAIR_STALE_GMAIL_LEAD:
        from .linkedin_scraping import repair_stale_blocked_gmail_leads

        repair_stale_blocked_gmail_leads(
            paths.project_root,
            lead_id=_require_text(selected_work.work_id, "work_id"),
            limit=1,
        )
        return None, None, None

    if catalog_entry.action_id == ACTION_BOOTSTRAP_ROLE_TARGETED_RUN:
        pipeline_run, _ = ensure_role_targeted_pipeline_run(
            connection,
            lead_id=_require_text(selected_work.lead_id, "lead_id"),
            job_posting_id=selected_work.work_id,
            current_stage="lead_handoff",
            started_at=timestamp,
            run_summary=(
                "Supervisor bootstrapped a durable role-targeted run from posting state."
            ),
        )
        return pipeline_run, None, None

    if catalog_entry.action_id == ACTION_CHECKPOINT_PIPELINE_RUN:
        pipeline_run = _require_pipeline_run(connection, selected_work.work_id)
        next_stage = "resume_tailoring"
        run_summary = (
            "Supervisor advanced the durable pipeline run from lead_handoff into the "
            "bounded resume_tailoring boundary."
        )
        if pipeline_run.job_posting_id is not None:
            latest_run = connection.execute(
                """
                SELECT tailoring_status, resume_review_status
                FROM resume_tailoring_runs
                WHERE job_posting_id = ?
                ORDER BY COALESCE(completed_at, updated_at, created_at, started_at) DESC,
                         resume_tailoring_run_id DESC
                LIMIT 1
                """,
                (pipeline_run.job_posting_id,),
            ).fetchone()
            posting_row = connection.execute(
                """
                SELECT posting_status
                FROM job_postings
                WHERE job_posting_id = ?
                """,
                (pipeline_run.job_posting_id,),
            ).fetchone()
            if (
                posting_row is not None
                and posting_row[0] == "resume_review_pending"
                and latest_run is not None
                and latest_run[0] == "tailored"
                and latest_run[1] == "resume_review_pending"
            ):
                next_stage = "agent_review"
                run_summary = (
                    "Supervisor advanced the durable pipeline run from lead_handoff into "
                    "mandatory agent review without creating duplicate work."
                )
        pipeline_run = advance_pipeline_run(
            connection,
            selected_work.work_id,
            current_stage=next_stage,
            run_summary=run_summary,
            timestamp=timestamp,
        )
        return pipeline_run, None, None

    if catalog_entry.action_id == ACTION_RUN_ROLE_TARGETED_RESUME_TAILORING:
        from .resume_tailoring import (
            generate_tailoring_intelligence,
            finalize_tailoring_run,
        )

        pipeline_run = _require_pipeline_run(connection, selected_work.work_id)
        job_posting_id = _require_text(pipeline_run.job_posting_id, "job_posting_id")
        intelligence_result = generate_tailoring_intelligence(
            connection,
            paths,
            job_posting_id=job_posting_id,
            timestamp=timestamp,
        )
        posting_row = connection.execute(
            """
            SELECT posting_status
            FROM job_postings
            WHERE job_posting_id = ?
            """,
            (job_posting_id,),
        ).fetchone()
        posting_status = _optional_text(posting_row[0]) if posting_row is not None else None
        if intelligence_result.resume_tailoring_run_id is None:
            if posting_status == "hard_ineligible":
                pipeline_run = complete_pipeline_run(
                    connection,
                    selected_work.work_id,
                    current_stage="hard_ineligible",
                    run_summary=(
                        "Supervisor completed the durable pipeline run because the posting "
                        "was marked hard_ineligible during autonomous resume-tailoring bootstrap."
                    ),
                    timestamp=timestamp,
                )
            else:
                reason = intelligence_result.blocked_reason_code or "resume_tailoring_unavailable"
                pipeline_run = escalate_pipeline_run(
                    connection,
                    selected_work.work_id,
                    current_stage="resume_tailoring",
                    error_summary=(
                        "Autonomous resume tailoring could not start for the selected "
                        f"job_posting because {reason}."
                    ),
                    run_summary=(
                        "Supervisor escalated the durable pipeline run at the "
                        "resume_tailoring boundary because bootstrap could not continue."
                    ),
                    timestamp=timestamp,
                )
            return pipeline_run, None, None

        finalize_result = finalize_tailoring_run(
            connection,
            paths,
            job_posting_id=job_posting_id,
            timestamp=timestamp,
        )
        if finalize_result.result != "pass":
            reason = finalize_result.reason_code or finalize_result.result
            if finalize_result.result == "needs_revision":
                error_summary = (
                    "Autonomous resume tailoring did not reach the pending-review gate "
                    f"for job_posting {job_posting_id!r}: {reason}."
                )
                if pipeline_run.run_status == RUN_STATUS_PAUSED:
                    pipeline_run = escalate_pipeline_run(
                        connection,
                        selected_work.work_id,
                        current_stage="resume_tailoring",
                        error_summary=error_summary,
                        run_summary=(
                            "Supervisor escalated the durable pipeline run at the "
                            "resume_tailoring boundary because a bounded retry still "
                            "did not produce a pending-review tailored output."
                        ),
                        timestamp=timestamp,
                    )
                else:
                    pipeline_run = pause_pipeline_run(
                        connection,
                        selected_work.work_id,
                        current_stage="resume_tailoring",
                        error_summary=error_summary,
                        run_summary=(
                            "Supervisor paused the durable pipeline run at the "
                            "resume_tailoring boundary after a revision-required "
                            "output and will retry the same bounded stage once on "
                            "the next heartbeat."
                        ),
                        timestamp=timestamp,
                    )
                return pipeline_run, None, None
            pipeline_run = escalate_pipeline_run(
                connection,
                selected_work.work_id,
                current_stage="resume_tailoring",
                error_summary=(
                    "Autonomous resume tailoring did not reach the pending-review gate "
                    f"for job_posting {job_posting_id!r}: {reason}."
                ),
                run_summary=(
                    "Supervisor escalated the durable pipeline run at the "
                    "resume_tailoring boundary because finalize did not produce a "
                    "pending-review tailored output."
                ),
                timestamp=timestamp,
            )
            return pipeline_run, None, None

        pipeline_run = advance_pipeline_run(
            connection,
            selected_work.work_id,
            current_stage="agent_review",
            run_summary=(
                "Supervisor completed the bounded resume_tailoring boundary and "
                "advanced the durable pipeline run into mandatory agent review."
            ),
            timestamp=timestamp,
        )
        return pipeline_run, None, None

    if catalog_entry.action_id == ACTION_PERFORM_MANDATORY_AGENT_REVIEW:
        from .resume_tailoring import (
            JOB_POSTING_STATUS_READY_FOR_OUTREACH,
            JOB_POSTING_STATUS_REQUIRES_CONTACTS,
            MANDATORY_REVIEWER_AGENT,
            RESUME_REVIEW_STATUS_APPROVED,
            record_tailoring_review_decision,
        )

        review_result = record_tailoring_review_decision(
            connection,
            paths,
            job_posting_id=_require_text(selected_work.job_posting_id, "job_posting_id"),
            decision_type=RESUME_REVIEW_STATUS_APPROVED,
            decision_notes=(
                "Supervisor agent approved the verified tailored output under the current "
                "bounded autonomous review policy."
            ),
            reviewer_type=MANDATORY_REVIEWER_AGENT,
            timestamp=timestamp,
        )
        if review_result.posting_status == JOB_POSTING_STATUS_REQUIRES_CONTACTS:
            next_stage = "people_search"
        elif review_result.posting_status == JOB_POSTING_STATUS_READY_FOR_OUTREACH:
            next_stage = "sending"
        else:  # pragma: no cover - defensive invariant
            raise SupervisorStateError(
                "Mandatory agent review advanced the posting to an unsupported "
                f"status {review_result.posting_status!r}."
            )
        pipeline_run = advance_pipeline_run(
            connection,
            selected_work.work_id,
            current_stage=next_stage,
            run_summary=(
                "Supervisor completed the bounded mandatory agent review and "
                f"advanced the durable pipeline run to {next_stage}."
            ),
            timestamp=timestamp,
        )
        return pipeline_run, None, None

    if catalog_entry.action_id == ACTION_RUN_ROLE_TARGETED_PEOPLE_SEARCH:
        from .email_discovery import (
            JOB_POSTING_STATUS_READY_FOR_OUTREACH,
            JOB_POSTING_STATUS_REQUIRES_CONTACTS,
            run_apollo_contact_enrichment,
            run_apollo_people_search,
        )

        job_posting_id = _require_text(selected_work.job_posting_id, "job_posting_id")
        posting_row = connection.execute(
            """
            SELECT posting_status
            FROM job_postings
            WHERE job_posting_id = ?
            """,
            (job_posting_id,),
        ).fetchone()
        if posting_row is None:  # pragma: no cover - validated earlier
            raise SupervisorStateError(f"job_posting {job_posting_id!r} no longer exists.")

        current_posting_status = _require_text(
            _optional_text(posting_row[0]),
            "posting_status",
        )
        next_stage: str
        run_summary: str
        if current_posting_status == JOB_POSTING_STATUS_READY_FOR_OUTREACH:
            next_stage = "sending"
            run_summary = (
                "Supervisor detected that canonical discovery state was already "
                "ready_for_outreach and advanced the durable pipeline run directly to sending."
            )
        elif current_posting_status == JOB_POSTING_STATUS_REQUIRES_CONTACTS:
            search_result = run_apollo_people_search(
                project_root=paths.project_root,
                job_posting_id=job_posting_id,
                provider=action_dependencies.apollo_people_search_provider,
                current_time=timestamp,
            )
            enrichment_result = run_apollo_contact_enrichment(
                project_root=paths.project_root,
                job_posting_id=job_posting_id,
                provider=action_dependencies.apollo_contact_enrichment_provider,
                recipient_profile_extractor=action_dependencies.recipient_profile_extractor,
                current_time=timestamp,
            )
            if enrichment_result.posting_status == JOB_POSTING_STATUS_READY_FOR_OUTREACH:
                next_stage = "sending"
            elif enrichment_result.posting_status == JOB_POSTING_STATUS_REQUIRES_CONTACTS:
                shortlisted_count = _count_posting_contacts_with_link_status(
                    connection,
                    job_posting_id=job_posting_id,
                    link_level_status="shortlisted",
                )
                if shortlisted_count <= 0:
                    pipeline_run = escalate_pipeline_run(
                        connection,
                        selected_work.work_id,
                        current_stage="people_search",
                        error_summary=(
                            "Bounded people search did not identify any shortlisted "
                            f"internal contacts for job_posting {job_posting_id!r}."
                        ),
                        run_summary=(
                            "Supervisor escalated the durable pipeline run at the "
                            "people_search boundary because bounded discovery did "
                            "not find any viable internal contacts."
                        ),
                        timestamp=timestamp,
                    )
                    return pipeline_run, None, None
                next_stage = "email_discovery"
            else:  # pragma: no cover - defensive invariant
                raise SupervisorStateError(
                    "People search advanced the posting to an unsupported status "
                    f"{enrichment_result.posting_status!r}."
                )
            run_summary = (
                "Supervisor ran bounded people search across "
                f"{search_result.candidate_count} candidates, refreshed the shortlisted "
                f"contact boundary, and advanced the durable pipeline run to {next_stage}."
            )
        else:  # pragma: no cover - validated earlier
            raise SupervisorStateError(
                f"job_posting {job_posting_id!r} is at unsupported people-search "
                f"posting_status={current_posting_status!r}."
            )

        pipeline_run = advance_pipeline_run(
            connection,
            selected_work.work_id,
            current_stage=next_stage,
            run_summary=run_summary,
            timestamp=timestamp,
        )
        return pipeline_run, None, None

    if catalog_entry.action_id == ACTION_RUN_ROLE_TARGETED_EMAIL_DISCOVERY:
        from .email_discovery import (
            JOB_POSTING_STATUS_READY_FOR_OUTREACH,
            JOB_POSTING_STATUS_REQUIRES_CONTACTS,
            run_email_discovery_for_contact,
        )
        from .outreach import evaluate_role_targeted_send_set

        job_posting_id = _require_text(selected_work.job_posting_id, "job_posting_id")
        posting_row = connection.execute(
            """
            SELECT posting_status
            FROM job_postings
            WHERE job_posting_id = ?
            """,
            (job_posting_id,),
        ).fetchone()
        if posting_row is None:  # pragma: no cover - validated earlier
            raise SupervisorStateError(f"job_posting {job_posting_id!r} no longer exists.")

        current_posting_status = _require_text(
            _optional_text(posting_row[0]),
            "posting_status",
        )
        if current_posting_status == JOB_POSTING_STATUS_READY_FOR_OUTREACH:
            next_stage = "sending"
            run_summary = (
                "Supervisor detected that the current send set was already ready "
                "for outreach and advanced the durable pipeline run directly to sending."
            )
        elif current_posting_status == JOB_POSTING_STATUS_REQUIRES_CONTACTS:
            def _escalate_exhausted_email_discovery() -> tuple[PipelineRunRecord, None, None]:
                return (
                    escalate_pipeline_run(
                        connection,
                        selected_work.work_id,
                        current_stage="email_discovery",
                        error_summary=(
                            "Bounded email discovery exhausted the current send set "
                            f"without a usable email for job_posting {job_posting_id!r}."
                        ),
                        run_summary=(
                            "Supervisor escalated the durable pipeline run at the "
                            "email_discovery boundary because bounded discovery "
                            "exhausted the current send set without a usable email."
                        ),
                        timestamp=timestamp,
                    ),
                    None,
                    None,
                )

            send_set_plan = evaluate_role_targeted_send_set(
                connection,
                job_posting_id=job_posting_id,
                current_time=timestamp,
            )
            if not send_set_plan.selected_contacts:
                return _escalate_exhausted_email_discovery()
            target_contact = next(
                (
                    contact
                    for contact in send_set_plan.selected_contacts
                    if not contact.has_usable_email
                ),
                send_set_plan.selected_contacts[0],
            )
            discovery_result = run_email_discovery_for_contact(
                project_root=paths.project_root,
                job_posting_id=job_posting_id,
                contact_id=target_contact.contact_id,
                providers=action_dependencies.email_finder_providers,
                current_time=timestamp,
            )
            if discovery_result.posting_status == JOB_POSTING_STATUS_READY_FOR_OUTREACH:
                next_stage = "sending"
                run_summary = (
                    "Supervisor ran bounded email discovery for "
                    f"{target_contact.contact_id} and advanced the durable pipeline run to "
                    "sending once the current send set became ready."
                )
            elif discovery_result.posting_status == JOB_POSTING_STATUS_REQUIRES_CONTACTS:
                refreshed_send_set_plan = evaluate_role_targeted_send_set(
                    connection,
                    job_posting_id=job_posting_id,
                    current_time=timestamp,
                )
                if not refreshed_send_set_plan.selected_contacts:
                    return _escalate_exhausted_email_discovery()
                next_stage = "email_discovery"
                run_summary = (
                    "Supervisor ran bounded email discovery for "
                    f"{target_contact.contact_id} and kept the durable pipeline run at "
                    "email_discovery while other current send-set contacts still need "
                    "usable emails."
                )
            else:  # pragma: no cover - defensive invariant
                raise SupervisorStateError(
                    "Email discovery advanced the posting to an unsupported status "
                    f"{discovery_result.posting_status!r}."
                )
        else:  # pragma: no cover - validated earlier
            raise SupervisorStateError(
                f"job_posting {job_posting_id!r} is at unsupported email-discovery "
                f"posting_status={current_posting_status!r}."
            )

        pipeline_run = advance_pipeline_run(
            connection,
            selected_work.work_id,
            current_stage=next_stage,
            run_summary=run_summary,
            timestamp=timestamp,
        )
        return pipeline_run, None, None

    if catalog_entry.action_id == ACTION_RUN_ROLE_TARGETED_SENDING:
        from .outreach import (
            JOB_POSTING_STATUS_COMPLETED,
            JOB_POSTING_STATUS_OUTREACH_IN_PROGRESS,
            JOB_POSTING_STATUS_READY_FOR_OUTREACH,
            execute_role_targeted_send_set,
            generate_role_targeted_send_set_drafts,
        )

        job_posting_id = _require_text(selected_work.job_posting_id, "job_posting_id")
        posting_row = connection.execute(
            """
            SELECT posting_status
            FROM job_postings
            WHERE job_posting_id = ?
            """,
            (job_posting_id,),
        ).fetchone()
        if posting_row is None:  # pragma: no cover - validated earlier
            raise SupervisorStateError(f"job_posting {job_posting_id!r} no longer exists.")

        current_posting_status = _require_text(
            _optional_text(posting_row[0]),
            "posting_status",
        )
        drafted_count = 0
        sent_count = 0
        blocked_count = 0
        failed_count = 0
        delayed_count = 0

        if current_posting_status == JOB_POSTING_STATUS_READY_FOR_OUTREACH:
            draft_batch = generate_role_targeted_send_set_drafts(
                connection,
                project_root=paths.project_root,
                job_posting_id=job_posting_id,
                current_time=timestamp,
                local_timezone=action_dependencies.local_timezone,
            )
            drafted_count = len(draft_batch.drafted_messages)

        latest_posting_status = _load_posting_status(connection, job_posting_id=job_posting_id)
        if latest_posting_status in {
            JOB_POSTING_STATUS_READY_FOR_OUTREACH,
            JOB_POSTING_STATUS_OUTREACH_IN_PROGRESS,
        }:
            send_result = execute_role_targeted_send_set(
                connection,
                project_root=paths.project_root,
                job_posting_id=job_posting_id,
                current_time=timestamp,
                sender=_require_dependency(
                    action_dependencies.outreach_sender,
                    "Supervisor sending requires an injected outreach sender.",
                ),
                local_timezone=action_dependencies.local_timezone,
                feedback_observer=action_dependencies.feedback_observer,
            )
            latest_posting_status = send_result.posting_status_after_execution
            sent_count = len(send_result.sent_messages)
            blocked_count = len(send_result.blocked_messages)
            failed_count = len(send_result.failed_messages)
            delayed_count = len(send_result.delayed_messages)

        if latest_posting_status == JOB_POSTING_STATUS_COMPLETED:
            if _count_posting_outreach_messages_with_status(
                connection,
                job_posting_id=job_posting_id,
                message_status="sent",
            ) > 0:
                pipeline_run = advance_pipeline_run(
                    connection,
                    selected_work.work_id,
                    current_stage="delivery_feedback",
                    run_summary=(
                        "Supervisor completed the bounded sending step, observed a "
                        f"terminal outreach wave after {sent_count} sent, {blocked_count} "
                        f"blocked, and {failed_count} failed messages in this cycle, and "
                        "advanced the durable pipeline run to delivery_feedback."
                    ),
                    timestamp=timestamp,
                )
            else:
                pipeline_run = complete_pipeline_run(
                    connection,
                    selected_work.work_id,
                    current_stage="completed",
                    run_summary=(
                        "Supervisor completed the bounded sending step without a "
                        "successful automatic send, so the durable pipeline run reached "
                        "a review-worthy terminal blocked outcome."
                    ),
                    timestamp=timestamp,
                )
            return pipeline_run, None, None

        if latest_posting_status != JOB_POSTING_STATUS_OUTREACH_IN_PROGRESS:
            raise SupervisorStateError(
                "Sending advanced the posting to an unsupported status "
                f"{latest_posting_status!r}."
            )

        pipeline_run = advance_pipeline_run(
            connection,
            selected_work.work_id,
            current_stage="sending",
            run_summary=(
                "Supervisor ran the bounded sending step with "
                f"{drafted_count} drafted, {sent_count} sent, {blocked_count} blocked, "
                f"{failed_count} failed, and {delayed_count} delayed messages in this cycle, "
                "and kept the durable pipeline run at sending while later-wave work remains."
            ),
            timestamp=timestamp,
        )
        return pipeline_run, None, None

    if catalog_entry.action_id == ACTION_RUN_ROLE_TARGETED_DELIVERY_FEEDBACK:
        job_posting_id = _require_text(selected_work.job_posting_id, "job_posting_id")
        sent_message_ids = _list_posting_sent_outreach_message_ids(
            connection,
            job_posting_id=job_posting_id,
        )
        if not sent_message_ids:
            raise SupervisorStateError(
                f"job_posting {job_posting_id!r} reached delivery_feedback without any "
                "sent outreach messages."
            )

        pending_feedback_message_ids = _list_posting_sent_outreach_message_ids_without_terminal_feedback(
            connection,
            job_posting_id=job_posting_id,
        )
        if pending_feedback_message_ids:
            pipeline_run = advance_pipeline_run(
                connection,
                selected_work.work_id,
                current_stage="delivery_feedback",
                run_summary=(
                    "Supervisor inspected persisted delivery-feedback state and kept "
                    "the durable pipeline run at delivery_feedback while "
                    f"{len(pending_feedback_message_ids)} sent messages still await a "
                    "high-level feedback outcome from the separate feedback-sync worker."
                ),
                timestamp=timestamp,
            )
            return pipeline_run, None, None

        pipeline_run = complete_pipeline_run(
            connection,
            selected_work.work_id,
            current_stage="completed",
            run_summary=(
                "Supervisor inspected persisted delivery-feedback state and "
                "completed the durable pipeline run once every sent message had a "
                "high-level delivery-feedback outcome recorded by the separate "
                "feedback-sync worker."
            ),
            timestamp=timestamp,
        )
        return pipeline_run, None, None

    if catalog_entry.action_id == ACTION_RUN_GENERAL_LEARNING_EMAIL_DISCOVERY:
        from .email_discovery import run_general_learning_email_discovery

        general_learning_discovery = run_general_learning_email_discovery(
            project_root=paths.project_root,
            contact_id=selected_work.work_id,
            providers=action_dependencies.email_finder_providers,
            current_time=timestamp,
        )
        if general_learning_discovery.contact_status in {
            "identified",
            "working_email_found",
            "exhausted",
        }:
            return None, None, None
        raise SupervisorStateError(
            "General-learning email discovery completed with an unsupported contact "
            f"status {general_learning_discovery.contact_status!r}."
        )

    if catalog_entry.action_id == ACTION_RUN_GENERAL_LEARNING_OUTREACH:
        from .outreach import execute_general_learning_outreach

        general_learning_result = execute_general_learning_outreach(
            connection,
            project_root=paths.project_root,
            contact_id=selected_work.work_id,
            current_time=timestamp,
            sender=_require_dependency(
                action_dependencies.outreach_sender,
                "Supervisor general-learning outreach requires an injected outreach sender.",
            ),
            feedback_observer=action_dependencies.feedback_observer,
        )
        if general_learning_result.message_status_after_execution == "sent":
            return None, None, None
        if general_learning_result.message_status_after_execution in {"blocked", "failed"}:
            return None, None, None
        raise SupervisorStateError(
            "General-learning outreach completed with an unsupported message status "
            f"{general_learning_result.message_status_after_execution!r}."
        )

    if catalog_entry.action_id == ACTION_RUN_GENERAL_LEARNING_DELIVERY_FEEDBACK:
        # The separate feedback-sync worker owns delayed mailbox polling for
        # contact-rooted general-learning outreach.
        return None, None, None

    if catalog_entry.action_id == ACTION_RUN_DAILY_MAINTENANCE:
        maintenance_execution = run_daily_maintenance_cycle(
            connection,
            paths,
            current_time=timestamp,
            local_timezone=action_dependencies.local_timezone,
            dependencies=_require_dependency(
                action_dependencies.maintenance_dependencies,
                "Supervisor maintenance requires injected maintenance dependencies.",
            ),
        )
        return None, None, maintenance_execution.batch.maintenance_change_batch_id

    if catalog_entry.action_id == ACTION_ESCALATE_OPEN_INCIDENT:
        incident = escalate_agent_incident(
            connection,
            selected_work.work_id,
            escalation_reason=(
                "No bounded repair action is registered yet for this incident, so the "
                "supervisor escalated it for expert review."
            ),
            timestamp=timestamp,
            repair_attempt_summary=(
                "Supervisor cycle selected the unresolved incident first and escalated it "
                "because the current action catalog has no repair handler yet."
            ),
        )
        return None, incident, None

    raise SupervisorStateError(
        f"Catalog action {catalog_entry.action_id!r} is not executable yet."
    )


def _validate_selected_work_result(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    selected_work: SupervisorWorkUnit,
    *,
    catalog_entry: SupervisorActionCatalogEntry,
    pipeline_run: PipelineRunRecord | None,
    incident: AgentIncidentRecord | None,
    maintenance_batch_id: str | None,
) -> str | None:
    if catalog_entry.action_id == ACTION_POLL_GMAIL_LINKEDIN_ALERTS:
        matching_batches = 0
        for email_json_path in sorted(paths.gmail_runtime_dir.glob("*/email.json")):
            try:
                payload = json.loads(email_json_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            if payload.get("ingestion_run_id") == selected_work.work_id:
                matching_batches += 1
        if matching_batches <= 0:
            return (
                "Supervisor Gmail polling completed without persisting any Gmail "
                "collection units for ingestion_run_id "
                f"{selected_work.work_id!r}."
            )
        return None

    if catalog_entry.action_id == ACTION_REPAIR_STALE_GMAIL_LEAD:
        lead_row = connection.execute(
            """
            SELECT lead_status, source_url
            FROM linkedin_leads
            WHERE lead_id = ?
            """,
            (selected_work.work_id,),
        ).fetchone()
        if lead_row is None:
            return (
                "Supervisor stale Gmail lead repair completed but the selected lead "
                f"{selected_work.work_id!r} no longer exists."
            )
        if not _optional_text(lead_row["source_url"]):
            return (
                "Supervisor stale Gmail lead repair completed without restoring a "
                f"canonical source_url for lead {selected_work.work_id!r}."
            )
        return None

    if catalog_entry.action_id == ACTION_BOOTSTRAP_ROLE_TARGETED_RUN:
        if pipeline_run is None:
            return "Supervisor failed to create a pipeline_run for the selected job_posting."
        if pipeline_run.job_posting_id != selected_work.work_id:
            return (
                "Supervisor created a pipeline_run for the wrong job_posting_id: "
                f"{pipeline_run.job_posting_id!r}."
            )
        if pipeline_run.current_stage != "lead_handoff":
            return (
                "Bootstrapped pipeline_run did not start at lead_handoff; found "
                f"{pipeline_run.current_stage!r}."
            )
        return None

    if catalog_entry.action_id == ACTION_CHECKPOINT_PIPELINE_RUN:
        if pipeline_run is None:
            return "Supervisor failed to load the selected pipeline_run after checkpointing."
        if pipeline_run.pipeline_run_id != selected_work.work_id:
            return "Supervisor checkpointing changed the selected pipeline_run identity."
        if pipeline_run.run_status != RUN_STATUS_IN_PROGRESS:
            return (
                "Checkpointed pipeline_run is not in progress after resume; found "
                f"{pipeline_run.run_status!r}."
            )
        if pipeline_run.current_stage not in {"agent_review", "resume_tailoring"}:
            return (
                "Lead handoff progression did not advance into the expected next "
                f"boundary; found {pipeline_run.current_stage!r}."
            )
        return None

    if catalog_entry.action_id == ACTION_RUN_ROLE_TARGETED_RESUME_TAILORING:
        if pipeline_run is None:
            return (
                "Supervisor failed to load the selected pipeline_run after running the "
                "resume-tailoring boundary."
            )
        if pipeline_run.pipeline_run_id != selected_work.work_id:
            return "Resume-tailoring progression changed the selected pipeline_run identity."
        if pipeline_run.run_status == RUN_STATUS_IN_PROGRESS:
            if pipeline_run.current_stage != "agent_review":
                return (
                    "Resume-tailoring progression did not advance into agent_review; "
                    f"found {pipeline_run.current_stage!r}."
                )
            if pipeline_run.job_posting_id is None:
                return (
                    "Resume-tailoring progression completed without a linked job_posting_id."
                )
            latest_run = connection.execute(
                """
                SELECT tailoring_status, resume_review_status
                FROM resume_tailoring_runs
                WHERE job_posting_id = ?
                ORDER BY COALESCE(completed_at, updated_at, created_at, started_at) DESC,
                         resume_tailoring_run_id DESC
                LIMIT 1
                """,
                (pipeline_run.job_posting_id,),
            ).fetchone()
            if latest_run is None:
                return (
                    "Resume-tailoring progression did not persist a resume_tailoring_run "
                    "for the selected posting."
                )
            if latest_run[0] != "tailored" or latest_run[1] != "resume_review_pending":
                return (
                    "Resume-tailoring progression did not reach the pending-review gate; "
                    f"found tailoring_status={latest_run[0]!r}, "
                    f"resume_review_status={latest_run[1]!r}."
                )
            posting_row = connection.execute(
                """
                SELECT posting_status
                FROM job_postings
                WHERE job_posting_id = ?
                """,
                (pipeline_run.job_posting_id,),
            ).fetchone()
            if posting_row is None or posting_row[0] != "resume_review_pending":
                return (
                    "Resume-tailoring progression did not update the posting to "
                    f"resume_review_pending; found {None if posting_row is None else posting_row[0]!r}."
                )
            return None
        if pipeline_run.run_status == RUN_STATUS_COMPLETED:
            if pipeline_run.current_stage != "hard_ineligible":
                return (
                    "Resume-tailoring completed terminally at an unexpected stage; "
                    f"found {pipeline_run.current_stage!r}."
                )
            return None
        if pipeline_run.run_status == RUN_STATUS_ESCALATED:
            if pipeline_run.current_stage != "resume_tailoring":
                return (
                    "Resume-tailoring escalated at an unexpected stage; found "
                    f"{pipeline_run.current_stage!r}."
                )
            if not _optional_text(pipeline_run.last_error_summary):
                return "Resume-tailoring escalation did not persist an error summary."
            return None
        if pipeline_run.run_status == RUN_STATUS_PAUSED:
            if pipeline_run.current_stage != "resume_tailoring":
                return (
                    "Resume-tailoring retry pause landed at an unexpected stage; found "
                    f"{pipeline_run.current_stage!r}."
                )
            if pipeline_run.job_posting_id is None:
                return "Resume-tailoring pause did not preserve the linked job_posting_id."
            latest_run = connection.execute(
                """
                SELECT tailoring_status, resume_review_status
                FROM resume_tailoring_runs
                WHERE job_posting_id = ?
                ORDER BY COALESCE(completed_at, updated_at, created_at, started_at) DESC,
                         resume_tailoring_run_id DESC
                LIMIT 1
                """,
                (pipeline_run.job_posting_id,),
            ).fetchone()
            if latest_run is None:
                return (
                    "Resume-tailoring retry pause did not preserve the latest tailoring "
                    "run for the selected posting."
                )
            if latest_run[0] != "needs_revision" or latest_run[1] != "not_ready":
                return (
                    "Resume-tailoring retry pause expected a needs_revision/not_ready "
                    f"tailoring run; found tailoring_status={latest_run[0]!r}, "
                    f"resume_review_status={latest_run[1]!r}."
                )
            if not _optional_text(pipeline_run.last_error_summary):
                return "Resume-tailoring retry pause did not persist an error summary."
            return None
        return (
            "Resume-tailoring progression left the pipeline_run in an unsupported state "
            f"{pipeline_run.run_status!r}."
        )

    if catalog_entry.action_id == ACTION_PERFORM_MANDATORY_AGENT_REVIEW:
        if pipeline_run is None:
            return "Supervisor failed to load the selected pipeline_run after mandatory review."
        if pipeline_run.pipeline_run_id != selected_work.work_id:
            return "Mandatory review changed the selected pipeline_run identity."
        if pipeline_run.run_status != RUN_STATUS_IN_PROGRESS:
            return (
                "Mandatory review left the pipeline_run outside in-progress state; found "
                f"{pipeline_run.run_status!r}."
            )
        if pipeline_run.current_stage not in {"people_search", "sending"}:
            return (
                "Mandatory review did not advance the durable pipeline run to the next "
                f"supported outreach stage; found {pipeline_run.current_stage!r}."
            )
        if pipeline_run.job_posting_id is None:
            return "Mandatory review completed without a linked job_posting_id."
        latest_run = connection.execute(
            """
            SELECT resume_review_status
            FROM resume_tailoring_runs
            WHERE job_posting_id = ?
            ORDER BY COALESCE(completed_at, updated_at, created_at, started_at) DESC,
                     resume_tailoring_run_id DESC
            LIMIT 1
            """,
            (pipeline_run.job_posting_id,),
        ).fetchone()
        if latest_run is None or latest_run[0] != "approved":
            return "Mandatory review did not persist an approved tailoring decision."
        posting_row = connection.execute(
            """
            SELECT posting_status
            FROM job_postings
            WHERE job_posting_id = ?
            """,
            (pipeline_run.job_posting_id,),
        ).fetchone()
        if posting_row is None:
            return "Mandatory review completed without a persisted job_posting row."
        if posting_row[0] == "requires_contacts" and pipeline_run.current_stage != "people_search":
            return (
                "Approved mandatory review should advance to people_search when "
                f"posting_status=require_contacts, but found {pipeline_run.current_stage!r}."
            )
        if posting_row[0] == "ready_for_outreach" and pipeline_run.current_stage != "sending":
            return (
                "Approved mandatory review should advance to sending when "
                f"posting_status=ready_for_outreach, but found {pipeline_run.current_stage!r}."
            )
        if posting_row[0] not in {"requires_contacts", "ready_for_outreach"}:
            return (
                "Mandatory review persisted an unexpected posting status "
                f"{posting_row[0]!r}."
            )
        return None

    if catalog_entry.action_id == ACTION_RUN_ROLE_TARGETED_PEOPLE_SEARCH:
        if pipeline_run is None:
            return "Supervisor failed to load the selected pipeline_run after people search."
        if pipeline_run.pipeline_run_id != selected_work.work_id:
            return "People search changed the selected pipeline_run identity."
        if pipeline_run.run_status == RUN_STATUS_ESCALATED:
            if pipeline_run.current_stage != "people_search":
                return (
                    "People search escalation must persist at the people_search "
                    f"boundary; found {pipeline_run.current_stage!r}."
                )
            if not _optional_text(pipeline_run.last_error_summary):
                return "People search escalation did not persist an error summary."
            if pipeline_run.job_posting_id is None:
                return "People search escalation completed without a linked job_posting_id."
            posting_row = connection.execute(
                """
                SELECT posting_status
                FROM job_postings
                WHERE job_posting_id = ?
                """,
                (pipeline_run.job_posting_id,),
            ).fetchone()
            if posting_row is None:
                return "People search escalation completed without a persisted job_posting row."
            if posting_row[0] != "requires_contacts":
                return (
                    "People search escalation must leave the posting at "
                    f"requires_contacts; found {posting_row[0]!r}."
                )
            people_search_artifact_count = connection.execute(
                """
                SELECT COUNT(*)
                FROM artifact_records
                WHERE artifact_type = 'people_search_result'
                  AND job_posting_id = ?
                """,
                (pipeline_run.job_posting_id,),
            ).fetchone()[0]
            if people_search_artifact_count <= 0:
                return (
                    "People search escalation completed without a persisted "
                    "people_search_result artifact."
                )
            return None
        if pipeline_run.run_status != RUN_STATUS_IN_PROGRESS:
            return (
                "People search left the pipeline_run outside in-progress state; found "
                f"{pipeline_run.run_status!r}."
            )
        if pipeline_run.current_stage not in {"email_discovery", "sending"}:
            return (
                "People search did not advance the durable pipeline run to the next "
                f"downstream stage; found {pipeline_run.current_stage!r}."
            )
        if pipeline_run.job_posting_id is None:
            return "People search completed without a linked job_posting_id."
        posting_row = connection.execute(
            """
            SELECT posting_status
            FROM job_postings
            WHERE job_posting_id = ?
            """,
            (pipeline_run.job_posting_id,),
        ).fetchone()
        if posting_row is None:
            return "People search completed without a persisted job_posting row."
        shortlisted_count = _count_posting_contacts_with_link_status(
            connection,
            job_posting_id=pipeline_run.job_posting_id,
            link_level_status="shortlisted",
        )
        people_search_artifact_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM artifact_records
            WHERE artifact_type = 'people_search_result'
              AND job_posting_id = ?
            """,
            (pipeline_run.job_posting_id,),
        ).fetchone()[0]
        if posting_row[0] == "requires_contacts":
            if pipeline_run.current_stage != "email_discovery":
                return (
                    "People search should advance to email_discovery when "
                    f"posting_status=requires_contacts, but found {pipeline_run.current_stage!r}."
                )
            if shortlisted_count <= 0:
                return "People search advanced to email_discovery without any shortlisted contacts."
            if people_search_artifact_count <= 0:
                return "People search advanced to email_discovery without a people_search_result artifact."
            return None
        if posting_row[0] == "ready_for_outreach" and pipeline_run.current_stage != "sending":
            return (
                "People search should advance to sending when "
                f"posting_status=ready_for_outreach, but found {pipeline_run.current_stage!r}."
            )
        if posting_row[0] not in {"requires_contacts", "ready_for_outreach"}:
            return f"People search persisted an unexpected posting status {posting_row[0]!r}."
        return None

    if catalog_entry.action_id == ACTION_RUN_ROLE_TARGETED_EMAIL_DISCOVERY:
        if pipeline_run is None:
            return "Supervisor failed to load the selected pipeline_run after email discovery."
        if pipeline_run.pipeline_run_id != selected_work.work_id:
            return "Email discovery changed the selected pipeline_run identity."
        if pipeline_run.run_status not in {RUN_STATUS_IN_PROGRESS, RUN_STATUS_ESCALATED}:
            return (
                "Email discovery left the pipeline_run outside the expected active/terminal state; found "
                f"{pipeline_run.run_status!r}."
            )
        if pipeline_run.current_stage != "email_discovery" and not (
            pipeline_run.run_status == RUN_STATUS_IN_PROGRESS and pipeline_run.current_stage == "sending"
        ):
            return (
                "Email discovery did not keep the durable pipeline run at the current "
                f"boundary or advance it to sending; found {pipeline_run.current_stage!r}."
            )
        if pipeline_run.job_posting_id is None:
            return "Email discovery completed without a linked job_posting_id."
        posting_row = connection.execute(
            """
            SELECT posting_status
            FROM job_postings
            WHERE job_posting_id = ?
            """,
            (pipeline_run.job_posting_id,),
        ).fetchone()
        if posting_row is None:
            return "Email discovery completed without a persisted job_posting row."
        discovery_artifact_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM artifact_records
            WHERE artifact_type = 'discovery_result'
              AND job_posting_id = ?
            """,
            (pipeline_run.job_posting_id,),
        ).fetchone()[0]
        if posting_row[0] == "requires_contacts":
            if pipeline_run.current_stage != "email_discovery":
                return (
                    "Email discovery should stay at email_discovery when "
                    f"posting_status=requires_contacts, but found {pipeline_run.current_stage!r}."
                )
            if pipeline_run.run_status == RUN_STATUS_ESCALATED:
                return None
            if discovery_artifact_count <= 0:
                return (
                    "Email discovery kept the run active without persisting a "
                    "discovery_result artifact."
                )
            return None
        if posting_row[0] == "ready_for_outreach":
            if pipeline_run.run_status != RUN_STATUS_IN_PROGRESS:
                return (
                    "Email discovery should remain in-progress when "
                    f"posting_status=ready_for_outreach, but found {pipeline_run.run_status!r}."
                )
            if pipeline_run.current_stage != "sending":
                return (
                    "Email discovery should advance to sending when "
                    f"posting_status=ready_for_outreach, but found {pipeline_run.current_stage!r}."
                )
            return None
        if posting_row[0] not in {"requires_contacts", "ready_for_outreach"}:
            return f"Email discovery persisted an unexpected posting status {posting_row[0]!r}."
        return None

    if catalog_entry.action_id == ACTION_RUN_ROLE_TARGETED_SENDING:
        if pipeline_run is None:
            return "Supervisor failed to load the selected pipeline_run after sending."
        if pipeline_run.pipeline_run_id != selected_work.work_id:
            return "Sending changed the selected pipeline_run identity."
        if pipeline_run.job_posting_id is None:
            return "Sending completed without a linked job_posting_id."
        posting_row = connection.execute(
            """
            SELECT posting_status
            FROM job_postings
            WHERE job_posting_id = ?
            """,
            (pipeline_run.job_posting_id,),
        ).fetchone()
        if posting_row is None:
            return "Sending completed without a persisted job_posting row."
        posting_status = posting_row[0]
        message_row_count = int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM outreach_messages
                WHERE job_posting_id = ?
                """,
                (pipeline_run.job_posting_id,),
            ).fetchone()[0]
            or 0
        )
        send_result_artifact_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM artifact_records
            WHERE artifact_type = 'send_result'
              AND job_posting_id = ?
            """,
            (pipeline_run.job_posting_id,),
        ).fetchone()[0]
        sent_message_count = _count_posting_outreach_messages_with_status(
            connection,
            job_posting_id=pipeline_run.job_posting_id,
            message_status="sent",
        )
        if message_row_count <= 0 or send_result_artifact_count <= 0:
            return (
                "Sending completed without persisting outreach messages and send_result "
                "artifacts for the selected posting."
            )
        if posting_status == "outreach_in_progress":
            if pipeline_run.run_status != RUN_STATUS_IN_PROGRESS:
                return (
                    "Sending left the pipeline_run outside in-progress state while later "
                    f"wave work remains; found {pipeline_run.run_status!r}."
                )
            if pipeline_run.current_stage != "sending":
                return (
                    "Sending should remain at the sending stage when the posting is still "
                    f"outreach_in_progress, but found {pipeline_run.current_stage!r}."
                )
            return None
        if posting_status == "completed":
            if sent_message_count > 0:
                if pipeline_run.run_status != RUN_STATUS_IN_PROGRESS:
                    return (
                        "Sending should hand off completed sent waves into delivery feedback "
                        f"without terminalizing the run; found {pipeline_run.run_status!r}."
                    )
                if pipeline_run.current_stage != "delivery_feedback":
                    return (
                        "Sending should advance to delivery_feedback after the terminal "
                        f"sent wave, but found {pipeline_run.current_stage!r}."
                    )
                return None
            if pipeline_run.run_status != RUN_STATUS_COMPLETED:
                return (
                    "Sending should complete the pipeline_run when the terminal wave "
                    f"contains no sent messages, but found {pipeline_run.run_status!r}."
                )
            if pipeline_run.current_stage != "completed":
                return (
                    "No-send blocked sending outcomes should complete the pipeline run at "
                    f"`completed`, but found {pipeline_run.current_stage!r}."
                )
            return None
        return f"Sending persisted an unexpected posting status {posting_status!r}."

    if catalog_entry.action_id == ACTION_RUN_ROLE_TARGETED_DELIVERY_FEEDBACK:
        if pipeline_run is None:
            return "Supervisor failed to load the selected pipeline_run after delivery feedback."
        if pipeline_run.pipeline_run_id != selected_work.work_id:
            return "Delivery feedback changed the selected pipeline_run identity."
        if pipeline_run.job_posting_id is None:
            return "Delivery feedback completed without a linked job_posting_id."
        posting_status = _load_posting_status(
            connection,
            job_posting_id=pipeline_run.job_posting_id,
        )
        if posting_status != "completed":
            return (
                "Delivery feedback should preserve the terminal completed posting status, "
                f"but found {posting_status!r}."
            )
        sent_message_ids = _list_posting_sent_outreach_message_ids(
            connection,
            job_posting_id=pipeline_run.job_posting_id,
        )
        if not sent_message_ids:
            return "Delivery feedback completed without any sent outreach messages."
        pending_feedback_message_ids = _list_posting_sent_outreach_message_ids_without_terminal_feedback(
            connection,
            job_posting_id=pipeline_run.job_posting_id,
        )
        if pending_feedback_message_ids:
            if pipeline_run.run_status != RUN_STATUS_IN_PROGRESS:
                return (
                    "Delivery feedback should keep the pipeline_run active while high-level "
                    f"feedback outcomes remain pending; found {pipeline_run.run_status!r}."
                )
            if pipeline_run.current_stage != "delivery_feedback":
                return (
                    "Delivery feedback should remain at the delivery_feedback stage while "
                    f"outcomes remain pending; found {pipeline_run.current_stage!r}."
                )
            return None
        if pipeline_run.run_status != RUN_STATUS_COMPLETED:
            return (
                "Delivery feedback should complete the pipeline_run once every sent "
                f"message has a high-level feedback outcome; found {pipeline_run.run_status!r}."
            )
        if pipeline_run.current_stage != "completed":
            return (
                "Completed delivery-feedback runs should end at `completed`, but found "
                f"{pipeline_run.current_stage!r}."
            )
        return None

    if catalog_entry.action_id == ACTION_RUN_GENERAL_LEARNING_EMAIL_DISCOVERY:
        contact_row = connection.execute(
            """
            SELECT current_working_email, contact_status
            FROM contacts
            WHERE contact_id = ?
            """,
            (selected_work.work_id,),
        ).fetchone()
        if contact_row is None:
            return "General-learning discovery removed the selected contact unexpectedly."
        artifact_count = int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM artifact_records
                WHERE artifact_type = 'discovery_result'
                  AND contact_id = ?
                  AND job_posting_id IS NULL
                """,
                (selected_work.work_id,),
            ).fetchone()[0]
            or 0
        )
        if artifact_count <= 0:
            return (
                "General-learning discovery completed without a persisted contact-rooted "
                "discovery_result artifact."
            )
        contact_status = _require_text(
            _optional_text(contact_row["contact_status"]),
            "contact_status",
        )
        if contact_status == "working_email_found":
            if not _optional_text(contact_row["current_working_email"]):
                return (
                    "General-learning discovery marked the contact as "
                    "`working_email_found` without persisting a usable email."
                )
            return None
        if contact_status == "identified":
            if _optional_text(contact_row["current_working_email"]):
                return (
                    "General-learning discovery left the contact at `identified` even "
                    "though a working email is now present."
                )
            return None
        if contact_status == "exhausted":
            if _optional_text(contact_row["current_working_email"]):
                return (
                    "General-learning discovery marked the contact exhausted while still "
                    "keeping a working email attached."
                )
            return None
        return (
            "General-learning discovery persisted an unexpected contact status "
            f"{contact_status!r}."
        )

    if catalog_entry.action_id == ACTION_RUN_GENERAL_LEARNING_OUTREACH:
        message_row = connection.execute(
            """
            SELECT outreach_message_id, outreach_mode, message_status, job_posting_id,
                   sent_at, thread_id, delivery_tracking_id
            FROM outreach_messages
            WHERE contact_id = ?
              AND outreach_mode = 'general_learning'
            ORDER BY created_at DESC, outreach_message_id DESC
            LIMIT 1
            """,
            (selected_work.work_id,),
        ).fetchone()
        if message_row is None:
            return (
                "Supervisor failed to persist a general-learning outreach message for the "
                "selected contact."
            )
        if message_row["job_posting_id"] is not None:
            return (
                "General-learning supervisor outreach should remain contact-rooted without "
                "introducing job_posting linkage."
            )
        if message_row["message_status"] not in {"sent", "blocked", "failed"}:
            return (
                "General-learning supervisor outreach must persist a terminal bounded "
                f"message outcome; found {message_row['message_status']!r}."
            )
        artifact_count = int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM artifact_records
                WHERE artifact_type = 'send_result'
                  AND contact_id = ?
                  AND outreach_message_id = ?
                """,
                (
                    selected_work.work_id,
                    message_row["outreach_message_id"],
                ),
            ).fetchone()[0]
            or 0
        )
        if artifact_count <= 0:
            return (
                "General-learning supervisor outreach completed without a persisted "
                "send_result artifact."
            )
        if message_row["message_status"] == "sent":
            contact_row = connection.execute(
                """
                SELECT contact_status
                FROM contacts
                WHERE contact_id = ?
                """,
                (selected_work.work_id,),
            ).fetchone()
            if contact_row is None:
                return "General-learning send removed the selected contact unexpectedly."
            if contact_row[0] != "sent":
                return (
                    "General-learning send should persist `contact_status = sent` after a "
                    f"successful send, but found {contact_row[0]!r}."
                )
            feedback_sync_row = connection.execute(
                """
                SELECT scheduler_name, scheduler_type, observation_scope, result
                FROM feedback_sync_runs
                ORDER BY started_at DESC, feedback_sync_run_id DESC
                LIMIT 1
                """
            ).fetchone()
            if feedback_sync_row is None:
                return (
                    "General-learning send should trigger an immediate feedback sync run "
                    "even when no mailbox observer is configured."
                )
            if dict(feedback_sync_row) != {
                "scheduler_name": "interactive_post_send",
                "scheduler_type": "interactive",
                "observation_scope": "immediate_post_send",
                "result": "success",
            }:
                return (
                    "General-learning send did not persist the expected immediate feedback "
                    f"sync metadata; found {dict(feedback_sync_row)!r}."
                )
        return None

    if catalog_entry.action_id == ACTION_RUN_GENERAL_LEARNING_DELIVERY_FEEDBACK:
        message_ids = _list_contact_rooted_general_learning_sent_outreach_message_ids(
            connection,
            contact_id=selected_work.work_id,
        )
        if not message_ids:
            return (
                "General-learning delayed feedback completed without any sent "
                "general-learning outreach messages for the selected contact."
            )
        message_row = connection.execute(
            """
            SELECT DISTINCT job_posting_id
            FROM outreach_messages
            WHERE contact_id = ?
              AND outreach_mode = 'general_learning'
              AND message_status = 'sent'
            """,
            (selected_work.work_id,),
        ).fetchone()
        if message_row is not None and message_row[0] is not None:
            return (
                "General-learning delayed feedback should remain contact-rooted "
                "without introducing job_posting linkage."
            )
        return None

    if catalog_entry.action_id == ACTION_RUN_DAILY_MAINTENANCE:
        if maintenance_batch_id is None:
            return "Supervisor failed to persist a maintenance_change_batch for the selected cycle."
        batch = get_maintenance_batch(connection, maintenance_batch_id)
        if batch is None:
            return (
                "Supervisor completed maintenance without a persisted "
                f"maintenance_change_batch row for {maintenance_batch_id!r}."
            )
        if batch.status not in {"validated", "retained_for_review"}:
            return (
                "Maintenance completed with an unsupported batch status "
                f"{batch.status!r}."
            )
        if batch.approval_outcome not in {"pending", "failed_validation"}:
            return (
                "Maintenance completed with an unsupported approval outcome "
                f"{batch.approval_outcome!r}."
            )
        json_path = paths.resolve_from_root(batch.json_path)
        markdown_path = paths.resolve_from_root(batch.summary_path)
        if not json_path.exists():
            return (
                "Maintenance completed without a persisted maintenance_change.json artifact "
                f"at {batch.json_path!r}."
            )
        if not markdown_path.exists():
            return (
                "Maintenance completed without a persisted maintenance_change.md artifact "
                f"at {batch.summary_path!r}."
            )
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return (
                "Maintenance completed with a malformed machine-readable artifact "
                f"at {batch.json_path!r}."
            )
        if payload.get("maintenance_change_batch_id") != maintenance_batch_id:
            return (
                "Maintenance artifact recorded the wrong maintenance_change_batch_id: "
                f"{payload.get('maintenance_change_batch_id')!r}."
            )
        if payload.get("local_day") != selected_work.work_id:
            return (
                "Maintenance artifact recorded the wrong local_day for the selected "
                f"maintenance cycle: {payload.get('local_day')!r}."
            )
        if payload.get("status") != batch.status:
            return (
                "Maintenance artifact status does not match the persisted batch row: "
                f"artifact={payload.get('status')!r}, row={batch.status!r}."
            )
        if payload.get("approval_outcome") != batch.approval_outcome:
            return (
                "Maintenance artifact approval outcome does not match the persisted "
                f"batch row: artifact={payload.get('approval_outcome')!r}, row={batch.approval_outcome!r}."
            )
        if not _optional_text(payload.get("head_commit_sha")):
            return "Maintenance completed without a head_commit_sha in maintenance_change.json."
        if not str(payload.get("branch_name") or "").startswith("maintenance/"):
            return (
                "Maintenance completed with a branch_name outside the maintenance/ "
                f"namespace: {payload.get('branch_name')!r}."
            )
        if payload.get("merged_commit_sha") is not None:
            return "Fresh maintenance batches must not record merged_commit_sha before approval."
        if payload.get("merge_commit_message") is not None:
            return (
                "Fresh maintenance batches must not record merge_commit_message before explicit approval."
            )
        if batch.approval_outcome == "pending" and batch.status != "validated":
            return (
                "Maintenance batches awaiting approval must stay at status "
                f"'validated'; found {batch.status!r}."
            )
        if (
            batch.approval_outcome == "failed_validation"
            and batch.status != "retained_for_review"
        ):
            return (
                "Maintenance batches that fail validation must be retained for review; "
                f"found status {batch.status!r}."
            )
        return None

    if catalog_entry.action_id == ACTION_ESCALATE_OPEN_INCIDENT:
        if incident is None:
            return "Supervisor failed to load the escalated incident result."
        persisted = get_agent_incident(connection, incident.agent_incident_id)
        if persisted is None or persisted.status != INCIDENT_STATUS_ESCALATED:
            return "Selected incident was not persisted as escalated."
        return None

    return f"Catalog action {catalog_entry.action_id!r} has no postcondition validator."


def _record_progression_failure(
    connection: sqlite3.Connection,
    selected_work: SupervisorWorkUnit,
    *,
    summary: str,
    incident_type: str,
    severity: str,
    timestamp: str,
) -> tuple[AgentIncidentRecord, PipelineRunRecord | None]:
    incident = create_agent_incident(
        connection,
        incident_type=incident_type,
        severity=severity,
        summary=summary,
        pipeline_run_id=selected_work.pipeline_run_id,
        lead_id=selected_work.lead_id,
        job_posting_id=selected_work.job_posting_id,
        created_at=timestamp,
    )
    pipeline_run: PipelineRunRecord | None = None
    if selected_work.pipeline_run_id is not None:
        current_run = _require_pipeline_run(connection, selected_work.pipeline_run_id)
        if not current_run.is_terminal:
            pipeline_run = escalate_pipeline_run(
                connection,
                current_run.pipeline_run_id,
                current_stage=current_run.current_stage,
                error_summary=summary,
                run_summary=(
                    "Supervisor escalated the pipeline run after blocked bounded progression."
                ),
                timestamp=timestamp,
            )
        else:
            pipeline_run = current_run
    return incident, pipeline_run


def _ensure_review_packet_for_terminal_run(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    pipeline_run: PipelineRunRecord | None,
    *,
    created_at: str,
) -> ExpertReviewPacketRecord | None:
    if pipeline_run is None or pipeline_run.run_status not in REVIEW_WORTHY_RUN_STATUSES:
        return None
    return generate_expert_review_packet(
        connection,
        paths,
        pipeline_run.pipeline_run_id,
        created_at=created_at,
    )


def _build_review_packet_payload(
    connection: sqlite3.Connection,
    pipeline_run: PipelineRunRecord,
    *,
    generated_at: str,
    recommended_expert_actions: list[str] | tuple[str, ...] | None = None,
) -> dict[str, object]:
    posting_row = None
    target_contacts_selected = 0
    emails_found = 0
    sends_attempted = 0
    sends_completed = 0
    if pipeline_run.job_posting_id:
        posting_row = connection.execute(
            """
            SELECT company_name, role_title
            FROM job_postings
            WHERE job_posting_id = ?
            """,
            (pipeline_run.job_posting_id,),
        ).fetchone()
        counts = connection.execute(
            """
            SELECT
              (SELECT COUNT(*)
               FROM job_posting_contacts
               WHERE job_posting_id = ?) AS target_contacts_selected,
              (SELECT COUNT(*)
               FROM job_posting_contacts jpc
               JOIN contacts c
                 ON c.contact_id = jpc.contact_id
               WHERE jpc.job_posting_id = ?
                 AND c.current_working_email IS NOT NULL
                 AND TRIM(c.current_working_email) <> '') AS emails_found,
              (SELECT COUNT(*)
               FROM outreach_messages
               WHERE job_posting_id = ?) AS sends_attempted,
              (SELECT COUNT(*)
               FROM outreach_messages
               WHERE job_posting_id = ?
                 AND sent_at IS NOT NULL) AS sends_completed
            """,
            (
                pipeline_run.job_posting_id,
                pipeline_run.job_posting_id,
                pipeline_run.job_posting_id,
                pipeline_run.job_posting_id,
            ),
        ).fetchone()
        target_contacts_selected = int(counts[0] or 0)
        emails_found = int(counts[1] or 0)
        sends_attempted = int(counts[2] or 0)
        sends_completed = int(counts[3] or 0)

    incidents = [
        {
            "agent_incident_id": incident.agent_incident_id,
            "incident_type": incident.incident_type,
            "severity": incident.severity,
            "status": incident.status,
            "summary": incident.summary,
            "escalation_reason": incident.escalation_reason,
            "repair_attempt_summary": incident.repair_attempt_summary,
            "created_at": incident.created_at,
            "updated_at": incident.updated_at,
        }
        for incident in _list_incidents_for_pipeline_run(connection, pipeline_run.pipeline_run_id)
    ]
    repairs_attempted = [
        incident["repair_attempt_summary"]
        for incident in incidents
        if incident["repair_attempt_summary"]
    ]

    return {
        "pipeline_run_id": pipeline_run.pipeline_run_id,
        "job_posting_id": pipeline_run.job_posting_id,
        "lead_id": pipeline_run.lead_id,
        "generated_at": generated_at,
        "run_outcome": pipeline_run.run_status,
        "run_status": pipeline_run.run_status,
        "current_stage": pipeline_run.current_stage,
        "run_summary": pipeline_run.run_summary,
        "last_error_summary": pipeline_run.last_error_summary,
        "started_at": pipeline_run.started_at,
        "completed_at": pipeline_run.completed_at,
        "company_name": _optional_text(posting_row[0]) if posting_row is not None else None,
        "role_title": _optional_text(posting_row[1]) if posting_row is not None else None,
        "stages_completed": [pipeline_run.current_stage] if pipeline_run.current_stage else [],
        "target_contacts_selected": target_contacts_selected,
        "emails_found": emails_found,
        "emails_not_found": max(0, target_contacts_selected - emails_found),
        "sends_attempted": sends_attempted,
        "sends_completed": sends_completed,
        "incidents": incidents,
        "retries_or_repairs_attempted": repairs_attempted,
        "recommended_expert_actions": list(
            recommended_expert_actions
            if recommended_expert_actions is not None
            else _default_recommended_expert_actions(pipeline_run, incidents)
        ),
    }


def _list_incidents_for_pipeline_run(
    connection: sqlite3.Connection,
    pipeline_run_id: str,
) -> list[AgentIncidentRecord]:
    rows = connection.execute(
        """
        SELECT agent_incident_id, incident_type, severity, status, summary,
               pipeline_run_id, lead_id, job_posting_id, contact_id,
               outreach_message_id, resolved_at, escalation_reason,
               repair_attempt_summary, created_at, updated_at, NULL
        FROM agent_incidents
        WHERE pipeline_run_id = ?
        ORDER BY created_at ASC, agent_incident_id ASC
        """,
        (pipeline_run_id,),
    ).fetchall()
    return [_agent_incident_from_row(row) for row in rows]


def _default_recommended_expert_actions(
    pipeline_run: PipelineRunRecord,
    incidents: list[dict[str, object]],
) -> list[str]:
    actions: list[str] = []
    if pipeline_run.run_status == RUN_STATUS_COMPLETED:
        actions.append(
            "Review the completed run outcome and capture any corrections or future guidance."
        )
    if pipeline_run.run_status == RUN_STATUS_FAILED:
        actions.append(
            "Inspect the terminal failure and decide whether the posting needs repair or a fresh retry."
        )
    if pipeline_run.run_status == RUN_STATUS_ESCALATED:
        actions.append(
            "Review the escalation condition and decide whether to resume the same run or start a fresh attempt later."
        )
    if incidents:
        actions.append(
            "Inspect the linked incidents and resolve or suppress any blockers before autonomous progression resumes."
        )
    if pipeline_run.run_status in {RUN_STATUS_FAILED, RUN_STATUS_ESCALATED}:
        actions.append(
            "Decide whether an explicit override or policy correction is required for the affected object state."
        )
    return actions


def _render_review_packet_markdown(packet_payload: dict[str, object]) -> str:
    lines = [
        "# Expert Review Packet",
        "",
        f"- Pipeline run: `{packet_payload['pipeline_run_id']}`",
        f"- Outcome: `{packet_payload['run_outcome']}`",
        f"- Current stage: `{packet_payload['current_stage']}`",
        f"- Job posting: `{packet_payload.get('job_posting_id') or 'n/a'}`",
        f"- Generated at: `{packet_payload['generated_at']}`",
    ]
    company_name = packet_payload.get("company_name")
    role_title = packet_payload.get("role_title")
    if company_name or role_title:
        lines.append(
            f"- Posting label: {company_name or 'Unknown company'} / {role_title or 'Unknown role'}"
        )
    if packet_payload.get("run_summary"):
        lines.append(f"- Run summary: {packet_payload['run_summary']}")
    if packet_payload.get("last_error_summary"):
        lines.append(f"- Error summary: {packet_payload['last_error_summary']}")

    lines.extend(
        [
            "",
            "## Coverage",
            "",
            f"- Contacts selected: {packet_payload['target_contacts_selected']}",
            f"- Emails found: {packet_payload['emails_found']}",
            f"- Emails not found: {packet_payload['emails_not_found']}",
            f"- Sends attempted: {packet_payload['sends_attempted']}",
            f"- Sends completed: {packet_payload['sends_completed']}",
        ]
    )

    incidents = packet_payload.get("incidents") or []
    lines.extend(["", "## Incidents", ""])
    if incidents:
        for incident in incidents:
            lines.append(
                f"- [{incident['severity']}] {incident['incident_type']}: {incident['summary']}"
            )
    else:
        lines.append("- No linked incidents were recorded for this run.")

    repairs_attempted = packet_payload.get("retries_or_repairs_attempted") or []
    lines.extend(["", "## Retries Or Repairs", ""])
    if repairs_attempted:
        for repair in repairs_attempted:
            lines.append(f"- {repair}")
    else:
        lines.append("- No bounded retries or repairs were recorded.")

    recommended_actions = packet_payload.get("recommended_expert_actions") or []
    lines.extend(["", "## Recommended Expert Actions", ""])
    for action in recommended_actions:
        lines.append(f"- {action}")

    return "\n".join(lines) + "\n"


def _review_packet_summary_excerpt(packet_payload: dict[str, object]) -> str:
    summary = (
        _optional_text(packet_payload.get("run_summary"))
        or _optional_text(packet_payload.get("last_error_summary"))
        or (
            f"Run {packet_payload['pipeline_run_id']} reached {packet_payload['run_outcome']} "
            f"at {packet_payload['current_stage']}."
        )
    )
    return summary[:280]


def _update_expert_review_packet_status(
    connection: sqlite3.Connection,
    expert_review_packet_id: str,
    *,
    packet_status: str,
    reviewed_at: str | None | object = _UNSET,
) -> ExpertReviewPacketRecord:
    if packet_status not in EXPERT_REVIEW_PACKET_STATUSES:
        raise SupervisorStateError(f"Unsupported expert packet status={packet_status!r}.")
    packet = _require_expert_review_packet(connection, expert_review_packet_id)
    allowed = EXPERT_REVIEW_PACKET_TRANSITIONS[packet.packet_status]
    if packet_status not in allowed:
        raise InvalidLifecycleTransition(
            f"Cannot transition expert_review_packet from {packet.packet_status!r} "
            f"to {packet_status!r}."
        )

    fields: dict[str, str | None] = {"packet_status": packet_status}
    if reviewed_at is not _UNSET:
        fields["reviewed_at"] = reviewed_at

    assignments = ", ".join(f"{field_name} = ?" for field_name in fields)
    values = [fields[field_name] for field_name in fields]
    values.append(expert_review_packet_id)
    with connection:
        connection.execute(
            f"UPDATE expert_review_packets SET {assignments} WHERE expert_review_packet_id = ?",
            values,
        )
    return _require_expert_review_packet(connection, expert_review_packet_id)


def _write_context_snapshot(
    paths: ProjectPaths,
    supervisor_cycle_id: str,
    snapshot_payload: dict[str, object],
) -> str:
    snapshot_path = (
        paths.project_root
        / "ops"
        / "agent"
        / "context-snapshots"
        / supervisor_cycle_id
        / "context_snapshot.json"
    )
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(
        json.dumps(snapshot_payload, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    return paths.relative_to_root(snapshot_path).as_posix()


def _catalog_entry_snapshot(
    catalog_entry: SupervisorActionCatalogEntry,
) -> dict[str, object]:
    return {
        "action_id": catalog_entry.action_id,
        "work_type": catalog_entry.work_type,
        "description": catalog_entry.description,
        "prerequisites": list(catalog_entry.prerequisites),
        "expected_outputs": list(catalog_entry.expected_outputs),
        "validation_references": list(catalog_entry.validation_references),
    }


def _maintenance_batch_snapshot(
    connection: sqlite3.Connection,
    maintenance_batch_id: str,
) -> dict[str, object] | None:
    batch = get_maintenance_batch(connection, maintenance_batch_id)
    if batch is None:
        return None
    return {
        "maintenance_change_batch_id": batch.maintenance_change_batch_id,
        "branch_name": batch.branch_name,
        "scope_slug": batch.scope_slug,
        "status": batch.status,
        "approval_outcome": batch.approval_outcome,
        "summary_path": batch.summary_path,
        "json_path": batch.json_path,
        "head_commit_sha": batch.head_commit_sha,
        "merged_commit_sha": batch.merged_commit_sha,
        "merge_commit_message": batch.merge_commit_message,
        "validated_at": batch.validated_at,
        "approved_at": batch.approved_at,
        "merged_at": batch.merged_at,
        "failed_at": batch.failed_at,
        "validation_summary": batch.validation_summary,
        "expert_review_packet_id": batch.expert_review_packet_id,
        "created_at": batch.created_at,
    }


def _count_posting_contacts_with_link_status(
    connection: sqlite3.Connection,
    *,
    job_posting_id: str,
    link_level_status: str,
) -> int:
    return int(
        connection.execute(
            """
            SELECT COUNT(*)
            FROM job_posting_contacts
            WHERE job_posting_id = ?
              AND link_level_status = ?
            """,
            (job_posting_id, link_level_status),
        ).fetchone()[0]
        or 0
    )


def _count_posting_outreach_messages_with_status(
    connection: sqlite3.Connection,
    *,
    job_posting_id: str,
    message_status: str,
) -> int:
    return int(
        connection.execute(
            """
            SELECT COUNT(*)
            FROM outreach_messages
            WHERE job_posting_id = ?
              AND message_status = ?
            """,
            (job_posting_id, message_status),
        ).fetchone()[0]
        or 0
    )


def _list_posting_sent_outreach_message_ids(
    connection: sqlite3.Connection,
    *,
    job_posting_id: str,
) -> list[str]:
    rows = connection.execute(
        """
        SELECT outreach_message_id
        FROM outreach_messages
        WHERE job_posting_id = ?
          AND message_status = 'sent'
        ORDER BY sent_at ASC, outreach_message_id ASC
        """,
        (job_posting_id,),
    ).fetchall()
    return [str(row[0]) for row in rows]


def _list_posting_sent_outreach_message_ids_without_terminal_feedback(
    connection: sqlite3.Connection,
    *,
    job_posting_id: str,
) -> list[str]:
    terminal_placeholders = ", ".join(
        "?" for _ in TERMINAL_DELIVERY_FEEDBACK_EVENT_STATES
    )
    rows = connection.execute(
        f"""
        SELECT om.outreach_message_id
        FROM outreach_messages om
        WHERE om.job_posting_id = ?
          AND om.message_status = 'sent'
          AND NOT EXISTS (
            SELECT 1
            FROM delivery_feedback_events dfe
            WHERE dfe.outreach_message_id = om.outreach_message_id
              AND dfe.event_state IN ({terminal_placeholders})
          )
        ORDER BY om.sent_at ASC, om.outreach_message_id ASC
        """,
        (
            job_posting_id,
            *sorted(TERMINAL_DELIVERY_FEEDBACK_EVENT_STATES),
        ),
    ).fetchall()
    return [str(row[0]) for row in rows]


def _list_contact_rooted_general_learning_sent_outreach_message_ids(
    connection: sqlite3.Connection,
    *,
    contact_id: str,
) -> list[str]:
    rows = connection.execute(
        """
        SELECT outreach_message_id
        FROM outreach_messages
        WHERE contact_id = ?
          AND outreach_mode = 'general_learning'
          AND job_posting_id IS NULL
          AND message_status = 'sent'
        ORDER BY sent_at ASC, outreach_message_id ASC
        """,
        (contact_id,),
    ).fetchall()
    return [str(row[0]) for row in rows]


def _list_contact_rooted_general_learning_sent_outreach_message_ids_without_terminal_feedback(
    connection: sqlite3.Connection,
    *,
    contact_id: str,
) -> list[str]:
    terminal_placeholders = ", ".join(
        "?" for _ in TERMINAL_DELIVERY_FEEDBACK_EVENT_STATES
    )
    rows = connection.execute(
        f"""
        SELECT om.outreach_message_id
        FROM outreach_messages om
        WHERE om.contact_id = ?
          AND om.outreach_mode = 'general_learning'
          AND om.job_posting_id IS NULL
          AND om.message_status = 'sent'
          AND NOT EXISTS (
            SELECT 1
            FROM delivery_feedback_events dfe
            WHERE dfe.outreach_message_id = om.outreach_message_id
              AND dfe.event_state IN ({terminal_placeholders})
          )
        ORDER BY om.sent_at ASC, om.outreach_message_id ASC
        """,
        (
            contact_id,
            *sorted(TERMINAL_DELIVERY_FEEDBACK_EVENT_STATES),
        ),
    ).fetchall()
    return [str(row[0]) for row in rows]


def _load_posting_status(
    connection: sqlite3.Connection,
    *,
    job_posting_id: str,
) -> str:
    row = connection.execute(
        """
        SELECT posting_status
        FROM job_postings
        WHERE job_posting_id = ?
        """,
        (job_posting_id,),
    ).fetchone()
    if row is None:
        raise SupervisorStateError(f"job_posting {job_posting_id!r} no longer exists.")
    return _require_text(_optional_text(row[0]), "posting_status")


def _require_dependency(value: object | None, message: str) -> object:
    if value is None:
        raise SupervisorStateError(message)
    return value


def _unsupported_work_summary(selected_work: SupervisorWorkUnit) -> str:
    if selected_work.work_type == WORK_TYPE_PIPELINE_RUN and selected_work.current_stage:
        return (
            "No registered bounded supervisor action covers pipeline stage "
            f"{selected_work.current_stage!r} yet."
        )
    return (
        "No registered bounded supervisor action covers selected work "
        f"{selected_work.work_type!r}:{selected_work.work_id!r}."
    )


def _incident_cluster_key(incident: AgentIncidentRecord) -> str:
    stage_scope = incident.current_stage or "operational"
    return f"{incident.incident_type}:{stage_scope}"


def _require_text(value: str | None, field_name: str) -> str:
    if value is None or not value.strip():
        raise SupervisorStateError(f"{field_name} is required.")
    return value


def _ensure_control_defaults(
    connection: sqlite3.Connection,
    *,
    timestamp: str | None = None,
) -> None:
    current_timestamp = timestamp or now_utc_iso()
    existing_keys = {
        row[0]
        for row in connection.execute(
            "SELECT control_key FROM agent_control_state WHERE control_key IN ({})".format(
                ",".join("?" for _ in CONTROL_DEFAULTS)
            ),
            tuple(CONTROL_DEFAULTS.keys()),
        ).fetchall()
    }
    missing_rows = [
        (control_key, control_value, current_timestamp)
        for control_key, control_value in CONTROL_DEFAULTS.items()
        if control_key not in existing_keys
    ]
    if not missing_rows:
        return
    with connection:
        connection.executemany(
            """
            INSERT INTO agent_control_state (control_key, control_value, updated_at)
            VALUES (?, ?, ?)
            """,
            missing_rows,
        )


def _update_pipeline_run(
    connection: sqlite3.Connection,
    pipeline_run_id: str,
    *,
    new_status: str | None = None,
    current_stage: str | None = None,
    review_packet_status: str | None = None,
    completed_at: str | None | object = _UNSET,
    last_error_summary: str | None | object = _UNSET,
    run_summary: str | None | object = _UNSET,
    timestamp: str | None = None,
) -> PipelineRunRecord:
    current = _require_pipeline_run(connection, pipeline_run_id)
    current_timestamp = timestamp or now_utc_iso()
    fields: dict[str, str | None] = {"updated_at": current_timestamp}

    if new_status is not None:
        if new_status not in RUN_STATUSES:
            raise SupervisorStateError(f"Unsupported run_status={new_status!r}.")
        _validate_run_status_transition(current.run_status, new_status)
        fields["run_status"] = new_status

    if current_stage is not None:
        if not current_stage.strip():
            raise SupervisorStateError("current_stage must not be blank.")
        fields["current_stage"] = current_stage

    if review_packet_status is not None:
        if review_packet_status not in REVIEW_PACKET_STATUSES:
            raise SupervisorStateError(
                f"Unsupported review_packet_status={review_packet_status!r}."
            )
        current_review_status = current.review_packet_status or REVIEW_PACKET_STATUS_NOT_READY
        allowed_review_states = REVIEW_PACKET_TRANSITIONS[current_review_status]
        if review_packet_status not in allowed_review_states:
            raise InvalidLifecycleTransition(
                f"Cannot transition review_packet_status from {current_review_status!r} "
                f"to {review_packet_status!r}."
            )
        fields["review_packet_status"] = review_packet_status

    if completed_at is not _UNSET:
        fields["completed_at"] = completed_at
    if last_error_summary is not _UNSET:
        fields["last_error_summary"] = last_error_summary
    if run_summary is not _UNSET:
        fields["run_summary"] = run_summary

    assignments = ", ".join(f"{field_name} = ?" for field_name in fields)
    values = [fields[field_name] for field_name in fields]
    values.append(pipeline_run_id)
    with connection:
        connection.execute(
            f"UPDATE pipeline_runs SET {assignments} WHERE pipeline_run_id = ?",
            values,
        )
    return _require_pipeline_run(connection, pipeline_run_id)


def _validate_run_status_transition(current_status: str, new_status: str) -> None:
    if current_status == new_status:
        return
    if current_status == RUN_STATUS_IN_PROGRESS:
        if new_status in {RUN_STATUS_PAUSED, RUN_STATUS_ESCALATED, RUN_STATUS_FAILED, RUN_STATUS_COMPLETED}:
            return
    if current_status == RUN_STATUS_PAUSED:
        if new_status in {RUN_STATUS_IN_PROGRESS, RUN_STATUS_ESCALATED, RUN_STATUS_FAILED, RUN_STATUS_COMPLETED}:
            return
    if current_status == RUN_STATUS_ESCALATED:
        if new_status == RUN_STATUS_IN_PROGRESS:
            return
    raise InvalidLifecycleTransition(
        f"Cannot transition pipeline_run from {current_status!r} to {new_status!r}."
    )


def _require_pipeline_run(
    connection: sqlite3.Connection,
    pipeline_run_id: str,
) -> PipelineRunRecord:
    run = get_pipeline_run(connection, pipeline_run_id)
    if run is None:
        raise SupervisorStateError(f"pipeline_run {pipeline_run_id!r} does not exist.")
    return run


def _require_supervisor_cycle(
    connection: sqlite3.Connection,
    supervisor_cycle_id: str,
) -> SupervisorCycleRecord:
    cycle = get_supervisor_cycle(connection, supervisor_cycle_id)
    if cycle is None:
        raise SupervisorStateError(
            f"supervisor_cycle {supervisor_cycle_id!r} does not exist."
        )
    return cycle


def _require_runtime_lease(
    connection: sqlite3.Connection,
    lease_name: str,
) -> LeaseRecord:
    lease = get_runtime_lease(connection, lease_name)
    if lease is None:
        raise SupervisorStateError(f"Lease {lease_name!r} does not exist.")
    return lease


def _require_agent_incident(
    connection: sqlite3.Connection,
    agent_incident_id: str,
) -> AgentIncidentRecord:
    incident = get_agent_incident(connection, agent_incident_id)
    if incident is None:
        raise SupervisorStateError(f"agent_incident {agent_incident_id!r} does not exist.")
    return incident


def _require_expert_review_packet(
    connection: sqlite3.Connection,
    expert_review_packet_id: str,
) -> ExpertReviewPacketRecord:
    packet = get_expert_review_packet(connection, expert_review_packet_id)
    if packet is None:
        raise SupervisorStateError(
            f"expert_review_packet {expert_review_packet_id!r} does not exist."
        )
    return packet


def _pipeline_run_from_row(row: sqlite3.Row | tuple[object, ...]) -> PipelineRunRecord:
    return PipelineRunRecord(
        pipeline_run_id=row[0],
        run_scope_type=row[1],
        run_status=row[2],
        current_stage=row[3],
        lead_id=_optional_text(row[4]),
        job_posting_id=_optional_text(row[5]),
        completed_at=_optional_text(row[6]),
        last_error_summary=_optional_text(row[7]),
        review_packet_status=_optional_text(row[8]),
        run_summary=_optional_text(row[9]),
        started_at=row[10],
        created_at=row[11],
        updated_at=row[12],
    )


def _supervisor_cycle_from_row(row: sqlite3.Row | tuple[object, ...]) -> SupervisorCycleRecord:
    return SupervisorCycleRecord(
        supervisor_cycle_id=row[0],
        trigger_type=row[1],
        scheduler_name=_optional_text(row[2]),
        selected_work_type=_optional_text(row[3]),
        selected_work_id=_optional_text(row[4]),
        pipeline_run_id=_optional_text(row[5]),
        context_snapshot_path=_optional_text(row[6]),
        sleep_wake_detection_method=_optional_text(row[7]),
        sleep_wake_event_ref=_optional_text(row[8]),
        started_at=row[9],
        completed_at=_optional_text(row[10]),
        result=row[11],
        error_summary=_optional_text(row[12]),
        created_at=row[13],
    )


def _lease_from_row(row: sqlite3.Row | tuple[object, ...]) -> LeaseRecord:
    return LeaseRecord(
        lease_name=row[0],
        lease_owner_id=row[1],
        acquired_at=row[2],
        expires_at=row[3],
        last_renewed_at=_optional_text(row[4]),
        lease_note=_optional_text(row[5]),
    )


def _agent_incident_from_row(row: sqlite3.Row | tuple[object, ...]) -> AgentIncidentRecord:
    return AgentIncidentRecord(
        agent_incident_id=row[0],
        incident_type=row[1],
        severity=row[2],
        status=row[3],
        summary=row[4],
        pipeline_run_id=_optional_text(row[5]),
        lead_id=_optional_text(row[6]),
        job_posting_id=_optional_text(row[7]),
        contact_id=_optional_text(row[8]),
        outreach_message_id=_optional_text(row[9]),
        resolved_at=_optional_text(row[10]),
        escalation_reason=_optional_text(row[11]),
        repair_attempt_summary=_optional_text(row[12]),
        created_at=row[13],
        updated_at=row[14],
        current_stage=_optional_text(row[15]) if len(row) > 15 else None,
    )


def _expert_review_packet_from_row(
    row: sqlite3.Row | tuple[object, ...],
) -> ExpertReviewPacketRecord:
    return ExpertReviewPacketRecord(
        expert_review_packet_id=row[0],
        pipeline_run_id=row[1],
        packet_status=row[2],
        packet_path=row[3],
        job_posting_id=_optional_text(row[4]),
        reviewed_at=_optional_text(row[5]),
        summary_excerpt=_optional_text(row[6]),
        created_at=row[7],
    )


def _expert_review_decision_from_row(
    row: sqlite3.Row | tuple[object, ...],
) -> ExpertReviewDecisionRecord:
    return ExpertReviewDecisionRecord(
        expert_review_decision_id=row[0],
        expert_review_packet_id=row[1],
        decision_type=row[2],
        decision_notes=_optional_text(row[3]),
        override_event_id=_optional_text(row[4]),
        decided_at=row[5],
        applied_at=_optional_text(row[6]),
    )


def _override_event_from_row(row: sqlite3.Row | tuple[object, ...]) -> OverrideEventRecord:
    return OverrideEventRecord(
        override_event_id=row[0],
        object_type=row[1],
        object_id=row[2],
        component_stage=row[3],
        previous_value=row[4],
        new_value=row[5],
        override_reason=row[6],
        override_timestamp=row[7],
        override_by=_optional_text(row[8]),
        lead_id=_optional_text(row[9]),
        job_posting_id=_optional_text(row[10]),
        contact_id=_optional_text(row[11]),
    )


def _normalize_control_value(value: str | bool | None) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    return str(value)


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _serialize_audit_value(value: object) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True)


def _timestamp_plus_seconds(timestamp: str, ttl_seconds: int) -> str:
    return _to_utc_iso(_parse_utc_iso(timestamp) + timedelta(seconds=ttl_seconds))


def _lease_is_expired(lease: LeaseRecord, now: str) -> bool:
    return _parse_utc_iso(lease.expires_at) <= _parse_utc_iso(now)


def _parse_utc_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _to_utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
