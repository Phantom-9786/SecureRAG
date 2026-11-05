# Phase 7 validation — 2026-11-01

## Results

| Check | Actual outcome |
|---|---|
| Complete backend suite with real Neon enabled | **114 passed, 0 skipped**, 418.41 seconds |
| Frontend API boundary tests | **9 passed** |
| Ruff | Passed |
| Next.js type/build checks | Passed, including Linux Docker builds |
| Docker Compose configuration | Validated with config --quiet |
| Container build/start | API + standalone frontend built; gateway started; app health checks passed |
| Runtime identities | API UID 10001, frontend UID 1000 |
| Image secret exclusions | No /app/.env or /app/.local in API image; allowlisted contexts |
| Alembic drift | No new upgrade operations detected |
| Deployed read-only smoke | All 7 routes/status/header checks passed at localhost:3000 |
| Edge authentication throttle | 14 invalid login submissions: 11 validation rejections, 3 rate-limit 429s; bucket reset before handoff |
| Dependency advisories | Frontend production audit: 0; 52 Python production packages: 0 known advisories |
| Configured-secret comparison | No matches in 102 scanned source/test/documentation files at scan time |

The existing Starlette/httpx TestClient deprecation warning is nonfatal. All opt-in database cases ran in this final suite, including admin, password/Google auth, PDF ingestion boundaries and RAG. Database tests use transaction-isolated schemas and synthetic/mock provider responses; they are not presented as live provider evidence.

## Real Docker -> Neon -> Gemini flow

The initial container verification ran on localhost:3300 to avoid interrupting the development servers. After it passed, the dev servers were stopped and the verified stack moved to localhost:3000, preserving the configured Google localhost origin. Only the Nginx gateway is published; the API/frontend ports remain internal.

1. Administrator authenticated through the gateway and provisioned a labelled synthetic Engineer.
2. Real PDF uploads created synthetic Engineering and HR documents. Actual Gemini embeddings were persisted; files were written through the private host bind mount.
3. Engineer's library included Engineering and excluded HR. Engineering download returned a PDF; HR download returned 404. Administration returned 403.
4. Auto-selected real **gemini-3.5-flash-lite** generated an Engineering answer with an allowed **page 1** citation; HTTP 201.
5. An HR question did not return the restricted marker **HR-ONLY-MANGO-742**, and no HR citation appeared.
6. Changing the user to Employee removed Engineering access. History withheld the prior answer, and the previous Engineering file returned 404.
7. Both synthetic PDFs and the synthetic user were deactivated in the script's cleanup. Existing real users/grants were preserved.

The deterministic database/SDK tests additionally inspect the actual outgoing generation payload for unauthorized canaries. The live answer check alone is not claimed to inspect Google's internal context or prove semantic correctness of every answer.

Sanitized evidence: ignored backend/.local/phase7-container-result.json. The backend cold/Neon connection check initially returned a sanitized 503; later direct/readiness checks and the complete flow passed. The intermittent environment connectivity issue is recorded as a remaining limit, not claimed fixed.

## Two-tab browser check

A first tab selected an old administrator conversation. A second tab signed out and signed into a separate synthetic Employee. Refreshing the first tab correctly changed the profile, cleared the old conversation/history and removed Administration navigation. This verifies the principal-change fix on revalidation; it is not an instant cross-tab push mechanism.

The browser fixture account was disabled after verification and its temporary plaintext credential file removed. Evidence: ignored backend/.local/phase7-browser-result.json. The final browser handoff returns to the login page; the user's existing Google administrator is unchanged.

## Release fixes verified

- Readiness now expects schema 0002 and has a regression test tied to migration head.
- Production API docs/OpenAPI are disabled; production Secure/HttpOnly cookie behavior remains covered.
- Response security headers are present without duplicate gateway/upstream values.
- Excess authentication requests get a distinct sign-in throttling message, not a Gemini-capacity message.
- Images omit runtime credentials and private source documents. The recreated API uses the same PDF bind mount and Neon database.

## Scope and remaining work

V1 is implemented and locally verified. This phase did not provision public hosting, DNS or a TLS certificate. Follow deployment.md before publishing on a selected host. Advanced-model availability, external network stability, future dependency advisories and unscanned OS-image packages remain outside the successful checks above. The supplied HTTP local stack uses development auth cookie flags; production mode requires the real HTTPS origin.
