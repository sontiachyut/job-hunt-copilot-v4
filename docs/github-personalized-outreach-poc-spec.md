# GitHub-Personalized Outreach POC Spec

## Status

Draft POC spec. This document defines the intended behavior of the GitHub-personalized coffee-chat outreach flow. Prompt wording and implementation details should follow this spec, not replace it.

## Purpose

Build a separate outreach flow that drafts a short personalized coffee-chat email to an engineer using public profile signals.

The system should:

1. find a real common-ground signal from the recipient's public profile, ideally GitHub
2. use that signal to write a specific, non-generic opener
3. establish the sender's credibility through relevant engineering background and `Job Hunt Copilot`
4. ask for a 15-minute virtual coffee chat with a concrete purpose

This flow is distinct from role-targeted outreach and follow-up emails. It is not a direct job-ask email.

## Operating Principle

This POC should be spec-driven.

That means:

1. this document defines behavior and quality expectations
2. prompts are implementation details that should follow the spec
3. Python orchestration and Pydantic contracts should enforce the spec where possible
4. tests should validate the spec, not just current prompt wording

## Primary Outcome

Given one contact record, the system should produce a draft email that:

1. starts from a real, specific common-ground signal
2. sounds like a human who spent time looking at the recipient's work
3. makes the sender sound worth replying to
4. asks for a low-pressure 15-minute conversation

## Outreach Readiness Rule

For this POC, a usable recipient email address alone is not sufficient to make a contact actionable for outreach.

The contact becomes draft-ready only when one of these research paths has completed with enough evidence to support the email:

1. GitHub-backed path
2. no-GitHub company-research fallback path

If neither path produces strong context, the workflow may still produce a minimal conservative draft rather than blocking outright, but it should not invent specific common ground.
When any specific company or role observation is available, the minimal conservative draft should still use at least one such observation rather than staying fully generic.
If the conservative draft mentions the recipient's role/title, it should also mention the company name rather than referencing the role alone.
That minimal conservative draft should still ask about:

1. engineering culture
2. current engineering challenges
3. how the sender should improve the profile to become a stronger candidate for the company and ultimately join it

## Non-Goals

This POC is not trying to:

1. ask directly for a job
2. ask directly for a referral
3. maximize research breadth across every possible source
4. reproduce LinkedIn's private or personalized graph data
5. operate as a free-form autonomous agent
6. expand into broader social-profile research beyond Apollo, GitHub, and personal site from GitHub

## Research Acquisition Order

For this POC, the system should collect profile data in this order:

1. Apollo enrichment
2. GitHub profile discovery and GitHub profile research
3. personal-site or blog discovery from GitHub profile data

If no personal site or blog is discoverable from GitHub, the workflow should continue without it.

The POC may use LinkedIn URL as an identity field when Apollo provides it, but the current personalization logic should not depend on private LinkedIn data.

This POC should remain bounded to these research sources only:

1. Apollo
2. GitHub
3. personal site or blog discovered from GitHub

## Common-Ground Source Priority

For common-ground selection during drafting, the system should prefer:

1. GitHub repository hook
2. GitHub engineering-theme hook
3. Apollo employment-history hook when GitHub is missing and the history is relevant
4. role/company fallback hook

## Inputs

For one contact, the system may use:

- Apollo-enriched person data
- contact full name
- email address
- current role/title
- current company
- LinkedIn URL when available
- resolved GitHub profile URL when available
- GitHub profile metadata
- public GitHub repositories and compact repo evidence
- personal-site or blog URL when discovered from GitHub
- personal-site metadata and extracted page summaries when collected
- sender identity and sender background summary
- sender availability window

## Required Sender Context

The sender context passed into the system should be intentionally small and stable.

For this POC, the sender context should include:

- sender name
- sender LinkedIn URL
- sender GitHub URL when available
- sender email
- sender phone
- `Job Hunt Copilot` repo URL
- short background summary
- short `Job Hunt Copilot` summary
- availability window

The sender context should not require full resume text for this flow.

## Research Record

Before any AI reasoning step runs, the deterministic pipeline should normalize the contact into a research record.

That research record should support at least:

- Apollo enrichment result
- contact identity fields
- GitHub resolution result
- GitHub profile metadata when resolved
- compact repo candidate list
- personal-site resolution result when available
- personal-site research result when available
- sender context

This research record is the source of truth for downstream selector, analyzer, and drafter stages.

## Research Goal

The research step should not aim to scrape the open web broadly. Instead, it should deterministically collect as much useful structured data as is available from the approved source chain for one contact.

For this POC, that means:

1. collect all useful fields returned by Apollo enrichment that are relevant to identity, role, company, public profile, and work-email readiness
2. resolve and collect all useful public GitHub profile data
3. if GitHub exposes a blog or personal-site link, collect useful public data from that site

### Apollo research expectations

For Apollo-backed contacts, the research step should collect and normalize as much of the returned enrichment payload as is useful and safe to persist, including at minimum:

- person/provider id
- display name
- full name
- first name
- last name
- current title
- location
- company and organization identifiers when available
- LinkedIn URL
- work email when returned
- email status when returned
- headline when returned

The full raw Apollo enrichment payload should be persisted as an artifact.

For this POC, the normalized research record should include the required normalized fields, but it should not attempt best-effort normalization of every additional Apollo-returned field.

If additional Apollo fields such as GitHub URL, Twitter URL, photo URL, or employment history are available and the system decides to normalize more of them later, that should be treated as an additive extension rather than a behavioral change.

### Apollo field-usage boundary

For this POC:

1. `employment_history` may be used as drafting evidence in the no-GitHub branch
2. `github_url` may be used as an identity handoff into GitHub research
3. `photo_url` should not be used as drafting evidence
4. `twitter_url` should not be used as drafting evidence in this POC unless a later social-profile research stage is added

When `employment_history` is used, the system may reference more than one past role if multiple roles create stronger and more relevant common ground than a single-role summary would.
When `employment_history` is used as the primary common-ground hook in the opener, the draft should mention both the company name and the role explicitly.
That opener should stay anchored on one role/company pair. If additional past
roles are useful, they should appear later as supporting context rather than be
stacked into the opener.
That opener should also include one or two concrete observations about why that
history feels relevant, depending on what reads more naturally.
When GitHub exists, `employment_history` may still be used as supporting context, but it should not replace GitHub as the primary common-ground hook in this POC.

### GitHub research expectations

For GitHub-backed contacts, the system should gather:

- GitHub profile URL
- profile name/login
- bio
- company
- blog or personal site when present
- all public repositories
- compact metadata for each repository
- README excerpt for the selected repository

### Personal-site research expectations

If a personal site or blog is discovered from GitHub, the system should gather a bounded summary of that site, such as:

- canonical URL
- page title
- meta description or obvious about summary
- obvious project, writing, or talk links

The workflow should not fail if no personal site is discovered.

Personal-site information should be treated as supporting context in this POC, not as the primary outreach hook. It may support both the GitHub-backed draft path and the no-GitHub fallback path.

## Common-Ground Rule

The email must begin from one specific common-ground signal.

The opener should anchor on exactly one primary evidence source. Other evidence
sources may appear later as supporting context, but the opener should not blend
multiple independent hooks into one introduction.

### Preferred common-ground source

If a usable GitHub profile exists, the system should prefer:

1. one specific repository, or
2. one repeated engineering theme across repositories

The system should prefer a specific repository when one repository offers a stronger, more concrete hook than a broad theme.

If a repeated engineering theme produces a cleaner, more natural opener than a
repo-specific hook, a theme-based opener is still allowed in this POC. The
workflow does not need to force a repo-based opener in every GitHub-backed case.

When the opener is theme-based, the draft should use whatever level of detail
looks most natural. It does not need to force a fixed number of observations,
but it should still stay grounded in real GitHub evidence and avoid generic
theme praise.
When the opener is theme-based, it should still mention one or two concrete
repository names as supporting evidence, depending on what reads more naturally.

When the opener is based on a repository hook, it should mention the repository
name explicitly.

The opener should also include one or two concrete observations about that
repository, depending on what reads more naturally.

For this POC, the draft should mention the recipient repository by name only.
It should not include the recipient repository URL in the email body.

### Common-ground quality rules

The chosen signal should:

1. be concrete enough to mention specifically
2. reveal a real engineering problem, tool, workflow, or design choice
3. overlap naturally with the sender's background or current project
4. avoid empty compliments or generic praise
5. support a real question the sender could ask in a 15-minute conversation

### Project selection tie-break rules

If more than one repository looks plausible, the system should prefer the repository that:

1. exposes clearer engineering constraints or tradeoffs
2. is easier to describe with 1 to 2 concrete observations
3. overlaps more naturally with the sender's engineering background or `Job Hunt Copilot`
4. feels like a real tool, workflow, or production-minded system rather than a toy demo

### Common-ground failure mode

If GitHub evidence is weak or absent, the common-ground should fall back to:

1. the recipient's current role
2. the recipient's company
3. curiosity about the kind of work the team is likely doing
4. curiosity about how to make the sender's profile stronger in order to join that company

The fallback should remain specific to the role/company context and should not become a generic networking email.

In a fallback opener, the draft may lead with either the company name or the
recipient's role/title, depending on what reads more naturally. If the opener
mentions the recipient's role/title, it should also mention the company name
rather than referencing the role alone.

That fallback opener should include one or two specific observations grounded in
the role, company context, employment history, or company research, depending
on what reads more naturally.

When the opener is using role/company fallback rather than GitHub or
employment-history common ground, it should stay anchored on one company/role
pair. It may add one inferred company-research theme when that makes the opener
more specific and natural.

When company research is available, the opener does not need to mention the
company-research theme explicitly every time. It should do so only when that
theme creates a cleaner opener than role/title-led context.

If a GitHub profile exists but the repos do not produce a strong hook, the system does not need to force a GitHub-based opener. In that case, the selector may choose stronger fallback context such as employment history, company-research fallback, or a minimal conservative draft.
This includes cases where Apollo or search resolves a GitHub profile successfully but the public repos are empty, thin, or otherwise not useful for outreach.

## Credibility Rule

The email must establish why the sender is worth the recipient's time.

The credibility layer should come from:

1. basic information about the sender's professional engineering background
2. `Job Hunt Copilot` as a current project
3. the fact that this outreach workflow is partially autonomous but human-reviewed

The credibility section should mention both:

1. a brief professional-background signal
2. `Job Hunt Copilot`

The professional-background mention should stay high level in this POC. The
draft does not need to include concrete metrics or detailed proof points unless
the implementation is later extended for that purpose.

### Ordering constraint

The draft must establish engineering credibility before the autonomous-email point becomes prominent.

`Job Hunt Copilot` should support credibility, not dominate the email.

The sender should sound like someone building a real system, not someone pitching a novelty tool.

### Required `Job Hunt Copilot` facts

The draft should communicate, directly or equivalently:

1. `Job Hunt Copilot` was built for the sender's own job search
2. it helps identify relevant roles and the right people to reach out to
3. parts of the workflow run autonomously
4. every email is reviewed personally before sending
5. this email itself came through that workflow, or an equivalent paraphrase
6. the email should include the `Job Hunt Copilot` repo link explicitly, near
   the `Job Hunt Copilot` mention rather than somewhere unrelated in the email.
   For this POC, that link should appear as the raw GitHub URL.

These ideas do not need to appear as five separate sentences. The drafter may
compress them into fewer sentences as long as the meaning is still covered.

When the draft refers to this workflow, it should use the word `email` rather
than `message`.

## Call-to-Action Rule

The call to action must be a low-pressure 15-minute virtual coffee chat.
For this POC, the draft should use the literal phrase `virtual coffee chat`.

The purpose of the conversation should be:

1. one tip about the kind of technical work the recipient does, builds, or thinks about
2. one tip related to the sender's job hunt, profile positioning, or preparation

The CTA should:

1. ask for 15 minutes
2. ask for some time in the next two weeks
3. include the sender's typical availability window
4. remain easy to answer yes or no to

For this POC, the default availability window should be:

1. weekdays from `8 AM MST` to `6 PM MST`
2. anytime on weekends
3. plus a short note that the sender can also try other times if the recipient prefers

### CTA topic rules

The CTA should point toward two conversation themes:

1. a technical or project-related question anchored in the recipient's work
2. a job-hunt or profile-positioning question about how the sender can make the profile stronger in order to join the recipient's company

The draft should make both purposes explicit. The ask should clearly signal that
the sender is hoping for:

1. one tip related to the recipient's work, engineering problems, or technical judgment
2. one tip related to the sender's job hunt, profile positioning, or preparation

When the fallback/company-guidance branch is used, the draft should ask about
both engineering culture and current challenges explicitly rather than leaving
either one implicit.

## Email Shape

The draft should follow this logical flow:

1. common ground
2. connection plus credibility
3. 15-minute ask

The implementation should prefer a concise 3-paragraph structure. A 4-paragraph
draft is allowed when it reads more naturally, but concision remains the
governing rule and the email should stay short enough that recipients do not
skip it.

### Paragraph intent

If implemented as 3 paragraphs, the intended paragraph jobs are:

1. `common_ground`
2. `credibility_and_connection`
3. `coffee_chat_cta`

The system may add greeting and signature outside the AI drafting step.

The final email should include the full signature block. At minimum, that
signature block should include:

1. sender name
2. sender LinkedIn URL
3. sender phone
4. sender email

For this POC, the sender LinkedIn URL should live in the signature rather than
being called out separately in the body.

## Email Content Rules

The email should:

1. sound natural and specific
2. mention a real project, repo, theme, or role signal
3. avoid generic praise
4. avoid inflated claims
5. avoid sounding like a mass template
6. avoid asking directly for a job or referral
7. avoid overexplaining the automation
8. stay concise enough to read quickly on email

The email should not say:

1. "I have been following your work" unless explicitly supported by evidence
2. "impressive profile"
3. "great work" without a specific observation
4. "I'd love to pick your brain"
5. language that makes the recipient responsible for getting the sender a job

### Tone rules

The tone should be:

- curious
- technically aware
- respectful
- low-pressure

The tone should not be:

- pleading
- overfamiliar
- salesy
- overly polished corporate outreach

## Fallback Behavior

If no GitHub profile can be resolved, the system should still be able to draft an email.

In that case the draft should:

1. reference the recipient's current role and company
2. use broader public web research to understand what the company has been doing recently in software engineering
3. infer likely team or domain context from the recipient's current role/title when that inference is reasonable
   and phrase it cautiously when used in the draft, for example with wording
   like "it looks like your team may be working on..."
   More than one such inferred statement is allowed when the company research
   genuinely supports it.
   The draft may combine direct company-research observations and cautious
   inferences in whatever way reads most naturally, as long as the distinction
   stays clear in the wording.
4. communicate interest in the company and in learning from strong engineers there, with exact phrasing left to the drafter
5. explicitly say that the sender came across the recipient's profile and that
   it is the reason for the outreach; the draft does not need to explain how
   the profile was found
6. ask about engineering culture, current challenges, and how the sender should improve the profile to become a stronger candidate for that company and ultimately join it
7. explicitly mention `Job Hunt Copilot` as part of the sender's credibility
8. connect the sender's interests and `Job Hunt Copilot` work to that context

### Fallback matrix

The system should follow this fallback order:

1. `GitHub repo hook`
2. `GitHub theme hook`
3. `employment-history hook`
4. `role/company hook`

If step 1 is unavailable, the system should try step 2 before dropping to later fallback options.

When GitHub evidence is weak and both employment-history context and company-research context are available, the system should prefer employment-history context before company-research context.
If GitHub evidence is weak and employment-history context is also weak, the system should prefer company-research fallback before dropping to a minimal conservative draft.

If all four are weak, the system should still draft conservatively rather than inventing details.

### No-GitHub fallback drafting rule

When no GitHub profile is found for the contact, the workflow should switch to a different outreach style instead of pretending GitHub-based common ground exists.

That fallback style should:

1. use the recipient's current company as the main anchor
2. use broader public web research to identify what the company has been doing recently in software engineering
3. infer likely team or domain signals from the recipient's current role/title when reasonable
4. use Apollo employment history as a possible common-ground hook when that history creates a stronger, more relevant signal than generic company context
5. frame the email as a request for guidance from someone at the company rather than as a repo/project-based technical hook
6. still mention `Job Hunt Copilot` explicitly as part of the sender's credibility
7. ask about:
   - engineering culture
   - the kinds of challenges the company or team is solving
   - how the sender should improve the profile to become a stronger candidate for that company and ultimately join it

The draft may phrase this as direct interest in joining the company or as softer interest in the company and its engineering work, depending on context, but it should remain clearly career-oriented.

The no-GitHub fallback should still avoid asking directly for a job or referral.

## Draft-Readiness Gate

Before the system drafts or sends an outreach email, it should confirm that at least one of these is true:

1. a usable GitHub-backed common-ground signal exists
2. a usable no-GitHub company-research context exists

A contact with only a work email and weak research context may still proceed to a minimal conservative draft, but that draft should avoid pretending stronger common ground exists.

## System Architecture

This POC should use a hybrid architecture:

- deterministic Python for orchestration, fetching, normalization, artifact writing, and validation
- bounded `codex exec` reasoning steps for judgment-heavy tasks
- Pydantic contracts between stages

The system should not use a free-form runtime agent for this workflow.

For this POC, Apollo collection, GitHub collection, and personal-site collection should all be handled by deterministic Python code rather than AI reasoning.
One exception is allowed: bounded AI may be used as a GitHub identity tie-breaker when deterministic GitHub search returns multiple plausible candidates.

When GitHub is missing, bounded `codex exec` company research may be used later in the flow to help draft the company-focused fallback email.
When GitHub is missing, `codex exec` company research may use broader public web research and is not limited to official company sources.

## Runtime Data Contracts

Each stage should pass structured data forward rather than unstructured prose when possible.

### Apollo enrichment result

Should include at minimum:

- provider person id
- normalized display/full/first/last name fields
- title
- location
- LinkedIn URL
- work email when returned
- email status when returned
- headline when returned
- organization identifiers when returned

### GitHub profile resolution result

Should include at minimum:

- resolved or unresolved status
- confidence score
- chosen GitHub URL when resolved
- candidate matches
- match reasons

### GitHub repo candidate record

Should include at minimum:

- repo name
- repo URL
- description
- primary language
- topics
- stars
- updated time
- README excerpt when available

### GitHub profile research result

Should include at minimum:

- GitHub profile URL
- login
- display name when available
- bio
- company
- blog URL when present
- profile README when available

### Project selection result

Should include at minimum:

- selected repo name
- selected repo URL
- why selected
- standout repo-level observations or shortlist reasoning

### Project analysis result

Should include at minimum:

- project summary
- engineering problem
- 2 to 3 standout observations
- why this is a good hook
- connection to sender work
- suggested conversation angle

### Coffee-chat draft result

Should include at minimum:

- subject
- body markdown

### Personal-site resolution result

Should include at minimum:

- resolved or unresolved status
- canonical URL when resolved
- resolution source, such as GitHub profile `blog` field or README link

### Personal-site research result

Should include at minimum:

- canonical URL
- page title
- summary text or about text when extractable
- discovered project/blog/talk links when extractable

## Required Runtime Stages

### 1. Apollo enrichment ingestion

Input:

- contact identity fields already known to the system

Behavior:

- call Apollo enrichment through deterministic Python code
- normalize the returned person payload
- persist useful enrichment fields into the research record

This stage should be treated as the first structured profile-data source for the POC.

### 2. GitHub profile resolution

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

The resolver should not depend on AI for primary matching.

If Apollo returns a `github_url`, the workflow should trust that URL as the primary GitHub identity. If that URL is unusable or invalid, the workflow should fall back to independent GitHub search.
If independent GitHub search yields multiple plausible candidates, the workflow may use bounded AI only as a tie-breaker after deterministic search has already narrowed the candidate set.

### 3. GitHub profile research

Input:

- resolved GitHub profile URL

Behavior:

- fetch public profile data
- normalize profile-level fields such as bio, company, and blog URL
- fetch all public repos
- produce compact repo candidate records
- capture profile README when available
- enrich the selected repo more deeply than the rest

The research stage should collect all public repos, not only pinned or recent repos, unless future scale constraints require a spec change.

### 4. Personal-site resolution

Input:

- GitHub profile data
- GitHub profile blog field when present
- relevant GitHub README links when present

Behavior:

- deterministically look for a personal-site or blog URL
- prefer the GitHub profile `blog` field when it is a valid site URL
- optionally fall back to obvious personal-site links from GitHub profile content or README content
- return unresolved state if no trustworthy site is found

This stage should not block the workflow when no site exists.

### 5. Personal-site research

Input:

- resolved personal-site URL

Behavior:

- fetch a bounded set of public site pages
- extract useful profile context
- normalize the result into a compact site-research record

This stage should remain deterministic and optional.

### 6. Company research fallback

Input:

- current company
- current role
- Apollo-enriched profile fields

Behavior:

- run bounded company research only when no GitHub profile is available or when GitHub evidence is weak
- gather recent company-level software-engineering context that can support the fallback draft
- infer likely team or domain context from the recipient's title when that inference is reasonable and clearly framed
- consider Apollo employment history as a possible common-ground signal when it is more relevant than generic company context
- produce compact company-research notes for drafting

The company-research fallback is not limited to official company sources. It may use broader public web research when useful.

This stage should run only when no GitHub profile is available or when GitHub evidence exists but is too weak to support a strong outreach hook.

### 7. Project selection

Behavior:

- choose the best repo or project theme to mention
- prioritize concrete engineering depth and natural overlap

Implementation:

- use `codex exec`
- return structured JSON only

The selector may use the full repo candidate set, but it should make one choice only.

### 8. Project analysis

Behavior:

- explain what engineering problem the chosen repo addresses
- identify specific details worth mentioning
- explain why it is a good outreach hook
- connect it to the sender's work
- propose a natural conversation angle

Implementation:

- use `codex exec`
- return structured JSON only

The analyzer should reason over the selected repo and profile context, not over the full repo set again.

### 9. Coffee-chat draft generation

Behavior:

- produce the final outreach draft from the selected common-ground and analysis
- follow the email rules in this spec

Implementation:

- use `codex exec`
- return structured JSON only

The drafter should not perform new discovery. It should only write from the supplied evidence and analysis.

When no GitHub profile exists, or when GitHub evidence is too weak to support a strong opener, the drafter may instead write from the company-research fallback inputs described above.

### 10. Human review

The POC should stop at draft generation unless an explicit send path is later added.

## `codex exec` Usage Rule

`codex exec` should be invoked only for bounded reasoning stages, not for general crawling or orchestration.

For this POC, the intended `codex exec` stages are:

1. company research fallback when GitHub is missing
2. project selection
3. project analysis
4. email drafting

Python should:

1. gather the evidence
2. choose what evidence to pass
3. validate returned JSON
4. persist artifacts

Python should also prevent stage drift by ensuring each later stage only receives the inputs that stage is supposed to reason over.

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

The draft contract may later be extended with internal diagnostics such as:

- common-ground type
- common-ground source
- CTA intent

But those are optional for this POC.

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

## Prompt Governance

Prompts should be treated as implementation artifacts derived from this spec.

Prompt changes should not silently introduce new behavior that is not described here.

If a prompt requires behavior that is not already captured by this spec, the spec should be updated first.

## Acceptance Criteria

A draft is acceptable for this POC if:

1. it contains one real common-ground signal
2. the common ground is specific, not generic
3. it connects that signal to the sender's background or `Job Hunt Copilot`
4. it establishes credibility before leaning on the autonomous-email gimmick
5. it asks for a 15-minute conversation with a concrete reason
6. it does not ask directly for a job or referral
7. it reads like a plausible human email
8. it uses evidence that actually exists in the supplied inputs
9. it remains useful even if the recipient does not have hiring influence

## Evaluation Questions

Each generated draft should be reviewable against these questions:

1. What specific signal did the system choose as common ground?
2. Is that signal genuinely interesting and technically discussable?
3. Does the draft show evidence that the sender actually looked at the project or role?
4. Does the draft make the sender sound worth replying to?
5. Does `Job Hunt Copilot` support credibility without taking over the email?
6. Is the coffee-chat ask concrete and low-pressure?
7. Would this email still make sense if the recipient does not want to help with hiring directly?
8. Did the system avoid inventing details that were not in the research record?

## Test Strategy

The POC should eventually have tests at three levels:

1. deterministic unit tests for profile resolution, repo research, and record normalization
2. stage-contract tests for selector, analyzer, and drafter payload validation
3. end-to-end fixture tests that validate the email against the acceptance criteria

Prompt text does not need literal snapshot-locking, but behavior should remain consistent with this spec.

## Example Scenarios

The spec should support at least these scenario types:

1. GitHub-present engineer with one strong repo hook
2. GitHub-present engineer with multiple plausible repos
3. GitHub-present engineer with weak repos, forcing theme-level selection
4. GitHub-missing contact, forcing role/company fallback

The current Hariharan example is one useful validation case, but the spec should not be written so narrowly that it only fits that example.

## Near-Term Extensions

After the POC stabilizes, likely extensions are:

1. structured badge normalization from LinkedIn job-alert cards
2. personal-site and blog enrichment
3. role/company fallback drafts when GitHub is missing
4. evaluation scoring for draft quality
5. optional send path after human approval
