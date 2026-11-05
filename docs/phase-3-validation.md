# Phase 3 verification — 2026-10-31

## Verified

- Final combined suite with real Neon enabled: **43 passed** in 255.35 seconds
  (36 local tests + 7 PostgreSQL integration tests). The existing Starlette/httpx deprecation
  warning remains; it did not fail any check.
- PDF/storage/chunking/Gemini SDK transport tests, including safe Unicode boundaries, page
  preservation, unsupported PDFs, resource limits, private-path handling, storage collision safety,
  normalized vectors and sanitized provider failures.
- Real Neon API/storage integration: upload lifecycle, page/chunk linkage, 1536-dimensional
  persistence, Engineer-versus-HR access, protected attachments, activation and grant revocation.
- Failed parsing/provider responses and injected SQL failures leave no published/partial chunks.
- Uploader permission revoked during embedding generation prevents final publication.
- Upload limits enforce both declared request length and actual streamed bytes, plus file size.
- Phase 2 authentication integration regression after extracting shared fixtures.
- Ruff checks, Python compilation and Alembic schema comparison pass; no new migration needed.
- Running HTTP API: admin login/listing 200. Missing GEMINI_API_KEY returns 503 before storing
  a PDF/document; document list remains unchanged. No fake provider fallback exists in the app.
- Before live credential setup, public development state: one admin, zero documents/chunks, 14 category grants, zero leftover
  test schemas. Test files use temporary storage; PostgreSQL schemas are rolled back.

Database integration uses an explicit test-only embedding double. SDK request tests use the actual
Google SDK with a mocked HTTP transport. These checks do not prove live Gemini API/model access.

## Live provider verification completed

Three supplied credentials are now configured privately. Real PDF -> Gemini -> pgvector verification
passed: a two-page upload produced two normalized 1536-dimensional vectors with pages 1/2, authorized
original download matched the upload, and deactivation hid the sample. All synthetic verification
documents were left inactive. See gemini-live-validation.md for selected models, exact check results,
provider capacity limitations and credential-rotation follow-up.

Frontend upload UI and RAG question answering remain outside Phase 3. Parser hard interruption,
OCR, job queues and crash-recovery workers are not implemented, as documented in phase-3.md.
