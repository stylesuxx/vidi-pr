from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from vidi_pr.models.storage import TERMINAL_JOB_STATUSES, Job, PrLock
from vidi_pr.storage.db import rowcount, utcnow


async def acquire_lock(session: AsyncSession, *, repo: str, pr_number: int, job_id: int) -> bool:
    stmt = (
        sqlite_insert(PrLock)
        .values(repo=repo, pr_number=pr_number, locked_at=utcnow(), job_id=job_id)
        .on_conflict_do_nothing(index_elements=["repo", "pr_number"])
    )

    return rowcount(await session.execute(stmt)) > 0


async def release_lock(session: AsyncSession, *, repo: str, pr_number: int) -> None:
    stmt = delete(PrLock).where(PrLock.repo == repo, PrLock.pr_number == pr_number)
    await session.execute(stmt)


async def fetch_lock(session: AsyncSession, *, repo: str, pr_number: int) -> PrLock | None:
    return await session.get(PrLock, {"repo": repo, "pr_number": pr_number})


async def clear_stale_locks(session: AsyncSession) -> int:
    terminal_job_ids = select(Job.id).where(Job.status.in_(TERMINAL_JOB_STATUSES))
    stmt = delete(PrLock).where(PrLock.job_id.in_(terminal_job_ids))

    return rowcount(await session.execute(stmt))
