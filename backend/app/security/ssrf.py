"""SSRF / DNS-rebinding guard for outbound HTTP upstream connections.

Upstream servers are operator-registered (not agent-controlled), so this is
defense-in-depth: it keeps a misconfigured or malicious server entry from
turning the gateway into a proxy to internal infrastructure or the cloud
metadata endpoint. Cloud metadata / link-local / multicast / reserved ranges
are *always* blocked; loopback and private ranges are blocked unless explicitly
permitted (dev default allows private so same-host Docker upstreams work).
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


class SsrfError(ValueError):
    """Raised when an upstream URL fails SSRF validation."""


_ALWAYS_BLOCK_METADATA = ipaddress.ip_address("169.254.169.254")


def _ip_always_blocked(ip: ipaddress._BaseAddress) -> bool:
    return (
        ip == _ALWAYS_BLOCK_METADATA
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _resolve_ips(host: str) -> list[ipaddress._BaseAddress]:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise SsrfError(f"cannot resolve upstream host {host!r}: {exc}") from exc
    ips: list[ipaddress._BaseAddress] = []
    seen: set[str] = set()
    for info in infos:
        addr = info[4][0]
        if addr in seen:
            continue
        seen.add(addr)
        try:
            ips.append(ipaddress.ip_address(addr))
        except ValueError:
            continue
    if not ips:
        raise SsrfError(f"upstream host {host!r} resolved to no usable address")
    return ips


def validate_http_url(
    url: str,
    *,
    allowlist: list[str] | None = None,
    allow_private: bool = True,
) -> list[str]:
    """Validate an upstream HTTP(S) URL. Returns the resolved IPs (as strings).

    Raises :class:`SsrfError` on any violation (fail-closed).
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise SsrfError(f"unsupported scheme {parsed.scheme!r} (http/https only)")
    host = parsed.hostname
    if not host:
        raise SsrfError("upstream URL has no host")

    if allowlist:
        port = parsed.port
        candidates = {host}
        if port is not None:
            candidates.add(f"{host}:{port}")
        if not (candidates & set(allowlist)):
            raise SsrfError(f"upstream host {host!r} is not in the SSRF allowlist")

    host_allowlisted = bool(allowlist) and host in set(allowlist or [])

    resolved: list[str] = []
    for ip in _resolve_ips(host):
        if _ip_always_blocked(ip):
            raise SsrfError(f"upstream resolves to a blocked address: {ip}")
        if (ip.is_loopback or ip.is_private) and not (allow_private or host_allowlisted):
            raise SsrfError(f"upstream resolves to a private/loopback address: {ip}")
        resolved.append(str(ip))
    return resolved
