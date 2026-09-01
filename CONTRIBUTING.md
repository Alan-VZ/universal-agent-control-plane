# Contributing

Thank you for helping improve the Universal Agent Control Plane.

## Before you start

- Search existing issues and pull requests before opening a duplicate.
- Open an issue before a large architectural or behavior-changing contribution.
- Never include API keys, tokens, private prompts, user state, or machine-specific paths.
- Follow the repository instructions in `AGENTS.md`.

## Development setup

```powershell
git clone https://github.com/Alan-VZ/universal-agent-control-plane.git
Set-Location universal-agent-control-plane
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Python 3.10 through 3.13 is supported.

## Validate a change

Run the smallest relevant test selection while developing, then run the full suite before
opening a pull request:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

If the architecture changes, update `README.md` and
`docs/universal-agent-control-plane.html` in the same pull request. Open the diagram in a
browser and confirm that its labels, connectors, and accessible description remain correct.

## Pull requests

- Keep changes focused and explain the user-visible behavior.
- Add or update tests when behavior changes.
- Update directly affected documentation and `CHANGELOG.md`.
- Confirm that no local runtime data from `.data/` or `.venv/` is included.
- Allow maintainers to edit the branch so small integration fixes can be applied.

By contributing, you agree that your contribution is licensed under the MIT License.
