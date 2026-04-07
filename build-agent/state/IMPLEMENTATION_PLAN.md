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
- `BA-05-S2` is complete: `bin/jhc-linkedin-ingest gmail-batch` now runs the bounded autonomous Gmail intake path end-to-end through lead workspace creation, copying lead-local `alert-email.md`, publishing `alert-card.json`, `jd-fetch.json`, and `lead-manifest.yaml`, deduping by `job_id` or synthetic fallback identity, and persisting honest `incomplete` / `blocked_no_jd` lead state without manual split artifacts.
- Explicit implementation note: failed startup no longer leaves dishonest control state behind; `jhc-agent-start` now rolls canonical state back to `stopped` if `launchctl bootstrap` fails before the job is actually loaded.
- Explicit implementation note: the generated `ops/agent/` files remain runtime-local artifacts under `.gitignore`, so the repo tracks the materialization code and tests rather than checking in those mutable rendered outputs.
- Explicit implementation note: `jhc-chat` now records begin/end metadata plus `active_chat_session_id` in canonical control state, pauses autonomous work immediately on open, resumes on clean explicit close when chat itself caused the pause, and intentionally keeps unexpected-exit pauses active until later explicit resume or future idle-timeout automation exists.
- Explicit implementation inference: freshly captured manual leads now persist immediately as `linkedin_leads` rows with `lead_status = captured` and `split_review_status = not_started` so pre-split work is queryable before `BA-04-S2` generates deterministic split/review artifacts.
- Explicit implementation inference: paste fallback refresh now requires an explicit `lead_id` because paste submissions intentionally fingerprint the scratch-buffer contents for new-lead creation, while matching manual-capture reruns refresh automatically when the lead identity key is reused.
- Explicit implementation inference: Gmail zero-card review thresholds are currently derived from retained `email.json` metadata under `linkedin-scraping/runtime/gmail/` rather than a dedicated DB table, which keeps this slice bounded while still making unresolved zero-card history queryable for later review surfaces.
- Explicit implementation inference: successful Gmail-derived leads currently remain `incomplete` even after `jd.md` is recovered because BA-05-S3 still owns multi-source JD merge, material mismatch review, and the downstream canonical posting-materialization handoff update.
- Known operational blocker: live `launchctl bootstrap gui/$UID ...` still returns `Input/output error` in this sandboxed session, and the system log needed for richer launchd diagnostics is itself blocked by sandbox restrictions.
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

## Dependency Notes

- `BA-01` must land before any component can publish canonical state or `artifact_records`.
- `BA-02` and `BA-03` depend on `BA-01` because supervisor state, runtime packs, and helper entrypoints all need stable schema and bootstrap helpers.
- `BA-04` establishes the shared lead workspace conventions that `BA-05` reuses for autonomous Gmail intake.
- `BA-06` depends on canonical postings plus persisted `jd.md` artifacts from ingestion.
- `BA-07` and `BA-08` depend on agent-approved tailoring state and canonical posting-contact relationships.
- `BA-09` depends on canonical messages from `BA-08` plus review-packet and incident surfaces from `BA-02`.
- `BA-10` closes the loop with acceptance traceability, smoke coverage, and blocker confirmation after the main component boundaries exist.

## Next Slice

- Current focus: `BA-05-S3` JD provenance merge and mismatch review.
- Why next: autonomous Gmail workspaces, single-source JD recovery, and lead-local provenance artifacts now exist, so the next bounded ingestion gap is merging multiple JD candidates into one canonical `jd.md` while keeping material Gmail-card versus fetched-JD identity mismatches queryable and blocked honestly.
- Done when:
  - non-conflicting multi-source JD additions merge into canonical `jd.md` with one final provenance record
  - materially conflicting JD portions prefer LinkedIn-derived content while provenance records every contributing source
  - material company or role mismatches between the parsed Gmail card and fetched JD are surfaced for review while minor normalization differences remain unblocked

## Working Rules

- Break large items into bounded slices before implementation.
- Prefer one primary slice per unattended build session.
- Mark completed slices clearly and keep the board and plan in sync.
- Record blockers explicitly rather than silently skipping them.
