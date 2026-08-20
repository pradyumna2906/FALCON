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
- **Checkpoint 5.2 (pending):** implement user-scoped transaction persistence.
- **Checkpoint 5.3 (pending):** implement application workflows and business
  invariants.
- **Checkpoint 5.4 (pending):** expose authenticated transaction and transfer
  routes with OpenAPI coverage.
- **Checkpoint 5.5 (pending):** add PostgreSQL lifecycle, concurrency, security,
  regression, and completion validation.

## 12. Deferred scope

Phase 5 does not implement CSV or Excel parsing, statement imports,
classification models, analytics, forecasting, budgets, goals, currency
conversion, recurring-transaction generation, or fuzzy duplicate detection.
Those capabilities remain in their owning phases.
