# Architecture Overview

This document is the quickest technical walkthrough of the repository.

For the full contract, see [prd/spec.md](../prd/spec.md).

## Big Picture

Job Hunt Copilot v4 is designed as two related systems:

1. the **product runtime**
   - ingests leads
   - tailors resumes
   - finds people
   - sends outreach
   - tracks delivery outcomes

2. the **control planes**
   - the **operations / supervisor agent** that runs the product
   - the **build agent** that helps implement the product itself

## Product Flow

```mermaid
flowchart TD
    A[Lead Intake] --> B[Lead + JD Materialization]
    B --> C[Resume Tailoring]
    C --> D[Agent Review]
    D --> E[People Search]
    E --> F[Enrichment]
    F --> G[Email Discovery]
    G --> H[Drafting]
    H --> I[Sending]
    I --> J[Delivery Feedback]
```

## Runtime Control Plane

```mermaid
flowchart TD
    A[launchd Heartbeat] --> B[Supervisor Cycle]
    B --> C[Read Canonical State]
    C --> D[Pick One Work Unit]
    D --> E[Reason With Fresh LLM Context]
    E --> F[Execute Bounded Action]
    F --> G[Validate]
    G --> H[Persist Results / Incidents / Review Packets]
    H --> I[Sleep Until Next Heartbeat]

    J[Expert via jhc-chat] --> B
```

Key design choice:
- the LLM is not the memory
- SQLite state, artifacts, and logs are the memory

## Build Control Plane

```mermaid
flowchart TD
    A[launchd Heartbeat] --> B[Build Lead Cycle]
    B --> C[Read PRD + Acceptance + Build State]
    C --> D[Choose One Bounded Slice]
    D --> E[Assign Specialist Role]
    E --> F[codex exec Fresh Session]
    F --> G[Validate Slice]
    G --> H[Checkpoint Build State]
    H --> I[Git Checkpoint + Push]
```

Key design choice:
- the build team thinks in multiple roles
- unattended execution stays serialized by default
- one primary slice per cycle keeps repo changes understandable

## Data And Artifact Philosophy

This repository prefers:
- explicit artifacts over hidden memory
- state transitions over vague narrative progress
- machine-readable handoffs plus human-readable companion files

The product runtime now has an explicit bootstrap layer under `job_hunt_copilot/`:
- repo-path helpers for the current-build layout
- canonical DB migrations and review views for `job_hunt_copilot.db`
- shared canonical ID and lifecycle timestamp helpers for downstream records
- shared artifact contract writers and `artifact_records` registration helpers
- supervisor control-state helpers for `agent_control_state`, `pipeline_runs`, `supervisor_cycles`, and `agent_runtime_leases`
- a bounded supervisor cycle executor that acquires the canonical lease, selects one work unit, persists a context snapshot, and records auto-pause or escalation outcomes through canonical incidents
- expert review packet generation under `ops/review-packets/`, canonical `expert_review_packets` and `expert_review_decisions`, and override audit history through `override_events`
- generated runtime self-awareness artifacts under `ops/agent/` for identity, policies, action catalog, service goals, escalation policy, progress log, ops plan, and bootstrap prompts
- local supervisor launchd materialization under `ops/launchd/` plus repo-local `jhc-agent-start`, `jhc-agent-stop`, `jhc-agent-cycle`, and `jhc-chat` wrappers for start/stop, one-shot heartbeat execution, and the expert chat entrypoint
- canonical chat-session bookkeeping that records active-session state, pauses autonomous work on chat open, and resumes on clean explicit close while preserving non-chat pause conditions
- bootstrap checks for assets and local secret materialization
- repo-local runtime directory creation for downstream components
- manual LinkedIn intake helpers that ingest `paste/paste.txt` or browser-style capture bundles into canonical lead workspaces, persist `capture-bundle.json`, and register the lead raw-source artifact in canonical state
- a deterministic manual-lead split pipeline that derives `post.md`, `jd.md`, and `poster-profile.md` when evidence exists, writes `source-split.yaml` plus `source-split-review.yaml`, and publishes a blocked-or-ready `lead-manifest.yaml` for manual leads
- manual lead materialization helpers that create canonical `job_postings`, poster `contacts`, `linkedin_lead_contacts`, and `job_posting_contacts`, then upgrade `lead-manifest.yaml` with created entity ids plus `resume_tailoring` handoff readiness
- refresh-in-place manual lead updates that replace the live source workspace while snapshotting prior source or review artifacts under each lead-local `history/` directory for auditability
- Gmail alert intake helpers that persist `email.md`, `email.json`, and `job-cards.json` under `linkedin-scraping/runtime/gmail/`, prefer the plain-text LinkedIn digest for multi-card parsing, fall back to HTML-derived text only when the plain-text body is unusable, retain zero-card threshold metadata for later review surfaces, dedupe by `job_id` or normalized LinkedIn job URL fallback, merge multiple JD candidates into canonical `jd.md` with LinkedIn conflict precedence, and fan out parsed cards into canonical lead workspaces with `alert-email.md`, `alert-card.json`, `jd-fetch.json`, `lead-manifest.yaml`, plus honest review-blocked or `blocked_no_jd` handoff state when identity or JD recovery issues remain
- Resume Tailoring eligibility, lifecycle, workspace-bootstrap, intelligence-generation, finalize, and mandatory-review helpers that evaluate the persisted posting-linked `jd.md`, write `applications/{company}/{role}/eligibility.yaml`, register that artifact in canonical metadata, mark hard-ineligible postings honestly, create or reuse the active `resume_tailoring_runs` row, materialize the per-posting workspace with `meta.yaml`, mirrored context files, `resume.tex`, `scope-baseline.resume.tex`, and Step 3 through Step 7 artifacts, generate deterministic JD-signal and evidence-mapping outputs from the persisted `jd.md` plus master profile, enforce scope against the baseline snapshot before apply, compile `Achyutaram Sonti.pdf`, verify one-page output with `pdfinfo`, persist mandatory review decisions as first-class artifacts, transition approved runs into `requires_contacts` or `ready_for_outreach`, record owner overrides with prior-decision context in `override_events`, and snapshot prior run workspaces before retailoring so historical run rows keep immutable references
- initial discovery helpers under `job_hunt_copilot.email_discovery` that bootstrap strictly from approved `requires_contacts` postings, resolve Apollo company identity when available, run a broad company-scoped people search, persist `people_search_result.json` with the full candidate list and applied filters, cap the first enrichment shortlist at 6 contacts across recruiter, manager-adjacent, and engineer buckets, and materialize canonical shortlist contacts plus `job_posting_contacts` only for the selected candidates while promoting reused `identified` links into `shortlisted`

Important artifact families:
- `lead-manifest.yaml`
- `capture-bundle.json`
- `eligibility.yaml`
- `meta.yaml`
- `people_search_result.json`
- `recipient_profile.json`
- `discovery_result.json`
- `send_result.json`
- `delivery_outcome.json`
- review packets and maintenance artifacts under `ops/`

## Repository Structure

```mermaid
flowchart LR
    A[prd/] --> A1[spec.md]
    A --> A2[test-spec.feature]
    B[job_hunt_copilot/] --> B1[bootstrap]
    B --> B2[db migrations + record helpers]
    C[build-agent/] --> C1[team roles]
    C --> C2[state]
    C --> C3[bin + scripts + launchd]
    D[docs/] --> D1[architecture]
    D --> D2[Q&A]
    E[assets/] --> E1[resume tailoring]
    E --> E2[outreach]
```

## What To Read Next

- [README.md](../README.md) for the repo-level summary
- [prd/spec.md](../prd/spec.md) for the full system contract
- [build-agent/README.md](../build-agent/README.md) for the unattended build system
