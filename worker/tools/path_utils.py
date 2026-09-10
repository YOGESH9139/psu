"""Run-scoped path validation. Every tool path argument goes through here.

Policy (plan.md "Sovereignty, Security, and Audit"):
  * A tool may only read or write inside `{workspaces_dir}/{run_id}`.
  * `..`, absolute host paths, `/etc`, symlink escapes and URLs are rejected.
  * Rejections raise `PathPolicyError`, which the agent records as a blocked
    tool attempt in the audit log rather than silently swallowing.
"""
from __future__ import annotations

import re
from pathlib import Path

from app.core.config import settings

WORKSPACE_ROOT = Path(settings.workspaces_dir).resolve()
UPLOADS_ROOT = Path(settings.uploads_dir).resolve()

_URL_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")


class PathPolicyError(ValueError):
    """Raised when a tool argument tries to leave its run workspace."""


def run_workspace(run_id: str) -> Path:
    """The single directory a run is allowed to touch. Created on demand."""
    if not run_id or "/" in run_id or "\\" in run_id or ".." in run_id:
        raise PathPolicyError(f"Invalid run_id: {run_id!r}")
    ws = (WORKSPACE_ROOT / run_id).resolve()
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "inputs").mkdir(exist_ok=True)
    (ws / "artifacts").mkdir(exist_ok=True)
    return ws


def validate_path(user_path: str | Path, run_id: str) -> Path:
    """Resolve `user_path` inside the run workspace, or raise PathPolicyError."""
    raw = str(user_path)

    # A scheme anywhere in the string, not just at position 0: joining "code" +
    # "http://host/x.py" yields a relative path that would otherwise slip past a
    # prefix-anchored check and create a junk "http:" directory.
    if _URL_RE.match(raw) or "://" in raw:
        raise PathPolicyError(f"URLs are not permitted as tool paths: {raw!r}")

    if chr(0) in raw:
        raise PathPolicyError("Null bytes are not permitted in tool paths")

    ws = run_workspace(run_id)
    candidate = Path(raw)

    if candidate.is_absolute():
        # Absolute paths are only tolerated when they already point into this
        # run's own workspace (tools echo absolute paths back to each other).
        resolved = candidate.resolve()
    else:
        resolved = (ws / candidate).resolve()

    try:
        resolved.relative_to(ws)
    except ValueError:
        raise PathPolicyError(
            f"Path {raw!r} resolves to {resolved}, which is outside the run "
            f"workspace {ws}. Denied by tool path policy."
        ) from None

    return resolved


def relative_to_workspace(path: Path | str, run_id: str) -> str:
    """Workspace-relative display form, safe to show in the UI and audit log."""
    ws = run_workspace(run_id)
    try:
        return str(Path(path).resolve().relative_to(ws)).replace("\\", "/")
    except Exception:
        return str(path)
