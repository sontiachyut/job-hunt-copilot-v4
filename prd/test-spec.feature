@next_build @gherkin
Feature: Job Hunt Copilot next-build acceptance
  The next build should satisfy the finalized behavior defined in the product spec
  using the next-build inputs, assets, and runtime integrations.

  Background:
    Given the build input pack contains `spec.md`
    And the build input pack contains `runtime_secrets.json` or equivalent local secret files
    And the build input pack contains the required `assets/` folder
    And the runtime environment targets Python 3.11
    And the runtime environment has the required Python dependencies installed
    And the runtime environment has a LaTeX toolchain capable of compiling the bundled resume source

  @bootstrap @system
  Rule: Build bootstrap and prerequisites

    Scenario: Fresh build validates required inputs and environment
      Given `spec.md` is present
      And `runtime_secrets.json` is present or vendor-specific secret files are already available
      And `assets/resume-tailoring/profile.md` exists
      And at least one base resume source exists under `assets/resume-tailoring/base/`
      And `assets/outreach/cold-outreach-guide.md` exists
      When the fresh build bootstrap checklist is executed
      Then vendor-specific runtime secret files can be materialized when required
      And `job_hunt_copilot.db` can be initialized or migrated successfully
      And the build can proceed without requiring the full old repository layout

    Scenario: Build smoke test passes
      Given a fresh build has been assembled
      When the smoke test checklist is executed
      Then the system initializes or migrates `job_hunt_copilot.db`
      And the system loads runtime secrets successfully
      And the system reads the required files from `assets/`
      And the system can create a Resume Tailoring workspace for a sample posting
      And the system can compile the base or tailored resume successfully
      And the system can run a discovery-path check with normalized output
      And the system can generate a machine-valid `discovery_result.json`
      And the system can generate a machine-valid `send_result.json`
      And the delayed feedback sync logic can run once without crashing
      And at least one review surface can be queried from canonical state

    Scenario: Build environment satisfies the declared runtime assumptions
      Given a fresh build environment is being validated
      When runtime prerequisites are checked
      Then the reference interpreter is Python 3.11
      And the required Python dependencies are installed
      And a LaTeX environment capable of compiling the bundled base resume source is available

    Scenario: Canonical database schema includes the next-build required tables
      Given a fresh build has initialized `job_hunt_copilot.db`
      When the next-build schema is inspected
      Then the database contains `linkedin_leads`
      And the database contains `job_postings`
      And the database contains `contacts`
      And the database contains `linkedin_lead_contacts`
      And the database contains `job_posting_contacts`
      And the database contains `resume_tailoring_runs`
      And the database contains `pipeline_runs`
      And the database contains `supervisor_cycles`
      And the database contains `agent_control_state`
      And the database contains `agent_runtime_leases`
      And the database contains `agent_incidents`
      And the database contains `expert_review_packets`
      And the database contains `expert_review_decisions`
      And the database contains `maintenance_change_batches`
      And the database contains `artifact_records`
      And the database contains `state_transition_events`
      And the database contains `override_events`
      And the database contains `feedback_sync_runs`
      And the database contains `windows`
      And the database contains `provider_budget_state`
      And the database contains `provider_budget_events`
      And the database contains `discovery_attempts`
      And the database contains `outreach_messages`
      And the database contains `delivery_feedback_events`

    Scenario: Build input pack is sufficient for a fresh build
      Given the build input pack contains `spec.md`
      And the build input pack contains `runtime_secrets.json`
      And the build input pack contains `assets/`
      When a fresh build implementation is bootstrapped
      Then the build can use `assets/resume-tailoring/profile.md` as master-profile input
      And the build can use the single bundled base resume track under `assets/resume-tailoring/base/`
      And the build can use `assets/outreach/cold-outreach-guide.md` as the outreach guide
      And no additional personal-context files are required to start the build

    Scenario: Fresh build materializes the paste inbox workflow
      Given a fresh build implementation is bootstrapped
      When workspace-support directories are inspected
      Then `paste/` exists at the repo root
      And `paste/paste.txt` exists as the reusable local inbox file
      And the paste inbox is available before the first lead is ingested

    Scenario: Fresh build materializes the supervisor runtime pack and local entrypoints
      Given a fresh build implementation is bootstrapped
      When supervisor support artifacts are inspected
      Then `ops/agent/identity.yaml` exists
      And `ops/agent/policies.yaml` exists
      And `ops/agent/action-catalog.yaml` exists
      And `ops/agent/service-goals.yaml` exists
      And `ops/agent/escalation-policy.yaml` exists
      And `ops/agent/chat-bootstrap.md` exists
      And `ops/agent/supervisor-bootstrap.md` exists
      And `bin/jhc-agent-start` exists
      And `bin/jhc-agent-stop` exists
      And `bin/jhc-chat` exists

  @contracts @system
  Rule: Machine handoff contracts and canonical state

    Scenario: Machine handoff artifacts include the shared contract envelope
      Given the build produces machine handoff artifacts
      When `lead-manifest.yaml`, `meta.yaml`, `discovery_result.json`, `send_result.json`, or `delivery_outcome.json` is validated
      Then the artifact includes `contract_version`
      And the artifact includes `produced_at`
      And the artifact includes `producer_component`
      And the artifact includes `result`
      And blocked or failed artifacts include `reason_code`
      And blocked or failed artifacts include `message`

    Scenario: Machine handoff artifacts carry the relevant root identifiers
      Given a machine handoff artifact is produced for a real workflow step
      When the artifact is inspected
      Then it includes the stable identifiers needed by the downstream component
      And upstream lead artifacts carry `lead_id` when applicable
      And role-targeted artifacts carry `job_posting_id` when applicable
      And contact-rooted artifacts carry `contact_id` when applicable
      And send and feedback artifacts carry `outreach_message_id` when applicable

    Scenario: Canonical state is stored in the central database while files remain handoff artifacts
      Given the system has processed at least one posting and one contact
      When current state is queried
      Then canonical lifecycle state is read from `job_hunt_copilot.db`
      And generated files are treated as runtime handoff artifacts or human-readable companions
      And disagreement on lifecycle state is resolved in favor of the central database

    Scenario: Tailoring handoff manifest includes the current required payload fields
      Given Resume Tailoring has produced a workspace handoff for Outreach
      When `meta.yaml` is inspected as a machine handoff artifact
      Then it includes `contract_version`
      And it includes `produced_at`
      And it includes `producer_component`
      And it includes `result`
      And it includes `job_posting_id`
      And it includes `base_used`
      And it includes finalize or review status
      And it includes resume artifact references suitable for downstream use

    Scenario: Tailoring-to-Outreach bootstrap is DB-first and starts only from the agent-approved requires-contacts state
      Given Resume Tailoring has completed for a role-targeted posting
      And the posting is linked by `job_posting_id`
      When Outreach bootstrap evaluates whether it may start
      Then canonical DB state is the primary bootstrap source
      And `meta.yaml` remains a supporting runtime reference rather than the primary bootstrap entrypoint
      And Outreach starts only when `resume_review_status = approved`
      And Outreach starts only when posting status is `requires_contacts`

    Scenario: Resume Tailoring input boundary is centered on `jd.md` rather than the raw lead dump
      Given `LinkedIn Scraping` has produced `raw/source.md` and the available derived lead artifacts for a lead
      When Resume Tailoring begins for that posting
      Then the core tailoring logic consumes the derived `jd.md` plus posting-level canonical state
      And the build does not require direct reading of `raw/source.md` to run Tailoring
      And mirrored `post.md` or `poster-profile.md` may exist for traceability without being mandatory inputs to the core tailoring decision path

    Scenario: Discovery handoff artifact includes the current required payload fields
      Given Email Discovery has completed for a contact
      When `discovery_result.json` is inspected as a machine handoff artifact
      Then it includes `contract_version`
      And it includes `produced_at`
      And it includes `producer_component`
      And it includes `result`
      And it includes `contact_id`
      And it includes `job_posting_id` when the flow is posting-linked
      And it includes the discovery outcome
      And it includes the discovered or working email when one was found
      And it includes provider or confidence metadata when available

    Scenario: Discovery handoff artifact can reference recipient-profile output when it exists
      Given Email Discovery completed for a contact that also has persisted recipient-profile enrichment
      When `discovery_result.json` is inspected
      Then it may include a reference to the related `recipient_profile.json` artifact
      And downstream drafting can rely on that stored artifact reference rather than refetching the profile

    Scenario: Send handoff artifact includes the current required payload fields
      Given Email Drafting and Sending has produced or sent a message
      When `send_result.json` is inspected as a machine handoff artifact
      Then it includes `contract_version`
      And it includes `produced_at`
      And it includes `producer_component`
      And it includes `result`
      And it includes `outreach_message_id`
      And it includes `contact_id`
      And it includes `job_posting_id` when the flow is posting-linked
      And it includes send timestamp
      And it includes send status
      And it includes a delivery-tracking identifier or thread ID when available

    Scenario: Feedback handoff artifact includes the current required payload fields
      Given Delivery Feedback has ingested a mailbox-observed outcome
      When `delivery_outcome.json` is inspected as a machine handoff artifact
      Then it includes `contract_version`
      And it includes `produced_at`
      And it includes `producer_component`
      And it includes `result`
      And it includes `outreach_message_id`
      And it includes `contact_id`
      And it includes `job_posting_id` when the flow is posting-linked
      And it includes the event state or event type
      And it includes the event timestamp
      And it includes reply summary or context when useful reply content exists

    Scenario: Expert review packet artifacts include machine and human-readable companions
      Given a review-worthy role-targeted pipeline run has reached a terminal outcome
      When the generated expert review packet artifacts are inspected
      Then `review_packet.json` exists for that run
      And `review_packet.md` exists for that run
      And the machine-readable packet includes the relevant stable identifiers and run outcome
      And the human-readable packet summarizes only the details relevant to that run outcome

    Scenario: Maintenance change artifacts exist for every autonomous maintenance batch
      Given an autonomous maintenance batch has been created
      When the maintenance artifacts are inspected
      Then `maintenance_change.json` exists for that maintenance batch
      And `maintenance_change.md` exists for that maintenance batch
      And the machine-readable artifact includes the maintenance batch id, branch, commits, approval outcome, validation summary, and changed files
      And those artifacts still exist even when the maintenance batch is failed or unapproved

    Scenario: Generated artifacts are queryable from shared artifact metadata
      Given the system has created runtime artifacts across tailoring, discovery, drafting, or feedback
      When artifact metadata is queried
      Then those artifacts are discoverable through `artifact_records`
      And artifact metadata links back to the relevant `job_posting_id`, `contact_id`, or `outreach_message_id` when applicable
      And artifact contents remain on the filesystem rather than being stored wholesale in the central database

    Scenario: External identifiers remain secondary to internal canonical identifiers
      Given a sent message or provider result includes vendor-specific identifiers
      When the related records and handoff artifacts are inspected
      Then internal identifiers such as `job_posting_id`, `contact_id`, and `outreach_message_id` remain the authoritative linkage keys
      And mailbox thread IDs or provider IDs are retained only as secondary references

    Scenario: Secrets and tokens do not leak into canonical state or review surfaces
      Given the build has loaded runtime secrets successfully
      When canonical tables, machine handoff artifacts, and review-oriented outputs are inspected
      Then secrets and tokens do not appear in those persisted records
      And operational review surfaces expose workflow-relevant data only

  @state @system
  Rule: State transitions and relationship records

    Scenario: Primary entity records expose the next-build minimum canonical fields
      Given the next-build schema has been initialized
      When the primary entity tables are inspected
      Then `linkedin_leads` includes a stable `lead_id`
      And `linkedin_leads` includes source metadata and split-review state
      And `job_postings` includes a stable `job_posting_id`
      And `job_postings` includes `lead_id`
      And `job_postings` includes a normalized posting identity key
      And `job_postings` includes company name, role title, and posting status
      And `contacts` includes a stable `contact_id`
      And `contacts` includes an `identity_key`
      And `contacts` includes `origin_component`
      And `contacts` includes full name, company name, contact status, and current working email when known
      And all primary entity tables include lifecycle timestamps

    Scenario: Lead and job posting follow forward-only lifecycle progression
      Given a role-targeted lead enters the pipeline
      When it progresses through the normal next-build flow
      Then the lead moves forward through `captured`, `split_ready`, `reviewed`, and `handed_off` when eligible
      And the linked job posting moves forward through the applicable states from `sourced`
      And it does not automatically move backward to an earlier lifecycle state
      And any deliberate backward move would require explicit user action or reset

    Scenario: Posting-contact links are stored as one canonical relationship row per pair
      Given a job posting and contact are connected for outreach
      When the relationship is persisted
      Then `job_posting_contacts` contains exactly one canonical row for that posting-contact pair
      And the row includes `recipient_type`
      And the row includes `relevance_reason`
      And time-based message or discovery history remains in component tables rather than duplicate link rows

    Scenario: Contact and posting-contact states advance with the workflow
      Given a linked contact begins discovery for a role-targeted posting
      When discovery, drafting, and sending proceed successfully
      Then the contact can advance through `discovery_in_progress`, `working_email_found`, `outreach_in_progress`, and `sent`
      And the posting-contact relationship can advance through `identified`, `shortlisted`, `outreach_in_progress`, and `outreach_done`
      And those major transitions are queryable through state-transition audit records

    Scenario: Contact identity may be reused across multiple postings without duplicating the person record
      Given the same real person is relevant to more than one job posting
      When those posting-contact relationships are created
      Then the system may reuse one canonical contact record across those postings
      And each posting relationship is tracked separately through `job_posting_contacts`
      But automatic role-targeted outreach does not send a second same-company message to that canonical contact without user review

    Scenario: Same-company grouping begins from a provisional company key before provider resolution
      Given a newly materialized posting has not yet resolved a provider-backed company identifier
      When the posting is created in canonical state
      Then the posting still receives a provisional canonical company-grouping key derived from the normalized company name
      And same-company repeat-outreach protections may already use that provisional key

    Scenario: Provider-backed company resolution strengthens an existing same-company grouping
      Given a posting already has a provisional canonical company-grouping key
      And later company-scoped people search resolves a stable provider-backed company identifier
      When canonical posting state is updated from that resolution
      Then the posting may be reconciled into the stronger provider-backed same-company grouping
      And same-company repeat-outreach protections continue without requiring a reset

    Scenario: Source metadata is owned by the lead rather than the posting
      Given a role-targeted lead has been ingested
      When canonical source metadata is inspected
      Then `linkedin_leads` stores the authoritative source metadata for that lead
      And `job_postings` rely on `lead_id` rather than owning that source metadata as the primary source-of-truth

    Scenario: Valid non-ambiguous JD creates a posting linked back to the lead
      Given a lead contains a valid non-ambiguous JD
      When canonical entities are materialized
      Then a canonical `job_posting` is created
      And that posting stores the originating `lead_id`

    Scenario: Missing or invalid JD does not auto-create a posting
      Given a lead does not contain a valid non-ambiguous JD
      When canonical entities are materialized
      Then a canonical `job_posting` is not auto-created
      And the lead remains available for review or later refresh

    Scenario: Identifiable poster profile creates lead-contact traceability
      Given a non-ambiguous lead contains an identifiable poster profile
      And a canonical `job_posting` has been created for that lead
      When canonical entities are materialized
      Then a canonical `contact` is auto-created for the poster
      And a `linkedin_lead_contacts` row links that `contact` back to the `lead`
      And a `job_posting_contacts` row links that `contact` to the `job_posting`

    Scenario: Founder is treated as a first-class inferred recipient type
      Given an identifiable poster title contains `Founder` or `Co-Founder`
      When recipient typing is inferred from that lead
      Then the inferred recipient type may be `founder`
      And that inferred type remains queryable through lead-contact or posting-contact linkage

    Scenario: New postings merge only when identity matching is confident
      Given a new posting resembles an existing posting in company and role metadata
      When posting identity is evaluated
      Then the system merges only when the match is confident
      And ambiguous cases create a new posting record instead of risking a bad automatic merge

    Scenario: Operational history is retained instead of broadly hard-deleted by default
      Given the system has accumulated operational records for postings, contacts, messages, and feedback
      When an item is retired from active use in the normal workflow
      Then the preferred behavior is status-based retirement, exhaustion, abandonment, or archival treatment
      And operational history is not broadly hard-deleted by default

  @integrations @build
  Rule: External integrations and bootstrap configuration

    Scenario: Raw text input takes precedence over URLs during LinkedIn Scraping normalization
      Given both raw JD or post text and a source URL are supplied for the same lead item
      When LinkedIn Scraping normalization runs
      Then the raw text is treated as the primary content source
      And the URL is treated as a reference rather than the canonical input body

    Scenario: Consolidated runtime secrets can materialize vendor-specific local secret files
      Given `runtime_secrets.json` is present with the required provider and Gmail configuration content
      When fresh-build setup materializes runtime secret files
      Then vendor-specific local secret files can be created from that bootstrap input
      And the bootstrap secret file remains a setup input rather than canonical runtime state

    Scenario: Provider integrations use normalized internal handling rather than vendor-specific orchestration logic
      Given contact search or Email Discovery is using vendors such as Apollo, Prospeo, GetProspect, or Hunter
      When a provider succeeds, fails, rate-limits, or exhausts credits
      Then provider-specific responses are normalized into internal outcomes or reason codes
      And orchestration continues using normalized internal state rather than branching directly on raw vendor response shapes

    Scenario: External integration failures surface as normalized blocked or failed reasons
      Given an external provider or mailbox integration fails during a workflow step
      When canonical state and machine handoff artifacts are inspected
      Then the failure appears as a normalized blocked or failed reason in internal state
      And review or retry logic does not depend on reading raw vendor error payloads directly

    Scenario: External source material used by the workflow is persisted internally for later review
      Given external job or profile context materially affects system behavior
      When the current pipeline ingests that context
      Then a usable internal snapshot, mirror, or normalized artifact is persisted
      And later review does not depend on re-fetching mutable external content

    Scenario: Manual browser capture creates a capture bundle and canonical raw source
      Given a browser-side manual LinkedIn capture submission contains one or more capture items
      When the local upstream receiver accepts that submission
      Then a lead workspace is created for that submission
      And `capture-bundle.json` is persisted for that lead
      And the canonical `linkedin-scraping/runtime/leads/<company>/<role>/<lead_id>/raw/source.md` is assembled from that accepted capture bundle

    Scenario: Manual capture defaults selected-text and full-page flows differently before converging into one bundle contract
      Given the manual browser-capture path is available
      When the user invokes capture with explicit selected text
      Then the default behavior is immediate selected-text submission into the local upstream receiver
      And the selected text remains preserved verbatim in the resulting capture artifacts
      When the user invokes capture without explicit selected text
      Then the default behavior opens the tray or popup review surface before submission
      And both paths still converge into the same shared capture-bundle contract

    Scenario: Selected text from manual capture is preserved verbatim
      Given a manual capture item includes explicit selected text and surrounding full-page text
      When that capture is persisted into the lead workspace
      Then the selected text remains available verbatim in the source-mode artifacts
      And later normalization does not silently overwrite that selected text with only full-page content

    Scenario: Autonomous Gmail job-alert intake persists the alert snapshot and JD-fetch provenance
      Given a LinkedIn job-alert email from `jobalerts-noreply@linkedin.com` is ingested from Gmail
      And the Gmail message contains one or more parseable job cards in its plain-text body
      When the autonomous lead-ingestion path runs
      Then a lead workspace is created for each parsed job card that survives validation and deduplication
      And `alert-email.md` is persisted for that lead
      And machine-readable alert metadata or parsed-card artifacts are persisted for that lead
      And the JD fetch outcome or fetch failure reason is recorded in lead metadata or artifacts
      And the lead manifest records whether `post.md` or `poster-profile.md` are unavailable for that lead

    Scenario: Autonomous Gmail parser prefers the plain-text digest and can emit multiple parsed job cards
      Given a LinkedIn alert email from `jobalerts-noreply@linkedin.com` contains multiple `View job` cards in the plain-text body
      And the digest uses dashed card separators with surrounding blank lines or whitespace
      When the autonomous Gmail parser runs
      Then the plain-text body is used as the primary parse input
      And one parsed alert-card entry is emitted for each valid job card discovered in that digest
      And later HTML parsing is needed only when the plain-text body is unavailable or unusable

    Scenario: Autonomous lead creation can proceed from a LinkedIn guest JD even when the exact company-hosted page is not recovered
      Given an autonomous alert card exposes a usable LinkedIn job URL or job id
      And the company website or careers page cannot be matched back to the same exact role
      When autonomous JD recovery runs
      Then `jd.md` can still be created from LinkedIn guest job data
      And the company-resolution outcome is persisted as best-effort provenance
      And the lead manifest records whether `post.md` or `poster-profile.md` are unavailable for that lead
      And downstream posting creation is not blocked solely because exact company-site role recovery failed

    Scenario: Autonomous JD is persisted fully in markdown before structured extraction
      Given an autonomous alert card yields a usable JD through LinkedIn guest recovery or another accepted JD source
      When the downstream posting workspace is materialized
      Then the full fetched JD text is persisted into `jd.md`
      And later structured eligibility or tailoring artifacts read from that persisted markdown
      And the build does not require direct reuse of only the transient network response payload

    Scenario: Autonomous posting files are grouped under a company or role workspace
      Given an autonomous lead has a valid company identity, role identity, and usable JD
      When downstream posting files are materialized
      Then a company or role-scoped workspace is created for that posting
      And posting-specific files such as `jd.md`, workspace metadata, and later structured artifacts are saved inside that grouped workspace

    Scenario: Component-oriented layout keeps runtime artifacts under the owning component folders
      Given a role-targeted lead has progressed through lead intake, tailoring, discovery, and drafting boundaries
      When the resulting filesystem artifacts are inspected
      Then upstream lead artifacts live under `linkedin-scraping/runtime/leads/<company>/<role>/<lead_id>/`
      And posting manifests live under `applications/<company>/<role>/`
      And tailoring workspace artifacts live under `resume-tailoring/output/tailored/<company>/<role>/`
      And discovery runtime outputs live under `discovery/output/<company>/<role>/`
      And outreach runtime outputs live under `outreach/output/<company>/<role>/`

    Scenario: Paste inbox ingestion creates one canonical lead raw source artifact
      Given `paste/paste.txt` contains a copied lead dump for a new lead
      When `LinkedIn Scraping` is started from the paste inbox
      Then the pasted file contents are copied unchanged into `linkedin-scraping/runtime/leads/<company>/<role>/<lead_id>/raw/source.md`
      And the lead raw folder contains only `source.md`
      And `artifact_records` contains `lead_raw_source` for that lead

    Scenario: Explicit new paste source replaces the live canonical lead source while later normalized-only reruns preserve it
      Given a lead already has a canonical `linkedin-scraping/runtime/leads/<company>/<role>/<lead_id>/raw/source.md`
      When `LinkedIn Scraping` is rerun for that same lead with a new explicit paste source file
      Then the live canonical `raw/source.md` is replaced by the new explicit source
      When `LinkedIn Scraping` is later rerun for that same lead without a new raw source file
      Then the existing live canonical `raw/source.md` is preserved

    Scenario: Derived lead files are split from the canonical raw source with review metadata
      Given a lead has a canonical `linkedin-scraping/runtime/leads/<company>/<role>/<lead_id>/raw/source.md`
      When lead context is derived from that canonical source
      Then available derived artifacts such as `post.md`, `jd.md`, or `poster-profile.md` are created from the source when that evidence exists
      And unavailable sections are recorded as unavailable in split-review or manifest metadata rather than being faked
      And `linkedin-scraping/runtime/leads/<company>/<role>/<lead_id>/source-split.yaml` records the selected split method and section ranges
      And `linkedin-scraping/runtime/leads/<company>/<role>/<lead_id>/source-split-review.yaml` records review status, confidence, checks, and recommended action
      And `linkedin-scraping/runtime/leads/<company>/<role>/<lead_id>/lead-manifest.yaml` records downstream handoff readiness
      And `artifact_records` contains `lead_split_metadata`, `lead_split_review`, and `lead_manifest` for that lead

    Scenario: Well-structured pasted lead dumps succeed with the rule-based first pass alone
      Given a pasted lead dump contains recognizable hiring-post, job-description, and poster-profile markers
      When lead context is derived from the canonical source
      Then the current selected split method is `rule_based_first_pass`
      And the review artifact is `confident` or `needs_review`
      And the pipeline does not require an AI second pass to produce usable derived lead files

    Scenario: Recruiter-authored pasted lead dump with plain-language hiring text is recognized by the rule-based first pass
      Given a pasted lead dump contains a recruiter-authored post that says `We're hiring` or `We’re hiring` instead of `#hiring`
      And the same dump also contains a recognizable `About the job` block and a poster profile block
      When lead context is derived from the canonical source
      Then `post.md` includes the recruiter-authored hiring text
      And the selected split method remains `rule_based_first_pass`
      And the review artifact is `confident` or `needs_review`

    Scenario: Networking-relevant post hints are preserved while obvious job-CTA chrome is dropped
      Given a pasted lead dump contains a copied post with both `View job` and `1 school alumni works here`
      When lead context is derived from the canonical source
      Then the extracted `post.md` does not retain `View job`
      But the extracted `post.md` preserves `1 school alumni works here`

    Scenario: Recruiter-profile chrome is cleaned from the derived poster profile in the Wilcore-style lead format
      Given a pasted lead dump contains recruiter-profile chrome such as `HighlightsHighlights` or `Introduce myself`
      When lead context is derived from the canonical source
      Then the derived `poster-profile.md` does not retain those profile-chrome lines
      And the substantive recruiter summary and experience content remain available in the derived profile

    Scenario: Ambiguous source dumps are escalated for review when no second-pass classifier is configured
      Given a pasted lead dump lacks enough structure for a confident deterministic split
      And no AI second-pass classifier is configured
      When lead context is reviewed from the canonical source
      Then the review artifact is `ambiguous`
      And the recommended action says the split should be reviewed rather than silently trusted
      And the canonical `raw/source.md` remains unchanged

    Scenario: Ambiguous lead review still publishes a blocked manifest
      Given a lead remains `ambiguous` after split review
      When the lead workspace is finalized
      Then `lead-manifest.yaml` still exists for that lead
      And the lead is marked not ready for downstream handoff
      And no downstream target is marked ready without an explicit non-ambiguous review result

    Scenario: Optional AI second pass can replace an ambiguous rule split only when confidence improves
      Given a pasted lead dump is ambiguous under the deterministic first pass
      And an AI second-pass classifier is configured
      When lead context is derived from the canonical source
      Then the system may attempt an AI second pass for that lead
      And the attempt outcome is recorded in split metadata or review metadata
      And the AI-selected split is accepted only when its review confidence is higher than the rule-based baseline
      And the canonical `raw/source.md` remains unchanged regardless of the selected split method

    Scenario: Vendor usage is auditable without exposing secrets
      Given a provider-based discovery call has been attempted
      When canonical records and runtime outputs are inspected
      Then the used provider name can be determined
      And the normalized result or normalized failure code can be determined
      But no provider secret value appears in those records

    Scenario: Gmail integration remains a channel rather than the canonical system of record
      Given the build uses Gmail for sending and mailbox observation
      When send and feedback data are persisted
      Then Gmail thread or provider identifiers may be retained as secondary metadata
      And canonical pipeline state remains internal to the copilot

  @failure @retry @system
  Rule: Failure, retry, and idempotency behavior

    Scenario: A stage is not successful until both state and required artifacts are persisted
      Given a stage completes its internal computation
      When canonical state or the required handoff artifact fails to persist
      Then the stage is treated as not successfully completed
      And downstream progression remains blocked

    Scenario: Canonical-state write failure marks the stage failed
      Given a stage has finished its internal work
      And the canonical database update cannot be written
      When orchestration records the stage result
      Then that stage is marked `failed`
      And dependent downstream stages do not proceed

    Scenario: Required handoff artifact publication failure marks the stage failed
      Given a stage is expected to publish a required machine handoff artifact
      And artifact publication fails
      When orchestration evaluates the stage result
      Then the stage is treated as `failed` for downstream progression
      And the stage is still treated as failed even if some internal work completed successfully

    Scenario: Retry occurs at the smallest safe unit of work
      Given a posting-scoped, contact-scoped, or message-scoped failure occurs
      When the system performs an automatic retry
      Then Resume Tailoring retries are posting-scoped
      And discovery or draft-generation retries are contact-scoped
      And feedback-ingestion retries are sent-message scoped

    Scenario: Draft-generation retry exhaustion surfaces review instead of silent skip
      Given draft generation fails for a contact because of a transient or execution problem
      When the allowed automatic retries are exhausted
      Then the case is surfaced for user review
      And the contact is not silently skipped as though drafting had succeeded

    Scenario: Ambiguous send state prefers under-sending to duplicate-sending
      Given the send outcome for a message is ambiguous
      When the system evaluates whether to retry sending
      Then it does not automatically resend when a prior successful send cannot be ruled out
      And the case is surfaced for review rather than risking a duplicate outreach

    Scenario: Feedback delay is not treated as pipeline failure
      Given an outreach message has been sent
      And no immediate bounce or reply is observed yet
      When the system evaluates the message before the observation window is complete
      Then the lack of immediate feedback is not treated as pipeline failure
      And the message may remain in a sent or awaiting-feedback state until later evidence arrives

    Scenario: Feedback ingestion is idempotent for the same logical message outcome
      Given Delivery Feedback retries ingestion for the same sent-message instance and mailbox signal
      When the duplicate ingestion path runs
      Then it does not create misleading duplicate logical outcomes for that same event
      And canonical feedback history remains consistent

  @resume_tailoring
  Rule: Resume Tailoring behavior

    Scenario: Hard-ineligible lead is stopped before tailoring
      Given a job posting explicitly requires more than 5 years of experience or citizenship or security clearance
      When Resume Tailoring evaluates hard eligibility
      Then the posting is marked `hard_ineligible`
      And downstream tailoring and outreach do not proceed for that posting

    Scenario: Current hard experience threshold is one global rule rather than role-family-specific policy
      Given Resume Tailoring is evaluating hard eligibility for different role-targeted postings
      When the build applies the current experience-threshold rule
      Then any JD that explicitly requires more than 5 years of experience is treated as `hard_ineligible`
      And the build does not require role-family-specific threshold overrides to make that decision

    Scenario: Missing eligibility signals are treated as unknown instead of hard failure
      Given a job posting has missing or ambiguous hard-eligibility language
      When Resume Tailoring evaluates hard eligibility
      Then the eligibility result is `unknown`
      And the posting is not hard-stopped only because the eligibility signals are incomplete
      And downstream tailoring may continue under the normal build flow

    Scenario: Eligibility evaluation persists an audit artifact with evidence
      Given Resume Tailoring has evaluated eligibility for a posting
      When the eligibility decision artifact is inspected
      Then it includes `eligibility_status`
      And it includes any triggered hard disqualifiers or soft flags
      And it includes `missing_data_fields` when relevant
      And it includes `decision_reason`
      And it includes supporting JD evidence snippets for the decision

    Scenario: Tailoring workspace is created with required artifacts
      Given a job posting is eligible for tailoring
      When Resume Tailoring runs for that posting
      Then a per-posting workspace is created
      And the workspace contains `meta.yaml`
      And the workspace contains mirrored context files
      And the workspace contains `resume.tex`
      And the workspace contains a scope-baseline snapshot
      And the workspace contains the current intelligence artifacts for Steps 3 through 7

    Scenario: Workspace metadata captures the current tailoring constraints
      Given a Resume Tailoring workspace has been created
      When `meta.yaml` is inspected
      Then it includes `base_used`
      And it includes `context_file`
      And it includes `scope_baseline_file`
      And it includes `section_locks`
      And it includes `experience_role_allowlist`

    Scenario: Scope guard prevents edits outside the allowed tailoring boundary
      Given the build has a workspace baseline and scope constraints
      When finalize validation checks the proposed resume edits
      Then edits outside locked sections or outside the allowed experience-role scope are rejected
      And out-of-scope changes do not silently pass through finalize

    Scenario: Base resume track is selected automatically and persisted in workspace metadata
      Given a job posting is eligible for tailoring
      When Resume Tailoring chooses the base resume track
      Then the most appropriate base track is selected from JD and context signals
      And the selected track is persisted in `meta.yaml` as `base_used`

    Scenario: Tailoring run lifecycle is persisted from bootstrap through mandatory agent review
      Given a job posting is eligible for tailoring
      When workspace bootstrap begins
      Then a `resume_tailoring_runs` row is created for that run
      And that row begins with `tailoring_status = in_progress`
      And that row begins with `resume_review_status = not_ready`
      When finalize succeeds for that same run
      Then the run transitions to `tailoring_status = tailored`
      And the run transitions to `resume_review_status = resume_review_pending`
      When the mandatory agent review finishes for that same run
      Then the run transitions to `resume_review_status = approved`

    Scenario: Current default editing scope stays narrow unless metadata expands it
      Given the build is tailoring a posting under the default scope rules
      When candidate edits are produced
      Then the editable areas are limited to `summary`, `technical-skills`, and the `software-engineer` experience block
      And locked sections outside that scope are not rewritten unless `meta.yaml` explicitly changes the allowed scope

    Scenario: Tailored resume shows credible overlap with the target role and JD intent
      Given a job posting has clear role intent, responsibilities, and must-have requirements
      When Resume Tailoring completes a role-targeted run
      Then the tailored resume shows clear overlap between the target role and the candidate's real experience
      And the `summary` is updated to reflect the JD's role intent in an evidence-grounded way
      And the `summary` remains neutral rather than sounding inflated or fabricated
      And the `software-engineer` experience block emphasizes similar or adjacent work that makes the candidate relevant to the position
      And the tailoring output includes traceable evidence mapping rather than opaque rewriting
      And honest gaps are surfaced instead of being hidden or fabricated

    Scenario: JD-relevant stack is reflected in summary-adjacent sections, work experience, and skills ordering
      Given a job posting emphasizes a specific technical stack in a meaningful order
      When Resume Tailoring emits the current Step 6 payload
      Then `software-engineer.tech-stack-line` is updated to match the selected role framing
      And the stack line stays consistent with the technologies actually reflected in the `software-engineer` work-experience bullets
      And JD-relevant technologies are ordered earlier when they are truthfully supported by candidate evidence
      And `technical-skills` is updated to foreground JD-relevant tools and categories
      And `technical-skills` remains category-clean rather than mixing unrelated groups chaotically
      And a JD-requested tool that is truthfully supported but not central to the work-experience bullets may appear later in the relevant skills line rather than being omitted
      But unsupported stack terms are not inserted only to mimic the JD

    Scenario: Step artifacts preserve JD-only extraction and honest evidence mapping
      Given Resume Tailoring has completed the current intelligence steps
      When the Step 3 and Step 4 artifacts are inspected
      Then Step 3 reflects JD-derived signals without being filtered by candidate evidence first
      And Step 4 records traceable evidence matches, source references, confidence, and honest gaps
      And the system does not force fake coverage for every JD requirement

    Scenario: JD signal weighting uses one current global default scale
      Given Resume Tailoring has produced JD signals with must-have, core-responsibility, nice-to-have, and informational priorities
      When current weighting is inspected for coverage or matching logic
      Then the build uses one shared default weighting scale across role-targeted postings
      And must-have signals outrank core responsibilities
      And core responsibilities outrank nice-to-have signals
      And nice-to-have signals outrank informational signals
      And the build does not require role-family-specific weight calibration

    Scenario: Step 6 payload uses the current structured edit contract
      Given Resume Tailoring has produced candidate resume edits
      When the Step 6 output is inspected
      Then it contains `summary`
      And it contains `technical-skills`
      And it contains `software-engineer.tech-stack-line`
      And it contains `software-engineer.bullets`

    Scenario: Step 5 controlled elaboration stays within allowed bounded evidence moves
      Given Resume Tailoring is producing Step 5 elaboration for one selected project boundary
      When the Step 5 artifact and claim ledger are inspected
      Then the elaboration may clarify architecture, data flow, known impact, or interview-safe narrative within that same project boundary
      And every retained claim is labeled as either `direct_evidence` or `bounded_inference`
      But the system does not invent a new project, ownership area, metric, technology, or scope boundary

    Scenario: Work-experience bullets preserve numeric metrics and resume-writing discipline
      Given the evidence map or master profile contains defensible project metrics
      When Resume Tailoring writes the `software-engineer` experience bullets
      Then the build produces exactly 4 bullets for that experience block
      And bullets use numeric metric style instead of spelled-out number forms when metrics are present
      And relevant bullets retain concrete numbers or metrics whenever truthful supporting evidence exists
      And bullets follow impact-first resume-writing structure closely enough to show meaningful overlap and outcomes
      And bullets stay within the current character-budget constraints

    Scenario: Final output remains compile-safe, one-page, and visually disciplined
      Given Resume Tailoring has produced candidate edits and verification has passed
      When finalize compiles the tailored resume
      Then the final output compiles to `Achyutaram Sonti.pdf`
      And the final output remains one page
      And tailored text remains LaTeX-safe and free of stray compile-breaking symbols
      And reserved characters are escaped correctly when needed
      And the resulting page does not waste substantial whitespace without a layout or content reason
      And the resume remains visually readable rather than collapsing into crowded or malformed formatting

    Scenario: Finalize requires valid intelligence and one-page output
      Given Resume Tailoring has produced Steps 3 through 7
      When finalize is attempted
      Then finalize succeeds only if Steps 3, 4, and 7 are valid
      And Step 7 is not `pending`
      And the final output compiles to `Achyutaram Sonti.pdf`
      And the final output remains one page

    Scenario: Insufficient evidence or scope conflicts return explicit revision guidance instead of guessing
      Given a requested tailoring change lacks defensible evidence or violates scope constraints
      When verification evaluates the candidate edits
      Then the result is `needs-revision` or `fail`
      And the output includes explicit blockers or revision guidance
      And the system does not fabricate claims to satisfy the JD

    Scenario: Tailoring overrides are persisted when the owner changes an agent-reviewed tailoring decision
      Given a role-targeted posting already has a tailoring outcome
      And the mandatory agent review has already produced a decision for that outcome
      And the owner applies an eligibility or tailoring override
      When the override is recorded
      Then the override includes the previous decision context
      And the override includes `override_reason`
      And the override includes `override_timestamp`
      And the affected posting can continue under the overridden decision

    Scenario: Role-targeted flow runs a mandatory agent review without a mandatory human pause
      Given a role-targeted tailored resume has been produced
      And finalize and verification have succeeded
      When the current flow reaches the tailoring review boundary
      Then the active tailoring run enters `resume_review_pending`
      And the mandatory reviewer is the agent rather than a human
      When the agent review approves that tailored output
      Then downstream contact search, selected-contact enrichment, email discovery, draft, and send work may continue without explicit user approval

    Scenario: Review rejection followed by retailoring preserves run history
      Given a role-targeted posting already has one completed tailoring run awaiting or following review
      And the owner rejects that tailored output and requests retailoring
      When Resume Tailoring runs again for that same posting
      Then a new `resume_tailoring_runs` row is created for the new attempt
      And the previous run row is preserved rather than overwritten

  @email_discovery
  Rule: Email Discovery behavior

    Scenario: Role-targeted contact search starts with Apollo people search
      Given a role-targeted posting needs internal contacts
      When company-scoped contact search runs
      Then Apollo is used first for people search
      And the broad candidate result is preserved in `people_search_result.json`
      And only shortlisted candidates are normalized into canonical `contacts`
      And posting-contact links are created or updated only for shortlisted candidates
      And selected contacts without usable emails may continue into person-scoped email discovery

    Scenario: Apollo people search resolves company identity before people search and tolerates sparse candidate rows
      Given a role-targeted posting needs company-scoped internal contacts
      When Apollo-backed people search runs
      Then the company is resolved to an organization record first when Apollo can do so
      And the resolved `organization_id` is used as the preferred people-search anchor when available
      And the system tolerates sparse candidate rows such as obfuscated names when stable provider identity exists
      And `people_search_result.json` preserves the resolved company record, applied filters, and returned candidate rows

    Scenario: Initial enrichment stays selective and capped to the current shortlist policy
      Given a broad Apollo people search has returned many candidate contacts for a posting
      When the build chooses the first enrichment wave
      Then no more than 6 contacts are selected into the initial enrichment shortlist
      And that shortlist aims to cover recruiter, manager-adjacent, and engineer recipient classes before lower-priority internals
      And broad-search candidates outside that shortlist are not enriched by default

    Scenario: LinkedIn URL from enrichment can produce a recipient profile snapshot before drafting
      Given a shortlisted contact has completed enrichment successfully
      And enrichment returns a LinkedIn URL for that contact
      When recipient-profile enrichment runs
      Then `recipient_profile.json` is persisted for that contact when public profile extraction succeeds
      And later drafting may use that persisted profile snapshot when it provides genuinely useful grounded context

    Scenario: Shortlisted candidate that becomes a terminal enrichment dead end is removed from canonical shortlist state
      Given a broad people search result has been persisted for a posting
      And a candidate from that result has been shortlisted and materialized canonically
      When enrichment determines that candidate will not continue into email discovery or outreach
      Then the posting-contact link for that candidate is removed from canonical shortlist state
      And the broad search artifact still preserves that the candidate was seen in the search result

    Scenario: Person-scoped email discovery uses the current provider order and stops on first usable result
      Given a selected contact has a name and company context
      And person-scoped email discovery is required
      When Email Discovery runs
      Then the provider order is `prospeo`, then `getprospect`, then `hunter`
      And discovery stops when a usable provider email candidate is returned
      And the result is persisted in canonical discovery history

    Scenario: Discovery returns either a usable email or an explicit unresolved outcome
      Given a linked contact is ready for discovery
      When Email Discovery completes its cascade
      Then the outcome is either a discovered working email or an explicit unresolved or not-found state
      And the result is available through `discovery_result.json`
      And attempts and outcomes are queryable from `job_hunt_copilot.db`

    Scenario: Provider-specific no-match responses normalize to explicit internal not-found outcomes
      Given Email Discovery receives a non-error no-match response from a provider
      When the provider result is normalized
      Then Prospeo `NO_MATCH` is treated as an explicit no-match outcome
      And GetProspect `success = false` with `status = not_found` is treated as an explicit no-match outcome
      And Hunter responses with `data.email = null` are treated as an explicit no-match outcome
      And those cases are not mislabeled as provider execution failures

    Scenario: Discovery reuses known working email only when identity is clear
      Given `job_hunt_copilot.db` already contains a known working email for a contact
      When a later run refers to the same clearly identified contact
      Then Email Discovery reuses that stored working email
      And new provider calls are skipped for that contact
      But if identity is ambiguous then a fresh lookup is performed instead

    Scenario: Current build does not reuse one contact's pattern for other contacts at the same company
      Given a working email has already been found for one contact at a company
      When Email Discovery runs for a different contact at that same company
      Then the build does not infer or generate a new email only from the prior discovered pattern
      And company-level pattern reuse remains deferred

    Scenario: Discovery resolves company domain internally and records a distinct domain-unresolved outcome when needed
      Given a provider path requires a company domain for a linked contact
      When Email Discovery cannot resolve a usable company domain from the available company context
      Then the attempt records a distinct `domain_unresolved` reason instead of collapsing to generic `not_found`
      And provider paths that do not require a domain may still continue for that same contact

    Scenario: Discovery updates provider-budget state and falls back when a provider is exhausted
      Given provider-based discovery is running through the current cascade
      When a provider is used, exhausted, or rate-limited
      Then per-provider budget state is updated in canonical storage
      And provider balances reflect provider-reported values when those values are available
      And providers without a reliable balance signal remain explicitly unknown rather than using fabricated placeholder values
      And provider budget events are recorded for later audit
      And the cascade falls through to the next remaining provider in order when possible

    Scenario: Discovery confidence follows current pre-send and post-send policy
      Given Email Discovery finds a provider-returned candidate email before any send occurs
      When confidence is evaluated before send
      Then pre-send confidence reflects provider-verified confidence rather than synthetic certainty
      When that same email is later sent and no bounce is observed during the configured observation window
      Then post-send confidence may advance to `100%`

    Scenario: Discovery retry after a bounced result skips the provider that already failed
      Given a contact previously received a discovered email that later bounced
      When Email Discovery is retried for that same contact
      Then the next discovery attempt does not restart with the provider that produced the bounced email
      And the exact same bounced email address is not accepted again as a fresh usable result

    Scenario: Provider exhaustion for a contact surfaces review instead of endless retries
      Given all current providers have been exhausted for a contact without producing a non-bounced result
      When the current discovery attempt finishes
      Then discovery stops for that contact
      And the contact is surfaced for user review rather than retried indefinitely in the same automatic flow

    Scenario: Discovery history is preserved as cascade-level attempts without overwriting prior outcomes
      Given the same contact undergoes multiple discovery attempts over time
      When those attempts are persisted
      Then `discovery_attempts` stores one row per completed discovery cascade
      And prior failed or unresolved attempts are not overwritten by later attempts
      And no-result attempts remain available for later analysis and future learning

    Scenario: Unresolved and bounced discovery review surfaces remain queryable
      Given discovery has produced unresolved contacts and later bounced-email cases
      When review-oriented discovery queries are run
      Then unresolved contacts are queryable with their unresolved reason details
      And bounced-email cases are queryable through the dedicated bounced review surface

  @drafting @sending
  Rule: Email Drafting and Sending behavior

    Scenario: Role-targeted outreach uses posting, recipient, and tailored resume context
      Given a job posting is ready for role-targeted outreach
      And a linked contact has a usable email
      And the active tailoring run is agent-approved
      When Email Drafting and Sending runs for that contact
      Then the draft uses job-posting context, recipient-profile context, and tailored-resume context
      And the exact final sent subject and body are persisted
      And `send_result.json` is produced as the machine handoff artifact

    Scenario: General learning outreach does not require a tailored resume or posting linkage
      Given a contact-rooted outreach is not tied to a specific job posting
      When Email Drafting and Sending runs in general learning mode
      Then no tailored resume is required
      And no role-targeted resume attachment is required
      And the draft follows a learning-first posture

    Scenario: Repeat outreach requiring interpretation is not auto-sent
      Given a contact already has prior outreach history
      When a new automatic outreach run considers that contact
      Then the system does not auto-send a new message
      And the case is surfaced for user review

    Scenario: Autonomous role-targeted sending respects per-posting pacing
      Given multiple contacts across one or more postings become ready for autonomous role-targeted outreach
      When send scheduling evaluates those contacts
      Then no more than 4 emails are sent for the same posting on the same day
      And additional same-posting sends are delayed or queued for a later allowed send window
      And any two automatic sends are separated by the current randomized 6-to-10-minute pacing gap rather than sent back-to-back

    Scenario: Later postings at the same company proactively skip an already-contacted person
      Given one posting at a company has already sent automatic outreach to a canonical contact
      And a later posting at that same company links that same canonical contact plus other eligible company contacts
      When orchestration evaluates the later posting for automatic outreach
      Then the already-contacted canonical contact is excluded from automatic send-set selection for the later posting
      And orchestration continues with alternate eligible contacts from that company when they exist

    Scenario: Later postings with no alternate same-company contacts do not auto-send a second email
      Given one posting at a company has already sent automatic outreach to a canonical contact
      And a later posting at that same company has no alternate automatically eligible contacts left after exclusions
      When orchestration evaluates the later posting for automatic outreach
      Then the system does not auto-send a second role-targeted email to that same canonical contact
      And the later posting is surfaced for review instead

    Scenario: Current autonomous send set prefers recruiter, manager-adjacent, and engineer coverage without a global daily cap
      Given a company has enough viable contacts across multiple recipient classes
      When the build forms the current autonomous send set for that company and day
      Then the default send set prefers one recruiter, one manager-adjacent contact, and one team-adjacent engineer when those classes are available
      And the current build does not impose a separate global cross-company daily send cap

    Scenario: Role-targeted one-step outreach uses personalization, overlap, and a low-friction ask
      Given a job posting is ready for outreach and a linked contact has usable profile context
      When Email Drafting and Sending creates a role-targeted draft
      Then the draft uses one-step direct outreach rather than the deferred two-step flow
      And the opening uses role, team, or work-area context rather than a generic self-introduction
      And the draft includes a grounded reason for reaching out to that specific recipient
      And the body shows visible overlap between the role and the sender's relevant background
      And the draft ends with a low-friction next step rather than a heavy ask

    Scenario: Drafting begins only after the full current send set is ready
      Given multiple contacts are intended for the current send set
      And at least one contact becomes ready earlier than the others
      When orchestration evaluates whether drafting may begin
      Then drafting does not begin for that one ready contact alone
      And drafting begins only after the full current send set is ready

    Scenario: The active ready send set is drafted before automatic sending begins
      Given the full current send set is ready for role-targeted outreach
      When Email Drafting and Sending prepares that send set
      Then the system first generates and persists the drafts for that send set
      And automatic sending begins only after that draft-generation phase completes for the ready set

    Scenario: Failed drafts do not block sending for successfully drafted contacts in the same ready set
      Given the current ready send set contains multiple contacts
      And draft generation fails for one contact in that set
      When draft generation for the ready set completes
      Then successfully generated drafts from that same set may still proceed into sending
      And the failed draft case is surfaced for review

    Scenario: Recruiter and team-adjacent outreach defaults to a short Zoom conversation ask
      Given the recipient type is recruiter or another team-adjacent one-step outreach target
      When a role-targeted outreach draft is generated
      Then the default call to action is a short 15-minute Zoom conversation
      And the draft does not default to a phone-call ask for that current-path recipient

    Scenario: Rich HTML outreach preserves readable fallback content and canonical message persistence
      Given Email Drafting and Sending produces a rich HTML outreach email
      When the send record is persisted
      Then the final sent subject and body are stored in canonical state
      And the final rendered HTML is persisted when HTML was used
      And a reasonable plain-text-compatible fallback representation remains available
      And the message is stored in `outreach_messages`

    Scenario: Human-readable and machine-readable drafting artifacts are both available
      Given an outreach draft has been generated or sent
      When the resulting artifacts are inspected
      Then `email_draft.md` is available as a human-readable companion artifact
      And `send_result.json` is available as the machine handoff artifact
      And `send_result.json` includes the shared contract envelope and relevant stable IDs

    Scenario: Default v4 shared template uses the current unified structure
      Given a role-targeted draft is generated with the default v4 shared template
      When the resulting draft is inspected
      Then it opens from role, team, or work-area context rather than requiring recipient-background hooks
      And it includes an explicit `why I am reaching out to you` line
      And it includes one concrete proof point of fit
      And it uses one 15-minute Zoom ask
      And any forwardable snippet is placed directly below the routing-help line

    Scenario: Internal-helper or alumni outreach may include a forwardable summary snippet
      Given the recipient type is internal helper, referral-style contact, or alumni-style contact
      When the outreach strategy benefits from easy internal forwarding
      Then the draft may include a compact forwardable summary snippet
      And that snippet stays small enough to be plausibly forwarded with little or no editing
      But a forwardable snippet is not treated as mandatory for every recipient type

  @delivery_feedback
  Rule: Delivery Feedback behavior

    Scenario: Delivery feedback uses mailbox observation with the current timing rules
      Given an outreach message has been sent
      When Delivery Feedback runs
      Then one immediate post-send mailbox poll is allowed
      And delayed polling continues every 5 minutes during the 30-minute bounce-observation window
      And delayed feedback capture does not require the original interactive send session to remain running

    Scenario: Delivery feedback may begin immediately for each sent message
      Given multiple messages are being sent as part of the current send set
      When one specific send succeeds before the rest of the set has finished sending
      Then Delivery Feedback may begin bounce or reply observation for that sent message immediately
      And feedback observation for that message does not wait for the rest of the current send set to finish

    Scenario: Delivery feedback persists canonical event history and machine handoff output
      Given a sent message later receives a bounce, not-bounced, or reply signal
      When Delivery Feedback ingests that signal
      Then the outcome is written as an event into `delivery_feedback_events`
      And the event includes an explicit timestamp
      And `delivery_outcome.json` is produced as the machine handoff artifact
      And the latest state is derivable from event history rather than overwriting that history

    Scenario: Bounced outcomes do not automatically rewrite discovery cache in the build
      Given a sent email later bounces
      When Delivery Feedback records the bounced outcome
      Then the bounced case is surfaced for owner review
      And discovery cache or reusable-email state is not automatically rewritten by that bounce in the build

    Scenario: Delayed feedback scheduling uses launchd in the current deployment
      Given the build is deployed on the supported single-user macOS setup
      When delayed feedback polling is configured
      Then `launchd` is used as the scheduler for recurring feedback sync
      And the scheduler invokes reusable Delivery Feedback sync logic rather than embedding mailbox logic directly
      And scheduled runs are auditable through `feedback_sync_runs`

    Scenario: Not-bounced is recorded when the observation window closes without a bounce
      Given an outreach message has been sent
      And no bounce signal is detected within the 30-minute observation window
      When the observation window completes
      Then Delivery Feedback may record a `not_bounced` event for that sent message
      And later reply detection may still continue after that not-bounced conclusion

    Scenario: Reply detection retains useful reply context without requiring reply classification
      Given a sent outreach message later receives a reply
      When Delivery Feedback ingests that reply signal
      Then the resulting event is recorded with state `replied`
      And useful reply content or reply summary is retained when available
      But reply classification such as positive or negative is not required in the build

    Scenario: Bounce and not-bounced outcomes are reusable for discovery while replies remain review-only
      Given Delivery Feedback has recorded bounced, not-bounced, and replied outcomes over time
      When later discovery-oriented reuse logic inspects those outcomes
      Then bounced and not-bounced outcomes may inform reusable discovery state
      But replied outcomes remain retained for review rather than entering the current discovery-learning loop

    Scenario: Feedback events are tied to the exact sent message instance
      Given multiple outreach messages may exist over time for the same contact
      When Delivery Feedback records a bounce, not-bounced, or replied event
      Then the event is linked to the exact `outreach_message_id`
      And mailbox or provider identifiers such as thread ID remain secondary linkage references rather than the canonical identifier

    Scenario: Feedback events are persisted immediately when detected
      Given Delivery Feedback detects a mailbox-observed bounce or reply signal
      When the event is recognized
      Then canonical feedback state is updated immediately
      And the system does not wait for a later batch sync to persist that event

    Scenario: Reply outcomes remain reviewable without entering the current discovery-learning loop
      Given Delivery Feedback has recorded one or more `replied` outcomes
      When discovery-facing feedback is considered
      Then bounced and not-bounced outcomes are available as discovery feedback
      And replied outcomes remain available for review and outreach analysis
      But replied outcomes are not part of the current discovery-learning loop

  @supervisor @ops
  Rule: Supervisor Agent behavior

    Scenario: Supervisor heartbeat runs under launchd and rebuilds fresh context from persisted state
      Given the current local deployment is the supported single-user macOS setup
      When the autonomous control plane is configured
      Then the supervisor heartbeat runs through `launchd`
      And the current heartbeat interval is 3 minutes
      And each heartbeat may use a fresh LLM context
      But that context is rebuilt from canonical state, runtime identity or policy artifacts, selected durable work units, and only the local evidence needed for those work units

    Scenario: Runtime self-awareness comes from the generated identity and policy pack
      Given the supervisor and chat operator are running in the current build
      When their runtime bootstrap inputs are inspected
      Then both use the generated runtime identity and policy artifacts under `ops/agent/`
      And they share the same canonical state, policies, incidents, and review queues
      And normal operation does not depend on rereading the full PRD on every heartbeat

    Scenario: Heartbeats resume durable pipeline runs rather than creating duplicate work
      Given a role-targeted posting already has an active non-terminal `pipeline_run`
      When a later supervisor heartbeat evaluates that posting
      Then the existing `pipeline_run` is resumed
      And a second non-terminal run for the same `job_posting_id` is not created
      And terminal runs remain immutable operational history

    Scenario: Supervisor control, incident, run, and review-packet states follow the current canonical semantics
      Given the supervisor control-plane tables are active in canonical state
      When their current semantics are inspected
      Then `pipeline_runs` use durable run statuses such as `in_progress`, `paused`, `escalated`, `failed`, and `completed`
      And `pipeline_runs.review_packet_status` uses `not_ready`, `pending_expert_review`, `reviewed`, and `superseded`
      And `agent_control_state` distinguishes enabled or running, enabled or paused, and disabled or stopped operation
      And `agent_incidents` use `open`, `in_repair`, `resolved`, `escalated`, and `suppressed`
      And `expert_review_packets.packet_status` uses `pending_expert_review`, `reviewed`, and `superseded`

    Scenario: Supervisor leases prevent overlapping cycles and allow stale recovery
      Given one supervisor heartbeat has already acquired the current runtime lease
      When another heartbeat fires before that lease expires
      Then the later heartbeat defers instead of starting overlapping work
      When the earlier lease becomes stale or expired
      Then a later heartbeat may reclaim the lease and resume from canonical state

    Scenario: Supervisor cycles follow the current bounded single-work-unit algorithm
      Given autonomous operation is enabled
      When one supervisor cycle runs
      Then it reads current control state before selecting work
      And it evaluates auto-pause conditions before normal progression
      And it selects at most one primary work unit or one tightly related object cluster by default
      And it validates action prerequisites before execution
      And it validates expected outputs and canonical state updates after execution
      And it persists a cycle summary before releasing or expiring the lease

    Scenario: Supervisor work selection follows the current default priority order
      Given multiple kinds of autonomous work are simultaneously due
      When the supervisor selects the next work unit
      Then control-state changes outrank all other work
      And open incidents and health-critical failures outrank ordinary pipeline advancement
      And due sends and due feedback polling outrank new Gmail ingestion and maintenance
      And bounded maintenance work remains the lowest default priority

    Scenario: Supervisor chooses only registered catalog actions and escalates unknown needs
      Given the supervisor has selected a work unit
      When it decides the next autonomous action
      Then that action must come from `ops/agent/action-catalog.yaml`
      And the chosen action has defined prerequisites, expected outputs, and canonical-state updates
      But if the needed next move is not covered by the registered catalog then the system escalates instead of improvising broad behavior

    Scenario: Review-worthy terminal runs always generate expert review packets
      Given a role-targeted `pipeline_run` reaches a successful, failed, blocked, or escalated review-worthy terminal outcome
      When the supervisor finalizes that run outcome
      Then both `review_packet.json` and `review_packet.md` are generated
      And the run's `review_packet_status` becomes `pending_expert_review`
      And early failures or blocked outcomes may use lighter relevance-shaped packets instead of a rigid full template

    Scenario: Auto-pause triggers on critical incidents or repeated unresolved incident clusters
      Given the supervisor is running autonomously
      When an unresolved `critical` incident affects send safety, duplicate-send risk, credential handling, or canonical-state integrity
      Then the system auto-pauses immediately
      When 3 unresolved incidents of the same type occur in the same stage, provider area, or operational area within 45 minutes
      Then the system also auto-pauses
      And new pipeline runs and new automatic sends do not begin while that auto-pause remains active

    Scenario: Paused and stopped modes have different operational boundaries
      Given the supervisor control state is persisted canonically
      When `agent_mode = paused`
      Then new pipeline progression and new automatic sends are blocked
      But safe observational work such as feedback polling, reporting, and chat-based inspection may still continue
      When `agent_mode = stopped`
      Then background autonomous execution is disabled until restarted
      But chat-based inspection remains available

    Scenario: jhc-agent-start starts once and jhc-agent-stop preserves state
      Given the local helper entrypoints are installed
      When `jhc-agent-start` is invoked
      Then it enables autonomous background operation
      And it loads or bootstraps the `launchd` supervisor job
      And it behaves idempotently without creating duplicate scheduler registrations
      When `jhc-agent-stop` is invoked
      Then future heartbeats are disabled
      And canonical state, incidents, review packets, and artifacts remain preserved

    Scenario: Current supervisor launchd and wrapper wiring uses the repo-local command path
      Given the current local macOS deployment is using the supported supervisor wiring
      When the supervisor launchd job and helper scripts are inspected
      Then `ops/launchd/job-hunt-copilot-supervisor.plist` uses `Label = com.jobhuntcopilot.supervisor`
      And it uses `RunAtLoad = true`, `StartInterval = 180`, and `KeepAlive = false`
      And it points `ProgramArguments` to `bin/jhc-agent-cycle` under the absolute project root
      And `bin/jhc-agent-cycle` runs `python3 scripts/ops/run_supervisor_cycle.py --project-root <absolute project root>`
      And supervisor stdout and stderr are written to dedicated files under `ops/logs/`

    Scenario: jhc-agent-start and jhc-agent-stop use the current launchctl wiring
      Given the current local helper entrypoints are installed
      When `jhc-agent-start` is invoked
      Then it runs the runtime-pack materialization step before enabling background execution
      And it ensures the supervisor plist is rendered with absolute project-root paths
      And it uses `launchctl bootstrap` or an equivalent idempotent load-if-needed step
      And it uses `launchctl kickstart -k gui/$UID/com.jobhuntcopilot.supervisor` for the immediate first heartbeat
      When `jhc-agent-stop` is invoked
      Then it writes disabled or stopped control state before unloading the job
      And it uses `launchctl bootout` or an equivalent idempotent unload step

    Scenario: jhc-chat is the direct Codex-backed operator entrypoint
      Given the expert wants to inspect or control the autonomous system
      When `jhc-chat` is opened
      Then it launches the project-specific Codex-backed chat operator directly
      And the expert does not need to open a generic Codex session first
      And on startup it reads control state, runtime identity or policy files, current incidents, pending review packets, and the relevant canonical DB snapshot

    Scenario: jhc-chat uses explicit session begin and end wiring in the current build
      Given the current local chat helper is installed
      When `jhc-chat` is opened
      Then it records chat-session begin state before launching the Codex operator
      And it launches Codex rooted at the project directory using `ops/agent/chat-bootstrap.md` as startup instructions
      When the chat is closed cleanly
      Then it records chat-session end with `explicit_close`
      When the chat exits unexpectedly
      Then it records chat-session end with `unexpected_exit`

    Scenario: jhc-chat startup dashboard is detailed, bounded, and clean-first
      Given `jhc-chat` has just started and loaded current state
      When the startup response is shown
      Then it proactively shows a dashboard-style summary without waiting for the first request
      And the first view stays clean rather than dumping low-level file paths or object IDs
      And it always includes pending expert review items, open incidents, and maintenance state
      And it includes runtime totals for today, yesterday, and rolling average daily runtime
      And it includes successful run counts, successful send counts, bounce counts, and reply counts for today and yesterday

    Scenario: Startup dashboard runtime metrics count only active autonomous execution
      Given the system has both active autonomous runtime and paused expert-interaction time
      When the startup dashboard computes runtime totals
      Then it counts only active autonomous background execution time
      And it excludes paused expert-interaction time and other non-executing intervals

    Scenario: Review retrieval is grouped, compact-first, and newest-first within each group
      Given there are pending expert review packets, failed expert-requested tasks, maintenance batches, and open incidents
      When the expert asks `show me items for review`
      Then the response is grouped by item type rather than mixed into one stream
      And items are newest-first within each group
      And the default group order is expert review packets, failed or unresolved expert-requested background tasks, autonomous maintenance change batches, then open incidents
      And the first presentation is a compact summary list before deeper detail is expanded

    Scenario: Progress log, ops plan, and context snapshot use the current exact file shapes
      Given the current autonomous control plane is persisting its supervisor artifacts
      When the current-build file contracts are inspected
      Then `ops/agent/progress-log.md` uses the ordered sections `Current Summary`, `Current Blockers`, `Next Likely Action`, `Latest Replan / Maintenance Note`, `Recent Entries`, and `Daily Rollups`
      And `ops/agent/ops-plan.yaml` uses the top-level keys `contract_version`, `generated_at`, `agent_mode`, `active_priorities`, `watch_items`, `maintenance_backlog`, `weak_areas`, and `replan`
      And each `context_snapshot.json` includes `selected_work`, `state_summary`, `candidate_actions`, `evidence_refs`, and `evidence_excerpts`
      And `sleep_wake_recovery_context` is included when the cycle is recovery-related

    Scenario: jhc-chat uses persisted state for answers and control routing
      Given the expert is interacting through `jhc-chat`
      When the expert asks for inspection-only status or review information
      Then `jhc-chat` rereads the relevant persisted state before answering
      And read-only requests do not mutate canonical state
      When the expert issues pause, resume, stop, or object-specific override requests
      Then global controls are routed through `agent_control_state`
      And object-specific overrides are routed through canonical object updates plus `override_events`

    Scenario: Current macOS sleep or wake detection uses pmset logs first and conservative fallback second
      Given the current deployment is the supported local macOS build
      When sleep or wake detection is evaluated
      Then the primary power-event source is `pmset -g log`
      And recent `Sleep`, `Wake`, and `DarkWake` lines are parsed before relying on timing-only heuristics
      And `pmset -g uuid` may be used as supporting correlation data
      But `pmset -g stats` is diagnostic only and not the authoritative event trigger
      And if explicit OS sleep or wake evidence is unavailable then a gap greater than 1 hour since the last started or completed supervisor cycle forces sleep or wake recovery

    Scenario: Default change summaries cover activity since the last completed expert review
      Given autonomous work, maintenance batches, and other reviewable updates have accumulated over time
      When the expert asks `what changed` without specifying a custom time window
      Then the default summary covers activity since the last completed expert review
      And the response still includes autonomous maintenance change outcomes in that window

    Scenario: Expert guidance becomes live immediately but conflicting or uncertain reuse asks first
      Given the expert has issued guidance, correction, or an override through the approved interface
      When that decision is persisted
      Then it becomes live operating guidance immediately
      And by default it affects the current object plus similar future cases unless the expert narrows it
      And any generalized future use persists lineage to the source expert decision
      But if the agent is not confident that a future case is similar enough, or if new expert guidance conflicts materially with older standing guidance, the system asks the expert before proceeding

    Scenario: Conflicting expert guidance pauses the whole autonomous system
      Given a new expert instruction materially conflicts with standing policy or older persisted expert guidance
      When the agent detects that conflict
      Then the whole autonomous system pauses
      And the conflict is surfaced for clarification through `jhc-chat`
      But `jhc-chat` itself remains fully available for inspection and resolution

    Scenario: Opening jhc-chat immediately pauses autonomous work and safe checkpointing is strict
      Given the autonomous supervisor is currently running
      When the expert opens `jhc-chat`
      Then expert presence is detected immediately at chat startup
      And autonomous background progression pauses
      And if a supervisor cycle is already active it stops at the next strict safe checkpoint
      And no new side-effectful step begins after the pause is observed
      And an in-flight side-effectful step performs only the minimum validation or writeback needed to leave state coherent before stopping

    Scenario: Expert-interaction resume follows explicit close, explicit resume, or safe idle timeout
      Given the system is paused because the expert is actively using `jhc-chat`
      When the expert explicitly resumes
      Then autonomous progression may resume immediately if no other pause condition exists
      When the expert explicitly closes `jhc-chat`
      Then that close counts as immediate safe auto-resume
      When `jhc-chat` exits unexpectedly
      Then the system follows the idle-timeout resume path instead of treating the crash as an explicit close
      And automatic resume still requires that no clarification or other active pause condition remains

    Scenario: Expert-requested background tasks require explicit handoff summary and exclusive focus
      Given the expert gives `jhc-chat` a longer investigation, repair, or implementation task
      When the agent wants to hand that task into background autonomous execution
      Then it first gives an explicit summary of scope, expected outputs, risks or assumptions, what will and will not change, and the completion condition
      And once handed off that task becomes the active autonomous priority
      And unrelated normal autonomous pipeline work stays paused until that task finishes or is explicitly released

    Scenario: Expert-requested background task outcomes return to review appropriately
      Given a longer expert-requested background task has been handed off
      When that task fails, stalls, or reaches an unresolved review-worthy state
      Then it is returned to expert review with persisted evidence instead of being retried forever
      And unrelated routine autonomous operations may later continue if no other global pause condition remains
      When that task finishes successfully
      Then its result is automatically surfaced into the expert review queue

    Scenario: Daily maintenance is mandatory, bounded, and run-boundary aware
      Given autonomous operation remains enabled across a full local calendar day
      When the supervisor schedules maintenance
      Then one bounded maintenance cycle is completed at least once that day
      And the supervisor prefers to run maintenance after a completed end-to-end run and before the next new run
      And it does not interrupt an active end-to-end run solely to satisfy maintenance
      And autonomous code or config changes are allowed only during that maintenance cycle
      And no more than one autonomous change batch is produced in a single daily maintenance cycle unless the expert explicitly overrides it

    Scenario: Maintenance changes follow the current git and approval workflow
      Given the supervisor produces an autonomous maintenance change batch
      When that change batch is prepared
      Then it is created on a dedicated maintenance branch rather than directly on the main working tree
      And the default branch naming follows `maintenance/{YYYYMMDD-local}-{maintenance_change_batch_id}-{scope_slug}`
      And the change batch produces a git-tracked checkpoint before merge
      And the canonical maintenance approval outcome is persisted in `maintenance_change_batches`
      And merge into the main operational code path happens only after explicit approval and required validation succeed
      And the normal merge commit subject follows `merge(maintenance): {maintenance_change_batch_id} {scope_slug}`
      And the merged change may be used automatically by later heartbeats

    Scenario: Proper maintenance validation requires both change-scoped and full-project testing
      Given an autonomous maintenance change batch modifies code or config
      When the system evaluates whether that batch may be approved and merged
      Then it first runs change-scoped validation for the modified areas
      And it also runs a broader full-project validation layer
      And merge is blocked unless both layers pass

    Scenario: Failed or unapproved maintenance batches remain reviewable
      Given an autonomous maintenance change batch fails validation or is not approved
      When the batch reaches that outcome
      Then the batch does not become operational
      And the maintenance branch or isolated change unit is retained for inspection
      And its validation evidence and changed-file summary remain available
      And the batch appears in expert-facing change or review summaries

  @review @observability
  Rule: Review surfaces and chat-based control

    Scenario: AI agent surfaces the current review queue in chat
      Given canonical state contains pending review items
      When the user says they are ready to review
      Then the AI agent presents the relevant review items from statuses, review queues, and linked artifacts
      And the user does not need to manually reconstruct what needs attention

    Scenario: Review surfaces are queryable from canonical state
      Given the system has processed postings, contacts, and messages
      When review-oriented queries are run
      Then the system can show posting-level states such as `resume_review_pending` and `requires_contacts`
      And the system can show contact-level states such as `working_email_found`, `sent`, and `replied`
      And the system can show unresolved discovery cases and bounced-email review cases
      And the system can show pending expert review packets and open agent incidents

    Scenario: Blocked, failed, and repeat-outreach cases are reviewable without log spelunking
      Given the build has produced blocked, failed, or repeat-contact review cases
      When the user asks to review outstanding work
      Then the AI agent can surface those review items from canonical state
      And the user does not need to reconstruct them from raw logs or mailbox inspection

    Scenario: Owner overrides remain queryable after they are applied
      Given one or more overrides have been applied during review
      When override history is queried
      Then the system can show the affected object
      And it can show the prior decision or state
      And it can show the new decision or state
      And it can show the override reason and timestamp

    Scenario: Sent-message history is queryable for later inspection
      Given the system has already sent one or more outreach messages
      When sent-message history is queried
      Then the system can show the linked contact
      And it can show the linked job posting when one exists
      And it can show the sent subject and body
      And it can show the send timestamp
      And it can show the latest known delivery outcome when available

    Scenario: Per-object traceability shows artifacts, transitions, and downstream history
      Given a `job_posting`, `contact`, or `outreach_message` exists in canonical state
      When that object's traceability view is queried
      Then the system can show linked artifacts for that object
      And it can show major recorded state transitions for that object
      And it can show the relevant downstream records connected to that object

    Scenario: Review surfaces are query-first rather than GUI-dependent
      Given the build is operating without a dedicated GUI
      When the owner reviews pipeline state
      Then queryable database views or filtered retrieval paths are sufficient to inspect the relevant cases
      And artifact references allow jumping from state to deeper inspection without manual directory spelunking

  @orchestration @system
  Rule: Current-build orchestration remains sequential

    Scenario: Discovery, drafting, sending, and delayed feedback do not require concurrency
      Given the build is executing the primary workflow
      When multiple eligible contacts exist for the same posting
      Then the system may process them one at a time in the defined outreach order
      And discovery does not require parallel fan-out
      And drafting does not require parallel fan-out
      And sending does not require parallel fan-out
      And delayed feedback sync does not require concurrent workers
      But per-message delivery feedback may still begin immediately after an individual send succeeds

    Scenario: Role-targeted orchestration follows the current dependency order
      Given a role-targeted posting is being processed in the build
      When the main pipeline runs
      Then the dependency order is LinkedIn Scraping, eligibility or tailoring, mandatory agent review, company-scoped contact search or contact linking or contact reuse, selected-contact enrichment, email discovery when still needed, batch drafting for the ready send set, sending, and delivery feedback
      And later stages do not proceed before their upstream prerequisites are satisfied

    Scenario: Posting remains requires-contacts until minimum outreach prerequisites exist
      Given a posting has completed tailoring
      And the mandatory agent review has approved that output
      And the posting does not yet have the required linked contacts and usable emails for the intended outreach set
      When posting-level state is evaluated
      Then the posting remains in `requires_contacts`
      And it does not advance to `ready_for_outreach` prematurely

    Scenario: Posting can move directly from agent review to ready-for-outreach when prerequisites already exist
      Given a posting has completed tailoring
      And the active tailoring run has been approved by the mandatory agent review
      And the required linked contacts already exist for the intended outreach set
      And the intended outreach set already has usable discovered email addresses
      When posting-level state is evaluated after agent review
      Then the posting may move directly from `resume_review_pending` to `ready_for_outreach`
      And no intermediate `requires_contacts` stop is required for that already-ready case

    Scenario: Posting becomes ready-for-outreach only when all minimum current prerequisites are satisfied
      Given a role-targeted posting is under build orchestration
      When posting readiness is evaluated
      Then `ready_for_outreach` requires completed tailoring
      And `ready_for_outreach` requires an agent-approved tailoring run
      And `ready_for_outreach` requires at least one actionable linked contact in the best currently available priority tier
      And `ready_for_outreach` requires usable discovered email addresses for the intended current outreach set

    Scenario: Role-targeted outreach uses the current recipient priority order with pacing-aware progression
      Given a posting has multiple linked contacts across recipient types
      When the build runs role-targeted outreach
      Then contacts are processed in this order when available: `recruiter`, `hiring_manager`, `engineer`, `alumni`, `other_internal`
      And sends may be delayed by pacing rules instead of blasting every recipient group immediately

    Scenario: Posting-contact linking is created before per-contact discovery or outreach begins
      Given a role-targeted posting has run broad company-scoped people search
      And a candidate has been shortlisted for outreach handling
      When the workflow prepares that shortlisted candidate for discovery or drafting
      Then a `job_posting_contacts` relationship is already present for that posting-contact pair
      And broad people search may have happened before that canonical link existed
      But person-scoped discovery or outreach does not begin first and create the link later as an afterthought

    Scenario: Link records become shortlisted when contacts enter the intended outreach set
      Given a contact has been identified for a posting
      When that contact is selected into the intended outreach set
      Then the posting-contact relationship transitions from `identified` to `shortlisted`
      And the link remains the canonical per-pair record for later discovery and outreach state

    Scenario: Known working email allows a contact to skip fresh discovery in orchestration
      Given a linked contact already has a clearly matched known working email
      When orchestration evaluates the next step for that contact
      Then the contact may move directly to `working_email_found`
      And fresh provider discovery is skipped for that contact in the current run
      And that contact counts as discovery-ready for the current send set
      But drafting or sending still waits for the full current send set to satisfy the remaining prerequisites

    Scenario: Prior outreach history blocks automatic repeat send during orchestration
      Given a linked contact already has prior outreach history
      When the current automatic role-targeted flow reaches that contact
      Then the system does not automatically send a new message to that contact
      And the contact is surfaced for user review instead
      And the broader posting flow may continue for other unrelated eligible contacts

    Scenario: Posting enters outreach-in-progress when the first intended contact starts drafting or sending
      Given a posting is `ready_for_outreach`
      When the first contact in the intended outreach set enters drafting or sending
      Then the posting transitions to `outreach_in_progress`
      And that transition does not require every contact in the outreach set to have started already

    Scenario: Contact and link records advance together once drafting or sending begins
      Given a linked contact has a usable working email for a role-targeted posting
      When drafting or sending begins for that posting-contact pair
      Then the contact advances to `outreach_in_progress`
      And the posting-contact relationship advances to `outreach_in_progress`
      And the related posting remains at least `outreach_in_progress`

    Scenario: Posting reaches completed when no untouched automatically eligible contacts remain
      Given a posting is currently `outreach_in_progress`
      When the remaining shortlisted contact pool has either been sent, exhausted, or excluded by repeat-contact rules
      Then the posting transitions to `completed`
      And bounced-message review items may still exist afterward
      But those review items do not block posting completion

    Scenario: Reply from one contact does not retroactively cancel the active outreach wave
      Given multiple contacts in the current selected outreach set are being processed in order
      And one contact replies while other contacts in the same active wave have already been sent or are proceeding
      When orchestration evaluates the remaining active-wave work
      Then that reply does not retroactively cancel outreach already issued in the same active wave
      And later-wave contacts already eligible under the current send order are not paused only because of that reply

    Scenario: Discovery, drafting, and feedback stages require both state persistence and handoff publication before downstream progression
      Given an upstream stage has completed its internal work for a posting or contact
      When orchestration decides whether the downstream stage may begin
      Then the upstream stage is treated as complete only if canonical state has been updated
      And any required machine handoff artifact for that boundary has been published
      And downstream progression remains blocked if either requirement is missing

    Scenario: Stage failure or blocked state prevents dependent downstream progression
      Given a stage becomes `blocked` or `failed` for a posting or contact
      When orchestration evaluates the next dependent stage
      Then downstream progression does not continue as if the upstream stage succeeded
      And the blocking or failure reason remains queryable for review

    Scenario: Contact exhaustion is local to that contact rather than a global posting stop
      Given discovery or outreach automation is exhausted for one contact
      When orchestration evaluates the remaining posting work
      Then that contact may move to `exhausted`
      And the posting does not fail globally only because of that one exhausted contact
      And other eligible contacts may still continue under the current posting flow

    Scenario: The user may explicitly abandon a posting from any active orchestration state
      Given a posting is in a non-terminal active state
      When the user explicitly decides to stop pursuing that posting
      Then the posting may transition to `abandoned`
      And the abandoned state is reflected in canonical posting status

    Scenario: General learning outreach bypasses the role-targeted agent-review requirement
      Given outreach is contact-rooted and not tied to a specific job posting
      When the build runs that general learning outreach flow
      Then the flow does not require posting-specific resume tailoring
      And the flow does not require the role-targeted agent-review requirement before drafting or sending

    Scenario: Discovery can start per contact but drafting or sending waits for the ready send set
      Given a posting has multiple linked contacts
      When one contact becomes linked and has enough local prerequisites to proceed
      Then discovery may begin for that contact without waiting for the full contact set
      But drafting or sending does not begin for that contact alone
      And drafting or sending waits until the current send set is fully ready under the active orchestration rules

    Scenario: One contact failure does not stop unrelated contacts in the same posting flow
      Given multiple contacts are being processed for the same posting
      When discovery, drafting, or sending fails for one contact
      Then unrelated eligible contacts may still continue through the workflow
      And the failed contact remains available for review or retry handling

    Scenario: Current build does not automatically expand contact search after the selected set is sent
      Given the current selected outreach set for a posting has been sent
      When no explicit user request for more contact expansion has been made
      Then the system does not automatically go back and discover additional contacts for that posting

  @linkedin_scraping
  Rule: LinkedIn Scraping acceptance

    Scenario: New leads receive stable lead identity and canonical lead workspaces
      Given a new upstream lead is ingested through `LinkedIn Scraping`
      When canonical lead state is materialized
      Then the lead receives a stable `lead_id`
      And the canonical lead workspace is rooted at `linkedin-scraping/runtime/leads/<company>/<role>/<lead_id>/`

    Scenario: Autonomous Gmail collection persists one collected-email unit before fan-out and remains idempotent by message id
      Given an agent-invoked Gmail ingestion run sees a LinkedIn job-alert email
      When that email is collected
      Then the collected email is first persisted under `linkedin-scraping/runtime/gmail/{YYYYMMDDTHHMMSSZ}-{gmail_message_id}/...`
      And job-card fan-out into per-lead workspaces happens only after that collected-email unit exists
      When the same `gmail_message_id` is encountered again later
      Then the duplicate email is ignored instead of overwriting or creating another collected-email unit

    Scenario: Gmail thread membership does not suppress collection or parsing
      Given multiple LinkedIn job-alert emails belong to the same `gmail_thread_id`
      When Gmail ingestion runs
      Then each message is still collected independently
      And thread membership alone does not suppress job-card parsing for any of those messages

    Scenario: Zero-card Gmail collections are retained and reviewed only after the configured threshold
      Given a collected Gmail message yields zero parseable job cards
      When the collection result is persisted
      Then the collected email artifacts are retained
      And `job-cards.json` may be empty
      And no lead workspace is created from that message
      And review is triggered only when more than 3 such emails occur in one Gmail ingestion run or when the cumulative unresolved count exceeds 3 across history

    Scenario: Gmail-derived lead workspaces start incomplete and become blocked-no-jd when JD recovery fails
      Given a parsed Gmail alert card survives validation and deduplication
      When the autonomous lead workspace is created
      Then that workspace is created immediately for the parsed card
      And the new workspace starts in `incomplete`
      When JD recovery later fails for that lead
      Then the autonomous lead workspace transitions to `blocked_no_jd`

    Scenario: Lead workspace artifacts differ by lead mode and blocked manifests still exist
      Given one lead was ingested from manual capture and another from autonomous Gmail intake
      When their lead workspaces are inspected
      Then every lead workspace contains `lead-manifest.yaml` plus the artifacts required by that lead mode
      And manual-capture leads contain `raw/source.md`, `source-split.yaml`, and `source-split-review.yaml`
      And autonomous Gmail-derived leads are not required to contain `raw/source.md`, `source-split.yaml`, or `source-split-review.yaml` by default
      And `lead-manifest.yaml` still exists even when the lead is blocked by ambiguous split review

    Scenario: Autonomous Gmail job-card deduplication prefers job id and falls back to normalized LinkedIn job URL
      Given an autonomous parsed alert card resolves to a LinkedIn `job_id` already seen for an existing autonomous lead
      When lead creation is evaluated
      Then a second lead is not created
      Given a parsed alert card lacks a usable LinkedIn `job_id`
      And a usable LinkedIn job URL is available
      When fallback identity is materialized
      Then a synthetic fallback identity key is created from the normalized LinkedIn job URL
      And the lead may still be created from that fallback identity

    Scenario: Missing both job id and job URL blocks the autonomous lead only when no JD can be recovered
      Given a parsed autonomous alert card lacks both a usable LinkedIn `job_id` and a usable LinkedIn job URL
      When no usable JD can be recovered from any supported source
      Then the lead transitions to `blocked_no_jd`

    Scenario: Multiple JD sources merge into canonical jd.md while LinkedIn wins conflicts
      Given an autonomous lead has JD candidate content from LinkedIn and a company-hosted source
      When canonical JD persistence is produced
      Then non-conflicting additional information is merged into `jd.md`
      And materially conflicting portions prefer LinkedIn-derived JD content
      And provenance still records the contributing sources

    Scenario: Company-role mismatch from Gmail card versus fetched JD is reviewed while minor normalization differences are tolerated
      Given the parsed Gmail alert-card company or role title materially disagrees with the fetched LinkedIn JD identity
      When autonomous lead review evaluates the mismatch
      Then the lead is surfaced for user review
      And downstream canonical company or role materialization remains blocked until resolved
      But minor normalization differences such as `Google` versus `Google LLC` or `SWE II` versus `Software Engineer II` do not by themselves trigger review

    Scenario: Source metadata is owned by the lead and downstreams use lead-manifest artifact references
      Given a lead has been ingested and normalized
      When source metadata and downstream inputs are inspected
      Then source metadata such as `source_type`, `source_reference`, `source_url`, `source_mode`, and source-mode-specific provenance is source-of-truth on the lead entity
      And downstream components consume artifact references from `lead-manifest.yaml` rather than relying on hardcoded upstream directory assumptions

    Scenario: Refreshing an existing lead updates the live workspace while preserving history snapshots
      Given an existing lead is refreshed with newer source or review state
      When the lead workspace is updated
      Then the live lead workspace is updated in place
      And older source or review snapshots remain preserved in lead-local history artifacts

  @end_to_end
  Rule: End-to-end acceptance

    Scenario: Role-targeted flow completes from LinkedIn Scraping through delivery feedback
      Given a role-targeted lead entered through manual browser capture or autonomous Gmail job-alert intake
      And the required secrets, assets, and environment prerequisites are all available
      When the build runs the primary role-targeted flow
      Then the flow progresses through LinkedIn Scraping, tailoring, mandatory agent review, company-scoped contact search, shortlist-time contact materialization, selected-contact enrichment, email discovery when needed, batch drafting for the ready send set, sending, and delivery feedback
      And intermediate machine artifacts are persisted at each stage boundary
      And canonical state remains queryable throughout the flow

    Scenario: Delayed bounce after the send session still gets captured
      Given an outreach message was sent and the interactive send session has already ended
      When a bounce email arrives later within the configured observation window
      Then delayed feedback sync can still detect the bounce from mailbox observation
      And the bounced event is written back into canonical state

    Scenario: End-to-end retry resumes from the last successful stage boundary
      Given a build workflow has successfully completed some earlier stages
      And a later stage fails or is blocked
      When the workflow is retried
      Then the system resumes from the last successful stage boundary rather than restarting from LinkedIn Scraping
      And previously successful stages do not need to be recomputed unless the user explicitly resets them

    Scenario: Two-step outreach is excluded from required acceptance
      Given the build is evaluated against this acceptance spec
      When current-build acceptance scope is determined
      Then one-step role-targeted outreach is in scope
      And general learning outreach is in scope
      But the detailed two-step outreach flow is not required for this acceptance target

  @safety @privacy @system
  Rule: Current-build safety, privacy, and evidence-grounding boundaries

    Scenario: Tailoring and outreach remain grounded in truthful stored evidence
      Given the system is tailoring a resume or drafting outreach
      When it uses candidate and recipient context
      Then it relies on stored job context, master-profile evidence, tailored resume context, and recipient-profile context
      And it does not invent qualifications, fake relationships, or unsupported facts

    Scenario: Persisted review surfaces expose only workflow-relevant personal data
      Given the system stores contact and outreach information for the build
      When review surfaces are generated
      Then they expose the contact or context details needed for workflow decisions
      And they avoid unnecessarily broad personal-data copies beyond that workflow need

    Scenario: Autonomous outreach stays within the current safety boundary
      Given the build is running autonomous draft or send behavior
      When it decides whether outreach may proceed automatically
      Then role-targeted flow still requires successful mandatory agent review before outreach begins
      And repeat-contact ambiguity still routes to review
      And evidence-grounding rules still apply to the resulting message
