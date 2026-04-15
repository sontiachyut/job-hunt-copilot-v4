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

- `RT-01-S5` Task 5 - Summary and skill category templates
- Owner role: `tailoring-engineer`
- Why now:
  - the experience and project evidence pools now exist, so the next static-foundation dependency is the theme-specific summary and skill-template layer
  - Step 12 and Step 13 need explicit per-theme templates before the new pipeline can compose grounded summaries and skill sections
  - this keeps the build inside the static-foundations phase while advancing the content templates that the redesign depends on

## Latest Completed Slice

`RT-01-S4` completed with:
- create `assets/resume-tailoring/data/bullet_pool_projects.yaml` with evidence-grounded project atoms for Job Hunt Copilot, LinkedIn Assistant, TIAA, Edge Face Recognition, National Parks, Health Monitoring, Content Recommendation, and Cloud Meraki
- extend `job_hunt_copilot/tailoring/bullet_pool.py` with validated project-pool loading, theme filtering, and alias-aware JD-overlap ranking helpers for project atoms
- extend `tests/test_bullet_pool.py` with targeted project-pool coverage for loading, theme filtering, and alias-aware ranking
- validate with `python3.11 -m pytest tests/test_bullet_pool.py -q`
- regression-check the adjacent keyword and theme layers with `python3.11 -m pytest tests/test_keyword_system.py -q` and `python3.11 -m pytest tests/test_theme_classifier.py -q`

## Next Execution Target

For the next unattended builder cycle, the target is:
- create `assets/resume-tailoring/data/summary_templates.yaml`
- create `assets/resume-tailoring/data/skill_categories.yaml`
- add targeted tests or loaders as needed for the theme-template slice
- validate the summary and skill-template slice before advancing to base-resume templates

## Done-When Summary

The redesign program is done only when:
- the new 16-step tailoring pipeline exists and is wired into the runtime
- Garmin Aviation classifies and tailors as `frontend_web`
- Step 16 rejects structurally valid but JD-misaligned resumes
- the redesign is proven by targeted and broad tests
- the old track or focus path is removed only after the new path is green

## Next Slice After Current Focus

If `RT-01-S5` completes cleanly, the next slice is:
- `RT-01-S6` Task 6 - Template A and Template B base resumes

If `RT-01-S5` is blocked, the builder should:
- record the blocker explicitly in `build-agent/state/build-board.yaml`
- log the attempted work in `build-agent/state/build-journal.md`
- add a short handoff note in `build-agent/state/codex-progress.txt`
- stop cleanly instead of jumping ahead to unrelated slices
