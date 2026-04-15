from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import unicodedata


def workspace_slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
    return slug or "unknown"


@dataclass(frozen=True)
class ProjectPaths:
    project_root: Path

    @classmethod
    def from_root(cls, project_root: Path | str | None = None) -> "ProjectPaths":
        root = Path(project_root) if project_root is not None else Path(__file__).resolve().parents[1]
        return cls(project_root=root.resolve())

    @property
    def spec_path(self) -> Path:
        return self.project_root / "prd" / "spec.md"

    @property
    def assets_dir(self) -> Path:
        return self.project_root / "assets"

    @property
    def tailoring_assets_dir(self) -> Path:
        return self.assets_dir / "resume-tailoring"

    @property
    def tailoring_base_dir(self) -> Path:
        return self.tailoring_assets_dir / "base"

    @property
    def projects_first_base_resume_path(self) -> Path:
        return self.tailoring_base_dir / "projects-first" / "base-resume.tex"

    @property
    def experience_first_base_resume_path(self) -> Path:
        return self.tailoring_base_dir / "experience-first" / "base-resume.tex"

    @property
    def secrets_dir(self) -> Path:
        return self.project_root / "secrets"

    @property
    def db_path(self) -> Path:
        return self.project_root / "job_hunt_copilot.db"

    @property
    def bin_dir(self) -> Path:
        return self.project_root / "bin"

    @property
    def scripts_dir(self) -> Path:
        return self.project_root / "scripts"

    @property
    def ops_scripts_dir(self) -> Path:
        return self.scripts_dir / "ops"

    @property
    def paste_dir(self) -> Path:
        return self.project_root / "paste"

    @property
    def paste_inbox_path(self) -> Path:
        return self.paste_dir / "paste.txt"

    @property
    def gmail_runtime_dir(self) -> Path:
        return self.project_root / "linkedin-scraping" / "runtime" / "gmail"

    @property
    def ops_dir(self) -> Path:
        return self.project_root / "ops"

    @property
    def ops_agent_dir(self) -> Path:
        return self.ops_dir / "agent"

    @property
    def ops_agent_identity_path(self) -> Path:
        return self.ops_agent_dir / "identity.yaml"

    @property
    def ops_agent_policies_path(self) -> Path:
        return self.ops_agent_dir / "policies.yaml"

    @property
    def ops_agent_action_catalog_path(self) -> Path:
        return self.ops_agent_dir / "action-catalog.yaml"

    @property
    def ops_agent_service_goals_path(self) -> Path:
        return self.ops_agent_dir / "service-goals.yaml"

    @property
    def ops_agent_escalation_policy_path(self) -> Path:
        return self.ops_agent_dir / "escalation-policy.yaml"

    @property
    def ops_agent_progress_log_path(self) -> Path:
        return self.ops_agent_dir / "progress-log.md"

    @property
    def ops_agent_ops_plan_path(self) -> Path:
        return self.ops_agent_dir / "ops-plan.yaml"

    @property
    def ops_agent_chat_bootstrap_path(self) -> Path:
        return self.ops_agent_dir / "chat-bootstrap.md"

    @property
    def ops_agent_chat_startup_path(self) -> Path:
        return self.ops_agent_dir / "chat-startup.md"

    @property
    def ops_agent_supervisor_bootstrap_path(self) -> Path:
        return self.ops_agent_dir / "supervisor-bootstrap.md"

    @property
    def ops_agent_context_snapshots_dir(self) -> Path:
        return self.ops_agent_dir / "context-snapshots"

    @property
    def ops_review_packets_dir(self) -> Path:
        return self.ops_dir / "review-packets"

    @property
    def ops_background_tasks_dir(self) -> Path:
        return self.ops_dir / "background-tasks"

    @property
    def ops_maintenance_dir(self) -> Path:
        return self.ops_dir / "maintenance"

    def maintenance_batch_dir(self, maintenance_change_batch_id: str) -> Path:
        return self.ops_maintenance_dir / maintenance_change_batch_id

    def maintenance_change_json_path(self, maintenance_change_batch_id: str) -> Path:
        return self.maintenance_batch_dir(maintenance_change_batch_id) / "maintenance_change.json"

    def maintenance_change_markdown_path(self, maintenance_change_batch_id: str) -> Path:
        return self.maintenance_batch_dir(maintenance_change_batch_id) / "maintenance_change.md"

    @property
    def ops_incidents_dir(self) -> Path:
        return self.ops_dir / "incidents"

    @property
    def ops_logs_dir(self) -> Path:
        return self.ops_dir / "logs"

    @property
    def ops_launchd_dir(self) -> Path:
        return self.ops_dir / "launchd"

    @property
    def supervisor_plist_path(self) -> Path:
        return self.ops_launchd_dir / "job-hunt-copilot-supervisor.plist"

    @property
    def feedback_sync_plist_path(self) -> Path:
        return self.ops_launchd_dir / "job-hunt-copilot-feedback-sync.plist"

    @property
    def supervisor_stdout_log_path(self) -> Path:
        return self.ops_logs_dir / "supervisor.stdout.log"

    @property
    def supervisor_stderr_log_path(self) -> Path:
        return self.ops_logs_dir / "supervisor.stderr.log"

    @property
    def feedback_sync_stdout_log_path(self) -> Path:
        return self.ops_logs_dir / "feedback-sync.stdout.log"

    @property
    def feedback_sync_stderr_log_path(self) -> Path:
        return self.ops_logs_dir / "feedback-sync.stderr.log"

    @property
    def chat_sessions_log_path(self) -> Path:
        return self.ops_logs_dir / "chat-sessions.jsonl"

    @property
    def build_runtime_pack_script_path(self) -> Path:
        return self.ops_scripts_dir / "build_runtime_pack.py"

    @property
    def materialize_supervisor_plist_script_path(self) -> Path:
        return self.ops_scripts_dir / "materialize_supervisor_plist.py"

    @property
    def materialize_feedback_sync_plist_script_path(self) -> Path:
        return self.ops_scripts_dir / "materialize_feedback_sync_plist.py"

    @property
    def control_agent_script_path(self) -> Path:
        return self.ops_scripts_dir / "control_agent.py"

    @property
    def run_supervisor_cycle_script_path(self) -> Path:
        return self.ops_scripts_dir / "run_supervisor_cycle.py"

    @property
    def run_feedback_sync_script_path(self) -> Path:
        return self.ops_scripts_dir / "run_feedback_sync.py"

    @property
    def chat_session_script_path(self) -> Path:
        return self.ops_scripts_dir / "chat_session.py"

    @property
    def agent_start_entrypoint_path(self) -> Path:
        return self.bin_dir / "jhc-agent-start"

    @property
    def agent_stop_entrypoint_path(self) -> Path:
        return self.bin_dir / "jhc-agent-stop"

    @property
    def agent_cycle_entrypoint_path(self) -> Path:
        return self.bin_dir / "jhc-agent-cycle"

    @property
    def feedback_sync_cycle_entrypoint_path(self) -> Path:
        return self.bin_dir / "jhc-feedback-sync-cycle"

    @property
    def chat_entrypoint_path(self) -> Path:
        return self.bin_dir / "jhc-chat"

    def relative_to_root(self, path: Path | str) -> Path:
        candidate = Path(path)
        absolute = candidate if candidate.is_absolute() else self.project_root / candidate
        resolved = absolute.resolve()
        try:
            return resolved.relative_to(self.project_root)
        except ValueError as exc:
            raise ValueError(
                f"Path must stay within the project root: {absolute}"
            ) from exc

    def resolve_from_root(self, path: Path | str) -> Path:
        candidate = Path(path)
        return candidate.resolve() if candidate.is_absolute() else (self.project_root / candidate).resolve()

    def lead_workspace_dir(self, company_name: str, role_title: str, lead_id: str) -> Path:
        return (
            self.project_root
            / "linkedin-scraping"
            / "runtime"
            / "leads"
            / workspace_slug(company_name)
            / workspace_slug(role_title)
            / lead_id
        )

    def lead_raw_dir(self, company_name: str, role_title: str, lead_id: str) -> Path:
        return self.lead_workspace_dir(company_name, role_title, lead_id) / "raw"

    def lead_raw_source_path(self, company_name: str, role_title: str, lead_id: str) -> Path:
        return self.lead_raw_dir(company_name, role_title, lead_id) / "source.md"

    def lead_capture_bundle_path(self, company_name: str, role_title: str, lead_id: str) -> Path:
        return self.lead_workspace_dir(company_name, role_title, lead_id) / "capture-bundle.json"

    def lead_alert_email_path(self, company_name: str, role_title: str, lead_id: str) -> Path:
        return self.lead_workspace_dir(company_name, role_title, lead_id) / "alert-email.md"

    def lead_alert_card_path(self, company_name: str, role_title: str, lead_id: str) -> Path:
        return self.lead_workspace_dir(company_name, role_title, lead_id) / "alert-card.json"

    def lead_post_path(self, company_name: str, role_title: str, lead_id: str) -> Path:
        return self.lead_workspace_dir(company_name, role_title, lead_id) / "post.md"

    def lead_jd_path(self, company_name: str, role_title: str, lead_id: str) -> Path:
        return self.lead_workspace_dir(company_name, role_title, lead_id) / "jd.md"

    def lead_jd_fetch_path(self, company_name: str, role_title: str, lead_id: str) -> Path:
        return self.lead_workspace_dir(company_name, role_title, lead_id) / "jd-fetch.json"

    def lead_poster_profile_path(self, company_name: str, role_title: str, lead_id: str) -> Path:
        return self.lead_workspace_dir(company_name, role_title, lead_id) / "poster-profile.md"

    def lead_split_metadata_path(self, company_name: str, role_title: str, lead_id: str) -> Path:
        return self.lead_workspace_dir(company_name, role_title, lead_id) / "source-split.yaml"

    def lead_split_review_path(self, company_name: str, role_title: str, lead_id: str) -> Path:
        return self.lead_workspace_dir(company_name, role_title, lead_id) / "source-split-review.yaml"

    def lead_manifest_path(self, company_name: str, role_title: str, lead_id: str) -> Path:
        return self.lead_workspace_dir(company_name, role_title, lead_id) / "lead-manifest.yaml"

    def lead_history_dir(self, company_name: str, role_title: str, lead_id: str) -> Path:
        return self.lead_workspace_dir(company_name, role_title, lead_id) / "history"

    def application_workspace_dir(self, company_name: str, role_title: str) -> Path:
        return (
            self.project_root
            / "applications"
            / workspace_slug(company_name)
            / workspace_slug(role_title)
        )

    def application_state_path(self, company_name: str, role_title: str) -> Path:
        return self.application_workspace_dir(company_name, role_title) / "application.yaml"

    def tailoring_eligibility_path(self, company_name: str, role_title: str) -> Path:
        return self.application_workspace_dir(company_name, role_title) / "eligibility.yaml"

    @property
    def tailoring_input_dir(self) -> Path:
        return self.project_root / "resume-tailoring" / "input"

    @property
    def tailoring_input_profile_path(self) -> Path:
        return self.tailoring_input_dir / "profile.md"

    def tailoring_input_job_posting_path(self, company_name: str, role_title: str) -> Path:
        return (
            self.tailoring_input_dir
            / "job-postings"
            / f"{workspace_slug(company_name)}-{workspace_slug(role_title)}.md"
        )

    def tailoring_workspace_dir(self, company_name: str, role_title: str) -> Path:
        return (
            self.project_root
            / "resume-tailoring"
            / "output"
            / "tailored"
            / workspace_slug(company_name)
            / workspace_slug(role_title)
        )

    def tailoring_history_dir(self, company_name: str, role_title: str) -> Path:
        return (
            self.project_root
            / "resume-tailoring"
            / "output"
            / "history"
            / workspace_slug(company_name)
            / workspace_slug(role_title)
        )

    def tailoring_run_snapshot_dir(
        self,
        company_name: str,
        role_title: str,
        resume_tailoring_run_id: str,
        snapshot_slug: str,
    ) -> Path:
        return (
            self.tailoring_history_dir(company_name, role_title)
            / resume_tailoring_run_id
            / snapshot_slug
        )

    def tailoring_meta_path(self, company_name: str, role_title: str) -> Path:
        return self.tailoring_workspace_dir(company_name, role_title) / "meta.yaml"

    def tailoring_workspace_jd_path(self, company_name: str, role_title: str) -> Path:
        return self.tailoring_workspace_dir(company_name, role_title) / "jd.md"

    def tailoring_workspace_post_path(self, company_name: str, role_title: str) -> Path:
        return self.tailoring_workspace_dir(company_name, role_title) / "post.md"

    def tailoring_workspace_poster_profile_path(self, company_name: str, role_title: str) -> Path:
        return self.tailoring_workspace_dir(company_name, role_title) / "poster-profile.md"

    def tailoring_resume_tex_path(self, company_name: str, role_title: str) -> Path:
        return self.tailoring_workspace_dir(company_name, role_title) / "resume.tex"

    def tailoring_scope_baseline_path(self, company_name: str, role_title: str) -> Path:
        return self.tailoring_workspace_dir(company_name, role_title) / "scope-baseline.resume.tex"

    def tailoring_pdf_path(self, company_name: str, role_title: str) -> Path:
        return self.tailoring_workspace_dir(company_name, role_title) / "Achyutaram Sonti.pdf"

    def tailoring_intelligence_dir(self, company_name: str, role_title: str) -> Path:
        return self.tailoring_workspace_dir(company_name, role_title) / "intelligence"

    def tailoring_intelligence_manifest_path(self, company_name: str, role_title: str) -> Path:
        return self.tailoring_intelligence_dir(company_name, role_title) / "manifest.yaml"

    def _tailoring_step_artifact_path(
        self,
        company_name: str,
        role_title: str,
        filename: str,
    ) -> Path:
        return self.tailoring_intelligence_dir(company_name, role_title) / filename

    def tailoring_step_01_path(self, company_name: str, role_title: str) -> Path:
        return self._tailoring_step_artifact_path(
            company_name,
            role_title,
            "step-01-jd-sections.yaml",
        )

    def tailoring_step_02_path(self, company_name: str, role_title: str) -> Path:
        return self._tailoring_step_artifact_path(
            company_name,
            role_title,
            "step-02-signals-raw.yaml",
        )

    def tailoring_step_03_path(self, company_name: str, role_title: str) -> Path:
        return self._tailoring_step_artifact_path(
            company_name,
            role_title,
            "step-03-signals-classified.yaml",
        )

    def tailoring_step_04_path(self, company_name: str, role_title: str) -> Path:
        return self._tailoring_step_artifact_path(
            company_name,
            role_title,
            "step-04-theme-scores.yaml",
        )

    def tailoring_step_05_path(self, company_name: str, role_title: str) -> Path:
        return self._tailoring_step_artifact_path(
            company_name,
            role_title,
            "step-05-theme-decision.yaml",
        )

    def tailoring_step_06_path(self, company_name: str, role_title: str) -> Path:
        return self._tailoring_step_artifact_path(
            company_name,
            role_title,
            "step-06-project-scores.yaml",
        )

    def tailoring_step_07_path(self, company_name: str, role_title: str) -> Path:
        return self._tailoring_step_artifact_path(
            company_name,
            role_title,
            "step-07-project-selection.yaml",
        )

    def tailoring_step_08_path(self, company_name: str, role_title: str) -> Path:
        return self._tailoring_step_artifact_path(
            company_name,
            role_title,
            "step-08-experience-evidence.yaml",
        )

    def tailoring_step_09_path(self, company_name: str, role_title: str) -> Path:
        return self._tailoring_step_artifact_path(
            company_name,
            role_title,
            "step-09-project-evidence.yaml",
        )

    def tailoring_step_10_path(self, company_name: str, role_title: str) -> Path:
        return self._tailoring_step_artifact_path(
            company_name,
            role_title,
            "step-10-gap-analysis.yaml",
        )

    def tailoring_step_11_path(self, company_name: str, role_title: str) -> Path:
        return self._tailoring_step_artifact_path(
            company_name,
            role_title,
            "step-11-bullet-allocation.yaml",
        )

    def tailoring_step_12_path(self, company_name: str, role_title: str) -> Path:
        return self._tailoring_step_artifact_path(
            company_name,
            role_title,
            "step-12-summary.yaml",
        )

    def tailoring_step_13_path(self, company_name: str, role_title: str) -> Path:
        return self._tailoring_step_artifact_path(
            company_name,
            role_title,
            "step-13-skills.yaml",
        )

    def tailoring_step_14_path(self, company_name: str, role_title: str) -> Path:
        return self._tailoring_step_artifact_path(
            company_name,
            role_title,
            "step-14-tech-stacks.yaml",
        )

    def tailoring_step_15_path(self, company_name: str, role_title: str) -> Path:
        return self._tailoring_step_artifact_path(
            company_name,
            role_title,
            "step-15-assembly.yaml",
        )

    def tailoring_step_16_path(self, company_name: str, role_title: str) -> Path:
        return self._tailoring_step_artifact_path(
            company_name,
            role_title,
            "step-16-verification.yaml",
        )

    def tailoring_step_3_jd_signals_path(self, company_name: str, role_title: str) -> Path:
        return self.tailoring_intelligence_dir(company_name, role_title) / "step-3-jd-signals.yaml"

    def tailoring_step_4_evidence_map_path(self, company_name: str, role_title: str) -> Path:
        return self.tailoring_intelligence_dir(company_name, role_title) / "step-4-evidence-map.yaml"

    def tailoring_step_5_context_path(self, company_name: str, role_title: str) -> Path:
        return (
            self.tailoring_intelligence_dir(company_name, role_title)
            / "step-5-elaborated-swe-context.md"
        )

    def tailoring_step_6_candidate_bullets_path(self, company_name: str, role_title: str) -> Path:
        return (
            self.tailoring_intelligence_dir(company_name, role_title)
            / "step-6-candidate-swe-bullets.yaml"
        )

    def tailoring_step_7_verification_path(self, company_name: str, role_title: str) -> Path:
        return self.tailoring_intelligence_dir(company_name, role_title) / "step-7-verification.yaml"

    def tailoring_prompts_dir(self, company_name: str, role_title: str) -> Path:
        return self.tailoring_intelligence_dir(company_name, role_title) / "prompts"

    def tailoring_review_dir(self, company_name: str, role_title: str) -> Path:
        return self.tailoring_workspace_dir(company_name, role_title) / "review"

    def tailoring_review_run_dir(
        self,
        company_name: str,
        role_title: str,
        resume_tailoring_run_id: str,
    ) -> Path:
        return self.tailoring_review_dir(company_name, role_title) / resume_tailoring_run_id

    def tailoring_review_decision_path(
        self,
        company_name: str,
        role_title: str,
        resume_tailoring_run_id: str,
        decision_slug: str,
    ) -> Path:
        return (
            self.tailoring_review_run_dir(
                company_name,
                role_title,
                resume_tailoring_run_id,
            )
            / f"{decision_slug}.yaml"
        )

    def discovery_workspace_dir(self, company_name: str, role_title: str) -> Path:
        return (
            self.project_root
            / "discovery"
            / "output"
            / workspace_slug(company_name)
            / workspace_slug(role_title)
        )

    def discovery_recipient_profiles_dir(self, company_name: str, role_title: str) -> Path:
        return self.discovery_workspace_dir(company_name, role_title) / "recipient-profiles"

    def discovery_recipient_profile_dir(
        self,
        company_name: str,
        role_title: str,
        contact_id: str,
    ) -> Path:
        return self.discovery_recipient_profiles_dir(company_name, role_title) / contact_id

    def discovery_recipient_profile_path(
        self,
        company_name: str,
        role_title: str,
        contact_id: str,
    ) -> Path:
        return self.discovery_recipient_profile_dir(company_name, role_title, contact_id) / "recipient_profile.json"

    def outreach_workspace_dir(self, company_name: str, role_title: str) -> Path:
        return (
            self.project_root
            / "outreach"
            / "output"
            / workspace_slug(company_name)
            / workspace_slug(role_title)
        )

    def outreach_messages_dir(self, company_name: str, role_title: str) -> Path:
        return self.outreach_workspace_dir(company_name, role_title) / "messages"

    def outreach_message_dir(
        self,
        company_name: str,
        role_title: str,
        outreach_message_id: str,
    ) -> Path:
        return self.outreach_messages_dir(company_name, role_title) / outreach_message_id

    def outreach_message_draft_path(
        self,
        company_name: str,
        role_title: str,
        outreach_message_id: str,
    ) -> Path:
        return self.outreach_message_dir(company_name, role_title, outreach_message_id) / "email_draft.md"

    def outreach_message_html_path(
        self,
        company_name: str,
        role_title: str,
        outreach_message_id: str,
    ) -> Path:
        return self.outreach_message_dir(company_name, role_title, outreach_message_id) / "email_draft.html"

    def outreach_message_send_result_path(
        self,
        company_name: str,
        role_title: str,
        outreach_message_id: str,
    ) -> Path:
        return self.outreach_message_dir(company_name, role_title, outreach_message_id) / "send_result.json"

    def outreach_latest_draft_path(self, company_name: str, role_title: str) -> Path:
        return self.outreach_workspace_dir(company_name, role_title) / "email_draft.md"

    def outreach_latest_send_result_path(self, company_name: str, role_title: str) -> Path:
        return self.outreach_workspace_dir(company_name, role_title) / "send_result.json"

    def outreach_message_feedback_dir(
        self,
        company_name: str,
        role_title: str,
        outreach_message_id: str,
        delivery_feedback_event_id: str,
    ) -> Path:
        return (
            self.outreach_message_dir(company_name, role_title, outreach_message_id)
            / "feedback"
            / delivery_feedback_event_id
        )

    def outreach_message_delivery_outcome_path(
        self,
        company_name: str,
        role_title: str,
        outreach_message_id: str,
        delivery_feedback_event_id: str,
    ) -> Path:
        return (
            self.outreach_message_feedback_dir(
                company_name,
                role_title,
                outreach_message_id,
                delivery_feedback_event_id,
            )
            / "delivery_outcome.json"
        )

    def outreach_latest_delivery_outcome_path(self, company_name: str, role_title: str) -> Path:
        return self.outreach_workspace_dir(company_name, role_title) / "delivery_outcome.json"

    def general_learning_outreach_workspace_dir(self, company_name: str, contact_id: str) -> Path:
        return (
            self.project_root
            / "outreach"
            / "output"
            / "general-learning"
            / workspace_slug(company_name)
            / contact_id
        )

    def general_learning_outreach_discovery_result_path(
        self,
        company_name: str,
        contact_id: str,
    ) -> Path:
        return self.general_learning_outreach_workspace_dir(company_name, contact_id) / "discovery_result.json"

    def general_learning_outreach_message_dir(
        self,
        company_name: str,
        contact_id: str,
        outreach_message_id: str,
    ) -> Path:
        return self.general_learning_outreach_workspace_dir(company_name, contact_id) / outreach_message_id

    def general_learning_outreach_draft_path(
        self,
        company_name: str,
        contact_id: str,
        outreach_message_id: str,
    ) -> Path:
        return (
            self.general_learning_outreach_message_dir(
                company_name,
                contact_id,
                outreach_message_id,
            )
            / "email_draft.md"
        )

    def general_learning_outreach_html_path(
        self,
        company_name: str,
        contact_id: str,
        outreach_message_id: str,
    ) -> Path:
        return (
            self.general_learning_outreach_message_dir(
                company_name,
                contact_id,
                outreach_message_id,
            )
            / "email_draft.html"
        )

    def general_learning_outreach_send_result_path(
        self,
        company_name: str,
        contact_id: str,
        outreach_message_id: str,
    ) -> Path:
        return (
            self.general_learning_outreach_message_dir(
                company_name,
                contact_id,
                outreach_message_id,
            )
            / "send_result.json"
        )

    def general_learning_outreach_feedback_dir(
        self,
        company_name: str,
        contact_id: str,
        outreach_message_id: str,
        delivery_feedback_event_id: str,
    ) -> Path:
        return (
            self.general_learning_outreach_message_dir(
                company_name,
                contact_id,
                outreach_message_id,
            )
            / "feedback"
            / delivery_feedback_event_id
        )

    def general_learning_outreach_delivery_outcome_path(
        self,
        company_name: str,
        contact_id: str,
        outreach_message_id: str,
        delivery_feedback_event_id: str,
    ) -> Path:
        return (
            self.general_learning_outreach_feedback_dir(
                company_name,
                contact_id,
                outreach_message_id,
                delivery_feedback_event_id,
            )
            / "delivery_outcome.json"
        )

    def general_learning_outreach_latest_delivery_outcome_path(
        self,
        company_name: str,
        contact_id: str,
    ) -> Path:
        return self.general_learning_outreach_workspace_dir(company_name, contact_id) / "delivery_outcome.json"

    def review_packet_dir(self, pipeline_run_id: str) -> Path:
        return self.ops_review_packets_dir / pipeline_run_id

    def review_packet_json_path(self, pipeline_run_id: str) -> Path:
        return self.review_packet_dir(pipeline_run_id) / "review_packet.json"

    def review_packet_markdown_path(self, pipeline_run_id: str) -> Path:
        return self.review_packet_dir(pipeline_run_id) / "review_packet.md"

    def background_task_dir(self, pipeline_run_id: str) -> Path:
        return self.ops_background_tasks_dir / pipeline_run_id

    def background_task_handoff_json_path(self, pipeline_run_id: str) -> Path:
        return self.background_task_dir(pipeline_run_id) / "background_task_handoff.json"

    def background_task_handoff_markdown_path(self, pipeline_run_id: str) -> Path:
        return self.background_task_dir(pipeline_run_id) / "background_task_handoff.md"

    def background_task_result_json_path(self, pipeline_run_id: str) -> Path:
        return self.background_task_dir(pipeline_run_id) / "background_task_result.json"

    def background_task_result_markdown_path(self, pipeline_run_id: str) -> Path:
        return self.background_task_dir(pipeline_run_id) / "background_task_result.md"

    def required_base_resume_template_paths(self) -> list[Path]:
        return [
            self.projects_first_base_resume_path,
            self.experience_first_base_resume_path,
        ]

    def base_resume_template_path(self, template_type: str) -> Path:
        normalized = template_type.strip().upper()
        if normalized == "A":
            return self.projects_first_base_resume_path
        if normalized == "B":
            return self.experience_first_base_resume_path
        raise ValueError(f"Unknown base resume template type: {template_type}")

    def base_resume_sources(self) -> list[Path]:
        priority = {
            "generalist": 0,
            "distributed-infra": 1,
        }
        return sorted(
            self.tailoring_base_dir.rglob("base-resume.tex"),
            key=lambda path: (priority.get(path.parent.name, 2), path.parent.name, str(path)),
        )

    def required_asset_paths(self) -> list[Path]:
        return [
            self.tailoring_assets_dir / "profile.md",
            self.tailoring_assets_dir / "ai" / "system-prompt.md",
            self.tailoring_assets_dir / "ai" / "cookbook.md",
            self.tailoring_assets_dir / "ai" / "sop-swe-experience-tailoring.md",
            self.assets_dir / "outreach" / "cold-outreach-guide.md",
        ]

    def runtime_support_directories(self) -> list[Path]:
        return [
            self.paste_dir,
            self.project_root / "applications",
            self.gmail_runtime_dir,
            self.project_root / "linkedin-scraping" / "runtime" / "leads",
            self.tailoring_input_dir / "job-postings",
            self.project_root / "resume-tailoring" / "output" / "tailored",
            self.project_root / "discovery" / "output",
            self.project_root / "outreach" / "output",
            self.ops_agent_context_snapshots_dir,
            self.ops_review_packets_dir,
            self.ops_background_tasks_dir,
            self.ops_maintenance_dir,
            self.ops_incidents_dir,
            self.ops_logs_dir,
            self.ops_launchd_dir,
        ]

    def runtime_secrets_candidates(self) -> list[Path]:
        return [
            self.project_root / "runtime_secrets.json",
            self.secrets_dir / "runtime_secrets.json",
        ]
