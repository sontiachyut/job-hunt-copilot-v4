# Project Agent Notes

## Bug-Fix Workflow

Use this workflow for bug fixes and small repairs in this repo:

1. Update the relevant requirement first in `prd/spec.md` when the bug exposes a spec ambiguity.
2. Resolve spec ambiguity one question at a time.
3. Create a GitHub issue for the bug before implementing the fix.
4. Implement the fix with regression coverage.
5. Document the fix back on the GitHub issue.
6. Commit and push the completed work to GitHub after the work is done.

## Decision Boundary

- For small bug fixes, small patches, and spec-ambiguity cleanup that does not materially change system direction, Codex may make the clarifying spec update and proceed.
- For changes that alter the system's intended behavior, operating model, or product direction, stop and hand the decision back to the owner before implementing.

## Spec-Ambiguity Method

When clearing ambiguity in `prd/spec.md`, use this method:

1. Ask one ambiguity question at a time.
2. Answer that one question directly.
3. Move to the next ambiguity only after the previous one has been resolved.

Do not collapse multiple unresolved ambiguities into one blended spec change when they can be resolved sequentially.

## Persistence

- Keep this file current when the owner defines new repo-specific operating rules.
- When possible, mirror the bug context and fix summary on the corresponding GitHub issue so the workflow history also exists outside the local checkout.
