from pathlib import Path

import aiosqlite
import pytest

from app.db import Database
from app.db.migrations import MIGRATIONS


@pytest.mark.asyncio
async def test_initialize_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "app.db"
    database = Database(f"sqlite+aiosqlite:///{db_path}")
    await database.initialize()
    await database.initialize()
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("SELECT MAX(version) FROM schema_migrations")
        assert (await cursor.fetchone())[0] == max(MIGRATIONS)
        cursor = await db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='allowed_users'")
        assert await cursor.fetchone() is not None


@pytest.mark.asyncio
async def test_global_case_dedup_by_case_court_or_hash(tmp_path: Path) -> None:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'dedup.db'}")
    await db.initialize()
    assert await db.record_case(
        subject_slug="law_intro", case_number="123", court_name="المحكمة التجارية",
        source_name="وزارة العدل", source_url="https://www.moj.gov.sa/a.pdf",
        pdf_sha256="a" * 64, suitability_score=95,
    )
    assert await db.is_case_used(case_number="123", court_name="المحكمة التجارية", pdf_sha256=None)
    assert await db.is_case_used(case_number="999", court_name="أخرى", pdf_sha256="a" * 64)
    assert not await db.record_case(
        subject_slug="commercial_law", case_number="123", court_name="المحكمة التجارية",
        source_name="وزارة العدل", source_url="https://www.moj.gov.sa/b.pdf",
        pdf_sha256="b" * 64, suitability_score=90,
    )


@pytest.mark.asyncio
async def test_global_used_case_exclusions_cross_subjects(tmp_path: Path) -> None:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'global-exclusions.db'}")
    await db.initialize()
    assert await db.record_case(
        subject_slug="law_intro",
        case_number="111",
        court_name="المحكمة العامة",
        source_name="وزارة العدل",
        source_url="https://www.moj.gov.sa/111.pdf",
        pdf_sha256="1" * 64,
        suitability_score=92,
    )
    assert await db.record_case(
        subject_slug="administrative_law",
        case_number="222",
        court_name="المحكمة الإدارية",
        source_name="ديوان المظالم",
        source_url="https://www.bog.gov.sa/222.pdf",
        pdf_sha256="2" * 64,
        suitability_score=94,
    )

    rows = await db.used_cases_global()
    identities = {(row["case_number"], row["court_name"]) for row in rows}
    assert ("111", "المحكمة العامة") in identities
    assert ("222", "المحكمة الإدارية") in identities
