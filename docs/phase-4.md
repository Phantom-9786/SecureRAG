# Phase 4: permission-aware RAG and conversations

## Deliverable

Protected conversation APIs, Gemini question embeddings, authorized exact vector retrieval,
bounded source context, grounded generation, validated citation labels and permission-aware
history. Existing users/roles/documents/chunks/conversations/messages/message_sources tables are
sufficient, so no database migration is introduced. Frontend chat belongs to Phase 5.

## Files and concepts

| File | Responsibility / concept |
|---|---|
| app/rag/retrieval.py | PostgreSQL joins, materialized authorized scope, cosine distance |
| app/rag/citations.py | Source labels, byte-bounded context, backend citation metadata |
| app/rag/embeddings.py | Query embeddings with RETRIEVAL_QUERY in the same vector space |
| app/rag/generation.py | Grounding instructions, exact insufficient-evidence response |
| app/services/rag.py | Request orchestration, source rechecks, atomic question/answer commit |
| app/services/conversations.py | Ownership, history projection, current access checks |
| app/schemas/conversations.py | Typed inputs, safe responses, question limits |
| app/api/routes/conversations.py | REST routes, session/CSRF dependencies, safe AI errors |
| app/core/config.py, .env.example, app/main.py | Retrieval settings and route registration |
| tests/test_rag_units.py | SQL shape, context, citations, query task, input bounds |
| tests/test_rag_integration.py | Real PostgreSQL permission and history boundary tests |

## Query flow

1. Validate the session and CSRF/Origin for the POST.
2. Verify the conversation belongs to the caller; an administrator has no ownership bypass.
3. Check whether any active, ready chunks exist within current database grants.
4. Close the read transaction before calling the embedding service.
5. Generate a normalized 1536-dimensional question vector with gemini-embedding-001 and
   RETRIEVAL_QUERY. Documents were embedded with RETRIEVAL_DOCUMENT.
6. Build authorized_chunks AS MATERIALIZED in PostgreSQL by joining the current user,
   role_category_access, documents and chunks. Require active user/current token_version,
   active document and ready ingestion status.
7. Compute exact cosine distance ONLY against that materialized relation; apply the similarity
   threshold, order and top-k there. There is no unrestricted global top-k followed by Python filtering.
8. Build source-labeled JSON context from full retrieved chunks within a UTF-8 byte budget.
9. Recheck every selected source and current session, then end the read transaction.
10. Call the selected basic/advanced model through the existing parallel peer-key pool.
11. Validate references against the selected source numbers, then recheck access/session again.
12. Atomically save the user message, assistant message and all used context-source mappings.

Database grants determine scope; the API accepts no client-provided role/category/document IDs for
retrieval. This is backend-enforced RBAC, not PostgreSQL row-level security. The application database
credential is trusted and never exposed to the browser. Direct privileged SQL is outside this boundary.

### Retrieval and relevance

Cosine similarity is 1 minus pgvector cosine distance. Defaults are top_k=5, min_similarity=0.60,
and at most 6000 bytes of packed context. These are initial operating choices, not universal
relevance guarantees. Calibrate the threshold with actual company questions/PDFs. Exact search
avoids approximate-index filtering tradeoffs for this V1 dataset size.

Context contains source label, current document title/filename, original page number and chunk text.
The byte budget counts metadata and Unicode bytes too. Whole chunks that do not fit are skipped,
not silently cut. No embedding values, filesystem paths or unauthorized source metadata are returned.

No eligible/relevant context produces exactly:

> I couldn't find enough information in the documents available to you.

The response does not reveal whether any restricted document exists. Empty authorized scope skips
both the embedding and generation calls; below-threshold retrieval skips generation. Prior assistant
messages are not fed back into the LLM. V1 questions must be self-contained, even within a saved chat.

### Citations and grounding

The model uses labels such as [S1] and [S2]. The backend validates label syntax/membership, requires
at least one label for a substantive generated answer, and resolves title/page/IDs itself. Invented
labels or uncited answers return 502 without persisting the failed turn. The exact insufficient-evidence
response needs no citation. URLs point to the existing protected document-download endpoint.

Validation establishes that referenced sources were supplied and authorized. It does not prove every
generated claim logically follows from the text; source inspection and evaluation remain necessary.
Document text is explicitly treated as reference data, not application instructions. No separate
prompt-injection detector, reranker or additional vector database is added.

### History after permission changes

Every source-based answer stores ALL chunks used in context, including chunks the answer did not
explicitly cite. Otherwise an uncited chunk could influence an answer and escape later revocation.
On history reads, PostgreSQL CASE returns a fixed placeholder instead of a stored assistant answer
if any used source is now inaccessible, inactive or not ready. Only citation metadata for currently
visible answers/sources is fetched. A source-less legacy assistant answer is withheld unless it is
the known insufficient-evidence constant. User-entered messages remain visible to their owner.

Withheld answers expose no source names, document IDs or citations. Restoring access makes an
otherwise valid old answer visible again. Permission changes apply to subsequent requests;
requests already sent to Gemini cannot be recalled. Source/session changes detected during a query
discard the result before returning/persisting it.

### Transactions and concurrent questions

Providers run without holding a database transaction or row lock. Before committing a turn, a
conditional UPDATE checks the conversation's starting updated_at. If another request has already
changed it, return 409 and save neither message. Other conversations can run concurrently through
the existing three-key pool. Explicit message timestamps preserve user-before-assistant order.
Conversation title defaults to the first question's first 80 characters; no model-generated title is used.

Provider failures, unknown references and SQL failures do not leave a half turn. Model/token quota
limits return safe errors; no busy advanced query is silently downgraded to the basic model.

## REST API

All paths below start with /api/v1. GETs require a valid session. POSTs additionally require the
trusted Origin and X-CSRF-Token from Phase 2.

| Method | Path | Behavior |
|---|---|---|
| POST | /conversations | Create an owned conversation; optional title; 201 |
| GET | /conversations?offset=0&limit=50 | List only caller's conversations, most recently updated first |
| GET | /conversations/{id} | Owned metadata; missing/other user's ID returns 404 |
| POST | /conversations/{id}/messages | Ask question and atomically save a complete turn; 201 |
| GET | /conversations/{id}/messages?offset=0&limit=50 | Chronological history with current source authorization |

Question body:

```json
{"question":"What do the engineering guidelines say about code review?","model_mode":"auto"}
```

model_mode is auto/basic/advanced; callers cannot choose arbitrary provider model IDs. Questions
are limited to 2000 characters and 2500 UTF-8 bytes, with invalid control characters rejected.
The response includes conversation_id, question/answer message objects, authorized sources,
selected model and routing reason. History returns sources and a withheld flag; model metadata is
returned for the current query but is not added to the database schema in V1.

Error behavior: 401 invalid session, 403 CSRF, 404 ownership, 409 concurrent edit/access change,
422 invalid input, 429 capacity with Retry-After, 502 grounding failure, 503 provider/database unavailable.

## Run and manual checklist

```powershell
cd D:\RAG_Project\backend
uv sync --locked
uv run uvicorn app.main:app --workers 1
```

Existing three credentials remain unchanged. Runtime settings:

```dotenv
RAG_TOP_K=5
RAG_MIN_SIMILARITY=0.60
RAG_CONTEXT_MAX_BYTES=6000
```

Keep the single-worker requirement for the local provider limiter. Source documents must be ready
and active. The Phase 3 synthetic verification PDFs were intentionally left inactive; either upload
your actual PDFs or activate a clearly identified test PDF only during testing.

After the Phase 2 PowerShell login ($api, $secureRagSession and $csrfHeaders):

```powershell
$conversation = Invoke-RestMethod "$api/conversations" -Method Post `
    -WebSession $secureRagSession -Headers $csrfHeaders -ContentType 'application/json' -Body '{}'
$body = @{question='What do the engineering guidelines say about code review?'; model_mode='auto'} | ConvertTo-Json
$turn = Invoke-RestMethod "$api/conversations/$($conversation.id)/messages" -Method Post `
    -WebSession $secureRagSession -Headers $csrfHeaders -ContentType 'application/json' -Body $body
$turn.answer
Invoke-RestMethod "$api/conversations/$($conversation.id)/messages" -WebSession $secureRagSession
```

- Engineer: General/Engineering sources only; HR/Finance question cannot reveal restricted chunks.
- No ready authorized documents: insufficient-evidence response, empty sources, model none.
- Relevant document: answer includes a source label plus actual document/page/chunk IDs.
- Another user, including admin, cannot read/query that conversation; all such calls return 404.
- Remove a source category grant or deactivate a used document: old answer is withheld with no sources.
- Missing CSRF on POST returns 403. Forged role_id/category fields return 422.
- Provider busy: 429/503 and no new partial history. Repeated concurrent questions can return 409;
  reload the conversation before retrying.

## Automated checks

```powershell
uv run pytest --tb=short
uv run ruff check .
$env:SECURERAG_RUN_DB_TESTS='1'
uv run pytest tests/test_rag_integration.py -v --tb=short
Remove-Item Env:SECURERAG_RUN_DB_TESTS
uv run alembic check
```

Integration tests use actual Neon/pgvector in an isolated rolled-back schema. Denied HR/Finance
vectors are deliberately closer than allowed vectors; the test verifies allowed results still win
and inspects the actual SDK request body for absence of restricted canaries. Gemini transport is
mocked there. Other tests cover uncited used-source revocation, inactive sources, owner isolation,
threshold abstention, invalid references, provider/SQL rollback, access changes during processing
and competing complete turns. Real provider smoke results are reported separately.

References:
- https://github.com/pgvector/pgvector
- https://www.postgresql.org/docs/current/queries-with.html
- https://ai.google.dev/gemini-api/docs/embeddings
