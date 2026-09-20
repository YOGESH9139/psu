"""Workspaces: a named area with its own reference library and starter tasks."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.db_models import Workspace

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])

BANNERS = {"PUBLIC", "INTERNAL", "RESTRICTED", "CONFIDENTIAL"}


class WorkspaceCreate(BaseModel):
    name: str
    template: str = "blank"
    banner: str = "INTERNAL"


def _out(w: Workspace) -> dict:
    return {
        "id": w.id,
        "name": w.name,
        "template": w.template,
        "banner": w.banner,
        "created_at": w.created_at.isoformat() if w.created_at else None,
    }


@router.get("")
async def list_workspaces(db: AsyncSession = Depends(get_db)) -> list[dict]:
    rows = (await db.execute(select(Workspace).order_by(Workspace.created_at))).scalars().all()
    return [_out(w) for w in rows]


@router.post("")
async def create_workspace(body: WorkspaceCreate, db: AsyncSession = Depends(get_db)) -> dict:
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Give the workspace a name")
    banner = body.banner.upper() if body.banner.upper() in BANNERS else "INTERNAL"
    w = Workspace(name=name[:128], template=body.template[:64], banner=banner)
    db.add(w)
    await db.commit()
    await db.refresh(w)
    return _out(w)
