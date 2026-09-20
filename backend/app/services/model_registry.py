"""Model Registry — loads models.yaml, health-checks Ollama, manages hot-swap.

Exposes both async (API process) and sync (worker/LangGraph nodes) methods so
neither side has to bridge event loops.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path
from typing import Any

import httpx
import yaml

from app.core.config import settings

logger = logging.getLogger("sovereign.model_registry")


class ModelInfo:
    def __init__(self, data: dict[str, Any]) -> None:
        self.id: str = data["id"]
        self.name: str = data.get("name", data["id"])
        self.ollama_model: str = data["ollama_model"]
        self.endpoint: str = data.get("endpoint", settings.ollama_url)
        self.capabilities: list[str] = data.get("capabilities", [])
        self.preferred_tasks: list[str] = data.get("preferred_tasks", [])
        self.context_limit: int = data.get("context_limit", 32768)
        # Working context actually requested at load time. The KV cache scales
        # with this, so on an 8 GB card it must stay well under context_limit.
        self.num_ctx: int = data.get("num_ctx", 8192)
        # Ollama accepts either seconds (int) or a duration string like "5m".
        self.keep_alive: int | str = data.get("keep_alive", "5m")
        self.health_check_path: str = data.get("health_check_path", "/api/tags")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "ollama_model": self.ollama_model,
            "endpoint": self.endpoint,
            "capabilities": self.capabilities,
            "preferred_tasks": self.preferred_tasks,
            "context_limit": self.context_limit,
            "num_ctx": self.num_ctx,
            "keep_alive": self.keep_alive,
        }


def _default_yaml_path() -> Path:
    """First existing candidate: the configured path, the container path, then a
    couple of repo-relative guesses for running outside Docker."""
    candidates = [Path(settings.models_yaml_path), Path("/app/infra/models.yaml")]

    here = Path(__file__).resolve()
    for depth in (3, 4):
        if depth < len(here.parents):
            candidates.append(here.parents[depth] / "infra" / "models.yaml")

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


class ModelRegistry:
    def __init__(self) -> None:
        self._models: dict[str, ModelInfo] = {}
        self._router_rules: list[dict] = []
        self._loaded = False
        self._active_model: str | None = None
        # Re-entrant: the same thread may hold it across swap_model and a chat call.
        self._lock = threading.RLock()

    # ── Loading ──────────────────────────────────────────────────────────────

    def load(self, yaml_path: str | None = None) -> None:
        path = Path(yaml_path) if yaml_path else _default_yaml_path()
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        self._models = {m["id"]: ModelInfo(m) for m in data.get("models", [])}
        self._router_rules = data.get("router_rules", [])
        self._loaded = True
        logger.info("Model registry loaded from %s: %s", path, list(self._models))

    def ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()

    # ── Lookup ───────────────────────────────────────────────────────────────

    def get_model(self, model_id: str) -> ModelInfo | None:
        self.ensure_loaded()
        return self._models.get(model_id)

    def all_models(self) -> list[ModelInfo]:
        self.ensure_loaded()
        return list(self._models.values())

    def router_rules(self) -> list[dict]:
        self.ensure_loaded()
        return self._router_rules

    def gpu(self):
        """Context manager: only one model call touches the GPU at a time."""
        return self._lock

    @property
    def active_model(self) -> str | None:
        return self._active_model

    # ── Health (async, used by the API) ──────────────────────────────────────

    async def health_check(self, model_id: str) -> bool:
        model = self.get_model(model_id)
        if not model:
            return False
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(f"{model.endpoint}{model.health_check_path}")
                if r.status_code != 200:
                    return False
                names = {m.get("name", "") for m in r.json().get("models", [])}
                # Present in the local store (exact tag or base name).
                return any(
                    n == model.ollama_model or n.split(":")[0] == model.ollama_model.split(":")[0]
                    for n in names
                )
        except Exception:
            return False

    async def all_health(self) -> dict[str, bool]:
        self.ensure_loaded()
        ids = list(self._models)
        results = await asyncio.gather(
            *[self.health_check(mid) for mid in ids], return_exceptions=True
        )
        return {mid: (r is True) for mid, r in zip(ids, results)}

    # ── Health + swap (sync, used by the worker/LangGraph nodes) ─────────────

    def server_reachable_sync(self) -> bool:
        try:
            with httpx.Client(timeout=5.0) as client:
                return client.get(f"{settings.ollama_url}/api/tags").status_code == 200
        except Exception:
            return False

    def installed_models_sync(self) -> list[str]:
        try:
            with httpx.Client(timeout=5.0) as client:
                r = client.get(f"{settings.ollama_url}/api/tags")
                r.raise_for_status()
                return [m.get("name", "") for m in r.json().get("models", [])]
        except Exception:
            return []

    def health_check_sync(self, model_id: str) -> bool:
        model = self.get_model(model_id)
        if not model:
            return False
        installed = self.installed_models_sync()
        base = model.ollama_model.split(":")[0]
        return any(n == model.ollama_model or n.split(":")[0] == base for n in installed)

    def loaded_models_sync(self) -> list[str]:
        """Models currently resident in VRAM, per Ollama's own /api/ps."""
        try:
            with httpx.Client(timeout=5.0) as client:
                r = client.get(f"{settings.ollama_url}/api/ps")
                r.raise_for_status()
                return [m.get("name", "") for m in r.json().get("models", [])]
        except Exception:
            return []

    def evict_sync(self, ollama_model: str) -> None:
        """Drop a model from VRAM.

        Only issued for models Ollama reports as resident: a keep_alive=0 request
        against an *unloaded* model makes Ollama load it in order to unload it,
        which on an 8 GB card is exactly the OOM this method exists to avoid.
        """
        if ollama_model not in self.loaded_models_sync():
            return
        try:
            with httpx.Client(timeout=60.0) as client:
                client.post(
                    f"{settings.ollama_url}/api/generate",
                    json={"model": ollama_model, "prompt": "", "keep_alive": 0},
                )
            logger.info("Evicted %s from VRAM", ollama_model)
        except Exception as e:  # best-effort — eviction failure is not fatal
            logger.debug("Eviction of %s failed: %s", ollama_model, e)

    def swap_model(self, model_id: str) -> bool:
        """Evict every other model, then warm the target. 8 GB VRAM holds one 8B Q4."""
        target = self.get_model(model_id)
        if not target:
            logger.warning("swap_model: unknown model_id %s", model_id)
            return False

        with self._lock:
            if self._active_model == model_id:
                return True
            for mid, m in self._models.items():
                if mid != model_id:
                    self.evict_sync(m.ollama_model)
            try:
                with httpx.Client(timeout=300.0) as client:
                    r = client.post(
                        f"{settings.ollama_url}/api/generate",
                        json={
                            "model": target.ollama_model,
                            "prompt": "",
                            "keep_alive": target.keep_alive,
                            "options": {"num_ctx": target.num_ctx},
                        },
                    )
                    r.raise_for_status()
            except Exception as e:
                logger.warning("Warm-up of %s failed: %s", target.ollama_model, e)
                return False
            self._active_model = model_id
            return True

    # Back-compat alias used in earlier code paths.
    async def swap_to(self, model_id: str) -> None:
        await asyncio.to_thread(self.swap_model, model_id)


# Singleton — shared across each process
registry = ModelRegistry()
model_registry = registry
