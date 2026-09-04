from pathlib import Path

import httpx
import pytest

from app.pdf.acquisition import PdfAcquisitionService
from app.pdf.errors import PdfAcquisitionError
from app.sources import SourceRegistry


class TimeoutClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def build_request(self, method: str, url: str, headers=None):
        return httpx.Request(method, url, headers=headers)

    async def send(self, request: httpx.Request, stream: bool = False):
        raise httpx.ConnectTimeout("fixture timeout", request=request)


@pytest.mark.asyncio
async def test_pdf_connect_timeout_is_wrapped_as_acquisition_error(
    tmp_path: Path, monkeypatch
) -> None:
    async def allow_url(url, source_registry):
        return None

    monkeypatch.setattr("app.pdf.acquisition.validate_pdf_url", allow_url)
    monkeypatch.setattr("app.pdf.acquisition.httpx.AsyncClient", TimeoutClient)

    service = PdfAcquisitionService(
        source_registry=SourceRegistry(),
        temp_dir=tmp_path,
        max_bytes=1024 * 1024,
        max_pages=20,
        timeout_seconds=30,
        connect_timeout_seconds=5,
        max_redirects=2,
    )

    with pytest.raises(PdfAcquisitionError, match="timed out"):
        await service.acquire("https://www.moj.gov.sa/case.pdf")
