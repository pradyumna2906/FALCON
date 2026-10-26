# ML Artifacts

Generated model binaries and training outputs are intentionally excluded from version control.

Phase 7.5 stores local classification artifacts as
`classification/<model_version>/model.pkl` beside a strict generated
`manifest.json`. Both remain ignored because deployment artifacts require an
approved storage and release process.

From the repository root, install the backend `ml` extra and run:

```text
PYTHONPATH=backend/src python scripts/package_classification_model.py
```

The command rebuilds the synthetic comparison, verifies the selected bytes
against the published evaluation checksum, and packages
`classification_2026_1_demo.1`. That model is explicitly provisional and can
suggest classifications but is not eligible for automatic ML assignment.

The runtime registry verifies manifest identity, artifact size and SHA-256,
feature/taxonomy compatibility, and exact training library versions before
trusted deserialization. Never accept artifact paths, manifests, or serialized
estimators from an API client.
