"""OpenAI-compatible chat client behind a `Protocol`, with tenacity-driven retries."""

from __future__ import annotations

from collections.abc import Sequence
from types import TracebackType
from typing import Any, Protocol, Self

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from vidi_pr.llm.errors import LLMError, LLMPermanentError, LLMTransientError
from vidi_pr.llm.types import ChatRequest, ChatResponse, Message, TokenUsage


class LLMClient(Protocol):
    async def chat(
        self,
        messages: Sequence[Message],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> ChatResponse: ...

    async def list_models(self) -> list[str]: ...


class OpenAICompatClient:
    """
    Async chat client for any OpenAI-compatible `/chat/completions` endpoint.

    Owns an `httpx.AsyncClient` for the lifetime of the instance. Retries
    transient failures (5xx, timeout, connection error) with exponential
    backoff + jitter; surfaces 4xx as `LLMPermanentError` without retry.
    """

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout: float = 600.0,
        max_attempts: int = 3,
        retry_initial_delay: float = 1.0,
        extra_body: dict[str, Any] | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._max_attempts = max_attempts
        self._retry_initial_delay = retry_initial_delay
        self._extra_body: dict[str, Any] = dict(extra_body) if extra_body else {}

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if api_key is not None:
            headers["Authorization"] = f"Bearer {api_key}"

        self._client = httpx.AsyncClient(timeout=timeout, headers=headers)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def chat(
        self,
        messages: Sequence[Message],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> ChatResponse:
        request = ChatRequest(
            model=self._model,
            messages=list(messages),
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )

        retrying = AsyncRetrying(
            stop=stop_after_attempt(self._max_attempts),
            wait=wait_exponential_jitter(initial=self._retry_initial_delay),
            retry=retry_if_exception_type(LLMTransientError),
            reraise=True,
        )
        async for attempt in retrying:
            with attempt:
                return await self._execute(request)

        raise LLMError("tenacity retry loop exited without result")

    async def list_models(self) -> list[str]:
        url = f"{self._base_url}/models"
        try:
            response = await self._client.get(url, timeout=10.0)
        except httpx.TimeoutException as exc:
            raise LLMTransientError(f"LLM /models request timed out: {exc}") from exc
        except httpx.RequestError as exc:
            raise LLMTransientError(f"LLM /models request failed: {exc}") from exc

        if 500 <= response.status_code < 600:
            raise LLMTransientError(f"LLM /models returned {response.status_code}: {response.text}")

        if 400 <= response.status_code < 500:
            raise LLMPermanentError(f"LLM /models returned {response.status_code}: {response.text}")

        try:
            payload = response.json()
        except ValueError as exc:
            raise LLMError(f"LLM /models response was not valid JSON: {exc}") from exc

        data = payload.get("data") or []
        return [str(entry["id"]) for entry in data if isinstance(entry, dict) and "id" in entry]

    async def _execute(self, request: ChatRequest) -> ChatResponse:
        url = f"{self._base_url}/chat/completions"
        payload: dict[str, Any] = dict(self._extra_body)
        payload.update(request.to_json_payload())
        try:
            response = await self._client.post(url, json=payload)
        except httpx.TimeoutException as exc:
            raise LLMTransientError(f"LLM request timed out: {exc}") from exc
        except httpx.RequestError as exc:
            raise LLMTransientError(f"LLM request failed: {exc}") from exc

        if 500 <= response.status_code < 600:
            raise LLMTransientError(
                f"LLM endpoint returned {response.status_code}: {response.text}"
            )

        if 400 <= response.status_code < 500:
            raise LLMPermanentError(
                f"LLM endpoint returned {response.status_code}: {response.text}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise LLMError(f"LLM response was not valid JSON: {exc}") from exc

        return _parse_response(payload)


def _parse_response(payload: dict[str, Any]) -> ChatResponse:
    choices = payload.get("choices") or []
    if not choices:
        raise LLMError("LLM response contained no choices")

    choice = choices[0]
    message = choice.get("message") or {}
    content = message.get("content")
    if content is None:
        raise LLMError("LLM response had no message content")

    reasoning = message.get("reasoning_content") or ""
    finish_reason = choice.get("finish_reason")
    usage_payload = payload.get("usage") or {}
    return ChatResponse(
        content=str(content),
        model=str(payload.get("model", "")),
        usage=TokenUsage.model_validate(usage_payload),
        reasoning_content=str(reasoning),
        finish_reason=str(finish_reason) if finish_reason is not None else None,
    )
