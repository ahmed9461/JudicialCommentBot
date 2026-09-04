"""Container/systemd health check: configuration, runtime path and SQLite schema."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from app.core.settings import get_settings
from app.db.migrations import MIGRATIONS


def check() -> tuple[bool, str]:
    try:
        settings = get_settings()
        if not settings.telegram_bot_token.get_secret_value().strip():
            return False, "telegram token is empty"
        if settings.owner_telegram_id <= 0:
            return False, "owner id is invalid"
        runtime = Path(settings.temp_dir).parent
        runtime.mkdir(parents=True, exist_ok=True)
        probe = runtime / ".healthcheck-write"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)

        db_path = _sqlite_path(settings.database_url)
        if db_path == ":memory:":
            return True, "ok"
        path = Path(db_path)
        if not path.is_file():
            return False, "database has not been initialized"
        with sqlite3.connect(path) as db:
            row = db.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()
            version = int(row[0] if row else 0)
        if version != max(MIGRATIONS):
            return False, f"database migration version is {version}, expected {max(MIGRATIONS)}"
        return True, "ok"
    except Exception as exc:
        return False, str(exc)


def _sqlite_path(url: str) -> str:
    for prefix in ("sqlite+aiosqlite:///", "sqlite:///"):
        if url.startswith(prefix):
            return url[len(prefix):]
    if url == ":memory:":
        return url
    raise ValueError("healthcheck supports SQLite only")


def main() -> None:
    healthy, message = check()
    print(message)
    raise SystemExit(0 if healthy else 1)


if __name__ == "__main__":
    main()
