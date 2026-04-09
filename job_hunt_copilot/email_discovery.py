from __future__ import annotations

import html
import json
import re
import sqlite3
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .artifacts import ArtifactLinkage, publish_json_artifact
from .delivery_feedback import (
    DISCOVERY_REUSE_STATE_BLOCKED_BOUNCED,
    DISCOVERY_REUSE_STATE_ELIGIBLE_NOT_BOUNCED,
    query_feedback_reuse_candidates,
)
from .outreach import evaluate_role_targeted_send_set
from .paths import ProjectPaths, workspace_slug
from .records import lifecycle_timestamps, new_canonical_id, now_utc_iso


EMAIL_DISCOVERY_COMPONENT = "email_discovery"
PEOPLE_SEARCH_ARTIFACT_TYPE = "people_search_result"
RECIPIENT_PROFILE_ARTIFACT_TYPE = "recipient_profile"
DISCOVERY_RESULT_ARTIFACT_TYPE = "discovery_result"
PROVIDER_NAME_APOLLO = "apollo"
PROVIDER_NAME_PROSPEO = "prospeo"
PROVIDER_NAME_GETPROSPECT = "getprospect"
PROVIDER_NAME_HUNTER = "hunter"
FEEDBACK_REUSE_PROVIDER_NAME = "delivery_feedback"

JOB_POSTING_STATUS_REQUIRES_CONTACTS = "requires_contacts"
JOB_POSTING_STATUS_READY_FOR_OUTREACH = "ready_for_outreach"
RESUME_REVIEW_STATUS_APPROVED = "approved"

CONTACT_STATUS_IDENTIFIED = "identified"
CONTACT_STATUS_WORKING_EMAIL_FOUND = "working_email_found"
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

DEFAULT_SHORTLIST_LIMIT = 6

DISCOVERY_OUTCOME_FOUND = "found"
DISCOVERY_OUTCOME_NOT_FOUND = "not_found"
DISCOVERY_OUTCOME_DOMAIN_UNRESOLVED = "domain_unresolved"
DISCOVERY_OUTCOME_INVALID_API_KEY = "invalid_api_key"
DISCOVERY_OUTCOME_RATE_LIMITED = "rate_limited"
DISCOVERY_OUTCOME_QUOTA_EXHAUSTED = "quota_exhausted"
DISCOVERY_OUTCOME_NETWORK_ERROR = "network_error"
DISCOVERY_OUTCOME_PROVIDER_ERROR = "provider_error"
DISCOVERY_OUTCOME_SKIPPED_BOUNCED_PROVIDER = "skipped_bounced_provider"
DISCOVERY_OUTCOME_BOUNCED_MATCH = "bounced_match"

EMAIL_FINDER_PROVIDER_ORDER = (
    PROVIDER_NAME_PROSPEO,
    PROVIDER_NAME_GETPROSPECT,
    PROVIDER_NAME_HUNTER,
)

APOLLO_COMPANY_SEARCH_URL = "https://api.apollo.io/api/v1/mixed_companies/search"
APOLLO_PEOPLE_SEARCH_URL = "https://api.apollo.io/api/v1/mixed_people/api_search"
APOLLO_PEOPLE_ENRICH_URL = "https://api.apollo.io/api/v1/people/match"
PROSPEO_ENRICH_URL = "https://api.prospeo.io/enrich-person"
PROSPEO_ACCOUNT_URL = "https://api.prospeo.io/account-information"
GETPROSPECT_EMAIL_FINDER_URL = "https://api.getprospect.com/v2/email-finder"
HUNTER_EMAIL_FINDER_URL = "https://api.hunter.io/v2/email-finder"
HUNTER_ACCOUNT_URL = "https://api.hunter.io/v2/account"

OBFUSCATED_NAME_RE = re.compile(r"[*•·]|(?:[A-Za-z]{2,}\*{2,})|(?:\*{2,}[A-Za-z]{2,})")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
WORD_RE = re.compile(r"[A-Za-z0-9]+")
HTML_TAG_RE = re.compile(r"<[^>]+>")
HTML_WS_RE = re.compile(r"\s+")
META_TAG_RE = re.compile(
    r"<meta\b[^>]*(?:property|name)\s*=\s*[\"'](?P<key>[^\"']+)[\"'][^>]*content\s*=\s*[\"'](?P<value>[^\"']*)[\"'][^>]*>",
    re.IGNORECASE,
)
JSON_LD_RE = re.compile(
    r"<script\b[^>]*type\s*=\s*[\"']application/ld\+json[\"'][^>]*>(?P<body>.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)
CONNECTIONS_RE = re.compile(r"(\d[\d,]*\+?)\s+connections", re.IGNORECASE)
FOLLOWERS_RE = re.compile(r"(\d[\d,]*)\s+followers", re.IGNORECASE)

SHORTLIST_BUCKETS = (
    ("recruiter", {RECIPIENT_TYPE_RECRUITER}, 2),
    ("manager_adjacent", {RECIPIENT_TYPE_HIRING_MANAGER}, 2),
    ("engineer", {RECIPIENT_TYPE_ENGINEER}, 2),
)
STOPWORD_TOKENS = frozenset(
    {
        "and",
        "or",
        "the",
        "with",
        "for",
        "to",
        "of",
        "a",
        "an",
        "senior",
        "sr",
        "staff",
        "principal",
        "lead",
        "ii",
        "iii",
        "iv",
    }
)


class EmailDiscoveryError(ValueError):
    """Raised when discovery bootstrap or provider normalization fails."""

    def __init__(self, message: str, *, reason_code: str | None = None) -> None:
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True)
class ApolloResolvedCompany:
    organization_id: str
    organization_name: str
    primary_domain: str | None = None
    website_url: str | None = None
    linkedin_url: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "organization_id": self.organization_id,
            "organization_name": self.organization_name,
            "primary_domain": self.primary_domain,
            "website_url": self.website_url,
            "linkedin_url": self.linkedin_url,
        }


@dataclass(frozen=True)
class PeopleSearchCandidate:
    provider_person_id: str | None
    display_name: str
    full_name: str | None
    linkedin_url: str | None
    title: str | None
    location: str | None
    has_email: bool
    email: str | None
    has_direct_phone: bool
    last_refreshed_at: str | None

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "PeopleSearchCandidate":
        provider_person_id = _normalize_optional_text(
            payload.get("provider_person_id") or payload.get("person_id") or payload.get("id")
        )
        display_name = (
            _normalize_optional_text(payload.get("display_name"))
            or _normalize_optional_text(payload.get("name"))
            or _combine_name_parts(payload)
            or _normalize_optional_text(payload.get("full_name"))
            or (
                f"Apollo person {provider_person_id}"
                if provider_person_id
                else None
            )
        )
        if display_name is None:
            raise EmailDiscoveryError("Apollo candidate rows must include a stable person id or display name.")

        full_name = _normalize_optional_text(payload.get("full_name"))
        if full_name is None and not _name_is_obfuscated(display_name) and " " in display_name:
            full_name = display_name
        email = _normalize_optional_text(payload.get("email") or payload.get("work_email"))
        has_email = _coerce_bool(payload.get("has_email")) or _is_usable_email(email)
        return cls(
            provider_person_id=provider_person_id,
            display_name=display_name,
            full_name=full_name if full_name and not _name_is_obfuscated(full_name) else None,
            linkedin_url=_normalize_optional_text(payload.get("linkedin_url")),
            title=_normalize_optional_text(payload.get("title") or payload.get("position_title")),
            location=_normalize_optional_text(payload.get("location")),
            has_email=has_email,
            email=email if _is_usable_email(email) else None,
            has_direct_phone=_coerce_bool(payload.get("has_direct_phone")),
            last_refreshed_at=_normalize_optional_text(
                payload.get("last_refreshed_at") or payload.get("updated_at")
            ),
        )

    @property
    def name_quality(self) -> str:
        if _name_is_obfuscated(self.display_name):
            return "provider_obfuscated"
        if self.full_name:
            return "provider_full"
        return "provider_sparse"

    @property
    def recipient_type(self) -> str:
        normalized = (self.title or "").lower()
        if "founder" in normalized or "co-founder" in normalized or "cofounder" in normalized:
            return RECIPIENT_TYPE_FOUNDER
        if any(token in normalized for token in ("recruit", "talent", "sourcer", "people ops")):
            return RECIPIENT_TYPE_RECRUITER
        if "alumni" in normalized:
            return RECIPIENT_TYPE_ALUMNI
        if any(token in normalized for token in ("manager", "director", "head", "vp", "vice president", "chief")):
            return RECIPIENT_TYPE_HIRING_MANAGER
        if any(token in normalized for token in ("engineer", "developer", "architect", "swe", "software")):
            return RECIPIENT_TYPE_ENGINEER
        return RECIPIENT_TYPE_OTHER_INTERNAL

    @property
    def relevance_reason(self) -> str:
        if self.recipient_type == RECIPIENT_TYPE_RECRUITER:
            return "Apollo title indicates a recruiting contact close to this role."
        if self.recipient_type == RECIPIENT_TYPE_HIRING_MANAGER:
            return "Apollo title indicates engineering leadership close to the likely hiring loop."
        if self.recipient_type == RECIPIENT_TYPE_ENGINEER:
            return "Apollo title indicates a role-relevant internal engineer."
        if self.recipient_type == RECIPIENT_TYPE_FOUNDER:
            return "Apollo title indicates founder-level routing context inside the company."
        if self.recipient_type == RECIPIENT_TYPE_ALUMNI:
            return "Apollo title indicates an alumni-style internal networking path."
        if self.title:
            return f"Apollo search returned this internal contact as `{self.title}`."
        return "Apollo search returned this internal contact for the company."

    def identity_key(self) -> str:
        if self.provider_person_id:
            return f"apollo_person|{self.provider_person_id}"
        if self.linkedin_url:
            return f"linkedin_profile|{workspace_slug(self.linkedin_url)}"
        return "|".join(
            [
                "apollo_search",
                workspace_slug(self.display_name),
                workspace_slug(self.title or "unknown"),
            ]
        )

    def as_artifact_dict(self, *, contact_id: str | None = None) -> dict[str, Any]:
        payload = {
            "provider_person_id": self.provider_person_id,
            "display_name": self.display_name,
            "name_quality": self.name_quality,
            "full_name": self.full_name,
            "linkedin_url": self.linkedin_url,
            "title": self.title,
            "recipient_type_inferred": self.recipient_type,
            "relevance_reason": self.relevance_reason,
            "has_email": self.has_email,
            "has_direct_phone": self.has_direct_phone,
            "last_refreshed_at": self.last_refreshed_at,
        }
        if contact_id:
            payload["contact_id"] = contact_id
        return payload


@dataclass(frozen=True)
class PeopleSearchRunResult:
    job_posting_id: str
    lead_id: str
    provider_name: str
    artifact_path: Path
    candidate_count: int
    shortlisted_contact_ids: tuple[str, ...]
    shortlisted_job_posting_contact_ids: tuple[str, ...]
    resolved_company: ApolloResolvedCompany | None


@dataclass(frozen=True)
class ApolloEnrichedPerson:
    provider_person_id: str | None
    display_name: str
    full_name: str | None
    first_name: str | None
    last_name: str | None
    linkedin_url: str | None
    title: str | None
    location: str | None
    email: str | None
    email_status: str | None
    headline: str | None
    organization_id: str | None
    organization_name: str | None

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ApolloEnrichedPerson | None":
        person_payload = payload.get("person") if isinstance(payload.get("person"), Mapping) else payload
        if not isinstance(person_payload, Mapping):
            return None

        provider_person_id = _normalize_optional_text(
            person_payload.get("provider_person_id")
            or person_payload.get("person_id")
            or person_payload.get("id")
        )
        display_name = (
            _normalize_optional_text(person_payload.get("display_name"))
            or _normalize_optional_text(person_payload.get("name"))
            or _combine_name_parts(person_payload)
        )
        full_name = _normalize_optional_text(person_payload.get("name") or person_payload.get("full_name"))
        if full_name is None and display_name and not _name_is_obfuscated(display_name) and " " in display_name:
            full_name = display_name

        first_name = _normalize_optional_text(person_payload.get("first_name"))
        last_name = _normalize_optional_text(person_payload.get("last_name"))
        if first_name is None or last_name is None:
            inferred_first, inferred_last = _split_name(full_name or display_name or "")
            first_name = first_name or inferred_first
            last_name = last_name or inferred_last

        organization_payload = person_payload.get("organization")
        organization_id = _normalize_optional_text(person_payload.get("organization_id"))
        organization_name = _normalize_optional_text(person_payload.get("organization_name"))
        if isinstance(organization_payload, Mapping):
            organization_id = organization_id or _normalize_optional_text(
                organization_payload.get("id") or organization_payload.get("organization_id")
            )
            organization_name = organization_name or _normalize_optional_text(
                organization_payload.get("name") or organization_payload.get("organization_name")
            )

        if display_name is None and full_name is None and provider_person_id is None:
            return None

        return cls(
            provider_person_id=provider_person_id,
            display_name=display_name or full_name or f"Apollo person {provider_person_id}",
            full_name=full_name if full_name and not _name_is_obfuscated(full_name) else None,
            first_name=first_name,
            last_name=last_name,
            linkedin_url=_normalize_optional_text(person_payload.get("linkedin_url")),
            title=_normalize_optional_text(person_payload.get("title")),
            location=_apollo_enriched_location(person_payload),
            email=_normalize_optional_text(person_payload.get("email")),
            email_status=_normalize_optional_text(person_payload.get("email_status")),
            headline=_normalize_optional_text(person_payload.get("headline")),
            organization_id=organization_id,
            organization_name=organization_name,
        )

    @property
    def name_quality(self) -> str:
        if _name_is_obfuscated(self.display_name):
            return "provider_obfuscated"
        if self.full_name:
            return "provider_full"
        return "provider_sparse"


@dataclass(frozen=True)
class ContactEnrichmentRunResult:
    job_posting_id: str
    lead_id: str
    processed_contact_ids: tuple[str, ...]
    enriched_contact_ids: tuple[str, ...]
    recipient_profile_contact_ids: tuple[str, ...]
    removed_contact_ids: tuple[str, ...]
    removed_job_posting_contact_ids: tuple[str, ...]
    posting_status: str


@dataclass(frozen=True)
class EmailDiscoveryProviderResult:
    provider_name: str
    outcome: str
    email: str | None = None
    provider_verification_status: str | None = None
    provider_score: str | None = None
    detected_pattern: str | None = None
    remaining_credits: int | None = None
    credit_limit: int | None = None
    reset_at: str | None = None
    message: str | None = None

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, Any],
        *,
        provider_name: str,
    ) -> "EmailDiscoveryProviderResult":
        return cls(
            provider_name=provider_name,
            outcome=_normalize_optional_text(payload.get("outcome")) or DISCOVERY_OUTCOME_PROVIDER_ERROR,
            email=_normalize_optional_text(payload.get("email")),
            provider_verification_status=_normalize_optional_text(payload.get("provider_verification_status")),
            provider_score=_normalize_optional_text(payload.get("provider_score")),
            detected_pattern=_normalize_optional_text(payload.get("detected_pattern")),
            remaining_credits=_normalize_optional_int(payload.get("remaining_credits")),
            credit_limit=_normalize_optional_int(payload.get("credit_limit")),
            reset_at=_normalize_optional_text(payload.get("reset_at")),
            message=_normalize_optional_text(payload.get("message")),
        )

    @property
    def is_found(self) -> bool:
        return self.outcome == DISCOVERY_OUTCOME_FOUND and _is_usable_email(self.email)


@dataclass(frozen=True)
class EmailDiscoveryRunResult:
    job_posting_id: str
    lead_id: str
    contact_id: str
    job_posting_contact_id: str
    discovery_attempt_id: str
    artifact_path: Path
    outcome: str
    provider_name: str | None
    email: str | None
    attempted_provider_names: tuple[str, ...]
    posting_status: str
    contact_status: str
    link_level_status: str
    reused_existing_email: bool


@dataclass(frozen=True)
class GeneralLearningEmailDiscoveryRunResult:
    contact_id: str
    discovery_attempt_id: str
    artifact_path: Path
    outcome: str
    provider_name: str | None
    email: str | None
    attempted_provider_names: tuple[str, ...]
    contact_status: str
    reused_existing_email: bool


class ApolloPeopleSearchProvider(Protocol):
    def resolve_company(
        self,
        *,
        company_name: str,
        company_domain: str | None,
        company_website: str | None,
    ) -> ApolloResolvedCompany | None:
        ...

    def search_people(
        self,
        *,
        company_name: str,
        resolved_company: ApolloResolvedCompany | None,
        search_filters: Mapping[str, Any],
    ) -> Sequence[PeopleSearchCandidate | Mapping[str, Any]]:
        ...


class ApolloContactEnrichmentProvider(Protocol):
    def enrich_person(
        self,
        *,
        provider_person_id: str | None,
        linkedin_url: str | None,
        person_name: str | None,
        company_domain: str | None,
        company_name: str | None,
    ) -> ApolloEnrichedPerson | Mapping[str, Any] | None:
        ...


class RecipientProfileExtractor(Protocol):
    def extract_profile(
        self,
        *,
        linkedin_url: str,
        contact: Mapping[str, Any],
        posting: Mapping[str, Any],
    ) -> Mapping[str, Any] | None:
        ...


class EmailFinderProvider(Protocol):
    provider_name: str
    requires_domain: bool

    def discover_email(
        self,
        *,
        contact: Mapping[str, Any],
        posting: Mapping[str, Any],
        company_domain: str | None,
        company_name: str | None,
    ) -> EmailDiscoveryProviderResult | Mapping[str, Any]:
        ...


def _request_json(
    request: Request,
    *,
    timeout_seconds: float,
    provider_label: str,
    http_error_map: Mapping[int, str],
) -> Mapping[str, Any]:
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            response_body = response.read().decode("utf-8")
            status_code = response.getcode()
    except HTTPError as exc:  # pragma: no cover - covered via normalization logic only
        reason_code = http_error_map.get(exc.code, DISCOVERY_OUTCOME_PROVIDER_ERROR)
        raise EmailDiscoveryError(
            f"{provider_label} request failed with HTTP {exc.code}.",
            reason_code=reason_code,
        ) from exc
    except URLError as exc:  # pragma: no cover - covered via normalization logic only
        raise EmailDiscoveryError(
            f"{provider_label} request failed with a network error.",
            reason_code=DISCOVERY_OUTCOME_NETWORK_ERROR,
        ) from exc

    if status_code != 200:  # pragma: no cover - defensive guard
        raise EmailDiscoveryError(
            f"{provider_label} request returned unexpected status {status_code}.",
            reason_code=DISCOVERY_OUTCOME_PROVIDER_ERROR,
        )
    try:
        payload = json.loads(response_body)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive guard
        raise EmailDiscoveryError(
            f"{provider_label} returned malformed JSON.",
            reason_code=DISCOVERY_OUTCOME_PROVIDER_ERROR,
        ) from exc
    if not isinstance(payload, Mapping):
        raise EmailDiscoveryError(
            f"{provider_label} returned a malformed top-level response body.",
            reason_code=DISCOVERY_OUTCOME_PROVIDER_ERROR,
        )
    return payload


def _load_provider_secret_payload(
    paths: ProjectPaths,
    *,
    filename: str,
    provider_label: str,
    reason_code_prefix: str,
) -> Mapping[str, Any]:
    secret_path = paths.secrets_dir / filename
    if not secret_path.exists():
        raise EmailDiscoveryError(
            f"{provider_label} secret file was not found at `{secret_path}`.",
            reason_code=f"missing_{reason_code_prefix}_secret",
        )
    payload = json.loads(secret_path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise EmailDiscoveryError(
            f"{provider_label} secret file must contain a JSON object.",
            reason_code=f"missing_{reason_code_prefix}_secret",
        )
    return payload


class ConfiguredApolloClient:
    def __init__(self, *, api_key: str, timeout_seconds: float = 30.0) -> None:
        if not api_key.strip():
            raise EmailDiscoveryError("Apollo API key is required for company-scoped people search.")
        self.api_key = api_key.strip()
        self.timeout_seconds = timeout_seconds

    @classmethod
    def from_paths(cls, paths: ProjectPaths) -> "ConfiguredApolloClient":
        payload = _load_provider_secret_payload(
            paths,
            filename="apollo_keys.json",
            provider_label="Apollo",
            reason_code_prefix="apollo",
        )
        api_key = _normalize_optional_text(payload.get("api_key"))
        if api_key is None:
            raise EmailDiscoveryError(
                "Apollo secret file does not include `api_key`.",
                reason_code="missing_apollo_api_key",
            )
        return cls(api_key=api_key)

    def resolve_company(
        self,
        *,
        company_name: str,
        company_domain: str | None,
        company_website: str | None,
    ) -> ApolloResolvedCompany | None:
        payload: dict[str, Any] = {
            "page": 1,
            "per_page": 5,
            "q_organization_name": company_name,
        }
        if company_domain:
            payload["q_website"] = company_domain
        elif company_website:
            payload["q_website"] = company_website

        response = self._post_json(APOLLO_COMPANY_SEARCH_URL, payload)
        company_rows = _extract_sequence(
            response,
            ("organizations", "accounts", "companies", "results"),
        )
        if not company_rows:
            return None

        top_result = company_rows[0]
        if not isinstance(top_result, Mapping):
            return None

        organization_id = _normalize_optional_text(
            top_result.get("organization_id") or top_result.get("id")
        )
        organization_name = _normalize_optional_text(
            top_result.get("organization_name") or top_result.get("name")
        ) or company_name
        if not organization_id:
            return None

        return ApolloResolvedCompany(
            organization_id=organization_id,
            organization_name=organization_name,
            primary_domain=_normalize_optional_text(
                top_result.get("primary_domain") or top_result.get("website_domain")
            ),
            website_url=_normalize_optional_text(
                top_result.get("website_url") or top_result.get("website")
            ),
            linkedin_url=_normalize_optional_text(
                top_result.get("linkedin_url") or top_result.get("linkedin_company_url")
            ),
        )

    def search_people(
        self,
        *,
        company_name: str,
        resolved_company: ApolloResolvedCompany | None,
        search_filters: Mapping[str, Any],
    ) -> Sequence[PeopleSearchCandidate]:
        payload: dict[str, Any] = {
            "page": 1,
            "per_page": 100,
            "person_titles": list(search_filters.get("titles") or []),
            "person_functions": list(search_filters.get("functions") or []),
            "person_seniorities": list(search_filters.get("seniority_levels") or []),
        }
        locations = list(search_filters.get("locations") or [])
        if locations:
            payload["person_locations"] = locations
        if resolved_company is not None:
            payload["organization_ids"] = [resolved_company.organization_id]
        else:
            payload["q_organization_name"] = company_name

        response = self._post_json(APOLLO_PEOPLE_SEARCH_URL, payload)
        people_rows = _extract_sequence(response, ("people", "contacts", "results"))
        candidates: list[PeopleSearchCandidate] = []
        for row in people_rows:
            if isinstance(row, Mapping):
                candidates.append(PeopleSearchCandidate.from_mapping(row))
        return candidates

    def enrich_person(
        self,
        *,
        provider_person_id: str | None,
        linkedin_url: str | None,
        person_name: str | None,
        company_domain: str | None,
        company_name: str | None,
    ) -> ApolloEnrichedPerson | None:
        query_params: dict[str, str] = {
            "reveal_personal_emails": "false",
            "reveal_phone_number": "false",
        }
        if provider_person_id:
            query_params["id"] = provider_person_id
        elif linkedin_url:
            query_params["linkedin_url"] = linkedin_url
        elif person_name:
            query_params["name"] = person_name
            if company_domain:
                query_params["domain"] = company_domain
            elif company_name:
                query_params["organization_name"] = company_name
        else:
            return None

        response = self._post_query(APOLLO_PEOPLE_ENRICH_URL, query_params)
        normalized = ApolloEnrichedPerson.from_mapping(response)
        return normalized

    def _post_json(self, url: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
            },
            method="POST",
        )
        return _request_json(
            request,
            timeout_seconds=self.timeout_seconds,
            provider_label="Apollo",
            http_error_map={
                401: DISCOVERY_OUTCOME_INVALID_API_KEY,
                403: "plan_restricted",
                429: DISCOVERY_OUTCOME_RATE_LIMITED,
            },
        )

    def _post_query(self, url: str, query_params: Mapping[str, Any]) -> Mapping[str, Any]:
        request_url = f"{url}?{urlencode(query_params, doseq=True)}"
        request = Request(
            request_url,
            data=b"",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Cache-Control": "no-cache",
                "x-api-key": self.api_key,
            },
            method="POST",
        )
        return _request_json(
            request,
            timeout_seconds=self.timeout_seconds,
            provider_label="Apollo",
            http_error_map={
                401: DISCOVERY_OUTCOME_INVALID_API_KEY,
                403: "plan_restricted",
                429: DISCOVERY_OUTCOME_RATE_LIMITED,
            },
        )


class LinkedInPublicProfileExtractor:
    def __init__(self, *, timeout_seconds: float = 20.0) -> None:
        self.timeout_seconds = timeout_seconds

    def extract_profile(
        self,
        *,
        linkedin_url: str,
        contact: Mapping[str, Any],
        posting: Mapping[str, Any],
    ) -> Mapping[str, Any] | None:
        request = Request(
            linkedin_url,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-US,en;q=0.9",
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
            },
            method="GET",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                html_text = response.read().decode("utf-8", errors="replace")
        except (HTTPError, URLError, ValueError):
            return None

        profile = _extract_linkedin_public_profile(
            html_text,
            linkedin_url=linkedin_url,
            contact=contact,
            posting=posting,
        )
        if profile is None:
            return None
        return {
            "profile_source": "linkedin_public_profile",
            "source_method": "public_profile_html",
            "profile": profile,
        }


class ConfiguredProspeoClient:
    provider_name = PROVIDER_NAME_PROSPEO
    requires_domain = True

    def __init__(self, *, api_key: str, timeout_seconds: float = 30.0) -> None:
        if not api_key.strip():
            raise EmailDiscoveryError("Prospeo API key is required for person-scoped email discovery.")
        self.api_key = api_key.strip()
        self.timeout_seconds = timeout_seconds

    @classmethod
    def from_paths(cls, paths: ProjectPaths) -> "ConfiguredProspeoClient":
        payload = _load_provider_secret_payload(
            paths,
            filename="prospeo_keys.json",
            provider_label="Prospeo",
            reason_code_prefix="prospeo",
        )
        api_key = _normalize_optional_text(payload.get("api_key"))
        if api_key is None:
            raise EmailDiscoveryError(
                "Prospeo secret file does not include `api_key`.",
                reason_code="missing_prospeo_api_key",
            )
        return cls(api_key=api_key)

    def discover_email(
        self,
        *,
        contact: Mapping[str, Any],
        posting: Mapping[str, Any],
        company_domain: str | None,
        company_name: str | None,
    ) -> EmailDiscoveryProviderResult:
        linkedin_url = _normalize_optional_text(contact.get("linkedin_url"))
        first_name, last_name = _contact_name_parts(contact)
        if linkedin_url:
            payload = {
                "only_verified_email": True,
                "data": {"linkedin_url": linkedin_url},
            }
        elif company_domain and first_name and last_name:
            payload = {
                "only_verified_email": True,
                "data": {
                    "first_name": first_name,
                    "last_name": last_name,
                    "company_website": company_domain,
                },
            }
        elif company_domain is None:
            return EmailDiscoveryProviderResult(
                provider_name=self.provider_name,
                outcome=DISCOVERY_OUTCOME_DOMAIN_UNRESOLVED,
            )
        else:
            return EmailDiscoveryProviderResult(
                provider_name=self.provider_name,
                outcome=DISCOVERY_OUTCOME_NOT_FOUND,
            )

        try:
            response = self._post_json(PROSPEO_ENRICH_URL, payload)
        except EmailDiscoveryError as exc:
            return EmailDiscoveryProviderResult(
                provider_name=self.provider_name,
                outcome=exc.reason_code or DISCOVERY_OUTCOME_PROVIDER_ERROR,
                message=str(exc),
            )

        result = _normalize_prospeo_discovery_result(response, company_domain=company_domain)
        budget_snapshot = self._fetch_budget_snapshot()
        if budget_snapshot:
            result = replace(
                result,
                remaining_credits=budget_snapshot["remaining_credits"],
                credit_limit=budget_snapshot["credit_limit"],
                reset_at=budget_snapshot["reset_at"],
            )
        return result

    def _post_json(self, url: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-KEY": self.api_key,
            },
            method="POST",
        )
        return _request_json(
            request,
            timeout_seconds=self.timeout_seconds,
            provider_label="Prospeo",
            http_error_map={
                401: DISCOVERY_OUTCOME_INVALID_API_KEY,
                429: DISCOVERY_OUTCOME_RATE_LIMITED,
            },
        )

    def _fetch_budget_snapshot(self) -> dict[str, int | str | None] | None:
        request = Request(
            PROSPEO_ACCOUNT_URL,
            headers={
                "Accept": "application/json",
                "X-KEY": self.api_key,
            },
            method="GET",
        )
        try:
            payload = _request_json(
                request,
                timeout_seconds=self.timeout_seconds,
                provider_label="Prospeo",
                http_error_map={
                    401: DISCOVERY_OUTCOME_INVALID_API_KEY,
                    429: DISCOVERY_OUTCOME_RATE_LIMITED,
                },
            )
        except EmailDiscoveryError:
            return None
        return _extract_budget_snapshot(
            payload,
            remaining_paths=(
                ("credits", "remaining"),
                ("data", "credits", "remaining"),
                ("remaining_credits",),
                ("remaining",),
            ),
            limit_paths=(
                ("credits", "limit"),
                ("data", "credits", "limit"),
                ("credit_limit",),
                ("limit",),
            ),
            reset_paths=(
                ("credits", "reset_at"),
                ("data", "credits", "reset_at"),
                ("reset_at",),
                ("next_quota_renewal_date",),
            ),
        )


class ConfiguredGetProspectClient:
    provider_name = PROVIDER_NAME_GETPROSPECT
    requires_domain = True

    def __init__(self, *, api_key: str, timeout_seconds: float = 30.0) -> None:
        if not api_key.strip():
            raise EmailDiscoveryError("GetProspect API key is required for person-scoped email discovery.")
        self.api_key = api_key.strip()
        self.timeout_seconds = timeout_seconds

    @classmethod
    def from_paths(cls, paths: ProjectPaths) -> "ConfiguredGetProspectClient":
        payload = _load_provider_secret_payload(
            paths,
            filename="getprospect_keys.json",
            provider_label="GetProspect",
            reason_code_prefix="getprospect",
        )
        api_key = _normalize_optional_text(payload.get("api_key"))
        if api_key is None:
            raise EmailDiscoveryError(
                "GetProspect secret file does not include `api_key`.",
                reason_code="missing_getprospect_api_key",
            )
        return cls(api_key=api_key)

    def discover_email(
        self,
        *,
        contact: Mapping[str, Any],
        posting: Mapping[str, Any],
        company_domain: str | None,
        company_name: str | None,
    ) -> EmailDiscoveryProviderResult:
        full_name = _best_known_contact_name(contact)
        if company_domain is None:
            return EmailDiscoveryProviderResult(
                provider_name=self.provider_name,
                outcome=DISCOVERY_OUTCOME_DOMAIN_UNRESOLVED,
            )
        if full_name is None:
            return EmailDiscoveryProviderResult(
                provider_name=self.provider_name,
                outcome=DISCOVERY_OUTCOME_NOT_FOUND,
            )

        query_params = {
            "full_name": full_name,
            "domain": company_domain,
            "api_key": self.api_key,
        }
        request = Request(
            f"{GETPROSPECT_EMAIL_FINDER_URL}?{urlencode(query_params)}",
            headers={"Accept": "application/json"},
            method="GET",
        )
        try:
            response = _request_json(
                request,
                timeout_seconds=self.timeout_seconds,
                provider_label="GetProspect",
                http_error_map={
                    401: DISCOVERY_OUTCOME_INVALID_API_KEY,
                    429: DISCOVERY_OUTCOME_RATE_LIMITED,
                },
            )
        except EmailDiscoveryError as exc:
            return EmailDiscoveryProviderResult(
                provider_name=self.provider_name,
                outcome=exc.reason_code or DISCOVERY_OUTCOME_PROVIDER_ERROR,
                message=str(exc),
            )

        return _normalize_getprospect_discovery_result(response, company_domain=company_domain)


class ConfiguredHunterClient:
    provider_name = PROVIDER_NAME_HUNTER
    requires_domain = False

    def __init__(self, *, api_keys: Sequence[str], timeout_seconds: float = 30.0) -> None:
        normalized_keys = [key.strip() for key in api_keys if key and key.strip()]
        if not normalized_keys:
            raise EmailDiscoveryError("At least one Hunter API key is required for person-scoped email discovery.")
        self.api_keys = tuple(normalized_keys)
        self.timeout_seconds = timeout_seconds

    @classmethod
    def from_paths(cls, paths: ProjectPaths) -> "ConfiguredHunterClient":
        payload = _load_provider_secret_payload(
            paths,
            filename="hunter_keys.json",
            provider_label="Hunter",
            reason_code_prefix="hunter",
        )
        keys_payload = payload.get("keys")
        if isinstance(keys_payload, Sequence) and not isinstance(keys_payload, (str, bytes)):
            api_keys = [_normalize_optional_text(value) or "" for value in keys_payload]
        else:
            api_key = _normalize_optional_text(payload.get("api_key"))
            api_keys = [api_key or ""]
        return cls(api_keys=api_keys)

    def discover_email(
        self,
        *,
        contact: Mapping[str, Any],
        posting: Mapping[str, Any],
        company_domain: str | None,
        company_name: str | None,
    ) -> EmailDiscoveryProviderResult:
        first_name, last_name = _contact_name_parts(contact)
        if first_name is None or last_name is None:
            return EmailDiscoveryProviderResult(
                provider_name=self.provider_name,
                outcome=DISCOVERY_OUTCOME_NOT_FOUND,
            )

        last_result = EmailDiscoveryProviderResult(
            provider_name=self.provider_name,
            outcome=DISCOVERY_OUTCOME_PROVIDER_ERROR,
        )
        for api_key in self.api_keys:
            query_params: dict[str, str] = {
                "first_name": first_name,
                "last_name": last_name,
                "api_key": api_key,
            }
            if company_domain:
                query_params["domain"] = company_domain
            elif company_name:
                query_params["company"] = company_name

            request = Request(
                f"{HUNTER_EMAIL_FINDER_URL}?{urlencode(query_params)}",
                headers={"Accept": "application/json"},
                method="GET",
            )
            try:
                response = _request_json(
                    request,
                    timeout_seconds=self.timeout_seconds,
                    provider_label="Hunter",
                    http_error_map={
                        401: DISCOVERY_OUTCOME_INVALID_API_KEY,
                        403: DISCOVERY_OUTCOME_RATE_LIMITED,
                        429: DISCOVERY_OUTCOME_QUOTA_EXHAUSTED,
                    },
                )
                last_result = _normalize_hunter_discovery_result(response, company_domain=company_domain)
            except EmailDiscoveryError as exc:
                last_result = EmailDiscoveryProviderResult(
                    provider_name=self.provider_name,
                    outcome=exc.reason_code or DISCOVERY_OUTCOME_PROVIDER_ERROR,
                    message=str(exc),
                )

            budget_snapshot = self._fetch_budget_snapshot(api_key)
            if budget_snapshot:
                last_result = replace(
                    last_result,
                    remaining_credits=budget_snapshot["remaining_credits"],
                    credit_limit=budget_snapshot["credit_limit"],
                    reset_at=budget_snapshot["reset_at"],
                )
            if last_result.outcome not in {
                DISCOVERY_OUTCOME_INVALID_API_KEY,
                DISCOVERY_OUTCOME_RATE_LIMITED,
                DISCOVERY_OUTCOME_QUOTA_EXHAUSTED,
            }:
                return last_result
        return last_result

    def _fetch_budget_snapshot(self, api_key: str) -> dict[str, int | str | None] | None:
        request = Request(
            f"{HUNTER_ACCOUNT_URL}?{urlencode({'api_key': api_key})}",
            headers={"Accept": "application/json"},
            method="GET",
        )
        try:
            payload = _request_json(
                request,
                timeout_seconds=self.timeout_seconds,
                provider_label="Hunter",
                http_error_map={
                    401: DISCOVERY_OUTCOME_INVALID_API_KEY,
                    403: DISCOVERY_OUTCOME_RATE_LIMITED,
                    429: DISCOVERY_OUTCOME_QUOTA_EXHAUSTED,
                },
            )
        except EmailDiscoveryError:
            return None
        return _extract_budget_snapshot(
            payload,
            remaining_paths=(
                ("data", "calls", "searches", "remaining"),
                ("data", "searches", "left"),
                ("data", "available_searches"),
                ("searches", "left"),
            ),
            limit_paths=(
                ("data", "calls", "searches", "limit"),
                ("data", "searches", "limit"),
                ("data", "searches", "total"),
                ("searches", "total"),
            ),
            reset_paths=(
                ("data", "reset_date",),
                ("data", "plan", "reset_date"),
                ("reset_date",),
            ),
        )


def run_apollo_people_search(
    *,
    project_root: Path | str,
    job_posting_id: str,
    provider: ApolloPeopleSearchProvider | None = None,
    shortlist_limit: int = DEFAULT_SHORTLIST_LIMIT,
    current_time: str | None = None,
) -> PeopleSearchRunResult:
    if shortlist_limit <= 0:
        raise EmailDiscoveryError("shortlist_limit must be greater than zero.")

    paths = ProjectPaths.from_root(project_root)
    connection = sqlite3.connect(paths.db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")

    try:
        posting_row = _load_search_ready_posting(connection, job_posting_id=job_posting_id)
        jd_text = _load_posting_jd(paths, posting_row)
        search_filters = _build_apollo_search_filters(posting_row, jd_text=jd_text, shortlist_limit=shortlist_limit)
        company_domain = _derive_company_domain(posting_row)
        company_website = _derive_company_website(posting_row)
        search_provider = provider or ConfiguredApolloClient.from_paths(paths)

        resolved_company = search_provider.resolve_company(
            company_name=posting_row["company_name"],
            company_domain=company_domain,
            company_website=company_website,
        )
        raw_candidates = search_provider.search_people(
            company_name=posting_row["company_name"],
            resolved_company=resolved_company,
            search_filters=search_filters,
        )
        candidates = tuple(_normalize_candidate_rows(raw_candidates))
        shortlist = select_initial_enrichment_shortlist(candidates, limit=shortlist_limit)
        timestamp = current_time or now_utc_iso()

        shortlisted_contact_ids: list[str] = []
        shortlisted_job_posting_contact_ids: list[str] = []
        shortlisted_candidate_ids: dict[str, str] = {}
        with connection:
            for candidate in shortlist:
                materialized = _materialize_shortlisted_candidate(
                    connection,
                    posting_row=posting_row,
                    candidate=candidate,
                    current_time=timestamp,
                )
                shortlisted_contact_ids.append(materialized["contact_id"])
                shortlisted_job_posting_contact_ids.append(materialized["job_posting_contact_id"])
                if candidate.provider_person_id:
                    shortlisted_candidate_ids[candidate.provider_person_id] = materialized["contact_id"]
                else:
                    shortlisted_candidate_ids[candidate.identity_key()] = materialized["contact_id"]

        artifact_path = (
            paths.discovery_workspace_dir(posting_row["company_name"], posting_row["role_title"])
            / "people_search_result.json"
        )
        candidate_payload = []
        for candidate in candidates:
            lookup_key = candidate.provider_person_id or candidate.identity_key()
            candidate_payload.append(
                candidate.as_artifact_dict(contact_id=shortlisted_candidate_ids.get(lookup_key))
            )

        with connection:
            connection.execute(
                """
                DELETE FROM artifact_records
                WHERE artifact_type = ? AND job_posting_id = ?
                """,
                (
                    PEOPLE_SEARCH_ARTIFACT_TYPE,
                    posting_row["job_posting_id"],
                ),
            )

        publish_json_artifact(
            connection,
            paths,
            artifact_type=PEOPLE_SEARCH_ARTIFACT_TYPE,
            artifact_path=artifact_path,
            producer_component=EMAIL_DISCOVERY_COMPONENT,
            result="success",
            linkage=ArtifactLinkage(
                lead_id=posting_row["lead_id"],
                job_posting_id=posting_row["job_posting_id"],
            ),
            payload={
                "company_name": posting_row["company_name"],
                "provider_name": PROVIDER_NAME_APOLLO,
                "resolved_company": resolved_company.as_dict() if resolved_company else None,
                "search_anchor": (
                    "organization_id"
                    if resolved_company is not None
                    else "company_name_fallback"
                ),
                "applied_filters": search_filters,
                "shortlist_limit": shortlist_limit,
                "candidate_count": len(candidates),
                "shortlisted_contact_ids": shortlisted_contact_ids,
                "shortlisted_job_posting_contact_ids": shortlisted_job_posting_contact_ids,
                "candidates": candidate_payload,
            },
            produced_at=timestamp,
        )

        return PeopleSearchRunResult(
            job_posting_id=posting_row["job_posting_id"],
            lead_id=posting_row["lead_id"],
            provider_name=PROVIDER_NAME_APOLLO,
            artifact_path=artifact_path,
            candidate_count=len(candidates),
            shortlisted_contact_ids=tuple(shortlisted_contact_ids),
            shortlisted_job_posting_contact_ids=tuple(shortlisted_job_posting_contact_ids),
            resolved_company=resolved_company,
        )
    finally:
        connection.close()


def run_apollo_contact_enrichment(
    *,
    project_root: Path | str,
    job_posting_id: str,
    provider: ApolloContactEnrichmentProvider | None = None,
    recipient_profile_extractor: RecipientProfileExtractor | None = None,
    current_time: str | None = None,
) -> ContactEnrichmentRunResult:
    paths = ProjectPaths.from_root(project_root)
    connection = sqlite3.connect(paths.db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")

    try:
        posting_row = dict(_load_search_ready_posting(connection, job_posting_id=job_posting_id))
        shortlisted_rows = _load_shortlisted_contact_rows(connection, job_posting_id=job_posting_id)
        timestamp = current_time or now_utc_iso()

        provider_client = provider
        profile_extractor = recipient_profile_extractor or LinkedInPublicProfileExtractor()

        people_search_payload = _load_people_search_payload(paths, posting_row)
        company_domain = (
            _normalize_optional_text((people_search_payload.get("resolved_company") or {}).get("primary_domain"))
            if isinstance(people_search_payload.get("resolved_company"), Mapping)
            else None
        ) or _derive_company_domain(posting_row)

        processed_contact_ids: list[str] = []
        enriched_contact_ids: list[str] = []
        recipient_profile_contact_ids: list[str] = []
        removed_contact_ids: list[str] = []
        removed_job_posting_contact_ids: list[str] = []

        for contact_row in shortlisted_rows:
            processed_contact_ids.append(str(contact_row["contact_id"]))
            refreshed_row = contact_row

            if _needs_apollo_contact_enrichment(refreshed_row):
                if provider_client is None:
                    provider_client = ConfiguredApolloClient.from_paths(paths)
                enriched_payload = provider_client.enrich_person(
                    provider_person_id=_normalize_optional_text(refreshed_row["provider_person_id"]),
                    linkedin_url=_normalize_optional_text(refreshed_row["linkedin_url"]),
                    person_name=_best_known_contact_name(refreshed_row),
                    company_domain=company_domain,
                    company_name=_normalize_optional_text(posting_row["company_name"]),
                )
                normalized_enrichment = _normalize_enriched_person(enriched_payload)
                if normalized_enrichment is not None:
                    with connection:
                        _apply_contact_enrichment(
                            connection,
                            contact_row=refreshed_row,
                            posting_row=posting_row,
                            enrichment=normalized_enrichment,
                            current_time=timestamp,
                        )
                    enriched_contact_ids.append(str(refreshed_row["contact_id"]))
                elif _is_terminal_enrichment_dead_end(refreshed_row):
                    with connection:
                        cleanup_result = _remove_terminal_shortlist_dead_end(
                            connection,
                            paths,
                            posting_row=posting_row,
                            contact_row=refreshed_row,
                        )
                    removed_job_posting_contact_ids.append(cleanup_result["job_posting_contact_id"])
                    if cleanup_result.get("removed_contact_id"):
                        removed_contact_ids.append(cleanup_result["removed_contact_id"])
                    continue

            refreshed_row = _load_shortlisted_contact_row(
                connection,
                job_posting_contact_id=str(contact_row["job_posting_contact_id"]),
            )
            if refreshed_row is None:
                continue
            if _is_terminal_enrichment_dead_end(refreshed_row):
                with connection:
                    cleanup_result = _remove_terminal_shortlist_dead_end(
                        connection,
                        paths,
                        posting_row=posting_row,
                        contact_row=refreshed_row,
                    )
                removed_job_posting_contact_ids.append(cleanup_result["job_posting_contact_id"])
                if cleanup_result.get("removed_contact_id"):
                    removed_contact_ids.append(cleanup_result["removed_contact_id"])
                continue

            with connection:
                _promote_contact_to_working_email_found_if_ready(
                    connection,
                    posting_row=posting_row,
                    contact_row=refreshed_row,
                    current_time=timestamp,
                )

            refreshed_row = _load_shortlisted_contact_row(
                connection,
                job_posting_contact_id=str(contact_row["job_posting_contact_id"]),
            )
            if refreshed_row is None:
                continue

            if _should_capture_recipient_profile(
                connection,
                paths,
                posting_row=posting_row,
                contact_row=refreshed_row,
            ):
                profile_payload = profile_extractor.extract_profile(
                    linkedin_url=str(refreshed_row["linkedin_url"]),
                    contact=refreshed_row,
                    posting=posting_row,
                )
                if profile_payload:
                    with connection:
                        _publish_recipient_profile(
                            connection,
                            paths,
                            posting_row=posting_row,
                            contact_row=refreshed_row,
                            profile_payload=profile_payload,
                            produced_at=timestamp,
                        )
                    recipient_profile_contact_ids.append(str(refreshed_row["contact_id"]))

        with connection:
            posting_status = _promote_posting_ready_for_outreach_if_eligible(
                connection,
                job_posting_id=job_posting_id,
                lead_id=str(posting_row["lead_id"]),
                current_time=timestamp,
            )

        return ContactEnrichmentRunResult(
            job_posting_id=str(posting_row["job_posting_id"]),
            lead_id=str(posting_row["lead_id"]),
            processed_contact_ids=tuple(processed_contact_ids),
            enriched_contact_ids=tuple(enriched_contact_ids),
            recipient_profile_contact_ids=tuple(recipient_profile_contact_ids),
            removed_contact_ids=tuple(removed_contact_ids),
            removed_job_posting_contact_ids=tuple(removed_job_posting_contact_ids),
            posting_status=posting_status,
        )
    finally:
        connection.close()


def run_email_discovery_for_contact(
    *,
    project_root: Path | str,
    job_posting_id: str,
    contact_id: str,
    providers: Sequence[EmailFinderProvider] | None = None,
    current_time: str | None = None,
) -> EmailDiscoveryRunResult:
    paths = ProjectPaths.from_root(project_root)
    connection = sqlite3.connect(paths.db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")

    try:
        target_row = _load_discovery_ready_contact_row(
            connection,
            job_posting_id=job_posting_id,
            contact_id=contact_id,
        )
        timestamp = current_time or now_utc_iso()
        discovery_attempt_id = new_canonical_id("discovery_attempts")
        feedback_reuse_state = _load_contact_feedback_reuse_state(
            connection,
            contact_id=contact_id,
        )

        reusable_email = _normalize_optional_text(target_row.get("current_working_email"))
        provider_steps: list[dict[str, Any]] = []
        attempted_provider_names: list[str] = []
        reused_existing_email = False

        feedback_reuse_result = _select_feedback_reusable_email(
            target_row=target_row,
            feedback_reuse_state=feedback_reuse_state,
        )
        latest_found_attempt = (
            _load_latest_found_attempt_for_email(
                connection,
                contact_id=contact_id,
                email=reusable_email,
            )
            if (
                feedback_reuse_result is None
                and _is_usable_email(reusable_email)
                and _normalize_email(reusable_email) not in feedback_reuse_state["blocked_emails"]
            )
            else None
        )
        if feedback_reuse_result is not None:
            reused_existing_email = True
            final_result = feedback_reuse_result
        elif latest_found_attempt is not None and reusable_email is not None:
            reused_existing_email = True
            final_result = EmailDiscoveryProviderResult(
                provider_name=_normalize_optional_text(latest_found_attempt["provider_name"]) or "",
                outcome=DISCOVERY_OUTCOME_FOUND,
                email=reusable_email,
                provider_verification_status=_normalize_optional_text(
                    latest_found_attempt["provider_verification_status"]
                ),
                provider_score=_normalize_optional_text(latest_found_attempt["provider_score"]),
                detected_pattern=_normalize_optional_text(latest_found_attempt["detected_pattern"]),
            )
        else:
            company_domain = _derive_company_domain(target_row)
            provider_sequence = tuple(providers) if providers is not None else _build_default_email_finder_providers(paths)
            final_result: EmailDiscoveryProviderResult | None = None

            for provider in provider_sequence:
                provider_name = _normalize_optional_text(getattr(provider, "provider_name", None))
                if provider_name is None:
                    raise EmailDiscoveryError("Email-finder providers must expose a non-empty `provider_name`.")
                attempted_provider_names.append(provider_name)

                if provider_name in feedback_reuse_state["blocked_providers"]:
                    skipped_result = EmailDiscoveryProviderResult(
                        provider_name=provider_name,
                        outcome=DISCOVERY_OUTCOME_SKIPPED_BOUNCED_PROVIDER,
                    )
                    provider_steps.append(_provider_step_payload(skipped_result))
                    with connection:
                        _persist_provider_budget_signal(
                            connection,
                            result=skipped_result,
                            discovery_attempt_id=discovery_attempt_id,
                            contact_id=contact_id,
                            created_at=timestamp,
                        )
                    continue

                if bool(getattr(provider, "requires_domain", False)) and company_domain is None:
                    unresolved_result = EmailDiscoveryProviderResult(
                        provider_name=provider_name,
                        outcome=DISCOVERY_OUTCOME_DOMAIN_UNRESOLVED,
                    )
                    provider_steps.append(_provider_step_payload(unresolved_result))
                    with connection:
                        _persist_provider_budget_signal(
                            connection,
                            result=unresolved_result,
                            discovery_attempt_id=discovery_attempt_id,
                            contact_id=contact_id,
                            created_at=timestamp,
                        )
                    continue

                raw_result = provider.discover_email(
                    contact=target_row,
                    posting=target_row,
                    company_domain=company_domain,
                    company_name=_normalize_optional_text(target_row.get("company_name")),
                )
                normalized_result = _normalize_email_finder_provider_result(
                    raw_result,
                    provider_name=provider_name,
                )
                if (
                    _is_usable_email(normalized_result.email)
                    and _normalize_email(normalized_result.email) in feedback_reuse_state["blocked_emails"]
                ):
                    normalized_result = replace(
                        normalized_result,
                        email=normalized_result.email,
                        outcome=DISCOVERY_OUTCOME_BOUNCED_MATCH,
                    )
                provider_steps.append(_provider_step_payload(normalized_result))
                with connection:
                    _persist_provider_budget_signal(
                        connection,
                        result=normalized_result,
                        discovery_attempt_id=discovery_attempt_id,
                        contact_id=contact_id,
                        created_at=timestamp,
                    )
                if normalized_result.is_found:
                    final_result = normalized_result
                    break

            if final_result is None:
                final_result = EmailDiscoveryProviderResult(
                    provider_name="",
                    outcome=_select_final_discovery_outcome(provider_steps),
                )

        with connection:
            _persist_discovery_attempt(
                connection,
                discovery_attempt_id=discovery_attempt_id,
                target_row=target_row,
                result=final_result,
                created_at=timestamp,
            )
            if final_result.is_found:
                _apply_discovery_success(
                    connection,
                    target_row=target_row,
                    result=final_result,
                    current_time=timestamp,
                )
            else:
                _apply_discovery_failure(
                    connection,
                    target_row=target_row,
                    result=final_result,
                    current_time=timestamp,
                )

            posting_status = _promote_posting_ready_for_outreach_if_eligible(
                connection,
                job_posting_id=job_posting_id,
                lead_id=str(target_row["lead_id"]),
                current_time=timestamp,
            )
            refreshed_row = _load_discovery_ready_contact_row(
                connection,
                job_posting_id=job_posting_id,
                contact_id=contact_id,
            )
            artifact_path = _publish_discovery_result_artifact(
                connection,
                paths,
                target_row=refreshed_row,
                discovery_attempt_id=discovery_attempt_id,
                result=final_result,
                provider_steps=provider_steps,
                feedback_reuse_state=feedback_reuse_state,
                attempted_provider_names=attempted_provider_names,
                produced_at=timestamp,
            )

        return EmailDiscoveryRunResult(
            job_posting_id=str(refreshed_row["job_posting_id"]),
            lead_id=str(refreshed_row["lead_id"]),
            contact_id=str(refreshed_row["contact_id"]),
            job_posting_contact_id=str(refreshed_row["job_posting_contact_id"]),
            discovery_attempt_id=discovery_attempt_id,
            artifact_path=artifact_path,
            outcome=final_result.outcome,
            provider_name=final_result.provider_name or None,
            email=final_result.email,
            attempted_provider_names=tuple(attempted_provider_names),
            posting_status=posting_status,
            contact_status=str(refreshed_row["contact_status"]),
            link_level_status=str(refreshed_row["link_level_status"]),
            reused_existing_email=reused_existing_email,
        )
    finally:
        connection.close()


def run_general_learning_email_discovery(
    *,
    project_root: Path | str,
    contact_id: str,
    providers: Sequence[EmailFinderProvider] | None = None,
    current_time: str | None = None,
) -> GeneralLearningEmailDiscoveryRunResult:
    paths = ProjectPaths.from_root(project_root)
    connection = sqlite3.connect(paths.db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")

    try:
        target_row = _load_general_learning_discovery_contact_row(
            connection,
            contact_id=contact_id,
        )
        timestamp = current_time or now_utc_iso()
        discovery_attempt_id = new_canonical_id("discovery_attempts")
        feedback_reuse_state = _load_contact_feedback_reuse_state(
            connection,
            contact_id=contact_id,
        )

        reusable_email = _normalize_optional_text(target_row.get("current_working_email"))
        provider_steps: list[dict[str, Any]] = []
        attempted_provider_names: list[str] = []
        reused_existing_email = False

        feedback_reuse_result = _select_feedback_reusable_email(
            target_row=target_row,
            feedback_reuse_state=feedback_reuse_state,
        )
        latest_found_attempt = (
            _load_latest_found_attempt_for_email(
                connection,
                contact_id=contact_id,
                email=reusable_email,
            )
            if (
                feedback_reuse_result is None
                and _is_usable_email(reusable_email)
                and _normalize_email(reusable_email) not in feedback_reuse_state["blocked_emails"]
            )
            else None
        )
        if feedback_reuse_result is not None:
            reused_existing_email = True
            final_result = feedback_reuse_result
        elif latest_found_attempt is not None and reusable_email is not None:
            reused_existing_email = True
            final_result = EmailDiscoveryProviderResult(
                provider_name=_normalize_optional_text(latest_found_attempt["provider_name"]) or "",
                outcome=DISCOVERY_OUTCOME_FOUND,
                email=reusable_email,
                provider_verification_status=_normalize_optional_text(
                    latest_found_attempt["provider_verification_status"]
                ),
                provider_score=_normalize_optional_text(latest_found_attempt["provider_score"]),
                detected_pattern=_normalize_optional_text(latest_found_attempt["detected_pattern"]),
            )
        else:
            provider_sequence = (
                tuple(providers)
                if providers is not None
                else _build_default_email_finder_providers(paths)
            )
            final_result: EmailDiscoveryProviderResult | None = None

            for provider in provider_sequence:
                provider_name = _normalize_optional_text(
                    getattr(provider, "provider_name", None)
                )
                if provider_name is None:
                    raise EmailDiscoveryError(
                        "Email-finder providers must expose a non-empty `provider_name`."
                    )
                attempted_provider_names.append(provider_name)

                if provider_name in feedback_reuse_state["blocked_providers"]:
                    skipped_result = EmailDiscoveryProviderResult(
                        provider_name=provider_name,
                        outcome=DISCOVERY_OUTCOME_SKIPPED_BOUNCED_PROVIDER,
                    )
                    provider_steps.append(_provider_step_payload(skipped_result))
                    with connection:
                        _persist_provider_budget_signal(
                            connection,
                            result=skipped_result,
                            discovery_attempt_id=discovery_attempt_id,
                            contact_id=contact_id,
                            created_at=timestamp,
                        )
                    continue

                raw_result = provider.discover_email(
                    contact=target_row,
                    posting=target_row,
                    company_domain=None,
                    company_name=_normalize_optional_text(target_row.get("company_name")),
                )
                normalized_result = _normalize_email_finder_provider_result(
                    raw_result,
                    provider_name=provider_name,
                )
                if (
                    _is_usable_email(normalized_result.email)
                    and _normalize_email(normalized_result.email)
                    in feedback_reuse_state["blocked_emails"]
                ):
                    normalized_result = replace(
                        normalized_result,
                        email=normalized_result.email,
                        outcome=DISCOVERY_OUTCOME_BOUNCED_MATCH,
                    )
                provider_steps.append(_provider_step_payload(normalized_result))
                with connection:
                    _persist_provider_budget_signal(
                        connection,
                        result=normalized_result,
                        discovery_attempt_id=discovery_attempt_id,
                        contact_id=contact_id,
                        created_at=timestamp,
                    )
                if normalized_result.is_found:
                    final_result = normalized_result
                    break

            if final_result is None:
                final_result = EmailDiscoveryProviderResult(
                    provider_name="",
                    outcome=_select_final_discovery_outcome(provider_steps),
                )

        with connection:
            _persist_discovery_attempt(
                connection,
                discovery_attempt_id=discovery_attempt_id,
                target_row=target_row,
                result=final_result,
                created_at=timestamp,
            )
            if final_result.is_found:
                _apply_general_learning_discovery_success(
                    connection,
                    target_row=target_row,
                    result=final_result,
                    current_time=timestamp,
                )
            else:
                _apply_general_learning_discovery_failure(
                    connection,
                    target_row=target_row,
                    result=final_result,
                    current_time=timestamp,
                )

            refreshed_row = _load_general_learning_discovery_contact_row(
                connection,
                contact_id=contact_id,
                allow_terminal_status=True,
            )
            artifact_path = _publish_general_learning_discovery_result_artifact(
                connection,
                paths,
                target_row=refreshed_row,
                discovery_attempt_id=discovery_attempt_id,
                result=final_result,
                provider_steps=provider_steps,
                feedback_reuse_state=feedback_reuse_state,
                attempted_provider_names=attempted_provider_names,
                produced_at=timestamp,
            )

        return GeneralLearningEmailDiscoveryRunResult(
            contact_id=str(refreshed_row["contact_id"]),
            discovery_attempt_id=discovery_attempt_id,
            artifact_path=artifact_path,
            outcome=final_result.outcome,
            provider_name=final_result.provider_name or None,
            email=final_result.email,
            attempted_provider_names=tuple(attempted_provider_names),
            contact_status=str(refreshed_row["contact_status"]),
            reused_existing_email=reused_existing_email,
        )
    finally:
        connection.close()


def load_provider_budget_summary(
    *,
    project_root: Path | str,
) -> dict[str, Any]:
    paths = ProjectPaths.from_root(project_root)
    connection = sqlite3.connect(paths.db_path)
    connection.row_factory = sqlite3.Row

    try:
        rows = connection.execute(
            """
            SELECT provider_name, remaining_credits, credit_limit, reset_at, updated_at
            FROM provider_budget_state
            ORDER BY provider_name ASC
            """
        ).fetchall()
        providers = [
            {
                "provider_name": str(row["provider_name"]),
                "remaining_credits": row["remaining_credits"],
                "credit_limit": row["credit_limit"],
                "reset_at": row["reset_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]
        combined_known_remaining_credits = sum(
            int(row["remaining_credits"])
            for row in rows
            if row["remaining_credits"] is not None
        )
        return {
            "providers": providers,
            "combined_known_remaining_credits": combined_known_remaining_credits,
        }
    finally:
        connection.close()


def select_initial_enrichment_shortlist(
    candidates: Sequence[PeopleSearchCandidate],
    *,
    limit: int = DEFAULT_SHORTLIST_LIMIT,
) -> tuple[PeopleSearchCandidate, ...]:
    if limit <= 0:
        raise EmailDiscoveryError("Shortlist limit must be greater than zero.")

    selected_indices: list[int] = []
    selected_lookup: set[int] = set()

    for _, recipient_types, bucket_limit in SHORTLIST_BUCKETS:
        bucket_count = 0
        for index, candidate in enumerate(candidates):
            if index in selected_lookup or candidate.recipient_type not in recipient_types:
                continue
            selected_indices.append(index)
            selected_lookup.add(index)
            bucket_count += 1
            if bucket_count >= bucket_limit or len(selected_indices) >= limit:
                break
        if len(selected_indices) >= limit:
            break

    if len(selected_indices) < limit:
        for index, candidate in enumerate(candidates):
            if index in selected_lookup:
                continue
            selected_indices.append(index)
            selected_lookup.add(index)
            if len(selected_indices) >= limit:
                break

    return tuple(candidates[index] for index in selected_indices)


def _normalize_candidate_rows(
    candidates: Sequence[PeopleSearchCandidate | Mapping[str, Any]],
) -> list[PeopleSearchCandidate]:
    normalized: list[PeopleSearchCandidate] = []
    for candidate in candidates:
        if isinstance(candidate, PeopleSearchCandidate):
            normalized.append(candidate)
        elif isinstance(candidate, Mapping):
            normalized.append(PeopleSearchCandidate.from_mapping(candidate))
        else:
            raise EmailDiscoveryError("Apollo candidate rows must be mappings or PeopleSearchCandidate values.")
    return normalized


def _load_search_ready_posting(
    connection: sqlite3.Connection,
    *,
    job_posting_id: str,
) -> sqlite3.Row:
    posting_row = connection.execute(
        """
        SELECT jp.job_posting_id, jp.lead_id, jp.company_name, jp.role_title, jp.posting_status,
               jp.location, jp.jd_artifact_path, ll.source_url
        FROM job_postings jp
        JOIN linkedin_leads ll
          ON ll.lead_id = jp.lead_id
        WHERE jp.job_posting_id = ?
        """,
        (job_posting_id,),
    ).fetchone()
    if posting_row is None:
        raise EmailDiscoveryError(f"Job posting `{job_posting_id}` was not found.")

    if posting_row["posting_status"] != JOB_POSTING_STATUS_REQUIRES_CONTACTS:
        raise EmailDiscoveryError(
            f"Job posting `{job_posting_id}` is `{posting_row['posting_status']}`; people search starts only from `requires_contacts`."
        )

    latest_run = connection.execute(
        """
        SELECT resume_tailoring_run_id, resume_review_status
        FROM resume_tailoring_runs
        WHERE job_posting_id = ?
        ORDER BY created_at DESC, resume_tailoring_run_id DESC
        LIMIT 1
        """,
        (job_posting_id,),
    ).fetchone()
    if latest_run is None or latest_run["resume_review_status"] != RESUME_REVIEW_STATUS_APPROVED:
        raise EmailDiscoveryError(
            f"Job posting `{job_posting_id}` is not backed by an approved tailoring review."
        )
    return posting_row


def _load_posting_jd(paths: ProjectPaths, posting_row: sqlite3.Row) -> str:
    jd_artifact_path = posting_row["jd_artifact_path"]
    if not jd_artifact_path:
        return ""
    jd_path = paths.resolve_from_root(jd_artifact_path)
    if not jd_path.exists():
        return ""
    return jd_path.read_text(encoding="utf-8")


def _build_apollo_search_filters(
    posting_row: sqlite3.Row,
    *,
    jd_text: str,
    shortlist_limit: int,
) -> dict[str, Any]:
    role_title = str(posting_row["role_title"]).strip()
    location = _normalize_optional_text(posting_row["location"])
    title_tokens = _role_title_tokens(role_title)
    title_hints = [
        role_title,
        _normalize_engineer_title(role_title),
        "Recruiter",
        "Technical Recruiter",
        "Talent Acquisition Partner",
        "Engineering Manager",
        "Director of Engineering",
        "Head of Engineering",
        "Software Engineer",
    ]
    if title_tokens:
        title_hints.extend(
            [
                " ".join([token.capitalize() for token in title_tokens]),
                " ".join([token.capitalize() for token in title_tokens] + ["Engineer"]),
            ]
        )

    if "machine learning" in jd_text.lower() or "artificial intelligence" in jd_text.lower() or " ai " in f" {jd_text.lower()} ":
        title_hints.extend(["Machine Learning Engineer", "AI Engineer"])

    return {
        "titles": _dedupe_preserve_order(title_hints),
        "functions": ["engineering", "recruiting"],
        "seniority_levels": _derive_seniority_levels(role_title, jd_text=jd_text),
        "locations": [location] if location else [],
        "target_classes": [
            RECIPIENT_TYPE_RECRUITER,
            RECIPIENT_TYPE_HIRING_MANAGER,
            RECIPIENT_TYPE_ENGINEER,
            RECIPIENT_TYPE_OTHER_INTERNAL,
        ],
        "shortlist_policy": {
            "limit": shortlist_limit,
            "buckets": [
                {
                    "bucket": bucket_name,
                    "recipient_types": sorted(recipient_types),
                    "cap": bucket_limit,
                }
                for bucket_name, recipient_types, bucket_limit in SHORTLIST_BUCKETS
            ],
        },
    }


def _derive_seniority_levels(role_title: str, *, jd_text: str) -> list[str]:
    normalized = f"{role_title} {jd_text}".lower()
    seniority_levels = ["manager", "director", "senior", "individual_contributor"]
    if "staff" in normalized or "principal" in normalized:
        seniority_levels.insert(0, "staff")
    return _dedupe_preserve_order(seniority_levels)


def _role_title_tokens(role_title: str) -> list[str]:
    tokens = [
        token.lower()
        for token in WORD_RE.findall(role_title)
        if token.lower() not in STOPWORD_TOKENS
    ]
    return tokens[:4]


def _normalize_engineer_title(role_title: str) -> str:
    normalized = " ".join(role_title.split())
    if "engineer" in normalized.lower():
        return normalized
    return f"{normalized} Engineer"


def _derive_company_domain(posting_row: sqlite3.Row) -> str | None:
    source_url = _normalize_optional_text(posting_row["source_url"])
    if not source_url:
        return None
    lowered = source_url.lower()
    if lowered.startswith("http://") or lowered.startswith("https://"):
        host = source_url.split("://", 1)[1].split("/", 1)[0].strip().lower()
        if host and "." in host and "linkedin.com" not in host:
            return host
    return None


def _derive_company_website(posting_row: sqlite3.Row) -> str | None:
    source_url = _normalize_optional_text(posting_row["source_url"])
    if source_url and "linkedin.com" not in source_url.lower():
        return source_url
    return None


def _load_people_search_payload(
    paths: ProjectPaths,
    posting_row: Mapping[str, Any],
) -> Mapping[str, Any]:
    artifact_path = (
        paths.discovery_workspace_dir(str(posting_row["company_name"]), str(posting_row["role_title"]))
        / "people_search_result.json"
    )
    if not artifact_path.exists():
        return {}
    try:
        payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, Mapping) else {}


def _load_shortlisted_contact_rows(
    connection: sqlite3.Connection,
    *,
    job_posting_id: str,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT jpc.job_posting_contact_id, jpc.job_posting_id, jpc.contact_id, jpc.recipient_type,
               jpc.relevance_reason, jpc.link_level_status, c.identity_key, c.display_name,
               c.company_name, c.origin_component, c.contact_status, c.full_name, c.first_name,
               c.last_name, c.linkedin_url, c.position_title, c.location, c.discovery_summary,
               c.current_working_email, c.identity_source, c.provider_name, c.provider_person_id,
               c.name_quality, c.created_at, c.updated_at
        FROM job_posting_contacts jpc
        JOIN contacts c
          ON c.contact_id = jpc.contact_id
        WHERE jpc.job_posting_id = ?
          AND jpc.link_level_status = ?
        ORDER BY jpc.created_at ASC, jpc.job_posting_contact_id ASC
        """,
        (
            job_posting_id,
            POSTING_CONTACT_STATUS_SHORTLISTED,
        ),
    ).fetchall()
    return [dict(row) for row in rows]


def _load_shortlisted_contact_row(
    connection: sqlite3.Connection,
    *,
    job_posting_contact_id: str,
) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT jpc.job_posting_contact_id, jpc.job_posting_id, jpc.contact_id, jpc.recipient_type,
               jpc.relevance_reason, jpc.link_level_status, c.identity_key, c.display_name,
               c.company_name, c.origin_component, c.contact_status, c.full_name, c.first_name,
               c.last_name, c.linkedin_url, c.position_title, c.location, c.discovery_summary,
               c.current_working_email, c.identity_source, c.provider_name, c.provider_person_id,
               c.name_quality, c.created_at, c.updated_at
        FROM job_posting_contacts jpc
        JOIN contacts c
          ON c.contact_id = jpc.contact_id
        WHERE jpc.job_posting_contact_id = ?
        """,
        (job_posting_contact_id,),
    ).fetchone()
    return dict(row) if row is not None else None


def _build_default_email_finder_providers(paths: ProjectPaths) -> tuple[EmailFinderProvider, ...]:
    return (
        ConfiguredProspeoClient.from_paths(paths),
        ConfiguredGetProspectClient.from_paths(paths),
        ConfiguredHunterClient.from_paths(paths),
    )


def _normalize_email_finder_provider_result(
    payload: EmailDiscoveryProviderResult | Mapping[str, Any],
    *,
    provider_name: str,
) -> EmailDiscoveryProviderResult:
    if isinstance(payload, EmailDiscoveryProviderResult):
        return payload if payload.provider_name else replace(payload, provider_name=provider_name)
    if isinstance(payload, Mapping):
        return EmailDiscoveryProviderResult.from_mapping(payload, provider_name=provider_name)
    raise EmailDiscoveryError("Email-finder providers must return mappings or EmailDiscoveryProviderResult values.")


def _provider_step_payload(result: EmailDiscoveryProviderResult) -> dict[str, Any]:
    return {
        "provider_name": result.provider_name,
        "outcome": result.outcome,
        "email": result.email,
        "provider_verification_status": result.provider_verification_status,
        "provider_score": result.provider_score,
        "detected_pattern": result.detected_pattern,
        "remaining_credits": result.remaining_credits,
        "credit_limit": result.credit_limit,
        "reset_at": result.reset_at,
        "message": result.message,
    }


def _select_final_discovery_outcome(provider_steps: Sequence[Mapping[str, Any]]) -> str:
    outcomes = {
        _normalize_optional_text(step.get("outcome"))
        for step in provider_steps
        if _normalize_optional_text(step.get("outcome"))
    }
    if DISCOVERY_OUTCOME_DOMAIN_UNRESOLVED in outcomes:
        return DISCOVERY_OUTCOME_DOMAIN_UNRESOLVED
    if DISCOVERY_OUTCOME_QUOTA_EXHAUSTED in outcomes:
        return DISCOVERY_OUTCOME_QUOTA_EXHAUSTED
    if DISCOVERY_OUTCOME_RATE_LIMITED in outcomes:
        return DISCOVERY_OUTCOME_RATE_LIMITED
    if DISCOVERY_OUTCOME_INVALID_API_KEY in outcomes:
        return DISCOVERY_OUTCOME_INVALID_API_KEY
    if DISCOVERY_OUTCOME_NETWORK_ERROR in outcomes:
        return DISCOVERY_OUTCOME_NETWORK_ERROR
    if DISCOVERY_OUTCOME_PROVIDER_ERROR in outcomes:
        return DISCOVERY_OUTCOME_PROVIDER_ERROR
    return DISCOVERY_OUTCOME_NOT_FOUND


def _load_discovery_ready_contact_row(
    connection: sqlite3.Connection,
    *,
    job_posting_id: str,
    contact_id: str,
) -> dict[str, Any]:
    row = connection.execute(
        """
        SELECT jp.job_posting_id, jp.lead_id, jp.company_name, jp.role_title, jp.posting_status,
               jp.location AS posting_location, jp.jd_artifact_path, ll.source_url,
               jpc.job_posting_contact_id, jpc.recipient_type, jpc.relevance_reason, jpc.link_level_status,
               c.contact_id, c.identity_key, c.display_name, c.company_name AS contact_company_name,
               c.origin_component, c.contact_status, c.full_name, c.first_name, c.last_name,
               c.linkedin_url, c.position_title, c.location, c.discovery_summary,
               c.current_working_email, c.identity_source, c.provider_name, c.provider_person_id,
               c.name_quality, c.created_at, c.updated_at
        FROM job_postings jp
        JOIN linkedin_leads ll
          ON ll.lead_id = jp.lead_id
        JOIN job_posting_contacts jpc
          ON jpc.job_posting_id = jp.job_posting_id
        JOIN contacts c
          ON c.contact_id = jpc.contact_id
        WHERE jp.job_posting_id = ?
          AND c.contact_id = ?
        ORDER BY jpc.created_at ASC, jpc.job_posting_contact_id ASC
        LIMIT 1
        """,
        (job_posting_id, contact_id),
    ).fetchone()
    if row is None:
        raise EmailDiscoveryError(
            f"Contact `{contact_id}` is not linked to job posting `{job_posting_id}`."
        )

    posting_status = str(row["posting_status"]).strip()
    if posting_status not in {JOB_POSTING_STATUS_REQUIRES_CONTACTS, JOB_POSTING_STATUS_READY_FOR_OUTREACH}:
        raise EmailDiscoveryError(
            f"Job posting `{job_posting_id}` is `{posting_status}`; person-scoped email discovery starts only from `requires_contacts` or `ready_for_outreach`."
        )

    link_level_status = str(row["link_level_status"]).strip()
    if link_level_status not in {
        POSTING_CONTACT_STATUS_IDENTIFIED,
        POSTING_CONTACT_STATUS_SHORTLISTED,
        POSTING_CONTACT_STATUS_EXHAUSTED,
    }:
        raise EmailDiscoveryError(
            f"Posting-contact link `{row['job_posting_contact_id']}` is `{link_level_status}`; discovery only runs for selected or reviewable linked contacts."
        )

    latest_run = connection.execute(
        """
        SELECT resume_review_status
        FROM resume_tailoring_runs
        WHERE job_posting_id = ?
        ORDER BY created_at DESC, resume_tailoring_run_id DESC
        LIMIT 1
        """,
        (job_posting_id,),
    ).fetchone()
    if latest_run is None or latest_run["resume_review_status"] != RESUME_REVIEW_STATUS_APPROVED:
        raise EmailDiscoveryError(
            f"Job posting `{job_posting_id}` is not backed by an approved tailoring review."
        )
    return dict(row)


def _load_general_learning_discovery_contact_row(
    connection: sqlite3.Connection,
    *,
    contact_id: str,
    allow_terminal_status: bool = False,
) -> dict[str, Any]:
    row = connection.execute(
        """
        SELECT c.contact_id, c.identity_key, c.display_name, c.company_name, c.origin_component,
               c.contact_status, c.full_name, c.first_name, c.last_name, c.linkedin_url,
               c.position_title, c.location, c.discovery_summary, c.current_working_email,
               c.identity_source, c.provider_name, c.provider_person_id, c.name_quality,
               c.created_at, c.updated_at,
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
        (contact_id,),
    ).fetchone()
    if row is None:
        raise EmailDiscoveryError(f"Contact `{contact_id}` was not found.")

    posting_link_count = int(row["posting_link_count"] or 0)
    if posting_link_count > 0:
        raise EmailDiscoveryError(
            f"Contact `{contact_id}` is still tied to posting-linked outreach state."
        )

    sent_message_count = int(row["sent_message_count"] or 0)
    if sent_message_count > 0:
        raise EmailDiscoveryError(
            f"Contact `{contact_id}` already has prior sent outreach history."
        )

    latest_status = _normalize_optional_text(row["latest_general_learning_message_status"])
    if latest_status is not None:
        raise EmailDiscoveryError(
            f"Contact `{contact_id}` already has general-learning outreach state at "
            f"{latest_status!r}."
        )

    contact_status = _normalize_optional_text(row["contact_status"]) or CONTACT_STATUS_IDENTIFIED
    if (
        not allow_terminal_status
        and contact_status in {CONTACT_STATUS_EXHAUSTED, "outreach_in_progress", "sent"}
    ):
        raise EmailDiscoveryError(
            f"Contact `{contact_id}` is already at contact_status={contact_status!r}."
        )
    return dict(row)


def _load_contact_feedback_reuse_state(
    connection: sqlite3.Connection,
    *,
    contact_id: str,
) -> dict[str, Any]:
    candidates = query_feedback_reuse_candidates(connection, contact_id=contact_id)
    blocked_emails = {
        str(candidate["recipient_email"]).strip().lower()
        for candidate in candidates
        if candidate["discovery_reuse_state"] == DISCOVERY_REUSE_STATE_BLOCKED_BOUNCED
    }
    reusable_emails = {
        str(candidate["recipient_email"]).strip().lower()
        for candidate in candidates
        if candidate["discovery_reuse_state"] == DISCOVERY_REUSE_STATE_ELIGIBLE_NOT_BOUNCED
    }
    reply_only_emails = {
        str(candidate["recipient_email"]).strip().lower()
        for candidate in candidates
        if candidate["discovery_reuse_state"] not in {
            DISCOVERY_REUSE_STATE_BLOCKED_BOUNCED,
            DISCOVERY_REUSE_STATE_ELIGIBLE_NOT_BOUNCED,
        }
    }
    blocked_providers: set[str] = set()
    for email in blocked_emails:
        provider_row = connection.execute(
            """
            SELECT provider_name
            FROM discovery_attempts
            WHERE contact_id = ?
              AND email = ?
              AND provider_name IS NOT NULL
              AND TRIM(provider_name) <> ''
            ORDER BY created_at DESC, discovery_attempt_id DESC
            LIMIT 1
            """,
            (contact_id, email),
        ).fetchone()
        if provider_row is not None and provider_row["provider_name"]:
            blocked_providers.add(str(provider_row["provider_name"]))
    return {
        "rows": tuple(candidates),
        "blocked_emails": blocked_emails,
        "reusable_emails": reusable_emails,
        "reply_only_emails": reply_only_emails,
        "blocked_providers": blocked_providers,
    }


def _select_feedback_reusable_email(
    target_row: Mapping[str, Any],
    feedback_reuse_state: Mapping[str, Any],
) -> EmailDiscoveryProviderResult | None:
    current_working_email = _normalize_optional_text(target_row.get("current_working_email"))
    reusable_emails = {
        str(email).strip().lower()
        for email in feedback_reuse_state.get("reusable_emails", set())
        if str(email).strip()
    }
    blocked_emails = {
        str(email).strip().lower()
        for email in feedback_reuse_state.get("blocked_emails", set())
        if str(email).strip()
    }

    selected_email: str | None = None
    if _is_usable_email(current_working_email):
        normalized_current = str(current_working_email).strip().lower()
        if normalized_current in reusable_emails and normalized_current not in blocked_emails:
            selected_email = normalized_current

    if selected_email is None:
        reusable_candidates = [
            candidate
            for candidate in feedback_reuse_state.get("rows", ())
            if candidate.get("discovery_reuse_state") == DISCOVERY_REUSE_STATE_ELIGIBLE_NOT_BOUNCED
            and _normalize_email(candidate.get("recipient_email")) not in blocked_emails
        ]
        if len(reusable_candidates) == 1:
            selected_email = _normalize_optional_text(reusable_candidates[0].get("recipient_email"))

    if not _is_usable_email(selected_email):
        return None

    return EmailDiscoveryProviderResult(
        provider_name=FEEDBACK_REUSE_PROVIDER_NAME,
        outcome=DISCOVERY_OUTCOME_FOUND,
        email=selected_email,
        provider_verification_status="mailbox_not_bounced",
        provider_score="1.0",
    )


def _load_latest_found_attempt_for_email(
    connection: sqlite3.Connection,
    *,
    contact_id: str,
    email: str | None,
) -> sqlite3.Row | None:
    if not _is_usable_email(email):
        return None
    return connection.execute(
        """
        SELECT discovery_attempt_id, provider_name, provider_verification_status, provider_score,
               detected_pattern, created_at
        FROM discovery_attempts
        WHERE contact_id = ?
          AND outcome = ?
          AND email = ?
        ORDER BY created_at DESC, discovery_attempt_id DESC
        LIMIT 1
        """,
        (
            contact_id,
            DISCOVERY_OUTCOME_FOUND,
            str(email).strip().lower(),
        ),
    ).fetchone()


def _persist_provider_budget_signal(
    connection: sqlite3.Connection,
    *,
    result: EmailDiscoveryProviderResult,
    discovery_attempt_id: str,
    contact_id: str,
    created_at: str,
) -> None:
    provider_name = _normalize_optional_text(result.provider_name)
    if provider_name is None:
        return

    current_state = connection.execute(
        """
        SELECT remaining_credits, credit_limit, reset_at
        FROM provider_budget_state
        WHERE provider_name = ?
        """,
        (provider_name,),
    ).fetchone()
    previous_remaining = (
        _normalize_optional_int(current_state["remaining_credits"])
        if current_state is not None
        else None
    )
    next_remaining = result.remaining_credits if result.remaining_credits is not None else previous_remaining
    next_limit = (
        result.credit_limit
        if result.credit_limit is not None
        else (_normalize_optional_int(current_state["credit_limit"]) if current_state is not None else None)
    )
    next_reset = (
        result.reset_at
        if result.reset_at is not None
        else (_normalize_optional_text(current_state["reset_at"]) if current_state is not None else None)
    )

    if current_state is None:
        connection.execute(
            """
            INSERT INTO provider_budget_state (
              provider_name, remaining_credits, credit_limit, reset_at, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                provider_name,
                next_remaining,
                next_limit,
                next_reset,
                created_at,
            ),
        )
    else:
        connection.execute(
            """
            UPDATE provider_budget_state
            SET remaining_credits = ?, credit_limit = ?, reset_at = ?, updated_at = ?
            WHERE provider_name = ?
            """,
            (
                next_remaining,
                next_limit,
                next_reset,
                created_at,
                provider_name,
            ),
        )

    credit_delta = 0
    if previous_remaining is not None and result.remaining_credits is not None:
        credit_delta = result.remaining_credits - previous_remaining
    connection.execute(
        """
        INSERT INTO provider_budget_events (
          provider_budget_event_id, provider_name, event_type, credit_delta,
          remaining_credits_after, related_discovery_attempt_id, related_contact_id, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            new_canonical_id("provider_budget_events"),
            provider_name,
            result.outcome,
            credit_delta,
            next_remaining,
            discovery_attempt_id,
            contact_id,
            created_at,
        ),
    )


def _persist_discovery_attempt(
    connection: sqlite3.Connection,
    *,
    discovery_attempt_id: str,
    target_row: Mapping[str, Any],
    result: EmailDiscoveryProviderResult,
    created_at: str,
) -> None:
    email = _normalize_optional_text(result.email)
    connection.execute(
        """
        INSERT INTO discovery_attempts (
          discovery_attempt_id, contact_id, job_posting_id, window_id, outcome,
          provider_name, email, email_local_part, detected_pattern, provider_verification_status,
          provider_score, bounced, display_name, first_name, last_name, full_name,
          linkedin_url, position_title, location, provider_person_id, name_quality, created_at
        ) VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            discovery_attempt_id,
            target_row["contact_id"],
            target_row.get("job_posting_id"),
            result.outcome,
            _normalize_optional_text(result.provider_name),
            email,
            email.split("@", 1)[0] if _is_usable_email(email) else None,
            result.detected_pattern,
            result.provider_verification_status,
            result.provider_score,
            0,
            _normalize_optional_text(target_row.get("display_name")),
            _normalize_optional_text(target_row.get("first_name")),
            _normalize_optional_text(target_row.get("last_name")),
            _normalize_optional_text(target_row.get("full_name")),
            _normalize_optional_text(target_row.get("linkedin_url")),
            _normalize_optional_text(target_row.get("position_title")),
            _normalize_optional_text(target_row.get("location")),
            _normalize_optional_text(target_row.get("provider_person_id")),
            _normalize_optional_text(target_row.get("name_quality")),
            created_at,
        ),
    )


def _apply_discovery_success(
    connection: sqlite3.Connection,
    *,
    target_row: Mapping[str, Any],
    result: EmailDiscoveryProviderResult,
    current_time: str,
) -> None:
    connection.execute(
        """
        UPDATE contacts
        SET current_working_email = ?, discovery_summary = ?, updated_at = ?
        WHERE contact_id = ?
        """,
        (
            result.email,
            CONTACT_STATUS_WORKING_EMAIL_FOUND,
            current_time,
            target_row["contact_id"],
        ),
    )
    if _normalize_optional_text(target_row.get("link_level_status")) == POSTING_CONTACT_STATUS_EXHAUSTED:
        connection.execute(
            """
            UPDATE job_posting_contacts
            SET link_level_status = ?, updated_at = ?
            WHERE job_posting_contact_id = ?
            """,
            (
                POSTING_CONTACT_STATUS_SHORTLISTED,
                current_time,
                target_row["job_posting_contact_id"],
            ),
        )
        _record_state_transition(
            connection,
            object_type="job_posting_contacts",
            object_id=str(target_row["job_posting_contact_id"]),
            stage="link_level_status",
            previous_state=POSTING_CONTACT_STATUS_EXHAUSTED,
            new_state=POSTING_CONTACT_STATUS_SHORTLISTED,
            transition_timestamp=current_time,
            transition_reason="Email discovery recovered a usable work email for this linked contact.",
            lead_id=str(target_row["lead_id"]),
            job_posting_id=str(target_row["job_posting_id"]),
            contact_id=str(target_row["contact_id"]),
        )
    refreshed_row = _load_discovery_ready_contact_row(
        connection,
        job_posting_id=str(target_row["job_posting_id"]),
        contact_id=str(target_row["contact_id"]),
    )
    _promote_contact_to_working_email_found_if_ready(
        connection,
        posting_row=refreshed_row,
        contact_row=refreshed_row,
        current_time=current_time,
    )


def _apply_discovery_failure(
    connection: sqlite3.Connection,
    *,
    target_row: Mapping[str, Any],
    result: EmailDiscoveryProviderResult,
    current_time: str,
) -> None:
    exhausted = _all_email_finder_providers_exhausted(
        connection,
        contact_id=str(target_row["contact_id"]),
    )
    discovery_summary = "all_providers_exhausted" if exhausted else result.outcome
    connection.execute(
        """
        UPDATE contacts
        SET discovery_summary = ?, updated_at = ?
        WHERE contact_id = ?
        """,
        (
            discovery_summary,
            current_time,
            target_row["contact_id"],
        ),
    )
    if not exhausted:
        return

    previous_contact_status = _normalize_optional_text(target_row.get("contact_status")) or CONTACT_STATUS_IDENTIFIED
    if previous_contact_status != CONTACT_STATUS_EXHAUSTED:
        connection.execute(
            """
            UPDATE contacts
            SET contact_status = ?, current_working_email = NULL, updated_at = ?
            WHERE contact_id = ?
            """,
            (
                CONTACT_STATUS_EXHAUSTED,
                current_time,
                target_row["contact_id"],
            ),
        )
        _record_state_transition(
            connection,
            object_type="contacts",
            object_id=str(target_row["contact_id"]),
            stage="contact_status",
            previous_state=previous_contact_status,
            new_state=CONTACT_STATUS_EXHAUSTED,
            transition_timestamp=current_time,
            transition_reason="Email discovery exhausted the current provider set without a non-bounced usable email.",
            lead_id=str(target_row["lead_id"]),
            job_posting_id=str(target_row["job_posting_id"]),
            contact_id=str(target_row["contact_id"]),
        )
    previous_link_status = _normalize_optional_text(target_row.get("link_level_status")) or POSTING_CONTACT_STATUS_IDENTIFIED
    if previous_link_status != POSTING_CONTACT_STATUS_EXHAUSTED:
        connection.execute(
            """
            UPDATE job_posting_contacts
            SET link_level_status = ?, updated_at = ?
            WHERE job_posting_contact_id = ?
            """,
            (
                POSTING_CONTACT_STATUS_EXHAUSTED,
                current_time,
                target_row["job_posting_contact_id"],
            ),
        )
        _record_state_transition(
            connection,
            object_type="job_posting_contacts",
            object_id=str(target_row["job_posting_contact_id"]),
            stage="link_level_status",
            previous_state=previous_link_status,
            new_state=POSTING_CONTACT_STATUS_EXHAUSTED,
            transition_timestamp=current_time,
            transition_reason="Email discovery exhausted the current provider set for this linked contact.",
            lead_id=str(target_row["lead_id"]),
            job_posting_id=str(target_row["job_posting_id"]),
            contact_id=str(target_row["contact_id"]),
        )


def _apply_general_learning_discovery_success(
    connection: sqlite3.Connection,
    *,
    target_row: Mapping[str, Any],
    result: EmailDiscoveryProviderResult,
    current_time: str,
) -> None:
    previous_contact_status = _normalize_optional_text(target_row.get("contact_status")) or CONTACT_STATUS_IDENTIFIED
    connection.execute(
        """
        UPDATE contacts
        SET current_working_email = ?, discovery_summary = ?, contact_status = ?, updated_at = ?
        WHERE contact_id = ?
        """,
        (
            result.email,
            CONTACT_STATUS_WORKING_EMAIL_FOUND,
            CONTACT_STATUS_WORKING_EMAIL_FOUND,
            current_time,
            target_row["contact_id"],
        ),
    )
    if previous_contact_status != CONTACT_STATUS_WORKING_EMAIL_FOUND:
        _record_state_transition(
            connection,
            object_type="contacts",
            object_id=str(target_row["contact_id"]),
            stage="contact_status",
            previous_state=previous_contact_status,
            new_state=CONTACT_STATUS_WORKING_EMAIL_FOUND,
            transition_timestamp=current_time,
            transition_reason="Contact-rooted general-learning email discovery produced a usable work email.",
            lead_id=None,
            job_posting_id=None,
            contact_id=str(target_row["contact_id"]),
        )


def _apply_general_learning_discovery_failure(
    connection: sqlite3.Connection,
    *,
    target_row: Mapping[str, Any],
    result: EmailDiscoveryProviderResult,
    current_time: str,
) -> None:
    exhausted = _all_email_finder_providers_exhausted(
        connection,
        contact_id=str(target_row["contact_id"]),
    )
    discovery_summary = "all_providers_exhausted" if exhausted else result.outcome
    connection.execute(
        """
        UPDATE contacts
        SET discovery_summary = ?, updated_at = ?
        WHERE contact_id = ?
        """,
        (
            discovery_summary,
            current_time,
            target_row["contact_id"],
        ),
    )
    if not exhausted:
        return

    previous_contact_status = _normalize_optional_text(target_row.get("contact_status")) or CONTACT_STATUS_IDENTIFIED
    if previous_contact_status == CONTACT_STATUS_EXHAUSTED:
        return
    connection.execute(
        """
        UPDATE contacts
        SET contact_status = ?, current_working_email = NULL, updated_at = ?
        WHERE contact_id = ?
        """,
        (
            CONTACT_STATUS_EXHAUSTED,
            current_time,
            target_row["contact_id"],
        ),
    )
    _record_state_transition(
        connection,
        object_type="contacts",
        object_id=str(target_row["contact_id"]),
        stage="contact_status",
        previous_state=previous_contact_status,
        new_state=CONTACT_STATUS_EXHAUSTED,
        transition_timestamp=current_time,
        transition_reason="Contact-rooted general-learning email discovery exhausted the current provider set without a non-bounced usable email.",
        lead_id=None,
        job_posting_id=None,
        contact_id=str(target_row["contact_id"]),
    )


def _all_email_finder_providers_exhausted(
    connection: sqlite3.Connection,
    *,
    contact_id: str,
) -> bool:
    rows = connection.execute(
        """
        SELECT DISTINCT provider_name
        FROM provider_budget_events
        WHERE related_contact_id = ?
          AND event_type IN (?, ?, ?, ?, ?, ?)
        """,
        (
            contact_id,
            DISCOVERY_OUTCOME_NOT_FOUND,
            DISCOVERY_OUTCOME_RATE_LIMITED,
            DISCOVERY_OUTCOME_QUOTA_EXHAUSTED,
            DISCOVERY_OUTCOME_INVALID_API_KEY,
            DISCOVERY_OUTCOME_BOUNCED_MATCH,
            DISCOVERY_OUTCOME_SKIPPED_BOUNCED_PROVIDER,
        ),
    ).fetchall()
    exhausted_provider_names = {
        str(row["provider_name"]).strip()
        for row in rows
        if str(row["provider_name"]).strip()
    }
    return all(provider_name in exhausted_provider_names for provider_name in EMAIL_FINDER_PROVIDER_ORDER)


def _publish_discovery_result_artifact(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    target_row: Mapping[str, Any],
    discovery_attempt_id: str,
    result: EmailDiscoveryProviderResult,
    provider_steps: Sequence[Mapping[str, Any]],
    feedback_reuse_state: Mapping[str, Any],
    attempted_provider_names: Sequence[str],
    produced_at: str,
) -> Path:
    artifact_path = (
        paths.discovery_workspace_dir(str(target_row["company_name"]), str(target_row["role_title"]))
        / "discovery_result.json"
    )
    connection.execute(
        """
        DELETE FROM artifact_records
        WHERE artifact_type = ? AND job_posting_id = ?
        """,
        (
            DISCOVERY_RESULT_ARTIFACT_TYPE,
            target_row["job_posting_id"],
        ),
    )
    recipient_profile = _lookup_recipient_profile_artifact(
        connection,
        paths,
        job_posting_id=str(target_row["job_posting_id"]),
        contact_id=str(target_row["contact_id"]),
    )
    publish_json_artifact(
        connection,
        paths,
        artifact_type=DISCOVERY_RESULT_ARTIFACT_TYPE,
        artifact_path=artifact_path,
        producer_component=EMAIL_DISCOVERY_COMPONENT,
        result="success" if result.is_found else "blocked",
        linkage=ArtifactLinkage(
            job_posting_id=str(target_row["job_posting_id"]),
            contact_id=str(target_row["contact_id"]),
        ),
        payload={
            "discovery_attempt_id": discovery_attempt_id,
            "outcome": result.outcome,
            "email": result.email,
            "provider_name": _normalize_optional_text(result.provider_name),
            "provider_verification_status": result.provider_verification_status,
            "provider_score": result.provider_score,
            "detected_pattern": result.detected_pattern,
            "observed_bounced": bool(feedback_reuse_state.get("blocked_emails")),
            "observed_not_bounced": bool(feedback_reuse_state.get("reusable_emails")),
            "reply_retained_for_review_only": bool(feedback_reuse_state.get("reply_only_emails")),
            "feedback_reuse_summary": {
                "blocked_bounced_emails": sorted(
                    str(email) for email in feedback_reuse_state.get("blocked_emails", set())
                ),
                "reusable_not_bounced_emails": sorted(
                    str(email) for email in feedback_reuse_state.get("reusable_emails", set())
                ),
                "reply_only_emails": sorted(
                    str(email) for email in feedback_reuse_state.get("reply_only_emails", set())
                ),
            },
            "attempted_provider_names": list(attempted_provider_names),
            "provider_steps": [dict(step) for step in provider_steps],
            "recipient_profile_artifact_ref": recipient_profile["relative_path"],
            "recipient_profile_artifact_path": recipient_profile["absolute_path"],
        },
        produced_at=produced_at,
        reason_code=None if result.is_found else result.outcome,
        message=None if result.is_found else _discovery_blocked_message(result.outcome),
    )
    return artifact_path


def _publish_general_learning_discovery_result_artifact(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    target_row: Mapping[str, Any],
    discovery_attempt_id: str,
    result: EmailDiscoveryProviderResult,
    provider_steps: Sequence[Mapping[str, Any]],
    feedback_reuse_state: Mapping[str, Any],
    attempted_provider_names: Sequence[str],
    produced_at: str,
) -> Path:
    company_name = _normalize_optional_text(target_row.get("company_name")) or "unknown-company"
    artifact_path = paths.general_learning_outreach_discovery_result_path(
        company_name,
        str(target_row["contact_id"]),
    )
    connection.execute(
        """
        DELETE FROM artifact_records
        WHERE artifact_type = ?
          AND contact_id = ?
          AND job_posting_id IS NULL
        """,
        (
            DISCOVERY_RESULT_ARTIFACT_TYPE,
            target_row["contact_id"],
        ),
    )
    publish_json_artifact(
        connection,
        paths,
        artifact_type=DISCOVERY_RESULT_ARTIFACT_TYPE,
        artifact_path=artifact_path,
        producer_component=EMAIL_DISCOVERY_COMPONENT,
        result="success" if result.is_found else "blocked",
        linkage=ArtifactLinkage(contact_id=str(target_row["contact_id"])),
        payload={
            "discovery_attempt_id": discovery_attempt_id,
            "outcome": result.outcome,
            "email": result.email,
            "provider_name": _normalize_optional_text(result.provider_name),
            "provider_verification_status": result.provider_verification_status,
            "provider_score": result.provider_score,
            "detected_pattern": result.detected_pattern,
            "observed_bounced": bool(feedback_reuse_state.get("blocked_emails")),
            "observed_not_bounced": bool(feedback_reuse_state.get("reusable_emails")),
            "reply_retained_for_review_only": bool(feedback_reuse_state.get("reply_only_emails")),
            "feedback_reuse_summary": {
                "blocked_bounced_emails": sorted(
                    str(email) for email in feedback_reuse_state.get("blocked_emails", set())
                ),
                "reusable_not_bounced_emails": sorted(
                    str(email) for email in feedback_reuse_state.get("reusable_emails", set())
                ),
                "reply_only_emails": sorted(
                    str(email) for email in feedback_reuse_state.get("reply_only_emails", set())
                ),
            },
            "attempted_provider_names": list(attempted_provider_names),
            "provider_steps": [dict(step) for step in provider_steps],
            "recipient_profile_artifact_ref": None,
            "recipient_profile_artifact_path": None,
        },
        produced_at=produced_at,
        reason_code=None if result.is_found else result.outcome,
        message=None if result.is_found else _discovery_blocked_message(result.outcome),
    )
    return artifact_path


def _lookup_recipient_profile_artifact(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    job_posting_id: str,
    contact_id: str,
) -> dict[str, str | None]:
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
        (
            RECIPIENT_PROFILE_ARTIFACT_TYPE,
            job_posting_id,
            contact_id,
        ),
    ).fetchone()
    if row is None or not row["file_path"]:
        return {"relative_path": None, "absolute_path": None}
    relative_path = str(row["file_path"])
    return {
        "relative_path": relative_path,
        "absolute_path": str(paths.resolve_from_root(relative_path)),
    }


def _discovery_blocked_message(outcome: str) -> str:
    if outcome == DISCOVERY_OUTCOME_DOMAIN_UNRESOLVED:
        return "Email discovery could not resolve a usable company domain for every required provider path."
    if outcome == DISCOVERY_OUTCOME_RATE_LIMITED:
        return "Email discovery hit a rate-limited provider path before producing a usable email."
    if outcome == DISCOVERY_OUTCOME_QUOTA_EXHAUSTED:
        return "Email discovery exhausted a provider quota before producing a usable email."
    if outcome == DISCOVERY_OUTCOME_INVALID_API_KEY:
        return "Email discovery hit an invalid provider credential while trying to find a usable email."
    if outcome == DISCOVERY_OUTCOME_NETWORK_ERROR:
        return "Email discovery hit a network failure before producing a usable email."
    if outcome == DISCOVERY_OUTCOME_PROVIDER_ERROR:
        return "Email discovery hit a provider execution failure before producing a usable email."
    return "Email discovery did not produce a usable work email for this linked contact."


def _contact_name_parts(contact_row: Mapping[str, Any]) -> tuple[str | None, str | None]:
    first_name = _normalize_optional_text(contact_row.get("first_name"))
    last_name = _normalize_optional_text(contact_row.get("last_name"))
    if first_name and last_name:
        return first_name, last_name
    inferred_first, inferred_last = _split_name(_best_known_contact_name(contact_row) or "")
    return first_name or inferred_first, last_name or inferred_last


def _normalize_prospeo_discovery_result(
    payload: Mapping[str, Any],
    *,
    company_domain: str | None,
) -> EmailDiscoveryProviderResult:
    error_code = _normalize_optional_text(payload.get("error_code"))
    if error_code == "NO_MATCH":
        return EmailDiscoveryProviderResult(
            provider_name=PROVIDER_NAME_PROSPEO,
            outcome=DISCOVERY_OUTCOME_NOT_FOUND,
        )

    data_payload = payload.get("data") if isinstance(payload.get("data"), Mapping) else payload
    email_payload = data_payload.get("email")
    person_payload = data_payload.get("person") if isinstance(data_payload.get("person"), Mapping) else data_payload
    email = _normalize_optional_text(data_payload.get("email"))
    if isinstance(email_payload, Mapping):
        email = email or _normalize_optional_text(
            email_payload.get("email") or email_payload.get("address") or email_payload.get("value")
        )
    if isinstance(person_payload, Mapping):
        email = email or _normalize_optional_text(
            person_payload.get("email") or person_payload.get("work_email")
        )
    verification_status = _normalize_optional_text(
        (email_payload.get("status") if isinstance(email_payload, Mapping) else None)
        or data_payload.get("email_status")
        or (person_payload.get("email_status") if isinstance(person_payload, Mapping) else None)
    )
    provider_score = _normalize_optional_text(
        (email_payload.get("score") if isinstance(email_payload, Mapping) else None)
        or data_payload.get("score")
        or payload.get("score")
    )
    detected_pattern = _normalize_optional_text(
        (email_payload.get("pattern") if isinstance(email_payload, Mapping) else None)
        or data_payload.get("pattern")
    )
    if email and _email_matches_company_domain(email, company_domain):
        if verification_status is None or verification_status.upper() == "VERIFIED":
            return EmailDiscoveryProviderResult(
                provider_name=PROVIDER_NAME_PROSPEO,
                outcome=DISCOVERY_OUTCOME_FOUND,
                email=email,
                provider_verification_status=(verification_status or "VERIFIED").lower(),
                provider_score=provider_score,
                detected_pattern=detected_pattern,
            )
        return EmailDiscoveryProviderResult(
            provider_name=PROVIDER_NAME_PROSPEO,
            outcome=DISCOVERY_OUTCOME_NOT_FOUND,
        )
    return EmailDiscoveryProviderResult(
        provider_name=PROVIDER_NAME_PROSPEO,
        outcome=DISCOVERY_OUTCOME_NOT_FOUND,
    )


def _normalize_getprospect_discovery_result(
    payload: Mapping[str, Any],
    *,
    company_domain: str | None,
) -> EmailDiscoveryProviderResult:
    success_flag = payload.get("success")
    data_payload = payload.get("data") if isinstance(payload.get("data"), Mapping) else {}
    provider_status = _normalize_optional_text(
        data_payload.get("status") or payload.get("status")
    )
    if success_flag is False and provider_status == "not_found":
        return EmailDiscoveryProviderResult(
            provider_name=PROVIDER_NAME_GETPROSPECT,
            outcome=DISCOVERY_OUTCOME_NOT_FOUND,
        )

    email = _normalize_optional_text(
        data_payload.get("email") or data_payload.get("email_address")
    )
    if (
        success_flag is True
        and email
        and _email_matches_company_domain(email, company_domain)
        and provider_status in {"valid", "risky", "accept_all"}
    ):
        return EmailDiscoveryProviderResult(
            provider_name=PROVIDER_NAME_GETPROSPECT,
            outcome=DISCOVERY_OUTCOME_FOUND,
            email=email,
            provider_verification_status=provider_status,
            provider_score=_normalize_optional_text(
                data_payload.get("score") or data_payload.get("confidence")
            ),
            detected_pattern=_normalize_optional_text(data_payload.get("pattern")),
        )
    if success_flag is False or email is None:
        return EmailDiscoveryProviderResult(
            provider_name=PROVIDER_NAME_GETPROSPECT,
            outcome=DISCOVERY_OUTCOME_NOT_FOUND,
        )
    return EmailDiscoveryProviderResult(
        provider_name=PROVIDER_NAME_GETPROSPECT,
        outcome=DISCOVERY_OUTCOME_PROVIDER_ERROR,
    )


def _normalize_hunter_discovery_result(
    payload: Mapping[str, Any],
    *,
    company_domain: str | None,
) -> EmailDiscoveryProviderResult:
    data_payload = payload.get("data") if isinstance(payload.get("data"), Mapping) else {}
    email = _normalize_optional_text(data_payload.get("email"))
    if email is None:
        return EmailDiscoveryProviderResult(
            provider_name=PROVIDER_NAME_HUNTER,
            outcome=DISCOVERY_OUTCOME_NOT_FOUND,
        )
    if not _email_matches_company_domain(email, company_domain):
        return EmailDiscoveryProviderResult(
            provider_name=PROVIDER_NAME_HUNTER,
            outcome=DISCOVERY_OUTCOME_NOT_FOUND,
        )
    return EmailDiscoveryProviderResult(
        provider_name=PROVIDER_NAME_HUNTER,
        outcome=DISCOVERY_OUTCOME_FOUND,
        email=email,
        provider_verification_status=_normalize_optional_text(
            data_payload.get("verification") or data_payload.get("status") or data_payload.get("result")
        ),
        provider_score=_normalize_optional_text(
            data_payload.get("score") or data_payload.get("confidence")
        ),
        detected_pattern=_normalize_optional_text(data_payload.get("pattern")),
    )


def _extract_budget_snapshot(
    payload: Mapping[str, Any],
    *,
    remaining_paths: Sequence[Sequence[str]],
    limit_paths: Sequence[Sequence[str]],
    reset_paths: Sequence[Sequence[str]],
) -> dict[str, int | str | None] | None:
    remaining_credits = _first_non_none_int(payload, remaining_paths)
    credit_limit = _first_non_none_int(payload, limit_paths)
    reset_at = _first_non_none_text(payload, reset_paths)
    if remaining_credits is None and credit_limit is None and reset_at is None:
        return None
    return {
        "remaining_credits": remaining_credits,
        "credit_limit": credit_limit,
        "reset_at": reset_at,
    }


def _first_non_none_int(payload: Mapping[str, Any], paths: Sequence[Sequence[str]]) -> int | None:
    for path in paths:
        value = _mapping_value_at_path(payload, path)
        normalized = _normalize_optional_int(value)
        if normalized is not None:
            return normalized
    return None


def _first_non_none_text(payload: Mapping[str, Any], paths: Sequence[Sequence[str]]) -> str | None:
    for path in paths:
        value = _mapping_value_at_path(payload, path)
        normalized = _normalize_optional_text(value)
        if normalized is not None:
            return normalized
    return None


def _mapping_value_at_path(payload: Mapping[str, Any], path: Sequence[str]) -> Any:
    current: Any = payload
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _email_matches_company_domain(email: str, company_domain: str | None) -> bool:
    if company_domain is None:
        return True
    email_domain = email.split("@", 1)[-1].strip().lower()
    normalized_domain = company_domain.strip().lower()
    return (
        email_domain == normalized_domain
        or normalized_domain.endswith(f".{email_domain}")
        or email_domain.endswith(f".{normalized_domain}")
    )


def _needs_apollo_contact_enrichment(contact_row: Mapping[str, Any]) -> bool:
    return (
        _is_contact_identity_sparse(contact_row)
        or not _is_usable_email(_normalize_optional_text(contact_row.get("current_working_email")))
        or _normalize_optional_text(contact_row.get("linkedin_url")) is None
    )


def _best_known_contact_name(contact_row: Mapping[str, Any]) -> str | None:
    full_name = _normalize_optional_text(contact_row.get("full_name"))
    if full_name and not _name_is_obfuscated(full_name):
        return full_name
    display_name = _normalize_optional_text(contact_row.get("display_name"))
    if display_name and not _name_is_obfuscated(display_name):
        return display_name
    first_name = _normalize_optional_text(contact_row.get("first_name"))
    last_name = _normalize_optional_text(contact_row.get("last_name"))
    if first_name and last_name:
        combined_name = f"{first_name} {last_name}"
        if not _name_is_obfuscated(combined_name):
            return combined_name
    return None


def _normalize_enriched_person(
    payload: ApolloEnrichedPerson | Mapping[str, Any] | None,
) -> ApolloEnrichedPerson | None:
    if payload is None:
        return None
    if isinstance(payload, ApolloEnrichedPerson):
        return payload
    if isinstance(payload, Mapping):
        return ApolloEnrichedPerson.from_mapping(payload)
    raise EmailDiscoveryError("Apollo enrichment rows must be mappings, ApolloEnrichedPerson values, or None.")


def _apply_contact_enrichment(
    connection: sqlite3.Connection,
    *,
    contact_row: Mapping[str, Any],
    posting_row: Mapping[str, Any],
    enrichment: ApolloEnrichedPerson,
    current_time: str,
) -> None:
    provider_person_id = enrichment.provider_person_id or _normalize_optional_text(contact_row.get("provider_person_id"))
    linkedin_url = enrichment.linkedin_url or _normalize_optional_text(contact_row.get("linkedin_url"))
    full_name = enrichment.full_name or _normalize_optional_text(contact_row.get("full_name"))
    display_name = _preferred_display_name(contact_row, enrichment)
    first_name = enrichment.first_name or _normalize_optional_text(contact_row.get("first_name"))
    last_name = enrichment.last_name or _normalize_optional_text(contact_row.get("last_name"))
    if first_name is None or last_name is None:
        inferred_first, inferred_last = _split_name(full_name or display_name)
        first_name = first_name or inferred_first
        last_name = last_name or inferred_last
    current_working_email = enrichment.email if _is_usable_email(enrichment.email) else _normalize_optional_text(
        contact_row.get("current_working_email")
    )
    title = enrichment.title or _normalize_optional_text(contact_row.get("position_title"))
    location = enrichment.location or _normalize_optional_text(contact_row.get("location"))
    identity_key = _contact_identity_key(
        provider_person_id=provider_person_id,
        linkedin_url=linkedin_url,
        display_name=display_name,
        title=title,
    )
    connection.execute(
        """
        UPDATE contacts
        SET identity_key = ?, display_name = ?, company_name = ?, origin_component = ?,
            full_name = ?, first_name = ?, last_name = ?, linkedin_url = ?,
            position_title = ?, location = ?, discovery_summary = ?, current_working_email = ?,
            identity_source = ?, provider_name = ?, provider_person_id = ?, name_quality = ?,
            updated_at = ?
        WHERE contact_id = ?
        """,
        (
            identity_key,
            display_name,
            posting_row["company_name"],
            _normalize_optional_text(contact_row.get("origin_component")) or EMAIL_DISCOVERY_COMPONENT,
            full_name if full_name and not _name_is_obfuscated(full_name) else None,
            first_name,
            last_name,
            linkedin_url,
            title,
            location,
            _build_enrichment_summary(contact_row, enrichment),
            current_working_email,
            "apollo_people_enrichment",
            PROVIDER_NAME_APOLLO,
            provider_person_id,
            _derive_name_quality(display_name, full_name),
            current_time,
            contact_row["contact_id"],
        ),
    )


def _is_terminal_enrichment_dead_end(contact_row: Mapping[str, Any]) -> bool:
    return (
        not _is_usable_email(_normalize_optional_text(contact_row.get("current_working_email")))
        and _normalize_optional_text(contact_row.get("linkedin_url")) is None
        and _best_known_contact_name(contact_row) is None
    )


def _remove_terminal_shortlist_dead_end(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    posting_row: Mapping[str, Any],
    contact_row: Mapping[str, Any],
) -> dict[str, str | None]:
    connection.execute(
        """
        DELETE FROM job_posting_contacts
        WHERE job_posting_contact_id = ?
        """,
        (contact_row["job_posting_contact_id"],),
    )

    removed_contact_id: str | None = None
    if _contact_is_orphaned(connection, contact_id=str(contact_row["contact_id"])):
        _delete_contact_artifacts(connection, paths, contact_id=str(contact_row["contact_id"]))
        connection.execute(
            """
            DELETE FROM contacts
            WHERE contact_id = ?
            """,
            (contact_row["contact_id"],),
        )
        removed_contact_id = str(contact_row["contact_id"])

    return {
        "job_posting_contact_id": str(contact_row["job_posting_contact_id"]),
        "removed_contact_id": removed_contact_id,
        "job_posting_id": str(posting_row["job_posting_id"]),
    }


def _contact_is_orphaned(connection: sqlite3.Connection, *, contact_id: str) -> bool:
    link_count = connection.execute(
        "SELECT COUNT(*) FROM job_posting_contacts WHERE contact_id = ?",
        (contact_id,),
    ).fetchone()[0]
    lead_link_count = connection.execute(
        "SELECT COUNT(*) FROM linkedin_lead_contacts WHERE contact_id = ?",
        (contact_id,),
    ).fetchone()[0]
    discovery_count = connection.execute(
        "SELECT COUNT(*) FROM discovery_attempts WHERE contact_id = ?",
        (contact_id,),
    ).fetchone()[0]
    message_count = connection.execute(
        "SELECT COUNT(*) FROM outreach_messages WHERE contact_id = ?",
        (contact_id,),
    ).fetchone()[0]
    return all(count == 0 for count in (link_count, lead_link_count, discovery_count, message_count))


def _delete_contact_artifacts(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    contact_id: str,
) -> None:
    artifact_rows = connection.execute(
        """
        SELECT artifact_id, file_path
        FROM artifact_records
        WHERE contact_id = ?
        """,
        (contact_id,),
    ).fetchall()
    connection.execute(
        """
        DELETE FROM artifact_records
        WHERE contact_id = ?
        """,
        (contact_id,),
    )
    for artifact_row in artifact_rows:
        artifact_path = paths.resolve_from_root(str(artifact_row["file_path"]))
        if artifact_path.exists() and artifact_path.is_file():
            artifact_path.unlink()


def _should_capture_recipient_profile(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    posting_row: Mapping[str, Any],
    contact_row: Mapping[str, Any],
) -> bool:
    linkedin_url = _normalize_optional_text(contact_row.get("linkedin_url"))
    if linkedin_url is None:
        return False
    artifact_path = paths.discovery_recipient_profile_path(
        str(posting_row["company_name"]),
        str(posting_row["role_title"]),
        str(contact_row["contact_id"]),
    )
    if artifact_path.exists():
        return False
    existing_record = connection.execute(
        """
        SELECT artifact_id
        FROM artifact_records
        WHERE artifact_type = ?
          AND job_posting_id = ?
          AND contact_id = ?
        LIMIT 1
        """,
        (
            RECIPIENT_PROFILE_ARTIFACT_TYPE,
            posting_row["job_posting_id"],
            contact_row["contact_id"],
        ),
    ).fetchone()
    return existing_record is None


def _publish_recipient_profile(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    posting_row: Mapping[str, Any],
    contact_row: Mapping[str, Any],
    profile_payload: Mapping[str, Any],
    produced_at: str,
) -> None:
    artifact_path = paths.discovery_recipient_profile_path(
        str(posting_row["company_name"]),
        str(posting_row["role_title"]),
        str(contact_row["contact_id"]),
    )
    connection.execute(
        """
        DELETE FROM artifact_records
        WHERE artifact_type = ?
          AND job_posting_id = ?
          AND contact_id = ?
        """,
        (
            RECIPIENT_PROFILE_ARTIFACT_TYPE,
            posting_row["job_posting_id"],
            contact_row["contact_id"],
        ),
    )
    publish_json_artifact(
        connection,
        paths,
        artifact_type=RECIPIENT_PROFILE_ARTIFACT_TYPE,
        artifact_path=artifact_path,
        producer_component=EMAIL_DISCOVERY_COMPONENT,
        result="success",
        linkage=ArtifactLinkage(
            job_posting_id=str(posting_row["job_posting_id"]),
            contact_id=str(contact_row["contact_id"]),
        ),
        payload={
            "profile_source": _normalize_optional_text(profile_payload.get("profile_source")) or "linkedin_public_profile",
            "source_method": _normalize_optional_text(profile_payload.get("source_method")) or "public_profile_html",
            "linkedin_url": _normalize_optional_text(contact_row.get("linkedin_url")),
            "profile": dict(profile_payload.get("profile") or {}),
        },
        produced_at=produced_at,
    )


def _promote_contact_to_working_email_found_if_ready(
    connection: sqlite3.Connection,
    *,
    posting_row: Mapping[str, Any],
    contact_row: Mapping[str, Any],
    current_time: str,
) -> None:
    working_email = _normalize_optional_text(contact_row.get("current_working_email"))
    if not _is_usable_email(working_email):
        return
    current_status = _normalize_optional_text(contact_row.get("contact_status")) or CONTACT_STATUS_IDENTIFIED
    if current_status in {
        CONTACT_STATUS_WORKING_EMAIL_FOUND,
        POSTING_CONTACT_STATUS_OUTREACH_IN_PROGRESS,
        "sent",
        "replied",
    }:
        return
    connection.execute(
        """
        UPDATE contacts
        SET contact_status = ?, updated_at = ?
        WHERE contact_id = ?
        """,
        (
            CONTACT_STATUS_WORKING_EMAIL_FOUND,
            current_time,
            contact_row["contact_id"],
        ),
    )
    _record_state_transition(
        connection,
        object_type="contacts",
        object_id=str(contact_row["contact_id"]),
        stage="contact_status",
        previous_state=current_status,
        new_state=CONTACT_STATUS_WORKING_EMAIL_FOUND,
        transition_timestamp=current_time,
        transition_reason="Apollo shortlist enrichment produced or confirmed a usable work email.",
        lead_id=str(posting_row["lead_id"]),
        job_posting_id=str(posting_row["job_posting_id"]),
        contact_id=str(contact_row["contact_id"]),
    )


def _promote_posting_ready_for_outreach_if_eligible(
    connection: sqlite3.Connection,
    *,
    job_posting_id: str,
    lead_id: str,
    current_time: str,
) -> str:
    posting_row = connection.execute(
        """
        SELECT posting_status
        FROM job_postings
        WHERE job_posting_id = ?
        """,
        (job_posting_id,),
    ).fetchone()
    if posting_row is None:
        raise EmailDiscoveryError(f"Job posting `{job_posting_id}` was not found.")
    current_status = str(posting_row["posting_status"])
    if current_status != JOB_POSTING_STATUS_REQUIRES_CONTACTS:
        return current_status
    readiness = evaluate_role_targeted_send_set(
        connection,
        job_posting_id=job_posting_id,
        current_time=current_time,
    )
    if not readiness.ready_for_outreach:
        return current_status
    connection.execute(
        """
        UPDATE job_postings
        SET posting_status = ?, updated_at = ?
        WHERE job_posting_id = ?
        """,
        (
            JOB_POSTING_STATUS_READY_FOR_OUTREACH,
            current_time,
            job_posting_id,
        ),
    )
    _record_state_transition(
        connection,
        object_type="job_postings",
        object_id=job_posting_id,
        stage="posting_status",
        previous_state=current_status,
        new_state=JOB_POSTING_STATUS_READY_FOR_OUTREACH,
        transition_timestamp=current_time,
        transition_reason="The active autonomous send set is fully ready with usable emails for each selected contact.",
        lead_id=lead_id,
        job_posting_id=job_posting_id,
        contact_id=None,
    )
    return JOB_POSTING_STATUS_READY_FOR_OUTREACH


def _evaluate_posting_ready_for_outreach(
    connection: sqlite3.Connection,
    *,
    job_posting_id: str,
) -> dict[str, Any]:
    return evaluate_role_targeted_send_set(
        connection,
        job_posting_id=job_posting_id,
        current_time=now_utc_iso(),
    ).as_dict()


def _materialize_shortlisted_candidate(
    connection: sqlite3.Connection,
    *,
    posting_row: sqlite3.Row,
    candidate: PeopleSearchCandidate,
    current_time: str,
) -> dict[str, str]:
    existing_contact = _find_reusable_contact(connection, candidate)
    if existing_contact is None:
        contact_id = new_canonical_id("contacts")
        timestamps = lifecycle_timestamps(current_time)
        connection.execute(
            """
            INSERT INTO contacts (
              contact_id, identity_key, display_name, company_name, origin_component, contact_status,
              full_name, first_name, last_name, linkedin_url, position_title, location,
              discovery_summary, current_working_email, identity_source, provider_name,
              provider_person_id, name_quality, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                contact_id,
                candidate.identity_key(),
                candidate.display_name,
                posting_row["company_name"],
                EMAIL_DISCOVERY_COMPONENT,
                CONTACT_STATUS_IDENTIFIED,
                candidate.full_name,
                _split_name(candidate.display_name)[0],
                _split_name(candidate.display_name)[1],
                candidate.linkedin_url,
                candidate.title,
                candidate.location,
                candidate.relevance_reason,
                candidate.email,
                "apollo_people_search_shortlist",
                PROVIDER_NAME_APOLLO,
                candidate.provider_person_id,
                candidate.name_quality,
                timestamps["created_at"],
                timestamps["updated_at"],
            ),
        )
    else:
        contact_id = str(existing_contact["contact_id"])
        connection.execute(
            """
            UPDATE contacts
            SET identity_key = ?, display_name = ?, company_name = ?, origin_component = ?,
                full_name = ?, first_name = ?, last_name = ?, linkedin_url = COALESCE(?, linkedin_url),
                position_title = ?, location = COALESCE(?, location),
                discovery_summary = ?, current_working_email = COALESCE(?, current_working_email),
                identity_source = ?, provider_name = ?, provider_person_id = COALESCE(?, provider_person_id),
                name_quality = ?, updated_at = ?
            WHERE contact_id = ?
            """,
            (
                candidate.identity_key(),
                candidate.display_name,
                posting_row["company_name"],
                existing_contact["origin_component"] or EMAIL_DISCOVERY_COMPONENT,
                candidate.full_name,
                _split_name(candidate.display_name)[0],
                _split_name(candidate.display_name)[1],
                candidate.linkedin_url,
                candidate.title,
                candidate.location,
                candidate.relevance_reason,
                candidate.email,
                "apollo_people_search_shortlist",
                PROVIDER_NAME_APOLLO,
                candidate.provider_person_id,
                candidate.name_quality,
                current_time,
                contact_id,
            ),
        )

    existing_link = connection.execute(
        """
        SELECT job_posting_contact_id, link_level_status
        FROM job_posting_contacts
        WHERE job_posting_id = ? AND contact_id = ?
        ORDER BY created_at ASC, job_posting_contact_id ASC
        """,
        (posting_row["job_posting_id"], contact_id),
    ).fetchall()
    if len(existing_link) > 1:
        raise EmailDiscoveryError(
            f"Posting `{posting_row['job_posting_id']}` has multiple links for contact `{contact_id}`."
        )

    if existing_link:
        job_posting_contact_id = str(existing_link[0]["job_posting_contact_id"])
        previous_status = str(existing_link[0]["link_level_status"])
        new_status = _promote_link_status(previous_status)
        connection.execute(
            """
            UPDATE job_posting_contacts
            SET recipient_type = ?, relevance_reason = ?, link_level_status = ?, updated_at = ?
            WHERE job_posting_contact_id = ?
            """,
            (
                candidate.recipient_type,
                candidate.relevance_reason,
                new_status,
                current_time,
                job_posting_contact_id,
            ),
        )
        if new_status != previous_status:
            _record_state_transition(
                connection,
                object_type="job_posting_contacts",
                object_id=job_posting_contact_id,
                stage="link_level_status",
                previous_state=previous_status,
                new_state=new_status,
                transition_timestamp=current_time,
                transition_reason="Apollo shortlist selected this posting-contact pair for enrichment handling.",
                lead_id=posting_row["lead_id"],
                job_posting_id=posting_row["job_posting_id"],
                contact_id=contact_id,
            )
    else:
        job_posting_contact_id = new_canonical_id("job_posting_contacts")
        timestamps = lifecycle_timestamps(current_time)
        connection.execute(
            """
            INSERT INTO job_posting_contacts (
              job_posting_contact_id, job_posting_id, contact_id, recipient_type, relevance_reason,
              link_level_status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_posting_contact_id,
                posting_row["job_posting_id"],
                contact_id,
                candidate.recipient_type,
                candidate.relevance_reason,
                POSTING_CONTACT_STATUS_SHORTLISTED,
                timestamps["created_at"],
                timestamps["updated_at"],
            ),
        )

    return {
        "contact_id": contact_id,
        "job_posting_contact_id": job_posting_contact_id,
    }


def _find_reusable_contact(
    connection: sqlite3.Connection,
    candidate: PeopleSearchCandidate,
) -> sqlite3.Row | None:
    if candidate.provider_person_id:
        rows = connection.execute(
            """
            SELECT contact_id, origin_component
            FROM contacts
            WHERE provider_name = ? AND provider_person_id = ?
            ORDER BY created_at ASC, contact_id ASC
            """,
            (
                PROVIDER_NAME_APOLLO,
                candidate.provider_person_id,
            ),
        ).fetchall()
        if len(rows) == 1:
            return rows[0]
        if len(rows) > 1:
            raise EmailDiscoveryError(
                f"Apollo person `{candidate.provider_person_id}` matches multiple canonical contacts."
            )

    if candidate.linkedin_url:
        rows = connection.execute(
            """
            SELECT contact_id, origin_component
            FROM contacts
            WHERE linkedin_url = ?
            ORDER BY created_at ASC, contact_id ASC
            """,
            (candidate.linkedin_url,),
        ).fetchall()
        if len(rows) == 1:
            return rows[0]
        if len(rows) > 1:
            raise EmailDiscoveryError(
                f"LinkedIn URL `{candidate.linkedin_url}` matches multiple canonical contacts."
            )

    rows = connection.execute(
        """
        SELECT contact_id, origin_component
        FROM contacts
        WHERE identity_key = ?
        ORDER BY created_at ASC, contact_id ASC
        """,
        (candidate.identity_key(),),
    ).fetchall()
    if len(rows) == 1:
        return rows[0]
    if len(rows) > 1:
        raise EmailDiscoveryError(
            f"Identity key `{candidate.identity_key()}` matches multiple canonical contacts."
        )
    return None


def _promote_link_status(previous_status: str) -> str:
    if previous_status == POSTING_CONTACT_STATUS_IDENTIFIED:
        return POSTING_CONTACT_STATUS_SHORTLISTED
    if previous_status in {
        POSTING_CONTACT_STATUS_SHORTLISTED,
        POSTING_CONTACT_STATUS_OUTREACH_IN_PROGRESS,
        POSTING_CONTACT_STATUS_OUTREACH_DONE,
        POSTING_CONTACT_STATUS_EXHAUSTED,
    }:
        return previous_status
    return POSTING_CONTACT_STATUS_SHORTLISTED


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
            EMAIL_DISCOVERY_COMPONENT,
            lead_id,
            job_posting_id,
            contact_id,
        ),
    )


def _apollo_enriched_location(payload: Mapping[str, Any]) -> str | None:
    direct_location = _normalize_optional_text(
        payload.get("location") or payload.get("present_raw_address") or payload.get("raw_address")
    )
    if direct_location:
        return direct_location
    parts = [
        _normalize_optional_text(payload.get("city")),
        _normalize_optional_text(payload.get("state")),
        _normalize_optional_text(payload.get("country")),
    ]
    filtered = [part for part in parts if part]
    return ", ".join(filtered) if filtered else None


def _is_contact_identity_sparse(contact_row: Mapping[str, Any]) -> bool:
    return _best_known_contact_name(contact_row) is None


def _preferred_display_name(
    contact_row: Mapping[str, Any],
    enrichment: ApolloEnrichedPerson,
) -> str:
    enriched_display = _normalize_optional_text(enrichment.full_name or enrichment.display_name)
    if enriched_display and not _name_is_obfuscated(enriched_display):
        return enriched_display
    existing_display = _normalize_optional_text(contact_row.get("display_name"))
    if existing_display:
        return existing_display
    return enriched_display or f"Apollo person {_normalize_optional_text(contact_row.get('provider_person_id')) or 'unknown'}"


def _build_enrichment_summary(
    contact_row: Mapping[str, Any],
    enrichment: ApolloEnrichedPerson,
) -> str:
    summary_parts: list[str] = []
    if enrichment.title:
        summary_parts.append(f"Apollo enrichment matched this contact as `{enrichment.title}`.")
    if _is_usable_email(enrichment.email):
        summary_parts.append("Apollo enrichment returned a usable work email.")
    if enrichment.headline:
        summary_parts.append(f"Headline hint: {enrichment.headline}")
    existing_summary = _normalize_optional_text(contact_row.get("discovery_summary"))
    if not summary_parts and existing_summary:
        return existing_summary
    return " ".join(summary_parts) if summary_parts else "Apollo enrichment refreshed the shortlisted contact."


def _derive_name_quality(display_name: str, full_name: str | None) -> str:
    if _name_is_obfuscated(display_name):
        return "provider_obfuscated"
    if full_name and not _name_is_obfuscated(full_name):
        return "provider_full"
    return "provider_sparse"


def _contact_identity_key(
    *,
    provider_person_id: str | None,
    linkedin_url: str | None,
    display_name: str,
    title: str | None,
) -> str:
    if provider_person_id:
        return f"apollo_person|{provider_person_id}"
    if linkedin_url:
        return f"linkedin_profile|{workspace_slug(linkedin_url)}"
    return "|".join(
        [
            "apollo_enrichment",
            workspace_slug(display_name),
            workspace_slug(title or "unknown"),
        ]
    )


def _extract_linkedin_public_profile(
    html_text: str,
    *,
    linkedin_url: str,
    contact: Mapping[str, Any],
    posting: Mapping[str, Any],
) -> dict[str, Any] | None:
    if not html_text.strip():
        return None

    json_ld_candidates = _extract_json_ld_candidates(html_text)
    person_ld = _find_person_json_ld(json_ld_candidates)
    meta_title = _first_non_empty(
        _meta_content(html_text, "og:title"),
        _meta_content(html_text, "twitter:title"),
    )
    meta_description = _first_non_empty(
        _meta_content(html_text, "description"),
        _meta_content(html_text, "og:description"),
        _meta_content(html_text, "twitter:description"),
    )

    identity_name = _first_non_empty(
        _json_ld_text(person_ld, "name"),
        _normalize_optional_text(contact.get("full_name")),
        _normalize_optional_text(contact.get("display_name")),
        meta_title,
    )
    if identity_name is None:
        return None

    person_company = _json_ld_nested_text(person_ld, "worksFor", "name")
    person_title = _first_non_empty(
        _json_ld_text(person_ld, "jobTitle"),
        _normalize_optional_text(contact.get("position_title")),
    )
    person_location = _first_non_empty(
        _json_ld_nested_text(person_ld, "address", "addressLocality"),
        _normalize_optional_text(contact.get("location")),
    )
    top_card_location = _compose_address(
        _json_ld_nested_text(person_ld, "address", "addressLocality"),
        _json_ld_nested_text(person_ld, "address", "addressRegion"),
        _json_ld_nested_text(person_ld, "address", "addressCountry"),
    ) or person_location
    connections = _extract_regex_group(CONNECTIONS_RE, html_text)
    followers = _extract_regex_group(FOLLOWERS_RE, html_text)
    about_preview = _normalize_optional_text(meta_description)
    headline = _first_non_empty(_json_ld_text(person_ld, "description"), meta_title)
    if headline == identity_name:
        headline = None

    work_signals = _inferred_work_signals(contact=contact, posting=posting, current_company=person_company)
    evidence_snippets = [
        snippet
        for snippet in [
            f"Current company hint: {person_company}" if person_company else None,
            f"Public headline: {headline}" if headline else None,
            f"About preview: {about_preview}" if about_preview else None,
        ]
        if snippet
    ]
    return {
        "identity": {
            "display_name": identity_name,
            "full_name": identity_name if not _name_is_obfuscated(identity_name) and " " in identity_name else None,
            "first_name": _json_ld_text(person_ld, "givenName") or _split_name(identity_name)[0],
            "last_name": _json_ld_text(person_ld, "familyName") or _split_name(identity_name)[1],
        },
        "top_card": {
            "current_company": person_company or _normalize_optional_text(contact.get("company_name")),
            "current_title": person_title,
            "headline": headline,
            "location": top_card_location,
            "connections": connections,
            "followers": followers,
        },
        "about": {
            "preview_text": about_preview,
            "is_truncated": False,
        },
        "experience_hints": {
            "current_company_hint": person_company,
            "education_hint": None,
            "experience_education_preview": about_preview,
        },
        "recent_public_activity": [],
        "public_signals": {
            "licenses_and_certifications": [],
            "honors_and_awards": [],
            "recommendation_entities": [],
        },
        "work_signals": work_signals,
        "evidence_snippets": evidence_snippets,
        "source_coverage": {
            "about": bool(about_preview),
            "activity": False,
            "experience_hint": bool(person_company),
            "public_signals": False,
        },
    }


def _extract_json_ld_candidates(html_text: str) -> list[Mapping[str, Any]]:
    candidates: list[Mapping[str, Any]] = []
    for match in JSON_LD_RE.finditer(html_text):
        body = html.unescape(match.group("body")).strip()
        if not body:
            continue
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, Mapping):
            candidates.append(payload)
        elif isinstance(payload, list):
            candidates.extend(item for item in payload if isinstance(item, Mapping))
    return candidates


def _find_person_json_ld(candidates: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    for candidate in candidates:
        type_name = str(candidate.get("@type") or "").lower()
        if type_name == "person":
            return candidate
        if type_name == "profilepage":
            main_entity = candidate.get("mainEntity")
            if isinstance(main_entity, Mapping):
                main_type = str(main_entity.get("@type") or "").lower()
                if main_type == "person":
                    return main_entity
    return None


def _json_ld_text(payload: Mapping[str, Any] | None, key: str) -> str | None:
    if not isinstance(payload, Mapping):
        return None
    return _normalize_optional_text(payload.get(key))


def _json_ld_nested_text(payload: Mapping[str, Any] | None, key: str, nested_key: str) -> str | None:
    if not isinstance(payload, Mapping):
        return None
    nested = payload.get(key)
    if isinstance(nested, Mapping):
        return _normalize_optional_text(nested.get(nested_key))
    if isinstance(nested, list):
        for item in nested:
            if isinstance(item, Mapping):
                value = _normalize_optional_text(item.get(nested_key))
                if value:
                    return value
    return None


def _meta_content(html_text: str, key: str) -> str | None:
    target = key.lower()
    for match in META_TAG_RE.finditer(html_text):
        if match.group("key").strip().lower() == target:
            return _normalize_optional_text(html.unescape(match.group("value")))
    return None


def _compose_address(*parts: str | None) -> str | None:
    filtered = [part for part in parts if _normalize_optional_text(part)]
    return ", ".join(filtered) if filtered else None


def _extract_regex_group(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    if not match:
        return None
    return _normalize_optional_text(match.group(1))


def _inferred_work_signals(
    *,
    contact: Mapping[str, Any],
    posting: Mapping[str, Any],
    current_company: str | None,
) -> list[str]:
    signals: list[str] = []
    title = (_normalize_optional_text(contact.get("position_title")) or "").lower()
    recipient_type = (_normalize_optional_text(contact.get("recipient_type")) or "").lower()
    company_name = _normalize_optional_text(posting.get("company_name"))
    if recipient_type == RECIPIENT_TYPE_RECRUITER or "recruit" in title or "talent" in title:
        signals.append("recruiting function close to the target role")
    elif recipient_type == RECIPIENT_TYPE_HIRING_MANAGER or "manager" in title or "director" in title:
        signals.append("engineering leadership close to the likely hiring loop")
    elif recipient_type == RECIPIENT_TYPE_ENGINEER or "engineer" in title or "developer" in title:
        signals.append("role-relevant internal engineer")
    if company_name and current_company and workspace_slug(company_name) == workspace_slug(current_company):
        signals.append("current internal employee at the target company")
    return signals


def _first_non_empty(*values: str | None) -> str | None:
    for value in values:
        normalized = _normalize_optional_text(value)
        if normalized:
            return normalized
    return None


def _extract_sequence(payload: Mapping[str, Any], keys: Sequence[str]) -> list[Any]:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            return list(value)
    return []


def _combine_name_parts(payload: Mapping[str, Any]) -> str | None:
    first_name = _normalize_optional_text(payload.get("first_name"))
    last_name = _normalize_optional_text(payload.get("last_name"))
    if first_name and last_name:
        return f"{first_name} {last_name}"
    return first_name or last_name


def _name_is_obfuscated(value: str) -> bool:
    return bool(OBFUSCATED_NAME_RE.search(value))


def _normalize_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _normalize_email(value: Any) -> str | None:
    normalized = _normalize_optional_text(value)
    if normalized is None:
        return None
    return normalized.lower()


def _normalize_optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    normalized = str(value).strip().replace(",", "")
    if normalized.startswith("-"):
        digits = normalized[1:]
        return int(normalized) if digits.isdigit() else None
    return int(normalized) if normalized.isdigit() else None


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    normalized = _normalize_optional_text(value)
    if normalized is None:
        return False
    return normalized.lower() in {"1", "true", "yes", "y"}


def _is_usable_email(value: str | None) -> bool:
    return bool(value and EMAIL_RE.match(value))


def _split_name(display_name: str) -> tuple[str | None, str | None]:
    parts = [part for part in display_name.split() if part]
    if not parts:
        return None, None
    if len(parts) == 1:
        return parts[0], None
    return parts[0], " ".join(parts[1:])


def _dedupe_preserve_order(values: Sequence[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = _normalize_optional_text(value)
        if normalized is None:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(normalized)
    return deduped
