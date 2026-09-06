"""Build a reusable local case catalog from official Saudi judicial PDFs.

The catalog is deterministic and provenance-aware: it downloads approved
official PDFs, finds *primary* judicial headers using the same parser used at
delivery time, stores exact physical page ranges, and records the source
SHA-256. References to other cases inside a judgment body never create a new
catalog boundary.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from collections import deque
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx
from pypdf import PdfReader

from app.pdf import PdfAcquisitionError, PdfAcquisitionService, extract_judgment_metadata
from app.pdf.headers import primary_judicial_header
from app.sources import SourceRegistry

from .manifest import CatalogManifest, CatalogSourceSpec
from .models import CatalogCase
from .store import CatalogStore
from .text import detect_court_name, detect_judgment_year, make_title, normalize_arabic

logger = logging.getLogger(__name__)

# Increment whenever catalog admission/boundary semantics change. Runtime search
# only exposes rows from this exact parser generation.
CATALOG_PARSER_VERSION = 4


@dataclass(frozen=True, slots=True)
class IndexReport:
    documents_seen: int = 0
    documents_indexed: int = 0
    documents_skipped: int = 0
    documents_failed: int = 0
    cases_indexed: int = 0


class OfficialCatalogIndexer:
    def __init__(
        self,
        *,
        store: CatalogStore,
        manifest: CatalogManifest,
        source_registry: SourceRegistry,
        pdf_service: PdfAcquisitionService,
    ) -> None:
        self.store = store
        self.manifest = manifest
        self.source_registry = source_registry
        self.pdf_service = pdf_service

    async def refresh(
        self,
        *,
        source_filter: set[str] | None = None,
        max_documents: int | None = None,
        force: bool = False,
    ) -> IndexReport:
        documents_seen = documents_indexed = documents_skipped = documents_failed = cases_indexed = 0
        remaining = max_documents if max_documents and max_documents > 0 else None

        for spec in self.manifest.sources:
            if not spec.enabled or (source_filter and spec.id not in source_filter):
                continue
            documents = await self._documents_for(spec)
            for document_id, url in documents:
                if remaining is not None and remaining <= 0:
                    return IndexReport(
                        documents_seen,
                        documents_indexed,
                        documents_skipped,
                        documents_failed,
                        cases_indexed,
                    )
                documents_seen += 1
                if remaining is not None:
                    remaining -= 1
                if not force and await self.store.is_document_indexed(
                    url,
                    parser_version=CATALOG_PARSER_VERSION,
                ):
                    documents_skipped += 1
                    continue
                try:
                    count, pdf_sha256 = await self._index_document(spec, document_id, url)
                except Exception as exc:
                    documents_failed += 1
                    logger.warning(
                        "Catalog document failed id=%s url=%s reason=%s",
                        document_id,
                        url,
                        exc,
                    )
                else:
                    documents_indexed += 1
                    cases_indexed += count
                    await self.store.record_document(
                        source_url=url,
                        collection_id=document_id,
                        source_id=spec.source_id,
                        pdf_sha256=pdf_sha256,
                        case_count=count,
                        parser_version=CATALOG_PARSER_VERSION,
                    )
                if self.manifest.request_delay_seconds:
                    await asyncio.sleep(self.manifest.request_delay_seconds)

        return IndexReport(
            documents_seen,
            documents_indexed,
            documents_skipped,
            documents_failed,
            cases_indexed,
        )

    async def _documents_for(self, spec: CatalogSourceSpec) -> list[tuple[str, str]]:
        direct = spec.direct_documents()
        if direct:
            return direct
        if spec.kind == "landing_page_crawl":
            return await self._crawl_official_pdfs(spec)
        return []

    async def _crawl_official_pdfs(self, spec: CatalogSourceSpec) -> list[tuple[str, str]]:
        queue: deque[tuple[str, int]] = deque((url, 0) for url in spec.landing_pages)
        seen_pages: set[str] = set()
        pdfs: set[str] = set()
        timeout = httpx.Timeout(20.0, connect=8.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            while queue and len(seen_pages) < spec.max_pages:
                url, depth = queue.popleft()
                if url in seen_pages:
                    continue
                seen_pages.add(url)
                if not self.source_registry.is_https_allowed(url):
                    continue
                classification = self.source_registry.classify(url)
                if classification.source_id != spec.source_id:
                    continue
                try:
                    response = await client.get(
                        url,
                        headers={"User-Agent": "JudicialCommentBot/1.0 catalog-indexer"},
                    )
                    response.raise_for_status()
                except httpx.HTTPError as exc:
                    logger.info("Catalog landing page skipped url=%s reason=%s", url, exc)
                    continue
                content_type = response.headers.get("content-type", "").lower()
                if "pdf" in content_type or urlparse(str(response.url)).path.lower().endswith(".pdf"):
                    final_url = str(response.url)
                    if self.source_registry.can_be_original_pdf_source(final_url):
                        pdfs.add(final_url)
                    continue
                if depth >= spec.max_depth:
                    continue
                html = response.text
                for href in re.findall(r'''href\s*=\s*["']([^"']+)["']''', html, flags=re.I):
                    absolute = urljoin(str(response.url), href)
                    parsed = urlparse(absolute)
                    if parsed.scheme != "https":
                        continue
                    classification = self.source_registry.classify(absolute)
                    if classification.source_id != spec.source_id:
                        continue
                    if spec.allowed_path_prefixes and not any(
                        parsed.path.startswith(prefix) for prefix in spec.allowed_path_prefixes
                    ):
                        continue
                    if parsed.path.lower().endswith(".pdf"):
                        pdfs.add(absolute)
                    else:
                        queue.append((absolute, depth + 1))
        return [
            (
                f"{spec.id}:crawl:{hashlib.sha256(url.encode('utf-8')).hexdigest()[:16]}",
                url,
            )
            for url in sorted(pdfs)
        ]

    async def _index_document(
        self,
        spec: CatalogSourceSpec,
        document_id: str,
        url: str,
    ) -> tuple[int, str]:
        if not self.source_registry.can_be_original_pdf_source(url):
            raise ValueError(f"Catalog document is not an approved official PDF source: {url}")
        try:
            artifact = await self.pdf_service.acquire(url, suggested_name=document_id)
        except PdfAcquisitionError:
            raise
        try:
            reader = PdfReader(str(artifact.path), strict=False)
            page_texts = [(page.extract_text() or "").strip() for page in reader.pages]
            starts = self._case_starts(page_texts)
            if not starts:
                await self.store.replace_collection(document_id, [])
                logger.info("No primary judicial case boundaries detected in %s", url)
                return 0, artifact.sha256

            parsed_cases: list[CatalogCase] = []
            for position, start_index in enumerate(starts):
                next_start = starts[position + 1] if position + 1 < len(starts) else len(page_texts)
                end_index = next_start  # exclusive; next primary header is the only case boundary

                while end_index - 1 > start_index and len(page_texts[end_index - 1].strip()) < 120:
                    end_index -= 1

                header = primary_judicial_header(page_texts[start_index])
                if header is None:
                    continue
                case_number = header.case_number

                # The range may legitimately mention other case numbers in its
                # reasoning.  That is not a boundary.  A second *primary* header
                # would already be in ``starts`` and therefore cannot be inside
                # this range.
                combined = "\n".join(page_texts[start_index:end_index]).strip()
                if len(combined) < self.manifest.min_case_text_chars:
                    continue

                metadata = extract_judgment_metadata(
                    page_texts[start_index],
                    require_primary_header=True,
                )
                if metadata.case_number != case_number:
                    continue

                court_name = metadata.court_name or detect_court_name(combined)
                year = metadata.judgment_year or detect_judgment_year(combined)
                text = combined[: self.manifest.max_case_text_chars]
                page_start = start_index + 1
                page_end = end_index
                key_material = f"{url}|{case_number}|{page_start}|{page_end}|v{CATALOG_PARSER_VERSION}".encode("utf-8")
                catalog_key = hashlib.sha256(key_material).hexdigest()
                parsed_cases.append(
                    CatalogCase(
                        catalog_key=catalog_key,
                        collection_id=document_id,
                        source_id=spec.source_id,
                        source_name=spec.source_name,
                        source_url=url,
                        pdf_url=url,
                        pdf_sha256=artifact.sha256,
                        page_start=page_start,
                        page_end=page_end,
                        title=make_title(page_texts[start_index], case_number),
                        case_number=case_number,
                        court_name=court_name,
                        judgment_year=year,
                        text=text,
                        normalized_text=normalize_arabic(text),
                    )
                )

            indexed = await self.store.replace_collection(document_id, parsed_cases)
            if indexed:
                logger.info("Indexed %d primary-header case ranges from official document %s", indexed, url)
            else:
                logger.info("No usable judgments remained after primary-header verification %s", url)
            return indexed, artifact.sha256
        finally:
            artifact.path.unlink(missing_ok=True)

    @staticmethod
    def _case_starts(page_texts: list[str]) -> list[int]:
        """Return physical pages that begin a high-confidence primary judgment.

        A body paragraph citing another case, an appeal number or a previous
        judgment is ignored even if it contains ``القضية رقم``.  This is the
        invariant that prevents neighboring judgments from being merged.
        """
        starts: list[int] = []
        previous_case: str | None = None
        for index, text in enumerate(page_texts):
            if len(text) < 180:
                continue
            header = primary_judicial_header(text)
            if header is None:
                continue
            if header.case_number == previous_case:
                continue
            starts.append(index)
            previous_case = header.case_number
        return starts
