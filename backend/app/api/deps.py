"""Auth dependencies: JWT bearer → current user, and role gating.

Role hierarchy: admin > approver > viewer. ``admin`` implicitly satisfies any
requirement; ``approver`` satisfies approver/viewer; ``viewer`` is read-only.
"""

from __future__ import annotations

import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.db.session import get_session
from app.enums import UserRole
from app.security.auth import decode_access_token

_bearer = HTTPBearer(auto_error=False)

_RANK = {UserRole.VIEWER.value: 0, UserRole.APPROVER.value: 1, UserRole.ADMIN.value: 2}


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
) -> User:
    if creds is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")
    try:
        payload = decode_access_token(creds.credentials)
        user_id = uuid.UUID(payload["sub"])
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token"
        ) from exc
    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="unknown or inactive user"
        )
    return user


def require_role(minimum: UserRole):
    """Dependency factory enforcing a minimum role."""

    async def _dep(user: User = Depends(get_current_user)) -> User:
        if _RANK.get(user.role, -1) < _RANK[minimum.value]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"requires {minimum.value} role or higher",
            )
        return user

    return _dep


require_viewer = require_role(UserRole.VIEWER)
require_approver = require_role(UserRole.APPROVER)
require_admin = require_role(UserRole.ADMIN)
