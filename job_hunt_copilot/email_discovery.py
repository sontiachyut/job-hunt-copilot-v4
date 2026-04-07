from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .artifacts import ArtifactLinkage, publish_json_artifact
from .paths import ProjectPaths, workspace_slug
from .records import lifecycle_timestamps, new_canonical_id, now_utc_iso


EMAIL_DISCOVERY_COMPONENT = "email_discovery"
PEOPLE_SEARCH_ARTIFACT_TYPE = "people_search_result"
PROVIDER_NAME_APOLLO = "apollo"

JOB_POSTING_STATUS_REQUIRES_CONTACTS = "requires_contacts"
RESUME_REVIEW_STATUS_APPROVED = "approved"

CONTACT_STATUS_IDENTIFIED = "identified"
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

APOLLO_COMPANY_SEARCH_URL = "https://api.apollo.io/api/v1/mixed_companies/search"
APOLLO_PEOPLE_SEARCH_URL = "https://api.apollo.io/api/v1/mixed_people/api_search"

OBFUSCATED_NAME_RE = re.compile(r"[*•·]|(?:[A-Za-z]{2,}\*{2,})|(?:\*{2,}[A-Za-z]{2,})")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
WORD_RE = re.compile(r"[A-Za-z0-9]+")

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


class ConfiguredApolloClient:
    def __init__(self, *, api_key: str, timeout_seconds: float = 30.0) -> None:
        if not api_key.strip():
            raise EmailDiscoveryError("Apollo API key is required for company-scoped people search.")
        self.api_key = api_key.strip()
        self.timeout_seconds = timeout_seconds

    @classmethod
    def from_paths(cls, paths: ProjectPaths) -> "ConfiguredApolloClient":
        secret_path = paths.secrets_dir / "apollo_keys.json"
        if not secret_path.exists():
            raise EmailDiscoveryError(
                f"Apollo secret file was not found at `{secret_path}`.",
                reason_code="missing_apollo_secret",
            )
        payload = json.loads(secret_path.read_text(encoding="utf-8"))
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
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                response_body = response.read().decode("utf-8")
                status_code = response.getcode()
        except HTTPError as exc:  # pragma: no cover - covered via normalization logic only
            reason_code = {
                401: "invalid_api_key",
                403: "plan_restricted",
                429: "rate_limited",
            }.get(exc.code, "provider_error")
            raise EmailDiscoveryError(
                f"Apollo request failed with HTTP {exc.code}.",
                reason_code=reason_code,
            ) from exc
        except URLError as exc:  # pragma: no cover - covered via normalization logic only
            raise EmailDiscoveryError(
                "Apollo request failed with a network error.",
                reason_code="network_error",
            ) from exc

        if status_code != 200:  # pragma: no cover - defensive guard
            raise EmailDiscoveryError(
                f"Apollo request returned unexpected status {status_code}.",
                reason_code="provider_error",
            )
        try:
            payload = json.loads(response_body)
        except json.JSONDecodeError as exc:  # pragma: no cover - defensive guard
            raise EmailDiscoveryError(
                "Apollo returned malformed JSON.",
                reason_code="provider_error",
            ) from exc
        if not isinstance(payload, Mapping):
            raise EmailDiscoveryError(
                "Apollo returned a malformed top-level response body.",
                reason_code="provider_error",
            )
        return payload


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
