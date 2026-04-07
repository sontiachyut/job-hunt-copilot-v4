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
    def ops_agent_supervisor_bootstrap_path(self) -> Path:
        return self.ops_agent_dir / "supervisor-bootstrap.md"

    @property
    def ops_agent_context_snapshots_dir(self) -> Path:
        return self.ops_agent_dir / "context-snapshots"

    @property
    def ops_review_packets_dir(self) -> Path:
        return self.ops_dir / "review-packets"

    @property
    def ops_maintenance_dir(self) -> Path:
        return self.ops_dir / "maintenance"

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
    def supervisor_stdout_log_path(self) -> Path:
        return self.ops_logs_dir / "supervisor.stdout.log"

    @property
    def supervisor_stderr_log_path(self) -> Path:
        return self.ops_logs_dir / "supervisor.stderr.log"

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
    def control_agent_script_path(self) -> Path:
        return self.ops_scripts_dir / "control_agent.py"

    @property
    def run_supervisor_cycle_script_path(self) -> Path:
        return self.ops_scripts_dir / "run_supervisor_cycle.py"

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

    def tailoring_eligibility_path(self, company_name: str, role_title: str) -> Path:
        return self.application_workspace_dir(company_name, role_title) / "eligibility.yaml"

    def tailoring_workspace_dir(self, company_name: str, role_title: str) -> Path:
        return (
            self.project_root
            / "resume-tailoring"
            / "output"
            / "tailored"
            / workspace_slug(company_name)
            / workspace_slug(role_title)
        )

    def discovery_workspace_dir(self, company_name: str, role_title: str) -> Path:
        return (
            self.project_root
            / "discovery"
            / "output"
            / workspace_slug(company_name)
            / workspace_slug(role_title)
        )

    def outreach_workspace_dir(self, company_name: str, role_title: str) -> Path:
        return (
            self.project_root
            / "outreach"
            / "output"
            / workspace_slug(company_name)
            / workspace_slug(role_title)
        )

    def review_packet_dir(self, pipeline_run_id: str) -> Path:
        return self.ops_review_packets_dir / pipeline_run_id

    def review_packet_json_path(self, pipeline_run_id: str) -> Path:
        return self.review_packet_dir(pipeline_run_id) / "review_packet.json"

    def review_packet_markdown_path(self, pipeline_run_id: str) -> Path:
        return self.review_packet_dir(pipeline_run_id) / "review_packet.md"

    def base_resume_sources(self) -> list[Path]:
        return sorted((self.assets_dir / "resume-tailoring" / "base").rglob("base-resume.tex"))

    def required_asset_paths(self) -> list[Path]:
        return [
            self.assets_dir / "resume-tailoring" / "profile.md",
            self.assets_dir / "resume-tailoring" / "ai" / "system-prompt.md",
            self.assets_dir / "resume-tailoring" / "ai" / "cookbook.md",
            self.assets_dir / "resume-tailoring" / "ai" / "sop-swe-experience-tailoring.md",
            self.assets_dir / "outreach" / "cold-outreach-guide.md",
        ]

    def runtime_support_directories(self) -> list[Path]:
        return [
            self.paste_dir,
            self.project_root / "applications",
            self.gmail_runtime_dir,
            self.project_root / "linkedin-scraping" / "runtime" / "leads",
            self.project_root / "resume-tailoring" / "input" / "job-postings",
            self.project_root / "resume-tailoring" / "output" / "tailored",
            self.project_root / "discovery" / "output",
            self.project_root / "outreach" / "output",
            self.ops_agent_context_snapshots_dir,
            self.ops_review_packets_dir,
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
