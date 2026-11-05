# Deployment runbook

The release includes Docker images for FastAPI and Next.js, plus an Nginx gateway. Neon PostgreSQL/pgvector stays external. PDFs are mounted privately into the API container; they are not baked into an image or served from a public directory.

## Local Docker deployment

Requirements: Docker Desktop/Engine with Linux containers, the configured backend/.env, and the existing PDF directory. Stop a development server using port 3000 before launching the stack. Do not run a second serving API against the same Gemini keys: V1 has one process-local quota manager.

From D:\RAG_Project:

```powershell
docker compose config --quiet
docker compose build
docker compose up -d --wait --wait-timeout 120
docker compose ps
```

Open http://localhost:3000. API/frontend container ports are internal; only the gateway is published on 127.0.0.1:3000. The local deployment uses APP_ENV=development because localhost is HTTP. Next.js still runs its compiled production server. Existing Google localhost origins remain valid.

The Phase 7 verification moved this workspace from the dev servers to this Docker stack on the same URL. Existing database, JWT secret, Google Client ID and private PDF directory were retained.

To use an alternate local port:

```powershell
$env:APP_PORT='3300'
$env:FRONTEND_ORIGIN='http://localhost:3300'
docker compose up -d --wait
```

Register that exact origin in Google Cloud before using Google sign-in on the alternate port. Port changes alone do not update Google's authorized origins. Clear these shell overrides before returning to port 3000.

## Migrations and first installation

Migrations are explicit release actions, not automatic web startup hooks. Back up before applying changes to an important database. Test on a Neon development/preview branch first and use the direct unpooled migration URL.

```powershell
docker compose run --rm --no-deps api alembic upgrade head
docker compose run --rm --no-deps api python -m app.db.seed
docker compose run --rm --no-deps api alembic check
```

On a genuinely empty new installation only:

```powershell
docker compose run --rm --no-deps api python -m app.db.bootstrap_admin --name "Project Admin" --email admin@example.com
```

The command prompts privately for a password and refuses if a user already exists. Do not run bootstrap against the existing populated development database. Schema head is 0002; readiness now checks that release version correctly.

## Secrets and files

- backend/.env is supplied at runtime via Compose env_file and excluded from Docker build contexts. The frontend receives no database/provider credentials.
- Both build contexts are allowlists. API runtime UID/GID is 10001; frontend uses the non-root node user (UID 1000).
- The default PDF bind mount is backend/storage/pdfs -> /app/storage/pdfs. Recreating a container preserves these host files.
- On a Linux host, provision a persistent directory owned/writable by UID/GID 10001 and restrict access, for example owner-only permissions. Set PDF_STORAGE_PATH to its absolute path.
- A new host using an existing database must restore the matching PDFs too. A database backup alone does not contain originals.
- Keep .env and .local out of source control, archives and support logs. Do not print a full `docker compose config`, container environment or raw SQL-driver errors; `config --quiet` validates without dumping secrets.

## Live deployment on Render

The V1 demo runs on a single Render Free Docker service in Singapore using
`deploy/render.Dockerfile`. Open [SecureRAG](https://securerag-syl4.onrender.com).
The separate production Neon project holds the database, vectors and private PDFs.
Render supplies the HTTPS origin, which is registered with Google OAuth.

The live release passed the health and authorization smoke checks. An end-to-end
test signed in as synthetic Admin and Engineer users, indexed two PDFs, verified
the authorized PDF download and page citation, and checked that a role change
revoked PDF and chat history access. The synthetic records and objects were removed.

Run the release check against the live origin after a deployment.

```powershell
.\backend\.venv\Scripts\python.exe backend/scripts/check_release.py --base-url https://securerag-syl4.onrender.com
```

## Deploying to another host

The Compose package can also run on a host with persistent disk storage:

1. Configure a separate production Neon branch/database as appropriate and restore matching private files.
2. Inject production database URLs, JWT secret, Gemini project/key settings and Google OAuth Client ID through the host's secret store or restricted environment file.
3. Set APP_ENV=production and FRONTEND_ORIGIN to the exact HTTPS origin. Use deploy/production.env.example as a non-secret template.
4. Put the gateway behind a trusted TLS terminator/reverse proxy. Keep API/frontend ports private. The supplied gateway is HTTP and loopback-bound; it is not a certificate server.
5. Register the HTTPS JavaScript origin in Google Cloud, configure the OAuth audience/publishing requirements and provision the intended workspace accounts.
6. Preserve the browser Origin and public Host through the edge. Allow at least 180 seconds for embedding/generation and at least the configured upload size. Terminate TLS before browser access; production cookies are Secure and use __Host- names.
7. If another proxy sits before Nginx, configure real client IP handling only for its trusted CIDRs. Otherwise the IP-based login limiter sees the proxy as one client. Never trust arbitrary forwarded IP headers.
8. Keep exactly one API instance/worker while using the local Gemini limiter and filesystem storage. Horizontal scaling requires shared coordination/storage and is outside V1.
9. Pin image digests for a published release, retain the prior images, and rebuild/audit dependencies regularly. Current Dockerfiles pin runtime major versions and uv; OS image tags can receive updates.

Nginx applies a shared per-IP authentication budget (10 requests/minute, burst 10), a 32 KB login body limit, a 64 KB default API body limit and a 26 MB upload ceiling. FastAPI still enforces its own tighter configured PDF limit and authorization. The limiter is an edge control, not a distributed account-lockout system. Frontend security headers allow the Google popup flow and deny framing; production API docs/schema are disabled.

## Verification and operations

```powershell
.\backend\.venv\Scripts\python.exe backend/scripts/check_release.py --base-url http://localhost:3000 --output backend/.local/release-check.json
docker compose exec -T gateway nginx -t
docker compose logs --tail 50 api frontend gateway
```

Liveness verifies the process; readiness verifies Neon connectivity and schema revision. A cold/unreachable database can return 503 while liveness stays healthy. Logs omit prompts, credentials and raw driver parameters. Existing intermittent DNS/Neon connection failures remain an observed environment limitation; the UI presents a retryable error. Do not automatically replay a failed mutation: confirm saved state first.

```powershell
docker compose stop
docker compose up -d --wait
```

Stop/start preserves the PDF bind mount and external database. Container image rollback does not undo database schema changes; assess schema compatibility and restore database plus files together if recovery requires it. Never use blanket recursive deletion or volume removal as a troubleshooting step.

## Return to development mode

Stop the container stack before starting another API with the same keys:

```powershell
docker compose stop
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

In a second terminal, start `npm.cmd run dev -- --hostname localhost` from frontend. The frontend default API_BASE_URL remains http://127.0.0.1:8000. The standalone Docker frontend is built with its internal api:8000 destination.

References: [Next.js self hosting](https://nextjs.org/docs/app/guides/self-hosting), [uv Docker integration](https://docs.astral.sh/uv/guides/integration/docker/), [Docker Desktop start](https://docs.docker.com/reference/cli/docker/desktop/start/).
