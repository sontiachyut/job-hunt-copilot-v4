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
      Then the database contains `leads`
      And the database contains `lead_source_observations`
      And the database contains `job_postings`
      And the database contains `contacts`
      And the database contains `lead_contacts`
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
      And the database contains `llm_usage_events`
      And the database contains `discovery_attempts`
      And the database contains `outreach_messages`
      And the database contains `outreach_followup_plans`
      And the database contains `followup_cycle_runs`
      And the database contains `delivery_feedback_events`
      And the database contains `contact_provider_profiles`
      And the database contains `contact_employment_history`
      And the database contains `job_posting_provider_contexts`

    Scenario: Build input pack is sufficient for a fresh build
      Given the build input pack contains `spec.md`
      And the build input pack contains `runtime_secrets.json`
      And the build input pack contains `assets/`
      When a fresh build implementation is bootstrapped
      Then the build can use `assets/resume-tailoring/profile.md` as master-profile input
      And the build can use the single bundled base resume track under `assets/resume-tailoring/base/`
      And the build can use `assets/outreach/cold-outreach-guide.md` as the outreach guide
      And no additional personal-context files are required to start the build

    Scenario: Fresh build can materialize lead-ingestion runtime roots
      Given a fresh build implementation is bootstrapped
      When the first authenticated Jobright ingestion run is prepared
      Then runtime-support directories under `lead-ingestion/runtime/jobright/` can be created locally
      And canonical lead workspaces under `lead-ingestion/runtime/leads/` can be created locally
      And the build does not require the retired paste-inbox workflow to begin lead ingestion

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

    Scenario: Resume Tailoring input boundary is centered on `jd.md` rather than any raw upstream dump
      Given `Lead Ingestion` has produced `jd.md` and the available lead artifacts for a lead
      When Resume Tailoring begins for that posting
      Then the core tailoring logic consumes the derived `jd.md` plus posting-level canonical state
      And the build does not require direct reading of any raw upstream source dump to run Tailoring
      And additional upstream artifacts may exist for traceability without being mandatory inputs to the core tailoring decision path

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
      Then `leads` includes a stable `lead_id`
      And `leads` includes promotion state plus the latest refreshable Jobright fit and connection metadata
      And `lead_source_observations` includes persisted Jobright recommendation and job-page observations
      And `job_postings` includes a stable `job_posting_id`
      And `job_postings` includes `lead_id`
      And `job_postings` includes a normalized posting identity key
      And `job_postings` includes company name, role title, and posting status
      And `contacts` includes a stable `contact_id`
      And `contacts` includes an `identity_key`
      And `contacts` includes `origin_component`
      And `contacts` includes full name, company name, contact status, and current working email when known
      And `lead_contacts` includes source-contact lineage and intended-set priority metadata
      And all primary entity tables include lifecycle timestamps

    Scenario: Lead and job posting follow forward-only lifecycle progression
      Given a role-targeted lead enters the pipeline
      When it progresses through the normal next-build flow
      Then the lead moves forward through discovery-oriented upstream states such as `discovered`, `held`, or `promoted` when eligible
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
      Then `leads` and `lead_source_observations` store the authoritative source metadata for that lead
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

    Scenario: Jobright-seeded contacts create lead-contact and posting-contact traceability
      Given a non-ambiguous Jobright lead contains one or more source-seeded contacts
      And a canonical `job_posting` has been created for that lead
      When canonical entities are materialized
      Then canonical `contacts` are created or reused for those source-seeded people
      And `lead_contacts` rows link those contacts back to the `lead`
      And `job_posting_contacts` rows link those contacts to the `job_posting`

    Scenario: Personalized Jobright connections are treated as first-class source contacts
      Given a Jobright observation contains personalized school or company connections
      When source contacts are materialized from that lead
      Then those contacts remain queryable through `lead_contacts`
      And their source type and priority metadata remain distinguishable from public Jobright connections and Apollo-shortlisted contacts

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

    Scenario: Authenticated Jobright recommendation ingestion persists feed and job-page evidence
      Given an authenticated Jobright recommendation batch contains one or more candidate roles
      When the autonomous lead-ingestion path runs
      Then recommendation-feed evidence is persisted under `lead-ingestion/runtime/jobright/{run_id}/`
      And job-page enrichment evidence is persisted for each observed Jobright job
      And a canonical lead workspace is created for each deduplicated lead that has enough identity to materialize

    Scenario: Canonical lead workspaces and artifacts follow the lead-ingestion layout
      Given a deduplicated Jobright lead has been materialized
      When the lead workspace is inspected
      Then upstream lead artifacts live under `lead-ingestion/runtime/leads/<company>/<role>/<lead_id>/`
      And that workspace contains `lead-manifest.yaml`
      And that workspace contains `source-observations.json`
      And that workspace contains `source-contacts.json`
      And promoted leads also persist `promotion-decision.json`, `jd.md`, and `jd-provenance.json`

    Scenario: Jobright recommendation-feed and job-page observations converge into one canonical lead
      Given the same Jobright role appears in both a recommendation-feed snapshot and a job-page enrichment snapshot
      When canonical lead state is materialized
      Then one canonical `lead_id` is reused
      And separate `lead_source_observations` rows preserve the feed-level and job-page-level evidence
      And downstream work is not duplicated merely because multiple upstream observations exist

    Scenario: Jobright observations refresh an existing discovery lead instead of duplicating it
      Given an unpromoted Jobright lead already exists in discovery
      When a later authenticated Jobright run sees that same lead again
      Then the canonical discovery lead is refreshed to the latest score, connection, freshness, and related upstream metadata
      And a new canonical lead is not created for that same job identity

    Scenario: Jobright session expiry records a recoverable reauth-required state
      Given Jobright ingestion depends on an authenticated browser-backed session
      When that session is expired or unavailable during a lead-ingestion run
      Then canonical lead state records `reauth_required`
      And no corrupted promoted posting is created from that failed ingestion cycle
      And already-promoted postings remain eligible to continue downstream tailoring, contact enrichment, drafting, and outreach

    Scenario: Jobright job-page JD is persisted fully before downstream structuring
      Given a Jobright observation yields a usable JD
      When the downstream lead workspace is materialized
      Then the full recovered JD text is persisted into `jd.md`
      And later eligibility or tailoring artifacts read from that persisted markdown
      And the build does not require direct reuse of only a transient network response payload

    Scenario: Structured Jobright sections count toward usable JD recovery
      Given a Jobright page exposes responsibilities, qualifications, or benefits as structured sections rather than one long free-text description
      When Jobright JD recovery assembles the canonical `jd.md`
      Then those structured sections are included in the persisted JD markdown
      And the JD usability gate evaluates the assembled structured content rather than only one narrow text field

    Scenario: Missing usable Jobright JD blocks promotion while preserving the discovery lead
      Given a Jobright observation does not yield a full usable JD
      When promotion eligibility is evaluated
      Then the lead remains in discovery or another upstream held state
      And a canonical `job_posting` is not auto-created from that lead
      And the source observations still remain queryable for later review or refresh

    Scenario: Jobright public and personalized connections are persisted as source-seeded contacts
      Given a Jobright lead yields public connections and personalized school or company connections
      When source contacts are materialized
      Then canonical contacts are created or reused for those people
      And `lead_contacts` preserves whether each one came from `jobright_public`, `jobright_personal_school`, or `jobright_personal_company`
      And the lead-contact records preserve the intended-set priority order needed by downstream outreach

    Scenario: Component-oriented layout keeps runtime artifacts under the owning component folders
      Given a role-targeted lead has progressed through lead intake, tailoring, discovery, and drafting boundaries
      When the resulting filesystem artifacts are inspected
      Then upstream lead artifacts live under `lead-ingestion/runtime/leads/<company>/<role>/<lead_id>/`
      And posting manifests live under `applications/<company>/<role>/`
      And tailoring workspace artifacts live under `resume-tailoring/output/tailored/<company>/<role>/`
      And discovery runtime outputs live under `discovery/output/<company>/<role>/`
      And outreach runtime outputs live under `outreach/output/<company>/<role>/`

    Scenario: Held or blocked upstream leads still publish a blocked manifest
      Given a lead remains held, blocked, or waiting on reauthentication in upstream lead ingestion
      When the lead workspace is finalized
      Then `lead-manifest.yaml` still exists for that lead
      And the lead is marked not ready for downstream handoff
      And no downstream target is marked ready without a promotable upstream state

    Scenario: Source-observation history remains preserved after discovery refreshes
      Given a Jobright lead has been refreshed by later recommendation or job-page observations
      When the lead workspace history is inspected
      Then older source observations remain preserved in history artifacts
      And the latest live workspace state still points to the active refreshed source observation

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

    Scenario: Cross-posting unsent outreach history does not block a new role-targeted send
      Given a contact has older unsent generated, blocked, or failed role-targeted outreach rows from other postings
      And the current posting has a fresh role-targeted draft for that same contact
      When automatic sending evaluates duplicate-send ambiguity for the current posting
      Then those older unsent rows from other postings do not by themselves create `ambiguous_send_state`
      And prior successful sent history may still trigger repeat-outreach review

    Scenario: Transient Gmail send failures are blocked and retried later
      Given a role-targeted automatic send hits a clearly transient Gmail auth or transport failure
      When the system persists that send outcome
      Then it marks that same message `blocked` instead of terminal `failed`
      And it keeps the posting `outreach_in_progress`
      And it keeps the durable run at `sending`
      And it stops the rest of the current posting wave immediately

    Scenario: A stale sending run falls back to discovery when the next frontier still needs emails
      Given a role-targeted posting is still marked `ready_for_outreach`
      And its durable run is at `sending`
      And reevaluating the next selected frontier finds no draftable ready contacts because those contacts still need usable emails
      When the supervisor executes that sending work
      Then it does not call drafting for that stale send frontier
      And it persists the posting back to `requires_contacts`
      And it moves the durable run back to `email_discovery`

    Scenario: Transient send retries wait for cooldown and stay bounded
      Given a role-targeted message is `blocked` because of a transient Gmail auth or transport failure
      When less than 15 minutes have passed since the latest blocked attempt
      Then the supervisor does not treat that sending run as currently runnable
      When the cooldown expires
      Then the supervisor may retry that same message
      And after 3 automatic retries are exhausted the message remains `blocked` and reviewable rather than becoming terminal `failed`

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
      And the manager-expansion harvest runs as a broad multi-pass current-company manager, technical-CxO, and founder-title search without location restriction
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

    Scenario: Apollo company resolution is persisted as posting-scoped provider context
      Given Apollo resolves company identity for a role-targeted posting
      When the resolved company context is persisted
      Then `job_posting_provider_contexts` stores that raw Apollo company-resolution payload for the `job_posting_id`
      And newer company-resolution payloads append newer provider-context rows rather than overwriting older raw snapshots

    Scenario: Adaptive manager-expansion shortlist scales with the eligible Apollo manager pool
      Given a broad Apollo people search has returned many candidate contacts for a posting
      When the build chooses the first manager-expansion wave
      Then the Apollo manager-expansion shortlist keeps all eligible manager/executive contacts when the eligible pool is 5 or fewer
      And it keeps up to 7 when the eligible pool is 6 to 10
      And it keeps up to 10 when the eligible pool is 11 or more
      And that shortlist prefers engineering managers first
      And in very small startup-style pools it raises founder-style executive routing above director/head/vp engineering leadership and above relevant technical CxO roles, even when the founder title is plain
      And in larger pools it keeps founder-style executive routing below director/head/vp engineering leadership and relevant technical CxO roles
      And plain CEO fallback contacts are searched but rank below founder-style executive routing and relevant technical CxO roles
      And lead-engineer variants remain below technical CxO in this manager-expansion lane
      And within the same priority bucket it prefers contacts that already have a usable work email
      And that priority order does not flip merely because the company appears larger
      And broad-search candidates outside that shortlist are not enriched by default

    Scenario: Shortlisted Apollo contacts persist full person snapshots and structured employment history
      Given a broad Apollo people search has yielded a shortlisted candidate for a posting
      And Apollo search or enrichment returns person payload for that shortlisted candidate
      When that candidate is materialized into canonical contact state
      Then `contact_provider_profiles` stores the full Apollo person payload for that contact
      And `contact_employment_history` stores any returned employment-history items as structured rows linked to the same `contact_id`
      And downstream drafting may query that stored Apollo context without reparsing only the raw provider artifact

    Scenario: Newer Apollo person payloads refresh latest employment history while preserving raw snapshot history
      Given a canonical contact already has one persisted Apollo person snapshot and structured Apollo employment history
      When a newer Apollo search or enrichment payload is persisted for that same contact
      Then `contact_provider_profiles` preserves both raw Apollo snapshots as append-only history
      And the contact's current structured Apollo employment history is refreshed to match the newest Apollo payload
      And stale duplicate employment-history rows do not accumulate indefinitely

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

    Scenario: Discovery reuses the saved resolved company domain before weaker derivation
      Given people search already persisted a resolved company record with `primary_domain` in `people_search_result.json`
      And person-scoped Email Discovery is running for a shortlisted contact from that posting
      When the posting source URL does not itself provide a usable company domain
      Then Email Discovery reuses the saved `primary_domain` for provider calls that need a company domain

    Scenario: Discovery still calls providers that can operate without company_domain
      Given person-scoped Email Discovery has no usable `company_domain`
      And a provider supports the available contact input through `linkedin_url` or company-name context
      When Email Discovery runs the provider cascade
      Then the provider is still called instead of being pre-skipped by the outer discovery loop

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

    Scenario: Role-targeted drafting chooses the current technical or managerial path by recipient type
      Given a job posting is ready for role-targeted outreach
      And a linked contact has a usable email
      When Email Drafting and Sending chooses the current role-split playbook for that contact
      Then technical individual contributors may use the technical path
      And managers, recruiters, and routing-side contacts may use the managerial path
      And the chosen path is recoverable from draft artifacts or review evidence

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

    Scenario: Scheduled role-targeted drafting resolves Codex outside the scheduler PATH
      Given the launchd environment does not expose the full interactive shell PATH
      And the local machine still has a valid `codex` binary in a deterministic install location
      When scheduled role-targeted drafting enters the send stage
      Then the drafter still resolves the `codex` executable successfully
      And the scheduler does not crash only because `codex` was absent from the ambient PATH
      And the drafter also supplies a runtime PATH that can resolve the local `node` launcher dependency when `codex` is a Node-based script

    Scenario: Sender signature keeps the public GitHub profile URL
      Given the sender master profile contains a personal GitHub profile URL in `Personal`
      And later project sections also contain project-specific `GitHub` bullets
      When role-targeted drafting loads the sender signature
      Then the signature uses the personal GitHub profile URL
      And the signature does not substitute a project repository URL or local filesystem path

    Scenario: Technical role-split payload drift is normalized before persistence
      Given the technical drafter returns a truthful opener that still drifts on debug scaffolding
      And the payload leaves `selected_career_steps` empty or returns more than two opener sentences
      When deterministic runtime validates the technical role-split payload
      Then runtime infers at least one supported career-step company from bounded employment history
      And runtime restores the exact two-sentence opener shape before the draft is persisted

    Scenario: Managerial debug lists are truncated instead of failing the draft
      Given the managerial drafter returns a valid email body payload
      But the managerial debug signal lists contain more than three items
      When deterministic runtime validates the managerial role-split payload
      Then runtime truncates those debug lists to the first three non-empty items
      And the draft is not failed solely because of oversized debug lists

    Scenario: Later postings at the same company proactively skip an already-contacted person
      Given one posting at a company has already sent automatic outreach to a canonical contact
      And a later posting at that same company links that same canonical contact plus other eligible company contacts
      When orchestration evaluates the later posting for automatic outreach
      Then the already-contacted canonical contact is excluded from automatic send-set selection for the later posting
      And orchestration continues with alternate eligible contacts from that company when they exist

    Scenario: Same-company exclusion begins only after an actual send
      Given one posting at a company has only generated or in-progress drafts for a canonical contact
      And no successful automatic send has yet occurred for that contact
      When a later posting at that same company evaluates that same canonical contact
      Then the contact is not excluded solely because of the earlier draft state

    Scenario: Later postings with no alternate same-company contacts do not auto-send a second email
      Given one posting at a company has already sent automatic outreach to a canonical contact
      And a later posting at that same company has no alternate automatically eligible contacts left after exclusions
      When orchestration evaluates the later posting for automatic outreach
      Then the system does not auto-send a second role-targeted email to that same canonical contact
      And the later posting is surfaced for review instead

    Scenario: Current autonomous active send slice prefers manager-heavy coverage without a global daily cap
      Given a posting has enough viable contacts across multiple recipient classes
      When the build forms the current autonomous active send slice for that posting
      Then the default active send slice prefers up to four manager-class contacts first and only then uses team-adjacent engineers for any remaining slots
      And the per-posting daily automatic send cap is 4 in the current build
      And recruiters and generic non-technical internal contacts are not auto-selected into that default active send slice
      And recruiter or talent contacts remain available only as manual-review fallback when stronger automatic contacts are unavailable or exhausted
      And the current build does not impose a separate global cross-company daily send cap

    Scenario: Quota-blocked sending work yields to other runnable supervisor work
      Given one posting is waiting only on its next allowed automatic send slot
      And other runnable supervisor work exists
      When the supervisor selects the next work item
      Then the delayed-only sending run yields
      And the supervisor may advance the other runnable work instead

    Scenario: Role-targeted one-step outreach uses personalization, overlap, and a low-friction ask
      Given a job posting is ready for outreach and a linked contact has usable profile context
      When Email Drafting and Sending creates a role-targeted draft
      Then the draft uses one-step direct outreach rather than the deferred two-step flow
      And the opening uses role, team, or work-area context rather than a generic self-introduction
      And the draft includes a grounded reason for reaching out to that specific recipient
      And the body shows visible overlap between the role and the sender's relevant background
      And the draft ends with a low-friction next step rather than a heavy ask

    Scenario: Drafting can begin as individual contacts become ready across the posting frontier
      Given multiple untouched contacts belong to the same posting
      And at least one contact becomes ready earlier than the others
      When orchestration evaluates whether drafting may begin
      Then drafting may begin for that ready contact without waiting for one fixed send set to become fully ready
      And automatic sending for that posting still remains subject to the active send-slice and pacing rules

    Scenario: The ready posting frontier is drafted before automatic sending consumes it
      Given one or more untouched contacts are currently ready for role-targeted outreach on a posting
      When Email Drafting and Sending prepares that posting frontier
      Then the system first generates and persists drafts for the currently ready untouched contacts
      And automatic sending consumes those drafts later through the active send-slice and pacing rules

    Scenario: Failed drafts do not block sending for successfully drafted contacts in the same posting frontier
      Given the current ready posting frontier contains multiple contacts
      And draft generation fails for one contact in that frontier
      When draft generation for the ready posting frontier completes
      Then successfully generated drafts from that same frontier may still proceed into sending
      And the failed draft case is surfaced for review

    Scenario: Managerial-path outreach uses the fixed concise 10-minute CTA
      Given the recipient type is recruiter, manager, or another routing-side role-targeted target
      When a managerial-path outreach draft is generated
      Then the CTA uses the fixed brief 10-minute conversation ask
      And the draft asks to better understand the team's real challenges
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
      And a draft-debug artifact is available for role-split drafts
      And `send_result.json` includes the shared contract envelope and relevant stable IDs

    Scenario: Technical-path draft is codex-generated only for the opener and reads Apollo history DB-first
      Given a role-targeted technical-path draft is being created for a linked contact
      And structured Apollo employment history exists for that contact in canonical state
      When Email Drafting and Sending renders the technical-path body
      Then `codex exec` generates only Technical Paragraph 1 plus debug fields
      And deterministic rendering appends the fixed later paragraphs and standard signature
      And the draft reads Apollo employment history from the structured database-backed provider store before falling back to artifact reparsing
      And the subject is `Learning from your career path`
      And the opener says `admired your path` rather than `really admired your path`
      And the opener does not emit placeholder ellipses or awkward same-company tenure phrasing
      And the fixed Job Hunt Copilot paragraph does not use a standalone `repo is here` sentence
      And the fixed Job Hunt Copilot paragraph does not describe the email itself as a live autonomous-workflow example
      And the fixed technical guidance ask does not list explicit weekday availability windows
      And the fixed technical guidance ask asks for guidance on how the recipient approached the work or what to focus on at the sender's stage
      And the technical-path body does not mention an attached resume
      And the technical-path send artifact does not attach the resume file
      And the assembled technical-path body stays within the current reduced technical word target
      And HTML rendering hyperlinks the `Job Hunt Copilot` label itself in that paragraph

    Scenario: Live role-split codex calls persist token usage events
      Given a live role-targeted role-split drafting call invokes `codex exec`
      When the subprocess completes and writes its stderr usage footer
      Then the system persists one `llm_usage_events` row for that call
      And the row records invocation success or failure plus the exit code
      And the row records the total token count when stderr reports it
      And the row still exists with an explicit missing-usage status when stderr omits token usage

    Scenario: Managerial-path draft uses fixed deterministic structure around codex-generated reasoning
      Given a role-targeted managerial-path draft is being created for a linked contact
      When Email Drafting and Sending renders the managerial-path body
      Then deterministic rendering emits the greeting and fixed `I hope you're doing well.` opener sentence
      And `codex exec` generates the role-alignment sentence, exactly 3 JD-challenge bullets, exactly 3 relevant-background bullets, and debug fields
      And deterministic rendering emits the fixed bold proof-of-concept sentence
      And the plain-text body does not contain raw Markdown strong markers around that proof-of-concept sentence
      And the HTML body renders that proof-of-concept sentence with strong emphasis
      And deterministic rendering emits the fixed CTA block and standard signature
      And the fixed JD heading is phrased as a question rather than a statement
      And the fixed CTA block mentions the proof-of-concept offer only once in the whole email body
      And the JD-challenge bullets are JD-only inferred problem hypotheses rather than verbatim JD paste
      And the relevant-background bullets come from real resume or project evidence
      And a `Job Hunt Copilot` background bullet appears only when it materially strengthens the dominant role-fit theme
      And the subject follows `Interest in the <Role Title> role at <Company>`

    Scenario: Managerial-path subject strips role-title formatting artifacts before send
      Given a role-targeted managerial-path draft is being created for a posting whose canonical role title contains a leading formatting artifact like `#`
      When Email Drafting and Sending renders the managerial-path subject
      Then the subject still follows `Interest in the <Role Title> role at <Company>`
      And the rendered subject does not contain the raw leading formatting artifact

    Scenario: Role-targeted original drafts fail closed on deterministic lint defects
      Given a role-targeted original draft has been assembled into final subject, plain-text body, and HTML body
      When the deterministic original-draft lint gate runs before persistence or refresh
      Then raw Markdown emphasis leakage in plain text blocks the draft
      And disallowed control characters block the draft
      And banned technical-path autonomy or scheduling phrases block the draft
      And major word-budget overshoot blocks the draft
      And a clean draft passes without further mutation

    Scenario: Managerial-path posting link is rendered deterministically from canonical state
      Given a managerial-path draft is being created for a concrete job posting
      And a public posting URL is available in canonical state
      When the body is rendered
      Then the email includes one standalone `Posting link:` line
      And that line appears immediately after the fixed bold proof-of-concept sentence
      And the line uses the canonical public posting URL rather than model-generated URL text

    Scenario: Generated send-ready work outranks new draft generation and Jobright polling
      Given one role-targeted `sending` run has an already-generated send frontier actionable now
      And another role-targeted `sending` run is actionable only for fresh draft generation
      And routine Jobright recommendation polling is also due
      When the supervisor selects the next work unit
      Then it chooses the generated send-ready `sending` run first
      And it does not choose the Jobright recommendation batch for that heartbeat
      And the generated-frontier-only pre-pass does not fall through to unrelated pipeline work when no generated frontier exists

    Scenario: Managerial-path bullets render as real lists in HTML
      Given a managerial-path draft contains exactly 3 JD-challenge bullets and exactly 3 relevant-background bullets
      When the draft is rendered to HTML for Gmail delivery
      Then each section is rendered as a list rather than a flattened paragraph
      And each bullet remains visually separate under its heading

    Scenario: Role-split codex outputs are schema-validated before the draft is accepted
      Given a role-split draft is generated through `codex exec`
      When the structured output contract is inspected
      Then the provider-facing JSON schema marks every top-level output field as required
      And the draft is rejected if runtime validation fails
      And accepted draft-debug artifacts record the selected JD, career-step, or sender-evidence signals actually used in the draft

    Scenario: Role-targeted original drafting does not fall back to the old deterministic template
      Given a scheduled or autonomous role-targeted original draft hits a Codex runtime drafting error
      When Email Drafting and Sending handles that failure
      Then it fails closed instead of rendering the legacy deterministic role-targeted body
      And it does not emit the old `Agentic AI skills` / `live example of that workflow` copy
      And the failed draft is not labeled as `codex_role_split`

  @followups
  Rule: Automated Follow-Up Worker behavior

    Scenario: Follow-up candidates are selected from sent role-targeted emails, not postings
      Given multiple `role_targeted` outreach messages have been sent
      And some of those messages are more than 4 calendar days old in `America/Phoenix`
      When the follow-up worker evaluates candidates
      Then it starts from sent `outreach_messages` rather than job postings
      And it considers only original sent `role_targeted` messages as follow-up roots
      And it excludes `general_learning`, `manual_reply`, `follow_up`, and `role_targeted_followup` messages as new follow-up roots
      And it processes due candidates oldest original sent email first
      And it does not render follow-up draft bodies before the 4-calendar-day eligibility threshold

    Scenario: Follow-up rendering uses the strict approved template
      Given an eligible unreplied original `role_targeted` outreach message exists
      And the original email body, role, company, recipient salutation, and grounding evidence are available
      When the follow-up worker renders the follow-up draft
      Then the body matches the approved warmer mutual-fit template shape
      And the only filled fields are first name or preserved salutation, role title, company name, and `background_fit_areas`
      And `background_fit_areas` contains 2 to 3 concise role-specific noun phrases grounded in allowed evidence
      And the draft uses the short signature only
      And the draft does not include attachments, quoted original content, full contact signature, retired terse JD-theme wording, internal artifact text, or metric-heavy proof paragraphs
      And a generic ungrounded background phrase blocks or escalates the candidate rather than being sent

    Scenario: Reply, bounce, and duplicate-follow-up guards suppress automatic follow-ups
      Given an original sent `role_targeted` outreach message is due for follow-up
      When the follow-up worker checks the original Gmail thread and canonical feedback state
      Then a bounce tied to the original message, recipient, delivery tracking ID, or thread suppresses the follow-up
      And any inbound reply in the same Gmail thread after the original `sent_at` suppresses the follow-up
      And a later outbound message from the sender in the same Gmail thread suppresses the follow-up as already followed up
      And existing `follow_up` or `role_targeted_followup` evidence suppresses another automatic follow-up for the same original thread
      And unknown reply state does not permit automatic sending

    Scenario: Follow-up send uses persisted same-thread content and immutable original outreach
      Given an eligible follow-up has passed internal follow-up review gates
      And the immediately-before-send Gmail-thread recheck still shows no reply, bounce, or later outbound follow-up
      When automatic follow-up sending is enabled and the shared pacing queue permits a send
      Then the worker sends a reply in the original Gmail thread rather than a new standalone email
      And it preserves the original recipient envelope from the first sent email
      And it sends the exact persisted follow-up draft body rather than regenerating text at send time
      And it records a separate `role_targeted_followup` outreach message linked to the original
      And it does not mutate the original `role_targeted` outreach message body, mode, sent timestamp, or delivery identity

    Scenario: Dry-run validates follow-up behavior without sending or sent-state mutation
      Given due follow-up candidates exist
      When the follow-up worker runs in dry-run mode
      Then it evaluates a bounded batch of 25 candidates ordered oldest original sent email first
      And it may create or refresh `outreach_followup_plans` rows and dry-run artifacts with clear dry-run markers
      And it renders and persists the actual draft text and agent-review evidence for would-send candidates
      And it performs only read-only Gmail checks
      And it does not call Gmail send APIs
      And it does not set `sent_at`, `message_status = sent`, `plan_status = sent`, or successful send-result state

    Scenario: Follow-up worker records plans, cycle audits, and reviewable failures
      Given the follow-up worker runs a scheduled or manual cycle
      When the cycle completes with sends, skips, pacing waits, retryable failures, or no-op results
      Then a `followup_cycle_runs` audit row is written for that invocation
      And one `outreach_followup_plans` row represents one allowed follow-up opportunity for one original sent outreach message
      And uniqueness on `original_outreach_message_id` plus `followup_sequence` prevents duplicate first-follow-up plans
      And structural same-thread failures or ambiguous may-have-sent states create blocked or reviewable follow-up state
      And real-mode blocked, ambiguous, failed, or escalated cases include enough review-packet context to inspect the original email, draft if present, thread evidence, bounce evidence, grounding evidence, and recommended owner action

    Scenario: Follow-up auto-send rollout is gated and paced
      Given the follow-up worker is deployed for the first time
      When runtime control state is inspected
      Then automatic follow-up sending is disabled by default
      And dry-run validation can run before enablement
      When automatic sending is later explicitly enabled
      Then follow-up sends share the global 6-to-10-minute send pacing queue with first emails
      And the worker sends at most one follow-up per cycle
      And the initial rollout pauses follow-up auto-send after 10 successful follow-up sends for inspection

  @delivery_feedback
  Rule: Delivery Feedback behavior

    Scenario: Delivery feedback uses mailbox observation with the current timing rules
      Given an outreach message has been sent
      When Delivery Feedback runs
      Then one immediate post-send mailbox poll is allowed
      And delayed polling continues every 5 minutes during the 30-minute bounce-observation window
      And delayed feedback capture does not require the original interactive send session to remain running

    Scenario: Delivery feedback may begin immediately for each sent message
      Given multiple messages are being sent as part of the current active send slice
      When one specific send succeeds before the rest of the set has finished sending
      Then Delivery Feedback may begin bounce or reply observation for that sent message immediately
      And feedback observation for that message does not wait for the rest of the current active send slice to finish

    Scenario: Delivery feedback persists canonical event history and machine handoff output
      Given a sent message later receives a bounce, not-bounced, or reply signal
      When Delivery Feedback ingests that signal
      Then the outcome is written as an event into `delivery_feedback_events`
      And the event includes an explicit timestamp
      And `delivery_outcome.json` is produced as the machine handoff artifact
      And the latest state is derivable from event history rather than overwriting that history

    Scenario: Bounced outcomes conservatively block reuse without starting bounce recovery
      Given a sent email later bounces
      When Delivery Feedback records the bounced outcome
      Then that bounced email identity is blocked from future automatic reuse
      And the directly responsible provider result may also be blocked from future reuse
      But the posting is not automatically reopened into a bounce-recovery loop in the current build

    Scenario: Delayed feedback scheduling uses launchd in the current deployment
      Given the build is deployed on the supported single-user macOS setup
      When delayed feedback polling is configured
      Then `launchd` is used as the scheduler for recurring feedback sync
      And the scheduler invokes reusable Delivery Feedback sync logic rather than embedding mailbox logic directly
      And scheduled runs are auditable through `feedback_sync_runs`

    Scenario: The separate feedback-sync worker owns delayed mailbox polling
      Given a role-targeted pipeline run is waiting at `delivery_feedback`
      When delayed mailbox polling is needed
      Then the separate feedback-sync worker performs the delayed mailbox polling
      And the supervisor only reads persisted feedback state to keep or complete the run

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

    Scenario: Persisted reply events promote contacts into responder tracking without replacing lifecycle state
      Given a contact already exists in canonical state with ordinary outreach lifecycle fields
      And a real reply is persisted for one of that contact's messages
      When Delivery Feedback writes that `replied` event
      Then the contact responder metadata transitions to `replied`
      And the first known reply timestamp is stored on the contact when available
      But `contact_status` remains the outreach or discovery lifecycle field rather than being replaced by responder metadata

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
      And the current heartbeat interval is 5 seconds
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
      And actionable role-targeted sending outranks older ordinary discovery backlog
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

    Scenario: Failed refreshed tailoring is quarantined without pausing unrelated postings
      Given posting A previously reached `people_search`, `email_discovery`, `sending`, or `delivery_feedback`
      And posting A now has a newer `resume_tailoring_runs` row with `tailoring_status = needs_revision` and `resume_review_status = not_ready`
      And posting B still has independently actionable role-targeted pipeline work
      When the supervisor reconciles open pipeline work before normal progression
      Then posting A returns to `tailoring_in_progress`
      And any active Outreach-side pipeline run for posting A is retired from the runnable queue
      And the supervisor does not let posting A create a blocking prerequisite-incident cluster
      And the supervisor may continue selecting posting B work

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
      And it uses `RunAtLoad = true`, `StartInterval = 5`, and `KeepAlive = false`
      And it points `ProgramArguments` to `bin/jhc-agent-cycle` under the absolute project root
      And `bin/jhc-agent-cycle` runs `python3 scripts/ops/run_supervisor_cycle.py --project-root <absolute project root>`
      And supervisor stdout and stderr are written to dedicated files under `ops/logs/`

    Scenario: Current feedback-sync launchd and wrapper wiring uses the repo-local command path
      Given the current local macOS deployment is using the supported delayed feedback wiring
      When the feedback-sync launchd job and helper scripts are inspected
      Then `ops/launchd/job-hunt-copilot-feedback-sync.plist` uses `Label = com.jobhuntcopilot.feedback-sync`
      And it uses `RunAtLoad = true`, `StartInterval = 300`, and `KeepAlive = false`
      And it points `ProgramArguments` to `bin/jhc-feedback-sync-cycle` under the absolute project root
      And `bin/jhc-feedback-sync-cycle` runs `python3 scripts/ops/run_feedback_sync.py --project-root <absolute project root>`
      And feedback-sync stdout and stderr are written to dedicated files under `ops/logs/`

    Scenario: jhc-agent-start and jhc-agent-stop use the current launchctl wiring
      Given the current local helper entrypoints are installed
      When `jhc-agent-start` is invoked
      Then it runs the runtime-pack materialization step before enabling background execution
      And it ensures the supervisor plist is rendered with absolute project-root paths
      And it ensures the follow-up worker plist is rendered with absolute project-root paths
      And it uses `launchctl bootstrap` or an equivalent idempotent load-if-needed step
      And it uses `launchctl kickstart -k gui/$UID/com.jobhuntcopilot.supervisor` for the immediate first heartbeat
      And it manages the dedicated follow-up launchd job alongside the supervisor and feedback-sync jobs
      When `jhc-agent-stop` is invoked
      Then it writes disabled or stopped control state before unloading the job
      And it uses `launchctl bootout` or an equivalent idempotent unload step
      And it stops or disables the dedicated follow-up launchd job as part of the normal stop path

    Scenario: Dedicated follow-up worker has its own local runtime wiring
      Given the current local helper entrypoints are installed
      When follow-up worker runtime wiring is inspected
      Then a dedicated launchd job exists for the follow-up worker
      And it runs every 60 seconds without overriding shared send pacing
      And it points to a manual cycle entrypoint such as `bin/jhc-followup-cycle`
      And follow-up stdout and stderr are written to dedicated files under `ops/logs/`
      And follow-up control state can be paused or resumed independently from the primary supervisor

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
      And it includes compact follow-up fields for `due_now`, `waiting_for_pacing`, `sent_today`, `blocked_or_review`, `last_cycle_at`, and `last_cycle_result`

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
      And manual application-state or responder-state updates are routed through canonical object updates plus `override_events`

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
      Then the dependency order is Lead Ingestion, promotion gate, eligibility or tailoring, mandatory agent review, source-seeded contact enrichment, Apollo company-scoped search when needed or useful for the posting, selected-contact recipient-profile extraction, email discovery when still needed, frontier drafting for ready untouched contacts, sending, and delivery feedback
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

    Scenario: Role-targeted outreach uses the current source-priority order with pacing-aware progression
      Given a posting has multiple linked contacts across recipient types
      When the build runs role-targeted outreach
      Then when otherwise comparable contacts are available, Apollo manager / executive / founder contacts are processed ahead of personalized or public Jobright contacts
      And Apollo-added contacts are internally ranked before inclusion by engineering-lead relevance, technical-leadership seniority, role-family relevance, and current-company relevance
      And sends may be delayed by pacing rules instead of blasting every recipient group immediately

    Scenario: Posting-contact linking is created before per-contact discovery or outreach begins
      Given a role-targeted posting has source-seeded Jobright contacts or Apollo-shortlisted candidates
      And a candidate has entered the intended outreach set for that posting
      When the workflow prepares that shortlisted candidate for discovery or drafting
      Then a `job_posting_contacts` relationship is already present for that posting-contact pair
      And upstream source capture or Apollo company-scoped search may have happened before that canonical link existed
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
      And that contact counts as discovery-ready immediately for the posting frontier
      And drafting may begin for that contact once the posting-level prerequisites are satisfied
      But automatic sending for that posting still waits for the active send-slice and pacing rules

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

    Scenario: Positive reply from one contact does not stop later waves for the posting
      Given one contact on a posting has replied positively
      And additional intended contacts still remain for later automatic waves on that same posting
      When orchestration evaluates the posting on a later eligible cycle
      Then the remaining contacts still continue automatically under the normal wave, pacing, and cap rules
      And only the replied contact or thread is removed from further automatic outbound progression

    Scenario: Remaining intended contacts continue automatically on the next eligible day
      Given a posting has already used its current-day automatic send slice and per-posting daily send capacity
      And additional intended contacts still remain for later waves
      When the next eligible local day arrives and the posting is still otherwise sendable
      Then the system automatically continues with the next eligible wave without requiring manual approval

    Scenario: Later waves continue even if the posting later closes
      Given a posting already has an intended outreach set and remaining untouched contacts
      And the posting is later marked closed, archived, removed, or otherwise unavailable
      When orchestration evaluates the posting on a later eligible cycle
      Then the remaining already-captured contacts still continue automatically under the normal wave, pacing, and cap rules
      And the later posting lifecycle change does not by itself stop automatic continuation for those already-captured contacts

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

    Scenario: The user may close an unresolved escalated review item from expert review
      Given a posting remains unresolved
      And its current `pipeline_run` is `escalated`
      And an `expert_review_packet` for that run is `pending_expert_review` or `reviewed`
      When the user closes the item from review with a non-empty comment
      Then the posting transitions to `closed_by_user`
      And the pipeline run becomes `completed`
      And the pipeline run stage becomes `completed`
      And the close comment is stored as an `expert_review_decisions` record for that packet
      And a posting-status override event is recorded
      And the item no longer appears in normal pending expert-review queues

    Scenario: Manual application tracking is stored separately from the autonomous posting lifecycle
      Given a posting already exists in canonical state
      When the owner records a manual application update for that posting
      Then the posting retains its autonomous `posting_status`
      And the posting stores manual application fields separately from pipeline lifecycle state
      And the application change is recorded in `override_events`
      And the readable mirror `applications/{company}/{role}/application.yaml` is updated from canonical state

    Scenario: Manual responder tracking is stored separately from contact lifecycle state
      Given a contact already exists in canonical state
      When the owner manually promotes that contact to `warm`
      Then the contact retains its ordinary `contact_status`
      And the contact stores responder metadata separately from the outreach or discovery lifecycle
      And the responder change is recorded in `override_events`

    Scenario: Manual application and responder state are forward-only in the current build
      Given a posting or contact already has manual application or responder state recorded
      When the owner attempts to reset that manual state backward
      Then the system rejects the downgrade
      And the previously recorded manual state remains unchanged

    Scenario: General learning outreach bypasses the role-targeted agent-review requirement
      Given outreach is contact-rooted and not tied to a specific job posting
      When the build runs that general learning outreach flow
      Then the flow does not require posting-specific resume tailoring
      And the flow does not require the role-targeted agent-review requirement before drafting or sending

    Scenario: Discovery can start per contact while automatic sending still waits for the active send slice
      Given a posting has multiple linked contacts
      When one contact becomes linked and has enough local prerequisites to proceed
      Then discovery may begin for that contact without waiting for the full contact set
      And drafting may begin for that contact once the posting-level prerequisites are satisfied
      But automatic sending for that posting still waits for the active send-slice and pacing rules

    Scenario: One contact failure does not stop unrelated contacts in the same posting flow
      Given multiple contacts are being processed for the same posting
      When discovery, drafting, or sending fails for one contact
      Then unrelated eligible contacts may still continue through the workflow
      And the failed contact remains available for review or retry handling

    Scenario: Saved broad-search results may backfill the shortlist without rerunning external people search
      Given a posting has already consumed part of its shortlisted contact pool
      And a saved broad Apollo people-search artifact still exists for that posting
      When orchestration sees that the active shortlist is below the current limit
      Then the system may backfill additional shortlisted contacts from the saved broad-search artifact
      But it does not need to rerun external company-scoped people search immediately just to continue the posting

  @lead_ingestion
  Rule: Lead Ingestion acceptance

    Scenario: New Jobright leads receive stable lead identity and canonical lead workspaces
      Given a new upstream lead is ingested through authenticated Jobright recommendation intake
      When canonical lead state is materialized
      Then the lead receives a stable `lead_id`
      And the canonical lead workspace is rooted at `lead-ingestion/runtime/leads/<company>/<role>/<lead_id>/`

    Scenario: Jobright recommendation-feed and job-page observations both persist before downstream promotion
      Given an authenticated Jobright ingestion run sees one or more candidate roles
      When that ingestion run is collected
      Then the recommendation-feed snapshot is persisted under `lead-ingestion/runtime/jobright/{run_id}/...`
      And per-job page enrichments are persisted for the observed Jobright jobs
      And canonical lead fan-out into per-lead workspaces happens only after that upstream evidence exists

    Scenario: Jobright lead deduplication prefers stable job id and falls back to normalized Jobright URL
      Given a Jobright observation resolves to a stable `jobright_job_id` already seen for an existing lead
      When lead creation is evaluated
      Then a second canonical lead is not created
      Given a later Jobright observation lacks a usable stable job identifier
      And a usable Jobright job URL is available
      When fallback identity is materialized
      Then a synthetic fallback identity key is created from the normalized Jobright job URL
      And the lead may still be created or refreshed from that fallback identity

    Scenario: Duplicate canonical lead identities are refreshed instead of crashing
      Given authenticated Jobright ingestion encounters a recommendation that resolves to an existing canonical lead identity
      When canonical lead materialization runs
      Then the existing lead is refreshed or reused
      But the run does not crash on duplicate canonical creation

    Scenario: New lead workspaces start in discovery and become blocked-no-jd only when usable JD recovery fails
      Given a Jobright recommendation survives validation and deduplication
      When the autonomous lead workspace is created
      Then that workspace is created immediately for the deduplicated lead
      And the new workspace starts in an upstream discovery or held state
      When usable JD recovery later fails for that lead
      Then the lead may transition to `blocked_no_jd`

    Scenario: Lead workspace artifacts remain present even when a lead is blocked, held, or waiting on reauthentication
      Given one lead is blocked by missing usable JD and another is waiting on Jobright reauthentication
      When their lead workspaces are inspected
      Then every lead workspace still contains `lead-manifest.yaml`
      And every lead workspace still contains the source-observation artifacts already captured for that lead
      And blocked or reauth-held leads are not required to materialize downstream `job_postings`

    Scenario: Source metadata is owned by the lead and downstreams use lead-manifest artifact references
      Given a lead has been ingested and normalized
      When source metadata and downstream inputs are inspected
      Then source metadata such as `source_type`, `source_reference`, `source_url`, `source_mode`, and source-mode-specific provenance is source-of-truth on the lead entity
      And downstream components consume artifact references from `lead-manifest.yaml` rather than relying on hardcoded upstream directory assumptions

    Scenario: Refreshing an existing discovery lead updates the live workspace while preserving history snapshots
      Given an existing unpromoted lead is refreshed with newer Jobright source state
      When the lead workspace is updated
      Then the live lead workspace is updated in place
      And older source snapshots remain preserved in lead-local history artifacts

    Scenario: Lower refreshed scores replace older stronger discovery scores until a later improvement occurs
      Given an unpromoted Jobright lead previously had a stronger score and connections snapshot
      When a later authenticated Jobright run returns that same lead with a lower score or weaker promotability
      Then the newer weaker discovery state becomes the active promotion state
      When a still-later Jobright run improves that same lead enough to satisfy the current promotion gate
      Then the lead becomes automatically eligible for promotion on that later cycle

    Scenario: Promotion creates the posting immediately and carries source-seeded contacts forward
      Given a Jobright lead has a usable JD and passes the current promotion rules
      When the lead is promoted
      Then a canonical `job_posting` is created immediately
      And the promoting source observation is linked to that posting
      And all Jobright-seeded contacts are carried forward into `job_posting_contacts`
      And Apollo top-up may continue later without blocking posting creation

    Scenario: Promotion keeps all Jobright-seeded contacts and Apollo adds shortlisted current-company plus manager-class contacts
      Given a promoted Jobright lead already has some public or personalized source-seeded contacts
      When the intended outreach set is built
      Then all Jobright-seeded contacts automatically enter that set
      And Apollo enrichment is used to recover fuller identity and usable-email data for those same contacts
      And Apollo current-company search may shortlist additional manager-class technical-leadership contacts for that posting
      And all Apollo manager-class contacts explicitly shortlisted for that posting enter the intended outreach set
      And Apollo may also add current-company manager-class contacts for that posting under the adaptive manager-expansion cap

  @end_to_end
  Rule: End-to-end acceptance

    Scenario: Role-targeted flow completes from Lead Ingestion through delivery feedback
      Given a role-targeted lead entered through authenticated Jobright recommendation intake
      And the required secrets, assets, and environment prerequisites are all available
      When the build runs the primary role-targeted flow
      Then the flow progresses through Lead Ingestion, promotion gate, tailoring, mandatory agent review, source-seeded contact enrichment, Apollo company-scoped search when needed or useful for the posting, selected-contact recipient-profile extraction, email discovery when needed, frontier drafting for ready untouched contacts, sending, and delivery feedback
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
      Then the system resumes from the last successful stage boundary rather than restarting from Lead Ingestion
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
