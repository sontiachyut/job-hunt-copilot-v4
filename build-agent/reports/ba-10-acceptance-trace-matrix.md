# BA-10 Acceptance Trace Matrix

- Feature file: `prd/test-spec.feature`
- Scenario count: `214`
- Status counts:
  - `implemented`: `189`
  - `partial`: `9`
  - `gap`: `14`
  - `deferred_optional`: `1`
  - `excluded_from_required_acceptance`: `1`

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
| Supervisor Agent behavior | build-lead | 17 | 5 | 11 | 0 | 0 |
| Review surfaces and chat-based control | quality-engineer | 6 | 0 | 1 | 0 | 0 |
| Current-build orchestration remains sequential | build-lead | 19 | 2 | 1 | 0 | 0 |
| LinkedIn Scraping acceptance | ingestion-engineer | 12 | 0 | 0 | 0 | 0 |
| End-to-end acceptance | quality-engineer | 1 | 2 | 0 | 0 | 1 |
| Current-build safety, privacy, and evidence-grounding boundaries | quality-engineer | 3 | 0 | 0 | 0 | 0 |

## Explicit Gaps

### BA10_SUPERVISOR_DOWNSTREAM_ACTION_CATALOG: Supervisor orchestration still stops at lead handoff
- Next slice: `BA-10-S3`
- Reason: The durable heartbeat and incident model exist, but the registered action catalog still only advances autonomous work through `lead_handoff` before unsupported downstream stages escalate.
- Scenarios: `5`
  - Supervisor work selection follows the current default priority order
  - Role-targeted orchestration follows the current dependency order
  - General learning outreach bypasses the role-targeted agent-review requirement
  - Role-targeted flow completes from LinkedIn Scraping through delivery feedback
  - End-to-end retry resumes from the last successful stage boundary

### BA10_MAINTENANCE_AUTOMATION: Maintenance workflow and artifacts are not implemented
- Next slice: `BA-10-S3`
- Reason: The schema and runtime pack reserve maintenance surfaces, but there is no autonomous maintenance batch workflow, no maintenance artifacts, and no maintenance review flow yet.
- Scenarios: `5`
  - Maintenance change artifacts exist for every autonomous maintenance batch
  - Daily maintenance is mandatory, bounded, and run-boundary aware
  - Maintenance changes follow the current git and approval workflow
  - Proper maintenance validation requires both change-scoped and full-project testing
  - Failed or unapproved maintenance batches remain reviewable

### BA10_CHAT_REVIEW_AND_CONTROL: Chat review and control remain wrapper-only
- Next slice: `BA-10-S3`
- Reason: The direct `jhc-chat` entrypoint manages chat session lifecycle, but richer review retrieval, control routing, and expert-guidance behaviors are not yet implemented in the chat surface.
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
- Reason: Explicit-close and explicit-resume paths exist, but unexpected `jhc-chat` exits still require a later explicit resume because automatic idle-timeout recovery is not implemented.
- Scenarios: `1`
  - Expert-interaction resume follows explicit close, explicit resume, or safe idle timeout

### BA10_SLEEP_WAKE_RECOVERY: Sleep and wake recovery is not implemented beyond metadata
- Next slice: `BA-10-S3`
- Reason: Supervisor cycles record the intended sleep/wake detection method, but the actual pmset-log parsing and conservative fallback logic have not been implemented.
- Scenarios: `1`
  - Current macOS sleep or wake detection uses pmset logs first and conservative fallback second

### BA10_POSTING_ABANDON_CONTROL: Posting-abandon control surface is missing
- Next slice: `BA-10-S3`
- Reason: There is no explicit user-facing or runtime control path that abandons a posting from arbitrary active orchestration states while preserving canonical history.
- Scenarios: `1`
  - The user may explicitly abandon a posting from any active orchestration state

## Epic Validation Ownership

### BA-01 (foundation-engineer)
- Focus: bootstrap, schema migration, shared artifact contracts
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
- Primary tests:
  - `tests/test_supervisor.py`
- BA-10 smoke targets:
  - single-cycle heartbeat execution
  - lease safety
  - review-packet persistence for escalations

### BA-03 (build-lead)
- Focus: runtime pack, launchd helpers, chat session lifecycle
- Primary tests:
  - `tests/test_runtime_pack.py`
  - `tests/test_local_runtime.py`
- BA-10 smoke targets:
  - runtime-pack materialization
  - repo-local wrapper wiring
  - chat begin/end pause semantics

### BA-04 (ingestion-engineer)
- Focus: manual capture, paste fallback, lead derivation and posting materialization
- Primary tests:
  - `tests/test_linkedin_scraping.py`
- BA-10 smoke targets:
  - paste inbox ingestion
  - capture-bundle persistence
  - posting/contact handoff creation

### BA-05 (ingestion-engineer)
- Focus: Gmail collection, job-card parsing, JD provenance merge
- Primary tests:
  - `tests/test_gmail_alerts.py`
- BA-10 smoke targets:
  - plain-text-first Gmail parsing
  - JD recovery merge
  - lead dedupe and blocked-no-jd handling

### BA-06 (tailoring-engineer)
- Focus: eligibility, tailoring workspace, finalize verification, mandatory review
- Primary tests:
  - `tests/test_resume_tailoring.py`
- BA-10 smoke targets:
  - sample posting tailoring bootstrap
  - finalize plus compile check
  - review approval handoff into outreach readiness

### BA-07 (outreach-engineer)
- Focus: people search, enrichment, email discovery, provider budgets
- Primary tests:
  - `tests/test_email_discovery.py`
- BA-10 smoke targets:
  - Apollo shortlist bootstrap
  - provider cascade outcome
  - machine-valid discovery artifact

### BA-08 (outreach-engineer)
- Focus: send-set readiness, drafting artifacts, safe send execution
- Primary tests:
  - `tests/test_outreach.py`
- BA-10 smoke targets:
  - role-targeted draft batch
  - general-learning draft path
  - machine-valid send artifact

### BA-09 (outreach-engineer)
- Focus: feedback event persistence, review queries, feedback reuse policy
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
- Primary tests:
  - `tests/test_acceptance_traceability.py`
  - `tests/test_smoke_harness.py`
- BA-10 smoke targets:
  - feature-to-code coverage honesty
  - committed smoke fixture coverage
  - explicit blocker confirmation
