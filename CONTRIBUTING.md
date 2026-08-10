# Contributing to FALCON

FALCON is developed incrementally by a four-member team. Every change must be focused, reviewable, testable and safe to reverse.

## Branch model

- `main` contains stable, demonstration-ready milestones.
- `develop` contains reviewed and integrated work.
- Create work branches from the latest `develop`.
- Use `feature/<topic>`, `fix/<topic>`, `docs/<topic>` or `chore/<topic>`.
- Never commit directly to `main` or `develop`.
- Delete work branches after merge and local synchronization.

## Before starting work

1. Fetch the latest remote state.
2. Fast-forward the local `develop` branch.
3. Confirm that the working tree is clean.
4. Create one focused work branch.
5. Define the purpose, scope, architecture fit, validation and owner.

## Implementation rules

- Keep frontend, backend, data, ML and reporting responsibilities separated.
- Keep authentication, authorization, validation and financial calculations authoritative in the backend.
- Add or update relevant tests with implementation changes.
- Update documentation when behaviour, setup or architecture changes.
- Avoid unrelated formatting or refactoring in focused changes.
- Do not add dependencies without documenting their purpose and compatibility.
- Record material architectural decisions in an Architecture Decision Record.

## Repository quality checks

Install the pinned repository-check runner in the active Python environment, then install its Git hook:

```powershell
python -m pip install "pre-commit==4.6.1"
python -m pre_commit install
```

Before every commit, run the complete repository checks and validate the Compose configuration:

```powershell
python -m pre_commit run --all-files --show-diff-on-failure
docker compose --env-file .env.example config --quiet
```

The `Repository quality` GitHub Actions workflow runs the same checks for pull requests and pushes targeting `develop` or `main`. Fix all failures before merge.

Backend linting, type checking and tests; frontend linting, type checking, tests and builds; and ML validation will be added when their project manifests and executable code exist.

## Security and financial-data rules

- Never commit secrets, tokens, credentials, private connection strings or local `.env` files.
- Never commit real bank statements, payment exports or personal financial records.
- Use synthetic or explicitly approved de-identified development data.
- Validate uploaded file type, size and content before processing.
- Enforce server-side ownership checks for every user-owned resource.
- Report a discovered secret or personal-data exposure immediately and rotate affected credentials.

## Commits

- Use Conventional Commit prefixes such as `feat`, `fix`, `docs`, `test`, `refactor`, `chore`, `ci` or `build`.
- Use a concise imperative subject with an optional scope.
- Keep each commit limited to one coherent change.
- Commit only after applicable validation passes.

Example:

`docs(repo): add contribution workflow`

## Pull requests

- Target `develop` for normal work.
- Target `main` only for approved release or milestone promotion.
- Open a draft pull request while work is incomplete.
- Explain what changed, why it is needed and what remains out of scope.
- List the exact validation performed.
- Describe security, privacy, data and migration effects.
- Request review from an appropriate repository collaborator.
- Resolve review discussions before merge.
- Use squash merge by default for a focused work branch.

## Definition of done

A change is complete only when:

- The agreed scope is implemented.
- Applicable tests and checks pass.
- Documentation is current.
- Security and privacy effects are reviewed.
- The pull request is reviewed and merged.
- Local and remote branches are synchronized and obsolete work branches are deleted.
