# Development Environment

FALCON uses pinned runtime versions so development, testing and CI behave consistently.

## Runtime baseline

| Tool | Required version | Declaration |
| --- | --- | --- |
| Python | 3.13.15 | `.python-version` |
| Node.js | 24.19.0 LTS | `.nvmrc` |
| npm | 11.17.0 | Bundled with Node.js 24.19.0 |

Python 3.14 may remain installed, but FALCON backend environments and commands must use Python 3.13.15.

## Verification

Run these commands from the repository root:

```powershell
py -3.13 --version
node --version
npm --version
```

Expected output:

```text
Python 3.13.15
v24.19.0
11.17.0
```

## Development rules

- Use an isolated Python virtual environment when the backend is initialized.
- Install frontend packages only inside the frontend workspace.
- Never commit virtual environments, dependencies, secrets or generated data.
- Update runtime pins and this document together through a focused pull request.
