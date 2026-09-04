"""Versioned SQLite schema migrations."""

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
    CREATE INDEX IF NOT EXISTS idx_case_history_subject ON case_history(subject_slug);
    CREATE INDEX IF NOT EXISTS idx_case_history_sha256 ON case_history(pdf_sha256);
    """,
    2: """
    DELETE FROM case_history
      WHERE pdf_sha256 IS NOT NULL AND pdf_sha256 <> ''
        AND id NOT IN (
          SELECT MIN(id) FROM case_history
          WHERE pdf_sha256 IS NOT NULL AND pdf_sha256 <> '' GROUP BY pdf_sha256
        );
    DELETE FROM case_history
      WHERE case_number IS NOT NULL AND case_number <> ''
        AND court_name IS NOT NULL AND court_name <> ''
        AND id NOT IN (
          SELECT MIN(id) FROM case_history
          WHERE case_number IS NOT NULL AND case_number <> ''
            AND court_name IS NOT NULL AND court_name <> ''
          GROUP BY LOWER(TRIM(case_number)), LOWER(TRIM(court_name))
        );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_case_history_unique_sha
        ON case_history(pdf_sha256)
        WHERE pdf_sha256 IS NOT NULL AND pdf_sha256 <> '';
    CREATE UNIQUE INDEX IF NOT EXISTS idx_case_history_unique_case_court
        ON case_history(LOWER(TRIM(case_number)), LOWER(TRIM(court_name)))
        WHERE case_number IS NOT NULL AND case_number <> ''
          AND court_name IS NOT NULL AND court_name <> '';
    CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_type TEXT NOT NULL,
        subject_slug TEXT,
        case_number TEXT,
        details TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_audit_log_created ON audit_log(created_at);
    """,
}
