from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from vidi_pr.models.storage import WebhookDelivery
from vidi_pr.storage.db import rowcount, utcnow


async def record_delivery(session: AsyncSession, delivery_id: str) -> bool:
    stmt = (
        sqlite_insert(WebhookDelivery)
        .values(delivery_id=delivery_id, received_at=utcnow())
        .on_conflict_do_nothing(index_elements=["delivery_id"])
    )

    return rowcount(await session.execute(stmt)) > 0
