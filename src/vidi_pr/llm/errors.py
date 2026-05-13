"""Exception hierarchy for the LLM layer."""

from vidi_pr.errors import VidiPrError


class LLMError(VidiPrError):
    """Base class for LLM-layer errors."""


class LLMTransientError(LLMError):
    """Errors that may succeed on retry: HTTP 5xx, timeout, connection error."""


class LLMPermanentError(LLMError):
    """Errors that will never succeed without changing the request: HTTP 4xx."""
