# Host Validation Closeout

- Date: `2026-04-09`
- Scope: `BUILD-CLI-001`, `OPS-LAUNCHD-001`
- Outcome: `passed`

## Summary

Real host-side validation is now complete for the remaining operational blockers.

- `bin/jhc-agent-start` successfully loaded both product launchd jobs.
- `launchctl print gui/$UID/com.jobhuntcopilot.supervisor` showed the supervisor job loaded from `ops/launchd/job-hunt-copilot-supervisor.plist` and running.
- `launchctl print gui/$UID/com.jobhuntcopilot.feedback-sync` showed the delayed-feedback job loaded from `ops/launchd/job-hunt-copilot-feedback-sync.plist` with `last exit code = 0`.
- `bin/jhc-agent-stop` booted both product launchd jobs out cleanly, and `scripts/ops/control_agent.py status` returned canonical `agent_mode = stopped`.
- `build-agent/bin/jhc-build-start` successfully loaded `gui/$UID/com.jobhuntcopilot.buildlead` and started real host build-lead heartbeats.
- The host build replay recorded clean `no_work` rows in `build-agent/state/build-cycles.jsonl`, proving the wrapper can start real cycles on the machine even after the earlier Codex CLI flag incompatibility.
- `build-agent/bin/jhc-build-stop` booted the build lead job out cleanly and returned the machine to stopped idle state.

## Commands Run

```bash
bin/jhc-agent-start
launchctl print gui/$UID/com.jobhuntcopilot.supervisor
launchctl print gui/$UID/com.jobhuntcopilot.feedback-sync
bin/jhc-agent-stop
python3.11 scripts/ops/control_agent.py status --project-root /Users/achyutaramsonti/Projects/job-hunt-copilot-v4
build-agent/bin/jhc-build-start
launchctl print gui/$UID/com.jobhuntcopilot.buildlead
tail -n 4 build-agent/state/build-cycles.jsonl
build-agent/bin/jhc-build-stop
```

## Key Evidence

- Product launchd start wrapper: [bin/jhc-agent-start](/Users/achyutaramsonti/Projects/job-hunt-copilot-v4/bin/jhc-agent-start)
- Product launchd stop wrapper: [bin/jhc-agent-stop](/Users/achyutaramsonti/Projects/job-hunt-copilot-v4/bin/jhc-agent-stop)
- Supervisor plist: [job-hunt-copilot-supervisor.plist](/Users/achyutaramsonti/Projects/job-hunt-copilot-v4/ops/launchd/job-hunt-copilot-supervisor.plist)
- Feedback plist: [job-hunt-copilot-feedback-sync.plist](/Users/achyutaramsonti/Projects/job-hunt-copilot-v4/ops/launchd/job-hunt-copilot-feedback-sync.plist)
- Build-agent start wrapper: [jhc-build-start](/Users/achyutaramsonti/Projects/job-hunt-copilot-v4/build-agent/bin/jhc-build-start)
- Build-agent stop wrapper: [jhc-build-stop](/Users/achyutaramsonti/Projects/job-hunt-copilot-v4/build-agent/bin/jhc-build-stop)
- Build cycle ledger: [build-cycles.jsonl](/Users/achyutaramsonti/Projects/job-hunt-copilot-v4/build-agent/state/build-cycles.jsonl)
- Build control state: [build-control.json](/Users/achyutaramsonti/Projects/job-hunt-copilot-v4/build-agent/state/build-control.json)

## Final State

- Product supervisor jobs: `stopped`
- Build agent: `stopped`
- Required acceptance surface: `212 implemented / 0 partial / 0 gap`
- Remaining repo-tracked blockers: `none`
