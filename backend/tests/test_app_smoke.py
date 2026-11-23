"""Import/wiring smoke tests — catch transport-layer breakage the pipeline tests
miss (they call the gateway directly and never import the MCP server / app)."""

from __future__ import annotations

from mcp import MCPError


def test_build_gateway_server_and_app_import(seeded):
    from app.mcp_gateway.server import build_gateway_server

    server = build_gateway_server(seeded.gateway)
    assert server is not None


def test_create_app_mounts_mcp_endpoint():
    from app.main import create_app

    app = create_app()
    # /mcp is a Mount on the top-level router
    assert any(getattr(r, "path", None) == "/mcp" for r in app.router.routes)
    # audit verify endpoint is registered (shows up in the OpenAPI path table)
    assert "/api/audit/verify" in app.openapi()["paths"]


def test_mcp_error_constructs():
    err = MCPError(-32001, "unauthenticated")
    assert err is not None
