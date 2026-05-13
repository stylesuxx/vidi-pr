from __future__ import annotations

from importlib import resources
from typing import TYPE_CHECKING

from vidi_pr.config.defaults import Strictness
from vidi_pr.prompts.loader import TemplateError

if TYPE_CHECKING:
    from importlib.resources.abc import Traversable

_PACKAGE = "vidi_pr.prompts.strictness"


def load_strictness_block(level: Strictness) -> str:
    package: Traversable = resources.files(_PACKAGE)
    entry = package / f"{level.value}.md"
    if not entry.is_file():
        raise TemplateError(f"strictness block not found: {level.value}.md")

    return entry.read_text(encoding="utf-8").strip()
