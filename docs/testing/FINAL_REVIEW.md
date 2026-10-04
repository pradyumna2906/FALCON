# FALCON final-review handoff

The implementation and automated evidence are reviewable. **Production release
and a 90% ML claim are not approved.** All committed ML benchmark data is
synthetic. Live email/AI-provider acceptance, owner-PC testing and independent
real-data validation remain required.

## What the project does

FALCON analyzes each authenticated owner's stored financial records. Users enter
transactions or upload supported CSV, Excel and digital PDF statements. The
application validates and deduplicates records, suggests categories, aggregates
income/spending, analyzes budgets and recurring payments, generates forecasts,
plans multiple goals, compares scenarios and explains available evidence through
a grounded AI assistant. PostgreSQL stores owner-scoped application records.
There is no automatic bank-account connection and no newly implemented OCR for
scanned statements in this change.

The classification training fixture is separate from the financial records used
for an owner's live analytics. Exact financial calculations are not ML accuracy
claims. The assistant uses a configured provider; FALCON does not train an LLM
from scratch.

## Verified ML evidence

| Measure | Version 3 result | Interpretation |
|---|---:|---|
| Classification training / validation / test | 12,240 / 4,080 / 4,080 | 48 leaves; template and merchant groups isolated |
| Selected classifier | Word + character TF-IDF, calibrated LinearSVC | Configuration selected using validation only |
| Final-test accuracy | 89.04% | Below the 90% target; do not round up |
| Final-test macro-F1 | 89.50% | Below the 90% target |
| Calibration error | 0.07889 | Ten-bin expected calibration error |
| Instrumented mean / p95 single-row prediction | 20.58 / 34.10 ms | Local Linux, Python 3.13.15; tracemalloc enabled |
| Serialized model | 54,912,092 bytes | Cached once per API process; rebuild for local library versions |
| Forecast comparisons | 150 histories; 300 series; 900 test observations | Six synthetic regimes, 36 monthly periods each |
| Forecast test MAE / RMSE | INR 5,558.24 / 14,694.45 | Income/expense series pooled, not a savings-accuracy percentage |
| Forecast WAPE | 8.89% | Sum absolute errors / sum absolute actual values |
| Baseline comparison MAE | INR 5,534.90 | Selected models are 0.42% worse on aggregate final test |
| 80% / 95% interval coverage | 69% / 69% | Four calibration residuals; intervals are provisional |
| Assistant replay | 720 / 720 guardrail expectations | Deterministic replay, not live LLM accuracy |
| Arithmetic/HiGHS replay | 1,000 / 1,000 cases | Bounded single-variable allocation oracle |
| Performance fixture | 100,000 records | Feature extraction plus separate isolated database/dashboard CI; HTTP import throughput unmeasured |

The theoretical confidence-policy automatic precision is 97.18% on its selected
subset, with 85.27% coverage. **This is not overall accuracy**, and synthetic
artifacts remain `production_eligible=false`; the hybrid service does not use
these ML predictions for automatic assignments. Strong deterministic rules and
existing user-confirmed corrections retain their original behavior.

Version 2 results and the validation-only character-feature experiment are
preserved. Validation increased to approximately 93% with character features;
the fresh version 3 holdout exposes a remaining generalization gap. Neither
version establishes real-world accuracy. See
[dataset provenance](../ml/DATASET_PROVENANCE.md) and the reports under
`ml/reports/review_2026_2` and `ml/reports/review_2026_3`.

## Software verification snapshot

Local Linux verification used Python 3.13.15 and the pinned project dependencies.
The final backend run passed **2,037 unit tests**, reaching **93.87% branch-aware
coverage**. Frontend lint, 55 unit tests and the production build passed.
Ten local Chromium production-browser checks passed; the repository's three
browser projects are exercised separately in GitHub CI. OpenAPI generation was
checked for drift. Backend dependency audit (including optional Prophet) and
frontend production dependency audit reported no known vulnerabilities.

The local PostgreSQL integration run skipped 49 tests because no disposable
PostgreSQL/Redis services were available. Skips are not passes. The PR's CI
supplies those services and runs migrations, integration, container and release
smoke checks. Consult the current PR checks for the authoritative CI status;
fixture/browser evidence does not verify live SMTP or an AI provider.

## Windows setup and startup

Stop the old frontend with Ctrl+C before dependency installation to avoid the
Rolldown file-lock problem. Retain your private root `.env` and database volume.
Do not discard local changes to switch branches.

In PowerShell:

```powershell
cd C:\Users\PRADYUMNA.P\PROJECTS\FALCON
git fetch origin
git switch feature/final-review-ml-readiness
git pull --ff-only
```

If the root virtual environment is missing:

```powershell
py -3.13 -m venv .venv
```

Prepare dependencies, regenerate missing dataset bytes, train/package the
classifier and verify the actual FastAPI wiring:

```powershell
& .\scripts\prepare-review.ps1 -SetModelConfiguration
```

This updates only `FALCON_CLASSIFICATION_ARTIFACT_ROOT` and
`FALCON_CLASSIFICATION_MODEL_VERSION` in the existing private `.env`. It does not
create credentials or rewrite other settings. Model training takes time; wait
for the successful integration output. Restart the backend after changing its
model configuration. Do not copy an older artifact manifest onto newly trained
model bytes.

Terminal 1, repository root:

```powershell
docker desktop start --timeout 120
docker compose --env-file .env up -d --wait postgres
& .\.venv\Scripts\python.exe -m alembic -c backend\alembic.ini upgrade head
& .\.venv\Scripts\python.exe -m uvicorn falcon_api.main:app --host 127.0.0.1 --port 8000 --loop falcon_api.core.event_loop:create_psycopg_compatible_event_loop --reload
```

Terminal 2:

```powershell
cd C:\Users\PRADYUMNA.P\PROJECTS\FALCON\frontend
npm ci
npm run dev -- --port 5173 --strictPort
```

Run `npm ci` after pulling dependency changes or repairing an incomplete install,
not every launch. If a lock prevents installation, identify and stop only the
Node processes belonging to this FALCON frontend; do not use placeholder process
IDs or terminate unrelated applications.

Terminal 3:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health/ready
```

Open **http://127.0.0.1:5173/sign-in** consistently and sign in with your existing
verified account. There are no demo/default login credentials. The chatbot is
available from Ask FALCON on authenticated workspace pages. The turn counter
now displays an explicit expiry date with a month name.

Actual verification/recovery emails require configured SMTP and a worker:

```powershell
cd C:\Users\PRADYUMNA.P\PROJECTS\FALCON
& .\.venv\Scripts\python.exe -m falcon_api.worker
```

Run that worker only with a valid SMTP configuration. An enqueued message is not
proof of email delivery. Real SMTP links require the configured HTTPS frontend
origin; see the existing deployment runbook and manual acceptance guide.

The live assistant requires the private backend provider/key/model/pricing
configuration documented in [manual acceptance](MANUAL_ACCEPTANCE.md). Keys must
never be placed in frontend variables, committed or pasted into review slides.
This task did not make paid provider calls or verify your local private keys.

## Reproduce model and software evidence

Use a new output directory to retain the committed report snapshot:

```powershell
cd C:\Users\PRADYUMNA.P\PROJECTS\FALCON
& .\.venv\Scripts\python.exe -m pip install -e "backend[dev,forecasting,ml,optimization,forecasting-prophet]"
$env:OMP_NUM_THREADS = '1'
$env:OPENBLAS_NUM_THREADS = '1'
& .\.venv\Scripts\python.exe .\scripts\build_review_datasets.py --materialize-missing
& .\.venv\Scripts\python.exe .\scripts\evaluate_review_models.py --reports ml/reports/local_review --registry ml/artifacts/local_review
& .\.venv\Scripts\python.exe .\scripts\check_classifier_integration.py --registry ml/artifacts/local_review --report ml/reports/local_review/fastapi_integration.json
& .\.venv\Scripts\python.exe .\scripts\check_review_evidence.py --reports ml/reports/local_review
& .\.venv\Scripts\python.exe -m pytest backend/tests/unit
```

The evaluation runner refuses existing report files or model versions. Choose a
new local output directory for a second run. Forecasting fits candidates on
individual histories; there is no global forecast model binary to deploy.
Prophet is optional for ordinary application startup but included in the full
review benchmark above. Do not enable PostgreSQL integration tests against your
personal development database: they require a dedicated disposable test
service. CI supplies that isolated PostgreSQL/Redis environment.

Frontend checks:

```powershell
cd C:\Users\PRADYUMNA.P\PROJECTS\FALCON\frontend
npm run lint
npm test
npm run build
npx playwright install
npx playwright test
```

## Demonstration script

1. Explain the synthetic training dataset versus the owner's real transaction
   records. State the measured model results and limitations.
2. Sign in and show financial profile, accounts and currency handling.
3. Use a disposable review account and import the exact sample from
   `MANUAL_ACCEPTANCE.md`. Reconcile rows/totals with the original file, then
   demonstrate duplicate handling and category confirmation.
4. Show income, spending, cash flow, recurring analysis, budgets and reports.
5. Show a saved forecast's selected model, validation/test errors, uncertainty
   and sufficiency warnings. Do not promise future outcomes.
6. Add goals, generate a plan, inspect capacity/constraints and compare scenarios.
7. Open the bottom-right chat, ask a supported financial question, expand its
   evidence, navigate to another page and demonstrate retained conversation.
8. Demonstrate missing-evidence handling and safe refusal. A successful offline
   replay is not proof that the live provider is available.
9. Export data and demonstrate owner isolation and deletion using disposable
   accounts. Do not delete your own existing account during the review.

## Feature-readiness matrix

| Area | Automated evidence | Live acceptance still required |
|---|---|---|
| Auth and privacy | Backend unit/API contracts; PostgreSQL integration CI; browser auth flows | Actual email delivery/recovery; two-owner PC check |
| Profiles/accounts/transactions/imports | Backend suites and browser onboarding/import/correction | Actual supported files, reconciliation and duplicate behavior |
| Classification | Dataset checks, training reports, registry/manifest checks, FastAPI wiring | Category confirmation on independently labelled real records |
| Analytics/budgets/recurring/health | Exact-decimal policy unit tests; database/browser CI | Reconcile actual statement totals and insights |
| Forecasting | All implemented candidates evaluated; chronological benchmark and backend tests | Real-history performance and interval calibration |
| Goals/scenarios | Solver cases, invariant/unit/database/browser checks | Review affordability and explanations for actual goals |
| Assistant | 720 offline replay cases; API/history/privacy tests; persistent-chat browser tests | Configured provider responses, grounding and multi-turn review |
| Reports/notifications/export/delete | Backend suites, browser download/lifecycle and release smoke CI | Actual files, background delivery and user-PC acceptance |
| Performance | Feature benchmark, 100,000-row database/dashboard CI, cached loading, event-loop responsiveness test | Target-PC concurrency and HTTP import/API load testing |
| Security/release | Dependency upgrades and local audits; CI deploy/restore drill | Owner approval, secrets/configuration and production operations |

## Release gates and presentation wording

The 90% classification target is unmet on the fresh synthetic holdout. Forecast
intervals do not meet nominal coverage in this benchmark. Independent real-data
validation is unavailable. Paid live AI evaluation and SMTP delivery are
unverified. These are explicit release/claim limitations, not hidden passes.

Say: “FALCON analyzes uploaded or manually entered user financial records,
combines exact analytics with evaluated classification/forecasting and constrained
planning, and provides evidence-grounded explanations. Our classifier has
89.04% accuracy and 89.50% macro-F1 on a fresh synthetic holdout; external
real-world validation remains future work.”

Do not say all models have 90% accuracy, the project is 100% bug-free, forecast
WAPE is an accuracy percentage, or offline replay proves live chatbot quality.
Complete the existing 50 manual checks, record failures and review the latest CI
status before approving release. Neither this branch nor its PR has been merged
or deployed by this task.
