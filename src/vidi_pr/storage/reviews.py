from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vidi_pr.models.storage import ReviewPosted
from vidi_pr.storage.db import utcnow


async def record_review_posted(
    session: AsyncSession,
    *,
    repo: str,
    pr_number: int,
    head_sha: str,
    review_id: int,
    duration_ms: int,
    chunk_count: int,
) -> ReviewPosted:
    posted = ReviewPosted(
        repo=repo,
        pr_number=pr_number,
        head_sha=head_sha,
        review_id=review_id,
        posted_at=utcnow(),
        duration_ms=duration_ms,
        chunk_count=chunk_count,
    )
    session.add(posted)
    await session.flush()
    return posted


async def fetch_review_posted(session: AsyncSession, row_id: int) -> ReviewPosted | None:
    return await session.get(ReviewPosted, row_id)


async def list_reviews_for_pr(
    session: AsyncSession, *, repo: str, pr_number: int
) -> list[ReviewPosted]:
    stmt = (
        select(ReviewPosted)
        .where(ReviewPosted.repo == repo, ReviewPosted.pr_number == pr_number)
        .order_by(ReviewPosted.posted_at, ReviewPosted.id)
    )
    result = await session.execute(stmt)

    return list(result.scalars())
