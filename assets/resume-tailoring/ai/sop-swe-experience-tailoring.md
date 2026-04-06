# SOP — SWE Experience Tailoring

## Purpose
Create 4 high-signal resume bullets for the `Software Engineer` role by mapping JD asks to the most relevant part of the SWE end-to-end project pipeline.

## Scope
- This SOP is only for tailoring the `Software Engineer` experience block.
- Section and role edit permissions must be read from `meta.yaml` before any edits.

## Inputs
- Job context: `resume-tailoring/input/job-postings/{company}-{role}.md`
- Master profile: `resume-tailoring/input/profile.md`
- Target resume: `resume-tailoring/output/tailored/{company}/{role}/resume.tex`
- Constraints: `resume-tailoring/output/tailored/{company}/{role}/meta.yaml`
- Rules and examples:
  - `resume-tailoring/ai/cookbook.md`
  - `resume-tailoring/ai/few-shot-examples/{company-role}/`

## Outputs
- Updated SWE bullets and stack line in `resume.tex`
- Compiled 1-page PDF
- Decision logs in cookbook + few-shot + workflow log

## Procedure

### Step 0: Load Constraints
1. Read `meta.yaml`.
2. Enforce `section-locks`.
3. Enforce `experience-role-allowlist`.
4. Confirm `scope-baseline-file` exists (or create with `scope_guard.py --snapshot`).
5. If `software-engineer` is not allowed, stop.

### Step 1: Extract JD Signals (JD-only, no filtering)
1. Parse the JD and capture all asks:
   - Responsibilities
   - Required skills/stack
   - Preferred skills
   - Domain constraints (real-time, clinical, safety, reliability, collaboration)
2. Convert asks to normalized signal tags.
3. Prioritize into:
   - `must-have`
   - `strong signal`
   - `nice-to-have`

Output: `jd_signal_map`

### Step 2: Retrieve Relevant SWE Pipeline from Master Profile
1. Read the SWE project context in `profile.md` (work experience + additional context + metrics bank).
2. Identify the exact pipeline segment(s) related to JD signals.
3. Build a retrieval table:
   - `pipeline-part`
   - `what-it-does`
   - `evidence` (tools, metrics, constraints, outcomes)
   - `jd-signals-covered`

Output: `swe_pipeline_slice`

### Step 3: Elaborate Selected Pipeline Segment(s)
1. Expand only the selected SWE pipeline part(s):
   - Add deeper mechanism detail
   - Add clearer user/clinical flow
   - Add reliability/operational context
2. Keep elaboration inside the SWE project boundary.
3. Do not introduce unrelated domains.
4. Keep all quantitative claims consistent with known metrics.

Output: `elaborated_swe_context`

Note:
- Formal policy for controlled elaboration levels is tracked in `TODO.md` and will be finalized separately.

### Step 4: Map and Draft 4 Bullets
1. Map: `jd_signal_map` + `elaborated_swe_context`.
2. Draft exactly 4 bullets for SWE role using this structure:
   - user/domain outcome -> technical action -> metric -> impact
3. Ensure each bullet has a distinct purpose:
   - scale + user impact
   - end-to-end flow
   - optimization tied to user-facing effect
   - reliability/compliance/operations
4. Update stack line for SWE role to match selected pipeline evidence.

Output: `candidate_swe_bullets`

### Step 5: Apply Resume Constraints
1. Respect line/page budget rules from cookbook.
2. Keep LaTeX-safe encoding (`\%`, `\$`, `$\geq$`, etc.).
3. Avoid client-name leakage if rule says not to include.
4. Preserve 1-page final output.
5. Enforce Step 6 guardrails:
   - Numeric metric style (no spelled-number metrics).
   - Neutral summary (no `aligned with ... goals` language).
   - Skills contain JD-required stack terms.
   - No label text inside skills items (example: `JD Stack:`).
   - Skills row/line budget within baseline tolerance.

### Step 6: Compile and Verify
1. Run scope check: `resume-tailoring/src/scope_guard.py --check`.
2. Compile using `resume-tailoring/src/compile_resume.py --enforce-scope`.
3. Verify:
   - compile success
   - PDF is 1 page
   - no overflow in Experience section

### Step 7: Log Decisions
1. Update `resume-tailoring/ai/cookbook.md` with rule-level decisions.
2. Update few-shot `original.tex` and `tailored.tex` with WHY notes.
3. Update workflow log (`automate_smooth_as_butter.md`) with completion status.

## Acceptance Checklist
- 4 SWE bullets updated.
- JD must-have signals addressed as much as SWE scope allows.
- Locks respected (`section-locks`, `experience-role-allowlist`).
- Numbers and stack remain consistent with project context.
- Numeric format, summary neutrality, and skills-budget checks pass.
- Resume compiles and remains 1 page.
- Decision logs updated in all required locations.
