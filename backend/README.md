# Backend

The FALCON backend is a FastAPI application organized as a layered modular monolith. It is authoritative for validation, financial calculations, persistence, authentication and authorization as those capabilities are introduced in later phases.

The current backend provides:

- A testable `create_app()` factory and Uvicorn entrypoint.
- Typed, immutable settings using `FALCON_` environment variables.
- One lazy async SQLAlchemy engine and session factory per application process.
- An explicit `/api/v1` compatibility boundary.
- A dependency-free `GET /health/live` operational endpoint.
- A bounded PostgreSQL-backed `GET /health/ready` readiness endpoint.
- Safe request correlation through `X-Request-ID`.
- An explicit, deny-by-default trusted browser-origin policy.
- Body-free structured JSON request logs written to standard output.
- One typed error envelope for validation, HTTP, application and unexpected errors.
- Automated API, configuration, database, request-context and error-contract tests.
- Reviewed PostgreSQL models and Alembic migrations for the current domains.
- Email/password authentication, session lifecycle, verification and recovery.
- An authenticated, user-isolated financial-profile API.
- Authenticated account provisioning and category discovery.
- User-isolated manual transaction and internal-transfer APIs.
- Authenticated, bounded CSV/XLSX/digital-PDF statement import and reconciliation APIs.
- A versioned Phase 7 transaction-classification taxonomy and strict confidence,
  abstention, provenance, batch-selection, and correction contracts.
- A versioned Phase 8 financial-analytics contract with exact metric, period,
  currency, completeness, confidence, and zero-data semantics, plus
  owner-scoped live PostgreSQL aggregation for summaries, trends, categories,
  merchants, and accounts.

## Requirements

- Python 3.13.15.
- Docker Engine with Docker Compose for the real PostgreSQL integration test.
- A local `.env` copied from `.env.example` and kept out of Git.

Run all commands below from the repository root.

## Install

```powershell
if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
}

py -3.13 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --disable-pip-version-check -e "backend[dev]"
```

## Test

### Unit tests

```powershell
& .\.venv\Scripts\python.exe -m pytest backend\tests\unit
```

The unit command does not require PostgreSQL and enforces at least 90% statement and branch coverage for the current backend package.

### PostgreSQL integration test

Start the digest-pinned PostgreSQL service and explicitly enable the real integration test:

```powershell
docker compose --env-file .env up -d --wait postgres

$env:FALCON_RUN_DATABASE_INTEGRATION = '1'
try {
    & .\.venv\Scripts\python.exe -m pytest `
        backend\tests\integration `
        -m integration `
        --no-cov `
        --tb=short
}
finally {
    Remove-Item Env:\FALCON_RUN_DATABASE_INTEGRATION -ErrorAction SilentlyContinue
}
```

This suite uses the PostgreSQL address and credentials from `.env`. It runs the
production Psycopg async driver, migration lifecycle, public readiness route,
and application lifecycle tests. Tests create isolated records and remove
them when their lifecycle finishes. Run the suite only against a dedicated
development or test database. Stop the service when it is no longer needed
with `docker compose --env-file .env stop postgres`.

## Database migrations

FALCON uses Alembic as the only mechanism for creating or changing persistent
database schema. Application startup, tests and deployment code must never call
`metadata.create_all()`.

Alembic loads the PostgreSQL connection settings from the ignored root `.env`
file. Database credentials are never stored in `backend/alembic.ini`.

Inspect the current database revision:

```powershell
.\.venv\Scripts\python.exe -m alembic `
    -c backend\alembic.ini `
    current
```

Upgrade to the latest reviewed migration:

```powershell
.\.venv\Scripts\python.exe -m alembic `
    -c backend\alembic.ini `
    upgrade head
```

Downgrade one revision:

```powershell
.\.venv\Scripts\python.exe -m alembic `
    -c backend\alembic.ini `
    downgrade -1
```

Generate a candidate migration after changing reviewed SQLAlchemy models:

```powershell
.\.venv\Scripts\python.exe -m alembic `
    -c backend\alembic.ini `
    revision --autogenerate -m "describe schema change"
```

Every generated migration must be inspected before it is committed. Upgrade and
downgrade functions must be explicit and reversible whenever PostgreSQL permits.
Production deployments must run `upgrade head` as a separate controlled step,
not during API process startup.

The initial `25efb498276a` revision is intentionally empty. It establishes the
migration history before Phase 2.5 introduces domain tables.
## Run

```powershell
& .\.venv\Scripts\python.exe -m uvicorn falcon_api.main:app `
    --host 127.0.0.1 `
    --port 8000 `
    --loop falcon_api.core.event_loop:create_psycopg_compatible_event_loop `
    --reload
```

The explicit loop factory selects an asyncio selector loop. Psycopg async connections require this on Windows because they are incompatible with the default proactor loop; the same factory keeps integration tests and local API execution on one verified event-loop contract.

The current endpoints are:

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1` | Identifies the public API compatibility boundary |
| `GET` | `/health/live` | Confirms the API process is responsive without querying dependencies |
| `GET` | `/health/ready` | Confirms PostgreSQL can accept a bounded `SELECT 1` probe |
| `POST` | `/api/v1/auth/register` | Registers a user account |
| `POST` | `/api/v1/auth/login` | Issues an authenticated session |
| `POST` | `/api/v1/auth/refresh` | Rotates a refresh token |
| `POST` | `/api/v1/auth/logout` | Revokes the current refresh session |
| `POST` | `/api/v1/auth/email-verification/request` | Requests email verification |
| `POST` | `/api/v1/auth/email-verification/confirm` | Confirms email verification |
| `POST` | `/api/v1/auth/password-reset/request` | Requests password recovery |
| `POST` | `/api/v1/auth/password-reset/confirm` | Confirms a password reset |
| `GET` | `/api/v1/auth/me` | Returns the bearer-authenticated user |
| `GET` | `/api/v1/profile` | Returns the authenticated user's profile |
| `PUT` | `/api/v1/profile` | Creates or replaces the authenticated user's profile |
| `POST` | `/api/v1/accounts` | Provisions an account for transaction entry |
| `GET` | `/api/v1/accounts` | Lists the authenticated user's active accounts |
| `GET` | `/api/v1/categories` | Lists available system and private categories |
| `POST` | `/api/v1/transactions` | Creates a manual income or expense |
| `GET` | `/api/v1/transactions` | Lists the authenticated user's transactions |
| `GET` | `/api/v1/transactions/{transaction_id}` | Returns one owned transaction |
| `PUT` | `/api/v1/transactions/{transaction_id}` | Replaces an eligible manual transaction |
| `DELETE` | `/api/v1/transactions/{transaction_id}` | Deletes an eligible manual transaction |
| `POST` | `/api/v1/transfers` | Creates an atomic internal transfer |
| `POST` | `/api/v1/imports` | Imports one bounded CSV/XLSX/digital-PDF statement into an owned account |
| `GET` | `/api/v1/imports/{job_id}` | Returns one owned import reconciliation result |
| `GET` | `/docs` | Development-only Swagger UI |
| `GET` | `/redoc` | Development-only ReDoc UI |
| `GET` | `/openapi.json` | Development-only OpenAPI document |

Production disables all documentation routes unless `FALCON_DOCS_ENABLED=true` is explicitly supplied. Production also rejects `FALCON_DEBUG=true`.

## Run with Docker Compose

Build and start the production-shaped API and PostgreSQL services:

```powershell
docker compose --env-file .env up --build --detach --wait api postgres
```

Verify both health contracts from the host:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health/live
Invoke-RestMethod http://127.0.0.1:8000/health/ready
```

Inspect logs and stop the services without deleting PostgreSQL data:

```powershell
docker compose --env-file .env logs --follow api
docker compose --env-file .env down
```

The default API container has no source bind mount and no reload process. It runs as UID/GID `10001`, publishes only to loopback, connects to PostgreSQL at `postgres:5432`, and uses dependency-free liveness for its Docker healthcheck. Readiness remains a separate PostgreSQL-backed contract.
## PostgreSQL lifecycle

FALCON creates one lazy async SQLAlchemy engine and one `async_sessionmaker` when each application process enters its lifespan. Engine creation does not open a database connection, so the API can start and continue serving `/health/live` while PostgreSQL is temporarily unavailable. Shutdown always disposes the engine and its connection pool.

Application code receives one `AsyncSession` per request or explicit unit of work. The session dependency never commits automatically, rolls back failed work and always closes the session. Explicit `transaction_scope()` boundaries own commit and rollback; services and repositories never hide commits.

The initial pool permits five persistent connections plus five overflow connections per API process. Pool checkout, recycling, driver connection and readiness timeouts are configured through the `FALCON_DB_*` settings in `.env.example`. `pool_pre_ping` checks reused connections before application work.

`GET /health/ready` bounds the entire connection-and-query operation and executes only `SELECT 1`. A timeout or database failure returns the common `503 service_unavailable` error envelope without exposing the database host, username, password, SQLAlchemy URL, query parameters or driver message. Database passwords use Pydantic `SecretStr`, and normal SQLAlchemy URL rendering redacts them.

## Browser access

FALCON authorizes browser origins only when they are listed exactly in the JSON-formatted `FALCON_CORS_ALLOWED_ORIGINS` setting:

```dotenv
FALCON_CORS_ALLOWED_ORIGINS=["http://localhost:5173","https://app.example.com"]
```

The setting defaults to an empty list, so browser cross-origin access is denied unless explicitly configured. Each entry must be a unique HTTP(S) origin containing only a scheme, host and optional non-default port. Wildcards, credentials, paths, query strings and fragments are rejected during startup.

The current policy permits `DELETE`, `GET`, `POST`, and `PUT` requests and the `Accept`,
`Authorization`, `Content-Type`, and `X-Request-ID` request headers. It exposes
`X-Request-ID` to trusted browser clients and permits credentialed requests
only for explicitly configured origins. Other methods and headers remain
denied until their owning capability requires and tests them.

An untrusted simple request is still processed by the API but receives no `Access-Control-Allow-Origin` response header, so the browser denies cross-origin access. A rejected preflight receives a CORS `400` response rather than an application authorization response.

## Request correlation and logging

Every HTTP response includes `X-Request-ID`. A client identifier is retained only when it is 1-64 characters, starts with an ASCII letter or digit and otherwise contains only ASCII letters, digits, `.`, `_`, `:` or `-`. Missing or malformed values are replaced with a generated identifier.

Request logs are emitted as one JSON object per line and contain only approved operational fields: request ID, method, normalized path, status, duration and exception type where applicable. Query strings, headers, cookies, request bodies and response bodies are not logged. FALCON disables Uvicorn's default access logger so this middleware remains the only access-log source and duplicate uncorrelated request lines are not emitted.

## Error responses

All framework and application errors use the same response shape:

```json
{
  "error": {
    "code": "not_found",
    "message": "Not Found.",
    "request_id": "0198-example",
    "timestamp": "2026-08-11T12:00:00Z"
  }
}
```

Validation responses may additionally contain bounded field-level `details`. Rejected values, custom HTTP detail, stack traces and exception messages are never returned. Expected failures must raise `ApplicationError` with a stable snake-case code, a deliberately public message and an HTTP error status.

## Boundaries

- Do not place business rules in route handlers.
- Add capability modules only when their implementation phase begins.
- Never log or commit secrets, tokens, bank statements or real financial records.
- Never include private exception or dependency details in an `ApplicationError` message.
- Do not trust client-calculated financial values.


## Persistence and transaction boundaries

FALCON uses one process-owned asynchronous SQLAlchemy engine and one session
factory derived from that engine. The application lifecycle creates and
disposes the engine; feature code must not create separate connection pools.

Every database-backed operation uses one `AsyncSession` inside
`transaction_scope()`:

```python
async with transaction_scope(resources.session_factory) as session:
    await service_operation(session)
```

The boundary provides the following behaviour:

- successful work commits when the transaction context exits
- failed work rolls back before the exception propagates
- the session closes in every case
- objects remain available after commit because `expire_on_commit` is disabled
- autoflush is disabled, so feature code flushes deliberately when required

FastAPI request handlers receive their session through
`get_database_session()`. Routes, services, repositories, and SQLAlchemy models
must not:

- create independent engines or session factories
- open unrelated sessions inside one business operation
- call `commit()` implicitly
- hide transaction boundaries inside model methods
- call `metadata.create_all()` during startup, tests, CI, or production

SQLAlchemy relationships help Python code navigate models. PostgreSQL foreign
keys and constraints remain authoritative for persistent integrity.

The persistence foundation itself introduced no domain tables. Current domain
models were added later through reviewed Alembic migrations; future models
must follow the same migration-only workflow.

### Running persistence tests

Run the unit suite with the project Python environment:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\unit -q
```

The real PostgreSQL integration tests are explicitly enabled:

```powershell
$env:FALCON_RUN_DATABASE_INTEGRATION = '1'

.\.venv\Scripts\python.exe -m pytest `
    backend\tests\integration\test_postgresql_readiness.py `
    -m integration `
    --no-cov `
    -q
```

Clear the temporary environment setting afterward:

```powershell
Remove-Item Env:FALCON_RUN_DATABASE_INTEGRATION
```
## Authentication implementation

Phase 3 provides registration, email verification, login, refresh-token
rotation, replay revocation, logout, password recovery, bearer authentication,
and the authenticated `/api/v1/auth/me` endpoint.

The authoritative implementation and operational contract is documented in
[`docs/authentication/PHASE_3_IMPLEMENTATION.md`](../docs/authentication/PHASE_3_IMPLEMENTATION.md).

Run the complete backend suite from the repository root:

```powershell
.venv\Scripts\python.exe -m pytest -q backend/tests
```

Run the real PostgreSQL authentication and database lifecycles:

```powershell
$env:FALCON_RUN_DATABASE_INTEGRATION = '1'
.venv\Scripts\python.exe -m pytest --no-cov -q backend/tests/integration
Remove-Item Env:FALCON_RUN_DATABASE_INTEGRATION
```

The private root `.env` must remain outside Git.

## Financial profile implementation

Phase 4 provides strict financial-profile validation, server-derived
completion state, user-scoped persistence, concurrent first-update recovery,
and authenticated `GET` and `PUT` operations at `/api/v1/profile`.

The authoritative contract and validation record is documented in
[`docs/financial-profile/PHASE_4_IMPLEMENTATION.md`](../docs/financial-profile/PHASE_4_IMPLEMENTATION.md).

## Transaction management implementation

Phase 5 provides account setup, category discovery, strict signed-ledger
semantics, user-scoped persistence, manual transaction lifecycle operations,
and atomic internal transfers.

The authoritative contract and checkpoint record is documented in
[`docs/transactions/PHASE_5_IMPLEMENTATION.md`](../docs/transactions/PHASE_5_IMPLEMENTATION.md).

## Statement import implementation

Phase 6 provides strict multipart upload metadata, secure bounded CSV/XLSX and
digital-PDF extraction, deterministic normalization and deduplication, atomic
ledger loading, persisted reconciliation issues, and owner-isolated
upload/status operations at `/api/v1/imports`.

Digital PDF statements use `source_type=bank_statement`. They may supply an
ephemeral `file_password`, are limited to 100 pages as well as the shared
10 MiB/10,000-row limits, and reject scanned, active-content, embedded-file, or
unsupported layouts. Successful jobs expose the selected adapter and, when a
complete running-balance column is present, its reconciliation result. PDF
passwords and raw statement bytes are never persisted or returned.

Raw statement bytes are processed only within the request and are not retained.
The authoritative contract and checkpoint record is documented in
[`docs/imports/PHASE_6_IMPLEMENTATION.md`](../docs/imports/PHASE_6_IMPLEMENTATION.md).

## Transaction classification implementation

Phase 7.1 defines taxonomy version `2026.1` and the strict ownership, prediction,
confidence, abstention, provenance, privacy, and user-correction boundaries for
the hybrid rules-and-ML classifier. Phase 7.2 adds the shared feature schema,
reference masking, merchant candidate extraction, payment-channel detection,
amount bands, calendar signals, and recurring-payment indicators. Trained
artifacts, persistence, and routes are introduced only by later checkpoints.
Phase 7.3 adds versioned, exact reviewed merchant knowledge and high-precision
keyword/channel rules with deterministic priority and explicit conflict
abstention. It does not use fuzzy merchant matching or user feedback memory.
Phase 7.4 adds the versioned privacy-bounded dataset workflow, opaque group-aware
train/calibration/test splitting, majority and rules baselines, TF-IDF logistic
regression and calibrated Linear SVM comparison, calibration-driven confidence
thresholds, and publishable evaluation evidence. The reference evidence is
synthetic and explicitly not production-eligible.
Phase 7.5 adds a stable classifier adapter, strict artifact manifest and local
packaging workflow, checksum/size/library compatibility verification, a
thread-safe lazy artifact provider, and rules-first hybrid orchestration.
Provisional synthetic models can suggest but never automatically assign a
category. Phase 7.6 adds stable system taxonomy-category mappings, owner-scoped
classification provenance, atomic automatic category assignment, protected
idempotence, and authenticated single and bounded-batch routes. Phase 7.7 adds
append-only correction snapshots, owner-isolated exact merchant memory,
memory-aware batch inference, and authenticated create/replace/list/delete
personalization operations without automatic global-model retraining. Phase 7.8
closes the phase with static reason-code explanations, aggregate privacy-safe
operational events, a guarded 100-item batch query shape, PostgreSQL index and
lifecycle validation, and full regression requirements. The committed synthetic
model remains provisional and cannot automatically assign model-only results.

The authoritative contract and checkpoint record is documented in
[`docs/classification/PHASE_7_IMPLEMENTATION.md`](../docs/classification/PHASE_7_IMPLEMENTATION.md).

## Financial analytics implementation

Phase 8.1 freezes versioned metric, date-window, currency, transaction-status,
classification-completeness, confidence, freshness, comparison, and zero-data
semantics. Phase 8.2 implements those meanings as exact, owner-scoped live
PostgreSQL aggregations for summary metrics, observed daily/monthly cash flow,
canonical categories, normalized merchants, and historical accounts. Every
surface uses one bounded SQL statement and archived ledger history remains
eligible. No analytics API route, materialized snapshot, anomaly model, budget,
score, recommendation, or forecast has been introduced yet.

The authoritative contract and checkpoint record is documented in
[`docs/analytics/PHASE_8_IMPLEMENTATION.md`](../docs/analytics/PHASE_8_IMPLEMENTATION.md).
