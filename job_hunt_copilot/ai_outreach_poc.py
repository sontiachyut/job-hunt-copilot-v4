from __future__ import annotations

import base64
import json
import mimetypes
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import urlencode

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .outreach import (
    SendAttemptOutcome,
    _job_hunt_copilot_pitch_lines,
    _render_markdown_email_html,
)
from .paths import ProjectPaths, workspace_slug


AI_OUTREACH_POC_COMPONENT = "ai_outreach_poc"
GITHUB_PROFILE_RESOLVER_POC_COMPONENT = "github_profile_resolver_poc"
GITHUB_PROJECT_SELECTOR_POC_COMPONENT = "github_project_selector_poc"
GITHUB_PROJECT_ANALYZER_POC_COMPONENT = "github_project_analyzer_poc"
GITHUB_COFFEE_CHAT_DRAFTER_POC_COMPONENT = "github_coffee_chat_drafter_poc"
PROFILE_FIELD_RE = re.compile(r"^- \*\*(?P<label>[^*]+):\*\* (?P<value>.+?)\s*$")
MARKDOWN_HEADING_RE = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<title>.+?)\s*$")
_TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".tex",
    ".json",
    ".yaml",
    ".yml",
    ".html",
    ".xml",
    ".csv",
}


class AiOutreachPocError(RuntimeError):
    pass


@dataclass(frozen=True)
class GithubProfileResearch:
    profile_url: str
    login: str
    display_name: str | None
    company: str | None
    bio: str | None
    blog: str | None
    location: str | None
    repo_candidates: tuple[GithubRepoCandidate, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "profile_url": self.profile_url,
            "login": self.login,
            "display_name": self.display_name,
            "company": self.company,
            "bio": self.bio,
            "blog": self.blog,
            "location": self.location,
            "repo_candidates": [repo.as_dict() for repo in self.repo_candidates],
        }


@dataclass(frozen=True)
class AiOutreachSenderIdentity:
    name: str
    email: str | None
    phone: str | None
    linkedin_url: str | None
    github_url: str | None


@dataclass(frozen=True)
class GithubRepoCandidate:
    name: str
    url: str
    description: str | None = None
    language: str | None = None
    topics: tuple[str, ...] = ()
    stars: int | None = None
    updated_at: str | None = None
    readme_excerpt: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "url": self.url,
            "description": self.description,
            "language": self.language,
            "topics": list(self.topics),
            "stars": self.stars,
            "updated_at": self.updated_at,
            "readme_excerpt": self.readme_excerpt,
        }


@dataclass(frozen=True)
class GithubProjectSelectionRequest:
    contact_name: str
    contact_company: str | None
    contact_role: str | None
    github_profile_url: str | None
    github_profile_bio: str | None
    sender_background_summary: str
    candidate_repos: Sequence[GithubRepoCandidate]
    model: str | None = None


@dataclass(frozen=True)
class GithubProfileResolutionRequest:
    contact_name: str
    contact_company: str | None
    contact_role: str | None
    linkedin_url: str | None = None
    email: str | None = None
    min_confidence_score: int = 70


@dataclass(frozen=True)
class GithubProjectAnalysisRequest:
    contact_name: str
    contact_company: str | None
    contact_role: str | None
    github_profile_bio: str | None
    sender_background_summary: str
    selected_repo: GithubRepoCandidate
    model: str | None = None


@dataclass(frozen=True)
class GithubCoffeeChatDraftRequest:
    contact_name: str
    contact_company: str | None
    contact_role: str | None
    github_profile_url: str | None
    github_profile_bio: str | None
    selected_repo: GithubRepoCandidate
    project_summary: str
    engineering_problem: str
    standout_observations: Sequence[str]
    connection_to_my_work: str
    conversation_angle: str
    availability_window: str
    model: str | None = None


@dataclass(frozen=True)
class GithubPersonalizedOutreachPocRequest:
    contact_name: str
    contact_company: str | None
    contact_role: str | None
    sender_background_summary: str
    availability_window: str
    linkedin_url: str | None = None
    email: str | None = None
    min_confidence_score: int = 70
    model: str | None = None


@dataclass(frozen=True)
class AiOutreachPocRequest:
    jd_path: str
    resume_path: str
    company_name: str | None = None
    role_title: str | None = None
    contact_name: str | None = None
    contact_role: str | None = None
    send_to_email: str | None = None
    model: str | None = None
    send: bool = False
    attach_resume: bool = True
    attach_jd: bool = True
    subject_prefix: str | None = "[AI POC] "


@dataclass(frozen=True)
class AiOutreachDraftResult:
    run_id: str
    run_dir: str
    company_name: str | None
    role_title: str | None
    contact_name: str | None
    send_to_email: str
    subject: str
    body_text: str
    body_html: str | None
    prompt_path: str
    schema_path: str
    request_path: str
    draft_json_path: str
    email_markdown_path: str
    codex_stdout_path: str
    codex_stderr_path: str
    jd_text_path: str
    resume_text_path: str
    attachment_paths: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "run_dir": self.run_dir,
            "company_name": self.company_name,
            "role_title": self.role_title,
            "contact_name": self.contact_name,
            "send_to_email": self.send_to_email,
            "subject": self.subject,
            "body_html_present": self.body_html is not None,
            "prompt_path": self.prompt_path,
            "schema_path": self.schema_path,
            "request_path": self.request_path,
            "draft_json_path": self.draft_json_path,
            "email_markdown_path": self.email_markdown_path,
            "codex_stdout_path": self.codex_stdout_path,
            "codex_stderr_path": self.codex_stderr_path,
            "jd_text_path": self.jd_text_path,
            "resume_text_path": self.resume_text_path,
            "attachment_paths": list(self.attachment_paths),
        }


@dataclass(frozen=True)
class AiOutreachSendResult:
    draft: AiOutreachDraftResult
    send_result_path: str
    outcome: str
    thread_id: str | None
    delivery_tracking_id: str | None
    sent_at: str | None
    reason_code: str | None
    message: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "draft": self.draft.as_dict(),
            "send_result_path": self.send_result_path,
            "outcome": self.outcome,
            "thread_id": self.thread_id,
            "delivery_tracking_id": self.delivery_tracking_id,
            "sent_at": self.sent_at,
            "reason_code": self.reason_code,
            "message": self.message,
        }


@dataclass(frozen=True)
class GithubProjectSelectionResult:
    run_id: str
    run_dir: str
    contact_name: str
    contact_company: str | None
    prompt_path: str
    schema_path: str
    request_path: str
    selection_json_path: str
    codex_stdout_path: str
    codex_stderr_path: str
    selected_repo_name: str
    selected_repo_url: str
    why_selected: str
    observations: tuple[str, ...]
    runner_up_repo_names: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "run_dir": self.run_dir,
            "contact_name": self.contact_name,
            "contact_company": self.contact_company,
            "prompt_path": self.prompt_path,
            "schema_path": self.schema_path,
            "request_path": self.request_path,
            "selection_json_path": self.selection_json_path,
            "codex_stdout_path": self.codex_stdout_path,
            "codex_stderr_path": self.codex_stderr_path,
            "selected_repo_name": self.selected_repo_name,
            "selected_repo_url": self.selected_repo_url,
            "why_selected": self.why_selected,
            "observations": list(self.observations),
            "runner_up_repo_names": list(self.runner_up_repo_names),
        }


@dataclass(frozen=True)
class GithubProjectAnalysisResult:
    run_id: str
    run_dir: str
    contact_name: str
    contact_company: str | None
    prompt_path: str
    schema_path: str
    request_path: str
    analysis_json_path: str
    codex_stdout_path: str
    codex_stderr_path: str
    project_summary: str
    engineering_problem: str
    standout_observations: tuple[str, ...]
    why_it_is_a_good_hook: str
    connection_to_my_work: str
    conversation_angle: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "run_dir": self.run_dir,
            "contact_name": self.contact_name,
            "contact_company": self.contact_company,
            "prompt_path": self.prompt_path,
            "schema_path": self.schema_path,
            "request_path": self.request_path,
            "analysis_json_path": self.analysis_json_path,
            "codex_stdout_path": self.codex_stdout_path,
            "codex_stderr_path": self.codex_stderr_path,
            "project_summary": self.project_summary,
            "engineering_problem": self.engineering_problem,
            "standout_observations": list(self.standout_observations),
            "why_it_is_a_good_hook": self.why_it_is_a_good_hook,
            "connection_to_my_work": self.connection_to_my_work,
            "conversation_angle": self.conversation_angle,
        }


@dataclass(frozen=True)
class GithubProfileResolutionCandidate:
    login: str
    profile_url: str
    display_name: str | None
    company: str | None
    bio: str | None
    blog: str | None
    location: str | None
    score: int
    match_reasons: tuple[str, ...]
    matched_query_labels: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "login": self.login,
            "profile_url": self.profile_url,
            "display_name": self.display_name,
            "company": self.company,
            "bio": self.bio,
            "blog": self.blog,
            "location": self.location,
            "score": self.score,
            "match_reasons": list(self.match_reasons),
            "matched_query_labels": list(self.matched_query_labels),
        }


@dataclass(frozen=True)
class GithubProfileResolutionResult:
    run_id: str
    run_dir: str
    contact_name: str
    contact_company: str | None
    request_path: str
    resolution_json_path: str
    resolved_github_url: str | None
    resolved_login: str | None
    confidence: str
    score: int | None
    why_matched: tuple[str, ...]
    candidates: tuple[GithubProfileResolutionCandidate, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "run_dir": self.run_dir,
            "contact_name": self.contact_name,
            "contact_company": self.contact_company,
            "request_path": self.request_path,
            "resolution_json_path": self.resolution_json_path,
            "resolved_github_url": self.resolved_github_url,
            "resolved_login": self.resolved_login,
            "confidence": self.confidence,
            "score": self.score,
            "why_matched": list(self.why_matched),
            "candidates": [candidate.as_dict() for candidate in self.candidates],
        }


@dataclass(frozen=True)
class GithubCoffeeChatDraftResult:
    run_id: str
    run_dir: str
    contact_name: str
    contact_company: str | None
    subject: str
    body_text: str
    body_html: str | None
    prompt_path: str
    schema_path: str
    request_path: str
    draft_json_path: str
    email_markdown_path: str
    codex_stdout_path: str
    codex_stderr_path: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "run_dir": self.run_dir,
            "contact_name": self.contact_name,
            "contact_company": self.contact_company,
            "subject": self.subject,
            "prompt_path": self.prompt_path,
            "schema_path": self.schema_path,
            "request_path": self.request_path,
            "draft_json_path": self.draft_json_path,
            "email_markdown_path": self.email_markdown_path,
            "codex_stdout_path": self.codex_stdout_path,
            "codex_stderr_path": self.codex_stderr_path,
        }


@dataclass(frozen=True)
class GithubPersonalizedOutreachPocResult:
    resolution: GithubProfileResolutionResult
    research: GithubProfileResearch
    selection: GithubProjectSelectionResult
    analysis: GithubProjectAnalysisResult
    draft: GithubCoffeeChatDraftResult

    def as_dict(self) -> dict[str, Any]:
        return {
            "resolution": self.resolution.as_dict(),
            "research": self.research.as_dict(),
            "selection": self.selection.as_dict(),
            "analysis": self.analysis.as_dict(),
            "draft": self.draft.as_dict(),
        }


class AiOutreachDraftPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str = Field(min_length=1)
    body_markdown: str = Field(min_length=1)

    @field_validator("subject", "body_markdown")
    @classmethod
    def _non_empty_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("field cannot be empty")
        return stripped


class GithubProjectSelectionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selected_repo_name: str = Field(min_length=1)
    selected_repo_url: str = Field(min_length=1)
    why_selected: str = Field(min_length=1)
    observations: list[str] = Field(min_length=2, max_length=3)
    runner_up_repo_names: list[str] = Field(default_factory=list, max_length=3)

    @field_validator("selected_repo_name", "selected_repo_url", "why_selected")
    @classmethod
    def _non_empty_scalar(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("field cannot be empty")
        return stripped

    @field_validator("observations", "runner_up_repo_names")
    @classmethod
    def _normalize_string_list(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value if item.strip()]
        if not normalized and value:
            raise ValueError("list cannot normalize to empty strings")
        return normalized


class GithubProjectAnalysisPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_summary: str = Field(min_length=1)
    engineering_problem: str = Field(min_length=1)
    standout_observations: list[str] = Field(min_length=2, max_length=3)
    why_it_is_a_good_hook: str = Field(min_length=1)
    connection_to_my_work: str = Field(min_length=1)
    conversation_angle: str = Field(min_length=1)

    @field_validator(
        "project_summary",
        "engineering_problem",
        "why_it_is_a_good_hook",
        "connection_to_my_work",
        "conversation_angle",
    )
    @classmethod
    def _non_empty_analysis_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("field cannot be empty")
        return stripped

    @field_validator("standout_observations")
    @classmethod
    def _normalize_observations(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value if item.strip()]
        if len(normalized) < 2:
            raise ValueError("need at least two standout observations")
        return normalized


class GithubCoffeeChatDraftPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str = Field(min_length=1)
    body_markdown: str = Field(min_length=1)

    @field_validator("subject", "body_markdown")
    @classmethod
    def _non_empty_draft_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("field cannot be empty")
        return stripped


class GithubProfileResearcher:
    def __init__(self, *, gh_bin: str | None = None) -> None:
        self._gh_bin = gh_bin or _resolve_required_binary("gh")

    def fetch_profile_research(self, *, profile_url: str) -> GithubProfileResearch:
        login = _github_login_from_url(profile_url)
        if login is None:
            raise AiOutreachPocError(f"Unsupported GitHub profile URL: {profile_url}")

        profile_payload = self._gh_api_json(f"/users/{login}")
        repo_payloads = self._fetch_all_repo_payloads(login=login)
        repo_candidates = tuple(
            self._repo_candidate_from_payload(login=login, payload=repo_payload)
            for repo_payload in repo_payloads
        )
        return GithubProfileResearch(
            profile_url=_normalize_non_empty_text(profile_payload.get("html_url")) or profile_url,
            login=login,
            display_name=_normalize_non_empty_text(profile_payload.get("name")),
            company=_normalize_non_empty_text(profile_payload.get("company")),
            bio=_normalize_non_empty_text(profile_payload.get("bio")),
            blog=_normalize_non_empty_text(profile_payload.get("blog")),
            location=_normalize_non_empty_text(profile_payload.get("location")),
            repo_candidates=repo_candidates,
        )

    def _fetch_all_repo_payloads(self, *, login: str) -> list[dict[str, Any]]:
        page = 1
        payloads: list[dict[str, Any]] = []
        while True:
            page_payload = self._gh_api_json(f"/users/{login}/repos?per_page=100&page={page}&sort=updated")
            if not isinstance(page_payload, list):
                raise AiOutreachPocError("GitHub repos response was not a list.")
            if not page_payload:
                break
            payloads.extend(item for item in page_payload if isinstance(item, dict))
            if len(page_payload) < 100:
                break
            page += 1
        return payloads

    def _repo_candidate_from_payload(self, *, login: str, payload: dict[str, Any]) -> GithubRepoCandidate:
        repo_name = _normalize_non_empty_text(payload.get("name"))
        repo_url = _normalize_non_empty_text(payload.get("html_url"))
        if repo_name is None or repo_url is None:
            raise AiOutreachPocError("GitHub repo payload missing name or html_url.")
        readme_excerpt = self._fetch_repo_readme_excerpt(login=login, repo_name=repo_name)
        return GithubRepoCandidate(
            name=repo_name,
            url=repo_url,
            description=_normalize_non_empty_text(payload.get("description")),
            language=_normalize_non_empty_text(payload.get("language")),
            topics=tuple(item for item in payload.get("topics", []) if isinstance(item, str) and item.strip()),
            stars=_normalize_optional_int(payload.get("stargazers_count")),
            updated_at=_normalize_non_empty_text(payload.get("updated_at")),
            readme_excerpt=readme_excerpt,
        )

    def _fetch_repo_readme_excerpt(self, *, login: str, repo_name: str) -> str | None:
        try:
            download_url = self._gh_api_text(
                f"/repos/{login}/{repo_name}/readme",
                jq=".download_url",
            ).strip()
        except AiOutreachPocError:
            return None
        if not download_url:
            return None
        completed = subprocess.run(
            ["curl", "-L", download_url],
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            return None
        readme_text = _normalize_source_text(completed.stdout)
        return _truncate_for_prompt(readme_text, max_chars=2400)

    def _gh_api_json(self, endpoint: str) -> Any:
        completed = subprocess.run(
            [self._gh_bin, "api", endpoint],
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            raise AiOutreachPocError(
                f"`gh api` failed for `{endpoint}` with exit code {completed.returncode}: {completed.stderr.strip()}"
            )
        try:
            return json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise AiOutreachPocError(f"`gh api` returned non-JSON output for `{endpoint}`.") from exc

    def _gh_api_text(self, endpoint: str, *, jq: str) -> str:
        completed = subprocess.run(
            [self._gh_bin, "api", endpoint, "--jq", jq],
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            raise AiOutreachPocError(
                f"`gh api` failed for `{endpoint}` with exit code {completed.returncode}: {completed.stderr.strip()}"
            )
        return completed.stdout


class GithubProfileResolver:
    def __init__(self, *, gh_bin: str | None = None) -> None:
        self._gh_bin = gh_bin or _resolve_required_binary("gh")

    def resolve_profile(
        self,
        request: GithubProfileResolutionRequest,
        *,
        project_root: Path | str,
    ) -> GithubProfileResolutionResult:
        if not request.contact_name.strip():
            raise AiOutreachPocError("GitHub profile resolution requires a contact name.")

        paths = ProjectPaths.from_root(project_root)
        run_id = _build_run_id(
            company_name=request.contact_company or "unknown-company",
            role_title=f"{request.contact_name}-github-resolver",
        )
        run_dir = paths.ops_dir / "github-personalization-poc" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        request_path = run_dir / "request.json"
        resolution_path = run_dir / "resolution.json"

        query_specs = _build_github_search_query_specs(request)
        request_path.write_text(
            json.dumps(
                {
                    "component": GITHUB_PROFILE_RESOLVER_POC_COMPONENT,
                    "generated_at": _now_utc_iso(),
                    "request": {
                        "contact_name": request.contact_name,
                        "contact_company": request.contact_company,
                        "contact_role": request.contact_role,
                        "linkedin_url": request.linkedin_url,
                        "email": request.email,
                        "min_confidence_score": request.min_confidence_score,
                        "queries": [spec.as_dict() for spec in query_specs],
                    },
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        search_hits_by_login: dict[str, set[str]] = {}
        for query_spec in query_specs:
            payload = self._gh_api_json(
                "/search/users?" + urlencode({"q": query_spec.query, "per_page": 10})
            )
            items = payload.get("items", []) if isinstance(payload, dict) else []
            for item in items:
                if not isinstance(item, dict):
                    continue
                login = _normalize_non_empty_text(item.get("login"))
                if login is None:
                    continue
                search_hits_by_login.setdefault(login, set()).add(query_spec.label)

        candidates: list[GithubProfileResolutionCandidate] = []
        for login, matched_query_labels in search_hits_by_login.items():
            profile_payload = self._gh_api_json(f"/users/{login}")
            candidate = _github_resolution_candidate_from_profile(
                request=request,
                profile_payload=profile_payload,
                matched_query_labels=tuple(sorted(matched_query_labels)),
            )
            candidates.append(candidate)

        ranked_candidates = tuple(sorted(candidates, key=lambda candidate: (-candidate.score, candidate.login)))
        top_candidate = ranked_candidates[0] if ranked_candidates else None
        second_candidate = ranked_candidates[1] if len(ranked_candidates) > 1 else None
        resolved_candidate: GithubProfileResolutionCandidate | None = None
        confidence = "unresolved"
        if top_candidate is not None and top_candidate.score >= request.min_confidence_score:
            if second_candidate is None or (top_candidate.score - second_candidate.score) >= 15:
                resolved_candidate = top_candidate
                confidence = _github_resolution_confidence_label(
                    score=top_candidate.score,
                    min_confidence_score=request.min_confidence_score,
                )

        resolution_payload = {
            "component": GITHUB_PROFILE_RESOLVER_POC_COMPONENT,
            "generated_at": _now_utc_iso(),
            "resolved_github_url": resolved_candidate.profile_url if resolved_candidate else None,
            "resolved_login": resolved_candidate.login if resolved_candidate else None,
            "confidence": confidence,
            "score": resolved_candidate.score if resolved_candidate else None,
            "why_matched": list(resolved_candidate.match_reasons if resolved_candidate else ()),
            "candidates": [candidate.as_dict() for candidate in ranked_candidates],
        }
        resolution_path.write_text(json.dumps(resolution_payload, indent=2) + "\n", encoding="utf-8")

        return GithubProfileResolutionResult(
            run_id=run_id,
            run_dir=str(run_dir),
            contact_name=request.contact_name,
            contact_company=request.contact_company,
            request_path=str(request_path),
            resolution_json_path=str(resolution_path),
            resolved_github_url=resolved_candidate.profile_url if resolved_candidate else None,
            resolved_login=resolved_candidate.login if resolved_candidate else None,
            confidence=confidence,
            score=resolved_candidate.score if resolved_candidate else None,
            why_matched=resolved_candidate.match_reasons if resolved_candidate else (),
            candidates=ranked_candidates,
        )

    def _gh_api_json(self, endpoint: str) -> Any:
        completed = subprocess.run(
            [self._gh_bin, "api", endpoint],
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            raise AiOutreachPocError(
                f"`gh api` failed for `{endpoint}` with exit code {completed.returncode}: {completed.stderr.strip()}"
            )
        try:
            return json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise AiOutreachPocError(f"`gh api` returned non-JSON output for `{endpoint}`.") from exc


@dataclass(frozen=True)
class _GithubSearchQuerySpec:
    label: str
    query: str

    def as_dict(self) -> dict[str, str]:
        return {"label": self.label, "query": self.query}


def build_ai_outreach_codex_exec_command(
    *,
    codex_bin: str,
    project_root: Path,
    schema_path: Path,
    output_path: Path,
    model: str | None = None,
) -> list[str]:
    command = [
        codex_bin,
        "exec",
    ]
    if model:
        command.extend(["--model", model])
    command.extend(
        [
        "--ephemeral",
        "--sandbox",
        "workspace-write",
        "-C",
        str(project_root),
        "--output-schema",
        str(schema_path),
        "-o",
        str(output_path),
        "-",
        ]
    )
    return command


def generate_github_project_selection(
    request: GithubProjectSelectionRequest,
    *,
    project_root: Path | str,
    codex_bin: str | None = None,
) -> GithubProjectSelectionResult:
    paths = ProjectPaths.from_root(project_root)
    candidate_repos = tuple(request.candidate_repos)
    if not candidate_repos:
        raise AiOutreachPocError("GitHub project selection requires at least one candidate repo.")

    run_id = _build_run_id(
        company_name=request.contact_company or "unknown-company",
        role_title=f"{request.contact_name}-github-selector",
    )
    run_dir = paths.ops_dir / "github-personalization-poc" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    request_path = run_dir / "request.json"
    prompt_path = run_dir / "prompt.md"
    schema_path = run_dir / "schema.json"
    output_path = run_dir / "selection.json"
    codex_stdout_path = run_dir / "codex.stdout.txt"
    codex_stderr_path = run_dir / "codex.stderr.txt"

    prompt = _build_github_project_selector_prompt(request=request)
    schema = _github_project_selector_output_schema()
    prompt_path.write_text(prompt, encoding="utf-8")
    schema_path.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
    request_path.write_text(
        json.dumps(
            {
                "component": GITHUB_PROJECT_SELECTOR_POC_COMPONENT,
                "generated_at": _now_utc_iso(),
                "request": {
                    "contact_name": request.contact_name,
                    "contact_company": request.contact_company,
                    "contact_role": request.contact_role,
                    "github_profile_url": request.github_profile_url,
                    "github_profile_bio": request.github_profile_bio,
                    "sender_background_summary": request.sender_background_summary,
                    "model": request.model,
                    "candidate_repos": [repo.as_dict() for repo in candidate_repos],
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    resolved_codex_bin = codex_bin or _resolve_codex_bin()
    command = build_ai_outreach_codex_exec_command(
        codex_bin=resolved_codex_bin,
        project_root=paths.project_root,
        schema_path=schema_path,
        output_path=output_path,
        model=request.model,
    )
    completed = subprocess.run(
        command,
        input=prompt,
        text=True,
        capture_output=True,
        check=False,
    )
    codex_stdout_path.write_text(completed.stdout, encoding="utf-8")
    codex_stderr_path.write_text(completed.stderr, encoding="utf-8")
    if completed.returncode != 0:
        raise AiOutreachPocError(
            f"`codex exec` failed with exit code {completed.returncode}. See {codex_stderr_path}."
        )
    if not output_path.exists():
        raise AiOutreachPocError(
            f"`codex exec` did not materialize a project-selection payload. Expected {output_path}."
        )

    try:
        payload = GithubProjectSelectionPayload.model_validate_json(output_path.read_text(encoding="utf-8"))
    except ValidationError as exc:
        raise AiOutreachPocError(
            f"Project-selection payload failed validation. See {output_path}. Errors: {exc}"
        )

    known_repo_pairs = {(repo.name, repo.url) for repo in candidate_repos}
    if (payload.selected_repo_name, payload.selected_repo_url) not in known_repo_pairs:
        raise AiOutreachPocError(
            "Project-selection payload chose a repo that was not provided in the candidate set."
        )

    return GithubProjectSelectionResult(
        run_id=run_id,
        run_dir=str(run_dir),
        contact_name=request.contact_name,
        contact_company=request.contact_company,
        prompt_path=str(prompt_path),
        schema_path=str(schema_path),
        request_path=str(request_path),
        selection_json_path=str(output_path),
        codex_stdout_path=str(codex_stdout_path),
        codex_stderr_path=str(codex_stderr_path),
        selected_repo_name=payload.selected_repo_name,
        selected_repo_url=payload.selected_repo_url,
        why_selected=payload.why_selected,
        observations=tuple(payload.observations),
        runner_up_repo_names=tuple(payload.runner_up_repo_names),
    )


def generate_github_project_analysis(
    request: GithubProjectAnalysisRequest,
    *,
    project_root: Path | str,
    codex_bin: str | None = None,
) -> GithubProjectAnalysisResult:
    paths = ProjectPaths.from_root(project_root)

    run_id = _build_run_id(
        company_name=request.contact_company or "unknown-company",
        role_title=f"{request.contact_name}-github-analyzer",
    )
    run_dir = paths.ops_dir / "github-personalization-poc" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    request_path = run_dir / "request.json"
    prompt_path = run_dir / "prompt.md"
    schema_path = run_dir / "schema.json"
    output_path = run_dir / "analysis.json"
    codex_stdout_path = run_dir / "codex.stdout.txt"
    codex_stderr_path = run_dir / "codex.stderr.txt"

    prompt = _build_github_project_analyzer_prompt(request=request)
    schema = _github_project_analyzer_output_schema()
    prompt_path.write_text(prompt, encoding="utf-8")
    schema_path.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
    request_path.write_text(
        json.dumps(
            {
                "component": GITHUB_PROJECT_ANALYZER_POC_COMPONENT,
                "generated_at": _now_utc_iso(),
                "request": {
                    "contact_name": request.contact_name,
                    "contact_company": request.contact_company,
                    "contact_role": request.contact_role,
                    "github_profile_bio": request.github_profile_bio,
                    "sender_background_summary": request.sender_background_summary,
                    "selected_repo": request.selected_repo.as_dict(),
                    "model": request.model,
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    resolved_codex_bin = codex_bin or _resolve_codex_bin()
    command = build_ai_outreach_codex_exec_command(
        codex_bin=resolved_codex_bin,
        project_root=paths.project_root,
        schema_path=schema_path,
        output_path=output_path,
        model=request.model,
    )
    completed = subprocess.run(
        command,
        input=prompt,
        text=True,
        capture_output=True,
        check=False,
    )
    codex_stdout_path.write_text(completed.stdout, encoding="utf-8")
    codex_stderr_path.write_text(completed.stderr, encoding="utf-8")
    if completed.returncode != 0:
        raise AiOutreachPocError(
            f"`codex exec` failed with exit code {completed.returncode}. See {codex_stderr_path}."
        )
    if not output_path.exists():
        raise AiOutreachPocError(
            f"`codex exec` did not materialize a project-analysis payload. Expected {output_path}."
        )

    try:
        payload = GithubProjectAnalysisPayload.model_validate_json(output_path.read_text(encoding="utf-8"))
    except ValidationError as exc:
        raise AiOutreachPocError(
            f"Project-analysis payload failed validation. See {output_path}. Errors: {exc}"
        )

    return GithubProjectAnalysisResult(
        run_id=run_id,
        run_dir=str(run_dir),
        contact_name=request.contact_name,
        contact_company=request.contact_company,
        prompt_path=str(prompt_path),
        schema_path=str(schema_path),
        request_path=str(request_path),
        analysis_json_path=str(output_path),
        codex_stdout_path=str(codex_stdout_path),
        codex_stderr_path=str(codex_stderr_path),
        project_summary=payload.project_summary,
        engineering_problem=payload.engineering_problem,
        standout_observations=tuple(payload.standout_observations),
        why_it_is_a_good_hook=payload.why_it_is_a_good_hook,
        connection_to_my_work=payload.connection_to_my_work,
        conversation_angle=payload.conversation_angle,
    )


def generate_github_coffee_chat_draft(
    request: GithubCoffeeChatDraftRequest,
    *,
    project_root: Path | str,
    codex_bin: str | None = None,
) -> GithubCoffeeChatDraftResult:
    paths = ProjectPaths.from_root(project_root)
    sender = _load_sender_identity(paths)

    run_id = _build_run_id(
        company_name=request.contact_company or "unknown-company",
        role_title=f"{request.contact_name}-github-coffee-chat",
    )
    run_dir = paths.ops_dir / "github-personalization-poc" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    request_path = run_dir / "request.json"
    prompt_path = run_dir / "prompt.md"
    schema_path = run_dir / "schema.json"
    output_path = run_dir / "draft.json"
    email_markdown_path = run_dir / "email.md"
    codex_stdout_path = run_dir / "codex.stdout.txt"
    codex_stderr_path = run_dir / "codex.stderr.txt"

    prompt = _build_github_coffee_chat_drafting_prompt(request=request, sender=sender)
    schema = _github_coffee_chat_draft_output_schema()
    prompt_path.write_text(prompt, encoding="utf-8")
    schema_path.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
    request_path.write_text(
        json.dumps(
            {
                "component": GITHUB_COFFEE_CHAT_DRAFTER_POC_COMPONENT,
                "generated_at": _now_utc_iso(),
                "request": {
                    "contact_name": request.contact_name,
                    "contact_company": request.contact_company,
                    "contact_role": request.contact_role,
                    "github_profile_url": request.github_profile_url,
                    "github_profile_bio": request.github_profile_bio,
                    "selected_repo": request.selected_repo.as_dict(),
                    "project_summary": request.project_summary,
                    "engineering_problem": request.engineering_problem,
                    "standout_observations": list(request.standout_observations),
                    "connection_to_my_work": request.connection_to_my_work,
                    "conversation_angle": request.conversation_angle,
                    "availability_window": request.availability_window,
                    "model": request.model,
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    resolved_codex_bin = codex_bin or _resolve_codex_bin()
    command = build_ai_outreach_codex_exec_command(
        codex_bin=resolved_codex_bin,
        project_root=paths.project_root,
        schema_path=schema_path,
        output_path=output_path,
        model=request.model,
    )
    completed = subprocess.run(
        command,
        input=prompt,
        text=True,
        capture_output=True,
        check=False,
    )
    codex_stdout_path.write_text(completed.stdout, encoding="utf-8")
    codex_stderr_path.write_text(completed.stderr, encoding="utf-8")
    if completed.returncode != 0:
        raise AiOutreachPocError(
            f"`codex exec` failed with exit code {completed.returncode}. See {codex_stderr_path}."
        )
    if not output_path.exists():
        raise AiOutreachPocError(
            f"`codex exec` did not materialize a coffee-chat draft payload. Expected {output_path}."
        )

    try:
        payload = GithubCoffeeChatDraftPayload.model_validate_json(output_path.read_text(encoding="utf-8"))
    except ValidationError as exc:
        raise AiOutreachPocError(
            f"Coffee-chat draft payload failed validation. See {output_path}. Errors: {exc}"
        )

    final_body = _compose_github_coffee_chat_email_body(
        contact_name=request.contact_name,
        body_markdown=payload.body_markdown,
        sender=sender,
    )
    final_html = _render_markdown_email_html(final_body)
    email_markdown_path.write_text(final_body, encoding="utf-8")

    return GithubCoffeeChatDraftResult(
        run_id=run_id,
        run_dir=str(run_dir),
        contact_name=request.contact_name,
        contact_company=request.contact_company,
        subject=payload.subject,
        body_text=final_body,
        body_html=final_html,
        prompt_path=str(prompt_path),
        schema_path=str(schema_path),
        request_path=str(request_path),
        draft_json_path=str(output_path),
        email_markdown_path=str(email_markdown_path),
        codex_stdout_path=str(codex_stdout_path),
        codex_stderr_path=str(codex_stderr_path),
    )


def run_github_personalized_outreach_poc(
    request: GithubPersonalizedOutreachPocRequest,
    *,
    project_root: Path | str,
    codex_bin: str | None = None,
    resolver: GithubProfileResolver | None = None,
    researcher: GithubProfileResearcher | None = None,
) -> GithubPersonalizedOutreachPocResult:
    resolved_resolver = resolver or GithubProfileResolver()
    resolution = resolved_resolver.resolve_profile(
        GithubProfileResolutionRequest(
            contact_name=request.contact_name,
            contact_company=request.contact_company,
            contact_role=request.contact_role,
            linkedin_url=request.linkedin_url,
            email=request.email,
            min_confidence_score=request.min_confidence_score,
        ),
        project_root=project_root,
    )
    if resolution.resolved_github_url is None:
        raise AiOutreachPocError(
            f"GitHub profile could not be resolved for {request.contact_name}. See {resolution.resolution_json_path}."
        )

    resolved_researcher = researcher or GithubProfileResearcher()
    research = resolved_researcher.fetch_profile_research(profile_url=resolution.resolved_github_url)
    if not research.repo_candidates:
        raise AiOutreachPocError(
            f"Resolved GitHub profile has no public repos to analyze: {resolution.resolved_github_url}"
        )

    selection = generate_github_project_selection(
        GithubProjectSelectionRequest(
            contact_name=request.contact_name,
            contact_company=request.contact_company,
            contact_role=request.contact_role,
            github_profile_url=research.profile_url,
            github_profile_bio=research.bio,
            sender_background_summary=request.sender_background_summary,
            candidate_repos=research.repo_candidates,
            model=request.model,
        ),
        project_root=project_root,
        codex_bin=codex_bin,
    )
    selected_repo = _select_repo_candidate(
        repo_candidates=research.repo_candidates,
        repo_name=selection.selected_repo_name,
        repo_url=selection.selected_repo_url,
    )
    analysis = generate_github_project_analysis(
        GithubProjectAnalysisRequest(
            contact_name=request.contact_name,
            contact_company=request.contact_company,
            contact_role=request.contact_role,
            github_profile_bio=research.bio,
            sender_background_summary=request.sender_background_summary,
            selected_repo=selected_repo,
            model=request.model,
        ),
        project_root=project_root,
        codex_bin=codex_bin,
    )
    draft = generate_github_coffee_chat_draft(
        GithubCoffeeChatDraftRequest(
            contact_name=request.contact_name,
            contact_company=request.contact_company,
            contact_role=request.contact_role,
            github_profile_url=research.profile_url,
            github_profile_bio=research.bio,
            selected_repo=selected_repo,
            project_summary=analysis.project_summary,
            engineering_problem=analysis.engineering_problem,
            standout_observations=analysis.standout_observations,
            connection_to_my_work=analysis.connection_to_my_work,
            conversation_angle=analysis.conversation_angle,
            availability_window=request.availability_window,
            model=request.model,
        ),
        project_root=project_root,
        codex_bin=codex_bin,
    )
    return GithubPersonalizedOutreachPocResult(
        resolution=resolution,
        research=research,
        selection=selection,
        analysis=analysis,
        draft=draft,
    )


def generate_ai_outreach_draft(
    request: AiOutreachPocRequest,
    *,
    project_root: Path | str,
    codex_bin: str | None = None,
) -> AiOutreachDraftResult:
    paths = ProjectPaths.from_root(project_root)
    sender = _load_sender_identity(paths)
    jd_path = Path(request.jd_path).expanduser().resolve()
    resume_path = Path(request.resume_path).expanduser().resolve()
    if not jd_path.exists():
        raise AiOutreachPocError(f"JD path does not exist: {jd_path}")
    if not resume_path.exists():
        raise AiOutreachPocError(f"Resume path does not exist: {resume_path}")

    send_to_email = (request.send_to_email or sender.email or "").strip()
    if not send_to_email:
        raise AiOutreachPocError(
            "No recipient email available. Pass `send_to_email` or add an email to `assets/resume-tailoring/profile.md`."
        )

    jd_text = _read_source_text(jd_path)
    resume_text = _read_source_text(resume_path)
    run_id = _build_run_id(
        company_name=request.company_name,
        role_title=request.role_title,
    )
    run_dir = paths.ops_dir / "ai-outreach-poc" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    request_path = run_dir / "request.json"
    prompt_path = run_dir / "prompt.md"
    schema_path = run_dir / "schema.json"
    output_path = run_dir / "draft.json"
    email_markdown_path = run_dir / "email.md"
    codex_stdout_path = run_dir / "codex.stdout.txt"
    codex_stderr_path = run_dir / "codex.stderr.txt"
    jd_text_path = run_dir / "jd.txt"
    resume_text_path = run_dir / "resume.txt"

    jd_text_path.write_text(jd_text, encoding="utf-8")
    resume_text_path.write_text(resume_text, encoding="utf-8")

    prompt = _build_drafting_prompt(
        request=request,
        sender=sender,
        jd_text=jd_text,
        resume_text=resume_text,
    )
    schema = _draft_output_schema()
    prompt_path.write_text(prompt, encoding="utf-8")
    schema_path.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
    request_path.write_text(
        json.dumps(
            {
                "component": AI_OUTREACH_POC_COMPONENT,
                "generated_at": _now_utc_iso(),
                "request": {
                    "jd_path": str(jd_path),
                    "resume_path": str(resume_path),
                    "company_name": request.company_name,
                    "role_title": request.role_title,
                    "contact_name": request.contact_name,
                    "contact_role": request.contact_role,
                    "send_to_email": send_to_email,
                    "model": request.model,
                    "send": request.send,
                    "attach_resume": request.attach_resume,
                    "attach_jd": request.attach_jd,
                    "subject_prefix": request.subject_prefix,
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    resolved_codex_bin = codex_bin or _resolve_codex_bin()
    command = build_ai_outreach_codex_exec_command(
        codex_bin=resolved_codex_bin,
        project_root=paths.project_root,
        schema_path=schema_path,
        output_path=output_path,
        model=request.model,
    )
    completed = subprocess.run(
        command,
        input=prompt,
        text=True,
        capture_output=True,
        check=False,
    )
    codex_stdout_path.write_text(completed.stdout, encoding="utf-8")
    codex_stderr_path.write_text(completed.stderr, encoding="utf-8")
    if completed.returncode != 0:
        raise AiOutreachPocError(
            f"`codex exec` failed with exit code {completed.returncode}. See {codex_stderr_path}."
        )
    if not output_path.exists():
        raise AiOutreachPocError(
            f"`codex exec` did not materialize a draft payload. Expected {output_path}."
        )

    try:
        draft_payload = AiOutreachDraftPayload.model_validate_json(output_path.read_text(encoding="utf-8"))
    except ValidationError as exc:
        raise AiOutreachPocError(
            f"Draft payload failed validation. See {output_path}. Errors: {exc}"
        )
    final_subject = f"{request.subject_prefix or ''}{draft_payload.subject}".strip()
    final_body = _compose_full_email_body(
        contact_name=request.contact_name or "there",
        fit_section_markdown=draft_payload.body_markdown,
        sender=sender,
    )
    final_html = _render_markdown_email_html(final_body)
    email_markdown_path.write_text(final_body, encoding="utf-8")

    attachment_paths: list[str] = []
    if request.attach_resume:
        attachment_paths.append(str(resume_path))
    if request.attach_jd:
        attachment_paths.append(str(jd_path))

    return AiOutreachDraftResult(
        run_id=run_id,
        run_dir=str(run_dir),
        company_name=request.company_name,
        role_title=request.role_title,
        contact_name=request.contact_name,
        send_to_email=send_to_email,
        subject=final_subject,
        body_text=final_body,
        body_html=final_html,
        prompt_path=str(prompt_path),
        schema_path=str(schema_path),
        request_path=str(request_path),
        draft_json_path=str(output_path),
        email_markdown_path=str(email_markdown_path),
        codex_stdout_path=str(codex_stdout_path),
        codex_stderr_path=str(codex_stderr_path),
        jd_text_path=str(jd_text_path),
        resume_text_path=str(resume_text_path),
        attachment_paths=tuple(attachment_paths),
    )


def send_ai_outreach_draft(
    draft: AiOutreachDraftResult,
    *,
    project_root: Path | str,
    sender: Any | None = None,
) -> AiOutreachSendResult:
    paths = ProjectPaths.from_root(project_root)
    send_result_path = Path(draft.run_dir) / "send_result.json"
    message = AiOutreachPocOutboundMessage(
        recipient_email=draft.send_to_email,
        subject=draft.subject,
        body_text=draft.body_text,
        body_html=draft.body_html,
        attachment_paths=draft.attachment_paths,
    )
    resolved_sender = sender or AiOutreachPocGmailSender(paths)
    outcome = resolved_sender.send(message)
    send_result_path.write_text(
        json.dumps(
            {
                "component": AI_OUTREACH_POC_COMPONENT,
                "generated_at": _now_utc_iso(),
                "recipient_email": draft.send_to_email,
                "subject": draft.subject,
                "attachment_paths": list(draft.attachment_paths),
                "outcome": {
                    "outcome": outcome.outcome,
                    "thread_id": outcome.thread_id,
                    "delivery_tracking_id": outcome.delivery_tracking_id,
                    "sent_at": outcome.sent_at,
                    "reason_code": outcome.reason_code,
                    "message": outcome.message,
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return AiOutreachSendResult(
        draft=draft,
        send_result_path=str(send_result_path),
        outcome=outcome.outcome,
        thread_id=outcome.thread_id,
        delivery_tracking_id=outcome.delivery_tracking_id,
        sent_at=outcome.sent_at,
        reason_code=outcome.reason_code,
        message=outcome.message,
    )


def run_ai_outreach_poc(
    request: AiOutreachPocRequest,
    *,
    project_root: Path | str,
    codex_bin: str | None = None,
    sender: Any | None = None,
) -> AiOutreachDraftResult | AiOutreachSendResult:
    draft = generate_ai_outreach_draft(
        request,
        project_root=project_root,
        codex_bin=codex_bin,
    )
    if not request.send:
        return draft
    return send_ai_outreach_draft(
        draft,
        project_root=project_root,
        sender=sender,
    )


def _build_run_id(*, company_name: str | None, role_title: str | None) -> str:
    timestamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    company_slug = workspace_slug(company_name or "unknown-company")
    role_slug = workspace_slug(role_title or "unknown-role")
    return f"{timestamp}-{company_slug}-{role_slug}"


def _read_source_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        pdftotext_bin = _resolve_required_binary("pdftotext")
        completed = subprocess.run(
            [pdftotext_bin, str(path), "-"],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise AiOutreachPocError(
                f"`pdftotext` failed for `{path}`: {completed.stderr.strip() or 'unknown error'}"
            )
        return _normalize_source_text(completed.stdout)
    if suffix in _TEXT_EXTENSIONS or not suffix:
        return _normalize_source_text(path.read_text(encoding="utf-8"))
    raise AiOutreachPocError(
        f"Unsupported source file type `{path.suffix}` for `{path}`. Use text-like files or PDFs."
    )


def _normalize_source_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip() + "\n"


def _build_drafting_prompt(
    *,
    request: AiOutreachPocRequest,
    sender: AiOutreachSenderIdentity,
    jd_text: str,
    resume_text: str,
) -> str:
    contact_name = request.contact_name or "there"
    company_name = request.company_name or "Infer from the JD if obvious."
    role_title = request.role_title or "Infer from the JD if obvious."
    contact_role = request.contact_role or "Unknown"
    return "\n".join(
        [
            "Draft the fit section for a role-targeted outreach email.",
            "",
            "Return JSON only and obey the output schema exactly.",
            "",
            "Constraints:",
            "- Write as Achyutaram Sonti.",
            "- This is cold outreach to a specific person at the company, not a cover letter.",
            "- Keep the writing specific to the JD and resume provided.",
            "- Use only facts supported by the resume text.",
            "- No bullets.",
            "- No markdown emphasis.",
            "- Produce exactly 2 paragraphs in `body_markdown`.",
            "- Do not include the greeting, Job Hunt Copilot block, closing ask, or signature. The system will add those parts.",
            "- The first paragraph should explain why I am reaching out about the exact role at the exact company, identify 2-3 JD focus areas, and say whether that is the kind of work I am actively building toward or already aligned with.",
            "- The second paragraph should explain why I am reaching out to this person specifically based on their role, then give one recent example from my background that best supports the overlap.",
            "- Mention the attached resume once in the second paragraph.",
            "- Prefer one strong proof point over a long list of tools.",
            "- If the JD emphasis is aspirational for me rather than already proven, say I am building toward it instead of overstating experience.",
            "- Avoid generic flattery.",
            "",
            "Context:",
            f"- Sender name: {sender.name}",
            f"- Sender LinkedIn: {sender.linkedin_url or 'not provided'}",
            f"- Company name: {company_name}",
            f"- Role title: {role_title}",
            f"- Target contact role: {contact_role}",
            f"- Greeting name that the system will use later: {contact_name}",
            "",
            "Reference style example:",
            "I'm reaching out about the Applied ML Engineer role at Paramount because I was interested in the role's focus on machine learning and deep learning and Spark-based big data engineering. That is the kind of applied AI work I'm actively building toward through academic and personal projects, and I want to keep growing in.",
            "",
            "Given your role as Senior Software Engineer, I thought you might have useful perspective on the day-to-day work this role touches. In one recent role, I built high-availability Python and Scala data services on AWS (EMR, S3), processing 50M+ daily HL7 records (~580 TPS) and supporting reliable shared analytics infrastructure across 1,500+ hospitals with 24/7 uptime. I've attached my resume for context.",
            "",
            "Resume excerpt:",
            _truncate_for_prompt(resume_text, max_chars=14000),
            "",
            "Job description excerpt:",
            _truncate_for_prompt(jd_text, max_chars=14000),
        ]
    ).strip() + "\n"


def _build_github_project_selector_prompt(
    *,
    request: GithubProjectSelectionRequest,
) -> str:
    repo_sections: list[str] = []
    for index, repo in enumerate(request.candidate_repos, start=1):
        repo_sections.extend(
            [
                f"Repo {index}: {repo.name}",
                f"- URL: {repo.url}",
                f"- Description: {repo.description or 'not provided'}",
                f"- Primary language: {repo.language or 'not provided'}",
                f"- Topics: {', '.join(repo.topics) if repo.topics else 'none listed'}",
                f"- Stars: {repo.stars if repo.stars is not None else 'unknown'}",
                f"- Updated at: {repo.updated_at or 'unknown'}",
                f"- README excerpt: {_truncate_for_prompt(repo.readme_excerpt or 'not provided', max_chars=1800)}",
                "",
            ]
        )

    return "\n".join(
        [
            "Select the best GitHub project to mention in a cold coffee-chat email to an engineer.",
            "",
            "Return JSON only and obey the output schema exactly.",
            "",
            "Objective:",
            "- Choose one repo that gives the strongest, most natural common ground for outreach.",
            "- Prefer repos that show real engineering depth, concrete constraints, and clear overlap with the sender's work.",
            "- Avoid selecting a repo only because it is popular or generic.",
            "",
            "Selection criteria:",
            "- The repo should make it easy to write 1-2 specific observations that sound real.",
            "- The repo should expose a clear engineering problem, tradeoff, or product/tooling shape.",
            "- The repo should connect naturally to the sender's background or current project.",
            "- Prefer practical systems or tooling over toy demos when possible.",
            "",
            "Output requirements:",
            "- `selected_repo_name`: exact repo name from the candidate list",
            "- `selected_repo_url`: exact repo URL from the candidate list",
            "- `why_selected`: short explanation of why this is the strongest hook",
            "- `observations`: 2 or 3 concrete technical observations worth mentioning in an email",
            "- `runner_up_repo_names`: optional list of 0 to 3 repo names that were also plausible",
            "",
            "Contact context:",
            f"- Contact name: {request.contact_name}",
            f"- Contact company: {request.contact_company or 'unknown'}",
            f"- Contact role: {request.contact_role or 'unknown'}",
            f"- GitHub profile URL: {request.github_profile_url or 'unknown'}",
            f"- GitHub profile bio: {request.github_profile_bio or 'not provided'}",
            "",
            "Sender context:",
            request.sender_background_summary.strip(),
            "",
            "Candidate repos:",
            *repo_sections,
        ]
    ).strip() + "\n"


def _build_github_project_analyzer_prompt(
    *,
    request: GithubProjectAnalysisRequest,
) -> str:
    repo = request.selected_repo
    return "\n".join(
        [
            "Analyze a GitHub project for personalized engineering outreach.",
            "",
            "Return JSON only and obey the output schema exactly.",
            "",
            "Your job is not to draft the email.",
            "Your job is to produce the reasoning that will later be used to draft the email.",
            "",
            "Goal:",
            "- Understand what engineering problem this repo is solving",
            "- Identify 2-3 concrete technical details that are worth mentioning in a cold email",
            "- Explain why this repo is a strong common-ground hook",
            "- Connect the repo naturally to the sender's work",
            "- Suggest what a 15-minute conversation with the contact could be about",
            "",
            "Constraints:",
            "- Use only the evidence provided",
            "- Do not invent facts",
            "- Do not use generic praise",
            "- Do not summarize the repo at a high level only",
            "- Prefer concrete engineering details over broad compliments",
            "- Focus on why this project feels like a real engineering system, tool, or workflow",
            "- If the evidence is weak, say so directly in the analysis",
            "",
            "Contact context:",
            f"- Contact name: {request.contact_name}",
            f"- Contact company: {request.contact_company or 'unknown'}",
            f"- Contact role: {request.contact_role or 'unknown'}",
            f"- GitHub bio: {request.github_profile_bio or 'not provided'}",
            "",
            "Sender context:",
            request.sender_background_summary.strip(),
            "",
            "Selected repo:",
            f"- Name: {repo.name}",
            f"- URL: {repo.url}",
            f"- Description: {repo.description or 'not provided'}",
            f"- Language: {repo.language or 'not provided'}",
            f"- Topics: {', '.join(repo.topics) if repo.topics else 'none listed'}",
            f"- Stars: {repo.stars if repo.stars is not None else 'unknown'}",
            f"- Updated at: {repo.updated_at or 'unknown'}",
            "- README excerpt:",
            _truncate_for_prompt(repo.readme_excerpt or "not provided", max_chars=2800),
        ]
    ).strip() + "\n"


def _build_github_coffee_chat_drafting_prompt(
    *,
    request: GithubCoffeeChatDraftRequest,
    sender: AiOutreachSenderIdentity,
) -> str:
    repo = request.selected_repo
    observations = "\n".join(
        [f"- Observation {index}: {observation}" for index, observation in enumerate(request.standout_observations, start=1)]
    )
    return "\n".join(
        [
            "Write a cold coffee-chat email to an engineer.",
            "",
            "Return JSON only and obey the output schema exactly.",
            "",
            "Goal:",
            "- Start from a GitHub-based common ground.",
            "- Show that I spent real time understanding one of their projects.",
            "- Connect that project to something I am building.",
            "- Briefly establish my credibility through Job Hunt Copilot.",
            "- Ask for a 15-minute conversation in the next two weeks.",
            "",
            "Required structure:",
            "- Produce exactly 3 paragraphs in `body_markdown`.",
            "- Do not include the greeting or signature. The system will add them.",
            "- Paragraph 1: mention the selected GitHub repo by name and include 1 or 2 concrete technical observations. No generic praise.",
            "- Paragraph 2: connect the repo to my work. Mention that I built Job Hunt Copilot for my own job search to identify relevant roles and the right people to reach out to, that parts of the workflow run autonomously, that I personally review every email before it goes out, and that this email is a live example of that workflow.",
            "- Paragraph 3: ask for a short 15-minute coffee chat. Say I would like to hear how they think about building projects or systems like this and what makes them genuinely useful in practice. Ask whether they are available sometime in the next two weeks. Mention that I am usually free on weekdays between the provided availability window and can be flexible on weekends if needed.",
            "",
            "Subject requirements:",
            "- Return a concise subject in `subject`.",
            "- Keep it natural and low-pressure.",
            "- Do not mention jobs, referrals, or hiring in the subject.",
            "",
            "Style requirements:",
            "- Natural, concise, technical, and human.",
            "- Not formal.",
            "- Not overly enthusiastic.",
            "- Not templated or robotic.",
            "- No flattery.",
            "- No exaggerated claims.",
            "- No bullets inside the email body.",
            "- Keep the email body under 220 words.",
            "",
            "Do not:",
            "- Ask for a job.",
            "- Ask for a referral.",
            "- Say that I have been following their work unless the evidence explicitly supports that.",
            "",
            "Contact context:",
            f"- Contact name: {request.contact_name}",
            f"- Contact company: {request.contact_company or 'unknown'}",
            f"- Contact role: {request.contact_role or 'unknown'}",
            f"- GitHub profile URL: {request.github_profile_url or 'unknown'}",
            f"- GitHub profile bio: {request.github_profile_bio or 'not provided'}",
            "",
            "Sender context:",
            f"- Sender name: {sender.name}",
            f"- Sender LinkedIn: {sender.linkedin_url or 'not provided'}",
            f"- Sender GitHub: {sender.github_url or 'not provided'}",
            "",
            "Selected repo:",
            f"- Name: {repo.name}",
            f"- URL: {repo.url}",
            f"- Description: {repo.description or 'not provided'}",
            f"- Language: {repo.language or 'not provided'}",
            f"- Topics: {', '.join(repo.topics) if repo.topics else 'none listed'}",
            f"- Updated at: {repo.updated_at or 'unknown'}",
            "",
            "Selected repo analysis:",
            f"- Project summary: {request.project_summary}",
            f"- Engineering problem: {request.engineering_problem}",
            observations,
            f"- Connection to my work: {request.connection_to_my_work}",
            f"- Conversation angle: {request.conversation_angle}",
            "",
            f"Availability window: {request.availability_window}",
        ]
    ).strip() + "\n"


def _truncate_for_prompt(text: str, *, max_chars: int) -> str:
    stripped = text.strip()
    if len(stripped) <= max_chars:
        return stripped
    return stripped[: max_chars - 16].rstrip() + "\n[truncated]"


def _select_repo_candidate(
    *,
    repo_candidates: Sequence[GithubRepoCandidate],
    repo_name: str,
    repo_url: str,
) -> GithubRepoCandidate:
    for repo in repo_candidates:
        if repo.name == repo_name and repo.url == repo_url:
            return repo
    raise AiOutreachPocError(
        f"Selected repo `{repo_name}` with URL `{repo_url}` was not present in the research candidate set."
    )


def _draft_output_schema() -> dict[str, Any]:
    return AiOutreachDraftPayload.model_json_schema()


def _github_project_selector_output_schema() -> dict[str, Any]:
    return GithubProjectSelectionPayload.model_json_schema()


def _github_project_analyzer_output_schema() -> dict[str, Any]:
    return GithubProjectAnalysisPayload.model_json_schema()


def _github_coffee_chat_draft_output_schema() -> dict[str, Any]:
    return GithubCoffeeChatDraftPayload.model_json_schema()


def _compose_full_email_body(
    *,
    contact_name: str,
    fit_section_markdown: str,
    sender: AiOutreachSenderIdentity,
) -> str:
    ask_paragraph = (
        "If it would be useful, I would welcome a short 15-minute conversation sometime this or next week "
        "to learn a bit more about the role and get your perspective on whether my background could be relevant. "
        "If you're not the right person, I'd also really appreciate it if you could point me to the right person "
        "or forward my resume internally."
    )
    signature_lines = ["Best,", sender.name]
    if sender.linkedin_url:
        signature_lines.append(sender.linkedin_url)
    if sender.phone:
        signature_lines.append(sender.phone)
    if sender.email:
        signature_lines.append(sender.email)
    return (
        "\n".join(
            [
                f"Hi {contact_name},",
                "",
                _strip_existing_signature(fit_section_markdown).strip(),
                "",
                *_job_hunt_copilot_pitch_lines(),
                "",
                ask_paragraph,
                "",
                *signature_lines,
            ]
        ).strip()
        + "\n"
    )


def _compose_github_coffee_chat_email_body(
    *,
    contact_name: str,
    body_markdown: str,
    sender: AiOutreachSenderIdentity,
) -> str:
    signature_lines = ["Best,", sender.name]
    if sender.linkedin_url:
        signature_lines.append(sender.linkedin_url)
    if sender.phone:
        signature_lines.append(sender.phone)
    if sender.email:
        signature_lines.append(sender.email)
    return (
        "\n".join(
            [
                f"Hi {contact_name},",
                "",
                _strip_existing_signature(body_markdown).strip(),
                "",
                *signature_lines,
            ]
        ).strip()
        + "\n"
    )


def _load_sender_identity(paths: ProjectPaths) -> AiOutreachSenderIdentity:
    profile_path = paths.assets_dir / "resume-tailoring" / "profile.md"
    if not profile_path.exists():
        raise AiOutreachPocError("Sender master profile is missing.")
    fields: dict[str, str] = {}
    current_heading = ""
    for raw_line in profile_path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("<!--"):
            continue
        heading_match = MARKDOWN_HEADING_RE.match(stripped)
        if heading_match is not None:
            current_heading = heading_match.group("title").strip().lower()
            continue
        if current_heading != "personal":
            continue
        field_match = PROFILE_FIELD_RE.match(stripped)
        if field_match is not None:
            fields[field_match.group("label").strip().lower()] = field_match.group("value").strip()
    return AiOutreachSenderIdentity(
        name=fields.get("name", "Achyutaram Sonti"),
        email=fields.get("email"),
        phone=fields.get("phone"),
        linkedin_url=fields.get("linkedin"),
        github_url=fields.get("github"),
    )


def _resolve_codex_bin() -> str:
    candidate = _resolve_required_binary("codex")
    return candidate


def _resolve_required_binary(name: str) -> str:
    candidate = shutil.which(name)
    if not candidate:
        raise AiOutreachPocError(f"Required binary not found on PATH: {name}")
    return candidate


def _normalize_non_empty_text(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _normalize_optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _github_login_from_url(url: str) -> str | None:
    normalized = url.strip().rstrip("/")
    match = re.match(r"^https?://github\.com/(?P<login>[A-Za-z0-9_.-]+)$", normalized)
    if match is None:
        return None
    return match.group("login")


def _build_github_search_query_specs(
    request: GithubProfileResolutionRequest,
) -> tuple[_GithubSearchQuerySpec, ...]:
    seen_queries: set[str] = set()
    query_specs: list[_GithubSearchQuerySpec] = []

    def add_query(label: str, query: str | None) -> None:
        normalized_query = _normalize_non_empty_text(query)
        if normalized_query is None:
            return
        if normalized_query in seen_queries:
            return
        seen_queries.add(normalized_query)
        query_specs.append(_GithubSearchQuerySpec(label=label, query=normalized_query))

    add_query("name_company", " ".join(part for part in [request.contact_name, request.contact_company] if part))
    add_query("name", request.contact_name)
    compact_name = _normalize_identity_token(request.contact_name)
    if compact_name:
        add_query("name_compact", compact_name)
    email_handle = _normalize_identity_token(_email_local_part(request.email))
    if email_handle and email_handle != compact_name:
        add_query("email_handle", email_handle)
    return tuple(query_specs)


def _github_resolution_candidate_from_profile(
    *,
    request: GithubProfileResolutionRequest,
    profile_payload: dict[str, Any],
    matched_query_labels: tuple[str, ...],
) -> GithubProfileResolutionCandidate:
    login = _normalize_non_empty_text(profile_payload.get("login"))
    profile_url = _normalize_non_empty_text(profile_payload.get("html_url"))
    if login is None or profile_url is None:
        raise AiOutreachPocError("GitHub profile payload missing login or html_url during resolution.")

    display_name = _normalize_non_empty_text(profile_payload.get("name"))
    company = _normalize_non_empty_text(profile_payload.get("company"))
    bio = _normalize_non_empty_text(profile_payload.get("bio"))
    blog = _normalize_non_empty_text(profile_payload.get("blog"))
    location = _normalize_non_empty_text(profile_payload.get("location"))

    contact_name_token = _normalize_identity_token(request.contact_name)
    display_name_token = _normalize_identity_token(display_name)
    contact_company_token = _normalize_identity_token(request.contact_company)
    company_token = _normalize_identity_token(company)
    bio_token = _normalize_identity_token(bio)
    login_token = _normalize_identity_token(login)
    email_handle_token = _normalize_identity_token(_email_local_part(request.email))

    score = 0
    reasons: list[str] = []

    if display_name_token and display_name_token == contact_name_token:
        score += 55
        reasons.append("GitHub display name exactly matches the contact name.")
    elif display_name_token and contact_name_token and display_name_token in contact_name_token:
        score += 35
        reasons.append("GitHub display name partially matches the contact name.")

    if login_token and contact_name_token and login_token == contact_name_token:
        score += 25
        reasons.append("GitHub login matches the compact contact name.")

    if login_token and email_handle_token and login_token == email_handle_token:
        score += 35
        reasons.append("GitHub login matches the contact email handle.")

    if "name_company" in matched_query_labels:
        score += 15
        reasons.append("GitHub account appeared in the name-plus-company search.")

    if contact_company_token and company_token and contact_company_token in company_token:
        score += 30
        reasons.append("GitHub company field matches the contact company.")

    if contact_company_token and bio_token and contact_company_token in bio_token:
        score += 15
        reasons.append("GitHub bio mentions the contact company.")

    return GithubProfileResolutionCandidate(
        login=login,
        profile_url=profile_url,
        display_name=display_name,
        company=company,
        bio=bio,
        blog=blog,
        location=location,
        score=score,
        match_reasons=tuple(reasons),
        matched_query_labels=matched_query_labels,
    )


def _github_resolution_confidence_label(*, score: int, min_confidence_score: int) -> str:
    if score >= max(min_confidence_score + 20, 90):
        return "high"
    if score >= min_confidence_score:
        return "medium"
    return "low"


def _normalize_identity_token(value: object) -> str | None:
    normalized = _normalize_non_empty_text(value)
    if normalized is None:
        return None
    token = re.sub(r"[^a-z0-9]+", "", normalized.lower())
    return token or None


def _email_local_part(email: str | None) -> str | None:
    normalized = _normalize_non_empty_text(email)
    if normalized is None or "@" not in normalized:
        return None
    return normalized.split("@", 1)[0]


def _now_utc_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _strip_existing_signature(body_markdown: str) -> str:
    match = re.search(r"\nBest,\s*$", body_markdown, flags=re.IGNORECASE | re.MULTILINE)
    if match is None:
        return body_markdown
    return body_markdown[: match.start()].rstrip()


@dataclass(frozen=True)
class AiOutreachPocOutboundMessage:
    recipient_email: str
    subject: str
    body_text: str
    body_html: str | None
    attachment_paths: Sequence[str]


class AiOutreachPocGmailSender:
    def __init__(
        self,
        paths: ProjectPaths,
        *,
        service_factory: object | None = None,
    ) -> None:
        self._paths = paths
        self._service_factory = service_factory

    def send(self, message: AiOutreachPocOutboundMessage) -> SendAttemptOutcome:
        try:
            service = self._build_service()
            mime_message = self._build_mime_message(message)
            raw_payload = base64.urlsafe_b64encode(mime_message.as_bytes()).decode("ascii")
            response = (
                service.users()
                .messages()
                .send(userId="me", body={"raw": raw_payload})
                .execute()
            )
        except FileNotFoundError as exc:
            return SendAttemptOutcome(
                outcome="failed",
                reason_code="missing_attachment",
                message=str(exc),
            )
        except Exception as exc:
            return SendAttemptOutcome(
                outcome="failed",
                reason_code="gmail_send_failed",
                message=str(exc),
            )
        delivery_tracking_id = _normalize_non_empty_text(response.get("id"))
        if delivery_tracking_id is None:
            return SendAttemptOutcome(
                outcome="ambiguous",
                reason_code="gmail_missing_message_id",
                message="Gmail send succeeded without returning a message id.",
            )
        return SendAttemptOutcome(
            outcome="sent",
            thread_id=_normalize_non_empty_text(response.get("threadId")),
            delivery_tracking_id=delivery_tracking_id,
            sent_at=_gmail_sent_at_from_response(response),
        )

    def _build_service(self) -> Any:
        if self._service_factory is not None:
            return self._service_factory()
        from .gmail_alerts import _build_gmail_service

        return _build_gmail_service(self._paths)

    def _build_mime_message(self, message: AiOutreachPocOutboundMessage) -> EmailMessage:
        mime_message = EmailMessage()
        mime_message["To"] = message.recipient_email
        mime_message["Subject"] = message.subject
        mime_message.set_content(message.body_text)
        if message.body_html:
            mime_message.add_alternative(message.body_html, subtype="html")
        for attachment_path_value in message.attachment_paths:
            attachment_path = Path(attachment_path_value)
            attachment_bytes = attachment_path.read_bytes()
            content_type, _ = mimetypes.guess_type(str(attachment_path))
            if content_type is None:
                maintype, subtype = ("application", "octet-stream")
            else:
                maintype, subtype = content_type.split("/", 1)
            mime_message.add_attachment(
                attachment_bytes,
                maintype=maintype,
                subtype=subtype,
                filename=attachment_path.name,
            )
        return mime_message


def _gmail_sent_at_from_response(response: dict[str, Any]) -> str:
    internal_date = _normalize_non_empty_text(response.get("internalDate"))
    if internal_date:
        try:
            internal_date_ms = int(internal_date)
        except ValueError:
            internal_date_ms = 0
        if internal_date_ms > 0:
            return (
                datetime.fromtimestamp(internal_date_ms / 1000, tz=UTC)
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z")
            )
    return _now_utc_iso()
