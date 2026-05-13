from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from ipaddress import IPv4Network
from pathlib import Path
from typing import Any, cast

import httpx
import pytest_asyncio
from githubkit.webhooks import sign as sign_webhook
from httpx import ASGITransport
from mocks.github import MockGitHubClient
from mocks.llm import MockLLMClient

from vidi_pr.config.defaults import Strictness
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
from vidi_pr.llm.types import ChatResponse, TokenUsage
from vidi_pr.models.review import (
    ChangedFile,
    FileStatus,
    PRInfo,
    RepoInfo,
)
from vidi_pr.models.storage import JobStatus
from vidi_pr.orchestration.handlers import OrchestrationHandler
from vidi_pr.pipeline.reviewer import Reviewer
from vidi_pr.pipeline.worker import Worker
from vidi_pr.storage.db import Database
from vidi_pr.storage.jobs import list_jobs_with_status
from vidi_pr.transport.github_client import GitHubClient
from vidi_pr.transport.server import create_app

_SECRET = "test-secret"
_OWNER = "stylesuxx"
_REPO_NAME = "vidi-pr"
_REPO = f"{_OWNER}/{_REPO_NAME}"
_INSTALLATION_ID = 42
_PR_NUMBER = 7
_HEAD_SHA = "abc123"
_BOT_LOGIN = "vidi-pr[bot]"


def _user(login: str = "stylesuxx", *, is_bot: bool = False) -> dict[str, Any]:
    return {
        "login": login,
        "id": 1,
        "node_id": "U_1",
        "avatar_url": "https://example.com/avatar.png",
        "gravatar_id": "",
        "url": "",
        "html_url": "",
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
        "full_name": _REPO,
        "private": False,
        "owner": _user(_OWNER),
        "html_url": f"https://github.com/{_REPO}",
        "description": None,
        "fork": False,
        "url": f"https://api.github.com/repos/{_REPO}",
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


def _pr_webhook_payload(action: str = "opened") -> dict[str, Any]:
    user = _user()
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
        "number": _PR_NUMBER,
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
        "head": {
            "label": "h:feature",
            "ref": "feature",
            "sha": _HEAD_SHA,
            "user": user,
            "repo": repo,
        },
        "base": {
            "label": "h:main",
            "ref": "main",
            "sha": "def",
            "user": user,
            "repo": repo,
        },
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
        "action": action,
        "number": _PR_NUMBER,
        "pull_request": pr,
        "repository": repo,
        "sender": user,
        "installation": {"id": _INSTALLATION_ID, "node_id": "I_42"},
    }


def _comment_webhook_payload(
    *,
    sender_login: str = "stylesuxx",
    body: str = "@vidi-pr review",
) -> dict[str, Any]:
    user = _user(sender_login)
    repo = _repository()
    reactions = {
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
    }

    issue = {
        "id": 1,
        "node_id": "I_1",
        "url": "",
        "repository_url": "",
        "labels_url": "",
        "comments_url": "",
        "events_url": "",
        "html_url": f"https://github.com/{_REPO}/pull/{_PR_NUMBER}",
        "number": _PR_NUMBER,
        "state": "open",
        "title": "Add feature",
        "body": None,
        "user": _user("stylesuxx"),
        "labels": [],
        "assignee": None,
        "assignees": [],
        "milestone": None,
        "locked": False,
        "active_lock_reason": None,
        "comments": 0,
        "pull_request": {"url": "", "html_url": "", "diff_url": "", "patch_url": ""},
        "closed_at": None,
        "created_at": "2026-05-12T10:00:00Z",
        "updated_at": "2026-05-12T11:00:00Z",
        "author_association": "OWNER",
        "reactions": reactions,
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
        "author_association": "OWNER" if sender_login == "stylesuxx" else "NONE",
        "body": body,
        "performed_via_github_app": None,
        "reactions": reactions,
    }

    return {
        "action": "created",
        "issue": issue,
        "comment": comment,
        "repository": repo,
        "sender": user,
        "installation": {"id": _INSTALLATION_ID, "node_id": "I_42"},
    }


def _operator_config(db_path: Path) -> OperatorConfig:
    return OperatorConfig(
        github=GitHubConfig(app_id=1, private_key_path=Path("/tmp/key.pem")),
        llm=LLMConfig(provider="openai_compat", base_url="http://llm.test/v1", model="m"),
        server=ServerConfig(
            host="127.0.0.1",
            port=8080,
            forwarded_allow_ips=[IPv4Network("127.0.0.0/8")],
        ),
        storage=StorageConfig(db_path=db_path),
        logging=LoggingConfig(),
        pipeline=PipelineConfig(
            job_timeout_seconds=30,
            failure_comment_cooldown_seconds=3600,
        ),
        defaults=DefaultsConfig(
            enabled=True,
            allowed_associations=["OWNER"],
            strictness=Strictness.NORMAL,
            include_conversation=True,
        ),
        webhook_secret=_SECRET,
    )


def _good_response() -> ChatResponse:
    return ChatResponse(
        content="## Summary\n\nOK\n\n## Findings\n\n## Suggestions\n\n## Positives\n\n- nice",
        model="mock",
        usage=TokenUsage(),
    )


def _pr_info(*, draft: bool = False) -> PRInfo:
    return PRInfo(
        number=_PR_NUMBER,
        title="Add feature",
        body=None,
        head_sha=_HEAD_SHA,
        base_ref="main",
        author_login="stylesuxx",
        draft=draft,
    )


def _changed_file() -> ChangedFile:
    return ChangedFile(
        filename="src/main.py",
        status=FileStatus.MODIFIED,
        additions=1,
        deletions=0,
        patch="@@\n+x\n",
    )


@dataclass
class Stack:
    client: httpx.AsyncClient
    github: MockGitHubClient
    llm: MockLLMClient
    worker: Worker
    database: Database


@pytest_asyncio.fixture
async def stack(database: Database, tmp_path: Path) -> AsyncIterator[Stack]:
    github = MockGitHubClient(
        prs={_PR_NUMBER: _pr_info()},
        pr_files={_PR_NUMBER: [_changed_file()]},
        comments={_PR_NUMBER: []},
        repos={_REPO: RepoInfo(full_name=_REPO, default_branch="main", private=False)},
    )

    config = _operator_config(tmp_path / "ignored.db")
    handler = OrchestrationHandler(
        client=cast("GitHubClient", github),
        database=database,
        defaults=config.defaults,
        bot_login=_BOT_LOGIN,
    )

    llm = MockLLMClient([_good_response() for _ in range(10)])
    reviewer = Reviewer(
        github_client=cast("GitHubClient", github),
        llm_client=llm,
        defaults=config.defaults,
        pipeline_config=config.pipeline,
        llm_config=config.llm,
        bot_login=_BOT_LOGIN,
    )

    worker = Worker(
        database=database,
        github_client=cast("GitHubClient", github),
        reviewer=reviewer,
        operator_config=config,
    )

    app = create_app(config=config, database=database, handler=handler)
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield Stack(client=http, github=github, llm=llm, worker=worker, database=database)


def _signed_headers(event: str, delivery: str, body: bytes) -> dict[str, str]:
    return {
        "X-GitHub-Event": event,
        "X-GitHub-Delivery": delivery,
        "X-Hub-Signature-256": sign_webhook(_SECRET, body),
        "Content-Type": "application/json",
    }


async def _drain_worker(worker: Worker) -> int:
    processed = 0
    while await worker.process_one():
        processed += 1

    return processed


async def test_signed_opened_webhook_posts_review_end_to_end(stack: Stack) -> None:
    body = json.dumps(_pr_webhook_payload(action="opened")).encode()
    response = await stack.client.post(
        "/webhook", content=body, headers=_signed_headers("pull_request", "d-1", body)
    )
    assert response.status_code == 200

    processed = await _drain_worker(stack.worker)

    assert processed == 1
    assert len(stack.github.reviews_posted) == 1
    assert "OK" in stack.github.reviews_posted[0].body


async def test_authorized_comment_review_request_posts_review(stack: Stack) -> None:
    body = json.dumps(_comment_webhook_payload()).encode()
    response = await stack.client.post(
        "/webhook", content=body, headers=_signed_headers("issue_comment", "d-1", body)
    )
    assert response.status_code == 200
    assert [r.reaction for r in stack.github.reactions] == ["eyes"]

    await _drain_worker(stack.worker)

    assert len(stack.github.reviews_posted) == 1


async def test_unauthorized_comment_gets_thumbsdown_and_no_review(stack: Stack) -> None:
    body = json.dumps(_comment_webhook_payload(sender_login="random-user")).encode()
    response = await stack.client.post(
        "/webhook", content=body, headers=_signed_headers("issue_comment", "d-1", body)
    )
    assert response.status_code == 200
    assert [r.reaction for r in stack.github.reactions] == ["-1"]

    processed = await _drain_worker(stack.worker)
    assert processed == 0
    assert stack.github.reviews_posted == []


async def test_duplicate_delivery_does_not_double_review(stack: Stack) -> None:
    body = json.dumps(_pr_webhook_payload(action="opened")).encode()
    headers = _signed_headers("pull_request", "d-dup", body)

    first = await stack.client.post("/webhook", content=body, headers=headers)
    second = await stack.client.post("/webhook", content=body, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 202

    await _drain_worker(stack.worker)
    assert len(stack.github.reviews_posted) == 1


async def test_concurrent_triggers_same_pr_produce_exactly_one_review(stack: Stack) -> None:
    payload = _pr_webhook_payload(action="opened")
    body1 = json.dumps(payload).encode()
    body2 = json.dumps(_comment_webhook_payload()).encode()

    responses = await asyncio.gather(
        stack.client.post(
            "/webhook", content=body1, headers=_signed_headers("pull_request", "d-pr", body1)
        ),
        stack.client.post(
            "/webhook", content=body2, headers=_signed_headers("issue_comment", "d-cm", body2)
        ),
    )
    assert all(r.status_code == 200 for r in responses)

    async with stack.database.sessionmaker() as session:
        pending = await list_jobs_with_status(session, JobStatus.PENDING)
    assert len(pending) == 1

    await _drain_worker(stack.worker)
    assert len(stack.github.reviews_posted) == 1
