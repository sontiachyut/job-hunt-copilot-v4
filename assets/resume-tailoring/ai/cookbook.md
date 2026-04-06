# Resume Tailoring Cookbook

This file contains recipes — rules and guidelines for tailoring a resume for a specific role or track.
Each recipe is a decision that was made manually, logged here so any LLM can replicate it.

Operational SOP for SWE Experience tailoring lives at:
`resume-tailoring/ai/sop-swe-experience-tailoring.md`

---

## Recipe 1: Rewrite Technical Skills for Target Track

### When to use
When the base resume skills section does not reflect the target engineering track.

### Rule
1. Identify the target track (e.g. `frontend-ai`, `distributed-infra`, `genai`)
2. Remove skills that belong to a different track — they dilute the signal
3. Add skills the JD explicitly mentions
4. Reorder languages — most relevant to the role goes first
5. Rename skill category headers to match the track identity
6. Add new category lines if needed (e.g. `Frontend & Mobile`, `AI & Systems`)

### For `frontend-ai` track

**Remove from base (`distributed-infra`):**
- Languages: Scala, C++, Bash
- Categories: `Infrastructure & Systems` (rename/replace)
- Skills: Apache Spark, EMR, GCP, Terraform, MySQL, gRPC, Protocol Buffers, Load Balancing

**Add:**
- Languages: TypeScript, JavaScript (move to front), Kotlin
- New category `Frontend & Mobile`: React, Next.js, Node.js, Swift, Android (Kotlin)
- New category `AI & Systems`: LLMs, Agentic AI, Real-time Data Streams, WebSockets, Distributed Systems, System Design
- Data: Neo4j (graph DB, relevant for AI/recommendation systems)

**Result structure:**
```
Languages: Python, TypeScript, JavaScript, Kotlin, Java, Golang, SQL
Frontend & Mobile: React, Next.js, Node.js, Swift, Android (Kotlin)
AI & Systems: LLMs, Agentic AI, Real-time Data Streams, WebSockets, Distributed Systems, System Design
Cloud & DevOps: AWS (Lambda, S3, DynamoDB, API Gateway, EC2), Docker, Kubernetes, GitLab CI/CD
Data & Storage: PostgreSQL, DynamoDB, MongoDB, Neo4j, Redis
Testing & Reliability: Pytest, JUnit, Unit/Integration Testing, Monitoring, Performance Profiling
```

### Why
A recruiter or hiring manager scanning the skills section must immediately see the right signal.
If the first thing they see is "Scala, Apache Spark, EMR" — they think data engineer.
If they see "React, TypeScript, Node.js, LLMs" — they think frontend AI engineer.
The skills section sets the first impression for the entire resume.

---

## Recipe 2: Rewrite Summary for Target Track

### When to use
When the summary positions the candidate in the wrong engineering category.

### Rule
1. Remove the track-specific framing of the base resume (e.g. "distributed systems and infrastructure")
2. Replace with the target track's core identity
3. Keep: years of experience, MS CS, quantitative signal
4. Add: the primary discipline + the AI/domain angle specific to the role
5. Keep it to 1-2 sentences max — concise, no fluff

### For `frontend-ai` track (Intuitive JD)
**Original:**
> MS CS candidate with 3+ years of experience building large-scale distributed systems and infrastructure, focusing on system reliability, performance optimization, and cost-efficient cloud architecture

**Tailored:**
> MS CS candidate with 3+ years of experience building full-stack applications and real-time AI-driven systems, focused on translating complex intelligent systems into intuitive, high-performance user experiences across web and mobile platforms

### Why
The Intuitive JD says: "designing the human layer of real-time intelligent systems" and "turning complex AI into elegant, trustworthy user experiences."
The summary must echo this language — the hiring manager should feel like the candidate already speaks their language.

---

## Recipe 3: Rewrite Experience for Target JD

### When to use
When experience bullets are truthful but framed for the wrong track (e.g. read "data engineer" but need to read "systems engineer with clinical domain who understands how data reaches users").

### Before starting
- Read `ai/few-shot-examples/` for a worked example — study the `original.tex` (before), `tailored.tex` (after with WHY comments), and `context.md` (JD signals). This shows you what good tailoring looks like.
- Start from the base resume bullets in `input/base/distributed-infra/base-resume.tex` — these are your raw material to modify.

### Steps (follow in order)

**Step 0: Check section locks before editing**
- Read `output/tailored/{company}/{role}/meta.yaml`
- If `section-locks` contains a section (example: `projects`), do not edit that section in this tailoring pass
- If `experience-role-allowlist` exists, only edit those roles inside `EXPERIENCE`
- Treat locks as a hard constraint unless explicitly removed in `meta.yaml`

**Step 1: Find the relevant project context from the master profile**
- Read `input/profile.md` — the "Additional Context" section has deep-dive project information, and the "Metrics Bank" section has all numbers
- Find the part of the project that is relevant to this JD
- Pull that context out — this is what you'll build bullets from

**Step 2: Write the top 4 things the JD is asking for**
- Read the JD and extract the 4 main requirements/themes
- Write them down explicitly — these are your targets

**Step 3: Compare the JD's 4 points to the candidate's project work**
- Map: which of the 4 JD asks can this role's experience credibly cover?
- Don't force coverage of asks that belong to other resume sections (projects, intern role, hackathons)
- Be honest about what overlaps and what doesn't

**Step 4: Modify the bullets to cover the JD's 4 points — push as hard as you can**
- Reframe each bullet by changing **what you lead with** — same truthful work, different emphasis
- Lead with the **user-facing output** or **domain context**, not the infrastructure
- Connect optimization metrics to **user experience impact**, not infra metrics
- Add domain-specific context that maps to the target domain
- Use numbers from the Metrics Bank in `input/profile.md` — numbers are critical for credibility

**Step 5: Match the language of the JD in the bullets**
- Use the JD's own words and phrases where they naturally fit
- The hiring manager should feel like the candidate already speaks their language
- Don't force JD jargon — it should read naturally

**Step 6: Compare with the JD's 4 points again**
- Check: which of the 4 asks did we cover? Which did we miss?
- Whatever we couldn't cover in this section → flag it for other sections (projects, intern, hackathons, etc.)
- Each resume section carries a different part of the story

**Step 7: Modify the stack line**
- Start with the actual tools used in the project — truthful foundation
- Remove wrong-track signals — tools that scream the wrong engineer identity (e.g., EMR, Terraform → data engineer)
- Cross-check JD — add any JD-mentioned tools you actually used but didn't list (sometimes tools get left off because they weren't relevant to the old track)
- Reorder — JD-relevant tools go first (e.g., Python before Spark if JD mentions Python)
- Add tools that bridge to the JD's domain — not in the JD explicitly but signal the right identity (e.g., Tableau signals "I think about the visualization layer", Datadog signals "I care about what users see")
- NEVER add tools you didn't actually use in this role — those come from other resume sections

### Page Budget Rule: Same Lines as Base Resume
The tailored resume MUST render to the same number of pages and lines as the base resume. No extra lines, no fewer lines.

**Character budget per bullet (Helvetica 9pt, current layout):**
- 1-line bullet: ≤ 140 characters
- 2-line bullet: 145–255 characters (fill both lines — no wasted whitespace, no spill to line 3)
- Target: fill lines edge-to-edge. A half-empty second line wastes space.

**How to maintain total line count:**
1. Count the total rendered lines in the base resume's experience section
2. After tailoring, the total rendered lines must be the same
3. If a bullet grows from 1 line to 2 lines (+1), compensate by cutting a bullet elsewhere or shrinking another bullet from 2 lines to 1
4. Prefer cutting the weakest-signal bullet for the target JD (e.g., a testing bullet is weak signal for a frontend-AI role)
5. After all tailoring, compile PDF and verify 1 page — if it overflows, trim the weakest content

### Additional Rules
- Don't include client names — it signals consulting/SRE, not product engineering
- Do this in ONE pass (tailor directly for the JD), extract a reusable base later by stripping company-specific language
- Always preserve real numbers/metrics — they are the strongest credibility signal
- Respect `section-locks` and `experience-role-allowlist` in `meta.yaml`
- Current default edit scope is: `summary`, `technical-skills`, and `software-engineer` in `EXPERIENCE`

---

## Recipe 4: Line Budget — Keep Resume at 1 Page

### Rule
Each experience section has a fixed line budget. Tailoring changes content, NOT line count.

**SWE Experience: 4 bullets × 2 lines = 8 lines. No more, no less.**

Each bullet must be **210–255 characters** to render as 1.5 to 2 full lines (Helvetica 9pt, current layout).
- Below 210 → second line too short, looks incomplete
- Above 255 → spills to 3 lines (breaks budget)
- Second line should be at least half full

Other sections will have their own line budgets defined when we tailor them.

### How character budget was measured
- Compiled a test LaTeX file with the exact resume layout
- Real proportional English text fits ~140 chars per line
- 2 full lines = up to ~275 chars, but safe upper bound is 255 to account for word-wrap variation

### LaTeX Encoding Gotchas
- `>=` renders as `¿=` — fix with `$\geq$`
- `<=` renders as `¡=` — fix with `$\leq$`
- `%` → `\%`, `$` → `\$`, `&` → `\&`, `#` → `\#`
- Em dash: `---` for —, `--` for –

### Final Verification
Compile PDF with `pdflatex`. Must be exactly 1 page.

---

## Recipe 5: Step 6 Guardrails (Permanent)

### Rule
Step 6 artifacts must pass these guardrails before apply/compile:

1. **Numeric style required for metrics**
- Use digits/symbol form: `3+`, `50M+`, `1,500+`, `40\%`, `(6 hours to 3.6 hours)`.
- Do not use spelled-number metrics like `three plus years`, `fifty million`, `twenty five`.

2. **Summary must stay neutral**
- Do not include self-judging phrases like `aligned with <company> goals`.
- Keep summary factual, evidence-grounded, and role-relevant.

3. **Skills items must stay category-clean**
- Keep tools inside the existing category line.
- Do not add labels inside items such as `JD Stack:`.

4. **JD stack coverage required**
- If key stack tools are explicitly listed in the JD (e.g., Kafka/Iceberg/Trino/Airflow), they must appear in technical skills.

5. **Skills line budget required**
- Skills rows are validated against baseline row count + row-length thresholds to prevent overflow risk.

### Why
These failures caused repeated resume review loops. Guardrails make Step 6 deterministic and prevent the same mistakes from resurfacing across runs.

---

### For Intuitive JD — SWE role rewrite

**JD asks (4 main points):**
1. Build UI layer for AI/robotics systems
2. Visualize real-time data (telemetry, video, sensor data)
3. Prototype fast in clinical environments
4. Systems thinking + clinical context across full stack

**What SWE bullets can cover:** #4 fully, #2 partially. #1 and #3 come from other sections (projects, intern, hackathons).

**Stack line change:**
- From: `Python, Apache Spark, PostgreSQL, AWS (S3, EMR), Terraform, Docker, GitLab CI/CD`
- To: `Python, Spark, Databricks, Azure (ADF, ADLS Gen2), PostgreSQL, Tableau, Datadog, Docker, GitLab CI/CD`
- Why: Match actual project stack. Removes wrong-track signals (EMR, Terraform). Adds user-facing (Tableau) and observability (Datadog).

**Bullet reframe strategy:**
- Bullet 1: Lead with clinical user output (KPI dashboards for ICU clinicians), keep scale metrics
- Bullet 2: Show data-to-visualization pipeline (lakehouse → STAR schema → Tableau), connect to "near real-time clinical decision-making"
- Bullet 3: Reframe optimization from cost savings to user experience latency (data-to-dashboard)
- Bullet 4: Add safety-critical healthcare context (PHI, >=99% availability, regulated, multi-tenant)

**Key impression per bullet:**
1. "This person builds things that clinicians use in ICUs" — keywords: KPI dashboards, ICU, Ventilation, Hemorrhage, clinical, real-time
2. "This person thinks end-to-end, from raw data to user-facing dashboards" — keywords: lakehouse layers, STAR schema, consumed by Tableau dashboards
3. "This person optimizes for user experience, not just infra" — keywords: data-to-dashboard latency, near real-time, clinician-facing analytics
4. "This person has operated in safety-critical healthcare systems" — keywords: multi-tenant, PHI, >=99% availability, regulated healthcare

### Why
Experience bullets are the strongest signal in screening. Recruiters infer role identity from verbs + system scope + connection to users.
Reframing from pipeline internals to end-to-end clinical system outcomes preserves truth while shifting the reader's perception from "data engineer" to "systems engineer who understands how data reaches clinicians."
Each resume section carries a different part of the story — the SWE role's job is to say: "I've operated in safety-critical clinical systems and I understand how data flows to what users see." Frontend and prototyping signals come from other sections.
