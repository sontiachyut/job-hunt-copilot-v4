# BA-10 Validation Suite Report

- Generated at: `2026-04-08T21:19:32Z`
- Project root: `/Users/achyutaramsonti/Projects/job-hunt-copilot-v4`
- Passed: `True`
- Command count: `4`
- Passed commands: `4`
- Failed commands: `0`
- Total duration seconds: `3.634`
- Command ids: none
- Smoke targets: `bootstrap`
- Acceptance gaps: none
- Build-board blockers: none
- Current focus requested: `True`
- Include manual commands: `False`
- Refresh reports before run: `True`

## Command Kind Counts

- `automated`: `4`

## Refreshed Reports

- Acceptance trace JSON: `/Users/achyutaramsonti/Projects/job-hunt-copilot-v4/build-agent/reports/ba-10-acceptance-trace-matrix.json`
- Acceptance trace markdown: `/Users/achyutaramsonti/Projects/job-hunt-copilot-v4/build-agent/reports/ba-10-acceptance-trace-matrix.md`
- Blocker audit JSON: `/Users/achyutaramsonti/Projects/job-hunt-copilot-v4/build-agent/reports/ba-10-blocker-audit.json`
- Blocker audit markdown: `/Users/achyutaramsonti/Projects/job-hunt-copilot-v4/build-agent/reports/ba-10-blocker-audit.md`

## Selector Details

### Smoke Targets

- `bootstrap`: Bootstrap and prerequisites
  - Acceptance scenario: `Build smoke test passes`
  - Acceptance checks: the system initializes or migrates `job_hunt_copilot.db`; the system loads runtime secrets successfully; the system reads the required files from `assets/`
  - Validation command ids: `qa_smoke_flow`, `qa_bootstrap_regressions`
  - Test refs: `tests/test_smoke_harness.py`, `tests/test_bootstrap.py`, `tests/test_schema.py`

### Current Focus

- Epic: `BA-10`
- Slice: `BA-10-S4`
- Owner role: `build-lead`
- Reason: BA-10-S4 now has a dedicated downstream-stage regression target plus refreshed traceability and blocker reports, while the matrix still sits at 190 implemented / 8 partial / 14 gap scenarios; the next highest-value slice remains a build-lead implementation pass on downstream supervisor action-catalog steps beyond `lead_handoff`, because that single cluster still accounts for the largest remaining acceptance partial set and blocks the strongest end-to-end closure.
- Gap ids: `BA10_SUPERVISOR_DOWNSTREAM_ACTION_CATALOG`
- Validation command ids: `qa_supervisor_regressions`, `qa_acceptance_reports`
- Validation suite: `python3.11 scripts/quality/run_ba10_validation_suite.py --project-root <repo_root> --current-focus`

## Command Results

| Command | Kind | Status | Returncode | Duration (s) |
| --- | --- | --- | ---: | ---: |
| qa_supervisor_regressions | automated | passed | 0 | 0.528 |
| qa_acceptance_reports | automated | passed | 0 | 0.301 |
| qa_smoke_flow | automated | passed | 0 | 2.360 |
| qa_bootstrap_regressions | automated | passed | 0 | 0.445 |

## Command Details

### qa_supervisor_regressions: Supervisor downstream hardening regressions
- Kind: `automated`
- Status: `passed`
- Returncode: `0`
- Duration seconds: `0.528`
- Command: `python3.11 -m pytest tests/test_supervisor_downstream_actions.py`
- Description: Confirms `lead_handoff` remains the only registered checkpoint, later stages escalate explicitly, and retries preserve the same durable run plus pending review packet.

### qa_acceptance_reports: Acceptance report guards
- Kind: `automated`
- Status: `passed`
- Returncode: `0`
- Duration seconds: `0.301`
- Command: `python3.11 -m pytest tests/test_acceptance_traceability.py tests/test_blocker_audit.py`
- Description: Keeps the committed BA-10 acceptance and blocker reports synchronized with repo code, tests, and state references.

### qa_smoke_flow: Smoke harness flow
- Kind: `automated`
- Status: `passed`
- Returncode: `0`
- Duration seconds: `2.36`
- Command: `python3.11 -m pytest tests/test_smoke_harness.py`
- Description: Replays the committed bootstrap -> tailoring -> discovery -> send -> feedback -> review-query smoke path.

### qa_bootstrap_regressions: Bootstrap regressions
- Kind: `automated`
- Status: `passed`
- Returncode: `0`
- Duration seconds: `0.445`
- Command: `python3.11 -m pytest tests/test_bootstrap.py tests/test_schema.py tests/test_artifacts.py`
- Description: Confirms bootstrap prerequisites, canonical schema migration, and shared artifact contracts stay valid.
