# FALCON Phase 4 Financial Profile Implementation

Phase 4 status: in progress.

## 1. Purpose

Phase 4 establishes the authenticated financial-planning context used by
later transaction analytics, forecasting, goal optimization, and risk-aware
recommendations.

The profile is not an account balance or transaction summary. It stores only
the user's current planning facts that are not naturally represented by the
ledger.

## 2. Public API contract

The financial-profile API will be available at `/api/v1/profile`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/profile` | Return the current user's profile |
| PUT | `/api/v1/profile` | Create or replace the current user's profile |

Both operations require a valid bearer access token. Ownership is always
resolved from the authenticated principal. A request cannot supply or
override a user identifier.

### GET semantics

`GET /api/v1/profile` returns `200 OK` with the current profile. If the
authenticated user has not created a profile, it returns `404 Not Found` with
the public error code `profile_not_found`.

The API does not silently create a profile during a read.

### PUT semantics

`PUT /api/v1/profile` uses create-on-first-update behavior:

- it creates a profile and returns `201 Created` when none exists;
- it replaces the existing profile and returns `200 OK` otherwise.

The operation is an idempotent replacement. All replaceable planning fields
must be present except the optional emergency-fund target. Repeating the same
valid request produces the same planning state and does not create another
profile.

## 3. Request fields

| Field | Required | Rule |
|---|---|---|
| `income_pattern` | Yes | Approved value or `null` while draft |
| `income_stability` | Yes | Approved value or `null` while draft |
| `has_household_responsibilities` | Yes | Boolean |
| `dependant_count` | Yes | Integer from 0 through 50 |
| `emergency_fund_target_months` | No | Decimal from 0 through 60, or `null` |

The emergency-fund target accepts at most two decimal places.

When `has_household_responsibilities` is false, `dependant_count` must be zero.

The request rejects unknown fields. In particular, it rejects `id`, `user_id`,
`completion_status`, `created_at`, and `updated_at` because they are
server-owned values.

## 4. Controlled values

Supported income patterns are:

- `salaried`;
- `self_employed`;
- `irregular`;
- `mixed`.

Supported income-stability assessments are:

- `stable`;
- `variable`;
- `unstable`.

## 5. Completion status

The server derives `completion_status`; clients cannot select it.

A profile is `complete` when both `income_pattern` and `income_stability` are
present and all household-context invariants are valid. Otherwise it is a
valid `draft` profile.

The emergency-fund target is a planning preference and is not required for a
complete profile.

## 6. Response fields

The public response contains:

- the stable profile `id`;
- the five planning fields;
- the derived `completion_status`;
- `created_at` and `updated_at` timestamps.

The response excludes `user_id`, authentication details, account information,
transactions, and derived financial metrics.

## 7. Error contract

The API uses FALCON's unified error envelope.

| HTTP status | Error code | Meaning |
|---|---|---|
| 401 | `invalid_access_token` | The bearer credential is missing or invalid |
| 404 | `profile_not_found` | No profile exists for the authenticated user |
| 422 | `validation_error` | The request violates the schema contract |

Database failures and internal details are never exposed through public error
messages.

## 8. Checkpoints

- **Checkpoint 4.1 (complete):** define the API contract, schemas, validation
  boundaries, completion rules, and contract tests.
- **Checkpoint 4.2 (complete):** implement the user-scoped persistence
  repository.
- **Checkpoint 4.3 (complete):** implement the application service and
  server-derived completion logic.
- **Checkpoint 4.4 (complete):** expose the authenticated GET and PUT
  operations and add OpenAPI and route tests.
- **Checkpoint 4.5:** add real PostgreSQL lifecycle tests, security hardening,
  completion documentation, and full-project validation.

## 9. Deferred scope

Phase 4 does not implement:

- financial accounts, liabilities, budgets, goals, or transactions;
- computed income, spending, net-worth, or risk metrics;
- profile history or forecasting snapshots;
- household sharing;
- partial `PATCH` updates;
- Phase 5 through Phase 7 behavior.

## 10. Persistence boundary

The financial-profile repository provides three operations:

- retrieve a profile by its owning user identifier, with an optional row lock;
- create one user-owned profile;
- replace mutable planning values on an already user-owned profile.

Every read includes `financial_profiles.user_id` in its query. Replacement
also requires the trusted user identifier and rejects a profile belonging to
another user. Repository operations flush pending changes but never commit;
the application transaction boundary retains commit and rollback ownership.

## 11. Application service

The service derives profile completion from validated planning values. Both an
income pattern and an income-stability assessment are required for `complete`;
otherwise the persisted state is `draft`.

Reads translate an absent user-scoped profile into `profile_not_found`.
Replacement first locks an existing profile. Creation runs inside a nested
transaction so a concurrent first update can be handled without invalidating
the outer request transaction. If another request creates the same user's
profile first, the service locks that row and applies the latest complete
replacement. Unrelated integrity failures remain internal failures and are not
translated into public profile errors.

## 12. Authenticated API boundary

The versioned router exposes only GET and PUT at `/api/v1/profile`. Both
operations resolve ownership from the bearer-authenticated principal and pass
that trusted user identifier to the application service. Neither route accepts
a client-selected owner.

The PUT operation returns `201 Created` when the service creates the first
profile and `200 OK` for replacement. Both success paths return the same public
profile representation. OpenAPI documents the two success cases, bearer
security, validation failures, authentication failures, and the GET not-found
contract.

Trusted browser preflight policy permits PUT and the `Authorization` header so
the frontend can call authenticated profile operations. Other new methods are
not enabled.
