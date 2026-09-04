"""Persistence and deterministic retrieval for the official judicial catalog."""

from __future__ import annotations

from collections.abc import Iterable

import aiosqlite

from app.db import Database

from .models import CatalogCase, CatalogStats
from .text import normalize_arabic

_CASE_UPSERT_SQL = """
INSERT INTO official_case_catalog(
    catalog_key, collection_id, source_id, source_name, source_url,
    pdf_url, pdf_sha256, page_start, page_end, title, case_number,
    court_name, judgment_year, extracted_text, normalized_text, indexed_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
ON CONFLICT(catalog_key) DO UPDATE SET
    collection_id=excluded.collection_id,
    source_id=excluded.source_id,
    source_name=excluded.source_name,
    source_url=excluded.source_url,
    pdf_url=excluded.pdf_url,
    pdf_sha256=excluded.pdf_sha256,
    page_start=excluded.page_start,
    page_end=excluded.page_end,
    title=excluded.title,
    case_number=excluded.case_number,
    court_name=excluded.court_name,
    judgment_year=excluded.judgment_year,
    extracted_text=excluded.extracted_text,
    normalized_text=excluded.normalized_text,
    indexed_at=CURRENT_TIMESTAMP
"""


def _case_params(case: CatalogCase) -> tuple[object, ...]:
    return (
        case.catalog_key,
        case.collection_id,
        case.source_id,
        case.source_name,
        case.source_url,
        case.pdf_url,
        case.pdf_sha256,
        case.page_start,
        case.page_end,
        case.title,
        case.case_number,
        case.court_name,
        case.judgment_year,
        case.text,
        case.normalized_text,
    )


class CatalogStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    def _connect(self) -> aiosqlite.Connection:
        return aiosqlite.connect(self.database.path)

    async def upsert(self, case: CatalogCase) -> None:
        async with self._connect() as db:
            await db.execute(_CASE_UPSERT_SQL, _case_params(case))
            await db.commit()

    async def replace_collection(
        self,
        collection_id: str,
        cases: Iterable[CatalogCase],
    ) -> int:
        """Atomically replace one indexed source document with a parsed snapshot.

        Parsing happens before this method is called. A crash or malformed PDF can
        therefore never leave half of a collection committed in the searchable
        catalog, and a large collection is inserted with one SQLite transaction
        instead of opening/committing once per judgment.
        """
        prepared = list(cases)
        if any(case.collection_id != collection_id for case in prepared):
            raise ValueError("All catalog cases must belong to the replaced collection")
        async with self._connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                await db.execute(
                    "DELETE FROM official_case_catalog WHERE collection_id = ?",
                    (collection_id,),
                )
                if prepared:
                    await db.executemany(
                        _CASE_UPSERT_SQL,
                        [_case_params(case) for case in prepared],
                    )
                await db.commit()
            except Exception:
                await db.rollback()
                raise
        return len(prepared)

    async def remove_collection(self, collection_id: str) -> int:
        async with self._connect() as db:
            cursor = await db.execute(
                "DELETE FROM official_case_catalog WHERE collection_id = ?",
                (collection_id,),
            )
            await db.commit()
            return max(0, cursor.rowcount)

    async def is_document_indexed(self, source_url: str) -> bool:
        async with self._connect() as db:
            cursor = await db.execute(
                "SELECT 1 FROM catalog_documents WHERE source_url = ? LIMIT 1",
                (source_url,),
            )
            return await cursor.fetchone() is not None

    async def record_document(
        self,
        *,
        source_url: str,
        collection_id: str,
        source_id: str,
        pdf_sha256: str | None,
        case_count: int,
    ) -> None:
        async with self._connect() as db:
            await db.execute(
                """
                INSERT INTO catalog_documents(
                    source_url, collection_id, source_id, pdf_sha256, case_count, indexed_at
                ) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(source_url) DO UPDATE SET
                    collection_id=excluded.collection_id,
                    source_id=excluded.source_id,
                    pdf_sha256=excluded.pdf_sha256,
                    case_count=excluded.case_count,
                    indexed_at=CURRENT_TIMESTAMP
                """,
                (source_url, collection_id, source_id, pdf_sha256, max(0, int(case_count))),
            )
            await db.commit()

    async def search(
        self,
        terms: list[str],
        *,
        preferred_source_ids: tuple[str, ...] = (),
        limit: int = 20,
    ) -> list[dict[str, object]]:
        normalized_terms: list[str] = []
        for term in terms:
            value = normalize_arabic(term)
            if len(value) >= 2 and value not in normalized_terms:
                normalized_terms.append(value)
        if not normalized_terms:
            return []

        # Catalog sizes are expected in the thousands, not millions. A bounded
        # LIKE prefilter over normalized Arabic is intentionally used instead of
        # tying correctness to optional SQLite FTS extensions; the second stage
        # ranks the bounded rows deterministically in Python.
        sql_terms = normalized_terms[:40]
        clauses = " OR ".join("normalized_text LIKE ?" for _ in sql_terms)
        params: list[object] = [f"%{term}%" for term in sql_terms]
        sql = f"""
            SELECT catalog_key, collection_id, source_id, source_name, source_url,
                   pdf_url, pdf_sha256, page_start, page_end, title, case_number,
                   court_name, judgment_year, extracted_text, normalized_text
              FROM official_case_catalog
             WHERE {clauses}
             ORDER BY indexed_at DESC
             LIMIT ?
        """
        params.append(max(40, min(int(limit) * 16, 600)))
        async with self._connect() as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(sql, params)
            rows = [dict(row) for row in await cursor.fetchall()]

        preferred = set(preferred_source_ids)
        for row in rows:
            haystack = str(row["normalized_text"])
            match_score = 0
            phrase_hits = 0
            for index, term in enumerate(normalized_terms):
                if term in haystack:
                    # Early terms are explicit search keywords/full course topics;
                    # later terms are recall-expansion tokens and get less weight.
                    match_score += max(1, 14 - min(index, 13))
                    if " " in term:
                        phrase_hits += 1
            if str(row["source_id"]) in preferred:
                match_score += 14
            if row.get("case_number"):
                match_score += 4
            if row.get("court_name"):
                match_score += 3
            row["catalog_match_score"] = match_score + phrase_hits * 5

        rows.sort(key=lambda row: int(row["catalog_match_score"]), reverse=True)
        return rows[: max(1, int(limit))]

    async def stats(self) -> CatalogStats:
        async with self._connect() as db:
            cursor = await db.execute(
                "SELECT COUNT(*), COUNT(DISTINCT collection_id), COUNT(DISTINCT source_id) FROM official_case_catalog"
            )
            row = await cursor.fetchone()
        return CatalogStats(cases=int(row[0]), collections=int(row[1]), sources=int(row[2]))
