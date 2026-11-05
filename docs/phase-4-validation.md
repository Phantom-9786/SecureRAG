# Phase 4 verification — 2026-10-31

## Automated checks

- Local suite: **73 passed**. Thirteen database tests across all phases are opt-in/skipped in
  the normal run. Those skips are not claimed as live coverage.
- Phase 4 PostgreSQL suite: **five passed** in the final 185.56-second run using real Neon/pgvector in isolated,
  rolled-back schemas. Gemini transports/generation are explicitly mocked in those tests.
- 17 new unit cases cover SQL materialization, query embedding task/dimensions, context limits,
  question validation, citation membership and fail-closed references.
- Ruff, Python compilation and Alembic schema comparison pass. No new migration is needed.
- Existing Starlette/httpx test-client deprecation warning remains non-fatal.

Security behaviors checked:
- Denied HR/Finance/Management vectors are closer than eligible vectors, but Engineer queries
  still retrieve General/Engineering only. The actual SDK HTTP payload excludes restricted,
  inactive, failed and below-threshold chunk canaries.
- Citation titles/pages/IDs come from backend metadata; forged S999 references are rejected.
- All used context chunks are stored, including uncited ones. Revoking an uncited source still
  withholds the entire old answer and removes citations. Document deactivation does the same.
- Other users, including admin, cannot read/query another user's conversation.
- Empty authorized scope skips both AI calls; low-relevance evidence skips generation.
- Provider errors and injected source-write failures leave no partial message pair.
- Authorization changes during embedding affect retrieval. Changes during generation discard
  the result. User deactivation during generation returns 401 without saving a turn.
- A competing question to the same conversation yields 409 for the losing request and retains
  one complete user/assistant pair.

## Real running API -> Gemini -> Neon

The live smoke passed using the existing development administrator and configured keys:

| Boundary | Evidence |
|---|---|
| Login | 200 |
| Create owned conversation | 201 |
| Empty active scope | 201, insufficient evidence, model none, no sources |
| Activate known synthetic PDF | 200 |
| Query embedding / filtered vector search / generated answer | 201 |
| Model | gemini-3.5-flash-lite |
| Citation | Original PDF page 2 |
| Persisted history | Four ordered messages, including the initial abstention turn |
| Deactivate PDF | 200 |
| Read old answer afterward | Withheld, with empty citations |

Conversation ID: 91815f3e-8237-4363-ab96-f749ddb34db7.
Source ID: 97452fef-28c0-4f56-9731-9e76133c1d33.
The synthetic source is inactive after verification. The conversation is labeled synthetic.
Sanitized machine result is in ignored backend/.local/phase4-live-result.json.

An initial live create attempt returned a generic database 503; a direct operation subsequently
succeeded. Create responses now use flushed metadata captured before commit, avoiding an extra
post-commit refresh. Database logs expose only exception class, safe category and SQLSTATE.
The successful full live smoke ran after this change; external connectivity is not claimed fixed.

Advanced-model capacity remains subject to provider limitations in gemini-live-validation.md.
This smoke verifies a real basic route. Citation membership checks do not prove factual entailment;
similarity thresholds still need evaluation on actual company data. In-flight provider requests
cannot be recalled on revocation. UI work remains in Phases 5/6.
