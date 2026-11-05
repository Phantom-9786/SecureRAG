# Phase 2 verification — 2026-10-31

## Results

- Local backend suite: 20 passed. Three database integration tests are opt-in in the normal run.
- Live Neon PostgreSQL integration suite: 3 passed (98.61 seconds).
- Ruff checks and Python compilation passed.
- Alembic schema comparison: `No new upgrade operations detected.` No new migration was needed.
- Real running HTTP API: login 200, current profile 200, user listing 200, logout 204,
  subsequent profile request 401. This smoke used the actual development admin and pooled URL.

## Security behaviors verified

- Argon2id hashing with unique salts; wrong password rejection.
- Signed token identity; expired, tampered, wrong-issuer/audience and invalid-claim rejection.
- Production cookie flags and unsafe production configuration rejection.
- Validation errors and database errors do not echo secret input.
- Anonymous requests denied; Engineer denied user/role administration.
- Missing CSRF, a forged cookie/header pair, and untrusted Origin rejected.
- Duplicate email conflicts; no password hashes/token versions exposed in user responses.
- Existing sessions immediately see database role/category grant changes.
- Inactive users cannot authenticate; reactivation does not revive old sessions.
- Logout revokes copied cookies via token_version.
- Last administrator cannot be deactivated/demoted or stripped of management permissions.
- A second administrator can demote the first; the demoted user's old cookie loses admin access.
- Renaming an administrative role does not remove its grant-based access.
- First-user bootstrap refuses to run after a user exists.

The integration tests use an isolated schema and rolled-back transactions. No test users or schemas
were retained. A transient local DNS failure was resolved before the successful live test run.
Concurrent admin requests were not load-tested; their transaction lock and invariant are implemented,
and sequential conflicting operations are covered.

## Development account

The actual development database now has its first administrator:
`admin@securerag.example.com`. The randomly generated password is stored only in the ignored local
file `backend/.local/bootstrap-admin.txt`. No password or signing key appears in committed code/docs.
Keep the file private, store the password safely and remove the plaintext file when no longer needed.
The signing key is configured in the ignored `backend/.env`.

The API is available on port 8000 during this work session. If it has stopped, follow phase-2.md
to run it again. Login UI, documents and RAG remain in their planned later phases.

Installed Starlette still emits the previously documented httpx TestClient deprecation warning;
all tests pass. It does not affect runtime API requests.
