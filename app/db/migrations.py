"""Small versioned SQLite migration set.

A lightweight migration runner is enough for the current single-service SQLite
architecture and keeps schema changes explicit and testable.
"""

MIGRATIONS: dict[int, str] = {
    1: """
    CREATE TABLE IF NOT EXISTS allowed_users (
        telegram_id INTEGER PRIMARY KEY,
        added_by INTEGER NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS case_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        subject_slug TEXT NOT NULL,
        case_number TEXT,
        court_name TEXT,
        source_name TEXT,
        source_url TEXT,
        pdf_sha256 TEXT,
        suitability_score INTEGER,
        used_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(case_number, court_name, pdf_sha256)
    );

    CREATE INDEX IF NOT EXISTS idx_case_history_subject
        ON case_history(subject_slug);
    CREATE INDEX IF NOT EXISTS idx_case_history_sha256
        ON case_history(pdf_sha256);
    """,
}
