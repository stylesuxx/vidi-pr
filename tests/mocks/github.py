from __future__ import annotations

from dataclasses import dataclass

from vidi_pr.config.repo import FetchResult, RepoConfigFetcher
from vidi_pr.models.review import PRInfo
from vidi_pr.transport.github_client import ReactionKind


@dataclass(frozen=True)
class ReactionCall:
    installation_id: int
    repo: str
    comment_id: int
    reaction: ReactionKind


class MockGitHubClient:
    """
    Test double for `GitHubClient`. Records reactions; returns scripted PR
    metadata and repo-config files. Also serves as the `RepoConfigFetcher`
    for an installation via `for_installation`.
    """

    def __init__(
        self,
        *,
        prs: dict[int, PRInfo] | None = None,
        files: dict[tuple[str, str, str], str] | None = None,
    ) -> None:
        self._prs: dict[int, PRInfo] = prs or {}
        self._files: dict[tuple[str, str, str], str] = files or {}
        self.reactions: list[ReactionCall] = []

    def for_installation(self, installation_id: int) -> RepoConfigFetcher:
        return _BoundFetcher(self, installation_id)

    async def get_pr(self, installation_id: int, repo: str, pr_number: int) -> PRInfo:
        return self._prs[pr_number]

    async def react_to_comment(
        self,
        installation_id: int,
        repo: str,
        comment_id: int,
        reaction: ReactionKind,
    ) -> None:
        self.reactions.append(ReactionCall(installation_id, repo, comment_id, reaction))

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
