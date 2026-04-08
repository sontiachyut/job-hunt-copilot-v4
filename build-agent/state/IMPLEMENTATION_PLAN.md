# Implementation Plan

This plan translates `prd/spec.md` and `prd/test-spec.feature` into the next build program for the specialist-engineer loop.

It should stay aligned with:
- `prd/spec.md`
- `prd/test-spec.feature`
- `build-agent/state/build-board.yaml`

## Current Planning Result

- `BA-00` is complete: the build is now sequenced by phases, dependencies, and bounded slices instead of the original seeded checklist.
- `BA-01-S1` is complete: the repository now has a real `job_hunt_copilot` bootstrap package, runtime support-directory creation, secret-file materialization, and a SQLite migration entrypoint for `job_hunt_copilot.db`.
- `BA-01-S2` is complete: the canonical next-build schema, minimum index set, review views, and shared record-ID/timestamp helpers now initialize cleanly through the migration framework.
- `BA-01-S3` is complete: shared artifact-contract writers, canonical workspace path helpers, and `artifact_records` registration utilities are now available for downstream components.
- `BA-01` and `BA-02` are now complete overall: the repository has a real supervisor-state access layer, lease-guarded bounded heartbeat execution, incident-aware work selection, auto-pause detection, terminal-run review packet generation, expert review decisions, override audit lineage, and persisted per-cycle context snapshots.
- Explicit implementation inference: the PRD currently conflicts on whether escalated runs are immutable history or resumable after clearance; this slice implemented the explicit `escalated -> in_progress` transition rule while still creating new posting runs only when no non-terminal run exists.
- Explicit implementation inference: the initial action catalog intentionally stays narrow to posting-run bootstrap, durable lead-handoff checkpointing, and unresolved-incident escalation so unsupported later-stage work becomes a canonical incident instead of improvised behavior.
- `BA-02-S3` is complete: review-worthy terminal runs can now emit `review_packet.json` plus `review_packet.md`, persist `expert_review_packets` and `expert_review_decisions`, register those artifacts in `artifact_records`, and record expert override lineage through canonical `override_events`.
- `BA-03-S1` is complete: bootstrap and `scripts/ops/build_runtime_pack.py` now render the product-side runtime identity, policies, action catalog, service goals, escalation policy, progress-log scaffold, ops-plan scaffold, and chat or supervisor bootstrap prompts under `ops/agent/`.
- `BA-03` is now complete in code overall: the repo has product-side plist rendering, canonical control-state CLI helpers, `scripts/ops/run_supervisor_cycle.py`, repo-local `jhc-agent-start`, `jhc-agent-stop`, `jhc-agent-cycle`, and the direct `jhc-chat` operator wrapper for the local supervisor heartbeat and expert-entry surface.
- `BA-04-S1` is complete: the repo now has `job_hunt_copilot.linkedin_scraping`, the repo-local `jhc-linkedin-ingest` entrypoint, canonical manual lead workspace creation, `capture-bundle.json` persistence, exact-copy paste fallback, and `lead_raw_source` artifact registration for accepted manual leads.
- `BA-04-S2` is complete: manual leads can now run a deterministic first-pass split over canonical `raw/source.md`, derive `post.md`, `jd.md`, and `poster-profile.md` when evidence exists, publish `source-split.yaml` plus `source-split-review.yaml`, and persist a blocked-or-ready `lead-manifest.yaml` with canonical `split_review_status` updates.
- `BA-04-S3` is complete: reviewed manual leads can now materialize canonical `job_postings`, auto-create poster `contacts`, persist `linkedin_lead_contacts` plus `job_posting_contacts`, expose founder recipient typing when titles warrant it, and upgrade `lead-manifest.yaml` with created entity ids plus `handoff_targets.resume_tailoring.ready = true`.
- `BA-04-S4` is complete: existing manual leads can now refresh in place, snapshot replaced source or review artifacts under `history/`, clear stale live split outputs, rewrite an honest refresh-state `lead-manifest.yaml`, and preserve prior posting `jd_artifact_path` history by repointing canonical postings to the snapped `jd.md` when a refreshed source retires the live one.
- `BA-05-S1` is complete: the repo now has `job_hunt_copilot.gmail_alerts`, timestamp-keyed Gmail collection-unit persistence under `linkedin-scraping/runtime/gmail/`, plain-text-first LinkedIn alert parsing with HTML-derived fallback only when the plain-text body is unusable, retained `job-cards.json` artifacts, and zero-card review-threshold metadata without lead fan-out yet.
- `BA-05-S2` is complete: `bin/jhc-linkedin-ingest gmail-batch` now runs the bounded autonomous Gmail intake path end-to-end through lead workspace creation, copying lead-local `alert-email.md`, publishing `alert-card.json`, `jd-fetch.json`, and `lead-manifest.yaml`, deduping by `job_id` or normalized LinkedIn job URL fallback when `job_id` is missing, and persisting honest `incomplete` / `blocked_no_jd` lead state without manual split artifacts.
- `BA-05` is now complete in code overall: autonomous Gmail intake now merges multi-source JD candidates into canonical `jd.md`, preserves final merge provenance plus identity-reconciliation metadata in `jd-fetch.json` and `lead-manifest.yaml`, blocks downstream handoff honestly on material Gmail-card versus JD identity mismatches, and tolerates normalization-only differences without creating unnecessary review debt.
- `BA-06-S1` is complete: `job_hunt_copilot.resume_tailoring` can now bootstrap from `job_posting_id`, evaluate hard eligibility from the persisted posting-linked `jd.md`, write `applications/{company}/{role}/eligibility.yaml`, mark `hard_ineligible` postings honestly, and create or reuse the first `resume_tailoring_runs` row with canonical timestamps plus workspace linkage for bootstrap-ready postings.
- `BA-06-S2` is complete: eligible postings now materialize `resume-tailoring/output/tailored/{company}/{role}/` with shared-contract `meta.yaml`, mirrored `jd.md`, optional mirrored `post.md` / `poster-profile.md`, working `resume.tex`, `scope-baseline.resume.tex`, component-local input mirrors, and Step 3 through Step 7 scaffold artifacts that later finalize logic can fill.
- `BA-06-S3` is complete: `job_hunt_copilot.resume_tailoring` now replaces the scaffold files with deterministic Step 3 through Step 7 artifacts, generates honest JD signals plus evidence mapping from the persisted `jd.md` and master profile, applies the selected Step 6 payload to `resume.tex`, enforces scope against `scope-baseline.resume.tex`, compiles `Achyutaram Sonti.pdf`, verifies one-page output, and moves successful runs into `tailoring_status = tailored` plus `resume_review_status = resume_review_pending`.
- `BA-06-S4` is complete: `job_hunt_copilot.resume_tailoring` now records mandatory review decisions as durable per-run artifacts, transitions pending review runs into `approved` or `rejected`, advances approved postings into `requires_contacts` or `ready_for_outreach`, records owner overrides with prior-decision context in canonical `override_events`, and snapshots completed run workspaces before retailoring so previous run rows keep immutable history references.
- `BA-06` is now complete in code overall: Resume Tailoring now runs from `job_posting_id` bootstrap through eligibility, workspace materialization, deterministic intelligence, finalize plus one-page verification, mandatory review approval or rejection, DB-first outreach handoff, override lineage, and repeated-run history preservation.
- `BA-07-S1` is complete: `job_hunt_copilot.email_discovery` now boots strictly from approved `requires_contacts` postings, resolves Apollo company identity when available, persists broad `discovery/output/{company}/{role}/people_search_result.json`, and materializes only the initial 6-contact shortlist into canonical `contacts` plus `job_posting_contacts` while promoting reused `identified` links into `shortlisted`.
- `BA-07-S2` is complete: `job_hunt_copilot.email_discovery` now runs selective Apollo enrichment only for canonical shortlisted contacts that still need clearer identity, LinkedIn URL recovery, or a usable work email, persists best-effort `recipient_profile.json` artifacts when public LinkedIn extraction succeeds, removes terminal sparse dead ends from canonical shortlist state, and publishes the contact-level readiness signals that now feed BA-08 send-set planning.
- `BA-07-S3` is complete: `job_hunt_copilot.email_discovery` now runs the ordered `prospeo -> getprospect -> hunter` cascade for linked contacts that still lack usable emails, normalizes provider-specific no-match and failure outcomes, reuses clearly identified working emails, skips bounced-provider retries, persists `discovery_result.json` plus one-row-per-cascade `discovery_attempts`, and updates canonical `provider_budget_state` plus `provider_budget_events`.
- `BA-07` is now complete in code overall: People search, shortlist materialization, selective enrichment, recipient-profile capture, person-scoped email discovery fallback, provider-budget tracking, and unresolved or exhausted review visibility now exist behind the current outreach discovery boundary.
- `BA-08-S1` is complete: `job_hunt_copilot.outreach` now computes the current autonomous role-targeted send set from canonical posting, contact, and prior-message state, prefers recruiter plus manager-adjacent plus engineer coverage with deterministic fallback fill, excludes repeat-outreach contacts from the automatic set, and exposes queryable company-cap plus randomized inter-send-gap pacing decisions for the later send runtime.
- `BA-08-S2` is complete: `job_hunt_copilot.outreach` now generates deterministic role-targeted and general-learning drafts from persisted posting, tailoring, sender-profile, and optional recipient-profile context, persists canonical `outreach_messages` rows plus stable per-message `email_draft.md` / `send_result.json` artifacts, mirrors the latest role-targeted draft artifacts at the posting workspace root, and advances postings plus linked contacts into `outreach_in_progress` when drafting begins.
- `BA-08-S3` is complete: `job_hunt_copilot.outreach` now executes the active drafted outreach wave through a provider-injected send runner, persists canonical `sent_at` plus thread or delivery identifiers, blocks repeat-contact or ambiguous resend cases with review-safe `blocked` outcomes instead of double-sending, advances successful sends into `sent` / `outreach_done`, and closes postings into `completed` once the active wave reaches terminal sent or review-blocked states.
- `BA-08` is now complete in code overall: send-set selection, draft persistence, paced send execution, duplicate-send guardrails, canonical message history, and posting-wave completion handling now exist behind the current outreach runtime boundary.
- `BA-09-S1` is complete: `job_hunt_copilot.delivery_feedback` now supports immediate post-send and delayed mailbox observation over canonical sent-message rows, persists auditable `feedback_sync_runs`, records exact-message `delivery_feedback_events` for `bounced`, `not_bounced`, and `replied` outcomes, emits per-event `delivery_outcome.json` artifacts with workspace-root latest mirrors, and lets send execution trigger the immediate poll automatically when a mailbox observer is supplied.
- `BA-09-S2` is complete: `job_hunt_copilot.review_queries` now exposes read-only review surfaces for posting states, contact states, sent-message history, unresolved discovery, bounced feedback, pending expert review packets, open incidents, blocked/failed/repeat-outreach cases, override history, and per-object traceability over artifacts, transitions, and downstream records.
- `BA-09-S3` is complete: repeated mailbox signals now dedupe at the logical-event level while preserving richer reply context, delivery feedback exposes queryable bounced versus `not_bounced` reuse candidates with replied outcomes kept review-only, and `job_hunt_copilot.email_discovery` now consumes that bounded feedback state without auto-clearing `current_working_email` on bounce retry.
- `BA-09` is now complete in code overall: delivery feedback persistence, review-query inspection, traceability, bounded feedback reuse, and reply-safe handling now exist across the outreach feedback boundary.
- `BA-10-S1` is complete: `job_hunt_copilot.acceptance_traceability`, `scripts/quality/generate_acceptance_trace_matrix.py`, and the committed `build-agent/reports/ba-10-acceptance-trace-matrix.{json,md}` reports now map all 214 acceptance scenarios to owning epics, code, tests, and explicit status.
- Explicit implementation note: the acceptance trace matrix now records 190 implemented scenarios, 8 partial scenarios, 14 gap scenarios, 1 deferred-optional scenario, and 1 excluded-from-required-acceptance scenario.
- Explicit blocker note: the remaining BA-10 hardening gaps are now explicit and narrower: downstream supervisor action registration beyond `lead_handoff`, chat review/control behavior, maintenance automation, and posting-abandon control.
- Explicit implementation note: repeat-outreach evaluation now keys off previously sent message history instead of counting freshly generated drafts, so the active drafted wave can continue into send execution without treating its own unsent drafts as prior outreach.
- Explicit implementation note: the BA-09-S2 review layer stayed query-first and read-only by reusing canonical tables, existing review views, `artifact_records`, and artifact-file lookups for reason recovery instead of adding another mutable review-state table.
- Explicit implementation note: BA-09-S3 keeps mailbox feedback as reusable read-side state instead of using bounce ingestion to rewrite `contacts.current_working_email`; discovery now decides how to consume those feedback signals when a later retry actually runs.
- Explicit implementation note: BA-09-S3 treats identical message-state-timestamp feedback as the same logical event, so retried mailbox ingestion updates the existing reply context when richer text arrives instead of appending misleading duplicates.
- Explicit implementation note: failed startup no longer leaves dishonest control state behind; `jhc-agent-start` now rolls canonical state back to `stopped` if `launchctl bootstrap` fails before the job is actually loaded.
- Explicit implementation note: the generated `ops/agent/` files remain runtime-local artifacts under `.gitignore`, so the repo tracks the materialization code and tests rather than checking in those mutable rendered outputs.
- Explicit implementation note: `jhc-chat` now records begin/end metadata plus `active_chat_session_id` in canonical control state, pauses autonomous work immediately on open, resumes on clean explicit close when chat itself caused the pause, and intentionally keeps unexpected-exit pauses active until later explicit resume or future idle-timeout automation exists.
- Explicit implementation inference: freshly captured manual leads now persist immediately as `linkedin_leads` rows with `lead_status = captured` and `split_review_status = not_started` so pre-split work is queryable before `BA-04-S2` generates deterministic split/review artifacts.
- Explicit implementation inference: paste fallback refresh now requires an explicit `lead_id` because paste submissions intentionally fingerprint the scratch-buffer contents for new-lead creation, while matching manual-capture reruns refresh automatically when the lead identity key is reused.
- Explicit implementation inference: Gmail zero-card review thresholds are currently derived from retained `email.json` metadata under `linkedin-scraping/runtime/gmail/` rather than a dedicated DB table, which keeps this slice bounded while still making unresolved zero-card history queryable for later review surfaces.
- Explicit implementation note: Gmail-derived leads with a recovered canonical `jd.md` now surface posting-materialization readiness or blocking reasons through `lead-manifest.yaml`, while downstream creation of later posting-linked runtime state remains a separate responsibility from the bounded Gmail intake slice.
- Explicit implementation note: the current tailoring runtime now backfills workspace files for preexisting active runs that predate BA-06-S2, but repeated bootstrap on an already-materialized active run intentionally preserves existing `resume.tex` and intelligence artifacts instead of clobbering in-progress tailoring work.
- Explicit implementation note: Step 3 through Step 7 persistence and the later mandatory review boundary currently stay artifact-first rather than adding new dedicated tailoring tables, which keeps BA-06 bounded while still making generated intelligence, review decisions, verification blockers, and compile outputs durable and reviewable from the workspace.
- Explicit implementation inference: the current company daily send cap is evaluated against the machine's local calendar day, while timestamps remain stored canonically as UTC ISO-8601 text and are converted only for the pacing check.
- `BA-10-S2` is complete: `tests/test_smoke_harness.py` now drives a committed bootstrap -> tailoring -> discovery -> send -> delayed-feedback -> review-query smoke path with deterministic fakes, and the regenerated BA-10 acceptance matrix now closes the explicit smoke-harness gap while leaving scheduler-wiring and other hardening blockers honest.
- `BA-10-S3` is in progress: explicit hardening regressions now verify unsupported tailoring asks stay as Step 4 gaps, role-targeted drafting ignores raw-source claims outside the approved tailoring inputs, drafting requires an approved tailoring run, outreach-message traceability exposes reply summaries without raw reply excerpts, runtime secret values stay out of canonical state/handoff artifacts/review outputs, delayed feedback now has a dedicated `launchd` scheduler path through `job_hunt_copilot.local_runtime`, `scripts/ops/run_feedback_sync.py`, `bin/jhc-feedback-sync-cycle`, and `ops/launchd/job-hunt-copilot-feedback-sync.plist`, supervisor heartbeats now use `pmset -g log` first with a >1 hour cycle-gap fallback to detect sleep/wake recovery state, targeted supervisor regressions now confirm downstream retries keep the same durable run id, blocked stage, and pending review packet while the narrow action catalog still blocks later-stage execution, focused chat/runtime-pack regressions now prove the explicit-resume recovery path after unexpected `jhc-chat` exit plus the generated chat-bootstrap scaffold without claiming the richer in-chat review/control behaviors, the BA-10 trace matrix now carries blocker-specific evidence summaries plus code/test refs for the remaining open gaps, the blocker audit report now summarizes the remaining acceptance-gap clusters plus build-board blockers with explicit confirmation commands, and the new `scripts/quality/run_ba10_validation_suite.py` entrypoint now replays the committed automated BA-10 report/smoke/runtime regression suite after refreshing the generated reports.
- Explicit implementation note: `job_hunt_copilot.acceptance_traceability` now keeps the downstream-supervisor gap aligned with the current `BA-10-S4` focus, and `tests/test_blocker_audit.py` fails if the active BA-10 focus slice is no longer represented in the open gap-cluster ledger.
- Explicit implementation note: the current chat surface is now validated through wrapper lifecycle, explicit-close resume, explicit manual resume after unexpected exit, and generated bootstrap guidance to persisted review/control surfaces, but in-chat review retrieval, control routing, and idle-timeout auto-resume remain downstream work.
- Explicit implementation note: `tests/test_local_runtime.py` now proves `scripts/ops/control_agent.py` still rejects the missing `abandon` control path, while `tests/test_runtime_pack.py` proves the generated `ops/agent/ops-plan.yaml` still treats maintenance as backlog-only placeholder state rather than an implemented workflow.
- Explicit implementation note: `job_hunt_copilot.quality_validation` and `scripts/quality/run_ba10_validation_suite.py` now give BA-10 one reusable automated validation entrypoint for the committed acceptance-report, smoke-harness, supervisor, local-runtime, review-surface, and runtime-pack checks, while manual host-side checks like live `launchctl` validation remain explicit separate blockers.
- Explicit implementation note: BA-10 smoke coverage is now machine-checkable across bootstrap, tailoring, discovery, send, feedback, and review-query targets in `job_hunt_copilot.acceptance_traceability`, and `scripts/quality/run_ba10_validation_suite.py --smoke-target ...` resolves the matching targeted command plan for each flow.
- Explicit implementation note: the BA-10 acceptance trace matrix and blocker audit now expose a machine-checked implemented-slice catalog sourced from `build-agent/state/build-board.yaml`, and each rule, scenario, gap cluster, and epic validation note now carries supporting slice ids so acceptance coverage is traceable to concrete bounded slices rather than epics alone.
- Explicit implementation note: the BA-10 blocker audit now publishes canonical validation-suite invocations for each open acceptance-gap cluster, open build-board blocker, and current focus slice, and `scripts/quality/run_ba10_validation_suite.py` now resolves `--gap-id`, `--blocker-id`, and `--current-focus` selectors directly so unresolved defects stay reproducible without hand-built command lists.
- Explicit implementation note: non-dry-run BA-10 validation passes now also persist `build-agent/reports/ba-10-validation-suite-latest.json` plus `.md`, so the latest automated smoke and hardening replay leaves durable machine-readable and reviewer-readable evidence rather than terminal-only output.
- Explicit implementation note: the latest BA-10 validation-suite snapshot now also preserves resolved selector details for requested smoke targets, acceptance gaps, build-board blockers, and current focus, so replay evidence explains why each command was selected instead of only listing the executed commands afterward.
- `BA-10-S4` is now in progress as a quality-owned support checkpoint: `tests/test_supervisor_downstream_actions.py` isolates the current `lead_handoff` checkpoint boundary, later-stage unsupported-action escalation, and retry-safe durable-run reuse, `qa_supervisor_regressions` now runs that focused file, and the regenerated BA-10 reports cite the dedicated downstream evidence explicitly.
- Explicit implementation note: the downstream-supervisor gap in `job_hunt_copilot.acceptance_traceability` and `job_hunt_copilot.blocker_audit` now carries a machine-readable implementation snapshot listing the only registered role-targeted checkpoint stage (`lead_handoff`), the validated blocked downstream stages (`agent_review`, `people_search`, `email_discovery`, `sending`, `delivery_feedback`), and the still-missing contact-rooted general-learning path.
- Explicit implementation note: `tests/test_supervisor_downstream_actions.py` now also proves that a ready contact-rooted general-learning candidate still yields `SUPERVISOR_CYCLE_RESULT_NO_WORK`, so the downstream-supervisor gap has direct regression evidence for the missing general-learning selector path rather than prose-only documentation.
- Explicit implementation note: the downstream-supervisor gap remains open; this slice tightened blocker evidence and validation routing only, so the next best work is still a build-lead implementation pass that registers at least one later-stage supervisor action.
- Known operational blocker: live `launchctl bootstrap gui/$UID ...` still returns `Input/output error` in this sandboxed session, and the system log needed for richer launchd diagnostics is itself blocked by sandbox restrictions, so host-side load validation remains pending for both the supervisor and delayed-feedback launchd jobs.
- Known operational risk: unattended build-lead execution needs a follow-up validation pass for the `codex exec` CLI compatibility fix already present in the worktree.

## Phase Order

1. Planning and build-loop readiness
   - `BA-00` Planning and decomposition
   - Completed in this cycle.
2. Canonical platform
   - `BA-01` Foundation and schema
     - `BA-01-S1` Runtime bootstrap and DB init skeleton
     - `BA-01-S2` Canonical schema and views
     - `BA-01-S3` Artifact contract and registry utilities
   - `BA-02` Supervisor control plane
     - `BA-02-S1` Control-state persistence and run lifecycle helpers
     - `BA-02-S2` Bounded cycle executor
     - `BA-02-S3` Review packet and override plumbing
   - `BA-03` macOS local runtime helpers
     - `BA-03-S1` Runtime pack materialization
     - `BA-03-S2` launchd and helper entrypoints
     - `BA-03-S3` `jhc-chat` operator bootstrap
3. Lead acquisition
   - `BA-04` Manual capture path
     - `BA-04-S1` Paste inbox and manual capture bundle persistence
     - `BA-04-S2` Rule-based split and review pipeline
     - `BA-04-S3` Manual lead entity materialization
     - `BA-04-S4` Lead refresh history and workspace snapshotting
   - `BA-05` Gmail alert intake
     - `BA-05-S1` Gmail collection unit and parser
     - `BA-05-S2` Autonomous lead fan-out and JD recovery
     - `BA-05-S3` JD provenance merge and mismatch review
4. Tailoring and review gate
   - `BA-06` Resume tailoring runtime
     - `BA-06-S1` Eligibility and tailoring-run lifecycle
     - `BA-06-S2` Workspace bootstrap and step artifact scaffolding
     - `BA-06-S3` Structured edit generation and finalize verification
     - `BA-06-S4` Mandatory agent review and override handling
5. Outreach execution
   - `BA-07` People search and discovery
     - `BA-07-S1` Apollo search and shortlist materialization
     - `BA-07-S2` Contact enrichment and recipient profiles
     - `BA-07-S3` Email discovery cascade and budget tracking
   - `BA-08` Drafting and sending
     - `BA-08-S1` Send-set readiness and pacing selection
     - `BA-08-S2` Draft generation and artifact persistence
     - `BA-08-S3` Send execution and repeat-outreach guardrails
   - `BA-09` Delivery feedback and review surfaces
     - `BA-09-S1` Feedback event ingestion and observation windows
     - `BA-09-S2` Review queries and traceability surfaces
     - `BA-09-S3` Feedback reuse and reply-safe handling
6. Validation and hardening
   - `BA-10` Validation and hardening
     - `BA-10-S1` Acceptance trace matrix
     - `BA-10-S2` Smoke harness and fixtures
     - `BA-10-S3` Cross-component regression and blocker burn-down
     - `BA-10-S4` Downstream supervisor action-catalog burn-down

## Dependency Notes

- `BA-01` must land before any component can publish canonical state or `artifact_records`.
- `BA-02` and `BA-03` depend on `BA-01` because supervisor state, runtime packs, and helper entrypoints all need stable schema and bootstrap helpers.
- `BA-04` establishes the shared lead workspace conventions that `BA-05` reuses for autonomous Gmail intake.
- `BA-06` depends on canonical postings plus persisted `jd.md` artifacts from ingestion.
- `BA-07` and `BA-08` depend on agent-approved tailoring state and canonical posting-contact relationships.
- `BA-09` depends on canonical messages from `BA-08` plus review-packet and incident surfaces from `BA-02`.
- `BA-10` closes the loop with acceptance traceability, smoke coverage, and blocker confirmation after the main component boundaries exist.

## Next Slice

- Current focus: `BA-10-S4` Downstream supervisor action-catalog burn-down.
- Why next: the quality-owned BA-10 hardening work now includes a dedicated downstream-stage regression target, refreshed traceability/blocker reports, and a latest validation-suite report snapshot with selector context, while the acceptance matrix still sits at 190 implemented / 8 partial / 14 gap scenarios; the highest-value remaining slice is still a build-lead implementation pass on downstream action-catalog steps beyond `lead_handoff`, because that single blocker cluster carries the largest remaining acceptance-partial count and blocks the strongest end-to-end closure.
- Done when:
  - at least one bounded downstream supervisor stage beyond `lead_handoff` is implemented without regressing durable run or review-packet semantics
  - targeted supervisor and smoke regressions prove the new stage advancement, or the blocker remains explicit with refreshed evidence
  - the acceptance trace matrix, blocker audit, build board, and progress notes all agree on the updated downstream-supervisor status

## Working Rules

- Break large items into bounded slices before implementation.
- Prefer one primary slice per unattended build session.
- Mark completed slices clearly and keep the board and plan in sync.
- Record blockers explicitly rather than silently skipping them.
