"""Regression tests for the literal contents of `system.md`.

These guard against silent drift: if anyone edits the system prompt and
breaks the rules the spec promises (four section names, no-emoji rule,
no-em-dash rule, anti-injection clause, strictness wording), the test
suite fails loudly.
"""

from vidi_pr.config.defaults import Strictness
from vidi_pr.prompts.loader import load_template
from vidi_pr.prompts.strictness import load_strictness_block


def test_system_prompt_has_all_four_section_headings() -> None:
    text = load_template("system.md")

    for heading in ("## Summary", "## Findings", "## Suggestions", "## Positives"):
        assert heading in text


def test_system_prompt_forbids_emojis() -> None:
    text = load_template("system.md").lower()

    assert "do not use emoji" in text


def test_system_prompt_forbids_em_dashes() -> None:
    text = load_template("system.md").lower()

    assert "em-dash" in text or "em dash" in text


def test_system_prompt_has_anti_injection_clause() -> None:
    text = load_template("system.md")

    assert "<pr_metadata>" in text
    assert "<diff>" in text
    assert "untrusted" in text.lower() or "injection" in text.lower()


def test_strictness_block_files_cover_all_levels() -> None:
    for level in Strictness:
        block = load_strictness_block(level)
        assert block != ""

    assert "clear bugs" in load_strictness_block(Strictness.LENIENT).lower()
    assert "substantive" in load_strictness_block(Strictness.NORMAL).lower()
    assert "close scrutiny" in load_strictness_block(Strictness.STRICT).lower()
