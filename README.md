# Job Hunt Copilot v4

An autonomous, spec-first job-search system designed to:
- ingest role leads from LinkedIn-style alerts
- tailor a resume to a specific posting
- find internal contacts
- draft and send targeted outreach
- observe delivery outcomes
- operate through a dedicated supervisor agent

## Why This Repo Exists

This repository is the fourth-generation design and build workspace for a serious agentic software project.

The goal is not just to "send job emails."
The goal is to build a reliable autonomous workflow with:
- durable state
- strict handoff contracts
- auditability
- bounded repair and escalation
- human-overseeable control planes

## Current Status

This repo is currently in a **spec-complete, implementation-underway** phase.

What already exists:
- a detailed product specification in [prd/spec.md](./prd/spec.md)
- an acceptance spec in [prd/test-spec.feature](./prd/test-spec.feature)
- an autonomous operations-agent design
- an unattended multi-agent build system scaffold under [build-agent/](./build-agent/)
- a foundation runtime bootstrap package for support-directory setup, secret materialization, and DB migration scaffolding
- a canonical SQLite schema migration set with review views plus shared ID and timestamp helpers for downstream components
- shared artifact publication helpers for YAML/JSON contracts, canonical workspace path building, and `artifact_records` registration
- supervisor control-plane persistence helpers for canonical control state, pipeline runs, supervisor cycles, and runtime leases
- a bounded supervisor cycle executor with incident-aware work selection, cycle snapshots, lease-guarded single-flight execution, and auto-pause or escalation handling for unsupported progression
- persisted expert review packets, expert review decisions, and override audit events with filesystem review-packet artifacts under `ops/review-packets/`
- a generated product-side runtime pack under `ops/agent/` with identity, policy, action-catalog, service-goal, escalation, progress-log, ops-plan, and bootstrap prompt surfaces
- repo-local supervisor launchd wiring under `ops/launchd/` plus `bin/jhc-agent-start`, `bin/jhc-agent-stop`, `bin/jhc-agent-cycle`, and `bin/jhc-chat` for local heartbeat and operator control
- the manual-ingestion and materialization slices under `job_hunt_copilot.linkedin_scraping`, including `bin/jhc-linkedin-ingest`, canonical lead workspace creation, `capture-bundle.json`, deterministic `post.md` / `jd.md` / `poster-profile.md` derivation, `source-split.yaml`, `source-split-review.yaml`, blocked-or-ready `lead-manifest.yaml` publication, and canonical `job_postings` / poster-contact link creation for reviewed manual leads

What is still in progress:
- Gmail lead intake, manual refresh-history snapshotting, and the later runtime components on top of the now-landed local operator plus manual-ingestion, split-review, and manual materialization entrypoints

## System Overview

```mermaid
flowchart LR
    A[LinkedIn / Gmail Lead Intake] --> B[Canonical Lead + JD Artifacts]
    B --> C[Resume Tailoring]
    C --> D[Agent Review Gate]
    D --> E[People Search + Enrichment]
    E --> F[Email Discovery]
    F --> G[Drafting + Sending]
    G --> H[Delivery Feedback]

    I[Supervisor Agent] --> A
    I --> C
    I --> E
    I --> G
    I --> H

    J[Expert via Chat] --> I
```

A more detailed view is in [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md).

## Why It Is Interesting

From a software-engineering perspective, this project is about:
- translating a complex operational workflow into explicit state machines
- using artifact contracts instead of vague agent memory
- separating a runtime ops agent from a build agent
- designing bounded autonomy instead of uncontrolled automation
- building systems that can recover, explain themselves, and be reviewed

## Repository Map

```text
.
├── prd/          Product spec and acceptance spec
├── job_hunt_copilot/  Product runtime bootstrap, schema, and persistence scaffolding
├── build-agent/  Long-run Codex build control plane
├── docs/         Human-readable architecture and repo explanation
├── assets/       Source assets for tailoring and outreach
├── tests/        Bootstrap and runtime validation
└── secrets/      Local runtime secrets (ignored from git)
```

## Key Documents

- [Product Specification](./prd/spec.md)
- [Acceptance Specification](./prd/test-spec.feature)
- [Architecture Overview](./docs/ARCHITECTURE.md)
- [Agent Autonomy Q&A](./docs/agent-autonomy-qna.md)
- [Build Agent Guide](./build-agent/README.md)

## For Recruiters And Engineering Managers

If you want the shortest path through this repo:
1. read this file
2. open [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md)
3. skim [prd/spec.md](./prd/spec.md) for the system depth
4. inspect [build-agent/](./build-agent/) for how the build itself is being automated

The most important engineering ideas here are:
- spec-first development
- agentic control planes with safety boundaries
- explicit operational state
- human-reviewable autonomous systems

## Build Philosophy

This repository is intentionally being built in a way that is itself part of the project:
- the runtime product has an autonomous supervisor-agent design
- the implementation process also has a long-run Codex build agent
- both are designed around durable state, fresh-session recovery, and bounded work units

## Notes

- Local secrets are intentionally excluded from version control.
- Generated runtime state for the build agent is intentionally excluded from version control.
- This README is meant to stay concise and navigable; deeper detail belongs in the linked docs.
