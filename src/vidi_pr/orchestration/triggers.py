from __future__ import annotations

import re
from dataclasses import dataclass

# Match `@vidi-pr review` only at column 0 of a line (so quoted `> @vidi-pr review`
# and mid-line mentions like `Hello @vidi-pr review` do not match). The capture
# group holds any trailing text on the same line, used as `extra_context`.
_TRIGGER = re.compile(
    r"^@vidi-pr\s+review\b\s*(.*?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


@dataclass(frozen=True)
class ParsedTrigger:
    extra_context: str | None


def parse_trigger(body: str | None) -> ParsedTrigger | None:
    if not body:
        return None

    match = _TRIGGER.search(body)
    if match is None:
        return None

    extra = (match.group(1) or "").strip()
    return ParsedTrigger(extra_context=extra or None)
