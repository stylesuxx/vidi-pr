from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy.ext.asyncio import AsyncSession

from vidi_pr.models.storage import Base
from vidi_pr.storage.db import Database


@pytest_asyncio.fixture
async def database(tmp_path: Path) -> AsyncIterator[Database]:
    db = await Database.open(tmp_path / "test.db")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield db
    finally:
        await db.aclose()


@pytest_asyncio.fixture
async def session(database: Database) -> AsyncIterator[AsyncSession]:
    async with database.sessionmaker() as session:
        yield session


@pytest.fixture(scope="session")
def app_private_key() -> str:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
