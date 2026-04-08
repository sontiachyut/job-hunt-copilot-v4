# BA-10 Blocker Audit

- Acceptance scenarios: `214`
- Open acceptance scenarios: `22`
- Open acceptance gap clusters: `5`
- Open build-board blockers: `3`
- Blockers with missing evidence refs: `0`

## Current Focus

- Epic: `BA-10`
- Slice: `BA-10-S4`
- Owner role: `build-lead`
- Reason: BA-10-S3 now has a committed blocker audit and fresh validation evidence, while the matrix still sits at 190 implemented / 8 partial / 14 gap scenarios; the next highest-value slice is a build-lead implementation pass on downstream supervisor action-catalog steps beyond `lead_handoff`, because that single cluster accounts for the largest remaining acceptance partial set and blocks the strongest end-to-end closure.

## Acceptance Gap Clusters

### BA10_SUPERVISOR_DOWNSTREAM_ACTION_CATALOG: Supervisor orchestration still stops at lead handoff
- Next slice: `BA-10-S3`
- Owner roles: `build-lead`, `quality-engineer`
- Rules: `Current-build orchestration remains sequential`, `End-to-end acceptance`, `Supervisor Agent behavior`
- Epics: `BA-02`, `BA-03`, `BA-06`, `BA-07`, `BA-08`, `BA-09`, `BA-10`
- Open scenarios: `5` (`partial`: `5`, `gap`: `0`)
- Reason: The durable heartbeat, selector ordering, and retry-safe run persistence exist, but the registered action catalog still only advances autonomous work through `lead_handoff`; later stages reselect the same durable run and escalate instead of executing.
- Evidence summary: Selector ordering, durable run reuse, and unsupported-stage escalation are covered, but later-stage autonomous actions remain unregistered.
- Evidence code refs: `job_hunt_copilot/supervisor.py`, `job_hunt_copilot/local_runtime.py`, `job_hunt_copilot/runtime_pack.py`
- Evidence test refs: `tests/test_supervisor.py`, `tests/test_acceptance_traceability.py`
- Confirmation commands:
  - `python3.11 -m pytest tests/test_supervisor.py` (automated: Confirms durable run reuse, unsupported-stage escalation, and retry-safe review-packet behavior.)
  - `python3.11 -m pytest tests/test_acceptance_traceability.py tests/test_blocker_audit.py` (automated: Keeps the committed BA-10 acceptance and blocker reports synchronized with repo code, tests, and state references.)
- Open scenarios:
  - `[partial]` Supervisor work selection follows the current default priority order
  - `[partial]` Role-targeted orchestration follows the current dependency order
  - `[partial]` General learning outreach bypasses the role-targeted agent-review requirement
  - `[partial]` Role-targeted flow completes from LinkedIn Scraping through delivery feedback
  - `[partial]` End-to-end retry resumes from the last successful stage boundary

### BA10_MAINTENANCE_AUTOMATION: Maintenance workflow and artifacts are not implemented
- Next slice: `BA-10-S3`
- Owner roles: `build-lead`
- Rules: `Machine handoff contracts and canonical state`, `Supervisor Agent behavior`
- Epics: `BA-01`, `BA-02`, `BA-03`, `BA-04`, `BA-06`, `BA-07`, `BA-08`, `BA-09`
- Open scenarios: `5` (`partial`: `0`, `gap`: `5`)
- Reason: The schema and runtime pack reserve maintenance surfaces, but there is no autonomous maintenance batch workflow, no maintenance artifacts, and no maintenance review flow yet.
- Evidence summary: Schema and runtime scaffolding reserve maintenance surfaces, but there is still no maintenance module, runner, or review-artifact workflow.
- Evidence code refs: `job_hunt_copilot/migrations/0002_canonical_schema.sql`, `job_hunt_copilot/paths.py`, `job_hunt_copilot/runtime_pack.py`
- Evidence test refs: `tests/test_schema.py`, `tests/test_runtime_pack.py`, `tests/test_acceptance_traceability.py`
- Confirmation commands:
  - `python3.11 -m pytest tests/test_runtime_pack.py` (automated: Confirms generated runtime scaffolding stays honest about current action-catalog and maintenance placeholder status.)
  - `python3.11 -m pytest tests/test_acceptance_traceability.py tests/test_blocker_audit.py` (automated: Keeps the committed BA-10 acceptance and blocker reports synchronized with repo code, tests, and state references.)
- Open scenarios:
  - `[gap]` Maintenance change artifacts exist for every autonomous maintenance batch
  - `[gap]` Daily maintenance is mandatory, bounded, and run-boundary aware
  - `[gap]` Maintenance changes follow the current git and approval workflow
  - `[gap]` Proper maintenance validation requires both change-scoped and full-project testing
  - `[gap]` Failed or unapproved maintenance batches remain reviewable

### BA10_CHAT_REVIEW_AND_CONTROL: Chat review and control remain wrapper-only
- Next slice: `BA-10-S3`
- Owner roles: `build-lead`, `quality-engineer`
- Rules: `Review surfaces and chat-based control`, `Supervisor Agent behavior`
- Epics: `BA-02`, `BA-03`, `BA-09`
- Open scenarios: `10` (`partial`: `2`, `gap`: `8`)
- Reason: The direct `jhc-chat` entrypoint manages chat session lifecycle, but richer review retrieval, control routing, and expert-guidance behaviors are not yet implemented in the chat surface.
- Evidence summary: Chat lifecycle, review-query reads, and bootstrap scaffolding exist, but chat itself still does not retrieve grouped reviews or route control decisions.
- Evidence code refs: `scripts/ops/chat_session.py`, `job_hunt_copilot/local_runtime.py`, `job_hunt_copilot/review_queries.py`, `job_hunt_copilot/runtime_pack.py`
- Evidence test refs: `tests/test_local_runtime.py`, `tests/test_review_queries.py`, `tests/test_runtime_pack.py`, `tests/test_acceptance_traceability.py`
- Confirmation commands:
  - `python3.11 -m pytest tests/test_local_runtime.py` (automated: Covers launchd plist wiring, control commands, chat lifecycle state, delayed feedback runners, and explicit negative control cases.)
  - `python3.11 -m pytest tests/test_review_queries.py` (automated: Verifies persisted grouped review surfaces and traceability reads that back the chat/review boundary.)
  - `python3.11 -m pytest tests/test_runtime_pack.py` (automated: Confirms generated runtime scaffolding stays honest about current action-catalog and maintenance placeholder status.)
  - `python3.11 -m pytest tests/test_acceptance_traceability.py tests/test_blocker_audit.py` (automated: Keeps the committed BA-10 acceptance and blocker reports synchronized with repo code, tests, and state references.)
- Open scenarios:
  - `[partial]` jhc-chat startup dashboard is detailed, bounded, and clean-first
  - `[gap]` Startup dashboard runtime metrics count only active autonomous execution
  - `[partial]` Review retrieval is grouped, compact-first, and newest-first within each group
  - `[gap]` jhc-chat uses persisted state for answers and control routing
  - `[gap]` Default change summaries cover activity since the last completed expert review
  - `[gap]` Expert guidance becomes live immediately but conflicting or uncertain reuse asks first
  - `[gap]` Conflicting expert guidance pauses the whole autonomous system
  - `[gap]` Expert-requested background tasks require explicit handoff summary and exclusive focus
  - `[gap]` Expert-requested background task outcomes return to review appropriately
  - `[gap]` AI agent surfaces the current review queue in chat

### BA10_CHAT_IDLE_TIMEOUT_RESUME: Idle-timeout resume is still backlog
- Next slice: `BA-10-S3`
- Owner roles: `build-lead`
- Rules: `Supervisor Agent behavior`
- Epics: `BA-02`, `BA-03`
- Open scenarios: `1` (`partial`: `1`, `gap`: `0`)
- Reason: Explicit-close and explicit-resume paths exist, but unexpected `jhc-chat` exits still require a later explicit resume because automatic idle-timeout recovery is not implemented.
- Evidence summary: Unexpected chat exit is recorded and a later explicit resume works, but no automatic idle-timeout resume helper exists.
- Evidence code refs: `job_hunt_copilot/local_runtime.py`, `job_hunt_copilot/runtime_pack.py`
- Evidence test refs: `tests/test_local_runtime.py`, `tests/test_runtime_pack.py`, `tests/test_acceptance_traceability.py`
- Confirmation commands:
  - `python3.11 -m pytest tests/test_local_runtime.py` (automated: Covers launchd plist wiring, control commands, chat lifecycle state, delayed feedback runners, and explicit negative control cases.)
  - `python3.11 -m pytest tests/test_runtime_pack.py` (automated: Confirms generated runtime scaffolding stays honest about current action-catalog and maintenance placeholder status.)
  - `python3.11 -m pytest tests/test_acceptance_traceability.py tests/test_blocker_audit.py` (automated: Keeps the committed BA-10 acceptance and blocker reports synchronized with repo code, tests, and state references.)
- Open scenarios:
  - `[partial]` Expert-interaction resume follows explicit close, explicit resume, or safe idle timeout

### BA10_POSTING_ABANDON_CONTROL: Posting-abandon control surface is missing
- Next slice: `BA-10-S3`
- Owner roles: `build-lead`
- Rules: `Current-build orchestration remains sequential`
- Epics: `BA-06`, `BA-07`, `BA-08`, `BA-09`
- Open scenarios: `1` (`partial`: `0`, `gap`: `1`)
- Reason: There is no explicit user-facing or runtime control path that abandons a posting from arbitrary active orchestration states while preserving canonical history.
- Evidence summary: Agent-level start/stop/pause/resume/replan controls exist, but there is still no posting-scoped abandon command or runtime mutation path.
- Evidence code refs: `scripts/ops/control_agent.py`, `job_hunt_copilot/local_runtime.py`, `job_hunt_copilot/supervisor.py`
- Evidence test refs: `tests/test_local_runtime.py`, `tests/test_acceptance_traceability.py`
- Confirmation commands:
  - `python3.11 -m pytest tests/test_local_runtime.py` (automated: Covers launchd plist wiring, control commands, chat lifecycle state, delayed feedback runners, and explicit negative control cases.)
  - `python3.11 -m pytest tests/test_acceptance_traceability.py tests/test_blocker_audit.py` (automated: Keeps the committed BA-10 acceptance and blocker reports synchronized with repo code, tests, and state references.)
- Open scenarios:
  - `[gap]` The user may explicitly abandon a posting from any active orchestration state

## Build-Board Blockers

### BA10-TRACE-001
- Status: `open`
- Severity: `high`
- Owner role: `quality-engineer`
- Summary: The regenerated BA-10 trace matrix now reports 190 implemented / 8 partial / 14 gap scenarios; the remaining downstream-supervisor, chat, maintenance, and posting-abandon gaps now each carry explicit evidence refs and reproducible blocker notes, but the missing current-build behaviors themselves remain open.
- Impact: Acceptance signoff is more credible now that committed smoke coverage, blocker-specific evidence refs, and explicit negative regressions exist, but BA-10 still cannot close until the remaining gap clusters are actually burned down or deliberately left open.
- Next action: Hand the next functional slice to the build-lead: downstream action-catalog burn-down beyond `lead_handoff` or a posting-abandon control implementation. Maintenance automation remains an explicit follow-up gap after those runtime-control surfaces.
- Evidence refs: `build-agent/reports/ba-10-acceptance-trace-matrix.json`, `build-agent/reports/ba-10-acceptance-trace-matrix.md`, `build-agent/reports/ba-10-blocker-audit.json`, `build-agent/reports/ba-10-blocker-audit.md`, `job_hunt_copilot/quality_validation.py`, `scripts/quality/generate_blocker_audit.py`, `scripts/quality/run_ba10_validation_suite.py`, `scripts/ops/control_agent.py`, `tests/test_acceptance_traceability.py`, `tests/test_blocker_audit.py`, `tests/test_local_runtime.py`, `tests/test_quality_validation.py`, `tests/test_delivery_feedback.py`, `tests/test_schema.py`, `tests/test_smoke_harness.py`, `tests/test_supervisor.py`, `tests/test_runtime_pack.py`, `tests/test_resume_tailoring.py`, `tests/test_outreach.py`, `tests/test_review_queries.py`
- Confirmation commands:
  - `python3.11 -m pytest tests/test_acceptance_traceability.py tests/test_blocker_audit.py` (automated: Keeps the committed BA-10 acceptance and blocker reports synchronized with repo code, tests, and state references.)
  - `python3.11 -m pytest tests/test_smoke_harness.py` (automated: Replays the committed bootstrap -> tailoring -> discovery -> send -> feedback -> review-query smoke path.)
  - `python3.11 -m pytest tests/test_supervisor.py` (automated: Confirms durable run reuse, unsupported-stage escalation, and retry-safe review-packet behavior.)
  - `python3.11 -m pytest tests/test_local_runtime.py` (automated: Covers launchd plist wiring, control commands, chat lifecycle state, delayed feedback runners, and explicit negative control cases.)
  - `python3.11 -m pytest tests/test_review_queries.py` (automated: Verifies persisted grouped review surfaces and traceability reads that back the chat/review boundary.)
  - `python3.11 -m pytest tests/test_runtime_pack.py` (automated: Confirms generated runtime scaffolding stays honest about current action-catalog and maintenance placeholder status.)

### BUILD-CLI-001
- Status: `open`
- Severity: `medium`
- Owner role: `build-lead`
- Summary: `codex exec` no longer accepts `--ask-for-approval`, and unattended build-cycle logs show BA-00 sessions failing before work starts when that flag is present.
- Impact: Unattended build sessions can fail before any implementation work starts if the CLI compatibility fix regresses.
- Next action: Re-run the unattended build-lead wrapper on the host and confirm it starts a real cycle without passing unsupported approval flags.
- Evidence refs: `build-agent/scripts/run_build_lead_cycle.py`, `build-agent/logs/cycles/build-cycle-20260406T034335Z-66be05af.log`
- Confirmation commands:
  - `codex exec --help && codex --help` (manual_local: Reconfirms the current CLI shape so unattended build wrappers do not reintroduce unsupported approval flags.)

### OPS-LAUNCHD-001
- Status: `open`
- Severity: `medium`
- Owner role: `build-lead`
- Summary: Live `launchctl bootstrap gui/$UID /Users/achyutaramsonti/Projects/job-hunt-copilot-v4/ops/launchd/job-hunt-copilot-supervisor.plist` still returns `Input/output error` in the current sandboxed session, so successful host-side launchd load validation remains pending for both the supervisor and delayed-feedback jobs even though their plists, wrappers, runners, and failed-start rollback validate locally.
- Impact: Product-side background launchd startup is not yet verified outside the sandbox even though the repo-local helper code and rollback behavior are working.
- Next action: Run `bin/jhc-agent-start` on the host outside the sandbox, then inspect `launchctl print gui/$UID/com.jobhuntcopilot.supervisor` and system launchd logs to capture the real bootstrap outcome.
- Evidence refs: `build-agent/logs/cycles/build-cycle-20260407T213533Z-5b2c1d98.log`, `bin/jhc-agent-start`, `bin/jhc-feedback-sync-cycle`, `scripts/ops/materialize_supervisor_plist.py`, `scripts/ops/materialize_feedback_sync_plist.py`, `tests/test_local_runtime.py`
- Confirmation commands:
  - `python3.11 -m pytest tests/test_local_runtime.py` (automated: Covers launchd plist wiring, control commands, chat lifecycle state, delayed feedback runners, and explicit negative control cases.)
  - `bin/jhc-agent-start && launchctl print gui/$UID/com.jobhuntcopilot.supervisor` (manual_host: Must run outside the sandbox to validate real host launchd bootstrap behavior and collect diagnostic output.)
