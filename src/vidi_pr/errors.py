"""Exception hierarchy for vidi-pr.

Each layer defines its own typed subclass of `VidiPrError` so that callers
can distinguish failure modes from generic exceptions. Only the worker and
the webhook handler may catch `Exception` broadly.
"""


class VidiPrError(Exception):
    """Base class for all errors raised by vidi-pr."""
