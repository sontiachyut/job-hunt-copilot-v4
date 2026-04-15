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

- `RT-02-S2` Task 9 - Steps 4 and 5
- Owner role: `tailoring-engineer`
- Why now:
  - RT-02-S1 now persists deterministic step-01 through step-03 artifacts, so the classifier can move from extraction into spec-backed theme scoring without reworking bootstrap again
  - Garmin validation depends on Steps 4 and 5 selecting `frontend_web` and the correct template from the new classified-signal contract
  - theme scoring and decision artifacts are the remaining open boundary before evidence selection work can start

## Latest Completed Slice

`RT-02-S1` completed with:
- add `job_hunt_copilot/tailoring/steps/step_01_jd_sections.py`, `step_02_signals_raw.py`, and `step_03_signals_classified.py` to implement deterministic JD sectioning, raw signal extraction, and classified-signal weighting from JD-only inputs
- wire `job_hunt_copilot/resume_tailoring.py` bootstrap and intelligence generation to scaffold and emit `step-01` through `step-03` artifacts while keeping legacy downstream artifacts available as compatibility outputs
- update runtime tests so the intelligence manifest now reflects the new 16-step contract and the generated step-03 payload is persisted to both the new canonical artifact path and the temporary legacy alias
- validate with `python3.11 -m pytest tests/test_pipeline_steps.py tests/test_resume_tailoring.py tests/test_base_templates.py -q`
- validate classifier handoff compatibility with `python3.11 -m pytest tests/test_theme_classifier.py -q`

## Next Execution Target

For the next unattended builder cycle, the target is:
- implement `job_hunt_copilot/tailoring/steps/step_04_theme_scores.py` and `step_05_theme_decision.py`
- score all 9 themes from the new step-03 classified-signal artifact and record the runner-up, margin, and template choice as explicit step artifacts
- update runtime wiring so theme selection starts feeding the redesign contract without prematurely deleting the legacy downstream path
- validate Garmin-targeted and synthetic classifier cases before advancing into project scoring and evidence selection

## Done-When Summary

The redesign program is done only when:
- the new 16-step tailoring pipeline exists and is wired into the runtime
- Garmin Aviation classifies and tailors as `frontend_web`
- Step 16 rejects structurally valid but JD-misaligned resumes
- the redesign is proven by targeted and broad tests
- the old track or focus path is removed only after the new path is green

## Next Slice After Current Focus

If `RT-02-S2` completes cleanly, the next slice is:
- `RT-03-S1` Task 10 - Steps 6 and 7

If `RT-02-S2` is blocked, the builder should:
- record the blocker explicitly in `build-agent/state/build-board.yaml`
- log the attempted work in `build-agent/state/build-journal.md`
- add a short handoff note in `build-agent/state/codex-progress.txt`
- stop cleanly instead of jumping ahead to unrelated slices
