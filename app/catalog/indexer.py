"""Build reusable local case-catalog snapshots from official Saudi judicial PDFs.

Every refresh is isolated in its own generation. The indexer never mutates the
active catalog. Text extraction and primary-header recognition are shared with
runtime verification so a case admitted by the catalog is interpreted by the
same deterministic machinery when it is later delivered.
"""

from __future__ import annotations

import asyncio
import hashlib
import html
import logging
import re
from collections import deque
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx

from app.pdf import PdfAcquisitionError, PdfAcquisitionService, extract_judgment_metadata
from app.pdf.headers import primary_judicial_header
from app.pdf.text import extract_pdf_page_texts
from app.sources import SourceRegistry

from .manifest import CatalogManifest, CatalogSourceSpec
from .models import CatalogCase
from .store import CatalogStore
from .text import detect_court_name, detect_judgment_year, make_title, normalize_arabic

logger = logging.getLogger(__name__)

# Increment whenever extraction/header/boundary admission semantics change.
CATALOG_PARSER_VERSION = 6


@dataclass(frozen=True, slots=True)
class IndexReport:
    generation_id: str
    documents_seen: int = 0
    documents_indexed: int = 0
    documents_skipped: int = 0
    documents_failed: int = 0
    cases_indexed: int = 0
    full_refresh: bool = True


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
        """Build one complete isolated snapshot.

        ``force`` is retained for CLI compatibility. Blue/green generations are
        always rebuilt from source and partial diagnostic runs are never active.
        """
        del force
        generation_id = await self.store.begin_generation(CATALOG_PARSER_VERSION)
        documents_seen = documents_indexed = documents_skipped = documents_failed = cases_indexed = 0
        remaining = max_documents if max_documents and max_documents > 0 else None
        full_refresh = source_filter is None and remaining is None

        try:
            for spec in self.manifest.sources:
                if not spec.enabled or (source_filter and spec.id not in source_filter):
                    continue
                documents = await self._documents_for(spec)
                logger.info("Catalog source discovered source=%s documents=%d", spec.id, len(documents))
                for document_id, url in documents:
                    if remaining is not None and remaining <= 0:
                        break
                    documents_seen += 1
                    if remaining is not None:
                        remaining -= 1
                    try:
                        count, pdf_sha256 = await self._index_document(
                            generation_id,
                            spec,
                            document_id,
                            url,
                        )
                    except Exception as exc:
                        documents_failed += 1
                        logger.warning(
                            "Catalog document failed generation=%s id=%s url=%s reason=%s",
                            generation_id,
                            document_id,
                            url,
                            exc,
                        )
                    else:
                        documents_indexed += 1
                        cases_indexed += count
                        await self.store.record_document(
                            generation_id,
                            source_url=url,
                            collection_id=document_id,
                            source_id=spec.source_id,
                            pdf_sha256=pdf_sha256,
                            case_count=count,
                        )
                    await self.store.update_generation_result(
                        generation_id,
                        status="building",
                        documents_seen=documents_seen,
                        documents_indexed=documents_indexed,
                        documents_failed=documents_failed,
                        cases_indexed=cases_indexed,
                    )
                    if self.manifest.request_delay_seconds:
                        await asyncio.sleep(self.manifest.request_delay_seconds)
                if remaining is not None and remaining <= 0:
                    break

            report = IndexReport(
                generation_id=generation_id,
                documents_seen=documents_seen,
                documents_indexed=documents_indexed,
                documents_skipped=documents_skipped,
                documents_failed=documents_failed,
                cases_indexed=cases_indexed,
                full_refresh=full_refresh,
            )
            if not full_refresh:
                await self.store.update_generation_result(
                    generation_id,
                    status="discarded",
                    documents_seen=documents_seen,
                    documents_indexed=documents_indexed,
                    documents_failed=documents_failed,
                    cases_indexed=cases_indexed,
                    error="diagnostic partial refresh; generation was never eligible for activation",
                )
            return report
        except Exception as exc:
            await self.store.update_generation_result(
                generation_id,
                status="failed",
                documents_seen=documents_seen,
                documents_indexed=documents_indexed,
                documents_failed=documents_failed,
                cases_indexed=cases_indexed,
                error=f"{type(exc).__name__}: {exc}",
            )
            raise

    async def _documents_for(self, spec: CatalogSourceSpec) -> list[tuple[str, str]]:
        direct = spec.direct_documents()
        if direct:
            return direct
        if spec.kind == "landing_page_crawl":
            return await self._crawl_official_pdfs(spec)
        return []

    async def _crawl_official_pdfs(self, spec: CatalogSourceSpec) -> list[tuple[str, str]]:
        """Discover official judicial PDFs without wandering into unrelated site areas.

        Navigation pages and downloadable documents have separate allow-lists.
        This is important on SharePoint government sites where a decisions page
        links to statistics, annual reports, forms, templates and help material.
        Those resources are not judicial corpus inputs and are excluded before
        download rather than counted as parser failures later.
        """
        queue: deque[tuple[str, int]] = deque((url, 0) for url in spec.landing_pages)
        seen_pages: set[str] = set()
        pdfs: set[str] = set()
        timeout = httpx.Timeout(30.0, connect=10.0)
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; JudicialCommentBot/1.0; +official-catalog)",
            "Accept-Language": "ar,en;q=0.8",
        }
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
            while queue and len(seen_pages) < spec.max_pages:
                url, depth = queue.popleft()
                if url in seen_pages:
                    continue
                seen_pages.add(url)
                if not self.source_registry.is_https_allowed(url) or not spec.allows_page(url):
                    continue
                classification = self.source_registry.classify(url)
                if classification.source_id != spec.source_id:
                    continue
                try:
                    response = await client.get(url)
                    response.raise_for_status()
                except httpx.HTTPError as exc:
                    logger.info("Catalog landing page skipped url=%s reason=%s", url, exc)
                    continue

                final_url = str(response.url)
                content_type = response.headers.get("content-type", "").lower()
                if "pdf" in content_type or urlparse(final_url).path.lower().endswith(".pdf"):
                    if spec.allows_document(final_url) and self.source_registry.can_be_original_pdf_source(final_url):
                        pdfs.add(final_url)
                    continue
                if depth >= spec.max_depth:
                    continue

                body = html.unescape(response.text).replace("\\/", "/")
                links = set(re.findall(r'''href\s*=\s*["']([^"']+)["']''', body, flags=re.I))
                # SharePoint/JSON often embeds document URLs without href.
                links.update(
                    match.group(1)
                    for match in re.finditer(
                        r'''["']((?:https://[^"']+|/[^"']+?)\.pdf(?:\?[^"']*)?)["']''',
                        body,
                        flags=re.I,
                    )
                )
                for href in links:
                    absolute = urljoin(final_url, href.strip())
                    parsed = urlparse(absolute)
                    if parsed.scheme != "https":
                        continue
                    classification = self.source_registry.classify(absolute)
                    if classification.source_id != spec.source_id:
                        continue
                    is_pdf = parsed.path.lower().endswith(".pdf")
                    if is_pdf:
                        if spec.allows_document(absolute) and self.source_registry.can_be_original_pdf_source(absolute):
                            pdfs.add(absolute)
                    elif spec.allows_page(absolute):
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
        generation_id: str,
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
            page_texts = extract_pdf_page_texts(artifact.path)
            text_pages = sum(1 for text in page_texts if len(text.strip()) >= 40)
            starts = self._case_starts(page_texts)
            if not starts:
                await self.store.replace_collection(generation_id, document_id, [])
                logger.info(
                    "No primary judicial case boundaries detected url=%s pages=%d text_pages=%d",
                    url,
                    len(page_texts),
                    text_pages,
                )
                return 0, artifact.sha256

            parsed_cases: list[CatalogCase] = []
            for position, start_index in enumerate(starts):
                next_start = starts[position + 1] if position + 1 < len(starts) else len(page_texts)
                end_index = next_start

                while end_index - 1 > start_index and len(page_texts[end_index - 1].strip()) < 120:
                    end_index -= 1

                header = primary_judicial_header(page_texts[start_index])
                if header is None:
                    continue
                case_number = header.case_number
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

            indexed = await self.store.replace_collection(generation_id, document_id, parsed_cases)
            if indexed:
                logger.info(
                    "Indexed %d primary-header ranges generation=%s document=%s pages=%d text_pages=%d",
                    indexed,
                    generation_id,
                    url,
                    len(page_texts),
                    text_pages,
                )
            else:
                logger.info("No usable judgments remained after primary-header verification %s", url)
            return indexed, artifact.sha256
        finally:
            artifact.path.unlink(missing_ok=True)

    @staticmethod
    def _case_starts(page_texts: list[str]) -> list[int]:
        """Return physical pages that begin a high-confidence primary judgment."""
        starts: list[int] = []
        previous_case: str | None = None
        for index, text in enumerate(page_texts):
            if len(text) < 100:
                continue
            header = primary_judicial_header(text)
            if header is None:
                continue
            if header.case_number == previous_case:
                continue
            starts.append(index)
            previous_case = header.case_number
        return starts
