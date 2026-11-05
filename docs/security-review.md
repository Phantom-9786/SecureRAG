# V1 security review

Review date: 2026-11-01. Scope: source/configuration review, dependency advisories, application tests, real Neon integration, live Gemini checks and local Docker deployment. This is not an external penetration test, formal compliance assessment or scan of every OS package in the images.

## Findings corrected

| Finding | Correction and evidence |
|---|---|
| Readiness expected obsolete revision 0001 | Required head is now 0002; migration-head regression test, container readiness 200 and Alembic drift check passed |
| Revalidation could retain old account UI when a selected conversation belongs to a previous account | Fetch identity first; clear account-bound state on principal change; check identity before admin writes; two-tab browser check verifies clearing on revalidation |
| Deployment lacked isolation/persistence packaging | Non-root app containers, no published backend/frontend ports, allowlisted build contexts and a private PDF bind mount |
| Authentication had no supplied edge throttling | Nginx shared per-IP auth zone; excess login requests observed as 429; normal application still verifies credentials/Origin/CSRF |
| Incomplete response hardening for release | nosniff, framing/referrer controls, Google-compatible popup policy, production API docs/schema disabled |

## Security boundaries verified

- Identity tokens contain no role grants. Active account, token version and current database grants are reloaded server-side.
- Argon2id password hashes, secure production cookie flags, Origin and JWT-bound CSRF, Google token signature/audience/issuer/time checks and one-time nonce binding are tested.
- Separate management grants protect users, roles and documents. Management alone is not permission to read a document.
- Retrieval SQL materializes authorized ready/active chunks before exact cosine ranking and top-k. Tests use restricted high-similarity canaries and inspect the actual generation SDK payload.
- Ownership protects conversations. SQL masks old assistant answers if any context source is no longer authorized; uncited context chunks are tracked too.
- Original PDFs use generated bounded private paths; extension/header/size/parser limits are enforced. Upload failure never publishes partial chunks.
- Provider calls run outside database transactions; actor/source rechecks precede persistence. A turn is atomic and concurrent writes cannot produce partial mixed history.
- Browser state contains no persisted JWT/provider keys. Account switches clear old UI on the next revalidation, and CSRF binding prevents a stale account's form from authenticating as another cookie session.
- Build images contain no .env or .local credential directory. Runtime UIDs were verified as 10001 (API) and 1000 (frontend). Source comparison against configured secret values found no matches in 102 scanned source/test/documentation files at scan time.

## Dependency audit

The frontend production dependency audit reported zero known advisories. pip-audit checked 52 locked production Python packages and reported zero known advisories. Results describe the audit time and scanned package databases; future advisories or unscanned base-image OS components are not covered.

## Remaining limits and operating requirements

- Public deployment requires a chosen host, HTTPS/TLS edge, exact Google origins, production cookie settings, restricted secret injection and storage backup/restore procedures. Only the local Docker deployment is claimed here.
- V1 requires one serving API instance/worker. Quota state is process-local and resets on restart; filesystem storage is not a distributed object store. Do not serve a second API against the same keys in parallel.
- Nginx rate limits the address it sees. Configure forwarded client IP handling only for a trusted upstream proxy. It is not a distributed account-lockout or WAF system.
- Already delivered source data or provider requests cannot be recalled. Permission changes are checked at request boundaries, not pushed to every open page instantly.
- A valid citation label does not establish semantic factual correctness. Prompt injection detection, reranking, OCR, ABAC and multi-turn agent memory are outside V1.
- A strict nonce-based CSP, account recovery/unlinking, durable ingestion jobs, user-level request budgets and audit trails may be later work; no such features are implied by this review.
- Intermittent Neon/DNS connectivity failures were observed on this environment, including during cold connection checks. They return sanitized 503 responses; their external root cause has not been established or claimed fixed. Never blindly replay a mutation after an uncertain network result.

See phase-7-validation.md for exact checks and cleanup status, and deployment.md for operating commands.
