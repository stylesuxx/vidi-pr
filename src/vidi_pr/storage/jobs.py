from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from vidi_pr.models.storage import Job, JobStatus, JobType, TriggerKind
from vidi_pr.storage.db import utcnow


async def insert_job(
    session: AsyncSession,
    *,
    job_type: JobType,
    installation_id: int,
    repo: str,
    pr_number: int,
    head_sha: str,
    trigger_kind: TriggerKind,
    extra_context: str | None = None,
) -> Job:
    now = utcnow()
    job = Job(
        job_type=job_type,
        installation_id=installation_id,
        repo=repo,
        pr_number=pr_number,
        head_sha=head_sha,
        trigger_kind=trigger_kind,
        extra_context=extra_context,
        status=JobStatus.PENDING,
        attempts=0,
        created_at=now,
        updated_at=now,
    )
    session.add(job)
    await session.flush()

    return job


async def fetch_job(session: AsyncSession, job_id: int) -> Job | None:
    return await session.get(Job, job_id)


async def list_jobs_with_status(session: AsyncSession, status: JobStatus) -> list[Job]:
    stmt = select(Job).where(Job.status == status).order_by(Job.created_at, Job.id)
    result = await session.execute(stmt)

    return list(result.scalars())


async def update_job_status(
    session: AsyncSession,
    job_id: int,
    *,
    status: JobStatus,
    status_detail: str | None = None,
    error: str | None = None,
) -> None:
    stmt = (
        update(Job)
        .where(Job.id == job_id)
        .values(
            status=status,
            status_detail=status_detail,
            error=error,
            updated_at=utcnow(),
        )
    )
    await session.execute(stmt)


async def increment_job_attempts(session: AsyncSession, job_id: int) -> None:
    stmt = (
        update(Job).where(Job.id == job_id).values(attempts=Job.attempts + 1, updated_at=utcnow())
    )
    await session.execute(stmt)
