"""Run-scoped episodic memory.

Lets the agent refer back to what earlier steps produced (OCR text, retrieved
clauses, a failed test run) without re-reading every tool payload from scratch.

Scope is strictly one `run_id` — there is no cross-run memory, and keys expire,
so nothing from one operator's run can leak into another's context window.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

import redis

from app.core.config import settings

logger = logging.getLogger("sovereign.memory")

MEMORY_TTL_SECONDS = 24 * 3600
MAX_MESSAGES = 200
SUMMARY_TRIGGER = 40          # messages before older ones are folded into a summary
CHARS_PER_MESSAGE = 1200

_redis = redis.Redis.from_url(settings.redis_url, decode_responses=True)


class RunMemory:
    """Append-only message log for a single run, with rolling summarisation."""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.key = f"run:{run_id}:memory"
        self.summary_key = f"run:{run_id}:memory_summary"

    def append(self, role: str, content: str, **metadata: Any) -> None:
        record = {
            "role": role,
            "content": content[:CHARS_PER_MESSAGE],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **metadata,
        }
        try:
            pipe = _redis.pipeline()
            pipe.rpush(self.key, json.dumps(record, default=str))
            pipe.ltrim(self.key, -MAX_MESSAGES, -1)
            pipe.expire(self.key, MEMORY_TTL_SECONDS)
            pipe.execute()
        except Exception as e:
            logger.debug("[%s] memory append failed: %s", self.run_id, e)

    def messages(self, limit: int = 20) -> List[Dict[str, Any]]:
        try:
            raw = _redis.lrange(self.key, -limit, -1)
        except Exception as e:
            logger.debug("[%s] memory read failed: %s", self.run_id, e)
            return []
        out = []
        for item in raw:
            try:
                out.append(json.loads(item))
            except json.JSONDecodeError:
                continue
        return out

    @property
    def summary(self) -> str:
        try:
            return _redis.get(self.summary_key) or ""
        except Exception:
            return ""

    def set_summary(self, text: str) -> None:
        try:
            _redis.set(self.summary_key, text[:4000], ex=MEMORY_TTL_SECONDS)
        except Exception as e:
            logger.debug("[%s] memory summary write failed: %s", self.run_id, e)

    def needs_summary(self) -> bool:
        try:
            return _redis.llen(self.key) >= SUMMARY_TRIGGER
        except Exception:
            return False

    def as_context(self, limit: int = 12) -> str:
        """Compact transcript to paste into a prompt."""
        parts = []
        if self.summary:
            parts.append(f"[earlier in this run]\n{self.summary}")
        for message in self.messages(limit):
            parts.append(f"[{message.get('role', '?')}] {message.get('content', '')}")
        return "\n\n".join(parts)

    def clear(self) -> None:
        try:
            _redis.delete(self.key, self.summary_key)
        except Exception:
            pass


def get_episodic_memory(run_id: str) -> RunMemory:
    return RunMemory(run_id)
