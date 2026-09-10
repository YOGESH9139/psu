"""Workspace inspection + the human-approval request signal."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, List

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from worker.tools.path_utils import PathPolicyError, relative_to_workspace, run_workspace, validate_path

MIME_BY_SUFFIX = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".txt": "text/plain",
    ".py": "text/x-python",
    ".json": "application/json",
}


class ListArtifactsInput(BaseModel):
    run_id: str = Field(..., description="Run ID")


class RequestHumanApprovalInput(BaseModel):
    run_id: str = Field(..., description="Run ID")
    artifact_path: str = Field(..., description="Workspace-relative path to the deliverable")
    summary: str = Field(..., description="Plain-language summary of what a human is approving")


@tool("list_run_artifacts", args_schema=ListArtifactsInput)
def list_run_artifacts(run_id: str) -> Dict[str, Any]:
    """List the deliverables this run has produced in its artifacts directory."""
    artifacts_dir = run_workspace(run_id) / "artifacts"
    files: List[Dict[str, Any]] = []
    for path in sorted(artifacts_dir.rglob("*")):
        if not path.is_file():
            continue
        files.append({
            "filename": path.name,
            "relative_path": relative_to_workspace(path, run_id),
            "size_bytes": path.stat().st_size,
            "mime_type": MIME_BY_SUFFIX.get(path.suffix.lower(), "application/octet-stream"),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        })
    return {"status": "success", "run_id": run_id, "artifact_count": len(files), "artifacts": files}


@tool("request_human_approval", args_schema=RequestHumanApprovalInput)
def request_human_approval(run_id: str, artifact_path: str, summary: str) -> Dict[str, Any]:
    """Flag that this deliverable needs an authorized human decision before the run
    can finalize. This tool only REQUESTS review — it cannot grant it."""
    try:
        resolved = validate_path(artifact_path, run_id)
    except PathPolicyError as e:
        return {"status": "rejected", "error": str(e)}

    if not resolved.exists():
        alt = validate_path(Path("artifacts") / Path(artifact_path).name, run_id)
        if not alt.exists():
            return {"status": "error", "error": f"Deliverable not found: {artifact_path}"}
        resolved = alt

    return {
        "status": "approval_requested",
        "run_id": run_id,
        "artifact_path": relative_to_workspace(resolved, run_id),
        "absolute_path": str(resolved),
        "artifact_sha256": hashlib.sha256(resolved.read_bytes()).hexdigest(),
        "summary": summary,
        "message": "Run will halt at AWAIT_APPROVAL until an authorized human records "
                   "a decision via POST /api/runs/{run_id}/approval.",
    }
