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

- `RT-03-S1` Task 10 - Steps 6 and 7
- Owner role: `tailoring-engineer`
- Why now:
  - RT-02 is now complete, so the next dependency-gated work is using the persisted Step 5 theme decision to drive project scoring and selection
  - evidence selection is the first slice that starts replacing the legacy backend-heavy candidate payload with theme-aware, auditable content selection
  - Step 6 and Step 7 are the minimum bounded slice that can hand trustworthy inputs into later experience and project evidence mapping

## Latest Completed Slice

`RT-02-S2` completed with:
- add `job_hunt_copilot/tailoring/steps/step_04_theme_scores.py` and `step_05_theme_decision.py` to persist auditable per-theme scoring, the winning theme, runner-up, margin, and fixed-vs-runtime template routing metadata
- wire `job_hunt_copilot/resume_tailoring.py` scaffolds, manifest updates, and intelligence generation so Step 4 and Step 5 artifacts are emitted alongside the existing compatibility outputs
- keep the legacy Step 6-plus path alive by continuing to feed it the compatibility track while exposing the new selected theme as the canonical classification result for the redesign contract
- validate Garmin-style frontend classification and distributed-infra regression coverage with `python3.11 -m pytest tests/test_pipeline_steps.py tests/test_resume_tailoring.py tests/test_theme_classifier.py tests/test_base_templates.py -q`

## Next Execution Target

For the next unattended builder cycle, the target is:
- implement `job_hunt_copilot/tailoring/steps/step_06_project_scores.py` and `step_07_project_selection.py`
- score every project against the Step 3 or Step 5 inputs and persist traceable relevance coverage for each candidate project
- select exactly four projects with Job Hunt Copilot first, plus explicit inclusion, exclusion, and fallback reasoning for the remaining project slots
- validate project-scoring and project-selection artifacts before moving into Step 8 and Step 9 evidence mapping

## Done-When Summary

The redesign program is done only when:
- the new 16-step tailoring pipeline exists and is wired into the runtime
- Garmin Aviation classifies and tailors as `frontend_web`
- Step 16 rejects structurally valid but JD-misaligned resumes
- the redesign is proven by targeted and broad tests
- the old track or focus path is removed only after the new path is green

## Next Slice After Current Focus

If `RT-03-S1` completes cleanly, the next slice is:
- `RT-03-S2` Task 11 - Steps 8 and 9

If `RT-03-S1` is blocked, the builder should:
- record the blocker explicitly in `build-agent/state/build-board.yaml`
- log the attempted work in `build-agent/state/build-journal.md`
- add a short handoff note in `build-agent/state/codex-progress.txt`
- stop cleanly instead of jumping ahead to unrelated slices
