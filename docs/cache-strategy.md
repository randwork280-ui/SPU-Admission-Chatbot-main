# Cache Strategy Decision

Date: 2026-06-21  
Status: implemented baseline, ready for measurement and tuning  
Scope: QA chat, retrieval, embeddings, OpenAI Responses API usage, and production cost controls

## Executive Decision

Do not build a manual "token cache" as the primary optimization.

Use OpenAI prompt caching opportunistically, but do not depend on it as the main cost-saving mechanism for this RAG chatbot. The current prompt shape has a short static prefix and then inserts dynamic retrieved chunks early, which means cross-question exact-prefix cache hits will be limited.

The implemented production path is:

1. Add per-request token, latency, cost, and cache telemetry.
2. Keep the prompt structured for automatic OpenAI prompt caching: stable instructions first, dynamic sources and user question last.
3. Add application-level retrieval caching keyed by normalized query, filters, collection version, `k`, and `min_score`.
4. Add exact-answer caching only for stable FAQ-style questions, keyed by source chunk hashes and prompt/model version.
5. Add embedding/query-vector caching in `Embedding_Store` for repeated searches.
6. Defer semantic answer caching until the eval dataset exists and proves it cannot return wrong admissions answers.

This gives strong savings without weakening grounded-answer correctness.

## Why Not A Manual Token Cache?

"Token cache" can mean several different things:

- Provider prompt cache: OpenAI reuses recently processed prompt prefixes.
- Generated-token cache: the app stores a previous final answer and replays it.
- Retrieval cache: the app stores retrieved chunks for a query/filter pair.
- Embedding cache: the app stores query vectors.
- KV cache: model-internal attention state cache, normally controlled by the model host, not by this application when using OpenAI.

For this project, manually caching generated tokens is the wrong first abstraction. Admissions answers must stay tied to current source documents. A cached answer without strict source-version and prompt-version keys can silently serve stale or unsupported facts.

OpenAI prompt caching is useful, but it is automatic and prefix-based. The application should make the prompt cache-friendly and log `cached_tokens`, not try to recreate provider-side KV caching.

## Official OpenAI Facts Used

OpenAI prompt caching:

- Works automatically for supported models, with no extra fee.
- Requires prompts of at least 1024 tokens.
- Matches exact prompt prefixes.
- Benefits from static content at the beginning and dynamic content at the end.
- Exposes `cached_tokens` in response usage details.
- Can use `prompt_cache_key` to improve routing for repeated prefixes.
- In-memory cache entries usually last minutes and up to one hour; extended retention is available for listed models and can last up to 24 hours.

Sources:

- OpenAI prompt caching guide: <https://developers.openai.com/api/docs/guides/prompt-caching>
- OpenAI cost optimization guide: <https://developers.openai.com/api/docs/guides/cost-optimization>
- OpenAI API pricing: <https://openai.com/api/pricing/>

## Current Application Flow

Current QA request path:

```text
Frontend
  -> QA_Chatting /chat or /chat/stream
  -> deterministic language/filter extraction
  -> optional LLM query rewrite for follow-ups
  -> RAG_Service /retrieve
  -> Embedding_Store /search
  -> BGE-M3 query embedding
  -> Qdrant hybrid dense+sparse RRF search
  -> QA_Chatting prompt build
  -> OpenAI Responses API generation
  -> streamed answer + source metadata
```

Important observations:

- The app already reduced LLM calls by making metadata extraction deterministic.
- The remaining normal request usually has one OpenAI generation call, with a possible rewrite call for follow-ups.
- Query embeddings are now cached in `Embedding_Store` with model-aware keys.
- Retrieval results are now cached in `QA_Chatting` with collection-version keys.
- The prompt system instructions are stable, but retrieved chunks are dynamic and appear before the question.
- Token/cost/latency telemetry is returned in chat metadata when the OpenAI API reports usage.
- Collection version endpoints now exist in `Embedding_Store` and `RAG_Service`, and ingestion updates the active version.

## Implemented In This Repository

- `Services/QA_Chatting/cache_utils.py`: bounded in-memory TTL cache, stable hashed keys, document signatures.
- `Services/QA_Chatting/telemetry.py`: OpenAI usage parsing and optional cost estimation.
- `Services/QA_Chatting/app.py`: request IDs, `cache_bypass`, retrieval cache, exact answer cache, prompt-cache parameters, token/cost metadata, `/cache/stats`.
- `Services/Embedding_Store/app.py`: query embedding cache, collection version updates after ingestion, `/collection-version`, `/cache/stats`.
- `Services/RAG_Service/app.py`: collection-version proxy and retrieval metadata pass-through.
- `.env.example` and `docker-compose.yml`: cache, prompt-cache, and cost telemetry configuration.

## Cache Option Analysis

| Option | Cost impact | Latency impact | Correctness risk | Complexity | Decision |
| --- | --- | --- | --- | --- | --- |
| OpenAI automatic prompt caching | Medium only when prompt prefixes repeat and exceed 1024 tokens | Medium to high on cache hits | Low | Low | Use opportunistically |
| `prompt_cache_key` | Helps routing for shared prefixes | Medium when traffic repeats | Low | Low | Add after telemetry |
| Extended prompt cache retention | Better hit rate for supported models | Medium | Privacy/config risk if not understood | Low to medium | Make configurable, not default blindly |
| Retrieval cache | High for repeated FAQs | High | Low if keyed by collection version | Medium | Implement first |
| Query embedding cache | No OpenAI cost savings, but reduces local compute | Medium | Low if keyed by embedding model/version | Medium | Implement after profiling or with retrieval cache |
| Exact answer cache | High for repeated FAQs | Very high | Medium if stale or over-broad | Medium | Implement with strict keys only |
| Semantic answer cache | Potentially high | Very high | High for admissions facts | High | Defer until eval gates exist |
| Self-hosted KV/token cache | Not available with OpenAI-hosted models | Potentially high for self-hosting | High operational complexity | Very high | Do not do now |
| Browser/local cache | Small | Small | Security and stale-answer risk | Low | Only cache UI session metadata, not answers |

## Recommended Architecture

### Layer 1: Telemetry First

Before caching behavior changes, log these fields for every LLM call:

- `request_id`
- `conversation_id`
- `route`: `rewrite` or `answer`
- `model`
- `input_tokens`
- `cached_input_tokens`
- `output_tokens`
- `latency_ms`
- `estimated_cost_usd`
- `retrieved_chunk_count`
- `cache_status`
- `collection_version`
- `prompt_version`

This is required because caching without measurement can hide stale-answer bugs and can create a false sense of savings.

### Layer 2: Prompt Cache Friendly Generation

Keep this prompt order:

```text
stable system/developer instructions
stable answer policy version
stable output/citation policy
stable examples or taxonomy, only if eval proves they help
dynamic retrieved source context
dynamic conversation summary
dynamic user question
```

Do not add a large static prompt just to cross 1024 tokens. That makes cache misses more expensive and can hurt latency. Add static content only if it improves answer quality or safety.

Recommended configurable request fields:

- `OPENAI_PROMPT_CACHE_KEY_PREFIX=spu-admissions`
- `OPENAI_PROMPT_CACHE_RETENTION=in_memory`
- `PROMPT_VERSION=admissions-rag-v1`

Use a cache key like:

```text
spu-admissions:{prompt_version}:{model}:{language_policy_version}
```

Only enable `24h` retention after confirming the selected model supports it and the deployment privacy posture accepts it.

### Layer 3: Retrieval Cache

Cache retrieval results before answer generation.

Key:

```text
retrieval:v1:
  collection_version:
  embedding_model:
  normalized_query:
  normalized_filters:
  k:
  min_score
```

Value:

```json
{
  "results": [],
  "score_stats": {},
  "created_at": "...",
  "ttl_seconds": 1800
}
```

Invalidation:

- Include `collection_version` in every key.
- Increment or replace `collection_version` after successful ingestion.
- Admin pipeline should report the new version.

Recommended TTL:

- Development: 5 minutes.
- Production: 30 to 60 minutes.
- Force bypass for admin diagnostics with `cache_bypass=true`.

### Layer 4: Query Embedding Cache

Cache query dense+sparse vectors in `Embedding_Store`.

Key:

```text
embedding:v1:
  embedding_model:
  model_max_length:
  normalized_query
```

Invalidation:

- Model name changes.
- normalization version changes.
- model max length changes.

This cache does not directly reduce OpenAI spend because BGE-M3 is local, but it can reduce latency, CPU/GPU load, and memory pressure.

### Layer 5: Exact Answer Cache

Add only after retrieval cache and token/cost telemetry are in place.

Key:

```text
answer:v1:
  model:
  prompt_version:
  answer_policy_version:
  normalized_question:
  language:
  normalized_filters:
  source_chunk_hashes:
  temperature:
  max_tokens
```

Rules:

- Cache only successful grounded answers.
- Do not cache answers generated from low-confidence retrieval.
- Do not cache prompt-injection, adversarial, or unsupported-question responses until security eval exists.
- Store sources with the cached answer.
- Stream cached answers by replaying short chunks to preserve frontend behavior.

Recommended TTL:

- 6 to 24 hours for exact FAQ cache.
- Immediate invalidation on ingestion version change.

### Layer 6: Semantic Cache, Later

Do not use semantic answer caching in the first production release.

Reason: admissions questions can differ by faculty, year, semester, regulation, or date. A semantic cache hit on a "similar" question can serve a fluent but wrong answer. This is especially risky for Arabic variants and short questions like "what about medicine?" after different conversation contexts.

Consider semantic caching only when all are true:

- Evaluation dataset exists.
- Retrieval hit@k and refusal gates pass.
- Cache audit logs can explain why a cached answer was reused.
- Similarity threshold is high and metadata filters match exactly.
- Admin can inspect and purge cache entries.

## Redis Or In-Memory?

Use in-memory cache only for local development and proof of value.

Use Redis or Valkey for production if any of these are true:

- More than one QA service replica.
- Admin dashboard needs cache metrics.
- Cached answers must survive container restart.
- You need centralized invalidation after ingestion.

Recommended production cache backend:

```text
CACHE_BACKEND=redis
REDIS_URL=redis://redis:6379/0
CACHE_NAMESPACE=spu-admissions
```

Recommended development backend:

```text
CACHE_BACKEND=memory
```

## Security And Data Governance

Caching must not weaken the answer policy.

Controls:

- Never cache raw Authorization headers, admin tokens, or OpenAI API keys.
- Never let user-controlled text become a cache namespace.
- Hash long query/cache key components to avoid storing sensitive free text in Redis keys.
- Store full query text only if privacy policy permits; otherwise store salted hashes and metrics.
- Include source version and source chunk hashes in answer-cache keys.
- Add `cache_bypass=true` for admin debugging.
- Add `cache_purge` admin action after server-side auth.
- Log cache hit/miss without logging secrets.

Prompt caching privacy:

- OpenAI states prompt caches are not shared between organizations.
- Extended prompt caching can temporarily persist key/value tensors up to the retention limit, so retention should be an explicit deployment decision.

## Cost Model

Caching value depends on traffic shape.

Let:

- `Q` = total questions per day.
- `R` = repeated normalized questions per day.
- `I` = average input tokens per answer.
- `O` = average output tokens per answer.
- `H` = cache hit rate.

Provider prompt caching helps only the cached input-token portion:

```text
savings ~= cached_input_tokens * (normal_input_price - cached_input_price)
```

Exact answer caching avoids the OpenAI generation call entirely:

```text
savings ~= H * (input_cost + output_cost)
```

Retrieval/embedding caching mostly saves latency and local compute:

```text
savings ~= reduced BGE-M3 encode time + reduced Qdrant search time
```

For this app, exact FAQ answer caching can outperform prompt caching for repeated questions, but only if it is keyed safely by source hashes and prompt/model version.

## Implementation Roadmap

### Step 1: Instrument

- Add `request_id` middleware.
- Capture OpenAI `usage` from non-streaming calls.
- For streaming calls, confirm SDK support for final usage events or add a non-stream fallback for admin/eval measurement.
- Add `cached_input_tokens` to metadata and logs.
- Add estimated cost table from env-configured model prices.

### Step 2: Prompt Cache Readiness

- Add optional `prompt_cache_key`.
- Add optional `prompt_cache_retention`.
- Keep prompt static prefix stable.
- Add `PROMPT_VERSION`.
- Log `cached_tokens`.

### Step 3: Retrieval Cache

- Add cache module in `QA_Chatting`.
- Start with in-memory TTL.
- Add Redis-compatible interface but do not require Redis locally.
- Key by collection version.

### Step 4: Collection Version

- Add a collection/source version endpoint.
- Update version after ingestion.
- Include version in chat metadata.

### Step 5: Exact Answer Cache

- Cache only high-confidence exact normalized questions.
- Include source chunk hashes.
- Replay cached answer as stream events.
- Add admin purge and metrics.

### Step 6: Eval-Gated Semantic Cache

- Build eval dataset first.
- Add negative/adversarial tests.
- Only then consider semantic cache.

## Decision Gates

Implement retrieval cache when:

- At least 10 percent of daily queries are repeated after normalization, or
- BGE-M3 query encode plus Qdrant search contributes more than 25 percent of p95 latency.

Implement exact answer cache when:

- At least 15 percent of questions are stable FAQs, and
- Evaluation confirms cached answers remain correct after source updates.

Use Redis when:

- Production runs multiple QA instances, or
- cache metrics/purge must work across restarts.

Do not implement semantic cache until:

- eval gates exist,
- source metadata is complete,
- and cache-hit explanations are visible to admins.

## Final Recommendation

The first production caching implementation should be:

```text
Telemetry + OpenAI prompt-cache readiness + retrieval cache
```

The second implementation should be:

```text
exact FAQ answer cache with source-hash invalidation
```

The project should not invest in a custom token/KV cache while it uses OpenAI-hosted models. That layer is provider-controlled. The app should instead make prompts cache-friendly, log cached-token usage, and cache deterministic application artifacts where it can enforce correctness.
