# Phase 12 — Grounded AI Assistant

Status: Batch 1 implemented locally on `feat/phase-12-grounded-assistant-foundation`.

This cumulative record freezes the approved Phase 12 semantics. Checkpoints
12.0–12.2 establish the provider-neutral architecture, closed assistant scope,
strict answer and citation contracts, evidence-source authorization, prompt data
allowlists, and threat model. Retrieval, model invocation, persistence, public
routes, and monitoring remain intentionally absent until their approved batches.

## 1. Phase boundary

Phase 12 explains trusted FALCON evidence. It does not replace the calculations
implemented by analytics, forecasting, goal optimization, or scenario simulation.
It cannot edit a profile, account, transaction, budget, goal, contribution,
forecast, plan, scenario, or selection, and it cannot move money.

The language model will receive only a bounded evidence packet produced by
owner-scoped application services. It will have no database connection and no
financial write tools. A generated financial answer must be cited and must survive
post-generation grounding verification before it is returned.

Phase 13 owns the React assistant surface, streaming presentation, distributed
rate limiting, scheduled work, notifications, and deployment operations.

## 2. Checkpoint 12.0 — readiness and architecture

The Phase 11 squash merge is the trusted starting tree. Phase 8 provides
analytics and insight evidence, Phase 9 provides versioned forecasts and
uncertainty, Phase 10 provides immutable optimized goal plans, and Phase 11
provides immutable scenario comparisons. Those capabilities remain authoritative.

ADR 0004 fixes the architecture:

- structured PostgreSQL retrieval for exact owner financial evidence;
- curated knowledge retrieval through PostgreSQL metadata and full-text search;
- optional `pgvector` only after measured retrieval improvement;
- no MongoDB or standalone vector database by default;
- no raw financial rows or private samples in an embedding index;
- a provider-neutral future `AssistantModel` boundary;
- generation disabled when no approved provider is configured;
- strict structured output with timeout, token, cost, retry, and size limits;
- no financial write tools or autonomous actions.

All Batch 1 policies use version `2026.1`. No LLM SDK, vector extension,
migration, provider credential, or public endpoint is added in this batch.

## 3. Checkpoint 12.1 — intents and response contract

The closed intent taxonomy is:

| Intent | Purpose |
|---|---|
| `explain_dashboard` | Explain a dashboard metric or summary |
| `explain_financial_health` | Explain score factors and limitations |
| `summarize_spending` | Explain bounded aggregate spending evidence |
| `explain_spending_signal` | Explain a leak, anomaly, or recurring signal |
| `explain_forecast` | Explain forecast values, bands, quality, and warnings |
| `explain_goal_progress` | Explain progress and required contribution |
| `explain_goal_plan` | Explain an immutable Phase 10 plan |
| `compare_scenarios` | Explain Phase 11 alternatives and risk |
| `financial_education` | Answer from curated non-product knowledge |
| `unsupported` | Produce a bounded refusal |

Answers have four dispositions:

- `answered` for grounded evidence with available reliability;
- `limited` when the answer is grounded but evidence is provisional or constrained;
- `unavailable` when verified evidence is insufficient;
- `refused` when the request violates scope or safety policy.

`AssistantAnswer` requires intent, disposition, bounded answer text, evidence
summary, citations, reliability, warnings, suggested follow-up questions, and the
contract and safety policy versions. Generated answers require cited evidence and
cannot carry a refusal reason. Unavailable and refused responses require
`unavailable` reliability and a closed reason. Insufficient evidence is distinct
from a policy refusal.

Each `AssistantCitation` contains only a closed source family, bounded opaque
reference, human label, timezone-aware cutoff, policy version, and available
reliability. Duplicate citations, summaries, suggestions, and warnings are
rejected.

`AssistantQuestionRequest` accepts only one trimmed question of at most 2,000
characters. Clients cannot submit owner, intent, cutoff, evidence, model, prompt,
provider, algorithm, policy, or reliability fields. `AssistantAnswerResponse`
does not contain user identity, raw evidence, prompts, provider metadata, or
hidden reasoning.

## 4. Checkpoint 12.2 — privacy, authorization, and threats

The evidence registry reserves six source families:

| Source | Owner required | Purpose |
|---|---:|---|
| `analytics` | Yes | Cash flow, spending, health, and insights |
| `forecast` | Yes | Forecast points, bands, models, and quality |
| `goal_progress` | Yes | Goal progress and required contribution |
| `goal_plan` | Yes | Phase 10 schedule, outcomes, and safety evidence |
| `scenario_simulation` | Yes | Phase 11 probabilities, comparisons, and sensitivity |
| `knowledge` | No | Curated methodology and financial education |

`authorize_evidence_sources()` runs before repository retrieval. It accepts the
resolved intent, requested source families, and authenticated owner. Sources must
be unique, allowed for the intent, and owner-backed when private. The unsupported
intent authorizes no source.

`prompt_safe_payload()` applies a closed top-level allowlist for each source and
recursively rejects forbidden private fields. It also bounds text, collection
size, nesting depth, and numeric finiteness, and rejects arbitrary objects.

Forbidden prompt fields include identity, email, passwords, password hashes,
access and refresh tokens, account and transaction identifiers, account numbers,
masked references, raw transactions, statements, rows, Monte Carlo samples, raw
prompts, system prompts, and chain-of-thought.

The threat model covers exactly:

1. cross-owner access;
2. user prompt injection;
3. retrieved instruction injection;
4. data exfiltration;
5. secret exposure;
6. raw financial embedding;
7. ungrounded financial claims;
8. prohibited financial actions;
9. unsafe product advice and guaranteed outcomes;
10. raw prompt logging; and
11. chain-of-thought exposure.

Every threat records both a control and the executable verification required
before Phase 12 can close.

## 5. Batch 1 security invariants

- The authenticated owner is never accepted from assistant request data.
- Every private evidence source requires owner scope before retrieval.
- Intent determines which evidence families may be queried.
- Raw accounts and transactions are not assistant evidence source families.
- Raw financial data is not embedded or semantically indexed.
- Generated answers require evidence summaries and citations.
- Missing evidence produces `unavailable`, not a guess.
- Unsupported or unsafe requests produce a bounded refusal.
- Unavailable evidence cannot be cited.
- Citation cutoffs must be timezone-aware.
- Provider, model, prompt, policy, and evidence selection remain server-owned.
- Public schemas exclude raw prompts, system instructions, secrets, owner identity,
  private identifiers, provider data, and hidden reasoning.
- Retrieved documents are evidence and never executable instructions.
- The assistant has no financial write capability.

## 6. Deferred checkpoints

- 12.3–12.5: evidence registry adapters, curated knowledge ingestion, retrieval,
  and reranking;
- 12.6–12.8: evidence packet construction, provider adapter, grounded generation,
  and citations;
- 12.9–12.11: conversation persistence, injection controls, verification, and RAG
  evaluation;
- 12.12–12.14: orchestration, authenticated APIs, monitoring, integration, and
  release closure.

Batch 1 deliberately adds no conversation table, knowledge table, embedding,
model invocation, retrieval query, public assistant endpoint, logging event, or
external network call.
