from pathlib import Path

import pytest

from app.catalog import CatalogStore
from app.db import Database


@pytest.mark.asyncio
async def test_document_parser_version_controls_reindex(tmp_path: Path) -> None:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'catalog-version.db'}")
    await db.initialize()
    store = CatalogStore(db)
    url = "https://www.moj.gov.sa/collection.pdf"

    await store.record_document(
        source_url=url,
        collection_id="fixture",
        source_id="ministry_of_justice",
        pdf_sha256="a" * 64,
        case_count=10,
        parser_version=1,
    )
    assert await store.is_document_indexed(url)
    assert await store.is_document_indexed(url, parser_version=1)
    assert not await store.is_document_indexed(url, parser_version=2)

    await store.record_document(
        source_url=url,
        collection_id="fixture",
        source_id="ministry_of_justice",
        pdf_sha256="a" * 64,
        case_count=10,
        parser_version=2,
    )
    assert await store.is_document_indexed(url, parser_version=2)
