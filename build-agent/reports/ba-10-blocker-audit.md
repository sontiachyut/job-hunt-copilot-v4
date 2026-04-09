# BA-10 Blocker Audit

- Acceptance scenarios: `214`
- Open acceptance scenarios: `15`
- Open acceptance gap clusters: `3`
- Open build-board blockers: `3`
- Blockers with missing evidence refs: `0`

## Current Focus

- Epic: `BA-10`
- Slice: `BA-10-S3`
- Owner role: `quality-engineer`
- Reason: BA-10-S4 closed the downstream supervisor action-catalog gap and the latest BA-10-S3 hardening pass burned down the `jhc-chat` startup dashboard plus active-runtime-metrics scenarios; this cycle also closed the posting-abandon control gap, so the acceptance matrix now holds at 197 implemented / 3 partial / 12 gap scenarios with maintenance automation, richer chat review/control, and idle-timeout resume still open BA-10-S3 work.
- Matching gap ids: `BA10_MAINTENANCE_AUTOMATION`, `BA10_CHAT_REVIEW_AND_CONTROL`, `BA10_CHAT_IDLE_TIMEOUT_RESUME`
- Validation suite: `python3.11 scripts/quality/run_ba10_validation_suite.py --project-root <repo_root> --current-focus`

## Acceptance Gap Clusters

### BA10_MAINTENANCE_AUTOMATION: Maintenance workflow and artifacts are not implemented
- Next slice: `BA-10-S3`
- Owner roles: `build-lead`
- Rules: `Machine handoff contracts and canonical state`, `Supervisor Agent behavior`
- Epics: `BA-01`, `BA-02`, `BA-03`, `BA-04`, `BA-06`, `BA-07`, `BA-08`, `BA-09`
- Supporting slices: `BA-01-S1`, `BA-01-S2`, `BA-01-S3`, `BA-02-S1`, `BA-02-S2`, `BA-02-S3`, `BA-04-S1`, `BA-04-S2`, `BA-04-S3`, `BA-04-S4`, `BA-06-S1`, `BA-06-S2`, `BA-06-S3`, `BA-06-S4`, `BA-07-S1`, `BA-07-S2`, `BA-07-S3`, `BA-08-S1`, `BA-08-S2`, `BA-08-S3`, `BA-09-S1`, `BA-09-S2`, `BA-09-S3`, `BA-03-S1`, `BA-03-S2`, `BA-03-S3`, `BA-10-S3`
- Open scenarios: `6` (`partial`: `1`, `gap`: `5`)
- Reason: The schema and runtime pack reserve maintenance surfaces, but there is no autonomous maintenance batch workflow, no maintenance artifacts, and no maintenance review flow yet.
- Evidence summary: Schema and runtime scaffolding reserve maintenance surfaces, but there is still no maintenance module, runner, or review-artifact workflow.
- Evidence code refs: `job_hunt_copilot/migrations/0002_canonical_schema.sql`, `job_hunt_copilot/paths.py`, `job_hunt_copilot/runtime_pack.py`
- Evidence test refs: `tests/test_schema.py`, `tests/test_runtime_pack.py`, `tests/test_acceptance_traceability.py`
- Validation suite: `python3.11 scripts/quality/run_ba10_validation_suite.py --project-root <repo_root> --gap-id BA10_MAINTENANCE_AUTOMATION`
- Confirmation commands:
  - `python3.11 -m pytest tests/test_runtime_pack.py` (automated: Confirms generated runtime scaffolding stays honest about current action-catalog and maintenance placeholder status.)
  - `python3.11 -m pytest tests/test_acceptance_traceability.py tests/test_blocker_audit.py` (automated: Keeps the committed BA-10 acceptance and blocker reports synchronized with repo code, tests, and state references.)
  - `python3.11 -m pytest tests/test_supervisor_downstream_actions.py` (automated: Confirms incident-first selector ordering, existing-run reuse, bounded role-targeted progression through `delivery_feedback`, and contact-rooted general-learning follow-through while keeping the remaining maintenance-selector gap explicit.)
- Open scenarios:
  - `[gap]` Maintenance change artifacts exist for every autonomous maintenance batch (rule: `Machine handoff contracts and canonical state`, line: `220`)
    - Evidence refs: `job_hunt_copilot/artifacts.py`, `job_hunt_copilot/contracts.py`, `job_hunt_copilot/supervisor.py`, `job_hunt_copilot/linkedin_scraping.py`, `job_hunt_copilot/resume_tailoring.py`, `job_hunt_copilot/email_discovery.py`, `job_hunt_copilot/outreach.py`, `job_hunt_copilot/delivery_feedback.py`, `job_hunt_copilot/review_queries.py`, `tests/test_artifacts.py`, `tests/test_supervisor.py`, `tests/test_linkedin_scraping.py`, `tests/test_resume_tailoring.py`, `tests/test_email_discovery.py`, `tests/test_outreach.py`, `tests/test_delivery_feedback.py`, `tests/test_review_queries.py`
    - Note: Maintenance artifacts are specified in the schema and PRD, but no maintenance batch workflow writes them yet.
  - `[partial]` Supervisor work selection follows the current default priority order (rule: `Supervisor Agent behavior`, line: `1132`)
    - Evidence refs: `job_hunt_copilot/chat_runtime.py`, `job_hunt_copilot/supervisor.py`, `job_hunt_copilot/local_runtime.py`, `job_hunt_copilot/runtime_pack.py`, `scripts/ops/run_supervisor_cycle.py`, `scripts/ops/control_agent.py`, `scripts/ops/chat_session.py`, `bin/jhc-agent-start`, `bin/jhc-agent-stop`, `bin/jhc-agent-cycle`, `bin/jhc-chat`, `tests/test_supervisor_downstream_actions.py`, `tests/test_supervisor.py`, `tests/test_local_runtime.py`, `tests/test_runtime_pack.py`
    - Note: Current supervisor regressions prove open incidents outrank ordinary pipeline advancement, existing runs outrank new posting bootstrap, new postings outrank opportunistic contact-rooted general-learning work, and contact-rooted general-learning work now covers bounded delayed feedback, send-ready dispatch, and email discovery, but bounded maintenance work itself still has no dedicated selector or action path.
  - `[gap]` Daily maintenance is mandatory, bounded, and run-boundary aware (rule: `Supervisor Agent behavior`, line: `1322`)
    - Evidence refs: `job_hunt_copilot/chat_runtime.py`, `job_hunt_copilot/supervisor.py`, `job_hunt_copilot/local_runtime.py`, `job_hunt_copilot/runtime_pack.py`, `scripts/ops/run_supervisor_cycle.py`, `scripts/ops/control_agent.py`, `scripts/ops/chat_session.py`, `bin/jhc-agent-start`, `bin/jhc-agent-stop`, `bin/jhc-agent-cycle`, `bin/jhc-chat`, `tests/test_supervisor_downstream_actions.py`, `tests/test_supervisor.py`, `tests/test_local_runtime.py`, `tests/test_runtime_pack.py`
    - Note: Only maintenance placeholders exist today; the maintenance workflow itself is still missing.
  - `[gap]` Maintenance changes follow the current git and approval workflow (rule: `Supervisor Agent behavior`, line: `1331`)
    - Evidence refs: `job_hunt_copilot/chat_runtime.py`, `job_hunt_copilot/supervisor.py`, `job_hunt_copilot/local_runtime.py`, `job_hunt_copilot/runtime_pack.py`, `scripts/ops/run_supervisor_cycle.py`, `scripts/ops/control_agent.py`, `scripts/ops/chat_session.py`, `bin/jhc-agent-start`, `bin/jhc-agent-stop`, `bin/jhc-agent-cycle`, `bin/jhc-chat`, `tests/test_supervisor_downstream_actions.py`, `tests/test_supervisor.py`, `tests/test_local_runtime.py`, `tests/test_runtime_pack.py`
    - Note: Only maintenance placeholders exist today; the maintenance workflow itself is still missing.
  - `[gap]` Proper maintenance validation requires both change-scoped and full-project testing (rule: `Supervisor Agent behavior`, line: `1342`)
    - Evidence refs: `job_hunt_copilot/chat_runtime.py`, `job_hunt_copilot/supervisor.py`, `job_hunt_copilot/local_runtime.py`, `job_hunt_copilot/runtime_pack.py`, `scripts/ops/run_supervisor_cycle.py`, `scripts/ops/control_agent.py`, `scripts/ops/chat_session.py`, `bin/jhc-agent-start`, `bin/jhc-agent-stop`, `bin/jhc-agent-cycle`, `bin/jhc-chat`, `tests/test_supervisor_downstream_actions.py`, `tests/test_supervisor.py`, `tests/test_local_runtime.py`, `tests/test_runtime_pack.py`
    - Note: Only maintenance placeholders exist today; the maintenance workflow itself is still missing.
  - `[gap]` Failed or unapproved maintenance batches remain reviewable (rule: `Supervisor Agent behavior`, line: `1349`)
    - Evidence refs: `job_hunt_copilot/chat_runtime.py`, `job_hunt_copilot/supervisor.py`, `job_hunt_copilot/local_runtime.py`, `job_hunt_copilot/runtime_pack.py`, `scripts/ops/run_supervisor_cycle.py`, `scripts/ops/control_agent.py`, `scripts/ops/chat_session.py`, `bin/jhc-agent-start`, `bin/jhc-agent-stop`, `bin/jhc-agent-cycle`, `bin/jhc-chat`, `tests/test_supervisor_downstream_actions.py`, `tests/test_supervisor.py`, `tests/test_local_runtime.py`, `tests/test_runtime_pack.py`
    - Note: Only maintenance placeholders exist today; the maintenance workflow itself is still missing.

### BA10_CHAT_REVIEW_AND_CONTROL: Chat review and control remain wrapper-only
- Next slice: `BA-10-S3`
- Owner roles: `build-lead`, `quality-engineer`
- Rules: `Review surfaces and chat-based control`, `Supervisor Agent behavior`
- Epics: `BA-02`, `BA-03`, `BA-09`
- Supporting slices: `BA-02-S1`, `BA-02-S2`, `BA-02-S3`, `BA-03-S1`, `BA-03-S2`, `BA-03-S3`, `BA-09-S1`, `BA-09-S2`, `BA-09-S3`, `BA-10-S3`
- Open scenarios: `8` (`partial`: `1`, `gap`: `7`)
- Reason: The direct `jhc-chat` entrypoint manages chat session lifecycle, but richer review retrieval, control routing, and expert-guidance behaviors are not yet implemented in the chat surface.
- Evidence summary: Chat lifecycle, a persisted startup dashboard, and a grouped review-queue snapshot now exist, but chat itself still does not route control decisions, default change summaries, or expert-guidance workflows.
- Evidence code refs: `job_hunt_copilot/chat_runtime.py`, `scripts/ops/chat_session.py`, `job_hunt_copilot/local_runtime.py`, `job_hunt_copilot/review_queries.py`, `job_hunt_copilot/runtime_pack.py`
- Evidence test refs: `tests/test_local_runtime.py`, `tests/test_review_queries.py`, `tests/test_runtime_pack.py`, `tests/test_acceptance_traceability.py`
- Validation suite: `python3.11 scripts/quality/run_ba10_validation_suite.py --project-root <repo_root> --gap-id BA10_CHAT_REVIEW_AND_CONTROL`
- Confirmation commands:
  - `python3.11 -m pytest tests/test_local_runtime.py` (automated: Covers launchd plist wiring, control commands, chat lifecycle state, delayed feedback runners, and explicit negative control cases.)
  - `python3.11 -m pytest tests/test_review_queries.py` (automated: Verifies persisted grouped review surfaces and traceability reads that back the chat/review boundary.)
  - `python3.11 -m pytest tests/test_runtime_pack.py` (automated: Confirms generated runtime scaffolding stays honest about current action-catalog and maintenance placeholder status.)
  - `python3.11 -m pytest tests/test_acceptance_traceability.py tests/test_blocker_audit.py` (automated: Keeps the committed BA-10 acceptance and blocker reports synchronized with repo code, tests, and state references.)
- Open scenarios:
  - `[partial]` Review retrieval is grouped, compact-first, and newest-first within each group (rule: `Supervisor Agent behavior`, line: `1233`)
    - Evidence refs: `job_hunt_copilot/chat_runtime.py`, `job_hunt_copilot/supervisor.py`, `job_hunt_copilot/local_runtime.py`, `job_hunt_copilot/runtime_pack.py`, `scripts/ops/run_supervisor_cycle.py`, `scripts/ops/control_agent.py`, `scripts/ops/chat_session.py`, `bin/jhc-agent-start`, `bin/jhc-agent-stop`, `bin/jhc-agent-cycle`, `bin/jhc-chat`, `tests/test_supervisor_downstream_actions.py`, `tests/test_supervisor.py`, `tests/test_local_runtime.py`, `tests/test_runtime_pack.py`
    - Note: The generated chat startup briefing now includes a grouped compact review-queue snapshot ordered by pending expert review packets, failed expert-requested background tasks, maintenance batches, and open incidents, but explicit chat-time retrieval and deeper control routing are still incomplete.
  - `[gap]` jhc-chat uses persisted state for answers and control routing (rule: `Supervisor Agent behavior`, line: `1249`)
    - Evidence refs: `job_hunt_copilot/chat_runtime.py`, `job_hunt_copilot/supervisor.py`, `job_hunt_copilot/local_runtime.py`, `job_hunt_copilot/runtime_pack.py`, `scripts/ops/run_supervisor_cycle.py`, `scripts/ops/control_agent.py`, `scripts/ops/chat_session.py`, `bin/jhc-agent-start`, `bin/jhc-agent-stop`, `bin/jhc-agent-cycle`, `bin/jhc-chat`, `tests/test_supervisor_downstream_actions.py`, `tests/test_supervisor.py`, `tests/test_local_runtime.py`, `tests/test_runtime_pack.py`
    - Note: The direct `jhc-chat` wrapper now prints a persisted startup dashboard plus grouped review snapshot, but explicit chat-side review retrieval, control routing, change summaries, and expert-guidance behaviors are still missing.
  - `[gap]` Default change summaries cover activity since the last completed expert review (rule: `Supervisor Agent behavior`, line: `1267`)
    - Evidence refs: `job_hunt_copilot/chat_runtime.py`, `job_hunt_copilot/supervisor.py`, `job_hunt_copilot/local_runtime.py`, `job_hunt_copilot/runtime_pack.py`, `scripts/ops/run_supervisor_cycle.py`, `scripts/ops/control_agent.py`, `scripts/ops/chat_session.py`, `bin/jhc-agent-start`, `bin/jhc-agent-stop`, `bin/jhc-agent-cycle`, `bin/jhc-chat`, `tests/test_supervisor_downstream_actions.py`, `tests/test_supervisor.py`, `tests/test_local_runtime.py`, `tests/test_runtime_pack.py`
    - Note: The direct `jhc-chat` wrapper now prints a persisted startup dashboard plus grouped review snapshot, but explicit chat-side review retrieval, control routing, change summaries, and expert-guidance behaviors are still missing.
  - `[gap]` Expert guidance becomes live immediately but conflicting or uncertain reuse asks first (rule: `Supervisor Agent behavior`, line: `1273`)
    - Evidence refs: `job_hunt_copilot/chat_runtime.py`, `job_hunt_copilot/supervisor.py`, `job_hunt_copilot/local_runtime.py`, `job_hunt_copilot/runtime_pack.py`, `scripts/ops/run_supervisor_cycle.py`, `scripts/ops/control_agent.py`, `scripts/ops/chat_session.py`, `bin/jhc-agent-start`, `bin/jhc-agent-stop`, `bin/jhc-agent-cycle`, `bin/jhc-chat`, `tests/test_supervisor_downstream_actions.py`, `tests/test_supervisor.py`, `tests/test_local_runtime.py`, `tests/test_runtime_pack.py`
    - Note: The direct `jhc-chat` wrapper now prints a persisted startup dashboard plus grouped review snapshot, but explicit chat-side review retrieval, control routing, change summaries, and expert-guidance behaviors are still missing.
  - `[gap]` Conflicting expert guidance pauses the whole autonomous system (rule: `Supervisor Agent behavior`, line: `1281`)
    - Evidence refs: `job_hunt_copilot/chat_runtime.py`, `job_hunt_copilot/supervisor.py`, `job_hunt_copilot/local_runtime.py`, `job_hunt_copilot/runtime_pack.py`, `scripts/ops/run_supervisor_cycle.py`, `scripts/ops/control_agent.py`, `scripts/ops/chat_session.py`, `bin/jhc-agent-start`, `bin/jhc-agent-stop`, `bin/jhc-agent-cycle`, `bin/jhc-chat`, `tests/test_supervisor_downstream_actions.py`, `tests/test_supervisor.py`, `tests/test_local_runtime.py`, `tests/test_runtime_pack.py`
    - Note: The direct `jhc-chat` wrapper now prints a persisted startup dashboard plus grouped review snapshot, but explicit chat-side review retrieval, control routing, change summaries, and expert-guidance behaviors are still missing.
  - `[gap]` Expert-requested background tasks require explicit handoff summary and exclusive focus (rule: `Supervisor Agent behavior`, line: `1307`)
    - Evidence refs: `job_hunt_copilot/chat_runtime.py`, `job_hunt_copilot/supervisor.py`, `job_hunt_copilot/local_runtime.py`, `job_hunt_copilot/runtime_pack.py`, `scripts/ops/run_supervisor_cycle.py`, `scripts/ops/control_agent.py`, `scripts/ops/chat_session.py`, `bin/jhc-agent-start`, `bin/jhc-agent-stop`, `bin/jhc-agent-cycle`, `bin/jhc-chat`, `tests/test_supervisor_downstream_actions.py`, `tests/test_supervisor.py`, `tests/test_local_runtime.py`, `tests/test_runtime_pack.py`
    - Note: The direct `jhc-chat` wrapper now prints a persisted startup dashboard plus grouped review snapshot, but explicit chat-side review retrieval, control routing, change summaries, and expert-guidance behaviors are still missing.
  - `[gap]` Expert-requested background task outcomes return to review appropriately (rule: `Supervisor Agent behavior`, line: `1314`)
    - Evidence refs: `job_hunt_copilot/chat_runtime.py`, `job_hunt_copilot/supervisor.py`, `job_hunt_copilot/local_runtime.py`, `job_hunt_copilot/runtime_pack.py`, `scripts/ops/run_supervisor_cycle.py`, `scripts/ops/control_agent.py`, `scripts/ops/chat_session.py`, `bin/jhc-agent-start`, `bin/jhc-agent-stop`, `bin/jhc-agent-cycle`, `bin/jhc-chat`, `tests/test_supervisor_downstream_actions.py`, `tests/test_supervisor.py`, `tests/test_local_runtime.py`, `tests/test_runtime_pack.py`
    - Note: The direct `jhc-chat` wrapper now prints a persisted startup dashboard plus grouped review snapshot, but explicit chat-side review retrieval, control routing, change summaries, and expert-guidance behaviors are still missing.
  - `[gap]` AI agent surfaces the current review queue in chat (rule: `Review surfaces and chat-based control`, line: `1360`)
    - Evidence refs: `job_hunt_copilot/chat_runtime.py`, `job_hunt_copilot/review_queries.py`, `job_hunt_copilot/local_runtime.py`, `bin/jhc-chat`, `tests/test_review_queries.py`, `tests/test_local_runtime.py`
    - Note: The direct `jhc-chat` wrapper now prints a persisted startup dashboard plus grouped review snapshot, but explicit chat-side review retrieval, control routing, change summaries, and expert-guidance behaviors are still missing.

### BA10_CHAT_IDLE_TIMEOUT_RESUME: Idle-timeout resume is still backlog
- Next slice: `BA-10-S3`
- Owner roles: `build-lead`
- Rules: `Supervisor Agent behavior`
- Epics: `BA-02`, `BA-03`
- Supporting slices: `BA-02-S1`, `BA-02-S2`, `BA-02-S3`, `BA-03-S1`, `BA-03-S2`, `BA-03-S3`, `BA-10-S3`
- Open scenarios: `1` (`partial`: `1`, `gap`: `0`)
- Reason: Explicit-close and explicit-resume paths exist, but unexpected `jhc-chat` exits still require a later explicit resume because automatic idle-timeout recovery is not implemented.
- Evidence summary: Unexpected chat exit is recorded and a later explicit resume works, but no automatic idle-timeout resume helper exists.
- Evidence code refs: `job_hunt_copilot/local_runtime.py`, `job_hunt_copilot/runtime_pack.py`
- Evidence test refs: `tests/test_local_runtime.py`, `tests/test_runtime_pack.py`, `tests/test_acceptance_traceability.py`
- Validation suite: `python3.11 scripts/quality/run_ba10_validation_suite.py --project-root <repo_root> --gap-id BA10_CHAT_IDLE_TIMEOUT_RESUME`
- Confirmation commands:
  - `python3.11 -m pytest tests/test_local_runtime.py` (automated: Covers launchd plist wiring, control commands, chat lifecycle state, delayed feedback runners, and explicit negative control cases.)
  - `python3.11 -m pytest tests/test_runtime_pack.py` (automated: Confirms generated runtime scaffolding stays honest about current action-catalog and maintenance placeholder status.)
  - `python3.11 -m pytest tests/test_acceptance_traceability.py tests/test_blocker_audit.py` (automated: Keeps the committed BA-10 acceptance and blocker reports synchronized with repo code, tests, and state references.)
- Open scenarios:
  - `[partial]` Expert-interaction resume follows explicit close, explicit resume, or safe idle timeout (rule: `Supervisor Agent behavior`, line: `1297`)
    - Evidence refs: `job_hunt_copilot/chat_runtime.py`, `job_hunt_copilot/supervisor.py`, `job_hunt_copilot/local_runtime.py`, `job_hunt_copilot/runtime_pack.py`, `scripts/ops/run_supervisor_cycle.py`, `scripts/ops/control_agent.py`, `scripts/ops/chat_session.py`, `bin/jhc-agent-start`, `bin/jhc-agent-stop`, `bin/jhc-agent-cycle`, `bin/jhc-chat`, `tests/test_supervisor_downstream_actions.py`, `tests/test_supervisor.py`, `tests/test_local_runtime.py`, `tests/test_runtime_pack.py`
    - Note: Explicit close and explicit resume paths exist, but automatic idle-timeout recovery after unexpected chat exit is still backlog.

## Build-Board Blockers

### BA10-TRACE-001
- Status: `open`
- Severity: `high`
- Owner role: `quality-engineer`
- Summary: The regenerated BA-10 trace matrix now reports 197 implemented / 3 partial / 12 gap scenarios; explicit smoke-coverage targets, implemented-slice traceability, reproducible validation-command mappings, and a durable latest validation-suite report snapshot cover bootstrap, tailoring, discovery, send, feedback, review-query, downstream supervisor follow-through, the persisted `jhc-chat` startup dashboard surface, and the new posting-abandon control path, but richer chat review/control, idle-timeout resume, and maintenance automation themselves remain open.
- Impact: Acceptance signoff is more credible now that committed smoke coverage, blocker-specific evidence refs, explicit negative regressions, and exact open-scenario traces exist, but BA-10 still cannot close until the remaining gap clusters are actually burned down or deliberately left open.
- Next action: Hand the next functional slice to the build lead and the relevant runtime owner for one real remaining BA-10-S3 gap, starting with idle-timeout auto-resume, then richer chat review/control or maintenance automation, and refresh the BA-10 reports plus validation-suite evidence afterward.
- Evidence refs: `build-agent/reports/ba-10-acceptance-trace-matrix.json`, `build-agent/reports/ba-10-acceptance-trace-matrix.md`, `build-agent/reports/ba-10-blocker-audit.json`, `build-agent/reports/ba-10-blocker-audit.md`, `build-agent/reports/ba-10-validation-suite-latest.json`, `build-agent/reports/ba-10-validation-suite-latest.md`, `job_hunt_copilot/acceptance_traceability.py`, `job_hunt_copilot/blocker_audit.py`, `job_hunt_copilot/quality_validation.py`, `scripts/quality/generate_blocker_audit.py`, `scripts/quality/run_ba10_validation_suite.py`, `scripts/ops/control_agent.py`, `tests/test_acceptance_traceability.py`, `tests/test_blocker_audit.py`, `tests/test_local_runtime.py`, `tests/test_quality_validation.py`, `tests/test_supervisor_downstream_actions.py`, `tests/test_delivery_feedback.py`, `tests/test_schema.py`, `tests/test_smoke_harness.py`, `tests/test_supervisor.py`, `tests/test_runtime_pack.py`, `tests/test_resume_tailoring.py`, `tests/test_outreach.py`, `tests/test_review_queries.py`
- Validation suite: `python3.11 scripts/quality/run_ba10_validation_suite.py --project-root <repo_root> --blocker-id BA10-TRACE-001`
- Confirmation commands:
  - `python3.11 -m pytest tests/test_acceptance_traceability.py tests/test_blocker_audit.py` (automated: Keeps the committed BA-10 acceptance and blocker reports synchronized with repo code, tests, and state references.)
  - `python3.11 -m pytest tests/test_smoke_harness.py` (automated: Replays the committed bootstrap -> tailoring -> discovery -> send -> feedback -> review-query smoke path.)
  - `python3.11 -m pytest tests/test_bootstrap.py tests/test_schema.py tests/test_artifacts.py` (automated: Confirms bootstrap prerequisites, canonical schema migration, and shared artifact contracts stay valid.)
  - `python3.11 -m pytest tests/test_resume_tailoring.py` (automated: Confirms tailoring bootstrap, deterministic artifact generation, compile verification, and mandatory review gates stay intact.)
  - `python3.11 -m pytest tests/test_email_discovery.py` (automated: Confirms people search, shortlist materialization, enrichment, discovery artifacts, and provider-budget behavior stay intact.)
  - `python3.11 -m pytest tests/test_outreach.py` (automated: Confirms send-set readiness, draft persistence, safe send execution, and repeat-outreach guardrails stay intact.)
  - `python3.11 -m pytest tests/test_delivery_feedback.py` (automated: Confirms immediate or delayed feedback ingestion, normalized event persistence, and delivery outcome artifacts stay intact.)
  - `python3.11 -m pytest tests/test_supervisor_downstream_actions.py` (automated: Confirms incident-first selector ordering, existing-run reuse, bounded role-targeted progression through `delivery_feedback`, and contact-rooted general-learning follow-through while keeping the remaining maintenance-selector gap explicit.)
  - `python3.11 -m pytest tests/test_local_runtime.py` (automated: Covers launchd plist wiring, control commands, chat lifecycle state, delayed feedback runners, and explicit negative control cases.)
  - `python3.11 -m pytest tests/test_review_queries.py` (automated: Verifies persisted grouped review surfaces and traceability reads that back the chat/review boundary.)
  - `python3.11 -m pytest tests/test_runtime_pack.py` (automated: Confirms generated runtime scaffolding stays honest about current action-catalog and maintenance placeholder status.)

### BUILD-CLI-001
- Status: `open`
- Severity: `medium`
- Owner role: `build-lead`
- Summary: The unattended build wrapper now has automated regression coverage for its `codex exec` command shape, but real host-side cycle execution still needs confirmation after the `--ask-for-approval` incompatibility.
- Impact: The wrapper command shape is now guarded in automated tests, but unattended build sessions can still fail before work starts if the real host environment or Codex CLI invocation diverges from that validated shape.
- Next action: Re-run the unattended build-lead wrapper on the host and confirm it starts a real cycle with the supported `codex exec` flags.
- Evidence refs: `build-agent/scripts/run_build_lead_cycle.py`, `tests/test_build_agent_cycle.py`, `build-agent/logs/cycles/build-cycle-20260406T034335Z-66be05af.log`
- Validation suite: `python3.11 scripts/quality/run_ba10_validation_suite.py --project-root <repo_root> --blocker-id BUILD-CLI-001 --include-manual`
- Confirmation commands:
  - `python3.11 -m pytest tests/test_build_agent_cycle.py` (automated: Guards the unattended build-lead `codex exec` invocation shape so unsupported approval flags do not return.)
  - `codex exec --help && codex --help` (manual_local: Reconfirms the current CLI shape so unattended build wrappers do not reintroduce unsupported approval flags.)

### OPS-LAUNCHD-001
- Status: `open`
- Severity: `medium`
- Owner role: `build-lead`
- Summary: Live `launchctl bootstrap gui/$UID /Users/achyutaramsonti/Projects/job-hunt-copilot-v4/ops/launchd/job-hunt-copilot-supervisor.plist` still returns `Input/output error` in the current sandboxed session, so successful host-side launchd load validation remains pending for both the supervisor and delayed-feedback jobs even though their plists, wrappers, runners, and failed-start rollback validate locally.
- Impact: Product-side background launchd startup is not yet verified outside the sandbox even though the repo-local helper code and rollback behavior are working.
- Next action: Run `bin/jhc-agent-start` on the host outside the sandbox, then inspect `launchctl print gui/$UID/com.jobhuntcopilot.supervisor` and system launchd logs to capture the real bootstrap outcome.
- Evidence refs: `build-agent/logs/cycles/build-cycle-20260407T213533Z-5b2c1d98.log`, `bin/jhc-agent-start`, `bin/jhc-feedback-sync-cycle`, `scripts/ops/materialize_supervisor_plist.py`, `scripts/ops/materialize_feedback_sync_plist.py`, `tests/test_local_runtime.py`
- Validation suite: `python3.11 scripts/quality/run_ba10_validation_suite.py --project-root <repo_root> --blocker-id OPS-LAUNCHD-001 --include-manual`
- Confirmation commands:
  - `python3.11 -m pytest tests/test_local_runtime.py` (automated: Covers launchd plist wiring, control commands, chat lifecycle state, delayed feedback runners, and explicit negative control cases.)
  - `bin/jhc-agent-start && launchctl print gui/$UID/com.jobhuntcopilot.supervisor` (manual_host: Must run outside the sandbox to validate real host launchd bootstrap behavior and collect diagnostic output.)
