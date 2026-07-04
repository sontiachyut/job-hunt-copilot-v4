from __future__ import annotations

import hashlib
import html
import json
import re
import shutil
import sqlite3
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .artifacts import ArtifactLinkage, write_json_contract, write_yaml_contract
from .paths import ProjectPaths, workspace_slug
from .records import lifecycle_timestamps, new_canonical_id, now_utc_iso


JOBRIGHT_COMPONENT = "jobright_ingestion"
JOBRIGHT_SOURCE_TYPE = "jobright_recommendation"
JOBRIGHT_SOURCE_MODE = "jobright_recommendation"
JOBRIGHT_OBSERVATION_KIND_FEED = "recommendation_feed"
JOBRIGHT_OBSERVATION_KIND_JOB_PAGE = "job_page"
JOBRIGHT_LEAD_STATUS_DISCOVERED = "discovered"
JOBRIGHT_LEAD_STATUS_HELD = "held"
JOBRIGHT_LEAD_STATUS_PROMOTED = "promoted"
JOBRIGHT_LEAD_STATUS_BLOCKED_NO_JD = "blocked_no_jd"
JOBRIGHT_LEAD_STATUS_REAUTH_REQUIRED = "reauth_required"
JOBRIGHT_LEAD_STATUS_CLOSED = "closed"
JOBRIGHT_BATCH_RESULT_READY = "ready"
JOBRIGHT_BATCH_RESULT_REAUTH_REQUIRED = "reauth_required"
JOBRIGHT_BATCH_RESULT_EMPTY = "empty"
JOBRIGHT_FEED_URL = "https://jobright.ai/swan/recommend/list/jobs"
JOBRIGHT_RECOMMENDATIONS_PAGE_URL = "https://jobright.ai/jobs/recommend"
CHROME_EPOCH_OFFSET_SECONDS = 11_644_473_600
DEFAULT_COMET_ROOT = Path.home() / "Library/Application Support/Comet"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/149.0.0.0 Safari/537.36"
)
DEFAULT_RECOMMENDATION_COUNT = 10
DEFAULT_MIN_POLL_INTERVAL_SECONDS = 15 * 60

NEXT_DATA_RE = re.compile(
    r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)
TITLE_RE = re.compile(r"<title>(.*?)</title>", re.DOTALL | re.IGNORECASE)
HTML_TAG_RE = re.compile(r"(?is)<[^>]+>")
WHITESPACE_RE = re.compile(r"[ \t]+")

JD_TEXT_KEYS = (
    "jobDescription",
    "jobDescriptionText",
    "description",
    "descriptionText",
    "jdText",
    "responsibilities",
    "requirements",
    "qualifications",
    "aboutTheJob",
    "jobSummary",
)
STRUCTURED_JD_SECTION_KEYS = (
    ("jobSummary", "Summary"),
    ("coreResponsibilities", "Responsibilities"),
    ("responsibilities", "Responsibilities"),
    ("requirements", "Requirements"),
    ("skillSummaries", "Qualifications"),
    ("educationSummaries", "Education"),
    ("benefitsSummaries", "Benefits"),
)


class JobrightSessionError(RuntimeError):
    """Raised when the authenticated Jobright session cannot be reused."""


class JobrightAuthRequired(JobrightSessionError):
    """Raised when Jobright requires the user to reauthenticate."""


@dataclass(frozen=True)
class JobrightRecommendation:
    jobright_job_id: str
    lead_identity_key: str
    job_url: str
    company_name: str
    role_title: str
    display_score: float | None
    rank_desc: str | None
    location: str | None
    salary: str | None
    apply_url: str | None
    recommendation_scores: dict[str, Any]
    skill_matching_scores: dict[str, Any]
    industry_matching_scores: dict[str, Any]
    social_connections: list[dict[str, Any]]
    personal_social_connections: dict[str, list[dict[str, Any]]] | None
    jd_text: str | None
    jd_is_usable: bool
    observed_at: str
    feed_payload: dict[str, Any]
    page_payload: dict[str, Any]


@dataclass(frozen=True)
class JobrightRecommendationBatch:
    ingestion_run_id: str
    result: str
    collected_at: str
    recommendations: tuple[JobrightRecommendation, ...]
    reason_code: str | None = None
    message: str | None = None
    raw_feed_payload: dict[str, Any] | list[Any] | None = None


@dataclass(frozen=True)
class JobrightIngestionResult:
    ingestion_run_id: str
    result: str
    leads_created: int
    leads_updated: int
    source_observations_written: int
    contacts_linked: int
    lead_ids: tuple[str, ...]
    reason_code: str | None = None
    message: str | None = None


def _parse_utc_iso_sort_key(timestamp: str) -> float:
    from datetime import datetime, timezone

    normalized = timestamp.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized).astimezone(timezone.utc).timestamp()


def _format_jobright_run_id(current_time: str) -> str:
    compact = current_time.replace("-", "").replace(":", "").replace("+00:00", "Z")
    compact = compact.replace(".", "")
    return f"jobright-auto-{compact}"


def _normalize_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        text = str(value)
    elif isinstance(value, str):
        text = value
    else:
        return None
    normalized = text.strip()
    return normalized or None


def _normalize_linkedin_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value.strip())
    if not parsed.scheme or not parsed.netloc:
        return value.strip()
    cleaned = parsed._replace(query="", fragment="")
    return cleaned.geturl().rstrip("/")


def _normalize_job_url(job_url: str, jobright_job_id: str | None = None) -> str:
    if job_url.startswith("/"):
        return f"https://jobright.ai{job_url}"
    if job_url.startswith("http://") or job_url.startswith("https://"):
        return job_url
    if jobright_job_id:
        return f"https://jobright.ai/jobs/info/{jobright_job_id}"
    return f"https://jobright.ai/{job_url.lstrip('/')}"


def _strip_html(value: str) -> str:
    text = html.unescape(value)
    text = HTML_TAG_RE.sub("\n", text)
    text = WHITESPACE_RE.sub(" ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _iter_dicts(obj: Any):
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _iter_dicts(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from _iter_dicts(item)


def _first_non_empty(*values: Any) -> Any | None:
    for value in values:
        if value not in (None, "", [], {}, False):
            return value
    return None


def _parse_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_title(html_text: str) -> str | None:
    match = TITLE_RE.search(html_text)
    if not match:
        return None
    return html.unescape(match.group(1).strip())


def _extract_next_data(html_text: str) -> dict[str, Any] | None:
    match = NEXT_DATA_RE.search(html_text)
    if not match:
        return None
    return json.loads(html.unescape(match.group(1)))


def _find_first_key(obj: Any, key: str) -> Any | None:
    for candidate in _iter_dicts(obj):
        if key in candidate:
            return candidate[key]
    return None


def _normalize_connection_item(
    item: dict[str, Any],
    *,
    fallback_company_name: str,
) -> dict[str, Any]:
    full_name = _first_non_empty(item.get("fullName"), item.get("name"))
    title = _first_non_empty(item.get("title"), item.get("positionTitle"), item.get("headline"))
    linkedin_url = _normalize_linkedin_url(_normalize_optional_text(item.get("linkedinUrl")))
    company_name = _first_non_empty(item.get("companyName"), fallback_company_name)
    return {
        "fullName": full_name,
        "title": title,
        "linkedinUrl": linkedin_url,
        "companyName": company_name,
    }


def _normalize_connection_list(
    items: Any,
    *,
    fallback_company_name: str,
) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        normalized_item = _normalize_connection_item(item, fallback_company_name=fallback_company_name)
        if _normalize_optional_text(normalized_item.get("fullName")) is None:
            continue
        normalized_item["sourceRank"] = index
        normalized.append(normalized_item)
    return normalized


def _extract_job_summary(
    next_data: dict[str, Any] | None,
    fallback: dict[str, Any],
) -> dict[str, Any]:
    job_result = None
    if next_data is not None:
        for candidate in _iter_dicts(next_data):
            if not isinstance(candidate, dict):
                continue
            if "socialConnections" in candidate or "personalSocialConnections" in candidate:
                job_result = candidate
                break
    company = _first_non_empty(
        fallback.get("companyName"),
        fallback.get("company"),
        fallback.get("companyTitle"),
        job_result.get("companyName") if isinstance(job_result, dict) else None,
        _find_first_key(next_data, "companyName") if next_data is not None else None,
    )
    if isinstance(company, dict):
        company = _first_non_empty(company.get("name"), company.get("companyName"))

    location = _first_non_empty(
        fallback.get("location"),
        fallback.get("locationName"),
        job_result.get("location") if isinstance(job_result, dict) else None,
        _find_first_key(next_data, "companyLocation") if next_data is not None else None,
    )
    if isinstance(location, dict):
        location = _first_non_empty(
            location.get("name"),
            location.get("displayName"),
            location.get("locationName"),
        )

    return {
        "title": _first_non_empty(
            fallback.get("jobTitle"),
            fallback.get("title"),
            job_result.get("title") if isinstance(job_result, dict) else None,
            _find_first_key(next_data, "jobTitle") if next_data is not None else None,
        ),
        "company": company,
        "location": location,
        "salary": _first_non_empty(
            fallback.get("salary"),
            fallback.get("salaryText"),
            fallback.get("compensationText"),
            job_result.get("salary") if isinstance(job_result, dict) else None,
            _find_first_key(next_data, "salaryDesc") if next_data is not None else None,
        ),
        "apply_url": _first_non_empty(
            fallback.get("applyUrl"),
            fallback.get("jobtargetEasyapply"),
            job_result.get("originalJobPostUrl") if isinstance(job_result, dict) else None,
            _find_first_key(next_data, "jobtargetEasyapply") if next_data is not None else None,
        ),
    }


def _collect_candidate_jd_text_legacy(next_data: dict[str, Any] | None) -> str | None:
    if next_data is None:
        return None
    candidates: list[str] = []
    seen: set[str] = set()
    for item in _iter_dicts(next_data):
        if not isinstance(item, dict):
            continue
        for key, value in item.items():
            if key not in JD_TEXT_KEYS:
                continue
            text = _flatten_jd_value(value)
            if text is None:
                continue
            if text in seen:
                continue
            seen.add(text)
            candidates.append(text)
    if not candidates:
        return None
    return max(candidates, key=len)


def _qualification_section_text(value: Any) -> str | None:
    if isinstance(value, dict):
        blocks: list[str] = []
        must_have = _flatten_jd_value(value.get("mustHave"))
        preferred_have = _flatten_jd_value(value.get("preferredHave"))
        if must_have:
            blocks.append(f"Must Have\n{must_have}")
        if preferred_have:
            blocks.append(f"Preferred\n{preferred_have}")
        remaining = {
            key: nested_value
            for key, nested_value in value.items()
            if key not in {"mustHave", "preferredHave"}
        }
        extra = _flatten_jd_value(remaining)
        if extra:
            blocks.append(extra)
        merged = "\n\n".join(block for block in blocks if block.strip()).strip()
        return merged or None
    return _flatten_jd_value(value)


def _append_structured_jd_section(
    blocks: list[str],
    seen_bodies: set[str],
    *,
    heading: str,
    body: str | None,
) -> None:
    if body is None:
        return
    normalized_body = re.sub(r"\s+", " ", body).strip().lower()
    if not normalized_body or normalized_body in seen_bodies:
        return
    seen_bodies.add(normalized_body)
    blocks.append(f"{heading}\n{body.strip()}")


def _collect_structured_jd_text(next_data: dict[str, Any] | None) -> str | None:
    if next_data is None:
        return None
    blocks: list[str] = []
    seen_bodies: set[str] = set()

    for key, heading in STRUCTURED_JD_SECTION_KEYS:
        body = _flatten_jd_value(_find_first_key(next_data, key))
        _append_structured_jd_section(
            blocks,
            seen_bodies,
            heading=heading,
            body=body,
        )

    qualifications_body = _qualification_section_text(_find_first_key(next_data, "qualifications"))
    _append_structured_jd_section(
        blocks,
        seen_bodies,
        heading="Qualifications",
        body=qualifications_body,
    )

    if not blocks:
        return None
    return "\n\n".join(blocks).strip() or None


def _collect_candidate_jd_text(next_data: dict[str, Any] | None) -> str | None:
    structured = _collect_structured_jd_text(next_data)
    if structured is not None:
        return structured
    return _collect_candidate_jd_text_legacy(next_data)


def _flatten_jd_value(value: Any) -> str | None:
    parts: list[str] = []

    def append_strings(candidate: Any) -> None:
        if isinstance(candidate, str):
            text = _strip_html(candidate)
            if text:
                parts.append(text)
            return
        if isinstance(candidate, list):
            for entry in candidate:
                append_strings(entry)
            return
        if isinstance(candidate, dict):
            for nested_value in candidate.values():
                append_strings(nested_value)

    append_strings(value)
    if not parts:
        return None
    merged = "\n\n".join(part for part in parts if part)
    merged = re.sub(r"\n{3,}", "\n\n", merged).strip()
    return merged or None


def _jd_is_usable(jd_text: str | None) -> bool:
    if not jd_text:
        return False
    return len(jd_text.split()) >= 80


def _extract_page_payload(
    html_text: str,
    *,
    fallback_entry: dict[str, Any],
) -> dict[str, Any]:
    next_data = _extract_next_data(html_text)
    summary = _extract_job_summary(next_data, fallback=fallback_entry)
    company_name = _normalize_optional_text(summary.get("company")) or _normalize_optional_text(
        fallback_entry.get("companyName")
    ) or "Unknown Company"
    social_connections = _normalize_connection_list(
        _find_first_key(next_data, "socialConnections"),
        fallback_company_name=company_name,
    )
    personal_raw = _find_first_key(next_data, "personalSocialConnections")
    personal_connections: dict[str, list[dict[str, Any]]] | None = None
    if isinstance(personal_raw, dict):
        school_connections = _normalize_connection_list(
            personal_raw.get("school"),
            fallback_company_name=company_name,
        )
        company_connections = _normalize_connection_list(
            personal_raw.get("company"),
            fallback_company_name=company_name,
        )
        if school_connections or company_connections:
            personal_connections = {
                "school": school_connections,
                "company": company_connections,
            }
    jd_text = _collect_candidate_jd_text(next_data)
    return {
        "fetch": {
            "http_status": 200,
            "page_title": _extract_title(html_text),
            "next_data_found": next_data is not None,
        },
        "job_summary": summary,
        "social_connections": social_connections,
        "personal_social_connections": personal_connections,
        "jd_text": jd_text,
        "jd_is_usable": _jd_is_usable(jd_text),
        "next_data": next_data,
    }


def _candidate_job_id(candidate: dict[str, Any]) -> str | None:
    for key in ("jobId", "jobID", "infoId", "_id", "id"):
        value = _normalize_optional_text(candidate.get(key))
        if value is not None:
            return value
    for nested_key in ("job", "jobResult"):
        nested_job = candidate.get(nested_key)
        if isinstance(nested_job, dict):
            nested_id = _candidate_job_id(nested_job)
            if nested_id is not None:
                return nested_id
    return None


def _candidate_job_url(candidate: dict[str, Any], jobright_job_id: str | None) -> str | None:
    for key in ("jobUrl", "jobLink", "url", "job_url"):
        value = _normalize_optional_text(candidate.get(key))
        if value is not None:
            return _normalize_job_url(value, jobright_job_id=jobright_job_id)
    for nested_key in ("job", "jobResult"):
        nested_job = candidate.get(nested_key)
        if isinstance(nested_job, dict):
            nested_url = _candidate_job_url(nested_job, jobright_job_id=jobright_job_id)
            if nested_url is not None:
                return nested_url
    if jobright_job_id:
        return _normalize_job_url("", jobright_job_id=jobright_job_id)
    return None


def _candidate_company_name(candidate: dict[str, Any]) -> str | None:
    company_value = _first_non_empty(candidate.get("companyName"), candidate.get("company"))
    if isinstance(company_value, dict):
        company_value = _first_non_empty(company_value.get("name"), company_value.get("companyName"))
    text = _normalize_optional_text(company_value)
    if text is not None:
        return text
    for nested_key in ("job", "jobResult", "companyResult"):
        nested_job = candidate.get(nested_key)
        if isinstance(nested_job, dict):
            nested_company_name = _candidate_company_name(nested_job)
            if nested_company_name is not None:
                return nested_company_name
    return None


def _candidate_role_title(candidate: dict[str, Any]) -> str | None:
    title_value = _first_non_empty(candidate.get("jobTitle"), candidate.get("title"), candidate.get("jobNlpTitle"))
    text = _normalize_optional_text(title_value)
    if text is not None:
        return text
    for nested_key in ("job", "jobResult"):
        nested_job = candidate.get(nested_key)
        if isinstance(nested_job, dict):
            nested_role_title = _candidate_role_title(nested_job)
            if nested_role_title is not None:
                return nested_role_title
    return None


def _normalize_recommendation_score_map(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, list):
        return {}
    normalized: dict[str, Any] = {}
    for entry in value:
        if not isinstance(entry, dict):
            continue
        label = _normalize_optional_text(
            _first_non_empty(
                entry.get("displayName"),
                entry.get("featureName"),
                entry.get("name"),
                entry.get("label"),
            )
        )
        score = _parse_float(entry.get("score"))
        if label is None or score is None:
            continue
        normalized[label] = score
    return normalized


def _candidate_value(candidate: dict[str, Any], *keys: str) -> Any:
    direct_values = [_first_non_empty(*(candidate.get(key) for key in keys))]
    for value in direct_values:
        if value is not None:
            return value
    for nested_key in ("job", "jobResult", "companyResult"):
        nested = candidate.get(nested_key)
        if not isinstance(nested, dict):
            continue
        nested_value = _first_non_empty(*(nested.get(key) for key in keys))
        if nested_value is not None:
            return nested_value
    return None


def _parse_recommendation_candidate(candidate: dict[str, Any]) -> dict[str, Any] | None:
    jobright_job_id = _candidate_job_id(candidate)
    job_url = _candidate_job_url(candidate, jobright_job_id)
    company_name = _candidate_company_name(candidate)
    role_title = _candidate_role_title(candidate)
    display_score = _parse_float(
        _first_non_empty(
            candidate.get("displayScore"),
            candidate.get("score"),
            candidate.get("matchScore"),
        )
    )
    rank_desc = _normalize_optional_text(
        _first_non_empty(candidate.get("rankDesc"), candidate.get("scoreDesc"), candidate.get("matchLabel"))
    )
    if not job_url or not company_name or not role_title:
        return None
    return {
        "jobright_job_id": jobright_job_id or workspace_slug(job_url),
        "job_url": job_url,
        "company_name": company_name,
        "role_title": role_title,
        "display_score": display_score,
        "rank_desc": rank_desc,
        "location": _normalize_optional_text(_candidate_value(candidate, "location", "locationName", "jobLocation")),
        "salary": _normalize_optional_text(
            _candidate_value(candidate, "salary", "salaryText")
        ),
        "apply_url": _normalize_optional_text(
            _candidate_value(candidate, "applyUrl", "jobtargetEasyapply", "applyLink", "originalUrl")
        ),
        "recommendation_scores": _normalize_recommendation_score_map(
            _candidate_value(candidate, "recommendationScores")
        ),
        "skill_matching_scores": _normalize_recommendation_score_map(
            _candidate_value(candidate, "skillMatchingScores")
        ),
        "industry_matching_scores": _normalize_recommendation_score_map(
            _candidate_value(candidate, "industryMatchingScores")
        ),
        "feed_payload": candidate,
    }


def _looks_like_recommendation(candidate: dict[str, Any]) -> bool:
    if "displayScore" in candidate or "rankDesc" in candidate:
        return True
    if any(key in candidate for key in ("jobUrl", "jobLink", "jobTitle", "companyName")):
        return True
    nested_job_result = candidate.get("jobResult")
    return isinstance(nested_job_result, dict) and any(
        key in nested_job_result for key in ("jobId", "jobTitle", "companyName")
    )


def _extract_recommendation_entries(payload: Any) -> list[dict[str, Any]]:
    recommendations: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for candidate in _iter_dicts(payload):
        if not isinstance(candidate, dict) or not _looks_like_recommendation(candidate):
            continue
        parsed = _parse_recommendation_candidate(candidate)
        if parsed is None:
            continue
        dedupe_key = parsed["jobright_job_id"] or parsed["job_url"]
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)
        recommendations.append(parsed)
    return recommendations


def _contact_identity_key(
    *,
    linkedin_url: str | None,
    full_name: str,
    company_name: str,
    title: str | None,
) -> str:
    normalized_linkedin = _normalize_linkedin_url(linkedin_url)
    if normalized_linkedin:
        return f"linkedin:{normalized_linkedin}"
    title_slug = workspace_slug(title or "unknown-title")
    return (
        f"jobright_contact:{workspace_slug(full_name)}:"
        f"{workspace_slug(company_name)}:{title_slug}"
    )


def _lead_identity_key(jobright_job_id: str, job_url: str) -> str:
    if jobright_job_id:
        return f"jobright:{jobright_job_id}"
    return f"jobright_url:{_normalize_job_url(job_url)}"


def _initial_lead_status(recommendation: JobrightRecommendation) -> tuple[str, str | None]:
    if not recommendation.jd_is_usable:
        return JOBRIGHT_LEAD_STATUS_BLOCKED_NO_JD, "blocked_no_jd"
    total_connections = len(recommendation.social_connections)
    if recommendation.personal_social_connections:
        total_connections += len(recommendation.personal_social_connections.get("school", []))
        total_connections += len(recommendation.personal_social_connections.get("company", []))
    if total_connections == 0:
        return JOBRIGHT_LEAD_STATUS_HELD, "blocked_no_connections"
    return JOBRIGHT_LEAD_STATUS_DISCOVERED, None


class JobrightSessionClient:
    def __init__(
        self,
        *,
        comet_root: Path = DEFAULT_COMET_ROOT,
        profile_name: str = "Default",
        safe_storage_service: str = "Comet Safe Storage",
        safe_storage_account: str = "Comet",
        user_agent: str = DEFAULT_USER_AGENT,
        timeout_seconds: int = 30,
    ) -> None:
        self.comet_root = comet_root.expanduser().resolve()
        self.profile_name = profile_name
        self.safe_storage_service = safe_storage_service
        self.safe_storage_account = safe_storage_account
        self.user_agent = user_agent
        self.timeout_seconds = timeout_seconds

    @property
    def profile_dir(self) -> Path:
        return self.comet_root / self.profile_name

    def is_configured(self) -> bool:
        return (self.profile_dir / "Cookies").exists()

    def _get_safe_storage_secret(self) -> str:
        result = subprocess.run(
            ["security", "find-generic-password", "-w", "-s", self.safe_storage_service, "-a", self.safe_storage_account],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip() or result.stdout.strip() or "unknown keychain error"
            raise JobrightSessionError(
                f"Could not read {self.safe_storage_service} from Keychain: {stderr}"
            )
        return result.stdout.strip()

    def _derive_cookie_key(self, secret: str) -> bytes:
        return hashlib.pbkdf2_hmac("sha1", secret.encode("utf-8"), b"saltysalt", 1003, dklen=16)

    def _decrypt_cookie(self, host_key: str, encrypted_value: bytes, key: bytes) -> str:
        if not encrypted_value:
            return ""
        if encrypted_value.startswith(b"v10"):
            iv = b" " * 16
            cipher = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
            plaintext = cipher.update(encrypted_value[3:]) + cipher.finalize()
            pad_length = plaintext[-1]
            plaintext = plaintext[:-pad_length]
            host_digest = hashlib.sha256(host_key.encode("utf-8")).digest()
            if plaintext.startswith(host_digest):
                plaintext = plaintext[len(host_digest) :]
            return plaintext.decode("utf-8", "ignore")
        return encrypted_value.decode("utf-8", "ignore")

    def _chrome_expires_to_unix(self, expires_utc: int) -> int:
        if expires_utc <= 0:
            return -1
        return max(0, int(expires_utc / 1_000_000 - CHROME_EPOCH_OFFSET_SECONDS))

    def _copy_cookie_db(self) -> Path:
        cookies_db = self.profile_dir / "Cookies"
        if not cookies_db.exists():
            raise JobrightSessionError(f"Comet cookies DB not found: {cookies_db}")
        temp_path = Path(tempfile.gettempdir()) / "jobright-comet-cookies-copy.sqlite"
        shutil.copy2(cookies_db, temp_path)
        return temp_path

    def load_jobright_cookies(self) -> list[dict[str, Any]]:
        secret = self._get_safe_storage_secret()
        cookie_key = self._derive_cookie_key(secret)
        temp_db = self._copy_cookie_db()
        try:
            connection = sqlite3.connect(temp_db)
            rows = connection.execute(
                """
                SELECT host_key, name, path, is_secure, is_httponly, expires_utc, encrypted_value
                FROM cookies
                WHERE host_key LIKE '%jobright%'
                ORDER BY host_key, name
                """
            ).fetchall()
        finally:
            try:
                connection.close()
            except Exception:
                pass
            temp_db.unlink(missing_ok=True)

        cookies: list[dict[str, Any]] = []
        for host_key, name, path, is_secure, is_httponly, expires_utc, encrypted_value in rows:
            value = self._decrypt_cookie(host_key, encrypted_value, cookie_key)
            if not value:
                continue
            cookies.append(
                {
                    "name": name,
                    "value": value,
                    "domain": host_key,
                    "path": path,
                    "secure": bool(is_secure),
                    "httpOnly": bool(is_httponly),
                    "expires": self._chrome_expires_to_unix(int(expires_utc)),
                }
            )
        return cookies

    def _session(self) -> requests.Session:
        cookies = self.load_jobright_cookies()
        if not cookies:
            raise JobrightAuthRequired("No reusable Jobright cookies were found in the Comet profile.")
        jar = requests.cookies.RequestsCookieJar()
        for cookie in cookies:
            jar.set(
                name=cookie["name"],
                value=cookie["value"],
                domain=cookie.get("domain"),
                path=cookie.get("path", "/"),
            )
        session = requests.Session()
        session.cookies = jar
        session.headers.update(
            {
                "User-Agent": self.user_agent,
                "Accept": "application/json, text/plain, */*",
            }
        )
        return session

    def fetch_recommendation_feed(
        self,
        *,
        count: int = DEFAULT_RECOMMENDATION_COUNT,
        position: int = 0,
    ) -> Any:
        session = self._session()
        response = session.get(
            JOBRIGHT_FEED_URL,
            params={
                "refresh": "true",
                "sortCondition": "0",
                "position": str(position),
                "count": str(count),
                "syncRerank": "false",
            },
            timeout=self.timeout_seconds,
        )
        if response.status_code in {401, 403}:
            raise JobrightAuthRequired(f"Jobright feed returned HTTP {response.status_code}.")
        try:
            return response.json()
        except json.JSONDecodeError as exc:
            preview = response.text[:200].strip()
            if "sign in" in preview.lower() or "join now" in preview.lower():
                raise JobrightAuthRequired("Jobright feed returned signed-out HTML.") from exc
            raise JobrightSessionError(
                f"Jobright feed did not return JSON. HTTP {response.status_code}: {preview}"
            ) from exc

    def fetch_job_page(self, job_url: str) -> str:
        session = self._session()
        response = session.get(job_url, timeout=self.timeout_seconds, headers={"User-Agent": self.user_agent})
        if response.status_code in {401, 403}:
            raise JobrightAuthRequired(f"Jobright job page returned HTTP {response.status_code}.")
        response.raise_for_status()
        return response.text


class JobrightRecommendationCollector:
    def __init__(
        self,
        client: JobrightSessionClient | None = None,
        *,
        recommendation_count: int = DEFAULT_RECOMMENDATION_COUNT,
        min_poll_interval_seconds: int = DEFAULT_MIN_POLL_INTERVAL_SECONDS,
    ) -> None:
        self.client = client or JobrightSessionClient()
        self.recommendation_count = recommendation_count
        self.min_poll_interval_seconds = min_poll_interval_seconds
        self._prepared_batches: dict[str, JobrightRecommendationBatch] = {}

    def prepare_batch(
        self,
        *,
        current_time: str,
        last_polled_at: str | None = None,
    ) -> JobrightRecommendationBatch | None:
        if self._prepared_batches:
            return next(iter(self._prepared_batches.values()))
        if last_polled_at is not None:
            age_seconds = _parse_utc_iso_sort_key(current_time) - _parse_utc_iso_sort_key(last_polled_at)
            if age_seconds < self.min_poll_interval_seconds:
                return None

        ingestion_run_id = _format_jobright_run_id(current_time)
        try:
            feed_payload = self.client.fetch_recommendation_feed(count=self.recommendation_count)
        except JobrightAuthRequired as exc:
            batch = JobrightRecommendationBatch(
                ingestion_run_id=ingestion_run_id,
                result=JOBRIGHT_BATCH_RESULT_REAUTH_REQUIRED,
                collected_at=current_time,
                recommendations=(),
                reason_code="reauth_required",
                message=str(exc),
                raw_feed_payload=None,
            )
            self._prepared_batches[ingestion_run_id] = batch
            return batch

        feed_entries = _extract_recommendation_entries(feed_payload)
        recommendations: list[JobrightRecommendation] = []
        for feed_entry in feed_entries:
            job_url = feed_entry["job_url"]
            job_html = self.client.fetch_job_page(job_url)
            page_payload = _extract_page_payload(job_html, fallback_entry=feed_entry)
            job_summary = page_payload["job_summary"]
            jobright_job_id = feed_entry["jobright_job_id"]
            normalized_job_url = _normalize_job_url(job_url, jobright_job_id=jobright_job_id)
            recommendations.append(
                JobrightRecommendation(
                    jobright_job_id=jobright_job_id,
                    lead_identity_key=_lead_identity_key(jobright_job_id, normalized_job_url),
                    job_url=normalized_job_url,
                    company_name=_normalize_optional_text(job_summary.get("company")) or feed_entry["company_name"],
                    role_title=_normalize_optional_text(job_summary.get("title")) or feed_entry["role_title"],
                    display_score=feed_entry["display_score"],
                    rank_desc=feed_entry["rank_desc"],
                    location=_normalize_optional_text(job_summary.get("location")) or feed_entry.get("location"),
                    salary=_normalize_optional_text(job_summary.get("salary")) or feed_entry.get("salary"),
                    apply_url=_normalize_optional_text(job_summary.get("apply_url")) or feed_entry.get("apply_url"),
                    recommendation_scores=feed_entry["recommendation_scores"],
                    skill_matching_scores=feed_entry["skill_matching_scores"],
                    industry_matching_scores=feed_entry["industry_matching_scores"],
                    social_connections=list(page_payload["social_connections"]),
                    personal_social_connections=page_payload["personal_social_connections"],
                    jd_text=_normalize_optional_text(page_payload["jd_text"]),
                    jd_is_usable=bool(page_payload["jd_is_usable"]),
                    observed_at=current_time,
                    feed_payload=dict(feed_entry["feed_payload"]),
                    page_payload={
                        "fetch": page_payload["fetch"],
                        "job_summary": job_summary,
                        "social_connections": page_payload["social_connections"],
                        "personal_social_connections": page_payload["personal_social_connections"],
                    },
                )
            )

        if not recommendations:
            return None
        batch = JobrightRecommendationBatch(
            ingestion_run_id=ingestion_run_id,
            result=JOBRIGHT_BATCH_RESULT_READY,
            collected_at=current_time,
            recommendations=tuple(recommendations),
            raw_feed_payload=feed_payload if isinstance(feed_payload, (dict, list)) else None,
        )
        self._prepared_batches[ingestion_run_id] = batch
        return batch

    def peek_prepared_batch(self, ingestion_run_id: str) -> JobrightRecommendationBatch | None:
        return self._prepared_batches.get(ingestion_run_id)

    def pop_prepared_batch(self, ingestion_run_id: str) -> JobrightRecommendationBatch | None:
        return self._prepared_batches.pop(ingestion_run_id, None)


def _write_jobright_run_artifacts(
    paths: ProjectPaths,
    batch: JobrightRecommendationBatch,
    *,
    result_payload: dict[str, Any],
) -> None:
    payload_path = paths.jobright_run_payload_path(batch.ingestion_run_id)
    summary_path = paths.jobright_run_summary_path(batch.ingestion_run_id)
    write_json_contract(
        payload_path,
        producer_component=JOBRIGHT_COMPONENT,
        result=batch.result,
        payload={
            "ingestion_run_id": batch.ingestion_run_id,
            "collected_at": batch.collected_at,
            "raw_feed_payload": batch.raw_feed_payload,
            "recommendations": [
                {
                    "jobright_job_id": recommendation.jobright_job_id,
                    "lead_identity_key": recommendation.lead_identity_key,
                    "job_url": recommendation.job_url,
                    "company_name": recommendation.company_name,
                    "role_title": recommendation.role_title,
                    "display_score": recommendation.display_score,
                    "rank_desc": recommendation.rank_desc,
                    "location": recommendation.location,
                    "salary": recommendation.salary,
                    "apply_url": recommendation.apply_url,
                    "recommendation_scores": recommendation.recommendation_scores,
                    "skill_matching_scores": recommendation.skill_matching_scores,
                    "industry_matching_scores": recommendation.industry_matching_scores,
                }
                for recommendation in batch.recommendations
            ],
        },
        reason_code=batch.reason_code if batch.result == JOBRIGHT_BATCH_RESULT_REAUTH_REQUIRED else None,
        message=batch.message if batch.result == JOBRIGHT_BATCH_RESULT_REAUTH_REQUIRED else None,
    )
    write_json_contract(
        summary_path,
        producer_component=JOBRIGHT_COMPONENT,
        result=batch.result,
        payload=result_payload,
        reason_code=batch.reason_code if batch.result == JOBRIGHT_BATCH_RESULT_REAUTH_REQUIRED else None,
        message=batch.message if batch.result == JOBRIGHT_BATCH_RESULT_REAUTH_REQUIRED else None,
    )


def _select_or_create_contact(
    connection: sqlite3.Connection,
    *,
    company_name: str,
    person: dict[str, Any],
    timestamp: str,
) -> str:
    full_name = _normalize_optional_text(person.get("fullName"))
    if full_name is None:
        raise ValueError("Jobright contact is missing a fullName.")
    title = _normalize_optional_text(person.get("title"))
    linkedin_url = _normalize_linkedin_url(_normalize_optional_text(person.get("linkedinUrl")))
    identity_key = _contact_identity_key(
        linkedin_url=linkedin_url,
        full_name=full_name,
        company_name=company_name,
        title=title,
    )
    row = connection.execute(
        """
        SELECT contact_id, full_name, position_title, linkedin_url, company_name
        FROM contacts
        WHERE identity_key = ?
        """,
        (identity_key,),
    ).fetchone()
    if row is None and linkedin_url is not None:
        row = connection.execute(
            """
            SELECT contact_id, full_name, position_title, linkedin_url, company_name
            FROM contacts
            WHERE linkedin_url = ?
            ORDER BY created_at ASC, contact_id ASC
            LIMIT 1
            """,
            (linkedin_url,),
        ).fetchone()
    if row is not None:
        connection.execute(
            """
            UPDATE contacts
            SET display_name = COALESCE(?, display_name),
                company_name = COALESCE(?, company_name),
                origin_component = ?,
                contact_status = COALESCE(contact_status, 'identified'),
                full_name = COALESCE(?, full_name),
                first_name = COALESCE(first_name, ?),
                last_name = COALESCE(last_name, ?),
                linkedin_url = COALESCE(?, linkedin_url),
                position_title = COALESCE(?, position_title),
                updated_at = ?
            WHERE contact_id = ?
            """,
            (
                full_name,
                company_name,
                JOBRIGHT_COMPONENT,
                full_name,
                full_name.split(" ", 1)[0] if " " in full_name else full_name,
                full_name.split(" ", 1)[1] if " " in full_name else None,
                linkedin_url,
                title,
                timestamp,
                row["contact_id"],
            ),
        )
        return str(row["contact_id"])

    contact_id = new_canonical_id("contacts")
    timestamps = lifecycle_timestamps(timestamp)
    first_name = full_name.split(" ", 1)[0] if full_name else None
    last_name = full_name.split(" ", 1)[1] if " " in full_name else None
    connection.execute(
        """
        INSERT INTO contacts (
          contact_id, identity_key, display_name, company_name, origin_component,
          contact_status, full_name, first_name, last_name, linkedin_url,
          position_title, identity_source, provider_name, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            contact_id,
            identity_key,
            full_name,
            company_name,
            JOBRIGHT_COMPONENT,
            "identified",
            full_name,
            first_name,
            last_name,
            linkedin_url,
            title,
            "jobright",
            "jobright",
            timestamps["created_at"],
            timestamps["updated_at"],
        ),
    )
    return contact_id


def _sync_lead_contacts(
    connection: sqlite3.Connection,
    *,
    lead_id: str,
    source_observation_id: str,
    company_name: str,
    social_connections: list[dict[str, Any]],
    personal_social_connections: dict[str, list[dict[str, Any]]] | None,
    timestamp: str,
) -> int:
    merged_contacts: dict[str, dict[str, Any]] = {}

    def add_people(
        people: list[dict[str, Any]],
        *,
        source_type: str,
        priority_tier: int,
    ) -> None:
        for person in people:
            normalized_name = _normalize_optional_text(person.get("fullName"))
            if normalized_name is None:
                continue
            normalized_linkedin = _normalize_linkedin_url(_normalize_optional_text(person.get("linkedinUrl")))
            dedupe_key = normalized_linkedin or normalized_name.lower()
            payload = {
                "fullName": normalized_name,
                "title": _normalize_optional_text(person.get("title")),
                "linkedinUrl": normalized_linkedin,
                "companyName": _normalize_optional_text(person.get("companyName")) or company_name,
                "source_type": source_type,
                "priority_tier": priority_tier,
                "source_rank": int(person.get("sourceRank") or 0),
            }
            existing = merged_contacts.get(dedupe_key)
            if existing is None or priority_tier < existing["priority_tier"]:
                merged_contacts[dedupe_key] = payload
                continue
            if priority_tier == existing["priority_tier"] and payload["source_rank"] < existing["source_rank"]:
                merged_contacts[dedupe_key] = payload

    if personal_social_connections:
        add_people(
            personal_social_connections.get("school", []),
            source_type="jobright_personal_school",
            priority_tier=1,
        )
        add_people(
            personal_social_connections.get("company", []),
            source_type="jobright_personal_company",
            priority_tier=1,
        )
    add_people(social_connections, source_type="jobright_public", priority_tier=2)

    linked_count = 0
    for payload in merged_contacts.values():
        contact_id = _select_or_create_contact(
            connection,
            company_name=company_name,
            person=payload,
            timestamp=timestamp,
        )
        existing = connection.execute(
            """
            SELECT lead_contact_id
            FROM lead_contacts
            WHERE lead_id = ? AND contact_id = ?
            """,
            (lead_id, contact_id),
        ).fetchone()
        if existing is None:
            lead_contact_id = new_canonical_id("lead_contacts")
            timestamps = lifecycle_timestamps(timestamp)
            connection.execute(
                """
                INSERT INTO lead_contacts (
                  lead_contact_id, lead_id, contact_id, source_observation_id,
                  contact_source_type, contact_source_priority_tier,
                  contact_source_rank, is_initial_intended_contact,
                  created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    lead_contact_id,
                    lead_id,
                    contact_id,
                    source_observation_id,
                    payload["source_type"],
                    payload["priority_tier"],
                    payload["source_rank"],
                    0,
                    timestamps["created_at"],
                    timestamps["updated_at"],
                ),
            )
        else:
            connection.execute(
                """
                UPDATE lead_contacts
                SET source_observation_id = ?,
                    contact_source_type = ?,
                    contact_source_priority_tier = ?,
                    contact_source_rank = ?,
                    updated_at = ?
                WHERE lead_contact_id = ?
                """,
                (
                    source_observation_id,
                    payload["source_type"],
                    payload["priority_tier"],
                    payload["source_rank"],
                    timestamp,
                    existing["lead_contact_id"],
                ),
            )
        linked_count += 1
    return linked_count


def ingest_jobright_recommendation_batch(
    project_root: Path | str,
    *,
    batch: JobrightRecommendationBatch,
) -> JobrightIngestionResult:
    paths = ProjectPaths.from_root(project_root)
    if batch.result == JOBRIGHT_BATCH_RESULT_REAUTH_REQUIRED:
        result_payload = {
            "ingestion_run_id": batch.ingestion_run_id,
            "leads_created": 0,
            "leads_updated": 0,
            "source_observations_written": 0,
            "contacts_linked": 0,
            "lead_ids": [],
        }
        _write_jobright_run_artifacts(paths, batch, result_payload=result_payload)
        return JobrightIngestionResult(
            ingestion_run_id=batch.ingestion_run_id,
            result=batch.result,
            leads_created=0,
            leads_updated=0,
            source_observations_written=0,
            contacts_linked=0,
            lead_ids=(),
            reason_code=batch.reason_code,
            message=batch.message,
        )

    db_path = paths.db_path
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")

    leads_created = 0
    leads_updated = 0
    source_observations_written = 0
    contacts_linked = 0
    lead_ids: list[str] = []

    with connection:
        for recommendation in batch.recommendations:
            row = connection.execute(
                """
                SELECT lead_id
                FROM leads
                WHERE lead_identity_key = ?
                """,
                (recommendation.lead_identity_key,),
            ).fetchone()
            if row is None:
                lead_id = new_canonical_id("leads")
                lead_ids.append(lead_id)
                lead_status, reason_code = _initial_lead_status(recommendation)
                timestamps = lifecycle_timestamps(recommendation.observed_at)
                connection.execute(
                    """
                    INSERT INTO leads (
                      lead_id, lead_identity_key, lead_status, source_type,
                      source_reference, source_mode, source_url, company_name,
                      role_title, location, canonical_jd_artifact_path,
                      active_source_observation_id, reason_code, latest_fit_score,
                      latest_fit_label, latest_public_connection_count,
                      latest_personal_connection_count, latest_total_connection_count,
                      created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        lead_id,
                        recommendation.lead_identity_key,
                        lead_status,
                        JOBRIGHT_SOURCE_TYPE,
                        JOBRIGHT_RECOMMENDATIONS_PAGE_URL,
                        JOBRIGHT_SOURCE_MODE,
                        recommendation.job_url,
                        recommendation.company_name,
                        recommendation.role_title,
                        recommendation.location,
                        None,
                        None,
                        reason_code,
                        recommendation.display_score,
                        recommendation.rank_desc,
                        len(recommendation.social_connections),
                        len(recommendation.personal_social_connections.get("school", []))
                        + len(recommendation.personal_social_connections.get("company", []))
                        if recommendation.personal_social_connections
                        else 0,
                        len(recommendation.social_connections)
                        + (
                            len(recommendation.personal_social_connections.get("school", []))
                            + len(recommendation.personal_social_connections.get("company", []))
                            if recommendation.personal_social_connections
                            else 0
                        ),
                        timestamps["created_at"],
                        timestamps["updated_at"],
                    ),
                )
                leads_created += 1
            else:
                lead_id = str(row["lead_id"])
                lead_ids.append(lead_id)
                leads_updated += 1

            workspace_dir = paths.lead_ingestion_lead_workspace_dir(
                recommendation.company_name,
                recommendation.role_title,
                lead_id,
            )
            raw_dir = paths.lead_ingestion_raw_dir(
                recommendation.company_name,
                recommendation.role_title,
                lead_id,
            )
            raw_dir.mkdir(parents=True, exist_ok=True)
            feed_artifact_path = raw_dir / "recommendation-feed.json"
            page_artifact_path = raw_dir / "job-page.json"
            source_observations_path = paths.lead_ingestion_source_observations_path(
                recommendation.company_name,
                recommendation.role_title,
                lead_id,
            )
            source_contacts_path = paths.lead_ingestion_source_contacts_path(
                recommendation.company_name,
                recommendation.role_title,
                lead_id,
            )
            lead_manifest_path = paths.lead_ingestion_lead_manifest_path(
                recommendation.company_name,
                recommendation.role_title,
                lead_id,
            )
            jd_path = paths.lead_ingestion_jd_path(
                recommendation.company_name,
                recommendation.role_title,
                lead_id,
            )

            write_json_contract(
                feed_artifact_path,
                producer_component=JOBRIGHT_COMPONENT,
                result="ok",
                linkage=ArtifactLinkage(lead_id=lead_id),
                payload={
                    "source_type": JOBRIGHT_SOURCE_TYPE,
                    "source_mode": JOBRIGHT_SOURCE_MODE,
                    "observation_kind": JOBRIGHT_OBSERVATION_KIND_FEED,
                    "ingestion_run_id": batch.ingestion_run_id,
                    "jobright_job_id": recommendation.jobright_job_id,
                    "job_url": recommendation.job_url,
                    "display_score": recommendation.display_score,
                    "rank_desc": recommendation.rank_desc,
                    "recommendation_scores": recommendation.recommendation_scores,
                    "skill_matching_scores": recommendation.skill_matching_scores,
                    "industry_matching_scores": recommendation.industry_matching_scores,
                    "feed_payload": recommendation.feed_payload,
                },
                produced_at=recommendation.observed_at,
            )
            write_json_contract(
                page_artifact_path,
                producer_component=JOBRIGHT_COMPONENT,
                result="ok",
                linkage=ArtifactLinkage(lead_id=lead_id),
                payload={
                    "source_type": JOBRIGHT_SOURCE_TYPE,
                    "source_mode": JOBRIGHT_SOURCE_MODE,
                    "observation_kind": JOBRIGHT_OBSERVATION_KIND_JOB_PAGE,
                    "jobright_job_id": recommendation.jobright_job_id,
                    "job_url": recommendation.job_url,
                    "page_payload": recommendation.page_payload,
                    "job_summary": {
                        "title": recommendation.role_title,
                        "company": recommendation.company_name,
                        "location": recommendation.location,
                        "salary": recommendation.salary,
                        "apply_url": recommendation.apply_url,
                    },
                    "social_connections": recommendation.social_connections,
                    "personal_social_connections": recommendation.personal_social_connections,
                    "jd_is_usable": recommendation.jd_is_usable,
                },
                produced_at=recommendation.observed_at,
            )
            if recommendation.jd_text:
                jd_path.parent.mkdir(parents=True, exist_ok=True)
                jd_path.write_text(recommendation.jd_text.strip() + "\n", encoding="utf-8")

            feed_observation_id = new_canonical_id("lead_source_observations")
            page_observation_id = new_canonical_id("lead_source_observations")
            timestamps = lifecycle_timestamps(recommendation.observed_at)
            public_connection_count = len(recommendation.social_connections)
            personal_connection_count = (
                len(recommendation.personal_social_connections.get("school", []))
                + len(recommendation.personal_social_connections.get("company", []))
                if recommendation.personal_social_connections
                else 0
            )
            total_connection_count = public_connection_count + personal_connection_count
            lead_status, reason_code = _initial_lead_status(recommendation)
            feed_summary_json = {
                "company": recommendation.company_name,
                "title": recommendation.role_title,
                "location": recommendation.location,
                "salary": recommendation.salary,
                "apply_url": recommendation.apply_url,
            }
            connection.execute(
                """
                INSERT INTO lead_source_observations (
                  source_observation_id, lead_id, ingestion_run_id, source_type,
                  source_reference, source_mode, source_url, observation_kind,
                  observed_at, jobright_job_id, apply_url, display_score, rank_desc,
                  recommendation_scores_json, skill_matching_scores_json,
                  industry_matching_scores_json, public_connection_count,
                  personal_connection_count, total_connection_count,
                  job_summary_json, jd_is_usable, promotion_eligibility_status,
                  promotion_hold_reason, source_payload_path, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    feed_observation_id,
                    lead_id,
                    batch.ingestion_run_id,
                    JOBRIGHT_SOURCE_TYPE,
                    JOBRIGHT_FEED_URL,
                    JOBRIGHT_SOURCE_MODE,
                    JOBRIGHT_RECOMMENDATIONS_PAGE_URL,
                    JOBRIGHT_OBSERVATION_KIND_FEED,
                    recommendation.observed_at,
                    recommendation.jobright_job_id,
                    recommendation.apply_url,
                    recommendation.display_score,
                    recommendation.rank_desc,
                    json.dumps(recommendation.recommendation_scores),
                    json.dumps(recommendation.skill_matching_scores),
                    json.dumps(recommendation.industry_matching_scores),
                    0,
                    0,
                    0,
                    json.dumps(feed_summary_json),
                    0,
                    JOBRIGHT_LEAD_STATUS_DISCOVERED,
                    None,
                    paths.relative_to_root(feed_artifact_path).as_posix(),
                    timestamps["created_at"],
                    timestamps["updated_at"],
                ),
            )
            connection.execute(
                """
                INSERT INTO lead_source_observations (
                  source_observation_id, lead_id, ingestion_run_id, source_type,
                  source_reference, source_mode, source_url, observation_kind,
                  observed_at, jobright_job_id, apply_url, display_score, rank_desc,
                  recommendation_scores_json, skill_matching_scores_json,
                  industry_matching_scores_json, public_connection_count,
                  personal_connection_count, total_connection_count,
                  job_summary_json, social_connections_json,
                  personal_social_connections_json, jd_artifact_path, jd_hash,
                  jd_is_usable, promotion_eligibility_status, promotion_hold_reason,
                  source_payload_path, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    page_observation_id,
                    lead_id,
                    batch.ingestion_run_id,
                    JOBRIGHT_SOURCE_TYPE,
                    recommendation.job_url,
                    JOBRIGHT_SOURCE_MODE,
                    recommendation.job_url,
                    JOBRIGHT_OBSERVATION_KIND_JOB_PAGE,
                    recommendation.observed_at,
                    recommendation.jobright_job_id,
                    recommendation.apply_url,
                    recommendation.display_score,
                    recommendation.rank_desc,
                    json.dumps(recommendation.recommendation_scores),
                    json.dumps(recommendation.skill_matching_scores),
                    json.dumps(recommendation.industry_matching_scores),
                    public_connection_count,
                    personal_connection_count,
                    total_connection_count,
                    json.dumps(feed_summary_json),
                    json.dumps(recommendation.social_connections),
                    json.dumps(recommendation.personal_social_connections or {}),
                    paths.relative_to_root(jd_path).as_posix() if recommendation.jd_text else None,
                    hashlib.sha256(recommendation.jd_text.encode("utf-8")).hexdigest()
                    if recommendation.jd_text
                    else None,
                    1 if recommendation.jd_is_usable else 0,
                    lead_status,
                    reason_code,
                    paths.relative_to_root(page_artifact_path).as_posix(),
                    timestamps["created_at"],
                    timestamps["updated_at"],
                ),
            )
            source_observations_written += 2

            contacts_linked += _sync_lead_contacts(
                connection,
                lead_id=lead_id,
                source_observation_id=page_observation_id,
                company_name=recommendation.company_name,
                social_connections=recommendation.social_connections,
                personal_social_connections=recommendation.personal_social_connections,
                timestamp=recommendation.observed_at,
            )

            source_contacts_payload = connection.execute(
                """
                SELECT lc.lead_contact_id, lc.contact_source_type, lc.contact_source_priority_tier,
                       lc.contact_source_rank, c.contact_id, c.full_name, c.position_title,
                       c.linkedin_url, c.company_name
                FROM lead_contacts lc
                JOIN contacts c
                  ON c.contact_id = lc.contact_id
                WHERE lc.lead_id = ?
                ORDER BY lc.contact_source_priority_tier ASC,
                         lc.contact_source_rank ASC,
                         lc.created_at ASC
                """,
                (lead_id,),
            ).fetchall()
            source_contacts = [
                {
                    "lead_contact_id": row["lead_contact_id"],
                    "contact_id": row["contact_id"],
                    "contact_source_type": row["contact_source_type"],
                    "contact_source_priority_tier": row["contact_source_priority_tier"],
                    "contact_source_rank": row["contact_source_rank"],
                    "full_name": row["full_name"],
                    "position_title": row["position_title"],
                    "linkedin_url": row["linkedin_url"],
                    "company_name": row["company_name"],
                }
                for row in source_contacts_payload
            ]
            source_contacts_path.parent.mkdir(parents=True, exist_ok=True)
            source_contacts_path.write_text(json.dumps(source_contacts, indent=2) + "\n", encoding="utf-8")

            source_observations = [
                {
                    "source_observation_id": feed_observation_id,
                    "observation_kind": JOBRIGHT_OBSERVATION_KIND_FEED,
                    "source_reference": JOBRIGHT_FEED_URL,
                    "source_url": JOBRIGHT_RECOMMENDATIONS_PAGE_URL,
                    "jobright_job_id": recommendation.jobright_job_id,
                    "display_score": recommendation.display_score,
                    "rank_desc": recommendation.rank_desc,
                    "source_payload_path": paths.relative_to_root(feed_artifact_path).as_posix(),
                },
                {
                    "source_observation_id": page_observation_id,
                    "observation_kind": JOBRIGHT_OBSERVATION_KIND_JOB_PAGE,
                    "source_reference": recommendation.job_url,
                    "source_url": recommendation.job_url,
                    "jobright_job_id": recommendation.jobright_job_id,
                    "display_score": recommendation.display_score,
                    "rank_desc": recommendation.rank_desc,
                    "source_payload_path": paths.relative_to_root(page_artifact_path).as_posix(),
                    "jd_artifact_path": paths.relative_to_root(jd_path).as_posix() if recommendation.jd_text else None,
                    "jd_is_usable": recommendation.jd_is_usable,
                },
            ]
            source_observations_path.parent.mkdir(parents=True, exist_ok=True)
            source_observations_path.write_text(
                json.dumps(source_observations, indent=2) + "\n",
                encoding="utf-8",
            )

            manifest_payload = {
                "lead_identity_key": recommendation.lead_identity_key,
                "lead_status": lead_status,
                "source_type": JOBRIGHT_SOURCE_TYPE,
                "source_mode": JOBRIGHT_SOURCE_MODE,
                "source_reference": JOBRIGHT_FEED_URL,
                "source_url": recommendation.job_url,
                "active_source_observation_id": page_observation_id,
                "lead_status_reason_code": reason_code,
                "company_name": recommendation.company_name,
                "role_title": recommendation.role_title,
                "location": recommendation.location,
                "display_score": recommendation.display_score,
                "rank_desc": recommendation.rank_desc,
                "connections": {
                    "public_count": public_connection_count,
                    "personal_count": personal_connection_count,
                    "total_count": total_connection_count,
                },
                "artifacts": {
                    "source_observations_path": paths.relative_to_root(source_observations_path).as_posix(),
                    "source_contacts_path": paths.relative_to_root(source_contacts_path).as_posix(),
                    "jd_path": paths.relative_to_root(jd_path).as_posix() if recommendation.jd_text else None,
                },
            }
            write_yaml_contract(
                lead_manifest_path,
                producer_component=JOBRIGHT_COMPONENT,
                result="ok",
                linkage=ArtifactLinkage(lead_id=lead_id),
                payload=manifest_payload,
                produced_at=recommendation.observed_at,
            )

            connection.execute(
                """
                UPDATE leads
                SET lead_status = ?,
                    source_reference = ?,
                    source_url = ?,
                    company_name = ?,
                    role_title = ?,
                    location = ?,
                    canonical_jd_artifact_path = ?,
                    active_source_observation_id = ?,
                    reason_code = ?,
                    latest_fit_score = ?,
                    latest_fit_label = ?,
                    latest_public_connection_count = ?,
                    latest_personal_connection_count = ?,
                    latest_total_connection_count = ?,
                    updated_at = ?
                WHERE lead_id = ?
                """,
                (
                    lead_status,
                    JOBRIGHT_FEED_URL,
                    recommendation.job_url,
                    recommendation.company_name,
                    recommendation.role_title,
                    recommendation.location,
                    paths.relative_to_root(jd_path).as_posix() if recommendation.jd_text else None,
                    page_observation_id,
                    reason_code,
                    recommendation.display_score,
                    recommendation.rank_desc,
                    public_connection_count,
                    personal_connection_count,
                    total_connection_count,
                    recommendation.observed_at,
                    lead_id,
                ),
            )

    connection.close()

    result_payload = {
        "ingestion_run_id": batch.ingestion_run_id,
        "leads_created": leads_created,
        "leads_updated": leads_updated,
        "source_observations_written": source_observations_written,
        "contacts_linked": contacts_linked,
        "lead_ids": lead_ids,
    }
    _write_jobright_run_artifacts(paths, batch, result_payload=result_payload)
    return JobrightIngestionResult(
        ingestion_run_id=batch.ingestion_run_id,
        result=batch.result,
        leads_created=leads_created,
        leads_updated=leads_updated,
        source_observations_written=source_observations_written,
        contacts_linked=contacts_linked,
        lead_ids=tuple(lead_ids),
    )
