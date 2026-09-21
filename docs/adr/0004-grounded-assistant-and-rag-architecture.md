# ADR 0004: Grounded Assistant and RAG Architecture

- Status: Accepted
- Date: 2026-09-21
- Decision owners: FALCON development team
- Related phase: Phase 12
- Supersedes: None
- Superseded by: None

## Context

Phases 8 through 11 now produce authenticated, owner-scoped analytics,
forecasts, optimized goal plans, and scenario decisions. Those services own all
financial calculations and expose explicit cutoff, reliability, warning, method,
and policy provenance. Phase 12 must explain that evidence conversationally
without letting a language model invent balances, probabilities, allocations, or
financial outcomes.

The project baseline requires an assistant that uses authenticated user data only
with permission, explains dashboard values and recommendations, answers from
backend-calculated results, avoids invented financial facts, and communicates
uncertainty. Conversation history, retrieval records, citations, and safety
metadata require an explicit privacy decision before persistence is introduced.

## Decision drivers

- financial values must remain authoritative and exactly reproducible;
- private evidence must never cross ownership boundaries;
- material financial claims must be traceable to a source;
- prompt injection and retrieved-document injection must fail safely;
- providers must remain replaceable and disabled when not configured;
- model, token, latency, and cost limits must be bounded;
- no assistant capability may move money or mutate financial records;
- the design must fit the existing FastAPI and PostgreSQL modular monolith;
- the four-person team should not operate unnecessary infrastructure.

## Decision

### 1. Calculation and language remain separate

FALCON services remain authoritative for every number. The language model may
summarize and explain retrieved evidence but cannot recompute a balance, forecast,
goal probability, optimized allocation, scenario score, or recommendation.

The assistant receives an immutable evidence packet rather than database access.
It receives no financial write tools and cannot create transactions,
contributions, plans, approvals, transfers, or account changes.

### 2. Two retrieval paths

Private financial evidence uses structured, owner-scoped PostgreSQL repository
queries over existing Phase 8–11 records. Exact SQL retrieval is authoritative
for values, cutoffs, reliability, methods, warnings, and policy versions.

General explanatory knowledge uses a separate curated document index. Initial
retrieval will use PostgreSQL metadata and full-text search. An embedding index
using `pgvector` may be added only after a fixed evaluation set shows a material
retrieval improvement. MongoDB and a standalone vector database are not added.

Raw accounts, statements, transactions, credentials, Monte Carlo samples, or
arbitrary user rows are never embedded. Knowledge documents are treated as
untrusted evidence and cannot supply system instructions.

### 3. Provider-neutral model boundary

The application layer depends on an `AssistantModel` protocol, not a provider
SDK. The provider-neutral adapter added in Checkpoint 12.7 accepts a bounded
evidence packet and returns a strict structured response. It enforces timeout,
cancellation, token, cost, retry, and output-size limits.

No provider is required to import or start the API. Generation remains disabled
when no approved provider is configured. Provider names, credentials, raw prompts,
responses, and request bodies never enter operational logs.

Low-temperature structured generation is the default. Provider-specific features
cannot weaken the shared answer, citation, privacy, or safety contract.

### 4. Closed assistant scope

The first assistant supports explanations of dashboard metrics, financial health,
spending summaries and signals, forecasts, goal progress, goal plans, scenario
comparisons, and curated financial education.

Product-specific investment recommendations, guaranteed outcomes, money movement,
credential access, other-user data, instruction disclosure, and unsupported
actions receive bounded refusals. Missing evidence receives an unavailable answer
rather than a guessed response.

### 5. Evidence and citations

Every material generated financial answer requires at least one evidence summary
and one source citation. Each citation records a closed source family, bounded
reference, human label, timezone-aware cutoff, policy version, and reliability.

The evidence packet records retrieval provenance and a canonical identity.
Checkpoint 12.8 performs the first mandatory claim/source, number, and citation
checks. Checkpoint 12.11 adds the complete post-generation verification and
evaluation gate before an answer can be persisted or publicly served.

### 6. Privacy and authorization

The authenticated owner is supplied by the application boundary and is never
accepted from an assistant request. Each private evidence family requires owner
scope. Curated public knowledge is the only source that can be retrieved without
an owner.

Every evidence family has a closed top-level prompt allowlist. Forbidden fields
are rejected recursively, including identity, email, credentials, tokens,
account and transaction identifiers, raw statements, raw rows, raw samples, raw
prompts, system prompts, and hidden reasoning.

The user question is client-provided content, not trusted instruction. It will be
bounded and excluded from operational telemetry. Retention, deletion, and
conversation persistence remain deferred to Checkpoint 12.9.

### 7. Threat model

Phase 12 reserves explicit controls for cross-owner access, prompt injection,
retrieved instruction injection, data exfiltration, secret exposure, raw financial
embedding, ungrounded financial claims, prohibited financial actions, unsafe
financial advice, raw prompt logging, and chain-of-thought exposure.

All threats require executable verification before Phase 12 closure.

### 8. Operational boundaries

Question, answer, evidence, citation, history, token, concurrency, rate, latency,
and retrieval sizes will be bounded. Streaming, frontend integration, distributed
rate limiting, scheduled execution, and notifications belong to Phase 13.

## Alternatives considered

### Let the model query PostgreSQL directly

Rejected because it would bypass owner-scoped repositories, prompt allowlists,
stable evidence contracts, and deterministic calculation boundaries.

### Embed all user financial records

Rejected because raw financial embeddings increase disclosure, deletion,
reconciliation, staleness, and cross-owner isolation risk without improving exact
numeric retrieval.

### Add MongoDB or a standalone vector database immediately

Rejected because PostgreSQL already owns the data and supports metadata,
full-text, and an optional measured `pgvector` extension. Additional
infrastructure is not justified before retrieval evaluation.

### Adopt a provider SDK throughout the application

Rejected because provider types, retries, errors, and output semantics would leak
into routes and domain policy.

### Permit assistant-initiated financial writes

Rejected. Phase 12 is explanation and question answering only. Any future action
capability requires a separate approval, authorization, confirmation, and audit
contract.

## Consequences

- Phase 12 can be fully tested with a deterministic model double.
- Changing providers does not change public or persistence contracts.
- Exact user values remain in owner-scoped PostgreSQL retrieval rather than a
  semantic index.
- RAG quality must be measured; embeddings are optional, not assumed.
- Some questions will correctly return unavailable or refused responses.
- Conversation storage and the real provider adapter require later approved
  checkpoints.
