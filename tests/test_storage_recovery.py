from sqlalchemy.ext.asyncio import AsyncSession

from vidi_pr.models.storage import JobStatus, JobType, TriggerKind
from vidi_pr.storage.jobs import fetch_job, insert_job, update_job_status
from vidi_pr.storage.locks import acquire_lock, fetch_lock
from vidi_pr.storage.recovery import INTERRUPTED_DETAIL, recover_on_startup


async def _seed_running_job(session: AsyncSession, *, pr_number: int = 1) -> int:
    job = await insert_job(
        session,
        job_type=JobType.REVIEW,
        installation_id=1,
        repo="o/r",
        pr_number=pr_number,
        head_sha="sha",
        trigger_kind=TriggerKind.AUTO,
    )
    await update_job_status(session, job.id, status=JobStatus.RUNNING)
    await acquire_lock(session, repo="o/r", pr_number=pr_number, job_id=job.id)

    return job.id


async def test_running_jobs_become_failed_with_interrupt_detail(session: AsyncSession) -> None:
    job_id = await _seed_running_job(session)
    assert await recover_on_startup(session) == 1

    fetched = await fetch_job(session, job_id)
    assert fetched is not None
    assert fetched.status == JobStatus.FAILED
    assert fetched.status_detail == INTERRUPTED_DETAIL
    assert fetched.error is not None
    assert await fetch_lock(session, repo="o/r", pr_number=1) is None


async def test_pending_jobs_are_untouched(session: AsyncSession) -> None:
    job = await insert_job(
        session,
        job_type=JobType.REVIEW,
        installation_id=1,
        repo="o/r",
        pr_number=1,
        head_sha="sha",
        trigger_kind=TriggerKind.AUTO,
    )
    assert await recover_on_startup(session) == 0

    fetched = await fetch_job(session, job.id)
    assert fetched is not None
    assert fetched.status == JobStatus.PENDING


async def test_terminal_jobs_are_untouched(session: AsyncSession) -> None:
    job = await insert_job(
        session,
        job_type=JobType.REVIEW,
        installation_id=1,
        repo="o/r",
        pr_number=1,
        head_sha="sha",
        trigger_kind=TriggerKind.AUTO,
    )
    await update_job_status(session, job.id, status=JobStatus.DONE, status_detail="all_good")
    assert await recover_on_startup(session) == 0

    await session.refresh(job)
    assert job.status == JobStatus.DONE
    assert job.status_detail == "all_good"


async def test_recovers_multiple_running_jobs(session: AsyncSession) -> None:
    first = await _seed_running_job(session, pr_number=1)
    second = await _seed_running_job(session, pr_number=2)
    assert await recover_on_startup(session) == 2

    for job_id, pr_number in [(first, 1), (second, 2)]:
        fetched = await fetch_job(session, job_id)
        assert fetched is not None
        assert fetched.status == JobStatus.FAILED
        assert await fetch_lock(session, repo="o/r", pr_number=pr_number) is None
