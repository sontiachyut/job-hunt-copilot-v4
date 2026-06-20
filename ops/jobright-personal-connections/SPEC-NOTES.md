# Jobright Spec Notes

## Purpose

This note captures the Jobright research conclusions in a spec-ready form so the future `prd/spec.md` update can reuse the validated findings directly instead of reconstructing them from terminal history.

## What Is Proven

### Public Jobright job pages are rich

For public Jobright job pages, deterministic extraction is already possible for:

- job title
- company
- location
- salary
- job description content
- skills and job metadata
- public `socialConnections`

Evidence:

- [20260618-otter/public-page-extraction.json](/Users/achyutaramsonti/Projects/job-hunt-copilot-v4/ops/jobright-personal-connections/20260618-otter/public-page-extraction.json:1)

### Personalized connections exist in the logged-in page payload

Jobright exposes personalized connection data in `personalSocialConnections` when the signed-in user has matches for that role.

Evidence:

- [20260618-otter/comet-authenticated-session-observed.json](/Users/achyutaramsonti/Projects/job-hunt-copilot-v4/ops/jobright-personal-connections/20260618-otter/comet-authenticated-session-observed.json:1)
- [20260618-otter/comet-cookie-replay-extraction.json](/Users/achyutaramsonti/Projects/job-hunt-copilot-v4/ops/jobright-personal-connections/20260618-otter/comet-cookie-replay-extraction.json:1)

### MCP / Computer Use are not required

The current proven extraction path does not require:

- MCP
- Computer Use
- fresh automated browser login

Instead, it reuses an existing logged-in Comet session by:

1. reading the Comet browser profile
2. reading the `Comet Safe Storage` key from macOS Keychain
3. decrypting the Jobright `SESSION_ID` cookie
4. replaying the Jobright request with plain Python HTTP
5. parsing `personalSocialConnections` from the returned payload

Evidence:

- [jobright_extract_from_comet_session.py](/Users/achyutaramsonti/Projects/job-hunt-copilot-v4/scripts/ops/jobright_extract_from_comet_session.py:1)

### Fresh automated SSO login is not a dependable base path

The school-backed SSO flow blocked automated fresh login in browser automation. That means the steady-state system should not depend on scripted login.

Instead, the correct operational model is:

- user logs into Jobright normally in Comet
- extractor reuses that existing session until it expires
- user refreshes login occasionally when needed

## Proven Operational Model

### Deterministic when data is present

If Jobright is actually returning personalized connections for the signed-in session on a given job page, the current Python path can fetch them deterministically.

That means:

- the browser session is valid
- the `SESSION_ID` cookie can be replayed
- the returned page payload includes `personalSocialConnections`
- the extractor reads it without UI automation

### Optional per job

Personalized connections are **not guaranteed** on every job.

The mechanism is stable, but the presence of matches is job-dependent.

Evidence from the recommendation batch:

- [20260620-recommendation-samples/summary.json](/Users/achyutaramsonti/Projects/job-hunt-copilot-v4/ops/jobright-personal-connections/20260620-recommendation-samples/summary.json:1)

Results from the tested 7-job recommendation batch:

- `7 / 7` jobs exposed public `social_connections`
- `2 / 7` jobs exposed non-empty `personal_social_connections`
- `5 / 7` jobs returned no personalized matches for this user

So in the system design:

- empty `personal_social_connections` is a valid result
- it should not be treated as extractor failure

## Recommendation Feed Finding

The signed-in Jobright recommendations page is not fully server-rendered with visible job links in initial HTML.

The recommendation jobs are loaded client-side, and a live network request was observed:

- `https://jobright.ai/swan/recommend/list/jobs?refresh=true&sortCondition=0&position=0&count=10&syncRerank=false`

This means the future recommendation ingestor can likely use one of two paths:

1. browser-rendered page flow to collect recommendation job URLs
2. direct authenticated replay of the recommendation feed request

The second path is likely better if we confirm its request contract and response schema.

## Recommended Spec Decisions

When Jobright is incorporated into the product spec, the system should model it as:

- `lead discovery source`
- `ranking/enrichment source`
- `authenticated optional personalization source`

It should **not** be modeled as:

- the final authoritative employer posting source
- a guaranteed source of personalized connections on every job
- a zero-maintenance background login flow

## Recommended Runtime Shape

### Core ingest

Use Jobright for:

- recommendation job discovery
- JD enrichment
- public `socialConnections`

### Authenticated enrichment

Use the Comet-session replay path for:

- `personalSocialConnections.school`
- `personalSocialConnections.company`

### Session handling

Assume:

- normal runs are automated
- session refresh is manual
- login expiry is an operational event, not a product failure

## Suggested Data Model Inputs

A future Jobright ingestion spec should account for:

- `jobright_job_url`
- `jobright_job_id`
- `jobright_job_summary`
- `jobright_social_connections`
- `jobright_personal_social_connections`
- `jobright_enrichment_status`
- `jobright_session_source = comet`
- `jobright_personalization_available = true|false`

## Current Reference Artifacts

- Single-job proof:
  - [20260618-otter/README.md](/Users/achyutaramsonti/Projects/job-hunt-copilot-v4/ops/jobright-personal-connections/20260618-otter/README.md:1)
- Cookie replay proof:
  - [20260618-otter/comet-cookie-replay-extraction.json](/Users/achyutaramsonti/Projects/job-hunt-copilot-v4/ops/jobright-personal-connections/20260618-otter/comet-cookie-replay-extraction.json:1)
- Recommendation batch proof:
  - [20260620-recommendation-samples/README.md](/Users/achyutaramsonti/Projects/job-hunt-copilot-v4/ops/jobright-personal-connections/20260620-recommendation-samples/README.md:1)
  - [20260620-recommendation-samples/summary.json](/Users/achyutaramsonti/Projects/job-hunt-copilot-v4/ops/jobright-personal-connections/20260620-recommendation-samples/summary.json:1)
- Reusable scripts:
  - [jobright_extract_from_comet_session.py](/Users/achyutaramsonti/Projects/job-hunt-copilot-v4/scripts/ops/jobright_extract_from_comet_session.py:1)
  - [jobright_extract_connections.py](/Users/achyutaramsonti/Projects/job-hunt-copilot-v4/scripts/ops/jobright_extract_connections.py:1)
  - [jobright_attach_cdp_session.py](/Users/achyutaramsonti/Projects/job-hunt-copilot-v4/scripts/ops/jobright_attach_cdp_session.py:1)

## Immediate Next Step

The next spec-adjacent technical step should be:

1. formalize the Jobright ingestion contract
2. decide whether recommendation discovery will use:
   - the observed `/swan/recommend/list/jobs` feed
   - or browser-rendered page enumeration
3. define how Jobright-enriched jobs reconcile with canonical employer/ATS sources
