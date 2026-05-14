from __future__ import annotations

from typing import Any

import httpx
import pytest
from pytest_httpx import HTTPXMock

from vidi_pr.llm.client import OpenAICompatClient
from vidi_pr.llm.errors import LLMPermanentError, LLMTransientError
from vidi_pr.llm.types import Message, Role

_BASE_URL = "http://llm.test/v1"
_ENDPOINT = f"{_BASE_URL}/chat/completions"
_MODEL = "qwen2.5-coder-32b"


def _success_body(content: str = "hello back", model: str = _MODEL) -> dict[str, Any]:
    return {
        "id": "chatcmpl-1",
        "model": model,
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
    }


def _client(*, api_key: str | None = None, max_attempts: int = 3) -> OpenAICompatClient:
    return OpenAICompatClient(
        base_url=_BASE_URL,
        model=_MODEL,
        api_key=api_key,
        max_attempts=max_attempts,
        retry_initial_delay=0.0,
    )


async def test_successful_chat_round_trip(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=_ENDPOINT, json=_success_body())

    async with _client() as client:
        response = await client.chat([Message(role=Role.USER, content="hi")])

    assert response.content == "hello back"
    assert response.model == _MODEL
    assert response.usage.total_tokens == 7


async def test_request_body_shape(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=_ENDPOINT, json=_success_body())

    async with _client() as client:
        await client.chat(
            [Message(role=Role.SYSTEM, content="you are a reviewer")],
            temperature=0.2,
            max_tokens=512,
        )

    request = httpx_mock.get_request()
    assert request is not None
    body = httpx.Response(200, content=request.content).json()
    assert body == {
        "model": _MODEL,
        "messages": [{"role": "system", "content": "you are a reviewer"}],
        "temperature": 0.2,
        "max_tokens": 512,
    }


async def test_optional_fields_are_omitted_when_unset(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=_ENDPOINT, json=_success_body())

    async with _client() as client:
        await client.chat([Message(role=Role.USER, content="hi")])

    request = httpx_mock.get_request()
    assert request is not None
    body = httpx.Response(200, content=request.content).json()
    assert "temperature" not in body
    assert "max_tokens" not in body
    assert "response_format" not in body


async def test_extra_body_is_merged_into_request_payload(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=_ENDPOINT, json=_success_body())

    client = OpenAICompatClient(
        base_url=_BASE_URL,
        model=_MODEL,
        retry_initial_delay=0.0,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}, "top_p": 0.9},
    )
    async with client:
        await client.chat([Message(role=Role.USER, content="hi")])

    request = httpx_mock.get_request()
    assert request is not None
    body = httpx.Response(200, content=request.content).json()
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert body["top_p"] == 0.9


async def test_typed_fields_override_extra_body_on_conflict(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=_ENDPOINT, json=_success_body())

    client = OpenAICompatClient(
        base_url=_BASE_URL,
        model=_MODEL,
        retry_initial_delay=0.0,
        extra_body={"temperature": 1.5},
    )
    async with client:
        await client.chat([Message(role=Role.USER, content="hi")], temperature=0.1)

    request = httpx_mock.get_request()
    assert request is not None
    body = httpx.Response(200, content=request.content).json()
    assert body["temperature"] == 0.1


async def test_reasoning_content_and_finish_reason_are_parsed(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=_ENDPOINT,
        json={
            "model": _MODEL,
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "final answer",
                        "reasoning_content": "step-by-step thinking",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12},
        },
    )

    async with _client() as client:
        response = await client.chat([Message(role=Role.USER, content="hi")])

    assert response.content == "final answer"
    assert response.reasoning_content == "step-by-step thinking"
    assert response.finish_reason == "stop"


async def test_response_without_reasoning_fields_has_safe_defaults(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=_ENDPOINT, json=_success_body())

    async with _client() as client:
        response = await client.chat([Message(role=Role.USER, content="hi")])

    assert response.reasoning_content == ""
    assert response.finish_reason is None


async def test_response_format_passes_through(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=_ENDPOINT, json=_success_body())

    async with _client() as client:
        await client.chat(
            [Message(role=Role.USER, content="hi")],
            response_format={"type": "json_object"},
        )

    request = httpx_mock.get_request()
    assert request is not None
    body = httpx.Response(200, content=request.content).json()
    assert body["response_format"] == {"type": "json_object"}


async def test_authorization_header_sent_when_api_key_set(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=_ENDPOINT, json=_success_body())

    async with _client(api_key="sk-secret") as client:
        await client.chat([Message(role=Role.USER, content="hi")])

    request = httpx_mock.get_request()
    assert request is not None
    assert request.headers["Authorization"] == "Bearer sk-secret"


async def test_authorization_header_omitted_when_no_api_key(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=_ENDPOINT, json=_success_body())

    async with _client(api_key=None) as client:
        await client.chat([Message(role=Role.USER, content="hi")])

    request = httpx_mock.get_request()
    assert request is not None
    assert "Authorization" not in request.headers


async def test_retries_on_503_then_succeeds(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=_ENDPOINT, status_code=503, text="busy")
    httpx_mock.add_response(url=_ENDPOINT, status_code=503, text="busy")
    httpx_mock.add_response(url=_ENDPOINT, json=_success_body("after retries"))

    async with _client() as client:
        response = await client.chat([Message(role=Role.USER, content="hi")])

    assert response.content == "after retries"
    assert len(httpx_mock.get_requests()) == 3


async def test_gives_up_after_max_attempts(httpx_mock: HTTPXMock) -> None:
    for _ in range(3):
        httpx_mock.add_response(url=_ENDPOINT, status_code=503, text="busy")

    async with _client(max_attempts=3) as client:
        with pytest.raises(LLMTransientError):
            await client.chat([Message(role=Role.USER, content="hi")])

    assert len(httpx_mock.get_requests()) == 3


async def test_does_not_retry_on_4xx(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=_ENDPOINT, status_code=400, text="bad request")

    async with _client() as client:
        with pytest.raises(LLMPermanentError):
            await client.chat([Message(role=Role.USER, content="hi")])

    assert len(httpx_mock.get_requests()) == 1


async def test_timeout_is_mapped_to_transient_and_retried(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_exception(httpx.ReadTimeout("timeout"), url=_ENDPOINT)
    httpx_mock.add_response(url=_ENDPOINT, json=_success_body("recovered"))

    async with _client() as client:
        response = await client.chat([Message(role=Role.USER, content="hi")])

    assert response.content == "recovered"
    assert len(httpx_mock.get_requests()) == 2


async def test_connection_error_is_mapped_to_transient(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_exception(httpx.ConnectError("nope"), url=_ENDPOINT)
    httpx_mock.add_response(url=_ENDPOINT, json=_success_body("recovered"))

    async with _client() as client:
        response = await client.chat([Message(role=Role.USER, content="hi")])

    assert response.content == "recovered"


async def test_aclose_shuts_underlying_client() -> None:
    client = _client()
    await client.aclose()
