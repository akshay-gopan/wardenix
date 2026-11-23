"""Wardenix gateway application factory and lifespan."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from sqlalchemy import func, select, text
from starlette.routing import Mount

from app.api.routers import agents as agents_router
from app.api.routers import approvals as approvals_router
from app.api.routers import audit as audit_router
from app.api.routers import auth as auth_router
from app.api.routers import policies as policies_router
from app.api.routers import servers as servers_router
from app.api.routers import users as users_router
from app.api.ws import WSHub
from app.approvals.manager import ApprovalManager
from app.audit.appender import AuditAppender
from app.config import get_settings
from app.db.models import User
from app.db.session import dispose_engine, get_sessionmaker
from app.enums import UserRole
from app.mcp_gateway.proxy import Gateway
from app.mcp_gateway.server import build_gateway_server
from app.mcp_gateway.upstream import UpstreamManager
from app.security.auth import decode_access_token, hash_password

logger = logging.getLogger("wardenix")


async def _bootstrap_admin() -> None:
    settings = get_settings()
    if not (settings.bootstrap_admin_email and settings.bootstrap_admin_password):
        return
    async with get_sessionmaker()() as session:
        if await session.scalar(select(func.count()).select_from(User)):
            return
        session.add(
            User(
                email=settings.bootstrap_admin_email,
                hashed_password=hash_password(settings.bootstrap_admin_password),
                role=UserRole.ADMIN.value,
            )
        )
        await session.commit()
        logger.info("Bootstrapped initial admin user %s", settings.bootstrap_admin_email)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level.upper())
    logger.info("Wardenix gateway starting up")
    # The Streamable HTTP session manager must be running while we serve /mcp.
    async with app.state.mcp_session_manager.run():
        await _bootstrap_admin()
        # Restart recovery: reconcile orphaned executions and expire stale approvals.
        await app.state.approvals.reconcile_orphaned_executions()
        await app.state.approvals.expire_stale()
        yield
    logger.info("Wardenix gateway shutting down")
    await app.state.upstream.aclose()
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Wardenix Gateway",
        version="0.1.0",
        summary="Runtime Security & Governance Platform for AI Agents",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- Data Plane wiring ---
    sessionmaker = get_sessionmaker()
    ws_hub = WSHub()
    upstream = UpstreamManager(settings)
    appender = AuditAppender(sessionmaker)
    manager = ApprovalManager(sessionmaker, settings, notifier=ws_hub.publish)
    gateway = Gateway(sessionmaker, upstream, appender, settings, manager)
    mcp_server = build_gateway_server(gateway)
    session_manager = StreamableHTTPSessionManager(app=mcp_server, json_response=True)

    app.state.settings = settings
    app.state.gateway = gateway
    app.state.upstream = upstream
    app.state.appender = appender
    app.state.approvals = manager
    app.state.ws_hub = ws_hub
    app.state.mcp_session_manager = session_manager

    async def handle_mcp(scope, receive, send) -> None:
        await session_manager.handle_request(scope, receive, send)

    app.router.routes.append(Mount("/mcp", app=handle_mcp))

    # --- Control Plane routers ---
    app.include_router(auth_router.router)
    app.include_router(users_router.router)
    app.include_router(agents_router.router)
    app.include_router(servers_router.router)
    app.include_router(policies_router.router)
    app.include_router(audit_router.router)
    app.include_router(approvals_router.router)

    @app.websocket("/ws")
    async def events_ws(websocket: WebSocket) -> None:
        # Browsers can't set headers on WS, so the token comes as a query param.
        token = websocket.query_params.get("token")
        try:
            decode_access_token(token) if token else None
            if not token:
                raise ValueError("missing token")
        except Exception:
            await websocket.close(code=4401)
            return
        await websocket.accept()
        queue = ws_hub.subscribe()
        # Initial snapshot so a (re)connecting dashboard reconciles from the DB.
        try:
            pending = await manager.list_pending()
            from app.approvals.manager import approval_to_dict

            await websocket.send_json(
                {"type": "snapshot", "pending": [approval_to_dict(p) for p in pending]}
            )
            while True:
                event = await queue.get()
                await websocket.send_json(event)
        except WebSocketDisconnect:
            pass
        finally:
            ws_hub.unsubscribe(queue)

    @app.get("/healthz", tags=["ops"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", tags=["ops"])
    async def readyz() -> dict[str, str]:
        try:
            async with get_sessionmaker()() as session:
                await session.execute(text("SELECT 1"))
            return {"status": "ready", "database": "ok"}
        except Exception as exc:  # pragma: no cover
            logger.warning("Readiness check failed: %s", exc)
            return {"status": "degraded", "database": "unavailable"}

    return app


app = create_app()
