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

from .outreach import (
    SendAttemptOutcome,
    _job_hunt_copilot_pitch_lines,
    _render_markdown_email_html,
)
from .paths import ProjectPaths, workspace_slug


AI_OUTREACH_POC_COMPONENT = "ai_outreach_poc"
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
class AiOutreachSenderIdentity:
    name: str
    email: str | None
    phone: str | None
    linkedin_url: str | None
    github_url: str | None


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

    draft_payload = json.loads(output_path.read_text(encoding="utf-8"))
    subject = _normalize_non_empty_text(draft_payload.get("subject"))
    body_markdown = _normalize_non_empty_text(draft_payload.get("body_markdown"))
    if subject is None or body_markdown is None:
        raise AiOutreachPocError(
            f"Draft payload is missing required fields. See {output_path}."
        )
    final_subject = f"{request.subject_prefix or ''}{subject}".strip()
    final_body = _compose_full_email_body(
        contact_name=request.contact_name or "there",
        fit_section_markdown=body_markdown,
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


def _truncate_for_prompt(text: str, *, max_chars: int) -> str:
    stripped = text.strip()
    if len(stripped) <= max_chars:
        return stripped
    return stripped[: max_chars - 16].rstrip() + "\n[truncated]"


def _draft_output_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "subject": {"type": "string"},
            "body_markdown": {"type": "string"},
        },
        "required": ["subject", "body_markdown"],
        "additionalProperties": False,
    }


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
