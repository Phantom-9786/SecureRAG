# Google sign-in (Phase 5 extension)

Google Identity Services supplies a signed Google ID token; FastAPI verifies it and issues the same SecureRAG session cookies used by password login. This is OpenID Connect sign-in, not access to Google Drive, Gmail or Calendar. Existing password login continues to work.

## Activate locally

1. Open [Google Auth Platform](https://console.cloud.google.com/auth/overview) and choose an existing Cloud project.
2. In **Branding**, set application name **SecureRAG**, your support email and developer contact email. Complete Google's required fields.
3. In **Audience**, use **External** for personal Gmail accounts. While the app is in testing, add your Google email as a test user where the console requests it. For an organization-only app, use the audience supported by your Workspace organization.
4. In **Clients**, choose **Create client → Web application**. Add authorized JavaScript origins **http://localhost** and **http://localhost:3000**.
5. Copy the OAuth **Client ID**, ending in `.apps.googleusercontent.com`, into ignored `backend/.env`:

```dotenv
GOOGLE_CLIENT_ID=YOUR_WEB_CLIENT_ID.apps.googleusercontent.com
```

Do not put a Gemini API key in this field. This GIS popup callback flow does not need a Client Secret or authorized redirect URI. The browser receives only the public Client ID from the backend configuration endpoint. No NEXT_PUBLIC variable or frontend rebuild is needed when the ID changes.

6. Restart the backend, reload http://localhost:3000 and select the Google-rendered **Continue with Google** button.
7. Use an email already provisioned as an active SecureRAG user with the intended role. A Google Cloud test user is not a SecureRAG account. The initial development administrator uses `admin@securerag.example.com`, which cannot match a real Gmail account. Provision a separate account with the intended Gmail/Workspace address through the existing administrator user API; Phase 6 will add the management UI. No role or administrator access is inferred from a Google email or domain.

Production needs HTTPS, the production origin registered in Google Cloud, APP_ENV=production and an exact FRONTEND_ORIGIN. Follow Google's consent-screen publishing requirements for your audience. The existing same-origin Next.js rewrite remains in place.

## Behavior and security

- `GET /api/v1/auth/google/config` exposes only `{enabled, client_id}`.
- `POST /auth/google/challenge` requires the exact trusted Origin. It creates a random five-minute nonce and a separate random HttpOnly, SameSite=Strict browser cookie. Only SHA-256 digests are persisted. Expired challenges are cleaned when another challenge is created.
- The Google-rendered popup button requests a token containing that nonce. There is no automatic account selection or One Tap prompt.
- `POST /auth/google` accepts a bounded SecretStr credential, requires the trusted Origin and initiating cookie, and verifies Google signature, audience, issuer, issued-at, expiry, verified email and nonce.
- Google certificate requests have a ten-second timeout. Raw tokens/provider errors are not logged or returned. No database transaction is held during certificate verification.
- An atomic DELETE consumes the browser-bound database challenge once. A second request with the same challenge cannot sign in again.
- Returning users are looked up by unique Google `sub`, not by a changing email.
- Initial binding only matches an existing active account when Google is authoritative for that verified email: Gmail, or a Google Workspace identity with the signed `hd` claim. Verified third-party email alone does not permit initial binding. Such users can keep using password login; explicit password-confirmed linking is not implemented here.
- A different Google subject cannot replace an existing binding. Unknown or disabled users are denied; no signup or role changes occur.
- The application reloads current role/category grants. Google profile fields never supply permissions.
- Google credentials are not stored. The application session continues to use HttpOnly JWT + CSRF, token-version revocation and existing logout. Logout signs out of SecureRAG, not the Google account itself.
- Failed sign-in refreshes the nonce; an idle login page renews it before expiry. An account chooser left open longer than the nonce lifetime may require retrying.

## Schema and implementation

Migration **0002** adds nullable unique `users.google_subject` and `google_login_challenges`. Existing users/password hashes/grants remain intact. The original 0001 SQL snapshot was preserved; its regression check now pins its immutable checksum while current-schema drift is checked with Alembic.

Files: `app/services/google_auth.py`, `app/api/routes/google_auth.py`, `app/models/oauth.py`, `migrations/versions/0002_google_signin.py`, and `frontend/src/components/google-signin.tsx`. Backend directly declares `google-auth[requests]`; the official GIS script is loaded only when configured. Existing auth was retained rather than introducing a second session system.

## Validation (2026-10-31)

- Backend local suite: **89 passed, 16 skipped**. This includes 16 new Google tests using the real google-auth verifier against locally signed RSA tokens and mocked certificate HTTP responses. Invalid signatures, audience, issuer, expiry, future issuance, verification status, nonce and provider transport failures are covered.
- Real Neon integration: **6 passed in 158.50 seconds** (3 Google flow + 3 existing authentication tests). Google flow tests cover provisioned-user binding/current grants, replay, logout, unknown/inactive accounts, non-authoritative email, cookie/nonce/expiry binding and conflicting subject. Provider identity responses are mocked in this suite; they are not Google-issued live tokens.
- Existing authentication integration checks were rerun against Neon alongside the Google suite.
- Frontend API tests: **7 passed**; TypeScript and production build passed.
- Migration 0002 applied to the existing Neon **development** branch; `alembic check` reported **No new upgrade operations detected**.
- Browser verified the unconfigured state: disabled Google sign-in button with an explicit message, while the normal password form remains usable.
- OAuth Client ID has now been imported from the user-specified local file into ignored backend/.env, and the backend restarted. The same-origin config and challenge endpoints returned HTTP 200; enabled=true and a nonce were verified without printing credentials. The official Google-rendered button is visible. The in-app browser did not expose an account chooser when clicked; no console errors were recorded. A successful live Google login remains pending a matching provisioned workspace account and completion of Google sign-in in a regular browser. No live authentication success is claimed.

References: [Google setup](https://developers.google.com/identity/gsi/web/guides/get-google-api-clientid), [server verification](https://developers.google.com/identity/gsi/web/guides/verify-google-id-token), [GIS JavaScript API](https://developers.google.com/identity/gsi/web/reference/js-reference).
