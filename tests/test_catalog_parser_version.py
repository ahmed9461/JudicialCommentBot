from pathlib import Path

import pytest

from app.catalog import CatalogStore
from app.catalog.indexer import CATALOG_PARSER_VERSION
from app.db import Database


@pytest.mark.asyncio
async def test_only_one_catalog_generation_can_build_at_a_time(tmp_path: Path) -> None:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'catalog-lock.db'}")
    await db.initialize()
    store = CatalogStore(db)

    first = await store.begin_generation(CATALOG_PARSER_VERSION)
    with pytest.raises(RuntimeError, match="already building"):
        await store.begin_generation(CATALOG_PARSER_VERSION)

    await store.update_generation_result(
        first,
        status="failed",
        documents_seen=0,
        documents_indexed=0,
        documents_failed=0,
        cases_indexed=0,
        error="test cleanup",
    )
    second = await store.begin_generation(CATALOG_PARSER_VERSION)
    assert second != first
