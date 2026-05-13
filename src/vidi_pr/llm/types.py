"""Pydantic models for the OpenAI-compatible chat completions protocol."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Role
    content: str


class TokenUsage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str
    messages: list[Message]
    temperature: float | None = None
    max_tokens: int | None = None
    response_format: dict[str, Any] | None = None

    def to_json_payload(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True)


class ChatResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    content: str
    model: str
    usage: TokenUsage = Field(default_factory=TokenUsage)
