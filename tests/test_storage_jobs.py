from sqlalchemy.ext.asyncio import AsyncSession

from vidi_pr.models.storage import JobStatus, JobType, TriggerKind
from vidi_pr.storage.jobs import (
    fetch_job,
    increment_job_attempts,
    insert_job,
    list_jobs_with_status,
    update_job_status,
)


async def test_insert_returns_pending_job_with_timestamps(session: AsyncSession) -> None:
    job = await insert_job(
        session,
        job_type=JobType.REVIEW,
        installation_id=42,
        repo="stylesuxx/vidi-pr",
        pr_number=7,
        head_sha="abc123",
        trigger_kind=TriggerKind.AUTO,
        extra_context="focus on security",
    )

    assert job.id > 0
    assert job.status == JobStatus.PENDING
    assert job.attempts == 0
    assert job.repo == "stylesuxx/vidi-pr"
    assert job.extra_context == "focus on security"
    assert job.created_at == job.updated_at


async def test_fetch_existing_and_missing(session: AsyncSession) -> None:
    inserted = await insert_job(
        session,
        job_type=JobType.REVIEW,
        installation_id=1,
        repo="o/r",
        pr_number=1,
        head_sha="sha",
        trigger_kind=TriggerKind.COMMENT,
    )
    fetched = await fetch_job(session, inserted.id)

    assert fetched is not None
    assert fetched.id == inserted.id
    assert fetched.trigger_kind == TriggerKind.COMMENT
    assert await fetch_job(session, 999_999) is None


async def test_update_status_writes_detail_and_error(session: AsyncSession) -> None:
    job = await insert_job(
        session,
        job_type=JobType.REVIEW,
        installation_id=1,
        repo="o/r",
        pr_number=1,
        head_sha="sha",
        trigger_kind=TriggerKind.AUTO,
    )
    await update_job_status(
        session,
        job.id,
        status=JobStatus.FAILED,
        status_detail="pr_closed",
        error="422 from GitHub",
    )
    await session.refresh(job)

    assert job.status == JobStatus.FAILED
    assert job.status_detail == "pr_closed"
    assert job.error == "422 from GitHub"


async def test_list_filters_by_status_and_orders_by_created_at(session: AsyncSession) -> None:
    ids: list[int] = []
    for pr_number in range(3):
        job = await insert_job(
            session,
            job_type=JobType.REVIEW,
            installation_id=1,
            repo="o/r",
            pr_number=pr_number,
            head_sha="sha",
            trigger_kind=TriggerKind.AUTO,
        )
        ids.append(job.id)
    await update_job_status(session, ids[1], status=JobStatus.RUNNING)

    pending = await list_jobs_with_status(session, JobStatus.PENDING)
    assert [j.id for j in pending] == [ids[0], ids[2]]
    running = await list_jobs_with_status(session, JobStatus.RUNNING)
    assert [j.id for j in running] == [ids[1]]
    assert await list_jobs_with_status(session, JobStatus.DONE) == []


async def test_increment_attempts(session: AsyncSession) -> None:
    job = await insert_job(
        session,
        job_type=JobType.REVIEW,
        installation_id=1,
        repo="o/r",
        pr_number=1,
        head_sha="sha",
        trigger_kind=TriggerKind.AUTO,
    )
    await increment_job_attempts(session, job.id)
    await increment_job_attempts(session, job.id)
    await session.refresh(job)

    assert job.attempts == 2
