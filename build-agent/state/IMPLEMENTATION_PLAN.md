# Implementation Plan

This is the human-readable prioritized checklist for the build team.

It should stay aligned with:
- `prd/spec.md`
- `prd/test-spec.feature`
- `build-agent/state/build-board.yaml`

## Initial Order

1. Foundation and schema
2. Supervisor control plane
3. macOS local runtime helpers
4. Manual capture path
5. Gmail alert intake
6. Resume tailoring runtime
7. People search and discovery
8. Drafting and sending
9. Delivery feedback and review surfaces
10. Validation and hardening

## Rules

- Break large items into bounded slices before implementation
- Prefer one primary slice per unattended build session
- Mark completed slices clearly
- Record blocked slices explicitly rather than silently skipping them

