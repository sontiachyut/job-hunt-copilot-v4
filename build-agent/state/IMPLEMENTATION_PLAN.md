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

- `RT-01-S7` Task 7 - Update master profile with Job Hunt Copilot
- Owner role: `tailoring-engineer`
- Why now:
  - Template A and Template B now exist, so the final remaining static-foundation gap is the profile evidence update required by FR-RT-34D
  - the Job Hunt Copilot project details must land in the source profile before project scoring, evidence mapping, and assembly can use them honestly
  - completing Task 7 closes RT-01 cleanly and unlocks the classification-core phase without leaving the redesign underpowered on its own flagship project

## Latest Completed Slice

`RT-01-S6` completed with:
- create `assets/resume-tailoring/base/projects-first/base-resume.tex` from the applied-AI source resume so Template A now exists in-tree with the required projects-first section order
- create `assets/resume-tailoring/base/experience-first/base-resume.tex` as the canonical Template B asset while leaving the legacy `distributed-infra` base in place for the old runtime
- extend `job_hunt_copilot/paths.py` with explicit Template A or B resolution plus step-01 through step-16 artifact path helpers for the redesign pipeline
- add bootstrap and fixture support so fresh builds require the new canonical template pair while the legacy tailoring runtime still ignores those template-only directories during old track selection
- add `tests/test_base_templates.py` and update bootstrap, tailoring, and smoke-harness tests to validate section order, path resolution, canonical template presence, and legacy-runtime stability
- validate with `python3.11 -m pytest tests/test_base_templates.py tests/test_bootstrap.py tests/test_resume_tailoring.py tests/test_smoke_harness.py -q`
- compile-smoke both canonical base templates in temporary directories with the local LaTeX toolchain

## Next Execution Target

For the next unattended builder cycle, the target is:
- update `assets/resume-tailoring/profile.md` with the Job Hunt Copilot project details required by FR-RT-34D
- update `resume-tailoring/input/profile.md` or the relevant profile-sync surface so the redesign runtime can consume the same Job Hunt Copilot evidence
- keep the additions evidence-grounded and aligned with the new summary, skill, and project-evidence pools
- validate the profile-update slice before advancing into RT-02 classification work

## Done-When Summary

The redesign program is done only when:
- the new 16-step tailoring pipeline exists and is wired into the runtime
- Garmin Aviation classifies and tailors as `frontend_web`
- Step 16 rejects structurally valid but JD-misaligned resumes
- the redesign is proven by targeted and broad tests
- the old track or focus path is removed only after the new path is green

## Next Slice After Current Focus

If `RT-01-S7` completes cleanly, the next slice is:
- `RT-02-S1` Task 8 - Steps 1 through 3

If `RT-01-S7` is blocked, the builder should:
- record the blocker explicitly in `build-agent/state/build-board.yaml`
- log the attempted work in `build-agent/state/build-journal.md`
- add a short handoff note in `build-agent/state/codex-progress.txt`
- stop cleanly instead of jumping ahead to unrelated slices
