"""
Dry-run review inspector.

Fetches a PR by URL, runs the exact review pipeline `run` uses, and prints the
review body that *would* be posted (plus, optionally, the prompts sent to the
model) instead of posting anything to GitHub. Intended for sanity-checking and
tuning prompts against real PRs.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import structlog
import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from vidi_pr.config.operator import DefaultsConfig, LLMConfig, PipelineConfig
from vidi_pr.errors import VidiPrError
from vidi_pr.llm.client import OpenAICompatClient
from vidi_pr.models.storage import Job, JobStatus, JobType, TriggerKind
from vidi_pr.orchestration.handlers import DEFAULT_BOT_LOGIN
from vidi_pr.pipeline.reviewer import RenderedReview, Reviewer
from vidi_pr.storage.db import utcnow
from vidi_pr.transport.errors import GitHubError
from vidi_pr.transport.github_client import GitHubClient

_TOKEN_ENV_VARS = ("VIDI_PR_GITHUB_TOKEN", "GITHUB_TOKEN")
_LLM_API_KEY_ENV = "VIDI_PR_LLM_API_KEY"

_PR_URL_RE = re.compile(r"github\.com[/:](?P<owner>[^/\s]+)/(?P<repo>[^/\s]+)/pull/(?P<number>\d+)")
_PR_SHORT_RE = re.compile(r"^(?P<owner>[^/\s]+)/(?P<repo>[^/#\s]+)#(?P<number>\d+)$")


class DryRunError(VidiPrError):
    pass


class DryRunConfig(BaseModel):
    """
    Minimal config for the dry-run inspector: only the LLM section is required.

    Loaded from the same YAML file as the operator config (the `github`,
    `server`, `storage`, etc. sections are ignored), or from a tiny file that
    holds just `llm:`. The LLM API key still comes from `VIDI_PR_LLM_API_KEY`.
    """

    model_config = ConfigDict(extra="ignore")

    llm: LLMConfig
    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)
    defaults: DefaultsConfig = Field(default_factory=DefaultsConfig)

    @classmethod
    def load(cls, path: Path | str) -> DryRunConfig:
        config_path = Path(path)
        try:
            text = config_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise DryRunError(f"config not readable at {config_path}: {exc}") from exc

        try:
            data = yaml.safe_load(text) or {}
        except yaml.YAMLError as exc:
            raise DryRunError(f"config at {config_path} is not valid YAML: {exc}") from exc

        if not isinstance(data, dict):
            raise DryRunError(f"config at {config_path} must be a YAML mapping")

        try:
            return cls.model_validate(data)
        except ValidationError as exc:
            raise DryRunError(f"config at {config_path} failed validation: {exc}") from exc


def parse_pr_url(value: str) -> tuple[str, int]:
    """Parse a PR URL or `owner/repo#number` into `("owner/repo", number)`."""
    text = value.strip()
    match = _PR_URL_RE.search(text) or _PR_SHORT_RE.match(text)
    if match is None:
        raise DryRunError(
            f"could not parse a PR reference from {value!r}; expected a URL like "
            "https://github.com/owner/repo/pull/123 or owner/repo#123"
        )

    repo = f"{match['owner']}/{match['repo']}"
    return repo, int(match["number"])


def _github_token() -> str | None:
    for name in _TOKEN_ENV_VARS:
        token = os.environ.get(name)
        if token:
            return token

    return None


def _build_job(repo: str, pr_number: int, extra_context: str | None) -> Job:
    now = utcnow()
    return Job(
        job_type=JobType.REVIEW,
        installation_id=0,
        repo=repo,
        pr_number=pr_number,
        head_sha="",
        trigger_kind=TriggerKind.COMMENT,
        extra_context=extra_context,
        status=JobStatus.RUNNING,
        status_detail=None,
        attempts=0,
        created_at=now,
        updated_at=now,
        error=None,
    )


async def render_pr(
    *,
    repo: str,
    pr_number: int,
    config: DryRunConfig,
    token: str | None,
    extra_context: str | None = None,
) -> RenderedReview:
    github = GitHubClient.from_token(token)
    llm = OpenAICompatClient(
        base_url=config.llm.base_url,
        model=config.llm.model,
        api_key=os.environ.get(_LLM_API_KEY_ENV),
        timeout=float(config.llm.timeout_seconds),
        extra_body=config.llm.extra_body,
    )
    reviewer = Reviewer(
        github_client=github,
        llm_client=llm,
        defaults=config.defaults,
        pipeline_config=config.pipeline,
        llm_config=config.llm,
        bot_login=DEFAULT_BOT_LOGIN,
    )

    try:
        return await reviewer.prepare(
            _build_job(repo, pr_number, extra_context), skip_draft_check=True
        )
    finally:
        await llm.aclose()
        await github.aclose()


def format_report(
    *,
    repo: str,
    pr_number: int,
    model: str,
    rendered: RenderedReview,
    dump_prompts: bool,
) -> tuple[str, str]:
    """Return `(stdout, stderr)`: the review body, and a human-readable summary."""
    header_lines = [
        f"# dry-run: {repo}#{pr_number}",
        f"model: {model}",
    ]

    if rendered.early_result is not None:
        result = rendered.early_result
        header_lines.append(f"status: {result.status.value}")
        if result.status_detail is not None:
            header_lines.append(f"detail: {result.status_detail}")
        if result.error:
            header_lines.append(f"error: {result.error}")
        stdout = f"(no review body: {result.status_detail or result.status.value})"
        return stdout, "\n".join(header_lines)

    header_lines.extend(
        [
            f"chunks: {rendered.chunk_count}",
            f"tokens: {rendered.prompt_tokens} prompt / {rendered.completion_tokens} completion",
            f"duration: {rendered.duration_seconds:.1f}s",
            f"parse_failed: {rendered.status_detail is not None}",
        ]
    )

    if dump_prompts:
        for dump in rendered.prompts:
            header_lines.append(f"\n===== prompt: {dump.label} =====")
            for message in dump.messages:
                header_lines.append(f"\n----- {message.role.value} -----")
                header_lines.append(message.content)

    return rendered.body or "", "\n".join(header_lines)


async def run_dry_run(
    *,
    url: str,
    config_path: Path | str,
    dump_prompts: bool,
    context: str | None = None,
) -> int:
    # Keep stdout clean (it carries the review body); send progress logs to stderr.
    structlog.configure(logger_factory=structlog.PrintLoggerFactory(file=sys.stderr))

    repo, pr_number = parse_pr_url(url)
    config = DryRunConfig.load(config_path)
    token = _github_token()
    if token is None:
        print(
            "warning: no GitHub token in "
            f"{' or '.join(_TOKEN_ENV_VARS)}; only public PRs will be reachable",
            file=sys.stderr,
        )

    try:
        rendered = await render_pr(
            repo=repo, pr_number=pr_number, config=config, token=token, extra_context=context
        )
    except GitHubError as exc:
        hint = " Set GITHUB_TOKEN to raise the limit." if "rate limited" in str(exc) else ""
        print(f"GitHub fetch failed: {exc}.{hint}", file=sys.stderr)
        return 2
    stdout, stderr = format_report(
        repo=repo,
        pr_number=pr_number,
        model=config.llm.model,
        rendered=rendered,
        dump_prompts=dump_prompts,
    )
    print(stderr, file=sys.stderr)
    print(stdout)

    return 0 if rendered.early_result is None else 1
