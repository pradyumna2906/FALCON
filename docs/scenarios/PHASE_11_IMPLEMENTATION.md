# Phase 11 — Scenario Simulation

Scenario-simulation contract version: `2026.1`

This cumulative record freezes the approved Phase 11 semantics. Batch 1 contains
Checkpoints 11.0–11.2; later approved batches reserve deterministic scenarios and
financial shocks for 11.3–11.5, Monte Carlo and risk metrics for 11.6–11.8,
alternative comparison and immutable history for 11.9–11.11, and orchestration,
authenticated APIs, monitoring, security, and closure for 11.12–11.14.

Phase 11 answers bounded what-if questions against immutable Phase 9 forecast and
Phase 10 plan evidence. It does not rewrite observations, forecasts, goals,
contributions, or plans. It cannot move money. Generative explanations and RAG
belong to Phase 12; scheduled execution, notification, frontend integration, and
production operations belong to Phase 13.

## 1. Checkpoint 11.0 — readiness, scope, and contracts

Phase 11 starts from merged Phase 10 commit
`14f66962f61c2aa1ee0bea2af86fe6fcde463018`. Phase 10 provides immutable
owner-scoped plan runs, exact protected-capacity schedules, frozen per-goal
outcomes, policy versions, solver provenance, and generated/approved/rejected/
superseded lifecycle history. Phase 11 reuses that evidence rather than creating
a second optimizer or reconstructing current financial state behind the source
plan's cutoff.

The contract fixes these boundaries:

- an authenticated owner selects one immutable Phase 10 source plan;
- a server-owned UTC cutoff and the plan's trusted timezone determine scenario
  time semantics;
- observed facts, forecast evidence, baseline plan decisions, hypothetical user
  assumptions, and derived scenario results remain distinct;
- every request is bounded to ten alternatives and a 24-month source horizon;
- a scenario snapshot is deterministic for the same cutoff, source evidence,
  policy version, and normalized assumptions;
- no scenario input can modify Phase 9 or Phase 10 records;
- no client can choose an owner, evidence cutoff, policy version, forecast value,
  stored balance, random-number implementation, or optimization constraint.

Batch 1 is deliberately read-only and requires no Alembic migration, package, or
public API route. It establishes the internal foundation that later checkpoints
will evaluate and persist.

## 2. Checkpoint 11.1 — strict scenario assumption contract

`ScenarioSimulationDraftRequest` identifies one source plan and accepts one to
ten uniquely named alternatives. Pydantic rejects unknown fields and freezes the
request graph. `ScenarioAssumptions` repeats the critical invariants at the
application boundary so internal callers cannot bypass the public schema.

One alternative may include:

| Assumption | Boundary |
|---|---|
| Income percentage change | −100% through +300% |
| Expense percentage change | −100% through +300% |
| One-time expense | Positive exact amount on a month boundary |
| Recurring expense adjustment | Non-zero signed amount over at most 24 months |
| Income interruption | Month range plus 0–100% retained income |
| Goal target | Positive exact amount not below frozen current progress |
| Goal deadline | Future date |
| Goal priority | Existing low/medium/high/critical enum |
| Monthly contribution delta | Non-zero signed exact amount |
| Goal-funding pause | Complete month range inside the source horizon |
| Emergency-fund target | 0–24 months |

Amounts use the existing four-decimal financial scale and the PostgreSQL
`NUMERIC(19,4)` magnitude. Scenario names are printable, trimmed, limited to 80
characters, and case-insensitively unique within one request. Each goal may be
adjusted at most once per alternative. An alternative must change at least one
value; the unchanged protected/expected/upside reference cases remain
server-owned rather than client-supplied duplicates.

Maximum collection sizes are closed constants: twelve one-time expenses, twelve
recurring expense adjustments, four interruption ranges, and one adjustment for
each of at most one hundred goals. All dated financial events and pause ranges
must fall within the immutable source-plan horizon.

The client cannot submit identity, cutoff, historical values, policy versions,
solver selection, random generator, forecast points, source balances, calculated
probabilities, or derived results.

## 3. Checkpoint 11.2 — immutable scenario evidence snapshot

`ScenarioEvidenceService.build()` performs the following read-only chain:

```text
validate normalized alternatives
→ load source plan by authenticated owner and plan identifier
→ require a current generated or approved lifecycle state
→ freeze a trusted UTC cutoff and local date
→ verify source timestamps, outcomes, ranks, and monthly periods
→ load the exact referenced savings forecast by owner and forecast identifier
→ verify target, monthly granularity, currency, cutoff, periods, and capacity
→ validate every hypothetical goal and period against frozen source evidence
→ build immutable source-plan, forecast, goal, schedule, and assumption records
→ calculate deterministic SHA-256 scenario snapshot identifier
```

A missing and foreign source plan share the same
`scenario_source_plan_not_found` response. Rejected and superseded plans cannot
start new simulations because they are no longer current decisions. Generated
plans remain eligible but carry `source_plan_generated_only`; approved plans do
not carry that warning.

When the Phase 10 plan references a forecast, the service requires the exact
owner-scoped run. It must forecast `savings_amount` monthly in the plan currency,
its data and source timestamps must not exceed the plan cutoff, its periods must
exactly equal the stored plan periods, and each stored protected capacity must
equal the non-negative 95% lower forecast bound. A mismatch fails closed with
`scenario_evidence_unavailable` rather than silently simulating against different
evidence.

Percentage income and expense assumptions require their own baselines because a
savings forecast alone cannot reveal how much income or expense changed. The
scenario repository therefore selects the newest eligible `gross_income` or
`total_expense` monthly forecast only when a requested alternative needs it. The
query is owner-, currency-, target-, granularity-, cutoff-, exact-horizon-, and
creation-time-scoped. Missing or provisional supplemental evidence is retained as
an income- or expense-specific warning; later engines must report that scenario
as limited or unavailable rather than infer a baseline from savings.

A Phase 10 zero-capacity plan without a forecast may still form a limited
snapshot. It receives `forecast_unavailable`, enabling later deterministic
comparison without manufacturing stochastic evidence. A provisional forecast
receives `forecast_provisional`.

The resulting internal snapshot retains the owner for repository enforcement but
future public response schemas must omit it. It freezes source identifiers,
hashes, status, timestamps, currency, strategy, feasibility, reserve, money
totals, score, all Phase 10 policy versions, forecast model and uncertainty
provenance, confidence bands, per-goal outcomes, exact monthly allocations,
normalized hypotheses, and bounded warnings.

## 4. Security and integrity established by Batch 1

- Owner scope appears in both source-plan and forecast repository reads.
- Foreign resources are indistinguishable from missing resources.
- Only generated or approved plans can start new simulations.
- Forecast and source-plan currencies must match; no conversion occurs.
- Percentage income and expense shocks use matching target-specific forecasts.
- Source timestamps cannot exceed either planning or scenario cutoffs.
- Forecast periods and protected values must reconcile with the stored plan.
- Goal overrides must reference a frozen source-plan goal.
- Goal targets cannot erase already achieved progress.
- Every dated adjustment remains within the frozen horizon.
- Hypotheses are immutable values and never update financial records.
- Snapshot identifiers use canonical JSON and SHA-256.

## 5. Validation boundary

Batch 1 validation covers domain and Pydantic assumption limits, immutability,
server-field rejection, unique alternatives and goals, owner-scoped repository
calls, deterministic hashing, exact forecast-to-plan reconciliation, future-data
rejection, source lifecycle rules, out-of-horizon adjustments, unknown goals,
missing forecasts, and a real PostgreSQL owner-isolation scenario added to the
existing goal-plan lifecycle test.

## 6. Deferred checkpoints

Batch 1 adds no deterministic scenario transformation, financial-shock engine,
scenario goal-plan reevaluation, Monte Carlo calibration, stochastic simulation,
percentile or tail-risk metric, sensitivity analysis, alternative ranking,
scenario persistence, selection history, public endpoint, background execution,
AI explanation, notification, or frontend. These responsibilities remain with
Checkpoints 11.3–11.14 and later phases.
