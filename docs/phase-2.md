# Phase 2: authentication and RBAC

## What this phase adds

Backend-only email/password login, cookie JWT sessions, CSRF checks, current-user profile,
logout/revocation, user creation and activation/role changes, role grant replacement,
authorized category listing, and a one-time command-line administrator bootstrap.
Frontend login/admin screens remain in Phases 5 and 6. No schema migration is needed.

## Concepts and design

**Authentication** answers who the caller is. The API verifies an HS256 JWT signature, expiry,
issuer, audience and required claims, then loads the current user. JWTs contain user ID,
token_version and a random CSRF value, but no roles/permissions. A signed token is readable,
not encrypted, so it contains no password or private document text.

**Authorization** reads current role grants from PostgreSQL. Every user may see their own
categories; `users.manage` allows user administration and `roles.manage` allows role/grant
administration. Category access does not imply administrative access. An old token cannot
retain a removed permission. Role display names never grant access.

**Passwords** use salted Argon2id hashes, with library-default memory-hard parameters. Identical
passwords produce different hashes. New passwords must contain 12-128 characters. Login failures
use one generic response for missing accounts, wrong passwords and inactive accounts; missing
accounts still perform password verification. Successful logins upgrade outdated hash parameters.

**Sessions** use a 30-minute access token, configurable from 1 to 120 minutes. No refresh token or
automatic renewal is added in V1; expiry requires login again. JWT is in an HttpOnly, host-only,
SameSite=Lax cookie. Production uses Secure cookies with __Host- prefixes and requires HTTPS.
Logout increments the user's token_version, revoking ALL their sessions. Deactivation also bumps
the version; reactivation cannot revive old cookies. Role edits preserve login while changing access.

**CSRF** is needed because browsers attach cookies automatically. Login requires an exact trusted
Origin. Every authenticated mutation requires that Origin plus X-CSRF-Token matching both the
CSRF cookie and the value inside the signed JWT. A forged cookie/header pair alone is insufficient.
Login and /auth/me return csrf_token so a future frontend can keep it in memory. It is not the JWT.
Use browser fetch with credentials: include. In production frontend/API should be same-site, or
use a same-origin proxy; unrelated hosting domains will not work with SameSite=Lax cookies.

**Transactions/concurrency:** admin writes acquire one PostgreSQL transaction advisory lock and
recheck the caller after acquiring it. The invariant requires at least one active user whose role
has all three management permissions. User demotion/deactivation or grant removal that breaks it
returns 409 and rolls back. The lock serializes these small V1 admin writes so simultaneous edits
cannot both remove the last admin. Direct SQL outside the application is outside this guarantee.

Inputs forbid unknown privilege fields. API outputs never include password hashes or token_version.
Validation errors omit raw input to prevent password echo; authenticated API responses are no-store.
CSRF checks do not replace RBAC. CORS does not replace either control.

## Files

- app/core/config.py, security.py: secrets, cookie settings, Argon2id and JWT.
- app/api/dependencies.py: authentication, CSRF and permission dependencies.
- app/api/routes/auth.py, users.py, roles.py: HTTP endpoints.
- app/schemas/identity.py: validated requests and safe response models.
- app/services/authorization.py: grant lookups, profile and last-admin invariant.
- app/db/bootstrap_admin.py: first-user CLI, guarded by the same transaction lock.
- app/db/seed.py: extracted seed_initial(session) for reusable transactional seeding.
- tests/test_security.py, test_auth_integration.py: token/input and real PostgreSQL API tests.
- pyproject.toml, uv.lock, .env.example, README.md, docs: dependencies and setup.

## Endpoints

| Method | Path under /api/v1 | Requirement |
|---|---|---|
| POST | /auth/login | Trusted Origin, valid credentials |
| GET | /auth/me | Current valid session |
| POST | /auth/logout | Session + CSRF |
| GET | /categories | Session; returns only granted categories |
| GET | /users?offset=0&limit=50 | users.manage |
| POST | /users | users.manage + CSRF |
| PATCH | /users/{id} | users.manage + CSRF |
| GET | /roles | roles.manage |
| GET | /permissions | roles.manage |
| GET | /admin/categories | roles.manage |
| PUT | /roles/{id}/grants | roles.manage + CSRF |

Role grant PUT accepts both category_ids and permission_ids as complete replacement lists.
Unknown IDs fail before any grants are removed. User PATCH accepts role_id and/or is_active.
There is no public registration, hardcoded administrator password, or bootstrap HTTP endpoint.

## Run/setup

```powershell
cd D:\RAG_Project\backend
uv sync --locked
uv run uvicorn app.main:app --reload
```

JWT_SECRET is now configured in the ignored local .env. For a new installation, generate a random
secret of at least 32 bytes and set JWT_SECRET before login; production refuses to start without it.
Do not use a predictable phrase. JWT_ACCESS_TOKEN_MINUTES defaults to 30.

If the database has no users, create the first admin interactively (password is not a CLI argument):

```powershell
uv run python -m app.db.bootstrap_admin --name "Project Admin" --email admin@securerag.example.com
```

Bootstrap refuses to create another user after any user exists. Later users are created through
the protected API. It never resets an existing account's password or overwrites a user.

In this workspace the development admin has already been bootstrapped as
`admin@securerag.example.com`. Its generated password is in the ignored local
`backend/.local/bootstrap-admin.txt`; do not paste it into chat or commit it. You do not need to run
bootstrap again. See phase-2-validation.md for verification results.

## Manual API test

PowerShell; enter the administrator email/password when prompted. Password input is hidden.
Run against the new Phase 2 server; restart an older server process first.

```powershell
$api = 'http://localhost:8000/api/v1'
$adminEmail = Read-Host 'Administrator email'
$adminCredential = Get-Credential -UserName $adminEmail -Message 'SecureRAG admin login'
$loginBody = @{
    email = $adminCredential.UserName
    password = $adminCredential.GetNetworkCredential().Password
} | ConvertTo-Json
$profile = Invoke-RestMethod "$api/auth/login" -Method Post `
    -Headers @{Origin='http://localhost:3000'} -ContentType 'application/json' `
    -Body $loginBody -SessionVariable secureRagSession
Remove-Variable loginBody, adminCredential
$csrfHeaders = @{Origin='http://localhost:3000'; 'X-CSRF-Token'=$profile.csrf_token}
Invoke-RestMethod "$api/auth/me" -WebSession $secureRagSession
$roles = Invoke-RestMethod "$api/roles" -WebSession $secureRagSession
Invoke-RestMethod "$api/categories" -WebSession $secureRagSession
```

Create a user by POSTing name, email, password and role_id to /users with the same WebSession and
csrfHeaders. Supply passwords interactively, not as committed script constants. A role ID comes
from the /roles response. Never copy JWT cookies into chat.

Checklist:
- Correct login returns the user, role, permissions, categories and csrf_token, but no JWT in JSON.
- Wrong password/nonexistent account both return 401 with the same message.
- No session returns 401; an Engineer calling /users or /roles returns 403.
- Mutations without CSRF, with a forged CSRF pair or with a different Origin return 403.
- Engineer starts with General + Engineering; change role to HR and next request shows General + HR.
- Remove a category grant; it disappears from the user's next categories/profile response.
- Deactivate a user: their existing session stops working; reactivation requires a fresh login.
- Deactivating/demoting the only admin or removing their management grants returns 409.
- Logout returns 204, clears cookies, and revokes old copies of that user's tokens.

## Automated checks

```powershell
uv run pytest
uv run ruff check .
# Explicit opt-in; use only the configured development database.
$env:SECURERAG_RUN_DB_TESTS='1'
uv run pytest tests/test_auth_integration.py -v --tb=short
Remove-Item Env:SECURERAG_RUN_DB_TESTS
uv run alembic check
```

Integration tests create a uniquely named schema within a transaction, assert that table resolution
points to that schema, and roll back the transaction afterward. Requests use savepoints so endpoint
commits are tested without persisting test accounts or altering public grants. The direct URL is
used for this schema-oriented test connection. No production branch is involved.

References:
- https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/
- https://pyjwt.readthedocs.io/en/stable/usage.html
- https://argon2-cffi.readthedocs.io/en/stable/howto.html
- https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html
