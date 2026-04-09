# BA-10 Acceptance Trace Matrix

- Feature file: `prd/test-spec.feature`
- Scenario count: `214`
- Status counts:
  - `implemented`: `194`
  - `partial`: `4`
  - `gap`: `14`
  - `deferred_optional`: `1`
  - `excluded_from_required_acceptance`: `1`

## Implemented Slice Catalog

| Slice | Epic | Owner | Status |
| --- | --- | --- | --- |
| BA-01-S1 | BA-01 | foundation-engineer | completed |
| BA-01-S2 | BA-01 | foundation-engineer | completed |
| BA-01-S3 | BA-01 | foundation-engineer | completed |
| BA-02-S1 | BA-02 | build-lead | completed |
| BA-02-S2 | BA-02 | build-lead | completed |
| BA-02-S3 | BA-02 | build-lead | completed |
| BA-03-S1 | BA-03 | build-lead | completed |
| BA-03-S2 | BA-03 | build-lead | completed |
| BA-03-S3 | BA-03 | build-lead | completed |
| BA-04-S1 | BA-04 | ingestion-engineer | completed |
| BA-04-S2 | BA-04 | ingestion-engineer | completed |
| BA-04-S3 | BA-04 | ingestion-engineer | completed |
| BA-04-S4 | BA-04 | ingestion-engineer | completed |
| BA-05-S1 | BA-05 | ingestion-engineer | completed |
| BA-05-S2 | BA-05 | ingestion-engineer | completed |
| BA-05-S3 | BA-05 | ingestion-engineer | completed |
| BA-06-S1 | BA-06 | tailoring-engineer | completed |
| BA-06-S2 | BA-06 | tailoring-engineer | completed |
| BA-06-S3 | BA-06 | tailoring-engineer | completed |
| BA-06-S4 | BA-06 | tailoring-engineer | completed |
| BA-07-S1 | BA-07 | outreach-engineer | completed |
| BA-07-S2 | BA-07 | outreach-engineer | completed |
| BA-07-S3 | BA-07 | outreach-engineer | completed |
| BA-08-S1 | BA-08 | outreach-engineer | completed |
| BA-08-S2 | BA-08 | outreach-engineer | completed |
| BA-08-S3 | BA-08 | outreach-engineer | completed |
| BA-09-S1 | BA-09 | outreach-engineer | completed |
| BA-09-S2 | BA-09 | outreach-engineer | completed |
| BA-09-S3 | BA-09 | outreach-engineer | completed |
| BA-10-S1 | BA-10 | quality-engineer | completed |
| BA-10-S2 | BA-10 | quality-engineer | completed |
| BA-10-S3 | BA-10 | quality-engineer | in_progress |
| BA-10-S4 | BA-10 | build-lead | in_progress |

## Rule Summary

| Rule | Owner | Implemented | Partial | Gap | Deferred | Excluded |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Build bootstrap and prerequisites | foundation-engineer | 7 | 0 | 0 | 0 | 0 |
| Machine handoff contracts and canonical state | build-lead | 14 | 0 | 1 | 0 | 0 |
| State transitions and relationship records | build-lead | 12 | 0 | 0 | 0 | 0 |
| External integrations and bootstrap configuration | ingestion-engineer | 25 | 0 | 0 | 1 | 0 |
| Failure, retry, and idempotency behavior | quality-engineer | 8 | 0 | 0 | 0 | 0 |
| Resume Tailoring behavior | tailoring-engineer | 23 | 0 | 0 | 0 | 0 |
| Email Discovery behavior | outreach-engineer | 17 | 0 | 0 | 0 | 0 |
| Email Drafting and Sending behavior | outreach-engineer | 14 | 0 | 0 | 0 | 0 |
| Delivery Feedback behavior | outreach-engineer | 11 | 0 | 0 | 0 | 0 |
| Supervisor Agent behavior | build-lead | 18 | 4 | 11 | 0 | 0 |
| Review surfaces and chat-based control | quality-engineer | 6 | 0 | 1 | 0 | 0 |
| Current-build orchestration remains sequential | build-lead | 21 | 0 | 1 | 0 | 0 |
| LinkedIn Scraping acceptance | ingestion-engineer | 12 | 0 | 0 | 0 | 0 |
| End-to-end acceptance | quality-engineer | 3 | 0 | 0 | 0 | 1 |
| Current-build safety, privacy, and evidence-grounding boundaries | quality-engineer | 3 | 0 | 0 | 0 | 0 |

## Rule-To-Slice Mapping

### Build bootstrap and prerequisites
- Supporting slices: `BA-01-S1`, `BA-01-S2`, `BA-01-S3`, `BA-03-S1`, `BA-03-S2`, `BA-03-S3`

### Machine handoff contracts and canonical state
- Supporting slices: `BA-01-S1`, `BA-01-S2`, `BA-01-S3`, `BA-02-S1`, `BA-02-S2`, `BA-02-S3`, `BA-04-S1`, `BA-04-S2`, `BA-04-S3`, `BA-04-S4`, `BA-06-S1`, `BA-06-S2`, `BA-06-S3`, `BA-06-S4`, `BA-07-S1`, `BA-07-S2`, `BA-07-S3`, `BA-08-S1`, `BA-08-S2`, `BA-08-S3`, `BA-09-S1`, `BA-09-S2`, `BA-09-S3`

### State transitions and relationship records
- Supporting slices: `BA-01-S1`, `BA-01-S2`, `BA-01-S3`, `BA-04-S1`, `BA-04-S2`, `BA-04-S3`, `BA-04-S4`, `BA-06-S1`, `BA-06-S2`, `BA-06-S3`, `BA-06-S4`, `BA-07-S1`, `BA-07-S2`, `BA-07-S3`, `BA-08-S1`, `BA-08-S2`, `BA-08-S3`, `BA-09-S1`, `BA-09-S2`, `BA-09-S3`

### External integrations and bootstrap configuration
- Supporting slices: `BA-01-S1`, `BA-01-S2`, `BA-01-S3`, `BA-04-S1`, `BA-04-S2`, `BA-04-S3`, `BA-04-S4`, `BA-05-S1`, `BA-05-S2`, `BA-05-S3`, `BA-07-S1`, `BA-07-S2`, `BA-07-S3`

### Failure, retry, and idempotency behavior
- Supporting slices: `BA-02-S1`, `BA-02-S2`, `BA-02-S3`, `BA-04-S1`, `BA-04-S2`, `BA-04-S3`, `BA-04-S4`, `BA-05-S1`, `BA-05-S2`, `BA-05-S3`, `BA-07-S1`, `BA-07-S2`, `BA-07-S3`, `BA-08-S1`, `BA-08-S2`, `BA-08-S3`, `BA-09-S1`, `BA-09-S2`, `BA-09-S3`

### Resume Tailoring behavior
- Supporting slices: `BA-06-S1`, `BA-06-S2`, `BA-06-S3`, `BA-06-S4`

### Email Discovery behavior
- Supporting slices: `BA-07-S1`, `BA-07-S2`, `BA-07-S3`, `BA-09-S1`, `BA-09-S2`, `BA-09-S3`

### Email Drafting and Sending behavior
- Supporting slices: `BA-08-S1`, `BA-08-S2`, `BA-08-S3`

### Delivery Feedback behavior
- Supporting slices: `BA-03-S1`, `BA-03-S2`, `BA-03-S3`, `BA-09-S1`, `BA-09-S2`, `BA-09-S3`

### Supervisor Agent behavior
- Supporting slices: `BA-02-S1`, `BA-02-S2`, `BA-02-S3`, `BA-03-S1`, `BA-03-S2`, `BA-03-S3`

### Review surfaces and chat-based control
- Supporting slices: `BA-03-S1`, `BA-03-S2`, `BA-03-S3`, `BA-09-S1`, `BA-09-S2`, `BA-09-S3`

### Current-build orchestration remains sequential
- Supporting slices: `BA-06-S1`, `BA-06-S2`, `BA-06-S3`, `BA-06-S4`, `BA-07-S1`, `BA-07-S2`, `BA-07-S3`, `BA-08-S1`, `BA-08-S2`, `BA-08-S3`, `BA-09-S1`, `BA-09-S2`, `BA-09-S3`

### LinkedIn Scraping acceptance
- Supporting slices: `BA-04-S1`, `BA-04-S2`, `BA-04-S3`, `BA-04-S4`, `BA-05-S1`, `BA-05-S2`, `BA-05-S3`

### End-to-end acceptance
- Supporting slices: `BA-06-S1`, `BA-06-S2`, `BA-06-S3`, `BA-06-S4`, `BA-07-S1`, `BA-07-S2`, `BA-07-S3`, `BA-08-S1`, `BA-08-S2`, `BA-08-S3`, `BA-09-S1`, `BA-09-S2`, `BA-09-S3`

### Current-build safety, privacy, and evidence-grounding boundaries
- Supporting slices: `BA-06-S1`, `BA-06-S2`, `BA-06-S3`, `BA-06-S4`, `BA-08-S1`, `BA-08-S2`, `BA-08-S3`, `BA-09-S1`, `BA-09-S2`, `BA-09-S3`


## Explicit Gaps

### BA10_SUPERVISOR_DOWNSTREAM_ACTION_CATALOG: Supervisor general-learning orchestration remains partial beyond bounded contact-rooted send completion
- Next slice: `BA-10-S4`
- Supporting slices: `BA-02-S1`, `BA-02-S2`, `BA-02-S3`, `BA-03-S1`, `BA-03-S2`, `BA-03-S3`, `BA-10-S4`
- Reason: The durable heartbeat now covers the full role-targeted flow through bounded delivery-feedback completion and can advance contact-rooted general-learning work from email discovery into send-ready dispatch, but delayed feedback follow-through for sent contact-rooted outreach still remains outside the registered autonomous catalog.
- Evidence summary: Focused downstream-stage regressions prove active incidents still outrank ordinary progression, existing durable runs are selected before bootstrapping new eligible postings, `lead_handoff` now advances into `agent_review`, bounded mandatory agent review advances the same run into `people_search`, bounded people search materializes shortlist artifacts and advances the same run into `email_discovery`, bounded email discovery advances the same durable run into `sending` when readiness is satisfied, bounded sending now drafts the ready send set, executes one safe send, stays at `sending` while later-wave contacts remain paced, advances the same durable run into `delivery_feedback` after terminal sent waves, bounded delivery feedback now runs the shared delayed-sync logic, keeps the durable run active while high-level outcomes remain pending, completes the same durable run with a review packet once all sent messages reach bounced, not_bounced, or replied state, a contact-rooted general-learning candidate without a working email now runs bounded email discovery, becomes send-ready in canonical contact state, and is then selected for the existing contact-rooted send path on the next heartbeat without posting linkage or review-gate prerequisites, and the remaining contact-rooted gap is narrowed to delayed-feedback follow-through after sent general-learning outreach.
- Evidence code refs: `job_hunt_copilot/supervisor.py`, `job_hunt_copilot/email_discovery.py`, `job_hunt_copilot/outreach.py`, `job_hunt_copilot/delivery_feedback.py`, `job_hunt_copilot/local_runtime.py`, `job_hunt_copilot/runtime_pack.py`
- Evidence test refs: `tests/test_supervisor_downstream_actions.py`, `tests/test_blocker_audit.py`, `tests/test_acceptance_traceability.py`
- Implementation snapshot:
  - Current selector priority order: `active_incident`, `open_pipeline_run`, `new_role_targeted_posting`, `general_learning_contact`
  - Registered role-targeted checkpoint stages: `agent_review`, `lead_handoff`
  - Unsupported autonomous scope paths: `contact_rooted_general_learning_delayed_feedback_followthrough`
- Scenarios: `1`
  - Supervisor work selection follows the current default priority order

### BA10_MAINTENANCE_AUTOMATION: Maintenance workflow and artifacts are not implemented
- Next slice: `BA-10-S3`
- Supporting slices: `BA-01-S1`, `BA-01-S2`, `BA-01-S3`, `BA-02-S1`, `BA-02-S2`, `BA-02-S3`, `BA-04-S1`, `BA-04-S2`, `BA-04-S3`, `BA-04-S4`, `BA-06-S1`, `BA-06-S2`, `BA-06-S3`, `BA-06-S4`, `BA-07-S1`, `BA-07-S2`, `BA-07-S3`, `BA-08-S1`, `BA-08-S2`, `BA-08-S3`, `BA-09-S1`, `BA-09-S2`, `BA-09-S3`, `BA-03-S1`, `BA-03-S2`, `BA-03-S3`, `BA-10-S3`
- Reason: The schema and runtime pack reserve maintenance surfaces, but there is no autonomous maintenance batch workflow, no maintenance artifacts, and no maintenance review flow yet.
- Evidence summary: Schema and runtime scaffolding reserve maintenance surfaces, but there is still no maintenance module, runner, or review-artifact workflow.
- Evidence code refs: `job_hunt_copilot/migrations/0002_canonical_schema.sql`, `job_hunt_copilot/paths.py`, `job_hunt_copilot/runtime_pack.py`
- Evidence test refs: `tests/test_schema.py`, `tests/test_runtime_pack.py`, `tests/test_acceptance_traceability.py`
- Scenarios: `5`
  - Maintenance change artifacts exist for every autonomous maintenance batch
  - Daily maintenance is mandatory, bounded, and run-boundary aware
  - Maintenance changes follow the current git and approval workflow
  - Proper maintenance validation requires both change-scoped and full-project testing
  - Failed or unapproved maintenance batches remain reviewable

### BA10_CHAT_REVIEW_AND_CONTROL: Chat review and control remain wrapper-only
- Next slice: `BA-10-S3`
- Supporting slices: `BA-02-S1`, `BA-02-S2`, `BA-02-S3`, `BA-03-S1`, `BA-03-S2`, `BA-03-S3`, `BA-09-S1`, `BA-09-S2`, `BA-09-S3`, `BA-10-S3`
- Reason: The direct `jhc-chat` entrypoint manages chat session lifecycle, but richer review retrieval, control routing, and expert-guidance behaviors are not yet implemented in the chat surface.
- Evidence summary: Chat lifecycle, review-query reads, and bootstrap scaffolding exist, but chat itself still does not retrieve grouped reviews or route control decisions.
- Evidence code refs: `scripts/ops/chat_session.py`, `job_hunt_copilot/local_runtime.py`, `job_hunt_copilot/review_queries.py`, `job_hunt_copilot/runtime_pack.py`
- Evidence test refs: `tests/test_local_runtime.py`, `tests/test_review_queries.py`, `tests/test_runtime_pack.py`, `tests/test_acceptance_traceability.py`
- Scenarios: `10`
  - jhc-chat startup dashboard is detailed, bounded, and clean-first
  - Startup dashboard runtime metrics count only active autonomous execution
  - Review retrieval is grouped, compact-first, and newest-first within each group
  - jhc-chat uses persisted state for answers and control routing
  - Default change summaries cover activity since the last completed expert review
  - Expert guidance becomes live immediately but conflicting or uncertain reuse asks first
  - Conflicting expert guidance pauses the whole autonomous system
  - Expert-requested background tasks require explicit handoff summary and exclusive focus
  - Expert-requested background task outcomes return to review appropriately
  - AI agent surfaces the current review queue in chat

### BA10_CHAT_IDLE_TIMEOUT_RESUME: Idle-timeout resume is still backlog
- Next slice: `BA-10-S3`
- Supporting slices: `BA-02-S1`, `BA-02-S2`, `BA-02-S3`, `BA-03-S1`, `BA-03-S2`, `BA-03-S3`, `BA-10-S3`
- Reason: Explicit-close and explicit-resume paths exist, but unexpected `jhc-chat` exits still require a later explicit resume because automatic idle-timeout recovery is not implemented.
- Evidence summary: Unexpected chat exit is recorded and a later explicit resume works, but no automatic idle-timeout resume helper exists.
- Evidence code refs: `job_hunt_copilot/local_runtime.py`, `job_hunt_copilot/runtime_pack.py`
- Evidence test refs: `tests/test_local_runtime.py`, `tests/test_runtime_pack.py`, `tests/test_acceptance_traceability.py`
- Scenarios: `1`
  - Expert-interaction resume follows explicit close, explicit resume, or safe idle timeout

### BA10_POSTING_ABANDON_CONTROL: Posting-abandon control surface is missing
- Next slice: `BA-10-S3`
- Supporting slices: `BA-06-S1`, `BA-06-S2`, `BA-06-S3`, `BA-06-S4`, `BA-07-S1`, `BA-07-S2`, `BA-07-S3`, `BA-08-S1`, `BA-08-S2`, `BA-08-S3`, `BA-09-S1`, `BA-09-S2`, `BA-09-S3`, `BA-10-S3`
- Reason: There is no explicit user-facing or runtime control path that abandons a posting from arbitrary active orchestration states while preserving canonical history.
- Evidence summary: Agent-level start/stop/pause/resume/replan controls exist, but there is still no posting-scoped abandon command or runtime mutation path.
- Evidence code refs: `scripts/ops/control_agent.py`, `job_hunt_copilot/local_runtime.py`, `job_hunt_copilot/supervisor.py`
- Evidence test refs: `tests/test_local_runtime.py`, `tests/test_acceptance_traceability.py`
- Scenarios: `1`
  - The user may explicitly abandon a posting from any active orchestration state

## Epic Validation Ownership

### BA-01 (foundation-engineer)
- Focus: bootstrap, schema migration, shared artifact contracts
- Implemented slices: `BA-01-S1`, `BA-01-S2`, `BA-01-S3`
- Primary tests:
  - `tests/test_bootstrap.py`
  - `tests/test_schema.py`
  - `tests/test_artifacts.py`
- BA-10 smoke targets:
  - bootstrap prerequisites
  - DB init and migration
  - required assets and secret materialization

### BA-02 (build-lead)
- Focus: durable supervisor state, bounded cycles, incidents, review packets
- Implemented slices: `BA-02-S1`, `BA-02-S2`, `BA-02-S3`
- Primary tests:
  - `tests/test_supervisor.py`
- BA-10 smoke targets:
  - single-cycle heartbeat execution
  - lease safety
  - review-packet persistence for escalations

### BA-03 (build-lead)
- Focus: runtime pack, launchd helpers, chat session lifecycle
- Implemented slices: `BA-03-S1`, `BA-03-S2`, `BA-03-S3`
- Primary tests:
  - `tests/test_runtime_pack.py`
  - `tests/test_local_runtime.py`
- BA-10 smoke targets:
  - runtime-pack materialization
  - repo-local wrapper wiring
  - chat begin/end pause semantics

### BA-04 (ingestion-engineer)
- Focus: manual capture, paste fallback, lead derivation and posting materialization
- Implemented slices: `BA-04-S1`, `BA-04-S2`, `BA-04-S3`, `BA-04-S4`
- Primary tests:
  - `tests/test_linkedin_scraping.py`
- BA-10 smoke targets:
  - paste inbox ingestion
  - capture-bundle persistence
  - posting/contact handoff creation

### BA-05 (ingestion-engineer)
- Focus: Gmail collection, job-card parsing, JD provenance merge
- Implemented slices: `BA-05-S1`, `BA-05-S2`, `BA-05-S3`
- Primary tests:
  - `tests/test_gmail_alerts.py`
- BA-10 smoke targets:
  - plain-text-first Gmail parsing
  - JD recovery merge
  - lead dedupe and blocked-no-jd handling

### BA-06 (tailoring-engineer)
- Focus: eligibility, tailoring workspace, finalize verification, mandatory review
- Implemented slices: `BA-06-S1`, `BA-06-S2`, `BA-06-S3`, `BA-06-S4`
- Primary tests:
  - `tests/test_resume_tailoring.py`
- BA-10 smoke targets:
  - sample posting tailoring bootstrap
  - finalize plus compile check
  - review approval handoff into outreach readiness

### BA-07 (outreach-engineer)
- Focus: people search, enrichment, email discovery, provider budgets
- Implemented slices: `BA-07-S1`, `BA-07-S2`, `BA-07-S3`
- Primary tests:
  - `tests/test_email_discovery.py`
- BA-10 smoke targets:
  - Apollo shortlist bootstrap
  - provider cascade outcome
  - machine-valid discovery artifact

### BA-08 (outreach-engineer)
- Focus: send-set readiness, drafting artifacts, safe send execution
- Implemented slices: `BA-08-S1`, `BA-08-S2`, `BA-08-S3`
- Primary tests:
  - `tests/test_outreach.py`
- BA-10 smoke targets:
  - role-targeted draft batch
  - general-learning draft path
  - machine-valid send artifact

### BA-09 (outreach-engineer)
- Focus: feedback event persistence, review queries, feedback reuse policy
- Implemented slices: `BA-09-S1`, `BA-09-S2`, `BA-09-S3`
- Primary tests:
  - `tests/test_delivery_feedback.py`
  - `tests/test_review_queries.py`
  - `tests/test_smoke_harness.py`
- BA-10 smoke targets:
  - one delayed feedback sync run
  - delivery_outcome artifact generation
  - review-surface queryability

### BA-10 (quality-engineer)
- Focus: acceptance traceability, smoke harness, blocker burn-down
- Implemented slices: `BA-10-S1`, `BA-10-S2`, `BA-10-S3`, `BA-10-S4`
- Primary tests:
  - `tests/test_acceptance_traceability.py`
  - `tests/test_blocker_audit.py`
  - `tests/test_supervisor_downstream_actions.py`
  - `tests/test_smoke_harness.py`
- BA-10 smoke targets:
  - feature-to-code coverage honesty
  - committed smoke fixture coverage
  - explicit blocker confirmation

## Smoke Coverage Targets

### bootstrap: Bootstrap and prerequisites
- Acceptance scenario: `Build smoke test passes`
- Acceptance checks:
  - the system initializes or migrates `job_hunt_copilot.db`
  - the system loads runtime secrets successfully
  - the system reads the required files from `assets/`
- Evidence code refs: `job_hunt_copilot/bootstrap.py`, `job_hunt_copilot/secrets.py`, `job_hunt_copilot/db.py`
- Evidence test refs: `tests/test_smoke_harness.py`, `tests/test_bootstrap.py`, `tests/test_schema.py`
- Validation command ids: `qa_smoke_flow`, `qa_bootstrap_regressions`

### tailoring: Resume tailoring
- Acceptance scenario: `Build smoke test passes`
- Acceptance checks:
  - the system can create a Resume Tailoring workspace for a sample posting
  - the system can compile the base or tailored resume successfully
- Evidence code refs: `job_hunt_copilot/resume_tailoring.py`, `job_hunt_copilot/paths.py`
- Evidence test refs: `tests/test_smoke_harness.py`, `tests/test_resume_tailoring.py`
- Validation command ids: `qa_smoke_flow`, `qa_tailoring_regressions`

### discovery: Discovery path
- Acceptance scenario: `Build smoke test passes`
- Acceptance checks:
  - the system can run a discovery-path check with normalized output
  - the system can generate a machine-valid `discovery_result.json`
- Evidence code refs: `job_hunt_copilot/email_discovery.py`, `job_hunt_copilot/review_queries.py`
- Evidence test refs: `tests/test_smoke_harness.py`, `tests/test_email_discovery.py`
- Validation command ids: `qa_smoke_flow`, `qa_discovery_regressions`

### send: Drafting and sending
- Acceptance scenario: `Build smoke test passes`
- Acceptance checks:
  - the system can generate a machine-valid `send_result.json`
- Evidence code refs: `job_hunt_copilot/outreach.py`, `job_hunt_copilot/paths.py`
- Evidence test refs: `tests/test_smoke_harness.py`, `tests/test_outreach.py`
- Validation command ids: `qa_smoke_flow`, `qa_outreach_regressions`

### feedback: Delayed feedback sync
- Acceptance scenario: `Build smoke test passes`
- Acceptance checks:
  - the delayed feedback sync logic can run once without crashing
- Evidence code refs: `job_hunt_copilot/delivery_feedback.py`, `job_hunt_copilot/local_runtime.py`
- Evidence test refs: `tests/test_smoke_harness.py`, `tests/test_delivery_feedback.py`, `tests/test_local_runtime.py`
- Validation command ids: `qa_smoke_flow`, `qa_feedback_regressions`

### review_query: Review-query surfaces
- Acceptance scenario: `Build smoke test passes`
- Acceptance checks:
  - at least one review surface can be queried from canonical state
- Evidence code refs: `job_hunt_copilot/review_queries.py`, `job_hunt_copilot/delivery_feedback.py`
- Evidence test refs: `tests/test_smoke_harness.py`, `tests/test_review_queries.py`
- Validation command ids: `qa_smoke_flow`, `qa_review_surface_regressions`
