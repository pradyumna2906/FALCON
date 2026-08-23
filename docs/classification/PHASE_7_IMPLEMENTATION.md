# FALCON Phase 7 Intelligent Transaction Classification

Phase 7 status: Checkpoints 7.1 through 7.4 complete; later implementation
checkpoints pending.

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

Checkpoint 7.1 freezes the taxonomy and public/domain behavior before rules,
datasets, models, persistence, or routes are introduced. Checkpoint 7.4 now
publishes comparison evidence but deliberately does not register or serve an
estimator; artifact loading and inference remain Checkpoint 7.5 responsibilities.

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
Logs and metrics use identifiers, stable reason codes, versions, timing, counts,
and category codes. Training exports remove user IDs, account numbers, UPI IDs,
card numbers, bank references, and other direct identifiers.

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
| `409` | `classification_conflict` | Stored state changed or a confirmed result cannot be silently replaced |
| `422` | `invalid_classification_target` | Category and transaction semantics are incompatible |
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
- **Checkpoint 7.5:** implement the classifier interface, artifact registry,
  checksum verification, lazy inference, hybrid orchestration, and abstention.
- **Checkpoint 7.6:** add user-scoped persistence, migrations, authenticated
  single/batch APIs, bounded atomic updates, and classification provenance.
- **Checkpoint 7.7:** add immutable user correction events and isolated adaptive
  merchant memory without automatic global retraining.
- **Checkpoint 7.8:** add bounded explainability, privacy-safe monitoring,
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
