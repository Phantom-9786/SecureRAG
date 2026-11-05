# Phase 7 — Release verification and deployment

This phase closes V1 with a security review, the complete database regression suite, real-provider container smoke tests, Docker packaging and interview/runbook documentation. The application is locally deployed at http://localhost:3000 using the verified Docker stack. Public hosting and TLS infrastructure are not provisioned by this phase.

## Changes

- Corrected readiness from the obsolete schema revision 0001 to the current release head 0002. A regression test compares the required version with Alembic's migration head.
- Added explicit non-root FastAPI and standalone Next.js Dockerfiles with allowlisted contexts; secrets, local credentials, caches and PDFs are excluded from images.
- Added compose.yaml and an Nginx gateway with same-origin routing, private app ports, authentication throttling, bounded bodies, safe request logging and security headers.
- Added deployment guidance for runtime secrets, private file persistence, migrations, backups, TLS/origins, single-worker limits and returning to development.
- Added security headers and disabled API docs/OpenAPI in production mode.
- Hardened browser principal changes: revalidation checks identity before loading a selected history; another account clears the prior user's draft, conversations, documents and admin state. Admin writes also check that the current identity still matches the displayed account.
- Added a read-only release smoke-check command and a placement/interview explanation guide.

The established architecture, 12-table schema, Gemini peer pool and rule-based Auto model selection remain unchanged. No Redis, queue, OCR, reranker, ABAC engine or distributed services were added. Nginx is the deployment edge, not a new business service.

## Files to read

| File | Purpose |
|---|---|
| backend/Dockerfile, frontend/Dockerfile | Locked dependencies and non-root runtime images |
| backend/.dockerignore, frontend/.dockerignore | Build-context allowlists |
| compose.yaml | One serving API, frontend, gateway and persistent PDF mount |
| deploy/nginx.conf | Routing, auth rate limits and request size/time limits |
| deploy/production.env.example | Non-secret production settings template |
| backend/app/db/schema.py | Required release migration head |
| backend/tests/test_release.py | Readiness, production docs/headers and build-context regression checks |
| backend/scripts/check_release.py | Read-only deployed smoke test |
| docs/deployment.md | Deployment and recovery runbook |
| docs/security-review.md | Findings, evidence and remaining limits |
| docs/interview-guide.md | Concepts and demonstration script |
| docs/phase-7-validation.md | Actual test results |

## Concepts to learn

A health check is not the same as readiness: a process can be alive while its database is unavailable or on an incompatible schema. Environment files belong at runtime, not in image layers. File backups and database backups must stay consistent. HTTPS determines production cookie configuration and OAuth origins. Authorization stays in FastAPI/SQL even when a gateway or UI adds controls. Dependency scans and tests provide evidence for their scope, not a blanket security guarantee.

## Run and verify

From the project root:

```powershell
docker compose config --quiet
docker compose up -d --build --wait --wait-timeout 120
.\backend\.venv\Scripts\python.exe backend/scripts/check_release.py --output backend/.local/release-check.json
```

From backend:

```powershell
$env:SECURERAG_RUN_DB_TESTS='1'
.\.venv\Scripts\python.exe -m pytest -q --tb=short
.\.venv\Scripts\ruff.exe check .
```

From frontend:

```powershell
npm.cmd test
npm.cmd run typecheck
```

The Docker frontend build also runs Next.js TypeScript checks. The current Docker environment keeps localhost HTTP development auth flags; switch to APP_ENV=production only with the configured HTTPS origin. Follow the deployment runbook before public hosting.

## Manual checklist

1. Google Admin signs in at localhost:3000 and sees Administration.
2. Create an Engineer account and upload clearly synthetic Engineering and HR PDFs.
3. Engineer can see/download Engineering but gets no HR document or citation.
4. An Engineering question returns an allowed document/page citation; an HR canary question does not leak the restricted value.
5. Remove Engineering access and refresh history; the old source-backed answer is withheld.
6. Deactivate the user and confirm the old session is rejected.
7. Switch accounts in another tab, then revalidate the old tab; old account details/history must clear.
8. Deactivate synthetic records after the demonstration.

Actual execution is recorded in phase-7-validation.md. For the current local installation, the user retains their existing Google Admin account, and verification users/documents are left inactive.
