# Phase 8 — Financial Analytics and Spending Intelligence

**Phase status:** in progress
**Current checkpoint:** 8.8 complete after validation
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
- **Checkpoint 8.4 (complete after validation):** explainable recurring
  transaction and subscription intelligence with explicit abstention.
- **Checkpoint 8.5 (complete after validation):** deterministic spending-leak and
  anomaly signals with robust personal baselines and cautious evidence.
- **Checkpoint 8.6 (complete after validation):** budget variance and bounded
  overspend-risk pace arithmetic.
- **Checkpoint 8.7 (complete after validation):** versioned, explainable
  financial-health score with factor-level contributions and abstention.
- **Checkpoint 8.8 (complete after validation):** prioritized insights and
  recommendations.
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

## 18. Checkpoint 8.4 recurring intelligence

Checkpoint 8.4 exposes one authenticated live read operation:

```text
GET /api/v1/analytics/recurring
```

The request accepts the frozen inclusive `date_from`, `date_to`, and `currency`
controls plus three bounded recurrence controls: `minimum_occurrences` from 3
through 12, a response `limit` from 1 through 100, and
`include_abstained`. The defaults are 3, 25, and true. Clients cannot select an
owner, override the trusted timezone, provide transaction IDs, change interval
or amount tolerances, inject a confidence value, or request an unbounded source
history. The normal no-date behavior remains the frozen current-month-to-date
period; a useful monthly recurrence review should normally select a longer
explicit range, up to the existing 366-day maximum.

Only owned, posted income and expense transactions from one account currency
and the selected inclusive period enter recurrence analysis. Pending entries,
transfers, adjustments, foreign-currency rows, and another user's ledger are
excluded in PostgreSQL. The source query reads dates, absolute amounts,
transaction direction, normalized merchant display data, and valid canonical
category metadata. It never reads descriptions, transaction IDs, import
provenance, feature vectors, model paths, or prediction confidence.

Transactions are grouped by exact normalized merchant and direction. When a
merchant is unavailable, a valid canonical classification code is the bounded
fallback. Records with neither signal are ignored because merging them would
create an unexplainable cross-merchant pattern. Category metadata is accepted
only when it is system-owned or belongs to the authenticated user and its kind
matches the transaction direction. Multiple same-merchant entries on one
calendar date are consolidated into one daily amount, so duplicates or split
charges cannot inflate the minimum occurrence count.

Canonical classification codes provide these reviewed behavioral meanings:

| Canonical code | Recurring meaning |
| --- | --- |
| `salary` | Salary |
| `rent` | Rent |
| `emi_loan_payment` | EMI |
| `mutual_fund` | SIP |
| `health_insurance`, `other_insurance` | Insurance |
| `utilities` | Utilities |
| `streaming` | Subscription |

Any sufficiently regular merchant without one of those canonical meanings is
reported only as `repeated_merchant`; merchant text is never used to guess a
regulated or financial meaning. A merchant group adopts a canonical meaning
only when that classification code covers a strict majority of its observed
dates. This avoids labeling a whole pattern as rent, EMI, insurance,
subscription, or investment from one isolated category or a name fragment.

The first policy version recognizes weekly (5–9 days), biweekly (12–16 days),
monthly (25–35 days), and quarterly (80–100 days) cadence bands. It calculates
the exact median interval, the share of intervals inside the selected band, the
exact median/minimum/maximum/total amount, and the share of amounts inside the
reviewed tolerance. The normal amount tolerance is 15%; salary permits 25%,
utilities 50%, and unclassified repeated merchants 20% because those behaviors
have materially different expected variability.

The deterministic evidence score is:

```text
0.65 × interval consistency + 0.35 × amount consistency
```

The score uses exact six-decimal arithmetic and is an evidence ratio, not a
probability or averaged Phase 7 model confidence. A pattern is `detected` only
when it has a recognized cadence and a score of at least `0.700000`; otherwise
the service explicitly `abstained`. Evidence bands are low below 0.70, medium
at or above 0.70, and high at or above 0.90 with at least four observations.
Bounded reason codes and a privacy-safe explanation identify canonical versus
merchant evidence, regular versus irregular timing, and stable versus variable
amounts.

The response includes the normal analytics context and freshness/completeness
metadata, policy version `2026.1`, candidate/detected/abstained/returned counts,
whether the response limit truncated visible patterns, observed detected income
and expense totals, and bounded pattern details. Observed totals cover only the
selected history; they are not a forecast, next-payment prediction, budget,
recommendation, or annualized estimate. Zero data returns `200` with zero
counts, exact zero amounts, and an empty pattern list.

The endpoint uses at most two SQL statements: the existing owner-scoped summary
and one ordered recurrence-evidence query. Detection performs no query per
merchant or transaction. It adds no table, migration, snapshot, cache,
background job, fuzzy match, anomaly detector, duplicate detector, budget,
health score, recommendation, next-due-date prediction, or Phase 9 forecast.

## 19. Checkpoint 8.4 validation

Focused recurrence, repository, schema, service, route, contract, application,
and integration-collection coverage passed 115 tests while skipping the two
explicitly PostgreSQL-gated analytics scenarios. The complete backend
collection passed 1,022 tests and skipped 37 explicitly PostgreSQL-gated tests.
The complete backend unit coverage gate passed at 95.47%, above the required
90% threshold. The recurrence policy reached 97% statement and branch coverage;
the analytics repository and internal result types remained fully covered.

The PostgreSQL-gated authenticated API lifecycle now creates recurring
transactions for two owners, verifies an exact monthly pattern for the first
owner, and proves the second owner's high-value recurring merchant cannot leak
into counts, amounts, or returned patterns. No PostgreSQL service was listening
locally on ports 5432 or 5433, so this real-database scenario remains collected
for the existing PostgreSQL CI job.

Direct module-import order, source compilation, OpenAPI generation, offline
Alembic upgrade and downgrade SQL, whitespace, line-ending, final-newline,
merge-marker, large-file, case-conflict, illegal-Windows-name, submodule, and
private-key checks passed. No migration is required because Checkpoint 8.4 is a
live, read-only policy and API over the existing indexed transaction ledger.

## 20. Checkpoint 8.5 spending-leak and anomaly detection

Checkpoint 8.5 exposes one authenticated live read operation:

```text
GET /api/v1/analytics/spending-signals
```

The request accepts the frozen inclusive `date_from`, `date_to`, and `currency`
controls plus a response `limit` from 1 through 100, defaulting to 25. The
policy thresholds are server-owned and versioned. Clients cannot select a user,
override the trusted timezone, submit descriptions or transaction IDs, change
statistical thresholds, inject model confidence, or request a different signal
formula under policy version `2026.1`.

Only owned, posted expense transactions from one account currency and the
selected period enter the policy. Pending rows, income, transfers, adjustments,
foreign-currency rows, and another user's ledger are excluded in PostgreSQL.
The source statement reads the financial date, absolute amount, normalized
merchant display data, and valid canonical category metadata. It does not read
transaction descriptions, source hashes, import provenance, feature vectors,
model paths, or Phase 7 prediction confidence.

The fixed policy evaluates eight distinct checks:

| Check | Evidence and minimum guard |
| --- | --- |
| Bank-charge leakage | At least two expenses with canonical `bank_charges` evidence |
| Repeated small expenses | At least five same-merchant/category payments no greater than half the user's selected-period median expense |
| Recurring subscriptions | At least three canonical `streaming` observations that pass the reviewed Checkpoint 8.4 recurrence policy |
| Merchant concentration | At least three payments to one merchant, at least five expenses overall, and at least 30% of selected-period expense |
| Category spike | Latest seven-day canonical category total above both 1.5× the median of the three preceding seven-day windows and median plus 3× median absolute deviation |
| Unusual amount | A merchant/category group with at least five observations and an amount above both its 1.5× median guard and median plus 3× median absolute deviation; when deviation is zero the amount must exceed 2× median |
| Discretionary spike | Latest seven-day total across the reviewed discretionary code set above the same three-window robust baseline |
| Duplicate-like expense | At least two same-day rows with the same exact amount and normalized merchant or canonical category key |

The reviewed discretionary set contains restaurants, food delivery, taxi and
ride share, clothing, electronics, general shopping, streaming, movies and
events, gaming, and hobbies. Category evidence is accepted only when it is
system-owned or belongs to the authenticated user and its kind is compatible
with an expense transaction. Merchant text is used only as an exact normalized
grouping key; it never assigns a financial meaning.

Every check returns one explicit evaluation state: `detected`, `no_signal`, or
`insufficient_data`. This prevents an empty response from pretending that all
checks ran successfully. Detected signals are separated into `potential_leak`
and `anomaly` families and include severity, a six-decimal evidence score,
bounded reason codes, observed amount, optional baseline and excess, share of
selected-period expense, occurrence count, observed date bounds, reviewed
merchant/category dimensions, and a privacy-safe explanation.

Evidence score is deterministic policy strength, not a probability, fraud
score, Phase 7 model confidence, or prediction of future behavior. Severity is
an impact band based on the signal's observed share of selected-period expense:
low below 10%, medium from 10% through below 20%, and high at or above 20%.
Signals can overlap, so the response deliberately does not sum their amounts
into “potential savings.” Bank charges and recurring subscriptions may be
legitimate; recurring does not mean unwanted. Duplicate-like evidence is not a
confirmed duplicate, and unusual behavior is not confirmed fraud. Explanations
therefore request review without making a financial, legal, or fraud claim.

Signals are deterministically ordered by severity, observed amount, signal
type, and date before the response limit is applied. Zero data returns `200`,
zero signal counts, all eight evaluations as `insufficient_data`, and an empty
signal list. The endpoint uses at most two SQL statements: the existing
owner-scoped analytics summary and one ordered expense-evidence query. Detection
performs no query per transaction, merchant, category, or signal.

Checkpoint 8.5 adds no database table, migration, write operation, snapshot,
cache, background job, black-box anomaly model, clustering model, fuzzy match,
fraud decision, automatic cancellation, budget, health score, recommendation,
forecast, or UI. Checkpoint 8.6 owns budget variance and bounded overspend risk;
Checkpoint 8.8 owns prioritized recommendations; Phase 9 owns forecasting.

## 21. Checkpoint 8.5 validation

Focused signal-policy, repository, schema, service, route, contract, and
integration-collection coverage passed 131 tests while skipping the two
explicitly PostgreSQL-gated analytics scenarios. The complete backend
collection passed 1,044 tests and skipped 37 explicitly PostgreSQL-gated tests.
The complete backend statement and branch coverage gate passed at 95.38%, above
the required 90% threshold. The new spending-signal policy reached 95%; the
analytics repository and private result types remained fully covered.

The PostgreSQL-gated authenticated API lifecycle now creates same-day exact
duplicate-like expenses for two owners, verifies only the authenticated owner's
bounded signal and amounts, and proves the second owner's much larger matching
expenses cannot leak into counts, evidence, merchant dimensions, or signals. A
local PostgreSQL execution is attempted only when the existing integration flag
and service are available; otherwise the scenario remains collected for the
existing PostgreSQL CI job.

Source compilation, Ruff static checks for the touched Python surface, OpenAPI
generation, offline Alembic upgrade and downgrade SQL, whitespace, line-ending,
final-newline, merge-marker, large-file, case-conflict, illegal-Windows-name,
submodule, and private-key checks passed. No migration is required because
Checkpoint 8.5 is a live, read-only policy and API over the existing indexed
transaction ledger.

## 22. Checkpoint 8.6 budget variance and overspend risk

Checkpoint 8.6 exposes one authenticated read operation:

```text
GET /api/v1/analytics/budgets/{budget_id}
```

The path accepts only a UUID budget identifier. The authenticated principal
supplies the owner and trusted IANA timezone; the stored budget supplies its
fixed currency, full period, overall limit, and canonical category limits.
Clients cannot select another owner, override the timezone or currency, provide
an as-of timestamp, alter thresholds, inject spending, or request a future
calculation date. A missing or cross-owner identifier returns the same
`404 budget_not_found` response and reveals no ownership information.

The endpoint analyzes persisted Phase 2 budgets rather than creating another
budget representation. Historical archived budgets remain readable because
archiving must not rewrite their financial history. A budget that has not
started returns `422 budget_not_started`. The first policy supports stored
periods of at most 366 inclusive days; a longer plan returns
`422 budget_period_unsupported` instead of silently truncating evidence.

The observation window begins on the stored budget start and ends on the
earlier of the trusted local current date and stored budget end. Only owned,
posted expense transactions from accounts in the budget's stored currency enter
overall usage. Pending transactions, income, transfers, adjustments,
foreign-currency rows, and another user's ledger are excluded. Overall spending
does not depend on category coverage. Each category limit receives only posted
expenses whose canonical `transactions.category_id` matches its valid expense
category. Suggested or abstained classifications without a canonical category
remain in overall spending but outside configured category limits.

For an overall or category limit `L`, observed spending `S`, elapsed inclusive
days `e`, and total budget days `d`, policy version `2026.1` calculates:

| Metric | Exact meaning |
| --- | --- |
| Remaining allowance | `L - S`; negative means the stored limit is exceeded |
| Utilization ratio | `S / L` |
| Period progress ratio | `e / d` |
| Daily burn rate | `S / e` using exact decimal arithmetic |
| Expected spend to date | `L × (e / d)` |
| Pace variance | Expected spend to date minus observed spending; negative means spending is ahead of even pace |
| Pace-projected spend | `S / e × d` while active; realized `S` after completion |
| Projected variance | `L - pace-projected spend` |
| Projected overspend amount | `max(0, pace-projected spend - L)` |

Money values serialize at four decimal places and ratios at six. The overall
response also separates spending assigned to configured category limits from
spending outside configured categories. These amounts add exactly to overall
budget usage; no money is omitted merely because classification is incomplete.
If `overall_limit` is absent, overall spending, progress, and daily burn remain
available, while limit-dependent values and overall overspend risk are null or
`unavailable`. Category limits remain independently evaluable.

The deterministic risk and warning policy is:

| Evidence | Risk | Warning |
| --- | --- | --- |
| Current spending exceeds the limit | `high` | `over_limit` |
| Pace projection is at least 110% of the limit | `high` | `projected_overspend` |
| Pace projection exceeds the limit but is below 110% | `medium` | `projected_overspend` |
| Projection is within limit and utilization is at least 80% | `low` | `approaching_limit` |
| Projection and utilization remain below those guards | `low` | `within_budget` |
| No stored overall limit | `unavailable` | `unavailable` |

Risk is a deterministic evidence band, not a probability, credit assessment,
or averaged model confidence. Pace-projected spend is transparent linear
month/period-progress arithmetic, not a Phase 9 forecast, seasonal model, or
claim about future behavior. A completed budget uses realized spending instead
of extrapolation; a completed budget within its limit is `within_budget`, while
a realized excess is `over_limit`. Checkpoint 8.6 exposes warnings but sends no
notification and makes no recommendation.

The endpoint uses at most three SQL statements: one owner-scoped budget and
limit definition query, the existing owner/date/currency summary, and one
set-based category-spending query. It performs no query per category or
transaction. A budget with no spending returns `200` with exact zeros. A budget
with no category limits returns an empty category list and assigns all spending
outside configured categories.

Checkpoint 8.6 adds no table, migration, budget CRUD, write operation, cache,
snapshot, background job, alert delivery, ML model, health score,
recommendation, goal optimization, scenario simulation, forecast, or UI.
Checkpoint 8.7 owns the explainable health score, Checkpoint 8.8 owns prioritized
recommendations, and Phase 9 owns forecasting.

## 23. Checkpoint 8.6 validation

Focused budget policy, repository, schema, service, route, contract, and
integration-collection coverage passed 151 tests while skipping the two
explicitly PostgreSQL-gated analytics scenarios. The complete backend
collection passed 1,064 tests and skipped 37 explicitly PostgreSQL-gated tests.
The complete backend statement and branch coverage gate passed at 95.30%, above
the required 90% threshold. The new budget policy reached 99%; the expanded
analytics repository reached 99% and its private result types remained fully
covered.

The PostgreSQL-gated authenticated lifecycle creates independent budgets,
category limits, accounts, and expenses for two owners. It verifies the first
owner's exact overall usage, configured-category usage, outside-category usage,
category transaction count, pace metrics, and response currency, while proving
the second owner's much larger spending and budget cannot leak. Fetching the
second owner's budget identifier through the first owner's token returns the
same `budget_not_found` response as a missing identifier.

Source compilation, Ruff static checks for the touched Python surface, OpenAPI
generation, offline Alembic upgrade and downgrade SQL, whitespace, line-ending,
final-newline, merge-marker, large-file, case-conflict, illegal-Windows-name,
submodule, and private-key checks passed. No migration is required because
Checkpoint 8.6 derives read-only metrics from the existing budget, category,
account, and transaction schema.

## 24. Checkpoint 8.7 explainable financial health score v1

Checkpoint 8.7 adds the authenticated read-only endpoint:

```text
GET /api/v1/analytics/health-score
```

The query accepts only `date_from`, `date_to`, `currency`, and an optional
owner-scoped `budget_id`. It accepts no user identifier, timezone override,
weight, threshold, factor result, transaction identifier, model confidence,
or score override. Date, future-day, range, currency, posted-status, transfer,
adjustment, correction-precedence, and zero-data behavior reuse analytics
contract `2026.1` exactly.

Financial-health policy `2026.1` uses seven stable factors whose configured
weights total 100:

| Factor | Weight | Versioned evidence and scoring rule |
| --- | ---: | --- |
| Savings rate (25) | 25 | Uses the contract cash-flow savings rate. A non-positive rate scores 0; 10% scores 40, 20% scores 70, and 30% or more scores 100, with linear interpolation between anchors. Zero income makes the factor unavailable. |
| Emergency-fund readiness (20) | 20 | Positive balances in active bank, cash, and wallet accounts are divided by the selected period's monthly-equivalent expense. Readiness is capped at the user's positive emergency target; otherwise the disclosed policy default is three months. Zero observed expense makes the factor unavailable. |
| Debt-service burden (15) | 15 | Stored minimum payments on active loan and credit-card accounts are divided by monthly-equivalent gross income. No debt accounts score 100. If any debt account lacks a minimum payment, the factor abstains rather than understating debt. Burden receives full points through 10%, declines to 80 at 20%, 50 at 30%, and 0 at 50%. |
| Budget adherence (15) | 15 | Available only when the request selects an owned budget aligned to the score currency, start date, and observed end date and the budget has an overall limit. The larger of actual and transparent pace-projected utilization scores 100 through the limit and declines linearly to 0 at 150%. |
| Cash-flow stability (10) | 10 | Requires at least 90 selected days, three complete observed calendar-month buckets, and positive average income. Partial boundary months are excluded. The index combines non-negative monthly cash-flow frequency (60%) and one minus mean-absolute-deviation divided by average income (40%). |
| Spending concentration (5) | 5 | Requires at least five canonically categorized expense transactions. The largest category share scores 100 at 25% or less and declines linearly to 0 at 75% or more. Uncategorized spending remains disclosed through normal completeness metadata. |
| Data completeness (10) | 10 | Combines canonical category coverage (50%), sample adequacy capped at 30 eligible transactions (30%), and financial-profile completion (20%). It is evidence quality, not averaged ML confidence. |

Money, counts, profile fields, budgets, and categories are read only from
trusted owner-scoped sources. Liquid balance is the opening balance plus posted
signed ledger movements through the selected end date for active liquid
accounts in the selected currency. Negative liquid-account balances cannot
inflate emergency readiness. Archived debt or liquid accounts do not enter the
live readiness assessment. Historical score reproducibility is intentionally
deferred to Checkpoint 8.9 snapshots.

Every factor returns its stable identifier, configured weight, availability,
0–100 factor score when available, observed value, benchmark, effective weight,
contribution points, bounded reason codes, and deterministic explanation.
Unavailable factors receive zero effective weight and zero contribution; the
remaining available factors are reweighted to total 100. This prevents missing
budget or liability evidence from being silently interpreted as good or bad.

A composite requires at least 10 eligible transactions and at least 50
available configured weight points. Otherwise `status = unavailable`, the
score is null, and all factor evidence remains visible. A score is `complete`
only when all 100 configured weight points are available; otherwise it is
`partial`. The rounded contribution points add exactly to the public score.

An optional budget must belong to the authenticated user. A missing or
cross-owner identifier returns the uniform `budget_not_found` response. A
budget whose currency, start date, or observed end date does not align with the
score range returns `health_budget_period_mismatch`. A selected aligned budget
without an overall limit leaves only the budget factor unavailable.

The endpoint uses at most five SQL statements: the existing summary, monthly
cash-flow buckets, bounded canonical expense categories, one combined live
profile/liquidity/liability query, and the optional owned-budget definition.
There is no query per transaction, account, category, liability, or factor.

The score is a deterministic planning indicator. It is not a credit score and
not an investment recommendation. It is not a diagnosis of financial solvency,
not a probability, and not a forecast. Checkpoint 8.7 adds no recommendation engine,
alert delivery, lending decision, automated financial action, ML model,
materialized snapshot, background job, table, migration, or Phase 9 behavior.
Checkpoint 8.8 owns prioritized insights and recommendations; Checkpoint 8.9
owns score snapshots, invalidation, performance closure, and monitoring.

## 25. Checkpoint 8.7 validation

Focused analytics policy, repository, schema, application, route, contract,
and integration-collection coverage passed 174 tests while skipping the two
explicitly PostgreSQL-gated analytics scenarios. The complete backend
collection passed 1,087 tests and skipped 37 explicitly PostgreSQL-gated tests.
The complete backend statement and branch coverage gate passed at 95.09%, above
the required 90% threshold. The new financial-health policy reached 96%.

The PostgreSQL-gated authenticated scenario extends the existing two-owner
analytics lifecycle. It verifies a seven-factor partial score, aligned owned
budget evidence, the fixed policy version, and the absence of another user's
transactions and amounts. Supplying the other owner's budget identifier
returns the same `budget_not_found` response as a missing identifier. Local
PostgreSQL was unavailable on ports 5432 and 5433, so the scenario was
collected and skipped locally and remains enabled for the repository's
PostgreSQL CI service.

Source compilation, focused Ruff import/error checks, OpenAPI generation,
offline Alembic upgrade and downgrade SQL, whitespace, line-ending,
final-newline, merge-marker, large-file, case-conflict, illegal-Windows-name,
submodule, and private-key checks passed. No migration is required because
Checkpoint 8.7 derives live read-only evidence from existing profiles,
accounts, liabilities, transactions, categories, and budgets.

## 26. Checkpoint 8.8 prioritized insights and recommendations

Checkpoint 8.8 adds one authenticated read-only operation:

```text
GET /api/v1/analytics/insights
```

The query accepts only `date_from`, `date_to`, `currency`, optional
owner-scoped `budget_id`, and a response `limit` from 1 through 50. The
authenticated principal supplies the owner and trusted timezone. A client
cannot provide a user identifier, policy weights, thresholds, priority score,
confidence, recommendation text, source transactions, or lifecycle override.
The date, currency, posted-status, transfer, adjustment, category-correction,
freshness, and completeness rules remain analytics contract `2026.1`.

Insight policy `2026.1` composes evidence that Checkpoints 8.5–8.7 already
define. It runs the spending-signal and financial-health policies over the same
owner/date/currency selection, then converts only evidence that crosses a fixed
threshold into a bounded action. It does not reinterpret raw transactions with
a second set of hidden financial formulas.

The first policy can produce these stable insight families:

- restore positive cash flow;
- improve savings rate;
- build emergency-fund readiness;
- review debt-service burden;
- protect an aligned selected budget;
- stabilize monthly cash flow;
- improve classification completeness;
- review repeated bank charges, small expenses, subscriptions, merchant
  concentration, category spikes, or discretionary spikes; and
- verify unusual amounts or duplicate-like expenses against the source
  statement.

Each item exposes a deterministic 24-character identifier derived from policy
version, insight type, and bounded merchant/category dimensions. Repeated
candidates with the same identity are deduplicated and the strongest one is
kept. No transaction identifier, raw description, account number, feature
vector, or cross-user dimension enters the identity or public response.

Prioritization is deterministic. A 0–100 priority score combines severity,
urgency, confidence, and fixed policy points:

| Component | Fixed points |
| --- | --- |
| Severity | low 20, medium 40, high 55 |
| Urgency | routine 5, soon 15, immediate 25 |
| Confidence | evidence score multiplied by 20 |

Items are sorted by descending priority and then by stable identifier, so the
same evidence produces the same order. Negative net cash flow is a high,
immediate item and suppresses the redundant low-savings item. Available health
factors create an item only below their documented thresholds; unavailable
factors abstain, and an unavailable composite withholds all health-derived
recommendations. Spending-signal confidence reuses its deterministic evidence
score and is banded as low below 0.50, medium from 0.50, and high from 0.80.
It is not an ML probability.

Every insight returns severity, urgency, confidence, bounded reason codes,
title, evidence explanation, recommended action, and optional estimated period impact.
Monetary impact is labeled either the observed reviewable amount,
robust-baseline excess, or selected-period cash-flow deficit. It is not guaranteed savings,
a prediction, or an instruction to dispute a valid charge.
Actions use fixed reviewed text, ask the user to verify uncertain evidence, and
never name a financial product, security, lender, or investment allocation.

The lifecycle state is `active` because Checkpoint 8.8 is a live read-only
policy. Dismissal, snoozing, delivery, and persisted lifecycle history are not
invented without a storage and product contract. A zero-data selection returns
`insufficient_data`; sufficient evidence that crosses no threshold returns
`no_insights`; otherwise the response is `available`. The summary reports
candidate, active, severity, returned, and truncation counts without summing
overlapping monetary evidence.

An optional budget must be owned and aligned to the selected currency, start
date, and observed end date. Missing or cross-owner identifiers use
`budget_not_found`; misalignment uses `insight_budget_period_mismatch`. The
endpoint uses at most six SQL statements: summary, spending-signal records,
monthly cash-flow buckets, bounded expense categories, combined live
profile/liquidity/liability evidence, and the optional budget definition. It
performs no query per insight, signal, transaction, account, factor, or
category.

These recommendations are personal-finance review prompts. They are not investment advice,
credit or lending decisions, legal or tax advice, automated financial actions,
guaranteed outcomes, or fraud findings. This policy is not a forecast. Phase 9
owns forecasting; Phase 10 owns goal optimization. Checkpoint 8.8 adds no
write endpoint, notification, LLM generation, ML model, table, migration,
snapshot, cache, or background job. Checkpoint 8.9 owns performance,
monitoring, snapshot policy, invalidation, regression closure, and Phase 8 PR
readiness.

## 27. Checkpoint 8.8 validation

Focused analytics policy, schema, application, route, contract, and
integration-collection coverage passed 187 tests while skipping the two
explicitly PostgreSQL-gated analytics scenarios. The complete backend suite
passed 1,100 tests and skipped 37 explicitly PostgreSQL-gated tests. Complete
statement and branch coverage passed at 95.07%, above the required 90% gate;
the new insight policy reached 99% coverage.

The PostgreSQL-gated authenticated scenario extends the existing two-owner
analytics lifecycle. It verifies the policy version, active prioritized items,
stable identifiers, bounded counts, optional owned budget, and absence of the
other owner's much larger transaction and merchant evidence. Supplying the
other owner's budget identifier returns the same `budget_not_found` response
as a missing identifier. Local PostgreSQL was unavailable, so the collected
scenario remains enabled for the repository's PostgreSQL CI service.

Source compilation, focused Ruff error/import checks, OpenAPI generation,
offline Alembic upgrade and downgrade SQL, pre-commit hooks, whitespace,
line-ending, final-newline, merge-marker, large-file, case-conflict,
illegal-Windows-name, submodule, and private-key checks passed. No migration is
required because Checkpoint 8.8 is a live read-only policy over existing
analytics sources.
