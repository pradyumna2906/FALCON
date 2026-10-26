# FALCON real-environment acceptance checklist

Use the running React frontend and real FastAPI/PostgreSQL backend. These are
manual acceptance tests, separate from browser tests that mock API responses.
Record date, branch/commit, browser, test account and each result. Leave a check
unchecked until you actually observe the expected behaviour.

Use a dedicated test account and synthetic records before testing your own
financial data. Keep the API/worker terminals visible. In browser DevTools,
inspect Console and Network when a step fails. Record the request path, status
and redacted error; never copy passwords, Authorization headers, cookies, keys,
verification/reset tokens or full private financial payloads into an issue.

## Preparation

- [ ] Run the latest feature branch; confirm the API `/health/live` and
  `/health/ready` succeed, PostgreSQL is healthy and Alembic reports `(head)`.
- [ ] Register and verify two separate test accounts, A and B. Do not use an
  account containing important data for deletion tests.
- [ ] Use INR and Asia/Kolkata for account A. Start without any transactions.
- [ ] Confirm empty pages give useful prompts rather than made-up figures.
- [ ] Keep evidence: expected result, observed result, screenshot and PASS/FAIL.

## Small dataset with exact expected totals

Create one INR bank account named `Acceptance INR` with opening balance zero.
Import the following as a CSV, using ISO dates and signed Amount values. Positive
amounts are income; negative amounts are expenses. Choose this new account.

```csv
Date,Description,Amount
2026-09-01,Acceptance salary,60000
2026-09-05,Acceptance rent,-15000
2026-09-10,Acceptance groceries,-6000
2026-09-15,Acceptance commute,-3000
2026-09-20,Acceptance subscription,-499
```

For September 2026 and INR, with only these five posted transactions:

| Check | Expected |
| --- | ---: |
| Income | 60000.0000 |
| Expenses | 24499.0000 |
| Net cash flow | 35501.0000 |
| Eligible transaction count | 5 |

Compare exact displayed/API values, not approximate chart coordinates. For
forecasting/recurring tests, add the same five entries for April–August, changing
the month in each date. This makes 30 entries across six months. For April–September,
income is 360000, expenses 146994 and net cash flow 213006. Categorize groceries,
rent, commute and the subscription before category/budget tests. Classification
may need a manual correction; do not assume every novel merchant is recognized.

## Authentication and financial profile

| ID | Action | Expected result | Result |
| --- | --- | --- | --- |
| A01 | Register a new email; try registering it again | First succeeds; duplicate is rejected without a second user | |
| A02 | Sign in with a wrong password, then correct one | Wrong login fails; correct login succeeds | |
| A03 | Try financial pages before email verification | Access remains blocked until valid verification | |
| A04 | Request verification; run configured email worker | Real message arrives; valid token works once; expired/reused token fails | |
| A05 | Request password reset and use received token | New password works; old password fails; prior sessions are revoked | |
| A06 | Open a private URL while signed out, then sign in | Verified user returns to the intended route; assistant URL opens chat | |
| A07 | Save profile, currency/timezone, risk answers; reload | Saved values remain and calculations use the selected context | |
| A08 | Submit invalid/blank profile values | Clear validation; no corrupted/partial record | |
| A09 | Sign out and use browser Back | Private data is guarded; chat and cached user data disappear | |

## Money, import and classification

| ID | Action | Expected result | Result |
| --- | --- | --- | --- |
| M01 | Create/edit bank, savings and debt accounts; set debt terms | Records persist, valid debt properties displayed, invalid values rejected | |
| M02 | Add/edit/delete a manual transaction and reload | Only the intended entry changes; totals update once | |
| M03 | Transfer 1000 between two INR accounts | Paired transfer records; no extra income/expense in analytics | |
| M04 | Import the five-row CSV above | Five accepted entries with correct dates/signs/amounts | |
| M05 | Reimport the identical statement | Existing duplicates are detected; totals do not double | |
| M06 | Import a file containing zero amount, bad date and valid rows | Issues identify invalid rows; accepted counts match stored valid rows | |
| M07 | Import a valid Excel and supported digital PDF statement | Review counts, signs and any balance reconciliation; unreadable/unsupported layouts return a useful error | |
| M08 | Review classification; correct merchant/category; add a matching entry | Correction persists and merchant memory behaves as documented | |
| M09 | Add a pending entry, adjustment and second-currency account/entry | Context reports exclusions; no unconverted currency mixing | |
| M10 | Search/filter transactions by date, account, type/category/status | Results match the selected filters; changing filters clears stale results | |

## Analytics, forecasts, goals and scenarios

| ID | Action | Expected result | Result |
| --- | --- | --- | --- |
| F01 | Select September and INR on Overview/Analytics | Exact totals match the five-row dataset | |
| F02 | Compare periods, account drill-down and category chart/table | Scope and exact values agree; dates/currency/timezone visible | |
| F03 | Set grocery budget 5000 with grocery spend 6000 | Variance shows overspend 1000 in that category/period | |
| F04 | Inspect recurring entries, anomalies, health and insights | Evidence/reasons/coverage visible; confidence reflects available history | |
| F05 | Generate each supported forecast target from six months | Saved result, methods, backtest evidence and uncertainty intervals available | |
| F06 | Reload forecast history and open a result | Same saved result persists; Overview preview uses matching currency | |
| F07 | Forecast with sparse history | Low/provisional reliability or documented insufficiency; no guaranteed outcomes | |
| F08 | Create two goals; edit target/deadline/priority | Goal properties persist; invalid targets/dates rejected | |
| F09 | Record a goal contribution; reload progress | Contribution recorded once; exact saved amount/progress update | |
| F10 | Generate a multi-goal plan and inspect allocations/schedule | Capacity, constraints, evidence and feasibility are explicit; no invented funds | |
| F11 | Accept/reject/supersede a plan using supported controls | Decision lifecycle persists; duplicate/stale decisions handled safely | |
| F12 | Run baseline, -10% income and +10% expense scenarios | Alternatives persist and show meaningful effects against the same baseline | |
| F13 | Inspect sensitivity and choose an alternative; reload | Selection persists; changing selection uses confirmation/expected prior state | |

Do not invent an expected health score, model winner, probability or allocation.
Those depend on actual backend definitions, training/evidence and constraints.
Validate the reported reasons and inputs, not a hand-picked target score.

## Persistent chat and live AI

The Ask FALCON panel is available throughout the verified workspace. It is a
modeless chat dialog so desktop users can navigate while it stays open. On
mobile, minimize it to access the page beneath. Closing/minimizing retains the
active conversation and draft during navigation; reloading the browser resets
transient UI state, while saved conversations remain in Recent conversations.

| ID | Action | Expected result | Result |
| --- | --- | --- | --- |
| C01 | Open Ask FALCON on Money, Analytics, Forecasts, Goals, Reports and Settings | Bottom-right chat opens without navigating to a dedicated chat page | |
| C02 | Start a conversation; ask a question | Right-hand user bubble and left-hand server-verified AI reply | |
| C03 | Ask "What did I spend in September 2026?" | Reply corresponds to available scoped evidence; inspect citations and reliability | |
| C04 | Ask about a saved forecast, goal plan and scenario | Relevant evidence-grounded reply or clear explanation of unsupported/missing evidence | |
| C05 | Ask a follow-up; inspect suggested questions and evidence | Conversation retained; suggestions populate composer; sources can be inspected/copied | |
| C06 | Type a draft, navigate, minimize and reopen | Draft and active conversation remain; no duplicate conversation/request | |
| C07 | Stop the API while sending; restart; retry unchanged text | Explicit error; no unverified reply; same idempotency key safely recovers request | |
| C08 | Open an old conversation; delete with Cancel then Confirm | Cancel preserves it; confirmation deletes history and returns to start state | |
| C09 | Resize to mobile; use keyboard, Escape and long text | Composer accessible; independent scrolling; Escape minimizes and focus returns | |
| C10 | Request another user's records or instructions to ignore safeguards | No cross-owner data or fabricated financial guidance | |

The default provider is **disabled**. A working chat UI does not establish live
AI activation. For generated replies, set these values in the private root
`.env`, using your actual provider account configuration, then restart the API:

```dotenv
FALCON_ASSISTANT_PROVIDER=openai
FALCON_OPENAI_API_KEY=<your private API key>
FALCON_OPENAI_MODEL=<supported model you have access to>
FALCON_OPENAI_INPUT_USD_PER_MILLION=<actual positive input price>
FALCON_OPENAI_OUTPUT_USD_PER_MILLION=<actual positive output price>
```

Do not copy the angle-bracket placeholders literally. Never put the key in the
frontend or commit `.env`. Provider failure must stay visible, not be replaced
with a fabricated reply. This assistant is for supported financial questions;
unrelated requests or insufficient evidence can legitimately receive a refusal
or limited answer. SMTP activation is separate from AI activation.

## Reports, notifications, settings and privacy

| ID | Action | Expected result | Result |
| --- | --- | --- | --- |
| P01 | Download September monthly PDF and filtered transaction CSV | Files open; period/currency/rows/totals agree with the app | |
| P02 | Save notification preferences; inspect/dismiss a real notification | Preference and dismissal persist after reload | |
| P03 | Change display name/timezone/currency and reload | Preferences persist; new views show correct context | |
| P04 | Inspect/revoke another session | Revoked session loses access; current-session behaviour is explicit | |
| P05 | Export account A data | Export contains A's retained data, excludes B's; files parse correctly | |
| P06 | Use account B and inspect every feature/history/export | A's accounts, goals, reports and chat never appear | |
| P07 | Delete disposable account A using confirmation | Account access and owned data removed according to documented retention policy | |
| P08 | Reload/deep-link major routes; disconnect/reconnect API | SPA routes load; failures are readable; retry works without duplicate writes | |

## Record a defect

Use: ID / steps / expected / observed / browser / commit / request path and
status / redacted screenshot. Keep failures in this checklist until fixed and
retested. A release requires the dependency audit, real SMTP/provider checks and
owner-isolation/privacy acceptance as well as the automated suites. Existing
PyJWT/PDF dependency audit findings remain a separate release blocker.
