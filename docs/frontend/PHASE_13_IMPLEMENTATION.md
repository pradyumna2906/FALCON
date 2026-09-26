# Phase 13 — Frontend integration and production readiness

## Batch 1 scope (13.0–13.2)

Baseline: Phase 12 audit squash merge `fa579f0` (PR #62).
Implementation status: implemented; database and container CI gates pending.
Stage, commit and push approved for Batch 1. Not released or merged.

### 13.0 — Architecture and release contract

See ADR 0005 for topology, tokens, authentication, wireframes, performance,
security, accessibility and release gates. One reviewed batch at a time.

| Screen | Existing API | Batch 1 closure / later work |
| --- | --- | --- |
| Authentication | auth registration/login/refresh/reset/verification | Client transport now; screens 13.3; email provider 13.12 |
| Profile/settings | financial-profile GET/PUT, auth/me | Preferences GET/PUT |
| Accounts | accounts create/list | Details, metadata update and archive |
| Loans | LiabilityDetail persistence | Account-scoped liability GET/PUT |
| Budgets | budget analytics | Create/list/get/replace/archive including category limits |
| Transactions | manual CRUD and internal transfers | UI 13.5; no bank money movement |
| Imports | upload and job lookup | Bounded history listing |
| Analytics | dashboard and individual analysis endpoints | UI 13.4/13.6 |
| Forecasts | generation/history/detail | UI 13.7 |
| Goals/plans | CRUD/progress/contributions/plans/decisions | UI 13.8 |
| Scenarios | simulation/compare/select/regenerate | UI 13.9 |
| Assistant | conversation/messages/citations/delete | UI 13.10; provider 13.12 |
| Reports/privacy/notifications | No complete public lifecycle | 13.11, not fake Batch 1 buttons |

### 13.1 — Setup APIs

Use existing tables; no migration planned. Archive means retain historical
rows. Whole-user erasure is a separate privacy workflow. Preference changes do
not convert existing accounts, rewrite dates or recompute immutable snapshots.
Budget categories must be active expense categories belonging to the owner or
the system. Liability subtype must match the account type. Lists are bounded.

### 13.2 — React foundation

Foundation only: public introduction, session restoration, guarded app shell,
theme, safe transport, query lifecycle, contract generation and test tooling.
Batch 2 owns registration/login/onboarding and functional financial screens.

## Validation

Validated on 2026-09-26:

| Gate | Result |
| --- | --- |
| Full backend unit suite | 1,989 passed; 94.03% branch-inclusive coverage, above the 90% gate |
| Setup/CORS focused checks after the final HTTP-contract test | 47 passed, including the additional budget lifecycle test |
| Frontend tests | 20 passed across transport, guarded routes and session lifecycle |
| TypeScript / ESLint / production build | Passed |
| Production npm dependency audit | Zero vulnerabilities reported at validation time |
| OpenAPI / generated TypeScript | Schema drift check passed; types regenerated |
| Repository hooks including new files | Passed |
| PostgreSQL setup integration | Added and collected; skipped locally because no permitted PostgreSQL service is available |
| Container / Compose smoke | Not run locally; Docker unavailable; existing CI gates retained |

The initial JavaScript bundle is approximately 189 kB gzip. A build-time gate
enforces the 350 KiB foundation budget across all emitted JavaScript. Vite also
reports its advisory 500 kB uncompressed chunk warning; feature-level route
splitting remains necessary as later screens are implemented.

The new PostgreSQL test covers persisted decimal precision, owner isolation,
duplicate-budget conflicts, atomic replacement rollback, preferences and
historical retention after archival. It must pass in database CI before Batch 1
is accepted as fully validated. Unit tests and mocked browser tests do not
establish production readiness, browser accessibility or end-to-end behavior.

Review follow-up for Batch 2: existing financial endpoints do not universally
enforce verified email on the server. New setup endpoints do. Align existing
endpoint authorization with ADR 0003 while implementing authentication and
onboarding; do not treat the frontend route guard as that enforcement.
