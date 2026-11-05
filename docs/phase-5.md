# Phase 5 — User portal

Phase 5 connects the existing secure backend to a usable Next.js user workspace. Admin management screens belong to Phase 6.

## What is available

- Company account login, existing-session restore, logout and expired-session handling.
- New conversations, own conversation history and self-contained document questions.
- Auto/basic/advanced model selection using the existing Gemini peer pool and limiter.
- Source cards showing document title, source label and original PDF page number.
- Protected original PDF downloads and a library of currently accessible documents.
- Loading, busy, validation, server-error, no-evidence and revoked-answer states.
- Desktop sidebar and narrow-screen navigation, keyboard labels, visible focus and alert/status announcements.

There is no registration screen: accounts are provisioned by administrators. There is no streaming or multi-turn memory in V1. Each question must contain its own context.

## Files and responsibilities

| File | Responsibility |
|---|---|
| frontend/next.config.ts | Same-origin /api/v1 rewrite to FastAPI and 180-second proxy timeout |
| frontend/src/lib/api.ts | API types, cookies, CSRF header, safe errors and pagination |
| frontend/src/components/login.tsx | Accessible login form and invalid-credential state |
| frontend/src/components/workspace.tsx | Session lifecycle, conversation selection, sending, refresh and library |
| frontend/src/components/message.tsx | Plain-text answer and protected source links |
| frontend/src/app/page.tsx | Workspace entry point |
| frontend/src/app/globals.css | Responsive layout, states and focus styling |

## Request flow

1. The browser loads the static application shell and requests /api/v1/auth/me with its session cookie.
2. Next.js forwards /api/v1 requests to the configured API server. It does not decide permissions or mint sessions.
3. Login sends the browser Origin to FastAPI. FastAPI validates credentials and issues its HttpOnly JWT cookie.
4. The returned profile includes the CSRF token, stored only in React memory. Mutations send X-CSRF-Token. JWTs, prompts and history are not saved in localStorage or sessionStorage.
5. Conversation lists, documents and history are loaded from real APIs. Pagination is followed in 100-item pages.
6. On send, the client refreshes the profile/CSRF token, creates a conversation if needed, then submits the question and model mode. A ref lock prevents duplicate submissions while the request is running.
7. After completion, history is fetched again from the backend. The backend rechecks access and can withhold an older answer whose supporting source is no longer visible.
8. Selecting another conversation invalidates stale reads using a request sequence. Refresh and browser focus fetch current grants/history again. Hidden-tab history is cleared while idle.

The UI is not an authorization boundary. Editing frontend state or a URL never grants source access. Links are built from document IDs to the protected download endpoint; model output is rendered as escaped plain text, never raw HTML or arbitrary generated hyperlinks.

## Setup

From D:\RAG_Project, use separate PowerShell terminals:

```powershell
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

```powershell
cd frontend
npm.cmd ci
# Only on a fresh installation; preserve an existing .env.local.
if (-not (Test-Path .env.local)) { Copy-Item .env.example .env.local }
npm.cmd run dev -- --hostname localhost
```

Open http://localhost:3000. Backend FRONTEND_ORIGIN must exactly equal this origin. Do not alternate localhost and 127.0.0.1 in the browser. API_BASE_URL is a server-only destination (default http://127.0.0.1:8000); changing it requires restarting Next.js and rebuilding a production bundle. No Gemini keys belong in the frontend.

Next.js external rewrites use a 30-second default timeout in this installed version. Real embedding + generation exceeded it in verification; experimental.proxyTimeout is explicitly set to 180000ms. Configure any future deployment proxy to allow the same request budget. This is an installed-version experimental setting, validated by typecheck, build and a live request.

Use the existing provisioned admin credentials stored privately in backend/.local/bootstrap-admin.txt for this development installation. Do not publish that file. The synthetic verification account is disabled after testing.

## Verification

```powershell
cd frontend
npm.cmd run typecheck
npm.cmd test
npm.cmd run build
```

See phase-5-validation.md for actual browser/API evidence. Existing backend tests remain the permission enforcement regression suite.

## Interview explanation

The frontend orchestrates requests and presents state. FastAPI authenticates every call, authorizes document scope before vector ranking, validates citations and checks access again when history or a file is read. The HttpOnly cookie reduces JavaScript access to session credentials; the Origin check and signed CSRF token protect cookie-authenticated writes. React state is temporary UI state, not trusted identity.

An uncertain network failure does not imply the operation failed to commit. The UI preserves the draft and advises refreshing history before resubmitting; it never automatically retries a question. Durable request idempotency is not implemented in V1.

## Limits

- Permission changes become visible on a fresh server request, focus, conversation selection or Refresh. There is no push revocation, and already downloaded content cannot be recalled.
- The portal loads all pages into memory; very large histories need incremental loading later.
- The selected conversation is local UI state; a page reload shows the new-conversation view, with saved conversations available in the sidebar.
- Model availability and quotas remain provider dependent. Choosing Advanced does not guarantee current capacity and does not silently downgrade.
- Source downloads return the original PDF; the citation card identifies the relevant page.
- Admin UI, deployment and final hardening remain later phases.

References: [Next.js rewrites](https://nextjs.org/docs/app/api-reference/config/next-config-js/rewrites), installed Next.js dist/docs, and the React best-practices / full-story verification skills used for implementation review.

## Google sign-in extension

Google Identity Services is integrated with the existing backend sessions. See
[setup and security validation](google-signin.md) for the OAuth Client ID, exact origins,
provisioned-account rules and the live-login configuration still required.
