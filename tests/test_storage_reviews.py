from sqlalchemy.ext.asyncio import AsyncSession

from vidi_pr.storage.reviews import (
    fetch_review_posted,
    list_reviews_for_pr,
    record_review_posted,
)


async def test_record_returns_row_with_id(session: AsyncSession) -> None:
    posted = await record_review_posted(
        session,
        repo="o/r",
        pr_number=1,
        head_sha="sha-1",
        review_id=1001,
        duration_ms=12_345,
        chunk_count=2,
    )
    assert posted.id > 0
    assert posted.review_id == 1001
    assert posted.duration_ms == 12_345
    assert posted.chunk_count == 2


async def test_fetch_returns_inserted_row(session: AsyncSession) -> None:
    inserted = await record_review_posted(
        session,
        repo="o/r",
        pr_number=2,
        head_sha="sha-2",
        review_id=42,
        duration_ms=1,
        chunk_count=1,
    )
    fetched = await fetch_review_posted(session, inserted.id)
    assert fetched is not None
    assert fetched.head_sha == "sha-2"
    assert await fetch_review_posted(session, 999_999) is None


async def test_list_returns_reviews_in_post_order(session: AsyncSession) -> None:
    for review_id in (100, 200, 300):
        await record_review_posted(
            session,
            repo="o/r",
            pr_number=1,
            head_sha=f"sha-{review_id}",
            review_id=review_id,
            duration_ms=1,
            chunk_count=1,
        )
    reviews = await list_reviews_for_pr(session, repo="o/r", pr_number=1)
    assert [r.review_id for r in reviews] == [100, 200, 300]
    assert await list_reviews_for_pr(session, repo="o/r", pr_number=999) == []
