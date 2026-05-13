from __future__ import annotations


def format_duration(seconds: float) -> str:
    if seconds < 1.0:
        return f"{seconds:.1f}s"
    seconds_int = int(seconds)

    if seconds_int < 60:
        return f"{seconds_int}s"

    if seconds_int < 3600:
        minutes, remainder = divmod(seconds_int, 60)
        return f"{minutes}m{remainder:02d}s"

    hours, remainder = divmod(seconds_int, 3600)
    minutes = remainder // 60
    return f"{hours}h{minutes:02d}m"


def render_footer(
    *,
    model: str,
    duration_seconds: float,
    prompt_tokens: int,
    completion_tokens: int,
) -> str:
    total = prompt_tokens + completion_tokens
    duration = format_duration(duration_seconds)

    return (
        "---\n"
        f"_Reviewed by vidi-pr - model: {model} - "
        f"took {duration} - tokens: {prompt_tokens}+{completion_tokens}={total}_"
    )
