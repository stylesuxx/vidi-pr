from __future__ import annotations

import re
from importlib import resources
from typing import TYPE_CHECKING

from vidi_pr.errors import VidiPrError

if TYPE_CHECKING:
    from importlib.resources.abc import Traversable

_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")
_TEMPLATES_PACKAGE = "vidi_pr.prompts"


class TemplateError(VidiPrError):
    pass


def load_template(name: str) -> str:
    filename = name if name.endswith(".md") else f"{name}.md"
    package: Traversable = resources.files(_TEMPLATES_PACKAGE)
    entry = package / filename
    if not entry.is_file():
        raise TemplateError(f"prompt template not found: {filename}")

    return entry.read_text(encoding="utf-8")


def render_template(template: str, variables: dict[str, str]) -> str:
    def _replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in variables:
            raise TemplateError(f"unknown template variable: {name}")

        return variables[name]

    return _PLACEHOLDER.sub(_replace, template)
