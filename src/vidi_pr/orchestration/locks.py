from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from vidi_pr.models.storage import Job, JobType, TriggerKind
from vidi_pr.storage.jobs import insert_job
from vidi_pr.storage.locks import acquire_lock, fetch_lock


async def try_enqueue_review(
    session: AsyncSession,
    *,
    installation_id: int,
    repo: str,
    pr_number: int,
    head_sha: str,
    trigger_kind: TriggerKind,
    extra_context: str | None = None,
) -> Job | None:
    """
    Insert a pending review job and take the per-PR lock atomically.

    Returns the inserted `Job` on success, `None` if another job already
    holds the lock for this PR (the caller decides whether to react or
    silently drop). The lock is held by the new job until the worker
    completes it and releases the row.
    """
    existing = await fetch_lock(session, repo=repo, pr_number=pr_number)
    if existing is not None:
        return None

    job = await insert_job(
        session,
        job_type=JobType.REVIEW,
        installation_id=installation_id,
        repo=repo,
        pr_number=pr_number,
        head_sha=head_sha,
        trigger_kind=trigger_kind,
        extra_context=extra_context,
    )
    if not await acquire_lock(session, repo=repo, pr_number=pr_number, job_id=job.id):
        await session.rollback()
        return None

    await session.commit()
    return job
