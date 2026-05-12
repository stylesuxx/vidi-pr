# vidi-pr

Self-hosted GitHub App that performs LLM-based code reviews on pull requests.

This repository is in early development. The current state is a project skeleton
with the toolchain wired up (formatting, linting, type checking, tests). No
review functionality exists yet.

## Prerequisites

- Python 3.14
- [uv](https://docs.astral.sh/uv/) for environment, dependency, and Python
  version management

`uv` will install the pinned Python version automatically on first sync.

## Setup

Clone the repository and install the development environment:

```sh
uv sync --all-groups
```

This creates a virtual environment under `.venv/` and installs all runtime and
development dependencies pinned in `uv.lock`.

## Common commands

| Task                 | Command                          |
| -------------------- | -------------------------------- |
| Run tests            | `uv run pytest`                  |
| Lint                 | `uv run ruff check`              |
| Check formatting     | `uv run ruff format --check`     |
| Apply formatting     | `uv run ruff format`             |
| Type-check the code  | `uv run mypy src`                |
| Install git hooks    | `uv run pre-commit install`      |
| Run all hooks now    | `uv run pre-commit run --all-files` |

The same checks (`ruff check`, `ruff format --check`, `mypy src`, `pytest`) run
in CI on every push and pull request.
