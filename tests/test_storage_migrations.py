import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from vidi_pr.storage.db import Database, make_database_url

_ALEMBIC_SCRIPT_LOCATION = "src/vidi_pr/storage/alembic"


def _alembic_config(db_path: Path) -> Config:
    config = Config()
    config.set_main_option("script_location", _ALEMBIC_SCRIPT_LOCATION)
    config.set_main_option("sqlalchemy.url", make_database_url(db_path))
    return config


async def _table_names(database: Database) -> set[str]:
    async with database.engine.connect() as conn:
        return set(await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names()))


async def _index_names(database: Database, table: str) -> set[str]:
    async with database.engine.connect() as conn:

        def _gather(sync_conn: object) -> set[str]:
            inspector = inspect(sync_conn)
            return {idx["name"] for idx in inspector.get_indexes(table) if idx["name"]}

        return await conn.run_sync(_gather)


async def test_upgrade_creates_business_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    await asyncio.to_thread(command.upgrade, _alembic_config(db_path), "head")
    database = await Database.open(db_path)
    try:
        tables = await _table_names(database)
        expected = {
            "alembic_version",
            "webhook_deliveries",
            "jobs",
            "pr_locks",
            "reviews_posted",
        }
        assert expected <= tables
        indexes = await _index_names(database, "jobs")
        assert "jobs_status_created_at_idx" in indexes
    finally:
        await database.close()


async def test_upgrade_is_idempotent(tmp_path: Path) -> None:
    config = _alembic_config(tmp_path / "test.db")
    await asyncio.to_thread(command.upgrade, config, "head")
    await asyncio.to_thread(command.upgrade, config, "head")


async def test_downgrade_drops_business_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    config = _alembic_config(db_path)
    await asyncio.to_thread(command.upgrade, config, "head")
    await asyncio.to_thread(command.downgrade, config, "base")
    database = await Database.open(db_path)
    try:
        tables = await _table_names(database)
        assert "jobs" not in tables
        assert "pr_locks" not in tables
        assert "reviews_posted" not in tables
        assert "webhook_deliveries" not in tables
    finally:
        await database.close()
