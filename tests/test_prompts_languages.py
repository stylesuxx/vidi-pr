from vidi_pr.models.review import ChangedFile, FileStatus, Language
from vidi_pr.prompts.languages import detect_languages, load_language_note


def _file(name: str) -> ChangedFile:
    return ChangedFile(
        filename=name,
        status=FileStatus.MODIFIED,
        additions=1,
        deletions=0,
        patch="",
    )


def test_py_maps_to_python() -> None:
    assert detect_languages([_file("foo.py")]) == {Language.PYTHON}


def test_tsx_maps_to_typescript() -> None:
    assert detect_languages([_file("ui/Card.tsx")]) == {Language.TYPESCRIPT}


def test_drupal_module_returns_both_drupal_and_php() -> None:
    assert detect_languages([_file("mymod.module")]) == {Language.DRUPAL, Language.PHP}


def test_unknown_extension_yields_generic() -> None:
    assert detect_languages([_file("README.notalang")]) == {Language.GENERIC}


def test_no_extension_yields_generic() -> None:
    assert detect_languages([_file("Makefile")]) == {Language.GENERIC}


def test_multiple_files_union() -> None:
    assert detect_languages([_file("a.py"), _file("b.ts")]) == {
        Language.PYTHON,
        Language.TYPESCRIPT,
    }


def test_load_language_note_returns_content() -> None:
    note = load_language_note(Language.PYTHON)

    assert note != ""
    assert "type" in note.lower()


def test_every_language_has_a_built_in_note() -> None:
    for language in Language:
        assert load_language_note(language) != ""
