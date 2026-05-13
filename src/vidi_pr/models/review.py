from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class Language(StrEnum):
    PYTHON = "python"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    PHP = "php"
    DRUPAL = "drupal"
    KOTLIN = "kotlin"
    C = "c"
    CPP = "cpp"
    BASH = "bash"
    YAML = "yaml"
    SQL = "sql"
    GENERIC = "generic"


class FileStatus(StrEnum):
    ADDED = "added"
    MODIFIED = "modified"
    REMOVED = "removed"
    RENAMED = "renamed"


class ChangedFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str
    status: FileStatus
    additions: int
    deletions: int
    patch: str | None


class PRInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    number: int
    title: str
    body: str | None
    head_sha: str
    base_ref: str
    author_login: str
    draft: bool


class ConversationComment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    author_login: str
    is_bot: bool
    body: str
    created_at: datetime


class Chunk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int
    total: int
    files: list[ChangedFile]


class ParsedReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str
    findings: str
    suggestions: str
    positives: str
    raw: str
    parse_failed: bool = False


class RepoInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str
    default_branch: str
    private: bool
