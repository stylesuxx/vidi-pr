from sqlalchemy.ext.asyncio import AsyncSession

from vidi_pr.storage.dedup import record_delivery


async def test_first_delivery_is_recorded(session: AsyncSession) -> None:
    assert await record_delivery(session, "delivery-1") is True


async def test_duplicate_delivery_is_rejected(session: AsyncSession) -> None:
    assert await record_delivery(session, "delivery-1") is True
    assert await record_delivery(session, "delivery-1") is False


async def test_distinct_deliveries_each_succeed(session: AsyncSession) -> None:
    assert await record_delivery(session, "delivery-1") is True
    assert await record_delivery(session, "delivery-2") is True
