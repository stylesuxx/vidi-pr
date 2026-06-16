from __future__ import annotations

from pathlib import Path

import pytest

from vidi_pr.dryrun import (
    DryRunConfig,
    DryRunError,
    format_report,
    parse_pr_url,
)
from vidi_pr.llm.types import Message, Role
from vidi_pr.models.storage import JobStatus, JobStatusDetail
from vidi_pr.pipeline.reviewer import PromptDump, RenderedReview, ReviewResult
from vidi_pr.transport.github_client import GitHubClient


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://github.com/stylesuxx/vidi-pr/pull/7", ("stylesuxx/vidi-pr", 7)),
        ("http://github.com/o/r/pull/123/files", ("o/r", 123)),
        ("github.com/o/r/pull/9", ("o/r", 9)),
        ("  https://github.com/o/r/pull/42#discussion  ", ("o/r", 42)),
        ("stylesuxx/vidi-pr#7", ("stylesuxx/vidi-pr", 7)),
    ],
)
def test_parse_pr_url_accepts_supported_forms(value: str, expected: tuple[str, int]) -> None:
    assert parse_pr_url(value) == expected


@pytest.mark.parametrize("value", ["not a url", "https://github.com/o/r", "o/r", "o/r#x"])
def test_parse_pr_url_rejects_garbage(value: str) -> None:
    with pytest.raises(DryRunError):
        parse_pr_url(value)


def test_config_load_ignores_operator_only_sections(tmp_path: Path) -> None:
    config_file = tmp_path / "vidi-pr.yml"
    config_file.write_text(
        "github:\n"
        "  app_id: 1\n"
        "  private_key_path: /nope.pem\n"
        "storage:\n"
        "  db_path: /nope.db\n"
        "llm:\n"
        "  provider: openai_compat\n"
        "  base_url: http://llm.test/v1\n"
        "  model: test-model\n",
        encoding="utf-8",
    )

    config = DryRunConfig.load(config_file)

    assert config.llm.model == "test-model"
    assert config.pipeline.max_files == 50


def test_config_load_requires_llm_section(tmp_path: Path) -> None:
    config_file = tmp_path / "vidi-pr.yml"
    config_file.write_text("storage:\n  db_path: /nope.db\n", encoding="utf-8")

    with pytest.raises(DryRunError):
        DryRunConfig.load(config_file)


def test_format_report_emits_body_and_summary() -> None:
    rendered = RenderedReview(
        body="## Summary\n\nLooks fine.",
        status_detail=None,
        duration_seconds=1.5,
        chunk_count=2,
        prompt_tokens=100,
        completion_tokens=20,
        prompts=[
            PromptDump(
                label="review",
                messages=[
                    Message(role=Role.SYSTEM, content="be terse"),
                    Message(role=Role.USER, content="the diff"),
                ],
            )
        ],
    )

    stdout, stderr = format_report(
        repo="o/r", pr_number=3, model="m", rendered=rendered, dump_prompts=True
    )

    assert stdout == "## Summary\n\nLooks fine."
    assert "o/r#3" in stderr
    assert "chunks: 2" in stderr
    assert "tokens: 100 prompt / 20 completion" in stderr
    assert "be terse" in stderr
    assert "the diff" in stderr


def test_format_report_without_dump_omits_prompts() -> None:
    rendered = RenderedReview(body="body", prompts=[PromptDump("review", [])])

    stdout, stderr = format_report(
        repo="o/r", pr_number=3, model="m", rendered=rendered, dump_prompts=False
    )

    assert stdout == "body"
    assert "prompt:" not in stderr


def test_format_report_reports_early_exit() -> None:
    rendered = RenderedReview(
        early_result=ReviewResult(
            status=JobStatus.DONE,
            status_detail=JobStatusDetail.NO_REVIEWABLE_FILES,
        )
    )

    stdout, stderr = format_report(
        repo="o/r", pr_number=3, model="m", rendered=rendered, dump_prompts=False
    )

    assert "no_reviewable_files" in stdout
    assert "detail: no_reviewable_files" in stderr


def test_from_token_routes_all_installations_to_one_client() -> None:
    client = GitHubClient.from_token("ghp_test")

    gh = client._gh(111)

    assert gh is client._gh(222)


def test_from_token_unauthenticated_when_token_is_none() -> None:
    client = GitHubClient.from_token(None)

    assert client._gh(0) is not None
