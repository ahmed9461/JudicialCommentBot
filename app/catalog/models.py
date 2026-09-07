"""Models for the local official judicial catalog."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CatalogCase:
    catalog_key: str
    collection_id: str
    source_id: str
    source_name: str
    source_url: str
    pdf_url: str
    page_start: int
    page_end: int
    title: str
    case_number: str | None
    court_name: str | None
    judgment_year: str | None
    text: str
    normalized_text: str
    pdf_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class CatalogStats:
    cases: int
    collections: int
    sources: int


@dataclass(frozen=True, slots=True)
class CatalogGenerationState:
    parser_version: int
    is_ready: bool
    refresh_status: str
    ready_at: str | None = None
    refresh_started_at: str | None = None
    refresh_finished_at: str | None = None
    documents_seen: int = 0
    documents_indexed: int = 0
    documents_skipped: int = 0
    documents_failed: int = 0
    cases_indexed: int = 0
    last_error: str | None = None
