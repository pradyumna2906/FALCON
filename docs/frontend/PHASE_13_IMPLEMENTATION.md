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

Batch 2 closes the recorded email-verification enforcement gap on all financial
routers. Authentication and recovery retain their separate access contracts.

## Batch 2 — Checkpoints 13.3–13.5

Approved scope: implementation, staging, commit and push. Built on Batch 1
commit `2ed31e2`; Batch 1 is still unmerged, so review includes that dependency.

| Checkpoint | Implemented behavior |
| --- | --- |
| 13.3 Authentication and onboarding | Registration, login/logout, verification/resend, recovery/reset, current-user refresh, verified route guards, editable financial profile and guided account/import links |
| 13.4 Overview | Responsive navigation, date/currency filters, server-provided income/expense/cash-flow/savings cards, cash-flow history table, spending shares, health factors, prioritized insights, goal progress, freshness and completeness |
| 13.5 Money | Account creation/metadata/archive, liability terms, manual transaction create/edit/delete, filters/cursor pagination, transfers, CSV/XLSX/PDF review-confirm-upload and issue history, category corrections and merchant memory |

Money values remain decimal strings. Only visual bar positioning converts a
server-supplied ratio to a browser number. Currency is not inferred across
accounts, nor are financial totals recalculated in JavaScript. Imported and
transfer transactions do not expose unsupported manual editing/deletion.
Server errors preserve form context; writes are never replayed after ambiguous
network/server failures. Confirmation dialogs precede destructive UI actions.
Files/passwords stay in memory for the import and are cleared on completion,
cancellation or navigation away. No private data is persisted in browser storage.

All financial API routers now enforce verified email centrally and document
403 in OpenAPI. A contract-driven test exercises every financial operation
with an unverified principal. Existing PostgreSQL API fixtures now consume real
verification challenges via a test-only encrypted-outbox helper instead of
bypassing verification. No migration or production provider is introduced.

### Batch 2 validation and remaining gates

- Frontend: 31 unit/component tests passed; TypeScript, ESLint, production build
  and production dependency audit passed. All JS bundles total about 233.5 KiB
  gzip, below the conservative 350 KiB build gate. Pages are split by route.
- Backend: 1,992 unit tests passed with 94.49% branch-inclusive coverage,
  including the contract-driven financial verification gate.
- PostgreSQL: 46 integration tests collect, including a new registration →
  verification → profile → account → CSV import → correction → merchant memory
  → dashboard → refresh/logout workflow. Execution requires database CI.
- Chromium: a production-build workflow covers onboarding, account creation,
  import confirmation/rejections, correction, overview, mobile width and logout
  using synthetic API fixtures. This workflow passed in frontend CI, together
  with contract export, generated-type drift checks, lint, tests and build.
- API container build and Compose smoke passed in CI. Docker/Compose and
  PostgreSQL execution remain unavailable locally.

Notification persistence and delivery remain 13.11; the overview's Insights
action exposes actual backend recommendations without inventing notifications.
Email provider delivery remains 13.12. Dedicated analytics/forecast/goal/scenario/
assistant/report screens remain in their later approved checkpoints. This batch
does not claim full production readiness or complete accessibility certification.

CI hardening installs the API optimization dependencies for contract export.
Imported category corrections first store classification provenance when needed;
repeat corrections preserve the existing user override. Manual categories use
the transaction edit form. Tests cover both first-time and repeated corrections.
