# Phase 5 verification — 2026-10-31

Story: a provisioned Employee signs in through Next.js, asks a document question, receives a real Gemini answer with a page citation, opens the protected original, revisits history, then signs out.

## Automated checks

| Check | Actual result |
|---|---|
| Frontend TypeScript | Passed |
| Next.js production build | Passed with explicit 180-second proxy timeout |
| Frontend API-boundary tests | 7 passed, 0 failed |
| Backend regression suite | 73 passed, 13 skipped |

The 13 backend tests require an explicit database-test opt-in; they were not rerun this phase because backend behavior was unchanged. Phase 4 records the previous real Neon integration results. The existing Starlette/httpx deprecation warning remains nonfatal.

The frontend tests use mocked HTTP responses to verify the cookie/CSRF contract, non-retry behavior on 429, safe proxy-error recovery text, session-status propagation, empty logout responses, pagination beyond 100 and cancellation. They do not call Gemini or replace the live evidence below.

## Live browser / API evidence

| Boundary | Result |
|---|---|
| Invalid password | Login stays visible with “Invalid email or password” |
| Correct login through localhost:3000 rewrite | HTTP 200; Employee workspace renders |
| Cookie | HttpOnly present; reload restores the session |
| CSRF omitted on conversation create | HTTP 403 through frontend proxy |
| Real question -> Gemini -> Neon retrieval | Three persisted question/answer pairs with real Gemini generation |
| Final send after timeout fix | HTTP 201, answer renders, draft clears, basic model shown |
| Citation UI | S1, synthetic PDF title, original page 2 and protected download link |
| PDF | Browser click reached protected endpoint with HTTP 200; separate authenticated proxy check received %PDF- bytes |
| Source deactivated | HTTP 404 for PDF; zero accessible library entries |
| History after source deactivation | All three previous grounded answers withheld, no source cards |
| Empty-evidence question | Canonical no-evidence answer, no source cards |
| UTF-8 input limit | 1,000 Devanagari characters rejected by client byte check; draft preserved |
| Logout | HTTP 204 and login screen with “You have signed out” |
| Narrow viewport | Compact navigation, readable history/composer; measured document width equals viewport width (433 CSS px in browser runtime) |

The mobile capability was reset after inspection. Desktop chat preview is saved in ignored backend/.local/phase5-chat.png. The source was active when that preview was captured; it was restored inactive afterward.

## Issue found and fixed

The first real answer took longer than Next.js's default 30-second external proxy timeout. The browser saw a proxy failure although the backend later committed the turn. Setting experimental.proxyTimeout to 180000ms allowed the final live send to complete and render normally. Safe proxy-error text now advises refreshing history before resending. Automatic request replay is not implemented.

A development-server restart while formatting configuration briefly disconnected an earlier verification tab. Testing continued in a fresh tab after confirming the server returned HTTP 200. This was a local development restart, not an additional production failure.

## Test data and cleanup

A clearly labelled synthetic Employee account was used, with only its existing role grants. The original administrator account and credentials were not changed. The existing synthetic two-page PDF was temporarily activated. Cleanup verified the account is inactive, token version incremented, PDF inactive and a fresh login attempt returns 401. Synthetic conversations remain as inactive-account verification data; no existing records were deleted.

Sanitized HTTP outcomes are in ignored backend/.local/phase5-live-result.json. No database/provider secrets are in this report.

## Scope limits

This verifies the user portal against real local servers, Neon and the basic Gemini model. It does not certify production hosting, every device, accessibility conformance, current advanced-model capacity or instant push revocation. Those provider/deployment boundaries and the Phase 6 admin portal remain separate work.
