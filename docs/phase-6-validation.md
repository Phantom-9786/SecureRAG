# Phase 6 validation â€” 2026-11-01

Story: an administrator uploads a document, controls its visibility, creates a user, assigns a role and edits category grants; an ordinary user cannot enter administration or call its APIs.

## Automated results

| Check | Result |
|---|---|
| Backend local suite | 90 passed, 18 skipped |
| Real Neon admin/auth/document suite | 10 passed in 290.81 seconds |
| Frontend API transport tests | 8 passed |
| TypeScript / production build | Passed |
| Ruff | Passed |

The 18 skipped backend cases are explicitly opt-in database tests. This phase separately ran the 10 relevant real Neon admin/auth/document cases. Those tests use a private transaction-scoped schema and roll back fixture records. Their embedding responses are mocked; real provider ingestion was separately verified below. The existing Starlette/httpx deprecation warning remains nonfatal.

The two new Neon cases verify Google-user provisioning, CSRF/Origin enforcement, duplicate handling, no returned password/Google subject, ordinary-user denial and independent users.manage / roles.manage / documents.manage lookup scopes. Existing last-admin, current-grant, deactivation, document lifecycle, revoked uploader, failure, rate-limit and upload-limit tests also passed.

The frontend multipart test verifies that the browser owns the Content-Type boundary, while cookies and X-CSRF-Token are included. The API client never automatically retries a mutation.

## Live browser and data flow

| Boundary | Evidence |
|---|---|
| Administrator session | Real password login through Next.js rewrite; Administration entry visible |
| Management reads | Documents, Users and Roles & access loaded real API records |
| PDF upload | Browser form submitted a labelled synthetic PDF; backend returned 201 |
| Ingestion | Real Gemini embeddings persisted; ready status with one 1536-dimension chunk verified |
| Visibility | Uploaded PDF active after indexing; browser Deactivate returned 200 and row became inactive |
| User creation | Password-account form created a labelled synthetic user with Employee role, HTTP 201 |
| Role assignment | Browser saved the synthetic user's isolated verification role, HTTP 200 |
| Grant editing | Browser added Engineering to an isolated role and saved; refresh kept it selected; change was then restored to General only |
| Ordinary user UI | Real synthetic account login showed no Administration button |
| Ordinary user API | /admin/options returned 403 |
| Deactivation | Protected API disabled the synthetic user; an existing session and a fresh login attempt both returned 401; browser Refresh returned to login |
| Responsive layout | 390 × 844 viewport: document width 390 and document height 844; compact navigation and scroll-contained forms verified; override reset |

No existing role's grants were altered for live UI verification. The synthetic test role was created separately, then restored to General category access and zero management permissions. The original administrator and the user's Google Admin account were preserved.

## Issues resolved during verification

- Select controls now have explicit accessible names for Category, Role, Sign-in method and role selection.
- Focus refresh revalidates data without discarding unfinished form/file selections. Data is hidden while revalidating; failed authorization clears it.
- Clicking the already-selected section refreshes rather than leaving it in a loading state.
- Successful management changes refresh the shared document library/counts.
- Administrator content becomes inert while logout is pending, preventing a simultaneous management submit.
- Positioned workspace/table scroll containers keep hidden table captions inside the scroll boundary, removing an extra document-level vertical scrollbar.

An initial Neon request failed with a sanitized DNS-category OperationalError and HTTP 503; the next login and subsequent operations succeeded. This pre-existing intermittent connectivity behavior was not diagnosed as eliminated and remains an environment limitation.

## Artifacts and cleanup

Ignored backend/.local/phase6-live-result.json records sanitized outcomes. phase6-admin.png is the desktop preview; phase6-ui-sample.pdf is synthetic test input. The sample document is inactive, the synthetic user is disabled with old sessions revoked, and the isolated synthetic role has no management grants. These labelled records remain for verification; no existing records were deleted. No provider/database credentials are in the report.

Production deployment, a full browser automation regression suite and formal accessibility certification remain outside this phase.
