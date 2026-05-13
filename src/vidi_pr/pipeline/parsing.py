from __future__ import annotations

import re

from vidi_pr.models.review import ParsedReview

_HEADING = re.compile(r"^##\s+(Summary|Findings|Suggestions|Positives)\s*$", re.MULTILINE)


def parse_review_output(text: str) -> ParsedReview:
    """
    Split a review reply into the four canonical sections.

    The reply is expected to use `## Summary`, `## Findings`, `## Suggestions`,
    `## Positives` headings (in any order). Missing or duplicate sections are
    tolerated. If none of the four headings is present, the result has
    `parse_failed=True` and the raw text is preserved verbatim so the caller
    can post it as a fallback.
    """
    sections: dict[str, str] = {"Summary": "", "Findings": "", "Suggestions": "", "Positives": ""}
    matches = list(_HEADING.finditer(text))
    if not matches:
        return ParsedReview(
            summary="",
            findings="",
            suggestions="",
            positives="",
            raw=text,
            parse_failed=True,
        )

    for i, match in enumerate(matches):
        name = match.group(1)
        body_start = match.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections[name] = text[body_start:body_end].strip()

    return ParsedReview(
        summary=sections["Summary"],
        findings=sections["Findings"],
        suggestions=sections["Suggestions"],
        positives=sections["Positives"],
        raw=text,
        parse_failed=False,
    )
