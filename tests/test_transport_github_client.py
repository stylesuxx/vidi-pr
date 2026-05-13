from __future__ import annotations

import base64
import json
from typing import Any

import pytest
from pytest_httpx import HTTPXMock

from vidi_pr.config.repo import FetchStatus
from vidi_pr.models.review import FileStatus
from vidi_pr.transport.errors import GitHubNotFound, GitHubPermanentError, GitHubTransientError
from vidi_pr.transport.github_client import GitHubClient

_INSTALLATION_ID = 42
_TOKEN_URL = f"https://api.github.com/app/installations/{_INSTALLATION_ID}/access_tokens"
_OWNER = "stylesuxx"
_REPO_NAME = "vidi-pr"
_REPO = f"{_OWNER}/{_REPO_NAME}"
_PR_NUMBER = 7


def _mock_token(httpx_mock: HTTPXMock, *, token: str = "ghs_test") -> None:
    httpx_mock.add_response(
        method="POST",
        url=_TOKEN_URL,
        status_code=201,
        json={
            "token": token,
            "expires_at": "2099-01-01T00:00:00Z",
            "permissions": {"contents": "read"},
            "repository_selection": "all",
        },
    )


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


def _pr_response() -> dict[str, Any]:
    user = _user("stylesuxx")
    repo = _repo_response()
    return {
        "url": f"https://api.github.com/repos/{_REPO}/pulls/{_PR_NUMBER}",
        "id": 1,
        "node_id": "PR_1",
        "html_url": f"https://github.com/{_REPO}/pull/{_PR_NUMBER}",
        "diff_url": f"https://github.com/{_REPO}/pull/{_PR_NUMBER}.diff",
        "patch_url": f"https://github.com/{_REPO}/pull/{_PR_NUMBER}.patch",
        "issue_url": f"https://api.github.com/repos/{_REPO}/issues/{_PR_NUMBER}",
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
        "body": "PR body",
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
            "label": f"{_OWNER}:feature",
            "ref": "feature",
            "sha": "abc123",
            "user": user,
            "repo": repo,
        },
        "base": {
            "label": f"{_OWNER}:main",
            "ref": "main",
            "sha": "def456",
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


def _file_entry(filename: str, status: str = "modified") -> dict[str, Any]:
    return {
        "sha": "filesha",
        "filename": filename,
        "status": status,
        "additions": 1,
        "deletions": 0,
        "changes": 1,
        "blob_url": "",
        "raw_url": "",
        "contents_url": "",
        "patch": "@@ -1 +1,2 @@\n+added\n",
    }


def _issue_comment(login: str = "stylesuxx", body: str = "comment body") -> dict[str, Any]:
    return {
        "id": 1,
        "node_id": "IC_1",
        "url": "",
        "html_url": "",
        "issue_url": "",
        "body": body,
        "user": _user(login),
        "created_at": "2026-05-12T12:00:00Z",
        "updated_at": "2026-05-12T12:00:00Z",
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


def _repo_response() -> dict[str, Any]:
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


async def test_fetch_text_not_found(httpx_mock: HTTPXMock, app_private_key: str) -> None:
    _mock_token(httpx_mock)
    httpx_mock.add_response(
        method="GET",
        url=f"https://api.github.com/repos/{_REPO}/contents/foo.txt?ref=main",
        status_code=404,
        json={"message": "Not Found", "documentation_url": ""},
    )

    async with GitHubClient(app_id=1, private_key=app_private_key) as client:
        result = await client.fetch_text(_INSTALLATION_ID, _REPO, "main", "foo.txt")

    assert result.status is FetchStatus.NOT_FOUND


async def test_fetch_text_not_modified_on_304(httpx_mock: HTTPXMock, app_private_key: str) -> None:
    _mock_token(httpx_mock)
    httpx_mock.add_response(
        method="GET",
        url=f"https://api.github.com/repos/{_REPO}/contents/foo.txt?ref=main",
        status_code=304,
    )

    async with GitHubClient(app_id=1, private_key=app_private_key) as client:
        result = await client.fetch_text(_INSTALLATION_ID, _REPO, "main", "foo.txt", etag='W/"old"')

    assert result.status is FetchStatus.NOT_MODIFIED


async def test_fetch_text_decodes_base64(httpx_mock: HTTPXMock, app_private_key: str) -> None:
    encoded = base64.b64encode(b"file contents here").decode()
    _mock_token(httpx_mock)
    httpx_mock.add_response(
        method="GET",
        url=f"https://api.github.com/repos/{_REPO}/contents/foo.txt?ref=main",
        status_code=200,
        headers={"ETag": 'W/"abc"'},
        json={
            "name": "foo.txt",
            "path": "foo.txt",
            "sha": "filesha",
            "size": len(encoded),
            "url": "",
            "html_url": "",
            "git_url": "",
            "download_url": "",
            "type": "file",
            "content": encoded,
            "encoding": "base64",
            "_links": {"self": "", "git": "", "html": ""},
        },
    )

    async with GitHubClient(app_id=1, private_key=app_private_key) as client:
        result = await client.fetch_text(_INSTALLATION_ID, _REPO, "main", "foo.txt")

    assert result.status is FetchStatus.FOUND
    assert result.content == "file contents here"
    assert result.etag == 'W/"abc"'


async def test_create_review_always_sends_event_comment(
    httpx_mock: HTTPXMock, app_private_key: str
) -> None:
    _mock_token(httpx_mock)
    httpx_mock.add_response(
        method="POST",
        url=f"https://api.github.com/repos/{_REPO}/pulls/{_PR_NUMBER}/reviews",
        status_code=200,
        json={
            "id": 1001,
            "node_id": "PRR_1",
            "user": _user(),
            "body": "the review",
            "state": "COMMENTED",
            "html_url": "",
            "pull_request_url": "",
            "_links": {"html": {"href": ""}, "pull_request": {"href": ""}},
            "submitted_at": "2026-05-12T13:00:00Z",
            "commit_id": "abc",
            "author_association": "OWNER",
        },
    )

    async with GitHubClient(app_id=1, private_key=app_private_key) as client:
        review_id = await client.create_review(_INSTALLATION_ID, _REPO, _PR_NUMBER, "the review")

    assert review_id == 1001

    review_request = httpx_mock.get_request(
        method="POST",
        url=f"https://api.github.com/repos/{_REPO}/pulls/{_PR_NUMBER}/reviews",
    )
    assert review_request is not None
    body = json.loads(review_request.content)
    assert body == {"body": "the review", "event": "COMMENT"}


async def test_react_to_comment_posts_reaction_verbatim(
    httpx_mock: HTTPXMock, app_private_key: str
) -> None:
    _mock_token(httpx_mock)
    httpx_mock.add_response(
        method="POST",
        url=f"https://api.github.com/repos/{_REPO}/issues/comments/99/reactions",
        status_code=201,
        json={
            "id": 1,
            "node_id": "RC_1",
            "user": _user(),
            "content": "eyes",
            "created_at": "2026-05-12T13:00:00Z",
        },
    )

    async with GitHubClient(app_id=1, private_key=app_private_key) as client:
        await client.react_to_comment(_INSTALLATION_ID, _REPO, 99, "eyes")

    request = httpx_mock.get_request(
        method="POST",
        url=f"https://api.github.com/repos/{_REPO}/issues/comments/99/reactions",
    )
    assert request is not None
    body = json.loads(request.content)
    assert body == {"content": "eyes"}


async def test_get_pr_maps_to_pr_info(httpx_mock: HTTPXMock, app_private_key: str) -> None:
    _mock_token(httpx_mock)
    httpx_mock.add_response(
        method="GET",
        url=f"https://api.github.com/repos/{_REPO}/pulls/{_PR_NUMBER}",
        json=_pr_response(),
    )

    async with GitHubClient(app_id=1, private_key=app_private_key) as client:
        pr = await client.get_pr(_INSTALLATION_ID, _REPO, _PR_NUMBER)

    assert pr.number == _PR_NUMBER
    assert pr.title == "Add feature"
    assert pr.head_sha == "abc123"
    assert pr.base_ref == "main"
    assert pr.author_login == "stylesuxx"
    assert pr.draft is False


async def test_get_pr_files_paginates(httpx_mock: HTTPXMock, app_private_key: str) -> None:
    _mock_token(httpx_mock)
    page2_url = f"https://api.github.com/repos/{_REPO}/pulls/{_PR_NUMBER}/files?per_page=100&page=2"
    httpx_mock.add_response(
        method="GET",
        url=f"https://api.github.com/repos/{_REPO}/pulls/{_PR_NUMBER}/files?per_page=100",
        json=[_file_entry(f"page1_{i}.py") for i in range(2)],
        headers={"Link": f'<{page2_url}>; rel="next", <{page2_url}>; rel="last"'},
    )
    httpx_mock.add_response(
        method="GET",
        url=page2_url,
        json=[_file_entry("page2.py", status="added")],
    )

    async with GitHubClient(app_id=1, private_key=app_private_key) as client:
        files = await client.get_pr_files(_INSTALLATION_ID, _REPO, _PR_NUMBER)

    assert [f.filename for f in files] == ["page1_0.py", "page1_1.py", "page2.py"]
    assert files[-1].status is FileStatus.ADDED


async def test_get_pr_comments_maps_user_type_to_is_bot(
    httpx_mock: HTTPXMock, app_private_key: str
) -> None:
    _mock_token(httpx_mock)
    httpx_mock.add_response(
        method="GET",
        url=f"https://api.github.com/repos/{_REPO}/issues/{_PR_NUMBER}/comments?per_page=100",
        json=[
            _issue_comment("alice", "human says hi"),
            {
                **_issue_comment("vidi-pr[bot]", "bot says hi"),
                "user": _user("vidi-pr[bot]", is_bot=True),
            },
        ],
    )

    async with GitHubClient(app_id=1, private_key=app_private_key) as client:
        comments = await client.get_pr_comments(_INSTALLATION_ID, _REPO, _PR_NUMBER)

    assert len(comments) == 2
    assert comments[0].is_bot is False
    assert comments[1].is_bot is True


async def test_get_repo_returns_default_branch(httpx_mock: HTTPXMock, app_private_key: str) -> None:
    _mock_token(httpx_mock)
    httpx_mock.add_response(
        method="GET",
        url=f"https://api.github.com/repos/{_REPO}",
        json=_repo_response(),
    )

    async with GitHubClient(app_id=1, private_key=app_private_key) as client:
        repo_info = await client.get_repo(_INSTALLATION_ID, _REPO)

    assert repo_info.full_name == _REPO
    assert repo_info.default_branch == "main"
    assert repo_info.private is False


async def test_installation_token_is_cached_across_calls(
    httpx_mock: HTTPXMock, app_private_key: str
) -> None:
    _mock_token(httpx_mock)
    httpx_mock.add_response(
        method="GET",
        url=f"https://api.github.com/repos/{_REPO}",
        json=_repo_response(),
        is_reusable=True,
    )

    async with GitHubClient(app_id=1, private_key=app_private_key) as client:
        await client.get_repo(_INSTALLATION_ID, _REPO)
        await client.get_repo(_INSTALLATION_ID, _REPO)
        await client.get_repo(_INSTALLATION_ID, _REPO)

    token_requests = httpx_mock.get_requests(method="POST", url=_TOKEN_URL)
    assert len(token_requests) == 1


async def test_4xx_other_than_404_raises_permanent_error(
    httpx_mock: HTTPXMock, app_private_key: str
) -> None:
    _mock_token(httpx_mock)
    httpx_mock.add_response(
        method="GET",
        url=f"https://api.github.com/repos/{_REPO}/pulls/{_PR_NUMBER}",
        status_code=422,
        json={"message": "Unprocessable", "documentation_url": ""},
    )

    async with GitHubClient(app_id=1, private_key=app_private_key) as client:
        with pytest.raises(GitHubPermanentError):
            await client.get_pr(_INSTALLATION_ID, _REPO, _PR_NUMBER)


async def test_5xx_raises_transient_error(httpx_mock: HTTPXMock, app_private_key: str) -> None:
    _mock_token(httpx_mock)
    # githubkit retries 5xx internally before re-raising, so the mock must be reusable.
    httpx_mock.add_response(
        method="GET",
        url=f"https://api.github.com/repos/{_REPO}/pulls/{_PR_NUMBER}",
        status_code=503,
        text="busy",
        is_reusable=True,
    )

    async with GitHubClient(app_id=1, private_key=app_private_key) as client:
        with pytest.raises(GitHubTransientError):
            await client.get_pr(_INSTALLATION_ID, _REPO, _PR_NUMBER)


async def test_404_raises_github_not_found(httpx_mock: HTTPXMock, app_private_key: str) -> None:
    _mock_token(httpx_mock)
    httpx_mock.add_response(
        method="GET",
        url=f"https://api.github.com/repos/{_REPO}",
        status_code=404,
        json={"message": "Not Found", "documentation_url": ""},
    )

    async with GitHubClient(app_id=1, private_key=app_private_key) as client:
        with pytest.raises(GitHubNotFound):
            await client.get_repo(_INSTALLATION_ID, _REPO)


def test_for_installation_returns_repo_config_fetcher(app_private_key: str) -> None:
    client = GitHubClient(app_id=1, private_key=app_private_key)
    fetcher = client.for_installation(_INSTALLATION_ID)

    assert hasattr(fetcher, "fetch_text")
