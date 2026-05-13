from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from vidi_pr.models.storage import (
    TERMINAL_JOB_STATUSES,
    Job,
    JobStatus,
    JobStatusDetail,
    PrLock,
)
from vidi_pr.storage.db import rowcount, utcnow

INTERRUPTED_ERROR = "interrupted by service restart"


async def recover_on_startup(session: AsyncSession) -> int:
    """Fail orphaned `running` jobs and clear stale locks; returns jobs recovered."""
    fail_running = (
        update(Job)
        .where(Job.status == JobStatus.RUNNING)
        .values(
            status=JobStatus.FAILED,
            status_detail=JobStatusDetail.INTERRUPTED_BY_RESTART,
            error=func.coalesce(Job.error, INTERRUPTED_ERROR),
            updated_at=utcnow(),
        )
    )
    recovered = rowcount(await session.execute(fail_running))

    terminal_job_ids = select(Job.id).where(Job.status.in_(TERMINAL_JOB_STATUSES))
    await session.execute(delete(PrLock).where(PrLock.job_id.in_(terminal_job_ids)))

    return recovered
