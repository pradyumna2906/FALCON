# ML Evaluation Reports

This directory contains reviewable evaluation metadata, not serialized model
artifacts or private training examples.

`classification_evaluation_2026_1.json` records the deterministic Phase 7.4
comparison contract, split identity, candidate metrics, confidence thresholds,
library versions, hyperparameters, and in-memory artifact checksums. Timing and
peak-memory measurements can vary by machine. Because its source dataset is
synthetic, `production_eligible` is deliberately false.
