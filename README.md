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

## Configuration

The reviewer has two completely separate configuration surfaces.

### Operator config (on the host)

Loaded on startup from a YAML file. By default the path is
`/etc/vidi-pr/vidi-pr.yml`; set `VIDI_PR_CONFIG` to point elsewhere. Secrets
never live in the YAML - they come from environment variables.

Minimal example:

```yaml
github:
  app_id: 123456
  private_key_path: /etc/vidi-pr/private-key.pem

llm:
  provider: openai_compat
  base_url: http://ai01.lan:8080/v1
  model: qwen2.5-coder-32b
  # Optional overrides:
  # temperature: 0.2
  # timeout_seconds: 600
  # max_tokens: 4096

server:
  host: 127.0.0.1
  port: 8080
  forwarded_allow_ips:
    - 172.18.0.0/16

storage:
  db_path: /var/lib/vidi-pr/vidi-pr.db

logging:
  level: INFO
  format: json   # json | console

pipeline:
  max_files: 50
  max_chunks: 5
  max_chunk_chars: 80000
  max_conversation_chars: 15000
  max_concurrent_reviews: 1
  job_timeout_seconds: 900
  failure_comment_cooldown_seconds: 3600

defaults:
  enabled: true
  allowed_associations: [OWNER, COLLABORATOR]
  strictness: normal     # lenient | normal | strict
  include_conversation: true
```

Required environment variables:

| Variable | Purpose |
| --- | --- |
| `VIDI_PR_WEBHOOK_SECRET` | GitHub webhook HMAC secret. Required. |
| `VIDI_PR_LLM_API_KEY`    | LLM endpoint API key. Optional (omit for unauthenticated local endpoints). |

Any non-secret YAML field can also be overridden at runtime via env vars of the
form `VIDI_PR_<SECTION>__<FIELD>` (double underscore is the section
delimiter), e.g. `VIDI_PR_LOGGING__LEVEL=DEBUG`. Env vars take precedence over
the YAML file.

### Per-repo config

Each repository being reviewed can supply `.github/vidi-pr.yml`. The
reviewer reads this file from the repo's **default branch** (always trusted),
or - if the PR's base branch is listed in the default-branch config's
`trusted_base_branches` - from that base branch.

Example:

```yaml
enabled: true

# Who may trigger reviews via `@vidi-pr review` comments.
allowed_users:
  - stylesuxx
allowed_associations: [OWNER, COLLABORATOR]

# Branches that may also serve as the source of this config.
trusted_base_branches:
  - develop

review:
  # Free-form project context injected into the review prompt.
  project_context: |
    Drupal 11 module for the SCX24 parts catalog.
    Follow Drupal coding standards. Flag business logic in .module files.

  # Optional: path (in this repo, same trusted ref) to a longer prompt file.
  # If both are set, the file content overrides the inline value.
  # project_context_file: .github/reviewer-context.md

  # Merged with the reviewer's built-in language defaults.
  language_notes:
    php: "Watch for SQL injection in db_query(); prefer entity API."

  focus:
    - security
    - performance

  ignore:
    - vendor/**
    - "*.min.js"

  include_conversation: true
  strictness: normal     # lenient | normal | strict
```

If `.github/vidi-pr.yml` is absent on the trusted ref, the operator's
`defaults` block is used and triggers are restricted to repository owners.
