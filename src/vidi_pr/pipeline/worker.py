from __future__ import annotations

import asyncio
import contextlib

import structlog
from sqlalchemy import select

from vidi_pr.config.operator import OperatorConfig
from vidi_pr.models.storage import Job, JobStatus, JobStatusDetail
from vidi_pr.pipeline.failure import maybe_post_failure_comment
from vidi_pr.pipeline.reviewer import Reviewer, ReviewResult
from vidi_pr.storage.db import Database
from vidi_pr.storage.jobs import update_job_status
from vidi_pr.storage.locks import release_lock
from vidi_pr.storage.reviews import record_review_posted
from vidi_pr.transport.github_client import GitHubClient

_DEFAULT_POLL_INTERVAL = 1.0

_logger = structlog.get_logger(__name__)


class Worker:
    """
    Polls for `pending` jobs and processes them serially.

    `max_concurrent_reviews=1` keeps this loop single-flight; we claim one
    job at a time, run it under `asyncio.wait_for(job_timeout_seconds)`,
    persist the outcome, release the lock, and loop.
    """

    def __init__(
        self,
        *,
        database: Database,
        github_client: GitHubClient,
        reviewer: Reviewer,
        operator_config: OperatorConfig,
        poll_interval: float = _DEFAULT_POLL_INTERVAL,
    ) -> None:
        self._database = database
        self._github = github_client
        self._reviewer = reviewer
        self._operator_config = operator_config
        self._poll_interval = poll_interval
        self._stop = asyncio.Event()

    async def run_forever(self) -> None:
        while not self._stop.is_set():
            job = await self._claim_one()
            if job is None:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._stop.wait(), timeout=self._poll_interval)
                continue

            await self._process(job)

    def stop(self) -> None:
        self._stop.set()

    async def process_one(self) -> bool:
        """Single-shot loop body for tests: claim and process exactly one job."""
        job = await self._claim_one()
        if job is None:
            return False

        await self._process(job)
        return True

    async def _claim_one(self) -> Job | None:
        async with self._database.sessionmaker() as session:
            pending = (
                await session.execute(
                    select(Job)
                    .where(Job.status == JobStatus.PENDING)
                    .order_by(Job.created_at, Job.id)
                    .limit(1)
                )
            ).scalar_one_or_none()
            if pending is None:
                return None

            await update_job_status(session, pending.id, status=JobStatus.RUNNING)
            await session.commit()
            await session.refresh(pending)

            return pending

    async def _process(self, job: Job) -> None:
        timeout = self._operator_config.pipeline.job_timeout_seconds
        try:
            result = await asyncio.wait_for(self._reviewer.run(job), timeout=timeout)

        except TimeoutError:
            await self._finalize_failure(
                job,
                status_detail=JobStatusDetail.TIMEOUT,
                error="job timed out",
                failure_message=("vidi-pr could not complete the review: job timed out"),
            )
            return

        except Exception as exc:
            _logger.exception(
                "unhandled reviewer error",
                repo=job.repo,
                pr_number=job.pr_number,
                job_id=job.id,
            )
            await self._finalize_failure(
                job,
                status_detail=JobStatusDetail.LLM_FAILURE,
                error=str(exc),
                failure_message=f"vidi-pr could not complete the review: {exc}",
            )
            return

        await self._persist(job, result)

    async def _persist(self, job: Job, result: ReviewResult) -> None:
        async with self._database.sessionmaker() as session:
            await update_job_status(
                session,
                job.id,
                status=result.status,
                status_detail=result.status_detail,
                error=result.error,
            )

            if result.review_id is not None:
                await record_review_posted(
                    session,
                    repo=job.repo,
                    pr_number=job.pr_number,
                    head_sha=job.head_sha,
                    review_id=result.review_id,
                    duration_ms=int(result.duration_seconds * 1000),
                    chunk_count=result.chunk_count,
                )

            await release_lock(session, repo=job.repo, pr_number=job.pr_number)
            await session.commit()

        if result.status is JobStatus.FAILED and result.failure_message is not None:
            await maybe_post_failure_comment(
                client=self._github,
                sessionmaker=self._database.sessionmaker,
                installation_id=job.installation_id,
                repo=job.repo,
                pr_number=job.pr_number,
                message=result.failure_message,
                cooldown_seconds=self._operator_config.pipeline.failure_comment_cooldown_seconds,
            )

    async def _finalize_failure(
        self,
        job: Job,
        *,
        status_detail: JobStatusDetail,
        error: str,
        failure_message: str,
    ) -> None:
        async with self._database.sessionmaker() as session:
            await update_job_status(
                session,
                job.id,
                status=JobStatus.FAILED,
                status_detail=status_detail,
                error=error,
            )
            await release_lock(session, repo=job.repo, pr_number=job.pr_number)
            await session.commit()

        await maybe_post_failure_comment(
            client=self._github,
            sessionmaker=self._database.sessionmaker,
            installation_id=job.installation_id,
            repo=job.repo,
            pr_number=job.pr_number,
            message=failure_message,
            cooldown_seconds=self._operator_config.pipeline.failure_comment_cooldown_seconds,
        )
