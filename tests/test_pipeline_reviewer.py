from __future__ import annotations

from typing import cast

from mocks.github import MockGitHubClient
from mocks.llm import MockLLMClient

from vidi_pr.config.defaults import Strictness
from vidi_pr.config.operator import DefaultsConfig, LLMConfig, PipelineConfig
from vidi_pr.llm.client import LLMClient
from vidi_pr.llm.errors import LLMPermanentError, LLMTransientError
from vidi_pr.llm.types import ChatResponse, TokenUsage
from vidi_pr.models.review import (
    ChangedFile,
    FileStatus,
    PRInfo,
    RepoInfo,
)
from vidi_pr.models.storage import Job, JobStatus, JobStatusDetail, JobType, TriggerKind
from vidi_pr.pipeline.reviewer import Reviewer
from vidi_pr.storage.db import utcnow
from vidi_pr.transport.errors import GitHubPermanentError
from vidi_pr.transport.github_client import GitHubClient

_INSTALLATION_ID = 42
_REPO = "stylesuxx/vidi-pr"
_PR_NUMBER = 7
_HEAD_SHA = "abc123"
_BOT_LOGIN = "vidi-pr[bot]"


def _pr(*, draft: bool = False, base_ref: str = "main", head_sha: str = _HEAD_SHA) -> PRInfo:
    return PRInfo(
        number=_PR_NUMBER,
        title="Add feature",
        body=None,
        head_sha=head_sha,
        base_ref=base_ref,
        author_login="stylesuxx",
        draft=draft,
    )


def _file(name: str, *, patch_size: int = 100, patch: str | None = None) -> ChangedFile:
    return ChangedFile(
        filename=name,
        status=FileStatus.MODIFIED,
        additions=1,
        deletions=0,
        patch=patch if patch is not None else ("x" * patch_size),
    )


def _binary_file(name: str = "image.png") -> ChangedFile:
    return ChangedFile(
        filename=name,
        status=FileStatus.MODIFIED,
        additions=0,
        deletions=0,
        patch=None,
    )


def _repo_info() -> RepoInfo:
    return RepoInfo(full_name=_REPO, default_branch="main", private=False)


def _job(*, head_sha: str = _HEAD_SHA, extra_context: str | None = None) -> Job:
    now = utcnow()
    return Job(
        id=1,
        job_type=JobType.REVIEW,
        installation_id=_INSTALLATION_ID,
        repo=_REPO,
        pr_number=_PR_NUMBER,
        head_sha=head_sha,
        trigger_kind=TriggerKind.AUTO,
        extra_context=extra_context,
        status=JobStatus.RUNNING,
        status_detail=None,
        attempts=0,
        created_at=now,
        updated_at=now,
        error=None,
    )


_FOUR_SECTION_OK = (
    "## Summary\n\nOK\n\n"
    "## Findings\n\n(none)\n\n"
    "## Suggestions\n\n(none)\n\n"
    "## Positives\n\n- nice"
)


def _good_response(content: str = _FOUR_SECTION_OK) -> ChatResponse:
    return ChatResponse(
        content=content,
        model="mock",
        usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )


def _llm_config() -> LLMConfig:
    return LLMConfig(
        provider="openai_compat",
        base_url="http://llm.test/v1",
        model="mock-model",
    )


def _pipeline_config(**kwargs: int) -> PipelineConfig:
    return PipelineConfig(**kwargs)


def _defaults() -> DefaultsConfig:
    return DefaultsConfig(
        enabled=True,
        allowed_associations=["OWNER"],
        strictness=Strictness.NORMAL,
        include_conversation=True,
    )


def _make_reviewer(
    *,
    github: MockGitHubClient,
    llm: MockLLMClient,
    pipeline: PipelineConfig | None = None,
) -> Reviewer:
    return Reviewer(
        github_client=cast("GitHubClient", github),
        llm_client=cast("LLMClient", llm),
        defaults=_defaults(),
        pipeline_config=pipeline or _pipeline_config(),
        llm_config=_llm_config(),
        bot_login=_BOT_LOGIN,
    )


async def test_single_chunk_pr_produces_one_review_no_synthesis() -> None:
    github = MockGitHubClient(
        prs={_PR_NUMBER: _pr()},
        pr_files={_PR_NUMBER: [_file("a.py")]},
        comments={_PR_NUMBER: []},
        repos={_REPO: _repo_info()},
    )
    llm = MockLLMClient([_good_response()])

    result = await _make_reviewer(github=github, llm=llm).run(_job())

    assert result.status is JobStatus.DONE
    assert result.review_id == 1
    assert result.chunk_count == 1
    assert len(llm.calls) == 1
    assert len(github.reviews_posted) == 1


async def test_multi_chunk_pr_runs_synthesis_pass() -> None:
    big_files = [_file(f"f{i}.py", patch_size=900) for i in range(3)]
    github = MockGitHubClient(
        prs={_PR_NUMBER: _pr()},
        pr_files={_PR_NUMBER: big_files},
        comments={_PR_NUMBER: []},
        repos={_REPO: _repo_info()},
    )
    # 3 per-chunk responses + 1 synthesis response.
    sections = "## Findings\n\n## Suggestions\n\n## Positives\n\n- x"
    llm = MockLLMClient(
        [_good_response(f"## Summary\n\nchunk {i}\n\n{sections}") for i in range(3)]
        + [_good_response(f"## Summary\n\nconsolidated\n\n{sections}")]
    )

    result = await _make_reviewer(
        github=github,
        llm=llm,
        pipeline=_pipeline_config(max_chunks=5, max_chunk_chars=1_000),
    ).run(_job())

    assert result.status is JobStatus.DONE
    assert result.chunk_count == 3
    assert len(llm.calls) == 4
    assert "consolidated" in github.reviews_posted[0].body


async def test_drafted_mid_flight_is_aborted() -> None:
    github = MockGitHubClient(
        prs={_PR_NUMBER: _pr(draft=True)},
        pr_files={_PR_NUMBER: [_file("a.py")]},
        comments={_PR_NUMBER: []},
        repos={_REPO: _repo_info()},
    )
    llm = MockLLMClient([_good_response()])

    result = await _make_reviewer(github=github, llm=llm).run(_job())

    assert result.status is JobStatus.DONE
    assert result.status_detail == JobStatusDetail.DRAFTED_AFTER_EVENT
    assert llm.calls == []
    assert github.reviews_posted == []


async def test_all_files_filtered_yields_no_reviewable_files() -> None:
    github = MockGitHubClient(
        prs={_PR_NUMBER: _pr()},
        pr_files={_PR_NUMBER: [_binary_file()]},
        comments={_PR_NUMBER: []},
        repos={_REPO: _repo_info()},
    )
    llm = MockLLMClient([])

    result = await _make_reviewer(github=github, llm=llm).run(_job())

    assert result.status is JobStatus.DONE
    assert result.status_detail == JobStatusDetail.NO_REVIEWABLE_FILES
    assert github.reviews_posted == []


async def test_ignore_globs_skip_matching_files() -> None:
    github = MockGitHubClient(
        prs={_PR_NUMBER: _pr()},
        pr_files={_PR_NUMBER: [_file("vendor/lib.js"), _file("src/main.py")]},
        comments={_PR_NUMBER: []},
        repos={_REPO: _repo_info()},
        files={
            (_REPO, "main", ".github/vidi-pr.yml"): "review:\n  ignore:\n    - vendor/**\n",
        },
    )
    llm = MockLLMClient([_good_response()])

    result = await _make_reviewer(github=github, llm=llm).run(_job())

    assert result.status is JobStatus.DONE

    # The diff in the prompt should reference only the non-ignored file.
    user_prompt = llm.calls[0].messages[1].content
    assert "src/main.py" in user_prompt
    assert "vendor/lib.js" not in user_prompt


async def test_chunk_overflow_lists_skipped_files_in_footer() -> None:
    # 3 big files but only 1 chunk slot of 1 KB
    github = MockGitHubClient(
        prs={_PR_NUMBER: _pr()},
        pr_files={
            _PR_NUMBER: [
                _file("a.py", patch_size=900),
                _file("b.py", patch_size=900),
                _file("c.py", patch_size=900),
            ]
        },
        comments={_PR_NUMBER: []},
        repos={_REPO: _repo_info()},
    )
    llm = MockLLMClient([_good_response()])

    result = await _make_reviewer(
        github=github,
        llm=llm,
        pipeline=_pipeline_config(max_chunks=1, max_chunk_chars=1_000),
    ).run(_job())

    assert result.status is JobStatus.DONE
    body = github.reviews_posted[0].body
    assert "Not reviewed due to size" in body


async def test_parse_failed_output_still_posts_raw_in_blockquote() -> None:
    github = MockGitHubClient(
        prs={_PR_NUMBER: _pr()},
        pr_files={_PR_NUMBER: [_file("a.py")]},
        comments={_PR_NUMBER: []},
        repos={_REPO: _repo_info()},
    )
    llm = MockLLMClient(
        [
            ChatResponse(content="free-form blob with no headings", model="m", usage=TokenUsage()),
        ]
    )

    result = await _make_reviewer(github=github, llm=llm).run(_job())

    assert result.status is JobStatus.DONE
    assert result.status_detail == JobStatusDetail.PARSE_FAILED
    body = github.reviews_posted[0].body
    assert "> free-form blob with no headings" in body


async def test_llm_permanent_failure_results_in_failed_job_with_failure_message() -> None:
    class FailingClient:
        async def chat(self, *args: object, **kwargs: object) -> ChatResponse:
            raise LLMPermanentError("400")

    github = MockGitHubClient(
        prs={_PR_NUMBER: _pr()},
        pr_files={_PR_NUMBER: [_file("a.py")]},
        comments={_PR_NUMBER: []},
        repos={_REPO: _repo_info()},
    )

    reviewer = Reviewer(
        github_client=cast("GitHubClient", github),
        llm_client=cast("LLMClient", FailingClient()),
        defaults=_defaults(),
        pipeline_config=_pipeline_config(),
        llm_config=_llm_config(),
        bot_login=_BOT_LOGIN,
    )
    result = await reviewer.run(_job())

    assert result.status is JobStatus.FAILED
    assert result.status_detail == JobStatusDetail.LLM_FAILURE
    assert result.failure_message is not None


async def test_llm_transient_failure_after_retries_results_in_failed_job() -> None:
    class TransientClient:
        async def chat(self, *args: object, **kwargs: object) -> ChatResponse:
            raise LLMTransientError("503")

    github = MockGitHubClient(
        prs={_PR_NUMBER: _pr()},
        pr_files={_PR_NUMBER: [_file("a.py")]},
        comments={_PR_NUMBER: []},
        repos={_REPO: _repo_info()},
    )

    reviewer = Reviewer(
        github_client=cast("GitHubClient", github),
        llm_client=cast("LLMClient", TransientClient()),
        defaults=_defaults(),
        pipeline_config=_pipeline_config(),
        llm_config=_llm_config(),
        bot_login=_BOT_LOGIN,
    )
    result = await reviewer.run(_job())

    assert result.status is JobStatus.FAILED
    assert result.status_detail == JobStatusDetail.LLM_FAILURE


async def test_github_permanent_on_post_marks_pr_closed() -> None:
    github = MockGitHubClient(
        prs={_PR_NUMBER: _pr()},
        pr_files={_PR_NUMBER: [_file("a.py")]},
        comments={_PR_NUMBER: []},
        repos={_REPO: _repo_info()},
    )
    github.queue_post_failures(GitHubPermanentError("422 cannot review closed PR"))
    llm = MockLLMClient([_good_response()])

    result = await _make_reviewer(github=github, llm=llm).run(_job())

    assert result.status is JobStatus.DONE
    assert result.status_detail == JobStatusDetail.PR_CLOSED
    assert github.reviews_posted == []
    assert result.failure_message is None
