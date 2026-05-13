from vidi_pr.prompts.footer import format_duration, render_footer


def test_subsecond_one_decimal() -> None:
    assert format_duration(0.3) == "0.3s"


def test_under_minute_integer_seconds() -> None:
    assert format_duration(42.0) == "42s"
    assert format_duration(42.9) == "42s"


def test_minute_and_second_zero_padded() -> None:
    assert format_duration(83.0) == "1m23s"
    assert format_duration(307.0) == "5m07s"


def test_hour_and_minute_zero_padded() -> None:
    assert format_duration(3900.0) == "1h05m"
    assert format_duration(8220.0) == "2h17m"


def test_render_footer_under_minute() -> None:
    footer = render_footer(
        model="gpt",
        duration_seconds=42.0,
        prompt_tokens=100,
        completion_tokens=50,
    )

    assert footer == "---\n_Reviewed by vidi-pr - model: gpt - took 42s - tokens: 100+50=150_"


def test_render_footer_subsecond() -> None:
    footer = render_footer(
        model="local",
        duration_seconds=0.3,
        prompt_tokens=10,
        completion_tokens=5,
    )

    assert "took 0.3s" in footer
    assert "tokens: 10+5=15" in footer


def test_render_footer_over_hour() -> None:
    footer = render_footer(
        model="gpt",
        duration_seconds=3900.0,
        prompt_tokens=0,
        completion_tokens=0,
    )

    assert "took 1h05m" in footer
    assert "tokens: 0+0=0" in footer
