# FALCON Phase 6 Statement Import and ETL Implementation

Phase 6 status: in progress.

## 1. Purpose and boundary

Phase 6 converts authenticated user-provided transaction statements into the
Phase 5 ledger through a deterministic extract, validate, normalize, deduplicate,
and load pipeline. Checkpoint 6.1 defines the contract before parsers,
persistence workflows, or routes are implemented.

The first release supports CSV and modern Excel `.xlsx` workbooks. PDF, legacy
`.xls`, scanned statements, credit-card-specific adapters, Paytm, PhonePe, and
Google Pay adapters remain deferred until a source-specific contract is tested.
Phase 7 owns transaction classification; Phase 6 may preserve an explicit
category supplied by a reviewed source but does not predict one.

## 2. Ownership and authorization

Every import is owned by the trusted user identifier from the authenticated
principal. The request selects one user-owned account that must be active, but
never accepts
`user_id`, job identifiers, fingerprints, lifecycle status, counts, or processing
timestamps. The service verifies account ownership before reading the uploaded
content. Cross-user accounts and jobs return the same bounded not-found response
as absent resources.

One file import targets one account and inherits that account's currency. Phase 6
does not perform foreign-exchange conversion or permit statement content to
select another account or owner.

## 3. Upload contract

The future authenticated endpoint accepts one multipart file plus the strict
`StatementImportOptions` metadata contract:

| Field | Rule |
|---|---|
| `account_id` | Required UUID of one user-owned active account |
| `source_type` | `csv` or `excel` only |
| `date_order` | `day_first` by default; `month_first` or `year_first` allowed |
| `header_row` | One-based row number from 1 through 50 |
| `sheet_name` | Optional Excel worksheet name; forbidden for CSV |

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

An accepted upload creates a `pending` job and returns `202`. Processing moves it
to `processing` and then exactly one terminal state:

- `completed`: at least one row accepted and no row rejected;
- `partial`: at least one row accepted and at least one row rejected;
- `failed`: no row accepted because the file or every data row was invalid.

Accepted and rejected counts cover non-blank data rows and must reconcile with
the number processed. Start and completion timestamps are server-owned UTC values.
Public job reads expose bounded row issues but not raw file data, fingerprints, or
internal failure details.

The raw file is processed as an ephemeral request resource and is not retained
after the job reaches a terminal state. Durable storage contains the sanitized
filename, fingerprint, mapping/reconciliation metadata, bounded issue codes, and
accepted ledger rows. Future raw-file retention requires a separate encrypted
storage, deletion, access-control, and privacy review.

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
- **Checkpoint 6.4 (pending):** implement user-scoped job/reconciliation
  persistence and atomic ledger loading.
- **Checkpoint 6.5 (pending):** expose authenticated upload/status routes and run
  PostgreSQL, security, rollback, container, and full regression validation.

## 10. Completion criteria

Phase 6 is complete only when Checkpoints 6.1 through 6.5 are implemented, the
full backend regression remains above the repository coverage threshold, real
PostgreSQL tests prove ownership, retry, reconciliation, and rollback behavior,
and all required PR quality jobs pass.
