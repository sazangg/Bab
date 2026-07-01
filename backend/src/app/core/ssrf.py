"""SSRF protection for outbound, operator-configured upstream URLs.

Provider ``base_url`` values are admin-controlled, and the gateway issues server-side
requests to them. In a multi-tenant deployment a tenant admin must not be able to point
the backend at internal services, cloud metadata endpoints, or loopback. These helpers
resolve a host and reject any address that is not publicly routable.
"""

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse


class SsrfValidationError(ValueError):
    """Raised when a URL targets a non-public / disallowed network address."""


def _is_disallowed_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        # If it cannot be parsed as an IP, treat it as disallowed (fail closed).
        return True
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local  # includes 169.254.0.0/16 (cloud metadata) and fe80::/10
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def _resolve_host(host: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise SsrfValidationError(f"could not resolve host: {host}") from exc
    return [info[4][0] for info in infos]


def assert_public_url(url: str) -> None:
    """Validate a URL targets a public host. Raises SsrfValidationError otherwise.

    Synchronous (does DNS); call at configuration time. Use ``assert_public_url_async``
    on the request hot path.
    """
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise SsrfValidationError("url scheme must be http or https")
    host = parsed.hostname
    if not host:
        raise SsrfValidationError("url must include a host")
    # A literal IP host is checked directly; a name is resolved and every A/AAAA
    # record must be public (defends against split-horizon and multi-record tricks).
    addresses = [host] if _looks_like_ip(host) else _resolve_host(host)
    for address in addresses:
        if _is_disallowed_ip(address):
            raise SsrfValidationError(f"host '{host}' resolves to a non-public address ({address})")


async def assert_public_url_async(url: str) -> None:
    await asyncio.to_thread(assert_public_url, url)


def _looks_like_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


async def resolve_public_addresses(host: str) -> list[str]:
    addresses = [host] if _looks_like_ip(host) else await asyncio.to_thread(_resolve_host, host)
    if not addresses:
        raise SsrfValidationError(f"could not resolve host: {host}")
    normalized = [_normalize_ip_address(address) for address in addresses]
    for address in normalized:
        if _is_disallowed_ip(address):
            raise SsrfValidationError("host resolves to a non-public address")
    return normalized


def _normalize_ip_address(value: str) -> str:
    address = ipaddress.ip_address(value)
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return str(address)
