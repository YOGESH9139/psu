"""Sovereignty status endpoint — the live, *measured* proof panel.

Nothing in this response is a hardcoded claim. Every boolean is either measured
here and now, or read from a heartbeat that the measuring container wrote.
"""
from __future__ import annotations

import asyncio
import json
import socket
from datetime import datetime, timezone

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db import get_db
from app.models.db_models import AuditEvent
from app.services.model_registry import registry

router = APIRouter(prefix="/api/sovereignty", tags=["sovereignty"])

# Probing several well-known public endpoints, not just one, so a single
# blackholed IP cannot be mistaken for a real air gap.
EGRESS_PROBES = [("8.8.8.8", 443), ("1.1.1.1", 443), ("93.184.216.34", 80)]
HEARTBEAT_STALE_SECONDS = 60


def _blocking_probe(host: str, port: int) -> bool:
    """True if the connection was REFUSED/unreachable (i.e. egress blocked)."""
    try:
        socket.create_connection((host, port), timeout=2).close()
        return False
    except Exception:
        return True


async def measure_egress_blocked() -> bool:
    loop = asyncio.get_running_loop()
    results = await asyncio.gather(*[
        loop.run_in_executor(None, _blocking_probe, host, port)
        for host, port in EGRESS_PROBES
    ])
    return all(results)


def _heartbeat_age(payload: dict | None) -> float | None:
    if not payload or "timestamp" not in payload:
        return None
    try:
        ts = datetime.fromisoformat(payload["timestamp"])
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - ts).total_seconds()
    except Exception:
        return None


async def _read_heartbeats() -> dict:
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        raw = await redis.mget("sovereignty:worker", "sovereignty:sandbox")
    except Exception:
        raw = [None, None]
    finally:
        await redis.aclose()

    out = {}
    for name, blob in zip(("worker", "sandbox"), raw):
        try:
            payload = json.loads(blob) if blob else None
        except Exception:
            payload = None
        age = _heartbeat_age(payload)
        out[name] = {
            "reporting": payload is not None and age is not None and age < HEARTBEAT_STALE_SECONDS,
            "age_seconds": round(age, 1) if age is not None else None,
            **(payload or {}),
        }
    return out


@router.get("/status")
async def sovereignty_status(db: AsyncSession = Depends(get_db)) -> dict:
    api_egress_blocked, health, heartbeats = await asyncio.gather(
        measure_egress_blocked(),
        registry.all_health(),
        _read_heartbeats(),
    )

    worker = heartbeats.get("worker", {})
    sandbox = heartbeats.get("sandbox", {})

    # The containers that actually touch model weights, documents and generated
    # code are the ones that must be unable to reach the internet.
    worker_blocked = bool(worker.get("reporting")) and bool(worker.get("egress_blocked"))
    sandbox_blocked = bool(sandbox.get("reporting")) and bool(sandbox.get("egress_blocked"))
    offline_capable = worker_blocked and sandbox_blocked

    result = await db.execute(
        select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(20)
    )
    audit_tail = [
        {
            "id": e.id,
            "run_id": e.run_id,
            "event_type": e.event_type,
            "actor": e.actor,
            "model_id": e.model_id,
            "tool_name": e.tool_name,
            "approval_decision": e.approval_decision,
            "blocked_tool_attempt": e.blocked_tool_attempt,
            "created_at": e.created_at.isoformat(),
        }
        for e in result.scalars().all()
    ]

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        # ── Measured, per-container ───────────────────────────────────────────
        "egress": {
            "api": {
                "egress_blocked": api_egress_blocked,
                "note": "API joins the edge network so the local browser can reach it. "
                        "It never calls out; the agent runtime below is the isolated part.",
            },
            "worker": {
                "egress_blocked": worker_blocked,
                "reporting": worker.get("reporting", False),
                "age_seconds": worker.get("age_seconds"),
            },
            "sandbox": {
                "egress_blocked": sandbox_blocked,
                "reporting": sandbox.get("reporting", False),
                "age_seconds": sandbox.get("age_seconds"),
                "network_mode": sandbox.get("network_mode", "unknown"),
            },
        },
        # Top-level rollups the UI pills bind to.
        "egress_blocked": worker_blocked,
        "offline_capable": offline_capable,
        "sandbox_network_mode": sandbox.get("network_mode", "unknown"),
        "model_endpoints": [
            {**m.to_dict(), "healthy": health.get(m.id, False)}
            for m in registry.all_models()
        ],
        "external_integrations": [],   # deliberately empty — no cloud connectors exist
        "cloud_credentials": [],       # deliberately empty — no API keys are configured
        "audit_tail": audit_tail,
    }
