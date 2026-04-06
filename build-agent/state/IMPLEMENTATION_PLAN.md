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
- `BA-03-S2` is complete in code: the repo now has product-side plist rendering, canonical control-state CLI helpers, `scripts/ops/run_supervisor_cycle.py`, and repo-local `jhc-agent-start`, `jhc-agent-stop`, and `jhc-agent-cycle` wrappers for the local supervisor heartbeat.
- Explicit implementation note: failed startup no longer leaves dishonest control state behind; `jhc-agent-start` now rolls canonical state back to `stopped` if `launchctl bootstrap` fails before the job is actually loaded.
- Explicit implementation note: the generated `ops/agent/` files remain runtime-local artifacts under `.gitignore`, so the repo tracks the materialization code and tests rather than checking in those mutable rendered outputs.
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
     - `BA-04-S3` Manual lead entity materialization and refresh history
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

- Current focus: `BA-03-S3` `jhc-chat` operator bootstrap.
- Why next: the runtime pack plus launchd/start/stop/cycle entrypoints now exist, so the next missing acceptance surface is the direct expert chat wrapper that reads persisted state, opens the project-specific Codex operator, and pauses background work through canonical control-state wiring.
- Done when:
  - repo-local `bin/jhc-chat` exists and launches the project-rooted Codex operator with `ops/agent/chat-bootstrap.md`
  - chat session begin or end bookkeeping persists active-session state plus clean or unexpected exit history through canonical control state
  - opening and closing `jhc-chat` wires pause-on-chat plus safe resume behavior without pretending later idle-timeout or deeper operator features already exist

## Working Rules

- Break large items into bounded slices before implementation.
- Prefer one primary slice per unattended build session.
- Mark completed slices clearly and keep the board and plan in sync.
- Record blockers explicitly rather than silently skipping them.
