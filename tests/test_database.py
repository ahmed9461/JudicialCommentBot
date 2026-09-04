from pathlib import Path

import aiosqlite
import pytest

from app.db import Database


@pytest.mark.asyncio
async def test_initialize_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "app.db"
    database = Database(f"sqlite+aiosqlite:///{db_path}")

    await database.initialize()
    await database.initialize()

    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("SELECT MAX(version) FROM schema_migrations")
        assert (await cursor.fetchone())[0] == 1
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='allowed_users'"
        )
        assert await cursor.fetchone() is not None
