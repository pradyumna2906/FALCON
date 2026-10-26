# Deployment

This directory contains Docker, environment and deployment configuration.

Deployment assets must use environment-based configuration and must never contain secrets. Local-development and production concerns should remain clearly separated.

Use [RUNBOOK.md](RUNBOOK.md) for the Phase 13 production package, activation
decisions, migrations, worker operations, secret rotation and recovery.
`compose.production.yaml` is separate from the root development Compose file.
