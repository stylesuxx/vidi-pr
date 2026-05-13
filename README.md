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

## Running the service

The webhook receiver is started via the module entrypoint:

```sh
uv run python -m vidi_pr
```

On startup the service:

1. Loads operator configuration (see below).
2. Runs database migrations (Alembic, `head`).
3. Binds the FastAPI server to `server.host:server.port` from the operator
   config (default `127.0.0.1:8080`).
4. Accepts webhooks on `POST /webhook` and exposes `GET /healthz`.

For local development you typically expose `127.0.0.1:8080` to GitHub by way
of an SSH reverse tunnel, your existing reverse proxy, or a temporary tunnel
service. The production deployment terminates TLS at Traefik (covered in the
deployment guide once it lands).

The default `server.host` of `127.0.0.1` only accepts connections from the
same machine. If your reverse proxy lives on another host on the LAN (the
expected topology when Traefik is on a separate box), set `server.host` to
`0.0.0.0` (or the specific LAN address you want to listen on) and constrain
`server.forwarded_allow_ips` to the proxy's IP range so uvicorn only honors
`X-Forwarded-For` from there. The HMAC signature on `/webhook` is checked
regardless, but lock down the network surface anyway.

### Registering the GitHub App

1. Create a new GitHub App in your account or organization settings.
2. Webhook URL: a publicly reachable URL ending in `/webhook`, e.g.
   `https://vidi-pr.example.com/webhook`. GitHub `POST`s every event there.
3. Webhook secret: generate a random, high-entropy string yourself (for
   example `openssl rand -hex 32`) and paste it into the App's secret
   field. The same value must appear in **both** places:
   - the App's webhook secret field on GitHub,
   - the `VIDI_PR_WEBHOOK_SECRET` environment variable wherever the service
     runs.
   Mismatch produces HTTP 401 at `/webhook` and is the most common
   "nothing happens" failure mode.
4. Under *Permissions & events* → **Repository permissions** (not
   *Organization* or *Account*), grant:
   - **Contents**: Read
   - **Issues**: Read & write
   - **Pull requests**: Read & write
   - **Metadata**: Read (usually auto-selected when any of the others
     are set)
   If these end up under the wrong section, the install screen later
   shows "No repositories: this app does not require access to your
   repositories" and reviews can't happen.
5. On the same page, under **Subscribe to events**, check
   **Pull request** and **Issue comment**. (These options only appear
   once the matching Repository permissions above are set.)
6. Generate a private key, save the `.pem` file on the host, and point
   `github.private_key_path` in the YAML config at it.
7. In the App's left sidebar, click **Install App** → **Install** next
   to your account or org → **Only select repositories** → pick the
   repos you want reviewed → confirm. If you already installed the App
   before adding the permissions in step 4, click **Configure** instead
   of *Install* and accept the new permission set.

The App's *Advanced* tab has a *Recent Deliveries* view that's useful for
debugging - it shows the exact payload GitHub sent, the response code our
service returned, and a *Redeliver* button you can use to replay any event
without making a new PR.

### Local end-to-end smoke test

To verify the full path against real GitHub before deployment:

1. Make the local service reachable from github.com. Any of: an SSH reverse
   tunnel through a publicly-addressed host, your existing reverse proxy, or
   a temporary tunnel service. Point the App's webhook URL at the tunnel's
   address with the path `/webhook`.
2. Start the service: `uv run python -m vidi_pr`. Confirm uvicorn binds and
   Alembic upgrades cleanly.
3. Open a draft PR on a repo the App is installed on, then mark it ready for
   review. The bot should fetch the PR, call the LLM, and post a review
   within a few seconds. Failures surface as a single failure comment
   (cooldown-limited) and the structured logs.

This repo ships its own `.github/vidi-pr.yml` so a local-service run can review
its own PRs.

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
  base_url: http://llm.example.lan:8080/v1
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
