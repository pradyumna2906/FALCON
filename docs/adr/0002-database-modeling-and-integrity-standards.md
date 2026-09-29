# ADR 0002: Database Modeling and Integrity Standards

- Status: Accepted
- Date: 2026-08-12
- Decision owners: FALCON development team
- Related issue: #22
- Supersedes: None
- Superseded by: None

## Context

FALCON is an AI-augmented, multi-goal financial advisor that stores private
financial information for multiple users.

The Phase 2.1 domain model defines the conceptual entities, relationships,
ownership boundaries, lifecycle requirements, and stored-versus-derived data
decisions for the MVP.

Before implementing SQLAlchemy models or Alembic migrations, the project needs
consistent database-wide standards. Without those standards, independently
implemented models could disagree about identifiers, monetary precision,
currency, timestamps, ownership, deletion, constraints, and indexing.

Financial data requires stronger correctness guarantees than ordinary content
data. Rounding errors, inconsistent ownership, ambiguous transaction signs, or
silent currency conversion could produce incorrect balances, forecasts, goals,
and recommendations.

This ADR establishes the implementation rules that will govern the initial
PostgreSQL schema and later schema changes.

## Decision drivers

The standards prioritize:

- exact financial calculations
- explicit user-data isolation
- database-enforced structural integrity
- predictable SQLAlchemy behaviour
- reviewable Alembic migrations
- safe collaboration across the development team
- India-first product behaviour
- international-ready currency representation
- understandable API identifiers
- reliable imports and duplicate detection
- complete user-data deletion
- future forecasting and analytics requirements
- maintainability over premature optimization

## Decision

### 1. Database authority

PostgreSQL is the authoritative persistent data store for the FALCON MVP.

SQLAlchemy models describe the schema in Python, but PostgreSQL constraints
remain authoritative for structural integrity.

Application validation improves error messages and user experience. It does
not replace database constraints.

The application must not create production tables dynamically at runtime.
Schema creation and modification occur only through reviewed Alembic
migrations.

### 2. Identifier strategy

Every primary domain table uses an application-generated UUIDv4 primary key.

Identifiers are generated before insertion so application code can establish
relationships without requiring a database round trip solely to obtain an ID.

A standard primary-key column has these conceptual properties:

- UUID value
- non-null
- primary key
- application-generated UUIDv4 default
- immutable after creation

UUIDs may be exposed through APIs. A UUID is an identifier, not an
authorization mechanism.

Every API operation that reads or changes private data must verify ownership
using the authenticated user context.

Sequential integer identifiers are not used as public domain identifiers in
the initial schema.

UUIDv7 may be reconsidered before large production datasets if ordered UUIDs
provide a demonstrated indexing or operational advantage.

### 3. Naming conventions

Database identifiers use lowercase `snake_case`.

The project uses:

- plural table names
- singular column names
- `_id` suffixes for foreign-key columns
- `_at` suffixes for timestamps
- `_date` suffixes for calendar dates
- `_amount` suffixes for monetary amounts
- `_rate` suffixes for fractional rates
- `_hash` suffixes for cryptographic or keyed hashes
- `_count` suffixes for stored counts
- `is_` prefixes only for genuine Boolean states

Names must describe business meaning rather than implementation details.

Abbreviations should be avoided unless they are established domain terms, such
as `id`, `api`, or `iso`.

### 4. Constraint and index names

SQLAlchemy metadata uses a deterministic naming convention for database
objects.

The intended patterns are:

- primary key: `pk_<table>`
- foreign key: `fk_<table>_<column>_<referred_table>`
- unique constraint: `uq_<table>_<column_or_purpose>`
- check constraint: `ck_<table>_<purpose>`
- ordinary index: `ix_<table>_<column_or_purpose>`

Composite constraints use a concise purpose name when listing every column
would make the identifier unclear or exceed PostgreSQL identifier limits.

Every manually defined check constraint and index must have an explicit,
stable name.

Deterministic names make Alembic migrations reproducible and allow constraints
to be changed safely in future migrations.

### 5. Monetary values

Stored monetary values use PostgreSQL `NUMERIC(19,4)`.

Python application code uses `decimal.Decimal`.

Binary floating-point types such as PostgreSQL `REAL`, PostgreSQL
`DOUBLE PRECISION`, and Python `float` must not be used for authoritative
monetary values.

The selected precision supports large personal-finance values while retaining
four fractional digits for allocation and intermediate financial requirements.

Currency-specific display formatting does not change stored precision.

API schemas accept and return monetary values using a representation that
preserves decimal exactness. JSON conversion must not introduce binary
floating-point rounding.

Rounding must be explicit and must use a documented rounding mode at the
business-operation boundary. Intermediate calculations should not be rounded
prematurely.

### 6. Rates and percentages

Rates that require fractional precision use PostgreSQL `NUMERIC(9,6)` and
Python `Decimal`.

A stored rate uses a documented unit. The schema and service must not mix:

- decimal fractions, such as `0.075`; and
- percentage values, such as `7.5`.

The initial implementation standard is to store rates as decimal fractions
unless a specific domain requirement documents another representation.

Named check constraints enforce valid ranges where the domain has a defined
range.

### 7. Currency representation

Currency codes use uppercase ISO 4217 three-letter identifiers.

The physical representation is `CHAR(3)` or an equivalent fixed three-character
SQLAlchemy mapping, with a named check constraint that permits uppercase ASCII
letters.

INR is the configurable default currency for the India-first MVP. INR must not
be hard-coded as the only accepted currency.

Each account stores exactly one fixed currency.

Transactions inherit currency from their account and must not carry an
independently editable currency field.

Each budget and goal stores an explicit fixed currency because it may aggregate
or plan across more than one account.

Amounts in different currencies must never be silently added, compared, or
transferred.

Cross-currency transfers, exchange-rate history, conversion records, and
base-currency analytics are deferred.

### 8. Calendar dates and system timestamps

Financial calendar values use PostgreSQL `DATE`.

Examples include:

- transaction date
- goal target date
- budget start and end dates
- liability start and maturity dates
- opening-balance effective date

System event times use timezone-aware PostgreSQL `TIMESTAMPTZ`.

Examples include:

- creation time
- update time
- archival time
- import start and completion time
- verification and processing events

System timestamps are generated and interpreted as UTC.

The API may convert timestamps to the user's preferred timezone for display.
The stored UTC instant remains authoritative.

A calendar date must not be converted into a timestamp merely to reuse a common
type, because timezone conversion could change its intended financial date.

Naive system datetimes are not permitted.

### 9. Controlled values

Controlled domain values are stored as strings with named check constraints
during the initial schema.

Examples include:

- account type
- transaction type
- transaction status
- import status
- goal status
- goal priority
- category kind
- source type

Python may use string-backed enums for validation and type safety.

PostgreSQL native enum types are not used initially because changing native
enum definitions adds migration complexity and unnecessary coupling at the
current project scale.

Controlled values must:

- use stable lowercase machine values
- remain independent of user-facing labels
- be explicitly validated
- be changed only through reviewed migrations and application updates

Reference tables may replace check-constrained strings when values acquire
their own behaviour, metadata, localization, or administration requirements.

### 10. Transaction sign convention

A transaction amount represents its effect on the account's economic value.

For asset accounts:

- a positive amount increases the asset value
- a negative amount decreases the asset value

For liability accounts:

- a positive amount decreases the debt and improves net worth
- a negative amount increases the debt and reduces net worth

Examples include:

- salary deposited into a bank account: positive
- grocery payment from a bank account: negative
- credit-card purchase increasing debt: negative
- credit-card repayment reducing debt: positive

This convention makes aggregation consistent with net-worth direction.

User interfaces may display liability charges and repayments using familiar
debit, credit, payment, or outstanding-balance language. Presentation labels
must not alter stored sign semantics.

Import adapters are responsible for converting source-specific debit and credit
representations into the authoritative sign convention.

Adjustments must follow the same economic-value rule and must carry an explicit
source or reason.

### 11. Audit fields

Mutable domain entities include:

- `created_at`
- `updated_at`

Both fields use timezone-aware UTC timestamps and are non-null.

`created_at` is set once and does not change.

`updated_at` changes whenever persisted business data changes.

Database and SQLAlchemy behaviour must be tested so timestamps remain correct
for both application-driven and migration-driven operations.

An `archived_at` timestamp is added only to entities with an approved archival
workflow, such as accounts or user-created categories.

The schema does not add universal audit columns that lack a defined use.

Detailed event history, actor tracking, and before-and-after audit logs require
a separate domain and privacy decision.

### 12. Archival and deletion

FALCON does not use a universal `is_deleted` or `deleted_at` soft-deletion
pattern.

Archival and deletion have different meanings:

- archival hides an inactive record while preserving required history
- deletion removes a record according to an approved lifecycle rule
- complete account erasure permanently removes or irreversibly anonymizes
  private user data

Entities that support archival use `archived_at`. A null value means active,
and a non-null value records when the entity was archived.

Normal deletion of historically referenced financial records is restricted or
requires deliberate reconciliation.

Complete user deletion must remove all private dependent records, including
future derived records and retained import artifacts.

Soft deletion must never be used to falsely claim that personal financial data
was erased.

Production backup retention and erasure procedures are deployment and privacy
policies outside this ADR.

### 13. Direct ownership

Private top-level entities store a direct non-null `user_id`.

Examples include:

- accounts
- transactions
- transfer groups
- budgets
- goals
- import jobs
- custom categories

Direct ownership supports:

- explicit isolation
- efficient user-scoped queries
- composite referential integrity
- complete user erasure
- easier security review

A client-provided `user_id` is never trusted as authorization. The service
derives ownership from the authenticated request context.

### 14. Ownership consistency

When a private child references a user-owned parent, the database should enforce
that both records resolve to the same user.

The preferred pattern uses:

- direct `user_id` on the child
- a composite uniqueness candidate on the parent covering `user_id` and `id`
- a composite foreign key from the child covering `user_id` and the parent ID

Examples include:

- transaction to account
- transaction to import job
- transaction to transfer group
- budget limit to budget
- goal contribution to goal
- goal contribution to a supporting transaction

This pattern prevents application bugs from linking records owned by different
users.

Exceptions must be documented.

System categories are a deliberate exception because they have no private
owner and are available to all users. Category ownership requires check
constraints and service validation that distinguish system categories from
custom categories.

The final physical schema must test every ownership path with valid and invalid
cross-user cases.

### 15. Foreign-key deletion actions

Foreign-key actions are selected according to business lifecycle rather than
using one global rule.

The standards are:

- complete user erasure cascades through exclusively private dependent data
- identifying detail records are deleted with their parent
- ordinary deletion of historically referenced records is restricted
- optional classification may be set to null only when doing so preserves
  financial meaning
- archival is preferred when historical transactions must remain
- transfer entries are created, reversed, or removed as one unit
- goal contributions must be reconciled deliberately if a supporting
  transaction is removed
- imported transaction provenance must not disappear accidentally

Every foreign key must specify its intended deletion behaviour explicitly in
the model and migration.

Default database behaviour must not be accepted without review.

### 16. Category integrity

A category is either:

- a system category with no user owner; or
- a custom category with exactly one user owner.

A named check constraint enforces that ownership and system status agree.

System categories cannot be privately edited or deleted.

A custom category is visible only to its owner.

A custom category referenced by a transaction or budget limit is normally
archived or replaced rather than deleted.

Parent and child categories must have compatible scope:

- system categories may have system parents
- custom categories may use an allowed system parent or a custom parent owned
  by the same user
- one user's category must never be parented by another user's custom category

The physical enforcement strategy will be tested during initial schema
implementation.

### 17. Transfer integrity

An internal transfer consists of exactly two transaction entries connected by
one transfer group.

A valid transfer requires:

- exactly one outgoing entry
- exactly one incoming entry
- distinct source and destination accounts
- one common user owner
- accounts owned by that user
- transactions owned by that user
- one common currency
- equal absolute amounts
- opposite signs
- the transfer transaction type on both entries

Both entries and the transfer group are created in one database transaction.

Reversal or deletion operates on both entries atomically.

The service layer validates the complete transfer before persistence.

The PostgreSQL implementation must preserve ownership and referential
constraints even if application validation fails.

Because an exactly-two-row rule spans multiple records, the Phase 2.5 schema
implementation must evaluate and test the most maintainable PostgreSQL-compatible
transactional verification strategy. A deferrable constraint trigger is an
acceptable option if its migration and testing cost is justified.

The database must never expose a committed one-sided transfer as valid.

### 18. Sensitive external references

FALCON stores only the external account or source information required for the
approved feature.

Full bank-account numbers, card numbers, and equivalent secrets must not be
stored merely for display or matching.

User-facing display values are masked.

When equality matching or duplicate detection is required, the system uses a
keyed cryptographic hash rather than a plain unsalted hash of a predictable
identifier.

Hash keys are supplied through protected configuration and are never committed
to the repository.

Logs, errors, fixtures, and test output must not reveal complete sensitive
external identifiers.

Encryption requirements for data that must later be recovered will be defined
with the relevant feature and threat model.

### 19. Import fingerprints

Import duplicate detection uses user-scoped fingerprints.

The design distinguishes:

- a source-file fingerprint for detecting repeated file uploads
- a normalized-record fingerprint for detecting repeated imported records

A record fingerprint should be derived from stable normalized fields selected
by the ETL contract, potentially including:

- user scope
- source identity
- account identity
- transaction date
- exact amount
- normalized description
- external transaction reference, when available

Fingerprints are not treated as globally unique across unrelated users.

The detailed normalization algorithm, retry behaviour, conflict reporting, and
false-positive handling belong to Phase 6.

The initial schema must leave a safe extension path without prematurely storing
raw statement data.

### 20. Indexing standards

Indexes are created from documented query patterns, ownership boundaries, and
constraint requirements.

Private-data indexes generally begin with `user_id` when the query is
user-scoped.

Expected initial index families include:

- user and active-state account lookup
- user transaction date-range lookup
- account transaction date-range lookup
- category and date transaction analysis
- import-job transaction lookup
- transfer-group entry lookup
- active budget period lookup
- active goal deadline and priority lookup
- user-scoped fingerprint lookup

Foreign-key columns are indexed when their query or deletion behaviour requires
it. PostgreSQL does not automatically create indexes for every foreign key.

Indexes must not be added speculatively.

Every index has a documented query purpose because indexes increase storage,
write cost, migration time, and maintenance overhead.

Partial indexes may be used for active or non-archived records when supported
by demonstrated query patterns.

Index effectiveness will be reviewed with realistic PostgreSQL query plans when
data volume becomes sufficient.

### 21. Unique constraints

Uniqueness is scoped to the business boundary.

Examples include:

- normalized email identity
- account name within one user, if the product requires it
- custom category name within one user and category namespace
- one financial profile per user
- one liability-detail record per qualifying account
- one category limit per budget and category
- user-scoped import fingerprints
- composite ownership candidates such as `user_id` and `id`

Application checks may provide friendly conflict messages, but the database
constraint remains authoritative against concurrent requests.

Case-insensitive uniqueness requires an explicit normalization or PostgreSQL
strategy. It must not depend on unspecified collation behaviour.

### 22. Check constraints

Named check constraints enforce row-local invariants where PostgreSQL can
express them clearly.

Candidate constraints include:

- positive goal target amounts
- non-negative starting amounts
- valid budget date ranges
- positive budget limits
- positive goal contributions
- uppercase three-letter currency codes
- valid rate ranges
- compatible category system and owner state
- required archival-state consistency
- allowed controlled string values

Cross-row and aggregate invariants require transactional service behaviour,
database triggers, or another explicitly tested mechanism.

A check constraint is not added if it only restates a type guarantee without
improving domain integrity.

### 23. Migration standards

Alembic is the only supported schema migration mechanism.

Every migration must:

- be committed to version control
- have one clear purpose
- include a descriptive revision message
- use deterministic constraint names
- be reviewed rather than trusting autogeneration blindly
- preserve or deliberately transform existing data
- be tested against PostgreSQL
- support upgrade from the previous repository schema
- provide a downgrade when safe and truthful
- explain an intentionally irreversible downgrade
- avoid embedding environment-specific secrets
- avoid destructive data changes without an explicit migration plan

Model changes and migration changes must be reviewed together.

Autogenerated migrations are a starting point, not an approved result.

The application must not call `metadata.create_all()` as a substitute for
migrations in development, CI, or production.

### 24. SQLAlchemy boundary

SQLAlchemy models must use modern typed declarative mappings.

Shared model infrastructure may provide:

- declarative base
- UUID primary-key behaviour
- timestamp behaviour
- naming-convention metadata
- common typed aliases

Shared infrastructure must not hide important business constraints.

Relationships are conveniences for Python navigation. Foreign keys and database
constraints define persistent integrity.

Session and transaction boundaries belong to the application database layer,
not individual model methods.

Domain models must not open independent sessions or commit implicitly.

### 25. Testing requirements

The database implementation must be tested against PostgreSQL rather than
assuming SQLite is behaviourally equivalent.

Tests must cover:

- UUID generation
- exact decimal round trips
- rate precision
- currency constraints
- timezone-aware timestamps
- financial calendar dates
- controlled-value constraints
- uniqueness boundaries
- check constraints
- foreign-key actions
- same-user ownership enforcement
- rejected cross-user relationships
- category ownership rules
- transfer atomicity and pair integrity
- user-erasure cascades
- restricted ordinary deletion
- archived-record behaviour
- migration upgrade from an empty database
- migration downgrade where supported

Tests should verify database failures as well as successful persistence.

## Consequences

### Positive consequences

- Monetary data remains exact.
- Currency boundaries are explicit.
- Calendar dates cannot shift because of timezone conversion.
- Private relationships gain database-level ownership protection.
- Schema changes remain reviewable and reproducible.
- Constraint names remain stable across developer environments.
- API identifiers do not reveal simple record counts.
- Imports have a defined path toward safe duplicate detection.
- Complete user erasure remains distinct from archival.
- Future forecasting and analytics receive consistent financial semantics.

### Costs and trade-offs

- UUID indexes are larger than integer indexes.
- Composite ownership foreign keys add columns and constraints.
- Four-decimal monetary storage requires explicit display rounding.
- Check-constrained strings require coordinated migrations when values change.
- Exact transfer-pair enforcement may require PostgreSQL-specific logic.
- Database integration tests are slower than purely mocked or SQLite tests.
- Complete deletion and restrictive ordinary deletion require careful lifecycle
  implementation.
- Keyed fingerprints require secure key management.

These costs are accepted because correctness, privacy, and maintainability are
more important than minimizing initial schema complexity.

## Alternatives considered

### Sequential integer primary keys

Rejected for the initial domain schema because they expose predictable
identifiers and would require a separate public-ID standard.

They may remain appropriate for internal immutable reference data if a later
ADR justifies the exception.

### UUIDv7 primary keys

Deferred.

UUIDv7 offers improved time ordering but currently adds compatibility and team
complexity without a demonstrated MVP requirement.

### Floating-point money

Rejected because binary floating-point arithmetic cannot represent many decimal
financial values exactly.

### Storing money as integer minor units

Not selected as the universal standard because currencies have different minor
units and FALCON requires fractional allocations and calculated values.

It may be reconsidered for a narrowly defined external integration if required.

### PostgreSQL native enums

Deferred because they make controlled-value evolution and downgrade migrations
more cumbersome at the current stage.

### Storing currency on every transaction

Rejected for the MVP because transactions already inherit the fixed currency
of their account. Duplicating it would allow contradictory values.

### One transaction row for a transfer

Rejected because one row cannot naturally belong to and affect two separate
accounts while preserving a clear account ledger.

### Universal soft deletion

Rejected because it complicates every query and conflicts with FALCON's promise
of complete user-data deletion.

### Application-only ownership validation

Rejected because an application bug or concurrent operation could create
cross-user relationships despite route-level checks.

### Runtime table creation

Rejected because it bypasses migration history, review, downgrade planning, and
deployment consistency.

### SQLite as the database integration-test substitute

Rejected because SQLite differs from PostgreSQL in types, constraints,
timestamps, transaction behaviour, and migration semantics.

## Implementation sequence

This ADR will be implemented incrementally:

1. Phase 2.3 establishes SQLAlchemy metadata, typed declarative infrastructure,
   session boundaries, and PostgreSQL test utilities.
2. Phase 2.4 establishes Alembic and migration verification.
3. Phase 2.5 implements the approved initial domain schema, relationships,
   constraints, and indexes.
4. Phase 2.6 verifies migrations, PostgreSQL integrity, Compose integration,
   CI, and developer documentation.

Later feature phases may extend the schema through reviewed migrations and,
when necessary, additional ADRs.

## Compliance

A database change complies with this ADR when:

- it preserves exact financial values
- it preserves explicit currency boundaries
- it uses the approved date and timestamp semantics
- it maintains direct user ownership
- it prevents invalid cross-user relationships
- it specifies constraint and deletion behaviour
- it uses reviewed Alembic migrations
- it includes relevant PostgreSQL tests
- it does not introduce silent currency conversion
- it does not weaken complete user-data deletion

Exceptions require an explicit rationale in the pull request and, when
architecturally significant, a superseding or supplementary ADR.
