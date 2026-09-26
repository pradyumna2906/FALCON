# Frontend

This directory contains the React and TypeScript web application.

The frontend is responsible for presentation, accessibility, user interaction and communication with authenticated backend APIs. Authoritative financial calculations and security decisions must remain in the backend.

## Development

Use the Node version in the root `.nvmrc`. From this directory run `npm ci`
then `npm run dev`. Run the backend on `127.0.0.1:8000`; Vite proxies `/api`
to it so browser requests and refresh cookies remain same-origin. Production
must provide the same `/api/v1` reverse proxy and SPA route fallback.
No frontend environment variable may contain a secret.

Batch 1 provides the public preview and guarded navigation shell. Sign-in,
registration, verification and onboarding screens arrive in Batch 2; the
navigation sections currently explain their pending implementation.

## Validation and contracts

Run `npm run lint`, `npm test`, and `npm run build` (includes TypeScript).
After backend contract changes, run `python scripts/export-openapi.py` from
the repository root with the backend installed, then `npm run generate:api`
here. Commit both generated files together. CI checks contract drift.

Access tokens remain in memory; refresh cookies are HttpOnly. Session exit
clears the query cache. Failed server sign-out exposes a retry action even
after the private shell unmounts. Automatic retries are restricted to one
authentication refresh; failed writes are not replayed on server errors.
