from __future__ import annotations

from dataclasses import dataclass

from vidi_pr.config.repo import FetchResult, RepoConfigFetcher
from vidi_pr.models.review import ChangedFile, ConversationComment, PRInfo, RepoInfo
from vidi_pr.transport.github_client import ReactionKind


@dataclass(frozen=True)
class ReactionCall:
    installation_id: int
    repo: str
    comment_id: int
    reaction: ReactionKind


@dataclass(frozen=True)
class ReviewCall:
    installation_id: int
    repo: str
    pr_number: int
    body: str


@dataclass(frozen=True)
class CommentCall:
    installation_id: int
    repo: str
    issue_number: int
    body: str


class MockGitHubClient:
    """
    Records calls; returns scripted PR metadata, file lists, conversation,
    repo info, and content fetches. Also serves as the `RepoConfigFetcher`
    for an installation via `for_installation`.
    """

    def __init__(
        self,
        *,
        prs: dict[int, PRInfo] | None = None,
        files: dict[tuple[str, str, str], str] | None = None,
        pr_files: dict[int, list[ChangedFile]] | None = None,
        comments: dict[int, list[ConversationComment]] | None = None,
        repos: dict[str, RepoInfo] | None = None,
    ) -> None:
        self._prs: dict[int, PRInfo] = prs or {}
        self._files: dict[tuple[str, str, str], str] = files or {}
        self._pr_files: dict[int, list[ChangedFile]] = pr_files or {}
        self._comments: dict[int, list[ConversationComment]] = comments or {}
        self._repos: dict[str, RepoInfo] = repos or {}
        self.reactions: list[ReactionCall] = []
        self.reviews_posted: list[ReviewCall] = []
        self.comments_posted: list[CommentCall] = []
        self.next_review_id: int = 1
        self._post_failures: list[Exception] = []

    def queue_post_failures(self, *exceptions: Exception) -> None:
        self._post_failures.extend(exceptions)

    def for_installation(self, installation_id: int) -> RepoConfigFetcher:
        return _BoundFetcher(self, installation_id)

    async def get_pr(self, installation_id: int, repo: str, pr_number: int) -> PRInfo:
        return self._prs[pr_number]

    async def get_pr_files(
        self, installation_id: int, repo: str, pr_number: int
    ) -> list[ChangedFile]:
        return list(self._pr_files.get(pr_number, []))

    async def get_pr_comments(
        self, installation_id: int, repo: str, pr_number: int
    ) -> list[ConversationComment]:
        return list(self._comments.get(pr_number, []))

    async def get_repo(self, installation_id: int, repo: str) -> RepoInfo:
        return self._repos[repo]

    async def create_review(
        self,
        installation_id: int,
        repo: str,
        pr_number: int,
        body: str,
    ) -> int:
        if self._post_failures:
            raise self._post_failures.pop(0)

        review_id = self.next_review_id
        self.next_review_id += 1
        self.reviews_posted.append(ReviewCall(installation_id, repo, pr_number, body))

        return review_id

    async def create_comment(
        self,
        installation_id: int,
        repo: str,
        issue_number: int,
        body: str,
    ) -> int:
        self.comments_posted.append(CommentCall(installation_id, repo, issue_number, body))
        return 1

    async def react_to_comment(
        self,
        installation_id: int,
        repo: str,
        comment_id: int,
        reaction: ReactionKind,
    ) -> None:
        self.reactions.append(ReactionCall(installation_id, repo, comment_id, reaction))

    async def aclose(self) -> None:
        return None

    async def _fetch(self, repo: str, ref: str, path: str, *, etag: str | None) -> FetchResult:
        content = self._files.get((repo, ref, path))
        if content is None:
            return FetchResult.not_found()

        return FetchResult.found(content)


@dataclass(frozen=True)
class _BoundFetcher:
    client: MockGitHubClient
    installation_id: int

    async def fetch_text(
        self, repo: str, ref: str, path: str, *, etag: str | None = None
    ) -> FetchResult:
        return await self.client._fetch(repo, ref, path, etag=etag)
