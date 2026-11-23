"""Agent (caller identity) management. Admin only. API keys are shown once."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.db.models import Agent
from app.db.session import get_session
from app.schemas import AgentCreate, agent_dict
from app.security.auth import generate_api_key, hash_api_key

router = APIRouter(prefix="/api/agents", tags=["agents"], dependencies=[Depends(require_admin)])


@router.get("")
async def list_agents(session: AsyncSession = Depends(get_session)) -> list[dict]:
    rows = (await session.execute(select(Agent).order_by(Agent.created_at))).scalars().all()
    return [agent_dict(a) for a in rows]


@router.post("", status_code=201)
async def create_agent(body: AgentCreate, session: AsyncSession = Depends(get_session)) -> dict:
    if await session.scalar(select(Agent).where(Agent.name == body.name)):
        raise HTTPException(status_code=409, detail="agent name already exists")
    api_key = generate_api_key()
    agent = Agent(name=body.name, api_key_hash=hash_api_key(api_key), meta=body.meta)
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    # The plaintext key is returned exactly once; only its hash is stored.
    return {**agent_dict(agent), "api_key": api_key}


@router.post("/{agent_id}/rotate")
async def rotate_key(agent_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> dict:
    agent = await session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")
    api_key = generate_api_key()
    agent.api_key_hash = hash_api_key(api_key)
    await session.commit()
    await session.refresh(agent)
    return {**agent_dict(agent), "api_key": api_key}


@router.patch("/{agent_id}")
async def set_enabled(
    agent_id: uuid.UUID, enabled: bool, session: AsyncSession = Depends(get_session)
) -> dict:
    agent = await session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")
    agent.enabled = enabled
    await session.commit()
    await session.refresh(agent)
    return agent_dict(agent)


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(agent_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> None:
    agent = await session.get(Agent, agent_id)
    if agent is not None:
        await session.delete(agent)
        await session.commit()
