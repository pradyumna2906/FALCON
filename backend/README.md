# Backend

The FALCON backend is a FastAPI application organized as a layered modular monolith. It is authoritative for validation, financial calculations, persistence, authentication and authorization as those capabilities are introduced in later phases.

Checkpoint 2 provides only the executable HTTP foundation:

- A testable `create_app()` factory and Uvicorn entrypoint.
- Typed, immutable settings using `FALCON_` environment variables.
- An explicit `/api/v1` compatibility boundary.
- A dependency-free `GET /health/live` operational endpoint.
- Automated API, configuration and factory tests.

PostgreSQL access, readiness checks, request middleware, common errors, CORS, Docker API service, business modules and authentication are intentionally deferred to their dedicated checkpoints.

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

## Boundaries

- Do not place business rules in route handlers.
- Add capability modules only when their implementation phase begins.
- Never log or commit secrets, tokens, bank statements or real financial records.
- Do not trust client-calculated financial values.
