# Jobright Recommendation Batch Sample

## Goal

Verify whether the Comet-session replay extractor works across multiple Jobright recommendation jobs, not just the original Otter sample.

Source surface:

- Recommendations page: `https://jobright.ai/jobs/recommend`
- Recommendation feed observed in page-network activity:
  - `https://jobright.ai/swan/recommend/list/jobs?refresh=true&sortCondition=0&position=0&count=10&syncRerank=false`

## What Was Tested

The signed-in recommendations page rendered `7` visible job-detail links during this sample run.

Each of those job URLs was fetched with:

- `scripts/ops/jobright_extract_from_comet_session.py`
- the logged-in Comet session replay path
- no MCP
- no Computer Use
- no fresh browser login

Saved files:

- `summary.json`
- one per-job JSON file for each sampled recommendation

## Results

Summary from the 7 recommendation jobs:

- `7 / 7` fetched successfully
- `7 / 7` exposed public `social_connections`
- `2 / 7` exposed non-empty `personal_social_connections`
- `5 / 7` had no personalized matches for this user on that specific role

Jobs with personalized matches:

- `Ivo` — `Software Engineer`
  - school matches: `2`
  - names: `Caitlan R.`, `Rebecca Lynn Baldwin`

- `Ridgeline` — `Software Engineer, Migrations Engineering`
  - school matches: `1`
  - company matches: `1`
  - names: `Chelsea Enea`, `Adithya Nagaraj Tirumale`

Jobs without personalized matches in this sample:

- `Reducto` — `Backend/AI Engineer`
- `Kensho Technologies` — `Software Engineer II`
- `Pave` — `Software Engineer - Core Platform`
- `Delart` — `Staff Software Engineers`
- `AAMVA (American Association of Motor Vehicle Administrators)` — `Software Engineer-Data Engineering, Machine Learning (ML)`

## Conclusion

The extraction mechanism is reusable across recommendation jobs.

The important distinction is:

- the **mechanism** works broadly across recommendation pages
- the **presence of personalized matches** is job-dependent

So for system design:

- we can programmatically process recommendation jobs in batch
- we should treat `personal_social_connections` as optional enrichment
- empty personalized blocks are a normal outcome, not an extraction failure
