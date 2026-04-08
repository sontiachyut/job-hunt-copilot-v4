# BA-10 Validation Suite Report

- Generated at: `2026-04-08T20:53:42Z`
- Project root: `/Users/achyutaramsonti/Projects/job-hunt-copilot-v4`
- Passed: `True`
- Command count: `11`
- Passed commands: `11`
- Failed commands: `0`
- Total duration seconds: `16.212`
- Command ids: none
- Smoke targets: none
- Acceptance gaps: none
- Build-board blockers: none
- Current focus requested: `False`
- Include manual commands: `False`
- Refresh reports before run: `True`

## Command Kind Counts

- `automated`: `11`

## Refreshed Reports

- Acceptance trace JSON: `/Users/achyutaramsonti/Projects/job-hunt-copilot-v4/build-agent/reports/ba-10-acceptance-trace-matrix.json`
- Acceptance trace markdown: `/Users/achyutaramsonti/Projects/job-hunt-copilot-v4/build-agent/reports/ba-10-acceptance-trace-matrix.md`
- Blocker audit JSON: `/Users/achyutaramsonti/Projects/job-hunt-copilot-v4/build-agent/reports/ba-10-blocker-audit.json`
- Blocker audit markdown: `/Users/achyutaramsonti/Projects/job-hunt-copilot-v4/build-agent/reports/ba-10-blocker-audit.md`

## Command Results

| Command | Kind | Status | Returncode | Duration (s) |
| --- | --- | --- | ---: | ---: |
| qa_acceptance_reports | automated | passed | 0 | 0.373 |
| qa_smoke_flow | automated | passed | 0 | 2.364 |
| qa_bootstrap_regressions | automated | passed | 0 | 0.489 |
| qa_tailoring_regressions | automated | passed | 0 | 5.631 |
| qa_discovery_regressions | automated | passed | 0 | 0.751 |
| qa_outreach_regressions | automated | passed | 0 | 0.855 |
| qa_feedback_regressions | automated | passed | 0 | 0.358 |
| qa_supervisor_regressions | automated | passed | 0 | 0.479 |
| qa_runtime_control_regressions | automated | passed | 0 | 4.343 |
| qa_review_surface_regressions | automated | passed | 0 | 0.394 |
| qa_runtime_pack_regressions | automated | passed | 0 | 0.175 |

## Command Details

### qa_acceptance_reports: Acceptance report guards
- Kind: `automated`
- Status: `passed`
- Returncode: `0`
- Duration seconds: `0.373`
- Command: `python3.11 -m pytest tests/test_acceptance_traceability.py tests/test_blocker_audit.py`
- Description: Keeps the committed BA-10 acceptance and blocker reports synchronized with repo code, tests, and state references.

### qa_smoke_flow: Smoke harness flow
- Kind: `automated`
- Status: `passed`
- Returncode: `0`
- Duration seconds: `2.364`
- Command: `python3.11 -m pytest tests/test_smoke_harness.py`
- Description: Replays the committed bootstrap -> tailoring -> discovery -> send -> feedback -> review-query smoke path.

### qa_bootstrap_regressions: Bootstrap regressions
- Kind: `automated`
- Status: `passed`
- Returncode: `0`
- Duration seconds: `0.489`
- Command: `python3.11 -m pytest tests/test_bootstrap.py tests/test_schema.py tests/test_artifacts.py`
- Description: Confirms bootstrap prerequisites, canonical schema migration, and shared artifact contracts stay valid.

### qa_tailoring_regressions: Tailoring regressions
- Kind: `automated`
- Status: `passed`
- Returncode: `0`
- Duration seconds: `5.631`
- Command: `python3.11 -m pytest tests/test_resume_tailoring.py`
- Description: Confirms tailoring bootstrap, deterministic artifact generation, compile verification, and mandatory review gates stay intact.

### qa_discovery_regressions: Discovery regressions
- Kind: `automated`
- Status: `passed`
- Returncode: `0`
- Duration seconds: `0.751`
- Command: `python3.11 -m pytest tests/test_email_discovery.py`
- Description: Confirms people search, shortlist materialization, enrichment, discovery artifacts, and provider-budget behavior stay intact.

### qa_outreach_regressions: Outreach regressions
- Kind: `automated`
- Status: `passed`
- Returncode: `0`
- Duration seconds: `0.855`
- Command: `python3.11 -m pytest tests/test_outreach.py`
- Description: Confirms send-set readiness, draft persistence, safe send execution, and repeat-outreach guardrails stay intact.

### qa_feedback_regressions: Delivery feedback regressions
- Kind: `automated`
- Status: `passed`
- Returncode: `0`
- Duration seconds: `0.358`
- Command: `python3.11 -m pytest tests/test_delivery_feedback.py`
- Description: Confirms immediate or delayed feedback ingestion, normalized event persistence, and delivery outcome artifacts stay intact.

### qa_supervisor_regressions: Supervisor downstream hardening regressions
- Kind: `automated`
- Status: `passed`
- Returncode: `0`
- Duration seconds: `0.479`
- Command: `python3.11 -m pytest tests/test_supervisor_downstream_actions.py`
- Description: Confirms `lead_handoff` remains the only registered checkpoint, later stages escalate explicitly, and retries preserve the same durable run plus pending review packet.

### qa_runtime_control_regressions: Runtime control regressions
- Kind: `automated`
- Status: `passed`
- Returncode: `0`
- Duration seconds: `4.343`
- Command: `python3.11 -m pytest tests/test_local_runtime.py`
- Description: Covers launchd plist wiring, control commands, chat lifecycle state, delayed feedback runners, and explicit negative control cases.

### qa_review_surface_regressions: Review surface regressions
- Kind: `automated`
- Status: `passed`
- Returncode: `0`
- Duration seconds: `0.394`
- Command: `python3.11 -m pytest tests/test_review_queries.py`
- Description: Verifies persisted grouped review surfaces and traceability reads that back the chat/review boundary.

### qa_runtime_pack_regressions: Runtime pack regressions
- Kind: `automated`
- Status: `passed`
- Returncode: `0`
- Duration seconds: `0.175`
- Command: `python3.11 -m pytest tests/test_runtime_pack.py`
- Description: Confirms generated runtime scaffolding stays honest about current action-catalog and maintenance placeholder status.
