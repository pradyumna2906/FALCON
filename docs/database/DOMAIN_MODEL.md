# FALCON MVP Database Domain Model

## 1. Purpose

This document defines the authoritative conceptual database model for the
FALCON MVP.

FALCON is an AI-augmented, multi-goal financial advisor for individuals with
regular or irregular income. The database must support reliable financial
record keeping, user isolation, planning, future forecasting, and explainable
recommendations.

This document defines what information the MVP needs to store and how that
information relates. It intentionally does not define SQLAlchemy
implementations, PostgreSQL types, Alembic migrations, API contracts, or
authentication behaviour.

Those implementation standards will be decided in later Phase 2 checkpoints.

## 2. Scope

The MVP domain model covers:

- user ownership
- financial profiles
- financial accounts
- liability details
- transaction categories
- transactions
- transfers
- budgets and category limits
- financial goals and contributions
- statement-import traceability

The following capabilities are represented only through future extension
points:

- authentication credentials and sessions
- forecasting runs and projections
- scenario simulations
- recommendations
- generated reports
- machine-learning artifacts
- household and shared-finance support

## 3. Approved architecture decisions

The following decisions are authoritative for the MVP:

1. Accounts use one common identity. Specialized detail records are introduced
   only when an account type requires additional attributes.
2. A transfer is stored as two linked transaction entries: one outgoing entry
   and one incoming entry.
3. Every MVP financial record belongs to one user. Shared household ownership
   is deferred.
4. Each account has one fixed currency. Transactions inherit that currency
   from their account.
5. PostgreSQL is the authoritative data store.
6. Stored facts are separated from values that can be reliably derived.
7. Forecasting, scenarios, recommendations, and reports are deferred until
   their feature requirements are defined.

## 4. Design principles

### 4.1 User isolation

Every private entity must have either:

- a direct user owner; or
- an unambiguous relationship to another entity owned by that user.

An application query must never depend on a client-supplied resource identifier
alone. The active user and ownership relationship must also be checked.

Relationships between records owned by different users are invalid.

### 4.2 Financial correctness

Financial values must use exact decimal arithmetic. Binary floating-point
values are unsuitable for stored monetary amounts.

The final precision, scale, rounding, and PostgreSQL types will be selected in
the database-standards checkpoint.

### 4.3 Currency

Every account has one fixed ISO 4217 currency code.

A transaction inherits its currency from its account. The transaction does not
store an independently editable currency because doing so could create a
currency conflict with the account.

Cross-currency transfers, foreign-exchange rates, and currency conversion
records are outside the MVP.

### 4.4 Time

The model distinguishes between:

- calendar dates, such as a transaction date or goal deadline; and
- system events, such as record creation or import completion.

System timestamps must eventually use timezone-aware UTC storage. User-facing
calendar dates must retain their financial meaning independently of server
timezone.

### 4.5 Stored versus derived information

A value should be stored when it represents an independently supplied fact,
user decision, or historical event.

A value should normally be derived when it can be reproduced reliably from
authoritative stored records.

This reduces conflicting copies of financial information.

### 4.6 Lifecycle traceability

Records requiring traceability include creation and update metadata.

Imported transactions retain a relationship to their import job. Manual edits
must not destroy the ability to identify the transaction's original source.

Detailed audit-event history is deferred until its requirements are defined.

## 5. Conceptual entity catalogue

### 5.1 User

**Purpose**

The user is the ownership root for all private FALCON data.

The entity represents the persistent person identity required by the database.
Authentication credentials and sessions will be added during Phase 3.

**Ownership**

The user owns their own record and all financial records reachable through it.

**Important information**

- stable identifier
- normalized email identity
- account status
- preferred display name
- preferred timezone
- default currency
- creation timestamp
- update timestamp

**Relationships**

- one user may have zero or one financial profile
- one user may own zero or many accounts
- one user may own zero or many custom categories
- one user may own zero or many transactions
- one user may create zero or many budgets
- one user may create zero or many goals
- one user may initiate zero or many import jobs

**Lifecycle**

Deleting a user through the complete-account-deletion workflow must permanently
remove or irreversibly anonymize all personal financial data according to the
approved deletion policy.

Authentication records are outside this checkpoint.

### 5.2 Financial Profile

**Purpose**

Stores the user's current planning context that is not naturally represented
by accounts, transactions, liabilities, or goals.

**Ownership**

Exactly one user owns a financial profile. A user has at most one current
profile in the MVP.

**Important information**

- employment or income pattern
- income stability
- household responsibility information
- number of dependants
- planning preferences
- emergency-fund target preference
- current profile-completion state
- creation timestamp
- update timestamp

**Relationships**

- each profile belongs to exactly one user
- each user has zero or one profile

**Lifecycle**

The profile is deleted with the user. Profile changes update the current
planning context.

Historical profile snapshots are deferred until forecasting and explainability
requirements establish a need for them.

### 5.3 Account

**Purpose**

Represents a financial location, instrument, or obligation against which
transactions are recorded.

**Supported conceptual types**

- bank
- cash
- wallet
- credit card
- investment
- loan

The exact controlled vocabulary will be decided during implementation.

**Ownership**

Every account belongs to exactly one user.

**Important information**

- account identifier
- owner
- user-visible name
- account type
- institution name, when applicable
- masked external reference, when applicable
- fixed ISO 4217 currency code
- opening balance
- opening-balance effective date
- active or archived status
- creation timestamp
- update timestamp

**Relationships**

- one user may own many accounts
- one account may contain many transactions
- a qualifying credit or loan account may have one liability-detail record

**Rules**

- account names may be unique within one user if Phase 2.2 approves that rule
- external account numbers must never be stored unnecessarily in plain text
- an account's currency cannot be changed casually after transactions exist
- archived accounts retain historical transactions
- account type changes must not invalidate existing specialized details

**Derived information**

Current balance is derived from the opening balance and posted transactions. It
is not an independently editable source of truth.

### 5.4 Liability Detail

**Purpose**

Stores terms that apply specifically to debt-bearing accounts without
duplicating the common account identity.

Typical examples include loan and credit-card accounts.

**Ownership**

The liability detail inherits its owner through its account.

**Important information**

- related account
- liability subtype
- principal or approved credit limit, as applicable
- outstanding amount captured as an optional user-supplied baseline
- annual interest rate
- minimum payment or scheduled instalment
- payment due day, when applicable
- start date
- expected end or maturity date
- creation timestamp
- update timestamp

**Relationships**

- each liability-detail record belongs to exactly one account
- each qualifying account has zero or one liability-detail record

**Rules**

- the related account must belong to the same effective user
- the account type must support liability details
- monetary values cannot be negative unless a later requirement explicitly
  permits it
- percentage and date constraints will be finalized during implementation

**Derived information**

Future amortization schedules, interest projections, and payoff simulations are
derived results and are not part of this entity.

### 5.5 Category

**Purpose**

Classifies the financial meaning of a transaction.

FALCON supports both system-defined categories and user-created categories.

**Ownership**

- a system category has no private user owner
- a custom category belongs to exactly one user

A category must never simultaneously behave as both system-owned and
user-owned.

**Important information**

- category identifier
- optional owner
- name
- category kind, such as income, expense, or transfer
- optional parent category
- system-defined indicator
- active status
- display ordering information
- creation timestamp
- update timestamp

**Relationships**

- one user may own many custom categories
- one category may classify many transactions
- one category may contain many child categories
- one category may be referenced by many budget limits

**Rules**

- system categories are visible to all users but cannot be privately modified
- custom categories are visible only to their owner
- category names should be unique within their effective namespace
- parent and child categories must have compatible ownership
- transfer categories are not ordinary spending categories
- an in-use category should normally be archived or replaced rather than
  deleted

### 5.6 Import Job

**Purpose**

Represents one attempt to ingest a user-provided financial file and provides
traceability for transactions produced from it.

The detailed ETL pipeline will be implemented in Phase 6.

**Ownership**

Every import job belongs to exactly one user.

**Important information**

- owner
- source type
- original safe filename
- file fingerprint
- processing status
- processing timestamps
- number of accepted records
- number of rejected records
- sanitized failure summary
- creation timestamp
- update timestamp

**Relationships**

- one user may initiate many import jobs
- one import job may produce many transactions

**Rules**

- uploaded content is private user data
- file fingerprints support duplicate-import detection
- failures must not expose secrets or unsafe raw statement content
- retry behaviour must not create duplicate transactions
- file-retention policy will be defined with the ETL and privacy requirements

### 5.7 Transfer Group

**Purpose**

Connects the two transaction entries representing one internal transfer.

**Ownership**

Every transfer group belongs to exactly one user.

**Important information**

- owner
- creation timestamp

A transfer group does not need to duplicate amount or currency if those facts
are validated through its transaction entries.

**Relationships**

- one user may own many transfer groups
- one transfer group connects exactly two transactions
- each linked transaction belongs to one transfer group

**Rules**

A valid transfer group must contain:

- exactly one outgoing transaction
- exactly one incoming transaction
- two distinct accounts
- accounts owned by the same user
- transactions owned by the transfer-group owner
- equal absolute amounts for the MVP
- accounts using the same currency for the MVP

The database and service-layer division for enforcing the exactly-two-entry
rule will be decided during implementation.

Deleting or reversing a transfer must preserve the integrity of both sides.

### 5.8 Transaction

**Purpose**

Represents one financial movement recorded against one account.

**Conceptual transaction types**

- income
- expense
- transfer
- adjustment

**Ownership**

Every transaction belongs directly to one user and one account owned by that
same user.

Direct ownership is retained even though ownership can also be reached through
the account. This supports explicit isolation and common user-scoped queries.
The database implementation must prevent owner/account inconsistency.

**Important information**

- owner
- account
- optional category
- optional import job
- optional transfer group
- transaction type
- exact signed amount
- transaction date
- normalized description
- optional merchant or counterparty text
- source type
- external source reference or fingerprint, when available
- pending or posted status
- user-modified indicator
- creation timestamp
- update timestamp

**Sign convention**

The authoritative sign convention will be finalized in Phase 2.2. It must be
consistent across balances, analytics, imports, and transfers.

A likely convention is:

- positive values increase the account balance
- negative values decrease the account balance

Account type semantics must be considered carefully for liability accounts.

**Relationships**

- one account contains many transactions
- one category may classify many transactions
- one import job may produce many transactions
- one transfer group connects exactly two transfer transactions
- one transaction may support zero or many goal contributions

**Rules**

- the transaction owner must own its account
- a custom category must belong to the transaction owner
- a system category may be used by any user
- an import job must belong to the transaction owner
- a transfer group must belong to the transaction owner
- ordinary transactions must not reference a transfer group
- transfer transactions must reference a valid transfer group
- transaction currency is inherited from the account
- imported duplicate detection must not depend only on description text

**Derived information**

Monthly spending totals, category totals, account balances, savings rates, and
cash-flow summaries are derived from transactions and related records.

### 5.9 Budget

**Purpose**

Represents a user-defined spending plan for a bounded period.

**Ownership**

Every budget belongs to exactly one user.

**Important information**

- owner
- name
- period start date
- period end date
- optional overall spending limit
- active or archived status
- creation timestamp
- update timestamp

**Relationships**

- one user may create many budgets
- one budget contains one or many budget limits

**Rules**

- the period end date must not precede the start date
- overlapping budgets may be allowed because users can create different plans,
  but duplicate active budget definitions should be controlled
- monetary limits use the user's supported planning currency
- category-level limits must not exceed an overall limit without an explicit
  product decision

**Derived information**

Actual spending, remaining budget, utilization percentage, projected overspend,
and warning status are derived from transactions.

### 5.10 Budget Limit

**Purpose**

Assigns a spending limit to a category within one budget.

**Ownership**

A budget limit inherits its owner through the budget.

**Important information**

- budget
- category
- exact limit amount
- creation timestamp
- update timestamp

**Relationships**

- each budget limit belongs to exactly one budget
- each budget limit references exactly one eligible expense category
- one budget may contain many limits
- one category may appear in many budgets

**Rules**

- the category must be a system category or a custom category owned by the
  budget owner
- the same category should appear at most once within one budget
- the limit amount must be positive
- transfer and income categories cannot receive spending limits

### 5.11 Goal

**Purpose**

Represents a user-defined financial target.

Examples include travel, marriage, education fees, emergency funds, or a major
purchase.

**Ownership**

Every goal belongs to exactly one user.

**Important information**

- owner
- name
- goal type
- target amount
- starting amount
- target date
- priority
- status
- optional description
- creation timestamp
- update timestamp

**Relationships**

- one user may create many goals
- one goal may receive many goal contributions

**Rules**

- target amount must be positive
- starting amount cannot be negative
- starting amount must not exceed the target without an explicit completed-goal
  interpretation
- target date must be meaningful relative to creation
- goal priority must use an approved controlled representation
- completed and cancelled goals retain their historical contributions

**Derived information**

Current progress, remaining amount, required monthly saving, completion
probability, confidence bands, and forecasted completion date are derived.

### 5.12 Goal Contribution

**Purpose**

Represents an amount allocated toward a goal.

It allows FALCON to distinguish goal progress from general account balance.

**Ownership**

A contribution inherits its owner through its goal. If it references a
transaction, that transaction must have the same owner.

**Important information**

- goal
- optional supporting transaction
- amount
- contribution date
- source type
- optional note
- creation timestamp
- update timestamp

**Relationships**

- one goal may have many contributions
- one transaction may support zero or many goal contributions
- each contribution belongs to exactly one goal

**Rules**

- contribution amount must be positive
- the goal and supporting transaction must belong to the same user
- total allocations linked to one transaction must not exceed the transaction's
  eligible amount
- removing a transaction must not silently leave a misleading contribution
- manual contributions without a transaction are allowed for opening progress
  and external savings

### 5.13 Budget and goal currency boundary

The MVP uses fixed account currencies and defers foreign exchange.

Budget and goal currency handling will follow one of these implementation
approaches, to be finalized in Phase 2.2:

- explicitly store a fixed currency on each budget and goal; or
- require them to use the user's default planning currency.

Whichever approach is selected must prevent silently adding amounts expressed
in different currencies.

## 6. Conceptual ER model

```mermaid
erDiagram
    USER ||--o| FINANCIAL_PROFILE : has
    USER ||--o{ ACCOUNT : owns
    ACCOUNT ||--o| LIABILITY_DETAIL : specializes
    USER ||--o{ CATEGORY : creates
    CATEGORY o|--o{ CATEGORY : contains
    USER ||--o{ IMPORT_JOB : initiates
    USER ||--o{ TRANSFER_GROUP : owns
    USER ||--o{ TRANSACTION : owns
    ACCOUNT ||--o{ TRANSACTION : records
    CATEGORY o|--o{ TRANSACTION : classifies
    IMPORT_JOB o|--o{ TRANSACTION : produces
    TRANSFER_GROUP o|--|{ TRANSACTION : links
    USER ||--o{ BUDGET : creates
    BUDGET ||--o{ BUDGET_LIMIT : contains
    CATEGORY ||--o{ BUDGET_LIMIT : limits
    USER ||--o{ GOAL : creates
    GOAL ||--o{ GOAL_CONTRIBUTION : receives
    TRANSACTION o|--o{ GOAL_CONTRIBUTION : supports
    ```

The diagram expresses conceptual cardinality. Rules such as exactly two
transactions per transfer group require additional constraints or transactional
service behaviour beyond what the diagram alone can show.

## 7. Relationship and lifecycle rules

| Parent | Child | Cardinality | Child behaviour |
|---|---|---:|---|
| User | Financial profile | 1 to 0..1 | Delete with user |
| User | Account | 1 to 0..many | Delete through account-erasure workflow |
| Account | Liability detail | 1 to 0..1 | Delete with account |
| User | Custom category | 1 to 0..many | Archive if referenced |
| Category | Child category | 0..1 to 0..many | Restrict invalid hierarchy deletion |
| User | Import job | 1 to 0..many | Delete with user |
| Import job | Transaction | 0..1 to 0..many | Preserve transaction provenance |
| User | Transaction | 1 to 0..many | Delete with user |
| Account | Transaction | 1 to 0..many | Preserve while account is archived |
| Category | Transaction | 0..1 to 0..many | Restrict or safely unclassify |
| Transfer group | Transaction | 1 to exactly 2 | Operate on both entries atomically |
| User | Budget | 1 to 0..many | Delete with user |
| Budget | Budget limit | 1 to 0..many | Delete with budget |
| Category | Budget limit | 1 to 0..many | Restrict while referenced |
| User | Goal | 1 to 0..many | Delete with user |
| Goal | Goal contribution | 1 to 0..many | Delete with goal |
| Transaction | Goal contribution | 0..1 to 0..many | Restrict or reconcile deliberately |

Exact PostgreSQL foreign-key actions will be specified in Phase 2.2 and
implemented with the schema.

## 8. Ownership invariants

The following invariants are mandatory:

1. An account's owner is its user.
2. A transaction's user must own its account.
3. A private category used by a transaction must have the same owner.
4. An import job linked to a transaction must have the same owner.
5. A transfer group and both transfer entries must have the same owner.
6. Both accounts in a transfer must have the same owner.
7. A budget limit's private category must belong to the budget owner.
8. A goal contribution and its supporting transaction must resolve to the same
   owner.
9. No query may return a private record only because its identifier was known.
10. Derived data, exports, forecasts, and reports must preserve these ownership
    boundaries.

## 9. Stored and derived information

| Information | Stored or derived | Reason |
|---|---|---|
| Account opening balance | Stored | User-supplied starting fact |
| Account current balance | Derived | Opening balance plus transactions |
| Transaction amount and date | Stored | Historical financial event |
| Transaction currency | Inherited | Fixed by account |
| Monthly income and spending | Derived | Aggregation of transactions |
| Budget limit | Stored | User decision |
| Budget consumption | Derived | Eligible transactions in budget period |
| Goal target and deadline | Stored | User decision |
| Goal progress | Derived | Starting amount plus contributions |
| Required monthly saving | Derived | Goal gap and remaining time |
| Liability terms | Stored | User-supplied or imported facts |
| Amortization projection | Derived | Liability terms and assumptions |
| Risk score | Deferred derived result | Requires Phase 4 risk design |
| Forecast probability | Deferred derived result | Requires Phase 9 design |
| Financial health score | Deferred derived result | Requires analytics definition |
| Import processing status | Stored | Operational history |
| Duplicate-import indicators | Stored or derived during ETL | Requires Phase 6 design |

## 10. Expected query patterns

The future physical schema and indexes must support:

- retrieving one user's active accounts
- retrieving one account's transactions over a date range
- retrieving all user transactions over a date range
- aggregating spending by month and category
- calculating account balances
- finding uncategorized transactions
- finding transactions produced by an import job
- detecting previously imported source records
- retrieving both sides of a transfer
- retrieving active budgets for a date
- calculating budget usage by category
- retrieving active goals ordered by priority or deadline
- calculating contributions and progress for a goal
- retrieving a user's debt-bearing accounts
- calculating upcoming liability obligations
- retrieving the current financial profile

Index choices will be justified from these access patterns during physical
schema design.

## 11. Deletion and privacy requirements

FALCON promises complete user-data deletion.

The deletion design must therefore support:

- permanent deletion of personal profiles
- permanent deletion of accounts and transactions
- permanent deletion of custom categories
- permanent deletion of goals, budgets, and contributions
- permanent deletion of import records and retained source files
- deletion of future forecasts, scenarios, recommendations, and reports
- removal of authentication identity and credentials
- prevention of orphaned private records

Archiving is permitted for normal product workflows such as closing an account
or retiring a category. Archiving is not a substitute for complete
user-requested erasure.

System-defined reference categories are not deleted when one user is erased.

Backup retention and production erasure procedures will require a separate
deployment and privacy policy.

## 12. Deferred domains

The following domains are deliberately deferred:

### Authentication

Password hashes, verification tokens, reset tokens, sessions, refresh tokens,
and external-login identities belong to Phase 3.

### Risk assessment

Question definitions, answers, assessment versions, scores, and explanation
snapshots require the Phase 4 risk-profile contract.

### Detailed ETL records

Raw extracted rows, validation failures, mapping decisions, and reconciliation
records require the Phase 6 ETL design.

### Classification metadata

Model versions, confidence scores, explanations, correction history, and
training feedback require the Phase 7 classification design.

### Analytics snapshots

Financial-health scores, warnings, streaks, milestones, and badges require
formal metric definitions in Phase 8.

### Forecasting

Forecast runs, model candidates, selected models, confidence bands,
probabilities, and breaking events require Phase 9.

### Optimization and scenarios

Goal allocations, optimized schedules, assumptions, alternatives, and
comparison results require Phases 10 and 11.

### AI assistant

Conversation history, retrieval records, citations, and safety metadata require
Phase 12 and a separate privacy decision.

### Reports and exports

Generated artifact metadata, retention, download authorization, and report
snapshots require their feature contracts.

### Households and shared finances

The MVP uses direct single-user ownership.

A future household design may introduce a household or workspace ownership
root, memberships, roles, and sharing rules. The MVP does not add nullable
household identifiers or premature sharing tables.

Migration to households must be designed explicitly rather than weakening
current user-isolation rules.

### Foreign exchange

Cross-currency accounts may exist independently, but cross-currency transfers,
conversion rates, base-currency analytics, and realized gains or losses are
deferred.

## 13. Implementation questions reserved for Phase 2.2

The database-standards checkpoint must decide:

- identifier type and public identifier exposure
- table and constraint naming conventions
- exact monetary precision and scale
- transaction sign convention
- currency representation
- timestamp and date types
- controlled vocabulary implementation
- common audit fields
- account and category archival fields
- foreign-key deletion actions
- database-level ownership enforcement
- transfer-pair enforcement
- budget and goal currency representation
- encryption or hashing of sensitive external references
- duplicate-import key strategy
- initial index conventions

These questions must be resolved before SQLAlchemy models and migrations are
implemented.

## 14. Acceptance review

This model is ready for Phase 2.1 approval when:

- every MVP entity has a clear purpose
- every private entity has an ownership rule
- relationships and conceptual cardinalities are documented
- transfer pairs and currency inheritance are explicit
- user-isolation invariants are documented
- stored and derived values are distinguished
- lifecycle and deletion requirements are documented
- expected query patterns are identified
- future household support remains deferred cleanly
- the ER model matches the entity catalogue
- implementation-specific questions are reserved for Phase 2.2
