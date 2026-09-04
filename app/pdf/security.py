"""Network safety checks for remote PDF acquisition."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

from app.sources import SourceRegistry

from .errors import PdfSecurityError


async def validate_pdf_url(url: str, source_registry: SourceRegistry) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise PdfSecurityError("PDF URL must use HTTPS")
    if not parsed.hostname:
        raise PdfSecurityError("PDF URL has no hostname")
    if parsed.username or parsed.password:
        raise PdfSecurityError("Credentials in PDF URLs are not allowed")
    if parsed.port not in (None, 443):
        raise PdfSecurityError("Non-standard remote ports are not allowed")
    if not source_registry.can_be_original_pdf_source(url):
        raise PdfSecurityError("PDF URL is not on an approved official source")

    host = parsed.hostname
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        _reject_unsafe_ip(literal)

    addresses = await asyncio.to_thread(_resolve_host, host)
    if not addresses:
        raise PdfSecurityError("PDF hostname did not resolve")
    for address in addresses:
        _reject_unsafe_ip(ipaddress.ip_address(address))


def _resolve_host(host: str) -> set[str]:
    results = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    return {item[4][0].split("%", 1)[0] for item in results}


def _reject_unsafe_ip(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    if (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    ):
        raise PdfSecurityError(f"Unsafe network address: {address}")
