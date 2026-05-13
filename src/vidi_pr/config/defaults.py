"""
Baked-in absolute fallback values for the per-repo config.

These are used when a repo's `.github/vidi-pr.yml` is absent on every
trusted ref. The operator config's `defaults` block overrides them per
deployment; an actual per-repo config overrides both.
"""

from enum import StrEnum


class Strictness(StrEnum):
    LENIENT = "lenient"
    NORMAL = "normal"
    STRICT = "strict"


DEFAULT_ENABLED = True
DEFAULT_ALLOWED_ASSOCIATIONS: tuple[str, ...] = ("OWNER", "COLLABORATOR")
DEFAULT_STRICTNESS = Strictness.NORMAL
DEFAULT_INCLUDE_CONVERSATION = True

ABSENT_CONFIG_ALLOWED_ASSOCIATIONS: tuple[str, ...] = ("OWNER",)
