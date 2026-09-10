"""SSE emission (via Redis) and append-only audit writes.

Every event is published on `run:{run_id}:events` AND appended to
`run:{run_id}:event_log`, so a browser that connects late still replays the
whole trace.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import redis
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.db_models import AuditEvent, Run

logger = logging.getLogger("sovereign.events")

EVENT_LOG_TTL_SECONDS = 24 * 3600

engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)
redis_client = redis.Redis.from_url(settings.redis_url, decode_responses=True)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def hash_result(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, default=str, sort_keys=True).encode("utf-8")
    ).hexdigest()


def emit(run_id: str, event_type: str, data: Optional[Dict[str, Any]] = None) -> None:
    """Publish one SSE event and mirror it into the replay log."""
    payload = json.dumps({
        "type": event_type,
        "run_id": run_id,
        "timestamp": now_iso(),
        "data": data or {},
    }, default=str)
    try:
        log_key = f"run:{run_id}:event_log"
        pipe = redis_client.pipeline()
        pipe.rpush(log_key, payload)
        pipe.expire(log_key, EVENT_LOG_TTL_SECONDS)
        pipe.publish(f"run:{run_id}:events", payload)
        pipe.execute()
    except Exception as e:
        logger.warning("Failed to emit %s for run %s: %s", event_type, run_id, e)


def audit(
    run_id: str,
    event_type: str,
    *,
    actor: str = "system",
    model_id: str | None = None,
    tool_name: str | None = None,
    sanitized_args: Dict[str, Any] | None = None,
    duration_ms: int | None = None,
    result_hash: str | None = None,
    artifact_hash: str | None = None,
    source_citations: list | None = None,
    approval_decision: str | None = None,
    blocked_tool_attempt: bool = False,
    metadata: Dict[str, Any] | None = None,
) -> None:
    """Append one immutable audit row. Never raises into the agent loop."""
    try:
        with SessionLocal() as session:
            session.add(AuditEvent(
                run_id=run_id,
                event_type=event_type,
                actor=actor,
                model_id=model_id,
                tool_name=tool_name,
                sanitized_args=sanitized_args,
                duration_ms=duration_ms,
                result_hash=result_hash,
                artifact_hash=artifact_hash,
                source_citations=source_citations,
                approval_decision=approval_decision,
                blocked_tool_attempt=blocked_tool_attempt,
                extra_metadata=metadata,
            ))
            session.commit()
    except Exception as e:
        logger.error("Failed to write audit event %s for run %s: %s", event_type, run_id, e)


def set_run_status(run_id: str, status: str, error_message: str | None = None) -> None:
    try:
        with SessionLocal() as session:
            run = session.get(Run, run_id)
            if run is None:
                logger.warning("set_run_status: run %s not found", run_id)
                return
            run.status = status
            if error_message is not None:
                run.error_message = error_message[:2000]
            session.commit()
    except Exception as e:
        logger.error("Failed to set status %s on run %s: %s", status, run_id, e)


def bump_iteration_count(run_id: str, value: int) -> None:
    try:
        with SessionLocal() as session:
            run = session.get(Run, run_id)
            if run is not None:
                run.iteration_count = value
                session.commit()
    except Exception as e:
        logger.debug("Failed to persist iteration count: %s", e)
