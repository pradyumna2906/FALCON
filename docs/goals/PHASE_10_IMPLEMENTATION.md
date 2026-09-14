# Phase 10 — Multi-Goal Optimization

Goal-planning contract version: `2026.1`

This cumulative record freezes the approved Phase 10 semantics. Batch 1 contains
Checkpoints 10.0–10.2 and Batch 2 contains Checkpoints 10.3–10.5. Together they
establish goal management, contribution-aware progress, immutable planning
evidence, and the forecast-to-savings-capacity bridge. They do not yet rank goals,
allocate savings, or generate an optimized goal plan.

## 1. Checkpoint 10.0 — readiness and boundaries

Phase 10 starts from merged Phase 9 commit
`0173cb672f80b8ec774e1bdce61aa4a7ac98776d`. The initial domain migration
already provides owner-scoped `goals` and `goal_contributions` tables, allowed
goal types, lifecycle states, composite ownership keys, contribution integrity
triggers, and priority/deadline indexes. Batch 1 therefore adds no duplicate
table or migration.

The pinned development stack already includes SciPy with its HiGHS linear
programming implementation. Solver work remains deferred to Checkpoint 10.9;
Batch 1 introduces no new runtime dependency.

Phase 10 owns goal management, progress, feasibility, completion-probability
evidence, goal ranking, constrained savings allocation, contribution schedules,
and immutable plan approval history. Phase 11 owns user-controlled what-if and
best/expected/worst scenario comparison. Phase 12 owns generative explanations,
and Phase 13 owns scheduled production execution and notifications.

## 2. Checkpoint 10.1 — contract and semantics

Policy version `2026.1` supports travel, marriage, education, emergency-fund,
major-purchase, and other goals. A goal records a positive target, a
non-negative starting amount no greater than its target, one ISO-style currency,
a future deadline, low/medium/high/critical priority, active/completed/cancelled
status, and bounded optional descriptive text.

New goals always start as `active`. The only permitted lifecycle transitions
are `active` to `completed` and `active` to `cancelled`. Terminal goals retain
their history and cannot be edited or transitioned again. FALCON does not infer
completion merely because starting progress equals the target; completion is an
explicit user decision until contribution-aware progress arrives in Checkpoint
10.3.

The authenticated principal supplies the owner, trusted IANA timezone, and
default currency. The client cannot submit an owner identifier or lifecycle
status. An explicitly supplied currency is normalized to uppercase, but Phase
10 performs no conversion or mixed-currency arithmetic.

The following calculations are reserved for Checkpoint 10.3 and later:

- current progress from starting amount plus eligible contributions;
- remaining amount and required monthly contribution;
- completion probability and forecasted completion date;
- priority scoring, savings capacity, allocation, and plan optimization.

## 3. Checkpoint 10.2 — authenticated goal management

`GoalService` and `GoalRepository` provide create, list, get, partial update,
complete, and cancel operations. Every lookup contains both the trusted
`user_id` and goal identifier. A missing goal and a goal owned by another user
therefore share the same `goal_not_found` response.

Updates and terminal transitions acquire a PostgreSQL row lock before checking
the current state. This prevents two concurrent requests from safely applying
incompatible changes to the same active goal. Repository mutation methods also
verify the owner before changing an already-loaded object.

The authenticated API operations are:

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v1/goals` | Create one active owner-scoped goal |
| `GET` | `/api/v1/goals` | List at most 100 owned goals |
| `GET` | `/api/v1/goals/{goal_id}` | Get one owned goal |
| `PATCH` | `/api/v1/goals/{goal_id}` | Partially update one active goal |
| `POST` | `/api/v1/goals/{goal_id}/complete` | Complete one active goal |
| `POST` | `/api/v1/goals/{goal_id}/cancel` | Cancel one active goal |

List ordering is deterministic: active goals first, then completed and
cancelled goals; within each state, critical/high/medium/low priority, deadline,
creation time, and identifier break ties. An optional status filter and a
bounded limit are supported.

Public responses exclude `user_id`. Unknown request fields are rejected, so a
client cannot override identifiers, status, timestamps, progress, computed
probability, or future optimization evidence.

## 4. Checkpoint 10.3 — contributions and exact progress

`ContributionService` supports manual, transaction-linked, and opening-balance
contributions. Manual and opening-balance records require a non-future local
date and cannot reference a transaction. Transaction-linked records require a
posted transaction owned by the authenticated user, inherit that transaction's
date, and must use the same currency as the goal.

Every contribution mutation locks the owner-scoped goal first. Transaction-linked
creation also locks the transaction before checking its existing allocation.
The application rejects contributions that exceed either the goal's remaining
amount or the unallocated absolute transaction amount. The existing deferred
PostgreSQL trigger remains the final cross-goal transaction-allocation guard.

Progress is calculated with four-decimal `Decimal` arithmetic:

- `current = starting_amount + eligible_contributions`;
- `remaining = max(0, target_amount - current)`;
- `funding_ratio = min(1, current / target_amount)`;
- `required_monthly = ceil(remaining / available_monthly_deposits, 4 decimals)`.

The progress result includes current and remaining amounts, funding ratio and
percentage, remaining monthly deposit opportunities, required monthly amount,
and a contribution-aware funding state. A fully funded active goal remains
active until the user explicitly completes it; an unfunded active goal whose
deadline has passed is reported as overdue.

The authenticated contribution operations are:

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v1/goals/{goal_id}/contributions` | Add one allocation-safe contribution |
| `GET` | `/api/v1/goals/{goal_id}/contributions` | List contribution evidence in stable date order |
| `DELETE` | `/api/v1/goals/{goal_id}/contributions/{id}` | Remove evidence from an active goal |
| `GET` | `/api/v1/goals/{goal_id}/progress` | Calculate exact contribution-aware progress |

## 5. Checkpoint 10.4 — immutable planning snapshot

`GoalPlanningSnapshotService` reads every planning input under one trusted UTC
cutoff and authenticated owner. It includes active same-currency goals and
contributions, the current financial profile, emergency-fund target, liquid
balance, debt and minimum-payment evidence, active budget evidence, and the
latest eligible monthly savings forecast.

All source queries contain `user_id`, currency where monetary evidence is used,
and creation/update cutoff predicates. Goals in other currencies are excluded
instead of being converted. The snapshot records warnings for missing or
incomplete evidence and exposes source counts, identifiers, latest timestamps,
the cutoff, trusted timezone, local date, and a deterministic SHA-256 snapshot
identifier. Public responses do not expose the owner identifier or raw ledger
records.

`GET /api/v1/goal-planning/snapshot` builds this read-only snapshot. It does not
persist a plan or change any goal, forecast, budget, profile, or contribution.

## 6. Checkpoint 10.5 — forecast-to-savings-capacity bridge

Capacity policy version `2026.1` accepts only the newest eligible owner-scoped,
same-currency, monthly `savings_amount` forecast whose data and source timestamps
do not exceed the snapshot cutoff. Each future forecast point becomes:

- protected capacity from the non-negative 95% lower bound;
- expected capacity from the non-negative point estimate;
- upside capacity from the non-negative 95% upper bound.

Negative savings are clipped to zero because debt cannot be allocated as goal
funding. The snapshot returns monthly values, totals, the forecast run identifier,
uncertainty reliability, protection-band name, and policy version. Provisional or
unusable forecasts produce explicit warnings. These ranges are planning evidence,
not Phase 11 user-controlled best/expected/worst scenarios.

## 7. Batch 2 boundary

Batch 2 adds no feasibility probability, deadline-risk estimator, goal ranking,
greedy allocator, linear-programming solver, generated-plan table, plan approval,
optimization endpoint, scenario controls, AI explanation, background task, or
notification. Those responsibilities remain with Checkpoints 10.6–10.14 and
later phases.
