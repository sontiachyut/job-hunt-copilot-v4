from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .delivery_feedback import query_feedback_reuse_candidates
from .paths import ProjectPaths


TRACEABLE_OBJECT_TYPES = frozenset({"job_posting", "contact", "outreach_message"})


def query_review_surfaces(
    connection: sqlite3.Connection,
    *,
    project_root: Path | str,
) -> dict[str, tuple[dict[str, Any], ...]]:
    return {
        "posting_states": query_posting_review_states(connection),
        "contact_states": query_contact_review_states(connection),
        "sent_message_history": query_sent_message_history(connection),
        "outstanding_outreach_review_items": query_outstanding_outreach_review_items(
            connection,
            project_root=project_root,
        ),
        "unresolved_discovery_cases": _fetchall_dicts(
            connection.execute(
                """
                SELECT contact_id, full_name, company_name, contact_status, current_working_email,
                       unresolved_reason, discovery_attempt_id, latest_discovery_outcome,
                       provider_name, provider_verification_status, latest_attempt_email,
                       latest_attempt_at
                FROM unresolved_contacts_review
                ORDER BY latest_attempt_at DESC, contact_id DESC
                """
            )
        ),
        "delivery_feedback_reuse_candidates": query_feedback_reuse_candidates(connection),
        "bounced_email_cases": _fetchall_dicts(
            connection.execute(
                """
                SELECT delivery_feedback_event_id, outreach_message_id, contact_id, job_posting_id,
                       full_name, recipient_email, event_state, event_timestamp, reply_summary
                FROM bounced_email_review
                ORDER BY event_timestamp DESC, delivery_feedback_event_id DESC
                """
            )
        ),
        "pending_expert_review_packets": _fetchall_dicts(
            connection.execute(
                """
                SELECT expert_review_packet_id, pipeline_run_id, job_posting_id, packet_status,
                       packet_path, run_status, current_stage, run_summary, company_name,
                       role_title, incident_ids, incident_summaries, created_at
                FROM expert_review_queue
                ORDER BY created_at DESC, expert_review_packet_id DESC
                """
            )
        ),
        "open_agent_incidents": _fetchall_dicts(
            connection.execute(
                """
                SELECT agent_incident_id, incident_type, severity, status, summary,
                       pipeline_run_id, lead_id, job_posting_id, contact_id,
                       outreach_message_id, created_at, updated_at, run_status,
                       current_stage, company_name, role_title, full_name, recipient_email
                FROM open_agent_incidents_review
                ORDER BY updated_at DESC, created_at DESC, agent_incident_id DESC
                """
            )
        ),
    }


def query_posting_review_states(connection: sqlite3.Connection) -> tuple[dict[str, Any], ...]:
    return _fetchall_dicts(
        connection.execute(
            """
            SELECT
              jp.job_posting_id,
              jp.lead_id,
              jp.company_name,
              jp.role_title,
              jp.posting_status,
              jp.created_at,
              jp.updated_at,
              rtr.resume_tailoring_run_id AS latest_resume_tailoring_run_id,
              rtr.tailoring_status AS latest_tailoring_status,
              rtr.resume_review_status AS latest_resume_review_status,
              rtr.completed_at AS latest_tailoring_completed_at,
              pr.pipeline_run_id AS latest_pipeline_run_id,
              pr.run_status AS latest_pipeline_run_status,
              pr.current_stage AS latest_pipeline_stage,
              pr.review_packet_status AS latest_review_packet_status,
              pr.started_at AS latest_pipeline_started_at,
              COUNT(DISTINCT jpc.job_posting_contact_id) AS linked_contact_count,
              COUNT(DISTINCT CASE
                WHEN jpc.link_level_status IN ('identified', 'shortlisted') THEN jpc.job_posting_contact_id
              END) AS reviewable_contact_count,
              COUNT(DISTINCT CASE
                WHEN om.sent_at IS NOT NULL OR om.message_status = 'sent' THEN om.outreach_message_id
              END) AS sent_message_count,
              MAX(om.sent_at) AS latest_sent_at
            FROM job_postings jp
            LEFT JOIN resume_tailoring_runs rtr
              ON rtr.resume_tailoring_run_id = (
                SELECT rtr2.resume_tailoring_run_id
                FROM resume_tailoring_runs rtr2
                WHERE rtr2.job_posting_id = jp.job_posting_id
                ORDER BY COALESCE(rtr2.completed_at, rtr2.updated_at, rtr2.created_at, rtr2.started_at) DESC,
                         rtr2.resume_tailoring_run_id DESC
                LIMIT 1
              )
            LEFT JOIN pipeline_runs pr
              ON pr.pipeline_run_id = (
                SELECT pr2.pipeline_run_id
                FROM pipeline_runs pr2
                WHERE pr2.job_posting_id = jp.job_posting_id
                ORDER BY COALESCE(pr2.completed_at, pr2.updated_at, pr2.created_at, pr2.started_at) DESC,
                         pr2.pipeline_run_id DESC
                LIMIT 1
              )
            LEFT JOIN job_posting_contacts jpc
              ON jpc.job_posting_id = jp.job_posting_id
            LEFT JOIN outreach_messages om
              ON om.job_posting_id = jp.job_posting_id
            GROUP BY
              jp.job_posting_id,
              jp.lead_id,
              jp.company_name,
              jp.role_title,
              jp.posting_status,
              jp.created_at,
              jp.updated_at,
              rtr.resume_tailoring_run_id,
              rtr.tailoring_status,
              rtr.resume_review_status,
              rtr.completed_at,
              pr.pipeline_run_id,
              pr.run_status,
              pr.current_stage,
              pr.review_packet_status,
              pr.started_at
            ORDER BY COALESCE(MAX(om.sent_at), pr.started_at, jp.updated_at, jp.created_at) DESC,
                     jp.job_posting_id DESC
            """
        )
    )


def query_contact_review_states(connection: sqlite3.Connection) -> tuple[dict[str, Any], ...]:
    return _fetchall_dicts(
        connection.execute(
            """
            SELECT
              c.contact_id,
              c.display_name,
              c.company_name,
              c.contact_status,
              c.current_working_email,
              c.position_title,
              c.linkedin_url,
              c.created_at,
              c.updated_at,
              jpc.job_posting_contact_id,
              jpc.job_posting_id,
              jp.role_title,
              jpc.recipient_type,
              jpc.link_level_status,
              om.outreach_message_id AS latest_outreach_message_id,
              om.message_status AS latest_message_status,
              om.sent_at AS latest_sent_at,
              dfe.delivery_feedback_event_id AS latest_delivery_feedback_event_id,
              dfe.event_state AS latest_delivery_outcome,
              dfe.event_timestamp AS latest_delivery_outcome_at
            FROM contacts c
            LEFT JOIN job_posting_contacts jpc
              ON jpc.job_posting_contact_id = (
                SELECT jpc2.job_posting_contact_id
                FROM job_posting_contacts jpc2
                WHERE jpc2.contact_id = c.contact_id
                ORDER BY COALESCE(jpc2.updated_at, jpc2.created_at) DESC,
                         jpc2.job_posting_contact_id DESC
                LIMIT 1
              )
            LEFT JOIN job_postings jp
              ON jp.job_posting_id = jpc.job_posting_id
            LEFT JOIN outreach_messages om
              ON om.outreach_message_id = (
                SELECT om2.outreach_message_id
                FROM outreach_messages om2
                WHERE om2.contact_id = c.contact_id
                ORDER BY COALESCE(om2.sent_at, om2.updated_at, om2.created_at) DESC,
                         om2.outreach_message_id DESC
                LIMIT 1
              )
            LEFT JOIN delivery_feedback_events dfe
              ON dfe.delivery_feedback_event_id = (
                SELECT dfe2.delivery_feedback_event_id
                FROM delivery_feedback_events dfe2
                WHERE dfe2.outreach_message_id = om.outreach_message_id
                ORDER BY dfe2.event_timestamp DESC,
                         COALESCE(dfe2.created_at, dfe2.event_timestamp) DESC,
                         dfe2.delivery_feedback_event_id DESC
                LIMIT 1
              )
            ORDER BY COALESCE(dfe.event_timestamp, om.sent_at, c.updated_at, c.created_at) DESC,
                     c.contact_id DESC
            """
        )
    )


def query_sent_message_history(
    connection: sqlite3.Connection,
    *,
    job_posting_id: str | None = None,
    contact_id: str | None = None,
    sent_only: bool = True,
) -> tuple[dict[str, Any], ...]:
    filters = []
    params: list[Any] = []
    if sent_only:
        filters.append("(om.sent_at IS NOT NULL OR om.message_status = 'sent')")
    if job_posting_id is not None:
        filters.append("om.job_posting_id = ?")
        params.append(job_posting_id)
    if contact_id is not None:
        filters.append("om.contact_id = ?")
        params.append(contact_id)
    where_clause = ""
    if filters:
        where_clause = "WHERE " + " AND ".join(filters)

    return _fetchall_dicts(
        connection.execute(
            f"""
            SELECT
              om.outreach_message_id,
              om.contact_id,
              c.display_name,
              om.job_posting_id,
              jp.company_name,
              jp.role_title,
              om.job_posting_contact_id,
              om.outreach_mode,
              om.recipient_email,
              om.message_status,
              om.subject,
              om.body_text,
              om.body_html,
              om.thread_id,
              om.delivery_tracking_id,
              om.sent_at,
              om.created_at,
              om.updated_at,
              dfe.delivery_feedback_event_id AS latest_delivery_feedback_event_id,
              dfe.event_state AS latest_delivery_outcome,
              dfe.event_timestamp AS latest_delivery_outcome_at,
              dfe.reply_summary AS latest_reply_summary,
              send_result.file_path AS send_result_artifact_path,
              delivery_outcome.file_path AS latest_delivery_outcome_artifact_path,
              GROUP_CONCAT(DISTINCT ai.agent_incident_id) AS linked_incident_ids,
              GROUP_CONCAT(DISTINCT erp.expert_review_packet_id) AS linked_review_packet_ids,
              GROUP_CONCAT(DISTINCT erp.packet_path) AS linked_review_packet_paths
            FROM outreach_messages om
            LEFT JOIN contacts c
              ON c.contact_id = om.contact_id
            LEFT JOIN job_postings jp
              ON jp.job_posting_id = om.job_posting_id
            LEFT JOIN delivery_feedback_events dfe
              ON dfe.delivery_feedback_event_id = (
                SELECT dfe2.delivery_feedback_event_id
                FROM delivery_feedback_events dfe2
                WHERE dfe2.outreach_message_id = om.outreach_message_id
                ORDER BY dfe2.event_timestamp DESC,
                         COALESCE(dfe2.created_at, dfe2.event_timestamp) DESC,
                         dfe2.delivery_feedback_event_id DESC
                LIMIT 1
              )
            LEFT JOIN artifact_records send_result
              ON send_result.artifact_id = (
                SELECT ar1.artifact_id
                FROM artifact_records ar1
                WHERE ar1.outreach_message_id = om.outreach_message_id
                  AND ar1.artifact_type = 'send_result'
                ORDER BY ar1.created_at DESC, ar1.artifact_id DESC
                LIMIT 1
              )
            LEFT JOIN artifact_records delivery_outcome
              ON delivery_outcome.artifact_id = (
                SELECT ar2.artifact_id
                FROM artifact_records ar2
                WHERE ar2.outreach_message_id = om.outreach_message_id
                  AND ar2.artifact_type = 'delivery_outcome'
                ORDER BY ar2.created_at DESC, ar2.artifact_id DESC
                LIMIT 1
              )
            LEFT JOIN agent_incidents ai
              ON ai.outreach_message_id = om.outreach_message_id
            LEFT JOIN expert_review_packets erp
              ON erp.pipeline_run_id = ai.pipeline_run_id
            {where_clause}
            GROUP BY
              om.outreach_message_id,
              om.contact_id,
              c.display_name,
              om.job_posting_id,
              jp.company_name,
              jp.role_title,
              om.job_posting_contact_id,
              om.outreach_mode,
              om.recipient_email,
              om.message_status,
              om.subject,
              om.body_text,
              om.body_html,
              om.thread_id,
              om.delivery_tracking_id,
              om.sent_at,
              om.created_at,
              om.updated_at,
              dfe.delivery_feedback_event_id,
              dfe.event_state,
              dfe.event_timestamp,
              dfe.reply_summary,
              send_result.file_path,
              delivery_outcome.file_path
            ORDER BY COALESCE(om.sent_at, om.updated_at, om.created_at) DESC,
                     om.outreach_message_id DESC
            """,
            tuple(params),
        )
    )


def query_outstanding_outreach_review_items(
    connection: sqlite3.Connection,
    *,
    project_root: Path | str,
) -> tuple[dict[str, Any], ...]:
    paths = ProjectPaths.from_root(project_root)

    blocked_or_failed = _fetchall_dicts(
        connection.execute(
            """
            SELECT
              om.outreach_message_id,
              om.contact_id,
              om.job_posting_id,
              om.job_posting_contact_id,
              om.message_status,
              om.recipient_email,
              om.subject,
              om.created_at,
              om.updated_at,
              c.display_name,
              jp.company_name,
              jp.role_title,
              ar.file_path AS send_result_artifact_path
            FROM outreach_messages om
            LEFT JOIN contacts c
              ON c.contact_id = om.contact_id
            LEFT JOIN job_postings jp
              ON jp.job_posting_id = om.job_posting_id
            LEFT JOIN artifact_records ar
              ON ar.artifact_id = (
                SELECT ar2.artifact_id
                FROM artifact_records ar2
                WHERE ar2.outreach_message_id = om.outreach_message_id
                  AND ar2.artifact_type = 'send_result'
                ORDER BY ar2.created_at DESC, ar2.artifact_id DESC
                LIMIT 1
              )
            WHERE om.message_status IN ('blocked', 'failed')
            ORDER BY COALESCE(om.updated_at, om.created_at) DESC, om.outreach_message_id DESC
            """
        )
    )

    items: list[dict[str, Any]] = []
    for row in blocked_or_failed:
        artifact_payload = _read_json_artifact(paths, row.get("send_result_artifact_path"))
        items.append(
            {
                "item_type": f"{row['message_status']}_message",
                "review_state": row["message_status"],
                "outreach_message_id": row["outreach_message_id"],
                "contact_id": row["contact_id"],
                "job_posting_id": row["job_posting_id"],
                "job_posting_contact_id": row["job_posting_contact_id"],
                "display_name": row["display_name"],
                "company_name": row["company_name"],
                "role_title": row["role_title"],
                "recipient_email": row["recipient_email"],
                "subject": row["subject"],
                "reason_code": artifact_payload.get("reason_code"),
                "message": artifact_payload.get("message"),
                "send_result_artifact_path": row["send_result_artifact_path"],
                "updated_at": row["updated_at"],
                "created_at": row["created_at"],
            }
        )

    repeat_cases = _fetchall_dicts(
        connection.execute(
            """
            WITH outreach_history AS (
              SELECT contact_id,
                     COUNT(*) AS prior_outreach_count,
                     MAX(COALESCE(sent_at, updated_at, created_at)) AS latest_outreach_at
              FROM outreach_messages
              WHERE sent_at IS NOT NULL
                 OR message_status = 'sent'
              GROUP BY contact_id
            )
            SELECT
              jpc.job_posting_contact_id,
              jpc.job_posting_id,
              jpc.contact_id,
              jpc.recipient_type,
              jpc.link_level_status,
              jpc.created_at,
              c.display_name,
              c.contact_status,
              c.current_working_email,
              jp.company_name,
              jp.role_title,
              oh.prior_outreach_count,
              oh.latest_outreach_at
            FROM job_posting_contacts jpc
            JOIN contacts c
              ON c.contact_id = jpc.contact_id
            JOIN job_postings jp
              ON jp.job_posting_id = jpc.job_posting_id
            JOIN outreach_history oh
              ON oh.contact_id = jpc.contact_id
            WHERE NOT EXISTS (
              SELECT 1
              FROM outreach_messages om
              WHERE om.job_posting_id = jpc.job_posting_id
                AND om.contact_id = jpc.contact_id
            )
            ORDER BY oh.latest_outreach_at DESC, jpc.created_at DESC, jpc.job_posting_contact_id DESC
            """
        )
    )
    for row in repeat_cases:
        items.append(
            {
                "item_type": "repeat_outreach_contact",
                "review_state": "repeat_outreach_review_required",
                "outreach_message_id": None,
                "contact_id": row["contact_id"],
                "job_posting_id": row["job_posting_id"],
                "job_posting_contact_id": row["job_posting_contact_id"],
                "display_name": row["display_name"],
                "company_name": row["company_name"],
                "role_title": row["role_title"],
                "recipient_email": row["current_working_email"],
                "subject": None,
                "reason_code": "repeat_outreach_review_required",
                "message": "Prior outreach history exists for this contact, so automatic repeat sending is blocked pending review.",
                "send_result_artifact_path": None,
                "prior_outreach_count": row["prior_outreach_count"],
                "recipient_type": row["recipient_type"],
                "link_level_status": row["link_level_status"],
                "contact_status": row["contact_status"],
                "updated_at": row["latest_outreach_at"],
                "created_at": row["created_at"],
            }
        )

    items.sort(
        key=lambda item: (
            str(item.get("updated_at") or item.get("created_at") or ""),
            str(item.get("outreach_message_id") or item.get("job_posting_contact_id") or ""),
        ),
        reverse=True,
    )
    return tuple(items)


def query_override_history(
    connection: sqlite3.Connection,
    *,
    object_type: str | None = None,
    object_id: str | None = None,
) -> tuple[dict[str, Any], ...]:
    filters = []
    params: list[Any] = []
    if object_type is not None:
        filters.append("oe.object_type = ?")
        params.append(object_type)
    if object_id is not None:
        filters.append("oe.object_id = ?")
        params.append(object_id)
    where_clause = ""
    if filters:
        where_clause = "WHERE " + " AND ".join(filters)

    return _fetchall_dicts(
        connection.execute(
            f"""
            SELECT
              oe.override_event_id,
              oe.object_type,
              oe.object_id,
              oe.component_stage,
              oe.previous_value,
              oe.new_value,
              oe.override_reason,
              oe.override_timestamp,
              oe.override_by,
              oe.lead_id,
              oe.job_posting_id,
              oe.contact_id,
              jp.company_name,
              jp.role_title,
              c.display_name
            FROM override_events oe
            LEFT JOIN job_postings jp
              ON jp.job_posting_id = oe.job_posting_id
            LEFT JOIN contacts c
              ON c.contact_id = oe.contact_id
            {where_clause}
            ORDER BY oe.override_timestamp DESC, oe.override_event_id DESC
            """,
            tuple(params),
        )
    )


def query_object_traceability(
    connection: sqlite3.Connection,
    *,
    project_root: Path | str,
    object_type: str,
    object_id: str,
) -> dict[str, Any]:
    if object_type not in TRACEABLE_OBJECT_TYPES:
        raise ValueError(f"Unsupported traceability object_type: {object_type!r}")

    snapshot = _load_traceability_snapshot(connection, object_type=object_type, object_id=object_id)
    artifact_key = {
        "job_posting": "job_posting_id",
        "contact": "contact_id",
        "outreach_message": "outreach_message_id",
    }[object_type]
    artifacts = _fetchall_dicts(
        connection.execute(
            f"""
            SELECT artifact_id, artifact_type, file_path, producer_component, created_at
            FROM artifact_records
            WHERE {artifact_key} = ?
            ORDER BY created_at DESC, artifact_id DESC
            """,
            (object_id,),
        )
    )
    transitions = _fetchall_dicts(
        connection.execute(
            """
            SELECT state_transition_event_id, stage, previous_state, new_state,
                   transition_timestamp, transition_reason, caused_by,
                   lead_id, job_posting_id, contact_id
            FROM state_transition_events
            WHERE object_type = ?
              AND object_id = ?
            ORDER BY transition_timestamp DESC, state_transition_event_id DESC
            """,
            (object_type, object_id),
        )
    )

    if object_type == "job_posting":
        downstream_records = {
            "posting_contacts": _fetchall_dicts(
                connection.execute(
                    """
                    SELECT jpc.job_posting_contact_id, jpc.contact_id, c.display_name,
                           jpc.recipient_type, jpc.link_level_status, jpc.created_at, jpc.updated_at
                    FROM job_posting_contacts jpc
                    JOIN contacts c
                      ON c.contact_id = jpc.contact_id
                    WHERE jpc.job_posting_id = ?
                    ORDER BY jpc.created_at ASC, jpc.job_posting_contact_id ASC
                    """,
                    (object_id,),
                )
            ),
            "outreach_messages": query_sent_message_history(
                connection,
                job_posting_id=object_id,
                sent_only=False,
            ),
            "pipeline_runs": _fetchall_dicts(
                connection.execute(
                    """
                    SELECT pipeline_run_id, run_scope_type, run_status, current_stage,
                           review_packet_status, run_summary, started_at, completed_at,
                           updated_at
                    FROM pipeline_runs
                    WHERE job_posting_id = ?
                    ORDER BY COALESCE(completed_at, updated_at, started_at, created_at) DESC,
                             pipeline_run_id DESC
                    """,
                    (object_id,),
                )
            ),
            "expert_review_packets": _fetchall_dicts(
                connection.execute(
                    """
                    SELECT expert_review_packet_id, pipeline_run_id, packet_status,
                           packet_path, reviewed_at, summary_excerpt, created_at
                    FROM expert_review_packets
                    WHERE job_posting_id = ?
                    ORDER BY COALESCE(reviewed_at, created_at) DESC, expert_review_packet_id DESC
                    """,
                    (object_id,),
                )
            ),
            "agent_incidents": _fetchall_dicts(
                connection.execute(
                    """
                    SELECT agent_incident_id, incident_type, severity, status, summary,
                           pipeline_run_id, contact_id, outreach_message_id,
                           resolved_at, escalation_reason, created_at, updated_at
                    FROM agent_incidents
                    WHERE job_posting_id = ?
                    ORDER BY updated_at DESC, created_at DESC, agent_incident_id DESC
                    """,
                    (object_id,),
                )
            ),
        }
    elif object_type == "contact":
        downstream_records = {
            "job_posting_links": _fetchall_dicts(
                connection.execute(
                    """
                    SELECT jpc.job_posting_contact_id, jpc.job_posting_id, jp.company_name,
                           jp.role_title, jpc.recipient_type, jpc.link_level_status,
                           jpc.created_at, jpc.updated_at
                    FROM job_posting_contacts jpc
                    JOIN job_postings jp
                      ON jp.job_posting_id = jpc.job_posting_id
                    WHERE jpc.contact_id = ?
                    ORDER BY jpc.created_at ASC, jpc.job_posting_contact_id ASC
                    """,
                    (object_id,),
                )
            ),
            "discovery_attempts": _fetchall_dicts(
                connection.execute(
                    """
                    SELECT discovery_attempt_id, job_posting_id, outcome, provider_name,
                           email, provider_verification_status, bounced, created_at
                    FROM discovery_attempts
                    WHERE contact_id = ?
                    ORDER BY created_at DESC, discovery_attempt_id DESC
                    """,
                    (object_id,),
                )
            ),
            "outreach_messages": query_sent_message_history(
                connection,
                contact_id=object_id,
                sent_only=False,
            ),
            "agent_incidents": _fetchall_dicts(
                connection.execute(
                    """
                    SELECT agent_incident_id, incident_type, severity, status, summary,
                           pipeline_run_id, job_posting_id, outreach_message_id,
                           resolved_at, escalation_reason, created_at, updated_at
                    FROM agent_incidents
                    WHERE contact_id = ?
                    ORDER BY updated_at DESC, created_at DESC, agent_incident_id DESC
                    """,
                    (object_id,),
                )
            ),
        }
    else:
        downstream_records = {
            "delivery_feedback_events": _fetchall_dicts(
                connection.execute(
                    """
                    SELECT delivery_feedback_event_id, event_state, event_timestamp,
                           reply_summary, raw_reply_excerpt, created_at
                    FROM delivery_feedback_events
                    WHERE outreach_message_id = ?
                    ORDER BY event_timestamp DESC,
                             COALESCE(created_at, event_timestamp) DESC,
                             delivery_feedback_event_id DESC
                    """,
                    (object_id,),
                )
            ),
            "agent_incidents": _fetchall_dicts(
                connection.execute(
                    """
                    SELECT agent_incident_id, incident_type, severity, status, summary,
                           pipeline_run_id, job_posting_id, contact_id, resolved_at,
                           escalation_reason, created_at, updated_at
                    FROM agent_incidents
                    WHERE outreach_message_id = ?
                    ORDER BY updated_at DESC, created_at DESC, agent_incident_id DESC
                    """,
                    (object_id,),
                )
            ),
            "expert_review_packets": _fetchall_dicts(
                connection.execute(
                    """
                    SELECT DISTINCT erp.expert_review_packet_id, erp.pipeline_run_id,
                           erp.packet_status, erp.packet_path, erp.reviewed_at,
                           erp.summary_excerpt, erp.created_at
                    FROM agent_incidents ai
                    JOIN expert_review_packets erp
                      ON erp.pipeline_run_id = ai.pipeline_run_id
                    WHERE ai.outreach_message_id = ?
                    ORDER BY COALESCE(erp.reviewed_at, erp.created_at) DESC,
                             erp.expert_review_packet_id DESC
                    """,
                    (object_id,),
                )
            ),
        }

    return {
        "object_type": object_type,
        "object_id": object_id,
        "snapshot": snapshot,
        "artifacts": artifacts,
        "state_transitions": transitions,
        "downstream_records": downstream_records,
    }


def _load_traceability_snapshot(
    connection: sqlite3.Connection,
    *,
    object_type: str,
    object_id: str,
) -> dict[str, Any]:
    if object_type == "job_posting":
        snapshot = _fetchone_dict(
            connection.execute(
                """
                SELECT job_posting_id, lead_id, posting_identity_key, company_name, role_title,
                       posting_status, location, employment_type, posted_at, jd_artifact_path,
                       archived_at, created_at, updated_at
                FROM job_postings
                WHERE job_posting_id = ?
                """,
                (object_id,),
            )
        )
    elif object_type == "contact":
        snapshot = _fetchone_dict(
            connection.execute(
                """
                SELECT contact_id, identity_key, display_name, company_name, origin_component,
                       contact_status, full_name, first_name, last_name, linkedin_url,
                       position_title, location, discovery_summary, current_working_email,
                       identity_source, provider_name, provider_person_id, name_quality,
                       created_at, updated_at
                FROM contacts
                WHERE contact_id = ?
                """,
                (object_id,),
            )
        )
    else:
        snapshot = _fetchone_dict(
            connection.execute(
                """
                SELECT om.outreach_message_id, om.contact_id, om.job_posting_id,
                       om.job_posting_contact_id, om.outreach_mode, om.recipient_email,
                       om.message_status, om.subject, om.body_text, om.body_html,
                       om.thread_id, om.delivery_tracking_id, om.sent_at,
                       om.created_at, om.updated_at,
                       dfe.delivery_feedback_event_id AS latest_delivery_feedback_event_id,
                       dfe.event_state AS latest_delivery_outcome,
                       dfe.event_timestamp AS latest_delivery_outcome_at
                FROM outreach_messages om
                LEFT JOIN delivery_feedback_events dfe
                  ON dfe.delivery_feedback_event_id = (
                    SELECT dfe2.delivery_feedback_event_id
                    FROM delivery_feedback_events dfe2
                    WHERE dfe2.outreach_message_id = om.outreach_message_id
                    ORDER BY dfe2.event_timestamp DESC,
                             COALESCE(dfe2.created_at, dfe2.event_timestamp) DESC,
                             dfe2.delivery_feedback_event_id DESC
                    LIMIT 1
                  )
                WHERE om.outreach_message_id = ?
                """,
                (object_id,),
            )
        )
    if snapshot is None:
        raise ValueError(f"{object_type} `{object_id}` was not found in canonical state.")
    return snapshot


def _fetchall_dicts(cursor: sqlite3.Cursor) -> tuple[dict[str, Any], ...]:
    columns = [description[0] for description in cursor.description or ()]
    return tuple(dict(zip(columns, row)) for row in cursor.fetchall())


def _fetchone_dict(cursor: sqlite3.Cursor) -> dict[str, Any] | None:
    columns = [description[0] for description in cursor.description or ()]
    row = cursor.fetchone()
    if row is None:
        return None
    return dict(zip(columns, row))


def _read_json_artifact(
    paths: ProjectPaths,
    relative_path: object,
) -> dict[str, Any]:
    if not relative_path:
        return {}
    path = paths.resolve_from_root(str(relative_path))
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
