import vidi_pr


def test_version_is_non_empty_string() -> None:
    assert isinstance(vidi_pr.__version__, str)
    assert vidi_pr.__version__ != ""
