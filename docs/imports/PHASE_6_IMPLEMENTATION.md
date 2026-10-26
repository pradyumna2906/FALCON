# FALCON Phase 6 Statement Import and ETL Implementation

Phase 6 status: complete.

## 1. Purpose and boundary

Phase 6 converts authenticated user-provided transaction statements into the
Phase 5 ledger through a deterministic extract, validate, normalize, deduplicate,
and load pipeline. Checkpoint 6.1 established the contract before parsers,
persistence workflows, and routes were implemented.

The release supports CSV, modern Excel `.xlsx` workbooks, and digitally generated
`.pdf` bank statements. Legacy `.xls`, scanned-image statements, OCR,
credit-card-specific adapters, Paytm, PhonePe, and Google Pay adapters remain
deferred until a source-specific contract is tested.
Phase 7 owns transaction classification; Phase 6 may preserve an explicit
category supplied by a reviewed source but does not predict one.

## 2. Ownership and authorization

Every import is owned by the trusted user identifier from the authenticated
principal. The request selects one user-owned account that must be active, but
never accepts
`user_id`, job identifiers, fingerprints, lifecycle status, counts, or processing
timestamps. The service verifies account ownership before parsing the statement
structure or normalizing any row. Cross-user accounts and jobs return the same
bounded not-found response as absent resources.

One file import targets one account and inherits that account's currency. Phase 6
does not perform foreign-exchange conversion or permit statement content to
select another account or owner.

## 3. Upload contract

The future authenticated endpoint accepts one multipart file plus the strict
`StatementImportOptions` metadata contract:

| Field | Rule |
|---|---|
| `account_id` | Required UUID of one user-owned active account |
| `source_type` | `csv`, `excel`, or `bank_statement` |
| `date_order` | `day_first` by default; `month_first` or `year_first` allowed |
| `header_row` | One-based row number from 1 through 50 |
| `sheet_name` | Optional Excel worksheet name; forbidden otherwise |
| `file_password` | Optional only for a PDF; ephemeral and never persisted or returned |

Files are limited to 10 MiB and 10,000 data rows. A CSV must be UTF-8 or
UTF-8-with-BOM and use a delimiter selected from comma, semicolon, or tab after
bounded dialect detection. An Excel upload must be an Open Packaging Convention
`.xlsx` workbook. Extension, declared media type, and content signature must
agree. Password-protected, macro-enabled, malformed, and archive-bomb content is
rejected.

Excel is opened in read-only, data-only mode. Formula text is never evaluated or
executed. If a required cell contains only a formula without a cached scalar
value, that row is rejected. The parser never follows links, fetches remote
content, expands embedded objects, or writes the workbook to a public path.

A digital PDF must have a valid PDF signature, contain extractable text, and be
no more than 100 pages. Strict preflight rejects malformed documents, JavaScript,
automatic actions, embedded files, scanned-image-only content, and unsupported
layouts. Password-protected PDFs are decrypted only in request memory using the
optional `file_password`; missing or incorrect passwords receive a generic
error. A versioned adapter converts tables or aligned text into the same inert
canonical row contract used by CSV and Excel. There is no OCR, script execution,
remote fetch, attachment extraction, or raw-file retention.

## 4. Canonical columns and mapping

Header matching is case-insensitive after Unicode normalization, whitespace
collapse, and safe punctuation removal. The first release recognizes reviewed
aliases for these canonical fields:

| Canonical field | Required behavior |
|---|---|
| `transaction_date` | Required date using an unambiguous format or `date_order` |
| `description` | Required non-blank text, normalized to at most 500 characters |
| `amount` | One signed amount column, or the debit/credit pair below |
| `debit` | Optional outflow magnitude; requires the `credit` column |
| `credit` | Optional inflow magnitude; requires the `debit` column |
| `merchant_name` | Optional normalized text at most 200 characters |
| `reference` | Optional stable source identifier used for deduplication |
| `balance` | Optional running balance used for statement-level reconciliation |

An input must provide either one signed `amount` column or a `debit` and `credit`
pair, never both representations. For a pair, exactly one non-zero side is
allowed per row. Debit/outflow becomes a negative ledger amount and
credit/inflow becomes positive. For a signed amount, its sign is retained.
Parentheses indicate a negative amount. Currency symbols and grouping separators
may be removed only through deterministic locale-aware normalization; currency
codes conflicting with the target account are rejected.

## 5. Row validation and normalization

Blank rows are ignored and do not affect accepted or rejected counts. Every
non-blank row is independently validated for a date, one non-zero exact decimal
amount, and a non-blank description. Dates cannot be in the future in the
authenticated user's trusted IANA timezone. Amounts use the ledger's 19-digit,
4-decimal bound and are never parsed through binary floating point.

Normalized rows contain only the target account, signed amount, transaction date,
description, optional merchant/reference, import provenance, and posting status.
Unknown columns are ignored after the required mapping is resolved. Spreadsheet
cells cannot set `id`, `user_id`, `account_id`, `category_id`, `source_type`,
`status`, `import_job_id`, `transfer_group_id`, audit timestamps, or modification
flags.

At most 100 public row issues are returned. Each contains a one-based source row,
a stable reason code, and a generic message. Raw row content, raw values, formulas,
database errors, and internal failure summaries are never echoed in an API
response or ordinary application log.

When every accepted PDF row supplies a running balance, the service verifies the
ledger arithmetic in either chronological or reverse-chronological order. A
definite mismatch rejects the PDF before a job or transaction is created. If a
balance is absent or any row is invalid, the result is unknown rather than a
false pass. Successful PDF jobs persist and return the versioned `adapter_name`
and nullable `balance_reconciled` result, but never the password.

## 6. Duplicate and retry contract

The service streams the upload through SHA-256 and stores the lowercase digest as
the private file fingerprint. The existing per-user uniqueness rule rejects an
identical raw file retry with `409 duplicate_import`; fingerprints are never
returned publicly.

Every accepted row receives a deterministic `external_source_hash`. A stable
source reference is preferred. Otherwise the hash is derived from the normalized
date, signed amount, description, merchant, and deterministic occurrence number
for identical rows. The existing unique index scopes that value to the user and
account. Exact repeats across overlapping files are rejected without removing two
legitimate identical occurrences inside one statement. Fuzzy duplicate detection
is deferred and must never silently discard a transaction.

Database loading is atomic per accepted batch. A retry after any failure either
observes the completed prior result or safely resumes/rejects through the same
fingerprints; it cannot create a second ledger transaction.

## 7. Job lifecycle and reconciliation

An accepted upload first creates a `pending` job. Because raw files are not
retained, the bounded request workflow moves the job to `processing` and then
exactly one terminal state before its database transaction commits:

- `completed`: at least one row accepted and no row rejected;
- `partial`: at least one row accepted and at least one row rejected;
- `failed`: no row accepted because every data row was invalid or the accepted
  batch could not be committed.

Accepted and rejected counts cover non-blank data rows and must reconcile with
the number processed. Start and completion timestamps are server-owned UTC values.
Public job reads expose bounded row issues but not raw file data, fingerprints, or
internal failure details.

The upload endpoint returns the committed reconciliation result and a separate
owner-scoped status route returns it later; no background worker receives raw
statement bytes. The raw file is processed as an ephemeral request resource and
is not retained after the job reaches a terminal state. Durable storage contains
the sanitized filename, fingerprint, mapping/reconciliation metadata, bounded
issue codes, and accepted ledger rows. Future raw-file retention requires a
separate encrypted storage, deletion, access-control, and privacy review.

## 8. Public error contract

| HTTP status | Code | Meaning |
|---|---|---|
| `401` | `invalid_access_token` | Authentication failed |
| `404` | `account_not_found` | Owned active account is absent |
| `404` | `import_job_not_found` | Owned job is absent |
| `409` | `duplicate_import` | The same user's file was already accepted |
| `413` | `import_file_too_large` | Upload exceeds 10 MiB |
| `415` | `unsupported_import_file` | Type, signature, encoding, or workbook is unsupported |
| `422` | `invalid_import_mapping` | Required columns cannot be mapped safely |
| `422` | `invalid_statement_password` | The PDF password is missing or invalid |
| `422` | `unsupported_statement_layout` | No reviewed digital-PDF adapter can map the layout |
| `422` | `statement_balance_mismatch` | Extracted PDF rows do not reconcile to their running balances |
| `422` | `validation_error` | Request metadata is invalid |

Messages remain generic and never reveal cross-user existence, local paths,
parser internals, SQL, formulas, source content, or library exception details.

## 9. Checkpoints

- **Checkpoint 6.1 (complete):** define ownership, supported files, strict API
  schemas, canonical mapping, normalization, deduplication, job lifecycle,
  privacy, errors, and contract tests.
- **Checkpoint 6.2 (complete):** implement bounded secure CSV and `.xlsx`
  extraction.
- **Checkpoint 6.3 (complete):** implement mapping, row normalization, validation,
  deterministic hashes, and duplicate handling.
- **Checkpoint 6.4 (complete):** implement user-scoped job/reconciliation
  persistence and atomic ledger loading.
- **Checkpoint 6.5 (complete):** expose authenticated upload/status routes and run
  PostgreSQL, security, rollback, container, and full regression validation.
- **Checkpoint 6.6 (complete):** add bounded digital-PDF bank-statement
  extraction, encrypted-file support, active-content rejection, versioned
  adapter metadata, and running-balance reconciliation.

## 10. Completion criteria

Phase 6 is complete only when Checkpoints 6.1 through 6.6 are implemented, the
full backend regression remains above the repository coverage threshold, real
PostgreSQL tests prove ownership, retry, reconciliation, and rollback behavior,
and all required PR quality jobs pass.

## 11. Delivered API and validation record

`POST /api/v1/imports` accepts one authenticated multipart CSV, XLSX, or digital
PDF upload,
strictly validates its metadata, reads at most 10 MiB, derives the current date
from the trusted principal timezone, and returns the committed terminal
reconciliation with `201`. `GET /api/v1/imports/{job_id}` returns the same
bounded result only to its owner.

Unit tests cover authentication, server-owned field rejection, metadata bounds,
file-size enforcement, response privacy, timezone propagation, duplicate
handling, lifecycle transitions, and rollback orchestration. The complete unit
suite remains above the repository's 90% coverage gate.

PostgreSQL integration tests exercise real migrations and prove:

- cross-user accounts and jobs remain indistinguishable from absent resources;
- accepted rows retain import provenance and reconcile with their job;
- exact file retries return `409` without adding a second transaction;
- a forced failure after an accepted batch is flushed rolls back every ledger
  row while committing a sanitized terminal `failed` job.

The required PR workflow runs the complete PostgreSQL integration directory,
validates Compose configuration, builds the non-root API image, and performs
live API/PostgreSQL readiness smoke tests before Phase 6 can be merged.

## 12. Digital PDF extension validation

Checkpoint 6.6 keeps one ingestion pipeline rather than creating a separate PDF
ledger path. PDF bytes pass strict preflight, then a named adapter produces the
existing extracted-statement representation. Mapping, exact decimal parsing,
timezone validation, duplicate hashing, atomic loading, ownership checks, and
job reconciliation therefore remain shared across all formats.

Unit coverage includes malformed and encrypted PDFs, invalid passwords,
active-content rejection, page and row limits, repeated headers, table and
position-aware text extraction, adapter dispatch, metadata privacy, and forward
and reverse running-balance checks. PostgreSQL integration submits a real
digitally generated PDF through the authenticated route and verifies its rows,
adapter identity, and reconciliation metadata in durable storage.
