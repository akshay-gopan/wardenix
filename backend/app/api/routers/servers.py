"""Upstream MCP server management. Read: viewer+. Write/test: admin."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin, require_viewer
from app.db.models import MCPServer
from app.db.session import get_session
from app.mcp_gateway.errors import GatewayError
from app.schemas import ServerCreate, ServerUpdate, server_dict

router = APIRouter(prefix="/api/servers", tags=["servers"])


@router.get("", dependencies=[Depends(require_viewer)])
async def list_servers(session: AsyncSession = Depends(get_session)) -> list[dict]:
    rows = (await session.execute(select(MCPServer).order_by(MCPServer.created_at))).scalars().all()
    return [server_dict(s) for s in rows]


@router.post("", status_code=201, dependencies=[Depends(require_admin)])
async def create_server(body: ServerCreate, session: AsyncSession = Depends(get_session)) -> dict:
    if await session.scalar(select(MCPServer).where(MCPServer.name == body.name)):
        raise HTTPException(status_code=409, detail="server name already exists")
    server = MCPServer(
        name=body.name,
        transport=body.transport.value,
        command=body.command,
        args=body.args,
        env=body.env,
        url=body.url,
        headers=body.headers,
        tags=body.tags,
        enabled=body.enabled,
    )
    session.add(server)
    await session.commit()
    await session.refresh(server)
    return server_dict(server)


@router.patch("/{server_id}", dependencies=[Depends(require_admin)])
async def update_server(
    server_id: uuid.UUID, body: ServerUpdate, session: AsyncSession = Depends(get_session)
) -> dict:
    server = await session.get(MCPServer, server_id)
    if server is None:
        raise HTTPException(status_code=404, detail="server not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(server, field, value)
    await session.commit()
    await session.refresh(server)
    return server_dict(server)


@router.delete("/{server_id}", status_code=204, dependencies=[Depends(require_admin)])
async def delete_server(server_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> None:
    server = await session.get(MCPServer, server_id)
    if server is not None:
        await session.delete(server)
        await session.commit()


@router.post("/{server_id}/test", dependencies=[Depends(require_admin)])
async def test_server(
    server_id: uuid.UUID, request: Request, session: AsyncSession = Depends(get_session)
) -> dict:
    server = await session.get(MCPServer, server_id)
    if server is None:
        raise HTTPException(status_code=404, detail="server not found")
    upstream = request.app.state.upstream
    try:
        tools = await upstream.list_tools(server)
        server.health = "healthy"
        await session.commit()
        return {"ok": True, "tools": [t.name for t in tools]}
    except GatewayError as exc:
        server.health = "unhealthy"
        await session.commit()
        return {"ok": False, "error": exc.public_message}
