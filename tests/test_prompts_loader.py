import pytest

from vidi_pr.prompts.loader import TemplateError, load_template, render_template


def test_load_existing_template_returns_text() -> None:
    text = load_template("system.md")

    assert isinstance(text, str)
    assert "## Summary" in text


def test_load_template_accepts_name_without_md_suffix() -> None:
    a = load_template("system")
    b = load_template("system.md")

    assert a == b


def test_load_missing_template_raises() -> None:
    with pytest.raises(TemplateError):
        load_template("does_not_exist")


def test_render_substitutes_variables() -> None:
    assert render_template("hello {{name}}", {"name": "world"}) == "hello world"


def test_render_supports_multiple_placeholders() -> None:
    result = render_template("{{a}}+{{b}}={{c}}", {"a": "1", "b": "2", "c": "3"})
    assert result == "1+2=3"


def test_render_raises_on_unknown_variable() -> None:
    with pytest.raises(TemplateError):
        render_template("hello {{name}}", {})


def test_render_passes_through_text_without_placeholders() -> None:
    assert render_template("plain text", {}) == "plain text"
