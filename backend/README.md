# Backend

The FALCON backend is a FastAPI application organized as a layered modular monolith. It is authoritative for validation, financial calculations, persistence, authentication and authorization as those capabilities are introduced in later phases.

The current foundation provides:

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

Database tables, models, migrations, business modules and authentication remain intentionally deferred to their dedicated checkpoints.

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

This test uses the PostgreSQL address and credentials from `.env`. It runs the production Psycopg async driver and the public readiness route; it does not create tables or modify persisted application data. Stop the service when it is no longer needed with `docker compose --env-file .env stop postgres`.

## Run

```powershell
& .\.venv\Scripts\python.exe -m uvicorn falcon_api.main:app `
    --host 127.0.0.1 `
    --port 8000 `
    --loop falcon_api.core.event_loop:create_psycopg_compatible_event_loop `
    --reload
```

The explicit loop factory selects an asyncio selector loop. Psycopg async connections require this on Windows because they are incompatible with the default proactor loop; the same factory keeps integration tests and local API execution on one verified event-loop contract.

The initial endpoints are:

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1` | Identifies the public API compatibility boundary |
| `GET` | `/health/live` | Confirms the API process is responsive without querying dependencies |
| `GET` | `/health/ready` | Confirms PostgreSQL can accept a bounded `SELECT 1` probe |
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

Application code receives one `AsyncSession` per request or explicit unit of work. The session dependency never commits automatically, rolls back failed work and always closes the session. Service-layer code will own commit boundaries when persistence operations are introduced.

The initial pool permits five persistent connections plus five overflow connections per API process. Pool checkout, recycling, driver connection and readiness timeouts are configured through the `FALCON_DB_*` settings in `.env.example`. `pool_pre_ping` checks reused connections before application work.

`GET /health/ready` bounds the entire connection-and-query operation and executes only `SELECT 1`. A timeout or database failure returns the common `503 service_unavailable` error envelope without exposing the database host, username, password, SQLAlchemy URL, query parameters or driver message. Database passwords use Pydantic `SecretStr`, and normal SQLAlchemy URL rendering redacts them.

## Browser access

FALCON authorizes browser origins only when they are listed exactly in the JSON-formatted `FALCON_CORS_ALLOWED_ORIGINS` setting:

```dotenv
FALCON_CORS_ALLOWED_ORIGINS=["http://localhost:5173","https://app.example.com"]
```

The setting defaults to an empty list, so browser cross-origin access is denied unless explicitly configured. Each entry must be a unique HTTP(S) origin containing only a scheme, host and optional non-default port. Wildcards, credentials, paths, query strings and fragments are rejected during startup.

The current policy permits only `GET` requests and the `Accept`, `Content-Type` and `X-Request-ID` request headers. It exposes `X-Request-ID` to trusted browser clients. Credentialed cross-origin requests, `Authorization` and mutating methods remain disabled until their owning API and authentication checkpoints define them deliberately.

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

No concrete FALCON domain tables are introduced by the persistence foundation.
Domain models will be added only after Alembic migration infrastructure is
established and reviewed.

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
