# BA-10 Validation Suite Report

- Generated at: `2026-04-09T00:10:51Z`
- Project root: `/Users/achyutaramsonti/Projects/job-hunt-copilot-v4`
- Passed: `True`
- Command count: `2`
- Passed commands: `2`
- Failed commands: `0`
- Total duration seconds: `1.177`
- Requested command ids: none
- Requested smoke targets: none
- Requested acceptance gaps: none
- Requested build-board blockers: none
- Current focus requested: `True`
- Include manual commands: `False`
- Refresh reports before run: `True`

## Command Kind Counts

- `automated`: `2`

## Refreshed Reports

- Acceptance trace JSON: `/Users/achyutaramsonti/Projects/job-hunt-copilot-v4/build-agent/reports/ba-10-acceptance-trace-matrix.json`
- Acceptance trace markdown: `/Users/achyutaramsonti/Projects/job-hunt-copilot-v4/build-agent/reports/ba-10-acceptance-trace-matrix.md`
- Blocker audit JSON: `/Users/achyutaramsonti/Projects/job-hunt-copilot-v4/build-agent/reports/ba-10-blocker-audit.json`
- Blocker audit markdown: `/Users/achyutaramsonti/Projects/job-hunt-copilot-v4/build-agent/reports/ba-10-blocker-audit.md`

## Open BA-10 Status

- Acceptance scenarios: `214`
- Open acceptance scenarios: `19`
- Acceptance status counts: `implemented`=193, `partial`=5, `gap`=14, `deferred_optional`=1, `excluded_from_required_acceptance`=1
- Open acceptance gap clusters: `5`
- Open acceptance gap ids: `BA10_SUPERVISOR_DOWNSTREAM_ACTION_CATALOG`, `BA10_MAINTENANCE_AUTOMATION`, `BA10_CHAT_REVIEW_AND_CONTROL`, `BA10_CHAT_IDLE_TIMEOUT_RESUME`, `BA10_POSTING_ABANDON_CONTROL`
- Open build-board blockers: `3`
- Open build-board blocker ids: `BA10-TRACE-001`, `BUILD-CLI-001`, `OPS-LAUNCHD-001`
- Current build focus: `BA-10` / `BA-10-S4` / `build-lead`

## Selector Details

### Current Focus

- Epic: `BA-10`
- Slice: `BA-10-S4`
- Owner role: `build-lead`
- Reason: BA-10-S4 now covers the full role-targeted supervisor chain through bounded `delivery_feedback` completion and moved the acceptance matrix to 193 implemented / 5 partial / 14 gap scenarios; the highest-value remaining work in this slice is the still-missing contact-rooted general-learning selector or action path.
- Gap ids: `BA10_SUPERVISOR_DOWNSTREAM_ACTION_CATALOG`
- Validation command ids: `qa_supervisor_regressions`, `qa_acceptance_reports`
- Validation suite: `python3.11 scripts/quality/run_ba10_validation_suite.py --project-root <repo_root> --current-focus`

## Command Results

| Command | Kind | Status | Returncode | Duration (s) |
| --- | --- | --- | ---: | ---: |
| qa_supervisor_regressions | automated | passed | 0 | 0.859 |
| qa_acceptance_reports | automated | passed | 0 | 0.318 |

## Command Details

### qa_supervisor_regressions: Supervisor downstream hardening regressions
- Kind: `automated`
- Status: `passed`
- Returncode: `0`
- Duration seconds: `0.859`
- Command: `python3.11 -m pytest tests/test_supervisor_downstream_actions.py`
- Description: Confirms `lead_handoff` advances into `agent_review`, bounded mandatory review advances into `people_search`, bounded people search advances into `email_discovery`, bounded email discovery advances into `sending`, bounded sending advances into `delivery_feedback`, bounded delivery feedback either stays active until high-level outcomes are due or completes the same durable run with a review packet, and the remaining contact-rooted general-learning selector gap still yields no selected supervisor work.

### qa_acceptance_reports: Acceptance report guards
- Kind: `automated`
- Status: `passed`
- Returncode: `0`
- Duration seconds: `0.318`
- Command: `python3.11 -m pytest tests/test_acceptance_traceability.py tests/test_blocker_audit.py`
- Description: Keeps the committed BA-10 acceptance and blocker reports synchronized with repo code, tests, and state references.
