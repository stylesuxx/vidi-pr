from vidi_pr.orchestration.triggers import parse_trigger


def test_bare_trigger_matches_with_no_extra_context() -> None:
    result = parse_trigger("@vidi-pr review")

    assert result is not None
    assert result.extra_context is None


def test_trigger_with_trailing_text_captures_extra_context() -> None:
    result = parse_trigger("@vidi-pr review please focus on the migration logic")

    assert result is not None
    assert result.extra_context == "please focus on the migration logic"


def test_trigger_is_case_insensitive() -> None:
    assert parse_trigger("@vidi-pr Review") is not None
    assert parse_trigger("@VIDI-PR REVIEW") is not None


def test_mid_line_mention_does_not_trigger() -> None:
    assert parse_trigger("Hey there, @vidi-pr review pls") is None


def test_quoted_trigger_does_not_match() -> None:
    body = "> @vidi-pr review please"
    assert parse_trigger(body) is None


def test_quoted_trigger_in_multiline_body_does_not_match() -> None:
    body = "Some comment about a previous bot post:\n\n> @vidi-pr review focus on x\n\nLooks good."
    assert parse_trigger(body) is None


def test_trigger_on_second_line_matches() -> None:
    body = "Hi team,\n@vidi-pr review focus on security"
    result = parse_trigger(body)

    assert result is not None
    assert result.extra_context == "focus on security"


def test_word_boundary_rejects_reviewer() -> None:
    assert parse_trigger("@vidi-pr reviewer please look") is None


def test_empty_body_returns_none() -> None:
    assert parse_trigger("") is None
    assert parse_trigger(None) is None


def test_trailing_whitespace_is_stripped_from_extra_context() -> None:
    result = parse_trigger("@vidi-pr review    extra stuff   ")

    assert result is not None
    assert result.extra_context == "extra stuff"
