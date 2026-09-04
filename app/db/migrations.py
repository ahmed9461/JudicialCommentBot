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
    3: """
    ALTER TABLE case_history ADD COLUMN artifact_kind TEXT;
    ALTER TABLE case_history ADD COLUMN source_page_start INTEGER;
    ALTER TABLE case_history ADD COLUMN source_page_end INTEGER;

    CREATE TABLE IF NOT EXISTS case_reservations (
        token TEXT PRIMARY KEY,
        case_number TEXT,
        court_name TEXT,
        pdf_sha256 TEXT NOT NULL,
        reserved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_case_reservation_sha
        ON case_reservations(pdf_sha256);
    CREATE UNIQUE INDEX IF NOT EXISTS idx_case_reservation_case_court
        ON case_reservations(LOWER(TRIM(case_number)), LOWER(TRIM(court_name)))
        WHERE case_number IS NOT NULL AND case_number <> ''
          AND court_name IS NOT NULL AND court_name <> '';
    """,
    4: """
    CREATE TABLE IF NOT EXISTS official_case_catalog (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        catalog_key TEXT NOT NULL UNIQUE,
        collection_id TEXT NOT NULL,
        source_id TEXT NOT NULL,
        source_name TEXT NOT NULL,
        source_url TEXT NOT NULL,
        pdf_url TEXT NOT NULL,
        pdf_sha256 TEXT,
        page_start INTEGER NOT NULL,
        page_end INTEGER NOT NULL,
        title TEXT NOT NULL,
        case_number TEXT,
        court_name TEXT,
        judgment_year TEXT,
        extracted_text TEXT NOT NULL,
        normalized_text TEXT NOT NULL,
        indexed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CHECK(page_start >= 1),
        CHECK(page_end >= page_start)
    );
    CREATE INDEX IF NOT EXISTS idx_catalog_collection ON official_case_catalog(collection_id);
    CREATE INDEX IF NOT EXISTS idx_catalog_source ON official_case_catalog(source_id);
    CREATE INDEX IF NOT EXISTS idx_catalog_case_number ON official_case_catalog(case_number);
    CREATE INDEX IF NOT EXISTS idx_catalog_year ON official_case_catalog(judgment_year);
    """,
    5: """
    CREATE TABLE IF NOT EXISTS catalog_documents (
        source_url TEXT PRIMARY KEY,
        collection_id TEXT NOT NULL,
        source_id TEXT NOT NULL,
        pdf_sha256 TEXT,
        case_count INTEGER NOT NULL DEFAULT 0,
        indexed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_catalog_documents_source ON catalog_documents(source_id);
    """,
}
