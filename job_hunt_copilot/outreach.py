from __future__ import annotations

import base64
import html
import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence
from zoneinfo import ZoneInfo

import yaml

from .artifacts import ArtifactLinkage, publish_json_artifact, register_artifact_record, write_json_contract
from .company_keys import ensure_missing_posting_company_keys, posting_company_key_from_row
from .delivery_feedback import MailboxFeedbackObserver, run_immediate_delivery_feedback_poll
from .paths import ProjectPaths
from .records import lifecycle_timestamps, new_canonical_id

OUTREACH_COMPONENT = "email_drafting_sending"
OUTREACH_DRAFT_ARTIFACT_TYPE = "email_draft"
OUTREACH_DRAFT_HTML_ARTIFACT_TYPE = "email_draft_html"
OPENER_DECISION_ARTIFACT_TYPE = "opener_decision"
SEND_RESULT_ARTIFACT_TYPE = "send_result"

JOB_POSTING_STATUS_REQUIRES_CONTACTS = "requires_contacts"
JOB_POSTING_STATUS_READY_FOR_OUTREACH = "ready_for_outreach"
JOB_POSTING_STATUS_OUTREACH_IN_PROGRESS = "outreach_in_progress"
JOB_POSTING_STATUS_COMPLETED = "completed"

CONTACT_STATUS_WORKING_EMAIL_FOUND = "working_email_found"
CONTACT_STATUS_OUTREACH_IN_PROGRESS = "outreach_in_progress"
CONTACT_STATUS_SENT = "sent"
CONTACT_STATUS_EXHAUSTED = "exhausted"
POSTING_CONTACT_STATUS_IDENTIFIED = "identified"
POSTING_CONTACT_STATUS_SHORTLISTED = "shortlisted"
POSTING_CONTACT_STATUS_OUTREACH_IN_PROGRESS = "outreach_in_progress"
POSTING_CONTACT_STATUS_OUTREACH_DONE = "outreach_done"
POSTING_CONTACT_STATUS_EXHAUSTED = "exhausted"

RECIPIENT_TYPE_RECRUITER = "recruiter"
RECIPIENT_TYPE_HIRING_MANAGER = "hiring_manager"
RECIPIENT_TYPE_ENGINEER = "engineer"
RECIPIENT_TYPE_ALUMNI = "alumni"
RECIPIENT_TYPE_OTHER_INTERNAL = "other_internal"
RECIPIENT_TYPE_FOUNDER = "founder"

AUTOMATIC_SEND_SET_LIMIT = 3
AUTOMATIC_POSTING_DAILY_SEND_CAP = 4
MIN_INTER_SEND_GAP_MINUTES = 6
MAX_INTER_SEND_GAP_MINUTES = 10
JOB_HUNT_COPILOT_REPO_URL = "https://github.com/sontiachyut/job-hunt-copilot-v4"

SEND_SET_PRIMARY_SLOTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("recruiter", (RECIPIENT_TYPE_RECRUITER,)),
    ("manager_adjacent", (RECIPIENT_TYPE_HIRING_MANAGER, RECIPIENT_TYPE_FOUNDER)),
    ("engineer", (RECIPIENT_TYPE_ENGINEER,)),
)
SEND_SET_FALLBACK_TYPE_ORDER = (
    RECIPIENT_TYPE_HIRING_MANAGER,
    RECIPIENT_TYPE_FOUNDER,
    RECIPIENT_TYPE_RECRUITER,
    RECIPIENT_TYPE_ENGINEER,
    RECIPIENT_TYPE_ALUMNI,
    RECIPIENT_TYPE_OTHER_INTERNAL,
)

_CANDIDATE_STATE_READY = "ready"
_CANDIDATE_STATE_NEEDS_EMAIL = "needs_email"
_CANDIDATE_STATE_REPEAT_REVIEW = "repeat_review"
_CANDIDATE_STATE_SAME_COMPANY_SENT = "same_company_sent"
_CANDIDATE_STATE_UNAVAILABLE = "unavailable"

OUTREACH_MODE_ROLE_TARGETED = "role_targeted"
OUTREACH_MODE_GENERAL_LEARNING = "general_learning"
MESSAGE_STATUS_GENERATED = "generated"
MESSAGE_STATUS_BLOCKED = "blocked"
MESSAGE_STATUS_FAILED = "failed"
MESSAGE_STATUS_SENT = "sent"

CLAIM_MODE_DIRECT_BACKGROUND = "direct_background"
CLAIM_MODE_ADJACENT_OVERLAP = "adjacent_overlap"
CLAIM_MODE_GROWTH_AREA = "growth_area"
CLAIM_MODE_INTEREST_AREA = "interest_area"

SEND_OUTCOME_SENT = "sent"
SEND_OUTCOME_FAILED = "failed"
SEND_OUTCOME_AMBIGUOUS = "ambiguous"

TRANSIENT_SEND_RETRY_COOLDOWN_MINUTES = 15
MAX_AUTOMATIC_TRANSIENT_SEND_RETRIES = 3
TRANSIENT_SEND_RETRY_PACING_REASON = "transient_send_retry_cooldown"
TRANSIENT_SEND_FAILURE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"nameresolutionerror", re.IGNORECASE),
    re.compile(r"failed to resolve", re.IGNORECASE),
    re.compile(r"temporary failure in name resolution", re.IGNORECASE),
    re.compile(r"max retries exceeded", re.IGNORECASE),
    re.compile(r"newconnectionerror", re.IGNORECASE),
    re.compile(r"connecttimeout", re.IGNORECASE),
    re.compile(r"read timed out", re.IGNORECASE),
    re.compile(r"connection reset", re.IGNORECASE),
    re.compile(r"connection aborted", re.IGNORECASE),
    re.compile(r"remotedisconnected", re.IGNORECASE),
    re.compile(r"temporar(?:ily|y) unavailable", re.IGNORECASE),
)

PROFILE_FIELD_RE = re.compile(r"^- \*\*(?P<label>[^*]+):\*\* (?P<value>.+?)\s*$")
MARKDOWN_HEADING_RE = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<title>.+?)\s*$")
METRIC_RE = re.compile(r"\b(?:\$?\d[\d,.]*\+?%?|\d[\d,.]*\+?(?:\s?(?:TPS|ms|hours?|day|days|hospitals?|users?|microservices?|records(?:/second)?|students?|tests?|bugs?)))\b")
NAME_SPLIT_RE = re.compile(r"\s+")
ROLE_SIGNAL_BOILERPLATE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b\d+\+?\s+years?\b", re.IGNORECASE),
    re.compile(r"\bbachelor", re.IGNORECASE),
    re.compile(r"\bequal opportunity", re.IGNORECASE),
    re.compile(r"\bpay range\b", re.IGNORECASE),
    re.compile(r"\badditional compensation\b", re.IGNORECASE),
    re.compile(r"\bbenefits\b", re.IGNORECASE),
    re.compile(r"\bapply today\b", re.IGNORECASE),
    re.compile(r"\bfind us at\b", re.IGNORECASE),
    re.compile(r"\bfor over \d+ years\b", re.IGNORECASE),
    re.compile(r"\bnationalities\b", re.IGNORECASE),
    re.compile(r"\bdiversity\b", re.IGNORECASE),
    re.compile(r"\bsustainability\b", re.IGNORECASE),
    re.compile(r"\bhybrid work model\b", re.IGNORECASE),
    re.compile(r"\brelocation is not provided\b", re.IGNORECASE),
    re.compile(r"\breside in\b", re.IGNORECASE),
    re.compile(r"\bwho we are\b", re.IGNORECASE),
    re.compile(r"\bthe company\b", re.IGNORECASE),
    re.compile(r"\bour benefits\b", re.IGNORECASE),
    re.compile(r"\bcommitment to diversity\b", re.IGNORECASE),
    re.compile(r"\bjoin our team\b", re.IGNORECASE),
    re.compile(r"\bthis role is ideal for\b", re.IGNORECASE),
    re.compile(r"\beager to learn\b", re.IGNORECASE),
)
ROLE_SIGNAL_NONTECHNICAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^we are seeking\b", re.IGNORECASE),
    re.compile(r"^we are looking for\b", re.IGNORECASE),
    re.compile(r"^looking for\b", re.IGNORECASE),
    re.compile(r"^seeking an? .+ to join our team", re.IGNORECASE),
    re.compile(
        r"^contribute to design of new functionality and expand existing functionality$",
        re.IGNORECASE,
    ),
    re.compile(r"^you will help build and drive solutions", re.IGNORECASE),
    re.compile(r"^communicat", re.IGNORECASE),
    re.compile(r"^manage (?:a number of )?projects?", re.IGNORECASE),
    re.compile(r"^learn and become proficient", re.IGNORECASE),
    re.compile(r"^effective communication", re.IGNORECASE),
    re.compile(r"^team player", re.IGNORECASE),
    re.compile(r"^well-rounded", re.IGNORECASE),
    re.compile(r"^strong analytical and problem-solving skills", re.IGNORECASE),
    re.compile(r"^thrives in a fast-paced", re.IGNORECASE),
    re.compile(r"^ability and desire", re.IGNORECASE),
    re.compile(r"^willing to work extended hours", re.IGNORECASE),
    re.compile(r"^passionate about building great software", re.IGNORECASE),
)
ROLE_SIGNAL_INELIGIBLE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bmedical, dental(?:,? & vision| and vision)\b", re.IGNORECASE),
    re.compile(r"\b(?:401\(k\)|paid time off|pto|life insurance|wellness|tuition reimbursement)\b", re.IGNORECASE),
    re.compile(r"\bgrow a career\b", re.IGNORECASE),
    re.compile(r"\bbuild a future\b", re.IGNORECASE),
    re.compile(r"\bcareer growth\b", re.IGNORECASE),
    re.compile(r"\bjoin our team\b", re.IGNORECASE),
    re.compile(r"\babout us\b", re.IGNORECASE),
    re.compile(r"\bwho we are\b", re.IGNORECASE),
    re.compile(r"\bour values\b", re.IGNORECASE),
    re.compile(r"\bour culture\b", re.IGNORECASE),
    re.compile(r"\bapply now\b", re.IGNORECASE),
    re.compile(r"\bwhy (?:work|join)\b", re.IGNORECASE),
    re.compile(r"\bbenefits to support you\b", re.IGNORECASE),
)
ROLE_SIGNAL_GENERIC_FOCUS_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bapplication delivery\b", re.IGNORECASE),
    re.compile(r"\bplatform enhancements?\b", re.IGNORECASE),
    re.compile(r"\bbackend services\b", re.IGNORECASE),
    re.compile(r"\bmodels?, simulations?,? and analytics\b", re.IGNORECASE),
)
ROLE_SIGNAL_TECHNICAL_PRIORITY_PATTERNS: tuple[tuple[re.Pattern[str], int], ...] = (
    (
        re.compile(
            r"\b(?:generative ai|machine learning|deep learning|large language models?|llm(?:ops)?|ai/ml|ai cognitive services?|ai copilots?|ai assistants?)\b",
            re.IGNORECASE,
        ),
        10,
    ),
    (re.compile(r"\b(?:rest apis?|microservices?)\b", re.IGNORECASE), 10),
    (re.compile(r"\b(?:full cycle delivery|requirements/design to release)\b", re.IGNORECASE), 11),
    (
        re.compile(
            r"\b(?:production-level models? and pipelines?|production-ready solutions?)\b",
            re.IGNORECASE,
        ),
        9,
    ),
    (re.compile(r"\b(?:high-throughput|enterprise-scale|payment systems?)\b", re.IGNORECASE), 9),
    (re.compile(r"\b(?:webapi|restful services?|swagger|postman)\b", re.IGNORECASE), 9),
    (re.compile(r"\b(?:web-based client-server|client-server applications?)\b", re.IGNORECASE), 8),
    (re.compile(r"\b(?:distributed|event-driven|backend)\b", re.IGNORECASE), 8),
    (
        re.compile(
            r"\b(?:data pipelines?|ml models?|ai models?|model inference|databricks|airflow|langchain|llamaindex|vector databases?|vector index)\b",
            re.IGNORECASE,
        ),
        8,
    ),
    (re.compile(r"\b(?:spring boot|jakarta ee)\b", re.IGNORECASE), 7),
    (re.compile(r"\b(?:robotic|robotics|ros|motion control|sensor integration)\b", re.IGNORECASE), 7),
    (re.compile(r"\b(?:\.net(?: framework| core)?|asp\.net|c#)\b", re.IGNORECASE), 6),
    (re.compile(r"\b(?:sql server|mongodb|postgresql|mysql|relational databases?)\b", re.IGNORECASE), 6),
    (re.compile(r"\b(?:aws|gcp|azure|cloud|ci/cd|jenkins|circleci|github actions)\b", re.IGNORECASE), 6),
    (re.compile(r"\b(?:docker|kubernetes)\b", re.IGNORECASE), 6),
    (re.compile(r"\b(?:concurrency|stream processing|relational databases?)\b", re.IGNORECASE), 5),
    (re.compile(r"\b(?:java(?:\s*17\+?)?|python|scala|golang|go(?!-)|c\+\+|c#)\b", re.IGNORECASE), 5),
    (re.compile(r"\b(?:object-oriented design|design patterns?)\b", re.IGNORECASE), 4),
    (re.compile(r"\b(?:security|real-time|scheduling|metadata|documents?|platform|infrastructure)\b", re.IGNORECASE), 4),
)
ROLE_SIGNAL_SOURCE_PRIORITY: dict[str, int] = {
    "role_intent": 1,
    "must_have": 4,
    "core_responsibility": 5,
    "nice_to_have": 2,
    "jd_fallback": 1,
}
ROLE_SIGNAL_LEADING_CASE_EXCEPTIONS: frozenset[str] = frozenset(
    {
        "java",
        "python",
        "scala",
        "golang",
        "go",
        "aws",
        "gcp",
        "azure",
        "spring",
        "jakarta",
        "kubernetes",
        "docker",
    }
)
ROLE_SIGNAL_TITLE_THEME_PATTERNS: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...] = (
    (
        re.compile(r"\b(?:cloud|platform|systems?)\b", re.IGNORECASE),
        ("cloud", "aws", "gcp", "azure", "pcf", "platform", "container", "infrastructure", "backend"),
    ),
    (
        re.compile(r"\bbackend\b", re.IGNORECASE),
        ("backend", "api", "apis", "microservice", "microservices", "distributed", "event-driven"),
    ),
    (
        re.compile(r"\b(?:data|analytics|spark)\b", re.IGNORECASE),
        ("spark", "data", "pipeline", "pipelines", "etl", "analytics", "distributed"),
    ),
    (
        re.compile(r"\b(?:ai|ml|machine learning|deep learning|perception)\b", re.IGNORECASE),
        ("ai", "machine learning", "deep learning", "llm", "perception", "edge", "model", "models"),
    ),
    (
        re.compile(r"\bsecurity\b", re.IGNORECASE),
        ("security", "secure", "identity"),
    ),
    (
        re.compile(r"\bfull stack\b", re.IGNORECASE),
        ("frontend", "backend", "api", "apis", "angular", "react", "javascript"),
    ),
    (
        re.compile(r"\brobotics?\b", re.IGNORECASE),
        ("robotic", "robotics", "ros", "motion", "sensor", "automation"),
    ),
)
ROLE_SIGNAL_FOCUS_ANCHOR_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(?:hybrid-cloud applications?|cloud and hybrid-cloud applications?)\b", re.IGNORECASE), "hybrid_cloud_apps"),
    (re.compile(r"\bdevsecops\b", re.IGNORECASE), "devsecops"),
    (re.compile(r"\b(?:web services? in the cloud|cloud web services?)\b", re.IGNORECASE), "cloud_web_services"),
    (re.compile(r"\bgraphql\b", re.IGNORECASE), "graphql_rest"),
    (re.compile(r"\b(?:rest(?:ful)? (?:apis?|services?)|swagger|postman)\b", re.IGNORECASE), "graphql_rest"),
    (re.compile(r"\bci/cd\b", re.IGNORECASE), "ci_cd"),
    (re.compile(r"\b(?:public cloud|cloud-native|cloud-ready|aws|gcp|azure|pcf)\b", re.IGNORECASE), "cloud"),
    (re.compile(r"\b(?:kubernetes|docker|container(?:s|ization)?|container orchestration|podman|cri-o)\b", re.IGNORECASE), "containers"),
    (re.compile(r"\b(?:backend|rest apis?|restful services?|backend apis?|microservices?|grpc|event-driven)\b", re.IGNORECASE), "backend"),
    (re.compile(r"\b(?:automation(?: tooling| tools?)?|automation workflows?|ci/cd|github actions|jenkins)\b", re.IGNORECASE), "automation"),
    (re.compile(r"\b(?:terraform|infrastructure provisioning)\b", re.IGNORECASE), "terraform"),
    (re.compile(r"\bapi gateway\b", re.IGNORECASE), "api_gateway"),
    (re.compile(r"\b(?:workload identity|iam|oauth|oidc)\b", re.IGNORECASE), "identity"),
    (re.compile(r"\b(?:spark|databricks|big data|data pipelines?|etl|stream processing)\b", re.IGNORECASE), "data"),
    (re.compile(r"\b(?:distributed systems?|distributed services?)\b", re.IGNORECASE), "distributed"),
    (re.compile(r"\b(?:ai|machine learning|deep learning|generative ai|ai/ml|llm|large language models?)\b", re.IGNORECASE), "ai_ml"),
    (re.compile(r"\bperception\b", re.IGNORECASE), "perception"),
    (re.compile(r"\bedge devices?\b", re.IGNORECASE), "edge"),
    (re.compile(r"\b(?:robotic|robotics|ros|motion control|sensor integration)\b", re.IGNORECASE), "robotics"),
    (re.compile(r"\b(?:security|secure infrastructure|cloud security|application security)\b", re.IGNORECASE), "security"),
    (re.compile(r"\b(?:scheduler|scheduling|real-time|control systems?)\b", re.IGNORECASE), "scheduling"),
    (re.compile(r"\b(?:java|scala|python|golang|go|spring(?: boot)?|kotlin|c\+\+|c#)\b", re.IGNORECASE), "languages"),
)
ROLE_SIGNAL_SUMMARY_GROUPS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bevent-driven\b.*\bmetadata\b", re.IGNORECASE), "event-driven metadata pipelines"),
    (re.compile(r"\bscheduling engines?\b.*\breal-time control systems?\b", re.IGNORECASE), "scheduling engines for real-time control systems"),
    (re.compile(r"\bproduction-level models? and pipelines?\b", re.IGNORECASE), "production-level AI/ML models and pipelines"),
    (re.compile(r"\b(?:hybrid-cloud applications?|cloud and hybrid-cloud applications?)\b", re.IGNORECASE), "hybrid-cloud application development"),
    (re.compile(r"\bdevsecops\b", re.IGNORECASE), "DevSecOps"),
    (re.compile(r"\b(?:web services? in the cloud|cloud web services?)\b", re.IGNORECASE), "cloud web services"),
    (
        re.compile(
            r"(?=.*\bgraphql\b)(?=.*\b(?:rest(?:ful)? (?:apis?|services?)|swagger|postman)\b)",
            re.IGNORECASE,
        ),
        "GraphQL and REST APIs",
    ),
    (
        re.compile(
            r"\brest(?:ful)? services?\b.*\bswagger\b.*\bpostman\b|\bpostman\b.*\bswagger\b.*\brest(?:ful)? services?\b",
            re.IGNORECASE,
        ),
        "RESTful services, Swagger, and Postman",
    ),
    (
        re.compile(
            r"\brest(?:ful)? apis?\b.*\bmicroservices?\b|\bmicroservices?\b.*\brest(?:ful)? apis?\b",
            re.IGNORECASE,
        ),
        "REST APIs or microservices",
    ),
    (re.compile(r"\bgraphql\b", re.IGNORECASE), "GraphQL APIs"),
    (re.compile(r"\b(?:rest(?:ful)? (?:apis?|services?))\b", re.IGNORECASE), "REST APIs"),
    (re.compile(r"\bci/cd\b", re.IGNORECASE), "CI/CD automation"),
    (re.compile(r"\b(?:terraform|infrastructure provisioning)\b", re.IGNORECASE), "Terraform-based infrastructure provisioning"),
    (re.compile(r"\bapi gateway\b", re.IGNORECASE), "API gateway build-out"),
    (re.compile(r"\b(?:workload identity|iam|oauth|oidc)\b", re.IGNORECASE), "workload identity automation"),
    (re.compile(r"\b(?:public cloud|cloud-native|cloud-ready|aws|gcp|azure|pcf)\b", re.IGNORECASE), "public cloud infrastructure"),
    (re.compile(r"\b(?:kubernetes|docker|container(?:s|ization)?|container orchestration|podman|cri-o)\b", re.IGNORECASE), "container platforms"),
    (re.compile(r"\b(?:backend automation|automation tooling|automation tools?|automation workflows?)\b", re.IGNORECASE), "backend automation tooling"),
    (re.compile(r"\b(?:backend|rest apis?|restful services?|backend apis?|microservices?)\b", re.IGNORECASE), "backend APIs and services"),
    (re.compile(r"\b(?:spark|databricks|big data|data pipelines?|etl)\b", re.IGNORECASE), "Spark-based big data engineering"),
    (re.compile(r"\b(?:distributed systems?|distributed services?)\b", re.IGNORECASE), "distributed systems"),
    (re.compile(r"\b(?:machine learning|deep learning)\b", re.IGNORECASE), "machine learning and deep learning"),
    (re.compile(r"\bperception\b", re.IGNORECASE), "perception software"),
    (re.compile(r"\bedge devices?\b", re.IGNORECASE), "edge devices"),
    (re.compile(r"\b(?:robotic|robotics|ros|motion control|sensor integration)\b", re.IGNORECASE), "robotic systems integration"),
    (re.compile(r"\b(?:scheduler|scheduling engines?|real-time|control systems?)\b", re.IGNORECASE), "real-time scheduling systems"),
    (re.compile(r"\benterprise security systems?\b", re.IGNORECASE), "enterprise security systems"),
    (re.compile(r"\b(?:security|secure infrastructure|cloud security|application security)\b", re.IGNORECASE), "secure infrastructure"),
    (re.compile(r"\b(?:intel federal|government)\b", re.IGNORECASE), "government-focused security work"),
)
ROLE_THEME_TITLE_RULES: tuple[dict[str, Any], ...] = (
    {
        "family": "ai_ml",
        "pattern": re.compile(r"\b(?:ai|ml|machine learning|deep learning|perception|generative)\b", re.IGNORECASE),
        "preferred_anchors": ("ai_ml", "perception", "edge", "data", "distributed"),
        "fallback_label": "AI/ML systems",
        "growth_area_ids": ("ai_ml_systems", "backend_distributed_systems", "platform_infrastructure"),
        "interest_area_ids": ("agentic_ai", "applied_ai", "ai_platform_infrastructure"),
    },
    {
        "family": "robotics",
        "pattern": re.compile(r"\b(?:robotics?|robotic|autonomy|embedded|perception)\b", re.IGNORECASE),
        "preferred_anchors": ("robotics", "perception", "edge", "ai_ml", "distributed"),
        "fallback_label": "robotics and edge systems",
        "growth_area_ids": ("robotics_edge_systems", "ai_ml_systems", "backend_distributed_systems"),
    },
    {
        "family": "security",
        "pattern": re.compile(r"\b(?:security|cyber|identity|secure)\b", re.IGNORECASE),
        "preferred_anchors": ("security", "identity", "cloud", "automation", "backend"),
        "fallback_label": "security and identity systems",
        "growth_area_ids": ("security_identity", "platform_infrastructure"),
    },
    {
        "family": "data",
        "pattern": re.compile(r"\b(?:data|analytics|spark|etl|pipeline)\b", re.IGNORECASE),
        "preferred_anchors": ("data", "distributed", "cloud", "automation", "backend"),
        "fallback_label": "data and analytics systems",
        "growth_area_ids": ("data_platforms", "backend_distributed_systems", "platform_infrastructure"),
    },
    {
        "family": "cloud_platform",
        "pattern": re.compile(r"\b(?:cloud|platform|devops|infrastructure|site reliability|sre)\b", re.IGNORECASE),
        "preferred_anchors": ("terraform", "identity", "devsecops", "cloud_web_services", "hybrid_cloud_apps", "cloud", "containers", "automation", "backend", "distributed", "graphql_rest", "ci_cd"),
        "fallback_label": "platform and infrastructure",
        "growth_area_ids": ("platform_infrastructure", "backend_distributed_systems"),
    },
    {
        "family": "backend",
        "pattern": re.compile(r"\b(?:backend|api|server|services?)\b", re.IGNORECASE),
        "preferred_anchors": ("backend", "graphql_rest", "distributed", "automation", "cloud", "data", "languages"),
        "fallback_label": "backend and distributed systems",
        "growth_area_ids": ("backend_distributed_systems", "platform_infrastructure"),
    },
    {
        "family": "full_stack",
        "pattern": re.compile(r"\bfull[ -]?stack\b", re.IGNORECASE),
        "preferred_anchors": ("backend", "graphql_rest", "cloud", "automation", "languages"),
        "fallback_label": "full-stack application systems",
        "growth_area_ids": ("backend_distributed_systems",),
    },
    {
        "family": "scheduling",
        "pattern": re.compile(r"\b(?:scheduler|scheduling|real-time|control systems?)\b", re.IGNORECASE),
        "preferred_anchors": ("scheduling", "distributed", "backend", "languages"),
        "fallback_label": "real-time systems",
        "growth_area_ids": ("systems_leadership",),
    },
)
ROLE_THEME_PART_PRIORITY: dict[str, int] = {
    "hybrid_cloud_apps": 12,
    "devsecops": 11,
    "cloud_web_services": 11,
    "graphql_rest": 10,
    "terraform": 12,
    "api_gateway": 11,
    "identity": 10,
    "ai_ml": 10,
    "perception": 10,
    "edge": 9,
    "robotics": 9,
    "data": 9,
    "distributed": 8,
    "containers": 8,
    "ci_cd": 8,
    "backend": 9,
    "automation": 7,
    "cloud": 6,
    "security": 6,
    "scheduling": 6,
    "languages": 4,
}
ROLE_THEME_PART_LABELS: dict[str, str] = {
    "event-driven metadata pipelines": "backend",
    "scheduling engines for real-time control systems": "scheduling",
    "production-level AI/ML models and pipelines": "ai_ml",
    "hybrid-cloud application development": "hybrid_cloud_apps",
    "DevSecOps": "devsecops",
    "cloud web services": "cloud_web_services",
    "GraphQL and REST APIs": "graphql_rest",
    "GraphQL APIs": "graphql_rest",
    "RESTful services, Swagger, and Postman": "graphql_rest",
    "REST APIs or microservices": "backend",
    "REST APIs": "graphql_rest",
    "CI/CD automation": "ci_cd",
    "Terraform-based infrastructure provisioning": "terraform",
    "API gateway build-out": "api_gateway",
    "workload identity automation": "identity",
    "public cloud infrastructure": "cloud",
    "container platforms": "containers",
    "backend automation tooling": "automation",
    "backend APIs and services": "backend",
    "Spark-based big data engineering": "data",
    "distributed systems": "distributed",
    "machine learning and deep learning": "ai_ml",
    "perception software": "perception",
    "edge devices": "edge",
    "robotic systems integration": "robotics",
    "real-time scheduling systems": "scheduling",
    "enterprise security systems": "security",
    "secure infrastructure": "security",
    "government-focused security work": "security",
}
ROLE_THEME_SENTENCE_LABELS: dict[str, str] = {
    "cloud_platform": "platform and infrastructure",
    "backend": "backend and distributed systems",
    "data": "data and analytics systems",
    "ai_ml": "AI/ML systems",
    "robotics": "robotics and edge systems",
    "security": "security and identity systems",
    "full_stack": "application platform work",
    "scheduling": "systems and leadership work",
}
ROLE_THEME_SPECIALIZED_DIRECT_ANCHORS: frozenset[str] = frozenset(
    {
        "ai_ml",
        "perception",
        "edge",
        "robotics",
        "security",
        "identity",
        "scheduling",
        "data",
    }
)
ROLE_THEME_DIRECT_CLAIM_RULES: dict[str, tuple[str, ...]] = {
    "ai_ml": ("ai_ml", "perception", "edge"),
    "robotics": ("robotics", "perception", "edge"),
    "security": ("security", "identity"),
    "data": ("data",),
    "cloud_platform": (
        "hybrid_cloud_apps",
        "devsecops",
        "cloud_web_services",
        "graphql_rest",
        "ci_cd",
        "terraform",
        "api_gateway",
        "identity",
        "cloud",
        "containers",
        "automation",
    ),
    "backend": ("backend", "graphql_rest", "distributed", "languages"),
    "full_stack": ("backend", "graphql_rest", "languages", "cloud", "automation"),
    "scheduling": ("scheduling",),
}
ROLE_THEME_TRANSFERABLE_ANCHORS: tuple[str, ...] = (
    "backend",
    "distributed",
    "cloud",
    "data",
    "automation",
    "containers",
    "languages",
    "graphql_rest",
)
ANCHOR_KEYWORD_HINTS: dict[str, tuple[str, ...]] = {
    "hybrid_cloud_apps": ("hybrid-cloud", "cloud applications", "application development", "cloud development"),
    "devsecops": ("devsecops", "secure delivery", "security standards"),
    "cloud_web_services": ("web services", "cloud web services"),
    "graphql_rest": ("graphql", "rest", "restful", "apis", "api", "swagger", "postman"),
    "ci_cd": ("ci/cd", "deployment", "release automation"),
    "terraform": ("terraform", "infrastructure provisioning"),
    "api_gateway": ("api gateway",),
    "identity": ("identity", "iam", "oauth", "oidc", "workload identity"),
    "cloud": ("cloud", "aws", "gcp", "azure", "pcf"),
    "containers": ("kubernetes", "docker", "containers"),
    "backend": ("backend", "microservices", "services", "event-driven", "grpc"),
    "automation": ("automation", "workflow", "jenkins", "github actions"),
    "data": ("spark", "etl", "data", "analytics", "databricks", "stream processing"),
    "distributed": ("distributed", "throughput", "reliability", "scale", "latency"),
    "ai_ml": ("ai", "machine learning", "deep learning", "generative ai", "llm", "model"),
    "perception": ("perception",),
    "edge": ("edge", "on-device", "embedded"),
    "robotics": ("robotic", "robotics", "ros", "motion", "sensor"),
    "security": ("security", "secure", "government"),
    "scheduling": ("scheduler", "scheduling", "real-time", "control"),
    "languages": ("java", "scala", "python", "golang", "kotlin", "c++", "c#"),
}
ROLE_THEME_OVERLAP_STOPWORDS: frozenset[str] = frozenset(
    {
        "build",
        "building",
        "design",
        "designing",
        "develop",
        "developing",
        "implement",
        "implementing",
        "support",
        "supporting",
        "systems",
        "system",
        "services",
        "service",
        "platform",
        "platforms",
        "software",
        "engineering",
        "engineer",
        "team",
        "teams",
        "solutions",
        "solution",
        "role",
        "work",
        "workloads",
        "production",
        "multiple",
        "global",
    }
)
ROLE_TARGETED_DRAFT_BLOCK_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bwork around identifies\b", re.IGNORECASE),
    re.compile(r"\brole's focus on seeking\b", re.IGNORECASE),
    re.compile(r"\brole's focus on basic understanding of\b", re.IGNORECASE),
    re.compile(r"\brole's focus on (?:contribute|communicat|manage|learn)\b", re.IGNORECASE),
    re.compile(r"\byour role as .+ seems close to\b", re.IGNORECASE),
    re.compile(r"\bteam behind this role\b", re.IGNORECASE),
    re.compile(r"\bwork behind this role\b", re.IGNORECASE),
    re.compile(r"\bstrong fit\b", re.IGNORECASE),
    re.compile(r"\bOne example of that overlap is\b", re.IGNORECASE),
    re.compile(r"\bI came across the\b", re.IGNORECASE),
    re.compile(r"\bThe emphasis on\b", re.IGNORECASE),
    re.compile(r"\bMS in Computer Science at ASU\b", re.IGNORECASE),
    re.compile(r"\bArizona State University\b", re.IGNORECASE),
    re.compile(r"\b(?:which is )?what prompted me to reach out\b", re.IGNORECASE),
)
ROLE_SIGNAL_VERB_PREFIXES = {
    "deliver": "delivering",
    "delivers": "delivering",
    "advise": "advising",
    "advises": "advising",
    "guide": "guiding",
    "guides": "guiding",
    "operate": "operating",
    "operates": "operating",
    "apply": "applying",
    "applies": "applying",
    "drive": "driving",
    "develop": "developing",
    "design": "designing",
    "implement": "implementing",
    "collaborate": "collaborating",
    "ensure": "ensuring",
    "review": "reviewing",
    "evaluate": "evaluating",
    "lead": "leading",
    "build": "building",
    "extract": "extracting",
    "enrich": "enriching",
    "process": "processing",
    "support": "supporting",
    "oversee": "overseeing",
    "manage": "managing",
}


@dataclass(frozen=True)
class SendSetContactPlan:
    slot_name: str
    selection_kind: str
    contact_id: str
    job_posting_contact_id: str
    recipient_type: str
    display_name: str
    has_usable_email: bool
    current_working_email: str | None
    readiness_state: str
    blocking_reason: str | None
    prior_outreach_count: int
    link_level_status: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "slot_name": self.slot_name,
            "selection_kind": self.selection_kind,
            "contact_id": self.contact_id,
            "job_posting_contact_id": self.job_posting_contact_id,
            "recipient_type": self.recipient_type,
            "display_name": self.display_name,
            "has_usable_email": self.has_usable_email,
            "current_working_email": self.current_working_email,
            "readiness_state": self.readiness_state,
            "blocking_reason": self.blocking_reason,
            "prior_outreach_count": self.prior_outreach_count,
            "link_level_status": self.link_level_status,
        }


@dataclass(frozen=True)
class RepeatOutreachReviewContact:
    contact_id: str
    job_posting_contact_id: str
    recipient_type: str
    display_name: str
    prior_outreach_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "contact_id": self.contact_id,
            "job_posting_contact_id": self.job_posting_contact_id,
            "recipient_type": self.recipient_type,
            "display_name": self.display_name,
            "prior_outreach_count": self.prior_outreach_count,
        }


@dataclass(frozen=True)
class RoleTargetedSendSetPlan:
    job_posting_id: str
    lead_id: str
    company_name: str
    role_title: str
    posting_status_after_evaluation: str
    ready_for_outreach: bool
    selected_contacts: tuple[SendSetContactPlan, ...]
    repeat_outreach_review_contacts: tuple[RepeatOutreachReviewContact, ...]
    max_send_set_size: int
    current_send_set_size: int
    posting_sent_today: int
    remaining_posting_daily_capacity: int
    global_gap_minutes: int
    earliest_allowed_send_at: str
    pacing_allowed_now: bool
    pacing_block_reason: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "posting_status_after_review": self.posting_status_after_evaluation,
            "ready_for_outreach": self.ready_for_outreach,
            "max_send_set_size": self.max_send_set_size,
            "current_send_set_size": self.current_send_set_size,
            "selected_slots": [contact.slot_name for contact in self.selected_contacts],
            "selected_contact_ids": [contact.contact_id for contact in self.selected_contacts],
            "selected_job_posting_contact_ids": [
                contact.job_posting_contact_id for contact in self.selected_contacts
            ],
            "selected_contacts": [contact.as_dict() for contact in self.selected_contacts],
            "blocking_contact_ids": [
                contact.contact_id
                for contact in self.selected_contacts
                if contact.readiness_state != _CANDIDATE_STATE_READY
            ],
            "repeat_outreach_review_contact_ids": [
                contact.contact_id for contact in self.repeat_outreach_review_contacts
            ],
            "repeat_outreach_review_contacts": [
                contact.as_dict() for contact in self.repeat_outreach_review_contacts
            ],
            "posting_pacing": {
                "daily_send_cap": AUTOMATIC_POSTING_DAILY_SEND_CAP,
                "posting_sent_today": self.posting_sent_today,
                "remaining_posting_daily_capacity": self.remaining_posting_daily_capacity,
                "global_gap_minutes": self.global_gap_minutes,
                "earliest_allowed_send_at": self.earliest_allowed_send_at,
                "pacing_allowed_now": self.pacing_allowed_now,
                "pacing_block_reason": self.pacing_block_reason,
            },
        }


class OutreachDraftingError(RuntimeError):
    pass


class OutreachSendingError(RuntimeError):
    pass


@dataclass(frozen=True)
class SenderIdentity:
    name: str
    email: str | None
    phone: str | None
    linkedin_url: str | None
    github_url: str | None
    education_summary: str | None


@dataclass(frozen=True)
class SenderGrowthArea:
    area_id: str
    label: str
    keywords: tuple[str, ...]
    growth_overlap_sentence: str
    background_overlap_sentence: str
    combined_overlap_sentence: str


@dataclass(frozen=True)
class SenderInterestArea:
    area_id: str
    label: str
    keywords: tuple[str, ...]
    interest_overlap_sentence: str
    snippet_interest_sentence: str


@dataclass(frozen=True)
class OpenerRubric:
    version: int
    allowed_claim_modes: tuple[str, ...]
    blocked_focus_phrases: tuple[str, ...]
    blocked_opener_phrases: tuple[str, ...]
    minimum_specific_anchor_count: int
    require_title_alignment: bool


@dataclass(frozen=True)
class RoleThemeSelection:
    focus_phrase: str
    role_family: str | None
    anchor_labels: tuple[str, ...]
    source_signals: tuple[str, ...]
    background_overlap: bool
    direct_background_overlap: bool
    adjacent_background_overlap: bool
    growth_overlap: bool
    growth_area_label: str | None
    interest_overlap: bool
    interest_area_label: str | None
    interest_overlap_sentence: str | None
    interest_snippet_sentence: str | None
    overlap_sentence: str


@dataclass(frozen=True)
class RoleTargetedOpenerDecision:
    role_title: str
    company_name: str
    role_theme: str
    technical_focus: str
    claim_mode: str
    overlap_sentence: str
    source_signals: tuple[str, ...]
    growth_area_label: str | None
    interest_area_label: str | None
    rationale: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "role_title": self.role_title,
            "company_name": self.company_name,
            "role_theme": self.role_theme,
            "technical_focus": self.technical_focus,
            "claim_mode": self.claim_mode,
            "overlap_sentence": self.overlap_sentence,
            "source_signals": list(self.source_signals),
            "growth_area_label": self.growth_area_label,
            "interest_area_label": self.interest_area_label,
            "rationale": list(self.rationale),
        }


@dataclass(frozen=True)
class _RoleThemeCandidate:
    raw_signal: str
    source_kind: str
    normalized_focus: str
    anchor_labels: tuple[str, ...]
    focus_parts: tuple[str, ...]
    score: int
    title_score: int
    technical_score: int
    specificity_score: int
    background_score: int
    growth_score: int
    interest_score: int
    role_family: str | None
    growth_area_label: str | None


@dataclass(frozen=True)
class RenderedDraft:
    subject: str
    body_markdown: str
    body_html: str | None
    include_forwardable_snippet: bool
    opener_decision: RoleTargetedOpenerDecision | None = None


@dataclass(frozen=True)
class RoleTargetedDraftContext:
    job_posting_id: str
    job_posting_contact_id: str
    lead_id: str
    company_name: str
    role_title: str
    recipient_type: str
    contact_id: str
    display_name: str
    recipient_email: str
    position_title: str | None
    discovery_summary: str | None
    recipient_profile: Mapping[str, Any] | None
    jd_text: str
    role_intent_summary: str | None
    proof_point: str | None
    fit_summary: str | None
    work_area: str | None
    theme_selection: RoleThemeSelection
    opener_rubric: OpenerRubric
    opener_decision: RoleTargetedOpenerDecision
    sender: SenderIdentity
    tailored_resume_path: str


@dataclass(frozen=True)
class RoleTargetedCompositionPlan:
    opener_paragraph: str
    background_paragraph: str
    copilot_paragraphs: tuple[str, str, str]
    ask_paragraph: str
    snippet_text: str


@dataclass(frozen=True)
class RoleTargetedOpenerInputs:
    company_name: str
    role_title: str
    technical_focus: str
    overlap_sentence: str


@dataclass(frozen=True)
class GeneralLearningDraftContext:
    contact_id: str
    company_name: str
    display_name: str
    recipient_email: str
    recipient_type: str
    position_title: str | None
    recipient_profile: Mapping[str, Any] | None
    sender: SenderIdentity


@dataclass(frozen=True)
class DraftFailure:
    outreach_message_id: str
    contact_id: str
    job_posting_contact_id: str | None
    reason_code: str
    message: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "outreach_message_id": self.outreach_message_id,
            "contact_id": self.contact_id,
            "job_posting_contact_id": self.job_posting_contact_id,
            "reason_code": self.reason_code,
            "message": self.message,
        }


@dataclass(frozen=True)
class DraftedOutreachMessage:
    outreach_message_id: str
    contact_id: str
    job_posting_id: str | None
    job_posting_contact_id: str | None
    outreach_mode: str
    recipient_email: str
    message_status: str
    subject: str
    body_text: str
    body_html: str | None
    body_text_artifact_path: str
    send_result_artifact_path: str
    body_html_artifact_path: str | None
    opener_decision_artifact_path: str | None
    resume_attachment_path: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "outreach_message_id": self.outreach_message_id,
            "contact_id": self.contact_id,
            "job_posting_id": self.job_posting_id,
            "job_posting_contact_id": self.job_posting_contact_id,
            "outreach_mode": self.outreach_mode,
            "recipient_email": self.recipient_email,
            "message_status": self.message_status,
            "subject": self.subject,
            "body_text_artifact_path": self.body_text_artifact_path,
            "send_result_artifact_path": self.send_result_artifact_path,
            "body_html_artifact_path": self.body_html_artifact_path,
            "opener_decision_artifact_path": self.opener_decision_artifact_path,
            "resume_attachment_path": self.resume_attachment_path,
        }


@dataclass(frozen=True)
class RoleTargetedDraftBatchResult:
    job_posting_id: str
    selected_contact_ids: tuple[str, ...]
    drafted_messages: tuple[DraftedOutreachMessage, ...]
    failed_contacts: tuple[DraftFailure, ...]
    posting_status_after_drafting: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "job_posting_id": self.job_posting_id,
            "selected_contact_ids": list(self.selected_contact_ids),
            "drafted_messages": [message.as_dict() for message in self.drafted_messages],
            "failed_contacts": [failure.as_dict() for failure in self.failed_contacts],
            "posting_status_after_drafting": self.posting_status_after_drafting,
        }


@dataclass(frozen=True)
class GeneralLearningDraftResult:
    drafted_message: DraftedOutreachMessage

    def as_dict(self) -> dict[str, Any]:
        return {"drafted_message": self.drafted_message.as_dict()}


@dataclass(frozen=True)
class OutboundOutreachMessage:
    outreach_message_id: str
    contact_id: str
    job_posting_id: str | None
    job_posting_contact_id: str | None
    outreach_mode: str
    recipient_email: str
    subject: str
    body_text: str
    body_html: str | None
    resume_attachment_path: str | None


@dataclass(frozen=True)
class SendAttemptOutcome:
    outcome: str
    thread_id: str | None = None
    delivery_tracking_id: str | None = None
    sent_at: str | None = None
    reason_code: str | None = None
    message: str | None = None


class OutreachMessageSender(Protocol):
    def send(self, message: OutboundOutreachMessage) -> SendAttemptOutcome:
        raise NotImplementedError


class GmailApiOutreachSender:
    def __init__(
        self,
        paths: ProjectPaths,
        *,
        service_factory: object | None = None,
    ) -> None:
        self._paths = paths
        self._service_factory = service_factory

    def send(self, message: OutboundOutreachMessage) -> SendAttemptOutcome:
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
                outcome=SEND_OUTCOME_FAILED,
                reason_code="missing_resume_attachment",
                message=str(exc),
            )
        except Exception as exc:
            return SendAttemptOutcome(
                outcome=SEND_OUTCOME_FAILED,
                reason_code="gmail_send_failed",
                message=str(exc),
            )

        delivery_tracking_id = _normalize_optional_text(response.get("id"))
        if delivery_tracking_id is None:
            return SendAttemptOutcome(
                outcome=SEND_OUTCOME_AMBIGUOUS,
                reason_code="gmail_missing_message_id",
                message="Gmail send succeeded without returning a message id.",
            )
        sent_at = _gmail_sent_at_from_response(response)
        return SendAttemptOutcome(
            outcome=SEND_OUTCOME_SENT,
            thread_id=_normalize_optional_text(response.get("threadId")),
            delivery_tracking_id=delivery_tracking_id,
            sent_at=sent_at,
        )

    def _build_service(self) -> Any:
        if self._service_factory is not None:
            return self._service_factory()
        from .gmail_alerts import _build_gmail_service

        return _build_gmail_service(self._paths)

    def _build_mime_message(self, message: OutboundOutreachMessage) -> EmailMessage:
        mime_message = EmailMessage()
        mime_message["To"] = message.recipient_email
        mime_message["Subject"] = message.subject
        mime_message.set_content(message.body_text)
        if message.body_html:
            mime_message.add_alternative(message.body_html, subtype="html")
        if message.resume_attachment_path:
            attachment_path = Path(message.resume_attachment_path)
            attachment_bytes = attachment_path.read_bytes()
            mime_message.add_attachment(
                attachment_bytes,
                maintype="application",
                subtype="pdf",
                filename=attachment_path.name,
            )
        return mime_message


def _gmail_sent_at_from_response(response: Mapping[str, Any]) -> str:
    internal_date = _normalize_optional_text(response.get("internalDate"))
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
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class SentOutreachMessage:
    outreach_message_id: str
    contact_id: str
    job_posting_contact_id: str
    recipient_email: str
    sent_at: str
    thread_id: str | None
    delivery_tracking_id: str | None
    send_result_artifact_path: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "outreach_message_id": self.outreach_message_id,
            "contact_id": self.contact_id,
            "job_posting_contact_id": self.job_posting_contact_id,
            "recipient_email": self.recipient_email,
            "sent_at": self.sent_at,
            "thread_id": self.thread_id,
            "delivery_tracking_id": self.delivery_tracking_id,
            "send_result_artifact_path": self.send_result_artifact_path,
        }


@dataclass(frozen=True)
class SendExecutionIssue:
    outreach_message_id: str
    contact_id: str
    job_posting_contact_id: str
    reason_code: str
    message: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "outreach_message_id": self.outreach_message_id,
            "contact_id": self.contact_id,
            "job_posting_contact_id": self.job_posting_contact_id,
            "reason_code": self.reason_code,
            "message": self.message,
        }


@dataclass(frozen=True)
class DelayedOutreachMessage:
    outreach_message_id: str
    contact_id: str
    job_posting_contact_id: str
    earliest_allowed_send_at: str
    pacing_block_reason: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "outreach_message_id": self.outreach_message_id,
            "contact_id": self.contact_id,
            "job_posting_contact_id": self.job_posting_contact_id,
            "earliest_allowed_send_at": self.earliest_allowed_send_at,
            "pacing_block_reason": self.pacing_block_reason,
        }


@dataclass(frozen=True)
class RetryableBlockedSendState:
    is_retryable: bool
    retry_allowed_now: bool
    retry_exhausted: bool
    attempt_count: int
    automatic_retry_count: int
    earliest_retry_at: str | None
    reason_code: str | None
    message: str | None


@dataclass(frozen=True)
class RoleTargetedSendExecutionResult:
    job_posting_id: str
    selected_contact_ids: tuple[str, ...]
    sent_messages: tuple[SentOutreachMessage, ...]
    blocked_messages: tuple[SendExecutionIssue, ...]
    failed_messages: tuple[SendExecutionIssue, ...]
    delayed_messages: tuple[DelayedOutreachMessage, ...]
    posting_status_after_execution: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "job_posting_id": self.job_posting_id,
            "selected_contact_ids": list(self.selected_contact_ids),
            "sent_messages": [message.as_dict() for message in self.sent_messages],
            "blocked_messages": [issue.as_dict() for issue in self.blocked_messages],
            "failed_messages": [issue.as_dict() for issue in self.failed_messages],
            "delayed_messages": [message.as_dict() for message in self.delayed_messages],
            "posting_status_after_execution": self.posting_status_after_execution,
        }


@dataclass(frozen=True)
class GeneralLearningSendExecutionResult:
    contact_id: str
    outreach_message_id: str
    drafted_message: DraftedOutreachMessage | None
    message_status_after_execution: str
    send_result_artifact_path: str
    sent_at: str | None
    thread_id: str | None
    delivery_tracking_id: str | None
    reason_code: str | None
    message: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "contact_id": self.contact_id,
            "outreach_message_id": self.outreach_message_id,
            "drafted_message": (
                None if self.drafted_message is None else self.drafted_message.as_dict()
            ),
            "message_status_after_execution": self.message_status_after_execution,
            "send_result_artifact_path": self.send_result_artifact_path,
            "sent_at": self.sent_at,
            "thread_id": self.thread_id,
            "delivery_tracking_id": self.delivery_tracking_id,
            "reason_code": self.reason_code,
            "message": self.message,
        }


class OutreachDraftRenderer:
    def render_role_targeted(self, context: RoleTargetedDraftContext) -> RenderedDraft:
        raise NotImplementedError

    def render_general_learning(self, context: GeneralLearningDraftContext) -> RenderedDraft:
        raise NotImplementedError


@dataclass(frozen=True)
class _CandidateRow:
    contact_id: str
    job_posting_contact_id: str
    recipient_type: str
    display_name: str
    current_working_email: str | None
    contact_status: str
    link_level_status: str
    prior_outreach_count: int
    prior_same_company_outreach_count: int
    link_created_at: str

    @property
    def has_usable_email(self) -> bool:
        return _is_usable_email(self.current_working_email)

    @property
    def selection_state(self) -> str:
        if self.prior_same_company_outreach_count > 0:
            return _CANDIDATE_STATE_SAME_COMPANY_SENT
        if self.prior_outreach_count > 0:
            return _CANDIDATE_STATE_REPEAT_REVIEW
        if self.link_level_status in {
            POSTING_CONTACT_STATUS_OUTREACH_IN_PROGRESS,
            POSTING_CONTACT_STATUS_OUTREACH_DONE,
            POSTING_CONTACT_STATUS_EXHAUSTED,
        }:
            return _CANDIDATE_STATE_UNAVAILABLE
        if self.contact_status == CONTACT_STATUS_EXHAUSTED:
            return _CANDIDATE_STATE_UNAVAILABLE
        if self.link_level_status not in {
            POSTING_CONTACT_STATUS_IDENTIFIED,
            POSTING_CONTACT_STATUS_SHORTLISTED,
        }:
            return _CANDIDATE_STATE_UNAVAILABLE
        if self.has_usable_email:
            return _CANDIDATE_STATE_READY
        return _CANDIDATE_STATE_NEEDS_EMAIL


def evaluate_role_targeted_send_set(
    connection: sqlite3.Connection,
    *,
    job_posting_id: str,
    current_time: str,
    local_timezone: tzinfo | str | None = None,
) -> RoleTargetedSendSetPlan:
    ensure_missing_posting_company_keys(connection, current_time=current_time)
    posting_row = _load_posting_row(connection, job_posting_id=job_posting_id)
    candidates = _load_candidate_rows(
        connection,
        job_posting_id=job_posting_id,
        posting_company_key=posting_company_key_from_row(posting_row),
    )
    selected_candidates = _select_send_set_candidates(candidates)
    selected_contacts = tuple(
        SendSetContactPlan(
            slot_name=slot_name,
            selection_kind=selection_kind,
            contact_id=candidate.contact_id,
            job_posting_contact_id=candidate.job_posting_contact_id,
            recipient_type=candidate.recipient_type,
            display_name=candidate.display_name,
            has_usable_email=candidate.has_usable_email,
            current_working_email=candidate.current_working_email,
            readiness_state=candidate.selection_state,
            blocking_reason=(
                None
                if candidate.selection_state == _CANDIDATE_STATE_READY
                else "waiting_for_usable_email"
            ),
            prior_outreach_count=candidate.prior_outreach_count,
            link_level_status=candidate.link_level_status,
        )
        for slot_name, selection_kind, candidate in selected_candidates
    )
    same_company_repeat_candidates = [
        candidate for candidate in candidates if candidate.selection_state == _CANDIDATE_STATE_SAME_COMPANY_SENT
    ]
    repeat_review_contacts = tuple(
        RepeatOutreachReviewContact(
            contact_id=candidate.contact_id,
            job_posting_contact_id=candidate.job_posting_contact_id,
            recipient_type=candidate.recipient_type,
            display_name=candidate.display_name,
            prior_outreach_count=candidate.prior_outreach_count,
        )
        for candidate in candidates
        if candidate.selection_state == _CANDIDATE_STATE_REPEAT_REVIEW
    )
    if not selected_contacts and same_company_repeat_candidates:
        repeat_review_contacts = repeat_review_contacts + tuple(
            RepeatOutreachReviewContact(
                contact_id=candidate.contact_id,
                job_posting_contact_id=candidate.job_posting_contact_id,
                recipient_type=candidate.recipient_type,
                display_name=candidate.display_name,
                prior_outreach_count=candidate.prior_outreach_count,
            )
            for candidate in same_company_repeat_candidates
        )
    ready_for_outreach = any(
        contact.readiness_state == _CANDIDATE_STATE_READY for contact in selected_contacts
    )

    current_dt = _parse_iso_datetime(current_time)
    resolved_timezone = _resolve_local_timezone(current_dt, local_timezone)
    posting_sent_today = _count_posting_sends_today(
        connection,
        job_posting_id=str(posting_row["job_posting_id"]),
        current_dt=current_dt,
        local_timezone=resolved_timezone,
    )
    remaining_posting_daily_capacity = max(
        0,
        AUTOMATIC_POSTING_DAILY_SEND_CAP - posting_sent_today,
    )
    global_gap_minutes = _determine_global_gap_minutes(
        job_posting_id=job_posting_id,
        selected_contact_ids=[contact.contact_id for contact in selected_contacts],
        current_dt=current_dt,
        local_timezone=resolved_timezone,
    )
    pacing = _build_pacing_plan(
        connection,
        current_dt=current_dt,
        local_timezone=resolved_timezone,
        job_posting_id=str(posting_row["job_posting_id"]),
        posting_sent_today=posting_sent_today,
        remaining_posting_daily_capacity=remaining_posting_daily_capacity,
        global_gap_minutes=global_gap_minutes,
    )

    return RoleTargetedSendSetPlan(
        job_posting_id=str(posting_row["job_posting_id"]),
        lead_id=str(posting_row["lead_id"]),
        company_name=str(posting_row["company_name"]),
        role_title=str(posting_row["role_title"]),
        posting_status_after_evaluation=(
            JOB_POSTING_STATUS_READY_FOR_OUTREACH
            if ready_for_outreach
            else JOB_POSTING_STATUS_REQUIRES_CONTACTS
        ),
        ready_for_outreach=ready_for_outreach,
        selected_contacts=selected_contacts,
        repeat_outreach_review_contacts=repeat_review_contacts,
        max_send_set_size=AUTOMATIC_SEND_SET_LIMIT,
        current_send_set_size=len(selected_contacts),
        posting_sent_today=posting_sent_today,
        remaining_posting_daily_capacity=remaining_posting_daily_capacity,
        global_gap_minutes=global_gap_minutes,
        earliest_allowed_send_at=pacing["earliest_allowed_send_at"],
        pacing_allowed_now=pacing["pacing_allowed_now"],
        pacing_block_reason=pacing["pacing_block_reason"],
    )


def is_role_targeted_sending_actionable_now(
    connection: sqlite3.Connection,
    *,
    project_root: Path | str,
    job_posting_id: str,
    current_time: str,
    local_timezone: tzinfo | str | None = None,
) -> bool:
    paths = ProjectPaths.from_root(project_root)
    posting_row = _load_role_targeted_send_posting_row(connection, job_posting_id=job_posting_id)
    active_wave = _load_active_role_targeted_wave(connection, job_posting_id=job_posting_id)
    next_message, retry_state = _find_next_send_frontier_message(
        connection,
        paths,
        posting_row=posting_row,
        active_wave=active_wave,
        current_time=current_time,
    )
    if next_message is not None:
        if retry_state is not None:
            if not retry_state.retry_allowed_now:
                return False
        current_dt = _parse_iso_datetime(current_time)
        resolved_timezone = _resolve_local_timezone(current_dt, local_timezone)
        global_gap_minutes = _determine_global_gap_minutes(
            job_posting_id=job_posting_id,
            selected_contact_ids=[message.contact_id for message in active_wave],
            current_dt=current_dt,
            local_timezone=resolved_timezone,
        )
        pacing = _build_role_targeted_send_pacing_plan(
            connection,
            posting_row=posting_row,
            current_dt=current_dt,
            local_timezone=resolved_timezone,
            global_gap_minutes=global_gap_minutes,
        )
        return bool(pacing["pacing_allowed_now"])

    if posting_row["posting_status"] != JOB_POSTING_STATUS_READY_FOR_OUTREACH:
        return False
    send_set_plan = evaluate_role_targeted_send_set(
        connection,
        job_posting_id=job_posting_id,
        current_time=current_time,
        local_timezone=local_timezone,
    )
    return bool(send_set_plan.selected_contacts) and send_set_plan.remaining_posting_daily_capacity > 0


def _load_posting_row(
    connection: sqlite3.Connection,
    *,
    job_posting_id: str,
) -> sqlite3.Row:
    posting_row = connection.execute(
        """
        SELECT job_posting_id, lead_id, canonical_company_key, company_name, role_title
        FROM job_postings
        WHERE job_posting_id = ?
        """,
        (job_posting_id,),
    ).fetchone()
    if posting_row is None:
        raise ValueError(f"Job posting `{job_posting_id}` was not found.")
    return posting_row


def _load_candidate_rows(
    connection: sqlite3.Connection,
    *,
    job_posting_id: str,
    posting_company_key: str,
) -> list[_CandidateRow]:
    rows = connection.execute(
        """
        WITH outreach_history AS (
          SELECT om.contact_id,
                 COUNT(*) AS prior_outreach_count,
                 SUM(
                   CASE
                     WHEN om.job_posting_id <> ?
                      AND jp.canonical_company_key = ?
                     THEN 1
                     ELSE 0
                   END
                 ) AS prior_same_company_outreach_count
          FROM outreach_messages om
          JOIN job_postings jp
            ON jp.job_posting_id = om.job_posting_id
          WHERE om.sent_at IS NOT NULL
             OR om.message_status = ?
          GROUP BY om.contact_id
        )
        SELECT jpc.job_posting_contact_id, jpc.contact_id, jpc.recipient_type, jpc.link_level_status,
               jpc.created_at AS link_created_at, c.display_name, c.current_working_email,
               c.contact_status, COALESCE(oh.prior_outreach_count, 0) AS prior_outreach_count,
               COALESCE(oh.prior_same_company_outreach_count, 0) AS prior_same_company_outreach_count
        FROM job_posting_contacts jpc
        JOIN contacts c
          ON c.contact_id = jpc.contact_id
        LEFT JOIN outreach_history oh
          ON oh.contact_id = jpc.contact_id
        WHERE jpc.job_posting_id = ?
        ORDER BY jpc.created_at ASC, jpc.job_posting_contact_id ASC
        """,
        (job_posting_id, posting_company_key, MESSAGE_STATUS_SENT, job_posting_id),
    ).fetchall()
    return [
        _CandidateRow(
            contact_id=str(row["contact_id"]),
            job_posting_contact_id=str(row["job_posting_contact_id"]),
            recipient_type=str(row["recipient_type"]).strip(),
            display_name=str(row["display_name"]).strip(),
            current_working_email=_normalize_optional_text(row["current_working_email"]),
            contact_status=str(row["contact_status"]).strip(),
            link_level_status=str(row["link_level_status"]).strip(),
            prior_outreach_count=int(row["prior_outreach_count"] or 0),
            prior_same_company_outreach_count=int(row["prior_same_company_outreach_count"] or 0),
            link_created_at=str(row["link_created_at"]).strip(),
        )
        for row in rows
        if str(row["recipient_type"]).strip()
    ]


def _load_role_targeted_draftable_contacts(
    connection: sqlite3.Connection,
    *,
    job_posting_id: str,
) -> tuple[_CandidateRow, ...]:
    draftable: list[_CandidateRow] = []
    posting_row = _load_posting_row(connection, job_posting_id=job_posting_id)
    for candidate in _load_candidate_rows(
        connection,
        job_posting_id=job_posting_id,
        posting_company_key=posting_company_key_from_row(posting_row),
    ):
        if candidate.selection_state != _CANDIDATE_STATE_READY:
            continue
        existing_message_count = int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM outreach_messages
                WHERE job_posting_id = ?
                  AND contact_id = ?
                """,
                (job_posting_id, candidate.contact_id),
            ).fetchone()[0]
            or 0
        )
        if existing_message_count > 0:
            continue
        draftable.append(candidate)
    return tuple(draftable)


def _select_send_set_candidates(
    candidates: Sequence[_CandidateRow],
) -> list[tuple[str, str, _CandidateRow]]:
    selected: list[tuple[str, str, _CandidateRow]] = []
    selected_contact_ids: set[str] = set()
    filled_primary_slots: set[str] = set()

    def append_primary_candidates(
        *,
        allowed_selection_states: frozenset[str],
        selection_kind: str,
    ) -> None:
        for slot_name, recipient_types in SEND_SET_PRIMARY_SLOTS:
            if len(selected) >= AUTOMATIC_SEND_SET_LIMIT:
                return
            if slot_name in filled_primary_slots:
                continue
            candidate = _pick_best_candidate(
                candidates,
                allowed_recipient_types=recipient_types,
                selected_contact_ids=selected_contact_ids,
                allowed_selection_states=allowed_selection_states,
            )
            if candidate is None:
                continue
            selected.append((slot_name, selection_kind, candidate))
            selected_contact_ids.add(candidate.contact_id)
            filled_primary_slots.add(slot_name)

    def append_fallback_candidates(
        *,
        allowed_selection_states: frozenset[str],
        selection_kind: str,
    ) -> None:
        fallback_candidates = sorted(
            (
                candidate
                for candidate in candidates
                if candidate.contact_id not in selected_contact_ids
                and candidate.selection_state in allowed_selection_states
            ),
            key=_fallback_sort_key,
        )
        for candidate in fallback_candidates:
            if len(selected) >= AUTOMATIC_SEND_SET_LIMIT:
                return
            selected.append((f"fallback_{len(selected) + 1}", selection_kind, candidate))
            selected_contact_ids.add(candidate.contact_id)

    append_primary_candidates(
        allowed_selection_states=frozenset({_CANDIDATE_STATE_READY}),
        selection_kind="preferred",
    )
    append_fallback_candidates(
        allowed_selection_states=frozenset({_CANDIDATE_STATE_READY}),
        selection_kind="fallback",
    )
    append_primary_candidates(
        allowed_selection_states=frozenset({_CANDIDATE_STATE_NEEDS_EMAIL}),
        selection_kind="preferred",
    )
    append_fallback_candidates(
        allowed_selection_states=frozenset({_CANDIDATE_STATE_NEEDS_EMAIL}),
        selection_kind="fallback",
    )
    return selected[:AUTOMATIC_SEND_SET_LIMIT]


def _pick_best_candidate(
    candidates: Sequence[_CandidateRow],
    *,
    allowed_recipient_types: Sequence[str],
    selected_contact_ids: set[str],
    allowed_selection_states: frozenset[str] = frozenset(
        {_CANDIDATE_STATE_READY, _CANDIDATE_STATE_NEEDS_EMAIL}
    ),
) -> _CandidateRow | None:
    eligible_candidates = [
        candidate
        for candidate in candidates
        if candidate.contact_id not in selected_contact_ids
        and candidate.recipient_type in allowed_recipient_types
        and candidate.selection_state in allowed_selection_states
    ]
    if not eligible_candidates:
        return None
    return min(eligible_candidates, key=_preferred_sort_key)


def _preferred_sort_key(candidate: _CandidateRow) -> tuple[int, int, str, str]:
    return (
        _selection_state_rank(candidate.selection_state),
        0 if candidate.link_level_status == POSTING_CONTACT_STATUS_SHORTLISTED else 1,
        candidate.link_created_at,
        candidate.contact_id,
    )


def _fallback_sort_key(candidate: _CandidateRow) -> tuple[int, int, int, str, str]:
    return (
        _selection_state_rank(candidate.selection_state),
        _fallback_type_rank(candidate.recipient_type),
        0 if candidate.link_level_status == POSTING_CONTACT_STATUS_SHORTLISTED else 1,
        candidate.link_created_at,
        candidate.contact_id,
    )


def _selection_state_rank(selection_state: str) -> int:
    if selection_state == _CANDIDATE_STATE_READY:
        return 0
    if selection_state == _CANDIDATE_STATE_NEEDS_EMAIL:
        return 1
    if selection_state == _CANDIDATE_STATE_REPEAT_REVIEW:
        return 2
    if selection_state == _CANDIDATE_STATE_SAME_COMPANY_SENT:
        return 3
    return 3


def _fallback_type_rank(recipient_type: str) -> int:
    try:
        return SEND_SET_FALLBACK_TYPE_ORDER.index(recipient_type)
    except ValueError:
        return len(SEND_SET_FALLBACK_TYPE_ORDER)


def _count_posting_sends_today(
    connection: sqlite3.Connection,
    *,
    job_posting_id: str,
    current_dt: datetime,
    local_timezone: tzinfo,
) -> int:
    rows = connection.execute(
        """
        SELECT om.sent_at
        FROM outreach_messages om
        WHERE om.sent_at IS NOT NULL
          AND TRIM(om.sent_at) <> ''
          AND om.job_posting_id = ?
        """
        ,
        (job_posting_id,),
    ).fetchall()
    current_local_day = current_dt.astimezone(local_timezone).date()
    send_count = 0
    for row in rows:
        sent_at = _normalize_optional_text(row["sent_at"])
        if sent_at is None:
            continue
        sent_at_local = _parse_iso_datetime(sent_at).astimezone(local_timezone)
        if sent_at_local.date() == current_local_day:
            send_count += 1
    return send_count


def _determine_global_gap_minutes(
    *,
    job_posting_id: str,
    selected_contact_ids: Sequence[str],
    current_dt: datetime,
    local_timezone: tzinfo,
) -> int:
    seed = "|".join(
        [
            job_posting_id,
            current_dt.astimezone(local_timezone).date().isoformat(),
            ",".join(sorted(selected_contact_ids)),
        ]
    )
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return MIN_INTER_SEND_GAP_MINUTES + (digest[0] % (MAX_INTER_SEND_GAP_MINUTES - MIN_INTER_SEND_GAP_MINUTES + 1))


def _build_pacing_plan(
    connection: sqlite3.Connection,
    *,
    current_dt: datetime,
    local_timezone: tzinfo,
    job_posting_id: str,
    posting_sent_today: int,
    remaining_posting_daily_capacity: int,
    global_gap_minutes: int,
) -> dict[str, Any]:
    constraint_times = [current_dt]
    pacing_block_reason: str | None = None

    if remaining_posting_daily_capacity <= 0 or posting_sent_today >= AUTOMATIC_POSTING_DAILY_SEND_CAP:
        next_day = current_dt.astimezone(local_timezone).date() + timedelta(days=1)
        posting_window_start = datetime.combine(next_day, time.min, tzinfo=local_timezone).astimezone(UTC)
        constraint_times.append(posting_window_start)
        pacing_block_reason = "posting_daily_cap"

    latest_sent_at = _load_latest_sent_at(connection)
    if latest_sent_at is not None:
        gap_due_at = latest_sent_at + timedelta(minutes=global_gap_minutes)
        constraint_times.append(gap_due_at)
        if gap_due_at > current_dt and pacing_block_reason is None:
            pacing_block_reason = "global_inter_send_gap"

    earliest_allowed_send_at = max(constraint_times)
    return {
        "earliest_allowed_send_at": _isoformat_utc(earliest_allowed_send_at),
        "pacing_allowed_now": earliest_allowed_send_at <= current_dt,
        "pacing_block_reason": pacing_block_reason,
        "job_posting_id": job_posting_id,
    }


def _load_latest_sent_at(connection: sqlite3.Connection) -> datetime | None:
    row = connection.execute(
        """
        SELECT sent_at
        FROM outreach_messages
        WHERE sent_at IS NOT NULL
          AND TRIM(sent_at) <> ''
        ORDER BY sent_at DESC, outreach_message_id DESC
        LIMIT 1
        """
    ).fetchone()
    sent_at = _normalize_optional_text(row["sent_at"]) if row is not None else None
    if sent_at is None:
        return None
    return _parse_iso_datetime(sent_at)


def _resolve_local_timezone(current_dt: datetime, local_timezone: tzinfo | str | None) -> tzinfo:
    if isinstance(local_timezone, str):
        return ZoneInfo(local_timezone)
    if local_timezone is not None:
        return local_timezone
    return current_dt.astimezone().tzinfo or UTC


def _parse_iso_datetime(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _isoformat_utc(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _normalize_optional_text(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _is_usable_email(value: str | None) -> bool:
    return bool(value and "@" in value and "." in value.split("@", 1)[-1])


class DeterministicOutreachDraftRenderer(OutreachDraftRenderer):
    def render_role_targeted(self, context: RoleTargetedDraftContext) -> RenderedDraft:
        plan = _compose_role_targeted_composition_plan(context)
        body_lines = [
            f"Hi {_first_name(context.display_name)},",
            "",
            plan.opener_paragraph,
            "",
            plan.background_paragraph,
            "",
            *plan.copilot_paragraphs,
            "",
            plan.ask_paragraph,
        ]
        include_snippet = True
        if include_snippet:
            body_lines.extend(
                [
                    "",
                    "I've included a short snippet below that you can paste into an IM/Email:",
                    "[snippet]",
                    plan.snippet_text,
                    "[/snippet]",
                ]
            )
        body_lines.extend(
            [
                "",
                "Best,",
                context.sender.name,
                *_signature_lines(context.sender),
            ]
        )
        body_markdown = "\n".join(line for line in body_lines if line is not None).strip() + "\n"
        return RenderedDraft(
            subject=_build_role_targeted_subject(context),
            body_markdown=body_markdown,
            body_html=_render_markdown_email_html(body_markdown),
            include_forwardable_snippet=include_snippet,
            opener_decision=context.opener_decision,
        )

    def render_general_learning(self, context: GeneralLearningDraftContext) -> RenderedDraft:
        work_signal = _recipient_work_signal(context.recipient_profile)
        role_hint = context.position_title or "your work"
        subject = f"Learning from your work at {context.company_name} | {context.sender.name}"
        opening = (
            f"I came across your background at {context.company_name}"
            if not work_signal
            else f"I came across your work on {work_signal} at {context.company_name}"
        )
        body_lines = [
            f"Hi {_first_name(context.display_name)},",
            "",
            (
                f"{opening}, and it stood out to me because I have been trying to learn from people working close to "
                f"{role_hint.lower()}. I have been gravitating toward backend, distributed-systems, and "
                "AI-adjacent engineering work."
            ),
            "",
            (
                "I am reaching out in a learning-first mode rather than with a direct role ask. "
                "If you would be open to it, I would really value a short 15-minute conversation to learn "
                "how you think about the work, the team, and what matters most in that area."
            ),
            "",
            "Best,",
            context.sender.name,
            *_signature_lines(context.sender),
        ]
        body_markdown = "\n".join(body_lines).strip() + "\n"
        return RenderedDraft(
            subject=subject,
            body_markdown=body_markdown,
            body_html=_render_markdown_email_html(body_markdown),
            include_forwardable_snippet=False,
        )


def _build_role_targeted_draft_context(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    posting_row: Mapping[str, Any],
    contact_row: Mapping[str, Any],
    sender: SenderIdentity,
    tailoring_inputs: Mapping[str, Any],
) -> RoleTargetedDraftContext:
    recipient_email = _normalize_optional_text(contact_row["current_working_email"])
    if recipient_email is None:
        raise OutreachDraftingError(
            f"Contact `{contact_row['contact_id']}` is missing a usable working email."
        )
    recipient_profile = _load_recipient_profile(
        connection,
        paths,
        job_posting_id=str(posting_row["job_posting_id"]),
        contact_id=str(contact_row["contact_id"]),
    )
    growth_areas = _load_sender_growth_areas(paths)
    interest_areas = _load_sender_interest_areas(paths)
    opener_rubric = _load_opener_rubric(paths)
    theme_selection = _select_role_theme_selection(
        tailoring_inputs["step_3_payload"],
        str(tailoring_inputs["jd_text"]),
        step_4_payload=tailoring_inputs["step_4_payload"],
        step_6_payload=tailoring_inputs["step_6_payload"],
        role_title=str(posting_row["role_title"]),
        growth_areas=growth_areas,
        interest_areas=interest_areas,
    )
    if theme_selection is None:
        raise OutreachDraftingError(
            f"Job posting `{posting_row['job_posting_id']}` does not have an acceptable title-aligned technical theme for role-targeted drafting."
        )
    opener_decision = _build_role_targeted_opener_decision(
        company_name=str(posting_row["company_name"]),
        role_title=str(posting_row["role_title"]),
        jd_text=str(tailoring_inputs["jd_text"]),
        role_intent_summary=_normalize_optional_text(tailoring_inputs.get("role_intent_summary")),
        theme_selection=theme_selection,
    )
    return RoleTargetedDraftContext(
        job_posting_id=str(posting_row["job_posting_id"]),
        job_posting_contact_id=str(contact_row["job_posting_contact_id"]),
        lead_id=str(posting_row["lead_id"]),
        company_name=str(posting_row["company_name"]),
        role_title=str(posting_row["role_title"]),
        recipient_type=str(contact_row["recipient_type"]),
        contact_id=str(contact_row["contact_id"]),
        display_name=str(contact_row["display_name"]),
        recipient_email=recipient_email,
        position_title=_normalize_optional_text(contact_row["position_title"]),
        discovery_summary=_normalize_optional_text(contact_row["discovery_summary"]),
        recipient_profile=recipient_profile,
        jd_text=str(tailoring_inputs["jd_text"]),
        role_intent_summary=_normalize_optional_text(tailoring_inputs.get("role_intent_summary")),
        proof_point=_select_theme_aligned_proof_point(
            tailoring_inputs["step_6_payload"],
            theme_selection=theme_selection,
        ),
        fit_summary=_select_fit_summary(
            tailoring_inputs["step_6_payload"],
            tailoring_inputs["step_3_payload"],
        ),
        work_area=theme_selection.focus_phrase,
        theme_selection=theme_selection,
        opener_rubric=opener_rubric,
        opener_decision=opener_decision,
        sender=sender,
        tailored_resume_path=str(tailoring_inputs["resume_path"]),
    )


def generate_role_targeted_send_set_drafts(
    connection: sqlite3.Connection,
    *,
    project_root: Path | str,
    job_posting_id: str,
    current_time: str,
    local_timezone: tzinfo | str | None = None,
    renderer: OutreachDraftRenderer | None = None,
) -> RoleTargetedDraftBatchResult:
    paths = ProjectPaths.from_root(project_root)
    posting_row = _load_role_targeted_draft_posting_row(connection, job_posting_id=job_posting_id)
    if posting_row["posting_status"] != JOB_POSTING_STATUS_READY_FOR_OUTREACH:
        raise OutreachDraftingError(
            f"Job posting `{job_posting_id}` is `{posting_row['posting_status']}`; drafting starts only from `ready_for_outreach`."
        )
    draftable_contacts = _load_role_targeted_draftable_contacts(
        connection,
        job_posting_id=job_posting_id,
    )
    if not draftable_contacts:
        raise OutreachDraftingError(
            f"Job posting `{job_posting_id}` does not have any untouched ready contacts for drafting."
        )

    sender = _load_sender_identity(paths)
    tailoring_inputs = _load_tailoring_draft_inputs(
        connection,
        paths,
        posting_row=posting_row,
        current_time=current_time,
    )
    draft_renderer = renderer or DeterministicOutreachDraftRenderer()
    drafted_messages: list[DraftedOutreachMessage] = []
    failed_contacts: list[DraftFailure] = []
    posting_promoted = False

    for contact_plan in draftable_contacts:
        contact_row = _load_draft_contact_row(
            connection,
            job_posting_id=job_posting_id,
            contact_id=contact_plan.contact_id,
        )
        recipient_email = _normalize_optional_text(contact_row["current_working_email"])
        if recipient_email is None:
            raise OutreachDraftingError(
                f"Contact `{contact_plan.contact_id}` is missing a usable working email."
            )
        message_id = new_canonical_id("outreach_messages")
        if not posting_promoted:
            _promote_posting_into_outreach_in_progress(
                connection,
                posting_row=posting_row,
                current_time=current_time,
            )
            posting_promoted = True
        _promote_contact_into_outreach_in_progress(
            connection,
            posting_row=posting_row,
            contact_row=contact_row,
            current_time=current_time,
        )
        try:
            context = _build_role_targeted_draft_context(
                connection,
                paths,
                posting_row=posting_row,
                contact_row=contact_row,
                sender=sender,
                tailoring_inputs=tailoring_inputs,
            )
            rendered = draft_renderer.render_role_targeted(context)
        except Exception as exc:
            failure = _persist_failed_draft_attempt(
                connection,
                paths,
                posting_row=posting_row,
                contact_row=contact_row,
                outreach_message_id=message_id,
                outreach_mode=OUTREACH_MODE_ROLE_TARGETED,
                recipient_email=recipient_email,
                current_time=current_time,
                reason_code="draft_generation_failed",
                message=str(exc) or "Draft generation failed.",
            )
            failed_contacts.append(failure)
            continue

        drafted = _persist_rendered_draft(
            connection,
            paths,
            posting_row=posting_row,
            contact_row=contact_row,
            outreach_message_id=message_id,
            outreach_mode=OUTREACH_MODE_ROLE_TARGETED,
            recipient_email=recipient_email,
            rendered=rendered,
            current_time=current_time,
            resume_attachment_path=str(tailoring_inputs["resume_path"]),
            use_role_targeted_mirrors=True,
        )
        drafted_messages.append(drafted)

    return RoleTargetedDraftBatchResult(
        job_posting_id=job_posting_id,
        selected_contact_ids=tuple(contact.contact_id for contact in draftable_contacts),
        drafted_messages=tuple(drafted_messages),
        failed_contacts=tuple(failed_contacts),
        posting_status_after_drafting=JOB_POSTING_STATUS_OUTREACH_IN_PROGRESS,
    )


def refresh_role_targeted_generated_drafts(
    connection: sqlite3.Connection,
    *,
    project_root: Path | str,
    job_posting_id: str,
    current_time: str,
    renderer: OutreachDraftRenderer | None = None,
) -> tuple[str, ...]:
    paths = ProjectPaths.from_root(project_root)
    posting_row = _load_role_targeted_draft_posting_row(connection, job_posting_id=job_posting_id)
    if posting_row["posting_status"] not in {
        JOB_POSTING_STATUS_READY_FOR_OUTREACH,
        JOB_POSTING_STATUS_OUTREACH_IN_PROGRESS,
        JOB_POSTING_STATUS_COMPLETED,
    }:
        return ()
    active_wave = _load_active_role_targeted_wave(connection, job_posting_id=job_posting_id)
    generated_messages = [
        message
        for message in active_wave
        if message.message_status == MESSAGE_STATUS_GENERATED
    ]
    if not generated_messages:
        return ()

    sender = _load_sender_identity(paths)
    tailoring_inputs = _load_tailoring_draft_inputs(
        connection,
        paths,
        posting_row=posting_row,
        current_time=current_time,
    )
    draft_renderer = renderer or DeterministicOutreachDraftRenderer()
    refreshed_ids: list[str] = []

    for active_message in generated_messages:
        contact_row = _load_draft_contact_row(
            connection,
            job_posting_id=job_posting_id,
            contact_id=active_message.contact_id,
        )
        try:
            context = _build_role_targeted_draft_context(
                connection,
                paths,
                posting_row=posting_row,
                contact_row=contact_row,
                sender=sender,
                tailoring_inputs=tailoring_inputs,
            )
            rendered = draft_renderer.render_role_targeted(context)
        except Exception as exc:
            _persist_blocked_send(
                connection,
                paths,
                posting_row=posting_row,
                active_message=active_message,
                current_time=current_time,
                reason_code="draft_refresh_blocked",
                message=str(exc) or "Pending generated draft no longer meets drafting quality gates.",
                exhaust_link=False,
            )
            continue
        refreshed = _refresh_persisted_role_targeted_generated_draft(
            connection,
            paths,
            posting_row=posting_row,
            contact_row=contact_row,
            active_message=active_message,
            rendered=rendered,
            current_time=current_time,
            resume_attachment_path=str(tailoring_inputs["resume_path"]),
        )
        if refreshed:
            refreshed_ids.append(active_message.outreach_message_id)

    return tuple(refreshed_ids)


def _refresh_persisted_role_targeted_generated_draft(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    posting_row: Mapping[str, Any],
    contact_row: Mapping[str, Any],
    active_message: _ActiveWaveMessage,
    rendered: RenderedDraft,
    current_time: str,
    resume_attachment_path: str,
) -> bool:
    company_name = str(posting_row["company_name"])
    role_title = str(posting_row["role_title"])
    recipient_email = _normalize_optional_text(contact_row["current_working_email"]) or str(active_message.recipient_email or "")
    draft_path = paths.outreach_message_draft_path(
        company_name,
        role_title,
        active_message.outreach_message_id,
    )
    html_path = paths.outreach_message_html_path(
        company_name,
        role_title,
        active_message.outreach_message_id,
    )
    send_result_path = paths.outreach_message_send_result_path(
        company_name,
        role_title,
        active_message.outreach_message_id,
    )
    opener_decision_path = paths.outreach_message_opener_decision_path(
        company_name,
        role_title,
        active_message.outreach_message_id,
    )
    needs_refresh = any(
        (
            active_message.subject != rendered.subject,
            active_message.body_text != rendered.body_markdown,
            active_message.body_html != rendered.body_html,
            not draft_path.exists(),
            not send_result_path.exists(),
            bool(rendered.body_html) and not html_path.exists(),
            rendered.opener_decision is not None and not opener_decision_path.exists(),
        )
    )
    if not needs_refresh:
        return False

    _write_text_file(draft_path, rendered.body_markdown)
    body_html_artifact_path: str | None = None
    if rendered.body_html:
        _write_text_file(html_path, rendered.body_html)
        body_html_artifact_path = str(html_path.resolve())
    elif html_path.exists():
        html_path.unlink()
    opener_decision_artifact_path: str | None = None
    linkage = ArtifactLinkage(
        lead_id=str(posting_row["lead_id"]),
        job_posting_id=str(posting_row["job_posting_id"]),
        contact_id=str(contact_row["contact_id"]),
        outreach_message_id=active_message.outreach_message_id,
    )
    if rendered.opener_decision is not None:
        if opener_decision_path.exists():
            write_json_contract(
                opener_decision_path,
                producer_component=OUTREACH_COMPONENT,
                result="success",
                linkage=linkage,
                payload=rendered.opener_decision.as_dict(),
                produced_at=current_time,
            )
        else:
            publish_json_artifact(
                connection,
                paths,
                artifact_type=OPENER_DECISION_ARTIFACT_TYPE,
                artifact_path=opener_decision_path,
                producer_component=OUTREACH_COMPONENT,
                result="success",
                linkage=linkage,
                payload=rendered.opener_decision.as_dict(),
                produced_at=current_time,
            )
        opener_decision_artifact_path = str(opener_decision_path.resolve())
    elif opener_decision_path.exists():
        opener_decision_path.unlink()

    with connection:
        connection.execute(
            """
            UPDATE outreach_messages
            SET subject = ?, body_text = ?, body_html = ?, updated_at = ?
            WHERE outreach_message_id = ?
            """,
            (
                rendered.subject,
                rendered.body_markdown,
                rendered.body_html,
                current_time,
                active_message.outreach_message_id,
            ),
        )

    write_json_contract(
        send_result_path,
        producer_component=OUTREACH_COMPONENT,
        result="success",
        linkage=linkage,
        payload={
            "outreach_mode": OUTREACH_MODE_ROLE_TARGETED,
            "recipient_email": recipient_email,
            "send_status": MESSAGE_STATUS_GENERATED,
            "sent_at": None,
            "thread_id": None,
            "delivery_tracking_id": None,
            "subject": rendered.subject,
            "body_text_artifact_path": str(draft_path.resolve()),
            "body_html_artifact_path": body_html_artifact_path,
            "opener_decision_artifact_path": opener_decision_artifact_path,
            "resume_attachment_path": resume_attachment_path,
        },
        produced_at=current_time,
    )
    _write_text_file(paths.outreach_latest_draft_path(company_name, role_title), rendered.body_markdown)
    _write_text_file(
        paths.outreach_latest_send_result_path(company_name, role_title),
        send_result_path.read_text(encoding="utf-8"),
    )
    return True


def generate_general_learning_draft(
    connection: sqlite3.Connection,
    *,
    project_root: Path | str,
    contact_id: str,
    current_time: str,
    renderer: OutreachDraftRenderer | None = None,
) -> GeneralLearningDraftResult:
    paths = ProjectPaths.from_root(project_root)
    sender = _load_sender_identity(paths)
    contact_row = _load_general_learning_contact_row(connection, contact_id=contact_id)
    recipient_email = _normalize_optional_text(contact_row["current_working_email"])
    if recipient_email is None:
        raise OutreachDraftingError(f"Contact `{contact_id}` is missing a usable working email.")
    recipient_profile = _load_latest_contact_recipient_profile(
        connection,
        paths,
        contact_id=contact_id,
    )
    context = GeneralLearningDraftContext(
        contact_id=str(contact_row["contact_id"]),
        company_name=str(contact_row["company_name"] or "unknown-company"),
        display_name=str(contact_row["display_name"]),
        recipient_email=recipient_email,
        recipient_type=str(contact_row["recipient_type"] or RECIPIENT_TYPE_OTHER_INTERNAL),
        position_title=_normalize_optional_text(contact_row["position_title"]),
        recipient_profile=recipient_profile,
        sender=sender,
    )
    draft_renderer = renderer or DeterministicOutreachDraftRenderer()
    message_id = new_canonical_id("outreach_messages")
    rendered = draft_renderer.render_general_learning(context)
    drafted_message = _persist_rendered_general_learning_draft(
        connection,
        paths,
        contact_row=contact_row,
        outreach_message_id=message_id,
        recipient_email=recipient_email,
        rendered=rendered,
        current_time=current_time,
    )
    return GeneralLearningDraftResult(drafted_message=drafted_message)


def execute_general_learning_outreach(
    connection: sqlite3.Connection,
    *,
    project_root: Path | str,
    contact_id: str,
    current_time: str,
    sender: OutreachMessageSender,
    renderer: OutreachDraftRenderer | None = None,
    feedback_observer: MailboxFeedbackObserver | None = None,
) -> GeneralLearningSendExecutionResult:
    paths = ProjectPaths.from_root(project_root)
    contact_row = _load_general_learning_contact_row(connection, contact_id=contact_id)
    drafted_message: DraftedOutreachMessage | None = None

    active_message = _load_latest_general_learning_message_row(
        connection,
        contact_id=contact_id,
    )
    if active_message is None:
        draft_result = generate_general_learning_draft(
            connection,
            project_root=project_root,
            contact_id=contact_id,
            current_time=current_time,
            renderer=renderer,
        )
        drafted_message = draft_result.drafted_message
        active_message = _load_latest_general_learning_message_row(
            connection,
            contact_id=contact_id,
        )

    if active_message is None:  # pragma: no cover - defensive invariant
        raise OutreachSendingError(
            f"General-learning outreach failed to materialize a message for contact `{contact_id}`."
        )
    if str(active_message["message_status"]) != MESSAGE_STATUS_GENERATED:
        raise OutreachSendingError(
            "General-learning automatic sending requires the latest message to be "
            f"`{MESSAGE_STATUS_GENERATED}`, but `{active_message['outreach_message_id']}` is "
            f"`{active_message['message_status']}`."
        )

    guardrail_block = _evaluate_general_learning_send_guardrails(
        connection,
        paths,
        contact_row=contact_row,
        active_message=active_message,
    )
    if guardrail_block is not None:
        return _persist_blocked_general_learning_send(
            connection,
            paths,
            contact_row=contact_row,
            active_message=active_message,
            current_time=current_time,
            drafted_message=drafted_message,
            reason_code=guardrail_block["reason_code"],
            message=guardrail_block["message"],
        )

    outbound = OutboundOutreachMessage(
        outreach_message_id=str(active_message["outreach_message_id"]),
        contact_id=str(contact_row["contact_id"]),
        job_posting_id=None,
        job_posting_contact_id=None,
        outreach_mode=OUTREACH_MODE_GENERAL_LEARNING,
        recipient_email=str(active_message["recipient_email"]),
        subject=str(active_message["subject"]),
        body_text=str(active_message["body_text"]),
        body_html=_normalize_optional_text(active_message["body_html"]),
        resume_attachment_path=None,
    )
    normalized_outcome = _normalize_send_attempt_outcome(sender.send(outbound))

    if normalized_outcome.outcome == SEND_OUTCOME_SENT:
        result = _persist_successful_general_learning_send(
            connection,
            paths,
            contact_row=contact_row,
            active_message=active_message,
            current_time=current_time,
            drafted_message=drafted_message,
            sent_at=normalized_outcome.sent_at or current_time,
            thread_id=normalized_outcome.thread_id,
            delivery_tracking_id=normalized_outcome.delivery_tracking_id,
        )
        _run_immediate_delivery_feedback_poll_safely(
            connection,
            project_root=project_root,
            current_time=current_time,
            outreach_message_ids=[result.outreach_message_id],
            observer=feedback_observer,
        )
        return result

    if normalized_outcome.outcome == SEND_OUTCOME_AMBIGUOUS:
        return _persist_blocked_general_learning_send(
            connection,
            paths,
            contact_row=contact_row,
            active_message=active_message,
            current_time=current_time,
            drafted_message=drafted_message,
            reason_code=normalized_outcome.reason_code or "ambiguous_send_outcome",
            message=normalized_outcome.message
            or "The general-learning send outcome could not be reconciled safely.",
        )

    return _persist_failed_general_learning_send_attempt(
        connection,
        paths,
        contact_row=contact_row,
        active_message=active_message,
        current_time=current_time,
        drafted_message=drafted_message,
        reason_code=normalized_outcome.reason_code or "send_provider_failed",
        message=normalized_outcome.message
        or "The outbound send provider returned a failure.",
    )


@dataclass(frozen=True)
class _ActiveWaveMessage:
    contact_id: str
    job_posting_contact_id: str
    recipient_type: str
    display_name: str
    recipient_email: str | None
    contact_status: str
    link_level_status: str
    link_created_at: str
    outreach_message_id: str
    message_status: str
    subject: str | None
    body_text: str | None
    body_html: str | None
    thread_id: str | None
    delivery_tracking_id: str | None
    sent_at: str | None
    message_created_at: str
    message_updated_at: str


def execute_role_targeted_send_set(
    connection: sqlite3.Connection,
    *,
    project_root: Path | str,
    job_posting_id: str,
    current_time: str,
    sender: OutreachMessageSender,
    local_timezone: tzinfo | str | None = None,
    feedback_observer: MailboxFeedbackObserver | None = None,
) -> RoleTargetedSendExecutionResult:
    paths = ProjectPaths.from_root(project_root)
    posting_row = _load_role_targeted_send_posting_row(connection, job_posting_id=job_posting_id)
    if posting_row["posting_status"] not in {
        JOB_POSTING_STATUS_READY_FOR_OUTREACH,
        JOB_POSTING_STATUS_OUTREACH_IN_PROGRESS,
        JOB_POSTING_STATUS_COMPLETED,
    }:
        raise OutreachSendingError(
            f"Job posting `{job_posting_id}` is `{posting_row['posting_status']}`; sending starts only from `ready_for_outreach`, `outreach_in_progress`, or `completed`."
        )

    refresh_role_targeted_generated_drafts(
        connection,
        project_root=project_root,
        job_posting_id=job_posting_id,
        current_time=current_time,
    )
    active_wave = _load_active_role_targeted_wave(connection, job_posting_id=job_posting_id)
    if not active_wave:
        raise OutreachSendingError(
            f"Job posting `{job_posting_id}` does not have an active drafted outreach wave."
        )
    _validate_active_role_targeted_wave(active_wave, job_posting_id=job_posting_id)

    current_dt = _parse_iso_datetime(current_time)
    resolved_timezone = _resolve_local_timezone(current_dt, local_timezone)
    wave_contact_ids = [message.contact_id for message in active_wave]
    global_gap_minutes = _determine_global_gap_minutes(
        job_posting_id=job_posting_id,
        selected_contact_ids=wave_contact_ids,
        current_dt=current_dt,
        local_timezone=resolved_timezone,
    )

    sent_messages: list[SentOutreachMessage] = []
    blocked_messages: list[SendExecutionIssue] = []
    failed_messages: list[SendExecutionIssue] = []
    delayed_messages: list[DelayedOutreachMessage] = []

    for index, active_message in enumerate(active_wave):
        if active_message.message_status == MESSAGE_STATUS_SENT:
            continue
        if active_message.message_status == MESSAGE_STATUS_FAILED:
            continue
        retry_state: RetryableBlockedSendState | None = None
        if active_message.message_status == MESSAGE_STATUS_BLOCKED:
            retry_state = _evaluate_retryable_blocked_send_state(
                connection,
                paths,
                posting_row=posting_row,
                active_message=active_message,
                current_time=current_time,
            )
            if not retry_state.is_retryable:
                continue
            if retry_state.retry_exhausted:
                break
            if not retry_state.retry_allowed_now:
                delayed_messages.extend(
                    _build_retry_frontier_delayed_messages(
                        active_wave[index:],
                        earliest_allowed_send_at=str(retry_state.earliest_retry_at),
                    )
                )
                break
        elif active_message.message_status != MESSAGE_STATUS_GENERATED:
            issue = _persist_blocked_send(
                connection,
                paths,
                posting_row=posting_row,
                active_message=active_message,
                current_time=current_time,
                reason_code="unexpected_message_status",
                message=(
                    f"Automatic sending only supports `{MESSAGE_STATUS_GENERATED}` messages, "
                    f"but `{active_message.outreach_message_id}` is `{active_message.message_status}`."
                ),
                exhaust_link=False,
            )
            blocked_messages.append(issue)
            continue

        guardrail_block = _evaluate_send_guardrails(
            connection,
            paths,
            posting_row=posting_row,
            active_message=active_message,
            allow_existing_blocked_send_result=retry_state is not None,
        )
        if guardrail_block is not None:
            issue = _persist_blocked_send(
                connection,
                paths,
                posting_row=posting_row,
                active_message=active_message,
                current_time=current_time,
                reason_code=guardrail_block["reason_code"],
                message=guardrail_block["message"],
                exhaust_link=bool(guardrail_block["exhaust_link"]),
            )
            blocked_messages.append(issue)
            if bool(guardrail_block["stop_wave"]):
                break
            continue

        pacing = _build_role_targeted_send_pacing_plan(
            connection,
            posting_row=posting_row,
            current_dt=current_dt,
            local_timezone=resolved_timezone,
            global_gap_minutes=global_gap_minutes,
        )
        if not pacing["pacing_allowed_now"]:
            if retry_state is not None:
                delayed_messages.extend(
                    _build_retry_frontier_delayed_messages(
                        active_wave[index:],
                        earliest_allowed_send_at=str(pacing["earliest_allowed_send_at"]),
                    )
                )
            else:
                delayed_messages.extend(
                    _build_delayed_messages(
                        active_wave[index:],
                        earliest_allowed_send_at=str(pacing["earliest_allowed_send_at"]),
                        pacing_block_reason=_normalize_optional_text(pacing["pacing_block_reason"]),
                    )
                )
            break

        outbound = OutboundOutreachMessage(
            outreach_message_id=active_message.outreach_message_id,
            contact_id=active_message.contact_id,
            job_posting_id=str(posting_row["job_posting_id"]),
            job_posting_contact_id=active_message.job_posting_contact_id,
            outreach_mode=OUTREACH_MODE_ROLE_TARGETED,
            recipient_email=str(active_message.recipient_email),
            subject=str(active_message.subject),
            body_text=str(active_message.body_text),
            body_html=active_message.body_html,
            resume_attachment_path=_load_resume_attachment_path(
                paths,
                company_name=str(posting_row["company_name"]),
                role_title=str(posting_row["role_title"]),
                outreach_message_id=active_message.outreach_message_id,
            ),
        )
        outcome = sender.send(outbound)
        normalized_outcome = _normalize_send_attempt_outcome(outcome)

        if normalized_outcome.outcome == SEND_OUTCOME_SENT:
            sent_messages.append(
                _persist_successful_send(
                    connection,
                    paths,
                    posting_row=posting_row,
                    active_message=active_message,
                    current_time=current_time,
                    sent_at=normalized_outcome.sent_at or current_time,
                    thread_id=normalized_outcome.thread_id,
                    delivery_tracking_id=normalized_outcome.delivery_tracking_id,
                )
            )
            if index + 1 < len(active_wave):
                post_send_pacing = _build_role_targeted_send_pacing_plan(
                    connection,
                    posting_row=posting_row,
                    current_dt=current_dt,
                    local_timezone=resolved_timezone,
                    global_gap_minutes=global_gap_minutes,
                )
                delayed_messages.extend(
                    _build_delayed_messages(
                        active_wave[index + 1 :],
                        earliest_allowed_send_at=str(post_send_pacing["earliest_allowed_send_at"]),
                        pacing_block_reason=_normalize_optional_text(post_send_pacing["pacing_block_reason"]),
                    )
                )
            break

        if normalized_outcome.outcome == SEND_OUTCOME_AMBIGUOUS:
            blocked_messages.append(
                _persist_blocked_send(
                    connection,
                    paths,
                    posting_row=posting_row,
                    active_message=active_message,
                    current_time=current_time,
                    reason_code=normalized_outcome.reason_code or "ambiguous_send_outcome",
                    message=normalized_outcome.message or "The send outcome could not be reconciled safely.",
                    exhaust_link=True,
                )
            )
            break

        if _is_retryable_transient_send_failure(
            reason_code=normalized_outcome.reason_code,
            message=normalized_outcome.message,
        ):
            blocked_messages.append(
                _persist_blocked_send(
                    connection,
                    paths,
                    posting_row=posting_row,
                    active_message=active_message,
                    current_time=current_time,
                    reason_code=normalized_outcome.reason_code or "gmail_send_failed",
                    message=normalized_outcome.message
                    or "The outbound Gmail transport failed transiently and should be retried later.",
                    exhaust_link=False,
                    allow_wave_completion=False,
                )
            )
            retry_due_at = _isoformat_utc(
                _parse_iso_datetime(current_time)
                + timedelta(minutes=TRANSIENT_SEND_RETRY_COOLDOWN_MINUTES)
            )
            delayed_messages.extend(
                _build_retry_frontier_delayed_messages(
                    active_wave[index:],
                    earliest_allowed_send_at=retry_due_at,
                )
            )
            break

        failed_messages.append(
            _persist_failed_send_attempt(
                connection,
                paths,
                posting_row=posting_row,
                active_message=active_message,
                current_time=current_time,
                reason_code=normalized_outcome.reason_code or "send_provider_failed",
                message=normalized_outcome.message or "The outbound send provider returned a failure.",
            )
        )

    posting_status_after_execution = _load_current_posting_status(
        connection,
        job_posting_id=job_posting_id,
    )
    if sent_messages:
        _run_immediate_delivery_feedback_poll_safely(
            connection,
            project_root=project_root,
            current_time=current_time,
            outreach_message_ids=[message.outreach_message_id for message in sent_messages],
            observer=feedback_observer,
        )
    return RoleTargetedSendExecutionResult(
        job_posting_id=job_posting_id,
        selected_contact_ids=tuple(message.contact_id for message in active_wave),
        sent_messages=tuple(sent_messages),
        blocked_messages=tuple(blocked_messages),
        failed_messages=tuple(failed_messages),
        delayed_messages=tuple(delayed_messages),
        posting_status_after_execution=posting_status_after_execution,
    )


def _load_role_targeted_send_posting_row(
    connection: sqlite3.Connection,
    *,
    job_posting_id: str,
) -> sqlite3.Row:
    row = connection.execute(
        """
        SELECT job_posting_id, lead_id, company_name, role_title, posting_status
        FROM job_postings
        WHERE job_posting_id = ?
        """,
        (job_posting_id,),
    ).fetchone()
    if row is None:
        raise OutreachSendingError(f"Job posting `{job_posting_id}` was not found.")
    return row


def _load_active_role_targeted_wave(
    connection: sqlite3.Connection,
    *,
    job_posting_id: str,
) -> list[_ActiveWaveMessage]:
    rows = connection.execute(
        """
        SELECT jpc.job_posting_contact_id, jpc.contact_id, jpc.recipient_type, jpc.link_level_status,
               jpc.created_at AS link_created_at, c.display_name, c.current_working_email,
               c.contact_status, om.outreach_message_id, om.message_status, om.subject,
               om.body_text, om.body_html, om.thread_id, om.delivery_tracking_id, om.sent_at,
               om.created_at AS message_created_at, om.updated_at AS message_updated_at
        FROM job_posting_contacts jpc
        JOIN contacts c
          ON c.contact_id = jpc.contact_id
        LEFT JOIN outreach_messages om
          ON om.outreach_message_id = (
            SELECT om2.outreach_message_id
            FROM outreach_messages om2
            WHERE om2.job_posting_id = jpc.job_posting_id
              AND om2.contact_id = jpc.contact_id
            ORDER BY om2.created_at DESC, om2.outreach_message_id DESC
            LIMIT 1
          )
        WHERE jpc.job_posting_id = ?
          AND jpc.link_level_status IN (?, ?, ?)
          AND EXISTS (
            SELECT 1
            FROM outreach_messages om3
            WHERE om3.job_posting_id = jpc.job_posting_id
              AND om3.contact_id = jpc.contact_id
          )
        ORDER BY jpc.created_at ASC, jpc.job_posting_contact_id ASC
        """,
        (
            job_posting_id,
            POSTING_CONTACT_STATUS_OUTREACH_IN_PROGRESS,
            POSTING_CONTACT_STATUS_OUTREACH_DONE,
            POSTING_CONTACT_STATUS_EXHAUSTED,
        ),
    ).fetchall()
    wave = [
        _ActiveWaveMessage(
            contact_id=str(row["contact_id"]),
            job_posting_contact_id=str(row["job_posting_contact_id"]),
            recipient_type=str(row["recipient_type"]),
            display_name=str(row["display_name"]),
            recipient_email=_normalize_optional_text(row["current_working_email"]),
            contact_status=str(row["contact_status"]),
            link_level_status=str(row["link_level_status"]),
            link_created_at=str(row["link_created_at"]),
            outreach_message_id=str(row["outreach_message_id"]) if row["outreach_message_id"] else "",
            message_status=str(row["message_status"]) if row["message_status"] else "",
            subject=_normalize_optional_text(row["subject"]),
            body_text=_normalize_optional_text(row["body_text"]),
            body_html=_normalize_optional_text(row["body_html"]),
            thread_id=_normalize_optional_text(row["thread_id"]),
            delivery_tracking_id=_normalize_optional_text(row["delivery_tracking_id"]),
            sent_at=_normalize_optional_text(row["sent_at"]),
            message_created_at=str(row["message_created_at"]) if row["message_created_at"] else "",
            message_updated_at=str(row["message_updated_at"]) if row["message_updated_at"] else "",
        )
        for row in rows
    ]
    return sorted(wave, key=_active_wave_sort_key)


def _validate_active_role_targeted_wave(
    active_wave: Sequence[_ActiveWaveMessage],
    *,
    job_posting_id: str,
) -> None:
    missing_messages = [
        message.job_posting_contact_id
        for message in active_wave
        if not message.outreach_message_id or not message.message_status
    ]
    if missing_messages:
        missing_label = ", ".join(missing_messages)
        raise OutreachSendingError(
            f"Job posting `{job_posting_id}` has active outreach contacts without persisted message rows: {missing_label}."
        )


def _active_wave_sort_key(message: _ActiveWaveMessage) -> tuple[int, int, str, str]:
    return (
        _selection_state_rank(_recipient_type_send_slot(message.recipient_type)),
        _fallback_type_rank(message.recipient_type),
        message.link_created_at,
        message.contact_id,
    )


def _recipient_type_send_slot(recipient_type: str) -> str:
    if recipient_type == RECIPIENT_TYPE_RECRUITER:
        return _CANDIDATE_STATE_READY
    if recipient_type in {RECIPIENT_TYPE_HIRING_MANAGER, RECIPIENT_TYPE_FOUNDER}:
        return _CANDIDATE_STATE_NEEDS_EMAIL
    if recipient_type == RECIPIENT_TYPE_ENGINEER:
        return _CANDIDATE_STATE_REPEAT_REVIEW
    return _CANDIDATE_STATE_UNAVAILABLE


def _build_role_targeted_send_pacing_plan(
    connection: sqlite3.Connection,
    *,
    posting_row: Mapping[str, Any],
    current_dt: datetime,
    local_timezone: tzinfo,
    global_gap_minutes: int,
) -> dict[str, Any]:
    posting_sent_today = _count_posting_sends_today(
        connection,
        job_posting_id=str(posting_row["job_posting_id"]),
        current_dt=current_dt,
        local_timezone=local_timezone,
    )
    remaining_posting_daily_capacity = max(
        0,
        AUTOMATIC_POSTING_DAILY_SEND_CAP - posting_sent_today,
    )
    return _build_pacing_plan(
        connection,
        current_dt=current_dt,
        local_timezone=local_timezone,
        job_posting_id=str(posting_row["job_posting_id"]),
        posting_sent_today=posting_sent_today,
        remaining_posting_daily_capacity=remaining_posting_daily_capacity,
        global_gap_minutes=global_gap_minutes,
    )


def _build_delayed_messages(
    messages: Sequence[_ActiveWaveMessage],
    *,
    earliest_allowed_send_at: str,
    pacing_block_reason: str | None,
) -> list[DelayedOutreachMessage]:
    delayed: list[DelayedOutreachMessage] = []
    for message in messages:
        if message.message_status != MESSAGE_STATUS_GENERATED:
            continue
        delayed.append(
            DelayedOutreachMessage(
                outreach_message_id=message.outreach_message_id,
                contact_id=message.contact_id,
                job_posting_contact_id=message.job_posting_contact_id,
                earliest_allowed_send_at=earliest_allowed_send_at,
                pacing_block_reason=pacing_block_reason,
            )
        )
    return delayed


def _build_retry_frontier_delayed_messages(
    messages: Sequence[_ActiveWaveMessage],
    *,
    earliest_allowed_send_at: str,
) -> list[DelayedOutreachMessage]:
    delayed: list[DelayedOutreachMessage] = []
    for message in messages:
        if message.message_status not in {MESSAGE_STATUS_GENERATED, MESSAGE_STATUS_BLOCKED}:
            continue
        delayed.append(
            DelayedOutreachMessage(
                outreach_message_id=message.outreach_message_id,
                contact_id=message.contact_id,
                job_posting_contact_id=message.job_posting_contact_id,
                earliest_allowed_send_at=earliest_allowed_send_at,
                pacing_block_reason=TRANSIENT_SEND_RETRY_PACING_REASON,
            )
        )
    return delayed


def _is_retryable_transient_send_failure(
    *,
    reason_code: str | None,
    message: str | None,
) -> bool:
    if reason_code != "gmail_send_failed":
        return False
    normalized_message = _normalize_optional_text(message)
    if normalized_message is None:
        return False
    return any(pattern.search(normalized_message) for pattern in TRANSIENT_SEND_FAILURE_PATTERNS)


def _load_role_targeted_send_result_path(
    paths: ProjectPaths,
    *,
    posting_row: Mapping[str, Any],
    outreach_message_id: str,
) -> Path:
    return paths.outreach_message_send_result_path(
        str(posting_row["company_name"]),
        str(posting_row["role_title"]),
        outreach_message_id,
    )


def _evaluate_retryable_blocked_send_state(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    posting_row: Mapping[str, Any],
    active_message: _ActiveWaveMessage,
    current_time: str,
) -> RetryableBlockedSendState:
    if active_message.message_status != MESSAGE_STATUS_BLOCKED:
        return RetryableBlockedSendState(
            is_retryable=False,
            retry_allowed_now=False,
            retry_exhausted=False,
            attempt_count=0,
            automatic_retry_count=0,
            earliest_retry_at=None,
            reason_code=None,
            message=None,
        )

    send_result_path = _load_role_targeted_send_result_path(
        paths,
        posting_row=posting_row,
        outreach_message_id=active_message.outreach_message_id,
    )
    if not send_result_path.exists():
        return RetryableBlockedSendState(
            is_retryable=False,
            retry_allowed_now=False,
            retry_exhausted=False,
            attempt_count=0,
            automatic_retry_count=0,
            earliest_retry_at=None,
            reason_code=None,
            message=None,
        )

    try:
        send_result_contract = _read_json_file(send_result_path)
    except Exception:
        return RetryableBlockedSendState(
            is_retryable=False,
            retry_allowed_now=False,
            retry_exhausted=False,
            attempt_count=0,
            automatic_retry_count=0,
            earliest_retry_at=None,
            reason_code=None,
            message=None,
        )

    send_status = _normalize_optional_text(send_result_contract.get("send_status"))
    reason_code = _normalize_optional_text(send_result_contract.get("reason_code"))
    message = _normalize_optional_text(send_result_contract.get("message"))
    if send_status != MESSAGE_STATUS_BLOCKED:
        return RetryableBlockedSendState(
            is_retryable=False,
            retry_allowed_now=False,
            retry_exhausted=False,
            attempt_count=0,
            automatic_retry_count=0,
            earliest_retry_at=None,
            reason_code=reason_code,
            message=message,
        )

    send_attempt_count = max(
        0,
        int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM artifact_records
                WHERE artifact_type = ?
                  AND outreach_message_id = ?
                """,
                (
                    SEND_RESULT_ARTIFACT_TYPE,
                    active_message.outreach_message_id,
                ),
            ).fetchone()[0]
            or 0
        )
        - 1,
    )
    if reason_code == "ambiguous_send_state":
        remaining_guardrail = _evaluate_send_guardrails(
            connection,
            paths,
            posting_row=posting_row,
            active_message=active_message,
            allow_existing_blocked_send_result=True,
        )
        if remaining_guardrail is None:
            return RetryableBlockedSendState(
                is_retryable=True,
                retry_allowed_now=True,
                retry_exhausted=False,
                attempt_count=send_attempt_count,
                automatic_retry_count=0,
                earliest_retry_at=current_time,
                reason_code=reason_code,
                message=message,
            )
        return RetryableBlockedSendState(
            is_retryable=False,
            retry_allowed_now=False,
            retry_exhausted=False,
            attempt_count=send_attempt_count,
            automatic_retry_count=0,
            earliest_retry_at=None,
            reason_code=reason_code,
            message=message,
        )

    if not _is_retryable_transient_send_failure(
        reason_code=reason_code,
        message=message,
    ):
        return RetryableBlockedSendState(
            is_retryable=False,
            retry_allowed_now=False,
            retry_exhausted=False,
            attempt_count=send_attempt_count,
            automatic_retry_count=0,
            earliest_retry_at=None,
            reason_code=reason_code,
            message=message,
        )

    automatic_retry_count = max(0, send_attempt_count - 1)
    retry_exhausted = automatic_retry_count >= MAX_AUTOMATIC_TRANSIENT_SEND_RETRIES

    current_dt = _parse_iso_datetime(current_time)
    last_attempt_at = _normalize_optional_text(send_result_contract.get("produced_at"))
    if last_attempt_at is None:
        last_attempt_at = active_message.message_updated_at
    earliest_retry_at_dt = _parse_iso_datetime(last_attempt_at) + timedelta(
        minutes=TRANSIENT_SEND_RETRY_COOLDOWN_MINUTES
    )
    earliest_retry_at = _isoformat_utc(earliest_retry_at_dt)
    return RetryableBlockedSendState(
        is_retryable=True,
        retry_allowed_now=not retry_exhausted and earliest_retry_at_dt <= current_dt,
        retry_exhausted=retry_exhausted,
        attempt_count=send_attempt_count,
        automatic_retry_count=automatic_retry_count,
        earliest_retry_at=earliest_retry_at,
        reason_code=reason_code,
        message=message,
    )


def _find_next_send_frontier_message(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    posting_row: Mapping[str, Any],
    active_wave: Sequence[_ActiveWaveMessage],
    current_time: str,
) -> tuple[_ActiveWaveMessage | None, RetryableBlockedSendState | None]:
    for active_message in active_wave:
        if active_message.message_status == MESSAGE_STATUS_SENT:
            continue
        if active_message.message_status == MESSAGE_STATUS_FAILED:
            continue
        if active_message.message_status == MESSAGE_STATUS_BLOCKED:
            retry_state = _evaluate_retryable_blocked_send_state(
                connection,
                paths,
                posting_row=posting_row,
                active_message=active_message,
                current_time=current_time,
            )
            if retry_state.is_retryable:
                return active_message, retry_state
            continue
        return active_message, None
    return None, None


def _evaluate_send_guardrails(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    posting_row: Mapping[str, Any],
    active_message: _ActiveWaveMessage,
    allow_existing_blocked_send_result: bool = False,
) -> dict[str, Any] | None:
    if active_message.recipient_email is None:
        return {
            "reason_code": "missing_recipient_email",
            "message": "Automatic sending requires a usable recipient email.",
            "exhaust_link": False,
            "stop_wave": False,
        }
    if active_message.subject is None or active_message.body_text is None:
        return {
            "reason_code": "missing_draft_content",
            "message": "Automatic sending requires persisted draft subject and body content.",
            "exhaust_link": False,
            "stop_wave": False,
        }

    draft_path = paths.outreach_message_draft_path(
        str(posting_row["company_name"]),
        str(posting_row["role_title"]),
        active_message.outreach_message_id,
    )
    send_result_path = paths.outreach_message_send_result_path(
        str(posting_row["company_name"]),
        str(posting_row["role_title"]),
        active_message.outreach_message_id,
    )
    if not draft_path.exists():
        return {
            "reason_code": "missing_draft_artifact",
            "message": f"Draft artifact is missing for `{active_message.outreach_message_id}`.",
            "exhaust_link": False,
            "stop_wave": False,
        }
    if not send_result_path.exists():
        return {
            "reason_code": "missing_send_result_artifact",
            "message": f"send_result.json is missing for `{active_message.outreach_message_id}`.",
            "exhaust_link": False,
            "stop_wave": False,
        }

    try:
        send_result_contract = _read_json_file(send_result_path)
    except Exception:
        return {
            "reason_code": "invalid_send_result_artifact",
            "message": f"send_result.json is unreadable for `{active_message.outreach_message_id}`.",
            "exhaust_link": False,
            "stop_wave": False,
        }
    send_status = _normalize_optional_text(send_result_contract.get("send_status"))
    if send_status == MESSAGE_STATUS_SENT or (
        send_status == MESSAGE_STATUS_BLOCKED and not allow_existing_blocked_send_result
    ):
        return {
            "reason_code": "ambiguous_send_state",
            "message": "Stored send_result.json already reflects a non-generated send state, so automatic resend is unsafe.",
            "exhaust_link": True,
            "stop_wave": True,
        }
    if active_message.sent_at or active_message.thread_id or active_message.delivery_tracking_id:
        return {
            "reason_code": "ambiguous_send_state",
            "message": "Message delivery metadata already exists without a clean completed send state, so automatic resend is unsafe.",
            "exhaust_link": True,
            "stop_wave": True,
        }

    prior_sent_count = int(
        connection.execute(
            """
            SELECT COUNT(*)
            FROM outreach_messages
            WHERE contact_id = ?
              AND outreach_message_id <> ?
              AND (
                sent_at IS NOT NULL
                OR message_status = ?
              )
            """,
            (
                active_message.contact_id,
                active_message.outreach_message_id,
                MESSAGE_STATUS_SENT,
            ),
        ).fetchone()[0]
        or 0
    )
    if prior_sent_count > 0:
        return {
            "reason_code": "repeat_outreach_review_required",
            "message": "Prior outreach history exists for this contact, so automatic repeat sending is blocked pending review.",
            "exhaust_link": True,
            "stop_wave": False,
        }

    other_active_message_count = int(
        connection.execute(
            """
            SELECT COUNT(*)
            FROM outreach_messages
            WHERE contact_id = ?
              AND outreach_message_id <> ?
              AND message_status IN (?, ?)
            """,
            (
                active_message.contact_id,
                active_message.outreach_message_id,
                MESSAGE_STATUS_GENERATED,
                MESSAGE_STATUS_BLOCKED,
            ),
        ).fetchone()[0]
        or 0
    )
    if other_active_message_count > 0:
        return {
            "reason_code": "ambiguous_send_state",
            "message": "Multiple active outreach messages exist for this contact, so automatic resend is unsafe.",
            "exhaust_link": True,
            "stop_wave": True,
        }
    return None


def _normalize_send_attempt_outcome(outcome: SendAttemptOutcome) -> SendAttemptOutcome:
    if outcome.outcome not in {
        SEND_OUTCOME_SENT,
        SEND_OUTCOME_FAILED,
        SEND_OUTCOME_AMBIGUOUS,
    }:
        raise OutreachSendingError(
            f"Unsupported send outcome `{outcome.outcome}` returned by the message sender."
        )
    return outcome


def _load_resume_attachment_path(
    paths: ProjectPaths,
    *,
    company_name: str,
    role_title: str,
    outreach_message_id: str,
) -> str | None:
    send_result_path = paths.outreach_message_send_result_path(company_name, role_title, outreach_message_id)
    if not send_result_path.exists():
        return None
    payload = _read_json_file(send_result_path)
    return _normalize_optional_text(payload.get("resume_attachment_path"))


def _persist_successful_send(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    posting_row: Mapping[str, Any],
    active_message: _ActiveWaveMessage,
    current_time: str,
    sent_at: str,
    thread_id: str | None,
    delivery_tracking_id: str | None,
) -> SentOutreachMessage:
    normalized_sent_at = _isoformat_utc(_parse_iso_datetime(sent_at))
    with connection:
        connection.execute(
            """
            UPDATE outreach_messages
            SET message_status = ?, thread_id = ?, delivery_tracking_id = ?, sent_at = ?, updated_at = ?
            WHERE outreach_message_id = ?
            """,
            (
                MESSAGE_STATUS_SENT,
                thread_id,
                delivery_tracking_id,
                normalized_sent_at,
                current_time,
                active_message.outreach_message_id,
            ),
        )
    _transition_contact_to_sent(
        connection,
        posting_row=posting_row,
        active_message=active_message,
        current_time=current_time,
    )
    send_result_artifact_path = _publish_role_targeted_send_result(
        connection,
        paths,
        posting_row=posting_row,
        active_message=active_message,
        current_time=current_time,
        result="success",
        send_status=MESSAGE_STATUS_SENT,
        sent_at=normalized_sent_at,
        thread_id=thread_id,
        delivery_tracking_id=delivery_tracking_id,
        reason_code=None,
        message=None,
    )
    _complete_posting_if_wave_finished(
        connection,
        posting_row=posting_row,
        current_time=current_time,
    )
    return SentOutreachMessage(
        outreach_message_id=active_message.outreach_message_id,
        contact_id=active_message.contact_id,
        job_posting_contact_id=active_message.job_posting_contact_id,
        recipient_email=str(active_message.recipient_email),
        sent_at=normalized_sent_at,
        thread_id=thread_id,
        delivery_tracking_id=delivery_tracking_id,
        send_result_artifact_path=send_result_artifact_path,
    )


def _persist_blocked_send(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    posting_row: Mapping[str, Any],
    active_message: _ActiveWaveMessage,
    current_time: str,
    reason_code: str,
    message: str,
    exhaust_link: bool,
    allow_wave_completion: bool = True,
) -> SendExecutionIssue:
    with connection:
        connection.execute(
            """
            UPDATE outreach_messages
            SET message_status = ?, updated_at = ?
            WHERE outreach_message_id = ?
            """,
            (
                MESSAGE_STATUS_BLOCKED,
                current_time,
                active_message.outreach_message_id,
            ),
        )
    if exhaust_link:
        _mark_posting_contact_exhausted_for_review(
            connection,
            posting_row=posting_row,
            active_message=active_message,
            current_time=current_time,
            transition_reason=message,
        )
    _publish_role_targeted_send_result(
        connection,
        paths,
        posting_row=posting_row,
        active_message=active_message,
        current_time=current_time,
        result="blocked",
        send_status=MESSAGE_STATUS_BLOCKED,
        sent_at=None,
        thread_id=active_message.thread_id,
        delivery_tracking_id=active_message.delivery_tracking_id,
        reason_code=reason_code,
        message=message,
    )
    if allow_wave_completion:
        _complete_posting_if_wave_finished(
            connection,
            posting_row=posting_row,
            current_time=current_time,
        )
    return SendExecutionIssue(
        outreach_message_id=active_message.outreach_message_id,
        contact_id=active_message.contact_id,
        job_posting_contact_id=active_message.job_posting_contact_id,
        reason_code=reason_code,
        message=message,
    )


def _persist_failed_send_attempt(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    posting_row: Mapping[str, Any],
    active_message: _ActiveWaveMessage,
    current_time: str,
    reason_code: str,
    message: str,
) -> SendExecutionIssue:
    with connection:
        connection.execute(
            """
            UPDATE outreach_messages
            SET message_status = ?, updated_at = ?
            WHERE outreach_message_id = ?
            """,
            (
                MESSAGE_STATUS_FAILED,
                current_time,
                active_message.outreach_message_id,
            ),
        )
    _publish_role_targeted_send_result(
        connection,
        paths,
        posting_row=posting_row,
        active_message=active_message,
        current_time=current_time,
        result="failed",
        send_status=MESSAGE_STATUS_FAILED,
        sent_at=None,
        thread_id=None,
        delivery_tracking_id=None,
        reason_code=reason_code,
        message=message,
    )
    return SendExecutionIssue(
        outreach_message_id=active_message.outreach_message_id,
        contact_id=active_message.contact_id,
        job_posting_contact_id=active_message.job_posting_contact_id,
        reason_code=reason_code,
        message=message,
    )


def _publish_role_targeted_send_result(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    posting_row: Mapping[str, Any],
    active_message: _ActiveWaveMessage,
    current_time: str,
    result: str,
    send_status: str,
    sent_at: str | None,
    thread_id: str | None,
    delivery_tracking_id: str | None,
    reason_code: str | None,
    message: str | None,
) -> str:
    company_name = str(posting_row["company_name"])
    role_title = str(posting_row["role_title"])
    draft_path = paths.outreach_message_draft_path(company_name, role_title, active_message.outreach_message_id)
    html_path = paths.outreach_message_html_path(company_name, role_title, active_message.outreach_message_id)
    send_result_path = paths.outreach_message_send_result_path(
        company_name,
        role_title,
        active_message.outreach_message_id,
    )
    published = publish_json_artifact(
        connection,
        paths,
        artifact_type=SEND_RESULT_ARTIFACT_TYPE,
        artifact_path=send_result_path,
        producer_component=OUTREACH_COMPONENT,
        result=result,
        linkage=ArtifactLinkage(
            lead_id=str(posting_row["lead_id"]),
            job_posting_id=str(posting_row["job_posting_id"]),
            contact_id=active_message.contact_id,
            outreach_message_id=active_message.outreach_message_id,
        ),
        payload={
            "outreach_mode": OUTREACH_MODE_ROLE_TARGETED,
            "recipient_email": active_message.recipient_email,
            "send_status": send_status,
            "sent_at": sent_at,
            "thread_id": thread_id,
            "delivery_tracking_id": delivery_tracking_id,
            "subject": active_message.subject,
            "body_text_artifact_path": str(draft_path.resolve()) if draft_path.exists() else None,
            "body_html_artifact_path": str(html_path.resolve()) if html_path.exists() else None,
            "resume_attachment_path": _load_resume_attachment_path(
                paths,
                company_name=company_name,
                role_title=role_title,
                outreach_message_id=active_message.outreach_message_id,
            ),
        },
        produced_at=current_time,
        reason_code=reason_code,
        message=message,
    )
    _write_text_file(
        paths.outreach_latest_send_result_path(company_name, role_title),
        json.dumps(published.contract, indent=2) + "\n",
    )
    return str(send_result_path.resolve())


def _transition_contact_to_sent(
    connection: sqlite3.Connection,
    *,
    posting_row: Mapping[str, Any],
    active_message: _ActiveWaveMessage,
    current_time: str,
) -> None:
    with connection:
        if active_message.contact_status != CONTACT_STATUS_SENT:
            connection.execute(
                """
                UPDATE contacts
                SET contact_status = ?, updated_at = ?
                WHERE contact_id = ?
                """,
                (
                    CONTACT_STATUS_SENT,
                    current_time,
                    active_message.contact_id,
                ),
            )
            _record_state_transition(
                connection,
                object_type="contact",
                object_id=active_message.contact_id,
                stage="contact_status",
                previous_state=active_message.contact_status,
                new_state=CONTACT_STATUS_SENT,
                transition_timestamp=current_time,
                transition_reason="An outreach message was sent for this contact.",
                lead_id=str(posting_row["lead_id"]),
                job_posting_id=str(posting_row["job_posting_id"]),
                contact_id=active_message.contact_id,
            )
        if active_message.link_level_status != POSTING_CONTACT_STATUS_OUTREACH_DONE:
            connection.execute(
                """
                UPDATE job_posting_contacts
                SET link_level_status = ?, updated_at = ?
                WHERE job_posting_contact_id = ?
                """,
                (
                    POSTING_CONTACT_STATUS_OUTREACH_DONE,
                    current_time,
                    active_message.job_posting_contact_id,
                ),
            )
            _record_state_transition(
                connection,
                object_type="job_posting_contact",
                object_id=active_message.job_posting_contact_id,
                stage="link_level_status",
                previous_state=active_message.link_level_status,
                new_state=POSTING_CONTACT_STATUS_OUTREACH_DONE,
                transition_timestamp=current_time,
                transition_reason="An outreach message was sent for this posting-contact pair.",
                lead_id=str(posting_row["lead_id"]),
                job_posting_id=str(posting_row["job_posting_id"]),
                contact_id=active_message.contact_id,
            )


def _mark_posting_contact_exhausted_for_review(
    connection: sqlite3.Connection,
    *,
    posting_row: Mapping[str, Any],
    active_message: _ActiveWaveMessage,
    current_time: str,
    transition_reason: str,
) -> None:
    if active_message.link_level_status in {
        POSTING_CONTACT_STATUS_OUTREACH_DONE,
        POSTING_CONTACT_STATUS_EXHAUSTED,
    }:
        return
    with connection:
        connection.execute(
            """
            UPDATE job_posting_contacts
            SET link_level_status = ?, updated_at = ?
            WHERE job_posting_contact_id = ?
            """,
            (
                POSTING_CONTACT_STATUS_EXHAUSTED,
                current_time,
                active_message.job_posting_contact_id,
            ),
        )
        _record_state_transition(
            connection,
            object_type="job_posting_contact",
            object_id=active_message.job_posting_contact_id,
            stage="link_level_status",
            previous_state=active_message.link_level_status,
            new_state=POSTING_CONTACT_STATUS_EXHAUSTED,
            transition_timestamp=current_time,
            transition_reason=transition_reason,
            lead_id=str(posting_row["lead_id"]),
            job_posting_id=str(posting_row["job_posting_id"]),
            contact_id=active_message.contact_id,
        )


def _complete_posting_if_wave_finished(
    connection: sqlite3.Connection,
    *,
    posting_row: Mapping[str, Any],
    current_time: str,
) -> None:
    active_wave = _load_active_role_targeted_wave(
        connection,
        job_posting_id=str(posting_row["job_posting_id"]),
    )
    if not active_wave:
        return
    latest_statuses = {message.message_status for message in active_wave}
    if not latest_statuses or not latest_statuses.issubset({MESSAGE_STATUS_SENT, MESSAGE_STATUS_BLOCKED}):
        return

    current_status = _load_current_posting_status(
        connection,
        job_posting_id=str(posting_row["job_posting_id"]),
    )
    if current_status == JOB_POSTING_STATUS_COMPLETED:
        return
    next_send_set_plan = evaluate_role_targeted_send_set(
        connection,
        job_posting_id=str(posting_row["job_posting_id"]),
        current_time=current_time,
    )
    if next_send_set_plan.selected_contacts:
        next_status = next_send_set_plan.posting_status_after_evaluation
        if next_status == JOB_POSTING_STATUS_READY_FOR_OUTREACH:
            transition_reason = (
                "The active drafted outreach wave reached terminal states, and untouched "
                "contacts remain ready for the next automatic send wave."
            )
        else:
            transition_reason = (
                "The active drafted outreach wave reached terminal states, and untouched "
                "contacts remain but still need usable email discovery before the next wave."
            )
    else:
        next_status = JOB_POSTING_STATUS_COMPLETED
        transition_reason = (
            "The active drafted outreach wave reached terminal sent or review-blocked "
            "states and no untouched automatic outreach contacts remain."
        )
    if current_status == next_status:
        return
    with connection:
        connection.execute(
            """
            UPDATE job_postings
            SET posting_status = ?, updated_at = ?
            WHERE job_posting_id = ?
            """,
            (
                next_status,
                current_time,
                posting_row["job_posting_id"],
            ),
        )
        _record_state_transition(
            connection,
            object_type="job_posting",
            object_id=str(posting_row["job_posting_id"]),
            stage="posting_status",
            previous_state=current_status,
            new_state=next_status,
            transition_timestamp=current_time,
            transition_reason=transition_reason,
            lead_id=str(posting_row["lead_id"]),
            job_posting_id=str(posting_row["job_posting_id"]),
            contact_id=None,
        )


def _load_current_posting_status(
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
        raise OutreachSendingError(f"Job posting `{job_posting_id}` was not found.")
    return str(row["posting_status"])


def _load_role_targeted_draft_posting_row(
    connection: sqlite3.Connection,
    *,
    job_posting_id: str,
) -> sqlite3.Row:
    row = connection.execute(
        """
        SELECT jp.job_posting_id, jp.lead_id, jp.company_name, jp.role_title, jp.posting_status,
               jp.jd_artifact_path
        FROM job_postings jp
        WHERE jp.job_posting_id = ?
        """,
        (job_posting_id,),
    ).fetchone()
    if row is None:
        raise OutreachDraftingError(f"Job posting `{job_posting_id}` was not found.")
    return row


def _load_draft_contact_row(
    connection: sqlite3.Connection,
    *,
    job_posting_id: str,
    contact_id: str,
) -> sqlite3.Row:
    row = connection.execute(
        """
        SELECT jpc.job_posting_contact_id, jpc.job_posting_id, jpc.contact_id, jpc.recipient_type,
               jpc.link_level_status, c.display_name, c.current_working_email, c.contact_status,
               c.position_title, c.discovery_summary, c.company_name
        FROM job_posting_contacts jpc
        JOIN contacts c
          ON c.contact_id = jpc.contact_id
        WHERE jpc.job_posting_id = ?
          AND jpc.contact_id = ?
        """,
        (job_posting_id, contact_id),
    ).fetchone()
    if row is None:
        raise OutreachDraftingError(
            f"Linked contact `{contact_id}` for job posting `{job_posting_id}` was not found."
        )
    return row


def _load_general_learning_contact_row(
    connection: sqlite3.Connection,
    *,
    contact_id: str,
) -> sqlite3.Row:
    row = connection.execute(
        """
        SELECT c.contact_id, c.display_name, c.current_working_email, c.company_name,
               c.contact_status,
               c.position_title, c.discovery_summary,
               (
                 SELECT jpc.recipient_type
                 FROM job_posting_contacts jpc
                 WHERE jpc.contact_id = c.contact_id
                 ORDER BY jpc.created_at DESC, jpc.job_posting_contact_id DESC
                 LIMIT 1
               ) AS recipient_type
        FROM contacts c
        WHERE c.contact_id = ?
        """,
        (contact_id,),
    ).fetchone()
    if row is None:
        raise OutreachDraftingError(f"Contact `{contact_id}` was not found.")
    return row


def _load_latest_general_learning_message_row(
    connection: sqlite3.Connection,
    *,
    contact_id: str,
) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT outreach_message_id, contact_id, recipient_email, message_status, subject,
               body_text, body_html, thread_id, delivery_tracking_id, sent_at, created_at,
               updated_at
        FROM outreach_messages
        WHERE contact_id = ?
          AND outreach_mode = ?
        ORDER BY created_at DESC, outreach_message_id DESC
        LIMIT 1
        """,
        (contact_id, OUTREACH_MODE_GENERAL_LEARNING),
    ).fetchone()


def _run_immediate_delivery_feedback_poll_safely(
    connection: sqlite3.Connection,
    *,
    project_root: Path | str,
    current_time: str,
    outreach_message_ids: Sequence[str],
    observer: MailboxFeedbackObserver | None,
) -> None:
    try:
        run_immediate_delivery_feedback_poll(
            connection,
            project_root=project_root,
            current_time=current_time,
            outreach_message_ids=outreach_message_ids,
            observer=observer,
        )
    except Exception:
        # Immediate polling is opportunistic; the delayed feedback sync is the durable
        # recovery path and should not negate a successful send.
        return


def _load_latest_approved_tailoring_run_row(
    connection: sqlite3.Connection,
    *,
    job_posting_id: str,
) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT resume_tailoring_run_id, resume_review_status, final_resume_path, meta_yaml_path
        FROM resume_tailoring_runs
        WHERE job_posting_id = ?
          AND resume_review_status = 'approved'
        ORDER BY COALESCE(completed_at, updated_at, created_at, started_at) DESC,
                 resume_tailoring_run_id DESC
        LIMIT 1
        """,
        (job_posting_id,),
    ).fetchone()


def _load_tailoring_draft_inputs(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    posting_row: Mapping[str, Any],
    current_time: str,
) -> dict[str, Any]:
    latest_run = _load_latest_approved_tailoring_run_row(
        connection,
        job_posting_id=str(posting_row["job_posting_id"]),
    )
    if latest_run is None or str(latest_run["resume_review_status"]).strip() != "approved":
        raise OutreachDraftingError(
            f"Job posting `{posting_row['job_posting_id']}` is not backed by an approved tailoring run."
        )
    resume_path_text = _normalize_optional_text(latest_run["final_resume_path"])
    if resume_path_text is None:
        raise OutreachDraftingError(
            f"Job posting `{posting_row['job_posting_id']}` does not have a tailored resume attachment path."
        )
    resume_path = paths.resolve_from_root(resume_path_text)
    if not resume_path.exists():
        raise OutreachDraftingError(f"Tailored resume path does not exist: {resume_path}")

    company_name = str(posting_row["company_name"])
    role_title = str(posting_row["role_title"])
    step_3_path = paths.tailoring_step_3_jd_signals_path(company_name, role_title)
    step_4_path = paths.tailoring_step_4_evidence_map_path(company_name, role_title)
    step_6_path = paths.tailoring_step_6_candidate_bullets_path(company_name, role_title)
    if not step_3_path.exists() or not step_6_path.exists():
        raise OutreachDraftingError(
            f"Tailoring intelligence artifacts are missing for job posting `{posting_row['job_posting_id']}`."
        )
    jd_text = _load_posting_jd_text(paths, posting_row)
    return {
        "current_time": current_time,
        "resume_path": resume_path,
        "jd_text": jd_text,
        "step_3_payload": _read_yaml_file(step_3_path),
        "step_4_payload": _read_yaml_file(step_4_path) if step_4_path.exists() else {},
        "step_6_payload": _read_yaml_file(step_6_path),
        "role_intent_summary": _normalize_optional_text(
            _read_yaml_file(step_3_path).get("role_intent_summary")
        ),
    }


def _load_posting_jd_text(paths: ProjectPaths, posting_row: Mapping[str, Any]) -> str:
    jd_artifact_path = _normalize_optional_text(posting_row["jd_artifact_path"])
    if jd_artifact_path is None:
        return ""
    jd_path = paths.resolve_from_root(jd_artifact_path)
    if not jd_path.exists():
        return ""
    return jd_path.read_text(encoding="utf-8")


def _load_sender_identity(paths: ProjectPaths) -> SenderIdentity:
    profile_path = paths.assets_dir / "resume-tailoring" / "profile.md"
    if not profile_path.exists():
        raise OutreachDraftingError("Sender master profile is missing.")
    profile_text = profile_path.read_text(encoding="utf-8")
    fields: dict[str, str] = {}
    education_line: str | None = None
    current_heading = ""
    for raw_line in profile_text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("<!--"):
            continue
        heading_match = MARKDOWN_HEADING_RE.match(stripped)
        if heading_match is not None:
            current_heading = heading_match.group("title").strip().lower()
            continue
        field_match = PROFILE_FIELD_RE.match(stripped)
        if field_match is not None:
            fields[field_match.group("label").strip().lower()] = field_match.group("value").strip()
            continue
        if current_heading == "education" and stripped.startswith("- ") and education_line is None:
            education_line = stripped[2:].strip()
    name = fields.get("name", "Achyutaram Sonti")
    return SenderIdentity(
        name=name,
        email=fields.get("email"),
        phone=fields.get("phone"),
        linkedin_url=fields.get("linkedin"),
        github_url=fields.get("github"),
        education_summary=_normalize_education_line(education_line),
    )


def _normalize_education_line(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"\*\*", "", value).strip()
    if "Arizona State University" in normalized and "MS" in normalized:
        return None
    return normalized


def _load_recipient_profile(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    job_posting_id: str,
    contact_id: str,
) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT file_path
        FROM artifact_records
        WHERE artifact_type = ?
          AND job_posting_id = ?
          AND contact_id = ?
        ORDER BY created_at DESC, artifact_id DESC
        LIMIT 1
        """,
        ("recipient_profile", job_posting_id, contact_id),
    ).fetchone()
    if row is None or not row["file_path"]:
        return None
    path = paths.resolve_from_root(str(row["file_path"]))
    if not path.exists():
        return None
    payload = _read_json_file(path)
    profile = payload.get("profile")
    return profile if isinstance(profile, Mapping) else None


def _load_latest_contact_recipient_profile(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    contact_id: str,
) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT file_path
        FROM artifact_records
        WHERE artifact_type = ?
          AND contact_id = ?
        ORDER BY created_at DESC, artifact_id DESC
        LIMIT 1
        """,
        ("recipient_profile", contact_id),
    ).fetchone()
    if row is None or not row["file_path"]:
        return None
    path = paths.resolve_from_root(str(row["file_path"]))
    if not path.exists():
        return None
    payload = _read_json_file(path)
    profile = payload.get("profile")
    return profile if isinstance(profile, Mapping) else None


def _select_proof_point(step_6_payload: Mapping[str, Any]) -> str | None:
    bullets = list((step_6_payload.get("software_engineer") or {}).get("bullets") or [])
    if not bullets:
        return None
    candidate_entries = []
    for entry in bullets:
        text = str(entry.get("text") or "").strip()
        if not text:
            continue
        candidate_entries.append(
            (
                text,
                _normalize_optional_text(entry.get("purpose")) or "",
            )
        )
    if not candidate_entries:
        return None
    purpose_rank = {
        "scale-impact": 0,
        "optimization": 1,
        "end-to-end-flow": 2,
        "reliability-operations": 3,
    }
    candidate_entries.sort(
        key=lambda item: (
            purpose_rank.get(item[1], 99),
            0 if METRIC_RE.search(item[0]) else 1,
            len(item[0]),
        )
    )
    return candidate_entries[0][0]


def _select_fit_summary(
    step_6_payload: Mapping[str, Any],
    step_3_payload: Mapping[str, Any],
) -> str | None:
    selected_items: list[str] = []
    signal_ids = {
        str(signal.get("signal_id"))
        for signal in step_3_payload.get("signals", [])
        if signal.get("priority") in {"must_have", "core_responsibility"}
    }
    for entry in step_6_payload.get("technical_skills", []) or []:
        matched_signal_ids = {str(signal_id) for signal_id in entry.get("matched_signal_ids") or []}
        if signal_ids and not (signal_ids & matched_signal_ids):
            continue
        for item in entry.get("items") or []:
            normalized = str(item).strip()
            if normalized and normalized not in selected_items:
                selected_items.append(normalized)
            if len(selected_items) == 4:
                return ", ".join(selected_items)
    for entry in step_6_payload.get("technical_skills", []) or []:
        for item in entry.get("items") or []:
            normalized = str(item).strip()
            if normalized and normalized not in selected_items:
                selected_items.append(normalized)
            if len(selected_items) == 4:
                return ", ".join(selected_items)
    return ", ".join(selected_items[:4]) or None


def _load_sender_growth_areas(paths: ProjectPaths) -> tuple[SenderGrowthArea, ...]:
    growth_path = paths.assets_dir / "outreach" / "candidate-growth-areas.yaml"
    if not growth_path.exists():
        return ()
    payload = _read_yaml_file(growth_path)
    areas: list[SenderGrowthArea] = []
    for entry in payload.get("areas") or []:
        if not isinstance(entry, Mapping):
            continue
        area_id = _normalize_optional_text(entry.get("area_id"))
        label = _normalize_optional_text(entry.get("label"))
        if area_id is None or label is None:
            continue
        keywords = tuple(
            keyword.lower()
            for keyword in (entry.get("keywords") or [])
            if _normalize_optional_text(keyword) is not None
        )
        growth_sentence = _normalize_optional_text(entry.get("growth_overlap_sentence"))
        background_sentence = _normalize_optional_text(entry.get("background_overlap_sentence"))
        combined_sentence = _normalize_optional_text(entry.get("combined_overlap_sentence"))
        if growth_sentence is None or background_sentence is None or combined_sentence is None:
            continue
        areas.append(
            SenderGrowthArea(
                area_id=area_id,
                label=label,
                keywords=keywords,
                growth_overlap_sentence=growth_sentence,
                background_overlap_sentence=background_sentence,
                combined_overlap_sentence=combined_sentence,
            )
        )
    return tuple(areas)


def _load_sender_interest_areas(paths: ProjectPaths) -> tuple[SenderInterestArea, ...]:
    interest_path = paths.assets_dir / "outreach" / "candidate-interest-areas.yaml"
    if not interest_path.exists():
        return ()
    payload = _read_yaml_file(interest_path)
    areas: list[SenderInterestArea] = []
    for entry in payload.get("areas") or []:
        if not isinstance(entry, Mapping):
            continue
        area_id = _normalize_optional_text(entry.get("area_id"))
        label = _normalize_optional_text(entry.get("label"))
        if area_id is None or label is None:
            continue
        keywords = tuple(
            keyword.lower()
            for keyword in (entry.get("keywords") or [])
            if _normalize_optional_text(keyword) is not None
        )
        interest_sentence = _normalize_optional_text(entry.get("interest_overlap_sentence"))
        snippet_sentence = _normalize_optional_text(entry.get("snippet_interest_sentence"))
        if interest_sentence is None or snippet_sentence is None:
            continue
        areas.append(
            SenderInterestArea(
                area_id=area_id,
                label=label,
                keywords=keywords,
                interest_overlap_sentence=interest_sentence,
                snippet_interest_sentence=snippet_sentence,
            )
        )
    return tuple(areas)


def _default_opener_rubric() -> OpenerRubric:
    return OpenerRubric(
        version=1,
        allowed_claim_modes=(
            CLAIM_MODE_DIRECT_BACKGROUND,
            CLAIM_MODE_ADJACENT_OVERLAP,
            CLAIM_MODE_GROWTH_AREA,
            CLAIM_MODE_INTEREST_AREA,
        ),
        blocked_focus_phrases=(
            "application delivery",
            "platform enhancements",
            "additional tools such as",
            "programming languages such as",
        ),
        blocked_opener_phrases=(
            "i've done this kind of work",
            "that is what prompted me to reach out",
            "which is what prompted me to reach out",
        ),
        minimum_specific_anchor_count=1,
        require_title_alignment=True,
    )


def _load_opener_rubric(paths: ProjectPaths) -> OpenerRubric:
    rubric_path = paths.assets_dir / "outreach" / "opener-rubric.yaml"
    if not rubric_path.exists():
        return _default_opener_rubric()
    payload = _read_yaml_file(rubric_path)
    default = _default_opener_rubric()
    allowed_claim_modes = tuple(
        value
        for value in (payload.get("allowed_claim_modes") or [])
        if _normalize_optional_text(value) is not None
    ) or default.allowed_claim_modes
    blocked_focus_phrases = tuple(
        value.lower()
        for value in (payload.get("blocked_focus_phrases") or [])
        if _normalize_optional_text(value) is not None
    ) or default.blocked_focus_phrases
    blocked_opener_phrases = tuple(
        value.lower()
        for value in (payload.get("blocked_opener_phrases") or [])
        if _normalize_optional_text(value) is not None
    ) or default.blocked_opener_phrases
    minimum_specific_anchor_count = payload.get("minimum_specific_anchor_count")
    if not isinstance(minimum_specific_anchor_count, int) or minimum_specific_anchor_count <= 0:
        minimum_specific_anchor_count = default.minimum_specific_anchor_count
    require_title_alignment = payload.get("require_title_alignment")
    if not isinstance(require_title_alignment, bool):
        require_title_alignment = default.require_title_alignment
    version = payload.get("version")
    if not isinstance(version, int):
        version = default.version
    return OpenerRubric(
        version=version,
        allowed_claim_modes=allowed_claim_modes,
        blocked_focus_phrases=blocked_focus_phrases,
        blocked_opener_phrases=blocked_opener_phrases,
        minimum_specific_anchor_count=minimum_specific_anchor_count,
        require_title_alignment=require_title_alignment,
    )


def _format_interest_snippet_sentence(template: str, *, focus: str) -> str:
    try:
        return template.format(focus=focus)
    except (IndexError, KeyError, ValueError):
        return template


def _tokenize_role_theme_text(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[A-Za-z0-9+#./-]+", text.lower())
        if len(token) >= 2
    }


def _role_theme_rule(role_title: str | None) -> Mapping[str, Any] | None:
    normalized_title = _normalize_optional_text(role_title)
    if normalized_title is None:
        return None
    for rule in ROLE_THEME_TITLE_RULES:
        if rule["pattern"].search(normalized_title):
            return rule
    return None


def _extract_cloud_provider_suffix(value: str) -> str | None:
    lowered = value.lower()
    providers: list[str] = []
    if "aws" in lowered or "amazon web services" in lowered:
        providers.append("AWS")
    if "gcp" in lowered or "google cloud" in lowered:
        providers.append("GCP")
    if "azure" in lowered:
        providers.append("Azure")
    if "pcf" in lowered:
        providers.append("PCF")
    unique: list[str] = []
    for provider in providers:
        if provider not in unique:
            unique.append(provider)
    if len(unique) < 2:
        return None
    return _join_focus_phrases(unique)


def _extract_role_theme_parts(*values: str) -> tuple[str, ...]:
    parts: list[str] = []
    for value in values:
        if not value:
            continue
        for part in _focus_summary_parts(value):
            if part not in parts:
                parts.append(part)
    return tuple(parts)


def _anchor_keywords(anchor_labels: Sequence[str]) -> set[str]:
    keywords: set[str] = set()
    for label in anchor_labels:
        keywords.update(ANCHOR_KEYWORD_HINTS.get(label, ()))
    return keywords


def _score_step_6_theme_overlap(
    raw_signal: str,
    *,
    step_6_payload: Mapping[str, Any] | None,
    anchor_labels: Sequence[str],
) -> int:
    if step_6_payload is None:
        return 0
    target_terms = {
        token
        for token in _tokenize_role_theme_text(raw_signal)
        if token not in ROLE_THEME_OVERLAP_STOPWORDS and len(token) >= 4
    }
    target_terms |= _anchor_keywords(anchor_labels)
    if not target_terms:
        return 0
    score = 0
    for entry in step_6_payload.get("technical_skills", []) or []:
        items = " ".join(str(item) for item in entry.get("items") or [])
        overlap = target_terms & _tokenize_role_theme_text(items)
        if overlap:
            score += min(3, len(overlap))
    for bullet in (step_6_payload.get("software_engineer") or {}).get("bullets") or []:
        text = _normalize_optional_text(bullet.get("text"))
        if text is None:
            continue
        overlap = target_terms & _tokenize_role_theme_text(text)
        if not overlap:
            continue
        score += 2 + min(3, len(overlap))
        if METRIC_RE.search(text):
            score += 2
    return score


def _match_growth_area(
    cleaned_signal: str,
    *,
    role_title: str | None,
    anchor_labels: Sequence[str],
    growth_areas: Sequence[SenderGrowthArea],
) -> tuple[int, SenderGrowthArea | None]:
    if not growth_areas:
        return 0, None
    normalized_title = (_normalize_optional_text(role_title) or "").lower()
    signal_terms = _tokenize_role_theme_text(cleaned_signal) | _anchor_keywords(anchor_labels)
    role_rule = _role_theme_rule(role_title)
    allowed_area_ids = set(role_rule.get("growth_area_ids") or ()) if role_rule is not None else set()
    best_score = 0
    best_area: SenderGrowthArea | None = None
    for area in growth_areas:
        if allowed_area_ids and area.area_id not in allowed_area_ids:
            continue
        score = 0
        for keyword in area.keywords:
            if keyword in normalized_title:
                score += 1
            if keyword in cleaned_signal.lower():
                score += 2
            if keyword in signal_terms:
                score += 1
        if score > best_score:
            best_score = score
            best_area = area
    return best_score, best_area


def _match_interest_area(
    cleaned_signal: str,
    *,
    source_text: str | None,
    role_title: str | None,
    anchor_labels: Sequence[str],
    interest_areas: Sequence[SenderInterestArea],
) -> tuple[int, SenderInterestArea | None]:
    if not interest_areas:
        return 0, None
    role_rule = _role_theme_rule(role_title)
    if role_rule is None:
        return 0, None
    allowed_area_ids = tuple(role_rule.get("interest_area_ids") or ())
    if not allowed_area_ids:
        return 0, None
    normalized_title = (_normalize_optional_text(role_title) or "").lower()
    lowered_signal = cleaned_signal.lower()
    lowered_source = (_normalize_optional_text(source_text) or "").lower()
    signal_terms = (
        _tokenize_role_theme_text(cleaned_signal)
        | _tokenize_role_theme_text(lowered_source)
        | _anchor_keywords(anchor_labels)
    )
    allowed_area_id_set = set(allowed_area_ids)
    best_score = 0
    best_area: SenderInterestArea | None = None
    for area in interest_areas:
        if area.area_id not in allowed_area_id_set:
            continue
        score = 0
        for keyword in area.keywords:
            if keyword in normalized_title:
                score += 1
            if keyword in lowered_signal:
                score += 2
            if keyword in lowered_source:
                score += 2
            if keyword in signal_terms:
                score += 1
        if score > best_score:
            best_score = score
            best_area = area
    return best_score, best_area


def _keyword_hits(text: str, keywords: set[str]) -> int:
    lowered = text.lower()
    tokens = _tokenize_role_theme_text(text)
    hits = 0
    for keyword in keywords:
        normalized_keyword = keyword.lower()
        if (
            " " in normalized_keyword
            or "/" in normalized_keyword
            or "-" in normalized_keyword
        ):
            if normalized_keyword in lowered:
                hits += 1
        elif normalized_keyword in tokens:
            hits += 1
    return hits


def _theme_direct_anchor_labels(theme_selection: RoleThemeSelection) -> tuple[str, ...]:
    focus_labels = tuple(sorted(_extract_role_focus_anchors(theme_selection.focus_phrase)))
    candidate_labels = focus_labels or theme_selection.anchor_labels
    allowed_labels = ROLE_THEME_DIRECT_CLAIM_RULES.get(theme_selection.role_family or "", ())
    if allowed_labels:
        direct_labels = tuple(
            label for label in candidate_labels if label in allowed_labels
        )
        if direct_labels:
            return direct_labels
    specialized = tuple(
        label
        for label in candidate_labels
        if label in ROLE_THEME_SPECIALIZED_DIRECT_ANCHORS
    )
    if specialized:
        return specialized
    return candidate_labels


def _score_direct_background_overlap_for_label(
    label: str,
    *,
    theme_selection: RoleThemeSelection,
    step_4_payload: Mapping[str, Any] | None,
    step_6_payload: Mapping[str, Any] | None,
) -> int:
    direct_keywords = _anchor_keywords((label,))
    if not direct_keywords:
        return 0
    score = 0
    source_signals = {
        normalized
        for signal in theme_selection.source_signals
        if (normalized := _normalize_optional_text(signal)) is not None
    }
    if step_4_payload is not None:
        confidence_weight = {"high": 3, "medium": 2, "low": 1}
        matches = step_4_payload.get("matches")
        if isinstance(matches, list):
            for match in matches:
                if not isinstance(match, Mapping):
                    continue
                jd_signal = _normalize_optional_text(match.get("jd_signal"))
                if source_signals and jd_signal not in source_signals:
                    continue
                source_excerpt = _normalize_optional_text(match.get("source_excerpt"))
                if source_excerpt is None:
                    continue
                hits = _keyword_hits(source_excerpt, direct_keywords)
                if hits <= 0:
                    continue
                confidence = (_normalize_optional_text(match.get("confidence")) or "").lower()
                score += hits + confidence_weight.get(confidence, 1)
    if step_6_payload is not None:
        for bullet in (step_6_payload.get("software_engineer") or {}).get("bullets") or []:
            text = _normalize_optional_text(bullet.get("text"))
            if text is None:
                continue
            hits = _keyword_hits(text, direct_keywords)
            if hits <= 0:
                continue
            score += hits + (1 if METRIC_RE.search(text) else 0)
    return score


def _score_theme_direct_background_overlap(
    theme_selection: RoleThemeSelection,
    *,
    step_4_payload: Mapping[str, Any] | None,
    step_6_payload: Mapping[str, Any] | None,
) -> int:
    direct_anchor_labels = _theme_direct_anchor_labels(theme_selection)
    if not direct_anchor_labels:
        return 0
    per_label_scores = {
        label: _score_direct_background_overlap_for_label(
            label,
            theme_selection=theme_selection,
            step_4_payload=step_4_payload,
            step_6_payload=step_6_payload,
        )
        for label in direct_anchor_labels
    }
    specialized_focus_labels = tuple(
        label
        for label in direct_anchor_labels
        if label in ROLE_THEME_SPECIALIZED_DIRECT_ANCHORS
    )
    if (
        theme_selection.role_family is None
        and len(specialized_focus_labels) > 1
        and any(per_label_scores.get(label, 0) <= 0 for label in specialized_focus_labels)
    ):
        return 0
    return sum(per_label_scores.values())


def _score_transferable_background_overlap(
    *,
    step_4_payload: Mapping[str, Any] | None,
    step_6_payload: Mapping[str, Any] | None,
) -> int:
    transferable_keywords = _anchor_keywords(ROLE_THEME_TRANSFERABLE_ANCHORS)
    score = 0
    if step_4_payload is not None:
        matches = step_4_payload.get("matches")
        if isinstance(matches, list):
            for match in matches:
                if not isinstance(match, Mapping):
                    continue
                source_excerpt = _normalize_optional_text(match.get("source_excerpt"))
                if source_excerpt is None:
                    continue
                hits = _keyword_hits(source_excerpt, transferable_keywords)
                if hits > 0:
                    score += hits
    if step_6_payload is not None:
        for entry in step_6_payload.get("technical_skills", []) or []:
            items_text = " ".join(str(item) for item in entry.get("items") or [])
            hits = _keyword_hits(items_text, transferable_keywords)
            if hits > 0:
                score += hits
        for bullet in (step_6_payload.get("software_engineer") or {}).get("bullets") or []:
            text = _normalize_optional_text(bullet.get("text"))
            if text is None:
                continue
            hits = _keyword_hits(text, transferable_keywords)
            if hits > 0:
                score += hits + (1 if METRIC_RE.search(text) else 0)
    return score


def _candidate_focus_parts(
    raw_signal: str,
    normalized_focus: str,
) -> tuple[str, ...]:
    normalized = _normalize_optional_text(normalized_focus)
    if normalized is not None and _should_preserve_explicit_focus(raw_signal, normalized):
        return (normalized,)
    parts = list(_extract_role_theme_parts(raw_signal, normalized_focus))
    if parts:
        return tuple(parts)
    return (normalized,) if normalized is not None else ()


def _is_tool_only_candidate(raw_signal: str, normalized_focus: str) -> bool:
    lowered_raw = raw_signal.lower()
    lowered_focus = normalized_focus.lower()
    if "backend work will include" in lowered_raw or "frontend work will include" in lowered_raw:
        return False
    if re.search(r"\b(?:additional tools such as|tools such as|programming languages such as)\b", lowered_raw):
        return True
    if _looks_like_technology_focus_list(normalized_focus):
        return not re.search(
            r"\b(?:build|design|develop|implement|architect|drive|define|support|deploy|deliver)\b",
            lowered_raw,
        )
    if re.fullmatch(r"[a-z0-9#+./ -]+(?:,\s*[a-z0-9#+./ -]+){1,5}", lowered_focus):
        return True
    return False


def _should_preserve_explicit_focus(raw_signal: str, normalized_focus: str) -> bool:
    lowered_raw = raw_signal.lower()
    lowered_focus = normalized_focus.lower()
    if any(token in lowered_raw or token in lowered_focus for token in ("swagger", "postman")):
        return True
    if "full cycle delivery" in lowered_raw or "full-cycle ai/ml" in lowered_focus:
        return True
    if "spark-based data pipelines" in lowered_focus:
        return True
    if re.search(r"\bfor (?:ai|ml|machine learning|deep learning)\b.*\bworkloads?\b", lowered_focus):
        return True
    if re.match(
        r"^(?:implementing|building|designing|developing)\s+event-driven,?\s+distributed systems?\b",
        lowered_focus,
    ) and "metadata" in lowered_focus:
        return True
    if re.search(r"\brest(?:ful)? apis?\s+or\s+microservices?\b", lowered_focus):
        return True
    if "backend work will include" in lowered_raw or "frontend work will include" in lowered_raw:
        return True
    if _looks_like_technology_focus_list(normalized_focus) and not re.search(
        r"\b(?:additional tools such as|tools such as|programming languages such as)\b",
        lowered_raw,
    ):
        return True
    if re.match(
        r"^(?:supporting|building|designing|developing|implementing)\s+cloud-based applications? and services?\b",
        lowered_focus,
    ):
        return True
    return False


def _build_role_theme_candidates(
    step_3_payload: Mapping[str, Any],
    jd_text: str,
    *,
    step_4_payload: Mapping[str, Any] | None,
    step_6_payload: Mapping[str, Any] | None,
    role_title: str | None,
    growth_areas: Sequence[SenderGrowthArea],
    interest_areas: Sequence[SenderInterestArea],
) -> list[_RoleThemeCandidate]:
    candidate_signals: list[tuple[str, str]] = []
    for priority_key in ("must_have", "core_responsibility", "nice_to_have"):
        signals = step_3_payload.get("signals_by_priority", {}).get(priority_key) or []
        for signal in signals:
            text = _normalize_optional_text(signal.get("signal"))
            if text is not None:
                candidate_signals.append((priority_key, text))
    role_intent_summary = _normalize_optional_text(step_3_payload.get("role_intent_summary"))
    if role_intent_summary is not None:
        candidate_signals.extend(
            ("role_intent", part.strip())
            for part in role_intent_summary.split(";")
            if part.strip()
        )
    derived_role_title = role_title or _normalize_optional_text(
        (step_3_payload.get("role_metadata") or {}).get("role_title")
        if isinstance(step_3_payload.get("role_metadata"), Mapping)
        else None
    )
    candidates: list[_RoleThemeCandidate] = []
    for source_kind, raw_signal in candidate_signals:
        normalized_focus = _normalize_technical_focus_phrase(
            raw_signal,
            role_title=derived_role_title,
        )
        if normalized_focus is None:
            continue
        if _is_tool_only_candidate(raw_signal, normalized_focus) and source_kind in {"must_have", "nice_to_have"}:
            continue
        anchor_labels = tuple(
            sorted(_extract_role_focus_anchors(normalized_focus) | _extract_role_focus_anchors(raw_signal))
        )
        if not anchor_labels:
            continue
        title_score = _score_role_signal_title_alignment(normalized_focus, derived_role_title)
        technical_score = _role_signal_technical_priority(normalized_focus, raw_signal)
        specificity_score = _score_role_signal_specificity(normalized_focus, raw_signal)
        background_score = _score_jd_signal_evidence_overlap(raw_signal, step_4_payload)
        background_score += _score_step_6_theme_overlap(
            raw_signal,
            step_6_payload=step_6_payload,
            anchor_labels=anchor_labels,
        )
        growth_score, matched_growth_area = _match_growth_area(
            normalized_focus,
            role_title=derived_role_title,
            anchor_labels=anchor_labels,
            growth_areas=growth_areas,
        )
        interest_score, _matched_interest_area = _match_interest_area(
            normalized_focus,
            source_text=raw_signal,
            role_title=derived_role_title,
            anchor_labels=anchor_labels,
            interest_areas=interest_areas,
        )
        if technical_score <= 0 or specificity_score <= 0:
            continue
        if background_score <= 0 and growth_score <= 0 and interest_score <= 0:
            continue
        score = (
            technical_score * 100
            + specificity_score * 25
            + title_score * 20
            + ROLE_SIGNAL_SOURCE_PRIORITY.get(source_kind, 0) * 10
            + background_score * 5
            + growth_score * 5
            + interest_score * 5
        )
        candidates.append(
            _RoleThemeCandidate(
                raw_signal=raw_signal,
                source_kind=source_kind,
                normalized_focus=normalized_focus,
                anchor_labels=anchor_labels,
                focus_parts=_candidate_focus_parts(raw_signal, normalized_focus),
                score=score,
                title_score=title_score,
                technical_score=technical_score,
                specificity_score=specificity_score,
                background_score=background_score,
                growth_score=growth_score,
                interest_score=interest_score,
                role_family=_normalize_optional_text(
                    (_role_theme_rule(derived_role_title) or {}).get("family")
                    if _role_theme_rule(derived_role_title) is not None
                    else None
                ),
                growth_area_label=matched_growth_area.label if matched_growth_area is not None else None,
            )
        )
    if candidates:
        return candidates
    for line in jd_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        normalized_focus = _normalize_technical_focus_phrase(stripped, role_title=derived_role_title)
        if normalized_focus is None:
            continue
        anchor_labels = tuple(
            sorted(_extract_role_focus_anchors(normalized_focus) | _extract_role_focus_anchors(stripped))
        )
        if not anchor_labels:
            continue
        background_score = _score_jd_signal_evidence_overlap(stripped, step_4_payload)
        background_score += _score_step_6_theme_overlap(
            stripped,
            step_6_payload=step_6_payload,
            anchor_labels=anchor_labels,
        )
        growth_score, matched_growth_area = _match_growth_area(
            normalized_focus,
            role_title=derived_role_title,
            anchor_labels=anchor_labels,
            growth_areas=growth_areas,
        )
        interest_score, _matched_interest_area = _match_interest_area(
            normalized_focus,
            source_text=stripped,
            role_title=derived_role_title,
            anchor_labels=anchor_labels,
            interest_areas=interest_areas,
        )
        if background_score <= 0 and growth_score <= 0 and interest_score <= 0:
            continue
        title_score = _score_role_signal_title_alignment(normalized_focus, derived_role_title)
        technical_score = _role_signal_technical_priority(normalized_focus, stripped)
        specificity_score = _score_role_signal_specificity(normalized_focus, stripped)
        if technical_score <= 0 or specificity_score <= 0:
            continue
        candidates.append(
            _RoleThemeCandidate(
                raw_signal=stripped,
                source_kind="jd_fallback",
                normalized_focus=normalized_focus,
                anchor_labels=anchor_labels,
                focus_parts=_candidate_focus_parts(stripped, normalized_focus),
                score=(
                    technical_score * 100
                    + specificity_score * 25
                    + title_score * 20
                    + background_score * 5
                    + growth_score * 5
                    + interest_score * 5
                ),
                title_score=title_score,
                technical_score=technical_score,
                specificity_score=specificity_score,
                background_score=background_score,
                growth_score=growth_score,
                interest_score=interest_score,
                role_family=_normalize_optional_text(
                    (_role_theme_rule(derived_role_title) or {}).get("family")
                    if _role_theme_rule(derived_role_title) is not None
                    else None
                ),
                growth_area_label=matched_growth_area.label if matched_growth_area is not None else None,
            )
        )
    return candidates


def _order_theme_parts(
    parts: Sequence[str],
    *,
    role_title: str | None,
) -> list[str]:
    role_rule = _role_theme_rule(role_title)
    preferred_anchors = tuple(role_rule.get("preferred_anchors") or ()) if role_rule is not None else ()
    preferred_index = {anchor: index for index, anchor in enumerate(preferred_anchors)}
    unique_parts: list[str] = []
    for part in parts:
        if part not in unique_parts:
            unique_parts.append(part)
    return sorted(
        unique_parts,
        key=lambda part: (
            preferred_index.get(ROLE_THEME_PART_LABELS.get(part, ""), 99),
            -ROLE_THEME_PART_PRIORITY.get(ROLE_THEME_PART_LABELS.get(part, ""), 0),
            len(part),
        ),
    )


def _synthesize_role_theme_focus(
    best_candidate: _RoleThemeCandidate,
    candidates: Sequence[_RoleThemeCandidate],
    *,
    role_title: str | None,
) -> str:
    chosen_parts: list[str] = []
    provider_suffix: str | None = None
    primary_anchors = set(best_candidate.anchor_labels)
    generic_anchor_labels = {"cloud", "backend", "distributed"}
    explicit_best_focus = (
        len(best_candidate.focus_parts) == 1
        and best_candidate.focus_parts[0] == best_candidate.normalized_focus
        and best_candidate.focus_parts[0] not in ROLE_THEME_PART_LABELS
    )
    if explicit_best_focus:
        chosen_parts.extend(best_candidate.focus_parts)
        provider_suffix = _extract_cloud_provider_suffix(best_candidate.raw_signal)
    else:
        for candidate in sorted(candidates, key=lambda item: item.score, reverse=True):
            shared = primary_anchors & set(candidate.anchor_labels)
            if candidate is not best_candidate and not shared and candidate.title_score <= 0:
                continue
            for part in candidate.focus_parts:
                if part not in chosen_parts:
                    chosen_parts.append(part)
            provider_suffix = provider_suffix or _extract_cloud_provider_suffix(candidate.raw_signal)
            if len(chosen_parts) >= 4:
                break
    ordered_parts = _order_theme_parts(chosen_parts, role_title=role_title)
    specific_parts = [
        part
        for part in ordered_parts
        if ROLE_THEME_PART_LABELS.get(part, "") not in generic_anchor_labels
    ]
    if len(specific_parts) >= 3:
        ordered_parts = specific_parts
    selected_parts = ordered_parts[:3]
    if not selected_parts:
        return best_candidate.normalized_focus
    if (
        len(selected_parts) == 1
        and ROLE_THEME_PART_LABELS.get(selected_parts[0]) == "cloud"
        and provider_suffix is None
    ):
        return best_candidate.normalized_focus
    focus = _join_focus_phrases(selected_parts)
    if (
        provider_suffix is not None
        and any("cloud" in part.lower() for part in selected_parts)
        and provider_suffix.lower() not in focus.lower()
    ):
        focus = f"{focus} across {provider_suffix}"
    return _restore_focus_term_casing(focus)


def _select_role_theme_selection(
    step_3_payload: Mapping[str, Any],
    jd_text: str,
    *,
    step_4_payload: Mapping[str, Any] | None,
    step_6_payload: Mapping[str, Any] | None,
    role_title: str | None,
    growth_areas: Sequence[SenderGrowthArea],
    interest_areas: Sequence[SenderInterestArea],
) -> RoleThemeSelection | None:
    candidates = _build_role_theme_candidates(
        step_3_payload,
        jd_text,
        step_4_payload=step_4_payload,
        step_6_payload=step_6_payload,
        role_title=role_title,
        growth_areas=growth_areas,
        interest_areas=interest_areas,
    )
    if not candidates:
        return None
    ranked = sorted(candidates, key=lambda item: item.score, reverse=True)
    best_candidate = ranked[0]
    focus_phrase = _synthesize_role_theme_focus(
        best_candidate,
        ranked,
        role_title=role_title,
    )
    anchor_labels = tuple(
        sorted({label for candidate in ranked[:4] for label in candidate.anchor_labels})
    )
    growth_area_label = next(
        (
            candidate.growth_area_label
            for candidate in ranked
            if candidate.growth_area_label is not None
        ),
        None,
    )
    growth_overlap = any(candidate.growth_score > 0 for candidate in ranked[:3])
    provisional_selection = RoleThemeSelection(
        focus_phrase=focus_phrase,
        role_family=best_candidate.role_family,
        anchor_labels=anchor_labels,
        source_signals=tuple(candidate.raw_signal for candidate in ranked[:3]),
        background_overlap=False,
        direct_background_overlap=False,
        adjacent_background_overlap=False,
        growth_overlap=growth_overlap,
        growth_area_label=growth_area_label,
        interest_overlap=False,
        interest_area_label=None,
        interest_overlap_sentence=None,
        interest_snippet_sentence=None,
        overlap_sentence="",
    )
    interest_score, matched_interest_area = _match_interest_area(
        provisional_selection.focus_phrase,
        source_text=" ".join(provisional_selection.source_signals),
        role_title=role_title,
        anchor_labels=provisional_selection.anchor_labels,
        interest_areas=interest_areas,
    )
    interest_overlap = interest_score > 0
    interest_area_label = matched_interest_area.label if matched_interest_area is not None else None
    interest_overlap_sentence = (
        matched_interest_area.interest_overlap_sentence if matched_interest_area is not None else None
    )
    interest_snippet_sentence = (
        _format_interest_snippet_sentence(
            matched_interest_area.snippet_interest_sentence,
            focus=provisional_selection.focus_phrase,
        )
        if matched_interest_area is not None
        else None
    )
    direct_background_overlap = (
        _score_theme_direct_background_overlap(
            provisional_selection,
            step_4_payload=step_4_payload,
            step_6_payload=step_6_payload,
        )
        > 0
    )
    adjacent_background_overlap = (
        not direct_background_overlap
        and _score_transferable_background_overlap(
            step_4_payload=step_4_payload,
            step_6_payload=step_6_payload,
        )
        > 0
    )
    background_overlap = direct_background_overlap or adjacent_background_overlap
    return RoleThemeSelection(
        focus_phrase=provisional_selection.focus_phrase,
        role_family=provisional_selection.role_family,
        anchor_labels=provisional_selection.anchor_labels,
        source_signals=provisional_selection.source_signals,
        background_overlap=background_overlap,
        direct_background_overlap=direct_background_overlap,
        adjacent_background_overlap=adjacent_background_overlap,
        growth_overlap=provisional_selection.growth_overlap,
        growth_area_label=provisional_selection.growth_area_label,
        interest_overlap=interest_overlap,
        interest_area_label=interest_area_label,
        interest_overlap_sentence=interest_overlap_sentence,
        interest_snippet_sentence=interest_snippet_sentence,
        overlap_sentence=_theme_overlap_sentence(
            RoleThemeSelection(
                focus_phrase=provisional_selection.focus_phrase,
                role_family=provisional_selection.role_family,
                anchor_labels=provisional_selection.anchor_labels,
                source_signals=provisional_selection.source_signals,
                background_overlap=background_overlap,
                direct_background_overlap=direct_background_overlap,
                adjacent_background_overlap=adjacent_background_overlap,
                growth_overlap=provisional_selection.growth_overlap,
                growth_area_label=provisional_selection.growth_area_label,
                interest_overlap=interest_overlap,
                interest_area_label=interest_area_label,
                interest_overlap_sentence=interest_overlap_sentence,
                interest_snippet_sentence=interest_snippet_sentence,
                overlap_sentence="",
            ),
            growth_areas,
        ),
    )


def _theme_overlap_sentence(
    theme_selection: RoleThemeSelection,
    growth_areas: Sequence[SenderGrowthArea],
) -> str:
    matched_area = next(
        (
            area
            for area in growth_areas
            if area.label == theme_selection.growth_area_label
        ),
        None,
    )
    if matched_area is not None:
        if theme_selection.direct_background_overlap and theme_selection.growth_overlap:
            return matched_area.combined_overlap_sentence
        if theme_selection.direct_background_overlap:
            return matched_area.background_overlap_sentence
        if theme_selection.interest_overlap and theme_selection.interest_overlap_sentence is not None:
            return theme_selection.interest_overlap_sentence
        if theme_selection.adjacent_background_overlap and theme_selection.growth_overlap:
            return (
                "I see a real overlap with the systems work I've done, and "
                f"{_growth_sentence_to_clause(matched_area.growth_overlap_sentence)}."
            )
        if theme_selection.adjacent_background_overlap:
            return "I see a real overlap with the systems work I've done."
        if theme_selection.growth_overlap:
            return matched_area.growth_overlap_sentence
    label = ROLE_THEME_SENTENCE_LABELS.get(theme_selection.role_family or "", "systems")
    if theme_selection.direct_background_overlap and theme_selection.growth_overlap:
        return f"That lines up well with the kind of {label} work I've done and want to keep growing in."
    if theme_selection.direct_background_overlap:
        return f"That lines up with the kind of {label} work I've been doing."
    if theme_selection.interest_overlap and theme_selection.interest_overlap_sentence is not None:
        return theme_selection.interest_overlap_sentence
    if theme_selection.adjacent_background_overlap and theme_selection.growth_overlap:
        return (
            "I see a real overlap with the systems work I've done, and "
            f"it's the kind of {label} work I want to keep growing in."
        )
    if theme_selection.adjacent_background_overlap:
        return "I see a real overlap with the systems work I've done."
    return f"That is the kind of {label} work I want to keep growing in."


def _growth_sentence_to_clause(growth_sentence: str) -> str:
    stripped = growth_sentence.strip().rstrip(".")
    lowered = stripped.lower()
    if lowered.startswith("that is "):
        return "it's " + stripped[8:]
    if lowered.startswith("that lines up "):
        return "it lines up " + stripped[14:]
    return stripped[:1].lower() + stripped[1:] if stripped else "it's a direction I want to keep growing in"


def _select_theme_aligned_proof_point(
    step_6_payload: Mapping[str, Any],
    *,
    theme_selection: RoleThemeSelection,
) -> str | None:
    bullets = list((step_6_payload.get("software_engineer") or {}).get("bullets") or [])
    if not bullets:
        return None
    target_terms = _anchor_keywords(theme_selection.anchor_labels) | _tokenize_role_theme_text(
        theme_selection.focus_phrase
    )
    if not target_terms:
        return _select_proof_point(step_6_payload)
    candidate_entries: list[tuple[int, int, int, str]] = []
    purpose_rank = {
        "scale-impact": 0,
        "optimization": 1,
        "end-to-end-flow": 2,
        "reliability-operations": 3,
    }
    for entry in bullets:
        text = _normalize_optional_text(entry.get("text"))
        if text is None:
            continue
        overlap = target_terms & _tokenize_role_theme_text(text)
        metric_bonus = 2 if METRIC_RE.search(text) else 0
        candidate_entries.append(
            (
                len(overlap) * 5 + metric_bonus,
                -purpose_rank.get(_normalize_optional_text(entry.get("purpose")) or "", 99),
                -len(text),
                text,
            )
        )
    candidate_entries.sort(reverse=True)
    if candidate_entries and candidate_entries[0][0] > 0:
        return candidate_entries[0][3]
    return _select_proof_point(step_6_payload)


def _role_work_area(step_3_payload: Mapping[str, Any], jd_text: str) -> str | None:
    selection = _select_role_theme_selection(
        step_3_payload,
        jd_text,
        step_4_payload=None,
        step_6_payload=None,
        role_title=None,
        growth_areas=(),
        interest_areas=(),
    )
    return None if selection is None else selection.focus_phrase


def _select_role_work_area(
    step_3_payload: Mapping[str, Any],
    jd_text: str,
    *,
    step_4_payload: Mapping[str, Any] | None,
    step_6_payload: Mapping[str, Any] | None,
    role_title: str | None,
    growth_areas: Sequence[SenderGrowthArea] = (),
    interest_areas: Sequence[SenderInterestArea] = (),
) -> str | None:
    selection = _select_role_theme_selection(
        step_3_payload,
        jd_text,
        step_4_payload=step_4_payload,
        step_6_payload=step_6_payload,
        role_title=role_title,
        growth_areas=growth_areas,
        interest_areas=interest_areas,
    )
    return None if selection is None else selection.focus_phrase


def _clean_role_signal(value: str) -> str | None:
    cleaned = re.sub(r"^\s*[-*]\s*", "", value.strip())
    cleaned = re.sub(r"\s+", " ", cleaned.rstrip("."))
    stripped_original = cleaned
    focus_marker = re.search(
        r"\b(?:you will focus primarily on|focus primarily on|will focus on)\b",
        cleaned,
        flags=re.IGNORECASE,
    )
    if focus_marker is not None:
        cleaned = cleaned[focus_marker.end():].strip()
        stripped_original = cleaned
    cleaned = re.sub(
        r"^[A-Za-z][A-Za-z0-9 &/()+.\-]{0,40}:\s+",
        "",
        cleaned,
    )
    cleaned = re.sub(
        r"^\d+\+?(?:\s*[-–]\s*\d+)?\s+years?\s+of\s+"
        r"(?:(?:professional|hands-on)\s+)*experience(?:\s+(?:with|in|building))?\s+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"^\d+\+?(?:\s*[-–]\s*\d+)?\s+years?\s+"
        r"(?:(?:building|working\s+with|working\s+on|supporting|designing|developing|implementing)\s+)",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"^As a .*?,\s+you(?:'|’)ll\s+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"^as a [^,]+,\s+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"^(?:experience with|experience in|experience building|building|build|developing|develop|designing|design|working on|work on)\s+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"^(?:at least one programming language like|one or more programming languages such as)\s+.+?\s+\bto\b\s+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"^(?:developing|working)\s+in\s+programming languages such as\s+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"^(?:additional tools such as|tools such as|programming languages such as)\s+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"^(?:design/build/test|design, build, test|design and build|build and maintain|build and support)\s+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    if cleaned.lower().startswith(("and ", "or ")):
        cleaned = stripped_original
    cleaned = re.sub(
        r"^(?:strong proficiency in|solid understanding of|hands-on experience with|proficiency in|understanding of|basic understanding of|basic knowledge of|working knowledge of|knowledge of|familiarity with)\s+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\s*\(\d+\s+years?\)\s*$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*\(\d+\s+year\)\s*$", "", cleaned, flags=re.IGNORECASE)
    if not cleaned:
        return None
    normalized = cleaned.lower()
    if _is_ineligible_role_signal_text(cleaned):
        return None
    if any(pattern.search(normalized) for pattern in ROLE_SIGNAL_BOILERPLATE_PATTERNS):
        return None
    if any(pattern.search(normalized) for pattern in ROLE_SIGNAL_NONTECHNICAL_PATTERNS):
        return None
    if len(cleaned) > 260 and cleaned.count(".") + cleaned.count(";") >= 1:
        return None
    first_word, _, remainder = cleaned.partition(" ")
    gerund = ROLE_SIGNAL_VERB_PREFIXES.get(first_word.lower())
    if gerund is not None:
        cleaned = f"{gerund} {remainder}".strip()
    if (
        cleaned
        and not (len(cleaned) > 1 and cleaned[:2].isupper())
        and first_word.lower() not in ROLE_SIGNAL_LEADING_CASE_EXCEPTIONS
    ):
        cleaned = cleaned[:1].lower() + cleaned[1:]
    return cleaned or None


def _score_role_signal_for_opener(
    cleaned_signal: str,
    *,
    raw_signal: str,
    role_title: str | None,
    source_kind: str,
    step_4_payload: Mapping[str, Any] | None,
) -> int:
    if _fails_role_title_specific_gate(cleaned_signal, role_title):
        return 0
    technical_score = _role_signal_technical_priority(cleaned_signal, raw_signal)
    if technical_score <= 0:
        return 0
    specificity_score = _score_role_signal_specificity(cleaned_signal, raw_signal)
    if specificity_score <= 0:
        return 0
    title_score = _score_role_signal_title_alignment(cleaned_signal, role_title)
    evidence_score = _score_jd_signal_evidence_overlap(raw_signal, step_4_payload)
    return (
        technical_score * 100
        + specificity_score * 25
        + title_score * 20
        + ROLE_SIGNAL_SOURCE_PRIORITY.get(source_kind, 0) * 10
        + evidence_score * 5
    )


def _is_ineligible_role_signal_text(value: str) -> bool:
    normalized = value.strip()
    lowered = normalized.lower()
    if any(pattern.search(lowered) for pattern in ROLE_SIGNAL_INELIGIBLE_PATTERNS):
        return True
    if normalized.endswith("!") and len(normalized.split()) <= 8 and not _extract_role_focus_anchors(normalized):
        return True
    return False


def _role_signal_technical_priority(cleaned_signal: str, raw_signal: str) -> int:
    scores: list[int] = []
    for candidate in (cleaned_signal, raw_signal):
        lowered = candidate.lower()
        scores.extend(
            weight
            for pattern, weight in ROLE_SIGNAL_TECHNICAL_PRIORITY_PATTERNS
            if pattern.search(lowered)
        )
    return max(scores) if scores else 0


def _extract_role_focus_anchors(value: str) -> set[str]:
    anchors: set[str] = set()
    for pattern, label in ROLE_SIGNAL_FOCUS_ANCHOR_PATTERNS:
        if pattern.search(value):
            anchors.add(label)
    return anchors


def _score_role_signal_specificity(cleaned_signal: str, raw_signal: str) -> int:
    anchors = _extract_role_focus_anchors(cleaned_signal) | _extract_role_focus_anchors(raw_signal)
    if not anchors:
        return 0
    if any(pattern.search(cleaned_signal) for pattern in ROLE_SIGNAL_GENERIC_FOCUS_PATTERNS) and len(anchors) < 2:
        return 0
    return len(anchors) + (1 if len(cleaned_signal.split()) <= 12 else 0)


def _score_role_signal_title_alignment(cleaned_signal: str, role_title: str | None) -> int:
    normalized_title = _normalize_optional_text(role_title)
    if normalized_title is None:
        return 0
    lowered_title = normalized_title.lower()
    lowered_signal = cleaned_signal.lower()
    score = 0
    for title_pattern, keywords in ROLE_SIGNAL_TITLE_THEME_PATTERNS:
        if not title_pattern.search(lowered_title):
            continue
        if any(keyword in lowered_signal for keyword in keywords):
            score += 1
    return score


def _fails_role_title_specific_gate(cleaned_signal: str, role_title: str | None) -> bool:
    normalized_title = _normalize_optional_text(role_title)
    if normalized_title is None:
        return False
    lowered_title = normalized_title.lower()
    lowered_signal = cleaned_signal.lower()
    gates: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
        (("cloud",), ("cloud", "aws", "gcp", "azure", "pcf", "hybrid-cloud", "application", "applications", "infrastructure", "platform")),
        (("security",), ("security", "secure", "identity")),
        (("robotics", "robotic"), ("robotic", "robotics", "ros", "motion", "sensor", "automation")),
        (("backend",), ("backend", "api", "apis", "microservice", "distributed", "rest")),
        (("scheduler", "scheduling"), ("scheduler", "scheduling", "real-time", "control systems")),
        (("data", "analytics"), ("data", "spark", "pipeline", "pipelines", "analytics", "etl")),
    )
    for title_tokens, required_tokens in gates:
        if not any(token in lowered_title for token in title_tokens):
            continue
        return not any(token in lowered_signal for token in required_tokens)
    return False


def _score_jd_signal_evidence_overlap(
    raw_signal: str,
    step_4_payload: Mapping[str, Any] | None,
) -> int:
    if step_4_payload is None:
        return 0
    matches = step_4_payload.get("matches")
    if not isinstance(matches, list):
        return 0
    confidence_weight = {"high": 4, "medium": 2, "low": 1}
    score = 0
    normalized_raw_signal = raw_signal.strip()
    for match in matches:
        if not isinstance(match, Mapping):
            continue
        if _normalize_optional_text(match.get("jd_signal")) != normalized_raw_signal:
            continue
        confidence = (_normalize_optional_text(match.get("confidence")) or "").lower()
        score += confidence_weight.get(confidence, 1)
        source_excerpt = (_normalize_optional_text(match.get("source_excerpt")) or "").lower()
        if METRIC_RE.search(source_excerpt):
            score += 2
        if any(
            token in source_excerpt
            for token in (
                "microservice",
                "backend api",
                "distributed",
                "throughput",
                "uptime",
                "java",
                "aws",
                "kubernetes",
            )
        ):
            score += 1
    return score


def _determine_opener_claim_mode(theme_selection: RoleThemeSelection) -> str:
    if theme_selection.direct_background_overlap:
        return CLAIM_MODE_DIRECT_BACKGROUND
    if theme_selection.interest_overlap:
        return CLAIM_MODE_INTEREST_AREA
    if theme_selection.adjacent_background_overlap:
        return CLAIM_MODE_ADJACENT_OVERLAP
    return CLAIM_MODE_GROWTH_AREA


def _compose_role_targeted_role_theme_from_values(
    *,
    role_title: str,
    work_area: str | None,
    role_intent_summary: str | None,
    jd_text: str,
) -> str:
    source_parts = [
        role_title,
        _normalize_optional_text(work_area),
        _normalize_optional_text(role_intent_summary),
    ]
    if not any(source_parts[1:]):
        source_parts.append(jd_text[:2000])
    source = " ".join(value for value in source_parts if value).lower()
    if any(
        token in source
        for token in (
            "information security",
            "security engineer",
            "enterprise security",
            "application security",
            "cloud security",
            "cybersecurity",
            "cyber security",
            "secure infrastructure",
            "intel federal",
            "government information security",
            "government-focused security",
        )
    ):
        return "enterprise security systems, secure infrastructure, and government-focused security work"
    if any(token in source for token in ("scheduler", "scheduling", "scheduling engines")):
        return "engineering leadership and real-time scheduling systems"
    if any(token in source for token in ("platform", "cloud", "infrastructure")) and any(
        token in source
        for token in ("backend", "distributed", "api", "microservice", "container", "automation")
    ):
        return "cloud infrastructure, backend systems, and platform engineering"
    if any(token in source for token in ("distributed", "grpc", "load balancing")):
        return "backend systems, distributed services, and production delivery"
    if any(token in source for token in ("event-driven", "metadata", "documents", "document", "python")):
        return "production Python services, backend systems, and distributed processing"
    if "backend" in source:
        return "backend systems and APIs"
    if any(token in source for token in ("platform", "cloud", "infrastructure")):
        return "cloud infrastructure, platform systems, and production engineering"
    candidate = _role_work_area_phrase(work_area or role_intent_summary)
    if len(candidate.split()) <= 8 and " " in candidate:
        return candidate
    return "backend systems, distributed services, and production engineering"


def _compose_role_targeted_technical_focus_from_values(
    *,
    role_title: str,
    work_area: str | None,
    role_intent_summary: str | None,
    fallback_role_theme: str,
) -> str:
    preserved_focus = _normalize_optional_text(work_area)
    if preserved_focus is not None:
        return _restore_focus_term_casing(preserved_focus.strip(" ,.;"))
    for raw_value in (role_intent_summary,):
        normalized_focus = _normalize_technical_focus_phrase(raw_value, role_title=role_title)
        if normalized_focus is not None:
            return normalized_focus
    return fallback_role_theme


def _build_role_targeted_opener_decision(
    *,
    company_name: str,
    role_title: str,
    jd_text: str,
    role_intent_summary: str | None,
    theme_selection: RoleThemeSelection,
) -> RoleTargetedOpenerDecision:
    role_theme = _compose_role_targeted_role_theme_from_values(
        role_title=role_title,
        work_area=theme_selection.focus_phrase,
        role_intent_summary=role_intent_summary,
        jd_text=jd_text,
    )
    technical_focus = _compose_role_targeted_technical_focus_from_values(
        role_title=role_title,
        work_area=theme_selection.focus_phrase,
        role_intent_summary=role_intent_summary,
        fallback_role_theme=role_theme,
    )
    claim_mode = _determine_opener_claim_mode(theme_selection)
    rationale: list[str] = [
        f"Selected theme `{technical_focus}` from JD-grounded signals aligned to role `{role_title}`.",
        f"Claim mode classified as `{claim_mode}`.",
    ]
    if theme_selection.growth_area_label is not None:
        rationale.append(f"Matched growth area `{theme_selection.growth_area_label}`.")
    if theme_selection.interest_area_label is not None:
        rationale.append(f"Matched interest area `{theme_selection.interest_area_label}`.")
    return RoleTargetedOpenerDecision(
        role_title=role_title,
        company_name=company_name,
        role_theme=role_theme,
        technical_focus=technical_focus,
        claim_mode=claim_mode,
        overlap_sentence=theme_selection.overlap_sentence,
        source_signals=theme_selection.source_signals,
        growth_area_label=theme_selection.growth_area_label,
        interest_area_label=theme_selection.interest_area_label,
        rationale=tuple(rationale),
    )


def _build_role_targeted_subject(context: RoleTargetedDraftContext) -> str:
    return f"Interest in the {context.role_title} role at {context.company_name}"


def _compose_role_targeted_composition_plan(
    context: RoleTargetedDraftContext,
) -> RoleTargetedCompositionPlan:
    proof_point = context.proof_point or (
        "the distributed systems work I have done across reliability, performance, and production delivery"
    )
    opener_inputs = _compose_role_targeted_opener_inputs(context)
    plan = RoleTargetedCompositionPlan(
        opener_paragraph=_render_role_targeted_opener(opener_inputs),
        background_paragraph=(
            f"{_build_role_targeted_why_line(context)} "
            f"{_proof_point_sentence(proof_point)}"
        ),
        copilot_paragraphs=tuple(_job_hunt_copilot_pitch_lines()),
        ask_paragraph=(
            "If it would be useful, I would welcome a short 15-minute conversation sometime this or next week "
            "to learn a bit more about the role and get your perspective on whether my background could be relevant. "
            "If you're not the right person, I'd also really appreciate it if you could point me to the right "
            "person or forward my resume internally."
        ),
        snippet_text=_render_forwardable_snippet_text(context),
    )
    _validate_role_targeted_composition_plan(plan, context)
    return plan


def _compose_role_targeted_opener_inputs(
    context: RoleTargetedDraftContext,
) -> RoleTargetedOpenerInputs:
    return RoleTargetedOpenerInputs(
        company_name=context.company_name,
        role_title=context.role_title,
        technical_focus=context.opener_decision.technical_focus,
        overlap_sentence=context.opener_decision.overlap_sentence,
    )


def _render_role_targeted_opener(inputs: RoleTargetedOpenerInputs) -> str:
    return (
        f"I'm reaching out about the {inputs.role_title} role at {inputs.company_name} because I was "
        f"interested in the role's focus on {inputs.technical_focus}. {inputs.overlap_sentence}"
    )


def _build_role_targeted_why_line(context: RoleTargetedDraftContext) -> str:
    title = _normalize_optional_text(context.position_title)
    if context.recipient_type == RECIPIENT_TYPE_RECRUITER:
        if title is not None:
            return f"Given your role as {title}, I thought you might have useful perspective on the hiring context for this opening."
        return "I thought you might have useful perspective on the hiring context for this opening."
    if context.recipient_type == RECIPIENT_TYPE_HIRING_MANAGER:
        if title is not None:
            return f"Given your role as {title}, I thought you might be a good person to reach out to for some perspective on this opening."
        return "I thought you might be a good person to reach out to for some perspective on this opening."
    if context.recipient_type == RECIPIENT_TYPE_ALUMNI:
        return (
            "I'm reaching out to you specifically because you seemed like the right fellow Sun Devil to ask for a grounded perspective on this work."
        )
    if title is not None:
        return f"Given your role as {title}, I thought you might have useful perspective on the day-to-day work this role touches."
    return "I thought you might have useful perspective on the day-to-day work this role touches."


def _recipient_work_signal(recipient_profile: Mapping[str, Any] | None) -> str | None:
    if recipient_profile is None:
        return None
    work_signals = recipient_profile.get("work_signals")
    if isinstance(work_signals, list):
        for signal in work_signals:
            normalized = _normalize_optional_text(signal)
            if normalized is not None:
                return normalized
    about_preview = _normalize_optional_text(
        (recipient_profile.get("about") or {}).get("preview_text")
        if isinstance(recipient_profile.get("about"), Mapping)
        else None
    )
    if about_preview is not None:
        return about_preview
    top_card = recipient_profile.get("top_card")
    if isinstance(top_card, Mapping):
        for key in ("headline", "current_title"):
            normalized = _normalize_optional_text(top_card.get(key))
            if normalized is not None:
                return normalized
    return None


def _impact_summary_line(context: RoleTargetedDraftContext) -> str:
    proof_point = context.proof_point or "credible impact across backend and distributed systems work"
    return proof_point.rstrip(".")


def _snippet_focus_phrase(context: RoleTargetedDraftContext) -> str:
    role_theme = _compose_role_targeted_role_theme(context)
    technical_focus = _compose_role_targeted_technical_focus(context, role_theme)
    focus = _normalize_optional_text(technical_focus) or role_theme
    compact_focus = _compact_focus_for_snippet(focus, role_title=context.role_title)
    return compact_focus or focus or role_theme


def _snippet_focus_preposition(focus: str) -> str:
    lowered = focus.lower()
    if "," in focus:
        return "with"
    if any(
        lowered.startswith(prefix)
        for prefix in (
            "java",
            "python",
            "scala",
            "kotlin",
            "c#",
            ".net",
            "aws",
            "azure",
            "gcp",
            "spring",
            "angular",
            "react",
            "restful",
            "backend services and apis",
            "full-stack services and backend apis",
        )
    ):
        return "with"
    return "in"


def _snippet_proof_fragment(context: RoleTargetedDraftContext) -> str | None:
    proof = _normalize_optional_text(context.proof_point)
    if proof is None:
        return None
    candidate = proof.rstrip(".")
    candidate = re.sub(
        r"\band automating high-volume clinical data flows that powered\b",
        "supporting",
        candidate,
        flags=re.IGNORECASE,
    )
    candidate = re.sub(r"\s+", " ", candidate).strip(" ,.;")
    first_word, _, remainder = candidate.partition(" ")
    gerund = ROLE_SIGNAL_VERB_PREFIXES.get(first_word.lower())
    if gerund is None:
        gerund = {
            "built": "building",
            "designed": "designing",
            "developed": "developing",
            "implemented": "implementing",
            "optimized": "optimizing",
            "led": "leading",
            "created": "creating",
            "improved": "improving",
            "shipped": "shipping",
            "migrated": "migrating",
            "automated": "automating",
            "scaled": "scaling",
            "owned": "owning",
            "processed": "processing",
            "ran": "running",
            "delivered": "delivering",
        }.get(first_word.lower())
    if gerund is not None:
        candidate = f"{gerund} {remainder}".strip()
    return candidate or None


def _snippet_intro_sentence(context: RoleTargetedDraftContext) -> str:
    if context.recipient_type in {RECIPIENT_TYPE_HIRING_MANAGER, RECIPIENT_TYPE_FOUNDER}:
        return (
            f"Hi, passing along a candidate who may be worth a look for the "
            f"{context.role_title} role at {context.company_name}."
        )
    return (
        f"Hi, sharing a candidate who may be relevant for the "
        f"{context.role_title} role at {context.company_name}."
    )


def _snippet_background_sentence(context: RoleTargetedDraftContext) -> str:
    focus = _snippet_focus_phrase(context)
    preposition = _snippet_focus_preposition(focus)
    proof_fragment = _snippet_proof_fragment(context)
    if context.theme_selection.interest_overlap and not context.theme_selection.direct_background_overlap:
        sentence = (
            context.theme_selection.interest_snippet_sentence
            or f"He's actively building toward the role's focus on {focus} through academic and personal projects."
        ).rstrip(".")
        if proof_fragment is not None:
            return f"{sentence}, while bringing supporting systems experience including {proof_fragment}."
        return f"{sentence}."
    if context.theme_selection.adjacent_background_overlap and not context.theme_selection.direct_background_overlap:
        if context.theme_selection.growth_overlap:
            sentence = (
                f"His background overlaps well with the role's focus on {focus}, and he's intentionally "
                "growing in that direction"
            )
        else:
            sentence = f"His background overlaps well with the role's focus on {focus}"
        if proof_fragment is not None:
            return f"{sentence}, including {proof_fragment}."
        return f"{sentence}."
    if context.recipient_type in {
        RECIPIENT_TYPE_HIRING_MANAGER,
        RECIPIENT_TYPE_ENGINEER,
        RECIPIENT_TYPE_FOUNDER,
    }:
        if preposition == "with":
            prefix = "His background includes work with"
        else:
            prefix = "His background is in"
    else:
        if preposition == "with":
            prefix = "He has experience with"
        else:
            prefix = "He has experience in"
    if proof_fragment is not None:
        return f"{prefix} {focus}, including {proof_fragment}."
    return f"{prefix} {focus}."


def _role_work_area_phrase(value: str | None) -> str:
    normalized = _normalize_optional_text(value)
    if normalized is None:
        return "backend and distributed systems work"
    cleaned = normalized.strip(" .,:;")
    lowered = cleaned.lower()
    for prefix in ("and ", "to ", "help ", "able to "):
        if lowered.startswith(prefix):
            cleaned = cleaned[len(prefix):].strip(" .,:;")
            lowered = cleaned.lower()
    for marker in (
        ", based on definitions from more senior roles",
        " based on definitions from more senior roles",
        "; based on definitions from more senior roles",
    ):
        position = lowered.find(marker)
        if position >= 0:
            cleaned = cleaned[:position].strip(" .,:;")
            lowered = cleaned.lower()
    if ";" in cleaned:
        parts = [part.strip(" .,:;") for part in cleaned.split(";") if part.strip(" .,:;")]
        if parts:
            cleaned = parts[-1]
            lowered = cleaned.lower()
    return cleaned or "backend and distributed systems work"


def _compose_role_targeted_role_theme(context: RoleTargetedDraftContext) -> str:
    return context.opener_decision.role_theme


def _compose_role_targeted_technical_focus(
    context: RoleTargetedDraftContext,
    role_theme: str,
) -> str:
    _ = role_theme
    return context.opener_decision.technical_focus


def _join_focus_phrases(parts: Sequence[str]) -> str:
    cleaned = [part.strip(" ,.;") for part in parts if part.strip(" ,.;")]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    if len(cleaned) == 2:
        return f"{cleaned[0]} and {cleaned[1]}"
    return ", ".join(cleaned[:-1]) + f", and {cleaned[-1]}"


def _looks_like_technology_focus_list(value: str) -> bool:
    lowered = value.lower()
    if re.search(
        r"\b(?:designing|deploying|managing|developing|creating|implementing)\b,\s+"
        r"\b(?:designing|deploying|managing|developing|creating|implementing)\b",
        lowered,
    ):
        return False
    if "cloud solutions using" in lowered or "applications using frameworks" in lowered:
        return False
    if any(
        marker in lowered
        for marker in (
            "backend work will include",
            "frontend work will include",
            "technologies such as",
            "as well as html",
            "as well as css",
            "as well as javascript",
            "as well as bootstrap",
        )
    ):
        return True
    tech_term_hits = sum(
        1
        for term in (
            "java",
            "scala",
            "kotlin",
            "restful",
            "spring",
            "angular",
            "html",
            "css",
            "javascript",
            "bootstrap",
            "docker",
            "kubernetes",
            "aws",
            "gcp",
            "azure",
        )
        if term in lowered
    )
    return value.count(",") >= 3 and tech_term_hits >= 3


def _summarize_technical_focus_enumeration(candidate: str) -> str:
    normalized = re.sub(r"\band\b", ",", candidate, flags=re.IGNORECASE)
    raw_parts = [part.strip(" ,.;") for part in normalized.split(",") if part.strip(" ,.;")]
    if len(raw_parts) <= 4:
        return candidate

    selected: list[str] = []
    for part in raw_parts:
        lowered = part.lower()
        if lowered in {"backend work will include", "frontend work will include", "technologies such as"}:
            continue
        if lowered.startswith("containerization technologies"):
            part = "containerization technologies"
        elif lowered == "restful":
            part = "RESTful services"
        if part not in selected:
            selected.append(part)

    if not selected:
        return candidate

    preferred_order = [
        "angular",
        "html",
        "css",
        "javascript",
        "bootstrap",
        "java",
        "scala",
        "restful services",
        "spring",
        "kotlin",
        "aws",
        "gcp",
        "azure",
        "docker",
        "kubernetes",
        "containerization technologies",
    ]
    preferred: list[str] = []
    for term in preferred_order:
        for part in selected:
            if part.lower() == term and part not in preferred:
                preferred.append(part)
    if preferred:
        selected = preferred + [part for part in selected if part not in preferred]

    if "containerization technologies" in selected and len(selected) > 4:
        selected = [part for part in selected if part != "containerization technologies"][:3] + [
            "containerization technologies"
        ]
    else:
        selected = selected[:4]

    summary = _join_focus_phrases(selected)
    return summary or candidate


def _focus_summary_parts(value: str) -> list[str]:
    parts: list[str] = []
    for pattern, summary in ROLE_SIGNAL_SUMMARY_GROUPS:
        if pattern.search(value) and summary not in parts:
            parts.append(summary)
    return parts


def _compact_focus_for_snippet(focus: str | None, *, role_title: str | None) -> str | None:
    normalized = _normalize_technical_focus_phrase(focus, role_title=role_title)
    if normalized is None:
        return None
    if len(normalized.split()) <= 10:
        return normalized
    summarized = _summarize_long_technical_focus_phrase(normalized, role_title=role_title)
    return summarized or normalized


def _summarize_long_technical_focus_phrase(candidate: str, *, role_title: str | None) -> str | None:
    parts = _focus_summary_parts(candidate)
    if not parts:
        return None
    if role_title and "full stack" in role_title.lower():
        parts = [part for part in parts if part != "backend APIs and services"] or parts
    summary = _join_focus_phrases(parts[:3]) or None
    if summary is None:
        return None
    return _restore_focus_term_casing(summary)


def _restore_focus_term_casing(candidate: str) -> str:
    replacements = (
        (r"\bjava\b", "Java"),
        (r"\bscala\b", "Scala"),
        (r"\bkotlin\b", "Kotlin"),
        (r"\bpython\b", "Python"),
        (r"\bgolang\b", "Golang"),
        (r"\bgraphql\b", "GraphQL"),
        (r"\brest apis\b", "REST APIs"),
        (r"\bspark\b", "Spark"),
        (r"\baws\b", "AWS"),
        (r"\bgcp\b", "GCP"),
        (r"\bazure\b", "Azure"),
        (r"\bpcf\b", "PCF"),
        (r"\bterraform\b", "Terraform"),
        (r"\bdevsecops\b", "DevSecOps"),
        (r"\bci/cd\b", "CI/CD"),
        (r"\bai/ml\b", "AI/ML"),
        (r"\bllm\b", "LLM"),
        (r"\brestful services\b", "RESTful services"),
        (r"\bapi gateway\b", "API gateway"),
    )
    normalized = candidate
    for pattern, replacement in replacements:
        normalized = re.sub(pattern, replacement, normalized, flags=re.IGNORECASE)
    return normalized


def _normalize_technical_focus_phrase(value: str | None, *, role_title: str | None) -> str | None:
    normalized = _normalize_optional_text(value)
    if normalized is None:
        return None
    candidate = _clean_role_signal(normalized)
    if candidate is None:
        lowered_normalized = normalized.lower()
        if _is_ineligible_role_signal_text(normalized):
            return None
        if any(pattern.search(lowered_normalized) for pattern in ROLE_SIGNAL_BOILERPLATE_PATTERNS):
            return None
        if any(pattern.search(lowered_normalized) for pattern in ROLE_SIGNAL_NONTECHNICAL_PATTERNS):
            return None
        candidate = _role_work_area_phrase(normalized)
    candidate = _role_work_area_phrase(candidate)
    first_word, _, remainder = candidate.partition(" ")
    gerund = ROLE_SIGNAL_VERB_PREFIXES.get(first_word.lower())
    if gerund is not None:
        candidate = f"{gerund} {remainder}".strip()
    candidate = re.sub(
        r"\busing agile methodologies and devops principles\b.*$",
        "",
        candidate,
        flags=re.IGNORECASE,
    )
    candidate = re.sub(
        r"\bto improve and grow\b.*$",
        "",
        candidate,
        flags=re.IGNORECASE,
    )
    candidate = re.sub(
        r"\bwith a constant focus on security\b.*$",
        "",
        candidate,
        flags=re.IGNORECASE,
    )
    candidate = re.sub(
        r"^(?:backend|frontend)\s+work\s+will\s+include(?:\s+project\s+heavily\s+using|\s+technologies\s+such\s+as)?\s+",
        "",
        candidate,
        flags=re.IGNORECASE,
    )
    candidate = re.sub(
        r"\btechnologies such as\b",
        "",
        candidate,
        flags=re.IGNORECASE,
    )
    candidate = re.sub(
        r"\bas well as\b",
        ",",
        candidate,
        flags=re.IGNORECASE,
    )
    candidate = re.sub(
        r"\bto deliver\b.*$",
        "",
        candidate,
        flags=re.IGNORECASE,
    )
    candidate = re.sub(
        r"\bwith an emphasis on\b.*$",
        "",
        candidate,
        flags=re.IGNORECASE,
    )
    candidate = re.sub(
        r"\bRESTful\b(?!\s+services)",
        "RESTful services",
        candidate,
        flags=re.IGNORECASE,
    )
    candidate = re.sub(r"\s*\(\d+\s+years?\)\s*$", "", candidate, flags=re.IGNORECASE)
    candidate = re.sub(r"\s*\(\d+\s+year\)\s*$", "", candidate, flags=re.IGNORECASE)
    candidate = re.sub(r"\s+", " ", candidate).strip(" ,.;")
    rewritten_ai_ml_focus = _rewrite_ai_ml_focus_phrase(candidate)
    if rewritten_ai_ml_focus is not None:
        candidate = rewritten_ai_ml_focus
    lowered_candidate = candidate.lower()
    if "cloud solutions" in lowered_candidate and any(
        token in lowered_candidate for token in ("aws", "gcp", "azure", "pcf")
    ):
        summarized_cloud = _summarize_long_technical_focus_phrase(candidate, role_title=role_title)
        if summarized_cloud is not None:
            candidate = summarized_cloud
    if _looks_like_technology_focus_list(candidate):
        candidate = _summarize_technical_focus_enumeration(candidate)
    if not candidate:
        return None
    if _is_ineligible_role_signal_text(candidate):
        return None
    if any(pattern.search(candidate) for pattern in ROLE_SIGNAL_GENERIC_FOCUS_PATTERNS):
        summarized_generic = _summarize_long_technical_focus_phrase(candidate, role_title=role_title)
        if summarized_generic is not None:
            candidate = summarized_generic
    if not candidate:
        return None
    if len(candidate.split()) > 18:
        summarized = _summarize_long_technical_focus_phrase(candidate, role_title=role_title)
        if summarized is None:
            return None
        candidate = summarized
    lowered = candidate.lower()
    if any(pattern.search(lowered) for pattern in ROLE_SIGNAL_BOILERPLATE_PATTERNS):
        return None
    if re.search(r"\b(?:identifies|develops|plans|implements|supports),\s", lowered):
        summarized = _summarize_long_technical_focus_phrase(candidate, role_title=role_title)
        if summarized is None:
            return None
        candidate = summarized
        lowered = candidate.lower()
    if not _extract_role_focus_anchors(candidate):
        return None
    return _restore_focus_term_casing(candidate)


def _rewrite_ai_ml_focus_phrase(candidate: str) -> str | None:
    lowered = candidate.lower()
    if (
        ("full cycle delivery" in lowered or "requirements/design to release" in lowered)
        and "ai/ml" in lowered
    ):
        return "full-cycle AI/ML delivery and AI/ML infrastructure evolution"
    if "production-level models and pipelines" in lowered:
        return "production-level AI/ML models and pipelines"
    if any(token in lowered for token in ("generative ai", "large language models", "llm")):
        return "production-ready generative AI and machine learning solutions"
    if "ai/ml operations" in lowered and "monitor" in lowered:
        return "AI/ML operations and model monitoring"
    return None


def _role_work_area_opening(work_area: str) -> str:
    lowered = work_area.lower()
    base_action_prefixes = (
        "build ",
        "design ",
        "develop ",
        "implement ",
        "improve ",
        "optimize ",
        "scale ",
        "modernize ",
        "create ",
        "lead ",
        "support ",
        "maintain ",
        "drive ",
        "own ",
        "extract ",
        "enrich ",
        "process ",
    )
    gerund_action_prefixes = (
        "building ",
        "designing ",
        "developing ",
        "implementing ",
        "improving ",
        "optimizing ",
        "scaling ",
        "modernizing ",
        "creating ",
        "leading ",
        "supporting ",
        "maintaining ",
        "driving ",
        "owning ",
        "extracting ",
        "enriching ",
        "processing ",
        "delivering ",
    )
    if lowered.startswith(base_action_prefixes):
        return f"the chance to {work_area}"
    if lowered.startswith(gerund_action_prefixes):
        return f"the chance to work on {work_area}"
    return f"the work around {work_area}"


def _ensure_sentence(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return ""
    if stripped.endswith((".", "!", "?")):
        return stripped
    return stripped + "."


def _proof_point_sentence(proof_point: str) -> str:
    stripped = proof_point.strip().rstrip(".")
    if not stripped:
        return "For example, I have worked on backend and distributed systems in production."
    lowered = stripped.lower()
    if lowered.startswith("i "):
        return f"In one recent role, {stripped}."
    verb_prefixes = (
        "built ",
        "designed ",
        "developed ",
        "implemented ",
        "optimized ",
        "led ",
        "created ",
        "improved ",
        "shipped ",
        "migrated ",
        "automated ",
        "scaled ",
        "reduced ",
        "owned ",
        "processed ",
        "ran ",
        "delivered ",
    )
    if lowered.startswith(verb_prefixes):
        return f"In one recent role, I {stripped[0].lower()}{stripped[1:]}."
    return f"For example, {stripped}."


def _compact_linkedin(value: str | None) -> str:
    if value is None:
        return "LinkedIn available on request"
    return re.sub(r"^https?://", "", value).rstrip("/")


def _signature_lines(sender: SenderIdentity) -> list[str]:
    lines: list[str] = []
    if sender.linkedin_url:
        lines.append(sender.linkedin_url)
    if sender.phone:
        lines.append(sender.phone)
    if sender.email:
        lines.append(sender.email)
    return lines


def _job_hunt_copilot_pitch_lines() -> list[str]:
    return [
        "Lately, I have been spending time sharpening my Agentic AI skills.",
        (
            f"I built Job Hunt Copilot ({JOB_HUNT_COPILOT_REPO_URL}) for my own job search "
            "to help me identify relevant roles and the right people to reach out to."
        ),
        (
            "The AI agent runs autonomously with human-in-the-loop (HITL) review, and I personally "
            "review every email before it goes out. This email is a live example of that workflow."
        ),
    ]


def _render_forwardable_snippet_text(context: RoleTargetedDraftContext) -> str:
    linkedin = _compact_linkedin(context.sender.linkedin_url)
    return " ".join(
        [
            _snippet_intro_sentence(context),
            _snippet_background_sentence(context),
            f"Profile: {linkedin}",
        ]
    )


def _validate_role_targeted_opener_decision(context: RoleTargetedDraftContext) -> None:
    decision = context.opener_decision
    rubric = context.opener_rubric
    if decision.claim_mode not in rubric.allowed_claim_modes:
        raise OutreachDraftingError(
            f"Opener decision uses unsupported claim mode `{decision.claim_mode}`."
        )
    lowered_focus = decision.technical_focus.lower()
    blocked_focus = next(
        (phrase for phrase in rubric.blocked_focus_phrases if phrase in lowered_focus),
        None,
    )
    if blocked_focus is not None:
        raise OutreachDraftingError(
            f"Opener decision technical focus `{decision.technical_focus}` contains blocked phrase `{blocked_focus}`."
        )
    anchor_count = len(_extract_role_focus_anchors(decision.technical_focus))
    if anchor_count < rubric.minimum_specific_anchor_count:
        raise OutreachDraftingError(
            f"Opener decision technical focus `{decision.technical_focus}` does not meet minimum specificity."
        )
    if rubric.require_title_alignment and _fails_role_title_specific_gate(
        decision.technical_focus,
        decision.role_title,
    ):
        raise OutreachDraftingError(
            f"Opener decision technical focus `{decision.technical_focus}` is not title-aligned for `{decision.role_title}`."
        )
    overlap_lower = decision.overlap_sentence.lower()
    if decision.claim_mode == CLAIM_MODE_DIRECT_BACKGROUND and any(
        marker in overlap_lower
        for marker in ("actively building toward", "academic and personal projects")
    ):
        raise OutreachDraftingError(
            "Direct-background opener decision cannot use interest-area wording."
        )
    if decision.claim_mode == CLAIM_MODE_INTEREST_AREA and any(
        marker in overlap_lower for marker in ("i've done", "background overlaps", "background is")
    ):
        raise OutreachDraftingError(
            "Interest-area opener decision cannot imply direct professional experience."
        )
    if decision.claim_mode == CLAIM_MODE_GROWTH_AREA and any(
        marker in overlap_lower for marker in ("i've done", "background overlaps", "background is")
    ):
        raise OutreachDraftingError(
            "Growth-area opener decision cannot imply direct professional experience."
        )


def _validate_role_targeted_composition_plan(
    plan: RoleTargetedCompositionPlan,
    context: RoleTargetedDraftContext,
) -> None:
    _validate_role_targeted_opener_decision(context)
    opener_lower = plan.opener_paragraph.lower()
    blocked_phrase = next(
        (phrase for phrase in context.opener_rubric.blocked_opener_phrases if phrase in opener_lower),
        None,
    )
    if blocked_phrase is not None:
        raise OutreachDraftingError(
            f"Role-targeted opener failed quality validation for blocked phrase `{blocked_phrase}`."
        )
    if context.opener_decision.technical_focus not in plan.opener_paragraph:
        raise OutreachDraftingError("Rendered opener does not include the selected technical focus.")
    if context.opener_decision.overlap_sentence not in plan.opener_paragraph:
        raise OutreachDraftingError("Rendered opener does not include the selected overlap sentence.")
    combined_text = " ".join(
        [
            plan.opener_paragraph,
            plan.background_paragraph,
            *plan.copilot_paragraphs,
            plan.ask_paragraph,
            plan.snippet_text,
        ]
    )
    for pattern in ROLE_TARGETED_DRAFT_BLOCK_PATTERNS:
        if pattern.search(combined_text):
            raise OutreachDraftingError(
                f"Role-targeted composition failed quality validation for pattern `{pattern.pattern}`."
            )


def _persist_rendered_draft(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    posting_row: Mapping[str, Any],
    contact_row: Mapping[str, Any],
    outreach_message_id: str,
    outreach_mode: str,
    recipient_email: str,
    rendered: RenderedDraft,
    current_time: str,
    resume_attachment_path: str | None,
    use_role_targeted_mirrors: bool,
) -> DraftedOutreachMessage:
    company_name = str(posting_row["company_name"])
    role_title = str(posting_row["role_title"])
    draft_path = paths.outreach_message_draft_path(company_name, role_title, outreach_message_id)
    html_path = paths.outreach_message_html_path(company_name, role_title, outreach_message_id)
    send_result_path = paths.outreach_message_send_result_path(company_name, role_title, outreach_message_id)
    opener_decision_path = paths.outreach_message_opener_decision_path(
        company_name,
        role_title,
        outreach_message_id,
    )

    _write_text_file(draft_path, rendered.body_markdown)
    body_html_artifact_path: str | None = None
    if rendered.body_html:
        _write_text_file(html_path, rendered.body_html)
        body_html_artifact_path = str(html_path.resolve())
    linkage = ArtifactLinkage(
        lead_id=str(posting_row["lead_id"]),
        job_posting_id=str(posting_row["job_posting_id"]),
        contact_id=str(contact_row["contact_id"]),
        outreach_message_id=outreach_message_id,
    )

    timestamps = lifecycle_timestamps(current_time)
    with connection:
        connection.execute(
            """
            INSERT INTO outreach_messages (
              outreach_message_id, contact_id, outreach_mode, recipient_email, message_status,
              job_posting_id, job_posting_contact_id, subject, body_text, body_html,
              thread_id, delivery_tracking_id, sent_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                outreach_message_id,
                contact_row["contact_id"],
                outreach_mode,
                recipient_email,
                MESSAGE_STATUS_GENERATED,
                posting_row["job_posting_id"],
                contact_row["job_posting_contact_id"],
                rendered.subject,
                rendered.body_markdown,
                rendered.body_html,
                None,
                None,
                None,
                timestamps["created_at"],
                timestamps["updated_at"],
            ),
        )

    _register_text_artifact(
        connection,
        paths,
        artifact_type=OUTREACH_DRAFT_ARTIFACT_TYPE,
        artifact_path=draft_path,
        linkage=linkage,
        created_at=current_time,
    )
    if rendered.body_html:
        _register_text_artifact(
            connection,
            paths,
            artifact_type=OUTREACH_DRAFT_HTML_ARTIFACT_TYPE,
            artifact_path=html_path,
            linkage=linkage,
            created_at=current_time,
        )

    opener_decision_artifact_path: str | None = None
    if rendered.opener_decision is not None:
        published_opener_decision = publish_json_artifact(
            connection,
            paths,
            artifact_type=OPENER_DECISION_ARTIFACT_TYPE,
            artifact_path=opener_decision_path,
            producer_component=OUTREACH_COMPONENT,
            result="success",
            linkage=linkage,
            payload=rendered.opener_decision.as_dict(),
            produced_at=current_time,
        )
        opener_decision_artifact_path = str(published_opener_decision.location.absolute_path)

    published_send_result = publish_json_artifact(
        connection,
        paths,
        artifact_type=SEND_RESULT_ARTIFACT_TYPE,
        artifact_path=send_result_path,
        producer_component=OUTREACH_COMPONENT,
        result="success",
        linkage=linkage,
        payload={
            "outreach_mode": outreach_mode,
            "recipient_email": recipient_email,
            "send_status": MESSAGE_STATUS_GENERATED,
            "sent_at": None,
            "thread_id": None,
            "delivery_tracking_id": None,
            "subject": rendered.subject,
            "body_text_artifact_path": str(draft_path.resolve()),
            "body_html_artifact_path": body_html_artifact_path,
            "opener_decision_artifact_path": opener_decision_artifact_path,
            "resume_attachment_path": resume_attachment_path,
        },
        produced_at=current_time,
    )
    if use_role_targeted_mirrors:
        _write_text_file(paths.outreach_latest_draft_path(company_name, role_title), rendered.body_markdown)
        _write_text_file(
            paths.outreach_latest_send_result_path(company_name, role_title),
            json.dumps(published_send_result.contract, indent=2) + "\n",
        )
    return DraftedOutreachMessage(
        outreach_message_id=outreach_message_id,
        contact_id=str(contact_row["contact_id"]),
        job_posting_id=str(posting_row["job_posting_id"]),
        job_posting_contact_id=str(contact_row["job_posting_contact_id"]),
        outreach_mode=outreach_mode,
        recipient_email=recipient_email,
        message_status=MESSAGE_STATUS_GENERATED,
        subject=rendered.subject,
        body_text=rendered.body_markdown,
        body_html=rendered.body_html,
        body_text_artifact_path=str(draft_path.resolve()),
        send_result_artifact_path=str(send_result_path.resolve()),
        body_html_artifact_path=body_html_artifact_path,
        opener_decision_artifact_path=opener_decision_artifact_path,
        resume_attachment_path=resume_attachment_path,
    )


def _persist_rendered_general_learning_draft(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    contact_row: Mapping[str, Any],
    outreach_message_id: str,
    recipient_email: str,
    rendered: RenderedDraft,
    current_time: str,
) -> DraftedOutreachMessage:
    company_name = str(contact_row["company_name"] or "unknown-company")
    contact_id = str(contact_row["contact_id"])
    draft_path = paths.general_learning_outreach_draft_path(company_name, contact_id, outreach_message_id)
    html_path = paths.general_learning_outreach_html_path(company_name, contact_id, outreach_message_id)
    send_result_path = paths.general_learning_outreach_send_result_path(company_name, contact_id, outreach_message_id)

    _write_text_file(draft_path, rendered.body_markdown)
    body_html_artifact_path: str | None = None
    if rendered.body_html:
        _write_text_file(html_path, rendered.body_html)
        body_html_artifact_path = str(html_path.resolve())

    timestamps = lifecycle_timestamps(current_time)
    with connection:
        connection.execute(
            """
            INSERT INTO outreach_messages (
              outreach_message_id, contact_id, outreach_mode, recipient_email, message_status,
              job_posting_id, job_posting_contact_id, subject, body_text, body_html,
              thread_id, delivery_tracking_id, sent_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                outreach_message_id,
                contact_id,
                OUTREACH_MODE_GENERAL_LEARNING,
                recipient_email,
                MESSAGE_STATUS_GENERATED,
                None,
                None,
                rendered.subject,
                rendered.body_markdown,
                rendered.body_html,
                None,
                None,
                None,
                timestamps["created_at"],
                timestamps["updated_at"],
            ),
        )

    _register_text_artifact(
        connection,
        paths,
        artifact_type=OUTREACH_DRAFT_ARTIFACT_TYPE,
        artifact_path=draft_path,
        linkage=ArtifactLinkage(
            contact_id=contact_id,
            outreach_message_id=outreach_message_id,
        ),
        created_at=current_time,
    )
    if rendered.body_html:
        _register_text_artifact(
            connection,
            paths,
            artifact_type=OUTREACH_DRAFT_HTML_ARTIFACT_TYPE,
            artifact_path=html_path,
            linkage=ArtifactLinkage(
                contact_id=contact_id,
                outreach_message_id=outreach_message_id,
            ),
            created_at=current_time,
        )
    publish_json_artifact(
        connection,
        paths,
        artifact_type=SEND_RESULT_ARTIFACT_TYPE,
        artifact_path=send_result_path,
        producer_component=OUTREACH_COMPONENT,
        result="success",
        linkage=ArtifactLinkage(
            contact_id=contact_id,
            outreach_message_id=outreach_message_id,
        ),
        payload={
            "outreach_mode": OUTREACH_MODE_GENERAL_LEARNING,
            "recipient_email": recipient_email,
            "send_status": MESSAGE_STATUS_GENERATED,
            "sent_at": None,
            "thread_id": None,
            "delivery_tracking_id": None,
            "subject": rendered.subject,
            "body_text_artifact_path": str(draft_path.resolve()),
            "body_html_artifact_path": body_html_artifact_path,
        },
        produced_at=current_time,
    )
    return DraftedOutreachMessage(
        outreach_message_id=outreach_message_id,
        contact_id=contact_id,
        job_posting_id=None,
        job_posting_contact_id=None,
        outreach_mode=OUTREACH_MODE_GENERAL_LEARNING,
        recipient_email=recipient_email,
        message_status=MESSAGE_STATUS_GENERATED,
        subject=rendered.subject,
        body_text=rendered.body_markdown,
        body_html=rendered.body_html,
        body_text_artifact_path=str(draft_path.resolve()),
        send_result_artifact_path=str(send_result_path.resolve()),
        body_html_artifact_path=body_html_artifact_path,
        opener_decision_artifact_path=None,
        resume_attachment_path=None,
    )


def _evaluate_general_learning_send_guardrails(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    contact_row: Mapping[str, Any],
    active_message: Mapping[str, Any],
) -> dict[str, str] | None:
    contact_id = str(contact_row["contact_id"])
    recipient_email = _normalize_optional_text(active_message["recipient_email"])
    if recipient_email is None:
        return {
            "reason_code": "missing_recipient_email",
            "message": "Automatic general-learning sending requires a usable recipient email.",
        }
    if (
        _normalize_optional_text(active_message["subject"]) is None
        or _normalize_optional_text(active_message["body_text"]) is None
    ):
        return {
            "reason_code": "missing_draft_content",
            "message": "Automatic general-learning sending requires persisted draft subject and body content.",
        }

    company_name = str(contact_row["company_name"] or "unknown-company")
    draft_path = paths.general_learning_outreach_draft_path(
        company_name,
        contact_id,
        str(active_message["outreach_message_id"]),
    )
    send_result_path = paths.general_learning_outreach_send_result_path(
        company_name,
        contact_id,
        str(active_message["outreach_message_id"]),
    )
    if not draft_path.exists():
        return {
            "reason_code": "missing_draft_artifact",
            "message": f"Draft artifact is missing for `{active_message['outreach_message_id']}`.",
        }
    if not send_result_path.exists():
        return {
            "reason_code": "missing_send_result_artifact",
            "message": f"send_result.json is missing for `{active_message['outreach_message_id']}`.",
        }

    try:
        send_result_contract = _read_json_file(send_result_path)
    except Exception:
        return {
            "reason_code": "invalid_send_result_artifact",
            "message": f"send_result.json is unreadable for `{active_message['outreach_message_id']}`.",
        }
    send_status = _normalize_optional_text(send_result_contract.get("send_status"))
    if send_status in {MESSAGE_STATUS_SENT, MESSAGE_STATUS_BLOCKED}:
        return {
            "reason_code": "ambiguous_send_state",
            "message": "Stored general-learning send_result.json already reflects a non-generated send state, so automatic resend is unsafe.",
        }
    if (
        _normalize_optional_text(active_message["sent_at"]) is not None
        or _normalize_optional_text(active_message["thread_id"]) is not None
        or _normalize_optional_text(active_message["delivery_tracking_id"]) is not None
    ):
        return {
            "reason_code": "ambiguous_send_state",
            "message": "Message delivery metadata already exists without a clean completed send state, so automatic resend is unsafe.",
        }

    prior_sent_count = int(
        connection.execute(
            """
            SELECT COUNT(*)
            FROM outreach_messages
            WHERE contact_id = ?
              AND outreach_message_id <> ?
              AND (
                sent_at IS NOT NULL
                OR message_status = ?
              )
            """,
            (
                contact_id,
                str(active_message["outreach_message_id"]),
                MESSAGE_STATUS_SENT,
            ),
        ).fetchone()[0]
        or 0
    )
    if prior_sent_count > 0:
        return {
            "reason_code": "repeat_outreach_review_required",
            "message": "Prior outreach history exists for this contact, so automatic repeat sending is blocked pending review.",
        }

    other_active_message_count = int(
        connection.execute(
            """
            SELECT COUNT(*)
            FROM outreach_messages
            WHERE contact_id = ?
              AND outreach_message_id <> ?
              AND message_status IN (?, ?)
            """,
            (
                contact_id,
                str(active_message["outreach_message_id"]),
                MESSAGE_STATUS_GENERATED,
                MESSAGE_STATUS_BLOCKED,
            ),
        ).fetchone()[0]
        or 0
    )
    if other_active_message_count > 0:
        return {
            "reason_code": "ambiguous_send_state",
            "message": "Multiple active outreach messages exist for this contact, so automatic resend is unsafe.",
        }
    return None


def _persist_failed_draft_attempt(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    posting_row: Mapping[str, Any],
    contact_row: Mapping[str, Any],
    outreach_message_id: str,
    outreach_mode: str,
    recipient_email: str,
    current_time: str,
    reason_code: str,
    message: str,
) -> DraftFailure:
    company_name = str(posting_row["company_name"])
    role_title = str(posting_row["role_title"])
    send_result_path = paths.outreach_message_send_result_path(company_name, role_title, outreach_message_id)
    timestamps = lifecycle_timestamps(current_time)
    with connection:
        connection.execute(
            """
            INSERT INTO outreach_messages (
              outreach_message_id, contact_id, outreach_mode, recipient_email, message_status,
              job_posting_id, job_posting_contact_id, subject, body_text, body_html,
              thread_id, delivery_tracking_id, sent_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                outreach_message_id,
                contact_row["contact_id"],
                outreach_mode,
                recipient_email,
                MESSAGE_STATUS_FAILED,
                posting_row["job_posting_id"],
                contact_row["job_posting_contact_id"],
                None,
                None,
                None,
                None,
                None,
                None,
                timestamps["created_at"],
                timestamps["updated_at"],
            ),
        )
    published_send_result = publish_json_artifact(
        connection,
        paths,
        artifact_type=SEND_RESULT_ARTIFACT_TYPE,
        artifact_path=send_result_path,
        producer_component=OUTREACH_COMPONENT,
        result="failed",
        linkage=ArtifactLinkage(
            lead_id=str(posting_row["lead_id"]),
            job_posting_id=str(posting_row["job_posting_id"]),
            contact_id=str(contact_row["contact_id"]),
            outreach_message_id=outreach_message_id,
        ),
        payload={
            "outreach_mode": outreach_mode,
            "recipient_email": recipient_email,
            "send_status": MESSAGE_STATUS_FAILED,
            "sent_at": None,
            "thread_id": None,
            "delivery_tracking_id": None,
            "subject": None,
            "body_text_artifact_path": None,
            "body_html_artifact_path": None,
        },
        produced_at=current_time,
        reason_code=reason_code,
        message=message,
    )
    _write_text_file(
        paths.outreach_latest_send_result_path(company_name, role_title),
        json.dumps(published_send_result.contract, indent=2) + "\n",
    )
    return DraftFailure(
        outreach_message_id=outreach_message_id,
        contact_id=str(contact_row["contact_id"]),
        job_posting_contact_id=str(contact_row["job_posting_contact_id"]),
        reason_code=reason_code,
        message=message,
    )


def _persist_successful_general_learning_send(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    contact_row: Mapping[str, Any],
    active_message: Mapping[str, Any],
    current_time: str,
    drafted_message: DraftedOutreachMessage | None,
    sent_at: str,
    thread_id: str | None,
    delivery_tracking_id: str | None,
) -> GeneralLearningSendExecutionResult:
    normalized_sent_at = _isoformat_utc(_parse_iso_datetime(sent_at))
    outreach_message_id = str(active_message["outreach_message_id"])
    with connection:
        connection.execute(
            """
            UPDATE outreach_messages
            SET message_status = ?, thread_id = ?, delivery_tracking_id = ?, sent_at = ?, updated_at = ?
            WHERE outreach_message_id = ?
            """,
            (
                MESSAGE_STATUS_SENT,
                thread_id,
                delivery_tracking_id,
                normalized_sent_at,
                current_time,
                outreach_message_id,
            ),
        )

    current_contact_status = str(contact_row["contact_status"]).strip()
    if current_contact_status != CONTACT_STATUS_SENT:
        with connection:
            connection.execute(
                """
                UPDATE contacts
                SET contact_status = ?, updated_at = ?
                WHERE contact_id = ?
                """,
                (
                    CONTACT_STATUS_SENT,
                    current_time,
                    contact_row["contact_id"],
                ),
            )
            _record_state_transition(
                connection,
                object_type="contact",
                object_id=str(contact_row["contact_id"]),
                stage="contact_status",
                previous_state=current_contact_status,
                new_state=CONTACT_STATUS_SENT,
                transition_timestamp=current_time,
                transition_reason="A general-learning outreach message was sent for this contact.",
                lead_id=None,
                job_posting_id=None,
                contact_id=str(contact_row["contact_id"]),
            )

    send_result_artifact_path = _publish_general_learning_send_result(
        connection,
        paths,
        contact_row=contact_row,
        active_message=active_message,
        current_time=current_time,
        result="success",
        send_status=MESSAGE_STATUS_SENT,
        sent_at=normalized_sent_at,
        thread_id=thread_id,
        delivery_tracking_id=delivery_tracking_id,
        reason_code=None,
        message=None,
    )
    return GeneralLearningSendExecutionResult(
        contact_id=str(contact_row["contact_id"]),
        outreach_message_id=outreach_message_id,
        drafted_message=drafted_message,
        message_status_after_execution=MESSAGE_STATUS_SENT,
        send_result_artifact_path=send_result_artifact_path,
        sent_at=normalized_sent_at,
        thread_id=thread_id,
        delivery_tracking_id=delivery_tracking_id,
        reason_code=None,
        message=None,
    )


def _persist_blocked_general_learning_send(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    contact_row: Mapping[str, Any],
    active_message: Mapping[str, Any],
    current_time: str,
    drafted_message: DraftedOutreachMessage | None,
    reason_code: str,
    message: str,
) -> GeneralLearningSendExecutionResult:
    outreach_message_id = str(active_message["outreach_message_id"])
    with connection:
        connection.execute(
            """
            UPDATE outreach_messages
            SET message_status = ?, updated_at = ?
            WHERE outreach_message_id = ?
            """,
            (
                MESSAGE_STATUS_BLOCKED,
                current_time,
                outreach_message_id,
            ),
        )

    send_result_artifact_path = _publish_general_learning_send_result(
        connection,
        paths,
        contact_row=contact_row,
        active_message=active_message,
        current_time=current_time,
        result="blocked",
        send_status=MESSAGE_STATUS_BLOCKED,
        sent_at=None,
        thread_id=_normalize_optional_text(active_message["thread_id"]),
        delivery_tracking_id=_normalize_optional_text(active_message["delivery_tracking_id"]),
        reason_code=reason_code,
        message=message,
    )
    return GeneralLearningSendExecutionResult(
        contact_id=str(contact_row["contact_id"]),
        outreach_message_id=outreach_message_id,
        drafted_message=drafted_message,
        message_status_after_execution=MESSAGE_STATUS_BLOCKED,
        send_result_artifact_path=send_result_artifact_path,
        sent_at=None,
        thread_id=None,
        delivery_tracking_id=None,
        reason_code=reason_code,
        message=message,
    )


def _persist_failed_general_learning_send_attempt(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    contact_row: Mapping[str, Any],
    active_message: Mapping[str, Any],
    current_time: str,
    drafted_message: DraftedOutreachMessage | None,
    reason_code: str,
    message: str,
) -> GeneralLearningSendExecutionResult:
    outreach_message_id = str(active_message["outreach_message_id"])
    with connection:
        connection.execute(
            """
            UPDATE outreach_messages
            SET message_status = ?, updated_at = ?
            WHERE outreach_message_id = ?
            """,
            (
                MESSAGE_STATUS_FAILED,
                current_time,
                outreach_message_id,
            ),
        )

    send_result_artifact_path = _publish_general_learning_send_result(
        connection,
        paths,
        contact_row=contact_row,
        active_message=active_message,
        current_time=current_time,
        result="failed",
        send_status=MESSAGE_STATUS_FAILED,
        sent_at=None,
        thread_id=None,
        delivery_tracking_id=None,
        reason_code=reason_code,
        message=message,
    )
    return GeneralLearningSendExecutionResult(
        contact_id=str(contact_row["contact_id"]),
        outreach_message_id=outreach_message_id,
        drafted_message=drafted_message,
        message_status_after_execution=MESSAGE_STATUS_FAILED,
        send_result_artifact_path=send_result_artifact_path,
        sent_at=None,
        thread_id=None,
        delivery_tracking_id=None,
        reason_code=reason_code,
        message=message,
    )


def _publish_general_learning_send_result(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    contact_row: Mapping[str, Any],
    active_message: Mapping[str, Any],
    current_time: str,
    result: str,
    send_status: str,
    sent_at: str | None,
    thread_id: str | None,
    delivery_tracking_id: str | None,
    reason_code: str | None,
    message: str | None,
) -> str:
    company_name = str(contact_row["company_name"] or "unknown-company")
    contact_id = str(contact_row["contact_id"])
    outreach_message_id = str(active_message["outreach_message_id"])
    draft_path = paths.general_learning_outreach_draft_path(
        company_name,
        contact_id,
        outreach_message_id,
    )
    html_path = paths.general_learning_outreach_html_path(
        company_name,
        contact_id,
        outreach_message_id,
    )
    send_result_path = paths.general_learning_outreach_send_result_path(
        company_name,
        contact_id,
        outreach_message_id,
    )
    publish_json_artifact(
        connection,
        paths,
        artifact_type=SEND_RESULT_ARTIFACT_TYPE,
        artifact_path=send_result_path,
        producer_component=OUTREACH_COMPONENT,
        result=result,
        linkage=ArtifactLinkage(
            contact_id=contact_id,
            outreach_message_id=outreach_message_id,
        ),
        payload={
            "outreach_mode": OUTREACH_MODE_GENERAL_LEARNING,
            "recipient_email": _normalize_optional_text(active_message["recipient_email"]),
            "send_status": send_status,
            "sent_at": sent_at,
            "thread_id": thread_id,
            "delivery_tracking_id": delivery_tracking_id,
            "subject": _normalize_optional_text(active_message["subject"]),
            "body_text_artifact_path": str(draft_path.resolve()) if draft_path.exists() else None,
            "body_html_artifact_path": str(html_path.resolve()) if html_path.exists() else None,
        },
        produced_at=current_time,
        reason_code=reason_code,
        message=message,
    )
    return str(send_result_path.resolve())


def _promote_posting_into_outreach_in_progress(
    connection: sqlite3.Connection,
    *,
    posting_row: Mapping[str, Any],
    current_time: str,
) -> None:
    current_status = str(posting_row["posting_status"]).strip()
    if current_status == JOB_POSTING_STATUS_OUTREACH_IN_PROGRESS:
        return
    with connection:
        connection.execute(
            """
            UPDATE job_postings
            SET posting_status = ?, updated_at = ?
            WHERE job_posting_id = ?
            """,
            (
                JOB_POSTING_STATUS_OUTREACH_IN_PROGRESS,
                current_time,
                posting_row["job_posting_id"],
            ),
        )
        _record_state_transition(
            connection,
            object_type="job_posting",
            object_id=str(posting_row["job_posting_id"]),
            stage="posting_status",
            previous_state=current_status,
            new_state=JOB_POSTING_STATUS_OUTREACH_IN_PROGRESS,
            transition_timestamp=current_time,
            transition_reason="The first contact in the ready send set entered drafting.",
            lead_id=str(posting_row["lead_id"]),
            job_posting_id=str(posting_row["job_posting_id"]),
            contact_id=None,
        )


def _promote_contact_into_outreach_in_progress(
    connection: sqlite3.Connection,
    *,
    posting_row: Mapping[str, Any],
    contact_row: Mapping[str, Any],
    current_time: str,
) -> None:
    current_contact_status = str(contact_row["contact_status"]).strip()
    current_link_status = str(contact_row["link_level_status"]).strip()
    with connection:
        if current_contact_status != CONTACT_STATUS_OUTREACH_IN_PROGRESS:
            connection.execute(
                """
                UPDATE contacts
                SET contact_status = ?, updated_at = ?
                WHERE contact_id = ?
                """,
                (
                    CONTACT_STATUS_OUTREACH_IN_PROGRESS,
                    current_time,
                    contact_row["contact_id"],
                ),
            )
            _record_state_transition(
                connection,
                object_type="contact",
                object_id=str(contact_row["contact_id"]),
                stage="contact_status",
                previous_state=current_contact_status,
                new_state=CONTACT_STATUS_OUTREACH_IN_PROGRESS,
                transition_timestamp=current_time,
                transition_reason="Drafting began for this posting-contact pair.",
                lead_id=str(posting_row["lead_id"]),
                job_posting_id=str(posting_row["job_posting_id"]),
                contact_id=str(contact_row["contact_id"]),
            )
        if current_link_status != POSTING_CONTACT_STATUS_OUTREACH_IN_PROGRESS:
            connection.execute(
                """
                UPDATE job_posting_contacts
                SET link_level_status = ?, updated_at = ?
                WHERE job_posting_contact_id = ?
                """,
                (
                    POSTING_CONTACT_STATUS_OUTREACH_IN_PROGRESS,
                    current_time,
                    contact_row["job_posting_contact_id"],
                ),
            )
            _record_state_transition(
                connection,
                object_type="job_posting_contact",
                object_id=str(contact_row["job_posting_contact_id"]),
                stage="link_level_status",
                previous_state=current_link_status,
                new_state=POSTING_CONTACT_STATUS_OUTREACH_IN_PROGRESS,
                transition_timestamp=current_time,
                transition_reason="Drafting began for this posting-contact pair.",
                lead_id=str(posting_row["lead_id"]),
                job_posting_id=str(posting_row["job_posting_id"]),
                contact_id=str(contact_row["contact_id"]),
            )


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
    contact_id: str | None,
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
            OUTREACH_COMPONENT,
            lead_id,
            job_posting_id,
            contact_id,
        ),
    )


def _register_text_artifact(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    artifact_type: str,
    artifact_path: Path,
    linkage: ArtifactLinkage,
    created_at: str,
) -> None:
    register_artifact_record(
        connection,
        paths,
        artifact_type=artifact_type,
        artifact_path=artifact_path,
        producer_component=OUTREACH_COMPONENT,
        linkage=linkage,
        created_at=created_at,
    )


def _write_text_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _render_markdown_email_html(body_markdown: str) -> str:
    html_blocks: list[str] = []
    paragraph_lines: list[str] = []
    blockquote_lines: list[str] = []
    pitch_lines = _job_hunt_copilot_pitch_lines()
    snippet_intro_line = "I've included a short snippet below that you can paste into an IM/Email:"

    def flush_paragraph() -> None:
        nonlocal paragraph_lines
        if paragraph_lines:
            html_blocks.append(f"<p>{html.escape(' '.join(paragraph_lines))}</p>")
            paragraph_lines = []

    def flush_blockquote() -> None:
        nonlocal blockquote_lines
        if blockquote_lines:
            html_blocks.append(
                "<blockquote>"
                + "".join(f"<p>{html.escape(line)}</p>" for line in blockquote_lines)
                + "</blockquote>"
            )
            blockquote_lines = []

    body_lines = body_markdown.splitlines()
    index = 0
    while index < len(body_lines):
        raw_line = body_lines[index]
        stripped = raw_line.rstrip()
        if not stripped:
            flush_paragraph()
            flush_blockquote()
            index += 1
            continue
        if stripped == snippet_intro_line:
            flush_paragraph()
            flush_blockquote()
            html_blocks.append(f"<p>{html.escape(snippet_intro_line)}</p>")
            index += 1
            if index < len(body_lines) and body_lines[index].strip() == "[snippet]":
                snippet_lines: list[str] = []
                index += 1
                while index < len(body_lines):
                    snippet_line = body_lines[index].rstrip()
                    if snippet_line.strip() == "[/snippet]":
                        index += 1
                        break
                    snippet_lines.append(snippet_line)
                    index += 1
                html_blocks.append(_render_forwardable_snippet_html("\n".join(snippet_lines).strip()))
            continue
        if stripped == "Best,":
            flush_paragraph()
            flush_blockquote()
            signature_lines = ["Best,"]
            index += 1
            while index < len(body_lines):
                signature_line = body_lines[index].rstrip()
                if not signature_line:
                    break
                signature_lines.append(signature_line)
                index += 1
            html_blocks.append(_render_signature_block_html(signature_lines))
            continue
        if stripped == "[snippet]":
            flush_paragraph()
            flush_blockquote()
            snippet_lines: list[str] = []
            index += 1
            while index < len(body_lines):
                snippet_line = body_lines[index].rstrip()
                if snippet_line.strip() == "[/snippet]":
                    index += 1
                    break
                snippet_lines.append(snippet_line)
                index += 1
            html_blocks.append(_render_forwardable_snippet_html("\n".join(snippet_lines).strip()))
            continue
        if body_lines[index : index + len(pitch_lines)] == pitch_lines:
            flush_paragraph()
            flush_blockquote()
            html_blocks.append(_render_job_hunt_copilot_callout_html())
            index += len(pitch_lines)
            continue
        if stripped.startswith("> "):
            flush_paragraph()
            blockquote_lines.append(stripped[2:])
            index += 1
            continue
        flush_blockquote()
        paragraph_lines.append(stripped)
        index += 1
    flush_paragraph()
    flush_blockquote()
    return "<html><body>" + "".join(html_blocks) + "</body></html>\n"


def _render_job_hunt_copilot_callout_html() -> str:
    line_one, line_two, line_three = _job_hunt_copilot_pitch_lines()
    repo_url = html.escape(JOB_HUNT_COPILOT_REPO_URL, quote=True)
    escaped_repo_text = html.escape(JOB_HUNT_COPILOT_REPO_URL)
    line_two_html = html.escape(line_two).replace(
        escaped_repo_text,
        f'<a href="{repo_url}" style="color:#1d4ed8;text-decoration:none;font-weight:600;">{escaped_repo_text}</a>',
    )
    return (
        '<div style="margin:16px 0;padding:14px 16px;'
        'border-left:3px solid #111827;border-radius:4px;'
        'background:#f8fafc;">'
        f'<p style="margin:0 0 8px 0;color:#334155;line-height:1.55;">{html.escape(line_one)}</p>'
        f'<p style="margin:0 0 8px 0;color:#111827;line-height:1.55;font-weight:600;">{line_two_html}</p>'
        f'<p style="margin:0;color:#111827;line-height:1.55;font-weight:600;">{html.escape(line_three)}</p>'
        "</div>"
    )


def _render_forwardable_snippet_html(snippet_text: str) -> str:
    return (
        '<div style="background:#f4f4f4;border-left:4px solid #1a73e8;'
        "padding:12px 16px;margin:12px 0;border-radius:4px;"
        "font-family:Arial,sans-serif;font-size:13px;color:#333;"
        'line-height:1.5;white-space:pre-wrap;">'
        f"{html.escape(snippet_text)}"
        "</div>"
    )


def _render_signature_block_html(signature_lines: Sequence[str]) -> str:
    escaped_lines = [html.escape(line) for line in signature_lines]
    return (
        '<p style="margin:16px 0 0 0;line-height:1.6;">'
        + "<br>".join(escaped_lines)
        + "</p>"
    )


def _read_yaml_file(path: Path) -> Mapping[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, Mapping):
        raise OutreachDraftingError(f"YAML payload must be a mapping: {path}")
    return payload


def _read_json_file(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise OutreachDraftingError(f"JSON payload must be an object: {path}")
    return payload


def _first_name(display_name: str) -> str:
    parts = [part for part in NAME_SPLIT_RE.split(display_name.strip()) if part]
    return parts[0] if parts else display_name
