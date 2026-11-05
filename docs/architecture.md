# Architecture and phases

Browser -> Next.js -> FastAPI -> Neon PostgreSQL + pgvector.
FastAPI also accesses private PDF storage and embedding/LLM APIs.
The browser has neither database credentials nor provider secrets.

1. Foundation: configuration, schema, migrations, seed, health, Next.js starter.
2. Authentication/RBAC: Argon2id, cookie JWT, CSRF, current database grants, admin bootstrap.
3. Documents: private file storage, bounded synchronous PDF ingestion, page-aware chunks, embeddings.
4. RAG: materialized authorized chunk scope, exact cosine ranking, grounded answers, citations/history.
5. User UI: login, chat, accessible documents, sources, history.
6. Admin UI: documents, users, roles and grants.
7. Security verification, deployment Dockerfiles, end-to-end checks, interview documentation.

Phase 3 provider decision: per user request, AI integration uses Gemini rather than the initially
proposed OpenAI provider. Text embeddings use gemini-embedding-001 at 1536 dimensions, retaining
the approved database shape. Chunking uses a 2000-byte UTF-8 budget/300-byte overlap as an explicit
approximation of the initial token target. See phase-3.md for details and limits.

Additional user-approved scope: Gemini peer key pooling, project/model local rate limiting, and
explainable basic/advanced answer-model routing. Embeddings use the shared pool; generation and
routing services are integrated with Phase 4. See gemini-provider-pool.md. V1 requires one
API worker for the process-local limiter; no distributed quota enforcement is claimed.

One role per user. Category access and administrative permission grants are separate.
No special role-name bypass. Admin initially receives explicit grants to all five categories.
Future categories require explicit grants.

Phase 1 adds no authentication or data-serving APIs. Empty speculative layers are not created;
schemas/services/RAG modules will be added when their phases have actual behavior.

Dependencies are locked with backend/uv.lock and frontend/package-lock.json.
No queue, separate vector database, caching tier, OCR, reranker, or microservices.

Phase 4 now implements owner-scoped question/history APIs, materialized permission-filtered exact
retrieval, source context and citation checks. Existing tables are reused. See phase-4.md and
phase-4-validation.md. Prior assistant answers are not reused as LLM context; revoked source access
withholds stored answers. Same-conversation write conflicts use updated_at and return 409.

Sources consulted for setup:
- https://fastapi.tiangolo.com/tutorial/bigger-applications/
- https://nextjs.org/docs/app/getting-started/installation
- https://neon.com/docs/connect/connection-pooling

Phase 5 implements the Next.js user portal using a same-origin /api/v1 rewrite to FastAPI.
HttpOnly session cookies remain backend-issued; CSRF/profile state stays in memory.
Browser focus and explicit refresh reload permission-aware history; no push revocation is claimed.
See phase-5.md for the UI structure, request lifecycle and local setup.

Phase 6 implements permission-scoped administration screens using the existing management APIs.
A scoped admin/options lookup supports independent management grants, and users/google provisions
Google accounts without issuing a usable password. No schema migration or new infrastructure was
needed. The backend remains the authorization boundary; see phase-6.md.

Phase 7 packages the same architecture as non-root API + standalone frontend containers behind
an Nginx deployment gateway. Neon remains external and PDFs use a private persistent bind mount.
Readiness tracks schema 0002. The verified local stack now serves localhost:3000; public hosting
and TLS are host-specific follow-up. See deployment.md, security-review.md and phase-7-validation.md.
