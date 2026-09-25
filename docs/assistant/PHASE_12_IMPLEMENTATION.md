# Phase 12 — Grounded AI Assistant

Status: Phase 12 complete and squash-merged into `develop` through PR #61
(`464e7c84d890944b69cf2a6cc10c6d0b9f481980`).

This cumulative record freezes the approved Phase 12 semantics. Checkpoints
12.0–12.2 establish the provider-neutral architecture, closed assistant scope,
strict answer and citation contracts, evidence-source authorization, prompt data
allowlists, and threat model. Checkpoints 12.3–12.5 add owner-scoped structured
retrieval, curated public knowledge persistence, PostgreSQL full-text search, and
deterministic reranking. Checkpoints 12.6–12.8 add canonical evidence packets, a
provider-neutral structured model adapter, and claim-level grounded answers.
Checkpoints 12.9–12.11 introduce encrypted owner-scoped conversation history,
adversarial safety screening, final verification, and offline RAG evaluation.
Checkpoints 12.12–12.14 complete atomic orchestration, authenticated APIs,
idempotency, privacy-safe monitoring, measured end-to-end evaluation, and the
Phase 12 release boundary.

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

## 14. Checkpoint 12.9 — encrypted conversation and audit persistence

Alembic revision `e8c2a6d1f704` adds three private PostgreSQL tables:
`assistant_conversations`, `assistant_conversation_turns`, and
`assistant_audit_events`. Composite foreign keys bind every turn and audit row
to the same authenticated owner as the conversation. Database triggers reject
updates; deletes are permitted for retention and privacy erasure, with database
cascades removing turns and audit records. Missing and foreign conversations
have indistinguishable empty results. Concurrent appends lock the conversation
and assign an ordinal from 1 to 50. Recent history is capped at 20 turns.

`AssistantHistoryService` requires an injected Fernet key ring and fails closed
without it. Only the user's bounded question and the *verified public answer*
are encrypted and stored. The first key encrypts new turns; up to two older keys
can decrypt history during rotation. Configuration and secure key storage belong
to the server deployment, not the client, database, prompt, or audit table.
Audit records hold only owner, conversation and turn IDs, packet/evidence hashes,
status, model ID, prompt and safety policy versions, elapsed time, and token
usage. They contain no
question, answer, raw evidence, provider response, credential, or hidden
reasoning. The turn also records the generation prompt-policy version.

Conversations expire 90 days after creation. `purge_expired()` erases at most
1,000 conversations per call; Phase 13 must schedule it. Owner-initiated
`delete()` and `erase_user()` are immediately available and erase audit rows as
well as history. User-account deletion cascades to all assistant records.
The application transaction must commit each write or deletion. No public
history API or configured encryption key is introduced in Batch 4.

## 15. Checkpoint 12.10 — untrusted input and financial safety

`screen_question()` is the pre-retrieval gate for the Checkpoint 12.12
orchestration flow. It detects override attempts, other-user
disclosure, credential access, financial writes, securities-product instructions,
and guaranteed outcomes. The generation boundary repeats screening after packet
construction. `screen_packet()` treats all retrieved evidence as data and refuses
retrieved instructions in evidence facts and labels before a model call. A
refusal has a closed reason, no citations, and no provider usage. Generated
claims and follow-up questions are
also screened for prompt disclosure, private email, token, and account leakage.
Models still receive no write tools; deterministic screening is a conservative
layer, not a proof that arbitrary prose is safe. The labelled adversarial cases
in Checkpoint 12.11 must pass before public release.

## 16. Checkpoint 12.11 — final verification and offline RAG evaluation

`verify_model_output()` is called by the generator and the public grounding
helper. It retains the Checkpoint 12.8 claim/source and numeric checks, then
requires displayed currency symbols, codes, and percentages to be backed by
the claim's authoritative cited source. It checks server-owned citation markers
and summaries,
stale/incomplete evidence warnings, prediction certainty language, and leakage
in both claims and follow-up questions. A failed check raises a bounded error;
`AssistantHistoryService` accepts only verified results.

`evaluate_assistant()` replays bounded labelled packets and deterministic model
outputs without a provider or private dataset. It reports retrieval precision
and recall, citation precision and recall, faithfulness of verified outputs,
unsupported-claim rate, refusal accuracy, leakage and verification block rates,
fixture latency p95, and average fixture token usage. The initial release gate
requires retrieval precision ≥0.80, recall ≥0.90, citation precision/recall 1.00,
fixture latency p95 ≤5 seconds, average input/output tokens ≤16,000/1,500,
and all labelled valid, refused, and adversarial cases handled correctly. It
requires at least one positive, refusal, and leakage case. Missing retrieved
evidence remains in the recall denominator. These are **offline fixture
metrics**; live latency, provider accuracy, and semantic entailment require
measured end-to-end evaluation in Checkpoints 12.12–12.14.

## 17. Batch 4 security and privacy invariants

- Owner predicates protect every history read, append, and deletion.
- Same-owner composite keys also enforce turn and audit ownership in PostgreSQL.
- Retained rows cannot be updated; erasure and 90-day expiry delete all related
  private history and audit data.
- Conversation text is encrypted before a database write. No key is stored in
  the database, prompt, audit log, or repository.
- Generation cannot persist without a successful final verification result.
- A blocked input or retrieved instruction never reaches a model transport.
- Financial write requests, product-specific advice, guaranteed outcomes, and
  private disclosure requests receive bounded refusals.
- The offline evaluation report contains only aggregate metrics, never prompts
  or evidence text.

## 18. Checkpoint 12.12 — atomic assistant orchestration

`GroundedAssistantOrchestrator.send_message()` owns the complete request chain:

1. enforce the per-owner process-local rate and concurrency limits;
2. lock the owner-scoped live conversation and resolve message idempotency;
3. classify the question with the closed deterministic intent classifier;
4. screen unsafe or unsupported input before evidence retrieval;
5. select resource IDs, source families, knowledge topics, timezone, and currency
   on the server;
6. authorize and retrieve structured financial and curated knowledge evidence;
7. build the bounded owner-free packet;
8. generate through the provider-neutral model boundary;
9. run final safety, citation, numeric, unit, and grounding verification;
10. encrypt and append the verified public exchange and content-free audit row;
11. return only after the request transaction can commit.

The deterministic planner chooses the current owner-scoped forecast, named or
highest-priority goal, current goal plan, and current scenario graph through the
existing repositories. Clients cannot submit an owner, intent, source family,
resource ID, cutoff, topic, model, policy, prompt, or reliability. Missing
resources use an owner-scoped empty lookup so packet construction can explicitly
mark required evidence unavailable instead of guessing.

The request session is the single transaction boundary. The conversation row is
locked before retrieval or provider work, so concurrent messages in one
conversation cannot receive ambiguous ordinals. Cancellation propagates normally;
an overall deadline converts timeout to a safe service error and causes rollback.
Provider unavailability, budget failure, malformed output, and verification
failure never append partial history.

Every message POST requires a bounded `Idempotency-Key`. Only its SHA-256 digest
is stored. A unique conversation/digest constraint makes a completed retry return
the original decrypted exchange, while reuse for a different question returns a
safe conflict. Process-local throttling is deliberately bounded; Phase 13 owns a
distributed limiter.

## 19. Checkpoint 12.13 — authenticated owner-only APIs

The non-streaming Phase 12 API is mounted under `/api/v1/assistant/conversations`:

| Method and path | Behavior |
|---|---|
| `POST /assistant/conversations` | Create a 90-day encrypted owner conversation |
| `GET /assistant/conversations` | List at most 20 live owner conversations |
| `GET /assistant/conversations/{conversation_id}` | Read at most 20 recent decrypted owner turns |
| `POST /assistant/conversations/{conversation_id}/messages` | Atomically produce and persist one verified grounded answer |
| `GET /assistant/conversations/{conversation_id}/messages/{message_id}/citations` | Read the verified owner-only public citations |
| `DELETE /assistant/conversations/{conversation_id}` | Erase the conversation, turns, and audit rows |

Every operation uses mandatory Bearer authentication and the trusted principal's
owner ID, timezone, and default currency. Foreign, expired, and missing resources
share the same 404 behavior. Message requests accept only `question`; the
idempotency key is a required header. New messages return 201, exact retries return
200, and bounded 404, 409, 422, 429, and 503 responses use the shared safe error
contract. OpenAPI records Bearer security and excludes provider configuration,
raw evidence, hidden reasoning, and streaming.

The configured history key ring is server-only, contains one to three Fernet
keys, and uses the first key for new ciphertext. Production rejects the development
placeholder and reuse of the authentication-delivery key. The API starts without
an external provider SDK or credential; an approved `AssistantModel` is injected
at the composition root. With no approved model, generated requests fail closed
with 503 while deterministic refusals and insufficient-evidence responses remain
available.

## 20. Checkpoint 12.14 — monitoring, measured evaluation, and closure

`AssistantMonitor` emits only low-cardinality aggregate fields: intent, source
types, evidence-count band, answer status, closed refusal/failure reason, citation
count, token bands, elapsed milliseconds, policy version, and provider outcome.
It never receives or logs an owner ID, question, answer, exact financial value,
raw prompt, evidence row, citation content, provider/model identifier, endpoint,
credential, response, or chain-of-thought. The structured logger allowlist contains
only those approved fields.

`evaluate_end_to_end_assistant()` complements the offline Checkpoint 12.11 replay.
It runs labelled generated, refused, and unavailable packets through the actual
configured `GroundedAssistantGenerator`, measures adapter latency and token usage,
and reports only aggregate outcome accuracy, citation precision/recall, provider
failure rate, latency p95, and mean token use. Release requires exact labelled
outcomes, citation precision/recall 1.00, no provider failures, latency p95 at most
5 seconds, and mean input/output usage at most 16,000/1,500 tokens. Provider
timeout, malformed output, retrieval error, prompt injection, leakage, ownership,
retention, deletion, migration, authentication, and OpenAPI paths are also covered
by executable regression tests.

Alembic revision `f2a7c9e4d816` adds the bounded idempotency digest and unique
conversation boundary without storing the original key. The application factory,
environment example, and Compose service wire encryption and process-local
operational limits. The default provider remains disabled in accordance with ADR
0004, so no secret or external network dependency is needed for startup or tests.

## 21. Batch 5 release invariants

- The only execution order is classify, authorize, retrieve, packetize, generate,
  verify, persist, and return.
- A refusal is decided before retrieval and never calls a provider.
- A missing required source never calls a provider and returns `unavailable`.
- Server code, never request data, selects owners, resource IDs, evidence sources,
  topics, timezone, currency, policies, model, and budgets.
- A timeout, cancellation, malformed response, failed verification, or database
  failure cannot leave a partial conversation turn.
- Completed message retries are deterministic and do not repeat retrieval,
  generation, token use, or history writes.
- Foreign and missing conversations, messages, and citations are indistinguishable.
- Every public route is authenticated, bounded, non-streaming, and owner-scoped.
- Telemetry contains aggregates only and cannot reconstruct private content.
- SQL remains authoritative; the model explains verified backend calculations.
- No assistant component has a financial write tool or embeds raw financial rows.

## 22. Phase 12 closure and Phase 13 boundary

Phase 12 is implementation-complete when the full backend regression, coverage,
offline and measured RAG gates, OpenAPI contract, Alembic chain/offline SQL,
container configuration, privacy/adversarial cases, and repository hooks pass.
The feature branch then targets `develop` through the normal squash-merge workflow.

Phase 13 owns the React assistant UI, streaming presentation, distributed rate
limiting, provider/deployment secret integration, scheduled retention execution,
notifications, production deployment, and production operations. Those deferred
capabilities cannot weaken Phase 12 owner isolation, evidence authorization,
grounding, citations, verification, deletion, or no-write boundaries.
