# FALCON

**FALCON — AI-Augmented Multi-goal Financial Advisor with Cognitive Forecasting** is an India-first personal-finance decision-support web application for people with regular or irregular income.

> Release target: **v1.0.0 — Academic Project Release**. The integrated application
> is implemented. The owner reports successful testing with real financial data;
> see [release acceptance](docs/testing/RELEASE_ACCEPTANCE.md) for the scope of
> that evidence and [release notes](CHANGELOG.md) for model limitations. Public
> hosting requires the separate production activation steps below.

## Purpose

FALCON helps users understand their financial behaviour, forecast future cash flow, plan multiple goals and receive practical, explainable recommendations.

## Core objectives

- Build a complete financial profile.
- Record and import transactions.
- Categorize spending and detect financial leaks.
- Forecast income, expenses, savings and cash flow.
- Plan and prioritize multiple financial goals.
- Compare best, expected and worst-case scenarios.
- Calculate financial-health and goal-completion scores.
- Explain forecasts and recommendations clearly.
- Protect user data through secure authentication, export and deletion.

## Technology

- Frontend: React and TypeScript
- Backend: FastAPI and Python 3.13
- Database: PostgreSQL
- ML: scikit-learn, XGBoost and time-series models
- Testing: Pytest, Vitest and Playwright
- Version control: Git and GitHub

## Development environment

FALCON standardizes on Python 3.13.15, Node.js 24.19.0 LTS and npm 11.17.0.

See [Development Environment](docs/DEVELOPMENT_ENVIRONMENT.md) for the version declarations and verification commands.

## Development workflow

FALCON is being developed incrementally:

1. Explain the feature.
2. Implement one focused change.
3. Test the change.
4. Review the changed files.
5. Commit and push.
6. Merge through a pull request.

Backend setup and execution instructions are maintained in
[`backend/README.md`](backend/README.md). See [`frontend/README.md`](frontend/README.md)
for the integrated web application and [`deployment/RUNBOOK.md`](deployment/RUNBOOK.md)
for deployment, provider activation, monitoring and recovery.

## Run the application

Use Python 3.13 and Node 24 as declared in the repository. Follow the
[Windows setup and startup instructions](docs/testing/FINAL_REVIEW.md#windows-setup-and-startup)
for dependency installation, optional review-model preparation, PostgreSQL,
explicit database migrations, the API and frontend. Keep `.env` private and
retain the database volume. Open the frontend URL printed by Vite and register
or sign in with your own account; no default credentials are supplied.

- [Backend setup and tests](backend/README.md)
- [Frontend setup and tests](frontend/README.md)
- [Manual acceptance checklist](docs/testing/MANUAL_ACCEPTANCE.md)
- [Algorithms and implementation locations](docs/ml/ALGORITHMS.md)
- [Dataset provenance and reproducibility](docs/ml/DATASET_PROVENANCE.md)
- [Release notes and limitations](CHANGELOG.md)
- [Production deployment and recovery](deployment/RUNBOOK.md)

Email verification/recovery delivery requires private SMTP configuration and the
background worker. Live assistant responses require private provider
configuration. A successful startup alone does not verify either service.
No provider key belongs in frontend configuration.

## Release verification

Run the backend unit suite, isolated PostgreSQL/Redis integration suite,
frontend lint/unit/build and three-browser workflows, ML evidence checks,
dependency audits and the TLS/encrypted-restore drill. GitHub Actions defines
the exact required commands and services. Use disposable databases for
integration tests, never the owner's financial database. A release is ready only
when checks on the final promoted commit pass.

All committed ML benchmarks use synthetic data. Owner-reported real-data
functional acceptance is separate from independently measured model accuracy.
The review classifier remains provisional and cannot automatically assign
categories. Forecast intervals and external generalization remain limitations.
