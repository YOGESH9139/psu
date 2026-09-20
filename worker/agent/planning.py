"""Plan construction, dynamic plan expansion, and argument resolution.

The plan skeleton per task class is deterministic (so the demo is reproducible
and the trace is readable), but every argument that matters — the SOP query, the
findings table, the recommended action, the generated code — is produced by the
local model from what the tools actually observed. Nothing in the deliverable is
hardcoded.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List

from app.core.config import settings
from worker.agent.llm import LocalModelError, chat, chat_json
from worker.agent.state import AgentState
from worker.tools.docx_tools import RISK_NOTICE
from worker.tools.tool_registry import RUN_SCOPED_TOOLS

logger = logging.getLogger("sovereign.planning")

MAX_OCR_PAGES = 2          # keeps the whole plan inside max_tool_cycles
MAX_OCR_CHARS_FOR_LLM = 6000

PDF_MIMES = {"application/pdf"}
IMAGE_MIMES = {"image/png", "image/jpeg", "image/tiff", "image/webp"}


# ─── helpers ────────────────────────────────────────────────────────────────

def primary_input(state: AgentState) -> Dict[str, Any] | None:
    files = state.get("input_files") or []
    return files[0] if files else None


def observations_for(state: AgentState, tool_name: str) -> List[Dict[str, Any]]:
    return [
        o["result"] for o in state.get("observations", [])
        if o.get("tool") == tool_name and isinstance(o.get("result"), dict)
    ]


def collected_ocr_text(state: AgentState) -> str:
    parts = []
    for result in observations_for(state, "run_ocr"):
        text = (result.get("text") or "").strip()
        if text:
            parts.append(f"[page {result.get('page_number', '?')}] {text}")
    for result in observations_for(state, "inspect_image"):
        desc = (result.get("description") or "").strip()
        if desc:
            parts.append(f"[vision] {desc}")
    return "\n\n".join(parts)[:MAX_OCR_CHARS_FOR_LLM]


_CLAUSE_ID_RE = re.compile(r"^((?:SECTION|CLAUSE|APPENDIX|ANNEX|PART)\s+[\w.\-]+|\d+(?:\.\d+)*)", re.IGNORECASE)


def _clause_label(hit: Dict[str, Any]) -> str:
    """A short, quotable clause id — 'SOP-CORR-014 s3.4', not a whole sentence."""
    source_stem = str(hit.get("source_file", "source")).rsplit(".", 1)[0]
    heading = (hit.get("heading") or "").strip()
    match = _CLAUSE_ID_RE.match(heading)
    if match:
        return f"{source_stem} §{match.group(1)}"
    return f"{source_stem} p.{hit.get('page_number', '?')}"


def _clause_body(hit: Dict[str, Any], max_chars: int = 500) -> str:
    """Chunks carry an overlap from the previous chunk so retrieval doesn't miss
    text spanning a cut. That overlap must not be quoted back as the clause, so
    trim to the detected heading before quoting."""
    text = (hit.get("text") or "").strip()
    heading = (hit.get("heading") or "").strip()
    if heading:
        first_token = heading.split()[0]
        position = text.find(first_token)
        if position > 0:
            text = text[position:]
    text = " ".join(text.split())
    return text[:max_chars] + ("…" if len(text) > max_chars else "")


def collected_citations(state: AgentState) -> List[Dict[str, Any]]:
    """Every retrieved passage, de-duplicated, ready to cite with source + page."""
    citations: List[Dict[str, Any]] = []
    seen: set = set()
    for result in observations_for(state, "search_knowledge"):
        for hit in result.get("results", []):
            chunk_id = hit.get("chunk_id")
            if chunk_id in seen:
                continue
            seen.add(chunk_id)
            citations.append({
                "clause": _clause_label(hit),
                "content": _clause_body(hit),
                "source_file": hit.get("source_file", "unknown"),
                "page_number": hit.get("page_number", "?"),
                "chunk_id": chunk_id,
                "score": hit.get("score"),
            })
    return citations


# ─── plan skeletons ─────────────────────────────────────────────────────────

def build_plan(state: AgentState) -> List[Dict[str, Any]]:
    task_class = state.get("task_class", "general-reasoning")
    run_id = state["run_id"]
    primary = primary_input(state)

    if task_class == "multimodal-document":
        return _multimodal_plan(run_id, primary)
    if task_class == "spreadsheet-analysis":
        return _spreadsheet_plan(run_id, primary)
    if task_class == "coding":
        return _coding_plan(run_id)
    return _general_plan(run_id, primary)


def _multimodal_plan(run_id: str, primary: Dict[str, Any] | None) -> List[Dict[str, Any]]:
    if primary is None:
        return [{"tool": "search_knowledge", "args": {}}]

    path = primary["workspace_path"]
    steps: List[Dict[str, Any]] = []

    if primary.get("mime_type") in PDF_MIMES or path.lower().endswith(".pdf"):
        steps.append({"tool": "extract_pdf_pages", "args": {"file_path": path, "run_id": run_id}})
        # run_ocr / inspect_image steps are appended by expand_plan once we know
        # how many pages the document actually has.
    else:
        steps.append({"tool": "run_ocr", "args": {"image_path": path, "run_id": run_id}})
        steps.append({"tool": "inspect_image", "args": {"image_path": path, "run_id": run_id}})

    steps.append({"tool": "search_knowledge", "args": {}})
    steps.append({"tool": "create_approval_docx", "args": {"output_filename": "approval_note.docx"}})
    steps.append({"tool": "verify_docx", "args": {"docx_path": "artifacts/approval_note.docx", "run_id": run_id}})
    steps.append({"tool": "request_human_approval", "args": {
        "run_id": run_id, "artifact_path": "artifacts/approval_note.docx"}})
    return steps


def _spreadsheet_plan(run_id: str, primary: Dict[str, Any] | None) -> List[Dict[str, Any]]:
    if primary is None:
        return [{"tool": "search_knowledge", "args": {}}]
    path = primary["workspace_path"]
    return [
        {"tool": "read_spreadsheet", "args": {"file_path": path, "run_id": run_id}},
        {"tool": "analyze_spreadsheet", "args": {"file_path": path, "run_id": run_id}},
        {"tool": "search_knowledge", "args": {}},
        {"tool": "create_approval_docx", "args": {"output_filename": "analysis_note.docx"}},
        {"tool": "verify_docx", "args": {"docx_path": "artifacts/analysis_note.docx", "run_id": run_id}},
        {"tool": "request_human_approval", "args": {
            "run_id": run_id, "artifact_path": "artifacts/analysis_note.docx"}},
    ]


def _coding_plan(run_id: str) -> List[Dict[str, Any]]:
    return [
        {"tool": "write_code_file", "args": {"run_id": run_id}},
        {"tool": "run_code_tests", "args": {"run_id": run_id, "test_command": "pytest"}},
        {"tool": "list_run_artifacts", "args": {"run_id": run_id}},
    ]


def _general_plan(run_id: str, primary: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
    """A conversational turn. With a spreadsheet attached, look at it, so a
    follow-up like "and above 80?" is answered from the data, not from memory."""
    steps: List[Dict[str, Any]] = []
    path = (primary or {}).get("workspace_path", "")
    if path.lower().endswith((".xlsx", ".xls", ".csv")):
        steps.append({"tool": "analyze_spreadsheet", "args": {"file_path": path, "run_id": run_id}})
    steps.append({"tool": "search_knowledge", "args": {}})
    return steps


def expand_plan(state: AgentState, tool_name: str, result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Steps to splice in right after the step that just ran."""
    if tool_name != "extract_pdf_pages" or result.get("status") != "success":
        return []

    run_id = state["run_id"]
    pages = result.get("pages", [])
    budget = settings.max_tool_cycles - len(state.get("plan", []))
    if budget <= 0:
        return []

    extra: List[Dict[str, Any]] = []
    for page in pages[:MAX_OCR_PAGES]:
        if len(extra) >= budget:
            break
        extra.append({"tool": "run_ocr", "args": {
            "image_path": page["image_path"], "run_id": run_id}})

    # One vision pass over the first page — the photograph and any handwriting
    # live there in the fixture, and OCR alone cannot read either.
    if pages and len(extra) < budget:
        extra.append({"tool": "inspect_image", "args": {
            "image_path": pages[0]["image_path"], "run_id": run_id}})

    return extra


# ─── argument resolution (where the local model actually does the work) ─────

def resolve_args(state: AgentState, step: Dict[str, Any]) -> Dict[str, Any]:
    tool_name = step["tool"]
    args = dict(step.get("args") or {})
    run_id = state["run_id"]
    model_id = state.get("model_id", "qwen3-8b")

    if tool_name == "search_knowledge":
        args.setdefault("query", _sop_query(state, model_id))
        args.setdefault("top_k", 5)
        args["workspace"] = state.get("workspace")

    elif tool_name == "analyze_spreadsheet":
        args.setdefault("query", state.get("goal", ""))

    elif tool_name == "write_code_file":
        filename, code = _generate_code(state, model_id)
        args.setdefault("file_path", filename)
        args.setdefault("code", code)

    elif tool_name == "create_approval_docx":
        args.update(_compose_note(state, model_id, args.get("output_filename", "note.docx")))
        args["run_id"] = run_id

    elif tool_name == "request_human_approval":
        args.setdefault("summary", _approval_summary(state))

    if tool_name in RUN_SCOPED_TOOLS:
        args["run_id"] = run_id
    else:
        args.pop("run_id", None)  # e.g. search_knowledge takes no run scope
    return args


def _sop_query(state: AgentState, model_id: str) -> str:
    """Turn the goal + what we read out of the document into a retrieval query."""
    evidence = collected_ocr_text(state)
    if not evidence:
        return state.get("goal", "")[:300]

    result = chat_json(
        model_id,
        system=(
            "You build search queries for a local standard-operating-procedure "
            "index. Reply with JSON only: {\"query\": \"...\"}. The query should "
            "be 4-15 words naming the equipment, defect and measurement involved."
        ),
        user=(
            f"Task: {state.get('goal', '')}\n\n"
            f"Extracted from the source document:\n{evidence[:2500]}\n\n"
            "Give the retrieval query."
        ),
        fallback=None,
        num_predict=200,
    )
    if isinstance(result, dict) and isinstance(result.get("query"), str) and result["query"].strip():
        return result["query"].strip()[:300]
    return state.get("goal", "")[:300]


def _generate_code(state: AgentState, model_id: str) -> tuple[str, str]:
    """Ask the coding model for a single self-testing Python file."""
    uploaded = ""
    primary = primary_input(state)
    if primary and primary["workspace_path"].endswith(".py"):
        try:
            from worker.tools.path_utils import validate_path

            uploaded = validate_path(primary["workspace_path"], state["run_id"]).read_text(
                encoding="utf-8", errors="replace")[:4000]
        except Exception as e:
            logger.debug("Could not read uploaded source: %s", e)

    hint = state.get("repair_hint") or ""
    system = (
        "You are a Python engineer working offline. Reply with JSON only: "
        '{"filename": "test_solution.py", "code": "..."}. '
        "The code must be one self-contained file that both implements the "
        "solution and contains pytest test functions verifying it. Use only the "
        "Python standard library and pytest. No network access is available."
    )
    user = (
        f"Task: {state.get('goal', '')}\n"
        + (f"\nExisting source to work from:\n```python\n{uploaded}\n```\n" if uploaded else "")
        + (f"\nThe previous attempt failed. Fix it. Test output was:\n{hint[:2000]}\n" if hint else "")
    )

    result = chat_json(model_id, system, user, fallback=None, num_predict=2048, timeout=420.0)
    if isinstance(result, dict) and isinstance(result.get("code"), str) and result["code"].strip():
        filename = str(result.get("filename") or "test_solution.py")
        filename = Path(filename).name
        if not filename.endswith(".py"):
            filename += ".py"
        if not filename.startswith("test_"):
            filename = f"test_{filename}"  # so pytest collects it
        return filename, result["code"]

    logger.warning("Code generation produced nothing usable; writing a failing placeholder")
    return "test_solution.py", (
        "# The local coding model did not return usable code for this task.\n"
        "def test_placeholder():\n"
        "    raise AssertionError(\n"
        "        'Code generation failed — the local model returned no parseable code.'\n"
        "    )\n"
    )


def _compose_note(state: AgentState, model_id: str, output_filename: str) -> Dict[str, Any]:
    """Synthesize the note's content from real observations + real citations."""
    citations = collected_citations(state)
    evidence = collected_ocr_text(state)
    spreadsheet = observations_for(state, "analyze_spreadsheet")
    primary = primary_input(state)

    if spreadsheet:
        evidence = (evidence + "\n\n" + json.dumps(spreadsheet[0], default=str)[:3000]).strip()

    citation_block = "\n".join(
        f"- [{c['clause']}] {c['content'][:300]} (Source: {c['source_file']}, Page {c['page_number']})"
        for c in citations
    ) or "(the local knowledge base returned no clauses)"

    system = (
        "You draft internal engineering approval notes for a plant. You work only "
        "from the evidence given. Reply with JSON only:\n"
        '{"purpose": "...", "findings": [{"item": "...", "detail": "...", '
        '"severity": "High|Medium|Low|Info", "evidence": "..."}], '
        '"recommended_action": "..."}\n'
        "Rules: never invent a measurement, component or clause that is not in the "
        "evidence. If the evidence is thin, say so in the finding detail. The "
        "recommended action must be an action for a human engineer to take, never "
        "an assertion that the work is approved."
    )
    user = (
        f"Task from the operator: {state.get('goal', '')}\n\n"
        f"Source document: {primary['filename'] if primary else 'none'}\n\n"
        f"Evidence extracted by the tools:\n{evidence or '(no text was extracted)'}\n\n"
        f"SOP clauses retrieved from the local knowledge base:\n{citation_block}\n\n"
        "Draft the note content."
    )

    drafted = chat_json(model_id, system, user, fallback=None, num_predict=1500, timeout=420.0)

    purpose = f"Support an engineer's decision on: {state.get('goal', '')}"
    findings: List[Dict[str, Any]] = []
    recommended = (
        "Route this note to an authorized engineer for review. No physical action "
        "should be taken on the basis of this draft alone."
    )

    if isinstance(drafted, dict):
        if isinstance(drafted.get("purpose"), str) and drafted["purpose"].strip():
            purpose = drafted["purpose"].strip()
        if isinstance(drafted.get("recommended_action"), str) and drafted["recommended_action"].strip():
            recommended = drafted["recommended_action"].strip()
        for raw in drafted.get("findings") or []:
            if not isinstance(raw, dict):
                continue
            findings.append({
                "item": str(raw.get("item", "Unspecified"))[:200],
                "detail": str(raw.get("detail", ""))[:800],
                "severity": str(raw.get("severity", "Info"))[:20],
                "evidence": str(raw.get("evidence", ""))[:300],
            })

    if not findings:
        findings = [{
            "item": primary["filename"] if primary else "Source document",
            "detail": "The local model produced no structured findings from the "
                      "extracted evidence. A human must read the source directly.",
            "severity": "Info",
            "evidence": f"{len(evidence)} characters of extracted text",
        }]

    ocr_results = observations_for(state, "run_ocr")
    source_metadata = {
        "source_file": primary["filename"] if primary else "none",
        "file_sha256": (primary or {}).get("sha256", "n/a"),
        "run_id": state["run_id"],
        "task_class": state.get("task_class", ""),
        "model_used": state.get("model_id", ""),
        "pages_processed": len(ocr_results) or "n/a",
        "mean_ocr_confidence": (
            round(sum(r.get("confidence", 0) for r in ocr_results) / len(ocr_results), 1)
            if ocr_results else "n/a"
        ),
        "generated_offline": "yes — no external service was contacted",
    }

    return {
        "output_filename": output_filename,
        "purpose": purpose,
        "source_metadata": source_metadata,
        "findings": findings,
        "sop_clauses": [
            {
                "clause": c["clause"],
                "content": c["content"],
                "source_file": c["source_file"],
                "page_number": c["page_number"],
            }
            for c in citations
        ],
        "recommended_action": recommended,
    }


def _approval_summary(state: AgentState) -> str:
    findings = state.get("findings") or []
    citations = state.get("citations") or []
    head = findings[0]["detail"] if findings else "A draft note has been generated."
    return (
        f"{head} "
        f"{len(findings)} finding(s), {len(citations)} SOP citation(s). {RISK_NOTICE}"
    )[:1000]


def answer_general_question(state: AgentState) -> str:
    """Plain-language answer for the general-reasoning class, grounded in the KB."""
    citations = collected_citations(state)
    context = "\n".join(
        f"- {c['content'][:400]} (Source: {c['source_file']}, Page {c['page_number']})"
        for c in citations
    ) or "(no local knowledge-base material matched this question)"

    # Data the tools actually read this turn, and what earlier turns produced.
    data_note = ""
    for result in observations_for(state, "analyze_spreadsheet"):
        rows = result.get("matched_rows") or []
        data_note += (
            f"\nSpreadsheet analysis ({result.get('interpretation', '')}): "
            f"{result.get('match_count', 0)} matching rows: "
            + "; ".join(", ".join(f"{k}={v}" for k, v in r.items()) for r in rows[:15])
            + f"\nColumn statistics: {json.dumps(result.get('column_statistics', {}), default=str)[:1500]}"
        )
    earlier = state.get("context") or ""

    try:
        return chat(
            state.get("model_id", "qwen3-8b"),
            system=(
                "You are an offline plant assistant. Answer using only the local "
                "context provided. Cite the source file and page when you use it. "
                "If the context does not answer the question, say so plainly."
            ),
            user=(
                (f"Earlier in this conversation:\n{earlier}\n\n" if earlier else "")
                + f"Question: {state.get('goal', '')}\n"
                + (f"\nData from the attached file:{data_note}\n" if data_note else "")
                + f"\nLocal context:\n{context}"
            ),
            num_predict=800,
            timeout=300.0,
        )
    except LocalModelError as e:
        return f"The local model was unavailable, so no answer could be produced: {e}"
