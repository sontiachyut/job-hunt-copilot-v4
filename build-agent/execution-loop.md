# Build Execution Loop

This is the durable working loop for the build team.

## 1. Rehydrate Context

At the start of a session or long-running cycle, read:
- `prd/spec.md`
- `prd/test-spec.feature`
- `build-agent/identity.yaml`
- `build-agent/policies.yaml`
- `build-agent/task-catalog.yaml`
- `build-agent/state/codex-progress.txt`
- `build-agent/state/IMPLEMENTATION_PLAN.md`
- `build-agent/state/build-board.yaml`
- `build-agent/state/build-journal.md`

Then inspect the current codebase and git state before deciding what to do.

In unattended loop mode, this rehydration step is mandatory for every fresh Codex session.

## 2. Pick One Bounded Slice and Assign an Owner

Choose one slice that is:
- high value
- clearly scoped
- buildable without redesigning the product
- testable or checkable before claiming completion

Then assign one primary engineer role to own it.

Good slices:
- add one DB table or migration cluster
- implement one component boundary
- implement one helper command or runtime service
- cover one acceptance-rule cluster

Avoid:
- trying to build the whole repo in one shot
- changing many unrelated components together

## 3. Implement Carefully Within Role Boundaries

While implementing:
- stay grounded in the PRD and acceptance spec
- prefer the narrowest change that satisfies the slice
- preserve unrelated user work
- keep the code readable and auditable
- keep the assigned engineer role inside its owned subsystem unless the build lead expands scope

## 4. Validate Before Advancing

Before marking the slice done:
- run targeted validation for the changed area
- run broader smoke checks if the change affects shared flow
- compare the result against the relevant acceptance scenarios

If the slice fails validation:
- repair it if the fix is bounded
- otherwise record the blocker explicitly

## 5. Integrate and Checkpoint Durably

Update:
- `build-agent/state/build-board.yaml`
- `build-agent/state/build-journal.md`

Record:
- what was attempted
- which engineer role owned it
- what changed
- what validation passed or failed
- what the next best slice is

## 6. Continue or Stop Cleanly

If another bounded slice is ready, continue.
If blocked, record the blocker and stop cleanly.

The session should remain understandable even if a later Codex session takes over.

## Recommended Loop Behavior

For long unattended runs:
- one fresh Codex session should usually do one primary slice
- the session should update:
  - `build-agent/state/codex-progress.txt`
  - `build-agent/state/IMPLEMENTATION_PLAN.md`
  - `build-agent/state/build-board.yaml`
  - `build-agent/state/build-journal.md`
- then it should exit cleanly

The next looped session should start fresh and rehydrate from those files.
