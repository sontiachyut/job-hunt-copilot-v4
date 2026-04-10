from __future__ import annotations

import os
import re
import shutil
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from .artifacts import (
    ArtifactLinkage,
    PublishedArtifact,
    artifact_location,
    publish_yaml_artifact,
    register_artifact_record,
    write_yaml_contract,
)
from .outreach import evaluate_role_targeted_send_set
from .paths import ProjectPaths
from .records import lifecycle_timestamps, new_canonical_id, now_utc_iso
from .supervisor import OverrideEventRecord, record_override_event


RESUME_TAILORING_COMPONENT = "resume_tailoring"
TAILORING_ELIGIBILITY_ARTIFACT_TYPE = "tailoring_eligibility"
TAILORING_META_ARTIFACT_TYPE = "tailoring_meta"
TAILORING_REVIEW_ARTIFACT_TYPE = "tailoring_review_decision"

ELIGIBILITY_STATUS_ELIGIBLE = "eligible"
ELIGIBILITY_STATUS_SOFT_FLAG = "soft-flag"
ELIGIBILITY_STATUS_HARD_INELIGIBLE = "hard-ineligible"
ELIGIBILITY_STATUS_UNKNOWN = "unknown"

TAILORING_STATUS_IN_PROGRESS = "in_progress"
TAILORING_STATUS_NEEDS_REVISION = "needs_revision"
TAILORING_STATUS_TAILORED = "tailored"
TAILORING_STATUS_FAILED = "failed"
TAILORING_STATUSES = frozenset(
    {
        TAILORING_STATUS_IN_PROGRESS,
        TAILORING_STATUS_NEEDS_REVISION,
        TAILORING_STATUS_TAILORED,
        TAILORING_STATUS_FAILED,
    }
)

RESUME_REVIEW_STATUS_NOT_READY = "not_ready"
RESUME_REVIEW_STATUS_PENDING = "resume_review_pending"
RESUME_REVIEW_STATUS_APPROVED = "approved"
RESUME_REVIEW_STATUS_REJECTED = "rejected"
RESUME_REVIEW_STATUSES = frozenset(
    {
        RESUME_REVIEW_STATUS_NOT_READY,
        RESUME_REVIEW_STATUS_PENDING,
        RESUME_REVIEW_STATUS_APPROVED,
        RESUME_REVIEW_STATUS_REJECTED,
    }
)

JOB_POSTING_STATUS_HARD_INELIGIBLE = "hard_ineligible"
JOB_POSTING_STATUS_TAILORING_IN_PROGRESS = "tailoring_in_progress"
JOB_POSTING_STATUS_RESUME_REVIEW_PENDING = "resume_review_pending"
JOB_POSTING_STATUS_REQUIRES_CONTACTS = "requires_contacts"
JOB_POSTING_STATUS_READY_FOR_OUTREACH = "ready_for_outreach"

INTELLIGENCE_STATUS_GENERATED = "generated"
VERIFICATION_OUTCOME_PASS = "pass"
VERIFICATION_OUTCOME_FAIL = "fail"
VERIFICATION_OUTCOME_NEEDS_REVISION = "needs_revision"

BOOTSTRAP_REASON_MISSING_JD = "missing_jd"
BOOTSTRAP_REASON_MISSING_BASE_RESUME = "missing_base_resume"
FINALIZE_REASON_MISSING_STEP_ARTIFACT = "missing_step_artifact"
FINALIZE_REASON_INVALID_STEP_ARTIFACT = "invalid_step_artifact"
FINALIZE_REASON_SCOPE_VIOLATION = "scope_violation"
FINALIZE_REASON_VERIFICATION_BLOCKED = "verification_blocked"
FINALIZE_REASON_COMPILE_FAILED = "compile_failed"
FINALIZE_REASON_PAGE_BUDGET = "page_budget_exceeded"
TAILORING_REVIEW_REASON_REJECTED = "review_rejected"
TAILORING_REVIEW_REASON_OVERRIDE_APPLIED = "review_override_applied"

MANDATORY_REVIEWER_AGENT = "agent"
MANDATORY_REVIEWER_OWNER = "owner"
REVIEWER_TYPES = frozenset({MANDATORY_REVIEWER_AGENT, MANDATORY_REVIEWER_OWNER})
TAILORING_REVIEW_DECISION_TYPES = frozenset(
    {
        RESUME_REVIEW_STATUS_APPROVED,
        RESUME_REVIEW_STATUS_REJECTED,
    }
)
DEFAULT_SECTION_LOCKS = (
    "education",
    "projects",
    "awards-and-leadership",
)
DEFAULT_EXPERIENCE_ROLE_ALLOWLIST = ("software-engineer",)
INTELLIGENCE_STATUS_NOT_STARTED = "not_started"
INTELLIGENCE_STATUS_PENDING = "pending"
STEP_7_CHECK_IDS = (
    "proof-grounding",
    "jd-coverage",
    "metric-sanity",
    "line-budget",
    "compile-page-readiness",
)
STEP_6_BULLET_TARGET_MIN = 210
STEP_6_BULLET_TARGET_MAX = 255
STEP_6_BULLET_HARD_MIN = 100
STEP_6_BULLET_HARD_MAX = 275
LATEX_BIN_CANDIDATE_DIRS = (
    "/Library/TeX/texbin",
    "/opt/homebrew/bin",
    "/usr/local/bin",
)
NON_RESUME_VERIFIABLE_SIGNAL_CATEGORIES = frozenset(
    {"authorization", "compensation", "location_constraint"}
)

FRONTEND_AI_TRACK = "frontend_ai"
DISTRIBUTED_INFRA_TRACK = "distributed_infra"
GENERALIST_SWE_TRACK = "generalist_swe"
ROLE_FOCUS_AI_APPLICATION = "ai_application"
ROLE_FOCUS_CLOUD_PLATFORM = "cloud_platform"
ROLE_FOCUS_BACKEND_SERVICE = "backend_service"
ROLE_FOCUS_DISTRIBUTED = "distributed"

HARD_DISQUALIFIER_EXPERIENCE = "experience_gt_5_years"
HARD_DISQUALIFIER_CITIZENSHIP = "citizenship_required"
HARD_DISQUALIFIER_SECURITY_CLEARANCE = "security_clearance_required"
SOFT_FLAG_NO_SPONSORSHIP = "no_sponsorship"
MISSING_FIELD_EXPERIENCE = "experience_requirement"
MISSING_FIELD_AUTHORIZATION = "citizenship_or_clearance_requirement"

EXPERIENCE_COMPARATOR_RE = re.compile(
    r"\b(?P<operator>more than|over|at least|minimum of|minimum)\s+(?P<years>\d+)\s+"
    r"(?:years?|yrs?)\b",
    re.IGNORECASE,
)
EXPERIENCE_PLUS_RE = re.compile(r"\b(?P<years>\d+)\s*\+\s*(?:years?|yrs?)\b", re.IGNORECASE)
EXPERIENCE_RANGE_RE = re.compile(
    r"\b(?P<years>\d+)\s*(?:-|to)\s*\d+\s*(?:years?|yrs?)\b",
    re.IGNORECASE,
)
EXPERIENCE_PLAIN_RE = re.compile(r"\b(?P<years>\d+)\s*(?:years?|yrs?)\b", re.IGNORECASE)
EXPERIENCE_CONTEXT_RE = re.compile(
    r"\b(experience|experienced|professional|engineering)\b",
    re.IGNORECASE,
)
AMBIGUOUS_EXPERIENCE_RE = re.compile(
    r"\b(years?|yrs?|experience|experienced)\b",
    re.IGNORECASE,
)

HARD_REQUIREMENT_PATTERNS = (
    (
        HARD_DISQUALIFIER_CITIZENSHIP,
        re.compile(
            r"\b(?:u\.?s\.?|us)\s+citizens?(?:hip)?\b.*\b(required|must|only)\b",
            re.IGNORECASE,
        ),
    ),
    (
        HARD_DISQUALIFIER_CITIZENSHIP,
        re.compile(
            r"\bcitizens?(?:hip)?\b.*\b(required|must|only)\b",
            re.IGNORECASE,
        ),
    ),
    (
        HARD_DISQUALIFIER_SECURITY_CLEARANCE,
        re.compile(
            r"\b(?:security|secret|top secret|ts/?sci)\b.*\bclearance\b",
            re.IGNORECASE,
        ),
    ),
    (
        HARD_DISQUALIFIER_SECURITY_CLEARANCE,
        re.compile(
            r"\bclearance\b.*\b(required|requires|must|active|eligible|obtain)\b",
            re.IGNORECASE,
        ),
    ),
)

SOFT_FLAG_PATTERNS = (
    re.compile(
        r"\b(?:no|without)\s+(?:employment\s+)?(?:visa\s+)?sponsorship\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:will not|won't|cannot|can't|do not|does not)\s+"
        r"(?:provide|offer|support)\s+(?:employment\s+)?(?:visa\s+)?sponsorship\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bauthorized to work\b.*\bwithout\b.*\bsponsorship\b",
        re.IGNORECASE,
    ),
)

SUMMARY_BLOCK_RE = re.compile(
    r"(?P<prefix>\\section\{SUMMARY\}\s*\\begin\{onecolentry\}\s*)(?P<summary>.*?)(?P<suffix>\s*\\end\{onecolentry\})",
    re.DOTALL,
)
TECHNICAL_SKILLS_BLOCK_RE = re.compile(
    r"(?P<prefix>\\section\{TECHNICAL SKILLS\}\s*)(?P<skills>(?:\\begin\{onecolentry\}.*?\\end\{onecolentry\}\s*)+)(?P<suffix>\\end\{document\})",
    re.DOTALL,
)
TECHNICAL_SKILL_LINE_RE = re.compile(
    r"\\begin\{onecolentry\}\s*\\textbf\{(?P<category>[^:]+):\}\s*(?P<items>.*?)\s*\\end\{onecolentry\}",
    re.DOTALL,
)
SOFTWARE_ENGINEER_BLOCK_RE = re.compile(
    r"(?P<prefix>\\textbf\{Software Engineer\}.*?\\end\{twocolentry\}\s*\\vspace\{0\.05cm\}\s*\\begin\{onecolentry\}\s*\\textit\{)"
    r"(?P<stack>[^}]*)"
    r"(?P<middle>\}\s*\\begin\{highlights\}\s*)"
    r"(?P<bullets>(?:\s*\\item .*?\n)+)"
    r"(?P<suffix>\s*\\end\{highlights\}\s*\\end\{onecolentry\})",
    re.DOTALL,
)
MARKDOWN_HEADING_RE = re.compile(r"^(?P<hashes>#+)\s+(?P<title>.+?)\s*$")
TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9.+/#-]*")
LEVEL_TOKEN_RE = re.compile(r"\b(intern|junior|mid|senior|staff|principal|lead)\b", re.IGNORECASE)
LOCATION_TOKEN_RE = re.compile(r"\b(remote|hybrid|on-site|onsite)\b", re.IGNORECASE)
EMPLOYMENT_TYPE_RE = re.compile(r"\b(full[- ]time|part[- ]time|contract|internship)\b", re.IGNORECASE)
NUMBER_WORD_METRIC_RE = re.compile(
    r"\b(one|two|three|four|five|six|seven|eight|nine|ten|twenty|thirty|forty|fifty)\b",
    re.IGNORECASE,
)
PAGES_RE = re.compile(r"^Pages:\s+(?P<pages>\d+)\s*$", re.MULTILINE)

COMMON_SIGNAL_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "any",
        "and",
        "as",
        "at",
        "by",
        "from",
        "the",
        "that",
        "this",
        "these",
        "those",
        "to",
        "of",
        "for",
        "with",
        "in",
        "on",
        "or",
        "our",
        "your",
        "you",
        "we",
        "will",
        "be",
        "is",
        "are",
        "using",
        "build",
        "develop",
        "experience",
        "more",
        "please",
        "visit",
    }
)
JD_HEADING_ONLY_PATTERNS = (
    re.compile(r"^(job description|job description summary|the company|required skills?(?:\s*&\s*experience)?|essential responsibilities|key responsibilities|responsibilities|what you(?:['’]ll| will) do|what you bring|minimum qualifications|qualifications|requirements|required qualifications?|preferred qualifications?|additional responsibilities(?:\s+and\s+preferred qualifications?)?|nice to have|our benefits|benefits(?: to support you)?|who we are|commitment to diversity and inclusion|belonging at .+|internal application policy)$", re.IGNORECASE),
    re.compile(r"^(lead with purpose\.?\s*partner with impact\.?)$", re.IGNORECASE),
)
JD_POLICY_LINE_PATTERNS = (
    re.compile(r"\bequal employment opportunity\b", re.IGNORECASE),
    re.compile(r"\bwithout discrimination\b", re.IGNORECASE),
    re.compile(r"\breasonable accommodations?\b", re.IGNORECASE),
    re.compile(r"\binternal applicants?\b", re.IGNORECASE),
    re.compile(r"\bbase pay range\b", re.IGNORECASE),
    re.compile(r"\bequity grade\b", re.IGNORECASE),
    re.compile(r"\bbenefits package\b", re.IGNORECASE),
    re.compile(r"\bremote-first company\b", re.IGNORECASE),
    re.compile(r"\bpay range\b", re.IGNORECASE),
    re.compile(r"\bconfidence gap\b", re.IGNORECASE),
    re.compile(r"\bimposter syndrome\b", re.IGNORECASE),
    re.compile(r"\btalent community\b", re.IGNORECASE),
    re.compile(r"\bred flag\b", re.IGNORECASE),
)
LOW_SIGNAL_PROFILE_SECTION_TERMS = frozenset(
    {
        "abstraction boundary",
        "interview safety",
        "scope boundary",
        "learning notes",
        "coursework",
        "personal",
    }
)
ROLE_FOCUS_AI_TERMS = frozenset(
    {
        "ai",
        "ai/ml",
        "agentic",
        "automation",
        "bedrock",
        "embeddings",
        "genai",
        "llm",
        "llms",
        "nlp",
        "prompt",
        "rag",
        "retrieval",
        "vector",
    }
)
ROLE_FOCUS_PLATFORM_TERMS = frozenset(
    {
        "automation",
        "azure",
        "bicep",
        "cloud",
        "governance",
        "iac",
        "infrastructure",
        "observability",
        "platform",
        "platform-engineering",
        "reliability",
        "terraform",
    }
)
ROLE_FOCUS_BACKEND_TERMS = frozenset(
    {
        "backend",
        "credit",
        "decisioning",
        "distributed",
        "kubernetes",
        "monitoring",
        "mysql",
        "python",
        "reliability",
        "scala",
        "underwriting",
    }
)
FRONTEND_AI_TERMS = frozenset(
    {
        "react",
        "typescript",
        "javascript",
        "node",
        "node.js",
        "frontend",
        "web",
        "mobile",
        "swift",
        "kotlin",
        "ui",
        "ux",
        "conversational",
        "llm",
        "ai",
        "ml",
        "agentic",
        "real-time",
    }
)
DISTRIBUTED_INFRA_TERMS = frozenset(
    {
        "python",
        "scala",
        "spark",
        "aws",
        "emr",
        "distributed",
        "reliability",
        "monitoring",
        "throughput",
        "etl",
        "hl7",
        "cloud",
        "pipeline",
        "kubernetes",
    }
)

TRACK_LIBRARY = {
    FRONTEND_AI_TRACK: {
        "summary": (
            "MS CS candidate with 3+ years of experience building full-stack applications and "
            "real-time AI-driven systems, focused on translating complex intelligent systems "
            "into intuitive, high-performance user experiences across web and mobile platforms"
        ),
        "technical_skills": [
            {
                "category": "Languages",
                "items": ["Python", "TypeScript", "JavaScript", "Kotlin", "Java", "Golang", "SQL"],
            },
            {
                "category": "Frontend \\& AI",
                "items": ["React", "Next.js", "Node.js", "Swift", "Android (Kotlin)", "LLMs", "Agentic AI"],
            },
            {
                "category": "Cloud \\& DevOps",
                "items": ["AWS (Lambda, S3, DynamoDB, API Gateway, EC2)", "Docker", "Kubernetes", "GitLab CI/CD"],
            },
            {
                "category": "Data \\& Storage",
                "items": ["PostgreSQL", "DynamoDB", "MongoDB", "Neo4j", "Redis"],
            },
            {
                "category": "Testing \\& Reliability",
                "items": ["Pytest", "JUnit", "Unit/Integration Testing", "Monitoring", "Performance Profiling"],
            },
        ],
        "software_engineer": {
            "tech_stack_line": (
                "Python, Spark, Databricks, Azure (ADF, ADLS Gen2), PostgreSQL, Tableau, "
                "Datadog, Docker, GitLab CI/CD"
            ),
            "bullets": [
                "Built real-time clinical data processing services ingesting 50M+ daily HL7 records (~580 TPS) from ICU bedside devices and patient monitors to power clinician-facing KPI dashboards across 1,500+ hospitals with 24/7 uptime",
                "Developed Spark pipelines transforming raw multi-EMR clinical data through bronze/silver/gold lakehouse layers into STAR schema tables consumed by Tableau dashboards, reducing data-to-dashboard turnaround by 40\\% to enable near real-time decisions",
                "Optimized 25+ Spark jobs on Databricks with parallel execution and Delta Lake caching, improving throughput by 50\\% (20K to 30K records/sec) and reducing data-to-dashboard latency for clinician-facing analytics",
                "Owned observability across multi-tenant clinical pipelines handling PHI --- monitoring, alerting, audit logging, and incident triage --- maintaining $\\geq$99\\% availability SLA in regulated environments where failures impact clinical workflows",
            ],
        },
    },
    DISTRIBUTED_INFRA_TRACK: {
        "summary": (
            "MS CS candidate with 3+ years of experience building large-scale distributed systems "
            "and data services, focused on reliable cloud infrastructure, performance "
            "optimization, and production-safe analytics delivery"
        ),
        "technical_skills": [
            {
                "category": "Languages",
                "items": ["Python", "Golang", "Java", "Scala", "SQL", "Bash", "C++"],
            },
            {
                "category": "Infrastructure \\& Systems",
                "items": ["Distributed Systems", "Microservices", "Load Balancing", "gRPC", "Protocol Buffers", "System Design"],
            },
            {
                "category": "Cloud \\& DevOps",
                "items": ["AWS (EMR, EC2, S3, Lambda, SQS)", "Kubernetes", "Docker", "Terraform", "GitLab CI/CD", "Linux"],
            },
            {
                "category": "Data \\& Storage",
                "items": ["Apache Spark", "PostgreSQL", "MySQL", "DynamoDB", "MongoDB", "Redis"],
            },
            {
                "category": "Testing \\& Reliability",
                "items": ["Pytest", "JUnit", "Unit/Integration Testing", "Monitoring", "Debugging", "Performance Profiling"],
            },
        ],
        "software_engineer": {
            "tech_stack_line": (
                "Python, Apache Spark, PostgreSQL, AWS (S3, EMR), Terraform, Docker, GitLab CI/CD"
            ),
            "bullets": [
                "Built and maintained distributed, high-availability clinical data services in Python and Scala on AWS (EMR, S3), processing 50M+ daily HL7 records (~580 TPS) for real-time analytics across 1,500+ hospitals with 24/7 uptime",
                "Developed Python and Apache Spark ETL pipelines with custom HL7 parsers, cutting processing time 40\\% from 6 hours to 3.6 hours on 2TB+ daily healthcare data so downstream clinical analytics stayed same-day and operationally dependable",
                "Optimized 25+ Apache Spark jobs with parallel execution and caching on AWS EMR, improving throughput by 50\\% from 20K to 30K records/sec while reducing monthly cloud spend by \\$15K and keeping time-sensitive analytics delivery stable",
                "Designed monitoring and alerting for production HL7 workflows, triaged data-quality issues, and resolved incidents against SLA expectations to support reliable analytics delivery for 1,500+ hospitals in a 24/7 production environment",
            ],
        },
    },
    GENERALIST_SWE_TRACK: {
        "summary": (
            "MS CS candidate with 3+ years of experience building production software across "
            "cloud, data, and AI-adjacent systems, focused on reliable delivery, measurable "
            "performance gains, and recruiter-readable product impact"
        ),
        "technical_skills": [
            {
                "category": "Languages",
                "items": ["Python", "Java", "TypeScript", "JavaScript", "Golang", "SQL", "Kotlin"],
            },
            {
                "category": "Application \\& Systems",
                "items": ["React", "Next.js", "Distributed Systems", "System Design", "Node.js", "Agentic AI"],
            },
            {
                "category": "Cloud \\& DevOps",
                "items": ["AWS (EMR, EC2, S3, Lambda, SQS)", "Kubernetes", "Docker", "GitLab CI/CD", "Linux"],
            },
            {
                "category": "Data \\& Storage",
                "items": ["Apache Spark", "PostgreSQL", "DynamoDB", "MongoDB", "Neo4j", "Redis"],
            },
            {
                "category": "Testing \\& Reliability",
                "items": ["Pytest", "JUnit", "Unit/Integration Testing", "Monitoring", "Performance Profiling"],
            },
        ],
        "software_engineer": {
            "tech_stack_line": "Python, Java, PostgreSQL, AWS, Docker, GitLab CI/CD, Spark, Kubernetes",
            "bullets": [
                "Built production data services in Python and Scala on AWS, processing 50M+ daily HL7 records (~580 TPS) with 24/7 uptime and reliable downstream analytics for 1,500+ hospitals",
                "Developed ETL and data-processing flows across Python, Apache Spark, and custom parsers, reducing runtime 40\\% from 6 hours to 3.6 hours on 2TB+ daily healthcare data while keeping same-day analytics delivery dependable",
                "Improved Spark throughput 50\\% across 25+ jobs through parallel execution and caching, keeping large-scale analytics delivery performant while reducing recurring infrastructure spend by \\$15K monthly across production workloads",
                "Owned monitoring, alerting, and incident triage for production HL7 workflows, resolving data-quality issues quickly enough to maintain SLA-aligned analytics delivery in a high-availability, always-on environment",
            ],
        },
    },
}


class ResumeTailoringError(RuntimeError):
    """Raised when resume-tailoring bootstrap cannot load required canonical state."""


@dataclass(frozen=True)
class EligibilityDecision:
    eligibility_status: str
    hard_disqualifiers_triggered: tuple[str, ...]
    soft_flags: tuple[str, ...]
    missing_data_fields: tuple[str, ...]
    decision_reason: str
    evidence_snippets: tuple[str, ...]
    recommended_note: str | None = None

    def as_payload(self) -> dict[str, Any]:
        return {
            "eligibility_status": self.eligibility_status,
            "hard_disqualifiers_triggered": list(self.hard_disqualifiers_triggered),
            "soft_flags": list(self.soft_flags),
            "missing_data_fields": list(self.missing_data_fields),
            "decision_reason": self.decision_reason,
            "evidence_snippets": list(self.evidence_snippets),
            "recommended_note": self.recommended_note,
        }


@dataclass(frozen=True)
class ResumeTailoringRunRecord:
    resume_tailoring_run_id: str
    job_posting_id: str
    base_used: str
    tailoring_status: str
    resume_review_status: str
    workspace_path: str
    meta_yaml_path: str | None
    final_resume_path: str | None
    verification_outcome: str | None
    started_at: str | None
    completed_at: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class TailoringBootstrapResult:
    job_posting_id: str
    lead_id: str
    company_name: str
    role_title: str
    posting_status: str
    eligibility: EligibilityDecision
    eligibility_artifact: PublishedArtifact
    run: ResumeTailoringRunRecord | None
    blocked_reason_code: str | None
    reused_existing_run: bool


@dataclass(frozen=True)
class TailoringIntelligenceResult:
    job_posting_id: str
    resume_tailoring_run_id: str | None
    track_name: str | None
    verification_outcome: str | None
    blocked_reason_code: str | None
    step_artifact_paths: dict[str, str]


@dataclass(frozen=True)
class TailoringFinalizeResult:
    job_posting_id: str
    resume_tailoring_run_id: str
    result: str
    reason_code: str | None
    run: ResumeTailoringRunRecord
    final_resume_path: str | None
    verification_outcome: str | None


@dataclass(frozen=True)
class TailoringReviewResult:
    job_posting_id: str
    resume_tailoring_run_id: str
    reviewer_type: str
    decision_type: str
    result: str
    reason_code: str | None
    run: ResumeTailoringRunRecord
    posting_status: str
    review_artifact: PublishedArtifact
    override_event: OverrideEventRecord | None = None


@dataclass(frozen=True)
class ParsedResumeDocument:
    summary: str
    technical_skills: list[dict[str, Any]]
    software_engineer_stack_line: str
    software_engineer_bullets: list[str]
    resume_wide_tokens: set[str]


def bootstrap_tailoring_run(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    job_posting_id: str,
    timestamp: str | None = None,
) -> TailoringBootstrapResult:
    current_time = timestamp or now_utc_iso()
    posting_row = _load_posting_row(connection, job_posting_id=job_posting_id)
    workspace_path = paths.tailoring_workspace_dir(
        posting_row["company_name"],
        posting_row["role_title"],
    )
    workspace_ref = paths.relative_to_root(workspace_path).as_posix()

    jd_path = _resolve_optional_project_path(paths, posting_row["jd_artifact_path"])
    if jd_path is None or not jd_path.exists():
        decision = EligibilityDecision(
            eligibility_status=ELIGIBILITY_STATUS_UNKNOWN,
            hard_disqualifiers_triggered=(),
            soft_flags=(),
            missing_data_fields=(MISSING_FIELD_EXPERIENCE, MISSING_FIELD_AUTHORIZATION),
            decision_reason=(
                "Resume Tailoring could not evaluate hard eligibility because the posting is "
                "missing a usable persisted `jd.md` artifact."
            ),
            evidence_snippets=(),
            recommended_note=None,
        )
        eligibility_artifact = _write_eligibility_artifact(
            connection,
            paths,
            posting_row=posting_row,
            decision=decision,
            result="blocked",
            current_time=current_time,
            workspace_ref=workspace_ref,
            base_used=None,
            active_run_id=None,
            bootstrap_ready=False,
            reason_code=BOOTSTRAP_REASON_MISSING_JD,
            message="Resume Tailoring requires a persisted `jd.md` artifact before bootstrap can begin.",
        )
        return TailoringBootstrapResult(
            job_posting_id=posting_row["job_posting_id"],
            lead_id=posting_row["lead_id"],
            company_name=posting_row["company_name"],
            role_title=posting_row["role_title"],
            posting_status=posting_row["posting_status"],
            eligibility=decision,
            eligibility_artifact=eligibility_artifact,
            run=None,
            blocked_reason_code=BOOTSTRAP_REASON_MISSING_JD,
            reused_existing_run=False,
        )

    jd_text = jd_path.read_text(encoding="utf-8")
    decision = evaluate_hard_eligibility(jd_text)
    run = None
    blocked_reason_code: str | None = None
    reused_existing_run = False
    base_used: str | None = None
    bootstrap_ready = False
    posting_status = str(posting_row["posting_status"])

    if decision.eligibility_status == ELIGIBILITY_STATUS_HARD_INELIGIBLE:
        posting_status = _set_job_posting_status(
            connection,
            job_posting_id=posting_row["job_posting_id"],
            lead_id=posting_row["lead_id"],
            previous_status=posting_status,
            new_status=JOB_POSTING_STATUS_HARD_INELIGIBLE,
            current_time=current_time,
            transition_reason="Resume Tailoring hard-eligibility gate short-circuited the posting.",
        )
    else:
        existing_run = get_latest_resume_tailoring_run_for_posting(
            connection,
            posting_row["job_posting_id"],
        )
        if existing_run is not None and not _run_requires_fresh_tailoring_attempt(existing_run):
            run = existing_run
            reused_existing_run = True
            base_used = existing_run.base_used
        else:
            if existing_run is not None:
                existing_run = _snapshot_completed_run_workspace(
                    connection,
                    paths,
                    posting_row=posting_row,
                    run=existing_run,
                    current_time=current_time,
                )
            selected_base = _select_base_resume_track(
                paths,
                role_title=posting_row["role_title"],
                jd_text=jd_text,
            )
            if selected_base is None:
                blocked_reason_code = BOOTSTRAP_REASON_MISSING_BASE_RESUME
            else:
                base_used, base_resume_source = selected_base
                run = _create_resume_tailoring_run(
                    connection,
                    posting_row=posting_row,
                    base_used=base_used,
                    workspace_ref=workspace_ref,
                    current_time=current_time,
                )
                run = _bootstrap_tailoring_workspace(
                    connection,
                    paths,
                    posting_row=posting_row,
                    run=run,
                    jd_path=jd_path,
                    base_resume_source=base_resume_source,
                    current_time=current_time,
                    overwrite=True,
                )

        if run is not None and blocked_reason_code is None:
            _sync_tailoring_input_mirrors(
                paths,
                posting_row=posting_row,
                jd_path=jd_path,
            )
            if not _workspace_bootstrap_is_complete(paths, posting_row=posting_row, run=run):
                base_resume_source = _resolve_base_resume_source(paths, base_used=run.base_used)
                resume_tex_path = paths.tailoring_resume_tex_path(
                    posting_row["company_name"],
                    posting_row["role_title"],
                )
                if base_resume_source is None and not resume_tex_path.exists():
                    blocked_reason_code = BOOTSTRAP_REASON_MISSING_BASE_RESUME
                else:
                    run = _bootstrap_tailoring_workspace(
                        connection,
                        paths,
                        posting_row=posting_row,
                        run=run,
                        jd_path=jd_path,
                        base_resume_source=base_resume_source,
                        current_time=current_time,
                        overwrite=False,
                    )
            bootstrap_ready = _workspace_bootstrap_is_complete(
                paths,
                posting_row=posting_row,
                run=run,
            )
            if bootstrap_ready:
                posting_status = _set_job_posting_status(
                    connection,
                    job_posting_id=posting_row["job_posting_id"],
                    lead_id=posting_row["lead_id"],
                    previous_status=posting_status,
                    new_status=JOB_POSTING_STATUS_TAILORING_IN_PROGRESS,
                    current_time=current_time,
                    transition_reason="Resume Tailoring bootstrap entered the active tailoring workspace stage.",
                )

    eligibility_artifact = _write_eligibility_artifact(
        connection,
        paths,
        posting_row=posting_row,
        decision=decision,
        result="blocked" if blocked_reason_code is not None else "success",
        current_time=current_time,
        workspace_ref=workspace_ref,
        base_used=base_used,
        active_run_id=run.resume_tailoring_run_id if run is not None else None,
        bootstrap_ready=bootstrap_ready,
        reason_code=blocked_reason_code,
        message=(
            "Resume Tailoring bootstrap requires at least one base resume track under "
            "`assets/resume-tailoring/base/`."
            if blocked_reason_code == BOOTSTRAP_REASON_MISSING_BASE_RESUME
            else None
        ),
    )
    return TailoringBootstrapResult(
        job_posting_id=posting_row["job_posting_id"],
        lead_id=posting_row["lead_id"],
        company_name=posting_row["company_name"],
        role_title=posting_row["role_title"],
        posting_status=posting_status,
        eligibility=decision,
        eligibility_artifact=eligibility_artifact,
        run=run,
        blocked_reason_code=blocked_reason_code,
        reused_existing_run=reused_existing_run,
    )


def evaluate_hard_eligibility(jd_text: str) -> EligibilityDecision:
    hard_disqualifiers: list[str] = []
    soft_flags: list[str] = []
    evidence_snippets: list[str] = []
    explicit_signal_found = False
    ambiguous_signal_found = False
    experience_signal_found = False
    authorization_signal_found = False

    for raw_line in jd_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        normalized = line.lower()

        experience_lower_bound = _extract_experience_lower_bound(normalized)
        if experience_lower_bound is not None:
            explicit_signal_found = True
            experience_signal_found = True
            if experience_lower_bound > 5:
                _append_unique(hard_disqualifiers, HARD_DISQUALIFIER_EXPERIENCE)
                _append_unique(evidence_snippets, line)
        elif AMBIGUOUS_EXPERIENCE_RE.search(normalized):
            ambiguous_signal_found = True
            _append_unique(evidence_snippets, line)

        for hard_code, pattern in HARD_REQUIREMENT_PATTERNS:
            if not pattern.search(line):
                continue
            explicit_signal_found = True
            authorization_signal_found = True
            _append_unique(hard_disqualifiers, hard_code)
            _append_unique(evidence_snippets, line)

        for pattern in SOFT_FLAG_PATTERNS:
            if not pattern.search(line):
                continue
            explicit_signal_found = True
            authorization_signal_found = True
            _append_unique(soft_flags, SOFT_FLAG_NO_SPONSORSHIP)
            _append_unique(evidence_snippets, line)
            break

    missing_data_fields: list[str] = []
    if not experience_signal_found:
        _append_unique(missing_data_fields, MISSING_FIELD_EXPERIENCE)
    if not authorization_signal_found:
        _append_unique(missing_data_fields, MISSING_FIELD_AUTHORIZATION)

    if hard_disqualifiers:
        return EligibilityDecision(
            eligibility_status=ELIGIBILITY_STATUS_HARD_INELIGIBLE,
            hard_disqualifiers_triggered=tuple(hard_disqualifiers),
            soft_flags=tuple(soft_flags),
            missing_data_fields=tuple(missing_data_fields),
            decision_reason=(
                "JD triggered the current hard-stop policy for Resume Tailoring."
            ),
            evidence_snippets=tuple(evidence_snippets),
            recommended_note=None,
        )

    if soft_flags:
        return EligibilityDecision(
            eligibility_status=ELIGIBILITY_STATUS_SOFT_FLAG,
            hard_disqualifiers_triggered=(),
            soft_flags=tuple(soft_flags),
            missing_data_fields=tuple(missing_data_fields),
            decision_reason=(
                "JD includes a no-sponsorship constraint, so the posting remains eligible with "
                "a soft flag for downstream context."
            ),
            evidence_snippets=tuple(evidence_snippets),
            recommended_note=(
                "Mention current OPT work authorization and the no-sponsorship constraint in "
                "later operator-facing context."
            ),
        )

    if explicit_signal_found:
        return EligibilityDecision(
            eligibility_status=ELIGIBILITY_STATUS_ELIGIBLE,
            hard_disqualifiers_triggered=(),
            soft_flags=(),
            missing_data_fields=tuple(missing_data_fields),
            decision_reason=(
                "The JD includes explicit eligibility-related signals and none of them trigger "
                "the current hard-stop policy."
            ),
            evidence_snippets=tuple(evidence_snippets),
            recommended_note=None,
        )

    if ambiguous_signal_found:
        reason = (
            "The JD mentions eligibility-related requirements without an explicit hard-stop "
            "threshold, so the posting remains `unknown` and may continue."
        )
    else:
        reason = (
            "The JD does not provide explicit hard-eligibility language, so the posting remains "
            "`unknown` and may continue."
        )
    return EligibilityDecision(
        eligibility_status=ELIGIBILITY_STATUS_UNKNOWN,
        hard_disqualifiers_triggered=(),
        soft_flags=(),
        missing_data_fields=tuple(missing_data_fields),
        decision_reason=reason,
        evidence_snippets=tuple(evidence_snippets),
        recommended_note=None,
    )


def get_resume_tailoring_run(
    connection: sqlite3.Connection,
    resume_tailoring_run_id: str,
) -> ResumeTailoringRunRecord | None:
    row = connection.execute(
        """
        SELECT resume_tailoring_run_id, job_posting_id, base_used, tailoring_status,
               resume_review_status, workspace_path, meta_yaml_path, final_resume_path,
               verification_outcome, started_at, completed_at, created_at, updated_at
        FROM resume_tailoring_runs
        WHERE resume_tailoring_run_id = ?
        """,
        (resume_tailoring_run_id,),
    ).fetchone()
    return None if row is None else _resume_tailoring_run_from_row(row)


def get_latest_resume_tailoring_run_for_posting(
    connection: sqlite3.Connection,
    job_posting_id: str,
) -> ResumeTailoringRunRecord | None:
    row = connection.execute(
        """
        SELECT resume_tailoring_run_id, job_posting_id, base_used, tailoring_status,
               resume_review_status, workspace_path, meta_yaml_path, final_resume_path,
               verification_outcome, started_at, completed_at, created_at, updated_at
        FROM resume_tailoring_runs
        WHERE job_posting_id = ?
        ORDER BY created_at DESC, resume_tailoring_run_id DESC
        LIMIT 1
        """,
        (job_posting_id,),
    ).fetchone()
    return None if row is None else _resume_tailoring_run_from_row(row)


def _load_posting_row(
    connection: sqlite3.Connection,
    *,
    job_posting_id: str,
) -> sqlite3.Row:
    row = connection.execute(
        """
        SELECT job_posting_id, lead_id, company_name, role_title, posting_status, jd_artifact_path
        FROM job_postings
        WHERE job_posting_id = ?
        """,
        (job_posting_id,),
    ).fetchone()
    if row is None:
        raise ResumeTailoringError(f"Job posting `{job_posting_id}` was not found.")
    return row


def _resolve_optional_project_path(paths: ProjectPaths, artifact_path: str | None) -> Path | None:
    if artifact_path is None:
        return None
    stripped = str(artifact_path).strip()
    if not stripped:
        return None
    return paths.resolve_from_root(stripped)


def _select_base_resume_track(
    paths: ProjectPaths,
    *,
    role_title: str,
    jd_text: str,
) -> tuple[str, Path] | None:
    candidates = paths.base_resume_sources()
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0].parent.name, candidates[0]

    ranking_text = f"{role_title}\n{jd_text}".lower()
    best_source = candidates[0]
    best_score = _base_track_score(best_source, ranking_text)
    for candidate in candidates[1:]:
        candidate_score = _base_track_score(candidate, ranking_text)
        if candidate_score > best_score:
            best_source = candidate
            best_score = candidate_score
    return best_source.parent.name, best_source


def _base_track_score(base_resume_path: Path, ranking_text: str) -> int:
    track_tokens = [token for token in re.split(r"[^a-z0-9]+", base_resume_path.parent.name.lower()) if token]
    return sum(1 for token in track_tokens if token in ranking_text)


def _resolve_base_resume_source(paths: ProjectPaths, *, base_used: str) -> Path | None:
    for candidate in paths.base_resume_sources():
        if candidate.parent.name == base_used:
            return candidate
    return None


def _write_eligibility_artifact(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    posting_row: Mapping[str, Any],
    decision: EligibilityDecision,
    result: str,
    current_time: str,
    workspace_ref: str,
    base_used: str | None,
    active_run_id: str | None,
    bootstrap_ready: bool,
    reason_code: str | None = None,
    message: str | None = None,
) -> PublishedArtifact:
    eligibility_path = paths.tailoring_eligibility_path(
        posting_row["company_name"],
        posting_row["role_title"],
    )
    jd_artifact_path = posting_row["jd_artifact_path"]
    jd_ref = (
        paths.relative_to_root(jd_artifact_path).as_posix()
        if jd_artifact_path
        else None
    )
    contract = write_yaml_contract(
        eligibility_path,
        producer_component=RESUME_TAILORING_COMPONENT,
        result=result,
        linkage=ArtifactLinkage(
            lead_id=posting_row["lead_id"],
            job_posting_id=posting_row["job_posting_id"],
        ),
        payload={
            **decision.as_payload(),
            "jd_artifact_ref": jd_ref,
            "workspace_path": workspace_ref,
            "base_used": base_used,
            "active_resume_tailoring_run_id": active_run_id,
            "bootstrap_ready": bootstrap_ready,
            "bootstrap_blockers": [reason_code] if reason_code else [],
        },
        produced_at=current_time,
        reason_code=reason_code,
        message=message,
    )
    with connection:
        connection.execute(
            """
            DELETE FROM artifact_records
            WHERE artifact_type = ? AND job_posting_id = ?
            """,
            (
                TAILORING_ELIGIBILITY_ARTIFACT_TYPE,
                posting_row["job_posting_id"],
            ),
        )
        record = register_artifact_record(
            connection,
            paths,
            artifact_type=TAILORING_ELIGIBILITY_ARTIFACT_TYPE,
            artifact_path=eligibility_path,
            producer_component=RESUME_TAILORING_COMPONENT,
            linkage=ArtifactLinkage(
                lead_id=posting_row["lead_id"],
                job_posting_id=posting_row["job_posting_id"],
            ),
            created_at=contract["produced_at"],
        )
    return PublishedArtifact(
        location=artifact_location(paths, eligibility_path),
        contract=contract,
        record=record,
    )


def _create_resume_tailoring_run(
    connection: sqlite3.Connection,
    *,
    posting_row: Mapping[str, Any],
    base_used: str,
    workspace_ref: str,
    current_time: str,
) -> ResumeTailoringRunRecord:
    timestamps = lifecycle_timestamps(current_time)
    run_id = new_canonical_id("resume_tailoring_runs")
    with connection:
        connection.execute(
            """
            INSERT INTO resume_tailoring_runs (
              resume_tailoring_run_id, job_posting_id, base_used, tailoring_status,
              resume_review_status, workspace_path, meta_yaml_path, final_resume_path,
              verification_outcome, started_at, completed_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                posting_row["job_posting_id"],
                base_used,
                TAILORING_STATUS_IN_PROGRESS,
                RESUME_REVIEW_STATUS_NOT_READY,
                workspace_ref,
                None,
                None,
                None,
                current_time,
                None,
                timestamps["created_at"],
                timestamps["updated_at"],
            ),
        )
        _record_state_transition(
            connection,
            object_type="resume_tailoring_runs",
            object_id=run_id,
            stage="tailoring_status",
            previous_state="not_created",
            new_state=TAILORING_STATUS_IN_PROGRESS,
            transition_timestamp=current_time,
            transition_reason="Resume Tailoring bootstrap created the first run row for the posting.",
            lead_id=posting_row["lead_id"],
            job_posting_id=posting_row["job_posting_id"],
        )
        _record_state_transition(
            connection,
            object_type="resume_tailoring_runs",
            object_id=run_id,
            stage="resume_review_status",
            previous_state="not_created",
            new_state=RESUME_REVIEW_STATUS_NOT_READY,
            transition_timestamp=current_time,
            transition_reason="Resume Tailoring bootstrap initialized the review gate as not ready.",
            lead_id=posting_row["lead_id"],
            job_posting_id=posting_row["job_posting_id"],
        )
    created = get_resume_tailoring_run(connection, run_id)
    if created is None:
        raise ResumeTailoringError(
            f"Failed to load resume_tailoring_run `{run_id}` after creation."
        )
    return created


def _workspace_bootstrap_is_complete(
    paths: ProjectPaths,
    *,
    posting_row: Mapping[str, Any],
    run: ResumeTailoringRunRecord,
) -> bool:
    meta_path = _resolve_optional_project_path(paths, run.meta_yaml_path)
    required_paths = (
        meta_path,
        paths.tailoring_workspace_jd_path(posting_row["company_name"], posting_row["role_title"]),
        paths.tailoring_resume_tex_path(posting_row["company_name"], posting_row["role_title"]),
        paths.tailoring_scope_baseline_path(posting_row["company_name"], posting_row["role_title"]),
        paths.tailoring_intelligence_manifest_path(posting_row["company_name"], posting_row["role_title"]),
        paths.tailoring_step_3_jd_signals_path(posting_row["company_name"], posting_row["role_title"]),
        paths.tailoring_step_4_evidence_map_path(posting_row["company_name"], posting_row["role_title"]),
        paths.tailoring_step_5_context_path(posting_row["company_name"], posting_row["role_title"]),
        paths.tailoring_step_6_candidate_bullets_path(posting_row["company_name"], posting_row["role_title"]),
        paths.tailoring_step_7_verification_path(posting_row["company_name"], posting_row["role_title"]),
    )
    return all(path is not None and path.exists() for path in required_paths)


def _sync_tailoring_input_mirrors(
    paths: ProjectPaths,
    *,
    posting_row: Mapping[str, Any],
    jd_path: Path,
) -> None:
    _copy_text_file(
        paths.assets_dir / "resume-tailoring" / "profile.md",
        paths.tailoring_input_profile_path,
        overwrite=True,
    )
    _copy_text_file(
        jd_path,
        paths.tailoring_input_job_posting_path(
            posting_row["company_name"],
            posting_row["role_title"],
        ),
        overwrite=True,
    )


def _bootstrap_tailoring_workspace(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    posting_row: Mapping[str, Any],
    run: ResumeTailoringRunRecord,
    jd_path: Path,
    base_resume_source: Path | None,
    current_time: str,
    overwrite: bool,
) -> ResumeTailoringRunRecord:
    workspace_dir = paths.tailoring_workspace_dir(
        posting_row["company_name"],
        posting_row["role_title"],
    )
    resume_tex_path = paths.tailoring_resume_tex_path(
        posting_row["company_name"],
        posting_row["role_title"],
    )
    scope_baseline_path = paths.tailoring_scope_baseline_path(
        posting_row["company_name"],
        posting_row["role_title"],
    )
    workspace_dir.mkdir(parents=True, exist_ok=True)

    if overwrite or not resume_tex_path.exists():
        if base_resume_source is None:
            raise ResumeTailoringError(
                f"Base resume track `{run.base_used}` is unavailable for workspace bootstrap."
            )
        _copy_text_file(base_resume_source, resume_tex_path, overwrite=True)
    if overwrite or not scope_baseline_path.exists():
        scope_baseline_path.write_text(resume_tex_path.read_text(encoding="utf-8"), encoding="utf-8")

    _copy_text_file(
        jd_path,
        paths.tailoring_workspace_jd_path(posting_row["company_name"], posting_row["role_title"]),
        overwrite=overwrite,
    )
    _sync_optional_workspace_context(
        paths,
        posting_row=posting_row,
        overwrite=overwrite,
    )
    _write_intelligence_scaffolds(
        paths,
        posting_row=posting_row,
        run=run,
        current_time=current_time,
        overwrite=overwrite,
    )
    _publish_tailoring_meta_artifact(
        connection,
        paths,
        posting_row=posting_row,
        run=run,
        current_time=current_time,
    )
    refreshed_run = get_resume_tailoring_run(connection, run.resume_tailoring_run_id)
    if refreshed_run is None:
        raise ResumeTailoringError(
            f"Failed to reload resume_tailoring_run `{run.resume_tailoring_run_id}` after workspace bootstrap."
        )
    return refreshed_run


def _sync_optional_workspace_context(
    paths: ProjectPaths,
    *,
    posting_row: Mapping[str, Any],
    overwrite: bool,
) -> None:
    optional_sources = (
        (
            paths.lead_post_path(
                posting_row["company_name"],
                posting_row["role_title"],
                posting_row["lead_id"],
            ),
            paths.tailoring_workspace_post_path(
                posting_row["company_name"],
                posting_row["role_title"],
            ),
        ),
        (
            paths.lead_poster_profile_path(
                posting_row["company_name"],
                posting_row["role_title"],
                posting_row["lead_id"],
            ),
            paths.tailoring_workspace_poster_profile_path(
                posting_row["company_name"],
                posting_row["role_title"],
            ),
        ),
    )
    for source_path, target_path in optional_sources:
        if source_path.exists():
            _copy_text_file(source_path, target_path, overwrite=overwrite)
        elif overwrite and target_path.exists():
            target_path.unlink()


def _write_intelligence_scaffolds(
    paths: ProjectPaths,
    *,
    posting_row: Mapping[str, Any],
    run: ResumeTailoringRunRecord,
    current_time: str,
    overwrite: bool,
) -> None:
    company_name = posting_row["company_name"]
    role_title = posting_row["role_title"]
    intelligence_dir = paths.tailoring_intelligence_dir(company_name, role_title)
    prompts_dir = paths.tailoring_prompts_dir(company_name, role_title)
    intelligence_dir.mkdir(parents=True, exist_ok=True)
    prompts_dir.mkdir(parents=True, exist_ok=True)

    workspace_path = paths.tailoring_workspace_dir(company_name, role_title).resolve()
    workspace_jd_path = paths.tailoring_workspace_jd_path(company_name, role_title).resolve()
    profile_path = paths.tailoring_input_profile_path.resolve()
    job_context_path = paths.tailoring_input_job_posting_path(company_name, role_title).resolve()
    resume_tex_path = paths.tailoring_resume_tex_path(company_name, role_title).resolve()

    _write_yaml_file(
        paths.tailoring_intelligence_manifest_path(company_name, role_title),
        {
            "job_posting_id": posting_row["job_posting_id"],
            "resume_tailoring_run_id": run.resume_tailoring_run_id,
            "bootstrap_timestamp": current_time,
            "workspace_path": str(workspace_path),
            "prompts_dir": str(prompts_dir.resolve()),
            "steps": {
                "step_3_jd_signals": {
                    "status": INTELLIGENCE_STATUS_NOT_STARTED,
                    "artifact_path": str(paths.tailoring_step_3_jd_signals_path(company_name, role_title).resolve()),
                },
                "step_4_evidence_map": {
                    "status": INTELLIGENCE_STATUS_NOT_STARTED,
                    "artifact_path": str(paths.tailoring_step_4_evidence_map_path(company_name, role_title).resolve()),
                },
                "step_5_elaborated_swe_context": {
                    "status": INTELLIGENCE_STATUS_NOT_STARTED,
                    "artifact_path": str(paths.tailoring_step_5_context_path(company_name, role_title).resolve()),
                },
                "step_6_candidate_resume_edits": {
                    "status": INTELLIGENCE_STATUS_NOT_STARTED,
                    "artifact_path": str(
                        paths.tailoring_step_6_candidate_bullets_path(company_name, role_title).resolve()
                    ),
                },
                "step_7_verification": {
                    "status": INTELLIGENCE_STATUS_PENDING,
                    "artifact_path": str(paths.tailoring_step_7_verification_path(company_name, role_title).resolve()),
                },
            },
        },
        overwrite=overwrite,
    )
    _write_yaml_file(
        paths.tailoring_step_3_jd_signals_path(company_name, role_title),
        {
            "job_posting_id": posting_row["job_posting_id"],
            "resume_tailoring_run_id": run.resume_tailoring_run_id,
            "status": INTELLIGENCE_STATUS_NOT_STARTED,
            "context_file": str(workspace_jd_path),
            "signal_priority_weights": {
                "must_have": 1.00,
                "core_responsibility": 0.75,
                "nice_to_have": 0.40,
                "informational": 0.15,
            },
            "signals": [],
        },
        overwrite=overwrite,
    )
    _write_yaml_file(
        paths.tailoring_step_4_evidence_map_path(company_name, role_title),
        {
            "job_posting_id": posting_row["job_posting_id"],
            "resume_tailoring_run_id": run.resume_tailoring_run_id,
            "status": INTELLIGENCE_STATUS_NOT_STARTED,
            "profile_file": str(profile_path),
            "job_context_file": str(job_context_path),
            "resume_file": str(resume_tex_path),
            "matches": [],
            "gaps": [],
        },
        overwrite=overwrite,
    )
    _write_text_file(
        paths.tailoring_step_5_context_path(company_name, role_title),
        (
            "# Step 5 Elaborated SWE Context\n\n"
            f"- job_posting_id: {posting_row['job_posting_id']}\n"
            f"- resume_tailoring_run_id: {run.resume_tailoring_run_id}\n"
            f"- status: {INTELLIGENCE_STATUS_NOT_STARTED}\n\n"
            "## Selected Pipeline Scope\n\n"
            "Not generated yet.\n\n"
            "## Controlled Elaboration\n\n"
            "Not generated yet.\n\n"
            "## Claim Ledger\n\n"
            "Not generated yet.\n\n"
            "## Interview-Safe Narrative\n\n"
            "Not generated yet.\n"
        ),
        overwrite=overwrite,
    )
    _write_yaml_file(
        paths.tailoring_step_6_candidate_bullets_path(company_name, role_title),
        {
            "job_posting_id": posting_row["job_posting_id"],
            "resume_tailoring_run_id": run.resume_tailoring_run_id,
            "status": INTELLIGENCE_STATUS_NOT_STARTED,
            "summary": None,
            "technical_skills": [],
            "software_engineer": {
                "tech_stack_line": None,
                "bullets": [],
            },
            "support_pointers": [],
            "blockers": [],
        },
        overwrite=overwrite,
    )
    _write_yaml_file(
        paths.tailoring_step_7_verification_path(company_name, role_title),
        {
            "job_posting_id": posting_row["job_posting_id"],
            "resume_tailoring_run_id": run.resume_tailoring_run_id,
            "status": INTELLIGENCE_STATUS_PENDING,
            "verification_outcome": "pending",
            "checks": [
                {
                    "check_id": check_id,
                    "status": INTELLIGENCE_STATUS_PENDING,
                    "notes": [],
                }
                for check_id in STEP_7_CHECK_IDS
            ],
            "blockers": [],
            "revision_guidance": [],
        },
        overwrite=overwrite,
    )


def _publish_tailoring_meta_artifact(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    posting_row: Mapping[str, Any],
    run: ResumeTailoringRunRecord,
    current_time: str,
) -> PublishedArtifact:
    company_name = posting_row["company_name"]
    role_title = posting_row["role_title"]
    meta_path = paths.tailoring_meta_path(company_name, role_title)
    workspace_jd_path = paths.tailoring_workspace_jd_path(company_name, role_title).resolve()
    workspace_post_path = paths.tailoring_workspace_post_path(company_name, role_title).resolve()
    workspace_poster_profile_path = paths.tailoring_workspace_poster_profile_path(
        company_name,
        role_title,
    ).resolve()
    final_resume_path = _resolve_optional_project_path(paths, run.final_resume_path)
    latest_review_contract = _load_latest_tailoring_review_contract(
        connection,
        paths,
        posting_row=posting_row,
        run=run,
    )
    payload = {
        "resume_tailoring_run_id": run.resume_tailoring_run_id,
        "base_used": run.base_used,
        "context_file": str(workspace_jd_path),
        "context_files": {
            "jd": str(workspace_jd_path),
            "post": str(workspace_post_path) if workspace_post_path.exists() else None,
            "poster_profile": (
                str(workspace_poster_profile_path) if workspace_poster_profile_path.exists() else None
            ),
            "working_job_context": str(
                paths.tailoring_input_job_posting_path(company_name, role_title).resolve()
            ),
            "profile": str(paths.tailoring_input_profile_path.resolve()),
        },
        "scope_baseline_file": str(paths.tailoring_scope_baseline_path(company_name, role_title).resolve()),
        "section_locks": list(DEFAULT_SECTION_LOCKS),
        "experience_role_allowlist": list(DEFAULT_EXPERIENCE_ROLE_ALLOWLIST),
        "tailoring_status": run.tailoring_status,
        "resume_review_status": run.resume_review_status,
        "workspace_path": str(paths.tailoring_workspace_dir(company_name, role_title).resolve()),
        "resume_artifacts": {
            "tex_path": str(paths.tailoring_resume_tex_path(company_name, role_title).resolve()),
            "pdf_path": str(final_resume_path.resolve()) if final_resume_path is not None else None,
        },
        "review_gate": {
            "history_dir": str(
                paths.tailoring_review_run_dir(
                    company_name,
                    role_title,
                    run.resume_tailoring_run_id,
                ).resolve()
            ),
            "latest_decision_type": (
                latest_review_contract.get("decision_type")
                if latest_review_contract is not None
                else None
            ),
            "latest_reviewer_type": (
                latest_review_contract.get("reviewer_type")
                if latest_review_contract is not None
                else None
            ),
            "latest_reviewed_at": (
                latest_review_contract.get("reviewed_at")
                if latest_review_contract is not None
                else None
            ),
            "latest_decision_path": (
                str(
                    paths.resolve_from_root(
                        str(latest_review_contract["artifact_path"])
                    ).resolve()
                )
                if latest_review_contract is not None
                and latest_review_contract.get("artifact_path")
                else None
            ),
            "override_event_id": (
                latest_review_contract.get("override_event_id")
                if latest_review_contract is not None
                else None
            ),
        },
        "send_linkage": {
            "outreach_mode": "role_targeted",
            "resume_required": True,
        },
    }
    with connection:
        connection.execute(
            """
            DELETE FROM artifact_records
            WHERE artifact_type = ? AND job_posting_id = ?
            """,
            (
                TAILORING_META_ARTIFACT_TYPE,
                posting_row["job_posting_id"],
            ),
        )
    artifact = publish_yaml_artifact(
        connection,
        paths,
        artifact_type=TAILORING_META_ARTIFACT_TYPE,
        artifact_path=meta_path,
        producer_component=RESUME_TAILORING_COMPONENT,
        result="success",
        linkage=ArtifactLinkage(
            lead_id=posting_row["lead_id"],
            job_posting_id=posting_row["job_posting_id"],
        ),
        payload=payload,
        produced_at=current_time,
    )
    meta_ref = paths.relative_to_root(meta_path).as_posix()
    with connection:
        connection.execute(
            """
            UPDATE resume_tailoring_runs
            SET meta_yaml_path = ?, updated_at = ?
            WHERE resume_tailoring_run_id = ?
            """,
            (
                meta_ref,
                current_time,
                run.resume_tailoring_run_id,
            ),
        )
    return artifact


def _copy_text_file(source_path: Path, target_path: Path, *, overwrite: bool) -> None:
    if not overwrite and target_path.exists():
        return
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(source_path.read_text(encoding="utf-8"), encoding="utf-8")


def _write_yaml_file(path: Path, payload: Mapping[str, Any], *, overwrite: bool) -> None:
    if not overwrite and path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(dict(payload), sort_keys=False), encoding="utf-8")


def _write_text_file(path: Path, content: str, *, overwrite: bool) -> None:
    if not overwrite and path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _set_job_posting_status(
    connection: sqlite3.Connection,
    *,
    job_posting_id: str,
    lead_id: str,
    previous_status: str,
    new_status: str,
    current_time: str,
    transition_reason: str,
) -> str:
    if previous_status == new_status:
        return new_status
    with connection:
        connection.execute(
            """
            UPDATE job_postings
            SET posting_status = ?, updated_at = ?
            WHERE job_posting_id = ?
            """,
            (
                new_status,
                current_time,
                job_posting_id,
            ),
        )
        _record_state_transition(
            connection,
            object_type="job_postings",
            object_id=job_posting_id,
            stage="posting_status",
            previous_state=previous_status,
            new_state=new_status,
            transition_timestamp=current_time,
            transition_reason=transition_reason,
            lead_id=lead_id,
            job_posting_id=job_posting_id,
        )
    return new_status


def _record_state_transition(
    connection: sqlite3.Connection,
    *,
    object_type: str,
    object_id: str,
    stage: str,
    previous_state: str,
    new_state: str,
    transition_timestamp: str,
    transition_reason: str | None,
    lead_id: str | None,
    job_posting_id: str | None,
) -> None:
    connection.execute(
        """
        INSERT INTO state_transition_events (
          state_transition_event_id, object_type, object_id, stage, previous_state,
          new_state, transition_timestamp, transition_reason, caused_by, lead_id,
          job_posting_id, contact_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            new_canonical_id("state_transition_events"),
            object_type,
            object_id,
            stage,
            previous_state,
            new_state,
            transition_timestamp,
            transition_reason,
            RESUME_TAILORING_COMPONENT,
            lead_id,
            job_posting_id,
            None,
        ),
    )


def _run_requires_fresh_tailoring_attempt(run: ResumeTailoringRunRecord) -> bool:
    return run.resume_review_status in {
        RESUME_REVIEW_STATUS_APPROVED,
        RESUME_REVIEW_STATUS_REJECTED,
    }


def _snapshot_completed_run_workspace(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    posting_row: Mapping[str, Any],
    run: ResumeTailoringRunRecord,
    current_time: str,
) -> ResumeTailoringRunRecord:
    if not _run_requires_fresh_tailoring_attempt(run):
        return run

    company_name = str(posting_row["company_name"])
    role_title = str(posting_row["role_title"])
    live_workspace_dir = paths.tailoring_workspace_dir(company_name, role_title)
    if not live_workspace_dir.exists():
        return run

    snapshot_dir = paths.tailoring_run_snapshot_dir(
        company_name,
        role_title,
        run.resume_tailoring_run_id,
        _timestamp_slug(current_time),
    )
    snapshot_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(live_workspace_dir, snapshot_dir)
    _rewrite_snapshot_meta_paths(
        snapshot_dir=snapshot_dir,
        live_workspace_dir=live_workspace_dir,
    )

    snapshot_workspace_ref = paths.relative_to_root(snapshot_dir).as_posix()
    snapshot_meta_path = snapshot_dir / "meta.yaml"
    snapshot_meta_ref = (
        paths.relative_to_root(snapshot_meta_path).as_posix()
        if snapshot_meta_path.exists()
        else run.meta_yaml_path
    )
    snapshot_final_resume_ref = _snapshot_workspace_reference(
        paths,
        live_workspace_dir=live_workspace_dir,
        snapshot_dir=snapshot_dir,
        original_ref=run.final_resume_path,
    )

    with connection:
        connection.execute(
            """
            UPDATE resume_tailoring_runs
            SET workspace_path = ?, meta_yaml_path = ?, final_resume_path = ?, updated_at = ?
            WHERE resume_tailoring_run_id = ?
            """,
            (
                snapshot_workspace_ref,
                snapshot_meta_ref,
                snapshot_final_resume_ref,
                current_time,
                run.resume_tailoring_run_id,
            ),
        )
    refreshed_run = get_resume_tailoring_run(connection, run.resume_tailoring_run_id)
    if refreshed_run is None:
        raise ResumeTailoringError(
            f"Failed to reload resume_tailoring_run `{run.resume_tailoring_run_id}` after snapshotting."
        )
    return refreshed_run


def _rewrite_snapshot_meta_paths(
    *,
    snapshot_dir: Path,
    live_workspace_dir: Path,
) -> None:
    snapshot_meta_path = snapshot_dir / "meta.yaml"
    if not snapshot_meta_path.exists():
        return

    payload = yaml.safe_load(snapshot_meta_path.read_text(encoding="utf-8")) or {}

    def remap(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        path = Path(text).resolve()
        try:
            relative = path.relative_to(live_workspace_dir.resolve())
        except ValueError:
            return text
        return str((snapshot_dir / relative).resolve())

    payload["workspace_path"] = str(snapshot_dir.resolve())
    payload["context_file"] = remap(payload.get("context_file"))
    context_files = dict(payload.get("context_files") or {})
    for key in ("jd", "post", "poster_profile"):
        context_files[key] = remap(context_files.get(key))
    payload["context_files"] = context_files
    payload["scope_baseline_file"] = remap(payload.get("scope_baseline_file"))
    resume_artifacts = dict(payload.get("resume_artifacts") or {})
    resume_artifacts["tex_path"] = remap(resume_artifacts.get("tex_path"))
    resume_artifacts["pdf_path"] = remap(resume_artifacts.get("pdf_path"))
    payload["resume_artifacts"] = resume_artifacts
    review_gate = dict(payload.get("review_gate") or {})
    review_gate["history_dir"] = remap(review_gate.get("history_dir"))
    review_gate["latest_decision_path"] = remap(review_gate.get("latest_decision_path"))
    payload["review_gate"] = review_gate

    snapshot_meta_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _snapshot_workspace_reference(
    paths: ProjectPaths,
    *,
    live_workspace_dir: Path,
    snapshot_dir: Path,
    original_ref: str | None,
) -> str | None:
    original_path = _resolve_optional_project_path(paths, original_ref)
    if original_path is None:
        return None
    try:
        relative = original_path.resolve().relative_to(live_workspace_dir.resolve())
    except ValueError:
        return original_ref
    snapshot_path = snapshot_dir / relative
    if not snapshot_path.exists():
        return None
    return paths.relative_to_root(snapshot_path).as_posix()


def _timestamp_slug(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z]+", "", value)


def _load_latest_tailoring_review_contract(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    posting_row: Mapping[str, Any],
    run: ResumeTailoringRunRecord,
) -> dict[str, Any] | None:
    review_dir_ref = paths.relative_to_root(
        paths.tailoring_review_run_dir(
            str(posting_row["company_name"]),
            str(posting_row["role_title"]),
            run.resume_tailoring_run_id,
        )
    ).as_posix()
    row = connection.execute(
        """
        SELECT file_path
        FROM artifact_records
        WHERE artifact_type = ?
          AND job_posting_id = ?
          AND file_path LIKE ?
        ORDER BY created_at DESC, artifact_id DESC
        LIMIT 1
        """,
        (
            TAILORING_REVIEW_ARTIFACT_TYPE,
            posting_row["job_posting_id"],
            f"{review_dir_ref}/%",
        ),
    ).fetchone()
    if row is None:
        return None

    artifact_path = paths.resolve_from_root(str(row["file_path"]))
    if not artifact_path.exists():
        return None
    contract = yaml.safe_load(artifact_path.read_text(encoding="utf-8")) or {}
    contract["artifact_path"] = str(row["file_path"])
    return contract


def _current_review_decision_context(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    posting_row: Mapping[str, Any],
    run: ResumeTailoringRunRecord,
) -> dict[str, Any]:
    latest_contract = _load_latest_tailoring_review_contract(
        connection,
        paths,
        posting_row=posting_row,
        run=run,
    )
    if latest_contract is not None:
        return {
            "decision_type": latest_contract.get("decision_type"),
            "reviewer_type": latest_contract.get("reviewer_type"),
            "reviewed_at": latest_contract.get("reviewed_at"),
            "artifact_path": latest_contract.get("artifact_path"),
            "override_event_id": latest_contract.get("override_event_id"),
        }
    return {
        "decision_type": (
            run.resume_review_status
            if run.resume_review_status in TAILORING_REVIEW_DECISION_TYPES
            else None
        ),
        "reviewer_type": None,
        "reviewed_at": None,
        "artifact_path": None,
        "override_event_id": None,
    }


def _evaluate_post_review_outreach_handoff(
    connection: sqlite3.Connection,
    job_posting_id: str,
) -> dict[str, Any]:
    return evaluate_role_targeted_send_set(
        connection,
        job_posting_id=job_posting_id,
        current_time=now_utc_iso(),
    ).as_dict()


def _apply_tailoring_review_outcome(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    posting_row: Mapping[str, Any],
    run: ResumeTailoringRunRecord,
    decision_type: str,
    decision_notes: str | None,
    reviewer_type: str,
    current_time: str,
    previous_decision_context: Mapping[str, Any],
    override_event: OverrideEventRecord | None,
    handoff: Mapping[str, Any] | None = None,
) -> TailoringReviewResult:
    if decision_type == RESUME_REVIEW_STATUS_APPROVED:
        handoff_details = dict(
            handoff
            or _evaluate_post_review_outreach_handoff(connection, run.job_posting_id)
        )
        posting_status_after_review = str(handoff_details["posting_status_after_review"])
        transition_reason = (
            "Mandatory tailoring review approved the current tailored output and advanced the "
            "posting to the next DB-first outreach handoff state."
            if override_event is None
            else "Owner override approved the current tailored output and advanced the posting."
        )
        artifact_result = "success"
        reason_code = None
        message = None
    else:
        handoff_details = dict(
            handoff
            or {
                "posting_status_after_review": JOB_POSTING_STATUS_TAILORING_IN_PROGRESS,
                "ready_for_outreach": False,
                "max_send_set_size": 3,
                "current_send_set_size": 0,
                "selected_slots": [],
                "selected_contact_ids": [],
                "selected_job_posting_contact_ids": [],
                "selected_contacts": [],
                "blocking_contact_ids": [],
                "repeat_outreach_review_contact_ids": [],
                "repeat_outreach_review_contacts": [],
                "company_pacing": {
                    "daily_send_cap": 3,
                    "company_sent_today": 0,
                    "remaining_company_daily_capacity": 3,
                    "global_gap_minutes": 6,
                    "earliest_allowed_send_at": now_utc_iso(),
                    "pacing_allowed_now": True,
                    "pacing_block_reason": None,
                },
            }
        )
        posting_status_after_review = JOB_POSTING_STATUS_TAILORING_IN_PROGRESS
        handoff_details["posting_status_after_review"] = posting_status_after_review
        transition_reason = (
            "Mandatory tailoring review rejected the current tailored output and returned the "
            "posting to retailoring."
            if override_event is None
            else "Owner override rejected the current tailored output and returned the posting to retailoring."
        )
        artifact_result = "blocked"
        reason_code = TAILORING_REVIEW_REASON_REJECTED
        message = (
            "Mandatory tailoring review rejected the current tailored output, so downstream "
            "progression remains blocked until retailoring produces a new approved run."
            if override_event is None
            else "Owner override rejected the current tailored output, so downstream progression "
            "returns to retailoring for a new approved run."
        )

    updated_run = _update_tailoring_run_state(
        connection,
        posting_row=posting_row,
        run=run,
        tailoring_status=run.tailoring_status,
        resume_review_status=decision_type,
        verification_outcome=run.verification_outcome,
        current_time=current_time,
        transition_reason=transition_reason,
        final_resume_path=run.final_resume_path,
        completed_at=run.completed_at,
    )
    posting_status = _set_job_posting_status(
        connection,
        job_posting_id=run.job_posting_id,
        lead_id=str(posting_row["lead_id"]),
        previous_status=str(posting_row["posting_status"]),
        new_status=posting_status_after_review,
        current_time=current_time,
        transition_reason=transition_reason,
    )
    review_artifact = _publish_tailoring_review_artifact(
        connection,
        paths,
        posting_row=posting_row,
        run=updated_run,
        reviewer_type=reviewer_type,
        decision_type=decision_type,
        decision_notes=decision_notes,
        current_time=current_time,
        previous_posting_status=str(posting_row["posting_status"]),
        new_posting_status=posting_status,
        previous_decision_context=previous_decision_context,
        handoff_details=handoff_details,
        override_event=override_event,
        result=artifact_result,
        reason_code=reason_code,
        message=message,
    )
    posting_row = dict(posting_row)
    posting_row["posting_status"] = posting_status
    _publish_tailoring_meta_artifact(
        connection,
        paths,
        posting_row=posting_row,
        run=updated_run,
        current_time=current_time,
    )
    return TailoringReviewResult(
        job_posting_id=run.job_posting_id,
        resume_tailoring_run_id=run.resume_tailoring_run_id,
        reviewer_type=reviewer_type,
        decision_type=decision_type,
        result=artifact_result,
        reason_code=reason_code,
        run=updated_run,
        posting_status=posting_status,
        review_artifact=review_artifact,
        override_event=override_event,
    )


def _publish_tailoring_review_artifact(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    posting_row: Mapping[str, Any],
    run: ResumeTailoringRunRecord,
    reviewer_type: str,
    decision_type: str,
    decision_notes: str | None,
    current_time: str,
    previous_posting_status: str,
    new_posting_status: str,
    previous_decision_context: Mapping[str, Any],
    handoff_details: Mapping[str, Any],
    override_event: OverrideEventRecord | None,
    result: str,
    reason_code: str | None,
    message: str | None,
) -> PublishedArtifact:
    verification_path = paths.tailoring_step_7_verification_path(
        str(posting_row["company_name"]),
        str(posting_row["role_title"]),
    )
    verification_snapshot = (
        _load_yaml_file(verification_path)
        if verification_path.exists()
        else {}
    )
    artifact_path = paths.tailoring_review_decision_path(
        str(posting_row["company_name"]),
        str(posting_row["role_title"]),
        run.resume_tailoring_run_id,
        _review_decision_slug(
            current_time=current_time,
            reviewer_type=reviewer_type,
            decision_type=decision_type,
        ),
    )
    artifact_ref = paths.relative_to_root(artifact_path).as_posix()
    return publish_yaml_artifact(
        connection,
        paths,
        artifact_type=TAILORING_REVIEW_ARTIFACT_TYPE,
        artifact_path=artifact_path,
        producer_component=RESUME_TAILORING_COMPONENT,
        result=result,
        linkage=ArtifactLinkage(
            lead_id=str(posting_row["lead_id"]),
            job_posting_id=str(posting_row["job_posting_id"]),
        ),
        payload={
            "artifact_path": artifact_ref,
            "review_kind": "mandatory_agent_review",
            "resume_tailoring_run_id": run.resume_tailoring_run_id,
            "reviewer_type": reviewer_type,
            "decision_type": decision_type,
            "decision_notes": decision_notes,
            "reviewed_at": current_time,
            "tailoring_status": run.tailoring_status,
            "resume_review_status": run.resume_review_status,
            "previous_posting_status": previous_posting_status,
            "new_posting_status": new_posting_status,
            "final_resume_path": run.final_resume_path,
            "meta_yaml_path": run.meta_yaml_path,
            "agent_review_score": verification_snapshot.get("agent_score"),
            "jd_coverage_score": verification_snapshot.get("jd_coverage_score"),
            "must_have_coverage_score": verification_snapshot.get("must_have_coverage_score"),
            "outreach_handoff": dict(handoff_details),
            "previous_decision_context": dict(previous_decision_context),
            "override_event_id": (
                override_event.override_event_id if override_event is not None else None
            ),
        },
        produced_at=current_time,
        reason_code=reason_code,
        message=message,
    )


def _review_decision_slug(
    *,
    current_time: str,
    reviewer_type: str,
    decision_type: str,
) -> str:
    return f"{_timestamp_slug(current_time)}-{reviewer_type}-{decision_type}"


def _extract_experience_lower_bound(line: str) -> int | None:
    if "year" not in line and "yr" not in line:
        return None
    if not EXPERIENCE_CONTEXT_RE.search(line):
        return None

    comparator_match = EXPERIENCE_COMPARATOR_RE.search(line)
    if comparator_match is not None:
        years = int(comparator_match.group("years"))
        operator = comparator_match.group("operator").lower()
        if operator in {"more than", "over"}:
            return years + 1
        return years

    plus_match = EXPERIENCE_PLUS_RE.search(line)
    if plus_match is not None:
        return int(plus_match.group("years"))

    range_match = EXPERIENCE_RANGE_RE.search(line)
    if range_match is not None:
        return int(range_match.group("years"))

    plain_match = EXPERIENCE_PLAIN_RE.search(line)
    if plain_match is not None:
        return int(plain_match.group("years"))
    return None


def _append_unique(values: list[str], candidate: str) -> None:
    if candidate not in values:
        values.append(candidate)


def _resume_tailoring_run_from_row(row: sqlite3.Row) -> ResumeTailoringRunRecord:
    tailoring_status = str(row[3])
    resume_review_status = str(row[4])
    if tailoring_status not in TAILORING_STATUSES:
        raise ResumeTailoringError(f"Unsupported tailoring_status={tailoring_status!r}.")
    if resume_review_status not in RESUME_REVIEW_STATUSES:
        raise ResumeTailoringError(
            f"Unsupported resume_review_status={resume_review_status!r}."
        )
    return ResumeTailoringRunRecord(
        resume_tailoring_run_id=row[0],
        job_posting_id=row[1],
        base_used=row[2],
        tailoring_status=tailoring_status,
        resume_review_status=resume_review_status,
        workspace_path=row[5],
        meta_yaml_path=row[6],
        final_resume_path=row[7],
        verification_outcome=row[8],
        started_at=row[9],
        completed_at=row[10],
        created_at=row[11],
        updated_at=row[12],
    )


def generate_tailoring_intelligence(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    job_posting_id: str,
    timestamp: str | None = None,
) -> TailoringIntelligenceResult:
    current_time = timestamp or now_utc_iso()
    bootstrap_result = bootstrap_tailoring_run(
        connection,
        paths,
        job_posting_id=job_posting_id,
        timestamp=current_time,
    )
    if bootstrap_result.run is None:
        return TailoringIntelligenceResult(
            job_posting_id=bootstrap_result.job_posting_id,
            resume_tailoring_run_id=None,
            track_name=None,
            verification_outcome=None,
            blocked_reason_code=bootstrap_result.blocked_reason_code,
            step_artifact_paths={},
        )

    posting_row = _load_posting_row(connection, job_posting_id=job_posting_id)
    run = get_resume_tailoring_run(connection, bootstrap_result.run.resume_tailoring_run_id)
    if run is None:
        raise ResumeTailoringError(
            f"Failed to reload resume_tailoring_run `{bootstrap_result.run.resume_tailoring_run_id}`."
        )

    company_name = str(posting_row["company_name"])
    role_title = str(posting_row["role_title"])
    workspace_jd_path = paths.tailoring_workspace_jd_path(company_name, role_title)
    profile_path = paths.tailoring_input_profile_path
    resume_tex_path = paths.tailoring_resume_tex_path(company_name, role_title)
    meta_path = paths.tailoring_meta_path(company_name, role_title)

    if not workspace_jd_path.exists():
        raise ResumeTailoringError(
            f"Tailoring workspace JD mirror is missing for job_posting_id `{job_posting_id}`."
        )
    if not profile_path.exists():
        raise ResumeTailoringError("Tailoring input profile mirror is missing.")
    if not resume_tex_path.exists():
        raise ResumeTailoringError("Tailoring workspace resume.tex is missing.")
    if not meta_path.exists():
        raise ResumeTailoringError("Tailoring workspace meta.yaml is missing.")

    jd_text = workspace_jd_path.read_text(encoding="utf-8")
    profile_text = profile_path.read_text(encoding="utf-8")
    resume_doc = _parse_resume_document(resume_tex_path.read_text(encoding="utf-8"))
    meta_payload = _load_yaml_file(meta_path)
    section_locks = _normalized_slug_list(meta_payload.get("section_locks"))
    experience_role_allowlist = _normalized_slug_list(meta_payload.get("experience_role_allowlist"))

    step_3_payload = _build_step_3_signal_artifact(
        posting_row=posting_row,
        run=run,
        jd_text=jd_text,
    )
    track_name = _select_tailoring_track(step_3_payload)
    profile_snippets = _extract_profile_snippets(profile_text, source_path=profile_path)
    step_4_payload = _build_step_4_evidence_artifact(
        posting_row=posting_row,
        run=run,
        step_3_payload=step_3_payload,
        profile_snippets=profile_snippets,
    )
    step_5_markdown = _build_step_5_context_markdown(
        posting_row=posting_row,
        run=run,
        track_name=track_name,
        step_4_payload=step_4_payload,
    )
    step_6_payload = _build_step_6_candidate_payload(
        posting_row=posting_row,
        run=run,
        track_name=track_name,
        profile_text=profile_text,
        resume_doc=resume_doc,
        step_3_payload=step_3_payload,
        step_4_payload=step_4_payload,
        section_locks=section_locks,
        experience_role_allowlist=experience_role_allowlist,
    )
    step_7_payload = _build_step_7_verification_artifact(
        posting_row=posting_row,
        run=run,
        resume_doc=resume_doc,
        step_3_payload=step_3_payload,
        step_4_payload=step_4_payload,
        step_6_payload=step_6_payload,
        section_locks=section_locks,
        experience_role_allowlist=experience_role_allowlist,
    )

    _write_yaml_file(
        paths.tailoring_step_3_jd_signals_path(company_name, role_title),
        step_3_payload,
        overwrite=True,
    )
    _write_yaml_file(
        paths.tailoring_step_4_evidence_map_path(company_name, role_title),
        step_4_payload,
        overwrite=True,
    )
    _write_text_file(
        paths.tailoring_step_5_context_path(company_name, role_title),
        step_5_markdown,
        overwrite=True,
    )
    _write_yaml_file(
        paths.tailoring_step_6_candidate_bullets_path(company_name, role_title),
        step_6_payload,
        overwrite=True,
    )
    _write_yaml_file(
        paths.tailoring_step_7_verification_path(company_name, role_title),
        step_7_payload,
        overwrite=True,
    )
    _update_intelligence_manifest(
        paths,
        posting_row=posting_row,
        run=run,
        current_time=current_time,
        track_name=track_name,
        verification_outcome=str(step_7_payload["verification_outcome"]),
    )

    refreshed_run = run
    verification_outcome = str(step_7_payload["verification_outcome"])
    if verification_outcome != VERIFICATION_OUTCOME_PASS:
        refreshed_run = _update_tailoring_run_state(
            connection,
            posting_row=posting_row,
            run=run,
            tailoring_status=TAILORING_STATUS_NEEDS_REVISION,
            resume_review_status=RESUME_REVIEW_STATUS_NOT_READY,
            verification_outcome=verification_outcome,
            current_time=current_time,
            transition_reason="Structured tailoring verification surfaced explicit blockers or revision guidance.",
            final_resume_path=run.final_resume_path,
            completed_at=None,
        )
        _publish_tailoring_meta_artifact(
            connection,
            paths,
            posting_row=posting_row,
            run=refreshed_run,
            current_time=current_time,
        )
    elif run.tailoring_status == TAILORING_STATUS_NEEDS_REVISION:
        refreshed_run = _update_tailoring_run_state(
            connection,
            posting_row=posting_row,
            run=run,
            tailoring_status=TAILORING_STATUS_IN_PROGRESS,
            resume_review_status=RESUME_REVIEW_STATUS_NOT_READY,
            verification_outcome=verification_outcome,
            current_time=current_time,
            transition_reason="Structured tailoring artifacts were regenerated and cleared the current verification gate.",
            final_resume_path=run.final_resume_path,
            completed_at=None,
        )
        _publish_tailoring_meta_artifact(
            connection,
            paths,
            posting_row=posting_row,
            run=refreshed_run,
            current_time=current_time,
        )

    return TailoringIntelligenceResult(
        job_posting_id=job_posting_id,
        resume_tailoring_run_id=refreshed_run.resume_tailoring_run_id,
        track_name=track_name,
        verification_outcome=verification_outcome,
        blocked_reason_code=None,
        step_artifact_paths={
            "step_3": paths.relative_to_root(
                paths.tailoring_step_3_jd_signals_path(company_name, role_title)
            ).as_posix(),
            "step_4": paths.relative_to_root(
                paths.tailoring_step_4_evidence_map_path(company_name, role_title)
            ).as_posix(),
            "step_5": paths.relative_to_root(
                paths.tailoring_step_5_context_path(company_name, role_title)
            ).as_posix(),
            "step_6": paths.relative_to_root(
                paths.tailoring_step_6_candidate_bullets_path(company_name, role_title)
            ).as_posix(),
            "step_7": paths.relative_to_root(
                paths.tailoring_step_7_verification_path(company_name, role_title)
            ).as_posix(),
        },
    )


def finalize_tailoring_run(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    job_posting_id: str,
    timestamp: str | None = None,
) -> TailoringFinalizeResult:
    current_time = timestamp or now_utc_iso()
    posting_row = _load_posting_row(connection, job_posting_id=job_posting_id)
    run = get_latest_resume_tailoring_run_for_posting(connection, job_posting_id)
    if run is None:
        raise ResumeTailoringError(
            f"No active resume_tailoring_run exists for job_posting_id `{job_posting_id}`."
        )

    company_name = str(posting_row["company_name"])
    role_title = str(posting_row["role_title"])
    resume_tex_path = paths.tailoring_resume_tex_path(company_name, role_title)
    baseline_path = paths.tailoring_scope_baseline_path(company_name, role_title)
    step_3_path = paths.tailoring_step_3_jd_signals_path(company_name, role_title)
    step_4_path = paths.tailoring_step_4_evidence_map_path(company_name, role_title)
    step_6_path = paths.tailoring_step_6_candidate_bullets_path(company_name, role_title)
    step_7_path = paths.tailoring_step_7_verification_path(company_name, role_title)

    required_paths = {
        "step_3_jd_signals": step_3_path,
        "step_4_evidence_map": step_4_path,
        "step_6_candidate_resume_edits": step_6_path,
        "step_7_verification": step_7_path,
        "scope_baseline": baseline_path,
        "resume_tex": resume_tex_path,
    }
    missing = [artifact_name for artifact_name, path in required_paths.items() if not path.exists()]
    if missing:
        refreshed_run = _update_tailoring_run_state(
            connection,
            posting_row=posting_row,
            run=run,
            tailoring_status=TAILORING_STATUS_NEEDS_REVISION,
            resume_review_status=RESUME_REVIEW_STATUS_NOT_READY,
            verification_outcome=VERIFICATION_OUTCOME_NEEDS_REVISION,
            current_time=current_time,
            transition_reason="Finalize is blocked because required tailoring artifacts are missing.",
            final_resume_path=run.final_resume_path,
            completed_at=None,
        )
        _write_finalize_blocker(
            step_7_path,
            posting_row=posting_row,
            run=refreshed_run,
            reason_code=FINALIZE_REASON_MISSING_STEP_ARTIFACT,
            blocker_message=(
                "Finalize requires Step 3, Step 4, Step 6, Step 7, scope baseline, and resume.tex."
            ),
            blocker_details=[f"Missing artifact: {artifact_name}" for artifact_name in missing],
            current_time=current_time,
            severity=VERIFICATION_OUTCOME_NEEDS_REVISION,
        )
        _publish_tailoring_meta_artifact(
            connection,
            paths,
            posting_row=posting_row,
            run=refreshed_run,
            current_time=current_time,
        )
        return TailoringFinalizeResult(
            job_posting_id=job_posting_id,
            resume_tailoring_run_id=refreshed_run.resume_tailoring_run_id,
            result=VERIFICATION_OUTCOME_NEEDS_REVISION,
            reason_code=FINALIZE_REASON_MISSING_STEP_ARTIFACT,
            run=refreshed_run,
            final_resume_path=refreshed_run.final_resume_path,
            verification_outcome=refreshed_run.verification_outcome,
        )

    step_3_payload = _load_yaml_file(step_3_path)
    step_4_payload = _load_yaml_file(step_4_path)
    step_6_payload = _load_yaml_file(step_6_path)
    step_7_payload = _load_yaml_file(step_7_path)
    if not _step_artifacts_are_valid(step_3_payload, step_4_payload, step_6_payload, step_7_payload):
        refreshed_run = _update_tailoring_run_state(
            connection,
            posting_row=posting_row,
            run=run,
            tailoring_status=TAILORING_STATUS_NEEDS_REVISION,
            resume_review_status=RESUME_REVIEW_STATUS_NOT_READY,
            verification_outcome=VERIFICATION_OUTCOME_NEEDS_REVISION,
            current_time=current_time,
            transition_reason="Finalize found malformed Step 3 through Step 7 artifacts.",
            final_resume_path=run.final_resume_path,
            completed_at=None,
        )
        _write_finalize_blocker(
            step_7_path,
            posting_row=posting_row,
            run=refreshed_run,
            reason_code=FINALIZE_REASON_INVALID_STEP_ARTIFACT,
            blocker_message="Finalize found malformed Step 3 through Step 7 artifacts.",
            blocker_details=["Regenerate the tailoring intelligence artifacts before finalize."],
            current_time=current_time,
            severity=VERIFICATION_OUTCOME_NEEDS_REVISION,
        )
        _publish_tailoring_meta_artifact(
            connection,
            paths,
            posting_row=posting_row,
            run=refreshed_run,
            current_time=current_time,
        )
        return TailoringFinalizeResult(
            job_posting_id=job_posting_id,
            resume_tailoring_run_id=refreshed_run.resume_tailoring_run_id,
            result=VERIFICATION_OUTCOME_NEEDS_REVISION,
            reason_code=FINALIZE_REASON_INVALID_STEP_ARTIFACT,
            run=refreshed_run,
            final_resume_path=refreshed_run.final_resume_path,
            verification_outcome=refreshed_run.verification_outcome,
        )

    verification_outcome = str(step_7_payload.get("verification_outcome", "")).strip()
    if verification_outcome != VERIFICATION_OUTCOME_PASS:
        refreshed_run = _update_tailoring_run_state(
            connection,
            posting_row=posting_row,
            run=run,
            tailoring_status=TAILORING_STATUS_NEEDS_REVISION,
            resume_review_status=RESUME_REVIEW_STATUS_NOT_READY,
            verification_outcome=verification_outcome or VERIFICATION_OUTCOME_NEEDS_REVISION,
            current_time=current_time,
            transition_reason="Finalize stopped because Step 7 verification has not reached pass.",
            final_resume_path=run.final_resume_path,
            completed_at=None,
        )
        _write_finalize_blocker(
            step_7_path,
            posting_row=posting_row,
            run=refreshed_run,
            reason_code=FINALIZE_REASON_VERIFICATION_BLOCKED,
            blocker_message="Finalize requires Step 7 verification to reach `pass`.",
            blocker_details=[
                f"Current Step 7 verification_outcome is `{verification_outcome or 'missing'}`."
            ],
            current_time=current_time,
            severity=VERIFICATION_OUTCOME_NEEDS_REVISION,
        )
        _publish_tailoring_meta_artifact(
            connection,
            paths,
            posting_row=posting_row,
            run=refreshed_run,
            current_time=current_time,
        )
        return TailoringFinalizeResult(
            job_posting_id=job_posting_id,
            resume_tailoring_run_id=refreshed_run.resume_tailoring_run_id,
            result=VERIFICATION_OUTCOME_NEEDS_REVISION,
            reason_code=FINALIZE_REASON_VERIFICATION_BLOCKED,
            run=refreshed_run,
            final_resume_path=refreshed_run.final_resume_path,
            verification_outcome=refreshed_run.verification_outcome,
        )

    current_resume_content = resume_tex_path.read_text(encoding="utf-8")
    baseline_content = baseline_path.read_text(encoding="utf-8")
    candidate_resume_content = _apply_step_6_payload_to_resume(
        current_resume_content,
        step_6_payload,
    )
    scope_result = _validate_scope_against_baseline(
        baseline_content=baseline_content,
        candidate_content=candidate_resume_content,
    )
    if scope_result is not None:
        refreshed_run = _update_tailoring_run_state(
            connection,
            posting_row=posting_row,
            run=run,
            tailoring_status=TAILORING_STATUS_NEEDS_REVISION,
            resume_review_status=RESUME_REVIEW_STATUS_NOT_READY,
            verification_outcome=VERIFICATION_OUTCOME_NEEDS_REVISION,
            current_time=current_time,
            transition_reason="Finalize rejected resume edits outside the allowed tailoring boundary.",
            final_resume_path=run.final_resume_path,
            completed_at=None,
        )
        _write_finalize_blocker(
            step_7_path,
            posting_row=posting_row,
            run=refreshed_run,
            reason_code=FINALIZE_REASON_SCOPE_VIOLATION,
            blocker_message="Finalize detected edits outside the allowed tailoring boundary.",
            blocker_details=scope_result,
            current_time=current_time,
            severity=VERIFICATION_OUTCOME_NEEDS_REVISION,
        )
        _publish_tailoring_meta_artifact(
            connection,
            paths,
            posting_row=posting_row,
            run=refreshed_run,
            current_time=current_time,
        )
        return TailoringFinalizeResult(
            job_posting_id=job_posting_id,
            resume_tailoring_run_id=refreshed_run.resume_tailoring_run_id,
            result=VERIFICATION_OUTCOME_NEEDS_REVISION,
            reason_code=FINALIZE_REASON_SCOPE_VIOLATION,
            run=refreshed_run,
            final_resume_path=refreshed_run.final_resume_path,
            verification_outcome=refreshed_run.verification_outcome,
        )

    resume_tex_path.write_text(candidate_resume_content, encoding="utf-8")
    compile_result = _compile_tailored_resume(paths, company_name=company_name, role_title=role_title)
    if compile_result["status"] == "failed":
        refreshed_run = _update_tailoring_run_state(
            connection,
            posting_row=posting_row,
            run=run,
            tailoring_status=TAILORING_STATUS_FAILED,
            resume_review_status=RESUME_REVIEW_STATUS_NOT_READY,
            verification_outcome=VERIFICATION_OUTCOME_FAIL,
            current_time=current_time,
            transition_reason="Finalize failed because LaTeX compilation did not succeed.",
            final_resume_path=None,
            completed_at=current_time,
        )
        _write_finalize_blocker(
            step_7_path,
            posting_row=posting_row,
            run=refreshed_run,
            reason_code=FINALIZE_REASON_COMPILE_FAILED,
            blocker_message="LaTeX compilation failed during finalize.",
            blocker_details=compile_result["notes"],
            current_time=current_time,
            severity=VERIFICATION_OUTCOME_FAIL,
            compiled_pdf_path=compile_result.get("compiled_pdf_path"),
        )
        _publish_tailoring_meta_artifact(
            connection,
            paths,
            posting_row=posting_row,
            run=refreshed_run,
            current_time=current_time,
        )
        return TailoringFinalizeResult(
            job_posting_id=job_posting_id,
            resume_tailoring_run_id=refreshed_run.resume_tailoring_run_id,
            result=VERIFICATION_OUTCOME_FAIL,
            reason_code=FINALIZE_REASON_COMPILE_FAILED,
            run=refreshed_run,
            final_resume_path=refreshed_run.final_resume_path,
            verification_outcome=refreshed_run.verification_outcome,
        )

    page_count = int(compile_result["page_count"])
    if page_count != 1:
        refreshed_run = _update_tailoring_run_state(
            connection,
            posting_row=posting_row,
            run=run,
            tailoring_status=TAILORING_STATUS_NEEDS_REVISION,
            resume_review_status=RESUME_REVIEW_STATUS_NOT_READY,
            verification_outcome=VERIFICATION_OUTCOME_NEEDS_REVISION,
            current_time=current_time,
            transition_reason="Finalize compiled a resume that violates the one-page rule.",
            final_resume_path=compile_result["final_pdf_relative_path"],
            completed_at=None,
        )
        _write_finalize_blocker(
            step_7_path,
            posting_row=posting_row,
            run=refreshed_run,
            reason_code=FINALIZE_REASON_PAGE_BUDGET,
            blocker_message="Finalize compiled successfully but the rendered PDF exceeds one page.",
            blocker_details=[f"Rendered page count: {page_count}."],
            current_time=current_time,
            severity=VERIFICATION_OUTCOME_NEEDS_REVISION,
            compiled_pdf_path=compile_result.get("compiled_pdf_path"),
            page_count=page_count,
        )
        _publish_tailoring_meta_artifact(
            connection,
            paths,
            posting_row=posting_row,
            run=refreshed_run,
            current_time=current_time,
        )
        return TailoringFinalizeResult(
            job_posting_id=job_posting_id,
            resume_tailoring_run_id=refreshed_run.resume_tailoring_run_id,
            result=VERIFICATION_OUTCOME_NEEDS_REVISION,
            reason_code=FINALIZE_REASON_PAGE_BUDGET,
            run=refreshed_run,
            final_resume_path=refreshed_run.final_resume_path,
            verification_outcome=refreshed_run.verification_outcome,
        )

    refreshed_run = _update_tailoring_run_state(
        connection,
        posting_row=posting_row,
        run=run,
        tailoring_status=TAILORING_STATUS_TAILORED,
        resume_review_status=RESUME_REVIEW_STATUS_PENDING,
        verification_outcome=VERIFICATION_OUTCOME_PASS,
        current_time=current_time,
        transition_reason="Finalize applied the Step 6 payload, compiled the PDF, and verified one-page output.",
        final_resume_path=compile_result["final_pdf_relative_path"],
        completed_at=current_time,
    )
    updated_posting_status = _set_job_posting_status(
        connection,
        job_posting_id=job_posting_id,
        lead_id=str(posting_row["lead_id"]),
        previous_status=str(posting_row["posting_status"]),
        new_status=JOB_POSTING_STATUS_RESUME_REVIEW_PENDING,
        current_time=current_time,
        transition_reason="Resume Tailoring finalize completed and handed the run to the mandatory review gate.",
    )
    posting_row = dict(posting_row)
    posting_row["posting_status"] = updated_posting_status
    _write_finalize_success(
        step_7_path,
        posting_row=posting_row,
        run=refreshed_run,
        current_time=current_time,
        compiled_pdf_path=compile_result["compiled_pdf_path"],
        page_count=page_count,
    )
    _publish_tailoring_meta_artifact(
        connection,
        paths,
        posting_row=posting_row,
        run=refreshed_run,
        current_time=current_time,
    )
    return TailoringFinalizeResult(
        job_posting_id=job_posting_id,
        resume_tailoring_run_id=refreshed_run.resume_tailoring_run_id,
        result=VERIFICATION_OUTCOME_PASS,
        reason_code=None,
        run=refreshed_run,
        final_resume_path=refreshed_run.final_resume_path,
        verification_outcome=refreshed_run.verification_outcome,
    )


def record_tailoring_review_decision(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    job_posting_id: str,
    decision_type: str,
    decision_notes: str | None = None,
    reviewer_type: str = MANDATORY_REVIEWER_AGENT,
    timestamp: str | None = None,
) -> TailoringReviewResult:
    if reviewer_type not in REVIEWER_TYPES:
        raise ResumeTailoringError(f"Unsupported reviewer_type={reviewer_type!r}.")
    if decision_type not in TAILORING_REVIEW_DECISION_TYPES:
        raise ResumeTailoringError(f"Unsupported decision_type={decision_type!r}.")

    current_time = timestamp or now_utc_iso()
    posting_row = _load_posting_row(connection, job_posting_id=job_posting_id)
    run = get_latest_resume_tailoring_run_for_posting(connection, job_posting_id)
    if run is None:
        raise ResumeTailoringError(
            f"No active resume_tailoring_run exists for job_posting_id `{job_posting_id}`."
        )
    if run.tailoring_status != TAILORING_STATUS_TAILORED:
        raise ResumeTailoringError(
            "Mandatory tailoring review requires a finalized run with "
            f"`tailoring_status = {TAILORING_STATUS_TAILORED}`."
        )
    if run.resume_review_status != RESUME_REVIEW_STATUS_PENDING:
        raise ResumeTailoringError(
            "Mandatory tailoring review requires the active run to be pending review, "
            f"but found `{run.resume_review_status}`."
        )

    return _apply_tailoring_review_outcome(
        connection,
        paths,
        posting_row=posting_row,
        run=run,
        decision_type=decision_type,
        decision_notes=decision_notes,
        reviewer_type=reviewer_type,
        current_time=current_time,
        override_event=None,
        previous_decision_context=_current_review_decision_context(
            connection,
            paths,
            posting_row=posting_row,
            run=run,
        ),
    )


def record_tailoring_review_override(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    job_posting_id: str,
    decision_type: str,
    override_reason: str,
    override_by: str = MANDATORY_REVIEWER_OWNER,
    decision_notes: str | None = None,
    timestamp: str | None = None,
) -> TailoringReviewResult:
    if decision_type not in TAILORING_REVIEW_DECISION_TYPES:
        raise ResumeTailoringError(f"Unsupported decision_type={decision_type!r}.")
    if not override_reason.strip():
        raise ResumeTailoringError("override_reason is required for tailoring review overrides.")

    current_time = timestamp or now_utc_iso()
    posting_row = _load_posting_row(connection, job_posting_id=job_posting_id)
    run = get_latest_resume_tailoring_run_for_posting(connection, job_posting_id)
    if run is None:
        raise ResumeTailoringError(
            f"No active resume_tailoring_run exists for job_posting_id `{job_posting_id}`."
        )
    if run.tailoring_status != TAILORING_STATUS_TAILORED:
        raise ResumeTailoringError(
            "Tailoring review overrides require a finalized run with "
            f"`tailoring_status = {TAILORING_STATUS_TAILORED}`."
        )
    if run.resume_review_status not in {
        RESUME_REVIEW_STATUS_APPROVED,
        RESUME_REVIEW_STATUS_REJECTED,
    }:
        raise ResumeTailoringError(
            "Tailoring review overrides require a prior review decision, "
            f"but found `{run.resume_review_status}`."
        )
    if run.resume_review_status == decision_type:
        raise ResumeTailoringError(
            "Tailoring review override must change the existing review decision."
        )

    previous_decision_context = _current_review_decision_context(
        connection,
        paths,
        posting_row=posting_row,
        run=run,
    )
    handoff = (
        _evaluate_post_review_outreach_handoff(connection, job_posting_id)
        if decision_type == RESUME_REVIEW_STATUS_APPROVED
        else {
            "posting_status_after_review": JOB_POSTING_STATUS_TAILORING_IN_PROGRESS,
            "ready_for_outreach": False,
            "max_send_set_size": 3,
            "current_send_set_size": 0,
            "selected_slots": [],
            "selected_contact_ids": [],
            "selected_job_posting_contact_ids": [],
            "selected_contacts": [],
            "blocking_contact_ids": [],
            "repeat_outreach_review_contact_ids": [],
            "repeat_outreach_review_contacts": [],
            "company_pacing": {
                "daily_send_cap": 3,
                "company_sent_today": 0,
                "remaining_company_daily_capacity": 3,
                "global_gap_minutes": 6,
                "earliest_allowed_send_at": now_utc_iso(),
                "pacing_allowed_now": True,
                "pacing_block_reason": None,
            },
        }
    )
    override_event = record_override_event(
        connection,
        object_type="resume_tailoring_runs",
        object_id=run.resume_tailoring_run_id,
        component_stage="resume_review_status",
        previous_value={
            "decision_context": previous_decision_context,
            "resume_review_status": run.resume_review_status,
            "posting_status": posting_row["posting_status"],
        },
        new_value={
            "decision_context": {
                "decision_type": decision_type,
                "reviewer_type": override_by,
                "reviewed_at": current_time,
                "applied_from": "owner_override",
            },
            "resume_review_status": decision_type,
            "posting_status": handoff["posting_status_after_review"],
        },
        override_reason=override_reason,
        override_by=override_by,
        lead_id=str(posting_row["lead_id"]),
        job_posting_id=str(posting_row["job_posting_id"]),
        override_timestamp=current_time,
    )
    return _apply_tailoring_review_outcome(
        connection,
        paths,
        posting_row=posting_row,
        run=run,
        decision_type=decision_type,
        decision_notes=decision_notes or override_reason,
        reviewer_type=override_by,
        current_time=current_time,
        override_event=override_event,
        previous_decision_context=previous_decision_context,
        handoff=handoff,
    )


def _step_artifacts_are_valid(
    step_3_payload: Mapping[str, Any],
    step_4_payload: Mapping[str, Any],
    step_6_payload: Mapping[str, Any],
    step_7_payload: Mapping[str, Any],
) -> bool:
    return all(
        (
            step_3_payload.get("status") == INTELLIGENCE_STATUS_GENERATED,
            isinstance(step_3_payload.get("signals"), list),
            step_4_payload.get("status") == INTELLIGENCE_STATUS_GENERATED,
            isinstance(step_4_payload.get("matches"), list),
            step_6_payload.get("status") == INTELLIGENCE_STATUS_GENERATED,
            isinstance(step_6_payload.get("technical_skills"), list),
            isinstance(step_6_payload.get("summary"), str),
            step_7_payload.get("status") == INTELLIGENCE_STATUS_GENERATED,
            step_7_payload.get("verification_outcome") in {
                VERIFICATION_OUTCOME_PASS,
                VERIFICATION_OUTCOME_FAIL,
                VERIFICATION_OUTCOME_NEEDS_REVISION,
            },
            isinstance(step_7_payload.get("checks"), list),
        )
    )


def _parse_resume_document(content: str) -> ParsedResumeDocument:
    summary_match = SUMMARY_BLOCK_RE.search(content)
    skills_match = TECHNICAL_SKILLS_BLOCK_RE.search(content)
    software_engineer_match = SOFTWARE_ENGINEER_BLOCK_RE.search(content)
    if summary_match is None or skills_match is None or software_engineer_match is None:
        raise ResumeTailoringError(
            "resume.tex does not match the current supported tailoring template."
        )

    technical_skills: list[dict[str, Any]] = []
    for match in TECHNICAL_SKILL_LINE_RE.finditer(skills_match.group("skills")):
        items = [item.strip() for item in match.group("items").split(",") if item.strip()]
        technical_skills.append(
            {
                "category": match.group("category").strip(),
                "items": items,
            }
        )
    bullets = [
        line.strip()[6:].strip()
        for line in software_engineer_match.group("bullets").splitlines()
        if line.strip().startswith("\\item ")
    ]
    return ParsedResumeDocument(
        summary=summary_match.group("summary").strip(),
        technical_skills=technical_skills,
        software_engineer_stack_line=software_engineer_match.group("stack").strip(),
        software_engineer_bullets=bullets,
        resume_wide_tokens=_resume_wide_tokens_from_content(content),
    )


def _resume_wide_tokens_from_content(content: str) -> set[str]:
    plain_text = re.sub(r"\\[A-Za-z]+", " ", content)
    plain_text = re.sub(r"[{}\\]", " ", plain_text)
    tokens = _tokenize(plain_text)
    return {
        token
        for token in tokens
        if token not in {"begin", "end", "document", "section", "textbf", "textit", "vspace"}
    }


def _apply_step_6_payload_to_resume(content: str, step_6_payload: Mapping[str, Any]) -> str:
    summary_text = str(step_6_payload["summary"]).strip()
    skill_lines = _render_technical_skills_block(
        step_6_payload.get("technical_skills", [])
    )
    software_engineer = dict(step_6_payload.get("software_engineer") or {})
    stack_line = str(software_engineer.get("tech_stack_line") or "").strip()
    bullets = software_engineer.get("bullets") or []
    bullet_lines = "\n".join(
        f"            \\item {str(entry['text']).strip()}"
        for entry in bullets
    )

    updated = SUMMARY_BLOCK_RE.sub(
        lambda match: f"{match.group('prefix')}{summary_text}{match.group('suffix')}",
        content,
        count=1,
    )
    updated = TECHNICAL_SKILLS_BLOCK_RE.sub(
        lambda match: f"{match.group('prefix')}{skill_lines}{match.group('suffix')}",
        updated,
        count=1,
    )
    updated = SOFTWARE_ENGINEER_BLOCK_RE.sub(
        lambda match: (
            f"{match.group('prefix')}{stack_line}{match.group('middle')}{bullet_lines}\n"
            f"{match.group('suffix')}"
        ),
        updated,
        count=1,
    )
    return updated


def _render_technical_skills_block(technical_skills: Sequence[Mapping[str, Any]]) -> str:
    rendered_blocks = []
    for entry in technical_skills:
        category = str(entry.get("category") or "").strip()
        items = ", ".join(str(item).strip() for item in entry.get("items") or [] if str(item).strip())
        rendered_blocks.append(
            "    \\begin{onecolentry}\n"
            f"        \\textbf{{{category}:}} {items}\n"
            "    \\end{onecolentry}\n"
        )
    return "\n".join(rendered_blocks).rstrip() + "\n\n"


def _extract_profile_skill_inventory(profile_text: str) -> list[dict[str, Any]]:
    inventory: list[dict[str, Any]] = []
    in_skills = False
    for raw_line in profile_text.splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("## "):
            in_skills = stripped[3:].strip().lower() == "skills"
            continue
        if in_skills and stripped.startswith("## "):
            break
        if not in_skills or not stripped.startswith("- **") or ":**" not in stripped:
            continue
        category_part, items_part = stripped[2:].split(":**", 1)
        category = category_part.strip("* ").strip()
        items = _split_skill_items(items_part)
        if not category or not items:
            continue
        inventory.append({"category": category, "items": items})
    return inventory


def _split_skill_items(raw_text: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    for char in raw_text.strip():
        if char == "(":
            depth += 1
        elif char == ")" and depth > 0:
            depth -= 1
        if char == "," and depth == 0:
            item = "".join(current).strip()
            if item:
                parts.append(item)
            current = []
            continue
        current.append(char)
    tail = "".join(current).strip()
    if tail:
        parts.append(tail)
    return parts


def _determine_role_focus(
    *,
    posting_row: Mapping[str, Any],
    step_3_payload: Mapping[str, Any],
    track_name: str,
) -> str:
    role_tokens = _tokenize(
        " ".join(
            [
                str(posting_row["role_title"] or ""),
                str(step_3_payload.get("role_intent_summary") or ""),
                " ".join(
                    str(signal.get("signal") or "")
                    for signal in step_3_payload.get("signals", [])
                ),
            ]
        )
    )
    if len(role_tokens & ROLE_FOCUS_AI_TERMS) >= 2:
        return ROLE_FOCUS_AI_APPLICATION
    if len(role_tokens & ROLE_FOCUS_PLATFORM_TERMS) >= 3:
        return ROLE_FOCUS_CLOUD_PLATFORM
    if len(role_tokens & ROLE_FOCUS_BACKEND_TERMS) >= 2:
        return ROLE_FOCUS_BACKEND_SERVICE
    if track_name == FRONTEND_AI_TRACK:
        return ROLE_FOCUS_AI_APPLICATION
    if track_name == DISTRIBUTED_INFRA_TRACK:
        return ROLE_FOCUS_DISTRIBUTED
    return ROLE_FOCUS_BACKEND_SERVICE


def _build_tailored_summary(role_focus: str) -> str:
    if role_focus == ROLE_FOCUS_AI_APPLICATION:
        return (
            "MS CS candidate with 3+ years building production Python and AWS systems plus "
            "hands-on LLM, RAG, and agentic AI projects, focused on automating user workflows "
            "with reliable cloud-native services and measurable performance gains"
        )
    if role_focus == ROLE_FOCUS_CLOUD_PLATFORM:
        return (
            "MS CS candidate with 3+ years building cloud platforms and production data "
            "services, focused on infrastructure automation, observability, reliability, and "
            "cost-aware operations across containerized distributed systems"
        )
    if role_focus == ROLE_FOCUS_BACKEND_SERVICE:
        return (
            "MS CS candidate with 3+ years building backend data services and distributed "
            "systems, focused on Python and AWS delivery, production reliability, and "
            "high-volume workflow automation"
        )
    return (
        "MS CS candidate with 3+ years building distributed systems and production data "
        "services, focused on reliable cloud infrastructure, performance optimization, and "
        "operationally safe delivery"
    )


def _build_tailored_technical_skills(
    *,
    role_focus: str,
    profile_skill_inventory: Sequence[Mapping[str, Any]],
    step_3_payload: Mapping[str, Any],
) -> list[dict[str, Any]]:
    jd_tokens = {
        token
        for signal in step_3_payload.get("signals", [])
        for token in signal.get("tokens", [])
    }
    categories_by_name = {
        str(entry.get("category") or "").strip().lower(): [str(item).strip() for item in entry.get("items") or []]
        for entry in profile_skill_inventory
    }

    def pick_items(category_names: Sequence[str], fallback: Sequence[str], *, limit: int = 6) -> list[str]:
        pool: list[str] = []
        for category_name in category_names:
            pool.extend(categories_by_name.get(category_name, []))
        if not pool:
            pool = list(fallback)
        scored: list[tuple[int, str]] = []
        seen: set[str] = set()
        for item in pool:
            normalized = item.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            score = _score_skill_item_relevance(item, jd_tokens, role_focus)
            scored.append((score, item))
        scored.sort(key=lambda pair: (-pair[0], pair[1].lower()))
        selected = [item for _, item in scored[:limit]]
        return selected or list(fallback[:limit])

    if role_focus == ROLE_FOCUS_AI_APPLICATION:
        skills = [
            {
                "category": "Languages",
                "items": pick_items(
                    ["languages"],
                    ["Python", "TypeScript", "JavaScript", "SQL", "Java", "Golang"],
                ),
            },
            {
                "category": "AI \\& Data",
                "items": pick_items(
                    ["ai & data", "systems"],
                    ["LLMs", "Agentic AI", "Apache Spark", "Neo4j", "FAISS", "Redis"],
                ),
            },
            {
                "category": "Application \\& APIs",
                "items": pick_items(
                    ["frontend & mobile"],
                    ["React", "Next.js", "Node.js", "FastAPI", "Android (Kotlin)", "Swift"],
                ),
            },
            {
                "category": "Cloud \\& DevOps",
                "items": pick_items(
                    ["cloud & devops"],
                    ["AWS (Lambda, S3, DynamoDB, API Gateway, EC2)", "Docker", "Kubernetes", "GitLab CI/CD", "Linux"],
                ),
            },
            {
                "category": "Testing \\& Reliability",
                "items": pick_items(
                    ["testing & reliability"],
                    ["Pytest", "Unit/Integration Testing", "Monitoring", "Debugging", "Performance Profiling"],
                ),
            },
        ]
    elif role_focus == ROLE_FOCUS_CLOUD_PLATFORM:
        skills = [
            {
                "category": "Languages",
                "items": pick_items(
                    ["languages"],
                    ["Python", "Golang", "Java", "Scala", "Bash", "SQL"],
                ),
            },
            {
                "category": "Cloud \\& DevOps",
                "items": pick_items(
                    ["cloud & devops"],
                    ["AWS (EMR, EC2, S3, Lambda, SQS)", "Kubernetes", "Docker", "Terraform", "GitLab CI/CD", "Linux"],
                ),
            },
            {
                "category": "Systems \\& Platform",
                "items": pick_items(
                    ["systems"],
                    ["Distributed Systems", "Microservices", "Load Balancing", "System Design", "gRPC", "Protocol Buffers"],
                ),
            },
            {
                "category": "Data \\& Storage",
                "items": pick_items(
                    ["ai & data"],
                    ["Apache Spark", "PostgreSQL", "MySQL", "DynamoDB", "MongoDB", "Redis"],
                ),
            },
            {
                "category": "Observability \\& Reliability",
                "items": pick_items(
                    ["testing & reliability"],
                    ["Monitoring", "Debugging", "Performance Profiling", "Pytest", "Unit/Integration Testing"],
                ),
            },
        ]
    else:
        skills = [
            {
                "category": "Languages",
                "items": pick_items(
                    ["languages"],
                    ["Python", "Golang", "Java", "Scala", "SQL", "Bash"],
                ),
            },
            {
                "category": "Infrastructure \\& Systems",
                "items": pick_items(
                    ["systems"],
                    ["Distributed Systems", "Microservices", "Load Balancing", "System Design", "gRPC", "Protocol Buffers"],
                ),
            },
            {
                "category": "Cloud \\& DevOps",
                "items": pick_items(
                    ["cloud & devops"],
                    ["AWS (EMR, EC2, S3, Lambda, SQS)", "Kubernetes", "Docker", "Terraform", "GitLab CI/CD", "Linux"],
                ),
            },
            {
                "category": "Data \\& Storage",
                "items": pick_items(
                    ["ai & data"],
                    ["Apache Spark", "PostgreSQL", "MySQL", "DynamoDB", "MongoDB", "Redis"],
                ),
            },
            {
                "category": "Testing \\& Reliability",
                "items": pick_items(
                    ["testing & reliability"],
                    ["Pytest", "Unit/Integration Testing", "Monitoring", "Debugging", "Performance Profiling"],
                ),
            },
        ]
    return _annotate_technical_skills(skills, step_3_payload=step_3_payload)


def _score_skill_item_relevance(item: str, jd_tokens: set[str], role_focus: str) -> int:
    item_tokens = _tokenize(item)
    score = len(item_tokens & jd_tokens)
    if role_focus == ROLE_FOCUS_AI_APPLICATION and item_tokens & ROLE_FOCUS_AI_TERMS:
        score += 2
    if role_focus == ROLE_FOCUS_CLOUD_PLATFORM and item_tokens & ROLE_FOCUS_PLATFORM_TERMS:
        score += 2
    if role_focus == ROLE_FOCUS_BACKEND_SERVICE and item_tokens & ROLE_FOCUS_BACKEND_TERMS:
        score += 2
    return score


def _build_tailored_stack_line(role_focus: str) -> str:
    if role_focus == ROLE_FOCUS_AI_APPLICATION:
        return "Python, AWS (EMR, S3), Docker, monitoring, distributed services, production analytics"
    if role_focus == ROLE_FOCUS_CLOUD_PLATFORM:
        return "Python, AWS (EMR, S3), Terraform, Docker, Kubernetes, monitoring"
    if role_focus == ROLE_FOCUS_BACKEND_SERVICE:
        return "Python, Scala, AWS (EMR, S3), distributed systems, monitoring, production reliability"
    return "Python, Apache Spark, AWS (EMR, S3), Docker, monitoring, distributed systems"


def _build_tailored_software_engineer_bullets(role_focus: str) -> list[str]:
    if role_focus == ROLE_FOCUS_AI_APPLICATION:
        return [
            "Built Python and Scala data services on AWS (EMR, S3), processing 50M+ daily HL7 records (~580 TPS) and automating high-volume clinical data flows that powered real-time analytics across 1,500+ hospitals with 24/7 uptime",
            "Developed Python and Apache Spark workflows with custom HL7 parsers, cutting end-to-end processing time 40\\% (6 hours to 3.6 hours) on 2TB+ daily data and reducing manual operational follow-up for downstream analytics teams",
            "Optimized 25+ Spark jobs on AWS EMR, improving throughput 50\\% (20K to 30K records/sec) and lowering monthly cloud spend by \\$15K while keeping large-scale production data services reliable and cost efficient",
            "Designed monitoring and alerting for production workflows, triaging data-quality issues and resolving incidents quickly enough to keep analytics and support operations dependable for 1,500+ hospitals in a 24/7 environment",
        ]
    if role_focus == ROLE_FOCUS_CLOUD_PLATFORM:
        return [
            "Built high-availability Python and Scala data services on AWS (EMR, S3), processing 50M+ daily HL7 records (~580 TPS) and supporting reliable shared analytics infrastructure across 1,500+ hospitals with 24/7 uptime",
            "Developed Python and Apache Spark automation workflows with custom HL7 parsers, reducing processing time 40\\% (6 hours to 3.6 hours) on 2TB+ daily data and improving repeatable production operations",
            "Optimized 25+ Spark jobs on AWS EMR, improving throughput 50\\% (20K to 30K records/sec) and lowering monthly cloud spend by \\$15K while strengthening cost-aware platform performance",
            "Designed monitoring and alerting for production workflows, triaging data-quality issues and resolving incidents to keep operational reliability high in an always-on environment",
        ]
    if role_focus == ROLE_FOCUS_BACKEND_SERVICE:
        return [
            "Built high-availability Python and Scala backend data services on AWS (EMR, S3), processing 50M+ daily HL7 records (~580 TPS) for real-time analytics across 1,500+ hospitals with 24/7 uptime",
            "Developed Python and Apache Spark pipelines with custom HL7 parsers, reducing end-to-end processing time 40\\% (6 hours to 3.6 hours) on 2TB+ daily data and enabling reliable same-day downstream decisions",
            "Optimized 25+ Spark jobs on AWS EMR, improving throughput 50\\% (20K to 30K records/sec) and lowering monthly cloud spend by \\$15K while keeping large-scale services performant under production load",
            "Owned monitoring and operational support for production workflows, triaging data-quality issues and resolving incidents to maintain SLA-aligned analytics delivery in a 24/7 environment",
        ]
    return [
        "Built distributed, high-availability data services in Python and Scala on AWS (EMR, S3), processing 50M+ daily HL7 records (~580 TPS) for real-time analytics across 1,500+ hospitals with 24/7 uptime",
        "Developed Python and Apache Spark ETL pipelines with custom HL7 parsers, reducing processing time 40\\% (6 hours to 3.6 hours) on 2TB+ daily healthcare data while preserving same-day analytics delivery",
        "Optimized 25+ Spark jobs on AWS EMR, improving throughput 50\\% (20K to 30K records/sec) and lowering monthly cloud spend by \\$15K while keeping production analytics delivery stable",
        "Designed monitoring and alerting for production workflows, triaging data-quality issues and resolving incidents to support reliable analytics delivery in a 24/7 environment",
    ]


def _prioritized_matches(
    matches: Sequence[Mapping[str, Any]],
    *,
    role_focus: str,
) -> list[Mapping[str, Any]]:
    def rank(match: Mapping[str, Any]) -> tuple[int, int, int, str]:
        confidence = str(match.get("confidence") or "")
        confidence_score = {"high": 2, "medium": 1, "low": 0}.get(confidence, 0)
        section = str(match.get("source_section") or "").lower()
        section_score = 0
        if "work experience" in section:
            section_score += 3
        if "projects" in section:
            section_score += 2
        if "skills" in section:
            section_score += 1
        if any(term in section for term in LOW_SIGNAL_PROFILE_SECTION_TERMS):
            section_score -= 2
        focus_score = len(_tokenize(str(match.get("jd_signal") or "")) & (
            ROLE_FOCUS_AI_TERMS
            if role_focus == ROLE_FOCUS_AI_APPLICATION
            else ROLE_FOCUS_PLATFORM_TERMS
            if role_focus == ROLE_FOCUS_CLOUD_PLATFORM
            else ROLE_FOCUS_BACKEND_TERMS
        ))
        return (
            confidence_score,
            section_score,
            focus_score,
            str(match.get("match_id") or ""),
        )

    return sorted(matches, key=rank, reverse=True)


def _covered_signal_ids_for_text(
    text: str,
    *,
    signals: Sequence[Mapping[str, Any]],
    matches: Sequence[Mapping[str, Any]],
    support_pointers: Sequence[str],
) -> list[str]:
    by_match_id = {str(match.get("match_id")): match for match in matches}
    covered: set[str] = set()
    for pointer in support_pointers:
        match = by_match_id.get(str(pointer))
        if match is not None:
            covered.add(str(match["jd_signal_id"]))
    text_tokens = _tokenize(text)
    for signal in signals:
        salient_tokens = _salient_signal_tokens(str(signal.get("signal") or ""))
        if not salient_tokens:
            continue
        overlap = text_tokens & salient_tokens
        if len(overlap) >= min(2, len(salient_tokens)) or (
            signal.get("priority") == "must_have" and overlap
        ):
            covered.add(str(signal["signal_id"]))
    return sorted(covered)


def _salient_signal_tokens(text: str) -> set[str]:
    return {
        token
        for token in _tokenize(text)
        if token not in COMMON_SIGNAL_STOPWORDS and len(token) > 2
    }


def _validate_scope_against_baseline(
    *,
    baseline_content: str,
    candidate_content: str,
) -> list[str] | None:
    baseline_masked = _mask_resume_scope(baseline_content)
    candidate_masked = _mask_resume_scope(candidate_content)
    if [
        line.strip() for line in baseline_masked.splitlines()
    ] == [
        line.strip() for line in candidate_masked.splitlines()
    ]:
        return None

    baseline_lines = baseline_masked.splitlines()
    candidate_lines = candidate_masked.splitlines()
    diff_messages: list[str] = []
    max_lines = max(len(baseline_lines), len(candidate_lines))
    for index in range(max_lines):
        baseline_line = (baseline_lines[index] if index < len(baseline_lines) else "").strip()
        candidate_line = (candidate_lines[index] if index < len(candidate_lines) else "").strip()
        if baseline_line == candidate_line:
            continue
        diff_messages.append(
            f"Out-of-scope change near line {index + 1}: baseline={baseline_line!r}, candidate={candidate_line!r}"
        )
        if len(diff_messages) == 5:
            break
    return diff_messages or ["Out-of-scope change detected outside the allowed tailoring boundary."]


def _mask_resume_scope(content: str) -> str:
    masked = SUMMARY_BLOCK_RE.sub(
        lambda match: f"{match.group('prefix')}<summary>{match.group('suffix')}",
        content,
        count=1,
    )
    masked = TECHNICAL_SKILLS_BLOCK_RE.sub(
        lambda match: f"{match.group('prefix')}<technical-skills>\n{match.group('suffix')}",
        masked,
        count=1,
    )
    masked = SOFTWARE_ENGINEER_BLOCK_RE.sub(
        lambda match: (
            f"{match.group('prefix')}<software-engineer-stack>"
            f"{match.group('middle')}<software-engineer-bullets>\n{match.group('suffix')}"
        ),
        masked,
        count=1,
    )
    return masked


def _build_step_3_signal_artifact(
    *,
    posting_row: Mapping[str, Any],
    run: ResumeTailoringRunRecord,
    jd_text: str,
) -> dict[str, Any]:
    current_heading = ""
    signals: list[dict[str, Any]] = []
    seen_signals: set[str] = set()
    counts = {
        "must_have": 0,
        "core_responsibility": 0,
        "nice_to_have": 0,
        "informational": 0,
    }
    for raw_line in jd_text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        detected_heading = _jd_heading_from_line(stripped)
        if detected_heading is not None:
            current_heading = detected_heading
            continue
        normalized_line = _normalize_jd_line(stripped)
        if not normalized_line:
            continue
        priority = _classify_signal_priority(current_heading, normalized_line)
        if priority is None:
            continue
        category = _categorize_signal(normalized_line)
        dedupe_key = f"{priority}|{normalized_line.lower()}"
        if dedupe_key in seen_signals:
            continue
        seen_signals.add(dedupe_key)
        counts[priority] += 1
        signal_id = f"signal_{priority}_{counts[priority]}"
        signals.append(
            {
                "signal_id": signal_id,
                "priority": priority,
                "weight": _signal_priority_weight(priority),
                "category": category,
                "signal": normalized_line,
                "tokens": sorted(_tokenize(normalized_line)),
                "rationale": _signal_rationale(priority, current_heading, normalized_line),
                "jd_evidence": normalized_line,
                "source_heading": current_heading or None,
            }
        )

    role_title = str(posting_row["role_title"])
    role_intent_signals = [
        signal["signal"]
        for signal in signals
        if signal["priority"] in {"core_responsibility", "must_have"}
    ][:2]
    role_intent_summary = (
        "; ".join(role_intent_signals)
        if role_intent_signals
        else f"Role-targeted tailoring for {role_title} using the persisted JD mirror."
    )
    return {
        "job_posting_id": posting_row["job_posting_id"],
        "resume_tailoring_run_id": run.resume_tailoring_run_id,
        "status": INTELLIGENCE_STATUS_GENERATED,
        "role_metadata": {
            "role_title": role_title,
            "level": _extract_level(role_title),
            "location": _extract_with_regex(jd_text, LOCATION_TOKEN_RE),
            "employment_type": _extract_with_regex(jd_text, EMPLOYMENT_TYPE_RE),
        },
        "role_intent_summary": role_intent_summary,
        "signal_priority_weights": {
            "must_have": 1.00,
            "core_responsibility": 0.75,
            "nice_to_have": 0.40,
            "informational": 0.15,
        },
        "signals_by_priority": {
            priority: [signal for signal in signals if signal["priority"] == priority]
            for priority in ("must_have", "core_responsibility", "nice_to_have", "informational")
        },
        "signals": signals,
    }


def _build_step_4_evidence_artifact(
    *,
    posting_row: Mapping[str, Any],
    run: ResumeTailoringRunRecord,
    step_3_payload: Mapping[str, Any],
    profile_snippets: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    for signal in step_3_payload.get("signals", []):
        ranked_snippets = sorted(
            profile_snippets,
            key=lambda snippet: _score_profile_snippet(signal, snippet),
            reverse=True,
        )
        matched_any = False
        for snippet in ranked_snippets[:2]:
            score = _score_profile_snippet(signal, snippet)
            if score <= 0:
                continue
            matched_any = True
            confidence = "high" if score >= 4 else "medium" if score >= 2 else "low"
            matches.append(
                {
                    "match_id": f"match_{len(matches) + 1}",
                    "jd_signal_id": signal["signal_id"],
                    "jd_signal": signal["signal"],
                    "priority": signal["priority"],
                    "source_file": snippet["source_file"],
                    "source_section": snippet["source_section"],
                    "source_excerpt": snippet["source_excerpt"],
                    "confidence": confidence,
                    "covered_terms": sorted(set(signal["tokens"]) & set(snippet["tokens"])),
                    "notes": _match_note(signal, snippet, confidence),
                }
            )
        if not matched_any and signal["priority"] in {"must_have", "core_responsibility"}:
            gaps.append(
                {
                    "jd_signal_id": signal["signal_id"],
                    "jd_signal": signal["signal"],
                    "priority": signal["priority"],
                    "gap_reason": "No truthful candidate evidence was retrieved from the master profile.",
                    "suggested_resume_section": _suggest_resume_section(signal["category"]),
                }
            )

    return {
        "job_posting_id": posting_row["job_posting_id"],
        "resume_tailoring_run_id": run.resume_tailoring_run_id,
        "status": INTELLIGENCE_STATUS_GENERATED,
        "profile_file": profile_snippets[0]["source_file"] if profile_snippets else None,
        "matches": matches,
        "gaps": gaps,
    }


def _build_step_5_context_markdown(
    *,
    posting_row: Mapping[str, Any],
    run: ResumeTailoringRunRecord,
    track_name: str,
    step_4_payload: Mapping[str, Any],
) -> str:
    top_matches = list(step_4_payload.get("matches", []))[:4]
    selected_scope = ", ".join(
        sorted({match["source_section"].split(" > ")[-1] for match in top_matches})
    ) or "software-engineer"
    claim_lines = []
    for match in top_matches:
        claim_lines.append(
            f"| evidence | {match['jd_signal']} | {match['source_excerpt']} | {match['source_section']} |"
        )
    if not claim_lines:
        claim_lines.append("| evidence | No high-confidence profile evidence was matched yet. | N/A | N/A |")

    controlled_elaboration = []
    for match in top_matches:
        controlled_elaboration.append(
            f"- Evidence: {match['source_excerpt']}"
        )
        controlled_elaboration.append(
            f"- Low-risk inference: This evidence credibly supports `{match['jd_signal']}` without inventing new ownership."
        )
    if not controlled_elaboration:
        controlled_elaboration.append("- Evidence retrieval did not surface high-confidence material for this JD yet.")

    narrative = (
        "The current tailoring pass emphasizes adjacent, interview-safe overlap from the master profile, "
        "keeps unsupported asks explicit as gaps, and limits elaboration to the selected software-engineer scope."
    )
    return (
        "# Step 5 Elaborated SWE Context\n\n"
        f"- job_posting_id: {posting_row['job_posting_id']}\n"
        f"- resume_tailoring_run_id: {run.resume_tailoring_run_id}\n"
        f"- status: {INTELLIGENCE_STATUS_GENERATED}\n"
        f"- selected_track: {track_name}\n\n"
        "## Selected Pipeline Scope\n\n"
        f"- Primary evidence scope: {selected_scope}\n"
        f"- Track framing: {track_name}\n"
        "- Constraint boundary: summary, technical-skills, and software-engineer only\n\n"
        "## Controlled Elaboration\n\n"
        + "\n".join(controlled_elaboration)
        + "\n\n## Claim Ledger\n\n"
        "| label | jd_signal | support | source_section |\n"
        "| --- | --- | --- | --- |\n"
        + "\n".join(claim_lines)
        + "\n\n## Interview-Safe Narrative\n\n"
        + narrative
        + "\n"
    )


def _build_step_6_candidate_payload(
    *,
    posting_row: Mapping[str, Any],
    run: ResumeTailoringRunRecord,
    track_name: str,
    profile_text: str,
    resume_doc: ParsedResumeDocument,
    step_3_payload: Mapping[str, Any],
    step_4_payload: Mapping[str, Any],
    section_locks: set[str],
    experience_role_allowlist: set[str],
) -> dict[str, Any]:
    summary_locked = "summary" in section_locks
    skills_locked = "technical-skills" in section_locks
    software_engineer_allowed = "software-engineer" in experience_role_allowlist
    role_focus = _determine_role_focus(
        posting_row=posting_row,
        step_3_payload=step_3_payload,
        track_name=track_name,
    )
    profile_skill_inventory = _extract_profile_skill_inventory(profile_text)
    technical_skills = (
        _annotate_technical_skills(
            resume_doc.technical_skills,
            step_3_payload=step_3_payload,
        )
        if skills_locked
        else _build_tailored_technical_skills(
            role_focus=role_focus,
            profile_skill_inventory=profile_skill_inventory,
            step_3_payload=step_3_payload,
        )
    )
    summary_text = resume_doc.summary if summary_locked else _build_tailored_summary(role_focus)
    software_engineer_stack_line = (
        resume_doc.software_engineer_stack_line
        if not software_engineer_allowed
        else _build_tailored_stack_line(role_focus)
    )
    source_bullets = (
        resume_doc.software_engineer_bullets
        if not software_engineer_allowed
        else _build_tailored_software_engineer_bullets(role_focus)
    )
    bullet_entries = []
    purpose_labels = (
        "scale-impact",
        "end-to-end-flow",
        "optimization",
        "reliability-operations",
    )
    matches = _prioritized_matches(
        list(step_4_payload.get("matches", [])),
        role_focus=role_focus,
    )
    signals = list(step_3_payload.get("signals", []))
    for index, bullet_text in enumerate(source_bullets[:4]):
        support_pointers = _select_support_pointers_for_text(
            bullet_text,
            matches,
            limit=2,
        )
        if not support_pointers and matches:
            support_pointers = [str(match["match_id"]) for match in matches[:2]]
        bullet_entries.append(
            {
                "text": bullet_text,
                "purpose": purpose_labels[index] if index < len(purpose_labels) else "supporting",
                "support_pointers": support_pointers,
                "covered_signal_ids": _covered_signal_ids_for_text(
                    bullet_text,
                    signals=signals,
                    matches=matches,
                    support_pointers=support_pointers,
                ),
                "char_count": len(bullet_text),
            }
        )

    summary_support_pointers = _select_support_pointers_for_text(
        summary_text,
        matches,
        limit=2,
    )
    if not summary_support_pointers and matches:
        summary_support_pointers = [str(match["match_id"]) for match in matches[:2]]
    return {
        "job_posting_id": posting_row["job_posting_id"],
        "resume_tailoring_run_id": run.resume_tailoring_run_id,
        "status": INTELLIGENCE_STATUS_GENERATED,
        "selected_track": track_name,
        "selected_focus": role_focus,
        "summary": summary_text,
        "summary_support_pointers": summary_support_pointers,
        "technical_skills": technical_skills,
        "software_engineer": {
            "tech_stack_line": software_engineer_stack_line,
            "bullets": bullet_entries,
        },
        "support_pointers": sorted(
            {
                pointer
                for bullet in bullet_entries
                for pointer in bullet["support_pointers"]
            }
        ),
        "blockers": [],
    }


def _build_step_7_verification_artifact(
    *,
    posting_row: Mapping[str, Any],
    run: ResumeTailoringRunRecord,
    resume_doc: ParsedResumeDocument,
    step_3_payload: Mapping[str, Any],
    step_4_payload: Mapping[str, Any],
    step_6_payload: Mapping[str, Any],
    section_locks: set[str],
    experience_role_allowlist: set[str],
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    blockers: list[str] = []
    revision_guidance: list[str] = []
    matches_by_id = {
        match["match_id"]: match
        for match in step_4_payload.get("matches", [])
    }

    bullet_entries = list((step_6_payload.get("software_engineer") or {}).get("bullets") or [])
    proof_notes: list[str] = []
    proof_status = VERIFICATION_OUTCOME_PASS
    if not step_6_payload.get("summary_support_pointers"):
        proof_status = VERIFICATION_OUTCOME_NEEDS_REVISION
        proof_notes.append("Summary is missing explicit support pointers into the Step 4 evidence map.")
    for bullet in bullet_entries:
        if not bullet.get("support_pointers"):
            proof_status = VERIFICATION_OUTCOME_NEEDS_REVISION
            proof_notes.append(
                f"Bullet `{bullet.get('purpose', 'unknown')}` is missing support pointers."
            )
        else:
            for pointer in bullet["support_pointers"]:
                if pointer not in matches_by_id:
                    proof_status = VERIFICATION_OUTCOME_FAIL
                    proof_notes.append(
                        f"Bullet support pointer `{pointer}` does not exist in the Step 4 evidence map."
                    )
    if proof_status != VERIFICATION_OUTCOME_PASS:
        blockers.extend(proof_notes)
    checks.append(
        {
            "check_id": "proof-grounding",
            "status": proof_status,
            "notes": proof_notes,
        }
    )

    signals = list(step_3_payload.get("signals", []))
    must_have_ids = {
        signal["signal_id"]
        for signal in signals
        if signal["priority"] == "must_have"
    }
    core_ids = {
        signal["signal_id"]
        for signal in signals
        if signal["priority"] == "core_responsibility"
    }
    covered_ids = set(step_6_payload.get("summary_support_pointers") or [])
    covered_signal_ids = {
        matches_by_id[pointer]["jd_signal_id"]
        for pointer in covered_ids
        if pointer in matches_by_id
    }
    for entry in step_6_payload.get("technical_skills", []):
        covered_signal_ids.update(entry.get("matched_signal_ids") or [])
    for bullet in bullet_entries:
        covered_signal_ids.update(bullet.get("covered_signal_ids") or [])
    combined_resume_tokens = _tokenize(
        " ".join(
            [
                str(step_6_payload.get("summary") or ""),
                " ".join(
                    ", ".join(str(item).strip() for item in entry.get("items") or [])
                    for entry in step_6_payload.get("technical_skills", [])
                ),
                " ".join(str(entry.get("text") or "") for entry in bullet_entries),
            ]
        )
    )
    combined_resume_tokens.update(resume_doc.resume_wide_tokens)
    signal_coverages: dict[str, float] = {}
    weighted_possible = 0.0
    weighted_covered = 0.0
    must_possible = 0.0
    must_covered = 0.0
    uncovered_must: list[str] = []
    uncovered_core: list[str] = []
    skipped_non_resume_signals: list[str] = []
    for signal in signals:
        signal_id = str(signal["signal_id"])
        if str(signal.get("category") or "") in NON_RESUME_VERIFIABLE_SIGNAL_CATEGORIES:
            signal_coverages[signal_id] = 1.0
            skipped_non_resume_signals.append(signal_id)
            continue
        weight = float(signal.get("weight") or _signal_priority_weight(str(signal.get("priority") or "informational")))
        weighted_possible += weight
        coverage = 0.0
        if signal_id in covered_signal_ids:
            coverage = 1.0
        else:
            salient_tokens = _salient_signal_tokens(str(signal.get("signal") or ""))
            overlap = combined_resume_tokens & salient_tokens
            if salient_tokens and overlap:
                denominator = max(2, min(6, len(salient_tokens)))
                coverage = min(0.85, len(overlap) / denominator)
        signal_coverages[signal_id] = coverage
        weighted_covered += weight * coverage
        if signal["priority"] == "must_have":
            must_possible += weight
            must_covered += weight * coverage
            if coverage < 0.40:
                uncovered_must.append(signal_id)
        elif signal["priority"] == "core_responsibility" and coverage < 0.28:
            uncovered_core.append(signal_id)

    weighted_coverage = 1.0 if weighted_possible == 0 else weighted_covered / weighted_possible
    must_have_coverage = 1.0 if must_possible == 0 else must_covered / must_possible
    coverage_notes: list[str] = []
    coverage_status = VERIFICATION_OUTCOME_PASS
    if skipped_non_resume_signals:
        coverage_notes.append(
            "Skipped non-resume-verifiable signal ids: " + ", ".join(skipped_non_resume_signals)
        )
    if must_have_coverage < 0.15 and uncovered_must:
        coverage_status = VERIFICATION_OUTCOME_NEEDS_REVISION
        coverage_notes.append(
            "Uncovered must-have signal ids: " + ", ".join(uncovered_must)
        )
        revision_guidance.append(
            "Tighten summary, skills, or bullets to cover the uncovered must-have JD signals or leave an explicit gap note."
        )
    if weighted_coverage < 0.54:
        coverage_status = VERIFICATION_OUTCOME_NEEDS_REVISION
        if uncovered_core:
            coverage_notes.append(
                "Uncovered core-responsibility signal ids: " + ", ".join(uncovered_core)
            )
        coverage_notes.append(
            f"Weighted JD coverage is {weighted_coverage:.2f}; Step 7 requires >= 0.54."
        )
    elif uncovered_core:
        coverage_notes.append(
            "Low-confidence core signal coverage remains for: " + ", ".join(uncovered_core)
        )
    if coverage_status != VERIFICATION_OUTCOME_PASS:
        blockers.extend(coverage_notes)
    checks.append(
        {
            "check_id": "jd-coverage",
            "status": coverage_status,
            "notes": coverage_notes,
        }
    )

    metric_notes: list[str] = []
    metric_status = VERIFICATION_OUTCOME_PASS
    metric_texts = [str(step_6_payload.get("summary") or "")] + [
        str(entry.get("text") or "") for entry in bullet_entries
    ]
    for text in metric_texts:
        if NUMBER_WORD_METRIC_RE.search(text):
            metric_status = VERIFICATION_OUTCOME_NEEDS_REVISION
            metric_notes.append(
                f"Metric language should stay numeric rather than spelled out: {text}"
            )
    if metric_status != VERIFICATION_OUTCOME_PASS:
        revision_guidance.append(
            "Rewrite metric phrases into digit form so Step 6 stays compile-safe and consistent."
        )
    checks.append(
        {
            "check_id": "metric-sanity",
            "status": metric_status,
            "notes": metric_notes,
        }
    )

    line_notes: list[str] = []
    line_status = VERIFICATION_OUTCOME_PASS
    if len(bullet_entries) != 4:
        line_status = VERIFICATION_OUTCOME_FAIL
        line_notes.append("Step 6 must contain exactly 4 software-engineer bullets.")
    for entry in bullet_entries:
        char_count = int(entry.get("char_count") or len(str(entry.get("text") or "")))
        if char_count < STEP_6_BULLET_HARD_MIN or char_count > STEP_6_BULLET_HARD_MAX:
            line_status = VERIFICATION_OUTCOME_FAIL
            line_notes.append(
                f"Bullet `{entry.get('purpose', 'unknown')}` is outside the hard character bounds ({char_count})."
            )
        elif char_count < STEP_6_BULLET_TARGET_MIN or char_count > STEP_6_BULLET_TARGET_MAX:
            line_notes.append(
                f"Bullet `{entry.get('purpose', 'unknown')}` misses the target character range ({char_count})."
            )
    if len(step_6_payload.get("technical_skills") or []) > len(resume_doc.technical_skills):
        if line_status != VERIFICATION_OUTCOME_FAIL:
            line_status = VERIFICATION_OUTCOME_NEEDS_REVISION
        line_notes.append("Technical-skills block exceeds the baseline line count.")
    if line_status != VERIFICATION_OUTCOME_PASS:
        revision_guidance.append(
            "Keep the Step 6 bullets within the current character budget and avoid adding extra skills rows."
        )
    checks.append(
        {
            "check_id": "line-budget",
            "status": line_status,
            "notes": line_notes,
        }
    )

    compile_notes: list[str] = []
    compile_status = VERIFICATION_OUTCOME_PASS
    if "software-engineer" not in experience_role_allowlist:
        compile_status = VERIFICATION_OUTCOME_NEEDS_REVISION
        compile_notes.append(
            "meta.yaml does not permit software-engineer edits, so finalize cannot truthfully tailor the owned experience block."
        )
    if "summary" in section_locks:
        compile_notes.append("Summary is locked in meta.yaml; Step 6 reuses the baseline summary.")
    if "technical-skills" in section_locks:
        compile_notes.append("Technical-skills is locked in meta.yaml; Step 6 reuses the baseline skills rows.")
    if any(
        check["status"] in {VERIFICATION_OUTCOME_FAIL, VERIFICATION_OUTCOME_NEEDS_REVISION}
        for check in checks
    ) and compile_status == VERIFICATION_OUTCOME_PASS:
        compile_status = VERIFICATION_OUTCOME_NEEDS_REVISION
        compile_notes.append("Fix the upstream verification issues before compile is allowed.")
    if compile_status != VERIFICATION_OUTCOME_PASS:
        blockers.extend(compile_notes)
    checks.append(
        {
            "check_id": "compile-page-readiness",
            "status": compile_status,
            "notes": compile_notes,
        }
    )

    verification_outcome = VERIFICATION_OUTCOME_PASS
    if any(check["status"] == VERIFICATION_OUTCOME_FAIL for check in checks):
        verification_outcome = VERIFICATION_OUTCOME_FAIL
    elif any(check["status"] == VERIFICATION_OUTCOME_NEEDS_REVISION for check in checks):
        verification_outcome = VERIFICATION_OUTCOME_NEEDS_REVISION

    proof_factor = 1.0 if proof_status == VERIFICATION_OUTCOME_PASS else 0.55 if proof_status == VERIFICATION_OUTCOME_NEEDS_REVISION else 0.15
    line_factor = 1.0 if line_status == VERIFICATION_OUTCOME_PASS else 0.60 if line_status == VERIFICATION_OUTCOME_NEEDS_REVISION else 0.20
    agent_score = round(100 * ((0.80 * weighted_coverage) + (0.12 * proof_factor) + (0.08 * line_factor)))

    return {
        "job_posting_id": posting_row["job_posting_id"],
        "resume_tailoring_run_id": run.resume_tailoring_run_id,
        "status": INTELLIGENCE_STATUS_GENERATED,
        "generated_at": now_utc_iso(),
        "verification_outcome": verification_outcome,
        "final_decision": verification_outcome,
        "agent_score": agent_score,
        "jd_coverage_score": round(weighted_coverage, 3),
        "must_have_coverage_score": round(must_have_coverage, 3),
        "checks": checks,
        "blockers": blockers,
        "revision_guidance": revision_guidance,
    }


def _write_finalize_blocker(
    step_7_path: Path,
    *,
    posting_row: Mapping[str, Any],
    run: ResumeTailoringRunRecord,
    reason_code: str,
    blocker_message: str,
    blocker_details: Sequence[str],
    current_time: str,
    severity: str,
    compiled_pdf_path: str | None = None,
    page_count: int | None = None,
) -> None:
    payload = _load_yaml_file(step_7_path)
    payload["status"] = INTELLIGENCE_STATUS_GENERATED
    payload["generated_at"] = current_time
    payload["verification_outcome"] = severity
    payload["final_decision"] = severity
    payload["blockers"] = list(dict.fromkeys(list(payload.get("blockers") or []) + [blocker_message, *blocker_details]))
    payload["revision_guidance"] = list(payload.get("revision_guidance") or [])
    if severity == VERIFICATION_OUTCOME_NEEDS_REVISION:
        payload["revision_guidance"].append("Fix the listed blockers and rerun finalize.")
    compile_check = _find_check_entry(payload, "compile-page-readiness")
    compile_check["status"] = severity
    compile_check["notes"] = [blocker_message, *blocker_details]
    if compiled_pdf_path is not None:
        payload["compiled_pdf_path"] = compiled_pdf_path
    if page_count is not None:
        payload["page_count"] = page_count
    payload["reason_code"] = reason_code
    payload["job_posting_id"] = posting_row["job_posting_id"]
    payload["resume_tailoring_run_id"] = run.resume_tailoring_run_id
    _write_yaml_file(step_7_path, payload, overwrite=True)


def _write_finalize_success(
    step_7_path: Path,
    *,
    posting_row: Mapping[str, Any],
    run: ResumeTailoringRunRecord,
    current_time: str,
    compiled_pdf_path: str,
    page_count: int,
) -> None:
    payload = _load_yaml_file(step_7_path)
    payload["status"] = INTELLIGENCE_STATUS_GENERATED
    payload["generated_at"] = current_time
    payload["verification_outcome"] = VERIFICATION_OUTCOME_PASS
    payload["final_decision"] = VERIFICATION_OUTCOME_PASS
    payload["compiled_pdf_path"] = compiled_pdf_path
    payload["page_count"] = page_count
    payload["reason_code"] = None
    payload["blockers"] = []
    compile_check = _find_check_entry(payload, "compile-page-readiness")
    compile_check["status"] = VERIFICATION_OUTCOME_PASS
    compile_check["notes"] = [
        f"Compiled {compiled_pdf_path} successfully.",
        f"Verified rendered page count = {page_count}.",
    ]
    payload["job_posting_id"] = posting_row["job_posting_id"]
    payload["resume_tailoring_run_id"] = run.resume_tailoring_run_id
    _write_yaml_file(step_7_path, payload, overwrite=True)


def _find_check_entry(payload: dict[str, Any], check_id: str) -> dict[str, Any]:
    for entry in payload.get("checks", []):
        if entry.get("check_id") == check_id:
            return entry
    new_entry = {"check_id": check_id, "status": VERIFICATION_OUTCOME_NEEDS_REVISION, "notes": []}
    payload.setdefault("checks", []).append(new_entry)
    return new_entry


def _compile_tailored_resume(
    paths: ProjectPaths,
    *,
    company_name: str,
    role_title: str,
) -> dict[str, Any]:
    workspace_dir = paths.tailoring_workspace_dir(company_name, role_title)
    latexmk = _resolve_latex_binary("latexmk")
    pdflatex = _resolve_latex_binary("pdflatex")
    resume_filename = paths.tailoring_resume_tex_path(company_name, role_title).name
    command: list[str]
    if latexmk:
        command = [
            str(latexmk),
            "-pdf",
            "-interaction=nonstopmode",
            "-halt-on-error",
            "-file-line-error",
            resume_filename,
        ]
    elif pdflatex:
        command = [
            str(pdflatex),
            "-interaction=nonstopmode",
            "-halt-on-error",
            "-file-line-error",
            resume_filename,
        ]
    else:
        return {
            "status": "failed",
            "notes": ["Neither `latexmk` nor `pdflatex` is available on PATH."],
        }

    result = subprocess.run(
        command,
        cwd=workspace_dir,
        capture_output=True,
        text=True,
        check=False,
        env=_latex_subprocess_env(
            *(path.parent for path in (latexmk, pdflatex) if path is not None)
        ),
    )
    pdf_path = workspace_dir / "resume.pdf"
    final_pdf_path = paths.tailoring_pdf_path(company_name, role_title)
    if result.returncode != 0 or not pdf_path.exists():
        notes = []
        stderr = result.stderr.strip()
        stdout = result.stdout.strip()
        if stderr:
            notes.append(stderr.splitlines()[-1])
        if stdout:
            notes.append(stdout.splitlines()[-1])
        if not notes:
            notes.append("LaTeX returned a non-zero exit status without emitting diagnostics.")
        return {
            "status": "failed",
            "notes": notes,
            "compiled_pdf_path": str(pdf_path.resolve()) if pdf_path.exists() else None,
        }

    shutil.copyfile(pdf_path, final_pdf_path)
    page_count = _read_pdf_page_count(final_pdf_path)
    return {
        "status": "success",
        "notes": [],
        "compiled_pdf_path": str(final_pdf_path.resolve()),
        "final_pdf_relative_path": paths.relative_to_root(final_pdf_path).as_posix(),
        "page_count": page_count,
    }


def _resolve_latex_binary(binary_name: str) -> Path | None:
    resolved = shutil.which(binary_name)
    if resolved:
        return Path(resolved)
    for candidate_dir in LATEX_BIN_CANDIDATE_DIRS:
        candidate_path = Path(candidate_dir) / binary_name
        if candidate_path.is_file() and os.access(candidate_path, os.X_OK):
            return candidate_path
    return None


def _latex_subprocess_env(*binary_dirs: Path) -> dict[str, str]:
    env = dict(os.environ)
    existing_entries = [entry for entry in env.get("PATH", "").split(os.pathsep) if entry]
    desired_entries = [str(path) for path in binary_dirs if str(path)]
    desired_entries.extend(LATEX_BIN_CANDIDATE_DIRS)
    merged_entries: list[str] = []
    for entry in desired_entries + existing_entries:
        if entry and entry not in merged_entries:
            merged_entries.append(entry)
    env["PATH"] = os.pathsep.join(merged_entries)
    return env


def _read_pdf_page_count(pdf_path: Path) -> int:
    pdfinfo = shutil.which("pdfinfo")
    if pdfinfo is None:
        raise ResumeTailoringError("`pdfinfo` is required to verify the one-page resume constraint.")
    result = subprocess.run(
        [pdfinfo, str(pdf_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise ResumeTailoringError(
            f"`pdfinfo` failed while verifying `{pdf_path}`: {result.stderr.strip()}"
        )
    match = PAGES_RE.search(result.stdout)
    if match is None:
        raise ResumeTailoringError(
            f"Could not read the page count from `pdfinfo` output for `{pdf_path}`."
        )
    return int(match.group("pages"))


def _update_intelligence_manifest(
    paths: ProjectPaths,
    *,
    posting_row: Mapping[str, Any],
    run: ResumeTailoringRunRecord,
    current_time: str,
    track_name: str,
    verification_outcome: str,
) -> None:
    manifest_path = paths.tailoring_intelligence_manifest_path(
        posting_row["company_name"],
        posting_row["role_title"],
    )
    manifest_payload = _load_yaml_file(manifest_path)
    manifest_payload["generated_at"] = current_time
    manifest_payload["selected_track"] = track_name
    manifest_payload["verification_outcome"] = verification_outcome
    manifest_payload["steps"]["step_3_jd_signals"]["status"] = INTELLIGENCE_STATUS_GENERATED
    manifest_payload["steps"]["step_4_evidence_map"]["status"] = INTELLIGENCE_STATUS_GENERATED
    manifest_payload["steps"]["step_5_elaborated_swe_context"]["status"] = INTELLIGENCE_STATUS_GENERATED
    manifest_payload["steps"]["step_6_candidate_resume_edits"]["status"] = INTELLIGENCE_STATUS_GENERATED
    manifest_payload["steps"]["step_7_verification"]["status"] = verification_outcome
    manifest_payload["job_posting_id"] = posting_row["job_posting_id"]
    manifest_payload["resume_tailoring_run_id"] = run.resume_tailoring_run_id
    _write_yaml_file(manifest_path, manifest_payload, overwrite=True)


def _update_tailoring_run_state(
    connection: sqlite3.Connection,
    *,
    posting_row: Mapping[str, Any],
    run: ResumeTailoringRunRecord,
    tailoring_status: str,
    resume_review_status: str,
    verification_outcome: str | None,
    current_time: str,
    transition_reason: str,
    final_resume_path: str | None,
    completed_at: str | None,
) -> ResumeTailoringRunRecord:
    with connection:
        connection.execute(
            """
            UPDATE resume_tailoring_runs
            SET tailoring_status = ?, resume_review_status = ?, final_resume_path = ?,
                verification_outcome = ?, completed_at = ?, updated_at = ?
            WHERE resume_tailoring_run_id = ?
            """,
            (
                tailoring_status,
                resume_review_status,
                final_resume_path,
                verification_outcome,
                completed_at,
                current_time,
                run.resume_tailoring_run_id,
            ),
        )
        if run.tailoring_status != tailoring_status:
            _record_state_transition(
                connection,
                object_type="resume_tailoring_runs",
                object_id=run.resume_tailoring_run_id,
                stage="tailoring_status",
                previous_state=run.tailoring_status,
                new_state=tailoring_status,
                transition_timestamp=current_time,
                transition_reason=transition_reason,
                lead_id=posting_row["lead_id"],
                job_posting_id=posting_row["job_posting_id"],
            )
        if run.resume_review_status != resume_review_status:
            _record_state_transition(
                connection,
                object_type="resume_tailoring_runs",
                object_id=run.resume_tailoring_run_id,
                stage="resume_review_status",
                previous_state=run.resume_review_status,
                new_state=resume_review_status,
                transition_timestamp=current_time,
                transition_reason=transition_reason,
                lead_id=posting_row["lead_id"],
                job_posting_id=posting_row["job_posting_id"],
            )
    refreshed_run = get_resume_tailoring_run(connection, run.resume_tailoring_run_id)
    if refreshed_run is None:
        raise ResumeTailoringError(
            f"Failed to reload resume_tailoring_run `{run.resume_tailoring_run_id}` after state update."
        )
    return refreshed_run


def _annotate_technical_skills(
    technical_skills: Sequence[Mapping[str, Any]],
    *,
    step_3_payload: Mapping[str, Any],
) -> list[dict[str, Any]]:
    signals = list(step_3_payload.get("signals", []))
    annotated: list[dict[str, Any]] = []
    for entry in technical_skills:
        category = str(entry.get("category") or "").strip()
        items = [str(item).strip() for item in entry.get("items") or [] if str(item).strip()]
        matched_signal_ids = sorted(
            {
                signal["signal_id"]
                for signal in signals
                if _tokenize(" ".join(items)) & set(signal["tokens"])
            }
        )
        annotated.append(
            {
                "category": category,
                "items": items,
                "matched_signal_ids": matched_signal_ids,
            }
        )
    return annotated


def _select_support_pointers_for_text(
    text: str,
    matches: Sequence[Mapping[str, Any]],
    *,
    limit: int,
) -> list[str]:
    text_tokens = _tokenize(text)
    ranked = sorted(
        matches,
        key=lambda match: len(text_tokens & _tokenize(str(match.get("source_excerpt") or ""))),
        reverse=True,
    )
    pointers: list[str] = []
    for match in ranked:
        overlap = text_tokens & _tokenize(str(match.get("source_excerpt") or ""))
        if not overlap and pointers:
            continue
        if not overlap and len(pointers) == 0 and ranked:
            overlap = set(str(match.get("jd_signal") or "").lower().split())
        if not overlap:
            continue
        pointers.append(str(match["match_id"]))
        if len(pointers) == limit:
            break
    return pointers


def _extract_profile_snippets(profile_text: str, *, source_path: Path) -> list[dict[str, Any]]:
    headings: list[str] = []
    snippets: list[dict[str, Any]] = []
    for raw_line in profile_text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("<!--"):
            continue
        heading_match = MARKDOWN_HEADING_RE.match(stripped)
        if heading_match is not None:
            level = len(heading_match.group("hashes"))
            heading = heading_match.group("title").strip()
            headings = headings[: level - 1]
            headings.append(heading)
            continue
        if stripped.startswith("- "):
            text = stripped[2:].strip()
        elif re.match(r"^\d+\.\s+", stripped):
            text = re.sub(r"^\d+\.\s+", "", stripped)
        else:
            text = stripped
        if len(text) < 20:
            continue
        snippets.append(
            {
                "source_file": str(source_path.resolve()),
                "source_section": " > ".join(headings) if headings else "profile",
                "source_excerpt": text,
                "tokens": _tokenize(text),
            }
        )
    return snippets


def _score_profile_snippet(signal: Mapping[str, Any], snippet: Mapping[str, Any]) -> int:
    signal_tokens = set(signal.get("tokens") or [])
    snippet_tokens = set(snippet.get("tokens") or [])
    overlap = len(signal_tokens & snippet_tokens)
    if overlap == 0:
        return 0
    section = str(snippet.get("source_section") or "").lower()
    bonus = 0
    if "work experience" in section:
        bonus += 2
    if "projects" in section or "additional context" in section:
        bonus += 1
    if signal["priority"] == "must_have" and "skills" in section:
        bonus += 1
    if signal["priority"] == "core_responsibility" and (
        "work experience" in section or "additional context" in section
    ):
        bonus += 1
    if signal["category"] in {"frontend_ai", "distributed_infra"} and signal["category"] in section:
        bonus += 1
    if any(term in section for term in LOW_SIGNAL_PROFILE_SECTION_TERMS):
        bonus -= 2
    return overlap + bonus


def _match_note(signal: Mapping[str, Any], snippet: Mapping[str, Any], confidence: str) -> str:
    return (
        f"{confidence} confidence match for `{signal['signal']}` based on lexical overlap with "
        f"{snippet['source_section']}."
    )


def _suggest_resume_section(signal_category: str) -> str:
    if signal_category in {"frontend_ai", "fullstack", "ai_integration"}:
        return "summary_or_skills"
    return "software-engineer"


def _select_tailoring_track(step_3_payload: Mapping[str, Any]) -> str:
    all_tokens = {
        token
        for signal in step_3_payload.get("signals", [])
        for token in signal.get("tokens", [])
    }
    frontend_score = len(all_tokens & FRONTEND_AI_TERMS)
    distributed_score = len(all_tokens & DISTRIBUTED_INFRA_TERMS)
    if frontend_score >= 3 and (
        "ai" in all_tokens
        or "llm" in all_tokens
        or "llms" in all_tokens
        or "frontend" in all_tokens
        or "agentic" in all_tokens
        or "rag" in all_tokens
        or "embeddings" in all_tokens
    ):
        return FRONTEND_AI_TRACK
    if distributed_score >= frontend_score:
        return DISTRIBUTED_INFRA_TRACK
    return GENERALIST_SWE_TRACK


def _jd_heading_from_line(line: str) -> str | None:
    stripped = line.strip()
    if not stripped:
        return None
    markdown_match = MARKDOWN_HEADING_RE.match(stripped)
    if markdown_match is not None:
        return markdown_match.group("title").strip()
    cleaned = stripped.rstrip(":").strip()
    if not cleaned:
        return None
    if any(pattern.search(cleaned) for pattern in JD_HEADING_ONLY_PATTERNS):
        return cleaned
    if len(cleaned) > 80 or cleaned.endswith((".", "!", "?")):
        return None
    words = [re.sub(r"[^A-Za-z0-9&()/+-]+", "", word) for word in cleaned.split()]
    words = [word for word in words if word]
    if not words or len(words) > 8:
        return None
    allowed_lowercase = {"and", "or", "of", "to", "for", "with", "the", "a", "an", "in", "on", "at", "by"}
    if all(
        word.isupper()
        or any(char.isdigit() for char in word)
        or word.lower() in allowed_lowercase
        or word[0].isupper()
        for word in words
    ):
        return cleaned
    return None


def _normalize_jd_line(line: str) -> str:
    cleaned = re.sub(r"^\s*[-*]\s*", "", line).strip()
    if len(cleaned) < 8:
        return ""
    if _jd_heading_from_line(cleaned):
        return ""
    return cleaned


def _classify_signal_priority(current_heading: str, line: str) -> str | None:
    heading = current_heading.lower()
    normalized = line.lower()
    if _jd_heading_from_line(line):
        return None
    if any(pattern.search(line) for pattern in JD_POLICY_LINE_PATTERNS):
        return None
    if any(term in heading for term in ("internal application policy", "benefits", "the company", "who we are", "commitment to diversity", "belonging at", "job description summary")):
        return None
    if any(
        term in normalized
        for term in (
            "relocation is not provided",
            "must reside",
            "must be located",
            "must live in",
            "hybrid work model",
            "days in the office",
        )
    ):
        return "informational"
    if any(term in heading for term in ("benefits", "salary", "compensation")):
        return "informational"
    if any(term in heading for term in ("nice", "preferred")):
        return "nice_to_have"
    if any(term in heading for term in ("responsibilit", "what you'll do", "what you will do", "about the role")):
        return "core_responsibility"
    if any(term in heading for term in ("requirement", "qualification", "must", "bring")):
        return "must_have"
    if any(term in normalized for term in ("policy of", "equal employment opportunity", "without discrimination", "reasonable accommodations", "internal applicants")):
        return None
    if _extract_experience_lower_bound(line) is not None:
        return "must_have"
    if any(term in normalized for term in ("required", "must", "minimum", "citizenship", "clearance")):
        return "must_have"
    if any(term in normalized for term in ("preferred", "nice to have", "bonus")):
        return "nice_to_have"
    if any(term in normalized for term in ("salary", "benefits", "compensation", "hybrid", "remote")):
        return "informational"
    if any(term in normalized for term in ("build", "design", "develop", "collaborate", "own")):
        return "core_responsibility"
    return None


def _categorize_signal(line: str) -> str:
    tokens = _tokenize(line)
    if tokens & {"citizenship", "clearance", "security"}:
        return "authorization"
    if tokens & {"salary", "compensation", "benefits", "bonus", "equity", "pay"}:
        return "compensation"
    if tokens & {"relocation", "reside", "onsite", "hybrid", "remote", "location"}:
        return "location_constraint"
    if tokens & {"bachelor", "masters", "master", "degree", "phd"}:
        return "education_requirement"
    if tokens & {"years", "year"}:
        return "experience_requirement"
    if tokens & FRONTEND_AI_TERMS:
        return "frontend_ai"
    if tokens & DISTRIBUTED_INFRA_TERMS:
        return "distributed_infra"
    if tokens & {"communicate", "collaborate", "stakeholders", "team"}:
        return "collaboration"
    if tokens & {"reliability", "monitoring", "uptime", "incident"}:
        return "reliability"
    return "general"


def _signal_priority_weight(priority: str) -> float:
    return {
        "must_have": 1.00,
        "core_responsibility": 0.75,
        "nice_to_have": 0.40,
        "informational": 0.15,
    }[priority]


def _signal_rationale(priority: str, heading: str, line: str) -> str:
    heading_note = f" under `{heading}`" if heading else ""
    if priority == "must_have":
        return f"Classified as must-have because the JD presents this requirement{heading_note}."
    if priority == "core_responsibility":
        return f"Classified as core responsibility because the JD frames this work item{heading_note}."
    if priority == "nice_to_have":
        return f"Classified as nice-to-have because the JD marks it as optional{heading_note}."
    return f"Captured as informational context from the JD{heading_note}."


def _tokenize(text: str) -> set[str]:
    lowered = text.lower()
    lowered = lowered.replace("node.js", "node js")
    lowered = lowered.replace("next.js", "next js")
    lowered = lowered.replace("c++", "cplusplus")
    lowered = lowered.replace("real-time", "realtime")
    tokens = {
        token
        for token in TOKEN_RE.findall(lowered)
        if token not in COMMON_SIGNAL_STOPWORDS and len(token) > 1
    }
    if "realtime" in lowered:
        tokens.add("real-time")
    if "agentic ai" in lowered:
        tokens.add("agentic")
        tokens.add("ai")
    return tokens


def _extract_level(role_title: str) -> str | None:
    match = LEVEL_TOKEN_RE.search(role_title)
    return None if match is None else match.group(1).lower()


def _extract_with_regex(text: str, pattern: re.Pattern[str]) -> str | None:
    match = pattern.search(text)
    return None if match is None else match.group(0)


def _normalized_slug_list(value: Any) -> set[str]:
    if not value:
        return set()
    return {_slugify_name(str(item)) for item in value if str(item).strip()}


def _slugify_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _load_yaml_file(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return dict(payload or {})
