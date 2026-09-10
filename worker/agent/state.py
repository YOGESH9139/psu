"""LangGraph agent state."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict


class InputFile(TypedDict, total=False):
    file_id: str
    filename: str
    mime_type: str
    workspace_path: str   # relative to the run workspace, e.g. inputs/report.pdf
    size_bytes: int
    sha256: str


class AgentState(TypedDict, total=False):
    # ── identity / input ─────────────────────────────────────────────────────
    run_id: str
    goal: str
    file_ids: List[str]
    input_files: List[InputFile]

    # ── routing ──────────────────────────────────────────────────────────────
    task_class: str
    model_id: str
    router_decision: Dict[str, Any]

    # ── plan / execution ─────────────────────────────────────────────────────
    plan: List[Dict[str, Any]]
    current_tool_idx: int
    observations: List[Dict[str, Any]]
    iteration_count: int
    replan_count: int
    repair_count: int

    # ── evidence / deliverables ──────────────────────────────────────────────
    findings: List[Dict[str, Any]]
    citations: List[Dict[str, Any]]
    deliverable_path: Optional[str]
    verify_result: Optional[Dict[str, Any]]
    needs_approval: bool

    # ── human decision ───────────────────────────────────────────────────────
    approval_decision: Optional[str]   # "approve" | "reject" | None
    approval_note: Optional[str]
    approval_revision_seen: int        # highest decision revision already acted on

    # ── control ──────────────────────────────────────────────────────────────
    started_at: float
    error: Optional[str]
    repair_hint: Optional[str]
