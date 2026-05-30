from __future__ import annotations

import json
import subprocess
from pathlib import Path

from job_hunt_copilot.ai_outreach_poc import (
    AiOutreachPocRequest,
    build_ai_outreach_codex_exec_command,
    generate_ai_outreach_draft,
    send_ai_outreach_draft,
)


def _write_sender_profile(project_root: Path) -> None:
    profile_path = project_root / "assets" / "resume-tailoring" / "profile.md"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(
        "\n".join(
            [
                "# Achyutaram Sonti — Master Profile",
                "",
                "## Personal",
                "",
                "- **Name:** Achyutaram Sonti",
                "- **Email:** asonti1@asu.edu",
                "- **Phone:** 602-768-6071",
                "- **LinkedIn:** https://www.linkedin.com/in/asonti/",
                "- **GitHub:** https://github.com/sontiachyut",
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_build_ai_outreach_codex_exec_command_uses_schema_and_output_file(tmp_path: Path):
    schema_path = tmp_path / "schema.json"
    output_path = tmp_path / "output.json"

    command = build_ai_outreach_codex_exec_command(
        codex_bin="/opt/homebrew/bin/codex",
        project_root=tmp_path,
        schema_path=schema_path,
        output_path=output_path,
        model="gpt-5.4",
    )

    assert command == [
        "/opt/homebrew/bin/codex",
        "exec",
        "--model",
        "gpt-5.4",
        "--ephemeral",
        "--sandbox",
        "workspace-write",
        "-C",
        str(tmp_path),
        "--output-schema",
        str(schema_path),
        "-o",
        str(output_path),
        "-",
    ]


def test_generate_ai_outreach_draft_materializes_prompt_and_email(monkeypatch, tmp_path: Path):
    _write_sender_profile(tmp_path)
    jd_path = tmp_path / "jd.md"
    resume_path = tmp_path / "resume.md"
    jd_path.write_text("Cloudflare is hiring a Software Engineer, Realtime.", encoding="utf-8")
    resume_path.write_text(
        "Built distributed systems in Python and Go with monitoring and high-throughput data flows.",
        encoding="utf-8",
    )

    def fake_run(command, **kwargs):  # type: ignore[no-untyped-def]
        output_path = Path(command[command.index("-o") + 1])
        output_path.write_text(
            json.dumps(
                {
                    "subject": "Software Engineer, Realtime",
                    "body_markdown": "I'm reaching out about the Software Engineer, Realtime role at Cloudflare because I was interested in the role's focus on distributed systems, realtime data flows, and production reliability. That lines up well with the kind of backend and platform work I have done and want to keep building toward.\n\nGiven your role as Senior Engineer, I thought you might have useful perspective on the day-to-day work this role touches. In one recent role, I built high-throughput backend services and monitoring-heavy production workflows, and I've attached my resume for context.",
                }
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, stdout='{"ok":true}', stderr="codex stderr")

    monkeypatch.setattr("job_hunt_copilot.ai_outreach_poc.shutil.which", lambda name: f"/opt/homebrew/bin/{name}")
    monkeypatch.setattr("job_hunt_copilot.ai_outreach_poc.subprocess.run", fake_run)

    result = generate_ai_outreach_draft(
        AiOutreachPocRequest(
            jd_path=str(jd_path),
            resume_path=str(resume_path),
            company_name="Cloudflare",
            role_title="Software Engineer, Realtime",
            contact_name="Eduardo",
        ),
        project_root=tmp_path,
    )

    assert result.subject == "[AI POC] Software Engineer, Realtime"
    assert result.send_to_email == "asonti1@asu.edu"
    assert Path(result.prompt_path).exists()
    assert Path(result.schema_path).exists()
    assert Path(result.draft_json_path).exists()
    assert Path(result.email_markdown_path).exists()
    email_text = Path(result.email_markdown_path).read_text(encoding="utf-8")
    assert email_text.startswith("Hi Eduardo,")
    assert "I built Job Hunt Copilot" in email_text
    assert "Best," in email_text
    assert "Achyutaram Sonti" in email_text
    assert "asonti1@asu.edu" in email_text
    assert result.body_html is not None
    assert len(result.attachment_paths) == 2
    assert str(jd_path) in result.attachment_paths
    assert str(resume_path) in result.attachment_paths


def test_send_ai_outreach_draft_uses_requested_recipient_and_attachments(tmp_path: Path):
    run_dir = tmp_path / "ops" / "ai-outreach-poc" / "run-1"
    run_dir.mkdir(parents=True, exist_ok=True)
    resume_path = tmp_path / "resume.pdf"
    jd_path = tmp_path / "jd.md"
    resume_path.write_bytes(b"%PDF-1.4\n")
    jd_path.write_text("jd", encoding="utf-8")
    draft = generate_fake_draft(run_dir=run_dir, resume_path=resume_path, jd_path=jd_path)

    class RecordingSender:
        def __init__(self) -> None:
            self.messages = []

        def send(self, message):  # type: ignore[no-untyped-def]
            self.messages.append(message)
            from job_hunt_copilot.outreach import SendAttemptOutcome

            return SendAttemptOutcome(
                outcome="sent",
                thread_id="thread-1",
                delivery_tracking_id="delivery-1",
                sent_at="2026-05-28T20:00:00Z",
            )

    sender = RecordingSender()
    result = send_ai_outreach_draft(
        draft,
        project_root=tmp_path,
        sender=sender,
    )

    assert result.outcome == "sent"
    assert sender.messages[0].recipient_email == "me@example.com"
    assert tuple(sender.messages[0].attachment_paths) == (str(resume_path), str(jd_path))
    assert Path(result.send_result_path).exists()


def generate_fake_draft(*, run_dir: Path, resume_path: Path, jd_path: Path):  # type: ignore[no-untyped-def]
    from job_hunt_copilot.ai_outreach_poc import AiOutreachDraftResult

    return AiOutreachDraftResult(
        run_id="run-1",
        run_dir=str(run_dir),
        company_name="Acme",
        role_title="Platform Engineer",
        contact_name="Taylor",
        send_to_email="me@example.com",
        subject="[AI POC] Platform Engineer",
        body_text="Hi Taylor,\n\nBody.\n\nBest,\nAchyutaram\n",
        body_html="<html><body><p>Body</p></body></html>\n",
        prompt_path=str(run_dir / "prompt.md"),
        schema_path=str(run_dir / "schema.json"),
        request_path=str(run_dir / "request.json"),
        draft_json_path=str(run_dir / "draft.json"),
        email_markdown_path=str(run_dir / "email.md"),
        codex_stdout_path=str(run_dir / "codex.stdout.txt"),
        codex_stderr_path=str(run_dir / "codex.stderr.txt"),
        jd_text_path=str(run_dir / "jd.txt"),
        resume_text_path=str(run_dir / "resume.txt"),
        attachment_paths=(str(resume_path), str(jd_path)),
    )
