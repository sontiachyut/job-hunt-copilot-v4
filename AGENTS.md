# Project Agent Notes

## Bug-Fix Workflow

Use this workflow for bug fixes and small repairs in this repo:

1. Update the relevant requirement first in `prd/spec.md` when the bug exposes a spec ambiguity.
2. Resolve spec ambiguity one question at a time.
3. Create a GitHub issue for the bug before implementing the fix.
4. Implement the fix with regression coverage.
5. Document the fix back on the GitHub issue.
6. Commit and push the completed work to GitHub after the work is done.

## Decision Boundary

- For small bug fixes, small patches, and spec-ambiguity cleanup that does not materially change system direction, Codex may make the clarifying spec update and proceed.
- For changes that alter the system's intended behavior, operating model, or product direction, stop and hand the decision back to the owner before implementing.

## Spec-Ambiguity Method

When clearing ambiguity in `prd/spec.md`, use this method:

1. Ask one ambiguity question at a time.
2. Answer that one question directly.
3. Move to the next ambiguity only after the previous one has been resolved.

Do not collapse multiple unresolved ambiguities into one blended spec change when they can be resolved sequentially.

## Persistence

- Keep this file current when the owner defines new repo-specific operating rules.
- When possible, mirror the bug context and fix summary on the corresponding GitHub issue so the workflow history also exists outside the local checkout.

## Follow-Up Email Workflow

When the owner asks to draft or send follow-up emails for unreplied outreach, use the current unreplied follow-up template in `assets/outreach/cold-outreach-guide.md`.

Default workflow:

1. Query `outreach_messages` for the requested send date or date range.
2. Exclude messages with `delivery_feedback_events.event_state IN ('bounced', 'replied')`.
3. Exclude contacts that already have a later sent follow-up or later sent outreach after the original message.
4. Load the original sent message plus the linked JD artifact from `job_postings.jd_artifact_path`.
5. Draft follow-ups using the warmer mutual-fit template, not the older terse JD-theme template.
6. Save drafts under `ops/followups/<run-id>/` with a combined `drafts.md` and `summary.json`.
7. Review the batch wording before showing drafts so it does not collapse into the same generic follow-up language for unrelated roles.
8. Show the owner one or more sample drafts for review before sending.
9. Only send after the owner explicitly approves sending.
10. Send follow-ups as replies in the original Gmail threads using the original `thread_id` and RFC `Message-ID` when available.
11. Insert each sent follow-up into `outreach_messages` with `outreach_mode = 'role_targeted_followup'`, `message_status = 'sent'`, final subject/body, Gmail thread/delivery IDs, and `sent_at`.
12. Write a sent batch summary under `ops/followups/<send-run-id>/summary.md`.

Current unreplied follow-up template shape:

```text
Hi {first_name},

I wanted to briefly follow up on my earlier note about the {role_title} role at {company_name}.

I reached out because I believe the role could be a strong mutual fit. I know you are busy, so I appreciate you taking the time to read this.

If you are open to it, I would be grateful for a brief 15-minute conversation to hear your perspective on the role, the team, or what tends to matter in the process.

If this is not relevant or not the right time, I completely understand and will not keep following up.

Best,
Achyutaram Sonti
```

Keep the follow-up brief and role-specific. Do not insert a separate `background_fit_areas` phrase, do not repeat the full proof point from the first email, and do not add the full LinkedIn / phone / email signature block in follow-ups.
