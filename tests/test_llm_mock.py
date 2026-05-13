from __future__ import annotations

import pytest
from mocks.llm import MockLLMClient

from vidi_pr.llm.errors import LLMError
from vidi_pr.llm.types import ChatResponse, Message, Role, TokenUsage


def _response(content: str) -> ChatResponse:
    return ChatResponse(content=content, model="mock", usage=TokenUsage())


async def test_returns_scripted_responses_in_order() -> None:
    client = MockLLMClient([_response("first"), _response("second")])

    assert (await client.chat([Message(role=Role.USER, content="a")])).content == "first"
    assert (await client.chat([Message(role=Role.USER, content="b")])).content == "second"


async def test_records_calls_with_keyword_args() -> None:
    client = MockLLMClient([_response("ok")])

    await client.chat(
        [Message(role=Role.USER, content="hi")],
        temperature=0.5,
        max_tokens=128,
        response_format={"type": "json_object"},
    )

    assert len(client.calls) == 1
    call = client.calls[0]
    assert call.temperature == 0.5
    assert call.max_tokens == 128
    assert call.response_format == {"type": "json_object"}


async def test_raises_when_exhausted() -> None:
    client = MockLLMClient([_response("only")])
    await client.chat([Message(role=Role.USER, content="a")])

    with pytest.raises(LLMError):
        await client.chat([Message(role=Role.USER, content="b")])
