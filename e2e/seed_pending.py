"""E2E global-setup helper: ensure an upstream + require_approval policy exist,
create a fresh agent, and make a real MCP call so a PENDING approval is waiting
for the Playwright browser flow to approve. Run with the backend venv python.
"""

from __future__ import annotations

import sys

import anyio
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

API = "http://localhost:8000"
MCP = "http://localhost:8000/mcp"
ADMIN = {"email": "admin@wardenix.local", "password": "changeme-admin"}


def setup() -> str:
    with httpx.Client(base_url=API, timeout=30) as c:
        token = c.post("/api/auth/login", json=ADMIN).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        servers = c.get("/api/servers", headers=h).json()
        if not any(s["name"] == "estdio" for s in servers):
            c.post(
                "/api/servers",
                headers=h,
                json={
                    "name": "estdio",
                    "transport": "stdio",
                    "command": "python",
                    "args": ["/app/tests/echo_stdio_server.py"],
                },
            )

        policies = c.get("/api/policies", headers=h).json()
        has_rule = any(
            r["action"] == "require_approval" and "echo" in (r["conditions"].get("tools") or [])
            for p in policies
            for r in (p.get("rules") or [])
        )
        if not has_rule:
            pid = c.post(
                "/api/policies", headers=h, json={"name": "e2e-approvals", "default_action": "deny"}
            )
            if pid.status_code == 409:
                pid_val = next(p["id"] for p in policies if p["name"] == "e2e-approvals")
            else:
                pid_val = pid.json()["id"]
            c.post(
                "/api/policies/rules",
                headers=h,
                json={
                    "policy_id": pid_val,
                    "action": "require_approval",
                    "priority": 1,
                    "conditions": {"tools": ["echo"]},
                },
            )

        import time

        key = c.post(
            "/api/agents", headers=h, json={"name": f"e2e-agent-{int(time.time())}"}
        ).json()["api_key"]
        return key


async def trigger(api_key: str) -> None:
    headers = {"Authorization": f"Bearer {api_key}"}
    async with httpx.AsyncClient(headers=headers, timeout=30) as hc:
        async with streamable_http_client(MCP, http_client=hc) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                res = await s.call_tool("estdio.echo", {"text": "e2e please review"})
                status = (res.structured_content or {}).get("status")
                if status != "approval_required":
                    print(f"UNEXPECTED: {status}", file=sys.stderr)
                    sys.exit(1)


def main() -> None:
    key = setup()
    anyio.run(trigger, key)
    print("SEEDED_PENDING")


if __name__ == "__main__":
    main()
