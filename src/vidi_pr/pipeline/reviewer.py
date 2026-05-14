from __future__ import annotations

import time
from dataclasses import dataclass

import structlog
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from vidi_pr.config.operator import DefaultsConfig, LLMConfig, PipelineConfig
from vidi_pr.config.repo import RepoConfig, RepoConfigLoader, is_ignored
from vidi_pr.llm.client import LLMClient
from vidi_pr.llm.errors import LLMError
from vidi_pr.models.review import (
    ChangedFile,
    Chunk,
    ParsedReview,
    PRContent,
    PRInfo,
)
from vidi_pr.models.storage import Job, JobStatus, JobStatusDetail
from vidi_pr.pipeline.chunking import pack_chunks
from vidi_pr.pipeline.fetcher import fetch_pr_content
from vidi_pr.pipeline.parsing import parse_review_output
from vidi_pr.prompts.composer import compose_review_prompt, compose_synthesis_prompt
from vidi_pr.prompts.footer import render_footer
from vidi_pr.transport.errors import GitHubError, GitHubPermanentError, GitHubTransientError
from vidi_pr.transport.github_client import GitHubClient

# Empirically GitHub caps review bodies near this size; we cap our output a
# little under to leave headroom for the truncation note.
_MAX_REVIEW_BODY = 65_536
_TRUNCATION_NOTE = "\n\n_(review truncated to fit GitHub's body length limit)_"

_logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ReviewResult:
    status: JobStatus
    status_detail: JobStatusDetail | None = None
    review_id: int | None = None
    duration_seconds: float = 0.0
    chunk_count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    error: str | None = None
    failure_message: str | None = None


@dataclass(frozen=True)
class _ChunksResult:
    outputs: list[ParsedReview]
    prompt_tokens: int
    completion_tokens: int
    reasoning_chars: int
    last_finish_reason: str | None


@dataclass(frozen=True)
class _SynthesisResult:
    review: ParsedReview
    prompt_tokens: int
    completion_tokens: int
    reasoning_chars: int
    last_finish_reason: str | None


class Reviewer:
    def __init__(
        self,
        *,
        github_client: GitHubClient,
        llm_client: LLMClient,
        defaults: DefaultsConfig,
        pipeline_config: PipelineConfig,
        llm_config: LLMConfig,
        bot_login: str,
    ) -> None:
        self._github = github_client
        self._llm = llm_client
        self._defaults = defaults
        self._pipeline = pipeline_config
        self._llm_config = llm_config
        self._bot_login = bot_login

    async def run(self, job: Job) -> ReviewResult:
        started = time.perf_counter()

        pr_now = await self._github.get_pr(job.installation_id, job.repo, job.pr_number)
        if pr_now.draft:
            _logger.info("review aborted: PR is draft", repo=job.repo, pr_number=job.pr_number)
            return ReviewResult(
                status=JobStatus.DONE,
                status_detail=JobStatusDetail.DRAFTED_AFTER_EVENT,
                duration_seconds=time.perf_counter() - started,
            )

        repo_config = await self._load_repo_config(job, pr_now)
        include_conversation = (
            repo_config.review.include_conversation
            if repo_config.review.include_conversation is not None
            else self._defaults.include_conversation
        )

        content = await fetch_pr_content(
            self._github,
            installation_id=job.installation_id,
            repo=job.repo,
            pr_number=job.pr_number,
            include_conversation=include_conversation,
            bot_login=self._bot_login,
        )

        eligible_files = _filter_files(content.files, repo_config)
        if not eligible_files:
            _logger.info(
                "review skipped: no reviewable files after filtering",
                repo=job.repo,
                pr_number=job.pr_number,
            )
            return ReviewResult(
                status=JobStatus.DONE,
                status_detail=JobStatusDetail.NO_REVIEWABLE_FILES,
                duration_seconds=time.perf_counter() - started,
            )

        packing = pack_chunks(
            eligible_files,
            max_files=self._pipeline.max_files,
            max_chunks=self._pipeline.max_chunks,
            max_chunk_chars=self._pipeline.max_chunk_chars,
        )
        if not packing.chunks:
            return ReviewResult(
                status=JobStatus.DONE,
                status_detail=JobStatusDetail.NO_REVIEWABLE_FILES,
                duration_seconds=time.perf_counter() - started,
            )

        try:
            chunks_result = await self._run_chunks(
                job, content.pr, content, repo_config, packing.chunks
            )
        except (LLMError, GitHubError) as exc:
            return _failure_from(exc, started, kind=JobStatusDetail.LLM_FAILURE)

        try:
            synthesis = await self._maybe_synthesize(repo_config, chunks_result.outputs)
        except (LLMError, GitHubError) as exc:
            return _failure_from(exc, started, kind=JobStatusDetail.LLM_FAILURE)

        prompt_tokens = chunks_result.prompt_tokens + synthesis.prompt_tokens
        completion_tokens = chunks_result.completion_tokens + synthesis.completion_tokens
        reasoning_chars = chunks_result.reasoning_chars + synthesis.reasoning_chars
        finish_reason = synthesis.last_finish_reason or chunks_result.last_finish_reason
        final_review = synthesis.review

        duration = time.perf_counter() - started
        body = _render_review_body(
            parsed=final_review,
            model=self._llm_config.model,
            duration_seconds=duration,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            skipped=packing.skipped,
            reasoning_chars=reasoning_chars,
            finish_reason=finish_reason,
        )

        status_detail: JobStatusDetail | None = (
            JobStatusDetail.PARSE_FAILED if final_review.parse_failed else None
        )

        try:
            review_id = await _post_with_retry(
                client=self._github,
                installation_id=job.installation_id,
                repo=job.repo,
                pr_number=job.pr_number,
                body=body,
            )
        except GitHubPermanentError as exc:
            _logger.warning(
                "review post rejected as permanent failure (assuming PR closed)",
                repo=job.repo,
                pr_number=job.pr_number,
                error=str(exc),
            )
            return ReviewResult(
                status=JobStatus.DONE,
                status_detail=JobStatusDetail.PR_CLOSED,
                duration_seconds=duration,
                chunk_count=len(packing.chunks),
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                error=str(exc),
            )
        except GitHubError as exc:
            return ReviewResult(
                status=JobStatus.FAILED,
                status_detail=JobStatusDetail.GITHUB_FAILURE,
                duration_seconds=duration,
                chunk_count=len(packing.chunks),
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                error=str(exc),
            )

        return ReviewResult(
            status=JobStatus.DONE,
            status_detail=status_detail,
            review_id=review_id,
            duration_seconds=duration,
            chunk_count=len(packing.chunks),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    async def _load_repo_config(self, job: Job, pr: PRInfo) -> RepoConfig:
        repo_data = await self._github.get_repo(job.installation_id, job.repo)
        loader = RepoConfigLoader(
            self._github.for_installation(job.installation_id),
            defaults=self._defaults,
        )
        return await loader.load(
            job.repo,
            base_ref=pr.base_ref,
            default_branch=repo_data.default_branch,
        )

    async def _run_chunks(
        self,
        job: Job,
        pr: PRInfo,
        content: PRContent,
        repo_config: RepoConfig,
        chunks: list[Chunk],
    ) -> _ChunksResult:
        outputs: list[ParsedReview] = []
        prompt_tokens = 0
        completion_tokens = 0
        reasoning_chars = 0
        last_finish_reason: str | None = None

        for index, chunk in enumerate(chunks):
            messages = compose_review_prompt(
                repo_config=repo_config,
                pr=pr,
                conversation=content.conversation,
                chunk=chunk,
                extra_context=job.extra_context,
            )
            response = await self._llm.chat(
                messages,
                temperature=self._llm_config.temperature,
                max_tokens=self._llm_config.max_tokens,
            )
            prompt_tokens += response.usage.prompt_tokens
            completion_tokens += response.usage.completion_tokens
            reasoning_chars += len(response.reasoning_content)
            last_finish_reason = response.finish_reason

            _logger.info(
                "chunk reviewed",
                repo=job.repo,
                pr_number=job.pr_number,
                chunk_index=index,
                chunk_total=len(chunks),
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                reasoning_chars=len(response.reasoning_content),
                answer_chars=len(response.content),
                finish_reason=response.finish_reason,
            )

            outputs.append(parse_review_output(response.content))

        return _ChunksResult(
            outputs=outputs,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            reasoning_chars=reasoning_chars,
            last_finish_reason=last_finish_reason,
        )

    async def _maybe_synthesize(
        self,
        repo_config: RepoConfig,
        chunk_outputs: list[ParsedReview],
    ) -> _SynthesisResult:
        if len(chunk_outputs) == 1:
            return _SynthesisResult(
                review=chunk_outputs[0],
                prompt_tokens=0,
                completion_tokens=0,
                reasoning_chars=0,
                last_finish_reason=None,
            )

        messages = compose_synthesis_prompt(
            repo_config=repo_config,
            chunk_outputs=[output.raw for output in chunk_outputs],
        )
        response = await self._llm.chat(
            messages,
            temperature=self._llm_config.temperature,
            max_tokens=self._llm_config.max_tokens,
        )

        return _SynthesisResult(
            review=parse_review_output(response.content),
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
            reasoning_chars=len(response.reasoning_content),
            last_finish_reason=response.finish_reason,
        )


def _filter_files(files: list[ChangedFile], repo_config: RepoConfig) -> list[ChangedFile]:
    return [
        file
        for file in files
        if file.patch is not None and not is_ignored(repo_config, file.filename)
    ]


def _render_review_body(
    *,
    parsed: ParsedReview,
    model: str,
    duration_seconds: float,
    prompt_tokens: int,
    completion_tokens: int,
    skipped: list[str],
    reasoning_chars: int = 0,
    finish_reason: str | None = None,
) -> str:
    if parsed.parse_failed:
        review_text = "> _Could not parse model output into the standard four sections._\n"
        review_text += _parse_failure_diagnostic(
            answer_chars=len(parsed.raw),
            reasoning_chars=reasoning_chars,
            finish_reason=finish_reason,
        )
        review_text += "\n\n"
        review_text += "\n".join(f"> {line}" for line in parsed.raw.splitlines())
    else:
        sections: list[str] = []
        for heading, content in (
            ("## Summary", parsed.summary),
            ("## Findings", parsed.findings),
            ("## Suggestions", parsed.suggestions),
            ("## Positives", parsed.positives),
        ):
            if content:
                sections.append(f"{heading}\n\n{content}")
        review_text = "\n\n".join(sections)

    if skipped:
        review_text += "\n\n## Not reviewed due to size\n\n"
        review_text += "\n".join(f"- `{name}`" for name in skipped)

    footer = render_footer(
        model=model,
        duration_seconds=duration_seconds,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )
    full = f"{review_text}\n\n{footer}"
    return _truncate(full)


def _parse_failure_diagnostic(
    *, answer_chars: int, reasoning_chars: int, finish_reason: str | None
) -> str:
    parts = [f"answer: {answer_chars} chars", f"reasoning: {reasoning_chars} chars"]
    if finish_reason is not None:
        parts.append(f"finish_reason: {finish_reason}")
    if finish_reason == "length":
        parts.append(
            "the model hit `llm.max_tokens` mid-output; raise it, or disable "
            "reasoning via `llm.extra_body`"
        )
    return f"> _({'; '.join(parts)})_"


def _truncate(body: str) -> str:
    if len(body) <= _MAX_REVIEW_BODY:
        return body

    available = _MAX_REVIEW_BODY - len(_TRUNCATION_NOTE)
    return body[:available] + _TRUNCATION_NOTE


async def _post_with_retry(
    *,
    client: GitHubClient,
    installation_id: int,
    repo: str,
    pr_number: int,
    body: str,
) -> int:
    retrying = AsyncRetrying(
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=1.0),
        retry=retry_if_exception_type(GitHubTransientError),
        reraise=True,
    )
    async for attempt in retrying:
        with attempt:
            return await client.create_review(installation_id, repo, pr_number, body)

    raise GitHubError("post-review retry loop exited without result")


def _failure_from(exc: Exception, started: float, *, kind: JobStatusDetail) -> ReviewResult:
    duration = time.perf_counter() - started
    message = str(exc)
    return ReviewResult(
        status=JobStatus.FAILED,
        status_detail=kind,
        duration_seconds=duration,
        error=message,
        failure_message=(f"vidi-pr could not complete the review: {kind} ({message[:200]})"),
    )
