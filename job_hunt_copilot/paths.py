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
    def paste_dir(self) -> Path:
        return self.project_root / "paste"

    @property
    def paste_inbox_path(self) -> Path:
        return self.paste_dir / "paste.txt"

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

    def application_workspace_dir(self, company_name: str, role_title: str) -> Path:
        return (
            self.project_root
            / "applications"
            / workspace_slug(company_name)
            / workspace_slug(role_title)
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
        return self.project_root / "ops" / "review-packets" / pipeline_run_id

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
            self.project_root / "linkedin-scraping" / "runtime" / "gmail",
            self.project_root / "linkedin-scraping" / "runtime" / "leads",
            self.project_root / "resume-tailoring" / "input" / "job-postings",
            self.project_root / "resume-tailoring" / "output" / "tailored",
            self.project_root / "discovery" / "output",
            self.project_root / "outreach" / "output",
            self.project_root / "ops" / "agent" / "context-snapshots",
            self.project_root / "ops" / "review-packets",
            self.project_root / "ops" / "maintenance",
            self.project_root / "ops" / "incidents",
            self.project_root / "ops" / "launchd",
        ]

    def runtime_secrets_candidates(self) -> list[Path]:
        return [
            self.project_root / "runtime_secrets.json",
            self.secrets_dir / "runtime_secrets.json",
        ]
