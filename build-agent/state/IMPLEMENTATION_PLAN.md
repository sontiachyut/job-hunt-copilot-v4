# Implementation Plan

This plan repoints the build agent from the completed BA-10 program to the resume-tailoring JD-content-fit redesign on branch `resume-tailoring`.

Canonical inputs for this build program:
- `prd/spec.md`
- `prd/test-spec.feature`
- `docs/superpowers/plans/2026-04-14-resume-tailoring-jd-fit.md`
- `build-agent/state/build-board.yaml`

## Current Planning Result

- The old builder backlog is intentionally retired on this branch. The canonical unattended build target is now the resume-tailoring redesign only.
- The redesign is not a prompt tweak. It is a structural replacement of the old 3-track or 4-focus path with a 9-theme, evidence-pool-driven, 16-step pipeline.
- The Garmin Aviation example is the primary repro that exposed the bug, but the target is general JD-content fit across all role families.
- The legacy tailoring path remains in-tree until the new pipeline passes targeted Garmin validation and broader regression coverage.

## Working Constraints

- Stay on branch `resume-tailoring` for the entire program.
- Do not modify `main` as part of this unattended build program.
- Do not delete or bypass legacy tailoring code until the redesign passes focused and broad validation.
- Prefer additive work under `job_hunt_copilot/tailoring/` and supporting assets before integration cutover.
- Use one bounded slice per unattended build session and checkpoint state after every meaningful slice.

## Phase Order

1. Static foundations
   - Task 1: Technology adjacency map
   - Task 2: Theme term sets and classifier
   - Task 3: Experience bullet evidence pool
   - Task 4: Project evidence atoms
   - Task 5: Summary templates and skill category templates
   - Task 6: Template A and Template B base resumes
   - Task 7: Update master profile with Job Hunt Copilot

2. Classification and decision core
   - Task 8: Steps 1 through 3
   - Task 9: Steps 4 and 5

3. Evidence selection and content generation
   - Task 10: Steps 6 and 7
   - Task 11: Steps 8 and 9
   - Task 12: Step 10 gap analysis
   - Task 13: Step 11 bullet ranking and allocation
   - Task 14: Steps 12 through 14

4. Assembly and verification
   - Task 15: Step 15 resume assembly and page fill
   - Task 16: Step 16 verification

5. Runtime integration
   - Task 17: Pipeline orchestration
   - Task 18: Wire up bootstrap and finalize

6. Validation and rollout
   - Task 19: Garmin integration validation
   - Task 20: Rewrite prompt, cookbook, and SOP
   - Task 21: Full test suite and manual verification
   - legacy-path retirement only after Task 21 is green

## Current Focus

- `RT-02-S1` Task 8 - Steps 1 through 3
- Owner role: `tailoring-engineer`
- Why now:
  - RT-01 is now complete, so the redesign can move from static assets into deterministic classification logic without foundation gaps
  - Garmin validation depends on Steps 1 through 3 producing auditable JD sections and classified signals before theme scoring can exist
  - implementing the first three step artifacts establishes the contract the rest of the 16-step pipeline will build on

## Latest Completed Slice

`RT-01-S7` completed with:
- update `assets/resume-tailoring/profile.md` so Job Hunt Copilot now exists as the first project with stack, runtime, workflow-contract, HITL-control, and validation evidence aligned to FR-RT-34D
- refresh the gitignored runtime mirror at `resume-tailoring/input/profile.md` so the working tailoring surface matches the tracked source profile byte-for-byte
- extend the profile metrics bank with Job Hunt Copilot validation counts so later tailoring slices can preserve those quantitative signals
- validate profile insertion and mirror consistency with a targeted local script
- validate the changed asset path with `python3.11 -m pytest tests/test_resume_tailoring.py tests/test_smoke_harness.py -q`

## Next Execution Target

For the next unattended builder cycle, the target is:
- implement `job_hunt_copilot/tailoring/steps/step_01_jd_sections.py`, `step_02_signals_raw.py`, and `step_03_signals_classified.py`
- produce deterministic step-01 through step-03 artifacts using the new JD-signal contract instead of the legacy track or focus logic
- add or update targeted tests that lock the first three redesign steps to spec-backed behavior
- validate the first classification slice before advancing into theme scoring and template selection

## Done-When Summary

The redesign program is done only when:
- the new 16-step tailoring pipeline exists and is wired into the runtime
- Garmin Aviation classifies and tailors as `frontend_web`
- Step 16 rejects structurally valid but JD-misaligned resumes
- the redesign is proven by targeted and broad tests
- the old track or focus path is removed only after the new path is green

## Next Slice After Current Focus

If `RT-01-S7` completes cleanly, the next slice is:
- `RT-02-S2` Task 9 - Steps 4 and 5

If `RT-02-S1` is blocked, the builder should:
- record the blocker explicitly in `build-agent/state/build-board.yaml`
- log the attempted work in `build-agent/state/build-journal.md`
- add a short handoff note in `build-agent/state/codex-progress.txt`
- stop cleanly instead of jumping ahead to unrelated slices
