# Job Hunt Copilot — Technical Spec (V4 Draft)

- **Status:** Draft v0.3 (v4 two-pronged LinkedIn leads update)
- **Date:** April 1, 2026
- **Owner:** Achyutaram Sonti
- **Source:** Consolidated from working conversation transcript
- **Document Type:** Living specification (iterative updates expected)

---

## 1. Project Goal

Build a progressively autonomous **Job Hunt Copilot** that can:
1. Capture LinkedIn-rooted leads through two complementary upstream modes:
   - manual browser capture for high-signal posts, profiles, and selected text
   - autonomous Gmail job-alert intake for passive lead collection
2. Tailor a resume for a specific job description (JD)
3. Discover relevant internal contacts and valid email IDs for role-targeted outreach
4. Draft and send personalized outreach, attaching the tailored resume for role-targeted outreach and supporting learning-first outreach when no role-specific resume is needed

This spec captures what has been finalized so far and what remains open.

## 1.0 Bird's-Eye Cheat Sheet

### Project View
```text
Job Hunt Copilot
|
|-- LinkedIn Lead Acquisition
|
|-- Resume Tailoring
|
|-- Operations / Supervisor Agent
|
|-- Email Outreach
    |
    |-- Contact Search / People Discovery
    |-- Email Discovery
    |-- Email Drafting and Sending
    |-- Delivery Feedback
```

### Flow View (Primary Role-Targeted Flow)
```text
Manual Capture or Gmail Job Alert
    ->
Lead Normalization / Handoff
    ->
Resume Tailoring
    ->
Mandatory Agent Review
    ->
Contact Search / Linking
    ->
Email Discovery
    ->
Email Drafting and Sending
    ->
Delivery Feedback
    ->
Post-Run Expert Review Packet
    ->
Learning / future improvement
```

General learning outreach is a lighter contact-rooted path that may skip resume tailoring and resume attachment.

### Responsibility View
```text
LinkedIn Lead Acquisition
    writes: canonical lead source, split/review artifacts, lead manifest

Contact Search / Email Discovery
    writes: candidate contacts, discovered email state, provider budget state, discovery history

Resume Tailoring
    writes: tailored resume

Operations / Supervisor Agent
    writes: pipeline runs, supervisor-cycle audit, incidents, review packets, control state

Email Drafting and Sending
    writes: draft content, send action, raw send result

Delivery Feedback
    writes: normalized delivery outcome (bounced / not-bounced / etc.)

Other components
    read what they need
```

### Current vs Future
```text
Now:
- two-pronged LinkedIn lead acquisition
- Apollo-first people search for company-scoped contact discovery
- provider-based email discovery and enrichment for selected contacts
- resume tailoring
- full-frontier draft preparation with per-posting send pacing
- delivery feedback storage
- launchd-driven supervisor heartbeat with chat-first control and post-run expert review packets

Later:
- richer browser-side ergonomics and higher-automation capture flows
- multi-provider people-search waterfall beyond the Apollo-first path
- Email Pattern Learning Engine
- provider-independent discovery for eligible domains
```

### 1.1 Autonomy Phases
1. **Current phase (agent-operated with expert oversight):** The role-targeted pipeline may proceed end-to-end without a mandatory human pause, but mandatory review gates are still present. The AI agent performs those reviews autonomously, records the review outcome, and then continues, revises, retries, or escalates according to policy. After each terminal or otherwise review-worthy end-to-end run outcome, the agent prepares an expert review packet so the human expert can keep the system on course.
2. **Future phase (broader autonomy and capability):** Later iterations may expand provider coverage, richer maintenance behavior, and more advanced learning loops without changing the core autonomous operating model.

### 1.2 Scope-Clarity Summary

This document now uses these reading rules:
1. Unless a requirement is explicitly marked `best-effort`, `optional`, `deferred`, `later`, or `future`, it should be read as a current-build requirement.
2. `Best-effort` means the system should try the behavior when inputs/provider conditions allow, but pipeline success must not depend on it.
3. `Optional` means the artifact or behavior may exist and may be useful, but downstream logic must not assume it always exists.
4. `Deferred` means the behavior is intentionally out of the current build's required implementation path.

Current-build required path:
1. autonomous Gmail LinkedIn job-alert intake
2. JD recovery and lead handoff into canonical posting state
3. Resume Tailoring
4. mandatory agent review of the tailored resume after verification/finalize
5. DB-first Outreach bootstrap by `job_posting_id`
6. Apollo-first company-scoped people search
7. shortlist-time contact materialization
8. selected-contact enrichment
9. person-scoped email discovery only when enrichment still lacks a usable email
10. send-set-ready batch drafting
11. paced autonomous sending
12. immediate per-message delivery feedback plus delayed mailbox polling
13. post-run expert review packet generation by the supervisor agent

Current-build optional / best-effort behavior:
1. company-site or careers-page JD recovery and company resolution enrichment
2. LinkedIn public-profile extraction into `recipient_profile.json`
3. optional AI second pass for ambiguous lead splits after the rule-based review path flags ambiguity
4. mirrored `post.md` / `poster-profile.md` tailoring context when available

Deferred / later behavior:
1. richer manual browser-capture UX beyond the current initial path
2. multi-provider people-search waterfall beyond Apollo-first
3. company-level email-pattern reuse / Email Pattern Learning Engine
4. detailed two-step learning-first outreach operational flow
5. broader recipient-type-specific drafting strategy expansion
6. reply classification beyond the current high-level delivery states
7. automatic follow-up generation and sending
8. serverized or remote recipient-profile extraction infrastructure

---

## 2. Scope and Components

### 2.1 In Scope
1. LinkedIn Lead Acquisition upstream component
   Current intake modes:
   - manual browser capture with hotkeys, context menu, and selected-text support
   - autonomous Gmail LinkedIn job-alert intake with JD fetch
   - repo-local paste inbox as manual fallback
2. Resume Tailoring Component
3. Email Outreach Component
   Current subcomponents:
   - Contact Search / People Discovery
   - Email Discovery / Enrichment
   - Email Drafting and Sending Subcomponent
   - Delivery Feedback Subcomponent
4. Operations / Supervisor Agent Component
5. Structured artifact persistence so work can be resumed/audited

### 2.2 Future Scope
1. Richer browser extension UX beyond the initial tray/hotkey/context-menu flow
2. Multi-provider people-search waterfall beyond the Apollo-first implementation
3. WhatsApp integration
4. Email Pattern Learning Engine rollout beyond the current provider-based discovery flow

---

## 3. User Roles

1. **Primary User (Candidate)**
   - Provides job and lead context

2. **AI Agent (Supervisor / Copilot)**
   - Extracts structured signals
   - Generates tailored resumes
   - Runs email outreach workflows
   - Understands each lead profile
   - Writes outreach drafts using the relevant context for the current outreach mode
   - Attaches the tailored resume for role-targeted outreach when required and sends the email
   - Runs the autonomous control loop, performs mandatory agent review gates, repairs bounded operational failures, and prepares expert review packets after terminal or otherwise review-worthy end-to-end run outcomes

3. **Human Expert / Owner**
   - Reviews post-run expert packets to keep the system on course
   - Can override any eligibility/discovery/drafting/sending decision when needed
   - Can pause, resume, stop, redirect, or reject active autonomous behavior conversationally
   - Interacts with the AI agent conversationally to inspect queues, incidents, review packets, and runtime decisions

---

## 4. Foundational System-Design Labels (from discussion)

This is the agreed vocabulary for design discussions.

1. **Architectural Style**
   - Monolithic, microservices, event-driven, client-server

2. **Functional Requirements (FR)**
   - What the system must do (features/actions)

3. **Non-Functional Requirements (NFR / Quality Attributes)**
   - Scalability, reliability, performance, maintainability

4. **Communication Mechanisms**
   - Artifact-based file handoff (filesystem contracts between components)

5. **Internal Organization**
   - Layering, caching, modular boundaries

6. **Cross-Cutting Concerns**
   - Security, fault tolerance, monitoring/observability, evolution

---

## 5. System Inputs and Outputs

### 5.1 Required Input Context (role-targeted flow)
1. Every role-targeted lead shall enter through one of two upstream modes:
   - `manual_capture`: browser extension, hotkeys, context menu, or manual paste fallback
   - `gmail_job_alert`: LinkedIn alert email ingested from Gmail and enriched with JD fetch
2. Both upstream modes shall converge into one canonical lead workspace and one shared downstream handoff shape.
3. The minimum upstream goal is to persist enough raw evidence to recover company, role, and job-context signals, plus post/profile context when that evidence exists.
4. Candidate base resume track / base resume evidence
5. Candidate master profile file with expanded background details

### 5.1.1 LinkedIn Lead Acquisition Modes
1. `LinkedIn Scraping` is the historical upstream component name and now covers both manual LinkedIn capture and autonomous Gmail job-alert intake.
2. Manual capture is the high-signal path for LinkedIn browsing, selected text, copied posts, profile context, and one-click capture bundles.
3. Autonomous Gmail alert intake is the passive path for job-alert ingestion, JD fetch, and company-scoped contact search preparation.
4. Both modes shall produce a lead workspace keyed by `lead_id` and a machine-readable `lead-manifest.yaml`.
5. Manual-capture leads shall also persist a canonical `raw/source.md` plus split/review artifacts.
6. Autonomous Gmail-alert leads are not required to persist `raw/source.md` in the lead workspace and may instead rely on Gmail collection artifacts, references to parsed job-card metadata, and JD/provenance artifacts as their upstream source bundle.

### 5.1.2 LinkedIn Scraping Input Source Precedence
1. If both URL and raw text are available for post/JD/profile context, the raw captured text is the source-of-truth for that section when the lead mode materializes a canonical raw-source artifact.
2. For manual capture, explicitly selected text shall be preserved verbatim as captured evidence rather than being overwritten by later full-page normalization.
3. URLs are retained as references unless the selected `LinkedIn Scraping` mode explicitly marks a fetched body as the canonical source for a missing section.
4. For manual-capture leads, the canonical persisted lead source shall be the copied `raw/source.md` artifact in the lead workspace.
5. For autonomous Gmail-alert leads, the canonical upstream source bundle shall be the collected Gmail email artifact plus references to parsed job-card metadata and any persisted JD/provenance artifacts, rather than a required `raw/source.md` in the lead workspace.

### 5.1.3 Manual Capture and Paste Fallback Workflow
1. The manual capture path shall support hotkeys, popup-tray submission, and a context-menu or equivalent `send selected text` action.
2. Each manual submission should carry a capture bundle with one or more capture items that can include:
   - `capture_mode` such as `selected_text` or `full_page`
   - `page_type` such as `post`, `job`, `profile`, or `unknown`
   - `source_url`, `page_title`, `selected_text`, `full_text`, and `captured_at`
3. The browser-side capture flow shall send data to a local upstream receiver owned by the copilot; the browser extension is not expected to write arbitrary repo files directly.
4. When a manual submission is accepted, the upstream shall persist a machine-readable capture artifact such as `capture-bundle.json` and shall assemble the canonical human-readable `raw/source.md`.
5. The next build shall also keep a repo-local paste inbox at `paste/paste.txt` as a manual fallback for copied lead dumps when the browser capture flow is not used.
6. The user may replace the contents of `paste/paste.txt` between leads; the inbox file is reusable scratch input, not canonical history.
7. When `LinkedIn Scraping` ingests from the paste inbox, the pasted file contents shall be copied unchanged into the lead's canonical raw source.

### 5.1.4 Autonomous Gmail Job Alert Workflow
1. The autonomous path shall execute as an agent-invoked Gmail ingestion run. In each such run, `LinkedIn Scraping` shall ingest LinkedIn job-alert emails from Gmail and persist each collected alert email once in a dedicated Gmail collection area owned by `LinkedIn Scraping` before per-card lead materialization begins.
2. Each collected Gmail alert email shall be stored as a collected-email unit keyed by `received_at + gmail_message_id`. Collection order shall be represented through explicit Gmail `received_at` timestamps and timestamp-keyed path naming rather than inferred from filesystem ordering alone.
3. For Gmail collection idempotency, the same Gmail message shall be determined by `gmail_message_id`. If a message with an already-collected `gmail_message_id` is encountered again, the autonomous path shall ignore that duplicate rather than overwriting or versioning the existing collected-email unit.
4. `gmail_thread_id` shall be retained as reference metadata only. Multiple Gmail messages in the same thread shall still be collected and parsed independently, and thread membership alone shall not suppress collection or job-card parsing for any individual message.
5. In the current build, the autonomous parser shall target `LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>` as the primary mailbox source and shall treat broader recommendation mail such as `jobs-listings@linkedin.com` as later-scope or secondary intake.
6. The autonomous parser shall prefer the Gmail `text/plain` body first and use HTML-derived text only as fallback when the plain-text body is missing or unusable.
7. The human-readable Gmail snapshot artifact `email.md` shall store one clean readable raw email snapshot for review, using `text/plain` when available and a noise-minimized HTML-derived text fallback only when plain text is unavailable or unusable. The machine-readable companion artifact `email.json` shall store normalized Gmail message metadata plus only the specific raw body parts and parse-relevant fields actually used by intake and review, rather than mirroring the full Gmail provider payload.
8. One Gmail alert email may contain multiple job cards. The collection artifact `job-cards.json` shall retain each parsed non-duplicate job card from that email even if JD recovery later fails for that card. If a collected Gmail message yields zero parseable job cards, the collected email artifacts shall still be retained, `job-cards.json` may be empty, and no lead workspace shall be created from that message. Zero-card Gmail-parse cases shall be surfaced for review when more than 3 such collected emails occur within a single Gmail ingestion run or when the cumulative unresolved count of such collected emails exceeds 3 across history.
9. Each parsed job card that survives validation and deduplication shall become its own candidate lead.
10. After a parsed alert card survives validation and deduplication, the autonomous path shall create the per-lead workspace immediately rather than waiting for JD recovery to succeed first.
11. A newly created autonomous lead workspace shall be marked `incomplete` until JD recovery succeeds and the lead is eligible for downstream handoff.
12. For autonomous Gmail-alert intake, LinkedIn `job_id` shall be the primary duplicate key for determining whether two parsed alert cards refer to the same underlying job.
13. If a newly parsed alert card resolves to a LinkedIn `job_id` that is already present for an existing autonomous lead, the duplicate card shall be ignored and the system shall not create a second lead for that same job.
14. If a parsed alert card does not yield a usable LinkedIn `job_id`, the autonomous path shall create and persist a synthetic fallback identity key for that card rather than dropping it solely for missing `job_id`.
15. When a synthetic fallback identity key is needed for an autonomous alert card, it shall be derived from the normalized LinkedIn job URL when that URL is available.
16. If a parsed alert card does not yield either a usable LinkedIn `job_id` or a usable LinkedIn job URL, that identifier gap alone shall not force review or rejection.
17. In that identifier-missing case, if no usable JD can be recovered from any supported source, the lead shall transition to `blocked_no_jd`.
18. The autonomous path shall extract, when available, company, role title, location, badge lines, source job URL, Gmail metadata, and alert metadata from the Gmail message.
19. When a usable LinkedIn job URL or job id is available, the autonomous path shall fetch the LinkedIn guest JD candidate as an input to canonical JD assembly.
20. If the company name or role title recovered from the fetched LinkedIn JD materially disagrees with the parsed Gmail alert-card identity, the lead shall be marked for review and downstream canonical company/role materialization shall remain blocked until that mismatch is resolved by the user.
21. Minor normalization differences such as legal-suffix variants in company names or abbreviation/expansion variants in role titles shall not be treated as a material disagreement and shall not require review.
22. The autonomous path shall resolve or derive company website/domain information for downstream people search and email discovery when possible, and may attempt company-site or careers-page JD recovery as best-effort enrichment.
23. When both a LinkedIn-derived JD candidate and a company-site-derived JD candidate are available for the same lead, the autonomous path shall compare them and treat matching content as the same underlying JD content.
24. If one JD source contains additional non-conflicting information that is absent from the other source, the autonomous path shall merge that additional information into the canonical `jd.md`.
25. If the LinkedIn-derived JD candidate and the company-site-derived JD candidate conflict materially, the autonomous path shall prefer the LinkedIn-derived JD content for the conflicting portion while still recording source provenance.
26. The canonical `jd.md` for an autonomous lead may therefore be a merged JD assembled from multiple recovered sources, with LinkedIn-derived content preferred for conflicts, and its provenance must record the final merged outcome and which sources contributed to that merged result.
27. Exact recovery of the same role from the company-hosted careers site is desirable but not required for candidate-lead creation when a usable JD can already be assembled from the available sources.
28. Autonomous leads may legitimately lack LinkedIn post or poster-profile context. In those cases, the lead manifest and split-review artifact shall explicitly mark those sections as unavailable rather than pretending the artifacts exist.
29. When JD recovery succeeds, the autonomous path shall persist the final canonical JD text into `jd.md` as a reviewable markdown artifact before later structured extraction runs.
30. Any later structured extraction for tailoring or eligibility shall read from the persisted `jd.md` artifact and associated canonical context files rather than depending only on transient fetch responses.
31. Once the lead has a valid non-mismatched company and role identity plus a usable JD, the system shall materialize a company/role-scoped downstream workspace so the posting's files are saved under that company-scoped area rather than as ad hoc loose files. The exact folder layout is deferred to the dedicated folder-structure pass.

### 5.1.4A Autonomous Feature Intent (Current Product Idea)
1. The autonomous feature starts from LinkedIn job-alert emails that already arrive in the user's Gmail inbox.
2. Each parsed alert job card becomes a candidate role-targeted lead rather than treating the whole email as one lead.
3. For each captured job, the system should first recover the JD from the LinkedIn guest job payload when the job URL supports it.
4. The system should also try to recover the company website, company careers page, or exact company-hosted job page as provenance or enrichment, but those company-site lookups are best-effort rather than the hard first step.
5. The JD used to create the tailored resume may come from the LinkedIn guest payload or a stable company-hosted job page, but it must carry persisted provenance so the source is reviewable later.
6. After JD capture, the system shall use Apollo to search the company for relevant internal people such as engineering managers, software engineers, recruiters, and other potentially helpful employees who may be able to route the candidate to the right person.
7. The autonomous concept is intentionally high-recall: gather as many relevant people records as practical from Apollo before later filtering or pacing decisions are applied.
8. The outreach intent for this autonomous mode is not limited to asking for the job directly. The default posture is to cold email those discovered people asking whether they can connect the candidate to the right hiring person or otherwise help route the application internally.
9. The current v4 spec records this as the product intent for the autonomous path; later iterations will narrow the exact filtering, ranking, and send policy details.

### 5.1.4B Autonomous Dry-Run Findings (April 2026)
1. A real `jobalerts-noreply@linkedin.com` sample email required whitespace-tolerant parsing around dashed separators before all visible job cards were recovered from the plain-text digest.
2. After that parser fix, one sampled LinkedIn alert email produced 6 parseable job cards.
3. In that same sample, LinkedIn guest JD recovery succeeded for all 6 parsed cards.
4. In that same sample, company-site exact-role recovery yielded only 1 weak search-page match and no dependable exact same-role page for the other 5 cards.
5. Therefore the current product direction treats LinkedIn guest JD recovery as the operational baseline for autonomous intake and treats company-site resolution as best-effort enrichment/provenance.

### 5.1.5 LinkedIn Scraping Split and Review Strategy
1. `LinkedIn Scraping` shall use a deterministic rule-based first pass before any optional AI assistance is considered when the lead mode includes a canonical `raw/source.md`.
2. For leads that include `raw/source.md`, the rule-based first pass shall derive `jd.md`, `post.md`, and `poster-profile.md` from that canonical raw source when the source contains those sections.
3. Manual capture bundles may seed page-type-aware section boundaries before the generic rule-based pass runs, but the persisted canonical source remains `raw/source.md`.
4. For leads that include `raw/source.md`, the selected split shall be persisted as a machine-readable metadata artifact at `linkedin-scraping/runtime/leads/<company>/<role>/<lead_id>/source-split.yaml`.
5. For leads that include `raw/source.md`, split review shall also produce a machine-readable review artifact at `linkedin-scraping/runtime/leads/<company>/<role>/<lead_id>/source-split-review.yaml`.
6. The review artifact shall include at least split status, confidence, coverage, validation checks, findings, recommended next action, acquisition mode, and derived-artifact availability when split review is applicable.
7. If the first pass is ambiguous, the system shall preserve the canonical raw source and derived outputs, mark the lead for review, and may optionally attempt an AI second pass.
8. Any AI second pass shall be bounded by the canonical raw source, shall record whether it was attempted and whether it was accepted, and shall never overwrite or discard the original `raw/source.md`.
9. The system shall prefer reviewability over aggressive cleanup: if there is doubt, it shall retain more source text in the derived sections rather than drop potentially useful evidence.
10. The splitter shall recognize recruiter-authored hiring posts even when the copied post uses plain-language hiring markers such as `We're hiring`, `We’re hiring`, or `hiring at` instead of a literal `#hiring` token.
11. The splitter shall preserve networking-relevant post signals, such as copied alumni counts or similar relationship hints, when those signals may materially affect outreach strategy, prioritization, or contact selection.
12. For autonomous Gmail-alert leads that do not materialize `raw/source.md`, source-split and split-review artifacts are not required by default.

### 5.1.6 Lead Handoff and Entity Materialization
1. `LinkedIn Scraping` is the upstream component for lead ingestion and handoff.
2. Each ingested lead shall receive a stable internal `lead_id`.
3. `LinkedIn Scraping` shall own the upstream raw-source workspace, source-mode artifacts, split files, split-review artifacts, and machine handoff manifest for that lead.
4. The canonical lead workspace root shall be `linkedin-scraping/runtime/leads/<company>/<role>/<lead_id>/`.
5. Every lead workspace shall contain `lead-manifest.yaml` plus the source-mode-specific artifacts needed for that lead.
6. Manual-capture leads shall also contain `raw/source.md`, `source-split.yaml`, and `source-split-review.yaml`.
7. Autonomous Gmail-derived leads are not required to contain `raw/source.md`, `source-split.yaml`, or `source-split-review.yaml` in the lead workspace by default.
8. For autonomous Gmail-derived leads, the originating Gmail collection references and parsed job-card references should be carried in `lead-manifest.yaml` rather than requiring additional lead-local metadata files by default.
9. The source-of-truth external-source metadata for a lead, such as source mode, source reference, and source URL, shall belong to the lead entity rather than to `job_postings`.
10. `LinkedIn Scraping` shall hand off to downstream components through `lead-manifest.yaml` plus the referenced lead artifacts rather than through hardcoded path assumptions.
11. Downstream handoff shall be blocked whenever split review remains `ambiguous` when split review is applicable for that lead mode.
12. A valid non-ambiguous JD shall be required before the component auto-creates a canonical `job_posting`.
13. When a poster or other explicit person/profile block is identifiable in a non-ambiguous lead, the component may auto-create canonical `contacts`, lead-contact trace rows, and posting-contact links as part of lead handoff.
14. The component shall support overwrite-in-place refresh of the live lead workspace while preserving prior source and review snapshots under lead-local history artifacts for auditability.

### 5.1.6A Component-Oriented Filesystem Layout
1. The next build shall use a component-oriented filesystem layout: each major component owns its own code, runtime/output folders, and machine handoff artifacts under its top-level directory.
2. The stable business identity shared across those component-owned folders shall be `{company_slug}/{role_slug}` for role-targeted work, with `lead_id`, `contact_id`, and `outreach_message_id` remaining the canonical object identifiers inside artifacts and DB state.
3. For basic functioning, `company_slug` and `role_slug` shall be lowercase kebab-case path segments derived from the chosen canonical company and role text by trimming, lowercasing, converting whitespace and slash-like separators to `-`, removing other punctuation, and collapsing repeated hyphens. The dry-run path `applications/prepass/software-engineer/...` is the reference shape.
4. The current component-owned path direction is:
   - `applications/{company}/{role}/application.yaml` for the readable posting-local mirror of manual application state
   - `linkedin-scraping/runtime/gmail/{YYYYMMDDTHHMMSSZ}-{gmail_message_id}/...` for collected Gmail email snapshots and parse artifacts before per-lead fan-out
   - `linkedin-scraping/runtime/leads/{company}/{role}/{lead_id}/...` for upstream lead-intake artifacts
   - `resume-tailoring/output/tailored/{company}/{role}/...` for resume-tailoring workspace artifacts
   - `discovery/output/{company}/{role}/...` for people-search and email-discovery runtime outputs
   - `outreach/output/{company}/{role}/...` for draft/send/delivery runtime outputs
5. Component-level caches, learned data, and provider-budget state that are not specific to one posting may remain in component-owned shared folders such as `discovery/data/` or `outreach/data/`.
6. The spec intentionally prefers this component-oriented layout over a single shared `companies/` root for now, so implementation can follow the current repo's component boundaries.

### 5.2 Contact Search / Discovery Input (minimum)
1. For company-scoped people search:
   - company name
   - role title or job family
   - JD text or job URL when available
   - company domain/website when available
2. For person-scoped email discovery:
   - person full name
   - company name
   - LinkedIn URL (if available)

### 5.2.1 Contact Search / Discovery Interpretation (Current)
1. In the current workflow, role-targeted leads should first attempt company-scoped people search when explicit internal contacts are not already available from the lead itself.
2. Apollo is the current primary provider for company-scoped people search. PDL, Coresignal, ContactOut, and Clay-style waterfalls are later expansion options.
3. If people search or enrichment returns a usable work email for a selected contact, the system may skip separate person-scoped email-finder calls for that contact.
4. Email Discovery shall use company name directly for provider lookup when the selected provider supports it.
5. Email Discovery shall resolve or derive the usable company domain internally only when a provider requires domain input.
6. Company domain is an internal operational field in this build, not a required user-facing input.

### 5.3 Core Outputs
1. Tailored resume artifact(s)
2. Company-scoped contact candidates and discovered email candidate(s) with confidence metadata
3. Personalized outreach draft(s)
4. Delivery status metadata (sent/bounced/replied)

---

## 6. End-to-End Workflow (High Level)

1. Ingest lead through `LinkedIn Scraping` using either manual browser capture or autonomous Gmail job-alert intake
2. Persist the canonical raw source plus any source-mode-specific artifacts
3. Derive available `jd.md`, `post.md`, and `poster-profile.md` sections and publish `lead-manifest.yaml`
4. Materialize lead, posting, and explicit-contact entities when the lead is eligible for handoff
5. Run eligibility gate (hard disqualifiers first)
6. Map JD signals to real candidate evidence
7. Generate tailored resume
8. Run the mandatory agent resume review, then approve, revise, retry, or escalate based on that review outcome
9. Run Apollo-first company-scoped people search to gather relevant internal contacts for the company
10. Enrich or discover missing emails for the selected contacts
11. Generate drafts across the ready posting frontier and send personalized outreach that asks those contacts to connect the candidate to the right person, using ranked waves, active send slices, and per-posting pacing
12. Capture delivery feedback
13. Feed outcomes back into lead/contact history and learning signals

---

## 7. Functional Requirements

## 7.1 System-Level FRs

- **FR-SYS-01:** System shall accept and persist lead-rooted input context through the `LinkedIn Scraping` upstream component.
- **FR-SYS-01A (Two Lead-Acquisition Modes):** `LinkedIn Scraping` shall support both `manual_capture` and `gmail_job_alert` as first-class upstream lead-ingestion modes.
- **FR-SYS-01B (Shared Lead Workspace Rule):** Both upstream modes shall converge into the same canonical lead workspace shape and lead-manifest handoff contract.
- **FR-SYS-01C (Manual Browser-Capture Support):** The manual path shall support browser-driven capture actions such as hotkeys, popup-tray submission, and selected-text capture.
- **FR-SYS-01C1 (Selected-Text Immediate-Submit Default):** When the user has explicitly selected text and invokes manual capture through the selected-text path, the default behavior should be immediate submission of that selected text into the local upstream receiver rather than forcing a tray-review detour first.
- **FR-SYS-01C2 (Tray-Review Default for Full-Page Capture):** When manual capture is invoked without explicit selected text, the default behavior should open the tray/popup review surface first so the user can confirm or adjust the full-page capture payload before submission.
- **FR-SYS-01C3 (Manual Capture UX Convergence Rule):** Both the selected-text path and the tray-review path shall converge into the same shared capture bundle contract. Selected text remains preserved verbatim when present, while the tray-review path remains the place to add notes, confirm metadata, or submit a full-page capture intentionally.
- **FR-SYS-01D (Selected-Text Preservation Rule):** When manual capture provides explicit selected text, that selected text shall be preserved verbatim in the source-mode artifacts and shall not be silently overwritten by later full-page extraction.
- **FR-SYS-01E (Manual Transport Boundary):** Manual browser capture shall reach the repo through a local copilot-owned upstream receiver rather than by granting the browser direct arbitrary file-write access to the workspace.
- **FR-SYS-01F (Paste Inbox Availability):** The next build shall materialize a repo-local paste inbox at `paste/paste.txt` so large copied lead dumps can still be provided through the filesystem as a manual fallback.
- **FR-SYS-01G (Paste Inbox LinkedIn-Scraping Entry Path):** The system shall support starting lead ingestion from `paste/paste.txt` or an explicitly provided replacement paste-file path.
- **FR-SYS-01H (Autonomous Gmail-Alert Intake):** The autonomous path shall support agent-invoked LinkedIn job-alert ingestion runs from Gmail and shall persist alert-derived lead context into the shared lead workspace.
- **FR-SYS-01H1 (Primary Gmail Sender Rule):** In the current build, the autonomous Gmail-alert path shall target `LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>` as the primary mailbox source. Support for other LinkedIn recommendation senders may be added later without changing the shared lead contract.
- **FR-SYS-01H2 (Plain-Text-First Gmail Parse Rule):** The autonomous parser shall prefer the Gmail `text/plain` body first and shall use HTML-derived text only as fallback when the plain-text body is unavailable or unusable.
- **FR-SYS-01H2A (Readable Gmail Snapshot Rule):** The human-readable Gmail snapshot artifact `email.md` shall contain one clean readable raw email snapshot for review, using `text/plain` when available and a noise-minimized HTML-derived text fallback only when plain text is unavailable or unusable.
- **FR-SYS-01H2B (Machine-Readable Gmail Snapshot Rule):** The machine-readable Gmail snapshot artifact `email.json` shall store normalized Gmail message metadata plus only the specific raw body parts and parse-relevant fields actually used by intake and review, rather than mirroring the full Gmail provider payload.
- **FR-SYS-01H3 (Gmail Collection Staging Rule):** In the autonomous Gmail-alert mode, each collected Gmail message shall be persisted once in a Gmail collection area under `linkedin-scraping/runtime/gmail/`, keyed by `received_at + gmail_message_id`, before per-card lead materialization begins.
- **FR-SYS-01H3A0 (Idempotent Gmail Collection Rule):** For Gmail collection idempotency, the same Gmail message shall be determined by `gmail_message_id`. If a message with an already-collected `gmail_message_id` is encountered again, the autonomous path shall ignore that duplicate rather than overwriting or versioning the existing collected-email unit.
- **FR-SYS-01H3A1 (Gmail Thread Reference Rule):** `gmail_thread_id` shall be treated as reference metadata only. Multiple collected Gmail messages in the same thread shall still be collected and parsed independently, and thread membership alone shall not suppress collection or job-card parsing for any individual message.
- **FR-SYS-01H3A (Gmail Job-Card Retention Rule):** The Gmail collection artifact `job-cards.json` shall retain each parsed non-duplicate job card from the collected email even if JD recovery later fails for that card.
- **FR-SYS-01H3B (Zero-Card Gmail Parse Escalation Rule):** If a collected Gmail message yields zero parseable job cards, the collected email artifacts shall still be retained, `job-cards.json` may be empty, and no lead workspace shall be created from that message. These zero-card cases shall be surfaced for review when more than 3 such collected emails occur within a single Gmail ingestion run or when the cumulative unresolved count of such collected emails exceeds 3 across history.
- **FR-SYS-01H3C (Durable Gmail History Checkpoint Rule):** Autonomous Gmail lead polling shall persist a durable mailbox history checkpoint and use that checkpoint for incremental polling when available rather than relying only on bounded recent-message searches.
- **FR-SYS-01H3C1 (Checkpoint Recovery Rule):** If incremental Gmail history polling encounters a referenced Gmail message that can no longer be fetched, such as a deleted or otherwise unavailable mailbox item, the collector shall not stall intake. It shall recover by resetting to a bounded recent-search poll over the configured LinkedIn alert senders and continue collecting currently available uncollected messages.
- **FR-SYS-01H3D (Checkpoint-Seed No-Work Rule):** When Gmail intake seeds or refreshes the mailbox history checkpoint without materializing any new lead cards, the run shall persist an auditable no-work outcome rather than surfacing a false incident or pretending a collection unit exists.
- **FR-SYS-01H3E (Digest-Summary Header Filter Rule):** Gmail alert fan-out shall ignore digest-summary headers or summary-only cards, such as `30+ new jobs match your preferences` or `Your job alert for ...`, and shall not materialize them as canonical leads or job postings.
- **FR-SYS-01H3F (Duplicate-Identity Canonicalization Rule):** If autonomous Gmail intake encounters a lead identity that resolves to an already-existing canonical lead or posting, the system shall merge or refresh that canonical identity instead of crashing on duplicate creation.
- **FR-SYS-01I (Autonomous JD-Fetch Provenance):** When the autonomous path assembles a canonical JD from LinkedIn guest job data, a company job page, or another stable job source, the system shall persist one final merged provenance-and-outcome record for that canonical JD.
- **FR-SYS-01I1 (Alert-Card-to-Lead Rule):** In the autonomous mode, each parsed LinkedIn job-alert card that survives validation and deduplication shall become a candidate role-targeted lead.
- **FR-SYS-01I1A0 (Autonomous Workspace-Creation Timing Rule):** After a parsed autonomous alert card survives validation and deduplication, the system shall create the per-lead workspace immediately rather than waiting for JD recovery to succeed first.
- **FR-SYS-01I1A1 (Autonomous Incomplete-Until-JD Rule):** A newly created autonomous lead workspace shall be marked `incomplete` until JD recovery succeeds and downstream handoff can be evaluated.
- **FR-SYS-01I1A2 (Autonomous Blocked-No-JD Rule):** If JD recovery does not succeed for an autonomous lead workspace, that lead shall transition from `incomplete` to `blocked_no_jd`.
- **FR-SYS-01I1A (Autonomous Duplicate-Key Rule):** For autonomous Gmail-alert intake, LinkedIn `job_id` shall be the primary duplicate key for determining whether two parsed alert cards refer to the same underlying job.
- **FR-SYS-01I1B (Autonomous Duplicate-Ignoring Rule):** If a newly parsed alert card resolves to a LinkedIn `job_id` already associated with an existing autonomous lead, the system shall ignore that duplicate card rather than create a second lead for the same job.
- **FR-SYS-01I1C (Autonomous Missing-Job-ID Fallback Rule):** If a parsed autonomous alert card does not yield a usable LinkedIn `job_id`, the system shall create and persist a synthetic fallback identity key for that card rather than dropping it solely for missing `job_id`.
- **FR-SYS-01I1D (Autonomous URL-Derived Fallback Key Rule):** When an autonomous alert card needs a synthetic fallback identity key, that key shall be derived from the normalized LinkedIn job URL when that URL is available.
- **FR-SYS-01I1E (Autonomous Identifier-Gap Non-Blocking Rule):** If a parsed autonomous alert card yields neither a usable LinkedIn `job_id` nor a usable LinkedIn job URL, that identifier gap alone shall not force review or rejection.
- **FR-SYS-01I1F (Autonomous No-JD Terminal Rule):** In that missing-identifier case, if no usable JD can be recovered from any supported source, the lead shall transition to `blocked_no_jd`.
- **FR-SYS-01I2 (LinkedIn JD Candidate Recovery Rule):** When a parsed alert card exposes a usable LinkedIn job URL or job id, the autonomous mode shall fetch the LinkedIn guest JD candidate as an input to canonical JD assembly.
- **FR-SYS-01I2A (Autonomous Identity-Mismatch Review Rule):** If the company name or role title recovered from the fetched LinkedIn JD materially disagrees with the parsed Gmail alert-card identity, the lead shall be marked for review and downstream canonical company/role materialization shall remain blocked until the user resolves that mismatch.
- **FR-SYS-01I2B (Autonomous Identity-Normalization Tolerance Rule):** Minor normalization differences such as legal-suffix variants in company names or abbreviation/expansion variants in role titles shall not be treated as a material disagreement and shall not require review.
- **FR-SYS-01I3 (Company-Site JD Candidate Recovery Rule):** The autonomous mode should attempt company-website or careers-page JD recovery and record the result, but failure to recover an exact company-hosted job page shall not block lead creation when a usable JD can still be assembled from the available sources.
- **FR-SYS-01I4 (Autonomous JD Compare-and-Merge Rule):** When more than one JD candidate source is available for the same autonomous lead, the system shall compare the recovered JD candidates, treat matching content as the same underlying JD content, and merge additional non-conflicting information into the canonical `jd.md`.
- **FR-SYS-01I4A (Autonomous JD Conflict Preference Rule):** If the recovered JD candidates conflict materially, the system shall prefer LinkedIn-derived JD content for the conflicting portion while still recording source provenance.
- **FR-SYS-01I5 (Canonical Merged JD Persistence Rule):** When autonomous JD recovery succeeds, the system shall persist the final canonical JD text in `jd.md`, and that canonical JD may be a merged result assembled from multiple recovered sources with one final merged provenance record.
- **FR-SYS-01I6 (Structured-From-Persisted-JD Rule):** Eligibility checks, JD-signal extraction, and other downstream structuring stages shall derive their structured outputs from the persisted `jd.md` artifact and canonical context files rather than only from transient fetch responses.
- **FR-SYS-01I7 (Company-Scoped Workspace Rule):** Once a valid company and role are known for a role-targeted lead, the downstream posting/application files shall be materialized under a company/role-scoped workspace. The exact folder layout is deferred, but company-scoped filesystem grouping is required.
- **FR-SYS-01J (Canonical Lead Raw Source Rule):** For lead modes that materialize a canonical raw-source artifact, the system shall persist exactly one canonical raw-source artifact at `linkedin-scraping/runtime/leads/<company>/<role>/<lead_id>/raw/source.md`.
- **FR-SYS-01K (Lead-Specific Source Artifact Rule):** The lead workspace may additionally persist source-mode-specific artifacts such as `capture-bundle.json` for manual capture or lead-local references to originating Gmail collection artifacts, references to parsed job-card metadata, JD-fetch provenance, and company-resolution artifacts for Gmail-alert intake.
- **FR-SYS-01L (Derived Lead Artifact Availability Rule):** `linkedin-scraping/runtime/leads/<company>/<role>/<lead_id>/jd.md`, `post.md`, and `poster-profile.md` are derived/normalized lead artifacts. They shall exist when the upstream evidence supports them and shall otherwise be explicitly marked unavailable in lead metadata rather than being treated as raw-source artifacts.
- **FR-SYS-01M (Lead Refresh Replacement Rule):** If `LinkedIn Scraping` is explicitly rerun with a new raw source file for a lead that materializes `raw/source.md`, the live canonical `raw/source.md` shall be replaced by that new explicit source. If later updates do not provide a new raw source, the existing live `raw/source.md` shall be preserved.
- **FR-SYS-01N (Rules-First Lead Split Rule):** `LinkedIn Scraping` shall run a deterministic rule-based first pass over the canonical `raw/source.md` before any optional AI-assisted re-segmentation is attempted when that lead mode materializes `raw/source.md`.
- **FR-SYS-01O (Lead Split Metadata Rule):** When a lead mode materializes `raw/source.md`, the first-pass or selected lead split shall be persisted as `linkedin-scraping/runtime/leads/<company>/<role>/<lead_id>/source-split.yaml` with machine-readable section boundaries, selected method, omitted-segment metadata, and any explicit page-type hints received from manual capture.
- **FR-SYS-01P (Lead Split Review Rule):** When a lead mode materializes `raw/source.md`, `LinkedIn Scraping` shall also persist `linkedin-scraping/runtime/leads/<company>/<role>/<lead_id>/source-split-review.yaml` containing review status, confidence, validation checks, findings, recommended next action, acquisition mode, and derived-artifact availability.
- **FR-SYS-01Q (Ambiguous Lead Split Escalation Rule):** If the rule-based first pass is ambiguous, the system shall preserve the canonical raw source, keep the derived artifacts reviewable, and mark the lead for review rather than silently treating the split as trustworthy.
- **FR-SYS-01R (Optional AI Second-Pass Rule):** An AI second pass may run only after the rule-based split has been reviewed and found ambiguous. Any accepted second-pass result shall record its provider/method provenance and shall be chosen only when it improves the split confidence relative to the rule baseline.
- **FR-SYS-01S (Plain-Language Hiring Marker Rule):** `LinkedIn Scraping` shall treat recruiter-authored phrases such as `We're hiring`, `We’re hiring`, `we are hiring`, and `hiring at` as valid post-start signals even when a copied lead dump does not include `#hiring`.
- **FR-SYS-01T (Networking-Signal Preservation Rule):** `LinkedIn Scraping` shall preserve networking-relevant post signals that may influence outreach planning, prioritization, or contact selection, such as copied alumni-count hints like `1 school alumni works here`.
- **FR-SYS-02:** System shall execute a pipeline across three top-level components: `LinkedIn Scraping -> Resume Tailoring -> Email Outreach`. The Email Outreach component shall contain discovery, drafting/sending, and delivery-feedback subcomponents.
- **FR-SYS-03:** System shall persist intermediate structured artifacts for resumability and auditing.
- **FR-SYS-04:** System shall support iterative refinement (spec, prompts, and outputs are revisitable and updatable).
- **FR-SYS-05 (Input Precedence Policy):** In this build, raw text inputs take precedence over URLs for post/JD/profile context when both are present; URLs are treated as references.
- **FR-SYS-06 (Central State Database):** The system shall use one central SQLite database, `job_hunt_copilot.db`, as the canonical source of truth for overall application/pipeline state and long-lived searchable operational data.
- **FR-SYS-07 (Files vs Database Boundary):** File artifacts remain the primary communication/handoff mechanism between components, while `job_hunt_copilot.db` stores canonical state, status, identifiers, and artifact metadata. If a file and the database disagree about system state, the database wins for state.
- **FR-SYS-08 (Entity-Based State Model):** The central database shall use an entity-based model rather than forcing the whole system to be rooted only in applications or only in contacts.
- **FR-SYS-09 (Primary Core Entities):** The central database shall treat these as the primary first-class entities:
  1. `linkedin_leads`
  2. `job_postings`
  3. `contacts`
- **FR-SYS-10 (Attached Supporting Records):** Other records, such as resume artifacts, lead-split artifacts, discovery attempts, drafts, sends, delivery-feedback events, and review metadata, shall attach to `linkedin_leads`, `job_postings`, `contacts`, or their linking records as appropriate.
- **FR-SYS-11 (Resume Tailoring Attachment Rule):** Resume-tailoring state and artifacts shall attach primarily to `job_postings`.
- **FR-SYS-12 (Email Discovery Attachment Rule):** Email-discovery state and history shall attach primarily to `contacts`.
- **FR-SYS-13 (Email Drafting and Sending Attachment Rule):** Email Drafting and Sending records shall always attach to `contacts`. They may additionally link to `job_postings` when the outreach is tied to a specific role or posting.
- **FR-SYS-14 (LinkedIn-Rooted Contact Identity):** When LinkedIn data is available, contacts shall be rooted in LinkedIn-derived identity and profile context. Outreach-side records such as discovery, draft/send, and delivery-feedback data shall attach to that contact record.
- **FR-SYS-15 (Top-Level State Split):** Top-level pipeline state shall be split by entity type:
  1. `linkedin_leads` carry upstream lead-ingestion, split-review, and handoff readiness state
  2. `job_postings` carry tailoring/application progression state
  3. `contacts` carry outreach/discovery progression state
- **FR-SYS-15A (Contact Status Set):** For this build, `contacts` should support a lightweight top-level status set such as:
  1. `identified`
  2. `discovery_in_progress`
  3. `working_email_found`
  4. `outreach_in_progress`
  5. `sent`
  6. `replied`
  7. `exhausted`
  These values summarize contact-level outreach/discovery lifecycle only. Detailed posting-specific, discovery-attempt, message, and delivery-feedback state shall remain in their own linked records.
- **FR-SYS-15B (Identified-to-Discovery Transition):** A `contact` shall transition from `identified` to `discovery_in_progress` when discovery begins for that contact and no clearly reusable working email is already available.
- **FR-SYS-15C (Identified-to-Working-Email Transition):** A `contact` may transition directly from `identified` to `working_email_found` when a clearly matched known working email already exists for that contact and fresh discovery is skipped.
- **FR-SYS-15D (Discovery-to-Working-Email Transition):** A `contact` shall transition from `discovery_in_progress` to `working_email_found` when discovery produces a usable email for that contact or reuses a clearly matched known working email.
- **FR-SYS-15E (Discovery-to-Exhausted Transition):** A `contact` shall transition from `discovery_in_progress` to `exhausted` when the automatic discovery path for that contact has been exhausted for the current flow without yielding a usable working email.
- **FR-SYS-15F (Working-Email-to-Outreach Transition):** A `contact` shall transition from `working_email_found` to `outreach_in_progress` when drafting or sending begins for that contact.
- **FR-SYS-15G (Outreach-to-Sent Transition):** A `contact` shall transition from `outreach_in_progress` to `sent` when an outreach message has been sent for that contact.
- **FR-SYS-15H (Sent-to-Replied Transition):** A `contact` shall transition from `sent` to `replied` when a reply is detected for that contact's outreach.
- **FR-SYS-15I (Post-Send-to-Exhausted Transition):** A `contact` may transition to `exhausted` after send when no further automatic discovery or outreach path remains for that contact in the current flow, such as when prior messages already exist and repeat outreach requires user review, or when bounce/retry paths have been exhausted.
- **FR-SYS-15J (Manual Application State Separation):** Manual application tracking shall be stored on `job_postings` as separate application fields and shall not overload or redefine `posting_status`, `pipeline_runs.run_status`, or other autonomous workflow statuses.
- **FR-SYS-15K (Application State Set):** For this build, `job_postings` manual application state should support at least `not_applied`, `applied`, `interviewing`, `rejected`, `offer`, and `withdrawn`.
- **FR-SYS-15L (Application Field Set):** `job_postings` should carry manual application fields `application_state`, `applied_at`, `application_url`, `application_notes`, and `application_updated_at`.
- **FR-SYS-15M (Application Timestamp Autofill):** When the owner manually sets `application_state` to a non-`not_applied` value and no `applied_at` is provided, the system should autofill `applied_at` with the current timestamp if no prior applied timestamp exists.
- **FR-SYS-15N (Application State Forward-Only Rule):** In the current build, manual application tracking is forward-only. It should not support resetting a posting back to `not_applied`.
- **FR-SYS-15O (Application Mirror Rule):** When manual application state changes, the canonical DB must be updated and a readable mirror must be written to `applications/{company}/{role}/application.yaml`.
- **FR-SYS-15P (Manual Responder State Separation):** Responder or warm-contact tracking shall be stored on `contacts` as separate responder fields and shall not overload `contact_status`, which remains the outreach/discovery lifecycle field.
- **FR-SYS-15Q (Responder State Set):** For this build, contact responder state should support at least `none`, `replied`, and `warm`.
- **FR-SYS-15R (Responder Field Set):** `contacts` should carry responder fields `responder_state`, `responded_at`, `responder_notes`, and `responder_updated_at`.
- **FR-SYS-15S (Detected Reply to Responder Promotion):** When a real reply is persisted in `delivery_feedback_events`, the linked contact should automatically transition to `responder_state = replied` unless the contact is already `warm`.
- **FR-SYS-15T (First Reply Timestamp Rule):** `responded_at` should store the first known reply timestamp for that contact rather than the most recent reply time.
- **FR-SYS-15U (Manual Warm Promotion Rule):** The owner may manually promote a contact from `replied` to `warm` or directly from `none` to `warm`. Manual warm promotion does not require a known `responded_at` value.
- **FR-SYS-15V (Responder State Forward-Only Rule):** In the current build, responder tracking is forward-only. It should not support resetting a contact back to `none` or downgrading `warm` to `replied`.
- **FR-SYS-15W (Manual State Audit Rule):** Manual application updates and manual responder updates shall record `override_events` so those state changes remain queryable with reason text and timestamp.
- **FR-SYS-16 (Multi-Posting Contact Reuse):** A single contact may link to multiple `job_postings`. The system shall support contact reuse across multiple role or outreach contexts without requiring duplicate contact records for the same person.
- **FR-SYS-16A (Single Automatic Company Touch per Canonical Contact):** A canonical contact may be reused across multiple postings at the same canonical company, but automatic role-targeted outreach shall treat that person as a single automatic company touch. Once one posting at that company has already sent automatic outreach to that contact, later postings at that company shall not automatically send a second role-targeted email to the same canonical contact.
- **FR-SYS-16B (Same-Company Alternate Contact Continuation):** When a later posting at the same company excludes an already-contacted canonical contact from automatic outreach, the system shall continue with other eligible contacts from that company's remaining contact pool rather than stalling the posting immediately.
- **FR-SYS-16C (Same-Company No-Alternate Review Escalation):** If no alternate automatically eligible same-company contacts remain after the repeat-contact exclusion is applied, the system shall leave the posting unresolved and surface the case for review rather than auto-sending a second message to the already-contacted person.
- **FR-SYS-16D (Canonical Company Grouping Key):** Each `job_posting` shall carry a canonical company-grouping key used for same-company orchestration rules such as no-repeat automatic outreach across multiple postings.
- **FR-SYS-16E (Immediate Provisional Company Key):** The canonical company-grouping key shall exist immediately when the posting is materialized, even before external company resolution is available. The initial provisional form should be derived deterministically from the posting's normalized company name, such as `name:<normalized-company-name>`.
- **FR-SYS-16F (Provider-Backed Company Key Preference):** When a stable provider-backed company identifier becomes available, such as Apollo `organization_id`, the system should prefer a provider-backed canonical company-grouping key such as `apollo_org:<organization_id>` for same-company orchestration.
- **FR-SYS-16G (Provisional-to-Provider Reconciliation):** The same-company no-repeat policy shall begin working immediately from the provisional company-grouping key and remain continuous after provider resolution. When a provider-backed company identifier later becomes available, the system shall reconcile the posting into that stronger grouping rather than requiring same-company protections to wait until provider resolution.
- **FR-SYS-17 (Multi-Contact Job Posting Coverage):** A single `job_posting` may link to multiple contacts. The system shall support multiple outreach targets for the same posting, such as hiring managers, recruiters, engineers, and alumni-connected contacts.
- **FR-SYS-17A (Job-Posting Status Set):** For this build, `job_postings` should support a lightweight top-level status set such as:
  1. `sourced`
  2. `hard_ineligible`
  3. `tailoring_in_progress`
  4. `resume_review_pending`
  5. `requires_contacts`
  6. `ready_for_outreach`
  7. `outreach_in_progress`
  8. `completed`
  9. `abandoned`
  10. `closed_by_user`
  These values summarize posting-level lifecycle only. Detailed contact, discovery, draft/send, and delivery progress shall remain in their own linked records.
- **FR-SYS-17B (No-Contact Ready State):** If a `job_posting` has cleared tailoring and mandatory agent review but does not yet have the required linked contacts and discovered outreach-ready emails for the current role-targeted flow, its posting-level status shall remain `requires_contacts` rather than advancing to `ready_for_outreach`.
- **FR-SYS-17B1 (Required Linked Contacts Meaning):** For this build, `required linked contacts` should mean at least one actionable linked contact in the best currently available priority tier for that posting. In practice:
  1. prefer `hiring_manager` or `recruiter`
  2. if neither exists, a role-relevant `engineer`
  3. if no stronger role-proximate option exists, `alumni` or `other_internal` may serve as the fallback starting contact
  Additional contacts are desirable and may still be added later, but they do not need to be present before the posting can leave `requires_contacts`.
- **FR-SYS-17C (Ready-for-Outreach Meaning):** A `job_posting` shall be considered `ready_for_outreach` when:
  1. resume tailoring is complete
  2. the active tailoring run is approved by the mandatory agent review
  3. the posting has the required linked contacts for the current intended outreach set
  4. at least the intended current outreach set has discovered usable email addresses
- **FR-SYS-17D (Outreach-in-Progress Meaning):** A `job_posting` shall be considered `outreach_in_progress` once drafting and/or sending is actively occurring for the current outreach set tied to that posting.
- **FR-SYS-17E (Completed Meaning):** A `job_posting` shall be considered `completed` when no untouched automatically eligible contacts remain for that posting after the current shortlisted contact pool, repeat-contact exclusions, and automatic discovery outcomes have been applied. Bounced contacts or bounced messages may still surface separately for review and corrective action, but those review items do not by themselves block the posting from reaching `completed`.
- **FR-SYS-17F (Sourced-to-Hard-Ineligible Transition):** A `job_posting` shall transition from `sourced` to `hard_ineligible` when the hard-disqualifier gate is triggered.
- **FR-SYS-17G (Sourced-to-Tailoring Transition):** A `job_posting` shall transition from `sourced` to `tailoring_in_progress` when the posting passes the hard-disqualifier gate and Resume Tailoring begins.
- **FR-SYS-17H (Tailoring-to-Review Transition):** A `job_posting` shall transition from `tailoring_in_progress` to `resume_review_pending` when tailoring/finalize work is complete and the tailored resume is ready for the mandatory agent review gate.
- **FR-SYS-17I (Review-to-Requires-Contacts Transition):** A `job_posting` shall transition from `resume_review_pending` to `requires_contacts` when the agent review approves the tailoring output but the posting does not yet satisfy the `ready_for_outreach` conditions.
- **FR-SYS-17J (Review-to-Ready Transition):** A `job_posting` shall transition from `resume_review_pending` directly to `ready_for_outreach` when the agent review approves the tailoring output and the posting already satisfies the contact-linking and usable-email prerequisites for the intended outreach set.
- **FR-SYS-17K (Requires-Contacts-to-Ready Transition):** A `job_posting` shall transition from `requires_contacts` to `ready_for_outreach` when the required linked contacts exist and the intended current outreach set has discovered usable email addresses.
- **FR-SYS-17L (Ready-to-Outreach-In-Progress Transition):** A `job_posting` shall transition from `ready_for_outreach` to `outreach_in_progress` when the first contact in the intended current outreach set enters drafting or sending.
- **FR-SYS-17M (Outreach-In-Progress-to-Completed Transition):** A `job_posting` shall transition from `outreach_in_progress` to `completed` when no untouched automatically eligible contacts remain for that posting after the current shortlisted contact pool, repeat-contact exclusions, and automatic discovery outcomes have been applied.
- **FR-SYS-17N (Abandon Transition):** A `job_posting` may transition to `abandoned` from any non-terminal active status when the user explicitly decides to stop pursuing that posting.
- **FR-SYS-17N1 (Manual Review Close Transition):** A `job_posting` may transition to `closed_by_user` when the user explicitly closes an unresolved escalated review item from expert review rather than leaving the posting in unresolved backlog.
- **FR-SYS-17N2 (Manual Review Close Eligibility and Audit Rule):** Manual review close shall be allowed only for unresolved `job_postings` backed by an `escalated` `pipeline_run` and an `expert_review_packet` whose `packet_status` is either `pending_expert_review` or `reviewed`. The close action shall require a non-empty expert comment, shall record an expert-review decision and an override event, shall move the posting to `closed_by_user`, and shall remove the item from normal pending-attention queues while keeping it queryable in history.
- **FR-SYS-18 (Dedicated Posting-Contact Link Table):** The many-to-many relationship between `job_postings` and `contacts` shall be represented through a dedicated linking table, `job_posting_contacts`, rather than only through direct foreign-key fields on one side.
- **FR-SYS-19 (Relationship-Specific Link Records):** `job_posting_contacts` shall be allowed to store relationship-specific context for a given posting-contact pair rather than acting as a pure two-column join table only.
- **FR-SYS-20 (Minimum Link-Table Fields):** For this build, `job_posting_contacts` should at minimum support:
  1. `job_posting_id`
  2. `contact_id`
  3. `recipient_type`
  4. `relevance_reason`
  5. link-level status
- **FR-SYS-21 (Recipient Type Categories):** For this build, `recipient_type` should support at least:
  1. `hiring_manager`
  2. `recruiter`
  3. `engineer`
  4. `alumni`
  5. `founder`
  6. `other_internal`
- **FR-SYS-22 (Free-Text Relevance Reason):** For this build, `relevance_reason` may be stored as free text rather than a tightly controlled category set.
- **FR-SYS-23 (Link-Level Status Meaning):** `job_posting_contacts` link-level status shall represent the state of that contact in the context of that specific job posting, rather than duplicating the contact's global state across the whole system.
- **FR-SYS-23A (Link-Level Status Set):** For this build, `job_posting_contacts.link_level_status` should support a lightweight set such as:
  1. `identified`
  2. `shortlisted`
  3. `outreach_in_progress`
  4. `outreach_done`
  5. `exhausted`
  These values are meant to summarize the posting-specific relationship at a high level. Detailed discovery, draft/send, and delivery state shall remain in their own component records.
- **FR-SYS-23B (Single Link Row Per Pair):** For this build, `job_posting_contacts` shall keep a single canonical row per unique (`job_posting_id`, `contact_id`) pair. Time-based or event-based history for that relationship shall remain in the linked component records such as discovery attempts, outreach messages, and delivery-feedback events rather than being represented through multiple link rows for the same pair.
- **FR-SYS-23C (Link Identified-to-Shortlisted Transition):** A `job_posting_contacts` record shall transition from `identified` to `shortlisted` when that contact is selected into the intended outreach set for that posting.
- **FR-SYS-23D (Link Shortlisted-to-Outreach-In-Progress Transition):** A `job_posting_contacts` record shall transition from `shortlisted` to `outreach_in_progress` when discovery, drafting, or sending begins for that posting-contact pair in the current outreach flow.
- **FR-SYS-23E (Link Outreach-In-Progress-to-Done Transition):** A `job_posting_contacts` record shall transition from `outreach_in_progress` to `outreach_done` when the intended outreach for that posting-contact pair has been sent or otherwise completed for the current run.
- **FR-SYS-23F (Link-to-Exhausted Transition):** A `job_posting_contacts` record may transition to `exhausted` from any active non-terminal link state when no further automatic action remains for that posting-contact pair in the current flow.
- **FR-SYS-23G (Forward-Only Default State Progression):** For this build, top-level status transitions for `job_postings`, `contacts`, and `job_posting_contacts` should move forward by default rather than automatically regressing to earlier stages. Moving a record back to an earlier lifecycle state should require explicit user action, a deliberate reset path, or a clearly defined future exception.
- **FR-SYS-24 (Company Field Simplicity Rule):** For this build, company information should remain as a field inside `job_postings` and `contacts` rather than being modeled as a separate first-class `companies` entity. A dedicated `companies` entity may be introduced later only if cross-company normalization or richer company-level workflows become necessary.
- **FR-SYS-24A (Company-Entity Promotion Trigger Rule):** A first-class `companies` entity shall not be introduced unless at least two of the following become required simultaneously:
  1. reusable company-level memory or policy across multiple postings
  2. company-level discovery or delivery learning that must be queried independently of individual postings
  3. stronger company normalization and domain/link resolution than field-based storage can support cleanly
  4. company-level review, reporting, or control surfaces that materially exceed simple field grouping
  Until those triggers are present, `company` remains a field-level concept in the canonical schema.
- **FR-SYS-25 (Artifact Metadata in Central DB):** The central database should persist metadata and references for generated file artifacts, such as artifact type, file path, linked `job_posting_id` and/or `contact_id`, and creation timestamp, so the system can query what artifacts exist without relying on directory inspection alone.
- **FR-SYS-25A (Shared Artifact Records Table):** The central database shall include a shared `artifact_records` table to store artifact metadata across components. For this build, this table should at minimum support an artifact identifier, artifact type, file path, linked `job_posting_id` and/or `contact_id`, and creation timestamp.
- **FR-SYS-25B (Canonical Lead Raw Artifact Metadata Rule):** For `LinkedIn Scraping`, `artifact_records` shall track the canonical raw-source artifact as `lead_raw_source`.
- **FR-SYS-25C (Lead Review Artifact Metadata Rule):** For `LinkedIn Scraping`, `artifact_records` shall also track the derived split metadata artifact (`lead_split_metadata`), the split-review artifact (`lead_split_review`), and the lead handoff manifest (`lead_manifest`) so the current upstream interpretation can be queried without manual directory spelunking.
- **FR-SYS-26 (Artifact Content Boundary):** The central database shall store artifact metadata and references, not the full contents of generated runtime files by default. The file system remains the primary home for artifact content itself.
- **FR-SYS-27 (Stable Job Posting Identifier):** Each `job_posting` shall have its own stable internal identifier, such as `job_posting_id`, rather than relying on company name, role title, or file paths as the primary linkage key.
- **FR-SYS-28 (Job Posting Identity Key):** `job_postings` should also support a normalized deduplication identity key in addition to `job_posting_id`, so the system can recognize likely duplicate postings that arrive from different sources or at different times.
- **FR-SYS-29 (Conservative Job Posting Merge Rule):** The system shall merge a new posting into an existing `job_posting` record only when identity matching is confident. If the match is ambiguous, the system shall create a new posting record rather than risk an incorrect automatic merge.
- **FR-SYS-30 (Major State-Transition Audit Trail):** The central database should preserve a lightweight audit trail of major state transitions, such as changes to `job_postings` status, `contacts` status, and `job_posting_contacts` link-level status, so major lifecycle changes remain traceable over time.
- **FR-SYS-31 (Retention-First Deletion Policy):** The system shall not hard-delete operational records by default. When records need to be retired from active use, the preferred build behavior is to represent that through status changes, archival-style markers, or other reversible state transitions rather than destructive deletion.
- **FR-SYS-32 (Minimum Job Posting Canonical Fields):** For this build, `job_postings` should at minimum support these canonical fields:
  1. `job_posting_id`
  2. `lead_id`
  3. normalized posting identity key
  4. company name
  5. role title
  6. posting-level status
- **FR-SYS-33 (Minimum Contact Canonical Fields):** For this build, `contacts` should at minimum support these canonical fields:
  1. `contact_id`
  2. `identity_key`
  3. `display_name`
  4. company name
  5. `linkedin_url` when available
  6. contact-level status
  7. current working email when known
- **FR-SYS-34 (Primary Entity Timestamps):** `job_postings` and `contacts` should each include lightweight lifecycle timestamps such as `created_at` and `updated_at`.
- **FR-SYS-35 (Link-Record Timestamps):** `job_posting_contacts` should also include lightweight timestamps such as `created_at` and `updated_at` so relationship creation and later changes remain traceable.
- **FR-SYS-36 (Minimum Required Supporting Tables):** Beyond the primary entities, the posting-contact link table, and the discovery-specific tables defined elsewhere in this specification, this build should minimally include these additional supporting tables in `job_hunt_copilot.db`:
  1. `resume_tailoring_runs`
  2. `artifact_records`
  3. `state_transition_events`
  4. `override_events`
  5. `feedback_sync_runs`
  6. `outreach_messages`
  7. `delivery_feedback_events`
  8. `pipeline_runs`
  9. `supervisor_cycles`
  10. `agent_control_state`
  11. `agent_runtime_leases`
  12. `agent_incidents`
  13. `expert_review_packets`
  14. `expert_review_decisions`
- **FR-SYS-37 (Lean Supporting-Table Rule):** This build should prefer this minimal supporting-table set rather than introducing separate per-component tables unless a clear new requirement appears. Shared needs such as artifact metadata should use shared tables where possible instead of multiplying narrowly scoped tables.
- **FR-SYS-38 (Primary Orchestration Sequence):** The primary role-targeted workflow shall run in this dependency order: LinkedIn Scraping -> eligibility/tailoring -> mandatory agent review of the tailored output -> company-scoped contact search and/or contact linking or contact reuse -> selected-contact enrichment and recipient-profile extraction -> email discovery for contacts still missing usable emails -> drafting/sending -> delivery feedback.
- **FR-SYS-38A (General Learning Outreach Path):** When outreach is not tied to a specific job posting, the system may run a lighter contact-rooted flow: identify contact -> discover email if needed -> generate/send learning-first outreach -> capture delivery feedback. This path does not require posting-specific resume tailoring or the role-targeted agent review gate.
- **FR-SYS-38A1 (Role-Targeted Company-Scoped Contact Search):** When a role-targeted posting lacks enough explicit internal contacts from the lead itself, the system shall be able to run company-scoped people search using company, role, and JD-linked filters to identify likely recipients before person-scoped email discovery begins.
- **FR-SYS-38A1B (Location-Relaxation Retry Rule):** When a location-filtered company-scoped people search returns no useful candidates, the system shall be able to retry the same search with the location constraint relaxed rather than treating the location miss as final.
- **FR-SYS-38A2 (Apollo-First People Search):** For the first implementation of company-scoped people search, Apollo shall be the primary provider.
- **FR-SYS-38A3 (People-Search Materialization Rule):** Company-scoped people-search results shall persist a runtime search artifact for the full broad-search result. Canonical `contacts` and `job_posting_contacts` shall be created or updated only when a candidate has been selected into the shortlist for enrichment or later outreach handling. Broad-search candidates that are not shortlisted may remain artifact-only search results.
- **FR-SYS-38A3B (Saved Broad-Search Replay Rule):** When a posting still has saved broad-search results, the system may later replay that saved result to materialize additional shortlisted contacts up to the current shortlist limit without rerunning the external people-search request immediately.
- **FR-SYS-38A3A (Shortlist Dead-End Cleanup Rule):** If a shortlisted candidate is materialized into canonical `contacts` / `job_posting_contacts` for enrichment but later proves unusable at the enrichment boundary and will not continue into email discovery or outreach, that candidate shall be dropped from the current posting's canonical shortlist state. The broad-search artifact shall remain as the historical record of the candidate having been seen.
- **FR-SYS-38A4 (Email-Less People-Search Continuation):** If people search returns a useful contact record without a usable work email, that contact may continue into the person-scoped email-discovery path rather than being discarded.
- **FR-SYS-38A5 (Autonomous High-Recall Contact Search):** In the autonomous role-targeted mode, company-scoped people search should initially favor broad capture of relevant internal people before later filtering, ranking, or pacing decisions narrow the active send slice.
- **FR-SYS-38A6 (Relevant-People Search Classes):** The first autonomous people-search pass should look for engineering managers, software engineers, recruiters, and other internal employees who may plausibly help route the candidate to the right person.
- **FR-SYS-38B (Priority-Wave Outreach Rule):** For role-targeted outreach, the system shall proceed in priority waves rather than contacting every linked contact across all recipient types at once. Higher-priority recipient groups shall be attempted before lower-priority groups.
- **FR-SYS-38B1 (Recipient-Type Wave Order):** For this build, the default role-targeted outreach wave order should be:
  1. `recruiter`
  2. `hiring_manager`
  3. `engineer`
  4. `alumni`
  5. `other_internal`
- **FR-SYS-38B1A (Current Guide Recipient Groups):** The current outreach guide should explicitly cover these working recipient groups: recruiting managers who post openings on LinkedIn, people who may be working on that team or adjacent area, ASU alumni connections, and previous job connections.
- **FR-SYS-38B1B (Current Guide Focus Profiles):** The current deepest drafting guidance is optimized first for recruiting-manager posters and team-adjacent engineers. Alumni and previous-job-connection outreach remain supported, but their more detailed playbooks may stay lighter until later refinement.
- **FR-SYS-38B1C (Autonomous Enrichment Shortlist Size):** In the autonomous role-targeted flow, the first shortlist taken from the broad people-search result should contain at most 30 contacts for enrichment unless the user explicitly overrides that limit.
- **FR-SYS-38B1D (Autonomous Shortlist Composition):** The autonomous enrichment shortlist should aim for role coverage in this order:
  1. up to 2 recruiter or recruiting-manager-adjacent contacts
  2. up to 2 hiring-manager, engineering-manager, or engineering-director contacts
  3. up to 2 senior, lead, staff, or otherwise team-adjacent engineers
  If a bucket has too few candidates, the remaining slots may be filled by the next-best available helpful internal contacts.
- **FR-SYS-38B1E (Current Autonomous Active Send-Slice Size):** After enrichment and any required email discovery, the current active automatic send slice for one posting should contain at most 3 contacts unless the user explicitly overrides that limit.
- **FR-SYS-38B1F (Current Autonomous Active Send-Slice Composition):** The default autonomous active send slice should prefer one recruiter, one hiring-manager-or-manager-adjacent contact, and one team-adjacent engineer when those contact classes are available. If one class is unavailable, the next-best shortlisted contact may fill the slot.
- **FR-SYS-38B2 (Pacing-Aware Wave Progression):** Priority waves define outreach order, but send execution shall still respect the active pacing rules. A later recipient wave may therefore continue in a later send window rather than blasting every wave immediately.
- **FR-SYS-38B3 (Per-Posting Daily Send Cap):** In the autonomous role-targeted flow, the system shall not send more than 4 emails for the same posting within the same calendar day unless the user explicitly overrides that cap.
- **FR-SYS-38B3A (No Global Daily Send Cap):** In this build, the autonomous role-targeted flow does not need a separate cross-company daily send cap. The active pacing rules are a global randomized inter-send gap plus the per-posting daily cap rather than one overall global daily-send ceiling.
- **FR-SYS-38B3B (Quota-Blocked Send Yield Rule):** If a posting's current send work is blocked only by the per-posting daily cap or the next eligible paced-send time, that delayed-only sending run shall yield to other runnable supervisor work rather than monopolizing heartbeat selection.
- **FR-SYS-38B4 (Global Inter-Send Gap Rule):** Between any two automatically sent outreach emails, the system shall enforce a randomized pacing gap of 6 to 10 minutes rather than using a fixed cadence.
- **FR-SYS-38C (Sequential Interactive Execution Rule):** In this build, the interactive discovery, drafting, and sending stages shall run sequentially rather than as parallel fan-out. Delivery Feedback for already-sent messages may still begin immediately per message, and delayed background feedback sync may continue independently of the interactive send flow.
- **FR-SYS-38C1 (No Concurrency Tuning Requirement):** Because this build is intentionally sequential, the specification does not require configurable concurrency settings for discovery, drafting, sending, or scheduled feedback sync.
- **FR-SYS-38D (Feedback Observation Timing):** Delivery Feedback shall evaluate sent outreach using a 30-minute bounce-observation window from `sent_at`. This timing is intended to capture the normal delivery-failure emails that arrive shortly after send without requiring the original interactive send session to remain open.
- **FR-SYS-38D1 (Immediate Post-Send Feedback Poll):** After an interactive send run, the system should perform one immediate mailbox-feedback poll to capture bounce signals that arrive almost immediately after send completion.
- **FR-SYS-38D2 (Delayed Background Feedback Sync):** Delivery Feedback shall continue beyond the immediate post-send poll through a delayed background feedback-sync process that is independent of the interactive copilot session.
- **FR-SYS-38D2A (Dedicated Delayed-Poll Ownership Rule):** The separate feedback-sync worker owns delayed mailbox polling and persistence of mailbox-observed feedback signals for already-sent outreach.
- **FR-SYS-38D2B (Supervisor Feedback-State Consumption Rule):** The supervisor shall read persisted delivery-feedback state and event history to decide whether a `delivery_feedback` run stays pending or completes. It shall not perform delayed mailbox polling inline as part of ordinary role-targeted progression.
- **FR-SYS-38D2C (Non-Blocking Dormant Delivery-Feedback Rule):** A role-targeted `delivery_feedback` run that has no pending high-level feedback outcomes and no send frontier actionable now shall not monopolize heartbeat selection. The supervisor shall yield to other due work, including eligible new-posting bootstrap, and revisit that `delivery_feedback` run later when feedback or sending becomes due.
- **FR-SYS-38D3 (Current Scheduler Choice - launchd):** In the current single-user macOS deployment, the delayed feedback-sync process should be scheduled by `launchd`.
- **FR-SYS-38D4 (Scheduler-Independent Core Logic):** The feedback-detection logic shall live in reusable Delivery Feedback sync logic or commands. `launchd` is responsible only for periodic invocation.
- **FR-SYS-38D5 (Background Feedback Scope Rule):** Each delayed feedback-sync run should inspect sent outreach that is still within the active 30-minute bounce-observation window and should also remain able to ingest later reply signals tied to already-sent outreach threads when such mailbox evidence arrives.
- **FR-SYS-38D6 (Mailbox Signal Matching Rule):** The delayed feedback-sync process should read inbound mailbox feedback signals, such as bounce emails and replies, and match them back to internal `outreach_message_id` records using preserved send metadata such as recipient email, thread ID, provider message ID, or equivalent linkage fields when available.
- **FR-SYS-38D7 (Session-Independent Feedback Continuity):** Delayed feedback capture shall not require the interactive chat session or the original send process to remain running. Once send metadata has been persisted, later feedback detection should be able to proceed independently.
- **FR-SYS-38D8 (Current Scheduled Polling Interval):** During the active 30-minute bounce-observation window, the delayed feedback-sync process should run every 5 minutes.
- **FR-SYS-38D9 (Current Bounce-Observation Completion Rule):** If no bounce signal is detected for a sent message by the end of the 30-minute bounce-observation window, the system may record the current high-level outcome as `not_bounced` for that observation window while still allowing later reply detection to continue through mailbox observation.
- **FR-SYS-38E (Automatic Continuation Across Remaining Shortlisted Contacts):** After one daily send slice or current send slice has been evaluated for a posting, the system shall continue automatic enrichment, email discovery, draft generation, and later-day sending across the remaining untouched shortlisted contacts for that posting until the automatically eligible contact pool has been exhausted. Only actual send execution remains gated by pacing and the per-posting daily cap.
- **FR-SYS-38E1 (Saved-Broad-Result Backfill Is Allowed):** Automatic continuation across the remaining contact pool does not by itself require rerunning broad external company-scoped people search. However, when a saved broad-search artifact already exists, the system may automatically rematerialize or backfill additional shortlisted contacts from that saved result up to the current shortlist limit.
- **FR-SYS-38F (Reply Does Not Retroactively Cancel Active Wave):** Because replies may arrive later than send time, a reply from one contact shall not retroactively cancel outreach already issued to other contacts in the same active wave.
- **FR-SYS-38G (Single-Contact Failure Does Not Stall Wave):** If discovery, drafting, or sending fails for one contact within an active wave, the remaining independent contacts in that wave may continue through the pipeline as long as their own prerequisites are satisfied.
- **FR-SYS-38H (Known-Working-Email Shortcut):** If a contact in the active outreach flow already has a known working email and the identity match is clear, that contact may skip fresh discovery and count as discovery-ready immediately for the current posting frontier. Draft generation may proceed for that contact once the posting-level prerequisites are satisfied, while actual sending still follows the active send-slice, pacing, and daily-cap rules.
- **FR-SYS-38I (Prior-Outreach Review Gate):** If a contact already has prior outreach history, the system shall not automatically send a new outreach message to that contact in a later run. It shall skip automatic repeat outreach and surface the contact to the user for review.
- **FR-SYS-38I1 (Same-Company Multi-Posting Automatic Exclusion):** If a canonical contact has already received automatic role-targeted outreach for one posting at a canonical company, later postings at that same company shall proactively exclude that contact from automatic send-set selection rather than waiting until final send time to block the repeat touch.
- **FR-SYS-38I2 (Same-Company Alternate-Contact Search Rule):** When same-company repeat-contact exclusion removes a candidate from a later posting, orchestration shall continue searching, enriching, discovering, drafting, and later sending against the posting's remaining eligible company contacts when they exist.
- **FR-SYS-38I3 (Same-Company Repeat-Contact Review Rule):** If a later posting at the same company has no alternate automatically eligible contacts after same-company repeat-contact exclusions are applied, the system shall surface the posting for review rather than auto-sending a second role-targeted email to the already-contacted person.
- **FR-SYS-38I4 (Sent-Only Same-Company Trigger Rule):** Same-company repeat-contact exclusion is triggered only after an actual automatic outreach send has succeeded for that canonical contact. Generated or in-progress drafts alone shall not block the same contact across later postings.
- **FR-SYS-38I5 (Silent Same-Company Skip Rule):** If a later posting at the same company still has alternate automatically eligible contacts, already-emailed same-company contacts shall be silently skipped rather than surfaced as repeat-outreach review items for that later posting.
- **FR-SYS-38I6 (Same-Company Shortlist Refill Rule):** When same-company repeat-contact exclusions reduce the active shortlist below the current shortlist limit and a saved broad-search artifact exists, the system shall automatically backfill replacement candidates from that saved broad-search result until the shortlist limit is reached or the saved candidate pool is exhausted.
- **FR-SYS-39 (Dependency-Gated Execution):** A downstream stage shall not proceed until its required upstream stage has produced the required status and handoff data. Components may assume persisted upstream outputs exist rather than recomputing missing prerequisites on the fly.
- **FR-SYS-40 (Agent Review as Outreach Gate):** In the current role-targeted flow, Outreach-side work shall not begin until the linked `job_posting` has completed tailoring/finalize successfully and the active tailoring run is marked `resume_review_status = approved` by the mandatory agent review step.
- **FR-SYS-41 (Posting-Contact Linking Before Per-Contact Progression):** In a role-targeted flow, broad company-scoped people search may run before canonical posting-contact links exist. However, before person-scoped email discovery, drafting, or sending begins for a specific shortlisted contact, the system shall establish the relevant posting-contact relationship in `job_posting_contacts`.
- **FR-SYS-41A (Per-Contact Discovery Start Rule):** For role-targeted outreach, discovery may begin for a contact only after that contact has been linked to the posting, the posting has cleared the agent review gate, and the contact's own prerequisites are satisfied. The system does not need to wait until the full intended contact set for the posting has been linked before beginning discovery work for already-linked contacts after the review gate is cleared.
- **FR-SYS-41B (Posting-Frontier Drafting and Send Progression Rule):** In the current role-targeted flow, drafting does not need to wait for one fixed three-contact send set to become fully ready. Instead, once the posting-level prerequisites are satisfied, the system may generate drafts across all currently ready untouched automatic contacts for that posting. Actual sending remains governed separately by the active send-slice selection, the per-posting daily cap, and the inter-send pacing rules.
- **FR-SYS-42 (Artifact + State Publication Rule):** Before a downstream component starts, the upstream component shall both:
  1. publish its runtime handoff artifact when that artifact is part of the flow
  2. update canonical state in `job_hunt_copilot.db`
  so downstream execution is grounded in both file-based handoff and canonical persisted state.
- **FR-SYS-43 (Tailoring-to-Outreach Minimum Handoff):** The minimum handoff from Resume Tailoring into Outreach shall make available, either directly or through artifact references:
  1. `job_posting_id`
  2. tailored resume artifact reference/path
  3. tailoring/finalize status
  4. readiness-for-outreach signal
  5. the canonical DB-backed posting state needed to bootstrap Outreach by `job_posting_id`
- **FR-SYS-44 (Discovery-to-Drafting Minimum Handoff):** The minimum handoff from Email Discovery into Email Drafting and Sending shall make available, either directly or through artifact references:
  1. `contact_id`
  2. optional `job_posting_id`
  3. discovery outcome
  4. discovered email or current working email when found
  5. provider/confidence metadata when available
  6. recipient-profile context or recipient-profile artifact reference when available
- **FR-SYS-45 (Drafting-to-Feedback Minimum Handoff):** The minimum handoff from Email Drafting and Sending into Delivery Feedback shall make available, either directly or through artifact references:
  1. `outreach_message_id`
  2. `contact_id`
  3. optional `job_posting_id`
  4. send timestamp
  5. delivery-tracking identifier or thread ID when available
- **FR-SYS-45A (Immediate Per-Message Feedback Start Rule):** Delivery Feedback may begin for each message immediately after that specific send succeeds. It does not need to wait for the rest of the current active send slice to finish sending before beginning bounce/reply observation for the already-sent message.
- **FR-SYS-46 (Structured Handoff Contract Rule):** Runtime handoff artifacts shall include stable machine-usable identifiers for the linked primary entities or message records so downstream steps do not have to infer identity only from filenames or free text.
- **FR-SYS-46A (Machine vs Human Handoff Format Rule):** Runtime handoff artifacts intended for machine-to-machine pipeline progression should use a structured format such as JSON or YAML. Human-readable review artifacts may use Markdown or other presentation-oriented formats, but they shall not be the only machine contract when downstream automation depends on them.
- **FR-SYS-46A1 (Shared Machine-Contract Envelope):** Machine-oriented runtime handoff artifacts should share a small common envelope so contracts are easier to inspect and evolve. For this build, that envelope should at minimum include:
  1. `contract_version`
  2. `produced_at`
  3. `producer_component`
- **FR-SYS-46A2 (Shared Contract Result Field):** Machine-oriented runtime handoff artifacts should also include a simple top-level `result` field so downstream stages can tell whether the producing step ended in `success`, `blocked`, or `failed` without inferring outcome only from missing payload fields or separate state queries.
- **FR-SYS-46A3 (Contract Result Semantics):** For this build, the shared contract `result` field should mean:
  1. `success`: the stage completed and produced a usable output for downstream progression
  2. `blocked`: the stage did not produce a usable downstream output because a prerequisite, gate, review condition, or required input is still unmet
  3. `failed`: the stage attempted execution but could not complete because of an error or unrecoverable problem
- **FR-SYS-46A4 (Shared Reason Fields):** When a machine-oriented runtime handoff artifact has `result = blocked` or `result = failed`, it should also include:
  1. `reason_code` for machine-readable handling
  2. `message` for human-readable explanation
- **FR-SYS-46A5 (Shared Root-Reference Rule):** Every machine-oriented runtime handoff artifact shall include the relevant stable identifiers that tie the artifact back to the root object(s) the flow started from. In practice, this means carrying the relevant combination of identifiers such as `job_posting_id`, `contact_id`, and `outreach_message_id` whenever those objects already exist for that stage, so downstream components can understand exactly what the artifact is tied to without guessing from filenames or free text.
- **FR-SYS-46B (Tailoring-to-Outreach Bootstrap Rule):** For this build, Resume Tailoring -> Outreach shall bootstrap primarily from canonical DB state keyed by `job_posting_id`. The tailored-workspace `meta.yaml` and referenced resume artifacts remain supporting references and audit surfaces, but they are not the primary bootstrap entrypoint for Outreach.
- **FR-SYS-46B0 (Tailoring-to-Outreach Start Condition):** For role-targeted Outreach, DB-first bootstrap by `job_posting_id` shall begin only when:
  1. the linked tailoring run has `resume_review_status = approved`
  2. the posting-level status is `requires_contacts`
  This is the explicit boundary state for starting people search and contact expansion in the current build.
- **FR-SYS-46B1 (Current Tailoring Input Boundary):** Resume Tailoring shall primarily consume posting-level canonical state plus the derived `jd.md` lead artifact. The canonical `raw/source.md` is retained for traceability and re-derivation, not as a required direct input to Tailoring.
- **FR-SYS-46B1A (LinkedIn-to-Tailoring Bootstrap Rule):** In the role-targeted flow, Resume Tailoring shall bootstrap from `lead-manifest.yaml` plus canonical DB state. Concretely, Tailoring shall read the lead handoff manifest, require `handoff_targets.resume_tailoring.ready = true`, read the referenced `artifacts.jd_path`, read the linked `created_entities.job_posting_id` when present, and then mirror that JD and posting-linked context into the tailoring workspace before JD-signal extraction or other structuring begins.
- **FR-SYS-46B2 (Current Optional Tailoring Context Files):** Derived lead artifacts such as `post.md` and `poster-profile.md` may be mirrored into the tailoring workspace for traceability or future use, but they are not required inputs for the core JD-signal extraction and evidence-mapping logic.
- **FR-SYS-46C (Discovery-to-Drafting Handoff Artifact):** For this build, the primary Discovery-to-Drafting runtime handoff artifact shall be `discovery_result.json`. At minimum, it should expose `contact_id`, optional `job_posting_id`, discovery outcome, discovered/working email when found, provider/confidence metadata when available, and a recipient-profile artifact reference when such context has been extracted.
- **FR-SYS-46D (Human-Readable Draft Artifact Role):** For this build, `email_draft.md` may be produced as a human-readable draft artifact for inspection, audit, or later reference, but it shall not be treated as the sole machine contract for downstream delivery tracking.
- **FR-SYS-46E (Drafting-to-Feedback Handoff Artifact):** For this build, the primary Drafting-and-Sending-to-Delivery-Feedback runtime handoff artifact shall be `send_result.json`. At minimum, it should expose `outreach_message_id`, `contact_id`, optional `job_posting_id`, send timestamp, delivery-tracking identifier or thread ID when available, and send status.
- **FR-SYS-46F (Feedback Handoff Artifact):** For this build, the primary Delivery-Feedback runtime handoff artifact shall be `delivery_outcome.json`. At minimum, it should expose `outreach_message_id`, `contact_id`, optional `job_posting_id`, delivery state/event type, event timestamp, and reply summary/context when available.
- **FR-SYS-47 (Failure Persistence and Blocking):** When a stage fails or becomes blocked, the system shall persist the failure/block reason in canonical state and shall prevent dependent downstream stages from silently proceeding as though the upstream stage succeeded.
- **FR-SYS-48 (Retry and Resume Rule):** The system shall support retry/resume from the last successfully persisted stage boundary rather than requiring the entire pipeline to restart from `LinkedIn Scraping` after every partial failure.
- **FR-SYS-49 (Failure Isolation Rule):** Failures should be isolated as narrowly as possible. For example, one contact's discovery or outreach failure should not invalidate unrelated contacts for the same posting, while a failed resume-tailoring or agent-review stage may block only the posting-dependent outreach that relies on that tailored resume.
- **FR-SYS-49A (Stage Success Completeness Rule):** A stage shall not be considered truly successful until it has both:
  1. updated canonical state in `job_hunt_copilot.db`
  2. published any required runtime handoff artifact for downstream use
  If either part is missing, the stage shall not be treated as complete.
- **FR-SYS-49B (Canonical State Write Failure Rule):** If a stage completes its internal work but cannot persist the required canonical state update, that stage shall be treated as `failed` for orchestration purposes and downstream stages shall remain blocked from proceeding.
- **FR-SYS-49C (Required Artifact Publication Failure Rule):** If a stage is expected to publish a required handoff artifact and that artifact is not produced successfully, the stage shall be treated as `failed` for downstream progression even if some internal work was completed.
- **FR-SYS-49D (Smallest-Unit Retry Rule):** Automatic retry should occur at the smallest safe unit of work rather than rerunning large unrelated portions of the pipeline. In practice:
  1. Resume Tailoring retries are posting-scoped
  2. Discovery and draft-generation retries are contact-scoped
  3. Delivery-feedback ingestion retries are sent-message scoped
- **FR-SYS-49E (Discovery Exhaustion Handling):** When the allowed automatic discovery path for a contact is exhausted without yielding a usable working email, the system shall stop automatic discovery for that contact in the current run, persist the exhausted outcome, and surface the contact for later review rather than looping indefinitely.
- **FR-SYS-49F (Draft Generation Retry Handling):** If draft generation fails due to a transient or execution-level problem, the system may retry draft generation for the same contact a limited number of times. If those automatic retries do not resolve the issue, the case shall be surfaced for user review rather than silently skipped.
- **FR-SYS-49F1 (Partial Frontier Continuation Rule):** If draft generation fails for one contact in the current ready posting frontier, the whole frontier does not need to stop. Successfully generated drafts in that same frontier may still proceed into sending, while the failed draft case is surfaced separately for review.
- **FR-SYS-49G (Safe Send Retry Rule):** Automatic resend shall only occur when the system can determine that no successful send has already occurred for that message/contact context. If send outcome is ambiguous, the system shall not guess by resending automatically and shall instead surface the case for review.
- **FR-SYS-49H (No Silent Duplicate-Send Rule):** The system shall prefer under-sending to duplicate-sending when send state is unclear. Avoiding accidental duplicate outreach is more important than aggressively auto-retrying a possibly completed send.
- **FR-SYS-49I (Feedback Delay Is Not Failure):** The absence of an immediate bounce or reply after send shall not be treated as a pipeline failure. Delivery-feedback observation may lag behind send time, and the message may remain in a sent/awaiting-feedback state until later delivery evidence arrives.
- **FR-SYS-49J (Retry Auditability Rule):** Automatic retries, retry exhaustion, and final retry outcomes should be persisted in a queryable form so later review can show what the system attempted before surfacing or stopping.
- **FR-SYS-49K (Idempotent Feedback Ingestion Rule):** Delivery-feedback ingestion should behave idempotently for the same sent-message instance, so retrying feedback capture does not create misleading duplicate logical outcomes in canonical history.
- **FR-SYS-50 (Control Layer):** This build shall distinguish between:
  1. mandatory agent-reviewed control points
  2. review-only informational surfaces
  3. explicit override paths
  so automation can proceed by default without losing clear owner control over risk-sensitive cases.
- **FR-SYS-51 (No Mandatory Human Gate in Primary Flow):** For this build, the main role-targeted flow has no mandatory human pause. Mandatory review gates are performed by the AI agent. The owner may still inspect or override outcomes, but autonomous progression does not wait for manual approval by default.
- **FR-SYS-52 (Review-Only Surfaces):** Review-oriented surfaces such as bounced-email review, unresolved-contact review, and later sent-email inspection are informational by default and do not automatically block the broader pipeline unless another rule explicitly makes them blocking.
- **FR-SYS-53 (Explicit Override Authority):** The primary user/owner may explicitly override system decisions where the specification allows override, but the system shall not assume implicit approval from silence or from mere visibility of a review surface.
- **FR-SYS-54 (Override Persistence Rule):** When an override is applied, the system shall persist:
  1. which object was overridden
  2. the affected component/stage
  3. the previous decision or state
  4. the override decision or new state
  5. `override_reason`
  6. `override_timestamp`
- **FR-SYS-55 (Override State Effect):** An override shall update canonical state and, when relevant, unblock or redirect downstream progression from that point onward. It does not require recomputing earlier completed stages unless the override explicitly demands a reset or rerun.
- **FR-SYS-56 (User-Review Escalation Cases):** In this build, the system should explicitly surface a case to the user for review instead of auto-continuing when:
  1. prior outreach history makes the correct next action ambiguous
  2. discovery exhausts the allowed automatic path for a contact
  3. a blocked or failed stage cannot be resolved through the current automatic retry rules
- **FR-SYS-57 (Autonomous Draft/Send Boundary):** Outside the mandatory agent review gates and explicit review-escalation cases, Email Drafting and Sending remains autonomous in this build and does not require pre-send human approval.
- **FR-SYS-58 (Observability and Review Layer):** The system shall provide lightweight observability and review surfaces so the owner can understand what the pipeline has done, what is currently waiting, what failed, and what needs manual attention without reconstructing the story from raw files alone.
- **FR-SYS-59 (Primary Status Query Surfaces):** The central database should support direct query/review of the primary entities and link records by current status, including:
  1. `linkedin_leads` by lead-level status or split-review status
  2. `job_postings` by posting-level status
  3. `contacts` by contact-level status
  4. `job_posting_contacts` by link-level status
- **FR-SYS-60 (Lead and Posting Review Queues):** The system should make it easy to list upstream `linkedin_leads` that are in operationally important states such as:
  1. `captured`
  2. `split_ready`
  3. `reviewed`
  4. blocked/ambiguous split-review cases
  5. `blocked_no_jd`
  and to list `job_postings` that are in downstream operationally important states such as:
  1. `resume_review_pending`
  2. `requires_contacts`
  3. `ready_for_outreach`
  4. `outreach_in_progress`
- **FR-SYS-61 (Contact-Level Review Queues):** For this build, the system should make it easy to list `contacts` that are in operationally important states such as:
  1. `discovery_in_progress`
  2. `working_email_found`
  3. `sent`
  4. `replied`
  5. `exhausted`
- **FR-SYS-62 (Escalation Review Queues):** In addition to normal status views, the system should provide focused review surfaces for the current explicit escalation cases, including:
  1. unresolved discovery cases
  2. bounced-email cases
  3. prior-outreach repeat-contact cases that require user review
  4. blocked/failed pipeline cases that could not auto-resolve
  5. terminal or otherwise review-worthy pipeline runs waiting for expert review
  6. open agent incidents and paused autonomous runs
- **FR-SYS-63 (Sent Outreach Inspection Surface):** The system should make sent outreach easy to inspect later by exposing queryable sent-message history, including the linked contact, optional linked posting, sent subject/body, send timestamp, and latest known delivery outcome when available.
- **FR-SYS-64 (Per-Object Traceability View):** For a given `job_posting`, `contact`, or `outreach_message`, the system should make it possible to trace the linked artifacts, major state transitions, and relevant downstream records so the owner can understand how that object moved through the pipeline.
- **FR-SYS-65 (Artifact Traceability from Review Surfaces):** Review surfaces should expose artifact references or paths when relevant so the owner can jump from canonical state into the corresponding human-readable or machine-readable artifacts for deeper inspection.
- **FR-SYS-66 (Review Surfaces Are Query-First):** In this build, review and observability surfaces do not require a dedicated GUI. Queryable database views, filtered retrieval paths, and artifact references are sufficient as long as they make the relevant cases inspectable without manual directory spelunking.
- **FR-SYS-67 (Chat-Based Review Operating Model):** In this build, the primary human-control and review experience may be conversational, with the AI agent acting as the operating interface for the copilot rather than requiring a separate GUI.
- **FR-SYS-67A (Chat-First Operating Interface):** In this build, the primary user-facing operating model may remain chat-first. The user can state intent conversationally, and the AI agent is responsible for interpreting that intent and carrying out the appropriate pipeline behavior while honoring the rules in this specification.
- **FR-SYS-67B (No Fixed User Command Contract Required):** The current specification does not require a fixed end-user command catalog. Concrete CLI commands, wrappers, or job entrypoints may exist in implementation, but their exact shape is an internal implementation detail rather than a required user-facing contract.
- **FR-SYS-68 (Review Queue Presentation Rule):** When the user indicates they are ready to review, the AI agent shall surface the currently relevant review items from the system's review queues, statuses, and linked artifacts rather than requiring the user to manually reconstruct what needs attention.
- **FR-SYS-69 (Mandatory Agent Review Behavior):** At a mandatory review gate, the AI agent shall pause downstream progression for that object, evaluate the relevant artifacts and canonical state against the stored review policy, record an explicit review outcome, and then continue, revise, retry, or escalate based on that outcome.
- **FR-SYS-70 (Override Interruption Rule):** If the user explicitly interrupts a currently active object or stage, the AI agent shall stop blind progression on that object, surface the current evidence and state, and then revise, rerun, override, or stop based on the user's instruction.
- **FR-SYS-71 (Review Rejection Handling Rule):** If a mandatory agent review finds an output unacceptable, or if the user or expert later rejects that output, the AI agent shall not blindly continue. It shall instead treat the case as unresolved and then revise, rerun, override, or stop based on the applicable escalation or override policy.
- **FR-SYS-71A (Supervisor Agent as Control Plane):** The current build shall include an `Operations / Supervisor Agent` control-plane component that keeps the autonomous workflow running, chooses the next safe action, validates outcomes, performs bounded repair, and prepares expert review packets.
- **FR-SYS-71B (Runtime Identity-Pack Rule):** The Supervisor Agent's runtime self-awareness shall come from generated compact identity and policy artifacts plus canonical state, not from repeatedly rereading the full PRD during normal operation.
- **FR-SYS-71C (Chat-Only Human Interface Rule):** The human expert's primary operating interface shall remain conversational. Internal CLIs or scripts may exist for implementation, but the user-facing operating model is chat-first.
- **FR-SYS-71D (Fresh-Context-Per-Cycle Rule):** Each supervisor heartbeat may construct a fresh LLM context. That context shall be reconstructed from durable state, selected work-unit evidence, and the runtime identity/policy pack rather than depending on the previous heartbeat's transient prompt state.
- **FR-SYS-71E (No Overlapping Supervisor Cycle Rule):** The control plane shall prevent overlapping supervisor cycles through an internal lease/lock mechanism. A new heartbeat shall not start a second active cycle while a valid prior lease remains active.
- **FR-SYS-71F (Pipeline-Run Persistence Rule):** Long-running posting-scoped work shall persist as canonical `pipeline_runs` that survive across many supervisor heartbeats. A fresh heartbeat resumes from canonical run state rather than assuming the previous LLM context still exists.
- **FR-SYS-71G (Continuous-Service-Goal Rule):** The Supervisor Agent shall optimize for continuous service behavior rather than one daily target batch. It shall keep due work moving, keep queues fresh, and persist explicit reasons whenever work cannot advance.
- **FR-SYS-71H (Post-Run Expert Review Packet Rule):** After each terminal or otherwise review-worthy end-to-end role-targeted pipeline run outcome, the Supervisor Agent shall generate a persisted expert review packet summarizing outcomes, misses, retries, incidents, and recommended expert actions.
- **FR-SYS-71I (Expert Review Is Supervisory by Default):** Expert review packets are mandatory outputs after terminal or otherwise review-worthy end-to-end run outcomes, but they do not automatically pause the entire autonomous system unless the expert explicitly issues a pause, stop, or override instruction.
- **FR-SYS-71J (Bounded Self-Repair Rule):** The Supervisor Agent may autonomously perform bounded operational repair such as retries, artifact regeneration, fallback-provider use, or small non-destructive fixes. Riskier behavioral changes, broad code changes, or unresolved repeated failures shall be escalated instead.
- **FR-SYS-71K (Pause-Resume-Stop Control Rule):** The Supervisor Agent shall honor persisted control state for `enabled`, `paused`, `stopped`, or equivalent operating modes so the expert can control autonomous execution conversationally without relying on an interactive shell session remaining open.

### 7.1.1 Next-Build Central DB Logical Schema

This section defines the next-build logical schema shape for `job_hunt_copilot.db`, with `LinkedIn Scraping` as the upstream root. The SQL DDL skeleton appears immediately below so the next build can implement against a concrete schema target.

#### Shared Schema Conventions
1. All primary identifiers should be stored as `TEXT`.
2. Status, type, and enum-like values should be stored as `TEXT`.
3. Timestamps should be stored as UTC ISO-8601 `TEXT`.
4. Optional structured metadata fields may be stored as JSON-encoded `TEXT` when a dedicated relational shape is not yet required.
5. Mutable tables should include `created_at` and `updated_at` unless the table is event-only and already has an authoritative event timestamp.

#### Primary Entity Tables

**`linkedin_leads`**
- Primary key:
  - `lead_id`
- Required columns:
  - `lead_id`
  - `lead_identity_key`
  - `lead_status`
  - `lead_shape`
  - `split_review_status`
  - `source_type`
  - `source_reference`
  - `source_mode`
  - `created_at`
  - `updated_at`
- Optional columns:
  - `source_url`
  - `company_name`
  - `role_title`
  - `location`
  - `work_mode`
  - `compensation_summary`
  - `poster_name`
  - `poster_title`
  - `last_scraped_at`
- Notes:
  - `lead_shape` should support at least `posting_only`, `posting_plus_contacts`, `contact_only`, and `invalid`.
  - `split_review_status` stores lead-level upstream review state such as `confident`, `needs_review`, or `ambiguous`.

**`job_postings`**
- Primary key:
  - `job_posting_id`
- Required columns:
  - `job_posting_id`
  - `lead_id`
  - `posting_identity_key`
  - `canonical_company_key`
  - `company_name`
  - `role_title`
  - `posting_status`
  - `created_at`
  - `updated_at`
- Optional columns:
  - `provider_company_key`
  - `company_key_source`
  - `location`
  - `employment_type`
  - `posted_at`
  - `jd_artifact_path`
  - `archived_at`
  - `application_state`
  - `applied_at`
  - `application_url`
  - `application_notes`
  - `application_updated_at`
- Notes:
  - `posting_identity_key` is the normalized dedupe key used for conservative posting matching.
  - `canonical_company_key` is the operational same-company grouping key used for multi-posting contact reuse and repeat-outreach exclusion.
  - `provider_company_key` may retain a stronger provider-backed company identifier such as Apollo `organization_id` when available.
  - `company_key_source` records whether the current grouping key came from provisional normalized-name derivation or a provider-backed resolution.
  - `posting_status` stores the posting-level lifecycle state such as `sourced`, `resume_review_pending`, `requires_contacts`, or `completed`.
  - `application_state` is separate owner-managed application tracking and does not drive the autonomous posting lifecycle.
  - `lead_id` points back to the originating upstream lead.

**`contacts`**
- Primary key:
  - `contact_id`
- Required columns:
  - `contact_id`
  - `identity_key`
  - `display_name`
  - `company_name`
  - `origin_component`
  - `contact_status`
  - `created_at`
  - `updated_at`
- Optional columns:
  - `full_name`
  - `first_name`
  - `last_name`
  - `linkedin_url`
  - `position_title`
  - `location`
  - `discovery_summary`
  - `current_working_email`
  - `identity_source`
  - `provider_name`
  - `provider_person_id`
  - `name_quality`
  - `responder_state`
  - `responded_at`
  - `responder_notes`
  - `responder_updated_at`
- Notes:
  - `display_name` is the best currently known human-readable name string for the contact and may initially be sparse or obfuscated when a people-search provider does not yet reveal the full name.
  - `full_name` should be populated only when the system has a non-obfuscated full name with enough confidence to treat it as person identity rather than a provider display artifact.
  - `identity_key` is the normalized person-lookup key and is not required to be globally unique because same-name ambiguity may still exist in name-based fallback cases.
  - `contact_status` stores the current top-level contact lifecycle state such as `identified`, `working_email_found`, `sent`, or `replied`.
  - `responder_state` is separate relationship metadata for reply-positive or warm contacts and does not replace `contact_status`.
  - Contacts auto-created from lead extraction should set `origin_component = linkedin_scraping`.

**`linkedin_lead_contacts`**
- Primary key:
  - `linkedin_lead_contact_id`
- Required columns:
  - `linkedin_lead_contact_id`
  - `lead_id`
  - `contact_id`
  - `contact_role`
  - `recipient_type_inferred`
  - `is_primary_poster`
  - `created_at`
  - `updated_at`
- Optional columns:
  - `extraction_confidence`
- Constraints:
  - unique (`lead_id`, `contact_id`)
- Notes:
  - This table preserves lead-to-contact extraction traceability even when a canonical contact is later reused elsewhere.

**`job_posting_contacts`**
- Primary key:
  - `job_posting_contact_id`
- Required columns:
  - `job_posting_contact_id`
  - `job_posting_id`
  - `contact_id`
  - `recipient_type`
  - `relevance_reason`
  - `link_level_status`
  - `created_at`
  - `updated_at`
- Constraints:
  - unique (`job_posting_id`, `contact_id`)
- Notes:
  - `recipient_type` stores values such as `hiring_manager`, `recruiter`, `engineer`, `alumni`, `founder`, or `other_internal`.
  - `link_level_status` stores the posting-specific relationship state such as `identified`, `shortlisted`, `outreach_in_progress`, `outreach_done`, or `exhausted`.

#### Supporting Operational Tables

**`resume_tailoring_runs`**
- Primary key:
  - `resume_tailoring_run_id`
- Required columns:
  - `resume_tailoring_run_id`
  - `job_posting_id`
  - `base_used`
  - `tailoring_status`
  - `resume_review_status`
  - `workspace_path`
  - `created_at`
  - `updated_at`
- Optional columns:
  - `meta_yaml_path`
  - `final_resume_path`
  - `verification_outcome`
  - `started_at`
  - `completed_at`
- Notes:
  - `tailoring_status` stores the run-level tailoring lifecycle using values such as `in_progress`, `needs_revision`, `tailored`, or `failed`.
  - `resume_review_status` stores the run-level review state using values such as `not_ready`, `resume_review_pending`, `approved`, or `rejected`.
  - A new run row should be created for a new tailoring attempt after a rejected review outcome rather than overwriting the prior run.

**`artifact_records`**
- Primary key:
  - `artifact_id`
- Required columns:
  - `artifact_id`
  - `artifact_type`
  - `file_path`
  - `producer_component`
  - `created_at`
- Optional linkage columns:
  - `lead_id`
  - `job_posting_id`
  - `contact_id`
  - `outreach_message_id`
- Constraint:
  - at least one linkage column should be populated so each artifact is tied to a real system object
- Notes:
  - For `LinkedIn Scraping`, the canonical raw-source artifact type is `lead_raw_source` and points to `linkedin-scraping/runtime/leads/<company>/<role>/<lead_id>/raw/source.md` when that lead mode materializes a raw-source artifact.
  - The next build should also emit `lead_split_metadata`, `lead_split_review`, and `lead_manifest` for upstream lead interpretation when those artifacts are applicable to the lead mode.

**`state_transition_events`**
- Primary key:
  - `state_transition_event_id`
- Required columns:
  - `state_transition_event_id`
  - `object_type`
  - `object_id`
  - `stage`
  - `previous_state`
  - `new_state`
  - `transition_timestamp`
- Optional columns:
  - `transition_reason`
  - `caused_by`
  - `lead_id`
  - `job_posting_id`
  - `contact_id`
- Notes:
  - This is the minimum audit table for major state changes referenced by the observability and audit requirements.

**`override_events`**
- Primary key:
  - `override_event_id`
- Required columns:
  - `override_event_id`
  - `object_type`
  - `object_id`
  - `component_stage`
  - `previous_value`
  - `new_value`
  - `override_reason`
  - `override_timestamp`
- Optional columns:
  - `override_by`
  - `lead_id`
  - `job_posting_id`
  - `contact_id`
- Notes:
  - This is the minimum audit table for explicit owner overrides.

**`feedback_sync_runs`**
- Primary key:
  - `feedback_sync_run_id`
- Required columns:
  - `feedback_sync_run_id`
  - `scheduler_name`
  - `scheduler_type`
  - `started_at`
  - `result`
- Optional columns:
  - `completed_at`
  - `observation_scope`
  - `messages_examined`
  - `bounce_events_written`
  - `reply_events_written`
  - `last_checkpoint`
  - `error_message`
- Notes:
  - This table provides auditability and health visibility for scheduled Delivery Feedback sync runs.
  - In the current local deployment, `scheduler_type` may be `launchd`.

**`pipeline_runs`**
- Primary key:
  - `pipeline_run_id`
- Required columns:
  - `pipeline_run_id`
  - `run_scope_type`
  - `run_status`
  - `current_stage`
  - `started_at`
  - `created_at`
  - `updated_at`
- Optional linkage columns:
  - `lead_id`
  - `job_posting_id`
- Optional operational columns:
  - `completed_at`
  - `last_error_summary`
  - `review_packet_status`
  - `run_summary`
- Notes:
  - In the current build, the primary `run_scope_type` is a posting-scoped role-targeted end-to-end run.
  - `run_status` should support values such as `in_progress`, `completed`, `failed`, `paused`, and `escalated`.
  - `run_scope_type` should support at least `role_targeted_posting` and `general_learning_contact`.
  - `current_stage` should support the major durable boundaries of the current flow, such as `lead_handoff`, `resume_tailoring`, `agent_review`, `people_search`, `enrichment`, `email_discovery`, `drafting`, `sending`, `feedback_started`, `completed`, and `failed`.
  - `review_packet_status` should support at least `not_ready`, `pending_expert_review`, `reviewed`, and `superseded`.
  - A terminal or otherwise review-worthy run should later link to an expert review packet rather than disappearing into raw logs.
  - An unresolved escalated run that is manually closed from expert review should become `completed` with `current_stage = completed` rather than staying open indefinitely.

**`supervisor_cycles`**
- Primary key:
  - `supervisor_cycle_id`
- Required columns:
  - `supervisor_cycle_id`
  - `trigger_type`
  - `started_at`
  - `result`
  - `created_at`
- Optional columns:
  - `scheduler_name`
  - `completed_at`
  - `selected_work_type`
  - `selected_work_id`
  - `pipeline_run_id`
  - `context_snapshot_path`
  - `sleep_wake_detection_method`
  - `sleep_wake_event_ref`
  - `error_summary`
- Notes:
  - One row represents one heartbeat invocation of the Supervisor Agent.
  - In the current local deployment, `trigger_type` may be `launchd_heartbeat`.
  - `result` should support at least `success`, `no_work`, `deferred`, `failed`, `auto_paused`, and `replanned`.

**`agent_control_state`**
- Primary key:
  - `control_key`
- Required columns:
  - `control_key`
  - `control_value`
  - `updated_at`
- Notes:
  - This table stores durable operator-visible control state such as `agent_enabled`, `agent_mode`, `pause_reason`, or similar runtime toggles.
  - The current build should at minimum persist keys such as `agent_enabled`, `agent_mode`, `pause_reason`, `paused_at`, `last_manual_command`, `last_replan_at`, `last_replan_reason`, `last_sleep_wake_check_at`, `last_seen_sleep_event_at`, `last_seen_wake_event_at`, `last_sleep_wake_event_ref`, and `active_chat_session_id`.
  - `agent_mode` should support at least `running`, `paused`, `stopped`, and `replanning`.

**`agent_runtime_leases`**
- Primary key:
  - `lease_name`
- Required columns:
  - `lease_name`
  - `lease_owner_id`
  - `acquired_at`
  - `expires_at`
- Optional columns:
  - `last_renewed_at`
  - `lease_note`
- Notes:
  - This table enforces single-flight execution for supervisor heartbeat cycles and other lease-guarded background work.
  - The current build should use at least a lease such as `supervisor_cycle`.

**`agent_incidents`**
- Primary key:
  - `agent_incident_id`
- Required columns:
  - `agent_incident_id`
  - `incident_type`
  - `severity`
  - `status`
  - `summary`
  - `created_at`
  - `updated_at`
- Optional linkage columns:
  - `pipeline_run_id`
  - `lead_id`
  - `job_posting_id`
  - `contact_id`
  - `outreach_message_id`
- Optional operational columns:
  - `resolved_at`
  - `escalation_reason`
  - `repair_attempt_summary`
- Notes:
  - This is the canonical store for failures or drift conditions that the Supervisor Agent could not safely resolve within bounded repair rules.
  - `severity` should support at least `low`, `medium`, `high`, and `critical`.
  - `status` should support at least `open`, `in_repair`, `escalated`, `resolved`, and `suppressed`.

**`expert_review_packets`**
- Primary key:
  - `expert_review_packet_id`
- Required columns:
  - `expert_review_packet_id`
  - `pipeline_run_id`
  - `packet_status`
  - `packet_path`
  - `created_at`
- Optional columns:
  - `job_posting_id`
  - `reviewed_at`
  - `summary_excerpt`
- Notes:
  - One packet is created after each terminal or otherwise review-worthy end-to-end role-targeted run outcome.
  - `packet_status` should support at least `pending_expert_review`, `reviewed`, and `superseded`.

**`expert_review_decisions`**
- Primary key:
  - `expert_review_decision_id`
- Required columns:
  - `expert_review_decision_id`
  - `expert_review_packet_id`
  - `decision_type`
  - `decided_at`
- Optional columns:
  - `decision_notes`
  - `applied_at`
  - `override_event_id`
- Notes:
  - This table stores expert course-correction decisions applied after reviewing a terminal or otherwise review-worthy run packet.
  - `decision_type` should support at least `approved`, `override_applied`, `course_correction`, `pause_requested`, `resume_allowed`, and `closed_by_user`.

**`maintenance_change_batches`**
- Primary key:
  - `maintenance_change_batch_id`
- Required columns:
  - `maintenance_change_batch_id`
  - `branch_name`
  - `scope_slug`
  - `status`
  - `approval_outcome`
  - `summary_path`
  - `json_path`
  - `created_at`
- Optional columns:
  - `head_commit_sha`
  - `merged_commit_sha`
  - `merge_commit_message`
  - `validated_at`
  - `approved_at`
  - `merged_at`
  - `failed_at`
  - `validation_summary`
  - `expert_review_packet_id`
- Notes:
  - This table is the canonical state store for autonomous maintenance change batches and their approval outcomes.
  - `status` should support at least `in_progress`, `validated`, `merged`, `failed`, and `retained_for_review`.
  - `approval_outcome` should support at least `pending`, `approved`, `not_approved`, and `failed_validation`.

#### Discovery Tables

**`windows`**
- Primary key:
  - `window_id`
- Required columns:
  - `window_id`
  - `window_start`
  - `window_end`
  - `status`

**`provider_budget_state`**
- Primary key:
  - `provider_name`
- Required columns:
  - `provider_name`
  - `updated_at`
- Optional columns:
  - `remaining_credits`
  - `credit_limit`
  - `reset_at`
- Notes:
  - `remaining_credits` may be `NULL` when the provider does not expose a trustworthy balance signal or the latest balance refresh failed.
  - `NULL` means unknown and must not be replaced with synthetic placeholder values.

**`provider_budget_events`**
- Primary key:
  - `provider_budget_event_id`
- Required columns:
  - `provider_budget_event_id`
  - `provider_name`
  - `event_type`
  - `credit_delta`
  - `created_at`
- Optional columns:
  - `remaining_credits_after`
  - `related_discovery_attempt_id`
  - `related_contact_id`

**`discovery_attempts`**
- Primary key:
  - `discovery_attempt_id`
- Required columns:
  - `discovery_attempt_id`
  - `contact_id`
  - `outcome`
  - `created_at`
- Optional linkage columns:
  - `job_posting_id`
  - `window_id`
- Optional discovery-result columns:
  - `provider_name`
  - `email`
  - `email_local_part`
  - `detected_pattern`
  - `provider_verification_status`
  - `provider_score`
  - `bounced`
- Optional identity/disambiguation snapshot columns:
  - `display_name`
  - `first_name`
  - `last_name`
  - `full_name`
  - `linkedin_url`
  - `position_title`
  - `location`
  - `provider_person_id`
  - `name_quality`
- Notes:
  - One row represents one completed cascade for one contact.
  - `outcome` should cover values such as `found` and `not_found`.

#### Outreach and Feedback Tables

**`outreach_messages`**
- Primary key:
  - `outreach_message_id`
- Required columns:
  - `outreach_message_id`
  - `contact_id`
  - `outreach_mode`
  - `recipient_email`
  - `message_status`
  - `created_at`
  - `updated_at`
- Optional linkage columns:
  - `job_posting_id`
  - `job_posting_contact_id`
- Optional content and delivery columns:
  - `subject`
  - `body_text`
  - `body_html`
  - `thread_id`
  - `delivery_tracking_id`
  - `sent_at`
- Notes:
  - `outreach_mode` should distinguish at least `role_targeted` and `general_learning`.
  - `message_status` is the current message-level lifecycle field for generated/sent outreach.

**`delivery_feedback_events`**
- Primary key:
  - `delivery_feedback_event_id`
- Required columns:
  - `delivery_feedback_event_id`
  - `outreach_message_id`
  - `event_state`
  - `event_timestamp`
- Optional denormalized linkage columns:
  - `contact_id`
  - `job_posting_id`
- Optional reply/detail columns:
  - `reply_summary`
  - `raw_reply_excerpt`
  - `created_at`
- Notes:
  - `event_state` should support the current high-level states `sent`, `bounced`, `not_bounced`, and `replied`.
  - Persisted `replied` events should also refresh the linked contact's responder metadata, setting `responder_state = replied` when the contact is not already `warm`.

#### Current Review Views

**`unresolved_contacts_review`**
- Should surface contacts whose current discovery path remains unresolved or exhausted without a usable working email.
- Should be derivable from `contacts` plus the latest relevant `discovery_attempts`.

**`bounced_email_review`**
- Should surface outreach messages or contacts with a bounced delivery outcome.
- Should be derivable from `delivery_feedback_events`, with join support from `outreach_messages` and `contacts`.

**`expert_review_queue`**
- Should surface terminal or otherwise review-worthy `pipeline_runs` whose `expert_review_packets.packet_status = pending_expert_review`.
- Should expose the linked packet path, the posting/run summary, and any linked incidents.

**`open_agent_incidents_review`**
- Should surface active `agent_incidents` in `open`, `escalated`, or equivalent unresolved states.
- Should be derivable from `agent_incidents`, with optional join support from `pipeline_runs`, `job_postings`, `contacts`, and `outreach_messages`.

#### Current Minimum Index Set
1. `job_postings`:
   - index on `posting_identity_key`
   - index on `posting_status`
2. `contacts`:
   - index on `identity_key`
   - index on `linkedin_url`
   - index on `contact_status`
   - index on `current_working_email`
3. `job_posting_contacts`:
   - unique index on (`job_posting_id`, `contact_id`)
   - index on `link_level_status`
   - index on `recipient_type`
4. `resume_tailoring_runs`:
   - index on `job_posting_id`
   - index on `resume_review_status`
5. `artifact_records`:
   - index on `artifact_type`
   - index on `job_posting_id`
   - index on `contact_id`
   - index on `outreach_message_id`
6. `state_transition_events`:
   - index on (`object_type`, `object_id`)
   - index on `transition_timestamp`
7. `override_events`:
   - index on (`object_type`, `object_id`)
   - index on `override_timestamp`
8. `feedback_sync_runs`:
   - index on `started_at`
   - index on `result`
   - index on `scheduler_name`
9. `pipeline_runs`:
   - index on `run_status`
   - index on `job_posting_id`
   - index on `current_stage`
10. `supervisor_cycles`:
   - index on `started_at`
   - index on `result`
   - index on `pipeline_run_id`
11. `agent_control_state`:
   - primary-key lookup on `control_key` is sufficient
12. `agent_runtime_leases`:
   - index on `expires_at`
13. `agent_incidents`:
   - index on `status`
   - index on `severity`
   - index on `pipeline_run_id`
14. `expert_review_packets`:
   - index on `packet_status`
   - index on `pipeline_run_id`
15. `expert_review_decisions`:
   - index on `expert_review_packet_id`
   - index on `decided_at`
16. `discovery_attempts`:
   - index on `contact_id`
   - index on `job_posting_id`
   - index on `outcome`
   - index on `created_at`
17. `provider_budget_events`:
   - index on `provider_name`
   - index on `created_at`
18. `outreach_messages`:
   - index on `contact_id`
   - index on `job_posting_id`
   - index on `message_status`
   - index on `sent_at`
19. `delivery_feedback_events`:
   - index on `outreach_message_id`
   - index on `event_state`
   - index on `event_timestamp`

### 7.1.1A Next-Build SQL DDL Skeleton

The following SQL DDL skeleton captures the next-build schema in implementation-ready form for SQLite. It is part of the specification and defines the expected table, view, foreign-key, and index shape for the next build.

```sql
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS linkedin_leads (
  lead_id TEXT PRIMARY KEY,
  lead_identity_key TEXT NOT NULL,
  lead_status TEXT NOT NULL,
  lead_shape TEXT NOT NULL,
  split_review_status TEXT NOT NULL,
  source_type TEXT NOT NULL,
  source_reference TEXT NOT NULL,
  source_mode TEXT NOT NULL,
  source_url TEXT,
  company_name TEXT,
  role_title TEXT,
  location TEXT,
  work_mode TEXT,
  compensation_summary TEXT,
  poster_name TEXT,
  poster_title TEXT,
  last_scraped_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_postings (
  job_posting_id TEXT PRIMARY KEY,
  lead_id TEXT NOT NULL,
  posting_identity_key TEXT NOT NULL,
  canonical_company_key TEXT NOT NULL,
  company_name TEXT NOT NULL,
  role_title TEXT NOT NULL,
  posting_status TEXT NOT NULL,
  provider_company_key TEXT,
  company_key_source TEXT,
  location TEXT,
  employment_type TEXT,
  posted_at TEXT,
  jd_artifact_path TEXT,
  archived_at TEXT,
  application_state TEXT,
  applied_at TEXT,
  application_url TEXT,
  application_notes TEXT,
  application_updated_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (lead_id) REFERENCES linkedin_leads(lead_id)
);

CREATE TABLE IF NOT EXISTS contacts (
  contact_id TEXT PRIMARY KEY,
  identity_key TEXT NOT NULL,
  display_name TEXT NOT NULL,
  company_name TEXT NOT NULL,
  origin_component TEXT NOT NULL,
  contact_status TEXT NOT NULL,
  full_name TEXT,
  first_name TEXT,
  last_name TEXT,
  linkedin_url TEXT,
  position_title TEXT,
  location TEXT,
  discovery_summary TEXT,
  current_working_email TEXT,
  identity_source TEXT,
  provider_name TEXT,
  provider_person_id TEXT,
  name_quality TEXT,
  responder_state TEXT,
  responded_at TEXT,
  responder_notes TEXT,
  responder_updated_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS linkedin_lead_contacts (
  linkedin_lead_contact_id TEXT PRIMARY KEY,
  lead_id TEXT NOT NULL,
  contact_id TEXT NOT NULL,
  contact_role TEXT NOT NULL,
  recipient_type_inferred TEXT NOT NULL,
  is_primary_poster INTEGER NOT NULL,
  extraction_confidence TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (lead_id) REFERENCES linkedin_leads(lead_id),
  FOREIGN KEY (contact_id) REFERENCES contacts(contact_id),
  UNIQUE (lead_id, contact_id)
);

CREATE TABLE IF NOT EXISTS job_posting_contacts (
  job_posting_contact_id TEXT PRIMARY KEY,
  job_posting_id TEXT NOT NULL,
  contact_id TEXT NOT NULL,
  recipient_type TEXT NOT NULL,
  relevance_reason TEXT NOT NULL,
  link_level_status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (job_posting_id) REFERENCES job_postings(job_posting_id),
  FOREIGN KEY (contact_id) REFERENCES contacts(contact_id),
  UNIQUE (job_posting_id, contact_id)
);

CREATE TABLE IF NOT EXISTS resume_tailoring_runs (
  resume_tailoring_run_id TEXT PRIMARY KEY,
  job_posting_id TEXT NOT NULL,
  base_used TEXT NOT NULL,
  tailoring_status TEXT NOT NULL,
  resume_review_status TEXT NOT NULL,
  workspace_path TEXT NOT NULL,
  meta_yaml_path TEXT,
  final_resume_path TEXT,
  verification_outcome TEXT,
  started_at TEXT,
  completed_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (job_posting_id) REFERENCES job_postings(job_posting_id)
);

CREATE TABLE IF NOT EXISTS artifact_records (
  artifact_id TEXT PRIMARY KEY,
  artifact_type TEXT NOT NULL,
  file_path TEXT NOT NULL,
  producer_component TEXT NOT NULL,
  lead_id TEXT,
  job_posting_id TEXT,
  contact_id TEXT,
  outreach_message_id TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (lead_id) REFERENCES linkedin_leads(lead_id),
  FOREIGN KEY (job_posting_id) REFERENCES job_postings(job_posting_id),
  FOREIGN KEY (contact_id) REFERENCES contacts(contact_id),
  FOREIGN KEY (outreach_message_id) REFERENCES outreach_messages(outreach_message_id),
  CHECK (
    lead_id IS NOT NULL
    OR job_posting_id IS NOT NULL
    OR contact_id IS NOT NULL
    OR outreach_message_id IS NOT NULL
  )
);

CREATE TABLE IF NOT EXISTS state_transition_events (
  state_transition_event_id TEXT PRIMARY KEY,
  object_type TEXT NOT NULL,
  object_id TEXT NOT NULL,
  stage TEXT NOT NULL,
  previous_state TEXT NOT NULL,
  new_state TEXT NOT NULL,
  transition_timestamp TEXT NOT NULL,
  transition_reason TEXT,
  caused_by TEXT,
  lead_id TEXT,
  job_posting_id TEXT,
  contact_id TEXT,
  FOREIGN KEY (lead_id) REFERENCES linkedin_leads(lead_id),
  FOREIGN KEY (job_posting_id) REFERENCES job_postings(job_posting_id),
  FOREIGN KEY (contact_id) REFERENCES contacts(contact_id)
);

CREATE TABLE IF NOT EXISTS override_events (
  override_event_id TEXT PRIMARY KEY,
  object_type TEXT NOT NULL,
  object_id TEXT NOT NULL,
  component_stage TEXT NOT NULL,
  previous_value TEXT NOT NULL,
  new_value TEXT NOT NULL,
  override_reason TEXT NOT NULL,
  override_timestamp TEXT NOT NULL,
  override_by TEXT,
  lead_id TEXT,
  job_posting_id TEXT,
  contact_id TEXT,
  FOREIGN KEY (lead_id) REFERENCES linkedin_leads(lead_id),
  FOREIGN KEY (job_posting_id) REFERENCES job_postings(job_posting_id),
  FOREIGN KEY (contact_id) REFERENCES contacts(contact_id)
);

CREATE TABLE IF NOT EXISTS feedback_sync_runs (
  feedback_sync_run_id TEXT PRIMARY KEY,
  scheduler_name TEXT NOT NULL,
  scheduler_type TEXT NOT NULL,
  started_at TEXT NOT NULL,
  result TEXT NOT NULL,
  completed_at TEXT,
  observation_scope TEXT,
  messages_examined INTEGER,
  bounce_events_written INTEGER,
  reply_events_written INTEGER,
  last_checkpoint TEXT,
  error_message TEXT
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
  pipeline_run_id TEXT PRIMARY KEY,
  run_scope_type TEXT NOT NULL,
  run_status TEXT NOT NULL,
  current_stage TEXT NOT NULL,
  lead_id TEXT,
  job_posting_id TEXT,
  completed_at TEXT,
  last_error_summary TEXT,
  review_packet_status TEXT,
  run_summary TEXT,
  started_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (lead_id) REFERENCES linkedin_leads(lead_id),
  FOREIGN KEY (job_posting_id) REFERENCES job_postings(job_posting_id)
);

CREATE TABLE IF NOT EXISTS supervisor_cycles (
  supervisor_cycle_id TEXT PRIMARY KEY,
  trigger_type TEXT NOT NULL,
  scheduler_name TEXT,
  selected_work_type TEXT,
  selected_work_id TEXT,
  pipeline_run_id TEXT,
  started_at TEXT NOT NULL,
  completed_at TEXT,
  result TEXT NOT NULL,
  error_summary TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (pipeline_run_id) REFERENCES pipeline_runs(pipeline_run_id)
);

CREATE TABLE IF NOT EXISTS agent_control_state (
  control_key TEXT PRIMARY KEY,
  control_value TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_runtime_leases (
  lease_name TEXT PRIMARY KEY,
  lease_owner_id TEXT NOT NULL,
  acquired_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  last_renewed_at TEXT,
  lease_note TEXT
);

CREATE TABLE IF NOT EXISTS agent_incidents (
  agent_incident_id TEXT PRIMARY KEY,
  incident_type TEXT NOT NULL,
  severity TEXT NOT NULL,
  status TEXT NOT NULL,
  summary TEXT NOT NULL,
  pipeline_run_id TEXT,
  lead_id TEXT,
  job_posting_id TEXT,
  contact_id TEXT,
  outreach_message_id TEXT,
  resolved_at TEXT,
  escalation_reason TEXT,
  repair_attempt_summary TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (pipeline_run_id) REFERENCES pipeline_runs(pipeline_run_id),
  FOREIGN KEY (lead_id) REFERENCES linkedin_leads(lead_id),
  FOREIGN KEY (job_posting_id) REFERENCES job_postings(job_posting_id),
  FOREIGN KEY (contact_id) REFERENCES contacts(contact_id),
  FOREIGN KEY (outreach_message_id) REFERENCES outreach_messages(outreach_message_id)
);

CREATE TABLE IF NOT EXISTS expert_review_packets (
  expert_review_packet_id TEXT PRIMARY KEY,
  pipeline_run_id TEXT NOT NULL,
  packet_status TEXT NOT NULL,
  packet_path TEXT NOT NULL,
  job_posting_id TEXT,
  reviewed_at TEXT,
  summary_excerpt TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (pipeline_run_id) REFERENCES pipeline_runs(pipeline_run_id),
  FOREIGN KEY (job_posting_id) REFERENCES job_postings(job_posting_id)
);

CREATE TABLE IF NOT EXISTS expert_review_decisions (
  expert_review_decision_id TEXT PRIMARY KEY,
  expert_review_packet_id TEXT NOT NULL,
  decision_type TEXT NOT NULL,
  decision_notes TEXT,
  override_event_id TEXT,
  decided_at TEXT NOT NULL,
  applied_at TEXT,
  FOREIGN KEY (expert_review_packet_id) REFERENCES expert_review_packets(expert_review_packet_id),
  FOREIGN KEY (override_event_id) REFERENCES override_events(override_event_id)
);

CREATE TABLE IF NOT EXISTS windows (
  window_id TEXT PRIMARY KEY,
  window_start TEXT NOT NULL,
  window_end TEXT NOT NULL,
  status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS provider_budget_state (
  provider_name TEXT PRIMARY KEY,
  remaining_credits INTEGER,
  credit_limit INTEGER,
  reset_at TEXT,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS provider_budget_events (
  provider_budget_event_id TEXT PRIMARY KEY,
  provider_name TEXT NOT NULL,
  event_type TEXT NOT NULL,
  credit_delta INTEGER NOT NULL,
  remaining_credits_after INTEGER,
  related_discovery_attempt_id TEXT,
  related_contact_id TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (related_contact_id) REFERENCES contacts(contact_id)
);

CREATE TABLE IF NOT EXISTS discovery_attempts (
  discovery_attempt_id TEXT PRIMARY KEY,
  contact_id TEXT NOT NULL,
  job_posting_id TEXT,
  window_id TEXT,
  outcome TEXT NOT NULL,
  provider_name TEXT,
  email TEXT,
  email_local_part TEXT,
  detected_pattern TEXT,
  provider_verification_status TEXT,
  provider_score TEXT,
  bounced INTEGER,
  display_name TEXT,
  first_name TEXT,
  last_name TEXT,
  full_name TEXT,
  linkedin_url TEXT,
  position_title TEXT,
  location TEXT,
  provider_person_id TEXT,
  name_quality TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (contact_id) REFERENCES contacts(contact_id),
  FOREIGN KEY (job_posting_id) REFERENCES job_postings(job_posting_id),
  FOREIGN KEY (window_id) REFERENCES windows(window_id)
);

CREATE TABLE IF NOT EXISTS outreach_messages (
  outreach_message_id TEXT PRIMARY KEY,
  contact_id TEXT NOT NULL,
  outreach_mode TEXT NOT NULL,
  recipient_email TEXT NOT NULL,
  message_status TEXT NOT NULL,
  job_posting_id TEXT,
  job_posting_contact_id TEXT,
  subject TEXT,
  body_text TEXT,
  body_html TEXT,
  thread_id TEXT,
  delivery_tracking_id TEXT,
  sent_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (contact_id) REFERENCES contacts(contact_id),
  FOREIGN KEY (job_posting_id) REFERENCES job_postings(job_posting_id),
  FOREIGN KEY (job_posting_contact_id) REFERENCES job_posting_contacts(job_posting_contact_id)
);

CREATE TABLE IF NOT EXISTS delivery_feedback_events (
  delivery_feedback_event_id TEXT PRIMARY KEY,
  outreach_message_id TEXT NOT NULL,
  event_state TEXT NOT NULL,
  event_timestamp TEXT NOT NULL,
  contact_id TEXT,
  job_posting_id TEXT,
  reply_summary TEXT,
  raw_reply_excerpt TEXT,
  created_at TEXT,
  FOREIGN KEY (outreach_message_id) REFERENCES outreach_messages(outreach_message_id),
  FOREIGN KEY (contact_id) REFERENCES contacts(contact_id),
  FOREIGN KEY (job_posting_id) REFERENCES job_postings(job_posting_id)
);

CREATE INDEX IF NOT EXISTS idx_linkedin_leads_identity_key
  ON linkedin_leads(lead_identity_key);
CREATE INDEX IF NOT EXISTS idx_linkedin_leads_status
  ON linkedin_leads(lead_status);
CREATE INDEX IF NOT EXISTS idx_linkedin_leads_split_review_status
  ON linkedin_leads(split_review_status);

CREATE INDEX IF NOT EXISTS idx_job_postings_lead_id
  ON job_postings(lead_id);
CREATE INDEX IF NOT EXISTS idx_job_postings_identity_key
  ON job_postings(posting_identity_key);
CREATE INDEX IF NOT EXISTS idx_job_postings_status
  ON job_postings(posting_status);
CREATE INDEX IF NOT EXISTS idx_job_postings_application_state
  ON job_postings(application_state);

CREATE INDEX IF NOT EXISTS idx_contacts_identity_key
  ON contacts(identity_key);
CREATE INDEX IF NOT EXISTS idx_contacts_linkedin_url
  ON contacts(linkedin_url);
CREATE INDEX IF NOT EXISTS idx_contacts_responder_state
  ON contacts(responder_state);
CREATE INDEX IF NOT EXISTS idx_contacts_provider_person
  ON contacts(provider_name, provider_person_id);
CREATE INDEX IF NOT EXISTS idx_contacts_status
  ON contacts(contact_status);
CREATE INDEX IF NOT EXISTS idx_contacts_working_email
  ON contacts(current_working_email);
CREATE INDEX IF NOT EXISTS idx_contacts_origin_component
  ON contacts(origin_component);

CREATE UNIQUE INDEX IF NOT EXISTS idx_linkedin_lead_contacts_pair
  ON linkedin_lead_contacts(lead_id, contact_id);
CREATE INDEX IF NOT EXISTS idx_linkedin_lead_contacts_role
  ON linkedin_lead_contacts(contact_role);
CREATE INDEX IF NOT EXISTS idx_linkedin_lead_contacts_recipient_type
  ON linkedin_lead_contacts(recipient_type_inferred);

CREATE UNIQUE INDEX IF NOT EXISTS idx_job_posting_contacts_pair
  ON job_posting_contacts(job_posting_id, contact_id);
CREATE INDEX IF NOT EXISTS idx_job_posting_contacts_status
  ON job_posting_contacts(link_level_status);
CREATE INDEX IF NOT EXISTS idx_job_posting_contacts_recipient_type
  ON job_posting_contacts(recipient_type);

CREATE INDEX IF NOT EXISTS idx_resume_tailoring_runs_job_posting
  ON resume_tailoring_runs(job_posting_id);
CREATE INDEX IF NOT EXISTS idx_resume_tailoring_runs_review_status
  ON resume_tailoring_runs(resume_review_status);

CREATE INDEX IF NOT EXISTS idx_artifact_records_type
  ON artifact_records(artifact_type);
CREATE INDEX IF NOT EXISTS idx_artifact_records_lead
  ON artifact_records(lead_id);
CREATE INDEX IF NOT EXISTS idx_artifact_records_job_posting
  ON artifact_records(job_posting_id);
CREATE INDEX IF NOT EXISTS idx_artifact_records_contact
  ON artifact_records(contact_id);
CREATE INDEX IF NOT EXISTS idx_artifact_records_message
  ON artifact_records(outreach_message_id);

CREATE INDEX IF NOT EXISTS idx_state_transition_events_object
  ON state_transition_events(object_type, object_id);
CREATE INDEX IF NOT EXISTS idx_state_transition_events_timestamp
  ON state_transition_events(transition_timestamp);

CREATE INDEX IF NOT EXISTS idx_override_events_object
  ON override_events(object_type, object_id);
CREATE INDEX IF NOT EXISTS idx_override_events_timestamp
  ON override_events(override_timestamp);

CREATE INDEX IF NOT EXISTS idx_feedback_sync_runs_started_at
  ON feedback_sync_runs(started_at);
CREATE INDEX IF NOT EXISTS idx_feedback_sync_runs_result
  ON feedback_sync_runs(result);
CREATE INDEX IF NOT EXISTS idx_feedback_sync_runs_scheduler_name
  ON feedback_sync_runs(scheduler_name);

CREATE INDEX IF NOT EXISTS idx_pipeline_runs_status
  ON pipeline_runs(run_status);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_job_posting
  ON pipeline_runs(job_posting_id);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_stage
  ON pipeline_runs(current_stage);

CREATE INDEX IF NOT EXISTS idx_supervisor_cycles_started_at
  ON supervisor_cycles(started_at);
CREATE INDEX IF NOT EXISTS idx_supervisor_cycles_result
  ON supervisor_cycles(result);
CREATE INDEX IF NOT EXISTS idx_supervisor_cycles_pipeline_run
  ON supervisor_cycles(pipeline_run_id);

CREATE INDEX IF NOT EXISTS idx_agent_runtime_leases_expires_at
  ON agent_runtime_leases(expires_at);

CREATE INDEX IF NOT EXISTS idx_agent_incidents_status
  ON agent_incidents(status);
CREATE INDEX IF NOT EXISTS idx_agent_incidents_severity
  ON agent_incidents(severity);
CREATE INDEX IF NOT EXISTS idx_agent_incidents_pipeline_run
  ON agent_incidents(pipeline_run_id);

CREATE INDEX IF NOT EXISTS idx_expert_review_packets_status
  ON expert_review_packets(packet_status);
CREATE INDEX IF NOT EXISTS idx_expert_review_packets_pipeline_run
  ON expert_review_packets(pipeline_run_id);

CREATE INDEX IF NOT EXISTS idx_expert_review_decisions_packet
  ON expert_review_decisions(expert_review_packet_id);
CREATE INDEX IF NOT EXISTS idx_expert_review_decisions_decided_at
  ON expert_review_decisions(decided_at);

CREATE INDEX IF NOT EXISTS idx_discovery_attempts_contact
  ON discovery_attempts(contact_id);
CREATE INDEX IF NOT EXISTS idx_discovery_attempts_job_posting
  ON discovery_attempts(job_posting_id);
CREATE INDEX IF NOT EXISTS idx_discovery_attempts_outcome
  ON discovery_attempts(outcome);
CREATE INDEX IF NOT EXISTS idx_discovery_attempts_created_at
  ON discovery_attempts(created_at);

CREATE INDEX IF NOT EXISTS idx_provider_budget_events_provider
  ON provider_budget_events(provider_name);
CREATE INDEX IF NOT EXISTS idx_provider_budget_events_created_at
  ON provider_budget_events(created_at);

CREATE INDEX IF NOT EXISTS idx_outreach_messages_contact
  ON outreach_messages(contact_id);
CREATE INDEX IF NOT EXISTS idx_outreach_messages_job_posting
  ON outreach_messages(job_posting_id);
CREATE INDEX IF NOT EXISTS idx_outreach_messages_status
  ON outreach_messages(message_status);
CREATE INDEX IF NOT EXISTS idx_outreach_messages_sent_at
  ON outreach_messages(sent_at);

CREATE INDEX IF NOT EXISTS idx_delivery_feedback_events_message
  ON delivery_feedback_events(outreach_message_id);
CREATE INDEX IF NOT EXISTS idx_delivery_feedback_events_state
  ON delivery_feedback_events(event_state);
CREATE INDEX IF NOT EXISTS idx_delivery_feedback_events_timestamp
  ON delivery_feedback_events(event_timestamp);

CREATE VIEW IF NOT EXISTS unresolved_contacts_review AS
WITH latest_attempt AS (
  SELECT da.*
  FROM discovery_attempts da
  JOIN (
    SELECT contact_id, MAX(created_at) AS max_created_at
    FROM discovery_attempts
    GROUP BY contact_id
  ) latest
    ON da.contact_id = latest.contact_id
   AND da.created_at = latest.max_created_at
)
SELECT
  c.contact_id,
  c.full_name,
  c.company_name,
  c.contact_status,
  c.current_working_email,
  la.discovery_attempt_id,
  la.outcome AS latest_discovery_outcome,
  la.provider_name,
  la.email AS latest_attempt_email,
  la.created_at AS latest_attempt_at
FROM contacts c
LEFT JOIN latest_attempt la
  ON la.contact_id = c.contact_id
WHERE
  c.contact_status = 'exhausted'
  OR (
    c.current_working_email IS NULL
    AND (la.outcome IS NULL OR la.outcome <> 'found')
  );

CREATE VIEW IF NOT EXISTS bounced_email_review AS
SELECT
  dfe.delivery_feedback_event_id,
  dfe.outreach_message_id,
  om.contact_id,
  om.job_posting_id,
  c.full_name,
  om.recipient_email,
  dfe.event_state,
  dfe.event_timestamp,
  dfe.reply_summary
FROM delivery_feedback_events dfe
JOIN outreach_messages om
  ON om.outreach_message_id = dfe.outreach_message_id
LEFT JOIN contacts c
  ON c.contact_id = om.contact_id
WHERE dfe.event_state = 'bounced';
```

### 7.1.1B Machine Artifact Payload Schemas

The next build should define exact payload shapes for the primary machine handoff artifacts so upstream and downstream stages, plus review tooling, can rely on stable field names.

#### `lead-manifest.yaml`

```yaml
contract_version: "1.0"
produced_at: "2026-03-22T01:15:00Z"
producer_component: "linkedin_scraping"
result: "success"
reason_code: null
message: null
lead_id: "ld_001"
lead_status: "reviewed"
lead_shape: "posting_plus_contacts"
split_review_status: "confident"
source:
  source_type: "manual_paste"
  source_reference: "paste/paste.txt"
  source_mode: "manual_paste"
  source_url: null
summary:
  company_name: "Guidewire Software"
  role_title: "Software Engineer (Full-Stack)"
  location: "Bedford, MA"
  work_mode: "Hybrid"
  compensation_summary: "$86K/yr - $130K/yr"
  poster_name: "Alex Kordun"
  poster_title: "Director of Engineering, Guidewire"
artifacts:
  raw_source_path: "/abs/path/linkedin-scraping/runtime/leads/guidewire-software/software-engineer-full-stack/ld_001/raw/source.md"
  post_path: "/abs/path/linkedin-scraping/runtime/leads/guidewire-software/software-engineer-full-stack/ld_001/post.md"
  jd_path: "/abs/path/linkedin-scraping/runtime/leads/guidewire-software/software-engineer-full-stack/ld_001/jd.md"
  poster_profile_path: "/abs/path/linkedin-scraping/runtime/leads/guidewire-software/software-engineer-full-stack/ld_001/poster-profile.md"
  split_metadata_path: "/abs/path/linkedin-scraping/runtime/leads/guidewire-software/software-engineer-full-stack/ld_001/source-split.yaml"
  split_review_path: "/abs/path/linkedin-scraping/runtime/leads/guidewire-software/software-engineer-full-stack/ld_001/source-split-review.yaml"
created_entities:
  job_posting_id: "jp_001"
  contact_ids:
    - "ct_001"
  job_posting_contact_ids:
    - "jpc_001"
  linkedin_lead_contact_ids:
    - "llc_001"
handoff_targets:
  resume_tailoring:
    ready: true
    reason_code: null
    required_artifacts:
      - "/abs/path/linkedin-scraping/runtime/leads/guidewire-software/software-engineer-full-stack/ld_001/jd.md"
  email_outreach:
    ready: false
    reason_code: "missing_working_email"
    required_artifacts:
      - "/abs/path/linkedin-scraping/runtime/leads/guidewire-software/software-engineer-full-stack/ld_001/poster-profile.md"
```

Rules:
1. `lead-manifest.yaml` is the authoritative machine handoff manifest from `LinkedIn Scraping`.
2. `lead-manifest.yaml` shall exist even when the lead is blocked or ambiguous.
3. `result = success` means the upstream lead bundle was persisted successfully; downstream readiness is determined separately per target in `handoff_targets`.
4. `handoff_targets` shall be the source-of-truth for whether a downstream may proceed from that lead bundle.

#### `meta.yaml`

```yaml
contract_version: "1.0"
produced_at: "2026-03-19T18:30:00Z"
producer_component: "resume_tailoring"
result: "success"
reason_code: null
message: null
job_posting_id: "jp_acme_backend_001"
resume_tailoring_run_id: "rtr_001"
base_used: "swe_general"
context_file: "/abs/path/jd.md"
scope_baseline_file: "/abs/path/scope-baseline.resume.tex"
section_locks:
  - "education"
experience_role_allowlist:
  - "software-engineer"
tailoring_status: "tailored"
resume_review_status: "resume_review_pending"
workspace_path: "/abs/path/workspace"
resume_artifacts:
  tex_path: "/abs/path/resume.tex"
  pdf_path: "/abs/path/Achyutaram Sonti.pdf"
send_linkage:
  outreach_mode: "role_targeted"
  resume_required: true
```

Rules:
1. `meta.yaml` is the structured Tailoring runtime artifact for review, audit, and artifact reference. Outreach bootstrap remains DB-first by `job_posting_id`.
2. `result` follows the shared contract semantics already defined in this specification.
3. `reason_code` and `message` should be populated when `result` is `blocked` or `failed`.
4. `resume_artifacts.pdf_path` should be present only when finalize/compile has completed successfully.

#### `people_search_result.json`

```json
{
  "contract_version": "1.0",
  "produced_at": "2026-04-04T20:40:00Z",
  "producer_component": "email_discovery",
  "result": "success",
  "reason_code": null,
  "message": null,
  "job_posting_id": "jp_acme_backend_001",
  "company_name": "Acme",
  "provider_name": "apollo",
  "resolved_company": {
    "organization_id": "57c4f624a6da9869ef365816",
    "organization_name": "PrePass",
    "primary_domain": "prepass.com",
    "website_url": "http://www.prepass.com",
    "linkedin_url": "http://www.linkedin.com/company/prepass-llc"
  },
  "applied_filters": {
    "titles": [
      "Engineering Manager",
      "Director of Engineering",
      "Recruiter",
      "Software Engineer"
    ]
  },
  "candidate_count": 31,
  "candidates": [
    {
      "provider_person_id": "54a44d9174686934427dd13c",
      "contact_id": "ct_001",
      "display_name": "Mike De***s",
      "name_quality": "provider_obfuscated",
      "full_name": null,
      "linkedin_url": null,
      "title": "Director of Engineering",
      "recipient_type_inferred": "hiring_manager",
      "relevance_reason": "engineering leadership for likely hiring area",
      "has_email": false,
      "has_direct_phone": true,
      "last_refreshed_at": "2026-03-20T04:11:39Z"
    },
    {
      "provider_person_id": "6710a593c236120001921676",
      "contact_id": "ct_002",
      "display_name": "Isaiah Lo***e",
      "name_quality": "provider_obfuscated",
      "full_name": null,
      "linkedin_url": null,
      "title": "Corporate Recruiter",
      "recipient_type_inferred": "recruiter",
      "relevance_reason": "recruiting function close to current role",
      "has_email": true,
      "has_direct_phone": true,
      "last_refreshed_at": "2026-03-30T17:50:12Z"
    }
  ]
}
```

Rules:
1. `people_search_result.json` is the authoritative machine artifact for the company-scoped people-search stage before person-scoped email discovery begins.
2. The artifact shall preserve the resolved company identity, the applied search filters, and the full candidate list returned by the broad search stage, even when many candidates are not later shortlisted.
3. Candidate rows may omit `full_name`, `linkedin_url`, and real email values at search time. Sparse or obfuscated search-stage identity is valid in this artifact.
4. For Apollo-backed candidates, `provider_person_id` shall be preserved whenever available because it is the stable bridge into later enrichment and contact identity.
5. `contact_id` should be present for candidates that have already been materialized into canonical `contacts`. It may be omitted for candidates that remain artifact-only search results.

#### `recipient_profile.json`

```json
{
  "contract_version": "1.0",
  "produced_at": "2026-04-04T20:55:00Z",
  "producer_component": "email_discovery",
  "result": "success",
  "reason_code": null,
  "message": null,
  "contact_id": "ct_002",
  "job_posting_id": "jp_acme_backend_001",
  "profile_source": "linkedin_public_profile",
  "source_method": "public_profile_html",
  "linkedin_url": "http://www.linkedin.com/in/isaiah-love-9170b9150",
  "profile": {
    "identity": {
      "display_name": "Isaiah Love",
      "full_name": "Isaiah Love",
      "first_name": "Isaiah",
      "last_name": "Love"
    },
    "top_card": {
      "current_company": "PrePass",
      "current_title": null,
      "headline": null,
      "location": "Phoenix, Arizona, United States",
      "connections": "500+",
      "followers": "412"
    },
    "about": {
      "preview_text": null,
      "is_truncated": false
    },
    "experience_hints": {
      "current_company_hint": "PrePass",
      "education_hint": null,
      "experience_education_preview": "Experience & Education PrePass ..."
    },
    "recent_public_activity": [],
    "public_signals": {
      "licenses_and_certifications": [],
      "honors_and_awards": [],
      "recommendation_entities": []
    },
    "work_signals": [
      "recruiting function close to the target role",
      "current internal employee at the target company"
    ],
    "evidence_snippets": [
      "Current company hint: PrePass"
    ],
    "source_coverage": {
      "about": false,
      "activity": false,
      "experience_hint": true,
      "public_signals": false
    }
  }
}
```

Rules:
1. `recipient_profile.json` is the persisted internal snapshot for selected-contact profile context used by drafting when LinkedIn-profile extraction succeeds.
2. The artifact shall be rooted in stable internal IDs such as `contact_id` and optional `job_posting_id`, while preserving the source LinkedIn URL used for extraction.
3. The snapshot shall be sectioned and broad, with the current preferred sections being `identity`, `top_card`, `about`, `experience_hints`, `recent_public_activity`, `public_signals`, `work_signals`, `evidence_snippets`, and `source_coverage`.
4. The extraction goal is to preserve as much clean public profile information as possible from the selected contact's public page, provided that the information is available without requiring hidden/member-only sections and can be stored in a stable structured form.
5. `top_card`, `about`, `experience_hints`, `recent_public_activity`, and `public_signals` are all optional. Sparse profiles may expose only a subset of these sections.
6. `recent_public_activity` may be populated from publicly exposed recent-profile activity or JSON-LD activity data when available. `public_signals` may include publicly exposed certifications, honors, awards, or recommendation names when visible.
7. `evidence_snippets` shall contain short grounded strings that explain where `work_signals` came from, such as visible about-preview text, public activity excerpts, company hints, or recommendation/certification clues.
8. `source_coverage` shall explicitly record which useful signal groups were actually exposed on the public page so downstream drafting can distinguish between `missing`, `not exposed`, and `not extracted`.
9. The artifact shall not invent hidden or member-only fields. `current_title`, `headline`, exact experience rows, full education history, skills, and other rich profile sections may be stored when they are clearly and cleanly available from the public page, but they shall otherwise remain `null`, empty, or omitted.
10. The artifact may be absent when no LinkedIn URL is available or extraction fails. In that case, drafting shall fall back to the best available search/enrichment context.
11. In practice, the highest-value LinkedIn-derived enrichment signals remain `recent_public_activity`, `about`, `work_signals`, and `evidence_snippets`, but the artifact should still preserve the broader clean public profile context because it may become useful for later ranking, review, or drafting improvements.

#### `discovery_result.json`

```json
{
  "contract_version": "1.0",
  "produced_at": "2026-03-19T18:35:00Z",
  "producer_component": "email_discovery",
  "result": "success",
  "reason_code": null,
  "message": null,
  "contact_id": "ct_001",
  "job_posting_id": "jp_acme_backend_001",
  "discovery_attempt_id": "da_001",
  "outcome": "found",
  "email": "maya@example.com",
  "provider_name": "hunter",
  "provider_verification_status": "verified",
  "provider_score": "0.93",
  "detected_pattern": "first.last",
  "observed_bounced": false,
  "recipient_profile_artifact_path": "/abs/path/discovery/output/acme/backend-engineer/recipient-profiles/ct_001/recipient_profile.json"
}
```

Rules:
1. `result = success` means a usable working email was produced for downstream drafting/sending.
2. `recipient_profile_artifact_path` should be present when recipient-profile extraction succeeded for the same contact before drafting begins.
3. If discovery cannot produce a usable working email, `result` should be `blocked` and `outcome` should capture the best current state such as `not_found` or `exhausted`.
4. `job_posting_id` may be `null` for general learning outreach.
5. `observed_bounced` is optional and defaults to `false` when omitted.

#### `send_result.json`

```json
{
  "contract_version": "1.0",
  "produced_at": "2026-03-19T18:40:00Z",
  "producer_component": "email_drafting_sending",
  "result": "success",
  "reason_code": null,
  "message": null,
  "outreach_message_id": "om_001",
  "contact_id": "ct_001",
  "job_posting_id": "jp_acme_backend_001",
  "outreach_mode": "role_targeted",
  "recipient_email": "maya@example.com",
  "send_status": "sent",
  "sent_at": "2026-03-19T18:40:00Z",
  "thread_id": "gmail-thread-123",
  "delivery_tracking_id": "gmail-message-456",
  "subject": "Backend Software Engineer, AI Infrastructure",
  "body_text_artifact_path": "/abs/path/email_draft.md",
  "body_html_artifact_path": null
}
```

Rules:
1. `send_status` should reflect the current message-level send result such as `generated`, `sent`, `blocked`, or `failed`.
2. `result = success` means the send-stage output is usable for downstream Delivery Feedback tracking. In the normal sent case, that means `outreach_message_id`, `recipient_email`, and send metadata are persisted.
3. `job_posting_id` may be `null` for general learning outreach.
4. `body_html_artifact_path` may be `null` when only plain-text-compatible output is used.

#### `delivery_outcome.json`

```json
{
  "contract_version": "1.0",
  "produced_at": "2026-03-19T18:55:00Z",
  "producer_component": "delivery_feedback",
  "result": "success",
  "reason_code": null,
  "message": null,
  "delivery_feedback_event_id": "dfe_001",
  "outreach_message_id": "om_001",
  "contact_id": "ct_001",
  "job_posting_id": "jp_acme_backend_001",
  "event_state": "bounced",
  "event_timestamp": "2026-03-19T18:54:00Z",
  "reply_summary": null,
  "raw_reply_excerpt": null,
  "mailbox_reference": "gmail-message-789"
}
```

Rules:
1. `event_state` should use the current high-level values `sent`, `bounced`, `not_bounced`, or `replied`.
2. `result = success` means a delivery-feedback event was successfully detected and persisted.
3. `reply_summary` and `raw_reply_excerpt` should be populated only when useful reply content exists.
4. `mailbox_reference` may store a secondary mailbox-specific identifier but does not replace `outreach_message_id` as the canonical internal linkage key.

### 7.1.1C LinkedIn Scraping Upstream Model

This section supplements the main system requirements and schema sections with the machine handoff contract for `LinkedIn Scraping`. The lead lifecycle, lead entity model, and lead-linked schema shape are defined primarily in Sections `5.1`, `7.1`, and `12.5A`.

#### `lead-manifest.yaml` Contract

`lead-manifest.yaml` should include, at minimum:

1. shared contract envelope fields such as `contract_version`, `produced_at`, `producer_component`, and `result`
2. lead identifiers and state such as `lead_id`, `lead_status`, `lead_shape`, `source_mode`, and `split_review_status`
3. extracted summary fields such as company, role, location, work mode, compensation summary, poster name, and poster title
4. direct artifact paths for `raw/source.md`, `source-split.yaml`, and `source-split-review.yaml` when those artifacts exist for the lead mode, plus available derived/source-mode artifacts such as `post.md`, `jd.md`, `poster-profile.md`, `capture-bundle.json`, and references to originating Gmail collection artifacts and parsed job-card metadata when the source mode is `gmail_job_alert`
5. created entity identifiers such as `job_posting_id`, created `contact_id` values, and created posting-contact link identifiers when they exist
6. artifact availability and provenance fields, such as whether `post.md` or `poster-profile.md` are unavailable and whether `jd.md` came from manual capture or autonomous fetch
7. `handoff_targets`, where each downstream target records at least readiness, reason code, required artifact references, and relevant created entities
8. for autonomous Gmail-derived leads, the originating Gmail collection references and parsed job-card references should be carried directly in `lead-manifest.yaml` rather than requiring additional lead-local metadata files by default
9. for autonomous Gmail-derived leads, `lead-manifest.yaml` should be able to represent `incomplete` before JD recovery succeeds and `blocked_no_jd` when JD recovery ultimately fails
10. for autonomous Gmail-derived leads, the minimum source-reference set in `lead-manifest.yaml` should include the originating `gmail_message_id`, `gmail_thread_id` when available, `received_at`, the Gmail collection artifact reference, the parsed job-card reference or card index, the LinkedIn `job_url`, and either the recovered `job_id` or the persisted synthetic fallback identity key
11. for autonomous Gmail-derived leads that are blocked or review-required, `lead-manifest.yaml` should still persist the current `lead_status`, a machine-readable `reason_code`, the known summary fields recovered so far, and `handoff_targets` entries with `ready = false` and the blocking reason

#### Manual Capture Submission Contract

The upstream manual-capture submission contract should include, at minimum:

1. `source_mode = manual_capture`
2. a stable submission identifier or request identifier
3. one or more `captures[]` entries with fields such as `capture_mode`, `page_type`, `source_url`, `page_title`, `selected_text`, `full_text`, and `captured_at`
4. enough metadata to preserve capture order so the canonical `raw/source.md` can be reconstructed deterministically

#### Gmail Job Alert Intake Contract

The upstream Gmail-alert intake contract should include, at minimum:

1. `source_mode = gmail_job_alert`
2. Gmail message identity fields such as `gmail_message_id` and `gmail_thread_id` when available, with `gmail_thread_id` treated as a secondary reference rather than a collection or deduplication key
3. source-mailbox metadata such as sender identity, subject, and alert timing fields such as `received_at`
4. run metadata identifying the agent-invoked Gmail ingestion run, plus collection metadata such as `collected_at` and a Gmail collection path or reference keyed by `received_at + gmail_message_id`
5. idempotent collection behavior keyed by `gmail_message_id`, so re-encountering a message with an already-collected `gmail_message_id` does not overwrite or create a second collected-email unit
6. enough snapshot content to preserve one clean human-readable alert-body snapshot plus a compact machine-readable snapshot containing normalized message metadata and only the raw body parts and parse-relevant fields actually used, without requiring a mailbox refetch for review
7. zero or more parsed non-duplicate alert-card entries, where each entry can carry company, role, location, badge lines, `job_url`, and extracted job identifier when available, and where entries may remain present even if later JD recovery for that card fails
8. zero-card parse outcomes, including retention of the collected email artifacts, an allowed empty `job-cards.json`, and the rule that no lead workspace is created from that message
9. zero-card review-threshold metadata so those collected emails are surfaced for review when more than 3 occur in a single Gmail ingestion run or when the cumulative unresolved count exceeds 3 across history
10. when `job_id` is unavailable, a persisted synthetic fallback identity key derived from the normalized LinkedIn job URL when that URL is available
11. when both `job_id` and usable LinkedIn job URL are unavailable, a reviewable recovery outcome indicating whether a usable JD was recovered from another supported source
12. final merged JD provenance fields such as canonical JD outcome, final canonical JD artifact reference, contributing source types, and the conflict-resolution policy used when sources differed
13. final company-resolution fields such as resolved company website, selected careers URL when found, final exact-match outcome, and final resolution reason
14. identity-reconciliation fields such as parsed alert-card company/role, JD-derived company/role when available, mismatch status, and the review-block reason when those identities disagree materially
15. for basic functioning, `email.json` should at minimum carry `gmail_message_id`, `gmail_thread_id` when available, sender, subject, `received_at`, `collected_at`, the agent-invoked Gmail ingestion run identifier, which body representation was used for parsing, the parse outcome, the parseable job-card count, and the specific raw body part or body-derived text actually used by the parser
16. for basic functioning, each `job-cards.json` entry should at minimum carry `card_index`, `role_title`, `company_name`, `location`, `badge_lines`, `job_url`, `job_id` when available, and the source `gmail_message_id`

### 7.1.2 External Integration Boundary

- **FR-SYS-72 (External Integration Classes):** In this build, the system's external integrations should be understood in these main classes:
  1. input/context sources such as job postings, LinkedIn-derived profile context, and other lead-source material
  2. email-discovery providers
  3. outbound email sending or mailbox integrations
  4. inbound delivery-feedback or mailbox-observation integrations
- **FR-SYS-73 (Normalized Adapter Boundary):** Core pipeline behavior shall rely on normalized internal artifacts, statuses, and canonical records rather than directly coupling orchestration or state transitions to provider-specific raw responses.
- **FR-SYS-74 (Persisted External-Context Rule):** When external source material materially affects system behavior, the pipeline shall persist a usable internal snapshot, mirror, or normalized artifact of that material so later review does not depend on re-fetching mutable external content.
- **FR-SYS-75 (External Identifiers Are Secondary):** External provider identifiers such as provider contact IDs, mailbox thread IDs, or remote message IDs may be stored as secondary references, but they shall not replace internal canonical identifiers such as `job_posting_id`, `contact_id`, or `outreach_message_id`.
- **FR-SYS-76 (External Error Normalization):** Provider-specific errors, mailbox errors, and upstream integration failures should be normalized into internal blocked/failed reason codes so the system can handle them consistently without embedding vendor-specific logic throughout the orchestration layer.
- **FR-SYS-77 (Replaceable Integration Rule):** External integrations should be replaceable over time without forcing changes to the internal entity model, top-level statuses, handoff contracts, or review model.
- **FR-SYS-78 (Graceful External Degradation):** Temporary unavailability or degradation of one external integration shall only affect the dependent stage or object currently using that integration. It shall not invalidate unrelated already-persisted state or completed work elsewhere in the pipeline.
- **FR-SYS-79 (Send/Feedback Continuity Rule):** Outbound send integrations and inbound feedback integrations shall preserve enough shared external metadata, such as thread or provider delivery identifiers when available, to reconnect later replies or bounce signals to the originating `outreach_message` while keeping `outreach_message_id` as the canonical internal anchor.
- **FR-SYS-80 (No External System as Canonical State):** No external integration shall be treated as the canonical source of overall copilot state. External systems act as sources, action channels, or signal providers; canonical system state remains internal to the copilot.
- **FR-SYS-81 (Runtime Secret Boundary):** Integration credentials, provider secrets, and mailbox tokens shall be runtime configuration concerns rather than being embedded inside spec-defined artifacts, prompt artifacts, or canonical state records.

### 7.1.3 Current Security, Privacy, and Safety Policy

- **FR-SYS-82 (Single-User Security Model):** This build assumes a single primary owner/operator of the copilot. Multi-user roles, shared-tenant isolation, and role-based permission systems are not required in this specification.
- **FR-SYS-83 (Local Data Ownership Boundary):** Job-posting data, contact data, tailored resumes, outreach artifacts, and canonical state are owned and controlled within the user's local copilot workspace and its configured runtime integrations rather than being designed as a shared multi-user SaaS data plane.
- **FR-SYS-84 (Secret Non-Persistence Rule):** Secrets, provider API keys, mailbox tokens, and other credentials shall not be persisted into canonical database records, runtime handoff artifacts, prompt artifacts, or review surfaces.
- **FR-SYS-85 (Minimum Necessary Personal Data Rule):** The system should persist only the personal/contact data needed to operate the current workflow, such as identity fields, contact linkage, working email, and review-relevant context. It should avoid storing broader personal data unless a clear workflow need exists.
- **FR-SYS-86 (Safe Outreach Grounding Rule):** Autonomous outreach shall remain grounded in persisted internal context such as the candidate master profile, tailored resume, job-posting context, and recipient-profile context. The system shall not invent qualifications, fake relationships, or imply facts not supported by stored evidence.
- **FR-SYS-87 (Autonomous Outreach Safety Boundary):** Autonomous sending is allowed only within the current workflow boundaries already defined in this specification, including:
  1. role-targeted outreach after tailoring/finalize succeeds and the mandatory agent review approves the active run
  2. general learning outreach that does not require a role-targeted resume
  3. no automatic repeat outreach when prior outreach history makes the next action ambiguous
- **FR-SYS-88 (Contact Respect Rule):** The system should behave conservatively around repeat contact, ambiguous resend, and exhausted discovery/send cases. When the respectful or safe next step is unclear, the system should surface the case for review instead of aggressively continuing.
- **FR-SYS-89 (Review-Safe Data Exposure):** Review surfaces should expose enough detail for the owner to make decisions, but they should avoid unnecessarily repeating secrets or unrelated personal data when a smaller relevant view would suffice.
- **FR-SYS-90 (Artifact and State Auditability as Safety Feature):** Persisted artifacts, state transitions, and override history are part of the system's safety model. The system should preserve enough auditability that the owner can understand why an outreach action happened and what evidence/context supported it.
- **FR-SYS-91 (No Broad Destructive Reset by Default):** Because the system stores personal contact data and outreach history, broad destructive reset or deletion behavior shall not be the default operational path. Safer archival, status-based retirement, or targeted cleanup should be preferred.

### 7.1.4 Current Vendor Integration Details

- **FR-SYS-92 (Vendor Detail Coverage in Spec):** The specification shall record the current vendor integration details needed for implementation, including credential shape, auth method, base endpoints, success criteria, and normalized failure handling. Actual secret values shall not be written into the spec.
- **FR-SYS-93 (Runtime Secret Shape for Current Build):** For the current local single-user build, it is sufficient for runtime vendor credentials to be supplied through local secret files or equivalent runtime configuration. The current local secret-file shapes should be:
  1. `apollo_keys.json`
     ```json
     {"api_key": "REDACTED"}
     ```
  2. `prospeo_keys.json`
     ```json
     {"api_key": "REDACTED"}
     ```
  3. `getprospect_keys.json`
     ```json
     {"api_key": "REDACTED"}
     ```
  4. `hunter_keys.json`
     ```json
     {"keys": [{"api_key": "REDACTED", "label": "primary"}]}
     ```
  5. Gmail OAuth client secret file matching `client_secret_*.json` as provided by Google Cloud OAuth desktop-app setup
  6. Gmail OAuth token file `token.json`
- **FR-SYS-93A (Single Bootstrap Secret File Allowed):** For setup convenience, this build may also accept one consolidated local bootstrap secret file, such as `runtime_secrets.json`, that contains all provider keys and Gmail OAuth client-secret content in one place. Build/setup logic may materialize vendor-specific runtime files from that single bootstrap file when needed. Actual secret values still must not appear in the spec.
- **FR-SYS-94 (Runtime Secret Location Rule):** Runtime secret files shall remain local runtime configuration only. They may live at the project root or another configured secret location, but they shall not be copied into canonical DB records, machine handoff artifacts, prompt artifacts, or normal review surfaces.
- **FR-SYS-94A (People-Search Provider Registry):** The current people-search provider priority shall be Apollo first. PDL, Coresignal, ContactOut, and Clay-managed waterfalls are optional later expansion paths rather than required first-build dependencies.
- **FR-SYS-94A1 (Later Fallback Evaluation Order):** If the system later adds a second company-scoped people-search provider after Apollo, the default evaluation/implementation order shall be:
  1. `PDL`
  2. `Coresignal`
  3. `ContactOut`
  Clay-managed waterfalls may orchestrate multiple providers later, but Clay is not the default second provider choice for this build line.
- **FR-SYS-94B (Apollo People Search Contract):** The current Apollo people-search contract should be:
  1. Organization resolution endpoint: `POST https://api.apollo.io/api/v1/mixed_companies/search`
  2. People Search endpoint: `POST https://api.apollo.io/api/v1/mixed_people/api_search`
  3. Enrichment endpoint for selected contacts: `POST https://api.apollo.io/api/v1/people/match`
  4. Bulk enrichment endpoint for selected contacts: `POST https://api.apollo.io/api/v1/people/bulk_match`
  5. Auth method: Apollo master API key sent in the request header such as `x-api-key`
  6. Preferred search flow:
     - resolve the target company to an Apollo `organization_id`
     - run people search anchored on that resolved `organization_id`
     - shortlist or rank the returned people
     - enrich only the selected contacts that need fuller identity, LinkedIn URL, or a usable work email
  7. Request filters should support `organization_id` plus title, seniority, or location filters as needed for the current role-targeted search
  8. Search success criteria:
     - HTTP `200`
     - response contains one or more candidate people records
     - returned records contain a stable Apollo person identifier and enough metadata to normalize into candidate contacts
  9. Search behavior note:
     - people search identifies candidate contacts
     - the People API Search endpoint is optimized for net-new people search and should not itself be treated as the email-returning step
     - search-stage results may be sparse and may expose only a partial or obfuscated display name, title, booleans such as `has_email`, and a stable Apollo person ID
     - it should not be treated as equivalent to already having a usable email for every returned person
     - selected contacts may still require Apollo enrichment or separate email discovery
     - when Apollo enrichment returns a verified work email for a selected contact, separate third-party email-finder calls may be skipped for that contact
  10. Normalized failure mapping:
     - `401` -> `invalid_api_key`
     - `403` -> `plan_restricted`
     - `429` -> `rate_limited`
     - request exception -> `network_error`
     - other non-200 or malformed body -> `provider_error`
- **FR-SYS-94C (Optional Later People-Search Providers):** If later people-search fallbacks are added, they should normalize into the same contact-search outputs and canonical contact model rather than introducing provider-specific contact-state logic.
- **FR-SYS-95 (Prospeo Integration Contract):** The current Prospeo integration contract should be:
  1. Base endpoint: `POST https://api.prospeo.io/enrich-person`
  2. Credits/account endpoint: `GET https://api.prospeo.io/account-information`
  3. Auth method: `X-KEY` request header
  4. Primary request body when LinkedIn URL exists:
     ```json
     {
       "only_verified_email": true,
       "data": {"linkedin_url": "..."}
     }
     ```
  5. Fallback request body when LinkedIn URL does not exist:
     ```json
     {
       "only_verified_email": true,
       "data": {
         "first_name": "...",
         "last_name": "...",
         "company_website": "example.com"
       }
     }
     ```
  6. Success criteria:
     - HTTP `200`
     - response has a person email object
     - email status is `VERIFIED`
     - returned email matches the target domain
  7. Normalized no-match behavior:
     - HTTP `200` with provider no-match payloads such as `error_code = NO_MATCH` shall be normalized to `not_found` rather than `provider_error`
  7. Normalized failure mapping:
     - `401` -> `invalid_api_key`
     - `429` -> `rate_limited`
     - request exception -> `network_error`
     - other non-200 or malformed body -> `provider_error`
- **FR-SYS-96 (GetProspect Integration Contract):** The current GetProspect integration contract should be:
  1. Base endpoint: `GET https://api.getprospect.com/v2/email-finder`
  2. Auth method: `api_key` query parameter
  3. Required request parameters:
     - `full_name`
     - `domain`
     - `api_key`
  4. Success criteria:
     - HTTP `200`
     - response `success = true`
     - response data contains an email
     - returned email matches the target domain
     - provider status is one of `valid`, `risky`, or `accept_all`
  5. Normalized no-match behavior:
     - HTTP `200` with `success = false` and provider data status such as `not_found` shall be normalized to `not_found` rather than `provider_error`
  5. Normalized failure mapping:
     - `401` -> `invalid_api_key`
     - `429` -> `rate_limited`
     - request exception after retry allowance -> `network_error`
     - other non-200 or malformed body -> `provider_error`
- **FR-SYS-97 (Hunter Integration Contract):** The current Hunter integration contract should be:
  1. Finder endpoint: `GET https://api.hunter.io/v2/email-finder`
  2. Account endpoint: `GET https://api.hunter.io/v2/account`
  3. Verifier endpoint: `GET https://api.hunter.io/v2/email-verifier`
  4. Optional domain-search endpoint: `GET https://api.hunter.io/v2/domain-search`
  5. Auth method: `api_key` query parameter
  6. Finder request uses:
     - `first_name`
     - `last_name`
     - `api_key`
     - and either `domain` or `company`
  7. Hunter key rotation is allowed through multiple entries inside `hunter_keys.json`
  8. Finder success criteria:
     - HTTP `200`
     - response `data.email` exists
  9. Normalized no-match behavior:
     - HTTP `200` with `data.email = null` and an otherwise well-formed response shall be normalized to `not_found` rather than `provider_error`
  9. Current normalized failure mapping:
     - `401` -> `invalid_api_key`
     - `403` -> `rate_limited`
     - `429` -> `quota_exhausted`
     - request exception -> `network_error`
     - other non-200 or malformed body -> `provider_error`
  10. Credits tracking should separately capture search and verification pools when that account metadata is available.
- **FR-SYS-98 (Gmail Integration Contract):** The current Gmail integration contract should be:
  1. OAuth scopes:
     - `https://www.googleapis.com/auth/gmail.send`
     - `https://www.googleapis.com/auth/gmail.readonly`
  2. Client secret source: local `client_secret_*.json`
  3. Refreshable token source: local `token.json`
  4. Send-side metadata to persist when available:
     - Gmail message ID
     - Gmail thread ID
  5. Mailbox-observation duties:
     - read bounce emails
     - read reply emails
     - extract enough metadata to link those outcomes back to `outreach_message_id`
- **FR-SYS-99 (Person-Scoped Email Discovery Cascade Order):** When a selected contact still lacks a usable work email after people search and enrichment, person-scoped email discovery shall use this direct vendor order:
  1. `prospeo`
  2. `getprospect`
  3. `hunter`
- **FR-SYS-99A (People-Search Before Email-Finder Rule):** For role-targeted autonomous contact expansion, the system should prefer people search first and should use person-scoped email-finder vendors only for selected contacts that still lack usable work emails.
- **FR-SYS-100 (Vendor Config Audit Fields):** The system should record, in canonical state and runtime outputs where relevant, which vendor/provider was used, what normalized result was produced, and what normalized failure code occurred when a provider call did not succeed. It should not record the secret value itself.

### 7.1.5 Current Build Input Pack

- **FR-SYS-101 (Build Input Pack):** For this build, the implementation may assume a small local build-input pack in addition to the specification itself. At minimum, that pack should contain:
  1. `spec.md`
  2. `runtime_secrets.json` or equivalent local runtime secret files
  3. an `assets/` folder containing the reusable personal/context assets needed for Resume Tailoring and Outreach guidance
- **FR-SYS-102 (Bootstrap Secret File):** The preferred single-file bootstrap secret input for this build may be `runtime_secrets.json`. That file is a local setup artifact, not a canonical runtime/output artifact, and should remain ignored from version control.
- **FR-SYS-103 (Current Assets Folder Purpose):** The `assets/` folder should act as the reusable personal/context asset pack for a fresh build so the implementation does not depend on the full historical repository layout to recover user-specific tailoring and outreach context.
- **FR-SYS-104 (Minimum Resume-Tailoring Assets):** For this build, `assets/` should at minimum carry these Resume Tailoring inputs:
  1. `assets/resume-tailoring/profile.md`
  2. at least one base resume source file such as `assets/resume-tailoring/base/<track>/base-resume.tex`
  3. `assets/resume-tailoring/ai/system-prompt.md`
  4. `assets/resume-tailoring/ai/cookbook.md`
  5. `assets/resume-tailoring/ai/sop-swe-experience-tailoring.md`
  6. any preserved few-shot examples needed for current tailoring quality
- **FR-SYS-105 (Outreach Asset Scope):** For this build, the Outreach portion of `assets/` only needs to include the cold outreach guide and does not need the full historical outreach implementation tree. A file such as `assets/outreach/cold-outreach-guide.md` is sufficient as the writing-guide asset.
- **FR-SYS-106 (Build Environment Assumptions):** In addition to the file/folder inputs above, this build may assume:
  1. a working Python environment with required packages installed
  2. a local LaTeX installation capable of compiling the resume source
  3. network access for vendor APIs and Gmail OAuth/mailbox operations
- **FR-SYS-107 (Build Inputs Are Not Canonical Runtime State):** The build-input pack exists to bootstrap implementation and local operation. These files are not themselves the canonical system state; canonical state remains in `job_hunt_copilot.db` and in the spec-defined runtime artifacts once the system is running.
- **FR-SYS-108 (Current Build Checklist):** Before starting a fresh build, the implementation should verify this checklist in order:
  1. `spec.md` is present
  2. `runtime_secrets.json` is present, or equivalent vendor-specific secret files are already available
  3. `assets/` is present with the minimum Resume Tailoring and Outreach guide files
  4. vendor-specific runtime files can be materialized from `runtime_secrets.json` when needed:
     - `apollo_keys.json`
     - `prospeo_keys.json`
     - `getprospect_keys.json`
     - `hunter_keys.json`
     - `client_secret_*.json`
     - `token.json` when already available
  5. Python environment is available with the required packages installed
  6. local LaTeX toolchain is available and can compile the base resume source
  7. network access is available for vendor APIs and Gmail OAuth/mailbox operations
- **FR-SYS-109 (Python Dependency Set):** This build should assume at minimum these Python package dependencies:
  1. `google-auth-oauthlib`
  2. `google-api-python-client`
  3. `requests`
  4. `dnspython`
  5. `PyYAML`
  6. `pytest` for local testing
- **FR-SYS-109A (Python Version Target):** This build should target Python `3.11` as the reference interpreter version. Later builds may support newer versions, but the implementation and smoke-test expectations should treat Python 3.11 as the primary target.
- **FR-SYS-110 (LaTeX Dependency Set):** This build should assume a LaTeX environment capable of compiling the bundled base resume source, including support for:
  1. `extarticle`
  2. `geometry`
  3. `titlesec`
  4. `tabularx`
  5. `array`
  6. `xcolor`
  7. `enumitem`
  8. `fontawesome5`
  9. `amsmath`
  10. `hyperref`
  11. `eso-pic`
  12. `calc`
  13. `bookmark`
  14. `lastpage`
  15. `changepage`
  16. `paracol`
  17. `ifthen`
  18. `needspace`
  19. `iftex`
  20. `glyphtounicode`
  21. `inputenc`
  22. `helvet`
- **FR-SYS-111 (Current Build Smoke-Test Checklist):** After a fresh build is assembled, the implementation should be able to pass this short smoke-test checklist:
  1. initialize or migrate `job_hunt_copilot.db` successfully
  2. load `runtime_secrets.json` and materialize vendor-specific runtime secret files when required
  3. read the required files from `assets/`
  4. create a Resume Tailoring workspace for a sample posting
  5. compile the base or tailored resume successfully through the local LaTeX toolchain
  6. run a discovery-path check successfully, such as provider credit lookup or one discovery call with normalized output
  7. generate a machine-valid `discovery_result.json`
  8. generate a machine-valid `send_result.json` for a contact/message flow
  9. run delayed feedback sync logic once without crashing, even if no new bounce or reply events are found
  10. query at least one review surface from canonical state, such as pending resume review, unresolved contacts, or bounced-email review

## 7.2 Resume Tailoring Component FRs

### 7.2.1 Core Requirement
- **FR-RT-01 (JD Signal Extraction):**
  System shall analyze a JD and extract structured signals required for resume tailoring.

### 7.2.2 Signal Categories to Extract

- **FR-RT-02 (Role Metadata):**
  Extract role title, function, location, employment type, level/seniority, posted date.

- **FR-RT-03 (Role Intent):**
  Extract core role intent summary (example from discussion: strong web/full-stack foundation + AI integration into user-facing systems).

- **FR-RT-04 (Responsibilities):**
  Extract concrete expected actions/ownership from “What You’ll Do” bullets.
  Example classes:
  1. Build intelligent web/conversational applications
  2. Integrate AI APIs in modern web stack
  3. Design voice/chat interfaces
  4. Collaborate with data/AI teams and clients
  5. Build reusable frameworks/components

- **FR-RT-05 (Must-Have Requirements):**
  Extract hard requirements from “What You’ll Bring”:
  1. Experience floor (years)
  2. Core stack (JS/TS, React/Angular, Node)
  3. AI/ML model/API integration experience
  4. API/security/data-flow understanding
  5. Communication/teamwork expectations
  6. Legal/work-authorization constraints

- **FR-RT-06 (Nice-to-Have Requirements):**
  Extract optional differentiators from “Nice to Have” and treat them as high-value bonus signals.
  Example classes:
  1. Voice agents/conversational interfaces/AI copilots
  2. Vector DB/embedding search
  3. LLM integration in user-facing products
  4. Cloud platform exposure (Azure/AWS/GCP)

- **FR-RT-07 (Low-Relevance Sections):**
  System may capture compensation/benefits for context, but must mark these as low priority for tailoring.

### 7.2.3 Eligibility and Routing

- **FR-RT-08 (Hard Eligibility Gate):**
  System shall detect hard disqualifiers using an explicit rule list.

- **FR-RT-09 (No-Go Decision):**
  If any hard disqualifier is triggered, system shall mark application as hard-ineligible and skip downstream resume tailoring and outreach for that lead.

#### 7.2.3.1 Hard Disqualifier Policy (Current)
1. **Required experience threshold:** If the JD explicitly requires more than 5 years of experience, mark `hard-ineligible`.
2. **Citizenship/clearance requirement:** If the JD explicitly requires citizenship or security clearance, mark `hard-ineligible`.

- **FR-RT-08A (Global Experience Threshold Rule):**
  In the current build, the `>5 years` hard-disqualifier threshold is a single global rule rather than a role-family-specific configurable threshold.

- **FR-RT-08B (Future Threshold-Override Gate):**
  A future role-family-specific experience-threshold override shall not be introduced unless the system first has:
  1. an explicit `role_family` taxonomy
  2. versioned eligibility-policy configuration
  3. validation evidence showing that the override improves outcomes without materially increasing bad-fit outreach
  Until those prerequisites exist, the fixed global `>5 years` rule remains canonical.

#### 7.2.3.2 Soft Qualifier Policy (Current)
1. **No sponsorship language:** If JD says no sponsorship, do not hard-stop.
2. Mark as `soft-flag` and include guidance to mention OPT work authorization in outreach/application context.

#### 7.2.3.3 Missing Data Policy
1. If eligibility signals are missing or ambiguous, classify as `unknown` and proceed like normal leads (do not fail closed).

#### 7.2.3.4 Eligibility Audit Output (Current)
For each lead, persist an eligibility decision artifact with:
1. `eligibility_status` (`eligible`, `soft-flag`, `hard-ineligible`, `unknown`)
2. `hard_disqualifiers_triggered` (list)
3. `soft_flags` (list)
4. `missing_data_fields` (list)
5. `decision_reason` (short summary)
6. `evidence_snippets` (JD text excerpts used for decision)
7. `recommended_note` (for example, OPT note when sponsorship is a soft flag)

- **FR-RT-09A (Eligibility Artifact Placement):**
  The eligibility audit artifact for a role-targeted posting shall be persisted at `applications/{company}/{role}/eligibility.yaml` so the current orchestration layer can inspect eligibility outcomes even when the tailoring workspace is never created.

- **FR-RT-09B (Hard-Ineligible Short-Circuit):**
  If the hard-disqualifier gate returns `hard-ineligible`, the system shall:
  1. persist `eligibility.yaml`
  2. set `job_postings.posting_status = hard_ineligible`
  3. stop before full Resume Tailoring workspace bootstrap
  4. skip Step 3 through Step 7 intelligence artifacts, resume compilation, and Tailoring-to-Outreach handoff
  The posting remains queryable for audit and owner override, but downstream tailoring and outreach do not proceed automatically.

- **FR-RT-09C (No Tailoring Run on Hard-Ineligible Short-Circuit):**
  When a posting is stopped by the hard-disqualifier gate before workspace bootstrap, the system does not need to create a `resume_tailoring_runs` row for that blocked case. Canonical persistence for that outcome is the posting status plus the eligibility audit artifact.

#### 7.2.3.5 Override Policy (Current)
1. Only the primary user (owner) can apply overrides.
2. Within Resume Tailoring, the owner can override eligibility or tailoring outcomes after the system has produced them or after the agent review has recorded its decision.
3. Resume Tailoring has no mandatory human checkpoint in this build. The mandatory checkpoint is the agent review gate, and human review/override remains available as an operator control rather than a default pause.
4. Override actions must be persisted in audit fields:
   - `override_applied` (boolean)
   - `override_by` (user identifier)
   - `override_reason` (required free-text reason)
   - `overridden_decisions` (list)
   - `override_timestamp`
5. When an override is applied, pipeline continues under the build rules for the affected component(s).

### 7.2.4 Workspace and Scope Control

- **FR-RT-10A (Application Workspace Bootstrap):**
  System shall maintain a per-application tailoring workspace with at least:
  1. `meta.yaml`
  2. mirrored job-context files
  3. `resume.tex`
  4. a scope-baseline snapshot
  5. an intelligence artifact directory
  6. company/role-scoped filesystem placement for that posting workspace

- **FR-RT-10A1 (Bootstrap Materialization Sequence):**
  When a role-targeted posting enters Resume Tailoring, workspace bootstrap shall:
  1. resolve the selected base resume track
  2. materialize the selected base resume source into the workspace `resume.tex`
  3. create `scope-baseline.resume.tex` from that pre-edit workspace resume state
  4. mirror `jd.md` and any available `post.md` / `poster-profile.md` context into the workspace
  5. persist `meta.yaml`
  before any Step 3 to Step 7 intelligence generation begins.

- **FR-RT-10A2 (Run Record Creation Rule):**
  Once a posting passes the hard-disqualifier gate and workspace bootstrap begins, the system shall create a `resume_tailoring_runs` row with `tailoring_status = in_progress` and `resume_review_status = not_ready`.

- **FR-RT-10B (Context Mirroring):**
  Current setup flow shall persist job context into both:
  1. per-application mirrors such as `jd.md`, `post.md`, and poster-profile mirror when available
  2. a canonical job-context markdown file for the application

- **FR-RT-10B1 (Full JD Mirror Before Structuring):**
  When autonomous or manual intake obtains a usable JD, the full JD text shall be mirrored into `jd.md` before structured tailoring artifacts such as JD signals or evidence maps are produced.

- **FR-RT-10B2 (Structured Tailoring Inputs Rooted in `jd.md`):**
  Current JD-signal extraction, eligibility analysis, and other structured tailoring artifacts shall treat the persisted `jd.md` mirror as the primary JD content source.

- **FR-RT-10B3 (Canonical Working Job-Context Mirror):**
  In addition to the per-workspace mirrors, the current setup flow may materialize a component-local working job-context file such as `resume-tailoring/input/job-postings/{company}-{role}.md`. When that working file exists, it shall be derived from the same linked lead `jd.md` / posting context and shall not diverge semantically from the workspace `jd.md`.

- **FR-RT-10C (Constraint Metadata):**
  `meta.yaml` shall record the base resume track used and current tailoring constraints, including:
  1. `base-used`
  2. `context-file`
  3. `scope-baseline-file`
  4. `section-locks`
  5. `experience-role-allowlist`
  6. send-linkage metadata when available

- **FR-RT-10D (Scope Guard Enforcement):**
  Current tailoring shall enforce locked sections and role-level edit allowlists against a baseline snapshot before finalize/compile.

- **FR-RT-10E (Targeted Edit Scope):**
  In this build, tailoring should operate as a targeted rewrite of allowed sections and roles rather than a whole-resume freeform rewrite.

### 7.2.5 AI-Ingest Structuring

- **FR-RT-10 (Machine-Friendly Signals):**
  Extracted signals shall be emitted in structured format (JSON/YAML), grouped and labeled for easy AI ingestion.

- **FR-RT-11 (Signal Priority):**
  Each signal shall be assigned priority:
  1. Must-have (highest)
  2. Core responsibilities (high)
  3. Nice-to-have (medium)
  4. Informational (low)

- **FR-RT-11A (Current Default Signal Weights):**
  When the runtime needs numeric weighting for JD-signal ranking, matching, or coverage scoring, the current default weights shall be:
  1. `must_have = 1.00`
  2. `core_responsibility = 0.75`
  3. `nice_to_have = 0.40`
  4. `informational = 0.15`

- **FR-RT-11B (No Role-Family Weight Variation Yet):**
  In the current build, these signal weights are global defaults and shall not vary by role family. Any future role-family-specific weighting must be versioned explicitly and introduced only after validated evidence justifies the extra complexity.

- **FR-RT-12 (Evidence Grounding):**
  Tailoring must map signals only to truthful candidate evidence; no fabricated claims.

- **FR-RT-12A (Intelligence Step Contract):**
  Resume tailoring shall persist structured intelligence artifacts for the current step model:
  1. Step 3 - JD Signal Map
  2. Step 4 - Evidence Map
  3. Step 5 - Elaborated SWE Context
  4. Step 6 - Candidate Resume Edits
  5. Step 7 - Verification

- **FR-RT-12B (Finalize Gate on Intelligence Artifacts):**
  In the current flow, finalize shall require valid Step 3, Step 4, and Step 7 artifacts before compile is allowed.

- **FR-RT-12B1 (Step 6 Apply Requirement):**
  Finalize shall also require a valid Step 6 candidate-edit payload. Compile is not allowed until the selected Step 6 edits have been applied to workspace `resume.tex`.

- **FR-RT-12C (Verification Decision Contract):**
  Step 7 verification shall end in one of:
  1. `pass`
  2. `fail`
  3. `needs-revision`
  and must not remain `pending` at finalize time.

- **FR-RT-12C1 (Minimum Verification Checks):**
  Step 7 verification shall at minimum evaluate:
  1. `proof-grounding`
  2. `jd-coverage`
  3. `metric-sanity`
  4. `line-budget`
  5. compile/page-readiness
  and shall record explicit notes for any failed or revision-required check.

- **FR-RT-12C2 (Current Tailoring Run Status Set):**
  For this build, `resume_tailoring_runs.tailoring_status` should use:
  1. `in_progress`
  2. `needs_revision`
  3. `tailored`
  4. `failed`
  and `resume_tailoring_runs.resume_review_status` should use:
  1. `not_ready`
  2. `resume_review_pending`
  3. `approved`
  4. `rejected`

- **FR-RT-12C3 (Run Status Transition Meaning):**
  In the current Resume Tailoring runtime:
  1. a newly bootstrapped run starts at `tailoring_status = in_progress`, `resume_review_status = not_ready`
  2. verification or finalize blockers that require human/author revision move the run to `tailoring_status = needs_revision`, `resume_review_status = not_ready`
  3. unrecoverable execution or compile failures move the run to `tailoring_status = failed`, `resume_review_status = not_ready`
  4. successful finalize/compile moves the run to `tailoring_status = tailored`, `resume_review_status = resume_review_pending`
  5. mandatory agent review moves review status to `approved` or `rejected`
  6. a later explicit owner or expert rejection may also move review status to `rejected`

- **FR-RT-12C4 (New Run on Post-Review Retailoring):**
  If the owner rejects a tailored resume and Resume Tailoring is run again for the same posting, the rerun should create a new `resume_tailoring_runs` row rather than overwriting the previous run's status history.

### 7.2.6 Tailoring Output

- **FR-RT-13 (Evidence Map):**
  System shall produce a mapping of JD signals -> resume evidence blocks.

- **FR-RT-14 (Tailored Resume Generation):**
  System shall generate a role-aligned resume variant emphasizing:
  1. Matching technical stack
  2. Relevant AI integration work
  3. Collaboration/client-facing signal when requested by JD

- **FR-RT-15 (Decision Transparency):**
  System shall provide rationale for what was emphasized and why.

- **FR-RT-15A (Scope-Checked Finalize):**
  Current finalize flow shall perform scope validation before compile in normal operation.

- **FR-RT-15A1 (Apply-Finalize-Compile Sequence):**
  In the current runtime flow, finalize shall proceed in this order:
  1. validate required Step 3 / Step 4 / Step 6 / Step 7 artifacts
  2. apply the Step 6 edit payload to workspace `resume.tex`
  3. run scope validation against `scope-baseline.resume.tex`
  4. compile PDF output
  5. verify the compiled output remains one page
  If any step fails, the tailoring run shall not be marked complete.

- **FR-RT-15B (Canonical Resume Output):**
  Current finalize flow shall compile `resume.tex` into a canonical human-facing PDF named `Achyutaram Sonti.pdf`. A convenience alias such as `resume.pdf` may also be maintained.

- **FR-RT-15C (One-Page Constraint):**
  In this build, the final tailored resume must remain one page.

### 7.2.7 Master Profile Requirement

- **FR-RT-16 (Master Profile File):**
  System shall maintain a candidate master profile artifact that captures detailed candidate background not fully present in the base resume.

- **FR-RT-17 (Master Profile Content Scope):**
  The master profile shall include elaborated work experience projects, academic projects, achievements, and other relevant accomplishments.

- **FR-RT-18 (Master Profile Usage in Tailoring):**
  Resume tailoring shall use the master profile as a primary evidence source, along with JD signals and base resume content, to improve tailoring quality while remaining truthful.

- **FR-RT-18A (Current Pantry Artifact):**
  In the current build-input pack, the source-of-truth master profile asset shall live at `assets/resume-tailoring/profile.md`. The tailoring runtime may materialize a working mirror such as `resume-tailoring/input/profile.md`, but that working copy is derived from the asset-pack source rather than acting as an independent canonical profile.

- **FR-RT-18B (Deep-Dive Evidence + Metrics Bank):**
  Current tailoring may pull from detailed project context and metrics-bank content inside the master profile when mapping JD signals to defensible resume evidence.

### 7.2.8 Base Resume Tracks and Current Editing Scope

- **FR-RT-18C (Base Resume Tracks):**
  Resume tailoring shall support multiple base resume tracks. Current known tracks include:
  1. `distributed-infra`
  2. `frontend-ai`
  3. `genai` (future/partial)

- **FR-RT-18C1 (Base Resume Track Source Rule):**
  The source-of-truth base resume track files for this build shall come from `assets/resume-tailoring/base/<track>/base-resume.tex`. Workspace `resume.tex` is a materialized working copy derived from the selected base track rather than the canonical source asset itself.

- **FR-RT-18D (Automatic Base Track Selection):**
  Resume tailoring shall automatically select the most appropriate base resume track for the application from JD/context signals rather than requiring manual base-track choice in the normal flow.

- **FR-RT-18D1 (Persist Selected Base Track):**
  The automatically selected base track shall be recorded in the application workspace metadata as `base-used` so downstream tailoring and review can see which base was chosen.

- **FR-RT-18E (Track Reframing):**
  Tailoring may rewrite summary and technical-skills content to match the selected track, remove wrong-track noise, and reorder JD-relevant tools earlier, while remaining truthful.

- **FR-RT-18F (Current Default Editable Scope):**
  Unless `meta.yaml` expands or restricts scope, the current default editable scope is:
  1. `summary`
  2. `technical-skills`
  3. `software-engineer` role inside `EXPERIENCE`

- **FR-RT-18G (Current SOP Focus):**
  The current deepest tailoring SOP is centered on the `software-engineer` experience block. Other resume sections may still be tailored, but the present detailed step discipline is strongest for that block.

- **FR-RT-18H (Deferred Scope Expansion):**
  Expansion beyond the current narrow default editing scope is deferred for a later iteration. This build should optimize the existing narrow scope before broader section-level tailoring is introduced.

### 7.2.9 Current Tailoring Method and Guardrails

- **FR-RT-19 (Current Source-of-Truth Set):**
  In this build, Resume Tailoring shall rely on the following source set unless explicitly provided additional context:
  1. job-context markdown files
  2. target `resume.tex`
  3. master profile
  4. cookbook
  5. SOP
  6. few-shot examples
  7. `meta.yaml` scope constraints

- **FR-RT-20 (JD-Only Extraction in Step 3):**
  Step 3 JD Signal Map shall be derived from JD content only and shall not be filtered by candidate evidence at extraction time.

- **FR-RT-21 (Evidence Traceability in Step 4):**
  Step 4 Evidence Map shall record traceable matches, source references, confidence, and honest gaps rather than forcing full JD coverage.

- **FR-RT-22 (Controlled Elaboration in Step 5):**
  Step 5 may elaborate relevant pipeline details only within the selected project boundary. Current elaboration output shall include:
  1. selected pipeline scope
  2. controlled elaboration
  3. claim ledger with evidence/inference labeling
  4. interview-safe narrative

- **FR-RT-22A (Current Elaboration Strictness):**
  In this build, Step 5 may perform moderate elaboration as long as it stays within the same project boundary, remains traceable to known evidence, and stays interview-safe. It should improve clarity and mapping power without inventing new project scope.

- **FR-RT-22B (Step 5 Allowed Elaboration Moves):**
  In the current build, Step 5 controlled elaboration may only:
  1. clarify an already-known project's architecture, data flow, or component interaction at a higher level of readability
  2. restate known impact, scale, latency, reliability, automation, or delivery outcomes more coherently
  3. connect already-supported technical actions to already-supported business or user outcomes
  4. compress or reorganize known evidence into an interview-safe narrative

- **FR-RT-22C (Step 5 Prohibited Elaboration Moves):**
  Step 5 shall not:
  1. introduce a new project, team, system, ownership area, customer, or production responsibility that is not already supported
  2. invent net-new metrics, technologies, integrations, or scope boundaries
  3. transform a weak inference into a direct factual claim
  4. broaden a project's blast radius beyond the selected project boundary

- **FR-RT-22D (Claim-Ledger Eligibility Rule):**
  Every Step 5 claim used for downstream tailoring shall be labeled in the claim ledger as either:
  1. `direct_evidence`
  2. `bounded_inference`
  Only claims that remain interview-safe and project-bound may survive into Step 6. If a claim cannot be defended under one of those labels, it shall not be used.

- **FR-RT-23 (Current Step 6 Payload Structure):**
  Current candidate resume edits shall be emitted as a structured payload containing:
  1. `summary`
  2. `technical-skills`
  3. `software-engineer.tech-stack-line`
  4. `software-engineer.bullets`
  5. support pointers where applicable

- **FR-RT-24 (Current SWE Bullet Contract):**
  In this build, the `software-engineer` experience edit contract requires exactly 4 bullets. Those bullets should collectively cover distinct purposes such as:
  1. scale/user impact
  2. end-to-end flow
  3. optimization tied to user-facing effect
  4. reliability/compliance/operations

- **FR-RT-25 (Bullet Construction Principle):**
  Current bullet-writing should generally lead with user, domain, or business impact, then technical action, then measurable result.

- **FR-RT-26 (Current Bullet Budget):**
  The current SWE bullet target is 210-255 characters, with hard bounds of 100-275 characters. Tailoring shall preserve overall line-budget discipline so the final PDF remains one page.

- **FR-RT-27 (LaTeX-Safe Output):**
  Tailored text shall remain LaTeX-safe. Current rules include escaping reserved characters such as `%`, `$`, `&`, `#`, and `_`, and using math-safe forms such as `$\\geq$` / `$\\leq$` when needed.

- **FR-RT-28 (Current Style Guardrails):**
  Current tailoring shall enforce the following guardrails before finalize:
  1. use numeric metric style rather than spelled-out number metrics
  2. keep summary neutral and evidence-grounded
  3. keep technical-skills items category-clean
  4. include JD-required stack terms in technical skills when truthfully supported
  5. avoid wrong-track noise that dilutes the target role signal

- **FR-RT-29 (Failure Behavior for Insufficient Evidence):**
  If evidence is insufficient, scope blocks a requested edit, or constraints conflict, Resume Tailoring shall not guess. It shall return a specific `needs-revision` or `fail` outcome with explicit blockers or revision guidance.

### 7.2.10 Learning Assets and Decision Logging

- **FR-RT-30 (Cookbook as Rule Memory):**
  Stable tailoring rules and decisions learned during manual operation should be persisted in `resume-tailoring/ai/cookbook.md` so future tailoring runs can reuse them consistently.

- **FR-RT-31 (Few-Shot Examples as Decision Memory):**
  Worked before/after tailoring examples with context and rationale should be preserved as few-shot assets so the system can inherit real manual decisions rather than re-deriving them each time.

- **FR-RT-32 (Workflow Log / Decision Trace):**
  Current tailoring workflows may also keep run-level completion or decision logs as supporting operational memory, but those logs do not replace the canonical workspace artifacts and intelligence files.

- **FR-RT-32A (Selective Knowledge-Asset Updates):**
  Cookbook and few-shot assets do not need to be updated on every tailoring run. They should be updated when a run produces a new stable rule, reusable decision pattern, or high-value worked example worth preserving.

- **FR-RT-32B (Resume Tailoring Runs Table):**
  The central database shall include a `resume_tailoring_runs` table for minimum run-level Resume Tailoring persistence. For this build, this table should at minimum capture a run identifier, linked `job_posting_id`, selected base track, current/final tailoring status, resume-review status, workspace reference, and timestamps.

## 7.3 Email Outreach Component FRs

### 7.3.1 Subcomponent Responsibilities

- **FR-EO-00 (Contact Search Responsibility):** The Outreach-side discovery layer shall own company-scoped people search for role-targeted leads when the upstream lead itself does not already provide enough internal contacts.
- **FR-EO-00A (Selected-Contact Enrichment Responsibility):** The Outreach-side discovery layer shall own selected-contact enrichment after the broad people-search pass, including fuller identity recovery, LinkedIn URL recovery, and usable-email recovery when the selected enrichment provider can supply them.
- **FR-EO-00B (Recipient-Profile Extraction Responsibility):** When a selected contact has a usable LinkedIn profile URL, the Outreach-side discovery layer shall own extracting and persisting as much clean workflow-relevant recipient-profile context as is actually exposed on the public page for later drafting use.
- **FR-EO-01 (Email Discovery Responsibility):** The Email Discovery subcomponent shall own person-scoped email lookup or enrichment, provider-budget tracking, discovery confidence, persistent discovery history, and future learning-data collection.
- **FR-EO-02 (Discovery Boundary):** The Email Discovery subcomponent shall not own email sending. It may consume delivery outcomes such as bounce feedback, but it does not originate send operations.
- **FR-EO-03 (Email Drafting and Sending Responsibility):** The Email Drafting and Sending subcomponent shall own outreach draft generation, attachment of the tailored resume, send execution, and persistence of the final sent content plus raw send metadata needed for downstream feedback tracking.
- **FR-EO-04 (Delivery Feedback Responsibility):** The Delivery Feedback subcomponent shall own normalization and persistence of post-send outcomes, such as sent / bounced / not-bounced / replied states, so those outcomes can be reviewed by the user and consumed by Email Discovery as feedback where appropriate.
- **FR-EO-05 (Subcomponent Feedback Loop):** Delivery Feedback shall feed post-send outcomes back into Email Discovery without collapsing the ownership boundary between send execution and discovery logic.

### 7.3.2 Email Discovery Subcomponent FRs

#### 7.3.2.1 Current Provider-Based Discovery

The current discovery behavior combines:
1. company-scoped people search to identify likely internal contacts for a posting
2. person-scoped email enrichment or email-finder lookup for selected contacts that still need usable work emails

It uses the active provider cascade to identify contacts, discover emails, capture provider-verified confidence signals, track budget usage, preserve bounce/outcome feedback, and collect the data needed for future learning.
For discovery-state persistence, the system shall use discovery-specific tables inside the central SQLite database rather than splitting long-lived discovery data across multiple JSON/JSONL files.
- **FR-ED-00 (Discovery Source of Truth):** Discovery-side persistent history, provider budget tracking, unresolved review data, bounced-email review data, and future learning state shall live inside `job_hunt_copilot.db`. JSON artifacts such as `discovery_result.json` and `delivery_outcome.json` shall be treated as runtime handoff outputs for pipeline communication rather than canonical long-term storage.
- **FR-ED-00A (Company-Scoped People Search Entry):** For role-targeted postings that still need internal contacts, the discovery layer shall accept company/job context and run company-scoped people search before person-scoped email-finder calls.
- **FR-ED-00B (Apollo-First Contact Search):** The current first-build company-scoped people-search provider shall be Apollo.
- **FR-ED-00B1 (Company Resolution Before Apollo People Search):** The Apollo path should first resolve the target company to an Apollo organization record and capture the resolved `organization_id` before broad people search begins.
- **FR-ED-00B2 (Organization-ID-Anchored Search):** When Apollo organization resolution succeeds, people search should anchor on the resolved `organization_id` rather than relying only on company name or raw domain filters.
- **FR-ED-00B3 (Company Resolution Artifact):** The people-search stage shall persist the resolved company-search outcome, including the chosen Apollo organization record when found, inside `people_search_result.json` so later review can see what company identity was actually searched.
- **FR-ED-00C (Role-Targeted Search Filters):** Company-scoped people search should use the resolved company context plus title, function, and seniority filters derived from the JD and current outreach priorities. Engineering managers, recruiters, and role-relevant engineers are the primary target classes.
- **FR-ED-00D (People-Search Materialization):** Company-scoped people-search results shall first persist the broad-search output in `people_search_result.json`. Canonical `contacts` and posting-contact links shall be created or updated only for shortlisted candidates that proceed into enrichment, identity clarification, or later outreach handling, even when a usable email is not yet available.
- **FR-ED-00D0 (Shortlist-Stage Canonical Materialization):** When shortlist-time materialization occurs, stable provider identity such as Apollo person ID is sufficient for creating the canonical contact and posting-contact link even before a non-obfuscated full name is known.
- **FR-ED-00D3 (Terminal Enrichment-Failure Cleanup):** If a shortlisted candidate fails enrichment in a way that makes the candidate unusable for the current build and the candidate will not continue into email discovery or outreach, the current posting-contact link shall be removed. If the linked canonical `contact` was created only for that shortlist candidate and is not reused elsewhere, that contact row shall also be removed instead of being retained as dead canonical state.
- **FR-ED-00D1 (Search-Stage Sparsity Handling):** The Apollo search stage may return sparse candidate data such as partial or obfuscated display names, title, freshness metadata, and capability flags like `has_email` without returning a real email value. The system shall preserve that sparse result shape rather than assuming search always yields a full profile.
- **FR-ED-00D2 (Best-Known Name Materialization Rule):** When people search returns only a sparse display name, the contact record shall still preserve the best currently known human-readable name string as `display_name`, and may leave `full_name` empty until enrichment or another source reveals the non-obfuscated full name.
- **FR-ED-00E (Skip Extra Email Lookup on Usable Provider Email):** If the selected people-search or enrichment provider already returns a usable work email for a selected contact, the system may skip separate person-scoped email-finder calls for that contact.
- **FR-ED-00E1 (Selective Apollo Enrichment After Search):** After the broad Apollo search pass, the system should enrich only the shortlisted contacts that need fuller identity, LinkedIn URL, or a usable work email. It should not bulk-enrich every broad-search candidate by default.
- **FR-ED-00E2 (Search-To-Enrichment Boundary):** Apollo Search is the high-recall candidate-generation step. Apollo enrichment is the identity-clarification and optional email-returning step for selected contacts.
- **FR-ED-00E2A (Enrichment-To-Email-Discovery Boundary):** Person-scoped email discovery shall begin only when shortlist-time enrichment has completed for that contact and still did not return a usable work email. Enrichment alone does not hand a contact into email discovery if it already produced a usable email.
- **FR-ED-00E3 (Search-Stage Recipient Typing):** The search stage should infer a preliminary `recipient_type` and `relevance_reason` from the returned title and job context, such as `recruiter`, `hiring_manager`, `engineer`, or `other_internal`, before later ranking or wave selection narrows the final outreach set.
- **FR-ED-00E4 (LinkedIn-URL-Driven Profile Extraction):** When enrichment yields a LinkedIn profile URL for a selected contact, the system may use that URL to extract as much clean public profile context as is actually visible and useful before drafting begins.
- **FR-ED-00E5 (Recipient-Profile Snapshot Scope):** LinkedIn-profile extraction should persist a structured public-profile snapshot that keeps useful identity fields, top-card fields, about preview, experience hints, recent public activity, visible public signals, and grounded work signals when they are actually exposed. It should not attempt to persist unrelated personal data or invent hidden/member-only fields.
- **FR-ED-00E6 (Recipient-Profile Artifact Persistence):** Extracted LinkedIn-profile context shall be persisted as a recipient-profile artifact linked to the canonical `contact_id` so drafting can consume a stable internal snapshot rather than refetching the live profile during generation.
- **FR-ED-00E7 (LinkedIn-Profile Extraction Failure Tolerance):** If a selected contact lacks a LinkedIn URL, or LinkedIn-profile extraction fails, the contact may still continue through email discovery and drafting using the best available sparse recipient context from search and enrichment. Missing LinkedIn-profile context alone does not block outreach.
- **FR-ED-00E8 (Email Outcome After Enrichment):** If Apollo enrichment does not return a usable work email for a selected contact, the system shall continue into the separate person-scoped email-discovery path for that contact rather than treating the enrichment step as final failure.
- **FR-ED-00F (Autonomous People-Search Breadth):** For the autonomous LinkedIn-alert mode, the initial Apollo search should prefer high recall over narrow precision so the system can collect a broad internal contact set before later ranking or pacing decisions.
- **FR-ED-00G (Autonomous Helpful-Contact Scope):** The autonomous search set is not limited to one exact title. It should include any role-relevant internal people who might realistically help route the candidate to the right hiring person.

- **FR-ED-01:** System shall accept either company/job context for people search or explicit per-contact identity for each selected contact, such as name + company name, LinkedIn URL, or provider-scoped person ID.
- **FR-ED-01A (Internal Domain Resolution):** When provider lookup requires a company domain, Email Discovery shall resolve or derive the domain internally from the available company context before running the provider cascade.
- **FR-ED-01A1 (Reuse Saved Resolved Company Domain):** If `people_search_result.json` already contains a resolved company record with `primary_domain`, person-scoped Email Discovery shall reuse that saved domain before falling back to source-URL parsing or weaker derivation heuristics.
- **FR-ED-01B (Domain Unresolved Outcome):** If Email Discovery cannot resolve a usable company domain for a provider path that requires it, the system shall record a distinct `domain_unresolved` outcome rather than collapsing that case into generic `not_found`.
- **FR-ED-01C (Continue Other Provider Paths):** A `domain_unresolved` condition shall block only the provider paths that require domain input. Email Discovery shall still continue through any remaining provider paths that can operate using company name or other available context.
- **FR-ED-01D (Provider-Owned Input Eligibility):** The discovery loop shall not globally skip a provider only because `company_domain` is absent. If a provider can still operate using other supported inputs, such as `linkedin_url`, provider-scoped identity, or company name, the provider shall still be called and allowed to determine whether the available input set is sufficient.
- **FR-ED-02:** System shall run provider cascade with ordered fallbacks.
- **FR-ED-02A (Stop on First Successful Discovery):** If a provider returns a usable email candidate, Email Discovery shall stop the provider cascade for that contact instead of continuing to spend credits on additional providers in the same run.
- **FR-ED-02B (Post-Bounce Fallback):** If a discovered email is later observed as bounced, the system may re-enter provider-based discovery for that contact in a later attempt using remaining providers or a fresh cascade run.
- **FR-ED-02C (Usable Candidate Definition):** For this build, a returned provider email candidate is sufficient to count as a usable discovery result and stop the cascade. Provider verification/confidence metadata shall still be stored and used for confidence reporting, but it is not required to continue spending credits in the same cascade once an email has been returned.
- **FR-ED-02D (Skip Prior Bounced Provider on Retry):** If discovery is retried for a contact after a bounced email outcome, the next provider-based attempt shall skip the provider that previously produced the bounced email rather than restarting from that same provider.
- **FR-ED-02E (Per-Contact Provider Exhaustion Limit):** For this build, Email Discovery may retry a contact across the available provider set, but once all three providers have been exhausted for that contact without yielding a non-bounced result, discovery shall stop for that contact and surface the case to the user for review.
- **FR-ED-02F (Exact Bounced Email Rejection):** If a provider returns the exact same email address that already produced a bounced outcome for that contact, Email Discovery shall treat that candidate as already failed and shall not retry or reuse it.
- **FR-ED-02G (No Pattern Reuse Across Contacts Yet):** In this build, Email Discovery shall not use one discovered email at a company to infer or generate emails for other contacts at that same company. Company-level reuse of discovered patterns is deferred to the future Email Pattern Learning Engine.
- **FR-ED-02H (No Separate Reporting Layer for Stored Discovery Context):** If discovery history already exists in `job_hunt_copilot.db`, the system does not need a separate reporting mechanism for that context. Stored discovery data itself is the lookup source that AI can read when needed.
- **FR-ED-02I (Reuse Known Working Email for Same Contact):** If `job_hunt_copilot.db` already contains a known working email outcome for the same contact, Email Discovery shall reuse that stored working email directly and skip new provider calls for that contact.
- **FR-ED-02J (Identity Clarity Requirement for Reuse):** Reuse of a stored working email is allowed only when AI can clearly identify that the current lead refers to the same contact using the available distinguishing information. AI shall use any non-common identifying context available for that person, such as LinkedIn URL, position title, location, or other unique profile context. If identity remains ambiguous, Email Discovery shall not auto-reuse the stored working email.
- **FR-ED-02K (Fresh Lookup on Identity Ambiguity):** If a stored working email exists for a possible contact match but identity is not clear enough to confirm it is the same person, Email Discovery shall not rely on that stored email and shall proceed with a fresh provider-based lookup for the current contact.
- **FR-ED-02L (Create New Contact Record on Unresolved Identity):** If a fresh provider-based lookup is performed for an ambiguously matched contact and the resulting information still cannot be confidently tied to an existing contact record, the system shall create a new contact record rather than merging it into a possible existing match.
- **FR-ED-03:** System shall return best candidate email with confidence/verification metadata using provider-verified status as the pre-send validity signal.
- **FR-ED-04:** System shall persist discovery attempts/outcomes for later analysis and cache improvement.
- **FR-ED-05 (Email-Finder Registry and Budget Scope):** Person-scoped email discovery shall operate with the current email-finder registry: `prospeo`, `getprospect`, and `hunter`.
- **FR-ED-06 (Per-Provider + Combined Budget):** System shall track both per-provider remaining credits and a derived combined total from known available provider balances.
- **FR-ED-06A (Unknown Balance Representation):** If a provider does not expose a reliable account-balance signal, or the balance cannot be retrieved successfully at the time of update, the system shall store that provider's remaining-credit value as `unknown`/`NULL` rather than inventing or guessing a numeric value.
- **FR-ED-06B (No Synthetic Budget Values):** The system shall not persist placeholder or sentinel values such as `-1` into canonical provider budget state. Canonical budget values must come from provider response metadata, provider account endpoints, or remain `unknown`.
- **FR-ED-07 (Monthly Budget Cycle):** Budget tracking shall assume monthly quota renewal for each provider and persist reset metadata (for example, `next_quota_renewal_date`) when available from provider APIs.
- **FR-ED-08 (Automatic Budget Updates):** Budget state shall be updated automatically after every provider usage event using provider response metadata and/or provider account endpoints when those provider signals are available.
- **FR-ED-08A (Best-Effort Budget Refresh):** For providers that expose free or low-cost account-information endpoints, the system should refresh canonical budget state from those endpoints after usage events. For providers without such support, canonical budget state may remain `unknown` while budget events still record usage deltas.
- **FR-ED-09 (Provider Exhaustion Fallback):** When one provider is exhausted or rate-limited, cascade shall continue with remaining providers in order.
- **FR-ED-10 (Verification Credit Accounting):**
  1. Prospeo and GetProspect discovery calls use their provider account credits and return provider-verified status for pre-send confidence.
  2. Hunter has separate search and verification pools; discovery uses Hunter search credits, and optional Hunter verifier calls use Hunter verification credits.
- **FR-ED-11 (Budget State Persistence):** System shall persist provider budget state and provider budget event history inside the main discovery SQLite dataset rather than in separate JSON/JSONL files.
- **FR-ED-11A (Budget Tracking Tables):** For this build, the main discovery SQLite dataset shall include dedicated budget-tracking tables such as `provider_budget_state` and `provider_budget_events`.
- **FR-ED-14 (Post-Send Delivery Validation):** System shall use bounce feedback as the final delivery validity check for sent emails.
- **FR-ED-14A (Bounced Email Reviewability):** Bounced email outcomes shall be stored in a retrievable form so the user can later review all bounced emails together and decide what corrective action to take.
- **FR-ED-14B (Bounced Email Dual Use in One Store):** Bounced email outcomes shall be stored once in the main discovery SQLite dataset and made available both for learning/history use and for later manual review through a dedicated review view.
- **FR-ED-15 (Discovery Confidence Model):** Before send, confidence is based on provider verification; after send, confidence is upgraded to 100% only when the sent email is observed as non-bounced within the configured bounce-check feedback window.
- **FR-ED-16 (Ambiguous Domain Stop Behavior):** If a domain remains ambiguous after the allowed provider-assisted attempts, the tool shall stop discovery for that domain only, surface the ambiguity to the user, and continue processing other domains in the same run if any exist.
- **FR-ED-17 (Unresolved Contact Handling):** Unresolved contacts shall be set aside for later review instead of being automatically retried by the cache in the same run.
- **FR-ED-18 (Unresolved Contact Audit Details):** For each unresolved contact, the system shall persist:
  1. which providers were attempted
  2. whether an email was found
  3. if an email was found, whether it later bounced
  4. a short unresolved reason (for example: `not_found`, `bounced`, `ambiguous_domain`, `domain_unresolved`)
- **FR-ED-19 (Unresolved Contact Review View):** Unresolved contacts shall be queryable from the main SQLite dataset through a dedicated review-oriented view or equivalent filtered retrieval path rather than requiring a separate JSON artifact.
- **FR-ED-19A (Bounced Email Review View):** The system shall maintain a dedicated bounced-email review view or equivalent filtered retrieval path on top of the main SQLite dataset so bounced contacts can be listed and revisited later without introducing a separate JSON artifact.

#### 7.3.2.2 Future Email Pattern Learning Engine

The Email Pattern Learning Engine is the future learning subsystem inside the Email Discovery Component.
It will learn domain-wise email naming behavior from provider-assisted discoveries and post-send outcomes,
then reuse that learned behavior to reduce provider dependency and save credits over time.
For the current scope, the system shall focus on collecting and storing the training data required for this engine.
The engine itself is not required to be implemented yet and shall be built later when the user decides enough training data has been collected.
- **FR-ED-12 (Pattern Learning Data Preservation):** System shall preserve provider-assisted discovery results and post-send outcomes in a form that can later be used to build the Email Pattern Learning Engine.
- **FR-ED-12A (Deferred Company-Level Pattern Reuse):** Reuse of company-level email patterns across multiple contacts is explicitly deferred until the Email Pattern Learning Engine is implemented. For now, the system shall only collect and preserve the data needed for that future behavior.
- **FR-ED-13 (Future Provider-Independent Discovery Readiness):** After sufficient high-quality pattern data is collected and the user chooses to build the Email Pattern Learning Engine, the system shall support high-confidence discovery using learned patterns without requiring provider calls for every lookup.
- **FR-ED-13A (User-Driven Engine Build Timing):** The timing for implementing the Email Pattern Learning Engine is user-driven rather than phase-fixed. The current requirement is to preserve the data needed to build it later once the user decides the dataset is sufficient.
- **FR-ED-13B (Training Sufficiency Decision Deferred):** The threshold for what counts as "enough training data" is intentionally left open for later user decision and is not fixed in the current specification.
- **FR-ED-20 (Training Dataset Update Timing):** The Email Pattern Learning Engine training dataset shall be updated immediately after each relevant discovery/send outcome event.
- **FR-ED-21 (Training and Testing Cadence):** Model training and testing for the Email Pattern Learning Engine shall be performed as a separate evaluation activity at the end of the defined collection window (currently: one week).
- **FR-ED-22 (Collection Window Policy):** The current collection window shall be a rolling 7-day window that begins when the user explicitly starts collection for that training cycle.
- **FR-ED-23 (Master Dataset Structure):** The Email Pattern Learning Engine shall use one long-term discovery/training dataset within `job_hunt_copilot.db` rather than one large JSON artifact or one file per collection window.
- **FR-ED-23A (Discovery Storage Coverage):** The discovery-related portion of `job_hunt_copilot.db` shall cover discovery/training history, provider budget tracking, unresolved review data, bounced-email review data, and future learned pattern state within the same storage system.
- **FR-ED-24 (Window Tracking Table):** The central database shall include a `windows` table so collection windows can be tracked with clear start and end timestamps. Training records shall link to their collection window using `window_id`.
- **FR-ED-24A (Minimal Windows Table Fields):** For this build, the `windows` table only needs these core fields: `window_id`, `window_start`, `window_end`, and `status`, where `status` indicates whether the window is currently `active` or `closed`.
- **FR-ED-25 (Discovery-to-Send Expectation):** If an email is discovered, the system shall treat that discovery as send-intended. The workflow should avoid collecting discovered emails that are not expected to proceed to send, so discovery effort is not wasted.
- **FR-ED-26 (Discovery Attempts Table):** The central database shall include a dedicated `discovery_attempts` table for attempt-level discovery/send records rather than storing only final resolved outcomes.
- **FR-ED-26A (No-Result Attempt Storage):** The `discovery_attempts` table shall also store attempts where no email candidate was found so provider coverage gaps and unresolved discovery outcomes are preserved for later analysis.
- **FR-ED-26B (No-Result Attempt Representation):** When no email is found for a contact, the corresponding `discovery_attempts` row shall preserve all available attempt context and record the outcome as `not_found` so the system can recognize that email discovery was difficult for that contact.
- **FR-ED-26C (Cascade-Level Attempt Granularity):** The `discovery_attempts` table shall store one row per completed discovery cascade for a contact, not one row per individual provider step. The row shall capture the final cascade outcome and, when successful, the provider that ultimately returned the discovered email.
- **FR-ED-26D (Provider and Credit Simplicity):** For this build, `discovery_attempts` only needs to store the provider that produced the final cascade result. Provider credit usage shall be tracked separately through the budget-tracking tables in the same SQLite dataset rather than inside each discovery row.
- **FR-ED-26E (Attempt Timestamp Field):** Each `discovery_attempts` row shall store a lightweight attempt timestamp such as `created_at` so discovery history can be ordered and analyzed over time.
- **FR-ED-26F (Discovery History as Training Data):** `discovery_attempts` shall serve both as the operational discovery-history table and as the primary raw training-data source for the future Email Pattern Learning Engine.
- **FR-ED-27 (Attempt History Preservation):** The dataset shall preserve which candidate emails did not work and which final email ultimately worked for a person/domain when that history exists.
- **FR-ED-27A (No Overwrite of Attempt History):** Repeated discovery cascades for the same contact shall create additional `discovery_attempts` rows instead of overwriting earlier rows so failed and successful histories are both preserved.
- **FR-ED-27B (Outcome Labeling for Candidate History):** When multiple different email candidates exist for the same contact across attempts, the system shall preserve all of them in history and explicitly mark which candidates became invalid (for example, bounced) and which candidate, if any, became the working email.
- **FR-ED-27C (Stop Discovery After Working Email):** Once a contact has a working email outcome, provider-based discovery shall be considered complete for that contact and shall not continue again unless the user explicitly asks for a retry.
- **FR-ED-28 (Contacts Table and Attempt Linking):** The central database shall include a `contacts` table. Attempt records in `discovery_attempts` shall be linked to the correct person using a stable machine-oriented `contact_id`.
- **FR-ED-28A (Minimal Contacts Table Scope):** For this build, the `contacts` table shall primarily store identity and disambiguation fields, plus lightweight latest-state fields such as current working email, top-level contact lifecycle status, and lightweight discovery summary fields when useful. Detailed historical attempt data shall remain in `discovery_attempts`.
- **FR-ED-28B (Lightweight Discovery Summary on Contact):** In addition to the top-level contact lifecycle status, the `contacts` table may also store a lightweight discovery-specific summary or reason field for the contact, such as `working_email_found`, `all_providers_exhausted`, or `identity_ambiguous`, while detailed history remains in `discovery_attempts`.
- **FR-ED-28C (Latest-State Contact Status):** The lightweight discovery status stored on a contact shall represent the latest known high-level state for that contact. Historical state transitions shall remain in `discovery_attempts` rather than being stored as multiple concurrent contact-status values.
- **FR-ED-28D (Current Working Email on Contact):** If a contact has a known working email, the `contacts` table shall store that current working email directly for efficient lookup, while `discovery_attempts` remains the source of detailed historical attempt data.
- **FR-ED-29 (Two-Key Identity Model):** The dataset shall use:
  1. `identity_key` for deterministic lookup
  2. `contact_id` for unique contact-instance linkage
  Provider secondary identifiers such as Apollo person ID and LinkedIn URL shall be stored on the contact when available because they may be the strongest stable identity signals for retrieval and deduplication.
- **FR-ED-30 (Identity Key Generation Policy):** `identity_key` shall be created using the strongest deterministic identifier available in this priority order:
  1. normalized LinkedIn profile URL when available
  2. normalized provider-scoped person key such as `apollo:{provider_person_id}` when a stable provider person ID exists
  3. hash of normalized company name plus normalized full name as the fallback path when stronger identifiers are absent
  The same chosen identity source must always produce the same `identity_key` so the key can be recomputed later for dataset lookup.
- **FR-ED-31 (Contact ID Uniqueness Policy):** `contact_id` shall be a unique machine identifier for one specific contact instance. Multiple contact records may share the same `identity_key` if they represent same-name conflicts at the same company.
- **FR-ED-32 (Normalization Rules for Identity Key):** Before generating `identity_key`, the chosen identity source shall be normalized using these rules:
  1. for LinkedIn URL identity:
     - convert to lowercase
     - trim leading and trailing whitespace
     - strip the URL scheme such as `http://` or `https://`
     - strip a trailing slash when present
  2. for provider-person identity:
     - convert provider name to lowercase
     - trim leading and trailing whitespace from both provider name and provider person ID
     - preserve the provider person ID content after trimming
  3. for fallback company-name + full-name identity:
     - convert to lowercase
     - trim leading and trailing whitespace
     - collapse repeated internal whitespace to a single space
     - preserve character order after normalization
- **FR-ED-33 (Contact ID Generation Policy):** `contact_id` shall be created using one deterministic dataset rule:
  1. compute `identity_key`
  2. assign a per-`identity_key` contact instance sequence number starting at `1`
  3. create `contact_id` from hash of `identity_key` plus the assigned sequence number
  The assigned sequence number must be persisted so the same contact instance keeps the same `contact_id` across future updates.
- **FR-ED-34 (Stored Email Features):** Each attempt record shall store the full email address, `email_local_part`, and `detected_pattern` as separate fields so the raw fact and the derived learning features are both preserved.
- **FR-ED-35 (Provider Verification Features):** Each attempt record shall also store provider verification/confidence fields such as provider verification status and provider score when available.
- **FR-ED-36 (Minimal Bounce Outcome Storage):** For this build, attempt records only need a minimal bounce outcome field indicating whether the email bounced. Detailed bounce metadata is not required.
- **FR-ED-37 (Provider Audit Field):** Each attempt record shall store the provider name that produced the final cascade result for audit and later analysis, even if provider identity is not used as a training feature.
- **FR-ED-38 (Stored Identity and Disambiguation Fields):** Each attempt or contact snapshot shall store `display_name`, `first_name`, `last_name`, `full_name`, `linkedin_url`, `position_title`, `location`, `provider_name`, `provider_person_id`, and `name_quality` when available. These fields support identity lookup and same-name disambiguation. Full LinkedIn profile text is not required in the Email Pattern Learning Engine dataset.
- **FR-ED-39 (Lookup and Disambiguation Behavior):** When retrieving stored data for a person, the system shall use the strongest available identifier in this order:
  1. `linkedin_url`
  2. provider-scoped person ID such as Apollo person ID
  3. company name plus full name
  Then it may use `position_title`, `location`, and other profile context as disambiguation fields when needed.

### 7.3.3 Email Drafting and Sending Subcomponent FRs

- **FR-EM-01:** System shall generate outreach per contact using the relevant available context for that outreach mode.
- **FR-EM-01A (Dynamic Subject Line Generation):** Drafting shall explicitly generate a subject line as part of the outreach draft. Subject lines should remain dynamic rather than fixed-form, while generally staying short, relevant, easy to scan, non-spammy, and aligned with recipient type and available personalization signals.
- **FR-EM-01B (Single-Draft Mode):** For this build, the subcomponent only needs to generate one final outreach draft per contact rather than producing multiple candidate drafts for selection or ranking.
- **FR-EM-01B1 (Current Posting-Frontier Draft Start Gate):** In the current role-targeted flow, draft generation for a posting may begin as soon as individual untouched contacts become ready after the posting-level prerequisites are satisfied. The build does not wait for one fixed send set to become fully ready before drafting starts.
- **FR-EM-01B2 (Frontier Draft Before Send Rule):** In the current role-targeted flow, the system shall persist drafts for the currently ready untouched posting frontier before those individual contacts are eligible for automatic sending. Sending then consumes that drafted frontier through the active send-slice and pacing rules.
- **FR-EM-01B3 (Partial Frontier Continuation Rule):** If one or more contacts in the current ready posting frontier fail draft generation, the successfully generated drafts from that same frontier may still proceed into sending. Failed draft cases shall be surfaced for review rather than blocking the successful drafts in that frontier.
- **FR-EM-01C (Pacing-Aware Per-Contact Sending):** For this build, Email Drafting and Sending may still operate per discovered contact, but actual send execution shall respect the active pacing and throttling decisions produced by orchestration.
- **FR-EM-01D (Role-Targeted Draft Inputs):** For role-targeted outreach, draft generation shall explicitly use job-posting context, recipient profile context, and the tailored resume as core inputs.
- **FR-EM-01D1 (Recipient-Profile Artifact Preference):** When `recipient_profile.json` or equivalent persisted recipient-profile context exists for the selected contact, draft generation shall use that persisted snapshot as the primary recipient-profile input rather than refetching the live profile at draft time.
- **FR-EM-01D2 (Sparse-Context Drafting Fallback):** When only sparse search or enrichment context exists for the selected contact and no richer recipient-profile snapshot is available, drafting shall fall back to title, team/work-area, and role proximity signals. It shall not invent person-specific background hooks.
- **FR-EM-01E (General Learning-Outreach Inputs):** For general outreach not tied to a specific job posting, draft generation shall primarily use recipient profile context and sender background context. A tailored resume is not required input for this mode.
- **FR-EM-02 (Mandatory Resume Attachment for Role-Targeted Outreach):** Role-targeted outreach shall always attach the relevant tailored resume for the outreach being sent.
- **FR-EM-02A (Optional Resume Mention in Body):** The draft may mention the attached tailored resume when it fits naturally, but the email body shall not be forced to explicitly call out the attachment in every case.
- **FR-EM-02B (Resume-Only Attachment Scope):** For this build, when a resume attachment is used, the only required attachment is the tailored resume. Additional file attachments are not required.
- **FR-EM-02C (No Resume Required for General Learning Outreach):** For general outreach that is not tied to a specific job posting, resume attachment is not required. That outreach should behave as curiosity-led learning outreach rather than as a direct role-application email.
- **FR-EM-03:** For this build, Email Drafting and Sending shall operate autonomously without requiring human review or approval before send.
- **FR-EM-03A (Final Draft Persistence Focus):** For this build, the drafting subcomponent only needs to persist the final generated draft rather than storing every intermediate generated draft version.
- **FR-EM-03B (Initial Outreach Scope Only):** For this build, the Email Drafting and Sending subcomponent only needs to generate the initial outreach email. Follow-up email drafting remains manual/user-owned for now.
- **FR-EM-03C (Standard Signature Block):** Drafts shall include a standard sender signature block containing the sender's name, LinkedIn URL, phone number, and email address.
- **FR-EM-03D (Shared Signature):** For this build, the same signature block may be used across recipient types. Recipient-specific signature variation is not required yet.
- **FR-EM-03E (Signature Source of Truth):** The actual signature values shall be sourced from the candidate master profile or equivalent runtime configuration rather than hardcoded into the specification itself.
- **FR-EM-03F (Pacing-Aware Send Execution):** For this build, once the relevant drafts for ready untouched contacts have been generated and persisted, the subcomponent may execute sends without a separate manual send trigger or mandatory pre-send draft approval, but only when the current active send-slice, per-posting daily-cap, and inter-send pacing rules allow each send at that time.
- **FR-EM-03F1 (Transient Send Failure Retry Rule):** In the current Gmail-backed role-targeted automatic sending flow, clearly transient auth or transport failures, such as DNS resolution failures, connection timeouts, or temporary token-endpoint connectivity failures, shall not be persisted as terminal recipient failures. Instead, the system shall keep the same outreach message, mark it `blocked`, stop the current posting wave immediately, and retry that same message later.
- **FR-EM-03F2 (Transient Send Cooldown And Retry Bound):** The current build shall wait 15 minutes before retrying a transient blocked role-targeted send, and it shall allow up to 3 automatic retries for that same message. Once that retry bound is exhausted, the message shall remain `blocked` and reviewable rather than being converted into a terminal `failed` recipient outcome.
- **FR-EM-03F3 (Posting-Scoped Retry Continuation Rule):** While a transient blocked role-targeted send remains within its automatic retry budget, the posting shall remain `outreach_in_progress` and the durable run shall remain at `sending` so later heartbeats can resume from that same message once the cooldown expires.
- **FR-EM-03G (Persist Final Sent Content):** The system shall persist the exact final sent subject and body for each outreach email so the user can later inspect what was actually sent.
- **FR-EM-03H (Persist Final Rendered HTML):** When rich HTML formatting is used, the system shall also persist the final rendered HTML version that was sent so later review can reflect the real recipient-facing rendering.
- **FR-EM-03I (No Extra Body Links by Default):** For this build, the email body does not need to include additional portfolio, GitHub, or project links beyond the standard signature/contact information unless a later design decision explicitly adds them.
- **FR-EM-03J (Outreach Messages Table):** The central database shall include an `outreach_messages` table as the minimum canonical store for generated/sent outreach messages. For this build, it should at minimum capture an outreach-message identifier, required `contact_id`, optional `job_posting_id`, final sent subject, final sent body, final rendered HTML when applicable, delivery-tracking identifier or thread ID when available, and send timestamp.
- **FR-EM-03K (Ambiguous Repeat-Outreach Review):** If the same contact already has prior outreach history and the correct next action depends on interpreting what was already sent, the system shall not auto-decide a new outreach message. It shall surface the case to the user for review.
- **FR-EM-03L (Manual Follow-Up Tracking Scope):** Follow-up email drafting remains manual/user-owned for now, but the system should still track enough outreach state to support later follow-up decisions, such as recipient type, outreach mode, follow-up state, last touch date, next follow-up date, and notes.
- **FR-EM-03M (Current Follow-Up Cadence Guidance):** For the current outreach guide, the working follow-up cadence should be roughly one week between follow-ups, with a maximum of 3 follow-ups, and follow-up should stop once the person replies.
- **FR-EM-03N (No Automatic Follow-Up Send):** The current follow-up cadence guidance is tracking and policy guidance only. The system shall not auto-generate or auto-send follow-up emails in this build unless the user later expands scope explicitly.
- **FR-EM-04:** System shall send outreach and track delivery outcomes such as sent, bounced, not-bounced, and replied states.
- **FR-EM-05 (High-Impact Draft Objective):** Email drafts shall be written to capture the recipient's attention, sustain interest through the message, and maximize the chance of earning at least a quick follow-up conversation.
- **FR-EM-05A (Early Attention Window):** The opening of the email shall be optimized for the first few seconds of reader attention. The early lines should give the recipient a concrete reason to keep reading rather than opening with generic self-introduction.
- **FR-EM-05B (Strong Work-Led Hook):** For outreach that references the recipient's work, the opening hook should be strong enough to stand out from generic applicant messages by combining something specific about the recipient's work, a grounded note of appreciation when appropriate, and a credible reason the sender wants to learn more.
- **FR-EM-05C (JD-Central Hook Preference):** For role-targeted outreach, the opening hook shall prefer technically central JD responsibilities, systems themes, or stack signals over weaker operational-support or boilerplate responsibilities. Clauses such as `UAT`, `after go-live`, or other secondary support language shall not become the lead hook unless the role is clearly operations-heavy.
- **FR-EM-05D (JD-Faithful Focus Compression Rule):** When the opening compresses or summarizes JD language, it shall remain faithful to the JD and shall not widen a narrower backend/full-stack signal into a broader abstraction that the JD does not clearly support.
- **FR-EM-06 (Draft Input Grounding):** Draft generation shall be grounded in the relevant context for the current outreach mode rather than relying on generic generation alone.
- **FR-EM-06A (No Raw JD-Boilerplate Leak Rule):** Role-targeted outreach shall not paste raw JD boilerplate, marketing copy, or long employer-branding language directly into live emails. JD grounding should be summarized into concise, human-sounding role-relevant hooks instead.
- **FR-EM-07 (Lead-Profile Personalization):** The subcomponent shall extract personalization hooks from the contact's available profile context, especially LinkedIn-derived information such as role, work, projects, posts, focus areas, or other distinctive details that can help make the outreach feel thoughtful and specific.
- **FR-EM-07A (Primary Personalization Hook Selection):** The draft should usually anchor on one strongest personalization hook rather than trying to mention too many things at once. A second hook may be used when it naturally reinforces the first without making the message feel crowded.
- **FR-EM-07B (Work-Centric Opening Hook):** When a draft intentionally uses recipient-profile-driven personalization, the opening should reference something specific about the recipient's present or past work that genuinely caught the sender's attention or triggered curiosity to learn more. This work-centric hook should be used to create connection before transitioning into fit or ask.
- **FR-EM-07C (Specific Appreciation in Hook):** The work-centric opening may include a small amount of specific appreciation or praise when it is grounded in a real observation about the recipient's work and helps strengthen the hook. The appreciation should feel earned and restrained rather than generic.
- **FR-EM-07D (Recipient-Profile-First Hooking):** In recipient-profile-driven variants such as imported legacy playbooks, the hook should prefer the recipient's own LinkedIn-derived present work, past work, projects, or other person-specific profile signals before falling back to broader team or role context. The outreach should feel person-to-person rather than driven primarily by generic team language.
- **FR-EM-07E (Overlap-First Hook Construction):** When a recipient-profile-driven hook is used and a credible overlap exists between the recipient's work and the sender's background or interests, the hook should center that overlap. When no meaningful overlap exists, the opening may still center the recipient's work with light, grounded appreciation and curiosity to learn more.
- **FR-EM-07F (Technical-Signal Preference in Hooking):** When choosing among available recipient-profile signals for a recipient-profile-driven hook, the draft should prefer technical, product, system, or problem-space work over generic managerial or recruiting activity. The opening should not rely on praise of hiring or management behavior unless no stronger person-specific work signal exists.
- **FR-EM-08 (Reader-Centric Framing):** The draft shall be framed around why the recipient should care, including role fit, relevant alignment, or a credible reason the sender's background may be useful or interesting to the recipient.
- **FR-EM-08A (Fit Evidence in the Body):** The draft shall include enough of the sender's relevant background to credibly establish strong fit for the role or conversation, but it shall limit itself to the most relevant supporting evidence rather than turning the email into a long self-summary.
- **FR-EM-08B (Overlap-Led Positioning):** For role-linked cold outreach, the draft should position the sender as someone who sees real overlap with the team's work and wants to learn more, rather than as someone leading with desperation for the job itself.
- **FR-EM-08C (Why-This-Person Bridge):** After the opening hook, the draft should usually include one short bridge line explaining why this specific recipient felt like the right person to contact, such as visible closeness to the work area, team, role, or problem space.
- **FR-EM-08D (Single Strong Proof Point):** For the current cold-outreach modes, the body should usually emphasize one strongest proof point of fit rather than a long list of credentials. That proof point may be one project, one internship or role, one technical area, or one especially strong overlap with the current work.
- **FR-EM-08E (Why-Now Clarity):** The email should make clear why the outreach is happening now, such as seeing the role, noticing real overlap with the team or work, or wanting to learn more because the recipient's current work appears closely relevant.
- **FR-EM-08F (Real Question Rule):** If the opening includes a question, that question should be small, specific, easy to understand, and genuinely tied to the work hook rather than functioning as a fake setup line.
- **FR-EM-08G (JD-Pain-Point-Aligned Evidence):** For role-targeted outreach, the strongest proof point should preferably align with the primary pain point or priority visible in the JD, such as cost, scale, latency, reliability, or delivery speed, when the sender has defensible evidence for that area.
- **FR-EM-08H (Metric-Led Evidence Preference):** When a quantified achievement is available and relevant, the draft should prefer one concrete metric-led evidence point over vague claims of impact.
- **FR-EM-08I (Exact-Skill Overlap Grounding):** When the draft references technical fit with the role, it shall ground that fit in real overlap between the resume and JD and shall not invent skills, tools, or stack experience that the sender does not actually have.
- **FR-EM-09 (Concise but Substantive Message):** Drafts shall balance brevity with enough substance to communicate a real reason for outreach. They should avoid being so short that they feel generic or empty, and avoid being so long that the reader is unlikely to continue.
- **FR-EM-09A (Tone Balance):** Drafts shall strike a balance between professional/direct and conversational/warm. They should feel human and approachable without becoming casual, sloppy, or overly informal.
- **FR-EM-09B (No Generic Flattery; Specific Praise Allowed):** Drafts shall avoid generic or performative flattery. However, light praise or appreciation is allowed in the opening when it is tied to a real, specific observation about the recipient's work and helps the message feel more thoughtful and engaging.
- **FR-EM-09C (Guided, Not Rigid Structure):** Drafts shall follow a guided structure rather than a rigid template. Certain building blocks should reliably appear, such as personalization, reason for outreach, fit/alignment, and a low-friction ask, but the exact phrasing and flow may adapt to keep the message natural.
- **FR-EM-09D (Drafting Guide Required):** The Email Drafting and Sending subcomponent shall eventually use an explicit drafting guide/playbook so email quality does not depend entirely on freeform model behavior.
- **FR-EM-09E (Deferred Drafting Guide Expansion):** Broader drafting-guide expansion beyond the currently imported legacy playbooks is intentionally deferred for a later deeper design pass. The current specification includes the imported current playbook, but it does not claim that playbook is the final long-term design.
- **FR-EM-09F (Mobile Readability Guard):** Drafts shall remain mobile-friendly by avoiding long dense text blocks. For this build, the email body should generally stay within three short paragraphs unless a recipient-type-specific reason justifies a different shape.
- **FR-EM-10 (Low-Friction Call to Action):** Drafts shall end with a simple, low-friction next step, such as openness to a short call or brief conversation, rather than a heavy or demanding ask.
- **FR-EM-10A (Recipient-Type-Dependent Ask):** The closing ask shall depend on recipient type. For example, hiring-manager outreach may lean toward a short conversation, while internal employee outreach may lean toward forwarding help, guidance, or light support.
- **FR-EM-10B (Current Default Conversation Ask):** For the current recruiter and team-adjacent one-step outreach flows, the default CTA should be a request for a short 15-minute Zoom conversation rather than a phone call.
- **FR-EM-10C (Autonomous Routing Ask):** In the autonomous LinkedIn-alert mode, the default outreach ask should explicitly allow for connection or routing help, such as connecting the candidate to the right hiring person or forwarding the resume internally, rather than assuming the recipient is already the exact target person.
- **FR-EM-10D (Single-Ask Discipline):** Even when the email contains both curiosity and role fit, the draft should end with one clear primary ask rather than stacking multiple different asks in the same message.
- **FR-EM-11 (Default Length Direction):** The default cold outreach style shall be medium-short: long enough to include real personalization and fit, but short enough to remain easy to read in one pass.
- **FR-EM-12 (Draft Priority Order):** When the draft must prioritize, it shall generally favor:
  1. strong personalization to the recipient
  2. clear role fit and relevant alignment
  3. a low-friction next step
  Personalization and role fit are both primary concerns and should remain meaningfully present together whenever possible.
- **FR-EM-12A (Two Outreach Modes):** The subcomponent shall support two outreach approaches at the product level:
  1. a direct one-step approach
  2. a learning-first two-step approach
- **FR-EM-12B (Primary Current Mode):** The direct one-step approach is the current primary outreach mode and the main mode being designed for current use.
- **FR-EM-12C (One-Step Direct Outreach):** In the one-step approach, the email shall use personalization, visible overlap with the recipient's work, and role fit to build interest and then move toward the intended low-friction call to action in the same email.
- **FR-EM-12C1 (Curiosity-Led One-Step Posture):** In the current one-step outreach mode for recruiter and team-adjacent profiles, the sender should lead with curiosity about the recipient's work and a desire to learn more, while still clearly mentioning the role and why there appears to be real fit.
- **FR-EM-12C2 (Current Shared Default Template Rule):** For v4, the current default shared role-targeted template shall not depend on opening from the recipient's personal background. Instead, it shall open from the role, team, or work area inferred from the JD or company context, then move into why the sender is reaching out to this person, one proof point of fit, one clear low-friction ask, and a routing-help line.
- **FR-EM-12C3 (Why-This-Person Line Required):** In the current shared default template, the body shall include one explicit sentence explaining why the sender chose to contact this person, such as because they posted the role, seem close to the team, or appear close to the relevant work area.
- **FR-EM-12C3A (Recipient-Type-Specific Why-Line Rule):** In the current shared default template, the explicit `why this person` line shall adapt by recipient type. For example, recruiter wording should point to hiring context, hiring-manager wording should use the softer `good person to reach out to for some perspective on this opening` framing, engineer or other-internal wording should point to day-to-day work perspective, and alumni wording should use the explicit fellow-Sun-Devil framing.
- **FR-EM-12C3B (Single Why-Line Discipline):** The current shared default template shall include the explicit `why this person` rationale once. It shall not restate the same reach-out rationale multiple times in slightly different wording later in the email.
- **FR-EM-12C4 (Routing-Then-Snippet Rule):** In the current shared default template, the routing-help sentence and the forwardable snippet shall appear together, with the snippet placed directly below the routing-help request.
- **FR-EM-12C5 (Current Shared Template Shape):** The current shared role-targeted template should follow this structure:
  1. role / team / work-area opening
  2. overlap statement
  3. explicit `why I am reaching out to you` line
  4. one proof point of fit with metric when available
  5. Job Hunt Copilot / AI-agent block
  6. one 15-minute Zoom ask plus routing-help sentence
  7. forwardable snippet block
- **FR-EM-12C5A (No Education-Status Default Line):** The current default shared role-targeted template shall not rely on an education-status sentence such as `I am currently finishing my MS ...` as a default body paragraph. Education context may still appear in signatures, alumni-specific messaging, or explicitly selected legacy playbooks when justified, but it is not part of the current default role-targeted body.
- **FR-EM-12C5B (Current Copilot Block Rule):** When the current shared template includes the Job Hunt Copilot block, that block shall state that Job Hunt Copilot helps identify relevant roles and the right people to reach out to, and that the AI agent runs autonomously with human-in-the-loop (HITL) review while the sender personally reviews each email before it goes out.
- **FR-EM-12C6 (Current Shared Template Draft Text):** The current default shared role-targeted template may use the following draft shape as the reference:

```text
Subject: [Role] at [Company] | Achyutaram Sonti

Hi [Name],

I'm reaching out about the [Role] role at [Company] because I was interested in the role's focus on [JD-faithful technical focus]. That is close to the kind of systems work I have been doing in production over the last few years.

[Why-this-person line based on recipient type/title.] In one recent role, [one strongest proof point with metric and grounded technical context].

Lately, I have been spending time sharpening my Agentic AI skills.
I built Job Hunt Copilot ([repo URL]) for my own job search to help me identify relevant roles and the right people to reach out to.
The AI agent runs autonomously with human-in-the-loop (HITL) review, and I personally review every email before it goes out. This email is a live example of that workflow.

If it would be useful, I would welcome a short 15-minute conversation sometime this or next week to learn a bit more about the role and get your perspective on whether my background could be relevant. If you're not the right person, I'd also really appreciate it if you could point me to the right person or forward my resume internally.

Forwardable snippet:
Hi, sharing a candidate who may be relevant for the [Role] role at [Company]. He has experience in [JD-aware focus phrase], including [one compact proof fragment]. Profile: www.linkedin.com/in/asonti

Best,
Achyutaram Sonti
[LinkedIn]
[Phone]
[Email]
```
- **FR-EM-12D (Two-Step Learning-First Outreach):** In the two-step approach, the email shall not begin with the direct role-oriented ask. Instead, it shall open from genuine curiosity about the recipient's work and ask for a brief learning conversation.
- **FR-EM-12E (Two-Step Learning Ask):** When the two-step mode is used, the ask should be framed as a short learning conversation, approximately 15 minutes, centered on something specific the sender wants to understand from the recipient's work or experience.
- **FR-EM-12E1 (General Learning Outreach Posture):** When outreach is not tied to a specific job posting, it should default to a learning-first posture centered on curiosity, learning, and a short coffee-chat-style conversation rather than behaving like a direct application email.
- **FR-EM-12F (Deferred Two-Step Flow Design):** The detailed flow, playbook, and follow-on behavior for the two-step approach are intentionally deferred for later design. The current specification fixes its existence and intent, but not the full operational sequence yet.
- **FR-EM-12F1 (Two-Step Out of Scope):** The two-step learning-first outreach approach shall remain on the to-do list for a later iteration and is not required for this build.
- **FR-EM-12F2 (Future Two-Step Flow Default Shape):** When the two-step learning-first outreach mode is implemented later, its default operating shape shall be:
  1. Step 1: send a learning-first email with no direct role ask
  2. wait for a positive or substantive response, or explicit expert instruction to continue
  3. Step 2: send the follow-on role-targeted ask only after that gate is satisfied
  Until that later mode is explicitly implemented, the current build continues to use the one-step direct role-targeted flow only.
- **FR-EM-13 (Primary Outreach Recipient Type):** The highest-priority outreach target shall be the recruiting manager or hiring manager who has publicly posted that they are hiring for the role.
- **FR-EM-14 (Secondary Internal Recipient Type):** The subcomponent shall also support outreach to additional internal contacts from the same company who appear close to the role, team, or adjacent work area, with the goal of asking for help, visibility, or forwarding of the tailored resume to the hiring manager.
- **FR-EM-15 (Relationship-Aware Framing):** When a meaningful connection signal exists, such as shared ASU alumni background, the draft shall use that relationship signal naturally to strengthen the outreach without forcing it where it does not fit.
- **FR-EM-16 (Recipient-Type Adaptive Strategy):** Drafting strategy shall adapt based on recipient type, such as hiring manager, internal employee, or alumni-connected contact, rather than using one identical outreach pattern for all recipients.
- **FR-EM-16A (Deferred Recipient-Type Strategy Expansion):** The exact message strategy and playbook for every recipient type is still deferred for deeper design later. The current specification imports concrete playbooks for some recipient types, but broader recipient-type strategy coverage remains open.
- **FR-EM-17 (Rich HTML Email Support):** The subcomponent shall support rich HTML email composition rather than limiting outreach to plain-text style only.
- **FR-EM-18 (Forwardable Internal Summary Snippet):** The email may include a compact, visually distinct summary snippet or block that a recipient can easily forward internally through email or messaging to the relevant person when that helps the recipient type or outreach goal.
- **FR-EM-18A (Forward-Ready Snippet Style):** When a forwardable snippet is used, it shall be very small, roughly three lines, and written so it feels like something the current recipient could plausibly forward as their own quick note with minimal or no editing. Its purpose is to reduce effort for the recipient and make internal forwarding easy.
- **FR-EM-18B (Current Shared-Template Snippet Default):** In the current shared role-targeted template, the forwardable snippet is a standard companion block because the primary outreach posture asks the recipient for routing or forwarding help. General learning outreach does not require that snippet by default.
- **FR-EM-18C (Forwardable Snippet Content Rule):** When a forwardable snippet is used, it should stay factual and compact, typically including only the candidate identity, one strongest impact point, and a small technical-fit summary rather than a long persuasive block.
- **FR-EM-18D (JD-Aware Snippet Rule):** The forwardable snippet shall choose its focus phrase from the role's strongest JD overlap and shall not fall back to generic skill-salad lines such as `3+ years across ...` when a clearer JD-grounded summary is available.
- **FR-EM-18E (Single-Proof Snippet Rule):** The forwardable snippet should usually carry one strongest supporting proof fragment rather than multiple stacked metrics or a long mini-pitch.
- **FR-EM-19 (Restrained Visual Polish):** Rich formatting shall aim for polished, brochure-like clarity without becoming flashy, noisy, or overly decorative. Visual emphasis should help readability and forwarding, not distract from the message.
- **FR-EM-19A (HTML Copilot Block Emphasis Rule):** In the current HTML renderer, the Job Hunt Copilot identity line and the AI-agent/HITL workflow line may receive bold emphasis, while the lighter bridge line above them remains visually secondary rather than equally emphasized.
- **FR-EM-20 (Compatibility Fallback):** Even when rich HTML formatting is used, the sending flow shall preserve a reasonable plain-text-compatible fallback representation so the core message remains readable across email clients.
- **FR-EM-20A (Markdown-Like Draft Source Rule):** The generated draft body may be authored in a markdown-like intermediary format for downstream rendering, but the drafting layer shall not rely on raw HTML generation as its primary authoring format.
- **FR-EM-20B (Locked Markdown Formatting Guidance):** In the imported current playbook, markdown bullets, markdown bold emphasis, and quoted snippet lines are the preferred authoring primitives for draft bodies and forwardable blocks before renderer conversion.

#### 7.3.3A Current Imported Outreach Guide and Legacy Draft Playbooks

The v4 specification should carry forward the imported current outreach guidance from the earlier `job-hunt-copilot/outreach/ai/` material so the live design does not lose the working playbook already developed there.

Current imported guidance should include, at minimum:

1. **Current recipient groups**
   - ASU alumni connections
   - previous job connections
   - recruiting managers who post job openings on LinkedIn
   - people who may be working on that team, especially software engineers
2. **Current recipient priority**
   - recruiting managers who post the job on LinkedIn
   - team-adjacent people who may work in or near that area, especially software engineers
   - ASU alumni connections
   - previous job connections
3. **Current focus profiles**
   - For now, the guide is designed most deeply first for:
     1. recruiting managers who post job openings on LinkedIn
     2. people who may be working on that team, especially software engineers
4. **Current one-step playbook shape**
   - hook about the recipient's work
   - one short appreciative note if it feels earned
   - short bridge for why this specific person
   - who the sender is
   - what the sender is looking for
   - one proof point of fit
   - one simple CTA
   - This imported playbook remains available, but the current v4 shared default template is the explicit structure defined in `FR-EM-12C2` through `FR-EM-12C6`.
5. **Current desired recipient reaction**
   - this is not a mass email
   - this person actually looked me up
   - this person seems thoughtful
   - there is a real reason they contacted me
   - this is job-related, but it does not feel needy or desperate
6. **Current imported metric-logic heuristic**
   - The legacy drafting SOP maps the JD's primary pain point to one or two strongest resume metrics before drafting.
   - Current heuristic categories include:
     - cost / budget
     - scale / volume
     - latency / performance
     - reliability / SLAs
     - velocity / speed
   - Current example metric anchors from the imported SOP include values such as `$120K annual cloud savings`, `2TB+/day` scale, `30k rec/sec (580 TPS)`, `99.95% uptime`, and `40% reduction in processing time`.
7. **Current imported hiring-manager playbook**
   - subject may follow the imported pattern: `[Job Title] ([Team Name]) | Achyutaram Sonti | Impact: [Primary Metric]`
   - the hook may directly mention the recent job posting, current role fit, and the company's current focus area
   - the body may use exactly 3 bullets when the imported playbook is selected:
     1. strongest metric aligned to the JD pain point
     2. second-best metric
     3. a `Technical Fit` bullet using exactly 3 to 5 real overlapping technologies from the resume and JD
   - the imported CTA may use the template: `Do you have 5-10 minutes for a brief chat this week regarding how my background aligns with your upcoming [JD Topic] goals?`
   - the imported routing block may use the template opening: `If you're not the right person to talk to, could you point me to or forward this to the hiring manager or someone on the team looking to fill this role. I've included a short snippet below that you can paste into an IM/Email:`
   - the imported forwardable snippet may use the field labels `Candidate`, `Experience`, `Impact`, and `Fit`
8. **Current imported ASU alumni playbook**
   - subject may follow the same imported pattern as the hiring-manager playbook
   - the imported hook may use the `Go Devils!` opener plus explicit ASU relationship framing
   - the imported body may use the same `exactly 3 bullets` rule as the hiring-manager playbook
   - the imported CTA may use the template: `As a fellow Sun Devil, would you be open to sharing a few minutes of advice on the engineering culture there?`
   - the imported routing block and forwardable snippet may match the hiring-manager pattern when useful
9. **Current imported forwardable snippet content**
   - candidate identity
   - concise experience summary
   - one strongest impact point
   - a compact technical-fit line
10. **Current imported formatting contract**
   - use markdown bullets (`* `) for bridge points and snippet point items
   - use markdown bold (`**text**`) where emphasis is required
   - use quoted lines (`>`) for forwardable snippet blocks when needed
   - do not author raw HTML directly in the drafting layer when the markdown-like intermediary format is available

### 7.3.4 Delivery Feedback Subcomponent FRs

- **FR-EF-01 (Feedback Capture):** Delivery Feedback shall capture send outcomes including sent, bounced, and not-bounced states when available.
- **FR-EF-01A (Feedback State Set):** For this build, Delivery Feedback only needs to track these high-level states: `sent`, `bounced`, `not_bounced`, and `replied`.
- **FR-EF-01B (Feedback Event History Preservation):** Delivery Feedback shall preserve feedback events over time rather than storing only a single overwritten latest state.
- **FR-EF-01C (Latest State as Derived View):** The latest delivery state may be surfaced as a convenience field or view, but it should be derived from preserved event history rather than replacing it.
- **FR-EF-01D (Per-Sent-Email Tracking Unit):** Delivery Feedback shall track outcomes at the level of a specific sent email instance rather than only at the broader contact level.
- **FR-EF-01E (Unique Sent-Instance Identifier):** Each sent email instance shall have a unique delivery-tracking identifier so later feedback events can be tied back to the exact sent instance. Thread ID may be used as a primary linkage field when available.
- **FR-EF-01F (Reply Context Retention):** When a reply is detected, Delivery Feedback should persist the reply content or a usable reply summary/context when available rather than storing only a boolean replied flag.
- **FR-EF-01G (Deferred Reply Classification):** Lightweight reply classification, such as `positive`, `neutral`, `negative`, or `unclear`, is deferred for later design and is not required in this build.
- **FR-EF-01H (Immediate Feedback Persistence):** Delivery Feedback shall update the canonical store immediately when a feedback event is detected rather than waiting for periodic batch synchronization.
- **FR-EF-01I (Event Timestamp Requirement):** Each delivery-feedback event shall store its event timestamp explicitly.
- **FR-EF-01J (Mailbox-Observed Feedback Source):** Delivery Feedback shall detect delayed bounce and reply outcomes by observing inbound mailbox feedback signals, such as bounce emails and reply messages, through the configured mailbox integration rather than requiring manual human reporting of those outcomes.
- **FR-EF-01K (Two-Phase Feedback Capture Pattern):** For this build, Delivery Feedback should use a two-phase capture pattern:
  1. one immediate post-send mailbox poll
  2. delayed scheduled mailbox polling every 5 minutes during the 30-minute bounce-observation window afterward
- **FR-EF-01L (Scheduled Feedback Sync Independence):** The delayed feedback polling path shall run independently from the original interactive send session so delayed bounce emails and replies can still be captured after the send run has ended.
- **FR-EF-01M (launchd Scheduler in Current Deployment):** In the current single-user macOS deployment, the delayed feedback-sync job should be invoked by `launchd`.
- **FR-EF-01N (Feedback Sync Run Audit):** Scheduled feedback-sync executions should be recorded in a queryable form, such as `feedback_sync_runs`, so the owner can tell whether delayed mailbox polling is actually running and when it last succeeded.
- **FR-EF-01O (Bounce-Observation Window):** For this build, the bounce-observation window for each sent email shall be 30 minutes from `sent_at`.
- **FR-EF-01P (Current Polling Cadence):** Within that 30-minute bounce-observation window, delayed feedback polling shall run every 5 minutes.
- **FR-EF-01Q (Current Not-Bounced Window Completion Rule):** If no bounce signal is detected by the end of the 30-minute bounce-observation window, Delivery Feedback may record a `not_bounced` outcome for that observation window while still allowing later reply detection to continue.
- **FR-EF-02 (Feedback Persistence):** Delivery Feedback shall persist post-send outcomes into the central SQLite database so they are queryable for review and reusable for future learning.
- **FR-EF-02A (Canonical Store + Optional Runtime Handoff):** `job_hunt_copilot.db` remains the source of truth for Delivery Feedback persistence. Runtime handoff artifacts may still be produced when a downstream workflow step needs them, but they do not replace the canonical store.
- **FR-EF-02B (Delivery Feedback Events Table):** The central database shall include a `delivery_feedback_events` table as the minimum canonical event-history store for post-send outcomes. For this build, it should at minimum capture a feedback-event identifier, linked outreach-message identifier, feedback state/event type, event timestamp, and reply content or summary when available.
- **FR-EF-03 (Feedback-to-Discovery Loop):** Delivery Feedback shall make bounced and non-bounced outcomes available to Email Discovery as feedback signals without requiring Email Discovery to own send execution.
- **FR-EF-03A (Reply Kept Out of Discovery Learning Loop):** Replied outcomes may still be retained in Delivery Feedback for review and outreach analysis, but they do not need to be part of the current Email Discovery learning loop.
- **FR-EF-03B (Conservative Bounce Reuse Rule):** In this build, bounced outcomes shall block future automatic reuse of that bounced email identity and any provider result that directly produced it, while `not_bounced` outcomes may be reused as positive discovery feedback. Automatic posting-level bounce-recovery loops remain deferred.

## 7.4 Operations / Supervisor Agent FRs

### 7.4.1 Mission and Operating Model

- **FR-OPS-01 (Supervisor Agent Component):** The current build shall include an `Operations / Supervisor Agent` component that continuously operates the end-to-end system, keeps queues moving, performs mandatory agent reviews, and maintains bounded autonomous stability without requiring a permanently open interactive session.
- **FR-OPS-02 (Single Identity, Two Faces):** The Supervisor Agent shall act as one logical agent with:
  1. a background supervisor face that runs the pipeline
  2. a chat operator face that the expert talks to
  Both faces share the same canonical state, identity, policies, incidents, and review queues.
- **FR-OPS-03 (Pipeline-Run Unit):** The Supervisor Agent shall treat one role-targeted end-to-end posting-scoped run as the primary durable unit of work. In the current build, that run starts from an actionable posting/lead handoff and continues through tailoring, mandatory agent review, contact search/discovery, frontier drafting, sending through the active send slice, and feedback-observation start.

### 7.4.2 Runtime Identity and Self-Awareness

- **FR-OPS-04 (Generated Runtime Identity Pack):** The Supervisor Agent's runtime identity shall be generated from the specification and build inputs into compact runtime artifacts rather than depending on the full PRD as its day-to-day prompt source.
- **FR-OPS-05 (Minimum Runtime Identity-Pack Contents):** The generated runtime identity pack should include:
  1. who the agent is and which project it operates
  2. allowed actions and forbidden actions
  3. stage map and handoff rules
  4. review policy and escalation policy
  5. service-goal and interval policy
  6. chat behavior policy
- **FR-OPS-06 (Runtime Self-Awareness Rule):** During normal operation, the Supervisor Agent should know what it is responsible for from the runtime identity pack plus canonical state. It should not need to reread the full PRD on every heartbeat to know who it is or what it should do.
- **FR-OPS-06A (`ops/agent/identity.yaml` Contract):** `ops/agent/identity.yaml` should minimally capture:
  1. agent name and role
  2. project name
  3. mission summary
  4. owned components
  5. allowed actions summary
  6. forbidden actions summary
  7. root canonical-state locations
- **FR-OPS-06B (`ops/agent/policies.yaml` Contract):** `ops/agent/policies.yaml` should minimally capture:
  1. mandatory review gates
  2. safety boundaries
  3. send policies and pacing constraints
  4. retry/repair limits
  5. pause/resume/stop semantics
  6. override semantics
- **FR-OPS-06C (`ops/agent/action-catalog.yaml` Contract):** `ops/agent/action-catalog.yaml` should minimally enumerate the bounded actions the Supervisor Agent may choose from, including the action name, scope, prerequisites, expected outputs, and validation rule reference for each action.
- **FR-OPS-06D (`ops/agent/service-goals.yaml` Contract):** `ops/agent/service-goals.yaml` should minimally capture the current heartbeat cadence, freshness expectations for actionable work, due-work priorities, and current continuous service-goal thresholds.
- **FR-OPS-06E (`ops/agent/escalation-policy.yaml` Contract):** `ops/agent/escalation-policy.yaml` should minimally capture incident severities, escalation triggers, auto-pause triggers, and what expert-facing packet or review surface should be created for each escalation class.
- **FR-OPS-06F (Separate Bootstrap Prompts Rule):** The current build should maintain separate bootstrap instructions for the background supervisor and the expert-facing chat operator so both Codex entrypoints inherit the same identity and policies while still behaving appropriately for their role.
- **FR-OPS-06G (`chat-bootstrap.md` and `supervisor-bootstrap.md`):** The current bootstrap prompt artifacts should be:
  1. `ops/agent/chat-bootstrap.md` for the expert-facing operator
  2. `ops/agent/supervisor-bootstrap.md` for the heartbeat-driven supervisor
  The chat bootstrap should prioritize inspection, explanation, and control-intent persistence. The supervisor bootstrap should prioritize work selection, validation, bounded repair, and escalation.
- **FR-OPS-06H (`ops/agent/progress-log.md` Contract):** `ops/agent/progress-log.md` should be a compact human-readable rolling handoff note for the Supervisor Agent. It is not canonical truth, but it should summarize the most recent meaningful operational changes so a fresh session can quickly understand what just happened.
- **FR-OPS-06H1 (`ops/agent/progress-log.md` Current Format):** In the current build, `ops/agent/progress-log.md` should use a stable Markdown shape with these sections in order:
  1. `Current Summary`
  2. `Current Blockers`
  3. `Next Likely Action`
  4. `Latest Replan / Maintenance Note`
  5. `Recent Entries`
  6. `Daily Rollups`
  Each recent entry should minimally include a timestamp, entry type, short summary, and relevant object or artifact references when needed.
- **FR-OPS-06H2 (`ops/agent/progress-log.md` Exact Current File Shape):** In the current build, `ops/agent/progress-log.md` should use this exact high-level Markdown layout:
  1. `# Supervisor Progress Log`
  2. `## Current Summary`
  3. `## Current Blockers`
  4. `## Next Likely Action`
  5. `## Latest Replan / Maintenance Note`
  6. `## Recent Entries`
  7. `## Daily Rollups`
  The `Current Summary` section should minimally include `updated_at`, `agent_mode`, `latest_cycle_result`, and `top_focus`. The `Recent Entries` section should use one compact row or bullet per entry with `timestamp`, `entry_type`, `summary`, and `refs`. The `Daily Rollups` section should use one dated compact summary per local calendar day.
- **FR-OPS-06I (`ops/agent/ops-plan.yaml` Contract):** `ops/agent/ops-plan.yaml` should capture the current near-term operating plan for the autonomous system, including current priorities, recurring issue themes, active watch items, maintenance backlog, weak areas, and the next replan focus when applicable.
- **FR-OPS-06I1 (`ops/agent/ops-plan.yaml` Current Format):** In the current build, `ops/agent/ops-plan.yaml` should minimally include:
  1. `contract_version`
  2. `generated_at`
  3. `agent_mode`
  4. `active_priorities`
  5. `watch_items`
  6. `maintenance_backlog`
  7. `weak_areas`
  8. `replan`
  Each active-priority entry should minimally include rank, title, reason, target object scope when applicable, and intended next action.
- **FR-OPS-06I2 (`ops/agent/ops-plan.yaml` Exact Current File Shape):** In the current build, `ops/agent/ops-plan.yaml` should use a stable YAML map with these top-level keys in order:
  1. `contract_version`
  2. `generated_at`
  3. `agent_mode`
  4. `active_priorities`
  5. `watch_items`
  6. `maintenance_backlog`
  7. `weak_areas`
  8. `replan`
  Each `active_priorities` item should minimally include `rank`, `title`, `reason`, `scope_type`, `scope_id`, and `intended_next_action`. Each `watch_items` entry should minimally include `title`, `reason`, and `trigger_condition`. Each `maintenance_backlog` entry should minimally include `title`, `reason`, and `blocked_by` when applicable. Each `weak_areas` entry should minimally include `area` and `note`. The `replan` block should minimally include `status`, `last_replan_at`, `next_focus`, and `reason` when replanning is active or recent.

### 7.4.3 Heartbeat, Context, and Scheduling

- **FR-OPS-07 (Current Scheduler Choice - Supervisor):** In the current local single-user macOS deployment, the Supervisor Agent heartbeat should be invoked by `launchd`.
- **FR-OPS-08 (Current Supervisor Heartbeat Interval):** The current Supervisor Agent heartbeat should run every 5 seconds unless the expert explicitly changes that interval later.
- **FR-OPS-09 (Fresh-Context Heartbeat Model):** Each heartbeat may create a fresh LLM reasoning context. Fresh context is allowed and expected.
- **FR-OPS-10 (Context Reconstruction Layers):** That fresh heartbeat context shall be reconstructed from:
  1. the runtime identity/policy pack
  2. a current system snapshot
  3. one or a few selected durable work units
  4. only the local evidence/artifacts needed for those work units
  5. the rolling progress log and near-term ops plan when those lightweight summaries are relevant to the selected work
- **FR-OPS-10A (Per-Cycle Context Snapshot Rule):** Before the supervisor asks the LLM to reason about the selected work unit, it shall persist a compact machine-readable cycle context snapshot that records the key state, selected work, and evidence references supplied to that reasoning call. This snapshot is an audit and context-efficiency artifact, not canonical truth over the database.
- **FR-OPS-10A1 (Context Snapshot Evidence Rule):** `context_snapshot.json` should include not only artifact paths and identifiers, but also the small exact evidence excerpts or compact snippets that were actually supplied to the reasoning call when those excerpts materially affected the decision. The snapshot should remain compact and selective rather than trying to duplicate full source artifacts.
- **FR-OPS-10A2 (`context_snapshot.json` Current Format):** In the current build, `context_snapshot.json` should minimally include:
  1. `contract_version`
  2. `supervisor_cycle_id`
  3. `created_at`
  4. `agent_mode`
  5. `selected_work`
  6. `state_summary`
  7. `candidate_actions`
  8. `evidence_refs`
  9. `evidence_excerpts`
  10. `sleep_wake_recovery_context` when applicable
  11. `notes`
  The snapshot may include additional keys, but these form the current minimum audit shape.
- **FR-OPS-10A3 (`context_snapshot.json` Exact Current File Shape):** In the current build, `context_snapshot.json` should use a stable JSON object with this current minimum nested shape:
  1. `selected_work` with `work_type`, `work_id`, and `pipeline_run_id` when applicable
  2. `state_summary` with compact current queue, pause, incident, and review counts relevant to the reasoning call
  3. `candidate_actions` as a compact array of action candidates, each with `action_name`, `reason`, and `prerequisites_ok`
  4. `evidence_refs` as a compact array of referenced objects or artifacts, each with `source_type`, `source_path`, and `object_id` when applicable
  5. `evidence_excerpts` as a compact array of exact excerpts actually supplied to the reasoning call, each with `source_path`, `excerpt`, and `reason`
  6. `sleep_wake_recovery_context` when applicable, with `detected`, `detection_method`, `event_ref`, and `recovery_scope`
  The snapshot should remain selective and should not duplicate whole source artifacts.
- **FR-OPS-11 (LLM Context Is Not Canonical Memory):** The LLM context window is working memory only. Durable memory shall remain in canonical DB state, persisted artifacts, incidents, review packets, and the runtime identity/policy pack.
- **FR-OPS-12 (Pipeline Run vs Heartbeat Cycle Distinction):** A heartbeat cycle is only one supervisor invocation. A pipeline run is the durable posting-scoped workflow object that may span many heartbeat cycles. A fresh heartbeat context shall not imply a fresh pipeline run.
- **FR-OPS-13 (No Overlapping Cycles):** Before doing work, the Supervisor Agent shall acquire a runtime lease. If another valid supervisor lease is still active, the new heartbeat shall exit or defer instead of creating overlapping autonomous work.
- **FR-OPS-14 (Lease-Recovery Rule):** If a previous supervisor lease is stale or expired, a later heartbeat may reclaim the lease and resume from canonical state rather than assuming the old interactive context still exists.
- **FR-OPS-14A (Current Supervisor Cycle Algorithm):** One heartbeat cycle should run in this order:
  1. read canonical control state
  2. if autonomous operation is disabled or stopped, record a deferred/no-work cycle and exit
  3. acquire the supervisor lease or defer if a valid lease already exists
  4. build a compact current system snapshot
  5. evaluate auto-pause conditions
  6. if paused or auto-paused, allow only safe observational work permitted by policy; otherwise select the highest-priority actionable work unit
  7. build and persist a minimal context pack for the selected work unit
  8. choose one allowed next action from the action catalog
  9. validate prerequisites before execution
  10. execute the action
  11. validate outputs and canonical state transitions
  12. persist cycle summary, run/incident updates, and any resulting review artifacts
  13. release or let expire the lease at a safe checkpoint
- **FR-OPS-14B (One Primary Work Unit Per Cycle):** By default, a supervisor cycle should focus on one primary work unit or one tightly related object cluster rather than trying to drain the whole queue in one invocation.
- **FR-OPS-14C (Same-Object Follow-Through Allowed):** Within one cycle, the Supervisor Agent may still finish immediate validation, writeback, or one short same-object follow-through step when required for consistency, as long as it does not branch into unrelated work units.
- **FR-OPS-14C1 (Pause Request Overrides Optional Follow-Through Rule):** If a pause condition or expert-interaction pause request arrives during a cycle, optional same-object follow-through shall not continue. The cycle should stop after only the minimum consistency-preserving checkpoint work needed to leave canonical state and external side effects coherent.
- **FR-OPS-14D (Long-Cycle Deferral Rule):** A selected action may run longer than the nominal heartbeat interval when needed to finish the current safe unit of work. If another heartbeat fires while the lease is still active, that later heartbeat shall defer rather than interrupt the active cycle.
- **FR-OPS-14E (Paused-Mode Safe Work Rule):** When `agent_mode = paused`, the Supervisor Agent shall not start new pipeline runs or new automatic sends, but it may still allow safe observational work such as feedback polling, report generation, chat-based inspection, and persisted control-state changes.
- **FR-OPS-14F (Sleep/Wake Recovery Priority Rule):** If the current heartbeat detects a likely host-sleep interruption or wake recovery condition under current macOS deployment rules, the Supervisor Agent shall run bounded sleep/wake recovery before it starts any ordinary new autonomous progression for that cycle.

### 7.4.4 Work Selection and Continuous Service Goals

- **FR-OPS-15 (Continuous Service Goal Model):** The Supervisor Agent shall run against continuous service goals rather than a once-per-day batch target model.
- **FR-OPS-16 (Current Continuous Service Goals):** The current service goals should include:
  1. due work is picked up within the active heartbeat cadence
  2. no actionable queue item remains untouched without an explicit persisted reason
  3. required send pacing is honored
  4. required feedback polling is honored
  5. blocked or failed work always receives a persisted reason or incident
- **FR-OPS-17 (Work-Selection Priority Rule):** The Supervisor Agent should choose the next work in this priority order by default:
  1. active control-state changes such as pause or stop
  2. open incidents and broken health-critical work
  3. due sends and due feedback polling
  4. mandatory agent review gates
  5. active posting runs waiting to advance
  6. new Gmail-ingestion work
  7. bounded maintenance work
- **FR-OPS-17A (Single Active Role-Targeted Run Per Posting):** For the current role-targeted flow, the system should keep at most one non-terminal `pipeline_run` for the same `job_posting_id` at a time. If relevant work already exists for that posting, the Supervisor Agent should resume the existing run rather than create a duplicate active run.
- **FR-OPS-17B (Pipeline-Run Creation Rule):** A `pipeline_run` shall be created when a posting first enters autonomous role-targeted execution and no active run already exists for that posting.
- **FR-OPS-17C (Pipeline-Run Status Transition Rule):** The current role-targeted run-status transitions should behave as:
  1. `in_progress` on creation and normal advancement
  2. `paused` when global or local pause conditions stop further automatic progression
  3. `escalated` when safe automatic progression stops because expert attention is required
  4. `failed` when the run reaches a terminal unresolved state for the current build
  5. `completed` when the current end-to-end boundary is reached and the review packet has been generated, or when the expert manually closes an unresolved escalated review item
- **FR-OPS-17D (Pipeline-Run Resume Rule):** A paused or escalated `pipeline_run` may return to `in_progress` after the relevant pause or escalation condition has been cleared and canonical prerequisites are again satisfied.
- **FR-OPS-17E (Terminal-Run Immutability Rule):** A terminal `pipeline_run`, including `completed`, `failed`, or `escalated` outcomes, should remain part of immutable operational history. The current build may still finalize an unresolved `escalated` run to `completed` when the expert explicitly closes that exact review-backed run from expert review. Outside that narrow closure path, if the expert later wants a fresh attempt after review, the system should create a new run rather than mutating the older terminal run back into an active state.
- **FR-OPS-17F (Review-Packet State Transition Rule):** `pipeline_runs.review_packet_status` should transition:
  1. `not_ready` while the run is still active
  2. `pending_expert_review` when the run reaches a terminal or expert-review-worthy outcome and the review packet is generated
  3. `reviewed` when expert review is finished, including expert-driven manual closure from review
  4. `superseded` only when a newer packet replaces the older packet for the same terminal or otherwise review-worthy run outcome
- **FR-OPS-17G (Agent-Control-State Semantics):** The current `agent_control_state` semantics should be:
  1. `agent_enabled = true` and `agent_mode = running` for normal autonomous operation
  2. `agent_enabled = true` and `agent_mode = paused` when autonomous progression is paused but safe observational work may continue
  3. `agent_enabled = false` and `agent_mode = stopped` when background autonomous execution is fully disabled
  4. `agent_enabled = true` and `agent_mode = replanning` when a bounded replanning pass is the active autonomous priority and normal pipeline advancement is temporarily held back under replanning rules
- **FR-OPS-17H (Pause/Resume State Transition Rule):** `jhc-agent-start` or an explicit resume command should set the system to enabled/running. Pause should keep the system enabled but paused. Stop should set the system to disabled/stopped. Replanning triggers should set the system to enabled/replanning until the replanning exit conditions are satisfied.
- **FR-OPS-17I (Agent-Incident State Transition Rule):** `agent_incidents` should transition:
  1. `open` when the issue is first detected
  2. `in_repair` when bounded automatic repair begins
  3. `resolved` when the issue is successfully cleared
  4. `escalated` when expert attention is required
  5. `suppressed` when the expert intentionally acknowledges but chooses no further action
- **FR-OPS-17J (Expert-Review-Packet State Transition Rule):** `expert_review_packets.packet_status` should transition from `pending_expert_review` to `reviewed` when the expert has finished with the packet, or to `superseded` if a replacement packet for the same terminal or otherwise review-worthy run outcome is generated later.
- **FR-OPS-17J1A (Manual Review Close Rule):** The current build shall support an explicit expert-review close action for unresolved escalated posting runs. When the expert closes such a packet with a non-empty comment:
  1. the comment shall be stored as an `expert_review_decisions` record linked to that packet
  2. the associated `job_posting.posting_status` shall become `closed_by_user`
  3. the associated `pipeline_run.run_status` shall become `completed`
  4. the associated `pipeline_run.current_stage` shall become `completed`
  5. a posting-status override event shall be recorded
  6. the item shall no longer appear in normal pending expert-review queues
- **FR-OPS-17J1 (Rolling Progress-Log Rule):** The Supervisor Agent shall maintain `ops/agent/progress-log.md` as a concise rolling handoff note that highlights the latest significant work completed, current blockers, the next likely action, and any replan or maintenance note worth surfacing to a fresh session.
- **FR-OPS-17J2 (Progress-Log Update Rule):** The progress log should be updated after each materially meaningful supervisor cycle, after each replan, and after each maintenance change batch outcome. It should remain compact and summarize recent state rather than trying to duplicate the full canonical history.
- **FR-OPS-17J2A (Current Progress-Log Retention Rule):** In the current build, `ops/agent/progress-log.md` should keep:
  1. one current summary section
  2. the last 20 meaningful detailed entries
  3. compact daily rollups for the last 7 local calendar days
  Older history should remain queryable through canonical DB records, cycle history, incidents, and review artifacts rather than continuing to accumulate in the progress log itself.
- **FR-OPS-17J3 (Near-Term Ops-Plan Rule):** The Supervisor Agent shall maintain `ops/agent/ops-plan.yaml` as the current near-term operating plan so repeated fresh sessions can quickly see the active priorities, current weak areas, recurring issue themes, maintenance backlog, and what the agent currently believes needs attention next.
- **FR-OPS-17J3A (Current Ops-Plan Shape Rule):** In the current build, `ops/agent/ops-plan.yaml` should keep:
  1. the top 5 active near-term priorities
  2. a separate watch-items section
  3. a separate maintenance-backlog section
  4. a concise weak-areas or recurring-issue section
  The file should remain a near-term operating plan, not a full historical archive or exhaustive queue dump.
- **FR-OPS-17J4 (Replanning Mode Rule):** The current autonomous system shall support a bounded `replanning` mode for the Supervisor Agent. Replanning is used to rebuild the near-term operating plan when repeated incidents, drift, or stale priorities indicate that normal incremental progression is no longer enough.
- **FR-OPS-17J5 (Current Replanning Triggers):** A bounded replanning pass should be triggered when at least one of these conditions occurs:
  1. the expert explicitly requests replanning
  2. the system enters auto-pause twice within a rolling 24-hour window
  3. the same continuous service goal is missed for 6 consecutive hours
  4. two consecutive autonomous maintenance change batches fail in the same operational area within 3 local calendar days
- **FR-OPS-17J5A (Automatic Replanning Cooldown Rule):** In the current build, automatically triggered replanning should not run more than once in any rolling 6-hour window unless the expert explicitly requests another replanning pass sooner.
- **FR-OPS-17J6 (Replanning Execution Boundary Rule):** During `agent_mode = replanning`, the Supervisor Agent shall not start new pipeline runs, new automatic sends, or new maintenance merges. Safe observational work such as feedback polling, report generation, and chat-based inspection may continue. If a replanning trigger arrives during an active cycle, the current cycle should finish at the next safe checkpoint first.
- **FR-OPS-17J7 (Replanning Outputs Rule):** A replanning pass shall refresh `ops/agent/ops-plan.yaml`, append a concise replanning entry to `ops/agent/progress-log.md`, and persist enough cycle-level evidence that the expert can later understand why priorities changed.
- **FR-OPS-17J8 (Replanning Exit Rule):** After a replanning pass completes, the Supervisor Agent may return to normal running only if no other pause, clarification, or stop condition still applies. Otherwise it shall remain in the stricter current mode until cleared.

### 7.4.4A Action Catalog

- **FR-OPS-17K (Action-Catalog Governance Rule):** During autonomous operation, the Supervisor Agent should choose only from the registered bounded actions in `ops/agent/action-catalog.yaml`. If the needed next move is not covered by a registered action, the system should escalate rather than improvise broad behavior.
- **FR-OPS-17L (Minimum Current Action Categories):** The current action catalog should cover at least these categories:
  1. supervisor/control actions
  2. lead-ingestion actions
  3. tailoring and review actions
  4. people-search and discovery actions
  5. drafting and sending actions
  6. feedback actions
  7. repair and escalation actions
  8. expert-interface/reporting actions
- **FR-OPS-17M (Minimum Current Registered Actions):** The current action catalog should include at least these named actions or their clear equivalents:
  1. `refresh_control_state`
  2. `evaluate_auto_pause`
  3. `create_or_resume_pipeline_run`
  4. `ingest_gmail_alert_batch`
  5. `advance_lead_handoff`
  6. `run_resume_tailoring`
  7. `perform_mandatory_agent_review`
  8. `run_people_search`
  9. `materialize_shortlist`
  10. `run_contact_enrichment`
  11. `run_recipient_profile_extraction`
  12. `run_email_discovery`
  13. `assemble_send_set`
  14. `generate_ready_set_drafts`
  15. `send_due_message`
  16. `run_immediate_feedback_poll`
  17. `run_scheduled_feedback_sync`
  18. `generate_expert_review_packet`
  19. `repair_incident`
  20. `apply_pause_or_resume_state`
  21. `persist_expert_override`
  22. `summarize_state_for_chat`
  23. `run_replanning_pass`
  24. `update_progress_log`
  25. `run_sleep_wake_recovery`
- **FR-OPS-17N (Action Entry Contract):** Each action-catalog entry should minimally describe:
  1. action name
  2. scope/object type
  3. prerequisites
  4. expected outputs
  5. canonical-state updates
  6. validation rule reference
- **FR-OPS-17O (Pre/Post-Action Validation Rule):** Before executing a catalog action, the Supervisor Agent shall confirm the action's prerequisites from persisted state. After execution, it shall validate that the expected outputs and canonical-state updates actually occurred before treating the action as successful.
- **FR-OPS-17P (Daily Maintenance Requirement):** The Supervisor Agent shall complete one bounded maintenance cycle at least once per calendar day in the machine's local timezone while autonomous operation remains enabled.
- **FR-OPS-17Q (Maintenance Scheduling Rule):** The Supervisor Agent should prefer to schedule the daily maintenance cycle at a natural end-to-end run boundary, after one completed end-to-end run and before starting the next new end-to-end run. The agent may choose the best timing autonomously, but it shall not skip the required daily maintenance cycle.
- **FR-OPS-17R (Maintenance-Only Change Rule):** Autonomous code or configuration changes are permitted only during a maintenance cycle, not during normal operational advancement cycles.
- **FR-OPS-17S (Git-Tracked Maintenance Change Rule):** Every autonomous code or configuration change made during a maintenance cycle shall be captured through git-backed change tracking so the expert can inspect and revert the change set if needed.
- **FR-OPS-17T (Maintenance Change Frequency Rule):** The Supervisor Agent should avoid frequent autonomous code/config churn. In the current build, at most one autonomous code/config change batch should be produced in a single daily maintenance cycle unless the expert explicitly overrides this limit.
- **FR-OPS-17U (No Mid-Run Maintenance Interruption Rule):** The Supervisor Agent shall not interrupt an active end-to-end run solely to satisfy the daily maintenance requirement. If maintenance becomes due while a run is still in progress, the agent should wait until the next safe run boundary and perform maintenance before beginning the next new run.
- **FR-OPS-17V (Maintenance Branch Isolation Rule):** Autonomous code/config changes shall not be applied directly to the main working tree. Each daily maintenance change batch should be prepared on a dedicated git maintenance branch or equivalent isolated git-tracked change unit.
- **FR-OPS-17W (Maintenance Commit Traceability Rule):** Each autonomous maintenance change batch should produce an explicit git commit or equivalent durable git-tracked checkpoint with a machine-readable summary of why the change was made, what files changed, and what validation was run before the change is considered operationally usable.
- **FR-OPS-17W1 (Default Maintenance Git Integration Rule):** In the current build, the default maintenance git workflow shall be:
  1. create a dedicated maintenance branch for the autonomous change batch
  2. commit the maintenance change on that branch
  3. after approval and validation, merge it back with a normal merge commit rather than squash-merge or rebase/fast-forward by default
- **FR-OPS-17W2 (Maintenance Approval Persistence Rule):** The canonical maintenance approval outcome shall be persisted in SQLite state rather than only in git metadata or commit messages. A companion maintenance artifact file should also be written for human inspection and auditability.
- **FR-OPS-17W3 (Maintenance Artifact Coverage Rule):** Companion maintenance artifacts shall be written for every autonomous maintenance change batch, including approved, merged, failed, and unapproved batches, so the expert has a complete audit trail rather than visibility only into successful changes.
- **FR-OPS-17W3A (Transient Send Runnable Gate Rule):** The Supervisor Agent shall treat a role-targeted `sending` run as runnable only when the next send attempt is actually due. A transient blocked send that is still inside its cooldown window shall not keep winning scheduler selection ahead of other runnable work.
- **FR-OPS-17W4 (Default Maintenance Branch Naming Rule):** In the current build, each autonomous maintenance branch should use this format:
  `maintenance/{YYYYMMDD-local}-{maintenance_change_batch_id}-{scope_slug}`
  where `scope_slug` is a short filesystem-safe summary of the intended change scope.
- **FR-OPS-17W5 (Default Maintenance Merge-Commit Format Rule):** In the current build, the default merge commit for an approved autonomous maintenance batch should use:
  1. subject line: `merge(maintenance): {maintenance_change_batch_id} {scope_slug}`
  2. body lines including at least:
     `Branch: {branch_name}`
     `Reason: {short_reason}`
     `Validation: {change_validation_summary}; {full_system_validation_summary}`
     `Approval: approved`
  The merge commit should remain concise but explicit enough for later audit and revert work.
- **FR-OPS-17W6 (Maintenance Change JSON Contract):** `maintenance_change.json` should minimally include:
  1. `contract_version`
  2. `maintenance_change_batch_id`
  3. `local_day`
  4. `scope_slug`
  5. `branch_name`
  6. `status`
  7. `approval_outcome`
  8. `short_reason`
  9. `head_commit_sha`
  10. `merged_commit_sha`
  11. `merge_commit_message`
  12. `created_at`
  13. `validated_at`
  14. `approved_at`
  15. `merged_at`
  16. `failed_at`
  17. `files_changed`
  18. `change_scoped_validation`
  19. `full_system_validation`
  20. `related_incident_ids`
  21. `related_review_packet_ids`
  22. `notes`
  The contract may include additional fields when needed, but these fields are the current minimum machine-readable audit surface.
- **FR-OPS-17X (Maintenance Merge Gate Rule):** An autonomous maintenance change batch may be merged back into the main operational code path only after the required maintenance validation/testing pass succeeds and the change batch receives an explicit maintenance approval outcome under current agent policy.
- **FR-OPS-17Y (Failed Maintenance Validation Rule):** If the maintenance validation/testing pass fails or the maintenance approval outcome is not `approved`, the change batch shall remain isolated from the main operational code path and the system shall persist the failure or review outcome for later inspection.
- **FR-OPS-17Z (Post-Merge Operational Use Rule):** Once an autonomous maintenance change batch has passed required validation, received an approved maintenance outcome, and been merged into the main operational code path, the Supervisor Agent may begin using the updated code/config automatically on subsequent heartbeats without waiting for a separate expert hold.
- **FR-OPS-17AA (Maintenance Test Scope Rule):** Proper testing for an autonomous maintenance change batch shall include both:
  1. validation/tests directly relevant to the changed files, modules, or behavior
  2. a broader end-to-end or full-system validation layer sufficient to confirm the overall project still operates correctly after the change
- **FR-OPS-17AB (Maintenance Approval Preconditions):** A maintenance change batch shall not receive an `approved` maintenance outcome unless both the change-scoped validation layer and the broader full-system validation layer have succeeded under current policy.
- **FR-OPS-17AC (Failed Maintenance Branch Retention Rule):** If an autonomous maintenance change batch fails validation or is not approved, the isolated branch/change unit shall be retained with its validation evidence, failure notes, and changed-file summary available for later expert inspection rather than being silently discarded.
- **FR-OPS-17AD (Expert Change Visibility Rule):** Any autonomous maintenance change batch, whether merged or not, shall be included in the expert-facing change/update summary when the expert asks what changed, what was attempted, or what needs review.
- **FR-OPS-17AD1 (Maintenance Focus-Slice Ownership Rule):** When an autonomous maintenance or build-improvement agent is operating under a declared focus slice, it shall prioritize work owned by that slice and honor same-slice role handoffs rather than looping on unrelated support work.
- **FR-OPS-17AE (Default Change-Summary Window Rule):** When the expert asks what changed or asks for updates without specifying a custom window, the Supervisor Agent shall default to showing changes and relevant autonomous maintenance activity since the last completed expert review checkpoint.

### 7.4.5 Review Model

- **FR-OPS-18 (Mandatory Agent Review Inside Pipeline):** Internal review gates remain mandatory, but the Supervisor Agent is the default reviewer. At those gates the agent shall record an explicit review outcome before the posting/contact/object can advance.
- **FR-OPS-19 (Post-Run Expert Review Packet):** After each terminal or review-worthy end-to-end role-targeted pipeline run outcome, including successful completion, failure, blocking terminality, or escalation requiring expert attention, the Supervisor Agent shall produce a persisted expert review packet that summarizes:
  1. what succeeded
  2. what failed or was missed
  3. what retries/repairs were attempted
  4. incidents raised
  5. recommended expert actions or corrections
- **FR-OPS-20 (Expert Review Is Supervisory by Default):** Expert review packets are mandatory outputs, but they do not automatically pause the entire autonomous system unless the expert explicitly issues a pause, stop, or override instruction.
- **FR-OPS-21 (Review Packet Retrieval Rule):** When the expert asks to see items for review, the Supervisor Agent shall surface the currently pending expert review packets, linked incidents, and the relevant artifact/report paths conversationally.
- **FR-OPS-21A1 (Default Review Queue Ordering Rule):** When the expert asks to see items for review without specifying another ordering, the default review queue ordering shall be by creation time with the newest review items first.
- **FR-OPS-21A2 (Grouped Review Queue Presentation Rule):** By default, `show me items for review` should present review items grouped by item type rather than as one mixed stream. Within each group, items should follow the default creation-time ordering with the newest items first.
- **FR-OPS-21A3 (Default Review Group Order Rule):** In the current build, the default grouped order for `show me items for review` should be:
  1. expert review packets
  2. failed or unresolved expert-requested background tasks
  3. autonomous maintenance change batches
  4. open incidents
- **FR-OPS-21A4 (Compact-First Review Group Presentation Rule):** Within each default review group, the first presentation should be a compact summary list rather than fully expanded detail. Deeper detail, artifact paths, and full reasoning should be surfaced only when the expert asks for expansion or selects a specific item.
- **FR-OPS-21A5 (Default Review Group Page Size Rule):** In the current build, the compact-first review presentation should show at most 5 items per review group by default. If more items exist in that group, the response should indicate that more items are available and support later expansion on request.
- **FR-OPS-21AA (Review Packet Relevance Rule):** Expert review packets should be relevance-shaped rather than rigidly uniform. Early failures, blocked runs, or escalations may use a lighter packet that contains only the details, evidence, and review questions relevant to that run outcome.
- **FR-OPS-21AB (Review Packet Lineage Reuse Rule):** If a run that already has review-packet history reaches another terminal or otherwise review-worthy state, the supervisor should preserve and reuse that run's existing review-packet lineage rather than creating disconnected duplicate history for the same run without reference to the earlier packet.
- **FR-OPS-21C (Expert Change Summary Inclusion Rule):** Expert-facing review retrieval shall also include autonomous maintenance change batches and their current outcomes so the expert can inspect merged improvements, failed maintenance attempts, and pending change-related follow-up from the same conversational interface.
- **FR-OPS-21D (Last-Review Default Retrieval Rule):** The default conversational retrieval scope for expert-facing updates/change summaries should be the period since the last completed expert review, while still allowing the expert to ask for broader history explicitly.
- **FR-OPS-21E (Immediate Expert Guidance Activation Rule):** Once the expert completes a review and issues guidance, correction, or override through the approved interface, that decision shall become live operating guidance immediately in canonical state rather than waiting for the next maintenance cycle to formalize it.
- **FR-OPS-21E1 (Future-Effective Override Rule):** By default, a direct expert override should not be treated as a one-off object fix only. Once persisted, it should also become future-facing operating guidance for later autonomous decisions unless the expert explicitly scopes it more narrowly.
- **FR-OPS-21E2 (Similarity-Based Guidance Generalization Rule):** Unless the expert explicitly narrows the scope, the Supervisor Agent should generalize persisted expert overrides and guidance to similar future cases using its judgment, while preserving traceability back to the original guidance source.
- **FR-OPS-21E3 (Guidance-Lineage Persistence Rule):** Whenever the Supervisor Agent applies generalized future guidance derived from an earlier expert decision, it shall persist lineage that identifies the source expert review or override decision from which that guidance was learned.
- **FR-OPS-21E4 (Similarity Uncertainty Clarification Rule):** If the Supervisor Agent is not sufficiently confident that a new case is similar enough to justify applying generalized expert guidance, it shall stop and ask the expert for clarification rather than guessing.
- **FR-OPS-21F (Conflicting Expert Guidance Clarification Rule):** If a newly issued expert instruction materially conflicts with standing policy, a previously persisted expert instruction, or an active operating constraint, the Supervisor Agent shall stop short of silently applying the conflicting guidance and instead request clarification through the expert-facing interface.
- **FR-OPS-21G (Guidance-Conflict Global Pause Rule):** When clarification is required for a materially conflicting expert instruction, the Supervisor Agent shall pause the whole autonomous system until the expert resolves the conflict through the approved interface.
- **FR-OPS-21H (No Chat Restriction During Guidance Pause Rule):** A clarification-driven global pause shall restrict autonomous background progression, not expert chat capability. During such a pause, `jhc-chat` shall continue to allow full expert interaction, including inspection, report retrieval, explanations, overrides, clarification, and other approved control requests.
- **FR-OPS-21A (Review Packet JSON Contract):** `review_packet.json` should minimally include the relevant subset of:
  1. `pipeline_run_id`
  2. linked `job_posting_id` when applicable
  3. run outcome/status
  4. stages completed
  5. target contacts selected
  6. emails found / not found
  7. sends attempted / completed
  8. incidents raised
  9. retries or repairs attempted
  10. recommended expert actions
- **FR-OPS-21B (Review Packet Markdown Companion):** `review_packet.md` should be the concise human-readable companion to `review_packet.json` and should summarize only the run story, misses, incidents, and review questions relevant to that run outcome.

### 7.4.6 Bounded Repair, Escalation, and Stability

- **FR-OPS-22 (Bounded Repair Rule):** The Supervisor Agent may autonomously perform bounded repair such as retrying a failed stage at the smallest safe unit, regenerating a missing artifact, using the next allowed provider fallback, or applying small non-destructive configuration/runtime fixes.
- **FR-OPS-22A (Operational vs Maintenance Repair Boundary):** During normal operational cycles, bounded repair should stay within runtime actions, retries, regeneration, and other non-code/non-config fixes. Code/config modifications remain reserved for the daily maintenance cycle unless the expert explicitly authorizes otherwise.
- **FR-OPS-23 (Escalation Boundary Rule):** The Supervisor Agent shall escalate instead of making blind changes when:
  1. repeated bounded repair still fails
  2. the failure suggests state corruption, secrets/auth breakage, or schema drift
  3. a broader code or behavior change would be required
  4. the safe next action is ambiguous
- **FR-OPS-24 (Incident Persistence Rule):** Unresolved or escalated failures shall be persisted as canonical `agent_incidents` rather than living only in temporary logs or chat memory.
- **FR-OPS-24A (Current Auto-Pause Threshold):** The Supervisor Agent shall automatically pause autonomous progression when either of these conditions occurs:
  1. any unresolved `critical` incident that affects send safety, duplicate-send risk, credential/secrets handling, or canonical-state integrity
  2. 3 unresolved incidents of the same `incident_type` within the same stage, provider area, or operational area inside a rolling 45-minute window
- **FR-OPS-24B (Current Auto-Pause Effect):** When the auto-pause threshold is triggered, the Supervisor Agent shall:
  1. stop starting new pipeline runs
  2. stop any new automatic sends
  3. persist the pause reason into canonical control state
  4. keep the triggering incidents visible in the expert review queue
  5. allow already-persisted state and already-written artifacts to remain intact for diagnosis and later resume

### 7.4.7 Chat-First Interface and Control

- **FR-OPS-25 (Chat-Only User Interface):** The expert-facing operating interface for the Supervisor Agent shall be chat-first. Reports may be shown directly in chat when compact or surfaced through file paths when large.
- **FR-OPS-26 (Conversational Control Intents):** Through chat, the expert shall be able to request status, pending review items, incidents, run summaries, report locations, pause, resume, stop, retry, or override actions without requiring a fixed public command-line contract.
- **FR-OPS-27 (Persisted Control-State Rule):** Chat-issued control intents that affect background behavior, such as pause/resume/stop, shall be persisted into canonical control state so the next heartbeat obeys them even if the current chat session disappears.
- **FR-OPS-27A (Chat Intent Classes):** `jhc-chat` should distinguish at least these intent classes:
  1. inspection/status requests
  2. review/report retrieval requests
  3. global control requests such as pause/resume/stop
  4. object-specific retry or override requests
  5. explanatory questions about why something happened
- **FR-OPS-27B (Read-Before-Answer Rule):** For every expert request, `jhc-chat` shall prefer current persisted state over earlier chat memory. It should re-read the relevant DB state, review packet, incident, or artifact before answering.
- **FR-OPS-27C (Chat Response Style Rule):** `jhc-chat` should answer concisely and factually, using the current persisted object IDs, statuses, reasons, and file paths when those help the expert act quickly.
- **FR-OPS-27D (Large-Result Presentation Rule):** If the requested result is too large for a clean chat response, `jhc-chat` should give a short summary and then point the expert to the exact artifact/report path.
- **FR-OPS-27E (Control Routing Rule):** `jhc-chat` should route:
  1. global pause/resume/stop intents into `agent_control_state`
  2. object-specific overrides into the relevant canonical state updates plus `override_events`
  3. read-only inspection requests into no-write responses
- **FR-OPS-27F (Clarification Before Risky Mutation Rule):** If an expert request would change autonomous state or override a decision but the target object or intended effect is ambiguous, `jhc-chat` should ask a focused clarifying question before mutating canonical state.
- **FR-OPS-27G (Full Chat Availability Rule):** `jhc-chat` shall remain fully available to the expert during paused states, auto-pauses, and guidance-conflict pauses. Pause state limits autonomous background work, not the expert's conversational access or control surface.
- **FR-OPS-27H (Expert-Interaction Global Pause Rule):** When the expert actively engages the system through `jhc-chat`, the autonomous background system shall enter an expert-interaction pause so the agent can focus on the expert without concurrent autonomous progression.
- **FR-OPS-27H1 (Pause-On-Chat-Startup Rule):** For the current build, opening `jhc-chat` itself shall count as active expert engagement and should trigger the expert-interaction pause immediately, without waiting for the first substantive expert message.
- **FR-OPS-27I (Safe Checkpoint Before Expert Conversation Rule):** If an expert interaction begins while a supervisor cycle is already executing, the cycle shall stop at the next strict safe checkpoint rather than being torn down mid-step. The agent should preserve canonical consistency, persist any finished writes that are required for correctness, and avoid leaving half-applied autonomous state.
- **FR-OPS-27I1 (Strict Safe Checkpoint Definition Rule):** In the current build, a strict safe checkpoint means:
  1. no new side-effectful step begins after the pause request is observed
  2. if the cycle is already inside a side-effectful step, it may perform only the minimum validation/writeback needed to leave canonical state and external side effects coherent
  3. no optional follow-through, unrelated work, or next-step progression begins after that minimum checkpoint work is complete
- **FR-OPS-27J (No New Autonomous Side-Effects During Expert Interaction Rule):** During an expert-interaction pause, the Supervisor Agent shall not start new pipeline runs, new automatic sends, new provider-driven progression steps, or new maintenance merges unless the expert explicitly instructs that action through the approved interface.
- **FR-OPS-27K (Allowed Actions During Expert Interaction Pause):** During an expert-interaction pause, the system may still perform read-only inspection, report retrieval, explanation, review presentation, persistence of expert decisions/overrides, and other state changes directly requested by the expert through `jhc-chat`.
- **FR-OPS-27L (Expert-Interaction Pause Reason Persistence Rule):** When the autonomous system pauses due to active expert interaction, canonical control state shall persist that the current pause reason is expert interaction so later status and audit surfaces can explain why autonomous background work is temporarily stopped.
- **FR-OPS-27M (Expert-Interaction Resume Rule):** An expert-interaction pause may end either:
  1. immediately when the expert explicitly issues a resume command, or
  2. immediately when the expert explicitly closes the active `jhc-chat` session, or
  3. automatically when the expert chat session becomes idle long enough under current policy
- **FR-OPS-27N (Safe Auto-Resume Guard Rule):** Automatic resume from expert-interaction pause shall happen only when there is no unresolved clarification question, no pending expert-response dependency, and no other pause condition still active. In the current build, explicit `jhc-chat` close should count as immediate safe auto-resume, while the default idle-based expert-interaction auto-resume timeout should be 15 minutes unless resumed earlier explicitly.
- **FR-OPS-27N1 (Unexpected Chat Exit Resume Rule):** If `jhc-chat` exits unexpectedly rather than through an explicit close, the system should treat that event like an idle-timeout path rather than an explicit close. Resume may occur after the normal safe auto-resume conditions and idle-timeout rules are satisfied.
- **FR-OPS-27O (Expert-Requested Background Task Handoff Rule):** If the expert gives `jhc-chat` a longer investigation, repair, or implementation task, the agent may hand that specific task off into background autonomous execution after it has confirmed the task intent, scope, and expected outcome well enough to proceed safely.
- **FR-OPS-27P (Scoped Resume From Expert Task Handoff Rule):** When a specific expert-requested task is handed off into background execution, the system may resume autonomous execution for that scoped task without requiring the entire expert conversation to remain active. The handoff shall be persisted as canonical work so later heartbeats can continue it.
- **FR-OPS-27Q (Handoff Confirmation Rule):** Before converting an expert-requested task into background autonomous execution, `jhc-chat` shall confirm its understanding of the task in enough detail that the expert can correct misunderstandings before the task begins running in the background.
- **FR-OPS-27R (Explicit Handoff Summary Rule):** The confirmation for an expert-requested background task shall be an explicit summary rather than a one-line acknowledgement. At minimum it should state:
  1. intended scope
  2. expected outputs
  3. important risks, assumptions, or possible blockers
  4. what will and will not be changed or executed
  5. the condition that will mark the task complete
- **FR-OPS-27S (Exclusive Expert-Requested Background Task Rule):** When a longer expert-requested task has been handed into background autonomous execution, that task becomes the active autonomous priority and normal unrelated autonomous pipeline progression shall remain paused until the handed-off task reaches a terminal or explicitly released state.
- **FR-OPS-27T (Expert-Requested Task Failure Return-To-Review Rule):** If a longer expert-requested background task becomes stuck, fails, or reaches an unresolved review-worthy state, the system shall persist that outcome, surface it back into the expert review queue, and make the task available for later expert inspection rather than silently retrying forever.
- **FR-OPS-27U (Resume Regular Operations After Task Failure Rule):** Once a longer expert-requested background task has been returned to expert review because of failure, blockage, or unresolved state, unrelated normal autonomous operations may resume as long as no other active global pause condition still applies.
- **FR-OPS-27V (Default Final-Only Task Reporting Rule):** For a longer expert-requested background task, the default reporting mode should be final-outcome reporting rather than continuous intermediate updates. The agent should surface the task result when it finishes, unless the expert explicitly asks for progress tracking.
- **FR-OPS-27W (Completed Expert-Requested Task Auto-Review Rule):** When a longer expert-requested background task finishes successfully, the system shall automatically surface its result into the expert review queue with the relevant summary, outputs, and artifact references instead of waiting for the expert to ask manually.
- **FR-OPS-27X (Expert-Presence Pause Rule):** Active expert presence through an ongoing `jhc-chat` interaction pauses autonomous background progression under the expert-interaction pause rules. In the current build, that presence begins at chat startup and is not determined by the mere existence of pending review items alone.
- **FR-OPS-27Y (Expert-Absent Continuation Rule):** When the expert is not actively interacting with `jhc-chat`, the Supervisor Agent may continue routine autonomous operations even if review items, completed expert-requested task results, or other expert-facing outputs are waiting in the review queue, as long as no other active global pause condition applies.

### 7.4.8 Current macOS Deployment Shape

- **FR-OPS-28 (Current macOS Deployment Shape):** In the current build, the autonomous control plane shall assume a local single-user macOS deployment with `launchd` heartbeat scheduling, local workspace artifacts, and local canonical SQLite state.
- **FR-OPS-29 (No Run-Once User Mode Requirement):** The current user-facing operating model does not require a separate manual `run-once` product mode. Continuous heartbeat-driven operation is the primary mode, with chat-based pause/resume/stop used to control it.
- **FR-OPS-29A (One-Time Start Registration Model):** The current local start behavior should be one-time registration rather than repeated manual launches. A local helper such as `jhc-agent-start` should load or bootstrap the `launchd` supervisor job, persist `agent_enabled = true`, and then rely on `launchd` heartbeats for continued operation.
- **FR-OPS-29B (Start-Once / Heartbeat-Afterward Rule):** After the initial successful `jhc-agent-start`, normal autonomous operation shall continue through scheduled supervisor heartbeats. Re-running the start helper is not required for ordinary steady-state operation.
- **FR-OPS-29C (Manual Restart Only After Job Failure):** If the `launchd` supervisor job is unloaded, corrupted, or otherwise stops being invoked, the expert may manually run the start helper again to restore the autonomous control plane.
- **FR-OPS-29D (Current Local Helper Entrypoints):** For the current local build, the preferred human-facing helper entrypoints should be:
  1. `jhc-agent-start` to register/start autonomous background operation
  2. `jhc-agent-stop` to disable or unload autonomous background operation
  3. `jhc-chat` to open the Codex-backed chat operator for status, review, and control
- **FR-OPS-29E (Short-Lived Supervisor Process Model):** The supervisor heartbeat process should be short-lived and repeat-invoked rather than implemented as one immortal Codex process. In the current local deployment, the `launchd` job should use a periodic `StartInterval`, run at load, and should not rely on `KeepAlive` to simulate one forever-running agent process.
- **FR-OPS-29E1 (Current Supervisor `launchd` Plist Wiring):** In the current build, `ops/launchd/job-hunt-copilot-supervisor.plist` should minimally set:
  1. `Label = com.jobhuntcopilot.supervisor`
  2. `RunAtLoad = true`
  3. `StartInterval = 5`
  4. `KeepAlive = false`
  5. `WorkingDirectory = <absolute project root>`
  6. `ProgramArguments = [<absolute project root>/bin/jhc-agent-cycle]`
  7. `StandardOutPath = <absolute project root>/ops/logs/supervisor.stdout.log`
  8. `StandardErrorPath = <absolute project root>/ops/logs/supervisor.stderr.log`
  The current build should materialize absolute paths into the plist rather than relying on shell-relative resolution.
- **FR-OPS-29E2 (`bin/jhc-agent-cycle` Wiring):** The current build should include `bin/jhc-agent-cycle` as the single launchd-facing wrapper for one supervisor heartbeat. That wrapper should resolve the project root and execute `python3 scripts/ops/run_supervisor_cycle.py --project-root <absolute project root>`, returning the underlying script exit status.
- **FR-OPS-29E2A (`bin/jhc-feedback-sync-cycle` Wiring):** The current build should include `bin/jhc-feedback-sync-cycle` as the single launchd-facing wrapper for one delayed feedback-sync heartbeat. That wrapper should resolve the project root and execute `python3 scripts/ops/run_feedback_sync.py --project-root <absolute project root>`, returning the underlying script exit status.
- **FR-OPS-29E2B (Deterministic Python Resolution Rule):** The launchd-facing wrappers shall resolve a deterministic Python binary, preferring explicit runtime or Homebrew paths before falling back to ambient `PATH`, so launchd environment drift does not break supervisor or delayed feedback execution.
- **FR-OPS-29E2C (Feedback-Sync `launchd` Plist Wiring):** In the current build, `ops/launchd/job-hunt-copilot-feedback-sync.plist` should minimally set:
  1. `Label = com.jobhuntcopilot.feedback-sync`
  2. `RunAtLoad = true`
  3. `StartInterval = 300`
  4. `KeepAlive = false`
  5. `WorkingDirectory = <absolute project root>`
  6. `ProgramArguments = [<absolute project root>/bin/jhc-feedback-sync-cycle]`
  7. `StandardOutPath = <absolute project root>/ops/logs/feedback-sync.stdout.log`
  8. `StandardErrorPath = <absolute project root>/ops/logs/feedback-sync.stderr.log`
  The current build should materialize absolute paths into that plist rather than relying on shell-relative resolution.
- **FR-OPS-29F (`jhc-agent-start` Behavior):** `jhc-agent-start` should:
  1. resolve the project root and required runtime paths
  2. ensure the runtime identity/policy pack and `launchd` plist are present or materialized
  3. persist control state such as `agent_enabled = true` and clear any ordinary paused/stopped mode
  4. load or bootstrap the `launchd` supervisor job
  5. trigger the first supervisor heartbeat
  It should behave idempotently and must not create duplicate scheduled jobs when run again accidentally.
- **FR-OPS-29F1 (`jhc-agent-start` Current Command Wiring):** In the current build, `jhc-agent-start` should be a shell wrapper that:
  1. resolves the project root from the wrapper location
  2. executes `python3 scripts/ops/build_runtime_pack.py --project-root <absolute project root>`
  3. ensures `ops/launchd/job-hunt-copilot-supervisor.plist` is rendered with absolute current-build paths
  4. writes enabled/running control-state values before starting background execution
  5. runs `launchctl bootstrap gui/$UID <absolute plist path>` when the job is not yet loaded, or an equivalent idempotent load-if-needed step when it already exists
  6. runs `launchctl kickstart -k gui/$UID/com.jobhuntcopilot.supervisor` to trigger the immediate first heartbeat
- **FR-OPS-29F2 (Runtime-Prerequisite Materialization Rule):** The runtime bootstrap and runtime pack shall surface deterministic prerequisites for launchd-executed work, including Python, resume-compilation toolchain discovery, page-count verification tooling such as `pdfinfo`, and sender-identity configuration needed for autonomous outreach.
- **FR-OPS-29G (`jhc-agent-stop` Behavior):** `jhc-agent-stop` should:
  1. persist control state such as `agent_enabled = false` or `agent_mode = stopped`
  2. unload or disable the `launchd` supervisor job so new heartbeats do not start
  3. preserve canonical DB state, incidents, review packets, and artifacts
  4. allow any already-running supervisor cycle to exit at the next safe checkpoint rather than deleting in-flight state
- **FR-OPS-29G1 (`jhc-agent-stop` Current Command Wiring):** In the current build, `jhc-agent-stop` should be a shell wrapper that:
  1. resolves the project root and current plist path
  2. writes disabled/stopped control-state values first
  3. runs `launchctl bootout gui/$UID <absolute plist path>` or an equivalent idempotent unload step
  4. leaves canonical state and persisted artifacts intact for later restart or inspection
- **FR-OPS-29H (`jhc-chat` Behavior):** `jhc-chat` should launch the Codex-backed chat operator for this project directly. It is the terminal entrypoint that opens the correct operator session; the user should not need to open a generic Codex session first and then type `jhc-chat` inside it.
- **FR-OPS-29H1 (`jhc-chat` Current Command Wiring):** In the current build, `jhc-chat` should be a shell wrapper that:
  1. resolves the project root
  2. executes `python3 scripts/ops/chat_session.py begin --project-root <absolute project root>`
  3. launches the Codex interactive entrypoint rooted at the project directory and injects `ops/agent/chat-bootstrap.md` as the startup instructions for that session
  4. on clean explicit close, executes `python3 scripts/ops/chat_session.py end --project-root <absolute project root> --exit-mode explicit_close`
  5. on abnormal session exit, executes `python3 scripts/ops/chat_session.py end --project-root <absolute project root> --exit-mode unexpected_exit`
  This wrapper is the expert-facing terminal command; the expert should not need to manually stage chat-session bookkeeping.
- **FR-OPS-29I (`jhc-chat` Startup Read Rule):** On startup, `jhc-chat` should read:
  1. canonical control state
  2. the runtime identity/policy pack under `ops/agent/`
  3. `ops/agent/progress-log.md`
  4. `ops/agent/ops-plan.yaml`
  5. current incidents
  6. pending expert review packets
  7. the current canonical DB snapshot needed for status and review
- **FR-OPS-29J (`jhc-chat` Startup Status Summary Rule):** After startup state is read and the expert-interaction pause is in effect, `jhc-chat` should proactively present a detailed but bounded dashboard-style startup summary without waiting for the expert's first request. The summary should remain easy to scan and should at least cover current agent mode, major pause reason if any, open incidents count, pending review count, the most important active or recently completed work, and the highest-priority next reviewable or operational items.
- **FR-OPS-29J1 (Startup Dashboard Recent-Work Limit Rule):** In the current build, the startup dashboard should show at most the top 3 most important active or recently completed work items by default. If more relevant items exist, the dashboard should summarize that additional work exists and support expansion on request.
- **FR-OPS-29K (Clean-First Startup Presentation Rule):** The default startup dashboard should stay visually clean. Exact file paths, low-level object IDs, and deeper artifact references should be omitted from the first view unless they are necessary for immediate expert action or the expert asks for deeper detail.
- **FR-OPS-29L (Always-Show Pending Review Section Rule):** The default startup dashboard shall always include a pending expert review section. If no items are waiting, the dashboard should still show that section explicitly with a clear zero/none state rather than omitting it.
- **FR-OPS-29M (Always-Show Open Incidents Section Rule):** The default startup dashboard shall always include an open-incidents section. If no incidents are currently open, the dashboard should still show that section explicitly with a clear zero/none state rather than omitting it.
- **FR-OPS-29N (Always-Show Maintenance State Rule):** The default startup dashboard shall always include current maintenance state. At minimum it should indicate whether daily maintenance is completed, due, or currently running for the current local day.
- **FR-OPS-29O (Always-Show Runtime Duration Metrics Rule):** The default startup dashboard shall always include runtime-duration metrics for:
  1. total autonomous runtime so far today
  2. total autonomous runtime for yesterday
  3. average autonomous runtime per day over a recent rolling window
- **FR-OPS-29O1 (Always-Show Recent Run Counts Rule):** The default startup dashboard shall also include end-to-end run counts for today and yesterday so the expert can quickly see both runtime and actual completed-run throughput.
- **FR-OPS-29O2 (Successful-Run Count Scope Rule):** The startup dashboard run counts for today and yesterday shall count only successful end-to-end runs, not failed, blocked, escalated, or otherwise non-success terminal outcomes.
- **FR-OPS-29O3 (Always-Show Daily Sent-Email Counts Rule):** The default startup dashboard shall also include sent-email counts for today and yesterday so the expert can quickly inspect recent outreach volume.
- **FR-OPS-29O4 (Successful-Send Count Scope Rule):** The startup dashboard sent-email counts for today and yesterday shall count only successful sends, not send attempts that failed before success.
- **FR-OPS-29O5 (Always-Show Daily Bounce Counts Rule):** The default startup dashboard shall also include bounce counts for today and yesterday so the expert can quickly inspect recent delivery risk and outreach quality.
- **FR-OPS-29O6 (Always-Show Daily Reply Counts Rule):** The default startup dashboard shall also include reply counts for today and yesterday so the expert can quickly inspect recent response volume.
- **FR-OPS-29P (Default Runtime Average Window Rule):** In the current build, the default average daily runtime shown in the startup dashboard should use a rolling 7-day local-time window unless the expert explicitly asks for a different window.
- **FR-OPS-29Q (Active Runtime Counting Rule):** The runtime-duration metrics shown in the startup dashboard shall count only active autonomous background execution time. Paused time, expert-interaction chat time, stopped time, and other non-executing intervals shall not be included in those runtime totals.
- **FR-OPS-29R (`jhc-chat` Operating Behavior):** During operation, `jhc-chat` should:
  1. answer status, review, incident, and run-summary questions from persisted state
  2. show concise results directly in chat when small
  3. return file/report paths when the result is large
  4. persist pause, resume, stop, retry, or override intents into canonical control state for the background supervisor to obey
- **FR-OPS-29S (`jhc-chat` Independence Rule):** `jhc-chat` shall remain usable even when the background supervisor is currently paused or stopped. The chat operator is an inspection/control interface over canonical state, not a dependency on an already-running heartbeat process.
- **FR-OPS-29T (Current Sleep/Wake Recovery Rule):** In the current local macOS deployment, laptop sleep shall be treated as a potentially unsafe interruption of background autonomous work rather than as an invisible normal continuation. The first heartbeat after a likely sleep/wake interruption shall perform bounded sleep/wake recovery before any new pipeline progression, automatic sends, or maintenance merges begin.
- **FR-OPS-29U (Current Sleep/Wake Detection Rule):** In the current macOS deployment, sleep/wake interruption detection shall prefer explicit OS-visible power events when available rather than relying only on timing heuristics. The detection stack should be:
  1. primary: OS-visible sleep/wake or power-management event capture from the host platform
  2. secondary: a stale or unexpectedly expired supervisor lease
  3. tertiary: a wall-clock gap greater than 1 hour since the last completed or started supervisor cycle
  If the primary signal is present, the cycle shall enter sleep/wake recovery handling directly. If explicit OS signals are unavailable or inconclusive, the secondary and tertiary checks shall provide conservative fallback detection.
- **FR-OPS-29U1 (Current Sleep/Wake Auditability Rule):** The current build should persist enough sleep/wake evidence for later diagnosis, such as the observed wake timestamp, detection method, and any relevant host power-event reference recorded by the implementation.
- **FR-OPS-29U2 (Current macOS Sleep/Wake Capture Method):** In the current macOS build, the primary host power-event source should be `pmset -g log`. The implementation should parse recent event lines newer than the last recorded check and look specifically for `Sleep`, `Wake`, and `DarkWake` entries. `pmset -g uuid` may be captured as supporting host power-session correlation data when useful, but `pmset -g stats` should be treated as diagnostic only rather than as the authoritative event feed.
- **FR-OPS-29U3 (Current Sleep/Wake Event Reference Rule):** The current build should persist a compact event reference for the most recent detected host power event, such as `pmset-log:{timestamp}:{event_type}`, along with `last_sleep_wake_check_at`, `last_seen_sleep_event_at`, and `last_seen_wake_event_at`, so later cycles can compare new power events without reparsing the full history as canonical state.
- **FR-OPS-29V (Sleep/Wake Recovery Scope Rule):** Sleep/wake recovery shall at minimum:
  1. reconcile supervisor lease state
  2. inspect any in-progress or recently interrupted pipeline runs
  3. inspect any side-effectful work that may have been interrupted near sleep, especially send-related work, provider-driven progression, and maintenance merges
  4. persist a recovery summary and any resulting incidents or pause reasons
  5. avoid starting unrelated new autonomous work until that recovery pass is complete
- **FR-OPS-29V1 (Interrupted-Send Reconciliation Rule):** If sleep/wake recovery finds a send that may have been interrupted mid-step, the Supervisor Agent shall first query authoritative mailbox/sent-state evidence and any local send artifact state to determine whether the send actually completed. Only if that reconciliation still leaves the send state ambiguous shall the system persist an incident and pause or escalate rather than guessing or silently resending.
- **FR-OPS-29W (Strict Post-Wake Resumption Rule):** The first post-wake recovery cycle should be recovery-focused only. If recovery succeeds cleanly, ordinary autonomous progression may resume on a later heartbeat. If recovery finds ambiguity or unsafe state, the system shall persist the issue and pause or escalate rather than guessing.
- **FR-OPS-29X (No Mandatory Pre-Sleep Expert Check Rule):** The current build does not require the expert to ask permission or run a special pre-close command before closing the laptop. Normal laptop close/sleep is allowed. The protection comes from strict post-wake recovery, lease handling, and conservative resumption rules rather than a mandatory human pre-sleep ritual.

---

## 8. Non-Functional Requirements (Quality Attributes)

- **NFR-01 Scalability:** Support growth in number of roles/leads without redesign.
- **NFR-02 Reliability:** Recover cleanly from provider/API failures and partial-step failures.
- **NFR-03 Performance:** Produce actionable outputs in interactive time for a single role run.
- **NFR-04 Maintainability:** Keep components modular and easy to change.
- **NFR-05 Security:** Protect credentials and personal data.
- **NFR-06 Observability:** Logs/status artifacts must support debugging and post-run analysis.
- **NFR-07 Fault Tolerance:** Continue with fallbacks when one provider/path fails.
- **NFR-08 Data Consistency:** State transitions and artifacts must not conflict.
- **NFR-09 Context Reconstructability:** Autonomous operation must be resumable from persisted state so fresh heartbeat contexts can safely continue in-progress work without relying on prior transient prompts.

---

## 9. Communication and Internal Organization

### 9.1 Communication Mechanisms
1. Artifact-based file handoff (file-to-file communication) is the primary mechanism.
2. Each component publishes structured output artifacts that act as contracts for downstream components.
3. Downstream components read upstream artifacts and extract required fields without direct runtime coupling.
4. Current transport is local filesystem paths and manifest files (IPO model).
5. The central SQLite database stores state and artifact references, but it does not replace file-based runtime handoff.
6. Current named machine-oriented runtime handoff artifacts are:
   - Tailoring -> Outreach: workspace `meta.yaml`
   - Discovery -> Drafting: `discovery_result.json`
   - Drafting/Sending -> Delivery Feedback: `send_result.json`
   - Delivery Feedback -> downstream consumers: `delivery_outcome.json`
   - Supervisor Agent -> expert review: `review_packet.md` or equivalent packet artifact under `ops/review-packets/`
7. `email_draft.md` is a human-readable companion artifact for inspection and audit, not the sole machine contract for downstream automation.

### 9.2 Internal Organization
1. Ingestion layer (input normalization)
2. Processing layer (signal extraction/reasoning)
3. Persistence layer (artifacts/state)
4. Control layer (supervisor heartbeat, review, repair, escalation)
5. Delivery layer (external actions: discover/draft/send)

### 9.3 Caching and Learning
1. Store discovery outcomes and bounce outcomes
2. Preserve outcome history so future discovery confidence and pattern quality can be improved in later iterations

---

## 10. Constraints

1. Must not fabricate experience or credentials.
2. Must honor explicit hard constraints from JD (especially work authorization).
3. Must preserve source context sufficiently for audit.
4. Must remain operational with imperfect external providers.
5. Must not persist secrets or tokens into canonical state or runtime handoff artifacts.
6. Must keep autonomous outreach within the safety boundaries defined by automated tailoring approval, repeat-contact rules, escalation rules, and evidence-grounding rules.
7. Must not require a multi-user security model in the current single-user phase.
8. Must not depend on one long-lived LLM conversation as the only source of operational memory.
9. Tracked public tests, docs, and example artifacts must not include real third-party personal contact data unless explicit consent and purpose are documented.
10. Runtime-generated mirrors and other mutable operational byproducts must live under ignored paths or otherwise avoid dirtying the tracked worktree during ordinary operation.

---

## 11. Assumptions

1. User can supply basic job and lead context.
2. Candidate has at least some evidence matching target roles.
3. Provider APIs can be rate-limited/credit-limited and may fail intermittently.
4. This spec is iterative and expected to evolve.
5. The current autonomous deployment target is a local single-user macOS machine where `launchd` is available.

---

## 12. Acceptance Criteria

## 12.1 Resume Tailoring
1. Given a JD, system generates structured signal artifact with must-have vs nice-to-have split.
2. System applies the explicit hard-disqualifier policy and flags hard-ineligible leads early.
3. If a posting is hard-ineligible, the system persists `applications/{company}/{role}/eligibility.yaml`, sets posting status to `hard_ineligible`, and does not continue into workspace bootstrap, Step 3 to Step 7 artifacts, or outreach handoff.
4. Tailoring workspace contains `meta.yaml`, mirrored context files, `resume.tex`, a scope-baseline snapshot, and intelligence artifacts.
5. Workspace bootstrap materializes the selected base resume track into workspace `resume.tex`, creates `scope-baseline.resume.tex` from the pre-edit workspace state, and mirrors the linked JD context before Step 3 begins.
6. In this build, the effective tailoring context is the derived `jd.md` plus posting-level canonical state; `raw/source.md` may be kept for traceability when that artifact exists for the lead mode, but it is not a required direct tailoring input.
7. In this build, mirrored `post.md` and `poster-profile.md` files may exist in the tailoring workspace, but the core tailoring decision path does not depend on them being present or semantically normalized.
8. Scope constraints recorded in `meta.yaml` are enforced before finalize/compile.
9. Tailoring run persists the current step artifacts for JD signals, evidence mapping, candidate edits, and verification.
10. Once bootstrap begins, a `resume_tailoring_runs` row is created with `tailoring_status = in_progress` and `resume_review_status = not_ready`.
11. Finalize requires valid Step 3, Step 4, Step 6, and Step 7 artifacts, and Step 7 must not remain `pending`.
12. Finalize applies the selected Step 6 edit payload to workspace `resume.tex`, runs scope validation, compiles the PDF, and verifies one-page output before marking the run complete.
13. Successful finalize moves the run to `tailoring_status = tailored` and `resume_review_status = resume_review_pending`.
14. Tailored output includes traceable evidence mapping.
15. Tailoring run uses the candidate master profile file and surfaces which master-profile evidence was used.
16. Final output compiles to `Achyutaram Sonti.pdf` and remains one page.
17. Missing eligibility data is treated as `unknown` and proceeds without hard failure.
18. Eligibility audit output is persisted with status, triggered rules, and supporting evidence snippets.
19. Owner overrides (if any) are persisted with reason and timestamp.
20. Current default editable scope is respected unless `meta.yaml` explicitly changes it.
21. Current Step 6 payload contains structured summary, technical-skills, software-engineer stack line, and exactly 4 SWE bullets.
22. SWE bullets respect current character-budget and LaTeX-safety constraints closely enough to remain compile-safe and page-safe.
23. Verification evaluates at least proof-grounding, JD coverage, metric sanity, line budget, and compile/page-readiness checks and records explicit notes for failures or revision-required cases.
24. If evidence is insufficient or constraints block a requested edit, verification returns explicit blockers or revision guidance rather than fabricated claims.
25. Base resume track is selected automatically from JD/context signals and persisted in workspace metadata.
26. For role-targeted flow, the tailored resume stops at the mandatory agent-review gate before downstream outreach work begins.
27. A review rejection followed by retailoring creates a new `resume_tailoring_runs` row rather than overwriting the prior run history.
28. The Tailoring-to-Outreach handoff is DB-first by `job_posting_id`, with `meta.yaml` and referenced resume artifacts available as supporting runtime references and audit surfaces.

## 12.2 Email Discovery
1. Given a role-targeted posting that needs internal contacts, the system can run Apollo-first company-scoped people search and persist the broad candidate search result for the posting.
2. The Apollo path resolves the company to an organization record first and uses the resolved `organization_id` as the preferred anchor for people search when available.
3. `people_search_result.json` is produced and preserves the resolved company record, applied search filters, and the broad candidate list returned by people search.
4. The system correctly handles sparse Apollo search results, including candidates whose search-stage identity is only a partial or obfuscated display name plus stable Apollo person ID.
5. Shortlist-stage contact materialization can proceed from stable provider identity such as Apollo person ID even before a non-obfuscated full name is known.
6. After the broad search pass, the system enriches only shortlisted contacts that need fuller identity, LinkedIn URL, or a usable work email rather than enriching every broad-search candidate by default.
7. In autonomous role-targeted mode, the initial enrichment shortlist is capped at 30 contacts and aims to cover recruiter, manager, and engineer recipient classes before lower-priority internals are used.
8. When a saved broad Apollo people-search artifact exists, the system can later replay that artifact to backfill additional shortlisted contacts up to the current 30-contact limit without rerunning external people search immediately.
9. When a location-filtered Apollo search yields no useful contacts, the search logic can retry with the location constraint relaxed rather than dead-ending on the first miss.
10. When Apollo enrichment yields a LinkedIn URL for a shortlisted contact, the system can extract and persist a structured public-profile `recipient_profile.json` snapshot before drafting.
11. If Apollo enrichment returns a usable work email for a selected contact, the system can skip the separate email-finder cascade for that contact.
12. If enrichment does not return a usable work email, that contact can continue into the separate person-scoped email-discovery path.
13. If a shortlisted candidate becomes a terminal dead end at the enrichment boundary and will not continue into email discovery or outreach, that candidate is dropped from canonical shortlist state rather than being retained as dead contact state.
14. Given linked contact input, the system returns a discovered working email or an explicit unresolved/not-found outcome.
15. Provider-specific `HTTP 200` no-match responses are normalized correctly, such as Prospeo `NO_MATCH`, GetProspect `success = false` with `status = not_found`, and Hunter responses with `data.email = null`.
16. Discovery reuses an already known working email for the same clearly identified contact instead of rerunning provider discovery unnecessarily.
17. Attempts, outcomes, provider-budget history, unresolved review data, and bounced-email review data are queryable from the same central SQLite store.
18. Pattern-learning data is preserved so discovery quality can be improved in later iterations without redesigning storage.
19. System can perform high-confidence cached discovery for eligible domains once readiness criteria are met.
20. Pre-send confidence is provider-verified confidence.
21. Post-send confidence is set to 100% only for sent emails with no bounce observed in the configured feedback window.
22. Per-provider credit balances are auto-updated after each provider usage event when the provider exposes a reliable balance signal, and otherwise remain explicitly unknown rather than synthetic.
23. Combined budget totals, when shown, are derived only from known provider balances rather than fabricated placeholders.
24. Provider exhaustion automatically triggers fallback to remaining providers in cascade order.
25. The autonomous LinkedIn-alert mode can use Apollo to gather a broad set of engineering managers, software engineers, recruiters, and other potentially helpful internal people before later filtering.
26. `discovery_result.json` is produced as the machine handoff artifact for Drafting and includes the shared contract envelope, relevant root IDs, discovery outcome, discovered email when found, and the recipient-profile artifact reference when one exists.

## 12.3 Email Drafting and Sending
1. Given role-targeted context, system produces a personalized outreach draft using job-posting context, tailored-resume context, and a discovered working email, with recipient-profile context incorporated when it is available and genuinely useful.
2. Given general learning-outreach context, system can produce a contact-rooted outreach draft without requiring a tailored resume or job-posting linkage.
3. Once ready untouched contacts for a posting have been drafted and persisted, send execution may begin for the currently eligible active send slice when the current pacing rules allow each send; otherwise sends are delayed to the earliest allowed send slots.
4. Draft content demonstrably uses the relevant available context for the current outreach mode rather than generic generation alone.
5. When `recipient_profile.json` exists for the selected contact, drafting can use that persisted profile snapshot to ground `why this person` and work-centric personalization.
6. When only sparse search/enrichment context exists and no richer recipient-profile snapshot is available, the default v4 template still drafts correctly using role/team/work-area context without inventing a person-specific background hook.
7. Draft can be rendered with rich HTML formatting while preserving readability.
8. The current shared role-targeted template includes a forwardable summary snippet/block by default because the outreach posture asks for routing or forwarding help; general learning outreach does not require that snippet by default.
9. `email_draft.md` is available as the human-readable companion artifact, while `send_result.json` is produced as the machine handoff artifact with the shared contract envelope and relevant IDs.
10. Repeat-outreach cases that require interpretation of prior outreach are not auto-sent and instead surface for user review.
11. If the same canonical contact appears on multiple postings at the same company, automatic role-targeted outreach uses that person at most once after an actual successful send, and later postings must continue with alternate company contacts when available.
12. In the autonomous LinkedIn-alert mode, the default outreach objective is to ask discovered contacts for connection or routing help to the right hiring person rather than assuming the discovered recipient is already the exact target.
13. Autonomous role-targeted sending respects the per-posting cap of at most 4 emails per posting per day, and uses a randomized 6 to 10 minute gap between any two automatic sends rather than a fixed interval.
14. Autonomous role-targeted sending does not impose a separate global cross-company daily send cap in this build.
15. The default autonomous active send slice for one posting prefers one recruiter, one manager-adjacent contact, and one team-adjacent engineer when those recipient classes are available.
16. The system preserves enough outreach tracking state to support manual follow-up decisions, including recipient type, outreach mode, last touch date, next follow-up date, follow-up state, and notes.
17. The current imported playbook supports at least the core one-step recruiter / team-adjacent style plus the imported hiring-manager and ASU-alumni legacy prompt styles.
18. When the imported legacy playbook is selected, the draft can use the imported metric-led evidence logic, exact-skill-overlap grounding, and markdown-like forwardable snippet formatting without inventing skills or raw HTML.
19. The current v4 default shared role-targeted template opens from a JD-faithful role / team / work-area hook rather than requiring recipient-background hooks, includes an explicit `why I am reaching out to you` line, includes one proof point of fit, includes the Job Hunt Copilot / AI-agent block, uses one 15-minute Zoom ask, and places the forwardable snippet directly below the routing-help line.
20. In the current v4 default shared role-targeted template, the forwardable snippet remains factual, compact, and JD-aware, and it uses one strongest fit summary plus one strongest supporting proof fragment rather than a generic skills list.
21. The current default shared role-targeted body does not rely on an education-status sentence such as `I am currently finishing my MS ...` as a default paragraph.

## 12.4 Delivery Feedback
1. Post-send outcomes are persisted into the central SQLite database as event history rather than only a latest overwritten status.
2. Delivery Feedback captures the current high-level states `sent`, `bounced`, `not_bounced`, and `replied`, with timestamps for each event.
3. Bounced, reply, and other delivery-feedback event data are queryable without separate long-term JSON stores.
4. `delivery_outcome.json` is produced as the machine handoff artifact with the shared contract envelope, relevant IDs, event type/state, and event timestamp.
5. Bounced and not-bounced outcomes are available to Email Discovery as reusable feedback, while replies remain retained for review but outside the current discovery-learning loop.
6. Delayed bounce emails and replies can be detected through mailbox observation without requiring the human user to manually report them.
7. Delivery Feedback uses one immediate post-send mailbox poll plus delayed scheduled polling every 5 minutes during a 30-minute bounce-observation window.
8. In the current local single-user deployment, a separate `launchd`-managed feedback-sync worker owns delayed scheduled mailbox polling rather than the ordinary supervisor heartbeat.
9. The supervisor reads persisted delivery-feedback state and event history to keep `delivery_feedback` runs pending or complete them; it does not own delayed mailbox polling inline.
10. Scheduled feedback-sync runs are queryable so the owner can verify that delayed feedback capture is actually operating.
11. Bounced outcomes block future automatic reuse of that bounced email identity and directly responsible provider result, but automatic posting-level bounce recovery remains out of scope for the current build.

## 12.5 System-Level
1. Overall canonical system state is queryable from `job_hunt_copilot.db` without reconstructing the pipeline from ad hoc file inspection.
2. The central database exposes the primary entity states for `linkedin_leads`, `job_postings`, and `contacts`, plus relationship state for `linkedin_lead_contacts` and `job_posting_contacts`.
3. Runtime file artifacts remain usable as component handoff contracts without becoming the canonical source of system state.
4. Machine handoff artifacts use structured formats and include the shared contract envelope fields: `contract_version`, `produced_at`, `producer_component`, `result`, and blocked/failed reason details when applicable.
5. Machine handoff artifacts carry the relevant stable root identifiers such as `lead_id`, `job_posting_id`, `contact_id`, and `outreach_message_id` when those objects exist at that boundary.
6. Review surfaces are queryable for at least: `resume_review_pending`, `requires_contacts`, unresolved discovery, bounced emails, repeat-outreach review, blocked/failed unresolved cases, pending expert review packets, and open agent incidents.
7. When the user indicates they are ready to review, the AI agent can surface the current review items from statuses, review queues, and linked artifacts.
8. Major state transitions for `linkedin_leads`, `job_postings`, `contacts`, `linkedin_lead_contacts`, and `job_posting_contacts` are auditable from the central system state.
9. Owner overrides are queryable with previous value, new value, reason, and timestamp.
10. Retry attempts and retry exhaustion are queryable for later review.
11. External provider identifiers and mailbox identifiers may be retained as secondary references, but internal canonical identifiers remain the authoritative linkage keys across the system.
12. The system can explain important decisions from persisted internal artifacts and state without requiring a fresh fetch from the original external source.
13. External-integration failures appear as normalized blocked/failed reasons in internal state rather than only as raw vendor-specific errors.
14. Secrets and tokens do not appear in canonical DB records, runtime handoff artifacts, or normal review surfaces.
15. Autonomous outreach remains bounded by evidence-grounding, repeat-contact review, the mandatory agent-review gate, and explicit escalation rules for role-targeted flow.
16. Persisted review surfaces expose only workflow-relevant contact/context data rather than unnecessarily broad personal-data copies.
17. This build can be operated conversationally through the AI agent without requiring a fixed user command catalog.
18. A lead can arrive through manual browser capture, the repo-local paste fallback, or autonomous Gmail job-alert intake, and each path converges into one canonical lead workspace.
19. Manual browser capture can preserve selected text, full-page text, source URLs, and capture order in source-mode artifacts while still producing one canonical `raw/source.md`.
20. Autonomous Gmail-alert intake persists the alert snapshot, prefers the plain-text mailbox body for parsing, uses durable Gmail history checkpoints for incremental polling when available, attempts JD fetch when possible, and records JD-fetch provenance for later review.
21. In the autonomous mode, each parsed LinkedIn alert job card becomes a candidate role-targeted lead, and the LinkedIn guest JD is the default common tailoring input when it is available.
22. If the parsed Gmail alert-card company or role title materially disagrees with the fetched LinkedIn JD identity, the lead is surfaced for user review and downstream canonical company/role materialization remains blocked until resolved.
23. Minor normalization differences such as `Google` vs `Google LLC` or `SWE II` vs `Software Engineer II` do not by themselves trigger review.
24. Company-website and careers-page resolution in the autonomous mode is persisted as best-effort enrichment and provenance, even when exact same-role recovery fails.
25. In the autonomous mode, the full recovered JD is persisted to `jd.md` before later structured extraction or tailoring interpretation begins.
26. In the autonomous mode, structured eligibility and tailoring artifacts are derived from persisted markdown/context files rather than only from transient fetch responses.
27. Once a valid non-mismatched company and role are known, downstream posting files are materialized in a company/role-scoped workspace.
28. The autonomous mode uses Apollo to gather broad internal contact coverage before later filtering, ranking, and pacing decisions narrow the actual active send slice.
29. Digest-summary headers or summary-only Gmail cards are filtered and do not materialize as canonical leads or postings.
30. If autonomous Gmail intake encounters a duplicate canonical lead identity during fan-out, it canonicalizes or refreshes the existing lead instead of crashing on duplicate creation.
31. For lead modes that materialize `raw/source.md`, `LinkedIn Scraping` runs a deterministic first pass over that artifact, persists `source-split.yaml`, `source-split-review.yaml`, and `lead-manifest.yaml`, and keeps those artifacts queryable from `artifact_records`.
32. Ambiguous lead splits remain reviewable and may use an optional AI second pass only after the rule-based review flags ambiguity and only if that second pass improves confidence.
33. Recruiter-authored lead dumps that say `We're hiring` or similar plain-language variants are still recognized as valid posts by the deterministic first pass.
34. Networking-relevant copied post hints, such as alumni-count lines like `1 school alumni works here`, are preserved in the extracted post when they may affect outreach strategy, prioritization, or contact selection.

## 12.5A Supervisor Agent
1. The build includes a first-class `Operations / Supervisor Agent` component that runs the autonomous control loop in the background while exposing a chat-first operating interface to the expert.
2. The current local macOS deployment can schedule the supervisor heartbeat through `launchd` every 5 seconds.
3. Each heartbeat can create a fresh LLM context, and that fresh context is rebuilt from canonical state, runtime policy/identity artifacts, selected work-unit state, and local evidence rather than relying on the previous heartbeat's transient prompt memory.
4. A fresh heartbeat does not create a fresh posting run; the system persists durable `pipeline_runs` that survive across many heartbeat cycles.
5. The supervisor prevents overlapping cycles through a persisted lease/lock mechanism, and a new heartbeat does not start a second active cycle while a valid earlier lease remains active.
6. If a lease becomes stale, a later heartbeat can safely reclaim it and resume from canonical state.
7. The supervisor persists heartbeat audit rows, pipeline runs, incidents, control state, expert review packets, and expert review decisions in canonical state rather than only in ephemeral logs.
8. The supervisor honors persisted control state for pause, resume, stop, or similar operating modes even if the originating chat session no longer exists.
9. Mandatory pipeline review gates are performed by the AI agent and record explicit review outcomes before downstream progression continues.
10. After each review-worthy terminal end-to-end role-targeted run outcome, the supervisor produces an expert review packet summarizing outcomes, failures, retries, incidents, and recommended next actions.
11. The expert can ask conversationally for pending review items, incidents, run summaries, or report locations, and the agent can either answer in chat or provide the relevant file path.
12. The supervisor may perform bounded repair automatically, but unresolved repeated failures or riskier changes are surfaced as incidents and escalated for expert review.
13. Any unresolved `critical` incident affecting send safety, duplicate-send risk, credential/secrets handling, or canonical-state integrity triggers an automatic supervisor pause.
14. Three unresolved incidents of the same type in the same stage/provider/operational area within 45 minutes also trigger an automatic supervisor pause.
15. When auto-pause triggers, new pipeline runs and new automatic sends stop, the pause reason is persisted, and the incidents remain visible for expert review.
16. In the current local macOS deployment, `jhc-agent-start` is a one-time registration/start action for the `launchd` supervisor job rather than a command that must be rerun for every heartbeat.
17. After successful startup, ongoing autonomous operation continues through `launchd` heartbeats until the expert pauses/stops it or the scheduler/job itself breaks.
18. In the current local build, the preferred human-facing entrypoints are `jhc-agent-start`, `jhc-agent-stop`, and `jhc-chat`.
19. `jhc-agent-start` is idempotent: it enables autonomous background operation, bootstraps or loads the `launchd` supervisor job, and does not create duplicate scheduler registrations when rerun.
20. `jhc-agent-stop` disables future supervisor heartbeats while preserving canonical state, incidents, review packets, and existing artifacts.
21. `jhc-chat` is the terminal entrypoint that opens the project-specific Codex chat operator directly rather than being a command typed inside an already-open generic Codex session.
22. On startup, `jhc-chat` reads current control state, runtime identity/policy files, the rolling progress log, the near-term ops plan, incidents, pending review packets, and the relevant canonical DB snapshot before answering expert questions or accepting control intents.
23. After startup, `jhc-chat` proactively shows a detailed but bounded dashboard-style summary covering current mode, major pause reason if any, open incidents, pending review count, the most important active or recently completed work, and the highest-priority next reviewable or operational items.
24. The startup dashboard shows at most the top 3 most important active or recently completed work items by default before indicating that more can be expanded on request.
25. The default startup dashboard keeps the first view clean and does not dump exact file paths, low-level object IDs, or deep artifact references unless they are needed immediately or the expert asks for more detail.
26. The startup dashboard always includes a pending expert review section, even when the current value is explicitly zero or none.
27. The startup dashboard always includes an open-incidents section, even when the current value is explicitly zero or none.
28. The startup dashboard always includes current maintenance state, including whether daily maintenance is completed, due, or currently running.
29. The startup dashboard always includes autonomous runtime totals for today, yesterday, and average daily runtime over the default recent rolling window.
30. Those runtime totals count only active autonomous background execution time, not paused expert-interaction time or other non-executing intervals.
31. The startup dashboard also includes successful end-to-end run counts for today and yesterday.
32. The startup dashboard also includes successful sent-email counts for today and yesterday.
33. The startup dashboard also includes bounce counts for today and yesterday.
34. The startup dashboard also includes reply counts for today and yesterday.
35. `jhc-chat` remains usable even when the background supervisor is paused or stopped.
36. For the current role-targeted flow, at most one non-terminal `pipeline_run` exists for the same `job_posting_id` at a time.
37. A successful, failed, blocked, or escalated review-worthy `pipeline_run` generates both `review_packet.json` and `review_packet.md`, and the run's `review_packet_status` becomes `pending_expert_review`.
38. Expert review packets are relevance-shaped: early failures or blocked/escalated runs may use a lighter packet that includes only the failure-relevant details, evidence, and review questions.
39. `agent_mode = paused` blocks new pipeline progression and new automatic sends, but safe observational work such as feedback polling and chat-based inspection may still continue.
40. `agent_mode = stopped` disables background autonomous execution until restarted, while chat-based inspection remains available.
41. The Supervisor Agent chooses only from the registered bounded action catalog for autonomous work and validates prerequisites and expected outputs around each action.
42. One supervisor cycle focuses on one primary work unit by default, and a later heartbeat defers if the supervisor lease is still held by an active cycle.
43. `jhc-chat` routes global pause/resume/stop through control state, routes object-specific overrides through canonical object updates plus `override_events`, and does not mutate state for read-only inspection requests.
44. While autonomous operation remains enabled, the Supervisor Agent completes one bounded maintenance cycle at least once per calendar day in the machine's local timezone.
45. The agent prefers to schedule the daily maintenance cycle at a natural end-to-end run boundary, after one completed run and before the next new run begins, but it does not skip the required daily maintenance cycle.
46. Autonomous code/config changes are produced only during a maintenance cycle, are captured through git-backed change tracking, and are limited to at most one autonomous change batch per daily maintenance cycle unless the expert explicitly overrides that limit.
47. The agent does not interrupt an active end-to-end run solely to satisfy the daily maintenance requirement; if maintenance becomes due mid-run, it waits until the next safe run boundary.
48. Autonomous maintenance changes are not applied directly to the main working tree; each change batch is prepared on a dedicated git-tracked maintenance branch or equivalent isolated change unit.
49. Each autonomous maintenance change batch produces an explicit git commit or equivalent durable git-tracked checkpoint with enough metadata to inspect, validate, and revert the change if needed.
50. The default autonomous maintenance git workflow is dedicated branch -> branch commit -> normal merge commit after approval and validation.
51. The canonical maintenance approval outcome is persisted in SQLite state, with a companion maintenance artifact file for human inspection.
52. Companion maintenance artifacts are created for every autonomous maintenance batch, including approved, merged, failed, and unapproved batches.
53. An autonomous maintenance change batch is merged into the main operational code path only after the required maintenance validation/testing pass succeeds and the change batch receives an explicit maintenance approval outcome under current agent policy.
54. If maintenance validation fails or approval is not granted, the isolated maintenance change batch does not become operational and its outcome remains persisted for later inspection.
55. After a maintenance change batch is successfully validated, approved, and merged, the next supervisor heartbeats may use the updated code/config automatically without waiting for a separate expert hold.
56. Proper maintenance testing includes both change-scoped validation for the modified code/config and a broader full-project validation layer before the change can be approved and merged.
57. Failed or unapproved autonomous maintenance branches remain retained with their validation evidence and changed-file summary for later expert inspection rather than being silently discarded.
58. When the expert asks what changed or what needs review, autonomous maintenance change batches and their outcomes are included in the returned change/update summary.
59. By default, `show me items for review` returns review items ordered by creation time with the newest items first.
60. By default, `show me items for review` presents items grouped by item type, and within each group the newest items appear first.
61. The default review-group order is: expert review packets, failed/unresolved expert-requested background tasks, autonomous maintenance change batches, then open incidents.
62. Within each default review group, the first presentation is a compact summary list, with deeper detail shown only when the expert asks for expansion or selects an item.
63. The default compact review presentation shows at most 5 items per group before indicating that more items are available on request.
64. By default, expert-facing change/update summaries cover the period since the last completed expert review unless the expert explicitly asks for a broader history window.
65. Expert review feedback, correction, or override becomes live operating guidance immediately once persisted through the approved interface.
66. By default, a direct expert override affects the current object and also becomes future-facing operating guidance unless the expert explicitly scopes it more narrowly.
67. Future-facing expert guidance is generalized to similar future cases using agent judgment unless the expert explicitly narrows the scope.
68. When the agent applies generalized future guidance, it persists lineage to the expert review or override decision that taught that behavior.
69. If the agent is not sufficiently confident that a future case is similar enough for generalized expert guidance, it stops and asks the expert rather than guessing.
70. If a new expert instruction conflicts materially with standing policy or an older persisted expert instruction, the agent does not silently choose one; it asks the expert for clarification.
71. A material conflict in expert guidance pauses the whole autonomous system until the expert resolves the conflict.
72. Even when the autonomous system is paused, auto-paused, or waiting on guidance clarification, `jhc-chat` remains fully available for inspection, reports, explanation, clarification, and approved control actions.
73. When the expert actively engages the system through `jhc-chat`, autonomous background progression pauses so the agent can focus on the expert without concurrent autonomous work.
74. If an expert interaction begins during an active supervisor cycle, the cycle stops at the next strict safe checkpoint rather than being torn down mid-step.
75. During an expert-interaction pause, no new autonomous sends, new pipeline runs, new provider-driven progression steps, or new maintenance merges begin unless the expert explicitly directs them.
76. During an expert-interaction pause, the system still allows inspection, reports, explanations, review presentation, and persistence of expert decisions/overrides through `jhc-chat`.
77. The system persists expert interaction as the pause reason so later status and audit views explain why autonomous background work is paused.
78. Safe automatic resume does not happen while any clarification, pending expert response, or other active pause condition still exists; explicit `jhc-chat` close counts as immediate safe auto-resume, and the default idle timeout is 15 minutes unless resumed earlier explicitly.
79. If `jhc-chat` exits unexpectedly, the system treats that like the idle-timeout resume path rather than immediate explicit close.
80. A longer expert-requested investigation, repair, or implementation task may be handed off from `jhc-chat` into background autonomous execution after the agent confirms it understood the request well enough to proceed safely.
81. That handoff is persisted as canonical work so later heartbeats can continue it without keeping the interactive chat session open.
82. Before handing an expert-requested task into background execution, `jhc-chat` gives an explicit summary covering scope, expected outputs, important risks/assumptions, what will and will not be changed or executed, and the completion condition.
83. Once a longer expert-requested task is handed into background autonomous execution, unrelated normal autonomous pipeline work remains paused until that task finishes or is explicitly released.
84. If that expert-requested background task becomes stuck, fails, or reaches an unresolved review-worthy state, it is returned to expert review with persisted evidence instead of being retried indefinitely in the background.
85. After such a failed or unresolved expert-requested task is returned to review, unrelated regular autonomous operations may continue as long as no other global pause condition still applies.
86. By default, a longer expert-requested background task surfaces its result when it finishes rather than streaming intermediate progress, unless the expert explicitly asks for progress tracking.
87. When a longer expert-requested background task finishes successfully, its result is automatically surfaced into the expert review queue with the relevant summary and outputs.
88. Opening `jhc-chat` itself immediately counts as expert presence and pauses autonomous background work, even before the first substantive message.
89. Pending review items by themselves do not count as expert presence.
90. When the expert is not actively interacting with `jhc-chat`, routine autonomous operations may continue even if review items or completed expert-requested task results are waiting, as long as no other global pause condition applies.
91. A strict safe checkpoint means no new side-effectful step begins after the pause is observed, and if a step is already in progress the agent does only the minimum validation/writeback needed to leave state and external side effects coherent before stopping.
92. The default autonomous maintenance branch format is `maintenance/{YYYYMMDD-local}-{maintenance_change_batch_id}-{scope_slug}`.
93. The default autonomous maintenance merge uses a normal merge commit whose subject follows `merge(maintenance): {maintenance_change_batch_id} {scope_slug}`.
94. `maintenance_change.json` exists for every autonomous maintenance batch and includes the current minimum machine-readable audit fields for scope, branch, commits, approval outcome, validation, related incidents/review packets, and changed files.
95. The build includes `ops/agent/progress-log.md` as a compact rolling operational handoff note for fresh supervisor or chat sessions, and that file is treated as a convenience summary rather than canonical truth over DB state.
96. The build includes `ops/agent/ops-plan.yaml` as the current near-term operating plan covering active priorities, recurring issue themes, watch items, weak areas, and maintenance backlog.
97. `ops/agent/ops-plan.yaml` remains a near-term operating plan rather than a full history dump and keeps the top 5 active priorities plus separate sections for watch items, maintenance backlog, and concise weak/recurring issue notes.
98. `ops/agent/progress-log.md` stays compact by default and keeps one current summary, the last 20 meaningful detailed entries, and compact daily rollups for the last 7 local calendar days rather than unbounded history.
99. Each supervisor cycle persists a compact `context_snapshot.json` that records the selected work unit, key state, evidence references, and the small exact evidence excerpts that were actually supplied to the reasoning call when those excerpts materially affected the decision.
100. `supervisor_cycles` can reference the persisted cycle context snapshot path so the expert can later inspect what context the cycle used without reconstructing the whole prompt manually.
101. `agent_mode = replanning` exists as a bounded planning mode distinct from `running`, `paused`, and `stopped`.
102. During replanning, no new pipeline runs, new automatic sends, or new maintenance merges begin, but safe observational work such as feedback polling, report generation, and chat-based inspection may continue.
103. Replanning refreshes the near-term ops plan, appends a progress-log entry explaining why priorities changed, and leaves enough persisted evidence for later expert review.
104. Automatically triggered replanning does not run more than once in any rolling 6-hour window unless the expert explicitly requests another replanning pass sooner.
105. Replanning can be triggered by explicit expert request or by repeated drift signals such as repeated auto-pauses, prolonged service-goal misses, or repeated failed maintenance in the same operational area; after replanning completes, the agent returns to normal running only if no other pause or stop condition still applies.
106. In the current local macOS deployment, likely laptop sleep/wake interruption is treated as a recovery-worthy event rather than as a fully transparent continuation of ordinary autonomous work.
107. The first heartbeat after a likely sleep/wake interruption runs bounded sleep/wake recovery before any new pipeline progression, automatic sends, or maintenance merges begin.
108. Sleep/wake recovery at minimum reconciles leases, inspects in-progress or recently interrupted runs, checks interrupted side-effectful work such as sending/provider progression/maintenance merges, and persists a recovery summary plus any resulting incidents or pause reasons.
109. If sleep/wake recovery finds a possibly interrupted send, it first queries authoritative mailbox/sent-state evidence plus local send artifacts to determine whether the send actually completed; only unresolved ambiguity after that reconciliation becomes an incident or pause/escalation condition.
110. If post-wake recovery is clean, ordinary autonomous progression resumes only on a later heartbeat rather than continuing blindly in the same recovery-focused cycle.
111. If post-wake recovery finds ambiguity or unsafe state, the agent persists the issue and pauses or escalates rather than guessing; the expert is not required to perform a special pre-sleep command before closing the laptop.
112. If explicit OS sleep/wake evidence is unavailable, a wall-clock gap greater than 1 hour since the last completed or started supervisor cycle counts as the conservative fallback threshold for forcing sleep/wake recovery.
113. `ops/agent/progress-log.md` follows a stable current-build Markdown layout with `Current Summary`, `Current Blockers`, `Next Likely Action`, `Latest Replan / Maintenance Note`, `Recent Entries`, and `Daily Rollups`, and the summary includes `updated_at`, `agent_mode`, `latest_cycle_result`, and `top_focus`.
114. `ops/agent/ops-plan.yaml` follows a stable current-build YAML shape with `contract_version`, `generated_at`, `agent_mode`, `active_priorities`, `watch_items`, `maintenance_backlog`, `weak_areas`, and `replan`, and each active priority includes rank, title, reason, scope, and intended next action.
115. Each `context_snapshot.json` uses the current minimum nested shape for `selected_work`, `state_summary`, `candidate_actions`, `evidence_refs`, `evidence_excerpts`, and `sleep_wake_recovery_context` when applicable, rather than only flat top-level identifiers.
116. In the current macOS build, primary sleep/wake detection reads `pmset -g log` for recent `Sleep`, `Wake`, and `DarkWake` lines, while `pmset -g uuid` may be used as supporting correlation data and `pmset -g stats` remains diagnostic only.
117. The current `launchd` supervisor plist uses the exact current-build wiring of `Label = com.jobhuntcopilot.supervisor`, `RunAtLoad = true`, `StartInterval = 5`, `KeepAlive = false`, `WorkingDirectory = <absolute project root>`, `ProgramArguments = [<absolute project root>/bin/jhc-agent-cycle]`, and dedicated stdout/stderr log paths under `ops/logs/`.
118. The current `launchd` feedback-sync plist uses the exact current-build wiring of `Label = com.jobhuntcopilot.feedback-sync`, `RunAtLoad = true`, `StartInterval = 300`, `KeepAlive = false`, `WorkingDirectory = <absolute project root>`, `ProgramArguments = [<absolute project root>/bin/jhc-feedback-sync-cycle]`, and dedicated stdout/stderr log paths under `ops/logs/`.
119. The current build includes `bin/jhc-agent-cycle`, `bin/jhc-feedback-sync-cycle`, `scripts/ops/run_supervisor_cycle.py`, `scripts/ops/run_feedback_sync.py`, `scripts/ops/build_runtime_pack.py`, and `scripts/ops/chat_session.py`, and the shell entrypoints `jhc-agent-start`, `jhc-agent-stop`, and `jhc-chat` are wired through those repo-local helpers plus `launchctl`.

## 12.5B LinkedIn Scraping
1. A new upstream lead ingested through `LinkedIn Scraping` receives a stable `lead_id`.
2. In the autonomous Gmail-alert mode, each agent-invoked Gmail ingestion run first persists each collected Gmail message once under `linkedin-scraping/runtime/gmail/{YYYYMMDDTHHMMSSZ}-{gmail_message_id}/...` before job-card fan-out into per-lead workspaces begins.
3. If a Gmail message with an already-collected `gmail_message_id` is encountered again, collection behaves idempotently and the duplicate message is ignored rather than overwriting or creating another collected-email unit.
4. Multiple Gmail messages in the same `gmail_thread_id` are still collected and parsed independently; thread membership alone does not suppress collection or job-card parsing for any message.
5. If a collected Gmail message yields zero parseable job cards, the collected email artifacts are retained, `job-cards.json` may be empty, no lead workspace is created from that message, and review is triggered only when more than 3 such emails occur in one Gmail ingestion run or when the cumulative unresolved count exceeds 3 across history.
6. The canonical lead workspace is rooted at `linkedin-scraping/runtime/leads/<company>/<role>/<lead_id>/`.
7. In the autonomous Gmail-alert mode, the per-lead workspace is created immediately after a parsed job card survives validation and deduplication.
8. A newly created autonomous lead workspace is marked `incomplete` until JD recovery succeeds and downstream handoff can be evaluated.
9. If JD recovery does not succeed, the autonomous lead workspace transitions to `blocked_no_jd`.
10. Every lead workspace contains `lead-manifest.yaml` plus the artifacts required by that lead mode.
11. Manual-capture leads contain `raw/source.md`, `source-split.yaml`, and `source-split-review.yaml`.
12. Autonomous Gmail-derived leads are not required to contain `raw/source.md`, `source-split.yaml`, or `source-split-review.yaml` in the lead workspace by default.
13. `lead-manifest.yaml` exists even when the lead is blocked by ambiguous split review.
14. If split review is `ambiguous`, downstream handoff readiness is blocked and the manifest records that blocked state rather than silently omitting the lead when split review is applicable for that lead mode.
15. In the autonomous Gmail-alert mode, parsed alert cards that resolve to a LinkedIn `job_id` already seen for an existing autonomous lead do not create a second lead.
16. In the autonomous Gmail-alert mode, a parsed alert card without a usable LinkedIn `job_id` may still create a lead when a synthetic fallback identity key is materialized and persisted for that card.
17. In that same missing-`job_id` case, the synthetic fallback identity key shall be derived from the normalized LinkedIn job URL when that URL is available.
18. In the autonomous Gmail-alert mode, a parsed alert card that lacks both a usable LinkedIn `job_id` and a usable LinkedIn job URL transitions to `blocked_no_jd` if no usable JD can be recovered from any supported source.
19. In the autonomous Gmail-alert mode, when multiple JD candidate sources are available for the same lead, those sources are compared and any additional non-conflicting information is merged into the canonical `jd.md`.
20. If those JD candidate sources conflict materially, LinkedIn-derived JD content is preferred for the conflicting portion while provenance still records all contributing sources.
21. If a lead has a valid non-ambiguous JD, a canonical `job_posting` can be created and linked back through `lead_id`.
22. If a lead does not have a valid non-ambiguous JD, a canonical `job_posting` is not auto-created.
23. When a non-ambiguous lead contains an identifiable poster profile, the poster contact is auto-created, linked to the lead through `linkedin_lead_contacts`, and linked to the posting when the posting exists.
24. The recipient typing model includes `founder` as a first-class value in addition to the current recipient types.
25. Source metadata such as `source_type`, `source_reference`, `source_url`, `source_mode`, and source-mode-specific provenance is source-of-truth on the lead entity rather than on `job_postings`.
26. Downstream components consume artifact references from `lead-manifest.yaml` rather than relying on hardcoded upstream directory assumptions.
27. Refreshing an existing lead updates the live lead workspace in place while preserving older source or review snapshots in lead-local history artifacts.

## 12.6 End-to-End
1. The role-targeted flow can run from `LinkedIn Scraping` through delivery feedback with intermediate artifacts persisted at each stage boundary.
2. The role-targeted flow may start from either manual browser capture or autonomous Gmail job-alert intake without changing the downstream contract shape.
3. The role-targeted flow does not require a mandatory human pause after Tailoring, but it does require a mandatory agent review. Downstream progression continues only after that agent review approves the active tailoring run.
4. The general learning-outreach flow can run contact-rooted without requiring posting-specific resume tailoring or a resume attachment.
5. In the autonomous LinkedIn-alert flow, the system first attempts to recover the JD from LinkedIn guest job data when the parsed alert exposes a usable job URL or job id, and that JD becomes the default tailoring input.
6. In the autonomous LinkedIn-alert flow, company-website or careers-page resolution is attempted as best-effort enrichment and provenance rather than as a hard prerequisite for lead creation.
7. In the autonomous LinkedIn-alert flow, the full recovered JD is written to `jd.md` before eligibility or tailoring structuring runs.
8. In the autonomous LinkedIn-alert flow, downstream structuring reads from that persisted `jd.md` and company/role context files.
9. Company-scoped people search can identify candidate contacts before person-scoped email discovery, and selected contacts without usable emails can continue into the email-finder cascade.
10. In the autonomous LinkedIn-alert flow, Apollo is used to gather many relevant internal people, and the outreach posture asks those contacts for connection or routing help to the right person.
11. Discovery may begin per linked contact once prerequisites are satisfied, drafting may proceed across the ready untouched posting frontier as contacts become ready, and automatic sending remains separately governed by active send-slice selection and pacing.
12. Failures resume from the last successful stage boundary rather than forcing a restart from `LinkedIn Scraping`.
13. A failure on one contact does not invalidate unrelated contacts for the same posting.
14. For any `job_posting`, `contact`, or `outreach_message`, the system can show its current state, linked artifacts, and downstream history.
15. If send outcome is ambiguous, the system does not automatically resend and instead surfaces the case for review.
16. A bounce or reply that arrives after the interactive send session has ended can still be captured later by the delayed feedback-sync process and written back into canonical state.
17. This build can run sequentially without requiring concurrency in discovery, drafting, sending, or delayed feedback sync.
18. Replacing the contents of `paste/paste.txt` for a new lead does not modify historical lead records because each ingested lead keeps its own copied `linkedin-scraping/runtime/leads/.../raw/source.md`.
19. Autonomous role-targeted outreach respects ranked recipient waves plus per-posting send pacing rather than emailing every discovered contact immediately.
20. After a terminal or otherwise review-worthy role-targeted run reaches its current end-to-end boundary, the supervisor produces an expert review packet without requiring the whole system to stop by default.

---

## 13. Suggested Artifacts

### LinkedIn Scraping Gmail Collection Artifacts
1. `linkedin-scraping/runtime/gmail/{YYYYMMDDTHHMMSSZ}-{gmail_message_id}/email.md` (one clean human-readable raw email snapshot, `text/plain` first with noise-minimized HTML-derived fallback only when needed)
2. `linkedin-scraping/runtime/gmail/{YYYYMMDDTHHMMSSZ}-{gmail_message_id}/email.json` (normalized Gmail metadata plus only the specific raw body parts and parse-relevant fields actually used by intake/review; not a full provider payload dump; minimum fields should include `gmail_message_id`, `gmail_thread_id` when available, sender, subject, `received_at`, `collected_at`, Gmail ingestion run id, body format used, parse outcome, and parseable-job-card count)
3. `linkedin-scraping/runtime/gmail/{YYYYMMDDTHHMMSSZ}-{gmail_message_id}/job-cards.json` (parsed non-duplicate job cards from that email; may be empty when no cards are parseable; retained even when a given card later ends in `blocked_no_jd`; minimum per-card fields should include `card_index`, `role_title`, `company_name`, `location`, `badge_lines`, `job_url`, `job_id` when present, and source `gmail_message_id`)

### LinkedIn Scraping Upstream Artifacts
1. `paste/paste.txt`
2. `linkedin-scraping/runtime/leads/{company}/{role}/{lead_id}/raw/source.md` (when the lead mode materializes a canonical raw source)
3. `linkedin-scraping/runtime/leads/{company}/{role}/{lead_id}/capture-bundle.json` (manual capture when used)
4. `linkedin-scraping/runtime/leads/{company}/{role}/{lead_id}/jd-fetch.json` (final merged JD provenance and outcome metadata for the canonical `jd.md`)
5. `linkedin-scraping/runtime/leads/{company}/{role}/{lead_id}/company-resolution.json` (final company website and careers resolution outcome for autonomous mode)
6. `linkedin-scraping/runtime/leads/{company}/{role}/{lead_id}/jd.md`
7. `linkedin-scraping/runtime/leads/{company}/{role}/{lead_id}/post.md`
8. `linkedin-scraping/runtime/leads/{company}/{role}/{lead_id}/poster-profile.md`
9. `linkedin-scraping/runtime/leads/{company}/{role}/{lead_id}/source-split.yaml` (when split processing is applicable for that lead mode)
10. `linkedin-scraping/runtime/leads/{company}/{role}/{lead_id}/source-split-review.yaml` (when split review is applicable for that lead mode)
11. `linkedin-scraping/runtime/leads/{company}/{role}/{lead_id}/lead-manifest.yaml`
12. `linkedin-scraping/runtime/leads/{company}/{role}/{lead_id}/history/`

### Downstream Artifacts
1. `applications/{company}/{role}/application.yaml`
2. `resume-tailoring/input/profile.md`
3. `resume-tailoring/input/job-postings/{company}-{role}.md`
4. `resume-tailoring/ai/system-prompt.md`
5. `resume-tailoring/ai/cookbook.md`
6. `resume-tailoring/ai/sop-swe-experience-tailoring.md`
7. `resume-tailoring/ai/few-shot-examples/{company-role}/`
8. `resume-tailoring/output/tailored/{company}/{role}/meta.yaml`
9. `resume-tailoring/output/tailored/{company}/{role}/jd.md`
10. `resume-tailoring/output/tailored/{company}/{role}/post.md`
11. `resume-tailoring/output/tailored/{company}/{role}/poster-profile.md` (when available)
12. `resume-tailoring/output/tailored/{company}/{role}/resume.tex`
13. `resume-tailoring/output/tailored/{company}/{role}/scope-baseline.resume.tex`
14. `resume-tailoring/output/tailored/{company}/{role}/intelligence/manifest.yaml`
15. `resume-tailoring/output/tailored/{company}/{role}/intelligence/step-3-jd-signals.yaml`
16. `resume-tailoring/output/tailored/{company}/{role}/intelligence/step-4-evidence-map.yaml`
17. `resume-tailoring/output/tailored/{company}/{role}/intelligence/step-5-elaborated-swe-context.md`
18. `resume-tailoring/output/tailored/{company}/{role}/intelligence/step-6-candidate-swe-bullets.yaml`
19. `resume-tailoring/output/tailored/{company}/{role}/intelligence/step-7-verification.yaml`
20. `resume-tailoring/output/tailored/{company}/{role}/intelligence/prompts/`
21. `resume-tailoring/output/tailored/{company}/{role}/Achyutaram Sonti.pdf`
22. `discovery/output/{company}/{role}/people_search_result.json`
23. `discovery/output/{company}/{role}/recipient-profiles/{contact_id}/recipient_profile.json`
24. `discovery/output/{company}/{role}/discovery_result.json`
25. `job_hunt_copilot.db`
26. `outreach/output/{company}/{role}/email_draft.md`
27. `outreach/output/{company}/{role}/send_result.json`
28. `outreach/output/{company}/{role}/delivery_outcome.json`
29. `delivery_outcome.json`
30. `ops/launchd/job-hunt-copilot-feedback-sync.plist`
31. `ops/agent/identity.yaml` (agent name, mission, owned components, allowed/forbidden actions summary, canonical-state locations)
32. `ops/agent/policies.yaml` (review gates, send/safety policies, retry/repair limits, pause/resume/stop semantics, override semantics)
33. `ops/agent/action-catalog.yaml` (bounded actions the supervisor may choose, with prerequisites, expected outputs, and validation references)
34. `ops/agent/service-goals.yaml` (heartbeat cadence, work-freshness expectations, due-work priorities, and continuous service goals)
35. `ops/agent/escalation-policy.yaml` (incident severity levels, escalation triggers, auto-pause triggers, and expert-surface routing)
36. `ops/agent/progress-log.md` (compact rolling operational handoff note for fresh sessions)
37. `ops/agent/ops-plan.yaml` (near-term operating plan, maintenance backlog, recurring issues, and watch items)
38. `ops/agent/chat-bootstrap.md` (bootstrap instructions for the Codex-backed expert-facing chat operator)
39. `ops/agent/supervisor-bootstrap.md` (bootstrap instructions for the heartbeat-driven Codex supervisor)
40. `ops/agent/context-snapshots/{supervisor_cycle_id}/context_snapshot.json` (compact machine-readable reasoning context snapshot for one heartbeat cycle)
41. `ops/review-packets/{pipeline_run_id}/review_packet.md` (human-readable post-run expert review summary)
42. `ops/review-packets/{pipeline_run_id}/review_packet.json` (machine-readable post-run summary and expert-action payload)
43. `ops/maintenance/{maintenance_change_batch_id}/maintenance_change.md` (human-readable maintenance change summary, validation, and approval outcome)
44. `ops/maintenance/{maintenance_change_batch_id}/maintenance_change.json` (machine-readable maintenance change metadata and approval outcome)
45. `ops/incidents/{agent_incident_id}.md` (human-readable incident summary and diagnosis notes)
46. `ops/launchd/job-hunt-copilot-supervisor.plist`
47. `bin/jhc-agent-start`
48. `bin/jhc-agent-stop`
49. `bin/jhc-chat`
50. `bin/jhc-agent-cycle`
51. `bin/jhc-feedback-sync-cycle`
52. `scripts/ops/run_supervisor_cycle.py`
53. `scripts/ops/run_feedback_sync.py`
54. `scripts/ops/build_runtime_pack.py`
55. `scripts/ops/chat_session.py`
56. `ops/logs/supervisor.stdout.log`
57. `ops/logs/supervisor.stderr.log`
58. `ops/logs/feedback-sync.stdout.log`
59. `ops/logs/feedback-sync.stderr.log`

---

## 14. Current-Build Ambiguity Status

There are no remaining known product-level open questions that block the current build.

The main future-facing decisions have been frozen as explicit defaults or trigger rules:
1. the `>5 years` hard-disqualifier remains a single global rule until explicit role-family policy versioning exists
2. JD-signal weighting uses one global default scale in the current build rather than role-family-specific calibration
3. Step 5 controlled elaboration now has explicit allowed moves, prohibited moves, and claim-ledger rules
4. manual browser capture now has a default split between immediate selected-text submission and tray-first full-page review
5. the later people-search fallback evaluation order after Apollo is `PDL`, then `Coresignal`, then `ContactOut`
6. the deferred two-step outreach mode now has a default future operating shape even though it remains out of scope for the current build
7. `company` remains a field-level concept unless the explicit company-entity promotion triggers are met
