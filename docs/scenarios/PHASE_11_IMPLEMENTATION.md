# Phase 11 — Scenario Simulation

Scenario-simulation contract version: `2026.1`

This cumulative record freezes the approved Phase 11 semantics. Batch 1 contains
Checkpoints 11.0–11.2, Batch 2 contains deterministic scenarios, ordered
financial shocks, and Phase 10 goal-plan reevaluation for 11.3–11.5, Batch 3
contains uncertainty calibration, bounded seeded Monte Carlo, and empirical risk
metrics for 11.6–11.8, and Batch 4 contains cross-scenario comparison, sensitivity,
decision ranking, and immutable history for 11.9–11.11. Final Batch 5 completes
transactional orchestration, authenticated lifecycle APIs, privacy-safe
monitoring, security closure, and release readiness for 11.12–11.14.

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
| Debt-payment adjustment | Non-zero signed delta over at most 24 months |
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
recurring expense adjustments, twelve debt-payment adjustments, four
non-overlapping interruption ranges, and one adjustment for each of at most one
hundred goals. All dated financial events and pause ranges must fall within the
immutable source-plan horizon.

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

## 4. Checkpoint 11.3 — deterministic scenario paths

`build_deterministic_scenario_paths()` produces three server-owned references
before the bounded user alternatives:

| Case | Monthly capacity selected |
|---|---|
| Protected / worst | Phase 9 non-negative 95% lower savings bound |
| Expected | Phase 9 non-negative point estimate |
| Upside / best | Phase 9 non-negative 95% upper savings bound |

Each reference retains exact period identity, all three confidence values,
source provenance, the Phase 10 emergency reserve, totals, a policy version, and
a deterministic SHA-256 path identifier. When the source plan has no savings
forecast, the protected path may reuse its already verified stored capacity as
limited evidence; expected and upside cases are unavailable instead of invented.

User-defined cases begin with the same protected/expected/upside savings bands
and apply deterministic adjustments to each band. They select protected capacity
for allocation safety. There are no hidden salary, inflation, or stress constants:
a stress case is an explicit bounded hypothesis, while the three standard cases
remain server-owned. This prevents the user from submitting a duplicate baseline
or silently controlling confidence semantics.

All paths are pure values. They neither call the database nor update a forecast,
goal, contribution, or plan.

## 5. Checkpoint 11.4 — ordered financial shocks

The fixed monthly transformation order is:

```text
trusted savings bands
→ income percentage change
→ temporary income interruption and automatic recovery
→ expense percentage change
→ one-time expenses
→ recurring expense changes
→ debt-payment changes
→ clipped scenario savings bands
→ emergency reserve and goal-contribution constraints
```

Income and expense percentage changes use their matching owner- and cutoff-scoped
Phase 9 forecasts. An interruption retains 0–100% of the already adjusted income
inside its non-overlapping month range; the next month automatically returns to
the percentage-adjusted baseline. Recurring expense and debt-payment changes are
signed, range-bounded, and additive. A debt delta represents only the hypothetical
change from the savings forecast's observed post-expense baseline, preventing the
existing debt payment from being subtracted twice.

One-time expenses are applied exactly once in their named month. Every raw band
must remain finite and inside the exact `NUMERIC(19,4)` magnitude. Negative
savings are retained as raw evidence but clipped to zero before allocation, with
an explicit reason code. Confidence ordering is preserved after every shock.

Without an emergency-target override, the immutable Phase 10 reserve is reused.
With an override, the engine conservatively multiplies the requested 0–24 months
by the largest adjusted recurring monthly expense baseline and assumes no liquid
balance offset because the source plan intentionally does not persist private
account balances. Missing expense evidence makes that alternative unavailable.

Goal contribution changes become exact solver bounds relative to the immutable
Phase 10 monthly allocation: a positive delta is a minimum, a negative delta is
an upper cap, and a pause sets the cap to zero for its month range. Pause semantics
override a contribution delta in overlapping months. An impossible minimum is
reported as infeasible and is never silently relaxed.

## 6. Checkpoint 11.5 — scenario-aware goal-plan reevaluation

`evaluate_deterministic_scenarios()` converts each available path into an
immutable Phase 10-compatible planning snapshot and reuses the existing policies:

```text
scenario capacity and goal overrides
→ Phase 10 feasibility and completion probability
→ Phase 10 explainable ranking
→ Phase 10 SciPy/HiGHS constrained allocation
→ exact goal, deadline, capacity, reserve, and contribution-bound verification
→ bounded guarded-greedy fallback
→ comparison with the immutable source plan
```

Goal amount, deadline, and priority overrides are applied only to temporary
`GoalProgress` values. Existing progress is preserved. The optimizer still uses
one currency, non-negative capacity, hard deadlines, goal caps, single-use monthly
capacity, and the emergency reserve. A new generic `GoalAllocationBound` extension
lets downstream policies add exact monthly minimums or maximums while retaining
the original Phase 10 behavior when no bounds are supplied.

Solver output is accepted only after Phase 10's exact Decimal invariants also
validate every scenario contribution bound. The guarded deterministic fallback
uses the same rank, deadline, reserve, goal-cap, monthly-capacity, and bound rules.
If mandatory contribution minimums cannot be satisfied, the scenario is marked
infeasible rather than returning an unsafe fallback.

Each result includes monthly capacity and allocations, completion probability,
completion period, protected/expected shortfalls, deadline results, reserve
status, weighted funding score, optimizer evidence, and exact deltas from the
Phase 10 allocated total, funded-goal count, deadline count, and weighted score.
The source plan remains byte-for-byte unchanged and repeated evaluation of the
same snapshot produces identical path and evaluation identifiers.

## 7. Checkpoint 11.6 — owner-scoped uncertainty calibration

`calibrate_scenario_uncertainty()` converts only the Phase 9 evidence already
frozen inside the private scenario snapshot into a bounded sampling contract.
It never queries another owner, reloads newer data, consumes final-test metrics,
or reconstructs raw validation residuals. Phase 9 intentionally persists the
validation residual count and calibrated 80% and 95% bands rather than private
raw residuals; Phase 11 preserves that boundary.

For supported `absolute_residual_conformal` evidence, each month receives the
following piecewise-linear inverse-CDF knots:

| Cumulative probability | Sample value |
|---:|---|
| 0% and 2.5% | Raw 95% lower value |
| 10% | Raw 80% lower value |
| 50% | Expected value |
| 90% | Raw 80% upper value |
| 97.5% and 100% | Raw 95% upper value |

The repeated endpoints make the calibrated 95% interval a hard simulation
bound instead of extrapolating unsupported tails. User-defined deterministic
shocks shift all knots by the same exact amount, preserving ordering. Raw
negative values remain available for downside measurement and are clipped to
zero only at the allocation boundary.

Reliability is explicit:

- `normal`: supported Phase 9 calibration with at least ten validation
  residuals and normal source reliability;
- `provisional`: supported bands with fewer residuals or provisional source
  reliability;
- `conservative`: missing residual evidence, an unsupported uncertainty method,
  or a source plan without a forecast uses a protected point mass;
- `unavailable`: the deterministic path itself lacks required trusted evidence.

The calibration identifier hashes the snapshot, path, policy, reliability,
sampling method, knots, residual count, and bounded reason codes. Final-test
metrics and future observations cannot change the identifier or distribution.

## 8. Checkpoint 11.7 — bounded seeded Monte Carlo

`run_scenario_monte_carlo()` uses NumPy PCG64 with 1,000 trials by default and a
hard maximum of 10,000 trials. The caller may provide a seed from zero through
`2^63 − 1`; otherwise the engine deterministically derives one from the snapshot
and Monte Carlo policy version. The root and resolved scenario seed are retained
in every result so the run can be replayed exactly and persisted by a later
checkpoint.

All paths use common random numbers: the same seeded uniform draws are passed
through each path's inverse CDF. This reduces comparison noise and ensures that
differences between alternatives come from assumptions rather than unrelated
random samples. Monthly draws are independent because Phase 9 does not persist a
validated residual-correlation model; Phase 11 does not invent serial dependence.

Each trial performs this bounded replay:

```text
sample raw monthly capacity inside Phase 9 bands
→ record any negative-savings month
→ clip allocation capacity to zero
→ apply Phase 10 deterministic rank and deadline eligibility
→ enforce contribution minimums, caps, and pauses
→ preserve the emergency reserve for non-emergency goals
→ enforce monthly capacity and remaining-goal caps
→ record completion step, deadline result, and final shortfall
```

The trial engine never invokes a solver thousands of times. It holds the reviewed
Phase 10 ranking fixed and vectorizes the same guarded fallback policy across all
trials. Invalid hard contribution minimums make that trial infeasible rather
than relaxing the constraint. Results use compact little-endian float64, int16,
and uint8 buffers plus a SHA-256 sample digest. A 50-million work-unit ceiling
bounds the product of trials, months, goals, and paths before allocation begins.

Monte Carlo runs remain pure and non-persistent. They do not update a forecast,
goal, contribution, source plan, or scenario record.

## 9. Checkpoint 11.8 — risk, percentiles, tail loss, and robustness

`evaluate_scenario_risk()` reduces the seeded samples into bounded empirical
metrics. Every probability uses all trials as its denominator unless explicitly
identified as conditional. Per scenario it reports:

- probability that all goals complete within the horizon;
- probability that every goal meets its deadline;
- probability that total non-negative capacity covers the emergency reserve;
- probability of at least one raw negative-savings month;
- probability that all hard contribution constraints remain feasible;
- expected capacity and capacity P10, P50, and P90;
- expected total shortfall and shortfall P10, P50, and P90;
- 90% shortfall value-at-risk and mean shortfall across the threshold tail;
- per-goal completion and deadline probabilities, expected shortfall, shortfall
  percentiles, and completion-period P10, P50, and P90.

Completion-period percentiles are conditional on completion, so each goal
returns its completion count as the explicit denominator. All other goal
probabilities retain the full trial count. Percentiles use a versioned nearest-
rank definition; the 90% tail expectation includes all ties at the VaR threshold.

The 0–100 robustness score is transparent and fixed:

```text
100 × (
  30% all-goals completion
  + 25% all-deadlines met
  + 20% emergency-reserve coverage
  + 15% no negative-savings month
  + 10% hard-constraint feasibility
)
```

Every result labels empirical probabilities as `seeded_empirical_monte_carlo`
and Phase 10 comparison evidence as `phase_10_analytical_normal_cdf`; the two
methods are never presented as interchangeable. `normal` runs are available,
while provisional and conservative runs are explicitly limited. Blocked and
unavailable paths return no invented statistics.

Protected, expected, and upside references describe deterministic decision
points but share the same underlying Phase 9 stochastic distribution. Common
random numbers therefore make their stochastic risk equal when goals and
guardrails are equal, while their deterministic schedules remain distinct.

## 10. Checkpoint 11.9 — alternative decision comparison

`analyze_scenario_decisions()` executes the approved pure chain once: paths,
uncertainty calibration, deterministic reevaluation, seeded Monte Carlo, and risk
reduction. It compares every alternative with the trusted protected reference
using exact deltas for expected capacity, completion and deadline probability,
reserve coverage, negative-savings exposure, expected and 90% tail shortfall,
robustness, weighted funding, funded goals, deadlines met, and additional required
contribution. Blocked or unavailable evidence remains explicitly non-comparable;
the engine never invents a neutral value.

The protected reference is a conservative tie-breaker. Expected or upside cases
can rank ahead only when their measured evidence is better, not merely because a
more optimistic label was requested. All comparison and analysis identifiers use
canonical SHA-256 payloads, and validation reconstructs those identities before
persistence so a mutated score, rank, result, or policy cannot be stored.

## 11. Checkpoint 11.10 — sensitivity, robustness, and decision ranking

The fixed 0–100 decision score weights all-goal completion, deadlines, reserve
coverage, absence of negative savings, constraint feasibility, expected and tail
shortfall, weighted goal funding, required contribution, and reliability. Scores
are deterministic evidence summaries rather than financial advice. Equal scores
use reliability, protected-to-upside case order, and path identity as stable
tie-breakers.

Pareto checks mark an alternative dominated only when another safe alternative is
no worse on every completion, deadline, reserve, feasibility, funding,
reliability, downside, shortfall, and contribution dimension and is strictly
better on at least one. A recommendation must be available or limited,
non-dominated, and rank first; otherwise the result records `no_safe_alternative`.

Sensitivity signals identify which submitted assumption categories most affect
the scenario. They combine the exact direct capacity effect with equal attribution
of outcome-only effects, sum to 100, and are explicitly labelled non-causal. The
engine separately reports the exact additional contribution burden over eligible
months, excluding funding pauses.

## 12. Checkpoint 11.11 — immutable simulation persistence

`ScenarioSimulationRepository.create()` validates the complete decision graph at
the storage boundary and writes one transaction containing:

- `scenario_simulation_runs` for owner, source-plan, snapshot, policy, horizon,
  replay seed, trial count, and method provenance;
- `scenario_definitions` for normalized assumptions and aggregate deterministic
  and stochastic outcomes;
- `scenario_periods` for exact source, shock, selected, allocated, and unallocated
  monthly amounts;
- `scenario_goal_outcomes` for deterministic and empirical goal results;
- `scenario_comparisons` for deltas, score, rank, dominance, recommendation,
  sensitivity, and bounded reason codes;
- `scenario_events` for append-only generated, selected, and selection-cleared
  history.

Composite owner foreign keys prevent cross-owner source plans, definitions,
comparisons, outcomes, and events. Database checks enforce exact-money
reconciliation, probability ranges, empirical result shape, bounded seeds/trials,
unique paths/ranks/case-insensitive names, and at most one recommendation. Update
triggers make runs, results, comparisons, and events immutable. A deferred trigger
requires each new run to receive exactly one generated event in the same
transaction; event triggers enforce chronological valid transitions. Source-plan
deletion is restricted while history exists, while user erasure cascades through
the complete graph.

Selection changes never update the run. Each user choice or clear operation
appends an event after owner, membership, time-order, and expected-current-state
validation. This provides auditability and stale-decision protection without
mutating Phase 9 forecasts, Phase 10 plans, goals, contributions, or financial
records. Compact Monte Carlo sample buffers and private source facts are not
persisted; the stored seed, snapshot identity, methods, and aggregate evidence are
sufficient for controlled replay.

Definition ordinals preserve the three standard cases followed by the original
user-input order; comparison ranks remain separate decision evidence. This keeps
multi-alternative regeneration faithful even when ranking changes their display
order.

## 13. Checkpoint 11.12 — transactional simulation orchestration

`ScenarioSimulationService.simulate()` is the only public generation path. It
executes one owner-scoped chain using the request database transaction:

```text
validate bounded user alternatives
→ ScenarioEvidenceService.build()
→ analyze_scenario_decisions()
→ ScenarioSimulationRepository.create()
→ return the complete immutable run
```

Evidence and analysis complete before the repository adds a run. A validation,
evidence, solver, invariant, or storage error therefore cannot leave a partial
scenario graph. CPU-heavy analysis runs off the async event loop, while a
process-scoped guard permits at most two concurrent analyses, waits at most 250
milliseconds for capacity, and accepts at most five generation or regeneration
requests per authenticated owner in a rolling 60-second window. Rejected work
returns a bounded `429` response without revealing queue state or another owner.

`regenerate()` loads the prior run through the authenticated owner, reconstructs
only its stored user-defined assumptions, reuses the stored trial count and root
seed, freezes current cutoff-safe evidence, and persists a new immutable run. It
does not edit or delete the previous run. This gives reproducible stochastic
settings while allowing a newer trusted Phase 9/10 evidence cutoff to produce a
new decision record.

Retrieval and recent-history reads remain owner-scoped. Selection takes an owner
row lock and uses compare-and-set semantics: the caller must state the selection
it last observed. Selecting, switching, or clearing appends a new immutable event;
it never updates a scenario result or creates a transaction, contribution, plan,
forecast, or goal mutation.

## 14. Checkpoint 11.13 — authenticated scenario APIs

Six bearer-authenticated operations are exposed under
`/api/v1/scenario-simulations`:

| Method | Endpoint | Result |
|---|---|---|
| `POST` | `/api/v1/scenario-simulations` | Generate and persist one run |
| `GET` | `/api/v1/scenario-simulations` | List up to 100 compact recent summaries |
| `GET` | `/api/v1/scenario-simulations/{simulation_id}` | Retrieve full immutable evidence |
| `GET` | `/api/v1/scenario-simulations/{simulation_id}/compare` | Retrieve ranked comparisons and sensitivity |
| `POST` | `/api/v1/scenario-simulations/{simulation_id}/select` | Compare-and-set or clear the user choice |
| `POST` | `/api/v1/scenario-simulations/{simulation_id}/regenerate` | Create a replay-configured new run |

The generation body contains only a source plan identifier and one to ten strict
hypothetical alternatives. The server derives owner, cutoff, timezone, forecast
evidence, goals, trial count, root seed, probability and percentile methods,
optimization behavior, constraints, and all policy versions. Unknown fields are
rejected at every nested level. A selection target is required but nullable;
`null` explicitly means clear, while `expected_selected_scenario_id` guards stale
clients.

Full responses expose normalized assumptions, method and reliability labels,
seed and trial provenance, deterministic and empirical completion evidence,
completion-date percentiles, shortfall and tail-risk metrics, monthly capacity
and allocation summaries, comparison deltas, non-causal sensitivity signals,
decision scores, ranks, recommendations, warnings, policies, and append-only
events. They omit `user_id`, raw Monte Carlo paths, raw forecasts, accounts,
transactions, debts, and private evidence rows. History responses are compact;
request collections, horizons, trials, work units, list limits, and output graph
sizes all remain bounded. Foreign and missing run identifiers return the same
safe `404` contract.

## 15. Checkpoint 11.14 — monitoring, security, and release closure

Scenario operational telemetry uses policy version `2026.1` and a closed JSON
logging allowlist. Successful simulation events may contain only operation,
scenario-count band, horizon band, trial band, fixed probability method,
aggregate reliability, completion/risk bands, bounded result state, and duration.
Selection events contain only operation, result, and duration. Failures use only
closed reasons such as capacity exhausted, rate limited, evidence unavailable,
not found, or selection conflict.

Telemetry never includes identity, resource identifiers, scenario or goal names,
exact target amounts, exact capacities or allocations, assumptions, forecast
values, sampled paths, account data, transaction data, or debt data. The JSON
formatter drops all fields outside its reviewed allowlist.

Release closure covers request and response contracts, deterministic paths and
shocks, Phase 10 invariant reuse, uncertainty calibration, seeded Monte Carlo,
probability denominators, percentiles, tail loss, comparison, sensitivity,
dominance and ranking, persistence and replay, lifecycle races, authentication,
owner isolation, OpenAPI security, bounded work, and privacy-safe monitoring.
The real PostgreSQL lifecycle exercises service-level generation, selection,
clear, regeneration, immutable triggers, owner hiding, recent history, source-plan
protection, and user-erasure cascade. Migration upgrade and downgrade, the full
backend regression, coverage gate, hooks, compilation, container build, and
Compose smoke test remain mandatory release gates.

Phase 11 implementation is complete on its feature branch only after those gates
pass. Project completion is declared after the final pull request is squash-merged
into `develop`.

## 16. Security and integrity established through Phase 11

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
- Standard reference bands remain server-owned.
- Missing income or expense evidence makes dependent scenarios unavailable.
- Shock arithmetic is exact, bounded, ordered, and period-reconciled.
- Debt-payment changes adjust only the delta and cannot double-count the baseline.
- Pauses and contribution bounds are enforced by both solver and fallback.
- Phase 10 goal, deadline, capacity, and emergency-reserve invariants are reused.
- Scenario evaluation never changes its source plan or observed financial data.
- Calibration uses validation-derived bands and excludes final-test metrics.
- Raw validation residuals and private transaction values are never copied.
- Sampling distributions are bounded by the stored Phase 9 95% interval.
- Seeds, policy versions, methods, reliability, and sample digests are explicit.
- Common random numbers provide order-independent alternative comparison.
- Negative savings is measured before capacity is safely clipped to zero.
- Hard contribution and reserve constraints are never probabilistically relaxed.
- Trial counts, seeds, horizons, scenario counts, and total work are bounded.
- Monte Carlo samples use compact buffers and are not logged or persisted.
- Decision scores, dominance, ranks, deltas, and identifiers are recomputed and
  validated before persistence.
- Sensitivity signals are bounded, reconciled to 100, and labelled non-causal.
- Composite foreign keys enforce the same owner across source plans and all
  simulation children.
- Exact-money, probability, event-transition, and generated-event invariants are
  database-enforced.
- Immutable update triggers protect runs, outcomes, comparisons, and history.
- Selection state is derived from append-only events and guarded against stale
  concurrent decisions.
- User erasure cascades through scenario history; source-plan deletion is
  restricted while reproducibility evidence exists.
- Public generation accepts only bounded hypothetical inputs and derives all
  trusted identity, evidence, algorithms, random settings, and policies.
- Generation and regeneration have bounded concurrency, queue wait, per-owner
  request rate, trial count, horizon, alternatives, and total work.
- Selection uses an owner row lock and compare-and-set expected state.
- Public responses omit owner identity, raw samples, and private financial rows.
- Structured telemetry is constrained by closed enums, aggregate bands, and a
  JSON formatter allowlist.

## 17. Validation boundary

Batch 1 validation covers domain and Pydantic assumption limits, immutability,
server-field rejection, unique alternatives and goals, owner-scoped repository
calls, deterministic hashing, exact forecast-to-plan reconciliation, future-data
rejection, source lifecycle rules, out-of-horizon adjustments, unknown goals,
missing forecasts, and a real PostgreSQL owner-isolation scenario added to the
existing goal-plan lifecycle test.

Batch 2 adds deterministic-reference, ordered-shock, recovery, clipping,
reconciliation, emergency-reserve, contribution-bound, infeasibility, HiGHS,
guarded-fallback, exact-delta, and repeatability tests. Phase 10 regression tests
verify that optional allocation bounds do not alter existing callers.

Batch 3 adds calibration eligibility and reliability tiers, final-test leakage
exclusion, fallback point masses, ordered bounded knots, exact seeded equality,
common-random-number behavior, default and maximum trial limits, work-budget and
finite-output checks, blocked/unavailable handling, raw-negative detection,
compact-buffer bounds, probability denominators, nearest-rank percentiles,
reserve coverage, tail loss, method labels, and robustness-score coverage. The
real PostgreSQL owner-isolation lifecycle also executes the stochastic risk path.

Batch 4 adds deterministic comparison replay, conservative tie-breaking,
dominance, exact deltas, sensitivity reconciliation, contribution-burden,
tamper-rejection, model/metadata, owner-scoped repository, append-only selection,
stale-race, Alembic upgrade/downgrade, immutable-trigger, source-plan deletion,
stored-seed/snapshot reproducibility, and user-erasure-cascade coverage. The real
PostgreSQL lifecycle validates the complete Phase 10-to-Phase 11 persistence
boundary.

Batch 5 adds orchestration success and failure atomicity, complete stored-
assumption reconstruction, deterministic replay configuration, concurrency and
per-owner request limiting, owner-hidden retrieval, stale selection conflicts,
all six authenticated routes, strict nested request rejection, compact history,
full response serialization, OpenAPI bearer security, safe application errors,
telemetry banding and privacy allowlisting, service-level PostgreSQL lifecycle,
full regression, coverage, repository hygiene, and operational release checks.

## 18. Phase boundary after closure

Phase 11 adds no generative financial explanation, conversational assistant,
retrieval-augmented generation, autonomous action, background scheduling,
notification, or frontend. Phase 12 owns grounded explanation and assistant
behavior. Phase 13 owns production-wide distributed throttling, scheduled work,
notifications, frontend integration, deployment, and operations.
