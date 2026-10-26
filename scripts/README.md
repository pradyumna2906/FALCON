# Scripts

This directory contains repeatable development, validation, setup and synthetic-data-generation utilities.

Every script must document its inputs, outputs and prerequisites, avoid embedded credentials and fail safely without silently corrupting data.

`build_classification_evidence.py` deterministically builds the synthetic Phase
7.4 dataset, checksum manifest, and rules/ML comparison report. It requires the
backend `ml` extra and never persists a model binary or reads user data.

`package_classification_model.py` rebuilds that comparison and packages the
selected provisional estimator into the ignored local Phase 7.5 registry. It
refuses to replace an existing model version unless `--overwrite` is explicit.

## Final review ML evidence

- `build_review_datasets.py`: deterministic, versioned synthetic fixtures;
  refuses to overwrite an existing version manifest.
- `evaluate_review_models.py`: classification learning curves, chronological
  forecast comparisons, offline assistant guards, arithmetic/HiGHS checks and
  feature-extraction performance. No live AI calls or database writes.
- `evaluate_classifier_validation.py`: preserved character-feature validation
  experiment; never reads final-test rows for fitting or scoring.
- `package_classification_model.py`: defaults to the version 3 review classifier;
  `--dataset reference` explicitly selects the original small fixture generator.
- `check_classifier_integration.py`: actual FastAPI factory, lazy load/cache and
  synthetic-model automatic-assignment guard verification, without a database.
- `check_review_evidence.py`: machine-readable evidence contract checks;
  reports an unmet 90% target honestly rather than suppressing it.
- `prepare-review.ps1`: Windows dependency/data/model preparation. Explicit
  `-SetModelConfiguration` updates only two classifier entries in the private
  root `.env`, retaining the rest of the configuration.

See `docs/testing/FINAL_REVIEW.md` for startup, reproduction and release gates.
