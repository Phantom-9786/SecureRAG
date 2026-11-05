# Security contract

Authorization must restrict the eligible chunk relation before vector ranking and before LLM context.
Retrieval uses current database user/role/category grants plus active, ready document predicates.
No browser-supplied role or category list can grant access. All admin routes need database-backed
administrative permissions; CORS and hidden buttons are not authorization.

Implemented in Phase 2: Argon2id passwords, short-lived HttpOnly cookie JWT, CSRF protection,
current user checks, token revocation, database-backed administrative grants, and last-admin protection.
Private authorized PDF download endpoints are implemented in Phase 3. Phase 4 implements
owner-scoped conversations and permission-filtered exact vector retrieval through a materialized
authorized chunk relation, with current database grants and active/ready document checks.
History rechecks every source used in an answer before displaying stored content after grant changes.

Citation metadata is resolved from authorized retrieval results rather than trusted model-generated IDs.
Lack of evidence must not disclose whether a restricted document exists.
Permission changes apply to subsequent requests, without cancelling requests already in flight.

Process/readiness endpoints are public. Readiness and database failures return generic responses,
never database connection details. Secrets are redacted in settings repr and excluded from source
control. Input validation errors omit raw values, including passwords. See phase-2.md for cookie,
CSRF and administration rules. See phase-3.md for PDF validation, private storage, upload limits,
authorization rechecks and atomic publication. See phase-4.md for secure retrieval, citation
validation, atomic turns and history withholding after access changes.

## Phase 5 browser boundary

The user portal forwards same-origin /api/v1 requests through Next.js. FastAPI remains the
authorization boundary. JWT cookies are HttpOnly; the profile/CSRF token lives in React memory.
No conversation or credentials are persisted in localStorage/sessionStorage. React renders model
answers as escaped text. Source URLs are constructed from document IDs to protected PDF routes.
Focus, conversation selection and Refresh reload permission-aware history; there is no push
revocation guarantee. A failed network request can have committed, so questions are not retried
automatically. See phase-5.md and phase-5-validation.md.

## Google identity

Google sign-in verifies provider tokens using google-auth, binds login to an expiring one-time
database nonce and an HttpOnly browser cookie, and applies the same exact-Origin checks.
Only provisioned active users can sign in. Initial email binding requires a verified Gmail or
Google Workspace identity; later logins use the unique Google subject. No automatic signup,
role assignment or replacement of an existing subject is permitted. Google tokens are not
persisted. See google-signin.md for setup, limits and verification status.

## Phase 6 administration

Management UI visibility follows current permission codes. Backend dependencies enforce each
operation independently; admin/options exposes only the lookup data required by those grants.
Google-user provisioning is protected by users.manage plus Origin and CSRF checks. It issues no
usable password and performs no automatic Google subject binding. Existing last-admin guards,
source permissions and token-version revocation remain authoritative. UI mutations are not
automatically retried; see phase-6.md for the full flow and limits.

## Final V1 release review

Read security-review.md for the Phase 7 findings, corrected readiness/account-switch boundaries,
edge throttling, container isolation, dependency audit scope and remaining limitations. Full
validation is in phase-7-validation.md. Local Docker is deployed; public TLS hosting is separate.
