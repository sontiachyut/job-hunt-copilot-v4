# BA-10 Validation Suite Report

- Generated at: `2026-04-08T21:03:56Z`
- Project root: `/Users/achyutaramsonti/Projects/job-hunt-copilot-v4`
- Passed: `True`
- Command count: `2`
- Passed commands: `2`
- Failed commands: `0`
- Total duration seconds: `0.94`
- Command ids: none
- Smoke targets: none
- Acceptance gaps: none
- Build-board blockers: none
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

## Command Results

| Command | Kind | Status | Returncode | Duration (s) |
| --- | --- | --- | ---: | ---: |
| qa_supervisor_regressions | automated | passed | 0 | 0.640 |
| qa_acceptance_reports | automated | passed | 0 | 0.300 |

## Command Details

### qa_supervisor_regressions: Supervisor downstream hardening regressions
- Kind: `automated`
- Status: `passed`
- Returncode: `0`
- Duration seconds: `0.64`
- Command: `python3.11 -m pytest tests/test_supervisor_downstream_actions.py`
- Description: Confirms `lead_handoff` remains the only registered checkpoint, later stages escalate explicitly, and retries preserve the same durable run plus pending review packet.

### qa_acceptance_reports: Acceptance report guards
- Kind: `automated`
- Status: `passed`
- Returncode: `0`
- Duration seconds: `0.3`
- Command: `python3.11 -m pytest tests/test_acceptance_traceability.py tests/test_blocker_audit.py`
- Description: Keeps the committed BA-10 acceptance and blocker reports synchronized with repo code, tests, and state references.
