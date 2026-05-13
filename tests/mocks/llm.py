"""Scripted `LLMClient` for use in tests of layers that consume the LLM."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from vidi_pr.llm.errors import LLMError
from vidi_pr.llm.types import ChatResponse, Message


@dataclass(frozen=True)
class MockCall:
    messages: list[Message]
    temperature: float | None
    max_tokens: int | None
    response_format: dict[str, Any] | None


class MockLLMClient:
    """
    Returns scripted `ChatResponse`s in order; records every call.

    Raises `LLMError` if asked to chat more times than there are scripted
    responses, so tests fail loudly instead of looping or returning stale data.
    """

    def __init__(self, responses: Sequence[ChatResponse]) -> None:
        self._responses: list[ChatResponse] = list(responses)
        self._cursor = 0
        self.calls: list[MockCall] = []

    async def chat(
        self,
        messages: Sequence[Message],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> ChatResponse:
        self.calls.append(
            MockCall(
                messages=list(messages),
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=response_format,
            )
        )
        if self._cursor >= len(self._responses):
            msg = f"MockLLMClient exhausted after {len(self._responses)} scripted response(s)"
            raise LLMError(msg)

        response = self._responses[self._cursor]
        self._cursor += 1

        return response
