"""Thin client for the local Ollama gateway.

The only outbound HTTP the agent makes is to `settings.ollama_url`, which
resolves to a container on the internal Docker network. There is no code path
here that can be pointed at an external host.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List
from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.services.model_registry import registry

logger = logging.getLogger("sovereign.llm")

# Only these hostnames may ever be called. Container service names only.
ALLOWED_MODEL_HOSTS = {"ollama", "localhost", "127.0.0.1"}

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


class LocalModelError(RuntimeError):
    pass


def _assert_local_endpoint(url: str) -> None:
    host = urlparse(url).hostname or ""
    if host not in ALLOWED_MODEL_HOSTS:
        raise LocalModelError(
            f"Refusing to call model endpoint {url!r}: host {host!r} is not an "
            f"allowlisted local service ({sorted(ALLOWED_MODEL_HOSTS)})."
        )


def chat(
    model_id: str,
    system: str,
    user: str,
    *,
    json_mode: bool = False,
    temperature: float = 0.2,
    num_predict: int = 1024,
    timeout: float = 300.0,
) -> str:
    """One completion from a locally-served model. Returns the raw text."""
    model = registry.get_model(model_id)
    if model is None:
        raise LocalModelError(f"Model {model_id!r} is not in the registry")

    _assert_local_endpoint(settings.ollama_url)

    payload: Dict[str, Any] = {
        "model": model.ollama_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "keep_alive": model.keep_alive,
        "options": {
            "temperature": temperature,
            "num_predict": num_predict,
            "num_ctx": model.num_ctx,
        },
        # Qwen3 is a hybrid reasoning model. Left on, it spends the entire
        # num_predict budget inside its <think> block and returns empty content —
        # measured at 21 s and no answer, versus 1.4 s and the right answer with
        # it off. The agent's own state machine is the reasoning structure here,
        # so per-token chain-of-thought buys nothing.
        "think": False,
    }
    if json_mode:
        payload["format"] = "json"

    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(f"{settings.ollama_url}/api/chat", json=payload)
            if resp.status_code == 400 and "think" in resp.text.lower():
                # Model does not support the thinking toggle (e.g. the VL model).
                payload.pop("think", None)
                resp = client.post(f"{settings.ollama_url}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as e:
        raise LocalModelError(f"Local model call failed: {e}") from e

    message = data.get("message") or {}
    content = message.get("content") or ""
    if not content.strip() and message.get("thinking"):
        # Ran out of budget mid-reasoning; the thinking text is all we have.
        content = message["thinking"]
    # Older builds inline the reasoning instead of splitting it out.
    return re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()


def chat_json(
    model_id: str,
    system: str,
    user: str,
    *,
    fallback: Any = None,
    **kwargs: Any,
) -> Any:
    """Ask for JSON and parse it defensively. Returns `fallback` on any failure,
    so a model hiccup degrades the run instead of killing it."""
    try:
        raw = chat(model_id, system, user, json_mode=True, **kwargs)
    except LocalModelError as e:
        logger.warning("chat_json: model unavailable (%s); using fallback", e)
        return fallback

    for candidate in _json_candidates(raw):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue

    logger.warning("chat_json: could not parse model output as JSON: %.200s", raw)
    return fallback


def _json_candidates(raw: str) -> List[str]:
    raw = (raw or "").strip()
    if not raw:
        return []
    candidates = [raw]
    fenced = _JSON_BLOCK_RE.search(raw)
    if fenced:
        candidates.append(fenced.group(1).strip())
    # First balanced-looking object/array in the text.
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = raw.find(opener), raw.rfind(closer)
        if 0 <= start < end:
            candidates.append(raw[start:end + 1])
    return candidates
