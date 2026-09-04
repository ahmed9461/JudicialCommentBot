"""Async SQLite persistence and schema migrations."""

from __future__ import annotations

from pathlib import Path

import aiosqlite

from .migrations import MIGRATIONS


class Database:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.path = self._sqlite_path(database_url)

    @staticmethod
    def _sqlite_path(url: str) -> str:
        for prefix in ("sqlite+aiosqlite:///", "sqlite:///"):
            if url.startswith(prefix):
                return url[len(prefix):]
        if url == ":memory:":
            return url
        raise ValueError("Only SQLite database URLs are supported")

    def _connect(self) -> aiosqlite.Connection:
        return aiosqlite.connect(self.path)

    async def initialize(self) -> None:
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        async with self._connect() as db:
            await db.execute("PRAGMA foreign_keys = ON")
            if self.path != ":memory:":
                await db.execute("PRAGMA journal_mode = WAL")
            await db.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
            await db.commit()
            cursor = await db.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations")
            current = int((await cursor.fetchone())[0])
            for version in sorted(MIGRATIONS):
                if version <= current:
                    continue
                await db.executescript(MIGRATIONS[version])
                await db.execute("INSERT INTO schema_migrations(version) VALUES (?)", (version,))
                await db.commit()

    async def is_allowed_user(self, telegram_id: int) -> bool:
        async with self._connect() as db:
            cursor = await db.execute("SELECT 1 FROM allowed_users WHERE telegram_id = ? LIMIT 1", (telegram_id,))
            return await cursor.fetchone() is not None

    async def add_allowed_user(self, telegram_id: int, added_by: int) -> bool:
        async with self._connect() as db:
            cursor = await db.execute("INSERT OR IGNORE INTO allowed_users(telegram_id, added_by) VALUES (?, ?)", (telegram_id, added_by))
            await db.commit()
            return cursor.rowcount > 0

    async def remove_allowed_user(self, telegram_id: int) -> bool:
        async with self._connect() as db:
            cursor = await db.execute("DELETE FROM allowed_users WHERE telegram_id = ?", (telegram_id,))
            await db.commit()
            return cursor.rowcount > 0

    async def list_allowed_users(self) -> list[int]:
        async with self._connect() as db:
            cursor = await db.execute("SELECT telegram_id FROM allowed_users ORDER BY created_at, telegram_id")
            return [int(row[0]) for row in await cursor.fetchall()]

    async def used_cases_for_subject(self, subject_slug: str) -> list[dict[str, str | None]]:
        async with self._connect() as db:
            cursor = await db.execute(
                "SELECT case_number, court_name, source_url FROM case_history WHERE subject_slug = ? ORDER BY used_at DESC LIMIT 200",
                (subject_slug,),
            )
            return [{"case_number": row[0], "court_name": row[1], "source_url": row[2]} for row in await cursor.fetchall()]

    async def is_case_used(self, *, case_number: str | None, court_name: str | None, pdf_sha256: str | None) -> bool:
        clauses: list[str] = []
        params: list[str] = []
        if pdf_sha256:
            clauses.append("pdf_sha256 = ?")
            params.append(pdf_sha256)
        if case_number and court_name:
            clauses.append("(LOWER(TRIM(case_number)) = LOWER(TRIM(?)) AND LOWER(TRIM(court_name)) = LOWER(TRIM(?)))")
            params.extend([case_number, court_name])
        if not clauses:
            return False
        async with self._connect() as db:
            cursor = await db.execute(f"SELECT 1 FROM case_history WHERE {' OR '.join(clauses)} LIMIT 1", params)
            return await cursor.fetchone() is not None

    async def reserve_case(self, token: str, *, case_number: str | None, court_name: str | None,
                           pdf_sha256: str, ttl_minutes: int = 30) -> bool:
        async with self._connect() as db:
            await db.execute(
                "DELETE FROM case_reservations WHERE reserved_at < datetime('now', ?)",
                (f"-{max(1, ttl_minutes)} minutes",),
            )
            try:
                cursor = await db.execute(
                    "INSERT INTO case_reservations(token, case_number, court_name, pdf_sha256) VALUES (?, ?, ?, ?)",
                    (token, case_number, court_name, pdf_sha256),
                )
                await db.commit()
                return cursor.rowcount > 0
            except aiosqlite.IntegrityError:
                await db.rollback()
                return False

    async def release_reservation(self, token: str) -> None:
        async with self._connect() as db:
            await db.execute("DELETE FROM case_reservations WHERE token = ?", (token,))
            await db.commit()

    async def release_reservations(self, tokens: list[str]) -> None:
        if not tokens:
            return
        placeholders = ",".join("?" for _ in tokens)
        async with self._connect() as db:
            await db.execute(f"DELETE FROM case_reservations WHERE token IN ({placeholders})", tokens)
            await db.commit()

    async def record_case(self, *, subject_slug: str, case_number: str | None, court_name: str | None,
                          source_name: str | None, source_url: str | None, pdf_sha256: str,
                          suitability_score: int, artifact_kind: str = "official_pdf",
                          source_page_start: int | None = None, source_page_end: int | None = None) -> bool:
        async with self._connect() as db:
            cursor = await db.execute(
                """INSERT OR IGNORE INTO case_history(
                       subject_slug, case_number, court_name, source_name, source_url, pdf_sha256,
                       suitability_score, artifact_kind, source_page_start, source_page_end
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (subject_slug, case_number, court_name, source_name, source_url, pdf_sha256,
                 suitability_score, artifact_kind, source_page_start, source_page_end),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def add_audit(self, event_type: str, *, subject_slug: str | None = None,
                        case_number: str | None = None, details: str | None = None) -> None:
        async with self._connect() as db:
            await db.execute("INSERT INTO audit_log(event_type, subject_slug, case_number, details) VALUES (?, ?, ?, ?)",
                             (event_type, subject_slug, case_number, details))
            await db.commit()

    async def recent_history(self, limit: int = 20) -> list[dict[str, object]]:
        async with self._connect() as db:
            cursor = await db.execute(
                """SELECT subject_slug, case_number, court_name, source_name, source_url,
                          suitability_score, used_at, artifact_kind, source_page_start, source_page_end
                   FROM case_history ORDER BY used_at DESC LIMIT ?""",
                (max(1, min(limit, 100)),),
            )
            return [
                {"subject_slug": row[0], "case_number": row[1], "court_name": row[2],
                 "source_name": row[3], "source_url": row[4], "suitability_score": row[5],
                 "used_at": row[6], "artifact_kind": row[7], "source_page_start": row[8],
                 "source_page_end": row[9]}
                for row in await cursor.fetchall()
            ]
