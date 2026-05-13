from vidi_pr.pipeline.parsing import parse_review_output


def test_well_formed_output_parses_all_four_sections() -> None:
    text = (
        "## Summary\n\nOne line overview.\n\n"
        "## Findings\n\n- A real bug\n\n"
        "## Suggestions\n\n- A small nit\n\n"
        "## Positives\n\n- Nice tests"
    )

    parsed = parse_review_output(text)

    assert parsed.parse_failed is False
    assert parsed.summary == "One line overview."
    assert "real bug" in parsed.findings
    assert "small nit" in parsed.suggestions
    assert "Nice tests" in parsed.positives


def test_missing_sections_are_empty_strings() -> None:
    text = "## Summary\n\nJust a summary."
    parsed = parse_review_output(text)

    assert parsed.parse_failed is False
    assert parsed.summary == "Just a summary."
    assert parsed.findings == ""
    assert parsed.suggestions == ""
    assert parsed.positives == ""


def test_unrecognized_output_is_marked_parse_failed_with_raw_preserved() -> None:
    text = "Sorry, here is a free-form review with no headings."
    parsed = parse_review_output(text)

    assert parsed.parse_failed is True
    assert parsed.raw == text
    assert parsed.summary == ""


def test_sections_in_unexpected_order_still_parse() -> None:
    text = (
        "## Positives\n\nGood test coverage.\n\n"
        "## Summary\n\nLooks fine.\n\n"
        "## Findings\n\n(none)\n\n"
        "## Suggestions\n\n- minor"
    )

    parsed = parse_review_output(text)

    assert parsed.parse_failed is False
    assert parsed.summary == "Looks fine."
    assert parsed.positives == "Good test coverage."


def test_extra_text_around_headings_is_preserved_in_section() -> None:
    text = "## Findings\n\nA finding.\n\nMore detail."
    parsed = parse_review_output(text)

    assert "A finding." in parsed.findings
    assert "More detail." in parsed.findings
