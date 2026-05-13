from __future__ import annotations

from collections.abc import AsyncIterator
from ipaddress import IPv4Network
from pathlib import Path
from typing import Any

import httpx
import pytest_asyncio
from githubkit.webhooks import sign as sign_webhook
from httpx import ASGITransport

from vidi_pr.config.operator import (
    DefaultsConfig,
    GitHubConfig,
    LLMConfig,
    LoggingConfig,
    OperatorConfig,
    PipelineConfig,
    ServerConfig,
    StorageConfig,
)
from vidi_pr.storage.db import Database
from vidi_pr.transport.server import create_app

_SECRET = "test-webhook-secret"
_OWNER = "stylesuxx"
_REPO_NAME = "vidi-pr"
_REPO_FULL = f"{_OWNER}/{_REPO_NAME}"


class RecordingHandler:
    def __init__(self) -> None:
        self.pr_calls: list[Any] = []
        self.comment_calls: list[Any] = []

    async def on_pull_request(self, event: Any) -> None:
        self.pr_calls.append(event)

    async def on_issue_comment(self, event: Any) -> None:
        self.comment_calls.append(event)


def _operator_config(db_path: Path) -> OperatorConfig:
    return OperatorConfig(
        github=GitHubConfig(app_id=1, private_key_path=Path("/tmp/key.pem")),
        llm=LLMConfig(provider="openai_compat", base_url="http://llm.test/v1", model="model"),
        server=ServerConfig(
            host="127.0.0.1",
            port=8080,
            forwarded_allow_ips=[IPv4Network("127.0.0.0/8")],
        ),
        storage=StorageConfig(db_path=db_path),
        logging=LoggingConfig(),
        pipeline=PipelineConfig(),
        defaults=DefaultsConfig(),
        webhook_secret=_SECRET,
    )


@pytest_asyncio.fixture
async def app_client(
    database: Database, tmp_path: Path
) -> AsyncIterator[tuple[httpx.AsyncClient, RecordingHandler]]:
    handler = RecordingHandler()
    config = _operator_config(tmp_path / "ignored.db")
    app = create_app(config=config, database=database, handler=handler)
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, handler


def _user(login: str = "alice", *, is_bot: bool = False) -> dict[str, Any]:
    return {
        "login": login,
        "id": 1,
        "node_id": "U_1",
        "avatar_url": "https://example.com/avatar.png",
        "gravatar_id": "",
        "url": f"https://api.github.com/users/{login}",
        "html_url": f"https://github.com/{login}",
        "followers_url": "",
        "following_url": "",
        "gists_url": "",
        "starred_url": "",
        "subscriptions_url": "",
        "organizations_url": "",
        "repos_url": "",
        "events_url": "",
        "received_events_url": "",
        "type": "Bot" if is_bot else "User",
        "site_admin": False,
    }


def _repository() -> dict[str, Any]:
    return {
        "id": 1,
        "node_id": "R_1",
        "name": _REPO_NAME,
        "full_name": _REPO_FULL,
        "private": False,
        "owner": _user(_OWNER),
        "html_url": f"https://github.com/{_REPO_FULL}",
        "description": None,
        "fork": False,
        "url": f"https://api.github.com/repos/{_REPO_FULL}",
        "archive_url": "",
        "assignees_url": "",
        "blobs_url": "",
        "branches_url": "",
        "collaborators_url": "",
        "comments_url": "",
        "commits_url": "",
        "compare_url": "",
        "contents_url": "",
        "contributors_url": "",
        "deployments_url": "",
        "downloads_url": "",
        "events_url": "",
        "forks_url": "",
        "git_commits_url": "",
        "git_refs_url": "",
        "git_tags_url": "",
        "git_url": "",
        "issue_comment_url": "",
        "issue_events_url": "",
        "issues_url": "",
        "keys_url": "",
        "labels_url": "",
        "languages_url": "",
        "merges_url": "",
        "milestones_url": "",
        "notifications_url": "",
        "pulls_url": "",
        "releases_url": "",
        "ssh_url": "",
        "stargazers_url": "",
        "statuses_url": "",
        "subscribers_url": "",
        "subscription_url": "",
        "tags_url": "",
        "teams_url": "",
        "trees_url": "",
        "clone_url": "",
        "mirror_url": None,
        "hooks_url": "",
        "svn_url": "",
        "homepage": None,
        "language": None,
        "forks_count": 0,
        "stargazers_count": 0,
        "watchers_count": 0,
        "size": 0,
        "default_branch": "main",
        "open_issues_count": 0,
        "is_template": False,
        "topics": [],
        "has_issues": True,
        "has_projects": True,
        "has_wiki": True,
        "has_pages": False,
        "has_downloads": True,
        "has_discussions": False,
        "archived": False,
        "disabled": False,
        "visibility": "public",
        "pushed_at": "2026-05-12T10:00:00Z",
        "created_at": "2026-05-12T10:00:00Z",
        "updated_at": "2026-05-12T10:00:00Z",
        "permissions": None,
        "allow_rebase_merge": True,
        "temp_clone_token": None,
        "allow_squash_merge": True,
        "allow_auto_merge": False,
        "delete_branch_on_merge": False,
        "allow_merge_commit": True,
        "subscribers_count": 0,
        "network_count": 0,
        "license": None,
        "forks": 0,
        "open_issues": 0,
        "watchers": 0,
    }


def _pull_request_event() -> dict[str, Any]:
    user = _user("stylesuxx")
    repo = _repository()
    pr = {
        "url": "",
        "id": 1,
        "node_id": "PR_1",
        "html_url": "",
        "diff_url": "",
        "patch_url": "",
        "issue_url": "",
        "commits_url": "",
        "review_comments_url": "",
        "review_comment_url": "",
        "comments_url": "",
        "statuses_url": "",
        "number": 7,
        "state": "open",
        "locked": False,
        "title": "Add feature",
        "user": user,
        "body": None,
        "labels": [],
        "milestone": None,
        "active_lock_reason": None,
        "created_at": "2026-05-12T10:00:00Z",
        "updated_at": "2026-05-12T11:00:00Z",
        "closed_at": None,
        "merged_at": None,
        "merge_commit_sha": None,
        "assignee": None,
        "assignees": [],
        "requested_reviewers": [],
        "requested_teams": [],
        "head": {"label": "h:feature", "ref": "feature", "sha": "abc", "user": user, "repo": repo},
        "base": {"label": "h:main", "ref": "main", "sha": "def", "user": user, "repo": repo},
        "_links": {
            "self": {"href": ""},
            "html": {"href": ""},
            "issue": {"href": ""},
            "comments": {"href": ""},
            "review_comments": {"href": ""},
            "review_comment": {"href": ""},
            "commits": {"href": ""},
            "statuses": {"href": ""},
        },
        "author_association": "OWNER",
        "auto_merge": None,
        "draft": False,
        "merged": False,
        "mergeable": None,
        "rebaseable": None,
        "mergeable_state": "unknown",
        "merged_by": None,
        "comments": 0,
        "review_comments": 0,
        "maintainer_can_modify": False,
        "commits": 1,
        "additions": 1,
        "deletions": 0,
        "changed_files": 1,
    }

    return {
        "action": "opened",
        "number": 7,
        "pull_request": pr,
        "repository": repo,
        "sender": user,
        "installation": {"id": 42, "node_id": "I_42"},
    }


def _issue_comment_event() -> dict[str, Any]:
    user = _user("stylesuxx")
    repo = _repository()
    issue = {
        "id": 1,
        "node_id": "I_1",
        "url": "",
        "repository_url": "",
        "labels_url": "",
        "comments_url": "",
        "events_url": "",
        "html_url": f"https://github.com/{_REPO_FULL}/pull/7",
        "number": 7,
        "state": "open",
        "title": "Add feature",
        "body": None,
        "user": user,
        "labels": [],
        "assignee": None,
        "assignees": [],
        "milestone": None,
        "locked": False,
        "active_lock_reason": None,
        "comments": 0,
        "pull_request": {
            "url": "",
            "html_url": "",
            "diff_url": "",
            "patch_url": "",
        },
        "closed_at": None,
        "created_at": "2026-05-12T10:00:00Z",
        "updated_at": "2026-05-12T11:00:00Z",
        "author_association": "OWNER",
        "reactions": {
            "url": "",
            "total_count": 0,
            "+1": 0,
            "-1": 0,
            "laugh": 0,
            "confused": 0,
            "heart": 0,
            "hooray": 0,
            "eyes": 0,
            "rocket": 0,
        },
    }
    comment = {
        "id": 99,
        "node_id": "IC_99",
        "url": "",
        "html_url": "",
        "issue_url": "",
        "user": user,
        "created_at": "2026-05-12T12:00:00Z",
        "updated_at": "2026-05-12T12:00:00Z",
        "author_association": "OWNER",
        "body": "@vidi-pr review",
        "performed_via_github_app": None,
        "reactions": {
            "url": "",
            "total_count": 0,
            "+1": 0,
            "-1": 0,
            "laugh": 0,
            "confused": 0,
            "heart": 0,
            "hooray": 0,
            "eyes": 0,
            "rocket": 0,
        },
    }

    return {
        "action": "created",
        "issue": issue,
        "comment": comment,
        "repository": repo,
        "sender": user,
        "installation": {"id": 42, "node_id": "I_42"},
    }


def _send_headers(event_type: str, delivery_id: str, body: bytes) -> dict[str, str]:
    return {
        "X-GitHub-Event": event_type,
        "X-GitHub-Delivery": delivery_id,
        "X-Hub-Signature-256": sign_webhook(_SECRET, body),
        "Content-Type": "application/json",
    }


async def test_healthz_returns_200(app_client: tuple[httpx.AsyncClient, RecordingHandler]) -> None:
    client, _ = app_client
    response = await client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_valid_pull_request_event_dispatched(
    app_client: tuple[httpx.AsyncClient, RecordingHandler],
) -> None:
    client, handler = app_client
    body = httpx.Request("POST", "/webhook", json=_pull_request_event()).content
    response = await client.post(
        "/webhook", content=body, headers=_send_headers("pull_request", "delivery-1", body)
    )

    assert response.status_code == 200
    assert len(handler.pr_calls) == 1
    assert getattr(handler.pr_calls[0], "action", None) == "opened"
    assert handler.pr_calls[0].pull_request.number == 7


async def test_synchronize_action_still_dispatches(
    app_client: tuple[httpx.AsyncClient, RecordingHandler],
) -> None:
    # Transport never filters by action; the orchestration layer decides what to do.
    client, handler = app_client
    payload = _pull_request_event()
    payload["action"] = "synchronize"
    payload["before"] = "0" * 40
    payload["after"] = "f" * 40
    body = httpx.Request("POST", "/webhook", json=payload).content
    response = await client.post(
        "/webhook", content=body, headers=_send_headers("pull_request", "delivery-sync", body)
    )

    assert response.status_code == 200
    assert len(handler.pr_calls) == 1
    assert handler.pr_calls[0].action == "synchronize"


async def test_invalid_signature_returns_401(
    app_client: tuple[httpx.AsyncClient, RecordingHandler],
) -> None:
    client, handler = app_client
    body = httpx.Request("POST", "/webhook", json=_pull_request_event()).content
    headers = _send_headers("pull_request", "delivery-bad", body)
    headers["X-Hub-Signature-256"] = "sha256=" + "0" * 64
    response = await client.post("/webhook", content=body, headers=headers)

    assert response.status_code == 401
    assert handler.pr_calls == []


async def test_missing_signature_returns_401(
    app_client: tuple[httpx.AsyncClient, RecordingHandler],
) -> None:
    client, _ = app_client
    body = httpx.Request("POST", "/webhook", json=_pull_request_event()).content
    response = await client.post(
        "/webhook",
        content=body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": "delivery-2",
            "Content-Type": "application/json",
        },
    )

    assert response.status_code == 401


async def test_missing_github_event_header_returns_400(
    app_client: tuple[httpx.AsyncClient, RecordingHandler],
) -> None:
    client, _ = app_client
    body = httpx.Request("POST", "/webhook", json=_pull_request_event()).content
    headers = _send_headers("pull_request", "delivery-3", body)
    del headers["X-GitHub-Event"]
    response = await client.post("/webhook", content=body, headers=headers)

    assert response.status_code == 400


async def test_missing_delivery_header_returns_400(
    app_client: tuple[httpx.AsyncClient, RecordingHandler],
) -> None:
    client, _ = app_client
    body = httpx.Request("POST", "/webhook", json=_pull_request_event()).content
    headers = _send_headers("pull_request", "delivery-4", body)
    del headers["X-GitHub-Delivery"]
    response = await client.post("/webhook", content=body, headers=headers)

    assert response.status_code == 400


async def test_duplicate_delivery_returns_202(
    app_client: tuple[httpx.AsyncClient, RecordingHandler],
) -> None:
    client, handler = app_client
    body = httpx.Request("POST", "/webhook", json=_pull_request_event()).content
    headers = _send_headers("pull_request", "delivery-dup", body)

    first = await client.post("/webhook", content=body, headers=headers)
    second = await client.post("/webhook", content=body, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 202
    assert len(handler.pr_calls) == 1


async def test_body_over_25mb_returns_413(
    app_client: tuple[httpx.AsyncClient, RecordingHandler],
) -> None:
    client, _ = app_client
    body = b"x" * (25 * 1024 * 1024 + 1)
    response = await client.post(
        "/webhook",
        content=body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": "delivery-big",
            "X-Hub-Signature-256": "sha256=0",
            "Content-Type": "application/octet-stream",
        },
    )

    assert response.status_code == 413


async def test_issue_comment_routes_to_on_issue_comment(
    app_client: tuple[httpx.AsyncClient, RecordingHandler],
) -> None:
    client, handler = app_client
    body = httpx.Request("POST", "/webhook", json=_issue_comment_event()).content
    response = await client.post(
        "/webhook", content=body, headers=_send_headers("issue_comment", "delivery-c", body)
    )

    assert response.status_code == 200
    assert len(handler.comment_calls) == 1
    assert getattr(handler.comment_calls[0], "action", None) == "created"


async def test_unsupported_event_returns_200_without_dispatch(
    app_client: tuple[httpx.AsyncClient, RecordingHandler],
) -> None:
    client, handler = app_client
    body = httpx.Request("POST", "/webhook", json={"action": "ping"}).content
    response = await client.post(
        "/webhook", content=body, headers=_send_headers("ping", "delivery-p", body)
    )

    assert response.status_code == 200
    assert handler.pr_calls == []
    assert handler.comment_calls == []


async def test_unparseable_payload_returns_400(
    app_client: tuple[httpx.AsyncClient, RecordingHandler],
) -> None:
    client, _ = app_client
    body = b"not valid json or anything we can parse"
    response = await client.post(
        "/webhook", content=body, headers=_send_headers("pull_request", "delivery-bad-body", body)
    )

    assert response.status_code == 400


async def test_handler_receives_typed_event_not_raw_dict(
    app_client: tuple[httpx.AsyncClient, RecordingHandler],
) -> None:
    client, handler = app_client
    body = httpx.Request("POST", "/webhook", json=_pull_request_event()).content
    await client.post(
        "/webhook", content=body, headers=_send_headers("pull_request", "delivery-typed", body)
    )

    event = handler.pr_calls[0]
    assert not isinstance(event, dict)
    assert hasattr(event, "pull_request")
    assert hasattr(event, "action")
