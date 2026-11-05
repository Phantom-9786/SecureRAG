# Phase 6 — Administration portal

Phase 6 adds the management interface to the existing Next.js workspace. Users enter **Administration** from the sidebar when their current role has at least one management grant. The backend remains the authority for every read and write.

## Available tools

| Section | Required permission | Actions |
|---|---|---|
| Documents | documents.manage | Upload/index a PDF, inspect ingestion status, activate/deactivate, search titles/filenames |
| Users | users.manage | Create Google or password accounts, change role, activate/deactivate, search names/emails |
| Roles & access | roles.manage | Edit category access and management permissions, review full replacement before saving |

Navigation checks permission codes, not the role name Admin. A document manager can use document tools without receiving user or role administration. Management permissions do not grant document-read access by themselves.

## Backend additions

- `GET /api/v1/admin/options`: returns only the lookup data allowed by current management grants. User managers receive role IDs/names; document/role managers receive category IDs/names; role managers receive permission IDs/codes. Ordinary users receive 403.
- `POST /api/v1/users/google`: provisions a Google sign-in user using name, email and role_id. It generates and discards a strong random password before storing its Argon2 hash. No usable password is issued. Google still verifies the email and binds the stable subject at first login.
- Existing `/users`, `/roles/{id}/grants` and `/admin/documents` endpoints handle other operations. Existing exact Origin, signed CSRF, current-grant checks, administrator lock and last-active-admin invariant are reused.

No new schema migration, provider, key pool, queue or external service was introduced. The Google account creation option is an explicit administrator action, not public registration. Gmail or Google Workspace ownership is required for initial Google binding; arbitrary third-party verified Google email alone remains insufficient.

## Frontend files

- `components/admin/panel.tsx`: permission-filtered sections, fresh profile/CSRF checks, read invalidation, mutation lock, status/error messages.
- `components/admin/documents.tsx`: multipart upload, category/title/file fields, size check, indexing/activation table.
- `components/admin/users.tsx`: account creation and per-user role/active-status forms.
- `components/admin/roles.tsx`: category/permission checkboxes with a complete grant preview.
- `lib/admin.ts`: typed management contracts and permission-to-section mapping.
- `lib/api.ts`: multipart transport leaves Content-Type to the browser so its boundary is correct. Existing cookies and CSRF headers remain in place.
- `components/workspace.tsx`: management navigation and shared workspace refresh after changes.

## State and safety behavior

1. Opening a section fetches the current profile, allowed lookups and server-side records. Lists follow backend pagination in 100-item pages.
2. A mutation refreshes the current CSRF token, then sends exactly one request. A ref lock prevents duplicate submissions; navigation and other mutations are disabled while saving.
3. The panel rereads server state after the request. The document library is refreshed after successful changes as well.
4. Background reads use a sequence number so old responses cannot replace the selected section. Focus refreshes preserve forms, including the PDF file selection; data is hidden during revalidation. Failed/unauthorized reads clear management data.
5. If permissions change, section visibility follows the fresh profile. A missing permission on the backend returns 403 regardless of frontend state. Session expiry returns to login.
6. A network failure may occur after a commit. There is no automatic replay: refresh the current view before resubmitting a creation/upload.
7. Passwords are uncontrolled form inputs, not persisted in browser storage, and cleared after submission. Existing passwords/Google subjects are never returned by management APIs.
8. Role grants are a full replacement. The preview identifies the exact role and selected categories/management grants. A notice identifies edits to the caller's own role. The backend prevents removing the final active administrator.

Successful PDF uploads become active only after complete indexing. A processing/failed PDF cannot be activated. There is no retry, OCR, delete or background recovery UI. Inactive documents remain private and are excluded from retrieval/download under the existing rules.

## Local use

Start the configured backend with one worker and the frontend dev server, then sign in at http://localhost:3000. The user's provisioned Google administrator can use the new sidebar entry. Existing Google model routing and Auto selection are unchanged.

```powershell
cd D:\RAG_Project\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

```powershell
cd D:\RAG_Project\frontend
npm.cmd run dev -- --hostname localhost
```

## Checks

```powershell
cd D:\RAG_Project\backend
.\.venv\Scripts\python.exe -m pytest --tb=short
.\.venv\Scripts\ruff.exe check .
$env:SECURERAG_RUN_DB_TESTS='1'
.\.venv\Scripts\python.exe -m pytest tests/test_admin_integration.py tests/test_auth_integration.py tests/test_documents_integration.py -v --tb=short
```

```powershell
cd D:\RAG_Project\frontend
npm.cmd test
npm.cmd run typecheck
npm.cmd run build
```

Actual results and live-flow evidence are in [Phase 6 validation](phase-6-validation.md).

## Current limits

The UI edits existing roles; creating/deleting roles/categories and deleting users/documents are outside this phase. Google linking/unlinking, password resets, audit logs, distributed rate limiting and production deployment are separate features. Management tables are loaded into memory; server-side filtering/incremental loading can be added for larger installations. Permission revocation is enforced at request boundaries; there is no push revocation of already displayed data.

Next planned phase: final security verification, deployment packaging and interview documentation (Phase 7).
