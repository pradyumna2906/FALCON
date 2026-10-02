# Frontend

This directory contains the React and TypeScript web application.

The frontend is responsible for presentation, accessibility, user interaction and communication with authenticated backend APIs. Authoritative financial calculations and security decisions must remain in the backend.

## Development

Use the Node version in the root `.nvmrc`. From this directory run `npm ci`
then `npm run dev`. Run the backend on `127.0.0.1:8000`; Vite proxies `/api`
to it so browser requests and refresh cookies remain same-origin. Production
must provide the same `/api/v1` reverse proxy and SPA route fallback.
No frontend environment variable may contain a secret.

Batch 1 provides the public preview and guarded navigation shell. Batch 2 adds
registration, sign-in, verification/resend, password recovery/reset, financial
profile onboarding, the live overview and Money screens for accounts, debt
terms, transactions, transfers, imports and merchant/category corrections.
Batch 3 adds Analytics with comparison and account drill-down, budget setup and
risk, forecast generation/history with uncertainty bands and exact tables, and
goal contributions, planning evidence, allocation schedules and plan decisions.
Batch 4 adds scenarios, grounded assistant conversations, PDF/CSV reports,
notifications and account/privacy controls. Batch 5 supplies the TLS production
container and release checks. Email requests use the backend delivery queue;
the new worker delivers them once an owner-configured SMTP service is enabled.
See `deployment/RUNBOOK.md` for activation and remaining live acceptance gates.

## FALCON interface

The public landing page, authentication pages and application shell use a
responsive forest-green, gold and warm-neutral design inspired by the supplied
FALCON Finance reference. The sidebar keeps every existing workspace route;
on mobile it becomes a labelled navigation drawer. The overview adds financial
health, observed cash flow, category spending, goals, a saved forecast preview,
recent transactions and links to reports and the assistant.

Every financial figure comes from the existing authenticated API. Chart numbers
are used only for approximate geometry; the API's exact decimal strings remain
available in labels and tables. Transactions retain their own account currency.
No reference-site balances, advice, portfolios or mock records are included in
the running app. Backend calculations, ownership checks, session refresh,
verification requirements and privacy operations are unchanged.

Sign-in returns verified users to their requested workspace route. Verification
and password-reset links can populate a valid `token` query parameter for manual
submission. Password fields have a keyboard-accessible visibility control.
Loading, empty and error states remain tied to the existing resource/mutation
flows. The redesigned dashboard makes read requests only; existing forms remain
the explicit way to change financial data.

`e2e/redesign.spec.ts` checks mobile/desktop layout, WCAG 2.1 AA automated
accessibility rules, 200% text sizing, password visibility, sign-in return paths,
email-link tokens, API-driven dashboard content, account currencies and invalid
date ranges. Browser fixtures are synthetic; they do not verify SMTP delivery,
live database connectivity or provider activation. Continue using the production
runbook's live acceptance checks before releasing.

## Validation and contracts

Run `npm run lint`, `npm test`, and `npm run build` (includes TypeScript).
For production-build browser validation, install browsers with
`npx playwright install --with-deps chromium firefox webkit`, then run `npm run test:browser`.
Playwright 1.63.0 is an exact development-only pin compatible with the Node 24
baseline. The browser workflow uses synthetic API fixtures; real PostgreSQL
API integration is tested separately in the backend CI job.
After backend contract changes, run `python scripts/export-openapi.py` from
the repository root with `backend[optimization]` installed (the API runtime
requires NumPy/SciPy), then `npm run generate:api`
here. Commit both generated files together. CI checks contract drift.

Access tokens remain in memory; refresh cookies are HttpOnly. Session exit
clears the query cache. Failed server sign-out exposes a retry action even
after the private shell unmounts. Automatic retries are restricted to one
authentication refresh; failed writes are not replayed on server errors.
