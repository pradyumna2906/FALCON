# FALCON Phase 7 Intelligent Transaction Classification

Phase 7 status: complete. Checkpoints 7.1 through 7.8 are implemented and
subject to the validation record in this document.

## 1. Purpose and phase boundary

Phase 7 assigns understandable financial categories to the normalized ledger
transactions produced by Phases 5 and 6. Manual transactions, CSV, XLSX, and
digital PDF bank-statement imports use one classification contract after their
data reaches the canonical transaction ledger. Input-format-specific model
paths are forbidden.

Phase 6 remains responsible for extraction, normalization, validation,
deduplication, and atomic ledger loading. Phase 7 owns text preparation,
merchant intelligence, rules, model inference, confidence, abstention,
explanations, and user correction feedback. Phase 8 may aggregate reviewed
classification results for analytics but must not reinterpret model internals.

Checkpoint 7.1 froze the taxonomy and public/domain behavior before later work.
Checkpoints 7.2 through 7.7 added the shared feature path, rules, evaluated
provisional model, verified inference, persistence, APIs, corrections, and
owner-isolated merchant memory. Checkpoint 7.8 closes the phase with bounded
explanations, privacy-safe aggregate monitoring, database/performance evidence,
and full regression requirements.

## 2. Ownership and authorization

Every classification operation starts from the authenticated principal and may
read or update only that user's transactions. A request may select transaction
identifiers but never `user_id`, model provenance, confidence, decision,
prediction source, taxonomy version, ruleset version, or model version.

Single and batch repository queries must apply the trusted owner predicate as
part of transaction selection. Cross-user transaction and category identifiers
are indistinguishable from absent resources. System categories and active
private categories remain subject to the Phase 5 ownership rules.

One user's merchant memory and user correction events can never affect another
user. Global training data may incorporate feedback only after a separate,
reviewed, anonymized dataset-building process.

## 3. Versioned taxonomy

The first taxonomy version is `2026.1`. Codes are stable machine identifiers;
display names may be localized later without changing stored meaning. Every
subcategory has exactly one parent.

| Category | Kind | Subcategories |
|---|---|---|
| `food_dining` | Expense | Groceries, Restaurants, Food Delivery |
| `housing` | Expense | Rent, Maintenance, Utilities |
| `transportation` | Expense | Fuel, Public Transport, Taxi & Ride Share, Vehicle Maintenance, Toll & Parking |
| `shopping` | Expense | Clothing, Electronics, Household Goods, General Shopping |
| `healthcare` | Expense | Pharmacy, Hospital & Clinic, Health Insurance |
| `education` | Expense | Tuition & Fees, Courses, Books & Supplies |
| `entertainment` | Expense | Streaming, Movies & Events, Gaming, Hobbies |
| `financial` | Expense | EMI & Loan Payment, Bank Charges, Taxes, Other Insurance |
| `income` | Income | Salary, Freelance, Business Income, Interest, Dividend, Refund, Cashback, Other Income |
| `transfer` | Transfer | Self Transfer, Person Transfer |
| `investment` | Expense | Mutual Fund, Stocks, Fixed Deposit, Retirement, Other Investment |
| `cash` | Mixed ledger direction | ATM Withdrawal, Cash Deposit |
| `other` | Expense fallback | Uncategorized, Other Expense |

Transaction direction remains an independent ledger fact. Each leaf records its
compatible direction and category kind. Cash activity may arrive as income,
expense, or transfer depending on whether both sides are represented in FALCON:
ATM withdrawal accepts expense or transfer, while cash deposit accepts income or
transfer. The classifier never changes transaction amount, direction, account,
provenance, posting status, or import linkage.

Taxonomy changes require a new version, compatibility tests, migration and
reclassification analysis, and an explicit review. Existing codes cannot be
silently reused with a new meaning.

## 4. Shared feature schema

Feature schema version `2026.1` is the only preprocessing representation used
by both offline training and production inference. It accepts trusted canonical
ledger facts: description, optional merchant, transaction type, signed exact
amount, account currency, and calendar date. It intentionally does not accept `user_id`, account
identity, import source type, raw source reference, category, or any
client-supplied prediction field.

The deterministic output contains:

- normalized description and at most 64 bounded tokens;
- explicit normalized merchant, or a conservative rail-based candidate;
- one payment channel: UPI, IMPS, NEFT, RTGS, card, ATM, ACH/NACH/ECS,
  cheque, wallet, cash, bank transfer, or unknown;
- immutable transaction direction and ISO-style account currency from the ledger;
- one exact nominal-currency amount band: `micro` (up to 100), `small` (up to
  1,000), `medium` (up to 5,000), `large` (up to 25,000), or `very_large`;
- month, day of month, weekday, and weekend signal;
- a deterministic recurring-candidate signal for reviewed terms such as salary,
  rent, EMI, SIP, subscription, autopay, NACH, and standing instruction.

Unicode uses NFKC normalization and case folding. Control characters and safe
punctuation are normalized. Common UPI/email handles, masked account/card
suffixes, numeric values, long digit references, and long mixed alphanumeric
references are removed before model tokens are formed. Payment rails, currency
markers, and generic banking words
are represented as structured signals rather than duplicated text noise.

An explicit ledger merchant always takes precedence. Description-based merchant
inference runs only for reviewed electronic rails and remains a normalized
candidate; alias matching, fuzzy similarity, and category knowledge belong to
Checkpoint 7.3. Unknown free text does not invent a merchant.

Exact amounts are validated but excluded from the model record to reduce
memorization of user-specific values. Source format is also excluded, so
equivalent manual transactions, CSV, XLSX, and digital PDF imports use the same
representation. Sanitized feature text is still private financial information:
it is not an anonymized export and must not be placed in logs or metrics.

Tokenization, channel priority, amount boundaries, masking, record field order,
and the feature-schema version are contract-tested. Any semantic change requires
a new feature-schema version and model compatibility review.

## 5. Rules engine and merchant knowledge

Ruleset and merchant-knowledge version `2026.1` provide a deterministic,
dependency-free first layer before ML. The merchant knowledge base contains 24
reviewed India-first merchants across food delivery, groceries, transport,
fuel, clothing, electronics, pharmacy, streaming, events, education,
investment, and electricity. Each entry records a stable merchant identifier,
bounded display name, exact normalized aliases, compatible transaction types,
taxonomy target, and exact confidence.

Merchant resolution is exact after the shared feature normalization. It never
uses prefix, substring, edit-distance, phonetic, embedding, or other fuzzy
matching. Marketplaces and merchants with highly ambiguous financial meaning
are excluded from automatic merchant rules. Adding or changing an alias requires
review, uniqueness validation, taxonomy compatibility, tests, and a new
knowledge version when semantics change.

The high-precision keyword rules cover internal transfers, ATM withdrawals,
cash deposits, salary, cashback, refunds, interest, EMI/loan payments, rent,
SIP investments, bank charges, fuel, and electricity. They evaluate only the
versioned shared features, including exact normalized tokens, transaction type,
and payment channel. They do not inspect raw files or source-format identity.

Every rule has a stable identifier, target, compatible transaction types,
required/excluded tokens, optional channel constraint, explicit priority, exact
confidence, safe reason code, and ruleset version. Reviewed merchant matches
have priority over generic keyword signals. Results contain only bounded rule
provenance; no raw description, merchant text, identifier, or matched source
substring is returned.

Matches are sorted by priority, confidence, and stable rule identifier. If the
highest-priority matches disagree on their category target, the engine returns
an explicit conflict with no selected candidate. Equal-priority matches for the
same target resolve deterministically. No-match and conflict outcomes remain
unclassified for the later hybrid/ML orchestrator; the rules engine does not
force an `other` category.

The global reviewed merchant base is distinct from same-user merchant memory.
Personal mappings and immutable correction feedback remain owned by Checkpoint
7.7 and can never be created from this global exact-match table.

## 6. Hybrid classification decision contract

The finalized decision order is:

1. prepare sanitized deterministic features;
2. apply high-precision rules;
3. consult same-user reviewed merchant memory;
4. invoke the selected ML classifier when needed;
5. calibrate and compare confidence;
6. automatically assign, suggest, or abstain;
7. persist bounded provenance and return safe reason codes.

The supported result decisions are:

- `automatic`: sufficiently reliable for server assignment;
- `suggested`: shown for confirmation without pretending it is final;
- `abstained`: no category is assigned because evidence is insufficient or
  ambiguous.

The supported prediction sources are `rule`, `merchant_memory`, `ml`, and
`hybrid`. Rule and hybrid results carry a ruleset version. ML and hybrid results
carry a model version. All results carry the taxonomy version and an exact
decimal confidence from zero through one.

Checkpoint 7.5 implements this decision boundary without persistence or an API.
The stable classifier adapter accepts only the shared feature object and returns
at most two taxonomy candidates, exact four-decimal confidence, top-two margin,
model version, and production-eligibility status. Estimator classes must exactly
match the trusted manifest order. Invalid probability shapes, non-finite values,
unknown taxonomy leaves, incompatible feature versions, and probability rows
that do not sum to one are rejected.

The hybrid service evaluates Checkpoint 7.3 rules before requesting a model, so
a high-precision unambiguous rule never loads the artifact. When rules do not
resolve the transaction, calibrated model confidence selects automatic,
suggested, or abstained behavior. A small top-two margin forces ambiguity
abstention. A direction-incompatible category is never assigned. A model may
resolve a rule conflict only when it agrees with one of the leading rule targets;
otherwise the result remains abstained with hybrid provenance.

Synthetic or otherwise non-production-eligible models can provide suggestions
for the academic/demo workflow but can never create automatic ML assignments.
An unavailable, corrupt, incompatible, or invalid model becomes a bounded
`classifier_unavailable` abstention and leaves the ledger untouched. No raw
exception, path, feature text, or estimator diagnostic crosses the outcome
boundary.

Confidence thresholds are not guessed in Checkpoint 7.1. Checkpoint 7.4 selects
them from held-out calibration evidence. The intended policy is high-confidence
automatic assignment, medium-confidence suggestion, and low-confidence
abstention. A small top-two probability margin may also force abstention.

## 7. Public write and response boundary

The future single-classification operation selects one owned transaction in its
path. A future batch request accepts only `transaction_ids`, requires 1 through
100 unique UUIDs, and resolves every identifier under the authenticated owner.
It cannot submit features or prediction outputs.

A user correction accepts only one active allowed `category_id`. The server
captures the original prediction and provenance from trusted storage. A client
cannot manufacture a confidence score, model version, correction owner, or
feedback timestamp.

A classification result may expose:

- transaction identifier;
- decision and prediction source;
- category and subcategory codes, or neither when abstaining;
- bounded exact confidence;
- up to five stable reason codes;
- one static human-readable explanation for each reason code, in the same order;
- taxonomy, ruleset, and model versions where applicable.

It never exposes ownership keys, raw feature vectors, filesystem/model paths,
serialized estimators, training examples, arbitrary exception messages, or raw
model diagnostics.

## 8. Safety, privacy, and correction rules

Existing manually selected or previously user-confirmed categories are never
silently overwritten. Reclassification must be explicit and idempotent. A model
failure leaves the ledger transaction unchanged.

Raw transaction descriptions may be processed in request or worker memory but
must not be written to ordinary application metrics or model-operational logs.
Classification-operational events contain only a closed operation name, batch
size, decision/source/reason-code counts, taxonomy version, and elapsed time.
They exclude user IDs, transaction IDs, merchants, descriptions, category IDs,
feature values, model paths, and arbitrary exception text. Failed requests are
visible through the existing body-free HTTP status log rather than a second
content-bearing classifier event. Training exports remove user IDs, account
numbers, UPI IDs, card numbers, bank references, and other direct identifiers.

Each user correction is an immutable feedback event containing the original
bounded prediction, selected category, relevant versions, and server timestamp.
Corrections do not automatically mutate a global model. A user may create,
replace, or remove their own merchant memory without exposing another user's
mapping.

## 9. Model-selection and evaluation implementation

Checkpoint 7.4 compares rather than assumes the production model. Dataset
version `2026.1` accepts only the shared sanitized feature object plus a reviewed
taxonomy target. Private source and equivalent-merchant keys are converted to
opaque HMAC identifiers using a private secret of at least 32 bytes; the keys
are never exported. Exact duplicate labeled features, duplicate source records,
mixed-label groups, incompatible transaction directions, unknown record fields,
and manifest/checksum mismatches are rejected.

The committed reference dataset is deterministic and entirely synthetic. It
contains 864 records: 18 for each of all 48 taxonomy leaves, arranged into 288
independent synthetic merchant groups. It contains no real account, user,
statement, UPI, card, or transaction identifiers. Sanitized text is still
treated as private financial data by the workflow; a future reviewed dataset
must be held in approved encrypted storage rather than committed.

The stable group-aware split uses an opaque group exactly once and stratifies
each leaf into 576 training, 144 calibration, and 144 final-test records. The
calibration partition selects the automatic and suggestion confidence thresholds
and top-two margin. The final test partition is never used to choose them. Split
identity, seed, record IDs, dataset checksum, schema/taxonomy versions, library
versions, hyperparameters, and in-memory artifact checksum are recorded.

The implemented comparison includes a majority baseline, the Checkpoint 7.3
keyword/rule baseline with honest abstention, TF-IDF plus class-balanced logistic
regression, and TF-IDF plus calibrated linear SVM. Both learned candidates use
word unigrams/bigrams and the same bounded structured tokens. The training path
does not persist a pickle or joblib artifact. Structured-feature boosting and a
MiniLM sentence transformer are deferred because the balanced reference evidence
does not justify their dependency, latency, memory, and artifact cost.

Evaluation records dataset version, feature-schema version, split identity,
random seed, library versions, hyperparameters, artifact checksum, and results.
Required evidence includes:

- macro-F1 and weighted-F1;
- per-category precision and recall;
- confusion matrix and top-two accuracy;
- calibration error and abstention coverage;
- unseen-merchant performance;
- inference latency, memory use, and artifact size.

Macro-F1 is the primary classification-quality metric because dominant classes
must not hide failures in smaller financial categories. Dataset splitting is
group-aware by merchant or equivalent identity and prevents duplicate or
near-duplicate leakage across training and evaluation.

The reproducible synthetic reference run selected calibrated Linear SVM under
that primary metric. Its held-out macro-F1 is `0.99285714`, weighted-F1 is
`0.99285714`, top-two accuracy is `1.0`, and unseen-group macro-F1 is
`0.99285714`. Logistic regression remains a strong efficiency candidate at
`0.98571429` macro-F1 with a substantially smaller measured serialized size and
lower per-record latency. The provisional SVM thresholds are `0.40` automatic,
`0.20` suggested, and `0.00` minimum top-two margin, selected only from
calibration evidence.

These scores demonstrate pipeline behavior, not real-world generalization. The
report sets `production_eligible` to false for every synthetic dataset. A future
reviewed de-identified dataset must pass the same leakage, calibration,
held-out-quality, and automatic-precision gates before production eligibility
can become true. Checkpoint 7.5 may package the selected provisional estimator
for an academic/demo flow, but it must preserve that evidence status.

## 10. Error contract

The future API retains FALCON's unified error envelope.

| HTTP | Code | Meaning |
|---|---|---|
| `401` | `invalid_access_token` | Authentication failed |
| `404` | `transaction_not_found` | An owned eligible transaction is absent |
| `404` | `category_not_found` | An allowed active category is absent |
| `404` | `merchant_memory_not_found` | An owner-scoped personal mapping is absent |
| `409` | `classification_conflict` | Stored state changed or a confirmed result cannot be silently replaced |
| `422` | `invalid_classification_target` | Category and transaction semantics are incompatible |
| `422` | `invalid_merchant_memory` | The merchant or category cannot form a stable taxonomy mapping |
| `422` | `classification_unavailable` | No usable classifier artifact is available |
| `422` | `validation_error` | Public input violates its strict schema |

Parser details, model paths, raw text, feature values, SQL, cross-user
existence, and dependency exceptions never enter public messages.

## 11. Enhanced Phase 7 checkpoints

- **Checkpoint 7.1 (complete):** freeze taxonomy version `2026.1`, ownership,
  decisions, sources, confidence, abstention, corrections, privacy, errors,
  model-evaluation requirements, strict schemas, and contract tests.
- **Checkpoint 7.2 (complete):** implement shared text preprocessing, merchant
  extraction, payment-channel signals, reference masking, amount/calendar/
  recurrence features, and deterministic feature schema `2026.1`.
- **Checkpoint 7.3 (complete):** implement versioned reviewed exact merchant
  knowledge and priority-ordered high-precision rules with deterministic
  selection, bounded provenance, and conflict-safe abstention.
- **Checkpoint 7.4 (complete):** build the sanitized dataset workflow, train and compare
  baselines, calibrate confidence, select thresholds, and publish evaluation
  evidence.
- **Checkpoint 7.5 (complete):** implement the classifier interface, artifact registry,
  checksum verification, lazy inference, hybrid orchestration, and abstention.
- **Checkpoint 7.6 (complete):** add user-scoped persistence, migrations, authenticated
  single/batch APIs, bounded atomic updates, and classification provenance.
- **Checkpoint 7.7 (complete):** add immutable user correction events and
  isolated adaptive merchant memory without automatic global retraining.
- **Checkpoint 7.8 (complete):** add bounded explainability, privacy-safe monitoring,
  PostgreSQL and performance validation, full regression, documentation
  closure, and PR-quality verification.

## 12. Checkpoint 7.1 completion criteria

Checkpoint 7.1 is complete when the taxonomy is closed and uniquely mapped,
strict schemas reject client-controlled server fields, result invariants prevent
forced or structurally inconsistent predictions, contract tests protect the
documented ownership/privacy boundary, and the complete backend regression
remains above its coverage gate.

No database table, model artifact, route, training dependency, or production
prediction is introduced by this checkpoint. Those changes require their own
approved checkpoint and validation record.

## 13. Checkpoint 7.2 validation record

Checkpoint 7.2 adds a pure, dependency-light feature module. It does not read a
database, mutate a transaction, infer a category, load an artifact, access the
network, or log source content. Frozen input and output dataclasses keep the
boundary explicit and make the same function reusable by future dataset and
inference workflows.

Tests cover every payment channel, priority collisions, Unicode and control
characters, UPI/email/account/reference masking, explicit and inferred merchant
behavior, exact amount-band boundaries, recurring and calendar signals, token
limits, input sign and type invariants, stable primitive records, and equivalent
manual/imported inputs. Completion also requires the full Phases 1–7 backend
regression and repository quality checks to remain green.

## 14. Checkpoint 7.3 validation record

Checkpoint 7.3 adds no training dependency, model artifact, database mutation,
API route, network call, or user-owned memory. Merchant and keyword definitions
are immutable code-reviewed configuration. Startup construction rejects blank,
duplicate, ambiguous, malformed, direction-incompatible, or invalid-confidence
definitions before an evaluation can occur.

Tests cover the complete default knowledge base, exact alias normalization,
fuzzy/prefix rejection, taxonomy and direction compatibility, all reviewed
keyword behaviors, channel/type/token/exclusion predicates, merchant priority,
wrong-direction rejection, unknown abstention, same-target determinism,
different-target conflicts, custom version propagation, invalid configuration,
and the absence of raw evidence in rule results.

## 15. Checkpoint 7.4 validation record

Checkpoint 7.4 adds a strict dataset module, an explicitly imported offline
training/evaluation module, pinned optional ML dependencies, a deterministic
synthetic-data/evidence command, versioned dataset records and manifest, and a
publishable JSON evaluation report. Importing the ordinary FastAPI application
does not import scikit-learn because training is not re-exported by the stable
classification package boundary.

The committed evidence records all required candidate metrics, sparse confusion
entries, per-leaf and per-category precision/recall, calibration error, decision
coverage, unseen-merchant-group performance, inference latency, peak traced
Python inference memory, serialized estimator size/checksum, hyperparameters,
library versions, split identity, and seed. No model binary is committed.

Tests cover privacy pseudonymization, masking, strict serialization, checksum
verification, invalid configuration, duplicate rejection, group isolation,
stratification, deterministic split identity, threshold selection, probability
validation, all four candidate evaluations, report safety, and the synthetic
production gate. Completion requires the complete backend regression, coverage
gate, compilation, repository hooks, dataset regeneration, manifest verification,
and documentation-contract checks to pass.

## 16. Checkpoint 7.5 validation record

Checkpoint 7.5 adds the dependency-light classifier interface, strict artifact
manifest, local packaging workflow, trusted version registry, SHA-256 and size
verification, exact library compatibility checks, thread-safe lazy provider,
and rules-first hybrid classification service. The FastAPI application still
does not import scikit-learn during ordinary startup. Loading occurs only on the
first model request, successful verified loads are cached, and failures remain
retryable for operational recovery.

Model binaries and their generated manifests remain excluded from Git. The
packaging command rebuilds the reviewed dataset comparison, confirms that the
selected estimator bytes exactly match Checkpoint 7.4 evaluation evidence, and
writes one explicit model-version directory. The registry rejects traversal,
symlinks, missing files, unknown manifest fields, identity mismatch, excessive
size, checksum mismatch, incomplete production taxonomy coverage, Python
major/minor mismatch, and exact numpy/scipy/scikit-learn/joblib mismatch before
trusted pickle deserialization. Artifact directories are server configuration;
no client may select a filesystem path or upload serialized estimators.

Tests cover classifier probability and taxonomy invariants, deterministic top-two
selection, manifest round-trip and invalid shapes, production gates, packaging
evidence matching, overwrite protection, missing/corrupt/incompatible artifacts,
checksum-before-deserialization, concurrent lazy loading, retry after recovery,
rules-first short-circuiting, automatic/suggested/abstained thresholds,
provisional-model downgrade, transaction-direction safety, rule conflict
agreement/disagreement, and bounded unavailable outcomes. Completion also
requires local packaging verification, absence of tracked model binaries, full
backend regression, coverage, compilation, repository hooks, and documentation
contract checks.

## 17. Checkpoint 7.6 validation record

Checkpoint 7.6 connects the reviewed hybrid decision boundary to the canonical
ledger without accepting client-supplied features or prediction metadata. The
authenticated operations are `POST /api/v1/transactions/{transaction_id}/classification`
for one transaction and `POST /api/v1/classifications/batch` for 1 through 100
unique transaction IDs. Batch responses preserve request order, and every
identifier is resolved under the authenticated owner predicate. A missing or
cross-user identifier returns the same `transaction_not_found` response.

Migration `e4a7c91d2f63` installs all 48 taxonomy leaves as stable system
categories. Each leaf has a deterministic UUID and unique `classification_code`;
private categories cannot claim a classifier code. The public category list now
exposes this optional stable leaf code so a client can connect a suggestion to
the corresponding system category without matching localized display text.

The `transaction_classifications` table stores exactly one current result per
owned transaction. Composite foreign keys bind provenance to the same user and
transaction, and automatic assignments additionally bind the assigned category
ID to the stored taxonomy leaf code. Database checks bound decision, source,
confidence, reason count, taxonomy codes, version presence, and automatic,
suggested, or abstained target consistency. Raw descriptions, prepared features,
artifact paths, model exceptions, and user ownership keys are not copied into
classification provenance.

The application locks the bounded owner-scoped transaction set before checking
stored provenance, inference, and persistence. This serializes competing writes
to the same ledger entries while allowing unrelated users and transactions to
proceed independently. All batch validation and inference completes before the
single repository flush. Any missing identifier, protected category, changed
user state, invalid target, unavailable classifier, or missing taxonomy mapping
raises a bounded application error and causes the request transaction to roll
back without partial category or provenance writes.

Automatic rule results and future production-eligible model results assign the
system leaf category and provenance atomically. Suggestions and ordinary
abstentions store provenance but do not mutate `transactions.category_id`.
Classifier-unavailable abstentions instead return `classification_unavailable`
and leave the ledger untouched. Pending and adjustment transactions are
ineligible. Existing categories and `is_user_modified` transactions are
protected from silent overwrite.

Repeat classification is idempotent: an unchanged stored result is returned
without rerunning rules or loading the model. If a user changes a transaction or
selects a category after a suggestion, the operation returns
`classification_conflict`. Immutable correction events and personalized
merchant memory remain exclusively Checkpoint 7.7 work.

The process composition root configures a lazy verified provider from
`FALCON_CLASSIFICATION_ARTIFACT_ROOT` and
`FALCON_CLASSIFICATION_MODEL_VERSION`. Startup still does not deserialize or
import a scikit-learn estimator; rule-only traffic does not load the artifact.
Focused tests cover owner predicates, row locks, mapping constraints, automatic,
suggested and idempotent behavior, batch ordering and bounds, rollback-triggering
errors, safe authenticated routes, and the real PostgreSQL API lifecycle. Full
regression, coverage, compilation, migration lifecycle, and repository-quality
verification are required before Checkpoint 7.6 is staged.

## 18. Checkpoint 7.7 validation record

Checkpoint 7.7 adds a personalization layer without changing the global rules,
training data, or model artifact. Migration `f7b2d4e8a901` creates
`transaction_category_corrections` and `user_merchant_memories`. Correction
rows copy the original bounded decision, source, taxonomy target, exact
confidence, reason codes, and applicable taxonomy/ruleset/model versions from
trusted classification storage. The client still submits only one
`category_id`. Composite foreign keys bind every correction to the same owner,
transaction, and original classification, while a database trigger rejects any
attempt to update an existing event. User and transaction privacy deletion may
still cascade; ordinary application code exposes no correction update or delete
operation.

`POST /api/v1/transactions/{transaction_id}/classification/correction` locks
the owned transaction, requires its stored classification, validates an active
system or same-user private category against the current transaction direction,
marks the ledger category as user-modified, and appends the correction in the
same database transaction. Its response returns the correction identifier,
selected category, optional merchant-memory identifier, original bounded
classification, and server timestamp. It does not accept or return an owner
key, raw text, feature vector, model path, or client-provided prediction
metadata.

An initial correction rejects a transaction already marked as modified outside
this workflow. A later correction is accepted only when the transaction's last
update timestamp matches its latest immutable correction event. This permits
reviewers to change their selected category again while preventing a stale
prediction from creating merchant memory after unrelated transaction edits.

Exact personal mappings are keyed by `(user_id, normalized_merchant)` and point
only to stable active system-taxonomy leaves. The unique owner/key constraint,
composite taxonomy foreign key, version checks, and owner predicates prevent a
mapping from crossing users or drifting to a private or unknown classifier
label. Mapping writes use a transaction-scoped advisory lock so concurrent
corrections or direct writes for the same owner and merchant serialize without
lost updates. Selecting a private category still records a valid correction but
removes any stale taxonomy mapping for that merchant.

The authenticated mapping operations are `PUT` and `GET` on
`/api/v1/classification/merchant-memories` and `DELETE` on
`/api/v1/classification/merchant-memories/{memory_id}`. `PUT` creates or
replaces one exact mapping, `GET` returns a bounded stable page, and `DELETE`
uses a uniform owner-scoped not-found response. No endpoint can enumerate or
mutate another user's mapping.

During classification, reviewed global rules remain first. When rules do not
select a target, the application resolves every normalized merchant in a batch
with one same-user query and supplies exact matches to the hybrid service.
Direction-compatible memory produces an automatic `merchant_memory` result at
exact confidence `1.0000` with reason `user_merchant_memory`; incompatible
memory is ignored and inference safely continues to ML. There is no fuzzy
matching, cross-user sharing, training export, background retraining, or global
model mutation in this checkpoint.

## 19. Checkpoint 7.8 validation record and Phase 7 closure

Checkpoint 7.8 adds a read-only `explanations` array to every serialized
classification result, including the original result nested in a correction.
Each entry pairs the existing stable reason code with one static message of at
most 160 characters. Messages are selected from a complete code-reviewed map;
they never interpolate a merchant, description, amount, identifier, feature,
category, exception, or model diagnostic. Clients cannot submit or override
the computed field, and changing explanation wording is an explicit public
contract change rather than model output.

The application service emits one `classification_operation_completed` event
after each successful classification, correction, or merchant-memory action.
Single and batch predictions share the same low-cardinality `classify`
operation. Classification events aggregate decision, source, and reason-code
counts; other operations record only the bounded item count. All events use a
monotonic elapsed time and the existing JSON formatter allowlist, so arbitrary
logging extras cannot enter the serialized operational record.

Performance validation protects the maximum public batch of 100 transactions.
The application performs one owner-scoped target lock, one existing-result
lookup, one exact merchant-memory lookup, one taxonomy-category lookup, and one
persistence call for the batch; there is no per-transaction database query.
Inference remains intentionally per transaction within the bounded in-process
loop. A generous two-second unit regression ceiling detects accidental blocking
or query fan-out without claiming hardware-independent production latency.
PostgreSQL integration verifies the migration head, complete authenticated
classification/correction/memory lifecycle, immutable correction trigger,
cross-user isolation, and the explicit owner/time access indexes used by these
queries. CI runs all database-gated integration tests against PostgreSQL.

Phase 7 completion requires the full backend unit and integration suites,
branch coverage gate, source compilation, offline Alembic upgrade and downgrade
rendering, local artifact packaging/evidence verification, and repository hooks
to pass. The synthetic reference artifact remains `production_eligible=false`:
it is suitable for a verified demo flow and can suggest, but it cannot
automatically assign model-only results. Production rollout still requires a
reviewed de-identified real-world dataset to pass the documented leakage,
quality, calibration, automatic-precision, latency, and privacy gates.

Phase 7 does not add fuzzy matching, transformers, background retraining,
cross-user personalization, raw-text telemetry, or Phase 8 analytics. Phase 8
may now consume canonical reviewed categories and bounded provenance to build
aggregations and insights without reinterpreting classifier internals.
