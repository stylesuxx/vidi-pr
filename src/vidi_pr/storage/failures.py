from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from vidi_pr.models.storage import FailureCooldown
from vidi_pr.storage.db import utcnow


async def claim_failure_slot(
    session: AsyncSession,
    *,
    repo: str,
    pr_number: int,
    cooldown_seconds: int,
) -> bool:
    """
    Atomically take the cooldown slot for `(repo, pr_number)`.

    Returns True if the caller may post a failure comment now (no record, or
    the prior record is older than `cooldown_seconds`). Returns False if the
    cooldown is still in force. On True, the slot's timestamp is bumped to
    now so subsequent calls within the window return False.
    """
    now = utcnow()
    cutoff = now - timedelta(seconds=cooldown_seconds)

    stmt = select(FailureCooldown).where(
        FailureCooldown.repo == repo,
        FailureCooldown.pr_number == pr_number,
    )
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing is not None and existing.last_posted_at > cutoff:
        return False

    upsert = (
        sqlite_insert(FailureCooldown)
        .values(repo=repo, pr_number=pr_number, last_posted_at=now)
        .on_conflict_do_update(
            index_elements=["repo", "pr_number"],
            set_={"last_posted_at": now},
        )
    )
    await session.execute(upsert)
    await session.commit()

    return True
