# Implementation Plan

This is the human-readable prioritized checklist for the build team.

It should stay aligned with:
- `prd/spec.md`
- `prd/test-spec.feature`
- `build-agent/state/build-board.yaml`

## Initial Order

1. Planning and decomposition
2. Foundation and schema
3. Supervisor control plane
4. macOS local runtime helpers
5. Manual capture path
6. Gmail alert intake
7. Resume tailoring runtime
8. People search and discovery
9. Drafting and sending
10. Delivery feedback and review surfaces
11. Validation and hardening

## Rules

- Break large items into bounded slices before implementation
- Prefer one primary slice per unattended build session
- Mark completed slices clearly
- Record blocked slices explicitly rather than silently skipping them
