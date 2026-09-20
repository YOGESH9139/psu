"""FastAPI application entry point."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import files, knowledge, runs, sovereignty, workspaces
from app.core.config import settings
from app.services.model_registry import registry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("sovereign.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    for d in (settings.uploads_dir, settings.artifacts_dir, settings.workspaces_dir):
        Path(d).mkdir(parents=True, exist_ok=True)
    try:
        registry.load()
    except Exception as e:
        logger.error("Failed to load model registry: %s", e)
    yield


app = FastAPI(
    title="Sovereign AI Workbench API",
    version="0.1.0",
    lifespan=lifespan,
)

# The API is only ever reached from the operator's own browser on this machine.
# No wildcard origin — that would be an unnecessary hole in a sovereign system.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(files.router)
app.include_router(runs.router)
app.include_router(knowledge.router)
app.include_router(sovereignty.router)
app.include_router(workspaces.router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
