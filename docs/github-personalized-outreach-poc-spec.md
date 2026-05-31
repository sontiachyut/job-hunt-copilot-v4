# GitHub-Personalized Outreach POC Spec

## Status

Draft POC spec. This document defines the intended behavior of the GitHub-personalized coffee-chat outreach flow. Prompt wording and implementation details should follow this spec, not replace it.

## Purpose

Build a separate outreach flow that drafts a short personalized coffee-chat email to an engineer using public profile signals.

The system should:

1. find a real common-ground signal from the recipient's public profile, ideally GitHub
2. use that signal to write a specific, non-generic opener
3. establish the sender's credibility through relevant engineering background and `Job Hunt Copilot`
4. ask for a 15-minute coffee chat with a concrete purpose

This flow is distinct from role-targeted outreach and follow-up emails. It is not a direct job-ask email.

## Primary Outcome

Given one contact record, the system should produce a draft email that:

1. starts from a real, specific common-ground signal
2. sounds like a human who spent time looking at the recipient's work
3. makes the sender sound worth replying to
4. asks for a low-pressure 15-minute conversation

## Non-Goals

This POC is not trying to:

1. ask directly for a job
2. ask directly for a referral
3. maximize research breadth across every possible source
4. reproduce LinkedIn's private or personalized graph data
5. operate as a free-form autonomous agent

## Source Priority

For this POC, the system should prefer public sources in this order:

1. GitHub profile and repositories
2. contact role and company
3. GitHub-missing fallback using role/company curiosity

The POC may use LinkedIn URL as an identity field, but the current personalization logic should not depend on private LinkedIn data.

## Inputs

For one contact, the system may use:

- contact full name
- email address
- current role/title
- current company
- LinkedIn URL when available
- resolved GitHub profile URL when available
- GitHub profile metadata
- public GitHub repositories and compact repo evidence
- sender identity and sender background summary
- sender availability window

## Research Goal

The research step should not aim to collect "as many details as possible." Instead, it should collect enough evidence to support one high-quality outreach hook.

For GitHub-backed contacts, the system should gather:

- GitHub profile URL
- profile name/login
- bio
- company
- blog or personal site when present
- all public repositories
- compact metadata for each repository
- README excerpt for the selected repository

## Common-Ground Rule

The email must begin from one specific common-ground signal.

### Preferred common-ground source

If a usable GitHub profile exists, the system should prefer:

1. one specific repository, or
2. one repeated engineering theme across repositories

### Common-ground quality rules

The chosen signal should:

1. be concrete enough to mention specifically
2. reveal a real engineering problem, tool, workflow, or design choice
3. overlap naturally with the sender's background or current project
4. avoid empty compliments or generic praise

### Common-ground failure mode

If GitHub evidence is weak or absent, the common-ground should fall back to:

1. the recipient's current role
2. the recipient's company
3. curiosity about the kind of work the team is likely doing
4. curiosity about how to become a stronger candidate for that company

## Credibility Rule

The email must establish why the sender is worth the recipient's time.

The credibility layer should come from:

1. the sender's broader engineering background
2. `Job Hunt Copilot` as a current project
3. the fact that this outreach workflow is partially autonomous but human-reviewed

### Ordering constraint

The draft must establish engineering credibility before the autonomous-email point becomes prominent.

`Job Hunt Copilot` should support credibility, not dominate the email.

### Required `Job Hunt Copilot` facts

The draft should communicate, directly or equivalently:

1. `Job Hunt Copilot` was built for the sender's own job search
2. it helps identify relevant roles and the right people to reach out to
3. parts of the workflow run autonomously
4. every email is reviewed personally before sending
5. this email is a live example of that workflow

## Call-to-Action Rule

The call to action must be a low-pressure 15-minute coffee chat.

The purpose of the conversation should be:

1. one tip about the kind of technical work the recipient does, builds, or thinks about
2. one tip related to the sender's job hunt, profile positioning, or preparation

The CTA should:

1. ask for 15 minutes
2. ask for some time in the next two weeks
3. include the sender's typical availability window
4. remain easy to answer yes or no to

## Email Shape

The draft should follow this logical flow:

1. common ground
2. connection plus credibility
3. 15-minute ask

The implementation may keep this as a 3-paragraph structure.

## Email Content Rules

The email should:

1. sound natural and specific
2. mention a real project, repo, theme, or role signal
3. avoid generic praise
4. avoid inflated claims
5. avoid sounding like a mass template
6. avoid asking directly for a job or referral

The email should not say:

1. "I have been following your work" unless explicitly supported by evidence
2. "impressive profile"
3. "great work" without a specific observation
4. "I'd love to pick your brain"

## Fallback Behavior

If no GitHub profile can be resolved, the system should still be able to draft an email.

In that case the draft should:

1. reference the recipient's current role and company
2. show interest in the type of work the company or team is likely doing
3. ask about engineering culture, day-to-day work, or what makes candidates strong for that company
4. connect the sender's interests and `Job Hunt Copilot` work to that context

## System Architecture

This POC should use a hybrid architecture:

- deterministic Python for orchestration, fetching, normalization, artifact writing, and validation
- bounded `codex exec` reasoning steps for judgment-heavy tasks
- Pydantic contracts between stages

The system should not use a free-form runtime agent for this workflow.

## Required Runtime Stages

### 1. GitHub profile resolution

Input:

- contact name
- company
- title
- optional LinkedIn URL
- optional email

Behavior:

- deterministically search for GitHub candidates
- score candidates using explicit matching reasons
- return a resolved GitHub URL or unresolved state

### 2. GitHub profile research

Input:

- resolved GitHub profile URL

Behavior:

- fetch public profile data
- fetch all public repos
- produce compact repo candidate records
- enrich the selected repo more deeply than the rest

### 3. Project selection

Behavior:

- choose the best repo or project theme to mention
- prioritize concrete engineering depth and natural overlap

Implementation:

- use `codex exec`
- return structured JSON only

### 4. Project analysis

Behavior:

- explain what engineering problem the chosen repo addresses
- identify specific details worth mentioning
- explain why it is a good outreach hook
- connect it to the sender's work
- propose a natural conversation angle

Implementation:

- use `codex exec`
- return structured JSON only

### 5. Coffee-chat draft generation

Behavior:

- produce the final outreach draft from the selected common-ground and analysis
- follow the email rules in this spec

Implementation:

- use `codex exec`
- return structured JSON only

### 6. Human review

The POC should stop at draft generation unless an explicit send path is later added.

## `codex exec` Usage Rule

`codex exec` should be invoked only for bounded reasoning stages, not for general crawling or orchestration.

For this POC, the intended `codex exec` stages are:

1. project selection
2. project analysis
3. email drafting

Python should:

1. gather the evidence
2. choose what evidence to pass
3. validate returned JSON
4. persist artifacts

## Output Contracts

At minimum, the system should be able to produce:

### Project selection output

- selected repo name
- selected repo URL
- why it was selected
- shortlist notes or runner-up repos

### Project analysis output

- project summary
- engineering problem
- standout observations
- why it is a good hook
- connection to sender work
- conversation angle

### Draft output

- subject
- body markdown

## Artifact Requirements

Each `codex exec` stage should persist enough artifacts to debug quality and regressions.

Expected artifacts per stage should include:

- request payload
- prompt
- output schema
- stage result JSON
- stdout
- stderr

These artifacts should live under the existing POC runtime area.

## Acceptance Criteria

A draft is acceptable for this POC if:

1. it contains one real common-ground signal
2. the common ground is specific, not generic
3. it connects that signal to the sender's background or `Job Hunt Copilot`
4. it establishes credibility before leaning on the autonomous-email gimmick
5. it asks for a 15-minute conversation with a concrete reason
6. it does not ask directly for a job or referral
7. it reads like a plausible human email

## Evaluation Questions

Each generated draft should be reviewable against these questions:

1. What specific signal did the system choose as common ground?
2. Is that signal genuinely interesting and technically discussable?
3. Does the draft show evidence that the sender actually looked at the project or role?
4. Does the draft make the sender sound worth replying to?
5. Does `Job Hunt Copilot` support credibility without taking over the email?
6. Is the coffee-chat ask concrete and low-pressure?
7. Would this email still make sense if the recipient does not want to help with hiring directly?

## Near-Term Extensions

After the POC stabilizes, likely extensions are:

1. structured badge normalization from LinkedIn job-alert cards
2. personal-site and blog enrichment
3. role/company fallback drafts when GitHub is missing
4. evaluation scoring for draft quality
5. optional send path after human approval

