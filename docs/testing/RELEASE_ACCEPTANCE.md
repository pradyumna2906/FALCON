# v1.0.0 release acceptance

## Owner acceptance — 2026-10-26

The owner reported: “I have tested with real world data and it works well.”
The owner subsequently approved completion and release preparation.
This is owner-reported functional acceptance on their existing installation.
No real financial records are copied into the repository.

The exact local commit, dataset size, labelled expected outcomes, individual
feature results, SMTP delivery and live provider configuration were not supplied.
This record does not infer those details, a model accuracy percentage, or an
independent audit. Preserve any private test records outside Git.

## Automated release acceptance

Required checks must pass on the final integration and promoted release commits:
repository quality; backend unit and isolated PostgreSQL/Redis integration;
frontend contracts, lint, unit, production build and Chromium/Firefox/WebKit;
ML evidence including Windows fixture materialization; production dependency
audits; and TLS/encrypted backup/restore smoke.

The release-preparation change prevents opening an empty reviewed-category menu
before matching options load. Its browser workflow deliberately holds the
category response until the disabled state is checked, then selects the category
and verifies the persisted correction payload and exact dashboard amount.
No failure is hidden by increasing timeouts, enabling retries or removing checks.

## Release scope

The target is an academic/source release. It includes implemented application
workflows, reproducible synthetic evidence, setup and production runbooks.
The classifier review artifact stays `production_eligible=false`; automatic ML
assignments remain prohibited. Forecast intervals remain provisional.

Public hosting requires separate host/domain/TLS, secret management, live SMTP
and AI-provider verification, monitoring and actual-host recovery acceptance in
[the production runbook](../../deployment/RUNBOOK.md). This release does not
provision infrastructure or establish those services as operational.
