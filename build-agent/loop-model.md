# Fresh-Session Loop Model

This file adapts the useful ideas from the earlier Codex loop pattern into the v4 build-team workspace.

## Why This Is Useful

For long unattended build runs:
- Codex should not depend on one immortal process
- fresh starts reduce context drift
- persisted files give continuity
- bounded slices reduce chaos

## Core Pattern

Each unattended build session should:
1. start fresh
2. read the persisted build-state files
3. choose one bounded slice
4. implement it
5. validate it
6. checkpoint it
7. exit

Then an outer loop can start the next fresh session.

## Canonical Long-Term Memory Files

- `build-agent/state/codex-progress.txt`
- `build-agent/state/IMPLEMENTATION_PLAN.md`
- `build-agent/state/build-board.yaml`
- `build-agent/state/build-journal.md`

## Recommended Phase Model

- `init`
  - verify repository, state files, and conventions
- `plan`
  - refine implementation order from PRD and acceptance spec
- `build`
  - one primary slice per fresh session

## Why Not One Huge Session

One huge session tends to:
- drift away from the spec
- hold stale assumptions too long
- lose recovery clarity after errors
- make progress hard to audit

The loop model trades some restart overhead for much better durability.

