from __future__ import annotations

from collections.abc import Iterable
from importlib import resources
from typing import TYPE_CHECKING

from vidi_pr.models.review import ChangedFile, Language

if TYPE_CHECKING:
    from importlib.resources.abc import Traversable

_PACKAGE = "vidi_pr.prompts.languages"

_DRUPAL_PHP: frozenset[Language] = frozenset({Language.DRUPAL, Language.PHP})

EXTENSION_TO_LANGUAGES: dict[str, frozenset[Language]] = {
    ".py": frozenset({Language.PYTHON}),
    ".pyi": frozenset({Language.PYTHON}),
    ".js": frozenset({Language.JAVASCRIPT}),
    ".mjs": frozenset({Language.JAVASCRIPT}),
    ".cjs": frozenset({Language.JAVASCRIPT}),
    ".jsx": frozenset({Language.JAVASCRIPT}),
    ".ts": frozenset({Language.TYPESCRIPT}),
    ".tsx": frozenset({Language.TYPESCRIPT}),
    ".php": frozenset({Language.PHP}),
    ".module": _DRUPAL_PHP,
    ".install": _DRUPAL_PHP,
    ".inc": _DRUPAL_PHP,
    ".theme": _DRUPAL_PHP,
    ".profile": _DRUPAL_PHP,
    ".kt": frozenset({Language.KOTLIN}),
    ".kts": frozenset({Language.KOTLIN}),
    ".c": frozenset({Language.C}),
    ".h": frozenset({Language.C}),
    ".cpp": frozenset({Language.CPP}),
    ".cc": frozenset({Language.CPP}),
    ".cxx": frozenset({Language.CPP}),
    ".hpp": frozenset({Language.CPP}),
    ".hxx": frozenset({Language.CPP}),
    ".sh": frozenset({Language.BASH}),
    ".bash": frozenset({Language.BASH}),
    ".yml": frozenset({Language.YAML}),
    ".yaml": frozenset({Language.YAML}),
    ".sql": frozenset({Language.SQL}),
}


def detect_languages(files: Iterable[ChangedFile]) -> set[Language]:
    languages: set[Language] = set()
    for file in files:
        head, sep, tail = file.filename.rpartition(".")
        key = f".{tail.lower()}" if sep and head else ""
        matched = EXTENSION_TO_LANGUAGES.get(key)
        if matched:
            languages |= matched
        else:
            languages.add(Language.GENERIC)

    return languages


def load_language_note(language: Language) -> str:
    package: Traversable = resources.files(_PACKAGE)
    entry = package / f"{language.value}.md"
    if not entry.is_file():
        return ""

    return entry.read_text(encoding="utf-8").strip()
