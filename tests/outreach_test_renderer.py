from __future__ import annotations

from job_hunt_copilot.outreach import RenderedDraft, _render_markdown_email_html


def _first_name(display_name: str) -> str:
    normalized = str(display_name).strip()
    if not normalized:
        return "there"
    return normalized.split()[0]


def _role_targeted_why_line(context) -> str:  # type: ignore[no-untyped-def]
    title = (context.position_title or "").strip()
    if context.recipient_type == "recruiter":
        if title:
            return (
                f"Given your role as {title}, I thought you might have useful perspective "
                "on the hiring context for this opening."
            )
        return "I thought you might have useful perspective on the hiring context for this opening."
    if context.recipient_type == "hiring_manager":
        if title:
            return (
                f"Given your role as {title}, I thought you might be a good person to reach out to "
                "for some perspective on this opening."
            )
        return "I thought you might be a good person to reach out to for some perspective on this opening."
    if context.recipient_type == "alumni":
        return (
            "I'm reaching out to you specifically because you seemed like the right fellow Sun Devil "
            "to ask for a grounded perspective on this work."
        )
    if title:
        return (
            f"Given your role as {title}, I thought you might have useful perspective on "
            "the day-to-day work this role touches."
        )
    return "I thought you might have useful perspective on the day-to-day work this role touches."


def _proof_point_sentence(proof_point: str) -> str:
    cleaned = proof_point.strip().rstrip(".")
    return f"In one recent role, {cleaned}."


def _general_learning_work_signal(context) -> str | None:  # type: ignore[no-untyped-def]
    recipient_profile = context.recipient_profile
    if isinstance(recipient_profile, dict):
        work_signals = recipient_profile.get("work_signals")
        if isinstance(work_signals, list):
            for signal in work_signals:
                normalized = str(signal).strip()
                if normalized:
                    return normalized
        top_card = recipient_profile.get("top_card")
        if isinstance(top_card, dict):
            for key in ("headline", "current_title"):
                normalized = str(top_card.get(key) or "").strip()
                if normalized:
                    return normalized
    return None


def _signature_lines(sender) -> list[str]:  # type: ignore[no-untyped-def]
    lines: list[str] = []
    if sender.linkedin_url:
        lines.append(sender.linkedin_url)
    if sender.github_url:
        lines.append(sender.github_url)
    if sender.phone:
        lines.append(sender.phone)
    if sender.email:
        lines.append(sender.email)
    return lines


class StableTestOutreachRenderer:
    def render_role_targeted(self, context):  # type: ignore[no-untyped-def]
        proof_point = context.proof_point or (
            "the distributed systems work I have done across reliability, performance, and production delivery"
        )
        opener_paragraph = (
            f"I'm reaching out about the {context.role_title} role at {context.company_name} because I was "
            f"interested in the role's focus on {context.opener_decision.technical_focus}. "
            f"{context.opener_decision.overlap_sentence}"
        )
        background_paragraph = (
            f"{_role_targeted_why_line(context)} {_proof_point_sentence(proof_point)}"
        )
        ask_paragraph = (
            "If it would be useful, I would welcome a brief 10-minute conversation "
            "to better understand the team and whether my background could be relevant."
        )
        body_lines = [
            f"Hi {_first_name(context.display_name)},",
            "",
            opener_paragraph,
            "",
            background_paragraph,
            "",
            ask_paragraph,
            "",
            "Best,",
            context.sender.name,
            *_signature_lines(context.sender),
        ]
        body_markdown = "\n".join(body_lines).strip() + "\n"
        return RenderedDraft(
            subject=f"Interest in the {context.role_title} role at {context.company_name}",
            body_markdown=body_markdown,
            body_html=_render_markdown_email_html(body_markdown),
            include_forwardable_snippet=False,
            opener_decision=context.opener_decision,
            debug_payload={"draft_origin_kind": "test_stub"},
        )

    def render_general_learning(self, context):  # type: ignore[no-untyped-def]
        work_signal = _general_learning_work_signal(context)
        role_hint = context.position_title or "your work"
        subject = f"Learning from your career path"
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
            debug_payload={"draft_origin_kind": "test_stub"},
        )
