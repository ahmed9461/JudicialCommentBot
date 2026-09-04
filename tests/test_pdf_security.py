import pytest

from app.pdf.errors import PdfSecurityError
from app.pdf.security import validate_pdf_url
from app.sources import SourceRegistry


@pytest.mark.asyncio
async def test_http_pdf_url_is_rejected_before_dns() -> None:
    with pytest.raises(PdfSecurityError, match="HTTPS"):
        await validate_pdf_url("http://www.moj.gov.sa/file.pdf", SourceRegistry())


@pytest.mark.asyncio
async def test_unapproved_domain_is_rejected_before_dns() -> None:
    with pytest.raises(PdfSecurityError, match="approved official"):
        await validate_pdf_url("https://example.com/file.pdf", SourceRegistry())
