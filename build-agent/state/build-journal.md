# Build Journal

Use this file as an append-only implementation log for the build agent.

## Entry Template

### Session
- Date:
- Slice:
- Goal:

### Work Done
- 

### Validation
- 

### Result
- `done` / `partial` / `blocked`

### Next
- 

### Notes
- 

### Session
- Date: 2026-04-05 20:35:49 MST
- Slice: BA-00 planning refresh
- Goal: Replace the seeded build checklist with a dependency-aware implementation program tied to the PRD and acceptance spec.

### Work Done
- Re-read the build-agent identity, policies, coordination files, task catalog, state files, PRD, acceptance feature, and current git diff before editing.
- Validated that the existing `run_build_lead_cycle.py` carryover diff matches a real `codex exec` CLI incompatibility seen in the unattended cycle logs.
- Rewrote `build-agent/state/build-board.yaml` with phased epics, dependencies, bounded near-term slices, focus ordering, and an explicit unattended-build CLI blocker.
- Rewrote `build-agent/state/IMPLEMENTATION_PLAN.md` so the human-readable plan matches the new board structure and identifies the next slice.

### Validation
- Cross-checked the new plan against `prd/spec.md` section headings and the rule clusters in `prd/test-spec.feature`.
- Ran `codex exec --help` and `codex --help` to confirm the CLI flag mismatch that caused the earlier unattended-cycle failures.
- Parsed `build-agent/state/build-board.yaml` successfully with the system Ruby YAML parser after quoting machine-state strings that started with markdown backticks.

### Result
- `done`

### Next
- Start `BA-01-S1` as a foundation-engineer slice: bootstrap the runtime package layout, support directories, and DB initialization path.

### Notes
- The repository still contains the pre-existing uncommitted carryover change in `build-agent/scripts/run_build_lead_cycle.py`; it appears valid and is now recorded as `BUILD-CLI-001` for follow-up validation.

### Session
- Date: 2026-04-05 20:51:34 MST
- Slice: BA-01-S1 runtime bootstrap and DB init skeleton
- Goal: Land the first product-runtime foundation slice with bootstrap checks, support directories, secret materialization, and DB migration scaffolding.

### Work Done
- Added a new `job_hunt_copilot` package with repo-path helpers, bootstrap orchestration, secret-file expansion from `secrets/runtime_secrets.json`, and SQLite migration scaffolding.
- Added `bin/jhc-bootstrap` as the repo-local bootstrap entrypoint and a first migration that initializes `job_hunt_copilot.db` with migration tracking plus `PRAGMA user_version = 1`.
- Materialized the runtime support-directory layout in code for `paste/`, LinkedIn scraping runtime roots, tailoring/discovery/outreach outputs, and the major `ops/` runtime roots expected by later slices.
- Added focused pytest coverage for bootstrap success, idempotency, and missing-asset failure handling.
- Updated `.gitignore`, `README.md`, and `docs/ARCHITECTURE.md` so the repo-facing surfaces reflect the new runtime bootstrap layer honestly.

### Validation
- Ran `python3 -m pytest tests/test_bootstrap.py` and confirmed all 3 targeted tests passed.
- Ran `python3 -m job_hunt_copilot.bootstrap --project-root /Users/achyutaramsonti/Projects/job-hunt-copilot-v4` to verify real-repo bootstrap, support-directory creation, secret materialization, and DB initialization.
- Ran `python3 -m job_hunt_copilot.bootstrap prereqs` to confirm Python 3.11, required Python packages, and the local LaTeX toolchain are available.

### Result
- `done`

### Next
- Implement `BA-01-S2`: apply the canonical PRD section `7.1.1A` schema, indexes, and review views through the new migration framework.

### Notes
- The bootstrap slice intentionally stops short of creating the full canonical tables; that schema work remains bounded to `BA-01-S2`.

### Session
- Date: 2026-04-05 21:27:28 MST
- Slice: BA-01-S2 canonical schema and views
- Goal: Materialize the PRD-aligned canonical SQLite schema, review views, and shared record conventions through the migration framework.

### Work Done
- Added `job_hunt_copilot/migrations/0002_canonical_schema.sql` to create the canonical next-build tables, minimum index set, and review views required by `prd/spec.md` section `7.1.1A` plus the acceptance schema scenario.
- Added `job_hunt_copilot/records.py` so downstream slices can reuse stable record-ID prefixes and lifecycle timestamp helpers instead of inventing their own conventions.
- Added focused schema validation coverage in `tests/test_schema.py`, moved the minimal bootstrap test fixture into `tests/support.py`, and updated bootstrap expectations for the second migration.
- Updated `README.md` and `docs/ARCHITECTURE.md` so the repo-facing status reflects that the schema and review-view layer now exists.

### Validation
- Ran `python3.11 -m pytest tests/test_bootstrap.py tests/test_schema.py` and confirmed all 6 targeted tests passed.
- Ran `python3.11 -m job_hunt_copilot.bootstrap --project-root /Users/achyutaramsonti/Projects/job-hunt-copilot-v4` and confirmed the real repo DB applied `0002_canonical_schema.sql` and reported `user_version = 2`.
- Queried the live `job_hunt_copilot.db` and confirmed the canonical tables plus `unresolved_contacts_review`, `bounced_email_review`, `expert_review_queue`, and `open_agent_incidents_review` exist.

### Result
- `done`

### Next
- Implement `BA-01-S3`: shared artifact contract writers, `artifact_records` registration helpers, and canonical artifact path/reference helpers for downstream slices.

### Notes
- Inference recorded explicitly: the PRD prose requires `maintenance_change_batches` and additional `supervisor_cycles` snapshot columns even though the embedded DDL skeleton omits them, so this slice implemented those fields from the prose plus acceptance requirements rather than weakening the schema.
- The pre-existing unattended build-loop carryover diff under `build-agent/scripts/` remains untouched and is still tracked separately as `BUILD-CLI-001`.

### Session
- Date: 2026-04-05 21:46:03 MST
- Slice: BA-01-S3 artifact contract and registry utilities
- Goal: Land the shared handoff-contract writers, canonical artifact-path helpers, and `artifact_records` registration layer required by downstream components.

### Work Done
- Added `job_hunt_copilot/artifacts.py` with shared JSON and YAML contract writers, contract-envelope validation, relative artifact-reference normalization, and helpers that publish files plus register `artifact_records`.
- Added `job_hunt_copilot/contracts.py` so shared contract-version metadata is reusable without coupling bootstrap prerequisite checks to YAML imports.
- Extended `job_hunt_copilot/paths.py` with canonical workspace builders for lead, application, tailoring, discovery, and outreach artifacts under the repo-local runtime layout.
- Added `tests/test_artifacts.py` to cover workspace path generation, contract-envelope contents, failure-reason enforcement, and `artifact_records` persistence.
- Updated `README.md` and `docs/ARCHITECTURE.md` so the repo-facing surfaces now reflect that the artifact contract foundation exists.

### Validation
- Ran `python3.11 -m pytest tests/test_bootstrap.py tests/test_schema.py tests/test_artifacts.py` and confirmed all 9 targeted tests passed.
- Ran `python3.11 -m job_hunt_copilot.bootstrap --project-root /Users/achyutaramsonti/Projects/job-hunt-copilot-v4` and confirmed the real repo bootstrap still succeeds with `user_version = 2`.

### Result
- `done`

### Next
- Start `BA-02-S1`: add supervisor control-state persistence helpers for `pipeline_runs`, `supervisor_cycles`, `agent_control_state`, and `agent_runtime_leases`.

### Notes
- `BUILD-CLI-001` remains open and untouched; this slice deliberately stayed within foundation ownership rather than mixing in build-lead runtime fixes.

### Session
- Date: 2026-04-06 13:10:58 MST
- Slice: BA-02-S1 control-state persistence and run lifecycle helpers
- Goal: Land the supervisor control-plane access layer for canonical control state, durable pipeline runs, heartbeat-cycle audit rows, and runtime lease recovery before bounded cycle execution begins.

### Work Done
- Added `job_hunt_copilot/supervisor.py` with canonical helpers for agent control-state defaults and mode transitions, posting-scoped run creation or reuse, bounded run-status transitions, review-packet state transitions, heartbeat-cycle audit rows, and runtime lease acquisition, renewal, release, and stale recovery.
- Added focused supervisor persistence coverage in `tests/test_supervisor.py` for control-state semantics, single-open-run enforcement, non-terminal run reuse, escalated-run recovery, heartbeat-cycle summaries, and lease deferral or reclamation.
- Updated `README.md` and `docs/ARCHITECTURE.md` so the repo-facing status reflects that the supervisor persistence layer now exists.
- Updated the build board and implementation plan to mark `BA-02-S1` complete and hand off `BA-02-S2` as the next bounded slice.

### Validation
- Ran `python3.11 -m pytest tests/test_supervisor.py` and confirmed all 6 targeted supervisor-state tests passed.
- Ran `python3.11 -m pytest tests/test_bootstrap.py tests/test_schema.py tests/test_artifacts.py tests/test_supervisor.py` and confirmed all 15 targeted regression tests passed.

### Result
- `done`

### Next
- Implement `BA-02-S2`: a bounded supervisor heartbeat executor that reads control state, acquires or defers the lease, selects one work unit, and persists the cycle result without overlapping execution.

### Notes
- Explicit inference recorded: the PRD currently conflicts on whether an escalated `pipeline_run` is immutable history or resumable after clearance. This slice implemented the explicit `escalated -> in_progress` transition rule from `FR-OPS-17D` while still keeping automatic new-run creation limited to cases where no non-terminal run exists for the posting.
- `BUILD-CLI-001` remains open and untouched.

### Session
- Date: 2026-04-06 13:35:07 MST
- Slice: BA-02-S2 bounded cycle executor
- Goal: Land one bounded supervisor heartbeat executor that reads control state, acquires or defers the canonical lease, selects one work unit, validates bounded action execution, and records incidents or auto-pause outcomes instead of improvising broad behavior.

### Work Done
- Extended `job_hunt_copilot/supervisor.py` with canonical incident helpers, a narrow registered supervisor action catalog, one-work-unit selection logic, auto-pause detection, and `run_supervisor_cycle` as the lease-guarded bounded executor.
- Added cycle context snapshot persistence under `ops/agent/context-snapshots/<supervisor_cycle_id>/context_snapshot.json` so selected work, control state, and outcome details are inspectable after each completed bounded cycle.
- Added focused supervisor tests for new-run bootstrap, durable-run reuse, incident-first priority, critical auto-pause, and unsupported-stage escalation through canonical incidents rather than open-ended next-step guesses.
- Updated `README.md` and `docs/ARCHITECTURE.md` so the repo-facing status now reflects that a bounded supervisor cycle executor exists, while review packets and override plumbing remain explicitly in progress.
- Updated the build board and implementation plan to mark `BA-02-S2` complete and hand off `BA-02-S3` as the next bounded slice.

### Validation
- Ran `python3.11 -m pytest tests/test_supervisor.py` and confirmed all 11 supervisor tests passed.
- Ran `python3.11 -m pytest tests/test_bootstrap.py tests/test_schema.py tests/test_artifacts.py tests/test_supervisor.py` and confirmed all 20 targeted regression tests passed.

### Result
- `done`

### Next
- Implement `BA-02-S3`: persist `expert_review_packets`, `expert_review_decisions`, and `override_events` so terminal or otherwise review-worthy runs can expose canonical review and override lineage.

### Notes
- Explicit inference recorded: the initial supervisor action catalog intentionally stays narrow to posting bootstrap, lead-handoff checkpointing, and unresolved-incident escalation. Later-stage pipeline work now becomes a canonical incident and escalated run instead of an improvised control-plane action.
- `BUILD-CLI-001` remains open and untouched.

### Session
- Date: 2026-04-06 13:57:48 MST
- Slice: BA-02-S3 review packet and override plumbing
- Goal: Persist expert review packets, review decisions, and override lineage in the supervisor control plane, and hook review-worthy terminal run outcomes into canonical packet generation.

### Work Done
- Extended `job_hunt_copilot/supervisor.py` with canonical helpers for `expert_review_packets`, `expert_review_decisions`, and `override_events`, including persisted override lineage back to prior decision context and affected object-state snapshots.
- Added review-packet artifact generation under `ops/review-packets/<pipeline_run_id>/` plus `artifact_records` registration for both `review_packet.json` and `review_packet.md`, and added runtime path helpers for those artifacts in `job_hunt_copilot/paths.py`.
- Wired the bounded supervisor cycle so unsupported-stage escalation for a selected `pipeline_run` now emits a pending expert review packet automatically instead of leaving the terminal outcome without review artifacts.
- Added focused supervisor tests for direct review-worthy finalization, review decision plus override lineage persistence, and the bounded-cycle escalation path that now leaves a canonical review packet behind.
- Updated `README.md`, `docs/ARCHITECTURE.md`, the build board, the implementation plan, and the handoff note so repo-facing and build-agent-facing status now reflects that BA-02 is complete.

### Validation
- Ran `python3.11 -m pytest tests/test_supervisor.py` and confirmed all 13 supervisor tests passed.
- Ran `python3.11 -m pytest tests/test_bootstrap.py tests/test_schema.py tests/test_artifacts.py tests/test_supervisor.py` and confirmed all 22 targeted regression tests passed.

### Result
- `done`

### Next
- Implement `BA-03-S1`: materialize the product-side runtime pack under `ops/agent/` so the supervisor bootstrap acceptance surface exists before launchd and chat entrypoints are added.

### Notes
- Explicit implementation scope stayed bounded to canonical supervisor persistence and review artifacts; object-specific canonical state mutation helpers for later chat control slices are still downstream work.
- `BUILD-CLI-001` remains open and untouched.

### Session
- Date: 2026-04-06 14:21:43 MST
- Slice: BA-03-S1 runtime pack materialization
- Goal: Materialize the product-side `ops/agent/` runtime pack from current repo state so later launchd and chat entrypoints can reuse shared identity, policy, and control-model surfaces without rereading the full PRD each time.

### Work Done
- Added `job_hunt_copilot/runtime_pack.py` with product-side runtime-pack rendering for `identity.yaml`, `policies.yaml`, `action-catalog.yaml`, `service-goals.yaml`, `escalation-policy.yaml`, `chat-bootstrap.md`, and `supervisor-bootstrap.md`, driven by canonical paths, current supervisor constants, and the registered bounded action catalog.
- Added `scripts/ops/build_runtime_pack.py` as the repo-local CLI entrypoint for runtime-pack materialization, and extended `job_hunt_copilot/bootstrap.py` so a fresh bootstrap now seeds the runtime pack automatically.
- Extended `job_hunt_copilot/paths.py` with explicit `ops/agent`, `ops/logs`, launchd, script, and future helper-entrypoint paths so the generated runtime pack can render absolute project-root references cleanly.
- Added focused bootstrap and runtime-pack tests covering generated artifact existence, absolute-path rendering, current registered action-catalog contents, and preservation of existing `ops/agent/progress-log.md` plus `ops/agent/ops-plan.yaml` on rerender.
- Updated `.gitignore`, `README.md`, and `docs/ARCHITECTURE.md` so the repo now treats `ops/logs/` and the bootstrap-generated `ops/agent/` surfaces honestly as local runtime artifacts while still documenting that the runtime pack now exists.

### Validation
- Ran `python3.11 -m pytest tests/test_bootstrap.py tests/test_runtime_pack.py` and confirmed all 5 targeted tests passed.
- Ran `python3.11 -m pytest tests/test_bootstrap.py tests/test_schema.py tests/test_artifacts.py tests/test_supervisor.py tests/test_runtime_pack.py` and confirmed all 24 targeted regression tests passed.
- Ran `python3.11 scripts/ops/build_runtime_pack.py --project-root /Users/achyutaramsonti/Projects/job-hunt-copilot-v4` and confirmed the real repo rendered the full `ops/agent/` artifact set with `agent_mode = stopped` and `latest_cycle_result = not_started`.
- Ran `python3.11 -m job_hunt_copilot.bootstrap --project-root /Users/achyutaramsonti/Projects/job-hunt-copilot-v4` and confirmed real-repo bootstrap still succeeds, preserves the generated `progress-log.md` and `ops-plan.yaml`, and now creates `ops/logs/`.

### Result
- `done`

### Next
- Implement `BA-03-S2`: render the supervisor plist plus repo-local `jhc-agent-start`, `jhc-agent-stop`, and `jhc-agent-cycle` wrappers that consume the generated runtime pack and persist canonical control-state transitions around `launchctl`.

### Notes
- The generated `ops/agent/` files are intentionally ignored by git as runtime-local artifacts, so the tracked deliverable for this slice is the materialization code, tests, and bootstrap integration rather than checked-in rendered copies.
- The current action catalog remains intentionally narrow to the already-implemented supervisor behaviors; unsupported later-stage work still escalates instead of being overstated in the generated runtime pack.
- `BUILD-CLI-001` remains open and untouched.

### Session
- Date: 2026-04-06 14:44:45 MST
- Slice: BA-03-S2 launchd and helper entrypoints
- Goal: Render the supervisor plist plus repo-local `jhc-agent-start`, `jhc-agent-stop`, and `jhc-agent-cycle` wrappers that consume the generated runtime pack and persist canonical control-state transitions around `launchctl`.

### Work Done
- Added `job_hunt_copilot/local_runtime.py` with product-side helpers for supervisor plist rendering, canonical SQLite control-state mutation, and one-shot supervisor heartbeat execution.
- Added `scripts/ops/materialize_supervisor_plist.py`, `scripts/ops/control_agent.py`, and `scripts/ops/run_supervisor_cycle.py` so the product runtime has real CLI entrypoints for plist materialization, control-state writes, and launchd-facing cycle execution.
- Added repo-local `bin/jhc-agent-start`, `bin/jhc-agent-stop`, and `bin/jhc-agent-cycle` wrappers that resolve the absolute project root, render the runtime pack and plist, persist control-state transitions, and wire the local supervisor through `launchctl`.
- Tightened `jhc-agent-start` honesty after live smoke testing exposed a false-running-state bug: failed bootstrap attempts now boot out any partial load and roll canonical control state back to `stopped` instead of leaving the DB claiming the supervisor is active.
- Updated `job_hunt_copilot/runtime_pack.py`, `README.md`, and `docs/ARCHITECTURE.md` so the generated operator surfaces and recruiter-facing docs reflect that launchd plus start/stop/cycle wiring now exists while `jhc-chat` remains the next slice.
- Updated the build board and implementation plan to mark `BA-03-S2` complete in code, advance focus to `BA-03-S3`, and record the remaining live-launchd blocker explicitly.

### Validation
- Ran `python3.11 -m pytest tests/test_local_runtime.py tests/test_runtime_pack.py tests/test_supervisor.py` and confirmed all 18 targeted tests passed.
- Ran `python3.11 -m pytest tests/test_bootstrap.py tests/test_schema.py tests/test_artifacts.py tests/test_supervisor.py tests/test_runtime_pack.py tests/test_local_runtime.py` and confirmed all 28 targeted regression tests passed.
- Ran `python3.11 scripts/ops/materialize_supervisor_plist.py --project-root /Users/achyutaramsonti/Projects/job-hunt-copilot-v4` and confirmed the real repo rendered `ops/launchd/job-hunt-copilot-supervisor.plist`.
- Ran `plutil -p /Users/achyutaramsonti/Projects/job-hunt-copilot-v4/ops/launchd/job-hunt-copilot-supervisor.plist` and confirmed the rendered plist uses `Label = com.jobhuntcopilot.supervisor`, `RunAtLoad = true`, `StartInterval = 180`, `KeepAlive = false`, the absolute project-root working directory, the repo-local `bin/jhc-agent-cycle` program argument, and dedicated `ops/logs/` stdout or stderr paths.
- Ran `bin/jhc-agent-cycle` on the real repo and confirmed the wrapper executes `scripts/ops/run_supervisor_cycle.py`, records a canonical `launchd_heartbeat` cycle, and refreshes the ignored `ops/agent/` runtime pack surfaces.
- Ran live `bin/jhc-agent-start`; `launchctl bootstrap gui/$UID ...` still returned `Bootstrap failed: 5: Input/output error` in this sandboxed session, but follow-up `scripts/ops/control_agent.py status` plus `launchctl print gui/$UID/com.jobhuntcopilot.supervisor` confirmed the failed-start rollback now leaves `agent_mode = stopped` with no loaded launchd job.
- Ran `bin/jhc-agent-stop` and confirmed the stop path succeeds idempotently while the job is unloaded.

### Result
- `done`

### Next
- Implement `BA-03-S3`: add the direct `jhc-chat` operator wrapper with session begin or end bookkeeping, startup read surfaces, and pause-on-chat wiring through canonical control state.

### Notes
- Explicit blocker recorded as `OPS-LAUNCHD-001`: successful host-side `launchctl bootstrap` still needs follow-up validation outside the current sandboxed session because deeper launchd logging is sandbox-blocked here.
- `BUILD-CLI-001` remains open and untouched.

### Session
- Date: 2026-04-06 15:06:08 MST
- Slice: BA-03-S3 `jhc-chat` operator bootstrap
- Goal: Add the direct repo-local `jhc-chat` entrypoint with canonical chat session begin/end bookkeeping, pause-on-chat control-state wiring, and clean-close safe resume behavior.

### Work Done
- Extended `job_hunt_copilot.supervisor` control defaults and `job_hunt_copilot.local_runtime` so product-side chat sessions now persist `active_chat_session_id`, last chat begin/end metadata, and a clean-close auto-resume gate in canonical control state.
- Added `scripts/ops/chat_session.py` and repo-local `bin/jhc-chat`, wiring the wrapper to record session begin before launching Codex with `ops/agent/chat-bootstrap.md`, then record either `explicit_close` or `unexpected_exit` during cleanup.
- Implemented pause-on-chat semantics so opening `jhc-chat` immediately pauses a running supervisor with `pause_reason = expert_interaction`, while explicit close resumes only when chat itself caused that pause and pre-existing non-chat pauses remain untouched.
- Added `ops/logs/chat-sessions.jsonl` event logging, updated runtime-pack messaging from “chat pending” to “chat implemented with later idle-timeout follow-up”, and refreshed the repo-facing docs so BA-03 is represented honestly.
- Updated the build board and implementation plan to mark BA-03 complete, move the active focus to BA-04-S1, and keep the product launchd validation blocker explicit.

### Validation
- Ran `python3.11 -m pytest tests/test_local_runtime.py` and confirmed all 7 local-runtime tests passed, including the new chat session lifecycle coverage.
- Ran `python3.11 -m pytest tests/test_bootstrap.py tests/test_schema.py tests/test_artifacts.py tests/test_supervisor.py tests/test_runtime_pack.py tests/test_local_runtime.py` and confirmed all 31 targeted regression tests passed.
- Ran `env JHC_CODEX_BIN=/usr/bin/true bin/jhc-chat` on the real repo to exercise the shell wrapper, session begin/end scripts, and cleanup path without opening an interactive Codex UI.
- Ran `python3.11 scripts/ops/control_agent.py status --project-root /Users/achyutaramsonti/Projects/job-hunt-copilot-v4` after the wrapper smoke and confirmed `agent_mode = stopped`, `active_chat_session_id = ""`, and `last_chat_exit_mode = explicit_close`.

### Result
- `done`

### Next
- Implement `BA-04-S1`: add the bounded paste-inbox and manual capture bundle persistence path that writes canonical lead workspaces with `capture-bundle.json` and `raw/source.md`.

### Notes
- Explicit follow-up remains: unexpected `jhc-chat` exit is now persisted canonically but intentionally stays paused until a later idle-timeout helper or an explicit resume clears it.
- `OPS-LAUNCHD-001` remains open for host-side launchd load validation outside this sandboxed session.
- `BUILD-CLI-001` remains open and untouched.

### Session
- Date: 2026-04-06 15:28:43 MST
- Slice: BA-04-S1 paste inbox and manual capture bundle persistence
- Goal: Land the bounded manual-ingestion entrypoint that turns `paste/paste.txt` or browser-style manual capture bundles into canonical lead workspaces with preserved raw evidence.

### Work Done
- Added `job_hunt_copilot.linkedin_scraping` with manual submission validation, exact-copy paste fallback ingestion, browser-style capture-bundle ingestion, deterministic manual-source assembly, canonical `linkedin_leads` shell-row creation, and `lead_raw_source` artifact registration.
- Extended `job_hunt_copilot.paths` with explicit helpers for lead raw directories, `raw/source.md`, `capture-bundle.json`, and future lead history paths so later manual and Gmail slices can reuse the same workspace conventions.
- Added `scripts/linkedin_scraping/ingest_manual_capture.py` plus repo-local `bin/jhc-linkedin-ingest` as the current local upstream receiver entrypoint for `paste` and `capture-bundle` ingestion modes.
- Added `tests/test_linkedin_scraping.py` to cover paste raw-source copying, idempotent repeated paste ingestion, selected-text preservation inside capture artifacts, and the selected-text-versus-tray-review submission-path default.
- Updated `README.md` and `docs/ARCHITECTURE.md` so the repo-facing surfaces now reflect that manual lead ingestion exists while split/review and downstream materialization still remain future slices.
- Updated the build board and implementation plan to mark `BA-04-S1` complete, advance the active focus to `BA-04-S2`, and record the explicit pre-split `split_review_status = not_started` inference.

### Validation
- Ran `python3.11 -m pytest tests/test_linkedin_scraping.py` and confirmed all 4 ingestion tests passed.
- Ran `python3.11 -m pytest tests/test_bootstrap.py tests/test_artifacts.py tests/test_linkedin_scraping.py` and confirmed all 11 targeted regression tests passed.
- Ran full `python3.11 -m pytest` and confirmed all 35 tests passed across bootstrap, schema, artifacts, local runtime, runtime pack, supervisor, and the new ingestion slice.
- Ran `bin/jhc-linkedin-ingest --help` and confirmed the repo-local wrapper resolves the new manual-ingestion CLI correctly after adding the same repo-root import bootstrap used by the existing `scripts/ops/` entrypoints.

### Result
- `done`

### Next
- Implement `BA-04-S2`: deterministic rule-based split and review over canonical manual `raw/source.md`, with `source-split.yaml`, `source-split-review.yaml`, blocked-when-ambiguous `lead-manifest.yaml`, and `artifact_records` registration for those artifacts.

### Notes
- Explicit implementation inference: the spec names post-split review states but does not define a canonical pre-split placeholder, so this slice uses `split_review_status = not_started` for newly captured manual leads until `BA-04-S2` publishes the first deterministic split result.
- Paste fallback now converges into the same persisted `capture-bundle.json` contract as browser-style manual capture, but it still copies the inbox bytes unchanged into canonical `raw/source.md` per the acceptance requirement.
- `OPS-LAUNCHD-001` and `BUILD-CLI-001` remain open and untouched because this slice stayed within ingestion ownership.
