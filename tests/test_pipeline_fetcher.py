from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from mocks.github import MockGitHubClient

from vidi_pr.models.review import (
    ChangedFile,
    ConversationComment,
    FileStatus,
    PRInfo,
)
from vidi_pr.pipeline.fetcher import fetch_pr_content
from vidi_pr.transport.github_client import GitHubClient

_REPO = "stylesuxx/vidi-pr"
_PR_NUMBER = 7
_INSTALLATION_ID = 42
_BOT_LOGIN = "vidi-pr[bot]"


def _pr() -> PRInfo:
    return PRInfo(
        number=_PR_NUMBER,
        title="t",
        body=None,
        head_sha="abc",
        base_ref="main",
        author_login="stylesuxx",
        draft=False,
    )


def _file(name: str = "a.py") -> ChangedFile:
    return ChangedFile(
        filename=name,
        status=FileStatus.MODIFIED,
        additions=1,
        deletions=0,
        patch="@@\n+x\n",
    )


def _comment(login: str, body: str, *, is_bot: bool = False) -> ConversationComment:
    return ConversationComment(
        author_login=login,
        is_bot=is_bot,
        body=body,
        created_at=datetime(2026, 5, 12, 12, 0, tzinfo=UTC),
    )


async def test_returns_metadata_files_and_comments() -> None:
    mock = MockGitHubClient(
        prs={_PR_NUMBER: _pr()},
        pr_files={_PR_NUMBER: [_file()]},
        comments={_PR_NUMBER: [_comment("alice", "looks good")]},
    )
    content = await fetch_pr_content(
        cast("GitHubClient", mock),
        installation_id=_INSTALLATION_ID,
        repo=_REPO,
        pr_number=_PR_NUMBER,
        include_conversation=True,
        bot_login=_BOT_LOGIN,
    )

    assert content.pr.number == _PR_NUMBER
    assert content.files[0].filename == "a.py"
    assert len(content.conversation) == 1


async def test_bot_self_comments_are_filtered_out() -> None:
    mock = MockGitHubClient(
        prs={_PR_NUMBER: _pr()},
        pr_files={_PR_NUMBER: []},
        comments={
            _PR_NUMBER: [
                _comment("alice", "human comment"),
                _comment(_BOT_LOGIN, "earlier bot review", is_bot=True),
            ]
        },
    )
    content = await fetch_pr_content(
        cast("GitHubClient", mock),
        installation_id=_INSTALLATION_ID,
        repo=_REPO,
        pr_number=_PR_NUMBER,
        include_conversation=True,
        bot_login=_BOT_LOGIN,
    )

    assert [c.author_login for c in content.conversation] == ["alice"]


async def test_trigger_commands_are_filtered_out_of_conversation() -> None:
    mock = MockGitHubClient(
        prs={_PR_NUMBER: _pr()},
        pr_files={_PR_NUMBER: []},
        comments={
            _PR_NUMBER: [
                _comment("alice", "normal thoughts here"),
                _comment("alice", "@vidi-pr review please"),
            ]
        },
    )
    content = await fetch_pr_content(
        cast("GitHubClient", mock),
        installation_id=_INSTALLATION_ID,
        repo=_REPO,
        pr_number=_PR_NUMBER,
        include_conversation=True,
        bot_login=_BOT_LOGIN,
    )

    bodies = [c.body for c in content.conversation]
    assert bodies == ["normal thoughts here"]


async def test_include_conversation_false_skips_comments_fetch() -> None:
    mock = MockGitHubClient(
        prs={_PR_NUMBER: _pr()},
        pr_files={_PR_NUMBER: []},
        comments={_PR_NUMBER: [_comment("alice", "should not appear")]},
    )
    content = await fetch_pr_content(
        cast("GitHubClient", mock),
        installation_id=_INSTALLATION_ID,
        repo=_REPO,
        pr_number=_PR_NUMBER,
        include_conversation=False,
        bot_login=_BOT_LOGIN,
    )

    assert content.conversation == []
