from __future__ import annotations

import base64
from collections.abc import AsyncIterator
from types import TracebackType
from typing import Any, Literal, Self

from githubkit import GitHub
from githubkit.auth import AppInstallationAuthStrategy
from githubkit.exception import RequestFailed

from vidi_pr.config.repo import FetchResult, RepoConfigFetcher
from vidi_pr.models.review import (
    ChangedFile,
    ConversationComment,
    FileStatus,
    PRInfo,
    RepoInfo,
)
from vidi_pr.transport.errors import (
    GitHubAuthError,
    GitHubError,
    GitHubNotFound,
    GitHubPermanentError,
    GitHubTransientError,
)

ReactionKind = Literal["+1", "-1", "laugh", "confused", "heart", "hooray", "rocket", "eyes"]

_PER_PAGE = 100


class GitHubClient:
    def __init__(self, *, app_id: int, private_key: str, timeout: float = 30.0) -> None:
        self._app_id = app_id
        self._private_key = private_key
        self._timeout = timeout
        self._installations: dict[int, GitHub[AppInstallationAuthStrategy]] = {}

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        for client in self._installations.values():
            await client.__aexit__(None, None, None)

        self._installations.clear()

    def for_installation(self, installation_id: int) -> RepoConfigFetcher:
        return _InstallationFetcher(self, installation_id)

    async def get_pr(self, installation_id: int, repo: str, pr_number: int) -> PRInfo:
        owner, name = _split_repo(repo)

        async def call(gh: GitHub[AppInstallationAuthStrategy]) -> Any:
            return await gh.rest.pulls.async_get(owner=owner, repo=name, pull_number=pr_number)

        response = await self._with_auth_retry(installation_id, call)
        pr = response.parsed_data
        return PRInfo(
            number=pr.number,
            title=pr.title,
            body=pr.body,
            head_sha=pr.head.sha,
            base_ref=pr.base.ref,
            author_login=pr.user.login if pr.user else "",
            draft=bool(pr.draft) if pr.draft is not None else False,
        )

    async def get_pr_files(
        self, installation_id: int, repo: str, pr_number: int
    ) -> list[ChangedFile]:
        owner, name = _split_repo(repo)
        gh = self._gh(installation_id)
        entries: AsyncIterator[Any] = gh.paginate(
            gh.rest.pulls.async_list_files,
            owner=owner,
            repo=name,
            pull_number=pr_number,
            per_page=_PER_PAGE,
        )

        try:
            return [
                ChangedFile(
                    filename=entry.filename,
                    status=_map_file_status(entry.status),
                    additions=entry.additions,
                    deletions=entry.deletions,
                    patch=entry.patch,
                )
                async for entry in entries
            ]
        except RequestFailed as exc:
            raise _map_error(exc) from exc

    async def get_pr_comments(
        self, installation_id: int, repo: str, pr_number: int
    ) -> list[ConversationComment]:
        owner, name = _split_repo(repo)
        gh = self._gh(installation_id)
        comments: AsyncIterator[Any] = gh.paginate(
            gh.rest.issues.async_list_comments,
            owner=owner,
            repo=name,
            issue_number=pr_number,
            per_page=_PER_PAGE,
        )

        results: list[ConversationComment] = []
        try:
            async for comment in comments:
                user = comment.user
                login = user.login if user else ""
                is_bot = bool(user and user.type == "Bot")
                results.append(
                    ConversationComment(
                        author_login=login,
                        is_bot=is_bot,
                        body=comment.body or "",
                        created_at=comment.created_at,
                    )
                )
        except RequestFailed as exc:
            raise _map_error(exc) from exc

        return results

    async def get_repo(self, installation_id: int, repo: str) -> RepoInfo:
        owner, name = _split_repo(repo)

        async def call(gh: GitHub[AppInstallationAuthStrategy]) -> Any:
            return await gh.rest.repos.async_get(owner=owner, repo=name)

        response = await self._with_auth_retry(installation_id, call)
        repo_data = response.parsed_data
        return RepoInfo(
            full_name=repo_data.full_name,
            default_branch=repo_data.default_branch,
            private=repo_data.private,
        )

    async def create_review(
        self, installation_id: int, repo: str, pr_number: int, body: str
    ) -> int:
        owner, name = _split_repo(repo)

        async def call(gh: GitHub[AppInstallationAuthStrategy]) -> Any:
            return await gh.rest.pulls.async_create_review(
                owner=owner,
                repo=name,
                pull_number=pr_number,
                data={"body": body, "event": "COMMENT"},
            )

        response = await self._with_auth_retry(installation_id, call)
        review = response.parsed_data
        return int(review.id)

    async def create_comment(
        self, installation_id: int, repo: str, issue_number: int, body: str
    ) -> int:
        owner, name = _split_repo(repo)

        async def call(gh: GitHub[AppInstallationAuthStrategy]) -> Any:
            return await gh.rest.issues.async_create_comment(
                owner=owner, repo=name, issue_number=issue_number, data={"body": body}
            )

        response = await self._with_auth_retry(installation_id, call)
        comment = response.parsed_data
        return int(comment.id)

    async def react_to_comment(
        self, installation_id: int, repo: str, comment_id: int, reaction: ReactionKind
    ) -> None:
        owner, name = _split_repo(repo)

        async def call(gh: GitHub[AppInstallationAuthStrategy]) -> Any:
            return await gh.rest.reactions.async_create_for_issue_comment(
                owner=owner, repo=name, comment_id=comment_id, content=reaction
            )

        await self._with_auth_retry(installation_id, call)

    async def fetch_text(
        self,
        installation_id: int,
        repo: str,
        ref: str,
        path: str,
        *,
        etag: str | None = None,
    ) -> FetchResult:
        owner, name = _split_repo(repo)
        headers: dict[str, str] = {}
        if etag is not None:
            headers["If-None-Match"] = etag

        async def call(gh: GitHub[AppInstallationAuthStrategy]) -> Any:
            return await gh.rest.repos.async_get_content(
                owner=owner, repo=name, path=path, ref=ref, headers=headers
            )

        try:
            response = await self._with_auth_retry(installation_id, call)
        except GitHubNotFound:
            return FetchResult.not_found()

        if response.status_code == 304:
            return FetchResult.not_modified()

        data = response.parsed_data
        if isinstance(data, list):
            raise GitHubError(f"path {path!r} on {repo}@{ref} is a directory, not a file")

        if not hasattr(data, "content") or not hasattr(data, "encoding"):
            raise GitHubError(f"path {path!r} on {repo}@{ref} is not a regular file")

        if data.encoding != "base64":
            raise GitHubError(f"unexpected content encoding: {data.encoding}")

        decoded = base64.b64decode(data.content).decode("utf-8")
        response_etag = response.headers.get("ETag")
        return FetchResult.found(decoded, etag=response_etag)

    def _gh(self, installation_id: int) -> GitHub[AppInstallationAuthStrategy]:
        cached = self._installations.get(installation_id)
        if cached is not None:
            return cached

        strategy = AppInstallationAuthStrategy(
            app_id=str(self._app_id),
            private_key=self._private_key,
            installation_id=installation_id,
        )
        github = GitHub(strategy, timeout=self._timeout)
        self._installations[installation_id] = github

        return github

    async def _with_auth_retry(
        self,
        installation_id: int,
        op: Any,
    ) -> Any:
        try:
            return await op(self._gh(installation_id))
        except RequestFailed as exc:
            status = exc.response.status_code
            if status == 401:
                await self._drop_cached(installation_id)
                try:
                    return await op(self._gh(installation_id))
                except RequestFailed as second:
                    if second.response.status_code == 401:
                        raise GitHubAuthError(_message(second)) from second

                    raise _map_error(second) from second

            raise _map_error(exc) from exc

    async def _drop_cached(self, installation_id: int) -> None:
        cached = self._installations.pop(installation_id, None)
        if cached is not None:
            await cached.__aexit__(None, None, None)


class _InstallationFetcher:
    def __init__(self, client: GitHubClient, installation_id: int) -> None:
        self._client = client
        self._installation_id = installation_id

    async def fetch_text(
        self, repo: str, ref: str, path: str, *, etag: str | None = None
    ) -> FetchResult:
        return await self._client.fetch_text(self._installation_id, repo, ref, path, etag=etag)


def _split_repo(repo: str) -> tuple[str, str]:
    owner, _, name = repo.partition("/")
    if not owner or not name:
        raise ValueError(f"repo must be in 'owner/name' form, got {repo!r}")

    return owner, name


_FILE_STATUS_MAP: dict[str, FileStatus] = {
    "added": FileStatus.ADDED,
    "modified": FileStatus.MODIFIED,
    "removed": FileStatus.REMOVED,
    "renamed": FileStatus.RENAMED,
    "copied": FileStatus.MODIFIED,
    "changed": FileStatus.MODIFIED,
    "unchanged": FileStatus.MODIFIED,
}


def _map_file_status(status: str) -> FileStatus:
    return _FILE_STATUS_MAP.get(status, FileStatus.MODIFIED)


def _message(exc: RequestFailed) -> str:
    return f"{exc.response.status_code}: {exc.response.text}"


def _map_error(exc: RequestFailed) -> GitHubError:
    status = exc.response.status_code
    message = _message(exc)
    if status == 404:
        return GitHubNotFound(message)

    if 500 <= status < 600:
        return GitHubTransientError(message)

    return GitHubPermanentError(message)
