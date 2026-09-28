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
Remaining navigation sections explain their pending implementation. Email requests
use the backend delivery queue; production delivery remains a 13.12 gate.

## Validation and contracts

Run `npm run lint`, `npm test`, and `npm run build` (includes TypeScript).
For production-build browser validation, install Chromium with
`npx playwright install --with-deps chromium`, then run `npm run test:browser`.
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
