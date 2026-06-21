# SPU Admission Chatbot - Professional Enhancement TODO

Generated: 2026-06-21
Recommended project start: 2026-06-22
Target production-ready finish: 2026-07-19
Primary goal: lower operating cost while improving answer quality, security, reliability, and maintainability.

This TODO is based on a local code review of the current repository plus current official documentation and pricing pages listed in the Sources section.

## 1. Current Project Snapshot

The project is a bilingual English/Arabic RAG chatbot for Syrian Private University admissions. It currently uses:

- FastAPI microservices:
  - `Services/Data_Loader`
  - `Services/Data_Splitting`
  - `Services/Embedding_Store`
  - `Services/RAG_Service`
  - `Services/QA_Chatting`
- Qdrant for vector storage.
- BAAI/bge-m3 for multilingual dense+sparse embeddings.
- OpenAI Responses API with `gpt-4.1-mini` by default, configurable to `gpt-4.1`.
- Vite + React + TypeScript frontend in `Services/spu-ai-connect-main`.
- Docker Compose for backend infrastructure.

### Critical Findings

- The repository does not include the `Data/` folder required by `docker-compose.yml`, so ingestion cannot run from a clean checkout.
- Arabic text in code, README, frontend translations, prompts, and metadata maps appears mojibaked/corrupted. This directly harms Arabic UX and metadata extraction.
- The frontend admin password is hardcoded in client-side code (`Services/spu-ai-connect-main/src/components/admin/AdminAuth.tsx`), so admin protection is not real security.
- Admin and ingestion endpoints are unauthenticated.
- `allow_origins=["*"]` is used with credentials in backend CORS settings.
- The current QA service can call the expensive 70B LLM multiple times for one user question: filter extraction, optional query expansion, then answer generation.
- `Embedding_Store` exposes a hybrid search endpoint but the `min_score` request parameter is not applied after Qdrant RRF fusion.
- `RAG_Service.get_query_embedding()` expects `data["embeddings"]`, but `Embedding_Store /embed` returns `dense_embeddings` and `sparse_embeddings`.
- Qdrant client versions differ across services (`1.7.3` in RAG service, `1.10.1` in Embedding Store), while the Qdrant server image is `v1.10.1`.
- The pipeline is not idempotent: every ingest creates random UUIDs, so rerunning the pipeline can duplicate chunks instead of updating by source/hash.
- Frontend demo fallbacks can turn real backend failures into fake success.
- A source-independent smoke `eval_dataset.json` is present, but the 120-item source-backed gold dataset still requires approved admissions documents.
- No CI, test suite, dependency audit, budget tracking, or production deployment profile is present.

## 2. Success Definition

The project is "production-ready" when all of these are true:

- A clean checkout can ingest approved source documents and answer both Arabic and English questions.
- Arabic text displays correctly everywhere.
- Admin actions require server-side authentication.
- The chatbot refuses unsupported answers instead of guessing.
- Every answer includes source metadata with enough detail to audit the response.
- The system has an evaluation dataset with quality gates for retrieval, grounding, correctness, and Arabic quality.
- Per-request LLM cost, model, provider, latency, token count, retrieved chunk count, and cache status are logged.
- Average cost per useful answer is reduced by at least 50 percent from the current baseline without failing quality gates.
- Docker Compose can start services in a reliable order with health checks and no unauthenticated public admin/vector endpoints.
- README and `.env.example` explain setup, ingestion, evaluation, and deployment.

## 3. Recommended Timeline

Use these dates if work starts Monday, 2026-06-22. If work starts later, shift dates by the same number of days.

| Phase | Dates | Objective | Finish Criteria |
| --- | --- | --- | --- |
| Phase 0 | 2026-06-22 to 2026-06-23 | Baseline, data audit, and branch setup | Current behavior, cost, and missing assets are documented |
| Phase 1 | 2026-06-24 to 2026-06-28 | Fix data, Arabic encoding, ingestion idempotency | Clean ingestion works from approved documents |
| Phase 2 | 2026-06-29 to 2026-07-03 | Security and production blockers | Admin, CORS, secrets, and destructive APIs are protected |
| Phase 3 | 2026-07-04 to 2026-07-08 | Retrieval and answer quality | Evaluation suite proves retrieval and answers are reliable |
| Phase 4 | 2026-07-09 to 2026-07-12 | Cost optimization | Lower-cost model route passes quality gates |
| Phase 5 | 2026-07-13 to 2026-07-16 | Frontend/admin polish and observability | UI shows true states, metrics, errors, and citations |
| Phase 6 | 2026-07-17 to 2026-07-19 | Deployment hardening and launch review | Production checklist passes |

## 4. P0 - Immediate Blockers

Start these first. Do not spend serious time on model swaps before these are done.

### P0-01 Restore Source Data and Create a Data Manifest

- Start: 2026-06-22
- Finish target: 2026-06-23
- Files: `Data/`, `.gitignore`, `Services/Data_Loader/app.py`, new `Data/manifest.json`
- Problem: `Data/` is ignored and missing, but Docker mounts it into the loader.
- Tasks:
  - Decide whether admissions source documents are public, private, or generated artifacts.
  - If private, keep them ignored but add `Data/README.md` with required filenames and acquisition steps.
  - If public, commit sanitized Markdown or source PDFs.
  - Add `Data/manifest.json` containing `source`, `language`, `faculty`, `doc_category`, `version`, `official_date`, `checksum`, and `visibility`.
  - Make ingestion use manifest metadata first and filename metadata only as fallback.
- Finish when:
  - `docker compose up` can find the data path.
  - `/scan` returns real documents.
  - Each document has stable metadata independent of Arabic filename parsing.

### P0-02 Fix UTF-8 Arabic Text Corruption

- Start: 2026-06-22
- Finish target: 2026-06-25
- Files:
  - `README.md`
  - `Services/QA_Chatting/app.py`
  - `Services/Data_Loader/app.py`
  - `Services/Data_Splitting/app.py`
  - `Services/spu-ai-connect-main/src/i18n/locales/ar.json`
  - `Services/spu-ai-connect-main/src/pages/ChatPage.tsx`
  - `Services/spu-ai-connect-main/src/pages/AdminPage.tsx`
  - `docling.py`
  - `evaluate_system.py`
- Problem: Arabic strings and symbols appear corrupted. This breaks Arabic UI, prompts, regex/entity maps, fallback text, and metadata detection.
- Tasks:
  - Replace mojibake strings with valid UTF-8 Arabic from an approved source.
  - Add an encoding check script that fails on common mojibake sequences.
  - Normalize Arabic text during ingestion using a dedicated utility: Unicode normalization, optional diacritic removal, tatweel removal, punctuation normalization, and whitespace cleanup.
  - Keep raw text and normalized text separately if citations must preserve exact source wording.
- Finish when:
  - Arabic UI strings render correctly.
  - Arabic quick actions send readable Arabic.
  - Metadata extraction recognizes Arabic faculty/category names.
  - Encoding check runs in CI.

### P0-03 Replace Fake Admin Security with Server-Side Auth

- Start: 2026-06-24
- Finish target: 2026-06-28
- Files:
  - `Services/spu-ai-connect-main/src/components/admin/AdminAuth.tsx`
  - `Services/spu-ai-connect-main/src/pages/AdminPage.tsx`
  - `Services/Data_Loader/app.py`
  - `Services/Embedding_Store/app.py`
  - `Services/QA_Chatting/app.py`
  - new backend auth module
- Problem: The password is hardcoded in frontend JavaScript. Anyone can inspect or bypass it.
- Tasks:
  - Move admin login to a backend endpoint.
  - Store `ADMIN_PASSWORD_HASH` or use an identity provider.
  - Return short-lived signed JWT or secure httpOnly cookie.
  - Require admin auth for `/auto-pipeline`, `/scan`, `/stats`, `/delete_collection`, and any destructive or operational endpoints.
  - Remove demo success fallbacks from admin actions.
- Finish when:
  - Admin routes fail with 401/403 without a valid token.
  - Password is not present in frontend bundle.
  - Pipeline/delete actions are impossible from unauthenticated browser requests.

### P0-04 Make Ingestion Idempotent

- Start: 2026-06-24
- Finish target: 2026-06-28
- Files:
  - `Services/Data_Loader/app.py`
  - `Services/Data_Splitting/app.py`
  - `Services/Embedding_Store/app.py`
- Problem: Reingestion creates new random point IDs and can duplicate all chunks.
- Tasks:
  - Generate stable chunk IDs from `source + version + page + heading + chunk_index + content_hash`.
  - Store `source_id`, `source_version`, `chunk_hash`, `ingested_at`, and `content_hash`.
  - Before upsert, delete or overwrite chunks for changed sources only.
  - Add a dry-run mode that reports added/changed/removed chunks.
- Finish when:
  - Running the pipeline twice with unchanged data produces the same point count.
  - Updating one source only changes chunks for that source.
  - Admin stats show accurate `changed`, `added`, `deleted`, and `unchanged` counts.

### P0-05 Build a Minimum Evaluation Dataset

- Start: 2026-06-25
- Finish target: 2026-06-30
- Files:
  - `eval_dataset.json`
  - `evaluate_system.py`
  - new `evaluation/README.md`
- Problem: There is an evaluation script, but no dataset in this checkout.
- Current status: A smoke dataset and production-grade evaluation runner exist. The full 120-item source-backed dataset remains pending official reviewed source documents.
- Tasks:
  - Create at least 120 questions: 60 Arabic, 60 English.
  - Cover faculties, fees, admission requirements, curriculum, regulations, contact info, missing information, follow-up questions, and adversarial prompts.
  - For each item include `question`, `language`, `category`, `ground_truth_answer`, `must_cite_sources`, `expected_doc_category`, and optional `expected_faculty`.
  - Track retrieval hit@k, context precision, faithfulness/grounding, answer correctness, refusal correctness, latency, and estimated cost.
  - Add a small "smoke eval" subset for fast CI.
- Finish when:
  - `evaluate_system.py` can run against the local service.
  - The report includes pass/fail thresholds.
  - New model or prompt changes must pass the eval before merge.

## 5. P1 - Retrieval Quality and RAG Correctness

### P1-01 Apply `min_score` After Hybrid RRF Search

- Start: 2026-07-01
- Finish target: 2026-07-01
- Files: `Services/Embedding_Store/app.py`
- Problem: `/search` accepts `min_score` but does not filter fused results by it.
- Tasks:
  - Apply score filtering after `query_points(... FusionQuery(RRF) ...)`.
  - Log score distribution for tuning.
  - Return `min_score_applied: true` in debug metadata.
- Finish when:
  - Low-similarity queries return no sources instead of weak sources.
  - Missing-info tests return the approved fallback answer.

### P1-02 Fix Broken RAG Diagnostic Endpoints

- Start: 2026-07-01
- Finish target: 2026-07-02
- Files: `Services/RAG_Service/app.py`, `Services/Embedding_Store/app.py`
- Problems:
  - `get_query_embedding()` expects `data["embeddings"]`, but `/embed` returns `dense_embeddings`.
  - `collection-stats` assumes an unnamed vector config, but the collection uses named vectors.
- Tasks:
  - Standardize `/embed` response shape.
  - Update diagnostic code to support named vectors.
  - Add contract tests for `/embed`, `/search`, `/retrieve`, `/collection-info`, and `/collection-stats`.
- Finish when:
  - `/search-quality` and `/collection-stats` work with the hybrid collection.

### P1-03 Add Qdrant Payload Indexes

- Start: 2026-07-02
- Finish target: 2026-07-03
- Files: `Services/Embedding_Store/app.py`
- Tasks:
  - Create keyword indexes for:
    - `metadata.faculty`
    - `metadata.doc_category`
    - `metadata.source`
    - `metadata.language`
  - Create text indexes for searchable headers if needed:
    - `metadata.header_1`
    - `metadata.header_2`
    - `metadata.header_3`
  - Add an index migration endpoint or startup migration.
- Finish when:
  - Filtered search latency is measured before/after.
  - Filters work in Qdrant strict/cloud-compatible mode.

### P1-04 Improve Chunking for Admissions Documents

- Start: 2026-07-02
- Finish target: 2026-07-05
- Files: `Services/Data_Splitting/app.py`
- Tasks:
  - Replace fixed character splitting with token-aware splitting.
  - Preserve page number, table title, heading path, faculty, year, semester, and document category.
  - Treat tables and fee schedules as atomic chunks when possible.
  - Use smaller chunks for direct facts and larger chunks for regulations/curriculum narratives.
  - Add overlap based on headings, not only characters.
- Finish when:
  - Evaluation shows improved source hit@k and less cross-faculty confusion.
  - Fee/admission table questions retrieve the exact relevant table chunk.

### P1-05 Add Optional Reranking

- Start: 2026-07-04
- Finish target: 2026-07-08
- Files: `Services/Embedding_Store/app.py`, `Services/RAG_Service/app.py`
- Tasks:
  - Retrieve top 20 candidates by hybrid search.
  - Rerank to top 4-6 chunks using a multilingual reranker or a low-cost cross-encoder.
  - Compare with current top 8 direct RRF.
  - Keep reranking configurable because it adds latency.
- Finish when:
  - Evaluation proves reranking improves grounding or allows fewer context chunks without quality loss.
  - Average prompt context tokens are reduced.

### P1-06 Make Metadata Extraction Deterministic First

- Start: 2026-07-04
- Finish target: 2026-07-06
- Files: `Services/QA_Chatting/app.py`, new shared taxonomy file
- Problem: LLM-based filter extraction is expensive and can be inconsistent.
- Tasks:
  - Create a bilingual taxonomy for faculties, categories, years, semesters, common aliases, and abbreviations.
  - Use deterministic rules and fuzzy matching first.
  - Call a cheap/small model only when deterministic confidence is low.
  - Return extraction confidence in metadata.
- Finish when:
  - At least 90 percent of eval dataset filters are extracted without a 70B call.
  - Filter extraction failures are logged for taxonomy improvement.

## 6. P1 - Cost Optimization Without Quality Loss

### P1-07 Add Token, Cost, and Latency Accounting

- Start: 2026-06-29
- Finish target: 2026-07-02
- Files: `Services/QA_Chatting/app.py`, new `Services/common` or shared module
- Tasks:
  - Log for every LLM call:
    - request id
    - conversation id
    - model
    - provider if available
    - route purpose: `filter`, `rewrite`, `answer`, `judge`
    - input tokens
    - output tokens
    - latency
    - estimated cost
    - cache hit/miss
  - Add daily and monthly budget summary endpoint for admins.
  - Add alert thresholds for abnormal token use.
- Finish when:
  - Admin dashboard shows daily spend estimate and average cost per answer.
  - Evaluation report includes total estimated cost.

### P1-08 Reduce LLM Calls Per Question

- Start: 2026-07-03
- Finish target: 2026-07-07
- Files: `Services/QA_Chatting/app.py`
- Current likely cost issue: one user question can make 2-3 hosted LLM calls.
- Tasks:
  - Use deterministic filter extraction by default.
  - Only rewrite a query when the user query has pronouns, ellipsis, or follow-up indicators.
  - Use a cheap route for query rewriting.
  - Combine extraction and rewrite into one small-model call when needed.
  - Never call rewrite/extraction for simple greetings or out-of-domain messages.
- Finish when:
  - Average hosted LLM calls per normal question is <= 1.2.
  - Evaluation quality does not regress.

### P1-09 Add Response and Retrieval Caching

- Start: 2026-07-05
- Finish target: 2026-07-09
- Files: `Services/QA_Chatting/app.py`, new cache service/module
- Tasks:
  - Cache query embeddings by normalized query.
  - Cache retrieval results by normalized query + filters + collection version.
  - Cache final answers for stable FAQ questions by normalized query + source version + language.
  - Invalidate caches when ingestion changes the source version.
  - Add cache hit metrics.
- Finish when:
  - Repeated common admissions questions avoid LLM calls or reduce context processing.
  - Cache invalidation works after data update.

### P1-10 Add Model Router and Benchmark Candidates

- Start: 2026-07-08
- Finish target: 2026-07-12
- Files: `Services/QA_Chatting/app.py`, `evaluate_system.py`, `.env.example`
- Tasks:
  - Make OpenAI model selection configurable through environment variables.
  - Add routing tiers:
    - `tiny`: greetings, language detection, query rewrite, metadata extraction.
    - `standard`: normal admission Q&A.
    - `premium`: complex regulations or low-confidence retrieval.
  - Benchmark these OpenAI candidates:
    - Default low-cost route: `gpt-4.1-mini`
    - Higher-quality route: `gpt-4.1`
    - Ultra-low-cost route only if quality passes eval: `gpt-4.1-nano`
    - Newer OpenAI mini/nano routes if official docs show better score-per-dollar.
  - Choose by eval score per dollar, not by model size.
- Finish when:
  - A lower-cost route passes the same quality gates as current baseline.
  - The chosen route and fallback route are documented.

### P1-11 Trim Prompt and Context Tokens

- Start: 2026-07-07
- Finish target: 2026-07-10
- Files: `Services/QA_Chatting/app.py`
- Tasks:
  - Remove duplicated prompt blocks between streaming and non-streaming functions.
  - Keep a single prompt template file.
  - Shorten system prompt while preserving grounding, language, missing-data, and citation behavior.
  - Limit context by token budget, not character count.
  - Dynamically set `k`: start with 4, increase only if retrieval confidence is low.
  - Dynamically set max answer tokens by question type.
- Finish when:
  - Average input tokens per answer decreases by at least 30 percent.
  - No quality regression in evaluation.

## 7. P1 - Security, Safety, and Abuse Resistance

### P1-12 Lock Down CORS

- Start: 2026-06-29
- Finish target: 2026-06-30
- Files: `Services/QA_Chatting/app.py`, `Services/Data_Loader/app.py`
- Tasks:
  - Replace wildcard CORS with environment-controlled allowlist.
  - Separate dev origins from production origins.
  - Keep credentials disabled unless actually needed.
- Finish when:
  - Only approved frontend domains can call protected APIs in production.

### P1-13 Add Rate Limits, Request Limits, and Abuse Controls

- Start: 2026-06-30
- Finish target: 2026-07-03
- Files: `Services/QA_Chatting/app.py`, reverse proxy config if added
- Tasks:
  - Limit request body size.
  - Limit `k`, `max_tokens`, conversation history length, and concurrent streams.
  - Add per-IP and per-session rate limits.
  - Add timeout and circuit breaker for LLM provider failures.
  - Add safe error messages that do not reveal internals.
- Finish when:
  - Model-denial-of-service style requests cannot create unbounded cost.
  - UI shows a clear rate-limit message.

### P1-14 Add Prompt Injection and Data Poisoning Tests

- Start: 2026-07-04
- Finish target: 2026-07-09
- Files: `eval_dataset.json`, `evaluate_system.py`, optional `promptfoo` or custom tests
- Tasks:
  - Add tests where retrieved documents include malicious instructions.
  - Add user prompts requesting system prompt, secrets, hidden docs, or policy bypass.
  - Validate that the answer only uses admissions facts from sources.
  - Add tests for unsupported questions and missing information.
- Finish when:
  - Security eval passes before deployment.
  - Prompt injection failures are tracked as release blockers.

### P1-15 Protect Qdrant and Operational Endpoints

- Start: 2026-06-30
- Finish target: 2026-07-03
- Files: `docker-compose.yml`, `Services/Embedding_Store/app.py`
- Tasks:
  - Do not expose Qdrant dashboard publicly in production.
  - Configure Qdrant API key or network isolation for production.
  - Require admin auth for delete collection.
  - Add confirmation token for destructive operations.
- Finish when:
  - Public traffic cannot reach Qdrant directly.
  - Delete collection requires authenticated admin and explicit confirmation.

### P1-16 Secure Secrets

- Start: 2026-06-29
- Finish target: 2026-07-01
- Files: `docker-compose.yml`, `.env.example`, backend config modules
- Tasks:
  - Add `.env.example` with required variables and no real secrets.
  - Consider Docker Compose secrets for production.
  - Support `_FILE` variants for `OPENAI_API_KEY`, admin password hash, and any API keys.
  - Never log secrets or Authorization headers.
- Finish when:
  - Secrets are not hardcoded or committed.
  - Production docs explain secret setup.

## 8. P2 - Frontend and Admin UX

### P2-01 Replace Demo Fallbacks with Real Error States

- Start: 2026-07-13
- Finish target: 2026-07-14
- Files:
  - `Services/spu-ai-connect-main/src/pages/ChatPage.tsx`
  - `Services/spu-ai-connect-main/src/pages/AdminPage.tsx`
- Tasks:
  - Remove fake success/demo fallback responses.
  - Show connection errors, backend errors, rate limits, and timeouts.
  - Add retry button for transient failures.
  - Add abort/cancel for streaming response.
- Finish when:
  - Backend failure is visible and not presented as chatbot success.

### P2-02 Make API Endpoints Environment Driven

- Start: 2026-07-13
- Finish target: 2026-07-14
- Files: frontend `.env.example`, `AdminPage.tsx`, `ChatPage.tsx`
- Tasks:
  - Replace hardcoded admin API URLs with `VITE_API_BASE_URL`.
  - Route all admin and chat API calls through a typed API client.
  - Document dev/prod env vars.
- Finish when:
  - Frontend can run against localhost, staging, or production without code changes.

### P2-03 Improve Source Citation UI

- Start: 2026-07-14
- Finish target: 2026-07-15
- Files: `ChatPage.tsx`, backend source metadata
- Tasks:
  - Show source title, document category, faculty, page, heading path, and last updated date.
  - Hide raw internal chunk IDs by default.
  - Add "copy source excerpt" and "open document" if source files are public.
  - Display confidence as "high/medium/low" using calibrated thresholds, not raw arbitrary percentages.
- Finish when:
  - A human can verify each answer from visible source metadata.

### P2-04 Fix Arabic RTL and Localized Copy

- Start: 2026-07-13
- Finish target: 2026-07-16
- Files: frontend i18n and layout components
- Tasks:
  - Replace corrupted Arabic translations.
  - Review all Arabic text with a native speaker.
  - Ensure source panels, tables, timestamps, and markdown render correctly in RTL.
  - Add Arabic smoke screenshots for visual regression.
- Finish when:
  - Arabic and English UX are both production quality.

### P2-05 Admin Dashboard Enhancements

- Start: 2026-07-15
- Finish target: 2026-07-17
- Files: `AdminPage.tsx`, backend stats endpoints
- Tasks:
  - Show ingestion status from backend instead of simulated stages.
  - Show live logs or job history.
  - Show document version, chunk count, changed sources, failed files, and cost metrics.
  - Add evaluation run button for admins.
  - Add backup/snapshot status.
- Finish when:
  - Admin dashboard reflects real backend state only.

## 9. P2 - DevOps, Deployment, and Reliability

### P2-06 Add Health Checks and Startup Readiness

- Start: 2026-07-01
- Finish target: 2026-07-03
- Files: `docker-compose.yml`, all FastAPI services
- Tasks:
  - Add health checks to every service.
  - Use `depends_on` with `condition: service_healthy` where supported.
  - Add startup checks for Qdrant and embedding readiness.
  - Add restart policies.
- Finish when:
  - `docker compose up` starts services reliably from a clean environment.
  - QA service does not start accepting traffic until dependencies are ready.

### P2-07 Add Frontend Docker Service and Reverse Proxy

- Start: 2026-07-16
- Finish target: 2026-07-18
- Files: `docker-compose.yml`, frontend Dockerfile, reverse proxy config
- Tasks:
  - Build frontend as static assets.
  - Serve behind Nginx/Caddy/Traefik.
  - Proxy API routes to backend.
  - Enable TLS in production.
  - Keep internal services off the public network.
- Finish when:
  - One compose profile can run the full app.
  - Only frontend/reverse-proxy ports are public.

### P2-08 Add Qdrant Snapshots and Restore Runbook

- Start: 2026-07-10
- Finish target: 2026-07-12
- Files: `docker-compose.yml`, new `docs/backup-restore.md`, scripts
- Tasks:
  - Add snapshot creation script.
  - Add restore script/runbook.
  - Schedule backups for production.
  - Test restore into a fresh Qdrant volume.
- Finish when:
  - Restore from snapshot is tested and documented.

### P2-09 Add Observability

- Start: 2026-07-10
- Finish target: 2026-07-16
- Files: backend services, compose observability profile
- Tasks:
  - Add structured JSON logs with request IDs.
  - Track latency for ingestion, embedding, retrieval, reranking, and generation.
  - Track error rates and provider failures.
  - Add metrics endpoint or Prometheus integration.
  - Add dashboard for cost, quality, and system health.
- Finish when:
  - Production incidents can be debugged without reading container stdout manually.

### P2-10 Add CI and Quality Gates

- Start: 2026-07-03
- Finish target: 2026-07-08
- Files: `.github/workflows/*` or local CI config
- Current status: A lightweight local quality gate, unit tests, and GitHub Actions workflow exist. Docker build tests, API contract tests, dependency audit, and smoke RAG eval against live services remain pending.
- Tasks:
  - Python formatting and linting.
  - TypeScript lint/build.
  - Backend unit tests.
  - API contract tests.
  - Docker build test.
  - Smoke RAG eval.
  - Dependency/security audit.
- Finish when:
  - Pull requests cannot merge if tests or smoke eval fail.

## 10. P3 - Architecture Improvements

### P3-01 Decide Whether to Keep Five Backend Microservices

- Start: 2026-07-08
- Finish target: 2026-07-12
- Files: service structure and deployment docs
- Reason: For a small university admissions chatbot, five Python services increase memory, networking, and operational cost.
- Options:
  - Keep microservices if each service has separate scaling, ownership, or deployment needs.
  - Consolidate into one FastAPI backend with modules for loader, splitter, embeddings, retrieval, and chat.
  - Keep Qdrant separate.
- Recommended default:
  - Consolidate `Data_Loader`, `Data_Splitting`, `RAG_Service`, and `QA_Chatting` into one backend service.
  - Keep `Embedding_Store` separate only if the embedding model needs dedicated resources.
- Finish when:
  - A short architecture decision record explains the choice.
  - Deployment memory and startup complexity are reduced or justified.

### P3-02 Move Configuration to Typed Settings

- Start: 2026-07-06
- Finish target: 2026-07-08
- Files: all backend services
- Tasks:
  - Use Pydantic Settings or equivalent.
  - Remove hardcoded URLs, model names, thresholds, CORS origins, and token limits.
  - Add validation for required env vars.
- Finish when:
  - Dev/staging/prod configuration is environment driven.

### P3-03 Add Background Jobs for Ingestion

- Start: 2026-07-12
- Finish target: 2026-07-17
- Files: backend admin pipeline
- Tasks:
  - Do not run ingestion as a long blocking GET request.
  - Use POST to create ingestion job.
  - Return job id.
  - Poll or stream progress.
  - Persist job status and logs.
- Finish when:
  - Admin can start, monitor, and inspect ingestion jobs safely.

### P3-04 Improve Document Conversion Workflow

- Start: 2026-07-04
- Finish target: 2026-07-10
- Files: `docling.py`, new ingestion/conversion module
- Tasks:
  - Integrate Docling conversion into a reproducible script or admin-only pipeline.
  - Support PDF/DOCX/XLSX if admissions documents arrive in those formats.
  - Preserve tables, page numbers, headings, and document metadata.
  - Store converted Markdown/JSON artifacts with checksums.
  - Add human review step before publishing into Qdrant.
- Finish when:
  - Source PDFs can be converted, reviewed, and ingested without manual copy-paste.

## 11. P3 - Testing Details

### Unit Tests

- Backend:
  - language detection
  - Arabic normalization
  - metadata extraction
  - deterministic filters
  - prompt building
  - cost estimation
  - cache key generation
  - ingestion idempotency
- Frontend:
  - API client error handling
  - streaming parser
  - admin auth state
  - RTL rendering smoke tests

### Contract Tests

- `POST /chat`
- `POST /chat/stream`
- `GET /health`
- `POST /retrieve`
- `GET /search`
- `POST /embed`
- `POST /embed-and-store`
- admin login
- pipeline job creation

### RAG Evaluation Gates

Initial suggested thresholds:

- Retrieval source hit@5: >= 90 percent
- Context precision: >= 80 percent
- Answer correctness: >= 90 percent on gold questions
- Faithfulness/grounding: >= 95 percent
- Missing-info refusal correctness: >= 95 percent
- Arabic response language correctness: >= 98 percent
- Average answer latency target: <= 6 seconds streaming first token, <= 20 seconds full response for normal questions
- Cost target after Phase 4: at least 50 percent below baseline cost per accepted answer

Do not freeze these thresholds forever. Update them after the first baseline report.

## 12. Cost Strategy

### Baseline First

Before changing models, record:

- Average input tokens per answer.
- Average output tokens per answer.
- Average number of LLM calls per user question.
- Model/provider price.
- Retrieval latency.
- Generation latency.
- Quality score.
- Refusal correctness.

### High-Impact Cost Reductions

Do these in order:

1. Remove unnecessary LLM calls for filter extraction and rewrite.
2. Reduce context tokens with better retrieval, reranking, and dynamic `k`.
3. Cache repeated queries and retrieval.
4. Route simple tasks to smaller/cheaper models.
5. Keep the premium model only for hard questions or low-confidence retrieval.
6. Evaluate self-hosting only after traffic volume is known.

### Model Routing Notes

The current OpenAI default is `gpt-4.1-mini` because it is much cheaper than full `gpt-4.1` while remaining strong for grounded admissions Q&A. Use full `gpt-4.1` for hard questions or if evaluation shows the mini model misses important Arabic or policy details. Consider newer OpenAI mini/nano routes only after checking official pricing and rerunning the eval suite.

These prices can change. Treat them as candidates to benchmark, not permanent decisions.

## 13. Quality Strategy

The chatbot should be optimized around admissions correctness, not generic model intelligence.

### Answer Policy

- Use only retrieved sources.
- Refuse when information is missing.
- Do not mix admission requirements with graduation requirements.
- Match the user's language.
- Include citations/source metadata.
- Use tables only when all compared values are available.
- Never let retrieved document text override system rules.

### Retrieval Policy

- Prefer exact metadata filters when high confidence.
- Use hybrid dense+sparse retrieval for bilingual and Arabic queries.
- Rerank before generation if initial search returns too much noise.
- Track score distribution and failed queries.
- Add human-reviewed aliases for faculties and categories.

### Data Policy

- Official admissions documents are the source of truth.
- Every source must have owner, version, date, checksum, and review status.
- No document enters production without review.
- Store original and converted forms.

## 14. Documentation TODO

- [ ] Rewrite README with correct UTF-8 text.
- [ ] Add architecture diagram that matches the current code, not only the intended design.
- [ ] Add `.env.example`.
- [ ] Add `docs/local-setup.md`.
- [ ] Add `docs/ingestion.md`.
- [ ] Add `docs/evaluation.md`.
- [ ] Add `docs/deployment.md`.
- [ ] Add `docs/security.md`.
- [ ] Add `docs/backup-restore.md`.
- [ ] Add `docs/model-routing.md`.
- [ ] Add architecture decision records for:
  - model routing
  - service consolidation
  - vector schema
  - auth strategy
  - data governance

## 15. Clean Code TODO

- [ ] Remove duplicate `import re` in `Services/QA_Chatting/app.py`.
- [ ] Replace mutable Pydantic defaults like `metadata: Dict[str, Any] = {}` with `Field(default_factory=dict)`.
- [ ] Deduplicate streaming and non-streaming prompt construction.
- [ ] Add shared constants/taxonomy module.
- [ ] Replace broad `except:` with explicit exceptions.
- [ ] Return proper HTTP status codes instead of `{"success": false}` with status 200 for backend failures.
- [ ] Add consistent response schemas.
- [ ] Add typed frontend API client.
- [ ] Remove unused `sendMessageToAPI` or use it as non-streaming fallback.
- [ ] Remove stale file `vite.config.ts.timestamp-1767723421533-c83fb74d0cb2b.mjs` if not needed.
- [ ] Standardize Python dependency versions across services.
- [ ] Standardize Qdrant client/server compatibility.

## 16. Launch Checklist

- [ ] Clean checkout setup works.
- [ ] Data source manifest exists.
- [ ] Arabic text is valid UTF-8.
- [ ] Admin auth is backend enforced.
- [ ] CORS allowlist configured.
- [ ] Secrets are not committed.
- [ ] Qdrant is not public.
- [ ] Qdrant snapshots tested.
- [ ] Ingestion is idempotent.
- [ ] Eval dataset exists.
- [ ] Eval thresholds pass.
- [ ] Cost baseline and optimized cost report exists.
- [ ] CI passes.
- [ ] Frontend build passes.
- [ ] Backend contract tests pass.
- [ ] Docker Compose health checks pass.
- [ ] README and deployment docs are complete.
- [ ] Production monitoring/logging enabled.
- [ ] Rollback plan documented.

## 17. Sources Used

- BAAI/bge-m3 model card: https://huggingface.co/BAAI/bge-m3
- OpenAI API pricing: https://openai.com/api/pricing/
- OpenAI GPT-4.1 announcement and pricing details: https://openai.com/index/gpt-4-1/
- OpenAI Models documentation: https://developers.openai.com/api/docs/models/all
- OpenAI streaming responses documentation: https://developers.openai.com/api/docs/guides/streaming-responses
- Qdrant hybrid queries and RRF: https://qdrant.tech/documentation/search/hybrid-queries/
- Qdrant performance optimization and quantization: https://qdrant.tech/documentation/ops-optimization/optimize/
- Qdrant payload/full-text indexing: https://qdrant.tech/documentation/manage-data/indexing/
- Qdrant text search and keyword payload indexes: https://qdrant.tech/documentation/search/text-search/
- Qdrant snapshots and restore: https://qdrant.tech/documentation/snapshots/
- FastAPI CORS documentation: https://fastapi.tiangolo.com/tutorial/cors/
- Docker Compose startup order and health checks: https://docs.docker.com/compose/how-tos/startup-order/
- Docker Compose secrets: https://docs.docker.com/compose/how-tos/use-secrets/
- OWASP Top 10 for LLM Applications: https://owasp.org/www-project-top-10-for-large-language-model-applications/
- Ragas RAG evaluation metrics: https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/
- Docling usage documentation: https://docling-project.github.io/docling/usage/
