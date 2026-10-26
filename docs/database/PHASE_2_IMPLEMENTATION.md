# Phase 2 Database Implementation

## Status

Phase 2 implements the reviewed FALCON MVP database foundation, domain schema,
migration lifecycle and PostgreSQL integrity checks.

The implementation follows:

- `docs/database/DOMAIN_MODEL.md`
- `docs/adr/0002-database-modeling-and-integrity-standards.md`

PostgreSQL is authoritative. SQLAlchemy supplies typed application mappings,
and Alembic is the only supported schema-change mechanism.

## Migration chain

| Revision | Purpose |
| --- | --- |
| `25efb498276a` | Establish the empty migration baseline |
| `771fa3a74464` | Create the initial twelve-table domain schema |
| `a1b1833784e5` | Harden cross-table domain integrity |

The application must not call `metadata.create_all()` during development,
testing, CI or production.

## Implemented tables

The initial schema contains:

- `users`
- `financial_profiles`
- `accounts`
- `liability_details`
- `categories`
- `import_jobs`
- `transfer_groups`
- `transactions`
- `budgets`
- `budget_limits`
- `goals`
- `goal_contributions`

Authentication, detailed ETL, forecasting, analytics, scenarios,
recommendations, reports and AI-assistant storage remain deferred to their
own implementation phases.

## Database-enforced standards

The schema enforces:

- application-generated UUIDv4 primary keys
- plural snake-case table names
- deterministic constraint and index names
- `NUMERIC(19,4)` monetary values
- `NUMERIC(9,6)` fractional rates
- uppercase three-letter currency codes
- timezone-aware system timestamps
- calendar-date financial fields
- check-constrained string values
- direct user ownership
- composite same-user foreign keys
- explicit foreign-key deletion actions
- user-scoped uniqueness
- query-driven indexes
- category namespace and hierarchy compatibility
- transaction and budget category eligibility
- liability/account type compatibility
- goal-allocation limits against supporting transactions
- exactly two opposite, same-currency transfer entries on distinct accounts
- complete private-data deletion when a user is erased
- preservation of system categories during user erasure

Cross-row rules use reviewed PostgreSQL trigger functions. Transfer and
allocation checks use deferred constraint triggers so related rows can be
written atomically in one transaction and validated at commit.

## Application responsibilities

Database constraints do not replace application services. Future feature
services remain responsible for:

- deriving ownership from authenticated context
- normalizing emails, category names and imported data before persistence
- preventing inappropriate edits to system categories
- preserving account currency after transaction history exists
- validating complete transfer commands before writing either entry
- reconciling transaction deletion with goal contributions
- validating budget totals and goal dates with product-specific rules
- producing safe, user-facing conflict messages
- never exposing database exception details or private identifiers

## Local verification

Run the complete backend suite:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests -q
