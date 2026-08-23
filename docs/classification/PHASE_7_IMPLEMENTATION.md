# FALCON Phase 7 Intelligent Transaction Classification

Phase 7 status: Checkpoint 7.1 complete; implementation checkpoints pending.

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
datasets, models, persistence, or routes are introduced.

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

## 4. Hybrid classification decision contract

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

## 5. Public write and response boundary

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

## 6. Safety, privacy, and correction rules

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

## 7. Model-selection and evaluation contract

Checkpoint 7.4 will compare rather than assume the production model. Required
baselines are a majority/keyword baseline, TF-IDF plus logistic regression, and
TF-IDF plus calibrated linear SVM. Structured-feature boosting and a compact
sentence-transformer candidate may be evaluated only when the dataset and
latency budget justify them.

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

## 8. Error contract

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

## 9. Enhanced Phase 7 checkpoints

- **Checkpoint 7.1 (complete):** freeze taxonomy version `2026.1`, ownership,
  decisions, sources, confidence, abstention, corrections, privacy, errors,
  model-evaluation requirements, strict schemas, and contract tests.
- **Checkpoint 7.2:** implement shared text preprocessing, merchant extraction,
  payment-channel signals, reference masking, and deterministic feature schema.
- **Checkpoint 7.3:** implement the versioned high-precision rules engine and
  merchant knowledge base with conflict-safe explanations.
- **Checkpoint 7.4:** build the sanitized dataset workflow, train and compare
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

## 10. Checkpoint 7.1 completion criteria

Checkpoint 7.1 is complete when the taxonomy is closed and uniquely mapped,
strict schemas reject client-controlled server fields, result invariants prevent
forced or structurally inconsistent predictions, contract tests protect the
documented ownership/privacy boundary, and the complete backend regression
remains above its coverage gate.

No database table, model artifact, route, training dependency, or production
prediction is introduced by this checkpoint. Those changes require their own
approved checkpoint and validation record.
