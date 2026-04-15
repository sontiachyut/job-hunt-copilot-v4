# Achyutaram Sonti — Master Profile

<!-- This file is the complete picture of who I am professionally.
     Not limited by resume space. Used to pick the right points for each job.
     Add everything — experience, projects, skills, achievements, context. -->

## Personal

- **Name:** Achyutaram Sonti
- **Email:** asonti1@asu.edu
- **Phone:** 602-768-6071
- **LinkedIn:** https://www.linkedin.com/in/asonti/
- **GitHub:** https://github.com/sontiachyut

## Education

- **Arizona State University, Tempe, USA** — MS in Computer Science, GPA 3.96/4.00 (Aug 2024 – May 2026)
- **Manipal Institute of Technology, India** — BTech in Electrical and Electronics Engineering, GPA 7.1/10 (Jul 2017 – Aug 2021)
- **Coursework:** Advanced Operating Systems, Cloud Computing, Foundation of Algorithms, Statistical Machine Learning, Mobile Computing, Computer Networks, Data Structures and Algorithms, OOP, C++

## Work Experience

### Software Engineer — Infinite Computer Solutions (Mar 2023 – Mar 2024)
- Built and maintained distributed, high-availability data services in Python and Scala on AWS (EMR, S3), processing 50M+ daily HL7 records (~580 TPS) powering real-time clinical analytics for 1,500+ hospitals with 24/7 uptime
- Developed ETL pipelines using Python, Apache Spark, and custom HL7 parsers, reducing processing time by 40% (6 hours to 3.6 hours) on 2TB+ daily data, enabling same-day analytics
- Optimized 25+ Apache Spark jobs with parallel processing and caching on AWS EMR, improving throughput by 50% (20K to 30K records/second) and reducing AWS costs by $15K monthly
- Designed monitoring and alerting for pipeline health, triaging data quality issues and resolving production incidents to meet SLAs

### Associate Software Engineer — Infinite Computer Solutions (Aug 2021 – Feb 2023)

#### Cloud Meraki — System Narrative
Cloud Meraki was a Kubernetes resource optimization platform. The system tracked resource usage patterns across 200+ microservices, identified over-provisioned workloads (services requesting more CPU/memory than they actually used), and recommended right-sized allocations. The end result: 25% reduction in cloud compute costs ($120K annually).

**How it worked (level of abstraction you can defend):**
1. **Observe:** Tracked resource usage patterns across the 200+ microservice fleet on Kubernetes
2. **Analyze:** Identified over-provisioned workloads — services requesting more CPU/memory than they consumed
3. **Recommend/Apply:** Right-sized CPU and memory allocations via vertical scaling (VPA)

**What you built specifically:**
- The optimizer engine and backend APIs in Golang and Java
- Integrated with Kubernetes to apply vertical scaling (VPA) decisions across microservice clusters
- Maintained 99.95% uptime during live workload adjustments — the hard part is resizing services without disrupting production traffic

**Testing and reliability:**
- 250+ unit and integration tests in Golang, Java, and Python across the optimization and autoscaling pipeline
- Caught 50+ critical bugs in scaling logic before production deployment
- At 200+ services, bugs in autoscaling cascade — testing wasn't optional, it was existential

#### Abstraction Boundary (Interview Safety)
- You don't remember specific implementation details (e.g., whether Prometheus was used for metrics collection, whether analysis was percentile-based)
- Bullets stay at a level you can confidently defend: "tracked usage → identified over-provisioned → recommended right-sized"
- The stack line includes Prometheus, which is accurate for the team's stack, but don't claim specific Prometheus query patterns unless you remember them
- Safe to discuss: Kubernetes resource requests/limits, VPA (Vertical Pod Autoscaler), the concept of right-sizing, the cost savings mechanism
- Avoid claiming: specific algorithm details, specific metric thresholds, internal architecture of the optimizer engine

#### Stack
Golang, Python, Java, Kubernetes, Docker, PostgreSQL, Jenkins, GitLab CI/CD, Prometheus

### Software Intern — Infinite Computer Solutions (Feb 2021 – Aug 2021)
- Deployed containerized job recruitment portal using React, Node.js, and Kubernetes across distributed clusters serving 5,000+ users

### SCAI Grader, CSE 360 — Arizona State University (Aug 2025 – Present)
- Served as a teaching assistant, conducting office hours and guiding 50+ students in building Java applications and debugging code
- Graded assignments and collaborated with Prof. Lynn Robert Carter to develop course materials on software engineering and OOP

## Projects

### Job Hunt Copilot v4 (Feb 2026 – Apr 2026)
- **Stack:** Python, SQLite, Multi-Agent Systems, Agentic Workflows, Review Gates
- Built an autonomous supervisor-agent in Python with durable SQLite state and lease-guarded execution across Gmail intake, resume tailoring, contact discovery, outreach, and delivery feedback
- Engineered DB-first, artifact-backed workflow contracts, review packets, and audit events so fresh sessions can reconstruct context, resume runs, and preserve traceable handoffs
- Added human-in-the-loop controls with repo-local launchd heartbeats, pause/escalation routing, and grouped review snapshots to keep autonomous runs bounded, inspectable, and recoverable
- Hardened the runtime with a spec-backed quality layer, 220+ automated tests, and 212 implemented required acceptance scenarios across supervisor control and downstream workflows
- **GitHub:** https://github.com/sontiachyut/job-hunt-copilot-v4

### Distributed Edge Face Recognition Pipeline (Jan 2025 – Apr 2025)
- **Stack:** Python, AWS IoT Greengrass v2, EC2, MQTT, SQS, AWS Lambda, S3, MTCNN, FaceNet
- Developed real-time edge computing pipeline deploying AWS IoT Greengrass Core on EC2 for MTCNN-based face detection via MQTT streaming, achieving 100% accuracy on 100 frames with sub-second latency

### Student Loan Retirement Matching Platform (Oct 2025)
- **Stack:** React, TypeScript, AWS Lambda, DynamoDB, S3, AWS Bedrock
- Won 2nd place at TIAA Spark Challenge 2025: Developed full-stack web application with serverless APIs for 45M+ eligible Americans under SECURE 2.0

### LinkedIn Job-Matching Assistant (Aug 2025 – Nov 2025)
- **Stack:** Python, FastAPI, Next.js, React, scikit-learn, FAISS, Neo4j
- Built a full-stack job-search web application using FastAPI, Next.js, and Neo4j, exposing RESTful APIs and user-centric interfaces for personalized job recommendations (NDCG 0.78)

### Context-Aware Health Monitoring App (Aug 2025 – Nov 2025)
- **Stack:** Kotlin, Android, Room, Coroutines
- Built an Android app measuring heart rate via camera-based PPG and respiratory rate via accelerometer data, with symptom tracking persisted in Room database using Repository pattern

## Awards & Leadership

- **2nd Place ($2,000) — TIAA Spark Challenge 2025:** Built secure financial planning system with AI-powered automation using React and AWS serverless architecture
- **Most Technically Sophisticated Project — InnovationHacks 25 ASU:** Developed AI agent-powered solution recognized among 50+ competing projects
- **Director of Technology (Volunteer) — AI Club at Thunderbird, ASU (Nov 2025 – Present):** Conduct workshops for 30+ graduate students on Agentic AI and tools like Lovable

## Skills

- **Languages:** Python, Golang, TypeScript, JavaScript, Java, Kotlin, Scala, C++, SQL, Bash
- **Frontend & Mobile:** React, Next.js, Node.js, Android (Kotlin), Swift
- **Cloud & DevOps:** AWS (EMR, EC2, S3, Lambda, SQS, DynamoDB, API Gateway), GCP, Kubernetes, Docker, Terraform, GitLab CI/CD, Linux
- **AI & Data:** LLMs, Agentic AI, Apache Spark, PostgreSQL, MySQL, DynamoDB, MongoDB, Redis
- **Systems:** Distributed Systems, Microservices, Load Balancing, gRPC, Protocol Buffers, System Design
- **Testing & Reliability:** Pytest, JUnit, Unit/Integration Testing, Monitoring, Debugging, Performance Profiling

## Metrics Bank

<!-- These numbers are SACRED. They come from real work and must be preserved in tailored resumes.
     When reframing bullets for a different track, always find a way to use these metrics.
     Numbers are the strongest credibility signal in screening. -->

### SWE Role (Mar 2023 – Mar 2024)
- **50M+** daily HL7 records ingested
- **~580 TPS** throughput
- **1,500+** hospitals served
- **24/7** uptime
- **40%** processing time reduction (6 hours → 3.6 hours)
- **2TB+** daily data volume
- **25+** Spark jobs optimized
- **50%** throughput improvement (20K → 30K records/sec)
- **$15K** monthly cost savings
- **>=99%** availability SLA

### Associate SWE Role (Aug 2021 – Feb 2023)
- **200+** microservices managed
- **3,500+** lines of Golang code
- **25%** cloud compute cost reduction
- **$120K** annual cost savings
- **99.95%** uptime maintained
- **250+** unit and integration tests
- **50+** critical bugs resolved

### Intern Role (Feb 2021 – Aug 2021)
- **5,000+** users served

### Projects
- **220+** automated tests and **212** implemented required acceptance scenarios (Job Hunt Copilot v4)
- **100%** accuracy on 100 frames, sub-second latency (Edge Face Recognition)
- **45M+** eligible Americans under SECURE 2.0 (TIAA Platform)
- **2nd place, $2,000** prize (TIAA Spark Challenge)
- **NDCG 0.78** recommendation accuracy (LinkedIn Assistant)
- **31,597** job records indexed (LinkedIn Assistant)
- **~50ms** search latency (LinkedIn Assistant)
- **50+** competing projects beaten (InnovationHacks — Most Technically Sophisticated)

### Teaching & Leadership
- **50+** students guided (SCAI Grader)
- **30+** graduate students in workshops (AI Club)

## Additional Context

### GE PCS / Mural Insights Platform (Software Engineer Project Deep-Dive, Evidence-Grounded)

- **Reconstruction status:** Built from project artifacts in `/Users/achyutaramsonti/Documents/Office/GE PCS` (architecture decks, concept TDRs, product specification, org chart), not from memory alone.
- **Program context:** GE Healthcare PCS "Data Analytics Platform Delivery" and "Distributed Data Platform / Data Mesh" initiative.
- **Problem being solved:** Hospital data was fragmented across EMR systems, patient monitoring systems, and device data silos. The platform aimed to unify this into reusable data products, analytics dashboards, and decision-support insights.

#### End-to-End System Narrative

- **Business objective:** Offer PCS customers a cloud-hosted analytics platform with curated/standardized data products, visualization, and AI/ML-ready datasets, instead of every customer building custom on-prem analytics infrastructure.
- **Primary users/personas:**
  - Customer clinical and operations users consuming KPI dashboards
  - Customer Tableau/site admins
  - BI/data engineers building pipelines and reports
  - GE platform operators/support teams
  - Clinical researchers/subscribers consuming curated datasets
- **Clinical domain:** Acute care (ICU/perinatal/monitoring contexts in artifacts), "hospital-to-home" continuum, clinician-facing and operations-facing analytics.

#### Architecture (High Level)

- **Platform pattern:** Distributed Data Mesh + Health Lakehouse architecture.
- **Core building blocks:**
  - Edge/on-ramp data ingress from hospital environments
  - Unified Data Highway for governed ingestion
  - Transient/Data Landing Zones
  - Health Lakehouse landing zone (core analytics substrate)
  - Domain-specific landing zones and data products
- **Cloud/data stack referenced in artifacts:**
  - Azure Data Factory (ingestion orchestration)
  - Azure PostgreSQL (raw HL7 source in Mural path)
  - ADLS Gen2 (lake storage)
  - Databricks/Spark (data processing)
  - Tableau (dashboard delivery)
  - Azure Log Analytics + Datadog (monitoring/observability)

#### Data Flow (As Reconstructed)

- **Ingress:** HL7 feeds from EMR/EHR and patient monitoring/device systems flow through edge/on-ramp to cloud pathways.
- **Mural Insights 2.2 interface path:** Raw HL7 in Azure PostgreSQL is copied by ADF (with private link) to ADLS Gen2.
- **Processing model:** Multi-stage pipeline in lakehouse:
  - **Bronze:** raw or curated-raw data for replay/reprocessing/audit
  - **Silver:** cleaned/standardized data (FHIR/OMOP standardization path in design docs)
  - **Gold:** business aggregates/features for analytics and downstream products
- **Consumption/egress patterns:** ODBC connectors, REST-style service endpoints, and Kafka-style subscription connectors were explicitly identified as target egress mechanisms.
- **Operating mode:** Architecture explicitly supports both **batch** and **streaming/near-real-time** workflows.

#### Product Outputs

- KPI dashboards and BI reporting (Tableau)
- Clinical decision support and operational analytics signals
- Domain-oriented reusable data products (not only one point solution)
- Data quality and usage metrics dashboards (including OMOP data quality patterns in discovery artifacts)

#### Reliability, Security, and Compliance Constraints

- **Reliability expectations in docs:** >=99% availability target for Mural Insights, alerting and automated data quality checks.
- **Observability model:** Pipeline/application logs, metrics, and audit events routed to centralized monitoring (Log Analytics, Datadog integrations).
- **Security model:** Multi-tenant isolation, restricted access patterns, encryption in motion and at rest, audit logging.
- **Regulatory/geo constraints:** Regional deployment and data residency/compliance concerns (for example GDPR) influenced multi-region strategy and tenant planning.

#### Scope Boundary Notes (Important for Resume Truthfulness)

- Some artifacts describe full target-state platform vision, while some sections explicitly mark parts as out of scope for the immediate phase.
- A recurring in-scope focus in design docs is HL7 ingress into the health lakehouse and pipeline foundation; broader mesh components are partly roadmap/phase-dependent.
- Resume/interview narratives should separate:
  - **implemented/owned work**
  - **team/platform target architecture**
  - **future-state design intent**

#### Likely Personal Ownership Zone (Conservative Framing)

- Pipeline engineering on HL7-oriented clinical data flows
- Data processing/reliability work in Databricks/Spark-style pipeline stages
- Data quality, monitoring/alerting, and incident/SLA support
- Integration-oriented engineering with standardized outputs for analytics consumers

#### Learning Notes (Project Vocabulary)

- **Data Mesh:** A domain-oriented data architecture where teams publish discoverable, reusable data products instead of one centralized monolith.
- **Landing Zone:** A governed cloud boundary/subscription/network slice where data/platform services run with policy/security controls.
- **Lakehouse:** Combines low-cost data lake storage with warehouse-like reliability/performance for BI + AI workloads.
- **Bronze/Silver/Gold:** Progressive data quality layers from raw ingest to standardized truth to business-ready aggregates.
- **HL7:** Widely used healthcare messaging format for exchanging clinical events and records.
- **FHIR:** Interoperability standard for structured healthcare data resources and API-oriented exchange.
- **OMOP CDM:** Common data model for standardizing observational health data to enable repeatable analytics/research.
- **DataOps:** Engineering discipline for automated, reliable, testable data delivery (analogous to DevOps for data pipelines).
- **Observability:** System visibility via logs, metrics, traces, and alerts to detect and resolve operational issues quickly.
- **Multi-tenancy:** Serving multiple customers from shared platform infrastructure with strict isolation boundaries.

### National Parks Biodiversity Visualization — CSE578 (Academic Project, Spring 2025)
- **Stack:** D3.js v7, JavaScript, HTML5, CSS3, Bootstrap 5, d3-force-boundary
- **What it is:** Interactive web visualization of species diversity across 60 U.S. National Parks — combines hierarchical treemaps with nested force-directed circular packing
- **Visualization design:**
  - Treemap: States → Parks → Species categories (3-level hierarchy)
  - Nested force simulation inside each park rectangle: circles = species categories, radius = species count, with collision detection + boundary constraints + drag interaction
  - Dynamic toggle: switch between species count and acreage as the sizing metric without page reload
- **Engineering highlights:**
  - Force-directed layout with 4 simultaneous forces: boundary constraints, center attraction, charge repulsion, collision detection
  - `Promise.all()` parallel CSV loading of 3 files including 17.5MB species dataset
  - Custom `d3-force-boundary` to keep circles within park rectangles dynamically
  - Ordinal color scale (state-level), proportional circle radius (5–30px), cursor-following tooltips
- **Data:** 60 National Parks, multi-category species taxonomies, park acreage data
- **GitHub:** https://github.com/sontiachyut/data-visualization

### Student Loan Retirement Matching Platform — TIAA Spark Challenge (Oct 2025)
- **Stack:** React, TypeScript, Vite, TailwindCSS, Recharts, Python, AWS Lambda (6 functions), AWS API Gateway (REST + WebSocket), AWS S3, AWS DynamoDB, AWS Amplify, AWS CloudWatch, Supabase (Auth + PostgreSQL with Row-Level Security), boto3, bcrypt
- **What it is:** Full-stack web platform helping ASU employees use SECURE 2.0 provisions to match student loan payments toward retirement savings — built in 72 hours at TIAA x ASU Fund the Future Spark Challenge 2025
- **Award: 2nd Place ($2,000)** — Team Bit by Bit (3 developers, 72-hour hackathon)
- **Architecture:** Serverless-first — React SPA → API Gateway (REST + WebSocket) → 6 Lambda functions → DynamoDB + PostgreSQL + S3
- **Key Lambda functions:**
  - `calculate_match_lambda` — EMI calculations, debt-to-income ratios, 10/20/30-year compound growth projections (6% APY), LLM-powered personalized recommendations with fallback
  - `financial_chatbot_advisor_v2` — WebSocket-based multi-turn financial chatbot with DynamoDB session persistence, LLM integration, 3 operating modes
  - `add_user_profile_lambda` — Auth with bcrypt (12 rounds), ASU ID validation
  - `admin-API` — 6 admin endpoints: user management, document verification, 5 business metrics dashboard
  - `rag-process-document-1` + `rag-get-presigned-url` — RAG pipeline for loan document analysis + secure S3 presigned URL access
- **Dual database strategy:** DynamoDB for real-time WebSocket sessions (low latency), PostgreSQL + Supabase RLS for sensitive employee financial data
- **AI integration:** LLM-powered financial advisor with context-aware multi-turn conversations + graceful degradation fallback to calculated recommendations
- **Security:** bcrypt-12 password hashing, Cognito auth, Supabase Row-Level Security, presigned S3 URLs, environment variable isolation
- **Scale:** Serverless architecture supports thousands of concurrent users, 45M+ eligible Americans under SECURE 2.0
- **GitHub:** https://github.com/ShivamGS/loan-platform

### Distributed Edge Face Recognition Pipeline — CSE546 (Academic Project, Jan–Apr 2025)
- **Stack:** Python, PyTorch, MTCNN, InceptionResnetV1 (VGGFace2), AWS (EC2, Lambda, SQS, S3, API Gateway, IoT Core, IoT Greengrass, ECR, SimpleDB), Flask, Docker, boto3
- **What it is:** Same face recognition pipeline implemented across 4 cloud architectures — IaaS (EC2), multi-tier auto-scaling, serverless (Lambda), and hybrid edge-cloud (Greengrass + Lambda) — to compare trade-offs in scalability, cost, and latency
- **4 architectures built:**
  1. **Single-tier IaaS (P1.1):** Python HTTP server on EC2 + S3 + SimpleDB key-value lookup
  2. **Multi-tier auto-scaling IaaS (P1.2):** Flask web tier + SQS queue + controller auto-scales app tier up to 15 EC2 instances, 100 concurrent threads, SSE streaming results to client
  3. **Serverless FaaS (P2.1):** Containerized Lambda (Docker + ECR) — face detection Lambda → SQS → face recognition Lambda. Module-level model loading for warm invocation reuse
  4. **Hybrid edge-cloud (P2.2):** IoT Greengrass runs MTCNN locally on edge device, sends only cropped faces to cloud Lambda — 10-100x bandwidth reduction vs. full images
- **ML pipeline:** MTCNN cascade (P-Net → R-Net → O-Net, 90% confidence threshold) for face detection → InceptionResnetV1 generates 512-dim embeddings → Euclidean distance matching
- **Key engineering decisions:** Queue-based decoupling (web/app tiers scale independently), two-phase EC2 scaling (restart stopped instances first — faster than cold launch), CPU-only PyTorch in Lambda (smaller container, faster deploy), edge preprocessing (MTCNN locally, <100ms, reduces cloud invocations)
- **Performance:** Detection 100-200ms, embedding 50-100ms, Lambda cold start ~5s, EC2 boot ~60s, warm Lambda invocation <100ms
- **GitHub:** https://github.com/sontiachyut/CSE546-Cloud-Computing

### Context-Aware Health Monitoring App — CSE535 (Academic Project, Aug–Nov 2025)
- **Stack:** Kotlin, Android (SDK 35), Room Database 2.6.0, Kotlin Coroutines, AndroidX Lifecycle (ViewModel/LiveData), Material Design 3, Gradle, JUnit, Espresso
- **What it is:** A health monitoring Android app that measures heart rate and respiratory rate using only built-in smartphone sensors (camera + accelerometer) — no specialized hardware required
- **Heart rate algorithm (PPG — Photoplethysmography):**
  - Captures 425 video frames via camera (~30 Hz), extracts 100×100px ROI per frame
  - Applies moving average smoothing, counts brightness peaks exceeding 3500-unit threshold
  - Formula: `BPM = detected_peaks × 60 / 4`
  - Valid range: 40–200 BPM with bounds checking and fallback
- **Respiratory rate algorithm (accelerometer-based):**
  - Computes acceleration magnitude `sqrt(x²+y²+z²)` at 50 Hz
  - Detects breathing motion via threshold (0.15g) on magnitude changes
  - Formula: `breaths/min = (peak_count / 45.0) × 30`
  - Valid range: 8–35 breaths/min
- **Architecture:** MVVM — 4 activities (Record, Symptoms, Summary, Main) + Repository pattern + Room/SQLite local persistence + Kotlin Coroutines + Flow for reactive updates
- **Symptom tracking:** 10-symptom severity rating system (nausea, fever, cough, etc.) persisted with each measurement record + timestamp
- **Key decisions:** Local-first processing (all data on device, privacy-preserving), lifecycle-aware coroutines (prevents ANR and memory leaks), singleton Room database, Repository abstraction for testability
- **GitHub:** https://github.com/sontiachyut/CSE535-Project1-Context-Monitoring-App

### LinkedIn Job-Matching Assistant — CSE573 (Academic Project, Aug–Nov 2025)
- **Stack:** Python, FastAPI, Next.js 15, React 19, TypeScript, Tailwind CSS, scikit-learn, Sentence-BERT (all-MiniLM-L6-v2), FAISS, Neo4j, RapidFuzz, Pydantic, Pandas
- **What it is:** An explainable job-search copilot that ingests a resume, searches 31,597 LinkedIn job postings, and ranks matches using Rasch Item Response Theory (IRT) — exposing per-requirement probabilities so users understand *why* they match a role
- **Core innovation — Rasch IRT scoring:** Custom implementation of the 1PL Rasch model `P(θ-b) = 1/(1+e^(-(θ-b)))` where θ = candidate ability (estimated from resume), b = requirement difficulty (pre-assigned via domain heuristics). Produces per-requirement match probability — fully transparent, no black box
- **Retrieval pipeline (3 methods):**
  - RapidFuzz fuzzy search — ~50ms, NDCG 0.58 (initial filtering)
  - TF-IDF (scikit-learn, bigrams) — ~200ms, NDCG 0.62 (lexical baseline)
  - Sentence-BERT embeddings + FAISS — ~2s, NDCG 0.74 (semantic search)
  - Rasch scoring — ~100ms, **NDCG 0.78** (best, explainable)
- **Architecture:** Next.js 15 frontend (API proxy pattern) → FastAPI backend → in-memory state + optional Neo4j graph. Multi-step UI: Resume upload → Dataset search → Rasch scoring display → Conversational assistant
- **Chatbot:** Intent-aware (keyword-based intent detection), context-injected responses using Rasch probabilities + skill gaps — no LLM, fully rule-based
- **Scale:** 31,597 job records, ~50ms search latency, ~150ms full pipeline
- **GitHub:** `/Users/achyutaramsonti/Desktop/Academics/Semantic Web Mining/CSE573-LinkedIn-Assistant`
- **Note:** Academic project — in-memory state (no DB), single-user prototype, DOCX parsing stubbed

### Distributed Content Recommendation Engine — CSE512: Distributed Database Systems (Academic Project)
- **Stack:** React, Node.js, Express, MongoDB (sharded cluster), Neo4j, Docker, Docker Compose
- **What it is:** A distributed social media content recommendation platform with Instagram-like UI, delivering personalized recommendations using a hybrid collaborative filtering + content-based algorithm
- **Architecture:**
  - MongoDB sharded cluster: 3 config servers + 3 shards × 3 replicas (9 containers) — horizontal scaling for transactional data
  - Neo4j graph database for multi-hop graph traversal and recommendation scoring
  - Real-time MongoDB → Neo4j sync via change streams (watch API) — eventual consistency without polling
  - React SPA frontend + Node.js/Express REST API backend
- **Algorithm:** Hybrid collaborative filtering — Neo4j Cypher query traverses user-content-tag graph (3 hops), ranks by tag overlap + common interactions, returns top 10 personalized recommendations
- **Scale:** 10 users, 60 content items, 1,000 interactions, ~140MB dataset
- **Key decisions:** Dual-database architecture (MongoDB for storage, Neo4j for graph traversal), change streams for real-time sync, batch MongoDB aggregation pipelines to minimize round trips
- **GitHub:** `/Users/achyutaramsonti/Desktop/Academics/Distributed Systems/Distributed-Content-Rec-engine-main`
- **Note:** Academic project — no production auth, sync is one-way (MongoDB→Neo4j)
