# Phase 10 — Multi-Goal Optimization

Goal-planning contract version: `2026.1`

This cumulative record freezes the approved Phase 10 semantics. Batch 1 contains
Checkpoints 10.0–10.2, Batch 2 contains Checkpoints 10.3–10.5, Batch 3 contains
Checkpoints 10.6–10.8, and Batch 4 contains Checkpoints 10.9–10.11. Together
they establish goal management, contribution-aware progress, immutable planning
evidence, the forecast-to-savings-capacity bridge, independent feasibility
evidence, explainable ranking, a deterministic greedy reference allocation, a
constrained optimizer, fail-safe financial guardrails, and a unified monthly
contribution schedule with baseline comparison. The resulting plan is still
non-persistent and cannot move money.

## 1. Checkpoint 10.0 — readiness and boundaries

Phase 10 starts from merged Phase 9 commit
`0173cb672f80b8ec774e1bdce61aa4a7ac98776d`. The initial domain migration
already provides owner-scoped `goals` and `goal_contributions` tables, allowed
goal types, lifecycle states, composite ownership keys, contribution integrity
triggers, and priority/deadline indexes. Batch 1 therefore adds no duplicate
table or migration.

The pinned development stack already included SciPy with its HiGHS linear
programming implementation. Batch 4 formalizes a pinned `optimization` extra
containing NumPy and SciPy, and the production API image installs that extra.
The provider remains lazy so a minimal library installation fails safely into a
deterministic fallback rather than failing application import.

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

## 7. Checkpoint 10.6 — feasibility, probability, and deadline risk

Feasibility policy version `2026.1` evaluates every goal independently against
the shared savings-capacity evidence available through that goal's deadline. It
calculates protected, expected, and upside capacity; exact shortfalls; and the
first forecast month in which each capacity band could fund the remaining goal
amount.

The result is classified as funded, secure, feasible, stretch, unlikely,
indeterminate, overdue, or unavailable. Secure means the 95% lower capacity is
sufficient; feasible means the expected capacity is sufficient; stretch means
only the 95% upper capacity is sufficient. A forecast that ends before the goal
deadline cannot create a false failure: if the observed horizon is insufficient,
the state is indeterminate and the probability is omitted.

Completion probability uses a deterministic piecewise interpolation anchored at
the 95% lower bound (`0.975`), expected value (`0.5`), and 95% upper bound
(`0.025`). It is planning evidence rather than a promise or Monte Carlo scenario.
Results expose the policy and method, evidence reliability, horizon, deadline
risk, shortfalls, completion windows, and stable reason codes. These independent
assessments deliberately reuse capacity and therefore do not claim that all
goals can be achieved simultaneously.

## 8. Checkpoint 10.7 — explainable deterministic goal ranking

Ranking policy version `2026.1` produces one bounded 0–100 attention score from
five auditable components:

| Component | Maximum points | Meaning |
|---|---:|---|
| User priority | 40 | Preserves the user's low/medium/high/critical choice as the strongest signal |
| Deadline urgency | 25 | Gives nearer and overdue deadlines more attention |
| Goal-type safety | 15 | Gives emergency-fund and education goals a bounded safety weighting |
| Deadline risk | 10 | Surfaces goals whose forecast evidence indicates pressure |
| Completion momentum | 10 | Recognizes progress toward a still-unfunded goal |

Ordering is deterministic: allocation-eligible goals come first, then total
score, user-priority component, earlier deadline, completion momentum, and goal
identifier break ties. Each item returns the component scores, feasibility state,
deadline risk, probability, allocation eligibility, and stable reason codes.
Ranking is an explainable policy input; it does not itself move money or
constitute personalized investment advice.

## 9. Checkpoint 10.8 — protected-capacity greedy baseline

Greedy allocation policy version `2026.1` provides a safe reference result for
the constrained solver planned in Checkpoint 10.9. For each forecast month it
uses only the non-negative 95% lower savings capacity, visits eligible goals in
rank order, and assigns no more than the goal's remaining amount. One month's
capacity is consumed at most once, and no allocation is made after a goal's
deadline.

The immutable result contains a deterministic SHA-256 baseline identifier,
monthly allocations, per-goal projected completion and remaining amounts, total
capacity, allocated and unallocated totals, source policy versions, and explicit
warnings for missing/provisional capacity, incomplete snapshot evidence,
unallocated capacity, and unfunded goals. Missing capacity produces a valid
zero-allocation result rather than invented savings. The baseline is pure and
non-persistent: it does not create a contribution, mutate a goal, approve a plan,
or use the linear-programming solver.

`analyze_goal_planning_snapshot()` executes the complete Batch 3 chain against
one snapshot: feasibility assessment, ranking, and greedy baseline generation.

## 10. Checkpoint 10.9 — constrained SciPy/HiGHS optimizer

Constrained optimization policy version `2026.1` defines one continuous linear
program over monthly goal allocations and per-goal funded fractions. It
maximizes the sum of each explainable ranking score multiplied by that goal's
funded fraction. A bounded rank-order tie break preserves deterministic choices
when primary scores are equal.

The hard constraints require all allocations to be non-negative, keep each
month within that month's protected 95% lower savings capacity, keep every goal
within its exact remaining amount, link its funded fraction to actual assigned
money, and forbid assignment after its deadline. Capacity is shared across all
goals, so it can be consumed only once. The model uses no expected or upside
forecast money and performs no currency conversion.

`SciPyHighsSolver` is an injectable, lazy adapter around the pinned HiGHS method.
Provider outcomes are normalized as optimal, infeasible, unbounded, failed, or
unavailable. Output dimensions, finite values, bounds, and every floating-point
constraint are checked before any result is accepted. Accepted solver values are
rounded down to FALCON's four-decimal money scale and then rechecked with exact
`Decimal` invariants. The candidate includes provider/version/status evidence,
model dimensions, exact monthly allocations, projections, totals, a weighted
funding score, and stable outcome codes.

## 11. Checkpoint 10.10 — financial guardrails and safe fallback

Guardrail policy version `2026.1` evaluates the immutable snapshot before the
solver runs. Missing or zero protected capacity, no allocation-eligible goals,
or incomplete minimum-payment evidence for any debt account blocks automatic
allocation. Provisional forecasts and incomplete profile or budget evidence
remain explicit cautions instead of being silently treated as complete.

Current liquid balances are protected evidence and are never made available to
the optimizer. When a positive budget baseline exists, the emergency target is
the user's configured target months or a fixed three-month default, multiplied
by the monthly expense baseline. Any gap between that target and non-negative
liquid balance becomes a hard reserve. At every monthly prefix, non-emergency
allocations cannot exceed cumulative protected capacity minus that reserve.
Emergency-fund goals may consume the reserved capacity; if no eligible
emergency-fund goal can use it, it remains unallocated.

Observed savings forecasts already represent income less observed expenses.
Debt minimum payments are therefore audited for completeness and reported, but
are not subtracted from forecast savings a second time. This avoids overstating
capacity through missing debt terms and understating it through double counting.

Every selected schedule is rechecked for exact period identity, monthly totals,
single-use capacity, known goal and rank, positive allocation, goal cap,
deadline, emergency reserve, and aggregate reconciliation. If HiGHS is missing,
fails, reports no usable solution, returns non-finite or unsafe values, or
underperforms the guardrail-aware deterministic reference after rounding, FALCON
selects a deterministic guarded greedy schedule. A blocking guardrail instead
selects a zero-allocation schedule.

## 12. Checkpoint 10.11 — unified schedule and baseline comparison

`build_goal_optimization_plan()` executes the Batch 3 analysis, Batch 4
guardrails, constrained optimizer, invariant verification, and safe selection in
one pure orchestration path. It returns one exact monthly contribution schedule,
per-goal allocated and remaining amounts, projected completion periods, funded
and deadline-met counts, allocated/unallocated totals, and the selected weighted
funding score.

The comparison keeps four decisions auditable: the original Checkpoint 10.8
greedy baseline, whether that baseline complies with the new emergency reserve,
the guarded deterministic fallback, and the optimized candidate when one exists.
It exposes score, allocation, funded-goal, deadline, and delta evidence without
claiming that a larger raw allocation is automatically safer. The selected
result, reserve, strategy, reasons, and exact schedule produce a deterministic
SHA-256 plan identifier.

Fixed assumptions explicitly state that the plan uses only protected capacity,
excludes current liquid balance, treats the savings forecast as post-expense,
does not double-count debt payments, enforces deadlines, performs no currency
conversion, accepts no Phase 11 scenario overrides, and is non-persistent. Batch
4 creates no contribution, changes no goal, stores no approval, and exposes no
new public endpoint.

## 13. Batch boundaries

Batch 2 adds no feasibility probability, deadline-risk estimator, goal ranking,
greedy allocator, linear-programming solver, generated-plan table, plan approval,
optimization endpoint, scenario controls, AI explanation, background task, or
notification. Those responsibilities remain with Checkpoints 10.6–10.14 and
later phases.

Batch 3 adds feasibility, deadline-risk, ranking, and the greedy reference
allocator. It adds no SciPy/HiGHS optimization, mutable policy weights,
user-controlled scenario assumptions, generated-plan persistence, approval or
application workflow, public optimization endpoint, AI explanation, background
task, or notification. Those responsibilities remain with Checkpoints 10.9–10.14
and later phases.

Batch 4 adds the SciPy/HiGHS constrained optimizer, debt and emergency-fund
guardrails, exact invariant verification, deterministic safe fallback, and a
unified non-persistent schedule with baseline comparison. It adds no mutable
policy weights, user-controlled scenario assumptions, generated-plan table,
approval or contribution-application workflow, public optimization endpoint, AI
explanation, background task, or notification. Persistence, approval/application,
and public API responsibilities remain with Checkpoints 10.12–10.14; scenarios,
generative explanation, and scheduled execution remain assigned to Phases
11–13.
