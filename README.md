# SecureRAG

Permission-aware enterprise PDF assistant. Next.js + FastAPI + Neon PostgreSQL + pgvector.

## Current scope: V1 complete — Phase 7 verified locally

The seven phases are implemented. The application is running locally through Docker at
[http://localhost:3000](http://localhost:3000). Sign in with your provisioned Google account.
Public hosting/TLS setup remains a deployment action on a chosen host.

```powershell
docker compose up -d --build --wait --wait-timeout 120
.\backend\.venv\Scripts\python.exe backend/scripts/check_release.py
```

See [deployment/runbook](docs/deployment.md), [final validation](docs/phase-7-validation.md),
[security review](docs/security-review.md), [Phase 7 guide](docs/phase-7.md), and
[interview guide](docs/interview-guide.md). Do not run the Docker and development APIs against
the same Gemini keys simultaneously. The local Docker stack preserves the private PDF bind mount.

Implemented: application skeleton, typed configuration, PostgreSQL schema, immutable initial
migration, role/category seed, health endpoints, basic frontend, and backend authentication/RBAC.
Phase 2 adds Argon2id, cookie JWT + CSRF, user/role administration, first-admin bootstrap and
security integration tests. See [Phase 2 guide](docs/phase-2.md) for authentication setup.
Phase 3 adds private PDF storage, admin document APIs, page-aware extraction/chunking and real
Gemini embedding integration. See [Phase 3 guide](docs/phase-3.md) for configuration, endpoints,
learning notes and manual tests. Actual Gemini calls require your GEMINI_API_KEY in backend/.env.
Phase 4 now adds the backend question/conversation flow: permission-filtered exact pgvector
retrieval, source context, citation validation and permission-aware history.
See [Phase 4 guide](docs/phase-4.md) for the implementation, API contract and tests.
Real question -> Gemini -> authorized pgvector sources -> citation-backed answer/history has been
verified; [Phase 4 results](docs/phase-4-validation.md) include the security and live checks.
Phase 5 adds the user portal: login, chat, model selection, sources, document library and history.
See [Phase 5 guide](docs/phase-5.md) and [verification results](docs/phase-5-validation.md).
Phase 6 adds the Administration portal for documents, users and role/category grants.
See [Phase 6 guide](docs/phase-6.md) and [validation](docs/phase-6-validation.md).
Google sign-in is implemented as a Phase 5 extension; [setup and validation](docs/google-signin.md)
explain the OAuth Client ID and provisioned-account requirements. Live provider login awaits configuration.
User-requested enhancement: [Gemini parallel keys and model routing](docs/gemini-provider-pool.md).
Three peer credential slots support project/model rate budgets. V1 runs one API worker; generation
routing is wired into the protected Phase 4 flow. API quotas are not inferred from subscriptions.
Real PDF -> Gemini -> pgvector verification has now passed. See
[live verification results](docs/gemini-live-validation.md) for model availability and follow-up.

## Prerequisites

- Node.js 22+ and npm
- Python 3.12 and uv (https://docs.astral.sh/uv/)
- Neon development branch with pooled and direct connection strings

Commands below are PowerShell, starting in `D:\RAG_Project`.
If uv is not on PATH after installation, restart your terminal or use
`& "$env:USERPROFILE\.local\bin\uv.exe"` instead of `uv`.

## Backend setup

```powershell
cd D:\RAG_Project\backend
uv sync --locked
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Edit `.env` locally: replace both database URL placeholders with URLs for your Neon development
branch. Keep `sslmode=require`. The migration URL must not contain `-pooler` in its hostname.
Do not paste credentials into chat or commit `.env`.
Before running migrations on a new installation, also set a random JWT_SECRET (at least 32 bytes)
in `.env`; the template intentionally leaves it empty. Generate one with
`uv run python -c "import secrets; print(secrets.token_urlsafe(48))"`. This workspace is already configured.

```powershell
uv run alembic upgrade head
uv run python -m app.db.seed
uv run alembic current
uv run alembic check
uv run uvicorn app.main:app --reload
```

The initial migration installs the `vector` extension and creates 11 tables. Migration 0002 adds
Google identity binding and a one-time challenge table (12 tables at head). The database user needs
permission to install that extension. Migrations are explicit commands, never run automatically
when the API starts. The seed creates six roles, five categories, three administrative permissions,
and the initial grants. It does not create a user or password; use the Phase 2 bootstrap command
to create the first administrator on a new installation.
Repeated seeds preserve grant edits on existing roles.

Without database configuration the API still starts. Liveness returns 200; readiness returns 503.

Authentication also requires a random JWT_SECRET in `.env`; it has been configured in this workspace.
For a new installation, generate it with `uv run python -c "import secrets; print(secrets.token_urlsafe(48))"`
and set it in `.env`. Do not leave JWT_SECRET empty. Bootstrap before starting normal use:

```powershell
uv run python -m app.db.bootstrap_admin --name "Project Admin" --email admin@securerag.example.com
```

This interactive command refuses to run after any user exists. Follow [Phase 2](docs/phase-2.md)
for authentication details; the Phase 5 frontend now provides the login form.

## Frontend setup (second terminal)

```powershell
cd D:\RAG_Project\frontend
npm.cmd ci
if (-not (Test-Path .env.local)) { Copy-Item .env.example .env.local }
npm.cmd run dev
```

Open http://localhost:3000 and sign in with your provisioned account. Use localhost consistently:
FRONTEND_ORIGIN in backend/.env must exactly match the browser origin. Next.js proxies /api/v1
to FastAPI; API_BASE_URL is server-only. Restart Next.js after changing it.
Chat, history, citations and the accessible-document library use the real protected APIs.

## Checks

```powershell
cd D:\RAG_Project\backend
uv run pytest
uv run ruff check .
```

```powershell
cd D:\RAG_Project\frontend
npm.cmd run build
npm.cmd run typecheck
npm.cmd test
```

## Manual checklist

- GET http://localhost:8000/api/v1/health returns `status: ok`.
- GET http://localhost:8000/api/v1/health/ready returns 503 before configuration/migration.
- After migration, readiness returns 200 and `alembic current` reports `0002`.
- Run the seed twice: role/category counts and grants remain unchanged.
- In Neon SQL editor: `SELECT name FROM roles ORDER BY name;` returns six roles.
- `SELECT name FROM categories ORDER BY name;` returns five categories.
- `SELECT extname FROM pg_extension WHERE extname = 'vector';` returns `vector`.
- `alembic check` reports no new upgrade operations.
- Start frontend and backend: home page shows API online. Stop backend and refresh: unavailable.
- Check `/docs` in development for health and Phase 2 API schemas. Use the Phase 2 PowerShell
  checklist for authenticated calls because login requires the configured frontend Origin.

## Learning notes

- **Client/server:** Next.js renders the interface; FastAPI owns application behavior and database access.
- **Primary/foreign keys:** IDs identify rows; foreign keys reject invalid references between tables.
- **Join tables:** role/category and role/permission tables represent many-to-many relationships.
- **Constraints:** enforce normalized email, valid statuses, positive pages, and unique chunk positions.
- **Transactions:** a failed seed rolls back as a unit rather than leaving partial permissions.
- **Migrations:** version schema changes; the SQL snapshot does not import evolving models.
- **pgvector:** `vector(1536)` fixes embedding size; changing model dimensions needs a migration.
- **Liveness/readiness:** a running process is different from an API ready to serve database work.

See [architecture](docs/architecture.md), [database](docs/database.md), and
[security](docs/security.md) for boundaries and later phases.
