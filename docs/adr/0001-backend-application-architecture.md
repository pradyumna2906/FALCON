# ADR 0001: Backend Application Architecture

| Field | Value |
| --- | --- |
| Status | Accepted |
| Decision date | 11 August 2026 |
| Scope | FALCON backend foundation |
| Related phase | Phase 1 — Backend Architecture |
| Supersedes | None |

## Context

FALCON requires a backend foundation that can support authentication, financial profiles, transactions, imports, analytics, forecasting, goal planning, reports and an AI assistant without prematurely introducing microservices.

The project has already established:

- Python 3.13.15 as the backend runtime.
- FastAPI as the backend framework.
- PostgreSQL as the primary database.
- PostgreSQL 18.4 as the local development database.
- A root Docker Compose configuration.
- A four-member pull-request workflow targeting `develop`.
- Strict privacy rules prohibiting committed credentials and real financial data.

Phase 1 must provide a production-shaped foundation while avoiding database schema, authentication and business-feature implementation that belongs to later phases.

## Decision drivers

The architecture must:

- Remain understandable to a four-member student team.
- Support incremental delivery through focused pull requests.
- Keep security and authoritative financial calculations in the backend.
- Separate business rules from HTTP and infrastructure concerns.
- Support asynchronous database access and future long-running financial workflows.
- Be testable without real personal or financial data.
- Allow later extraction of a service only when operational evidence justifies it.
- Avoid empty abstractions and unused modules.

## Decision

### 1. Architecture style

FALCON will begin as a layered modular monolith.

One deployable FastAPI application will contain independently owned business-capability modules. A module may later represent authentication, profiles, transactions, imports, analytics, forecasting, goals or reports.

Each capability will follow these responsibility boundaries:

| Layer | Responsibility |
| --- | --- |
| Interface/API | HTTP routes, dependency wiring, request validation and response mapping |
| Application | Coordinates use cases and transaction boundaries |
| Domain | Financial rules, domain objects and invariants |
| Infrastructure | PostgreSQL repositories and external-service adapters |
| Core | Configuration, logging, errors, middleware and shared runtime utilities |

The dependency direction is inward:

1. The API layer may call application services.
2. Application services may use domain objects and declared infrastructure interfaces.
3. Infrastructure implements persistence or external-service behavior.
4. Domain code must not depend on FastAPI, SQLAlchemy or HTTP.
5. Feature modules must not import another feature's internal repository or database implementation.
6. Cross-feature behavior must use an explicit application-facing interface.
7. Shared code must represent a genuinely shared concept, not merely duplicated convenience code.

Phase 1 will create only the runtime packages it actually needs. Empty future feature modules will not be created.

### 2. Backend repository layout

The Phase 1 backend will use a Python `src` layout:

```text
backend/
├── pyproject.toml
├── Dockerfile
├── .dockerignore
├── README.md
├── src/
│   └── falcon_api/
│       ├── __init__.py
│       ├── main.py
│       ├── api/
│       ├── core/
│       ├── db/
│       ├── middleware/
│       └── schemas/
└── tests/
    ├── unit/
    └── integration/
```

Future capability packages will be added under `falcon_api/modules/<capability>` only when their implementation phase begins.

Feature-specific schemas, services and repositories will remain inside their capability package. The shared `schemas` package is limited to cross-cutting contracts such as health and error responses.

Root `tests/` remains reserved for contract, integration and end-to-end tests spanning multiple FALCON components.

### 3. Runtime and dependencies

- The required development and CI runtime is Python 3.13.15.
- FastAPI will provide the ASGI API framework.
- Pydantic v2 and Pydantic Settings will provide validation and configuration.
- Uvicorn will provide the development ASGI server.
- SQLAlchemy 2-style asynchronous APIs will provide database access.
- Psycopg 3 will provide the PostgreSQL driver.
- Direct dependencies will use reviewed, validated version constraints in `backend/pyproject.toml`.
- Dependency additions and upgrades require focused review and documented compatibility.
- Python 3.14 may remain installed locally but must not run the FALCON backend environment.

### 4. Application construction and lifecycle

The application will expose a `create_app()` factory.

The factory will:

- Accept injectable settings for tests.
- Register middleware and exception handlers.
- Register operational and versioned routers.
- Configure API documentation according to the environment.
- Use FastAPI lifespan management for startup and shutdown resources.

A module-level `app` may be exported for Uvicorn, but application construction must remain factory-based and testable.

A temporary PostgreSQL outage must not prevent the API process from starting. Liveness remains healthy while readiness reports the dependency failure.

### 5. API routing and versioning

Business APIs will be versioned beneath:

```text
/api/v1
```

Versioning begins with the first public business contract rather than waiting for a breaking change.

Operational endpoints remain outside the business prefix:

| Endpoint | Purpose |
| --- | --- |
| `GET /health/live` | Confirms that the API process and event loop are responsive |
| `GET /health/ready` | Confirms that required dependencies, initially PostgreSQL, are available |

Development API documentation may use `/docs`, `/redoc` and `/openapi.json`. Production documentation is disabled by default and can be enabled only through explicit configuration.

No authentication or financial business endpoints are introduced in Phase 1.

### 6. Configuration

Configuration will be represented by an immutable, typed settings object.

Rules:

- Environment variables use the `FALCON_` prefix.
- Supported application environments are `development`, `test` and `production`.
- Local development may read an ignored `.env` file.
- CI and production inject settings through the process environment.
- `.env.example` contains placeholders only.
- Missing or invalid required values fail with a clear startup error.
- Production rejects debug mode and unsafe origin configuration.
- Secrets use secret-aware types and must not appear in logs or exception messages.
- Database URLs are constructed safely from components rather than concatenated or logged.
- Settings are created at the application composition boundary and injected where needed.
- Modules must not repeatedly read arbitrary environment variables.

Authentication-specific configuration may remain documented in `.env.example`, but it will not activate authentication behavior before Phase 3.

### 7. PostgreSQL access

The backend will use SQLAlchemy's asynchronous engine with Psycopg 3.

Rules:

- One engine is managed per application process.
- One asynchronous session is created per request or explicit unit of work.
- Sessions are never stored globally.
- Failed operations roll back before the session is closed.
- The engine is disposed during application shutdown.
- Connection-pool limits and timeouts are configurable.
- Pool pre-ping is enabled where appropriate.
- Database credentials and complete connection URLs are never logged.
- Readiness uses a bounded `SELECT 1` query.
- Readiness failures return a safe service-unavailable response without driver details.
- SQLite will not substitute for PostgreSQL integration tests.

Phase 1 may use the existing local bootstrap development role for connectivity verification. Phase 2 will create the schema, migrations and separate least-privilege application role. Production must never use the bootstrap administrator.

Phase 1 introduces no models, tables, migrations or seed records.

### 8. Health semantics

Liveness:

- Does not query PostgreSQL.
- Returns HTTP `200` while the API runtime is healthy.
- Contains no sensitive configuration or dependency details.

Readiness:

- Checks PostgreSQL with a short timeout.
- Returns HTTP `200` when required dependencies respond.
- Returns HTTP `503` when PostgreSQL is unavailable.
- Does not expose hostnames, credentials, SQL, stack traces or driver errors.

Health responses use typed schemas and stable machine-readable status values.

### 9. Error contract

All API errors will use one safe envelope:

```json
{
  "error": {
    "code": "service_unavailable",
    "message": "The service is temporarily unavailable.",
    "request_id": "0198-example",
    "timestamp": "2026-08-11T12:00:00Z"
  }
}
```

Validated field details may be included when safe and useful.

Rules:

- Error codes are stable and machine-readable.
- Messages are safe for users.
- Timestamps use UTC ISO 8601.
- Validation errors are normalized into the common contract.
- Known application errors map to explicit HTTP statuses.
- Unexpected errors return a generic HTTP `500` message.
- Stack traces and database details are logged internally but never returned.
- Tests verify that sensitive values do not appear in responses.

### 10. Request context and logging

Every request receives a request ID.

- A valid incoming `X-Request-ID` may be retained.
- Missing or malformed values are replaced with a generated identifier.
- The identifier is returned in the `X-Request-ID` response header.
- Logs for the same request include the identifier.
- Request method, normalized path, status and duration may be logged.
- Logs are written to standard output for container collection.
- Production logs use structured fields.

The backend must not log:

- Passwords, tokens, cookies or authorization headers.
- Database credentials or full connection URLs.
- Request or response bodies containing financial information.
- Uploaded statement content.
- Raw personal or financial records.

### 11. CORS and API exposure

- Allowed origins come from explicit environment configuration.
- Credentialed requests never use a wildcard origin.
- Development defaults may allow the configured local frontend.
- Production startup rejects wildcard or malformed origins.
- Allowed methods and headers remain as narrow as the implemented frontend requires.
- Debug mode and interactive documentation are environment-controlled.

Authentication, authorization, rate limiting and account protection are implemented in Phase 3.

### 12. Testing and quality gates

Backend tests will use Pytest.

The test strategy includes:

- Unit tests without external services.
- ASGI/API tests using HTTPX.
- Configuration and startup-validation tests.
- Request-ID, CORS and error-contract tests.
- PostgreSQL integration tests using a real PostgreSQL service.
- Database-available and database-unavailable readiness tests.
- Shutdown and resource-disposal tests.

Quality gates are:

- Ruff formatting verification.
- Ruff linting.
- mypy type checking.
- Pytest with at least 80% backend statement coverage.
- Existing repository pre-commit checks.
- Docker Compose configuration validation.
- A dedicated least-privilege backend GitHub Actions workflow.

Tests use synthetic values and must not require real user credentials or financial records.

### 13. Docker and local development

The existing root `compose.yaml` remains the canonical local-development composition.

Phase 1 will extend it with an API service rather than creating a competing Compose file.

The API image will:

- Use a compatible pinned Python 3.13 base.
- Install only required runtime dependencies in its final stage.
- Run as a non-root user.
- Exclude local environments, secrets, caches and tests from the runtime context where appropriate.
- Expose its service through explicit local-development configuration.

PostgreSQL remains bound to loopback on the configured host port.

### 14. Phase 1 delivery boundaries

Phase 1 includes:

- Architecture documentation.
- FastAPI package and application factory.
- Versioned router foundation.
- Configuration, logging, request context and error handling.
- PostgreSQL engine and session foundation.
- Liveness and readiness endpoints.
- API and PostgreSQL local Docker services.
- Unit and integration tests.
- Ruff, mypy, coverage, pre-commit integration and backend CI.
- Reproducible backend documentation.

Phase 1 excludes:

- Database schema and Alembic migrations.
- User registration, login, tokens and permissions.
- Financial profiles, transactions, goals, loans or budgets.
- CSV, Excel, PDF or UPI imports.
- Classification, analytics, forecasting or optimization.
- Scenario simulation and the AI assistant.
- Frontend implementation.
- Cloud deployment.
- Redis, queues, Kafka, MongoDB or microservices.

## Consequences

### Positive

- The team has one deployable backend and one debugging surface.
- Business rules can remain independent of HTTP and persistence.
- Later features can be added as focused capability modules.
- PostgreSQL behavior is tested against the real database engine.
- Operational behavior is defined before business features depend on it.
- A future service can be extracted along an existing module boundary if evidence justifies it.

### Trade-offs

- Layer boundaries require discipline during reviews.
- Asynchronous database code introduces additional testing and lifecycle concerns.
- A modular monolith does not provide independent feature deployment.
- Shared-process failures remain possible and require good exception isolation.
- Exact dependency and configuration management adds maintenance work.

These trade-offs are acceptable for FALCON's team size, product stage and deployment goals.

## Alternatives considered

### Microservices

Rejected for the initial release because they would add deployment, networking, authentication, observability and data-consistency complexity before FALCON has validated service boundaries or load requirements.

### Flask

Rejected because FastAPI provides first-class type-driven validation, OpenAPI generation, dependency injection and asynchronous ASGI support aligned with FALCON's requirements.

### Synchronous database access

Rejected because the API will perform concurrent database and external-service operations. A single asynchronous pattern avoids maintaining two database-access models.

### SQLite integration tests

Rejected because SQLite cannot validate PostgreSQL types, constraints, SQL behavior, pooling or connection failures accurately.

### Unversioned business APIs

Rejected because authentication, finance and assistant clients will require an explicit compatibility boundary.

## Revisit conditions

This ADR must be superseded rather than silently rewritten if FALCON changes:

- Its backend framework.
- Its primary database.
- Its application layering or module-boundary strategy.
- From a modular monolith to independently deployed services.
- From asynchronous to synchronous database access.
- Its public API versioning policy.
