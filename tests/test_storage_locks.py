from sqlalchemy.ext.asyncio import AsyncSession

from vidi_pr.models.storage import JobStatus, JobType, TriggerKind
from vidi_pr.storage.jobs import insert_job, update_job_status
from vidi_pr.storage.locks import (
    acquire_lock,
    clear_stale_locks,
    fetch_lock,
    release_lock,
)


async def _make_job(session: AsyncSession, *, pr_number: int = 1) -> int:
    job = await insert_job(
        session,
        job_type=JobType.REVIEW,
        installation_id=1,
        repo="o/r",
        pr_number=pr_number,
        head_sha="sha",
        trigger_kind=TriggerKind.AUTO,
    )
    return job.id


async def test_acquire_succeeds_when_free(session: AsyncSession) -> None:
    job_id = await _make_job(session)
    assert await acquire_lock(session, repo="o/r", pr_number=1, job_id=job_id) is True


async def test_acquire_fails_when_held(session: AsyncSession) -> None:
    job_id = await _make_job(session)
    assert await acquire_lock(session, repo="o/r", pr_number=1, job_id=job_id) is True
    assert await acquire_lock(session, repo="o/r", pr_number=1, job_id=job_id) is False


async def test_acquire_succeeds_after_release(session: AsyncSession) -> None:
    job_id = await _make_job(session)
    await acquire_lock(session, repo="o/r", pr_number=1, job_id=job_id)
    await release_lock(session, repo="o/r", pr_number=1)

    assert await acquire_lock(session, repo="o/r", pr_number=1, job_id=job_id) is True


async def test_fetch_returns_lock_when_present(session: AsyncSession) -> None:
    job_id = await _make_job(session)
    assert await fetch_lock(session, repo="o/r", pr_number=1) is None

    await acquire_lock(session, repo="o/r", pr_number=1, job_id=job_id)
    lock = await fetch_lock(session, repo="o/r", pr_number=1)
    assert lock is not None
    assert lock.job_id == job_id
    assert lock.repo == "o/r"
    assert lock.pr_number == 1


async def test_clear_stale_locks_skips_pending_jobs(session: AsyncSession) -> None:
    job_id = await _make_job(session)
    await acquire_lock(session, repo="o/r", pr_number=1, job_id=job_id)

    assert await clear_stale_locks(session) == 0
    assert await fetch_lock(session, repo="o/r", pr_number=1) is not None


async def test_clear_stale_locks_removes_terminal_job_locks(session: AsyncSession) -> None:
    done_id = await _make_job(session, pr_number=1)
    failed_id = await _make_job(session, pr_number=2)
    running_id = await _make_job(session, pr_number=3)
    await acquire_lock(session, repo="o/r", pr_number=1, job_id=done_id)
    await acquire_lock(session, repo="o/r", pr_number=2, job_id=failed_id)
    await acquire_lock(session, repo="o/r", pr_number=3, job_id=running_id)
    await update_job_status(session, done_id, status=JobStatus.DONE)
    await update_job_status(session, failed_id, status=JobStatus.FAILED)
    await update_job_status(session, running_id, status=JobStatus.RUNNING)

    removed = await clear_stale_locks(session)
    assert removed == 2
    assert await fetch_lock(session, repo="o/r", pr_number=1) is None
    assert await fetch_lock(session, repo="o/r", pr_number=2) is None
    assert await fetch_lock(session, repo="o/r", pr_number=3) is not None
