from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest_asyncio
from mocks.github import MockGitHubClient

from vidi_pr.config.defaults import Strictness
from vidi_pr.config.operator import DefaultsConfig
from vidi_pr.models.review import PRInfo
from vidi_pr.models.storage import JobStatus, TriggerKind
from vidi_pr.orchestration.handlers import OrchestrationHandler
from vidi_pr.storage.db import Database
from vidi_pr.storage.jobs import list_jobs_with_status
from vidi_pr.transport.github_client import GitHubClient

_REPO = "stylesuxx/vidi-pr"
_INSTALLATION_ID = 42
_PR_NUMBER = 7
_BOT_LOGIN = "vidi-pr[bot]"


def _pr_info(*, base_ref: str = "main", head_sha: str = "abc123") -> PRInfo:
    return PRInfo(
        number=_PR_NUMBER,
        title="Add feature",
        body=None,
        head_sha=head_sha,
        base_ref=base_ref,
        author_login="stylesuxx",
        draft=False,
    )


def _make_handler(client: MockGitHubClient, database: Database) -> OrchestrationHandler:
    return OrchestrationHandler(
        client=cast("GitHubClient", client),
        database=database,
        defaults=DefaultsConfig(
            enabled=True,
            allowed_associations=["OWNER"],
            strictness=Strictness.NORMAL,
            include_conversation=True,
        ),
        bot_login=_BOT_LOGIN,
    )


def _pull_request_event(
    action: str = "opened",
    *,
    draft: bool = False,
    head_sha: str = "abc123",
    base_ref: str = "main",
) -> Any:
    return SimpleNamespace(
        action=action,
        pull_request=SimpleNamespace(
            number=_PR_NUMBER,
            draft=draft,
            head=SimpleNamespace(sha=head_sha),
            base=SimpleNamespace(ref=base_ref),
        ),
        repository=SimpleNamespace(full_name=_REPO, default_branch="main"),
        installation=SimpleNamespace(id=_INSTALLATION_ID),
        sender=SimpleNamespace(login="stylesuxx"),
    )


def _issue_comment_event(
    *,
    action: str = "created",
    sender_login: str = "stylesuxx",
    body: str = "@vidi-pr review",
    author_association: str = "OWNER",
    is_pr: bool = True,
    comment_id: int = 99,
) -> Any:
    return SimpleNamespace(
        action=action,
        issue=SimpleNamespace(
            number=_PR_NUMBER,
            pull_request=(SimpleNamespace(url="") if is_pr else None),
        ),
        comment=SimpleNamespace(
            id=comment_id,
            body=body,
            author_association=author_association,
        ),
        repository=SimpleNamespace(full_name=_REPO, default_branch="main"),
        installation=SimpleNamespace(id=_INSTALLATION_ID),
        sender=SimpleNamespace(login=sender_login),
    )


def _repo_yaml(*, allowed_users: list[str] | None = None) -> str:
    users = allowed_users or ["stylesuxx"]
    users_yaml = "\n".join(f"  - {u}" for u in users)
    return f"enabled: true\nallowed_users:\n{users_yaml}\nallowed_associations: [OWNER]\n"


@pytest_asyncio.fixture
async def stocked_client() -> MockGitHubClient:
    return MockGitHubClient(
        prs={_PR_NUMBER: _pr_info()},
        files={(_REPO, "main", ".github/vidi-pr.yml"): _repo_yaml()},
    )


async def test_opened_non_draft_enqueues_job(
    database: Database, stocked_client: MockGitHubClient
) -> None:
    handler = _make_handler(stocked_client, database)

    await handler.on_pull_request(_pull_request_event(action="opened"))

    async with database.sessionmaker() as session:
        jobs = await list_jobs_with_status(session, JobStatus.PENDING)
    assert len(jobs) == 1
    assert jobs[0].trigger_kind is TriggerKind.AUTO
    assert jobs[0].head_sha == "abc123"


async def test_draft_pull_request_does_not_enqueue(
    database: Database, stocked_client: MockGitHubClient
) -> None:
    handler = _make_handler(stocked_client, database)

    await handler.on_pull_request(_pull_request_event(action="opened", draft=True))

    async with database.sessionmaker() as session:
        jobs = await list_jobs_with_status(session, JobStatus.PENDING)
    assert jobs == []


async def test_ready_for_review_enqueues(
    database: Database, stocked_client: MockGitHubClient
) -> None:
    handler = _make_handler(stocked_client, database)

    await handler.on_pull_request(_pull_request_event(action="ready_for_review"))

    async with database.sessionmaker() as session:
        jobs = await list_jobs_with_status(session, JobStatus.PENDING)
    assert len(jobs) == 1


async def test_synchronize_does_not_enqueue(
    database: Database, stocked_client: MockGitHubClient
) -> None:
    handler = _make_handler(stocked_client, database)

    await handler.on_pull_request(_pull_request_event(action="synchronize"))

    async with database.sessionmaker() as session:
        jobs = await list_jobs_with_status(session, JobStatus.PENDING)
    assert jobs == []


async def test_authorized_comment_reacts_eyes_and_enqueues(
    database: Database, stocked_client: MockGitHubClient
) -> None:
    handler = _make_handler(stocked_client, database)

    await handler.on_issue_comment(_issue_comment_event())

    assert len(stocked_client.reactions) == 1
    assert stocked_client.reactions[0].reaction == "eyes"
    assert stocked_client.reactions[0].comment_id == 99

    async with database.sessionmaker() as session:
        jobs = await list_jobs_with_status(session, JobStatus.PENDING)
    assert len(jobs) == 1
    assert jobs[0].trigger_kind is TriggerKind.COMMENT


async def test_unauthorized_comment_reacts_thumbsdown_and_does_not_enqueue(
    database: Database, stocked_client: MockGitHubClient
) -> None:
    handler = _make_handler(stocked_client, database)

    event = _issue_comment_event(sender_login="random_user", author_association="NONE")
    await handler.on_issue_comment(event)

    assert len(stocked_client.reactions) == 1
    assert stocked_client.reactions[0].reaction == "-1"

    async with database.sessionmaker() as session:
        jobs = await list_jobs_with_status(session, JobStatus.PENDING)
    assert jobs == []


async def test_bot_self_comment_is_ignored_entirely(
    database: Database, stocked_client: MockGitHubClient
) -> None:
    handler = _make_handler(stocked_client, database)

    event = _issue_comment_event(sender_login=_BOT_LOGIN)
    await handler.on_issue_comment(event)

    assert stocked_client.reactions == []
    async with database.sessionmaker() as session:
        assert await list_jobs_with_status(session, JobStatus.PENDING) == []


async def test_edited_comment_does_not_trigger(
    database: Database, stocked_client: MockGitHubClient
) -> None:
    handler = _make_handler(stocked_client, database)

    event = _issue_comment_event(action="edited")
    await handler.on_issue_comment(event)

    assert stocked_client.reactions == []
    async with database.sessionmaker() as session:
        assert await list_jobs_with_status(session, JobStatus.PENDING) == []


async def test_comment_on_non_pr_issue_is_ignored(
    database: Database, stocked_client: MockGitHubClient
) -> None:
    handler = _make_handler(stocked_client, database)

    event = _issue_comment_event(is_pr=False)
    await handler.on_issue_comment(event)

    assert stocked_client.reactions == []


async def test_quoted_trigger_does_not_fire(
    database: Database, stocked_client: MockGitHubClient
) -> None:
    handler = _make_handler(stocked_client, database)

    event = _issue_comment_event(body="> @vidi-pr review please")
    await handler.on_issue_comment(event)

    assert stocked_client.reactions == []
    async with database.sessionmaker() as session:
        assert await list_jobs_with_status(session, JobStatus.PENDING) == []


async def test_extra_context_is_persisted_on_the_job(
    database: Database, stocked_client: MockGitHubClient
) -> None:
    handler = _make_handler(stocked_client, database)

    event = _issue_comment_event(body="@vidi-pr review focus on the migration")
    await handler.on_issue_comment(event)

    async with database.sessionmaker() as session:
        jobs = await list_jobs_with_status(session, JobStatus.PENDING)
    assert len(jobs) == 1
    assert jobs[0].extra_context == "focus on the migration"


async def test_lock_held_drops_second_comment_trigger_with_eyes_ack(
    database: Database, stocked_client: MockGitHubClient
) -> None:
    handler = _make_handler(stocked_client, database)

    await handler.on_issue_comment(_issue_comment_event(comment_id=100))
    await handler.on_issue_comment(_issue_comment_event(comment_id=101))

    # Both comments got an eyes reaction (acknowledged), but only one job exists.
    assert [r.reaction for r in stocked_client.reactions] == ["eyes", "eyes"]
    async with database.sessionmaker() as session:
        jobs = await list_jobs_with_status(session, JobStatus.PENDING)
    assert len(jobs) == 1


async def test_auto_trigger_dropped_silently_when_lock_held(
    database: Database, stocked_client: MockGitHubClient
) -> None:
    handler = _make_handler(stocked_client, database)

    await handler.on_pull_request(_pull_request_event(action="opened"))
    await handler.on_pull_request(_pull_request_event(action="ready_for_review"))

    async with database.sessionmaker() as session:
        jobs = await list_jobs_with_status(session, JobStatus.PENDING)
    assert len(jobs) == 1


async def test_pull_request_closed_action_does_not_enqueue(
    database: Database, stocked_client: MockGitHubClient
) -> None:
    handler = _make_handler(stocked_client, database)

    await handler.on_pull_request(_pull_request_event(action="closed"))

    async with database.sessionmaker() as session:
        assert await list_jobs_with_status(session, JobStatus.PENDING) == []
