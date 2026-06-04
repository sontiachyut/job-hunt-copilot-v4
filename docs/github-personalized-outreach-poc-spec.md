# Role-Split Outreach POC Spec

## Status

Draft POC spec. This document supersedes the earlier GitHub-first outreach
strategy. The current strategy is simpler: classify the recipient by role type,
draft the first email from Apollo-backed role and career-path data, and keep
the ask focused on guidance rather than referrals.

## Purpose

Build a first-touch outreach flow that sends a short email with one of two
intent patterns:

1. a manager-facing role-fit email
2. a technical-contact career-guidance email

This flow is distinct from:

1. direct referral requests
2. follow-up emails
3. GitHub-common-ground outreach

The first email should earn attention, make the sender's goal clear, and ask
for a small amount of time.

For the current technical-path implementation, the body should target roughly
225 to 240 words.

For the current managerial-path implementation, the body should target roughly
185 to 215 words.
That target should include the greeting, opener, bullet sections, and fixed
CTA block, but exclude the signature.

## Operating Principle

This POC should remain spec-driven.

That means:

1. this document defines behavior
2. prompts implement the behavior
3. deterministic Python should enforce classification and input boundaries
4. tests should validate the behavior described here

## Primary Outcome

Given one contact record, the system should produce a draft email that:

1. is clearly tailored to the recipient type
2. sounds human and respectful
3. makes the sender's intent clear
4. asks for a low-pressure conversation, not a referral

## Core Strategy

The workflow should no longer depend on GitHub research as the primary basis
for the first email.

Instead, the workflow should:

1. enrich the contact with Apollo
2. classify the contact as managerial or technical based on current title
3. choose the matching email strategy
4. draft a concise first email from that path

The first email should not ask directly for a referral.

## Recipient Classification Rule

The workflow should classify the recipient from the current Apollo title.

### Managerial path

Use the managerial path when the current title clearly indicates management or
leadership, for example:

- `manager`
- `director`
- `head`
- `vp`
- `vice president`
- `chief`

### Technical path

Use the technical path when the current title clearly indicates an individual
technical builder or technical lead, for example:

- `engineer`
- `developer`
- `architect`
- `software`
- `technical lead`
- `tech lead`
- `staff`
- `principal`
- `machine learning`
- `ai`
- `ml`

### Recruiting titles

Recruiting titles should currently route through the managerial path.

If the current title looks primarily recruiting-oriented, for example:

- `recruiter`
- `talent`
- `sourcer`
- `people ops`

the contact should be drafted through the managerial path by default.

## Research Source Boundary

For this simplified POC, drafting should rely primarily on:

1. Apollo enrichment
2. existing job-posting and role context already in the system

This strategy does not require GitHub research, personal-site research, or
broader company research for the first email.

The workflow may still store LinkedIn URL when Apollo provides it, but the
drafting logic should not depend on private LinkedIn data.

## Required Contact Data

The deterministic pipeline should collect and normalize at least:

- contact name
- first name
- current title
- current company
- location when available
- current work email when available
- LinkedIn URL when available
- headline when available
- Apollo person id
- Apollo employment history when available

For managerial-path drafts, the pipeline should also pass:

- the job role being pursued
- the target company/job-posting context

When a job posting is the trigger for the outreach, the deterministic pipeline
should also derive a compact JD summary from that posting for the managerial
path.
That JD summary should include only the parts most relevant to sender-fit
selection, such as:

- role title
- core engineering responsibilities
- key technical requirements
- domain or product context

The pipeline should not pass the full raw JD into the drafter when a compact
summary can represent the relevant context.

The full raw Apollo enrichment payload should still be persisted as an artifact.

## Required Sender Context

The sender context passed into drafting should remain intentionally small and
stable.

For this POC, it should include:

- sender name
- sender LinkedIn URL
- sender email
- sender phone
- sender background summary
- `Job Hunt Copilot` repo URL
- short `Job Hunt Copilot` summary
- availability window

The sender background summary should support these facts:

1. recent `MS in CS` from `ASU`
2. about `3 years` of experience building large-scale systems
3. one additional short professional-background line

## Research Record

Before any AI drafting step runs, deterministic Python should normalize the
contact into a research record.

That research record should support at least:

- contact identity fields
- current role/title
- current company
- Apollo employment history
- job-posting context when applicable
- sender context
- selected recipient path

The deterministic pipeline may also produce a full markdown dossier for
debugging and review, but the drafter should receive only the bounded fields
needed for the selected path.

## JD Relevance Extraction Rule

When a job posting triggered the outreach for the managerial path,
deterministic Python should reduce the JD into a bounded relevance pack before
drafting.

For this POC, Python may do that deterministically by selecting only:

1. the role title
2. the most relevant engineering responsibilities
3. the most relevant technical skills or systems signals
4. one short domain or product-context line when helpful

Python should do this with bounded heuristics such as:

1. heading detection
2. bullet extraction
3. keyword scoring for engineering responsibilities and technical requirements
4. removal of known low-signal sections

It should cut obviously unnecessary sections such as:

1. generic equal-opportunity language
2. broad benefits and perks
3. repeated company marketing copy
4. long legal or policy sections

The goal is not to summarize the whole JD. The goal is to pass only the
minimum role-fit context needed to support the managerial draft.

This deterministic extraction should be treated as a bounded reduction step,
not as a perfect semantic understanding step. It should work well for many JDs,
but it should also have a safe fallback when the JD structure is noisy.

If deterministic extraction cannot confidently identify clean responsibility and
requirements sections, it should fall back to a minimal pack containing:

1. the role title
2. up to three technical-looking requirement or responsibility lines
3. one short domain or product-context line when available

## Managerial Path Intent

The managerial path is for recipients who are closer to hiring, team
leadership, or internal routing.

This includes recruiting-oriented recipients for now.

The email should read like a short, respectful application-style note.

It should:

1. reference the role the sender saw
2. explain why the sender is a plausible fit
3. mention the sender's relevant technical background and skills
4. ask for a short conversation
5. allow a polite request to forward the note to the right person when the
   recipient is not the best owner

This path is job-role-centric rather than career-path-centric. It should sell
fit directly through evidence rather than through broad networking language.

## Technical Path Intent

The technical path is for engineers, technical leads, staff/principal
engineers, and other technical individual contributors.

The email should be a career-guidance email, not a cover letter.

It should:

1. say the sender came across the recipient's LinkedIn profile
2. express admiration for the recipient's career path and current role
3. say the sender wants to grow in a similar way and ship software like the
   recipient
4. briefly introduce the sender
5. mention `Job Hunt Copilot`
6. make the sender's job-hunt guidance ask explicit

## Technical Path Draft Shape

The technical path should currently use a concise 4-paragraph structure.

### Paragraph 1

Paragraph 1 should:

1. begin with `I came across your LinkedIn profile and really admired your path from ...`
2. reference the recipient's career path from Apollo employment history
3. mention the recipient's current role explicitly
4. make clear that the sender admires that path and role
5. say the sender wants to grow in a similar way and ship software like them

When this admiration line is written, it should stay focused on growing in a
similar direction and shipping software at that level. It should not drift into
phrasing about building teams.

For this path, Paragraph 1 should usually mention the most relevant two or
three past companies plus the current role. That is the preferred balance
between showing real profile research and keeping the opener concise.

Those steps do not need to be the most recent ones. The drafter may choose any
two or three relevant steps from the full Apollo employment history when that
produces a stronger growth story.

When possible, these earlier steps should be phrased primarily as company
transitions, while the current step should use the recipient's exact current
role and company. For the technical path, the current step should keep the
exact sourced current title and company rather than a shortened variant. The
opener should use just company names for past steps rather than past role
titles.

Earlier non-software steps do not have to be excluded automatically. The
opener may include one when it makes the recipient's growth story more
interesting or more meaningful, as long as the paragraph stays selective and
concise.

The preferred closing line for this opener is:

`I'd love to grow in a similar direction and ship software at that level over time.`

Close variants with the same meaning are also allowed in the second sentence,
as long as they keep the focus on the path standing out and the sender wanting
to grow in a similar direction and ship software at that level over time.

For this technical path, the emotional framing should stay closer to `admired`
than to a softer word like `interesting`.

This paragraph should stay personal and respectful.

It should not:

1. become a long chronology
2. drift into generic praise
3. sound like a referral ask

### Paragraph 2

Paragraph 2 should give sender background context.

For the current technical-path POC, Paragraph 2 should stay fully fixed as:

`I recently graduated from ASU with an MS in Computer Science. I also have about three years of experience building large-scale systems, including distributed high-availability data services in Python and Scala on Azure that handled ~580 TPS in production while maintaining 99.95% uptime.`

Deterministic Python should append this exact paragraph after the generated
Paragraph 1. `codex exec` should not generate or rewrite Paragraph 2 for the
technical path.

### Paragraph 3

Paragraph 3 should explain the sender's current project.

It should include:

1. `Job Hunt Copilot` as `an AI workflow automation tool`
2. the idea that the sender has a passion for learning new technology and
   building products, and that this is part of what led to building `Job Hunt
   Copilot`
3. the exact idea that the tool `helps me connect with strong engineers and
   technical leaders while supporting my job search`
4. the fact that this email is a live example of that autonomous workflow
5. the raw repo URL near the `Job Hunt Copilot` mention

This paragraph should use five fixed sentences, and the sentence order should stay
fixed:

1. passion for learning/building products led to `Job Hunt Copilot`
2. what the tool does
3. `This email is a live example of that autonomous workflow.`
4. production-minded note
5. repo link sentence

The first sentence of this paragraph should stay fixed as:

`I'm passionate about learning new technology and building products, which is what led me to build Job Hunt Copilot.`

The second sentence of this paragraph should stay fixed as:

`It's an AI workflow automation tool I built to help me connect with strong engineers and technical leaders while supporting my job search.`

The third sentence of this paragraph should stay fixed as:

`This email is a live example of that autonomous workflow.`

The fourth sentence of this paragraph should stay fixed as:

`It's something I built from scratch and have been shaping with real production use in mind, not just as a one-off prototype.`

The fifth sentence of this paragraph should stay fixed as:

`If you're interested, the repo is here: <repo_url>`

So the full fixed Paragraph 3 is:

`I'm passionate about learning new technology and building products, which is what led me to build Job Hunt Copilot. It's an AI workflow automation tool I built to help me connect with strong engineers and technical leaders while supporting my job search. This email is a live example of that autonomous workflow. It's something I built from scratch and have been shaping with real production use in mind, not just as a one-off prototype. If you're interested, the repo is here: <repo_url>`

### Paragraph 4

Paragraph 4 should:

1. say the sender is currently in the job-hunt process
2. say the sender would really value the recipient's guidance
3. say the sender wants to build a career like the recipient's
4. ask whether the recipient is open to a `10-minute` conversation in the next
   week or two
5. include the availability line in the same paragraph

This paragraph should be low-pressure and easy to answer.

For this path, the sentence `I'm currently in the job hunt process, and I'd
really value your guidance.` should also stay fixed.

For this path, the sentence `I want to build a career like yours.` should also
stay fixed.

For this path, the final question should stay fixed as:

`Would you be open to a 10-minute conversation sometime in the next week or two?`

The preferred availability line for this path is:

`I'm usually free weekdays between 8 AM and 6 PM MST, and I'm flexible outside that too if another time works better for you.`

So the full fixed Paragraph 4 is:

`I'm currently in the job hunt process, and I'd really value your guidance. I want to build a career like yours. Would you be open to a 10-minute conversation sometime in the next week or two? I'm usually free weekdays between 8 AM and 6 PM MST, and I'm flexible outside that too if another time works better for you.`

## Managerial Path Draft Shape

The managerial path should currently use a concise problem-solver structure.

### Paragraph 1

Paragraph 1 should:

1. reference the specific job role the sender saw
2. mention the company
3. briefly explain why the role caught the sender's attention
4. include an early proof-of-concept offer so it appears high in inbox
   preview text
5. stay at exactly three sentences

For this POC, managerial `paragraph_1` should stay at exactly three sentences:

1. `I hope you're doing well.`
2. `I came across the <Role Title> opening at <Company> and wanted to reach out because the role looks closely aligned with the kind of <role-relevant area> I've been trying to work on.`
3. `**If helpful, I'd be happy to build a small proof of concept based on my understanding of the challenges the team is working on and share the repo.**`

The phrase `I hope you're doing well.` should stay fixed, and the
`<role-relevant area>` phrasing in sentence 2 may vary based on the role/JD so
the opener reads less like a template.
The proof-of-concept sentence should stay fixed in meaning and should be bolded
in the rendered email body.

### Problem Hypotheses

This section should:

1. be rendered under the fixed heading:
   `My read from the JD is that the team is likely working on:`
2. use exactly three short bullets
3. stay specific and non-generic
4. infer challenges cautiously from the JD rather than claiming certainty
5. focus on concrete engineering challenges, not company boilerplate
6. avoid repeating the exact same idea across all bullets

### Relevant Background

This section should:

1. be rendered under the fixed heading:
   `Relevant background from my side:`
2. use exactly three short bullets
3. stay highly scannable for managers
4. choose bullets dynamically based on the role/JD and sender evidence
5. prefer action-led bullets
6. prefer one strongest professional proof, one second strong systems proof,
   and an optional `Job Hunt Copilot` bullet when relevant
7. include the repo URL in the same `Job Hunt Copilot` bullet when used
8. explicitly mention `ASU` and `about three years of experience` somewhere in
   this section when those facts do not already appear elsewhere in the body

For the managerial path output contract, this section should be represented as
a structured list of bullet strings rather than one preformatted paragraph
string. Deterministic Python should render the heading and bullet formatting.

### Paragraph 4

Paragraph 4 should:

1. mention the attached resume briefly
2. ask for a `10-minute` conversation
3. make clear the conversation is to understand the team's real challenges
4. mention the sender may build a small proof of concept afterward if helpful
5. include a polite forward-to-the-right-person note when the recipient is not
   the best contact
6. stay at exactly four sentences

The preferred managerial CTA wording is:

`I've attached my resume for context. Would you be open to a brief 10-minute conversation? I'd love to better understand the challenges the team is actually focused on, and if helpful, I'd be happy to build a small proof of concept afterward and share the repo. If this is better routed elsewhere, I'd appreciate a forward to the right person internally.`

This managerial path is intentionally provisional and will be tightened further
in a later ambiguity pass.

## Credibility Rule

The email must establish why the sender is worth replying to.

The credibility layer should come from:

1. concise professional background
2. `Job Hunt Copilot` as a current project
3. the fact that the workflow is autonomous and this email came through it

`Job Hunt Copilot` should support credibility, not dominate the email.

The sender should sound like someone building a real system, not pitching a
novelty tool.

## Required `Job Hunt Copilot` Facts

When `Job Hunt Copilot` appears in the technical path, the draft should
communicate, directly or equivalently:

1. `Job Hunt Copilot` is the sender's own project
2. it helps the sender connect with `strong engineers and technical leaders`
3. it also supports the sender's job search
4. the workflow runs autonomously
5. the sender is using this email as a live example of that workflow
6. the repo URL appears near the mention

The wording does not need to be identical every time, but the meaning should
stay intact.

For the managerial path, `Job Hunt Copilot` should usually appear only as a
concise builder-signal or project bullet when relevant to the role. The
managerial path does not need to say that the workflow runs autonomously or
that the email itself is a live example of the workflow.

## Call-to-Action Rule

The first email should ask for time and guidance, not for a referral.

### Technical path CTA

For technical contacts, the CTA should:

1. ask for `10 minutes`
2. ask sometime in the next week or two
3. frame the call as guidance during the sender's job hunt
4. make clear that the sender wants to learn how to build a career like the
   recipient's

### Managerial path CTA

For managerial contacts, the CTA should:

1. ask for `10 minutes`
2. frame the call around understanding the team's real challenges
3. mention that the sender may build a small proof of concept afterward if helpful
4. allow a polite forward-to-the-right-person request

## Subject Line Rule

The subject line should stay:

1. short
2. low-pressure
3. recipient-focused

It should avoid:

1. `job`
2. `referral`
3. `application`
4. `opportunity`
5. `AI`
6. `agent`

For now:

1. technical-path subjects should stay fixed as `Learning from your career path`
2. managerial-path subjects should stay fixed to the pattern `Interest in the <Role Title> role at <Company>`

Exact subject patterns can be tightened in a later pass.

## Tone Rule

The email should be:

- respectful
- concise
- human
- clear about intent
- naturally written as a complete email rather than as stitched-together pieces

The email should not be:

- overly flattering
- generic
- pleading
- salesy
- an indirect referral ask
- overly compressed into abstract or noun-heavy phrasing that feels assembled

## Runtime Boundaries

### Deterministic Python

Deterministic Python should handle:

1. Apollo enrichment
2. employment-history normalization
3. recipient classification
4. job-posting context loading
5. deterministic JD relevance extraction for the managerial path
6. sender-context assembly
7. bounded drafting input assembly
8. output validation and persistence

### `codex exec`

`codex exec` should be used for:

1. managerial-path drafting
2. technical-path Paragraph 1 generation

This simplified strategy does not require GitHub analysis, project selection,
or company-research fallback stages.

## Structured Output Contract

All `codex exec` outputs should be validated by Pydantic.

### Technical path contract

For the technical path, `codex exec` should not generate the full email body.
Instead, it should return only the dynamic content needed for Paragraph 1.
Deterministic Python should append the fixed Paragraph 2, Paragraph 3, and
Paragraph 4 afterward.

Required fields:

1. `paragraph_1_text`
2. `selected_career_steps`

Required Pydantic shape:

```python
class TechnicalDraftSlots(BaseModel):
    paragraph_1_text: str
    selected_career_steps: list[str]
```

`paragraph_1_text` should be returned exactly as it should appear in the final
email as the full final Paragraph 1, and it should follow the fixed Paragraph 1
rules in this spec.

Deterministic Python should not rewrite the generated Paragraph 1. It should
only validate it, persist the debug fields, and append the fixed Paragraph 2,
Paragraph 3, and Paragraph 4.

For this path, `codex exec` should return JSON only, matching the Pydantic
schema exactly, with no extra rationale or commentary outside the schema.

For the technical path, `paragraph_1_text` should stay at exactly two
sentences.
`selected_career_steps` is for debugging and traceability and should store
only the company names chosen for the path transitions.

The technical-path prompt should include one short realistic example of valid
JSON output that matches this schema. It should not include multiple examples.

### Managerial path contract

For the managerial path, `codex exec` should generate only the variable
problem-solver content. Deterministic Python should own:

1. the fixed subject
2. the greeting line
3. the fixed bold proof-of-concept sentence
4. the fixed JD-challenge heading
5. the fixed relevant-background heading
6. the fixed resume / CTA paragraph
7. the signature block

So for this path, `codex exec` should return:

1. `role_alignment_sentence`
2. `problem_hypotheses`
3. `relevant_background`
4. `selected_jd_signals`
5. `selected_resume_signals`

Suggested Pydantic shape:

```python
class ManagerialDraftPayload(BaseModel):
    role_alignment_sentence: str
    problem_hypotheses: list[str]
    relevant_background: list[str]
    selected_jd_signals: list[str]
    selected_resume_signals: list[str]
```

Those debug fields should explain what the draft was anchored on, such as:

1. selected JD signals
2. selected sender-background or resume signals

For now, the managerial-path debug payload should keep only:

1. `selected_jd_signals`
2. `selected_resume_signals`

Both fields should be simple lists of short strings rather than richer nested
objects.
Each list should normally contain no more than three items.
`selected_jd_signals` should use normalized short strings taken from the
bounded JD relevance pack that actually informed the draft.
`selected_resume_signals` should use normalized short strings tied to the
sender-evidence items that actually informed the draft, rather than vague
theme labels unrelated to the written paragraphs.
These debug lists should reflect only the JD and sender signals that actually
appear in or directly support the returned sentence and bullets. They should
not include unused extra context.

Unlike the technical path, the managerial path is a bounded partial-drafting
path with attached debug metadata.

The managerial-path prompt should include one short realistic JSON example that
matches the eventual managerial-path schema. It should not include multiple
examples.
That example should use a software or AI-adjacent role context rather than an
unrelated domain example.
The preferred example context is an `AI Engineer` style role.
In that example and in real drafts, a `Job Hunt Copilot` bullet should appear
only when the role is clearly AI-relevant or when that project materially
strengthens fit for the role.
The preferred managerial example should show three JD-challenge bullets and
three relevant-background bullets so the maximum intended shape is explicit.
That example should also populate `selected_jd_signals` and
`selected_resume_signals` with realistic short strings rather than placeholder
labels.

The managerial-path prompt should prefer a stable section order:

1. task statement
2. output schema
3. sentence and bullet rules
4. hard constraints
5. bounded evidence
6. one valid JSON example

For the managerial path, `codex exec` should return JSON only, matching the
managerial-path Pydantic schema exactly, with no extra rationale or commentary
outside the schema.
It should not return markdown fences, prose outside the JSON object, or
alternative formatting.

The managerial-path prompt should enforce these structural limits:

1. `role_alignment_sentence` stays at exactly one sentence
2. `problem_hypotheses` contains exactly three short bullets
3. `relevant_background` contains exactly three short bullets
4. both bullet lists should stay easy to scan and should not read like pasted JD
   or resume sentences
5. the assembled managerial body before the signature should target roughly
   `185-215` words

The preferred exact managerial-path prompt should follow this shape:

```text
Draft the variable content for a concise managerial outreach email.

Return JSON only. Do not return markdown fences. Do not return commentary.

Output schema:
- role_alignment_sentence: string
- problem_hypotheses: list[string]
- relevant_background: list[string]
- selected_jd_signals: list[string]
- selected_resume_signals: list[string]

Sentence and bullet rules:
- role_alignment_sentence must be exactly 1 sentence.
- role_alignment_sentence should begin with:
  "I came across the <Role Title> opening at <Company> and wanted to reach out because..."
- role_alignment_sentence should explain why the role looks closely aligned with the kind of role-relevant engineering problems I've been trying to work on.
- role_alignment_sentence should sound natural and concise, not stitched together.
- problem_hypotheses must contain exactly 3 bullets.
- each problem_hypotheses bullet should be short and easy to scan.
- problem_hypotheses should infer likely team challenges from the JD without copying JD lines verbatim.
- problem_hypotheses should be grounded only in the JD and should not assume unsupported internal facts.
- relevant_background must contain exactly 3 bullets.
- each relevant_background bullet should be short and easy to scan.
- relevant_background should be chosen from my real resume evidence, including experience and projects when relevant.
- relevant_background should prefer this order:
  1. strongest directly role-relevant professional proof
  2. second strongest professional or systems proof
  3. optional project proof such as Job Hunt Copilot when relevant
- if a Job Hunt Copilot bullet is included, it should include the repo URL in that same bullet.
- the assembled managerial body before the signature should target roughly 185 to 215 words.

Hard constraints:
- Use only the bounded JD relevance pack and sender evidence provided.
- Do not invent unsupported team challenges, technical specifics, or fit claims.
- Problem hypotheses must come from reasoning over the JD only, not from outside assumptions.
- Do not copy-paste JD bullets or wording into the returned bullets.
- Do not use generic self-praise such as passionate, hardworking, fast learner, or excited unless directly grounded in evidence.
- Keep the returned bullets short, readable, and non-redundant.
- Do not mention LinkedIn or GitHub in the variable content. They belong in the signature only.
- Optimize for a natural email voice. The draft should read like one person writing a concise note, not like bits and pieces attached together.

Bounded evidence:
- recipient_name: {recipient_name}
- target_role_title: {target_role_title}
- target_company: {target_company}
- bounded_jd_relevance_pack: {bounded_jd_relevance_pack}
- sender_core_summary: {sender_core_summary}
- sender_evidence_pool: {sender_evidence_pool}
- fixed_downstream_context:
  - Greeting line is fixed: "Hi <FirstName>,"
  - Opener sentence 1 is fixed: "I hope you're doing well."
  - Opener sentence 3 is fixed and bolded: "**If helpful, I'd be happy to build a small proof of concept based on my understanding of the challenges the team is working on and share the repo.**"
  - JD heading is fixed: "My read from the JD is that the team is likely working on:"
  - Background heading is fixed: "Relevant background from my side:"
  - CTA block is fixed:
    - "I've attached my resume for context."
    - "Would you be open to a brief 10-minute conversation?"
    - "I'd love to better understand the challenges the team is actually focused on, and if helpful, I'd be happy to build a small proof of concept afterward and share the repo."
    - "If this is better routed elsewhere, I'd appreciate a forward to the right person internally."
  - Signature context: LinkedIn and GitHub are in the signature only. Resume is attached separately.

Valid JSON example:
{...}
```

The preferred managerial-path JSON example is:

```json
{
  "role_alignment_sentence": "I came across the AI Engineer opening at Elicit and wanted to reach out because the role looks closely aligned with the kind of workflow and systems problems I've been trying to work on.",
  "problem_hypotheses": [
    "dependable AI workflows in production",
    "evaluation and failure testing for model behavior",
    "observable systems with low-latency reliability constraints"
  ],
  "relevant_background": [
    "built distributed data services handling ~580 TPS at 99.95% uptime",
    "worked on monitoring, alerting, and production reliability for backend/data workflows",
    "built Job Hunt Copilot, an AI workflow automation tool from scratch: https://github.com/sontiachyut/job-hunt-copilot-v4"
  ],
  "selected_jd_signals": [
    "backend reliability",
    "evaluation of AI workflows",
    "production GenAI systems"
  ],
  "selected_resume_signals": [
    "~580 TPS at 99.95% uptime",
    "monitoring and alerting",
    "Job Hunt Copilot"
  ]
}
```

Deterministic Python should assemble the final managerial-path email in this
fixed order:

1. greeting line
2. fixed opener sentence 1
3. `role_alignment_sentence`
4. fixed bold proof-of-concept sentence
5. rendered `My read from the JD is that the team is likely working on:` section
6. rendered `Relevant background from my side:` section
7. fixed CTA block

## Prompt-Budget Rule

The drafter should receive only the compact evidence needed for the selected
path.

### Technical path evidence pack

The technical drafter for Paragraph 1 should receive:

1. recipient name
2. current title
3. current company
4. the full Apollo employment-history summary

It should also receive the fixed email shape so Paragraph 1 reads naturally
beside the fixed Paragraph 2, Paragraph 3, and Paragraph 4.

The technical-path prompt should include:

1. the technical-path evidence pack
2. the fixed Paragraph 1 rule
3. one short realistic JSON example matching the technical-path schema

The technical-path prompt should also explicitly tell `codex exec` not to
invent unsupported technical specifics about the recipient's work, stack, or
responsibilities. It should use only what is directly supported by the full
Apollo employment-history summary provided.

The technical-path prompt should also explicitly tell `codex exec` not to
restate, paraphrase, or preempt the fixed Paragraph 2, Paragraph 3, and
Paragraph 4 content inside `paragraph_1_text`. Paragraph 1 should stay focused
on the recipient's path only.

Deterministic Python should assemble the final technical-path email from:

1. generated `paragraph_1_text`
2. fixed Paragraph 2
3. fixed Paragraph 3
4. fixed Paragraph 4

### Managerial path evidence pack

The managerial drafter should receive:

1. recipient name
2. current title
3. current company
4. target role and company context
5. bounded JD relevance pack
6. a short fixed sender core summary
7. a bounded sender evidence pool curated from the sender's resume/background
8. relevant skills summary
9. `Job Hunt Copilot` summary when included
10. availability window
11. signature-link context, including that LinkedIn and GitHub live in the
    signature and the resume is attached separately

The bounded JD relevance pack should also be structured rather than passed as
an untyped blob. For this POC, each JD evidence item should prefer a shape such
as:

1. `jd_signal`
2. `supporting_line`
3. optional `theme_tags`

The drafter should not receive the full raw Apollo payload.
It also should not receive the full raw resume or an unbounded sender-profile
blob when a bounded sender evidence pool can represent the relevant proof
points more cleanly.

That fixed sender core summary should carry the stable sender facts the model
should not have to reconstruct from scattered evidence lines, such as:

1. recent `MS in CS` from `ASU`
2. about `3 years` of experience
3. one short systems/software background sentence

That bounded sender evidence pool should include short proof lines plus
lightweight metric or theme tags so deterministic Python and `codex exec` can
select the strongest role-relevant evidence without needing the full resume.

For this POC, each bounded sender evidence item should be represented as a
small structured object rather than one flat tagged string. The preferred
shape is:

1. `proof_line`
2. `metric_tags`
3. `theme_tags`
4. optional `source_label`

This keeps the prompt compact while still letting deterministic Python inspect,
filter, and validate the sender-evidence pool before sending it to the
managerial drafter.

When practical, deterministic Python should normalize `theme_tags` from a
small controlled vocabulary so evidence selection stays consistent across
drafts. That vocabulary can include themes such as:

1. `backend`
2. `distributed_systems`
3. `reliability`
4. `performance`
5. `data_processing`
6. `production_engineering`
7. `ai_workflows`
8. `product_building`

`metric_tags` should also stay short and normalized when possible, for example
`~580 TPS`, `99.95% uptime`, or `40% processing-time reduction`.

For consistency, `selected_jd_signals` in the managerial debug payload should
be drawn from the normalized `jd_signal` values used in this bounded JD pack.

For the managerial path, LinkedIn and GitHub should stay in the signature and
do not need to be mentioned explicitly in the body.

The managerial-path prompt should explicitly tell `codex exec` not to invent
unsupported team challenges, technical specifics, or fit claims. Any inferred
team/problem statement should stay cautious and be grounded in the bounded JD
relevance pack and the provided sender background or resume signals.
The managerial-path prompt should also explicitly limit that inferred
team/problem statement to the `problem_hypotheses` section rather than
repeating speculative challenge language across the draft.

The managerial-path prompt should also explicitly tell `codex exec` to avoid
generic self-praise language such as `passionate`, `hardworking`, `fast
learner`, or `excited` unless the phrasing is directly grounded in evidence and
meaningfully helps role fit.

The managerial-path prompt should also explicitly tell `codex exec` that
LinkedIn and GitHub belong in the signature only, while the resume is attached
separately and will be mentioned briefly in the fixed CTA block rendered by
deterministic Python.

The managerial-path draft should keep the only explicit question in the body
inside the fixed CTA block. Earlier paragraphs should stay declarative.

## Remaining Implementation Work

The main remaining work is now implementation and validation rather than major
spec ambiguity:

1. implement deterministic JD relevance extraction and sender-evidence
   normalization
2. wire the managerial and technical prompt contracts into the drafting flow
3. add regression coverage for schema validation, section ordering, and email
   length targets
