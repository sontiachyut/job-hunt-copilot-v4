from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from .contracts import CONTRACT_VERSION
from .paths import ProjectPaths
from .records import new_canonical_id, now_utc_iso


FAILURE_RESULTS = frozenset({"blocked", "failed", "error"})
ENVELOPE_FIELDS = frozenset(
    {
        "contract_version",
        "produced_at",
        "producer_component",
        "result",
        "reason_code",
        "message",
        "lead_id",
        "job_posting_id",
        "contact_id",
        "outreach_message_id",
    }
)


@dataclass(frozen=True)
class ArtifactLinkage:
    lead_id: str | None = None
    job_posting_id: str | None = None
    contact_id: str | None = None
    outreach_message_id: str | None = None

    def validate(self) -> None:
        if not any(self.as_dict().values()):
            raise ValueError(
                "Artifact linkage requires at least one canonical identifier."
            )

    def as_dict(self) -> dict[str, str]:
        return {
            key: value
            for key, value in {
                "lead_id": self.lead_id,
                "job_posting_id": self.job_posting_id,
                "contact_id": self.contact_id,
                "outreach_message_id": self.outreach_message_id,
            }.items()
            if value
        }


@dataclass(frozen=True)
class ArtifactLocation:
    absolute_path: Path
    relative_path: str

    def as_reference(self) -> str:
        return self.relative_path


@dataclass(frozen=True)
class ArtifactRecord:
    artifact_id: str
    artifact_type: str
    file_path: str
    producer_component: str
    lead_id: str | None
    job_posting_id: str | None
    contact_id: str | None
    outreach_message_id: str | None
    created_at: str


@dataclass(frozen=True)
class PublishedArtifact:
    location: ArtifactLocation
    contract: dict[str, Any]
    record: ArtifactRecord


def artifact_location(paths: ProjectPaths, artifact_path: Path | str) -> ArtifactLocation:
    relative_path = paths.relative_to_root(artifact_path)
    absolute_path = paths.resolve_from_root(relative_path)
    return ArtifactLocation(
        absolute_path=absolute_path,
        relative_path=relative_path.as_posix(),
    )


def build_contract_envelope(
    *,
    producer_component: str,
    result: str,
    linkage: ArtifactLinkage | None = None,
    payload: Mapping[str, Any] | None = None,
    produced_at: str | None = None,
    reason_code: str | None = None,
    message: str | None = None,
) -> dict[str, Any]:
    if not producer_component:
        raise ValueError("producer_component is required for artifact contracts.")
    if not result:
        raise ValueError("result is required for artifact contracts.")
    if bool(reason_code) != bool(message):
        raise ValueError("reason_code and message must be provided together.")
    if result in FAILURE_RESULTS and not (reason_code and message):
        raise ValueError(
            "Blocked, failed, and error artifacts must include reason_code and message."
        )

    contract = {
        "contract_version": CONTRACT_VERSION,
        "produced_at": produced_at or now_utc_iso(),
        "producer_component": producer_component,
        "result": result,
    }
    if linkage is not None:
        contract.update(linkage.as_dict())

    extra_payload = dict(payload or {})
    overlapping_fields = ENVELOPE_FIELDS.intersection(extra_payload)
    if overlapping_fields:
        overlap_list = ", ".join(sorted(overlapping_fields))
        raise ValueError(f"Payload fields overlap with the contract envelope: {overlap_list}")

    contract.update(extra_payload)

    if reason_code and message:
        contract["reason_code"] = reason_code
        contract["message"] = message

    return contract


def write_json_contract(
    artifact_path: Path | str,
    *,
    producer_component: str,
    result: str,
    linkage: ArtifactLinkage | None = None,
    payload: Mapping[str, Any] | None = None,
    produced_at: str | None = None,
    reason_code: str | None = None,
    message: str | None = None,
) -> dict[str, Any]:
    path = Path(artifact_path)
    contract = build_contract_envelope(
        producer_component=producer_component,
        result=result,
        linkage=linkage,
        payload=payload,
        produced_at=produced_at,
        reason_code=reason_code,
        message=message,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
    return contract


def write_yaml_contract(
    artifact_path: Path | str,
    *,
    producer_component: str,
    result: str,
    linkage: ArtifactLinkage | None = None,
    payload: Mapping[str, Any] | None = None,
    produced_at: str | None = None,
    reason_code: str | None = None,
    message: str | None = None,
) -> dict[str, Any]:
    path = Path(artifact_path)
    contract = build_contract_envelope(
        producer_component=producer_component,
        result=result,
        linkage=linkage,
        payload=payload,
        produced_at=produced_at,
        reason_code=reason_code,
        message=message,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(contract, sort_keys=False), encoding="utf-8")
    return contract


def register_artifact_record(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    artifact_type: str,
    artifact_path: Path | str,
    producer_component: str,
    linkage: ArtifactLinkage,
    artifact_id: str | None = None,
    created_at: str | None = None,
) -> ArtifactRecord:
    if not artifact_type:
        raise ValueError("artifact_type is required for artifact registration.")
    if not producer_component:
        raise ValueError("producer_component is required for artifact registration.")

    linkage.validate()
    location = artifact_location(paths, artifact_path)
    if not location.absolute_path.exists():
        raise FileNotFoundError(
            f"Artifact path must exist before registration: {location.absolute_path}"
        )

    timestamp = created_at or now_utc_iso()
    record = ArtifactRecord(
        artifact_id=artifact_id or new_canonical_id("artifact_records"),
        artifact_type=artifact_type,
        file_path=location.relative_path,
        producer_component=producer_component,
        lead_id=linkage.lead_id,
        job_posting_id=linkage.job_posting_id,
        contact_id=linkage.contact_id,
        outreach_message_id=linkage.outreach_message_id,
        created_at=timestamp,
    )

    with connection:
        connection.execute(
            """
            INSERT INTO artifact_records (
              artifact_id, artifact_type, file_path, producer_component,
              lead_id, job_posting_id, contact_id, outreach_message_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.artifact_id,
                record.artifact_type,
                record.file_path,
                record.producer_component,
                record.lead_id,
                record.job_posting_id,
                record.contact_id,
                record.outreach_message_id,
                record.created_at,
            ),
        )

    return record


def publish_json_artifact(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    artifact_type: str,
    artifact_path: Path | str,
    producer_component: str,
    result: str,
    linkage: ArtifactLinkage,
    payload: Mapping[str, Any] | None = None,
    produced_at: str | None = None,
    reason_code: str | None = None,
    message: str | None = None,
    artifact_id: str | None = None,
) -> PublishedArtifact:
    contract = write_json_contract(
        artifact_path,
        producer_component=producer_component,
        result=result,
        linkage=linkage,
        payload=payload,
        produced_at=produced_at,
        reason_code=reason_code,
        message=message,
    )
    record = register_artifact_record(
        connection,
        paths,
        artifact_type=artifact_type,
        artifact_path=artifact_path,
        producer_component=producer_component,
        linkage=linkage,
        artifact_id=artifact_id,
        created_at=contract["produced_at"],
    )
    return PublishedArtifact(
        location=artifact_location(paths, artifact_path),
        contract=contract,
        record=record,
    )


def publish_yaml_artifact(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
    *,
    artifact_type: str,
    artifact_path: Path | str,
    producer_component: str,
    result: str,
    linkage: ArtifactLinkage,
    payload: Mapping[str, Any] | None = None,
    produced_at: str | None = None,
    reason_code: str | None = None,
    message: str | None = None,
    artifact_id: str | None = None,
) -> PublishedArtifact:
    contract = write_yaml_contract(
        artifact_path,
        producer_component=producer_component,
        result=result,
        linkage=linkage,
        payload=payload,
        produced_at=produced_at,
        reason_code=reason_code,
        message=message,
    )
    record = register_artifact_record(
        connection,
        paths,
        artifact_type=artifact_type,
        artifact_path=artifact_path,
        producer_component=producer_component,
        linkage=linkage,
        artifact_id=artifact_id,
        created_at=contract["produced_at"],
    )
    return PublishedArtifact(
        location=artifact_location(paths, artifact_path),
        contract=contract,
        record=record,
    )
