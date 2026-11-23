"""Control Plane API: auth, RBAC gating, and approver attribution."""

from __future__ import annotations

import httpx
import pytest_asyncio
from asgi_lifespan import LifespanManager

from app.db.models import Agent, ApprovalRequest, MCPServer
from app.enums import ApprovalStatus, Transport
from app.main import create_app

ADMIN = {"email": "admin@wardenix.local", "password": "changeme-admin"}


@pytest_asyncio.fixture
async def api(sessionmaker):
    app = create_app()
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            client.app = app  # type: ignore[attr-defined]
            client.sessionmaker = sessionmaker  # type: ignore[attr-defined]
            yield client


async def _token(client, email=ADMIN["email"], password=ADMIN["password"]) -> str:
    r = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def test_login_and_me(api):
    token = await _token(api)
    me = await api.get("/api/auth/me", headers=_auth(token))
    assert me.status_code == 200
    assert me.json()["role"] == "admin"


async def test_login_bad_password(api):
    r = await api.post("/api/auth/login", json={"email": ADMIN["email"], "password": "nope"})
    assert r.status_code == 401


async def test_unauthenticated_rejected(api):
    assert (await api.get("/api/users")).status_code == 401
    assert (await api.get("/api/policies")).status_code == 401


async def test_role_gating(api):
    admin_token = await _token(api)
    # admin creates a viewer user
    r = await api.post(
        "/api/users",
        headers=_auth(admin_token),
        json={"email": "viewer@x.com", "password": "viewerpass1", "role": "viewer"},
    )
    assert r.status_code == 201
    viewer_token = await _token(api, "viewer@x.com", "viewerpass1")

    # viewer can read policies...
    assert (await api.get("/api/policies", headers=_auth(viewer_token))).status_code == 200
    # ...but cannot create one (admin-only) -> 403
    r = await api.post(
        "/api/policies", headers=_auth(viewer_token), json={"name": "p1"}
    )
    assert r.status_code == 403
    # admin can
    r = await api.post("/api/policies", headers=_auth(admin_token), json={"name": "p1"})
    assert r.status_code == 201


async def test_agent_key_shown_once(api):
    token = await _token(api)
    r = await api.post("/api/agents", headers=_auth(token), json={"name": "a1"})
    assert r.status_code == 201
    body = r.json()
    assert body["api_key"].startswith("wrdx_")
    # listing never includes the key
    lst = (await api.get("/api/agents", headers=_auth(token))).json()
    assert "api_key" not in lst[0]


async def test_rule_bad_regex_rejected(api):
    token = await _token(api)
    pol = (await api.post("/api/policies", headers=_auth(token), json={"name": "pr"})).json()
    r = await api.post(
        "/api/policies/rules",
        headers=_auth(token),
        json={
            "policy_id": pol["id"],
            "action": "deny",
            "conditions": {"args": [{"key": "p", "op": "regex", "value": "(unclosed"}]},
        },
    )
    assert r.status_code == 400
    assert "regex" in r.json()["detail"]


async def test_approval_attribution_and_gating(api):
    admin_token = await _token(api)
    # viewer cannot approve
    await api.post(
        "/api/users",
        headers=_auth(admin_token),
        json={"email": "v2@x.com", "password": "viewerpass1", "role": "viewer"},
    )
    viewer_token = await _token(api, "v2@x.com", "viewerpass1")

    # seed an agent, server, and a pending approval directly
    async with api.sessionmaker() as s:
        agent = Agent(name="att-agent", api_key_hash="h")
        server = MCPServer(name="att-srv", transport=Transport.STDIO.value, command="x")
        s.add_all([agent, server])
        await s.commit()
        await s.refresh(agent)
        await s.refresh(server)
        ar = ApprovalRequest(
            agent_id=agent.id, server_id=server.id, tool="echo", args_hash="h",
            status=ApprovalStatus.PENDING.value,
            expires_at=__import__("datetime").datetime.now(__import__("datetime").UTC)
            + __import__("datetime").timedelta(hours=1),
        )
        s.add(ar)
        await s.commit()
        await s.refresh(ar)
        approval_id = ar.id

    # viewer forbidden
    r = await api.post(f"/api/approvals/{approval_id}/approve", headers=_auth(viewer_token))
    assert r.status_code == 403

    # admin (>= approver) approves -> attribution recorded
    r = await api.post(f"/api/approvals/{approval_id}/approve", headers=_auth(admin_token))
    assert r.status_code == 200
    assert r.json()["status"] == "approved"

    async with api.sessionmaker() as s:
        row = await s.get(ApprovalRequest, approval_id)
    assert row.decided_by is not None
    assert row.decided_at is not None
