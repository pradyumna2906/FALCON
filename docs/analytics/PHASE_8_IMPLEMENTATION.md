# Phase 8 — Financial Analytics and Spending Intelligence

**Phase status:** in progress
**Current checkpoint:** 8.3 complete
Analytics contract version: `2026.1`

## 1. Purpose

Phase 8 converts the canonical, classified transaction ledger into consistent
financial intelligence. Checkpoint 8.1 freezes meanings before SQL aggregation,
API routes, anomaly detection, budget intelligence, scores, or recommendations
are built. Every later Phase 8 consumer must use this contract instead of
inventing its own financial formulas.

All analytics are scoped by the authenticated principal supplied by the
existing bearer-authentication boundary. A public analytics request can select
a date range, currency, and comparison mode; it cannot select a user, override
the trusted timezone, provide freshness timestamps, or influence confidence.

## 2. Versioning and compatibility

The first analytics contract is `2026.1`. Metric identifiers, formulas,
inclusion rules, response scales, range rules, and completeness thresholds are
part of that version. A future incompatible semantic change requires a new
contract version and an explicit migration plan; silently changing a formula
under an existing identifier is prohibited.

The Phase 7 classification taxonomy has its own version. Analytics returns its
analytics contract version separately so clients never confuse metric meaning
with taxonomy or model provenance.

## 3. Date-window semantics

- `date_from` and `date_to` are inclusive calendar dates.
- Both explicit dates must be supplied together.
- An explicit range must be ordered and cannot exceed 366 days.
- When neither date is supplied, the range is the current calendar month to
  date in the authenticated principal's trusted IANA timezone.
- A date range cannot end after the principal's local current date.
- Stored `transaction_date` values are financial dates and are never shifted by
  timezone conversion.
- The trusted IANA timezone is used only to determine local “today,” default
  period boundaries, and future-date validation.
- System freshness timestamps remain timezone-aware UTC values.

The `previous_period` comparison is the equal-length, non-overlapping range
immediately before the selected range. For example, 10–24 August is compared
with 26 July–9 August. `none` disables comparison. Monthly trend buckets in a
later checkpoint remain calendar months and are distinct from this equal-length
comparison rule.

## 4. Currency semantics

- Every result is calculated for exactly one uppercase three-letter currency.
- A requested currency is used when supplied; otherwise the authenticated
  principal's verified default currency is used.
- Currency belongs to the transaction's owned account because transactions do
  not duplicate currency.
- Accounts and transactions in other currencies are excluded and counted in
  response completeness metadata where applicable.
- Values in different currencies are never added, compared, or ranked together.
- Phase 8 performs no currency conversion and accepts no client-provided
  exchange rate.
- A syntactically valid currency with no matching data produces the documented
  zero-data response instead of a misleading cross-currency total.

## 5. Eligible transaction population

Core income, expense, cash-flow, savings, category, merchant, and account
analytics use transactions that satisfy all of the following:

1. owned by the authenticated principal;
2. account currency equals the resolved result currency;
3. `transaction_date` is inside the inclusive selected period; and
4. `status = posted`.

Pending transactions never enter actual financial metrics. They are reported
only as an exclusion count so a user can understand why totals may differ from
an account's pending display.

Archived accounts remain eligible for historical analytics because archiving
must not rewrite the past. Deleted transactions are absent by design and cannot
be reconstructed by analytics.

## 6. Transaction-type behavior

### Income

Gross income is the sum of positive magnitudes of eligible posted
`transaction_type = income` rows. Category presence and classifier confidence
do not determine whether a row contributes to income.

### Expense

Total expense is the sum of positive magnitudes of eligible posted
`transaction_type = expense` rows. Investment-category outflows remain expense
cash outflows in contract `2026.1`; a future wealth or portfolio metric must be
separate and must not silently redefine total expense.

### Internal transfers

Internal transfers are excluded from gross income, total expense, net cash
flow, savings amount, and savings rate. Transfer volume counts one posted
negative/debit leg per transfer group, preventing the two ledger legs from
double counting the same movement. Transfer entries may be shown separately in
account drill-downs, but user-wide financial performance never treats moving
money between owned accounts as earning or spending money.

### Adjustments

Adjustments are excluded from income, expense, net cash flow, savings, and
behavioral category analytics. Their signed sum is exposed only as the separate
`net_adjustment` reconciliation metric. This prevents balance corrections from
being interpreted as user behavior.

## 7. Metric dictionary

| Metric | Exact formula | Zero-data value |
| --- | --- | --- |
| `gross_income` | Sum of `abs(amount)` for eligible posted income rows | `0.0000` |
| `total_expense` | Sum of `abs(amount)` for eligible posted expense rows | `0.0000` |
| `net_cash_flow` | `gross_income - total_expense` | `0.0000` |
| `savings_amount` | `gross_income - total_expense` | `0.0000` |
| `savings_rate` | `savings_amount / gross_income` when income is positive | `null` |
| `internal_transfer_volume` | Sum of `abs(amount)` for one posted debit leg per transfer group | `0.0000` |
| `net_adjustment` | Signed sum of eligible posted adjustment rows | `0.0000` |
| `classification_coverage` | Categorized eligible income/expense count divided by eligible count | `null` |

Savings amount is deliberately labeled a cash-flow proxy. It may be negative.
It is not account balance, goal funding, net worth, or investment performance.
Savings rate is a ratio, not a percentage: `0.250000` means 25%. It is `null`
when gross income is zero because the denominator is undefined.

Money values use exact decimal arithmetic and serialize to four decimal places.
Rates serialize to six decimal places. Floating-point financial arithmetic is
not permitted.

## 8. Category and correction precedence

Financial totals never depend on category presence, classification confidence,
or model availability. Category, merchant, recurring, leak, and budget
breakdowns use only the canonical `transactions.category_id` after verifying
that the category is available to the authenticated owner and compatible with
the transaction type.

Resolution precedence is:

1. latest immutable user correction reflected by the canonical category;
2. another explicit user-provided canonical category;
3. an automatic Phase 7 assignment reflected by the canonical category;
4. no category allocation.

A suggested classification does not allocate money to a category until a user
accepts or corrects it and the ledger receives a canonical category. An
abstained result also remains unclassified. Suggestions and abstentions are
reported in completeness metadata, not silently included in category totals.
This makes a correction take precedence without mutating historical correction
events or trusting an obsolete prediction.

## 9. Completeness and confidence

Classification coverage is count based:

```text
categorized eligible posted income/expense rows
------------------------------------------------
all eligible posted income/expense rows
```

It is `null` when there are no eligible rows. It is not amount weighted and is
not an ML probability. Phase 7 prediction confidences are never averaged into
an analytics confidence score.

The versioned data-confidence band is deterministic:

- `unavailable`: zero eligible transactions;
- `low`: fewer than 10 eligible transactions or coverage below `0.600000`;
- `medium`: fewer than 30 eligible transactions or coverage below `0.900000`;
- `high`: at least 30 eligible transactions and coverage at least `0.900000`.

Freshness is reported separately and never hidden inside confidence. Every
response identifies the UTC calculation time, the latest included transaction
date, the newest source update timestamp when data exists, and whether the
result is materialized. Checkpoint 8.1 defines live responses, so `materialized`
is false; Checkpoint 8.9 owns any snapshot strategy.

## 10. Zero-data behavior

A valid owner, period, and currency with no eligible transactions returns a
successful response. Money metrics are exact `0.0000`, denominator-dependent
rates are `null`, distributions and time series are empty, eligible and
categorized counts are zero, classification coverage is `null`, and data
confidence is `unavailable`. No-data is not a `404` and must not borrow data
from another currency, period, or user.

## 11. Public schema and error contract

`AnalyticsRangeQuery` accepts only:

- `date_from`
- `date_to`
- `currency`
- `comparison`

The common `AnalyticsContext` response carries:

- analytics contract version;
- resolved currency;
- selected and optional comparison periods;
- freshness metadata;
- completeness and exclusion counts.

Malformed currency, partial ranges, inverted ranges, and ranges longer than
366 days use the existing `422 validation_error` envelope. A range
ending after the trusted local date uses `422 analytics_date_in_future`.
An invalid stored trusted timezone is an internal invariant failure identified
as `invalid_trusted_timezone`; clients cannot provide or override that value.

Public requests and responses exclude user identifiers, raw transaction
descriptions, transaction-ID collections, merchant names, feature vectors,
model paths, and model confidence aggregates. Later drill-down endpoints may
return reviewed display dimensions, but the common analytics context remains
bounded and privacy safe.

## 12. Checkpoint boundaries

- **Checkpoint 8.1 (complete after validation):** versioned metric dictionary,
  date/currency/status/type/category/comparison/freshness/completeness semantics,
  strict schemas, error identifiers, contract tests, and this implementation
  record.
- **Checkpoint 8.2 (complete after validation):** owner-scoped PostgreSQL
  aggregation foundation and query efficiency. It implements this contract
  without changing its meanings.
- **Checkpoint 8.3 (complete after validation):** authenticated dashboard
  cash-flow and spending summary APIs.
- **Checkpoints 8.4–8.8:** recurring intelligence, leak/anomaly detection,
  bounded budget risk, explainable health score, and prioritized insights.
- **Checkpoint 8.9:** snapshot policy, invalidation, monitoring, maximum-range
  performance, full regression, and Phase 8 closure.

Checkpoint 8.1 adds no SQL aggregation, API route, database migration, cache,
snapshot, anomaly model, budget calculation, health score, recommendation,
forecast, or UI. Phase 9 owns time-series forecasting; Phase 8 must not disguise
month-progress arithmetic or a previous-period comparison as a forecast.

## 13. Checkpoint 8.1 validation

The completed contract passed 42 focused analytics tests with 98.77% focused
statement and branch coverage. The complete backend unit suite passed 955 tests
at 95.22% coverage, above the required 90% gate. The complete backend collection
also passed the same 955 tests while skipping 35 explicitly PostgreSQL-gated
tests because no local PostgreSQL service was enabled.

Source compilation, whitespace, line-ending, final-newline, merge-marker,
large-file, and private-key checks passed. No database migration is required
because this checkpoint defines immutable application and API contracts only;
PostgreSQL aggregation and live database validation begin in Checkpoint 8.2.

## 14. Checkpoint 8.2 aggregation foundation

Checkpoint 8.2 implements the contract as a read-only application repository.
Every method receives the authenticated `user_id` from trusted application
context plus a previously resolved `AnalyticsPeriod` and currency. No public
request model contains an owner selector or timezone override.

The repository exposes five bounded read paths:

1. one summary statement for income, expense, transfer volume, adjustments,
   category completeness, exclusions, and freshness watermarks;
2. observed daily or calendar-month income/expense buckets;
3. canonical category allocations;
4. case-normalized merchant allocations, including one unattributed bucket;
5. historical owned-account allocations.

Every read path applies `transactions.user_id = authenticated_user_id`, joins
accounts through both `account_id` and `user_id`, filters the inclusive date
window, and isolates one account currency. Other-owner rows cannot contribute
even if a transaction or account identifier is guessed. Other-currency posted
income/expense rows are counted only in summary exclusion metadata and are
never mixed into money totals.

Summary transfer volume is a grouped scalar subquery: negative posted transfer
legs are grouped by `transfer_group_id`, one magnitude is retained per group,
and those magnitudes are summed. Thus the normal two ledger legs do not double
count a move, and a transfer group contributes at most one aggregate value.
Adjustments use their signed amount and remain separate from external cash
flow.

Category allocation joins only the canonical `transactions.category_id`. A
category counts only when its kind matches the transaction type and it is a
system category or a private category belonging to the same authenticated
owner. Suggested or abstained predictions without a canonical category remain
unallocated. Archived categories and accounts remain available to historical
analytics because archiving does not rewrite already-posted ledger history.

Merchant keys use trimmed lowercase text only for grouping. The foundation
retains a deterministic display variant and a `null` unattributed group but
never reads or returns transaction descriptions. Account and merchant rows
contain separate income and expense amounts. Category rows contain their
single compatible amount and kind.

All database numerics are converted to `Decimal` and quantized to four places.
Daily/monthly, category, merchant, and account outputs have deterministic
ordering. Dimension queries accept only a 1–100 row bound. Each surface uses
exactly one SQL statement, so aggregation never performs a query per
transaction, category, merchant, or account. Empty results remain empty tuples;
the summary statement still returns the contract's exact zero values.

Checkpoint 8.2 adds no API route, response endpoint, materialized view,
database table, migration, cache, background job, anomaly detector, recurring
payment logic, budget, health score, recommendation, or forecast. Checkpoint
8.3 owns authenticated dashboard APIs and presentation schemas; Checkpoint 8.9
owns snapshot policy and maximum-range production performance gates.

## 15. Checkpoint 8.2 validation

The aggregation repository has unit coverage for owner/date/currency/status
predicates, composite account joins, compatible category visibility, exact
money mapping, transfer-group de-duplication, archived-history inclusion,
merchant normalization, daily/monthly grouping, stable limits, and the
one-statement-per-surface query budget. A PostgreSQL-gated integration test
constructs two owners and two currencies, exercises every read path, and
verifies that pending entries, transfers, adjustments, foreign currency, and
the second owner's ledger cannot leak into core totals.

No migration is required: the existing `ix_transactions_user_date`, account,
category, and transfer-group indexes support the bounded read shapes. The live
integration test remains gated by `FALCON_RUN_DATABASE_INTEGRATION=1` and is
executed by the existing PostgreSQL CI service.

Final verification passed 58 focused analytics tests with 100% statement and
branch coverage across `falcon_api.analytics`. The complete backend collection
passed 971 tests and skipped 36 explicitly PostgreSQL-gated tests. The complete
backend coverage gate passed at 95.33%; the final repository changes remained
fully covered by the focused run. Offline Alembic upgrade and downgrade SQL,
source compilation, whitespace, line-ending, final-newline, merge-marker,
large-file, case-conflict, and private-key checks also passed.

No PostgreSQL service was listening locally on ports 5432 or 5433, so the new
real-database scenario could not execute in this workspace. It is collected by
the full test run and will execute in the existing PostgreSQL CI job alongside
the other database-gated tests.

## 16. Checkpoint 8.3 cash-flow and spending APIs

Checkpoint 8.3 exposes two authenticated read operations:

```text
GET /api/v1/analytics/cash-flow
GET /api/v1/analytics/spending
```

Both operations accept the frozen range controls `date_from`, `date_to`,
`currency`, and `comparison`. Cash flow additionally accepts `granularity` as
`day` or `month`, defaulting to calendar month. Spending accepts a dimension
`limit` from 1 through 100, defaulting to 25. Extra query fields are forbidden,
so clients cannot select a user, override the trusted timezone, supply a
freshness timestamp, or inject calculated metrics.

The application service resolves the current month-to-date default from the
authenticated principal's IANA timezone, selects the requested currency or the
principal's trusted default currency, and passes the authenticated `user_id`
directly into every repository call. A `previous_period` comparison fetches
the equal-length immediately preceding summary. `none` performs no comparison
query. Previous-period responses expose the prior exact values rather than an
unstated percentage-change formula.

The cash-flow response contains:

- gross income, total expense, net cash flow, savings amount and savings rate;
- internal-transfer volume and signed net adjustments;
- optional previous-period values for the same metrics;
- observed daily or calendar-month cash-flow buckets;
- common period, currency, freshness, completeness, and exclusion context.

The spending response contains:

- current and optional previous-period total expense;
- canonical expense-category allocations;
- normalized merchant expense allocations;
- historical owned-account expense allocations;
- each dimension's exact amount, expense transaction count, and share of total
  expense; and
- the same common context as cash flow.

Spending queries are filtered to `transaction_type=expense` in PostgreSQL
before ranking and limiting. Income rows therefore cannot consume a dimension
slot, inflate a spending count, or alter an expense share. Category shares may
sum below one when expenses remain unclassified or the requested top-N limit
truncates the category list. Merchant and account shares may also sum below
one after top-N truncation. A share is `null` when total expense is zero.

Money values serialize at four decimal places and ratios at six. Valid
zero-data selections return `200`, exact zero totals, `null` denominator-based
rates, empty series/distributions, and `unavailable` data confidence. Responses
never expose user IDs, transaction IDs, descriptions, raw feature data, model
paths, or model-confidence aggregates. Reviewed merchant/account/category
display dimensions appear only in the spending response.

Cash flow uses at most three SQL statements: current summary, observed series,
and an optional comparison summary. Spending uses at most five: current
summary, three expense dimensions, and an optional comparison summary. Every
statement remains owner/date/currency scoped and no endpoint performs a query
per transaction or returned dimension.

Checkpoint 8.3 adds no table, migration, write operation, materialized view,
cache, background calculation, recurring-payment inference, anomaly detector,
budget, health score, recommendation, forecast, or UI. Those remain assigned
to later approved checkpoints.

## 17. Checkpoint 8.3 validation

Focused service, schema, repository, route, application-wiring, contract, and
integration-collection coverage passed 86 tests while skipping the two
explicitly PostgreSQL-gated analytics scenarios. The complete backend
collection passed 993 tests and skipped 37 explicitly PostgreSQL-gated tests.
The complete backend unit coverage gate passed at 95.42%, above the required
90% threshold; the analytics repository and internal result types remain fully
covered, the application service reached 97%, and the public analytics schemas
reached 99%.

The integration suite now contains both direct repository aggregation and
authenticated API lifecycle scenarios. The API scenario creates two owners,
proves the second owner's large expense cannot affect either response, and
checks exact cash-flow, spending, merchant, account, share, and comparison
serialization. No PostgreSQL service was listening locally on ports 5432 or
5433, so those scenarios remain collected for the existing PostgreSQL CI job.

Offline Alembic upgrade and downgrade SQL, source compilation, OpenAPI
generation, whitespace, line-ending, final-newline, merge-marker, large-file,
case-conflict, illegal-Windows-name, submodule, and private-key checks passed.
No migration is required because Checkpoint 8.3 composes the existing live
aggregation foundation into authenticated read-only responses.
