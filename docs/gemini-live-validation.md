# Live Gemini setup and verification — 2026-10-31

## Configuration

Three distinct authorization keys and their three provided Cloud project IDs were imported from
the user's local credential file into ignored backend/.env. Slot numbers follow the key names
(Key 1, Key 2, Key 3), irrespective of their order in the file. Existing database/JWT secrets were
preserved. No billing settings or account subscriptions were changed.

The API was restarted with one worker. Configured models:
- Embeddings: gemini-embedding-001, 1536 dimensions.
- Basic answers: gemini-3.5-flash-lite.
- Advanced answers: gemini-3.6-flash, optional low thinking level.

Generation now has a separate 60-second budget instead of inheriting the embedding call's
30-second timeout. Thinking level is optional/configurable for compatible model families.
App-local quota budgets remain conservative defaults; actual project quotas/billing balances
have not been retrieved or inferred from the user's consumer subscriptions.

## Actual API checks

| Check | Result |
|---|---|
| Model listing, all three keys | HTTP 200 |
| gemini-embedding-001, all three keys | Valid 1536-dimensional vectors |
| gemini-3.5-flash-lite, all three keys | Text generation successful |
| Basic routed generation service | Successful, selected configured basic model |
| gemini-3.6-flash direct probes | Slots 1/2 returned text; slot 3 returned 504 |
| Advanced routed generation service | Not reliably verified; ended with GeminiBusy |
| gemini-4-argon | HTTP 429 on all three slots |
| gemini-3.1-pro-preview | Slot 1 returned HTTP 429 |
| gemini-3.8-flash | HTTP 503 on all three slots, persisted on one bounded recheck |

Listing a model is not proof of current inference capacity. The selected advanced model remains
configured, but reliable advanced generation is **pending provider availability/quota verification**.
No busy advanced answer is silently sent to the basic model. No real credentials or provider error
bodies are included in these reports. Sanitized machine-readable checks are under ignored .local/.

## Real PDF -> Gemini -> pgvector

Passed through the running HTTP API using the development administrator:
1. Uploaded a synthetic two-page PDF: HTTP 201, ready and active.
2. Extracted two chunks with original page numbers 1 and 2.
3. Called real gemini-embedding-001 and stored 1536-dimensional normalized vectors in Neon.
4. Downloaded the authorized original and compared its SHA-256 to the uploaded bytes.
5. Deactivated the synthetic sample through the admin API.
6. Confirmed ordinary listings omit it and its download returns HTTP 404.

Verified sample document ID: 97452fef-28c0-4f56-9731-9e76133c1d33.
An additional one-page diagnostic sample was also deactivated. Final recorded database state:
one admin, two inactive synthetic documents, three real embedded chunks, no leftover test schemas.
These samples are explicitly not company policy and are excluded from normal retrieval.
One initial upload returned 503 without retaining metadata; subsequent uploads succeeded. The
initial transient failure was not reproduced and is not claimed to have been diagnosed.

Local regression after the generation timeout/config changes: 56 passed, eight DB tests opt-in/skipped.
Ruff passed. Existing Starlette/httpx test-client deprecation warning remains non-fatal.

## Credential handling

The user explicitly chose to retain the existing three credentials. They remain configured and
are reused; no replacement/rotation action is pending. Diagnostic outputs use allowlisted status
metadata rather than printing source files or secret values.

Phase 3's real embedding verification is complete. Phase 4 now implements permission-filtered
question answering, citation validation and conversation APIs; see phase-4-validation.md for the
subsequent live end-to-end backend result.
