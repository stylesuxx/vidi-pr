from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

import pytest

from vidi_pr.config.defaults import (
    ABSENT_CONFIG_ALLOWED_ASSOCIATIONS,
    Strictness,
)
from vidi_pr.config.operator import DefaultsConfig
from vidi_pr.config.repo import (
    CACHE_TTL,
    CONFIG_PATH,
    FetchResult,
    RepoConfig,
    RepoConfigError,
    RepoConfigLoader,
    ReviewConfig,
    is_ignored,
)

_REPO = "stylesuxx/vidi-pr"


@dataclass
class FakeFetcher:
    """In-memory fetcher: maps (ref, path) -> (etag, content). Records every call."""

    files: dict[tuple[str, str], tuple[str | None, str]] = field(default_factory=dict)
    calls: list[tuple[str, str, str, str | None]] = field(default_factory=list)

    async def fetch_text(
        self, repo: str, ref: str, path: str, *, etag: str | None = None
    ) -> FetchResult:
        self.calls.append((repo, ref, path, etag))
        existing = self.files.get((ref, path))
        if existing is None:
            return FetchResult.not_found()
        current_etag, content = existing
        if etag is not None and current_etag is not None and etag == current_etag:
            return FetchResult.not_modified()
        return FetchResult.found(content, etag=current_etag)


def _defaults() -> DefaultsConfig:
    return DefaultsConfig()


def _loader(fetcher: FakeFetcher) -> RepoConfigLoader:
    return RepoConfigLoader(fetcher, defaults=_defaults())


async def test_valid_yaml_parses(loader_fixture: None = None) -> None:
    fetcher = FakeFetcher(
        files={
            ("main", CONFIG_PATH): (
                None,
                "enabled: true\nallowed_users: [stylesuxx]\nreview:\n  strictness: strict\n",
            )
        }
    )
    config = await _loader(fetcher).load(_REPO, base_ref="main", default_branch="main")

    assert config.enabled is True
    assert config.allowed_users == ["stylesuxx"]
    assert config.review.strictness is Strictness.STRICT


async def test_invalid_yaml_raises_repo_config_error() -> None:
    fetcher = FakeFetcher(files={("main", CONFIG_PATH): (None, "enabled: [unterminated")})

    with pytest.raises(RepoConfigError):
        await _loader(fetcher).load(_REPO, base_ref="main", default_branch="main")


async def test_yaml_that_is_not_a_mapping_raises() -> None:
    fetcher = FakeFetcher(files={("main", CONFIG_PATH): (None, "- a list, not a map\n")})

    with pytest.raises(RepoConfigError):
        await _loader(fetcher).load(_REPO, base_ref="main", default_branch="main")


async def test_unknown_field_rejected() -> None:
    fetcher = FakeFetcher(files={("main", CONFIG_PATH): (None, "unexpected: nope\n")})

    with pytest.raises(RepoConfigError):
        await _loader(fetcher).load(_REPO, base_ref="main", default_branch="main")


async def test_absent_file_returns_owner_only_defaults() -> None:
    fetcher = FakeFetcher()
    config = await _loader(fetcher).load(_REPO, base_ref="main", default_branch="main")

    assert config.allowed_associations == list(ABSENT_CONFIG_ALLOWED_ASSOCIATIONS)
    assert config.enabled is True
    assert config.review.strictness is Strictness.NORMAL


async def test_loads_from_default_branch_when_base_ref_not_trusted() -> None:
    fetcher = FakeFetcher(
        files={
            ("main", CONFIG_PATH): (None, "review:\n  strictness: lenient\n"),
            ("feature", CONFIG_PATH): (None, "review:\n  strictness: strict\n"),
        }
    )
    config = await _loader(fetcher).load(_REPO, base_ref="feature", default_branch="main")

    assert config.review.strictness is Strictness.LENIENT


async def test_loads_from_base_ref_when_trusted() -> None:
    default_yaml = "trusted_base_branches: [develop]\nreview:\n  strictness: lenient\n"
    develop_yaml = "review:\n  strictness: strict\n"
    fetcher = FakeFetcher(
        files={
            ("main", CONFIG_PATH): (None, default_yaml),
            ("develop", CONFIG_PATH): (None, develop_yaml),
        }
    )
    config = await _loader(fetcher).load(_REPO, base_ref="develop", default_branch="main")

    assert config.review.strictness is Strictness.STRICT


async def test_trusted_base_ref_missing_file_falls_back_to_default_branch() -> None:
    default_yaml = "trusted_base_branches: [develop]\nreview:\n  strictness: lenient\n"
    fetcher = FakeFetcher(files={("main", CONFIG_PATH): (None, default_yaml)})

    config = await _loader(fetcher).load(_REPO, base_ref="develop", default_branch="main")
    assert config.review.strictness is Strictness.LENIENT


async def test_project_context_file_overrides_inline() -> None:
    repo_yaml = "review:\n  project_context: inline\n  project_context_file: .github/context.md\n"
    fetcher = FakeFetcher(
        files={
            ("main", CONFIG_PATH): (None, repo_yaml),
            ("main", ".github/context.md"): (None, "FROM FILE"),
        }
    )
    config = await _loader(fetcher).load(_REPO, base_ref="main", default_branch="main")

    assert config.review.project_context == "FROM FILE"


async def test_missing_project_context_file_logs_and_keeps_inline(
    caplog: pytest.LogCaptureFixture,
) -> None:
    repo_yaml = "review:\n  project_context: inline\n  project_context_file: .github/context.md\n"
    fetcher = FakeFetcher(files={("main", CONFIG_PATH): (None, repo_yaml)})

    with caplog.at_level("WARNING"):
        config = await _loader(fetcher).load(_REPO, base_ref="main", default_branch="main")

    assert config.review.project_context == "inline"
    assert any("project_context_file" in record.message for record in caplog.records)


async def test_absolute_project_context_file_path_rejected() -> None:
    fetcher = FakeFetcher(
        files={
            ("main", CONFIG_PATH): (None, "review:\n  project_context_file: /etc/secret\n"),
        }
    )
    with pytest.raises(RepoConfigError):
        await _loader(fetcher).load(_REPO, base_ref="main", default_branch="main")


async def test_traversing_project_context_file_path_rejected() -> None:
    fetcher = FakeFetcher(
        files={
            ("main", CONFIG_PATH): (None, "review:\n  project_context_file: ../etc/secret\n"),
        }
    )
    with pytest.raises(RepoConfigError):
        await _loader(fetcher).load(_REPO, base_ref="main", default_branch="main")


async def test_cache_hit_within_ttl_skips_fetcher() -> None:
    fetcher = FakeFetcher(files={("main", CONFIG_PATH): (None, "enabled: false\n")})
    loader = _loader(fetcher)
    await loader.load(_REPO, base_ref="main", default_branch="main")
    calls_after_first = len(fetcher.calls)

    await loader.load(_REPO, base_ref="main", default_branch="main")
    assert len(fetcher.calls) == calls_after_first


def test_is_ignored_matches_gitignore_globs() -> None:
    config = RepoConfig(review=ReviewConfig(ignore=["vendor/**", "*.min.js"]))

    assert is_ignored(config, "vendor/foo.go") is True
    assert is_ignored(config, "vendor/sub/dir/lib.go") is True
    assert is_ignored(config, "main.go") is False
    assert is_ignored(config, "app.min.js") is True


def test_is_ignored_returns_false_when_no_patterns() -> None:
    assert is_ignored(RepoConfig(), "anything.go") is False


async def test_past_ttl_revalidates_and_keeps_cached_on_304() -> None:
    fetcher = FakeFetcher(files={("main", CONFIG_PATH): ("etag-1", "enabled: false\n")})
    loader = _loader(fetcher)
    await loader.load(_REPO, base_ref="main", default_branch="main")

    entry = loader._cache[(_REPO, "main", CONFIG_PATH)]
    entry.fetched_at -= CACHE_TTL + timedelta(seconds=1)

    config = await loader.load(_REPO, base_ref="main", default_branch="main")

    revalidation_call = fetcher.calls[-1]
    assert revalidation_call == (_REPO, "main", CONFIG_PATH, "etag-1")
    assert config.enabled is False
