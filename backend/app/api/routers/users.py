"""User management (admin only)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.db.models import User
from app.db.session import get_session
from app.schemas import UserCreate, UserUpdate, user_dict
from app.security.auth import hash_password

router = APIRouter(prefix="/api/users", tags=["users"], dependencies=[Depends(require_admin)])


@router.get("")
async def list_users(session: AsyncSession = Depends(get_session)) -> list[dict]:
    rows = (await session.execute(select(User).order_by(User.created_at))).scalars().all()
    return [user_dict(u) for u in rows]


@router.post("", status_code=201)
async def create_user(body: UserCreate, session: AsyncSession = Depends(get_session)) -> dict:
    if await session.scalar(select(User).where(User.email == body.email)):
        raise HTTPException(status_code=409, detail="email already exists")
    user = User(
        email=body.email, hashed_password=hash_password(body.password), role=body.role.value
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user_dict(user)


@router.patch("/{user_id}")
async def update_user(
    user_id: uuid.UUID, body: UserUpdate, session: AsyncSession = Depends(get_session)
) -> dict:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    if body.role is not None:
        user.role = body.role.value
    if body.is_active is not None:
        user.is_active = body.is_active
    if body.password is not None:
        user.hashed_password = hash_password(body.password)
    await session.commit()
    await session.refresh(user)
    return user_dict(user)


@router.delete("/{user_id}", status_code=204)
async def delete_user(user_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> None:
    user = await session.get(User, user_id)
    if user is not None:
        await session.delete(user)
        await session.commit()
