"""Per-repo config (`.github/vidi-pr.yml`): schema, fetcher protocol, and trust-aware loader."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from pathlib import PurePosixPath
from typing import Protocol

import yaml
from pathspec import GitIgnoreSpec
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from vidi_pr.config.defaults import ABSENT_CONFIG_ALLOWED_ASSOCIATIONS, Strictness
from vidi_pr.config.operator import DefaultsConfig
from vidi_pr.errors import VidiPrError

CONFIG_PATH = ".github/vidi-pr.yml"
CACHE_TTL = timedelta(minutes=5)

_logger = logging.getLogger(__name__)


class RepoConfigError(VidiPrError):
    pass


class FetchStatus(Enum):
    FOUND = "found"
    NOT_MODIFIED = "not_modified"
    NOT_FOUND = "not_found"


@dataclass(frozen=True)
class FetchResult:
    """
    Outcome of a `RepoConfigFetcher.fetch_text` call.

    `FOUND` carries content + an optional etag. `NOT_MODIFIED` indicates
    the caller-supplied etag matches the current resource (304). `NOT_FOUND`
    indicates the file does not exist on the ref (404).
    """

    status: FetchStatus
    content: str | None = None
    etag: str | None = None

    @classmethod
    def found(cls, content: str, etag: str | None = None) -> FetchResult:
        return cls(status=FetchStatus.FOUND, content=content, etag=etag)

    @classmethod
    def not_modified(cls) -> FetchResult:
        return cls(status=FetchStatus.NOT_MODIFIED)

    @classmethod
    def not_found(cls) -> FetchResult:
        return cls(status=FetchStatus.NOT_FOUND)


class RepoConfigFetcher(Protocol):
    """Fetches text files from a GitHub repo at a given ref."""

    async def fetch_text(
        self, repo: str, ref: str, path: str, *, etag: str | None = None
    ) -> FetchResult: ...


class ReviewConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_context: str | None = None
    project_context_file: str | None = None
    language_notes: dict[str, str] = Field(default_factory=dict)
    focus: list[str] = Field(default_factory=list)
    ignore: list[str] = Field(default_factory=list)
    include_conversation: bool | None = None
    strictness: Strictness | None = None

    @field_validator("project_context_file")
    @classmethod
    def _validate_context_path(cls, value: str | None) -> str | None:
        if value is None:
            return None

        path = PurePosixPath(value)
        if path.is_absolute():
            raise ValueError("project_context_file must be a relative path")

        if any(part == ".." for part in path.parts):
            raise ValueError("project_context_file cannot contain '..' segments")

        return value


class RepoConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    allowed_users: list[str] = Field(default_factory=list)
    allowed_associations: list[str] = Field(default_factory=list)
    trusted_base_branches: list[str] = Field(default_factory=list)
    review: ReviewConfig = Field(default_factory=ReviewConfig)


def is_ignored(repo_config: RepoConfig, path: str) -> bool:
    """Return True if `path` matches any glob in `review.ignore` (gitignore syntax)."""
    patterns = repo_config.review.ignore
    if not patterns:
        return False

    spec = GitIgnoreSpec.from_lines(patterns)
    return spec.match_file(path)


@dataclass
class _CacheEntry:
    etag: str | None
    content: str | None
    fetched_at: datetime


class RepoConfigLoader:
    """
    Resolves a `RepoConfig` for a single PR event using the trust rules from §4.3.

    Steps on every `load()`:
      1. Read config from the repo's default branch (always trusted) via the fetcher.
      2. If the PR's `base_ref` differs from the default branch AND appears in the
         default-branch config's `trusted_base_branches`, also load config from
         `base_ref` and prefer that.
      3. If `project_context_file` is set on the chosen config, fetch it from the
         same trusted ref and inline its contents as `project_context`. A 404 is
         logged at WARNING and the field is treated as unset.
      4. If no config file exists on the trusted ref, return a config derived from
         `operator.defaults` with `allowed_associations=["OWNER"]` (the "owner-only"
         fallback from §4.3.4).

    Fetches go through a per-loader in-memory cache keyed on `(repo, ref, path)`:
    within `CACHE_TTL` (5 min) entries are served outright; past TTL the loader
    revalidates with `If-None-Match`, and a 304 keeps the cached body.
    """

    def __init__(self, fetcher: RepoConfigFetcher, *, defaults: DefaultsConfig) -> None:
        self._fetcher = fetcher
        self._defaults = defaults
        self._cache: dict[tuple[str, str, str], _CacheEntry] = {}

    async def load(self, repo: str, base_ref: str, default_branch: str) -> RepoConfig:
        default_branch_text = await self._cached_fetch(repo, default_branch, CONFIG_PATH)
        if default_branch_text is None:
            return self._absent_config()

        default_branch_config = self._parse(default_branch_text)

        target_config = default_branch_config
        target_ref = default_branch
        if base_ref != default_branch and base_ref in default_branch_config.trusted_base_branches:
            base_ref_text = await self._cached_fetch(repo, base_ref, CONFIG_PATH)
            if base_ref_text is not None:
                target_config = self._parse(base_ref_text)
                target_ref = base_ref

        return await self._resolve_project_context(repo, target_ref, target_config)

    def _parse(self, text: str) -> RepoConfig:
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise RepoConfigError(f"per-repo config is not valid YAML: {exc}") from exc

        if data is None:
            data = {}

        if not isinstance(data, dict):
            raise RepoConfigError(
                f"per-repo config must be a YAML mapping, not {type(data).__name__}"
            )

        try:
            return RepoConfig.model_validate(data)
        except ValidationError as exc:
            raise RepoConfigError(f"per-repo config failed validation: {exc}") from exc

    async def _resolve_project_context(self, repo: str, ref: str, config: RepoConfig) -> RepoConfig:
        path = config.review.project_context_file
        if path is None:
            return config

        result = await self._fetcher.fetch_text(repo, ref, path)
        if result.status is FetchStatus.NOT_FOUND:
            _logger.warning(
                "project_context_file %s not found on %s@%s; using inline project_context",
                path,
                repo,
                ref,
            )
            return config

        if result.status is FetchStatus.NOT_MODIFIED or result.content is None:
            return config

        return config.model_copy(
            update={
                "review": config.review.model_copy(
                    update={"project_context": result.content},
                ),
            },
        )

    async def _cached_fetch(self, repo: str, ref: str, path: str) -> str | None:
        key = (repo, ref, path)
        now = datetime.now(UTC)
        entry = self._cache.get(key)
        if entry is not None and now - entry.fetched_at < CACHE_TTL:
            return entry.content

        result = await self._fetcher.fetch_text(
            repo, ref, path, etag=entry.etag if entry is not None else None
        )

        if result.status is FetchStatus.NOT_MODIFIED and entry is not None:
            entry.fetched_at = now
            return entry.content

        if result.status is FetchStatus.NOT_FOUND:
            self._cache[key] = _CacheEntry(etag=None, content=None, fetched_at=now)
            return None

        self._cache[key] = _CacheEntry(etag=result.etag, content=result.content, fetched_at=now)
        return result.content

    def _absent_config(self) -> RepoConfig:
        return RepoConfig(
            enabled=self._defaults.enabled,
            allowed_users=[],
            allowed_associations=list(ABSENT_CONFIG_ALLOWED_ASSOCIATIONS),
            trusted_base_branches=[],
            review=ReviewConfig(
                include_conversation=self._defaults.include_conversation,
                strictness=self._defaults.strictness,
            ),
        )
