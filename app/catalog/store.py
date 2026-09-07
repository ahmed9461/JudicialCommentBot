"""Persistence and deterministic retrieval for the official judicial catalog.

The catalog uses blue/green generations.  A refresh writes into an isolated
snapshot and runtime reads only the single generation referenced by
``catalog_active_generation``.  Promotion is one SQLite transaction, so a
partially-built refresh can never leak into Telegram searches.
"""

from __future__ import annotations

from collections.abc import Iterable
from uuid import uuid4

import aiosqlite

from app.db import Database

from .models import CatalogCase, CatalogGenerationState, CatalogStats
from .text import normalize_arabic

_CASE_UPSERT_SQL = """
INSERT INTO catalog_generation_cases(
    generation_id, catalog_key, collection_id, source_id, source_name, source_url,
    pdf_url, pdf_sha256, page_start, page_end, title, case_number, court_name,
    judgment_year, extracted_text, normalized_text, indexed_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
ON CONFLICT(generation_id, catalog_key) DO UPDATE SET
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


def _case_params(generation_id: str, case: CatalogCase) -> tuple[object, ...]:
    return (
        generation_id,
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

    @staticmethod
    def _state_from_row(row: aiosqlite.Row | tuple[object, ...] | None, *, active_id: str | None = None) -> CatalogGenerationState | None:
        if row is None:
            return None
        return CatalogGenerationState(
            generation_id=str(row[0]),
            parser_version=int(row[1]),
            status=str(row[2]),
            is_active=str(row[0]) == active_id,
            started_at=row[3],
            finished_at=row[4],
            activated_at=row[5],
            documents_seen=int(row[6]),
            documents_indexed=int(row[7]),
            documents_failed=int(row[8]),
            cases_indexed=int(row[9]),
            covered_subjects=int(row[10]),
            total_subjects=int(row[11]),
            last_error=row[12],
        )

    async def begin_generation(self, parser_version: int) -> str:
        """Create one isolated build snapshot.

        The database permits only one ``building`` generation at a time.  This
        prevents overlapping timers/manual refreshes from racing to activation.
        """
        generation_id = uuid4().hex
        async with self._connect() as db:
            try:
                await db.execute(
                    "INSERT INTO catalog_generations(generation_id, parser_version, status) VALUES (?, ?, 'building')",
                    (generation_id, int(parser_version)),
                )
                await db.commit()
            except aiosqlite.IntegrityError as exc:
                await db.rollback()
                raise RuntimeError("another catalog generation is already building") from exc
        return generation_id

    async def active_generation_state(self) -> CatalogGenerationState | None:
        async with self._connect() as db:
            cursor = await db.execute(
                """
                SELECT g.generation_id, g.parser_version, g.status, g.started_at,
                       g.finished_at, g.activated_at, g.documents_seen,
                       g.documents_indexed, g.documents_failed, g.cases_indexed,
                       g.covered_subjects, g.total_subjects, g.last_error
                  FROM catalog_active_generation AS a
                  JOIN catalog_generations AS g ON g.generation_id = a.generation_id
                 WHERE a.singleton = 1
                """
            )
            row = await cursor.fetchone()
        return self._state_from_row(row, active_id=str(row[0]) if row else None)

    async def latest_generation_state(self, parser_version: int | None = None) -> CatalogGenerationState | None:
        async with self._connect() as db:
            active_cursor = await db.execute(
                "SELECT generation_id FROM catalog_active_generation WHERE singleton = 1"
            )
            active_row = await active_cursor.fetchone()
            active_id = str(active_row[0]) if active_row else None
            if parser_version is None:
                cursor = await db.execute(
                    """
                    SELECT generation_id, parser_version, status, started_at,
                           finished_at, activated_at, documents_seen,
                           documents_indexed, documents_failed, cases_indexed,
                           covered_subjects, total_subjects, last_error
                      FROM catalog_generations
                     ORDER BY started_at DESC, rowid DESC LIMIT 1
                    """
                )
            else:
                cursor = await db.execute(
                    """
                    SELECT generation_id, parser_version, status, started_at,
                           finished_at, activated_at, documents_seen,
                           documents_indexed, documents_failed, cases_indexed,
                           covered_subjects, total_subjects, last_error
                      FROM catalog_generations
                     WHERE parser_version = ?
                     ORDER BY started_at DESC, rowid DESC LIMIT 1
                    """,
                    (int(parser_version),),
                )
            row = await cursor.fetchone()
        return self._state_from_row(row, active_id=active_id)

    async def active_generation_id(self, *, parser_version: int | None = None) -> str | None:
        state = await self.active_generation_state()
        if state is None:
            return None
        if parser_version is not None and state.parser_version != int(parser_version):
            return None
        return state.generation_id

    async def update_generation_result(
        self,
        generation_id: str,
        *,
        status: str,
        documents_seen: int,
        documents_indexed: int,
        documents_failed: int,
        cases_indexed: int,
        covered_subjects: int = 0,
        total_subjects: int = 0,
        error: str | None = None,
    ) -> None:
        if status not in {"building", "failed", "discarded"}:
            raise ValueError("update_generation_result only accepts non-active build states")
        async with self._connect() as db:
            await db.execute(
                """
                UPDATE catalog_generations
                   SET status=?, finished_at=CASE WHEN ?='building' THEN NULL ELSE CURRENT_TIMESTAMP END,
                       documents_seen=?, documents_indexed=?, documents_failed=?, cases_indexed=?,
                       covered_subjects=?, total_subjects=?, last_error=?
                 WHERE generation_id=?
                """,
                (
                    status,
                    status,
                    max(0, int(documents_seen)),
                    max(0, int(documents_indexed)),
                    max(0, int(documents_failed)),
                    max(0, int(cases_indexed)),
                    max(0, int(covered_subjects)),
                    max(0, int(total_subjects)),
                    (error or "")[:1000] or None,
                    generation_id,
                ),
            )
            await db.commit()

    async def promote_generation(
        self,
        generation_id: str,
        *,
        documents_seen: int,
        documents_indexed: int,
        documents_failed: int,
        cases_indexed: int,
        covered_subjects: int,
        total_subjects: int,
    ) -> None:
        """Atomically make a fully-built generation visible to runtime."""
        async with self._connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                cursor = await db.execute(
                    "SELECT status FROM catalog_generations WHERE generation_id = ?",
                    (generation_id,),
                )
                row = await cursor.fetchone()
                if row is None or str(row[0]) != "building":
                    raise RuntimeError("catalog generation is not promotable")
                stats_cursor = await db.execute(
                    "SELECT COUNT(*) FROM catalog_generation_cases WHERE generation_id = ?",
                    (generation_id,),
                )
                if int((await stats_cursor.fetchone())[0]) <= 0:
                    raise RuntimeError("cannot promote an empty catalog generation")

                active_cursor = await db.execute(
                    "SELECT generation_id FROM catalog_active_generation WHERE singleton = 1"
                )
                active_row = await active_cursor.fetchone()
                if active_row and str(active_row[0]) != generation_id:
                    await db.execute(
                        "UPDATE catalog_generations SET status='superseded' WHERE generation_id = ? AND status='ready'",
                        (str(active_row[0]),),
                    )

                await db.execute(
                    """
                    UPDATE catalog_generations
                       SET status='ready', finished_at=CURRENT_TIMESTAMP,
                           activated_at=CURRENT_TIMESTAMP, documents_seen=?,
                           documents_indexed=?, documents_failed=?, cases_indexed=?,
                           covered_subjects=?, total_subjects=?, last_error=NULL
                     WHERE generation_id=?
                    """,
                    (
                        max(0, int(documents_seen)),
                        max(0, int(documents_indexed)),
                        max(0, int(documents_failed)),
                        max(0, int(cases_indexed)),
                        max(0, int(covered_subjects)),
                        max(0, int(total_subjects)),
                        generation_id,
                    ),
                )
                await db.execute(
                    """
                    INSERT INTO catalog_active_generation(singleton, generation_id, activated_at)
                    VALUES (1, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(singleton) DO UPDATE SET
                        generation_id=excluded.generation_id,
                        activated_at=CURRENT_TIMESTAMP
                    """,
                    (generation_id,),
                )
                await db.commit()
            except Exception:
                await db.rollback()
                raise

    async def cleanup_inactive_generations(self, *, keep: int = 2) -> int:
        """Delete old non-active snapshot rows while retaining recent audit generations."""
        keep = max(1, int(keep))
        async with self._connect() as db:
            active_cursor = await db.execute(
                "SELECT generation_id FROM catalog_active_generation WHERE singleton = 1"
            )
            active_row = await active_cursor.fetchone()
            active_id = str(active_row[0]) if active_row else None
            cursor = await db.execute(
                """
                SELECT generation_id FROM catalog_generations
                 WHERE status IN ('failed', 'discarded', 'superseded')
                 ORDER BY COALESCE(finished_at, started_at) DESC
                """
            )
            candidates = [str(row[0]) for row in await cursor.fetchall() if str(row[0]) != active_id]
            doomed = candidates[keep:]
            if not doomed:
                return 0
            placeholders = ",".join("?" for _ in doomed)
            await db.execute(f"DELETE FROM catalog_generation_cases WHERE generation_id IN ({placeholders})", doomed)
            await db.execute(f"DELETE FROM catalog_generation_documents WHERE generation_id IN ({placeholders})", doomed)
            await db.execute(f"DELETE FROM catalog_generations WHERE generation_id IN ({placeholders})", doomed)
            await db.commit()
            return len(doomed)

    async def upsert(self, generation_id: str, case: CatalogCase) -> None:
        async with self._connect() as db:
            await db.execute(_CASE_UPSERT_SQL, _case_params(generation_id, case))
            await db.commit()

    async def replace_collection(
        self,
        generation_id: str,
        collection_id: str,
        cases: Iterable[CatalogCase],
    ) -> int:
        """Atomically replace one source document inside one staging generation."""
        prepared = list(cases)
        if any(case.collection_id != collection_id for case in prepared):
            raise ValueError("All catalog cases must belong to the replaced collection")
        async with self._connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                await db.execute(
                    "DELETE FROM catalog_generation_cases WHERE generation_id = ? AND collection_id = ?",
                    (generation_id, collection_id),
                )
                if prepared:
                    await db.executemany(
                        _CASE_UPSERT_SQL,
                        [_case_params(generation_id, case) for case in prepared],
                    )
                await db.commit()
            except Exception:
                await db.rollback()
                raise
        return len(prepared)

    async def is_document_indexed(self, generation_id: str, source_url: str) -> bool:
        async with self._connect() as db:
            cursor = await db.execute(
                "SELECT 1 FROM catalog_generation_documents WHERE generation_id=? AND source_url=? LIMIT 1",
                (generation_id, source_url),
            )
            return await cursor.fetchone() is not None

    async def record_document(
        self,
        generation_id: str,
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
                INSERT INTO catalog_generation_documents(
                    generation_id, source_url, collection_id, source_id,
                    pdf_sha256, case_count, indexed_at
                ) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(generation_id, source_url) DO UPDATE SET
                    collection_id=excluded.collection_id,
                    source_id=excluded.source_id,
                    pdf_sha256=excluded.pdf_sha256,
                    case_count=excluded.case_count,
                    indexed_at=CURRENT_TIMESTAMP
                """,
                (
                    generation_id,
                    source_url,
                    collection_id,
                    source_id,
                    pdf_sha256,
                    max(0, int(case_count)),
                ),
            )
            await db.commit()

    async def search(
        self,
        terms: list[str],
        *,
        preferred_source_ids: tuple[str, ...] = (),
        limit: int = 20,
        generation_id: str | None = None,
        parser_version: int | None = None,
    ) -> list[dict[str, object]]:
        normalized_terms: list[str] = []
        for term in terms:
            value = normalize_arabic(term)
            if len(value) >= 2 and value not in normalized_terms:
                normalized_terms.append(value)
        if not normalized_terms:
            return []

        if generation_id is None:
            generation_id = await self.active_generation_id(parser_version=parser_version)
        if not generation_id:
            return []

        sql_terms = normalized_terms[:40]
        clauses = " OR ".join("normalized_text LIKE ?" for _ in sql_terms)
        params: list[object] = [generation_id, *[f"%{term}%" for term in sql_terms]]
        sql = f"""
            SELECT catalog_key, collection_id, source_id, source_name, source_url,
                   pdf_url, pdf_sha256, page_start, page_end, title, case_number,
                   court_name, judgment_year, extracted_text, normalized_text
              FROM catalog_generation_cases
             WHERE generation_id = ? AND ({clauses})
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

    async def stats(
        self,
        *,
        generation_id: str | None = None,
        parser_version: int | None = None,
    ) -> CatalogStats:
        if generation_id is None:
            generation_id = await self.active_generation_id(parser_version=parser_version)
        if not generation_id:
            return CatalogStats(cases=0, collections=0, sources=0)
        async with self._connect() as db:
            cursor = await db.execute(
                """
                SELECT COUNT(*), COUNT(DISTINCT collection_id), COUNT(DISTINCT source_id)
                  FROM catalog_generation_cases WHERE generation_id = ?
                """,
                (generation_id,),
            )
            row = await cursor.fetchone()
        return CatalogStats(cases=int(row[0]), collections=int(row[1]), sources=int(row[2]))

    async def generation_case_texts(self, generation_id: str) -> list[str]:
        async with self._connect() as db:
            cursor = await db.execute(
                "SELECT extracted_text FROM catalog_generation_cases WHERE generation_id = ?",
                (generation_id,),
            )
            return [str(row[0]) for row in await cursor.fetchall()]
