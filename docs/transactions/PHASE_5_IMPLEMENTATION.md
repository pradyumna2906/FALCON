# FALCON Phase 5 Transaction Management Implementation

Phase 5 status: in progress.

## 1. Purpose

Phase 5 establishes the authenticated transaction ledger used by statement
imports, classification, analytics, forecasting, and financial planning.
Transactions record movements against user-owned accounts. They do not store
computed budgets, forecasts, recommendations, or financial-profile answers.

Transaction operations require the Phase 3 authenticated principal. Phase 4's
one profile per user remains a separate planning-context boundary; a profile
is not used as a transaction owner and its absence does not change ledger
ownership.

## 2. Ownership and authorization

Every transaction operation is scoped by the trusted user identifier resolved
from the bearer-authenticated principal. Request bodies, paths, filters, and
cursors never select or override `user_id`.

Before creating or replacing an entry, the application must verify that the
referenced account is one user-owned account belonging to that principal. A
category is valid only when it is an active system category or an active
private category owned by the same user. Cross-user account, category,
transaction, transfer, and cursor access must produce the same public
not-found result as an absent resource.

## 3. Public API plan

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v1/accounts` | Provision an owned account for transaction entry |
| `GET` | `/api/v1/accounts` | List the current user's active accounts |
| `GET` | `/api/v1/categories` | List active system and same-user categories |
| `POST` | `/api/v1/transactions` | Create a manual income or expense |
| `GET` | `/api/v1/transactions` | List the current user's timeline |
| `GET` | `/api/v1/transactions/{transaction_id}` | Get one owned entry |
| `PUT` | `/api/v1/transactions/{transaction_id}` | Replace a mutable entry |
| `DELETE` | `/api/v1/transactions/{transaction_id}` | Delete an eligible manual entry |
| `POST` | `/api/v1/transfers` | Atomically create a paired internal transfer |

Routes are not exposed in Checkpoint 5.1. Later checkpoints implement this
reviewed contract without weakening its ownership rules.

## 4. Manual write contract

A manual create or replacement accepts:

| Field | Rule |
|---|---|
| `account_id` | Required UUID for an active owned account |
| `category_id` | Optional active system or same-user category UUID |
| `transaction_type` | `income` or `expense` only |
| `amount` | Positive magnitude, at most 15 integral and 4 decimal digits |
| `transaction_date` | ISO calendar date |
| `description` | Trimmed, non-blank, at most 500 characters |
| `merchant_name` | Optional trimmed value, at most 200 characters |

The public amount is always a positive magnitude. The application converts an
income to a positive signed ledger amount and an expense to a negative signed
ledger amount. Clients cannot create `transfer` or `adjustment` entries through
the ordinary manual endpoint.

The account determines currency. A transaction request cannot submit or
override currency, and Phase 5 does not perform foreign-exchange conversion.
The service will reject a future date for a posted manual transaction using an
injected application clock rather than a schema-time system clock.

Unknown fields are rejected. In particular, clients cannot select `id`,
`user_id`, `source_type`, `status`, `is_user_modified`, `import_job_id`,
`transfer_group_id`, `external_source_hash`, `created_at`, or `updated_at`.

## 5. Transfer contract

An internal transfer names two different active accounts owned by the same
authenticated user, one positive magnitude, a date, and a description. Both
accounts must use the same currency in Phase 5.

The service creates one transfer group and exactly two linked entries inside
one transaction:

- a negative amount against the source account;
- an equal positive amount against the destination account.

Both entries use `transaction_type=transfer` and `source_type=transfer`.
Neither half may be independently replaced or deleted. Any failure rolls back
the group and both entries.

## 6. Read and response contract

Responses expose the transaction identifier, account and optional category,
type, positive public magnitude, date, description, optional merchant,
provenance, posting status, modification flag, and timestamps.

Responses exclude `user_id`, import-job identifiers, transfer-group internal
keys, and `external_source_hash`. A transfer response exposes one public group
identifier plus its debit and credit entries.

## 7. Timeline, filtering, and pagination

The list operation supports optional filters for account, category,
transaction type, posting status, and an inclusive date range. Every filter is
combined with the authenticated user predicate.

Results use deterministic keyset pagination ordered by `transaction_date DESC,
id DESC`. The default page size is 50 and the maximum is 100. The continuation
cursor is opaque, URL-safe, integrity-protected, and bound to the user and
normalized filter set. A cursor from another user or filter set is invalid.
Offset pagination is not used because concurrent inserts would make it skip or
duplicate timeline entries.

## 8. Replacement and deletion

PUT is a complete replacement of the public mutable fields. The transaction
identifier, owner, provenance, creation timestamp, import linkage, and transfer
linkage remain server-owned.

Manual income and expense entries may be replaced or deleted. Imported entries
may later allow reviewed user corrections while retaining their import
provenance and setting `is_user_modified`; Phase 6 owns that workflow. Transfer
halves and internal adjustments are never mutated through the ordinary entry
endpoints.

## 9. Duplicate and idempotency boundary

Phase 5 does not guess that two manual entries are duplicates from matching
amounts, dates, or descriptions. Repeated manual POST requests therefore create
distinct entries unless a later reviewed idempotency-key contract is added.

Phase 6 calculates a deterministic `external_source_hash` from normalized
source identity and uses the existing per-user, per-account unique database
index. Import retries return the already accepted outcome or report a bounded
duplicate; they never create a second ledger entry. The raw hash and source
row are internal and are never exposed by Phase 5 responses.

## 10. Error contract

The API uses FALCON's unified error envelope.

| HTTP status | Code | Meaning |
|---|---|---|
| `401` | `invalid_access_token` | Bearer authentication failed |
| `404` | `transaction_not_found` | Owned transaction is absent |
| `404` | `account_not_found` | Owned active account is absent |
| `404` | `category_not_found` | Allowed active category is absent |
| `409` | `transaction_conflict` | State changed or violates an immutable boundary |
| `422` | `validation_error` | Public schema or business validation failed |

Database constraint names, SQL, hashes, and cross-user existence are never
included in public errors.

## 11. Checkpoints

- **Checkpoint 5.1 (complete):** define ownership, public schemas, signed-money
  mapping, transfer semantics, filtering, pagination, duplicate boundaries,
  errors, and contract tests.
- **Checkpoint 5.2 (complete):** implement user-scoped transaction persistence.
- **Checkpoint 5.3 (complete):** implement application workflows and business
  invariants.
- **Checkpoint 5.4 (complete):** expose authenticated transaction and transfer
  routes with OpenAPI coverage.
- **Checkpoint 5.4A (complete):** provision user-owned accounts and expose
  active account and category discovery required for usable transaction entry.
- **Checkpoint 5.5 (implemented; CI execution pending):** add PostgreSQL
  lifecycle, concurrency, security, rollback, regression, and completion
  validation.

## 12. Deferred scope

Phase 5 does not implement CSV or Excel parsing, statement imports,
classification models, analytics, forecasting, budgets, goals, currency
conversion, recurring-transaction generation, or fuzzy duplicate detection.
Those capabilities remain in their owning phases.

## 13. Persistence boundary

The transaction repository resolves only active accounts owned by the trusted
user. Category resolution accepts active system categories and active private
categories owned by that same user. Transaction reads and mutations always
include the trusted user identifier; cross-user rows are indistinguishable
from absent rows at the application boundary.

Timeline retrieval applies ownership before every optional filter. It uses the
reviewed descending `(transaction_date, id)` keyset and fetches at most one row
beyond the requested limit to determine whether another page exists. Cursor
decoding and integrity verification remain application-service concerns.

Creation persists complete validated ledger values. Replacement changes only
the reviewed mutable fields and preserves identifier, owner, provenance,
import linkage, transfer linkage, and creation time. Deletion requires an
already owner-validated entity. The application service remains responsible
for deciding whether a manual, imported, transfer, or adjustment entry may be
mutated.

Transfer-group and ledger-entry creation are separate repository primitives so
the application service can create the group, debit, and credit inside one
explicit outer transaction. Repository operations add, delete, and flush but
never commit, roll back, or open independent sessions.

## 14. Application service boundary

The transaction service converts validated public positive magnitudes into
signed ledger values and converts persisted signed values back into positive
public views. It authorizes active accounts and categories before persistence,
rejects future posted dates using the authenticated principal's trusted IANA
timezone, and maps absent or immutable resources into stable public errors.

Manual replacement and deletion lock the owned row and accept only ordinary
manual income or expense entries. Imported entries, transfers, and adjustments
retain immutable provenance through these operations. A successful manual
replacement marks the entry as user modified without changing its source.

Transfer creation locks both owned accounts in canonical UUID order to avoid
opposite-direction lock-order deadlocks, verifies different identities and
equal currencies, creates one transfer group, and persists equal negative and
positive entries through the same caller-owned database transaction.

Timeline cursors contain only a signed keyset payload. Separate HMAC-derived
keys bind each cursor to the user and normalized filter set without exposing a
raw user identifier. Modified, malformed, cross-user, and cross-filter cursors
all map to the same bounded `invalid_transaction_cursor` response.

## 15. Authenticated API boundary

The versioned API exposes manual transaction create, list, get, replace, and
delete operations plus atomic transfer creation. Every route requires the
existing bearer principal and passes only its trusted user identifier and IANA
timezone to the application service. Request bodies and query parameters never
select an owner.

Routes translate strict request and query schemas into application commands
and serialize only public transaction views. OpenAPI documents bearer
security, success responses, validation, not-found, and immutable-provenance
conflicts. Browser preflight permits `DELETE` in addition to the previously
reviewed methods while retaining the explicit trusted-origin allowlist and
`Authorization` header boundary.

## 16. Ledger setup extension

Authenticated users can provision accounts before creating transactions and
can list every active account they own. Account requests never accept an owner,
identifier, archive state, or timestamps. When currency is omitted, the
service uses the authenticated principal's verified default currency; an
explicit three-letter currency is normalized to uppercase. Account names are
unique inside one user's active and archived namespace, and conflicts return
the stable `409 account_name_conflict` contract without exposing a database
constraint.

Category discovery is intentionally read-only in Phase 5. It returns active
system categories plus active private categories owned by the authenticated
user, excluding normalized names, ownership identifiers, archive state, and
timestamps. Category authoring and automated classification remain outside
this extension so Phase 7 retains ownership of classification behavior.

## 17. Completion validation

Checkpoint 5.5 adds real PostgreSQL coverage for the complete authenticated
ledger lifecycle. The suite registers and authenticates two users, provisions
isolated accounts, verifies duplicate-name conflicts, creates and paginates
manual transactions, rejects cross-user reads and stolen cursors, replaces and
deletes eligible entries, creates an atomic transfer, and rejects mutation of
either transfer half.

Separate database scenarios execute opposite-direction transfers concurrently
and require both operations to complete within a bounded timeout. The resulting
two transfer groups must each contain exactly two entries on different
accounts with a zero signed sum. A forced application failure after a flushed
manual entry verifies that the request transaction rolls back without leaving
partial ledger state.

The local environment validates collection, compilation, all unit regressions,
coverage, formatting, and repository hygiene. The repository's existing
`migration-tests` CI job supplies PostgreSQL 18.4, upgrades Alembic to `head`,
and executes every integration test with
`FALCON_RUN_DATABASE_INTEGRATION=1`. Phase 5 becomes complete only when that
required CI job and the remaining backend quality jobs pass on the Phase 5 PR.
