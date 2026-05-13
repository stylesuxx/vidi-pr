from __future__ import annotations

from ipaddress import IPv4Network
from pathlib import Path
from typing import cast

from mocks.github import MockGitHubClient
from mocks.llm import MockLLMClient

from vidi_pr.config.defaults import Strictness
from vidi_pr.config.operator import (
    DefaultsConfig,
    GitHubConfig,
    LLMConfig,
    LoggingConfig,
    OperatorConfig,
    PipelineConfig,
    ServerConfig,
    StorageConfig,
)
from vidi_pr.llm.types import ChatResponse, TokenUsage
from vidi_pr.models.review import (
    ChangedFile,
    FileStatus,
    PRInfo,
    RepoInfo,
)
from vidi_pr.models.storage import JobStatus, JobStatusDetail, JobType, TriggerKind
from vidi_pr.pipeline.reviewer import Reviewer
from vidi_pr.pipeline.worker import Worker
from vidi_pr.storage.db import Database
from vidi_pr.storage.jobs import insert_job, list_jobs_with_status
from vidi_pr.storage.locks import acquire_lock, fetch_lock
from vidi_pr.storage.reviews import list_reviews_for_pr
from vidi_pr.transport.github_client import GitHubClient

_REPO = "stylesuxx/vidi-pr"
_PR_NUMBER = 7
_INSTALLATION_ID = 42
_HEAD_SHA = "abc123"
_BOT_LOGIN = "vidi-pr[bot]"


def _pr() -> PRInfo:
    return PRInfo(
        number=_PR_NUMBER,
        title="t",
        body=None,
        head_sha=_HEAD_SHA,
        base_ref="main",
        author_login="stylesuxx",
        draft=False,
    )


def _file() -> ChangedFile:
    return ChangedFile(
        filename="a.py",
        status=FileStatus.MODIFIED,
        additions=1,
        deletions=0,
        patch="@@\n+x\n",
    )


def _operator_config(db_path: Path, *, job_timeout: int = 900) -> OperatorConfig:
    return OperatorConfig(
        github=GitHubConfig(app_id=1, private_key_path=Path("/tmp/key.pem")),
        llm=LLMConfig(provider="openai_compat", base_url="http://llm.test/v1", model="m"),
        server=ServerConfig(
            host="127.0.0.1",
            port=8080,
            forwarded_allow_ips=[IPv4Network("127.0.0.0/8")],
        ),
        storage=StorageConfig(db_path=db_path),
        logging=LoggingConfig(),
        pipeline=PipelineConfig(
            job_timeout_seconds=job_timeout,
            failure_comment_cooldown_seconds=3600,
        ),
        defaults=DefaultsConfig(
            enabled=True,
            allowed_associations=["OWNER"],
            strictness=Strictness.NORMAL,
            include_conversation=True,
        ),
        webhook_secret="x",
    )


def _good_response() -> ChatResponse:
    return ChatResponse(
        content="## Summary\n\nOK\n\n## Findings\n\n## Suggestions\n\n## Positives\n\n- nice",
        model="mock",
        usage=TokenUsage(),
    )


async def _enqueue_pending(database: Database) -> int:
    async with database.sessionmaker() as session:
        job = await insert_job(
            session,
            job_type=JobType.REVIEW,
            installation_id=_INSTALLATION_ID,
            repo=_REPO,
            pr_number=_PR_NUMBER,
            head_sha=_HEAD_SHA,
            trigger_kind=TriggerKind.AUTO,
        )

        await acquire_lock(session, repo=_REPO, pr_number=_PR_NUMBER, job_id=job.id)
        await session.commit()

        return job.id


def _make_worker(
    *,
    database: Database,
    github: MockGitHubClient,
    llm: MockLLMClient,
    tmp_path: Path,
    job_timeout: int = 900,
) -> Worker:
    config = _operator_config(tmp_path / "ignored.db", job_timeout=job_timeout)
    reviewer = Reviewer(
        github_client=cast("GitHubClient", github),
        llm_client=llm,
        defaults=config.defaults,
        pipeline_config=config.pipeline,
        llm_config=config.llm,
        bot_login=_BOT_LOGIN,
    )
    return Worker(
        database=database,
        github_client=cast("GitHubClient", github),
        reviewer=reviewer,
        operator_config=config,
    )


async def test_process_one_runs_a_queued_job_and_marks_done(
    database: Database, tmp_path: Path
) -> None:
    github = MockGitHubClient(
        prs={_PR_NUMBER: _pr()},
        pr_files={_PR_NUMBER: [_file()]},
        comments={_PR_NUMBER: []},
        repos={_REPO: _repo_info_for_main()},
    )
    llm = MockLLMClient([_good_response()])
    job_id = await _enqueue_pending(database)
    worker = _make_worker(database=database, github=github, llm=llm, tmp_path=tmp_path)

    processed = await worker.process_one()

    assert processed is True
    async with database.sessionmaker() as session:
        done = await list_jobs_with_status(session, JobStatus.DONE)
        assert [j.id for j in done] == [job_id]
        assert await fetch_lock(session, repo=_REPO, pr_number=_PR_NUMBER) is None
        reviews = await list_reviews_for_pr(session, repo=_REPO, pr_number=_PR_NUMBER)
        assert len(reviews) == 1


async def test_process_one_returns_false_when_queue_empty(
    database: Database, tmp_path: Path
) -> None:
    github = MockGitHubClient()
    llm = MockLLMClient([])
    worker = _make_worker(database=database, github=github, llm=llm, tmp_path=tmp_path)

    processed = await worker.process_one()
    assert processed is False


async def test_worker_releases_lock_and_records_failure_comment_on_timeout(
    database: Database, tmp_path: Path
) -> None:
    class SlowLLM:
        async def chat(self, *args: object, **kwargs: object) -> ChatResponse:
            import asyncio

            await asyncio.sleep(2.0)
            return _good_response()

    github = MockGitHubClient(
        prs={_PR_NUMBER: _pr()},
        pr_files={_PR_NUMBER: [_file()]},
        comments={_PR_NUMBER: []},
        repos={_REPO: _repo_info_for_main()},
    )
    await _enqueue_pending(database)
    worker = _make_worker(
        database=database,
        github=github,
        llm=cast("MockLLMClient", SlowLLM()),
        tmp_path=tmp_path,
        job_timeout=1,
    )

    await worker.process_one()

    async with database.sessionmaker() as session:
        failed = await list_jobs_with_status(session, JobStatus.FAILED)
        assert len(failed) == 1
        assert failed[0].status_detail == JobStatusDetail.TIMEOUT
        assert await fetch_lock(session, repo=_REPO, pr_number=_PR_NUMBER) is None

    assert len(github.comments_posted) == 1
    assert "timed out" in github.comments_posted[0].body


def _repo_info_for_main() -> RepoInfo:
    return RepoInfo(full_name=_REPO, default_branch="main", private=False)
