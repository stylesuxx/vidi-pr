"""Operator config loaded from YAML on disk + env vars."""

from __future__ import annotations

import os
from ipaddress import IPv4Network, IPv6Network, ip_network
from pathlib import Path
from typing import Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
)
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from vidi_pr.config.defaults import (
    DEFAULT_ALLOWED_ASSOCIATIONS,
    DEFAULT_ENABLED,
    DEFAULT_INCLUDE_CONVERSATION,
    DEFAULT_STRICTNESS,
    Strictness,
)
from vidi_pr.errors import VidiPrError

DEFAULT_CONFIG_PATH = "/etc/vidi-pr/vidi-pr.yml"
CONFIG_PATH_ENV = "VIDI_PR_CONFIG"


class OperatorConfigError(VidiPrError):
    pass


class GitHubConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    app_id: int
    private_key_path: Path


class LLMConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["openai_compat"]
    base_url: str
    model: str
    temperature: float = 0.2
    timeout_seconds: int = Field(default=600, ge=1)
    max_tokens: int = Field(default=4096, ge=1)


class ServerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str = "127.0.0.1"
    port: int = Field(default=8080, ge=1, le=65535)
    forwarded_allow_ips: list[IPv4Network | IPv6Network] = []

    @field_validator("forwarded_allow_ips", mode="before")
    @classmethod
    def _parse_networks(cls, raw: object) -> object:
        if not isinstance(raw, list):
            return raw
        parsed: list[IPv4Network | IPv6Network] = []
        for item in raw:
            if isinstance(item, IPv4Network | IPv6Network):
                parsed.append(item)
            elif isinstance(item, str):
                parsed.append(ip_network(item, strict=False))
            else:
                msg = f"forwarded_allow_ips entries must be CIDR strings, got {item!r}"
                raise ValueError(msg)

        return parsed


class StorageConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    db_path: Path


class LoggingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    format: Literal["json", "console"] = "json"


class PipelineConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_files: int = Field(default=50, ge=1)
    max_chunks: int = Field(default=5, ge=1)
    max_chunk_chars: int = Field(default=80_000, ge=1)
    max_conversation_chars: int = Field(default=15_000, ge=0)
    max_concurrent_reviews: int = Field(default=1, ge=1)
    job_timeout_seconds: int = Field(default=900, ge=1)
    failure_comment_cooldown_seconds: int = Field(default=3600, ge=0)


class DefaultsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = DEFAULT_ENABLED
    allowed_associations: list[str] = list(DEFAULT_ALLOWED_ASSOCIATIONS)
    strictness: Strictness = DEFAULT_STRICTNESS
    include_conversation: bool = DEFAULT_INCLUDE_CONVERSATION


class OperatorConfig(BaseSettings):
    """
    The on-host operator configuration.

    Non-secret fields come from the YAML file at `$VIDI_PR_CONFIG`
    (default `/etc/vidi-pr/vidi-pr.yml`). Secrets come from env vars
    (`VIDI_PR_WEBHOOK_SECRET`, `VIDI_PR_LLM_API_KEY`) and never appear
    in the YAML. Nested YAML fields can also be overridden by env vars
    using the `VIDI_PR_<SECTION>__<FIELD>` form (double underscore is
    the section delimiter).
    """

    model_config = SettingsConfigDict(
        env_prefix="VIDI_PR_",
        env_nested_delimiter="__",
        extra="forbid",
        case_sensitive=False,
    )

    github: GitHubConfig
    llm: LLMConfig
    server: ServerConfig = Field(default_factory=ServerConfig)
    storage: StorageConfig
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)
    defaults: DefaultsConfig = Field(default_factory=DefaultsConfig)

    webhook_secret: SecretStr
    llm_api_key: SecretStr | None = None

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (env_settings, init_settings, file_secret_settings)

    @classmethod
    def load(cls, yaml_path: Path | str | None = None) -> OperatorConfig:
        path = Path(os.environ.get(CONFIG_PATH_ENV, DEFAULT_CONFIG_PATH))
        if yaml_path is not None:
            path = Path(yaml_path)

        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            msg = f"operator config not readable at {path}: {exc}"
            raise OperatorConfigError(msg) from exc

        try:
            data = yaml.safe_load(text) or {}
        except yaml.YAMLError as exc:
            msg = f"operator config at {path} is not valid YAML: {exc}"
            raise OperatorConfigError(msg) from exc

        if not isinstance(data, dict):
            msg = f"operator config at {path} must be a YAML mapping, not {type(data).__name__}"
            raise OperatorConfigError(msg)

        return cls(**data)
