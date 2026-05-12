from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import CursorResult, event
from sqlalchemy.engine import Result
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from vidi_pr.errors import VidiPrError

if TYPE_CHECKING:
    from sqlite3 import Connection as Sqlite3Connection


class StorageError(VidiPrError):
    """Base class for storage-layer errors."""


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def make_database_url(path: Path | str) -> str:
    return f"sqlite+aiosqlite:///{path}"


def rowcount(result: Result[Any]) -> int:
    """Bridge `Session.execute()`'s declared `Result` to the runtime `CursorResult.rowcount`."""
    return cast(CursorResult[Any], result).rowcount


class Database:
    """
    Async SQLAlchemy engine + session factory for the SQLite store.

    WAL mode and foreign-key enforcement are applied on every new connection
    via a sync-side event listener; concurrency is bounded by
    `pipeline.max_concurrent_reviews=1` plus the webhook receiver, so a
    NullPool-style single-writer model is fine.
    """

    def __init__(
        self,
        engine: AsyncEngine,
        sessionmaker: async_sessionmaker[AsyncSession],
    ) -> None:
        self._engine = engine
        self._sessionmaker = sessionmaker

    @classmethod
    async def open(cls, path: Path | str) -> Database:
        engine = create_async_engine(make_database_url(path))
        _attach_sqlite_pragmas(engine)
        sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

        return cls(engine, sessionmaker)

    async def close(self) -> None:
        await self._engine.dispose()

    @property
    def engine(self) -> AsyncEngine:
        return self._engine

    @property
    def sessionmaker(self) -> async_sessionmaker[AsyncSession]:
        return self._sessionmaker


def _attach_sqlite_pragmas(engine: AsyncEngine) -> None:
    @event.listens_for(engine.sync_engine, "connect")
    def _set_pragmas(dbapi_connection: Sqlite3Connection, _record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
