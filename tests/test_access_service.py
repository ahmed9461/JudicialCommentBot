from pathlib import Path

import pytest

from app.db import Database
from app.services import AccessService


@pytest.mark.asyncio
async def test_owner_and_allowlist_roundtrip(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    database = Database(f"sqlite+aiosqlite:///{db_path}")
    await database.initialize()

    service = AccessService(owner_id=100, database=database)

    assert await service.is_allowed(100) is True
    assert await service.is_allowed(200) is False

    assert await service.add_user(100, 200) is True
    assert await service.add_user(100, 200) is False
    assert await service.is_allowed(200) is True
    assert await service.list_users(100) == [200]

    assert await service.remove_user(100, 200) is True
    assert await service.is_allowed(200) is False


@pytest.mark.asyncio
async def test_non_owner_cannot_manage_allowlist(tmp_path: Path) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    await database.initialize()
    service = AccessService(owner_id=100, database=database)

    with pytest.raises(PermissionError):
        await service.add_user(999, 200)

    with pytest.raises(PermissionError):
        await service.list_users(999)


@pytest.mark.asyncio
async def test_owner_cannot_be_removed(tmp_path: Path) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    await database.initialize()
    service = AccessService(owner_id=100, database=database)

    with pytest.raises(ValueError, match="Owner"):
        await service.remove_user(100, 100)
