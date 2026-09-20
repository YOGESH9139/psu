"""Runs endpoints — create, status, SSE events, artifacts, approval."""
from __future__ import annotations

import json
from pathlib import Path
from typing import AsyncIterator

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.core.config import settings
from app.db import get_db
from app.models.db_models import (
    ApprovalDecision,
    ApprovalRecord,
    Artifact,
    AuditEvent,
    Run,
    RunStatus,
    UploadedFile,
)
from app.services.artifact_preview import preview_artifact
from app.services.model_registry import registry
from app.services.model_router import route, route_followup

router = APIRouter(prefix="/api/runs", tags=["runs"])

RUN_QUEUE = "run_jobs"


# ─── Pydantic schemas ─────────────────────────────────────────────────────────

class CreateRunRequest(BaseModel):
    goal: str
    file_ids: list[str] = []
    workspace: str | None = None
    parent_run_id: str | None = None
    model: str | None = None   # None = Automatic: the router picks


class RunResponse(BaseModel):
    run_id: str
    status: str
    goal: str
    task_class: str | None = None
    model_id: str | None = None
    router_decision: dict | None = None
    error_message: str | None = None
    workspace: str | None = None
    parent_run_id: str | None = None
    created_at: str


class ApprovalRequest(BaseModel):
    decision: ApprovalDecision
    note: str = ""


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _redis() -> aioredis.Redis:
    return aioredis.from_url(settings.redis_url, decode_responses=True)


async def _get_run_or_404(run_id: str, db: AsyncSession) -> Run:
    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


def _to_response(run: Run) -> RunResponse:
    return RunResponse(
        run_id=run.id,
        status=run.status.value if hasattr(run.status, "value") else str(run.status),
        goal=run.goal,
        task_class=run.task_class,
        model_id=run.model_id,
        router_decision=run.router_decision,
        error_message=run.error_message,
        workspace=run.workspace,
        parent_run_id=run.parent_run_id,
        created_at=run.created_at.isoformat(),
    )


def _context_from_parent(parent: Run) -> str:
    """Compact text of what the earlier turn produced, for the follow-up to use."""
    result = parent.result or {}
    parts = [f"Earlier request: {parent.goal}"]
    if result.get("answer"):
        parts.append(f"Earlier answer: {result['answer']}")
    for f in (result.get("findings") or [])[:6]:
        parts.append(f"Earlier finding: {f.get('item')}: {f.get('detail')}")
    rows = result.get("matched_rows") or []
    if rows:
        parts.append("Earlier matching rows: " + "; ".join(
            ", ".join(f"{k}={v}" for k, v in r.items()) for r in rows[:12]))
    return chr(10).join(parts)[:3500]


# ─── Routes ──────────────────────────────────────────────────────────────────

@router.post("", response_model=RunResponse)
async def create_run(
    body: CreateRunRequest, db: AsyncSession = Depends(get_db)
) -> RunResponse:
    if not body.goal.strip():
        raise HTTPException(status_code=422, detail="Goal must not be empty")

    # A follow-up continues an earlier run: same workspace, same files unless new
    # ones are attached, and the earlier result handed over as context.
    parent: Run | None = None
    context = ""
    file_ids = list(body.file_ids)
    workspace = body.workspace
    if body.parent_run_id:
        parent = await db.get(Run, body.parent_run_id)
        if parent is None:
            raise HTTPException(status_code=404, detail="Unknown parent run")
        workspace = workspace or parent.workspace
        if not file_ids:
            file_ids = list(parent.file_ids or [])
        context = _context_from_parent(parent)

    # Collect MIME types / names from uploaded files so the router can see them.
    files: list[UploadedFile] = []
    for fid in file_ids:
        f = await db.get(UploadedFile, fid)
        if not f:
            raise HTTPException(status_code=404, detail=f"Unknown file_id: {fid}")
        files.append(f)

    router_fn = route_followup if parent is not None else route
    decision = router_fn(
        body.goal,
        [f.mime_type for f in files],
        [f.original_filename for f in files],
    )
    decision_dict = decision.to_dict()

    # Automatic is the default. A person may instead pin a specific local model.
    if body.model:
        chosen = registry.get_model(body.model)
        if chosen is None:
            raise HTTPException(status_code=422, detail=f"Unknown model: {body.model}")
        signals = list(decision_dict.get("matched_signals", [])) + ["manual: model chosen by user"]
        decision_dict.update(
            model_id=chosen.id, modelId=chosen.id, manual=True,
            matched_signals=signals, matchedSignals=signals,
        )

    run = Run(
        goal=body.goal,
        task_class=decision_dict["task_class"],
        model_id=decision_dict["model_id"],
        router_decision=decision_dict,
        file_ids=file_ids,
        workspace=workspace,
        parent_run_id=body.parent_run_id,
        status=RunStatus.queued,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    # Enqueue to the worker. The worker resolves file_ids -> workspace paths itself.
    redis = _redis()
    try:
        await redis.rpush(RUN_QUEUE, json.dumps({
            "task_type": "run",
            "run_id": run.id,
            "goal": run.goal,
            "file_ids": run.file_ids or [],
            "workspace": run.workspace,
            "context": context,
            "model_override": body.model,
        }))
    finally:
        await redis.aclose()

    return _to_response(run)


@router.get("", response_model=list[RunResponse])
async def list_runs(limit: int = 20, db: AsyncSession = Depends(get_db)) -> list[RunResponse]:
    result = await db.execute(select(Run).order_by(Run.created_at.desc()).limit(limit))
    return [_to_response(r) for r in result.scalars().all()]


@router.get("/{run_id}", response_model=RunResponse)
async def get_run(run_id: str, db: AsyncSession = Depends(get_db)) -> RunResponse:
    return _to_response(await _get_run_or_404(run_id, db))


@router.get("/{run_id}/events")
async def stream_events(run_id: str, db: AsyncSession = Depends(get_db)) -> EventSourceResponse:
    """SSE stream. The worker publishes to `run:{run_id}:events` and mirrors every
    event into the `run:{run_id}:event_log` list so late subscribers can catch up."""
    await _get_run_or_404(run_id, db)

    async def generator() -> AsyncIterator[dict]:
        redis = _redis()
        channel = f"run:{run_id}:events"
        log_key = f"run:{run_id}:event_log"
        pubsub = redis.pubsub()
        # Subscribe FIRST, then replay the log, so nothing is lost in the gap.
        await pubsub.subscribe(channel)
        try:
            replayed = await redis.lrange(log_key, 0, -1)
            seen: set[str] = set()
            terminal = False
            for raw in replayed:
                seen.add(raw)
                yield {"data": raw}
                if json.loads(raw).get("type") in ("run_complete", "run_error"):
                    terminal = True
            if terminal:
                return

            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                raw = message["data"]
                if raw in seen:
                    seen.discard(raw)  # already delivered during replay
                    continue
                yield {"data": raw}
                if json.loads(raw).get("type") in ("run_complete", "run_error"):
                    break
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()
            await redis.aclose()

    return EventSourceResponse(generator())


@router.get("/{run_id}/artifacts")
async def list_artifacts(run_id: str, db: AsyncSession = Depends(get_db)) -> list[dict]:
    result = await db.execute(select(Artifact).where(Artifact.run_id == run_id))
    return [
        {
            "artifact_id": a.id,
            "filename": a.filename,
            "mime_type": a.mime_type,
            "size_bytes": a.size_bytes,
            "sha256": a.sha256,
            "download_url": f"/api/runs/{run_id}/artifacts/{a.id}/download",
            "preview_url": f"/api/runs/{run_id}/artifacts/{a.id}/preview",
        }
        for a in result.scalars().all()
    ]


@router.get("/{run_id}/audit")
async def run_audit(run_id: str, db: AsyncSession = Depends(get_db)) -> list[dict]:
    result = await db.execute(
        select(AuditEvent)
        .where(AuditEvent.run_id == run_id)
        .order_by(AuditEvent.created_at.asc())
    )
    return [
        {
            "id": e.id,
            "event_type": e.event_type,
            "actor": e.actor,
            "model_id": e.model_id,
            "tool_name": e.tool_name,
            "sanitized_args": e.sanitized_args,
            "result_hash": e.result_hash,
            "approval_decision": e.approval_decision,
            "blocked_tool_attempt": e.blocked_tool_attempt,
            "created_at": e.created_at.isoformat(),
        }
        for e in result.scalars().all()
    ]


@router.get("/{run_id}/artifacts/{artifact_id}/download")
async def download_artifact(
    run_id: str, artifact_id: str, db: AsyncSession = Depends(get_db)
) -> FileResponse:
    artifact = await db.get(Artifact, artifact_id)
    if not artifact or artifact.run_id != run_id:
        raise HTTPException(status_code=404, detail="Artifact not found")
    path = Path(artifact.local_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Artifact file missing on disk")
    return FileResponse(path, filename=artifact.filename, media_type=artifact.mime_type)


@router.get("/{run_id}/artifacts/{artifact_id}/preview")
async def preview_artifact_route(
    run_id: str, artifact_id: str, db: AsyncSession = Depends(get_db)
) -> dict:
    """Structured content of a deliverable, so a reviewer can read what they are
    approving without leaving the workbench."""
    artifact = await db.get(Artifact, artifact_id)
    if not artifact or artifact.run_id != run_id:
        raise HTTPException(status_code=404, detail="Artifact not found")
    path = Path(artifact.local_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Artifact file missing on disk")

    return {
        "artifact_id": artifact.id,
        "filename": artifact.filename,
        "size_bytes": artifact.size_bytes,
        "sha256": artifact.sha256,
        **preview_artifact(path, artifact.filename),
    }


@router.post("/{run_id}/approval")
async def record_approval(
    run_id: str,
    body: ApprovalRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Human-in-the-loop gate. The agent has no code path that can call this."""
    run = await _get_run_or_404(run_id, db)
    if run.status != RunStatus.awaiting_approval:
        raise HTTPException(
            status_code=409,
            detail=f"Run is not awaiting approval (status: {run.status.value})",
        )

    prior = await db.execute(
        select(func.count()).select_from(ApprovalRecord)
        .where(ApprovalRecord.run_id == run_id)
    )
    revision = (prior.scalar_one() or 0) + 1

    db.add(ApprovalRecord(
        run_id=run_id,
        revision=revision,
        decision=body.decision,
        note=body.note,
        decided_by="human",
    ))
    db.add(AuditEvent(
        run_id=run_id,
        event_type="approval_recorded",
        actor="human",
        approval_decision=body.decision.value,
        extra_metadata={"note": body.note, "revision": revision},
    ))
    await db.commit()

    # Hand the decision to the blocked worker. A LIST (not pub/sub) so the signal
    # survives even if the worker is momentarily not listening.
    redis = _redis()
    try:
        await redis.rpush(
            f"run:{run_id}:approval",
            json.dumps({"decision": body.decision.value, "note": body.note,
                        "revision": revision}),
        )
        await redis.expire(f"run:{run_id}:approval", 3600)
    finally:
        await redis.aclose()

    return {"status": "recorded", "decision": body.decision.value, "revision": revision}
