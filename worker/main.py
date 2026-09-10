"""Worker daemon — consumes the Redis job queue and runs the LangGraph agent.

Runs are executed concurrently in worker threads so that one run parked at
AWAIT_APPROVAL never blocks the queue.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path

import redis.asyncio as aioredis

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app.core.config import settings                    # noqa: E402
from app.services.model_registry import registry        # noqa: E402
from worker.agent.events import emit, set_run_status    # noqa: E402
from worker.agent.graph import agent_graph              # noqa: E402
from worker.rag.pipeline import rag_pipeline            # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("sovereign.worker")

RUN_QUEUE = "run_jobs"
MAX_CONCURRENT_RUNS = 2
HEARTBEAT_INTERVAL = 10
EGRESS_PROBES = [("8.8.8.8", 443), ("1.1.1.1", 443)]

_shutdown = asyncio.Event()


# ─── sovereignty heartbeat ───────────────────────────────────────────────────

def _egress_blocked() -> bool:
    """Measure, from inside this container, whether the internet is reachable."""
    for host, port in EGRESS_PROBES:
        try:
            socket.create_connection((host, port), timeout=2).close()
            return False
        except Exception:
            continue
    return True


async def heartbeat_loop(redis: aioredis.Redis) -> None:
    """Publish the worker's measured egress state, and relay the sandbox's."""
    sandbox_heartbeat = Path(settings.sandbox_queue_dir) / "heartbeat.json"
    while not _shutdown.is_set():
        try:
            blocked = await asyncio.to_thread(_egress_blocked)
            await redis.set("sovereignty:worker", json.dumps({
                "component": "worker",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "egress_blocked": blocked,
                "pid": os.getpid(),
            }), ex=120)

            if sandbox_heartbeat.exists():
                payload = json.loads(sandbox_heartbeat.read_text(encoding="utf-8"))
                await redis.set("sovereignty:sandbox", json.dumps(payload), ex=120)
        except Exception as e:
            logger.debug("heartbeat error: %s", e)

        try:
            await asyncio.wait_for(_shutdown.wait(), timeout=HEARTBEAT_INTERVAL)
        except asyncio.TimeoutError:
            pass


# ─── jobs ────────────────────────────────────────────────────────────────────

async def process_run_job(job: dict) -> None:
    run_id = job["run_id"]
    logger.info("Starting run %s", run_id)

    initial_state = {
        "run_id": run_id,
        "goal": job.get("goal", ""),
        "file_ids": job.get("file_ids", []),
    }
    try:
        await asyncio.to_thread(
            agent_graph.invoke,
            initial_state,
            {"recursion_limit": 100},
        )
        logger.info("Run %s finished", run_id)
    except Exception as e:
        logger.exception("Run %s crashed", run_id)
        set_run_status(run_id, "failed", str(e))
        emit(run_id, "run_error", {"run_id": run_id, "error": f"{type(e).__name__}: {e}"})


async def process_ingest_job(job: dict) -> None:
    file_id = job.get("file_id")
    file_path = job.get("file_path")
    name = job.get("original_filename")
    logger.info("Ingesting %s (%s)", name, file_id)

    result = await asyncio.to_thread(
        rag_pipeline.ingest_file, file_path, name, job.get("mime_type")
    )
    if result.get("status") == "success":
        logger.info("Ingested %s: %d chunks over %d pages",
                    name, result["chunks"], result["pages"])
    else:
        logger.error("Ingestion of %s failed: %s", name, result.get("error"))

    try:
        redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        await redis.set(f"ingest:{file_id}", json.dumps(result), ex=3600)
        await redis.aclose()
    except Exception as e:
        logger.debug("Could not record ingestion result: %s", e)


async def dispatch(job: dict, semaphore: asyncio.Semaphore) -> None:
    async with semaphore:
        task_type = job.get("task_type", "run")
        if task_type == "run":
            await process_run_job(job)
        elif task_type == "knowledge_ingest":
            await process_ingest_job(job)
        else:
            logger.warning("Unknown task_type %r — ignoring", task_type)


# ─── main loop ───────────────────────────────────────────────────────────────

async def worker_loop() -> None:
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_RUNS)
    in_flight: set[asyncio.Task] = set()

    try:
        registry.load()
    except Exception as e:
        logger.error("Could not load the model registry: %s", e)

    heartbeat = asyncio.create_task(heartbeat_loop(redis))
    logger.info("Sovereign worker ready — polling %r (max %d concurrent runs)",
                RUN_QUEUE, MAX_CONCURRENT_RUNS)

    while not _shutdown.is_set():
        try:
            popped = await redis.blpop(RUN_QUEUE, timeout=2)
            if not popped:
                continue
            job = json.loads(popped[1])
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Queue read failed: %s", e)
            await asyncio.sleep(1)
            continue

        task = asyncio.create_task(dispatch(job, semaphore))
        in_flight.add(task)
        task.add_done_callback(in_flight.discard)

    logger.info("Shutting down; waiting for %d in-flight run(s)", len(in_flight))
    heartbeat.cancel()
    if in_flight:
        await asyncio.gather(*in_flight, return_exceptions=True)
    await redis.aclose()


def _install_signal_handlers(loop: asyncio.AbstractEventLoop) -> None:
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _shutdown.set)
        except NotImplementedError:  # pragma: no cover - Windows dev runs
            pass


def main() -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _install_signal_handlers(loop)
    try:
        loop.run_until_complete(worker_loop())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
