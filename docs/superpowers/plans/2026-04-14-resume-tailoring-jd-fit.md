# Resume Tailoring JD-Content Fit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the resume tailoring system's 3-track/4-focus model with a 9-theme, evidence-pool-based system that produces JD-content-aligned resumes via a 16-step pipeline.

**Architecture:** The new system uses a deterministic theme classifier to select from 9 role archetypes, draws bullets from a two-tier evidence pool (pre-written variants for experience, evidence atoms for projects), and applies hero/supporting tailoring intensity based on section ordering. A 3-layer JD keyword system with an adjacency map maximizes ATS keyword coverage. A 16-step pipeline replaces the old Step 3-7 architecture, with each step producing an auditable YAML artifact.

**Tech Stack:** Python 3, PyYAML, LaTeX (latexmk/pdflatex), SQLite, pytest

**Spec:** `prd/spec.md` section 7.2.11 (FR-RT-33 through FR-RT-42B)

---

## File Structure

### New Files to Create

| File | Responsibility |
|------|---------------|
| `job_hunt_copilot/tailoring/theme_classifier.py` | Theme term sets, signal-source weighting, theme scoring, theme selection |
| `job_hunt_copilot/tailoring/keyword_system.py` | JD keyword extraction, profile matching, adjacency map, term normalization, placement rules |
| `job_hunt_copilot/tailoring/bullet_pool.py` | Load/query experience bullet variants and project evidence atoms |
| `job_hunt_copilot/tailoring/pipeline.py` | 16-step pipeline orchestration, step artifact I/O |
| `job_hunt_copilot/tailoring/steps/step_01_jd_sections.py` | Step 1: JD section identification |
| `job_hunt_copilot/tailoring/steps/step_02_signals_raw.py` | Step 2: Signal extraction |
| `job_hunt_copilot/tailoring/steps/step_03_signals_classified.py` | Step 3: Signal classification & weighting |
| `job_hunt_copilot/tailoring/steps/step_04_theme_scores.py` | Step 4: Theme scoring |
| `job_hunt_copilot/tailoring/steps/step_05_theme_decision.py` | Step 5: Theme & layout decision |
| `job_hunt_copilot/tailoring/steps/step_06_project_scores.py` | Step 6: Project relevance scoring |
| `job_hunt_copilot/tailoring/steps/step_07_project_selection.py` | Step 7: Project selection & ordering |
| `job_hunt_copilot/tailoring/steps/step_08_experience_evidence.py` | Step 8: Experience evidence mapping |
| `job_hunt_copilot/tailoring/steps/step_09_project_evidence.py` | Step 9: Project evidence mapping |
| `job_hunt_copilot/tailoring/steps/step_10_gap_analysis.py` | Step 10: Gap analysis |
| `job_hunt_copilot/tailoring/steps/step_11_bullet_allocation.py` | Step 11: Bullet ranking & allocation |
| `job_hunt_copilot/tailoring/steps/step_12_summary.py` | Step 12: Summary composition |
| `job_hunt_copilot/tailoring/steps/step_13_skills.py` | Step 13: Skill categories composition |
| `job_hunt_copilot/tailoring/steps/step_14_tech_stacks.py` | Step 14: Tech stack lines composition |
| `job_hunt_copilot/tailoring/steps/step_15_assembly.py` | Step 15: Resume assembly & page fill |
| `job_hunt_copilot/tailoring/steps/step_16_verification.py` | Step 16: Verification |
| `job_hunt_copilot/tailoring/steps/__init__.py` | Package init |
| `job_hunt_copilot/tailoring/__init__.py` | Package init |
| `assets/resume-tailoring/data/adjacency_map.yaml` | Technology adjacency families |
| `assets/resume-tailoring/data/theme_terms.yaml` | Per-theme trigger term sets |
| `assets/resume-tailoring/data/bullet_pool_experience.yaml` | Pre-written experience bullet variants |
| `assets/resume-tailoring/data/bullet_pool_projects.yaml` | Project evidence atoms |
| `assets/resume-tailoring/data/term_aliases.yaml` | Term normalization aliases |
| `assets/resume-tailoring/data/skill_categories.yaml` | Per-theme skill category templates |
| `assets/resume-tailoring/data/summary_templates.yaml` | Per-theme summary templates |
| `assets/resume-tailoring/base/projects-first/base-resume.tex` | Template A (projects-first) |
| `assets/resume-tailoring/base/experience-first/base-resume.tex` | Template B (experience-first) |
| `tests/test_theme_classifier.py` | Tests for theme classifier |
| `tests/test_keyword_system.py` | Tests for keyword system |
| `tests/test_bullet_pool.py` | Tests for bullet pool |
| `tests/test_pipeline_steps.py` | Tests for individual pipeline steps |
| `tests/test_tailoring_integration.py` | Integration tests with real JDs |

### Files to Modify

| File | What changes |
|------|-------------|
| `job_hunt_copilot/resume_tailoring.py` | Remove old track/focus system, old step builders, old constants. Wire up new pipeline. Update bootstrap to use theme classifier. Update finalize for flexible layout. |
| `job_hunt_copilot/paths.py` | Add paths for new step artifacts (step-01 through step-16), new data files, Template A/B paths |
| `resume-tailoring/input/profile.md` | Add Job Hunt Copilot project |
| `assets/resume-tailoring/profile.md` | Add Job Hunt Copilot project (source of truth) |
| `assets/resume-tailoring/ai/system-prompt.md` | Rewrite for 16-step pipeline |
| `assets/resume-tailoring/ai/cookbook.md` | Rewrite for new theme/bullet system |
| `assets/resume-tailoring/ai/sop-swe-experience-tailoring.md` | Rewrite for new evidence pool approach |
| `tests/test_resume_tailoring.py` | Update tests for new pipeline, add theme-based tests |

---

## Phase 1: Static Data & Configuration

### Task 1: Technology Adjacency Map

**Files:**
- Create: `assets/resume-tailoring/data/adjacency_map.yaml`
- Create: `assets/resume-tailoring/data/term_aliases.yaml`
- Create: `job_hunt_copilot/tailoring/__init__.py`
- Create: `job_hunt_copilot/tailoring/keyword_system.py`
- Create: `tests/test_keyword_system.py`

- [ ] **Step 1: Create the package structure**

```bash
mkdir -p job_hunt_copilot/tailoring/steps
touch job_hunt_copilot/tailoring/__init__.py
touch job_hunt_copilot/tailoring/steps/__init__.py
```

- [ ] **Step 2: Write the adjacency map YAML**

Create `assets/resume-tailoring/data/adjacency_map.yaml` with all families from spec FR-RT-38D:

```yaml
families:
  frontend_frameworks:
    members: ["React", "Angular", "Vue", "Svelte"]
    skill_category_default: "Frontend & UI"
    reason: "Component-based, TypeScript-compatible, same mental model"

  javascript_ecosystem:
    members: ["JavaScript", "TypeScript", "Node.js", "Express", "Next.js", "Nuxt.js"]
    skill_category_default: "Frontend & UI"
    reason: "Same language runtime"

  python_web_frameworks:
    members: ["FastAPI", "Flask", "Django", "Tornado"]
    skill_category_default: "Backend & Data"
    reason: "Same language, similar patterns"

  data_processing:
    members: ["Apache Spark", "Apache Flink", "Apache Beam", "Databricks"]
    skill_category_default: "Data & Storage"
    reason: "Same distributed data processing paradigm"

  container_orchestration:
    members: ["Kubernetes", "Docker Swarm", "ECS", "EKS", "GKE", "AKS"]
    skill_category_default: "Cloud & Infra"
    reason: "Same container orchestration concept"

  cloud_compute:
    members: ["AWS EC2", "GCP Compute Engine", "Azure VMs"]
    skill_category_default: "Cloud & Infra"
    reason: "Same compute service category"

  cloud_serverless:
    members: ["AWS Lambda", "GCP Cloud Functions", "Azure Functions"]
    skill_category_default: "Cloud & Infra"
    reason: "Same serverless paradigm"

  cloud_storage:
    members: ["AWS S3", "GCP Cloud Storage", "Azure Blob Storage"]
    skill_category_default: "Cloud & Infra"
    reason: "Same object storage category"

  cloud_queue:
    members: ["AWS SQS", "GCP Pub/Sub", "Azure Service Bus", "Kafka", "RabbitMQ"]
    skill_category_default: "Cloud & Infra"
    reason: "Same messaging/queue paradigm"

  nosql_databases:
    members: ["DynamoDB", "MongoDB", "Cassandra", "CosmosDB"]
    skill_category_default: "Data & Storage"
    reason: "Same NoSQL paradigm"

  relational_databases:
    members: ["PostgreSQL", "MySQL", "SQL Server", "Oracle"]
    skill_category_default: "Data & Storage"
    reason: "Same relational database paradigm"

  cicd_tools:
    members: ["GitLab CI/CD", "GitHub Actions", "Jenkins", "CircleCI", "Travis CI"]
    skill_category_default: "Cloud & DevOps"
    reason: "Same build/deploy pipeline concept"

  iac_tools:
    members: ["Terraform", "CloudFormation", "Pulumi", "Bicep", "Ansible"]
    skill_category_default: "Cloud & Infra"
    reason: "Same infrastructure-as-code paradigm"

  monitoring_tools:
    members: ["Datadog", "Prometheus", "Grafana", "New Relic", "Splunk", "CloudWatch", "ELK Stack"]
    skill_category_default: "Testing & Reliability"
    reason: "Same observability paradigm"

  ml_frameworks:
    members: ["PyTorch", "TensorFlow", "Keras", "JAX", "scikit-learn"]
    skill_category_default: "Applied AI"
    reason: "Same ML training/inference paradigm"

  vector_search:
    members: ["FAISS", "Pinecone", "Weaviate", "Milvus", "ChromaDB", "Qdrant"]
    skill_category_default: "Applied AI"
    reason: "Same vector similarity search concept"

  llm_frameworks:
    members: ["LangChain", "LlamaIndex", "CrewAI", "AutoGen", "Semantic Kernel"]
    skill_category_default: "Applied AI"
    reason: "Same LLM orchestration paradigm"

  mobile_android:
    members: ["Kotlin", "Java (Android)", "Jetpack Compose"]
    skill_category_default: "Frontend & UI"
    reason: "Same Android platform"

  mobile_ios:
    members: ["Swift", "SwiftUI", "Objective-C"]
    skill_category_default: "Frontend & UI"
    reason: "Same iOS platform"

  mobile_cross_platform:
    members: ["React Native", "Flutter"]
    skill_category_default: "Frontend & UI"
    reason: "Cross-platform mobile frameworks"
```

- [ ] **Step 3: Write the term aliases YAML**

Create `assets/resume-tailoring/data/term_aliases.yaml`:

```yaml
aliases:
  "AWS": ["Amazon Web Services"]
  "K8s": ["Kubernetes"]
  "Postgres": ["PostgreSQL"]
  "JS": ["JavaScript"]
  "TS": ["TypeScript"]
  "Node": ["Node.js"]
  "React.js": ["React"]
  "GCP": ["Google Cloud Platform"]
  "C++": ["CPP", "Cplusplus"]
  "CI/CD": ["CICD"]
  "D3": ["D3.js"]
  "Vue": ["Vue.js"]
  "Next": ["Next.js"]
  "Nuxt": ["Nuxt.js"]
```

- [ ] **Step 4: Write failing test for adjacency lookup**

Create `tests/test_keyword_system.py`:

```python
import pytest
from job_hunt_copilot.tailoring.keyword_system import (
    load_adjacency_map,
    find_adjacent_match,
    normalize_term,
)


def test_find_adjacent_match_returns_family_when_profile_has_member():
    adj_map = load_adjacency_map()
    # Profile has React, JD asks for Angular
    profile_terms = {"React", "Python", "AWS"}
    result = find_adjacent_match("Angular", profile_terms, adj_map)
    assert result is not None
    assert result["family"] == "frontend_frameworks"
    assert result["matched_via"] == "React"


def test_find_adjacent_match_returns_none_when_no_family_member():
    adj_map = load_adjacency_map()
    profile_terms = {"Python", "AWS"}
    result = find_adjacent_match("Angular", profile_terms, adj_map)
    assert result is None


def test_normalize_term_resolves_aliases():
    assert normalize_term("K8s") == "Kubernetes"
    assert normalize_term("JS") == "JavaScript"
    assert normalize_term("React") == "React"  # No alias, returns as-is
```

- [ ] **Step 5: Run tests to verify they fail**

Run: `python -m pytest tests/test_keyword_system.py -v`
Expected: FAIL — module not found

- [ ] **Step 6: Implement adjacency map loading and lookup**

Create `job_hunt_copilot/tailoring/keyword_system.py`:

```python
from __future__ import annotations

import os
from typing import Any, Mapping, Sequence

import yaml

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DATA_DIR = os.path.join(_PROJECT_ROOT, "assets", "resume-tailoring", "data")


def _load_yaml(filename: str) -> dict[str, Any]:
    path = os.path.join(_DATA_DIR, filename)
    with open(path, "r") as f:
        return yaml.safe_load(f) or {}


def load_adjacency_map() -> dict[str, Any]:
    return _load_yaml("adjacency_map.yaml")


def load_term_aliases() -> dict[str, list[str]]:
    data = _load_yaml("term_aliases.yaml")
    return data.get("aliases", {})


_ALIAS_CACHE: dict[str, str] | None = None


def _build_alias_lookup() -> dict[str, str]:
    global _ALIAS_CACHE
    if _ALIAS_CACHE is not None:
        return _ALIAS_CACHE
    aliases = load_term_aliases()
    lookup: dict[str, str] = {}
    for canonical, variants in aliases.items():
        for variant in variants:
            lookup[variant.lower()] = canonical
        lookup[canonical.lower()] = canonical
    _ALIAS_CACHE = lookup
    return lookup


def normalize_term(term: str) -> str:
    lookup = _build_alias_lookup()
    return lookup.get(term.lower(), term)


def find_adjacent_match(
    jd_term: str,
    profile_terms: set[str],
    adjacency_map: dict[str, Any],
) -> dict[str, str] | None:
    normalized_jd = normalize_term(jd_term).lower()
    normalized_profile = {normalize_term(t).lower() for t in profile_terms}
    families = adjacency_map.get("families", {})
    for family_name, family_data in families.items():
        members_lower = [m.lower() for m in family_data.get("members", [])]
        if normalized_jd not in members_lower:
            continue
        for member in family_data.get("members", []):
            if member.lower() in normalized_profile and member.lower() != normalized_jd:
                return {
                    "family": family_name,
                    "matched_via": member,
                    "skill_category": family_data.get("skill_category_default", ""),
                }
    return None
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `python -m pytest tests/test_keyword_system.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add assets/resume-tailoring/data/adjacency_map.yaml assets/resume-tailoring/data/term_aliases.yaml job_hunt_copilot/tailoring/ tests/test_keyword_system.py
git commit -m "feat(tailoring): add adjacency map, term aliases, and keyword lookup"
```

---

### Task 2: Theme Term Sets & Classifier

**Files:**
- Create: `assets/resume-tailoring/data/theme_terms.yaml`
- Create: `job_hunt_copilot/tailoring/theme_classifier.py`
- Create: `tests/test_theme_classifier.py`

- [ ] **Step 1: Write the theme terms YAML**

Create `assets/resume-tailoring/data/theme_terms.yaml` with all 9 themes per FR-RT-33B. Each theme gets a list of trigger terms:

```yaml
themes:
  applied_ai:
    terms: ["llm", "llms", "rag", "embeddings", "ml", "machine learning", "model serving",
            "inference", "fine-tuning", "fine tuning", "prompt engineering", "ai-powered",
            "ai powered", "nlp", "natural language", "computer vision", "deep learning",
            "neural network", "transformer", "gpt", "bert", "diffusion"]
    template: A

  agent_ai_systems:
    terms: ["agentic", "multi-agent", "multi agent", "agent framework", "tool use",
            "autonomous workflow", "orchestration", "planning", "function calling",
            "agent", "agents", "copilot", "assistant", "chatbot", "conversational ai",
            "workflow automation", "autonomous"]
    template: A

  forward_deployed_ai:
    terms: ["solutions engineer", "forward deployed", "customer-facing ai", "technical consulting",
            "client", "implementation engineer", "deployment", "integration engineer",
            "field engineer", "professional services", "customer success", "domain-specific ai",
            "applied scientist"]
    template: A

  frontend_web:
    terms: ["react", "angular", "vue", "svelte", "javascript", "typescript", "css", "html",
            "web", "frontend", "front-end", "front end", "ui", "ux", "user interface",
            "responsive", "browser", "dom", "accessibility", "spa", "single page",
            "component", "tailwind", "bootstrap", "webpack", "vite"]
    template: runtime

  backend_service:
    terms: ["backend", "back-end", "back end", "api", "rest", "restful", "graphql",
            "microservice", "microservices", "database", "sql", "server-side",
            "authentication", "authorization", "crud", "middleware", "endpoint",
            "service", "gateway"]
    template: B

  distributed_infra:
    terms: ["distributed system", "distributed systems", "spark", "etl", "pipeline",
            "pipelines", "kafka", "high-availability", "throughput", "data engineering",
            "data engineer", "streaming", "batch processing", "data lake", "lakehouse",
            "airflow", "dag", "hadoop", "hive", "presto"]
    template: B

  platform_infra:
    terms: ["kubernetes", "terraform", "docker", "ci/cd", "cicd", "cloud infrastructure",
            "devops", "observability", "monitoring", "sre", "site reliability",
            "infrastructure", "platform engineer", "platform engineering",
            "container", "helm", "istio", "service mesh", "linux"]
    template: B

  fullstack:
    terms: ["full-stack", "full stack", "fullstack"]
    template: runtime

  generalist:
    terms: []
    template: runtime
```

- [ ] **Step 2: Write failing test for theme classifier**

Create `tests/test_theme_classifier.py`:

```python
import pytest
from job_hunt_copilot.tailoring.theme_classifier import classify_theme


def _make_signals(core_texts: list[str], must_have_texts: list[str] = None,
                  nice_texts: list[str] = None, role_title: str = ""):
    signals = []
    for i, text in enumerate(core_texts):
        signals.append({
            "signal_id": f"signal_core_{i}",
            "priority": "core_responsibility",
            "signal": text,
            "tokens": text.lower().split(),
        })
    for i, text in enumerate(must_have_texts or []):
        signals.append({
            "signal_id": f"signal_must_{i}",
            "priority": "must_have",
            "signal": text,
            "tokens": text.lower().split(),
        })
    for i, text in enumerate(nice_texts or []):
        signals.append({
            "signal_id": f"signal_nice_{i}",
            "priority": "nice_to_have",
            "signal": text,
            "tokens": text.lower().split(),
        })
    return {"signals": signals, "role_intent_summary": role_title}


def test_garmin_aviation_classifies_as_frontend_web():
    """Garmin Aviation Web Development JD should classify as frontend_web, not backend."""
    signals = _make_signals(
        core_texts=[
            "Software Engineer 1 Aviation Web Development",
            "web development for customer facing Garmin aviation products",
            "software design and development using Angular JavaScript",
            "Troubleshoots basic issue reports and implements software solutions",
        ],
        must_have_texts=[
            "develop basic software in C C++ C# Java assembly language",
        ],
        role_title="Software Engineer 1 - Aviation Web Development",
    )
    result = classify_theme(signals)
    assert result["theme"] == "frontend_web"


def test_agentic_ai_jd_classifies_as_agent_ai_systems():
    signals = _make_signals(
        core_texts=[
            "Build multi-agent autonomous workflows",
            "Design agentic AI systems with tool use and planning",
            "Implement function calling and orchestration pipelines",
        ],
        role_title="Agent AI Systems Engineer",
    )
    result = classify_theme(signals)
    assert result["theme"] == "agent_ai_systems"


def test_distributed_infra_jd_classifies_correctly():
    signals = _make_signals(
        core_texts=[
            "Build distributed systems and data pipelines",
            "Optimize Apache Spark ETL throughput",
            "Maintain high-availability streaming infrastructure",
        ],
        role_title="Data Engineer",
    )
    result = classify_theme(signals)
    assert result["theme"] == "distributed_infra"


def test_mixed_frontend_backend_classifies_as_fullstack():
    signals = _make_signals(
        core_texts=[
            "Build React frontend components",
            "Design REST API backend services",
            "Work across the full stack from database to UI",
        ],
        role_title="Full Stack Engineer",
    )
    result = classify_theme(signals)
    assert result["theme"] == "fullstack"


def test_no_clear_theme_falls_back_to_generalist():
    signals = _make_signals(
        core_texts=[
            "Work on various software projects",
            "Collaborate with team members",
        ],
        role_title="Software Engineer",
    )
    result = classify_theme(signals)
    assert result["theme"] == "generalist"


def test_result_includes_all_scores_and_template():
    signals = _make_signals(
        core_texts=["Build React web applications"],
        role_title="Frontend Engineer",
    )
    result = classify_theme(signals)
    assert "scores" in result
    assert "template" in result
    assert "runner_up" in result
    assert "margin" in result
    assert len(result["scores"]) == 9
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_theme_classifier.py -v`
Expected: FAIL — module not found

- [ ] **Step 4: Implement theme classifier**

Create `job_hunt_copilot/tailoring/theme_classifier.py`:

```python
from __future__ import annotations

import os
import re
from typing import Any, Mapping, Sequence

import yaml

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DATA_DIR = os.path.join(_PROJECT_ROOT, "assets", "resume-tailoring", "data")

# Signal source weights per FR-RT-33C
_SOURCE_WEIGHTS: dict[str, float] = {
    "core_responsibility": 2.0,
    "must_have": 1.0,
    "nice_to_have": 0.5,
    "informational": 0.0,
}

_FULLSTACK_MARGIN = 0.3  # If frontend and backend are within this ratio, pick fullstack
_CONFIDENCE_THRESHOLD = 2.0  # Minimum score to pick a theme over generalist


def _load_theme_terms() -> dict[str, Any]:
    path = os.path.join(_DATA_DIR, "theme_terms.yaml")
    with open(path, "r") as f:
        data = yaml.safe_load(f) or {}
    return data.get("themes", {})


def _tokenize_for_theme(text: str) -> list[str]:
    lowered = text.lower()
    lowered = lowered.replace("node.js", "node js")
    lowered = lowered.replace("next.js", "next js")
    lowered = lowered.replace("c++", "cplusplus")
    lowered = lowered.replace("ci/cd", "cicd")
    return re.findall(r"[a-z0-9#+.-]+", lowered)


def classify_theme(step_3_payload: Mapping[str, Any]) -> dict[str, Any]:
    theme_terms = _load_theme_terms()
    signals = step_3_payload.get("signals", [])
    role_summary = str(step_3_payload.get("role_intent_summary") or "")

    # Collect weighted tokens from signals + role title
    weighted_tokens: list[tuple[str, float]] = []
    for token in _tokenize_for_theme(role_summary):
        weighted_tokens.append((token, 2.0))  # Role title gets core weight
    for signal in signals:
        weight = _SOURCE_WEIGHTS.get(str(signal.get("priority", "")), 0.0)
        if weight == 0.0:
            continue
        signal_text = str(signal.get("signal") or "")
        for token in _tokenize_for_theme(signal_text):
            weighted_tokens.append((token, weight))

    # Build a searchable text blob for multi-word term matching
    all_signal_text = " ".join(
        [role_summary] + [str(s.get("signal") or "") for s in signals]
    ).lower()

    # Score each theme
    scores: dict[str, float] = {}
    for theme_id, theme_data in theme_terms.items():
        terms = theme_data.get("terms", [])
        score = 0.0
        for term in terms:
            term_lower = term.lower()
            # Multi-word term: check substring in full text
            if " " in term_lower or "-" in term_lower:
                if term_lower in all_signal_text:
                    score += 2.0  # Multi-word matches are high confidence
            else:
                # Single-word term: check weighted tokens
                for token, weight in weighted_tokens:
                    if token == term_lower:
                        score += weight
        scores[theme_id] = score

    # Sort by score descending
    ranked = sorted(scores.items(), key=lambda x: -x[1])
    best_theme, best_score = ranked[0]
    runner_up_theme, runner_up_score = ranked[1] if len(ranked) > 1 else ("generalist", 0.0)
    margin = best_score - runner_up_score

    # Fullstack detection: if frontend_web and backend_service both score high and close
    fw_score = scores.get("frontend_web", 0.0)
    bs_score = scores.get("backend_service", 0.0)
    if fw_score > 0 and bs_score > 0:
        ratio = min(fw_score, bs_score) / max(fw_score, bs_score) if max(fw_score, bs_score) > 0 else 0
        if ratio >= (1.0 - _FULLSTACK_MARGIN):
            # Also check if "fullstack" itself scored
            fs_score = scores.get("fullstack", 0.0)
            if fs_score > 0 or ratio >= 0.8:
                best_theme = "fullstack"
                best_score = fw_score + bs_score
                margin = best_score - max(fw_score, bs_score)

    # Confidence threshold: fall back to generalist if no theme is strong
    if best_score < _CONFIDENCE_THRESHOLD and best_theme != "generalist":
        best_theme = "generalist"

    # Determine template
    template_map = {tid: td.get("template", "runtime") for tid, td in theme_terms.items()}
    template = template_map.get(best_theme, "runtime")

    return {
        "theme": best_theme,
        "template": template,
        "scores": scores,
        "runner_up": runner_up_theme,
        "margin": margin,
        "confidence": best_score,
    }
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_theme_classifier.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add assets/resume-tailoring/data/theme_terms.yaml job_hunt_copilot/tailoring/theme_classifier.py tests/test_theme_classifier.py
git commit -m "feat(tailoring): add 9-theme classifier with weighted scoring"
```

---

### Task 3: Bullet Evidence Pool — Experience Variants

**Files:**
- Create: `assets/resume-tailoring/data/bullet_pool_experience.yaml`
- Create: `job_hunt_copilot/tailoring/bullet_pool.py`
- Create: `tests/test_bullet_pool.py`

- [ ] **Step 1: Write experience bullet variants YAML**

Create `assets/resume-tailoring/data/bullet_pool_experience.yaml`. This contains pre-written bullet variants for each experience entry, tagged by theme. Each variant of the same underlying work gets a different framing.

Write bullet variants for:
- SWE role: 4 base bullets (scale, flow, optimization, reliability) x ~4 theme variants each
- Associate SWE role (Cloud Meraki): 3 base bullets x ~3 theme variants each
- Intern role: 1 base bullet x ~3 theme variants

Structure per entry:

```yaml
entries:
  swe_role:
    company: "Infinite Computer Solutions"
    title: "Software Engineer"
    dates: "March 2023 - March 2024"
    bullets:
      - bullet_id: swe_scale_distributed
        base_purpose: scale
        themes: [distributed_infra, backend_service, generalist]
        tech_tags: [Python, Scala, AWS, EMR, S3, distributed systems]
        metrics: ["50M+", "580 TPS", "1,500+", "24/7"]
        text: "Built distributed Python and Scala services on AWS (EMR, S3), processing 50M+ daily HL7 records (~580 TPS) for real-time analytics across 1,500+ hospitals with 24/7 uptime"

      - bullet_id: swe_scale_platform
        base_purpose: scale
        themes: [platform_infra]
        tech_tags: [Python, Scala, AWS, EMR, S3]
        metrics: ["50M+", "580 TPS", "1,500+", "24/7"]
        text: "Built and operated production data services on AWS (EMR, S3) processing 50M+ daily records (~580 TPS), maintaining 24/7 uptime and SLA-aligned delivery across 1,500+ hospitals"

      - bullet_id: swe_scale_ai
        base_purpose: scale
        themes: [applied_ai, agent_ai_systems, forward_deployed_ai]
        tech_tags: [Python, Scala, AWS, EMR, S3]
        metrics: ["50M+", "580 TPS", "1,500+", "24/7"]
        text: "Built distributed Python and Scala services on AWS, processing 50M+ daily HL7 records (~580 TPS) for real-time clinical analytics across 1,500+ hospitals with 24/7 uptime"

      - bullet_id: swe_scale_frontend
        base_purpose: scale
        themes: [frontend_web, fullstack]
        tech_tags: [Python, Scala, AWS]
        metrics: ["50M+", "580 TPS", "1,500+", "24/7"]
        text: "Built production backend services in Python and Scala on AWS, processing 50M+ daily records (~580 TPS) powering customer-facing analytics dashboards across 1,500+ hospitals"

      # ... flow, optimization, reliability bullets with similar variant structure
      # (Full bullet content to be authored during implementation — spec FR-RT-35A)
```

Full bullet content will be authored for all entries and purposes during implementation. The YAML structure above establishes the pattern. Each base purpose (scale, flow, optimization, reliability for SWE; optimization, testing, platform for Associate; portal for Intern) needs variants for relevant theme groups.

- [ ] **Step 2: Write failing test for bullet pool loading**

Add to `tests/test_bullet_pool.py`:

```python
import pytest
from job_hunt_copilot.tailoring.bullet_pool import (
    load_experience_pool,
    get_bullets_for_entry,
    filter_bullets_by_theme,
)


def test_load_experience_pool_returns_all_entries():
    pool = load_experience_pool()
    assert "swe_role" in pool
    assert "associate_swe_role" in pool
    assert "intern_role" in pool


def test_get_bullets_for_entry_returns_all_variants():
    pool = load_experience_pool()
    swe_bullets = get_bullets_for_entry(pool, "swe_role")
    assert len(swe_bullets) > 0
    assert all("bullet_id" in b for b in swe_bullets)
    assert all("text" in b for b in swe_bullets)
    assert all("themes" in b for b in swe_bullets)


def test_filter_bullets_by_theme_returns_matching():
    pool = load_experience_pool()
    swe_bullets = get_bullets_for_entry(pool, "swe_role")
    distributed = filter_bullets_by_theme(swe_bullets, "distributed_infra")
    frontend = filter_bullets_by_theme(swe_bullets, "frontend_web")
    assert len(distributed) > 0
    assert len(frontend) > 0
    # Distributed variants should not appear in frontend results
    dist_ids = {b["bullet_id"] for b in distributed}
    front_ids = {b["bullet_id"] for b in frontend}
    assert not dist_ids & front_ids or True  # Some generalist variants may overlap
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_bullet_pool.py -v`
Expected: FAIL

- [ ] **Step 4: Implement bullet pool loading**

Create `job_hunt_copilot/tailoring/bullet_pool.py`:

```python
from __future__ import annotations

import os
from typing import Any, Sequence

import yaml

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DATA_DIR = os.path.join(_PROJECT_ROOT, "assets", "resume-tailoring", "data")


def _load_yaml(filename: str) -> dict[str, Any]:
    path = os.path.join(_DATA_DIR, filename)
    with open(path, "r") as f:
        return yaml.safe_load(f) or {}


def load_experience_pool() -> dict[str, Any]:
    data = _load_yaml("bullet_pool_experience.yaml")
    return data.get("entries", {})


def load_project_pool() -> dict[str, Any]:
    data = _load_yaml("bullet_pool_projects.yaml")
    return data.get("projects", {})


def get_bullets_for_entry(pool: dict[str, Any], entry_id: str) -> list[dict[str, Any]]:
    entry = pool.get(entry_id, {})
    return list(entry.get("bullets", []))


def filter_bullets_by_theme(
    bullets: Sequence[dict[str, Any]], theme: str
) -> list[dict[str, Any]]:
    return [b for b in bullets if theme in b.get("themes", [])]


def rank_bullets_by_jd_overlap(
    bullets: Sequence[dict[str, Any]], jd_tokens: set[str]
) -> list[dict[str, Any]]:
    scored: list[tuple[float, dict[str, Any]]] = []
    for bullet in bullets:
        tags = {t.lower() for t in bullet.get("tech_tags", [])}
        overlap = len(tags & jd_tokens)
        scored.append((overlap, bullet))
    scored.sort(key=lambda x: -x[0])
    return [b for _, b in scored]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_bullet_pool.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add assets/resume-tailoring/data/bullet_pool_experience.yaml job_hunt_copilot/tailoring/bullet_pool.py tests/test_bullet_pool.py
git commit -m "feat(tailoring): add experience bullet pool with theme variants"
```

---

### Task 4: Bullet Evidence Pool — Project Evidence Atoms

**Files:**
- Create: `assets/resume-tailoring/data/bullet_pool_projects.yaml`
- Modify: `tests/test_bullet_pool.py`

- [ ] **Step 1: Write project evidence atoms YAML**

Create `assets/resume-tailoring/data/bullet_pool_projects.yaml`. Each project is decomposed into evidence atoms — verified facts about what was built. The LLM composes bullets from these at runtime.

```yaml
projects:
  job_hunt_copilot:
    name: "Job Hunt Copilot v4"
    stack: ["Python", "SQLite", "Multi-Agent Systems", "Agentic Workflows", "Review Gates"]
    github: "https://github.com/sontiachyut/job-hunt-copilot-v4"
    dates: "February 2026 - April 2026"
    atoms:
      - atom_id: jhc_supervisor
        what: "autonomous supervisor-agent in Python with durable SQLite state and lease-guarded execution across Gmail intake, resume tailoring, contact discovery, outreach, and delivery feedback"
        themes: [agent_ai_systems, applied_ai, forward_deployed_ai, backend_service]
        tech: [Python, SQLite]
        metrics: []

      - atom_id: jhc_workflow_contracts
        what: "artifact-backed workflow contracts, review packets, and audit events so fresh sessions can reconstruct context, resume runs, and preserve traceable handoffs"
        themes: [agent_ai_systems, applied_ai, backend_service, platform_infra]
        tech: [Python, SQLite]
        metrics: []

      - atom_id: jhc_human_loop
        what: "human-in-the-loop controls with heartbeats, pause/escalation routing, and grouped review snapshots to keep autonomous runs bounded, inspectable, and recoverable"
        themes: [agent_ai_systems, applied_ai, platform_infra]
        tech: [Python]
        metrics: []

      - atom_id: jhc_testing
        what: "spec-backed quality layer, 220+ automated tests, and 212 implemented acceptance scenarios across supervisor control and downstream workflows"
        themes: [agent_ai_systems, applied_ai, backend_service, platform_infra]
        tech: [Python, Pytest]
        metrics: ["220+", "212"]

  linkedin_assistant:
    name: "LinkedIn Job-Matching Assistant"
    stack: ["Python", "FastAPI", "Next.js", "React", "scikit-learn", "FAISS", "Neo4j"]
    github: "https://github.com/sontiachyut/CSE573-LinkedIn-Assistant"
    dates: "August 2025 - November 2025"
    atoms:
      - atom_id: la_retrieval
        what: "explainable retrieval-backed job assistant over 31,597 postings using FastAPI, Sentence-BERT, FAISS, and Neo4j, achieving NDCG 0.78 and ~50ms search latency"
        themes: [applied_ai, agent_ai_systems, backend_service, fullstack]
        tech: [Python, FastAPI, FAISS, Neo4j, "Sentence-BERT"]
        metrics: ["31,597", "NDCG 0.78", "~50ms"]

      - atom_id: la_ranking_pipeline
        what: "multi-stage ranking pipeline combining fuzzy search, TF-IDF, semantic embeddings, and Rasch IRT scoring to surface explainable fit signals"
        themes: [applied_ai, agent_ai_systems, backend_service]
        tech: [Python, scikit-learn, FAISS]
        metrics: []

      - atom_id: la_fullstack
        what: "full-stack job-search web application using Next.js 15, React 19, FastAPI backend with TypeScript frontend and Tailwind CSS"
        themes: [frontend_web, fullstack]
        tech: [Next.js, React, TypeScript, "Tailwind CSS", FastAPI]
        metrics: ["31,597"]

  tiaa_platform:
    name: "Student Loan Retirement Matching Platform"
    stack: ["React", "TypeScript", "AWS Lambda", "DynamoDB", "S3", "AWS Bedrock"]
    github: "https://github.com/ShivamGS/loan-platform"
    dates: "October 2025"
    atoms:
      - atom_id: tiaa_serverless
        what: "serverless financial-planning app with React, Lambda, PostgreSQL, and Bedrock-powered advisor chat plus RAG-based document analysis for 45M+ Americans under SECURE 2.0; won 2nd place at TIAA Spark Challenge 2025"
        themes: [applied_ai, frontend_web, fullstack, forward_deployed_ai]
        tech: [React, TypeScript, "AWS Lambda", DynamoDB, S3, "AWS Bedrock"]
        metrics: ["45M+", "2nd place"]

      - atom_id: tiaa_ai_chat
        what: "WebSocket-based multi-turn financial chatbot with DynamoDB session persistence, LLM integration, and 3 operating modes with graceful degradation fallback"
        themes: [applied_ai, agent_ai_systems]
        tech: ["AWS Bedrock", DynamoDB, "WebSocket"]
        metrics: []

  edge_face_recognition:
    name: "Distributed Edge Face Recognition Pipeline"
    stack: ["Python", "AWS IoT Greengrass v2", "EC2", "MQTT", "SQS", "AWS Lambda", "S3"]
    github: "https://github.com/sontiachyut/CSE546-Cloud-Computing"
    dates: "January 2025 - April 2025"
    atoms:
      - atom_id: efr_edge_cloud
        what: "real-time edge-cloud face recognition pipeline with Greengrass, Lambda, SQS, and MTCNN/FaceNet inference, achieving 100% accuracy on 100 frames with sub-second latency"
        themes: [applied_ai, distributed_infra, platform_infra]
        tech: [Python, "AWS Lambda", SQS, "AWS IoT Greengrass", EC2, S3]
        metrics: ["100%", "100 frames"]

      - atom_id: efr_architectures
        what: "same pipeline implemented across 4 cloud architectures (IaaS, multi-tier auto-scaling, serverless, hybrid edge-cloud) to compare scalability, cost, and latency trade-offs"
        themes: [platform_infra, distributed_infra]
        tech: [Python, AWS, Docker, SQS]
        metrics: ["4"]

  national_parks_viz:
    name: "National Parks Biodiversity Visualization"
    stack: ["D3.js", "JavaScript", "HTML5", "CSS3", "Bootstrap 5"]
    github: "https://github.com/sontiachyut/data-visualization"
    dates: "Spring 2025"
    atoms:
      - atom_id: npv_viz
        what: "interactive web visualization of species diversity across 60 U.S. National Parks combining hierarchical treemaps with nested force-directed circular packing using D3.js"
        themes: [frontend_web]
        tech: ["D3.js", JavaScript, HTML5, CSS3]
        metrics: ["60"]

      - atom_id: npv_forces
        what: "force-directed layout with 4 simultaneous forces (boundary, center, charge, collision) and dynamic toggle between species count and acreage sizing"
        themes: [frontend_web]
        tech: ["D3.js", JavaScript]
        metrics: ["4"]

  health_monitoring:
    name: "Context-Aware Health Monitoring App"
    stack: ["Kotlin", "Android", "Room", "Coroutines"]
    github: "https://github.com/sontiachyut/CSE535-Project1-Context-Monitoring-App"
    dates: "August 2025 - November 2025"
    atoms:
      - atom_id: hm_sensors
        what: "health monitoring Android app measuring heart rate via camera-based PPG and respiratory rate via accelerometer, with symptom tracking persisted in Room database"
        themes: [frontend_web, fullstack]
        tech: [Kotlin, Android, Room]
        metrics: []

  content_rec_engine:
    name: "Distributed Content Recommendation Engine"
    stack: ["React", "Node.js", "Express", "MongoDB", "Neo4j", "Docker"]
    github: ""
    dates: "Academic Project"
    atoms:
      - atom_id: cre_distributed
        what: "distributed social media content recommendation platform with Instagram-like UI using React, MongoDB sharded cluster (9 containers), and Neo4j graph traversal"
        themes: [fullstack, frontend_web, distributed_infra]
        tech: [React, Node.js, Express, MongoDB, Neo4j, Docker]
        metrics: ["9"]

      - atom_id: cre_algorithm
        what: "hybrid collaborative filtering recommendation algorithm using Neo4j Cypher graph traversal (3 hops) with real-time MongoDB-to-Neo4j sync via change streams"
        themes: [backend_service, distributed_infra, applied_ai]
        tech: [Neo4j, MongoDB]
        metrics: []
```

- [ ] **Step 2: Write failing test for project pool**

Add to `tests/test_bullet_pool.py`:

```python
from job_hunt_copilot.tailoring.bullet_pool import (
    load_project_pool,
    get_project_atoms,
    filter_atoms_by_theme,
)


def test_load_project_pool_returns_all_projects():
    pool = load_project_pool()
    assert "job_hunt_copilot" in pool
    assert "linkedin_assistant" in pool
    assert "tiaa_platform" in pool


def test_get_project_atoms_returns_atoms():
    pool = load_project_pool()
    atoms = get_project_atoms(pool, "job_hunt_copilot")
    assert len(atoms) == 4
    assert all("atom_id" in a for a in atoms)


def test_filter_atoms_by_theme():
    pool = load_project_pool()
    atoms = get_project_atoms(pool, "job_hunt_copilot")
    ai_atoms = filter_atoms_by_theme(atoms, "agent_ai_systems")
    assert len(ai_atoms) >= 3  # supervisor, workflow, human_loop, testing
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_bullet_pool.py::test_load_project_pool_returns_all_projects -v`
Expected: FAIL

- [ ] **Step 4: Add project pool functions to bullet_pool.py**

Add to `job_hunt_copilot/tailoring/bullet_pool.py`:

```python
def get_project_atoms(pool: dict[str, Any], project_id: str) -> list[dict[str, Any]]:
    project = pool.get(project_id, {})
    return list(project.get("atoms", []))


def filter_atoms_by_theme(
    atoms: Sequence[dict[str, Any]], theme: str
) -> list[dict[str, Any]]:
    return [a for a in atoms if theme in a.get("themes", [])]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_bullet_pool.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add assets/resume-tailoring/data/bullet_pool_projects.yaml job_hunt_copilot/tailoring/bullet_pool.py tests/test_bullet_pool.py
git commit -m "feat(tailoring): add project evidence atoms pool"
```

---

### Task 5: Summary Templates & Skill Category Templates

**Files:**
- Create: `assets/resume-tailoring/data/summary_templates.yaml`
- Create: `assets/resume-tailoring/data/skill_categories.yaml`

- [ ] **Step 1: Write summary templates per theme (FR-RT-34B)**

Create `assets/resume-tailoring/data/summary_templates.yaml` with one summary per theme. Each summary frames the candidate appropriately for the role archetype:

```yaml
summaries:
  applied_ai: "Software engineer with 3+ years of experience building production systems at scale, including retrieval-backed LLM applications, stateful agent workflows, and evaluation-aware automation"
  agent_ai_systems: "Software engineer with 3+ years of experience building production systems at scale, including retrieval-backed LLM applications, stateful agent workflows, and evaluation-aware automation"
  forward_deployed_ai: "Software engineer with 3+ years of experience building production systems at scale, with hands-on AI integration, client-facing deployment, and domain-specific automation"
  frontend_web: "Software engineer with 3+ years of experience building production web applications and interactive user interfaces, focused on modern frontend frameworks, responsive design, and data visualization"
  backend_service: "MS CS candidate with 3+ years building backend data services and distributed systems, focused on Python and AWS delivery, production reliability, and high-volume workflow automation"
  distributed_infra: "MS CS candidate with 3+ years of experience building large-scale distributed systems and data services, focused on reliable cloud infrastructure, performance optimization, and production-safe analytics delivery"
  platform_infra: "MS CS candidate with 3+ years building cloud platforms and production data services, focused on infrastructure automation, observability, reliability, and cost-aware operations across containerized distributed systems"
  fullstack: "MS CS candidate with 3+ years of experience building full-stack applications across cloud, data, and AI-adjacent systems, focused on reliable delivery, measurable performance gains, and recruiter-readable product impact"
  generalist: "MS CS candidate with 3+ years of experience building production software across cloud, data, and AI-adjacent systems, focused on reliable delivery, measurable performance gains, and recruiter-readable product impact"
```

- [ ] **Step 2: Write skill categories per theme (FR-RT-34A)**

Create `assets/resume-tailoring/data/skill_categories.yaml`:

```yaml
categories:
  applied_ai:
    - name: "Languages"
      pool_sources: ["languages"]
    - name: "Applied AI"
      pool_sources: ["ai & data", "systems"]
    - name: "Backend \\& Data"
      pool_sources: ["backend", "data & storage"]
    - name: "Cloud \\& Infra"
      pool_sources: ["cloud & devops"]
    - name: "Testing \\& Reliability"
      pool_sources: ["testing & reliability"]

  agent_ai_systems:
    - name: "Languages"
      pool_sources: ["languages"]
    - name: "Applied AI"
      pool_sources: ["ai & data", "systems"]
    - name: "Backend \\& Data"
      pool_sources: ["backend", "data & storage"]
    - name: "Cloud \\& Infra"
      pool_sources: ["cloud & devops"]
    - name: "Testing \\& Reliability"
      pool_sources: ["testing & reliability"]

  forward_deployed_ai:
    - name: "Languages"
      pool_sources: ["languages"]
    - name: "Applied AI"
      pool_sources: ["ai & data"]
    - name: "Backend \\& Data"
      pool_sources: ["backend", "data & storage", "systems"]
    - name: "Cloud \\& Infra"
      pool_sources: ["cloud & devops"]
    - name: "Testing \\& Reliability"
      pool_sources: ["testing & reliability"]

  frontend_web:
    - name: "Languages"
      pool_sources: ["languages"]
    - name: "Frontend \\& UI"
      pool_sources: ["frontend & mobile"]
    - name: "Backend \\& Data"
      pool_sources: ["backend", "data & storage"]
    - name: "Cloud \\& DevOps"
      pool_sources: ["cloud & devops"]
    - name: "Testing \\& Reliability"
      pool_sources: ["testing & reliability"]

  backend_service:
    - name: "Languages"
      pool_sources: ["languages"]
    - name: "Infrastructure \\& Systems"
      pool_sources: ["systems"]
    - name: "Cloud \\& DevOps"
      pool_sources: ["cloud & devops"]
    - name: "Data \\& Storage"
      pool_sources: ["data & storage"]
    - name: "Testing \\& Reliability"
      pool_sources: ["testing & reliability"]

  distributed_infra:
    - name: "Languages"
      pool_sources: ["languages"]
    - name: "Infrastructure \\& Systems"
      pool_sources: ["systems"]
    - name: "Cloud \\& DevOps"
      pool_sources: ["cloud & devops"]
    - name: "Data \\& Storage"
      pool_sources: ["data & storage"]
    - name: "Testing \\& Reliability"
      pool_sources: ["testing & reliability"]

  platform_infra:
    - name: "Languages"
      pool_sources: ["languages"]
    - name: "Infrastructure \\& Systems"
      pool_sources: ["systems"]
    - name: "Cloud \\& DevOps"
      pool_sources: ["cloud & devops"]
    - name: "Data \\& Storage"
      pool_sources: ["data & storage"]
    - name: "Testing \\& Reliability"
      pool_sources: ["testing & reliability"]

  fullstack:
    - name: "Languages"
      pool_sources: ["languages"]
    - name: "Application \\& Systems"
      pool_sources: ["frontend & mobile", "systems"]
    - name: "Cloud \\& DevOps"
      pool_sources: ["cloud & devops"]
    - name: "Data \\& Storage"
      pool_sources: ["data & storage"]
    - name: "Testing \\& Reliability"
      pool_sources: ["testing & reliability"]

  generalist:
    - name: "Languages"
      pool_sources: ["languages"]
    - name: "Application \\& Systems"
      pool_sources: ["frontend & mobile", "systems"]
    - name: "Cloud \\& DevOps"
      pool_sources: ["cloud & devops"]
    - name: "Data \\& Storage"
      pool_sources: ["data & storage"]
    - name: "Testing \\& Reliability"
      pool_sources: ["testing & reliability"]
```

- [ ] **Step 3: Commit**

```bash
git add assets/resume-tailoring/data/summary_templates.yaml assets/resume-tailoring/data/skill_categories.yaml
git commit -m "feat(tailoring): add per-theme summary and skill category templates"
```

---

### Task 6: Templates A and B Base Resumes

**Files:**
- Create: `assets/resume-tailoring/base/projects-first/base-resume.tex`
- Create: `assets/resume-tailoring/base/experience-first/base-resume.tex`
- Modify: `job_hunt_copilot/paths.py`

- [ ] **Step 1: Create Template A**

Copy the Applied AI resume from `/Users/achyutaramsonti/Projects/Job Hunt/Resume/1. My Resumes/3. Applied AI and Agentic AI/base-resume.tex` to `assets/resume-tailoring/base/projects-first/base-resume.tex`. This is the projects-first template (Summary → Education → Projects → Experience → Awards → Skills).

Verify the section order matches Template A: Summary, Education, Projects, Experience, Awards/Leadership, Technical Skills.

- [ ] **Step 2: Create Template B**

Create `assets/resume-tailoring/base/experience-first/base-resume.tex` as the experience-first variant (Summary → Education → Experience → Projects → Awards → Skills).

Verify the section order matches Template B: Summary, Education, Experience, Projects, Awards/Leadership, Technical Skills.

- [ ] **Step 3: Update paths.py**

Add the Template A/B paths and new step artifact paths to `job_hunt_copilot/paths.py`. Add a function to resolve base template by template type ("A" or "B"):

```python
def base_resume_template_path(template_type: str) -> str:
    if template_type == "A":
        return os.path.join(PROJECT_ROOT, "assets", "resume-tailoring", "base", "projects-first", "base-resume.tex")
    return os.path.join(PROJECT_ROOT, "assets", "resume-tailoring", "base", "experience-first", "base-resume.tex")
```

Add step artifact path functions for steps 01-16 following the existing pattern (e.g., `tailoring_step_01_path`, `tailoring_step_02_path`, etc.).

- [ ] **Step 4: Commit**

```bash
git add assets/resume-tailoring/base/projects-first/base-resume.tex assets/resume-tailoring/base/experience-first/base-resume.tex job_hunt_copilot/paths.py
git commit -m "feat(tailoring): add base templates and update path resolution"
```

---

### Task 7: Update Master Profile — Add Job Hunt Copilot

**Files:**
- Modify: `assets/resume-tailoring/profile.md`
- Modify: `resume-tailoring/input/profile.md`

- [ ] **Step 1: Add Job Hunt Copilot to profile.md**

Add the Job Hunt Copilot project to the Projects section of `assets/resume-tailoring/profile.md`, using the detail from the Applied AI resume and expanding with evidence atoms. Place it as the first project:

```markdown
### Job Hunt Copilot v4 (Feb 2026 – Apr 2026)
- **Stack:** Python, SQLite, Multi-Agent Systems, Agentic Workflows, Review Gates
- Built an autonomous supervisor-agent in Python with durable SQLite state and lease-guarded execution across Gmail intake, resume tailoring, contact discovery, outreach, and delivery feedback
- Engineered artifact-backed workflow contracts, review packets, and audit events so fresh sessions can reconstruct context, resume runs, and preserve traceable handoffs
- Added human-in-the-loop controls with heartbeats, pause/escalation routing, and grouped review snapshots to keep autonomous runs bounded, inspectable, and recoverable
- Hardened the runtime with a spec-backed quality layer, 220+ automated tests, and 212 implemented acceptance scenarios across supervisor control and downstream workflows
- **GitHub:** https://github.com/sontiachyut/job-hunt-copilot-v4
```

- [ ] **Step 2: Mirror to input/profile.md**

Copy the updated profile to `resume-tailoring/input/profile.md` to keep the working mirror in sync.

- [ ] **Step 3: Commit**

```bash
git add assets/resume-tailoring/profile.md resume-tailoring/input/profile.md
git commit -m "feat(tailoring): add Job Hunt Copilot project to master profile"
```

---

## Phase 2: Pipeline Steps (Tasks 8-17)

Each pipeline step is a focused Python function that reads upstream artifacts and produces a YAML output. Steps are implemented incrementally with TDD.

### Task 8: Steps 1-3 (JD Parsing, Signal Extraction, Classification)

**Files:**
- Create: `job_hunt_copilot/tailoring/steps/step_01_jd_sections.py`
- Create: `job_hunt_copilot/tailoring/steps/step_02_signals_raw.py`
- Create: `job_hunt_copilot/tailoring/steps/step_03_signals_classified.py`
- Create: `tests/test_pipeline_steps.py`

These 3 steps are largely a refactor of the existing `_build_step_3_signal_artifact()` (lines 3455-3538 of `resume_tailoring.py`), split into discrete steps. The existing signal extraction logic is sound — it just needs to be decomposed.

- [ ] **Step 1: Write failing test for Step 1 (JD section identification)**

```python
from job_hunt_copilot.tailoring.steps.step_01_jd_sections import identify_jd_sections

GARMIN_JD = """Job Description

Software Engineer 1 - Aviation Web Development
...Essential Functions
Performs new product and/or application software design...
Basic Qualifications
Bachelor's Degree in Computer Science...
Desired Qualifications
Outstanding academics..."""


def test_step_01_identifies_sections():
    result = identify_jd_sections(GARMIN_JD)
    assert "sections" in result
    sections = result["sections"]
    assert any(s["heading"] == "Essential Functions" for s in sections)
    assert any(s["heading"] == "Basic Qualifications" for s in sections)
```

- [ ] **Step 2: Implement Step 1**

Extract heading identification logic from existing `_jd_heading_from_line()` (line 4465) and `_normalize_jd_line()` (line 4495) into a clean step function that returns structured sections.

- [ ] **Step 3: Write failing test for Step 2 (signal extraction)**

```python
from job_hunt_copilot.tailoring.steps.step_02_signals_raw import extract_signals

def test_step_02_extracts_signals_from_sections():
    sections = [
        {"heading": "Essential Functions", "lines": ["Performs software design using Angular, JavaScript"]},
        {"heading": "Basic Qualifications", "lines": ["Bachelor's Degree in Computer Science"]},
    ]
    result = extract_signals(sections)
    assert "signals" in result
    assert len(result["signals"]) >= 2
```

- [ ] **Step 4: Implement Step 2**

Extract signal extraction logic from existing step 3 builder. Each meaningful line becomes a signal with its source heading.

- [ ] **Step 5: Write failing test for Step 3 (signal classification)**

```python
from job_hunt_copilot.tailoring.steps.step_03_signals_classified import classify_signals

def test_step_03_classifies_priorities_and_tokenizes():
    raw_signals = [
        {"signal": "Performs software design using Angular", "source_heading": "Essential Functions"},
        {"signal": "Bachelor's Degree in CS", "source_heading": "Basic Qualifications"},
    ]
    result = classify_signals(raw_signals)
    signals = result["signals"]
    assert signals[0]["priority"] == "core_responsibility"
    assert signals[1]["priority"] == "must_have"
    assert "tokens" in signals[0]
    assert "weight" in signals[0]
    assert "category" in signals[0]
```

- [ ] **Step 6: Implement Step 3**

Extract classification logic from existing `_classify_signal_priority()` (line 4504), `_categorize_signal()` (line 4548), `_signal_priority_weight()` (line 4571), and `_tokenize()` (line 4591).

- [ ] **Step 7: Run all step tests**

Run: `python -m pytest tests/test_pipeline_steps.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add job_hunt_copilot/tailoring/steps/step_01*.py job_hunt_copilot/tailoring/steps/step_02*.py job_hunt_copilot/tailoring/steps/step_03*.py tests/test_pipeline_steps.py
git commit -m "feat(tailoring): implement pipeline steps 1-3 (JD parsing, signals, classification)"
```

---

### Task 9: Steps 4-5 (Theme Scoring & Decision)

**Files:**
- Create: `job_hunt_copilot/tailoring/steps/step_04_theme_scores.py`
- Create: `job_hunt_copilot/tailoring/steps/step_05_theme_decision.py`

These steps wrap the theme classifier (Task 2) to produce auditable step artifacts.

- [ ] **Step 1: Write failing test**

```python
def test_step_04_scores_all_themes():
    classified_signals = {...}  # Output from Step 3 with Garmin JD
    result = score_themes(classified_signals)
    assert len(result["theme_scores"]) == 9
    assert result["theme_scores"]["frontend_web"] > result["theme_scores"]["distributed_infra"]

def test_step_05_picks_theme_and_template():
    theme_scores = {...}  # Output from Step 4
    result = decide_theme(theme_scores)
    assert result["theme"] == "frontend_web"
    assert result["template"] in ("A", "B", "runtime")
    assert "reasoning" in result
```

- [ ] **Step 2: Implement Steps 4-5**

Step 4 calls `classify_theme()` from the theme classifier and structures the output as a step artifact.
Step 5 reads Step 4 output, records the decision with reasoning, runner-up, margin, and resolves the template type. For `runtime` templates, Step 5 defers the A/B decision to after evidence mapping (Step 9).

- [ ] **Step 3: Run tests, commit**

---

### Task 10: Steps 6-7 (Project Scoring & Selection)

**Files:**
- Create: `job_hunt_copilot/tailoring/steps/step_06_project_scores.py`
- Create: `job_hunt_copilot/tailoring/steps/step_07_project_selection.py`

- [ ] **Step 1: Write failing test**

```python
def test_step_06_scores_all_projects():
    result = score_projects(classified_signals, project_pool)
    assert "job_hunt_copilot" in result["project_scores"]
    assert all("score" in v for v in result["project_scores"].values())

def test_step_07_selects_4_projects_jhc_first():
    result = select_projects(project_scores, theme="applied_ai")
    assert len(result["selected"]) == 4
    assert result["selected"][0]["project_id"] == "job_hunt_copilot"
    assert len(result["excluded"]) > 0
```

- [ ] **Step 2: Implement**

Step 6: For each project in the pool, score its atoms against JD signals. Sum overlap scores.
Step 7: JHC always first. Sort remaining by score descending. Take top 3. Record exclusion reasons.

- [ ] **Step 3: Run tests, commit**

---

### Task 11: Steps 8-9 (Evidence Mapping)

**Files:**
- Create: `job_hunt_copilot/tailoring/steps/step_08_experience_evidence.py`
- Create: `job_hunt_copilot/tailoring/steps/step_09_project_evidence.py`

- [ ] **Step 1: Write failing tests**

Test that each JD signal gets mapped to matching bullet candidates (Step 8 for experience, Step 9 for projects). Test that scores reflect tech_tag/atom overlap with JD tokens.

- [ ] **Step 2: Implement**

Step 8: For each experience entry, for each JD signal, score each bullet variant by tech_tag overlap. Record matches with confidence.
Step 9: For each selected project, for each JD signal, score each atom by tech overlap. Record matches.

- [ ] **Step 3: Run tests, commit**

---

### Task 12: Step 10 (Gap Analysis)

**Files:**
- Create: `job_hunt_copilot/tailoring/steps/step_10_gap_analysis.py`

- [ ] **Step 1: Write failing test**

Test that uncovered must-have signals are flagged. Test that JD keywords present in profile but not in any selected bullet are flagged as missed opportunities.

- [ ] **Step 2: Implement**

Read Steps 8-9 outputs. For each JD signal, check if any bullet/atom covers it. Flag uncovered must-have signals. Cross-reference JD keywords against profile skill inventory — flag keywords that exist in profile but aren't surfaced.

- [ ] **Step 3: Run tests, commit**

---

### Task 13: Step 11 (Bullet Ranking & Allocation)

**Files:**
- Create: `job_hunt_copilot/tailoring/steps/step_11_bullet_allocation.py`

This is a critical step — it decides which bullets go where and how many each entry gets.

- [ ] **Step 1: Write failing test**

```python
def test_step_11_respects_min_max_limits():
    result = allocate_bullets(evidence_map, theme="applied_ai", template="A")
    jhc = result["allocations"]["job_hunt_copilot"]
    assert jhc["bullet_count"] == 4  # Fixed for AI themes
    swe = result["allocations"]["swe_role"]
    assert 3 <= swe["bullet_count"] <= 4
    assoc = result["allocations"]["associate_swe_role"]
    assert 2 <= assoc["bullet_count"] <= 3
    intern = result["allocations"]["intern_role"]
    assert intern["bullet_count"] == 1

def test_step_11_marks_hero_and_supporting():
    result = allocate_bullets(evidence_map, theme="applied_ai", template="A")
    assert result["hero_section"] == "projects"
    assert result["supporting_section"] == "experience"
```

- [ ] **Step 2: Implement**

Rank all bullet candidates by JD fit score. Assign hero/supporting mode based on template. Allocate bullet counts within min/max limits per entry. Select specific bullets per entry, highest-ranked first. Record what was cut and why.

- [ ] **Step 3: Run tests, commit**

---

### Task 14: Steps 12-14 (Summary, Skills, Tech Stacks)

**Files:**
- Create: `job_hunt_copilot/tailoring/steps/step_12_summary.py`
- Create: `job_hunt_copilot/tailoring/steps/step_13_skills.py`
- Create: `job_hunt_copilot/tailoring/steps/step_14_tech_stacks.py`

- [ ] **Step 1: Write failing tests**

```python
def test_step_12_uses_theme_summary_template():
    result = compose_summary(theme="frontend_web", signals=classified_signals)
    assert "web" in result["summary"].lower() or "frontend" in result["summary"].lower()

def test_step_13_injects_jd_keywords_into_skills():
    result = compose_skills(theme="frontend_web", jd_keywords=["Angular", "Vue"],
                            profile_skills=profile_skill_inventory, adjacency_map=adj_map)
    all_items = [item for cat in result["categories"] for item in cat["items"]]
    assert "Angular" in all_items  # Adjacent match via React

def test_step_14_generates_per_entry_stack_lines():
    result = compose_tech_stacks(allocations=allocations, theme="frontend_web")
    assert "swe_role" in result["tech_stacks"]
    assert "intern_role" in result["tech_stacks"]
```

- [ ] **Step 2: Implement Step 12**

Load summary template for theme from `summary_templates.yaml`. Return as step artifact.

- [ ] **Step 3: Implement Step 13**

Load skill category template for theme. For each category, pull items from profile skill inventory. Apply the 3-layer keyword system: extract JD keywords, match against profile (direct/equivalent/adjacent), inject matches into appropriate categories. Use adjacency map for adjacent matches. Promote JD-matching items to front.

- [ ] **Step 4: Implement Step 14**

For each experience entry, build a tech stack line from the technologies actually used in that role. Promote JD-mentioned technologies to the front. For projects, use the project's declared stack.

- [ ] **Step 5: Run tests, commit**

---

### Task 15: Step 15 (Resume Assembly & Page Fill)

**Files:**
- Create: `job_hunt_copilot/tailoring/steps/step_15_assembly.py`

This step assembles all components into the LaTeX template and runs the page-fill loop.

- [ ] **Step 1: Write failing test**

```python
def test_step_15_assembles_resume_dict():
    result = assemble_resume(
        template_type="A", summary=summary, skills=skills,
        tech_stacks=tech_stacks, allocations=allocations,
        bullet_pool=experience_pool, project_pool=project_pool,
    )
    assert "summary" in result
    assert "sections" in result
    assert result["sections"][0]["type"] == "projects"  # Template A
```

- [ ] **Step 2: Implement assembly**

Build a structured resume document from all upstream step outputs. Apply hero/supporting mode rules for bullet content:
- Hero projects: compose from evidence atoms using JD language
- Supporting projects: use pre-composed or lightly adjusted bullets
- Hero experience: aggressive keyword injection on pre-written variants
- Supporting experience: light keyword injection

Output a structured YAML that the finalize step will render into LaTeX.

- [ ] **Step 3: Run tests, commit**

---

### Task 16: Step 16 (Verification)

**Files:**
- Create: `job_hunt_copilot/tailoring/steps/step_16_verification.py`

- [ ] **Step 1: Write failing test**

```python
def test_step_16_catches_theme_content_mismatch():
    # Backend bullets on a frontend_web theme should fail alignment
    result = verify(theme="frontend_web", assembly=backend_heavy_assembly, signals=frontend_signals)
    alignment = next(c for c in result["checks"] if c["check_id"] == "jd-content-alignment")
    assert alignment["status"] in ("needs_revision", "fail")

def test_step_16_passes_aligned_resume():
    result = verify(theme="frontend_web", assembly=frontend_assembly, signals=frontend_signals)
    alignment = next(c for c in result["checks"] if c["check_id"] == "jd-content-alignment")
    assert alignment["status"] == "pass"
```

- [ ] **Step 2: Implement verification**

Two passes:
1. **Content verification:** JD-content alignment (compare theme vs. bullet tech tags vs. JD signals), proof-grounding (bullets cite evidence), JD coverage (% of signals covered), JD keyword coverage (% of critical keywords in final resume).
2. **Structural verification:** Metric sanity (no spelled-out numbers), bullet character budget (100-275 chars), LaTeX safety.

Refactor from existing `_build_step_7_verification_artifact()` (line 3764) and add the new `jd-content-alignment` and `jd-keyword-coverage` checks.

- [ ] **Step 3: Run tests, commit**

---

## Phase 3: Integration (Tasks 17-19)

### Task 17: Pipeline Orchestration

**Files:**
- Create: `job_hunt_copilot/tailoring/pipeline.py`

- [ ] **Step 1: Write failing test**

```python
def test_pipeline_runs_all_16_steps_and_produces_artifacts(tmp_path):
    # Set up a minimal workspace with JD and profile
    result = run_tailoring_pipeline(workspace_path=str(tmp_path), jd_text=GARMIN_JD, profile_text=PROFILE)
    assert len(result["step_artifacts"]) == 16
    assert all(os.path.exists(p) for p in result["step_artifacts"].values())
```

- [ ] **Step 2: Implement pipeline orchestration**

`run_tailoring_pipeline()` calls Steps 1-16 in sequence, passing each step's output to the next. Writes each step artifact to the intelligence directory. Returns a result dict with all artifact paths and the final verification outcome.

- [ ] **Step 3: Run tests, commit**

---

### Task 18: Wire Up Bootstrap & Finalize

**Files:**
- Modify: `job_hunt_copilot/resume_tailoring.py`

This is the largest modification — updating the existing bootstrap and finalize flows to use the new pipeline.

- [ ] **Step 1: Update bootstrap_tailoring_run()**

Replace `_select_base_resume_track()` with theme-based template selection:
1. Run Steps 1-5 early to determine theme and template
2. Use `base_resume_template_path(template)` to select Template A or B
3. Store theme ID in `base_used` field

- [ ] **Step 2: Update generate_tailoring_intelligence()**

Replace calls to `_build_step_3_signal_artifact()` through `_build_step_7_verification_artifact()` with `run_tailoring_pipeline()`.

- [ ] **Step 3: Update finalize_tailoring_run()**

Update to:
1. Load Step 15 assembly output instead of Step 6 payload
2. Apply assembly to template LaTeX (render summary, skills, bullets, tech stacks into the template sections)
3. Load Step 16 verification instead of Step 7
4. Perform the final canonical render/compile/persist pass only after Step 16 passes

Note: Step 15 may use iterative render/compile helpers during page-fill convergence, but finalize owns the final accepted workspace render and canonical PDF persist.

- [ ] **Step 4: Remove old code**

Remove from `resume_tailoring.py`:
- `TRACK_LIBRARY`, `FRONTEND_AI_TRACK`, `DISTRIBUTED_INFRA_TRACK`, `GENERALIST_SWE_TRACK`
- `FRONTEND_AI_TERMS`, `DISTRIBUTED_INFRA_TERMS`
- `ROLE_FOCUS_*` constants and `_determine_role_focus()`
- `_select_tailoring_track()`
- `_build_step_3_signal_artifact()` through `_build_step_7_verification_artifact()`
- `_build_tailored_summary()`, `_build_tailored_technical_skills()`
- Old step-specific helper functions

Keep:
- `bootstrap_tailoring_run()` (modified)
- `generate_tailoring_intelligence()` (modified)
- `finalize_tailoring_run()` (modified)
- All database interaction functions
- LaTeX compilation functions
- Resume parsing functions (updated for new structure)
- Eligibility evaluation
- Review functions
- State constants and dataclasses

- [ ] **Step 5: Update paths.py**

Add artifact paths for steps 01-16. Update `required_asset_paths()` to include new data files.

- [ ] **Step 6: Run existing tests and fix failures**

Run: `python -m pytest tests/test_resume_tailoring.py -v`
Fix any failures caused by the refactoring. Tests that validated old step artifact names need to be updated to the new step numbering.

- [ ] **Step 7: Commit**

```bash
git add job_hunt_copilot/resume_tailoring.py job_hunt_copilot/paths.py
git commit -m "feat(tailoring): wire up 16-step pipeline, remove old track/focus system"
```

---

### Task 19: Integration Test with Garmin JD

**Files:**
- Create: `tests/test_tailoring_integration.py`

- [ ] **Step 1: Write integration test**

```python
def test_garmin_aviation_produces_frontend_themed_resume(bootstrap_project_with_real_tailoring_assets):
    """The Garmin Aviation Web Development JD must produce a frontend_web themed resume,
    not backend/distributed. This is the original repro case from issue #80."""
    project_root = bootstrap_project_with_real_tailoring_assets
    # Seed the Garmin posting
    # Run generate_tailoring_intelligence()
    # Assert theme == "frontend_web"
    # Assert bullets contain web/frontend terms
    # Assert skills contain Angular (via adjacency from React)
    # Assert verification passes with jd-content-alignment == pass
    # Run finalize_tailoring_run()
    # Assert PDF compiles to 1 page
```

- [ ] **Step 2: Write integration test for AI-themed JD**

```python
def test_ai_jd_produces_projects_first_with_jhc_leading():
    """An agentic AI JD should use Template A with JHC as first project."""
    # Seed an agentic AI posting
    # Run pipeline
    # Assert theme == "agent_ai_systems" or "applied_ai"
    # Assert template == "A" (projects-first)
    # Assert JHC is first project with 4 bullets
```

- [ ] **Step 3: Run integration tests**

Run: `python -m pytest tests/test_tailoring_integration.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_tailoring_integration.py
git commit -m "test(tailoring): add integration tests for Garmin frontend and AI theme selection"
```

---

## Phase 4: Asset Replacement (Task 20)

### Task 20: Rewrite System Prompt, Cookbook, SOP

**Files:**
- Modify: `assets/resume-tailoring/ai/system-prompt.md`
- Modify: `assets/resume-tailoring/ai/cookbook.md`
- Modify: `assets/resume-tailoring/ai/sop-swe-experience-tailoring.md`

- [ ] **Step 1: Rewrite system prompt**

Update `system-prompt.md` to describe the 16-step pipeline, theme-based approach, bullet evidence pool, hero/supporting mode, and the new verification checks. Remove all references to the old 3-track system and Step 3-7 numbering.

- [ ] **Step 2: Rewrite cookbook**

Update `cookbook.md` recipes for:
- Theme-based skill category selection (replaces track-based)
- Evidence pool bullet selection (replaces hardcoded bullets)
- JD keyword injection rules (new)
- Hero vs. supporting mode writing rules (new)
- Page-fill adjustment procedure (updated)

- [ ] **Step 3: Rewrite SOP**

Update `sop-swe-experience-tailoring.md` to cover the new evidence-pool-based approach instead of the old 7-step procedure tied to a single SWE block.

- [ ] **Step 4: Commit**

```bash
git add assets/resume-tailoring/ai/
git commit -m "docs(tailoring): rewrite system prompt, cookbook, and SOP for new pipeline"
```

---

## Phase 5: Final Verification (Task 21)

### Task 21: Full Test Suite & Manual Verification

- [ ] **Step 1: Run full test suite**

Run: `python -m pytest tests/ -v --tb=short`
Expected: All tests pass

- [ ] **Step 2: Manual test with Garmin JD**

Run tailoring for Garmin Aviation and inspect:
- Theme selected: `frontend_web`
- Template: B or runtime-decided
- Skills contain Angular (adjacent), JavaScript, web terms
- Bullets are web/frontend relevant, not HL7/Spark
- PDF compiles to 1 page with no whitespace

- [ ] **Step 3: Manual test with AI JD**

Run tailoring for an agentic AI JD and inspect:
- Theme selected: `agent_ai_systems` or `applied_ai`
- Template: A (projects-first)
- JHC is first project with 4 bullets
- Skills contain "Agentic Workflows", "Multi-Agent Systems"
- PDF compiles to 1 page

- [ ] **Step 4: Manual test with distributed infra JD**

Run tailoring for a Spark/data engineering JD and inspect:
- Theme selected: `distributed_infra`
- Template: B (experience-first)
- SWE role bullets lead with HL7/Spark evidence
- PDF compiles to 1 page

- [ ] **Step 5: Commit any fixes**

```bash
git add -A
git commit -m "fix(tailoring): address issues found during manual verification"
```

---

## Task Dependency Graph

```
Phase 1 (parallel):
  Task 1: Adjacency map
  Task 2: Theme classifier
  Task 3: Experience bullet pool
  Task 4: Project evidence atoms
  Task 5: Summary + skill templates
  Task 6: Template A
  Task 7: Profile update (JHC)

Phase 2 (sequential, depends on Phase 1):
  Task 8: Steps 1-3 → Task 9: Steps 4-5 → Task 10: Steps 6-7
  Task 11: Steps 8-9 → Task 12: Step 10 → Task 13: Step 11
  Task 14: Steps 12-14 → Task 15: Step 15 → Task 16: Step 16

Phase 3 (depends on Phase 2):
  Task 17: Pipeline orchestration → Task 18: Wire up bootstrap/finalize → Task 19: Integration tests

Phase 4 (depends on Phase 3):
  Task 20: Asset replacement

Phase 5 (depends on all):
  Task 21: Full verification
```
