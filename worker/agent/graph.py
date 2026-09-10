"""LangGraph state machine:

    INTAKE → PREFLIGHT → ROUTE → PLAN → ACT ⇄ OBSERVE → VERIFY
                                                   ↓
                                          AWAIT_APPROVAL → DELIVER

Guards: at most `max_tool_cycles` tool executions, one re-plan, one code repair,
and a wall-clock timeout. The run cannot reach DELIVER on a safety-relevant
deliverable without a human decision row existing in Postgres.
"""
from __future__ import annotations

import hashlib
import json
import logging
import shutil
import time
from pathlib import Path
from typing import Any, Dict, Literal

import redis
from langgraph.graph import END, StateGraph
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.db_models import ApprovalRecord, Artifact, Run, UploadedFile
from app.services.model_registry import registry
from app.services.model_router import route as route_request
from worker.agent import planning
from worker.agent.events import audit, bump_iteration_count, emit, hash_result, set_run_status
from worker.agent.state import AgentState
from worker.rag.pipeline import rag_pipeline
from worker.tools.code_tools import sandbox_available
from worker.tools.docx_tools import stamp_human_decision
from worker.tools.path_utils import PathPolicyError, relative_to_workspace, run_workspace
from worker.tools.tool_registry import ToolNotAllowed, get_allowed_tool, sanitize_args

logger = logging.getLogger("sovereign.agent")

engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)
redis_client = redis.Redis.from_url(settings.redis_url, decode_responses=True)

MIME_BY_SUFFIX = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".txt": "text/plain",
    ".py": "text/x-python",
}


def _timed_out(state: AgentState) -> bool:
    started = state.get("started_at")
    return bool(started) and (time.monotonic() - started) > settings.run_timeout_seconds


def _state_event(state: AgentState, name: str) -> None:
    emit(state["run_id"], "state_change", {
        "state": name,
        "iteration": state.get("iteration_count", 0),
        "max_iterations": settings.max_tool_cycles,
    })


# ─── INTAKE ──────────────────────────────────────────────────────────────────

def intake_node(state: AgentState) -> Dict[str, Any]:
    run_id = state["run_id"]

    # The router decision is the FIRST thing the operator sees, before any step.
    with SessionLocal() as session:
        run = session.get(Run, run_id)
        stored_decision = (run.router_decision if run else None) or {}
    if stored_decision:
        emit(run_id, "router_decision", stored_decision)

    _state_event(state, "INTAKE")
    set_run_status(run_id, "running")

    try:
        workspace = run_workspace(run_id)
    except PathPolicyError as e:
        return {"error": f"Could not create run workspace: {e}"}

    input_files = []
    with SessionLocal() as session:
        for file_id in state.get("file_ids", []):
            record = session.get(UploadedFile, file_id)
            if record is None:
                logger.warning("[%s] unknown file_id %s", run_id, file_id)
                continue
            source = Path(record.local_path)
            if not source.exists():
                logger.warning("[%s] uploaded file missing on disk: %s", run_id, source)
                continue
            # Copy into the run workspace: tools may only ever touch that tree.
            dest = workspace / "inputs" / Path(record.original_filename).name
            shutil.copy2(source, dest)
            input_files.append({
                "file_id": record.id,
                "filename": record.original_filename,
                "mime_type": record.mime_type,
                "workspace_path": relative_to_workspace(dest, run_id),
                "size_bytes": record.size_bytes,
                "sha256": record.sha256,
            })

    audit(run_id, "INTAKE", sanitized_args={
        "goal": state.get("goal", "")[:300],
        "files": [f["filename"] for f in input_files],
    })
    emit(run_id, "intake", {
        "goal": state.get("goal", ""),
        "input_files": [
            {"filename": f["filename"], "mime_type": f["mime_type"], "sha256": f["sha256"][:16]}
            for f in input_files
        ],
    })

    return {
        "input_files": input_files,
        "router_decision": stored_decision,
        "observations": [],
        "plan": [],
        "current_tool_idx": 0,
        "iteration_count": 0,
        "replan_count": 0,
        "repair_count": 0,
        "findings": [],
        "citations": [],
        "needs_approval": False,
        "started_at": time.monotonic(),
        "error": None,
    }


# ─── PREFLIGHT ───────────────────────────────────────────────────────────────

def preflight_node(state: AgentState) -> Dict[str, Any]:
    run_id = state["run_id"]
    _state_event(state, "PREFLIGHT")

    registry.ensure_loaded()
    checks = {
        "ollama_reachable": registry.server_reachable_sync(),
        "installed_models": registry.installed_models_sync(),
        "qdrant": rag_pipeline.health(),
        "sandbox_ready": sandbox_available(),
    }
    emit(run_id, "preflight", checks)

    if not checks["ollama_reachable"]:
        audit(run_id, "PREFLIGHT_FAIL", metadata=checks)
        return {"error": "Local model server (Ollama) is unreachable. Start the "
                         "`ollama` service before running the agent."}

    if not checks["installed_models"]:
        audit(run_id, "PREFLIGHT_FAIL", metadata=checks)
        return {"error": "Ollama is running but has no models installed. Pull them "
                         "first: docker compose exec ollama ollama pull qwen3:8b"}

    audit(run_id, "PREFLIGHT_PASS", metadata={
        "installed_models": checks["installed_models"],
        "qdrant_reachable": checks["qdrant"].get("qdrant_reachable"),
        "sandbox_ready": checks["sandbox_ready"],
    })
    return {}


# ─── ROUTE ───────────────────────────────────────────────────────────────────

def route_node(state: AgentState) -> Dict[str, Any]:
    run_id = state["run_id"]
    _state_event(state, "ROUTE")

    files = state.get("input_files", [])
    decision = route_request(
        state.get("goal", ""),
        [f["mime_type"] for f in files],
        [f["filename"] for f in files],
    ).to_dict()

    emit(run_id, "router_decision", decision)

    # One 8B Q4 model fits in 8 GB VRAM; evict the other before loading this one.
    swapped = registry.swap_model(decision["model_id"])
    emit(run_id, "model_swap", {
        "model_id": decision["model_id"],
        "loaded": swapped,
        "policy": "keep_alive=0 — the previous model is evicted from VRAM first",
    })
    audit(run_id, "ROUTE", model_id=decision["model_id"], sanitized_args=decision)

    if not swapped:
        return {"error": f"Could not load model {decision['model_id']} into the local "
                         f"model server. Check `docker compose logs ollama`."}

    with SessionLocal() as session:
        run = session.get(Run, run_id)
        if run is not None:
            run.task_class = decision["task_class"]
            run.model_id = decision["model_id"]
            run.router_decision = decision
            session.commit()

    return {
        "task_class": decision["task_class"],
        "model_id": decision["model_id"],
        "router_decision": decision,
    }


# ─── PLAN ────────────────────────────────────────────────────────────────────

def plan_node(state: AgentState) -> Dict[str, Any]:
    run_id = state["run_id"]
    _state_event(state, "PLAN")

    plan = planning.build_plan(state)
    emit(run_id, "plan", {
        "steps": [{"tool": s["tool"]} for s in plan],
        "step_count": len(plan),
        "replan": state.get("replan_count", 0) > 0,
        "reason": state.get("repair_hint") or "",
    })
    audit(run_id, "PLAN", model_id=state.get("model_id"), sanitized_args={
        "steps": [s["tool"] for s in plan],
        "replan_count": state.get("replan_count", 0),
    })

    return {"plan": plan, "current_tool_idx": 0}


# ─── ACT ─────────────────────────────────────────────────────────────────────

def act_node(state: AgentState) -> Dict[str, Any]:
    run_id = state["run_id"]
    plan = state.get("plan", [])
    idx = state.get("current_tool_idx", 0)
    observations = list(state.get("observations", []))

    if idx >= len(plan):
        return {}

    step = plan[idx]
    tool_name = step["tool"]
    _state_event(state, "ACT")

    try:
        tool_fn = get_allowed_tool(tool_name)
    except ToolNotAllowed as e:
        emit(run_id, "tool_blocked", {"tool": tool_name, "error": str(e)})
        audit(run_id, "TOOL_BLOCKED", tool_name=tool_name, blocked_tool_attempt=True,
              sanitized_args={"reason": str(e)})
        observations.append({"tool": tool_name, "result": {"status": "blocked", "error": str(e)},
                             "blocked": True})
        return {"observations": observations, "current_tool_idx": idx + 1}

    try:
        args = planning.resolve_args(state, step)
    except Exception as e:
        logger.exception("[%s] argument resolution failed for %s", run_id, tool_name)
        observations.append({"tool": tool_name, "result": {"status": "error", "error": str(e)}})
        return {"observations": observations, "current_tool_idx": idx + 1}

    emit(run_id, "tool_call", {
        "tool": tool_name,
        "args": sanitize_args(args),
        "step": idx + 1,
        "of": len(plan),
    })
    audit(run_id, "TOOL_CALL", model_id=state.get("model_id"), tool_name=tool_name,
          sanitized_args=sanitize_args(args))

    started = time.monotonic()
    try:
        result = tool_fn.invoke(args)
    except PathPolicyError as e:
        result = {"status": "rejected", "error": str(e)}
        audit(run_id, "TOOL_PATH_DENIED", tool_name=tool_name, blocked_tool_attempt=True,
              sanitized_args={"reason": str(e)})
    except Exception as e:
        logger.exception("[%s] tool %s raised", run_id, tool_name)
        result = {"status": "error", "error": f"{type(e).__name__}: {e}"}

    duration_ms = int((time.monotonic() - started) * 1000)
    if not isinstance(result, dict):
        result = {"status": "success", "value": result}

    result_hash = hash_result(result)
    observations.append({"tool": tool_name, "result": result, "hash": result_hash[:12],
                         "duration_ms": duration_ms})

    emit(run_id, "tool_result", {
        "tool": tool_name,
        "status": result.get("status", "success"),
        "duration_ms": duration_ms,
        "hash": result_hash[:12],
        "result": _summarize_result(tool_name, result),
    })
    audit(run_id, "TOOL_RESULT", tool_name=tool_name, duration_ms=duration_ms,
          result_hash=result_hash, sanitized_args={"status": result.get("status")})

    updates: Dict[str, Any] = {
        "observations": observations,
        "iteration_count": state.get("iteration_count", 0) + 1,
    }
    bump_iteration_count(run_id, updates["iteration_count"])

    # Dynamic expansion: page count is only known after the PDF is rendered.
    new_plan = list(plan)
    extra = planning.expand_plan({**state, "plan": plan}, tool_name, result)
    if extra:
        new_plan[idx + 1:idx + 1] = extra
        updates["plan"] = new_plan
        emit(run_id, "plan_expanded", {
            "after": tool_name,
            "added": [s["tool"] for s in extra],
            "step_count": len(new_plan),
        })

    updates["current_tool_idx"] = idx + 1

    if tool_name == "create_approval_docx" and result.get("status") == "success":
        updates["deliverable_path"] = result.get("absolute_path")
        updates["findings"] = args.get("findings", [])
        updates["citations"] = args.get("sop_clauses", [])
    if tool_name == "verify_docx":
        updates["verify_result"] = result
    if tool_name == "request_human_approval" and result.get("status") == "approval_requested":
        updates["needs_approval"] = True

    return updates


def _summarize_result(tool_name: str, result: Dict[str, Any]) -> Dict[str, Any]:
    """Trim tool output for the live trace — full payloads stay server-side."""
    keep = {
        "extract_pdf_pages": ["page_count", "source_file", "status"],
        "run_ocr": ["page_number", "word_count", "confidence", "needs_vision_review", "status"],
        "inspect_image": ["anomalies_found", "anomaly_terms_seen", "model", "status"],
        "search_knowledge": ["result_count", "query", "status", "note"],
        "read_spreadsheet": ["sheet_names", "columns", "row_count", "status"],
        "analyze_spreadsheet": ["interpretation", "match_count", "filter", "status"],
        "create_approval_docx": ["docx_path", "file_size", "findings_count", "citation_count", "status"],
        "verify_docx": ["valid", "reason", "citation_count", "missing_headings"],
        "write_code_file": ["file_path", "line_count", "status"],
        "run_code_tests": ["passed", "exit_code", "status", "duration_seconds"],
        "list_run_artifacts": ["artifact_count", "status"],
        "request_human_approval": ["status", "artifact_path", "summary"],
    }.get(tool_name)

    summary = {k: result[k] for k in (keep or []) if k in result}
    if "error" in result:
        summary["error"] = str(result["error"])[:500]
    if tool_name == "search_knowledge":
        summary["citations"] = [
            {"source_file": h.get("source_file"), "page_number": h.get("page_number"),
             "heading": h.get("heading"), "excerpt": h.get("excerpt"), "score": h.get("score"),
             "chunk_id": h.get("chunk_id")}
            for h in result.get("results", [])
        ]
    if tool_name == "run_code_tests":
        summary["stdout"] = (result.get("stdout") or "")[-1500:]
        summary["stderr"] = (result.get("stderr") or "")[-1500:]
        summary["isolation"] = result.get("isolation")
    if tool_name == "analyze_spreadsheet":
        summary["matched_rows"] = result.get("matched_rows", [])[:10]
    return summary or {"status": result.get("status", "success")}


# ─── OBSERVE ─────────────────────────────────────────────────────────────────

def observe_node(state: AgentState) -> Dict[str, Any]:
    _state_event(state, "OBSERVE")
    return {}


def after_observe(state: AgentState) -> Literal["act", "verify", "fail"]:
    if state.get("error"):
        return "fail"
    if _timed_out(state):
        return "fail"
    steps_remaining = state.get("current_tool_idx", 0) < len(state.get("plan", []))

    if state.get("iteration_count", 0) >= settings.max_tool_cycles:
        # Only announce the guard when it actually cuts the plan short —
        # a plan that simply finished on its last allowed step is not a breach.
        if steps_remaining:
            emit(state["run_id"], "guard", {
                "guard": "max_tool_cycles",
                "limit": settings.max_tool_cycles,
                "skipped": len(state.get("plan", [])) - state.get("current_tool_idx", 0),
                "message": "Tool budget exhausted; verifying with what we have.",
            })
        return "verify"

    return "act" if steps_remaining else "verify"


# ─── VERIFY ──────────────────────────────────────────────────────────────────

def verify_node(state: AgentState) -> Dict[str, Any]:
    run_id = state["run_id"]
    _state_event(state, "VERIFY")

    task_class = state.get("task_class")
    updates: Dict[str, Any] = {}

    if task_class == "general-reasoning":
        answer = planning.answer_general_question(state)
        emit(run_id, "agent_answer", {"answer": answer,
                                      "citations": planning.collected_citations(state)})
        audit(run_id, "VERIFY_PASS", model_id=state.get("model_id"),
              sanitized_args={"kind": "general_answer"})
        return updates

    if task_class == "coding":
        tests = planning.observations_for(state, "run_code_tests")
        latest = tests[-1] if tests else None
        passed = bool(latest and latest.get("passed"))
        emit(run_id, "verification", {
            "kind": "code_tests",
            "passed": passed,
            "exit_code": (latest or {}).get("exit_code"),
            "sandbox_job_id": (latest or {}).get("sandbox_job_id"),
        })
        if not passed and state.get("repair_count", 0) < 1:
            hint = json.dumps({
                "exit_code": (latest or {}).get("exit_code"),
                "stdout": (latest or {}).get("stdout", "")[-1500:],
                "stderr": (latest or {}).get("stderr", "")[-1500:],
            })
            audit(run_id, "VERIFY_FAIL", sanitized_args={"kind": "code_tests"})
            emit(run_id, "repair", {"attempt": 1,
                                    "reason": "Sandbox tests failed; regenerating the code once."})
            return {"repair_count": state.get("repair_count", 0) + 1,
                    "repair_hint": hint, "replan_count": state.get("replan_count", 0)}
        audit(run_id, "VERIFY_PASS" if passed else "VERIFY_FAIL",
              sanitized_args={"kind": "code_tests", "passed": passed})
        return updates

    # Document / spreadsheet deliverable
    verify_result = state.get("verify_result") or {}
    if verify_result.get("valid"):
        audit(run_id, "VERIFY_PASS", sanitized_args={"kind": "docx"},
              source_citations=state.get("citations"))
        emit(run_id, "verification", {"kind": "docx", "valid": True,
                                      "citation_count": verify_result.get("citation_count")})
        return updates

    emit(run_id, "verification", {
        "kind": "docx",
        "valid": False,
        "reason": verify_result.get("reason", "no deliverable was produced"),
    })
    audit(run_id, "VERIFY_FAIL", sanitized_args={"reason": verify_result.get("reason", "")[:300]})

    if state.get("replan_count", 0) < 1:
        emit(run_id, "replan", {
            "attempt": 1,
            "reason": verify_result.get("reason", "deliverable verification failed"),
        })
        return {
            "replan_count": state.get("replan_count", 0) + 1,
            "repair_hint": f"The previous deliverable failed verification: "
                           f"{verify_result.get('reason', 'unknown reason')}",
        }
    return updates


def after_verify(state: AgentState) -> Literal["plan", "await_approval", "deliver", "fail"]:
    if state.get("error") or _timed_out(state):
        return "fail"

    task_class = state.get("task_class")

    if task_class == "coding":
        tests = planning.observations_for(state, "run_code_tests")
        passed = bool(tests and tests[-1].get("passed"))
        if not passed and state.get("repair_count", 0) == 1 and state.get("repair_hint"):
            return "plan"
        return "deliver"

    if task_class == "general-reasoning":
        return "deliver"

    verify_result = state.get("verify_result") or {}
    if not verify_result.get("valid") and state.get("replan_count", 0) == 1 \
            and state.get("repair_hint"):
        return "plan"

    if state.get("needs_approval"):
        return "await_approval"
    return "deliver"


# ─── AWAIT_APPROVAL ──────────────────────────────────────────────────────────

def await_approval_node(state: AgentState) -> Dict[str, Any]:
    """Block here until a human records a decision. The agent has no way past
    this node on its own — the decision must exist as a row in Postgres."""
    run_id = state["run_id"]
    _state_event(state, "AWAIT_APPROVAL")
    set_run_status(run_id, "awaiting_approval")

    verify_result = state.get("verify_result") or {}

    # Register the draft BEFORE blocking. A reviewer cannot be asked to approve a
    # document they have no way to read, so the artifact has to be addressable
    # while the run is still paused.
    drafts = _register_artifacts(run_id)

    emit(run_id, "awaiting_approval", {
        "run_id": run_id,
        "summary": planning._approval_summary(state),
        "deliverable": verify_result.get("docx_path"),
        "findings": state.get("findings", []),
        "citations": state.get("citations", []),
        "artifacts": drafts,
        "message": "This run will not finalize until an authorized human approves "
                   "or sends it back.",
    })
    audit(run_id, "AWAIT_APPROVAL", sanitized_args={
        "deliverable": verify_result.get("docx_path"),
        "citation_count": len(state.get("citations", [])),
    })

    # Which revisions this run has already consumed. Carried in state rather than
    # counted on entry, so a human who answers before the node starts waiting is
    # still honoured instead of being mistaken for a stale decision.
    seen_revision = int(state.get("approval_revision_seen") or 0)

    key = f"run:{run_id}:approval"
    deadline = time.monotonic() + settings.approval_timeout_seconds
    decision_payload: Dict[str, Any] | None = None

    while time.monotonic() < deadline:
        try:
            popped = redis_client.blpop(key, timeout=5)
        except Exception as e:
            logger.warning("[%s] approval wait error: %s", run_id, e)
            time.sleep(2)
            continue
        if popped:
            try:
                decision_payload = json.loads(popped[1])
            except Exception:
                decision_payload = None
            break

    if decision_payload is None:
        return {"error": "No human decision was recorded within "
                         f"{settings.approval_timeout_seconds}s. The run was not finalized."}

    # Trust the database row, not the queue message: a signal on the queue proves
    # nothing on its own, and the agent must never finalize on one.
    with SessionLocal() as session:
        record = session.execute(
            select(ApprovalRecord)
            .where(ApprovalRecord.run_id == run_id)
            .where(ApprovalRecord.revision > seen_revision)
            .order_by(ApprovalRecord.revision.desc())
        ).scalars().first()
        if record is None:
            return {"error": "An approval signal arrived with no matching decision row "
                             "in the database. Refusing to finalize."}
        decision = record.decision.value if hasattr(record.decision, "value") else str(record.decision)
        note = record.note or ""
        revision = record.revision

    emit(run_id, "approval_recorded", {"decision": decision, "note": note})
    audit(run_id, "APPROVAL_RECEIVED", actor="human", approval_decision=decision,
          sanitized_args={"note": note[:300]})

    return {
        "approval_decision": decision,
        "approval_note": note,
        "approval_revision_seen": revision,
    }


def after_approval(state: AgentState) -> Literal["deliver", "plan", "fail"]:
    if state.get("error"):
        return "fail"
    if state.get("approval_decision") == "reject":
        if state.get("replan_count", 0) < 1:
            emit(state["run_id"], "replan", {
                "attempt": 1,
                "reason": f"Sent back by a human: {state.get('approval_note') or 'no note given'}",
            })
            return "plan"
        return "deliver"  # recorded as rejected_final in DELIVER
    return "deliver"


# ─── DELIVER ─────────────────────────────────────────────────────────────────

def deliver_node(state: AgentState) -> Dict[str, Any]:
    run_id = state["run_id"]
    _state_event(state, "DELIVER")

    decision = state.get("approval_decision")

    # Stamp the *recorded* human decision into the note itself.
    deliverable = state.get("deliverable_path")
    if deliverable and decision:
        stamped = stamp_human_decision(deliverable, decision, state.get("approval_note") or "")
        if stamped.get("status") == "success":
            emit(run_id, "artifact_stamped", {
                "decision": decision, "decided_at": stamped.get("decided_at")})

    registered = _register_artifacts(run_id)
    emit(run_id, "artifacts", {"artifacts": registered})

    if decision == "reject":
        set_run_status(run_id, "rejected_final")
        audit(run_id, "DELIVER_REJECTED", approval_decision="reject",
              sanitized_args={"note": (state.get("approval_note") or "")[:300]})
        emit(run_id, "run_complete", {
            "run_id": run_id,
            "status": "rejected_final",
            "artifacts": registered,
            "message": "Sent back by a human and not re-approved. Nothing was finalized.",
        })
        return {}

    set_run_status(run_id, "completed")
    audit(
        run_id, "DELIVER",
        approval_decision=decision,
        artifact_hash=registered[0]["sha256"] if registered else None,
        source_citations=state.get("citations"),
        sanitized_args={"artifact_count": len(registered),
                        "iterations": state.get("iteration_count", 0)},
    )
    emit(run_id, "run_complete", {
        "run_id": run_id,
        "status": "completed",
        "artifacts": registered,
        "approval_decision": decision,
        "iterations": state.get("iteration_count", 0),
    })
    return {}


def _register_artifacts(run_id: str) -> list[dict]:
    """Record the run's deliverables in Postgres so the UI can offer downloads.

    Generated source files count as deliverables too — a coding run whose only
    output stayed inside the workspace would be unreviewable.
    """
    try:
        workspace = run_workspace(run_id)
    except PathPolicyError:
        return []

    candidates: list[Path] = []
    for subdir in ("artifacts", "code"):
        directory = workspace / subdir
        if directory.exists():
            candidates.extend(sorted(p for p in directory.rglob("*") if p.is_file()))

    registered: list[dict] = []
    with SessionLocal() as session:
        existing = {
            a.filename: a
            for a in session.execute(
                select(Artifact).where(Artifact.run_id == run_id)
            ).scalars().all()
        }
        for path in candidates:
            if not path.is_file():
                continue
            data = path.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            row = existing.get(path.name)
            if row is None:
                row = Artifact(
                    run_id=run_id,
                    filename=path.name,
                    mime_type=MIME_BY_SUFFIX.get(path.suffix.lower(), "application/octet-stream"),
                    size_bytes=len(data),
                    sha256=digest,
                    local_path=str(path),
                )
                session.add(row)
            else:
                row.size_bytes = len(data)
                row.sha256 = digest
                row.local_path = str(path)
            registered.append({
                "filename": path.name,
                "size_bytes": len(data),
                "sha256": digest,
                "mime_type": row.mime_type,
            })
        session.commit()
    return registered


# ─── FAIL ────────────────────────────────────────────────────────────────────

def fail_node(state: AgentState) -> Dict[str, Any]:
    run_id = state["run_id"]
    message = state.get("error") or "The run stopped without producing a deliverable."
    if _timed_out(state) and not state.get("error"):
        message = f"Run exceeded the {settings.run_timeout_seconds}s wall-clock limit."

    logger.error("[%s] run failed: %s", run_id, message)
    set_run_status(run_id, "failed", message)
    audit(run_id, "RUN_ERROR", sanitized_args={"error": message[:500]})
    emit(run_id, "run_error", {"run_id": run_id, "error": message})
    return {}


# ─── graph wiring ────────────────────────────────────────────────────────────

def _guard(next_node: str):
    def _decide(state: AgentState) -> str:
        if state.get("error"):
            return "fail"
        if _timed_out(state):
            return "fail"
        return next_node
    return _decide


builder = StateGraph(AgentState)
builder.add_node("intake", intake_node)
builder.add_node("preflight", preflight_node)
builder.add_node("route", route_node)
builder.add_node("plan", plan_node)
builder.add_node("act", act_node)
builder.add_node("observe", observe_node)
builder.add_node("verify", verify_node)
builder.add_node("await_approval", await_approval_node)
builder.add_node("deliver", deliver_node)
builder.add_node("fail", fail_node)

builder.set_entry_point("intake")
builder.add_conditional_edges("intake", _guard("preflight"),
                              {"preflight": "preflight", "fail": "fail"})
builder.add_conditional_edges("preflight", _guard("route"), {"route": "route", "fail": "fail"})
builder.add_conditional_edges("route", _guard("plan"), {"plan": "plan", "fail": "fail"})
builder.add_conditional_edges("plan", _guard("act"), {"act": "act", "fail": "fail"})
builder.add_edge("act", "observe")
builder.add_conditional_edges("observe", after_observe,
                              {"act": "act", "verify": "verify", "fail": "fail"})
builder.add_conditional_edges("verify", after_verify, {
    "plan": "plan", "await_approval": "await_approval", "deliver": "deliver", "fail": "fail"})
builder.add_conditional_edges("await_approval", after_approval,
                              {"deliver": "deliver", "plan": "plan", "fail": "fail"})
builder.add_edge("deliver", END)
builder.add_edge("fail", END)

# recursion_limit must comfortably exceed max_tool_cycles * nodes-per-cycle.
agent_graph = builder.compile()
