# Phase 1 validation

Verified locally:
- Backend foundation tests: liveness, readiness error redaction, PostgreSQL DDL compilation,
  settings secret redaction, initial migration snapshot consistency.
- Ruff static checks and Python compilation.
- Alembic offline upgrade SQL generated successfully, including vector extension and all tables.
- Next.js production build and TypeScript checks.
- Running API liveness returned 200, frontend returned 200 with API online.
- Running database readiness returned 503 with a generic error, as expected without credentials.

## Live Neon verification — 2026-10-31

- Project: SecureRAG (`ancient-mountain-11528016`), AWS Singapore.
- Development branch: `development` (`br-snowy-darkness-aokn3414`).
- Database: `neondb`. Credentials saved only in ignored `backend/.env`.
- Applied migration: `0001 (head)`; vector extension installed.
- `alembic check`: No new upgrade operations detected.
- Seed ran twice: stable counts of 6 roles, 5 categories, 3 permissions,
  14 category access grants, and 3 administrative grants.
- Readiness endpoint verified against live PostgreSQL: 200, `status: ready`.
- Backend regression suite: 6 passed; Ruff checks passed.
- Fixed environment parsing of string `EMBEDDING_DIMENSIONS=1536`; added regression coverage.

Migration rollback has not been run. The default parent branch and pre-existing eventpoint project
were left unchanged. Phase 2 authentication remains outside this work.

Dependency note: installed Starlette emits an httpx TestClient deprecation warning. Tests pass;
this concerns the test client's future transport migration, not the runtime health endpoints.
