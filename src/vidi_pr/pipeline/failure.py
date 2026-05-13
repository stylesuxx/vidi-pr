from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from vidi_pr.storage.failures import claim_failure_slot
from vidi_pr.transport.github_client import GitHubClient

_logger = structlog.get_logger(__name__)


async def maybe_post_failure_comment(
    *,
    client: GitHubClient,
    sessionmaker: async_sessionmaker[AsyncSession],
    installation_id: int,
    repo: str,
    pr_number: int,
    message: str,
    cooldown_seconds: int,
) -> bool:
    """
    Post a failure comment for this PR if the per-PR cooldown allows it.

    Returns True if the comment was posted, False if suppressed by cooldown.
    Failures during the GitHub post itself are caught and logged so we never
    raise out of a fallback-notification path.
    """
    async with sessionmaker() as session:
        allowed = await claim_failure_slot(
            session,
            repo=repo,
            pr_number=pr_number,
            cooldown_seconds=cooldown_seconds,
        )

    if not allowed:
        _logger.info(
            "failure comment suppressed by cooldown",
            repo=repo,
            pr_number=pr_number,
        )
        return False

    try:
        await client.create_comment(installation_id, repo, pr_number, message)
    except Exception:
        _logger.exception(
            "failed to post failure comment",
            repo=repo,
            pr_number=pr_number,
        )
        return False

    return True
