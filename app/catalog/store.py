"""Persistence and deterministic retrieval for the official judicial catalog."""

from __future__ import annotations

import aiosqlite

from app.db import Database

from .models import CatalogCase, CatalogStats
from .text import normalize_arabic


class CatalogStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    def _connect(self) -> aiosqlite.Connection:
        return aiosqlite.connect(self.database.path)

    async def upsert(self, case: CatalogCase) -> None:
        async with self._connect() as db:
            await db.execute(
                """
                INSERT INTO official_case_catalog(
                    catalog_key, collection_id, source_id, source_name, source_url,
                    pdf_url, pdf_sha256, page_start, page_end, title, case_number,
                    court_name, judgment_year, extracted_text, normalized_text,
                    indexed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(catalog_key) DO UPDATE SET
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
                """,
                (
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
                ),
            )
            await db.commit()

    async def remove_collection(self, collection_id: str) -> int:
        async with self._connect() as db:
            cursor = await db.execute(
                "DELETE FROM official_case_catalog WHERE collection_id = ?",
                (collection_id,),
            )
            await db.commit()
            return max(0, cursor.rowcount)

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

        # SQL narrows the candidate set; final weighted ranking happens in Python
        # so Arabic phrase matches and source preference remain deterministic.
        clauses = " OR ".join("normalized_text LIKE ?" for _ in normalized_terms[:24])
        params: list[object] = [f"%{term}%" for term in normalized_terms[:24]]
        sql = f"""
            SELECT catalog_key, collection_id, source_id, source_name, source_url,
                   pdf_url, pdf_sha256, page_start, page_end, title, case_number,
                   court_name, judgment_year, extracted_text, normalized_text
              FROM official_case_catalog
             WHERE {clauses}
             ORDER BY indexed_at DESC
             LIMIT ?
        """
        params.append(max(20, min(int(limit) * 12, 400)))
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
                    # Priority topics and earlier search terms are worth more.
                    match_score += max(2, 12 - min(index, 10))
                    if " " in term:
                        phrase_hits += 1
            if str(row["source_id"]) in preferred:
                match_score += 12
            if row.get("case_number"):
                match_score += 4
            if row.get("court_name"):
                match_score += 3
            row["catalog_match_score"] = match_score + phrase_hits * 4

        rows.sort(key=lambda row: int(row["catalog_match_score"]), reverse=True)
        return rows[: max(1, int(limit))]

    async def stats(self) -> CatalogStats:
        async with self._connect() as db:
            cursor = await db.execute(
                "SELECT COUNT(*), COUNT(DISTINCT collection_id), COUNT(DISTINCT source_id) FROM official_case_catalog"
            )
            row = await cursor.fetchone()
        return CatalogStats(cases=int(row[0]), collections=int(row[1]), sources=int(row[2]))
