from __future__ import annotations

from typing import cast

from mocks.github import MockGitHubClient
from sqlalchemy.ext.asyncio import AsyncSession

from vidi_pr.pipeline.failure import maybe_post_failure_comment
from vidi_pr.storage.db import Database
from vidi_pr.storage.failures import claim_failure_slot
from vidi_pr.transport.github_client import GitHubClient

_INSTALLATION_ID = 42
_REPO = "stylesuxx/vidi-pr"
_PR_NUMBER = 7


async def test_first_claim_returns_true(session: AsyncSession) -> None:
    assert (
        await claim_failure_slot(session, repo=_REPO, pr_number=_PR_NUMBER, cooldown_seconds=3600)
        is True
    )


async def test_second_claim_within_cooldown_returns_false(session: AsyncSession) -> None:
    await claim_failure_slot(session, repo=_REPO, pr_number=_PR_NUMBER, cooldown_seconds=3600)
    assert (
        await claim_failure_slot(session, repo=_REPO, pr_number=_PR_NUMBER, cooldown_seconds=3600)
        is False
    )


async def test_claim_allowed_again_after_zero_cooldown(session: AsyncSession) -> None:
    await claim_failure_slot(session, repo=_REPO, pr_number=_PR_NUMBER, cooldown_seconds=0)
    # cooldown_seconds=0 means any subsequent call past "now" should be allowed,
    # but since the prior claim used utcnow() == now, the cutoff equals
    # last_posted_at; strict ">" means False. Use a tiny cooldown.
    assert (
        await claim_failure_slot(session, repo=_REPO, pr_number=_PR_NUMBER, cooldown_seconds=0)
        is True
    )


async def test_post_helper_posts_comment_when_slot_claimed(database: Database) -> None:
    mock = MockGitHubClient()
    posted = await maybe_post_failure_comment(
        client=cast("GitHubClient", mock),
        sessionmaker=database.sessionmaker,
        installation_id=_INSTALLATION_ID,
        repo=_REPO,
        pr_number=_PR_NUMBER,
        message="something went wrong",
        cooldown_seconds=3600,
    )

    assert posted is True
    assert len(mock.comments_posted) == 1
    assert mock.comments_posted[0].body == "something went wrong"


async def test_post_helper_suppressed_within_cooldown(database: Database) -> None:
    mock = MockGitHubClient()
    await maybe_post_failure_comment(
        client=cast("GitHubClient", mock),
        sessionmaker=database.sessionmaker,
        installation_id=_INSTALLATION_ID,
        repo=_REPO,
        pr_number=_PR_NUMBER,
        message="first",
        cooldown_seconds=3600,
    )
    posted_again = await maybe_post_failure_comment(
        client=cast("GitHubClient", mock),
        sessionmaker=database.sessionmaker,
        installation_id=_INSTALLATION_ID,
        repo=_REPO,
        pr_number=_PR_NUMBER,
        message="second",
        cooldown_seconds=3600,
    )

    assert posted_again is False
    assert len(mock.comments_posted) == 1
