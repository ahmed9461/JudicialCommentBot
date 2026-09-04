"""Download original PDFs from approved official sources without rewriting them."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

import httpx

from app.sources import SourceRegistry

from .errors import PdfAcquisitionError, PdfValidationError
from .security import validate_pdf_url
from .validation import validate_pdf_file


@dataclass(frozen=True, slots=True)
class PdfArtifact:
    path: Path
    source_url: str
    sha256: str
    size_bytes: int
    page_count: int


class PdfAcquisitionService:
    def __init__(
        self,
        *,
        source_registry: SourceRegistry,
        temp_dir: str | Path,
        max_bytes: int,
        max_pages: int,
        timeout_seconds: float,
        max_redirects: int,
        connect_timeout_seconds: float | None = None,
    ) -> None:
        self.source_registry = source_registry
        self.temp_dir = Path(temp_dir)
        self.max_bytes = max_bytes
        self.max_pages = max_pages
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self.connect_timeout_seconds = max(
            1.0,
            float(connect_timeout_seconds if connect_timeout_seconds is not None else min(10.0, self.timeout_seconds)),
        )
        self.max_redirects = max_redirects
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    async def acquire(self, url: str, *, suggested_name: str = "case") -> PdfArtifact:
        current_url = url
        timeout = httpx.Timeout(
            self.timeout_seconds,
            connect=min(self.connect_timeout_seconds, self.timeout_seconds),
        )
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            for redirect_count in range(self.max_redirects + 1):
                await validate_pdf_url(current_url, self.source_registry)
                request = client.build_request(
                    "GET",
                    current_url,
                    headers={
                        "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.1",
                        "User-Agent": "JudicialCommentBot/1.0 (+official PDF acquisition)",
                    },
                )
                try:
                    response = await client.send(request, stream=True)
                except httpx.TimeoutException as exc:
                    raise PdfAcquisitionError(
                        f"Official PDF source timed out while connecting/downloading: {current_url}"
                    ) from exc
                except httpx.RequestError as exc:
                    raise PdfAcquisitionError(
                        f"Official PDF source network error: {current_url} ({type(exc).__name__})"
                    ) from exc
                try:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            raise PdfAcquisitionError("Redirect response has no Location header")
                        if redirect_count >= self.max_redirects:
                            raise PdfAcquisitionError("Too many PDF redirects")
                        current_url = urljoin(current_url, location)
                        continue
                    if response.status_code >= 400:
                        raise PdfAcquisitionError(
                            f"PDF download returned HTTP {response.status_code}"
                        )
                    return await self._save_response(response, current_url, suggested_name)
                except httpx.TimeoutException as exc:
                    raise PdfAcquisitionError(
                        f"Official PDF source timed out while streaming: {current_url}"
                    ) from exc
                except httpx.RequestError as exc:
                    raise PdfAcquisitionError(
                        f"Official PDF source failed while streaming: {current_url} ({type(exc).__name__})"
                    ) from exc
                finally:
                    await response.aclose()
        raise PdfAcquisitionError("PDF redirect loop")

    async def _save_response(
        self,
        response: httpx.Response,
        source_url: str,
        suggested_name: str,
    ) -> PdfArtifact:
        filename = _safe_filename(suggested_name)
        fd, raw_path = tempfile.mkstemp(
            prefix=f"{filename}-", suffix=".pdf", dir=self.temp_dir
        )
        os.close(fd)
        path = Path(raw_path)
        digest = hashlib.sha256()
        size = 0
        first = b""
        try:
            with path.open("wb") as handle:
                async for chunk in response.aiter_bytes(64 * 1024):
                    if not chunk:
                        continue
                    if not first:
                        first = chunk[:5]
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise PdfValidationError("PDF exceeds configured byte limit")
                    digest.update(chunk)
                    handle.write(chunk)
            if first != b"%PDF-":
                raise PdfValidationError("Downloaded resource is not a PDF")
            page_count = validate_pdf_file(path, max_pages=self.max_pages)
            return PdfArtifact(
                path=path,
                source_url=source_url,
                sha256=digest.hexdigest(),
                size_bytes=size,
                page_count=page_count,
            )
        except Exception:
            path.unlink(missing_ok=True)
            raise


def _safe_filename(value: str) -> str:
    value = re.sub(r"[^\w\-\u0600-\u06FF]+", "-", value, flags=re.UNICODE)
    value = value.strip("-_")[:80]
    return value or "case"
