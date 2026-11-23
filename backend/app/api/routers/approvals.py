"""Approvals Control Plane: list pending, approve, deny (with attribution)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.deps import require_approver, require_viewer
from app.approvals.manager import approval_to_dict
from app.db.models import User

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


def _manager(request: Request):
    return request.app.state.approvals


@router.get("", dependencies=[Depends(require_viewer)])
async def list_pending(request: Request) -> list[dict]:
    rows = await _manager(request).list_pending()
    return [approval_to_dict(r) for r in rows]


@router.get("/{approval_id}", dependencies=[Depends(require_viewer)])
async def get_approval(approval_id: uuid.UUID, request: Request) -> dict:
    row = await _manager(request).get(approval_id)
    if row is None:
        raise HTTPException(status_code=404, detail="approval not found")
    return approval_to_dict(row)


@router.post("/{approval_id}/approve")
async def approve(
    approval_id: uuid.UUID, request: Request, user: User = Depends(require_approver)
) -> dict:
    row = await _manager(request).approve(approval_id, user_id=user.id)
    if row is None:
        raise HTTPException(status_code=409, detail="not pending (already decided or expired)")
    return approval_to_dict(row)


@router.post("/{approval_id}/deny")
async def deny(
    approval_id: uuid.UUID, request: Request, user: User = Depends(require_approver)
) -> dict:
    row = await _manager(request).deny(approval_id, user_id=user.id)
    if row is None:
        raise HTTPException(status_code=409, detail="not pending (already decided or expired)")
    return approval_to_dict(row)
