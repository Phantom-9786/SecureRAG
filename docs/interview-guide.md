# SecureRAG interview guide

## 30-second explanation

SecureRAG lets employees ask questions about company PDFs. FastAPI authenticates each request and loads current database grants. SQL first materializes the authorized document chunks, then performs pgvector cosine ranking inside that scope. Only those chunks go to Gemini. Answers return backend-resolved document/page citations, and history is checked against current source access.

## How to explain the important decisions

| Topic | Explanation |
|---|---|
| Authentication vs authorization | Login proves who you are. Current role/category grants determine which resources you may access. Hiding a button is not authorization. |
| JWT | The signed HttpOnly cookie carries user identity, token version and CSRF binding, not roles. Permissions are read from the database so policy changes take effect on later requests. |
| Passwords | Argon2id stores salted, memory-hard hashes. Passwords are never returned or logged. |
| CSRF | Cookie-authenticated writes require the exact trusted Origin plus a token matching both the CSRF cookie and signed JWT claim. Google uses an additional one-time browser-bound nonce. |
| Google login | google-auth verifies the ID token. Only provisioned active accounts can bind. The unique Google subject identifies returning users; Google does not assign workspace roles. |
| Schema | Users have one role. Role-category and role-permission join tables keep content access separate from management capabilities. Documents own chunks; conversations own messages; message_sources records every context chunk used for an answer. |
| PDF storage | PostgreSQL stores metadata and vectors; original files stay in private filesystem storage. Generated storage keys prevent user-controlled paths. |
| Chunking | Pages are cleaned and split into bounded Unicode-safe UTF-8 byte windows, with overlap. The 2,000/300 byte budgets are an approximation, not an exact Gemini tokenizer count. Original page numbers remain intact. |
| Embeddings | Text becomes a numerical semantic representation. Documents and questions use the same Gemini embedding model/dimension with the appropriate retrieval task type. Vectors are validated and normalized. |
| pgvector | Stores 1,536-dimensional vectors inside PostgreSQL. V1 uses exact cosine search; no separate vector database or approximate index is required at this scale. |
| Permission filtering | A MATERIALIZED SQL scope joins active user, role grants, ready active documents and chunks before distance ranking/top-k. A restricted near-perfect vector cannot crowd out permitted results. |
| RAG | Retrieve authorized evidence and ask the model to answer from it. No evidence produces a deterministic abstention, avoiding an unnecessary generation call. |
| Citations | The model references S1/S2 labels. The server validates labels and resolves metadata itself; a label check does not prove factual entailment of every sentence. |
| History revocation | Store all context sources, including uncited ones. If any become inaccessible, SQL withholds the old assistant answer and omits its citations. User-entered questions remain owner-visible. |
| Transactions | Do not hold a database transaction during provider calls. Recheck actor/source access before saving. Persist the question, answer and source mappings atomically. |
| Concurrent questions | A conditional updated_at write allows one complete turn to win; a competing turn gets 409 rather than interleaved partial history. |
| Three Gemini keys | All keys are peers and can serve independent simultaneous requests. Quotas are budgeted by project/model, not treated as three sequential emergency tiers. One API worker owns the local limiter. |
| Model routing | Auto uses transparent rules: direct questions use basic; comparison/analysis/multi-question or larger retrieved context uses advanced. Manual override is optional. This is not a trained classifier. |
| Deployment | Non-root FastAPI and standalone Next.js containers, private PDF mount and a same-origin Nginx gateway. Neon remains managed/external. TLS, exact origins and secret injection are deployment configuration. |

## Important honest limits

- V1 uses category-level RBAC, not ABAC or per-chunk policies.
- Queries are self-contained; previous assistant answers are not fed back as model context.
- No OCR, reranker, distributed quota coordinator, queue or crash-recovery worker.
- Prompt instructions and citation validation reduce unsupported answers, but are not a prompt-injection detection system or semantic fact checker.
- Access is checked at request boundaries. Already sent provider requests or downloaded files cannot be recalled.
- Private filesystem storage and process-local rate counters constrain the app to one serving API instance. Restarting resets local quota counters.
- Gemini subscription branding does not establish API quotas. Actual model availability is checked separately; advanced capacity is not guaranteed.
- Package audits report known advisories for the scanned versions; they are not a penetration test or a scan of every OS image component.

## Demonstration flow

1. Sign in as Admin and show the three management sections.
2. Create an Engineer account with an explicit role; upload a synthetic Engineering PDF and an HR PDF.
3. Sign in as Engineer. Show that only allowed active documents appear and the HR file returns 404.
4. Ask a question answered by Engineering content; open its page citation.
5. Ask about the HR content. Show no restricted source/content returned, alongside the automated canary-context tests.
6. Revoke Engineering access and reload history. Show that the previous assistant answer is withheld.
7. Deactivate the user and show the old session is rejected.

Use clearly synthetic documents for demonstrations and leave test accounts/documents inactive afterward. Read phase-7-validation.md for the actual executed evidence.
