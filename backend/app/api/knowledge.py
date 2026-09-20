"""Knowledge base ingestion + listing endpoints."""
from __future__ import annotations

import json

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db import get_db
from app.models.db_models import KnowledgeChunk, UploadedFile

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

RUN_QUEUE = "run_jobs"


class IngestRequest(BaseModel):
    file_id: str
    workspace: str | None = None


@router.post("/ingest")
async def ingest(body: IngestRequest, db: AsyncSession = Depends(get_db)) -> dict:
    f = await db.get(UploadedFile, body.file_id)
    if not f:
        raise HTTPException(status_code=404, detail="File not found")

    redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        await redis.rpush(RUN_QUEUE, json.dumps({
            "task_type": "knowledge_ingest",
            "file_id": body.file_id,
            "file_path": f.local_path,
            "mime_type": f.mime_type,
            "original_filename": f.original_filename,
            "workspace": body.workspace,
        }))
    finally:
        await redis.aclose()

    return {"status": "queued", "file_id": body.file_id, "filename": f.original_filename}


@router.get("/sources")
async def list_sources(workspace: str | None = None,
                       db: AsyncSession = Depends(get_db)) -> list[dict]:
    """Which documents are currently in the local knowledge base, and how many chunks."""
    result = await db.execute(
        select(
            KnowledgeChunk.source_file,
            KnowledgeChunk.source_hash,
            func.count(KnowledgeChunk.id).label("chunk_count"),
            func.max(KnowledgeChunk.created_at).label("ingested_at"),
        ).where(KnowledgeChunk.workspace == workspace)
        .group_by(KnowledgeChunk.source_file, KnowledgeChunk.source_hash)
    )
    return [
        {
            "source_file": row.source_file,
            "source_hash": row.source_hash,
            "chunk_count": row.chunk_count,
            "ingested_at": row.ingested_at.isoformat() if row.ingested_at else None,
        }
        for row in result.all()
    ]
