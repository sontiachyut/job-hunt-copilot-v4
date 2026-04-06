# Build Agent

This folder defines a dedicated Codex-driven build team for implementing Job Hunt Copilot v4 from the finalized product documents.

The build team is separate from the runtime `Operations / Supervisor Agent` described in the PRD.
Its job is to build the project itself.

## Runtime Control Plane

The build agent now has a local control plane for long unattended runs:
- a `build-lead` heartbeat driven by `launchd`
- fresh-session `codex exec` cycles instead of one immortal Codex process
- file-backed control state, leases, cycle logs, and chat-session tracking
- shell entrypoints under `build-agent/bin/`

The default unattended build model is intentionally serialized:
- one active build-lead cycle at a time
- one primary role-owned slice per cycle
- no default parallel multi-role execution until the repository is more mature

That still preserves the multi-engineer model because each cycle explicitly assigns one specialist role and follows that role's brief.

## Operating Model

This is a multi-agent software-engineering team model:
- one coordinating build lead
- multiple specialist engineer agents
- shared canonical backlog and journal
- bounded ownership per engineer so work can run for long hours without becoming chaotic

The coordinating build lead decides what to build next, which engineer role owns it, what validation is required, and when a slice is actually done.

For long unattended build runs, the recommended execution style is a fresh-session loop:
- Codex starts fresh
- rehydrates from files on disk
- performs one bounded slice
- validates it
- checkpoints progress
- exits cleanly
- the loop starts the next session

That gives long runtime without depending on one immortal chat process.

Sleep/wake behavior is recovery-first:
- if the Mac sleeps, unattended build work stops while the machine sleeps
- on wake, the first heartbeat performs sleep/wake recovery only
- recovery uses macOS power logs first and a long-gap fallback second
- recovery may reclaim a stale interrupted lease, but it does not start a new slice until recovery completes

## Purpose

The build team should:
- use [../prd/spec.md](../prd/spec.md) as the canonical product and architecture contract
- use [../prd/test-spec.feature](../prd/test-spec.feature) as the canonical acceptance contract
- implement the project in bounded slices without rushing
- persist progress outside chat context so long-running work stays coherent across sessions
- validate work continuously and surface unresolved blockers cleanly

The build team should not:
- redesign the product casually while implementing it
- silently change the PRD or test spec unless explicitly asked
- rely on transient chat memory as its only source of project state
- skip validation just to move faster

## Folder Contents

- `identity.yaml`: who the build agent is and what it owns
- `policies.yaml`: working rules, safety limits, and quality expectations
- `task-catalog.yaml`: bounded work types the agent can perform
- `execution-loop.md`: the durable implementation loop
- `coordination.yaml`: build-team roles, ownership boundaries, and coordination rules
- `chat-bootstrap.md`: prompt file for interactive Codex operator mode
- `builder-bootstrap.md`: prompt file for long-running implementation mode
- `team/`: role-specific engineer briefs
- `state/build-board.yaml`: seeded implementation backlog and current build board
- `state/build-journal.md`: append-only work log template
- `state/codex-progress.txt`: short session-by-session handoff log
- `state/IMPLEMENTATION_PLAN.md`: human-readable prioritized implementation checklist
- `reports/README.md`: where build-review notes and summaries should go
- `runtime/runtime-pack.json`: generated compact runtime identity/policy pack
- `launchd/job-hunt-copilot-build-lead.plist.template`: template for the local build-lead heartbeat job
- `launchd/job-hunt-copilot-build-lead.plist`: rendered local plist with absolute project paths
- `bin/jhc-build-start`: start/register the unattended build loop
- `bin/jhc-build-stop`: stop future unattended build heartbeats
- `bin/jhc-build-chat`: open the expert-facing build chat operator
- `bin/jhc-build-cycle`: run one build-lead heartbeat cycle
- `scripts/`: Python helpers for runtime-pack generation, cycle execution, control state, and chat sessions

## Commands

Use the helper entrypoints from the repository root:

```bash
./build-agent/bin/jhc-build-start
./build-agent/bin/jhc-build-stop
./build-agent/bin/jhc-build-chat
```

`jhc-build-start` should be run once. After that, `launchd` keeps invoking the build-lead heartbeat on schedule until you stop it or the job breaks.

`jhc-build-chat` is the expert-facing control surface. It pauses unattended build execution while you are actively interacting, then resumes when the chat closes cleanly.

## Git Boundary Requirement

The unattended build agent assumes this project lives in its own dedicated Git repository rooted at `job-hunt-copilot-v4`.

That requirement is strict:
- the build lead reads current git state before selecting slices
- later checkpoint and backup push automation depends on the project root being the git root
- the agent should refuse unattended build execution if `git rev-parse --show-toplevel` does not equal this project root

Generated local runtime artifacts are intentionally gitignored and should not be part of normal source history.

## Intended Operating Model

The coordinating build lead should work in repeated bounded cycles:
1. read the PRD, acceptance spec, and current build board
2. choose one bounded implementation slice
3. assign it to the correct engineer role
4. implement it
5. validate it
6. checkpoint results into the build board and journal
7. continue with the next highest-value slice

This keeps the work durable even if the Codex session is restarted.

## Long-Run Loop Pattern

The most useful unattended-build pattern is:
1. `init` phase
   - verify workspace, state files, and conventions
2. `plan` phase
   - refine the implementation plan from the current PRD and acceptance spec
3. `build` phase
   - one bounded slice per fresh session
   - validate
   - checkpoint
   - exit

The next fresh session reads:
- `build-agent/state/codex-progress.txt`
- `build-agent/state/IMPLEMENTATION_PLAN.md`
- `build-agent/state/build-board.yaml`
- `build-agent/state/build-journal.md`

That gives the new session continuity without relying on old prompt memory.

In the current unattended runtime:
- `launchd` invokes the build-lead heartbeat every 10 minutes
- each cycle acquires a lease, selects one bounded slice, and launches one fresh `codex exec` implementation session
- if a prior cycle is still active, the new heartbeat defers cleanly

## Canonical Inputs

- [../prd/spec.md](../prd/spec.md)
- [../prd/test-spec.feature](../prd/test-spec.feature)
- repository source tree
- runtime artifacts and current git state

## Team Roles

- `build-lead`: coordinating architect and integrator
- `planning-engineer`: implementation planner and decomposition owner
- `foundation-engineer`: schema, persistence, runtime scaffolding
- `ingestion-engineer`: manual capture, Gmail intake, upstream normalization
- `tailoring-engineer`: resume-tailoring runtime and agent review gate
- `outreach-engineer`: people search, enrichment, discovery, drafting, sending
- `quality-engineer`: acceptance tracing, smoke validation, regression checks

Detailed role briefs live under [team/](./team/).

## Success Condition

The build team is successful when:
- the repository implements the current-build PRD
- the implementation can satisfy the acceptance scenarios in `prd/test-spec.feature`
- unresolved gaps are explicitly recorded rather than hidden

Planning quality is part of that success condition:
- the planning-engineer should turn the PRD into a clear executable build program
- other role agents should inherit bounded, dependency-aware work from that plan
