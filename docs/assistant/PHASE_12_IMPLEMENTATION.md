# Phase 12 — Grounded AI Assistant

Status: Batches 1–3 implemented on `feat/phase-12-grounded-assistant-foundation`.

This cumulative record freezes the approved Phase 12 semantics. Checkpoints
12.0–12.2 establish the provider-neutral architecture, closed assistant scope,
strict answer and citation contracts, evidence-source authorization, prompt data
allowlists, and threat model. Checkpoints 12.3–12.5 add owner-scoped structured
retrieval, curated public knowledge persistence, PostgreSQL full-text search, and
deterministic reranking. Checkpoints 12.6–12.8 add canonical evidence packets, a
provider-neutral structured model adapter, and claim-level grounded answers.
Conversation persistence, public routes, end-to-end orchestration, and monitoring
remain intentionally absent until their approved batches.

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

## 6. Checkpoint 12.3 — owner-scoped structured evidence registry

`AssistantEvidenceRegistry.retrieve()` is the only source-dispatch boundary. It
authorizes the complete unique source set before an adapter is called, requires
the authenticated owner for every private source, bounds requests and results,
and rejects missing adapters, cross-source output, duplicate evidence identities,
and oversized result sets.

Five private adapters reuse the existing authoritative application or repository
paths:

- analytics calls the live owner-scoped dashboard service and removes account
  identifiers before producing cash-flow and spending aggregates;
- forecasts load one owner-scoped immutable Phase 9 run and expose validation
  quality, points, confidence bands, model provenance, and uncertainty;
- goal progress calls the exact Phase 10 contribution/progress service;
- goal plans load one owner-scoped immutable Phase 10 schedule and safety result;
- scenarios load one owner-scoped immutable Phase 11 decision graph.

Every `AssistantEvidenceRecord` is deeply immutable, prompt-allowlisted, bounded,
time-cutoff aware, reliability-labelled, versioned, and assigned a canonical
SHA-256 identity. Foreign and missing persisted resources produce no record. The
model receives no repository, database connection, owner key, raw account, raw
transaction, final-test forecast metric, or financial write capability.

## 7. Checkpoint 12.4 — curated knowledge ingestion and persistence

Curated educational knowledge is deliberately separate from owner data. Offline
ingestion accepts a reviewed HTTPS source, lowercase slug, explicit version,
closed topic set, timezone-aware publication time, and bounded normalized
Markdown. Deterministic heading-aware chunking produces at most 200 chunks of at
most 4,000 characters with SHA-256 content identities.

Two PostgreSQL tables store document provenance and bounded chunks. Documents
are immutable except for one chronological retirement transition; chunks are
fully immutable. Database constraints enforce source, slug, version, topic,
hash, ordering, length, and retirement rules. A generated weighted `tsvector`
and GIN index support lexical retrieval. Retired or future-published versions are
excluded. The index contains no user identity, account, transaction, statement,
forecast, goal, scenario, conversation, prompt, model response, or embedding.

## 8. Checkpoint 12.5 — bounded retrieval and deterministic reranking

`AssistantKnowledgeService.retrieve()` normalizes a bounded lexical query and
selects only active documents at the trusted retrieval cutoff. PostgreSQL
`websearch_to_tsquery` and `ts_rank_cd` produce at most 50 candidates. Optional
closed-topic filtering is applied in SQL before results leave the repository.

`rerank_knowledge_candidates()` then combines transparent fixed signals: full-
text score, token overlap, title match, heading match, exact phrase match, and
topic match. It performs no model call and uses stable publication, slug, version,
ordinal, and chunk-ID tie-breaking. Returned hits contain a bounded score and
reason codes. The raw question is not persisted; provenance records only a query
digest, retrieval cutoff, policy version, ordered public chunk identities, and a
canonical retrieval ID.

`KnowledgeEvidenceAdapter` maps each hit into the same immutable allowlisted
evidence contract as structured evidence. Retrieved document text remains quoted
evidence and never becomes executable instruction. No semantic embedding or
external vector service is used; `pgvector` remains conditional on a later fixed
evaluation showing a material improvement over this lexical baseline.

## 9. Batch 2 security and integrity invariants

- Source authorization completes before any adapter query.
- The authenticated owner is forwarded unchanged to every private data access.
- Missing and foreign persisted resources are indistinguishable empty evidence.
- Adapter output cannot change its registered source family.
- Evidence payloads pass the recursive prompt allowlist before receiving an ID.
- Private identifiers and final-test forecast metrics are excluded from prompts.
- Public knowledge requires HTTPS provenance, explicit version, and closed topics.
- Knowledge chunks are deterministic, bounded, hashed, and database-immutable.
- Only active, already-published knowledge versions can be retrieved.
- Full-text candidate count, final result count, text size, and nesting are bounded.
- Reranking is deterministic, transparent, provider-free, and replayable.
- Query text is not stored in knowledge rows or retrieval provenance.
- Raw financial evidence is never inserted into a full-text or embedding index.
- Retrieved instructions cannot modify authorization, safety, tools, or policy.

## 10. Checkpoint 12.6 — immutable evidence packets and context builder

`build_evidence_packet()` re-authorizes the complete server-selected source set
using the authenticated owner and then deliberately drops that owner identity.
The resulting `AssistantEvidencePacket` contains only the normalized question,
closed intent, retrieval cutoff, requested and missing sources, policy versions,
reliability, bounded evidence facts, token budgets, and canonical provenance.

The packet builder rejects future cutoffs, duplicate evidence identities,
unrequested sources, ambiguous current versions, unsupported intents, and missing
intent-defining source requests. When the same source resource has older and newer
records, only the latest compatible record is retained. Missing core evidence is
explicit and makes the packet ineligible for generation; missing optional evidence
remains visible as a limitation. Source-specific staleness is recorded rather than
silently hidden.

System generation rules, untrusted user input, retrieval metadata, and typed
evidence facts occupy separate model-payload sections. Exact financial values stay
inside evidence facts and are never converted into explanatory prose by the packet
builder. Nested data is immutable, total serialized context is limited to 64,000
characters, input and output token budgets are fixed, and SHA-256 over canonical
content gives every replayable packet a deterministic identity.

## 11. Checkpoint 12.7 — provider-neutral structured model boundary

`AssistantModel.generate()` is the only generation protocol. The default
`DisabledAssistantModel` fails closed, while `StructuredAssistantModel` can wrap
an approved deployment transport without exposing provider credentials, headers,
SDK objects, or endpoints to application services. The transport receives no
tools and therefore cannot write financial data or call backend services.

`AssistantModelConfiguration` fixes a low temperature of at most 0.2, a maximum
60-second deadline, bounded input and output tokens, a cost ceiling, and at most
two explicitly transient retries. Timeouts are not retried. Cancellation remains
native, and no response or conversation persistence occurs inside this boundary.
Measured token and cost usage is checked again after the provider returns.

The provider must return one strict JSON object containing typed claims and safe
follow-up questions. Unknown fields, duplicate JSON keys, hidden reasoning,
unrecognized claim kinds, invalid evidence identities, unbounded text, malformed
JSON, and citations outside the packet are rejected. The model cannot choose the
public answer status, reliability, warnings, policy versions, or final citation
metadata. A deterministic transport double supports tests without any external
network or vendor SDK.

## 12. Checkpoint 12.8 — claim-level grounding and citations

Every generated claim declares one of five meanings: observation, forecast, plan,
simulation, or education. The grounding layer requires at least one cited source
that is authoritative for that meaning. It rejects packet-external references and
any numeric value that is absent from the specifically cited evidence. Formatting
normalization supports currency separators and evidence-backed percentage display,
but it does not derive new balances, probabilities, gaps, or recommendations.

FALCON, not the model, creates stable `[1]` citation markers, citation objects,
evidence summaries, worst-case reliability, stale/incomplete warnings, and the
`answered` or `limited` disposition. Claim labels visibly distinguish current
observations, forecasts, plans, simulations, and general education. Generated
guarantees, risk-free language, product buy/sell instructions, money-transfer
directions, system-prompt requests, and instruction-override language fail closed.

If intent-defining evidence is unavailable,
`GroundedAssistantGenerator.generate()` does not call a provider. It returns the
deterministic `unavailable` answer with `insufficient_evidence`. Valid answers
remain decision-support explanations and always carry the
`not_financial_advice` warning.

## 13. Batch 3 grounding and provider invariants

- The packet never stores or serializes the authenticated owner identity.
- Packet instructions and untrusted user text are structurally separated.
- Only the newest unambiguous version of one evidence resource enters a packet.
- Missing required evidence prevents every model call.
- Provider transports receive strict budgets, a response schema, and no tools.
- No provider secret, endpoint, raw response, or hidden reasoning enters a public
  answer.
- Only explicitly transient transport failures are retried; timeouts are not.
- The model can cite only canonical evidence identities already in its packet.
- Every material claim has a declared evidence meaning and at least one citation.
- Every generated number must exist in the claim's cited evidence.
- Citations, reliability, warnings, and answer status are server-derived.
- Unsupported numbers, source mismatches, guarantees, and financial actions are
  rejected before an answer can be returned.
- No Batch 3 component persists a question, packet, provider response, or answer.

## 14. Deferred checkpoints

- 12.9–12.11: conversation and audit persistence, full prompt-injection controls,
  post-generation verification, and RAG evaluation;
- 12.12–12.14: end-to-end retrieval/generation orchestration, authenticated APIs,
  monitoring, integration, and release closure.

Batches 1–3 deliberately add no conversation table, embedding, public assistant
endpoint, assistant response persistence, operational logging event, provider SDK,
or configured external network call. The only Phase 12 database tables continue to
hold curated public knowledge.
