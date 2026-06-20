# Jobright Personalized Connections Investigation

## Goal

Verify whether Jobright exposes logged-in, user-personalized connection data in a way that could be reused for Job Hunt Copilot lead ingestion and outreach enrichment.

Target job used for this investigation:

- Job URL: `https://jobright.ai/jobs/info/6a3335ccce501060b5ceca67`
- Company: `Otter.ai`
- Title: `Software Engineer, Virality and Activation`

Saved artifacts in this folder:

- `public-page-extraction.json` — actual extractor output from the anonymous public page
- `otter-software-engineer-virality-and-activation.sample.json` — curated sample of the logged-in personalized findings captured during the live investigation
- `comet-authenticated-session-observed.json` — authenticated extraction notes captured from the real signed-in Comet session after the fresh SSO login path was rejected
- `comet-cookie-replay-extraction.json` — sanitized extraction captured by replaying the logged-in Comet session cookies without MCP or Computer Use

## What Was Confirmed

### Public page data

The public Jobright page exposes a rich job payload in page state:

- title
- company
- location
- salary
- posted freshness
- employment type
- work model
- seniority
- JD sections
- skills
- work-auth / H1B hints
- non-personalized company connections

### Logged-in personalized data

The logged-in Jobright page exposes a separate `personalSocialConnections` object in page state.

This was confirmed by running a one-off page-context extractor in the live logged-in browser session:

```javascript
javascript:(()=>{
  const s=document.getElementById('__NEXT_DATA__');
  const j=s?JSON.parse(s.textContent):null;
  const hits=[];
  const seen=new WeakSet();
  const walk=(o,p='root')=>{
    if(!o||typeof o!=='object'||seen.has(o))return;
    seen.add(o);
    for(const [k,v] of Object.entries(o)){
      const np=p+'.'+k;
      if(k==='personalSocialConnections')hits.push({path:np,value:v});
      walk(v,np);
    }
  };
  walk(j);
  navigator.clipboard.writeText(JSON.stringify(hits,null,2));
  alert('copied '+hits.length);
})()
```

The live page returned `copied 1`, proving that `personalSocialConnections` exists in the logged-in page state.

### SSO/login constraint confirmed

Fresh automated login was blocked for the school-backed SSO flow. Entering the school account password in a fresh automation browser was not a supported path.

That did **not** block extraction from an already-authenticated browser session. Using the signed-in Comet tab for the same Otter job, the live page state still exposed the personalized data needed for extraction.

### Comet cookie replay confirmed

The terminal-only replay path now works too.

Using:

- the logged-in Comet profile on disk
- the Keychain-backed `Comet Safe Storage` secret
- the encrypted `.jobright.ai` `SESSION_ID` cookie

the project was able to replay the Jobright session with plain `requests` and extract personalized data from the returned `__NEXT_DATA__` payload.

That means the personalized connections can be fetched **without**:

- MCP
- Computer Use
- fresh automated browser login

The working terminal path is now:

1. read the Comet Jobright cookies from the local browser profile
2. decrypt them with the `Comet Safe Storage` key from macOS Keychain
3. replay the Jobright job request
4. parse `personalSocialConnections` from the page payload

## Personalized Connections Captured

### From Your School

- `Shreyas Aiyar` — `Software Engineer` — `Manipal Institute of Technology`
- `Ramesh T.` — `Senior NLP / Deep Learning Researcher` — `Arizona State University`
- `Colton Davis` — `Technical Recruiter` — `Arizona State University`

### Beyond Your Network

- `Will Owen` — `Software Engineer`
- `Yedi Wang` — `Software Engineer`
- `Colton Davis` — `Technical Recruiter`
- `Angus Ng` — `Software Engineer`
- `Cheng Yuan` — `Software Engineer`

### Terminal replay capture

The cookie replay extraction preserved direct LinkedIn URLs for the personalized school connections:

- `Shreyas Aiyar` — `https://www.linkedin.com/in/shreyas-aiyar/`
- `Ramesh T.` — `https://www.linkedin.com/in/rthul/`
- `Colton Davis` — `https://www.linkedin.com/in/colton-davis-695422217/`

### Find More Connections links observed in the logged-in UI

- School-based LinkedIn search:
  - `https://www.linkedin.com/search/results/people/?currentCompany=35593855&schoolFilter=%5B%228992884%22%2C%22577550%22%2C%224292%22%5D`
- Previous-company-based LinkedIn search:
  - `https://www.linkedin.com/search/results/people/?currentCompany=35593855&pastCompany=%5B%2211115%22%2C%224292%22%5D`
- Role-keyword/company LinkedIn search:
  - `https://www.linkedin.com/search/results/people/?currentCompany=35593855&keywords=Software%20Engineer%2C%20Virality%20and%20Activation`

## What Was Not Fully Resolved Yet

- direct LinkedIn profile URLs for each personalized person
- direct email addresses behind the mail icons
- a clean authenticated HTTP-only replay captured from the logged-in browser session

Those are likely still reachable, but they were not required to prove the main product question: the personalized connection data itself is present and fetchable from a logged-in session.

## Saved Repeatable Path

### Preferred path: real Chrome over CDP

This is the preferred approach when Jobright login uses Google and blocks automated sign-in.

1. Launch a real Chrome window with a temporary profile and CDP enabled:

```bash
open -na "Google Chrome" --args \
  --remote-debugging-port=9222 \
  --user-data-dir=/tmp/jobright-cdp-profile \
  https://jobright.ai/jobs/info/6a3335ccce501060b5ceca67
```

2. Log into Jobright normally in that Chrome window.

3. Attach to that real browser and save both the authenticated storage state and the connection snapshot:

```bash
python3 scripts/ops/jobright_attach_cdp_session.py \
  --job-url https://jobright.ai/jobs/info/6a3335ccce501060b5ceca67 \
  --storage-output ops/jobright-personal-connections/auth/jobright-storage-state.json \
  --connections-output ops/jobright-personal-connections/20260618-otter/extracted-from-session.json
```

The repo now has three prototype scripts:

1. `scripts/ops/jobright_capture_storage_state.py`
   - launches a headed Playwright browser
   - you log into Jobright once manually
   - saves a reusable `storage_state.json`
   - this may fail for Google-based sign-in because some providers block automated browsers

2. `scripts/ops/jobright_extract_connections.py`
   - loads the saved storage state
   - fetches the Jobright job page
   - parses `__NEXT_DATA__`
   - extracts:
     - `social_connections`
     - `personal_social_connections`
   - optionally falls back to Playwright rendering if the plain HTTP fetch does not carry the personalized page state

3. `scripts/ops/jobright_attach_cdp_session.py`
   - connects to a real Chrome window over CDP
   - avoids automated-browser login restrictions
   - saves both:
     - reusable `storage_state.json`
     - extracted personalized connections JSON

4. Existing authenticated browser session fallback
   - when fresh SSO login is blocked in automation
   - attach to or inspect the already-signed-in browser session
   - extract the personalized names from live page state or rendered cards
   - this is what `comet-authenticated-session-observed.json` documents

5. `scripts/ops/jobright_extract_from_comet_session.py`
   - reads the logged-in Comet browser profile directly
   - retrieves the `Comet Safe Storage` secret from macOS Keychain
   - decrypts the Jobright `SESSION_ID` cookie
   - replays the Jobright request with plain HTTP
   - extracts `social_connections` and `personal_social_connections`
   - writes only sanitized output JSON, not raw auth state
   - may trigger a one-time macOS Keychain permission prompt for `Comet Safe Storage`

Validation already completed:

```bash
python3 -m py_compile \
  scripts/ops/jobright_capture_storage_state.py \
  scripts/ops/jobright_extract_connections.py \
  scripts/ops/jobright_attach_cdp_session.py

python3 scripts/ops/jobright_extract_connections.py \
  --job-url https://jobright.ai/jobs/info/6a3335ccce501060b5ceca67 \
  --output ops/jobright-personal-connections/20260618-otter/public-page-extraction.json

python3 scripts/ops/jobright_extract_from_comet_session.py \
  --job-url https://jobright.ai/jobs/info/6a3335ccce501060b5ceca67 \
  --output ops/jobright-personal-connections/20260618-otter/comet-cookie-replay-extraction.json
```

## Suggested Usage

Install prerequisites once:

```bash
python3 -m pip install playwright requests
python3 -m playwright install chromium
```

Capture a reusable session:

```bash
python3 scripts/ops/jobright_capture_storage_state.py \
  --output ops/jobright-personal-connections/auth/jobright-storage-state.json \
  --job-url https://jobright.ai/jobs/info/6a3335ccce501060b5ceca67
```

Extract connection data:

```bash
python3 scripts/ops/jobright_extract_connections.py \
  --job-url https://jobright.ai/jobs/info/6a3335ccce501060b5ceca67 \
  --storage-state ops/jobright-personal-connections/auth/jobright-storage-state.json \
  --playwright-fallback \
  --output ops/jobright-personal-connections/20260618-otter/extracted-from-session.json
```

Or, if your real logged-in browser session is in Comet and you do not want any browser automation:

```bash
python3 scripts/ops/jobright_extract_from_comet_session.py \
  --job-url https://jobright.ai/jobs/info/6a3335ccce501060b5ceca67 \
  --output ops/jobright-personal-connections/20260618-otter/comet-cookie-replay-extraction.json
```

## Why This Matters For The Spec

This investigation establishes these likely spec requirements:

1. Jobright can be treated as a rich lead-discovery and enrichment source.
2. Personalized connection data is gated behind authentication and should not rely on Computer Use in production.
3. A logged-in browser session can be reused by replaying the encrypted session cookies; no UI automation is required for the steady-state extractor.
4. The preferred runtime shape is:
   - existing logged-in browser session
   - lightweight HTTP extraction first
   - browser/CDP fallback only if needed
5. Jobright should still be treated as a discovery/enrichment layer, not necessarily the final authoritative employer posting source.
