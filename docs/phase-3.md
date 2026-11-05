# Phase 3: private PDFs and document ingestion

## Scope and files

Adds admin PDF upload/list/activation, authorized document metadata/download, text extraction,
page-aware chunking, Gemini embeddings and transactional publication of chunks. Frontend upload
screens and question answering remain in their planned phases. No schema change is needed.

- app/services/storage.py: private files with generated storage keys and bounded copying.
- app/rag/extraction.py: pypdf extraction, cleanup and page/stream/text limits.
- app/rag/chunking.py: page-aware, overlapping chunks with UTF-8 byte boundaries.
- app/rag/embeddings.py: Google Gen AI SDK integration, batches, deadlines and vector validation.
- app/services/ingestion.py: processing/ready/failed lifecycle and atomic publication.
- app/services/documents.py: database-filtered visible document queries.
- app/api/routes/documents.py: upload, management, metadata and protected file endpoints.
- app/api/upload_limits.py: request-body cap before multipart spooling.
- app/schemas/documents.py: validated metadata/activation and safe response fields.
- app/core/config.py, app/main.py, pyproject.toml, uv.lock, .env.example: configuration/dependencies.
- tests/conftest.py, helpers.py: shared isolated PostgreSQL/API fixtures from Phase 2.
- tests/pdf_helpers.py, test_document_processing.py, test_documents_integration.py: parser,
  storage, SDK transport and real PostgreSQL API tests.

## Important decisions

### Provider change requested by the user

Gemini replaces the initially proposed OpenAI provider. V1 uses `gemini-embedding-001`, requesting
1536 dimensions, so the existing pgvector schema is unchanged. This text embedding model supports
one output vector per input string in a batch. The SDK sends RETRIEVAL_DOCUMENT during ingestion;
Phase 4 must use the same model/dimension and RETRIEVAL_QUERY for questions. Reduced vectors are
normalized and checked for finite values and nonzero length before storage.

EMBEDDING_MODEL is intentionally restricted to this model in V1. Equal vector length does not make
different models compatible. Changing models later requires an explicit migration/re-ingestion plan.
Gemini Embedding 2 has different batching/task semantics and is not substituted automatically.

### Chunking and citations

The original approximate 500-token/75-token-overlap target is implemented as a conservative
2000-byte UTF-8 budget with 300-byte overlap. This is roughly 500/75 English tokens, not an exact
Gemini token count. Multilingual text can have different token ratios. No OpenAI tokenizer or
additional token-count API request is introduced.

Chunks end near paragraph, line, sentence or word boundaries where possible, always within one PDF
page. Cumulative UTF-8 offsets prevent cutting encoded characters. Overlap keeps useful context
around boundaries. Each saved chunk has its document ID, sequential index and original 1-based PDF
page number, which later supports citations. Blank/image-only pages are skipped without renumbering
later pages. Entirely scanned PDFs are rejected; OCR is outside V1.

### Private storage

PDFs live under PDF_STORAGE_ROOT, default backend/storage/pdfs. The backend never mounts that folder
as public static content. Storage paths use generated UUID keys, not upload filenames. The database
stores only the reference and metadata. Download responses use attachment disposition and nosniff.
An original client filename is kept only as safe metadata/download filename, with path parts removed.
Production requires a private persistent volume; an ephemeral container filesystem will lose PDFs.

### Ingestion transactions

1. Authenticate, validate Origin/CSRF and require documents.manage before parsing multipart data.
2. Enforce total request limits and validate multipart metadata.
3. Require a configured Gemini key and existing category; validate individual file size,
   extension/MIME/header and store the private original file.
4. Recheck current uploader access and commit inactive processing metadata in a short transaction.
5. Extract/clean page text, create chunks and call Gemini in batches of at most 32.
6. Check response count, vector length, finite values and nonzero norm.
7. Recheck uploader activity/session/permission after external work.
8. Insert all chunks and change the document to ready + active in one transaction.

No database transaction or global admin lock is held during PDF parsing or provider HTTP requests.
All chunks are published atomically with readiness. Successful ingestion activates the document;
admins can subsequently deactivate it. Processing/failed documents cannot be activated.

Known parser/provider failures keep committed metadata failed and inactive, without chunks. The
original is retained privately for administrative troubleshooting/re-upload. Validation failures before
metadata creation leave no record/file. A missing key returns 503 before storing anything. Storage
or SQL failures return generic errors; SDK errors never echo provider payloads or keys.

There is no automatic retry endpoint, job queue or crash-recovery worker. A process crash/database
outage can leave a document processing, which remains inaccessible. Re-upload after fixing the cause.
Provider requests have bounded timeouts and no SDK automatic retries. The ingestion budget is checked
between stages and requests; it cannot forcibly interrupt an individual CPU-bound pypdf operation.
The later user-requested peer pool adds bounded attempts on other eligible keys and project/model
rate limiting; see gemini-provider-pool.md for quota, concurrency and single-worker requirements.
Byte/page/text/decompressed-stream limits bound normal workloads, not a full parser sandbox.

### Authorization

Only documents.manage can upload, list administrative metadata or activate/deactivate. This permission
does not grant a download bypass. Ordinary listing, details and file downloads require a current
category grant AND active=true AND ingestion_status=ready in the database query. Unauthorized,
inactive, failed and nonexistent document IDs all return 404. Storage keys never appear in API JSON.
Grant revocation and deactivation affect subsequent requests; in-flight downloads are not cancelled.

The upload recheck takes the short admin transaction lock only when saving metadata/publishing chunks,
so long provider requests do not block role/user administration. If access is revoked during external
work, publication fails and the document stays inactive. Requests already sent to the embedding
provider are not recalled.

## Endpoints

| Method | Path under /api/v1 | Access |
|---|---|---|
| POST | /admin/documents | documents.manage + Origin/CSRF; multipart file, title, category_id |
| GET | /admin/documents?offset=0&limit=50 | documents.manage; all ingestion states |
| PATCH | /admin/documents/{id} | documents.manage + Origin/CSRF; body {"active": false/true} |
| GET | /documents?offset=0&limit=50 | Current user's active, ready, granted documents |
| GET | /documents/{id} | Same document authorization |
| GET | /documents/{id}/file | Same authorization; private PDF attachment |

The admin list exposes management metadata across categories, but never file paths, chunks or vectors.
An upload returns 201 only after successful ingestion. Invalid PDF extraction returns 422 and provider
failure returns 502, with a safe message and document ID when failed metadata exists.
With the peer-pool enhancement, exhausted local/provider capacity returns 429 + Retry-After,
also retaining inactive failed metadata with no chunks.

## Setup and run

```powershell
cd D:\RAG_Project\backend
uv sync --locked
```

Set GEMINI_API_KEY in the ignored backend/.env, then restart the API. Do not paste the key into chat.
No key is invented or copied from a different service. Defaults:

```dotenv
GEMINI_API_KEY=your-private-key
EMBEDDING_MODEL=gemini-embedding-001
EMBEDDING_DIMENSIONS=1536
MAX_UPLOAD_MB=10
MAX_PDF_PAGES=100
MAX_DOCUMENT_CHARACTERS=500000
MAX_DOCUMENT_CHUNKS=300
EMBEDDING_TIMEOUT_SECONDS=30
INGESTION_TIMEOUT_SECONDS=120
```

```powershell
uv run uvicorn app.main:app --reload
```

## Manual checklist (PowerShell 7)

First sign in using the Phase 2 guide, retaining $secureRagSession, $profile and $csrfHeaders.
The developer admin credentials are in the ignored local file described in that guide.

```powershell
$api = 'http://localhost:8000/api/v1'
$categories = Invoke-RestMethod "$api/admin/categories" -WebSession $secureRagSession
$general = $categories | Where-Object name -eq 'General'
$document = Invoke-RestMethod "$api/admin/documents" -Method Post `
    -WebSession $secureRagSession -Headers $csrfHeaders `
    -Form @{title='Employee Handbook'; category_id=$general.id; file=(Get-Item 'C:\path\handbook.pdf')}
Invoke-RestMethod "$api/documents" -WebSession $secureRagSession
Invoke-WebRequest "$api/documents/$($document.id)/file" `
    -WebSession $secureRagSession -OutFile "$env:TEMP\securerag-handbook.pdf"
Invoke-RestMethod "$api/admin/documents/$($document.id)" -Method Patch `
    -WebSession $secureRagSession -Headers $csrfHeaders -ContentType 'application/json' `
    -Body '{"active":false}'
```

- Upload a text-based two-page PDF: 201, ready, active; stored chunks retain pages 1/2.
- Download as an authorized user: original PDF, attachment, no-store.
- Upload HR and General PDFs; Engineer sees/downloads General only. HR ID returns 404.
- Engineer upload attempt returns 403. Missing login returns 401; missing CSRF returns 403.
- Deactivate a document: it disappears from ordinary list and downloads return 404.
- Corrupt/encrypted/scanned PDF: 422, failed inactive metadata, zero chunks; activation returns 409.
- Oversize upload returns 413; unknown category and invalid metadata create no document.
- Provider/key/quota failure never marks a document ready or leaves partial chunks.
- Remove category access; an existing login immediately loses metadata/download access.

## Tests

```powershell
uv run pytest --tb=short
uv run ruff check .
$env:SECURERAG_RUN_DB_TESTS='1'
uv run pytest tests/test_auth_integration.py tests/test_documents_integration.py -v --tb=short
Remove-Item Env:SECURERAG_RUN_DB_TESTS
uv run alembic check
```

Local tests use real PDF bytes and the real Gemini SDK with an HTTP mock transport. PostgreSQL
integration tests use real Neon, isolated rolled-back schemas and temporary private storage, with an
explicit test-only embedding provider. They verify database/API correctness, not actual Gemini access
or semantic quality. Live provider verification must be reported separately after a real key is set.

References:
- https://ai.google.dev/gemini-api/docs/embeddings
- https://ai.google.dev/api/embeddings
- https://googleapis.github.io/python-genai/
- https://pypdf.readthedocs.io/en/stable/user/extract-text.html
- https://fastapi.tiangolo.com/tutorial/request-files/
