# Phase 13 — Frontend integration and production readiness

## Batch 1 scope (13.0–13.2)

Baseline: Phase 12 audit squash merge `fa579f0` (PR #62).
Implementation status: Batches 1 and 2 merged in PR #63 (`8ab0566`) after all
database, browser, container and unit CI gates passed. The validation records
below preserve the results available at each implementation stage.

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

The HTTPS PostgreSQL workflow also exposed a refresh-cookie formatting error:
database timezone objects were rejected by the HTTP date formatter. Cookie
expiry now normalizes to `datetime.UTC`, preserving the expiry instant. Two
additional unit cases reproduce UTC `ZoneInfo` and non-UTC database timestamps;
both failed before the fix and pass after it. The integration workflow covers
refresh rotation and logout revocation with secure cookies enabled.

## Batch 3 — Checkpoints 13.6–13.8

Baseline: PR #63 squash merge `8ab0566`. Implementation, stage, commit and push
approved together. This batch reuses the Phase 8–10 APIs; no production service,
new dependency or database migration is introduced.

| Checkpoint | Implemented behavior |
| --- | --- |
| 13.6 Analytics | Date/currency filters; prior-period cash-flow and spending comparison; category, merchant and account views; bounded account transaction drill-down; recurring/subscription evidence; leak/anomaly evaluations; budget creation, variance and overspend risk; health factors and prioritized insights |
| 13.7 Forecasts | Four forecast targets; history and horizon controls; immutable run history/detail; selected model and error metrics; expected line with 80%/95% intervals; exact-value table; explicit reliability and insufficient-history guidance |
| 13.8 Goals and planning | Create/edit/complete/cancel goals; manual and transaction-linked contributions; contribution removal; server progress; currency-specific planning snapshot; generate/approve/reject/regenerate plans; allocation schedules, probabilities, shortfalls, risk labels and decision/version history |

All financial numbers remain server-owned decimal strings. SVG conversion is
limited to chart positioning. Unknown probability is shown as unavailable,
not zero. Mixed currencies are never combined by the frontend. Goals use the
backend cancellation lifecycle, retaining history rather than inventing delete.
Blocked plans cannot be approved; rejected/superseded plans cannot regenerate.
Approval, rejection, regeneration and destructive actions require confirmation.
Writes retain the existing single-attempt failure behavior and owner cache scope.

Analytics queries load only for the selected section. History lists and
transaction drill-down use documented bounds. Each analytical result has
loading, error/retry, empty and partial-data evidence; absence of a result never
creates an example balance. Forecast charts have exact tabular alternatives.

Local validation: 47 frontend tests, TypeScript, ESLint and production build
passed; all emitted JavaScript is approximately 245.7 KiB gzip against 350 KiB.
The additional PostgreSQL test collects successfully. It imports 12 months of
synthetic transactions, generates/retrieves all four forecasts, checks analytics,
then exercises contributions, snapshot/plan generation, approval, regeneration,
rejection, cancellation and foreign-owner isolation through real API routes.
A new production-build Chromium workflow covers the corresponding UI journey,
confirmations, mobile width and absence of private browser storage. PostgreSQL
and browser execution are CI merge gates; the PR records their final results.

Scenarios (13.9), Assistant (13.10), reports/privacy/notifications (13.11),
production delivery (13.12), deployment (13.13), and release audit (13.14) remain
outside this batch. It does not claim all of Phase 13 is complete.

## Batch 4 — Checkpoints 13.9–13.11

Baseline: merged PR #64 (`67ebb9c`). Implementation, stage, commit and push are
approved together. This batch integrates the Phase 11/12 APIs and adds the
missing owner workspace endpoints for reports, privacy and notifications.

| Checkpoint | Implemented behavior |
| --- | --- |
| 13.9 Scenarios | Alternative builder for income, expense, one-time costs, recurring costs, debt, income interruptions, goal targets/deadlines/priorities/contributions/pauses and reserves; saved-plan source; Monte Carlo history; ranked comparison, probability/shortfall evidence, sensitivity, monthly capacity, selection/clear/regeneration and event history |
| 13.10 Assistant | Conversations/history, bounded questions, completed verified answers, evidence/citations/reliability/warnings/refusals, suggested follow-ups, copy with citations, retention expiry and confirmed deletion; stable idempotency key when retrying an unchanged question |
| 13.11 Workspace | Monthly cash-flow PDF, transaction CSV, persisted import notification inbox/read/dismiss/preferences, account preferences, active session listing/revocation, password-confirmed whole-user JSON export, typed-confirmation account erasure |

### Data and safety contract

- Financial calculations and ownership remain server-controlled. Scenario
  inputs do not update real transactions, goals or approved plan allocations.
  Unknown probability remains unavailable; zero is displayed as zero.
- Assistant displays only the atomic verified response. A failed provider or
  network response never reveals partial/unverified text. External assistant
  provider activation remains 13.12; unavailable responses remain explicit.
- Downloads are authenticated same-origin requests with `no-store` and a
  response-generation guard. A response finishing after sign-out is discarded.
  CSV cells neutralize spreadsheet formulas; monetary decimals remain strings.
- PDF summarizes eligible posted records for a completed month and currency,
  including confidence and exclusions. CSV includes all monthly owner records
  in that currency with status/type columns. Files are generated synchronously
  and not retained as server jobs or public download URLs.
- Export includes all retained owner financial tables and decrypted assistant
  turns; password hashes, refresh tokens, challenge tokens, delivery payloads,
  and global knowledge are excluded. A 100,000-row / 32 MiB limit fails explicitly
  instead of silently truncating. This is a portable data export, not a restore
  archive or a transactionally frozen analytical snapshot.
- Password reauthentication guards export, erasure and session revocation. A
  dedicated process-local limiter bounds these sensitive actions to ten per
  owner per minute, one at a time. Distributed edge enforcement is a 13.12 gate.
- Erasure deletes the live user ownership root and cascades private records,
  invalidating all sessions. Deployment backup retention and deletion from a
  user's downloaded files are outside this live-database action.
- Notification migration `a3d9e6f8b215` adds two owner-cascading tables. Import
  status events are refreshed explicitly from the latest 100 imports and
  deduplicated by owner/source/status. Dismissal persists across synchronization.
  Opt-out suppresses new events; existing inbox history is retained. No email,
  push delivery or scheduled background job is claimed in this checkpoint.

### Validation

Local frontend validation: 55 tests, lint, TypeScript and production build pass;
all JavaScript totals 253.7 KiB gzip against the 350 KiB budget.
Focused tests cover PDF text extraction, exact CSV decimals and formula
protection, secret exclusion/owner predicates, reauthentication, export bounds,
scenario input semantics, compare-and-set confirmation, assistant idempotency
and safe failure, binary downloads after sign-out, notification dismissal and
password preservation. The real PostgreSQL workflow now adds simulation and
selection, reports, inbox lifecycle, assistant refusal/replay/deletion, portable
export and whole-user erasure with foreign-owner checks. A production-build
Chromium workflow covers scenario → assistant → report → notification actions.
The Batch 4 PR records final unit, database, browser and container CI results.

Checkpoints 13.12–13.14 (production delivery, deployment and release audit)
remain pending. Batch 4 does not deploy or declare production readiness.
