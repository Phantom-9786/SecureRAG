# Gemini parallel keys, quotas and model routing

This user-requested extension adds a peer key pool to Phase 3 and a generation/routing building
block for Phase 4. The database and RBAC design are unchanged. No Redis or extra service is added.

## Account subscriptions and API projects

Three owned Google accounts can supply three keys. Google AI Pro/Plus/Ultra subscription names
do not establish paid API quota or model access: direct API usage/billing is managed separately.
Eligible Cloud credits require the corresponding account/billing setup. Confirm API access first.
Normal quotas are applied by Cloud project/model, not by key. Map each key to its actual Cloud
project ID in AI Studio. Account emails are not quota IDs.

Unknown IDs deliberately share a `shared-project` quota bucket. Distinct accounts are not assigned
independent budgets just because their emails differ. Keys with the same project must use the same ID.

Official sources checked 2026-10-31:
- https://ai.google.dev/gemini-api/docs/google-ai-plans
- https://ai.google.dev/gemini-api/docs/rate-limits
- https://ai.google.dev/gemini-api/docs/models

## Active peers and limits

Authorized work -> choose model -> reserve quota -> select available peer key -> Gemini -> release capacity.

All keys are active peers. Selection rotates fairly among available keys, with one request in flight
per key and at most three total. Independent uploads/queries can run concurrently. A single question
is not sent to all three keys. Batches within one upload remain sequential; concurrent work shares
the pool. Retries can use another eligible peer, but there is no fixed primary/secondary/tertiary order.

Before every call the pool atomically reserves RPM, estimated input TPM and RPD by project/model.
UTF-8 bytes plus overhead provide a conservative estimate, not an exact Gemini tokenizer. Failed
attempts retain reservations. Daily counters reset at Pacific calendar boundaries. Embedding batches
shrink to fit the configured input budget. Brief waiting is bounded by the request deadline and
GEMINI_MAX_WAIT_SECONDS; exhausted capacity returns 429 + Retry-After during ingestion.

429 cools the whole project/model, honoring numeric/HTTP-date Retry-After and structured RetryInfo.
Recognized daily exhaustion blocks that scope until the next quota day. A sibling key cannot bypass
it. Other configured projects can serve requests within their own legitimate quotas. There is at most
one attempt per key per operation, with SDK retries disabled. Invalid keys are disabled; 403/404 block
that key/model pair; 402 disables the project's configured keys until restart/reconfiguration.
Temporary transport/server failures briefly cool a key. Invalid-input 400 is not blindly retried.
Raw provider errors, prompts and keys are not logged or echoed by this layer.

Default app budgets: 5 RPM, 10000 estimated input TPM, 100 RPD. These are conservative local settings,
not claims about Google's allowance. Configure budgets within your real per-project/model quotas.
Other apps' usage and exact remaining billing credits are not visible locally; Google is authoritative.

## Single-worker V1 boundary

The pool is thread-safe but process-local. Run one Uvicorn worker. Multiple workers/instances would
have separate counters, and restarting resets local counters. This is not a distributed rate limiter
or durable billing ledger; Google still enforces actual quotas. A shared limiter is needed before
scaling across processes. No new database tables are introduced for this V1 extension.

## Model selection

`rag/model_routing.py` uses explainable rules, not a learned difficulty predictor:
- Direct lookup defaults to the basic model.
- Comparison/analysis, multiple questions, larger authorized context or at least three source
  documents select the advanced model.
- Explicit basic/advanced mode overrides auto routing.
- Empty authorized evidence returns an insufficient-information answer without an API call.

The result includes a reason. Difficulty inference is imperfect; advanced models do not guarantee
correctness. Model IDs are configured after verifying account access. Busy advanced routes are not
silently downgraded. No model is chosen solely because an account has a consumer subscription.

`rag/generation.py` calls the selected model through the pool, with grounded-answer instructions,
and returns text/model/routing reason. Phase 4 now connects it to permission-filtered retrieval,
citation validation and owned conversation APIs. No public endpoint lets clients supply arbitrary
source context. The backend flow is verified; the frontend chat screen remains in Phase 5.

Embedding model stays gemini-embedding-001 at 1536 dimensions. Document/query embeddings must share
the same model and compatible retrieval task types. Different credentials may call the same model;
switching embedding families requires re-embedding rather than answer-style model routing.

## Private configuration

Fill backend/.env locally. Slots have been prepared without overwriting existing values:

```dotenv
GEMINI_API_KEY=key-from-account-one
GEMINI_API_KEY_2=key-from-account-two
GEMINI_API_KEY_3=key-from-account-three
GEMINI_PROJECT_ID=actual-cloud-project-one
GEMINI_PROJECT_ID_2=actual-cloud-project-two
GEMINI_PROJECT_ID_3=actual-cloud-project-three
GEMINI_MAX_PARALLEL_REQUESTS=3
GEMINI_MAX_WAIT_SECONDS=5
GEMINI_BASIC_MODEL=verified-basic-model-id
GEMINI_ADVANCED_MODEL=verified-advanced-model-id
```

Never paste credentials into chat. Optional scope overrides are a single-line JSON array. These
example numbers are illustrative app budgets, not verified provider quotas:

```dotenv
GEMINI_RATE_LIMITS=[{"project_id":"actual-cloud-project-one","model":"gemini-embedding-001","rpm":5,"tpm":10000,"rpd":100}]
```

Add entries for each relevant project/model. Duplicate keys/scope entries are rejected. Restart
after edits. Do not add duplicate keys to create apparent extra capacity.

```powershell
cd D:\RAG_Project\backend
uv sync --locked
uv run uvicorn app.main:app --workers 1
```

## Validation

Verified on 2026-10-31: **56 local tests passed**, Ruff and Python compilation passed, and the
real Neon rate-limited-ingestion regression passed. Eight database integration tests are opt-in
in the normal suite; only the new rate-limit regression was rerun against Neon for this change.
Subsequently, real credentials, embeddings and basic generation were verified; see
gemini-live-validation.md for advanced-model capacity limitations. The existing Starlette/httpx test-client
deprecation warning remains non-fatal.

```powershell
uv run pytest tests/test_gemini_pool.py tests/test_document_processing.py --tb=short
uv run ruff check .
$env:SECURERAG_RUN_DB_TESTS='1'
uv run pytest tests/test_documents_integration.py::test_rate_limited_ingestion_returns_retry_after_and_stays_inactive --tb=short
Remove-Item Env:SECURERAG_RUN_DB_TESTS
```

Mock HTTP transports exercise the real SDK. A three-party barrier proves simultaneous requests
across three keys. Other tests cover shared limits, TPM/RPD, cooldowns, daily exhaustion, bounded
recovery, capacity wake-up and selected-model generation. The database test checks 429/Retry-After
and inactive failed ingestion. These tests do not prove live account/model access; real keys,
project mappings, quotas and model IDs still require configuration/verification.
