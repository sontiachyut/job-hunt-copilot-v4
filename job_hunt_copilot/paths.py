from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


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
