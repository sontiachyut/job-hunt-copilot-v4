from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator
import yaml

from .paths import ProjectPaths
from .records import now_utc_iso

PROFILE_EVIDENCE_SOURCE_TYPES = frozenset(
    {
        "resume_experience",
        "resume_project",
        "job_hunt_copilot",
        "tennis_augmented",
        "education",
    }
)
PROFILE_EVIDENCE_TYPES = frozenset(
    {
        "achievement",
        "project",
        "system",
        "reliability",
        "stakeholder",
        "skill_anchor",
    }
)

_TAG_TOKEN_RE = re.compile(r"[^a-z0-9]+")
_TEXT_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9+\-/]*")
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "because",
        "been",
        "by",
        "for",
        "from",
        "into",
        "in",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "their",
        "this",
        "to",
        "using",
        "with",
    }
)
_TECHNICAL_THEME_TAGS = frozenset({"ai", "backend", "cloud", "data", "distributed", "platform"})
_RELIABILITY_HINTS = frozenset(
    {"availability", "incident", "monitoring", "observability", "reliability", "sla", "support", "uptime"}
)
_PROJECT_SOURCE_TYPES = frozenset({"resume_project", "job_hunt_copilot", "tennis_augmented"})


class ProfileEvidenceError(RuntimeError):
    """Base profile-evidence failure."""


class ProfileEvidenceBuildError(ProfileEvidenceError):
    """Curated profile-evidence source could not be materialized."""


class ProfileEvidenceUnavailableError(ProfileEvidenceError):
    """Canonical corpus is missing or empty."""


class ProfileEvidenceRetrievalError(ProfileEvidenceError):
    """No sufficiently grounded evidence pack could be produced."""


class ProfileEvidenceChunkInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    text: str
    source_type: Literal[
        "resume_experience",
        "resume_project",
        "job_hunt_copilot",
        "tennis_augmented",
        "education",
    ]
    evidence_type: Literal[
        "achievement",
        "project",
        "system",
        "reliability",
        "stakeholder",
        "skill_anchor",
    ]
    skill_tags: list[str]
    theme_tags: list[str]
    strength: int = Field(ge=1, le=5)

    @field_validator("evidence_id")
    @classmethod
    def _validate_evidence_id(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{2,}", normalized):
            raise ValueError("evidence_id must be a stable lowercase token")
        return normalized

    @field_validator("text")
    @classmethod
    def _validate_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("text must not be empty")
        return normalized

    @field_validator("skill_tags", "theme_tags")
    @classmethod
    def _validate_tags(cls, value: list[str]) -> list[str]:
        normalized = _normalize_tag_list(value)
        if not normalized:
            raise ValueError("tag lists must contain at least one normalized token")
        return normalized


@dataclass(frozen=True)
class ProfileEvidenceChunkRecord:
    evidence_id: str
    text: str
    source_type: str
    evidence_type: str
    skill_tags: tuple[str, ...]
    theme_tags: tuple[str, ...]
    strength: int

    def as_storage_row(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "text": self.text,
            "source_type": self.source_type,
            "evidence_type": self.evidence_type,
            "skill_tags_json": json.dumps(list(self.skill_tags)),
            "theme_tags_json": json.dumps(list(self.theme_tags)),
            "strength": self.strength,
        }

    def as_prompt_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "text": self.text,
            "source_type": self.source_type,
            "evidence_type": self.evidence_type,
            "skill_tags": list(self.skill_tags),
            "theme_tags": list(self.theme_tags),
            "strength": self.strength,
        }

    @property
    def is_project_derived(self) -> bool:
        return self.source_type in _PROJECT_SOURCE_TYPES or self.evidence_type == "project"

    @property
    def is_reliability(self) -> bool:
        return self.evidence_type == "reliability" or "reliability" in self.theme_tags

    @property
    def is_technical(self) -> bool:
        return bool(_TECHNICAL_THEME_TAGS.intersection(self.theme_tags)) or self.evidence_type in {
            "achievement",
            "project",
            "skill_anchor",
            "system",
        }


@dataclass(frozen=True)
class RankedProfileEvidenceChunk:
    chunk: ProfileEvidenceChunkRecord
    score: float
    lexical_overlap: tuple[str, ...]
    theme_overlap: tuple[str, ...]
    skill_overlap: tuple[str, ...]

    @property
    def is_strong_match(self) -> bool:
        return (
            self.chunk.strength >= 3
            and (
                bool(self.theme_overlap)
                or bool(self.skill_overlap)
                or len(self.lexical_overlap) >= 2
            )
            and self.score >= 4.0
        )


@dataclass(frozen=True)
class ProfileEvidenceBuildResult:
    source_path: Path
    mirror_path: Path
    chunk_count: int


@dataclass(frozen=True)
class ManagerialProfileEvidenceSelection:
    candidate_chunks: tuple[ProfileEvidenceChunkRecord, ...]
    prompt_chunks: tuple[ProfileEvidenceChunkRecord, ...]


def load_curated_profile_evidence_source(paths: ProjectPaths) -> tuple[ProfileEvidenceChunkRecord, ...]:
    source_path = paths.managerial_profile_evidence_source_path
    if not source_path.exists():
        raise ProfileEvidenceBuildError(f"Missing curated profile-evidence source: {source_path}")
    try:
        payload = yaml.safe_load(source_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ProfileEvidenceBuildError(
            f"Curated profile-evidence source is invalid YAML: {source_path}"
        ) from exc
    if not isinstance(payload, Mapping):
        raise ProfileEvidenceBuildError("Curated profile-evidence source must be a YAML object")
    raw_chunks = payload.get("chunks")
    if not isinstance(raw_chunks, list):
        raise ProfileEvidenceBuildError("Curated profile-evidence source must contain a top-level chunks list")
    chunks: list[ProfileEvidenceChunkRecord] = []
    seen_ids: set[str] = set()
    for raw_chunk in raw_chunks:
        chunk_input = ProfileEvidenceChunkInput.model_validate(raw_chunk)
        if chunk_input.evidence_id in seen_ids:
            raise ProfileEvidenceBuildError(
                f"Duplicate evidence_id `{chunk_input.evidence_id}` in curated profile-evidence source"
            )
        seen_ids.add(chunk_input.evidence_id)
        chunks.append(
            ProfileEvidenceChunkRecord(
                evidence_id=chunk_input.evidence_id,
                text=chunk_input.text,
                source_type=chunk_input.source_type,
                evidence_type=chunk_input.evidence_type,
                skill_tags=tuple(chunk_input.skill_tags),
                theme_tags=tuple(chunk_input.theme_tags),
                strength=chunk_input.strength,
            )
        )
    if not chunks:
        raise ProfileEvidenceBuildError("Curated profile-evidence source must contain at least one chunk")
    return tuple(chunks)


def build_profile_evidence_corpus(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
) -> ProfileEvidenceBuildResult:
    chunks = load_curated_profile_evidence_source(paths)
    built_at = now_utc_iso()
    with connection:
        connection.execute("DELETE FROM profile_evidence_chunks")
        for chunk in chunks:
            row = chunk.as_storage_row()
            connection.execute(
                """
                INSERT INTO profile_evidence_chunks (
                  evidence_id,
                  text,
                  source_type,
                  evidence_type,
                  skill_tags_json,
                  theme_tags_json,
                  strength,
                  is_active,
                  created_at,
                  updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    row["evidence_id"],
                    row["text"],
                    row["source_type"],
                    row["evidence_type"],
                    row["skill_tags_json"],
                    row["theme_tags_json"],
                    row["strength"],
                    built_at,
                    built_at,
                ),
            )
    paths.ops_profile_evidence_latest_dir.mkdir(parents=True, exist_ok=True)
    mirror_payload = {
        "built_at": built_at,
        "source_path": paths.relative_to_root(paths.managerial_profile_evidence_source_path).as_posix(),
        "chunks": [chunk.as_prompt_dict() for chunk in chunks],
    }
    paths.profile_evidence_mirror_json_path.write_text(
        json.dumps(mirror_payload, indent=2) + "\n",
        encoding="utf-8",
    )
    return ProfileEvidenceBuildResult(
        source_path=paths.managerial_profile_evidence_source_path,
        mirror_path=paths.profile_evidence_mirror_json_path,
        chunk_count=len(chunks),
    )


def load_active_profile_evidence_chunks(
    connection: sqlite3.Connection,
) -> tuple[ProfileEvidenceChunkRecord, ...]:
    rows = connection.execute(
        """
        SELECT evidence_id, text, source_type, evidence_type, skill_tags_json, theme_tags_json, strength
        FROM profile_evidence_chunks
        WHERE is_active = 1
        ORDER BY evidence_id
        """
    ).fetchall()
    chunks = tuple(_chunk_record_from_row(row) for row in rows)
    if not chunks:
        raise ProfileEvidenceUnavailableError(
            "Canonical profile-evidence corpus is missing or empty; run the explicit corpus-build step first."
        )
    return chunks


def retrieve_managerial_profile_evidence(
    connection: sqlite3.Connection,
    *,
    role_title: str,
    role_theme: str,
    bounded_jd_relevance_pack: Sequence[Mapping[str, Any]],
) -> ManagerialProfileEvidenceSelection:
    chunks = load_active_profile_evidence_chunks(connection)
    query_texts = [role_title, role_theme]
    for item in bounded_jd_relevance_pack:
        for key in ("jd_signal", "supporting_line"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                query_texts.append(value.strip())
    query_tokens = _tokenize_text_fragments(query_texts)
    query_theme_tags = _derive_theme_tags(query_texts)
    if not query_tokens and not query_theme_tags:
        raise ProfileEvidenceRetrievalError("Managerial evidence retrieval could not derive any query signals")

    technical_heavy = bool(_TECHNICAL_THEME_TAGS.intersection(query_theme_tags))
    reliability_heavy = bool(_RELIABILITY_HINTS.intersection(query_tokens))
    ranked = [_rank_profile_evidence_chunk(chunk, query_tokens, query_theme_tags, technical_heavy) for chunk in chunks]
    if not reliability_heavy:
        best_theme_aligned_non_reliability = max(
            (
                item.score
                for item in ranked
                if not item.chunk.is_reliability and (item.theme_overlap or item.skill_overlap or item.lexical_overlap)
            ),
            default=None,
        )
        if best_theme_aligned_non_reliability is not None:
            adjusted_ranked: list[RankedProfileEvidenceChunk] = []
            for item in ranked:
                if item.chunk.is_reliability and best_theme_aligned_non_reliability > item.score:
                    adjusted_ranked.append(
                        RankedProfileEvidenceChunk(
                            chunk=item.chunk,
                            score=item.score - 2.5,
                            lexical_overlap=item.lexical_overlap,
                            theme_overlap=item.theme_overlap,
                            skill_overlap=item.skill_overlap,
                        )
                    )
                else:
                    adjusted_ranked.append(item)
            ranked = adjusted_ranked

    ranked.sort(key=lambda item: (-item.score, -item.chunk.strength, item.chunk.evidence_id))
    strong_ranked = [item for item in ranked if item.is_strong_match]
    if len(strong_ranked) < 3:
        raise ProfileEvidenceRetrievalError(
            "Managerial evidence retrieval could not produce three grounded evidence chunks."
        )
    candidate_ranked = strong_ranked[:8]
    selected_ranked = _select_prompt_chunks(
        candidate_ranked,
        technical_heavy=technical_heavy,
        reliability_heavy=reliability_heavy,
    )
    if len(selected_ranked) < 3:
        raise ProfileEvidenceRetrievalError(
            "Managerial evidence retrieval could not preserve three strong prompt chunks after diversity filtering."
        )
    return ManagerialProfileEvidenceSelection(
        candidate_chunks=tuple(item.chunk for item in candidate_ranked),
        prompt_chunks=tuple(item.chunk for item in selected_ranked[:5]),
    )


def _chunk_record_from_row(row: Any) -> ProfileEvidenceChunkRecord:
    skill_tags = tuple(_normalize_tag_list(json.loads(str(row["skill_tags_json"]))))
    theme_tags = tuple(_normalize_tag_list(json.loads(str(row["theme_tags_json"]))))
    return ProfileEvidenceChunkRecord(
        evidence_id=str(row["evidence_id"]),
        text=str(row["text"]),
        source_type=str(row["source_type"]),
        evidence_type=str(row["evidence_type"]),
        skill_tags=skill_tags,
        theme_tags=theme_tags,
        strength=int(row["strength"]),
    )


def _rank_profile_evidence_chunk(
    chunk: ProfileEvidenceChunkRecord,
    query_tokens: frozenset[str],
    query_theme_tags: frozenset[str],
    technical_heavy: bool,
) -> RankedProfileEvidenceChunk:
    chunk_text_tokens = _tokenize_text_fragments((chunk.text,))
    chunk_skill_tokens = _tokenize_text_fragments(chunk.skill_tags)
    lexical_overlap = tuple(sorted(query_tokens.intersection(chunk_text_tokens)))
    skill_overlap = tuple(sorted(query_tokens.intersection(chunk_skill_tokens)))
    theme_overlap = tuple(sorted(query_theme_tags.intersection(chunk.theme_tags)))
    score = float(chunk.strength * 1.5)
    score += len(theme_overlap) * 3.0
    score += len(skill_overlap) * 1.8
    score += len(lexical_overlap) * 0.7
    if chunk.source_type == "resume_experience":
        score += 0.9
    elif chunk.source_type == "education":
        score -= 0.2
    if chunk.evidence_type == "achievement":
        score += 0.8
    elif chunk.evidence_type == "system":
        score += 0.9
    elif chunk.evidence_type == "stakeholder" and technical_heavy:
        score -= 0.2
    if chunk.is_project_derived:
        score -= 0.35
    if technical_heavy and chunk.is_technical:
        score += 0.75
    return RankedProfileEvidenceChunk(
        chunk=chunk,
        score=score,
        lexical_overlap=lexical_overlap,
        theme_overlap=theme_overlap,
        skill_overlap=skill_overlap,
    )


def _select_prompt_chunks(
    ranked_chunks: Sequence[RankedProfileEvidenceChunk],
    *,
    technical_heavy: bool,
    reliability_heavy: bool,
) -> list[RankedProfileEvidenceChunk]:
    selected: list[RankedProfileEvidenceChunk] = []
    project_count = 0
    reliability_count = 0

    def can_add(item: RankedProfileEvidenceChunk) -> bool:
        nonlocal project_count, reliability_count
        if item.chunk.is_project_derived and project_count >= 1:
            return False
        if item.chunk.is_reliability and not reliability_heavy and reliability_count >= 1:
            return False
        return True

    for item in ranked_chunks:
        if technical_heavy and len(selected) < 2 and not item.chunk.is_technical:
            continue
        if not can_add(item):
            continue
        selected.append(item)
        if item.chunk.is_project_derived:
            project_count += 1
        if item.chunk.is_reliability:
            reliability_count += 1
        if len(selected) >= 5:
            return selected

    for item in ranked_chunks:
        if item in selected or not can_add(item):
            continue
        selected.append(item)
        if item.chunk.is_project_derived:
            project_count += 1
        if item.chunk.is_reliability:
            reliability_count += 1
        if len(selected) >= 5:
            break
    return selected


def _normalize_tag_list(values: Iterable[Any]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_value in values:
        if raw_value is None:
            continue
        candidate = _normalize_tag_token(str(raw_value))
        if candidate is None or candidate in seen:
            continue
        seen.add(candidate)
        normalized.append(candidate)
    return normalized


def _normalize_tag_token(value: str) -> str | None:
    lowered = value.strip().lower()
    if not lowered:
        return None
    candidate = _TAG_TOKEN_RE.sub("-", lowered).strip("-")
    return candidate or None


def _tokenize_text_fragments(fragments: Iterable[str]) -> frozenset[str]:
    tokens: set[str] = set()
    for fragment in fragments:
        for match in _TEXT_TOKEN_RE.findall(str(fragment).lower()):
            if match in _STOPWORDS:
                continue
            tokens.add(match)
    return frozenset(tokens)


def _derive_theme_tags(texts: Iterable[str]) -> frozenset[str]:
    joined = " ".join(str(text) for text in texts if str(text).strip()).lower()
    tags: set[str] = set()
    tag_rules: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("ai", ("agent", "ai", "bedrock", "genai", "generative", "llm", "machine learning", "workflow automation")),
        ("backend", ("api", "backend", "service", "software engineer")),
        ("distributed", ("distributed", "latency", "scale", "throughput")),
        ("reliability", ("incident", "monitoring", "observability", "reliability", "sla", "uptime")),
        ("data", ("analytics", "data", "etl", "hl7", "pipeline", "spark")),
        ("cloud", ("aws", "azure", "cloud", "gcp", "serverless")),
        ("platform", ("docker", "infrastructure", "kubernetes", "platform")),
        ("workflow-automation", ("orchestration", "workflow", "workflows")),
        ("stakeholder-enablement", ("adoption", "client", "coach", "coaching", "enablement", "stakeholder", "users")),
    )
    for tag, keywords in tag_rules:
        if any(keyword in joined for keyword in keywords):
            tags.add(tag)
    return frozenset(tags)
