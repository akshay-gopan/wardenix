"""SSRF guard unit tests (pure function, no network/DNS — IP-literal URLs)."""

from __future__ import annotations

import pytest

from app.security.ssrf import SsrfError, validate_http_url


def test_metadata_ip_always_blocked():
    with pytest.raises(SsrfError):
        validate_http_url("http://169.254.169.254/latest/meta-data/", allow_private=True)


def test_link_local_blocked():
    with pytest.raises(SsrfError):
        validate_http_url("http://169.254.1.1/", allow_private=True)


def test_private_blocked_when_private_disallowed():
    with pytest.raises(SsrfError):
        validate_http_url("http://10.0.0.5:9000/mcp", allow_private=False)


def test_private_allowed_when_permitted():
    ips = validate_http_url("http://10.0.0.5:9000/mcp", allow_private=True)
    assert ips == ["10.0.0.5"]


def test_allowlist_mismatch_rejected():
    with pytest.raises(SsrfError):
        validate_http_url(
            "http://10.0.0.5/mcp", allowlist=["tools.internal"], allow_private=True
        )


def test_allowlist_match_allows_private():
    ips = validate_http_url(
        "http://10.0.0.5/mcp", allowlist=["10.0.0.5"], allow_private=False
    )
    assert ips == ["10.0.0.5"]


def test_bad_scheme_rejected():
    with pytest.raises(SsrfError):
        validate_http_url("ftp://example.com/x")


def test_public_ip_allowed():
    ips = validate_http_url("http://8.8.8.8/mcp", allow_private=False)
    assert ips == ["8.8.8.8"]
