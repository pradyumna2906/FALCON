# Scripts

This directory contains repeatable development, validation, setup and synthetic-data-generation utilities.

Every script must document its inputs, outputs and prerequisites, avoid embedded credentials and fail safely without silently corrupting data.

`build_classification_evidence.py` deterministically builds the synthetic Phase
7.4 dataset, checksum manifest, and rules/ML comparison report. It requires the
backend `ml` extra and never persists a model binary or reads user data.
