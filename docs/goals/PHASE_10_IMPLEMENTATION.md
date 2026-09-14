# Phase 10 — Multi-Goal Optimization

Goal-planning contract version: `2026.1`

This cumulative record freezes the approved Phase 10 semantics. Batch 1 contains
Checkpoints 10.0, 10.1, and 10.2. It establishes the goal-management boundary
needed by later probability and optimization work; it does not yet allocate
savings or generate a goal plan.

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

## 4. Batch 1 boundary

Batch 1 adds no contribution service, progress calculation, forecast-to-savings
bridge, probability estimator, goal ranking, greedy allocator, linear-programming
solver, generated-plan table, plan approval, optimization endpoint, scenario,
AI explanation, background task, or notification. Those responsibilities remain
with approved Checkpoints 10.3–10.14 and later phases.
