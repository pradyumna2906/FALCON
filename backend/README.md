# Backend

The FALCON backend is a FastAPI application organized as a layered modular monolith. It is authoritative for validation, financial calculations, persistence, authentication and authorization as those capabilities are introduced in later phases.

The current foundation provides:

- A testable `create_app()` factory and Uvicorn entrypoint.
- Typed, immutable settings using `FALCON_` environment variables.
- An explicit `/api/v1` compatibility boundary.
- A dependency-free `GET /health/live` operational endpoint.
- Safe request correlation through `X-Request-ID`.
- Body-free structured JSON request logs written to standard output.
- One typed error envelope for validation, HTTP, application and unexpected errors.
- Automated API, configuration, request-context and error-contract tests.

PostgreSQL access, readiness checks, CORS, Docker API service, business modules and authentication are intentionally deferred to their dedicated checkpoints.

## Requirements

- Python 3.13.15.
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

```powershell
& .\.venv\Scripts\python.exe -m pytest backend
```

The test command enforces at least 90% statement and branch coverage for the current backend package.

## Run

```powershell
& .\.venv\Scripts\python.exe -m uvicorn falcon_api.main:app `
    --host 127.0.0.1 `
    --port 8000 `
    --reload
```

The initial endpoints are:

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1` | Identifies the public API compatibility boundary |
| `GET` | `/health/live` | Confirms the API process is responsive without querying dependencies |
| `GET` | `/docs` | Development-only Swagger UI |
| `GET` | `/redoc` | Development-only ReDoc UI |
| `GET` | `/openapi.json` | Development-only OpenAPI document |

Production disables all documentation routes unless `FALCON_DOCS_ENABLED=true` is explicitly supplied. Production also rejects `FALCON_DEBUG=true`.

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
