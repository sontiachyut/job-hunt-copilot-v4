# Follow-Up Email Feature Notes

Working notes for the follow-up email feature. These answers are not yet the formal product spec; merge the accepted decisions into `prd/spec.md` when the design is settled.

## Q1. After How Many Days Should We Follow Up?

Recommended default: send one follow-up after **4 calendar days** from the original sent email.

Rationale:
- Less than 3 calendar days can feel too soon for recruiters or engineers who are busy.
- 4 calendar days keeps the follow-up timely without feeling immediate.
- Waiting much longer than 7-10 calendar days makes the original note colder and easier to ignore.

Default rule:
- First follow-up becomes eligible after 4 calendar days.
- Start the 4-calendar-day timer from the original outreach message's `sent_at`.
- Calculate calendar days in the owner's local timezone, currently `America/Phoenix`, so behavior lines up with Gmail's displayed sent times.
- Do not exclude weekends, holidays, or other non-business days.
- Send at most one follow-up per original outreach thread unless the owner explicitly approves a different sequence.
- Enforce one follow-up plan per original email per follow-up sequence, using uniqueness on `original_outreach_message_id` plus `followup_sequence`.
- Do not impose a maximum original-email age cutoff; older eligible sent emails may still receive the first follow-up if all gates pass.

Hard stop:
- Never follow up if the original email bounced.
- Never follow up if the recipient has replied.
- Before drafting and again before sending, the follow-up worker must check the Gmail thread directly for an inbound reply after the original sent time.
- The immediately-before-send thread check is mandatory even if the earlier pre-draft check passed. If a reply, bounce, or later outbound follow-up appears while the candidate is waiting for drafting, review, retry, or pacing, suppress the send.
- If the thread check fails for a clearly temporary reason, such as provider timeout, network failure, or auth refresh interruption, retry later using the transient retry policy. If the failure is structural, such as missing original thread ID or impossible same-thread send metadata, block or hold for review immediately.

## Q2. What Follow-Up Template Should Be Used?

All unreplied outreach follow-ups should use this approved template:

```text
Hi {first_name},

I wanted to briefly follow up on my earlier note about the {role_title} role at {company_name}.

I reached out because I believe the role could be a strong mutual fit with my background in {background_fit_areas}. I know you are busy, so I appreciate you taking the time to read this.

If you are open to it, I would be grateful for a brief 15-minute conversation to hear your perspective on the role, the team, or what tends to matter in the process.

If this is not relevant or not the right time, I completely understand and will not keep following up.

Best,
Achyutaram Sonti
```

Template rules:
- Use this as the only default template for unreplied first follow-ups.
- Render the follow-up body deterministically from the approved template.
- Only `{background_fit_areas}` may be selected or generated from allowed evidence, and it must pass validation.
- `{background_fit_areas}` should be 2-3 short noun phrases, not a sentence, proof paragraph, long metric claim, or generic skill dump.
- Do not repeat metric-heavy proof points from the original email. Keep the follow-up light and rely on the existing thread for detailed evidence.
- If the worker cannot produce a role-specific, evidence-grounded `{background_fit_areas}` phrase, hold or escalate the follow-up rather than sending a generic fallback such as `software engineering`, `backend systems`, or another broad repeated phrase.
- Use the short follow-up signature only: `Best,` and `Achyutaram Sonti`.
- `{background_fit_areas}` must be grounded in the original sent email, the JD when available, and the tailored resume evidence.
- Do not repeat generic background phrases across unrelated roles.
- Do not use the older terse JD-theme follow-up template.

## Q3. Should Follow-Ups Require Owner Review Before Sending?

Decision: no owner review is required for normal eligible follow-ups.

The follow-up worker should directly send eligible follow-ups automatically after internal agent review and validation gates pass. This should work like normal first-email drafting and sending: autonomous by default, but blocked or held for review when safety checks fail.

Required internal review gates before send:
- approved follow-up template is used
- short follow-up signature is used
- `{background_fit_areas}` is grounded in the original sent email, JD when available, and tailored resume evidence
- retired terse JD-theme template is not used
- no prohibited internal artifact text leaks into the email
- original email did not bounce
- no prior follow-up was sent for the original outreach thread
- direct Gmail-thread reply check found no inbound recipient reply after the original `sent_at`
- Gmail-thread reply state is not unknown

## Q6. Should Missing JD/Role Artifacts Block Follow-Ups?

Decision: no.

If the JD or role-context artifact is missing, the follow-up worker may still send using the original sent email body plus tailored resume evidence. The worker should record that it used the missing-JD fallback in the follow-up plan review evidence.

## Q32. Which Resume Evidence Should Follow-Ups Use?

Decision: prefer the exact tailored resume/version associated with the original sent email.

If the original sent email's resume linkage is unavailable, the worker may fall back to the latest approved tailored resume for the same job posting and should record that fallback in review evidence.

If tailored resume evidence is missing too, the worker may still send using only the original sent email body when that body contains enough concrete fit context to derive `{background_fit_areas}`. If the original email body is too generic or unavailable, the worker should hold or escalate rather than invent fit areas.

The original sent email body is the narrative source of truth. JD and resume evidence may support or sharpen `{background_fit_areas}`, but the follow-up should not change the story, claim a different fit, or introduce materially new positioning that conflicts with the original email.

## Q33. How Should The Follow-Up Choose The Recipient Name?

Decision: reuse the recipient name exactly as used in the original sent email when recoverable.

If the original salutation cannot be recovered, parse the first name from the contact display name. Validate that the parsed value is not a placeholder, malformed name, email address, or otherwise unsafe salutation value before sending.

## Q34. Should Generic Email Addresses Be Followed Up?

Decision: yes, if the original sent `role_targeted` email was valid and all follow-up gates pass.

Generic addresses such as `careers@`, `jobs@`, or `info@` should not automatically block follow-up. Reuse the original salutation when available, and do not invent a personal first name for a generic mailbox.

If the original email used a generic salutation such as `Hi,` or `Hello,`, preserve that exact salutation in the follow-up.

## Q35. Where Should Role/Company Wording Come From?

Decision: prefer the original sent email body or subject when recoverable.

Use canonical database fields only as fallback. Do not silently change role/company wording in a way that conflicts with the original email.

## Q36. Should Signature Text Be Used For Fit Extraction?

Decision: no.

When extracting `{background_fit_areas}` from the original sent email, ignore the sender signature and contact block so LinkedIn URL, phone, email, and signoff text do not contaminate fit-area selection.

## Q7. What If Same-Thread Sending Is Not Possible?

Decision: skip automatic sending and escalate.

If the original Gmail thread ID is missing, or if the follow-up worker cannot send in the original thread, it should not send a standalone new email with a `Re:` subject. It should skip the send and create a review packet with a clear missing-thread-context reason.

## Q8. Should Successful Follow-Ups Create Review Packets?

Decision: no.

Successfully sent follow-ups should be visible through persisted follow-up plan, outreach message, send result, and follow-up cycle audit records. Review packets are only needed for blocked, ambiguous, failed, or escalated follow-up cases.

Every follow-up worker invocation should write a cycle-run audit row, including no-op cycles where no message is sent. The audit should capture counts such as candidates examined, drafts created, messages sent, waiting for pacing, skipped because replied/bounced/already-followed-up, retryable, blocked, held for review, and errors.

Blocked, ambiguous, failed, or escalated follow-up review packets should include the original sent email body, rendered follow-up draft if one exists, recipient and Gmail-thread metadata, structured skip/failure reason, thread-check evidence, bounce evidence, grounding evidence, and the exact recommended owner action such as reset after metadata repair, leave skipped, or inspect Gmail manually.

## Q9. Should Follow-Ups Attach The Tailored Resume?

Decision: no.

Follow-up emails should not attach the tailored resume or any other file by default, even when the original outreach included a resume attachment.

## Q10. Which Outreach Modes Should Automatic Follow-Ups Cover?

Decision: only original `role_targeted` sent emails.

The follow-up worker should not create automatic follow-ups for `general_learning`, `manual_reply`, existing `follow_up`, existing `role_targeted_followup`, or any future non-initial outreach mode. Historical sent `follow_up` and `role_targeted_followup` modes should be treated as equivalent suppression evidence and should suppress another automatic follow-up for the same original outreach thread.

New automatic follow-up messages should use `role_targeted_followup` as the canonical outreach mode. The older `follow_up` mode is legacy historical data only.

Sending a follow-up should not mutate the original sent `role_targeted` outreach message body, mode, sent timestamp, or delivery identity. Persist the follow-up as a separate `role_targeted_followup` `outreach_messages` row linked back to the original outreach message through `original_outreach_message_id` or equivalent follow-up plan linkage.

Email-rooted workflow:
- start from sent `outreach_messages`
- treat each original sent email/Gmail thread as its own follow-up scope, even when the same contact has multiple separate role threads
- do not suppress a separate role thread by contact alone unless Gmail/thread evidence shows it is the same conversation
- current contact-level hard stops such as `do_not_contact`, blacklisted, owner-blocked, or equivalent non-contactable states override otherwise eligible follow-up candidates
- do not start from job postings
- use job posting/JD artifacts only as optional drafting context
- do not block an otherwise eligible sent email just because the linked posting state changed
- do not block solely because `job_posting_id` is missing if the original sent email is otherwise valid and has enough email/thread context
- require the persisted original sent email body; if it cannot be loaded from canonical state or the associated sent-email artifact, skip automatic follow-up and create a review packet
- do not block solely because the original subject is missing when the original body and same-thread metadata are available
- include historical sent `role_targeted` emails from before the feature was implemented, subject to all gates
- during historical backfill/dry-run, create skipped plan rows for emails suppressed because they were already followed up, replied, bounced, or otherwise skipped, with structured reasons instead of silently ignoring them

System-recorded first-email scope:
- include first emails sent autonomously by the system
- include first emails manually triggered through the system
- require the original first email to be persisted as a sent `role_targeted` outreach message in canonical state
- do not follow up on arbitrary external Gmail messages that were never recorded as system outreach

## Q11. How Should We Detect That A Follow-Up Was Already Sent?

Decision: use both database linkage and Gmail-thread evidence.

The follow-up worker should skip a candidate if either:
- the database already links a follow-up to the original outreach message
- the original Gmail thread already contains a later outbound message from the sender after the original `sent_at`

This catches both clean future follow-ups and older/manual follow-ups that may not have perfect database linkage.

A later outbound message found directly in Gmail suppresses follow-up even if that outbound message was sent manually from Gmail and is not recorded in the local database.

The follow-up plan should link to the original outreach message as the canonical source and also store a Gmail thread ID snapshot used for checks/sending, for audit and debugging.

Skip/block reasons should be structured reason codes, such as `bounced`, `replied_in_thread`, `already_followed_up`, `missing_followup_thread_context`, `missing_original_body`, `waiting_for_pacing`, `transient_send_retry_cooldown`, `ambiguous_send_state`, and `grounding_evidence_insufficient`.

Terminal reasons such as `already_followed_up`, `bounced`, and `replied_in_thread` should stay skipped unless the owner explicitly resets the plan. `missing_followup_thread_context` is reviewable/resettable because repairing or importing thread metadata may make the plan sendable later. Temporary reasons such as Gmail API failure, transient send retry cooldown, or waiting for pacing may be rechecked by later cycles.

During backfill, old manual or legacy follow-up evidence may be linked back to the original outreach email when the system can confidently match the same Gmail thread or original message relationship. This linkage is only for suppression and audit; it should not rewrite historical message content. If precise local linkage cannot be created but Gmail-thread evidence shows a later outbound follow-up, suppress the original candidate as `already_followed_up`.

## Q23. When Should Follow-Up Plans Be Created?

Decision: continuously create or refresh plans before eligibility.

The follow-up worker may create or refresh plans for sent `role_targeted` messages before they are due. A plan becomes sendable only after the 4-calendar-day threshold and all stop-condition, thread-reply, duplicate-follow-up, pacing, and agent-review gates pass.

Do not render follow-up draft bodies or draft artifacts before the original email reaches the 4-calendar-day eligibility threshold. Pre-eligibility plans may track candidate status and due time, but content generation should wait until the follow-up is eligible so stale drafts are not created.

## Q12. Which Replies Should Suppress A Follow-Up?

Decision: any inbound reply in the same Gmail thread.

If anyone replies in the original Gmail thread after the original sent email, the follow-up worker should not send a follow-up. This includes replies from the original recipient, another person copied on the thread, or someone added later.

Thread checks for replies, bounces, and later outbound messages should consider only messages after the original `sent_at`. Earlier thread history should not block follow-up eligibility.

The worker should use the configured sender email identity, such as the Gmail profile email or runtime sender configuration, to distinguish your outbound messages from inbound replies.

The follow-up worker should only use inbound replies as suppression evidence for that original outreach thread. It should not classify reply sentiment, infer negative intent such as `not interested`, or update broader contact lifecycle state from reply content; that belongs to the feedback or reply-classification system.

## Q13. Should Bounce Emails Count As Replies?

Decision: bounce detection stays separate from reply detection.

However, if there is a bounce tied to the original outreach message, recipient address, delivery tracking ID, or original Gmail thread, the follow-up worker should not send a follow-up.

`not_bounced` is not required for follow-up eligibility. The worker should block if a bounce exists, but it does not need a positive `not_bounced` event before sending.

## Q14. Should Follow-Ups Preserve Original Recipients?

Decision: yes.

When sending a same-thread follow-up, preserve the original recipient envelope where available, including the original `To` recipient and any original `Cc` recipients. Do not add new recipients by default.

If the contact record's current email address or recipient metadata differs from the original sent email, use the original sent email's recipient envelope for the same-thread reply. Do not silently retarget an existing follow-up thread based on current contact metadata.

## Q15. Should The Follow-Up Change The Subject?

Decision: no.

The follow-up should be sent as an actual reply in the same Gmail thread. It should not create a new standalone email, and it should not rewrite the subject to simulate a reply.

## Q37. Should Follow-Ups Preserve HTML Formatting?

Decision: no.

Follow-ups should be plain text by default. The approved first-follow-up template is simple and does not need rich HTML formatting.

## Q38. Should Follow-Ups Quote The Original Email?

Decision: no.

The follow-up body should not include quoted original-email content by default. Gmail thread history is enough prior context.

## Q39. Should Follow-Ups Add Gmail Labels?

Decision: no.

Follow-up tracking metadata should be persisted locally in canonical database rows and artifacts. The current feature does not need Gmail labels or other provider-side metadata beyond sending the same-thread reply.

## Q16. How Often Should The Follow-Up Worker Run?

Decision: every 60 seconds.

The dedicated follow-up `launchd` worker should run once per minute. This is only the check interval; actual sending still obeys the global inter-send pacing rule.

## Q24. Should Follow-Ups Have Separate Pause/Stop Control?

Decision: yes, separate control for follow-ups, with global stop applying to all workers.

The follow-up worker should have separately inspectable control state so it can be paused or resumed independently from the primary supervisor. A global system stop should stop or disable all workers, including follow-ups.

## Q25. Should `jhc-agent-start` Start Follow-Ups Too?

Decision: yes.

The normal runtime start and stop commands should manage the follow-up `launchd` job alongside the supervisor and delayed feedback-sync jobs. A normal start should load/kick the follow-up worker, and a normal stop should unload/disable it.

## Q26. Should `jhc-chat` Show Follow-Up Status?

Decision: yes.

The startup dashboard should include a compact follow-up summary with `due_now`, `waiting_for_pacing`, `sent_today`, `blocked_or_review`, `last_cycle_at`, and `last_cycle_result`.

## Q41. How Should Implementation Start?

Decision: create a GitHub issue before implementation.

This follow-up feature should be tracked as one implementation work item with a GitHub issue summarizing the spec decisions. Implementation should include tests and dry-run validation first, with automatic sending disabled until explicitly enabled through runtime control state.

Tracking issue: https://github.com/sontiachyut/job-hunt-copilot-v4/issues/94

## Q27. Should Follow-Ups Have Separate Logs?

Decision: yes.

The follow-up `launchd` job should write to separate stdout and stderr logs, such as `ops/logs/followups.stdout.log` and `ops/logs/followups.stderr.log`, so follow-up activity can be debugged independently.

## Q28. Should There Be A Manual Follow-Up Cycle Command?

Decision: yes.

The runtime should provide an on-demand follow-up cycle command, such as `bin/jhc-followup-cycle`, that runs one bounded follow-up worker cycle for testing, debugging, and manual operational checks.

The runtime should also provide a manual control path to reset a skipped, held, blocked, or reviewable follow-up plan after metadata is repaired or the owner explicitly wants it re-evaluated.

Resetting a plan only allows re-evaluation. It must not override bounce, reply, already-followed-up, or other safety facts; those gates must be checked again before sending.

## Q29. Should Follow-Ups Support Dry Run?

Decision: yes.

The follow-up cycle command and reusable worker logic should support dry-run mode. Dry run should evaluate candidates and may render draft/review evidence for inspection, but must not send email or mutate sent-state as if an email had been sent.

Dry run is primarily for engineering validation by the agent: confirming candidate selection, gates, thread checks, draft rendering, and persistence. It is not the main owner-review workflow for follow-up content.

Dry run may create or update durable `outreach_followup_plans` rows and dry-run evaluation artifacts so the queue is visible. Those records must clearly indicate dry-run evaluation and must not mark any follow-up as sent.

Resolved dry-run details:
- render and persist the actual follow-up draft text with clear dry-run markers
- persist the same agent-review evidence required for auto-send
- perform only read-only Gmail checks for replies, bounces, and existing later outbound messages
- never call Gmail send APIs
- never set `sent_at`, `message_status = sent`, `plan_status = sent`, or successful send-result state
- allow evaluation fields such as `last_evaluated_at`, `last_reply_check_at`, `last_reply_check_result`, and `last_skip_reason`
- be idempotent for the same candidate and evidence
- refresh stale dry-run draft artifacts if source evidence changes
- avoid duplicate active follow-up plans for the same original outreach message
- evaluate a bounded dry-run batch instead of stopping at the first would-send candidate
- use 25 candidates examined as the default dry-run batch size, ordered oldest original sent email first
- report candidates examined, would-send candidates, skipped reasons, suppressed already-followed-up counts/examples, held/escalated cases, and artifact paths
- do not create expert review packets during dry-run; report blocked/skipped/held/escalated cases only

## Q30. Should The First Rollout Auto-Send Immediately?

Decision: no.

The first rollout should start in dry-run mode only for engineering validation. Automatic follow-up sending should require explicit later owner enablement after the implementation has been validated enough to proceed.

When auto-send is first enabled after dry-run validation, use a limited rollout cap of 10 successful follow-up sends, then pause follow-up auto-send and surface the results for inspection before sending more.

When the initial 10-send rollout cap is reached, pause follow-up auto-send only. The main supervisor pipeline and delayed feedback-sync worker may continue normally unless another global pause or stop condition applies.

The initial rollout inspection packet should include the 10 actual sent follow-up emails, recipients, original sent dates, follow-up sent dates, thread-check results, gate-pass evidence, and a compact skipped/blocked summary.

After the initial 10-send rollout has been inspected and approved, future automatic follow-up sends default to no additional batch cap unless the owner configures a follow-up batch limit later through runtime control state.

## Q31. Where Should Auto-Send Enablement Live?

Decision: canonical runtime control state.

Follow-up dry-run versus automatic-send mode should be controlled through `agent_control_state` or equivalent canonical runtime control state, not through code edits. The first rollout default should disable automatic sends.

## Q4. Should Follow-Ups Only Send During Business Hours?

Decision: no business-hours send window is required.

After a follow-up becomes eligible, the follow-up worker may send it at any time of day. The cadence still uses the 4-calendar-day eligibility rule.

## Q5. Should Follow-Ups Use Normal Send Pacing?

Decision: yes, follow-ups should use the same pacing rules as normal outreach.

The follow-up worker should not send all due follow-ups in one immediate burst. It should respect the same randomized global inter-send gap used by ordinary outreach.

Follow-ups do not need normal company, posting, or recipient-wave caps. Once an original sent email is more than 4 calendar days old and passes the bounce/reply/already-followed-up/internal-review gates, it is eligible to send subject only to the global inter-send pacing rule.

Initial outreach sends and follow-up sends should share the same global inter-send pacing queue. The follow-up worker should look at the latest `sent_at` across canonical sent outreach messages and wait for the active randomized 6-10 minute gap. It should not maintain a separate follow-up-only pacing lane.

## Q17. In What Order Should Due Follow-Ups Send?

Decision: oldest original sent email first.

When multiple follow-ups are due, process them by the original email's `sent_at` ascending.

Historical backfill and the initial 10-send rollout should use this same oldest-first ordering so review begins with the oldest eligible outreach threads.

## Q18. How Many Follow-Ups Can One Cycle Send?

Decision: at most one.

Each follow-up worker cycle may evaluate multiple due candidates to find the next sendable one, but it should stop after one successful send and leave the rest for later cycles.

If a follow-up is otherwise due but the shared global send pacing queue is blocked, the plan should use `waiting_for_pacing` so the dashboard can explain why nothing sent yet.

## Q19. Should Follow-Up Drafts Be Persisted Before Sending?

Decision: yes.

Even though owner review is not required, the follow-up worker should persist the exact follow-up draft body and agent-review evidence before attempting automatic send. The Gmail send attempt should use the persisted draft body exactly rather than regenerating follow-up text at send time.

Follow-up draft, dry-run, and agent-review artifacts should live next to the original outreach/email artifact under a clear `followups/` child folder when the original artifact path is available. If the original artifact path is missing, use a canonical fallback such as `data/outreach-followups/{original_outreach_message_id}/followup-1/`.

## Q20. What If Send State Becomes Ambiguous?

Decision: do not retry automatically; escalate.

If Gmail may have sent the follow-up but local persistence, thread metadata, or send-result writeback fails or becomes uncertain afterward, the worker should mark the plan as ambiguous or held, preserve all available provider evidence, and create a review packet. This avoids duplicate follow-up sends.

## Q21. What If There Is A Clear Transient Failure Before Send?

Decision: retry later with cooldown.

If the failure happens before there is evidence that Gmail accepted the follow-up send, such as a clear network, provider, or auth failure, the follow-up plan may stay pending or retryable for a later cycle. This retry path must not be used when the state is ambiguous and Gmail may have sent the email.

Retry policy:
- wait 15 minutes before retrying
- allow at most 3 automatic retries
- after retry exhaustion, leave the follow-up plan blocked and reviewable

## Q22. Should Successful Follow-Ups Start Delivery Feedback Tracking?

Decision: no.

Successful follow-up sends do not need a new Delivery Feedback tracking cycle. The required safety checks are the pre-draft and pre-send bounce/reply/thread guards.
