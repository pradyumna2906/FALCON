# ADR 0005 — Frontend and release integration

Status: Accepted for Phase 13 Batch 1 implementation.

## Context

Phase 12 audit PR #62 merged as `fa579f0`. The frontend was a directory
placeholder; existing APIs cover the financial intelligence workflows but lack
several user-facing setup operations. Phase 13 is not a rewrite of those engines.

## Decision

Use React, TypeScript, Vite, React Router Data Mode, Material UI and TanStack
Query. The SPA has no server rendering requirement. FastAPI remains the sole
authority for authentication, authorization and financial calculations.
Generate TypeScript contracts from the actual OpenAPI document and check drift
in CI. Node follows the repository version declaration; install exact npm pins
and commit a lockfile. Do not introduce a second global server-state store.

Production serves the SPA and `/api` under one HTTPS origin. Development uses a
Vite `/api` proxy. Only public configuration belongs in frontend environment
variables. AI-provider, database, email and encryption secrets stay server-side.
Final hosting/provider selection and paid resources require owner approval.

Access tokens remain in memory. Refresh credentials remain HttpOnly cookies.
Refresh is single-flight, requests retry at most once following a 401, and
logout clears private caches. Never persist financial responses in browser
storage. A session generation counter prevents delayed refreshes from restoring
a logged-out session. Route guards provide UX, never server authorization.

New setup endpoints use authenticated ownership, bounded lists, strict schemas,
atomic writes and indistinguishable foreign/missing responses. Account type,
currency and opening balances cannot be edited by the presentation-update API.
Archive accounts and budgets rather than deleting historical financial records.
Database schema changes are unnecessary if the existing models suffice.

The new setup endpoints require verified email. Existing financial endpoints
currently use the shared authenticated principal without a universal verified
email gate. Aligning those existing capabilities with ADR 0003 is a Batch 2
backend authentication acceptance requirement; frontend guards alone do not
close that gap.

## UX and boundaries

Navigation: Overview; Money (accounts, transactions, imports, budgets);
Analytics; Forecasts; Goals and Plans; Scenarios; Assistant; Reports; Settings.
Batch 1 provides the foundation, not functional screens owned by later batches.
Unavailable features have explanatory placeholders, never invented balances.

Desktop wireframe: left navigation, top identity/status bar, page heading,
filters, primary action, content cards. Mobile: navigation drawer, one-column
content and accessible menu button. Overview eventually has four headline
metrics, cash-flow trend, spending distribution, health factors and goal cards.
Assistant is a later dedicated page and drawer with verified answers and citations.

Design tokens: navy #102A43, blue #1565C0, pale background #F3F7FB, white cards,
teal success, amber warning, red error. Text and icon labels accompany color.
Use semantic landmarks, keyboard operation, visible focus, 44px touch targets,
reduced motion and accessible chart alternatives. Target WCAG 2.2 AA; automated
checks supplement manual keyboard/screen-reader review, not replace it.

Money remains decimal strings across the API boundary; browser charts may
convert values for positioning only, never authoritative arithmetic. Dates,
timezone and currency are explicit. Never aggregate mixed currencies.

## Performance and release gates

Initial foundation JS budget: 350 KiB gzip; route-split later feature bundles.
Use the consolidated analytics endpoint, bounded pagination and deliberate
cache invalidation. Never retry writes automatically after ambiguous failures.
Frontend CI: dependency install, typecheck, lint, tests, production build and
OpenAPI drift. Backend regression retains the existing combined coverage gate.
Final release requires real PostgreSQL E2E, accessibility review, cross-browser
testing, security/dependency review, restore/rollback exercises and load tests.
Staging uses isolated synthetic data and separate secrets from production.

## Deferred release work

Reports/privacy export/erasure/notifications belong to 13.11. Production email,
AI transport, retention scheduler, worker and distributed throttling belong to
13.12. HTTPS, backups, deployment and observability belong to 13.13. Full release
audit is 13.14. No external service provisioning or production changes in Batch 1.
